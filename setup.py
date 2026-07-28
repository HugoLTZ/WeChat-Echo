from cx_Freeze import setup, Executable

build_options = {
    "packages": [
        "webview", "clr_loader", "pythonnet",
        "win32gui", "win32process", "win32api",
        "psutil",
    ],
    "include_files": [
        ("gui/index.html", "gui/index.html"),
        ("assets/", "assets/"),
    ],
    "excludes": [],
}

executables = [
    Executable(
        "main.py",
        target_name="WeChat-Echo",
        base="gui",
        icon="assets/icon.ico",
    ),
]

setup(
    name="WeChat-Echo",
    version="1.0.0",
    options={"build_exe": build_options},
    executables=executables,
)
