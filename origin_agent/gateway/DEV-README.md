# gateway/ — WebSocket / HTTP 网关与会话管理

`gateway/` 负责 Evolve Agent 对外的所有网络交互：前端 WebSocket 长连接、消息路由、REST API 以及会话生命周期管理。

---

## 文件结构

```
gateway/
├── system.py                ← GatewaySystem：FastAPI/uvicorn/socket 与全部路由后台工作的唯一所有者（S21）
├── lifecycle.py             ← GatewayAdmission（HTTP/WS 输入准入）与 GatewayReadyTracker（真实启动就绪）
├── server.py                ← 静态 APIRouter 路由表 + build_router_app() 运行实例工厂
├── message_router.py        ← MessageRouter：WebSocket 消息按类型分发
├── chat.py                  ← SessionManager：会话索引、归档、合并、分支
├── session_manager.py       ← SessionManager：session_id → IMainSessionLoop 映射
└── __init__.py
```

---

## 分层职责

| 文件 | 职责 |
|---|---|
| `system.py` | `GatewaySystem`（framework AsyncSystem）：启动时创建唯一 FastAPI 实例、在本 System 持有的 socket 上 bind、管理 uvicorn serve 任务与真实 ready 事件；`spawn_work` 登记全部路由后台任务（TaskOwner）；关闭顺序为 `stop_accepting()` → `cancel_background_work()` → `stop_server()`。端口预探测 `check_port_available` 与 `GatewayPortBusyError`（占用按退出 0 的普通业务拒绝）也在此。 |
| `lifecycle.py` | `GatewayAdmission`：新业务经 `admit_business()`（要求 RUNNING）；WS 连接经 `admit_connection()`（STARTING/RUNNING）；已建立连接的每条输入经 `require_open_connection()`。`GatewayReadyTracker` 由 uvicorn 子类在 startup 成功后置位。 |
| `server.py` | 只含静态路由定义的模块级 `APIRouter` 与 `build_router_app() -> FastAPI` 工厂（include_router、挂载 assets、计算 build_hash 存于 `app.state.build_hash`）。不再有模块级 FastAPI 实例、`_agentspace_path`/`_BUILD_HASH` 运行快照、`set_agentspace_path` 或旧 `create_server` 入口；文件上传路径经 `RuntimeSystem.context.agentspace`。 |
| `message_router.py` | `MessageRouter`：将 WebSocket 消息按类型分发到对应的处理方法。USER_MESSAGE 在 `route()` 内同步完成目标/字段/Profile 校验并登记输入记录（主会话 `message_queue.accept(ready=False)`），之后才经 `GatewaySystem.spawn_work` 启动准备任务（Profile 就绪、自动标题——无标题会话首条消息经 `SessionMetadataService.maybe_generate_first_title` 触发 LLM 生成+截取回退、客户端信息、子会话转发），准备完成后 `mark_ready`；准备任务非取消异常按 RV9 记录应用失败，记录保留由关闭刷新只落 History。 |
| `chat.py` | `SessionManager`：维护会话元数据索引（`_index.json`），提供会话的创建、归档、删除、合并、分支、标签、标题等操作。 |
| `session_manager.py` | `SessionManager`：在 `chat.py` 的 `SessionManager` 之上维护 `session_id → IMainSessionLoop` 映射，负责创建/恢复会话、终止会话、会话旋转后的 Loop 切换。 |

---

## 主会话系统迁移（S16进行中）

`gateway/session_manager.py::SessionManager`已继承AsyncSystem并声明计划依赖，无参构造仅建立内存字段，virtual_awake创建索引管理器并确保随意聊聊索引；此时不创建Loop。Gateway、工具及钩子的Application.session_manager引用改为get_system(SessionManager)。输入关闭分为freeze_inputs、stop_rounds、flush_inputs，最后者返回ShutdownInputReport；运行期Loop及退役Loop由同一Manager持有，不并发保存同一History。

主队列先同步登记InputDelivery再安排消费者，Parent/Multi逐项APPENDED/PERSISTED后回显；Loop替换保留旧回复与工具结果提交，记录原sequence转交新队列。`SubAgentOrchestrator` 已作为 framework `AsyncSystem` 迁移，Gateway及工具调用统一经 `Application.current().get_system(SubAgentOrchestrator)` 取得；它不再由 `main.py` 注入启动用 Loop。子会话输入登记、反馈关闭交接和普通子Agent最终保存由该System持有；Gateway USER_MESSAGE 在后台任务之前的多目标接收/ready准备已由 S21 完成，Application 最终装配由 P22 完成。

## MessageRouter

### `gateway/message_router.py`

`MessageRouter` 从 `server.py` 的 `ws_chat` 中拆分，负责所有 WebSocket 消息类型的分发处理。`ws_chat` 仅保留 WebSocket 连接生命周期管理。

**消息类型与处理方法映射**：

| 消息类型 | 处理方法 | 说明 |
|---|---|---|
| `USER_MESSAGE` | `route()` 同步接收登记 + `_prepare_user_message` 后台任务 | 先在路由内完成目标/字段/Profile 校验并登记输入记录，再启动准备任务（自动标题——LLM 生成+截取回退、Profile 就绪、子 Agent 转发）；准备失败按 RV9 失败关闭，记录只落 History |
| `CONFIRM_RESPONSE` | `handle_confirm_response` | 审批确认/拒绝，解析到 `FrontendSink` |
| `ASK_RESPONSE` | `handle_ask_response` | 提问回答，解析到 `FrontendSink` |
| `INTERRUPT` | `handle_interrupt` | WS 兼容中断入口；经 `GatewaySystem.spawn_work` 调用统一 `request_interrupt()` 并通过 done callback 观察异常，前端权威交互使用 HTTP |
| `FILE_UPLOAD` | `handle_file_upload` | 文件上传：硬链接优先 → 复制 fallback → base64 解码 |
| `HANDSFREE_MODE` | `handle_handsfree_mode` | 切换手动/脱手/YOLO 模式；服务端实际模式先更新内存，再尽力原子写入会话文件并回送权威值 |
| `PING` | `handle_ping` | 心跳响应 |
| `SYSTEM` | `handle_system_message` | 系统消息（仅记录日志；多模态块使用占位符，不改变既有无截断约定） |
| 其他 | `handle_unsupported` | 不支持的消息类型 |

**`USER_MESSAGE` 处理流程（S21）**：

1. `route()` 同步接收：目标会话存在性/归档状态、`llm_profile_name` 字段与 Profile 命中校验；主会话经 `message_queue.accept(ready=False)` 登记输入记录。
2. `GatewaySystem.spawn_work(_prepare_user_message)`：Profile 就绪（空闲主会话立即切换）、`_auto_generate_title()`（无标题会话首条消息触发 LLM 标题生成，失败回退 30 字符截取）、客户端信息合并、`_dispatch_subagent_messages()` 子会话转发、轮次后回调注册。
3. 准备完成后对主会话记录 `mark_ready`；消费者只按 sequence 连续消费 ready 前缀。
4. 关闭中不再登记新输入；已登记记录由 SessionManager 关闭刷新只落 History。

---

## WebSocket 协议

### 端点

```
WS /ws/chat?resume=<sid>
```

- 不带 `resume`：创建新会话。
- 带 `resume`：只恢复已有会话，重放历史。这里的 `resume` 是 WebSocket 连接恢复参数，不等同于下方 REST `/api/sessions/{id}/resume` 的“恢复工具链执行”操作；两者都不会因为前端当前选择了新的 Profile 而自动更新会话配置。显式目标处于删除中或从内存、磁盘均不存在时，Gateway 拒绝握手，不再创建随机替代会话。

永久删除已建立连接时，Gateway 使用关闭码 `WEBSOCKET_CLOSE_SESSION_DELETED`（4004）使连接失效；前端收到后停止按旧会话 ID自动重连并切换到“随意聊聊”。握手前的拒绝可能被浏览器报告为 1006，前端因此通过 `/api/sessions/{id}/status` 的 `exists`再次确认；删除中的会话也按 `exists=false`返回。

连接建立后，服务端发送：

- `build_hash`：当前前端构建哈希，变化时前端提示刷新。
- `server_info`：服务端信息。
- `handsfree_mode`：每次连接都会主动发送的当前会话权威审批模式，包含兼容布尔字段 `handsfree_mode` 与三态字段 `approval_mode`。已有会话由 `ApprovalModeStore` 从 `approval_mode.es` 的 easysave `v1` key惰性重建 `SessionApprovalModeState`；新建普通主会话、派生主会话和首次创建的“随意聊聊”默认手动模式。前端不持久化该值。
- `history_sync`：新建/恢复连接以及每轮正典 History 写入完成后发送；顶层携带 `history_count`、`processing`、`token_usage`、`context_tokens` 和可选 `agents`，不携带正文。前端随后通过 History REST 按需加载。轮次后推送（`MessageRouter._send_history_sync`）的 `agents` 按会话当前注册 Loop 计算，不按轮次所属 Loop：ExitMultiAgent 退役 MultiAgentLoop 后，其最后一轮的轮次后推送若沿用退役 Loop 会把已清空的 agents 重新覆盖为过期列表，导致前端主徽章停留在多Agent配色。
- `agentspace_event` 初始序列：`resync`、`locks`及 watcher不可用时的 `watcher_error`；随后复用同一 EventHub订阅转发文件变化。事件突发时允许折叠为 `resync`，折叠日志按 `AGENTSPACE_WS_COALESCE_LOG_WINDOW_SECONDS` 时间窗限流并携带窗口累计 dropped；转发 task 登记在 `GatewaySystem.task_owner`，连接断开时经 `TaskOwner.cancel` 预期取消（禁止裸 `task.cancel()`，否则 Owner 会按 RV11 判定为未授权取消并报生命周期失败）并注销订阅；自动旋转复用同一物理连接和订阅。单事件发送超过 `AGENTSPACE_WS_SEND_TIMEOUT_SECONDS` 时抛哨兵异常 `AgentspaceSendTimeout`，done_callback 先经 `TaskOwner.mark_expected_failure` 标记例常预期失败（不触发应用失败关闭）再以 1011 断连驱逐慢消费者连接；该标记回调的注册顺序必须先于 `task_owner.track`（标记先于结算读取）。

### 上行消息类型

| 类型 | 说明 |
|---|---|
| `user_message` | 用户发送的文本/图片消息 |
| `confirm_response` | 审批确认/拒绝 |
| `ask_response` | Ask 回答（按题 answers 数组，null=整表跳过） |
| `interrupt` | 中断当前处理 |
| `file_upload` | 文件上传 |
| `handsfree_mode` | 切换免审批模式 |
| `ping` | 心跳 |
| `client_diagnostic` | 前端关键请求等待超过15秒时上报的脱敏客户端传输诊断；Gateway只记录 warning，不调用 Agent Loop、不写 History |

### 下行消息类型

| 类型 | 说明 |
|---|---|
| `system` | 系统通知；可选 JSON `stream_meta`携带 `stream_id`、`history_index`、`live_history_links`（实时行到正典行的明确关联），或顶层携带 system status 的 `index`/`is_system_status`。关联只在对应 History 写入后发送；前端不得按正文、顺序或实时版本猜测映射。多Agent模式继续携带可见性/响应角色。 |
| `user_message` | 用户消息回显 |
| `assistant_message` | 完整助手消息 |
| `stream_delta` | `StreamDeltaEvent`：必填非空 `session_id` / `stream_id`；可选文本、思考内容和角色名，`tool_call` / `tool_call_delta` 为顶层结构化对象，不再编码到 `content` 字符串。 |
| `stream_done` | `StreamDoneEvent`：必填非空 `session_id` / `stream_id` 与字符串 `finish_reason`；可选 `content`、`MessageMetrics`，缺失正文保留累计输出，显式空字符串表示空正文。 |
| `tool_call` | 工具调用开始 |
| `tool_result` | 工具执行结果；工具链中被消费的排队消息通过 `embedded_messages` 独立传输，不混入普通结果 JSON。 |
| `task_progress` | 任务进度更新 |
| `clipboard_display` | 剪贴板展示更新 |
| `subagent_update` | 子会话状态更新 |
| `history_sync` | 正典历史同步元数据；正文通过 REST 加载 |
| `agentspace_event` | 聊天页会话视觉使用的 typed Agentspace事件；载荷沿用既有文件、锁和重同步元数据范围 |
| `llm_profile_changed` | Profile 重命名/删除通知；顶层携带 `operation`、`old_name`、`new_name` |
| `metadata_profile_changed` | 全局元数据 Profile 状态通知；显式携带可空名称、模型和可用性 |
| `modality_profile_changed` | 图片、音频、视频三路全局回退 Profile 状态通知；一次携带三路可空名称、模型和可用性 |
| `confirm_request` | 请求用户审批 |
| `ask_request` | 请求用户回答（多问题表单：questions 数组，每项含 question/detail/options/multi_select） |
| `error` | 错误通知 |
| `pong` | 心跳响应 |

### 流式事件发送边界

`ws_chat` 从连接登记后的初始化起进入统一 `try/finally`：客户端信息读取、Loop 创建、服务端状态与 Agentspace 订阅任一步意外失败均传播，不继续提供不完整握手。订阅释放即使失败，也在嵌套 `finally` 中释放本连接的待审批/询问和连接登记；旧连接不得清除已接管的新连接状态。明确断线按正常生命周期结束，取消继续传播；通用 `RuntimeError` 不再被解释成正常断线。Agentspace 后台转发失败记录原异常并关闭连接，不伪造 watcher 降级状态。

`entity.puretype.ws` 中的 `StreamDeltaEvent` / `StreamDoneEvent` 是下行流式事件的权威模型，`StreamEvent` 以 `type` 区分两者。`FrontendSink` 直接持有并发送模型；Gateway只负责连接生命周期，不再提供 `_send_tool_event(session_id, event_type, tool_name, payload)` 字符串回调，启动时也不再注册该旧回调。Gateway经`Application.current().get_system(FrontendSink)`取得唯一实例（`_get_ws`、HTTP confirm/ask、会话占用检查、删除关闭、Profile广播与连接释放均走此入口），不再访问`Application.frontend_sink`属性。

`ToolCallRequest`、`ToolCallDelta`、`MessageMetrics` 在进程内保持类型，流式事件在 `FrontendSink._send_stream_event()` 才执行一次 JSON 序列化；可选 `None` 字段省略。工具增量保留 `id/index/name/args_delta/phase`，起始 `id` 可为空，`phase` 为 `start/append/done`，不把未完成的 `args_delta` 当作完整 JSON解析。现有事件出口的空结束正文仍按旧规则省略，不改变中断时的部分输出。其他非流式事件与入站通用 `Message` 暂时保持原协议。

前后端须同步部署：新的流式工具字段替代旧 `content` 内嵌 JSON，不双发两套载荷。前端在 WebSocket接收边界验证两种流式事件结构，非法载荷丢弃并产生不含正文/工具参数的本地诊断；`StreamFrameBuffer` 只接收已验证的流式增量，结束事件先刷新缓冲再固化。

---

### 主会话活动状态接口

`GET /api/sessions/{session_id}/status` 除了返回 `exists` 和 `occupied`，还返回 `processing` 与非持久化 `activity` 快照。快照包含 `activity_id`、`revision`、`source`、`phase`、可空 `stream_id` 和可空 `character_name`。状态查询只读取已经存在的运行时 Loop，不会为了轮询隐式创建 Loop。

`processing` 表示 Loop存在活动快照或已经进入处理状态；它覆盖队列排队窗口。WebSocket 的 `history_sync.processing` 保留兼容用途并使用相同活跃语义，首字前精细状态由前端活动状态轮询取得。

## 输入准入与关闭（S21）

- RUNNING 之前与 STOPPING 之后，所有新业务 HTTP 入口经 `_admit_business_http()` 返回 503；`/health` 只报告状态、不创建 Loop，非服务状态返回 503。
- WS 握手在 STARTING/RUNNING 期间允许（`admit_connection`），STOPPING 后以标准 1001 拒绝；已建立连接上的每条输入也经 `require_open_connection()` 检查，关闭时连接以 1001 结束。
- 动态端点在登记队列消息成功后才回报 202；关闭中的拒绝返回 503。
- 关闭顺序：先 `stop_accepting()` 封闭新输入（既有输出连接保留到 History 刷新完成），`cancel_background_work()` 取消自动标题/准备/恢复等路由后台任务，最后 `stop_server()` 结束 SSE/WS、置 `server.should_exit` 并等待 serve 任务结束。Gateway 是最后唤醒、首先资源注销的 System。
- uvicorn 由 GatewaySystem 子类 `_GatewayUvicornServer` 管理：禁用自身信号安装（App 统一处理信号），startup 成功后置 ready 事件；启动等待 ready、serve 提前结束与 30 秒超时三者竞速。

## HTTP 请求类型边界

Gateway 遵循快速失败：只将明确的业务异常映射为 HTTP 400/404/409 等状态；逻辑之外的异常直接传播给 FastAPI，不额外捕获后转换成通用 500，不返回空列表或默认请求继续执行。请求体 JSON 语法/编码错误返回 400，模型校验错误返回 400；原有 `default_on_json_error` 已移除，要求 JSON 请求体的端点不再用空模型替代无效 JSON（包括空 body）。

普通 HTTP 返回值保留 BaseModel，包括字典/列表中的嵌套模型，由 FastAPI 自动序列化。需要展开字段并增加兼容字段的响应暂保留字典适配；显式 `HTMLResponse` 的 JSON 正文使用 `model_dump_json(exclude_none=True)`，保持原有动态状态码及省略空字段的协议。WebSocket/SSE 不走普通 HTTP 返回值编码，仍在实际发送边界编码。HTTP 附带 WebSocket 通知在编码后跳过明确已关闭的连接，仅捕获 `WebSocketDisconnect`；模型构造、编码和其他内部错误不被吞没。

Profile API 只捕获 `ProfileNotFoundError`/`ProfileConflictError`，不捕获通用 `LookupError`/`ValueError`/`OSError`。动态沙盒空间管理仅映射 `DynamicSandboxInputError`（400）、`DynamicSandboxConflictError`（409）、`DynamicSandboxNotFoundError`（404）及既有 `SandboxError`；不靠错误文本猜测冲突，也不把类型错误当作用户输入错误。Agentspace REST 仅映射 `AgentspaceError`；意外错误直接交给 FastAPI，其 500 响应不承诺旧版自定义 JSON `detail` 结构。

Gateway REST 的 JSON 请求体在进入业务逻辑前统一解析为 `entity.puretype` 中的 Pydantic `BaseModel`。会话操作请求位于 `session.py`，confirm/ask 入站请求位于 `ws.py`，动态端点请求位于 `extools.py`，Agentspace 垃圾桶操作请求位于 `agentspace.py`。合法 JSON 中省略可选字段时沿用模型默认值；非法 JSON 不再使用默认请求，业务代码通过属性访问稳定字段。

动态端点的 `content` 使用稳定的多模态 content block 联合类型；content block 对未知扩展字段保持兼容，Gateway 在进入既有消息队列前转换为内部 `MessageContent` 结构。该转换是传输边界适配，不改变 History 或 LLM wire format。前端请求字段和 JSON wire format 保持不变。

## REST API

### 会话管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions` | 会话列表 |
| GET | `/api/sessions/{id}/status` | 返回内存索引中的存在状态与 WebSocket 占用状态；删除中按 `exists=false`处理 |
| GET | `/api/tags` | 全局标签列表 |
| PUT | `/api/sessions/{id}/tags` | 更新会话标签 |
| PUT | `/api/sessions/{id}/title` | 手动设置标题 |
| POST | `/api/sessions/{id}/auto-title` | 自动生成标题 |
| POST | `/api/sessions/{id}/auto-tags` | 自动生成标签 |
| POST | `/api/sessions/{id}/terminate` | 终结会话；元数据生成失败不阻止归档，响应通过 `metadata_warnings`返回警告 |
| POST | `/api/sessions/{id}/pin` | 置顶切换 |
| POST | `/api/sessions/{id}/branch` | 从会话创建分支；缺摘要时保底生成，失败不创建延续会话 |
| POST | `/api/sessions/merge` | 合并多个已归档会话；所有父摘要必须齐备，任一失败则整体失败 |
| DELETE | `/api/sessions/{id}` | 永久删除会话；拒绝“随意聊聊”、不存在目标和重复删除 |

永久删除先建立进程内删除中标记以阻止新连接重建 Loop，再关闭现有 WebSocket、停止子Agent、回收活动回复/消息队列/客户端信息/Cron 注册，随后删除会话索引与目录并清理 Shell、Cron 和动态端点。删除中并发请求对已移除的 Loop返回未找到或未就绪。Gateway 不吞掉子Agent停止或资源清理异常；前置步骤失败即终止后续删除，已完成的永久删除不因后续失败自动回滚。删除中标记在 `finally` 释放。下层服务的独立异常处理不在本次 Gateway 清理范围内。

### 聊天 History 按需读取

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/history/skeleton?start_index=` | 返回全历史骨架或 append-only 后缀，不含正文 |
| GET | `/api/sessions/{id}/history/page?start_index=&limit=` | 按 History 消息索引范围返回完整前端投影行 |
| GET | `/api/sessions/{id}/history/resources` | 返回完整 History 的图片与下载资源索引 |

骨架与历史内容页只是 Gateway 读取视图，不改变 `History` / `history.es` 整体存储。工具请求和匹配的 ToolResultMessage 在前端投影为一个 `tool_card` 行，结果按 `tool_call_id` 配对并可跨 History 内容页返回；只有孤立结果保留为独立降级行。编辑、按轮删除、单条删除和重新生成在 Agent 处理期间统一返回 HTTP 409；结构修改后前端取消旧页请求并重取骨架。前端对会话状态预检、History骨架和历史内容页设置15秒硬截止；超时显示持久通知和局部重试，WebSocket可用时发送不含正文、工具参数、附件或密钥的 `client_diagnostic`。

### 主会话媒体输入控制

| 方法 | 端点 | 说明 |
|---|---|---|
| GET | `/api/sessions/{id}/history/media?offset=0&limit=100` | 独立媒体实例轻量页，默认100、最多500；含总数/身份/开关/来源/缓存存在性，不含Base64或描述正文 |
| PUT | `/api/sessions/{id}/history/media/{media_id}` | StrictBool的send_multimodal与expected_send_multimodal必填；候选History严格保存后返回该实例权威状态 |
| GET | `/api/sessions/{id}/history/media/{media_id}/content` | 用户按需取得单个原媒体；inline返回二进制，HTTP(S)仅307由浏览器读取，服务器不抓取来源URL |

仅查询当前注册主会话Loop，不创建Loop、不另读活动磁盘History。新操作使用RUNNING准入/no-store：会话缺失或删除中404，存在但无Loop或正在旋转409；409不等于会话删除。归档已恢复Loop可GET及补齐旧身份，用户PUT403。处理中允许修改媒体开关，从保存后的下一模型请求生效，已开始请求不撤回。无新WS通知、SSE或轮询。

非法参数/ID/JSON/非boolean请求400，实例消失404，expected冲突409；预览格式不支持415、编码错误400。仅映射专门业务异常，损坏重复ID或必要写盘失败不返回默认清单。GET旧身份补齐可能严格写History，失败沿原HistoryPersistenceError可能导致500与应用失败关闭；归档“用户只读”不豁免系统元数据迁移。预览只解码一个块、无临时文件和Range；nosniff，SVG加sandbox CSP，不能把任意MIME当HTML执行。

清单支持普通/随意聊聊/多Agent主会话，不包括独立子会话或未进入History的上传/Markdown资源。关闭不减少History磁盘体积；PUT仍全量写盘，保存超时的前端须GET确认，不自动重试写入。源码已实施，未运行验证。

### 消息编辑

| 方法 | 端点 | 说明 |
|------|------|------|
| PUT | `/api/sessions/{id}/messages/{index}` | 编辑历史消息 |
| DELETE | `/api/sessions/{id}/messages` | 清空历史消息 |
| POST | `/api/sessions/{id}/regenerate` | 重新生成最后一条回复；请求体必须携带 `llm_profile_name`，可同时更新本次生成使用的 Profile |
| POST | `/api/sessions/{id}/resume` | 从当前历史状态恢复工具链执行；不追加用户消息、不截断历史，也不更新 LLM Profile |
| POST | `/api/sessions/{id}/regenerate-summary` | 重新生成会话摘要 |

`/regenerate` 与 `/resume` 不在 Gateway 重复登记活动 task；对应 Loop 在取得 `_process_lock` 后自行登记当前回复，并在完整收尾后注销。

### 会话变量池

`GET /api/sessions/{id}/variables`返回SessionVariablePoolResponse，直接复用AgentspaceService.session_variables.read_pool，与ReadSessionVariables的值/meta/issues一致，不创建Loop。no-store、RUNNING准入、读取前后存在性/删除中复检；归档及随意聊聊可读，已删除/删除中404，即使留下变量文件也不会复活会话。

有界读取通过run_in_threadpool执行，HTTP返回BaseModel而非提前降级。已知业务错误映射400（输入/不安全根）、403（根/目录访问）、409（源变化）、413（整池预算）；detail为code/message/path。条目输入问题与constraint保留在成功诊断响应，scan_complete=false明确不完整；意外异常直接交FastAPI，不变成空池。不新增WS类型、SSE连接或独立watcher。

变量存储在工作空间`ws:sessions/<id>/variables/`，与History存储根不同。单父复制、多父来源分组由Loop初始化路径协调；正常永久删除仍只沿既有规则清理聊天目录/索引及资源，不自动清理变量文件。

### 工具资源与子代理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/tool-resources` | 工具资源 |
| GET | `/api/sessions/{id}/subagents` | 当前会话的子代理状态 |
| POST | `/api/confirm/{request_id}` | 审批响应 |
| POST | `/api/ask/{request_id}` | 提问响应（请求体 `{answers: [{selected: [str], custom_text} \| null]}`，null=整表跳过） |
| POST | `/api/interrupt/{session_id}` | 强制中断已经取得处理锁的主会话当前回复 task；按活动 task 判定 idle，返回权威结果（cancelled / timeout / failed / not_found），不取消长期消息 consumer |
| POST | `/api/file-picker` | 系统文件选择器 |
| POST | `/api/shutdown-approval-model` | 卸载审批模型服务 |
| GET | `/api/characters/avatars` | 实时组装主Agent与全部子Agent角色的头像映射（`[avatar]` 元数据键 → `/files` URL，≤5 MiB、不限扩展名）；no-store、不创建 Loop、不依赖会话，组装委托 `system/character_avatars.py` |
| GET | `/api/characters/profiles` | 实时扫描全部子Agent角色档案（名称、类型、目录/档案逻辑路径、简介、提示词全文、Profile 名称引用、可用性错误），密钥与 Profile 配置内容不出模块；no-store、to_thread，组装委托 `system/character_profiles.py` |

### Shell会话与 Cron

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/shells` | 返回当前主会话全部 Shell会话元数据，不返回终端输出 |
| POST | `/api/sessions/{id}/shells/{shell_id}/stop` | 前端用户直接停止 Shell会话及其进程树 |
| GET/POST | `/api/sessions/{id}/cron-tasks/...` | Cron 任务列表/触发/取消 |

Shell 输出由 Agent 使用 `ReadShell` 拉取，不通过聊天 WebSocket 主动推送。WebSocket 断线不停止 Shell；自动旋转迁移所有权；手动终结、永久删除和应用关闭负责停止。

Cron REST、Loop路由注册/注销与会话清理统一调用 `get_system(CronRouter)`，不再导入cron_tools获取服务。任务持久化、调度和实际命令属于CronRouter；应用冻结不同于用户取消，不删除持久任务或把未执行任务标为完成。激活由 Application 在全部 System 唤醒且 Gateway ready 后统一执行，关闭编排由 Application 统一执行。

### LLM Profile

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/llm/profiles` | 返回 v2 `LLMProfileData` 的扁平 Profile 列表 |
| POST | `/api/llm/profiles` | 创建单个 Profile |
| PUT | `/api/llm/profiles` | 按原名称原地更新或重命名单个 Profile |
| DELETE | `/api/llm/profiles` | 删除 Profile，并为当前空闲会话指定替换名称或无配置 |
| GET | `/api/llm/clients` | 返回可用 LLM 客户端实现 |
| GET | `/api/sessions/{id}/llm-profile` | 只读返回会话保存的Profile名称及缺失时的全局最近使用回退；不创建Loop、不更新选择 |

`llm-profile` 返回 `SessionLlmProfileState(session_id, profile_name, available)`：profile_name为空字符串表示显式无配置，null表示会话和全局指针均缺失；非空名称的available只表示存在于注册表，不代表连接已验证。不存在或删除中会话返回404，指针格式/IO读取错误返回500；响应no-store，可查询归档及随意聊聊。该接口反映持久化指针，不是进行中的客户端快照。浏览器会话待用选择优先于恢复值，只在发送到主会话或重新生成时通过既有通道提交；没有新增切换Profile的PUT接口。

前端 USER_MESSAGE 与重新生成请求只传 `llm_profile_name`，不传完整 Profile。Profile 删除先检查其他 Profile 和全局多模态引用；允许删除时由 Store 在一次根对象写入中删除目标并清空指向它的审批/元数据引用，再更新会话运行配置和名称指针，避免业务拒绝时已清空引用。Profile 文件、会话指针文件和通知不是跨文件事务；后续失败直接报告，已提交部分不自动恢复。

前端 USER_MESSAGE 与重新生成请求中，空字符串表示明确无配置。`/resume` 请求不接收 `llm_profile_name`，始终使用当前 `ParentAgentLoop` 已持有的活动 Profile；前端刚切换但尚未通过 USER_MESSAGE 或重新生成提交的 Profile，不会被 resume 应用。Profile 重命名和删除通过 `llm_profile_changed` 广播；忙碌会话不在删除请求中切换。

### 审批 Profile

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/approval/profile` | 返回项目级审批 Profile 的名称、模型和可用性 |
| PUT | `/api/approval/profile` | 按 Profile 名称设置或以 `null`清空审批 Profile引用 |

审批 Profile设置、清空、编辑失效或删除只更新 Profile根对象、审批后端缓存和 `approval_profile_changed` 广播；广播不携带审批模式重置字段，也不改写任何会话的手动/脱手/YOLO 模式。已恢复的脱手模式在审批后端不可用时保持不变，实际审批按既有失败路径拒绝；YOLO不依赖审批 Profile。PUT响应中的 `disabled_sessions` 仅为兼容字段，固定为空列表。

### 全局元数据 Profile

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/metadata/profile` | 返回全局元数据 Profile 的可空名称、模型与配置可用性 |
| PUT | `/api/metadata/profile` | 按 Profile 名称设置或以 `null`清空全局元数据 Profile |

自动标题、自动标签和摘要直接调用 `Application.current().get_system(SessionMetadataService)`，不要求目标会话存在运行时 Loop。全局元数据 Profile未配置时按目标会话自己的活动 Profile回退；明确配置但不可用时返回失败，不静默回退。配置变化通过 `metadata_profile_changed`广播。删除当前元数据 Profile只清空全局引用，不自动采用删除请求中的替换 Profile。

### 全局多模态回退 Profile

| 方法 | 端点 | 说明 |
|---|---|---|
| GET | `/api/modality/profiles` | 一次返回图片、音频、视频三路全局回退 Profile 的名称、模型和可用性 |
| PUT | `/api/modality/profiles` | 请求体 `{media_type, profile_name}` 只更新其中一路；`profile_name: null` 清空该路引用 |

多模态回退引用直接保存为 `LLMProfileData` 根对象中根列表实例的引用。运行时先使用活动 Profile 的对应引用，只有该引用为空时才读取对应全局引用；活动引用存在但不可用或调用失败时不切换全局回退。三路引用独立管理，Profile 被任一路全局多模态引用时删除请求会被拒绝，用户须先清除引用。Profile 更新后的可用性和名称变化通过 `modality_profile_changed` 广播；非预期异常不被转成普通转发错误。

`/files` 的会话视觉入口支持 GET/HEAD 探测：源目录同级 `.meta` 的 `[redirect]` 只解析一层，合法目标通过 307 指向带 `visual_raw` 的原始入口，避免目标目录再次解析；最终 HEAD 响应返回 `X-Session-Visual-Version`。无效配置静默使用源目录，普通静态文件不受影响。site 的 `/zip` 源目录同样复用该规则。

`/files`、`/downloads` 与 `/zip` 均复用 `Application.current().get_system(Sandbox)`，不再临时构造 Sandbox。因此 fast 模式下可读且当前目录存在的全局动态沙盒空间也遵循同一逻辑前缀解析、遍历防护和权限检查；fallback 不启用动态空间。

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/uploads/{path}` | 静态文件访问 |
| GET | `/downloads/{path}` | 文件下载 |
| GET | `/local-font/{font_path}` | 本地字体文件访问（CSS `@font-face` `src` 用途）；扩展名白名单 `woff2`/`woff`/`ttf`/`otf`，单文件 ≤ 20 MiB，响应 `Access-Control-Allow-Origin: *` |

### Agentspace

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/agentspace/list` | 目录优先自然排序的文件列表（兼容返回 `type`，权威字段为 `kind`） |
| GET | `/api/agentspace/read` | UTF-8 文本快照、SHA-256 version 与修改时间 |
| POST | `/api/agentspace/write` | 独占创建或携带 `expected_version` 的版本化保存 |
| POST | `/api/agentspace/mkdir` | 无覆盖创建目录 |
| POST | `/api/agentspace/delete` | 用户操作：移动到 Agentspace 垃圾桶 |
| POST | `/api/agentspace/rename` | basename-only、无覆盖重命名 |
| GET | `/api/agentspace/trash` | 垃圾桶条目列表 |
| POST | `/api/agentspace/trash/{entry_id}/restore` | 无覆盖恢复，冲突自动改名 |
| DELETE | `/api/agentspace/trash/{entry_id}` | 永久删除单条垃圾桶条目 |
| DELETE | `/api/agentspace/trash` | 清空垃圾桶，返回 partial failure |
| GET | `/api/agentspace/locks` | 当前回复轮次路径锁完整快照 |
| GET | `/api/agentspace/events` | Agentspace `text/event-stream` 实时事件 |

Agentspace mutation body 均携带 `operation_id`；`write` 另携带 `expected_version`，`rename` 只接收 `path + new_name`。错误 `detail` 为机器可读对象：无效路径 400、不存在 404、目标或版本冲突 409、非 UTF-8 文本 415、命中 Agent 回复轮次文件锁 423、内部错误 500。该 SSE 只服务独立 Agentspace 编辑器：使用 `event: agentspace`，`id` 为进程内递增 sequence，连接后先发送 `resync` 与完整 `locks`，心跳为注释帧；断线重连后前端重新取得 REST 权威快照。聊天页视觉不再创建此 EventSource，而从已有会话 WebSocket接收 `agentspace_event`。

Agentspace SSE 长连接在 Gateway 收到关闭信号时主动结束；等待任务经 `GatewaySystem.task_owner` 登记，应用关闭编排（P3/P22）会等待 uvicorn 完成正常关闭，仅在超时后强制取消。`AgentspaceService` 的订阅在响应结束时由 `finally` 释放。

### 技能与动态端点

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/skills/list` | 技能列表 |
| POST | `/dynamic/{session_id}/{agent_name}/{endpoint_name}` | 动态端点调用 |

---

## 会话持久化

单个会话的数据持久化到 `workspace/sessions/<session_id>/`。History等内容由 `system/session_store.py` 管理，审批模式由 Application持有的 `ApprovalModeStore` 管理：

| 文件 | 说明 |
|---|---|
| `history.es` | 新版消息历史（v1，easysave 多态序列化） |
| `summary.txt` | 会话摘要 |
| `token_usage.json` | token 消耗 |
| `tool_resources.json` | 任务进度、剪贴板展示等 |
| `approval_mode.es` | easysave `v1` key保存的 `SessionApprovalModeState`；BaseModel直接保存并通过 stable type token重建，缺失、缺 key、损坏或类型错误时回退手动模式；模式变更先更新内存再尽力保存，安全写入与 `.bak`由 easysave负责 |

归档保留 `approval_mode.es`；永久删除会话目录时一并删除，随后清理 Store缓存。自动延续、单源分支和多父合并不会复制该文件，新会话统一写入手动模式。

全局会话索引：`workspace/sessions/_index.json`。