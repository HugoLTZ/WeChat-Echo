# 工作记录

## 2026-07-28

### 需求分析
- 评审《微信多开免扫码登录工具》需求文档 V1.0
- 调研 solong 微信多开助手、BetterWX 等同类工具技术方案
- 确认微信 4.x 技术路线：`global_config` + `global_config.crc` 凭证文件，`mklink` 软链接切换

### 技术选型
- **第一版**：PyQt5 — 原生控件风格老旧
- **第二版**：pywebview + HTML/CSS — 极简白 Apple 风格，自定义无边框标题栏
- **最终架构**：`pywebview (Edge WebView2) ↔ JS Bridge ↔ Python 业务层`

### 核心功能开发
- [x] 账号 CRUD（JSON 存储）
- [x] 凭证管理：硬链接（单开）+ 软链接（多开）双模式，三级回退
- [x] 微信启动器：`--multi` 参数，单开/并发/顺序三种模式
- [x] 进程检测：`win32gui.EnumWindows` 窗口枚举法，区分主进程与 worker 子进程
- [x] 头像自动捕获：`head_imgs/` 缓存检测 + base64 嵌入
- [x] wxid 自动检测：目录名扫描
- [x] 微信名手动编辑：自定义模态框，统一 UI 风格
- [x] 相对时间显示：今天/昨天/最近/一月内/很久以前
- [x] 开机自启：注册表 `HKCU\...\Run` 写入

### UI/UX 设计
- [x] 极简白配色（`#f5f5f7` 底色，`#1a1a2e` 强调）
- [x] 自定义无边框标题栏，JS 事件拖拽
- [x] 设置/关闭按钮自定义图标（`assets/` PNG 素材）
- [x] 卡片 hover 抽屉动画（`translateX` 从右侧滑入）
- [x] 图标按钮替代文字按钮
- [x] 艺术字标题图
- [x] Toast 毛玻璃提示
- [x] 模态框统一风格

### 打包踩坑记录
| 工具 | 版本 | 结果 | 原因 |
|------|------|------|------|
| PyInstaller | 6.21.0 | ❌ SxS 并行配置错误 | Python 3.14 兼容性 + UAC manifest 冲突 |
| Nuitka | 4.1.3 | ❌ pythonnet CLR 加载失败 | Nuitka 无法处理 .NET CLR 运行时依赖 |
| cx_Freeze | 8.6.4 | ❌ pythonnet CLR 加载失败 | 同上，`Python.Runtime.dll` 函数无法解析 |
| **PyInstaller** | 6.21.0 | ✅ 成功 | **去掉自定义 UAC manifest**，SxS 错误消失 |

- 最终方案：PyInstaller `--onefile`，`console=False`，不嵌入 UAC manifest
- 产物：`WeChat-Echo.exe` 18MB，`WeChat-Echo.zip` 17.5MB
- 注意：需右键「以管理员身份运行」（mklink 需要）

### 已知限制
- 微信 4.x 所有本地数据加密，无法提取微信昵称（仅能自动检测头像 + wxid）
- 多开时无法精确区分「哪个微信进程属于哪个账号」，关闭全部微信后统一重置状态
- 软链接方案依赖管理员权限
- 单机最多 4 个账号同时在线（微信服务端限制）
