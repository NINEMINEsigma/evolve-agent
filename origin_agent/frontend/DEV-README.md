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
│   ├── features/tabs/          ← Tab 导航体系：注册表、状态机、右侧 Tab 栏、主界面区域与十个 tab 内容层；含会话 Tab 能力探测 API/hook
│   ├── features/sessionMedia/ ← 中文相册、文案资源、共享预览与媒体详情窗
│   ├── features/characterAvatars/ ← 角色头像映射：zustand store、同步 hook 与子会话头像组件
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
│   │   ├── wsMessageDecoder.ts     ← 入站 JSON → 判别联合 WSMessage 解码器
│   │   ├── useSessionStore.ts       ← 会话列表与元数据管理
│   │   ├── useSubagentManager.ts    ← 子代理状态管理
│   │   ├── useUploadManager.ts      ← 文件上传管理
│   │   ├── useLlmProfiles.ts         ← Profile 列表、单对象 CRUD、活动名称、审批/元数据/三路全局多模态 Profile 状态
│   │   ├── useAgentspace.ts         ← Agentspace 文件浏览
│   │   ├── useSessionSite.ts        ← 会话网页探测与 WebSocket事件热刷新
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
│   │   ├── agentspaceApi.ts ← 独立 Agentspace 编辑器 REST/SSE 适配层
│   │   ├── chatAgentspaceEventBus.ts ← 聊天 WebSocket Agentspace事件页面内扇出
│   │   ├── fetchWithTimeout.ts ← 关键请求可取消15秒硬截止
│   │   └── fetchJsonWithTimeout.ts ← 覆盖响应体、JSON解析和解码的可取消硬截止
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
  - `remark-math`：识别 `$...$` 和 `$$...$$` 数学语法
  - `rehype-katex` / `katex`：将数学节点渲染为 KaTeX HTML 并提供公式样式
  - `react-zoom-pan-pinch`：图片缩放
  - `mermaid`：Mermaid 图表渲染
  - `react-virtuoso`：主聊天区可变高度虚拟列表
  - `zustand`：聊天运行时细粒度 selector store

---

## 关键组件

### 布局与导航

| 组件 | 职责 |
|---|---|
| `App.tsx` | 根组件，组合 Sidebar / Header / Tab 系统 / 各类弹窗 |
| `Layout.tsx` | 布局容器；`.main-content` 内为 `.tab-body`（主界面区域 `TabStage` + 右侧 Tab 栏 `TabRail`），会话锁定时整体替换为 `SessionLockOverlay`；组装 `TabRenderContext` 并持有 tab 状态机；非锁定分支以无 DOM `TabDataProvider` 包裹舞台与立柱并注入 `renderContext`/`previewBlocked`（性能遥测/灯箱/引导/右键菜单任一） |
| `Sidebar.tsx` | 会话列表、搜索、新建会话 |
| `Header.tsx` | 顶部工具栏、模型信息、设置入口；审批徽章按当前会话显示手动/脱手/YOLO，并在连接同步期间显示不可点击的“加载中”或“不可用”；`modelMenuBlocked` 仅由性能遥测、灯箱与引导向导触发 |
| `features/tabs/registry.tsx` | Tab 注册表：`TabId` / `TabDefinition` / `TabRenderContext` 类型与 `TAB_REGISTRY` 十条目（chat/resources/changes/media/variables/subagents/characters/site/llm/sandbox），内联 SVG 图标；新增 tab 需要注册条目、启用派生以及必要的数据能力来源 |
| `features/tabs/sessionTabCapabilitiesApi.ts` | 会话 Tab 能力 REST DTO/严格解码器/请求适配：只返回媒体数量和变量可见内容标志，不读取完整载荷 |

| `features/tabs/useTabSystem.ts` | 纯内存 tab 状态机：默认聊天 Tab、会话切换/刷新回聊天、活跃 tab 禁用自动回退；活跃状态携带 sessionId，render 同步将旧会话状态派生为聊天 Tab，避免新会话首次 render 误激活会话网页；持有 `useSessionSite` 的会话网页 HEAD 探测与 `useSessionTabCapabilities` 的媒体/变量内容能力探测；禁用 tab 切换静默忽略 |
| `features/tabs/TabRail.tsx` | 右侧 Tab 栏立柱（44px，移动端 40px）：图标 + tooltip + 激活指示条；无内容或能力未确认的 Tab 使用原生 `disabled` 禁用不可点击；对启用且非当前图标接入只读悬停/聚焦预览（`useAnchoredHoverPreview` + `useTabPreview`），窗口显示时 `aria-describedby` 指向小窗，预览与名称 tooltip 互斥 |
| `features/tabs/TabStage.tsx` | 主界面区域：grid 叠放全部 tab 外层，`visibility` 切换不卸载（保护聊天滚动与已加载 iframe 生命周期）；会话网页内部 iframe 首次激活后才创建，SiteTab 仅随 sessionId key 变化或外层卸载重建；切换时对 site iframe 执行 blur 兜底 |
| `features/tabs/TabDataContext.tsx` | 无 DOM 的唯一 Provider：持有 `useCharacterProfiles`/`useDynamicSandboxSpaces`/`useSessionMedia`/`useSessionVariables` 各一份，供正式 Tab 与只读预览共享同一快照；不随普通 Tab/会话切换重建，仅随锁定分支卸载；缺 Provider 时 `useTabData` 快速失败 |
| `features/tabs/useDynamicSandboxSpaces.ts` | 动态沙盒空间列表唯一持有者：只读列表与手动 `refresh`，不自动读取（激活读取仍由 SandboxTab effect 驱动） |
| `features/tabs/useTabPreview.ts` | 只读摘要数据组装：把 TabDataProvider / chatRuntimeStore / WebSocket 快照投影为纯 `TabPreviewInput` 并运行选择器；不发请求，仅资源预览且有下一项时运行本地 1 秒 tick |
| `features/tabs/TabHoverPreview.tsx` | 只读摘要卡片：复用 `PopupLayer`（外部点击/ESC 关闭显式 false），内层 `role=tooltip`，无按钮/输入/焦点陷阱/aria-live |
| `features/tabs/tabPreviewSelectors.ts` | 十个纯选择器 + `selectNextCronEvent`/`formatPreviewCountdown`/`truncatePreviewText`/`formatPreviewPayloadChars`/`formatPreviewRatio`；媒体双进度条与变量概要均在此组装 |
| `features/tabs/ChatTab.tsx` | 聊天 Tab 内容层：ChatArea + ClipboardPanel + 双倒计时条 + InputBar |
| `features/tabs/ResourcesTab.tsx` | 资源 Tab：四折叠区块（资源/Shell/Cron/动态端点），资源按 tab 激活懒加载 |
| `features/tabs/SubagentsTab.tsx` | 子会话 Tab：内部子级 tab 行（头像/名称/状态点）+ 单 `SubagentCard`，活跃项按会话持久化 |
| `features/tabs/CharactersTab.tsx` | 角色档案 Tab：全部子Agent 角色档案的只读配置目录；roleplay/task 分组列表 + 展开式详情（profile.md 全文、`[profile]` 引用提示词文件、LLM Profile 名称、错误全文），错误条目高亮、空态引导与“如需修改请在聊天中让主Agent操作”提示；运行状态仅当前会话视角（按角色名匹配 `subagentSessions`，优先 running）；提示词条目由 `buildPromptItems` 尽力对齐（正文与路径不保证一一对应）；档案数据从共享 `TabDataContext` 读取（唯一 hook 实例在 Provider，激活条件 `activeTab==="characters"`），不再直接调用 hook |
| `features/tabs/useCharacterProfiles.ts` | 角色档案数据 hook（Provider 内唯一实例）：激活即重拉 `GET /api/characters/profiles`（完整 JSON 截止 + 卸载取消）、`characters/` 相关 Agentspace 事件 1s 去抖刷新、请求代际控制防旧响应覆盖；载荷缺失或非数组按错误处理，不成功返回 `[]`；不依赖会话 ID（档案为全局数据） |
| `features/tabs/SiteTab.tsx` | 会话网页 Tab：首次激活且入口 ready、URL 可用时才创建 iframe/工具栏，未激活时只有外壳，不加载网页正文或脚本；局部 `hasBeenActivated` 在同会话切 Tab 后保留，registry 的 sessionId key 在切会话时重置，返回原会话也重新等待点击；首次加载后隐藏 Tab 仍沿用热刷新，入口删除后同会话重部署可自动重建。iframe 占剩余高度，刷新／全屏／新标签页／下载按钮栏在可视底部常驻并独占一行，不遮挡网页；不渲染顶部 56px 安全留白，接受现有桌面顶部栏浮层覆盖网页顶部；site 状态经 ctx 注入（提前运行的 HEAD 探测唯一源在 `useTabSystem`），全屏目标仍仅为网页视口 |
| `features/tabs/LlmTab.tsx` | 模型配置 Tab：去模态化（无遮罩/焦点陷阱/关闭按钮）；二级分页与 editor 状态机完整保留，草稿跨 tab 与跨会话保留，`beforeunload` 刷新守卫保留 |
| `features/tabs/SandboxTab.tsx` | 动态沙盒空间 Tab：全局动态沙盒空间管理，自命令菜单弹窗去模态化迁移；`activeTab` 懒加载键（切入即重拉列表）、viewing/editing 状态机与 REST 语义原样保留、`deleteTarget` 受控删除确认（复用 `LlmConfirmation`）、编辑态 `beforeunload` 刷新守卫、草稿跨 tab 与跨会话保留；列表改从共享 `TabDataContext` 读取（`spaces` 初次为 null 表示未读，成功 `[]` 才为空），本地 `operationError` 与列表 `error` 分开显示 |
| `ModelProfileMenu.tsx` | 顶部栏唯一会话待用模型选择浮层，支持触摸滚动、键盘、视口防越界和焦点返回 |
| `OnboardingTour.tsx` | 首次访问引导向导（react-joyride），spotlight 高亮 + 步骤动画驱动；步骤 4-6 锚定右侧 Tab 栏与资源/模型配置 Tab，经 `switchTab` 程序性切换 |
| `ErrorBoundary.tsx` | 错误边界，防止模态组件异常卸载整个 App |
| `SplashScreen.tsx` | 开屏动画，最少停留 800ms、最多 3000ms，可点击跳过 |
| `AgentStageLayer.tsx` | 聊天区背景层 Agent 舞台层 iframe（会话级 `stage/` 目录，透明、鼠标穿透）；仅负责渲染，由 `Layout` 统一提供舞台层状态 |
| `ChatStyleLayer.tsx` | 聊天区自定义样式注入层，以 `<style data-chat-style-scope>` 注入经 PostCSS 作用域处理的 CSS（会话级 `chat-style/index.css`） |

### 文件修改 Tab

`changes`位于资源/任务之后、媒体输入之前，是第十项注册后的只读目录树Tab。标题/状态/树节点/徽章中文来自`features/sessionFileChanges/zh-CN.json`，`labels.ts`显式校验；只显示实际文件，父目录仅为合成结构，目录目标不形成可见条目。文件颜色由`display_state`决定：created绿色、modified黄色、deleted隐藏；每个可见文件附最后一次操作徽章。无diff、正文、编辑、下载、撤销或统计起点说明。

`useTabSystem`持有唯一`useSessionFileChanges(sessionId, active, enabled)`，通过`TabRenderContext.fileChanges`给页面和预览；不在TabDataProvider重复实例化。`api.ts`严格解码六字段摘要和分页，使用现有`fetchJsonWithTimeout`的15秒截止；UTC字段为毫秒精度`+00:00`字符串，计数必须safe integer，Move允许路径条目数最多为revision的两倍。

解锁且`ws.isReady`的当前会话在页面可见时串行探测摘要，每请求结算后等3秒；归档也可查询，不依赖主History或ws:监听。Tab按钮始终可进入；摘要和完整树分别显示加载中、读取失败、当前没有可显示文件或过期状态。分页默认100行，仅激活时读取，切回Tab必重拉；摘要revision不变不重复拉正文。页面隐藏取消请求并暂停计时，恢复后刷新。主会话ID、请求代际、offset和单调revision共同阻止迟到覆盖；同类刷新最多合并一个pending请求。404使两链失效并清空，保留摘要再探测以覆盖删除取消；其他错误保留明确过期的同会话快照，不返回假零。

`FileChangesTab.tsx`沿用56px安全区和常驻挂载规则；共享CSS位于`session-file-changes.css`并由main.tsx导入，窄屏折行。当前页失败不撤销可用摘要，切页时旧offset正文不冒充新页。摘要selector只消费已有快照，即使未加载完整页也能显示真实总数；悬停/聚焦不发请求或建立计时器。

该功能仅做源码与定向只读审阅，未执行类型检查、构建或应用；中文、翻页、首个Move、多Agent独立写入、切会话、隐藏恢复及StrictMode生命周期需用户人工验收。

### 文件修改 Tab（目录树修订 2026-10-18）

`FileChangesTab`位于资源/任务之后，使用`useSessionFileChanges`唯一Hook提供的完整可见条目构造只读目录树。摘要的`file_count`只统计可见文件，`directory_count`统计可见目录；`operation_count`包含隐藏删除。命名空间、子目录、文件和实际目录条目按目录优先自然排序，合成父目录仅为结构节点，默认展开且只允许折叠/展开，不提供打开、编辑、删除、重命名或上下文菜单。实际文件节点只显示文件名，完整逻辑路径由目录层级表达，并保留在条目的悬停提示中。

持久条目增加`display_state`：`created`绿色、`modified`黄色、已存在文件删除时`deleted`红色可见，会话新增文件删除后隐藏。首次Write/Copy目的/Move目的为绿色；新增后修改仍绿色；删除后重建或再次成为Copy/Move目的为黄色；Move源按其历史状态显示或隐藏，目的按路径历史决定绿色或黄色。文件和实际目录条目都带最后操作徽章；合成父目录没有徽章。树只读颜色由`data-file-change-state`与`session-file-changes.css`控制。

Hook在激活后顺序取得全部可见分页，必须拥有同一revision的完整树才替换旧树；切会话、摘要revision变化、页面隐藏和404继续由请求代际控制。摘要预览不读取树，只显示已有摘要。目录操作保留为目录条目但不展开内部文件，只有合成父目录不计入统计。

### 媒体输入 Tab

显示标题「媒体输入」，注册id=media，位于资源Tab之后；只有会话 Tab 能力探测确认当前主会话 History 存在媒体实例时可打开，探测未知/失败或确认空 History 时禁用。探测只返回媒体数量，空 History 保留既有空态逻辑。相册式网格默认展示图片预览，只附名称/类型/发送状态角标，不在单元内堆元信息或开关表单；点击后在中文详情窗集中显示大预览、原信息和发送开关。单页100个实际图片/音频/视频实例，重复读取不合并，原展示资源Tab不变。

`features/sessionMedia/`含types.ts、api.ts、useSessionMedia.ts、zh-CN.json、labels.ts、MediaPreview.tsx、MediaGalleryTile.tsx、MediaDetailsWindow.tsx；旧MediaInputCard已移除，不保留双展示路径。UI中文值放正式JSON非代码资源，用Vite `?raw`和显式字段校验加载；仅此功能采用资源文件以兼顾UI中文与源码英文，不引入全局多语言框架或新依赖。registry复用labels.title，空态/分页/错误/可访问名称均中文，服务端或协议原文仅作可展开“错误详情”，不伪造翻译。

开关仍由服务端随History保存，前端不写localStorage。非乐观PUT成功才更新自身条目，GET epoch/pending集合避免旧页覆盖并发保存；未知结果中文提示并GET确认，409不当会话删除、单实例404移除该项。15秒截止覆盖正文/解析/解码，离Tab取消等待但不承诺服务端取消PUT。后端和useSessionMedia接口/低频刷新语义不改。列表响应在分页 `items` 之外携带六个全 History 聚合字段（开启/关闭数量、内联载荷字符、未知载荷数量），`useSessionMedia` 在成功响应时先独立提交 `aggregate` 再提交当前页；翻页期间旧聚合继续可用，切会话或404清空，读取失败保留旧聚合并标过期/错误。

图片挂img并原生lazy，CSS缩略显示原媒体；视频使用局部IntersectionObserver，仅临近视口挂metadata请求并保持静止/muted/无controls/autoplay，button单元内不嵌套交互控件或显式tabindex；音频以通用图标表示，不伪造波形。detail模式才有原生音视频controls，无autoplay；关闭/切资源/离Tab卸载时pause/清src/load。预览不调用转发/模型，原content端点可能取得完整媒体，并非后端缩略文件；不一次发100份视频载荷请求。

MediaInputTab只存selectedMediaId与焦点锚点，详情每次从当前权威页查找；切会话/页/Tab或实例删除即关闭，GET失败保留旧页并禁写。MediaDetailsWindow复用ModalWindow并portal到body，Esc/遮罩/关闭按钮走同一回调；初始焦点关闭按钮，Tab限制在详情边界，关闭后对有效锚点/刷新按钮恢复焦点，隐藏Tab不抢焦点。归档只读、处理中可改、下一请求生效与原多AgentNone后缀均不变。

网格顶部无常驻说明：短提示（点击看详情/独立实例语义）挂在带边框的标题文本上，经全局 data-tooltip 悬停显示；详情窗内转发仍收原媒体/新Read默认开启/保存本身不调用模型/下一请求生效等三条说明合并挂在发送开关标签文本（虚线下划线）的 data-tooltip 上，不再常驻渲染。useGlobalTooltip 的原生捕获监听器挂 document（覆盖 createPortal 到 body 的内容），tooltip.css 未改动。session-media.css独立控制密集网格/窄屏两列/大预览详情，其他Tab、聊天和全局ModalWindow样式不变。已按v2源码实施，未运行类型检查/构建/应用，由用户人工验收中文/默认预览/点击详情/键盘和播放器生命周期。

## 会话变量 Tab

右侧Tab注册表共十项，会话变量位于媒体输入Tab之后；只有会话 Tab 能力探测确认存在变量条目或可展示问题时可打开，探测未知/失败或确认空目录且无问题时禁用。进入后才读取完整变量池；`features/tabs/VariablesTab.tsx`使用既有TabRenderContext，不修改TabStage常驻挂载；目录折叠仅内存态，切会话清空。独立`session-variables.css`由main.tsx导入，TabRail纵向滚动保证短视口全部图标可达。

`features/sessionVariables/`包含types.ts、api.ts、useSessionVariables.ts、presentation.ts及VariableCard.tsx。typed GET `/api/sessions/<id>/variables`严格解码，15秒截止覆盖fetch与响应正文，解析前后检查时长（不能实时中断同步JSON.parse）；退出Tab/切会话取消请求，代际防旧响应覆盖。激活必重拉，现有chatAgentspaceEventBus文件/移动祖先路径命中后1秒去抖刷新，resync重拉，watcher_error提示降级；不新增长连接/轮询。刷新失败保留同会话旧数据并标过期，404清空旧池。

数字支持number/bar/gauge，auto在有效双边范围下用bar；无范围时显式降级number。percent=true显示原值×100加%，整数/范围检查仍来自服务端原值；clamp只限制绘图比例，越界真实数字常显。原文/meta可展开，输入错误、meta错误、constraint分开显示；scan_complete=false警告目录未完整读取。字符串/描述/原文只渲染React纯文本，不运行HTML/Markdown/脚本。SVG和目录按钮可键盘访问，用户只读，修改由Agent文件工具或已有Agentspace编辑器完成。

首版不提供回滚或原子结算；会话删除后文件留存。256/512KiB规模和1MiB输出等服务端限额明确拒绝，不让前端静默裁剪列表。后端验证由用户执行，尚未运行构建/类型检查。

卡片视图与工具调用卡片一致：默认只显示标签、类型、描述、数值/图形与问题；每张卡片有"原始 JSON"切换按钮，用与工具卡片相同的 `react18-json-view`（JsonView）渲染条目对象（含 raw_value/raw_metadata 原文与规范化字段），不显示文件路径，也没有独立"存储原值与元数据"折叠区。raw_metadata 由服务端去除键值分隔换行后的原文构成，值内部多行保留。

## 右侧 Tab 悬停预览

十个 Tab（chat/resources/changes/media/variables/subagents/characters/site/llm/sandbox）均登记只读摘要选择器（`TabDefinition.preview`，可选；缺失时该 Tab 摘要不可用但不影响编译）。悬停/聚焦「启用且非当前」的图标时在图标左侧显示只读摘要小窗；只消费页面已加载快照，不发请求、不刷新、不切换 activeTab、不新增轮询。悬停/焦点/几何逻辑在 `useAnchoredHoverPreview.ts`（泛型，尺寸等由 Options 注入，含 pending 250ms 开启、离开 120ms 关闭、Escape 抑制同次重开、模态/页面隐藏关闭、ResizeObserver 与 visualViewport 夹逼、全部 timer/rAF/observer 成对清理）；卡片在 `TabHoverPreview.tsx`（复用 `PopupLayer`，外部点击/ESC 关闭显式 false，内层 `role=tooltip`，无按钮/输入/焦点陷阱）。文案集中在 `features/tabs/tabPreviewLabels.json`，经 `constants/tabPreview.ts` 的 `TAB_PREVIEW_LABELS` 显式字段读取；`tsconfig.app.json` 仅启用 `resolveJsonModule` 支持正式 JSON 资源。

数据唯一来源是 Provider `TabDataContext.tsx`：`characters`/`sandbox` 为全局列表，`media`/`variables` 为会话级快照；四个 hook 各一份，正式 Tab（`CharactersTab`/`SandboxTab`/`MediaInputTab`/`VariablesTab`）与预览共享同一快照。会话资源（Shell/Cron/动态端点）改由 `useSessionStore` 的 Scope 快照（sid+generation）承载，`useWebSocket` 原 3 秒轮询经 `useSessionResourceSnapshot` 的 Token 与 Scope 校验提交，迟到响应不污染新会话；`useSessionMedia` 的 `aggregate` 独立于当前分页（翻页保留旧聚合，切会话/404 清空）。

媒体摘要用两根独立只读进度条（开启/关闭占比 = 状态数量/总数；总数为 0 不显示条），展示「内联载荷字符」与未统计数量（`inline_payload_chars=null` 的远程/非内联不计入字符和，但单独计数）。变量摘要显示总数/数字/字符串/无效/问题数与扫描完整性，严格区分读取中、尚未读取、空池、错误四态。资源摘要追加最近一项普通 Cron / WaitCron（只读 `is_wait` 身份），共同按 `next_run` 升序、`task_id` 字典序打破并列，本地倒计时仅在预览显示时运行。所有预览内容以 React 纯文本渲染，无 HTML/Markdown/iframe/密钥。已完成源码实施，未运行构建、类型检查或应用验收。

### 聊天区域

| 组件 | 职责 |
|---|---|
| `ChatArea.tsx` | 聊天区外层布局宿主；保持 Agent 舞台层、聊天区自定义样式、输入栏和轮次导航条的定位边界，消息序列委托给 `VirtualMessageList`；回到底部按钮在 ChatArea 挂载时常驻，不受滚动、初始化、内容数量或处理状态控制 |
| `features/chat/VirtualMessageList.tsx` | 基于 Virtuoso 渲染完整骨架的可视窗口；正文按页加载，live 尾部独立渲染 |
| `features/chat/ChatHistoryRow.tsx` | 单行 selector 消费，按 loaded / skeleton / page-error 三态渲染 |
| `MessageItem.tsx` | 单条消息渲染（文本、代码块、图片、工具调用卡片）；工具调用卡片以 `tool_call_id` 聚合请求、状态和结果，默认折叠并复用请求/结果的既有特殊渲染；通过 `data-character-name` 暴露角色显示名称，并在用户主动高度操作前通知滚动状态机；工具调用卡片和普通长消息的折叠入口互斥；`user`/`assistant` 头像按角色名查角色头像映射，命中渲染 `<img>`（onError 回退首字母） |
| `ToolCallCard.tsx` | 工具调用卡片的状态摘要、请求参数区、结果区、耗时和附件；展开详情顶部的“原始 JSON”按钮同时切换请求参数与结果正文，再次点击恢复默认预览。选择仅保留在当前挂载的卡片内，卸载后重新挂载恢复默认，不写入全局状态或浏览器存储。JSON 模式仅展示前端收到的数据，不额外获取后端内部字段；`_meta` 等内部字段不进入普通 JSON 展示，工具链注入的排队消息通过 `embedded_messages` 在结果区单独渲染。独立的嵌入消息、附件和耗时不随模式隐藏。 |
| `MessageBody.tsx` | 消息正文渲染；可选显示参数 `rawToolJson` 默认 `false`，仅影响工具分支。启用时绕过请求差异预览和结果特殊渲染，对象/数组复用 JSON 树，合法 JSON 标量使用 JSON 文本；非 JSON 文本和多模态内容块保留既有降级。未传参数的调用方保持默认预览，assistant 流式参数展示不受影响。 |
| `EmbeddedToolMessages.tsx` | 工具结果中嵌入的排队用户消息的独立渲染；显示消息正文、角色、来源和时间，不把内部字段原样展示为 JSON。 |
| `primitives/MarkdownRenderer.tsx` | 统一 Markdown、代码块、Mermaid、原始 HTML、图片和 KaTeX 数学公式渲染；规范化只作用于普通文本，行内代码和围栏代码中的公式标记保持原文；流式未闭合公式保持可见文本，未知 LaTeX 命令降级而不使消息树崩溃 |
| `MessageEditor.tsx` | 消息编辑器（编辑历史消息） |
| `MessageAttachments.tsx` | 消息附件展示 |
| `CodeBlock.tsx` | 代码块渲染与高亮 |
| `MermaidRenderer.tsx` | Mermaid 图表渲染 |
| `ChatContextMenu.tsx` | 聊天区右键菜单 |
| `RichInput.tsx` | 富文本输入（支持多行、快捷键） |
| `InputMorph.tsx` | ask/审批变形卡片（输入框顶部融合，非模态）；ask 侧为多问题分页向导——题号徽章（`2/3`）与左右切换箭头、按题选中 chips（多选 toggle / 单选替换，选中与文本草稿并存）、已答题圆点标记、非末题按钮"下一题"、末题"跳过"（整表回空）+ "提交"（始终可点，一次性回传按题 answers）；长标题单行 LED 跑马灯自动滚动（溢出检测后双份文本无缝循环，悬停暂停）+ `data-tooltip` 悬停全文；confirm 侧保持原因 + 参数 JSON 视图 + 三按钮。 |
| `InputBar.tsx` | 输入框、文件上传、发送按钮、功能按钮组（超宽收起菜单）、上下文徽章；普通单Agent桌面会话在已有消息后使用独立底部玻璃热区控制三态抽屉，空会话保留居中的完整输入栏；非空会话空闲时默认收缩，抵达聊天区底部时自动展开，离开底部后恢复收缩，热区悬停、聚焦及附件、审批、上传、录音、任务进度等交互期间保持展开；ask/审批变形同样遵循三态收起规则（不位于底部或不聚焦输入框时收起），变形待办通过热区呼吸光效与角标提示，聚焦变形按钮会钉住展开；中断按钮支持「正在中断」状态、禁止重复点击、失败后允许重试；审批确认内容先显示原因，再显示工具参数。ask 变形为多问题分页向导：InputBar 维护按题草稿字典（`askDrafts`）与当前页索引，`goToQuestion` 切页时保存/恢复 RichInput 草稿，RichInput 始终是当前题的回答输入框。 |
| `TokenRing.tsx` | 上下文用量环形徽章（Header 与输入栏共用） |
| `Lightbox.tsx` | 图片灯箱 |
| `SafeHtml.tsx` | 安全 HTML 渲染 |
| `RoundNavRail.tsx` | 轮次导航条：每条目对应一条 Role 为 `user` 的展示行（杠+内容文本一体，条目虚拟滚动，少轮次时列表垂直居中），杠按作者角色名 hue 散列着色（与头像一致），当前轮放大+花纹凸显并自动保持可见，点击跳转到目标消息（主聊天区经 `ChatVirtualListHandle.jumpToRound`，子会话卡片经本地 DOM 滚动）；当前轮按「已渲染行中最后位于视口参考线（视口顶 + 跳转偏移比例）以上的行」判定；条目在收起/展开两态共用同一套绝对定位布局——杠锚定条目右侧固定位置，文本是杠左侧的覆盖层，桌面 hover/focus 展开浮层只加宽背板并淡入文本，杠的坐标与间距不变；窄条常驻（无折叠按钮），触摸端点杠直接跳转 |
| `MentionMenu.tsx` | `@` 提及菜单（文件/skill 列表，Portal 渲染） |

`@` 提及支持通过 `/` 逐级查询工作空间子目录；选择目录会保留输入状态并自动进入该目录，选择文件才会插入不可编辑的引用标签。子目录查询期间候选项暂时为空时，`Enter` 和 `Tab` 也不会发送消息或切走输入焦点。只有输入开头或空白后的 `/` 才触发 skill 菜单，目录路径中的 `/` 会作为路径分隔符保留。

### 弹窗与对话框

| 组件 | 职责 |
|---|---|
| `TagEditor.tsx` | 会话标签编辑 |
| `primitives/ModalWindow.tsx` | 模态窗口基础原语 |
| `primitives/PopupLayer.tsx` | 弹出层基础原语 |
| `primitives/NoticeBanner.tsx` | 用户触发操作的持久错误/警告横幅；不会写入聊天 History，需用户关闭 |

### 面板与倒计时

子会话状态与后端统一为 `running` / `completed` / `terminated`。数量限制移除后不再保留旧 `waiting` 排队状态、标签或样式；输入栏只将 `running` 且可交互的子会话列为消息目标。此状态保存在页面内存并通过 WebSocket/快照同步，不涉及持久化迁移。

| 组件 | 职责 |
|---|---|
| `ClipboardPanel.tsx` | 剪贴板展示面板（聊天 Tab 内） |
| `SubagentCard.tsx` | 子会话卡片：单会话消息流 + 轮次导航条（子会话 Tab 内） |
| `TaskProgressPanel.tsx` | 任务进度面板（输入栏抽屉面内，聊天 Tab） |
| `PlaylistPlayer.tsx` | 播放列表播放器（资源 Tab） |
| `CronCountdown.tsx` / `SubagentCountdown.tsx` | 倒计时组件（聊天 Tab 内） |

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

### 主会话活动轮询与首字前气泡

聊天运行时通过 `useMainSessionActivityPolling` 每 1 秒查询当前会话状态；WebSocket 建立、恢复和页面重新可见时立即查询，断开、隐藏和卸载时停止并取消请求。`chatRuntimeStore` 先创建乐观空 assistant 流式行，再将权威 `activity_id` 收编；首个 `stream_id` 到达时与流事件共用唯一收敛函数进行原子换键。一个主会话活动可以先后拥有多个流式气泡，工具等待阶段不重复创建空气泡，终态会清理语义为空的占位行。

## Hooks

前端采用 hooks 拆分状态管理逻辑，从原有的 `useWebSocket.ts` 中提取出独立职责：

| Hook | 职责 |
|---|---|
| `useWebSocket.ts` | WebSocket 连接编排与低频会话状态桥接；入站消息经 `hooks/wsMessageDecoder.ts` 解码为判别联合 `WSMessage`（载荷守卫在 `features/chat/streamEventGuards.ts`），`handleMessage` 按 `type` 字面量分流后交给非流 helpers；聊天事件写入 `chatRuntimeStore`，流式增量经 `StreamFrameBuffer` 按动画帧提交；所有 user/assistant/tool/system 实时行使用明确 History 映射或保留为可诊断未映射行；工具请求和结果按 `tool_call_id` 幂等更新同一工具调用卡片；`tool_calls_discarded` 只接受当前会话的权威事件，按 `tool_call_id` 删除被批次声明丢弃的实时工具卡片及其映射/高度，不删除正典 History 正文；`agentspace_event`通过页面事件总线扇出给三个会话视觉 hook；关键请求超时显示持久通知并在 WebSocket可用时上报脱敏诊断；Agent 忙碌时仍允许消息进入后端 FIFO；`history_sync.processing` 的 true/false 均作为服务端权威值覆盖本地处理状态；永久删除只在 HTTP 明确成功后移除会话项，失败保留会话并显示错误，删除当前会话固定切换到“随意聊聊”；审批模式不写 localStorage/IndexedDB，只有 `HANDSFREE_MODE` 权威消息可更新三态模式，`APPROVAL_PROFILE_CHANGED` 只更新审批 Profile状态 |
| `features/chat/chatRuntimeStore.ts` | Zustand 聊天运行时唯一高频状态：完整骨架、内容行、live 尾部、输入草稿、pending、滚动与资源；通用 `liveId → historyRowId`关联把user/assistant/tool/system实时行提升到skeleton正典位置，工具请求和结果按 `tool_call_id` 幂等合并为同一工具调用卡片，REST内容页随后覆盖临时内容；`discardLiveToolCalls(ids, sessionId)` 只在事件会话等于当前会话时删除被丢弃的实时工具卡片、高度记录与 `liveId → historyRowId` 映射，正典 History 正文仍交给 `history_sync` 与内容页；未映射或History失败的行不按版本号清理；`toggleMessageCollapse(id, source)`分别维护历史与实时折叠状态 |
| `features/chat/chatRuntimeController.ts` | History skeleton/page 请求代际、Abort、页去重、正典同步、15秒超时局部错误与诊断 reporter、跳转目标页加载和资源懒加载 |
| `features/chat/useChatScrollController.ts` | `initializing/following/detached/returning` 四态追底与回底控制；实时提交和列表高度变化通过可取消、按浏览器帧合并的被动追底调度读取 Virtuoso scroller 物理底部；用户意图、消息高度操作和非 `following` 状态会取消待执行帧；`jumpToRound(rowIndex)` 按展示行索引跳转（未加载先取内容页，目标消息顶部落在视口中部略偏上，近平滑远瞬时） |
| `useLlmProfiles.ts` | 全局Profile目录CRUD、客户端列表、审批/元数据引用状态及图片/音频/视频三路全局回退引用；多模态状态一次 GET 恢复、三路独立 PUT，写成功与后续刷新失败分离，目录/引用请求按代际收敛 |
| `useSessionLlmSelection.ts` | 按会话名称存储、服务端恢复、读取取消与代际隔离、Profile重命名/删除处理 |
| `useLlmProfileEditor.ts` | 模型配置 Tab只读/编辑/新建状态、纯内存草稿、离开确认、删除替换、外部冲突和保存结果确认 |
| `useWebSocketConnection.ts` | WebSocket 连接生命周期管理：建立/断开/重连/心跳；会话状态预检和握手复检使用可取消15秒截止，超时报告后不误判删除；消息入口先按连接代际和当前 WebSocket 实例丢弃旧连接迟到消息，再由 `wsMessageDecoder.decodeWSMessage` 将原始 JSON 解码为判别联合 `WSMessage`（非法 JSON / 未知 type / 非法流式载荷 / 非法丢弃载荷在解码层丢弃），避免快速切换会话时污染当前状态；普通断开保留指数退避重连，永久删除的已建立连接按 4004 停止重连，握手拒绝则通过 `status.exists`二次确认后通知上层切换“随意聊聊” |
| `wsMessageDecoder.ts` | 入站消息统一解码器：`decodeWSMessage(raw)` 把原始 JSON 字符串转为判别联合 `WSMessage`；JSON 解析失败 / 非对象 / 未知 type 丢弃；`stream_delta` / `stream_done` 经 `streamEventGuards` 实际结构校验（嵌套类型、数字有限、整数、`extra=forbid`），非法载荷丢弃并输出不含正文 / 参数的诊断；`tool_calls_discarded` 经同一守卫校验 `session_id` / `stream_id` / `tool_call_ids` 后按判别联合收窄，非法载荷丢弃；旧非流事件暂仅基础检查后透传为 `NonStreamWSMessage`；日志只输出已验证且已知的消息 type |
| `useSessionStore.ts` | 会话列表与低频元数据管理：获取/创建/归档/删除/标签/标题；当前连接的审批模式显示与同步状态（服务端为唯一持久化真相）、任务资源、Shell/Cron 和交互队列；SYSTEM 消息 `session_title_updated`（首条消息自动标题写入）只精确更新单个会话条目的 title，不整体拉取；自动标题/标签/摘要/终结/合并错误通过全局操作通知展示，终结元数据警告不改变归档成功；主聊天消息、输入草稿与 pending 已迁移到 chat runtime store |
| `useSubagentManager.ts` | 子代理状态管理：注册/启动/停止/审批/列表 |
| `useUploadManager.ts` | 文件上传管理：拖拽上传、进度跟踪、文件选择器 |
| `useAgentspace.ts` | Agentspace 编辑器状态机：目录展开/选择、版本化标签、SSE 代际、逐文件锁、冲突和垃圾桶 |
| `useEdgeDrawer.ts` | 边缘抽屉三态状态机（hidden/peek/open），侧栏与顶部栏共用 |
| `useGlobalTooltip.ts` | 全局 tooltip 管理 |
| `features/characterAvatars/characterAvatarStore.ts` | 角色名 → 头像 URL 的 zustand 低频 store；主Agent条目优先防同名覆盖，`useCharacterAvatarUrl` selector 供消息与子会话组件订阅 |
| `features/characterAvatars/useCharacterAvatarSync.ts` | 挂载时拉取 `GET /api/characters/avatars`，订阅聊天页 Agentspace 事件（`SOUL.md.meta` / `characters/` 命中或 `resync`）后去抖重拉；失败静默保留旧映射 |
| `features/characterAvatars/SubagentAvatar.tsx` | 子会话 Tab子级 tab 与卡片标题的小尺寸头像；无 URL 或加载失败时不渲染 |
| `useMessageCharacterHover.ts` | 主聊天区同角色悬停事件委托；直接维护消息公开属性，避免瞬时悬停进入 React 消息状态 |
| `useSessionSite.ts` | 会话网页状态：提前通过 HEAD 探测稳定入口并跟随服务端重定向取得最终 `index.html` URL，不获取网页正文；订阅源 `.meta`/Agentspace 事件并以 HEAD 版本轮询兜底，资源连续变化时防抖刷新，入口或目录删除时禁用 Tab；探测唯一实例由 `features/tabs/useTabSystem.ts` 持有，SiteTab 经 ctx 消费，正文只在该会话首次激活会话网页 Tab 后由 iframe 加载 |
| `features/tabs/useSessionTabCapabilities.ts` | 会话 Tab 能力探测：请求媒体数量和变量可见内容状态，按 sessionId/generation 隔离；首次/会话切换未知时禁用，同会话后台 refreshing 保留已确认快照；监听 History 低频信号和变量 Agentspace 事件去抖刷新，不建立轮询 |
| `useSessionStage.ts` | 会话舞台层状态：通过稳定入口的服务端重定向取得最终 URL；Hook 不解析 `.meta`，以入口提交规则和版本探测自动刷新 iframe |
| `useSessionChatStyle.ts` | 会话聊天区自定义样式状态：服务端解析重定向，按最终 CSS URL 获取内容；PostCSS 作用域处理并按最终 URL重写 CSS `url()`，禁止 `@import` |

“模型配置”Tab（`features/tabs/LlmTab.tsx`，去模态化、无遮罩与焦点陷阱）由顶部分页按钮切换“模型配置”和“全局配置引用”，两个页面在 Tab 内保持挂载；编辑草稿跨 tab 与跨会话保留（内存态），`beforeunload` 刷新守卫保留。模型页按客户端→API端点→Profile纵向分组，详情同时只展开一个；先展示只读字段，再显式编辑。连接、生成参数、多模态分工、人格均使用常显分区标题，查看和编辑状态都不再单独折叠这些区块。Profile行只显示用途标签，不提供角色切换按钮。全局页分别显示审批/元数据用途卡和图片/音频/视频三张独立全局回退卡片；每张卡片使用独立的可用状态、保存状态、错误状态和清空确认。多模态卡片明确说明活动 Profile 引用优先，活动引用失败时不切换全局回退。引用选择立即保存到服务端，状态由 REST 响应与 WebSocket 广播收敛。

会话待用 Profile 选择只通过顶部栏修改。`useSessionLlmSelection` 使用 `evolve_session_llm_profile:<encoded sessionId>` 每会话键保存名称，本地明确选择优先；缺失时读取 `GET /api/sessions/{id}/llm-profile`。空sessionId不继承旧会话值；读失败不写空名称；目录加载失败不误判名称已删除。旧 `evolve_active_llm_profile` 全局键不再读取，也不猜测迁移。新建/分支/合并/旋转按新ID恢复服务端指针，不复制父会话未提交选择。发送消息与重新生成才提交名称，resume不受待用选择影响。读取请求完整覆盖响应正文的15秒截止，切会话/用户重选/名称广播使旧请求失效。

编辑草稿由 `useLlmProfileEditor` 持有且只驻留内存，切分页/搜索不会丢失；切Profile、收起编辑祖先、取消统一通过离开守卫（Tab 化后无遮罩/关闭按钮/Escape 关闭路径，`beforeunload` 刷新守卫保留）。外部变更不覆盖草稿，提示另存或放弃；写成功后的目录刷新失败显示警告，不再次创建；网络不确定保存先刷新确认。密钥不出现在只读详情或浏览器存储中。Tab 样式独立为 `llm-profile.css`（外壳由 `tabs.css` 的 `.llm-tab` 承载），不重写其他弹窗共享表单类。

顶部 `ModelProfileMenu` 通过 `PopupLayer` 挂到body，以fixed浮层和真实按钮支持触摸/键盘；触摸与折叠顶部栏均不依赖hover。pointerdown只判断外部关闭，选项通过click提交以保留触摸滚动；菜单追踪锚点与visualViewport变化，层级高于聊天但低于模态。仅选取/Escape关闭时归还触发按钮焦点，外部点击和新模态不抢焦点。

审批 Profile与会话审批模式是两个独立状态：清空、删除或改坏审批 Profile只改变 Profile名称/模型/可用性，不把当前会话改为手动模式。已有脱手模式继续显示，实际审批后端不可用时由服务端返回审批失败；YOLO不受影响。会话模式切换继续采用非乐观更新，只有专用权威回执到达后才解除“加载中”。

---

## Context

| Context | 职责 |
|---|---|
| `ConnectionDiagnosticsContext.tsx` | 连接诊断上下文：检测 WebSocket 连接状态、延迟、错误信息，为 UI 提供连接健康度反馈 |

---

## 主聊天历史数据流

### system 角色用户消息显示开关

顶部栏“⋮”命令菜单在桌面端和移动端提供“system 角色用户消息：显示／隐藏”开关。默认显示，以 `STORAGE_KEYS.SHOW_SYSTEM_USER_MESSAGES` 保存到浏览器 localStorage，所有会话共用；`chatRuntimeStore` 在初始化时恢复该偏好，切换、重置或重新加载会话时不重置，存储不可用时仍可在当前页面切换。

- `features/chat/messageVisibility.ts::isMessageVisible` 统一判断，仅隐藏 Role 为 `user` 且角色名为 `system` 的消息；普通用户消息、Agent 回复、工具卡片、系统状态和错误提示保持原有行为。
- 主聊天区在 `selectChatRenderRows` 完成历史与实时行关联之后过滤展示行。完整骨架、正文缓存、原始 History 索引、实时行和正典交接保持不变，重新打开即可恢复显示；空态和顶部/底部留白依据过滤后的展示行计算，不生成零高度占位行。
- Virtuoso、轮次导航条、分页加载和回到底部使用同一过滤后展示顺序。页请求先从展示行取原始 History 索引，再按页去重；隐藏行之间的长跨度不会导致额外拉取所有中间页。切换显示视为用户主动高度操作，取消旧回底动作并补取新的可见范围。
- 子会话卡片与其轮次导航条、工具结果嵌入消息复用同一显示规则；嵌入消息全部隐藏时不保留标题空壳。
- 该偏好只控制前端显示，不删除 History、不修改模型上下文、消息编辑/删除索引、后端协议或资源索引。

- 握手欢迎文本 `Connected to Evolve Agent` 由 `constants/ws.ts` 与 Gateway 发送处对应；前端仅在消息无 History 索引且不是业务系统状态时将其排除出聊天列表。首次连接和真实重连均如此，顶部连接状态、协议事件和其他系统消息不变，避免欢迎行留在实时 Footer 并在每轮正典交接后重新显露。
- 快速滚动的 `ChatSeekPlaceholder` 必须使用 Virtuoso 提供的原行 `height` 保留等高 border-box 外壳；内部复用普通骨架视觉，但不得以骨架估算高度替换长消息高度，缺失骨架数据时也保留空壳。用户验收可在开发者工具观察正文/快速占位切换前后的行外壳高度，允许亚像素误差，不要求肉眼辨认瞬间骨架。
- `useChatScrollController` 统一读取 scroller 的物理指标并更新 `scrollMetrics` 与 `atBottom`，底部阈值与 Virtuoso 一致。物理指标继续驱动自动追底与显式回底动作；回到底部按钮由 `ChatArea` 挂载时常驻，不受已有内容、初始化、物理离底、`followMode` 或主动回底状态控制。按钮点击仍复用 `ChatVirtualListHandle.returnToBottom()`；没有可滚动内容时保留按钮但不要求产生位移。用户主列表滚动立即中止被动追底及未完成回底动作，异步回底按动作序号和会话代际取消；失败保留按钮和现有错误状态。
- 用户主列表滚动立即中止被动追底及未完成回底，实际 scroll 采样在用户意图窗口内更新状态；单纯布局变化不解除离底浏览。回底动作带局部动作序号与会话代际，远距离加载检查页错误与已加载索引，下一布局帧才定位；失败保留错误和回底入口，用户新操作、会话切换与卸载均使旧动作失效。

- 主聊天默认水平间距使用 `.chat-area` 的 `--chat-message-inline-inset`：只有历史行添加 `.chat-history-row--history`，其左右内边距为变量的两倍；实时行则由 Footer 和行各提供一次内边距，使相同 Role 的新旧消息保持同一水平起点。
- 实时 Footer 末尾的 120px 留白属于完整列表的物理底部；被动追随只由 `useChatScrollController` 管理，实时内容提交、skeleton/liveRows 正典交接的布局提交和列表高度变化只申请一个按浏览器帧合并的追底任务，执行时重新读取 Virtuoso scroller 的最新物理指标。用户主动离底或主动改变消息高度时会取消待执行任务并停止被动追随；`atBottomStateChange(false)` 只报告布局状态，不独立派生追底任务。

- Gateway 通过 `history_sync` 只发送正典 History 元数据；前端 REST 取得全历史骨架和可见范围历史内容页。会话状态预检、骨架和内容页请求等待超过15秒会被主动中止：History显示局部错误与重试，顶层显示持久通知；WebSocket可用时同时上报不含正文、工具参数、附件或密钥的客户端传输诊断，Gateway只写 warning且不写聊天 History。
- 全历史骨架始终保留完整逻辑顺序；Virtuoso 只挂载可视区附近行，离屏 iframe、Mermaid 和播放器会卸载并可在滚回时重建。
- `stream_done` 先登记待结束流，实时 Footer 在布局阶段判断气泡是否与视口相交后再冻结 live 行；`history_sync` 后 skeleton 后缀与末尾内容页成功合并，才按 canonical cutoff 清理对应 live 行。
- `stream_done` 先使 live 行进入待结束状态；`ChatLiveFooter` 在布局阶段只对结束瞬间与当前聊天区视口有正面积交集的普通 Agent 长回复记录展开选择，之后再固化流。视口外、工具消息与短消息维持既有规则；用户手动收起优先。滚出视口不会自动折叠。
- 流式 WebSocket 事件类型化：`stream_delta` / `stream_done` 在 `types.ts` 中以 `StreamDeltaEvent` / `StreamDoneEvent` 两个具体结构化类型承载，`WSMessage` 改为判别联合（`StreamDeltaEvent | StreamDoneEvent | HistoryUpdatedEvent | NonStreamWSMessage`），非流式事件的 `type` 显式排除 `stream_delta`/`stream_done`，避免宽类型漏掉流式结构约束。后端 wire 使用顶层结构化 `tool_call` / `tool_call_delta`（含 `id`/`name`/`arguments` 或 `id`/`index`/`name`/`args_delta`/`phase`），不再将其塞进 `stream_delta.content` JSON 文本；可选字段后端 `None` 一律省略，不发送 `null`。`createStreamFrameBuffer` 只接收 `StreamDeltaEvent` 并直接消费顶层模型字段，取消 `JSON.parse(content)`。解码集中在独立模块 `hooks/wsMessageDecoder.ts::decodeWSMessage`，由 `useWebSocketConnection` 在 `ws.onmessage` 调用：统一把原始 JSON 转为 `WSMessage`，非法 JSON / 未知 type 丢弃；流式事件经 `features/chat/streamEventGuards.ts` 实际结构校验（嵌套类型、数字有限、整数，`extra=forbid` 拒绝非约定键含旧版 `content` 内嵌 JSON），非法流式载荷丢弃并输出不含正文 / 参数的诊断，不得静默成为其他消息或污染 store；`tool_calls_discarded` 经同一守卫严格校验 `session_id` / `stream_id` / `tool_call_ids` 后收窄；其余旧非流事件暂仅基础对象 / type 检查后透传为 `NonStreamWSMessage`，未在本次全面迁移。日志只输出已验证且已知的消息 type，避免原始 typeField 包含对象 / 正文导致泄露或字符串转换异常。`useWebSocket.ts` 的 `handleMessage` 接收已解码的 `WSMessage`，按判别联合 `type` 字面量分流，无需 `as` 断言；`stream_done` 不再猜测缺失 `stream_id`（由解码层校验保证非空），但保持先 flush 顺序、正文缺失 vs 空字符串及 metrics 语义。守卫使用 `constants/ws.ts::WS_IN` 常量；`tool_call.id` / `tool_call_delta.id` 后端仅 `str` 允许空，守卫不额外限制非空；`tool_call_delta.index` 仅整数不限定非负；`metrics` 沿用现有 `MessageMetrics`（int,int,int,float），不增加正数约束。
- 被批次声明丢弃的实时工具调用：下行 `tool_calls_discarded` 只承载 `session_id`、`stream_id` 与被丢弃的 `tool_call_ids`，不进入 History，也不替代工具结果。解码层严格校验这三个字段；`useWebSocket` flush 流式帧缓冲后调用 `chatRuntimeStore.discardLiveToolCalls(ids, sessionId)`，只在事件会话等于当前会话时按 `tool_call_id` 删除对应实时工具卡片、其高度记录与 `liveId → historyRowId` 映射。正典 History 的非追加结构变更由独立 `history_updated` 指令使旧视图失效并完整重载；普通追加仍由 `history_sync` 与内容页处理：丢弃事件不删除正典内容，也不按正文或数组顺序猜配被替换的 History 行，避免迟到事件或旧代际映射污染当前会话。
- 后端在写入 History 后、`history_sync` 前通过 `system.stream_meta`发送 `stream_id`、`history_index`和`live_history_links`权威关联；用户消息使用 `USER_MESSAGE.index`，工具结果使用实际 History 索引。前端在 skeleton 已存在目标行时把实时消息提升到正典位置，REST内容页覆盖临时内容后移除实时行；目标缺失或请求失败时保留原实时行并报告诊断，不按正文或顺序猜配。
- 工具消息与普通长消息统一使用气泡 `collapsed` 状态，但入口互斥：工具摘要切换工具详情，普通长消息底部按钮切换正文限高；流式工具消息默认折叠且允许摘要展开/收起。历史页重取按相同 History 行 ID 保留用户折叠选择；其他未命中视口保护的 live 行在正典交接时恢复默认折叠。UI 折叠不提高 live 正典版本，避免交接后留下重复气泡。
- 位于底部时被动内容增长继续追底；追底使用 Virtuoso scroller 的物理底部而不是只对齐最后一个正典数据项，因此空骨架的新会话和动态 live Footer 同样有效。最新流式消息即使超过一个视口，也不切换到消息顶部；实时提交与列表高度变化在同一浏览器帧内最多合并一次物理底部定位，避免长消息高度变化与 Virtuoso 校正互相竞争。用户主动离开底部后不追随。近距离回底平滑，远距离先加载最新页再瞬时定位。
- 主聊天区轮次导航条同时呈现正典骨架和当前 live 行中的 user 行；未加载正文的骨架行使用后端投影附带的 `content_excerpt` 摘要。
- `features/chat/useChatScrollController.ts` 统一从 Virtuoso scroller 采集 `scrollTop`、`scrollHeight`、`clientHeight`，供轮次导航条跳转使用；当前轮由 `ChatArea` 按 DOM 参考线判定——已渲染行（`data-render-row-id`）中最后一个顶部位于「视口顶 + `ROUND_NAV_JUMP_OFFSET_RATIO` 视口高度」参考线以上的行所归属的条目，与跳转落点同一条参考线，索引变化才更新高亮。
- 轮次导航条跳转复用「远距离先加载内容页再定位」模式：`jumpToRound` 在目标行未加载时先 `jumpToLogicalRow` 取页并核对加载结果，再以 `scrollToIndex`（align start + 补偿偏移）把目标消息顶部定位到视口中部略偏上；Virtuoso 条目偏移不含列表顶部安全区 spacer，`useChatScrollController` 的 `topSafeSpacePx` 参数将其补偿进 offset，使落点与 `ChatArea` 当前轮判定的 DOM 参考线严格为同一条线；近距离平滑、远距离瞬时。
- 资源 Tab使用完整 History 资源索引，不依赖前端已加载正文页。
- 会话离线导出使用独立完整History捕获与离线阅读器，不依赖当前可见DOM；虚拟列表仍不保证浏览器原生查找命中在线页面的离屏历史。导出接入及验收状态见下节和任务文件。

## 会话离线导出

顶部栏命令菜单的“导出离线网页”面向当前已恢复且空闲的主会话。流程为捕获完整现存 History、收集有界资源、准备 ZIP、服务端最终复核后才下载。展示不受在线分页、滚动、折叠或 system 消息隐藏偏好影响；包含思考、上下文扩展、工具请求/结果及嵌入消息，分享前明确提示敏感内容风险。子会话、会话变量、会话网页和普通非媒体下载附件不打包，原 History 不修改，也不调用模型。

`features/sessionExport/` 包含严格协议适配、有界依赖扫描/资源队列、离线打包和单次导出controller；`SessionExportDialog`提供确认、进度、缺失数量、失败和取消。切会话、锁定或开始处理会取消导出；全部异步终态按sessionId/generation核对，只有ZIP准备后verify成功才触发下载。资源明确不可用时占位并列清单，未知协议/服务故障和整体预算超限则整体失败，不截断历史冒充成功。

资源只读内联媒体及允许的同源文件/字体；跨源URL不代理抓取、不保留自动回源。CSS/HTML/经典脚本依赖只在明确支持范围内收集，不执行用户脚本发现依赖。chat style即使在线暂停也收集，离线初始开关继承导出偏好；stage重新运行，不承诺恢复内存状态，模块、Worker、远程API和未知动态加载明确提示。

`offline/` 是独立阅读器入口，复用消息内容组件和公开样式选择器契约，不导入App/Router/聊天运行时store/Monaco。独立Vite构建输出固定viewer.js/css，由专用只读路由提供，构建时把依赖中的 Node 风格 `process.env` 访问固定为浏览器可用的生产环境；归档页另提供最小兼容对象，保证 `file://` 双击时阅读器不会停留在初始占位文字。打包为自包含index.html、manifest.json和README.txt。解压后双击打开，不依赖本地HTTP服务、CDN或原Gateway。普通历史逐批挂载至全量，工具/思考/扩展可展开，原HTML保留纯源码查看；受支持舞台脚本仅在不给allow-same-origin的隔离frame执行。CSP与能力限制阻断正常网络加载，不宣称任意恶意代码的完整安全沙盒。

整体预算包括64MiB原History、96MiB捕获响应、20,000消息/40,000行、32MiB单资源、128MiB资源总计、1,024资源/16层依赖、192MiB归档输入；资源级超限明确占位，整体超限拒绝。单请求30秒、全导出180秒；客户端取消覆盖资源请求、队列、ZIP worker与Blob URL。源码已完成接入与定向静态审阅，尚未由开发助手AI运行构建、类型检查或离线验收。

全局tooltip的document捕获监听器必须先用`instanceof Element`校验event.target；mouseleave同时校验relatedTarget为Node或按离开视口隐藏，禁止用TypeScript断言把Document当HTMLElement再调用closest。该修复覆盖导出Portal窗口及既有tooltip，不改变视觉资源404探测语义。


## 历史更新指令与完整重载（2026-10-15）

独立 `HistoryUpdatedEvent` 仅允许固定 `history_updated` 与非空 `session_id`，解码器严格守卫；`NonStreamWSMessage` 排除该类型，`useWebSocket`在统一入口单独处理。当前会话事件先flush/cancel旧帧缓冲，再调用`chatRuntimeController.reloadHistory()`，不刷新网页或重连。Store同步提高generation、清旧骨架/正文/旧实时行/旧链接/旧高度/旧资源等历史视图状态，保留草稿、排队消息、processing、活动快照和显示偏好；liveVersion不归零。新的完整骨架和尾页由`applyHistoryReload()`原子安装，保留指令后新实时行、renderId、链接及待结束流，不再次调用clearLive/replaceSkeleton。

Controller持有当前重载Promise与最新待同步计数；旧REST即使忽略Abort也因generation不匹配而不能提交。同代际initialize/history_sync复用重载，后续普通同步合流；可见页、页重试和已请求资源读取等待该Promise。失败保留historyReloadRequired与可见错误，已有initialize重试按钮进入完整重试且不再清新流；成功后只在有更新计数时补后缀。首次连接/同session重连的onOpen记录liveVersion，首个history_sync完整重载并保留该连接边界后的实时数据；若已收到更新指令，则只合流而不二次失效。该重连机制恢复历史缓存，不承诺恢复断线期间未提交的流片段。普通追加用history_sync，未接受批次后缀用tool_calls_discarded；二者都不等于历史结构更新指令。以上仅源码实施与静态阅读，未运行类型检查、构建或应用验收。

## 本地性能遥测

顶部栏命令菜单可打开本地性能遥测。默认关闭；开启后只记录批次数、字符数、请求耗时、逻辑范围、追底状态、长任务和 DOM/iframe 数量，最多保留 5000 条事件并导出 JSON，不上传消息正文、附件、工具参数或密钥。关闭时断开全部 observer 和采样 timer。

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
| `round-nav.css` | 轮次导航条（杠/条目/当前轮花纹、展开浮层、折叠切换按钮） |
| `messages.css` | 消息气泡与渲染 |
| `input.css` | 输入框（半透明背景模糊、玻璃高光边框与聚焦光晕；非空桌面会话的底部玻璃热区和 hidden/peek/open 三态抽屉动画；空会话及触摸设备保持完整形态） |
| `dialogs.css` | 弹窗 |
| `drawer.css` | Tab 化后保留的共享区块样式：折叠区块、空态、任务/Cron 列表、资源网格、子会话子级 tab 行、site 工具栏 |
| `tabs.css` | Tab 导航体系：`.tab-body` 水平容器、`.tab-stage` grid 叠放、`.tab-panel-layer` visibility 切换、`.tab-rail` 右侧 Tab 栏、`.tab-panel-safe-top` 安全区、各 tab 内容层与 `dynamic-sandbox-*` 类族（动态沙盒空间 Tab） |
| `llm-profile.css` | 模型配置 Tab分页、纵向分组、只读详情/编辑、用途卡与窄屏适配布局 |
| `panels.css` | 任务进度/子代理面板 |
| `sidebar.css` | 侧边栏 |
| `header.css` | 顶部栏 |
| `lightbox.css` | 图片灯箱 |
| `context-menu.css` | 右键菜单 |
| `tooltip.css` | 工具提示 |
| `agentspace.css` | Agentspace 文件浏览器 |
| `agent-stage.css` | Agent 舞台层（聊天区背景层 iframe） |
| `chat-style-scope.css` | 聊天区自定义样式作用域基础变量（`.chat-area` 可覆盖 CSS 变量锚点） |

## 动态沙盒空间 Tab

右侧 Tab 栏的动态沙盒空间 tab（`SandboxTab`，原命令菜单弹窗去模态化迁移）。所有会话中可用，用户直接管理全局动态沙盒空间。Tab 通过 REST 接口完成列表查询、创建、完整更新和删除，不经过 Agent 工具审批；Sandbox 的名称、路径、描述、只读标志校验仍是唯一权威。列表以 `activeTab` 为懒加载键，每次切入 tab 重拉。空间名称不可修改，目录选择按钮只选择已有目录，手动输入允许暂不存在的绝对目录；删除仅删除配置，不删除目标目录和文件。删除确认使用复用 `LlmConfirmation` 的受控对话框；编辑态挂 `beforeunload` 刷新守卫。会话锁定（SessionLockOverlay）期间随 Tab 栏一起不可达。


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

## 资源清理状态展示

资源 Tab 的 Shell 停止按钮使用 `services/shellResourcesApi.ts` 解码真实停止结果。cleanup 未完成时保留该行并显示“资源清理待完成”，不把 HTTP 200 当成释放成功。文案来自 `resourceCleanupLabels.json`，不新增弹窗或自动轮询。

## 构建与开发注意事项

- 前端构建由 `origin_agent/__main__.py` 在启动时自动执行：`<pkg_mgr> install && <pkg_mgr> run build`（包管理器优先 pnpm，回退 npm），运行在 `workspace/fast_agent_space/frontend/` 副本中。
- **绝对禁止**在 `origin_agent/frontend/` 目录下直接运行 `pnpm install`、`pnpm build`、`pnpm dev`、`npm install`、`npm run build` 等命令，以免污染源码目录。
- 数学公式依赖（`remark-math`、`rehype-katex`、`katex`）随运行时 fast仓库前端副本安装；KaTeX 未知命令采用降级渲染，流式未闭合公式保持原文，块级长公式只在公式区域横向滚动。
- `origin_agent/frontend/` 不在仓库根目录，静态类型/IDE 感知可能不准确；不要依赖于此处的 TypeScript 类型检查结论。
- `tsconfig.app.json` 中针对测试文件名和 `src/test/`、`src/tests/`、嵌套 `__tests__/` 目录的排除模式，是隔离 fast仓库合并复制历史残留的正式构建防御；origin仓库仍严禁测试源、测试配置、测试夹具和测试专用入口，不得通过恢复测试依赖迁就残留文件。
- `tsconfig.app.json` 对退役的 `src/features/sessionMedia/MediaInputCard.tsx` 另有单文件精确排除：origin已移除旧Card及Props，fast仓库合并覆盖不会删除独有旧文件，因此历史残留仍可能被include=src扫描。此排除只阻止退役文件成为编译根，不恢复旧界面/类型、不屏蔽活跃依赖；若正式代码再次import它，仍参与TypeScript检查。不得扩大为整个功能目录排除。用户需把新构建配置同步到实际运行副本，本轮未运行构建验证。
- 由于前端构建是自动的，修改源码后由用户自行重启 `run.py` 触发重新构建。

### 统一聊天渲染行

主聊天区的历史骨架、历史内容页和实时消息统一投影为 Virtuoso 数据行。每行使用首次创建时确定的 `renderId` 作为 React/Virtuoso key；后端 History 行 ID通过 `historyRowId`关联，不在正典交接时替换渲染身份。实时消息完成后由同一行接收 `live_history_links`、History 正文和折叠状态更新，不再从 Footer 删除后重新挂载历史组件。

`ChatLiveFooter`仅承载等待指示器、最新历史页错误和底部安全留白。流结束可见性判断查询统一聊天列表中的渲染行，不能依赖 Footer 是否挂载。统一行的折叠状态和高度记录都按 `renderId`保存；Virtuoso 离开可视范围的正常卸载仍然保留。

历史内容页和正典关联可能乱序到达时，活动实时行通过正典交接屏障暂缓正文替换；只有后端明确的 `live_history_links`完成关联后，统一行才移动到对应 History 顺序位置。关联缺失、身份不匹配或页面失败时保留实时行，不按正文或数组顺序猜测。

### 重新生成的历史截断同步

`hooks/useWebSocket.ts` 消费既有 `SYSTEM.content` 中的 `regenerate_trim` 通知；先检查外层会话 ID 同时属于当前连接会话和聊天运行时，再由 `features/chat/regenerateTrim.ts::isRegenerateTrimPayload()` 校验原始类型、safe integer、`keep_count === message_index + 1` 与可空的两个 suffix。非法通知只给固定脱敏错误，不渲染为聊天正文，不按默认数量删除。JSON 解析异常边界不吞掉后续协议处理错误。

清理时点为收到服务端截断确认，而不是按钮点击或 POST 完成。通知处理同步取消旧流帧缓冲并重置旧结束事件标记，经 `chatRuntimeController.applyRegenerateTrim()` 取消旧历史请求，再由 `chatRuntimeStore.trimHistoryForRegeneration()` 单次提交保留 `[0, keep_count)` 的骨架/正文及目标 user 的新上下文扩展。`generation` 递增拒绝旧骨架、内容页、资源及活动轮询的迟到结果；已删除消息的实时尾部、映射、待交接页和高度记录同步失效，保留草稿、待发送记录、显示偏好、当前活动及其语义为空的占位。正在进行的回底动作因代际变化取消，`returning` 转为 `detached`，正常追底/离底偏好保持。

工具请求按骨架行及 `tool_call_id` 精确定位；结果范围来自 `toolCard.result.historyIndex`，实时结果缺索引时只可借用同一调用的正典结果索引。结果超出保留范围、身份冲突或已有结果却无可证明索引时，该锚点正文与 live 卡片失效，且删除已加载索引，后续可见页/尾页重新投影。资源索引失效后沿原懒加载重取，不回滚文件、变量池或 Shell/Cron 副作用。

正常路径保留既有前缀，不额外读取全骨架；仅本地尚缺目标 user 行时在新代际调用原 `initialize()` 补取。`replaceSkeleton()` 只替换正典骨架/正文缓存，不再隐式清空本代际新到的实时关联和待结束事件；旧流由明确的历史结构变化或会话边界失效。

重新生成 POST 按 hook 内的本地请求序号、对象身份、会话 ID 与 WebSocket 实例约束终态归属；本地序号不是服务端协议字段。截断确认后请求失败只报告错误，不把仍运行的活动置空闲、不恢复旧回复，实际活动由原服务端事件和状态轮询收敛。未确认的失败也只允许 `cancelOptimisticMainSessionActivity()` 清理严格属于该请求、仍 provisional 且语义为空的本地占位；已被实际流或轮询收编的气泡不清理。网络失败不代表服务端已停止。

重新生成的局部截断不新增后端字段、依赖或存储迁移；该改动原先延期的“断线漏通知且数量未下降”风险，在与历史更新指令合并后由本文件“历史更新指令与完整重载”一节的onOpen首次同步完整读取处理。regenerate_trim仍保留局部前缀，不替换为全量重载指令。已完成源码合并与定向静态审阅，未运行类型检查、构建或应用；用户按 `.tasks/2026-10-15_3-regenerate-stale-messages.md` 中有效验收矩阵验证。
