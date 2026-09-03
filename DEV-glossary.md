# Evolve Agent — 项目术语表

> **三位一体**：本表统一开发者/用户、开发助手AI、Evolve Agent 三方沟通口径。新增术语必须先登记后使用。

**防漂移规则**：

1. **新增术语先登记后使用** — 任何在文档、对话、prompt 中频繁出现的概念，必须先在本表登记规范称谓，后方可使用。
2. **Agent 一律大写 A** — Evolve Agent、Cursor AI、主Agent、子Agent、临时Agent、多Agent模式主会话等，"Agent" 永远大写。代码标识按源码原样（`SubAgentLoop`、`subagent` 工具集名等）。
3. **中英双锁定** — 每条术语锁定中文规范称谓与英文锚点；面向 Evolve Agent 的 prompt 模板使用规范英文形态。

---

## §1 元规则

| 规范称谓 | 定义 |
|---|---|
| 角色术语与实例名分层 | 文档默认用角色术语；实例名仅特指当前部署时使用 |
| Role 不译 | 固定搭配，直指 `puretype.Role` 枚举（user/assistant/system/tool） |
| 术语双锁定 | 中文规范称谓 + 英文锚点；prompt 模板使用规范英文形态 |

---

## §2 协作角色

| 规范称谓 | 指代 | 英文锚点 |
|---|---|---|
| 用户（场景别名：开发者） | 人类 | user / developer |
| 开发助手AI | 开发侧协助的 AI（角色术语；当前实例为 Cursor AI，未来可替换） | dev assistant AI |
| Cursor AI | 当前承担「开发助手AI」角色的具体 AI 实例 | Cursor AI |
| Evolve Agent（通称：项目 Agent） | 本项目的运行时 agent | Evolve Agent |
| 主Agent | 系统提示词含 SOUL 的 Agent，任意 loop 下保证存在 | `MAIN_AGENT_CHARACTER_NAME = "main-agent"` |

---

## §3 空间与沙盒

| 规范称谓 | 目录 | 沙盒前缀 | 角色 |
|---|---|---|---|
| origin仓库 | `origin_agent/` | 无 | 源码真相源：唯一持久化源码 |
| fast仓库 | `workspace/fast_agent_space/` | 无（无 `self:`） | 当前运行副本 |
| slow仓库 | `workspace/slow_agent_space/` | `fork:` | 进化目标副本 |
| fallback仓库 | `workspace/.fallback/` | `fix:` | 上一次 fast 仓库的备份 / 回退修复体 |
| 工作空间 | `workspace/agentspace/` | `ws:` | agent 的 workspace，通用 I/O |

> **设计注记**：fast/slow 借用快慢指针命名——fast 是当前执行位置，slow 是待提升位置，热交换即 slow 提升为 fast。
> 「副本」为角色描述词，不作名词术语。fast 模式 / fallback 模式保留英文形态。「回退」为 fallback 中文规范译法。
> **目录列均为默认配置名**——workspace 根与 fast/slow 空间、工作空间、logs 的实际目录名由 config.py 参数（`workspace_path`、`fast_agent_space_path`、`slow_agent_space_path`、`agentspace_path_name`、`logs_path_name`）覆盖；本表锁定的是角色称谓而非物理目录名。仅 `.fallback/` 为 run.py 硬编码固定名。

| 规范称谓 | 定义 |
|---|---|
| 沙盒命名空间 | `fork:`/`ws:`/`fix:`/`skills:`/`third:`/`custom_*:` 逻辑前缀体系（`Namespace` 枚举） |
| 逻辑路径 / 物理路径 | 带命名空间前缀的路径（如 `fork:main.py`）/ 真实文件系统路径 |
| `.docs/` | 项目示例与引用资料目录 |

---

## §4 会话与 Loop

| 规范称谓 | 指代 | 代码锚点 |
|---|---|---|
| 主会话 | 三种 loop 承载的顶层会话统称 | — |
| 普通模式主会话 | `ParentAgentLoop` 的会话 | `Loop.parent` |
| 多Agent模式主会话 | `MultiAgentLoop` 的会话 | `Loop.multi` |
| 随意聊聊会话 | `ColloquyLoop` 的内置会话 | `Loop.colloquy` / `COLLOQUY_SESSION_ID` |
| 子会话 | `SubAgentLoop` 的会话（与前端 UI「子会话面板/抽屉」对齐） | — |
| 临时子会话 | `TaskAgentLoop` 的会话 | — |
| 子Agent / subagent | `SubAgentLoop` 运行体；亦指多Agent模式中从注册表加载的非主参与者（两语境互斥，复用不歧义） | — |
| 临时Agent / taskagent | `TaskAgentLoop` 运行体（无系统提示词、无持久化、完成即终止） | — |
| 子Agent注册项 | `SubagentStore` 持久化的 `AgentConfig` 条目 | — |
| （子Agent的）档案 | 子Agent 创建时可被主Agent 配置的系统提示词 | `AgentConfig.system_prompt_paths` |
| 运行时Profile | 多Agent参与者的运行时形态 | `AgentProfile` 类 |
| 参与Agent | 多Agent模式主会话中的参与者（主Agent 必居其一） | — |
| 工具循环 | LLM→工具调用→结果回写→LLM 轮次循环（上限 90） | `MAX_TOOL_TURNS` |
| 级联 | 多Agent模式 `response_characters` 驱动的串行响应队列调度 | `_cascade` |

---

## §5 编排与进化

| 规范称谓 | 指代 | 英文锚点 |
|---|---|---|
| 启动入口 | `run.py` | launch entry |
| 子代理编排器 | `SubAgentOrchestrator`（禁用"调度器"叫法） | SubAgentOrchestrator |
| 进化触发模块 | `evolve/code.py` | — |
| 进化 | 词根统一（"演化"为待改写遗留） | evolution |
| 进化工具链 | read/edit（fork:）→ validate_code/validate_frontend → evolve_code | — |
| 热交换 | slow→fast 交换并重启 | fast-slow swap |
| 进化循环 | fast-slow-fallback 全流程统称 | evolution cycle |
| 回退修复 | fallback 模式下由 fallback仓库 修复 fast仓库 | fallback repair |
| 进化状态 | `workspace/logs/evolution.status` 记录的进化结果状态 | evolution status |

---

## §6 审批系统

| 规范称谓 | 定义 | 英文锚点 |
|---|---|---|
| 手动模式 | 工具调用经前端弹窗由用户逐条审批 | manual mode |
| 脱手模式 | 工具调用由审批模型自动审批 | handsfree mode |
| YOLO 模式 | "You Only Live Once"：AI 工具的免确认自动执行模式——含 critical 全部自动批准、无审批模型参与、`--yolo` 启动锁定、运行时不可退出 | YOLO mode |
| 审批模型 | 脱手模式下执行审批的 LLM；本地 GGUF 与远程审批端点为其两种部署形态 | approval model |
| 远程审批端点 | `approval_remote_*` 配置的无本地模型时 fallback 来源 | remote approval endpoint |
| 危险等级 | `danger_level` 四级：safe / write / dangerous / critical | danger level |
| 可用范围 | `availability` 位掩码：MAIN / SUBAGENT / MULTI_AGENT / TASKAGENT / EVERY | availability |
| 审批动作 | allow_once（允许一次）/ allow_always（始终允许，入白名单）/ deny（拒绝） | approval action |
| 审批策略 | `ApprovalPolicy`：手动模式与脱手模式各自需审批的危险等级集合 | approval policy |
| 白名单 / allowlist | 中文规范"白名单"、英文标识 allowlist | allowlist |
| 工具白名单 | `tool_allowlist.json` 持久化的"始终允许"记录 | tool allowlist |

---

## §7 消息与事件

| 规范称谓 | 指代 |
|---|---|
| Role（不译） | `puretype.Role` 协议层枚举（user/assistant/system/tool） |
| 角色（character）/ 角色名（character_name） | 会话参与者层标识（main-agent/end-user/system/子Agent名） |
| 事件出口 | sink 体系：`AgentSink` 抽象；`FrontendSink` = 前端事件出口；`ParentAgentSink` = 父会话事件出口 |
| 入站缓冲 / 出站缓冲 | inbox / outbox（异步消息缓冲；代码标识改名为可选遗留） |
| 消息体系 | `entity/messages.py` 的 `BaseMessage` 多态模型与 `History` |
| 流式增量 | `StreamChunk`（content_delta / reasoning_delta） |
| 思考内容 | reasoning_content / reasoning_delta（DeepSeek thinking-mode 载荷） |
| 记忆上下文 | memory_hook 注入的长期记忆块（`<|im_memory_context_start|>` 标记包裹，非持久化） |
| 元数据提取器 | `META_EXTRACTOR_CHARACTER`：生成标题/标签/摘要时的角色名，语义上隔离 agent 发言与元数据生成 |

---

## §8 上下文管理

| 规范称谓 | 定义 |
|---|---|
| 压缩 | 将早期消息压缩为摘要以释放上下文（`compress_history` 工具；随意聊聊会话用滑动窗口压缩最早 30%） |
| 摘要 | 会话级总结文本（`summary.txt`，终结/旋转时生成） |
| 旋转（rotation） | 上下文超限时自动终结当前会话并产生子会话的机制 |
| 延续（continuation） | **动作**：继承已终结父会话产生子会话——手动（一个或多个父会话，含合并）或旋转自动触发 |
| 延续会话 | 延续动作产生的子会话（`SessionInfo.continuation` 指向者） |
| 父会话 | `SessionInfo.parents` 指向的会话（支持多父） |

> 三机制分工：压缩保会话、旋转换会话、摘要作载体。

---

## §9 扩展点

| 规范称谓 | 定义 |
|---|---|
| 钩子 | `custom_hooks/` 下实现 `hook_tag_name` + `hook_message`/`hook_fixator` |
| 上下文扩展块 | 钩子返回、附加到用户消息末尾的内容块（前端渲染类名 `context-extension-part`） |
| 固着器（fixator） | 实现 `hook_fixator` 的钩子：产出**持久化**扩展块（`message_suffix`，写盘保留） |
| 非固着器 | 仅实现 `hook_message` 的钩子：产出**非持久化**扩展块（`dynamic_message_suffix`，当轮注入） |
| 技能 | `skills/` 下 `SKILL.md`，经 `load_skill`/`list_skills` 加载 |
| 插件 | `abstract/plugins` 目录扫描 + `plugin.yaml` 元数据 |
| 自定义工具 | `custom_tools/` 下的 `.py` 工具扩展 |
| 自定义LLM客户端 | `custom_llm_client/` 下的 `.py` LLM 客户端扩展 |
| 自定义模型 | `custom_models/` 下的 `.gguf` 模型文件 |
| MCP 桥接 | `component/mcp_tools.py` 将外部 MCP server 工具注册进工具注册表 |
| LLM Profile 根对象 | `LLMProfileData`（英文锚点：`LLM Profile root`）；`llm_profiles.es` v2 中唯一的持久化根，持有全部 Profile 及实例引用关系 |
| Profile 名称指针 | 会话级或全局最近使用的 Profile 名称（英文锚点：`Profile name pointer`）；只保存名称，不复制端点、密钥或 Profile 对象 |
| Profile 实例引用 | `LLMProfile` 多模态分工字段直接指向根列表中的另一个 `LLMProfile` 实例（英文锚点：`Profile object reference`） |

---

## §10 会话操作

| 规范称谓 | 定义 |
|---|---|
| 归档 | 会话只读化（`status = "archived"`），可参与合并 |
| 终结 | 归档 + 生成摘要 |
| 合并 | 多父延续：将多个已归档会话合并为一个新会话 |
| 分支 | 从当前会话创建子会话 |
| 置顶 | `pinned` 标记，置顶显示 |

---

## §11 前端 UI

> 用户口径优先：如「导航栏」专指**左侧 Sidebar**，不是顶部 Header。

### 页面布局总览

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

### Agentspace 编辑器

| 规范称谓 | 代码锚点 | 定义 | 英文锚点 |
|---|---|---|---|
| Agentspace 编辑器 | `pages/Agentspace.tsx` | 独立的工作空间文件浏览与文本编辑页面 | Agentspace editor |
| Agentspace 文件树 | `components/agentspace/FileTree.tsx` | Agentspace 编辑器左侧的目录与文件树；不称作「导航栏」 | Agentspace file tree |
| Agentspace 垃圾桶 | `ws:.trash/` | 仅承接用户从 Agentspace 编辑器发起的可恢复删除；不改变 Evolve Agent `Delete` 工具 | Agentspace trash |
| 文件锁 | `AgentspaceLockRegistry` | Agent 在单次回复轮次中明确接触 `ws:` 路径后持有的路径锁；轮次收尾时释放 | file lock |

> 「导航栏」仍然只指聊天页面左侧 Sidebar。Agentspace 文件树与导航栏是两个不同区域。

### 应用框架与加载层

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

### 左侧导航栏（Sidebar）

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

### 顶部栏（Header）

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

### 主内容区（Layout 其余区域）

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

---

## §12 退役术语

以下术语已过时或被取代，禁止在新内容中使用：

| 退役术语 | 替代术语 | 说明 |
|---|---|---|
| 冒险模式 / Adventure / Adventure Mode | 脱手模式（handsfree mode） | 非常旧的名称，已全面退役 |
| 演化 / 演化循环 | 进化 / 进化循环 | 词根统一为"进化" |
| 子代理调度器 | 子代理编排器 | `SubAgentOrchestrator` 的禁用叫法 |
| 正常模式 | 手动模式 | 审批模式名称，取代"正常模式" |
| RIPER Yolo | （已删除） | RIPER-5 协议中已过时的 Yolo 概念，已从 `.agents/skills/riper-core/SKILL.md` 移除 |
| 允许列表 | 白名单 | 统一为"白名单" |
| orchestrator（裸称） | 启动入口（launch entry） | prompt 模板中裸称 orchestrator 指代 run.py 的写法已退役；`SubAgentOrchestrator` 合法保留 |