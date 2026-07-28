# 微信多开免扫码登录工具

基于 Python 的微信 4.x 多开免扫码登录工具，通过 `mklink` 软链接实现多账号凭证隔离，无需反复扫码。

## 功能

- **无限多开**：同时运行最多 4 个微信 4.x 实例（微信服务端限制）
- **免扫码登录**：首次扫码备份凭证后，后续启动直接登录
- **账号管理**：添加/删除/搜索账号，直观的卡片式界面
- **凭证备份/导出**：支持凭证导入导出，便于迁移到其他电脑

## 工作原理

微信 4.x 将登录凭证存储在 `global_config` + `global_config.crc` 两个文件中。本工具：

1. 为每个账号备份独立的凭证文件
2. 启动前用 `mklink` 软链接将目标账号凭证映射到微信配置目录
3. 并发启动多个微信进程，绕过互斥体单实例限制

## 系统要求

- Windows 10/11（64 位）
- Python 3.10+
- 微信 4.x 版本
- **管理员权限**（`mklink` 命令需要）

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 以管理员身份运行
python main.py
```

## 使用说明

1. **添加账号**：在微信中扫码登录 → 打开本工具 → 点击「添加账号」→ 输入名称 → 点击「备份凭证」
2. **日常使用**：选中账号 → 点击「启动」→ 微信自动免扫码登录
3. **多开**：依次启动不同账号即可同时在线（最多 4 个）

## 打包为 exe

```bash
pip install pyinstaller
pyinstaller wechat_multi.spec
```

生成的文件位于 `dist/WeChatMulti.exe`。

## 项目结构

```
├── main.py                    # 入口（管理员提权）
├── config/settings.py         # 配置管理
├── core/
│   ├── account_manager.py     # 账号 CRUD
│   ├── credential_manager.py  # 凭证管理（mklink）
│   ├── launcher.py            # 微信启动器
│   └── process_detector.py    # 进程检测
├── gui/
│   ├── main_window.py         # 主界面
│   ├── add_account_dialog.py  # 添加账号对话框
│   └── settings_dialog.py     # 设置对话框
└── utils/logger.py            # 日志模块
```

## 注意事项

- 需要**管理员权限**运行（mklink 要求）
- 微信限制单机最多 **4 个账号**同时在线
- 凭证有时效性（数天到数周），过期后需重新扫码备份
- 使用前请确认遵守微信用户协议
