"""
微信启动模块。

负责启动微信进程并实现多开。
"""

import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

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
        self._processes: list[subprocess.Popen] = []

    # ---- 属性 ----

    @property
    def exe_path(self) -> str:
        return self._exe

    @exe_path.setter
    def exe_path(self, v: str) -> None:
        self._exe = v

    # ---- 启动 ----

    def launch_single(self) -> Optional[subprocess.Popen]:
        """
        启动单个微信实例。

        Returns:
            Popen 对象，若失败则返回 None。
        """
        return self._spawn()

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

    def launch_sequential(self, count: int, between: Optional[Callable[[int], None]] = None) -> list[subprocess.Popen]:
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
            # 等当前微信读完凭证文件，再切软链接启动下一个
            if i < count - 1:
                time.sleep(PER_INSTANCE_DELAY)

        logger.info("批量启动完成：成功 %d/%d", len(launched), count)
        return launched

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
