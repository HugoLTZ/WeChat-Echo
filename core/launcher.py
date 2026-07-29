"""
微信启动模块。

负责启动微信进程并实现多开。
"""

import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import psutil

from utils.logger import get_logger

logger = get_logger("launcher")

# 启动间隔（秒）：多个实例并发启动时的小间隔
LAUNCH_INTERVAL = 0.05
# 启动后等待（秒）：给微信进程足够时间读取凭证并完成初始化
# 时间太短会导致下一轮 mklink 切换时前一个实例还未读完凭证文件
POST_LAUNCH_DELAY = 5.0


class Launcher:
    """
    微信启动器。

    通过并发 Popen 方式实现多开：多个进程几乎同时启动，
    第一个创建互斥体但窗口尚未出现，后续进程检测到互斥体存在
    但 FindWindow 找不到已有窗口 → 正常启动。
    """

    def __init__(self, wechat_exe_path: str) -> None:
        self._exe = wechat_exe_path
        self._account_pids: dict[str, int] = {}  # account_id → 主进程 PID

    # ---- 属性 ----

    @property
    def exe_path(self) -> str:
        return self._exe

    @exe_path.setter
    def exe_path(self, v: str) -> None:
        self._exe = v

    # ---- 启动 ----

    def launch_single(self, account_id: str = "") -> Optional[subprocess.Popen]:
        """
        启动单个微信实例，追踪 PID 以支持在线状态检测和单独关闭。

        Args:
            account_id: 关联的账号 ID，用于后续追踪和单独关闭。

        Returns:
            Popen 对象，若失败则返回 None。
        """
        proc = self._spawn()
        if proc and account_id:
            self._account_pids[account_id] = proc.pid
            logger.debug("账号 %s 绑定 PID=%d", account_id, proc.pid)
        return proc

    def launch_multi(self, count: int, on_each: Optional[Callable[[int], None]] = None) -> list[subprocess.Popen]:
        """
        同时启动多个微信实例（多开）。

        Args:
            count: 要启动的实例数量。
            on_each: 每个实例启动后的回调，参数为序号（0-based）。

        Returns:
            成功启动的 Popen 对象列表。
        """
        launched: list[subprocess.Popen] = []

        def _launch_one(index: int) -> None:
            proc = self._spawn()
            if proc:
                launched.append(proc)
                if on_each:
                    on_each(index)

        threads = []
        for i in range(count):
            t = threading.Thread(target=_launch_one, args=(i,), daemon=True)
            t.start()
            threads.append(t)
            time.sleep(LAUNCH_INTERVAL)

        for t in threads:
            t.join(timeout=10)

        logger.info("多开完成：尝试 %d，成功 %d", count, len(launched))
        return launched

    def launch_sequential(
        self,
        count: int,
        between: Optional[Callable[[int], None]] = None,
        account_ids: Optional[list[str]] = None,
    ) -> list[subprocess.Popen]:
        """
        顺序启动多个微信实例，使用软链接实现凭证隔离。

        流程：
        1. 切换到账号 A 凭证（软链接）→ 启动微信 A → 等待微信 A 读取凭证
        2. 切换到账号 B 凭证（软链接可在文件被占用时删除重建）→ 启动微信 B
        3. 重复直到全部启动

        关键：每次启动后等待 3 秒，确保微信进程已完成凭证文件的打开和读取。
        软链接的优势：即使微信 A 持有文件句柄，软链接本身仍可被删除重建，
        不影响微信 A 的内存中的数据，同时微信 B 能通过新软链接读到自己的凭证。

        Args:
            count: 要启动的实例数量。
            between: 每次启动前的回调，参数为序号（0-based）。
            account_ids: 可选，与 count 等长的账号 ID 列表，用于 PID 追踪。

        Returns:
            成功启动的 Popen 对象列表。
        """
        PER_INSTANCE_DELAY = 3.0  # 等微信读完凭证文件

        launched = []
        for i in range(count):
            if between:
                between(i)
            proc = self._spawn()
            if proc:
                launched.append(proc)
                logger.debug("启动第 %d/%d 个实例 (PID=%d)", i + 1, count, proc.pid)
                if account_ids and i < len(account_ids):
                    self._account_pids[account_ids[i]] = proc.pid
            # 等当前微信读完凭证文件，再切软链接启动下一个
            if i < count - 1:
                time.sleep(PER_INSTANCE_DELAY)

        logger.info("批量启动完成：成功 %d/%d", len(launched), count)
        return launched

    # ---- 进程管理 ----

    def kill_account(self, account_id: str) -> bool:
        """
        终止指定账号的微信进程树（主进程 + 所有子进程）。

        Returns:
            是否成功终止（或进程已不存在）。
        """
        pid = self._account_pids.pop(account_id, None)
        if pid is None:
            return False
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                child.kill()
            parent.kill()
            psutil.wait_procs([parent] + children, timeout=5)
            logger.info("已终止账号 %s 的进程树 (PID=%d, 子进程=%d)", account_id, pid, len(children))
            return True
        except psutil.NoSuchProcess:
            logger.debug("账号 %s 的进程 PID=%d 已退出", account_id, pid)
            return True
        except psutil.AccessDenied:
            logger.warning("无法终止账号 %s 的进程 PID=%d (权限不足)", account_id, pid)
            return False

    def get_online_accounts(self) -> set[str]:
        """
        返回真正在线的账号 ID 集合（PID 存活 且 有主窗口）。
        仅进程存活但无主窗口的不算在线（仍在扫码等待中）。

        会清理已死亡的 PID 映射。
        """
        online: set[str] = set()
        dead: list[str] = []
        for aid, pid in self._account_pids.items():
            try:
                proc = psutil.Process(pid)
                if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                    dead.append(aid)
                    continue
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                dead.append(aid)
                continue
            # 进程存活，检查是否有主窗口（非登录窗口）
            if self._pid_has_main_window(pid):
                online.add(aid)
        for aid in dead:
            del self._account_pids[aid]
            logger.debug("账号 %s 的进程已退出，清理 PID 映射", aid)
        return online

    def get_launching_accounts(self) -> set[str]:
        """
        返回「启动中」的账号 ID 集合（PID 存活 但 尚无主窗口）。
        这些账号的微信进程在运行但可能还在扫码界面。
        """
        launching: set[str] = set()
        for aid, pid in self._account_pids.items():
            try:
                proc = psutil.Process(pid)
                if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                    if not self._pid_has_main_window(pid):
                        launching.add(aid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return launching

    @staticmethod
    def _pid_has_main_window(pid: int) -> bool:
        """检查指定 PID 是否有微信主窗口（大尺寸 + 可调大小，非登录窗口）。"""
        try:
            import win32gui
            import win32process
        except ImportError:
            return True  # 无法检测时乐观认为在线

        GWL_STYLE = -16
        WS_SIZEBOX = 0x00040000
        result = False

        def cb(hwnd: int, _ctx: None) -> bool:
            nonlocal result
            if result:
                return False
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                _, wpid = win32process.GetWindowThreadProcessId(hwnd)
                if wpid != pid:
                    return True
                title = win32gui.GetWindowText(hwnd)
                cls = win32gui.GetClassName(hwnd)
                if not (title == "微信" or cls.startswith("Qt5") or "WeChat" in cls):
                    return True
                rect = win32gui.GetWindowRect(hwnd)
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                if w <= 500 and h <= 500:
                    return True  # 登录窗口，跳过
                style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
                if style & WS_SIZEBOX:
                    result = True
                    return False
            except Exception:
                pass
            return True

        win32gui.EnumWindows(cb, None)
        return result

    # ---- 内部 ----

    def _spawn(self) -> Optional[subprocess.Popen]:
        """执行实际的 Popen 调用，附带 --multi 参数绕过单实例限制。"""
        exe_path = Path(self._exe)
        if not exe_path.is_file():
            logger.error("微信可执行文件不存在: %s", self._exe)
            return None
        try:
            proc = subprocess.Popen(
                [self._exe, "--multi"],
                cwd=str(exe_path.parent),
                shell=False,
            )
            logger.debug("微信进程已启动: PID=%d (--multi)", proc.pid)
            return proc
        except OSError as e:
            logger.error("启动微信失败: %s", e)
            return None
