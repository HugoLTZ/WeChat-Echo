"""
微信启动模块。

负责启动微信进程并实现多开。
"""

import hashlib
import json
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

    def __init__(self, wechat_exe_path: str, data_dir: str = "") -> None:
        self._exe = wechat_exe_path
        self._account_pids: dict[str, int] = {}  # account_id → 主进程 PID
        if data_dir:
            self._pid_file = Path(data_dir) / "pid_map.json"
        else:
            self._pid_file = Path("pid_map.json")
        self._load_pids()

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
            self._save_pids()
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
                    self._save_pids()
            # 等当前微信读完凭证文件，再切软链接启动下一个
            if i < count - 1:
                time.sleep(PER_INSTANCE_DELAY)

        logger.info("批量启动完成：成功 %d/%d", len(launched), count)
        return launched

    # ---- 进程管理 ----

    @staticmethod
    def _is_wechat_pid(pid: int) -> bool:
        """验证 PID 是否仍属于微信进程（防止 PID 被 OS 回收后误判到其他程序）。"""
        try:
            proc = psutil.Process(pid)
            if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                return False
            name = proc.name().lower()
            return "wechat" in name or "weixin" in name
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    @staticmethod
    def _get_all_wechat_pids() -> set[int]:
        """通过窗口枚举获取所有微信主进程 PID（高效，不走 psutil.process_iter）。"""
        try:
            import win32gui
            import win32process
        except ImportError:
            return set()
        pids: set[int] = set()
        def cb(hwnd: int, _ctx: None) -> bool:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            cls = win32gui.GetClassName(hwnd)
            if not (title == "微信" or cls.startswith("Qt5") or "WeChat" in cls):
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid:
                pids.add(pid)
            return True
        try:
            win32gui.EnumWindows(cb, None)
        except Exception:
            logger.debug("EnumWindows 异常")
        return pids

    def kill_account(self, account_id: str) -> bool:
        """
        终止指定账号的微信进程树（主进程 + 所有子进程）。

        安全措施：先验证 PID 是否仍属于微信进程再 kill，
        防止 PID 被 OS 回收给其他程序后误杀无辜进程。
        """
        pid = self._account_pids.pop(account_id, None)
        if pid is None:
            return False
        self._save_pids()
        # 关键校验：PID 可能已被回收给其他程序
        if not self._is_wechat_pid(pid):
            logger.warning("账号 %s 的 PID=%d 已不属于微信进程（被 OS 回收），跳过 kill", account_id, pid)
            return True
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

        会清理已死亡或 PID 被 OS 回收的映射。
        """
        online: set[str] = set()
        dead: list[str] = []
        for aid, pid in self._account_pids.items():
            try:
                if not self._is_wechat_pid(pid):
                    dead.append(aid)
                    continue
                if self._pid_has_main_window(pid):
                    online.add(aid)
            except Exception:
                logger.debug("账号 %s PID=%d 状态检测异常，跳过", aid, pid)
        for aid in dead:
            del self._account_pids[aid]
            logger.debug("账号 %s 的进程已退出或 PID 被回收，清理映射", aid)
        if dead:
            self._save_pids()
        return online

    def get_launching_accounts(self) -> set[str]:
        """
        返回「启动中」的账号 ID 集合（PID 存活 但 尚无主窗口）。
        这些账号的微信进程在运行但可能还在扫码界面。
        """
        launching: set[str] = set()
        for aid, pid in self._account_pids.items():
            try:
                if not self._is_wechat_pid(pid):
                    continue
                if not self._pid_has_main_window(pid):
                    launching.add(aid)
            except Exception:
                logger.debug("账号 %s PID=%d 启动检测异常，跳过", aid, pid)
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

        try:
            win32gui.EnumWindows(cb, None)
        except Exception:
            logger.debug("EnumWindows 异常 (PID=%d)，返回当前检测结果=%s", pid, result)
        return result

    # ---- 孤儿进程收养 ----

    def adopt_orphan_processes(self, wechat_data_dir: str, account_cred_dirs: dict[str, str]) -> int:
        """
        通过头像比对匹配孤儿微信进程到账号。

        策略：
        1. 扫描 xwechat_files/all_users/head_imgs/ 下所有头像文件
        2. 与各账号备份的 avatar.jpg 做 MD5 比对
        3. 头像匹配 + 有孤儿主窗口 PID → 收养

        相比 global_config hash 的优势：每个账号头像唯一，不受 config 目录
        被多实例覆盖的影响。

        Args:
            wechat_data_dir: 微信数据根目录（即 xwechat_files 的父目录）
            account_cred_dirs: {account_id: credential_backup_dir} 映射。

        Returns:
            成功收养的进程数。
        """
        all_pids = self._get_all_wechat_pids()
        tracked = set(self._account_pids.values())
        orphans = all_pids - tracked
        logger.info("孤儿检测: 全部微信PID=%s 已追踪=%s 孤儿=%s", all_pids, tracked, orphans)
        if not orphans:
            return 0

        # 收集有主窗口的孤儿 PID
        orphan_pids: list[int] = []
        for pid in orphans:
            try:
                if self._pid_has_main_window(pid):
                    orphan_pids.append(pid)
                    logger.info("孤儿 PID=%d 主窗口=True", pid)
                else:
                    logger.info("孤儿 PID=%d 主窗口=False（登录界面，跳过）", pid)
            except Exception:
                logger.debug("孤儿 PID=%d 窗口检测失败，跳过", pid)

        if not orphan_pids:
            logger.info("无可收养的孤儿进程（均无主窗口）")
            return 0

        # 扫描微信头像目录，收集当前活跃头像的 MD5
        head_imgs_dir = Path(wechat_data_dir) / "xwechat_files" / "all_users" / "head_imgs"
        active_avatars: set[str] = set()  # MD5 hex 集合
        if head_imgs_dir.is_dir():
            for d in head_imgs_dir.iterdir():
                if d.is_dir():
                    for f in d.iterdir():
                        if f.is_file():
                            try:
                                active_avatars.add(hashlib.md5(f.read_bytes()).hexdigest())
                            except OSError:
                                pass
        logger.info("头像目录 %s → 找到 %d 个头像文件", head_imgs_dir, len(active_avatars))

        if not active_avatars:
            logger.info("微信头像目录无头像文件，无法匹配")
            return 0

        # 为每个账号计算其备份头像的 MD5
        account_avatars: dict[str, str] = {}  # account_id → avatar_md5
        for aid, cred_dir in account_cred_dirs.items():
            avatar = Path(cred_dir) / "avatar.jpg"
            if avatar.is_file():
                try:
                    account_avatars[aid] = hashlib.md5(avatar.read_bytes()).hexdigest()
                except OSError:
                    pass

        if not account_avatars:
            logger.info("无账号有备份头像，无法匹配")
            return 0

        # 匹配：头像 MD5 一致 + 有孤儿 PID → 收养
        adopted = 0
        remaining_pids = list(orphan_pids)
        for aid, avatar_hash in account_avatars.items():
            if aid in self._account_pids:
                continue
            if avatar_hash in active_avatars:
                if remaining_pids:
                    pid = remaining_pids.pop(0)
                    self._account_pids[aid] = pid
                    self._save_pids()
                    logger.info("收养孤儿进程 PID=%d → 账号 %s (头像匹配)", pid, aid)
                    adopted += 1
                else:
                    logger.info("账号 %s 头像匹配但无剩余孤儿 PID", aid)
            else:
                logger.info("账号 %s 头像未匹配 (hash=%s)", aid, avatar_hash[:8])

        return adopted

    # ---- PID 持久化 ----

    def _save_pids(self) -> None:
        """将 account_id → pid 映射持久化到 JSON 文件。"""
        try:
            self._pid_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._pid_file, "w", encoding="utf-8") as f:
                json.dump(self._account_pids, f, ensure_ascii=False, indent=2)
            logger.debug("PID 映射已保存 (%d 条)", len(self._account_pids))
        except OSError as e:
            logger.warning("保存 PID 映射失败: %s", e)

    def _load_pids(self) -> None:
        """
        从 JSON 文件恢复 PID 映射。
        仅恢复仍存活且属于微信进程的 PID，已失效的自动丢弃。
        """
        if not self._pid_file.is_file():
            logger.debug("PID 映射文件不存在，跳过恢复: %s", self._pid_file)
            return
        try:
            with open(self._pid_file, "r", encoding="utf-8") as f:
                saved: dict[str, int] = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("加载 PID 映射失败: %s", e)
            return

        logger.info("PID 映射文件中有 %d 条记录，开始验证...", len(saved))
        restored = 0
        for aid, pid in saved.items():
            if not self._is_wechat_pid(pid):
                logger.debug("恢复 PID 跳过: %s PID=%d", aid, pid)
                continue
            self._account_pids[aid] = pid
            restored += 1

        if restored:
            logger.info("已恢复 %d 条 PID 映射", restored)
            self._save_pids()  # 清理已失效的条目后重新保存

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
