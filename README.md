# WeChat-Echo

微信 4.x 多开免扫码登录工具。极简白设计，自动备份凭证，一次扫码永久复用。

## 功能

- **自动备份** — 扫码登录后自动检测并备份凭证，无需手动操作
- **多开免扫码** — 同时运行最多 4 个微信 4.x 实例，首次扫码后免扫码登录
- **凭证隔离** — 临时目录+硬链接方案，备份文件不受微信回写污染
- **开机自启** — 注册表 Run 键，随系统启动
- **日志导出** — 设置页面一键导出诊断日志

## 使用

1. **添加账号** — 点击「添加账号」输入名称
2. **扫码绑定** — 点击无凭证卡片启动微信，扫码登录后自动备份
3. **顺序启动** — 所有账号绑定后，点击底部「登录」一键启动全部（按绑定顺序）

## 技术栈

```
pywebview (Edge WebView2) + HTML/CSS/JS
         ↕  window.pywebview.api
      Python 业务层
    account / credential / launcher / process
```

## 开发

```bash
pip install -r requirements.txt
python main.py
```

### 打包

```bash
pip install pyinstaller
pyinstaller wechat_multi.spec
# → dist/WeChat-Echo.exe
```

## 注意

- 需要 Windows 10/11，微信 4.x
- 多开一键启动需要管理员权限（mklink 软链接需要）
- 单账号启动无需管理员权限
- 微信限制单机同时最多 4 个账号
- 凭证有时效性，过期后需重新扫码备份
- 启动顺序需按账号绑定时间从旧到新
