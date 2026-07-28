"""
微信多开免扫码登录工具 —— 程序入口。

架构：pywebview (HTML/CSS 前端) + Python (业务逻辑)
  - GUI: gui/index.html + gui/api.py
  - Core: core/ (account / credential / launcher / process_detector)
  - Config: config/settings.py
"""

import sys
import os
import ctypes
from pathlib import Path

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
        print("[WeChatMulti] 需要管理员权限（mklink 需要）。正在请求提权...")
        run_as_admin()
        sys.exit(0)

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
    logger.info("===== 微信多开助手 启动 =====")

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
        api.kill_all_wechat,
        api.get_settings_data,
        api.save_settings,
        api.select_file,
    ]

    class Api:
        """pywebview 要求暴露的方法必须绑定到实例上。"""
        pass

    api_obj = Api()
    for method in api_methods:
        setattr(api_obj, method.__name__, method)

    html_path = PROJECT_ROOT / "gui" / "index.html"
    html_content = html_path.read_text(encoding="utf-8")

    window = webview.create_window(
        title="微信多开助手",
        html=html_content,
        js_api=api_obj,
        width=660,
        height=720,
        min_size=(560, 500),
        text_select=False,
    )

    logger.info("GUI 已启动")
    webview.start(debug=False)
    logger.info("===== 微信多开助手 退出 =====")


if __name__ == "__main__":
    main()
