"""
WeChat-Echo免扫码登录工具 —— 程序入口。

架构：pywebview (HTML/CSS 前端) + Python (业务逻辑)
  - GUI: gui/index.html + gui/api.py
  - Core: core/ (account / credential / launcher / process_detector)
  - Config: config/settings.py
"""

import sys
import os
import ctypes
from pathlib import Path

# 打包后资源路径适配
if getattr(sys, "frozen", False):
    # PyInstaller / Nuitka 使用 sys._MEIPASS
    if hasattr(sys, "_MEIPASS"):
        PROJECT_ROOT = Path(sys._MEIPASS)
    else:
        # cx_Freeze 等：exe 所在目录即根目录
        PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def run_as_admin() -> None:
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable,
        " ".join(f'"{a}"' for a in sys.argv),
        str(PROJECT_ROOT), 1,
    )


def main() -> None:
    # -- 管理员权限 --
    if not is_admin():
        # cx_Freeze 打包后无法自动提权，提示用户手动以管理员运行
        import tkinter.messagebox as mb
        mb.showerror(
            "需要管理员权限",
            "请右键 WeChat-Echo.exe → 以管理员身份运行\n\n（mklink 命令需要管理员权限）"
        )
        sys.exit(1)

    # -- 初始化配置 --
    from config.settings import get_settings
    settings = get_settings()
    settings.sync_auto_start()

    # -- 初始化日志 --
    from utils.logger import setup_logging, get_logger
    setup_logging(
        str(Path(settings.root_data_dir) / "logs"),
        settings.log_level,
    )
    logger = get_logger("main")
    logger.info("===== WeChat-Echo 启动 =====")

    # -- 初始化核心模块 --
    from core.account_manager import AccountManager
    from core.credential_manager import CredentialManager
    from core.launcher import Launcher
    from core.process_detector import ProcessDetector

    account_mgr = AccountManager(settings.accounts_file, settings.credentials_dir)
    account_mgr.load()

    credential_mgr = CredentialManager(settings.wechat_config_dir)
    launcher = Launcher(settings.wechat_exe_path)
    detector = ProcessDetector()

    logger.info(
        "初始化完成 | 微信: %s | 账号: %d | 进程: %d",
        settings.wechat_exe_path,
        len(account_mgr.list_all()),
        detector.count(),
    )

    # -- 注入到 API 桥接层 --
    import gui.api as api
    api.settings = settings
    api.account_mgr = account_mgr
    api.credential_mgr = credential_mgr
    api.launcher = launcher

    # -- 启动 WebView GUI --
    import webview
    import json

    # 暴露给 JS 的方法列表
    api_methods = [
        api.get_accounts,
        api.add_account,
        api.delete_account,
        api.search_accounts,
        api.backup_credentials,
        api.launch_account,
        api.launch_all,
        api.get_status,
        api.refresh_online_status,
        api.kill_all_wechat,
        api.kill_account,
        api.get_settings_data,
        api.save_settings,
        api.select_file,
        api.update_wechat_name,
        api.move_window_by,
        api.close_window,
        api.export_logs,
    ]

    class Api:
        """pywebview 要求暴露的方法必须绑定到实例上。"""
        pass

    api_obj = Api()
    for method in api_methods:
        setattr(api_obj, method.__name__, method)

    html_path = PROJECT_ROOT / "gui" / "index.html"
    html_content = html_path.read_text(encoding="utf-8")

    # 注入资源图标 base64
    import base64
    assets_dir = PROJECT_ROOT / "assets"
    icons = {
        "{{SETTING_ICON}}": "setting_selected.png",
        "{{CLOSE_ICON}}": "close_selected.png",
        "{{TITLE_LOGO}}": "title_1.png",
        "{{ICON_RUN}}": "run.png",
        "{{ICON_SAVE}}": "save.png",
        "{{ICON_DELETE}}": "delete.png",
        "{{ICON_MORE}}": "more.png",
        "{{CHAT_ICON}}": "chat.png",
    }
    for placeholder, filename in icons.items():
        p = assets_dir / filename
        if p.is_file():
            b64 = base64.b64encode(p.read_bytes()).decode()
            html_content = html_content.replace(placeholder, f"data:image/png;base64,{b64}")

    # 计算屏幕居中位置
    screen_w = ctypes.windll.user32.GetSystemMetrics(0)
    screen_h = ctypes.windll.user32.GetSystemMetrics(1)
    win_w, win_h = 440, 620
    x = (screen_w - win_w) // 2
    y = (screen_h - win_h) // 2

    window = webview.create_window(
        title="WeChat-Echo",
        html=html_content,
        js_api=api_obj,
        width=win_w,
        height=win_h,
        x=x,
        y=y,
        frameless=True,
        resizable=False,
        text_select=False,
        easy_drag=False,
    )

    logger.info("GUI 已启动")
    webview.start(debug=False)
    logger.info("===== WeChat-Echo 退出 =====")


if __name__ == "__main__":
    main()
