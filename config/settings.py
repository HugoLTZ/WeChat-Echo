"""
应用配置管理模块。

管理应用级别的设置项（微信路径、数据目录、窗口状态等），
与账号数据（accounts.json）分离。
"""

import os
import json
import sys
import winreg
from pathlib import Path
from typing import Optional


# ---- 默认值 ----

def _default_wechat_exe() -> str:
    """探测微信安装路径：优先查注册表，其次默认路径。"""
    candidates = []
    # 注册表卸载信息（4.x 注册表项可能为 "WeChat" 或 "Weixin"）
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\WeChat",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\WeChat",
        ):
            try:
                with winreg.OpenKey(root, sub) as key:
                    loc = winreg.QueryValueEx(key, "InstallLocation")
                    if loc and loc[0]:
                        p = Path(loc[0])
                        # 4.x 使用 Weixin.exe，3.x 使用 WeChat.exe
                        for exe_name in ("Weixin.exe", "WeChat.exe"):
                            if (p / exe_name).is_file():
                                candidates.append(p / exe_name)
            except OSError:
                continue
    # 常见默认路径（4.x + 3.x）
    candidates.extend([
        Path(r"C:\Program Files\Tencent\Weixin\Weixin.exe"),
        Path(r"C:\Program Files (x86)\Tencent\Weixin\Weixin.exe"),
        Path(r"C:\Program Files\Tencent\WeChat\WeChat.exe"),
        Path(r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe"),
    ])
    for p in candidates:
        if p.is_file():
            return str(p)
    return str(candidates[0]) if candidates else ""


def _default_wechat_data_dir() -> str:
    """探测微信 4.x 数据目录（即 xwechat_files 的父目录）。"""
    # 可能的 xwechat_files 位置（4.x 可能直接在 Documents 下，或 WeChat Files 子目录）
    candidates = [
        Path.home() / "Documents",
        Path.home() / "Documents" / "WeChat Files",
    ]
    # 也尝试从 Weixin.exe 所在盘符的根目录查找
    exe_path = _default_wechat_exe()
    if exe_path:
        exe_dir = Path(exe_path).parent
        # 从安装目录推测数据目录（微信 4.x 安装目录和数据目录可能不在同盘）
        for parent in [exe_dir.parent, Path(exe_dir.drive + "\\")]:
            if parent not in candidates:
                candidates.append(parent)

    for c in candidates:
        xwechat_dir = c / "xwechat_files"
        if xwechat_dir.is_dir():
            return str(c)
    # 回退：返回 Documents（最常见情况）
    return str(Path.home() / "Documents")


def _default_root_data_dir() -> str:
    """本工具默认数据存储目录。"""
    return str(Path.home() / "Documents" / "WeChatMulti")


# ---- 默认配置 ----

DEFAULTS = {
    "wechat_exe_path": _default_wechat_exe(),
    "wechat_data_dir": _default_wechat_data_dir(),
    "root_data_dir": _default_root_data_dir(),
    "auto_start": False,
    "log_level": "INFO",
}

# 注册表 Run 键
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "WeChatMulti"


class Settings:
    """
    应用设置管理。

    存储位置：{root_data_dir}/config/settings.json
    """

    def __init__(self) -> None:
        self._data: dict = dict(DEFAULTS)
        self._file_path: Path = self._build_path()

    # ---- 路径 ----

    @property
    def settings_dir(self) -> Path:
        return Path(self._data["root_data_dir"]) / "config"

    @property
    def credentials_dir(self) -> Path:
        return Path(self._data["root_data_dir"]) / "credentials"

    @property
    def accounts_file(self) -> Path:
        return self.settings_dir / "accounts.json"

    @property
    def wechat_config_dir(self) -> Path:
        """微信 4.x 凭证文件所在目录。

        防呆：如果用户配置的 wechat_data_dir 末尾已含 xwechat_files，
        则不再重复拼接。
        """
        data_dir = Path(self._data["wechat_data_dir"])
        if data_dir.name.lower() == "xwechat_files":
            return data_dir / "all_users" / "config"
        return data_dir / "xwechat_files" / "all_users" / "config"

    # ---- 属性 ----

    @property
    def wechat_exe_path(self) -> str:
        return self._data["wechat_exe_path"]

    @wechat_exe_path.setter
    def wechat_exe_path(self, v: str) -> None:
        self._data["wechat_exe_path"] = v

    @property
    def wechat_data_dir(self) -> str:
        return self._data["wechat_data_dir"]

    @wechat_data_dir.setter
    def wechat_data_dir(self, v: str) -> None:
        self._data["wechat_data_dir"] = v

    @property
    def root_data_dir(self) -> str:
        return self._data["root_data_dir"]

    @root_data_dir.setter
    def root_data_dir(self, v: str) -> None:
        self._data["root_data_dir"] = v
        self._file_path = self._build_path()

    @property
    def auto_start(self) -> bool:
        return self._data["auto_start"]

    @auto_start.setter
    def auto_start(self, v: bool) -> None:
        self._data["auto_start"] = v
        if v:
            self._set_auto_start()
        else:
            self._remove_auto_start()

    @property
    def log_level(self) -> str:
        return self._data["log_level"]

    @log_level.setter
    def log_level(self, v: str) -> None:
        self._data["log_level"] = v

    # ---- I/O ----

    def _build_path(self) -> Path:
        return self.settings_dir / "settings.json"

    def load(self) -> None:
        """从文件加载设置，缺失项使用默认值。"""
        if self._file_path.is_file():
            try:
                with open(self._file_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # 合并：只覆盖已存在的键（不触发 setter 副作用）
                for k in DEFAULTS:
                    if k in saved:
                        self._data[k] = saved[k]
            except (json.JSONDecodeError, OSError):
                pass  # 文件损坏则使用默认值

    def sync_auto_start(self) -> None:
        """确保注册表自启状态与设置一致（程序启动时调用一次）。"""
        if self._data["auto_start"]:
            self._set_auto_start()
        else:
            self._remove_auto_start()

    def save(self) -> None:
        """保存设置到文件。"""
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get_all(self) -> dict:
        return dict(self._data)

    # ---- 开机自启（注册表） ----

    @staticmethod
    def _get_exe_path() -> str:
        """获取本程序的 exe 路径（兼容 PyInstaller 打包和源码运行）。"""
        if getattr(sys, "frozen", False):
            return sys.executable
        # 源码运行时，注册 pythonw 启动 main.py（不弹控制台窗口）
        pythonw = Path(sys.exec_prefix) / "pythonw.exe"
        main_script = Path(__file__).resolve().parent.parent / "main.py"
        return f'"{pythonw}" "{main_script}"'

    @staticmethod
    def _set_auto_start() -> None:
        """写入注册表 Run 键。"""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, Settings._get_exe_path())
        except OSError:
            pass  # 静默失败，不自启不影响主功能

    @staticmethod
    def _remove_auto_start() -> None:
        """从注册表 Run 键中删除。"""
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_WRITE) as key:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
        except OSError:
            pass


# 全局单例
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取 Settings 单例。"""
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.load()
    return _settings
