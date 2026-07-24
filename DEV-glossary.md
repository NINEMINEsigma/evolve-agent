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

## 通用术语

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 脱手模式 | `handsfreeMode` | 工具调用由本地 GGUF 审批模型自动审批 |
| 归档会话 | `status === "archived"` | 只读，可参与合并 |
| 父会话 / 延续会话 | `parents` / `continuation` | 会话继承关系 |
| 进化目标副本 | `workspace/slow_agent_space/`（`fork:`） | Agent 自我修改的对象 |
| 源码真相源 | `origin_agent/` | 唯一持久化源码，禁止直接运行 |