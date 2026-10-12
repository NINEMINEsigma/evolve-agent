# Evolve Agent — 开发者文档

本文档面向需要理解、修改或扩展 Evolve Agent 的开发者。若你只是想安装和使用，请阅读根目录的 `README.md`。

---

## 设计目标

Evolve Agent 是一个以**运行时自我代码进化**为核心目标的 Agent。其设计围绕以下原则：

- **快速失败与只崩溃软件**：逻辑之外的错误直接传播，禁止以通用捕获、空结果、默认请求或无依据的重试继续执行。HTTP 请求由 FastAPI 处理失败，普通返回值保持 BaseModel；该边界不会回滚共享内存或已完成写入，状态修改应优先采用先校验、准备数据、提交的顺序。原子写和 `finally` 资源释放仍是正常生命周期约束。
- **唯一持久化源码**：`origin_agent/` 是唯一的源码真相源。所有运行时副本均由其派生，修改只对源码生效。
- **运行时副本隔离**：`workspace/fast_agent_space/`、`workspace/slow_agent_space/`、`workspace/.fallback/` 彼此隔离，任何进化失败都不会直接破坏当前运行实例。
- **fast-slow-fallback 进化循环**：Agent 通过工具链修改进化目标副本，验证通过后触发热交换；若新代码运行异常，自动回退到备份。
- **会话级隔离 + 全局索引**：每个用户连接对应独立会话，会话历史、资源、子代理均按会话隔离，同时维护全局索引支持检索与管理。

---

## 源码与运行时布局

> workspace 及其内部目录（fast/slow 空间、agentspace、logs）均为**默认配置名**，可由 config.py 参数（`workspace_path`、`fast_agent_space_path`、`slow_agent_space_path`、`agentspace_path_name`、`logs_path_name`）覆盖；只有 `.fallback/` 为 run.py 硬编码固定名。下列以默认名描述。

```
origin_agent/              <- origin仓库：唯一持久化源码真相源（修改这里）
workspace/                 <- 运行时根（默认名；整体被 gitignore）
  fast_agent_space/        <- fast仓库：当前运行的 agent 副本（默认名）
  slow_agent_space/        <- slow仓库：进化目标副本（fork: 命名空间）（默认名）
  .fallback/               <- fallback仓库：上一次 fast 的备份 / 回退修复体（固定名）
  agentspace/              <- 工作空间：agent 工作目录（ws: 命名空间）（默认名）
  dynamic_sandbox_spaces.es <- fast 模式全局动态沙盒空间配置（独立 easysave 根对象）
  sessions/                <- 会话持久化（各主会话含 approval_mode.es 审批模式状态）
  logs/                    <- 运行时日志、进化状态（默认名）
```

## origin仓库内容边界

`origin_agent/` 会被整体派生为 fast仓库、slow仓库和 fallback仓库，因此只允许包含正式运行源码和构建必需文件。禁止在其中新增或保留自动化测试源、测试运行配置、测试夹具和测试专用入口。发现违规内容时，应从 origin仓库定向移除，不得通过复制过滤、`.gitignore` 或其他忽略规则隐藏；运行时仓库的复制语义保持不变。

---

## 启动与生命周期

1. `run.py` 将 `origin_agent/` 复制到 `fast_agent_space/` 和 `slow_agent_space/`。
2. 启动 `fast_agent_space/__main__.py`。
3. `__main__.py` 解析 CLI、构造 `RuntimeContext`、构建前端，随后 `asyncio.run(App(ctx).run())`；返回后由 App 解除关闭硬截止 watchdog。
4. `main.py::App` 只负责创建唯一 `Application`、平台信号处理（统一经 `RuntimeSystem.request_shutdown`）、等待关闭事件与退出码映射；不再持有 Gateway 实例、第二份关闭事件或各子系统清理逻辑。
5. `Application` 继承 `AsyncArchitecture`，`start()` 按固定拓扑顺序串行注册 21 个 `AsyncSystem`（RuntimeSystem→…→ToolDiscoverySystem→GatewaySystem），先用 graphlib 校验依赖图完整性，注册失败即按逆序注销已注册节点并传播；全部唤醒后 `RuntimeSystem.mark_running()` 并激活 Cron，输入接收才开放。`AgentspaceService` 的垃圾桶恢复与 watcher 在 `virtual_awake` 完成，启动失败直接传播（D2）。
6. `GatewaySystem` 启动 uvicorn，监听 `WS /ws/chat`、REST API 与 Agentspace SSE。聊天页的 Agent 舞台层、会话网页和会话聊天区自定义样式复用各自已有的会话 WebSocket接收 typed `agentspace_event`，不再建立额外 SSE；独立 Agentspace 编辑器继续使用一条 SSE。`server.py` 只含静态 `APIRouter` 与 `build_router_app()` 工厂，运行实例、socket、serve 任务与 ready 事件均由 `GatewaySystem`（最后唤醒、首先注销）持有；启动前端口占用按退出 0 的普通业务拒绝（`GatewayPortBusyError`），bind 竞态失败属启动失败。
7. 用户连接后，`SessionManager` 创建新的 `ParentAgentLoop` 实例并绑定 `FrontendSink`。

关闭由 `Application.shutdown()` 单一协调任务执行（重复请求等待同一任务）：

1. `RuntimeSystem.request_shutdown` 原子封闭新输入，记录首个关闭原因（失败永远优先于进化）；跨线程请求经 `call_soon_threadsafe` 唤醒主循环。
2. Gateway 封闭新业务（HTTP 503、WS 1001）但保留既有输出连接；SessionManager/SubAgentOrchestrator 冻结队列与 Inbox；CronRouter 停止安排 Timer；ToolRegistry/MCP 封闭新调用。
3. 停止各会话在途生成与工具调用，取消路由后台任务；解除待审批/提问等待。
4. 子Agent未消费 Inbox 落各自 History 并保存（临时Agent不持久化），未交接反馈经专用接口并入父会话关闭批次；主/多会话按 sequence 只落 History 一次，严格写盘，不触发模型、标题、摘要或旋转（D4/D5）。
5. History 刷新完成后才结束 SSE/WS（1001）与 uvicorn serve 任务。
6. 按装配逆序逐一 `unregister` 全部 System；任一必要写盘或资源释放失败合并上抛，进程以退出码 1 结束，绝不返回进化成功 -1（D6）。关闭硬截止 60 秒由 RuntimeSystem 的 daemon watchdog 兜底，超时 `os._exit(1)`；成功路径由 `__main__` 在 `asyncio.run` 及其线程池结束后解除 watchdog。

Shell会话由 `Application.current().get_system(ShellManager)` 统一持有。Agent 通过五个 Shell 工具跨工具调用操作 Windows ConPTY；单条命令完成或当前回复结束不触发停止，未完成任务或后续可复用时保留 Shell会话，只有明确需要销毁整个 Shell 时才调用 `StopShell`。WebSocket 断线不停止，自动旋转迁移到延续会话，手动终结、永久删除、进化热交换与应用关闭时停止。Shell 输出仅由 Agent 拉取，前端资源抽屉只显示元数据与停止按钮。单个 Shell会话的原生 PTY 访问通过生命周期同步边界收敛，停止流程先等待 reader 收尾再关闭原生对象，并保留超时兜底日志；该防御性处理不等同于已确认 `0xC0000005` 根因。

主会话永久删除使用进程内删除中标记封闭并发恢复：Gateway 先使现有 WebSocket失效并停止子Agent，再回收活动回复、运行时 Loop、消息队列、客户端信息和 Cron 注册，最后删除持久化索引/目录及附带资源。已建立连接以 WebSocket 4004关闭码停止旧 ID重连；握手前拒绝通过会话状态接口二次确认。显式恢复已经删除或删除中的 ID不会创建随机新会话，当前前端固定切换到“随意聊聊”。

进化流程：

1. Agent 通过工具链读取 `fork:` 命名空间中的源码，修改后写入 `slow_agent_space/`。
2. 调用 `validate_code` / `validate_frontend` 完成语法与构建验证。
3. 调用 `evolve_code` 完成深度验证；通过只在本次工具调用登记调用级进化意图（`ToolContext.request_evolution()`），`finalize_evolution` 不再直接修改运行器。
4. 所属 Loop 的 `store_tool_result` 在该工具结果严格保存成功后才消费意图并调用 `RuntimeSystem.request_shutdown(EVOLUTION)`；保存失败不产生进化成功。请求之后立即停止后续模型/工具，未执行的 tool_calls 补现有中断占位。
5. `run.py` 执行 `fast -> .fallback` 备份、`slow -> fast` 交换，重启 agent。
6. 若进化后运行出错，进入 fallback 模式，由 `.fallback/` 修复 `fast_agent_space/`。

---

## 模块地图

| 模块 | 职责 | 详细文档 |
|---|---|---|
| `entry/` | Agent 主循环与抽象：`BaseAgentLoop`、`ParentAgentLoop`、`ColloquyLoop`、`MultiAgentLoop`、`LoopSessionManager`、`AgentSink`、`ToolExecutor`、`StreamConsumer`、`SessionMessageQueue`（会话级消息队列）、`tool_post_dispatch.finalize_tool_result`（工具结果统一后处理） | [entry/DEV-README.md](origin_agent/entry/DEV-README.md) |
| `subagent/` | 子代理编排与生命周期：`SubAgentOrchestrator`、`SubAgentLoop`、`TaskAgentLoop`（临时Agent：无系统提示词、无持久化、纯文本回复即终止） | [subagent/DEV-README.md](origin_agent/subagent/DEV-README.md) |
| `gateway/` | WebSocket / HTTP 网关、消息路由、会话管理 | [gateway/DEV-README.md](origin_agent/gateway/DEV-README.md) |
| `component/` | 工具实现、审批系统（目录化）、MCP 桥接、Cron 路由、桌面自动化（`automation/`）、浏览器控制（`browser/`） | [component/DEV-README.md](origin_agent/component/DEV-README.md) |
| `abstract/` | 抽象层：LLM 客户端、工具注册表（含 `ToolsetEntry` 工具集元数据与渐进式加载）、AST 发现、技能、插件、MCP 客户端 | [abstract/DEV-README.md](origin_agent/abstract/DEV-README.md) |
| `frontend/` | React + Vite + TypeScript 前端 | [frontend/DEV-README.md](origin_agent/frontend/DEV-README.md) |
| `system/` | 基础设施：`Application`、`RuntimeContext`、沙盒、路径工具、会话存储、模板、LSP（`lsp.py`）、转换工具 | 见下文 |
| `evolve/` | 进化系统：代码交换与验证 | 见下文 |
| `entity/` | 常量与纯类型定义：`messages.py`（`BaseMessage` 体系）、`puretype/`（包）、`constant/`（按职责拆分的全局常量包，`__init__.py` 统一导出） | 见相关模块文档 |
| `templates/` | Prompt 模板 `.txt` 文件与模式切换（含 `modes/`、`multiagent/`、`subagent/`、`approval/`、`evolve/`、`llm/`、`messages/` 子目录） | 见 `system/prompt.py` |

---

## 端到端数据流

```mermaid
sequenceDiagram
    participant FE as 前端 (React)
    participant GW as gateway/server.py
    participant MR as gateway/message_router.py
    participant SM as gateway/session_manager.py
    participant PAL as entry/parent_agent_loop.py
    participant FS as entry/agent_sink.py (FrontendSink)
    participant LLM as abstract/llm/ (BaseLLMClient)
    participant TR as abstract/tools/registry.py
    participant APP as component/approval/

    FE->>GW: WS user_message
    GW->>MR: MessageRouter.route()
    MR->>SM: route to ParentAgentLoop
    SM->>PAL: process_message()
    PAL->>PAL: append_user_message, build system prompt + hooks + memory
    PAL->>LLM: chat_stream(BaseMessage[])
    LLM-->>PAL: StreamChunk (text delta / tool_calls)
    PAL-->>FS: emit_stream_delta / emit_tool_call
    FS-->>FE: typed stream_delta / tool_call JSON
    PAL->>TR: dispatch(tool_name)
    TR->>APP: request_approval (if needed)
    APP-->>PAL: approval decision
    PAL->>PAL: append tool result, continue loop
    PAL-->>FS: emit_stream_done
    FS-->>FE: typed stream_done JSON
```

主要阶段说明：

- **消息接收**：`gateway/server.py` 通过 WebSocket 接收 `user_message`，`gateway/message_router.py` 在路由内同步完成目标校验并登记输入记录，再由 `GatewaySystem.spawn_work` 启动准备任务，交给 `SessionManager` 分配到对应 `ParentAgentLoop`。
- **上下文组装**：`entry/agent_support/messages.py` 加载 `custom_hooks`、memory 上下文、system prompt，组装成 `BaseMessage` 列表。
- **流式生成**：通过 `abstract/llm/` 抽象层的 `BaseLLMClient.chat_stream()` 调用大模型（具体后端由 `custom_llm_client/` 插件提供），`ParentAgentLoop` 实时解析 `StreamChunk` 中的文本增量与工具调用。
- **工具执行**：通过 `abstract/tools/registry.py` 按名分发；工具集加载检查在 `dispatch`/`async_dispatch` 中统一拦截未加载工具，`ToolExecutor` 在审批前做前置快速拒绝；主会话 safe 始终免审批，write 在手动模式也直接执行；dangerous 在手动模式由用户审批，write/dangerous 在脱手模式由审批模型审批，非 critical 可由参数匹配的白名单放行；critical 在手动/脱手模式均由用户审批，YOLO 则全部免审批（`component/approval/`，不改变工具权限与执行校验）。工具定义按会话已加载工具集动态生成（渐进式加载），首轮只加载 `core` 工具集，其他工具集通过 `LoadToolset` 按需加载。手动/脱手/YOLO 模式由 Application持有的 `ApprovalModeStore` 按主会话缓存，并将 `SessionApprovalModeState` BaseModel直接交给 easysave保存到 `approval_mode.es`；Gateway连接时读取恢复后的服务端权威值，前端不持久化该模式。
- **前端推送**：实时事件（流式文本、工具调用、工具结果、任务进度、子代理更新）通过 `FrontendSink` 经 WebSocket 推回前端。正典聊天历史不再在连接时整体回放：Gateway 先发送 typed `history_sync` 元数据，前端再通过 REST 取得全历史骨架与可见范围的历史内容页；`History` / `history.es` 仍保持整体存储。工具请求和匹配结果在前端以每个 `tool_call_id` 一张工具调用卡片显示；工具结果内部 `_meta` 与 `_queued_messages` 不作为普通 JSON 正文展示，分别通过耗时元数据和 `embedded_messages` 独立渲染；孤立结果保留降级行。聊天页会话视觉所需的 Agentspace 变化也通过同一会话 WebSocket的 typed `agentspace_event`推送，页面内事件总线扇出到三个视觉 hook；独立 Agentspace 编辑器仍使用 SSE。会话状态预检、History骨架和历史内容页具有15秒硬截止；超时显示持久通知，并在 WebSocket可用时以不进入 History 的脱敏 `client_diagnostic`记录 Gateway warning。

- **流式事件类型边界**：`StreamConsumer` 将 `ToolCallRequest` / `ToolCallDelta` 实例直接传入 `AgentSink`；`FrontendSink` 构造 `StreamDeltaEvent` / `StreamDoneEvent`，仅在 `_send_stream_event()` 中序列化一次。工具增量是 WebSocket顶层对象，计时元信息保持 `MessageMetrics` 类型，不再经过内部 JSON往返或前端 `JSON.parse(content)`。两种事件在前端组成按 `type` 区分的联合，并在接收边界验证结构。Gateway未使用的字符串事件回调和启动注册已移除，其他非流式协议保持不变；部署时前后端同步更新并刷新旧页面。

- 前端主聊天区使用全历史骨架 + 历史内容页：Gateway 进程内 `History` 仍是正典对象，连接与轮次结束仅通过 `history_sync` 宣告消息数，正文按 History 索引范围读取。前端以 Virtuoso 只挂载可视行；工具调用请求与匹配的工具结果按 `tool_call_id` 合并为同一工具调用卡片，实时 user/assistant/tool/system 行都通过明确的 `live_id → history_row_id` 关联提升到正典位置，只有完成交接的行才从实时尾部清理。
- 主聊天区被动追底由 `useChatScrollController` 统一协调：实时提交、正典交接的布局提交和列表总高度变化只提交可取消的单帧追底请求，执行时以 Virtuoso scroller 的物理底部为唯一锚点；最新流式消息超过视口时不定位到消息顶部。用户主动滚动、主动改变消息高度或会话状态离开 `following` 时取消待执行追底；`atBottomStateChange(false)` 不独立触发反馈循环。物理指标统一驱动底部状态与回底按钮；异步回底按动作序号和会话代际取消，过期请求不得接管新操作。
- 快速滚动占位沿用 Virtuoso 原行高度，避免展开长消息在正文与占位之间切换时发生高度跳变。无 History 索引且非业务状态的握手欢迎文本仅作为连接通知，不进入聊天 Footer；其他系统消息及顶部连接状态保持不变。
- 流式结束时位于聊天视口内的普通长回复保留展开；后端在存入 History 后、对应 `history_sync` 前通过 `system.stream_meta` 发送 `stream_id`、History 索引和可选 `live_history_links`权威关联，前端在 skeleton 已包含目标行时先提升到正典位置，REST 内容页到达后覆盖临时内容并原子传递展开选择。缺失关联时保留实时行并记录诊断，不按正文或顺序猜测。
- 主聊天区右侧为轮次导航条（`RoundNavRail`）：每条目对应一条 Role 为 `user` 的展示行，点击跳转到该消息（目标消息顶部落在视口中部略偏上），当前轮高亮并自动保持可见；骨架 user 行由后端投影附带 `content_excerpt` 摘要。本地性能遥测由用户在顶部栏命令菜单手动启用，默认关闭且不上传消息正文。
- 顶部栏命令菜单提供 system 角色用户消息显示开关，默认显示并保存为浏览器全局偏好。关闭时仅隐藏 Role 为 `user` 且角色名为 `system` 的消息，覆盖主聊天历史/实时行、子会话及工具结果嵌入消息；轮次导航条和分页/滚动定位使用过滤后的展示行顺序，完整 History、原始索引、正典交接与模型上下文保持不变，系统状态和错误提示不受影响。

---

## 子代理与多代理系统

Evolve Agent 内置两套多代理运行时：

### 子代理模式（SubAgent）

- `subagent/orchestrator.py` 的 `SubAgentOrchestrator` 是 framework `AsyncSystem`，按父会话维护子代理上下文；它通过 `SessionManager` 查询真实父会话，不再依赖启动用 Loop。子Agent输入由 `InputDeliveryBuffer` 记录，停止先等待任务收尾再刷新Inbox和保存普通子AgentHistory，反馈经 `SubAgentFeedbackDelivery` 一次性交接。
- 每个子代理是独立的 `SubAgentLoop`（继承 `BasePrivateChatAgentLoop`），拥有独立的 LLM 配置与历史；启动过程登记启动状态，不设置活跃数量上限，显式历史加载失败会拒绝启动并回滚，不会静默从空历史继续。
- `subagent/profile.py::CharacterProfileResolver` 每次动态扫描 `ws:characters/roleplay/` 与 `ws:characters/task/`，从 `profile.md.meta` 的 `[llm_profile]` 解析当前 LLM Profile、读取 `[description]` 简介，并按 `[profile]` 的多行逻辑路径加载多个独立系统提示词；角色名称跨类型全局唯一。主Agent系统提示词每次构建时注入当前可运行角色的名称、类型和简介。
- `component/multiagenttools/` 提供动态发现、启动、对话、审批、停止和列表工具，不再提供显式注册工具。
- 子代理的工具可见性由 `availability` 位掩码控制：通常只能看到标记为 `SUBAGENT` 或 `EVERY` 的工具。
- 审批结果和子代理输出会周期性注入父 Agent 的消息循环。

详见 [subagent/DEV-README.md](origin_agent/subagent/DEV-README.md)。

### 临时Agent（TaskAgent）

- `RunTaskAgent` 只接收单个 prompt，并在调用发生时取得父主会话活动 LLM Profile的非持久化深快照；后续 Profile切换或编辑不影响已经启动的临时Agent。
- 临时Agent无系统提示词、无历史持久化，产生纯文本结果后立即终止；不设置临时Agent数量上限。
- 工具范围严格为“已加载工具集 ∩ `TASKAGENT` 可用范围 ∩ `safe` 危险等级”，定义生成和执行期均校验，因此不会进入审批流程。
- 初始工具集状态默认从 `core` 开始；符合相同权限交集的 `LoadToolset` 可以加载其他工具集，但加载本身不扩大授权范围。

### 多 Agent 协作模式（MultiAgent）

- 通过 `enter_multi_agent` 工具切换，不可逆。切换后所有用户消息由 `MultiAgentLoop` 处理。
- 所有参与 Agent 共享同一份对话历史，每条用户消息触发一轮并发响应。
- Agent 可在回复中通过 `response_characters` 指定下一轮的响应者，按轮次级联直到无人指定或达到最大深度。
- `MultiAgentWorker` 是单个 Agent 的一轮响应执行器，由 `MultiAgentLoop` 创建并聚合 token 统计。
- 多 Agent 模式下 multiagent 工具集被禁用。

### Colloquy（随意聊聊）

- 内置的固定闲聊会话（session ID `____buildin_colloquy__`，常量 `COLLOQUY_SESSION_ID`），启动时由 `main.py` 调用 `SessionManager.ensure_colloquy_session()` 确保存在，不出现在普通会话列表中且不可删除。
- 由 `entry/colloquy_loop.py::ColloquyLoop`（继承 `ParentAgentLoop`）处理，仅暴露白名单工具集（`COLLOQUY_TOOLSET_WHITELIST`，filesystem/core/shell/python 等，不含进化工具），超长历史按 `COLLOQUY_COMPRESS_RATIO` 滑动窗口压缩为摘要。

---

## 路径沙盒

所有文件操作必须使用逻辑路径前缀，禁止裸路径、`..` 遍历和绝对路径。

> 下表映射目录所涉 workspace 内部名为**默认配置名**，实际由 config.py 参数决定（`slow_agent_space_path`、`agentspace_path_name` 等）；`.fallback/` 为硬编码固定名。权威映射见 `system/sandbox.py::namespace_bases()`。

| 前缀 | 映射目录 | 模式 | 用途 |
|------|----------|------|------|
| `fork:` | `workspace/slow_agent_space/` | fast | 读写进化代码 |
| `ws:` | `workspace/agentspace/` | fast / fallback | 通用 I/O |
| `fix:` | `workspace/.fallback/` | fallback | 修复目标 |
| `skills:` | `skills/` | fast / fallback | 技能读写 |
| `third:` | `third/` | fast / fallback | 第三方子模块（只读） |
| `custom_hooks:` | `custom_hooks/` | fast / fallback | 自定义钩子（只读） |
| `custom_llm_client:` | `custom_llm_client/` | fast / fallback | 自定义 LLM 客户端（只读） |
| `custom_tools:` | `custom_tools/` | fast / fallback | 自定义工具（只读） |
| 用户定义的动态前缀 | 用户授权的规范化绝对目录 | fast | 全局共享；每项为工具层只读或读写 |

fast 模式的动态沙盒空间由 Application 持有的 Sandbox 单例统一管理，配置直接以
`DynamicSandboxSpaceData` 根对象保存到 `RuntimeContext.workspace/dynamic_sandbox_spaces.es`，
不属于 `ws:`、会话或 LLM Profile。目录可暂时不存在；不存在时配置保留但该空间
不可读写，目录恢复后自动恢复。所有 Agent 共享动态映射；只有普通模式和多Agent模式
主Agent可在加载 `sandbox` 工具集后，通过 critical 的 `AddSandboxSpace` /
`RemoveSandboxSpace` 修改。用户也可从所有会话的右侧 Tab 栏打开动态沙盒空间 Tab，
通过 REST 接口直接查询、创建、更新和删除配置；更新不通过删除后重新添加，空间名称不可修改。
随意聊聊会话只能使用已有空间，临时Agent无动态空间提示词。
动态只读权限与现有只读空间相同，仅约束标准 Sandbox 文件 API，并非 OS 级 ACL。

**没有 `self:` 命名空间** — agent 不能读取或修改自身运行时副本，进化完全通过 `fork:`/`fix:` 实现。

沙盒实现位于 `system/sandbox.py`（权限表 `_PERMISSIONS`，映射 `namespace_bases()`）。

---

## Agentspace 编辑器数据流

- 用户文件操作由前端 `agentspaceApi.ts` 调用 Gateway typed REST，再委托 `Application.current().get_system(AgentspaceService)`；Service 负责路径校验、按目录优先自然排序、内容 SHA-256 版本与原子写。
- 前端本地版本计算优先使用浏览器原生 Web Crypto；远程普通 HTTP 部署下 `crypto.subtle` 不可用时自动回退到纯 TypeScript SHA-256 实现（`utils/sha256.ts`），结果与服务端 Python `hashlib.sha256` 完全一致，不改变版本/冲突流程。
- 用户删除进入 `ws:.trash/` 的事务垃圾桶；Evolve Agent `Delete` 的永久删除与审批语义保持不变。
- 内置 Agent 文件工具在明确接触 `ws:` 路径时登记回复轮次文件锁，主Agent、参与Agent、子Agent与临时Agent在各自回复收尾后释放。
- `watchdog` 把外部变化送入事件总线。独立 Agentspace 编辑器通过 `GET /api/agentspace/events` SSE 接收缓存失效信号；聊天页会话视觉通过已有会话 WebSocket的 `agentspace_event`接收同源事件，避免每个视觉功能建立长连接。两者都通过 REST 重新取得权威快照；依赖不可用时界面显示同步降级。
- 编辑器保存携带预期版本；冲突返回 HTTP 409，前端保留本地草稿并显示 Monaco 差异比较，禁止静默覆盖。
- Monaco Editor 和 DiffEditor 的 Web Worker 由 `services/monacoEnvironment.ts` 集中配置，应用入口在 React 渲染前初始化；Worker 通过 Vite `?worker` 打包为同源构建资源，远程普通 HTTP 部署下从当前应用地址加载。

---

## 扩展点

系统提供多个热扩展点，无需修改核心源码：

- **自定义工具**：在 `custom_tools/` 目录下编写 `.py` 文件，导出顶层同步 `register_tools(registry: ToolRegistry, ui_events: UIEventRouter) -> None`，工具与事件均在入口内注册；ToolDiscoverySystem 按 AST 发现后显式调用，导入期不操作运行时实例。
- **自定义 LLM 客户端**：在 `custom_llm_client/` 目录下编写 `.py` 文件，暴露 `create_llm_client(runtime_context, profile)` 工厂函数，返回 `BaseLLMClient` 子类实例。内置 `openai_client.py`、`anthropic_client.py`、`kscc_client.py` 和 `lmstudio_client.py`。
- **自定义钩子**：在 `custom_hooks/` 下实现 `hook_tag_name()` 与 `hook_message()`，返回的上下文块会追加到用户消息末尾。
- **本地模型**：在 `custom_models/` 下放置 `.gguf` 文件，可作为审批模型自动加载。
- **技能文件**：运行时 `skills/` 目录存放 `SKILL.md`，通过 `load_skill` / `list_skills` 工具加载。`pre-skills/` 提供参考模板。
- **插件**：`abstract/plugins/discover.py` 基于目录扫描插件，解析 `plugin.yaml`，启发式检测 provider 类型。
- **MCP**：`MCPSystem` 读取并校验 `mcp_config.json`，由 `MCPCore` 连接服务器并注册远程工具；`component/mcp_tools.py` 只通过 `register_tools` 声明 `MCPRefresh`。OAuth 按 Provider 独立回调端口并显式持有 `MCPOAuthManager`，认证任务、HTTP 回调线程与 401 dedup 均有完整归属；stdio 进程由 `MCPStdioTransport` 直接持有真实句柄和独立 cleanup task，不猜测宿主 PID。关闭时 `close_admission` 拒绝新工作，`stop_calls` 确认请求/连接任务实际退出，`shutdown` 等待 OAuth、stdio、cleanup 全部完成后才释放；资源未退出不伪装成功。`abstract/mcp/schema.py` 在注册和 sampling 的 provider 边界规范化工具参数 schema。
- **Agent 舞台层**：会话级背景渲染层，位于聊天区背景之上、聊天气泡之下。Agent 通过 `ws:sessions/<session_id>/stage/` 目录写入 `index.html` 及图集/动画资源，前端以透明 iframe 渲染，默认鼠标穿透。`Layout` 统一管理舞台层探测并订阅聊天 WebSocket扇出的 Agentspace事件，AgentStageLayer 只负责渲染；`stage/index.html` 是部署提交标记，资源应先写、入口最后写，只有入口文件的新内容版本经 1 秒安静窗口后重建 iframe。`resync` 和非入口资源变化不会重置正在运行的舞台。独立于会话网页 `site/`。系统提示词通过 `build_session_stage_block()` 注入。
- **会话网页**：独立于 Agent 舞台层的完整网页预览。Agent 通过 `ws:sessions/<session_id>/site/` 部署 `index.html` 及引用资源；前端探测入口文件并监听聊天 WebSocket中的该目录 Agentspace事件，部署完成后自动显示右侧会话网页入口，资源连续变化时等待 1 秒安静窗口后热刷新 iframe，入口文件或整个目录被删除/移走后自动隐藏入口。
- **会话聊天区自定义样式**：会话级聊天区 CSS 覆盖层。Agent 通过 `ws:sessions/<session_id>/chat-style/index.css` 写入 CSS，前端探测并经 PostCSS 作用域处理后注入 `<style>` 标签，仅作用于 `.chat-area` 聊天区。禁止 `@import`，允许 `@font-face`（`ChatStyle-` 前缀）和 `@keyframes`。CSS 缺失、超限（256 KiB）或作用域处理失败时恢复默认样式。用户可通过顶部栏命令菜单独立暂停 Agent 舞台层和聊天区自定义样式。系统提示词通过 `build_session_chat_style_block()` 注入。

---

## 基础设施与未拆分模块

- **会话视觉资源重定向**：`stage.meta`、`site.meta`、`chat-style.meta` 的 `[redirect]` 由 Gateway 服务端单层解析，稳定入口用 HTTP 307 指向有效逻辑目录；非法配置静默回退，前端 Hook 只消费最终 URL并自动刷新。
- **会话视觉资源状态**：会话 status REST 和 `session_meta_hook` 读取的非持久化 `visual_resources`，包含 stage/site/chat_style 的状态、源目录、有效目录、重定向标志和错误原因，不写入 History 或会话索引。

### system/

- `system/application.py`：`Application` 进程级唯一单例（继承 `AsyncArchitecture`），通过 `Application.current()` 访问。`start()` 用 graphlib 校验依赖图后按固定拓扑顺序串行注册全部 21 个 System，全部唤醒后 `mark_running()` 并激活 Cron；`shutdown()` 是唯一关闭协调任务，先业务停止与 History 提交，再按逆拓扑 `unregister`（RV10 顺序），失败合并上抛并保留 RuntimeSystem 失败记录。`Application` 不保留服务镜像字段，也不暴露 `runtime_context` 属性；各业务系统经类型化 `app.get_system(RuntimeSystem).context` 取得唯一 `RuntimeContext`。
- `system/runtime.py`：`RuntimeSystem`（`AsyncSystem`），持有唯一 `RuntimeContext`、应用状态、输入接收同步边界、跨线程关闭请求与失败记录；还持有进程级**主Agent角色名**（启动时从 `ws:SOUL.md.meta` 的 `[character_name]` 读取，缺失回退到 `DEFAULT_MAIN_AGENT_CHARACTER_NAME`，运行期由 `RefreshIdentity` 工具刷新）。`context` 为只读属性；完整应用装配在 P22 完成，中间阶段代码不具备启动条件。
- `system/character_avatars.py`：角色头像映射的纯函数组装（非 System、无缓存）。`collect_character_avatars()` 实时读 `ws:SOUL.md.meta` 与 `ws:characters/roleplay|task/*` 的 `[avatar]` 键，产出「角色名 → /files URL」条目（`CharacterAvatarsResponse`）；仅校验可读、是文件与 ≤`AVATAR_MAX_BYTES`（5 MiB），不限扩展名。Gateway `GET /api/characters/avatars`（no-store + `to_thread`）调用；声明无效仅条目级 error，不阻断。
- `component/approval/system.py`：`ApprovalSystem` 已改为 AsyncSystem，依赖 RuntimeSystem、LLMProfileStore，持有唯一模式Store、后端管理器和白名单Store。类型化入口是 `Application.current().get_system(ApprovalSystem)`；模型审批作为请求级任务等待，生命周期及清理失败继续传播，完整应用装配尚待后续阶段。
- `entry/agent_sink.py::FrontendSink`：已继承 `AsyncSystem` 与 `AgentSink`，依赖 RuntimeSystem；无参构造，`virtual_awake` 取得 RuntimeSystem 并创建 TaskOwner。`Application.frontend_sink` 属性已移除，全量引用迁移为 `get_system(FrontendSink)`。发送与交互属请求级操作：新交互（审批/提问）只在 RUNNING 接收，既有结果与 History 回显在 STOPPING 仍允许到关闭输出，发送期限不超过 `SHUTDOWN_SEND_TIMEOUT_SECONDS`（1秒）；网络断线/发送超时不回滚 History，模型构造/序列化错误与内部错误传播。`cancel_pending_interactions` 同步解除所有待审批/提问 Future；`close_all_connections` 以标准 1001 关闭所有连接，结束连接前等待/取消真实发送任务及交接，不把自身登记进同一 Owner 再等待；`close_session` 保留永久删除 4004 语义。所有原 emit 签名与消息协议保持不变，typed stream boundary 不退化。`ParentAgentSink` 不作为 System，转发经 `get_system(FrontendSink)` 取得唯一实例。
- `component/approval/mode_store.py`：由 ApprovalSystem 持有的唯一会话级审批模式存储。按会话惰性读取 `approval_mode.es` 的 easysave `v1` key，并通过 `entity/typeref.py` 的 stable type token重建 `SessionApprovalModeState`；业务 `RLock`保护缓存事务，easysave负责路径锁、前置 `.bak`、同目录临时文件与原子替换。模式变更先更新内存再尽力保存，写入失败不回滚；损坏、缺 key或类型错误回退手动模式。新建及自动延续、单源分支、多父合并产生的主会话统一初始化为手动模式，归档保留，永久删除随会话目录清理。
- `system/agentspace/`：Agentspace 编辑器后端业务包。`AgentspaceService` 已注册为 framework `AsyncSystem`（依赖 `RuntimeSystem`、`Sandbox`），由 `virtual_awake` 取得依赖并完成原 start 工作（绑定 EventHub、恢复垃圾桶、启动 watcher）；持有 `visual_resources: SessionVisualResourceService` 只读叶服务。统一版本化 CRUD、用户垃圾桶、按 Agent 回复轮次持有的文件锁、文件变化 watcher、`AgentspaceEventHub`和用户变更摘要；Gateway 将同一事件总线适配为独立编辑器 SSE与聊天 WebSocket typed事件，内置工具通过该服务协作。watcher 启动失败不再降级（D2）。
- `system/llm_profile_store.py`：`LLMProfileStore` 已注册为 framework `AsyncSystem`（依赖 `RuntimeSystem`），无参构造，由 `virtual_awake` 取得 `RuntimeContext` 确定 agentspace 路径并加载 v2 根对象。Store 自身创建唯一的共享 `threading.RLock`，通过 `locked()` 上下文管理器暴露同一把锁，替代原 `Application.profile_lock`；SessionMetadataService、审批后端及 Gateway Profile CRUD 经此接口进入事务边界。仅支持 `llm_profiles.es` 的 `v2` key，直接持有并保存 `LLMProfileData` 根对象；Profile 间多模态分工、审批 Profile、全局元数据 Profile、工具链摘要 Profile以及图片/音频/视频三条全局多模态回退引用均使用根列表中的实例引用，Gateway 通过 `get_system(LLMProfileStore)` 的单 Profile CRUD 和全局用途引用接口修改。写入先准备候选根、成功保存后提交共享内存，不再捕获任意异常做内存回滚；更新通过显式两阶段复制并重连引用图准备候选，提交保留原 Profile 实例身份和引用身份。删除可在同次根保存中清空审批/元数据/工具链摘要引用，但其他 Profile 与全局多模态引用仍阻止删除。不存在的文件允许初始化，已有文件缺 v2 key 直接失败；不启用未知存储字段跳过，缺失字段仍遵循 easysave/Pydantic 默认值语义。存储层保留外层临时文件原子替换，不做备份清理专属重试；Profile 文件与会话名称指针不构成跨文件事务。
- 前端模型配置抽屉通过“模型配置 / 全局配置引用”分页分别管理 Profile 定义和全局用途引用。模型定义按客户端、端点纵向分组，详情单项展开、先只读后编辑；切分页保留内存草稿，离开未保存配置时明确确认。会话待用 Profile 选择只在顶部栏修改，浏览器按会话独立保存名称；无本地覆盖时通过 `GET /api/sessions/{id}/llm-profile` 读取持久化指针及既有全局最近使用回退。选择本身不写服务端，发送到主会话或重新生成才提交；`resume` 保持后端当前配置。全局配置引用页还管理工具链摘要 Profile 与图片、音频、视频三条独立回退引用，状态分别经 `/api/toolchain-summary/profile`、`/api/modality/profiles` 和 `toolchain_summary_profile_changed`、`modality_profile_changed` 同步。旧浏览器全局选择不猜测迁移到任何会话。
- `system/session_metadata.py`：`SessionMetadataService` 已改为 framework `AsyncSystem`（依赖 `RuntimeSystem`、`LLMProfileStore`），无参构造，由 `virtual_awake` 取得依赖并创建本服务的 `SessionStore`。不创建独立 Profile 事务锁，原 `Application.profile_lock` 语义统一经 `LLMProfileStore.locked()` 访问同一把共享 RLock。全局元数据 Profile优先；未配置时按目标会话持久化的活动 Profile回退。统一生成标题、标签和摘要，并为分支、合并与自动旋转提供摘要保障。明确配置不可用时不静默回退。工具链摘要 Profile（`LLMProfileData.toolchain_summary_profile`）为 `CompressHistory` 折叠工具链生成紧凑链摘要（`generate_tool_chain_summary`），未配置时回退到目标会话活动 Profile；解析/校验/客户端创建与元数据共用 `_resolve_session_profile_fallback`、`_assert_profile_usable`、`_create_client_for_profile`，模板为 `toolchain_summary.txt` / `toolchain_summary_input.txt`。五个完整异步操作通过 `TaskOwner.run_request()` 登记，包含读取、模型调用、解析与必要写盘；普通请求异常交回原业务边界，用户取消不被误报为整个应用失败。`close_admission()` 在 STOPPING 期间仍可封闭接收，`cancel_pending()` 等待实际任务及结果交接，生命周期/清理失败继续传播。关闭消息刷新不调用生成接口。
- `abstract/tools/registry.py`：`ToolRegistry` 已迁移为依赖 RuntimeSystem 的 AsyncSystem，模块级单例与兼容代理已移除。异步工具通过 TaskOwner.run_request 托管；同步工具由唯一执行器持有真实 Future，取消等待不删除仍在运行的线程登记。停止分发、请求取消、真实工作等待及线程池异步关闭分别核对结局，生命周期失败继续传播。工具声明/发现已在 S20 迁移为 `ToolDiscoverySystem` 的显式 `register_tools(registry, ui_events)` 协议。
- `abstract/tools/discover.py`：`ToolDiscoverySystem` 依赖工具所需的已就绪 System，按固定顺序扫描五个 component 子包与可选 custom_tools，显式调用同步 `register_tools` 并登记唯一模块集合；最后注册 MCP 管理工具和工具集元数据，不重新建立 MCP 连接。语法/读取/导入/注册错误及旧全局声明直接失败，未授权名称覆盖拒绝会抛错；保留 Python 模块缓存，不通过重载或注入修补发现。
- `system/lifecycle.py`：`TaskOwner.create/track` 负责后台任务，`run_request` 负责有明确结果等待方的请求。`cancel` 登记预期取消并复用固定截止；`is_idle` 同时要求任务结束和交接完成，取消后仍运行的任务不能从所有权记录中移除。原生线程/子进程仍由各 System 持有真实资源，不由异步包装任务的结束替代。
- `system/context.py`：`RuntimeContext`（`BaseModel`，不可变运行时配置）。全局 `set_runtime_context`/`get_runtime_context` 单例入口已删除；配置唯一真相来源由 `RuntimeSystem` 持有，经 `app.get_system(RuntimeSystem).context` 取得。
- `system/sandbox.py`：`Sandbox` 已注册为 framework `AsyncSystem`（依赖 `RuntimeSystem` 与 `SubprocessRunner`），无参构造，`virtual_awake` 取得依赖并加载动态空间；由 Application 在 P22 装配后经 `app.get_system(Sandbox)` 取得。路径沙盒、固定命名空间解析，以及 fast 模式全局动态沙盒空间的严格加载、原子持久化、增删改、目录可用性和权限管理；`Sandbox.read()` 按 UTF-8、系统编码和 Windows 常见编码自动探测，返回准确原文，分页只按 LF 定位原文行片段，保留 CRLF、孤立 CR 与末尾换行；工具 `Read` 在其上独立应用正文单行展示截断，未截断内容保持原文。编辑和 LSP 使用的 `limit=0` 路径仍返回完整解码原文。`write()` / `append()` 禁用平台换行转换，按传入文本原样写入 UTF-8，避免 Windows 上 `PatchEdit` 写回时给已有 CRLF 增加一个 CR；`PatchEdit` 按原文匹配与替换，已有异常换行不自动修复。动态配置位于 workspace 根且由唯一 Sandbox 实例持有。动态沙盒空间 Tab 通过 Gateway REST 复用该单例。所有调用方（含 `component/tools/filesystem.py`、`custom_tools/read_forward.py`）统一经 `app.get_system(Sandbox)` 取得，不再从 `filesystem._s` 跨工具引用或 `Application.current().sandbox` 旧属性获取。
- `system/text_preview.py`：无 I/O 的 `truncate_lf_lines` 纯函数，由 Read 在原文分页统计后调用。Read 新参数 `max_line_chars` 默认 1000，仅允许正整数且可显式提高、不能关闭；按 Unicode 码点保留每行前 N 个正文字符，超限附加 ` ... [truncated]`（含前导空格），标识及 LF/CRLF 行尾不占额度，孤立 CR 仍按正文计数。成功文本结果附带 `max_line_chars`、`truncated`、`truncated_lines`（原文件绝对 0-indexed 行索引）；原行数和分页不变，`remaining=0` 仍可有截断。标识不是原文，PatchEdit 使用前需检查截断状态，必要时提高有限上限重读。自动附带 meta、目录和媒体不应用此展示策略，内部完整读取不变；这不是总输出预算或全文件解码内存限制。
- `system/file_metadata.py`：Read 的元数据文件纯文本解析器，`parse_meta_content(content)` 按独立的 `[key]` 行解析一层字符串字典，保留值的原始空白和换行；非法/重复键及前导非空文字抛带行号的 `MetaFormatError`。`component/tools/filesystem.py` 负责通过 Sandbox 读取目标完整名称追加 `.meta` 的同级文件，目录也使用同级 `目录名.meta`；命名空间根目录不附带，显式 `.meta` 不继续嵌套。成功时结果附加 `meta` 字典，缺失省略，元数据访问/解析失败附加错误字符串而保留原结果。会话视觉源目录的 `redirect` 由 `system/session_visual_resources.py` 单层消费，Read 只在 `meta.redirect` 中报告错误，不跟随目标。目录列表隐藏 `.meta` 文件（后缀不区分大小写，保留同后缀目录），其他文件工具与前端文件树不变。自动附带的元数据完整读取不受正文分页或单行字符限制影响；显式 Read `.meta` 目标则按文本正文分页及截断，但不继续查找 `.meta.meta`。ws: 元数据文件沿用回复轮次文件接触登记；当前不自动维护文件。
- `system/session_store.py`：单个会话的文件读写（`history.es`、`summary.txt`、`token_usage.json`、`tool_resources.json` 等）；活动 LLM Profile 仅以 `{"profile_name": ...}` 名称指针保存。旧版 `messages.jsonl` 已由 `scripts/migrate_v0_to_v1.py` 迁移到会话 v1 格式。`history.es` 通过 easysave 的安全写入事务保存：同目录临时文件、刷新/同步、原子替换和前置备份；残留 `.bak` 会阻断后续保存并要求人工处理，读取侧不自动恢复损坏文件。
- `system/prompt.py` / `system/templates.py`：System Prompt 组装与模板渲染。
- `system/convert.py`：类型转换工具（`as_enum()`、`as_bool()`）。
- `system/error_utils.py`：异常降级与日志辅助，用于可恢复副作用失败时记录日志但不中断主流程。
- `system/pathutils.py` / `system/atomic_io.py`：路径与原子 IO 工具。
- `system/subprocess_utils.py`：`SubprocessRunner` 已注册为 framework `AsyncSystem`（依赖 `RuntimeSystem`），是内部子进程同步/异步执行、活动进程登记与中断终止的唯一所有者；提供 `close_admission()`/`terminate_all()`/`wait_idle()` 关闭接口，由 Application 在 P22 装配后经 `app.get_system(SubprocessRunner)` 取得。代码验证、搜索、LSP 等基础设施继续复用。`build_subprocess_env` 为显式参数纯函数，无隐式全局配置读取。
- `StartShell` 在 Windows 上启动 powershell/pwsh 时使用 `-NoProfile`，并通过启动阶段内部 `-Command` 优先尝试移除 PSReadLine，失败时回退为关闭预测；第一阶段不提供历史、预测和方向键等行编辑能力。Agent 依赖显式的 `EVOLVE_PYTHON` 与 namespace 环境变量。
- Shell 单行输入通过 ConPTY 发送单独的 CR（`\r`）作为 Enter，不发送 CRLF；未换行提示符作为待提交逻辑行，在最后原始输出静默 0.4 秒后提交并立即返回，因此 InterruptShell 和 ReadShell 不必等待 30 秒硬截止。
- `system/search_engine.py`：`SearchFiles` / `Grep` 的搜索引擎封装。Windows x64 优先使用随 Agent 分发的固定版本 `ripgrep`（`origin_agent/vendor/ripgrep/win32-x64/rg.exe`），不可用、校验失败或单次兼容错误时回退 Python；ripgrep 匹配、Python 回退和上下文读取均按 LF 计行，孤立 CR 不会错位；统一处理 ignore/hidden 过滤、`limit` 截断、`full_scan`、`exhaustive`、`engine` 与 `warning` 返回字段。
- 主会话强制中断：`IMainSessionLoop` 只登记已经取得处理锁的单次回复 task；长期 `SessionMessageQueue` consumer 不属于中断目标。`request_interrupt()` 先设置轮次取消事件并等待协作式收尾，超时后只强制取消该轮 task；轮次 finally 在下一条消息开始前清除取消状态。`StreamConsumer` 自行竞速取消信号与流读取，并作为异步迭代器的唯一关闭者。前端以 `history_sync.processing` 的 true/false 为主会话处理状态权威。
- `gateway/session_manager.py`：SessionManager已改为AsyncSystem，virtual_awake加载索引与随意聊聊索引，外部统一get_system取得。S16已接入输入记录、主/多Agent逐项保存确认、工具结果先提交再发送与退役Loop交接；S17的SubAgentOrchestrator通过其公开关闭反馈入口完成子会话交接；S21完成Gateway提前接收登记，P22完成Application最终装配。
- `component/cron_router.py`：CronRouter已迁移为依赖RuntimeSystem/Sandbox/SubprocessRunner的AsyncSystem，持久任务严格加载但不启动Timer，RUNNING后由Application统一activate。工具和API只经公开实例方法操作；冻结保留持久任务，命令使用独立进程会话键，先终止命令再确认Timer退出。快照与原子写串行，失败传播，关闭后不再投递新模型工作。
- `component/browser/system.py`：`BrowserSystem` 已迁移为依赖RuntimeSystem的AsyncSystem，持有唯一Playwright/CDP连接、端点和全部自有无头进程；可选浏览器仍按需启动。请求与清理分别持有，原生进程确认退出后才回收句柄，用户自有浏览器不被终止。`_connection.py`只保留无状态函数，main.py重复清理已移除。
- `system/lsp.py`：`LSPManager` 已迁移为依赖 RuntimeSystem/Sandbox 的 AsyncSystem，工具和文件诊断附加通过 `get_system(LSPManager)` 取得实例。唤醒不启动 pyright，按需 start 保持；启动握手与正常响应共用唯一 reader，复用 Runtime 主 loop。最终关闭在线程中等待进程和 reader/stderr 退出，失败保留资源并传播；旧模块 getter/cleanup 与 main.py 重复清理已移除。
- `system/modality_capability.py`：`ModalityCapabilitySystem` 已迁移为依赖 RuntimeSystem/LLMProfileStore 的 AsyncSystem，独占探测锁、媒体及缓存路径。探测与转发请求由 TaskOwner 管理，六路子探针使用 TaskGroup 完整收尾；HTTP 400 模态拒绝经模块级 `_is_modality_rejection` 统一判定，只识别客户端归一化的 abstract 层 `LLMAPIStatusError(400)`（openai/anthropic 协议非流式由客户端转换、流式回退经 `StreamChunk.error_code` 重建），system 层不依赖具体 SDK 异常族；认证/网络/超时不写入不支持缓存。有状态调用经 get_system，纯媒体构造和显式引用解析保持函数。多模态能力探测与缓存（探针已内化为系统自动行为：伪装 Read 工具调用，按 模态 × 消息路径六路并发探测 tool/user 消息的图片/音频/视频支持；easysave 缓存按 model+base_url 联合索引；`build_modality_prompt_block()` 每轮生成 system prompt 注入块；`resolve_modality_reference_profile()` 按活动 Profile 对应引用优先、全局图片/音频/视频回退引用次之解析目标；`forward_modality_to_ref_profile()` 只将明确的模态/Provider 请求失败转换为转发错误，其他异常继续抛出）。`build_media_content_block()` 提供不附加 prompt 的共享单媒体块构造入口。自定义工具 `ReadForward` 使用该入口按 `paths` 顺序构造“文件标签 + 媒体块”，末尾只附加一次 prompt，并通过单条 user 消息和一次 LLM 调用转发混合模态；工具生成的紧凑 JSON 内容块载荷上限为 45 MiB，任意文件无效时整体失败。多模态预检调用（`ParentAgentLoop._run_tool_loop` 与 `MultiAgentWorker`）纳入模型错误转换边界：无法转发（`ModalityForwardUnavailableError`）时终止本轮并把配置指引持久化展示给前端，provider 错误降级为用户可见错误。

### `evolve/`

- `evolve/code.py`：进化编排，提供 `finalize_evolution()` 触发退出码 `-1`。
- `evolve/validator.py`：Python 语法与 `py_compile` 目录级检查。

### `entity/`

- `entity/messages.py`：`BaseMessage` 消息体系，包括 `BaseMessage`、`CharacterConversationMessage`、`CharacterSystemMessage`、`ToolResultMessage`、`History` 等。所有 LLM 调用统一使用 `list[BaseMessage]` 而非 `list[dict]`；`History.remove_message_with_pairing()` 返回稳定的 `SessionMessageDeletionResult`。
- `entity/puretype/`：纯数据类型包，按职责拆分为 `_base`、`approval`、`llm`、`skills`、`session`、`subagent`、`agent`、`ws`、`lsp`、`runtime`、`extools` 子模块。包括 `LLMResponse`、`StreamChunk`、`Role`、`ToolAvailability`、`ToolDangerLevel`、子Agent编排结果/快照模型以及 Agent Loop 公共操作结果模型。
- `entity/gentype.py`：泛型工具类型（`RefWrapper[T]` 可变引用容器，供 loop 与 `ToolExecutor` 等组件共享可变值，如工具循环计数器）。
- `entity/constant/`：按职责拆分的全局常量包。`constant/__init__.py` 显式重新导出历史公共名称，保持 `from entity.constant import ...` 兼容；`sandbox.py` 保留 `Namespace` 与 `is_namespaced_path()`，其余常量按基础、限制、超时、协议、Shell、文件系统、搜索、Agentspace、上传、聊天样式、HTTP、LLM、Agent、子Agent、多Agent、Cron、会话搜索、Watching、Skill、随意聊聊和 easysave 版本职责分模块维护。

### 前端主聊天统一渲染行补充

主聊天区将历史 skeleton、历史内容页和实时消息统一投影为 Virtuoso 数据行。每条消息首次出现时确定稳定 `renderId`；后端 History 行 ID只作为 `historyRowId`关联字段，正典交接不得替换渲染 key。实时行进入正典位置时保留同一组件实例，折叠状态与高度记录均按 `renderId`维护；Virtuoso 离屏卸载仍按正常虚拟化规则执行。

`stream_meta`中的 `live_history_links`仍是唯一权威关联来源。历史页面乱序、关联缺失、身份不匹配或页面错误时保留实时行，不按正文或数组顺序猜配。`ChatLiveFooter`只承载等待状态、页错误和底部留白，流结束可见性判断改为查询统一聊天列表。

---

## 开发者阅读顺序建议

1. 先通读本文件，建立整体架构认知。
2. 根据你关心的领域阅读对应子模块 DEV-README：
   - 改主循环、消息处理 -> `entry/DEV-README.md`
   - 改网关、会话、前端协议 -> `gateway/DEV-README.md`
   - 改工具、审批、MCP -> `component/DEV-README.md`
   - 改抽象层、注册表、LLM 客户端 -> `abstract/DEV-README.md`
   - 改前端 UI -> `frontend/DEV-README.md`
   - 改子代理 -> `subagent/DEV-README.md`
3. 深入具体源码时，从 `__main__.py` -> `main.py` -> `system/application.py` -> `gateway/server.py` -> `entry/parent_agent_loop.py` 这条主线开始追踪。