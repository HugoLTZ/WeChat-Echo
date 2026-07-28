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

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

logger = get_logger("credential_manager")

# 微信 4.x 凭证文件名
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
        将微信当前使用的凭证备份到指定目录，
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

        for fname in CRED_FILES:
            src = self._wechat_dir / fname
            dst = target_dir / fname
            if src.is_file():
                try:
                    shutil.copy2(src, dst)
                    logger.debug("备份凭证文件: %s → %s", src, dst)
                except OSError as e:
                    logger.error("备份失败 %s: %s", fname, e)
                    success = False
            else:
                logger.warning("凭证文件不存在: %s", src)
                success = False

        # 自动检测并保存 wxid 和头像
        if success:
            self._detect_and_save_user_info(target_dir)

        if success:
            logger.info("凭证备份成功 → %s", target_dir)
        return success

    @staticmethod
    def _detect_and_save_user_info(target_dir: Path) -> None:
        """检测当前微信的 wxid 和头像，保存到账号备份目录。"""
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

        detected_wxid = None
        if wxid_dirs and (now - wxid_dirs[0][0]) < 300:
            # 最近 5 分钟内有活动的 wxid
            detected_wxid = wxid_dirs[0][1]
            (target_dir / "wxid.txt").write_text(detected_wxid, encoding="utf-8")
            logger.debug("检测到 wxid: %s", detected_wxid)

        # 2) 找最近修改的头像文件（无时间限制，取最新的）
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
                logger.debug("头像已保存: %s (mtime=%s)",
                             head_files[0][1],
                             __import__("datetime").datetime.fromtimestamp(head_files[0][0]))
            except OSError as e:
                logger.debug("头像保存失败: %s", e)

    # ---- 凭证切换 ----

    def switch_to(self, source_dir: Path) -> bool:
        """
        单账号凭证切换（优先硬链接，完全透明）。

        Args:
            source_dir: 账号凭证备份目录。
        """
        return self._do_switch(source_dir, prefer_hardlink=True)

    def switch_to_symlink(self, source_dir: Path) -> bool:
        """
        多开凭证切换（强制软链接，可在文件被占用时删除重建）。

        硬链接在目标文件被其他进程锁定时无法删除，
        因此多开场景必须用软链接。
        """
        return self._do_switch(source_dir, prefer_hardlink=False)

    def _do_switch(self, source_dir: Path, *, prefer_hardlink: bool) -> bool:
        if not source_dir.is_dir():
            logger.error("凭证源目录不存在: %s", source_dir)
            return False

        for fname in CRED_FILES:
            if not (source_dir / fname).is_file():
                logger.error("凭证源文件缺失: %s", source_dir / fname)
                return False

        self._wechat_dir.mkdir(parents=True, exist_ok=True)

        success = True
        for fname in CRED_FILES:
            target = self._wechat_dir / fname
            source = source_dir / fname
            self._remove_path(target)
            if prefer_hardlink:
                if not self._create_link(source, target):
                    success = False
            else:
                if not self._create_symlink(source, target):
                    success = False

        if success:
            logger.info("凭证切换成功 (%s) → %s",
                        "硬链接" if prefer_hardlink else "软链接", source_dir)
        return success

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
        """删除账号凭证备份目录。"""
        if not cred_dir.is_dir():
            return True
        try:
            # 先删除文件，再删除目录
            for fname in CRED_FILES:
                fpath = cred_dir / fname
                if fpath.is_file() or fpath.is_symlink():
                    fpath.unlink()
            cred_dir.rmdir()
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
