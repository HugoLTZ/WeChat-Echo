# -*- mode: python ; coding: utf-8 -*-

"""
PyInstaller 打包配置。

使用方法：
    pyinstaller wechat_multi.spec

生成单文件 exe，带管理员 UAC 提权。
"""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve()  # SPECPATH = spec 文件所在目录

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "gui" / "index.html"), "gui"),
        (str(ROOT / "assets"), "assets"),
    ],
    hiddenimports=[
        "webview",
        "webview.platforms.winforms",
        "clr_loader",
        "pythonnet",
        "win32gui",
        "win32process",
        "win32api",
        "psutil",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WeChat-Echo",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "icon.ico") if (ROOT / "assets" / "icon.ico").is_file() else None,
)
