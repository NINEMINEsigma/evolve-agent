# Evolve Agent — 术语表（DEV Glossary）

记录 UI 各区域、组件的中文名称与代码标识符的对照，统一沟通口径。
用户口径优先：如「导航栏」专指**左侧 Sidebar**，不是顶部 Header。

---

## 页面布局总览

```
┌──────────┬────────────────────────────────────────────┬──────┐
│          │  顶部栏 (Header)                            │      │
│  左侧    ├────────────────────────────────────────────┤  右  │
│  导航栏  │  任务进度面板 (TaskProgressPanel)           │  侧  │
│          │  统一面板 (UnifiedPanel)                    │  触  │
│ (Sidebar)│  聊天区 (ChatArea)                          │  发  │
│          │  输入栏 (InputBar)                          │  条  │
└──────────┴────────────────────────────────────────────┴──────┘
```

> 启动屏（`SplashScreen`）和骨架屏（`SkeletonScreen`）作为覆盖层叠加在整体布局之上，分别用于开屏动画和首次连接前的占位。

---

## 应用框架与加载层

文件：`origin_agent/frontend/src/App.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 应用根组件 | `App` / `ChatApp` | 路由入口；管理 `SplashScreen`、`ChatContextMenu`、`TagEditor` 等顶层覆盖层；外层套 `ErrorBoundary` |
| 错误边界 | `ErrorBoundary` / `.error-boundary` | 组件渲染异常兜底，显示「界面渲染出错」+ 刷新按钮 |
| 连接诊断上下文 | `ConnectionDiagnosticsProvider` / `useConnectionDiagnostics` | 全局 Provider，向 `DebugBadges` 等组件提供 WebSocket 连接状态（waiting / pendingConfirm / streamingMessage 等） |

文件：`origin_agent/frontend/src/components/SplashScreen.tsx` · `origin_agent/frontend/src/components/SkeletonScreen.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 启动屏 | `SplashScreen` / `.splash-screen` | 开屏动画，最少停留 800ms、最多 3000ms，可点击跳过 |
| 骨架屏 | `SkeletonScreen` / `.skeleton-screen` | 首次 WebSocket 连接前的布局骨架占位（Header + Sidebar + 消息区轮廓） |

---

## 左侧导航栏（Sidebar）

> 用户所称「导航栏」「会话按钮和搜索框那一块」即此区域。

文件：`origin_agent/frontend/src/components/Sidebar.tsx` · `origin_agent/frontend/src/styles/sidebar.css`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 左侧导航栏 / 侧栏 | `Sidebar` / `.sidebar` | 展开宽 220px，`.collapsed` 时宽 0 完全隐藏 |
| 侧栏头部 | `.sidebar-header` | 顶部区域，含工具栏 |
| 侧栏工具栏 | `.sidebar-toolbar` | 搜索框 + 多选合并按钮 + 新建会话按钮 |
| 搜索框 | `.search-input`（容器 `.sidebar-search`） | 单行 28px，聚焦时展开为 96px 多行 |
| 标签云 | `.search-tag-cloud` / `.search-tag-btn` | 搜索聚焦或有搜索词时显示的标签快捷筛选 |
| 多选合并按钮 | `.icon-btn`（mergeMode 开关） | 进入/退出归档会话多选合并模式 |
| 新建会话按钮 | `.icon-btn`（onNewChat） | — |
| 会话列表 | `.session-list` | 可滚动区域，渲染平铺会话与会话簇 |
| 会话项 | `SessionListItem` / `.session-item` | 左侧 2px 竖线标识：蓝=当前，绿=父会话 |
| 会话簇 | `ClusterItem` / `.cluster` | 多个会话的聚合分组，可展开/折叠 |
| 关联会话快捷入口 | `RelatedSessionShortcut` / `.relation-shortcut` | 当前会话的父会话/延续会话跳转按钮 |
| 合并操作栏 | `.merge-bar` | 合并模式底部悬浮栏（已选数 + 合并按钮） |
| 侧栏遮罩 | `.sidebar-backdrop` | 移动端侧栏浮层展开时的背景遮罩 |
| 抽屉热区 | `.sidebar-hotzone` | 桌面端屏幕左缘 24px 隐形触发区，鼠标靠近时抽屉微微拉出 |
| 抽屉状态 | `.drawer-hidden` / `.drawer-peek` / `.drawer-open` | 桌面端侧栏三态：隐藏 / 微微拉出 / 彻底拉出（磨砂玻璃浮层） |
| 抽屉状态机 | `useEdgeDrawer` | 边缘抽屉三态状态机（hidden/peek/open），侧栏与顶部栏共用；`pinned` 选项在弹出层展开期间钉住抽屉 |

## 顶部栏（Header）

> 注意：用户口径中「导航栏」**不指这里**。

文件：`origin_agent/frontend/src/components/Header.tsx` · `origin_agent/frontend/src/styles/header.css`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 顶部栏 / 页头 | `Header` / `.app-header` | 三栏 grid：左 / 中 / 右；桌面端为顶部覆盖抽屉，移动端为流内页头 |
| 顶部栏覆盖层 | `.header-layer` | 桌面端 absolute 覆盖容器（z-index 90），自身不响应指针，子元素按需恢复 |
| 顶部栏热区 | `.header-hotzone` | 桌面端顶部 20px 隐形触发区，鼠标靠近时抽屉拉出 |
| 主徽章 dock | `.header-pill-dock` | 桌面端常驻的状态胶囊容器，bar 隐藏时 pill 依然可见可交互 |
| 顶部抽屉状态 | `.header-drawer-hidden` / `.header-drawer-peek` / `.header-drawer-open` | 桌面端顶部栏三态：隐藏 / 探出 12px / 完全展开（磨砂玻璃浮层，背景板由 `::before` 承载） |
| 侧栏开关按钮 | `.sidebar-toggle` | 位于顶部栏左侧，控制左侧导航栏收起/展开 |
| 会话徽章 | `.session-badge` | 当前会话 ID，≤768px 隐藏 |
| 调试徽章组 | `DebugBadges` / `.debug-badges` | 连接诊断徽章，≤1100px 隐藏 |
| 命令菜单 | `.cmd-menu-dropdown`（⋮ 按钮触发） | 导出会话 / 卸载审批模型；展开期间钉住顶部抽屉 |
| 状态胶囊 | `HeaderPill` / `.header-pill` | 居中渐变胶囊，hover 展开状态/模型名详情；桌面端渲染于 dock，移动端渲染于中栏 |
| 脱手模式徽章 | `.approval-model-badge` | 点击切换自动审批 |
| 令牌徽章 | `.token-badge` | token 统计文本，≤900px 隐藏 |
| 令牌环 | `TokenRing` / `.token-ring` | 上下文用量环形图，≤900px 显示 |
| 顶部栏折叠按钮 | `.header-collapse-btn` | 仅移动端出现的顶部栏折叠开关 |

## 主内容区（Layout 其余区域）

文件：`origin_agent/frontend/src/components/Layout.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 主内容区 | `.main-content` | 顶部栏以右的全部内容 |
| 任务进度面板 | `TaskProgressPanel` | 顶部栏下方，可折叠 |
| 统一面板（剪贴板） | `UnifiedPanel` | 剪贴板内容展示，可折叠 |
| 聊天区 | `ChatArea` | 消息流 |
| 输入栏 | `InputBar` | 底部输入区 |
| 右侧触发条 | `.right-trigger-strip` / `.right-trigger-bar` | 屏幕右缘的展开把手（资源抽屉 / 子会话面板） |
| 资源抽屉 | `Drawer` | 后台任务、Cron 等 |
| 子会话面板 | `SubagentPanel` | 宽度持久化于 localStorage 键 `evolve_subagent_panel_width` |
| 图片灯箱 | `Lightbox` | 图片放大查看 |
| 确认对话框 | `ConfirmDialog` | 工具调用审批弹窗 |
| 询问对话框 | `AskDialog` | Agent 提问弹窗 |

### 聊天区内部组件

文件：`origin_agent/frontend/src/components/ChatArea.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 消息项 | `MessageItem` / `.message` | 单条消息容器：头像、角色名、长消息折叠（>1200 字符或 >18 行）、编辑入口 |
| 消息体 | `MessageBody` | Markdown 渲染（GFM + breaks + raw）；reasoning 折叠；检测 `<script>`/`<style>` 等标签时切换到 `SafeHtml` 沙箱 |
| 消息编辑器 | `MessageEditor` / `.message-edit-box` | 用户消息内联编辑（textarea + 保存/取消） |
| 消息附件 | `MessageAttachments` | 图片缩略图、音频播放器、下载链接、播放列表 |
| 代码块 | `CodeBlock` / `.code-block-wrapper` | 语法高亮（Prism oneDark）+ 一键复制 |
| Mermaid 渲染器 | `MermaidRenderer` | Mermaid 图表渲染；点击放大为灯箱（缩放/平移，react-zoom-pan-pinch） |
| 安全 HTML | `SafeHtml` | iframe 沙箱渲染 agent 输出的原始 HTML，postMessage 同步高度，避免流式闪烁 |
| 等高线背景 | `ContourBackground` | 聊天区 canvas 等高线动态背景，受消息内容长度与 seed 影响 |
| 小地图 | `Minimap` | 聊天区右侧消息流缩略导航，可拖拽跳转；移动端默认折叠 |
| 回到底部按钮 | `.scroll-to-bottom-btn` | 滚动离开底部时出现的快捷回底按钮 |

### 输入栏内部组件

文件：`origin_agent/frontend/src/components/InputBar.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 富文本输入 | `RichInput` | contenteditable 富文本输入框，支持图片粘贴、`@` 提及（文件/skill）、`/` 命令 |
| @ 提及菜单 | `MentionMenu` / `.mention-menu` | `@` 或 `/` 触发的文件/skill 列表，Portal 渲染到 body，30s TTL 缓存 |
| 待上传图片预览 | `pendingImages` / `.pending-image` | 输入栏上方显示待发送的图片缩略图，可移除 |
| 目标会话选择器 | `targetSessions` | 选择消息发送目标（main / 子会话），位于输入栏工具区 |
| 角色可见性控制 | `visibleCharacters` / `responseCharacters` | 多 Agent 模式下控制消息可见范围与响应角色 |

### 会话操作弹层

文件：`origin_agent/frontend/src/components/ChatContextMenu.tsx` · `TagEditor.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 聊天右键菜单 | `ChatContextMenu` | 会话项右键菜单：自动标题、自动标签、置顶、分支、终止、删除、重生成摘要 |
| 标签编辑器 | `TagEditor` | 会话标签编辑弹窗（仅限 1-5 个汉字或 1-10 个英文字母） |

### 子会话与定时任务

文件：`origin_agent/frontend/src/components/SubagentDrawer.tsx` · `SubagentPanel.tsx` · `SubagentCountdown.tsx` · `CronCountdown.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 子会话抽屉 | `SubagentDrawer` / `SubagentCard` | 子会话全屏抽屉，含 `SubagentCard` 卡片和 `Minimap` |
| 子会话倒计时 | `SubagentCountdown` / `.cron-countdown-strip` | 子会话空闲收集倒计时条（≤30s 显示） |
| Cron 倒计时 | `CronCountdown` / `.cron-countdown-strip` | 定时任务下次执行倒计时条（≤60s 显示） |

### 资源抽屉内部

文件：`origin_agent/frontend/src/components/Drawer.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 播放列表播放器 | `PlaylistPlayer` | 音频播放列表 UI（上一首/下一首/进度条/展开折叠） |

### 遗留组件

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 剪贴板面板（旧版） | `ClipboardPanel` / `.clipboard-display-panel` | 与 `UnifiedPanel` 功能重叠的旧版组件，已被 `UnifiedPanel` 替代 |

## 通用术语

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 脱手模式 | `handsfreeMode` | 工具调用由本地 GGUF 审批模型自动审批 |
| 归档会话 | `status === "archived"` | 只读，可参与合并 |
| 父会话 / 延续会话 | `parents` / `continuation` | 会话继承关系 |
| 进化目标副本 | `workspace/slow_agent_space/`（`fork:`） | Agent 自我修改的对象 |
| 源码真相源 | `origin_agent/` | 唯一持久化源码，禁止直接运行 |