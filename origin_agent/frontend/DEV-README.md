# frontend/ — Web 前端

`frontend/` 是 Evolve Agent 的 Web 用户界面，基于 React + Vite + TypeScript。用户通过浏览器与 Agent 进行对话、审批工具调用、管理子代理、查看任务进度、浏览 agentspace 文件等。

---

## 文件结构

```
frontend/
├── src/
│   ├── App.tsx              ← 根组件
│   ├── main.tsx             ← 入口
│   ├── types.ts             ← 类型定义
│   ├── utils.ts             ← 工具函数
│   ├── declarations.d.ts    ← 全局类型声明
│   ├── pages/
│   │   └── Agentspace.tsx   ← Agentspace 页面（文件浏览器）
│   ├── context/
│   │   └── ConnectionDiagnosticsContext.tsx ← 连接诊断上下文
│   ├── constants/
│   │   ├── dimensions.ts    ← 尺寸常量
│   │   ├── session.ts       ← 会话相关常量
│   │   ├── storage.ts       ← localStorage 键名
│   │   ├── timing.ts        ← 时间常量
│   │   └── ws.ts            ← WebSocket 常量
│   ├── hooks/
│   │   ├── useWebSocket.ts          ← WebSocket 与状态管理核心
│   │   ├── useWebSocketConnection.ts ← WebSocket 连接生命周期
│   │   ├── useSessionStore.ts       ← 会话列表与元数据管理
│   │   ├── useSubagentManager.ts    ← 子代理状态管理
│   │   ├── useUploadManager.ts      ← 文件上传管理
│   │   ├── useLlmProfiles.ts         ← Profile 列表、单对象 CRUD 与活动名称
│   │   ├── useAgentspace.ts         ← Agentspace 文件浏览
│   │   ├── useEdgeDrawer.ts         ← 边缘抽屉三态状态机
│   │   └── useGlobalTooltip.ts      ← 全局 tooltip
│   ├── components/
│   │   ├── agentspace/             ← Agentspace 文件浏览器组件
│   │   │   ├── AgentspaceDialogs.tsx
│   │   │   ├── ConflictDialog.tsx
│   │   │   ├── EditorArea.tsx
│   │   │   ├── FileTree.tsx
│   │   │   ├── StatusBar.tsx
│   │   │   └── TreeIcons.tsx
│   │   ├── primitives/             ← 基础 UI 原语
│   │   │   ├── ModalWindow.tsx
│   │   │   ├── PopupLayer.tsx
│   │   │   └── CopyBanner.tsx
│   │   └── ...                      ← 聊天、弹窗、面板等组件
│   ├── services/
│   │   └── agentspaceApi.ts ← Agentspace REST/SSE 唯一适配层
│   ├── styles/              ← CSS 样式
│   └── utils/
│       ├── agentspacePath.ts ← Agentspace 路径与排序纯函数
│       ├── toolLabels.ts    ← 工具标签映射
│       └── exportSession.ts ← 会话导出
├── package.json
├── vite.config.ts
├── tsconfig*.json
└── index.html
```

---

## 技术栈

- **框架**：React 18
- **构建工具**：Vite 6
- **语言**：TypeScript 5.6
- **包管理器**：pnpm（优先），npm（回退）
- **主要依赖**：
  - `react-markdown`：Markdown 渲染
  - `react-syntax-highlighter`：代码高亮
  - `remark-gfm`：GitHub 风格 Markdown
  - `react-zoom-pan-pinch`：图片缩放
  - `mermaid`：Mermaid 图表渲染

---

## 关键组件

### 布局与导航

| 组件 | 职责 |
|---|---|
| `App.tsx` | 根组件，组合 Sidebar / Header / ChatArea / InputBar / 各类面板与弹窗 |
| `Layout.tsx` | 布局容器，管理主聊天区与侧面板的排列 |
| `Sidebar.tsx` | 会话列表、搜索、新建会话 |
| `Header.tsx` | 顶部工具栏、模型信息、设置入口 |
| `Drawer.tsx` | 侧边抽屉容器 |
| `OnboardingTour.tsx` | 首次访问引导向导（react-joyride），spotlight 高亮 + 步骤动画驱动 |
| `ErrorBoundary.tsx` | 错误边界，防止模态组件异常卸载整个 App |
| `SplashScreen.tsx` | 开屏动画，最少停留 800ms、最多 3000ms，可点击跳过 |
| `AgentStageLayer.tsx` | 聊天区背景层 Agent 舞台层 iframe（会话级 `stage/` 目录，透明、鼠标穿透） |

### 聊天区域

| 组件 | 职责 |
|---|---|
| `ChatArea.tsx` | 聊天消息滚动区域 |
| `MessageItem.tsx` | 单条消息渲染（文本、代码块、图片、工具调用） |
| `MessageBody.tsx` | 消息正文 Markdown 渲染 |
| `MessageEditor.tsx` | 消息编辑器（编辑历史消息） |
| `MessageAttachments.tsx` | 消息附件展示 |
| `CodeBlock.tsx` | 代码块渲染与高亮 |
| `MermaidRenderer.tsx` | Mermaid 图表渲染 |
| `ChatContextMenu.tsx` | 聊天区右键菜单 |
| `RichInput.tsx` | 富文本输入（支持多行、快捷键） |
| `InputBar.tsx` | 输入框、文件上传、发送按钮、功能按钮组（超宽收起菜单）、上下文徽章 |
| `TokenRing.tsx` | 上下文用量环形徽章（Header 与输入栏共用） |
| `Lightbox.tsx` | 图片灯箱 |
| `SafeHtml.tsx` | 安全 HTML 渲染 |
| `Minimap.tsx` | 小地图导航 |
| `MentionMenu.tsx` | `@` 提及菜单（文件/skill 列表，Portal 渲染） |

### 弹窗与对话框

| 组件 | 职责 |
|---|---|
| `AskDialog.tsx` | `Ask` 弹窗 |
| `TagEditor.tsx` | 会话标签编辑 |
| `primitives/ModalWindow.tsx` | 模态窗口基础原语 |
| `primitives/PopupLayer.tsx` | 弹出层基础原语 |

### 面板

| 组件 | 职责 |
|---|---|
| `ClipboardPanel.tsx` | 剪贴板展示面板 |
| `SubagentPanel.tsx` | 子代理状态面板 |
| `SubagentDrawer.tsx` | 子代理抽屉 |
| `TaskProgressPanel.tsx` | 任务进度面板 |
| `PlaylistPlayer.tsx` | 播放列表播放器 |
| `CronCountdown.tsx` / `SubagentCountdown.tsx` | 倒计时组件 |

### Agentspace 文件浏览器（新增）

| 组件 | 职责 |
|---|---|
| `pages/Agentspace.tsx` | Agentspace 页面编排、侧栏尺寸、离开确认和对话框宿主 |
| `components/agentspace/FileTree.tsx` | 目录优先文件树、独立类型图标、单选键盘导航和垃圾桶节点 |
| `components/agentspace/EditorArea.tsx` | Monaco 编辑、可滚动标签、同名消歧和逐文件锁/冲突状态 |
| `components/agentspace/StatusBar.tsx` | 路径、语言、光标、保存/冲突/锁与同步状态 |
| `components/agentspace/AgentspaceDialogs.tsx` | 创建、重命名、脏标签与永久清理确认 |
| `components/agentspace/ConflictDialog.tsx` | Monaco DiffEditor 冲突处理 |
| `components/agentspace/TreeIcons.tsx` | 无新增依赖的内联 SVG 文件树图标 |
| `services/agentspaceApi.ts` | Agentspace REST、结构化错误与 EventSource 适配 |
| `utils/agentspacePath.ts` | 路径规范化、前缀重写、选择上下文和自然排序 |
| `hooks/useAgentspace.ts` | 目录/标签/锁/垃圾桶状态机及 HTTP/SSE 代际控制 |

---

## Hooks

前端采用 hooks 拆分状态管理逻辑，从原有的 `useWebSocket.ts` 中提取出独立职责：

| Hook | 职责 |
|---|---|
| `useWebSocket.ts` | WebSocket 与状态管理核心：解析下行消息、管理消息列表、流式渲染、发送上行消息、调用 REST API；每条用户消息携带活动 Profile 名称并处理 `llm_profile_changed`；发送时不乐观渲染气泡，改为记录 pending message 供输入栏显示"已排队"徽章 |
| `useLlmProfiles.ts` | 从服务端读取 Profile；提供单对象创建/编辑/删除；浏览器仅持久化活动 Profile 名称，不保存 Profile 列表 |
| `useWebSocketConnection.ts` | WebSocket 连接生命周期管理：建立/断开/重连/心跳 |
| `useSessionStore.ts` | 会话列表与元数据管理：获取/创建/归档/删除/标签/标题；维护 pending messages 状态（`pendingMessages`），在 `USER_MESSAGE` 回显时渲染正式气泡并移除 pending，在 `TOOL_RESULT` 携带 `consumed_client_message_ids` 时移除匹配 pending，中断/切会话/历史重载时清空 |
| `useSubagentManager.ts` | 子代理状态管理：注册/启动/停止/审批/列表 |
| `useUploadManager.ts` | 文件上传管理：拖拽上传、进度跟踪、文件选择器 |
| `useAgentspace.ts` | Agentspace 编辑器状态机：目录展开/选择、版本化标签、SSE 代际、逐文件锁、冲突和垃圾桶 |
| `useEdgeDrawer.ts` | 边缘抽屉三态状态机（hidden/peek/open），侧栏与顶部栏共用 |
| `useGlobalTooltip.ts` | 全局 tooltip 管理 |
| `useSessionStage.ts` | 会话舞台层状态：探测 `stage/index.html`，订阅 Agentspace SSE 自动刷新 |

---

## Context

| Context | 职责 |
|---|---|
| `ConnectionDiagnosticsContext.tsx` | 连接诊断上下文：检测 WebSocket 连接状态、延迟、错误信息，为 UI 提供连接健康度反馈 |

---

## Agentspace 编辑器行为

- 文件树固定使用“文件夹优先、文件在后、组内自然名称排序”，展开箭头与类型图标分离；单击文件直接打开永久标签。
- 侧栏可拖动、折叠并保存宽度；标签栏可横向滚动，不同目录的同名文件显示最短可区分父路径。
- 用户删除进入独立 `ws:.trash/` 垃圾桶节点；恢复冲突自动添加 `.restored-N`，永久删除与清空需要明确确认。Evolve Agent 的 `Delete` 不受此 UI 语义影响。
- 保存携带打开时的 SHA-256 版本。外部修改干净标签时自动重载；脏标签保留本地内容并进入 DiffEditor 冲突处理。
- 内置 Agent 操作按回复轮次持有具体路径锁，只有命中路径变为只读；无关文件仍可编辑。
- 文件变化通过 SSE 实时同步。watcher 或连接不可用时状态栏显示降级，并保留手动刷新。
- 关闭脏标签提供保存/不保存/取消；页面离开使用浏览器原生确认，不跨刷新恢复草稿和标签。

---

## 样式组织

`src/styles/` 按功能拆分：

| 文件 | 说明 |
|---|---|
| `base.css` | 基础样式 |
| `variables.css` | CSS 变量 |
| `chat.css` | 聊天布局 |
| `messages.css` | 消息气泡与渲染 |
| `input.css` | 输入框 |
| `dialogs.css` | 弹窗 |
| `drawer.css` | 抽屉面板 |
| `panels.css` | 任务进度/子代理面板 |
| `sidebar.css` | 侧边栏 |
| `header.css` | 顶部栏 |
| `lightbox.css` | 图片灯箱 |
| `context-menu.css` | 右键菜单 |
| `tooltip.css` | 工具提示 |
| `agentspace.css` | Agentspace 文件浏览器 |
| `agent-stage.css` | Agent 舞台层（聊天区背景层 iframe） |
| `modal.css` | 模态窗口 |
| `popup.css` | 弹出层 |
| `splash.css` | 启动屏 |
| `skeleton.css` | 组件级骨架占位样式（shimmer 动画） |
| `onboarding.css` | 引导向导样式覆盖（react-joyride 主题微调） |

---

## 构建与开发注意事项

- 前端构建由 `origin_agent/__main__.py` 在启动时自动执行：`<pkg_mgr> install && <pkg_mgr> run build`（包管理器优先 pnpm，回退 npm），运行在 `workspace/fast_agent_space/frontend/` 副本中。
- **绝对禁止**在 `origin_agent/frontend/` 目录下直接运行 `pnpm install`、`pnpm build`、`pnpm dev`、`npm install`、`npm run build` 等命令，以免污染源码目录。
- `origin_agent/frontend/` 不在仓库根目录，静态类型/IDE 感知可能不准确；不要依赖于此处的 TypeScript 类型检查结论。
- 由于前端构建是自动的，修改源码后由用户自行重启 `run.py` 触发重新构建。