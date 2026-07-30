# WeChat-Echo

微信 4.x 多开免扫码登录工具。极简白设计，自动备份凭证，一次扫码永久复用。

## 功能

- **自动备份** — 扫码登录后自动检测并备份凭证，无需手动操作
- **多开免扫码** — 同时运行最多 4 个微信 4.x 实例，首次扫码后免扫码登录
- **凭证隔离** — 临时目录+文件复制方案，备份文件不受微信回写污染
- **PID 追踪** — 精确追踪每个账号对应的微信进程，支持单账号独立关闭
- **三态状态** — 区分「在线」「启动中」「离线」三种状态，主窗口检测精准判断
- **孤儿收养** — 头像 MD5 匹配，自动识别并关联用户手动启动的微信进程
- **PID 持久化** — 重启后自动恢复账号在线状态，无需重新登录
- **开机自启** — 注册表 Run 键，随系统启动
- **日志导出** — 设置页面一键导出诊断日志

## 使用

### 初次使用

1. 点击标题栏 ⚙ 设置 → 指定微信程序路径（`Weixin.exe`）和数据目录（`WeChat Files`）
2. 保存后即可使用

### 添加账号（扫码绑定）

1. 点击底部「添加账号」→ 自动弹出微信扫码登录窗口
2. 程序进入**等待扫码**状态，此时不可操作
3. 用手机微信扫描屏幕上的二维码
4. 登录成功后**自动备份凭证**，账号出现在列表中（命名 `Echo - 1`, `Echo - 2` …）
5. 若关闭扫码窗口或点取消，则终止流程

### 批量登录

1. 所有账号绑定凭证后，点击底部「**登录**」
2. 右上角出现进度条：`正在启动 1/3 个微信窗口…`
3. 按账号绑定时间**从旧到新**顺序启动，每个间隔 3 秒等待凭证切换
4. 等待所有微信登录窗口加载完成后，依次点击每个微信窗口的「登录」按钮
5. 进度条消失即全部启动完成

## 下载

从 [GitHub Releases](https://github.com/HugoLTZ/WeChat-Echo/releases) 下载最新版本 `WeChat-Echo.exe`，右键「以管理员身份运行」即可。

[![GitHub Release](https://img.shields.io/github/v/release/HugoLTZ/WeChat-Echo?label=最新版本)](https://github.com/HugoLTZ/WeChat-Echo/releases/latest)

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
