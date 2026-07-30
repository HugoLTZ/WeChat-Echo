"""
pywebview JS-Python 桥接 API。

前端通过 window.pywebview.api.xxx() 调用这些方法。
所有方法返回 JSON 可序列化的数据（dict / list / str / bool / int）。
"""

import threading
from pathlib import Path
from datetime import datetime
from typing import Any

from config.settings import get_settings, Settings
from core.account_manager import AccountManager, Account
from core.credential_manager import CredentialManager
from core.launcher import Launcher
from core.process_detector import ProcessDetector

from utils.logger import get_logger

logger = get_logger("api")

# 模块级单例，在 main.py 中注入
settings: Settings = None       # type: ignore[assignment]
account_mgr: AccountManager = None  # type: ignore[assignment]
credential_mgr: CredentialManager = None  # type: ignore[assignment]
launcher: Launcher = None       # type: ignore[assignment]

# 自动备份完成标记，前端检测后刷新列表
_needs_refresh = False


def _acc_to_dict(acc: Account) -> dict[str, Any]:
    display_title = acc.wechat_name or acc.wxid_display or acc.name
    return {
        "id": acc.id,
        "name": acc.name,
        "remark": acc.remark,
        "wxid": acc.wxid,
        "wxid_display": acc.wxid_display,
        "wechat_name": acc.wechat_name,
        "display_title": display_title,
        "has_wechat_name": bool(acc.wechat_name),
        "avatar_base64": _get_avatar_base64(acc),
        "has_credentials": acc.has_credentials,
        "credential_status": acc.credential_status,
        "last_login": acc.last_login,
        "last_login_text": _format_last_login(acc.last_login),
        "is_online": acc.is_online,
        "is_launching": acc.is_launching,
    }


def _format_last_login(last_login: str) -> str:
    """将时间戳转为相对时间文本。"""
    if not last_login:
        return "从未登录"
    try:
        dt = datetime.strptime(last_login, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return last_login
    now = datetime.now()
    delta = now - dt
    days = delta.days
    if days == 0 and dt.date() == now.date():
        return "今天"
    elif days == 1 or (days == 0 and dt.date() != now.date()):
        return "昨天"
    elif days <= 7:
        return "最近"
    elif days <= 30:
        return "一月内"
    else:
        return "很久以前"


def _get_avatar_base64(acc: Account) -> str:
    """读取头像文件并返回 base64 data URI 字符串，无头像时返回空。"""
    if not acc.avatar_path:
        return ""
    import base64
    try:
        data = Path(acc.avatar_path).read_bytes()
        return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
    except (OSError, ValueError):
        return ""


# ---- 账号管理 ----

def get_accounts() -> list[dict[str, Any]]:
    """获取所有账号列表。"""
    return [_acc_to_dict(a) for a in account_mgr.list_all()]


def add_account(name: str, remark: str = "") -> dict[str, Any]:
    """添加账号。"""
    acc = account_mgr.add(name, remark)
    return _acc_to_dict(acc)


def delete_account(account_id: str, delete_credentials: bool = False) -> bool:
    """删除账号。"""
    if delete_credentials:
        acc = account_mgr.get(account_id)
        if acc:
            credential_mgr.delete_backup(Path(acc.credential_dir))
    return account_mgr.remove(account_id)


def search_accounts(keyword: str) -> list[dict[str, Any]]:
    """搜索账号。"""
    return [_acc_to_dict(a) for a in account_mgr.search(keyword)]


# ---- 凭证操作 ----

def backup_credentials(account_id: str) -> dict[str, Any]:
    """备份当前微信的凭证到指定账号。"""
    acc = account_mgr.get(account_id)
    if not acc:
        return {"ok": False, "msg": "账号不存在"}
    if not ProcessDetector.is_running():
        return {"ok": False, "msg": "未检测到微信进程，请先在微信中扫码登录"}
    ok = credential_mgr.backup(Path(acc.credential_dir))
    if ok:
        account_mgr.refresh_wxid(account_id)
        return {"ok": True, "msg": f"「{acc.name}」的凭证已备份，下次启动将免扫码登录"}
    return {"ok": False, "msg": "备份失败，请确认微信已扫码登录"}


# ---- 启动 ----

def launch_account(account_id: str) -> dict[str, Any]:
    """启动单个账号的微信实例。"""
    acc = account_mgr.get(account_id)
    if not acc:
        return {"ok": False, "msg": "账号不存在"}

    if not ProcessDetector.can_launch():
        logger.warning("启动失败：已达同时在线上限 (%d/4)", ProcessDetector.count())
        return {"ok": False, "msg": f"同时在线上限为 4 个，当前已有 {ProcessDetector.count()} 个在运行"}

    if acc.has_credentials:
        if not credential_mgr.switch_to(Path(acc.credential_dir)):
            logger.error("凭证切换失败: %s", acc.id)
            return {"ok": False, "msg": "凭证切换失败"}
        if not credential_mgr.verify_switch(Path(acc.credential_dir)):
            logger.error("凭证切换验证失败: %s", acc.id)
            return {"ok": False, "msg": "凭证切换验证失败，请重新备份凭证"}

    proc = launcher.launch_single(acc.id)
    if proc:
        account_mgr.mark_logged_in(acc.id)

        if not acc.has_credentials:
            cred_dir = Path(acc.credential_dir)
            acc_id = acc.id
            logger.info("启动无凭证账号「%s」，开始自动备份监控", acc.name)

            def _auto_backup() -> None:
                ok = credential_mgr.wait_and_backup(cred_dir, timeout=300, interval=5)
                if ok:
                    account_mgr.refresh_wxid(acc_id)
                    global _needs_refresh
                    _needs_refresh = True

            threading.Thread(target=_auto_backup, daemon=True).start()
            return {"ok": True, "msg": f"已启动「{acc.name}」，扫码登录后将自动备份凭证"}

        logger.info("已启动「%s」", acc.name)
        return {"ok": True, "msg": f"已启动「{acc.name}」"}

    logger.error("启动微信失败: %s", settings.wechat_exe_path)
    return {"ok": False, "msg": "启动微信失败，请检查微信路径"}


def launch_all() -> dict[str, Any]:
    """一键启动所有已备份凭证的账号（多开）。"""
    accounts = account_mgr.list_all()
    ready = [a for a in accounts if a.has_credentials]
    # 按凭证更新时间从旧到新排序（先注册的账号先启动）
    ready.sort(key=lambda a: a.last_login or "")
    if not ready:
        return {"ok": False, "msg": "没有已备份凭证的账号"}

    slots = ProcessDetector.remaining_slots()
    if len(ready) > slots:
        return {"ok": False, "msg": f"已备份 {len(ready)} 个账号，但仅剩 {slots} 个上线名额"}

    def on_before_launch(index: int) -> None:
        acc = ready[index]
        credential_mgr.switch_to_symlink(Path(acc.credential_dir))

    ids = [a.id for a in ready]
    procs = launcher.launch_sequential(len(ready), between=on_before_launch, account_ids=ids)
    for acc in ready:
        account_mgr.mark_logged_in(acc.id)

    return {"ok": True, "msg": f"已启动 {len(procs)}/{len(ready)} 个微信实例"}


def refresh_online_status() -> list[str]:
    """
    通过 PID 追踪精确刷新各账号状态：在线 / 启动中 / 离线。
    同时尝试收养未被追踪的孤儿微信进程。
    返回当前在线的 account_id 列表。
    """
    # 尝试收养孤儿进程（用户手动启动的微信等）
    logger.info("当前追踪 PID: %s (%d 条)", dict(launcher._account_pids), len(launcher._account_pids))
    cred_dirs: dict[str, str] = {}
    for acc in account_mgr.list_all():
        if acc.has_credentials and acc.id not in launcher._account_pids:
            cred_dirs[acc.id] = acc.credential_dir
    if cred_dirs:
        logger.info("尝试收养孤儿进程，候选账号: %s", list(cred_dirs.keys()))
        try:
            adopted = launcher.adopt_orphan_processes(
                settings.wechat_data_dir,
                cred_dirs,
            )
            if adopted:
                logger.info("收养了 %d 个孤儿微信进程", adopted)
        except Exception:
            logger.warning("孤儿进程收养失败（非关键路径）", exc_info=True)
    else:
        logger.info("无需收养：所有有凭证的账号均已追踪 PID")

    online_ids = launcher.get_online_accounts()
    launching_ids = launcher.get_launching_accounts()
    for acc in account_mgr.list_all():
        acc.is_online = acc.id in online_ids
        acc.is_launching = acc.id in launching_ids
    try:
        total = ProcessDetector.count()
    except Exception:
        total = len(online_ids) + len(launching_ids)  # 回退：用已知 PID 数估算
    if total == 0:
        for acc in account_mgr.list_all():
            acc.is_online = False
            acc.is_launching = False
        return []
    return list(online_ids)


# ---- 进程状态 ----

def update_wechat_name(account_id: str, wechat_name: str) -> bool:
    """更新账号的微信名。"""
    return account_mgr.update(account_id, wechat_name=wechat_name)


def get_status() -> dict[str, Any]:
    """获取当前状态摘要。"""
    global _needs_refresh
    result = {
        "wechat_count": ProcessDetector.count(),
        "wechat_running": ProcessDetector.is_running(),
        "remaining_slots": ProcessDetector.remaining_slots(),
        "can_launch": ProcessDetector.can_launch(),
        "total_accounts": len(account_mgr.list_all()),
        "needs_refresh": _needs_refresh,
    }
    _needs_refresh = False  # 已通知前端，重置
    return result


def kill_account(account_id: str) -> dict[str, Any]:
    """单独关闭指定账号的微信进程。"""
    acc = account_mgr.get(account_id)
    if not acc:
        return {"ok": False, "msg": "账号不存在"}
    acc.is_online = False
    if launcher.kill_account(account_id):
        return {"ok": True, "msg": f"已关闭「{acc.name}」"}
    return {"ok": False, "msg": "该账号未在运行"}


def kill_all_wechat() -> dict[str, Any]:
    """关闭全部微信进程。"""
    count = ProcessDetector.count()
    if count == 0:
        return {"ok": True, "msg": "当前无微信进程"}
    killed = ProcessDetector.kill_all()
    for acc in account_mgr.list_all():
        acc.is_online = False
    return {"ok": True, "msg": f"已关闭 {killed} 个微信进程"}


# ---- 设置 ----

def get_settings_data() -> dict[str, Any]:
    """获取所有设置项。"""
    s = settings
    return {
        "wechat_exe_path": s.wechat_exe_path,
        "wechat_data_dir": s.wechat_data_dir,
        "root_data_dir": s.root_data_dir,
        "auto_start": s.auto_start,
        "log_level": s.log_level,
    }


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    """保存设置。"""
    try:
        if "wechat_exe_path" in data:
            settings.wechat_exe_path = data["wechat_exe_path"]
            launcher.exe_path = data["wechat_exe_path"]
        if "wechat_data_dir" in data:
            settings.wechat_data_dir = data["wechat_data_dir"]
            credential_mgr.wechat_config_dir = (
                Path(data["wechat_data_dir"]) / "xwechat_files" / "all_users" / "config"
            )
        if "root_data_dir" in data:
            settings.root_data_dir = data["root_data_dir"]
        if "auto_start" in data:
            settings.auto_start = data["auto_start"]
        if "log_level" in data:
            settings.log_level = data["log_level"]
        settings.save()
        logger.info("设置已更新")
        return {"ok": True, "msg": "设置已保存"}
    except Exception as e:
        logger.error("保存设置失败: %s", e)
        return {"ok": False, "msg": str(e)}


def export_logs() -> dict[str, Any]:
    """导出日志文件为 zip 压缩包。"""
    import tkinter.filedialog as fd
    import tkinter as tk
    import zipfile
    from datetime import datetime

    log_dir = Path(settings.root_data_dir) / "logs"
    if not log_dir.is_dir():
        return {"ok": False, "msg": "日志目录不存在"}

    log_files = sorted(log_dir.glob("app.log*"))
    if not log_files:
        return {"ok": False, "msg": "没有日志文件可导出"}

    # 打开保存对话框
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    default_name = f"WeChat-Echo-logs-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    path = fd.asksaveasfilename(
        title="导出日志",
        defaultextension=".zip",
        filetypes=[("ZIP 压缩包", "*.zip")],
        initialfile=default_name,
    )
    root.destroy()
    if not path:
        return {"ok": False, "msg": "已取消"}

    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in log_files:
                zf.write(f, f.name)
        logger.info("日志已导出: %s (%d 个文件)", path, len(log_files))
        return {"ok": True, "msg": f"已导出 {len(log_files)} 个日志文件"}
    except OSError as e:
        return {"ok": False, "msg": f"导出失败: {e}"}


_win_pos: tuple[int, int] = (0, 0)


def close_window() -> None:
    """关闭窗口（通过 Win32 WM_CLOSE 立即生效）。"""
    import ctypes
    hwnd = ctypes.windll.user32.FindWindowW(None, "WeChat-Echo")
    if hwnd:
        # WM_CLOSE = 0x0010
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)


def move_window_by(dx: int, dy: int) -> None:
    """相对移动窗口。"""
    import ctypes
    global _win_pos
    hwnd = ctypes.windll.user32.FindWindowW(None, "WeChat-Echo")
    if hwnd:
        rect = ctypes.create_string_buffer(16)
        ctypes.windll.user32.GetWindowRect(hwnd, rect)
        x = int.from_bytes(rect[0:4], 'little', signed=True)
        y = int.from_bytes(rect[4:8], 'little', signed=True)
        ctypes.windll.user32.SetWindowPos(hwnd, 0, x + dx, y + dy, 0, 0, 0x0001)


def select_file(title: str, file_types: str = "") -> str | None:
    """打开文件选择对话框，返回选中路径或 None。"""
    import tkinter.filedialog as fd
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    if file_types:
        path = fd.askopenfilename(title=title, filetypes=[(file_types, "*.*")])
    else:
        path = fd.askdirectory(title=title)
    root.destroy()
    return path if path else None
