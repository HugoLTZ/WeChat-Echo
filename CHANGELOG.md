# 工作记录

## 2026-07-29

### 自动备份凭证
- [x] 无凭证账号启动后自动监控微信登录状态，登录后自动备份
- [x] 登录检测：窗口尺寸 + WS_SIZEBOX 样式 + 主窗口计数三重信号
- [x] 备份时机：登录后 5+5 秒双重备份，确保凭证文件落盘完整

### 凭证管理重构
- [x] 备份/切换改为处理 config 目录全部文件（不仅是 global_config + crc）
- [x] switch_to 改为临时目录+硬链接方案：备份复制到 temp → temp 硬链接到 config
- [x] 微信回写只污染临时目录，备份文件永久干净（MD5 hash 验证通过）
- [x] clear_config 仅清除核心凭证文件，保留 upgrade_v4 确保微信正常初始化
- [x] 删除备份目录改用 shutil.rmtree

### 登录检测
- [x] 通过 win32gui 枚举微信窗口，检测 WS_SIZEBOX 样式区分主窗口/登录窗口
- [x] 综合尺寸（宽或高>500）+ 可调大小 + 窗口数增加判断登录成功
- [x] 进程检测兜底：可见窗口 + 进程名双重检查，覆盖登录过渡期

### UI/UX 优化
- [x] 删除确认弹窗替换为自定义模态框，统一风格
- [x] 卡片交互：无凭证可点击启动扫码，有凭证只能通过底部「登录」顺序启动
- [x] 更多按钮常驻卡片右侧，点击展开删除按钮（渐显动画）
- [x] 空状态 UI：chat.png 图标 + 提示文字
- [x] 窗口启动居中
- [x] 添加账号弹窗移除冗余提示文字
- [x] launch_all 按 last_login 从旧到新排序启动

### 日志与诊断
- [x] 补全 settings.py、account_manager.py、api.py 日志输出
- [x] account_manager._save() 加 OSError 异常保护
- [x] settings.py 开机自启失败加日志记录
- [x] 备份/切换操作增加 MD5 hash 诊断日志
- [x] 设置页面新增「导出日志」功能（打包 app.log 为 zip）

### Bug 修复
- [x] 修复 launch_all 重复定义（缺少 is_online 标记）
- [x] 修复 launcher.py 死代码（_track 方法不存在）
- [x] 修复 _count_main_windows EnumWindows 回调异常安全问题
- [x] 修复 _detect_and_save_user_info 无异常保护
- [x] 修复 _wechat_running 静默异常、_try_backup 日志级别
- [x] 修复 get_status 语法错误（多余花括号）
- [x] 删除确认弹窗停止事件冒泡，避免误触卡片

### 已知限制
- 微信 4.x 多账号启动有顺序依赖：需按凭证创建时间从旧到新启动
- 跳过旧账号直接启动新账号可能需要重新扫码（微信服务端策略）
- 多开一键启动需要管理员权限（mklink 软链接）
- 单机最多 4 个账号同时在线（微信服务端限制）
- 无法精确区分哪个微信进程属于哪个账号

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
