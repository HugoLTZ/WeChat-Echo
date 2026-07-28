"""
日志模块。

提供统一的日志记录，支持文件轮转和控制台输出。
"""

import logging
import logging.handlers
from pathlib import Path


# 日志格式
FILE_FORMAT = logging.Formatter(
    "%(asctime)s | %(levelname)-7s | %(module)s:%(lineno)d | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
CONSOLE_FORMAT = logging.Formatter(
    "%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5


def setup_logging(log_dir: str, level: str = "INFO") -> logging.Logger:
    """
    初始化日志系统。

    Args:
        log_dir: 日志文件存放目录。
        level: 日志级别（DEBUG / INFO / WARNING / ERROR）。

    Returns:
        根 logger 实例。
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("wechat_multi")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 避免重复添加 handler
    if root.handlers:
        return root

    # 文件 handler —— 自动轮转
    fh = logging.handlers.RotatingFileHandler(
        log_path / "app.log",
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(FILE_FORMAT)
    root.addHandler(fh)

    # 控制台 handler
    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, level.upper(), logging.INFO))
    ch.setFormatter(CONSOLE_FORMAT)
    root.addHandler(ch)

    return root


def get_logger(name: str = "") -> logging.Logger:
    """获取指定模块的 logger。"""
    if name:
        return logging.getLogger(f"wechat_multi.{name}")
    return logging.getLogger("wechat_multi")
