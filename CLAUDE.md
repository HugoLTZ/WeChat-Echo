# WeChat-Echo 项目指南

微信 4.x 多开免扫码登录工具。`pywebview + Python` 架构。

## 常用命令

```bash
# 运行
python main.py                          # 需要管理员权限

# 打包
pyinstaller wechat_multi.spec           # → dist/WeChat-Echo.exe (18MB)

# 格式化
pip install -r requirements.txt
```

## 发布流程

每次发版按以下步骤执行：

### 1. 更新文档
- `README.md` — 功能列表、使用说明
- `CHANGELOG.md` — 按日期记录新功能/修复/已知限制
- `微信多开程序需求文档.md` — 版本号、功能需求、技术方案、变更记录

### 2. 构建
```bash
pyinstaller wechat_multi.spec
cp dist/WeChat-Echo.exe dist/WeChat-Echo-vX.Y.Z.exe
```

### 3. 提交 & 打 Tag
```bash
git add README.md CHANGELOG.md 微信多开程序需求文档.md
git commit -m "docs: 更新文档至 VX.Y —— 摘要"
git tag -a vX.Y.Z -m "VX.Y.Z — 标题

新功能:
- ...

修复:
- ..."
```

### 4. 推送 & 发布 Release
```bash
git push origin master
git push origin vX.Y.Z
gh release create vX.Y.Z "dist/WeChat-Echo-vX.Y.Z.exe" \
  --title "vX.Y.Z — 标题" \
  --notes "## 新功能
- ...

## 修复
- ...

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

> **版本号规则**：大功能 +0.1，纯文档/小修复用 patch。当前最新 `v1.2.0`。

## 项目结构

```
wechat-account/
├── main.py                    # 入口（管理员提权 → 初始化 → GUI）
├── wechat_multi.spec          # PyInstaller 打包配置
├── CLAUDE.md                  # 本文件
├── config/settings.py         # 配置管理（路径/注册表自启）
├── core/
│   ├── account_manager.py     # 账号 CRUD（JSON）
│   ├── credential_manager.py  # 凭证备份/切换/验证
│   ├── launcher.py            # 微信启动 + PID 追踪 + 孤儿收养
│   └── process_detector.py    # 进程检测（窗口枚举）
├── gui/
│   ├── api.py                 # JS-Python 桥接（18 个方法）
│   └── index.html             # 前端 UI（单文件）
├── utils/logger.py            # 日志（RotatingFileHandler）
└── assets/                    # 图标资源（PNG）
```

## 技术要点

- **凭证方案**：单账号→文件复制（`shutil.copy2`），多开→软链接（`mklink`）
- **PID 追踪**：`pid_map.json` 持久化，kill 前校验进程名防 OS 回收误杀
- **三态检测**：在线（PID+主窗口）| 启动中（PID 无主窗口）| 离线
- **孤儿收养**：头像 MD5 匹配，自动关联用户手动启动的微信
- **启动参数**：`Weixin.exe --multi` 绕过单实例互斥体
- **打包**：PyInstaller `--onefile`，`console=False`，不嵌入 UAC manifest
