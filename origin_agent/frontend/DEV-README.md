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
│   ├── features/chat/          ← 主聊天运行时：骨架、内容页、Virtuoso、Zustand、滚动与遥测
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
│   │   ├── useSessionSite.ts        ← 会话网页探测与 SSE 热刷新
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
- **包管理器**：pnpm（优先），npm（回退）
- **主要依赖**：
  - `react-markdown`：Markdown 渲染
  - `react-syntax-highlighter`：代码高亮
  - `remark-gfm`：GitHub 风格 Markdown
  - `react-zoom-pan-pinch`：图片缩放
  - `mermaid`：Mermaid 图表渲染
  - `react-virtuoso`：主聊天区可变高度虚拟列表
  - `zustand`：聊天运行时细粒度 selector store

---

## 关键组件

### 布局与导航

| 组件 | 职责 |
|---|---|
| `App.tsx` | 根组件，组合 Sidebar / Header / ChatArea / InputBar / 各类面板与弹窗 |
| `Layout.tsx` | 布局容器，管理主聊天区与侧面板的排列 |
| `Sidebar.tsx` | 会话列表、搜索、新建会话 |
| `Header.tsx` | 顶部工具栏、模型信息、设置入口；审批徽章按当前会话显示手动/脱手/YOLO，并在连接同步期间显示不可点击的“加载中”或“不可用” |
| `Drawer.tsx` | 侧边抽屉容器；资源区包含 Shell会话元数据列表与用户停止按钮，不提供终端输出或人工输入 |
| `OnboardingTour.tsx` | 首次访问引导向导（react-joyride），spotlight 高亮 + 步骤动画驱动 |
| `ErrorBoundary.tsx` | 错误边界，防止模态组件异常卸载整个 App |
| `SplashScreen.tsx` | 开屏动画，最少停留 800ms、最多 3000ms，可点击跳过 |
| `AgentStageLayer.tsx` | 聊天区背景层 Agent 舞台层 iframe（会话级 `stage/` 目录，透明、鼠标穿透）；仅负责渲染，由 `Layout` 统一提供舞台层状态 |
| `SessionSiteSection.tsx` / `SessionSiteDrawer` | 会话网页抽屉展示与交互；消费 `useSessionSite` 的权威状态，保留手动刷新、全屏、新标签页和整站下载 |
| `ChatStyleLayer.tsx` | 聊天区自定义样式注入层，以 `<style data-chat-style-scope>` 注入经 PostCSS 作用域处理的 CSS（会话级 `chat-style/index.css`） |

### 聊天区域

| 组件 | 职责 |
|---|---|
| `ChatArea.tsx` | 聊天区外层布局宿主；保持 Agent 舞台层、聊天区自定义样式、输入栏和 Minimap 的定位边界，消息序列委托给 `VirtualMessageList` |
| `features/chat/VirtualMessageList.tsx` | 基于 Virtuoso 渲染完整骨架的可视窗口；正文按页加载，live 尾部独立渲染 |
| `features/chat/ChatHistoryRow.tsx` | 单行 selector 消费，按 loaded / skeleton / page-error 三态渲染 |
| `MessageItem.tsx` | 单条消息渲染（文本、代码块、图片、工具调用）；通过 `data-character-name` 暴露角色显示名称，并在用户主动高度操作前通知滚动状态机；工具调用折叠摘要显示工具名与参数 JSON，并按气泡实际宽度自适应省略；气泡折叠入口按消息类型互斥：工具消息仅由摘要切换详情，普通长消息仅由底部按钮切换正文 |
| `MessageBody.tsx` | 消息正文 Markdown 渲染 |
| `MessageEditor.tsx` | 消息编辑器（编辑历史消息） |
| `MessageAttachments.tsx` | 消息附件展示 |
| `CodeBlock.tsx` | 代码块渲染与高亮 |
| `MermaidRenderer.tsx` | Mermaid 图表渲染 |
| `ChatContextMenu.tsx` | 聊天区右键菜单 |
| `RichInput.tsx` | 富文本输入（支持多行、快捷键） |
| `InputBar.tsx` | 输入框、文件上传、发送按钮、功能按钮组（超宽收起菜单）、上下文徽章；普通单Agent桌面会话在已有消息后使用独立底部玻璃热区控制三态抽屉，空会话保留居中的完整输入栏；非空会话空闲时默认收缩，抵达聊天区底部时自动展开，离开底部后恢复收缩，热区悬停、聚焦及附件、审批、上传、录音、任务进度等交互期间保持展开；中断按钮支持「正在中断」状态、禁止重复点击、失败后允许重试 |
| `TokenRing.tsx` | 上下文用量环形徽章（Header 与输入栏共用） |
| `Lightbox.tsx` | 图片灯箱 |
| `SafeHtml.tsx` | 安全 HTML 渲染 |
| `Minimap.tsx` | 主聊天区使用 Canvas 逻辑 Minimap 映射，将正典骨架与尚未固化的 live 行共同绘制，不测量离屏 DOM；子会话抽屉继续使用局部 DOM 几何模式 |
| `MentionMenu.tsx` | `@` 提及菜单（文件/skill 列表，Portal 渲染） |

`@` 提及支持通过 `/` 逐级查询工作空间子目录；选择目录会保留输入状态并自动进入该目录，选择文件才会插入不可编辑的引用标签。子目录查询期间候选项暂时为空时，`Enter` 和 `Tab` 也不会发送消息或切走输入焦点。只有输入开头或空白后的 `/` 才触发 skill 菜单，目录路径中的 `/` 会作为路径分隔符保留。

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
| `services/monacoEnvironment.ts` | Monaco 统一环境配置：`MonacoEnvironment.getWorker` language label 路由 + Vite `?worker` 同源 Worker 构造器 + `loader.config({ monaco })` |
| `utils/agentspacePath.ts` | 路径规范化、前缀重写、选择上下文和自然排序 |
| `utils/sha256.ts` | SHA-256 统一摘要：安全上下文优先 Web Crypto，远程普通 HTTP 回退纯 TypeScript 实现 |
| `hooks/useAgentspace.ts` | 目录/标签/锁/垃圾桶状态机及 HTTP/SSE 代际控制 |

---

## Hooks

前端采用 hooks 拆分状态管理逻辑，从原有的 `useWebSocket.ts` 中提取出独立职责：

| Hook | 职责 |
|---|---|
| `useWebSocket.ts` | WebSocket 连接编排与低频会话状态桥接；聊天事件写入 `chatRuntimeStore`，流式增量经 `StreamFrameBuffer` 按动画帧提交；Agent 忙碌时仍允许消息进入后端 FIFO；`history_sync.processing` 的 true/false 均作为服务端权威值覆盖本地处理状态 |
| `features/chat/chatRuntimeStore.ts` | Zustand 聊天运行时唯一高频状态：完整骨架、内容行、live 尾部、输入草稿、pending、滚动与资源；`toggleMessageCollapse(id, source)` 分别切换历史内容行与 live 行的气泡折叠状态，不改变 live 正典版本号；待结束流在 Footer 布局采样后固化，`linkStreamHistory` 按权威索引交接展开选择 |
| `features/chat/chatRuntimeController.ts` | History skeleton/page 请求代际、Abort、页去重、正典同步、Minimap 随机目标与资源懒加载 |
| `features/chat/useChatScrollController.ts` | `initializing/following/detached/minimap_dragging/returning` 五态追底与回底控制 |
| `useLlmProfiles.ts` | 从服务端读取 Profile；提供单对象创建/编辑/删除；浏览器仅持久化活动 Profile 名称，不保存 Profile 列表 |
| `useWebSocketConnection.ts` | WebSocket 连接生命周期管理：建立/断开/重连/心跳；消息入口按连接代际和当前 WebSocket 实例丢弃旧连接迟到消息，避免快速切换会话时污染当前状态 |
| `useSessionStore.ts` | 会话列表与低频元数据管理：获取/创建/归档/删除/标签/标题；审批模式、任务资源、Shell/Cron 和交互队列；主聊天消息、输入草稿与 pending 已迁移到 chat runtime store |
| `useSubagentManager.ts` | 子代理状态管理：注册/启动/停止/审批/列表 |
| `useUploadManager.ts` | 文件上传管理：拖拽上传、进度跟踪、文件选择器 |
| `useAgentspace.ts` | Agentspace 编辑器状态机：目录展开/选择、版本化标签、SSE 代际、逐文件锁、冲突和垃圾桶 |
| `useEdgeDrawer.ts` | 边缘抽屉三态状态机（hidden/peek/open），侧栏与顶部栏共用 |
| `useGlobalTooltip.ts` | 全局 tooltip 管理 |
| `useMessageCharacterHover.ts` | 主聊天区同角色悬停事件委托；直接维护消息公开属性，避免瞬时悬停进入 React 消息状态 |
| `useSessionSite.ts` | 会话网页状态：探测当前会话 `site/index.html` 并订阅 `site/` 的 Agentspace SSE；部署完成后自动显示右侧入口，资源连续变化时等待 1 秒安静窗口后热刷新，入口文件或目录删除/移走后自动隐藏 |
| `useSessionStage.ts` | 会话舞台层状态：由 `Layout` 单例探测 `stage/index.html` 并订阅 Agentspace SSE；入口文件作为部署提交标记，新内容版本经 1 秒安静窗口后只重建一次 iframe，非入口资源事件和 SSE resync 不重置运行态 |
| `useSessionChatStyle.ts` | 会话聊天区自定义样式状态：探测 `chat-style/index.css`，经 PostCSS 作用域处理（`@import` 拒绝、`.chat-area` 前缀、`@font-face` 校验 `ChatStyle-` 前缀），SSE 热重载 |

---

## Context

| Context | 职责 |
|---|---|
| `ConnectionDiagnosticsContext.tsx` | 连接诊断上下文：检测 WebSocket 连接状态、延迟、错误信息，为 UI 提供连接健康度反馈 |

---

## 主聊天历史数据流

- 主聊天默认水平间距使用 `.chat-area` 的 `--chat-message-inline-inset`：只有历史行添加 `.chat-history-row--history`，其左右内边距为变量的两倍；实时行则由 Footer 和行各提供一次内边距，使相同 Role 的新旧消息保持同一水平起点。
- 实时 Footer 末尾的 120px 留白属于完整列表的物理底部；被动追随只由 `useChatScrollController` 管理，实时内容提交后的布局阶段和列表高度变化使用同一个幂等追底入口。用户主动离底或主动改变消息高度时不追随。

- Gateway 通过 `history_sync` 只发送正典 History 元数据；前端 REST 取得全历史骨架和可见范围历史内容页。
- 全历史骨架始终保留完整逻辑顺序；Virtuoso 只挂载可视区附近行，离屏 iframe、Mermaid 和播放器会卸载并可在滚回时重建。
- `stream_done` 先登记待结束流，实时 Footer 在布局阶段判断气泡是否与视口相交后再冻结 live 行；`history_sync` 后 skeleton 后缀与末尾内容页成功合并，才按 canonical cutoff 清理对应 live 行。
- `stream_done` 先使 live 行进入待结束状态；`ChatLiveFooter` 在布局阶段只对结束瞬间与当前聊天区视口有正面积交集的普通 Agent 长回复记录展开选择，之后再固化流。视口外、工具消息与短消息维持既有规则；用户手动收起优先。滚出视口不会自动折叠。
- 后端在写入 History 后、`history_sync` 前通过 `system.stream_meta` 发送 `stream_id` 与 `history_index` 的权威关联。前端按该关联将已展开的实时普通长回复原子交接给 History 行，不以正文或顺序猜配；历史页重取保留同一行的手动折叠选择。旧服务不发送关联时安全退回历史默认折叠，不会遗留重复气泡；会话重建不跨刷新保存本次展开选择。
- 工具消息与普通长消息统一使用气泡 `collapsed` 状态，但入口互斥：工具摘要切换工具详情，普通长消息底部按钮切换正文限高；流式工具消息默认折叠且允许摘要展开/收起。历史页重取按相同 History 行 ID 保留用户折叠选择；其他未命中视口保护的 live 行在正典交接时恢复默认折叠。UI 折叠不提高 live 正典版本，避免交接后留下重复气泡。
- 位于底部时被动内容增长继续追底；追底使用 Virtuoso scroller 的物理底部而不是只对齐最后一个正典数据项，因此空骨架的新会话和动态 live Footer 同样有效。用户主动离开底部后不追随。近距离回底平滑，远距离先加载最新页再瞬时定位。
- 主聊天区逻辑 Minimap 同时绘制正典骨架和当前 live 行；拖动到 live 尾部等价于回到底部。
- `features/chat/useChatScrollController.ts` 统一从 Virtuoso scroller 采集 `scrollTop`、`scrollHeight`、`clientHeight`，供 Minimap 物理高亮与拖拽使用；拖动期间抑制内容页请求，释放时以最终物理位置反查目标范围。
- 主聊天区 Minimap 的 Canvas 背景按已测量/骨架估算消息高度加权绘制；高亮和拖拽只使用 scroller 的 `scrollTop` / `scrollHeight` / `clientHeight` 物理指标，估算高度不反向修改 Virtuoso 或追底位置。极薄高亮保持真实比例，另以透明扩展命中区保留可抓取性。子会话 Legacy Minimap 保留原 DOM 几何实现。
- 资源抽屉使用完整 History 资源索引，不依赖前端已加载正文页。
- 原“导出会话为 HTML”已移除；虚拟列表不保证浏览器原生查找命中离屏历史。

## 本地性能遥测

顶部栏命令菜单可打开本地性能遥测。默认关闭；开启后只记录批次数、字符数、请求耗时、逻辑范围、追底状态、长任务和 DOM/iframe 数量，最多保留 5000 条事件并导出 JSON，不上传消息正文、附件、工具参数或密钥。关闭时断开全部 observer 和采样 timer。

## 测试入口

- `npm run test:unit`：Vitest 单元测试。
- `npm run test:chat:e2e`：Playwright 桌面/移动聊天场景。
- `npm run test:chat`：测试 TypeScript 检查、Vitest 与 Playwright。

以上命令只由用户在运行时 fast仓库前端副本执行，开发助手AI不得在 origin仓库前端目录运行。

## Agentspace 编辑器行为

- 文件树固定使用“文件夹优先、文件在后、组内自然名称排序”，展开箭头与类型图标分离；单击文件直接打开永久标签。
- 侧栏可拖动、折叠并保存宽度；标签栏可横向滚动，不同目录的同名文件显示最短可区分父路径。
- 用户删除进入独立 `ws:.trash/` 垃圾桶节点；恢复冲突自动添加 `.restored-N`，永久删除与清空需要明确确认。Evolve Agent 的 `Delete` 不受此 UI 语义影响。
- 保存携带打开时的 SHA-256 版本。安全上下文（HTTPS 或 localhost）下前端通过 Web Crypto 计算版本；远程普通 HTTP 部署下 `crypto.subtle` 不可用时自动回退到纯 TypeScript SHA-256 实现，结果与服务端 Python `hashlib.sha256` 完全一致。外部修改干净标签时自动重载；脏标签保留本地内容并进入 DiffEditor 冲突处理。
- 内置 Agent 操作按回复轮次持有具体路径锁，只有命中路径变为只读；无关文件仍可编辑。
- 文件变化通过 SSE 实时同步。watcher 或连接不可用时状态栏显示降级，并保留手动刷新。
- 关闭脏标签提供保存/不保存/取消；页面离开使用浏览器原生确认，不跨刷新恢复草稿和标签。

### Monaco Worker 统一配置

- Monaco Editor 和 DiffEditor 的 Web Worker 加载入口由 `services/monacoEnvironment.ts` 集中配置，应用入口 `main.tsx` 在 React 渲染前调用一次。
- Worker 通过 Vite `?worker` 机制打包为带构建哈希的同源资源，远程普通 HTTP 部署下浏览器从当前应用地址加载，不依赖 CDN 或 HTTPS。
- `EditorArea.tsx` 和 `ConflictDialog.tsx` 不再各自执行 `loader.config({ monaco })`，只消费应用入口已配置的 Monaco 实例。
- 浏览器或 CSP 拒绝 Worker 时允许 Monaco 自身降级到主线程；项目不实现伪 Worker 或全局错误抑制。

---

## 样式组织

`src/styles/` 按功能拆分：

| 文件 | 说明 |
|---|---|
| `base.css` | 基础样式 |
| `variables.css` | CSS 变量 |
| `chat.css` | 聊天布局 |
| `messages.css` | 消息气泡与渲染 |
| `input.css` | 输入框（半透明背景模糊、玻璃高光边框与聚焦光晕；非空桌面会话的底部玻璃热区和 hidden/peek/open 三态抽屉动画；空会话及触摸设备保持完整形态） |
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
| `chat-style-scope.css` | 聊天区自定义样式作用域基础变量（`.chat-area` 可覆盖 CSS 变量锚点） |

## 动态沙盒空间管理弹窗

顶部栏命令菜单中的“动态沙盒空间”在所有会话中显示，打开用户直接管理全局动态沙盒空间的弹窗。弹窗通过 REST 接口完成列表查询、创建、完整更新和删除，不经过 Agent 工具审批；Sandbox 的名称、路径、描述、只读标志校验仍是唯一权威。空间名称不可修改，目录选择按钮只选择已有目录，手动输入允许暂不存在的绝对目录；删除仅删除配置，不删除目标目录和文件。


| `modal.css` | 模态窗口 |
| `popup.css` | 弹出层 |
| `splash.css` | 启动屏 |
| `skeleton.css` | 组件级骨架占位样式（shimmer 动画） |
| `onboarding.css` | 引导向导样式覆盖（react-joyride 主题微调） |

---

## 公开样式选择器契约

聊天区自定义样式（`chat-style/index.css`）面向 Evolve Agent 暴露的稳定选择器契约。内部类名不保证跨版本兼容，Evolve Agent 应优先使用以下 `data-*` 属性选择器：

| 用途 | 选择器 |
|---|---|
| 聊天区根 | `.chat-area` |
| 消息根 | `[data-chat-scope="message"]` |
| 消息角色 | `[data-message-role="user"]`、`[data-message-role="assistant"]`、`[data-message-role="tool"]` |
| 同角色联动悬停 | `[data-character-hovered="true"]` |
| 气泡 | `[data-chat-scope="bubble"]` |
| 正文 | `[data-chat-scope="content"]` |
| 思考内容 | `[data-chat-scope="reasoning"]` |
| 工具调用 | `[data-chat-scope="tool-call"]` |
| 工具详情 | `[data-chat-scope="tool-detail"]` |
| 代码块 | `[data-chat-scope="code"]` |
| 附件 | `[data-chat-scope="attachments"]` |
| 工具栏 | `[data-chat-scope="toolbar"]` |
| 元数据 | `[data-chat-scope="meta"]` |
| 等待状态 | `[data-chat-scope="waiting"]` |

## 构建与开发注意事项

- 前端构建由 `origin_agent/__main__.py` 在启动时自动执行：`<pkg_mgr> install && <pkg_mgr> run build`（包管理器优先 pnpm，回退 npm），运行在 `workspace/fast_agent_space/frontend/` 副本中。
- **绝对禁止**在 `origin_agent/frontend/` 目录下直接运行 `pnpm install`、`pnpm build`、`pnpm dev`、`npm install`、`npm run build` 等命令，以免污染源码目录。
- `origin_agent/frontend/` 不在仓库根目录，静态类型/IDE 感知可能不准确；不要依赖于此处的 TypeScript 类型检查结论。
- 由于前端构建是自动的，修改源码后由用户自行重启 `run.py` 触发重新构建。