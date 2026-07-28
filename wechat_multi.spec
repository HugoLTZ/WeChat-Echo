# -*- mode: python ; coding: utf-8 -*-

"""
PyInstaller 打包配置（pywebview 架构）。

使用方法：
    pyinstaller wechat_multi.spec

生成单文件 exe，带管理员 UAC 提权。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "gui" / "index.html"), "gui"),
    ],
    hiddenimports=[
        "webview",
        "webview.platforms.winforms",
        "clr_loader",
        "pythonnet",
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
    name="WeChatMulti",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    manifest="""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedExecutionLevel level="requireAdministrator" uiAccess="false"/>
    </security>
  </trustInfo>
</assembly>""",
    icon=None,
)
