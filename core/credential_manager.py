"""
凭证管理模块。

负责每个账号登录凭证（global_config + global_config.crc）的：
  - 备份（从微信配置目录复制到账号私有目录）
  - 切换（通过 mklink 软链接将目标账号凭证映射到微信配置目录）
  - 验证（检查凭证文件是否存在）
  - 删除（删除账号凭证备份）

4.x 关键点：微信启动后锁定 global_config，因此必须用 mklink 软链接，
不能直接复制替换文件。
"""

import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

logger = get_logger("credential_manager")

# 微信 4.x 核心凭证文件名（用于快速检测）
CRED_FILES = ["global_config", "global_config.crc"]


class CredentialManager:
    """
    凭证管理器。

    Args:
        wechat_config_dir: 微信 4.x 的 config 目录路径
                            （即 xwechat_files/all_users/config）。
    """

    def __init__(self, wechat_config_dir: Path) -> None:
        self._wechat_dir = wechat_config_dir

    # ---- 属性 ----

    @property
    def wechat_config_dir(self) -> Path:
        return self._wechat_dir

    @wechat_config_dir.setter
    def wechat_config_dir(self, v: Path) -> None:
        self._wechat_dir = v

    # ---- 凭证备份 ----

    def backup(self, target_dir: Path) -> bool:
        """
        将微信 config 目录全部内容备份到指定目录，
        同时自动检测并保存 wxid 和头像。

        Args:
            target_dir: 备份目标目录。

        Returns:
            备份是否成功。
        """
        if not self._wechat_dir.is_dir():
            logger.error("微信配置目录不存在: %s", self._wechat_dir)
            return False

        target_dir.mkdir(parents=True, exist_ok=True)
        success = True

        for src in self._wechat_dir.iterdir():
            if not src.is_file():
                continue
            dst = target_dir / src.name
            try:
                shutil.copy2(str(src), str(dst))
                # 诊断：记录文件 hash
                h = hashlib.md5(src.read_bytes()).hexdigest()[:8]
                logger.info("[备份] %s size=%d hash=%s → %s", src.name, src.stat().st_size, h, dst)
            except OSError as e:
                logger.error("备份失败 %s: %s", src.name, e)
                success = False

        if not success:
            return False

        self._detect_and_save_user_info(target_dir)
        logger.info("凭证备份成功 → %s", target_dir)
        return True

    @staticmethod
    def _detect_and_save_user_info(target_dir: Path) -> None:
        """检测当前微信的 wxid 和头像，保存到账号备份目录。"""
        try:
            from config.settings import get_settings
            s = get_settings()
            xwechat_dir = Path(s.wechat_data_dir) / "xwechat_files"
            if not xwechat_dir.is_dir():
                return

            now = __import__("time").time()

            # 1) 找最近活跃的 wxid 目录
            wxid_dirs = []
            for d in xwechat_dir.iterdir():
                if d.is_dir() and d.name.startswith("wxid_"):
                    max_mtime = 0
                    for f in d.rglob("*"):
                        if f.is_file():
                            mtime = f.stat().st_mtime
                            if mtime > max_mtime:
                                max_mtime = mtime
                    wxid_dirs.append((max_mtime, d.name))
            wxid_dirs.sort(reverse=True)

            if wxid_dirs and (now - wxid_dirs[0][0]) < 300:
                detected_wxid = wxid_dirs[0][1]
                (target_dir / "wxid.txt").write_text(detected_wxid, encoding="utf-8")
                logger.debug("检测到 wxid: %s", detected_wxid)

            # 2) 找最近修改的头像文件
            head_dir = xwechat_dir / "all_users" / "head_imgs"
            head_files = []
            if head_dir.is_dir():
                for d in head_dir.iterdir():
                    if d.is_dir():
                        for f in d.iterdir():
                            if f.is_file():
                                head_files.append((f.stat().st_mtime, f))
            head_files.sort(reverse=True)

            if head_files:
                try:
                    shutil.copy2(str(head_files[0][1]), str(target_dir / "avatar.jpg"))
                    logger.debug("头像已保存: %s", head_files[0][1])
                except OSError as e:
                    logger.debug("头像保存失败: %s", e)
        except Exception as e:
            logger.warning("自动检测用户信息失败: %s", e)

    # ---- 自动监控备份 ----

    def wait_and_backup(self, target_dir: Path, timeout: float = 300.0, interval: float = 5.0) -> bool:
        """
        后台轮询监测微信配置目录，扫码登录后自动备份凭证。

        策略：综合三个信号判断「主窗口」——大尺寸 + 可调大小 + 窗口数增加。
        登录窗口：~370×485，无 WS_SIZEBOX，仅一个
        主窗口：  尺寸大（宽或高 > 500），有 WS_SIZEBOX
        启动时记录主窗口数，数量增加 = 登录成功。
        """
        logger.info("自动备份监控启动 (间隔: %.0fs, 超时: %.0fs) → %s",
                    interval, timeout, target_dir)

        initial_count = self._count_main_windows()
        logger.debug("初始主窗口数: %d", initial_count)

        start = time.monotonic()

        while time.monotonic() - start < timeout:
            time.sleep(interval)

            if not self._wechat_running():
                logger.info("微信已退出，停止监控")
                return False

            if not self._files_ready():
                continue

            current_count = self._count_main_windows()
            if current_count > initial_count:
                logger.info("检测到新增主窗口 (%d → %d)，已登录",
                            initial_count, current_count)
                # 此时 config 目录只有本账号刚写入的凭证，立即备份
                time.sleep(5)
                self._try_backup(target_dir)
                time.sleep(5)
                if self._try_backup(target_dir):
                    logger.info("自动备份成功 → %s", target_dir)
                    return True

        logger.info("监控超时 (%ds)", timeout)
        return False

    @staticmethod
    def _count_main_windows() -> int:
        """
        统计微信「主窗口」数量。
        主窗口 = 微信窗口 + 可调大小(WS_SIZEBOX) + 尺寸大(宽或高 > 500)。
        登录窗口不满足后两个条件，不会被计入。
        """
        import win32gui
        GWL_STYLE = -16
        WS_SIZEBOX = 0x00040000
        count = 0

        def cb(hwnd: int, _ctx: None) -> bool:
            nonlocal count
            try:
                if not win32gui.IsWindowVisible(hwnd):
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
                    count += 1
            except Exception:
                pass  # 跳过无法访问的窗口
            return True

        win32gui.EnumWindows(cb, None)
        return count

    def _try_backup(self, target_dir: Path) -> bool:
        """尝试备份，不抛异常。"""
        try:
            return self.backup(target_dir)
        except Exception as e:
            logger.warning("备份尝试失败: %s", e)
            return False

    def _files_ready(self) -> bool:
        """检查两个凭证文件是否都存在。"""
        return all((self._wechat_dir / f).is_file() for f in CRED_FILES)

    @staticmethod
    def _wechat_running() -> bool:
        """检查是否有微信进程在运行（含登录窗口到主窗口的过渡期）。"""
        try:
            from core.process_detector import ProcessDetector
            if ProcessDetector.is_running():
                return True
            return len(ProcessDetector.get_all_wechat_processes()) > 0
        except Exception as e:
            logger.warning("微信进程检测失败: %s，假设仍在运行", e)
            return True

    # ---- 凭证切换 ----

    def switch_to(self, source_dir: Path) -> bool:
        """
        单账号凭证切换。

        先复制备份到临时目录，再用临时目录创建硬链接到 config。
        微信回写只会污染临时目录，备份文件保持干净。
        """
        import tempfile
        tmp_dir = Path(tempfile.mkdtemp(prefix="wechat_echo_"))
        for src in source_dir.iterdir():
            if src.is_file():
                shutil.copy2(str(src), str(tmp_dir / src.name))
        return self._do_switch(tmp_dir, prefer_hardlink=True)
        # 临时目录不清理——硬链接创建后，临时目录条目删除不影响 config
        # 由系统 temp 目录回收机制处理

    def switch_to_symlink(self, source_dir: Path) -> bool:
        """
        多开凭证切换（强制软链接，可在文件被占用时删除重建）。

        硬链接在目标文件被其他进程锁定时无法删除，
        因此多开场景必须用软链接。
        """
        return self._do_switch(source_dir, prefer_hardlink=False)

    def _do_switch(self, source_dir: Path, *, prefer_hardlink: bool, use_copy: bool = False) -> bool:
        if not source_dir.is_dir():
            logger.error("凭证源目录不存在: %s", source_dir)
            return False

        # 至少要有关键凭证文件
        if not all((source_dir / f).is_file() for f in CRED_FILES):
            logger.error("凭证源文件缺失 (需要 global_config + global_config.crc)")
            return False

        self._wechat_dir.mkdir(parents=True, exist_ok=True)

        # 先清除目标目录中所有文件
        for old in list(self._wechat_dir.iterdir()):
            if old.is_file() or old.is_symlink():
                self._remove_path(old)

        # 复制备份目录中所有文件到 config 目录
        success = True
        for src in source_dir.iterdir():
            if not src.is_file():
                continue
            target = self._wechat_dir / src.name
            src_hash = hashlib.md5(src.read_bytes()).hexdigest()[:8] if src.is_file() else "?"
            ok = False
            if use_copy:
                ok = self._create_copy(src, target)
            elif prefer_hardlink:
                ok = self._create_link(src, target)
            else:
                ok = self._create_symlink(src, target)
            if not ok:
                success = False
            else:
                tgt_hash = hashlib.md5(target.read_bytes()).hexdigest()[:8] if target.is_file() else "?"
                logger.info("[切换] %s size=%d src_hash=%s dst_hash=%s %s",
                            src.name, src.stat().st_size, src_hash, tgt_hash,
                            "OK" if src_hash == tgt_hash else "HASH MISMATCH!")

        if success:
            logger.info("凭证切换成功 (%s) → %s",
                        "硬链接" if prefer_hardlink else "软链接", source_dir)
        return success

    @staticmethod
    def _create_copy(source: Path, dest: Path) -> bool:
        """文件复制（不会因微信回写污染源文件）。"""
        try:
            shutil.copy2(str(source), str(dest))
            logger.debug("复制成功: %s → %s", source, dest)
            return True
        except OSError as e:
            logger.warning("复制失败 %s → %s: %s", source, dest, e)
            return False

    @staticmethod
    def _create_link(source: Path, link_path: Path) -> bool:
        """创建硬链接（优先 os.link，备选 mklink /H）。"""
        try:
            os.link(str(source), str(link_path))
            logger.debug("os.link 硬链接成功: %s → %s", link_path, source)
            return True
        except OSError as e:
            logger.debug("os.link 失败 (%s)，尝试 mklink /H", e)

        try:
            result = subprocess.run(
                f'cmd /c mklink /H "{link_path}" "{source}"',
                capture_output=True, text=True, shell=True, timeout=10,
            )
            if result.returncode == 0:
                logger.debug("mklink /H 硬链接成功: %s → %s", link_path, source)
                return True
            logger.warning("硬链接失败: %s", result.stderr.strip())
        except Exception as e:
            logger.warning("硬链接异常: %s", e)

        return False

    @staticmethod
    def _create_symlink(source: Path, link_path: Path) -> bool:
        """创建软链接（专用于多开场景，可在文件被占用时删除重建）。"""
        try:
            result = subprocess.run(
                f'cmd /c mklink "{link_path}" "{source}"',
                capture_output=True, text=True, shell=True, timeout=10,
            )
            if result.returncode == 0:
                logger.debug("软链接成功: %s → %s", link_path, source)
                return True
            logger.error("软链接失败: %s", result.stderr.strip())
        except Exception as e:
            logger.error("软链接异常: %s", e)
        return False

    def clear_config(self) -> bool:
        """清除核心凭证文件，保留 upgrade_v4 等让微信能正常初始化。"""
        self._wechat_dir.mkdir(parents=True, exist_ok=True)
        ok = True
        for fname in CRED_FILES + ["client_config", "client_config.crc"]:
            fpath = self._wechat_dir / fname
            self._remove_path(fpath)
            if fpath.is_file() or fpath.is_symlink():
                logger.warning("无法清除（可能被占用）: %s", fpath)
                ok = False
        logger.debug("已清除核心凭证文件")
        return ok

    def _remove_path(self, path: Path) -> None:
        """安全删除文件 / 硬链接 / 软链接。"""
        try:
            if path.is_symlink():
                os.unlink(path)
                logger.debug("删除软链接: %s", path)
            elif path.is_file():
                path.unlink()
                logger.debug("删除文件: %s", path)
            elif path.is_dir():
                logger.warning("路径为目录，跳过删除: %s", path)
        except FileNotFoundError:
            pass  # 不存在无需处理
        except OSError as e:
            logger.warning("删除路径失败 %s: %s", path, e)

    # ---- 凭证验证 ----

    def validate_backup(self, account_cred_dir: Path) -> bool:
        """检查账号凭证备份是否齐全。"""
        if not account_cred_dir.is_dir():
            return False
        return all((account_cred_dir / f).is_file() for f in CRED_FILES)

    @staticmethod
    def delete_backup(cred_dir: Path) -> bool:
        """删除账号凭证备份目录（含凭证文件、wxid、头像等全部内容）。"""
        if not cred_dir.is_dir():
            return True
        try:
            shutil.rmtree(str(cred_dir))
            logger.info("已删除凭证目录: %s", cred_dir)
            return True
        except OSError as e:
            logger.error("删除凭证目录失败: %s", e)
            return False

    # ---- 导出 / 导入 ----

    @staticmethod
    def export_credentials(cred_dir: Path, output_zip: Path) -> bool:
        """将凭证目录打包为 zip。"""
        try:
            base = cred_dir.parent
            shutil.make_archive(
                str(output_zip.with_suffix("")),
                "zip",
                base,
                cred_dir.name,
            )
            logger.info("凭证已导出: %s", output_zip)
            return True
        except Exception as e:
            logger.error("导出凭证失败: %s", e)
            return False

    @staticmethod
    def import_credentials(zip_path: Path, cred_dir: Path) -> bool:
        """从 zip 导入凭证到指定目录。"""
        try:
            cred_dir.mkdir(parents=True, exist_ok=True)
            shutil.unpack_archive(str(zip_path), str(cred_dir), "zip")
            # 解压后目录结构可能是 cred_dir/acc_xxx/files，需拉平
            logger.info("凭证已导入: %s", cred_dir)
            return True
        except Exception as e:
            logger.error("导入凭证失败: %s", e)
            return False
