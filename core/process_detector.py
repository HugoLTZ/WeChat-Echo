"""
进程检测模块。

检测微信进程运行状态：是否运行、运行数量、在线状态。

关键区分：微信 4.x 是多进程架构（类似 Chrome），一个可见窗口会
衍生多个 Weixin.exe 子进程。本模块通过「窗口可见性」区分主实例进程
和后台 worker 进程，确保计数准确。
"""

import time
from collections.abc import Callable
from typing import Optional

import psutil
import win32gui
import win32process

from utils.logger import get_logger

logger = get_logger("process_detector")

# 微信进程名
_WECHAT_MAIN_NAMES = {"weixin.exe", "wechat.exe"}
_WECHAT_SUB_NAMES = {"wechatappex.exe", "wechatweb.exe"}

# 微信 4.x 主窗口特征（用于区分主进程和后台子进程）
_WECHAT_WINDOW_TITLE = "微信"
_WECHAT_WINDOW_CLASS_PREFIXES = ("Qt5", "WeChatMainWndForPC", "WeChatLoginWndForPC")

# 微信同时在线上限
MAX_INSTANCES = 4


# ---- 窗口枚举辅助 ----

def _get_main_wechat_pids() -> set[int]:
    """
    枚举所有可见窗口，返回属于微信主实例的 PID 集合。

    通过窗口可见性 + 窗口标题/类名筛选，排除后台 worker 进程。
    """
    main_pids: set[int] = set()
    # 缓存：避免对同一 PID 重复调用 psutil
    checked_pids: dict[int, bool] = {}

    def enum_callback(hwnd: int, _ctx: None) -> bool:
        # 只关注可见窗口
        if not win32gui.IsWindowVisible(hwnd):
            return True

        title = win32gui.GetWindowText(hwnd)
        class_name = win32gui.GetClassName(hwnd)

        # 窗口标题匹配
        is_wechat_title = (title == _WECHAT_WINDOW_TITLE)
        # 窗口类名匹配（Qt5 前缀或旧版固定类名）
        is_wechat_class = any(
            class_name.startswith(prefix) for prefix in _WECHAT_WINDOW_CLASS_PREFIXES
        )

        if not (is_wechat_title or is_wechat_class):
            return True

        # 获取窗口所属 PID
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid == 0:
            return True

        # 缓存检查：该 PID 是否真的是微信进程
        if pid not in checked_pids:
            try:
                proc = psutil.Process(pid)
                checked_pids[pid] = proc.name().lower() in _WECHAT_MAIN_NAMES
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                checked_pids[pid] = False

        if checked_pids[pid]:
            main_pids.add(pid)

        return True

    win32gui.EnumWindows(enum_callback, None)
    return main_pids


# ---- 检测器 ----

class ProcessDetector:
    """微信进程检测器。"""

    @staticmethod
    def get_wechat_processes() -> list[psutil.Process]:
        """获取所有微信主进程（有可见窗口的实例，不含 worker 子进程）。"""
        main_pids = _get_main_wechat_pids()
        procs = []
        for p in psutil.process_iter(["name"]):
            try:
                if p.pid in main_pids:
                    procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return procs

    @staticmethod
    def get_all_wechat_processes() -> list[psutil.Process]:
        """获取所有微信进程（含子进程 / worker）。"""
        procs = []
        all_names = _WECHAT_MAIN_NAMES | _WECHAT_SUB_NAMES
        for p in psutil.process_iter(["name"]):
            try:
                name = (p.info["name"] or "").lower()
                if name in all_names:
                    procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return procs

    @staticmethod
    def count() -> int:
        """正在运行的微信主实例数（一个窗口 = 一个实例）。"""
        return len(_get_main_wechat_pids())

    @staticmethod
    def is_running() -> bool:
        """是否有微信实例在运行。"""
        return len(_get_main_wechat_pids()) > 0

    @staticmethod
    def remaining_slots() -> int:
        """还能再启动几个微信实例。"""
        return max(0, MAX_INSTANCES - len(_get_main_wechat_pids()))

    @staticmethod
    def can_launch() -> bool:
        """是否还能启动新实例。"""
        return len(_get_main_wechat_pids()) < MAX_INSTANCES

    # ---- 工具方法 ----

    @staticmethod
    def kill_all() -> int:
        """终止所有微信进程（含子进程），返回终止数量。"""
        killed = 0
        for p in ProcessDetector.get_all_wechat_processes():
            try:
                p.kill()
                killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if killed:
            logger.info("已终止 %d 个微信进程", killed)
        return killed

    @staticmethod
    def wait_for_exit(timeout: float = 10.0, callback: Optional[Callable[[int], None]] = None) -> bool:
        """
        等待所有微信进程退出。

        Args:
            timeout: 超时秒数。
            callback: 每次检查的回调，参数为剩余进程数。

        Returns:
            是否在超时前全部退出。
        """
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            count = len(_get_main_wechat_pids())
            if count == 0:
                return True
            if callback:
                callback(count)
            time.sleep(0.5)
        return len(_get_main_wechat_pids()) == 0

    @staticmethod
    def pid_has_main_window(pid: int) -> bool:
        """
        检查指定 PID 是否有可见的微信主窗口（非登录窗口）。

        主窗口特征：可见 + 微信标题/类名 + 尺寸大（宽或高 > 500）+ 可调大小。
        登录窗口（~370×485，无 WS_SIZEBOX）不会被计入。
        """
        GWL_STYLE = -16
        WS_SIZEBOX = 0x00040000
        result = False

        def cb(hwnd: int, _ctx: None) -> bool:
            nonlocal result
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                _, hwnd_pid = win32process.GetWindowThreadProcessId(hwnd)
                if hwnd_pid != pid:
                    return True
                title = win32gui.GetWindowText(hwnd)
                cls = win32gui.GetClassName(hwnd)
                if not (title == "微信" or cls.startswith("Qt5") or "WeChat" in cls):
                    return True
                rect = win32gui.GetWindowRect(hwnd)
                w, h = rect[2] - rect[0], rect[3] - rect[1]
                if w <= 500 and h <= 500:
                    return True
                style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
                if style & WS_SIZEBOX:
                    result = True
                    return False  # 找到，停止枚举
            except Exception:
                pass
            return True

        win32gui.EnumWindows(cb, None)
        return result
