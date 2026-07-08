# frontend/ — Web 前端

`frontend/` 是 Evolve Agent 的 Web 用户界面，基于 React + Vite + TypeScript。用户通过浏览器与 Agent 进行对话、审批工具调用、管理子代理、查看任务进度等。

---

## 文件结构

```
frontend/
├── src/
│   ├── App.tsx              ← 根组件
│   ├── main.tsx             ← 入口
│   ├── types.ts             ← 类型定义
│   ├── utils.ts             ← 工具函数
│   ├── hooks/
│   │   └── useWebSocket.ts  ← WebSocket 与状态管理核心
│   ├── components/          ← React 组件
│   └── styles/              ← CSS 样式
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

---

## 关键组件

| 组件 | 职责 |
|---|---|
| `App.tsx` | 组合 Sidebar / Header / ChatArea / InputBar / 各类面板与弹窗 |
| `Sidebar.tsx` | 会话列表、搜索、新建会话 |
| `Header.tsx` | 顶部工具栏、模型信息、设置入口 |
| `ChatArea.tsx` | 聊天消息滚动区域 |
| `MessageItem.tsx` | 单条消息渲染（文本、代码块、图片、工具调用） |
| `InputBar.tsx` | 输入框、文件上传、发送按钮 |
| `ConfirmDialog.tsx` | 工具审批弹窗 |
| `AskDialog.tsx` | `ask_question` 弹窗 |
| `SubagentPanel.tsx` | 子代理状态面板 |
| `TaskProgressPanel.tsx` | 任务进度面板 |
| `UnifiedPanel.tsx` | 统一侧面板容器 |
| `ClipboardPanel.tsx` | 剪贴板展示 |
| `CronCountdown.tsx` / `SubagentCountdown.tsx` | 倒计时组件 |
| `Lightbox.tsx` | 图片灯箱 |
| `TagEditor.tsx` | 会话标签编辑 |
| `ErrorBoundary.tsx` | 错误边界，防止模态组件异常卸载整个 App |

---

## `useWebSocket.ts`

`useWebSocket.ts` 是前端的核心 hook，职责包括：

- 建立并维护 `WS /ws/chat` 连接，支持 `?resume=sid` 恢复会话。
- 解析服务端下行消息类型（`stream_delta`、`tool_call`、`tool_result`、`confirm_request`、`ask_request`、`subagent_update` 等）。
- 管理会话状态、消息列表、流式文本渲染。
- 发送上行消息：`user_message`、`confirm_response`、`ask_response`、`interrupt`、`file_upload`。
- 调用 REST API：获取会话列表、更新标题/标签、终止会话、获取子代理状态等。
- 处理前端上传、文件选择器回调。

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

---

## 构建与开发注意事项

- 前端构建由 `origin_agent/__main__.py` 在启动时自动执行：`pnpm install && pnpm run build`，运行在 `workspace/fast_agent_space/frontend/` 副本中。
- **绝对禁止**在 `origin_agent/frontend/` 目录下直接运行 `pnpm install`、`pnpm build`、`pnpm dev` 等命令，以免污染源码目录。
- `origin_agent/frontend/` 不在仓库根目录，静态类型/IDE 感知可能不准确；不要依赖于此处的 TypeScript 类型检查结论。
- 由于前端构建是自动的，修改源码后由用户自行重启 `run.py` 触发重新构建。