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
│   ├── pages/
│   │   └── Agentspace.tsx   ← Agentspace 页面（文件浏览器）
│   ├── context/
│   │   └── ConnectionDiagnosticsContext.tsx ← 连接诊断上下文
│   ├── hooks/
│   │   ├── useWebSocket.ts          ← WebSocket 与状态管理核心
│   │   ├── useWebSocketConnection.ts ← WebSocket 连接生命周期
│   │   ├── useSessionStore.ts       ← 会话列表与元数据管理
│   │   ├── useSubagentManager.ts    ← 子代理状态管理
│   │   ├── useUploadManager.ts      ← 文件上传管理
│   │   ├── useAgentspace.ts         ← Agentspace 文件浏览
│   │   └── useGlobalTooltip.ts      ← 全局 tooltip
│   ├── components/
│   │   ├── agentspace/             ← Agentspace 文件浏览器组件
│   │   │   ├── EditorArea.tsx
│   │   │   ├── FileTree.tsx
│   │   │   └── StatusBar.tsx
│   │   └── ...                      ← 聊天、弹窗、面板等组件
│   ├── styles/              ← CSS 样式
│   └── utils/
│       └── toolLabels.ts    ← 工具标签映射
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
- **包管理器**：pnpm
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
| `ErrorBoundary.tsx` | 错误边界，防止模态组件异常卸载整个 App |

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
| `InputBar.tsx` | 输入框、文件上传、发送按钮 |
| `Lightbox.tsx` | 图片灯箱 |
| `SafeHtml.tsx` | 安全 HTML 渲染 |
| `Minimap.tsx` | 小地图导航 |

### 弹窗与对话框

| 组件 | 职责 |
|---|---|
| `ConfirmDialog.tsx` | 工具审批弹窗（兼容 command 为字符串或数组） |
| `AskDialog.tsx` | `ask_question` 弹窗 |
| `TagEditor.tsx` | 会话标签编辑 |

### 面板

| 组件 | 职责 |
|---|---|
| `UnifiedPanel.tsx` | 统一侧面板容器 |
| `SubagentPanel.tsx` | 子代理状态面板 |
| `SubagentDrawer.tsx` | 子代理抽屉 |
| `TaskProgressPanel.tsx` | 任务进度面板 |
| `ClipboardPanel.tsx` | 剪贴板展示 |
| `PlaylistPlayer.tsx` | 播放列表播放器 |
| `CronCountdown.tsx` / `SubagentCountdown.tsx` | 倒计时组件 |

### Agentspace 文件浏览器（新增）

| 组件 | 职责 |
|---|---|
| `pages/Agentspace.tsx` | Agentspace 页面入口 |
| `components/agentspace/FileTree.tsx` | 文件树导航 |
| `components/agentspace/EditorArea.tsx` | 文件编辑/预览区域 |
| `components/agentspace/StatusBar.tsx` | 底部状态栏 |
| `hooks/useAgentspace.ts` | Agentspace 文件列表与内容管理 |

---

## Hooks

前端采用 hooks 拆分状态管理逻辑，从原有的 `useWebSocket.ts` 中提取出独立职责：

| Hook | 职责 |
|---|---|
| `useWebSocket.ts` | WebSocket 与状态管理核心：解析下行消息、管理消息列表、流式渲染、发送上行消息、调用 REST API |
| `useWebSocketConnection.ts` | WebSocket 连接生命周期管理：建立/断开/重连/心跳 |
| `useSessionStore.ts` | 会话列表与元数据管理：获取/创建/归档/删除/标签/标题 |
| `useSubagentManager.ts` | 子代理状态管理：注册/启动/停止/审批/列表 |
| `useUploadManager.ts` | 文件上传管理：拖拽上传、进度跟踪、文件选择器 |
| `useAgentspace.ts` | Agentspace 文件浏览：文件树加载、文件读写、路径导航 |
| `useGlobalTooltip.ts` | 全局 tooltip 管理 |

---

## Context

| Context | 职责 |
|---|---|
| `ConnectionDiagnosticsContext.tsx` | 连接诊断上下文：检测 WebSocket 连接状态、延迟、错误信息，为 UI 提供连接健康度反馈 |

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
| `playlist.css` | 播放列表 |
| `context-menu.css` | 右键菜单 |
| `tooltip.css` | 工具提示 |
| `agentspace.css` | Agentspace 文件浏览器 |

---

## 构建与开发注意事项

- 前端构建由 `origin_agent/__main__.py` 在启动时自动执行：`pnpm install && pnpm run build`，运行在 `workspace/fast_agent_space/frontend/` 副本中。
- **绝对禁止**在 `origin_agent/frontend/` 目录下直接运行 `pnpm install`、`pnpm build`、`pnpm dev` 等命令，以免污染源码目录。
- `origin_agent/frontend/` 不在仓库根目录，静态类型/IDE 感知可能不准确；不要依赖于此处的 TypeScript 类型检查结论。
- 由于前端构建是自动的，修改源码后由用户自行重启 `run.py` 触发重新构建。