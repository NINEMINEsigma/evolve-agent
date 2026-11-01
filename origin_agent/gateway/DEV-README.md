# gateway/ — WebSocket / HTTP 网关与会话管理

## 工具结果媒体传输（2026-11-02，当前约定）

下行 `tool_result.result` 使用字符串或原生媒体块数组，与历史内容页的工具结果展示内容一致；不把数组再次编码为 JSON 字符串或媒体占位文本。工具调用 ID、独立 `tool_call_meta`、`embedded_messages` 与消费确认字段不变。`FrontendSink` 直接构造原通用 `Message` 并复用现有发送所有权，Gateway 路由、准入、关闭顺序与消息类型不变。

`subagent_update.result` 外层继续为 JSON 字符串，其内部 `feedback[].content` 可以是媒体数组；子会话快照也保留工具媒体。历史页从原始工具内容的尾部元数据文本只读提取独立耗时和嵌入消息，不改变 History 存储。需要前后端同批部署并刷新浏览器；没有新端点或存储迁移。此次仅源码与文档同步、只读审阅，未运行校验、测试、实际导入、构建或应用。

`gateway/` 负责 Evolve Agent 对外的所有网络交互：前端 WebSocket 长连接、消息路由、REST API 以及会话生命周期管理。

> **2026-10-31当前规范**：端点定义全部位于`apis/`，server只保留工厂。请求结构/字段/参数错误采用标准422；明确业务拒绝采用非2xx及`detail:{code,message,...}`，成功结构与专属附加字段保持。下文历史章节中的“server端点/全局router/手动解析400/旧失败载荷”均由本说明与文末当前协议章节覆盖，不表示仍提供旧接口导入或错误格式兼容。

---

## 文件结构

```
gateway/
├── system.py                ← GatewaySystem：FastAPI/uvicorn/socket 与全部路由后台工作的唯一所有者（S21）
├── lifecycle.py             ← GatewayAdmission（HTTP/WS 输入准入）与 GatewayReadyTracker（真实启动就绪）
├── server.py                ← build_router_app(gateway)：无全局路由的运行实例工厂
├── apis/                    ← 91个API端点组件的模块级实例，按类型发现后显式登记92条路由
├── api_routes.py             ← 同文本路径的HTTP方法/WS重复登记检查
├── api_support/             ← 会话前置条件、Profile投影、专属错误及有界导出HTTP帮助
├── http_boundary.py         ← 新业务准入、标准422与结构化HTTP错误边界
├── frontend_assets.py       ← 前端产物路径、hash与MIME
├── notifications.py         ← 跨端点/子Agent共用的可选WebSocket通知
├── message_router.py        ← MessageRouter：WebSocket 消息按类型分发
├── chat.py                  ← SessionManager：会话索引、归档、合并、分支
├── session_manager.py       ← SessionManager：session_id → IMainSessionLoop 映射
└── __init__.py
```

---

## API端点启动发现与装配（2026-10-31，当前约定）

各具体端点模块在类定义后创建无参APIComponent实例，变量名不限；apis包入口无中央导入、类型清单或register_apis。`GatewaySystem.display_apis(router)`通过`abstract.discovery.StrictDiscovery`收集实例，复用framework的按类型枚举和对象身份去重。StrictDiscovery仅处理受信任的常规Python源包，逐层完整候选预检后确定性导入，同名模块文件/包目录歧义、读取和导入失败直接传播，不使用第三方默认发现器的吞异常路径。

System检查非空及priority后稳定排序，全部add_component绑定成功才逐个display。priority必须为真正int，默认0，负数允许，数值小者先；同值保持模块和变量发现顺序。1000必须恰好一个，当前由SpaFallbackAPI声明，普通组件不能大于或占用该末尾声明；这仅验证末尾优先级声明，不验证SPA handler语义。System不按URL具体程度自动排序。

新增`api_routes.py::validate_api_routes`只检查相同文本path的HTTP方法重复和WS重复；GET/HEAD、不同方法和不同协议共路径允许，不要求route.name唯一。不识别参数名不同的等价模板、正则交叠或通配遮蔽，作者应显式选择优先级。display只登记原生APIRoute/APIWebSocketRoute；StaticFiles仍由server在include_router后挂载，不放入组件router。

工厂只委托System，所有发现/display/重复登记错误发生于include_router和socket创建之前，直接终止启动，原Gateway失败启动清理继续负责其叶服务/资源。`_api_assembly_started`拒绝同Gateway重复装配；模块实例已绑定其他System时framework同样拒绝，不重试、reload、克隆或清空组件后恢复。发现列表和检查索引均为调用局部，不建立第二份服务/组件表。

Gateway尚未完成awake时使用现有self完成装配，不反查自身槽位或fastapi_app。单次Request、WebSocket、会话ID、订阅及结果仍为调用局部，原TaskOwner和业务服务持有真实资源；URL/name/响应模型、同步文件与ZIP、WS/SSE关闭顺序不变。无新System、配置、持久化格式或前端改动，工具发现和third保持不变。

新增内置模块在完整部署并重启后生效，无外部端点目录或运行期热加载。run.py合并复制可能残留已删除/移动旧端点，用户须先保护本地进化内容并定向处理残留；force_init不保证清除fast独有文件，开发助手AI不操作运行时副本。本轮未运行测试、校验、实际导入、构建或应用，用户人工验收见`.tasks/2026-10-31_2_gateway-api-discovery.md` P11/V12。

## 异常定义包（2026-10-30）

`GatewayPortBusyError`、`AgentspaceSendTimeout`、`AgentspaceConnectionClosed` 统一定义于 `entity/error/gateway.py`；端口检查和连接终止分类函数仍留在 Gateway 业务模块。所有公共自定义异常（包括 Profile、Sandbox、Agentspace、History媒体和导出异常）统一 `from entity.error import X`，不通过所属服务模块或旧包入口间接导入；标准库/第三方异常仍从原来源导入。

`SessionExportError` 在 `entity/error/session_export.py` 唯一定义，全部公共子类与 entry/system 使用同一类型族，HTTP 映射仍捕获该唯一基类。私有 `_SourceUnavailable` 不公开，使用方仅从 `entity.error.session_export` 显式导入。异常保留原 Exception 家族，不强行改 BaseModel；端口占用正常停止、慢消费者1011驱逐、对端断线不再发关闭帧、预期失败登记顺序和快速失败策略均保持。

[异常定义包文档](../entity/error/DEV-README.md) 是定义/导入规则依据；`system/agentspace/errors.py` 已删除，纯转发 `system/lifecycle_errors.py` 已删除，不提供兼容入口。异常不进 easysave/typeref，存储 key 未变。本次仅源码迁移与文档同步，未运行测试、实际导入、构建、校验或应用；用户须停机完整部署并重启，注意合并复制旧文件残留，开发助手AI不操作 workspace。

## 分层职责

| 文件 | 职责 |
|---|---|
| `system.py` | `GatewaySystem`（framework AsyncSystem）：启动时创建唯一 FastAPI 实例、在本 System 持有的 socket 上 bind、管理 uvicorn serve 任务与真实 ready 事件；`spawn_work` 登记全部路由后台任务（TaskOwner）；关闭顺序为 `stop_accepting()` → `cancel_background_work()` → `stop_server()`。端口预探测 `check_port_available` 也在此，抛出的 `GatewayPortBusyError` 定义于 `entity/error/gateway.py`（占用按退出 0 的普通业务拒绝）。 |
| `lifecycle.py` | `GatewayAdmission`：新业务经 `admit_business()`（要求 RUNNING）；WS 连接经 `admit_connection()`（STARTING/RUNNING）；已建立连接的每条输入经 `require_open_connection()`。`GatewayReadyTracker` 由 uvicorn 子类在 startup 成功后置位。 |
| `server.py` | 仅`build_router_app(gateway: IGatewaySystem) -> FastAPI`工厂：创建局部GatewayAPIRoute路由表，通过gateway.display_apis委托System发现和装配实例，include_router、挂载assets并将hash存于app.state。没有全局router、端点函数或通知转发；GatewaySystem传入现有self，避免未awake时查询自身。 |
| `apis/` | 每个具体APIComponent一文件，按职责分组；显式原URL/方法/name/response_model，91组件、92注册，GET/HEAD共组件但两条登记。只在handler局部保存连接/请求数据，sync文件/ZIP保留线程池语义。 |
| `http_boundary.py` | 原生ASGI中间件在正文读取前限制新业务；JSON字节/原生模型使用标准422；只映射HTTP与已识别停止，未知错误传播，WS不进入HTTP专属转换。 |
| `api_support/`、`notifications.py`、`frontend_assets.py` | 按职责共享前置条件、状态投影、专属HTTP错误、有界导出、通知和静态产物定位，不持有第二份业务服务或请求状态。 |
| `message_router.py` | `MessageRouter`：将 WebSocket 消息按类型分发到对应的处理方法。USER_MESSAGE 在 `route()` 内同步完成目标/字段/Profile 校验并登记输入记录（主会话 `message_queue.accept(ready=False)`），之后才经 `GatewaySystem.spawn_work` 启动准备任务（Profile 就绪、自动标题——无标题会话首条消息经 `SessionMetadataService.maybe_generate_first_title` 触发 LLM 生成+截取回退、客户端信息、子会话转发），准备完成后 `mark_ready`；准备任务非取消异常按 RV9 记录应用失败，记录保留由关闭刷新只落 History。 |
| `chat.py` | `SessionManager`：维护会话元数据索引（`_index.json`），提供会话的创建、归档、删除、合并、分支、标签、标题等操作。 |
| `session_manager.py` | `SessionManager`：在 `chat.py` 的 `SessionManager` 之上维护 `session_id → IMainSessionLoop` 映射，负责创建/恢复会话、终止会话、会话旋转后的 Loop 切换。 |

---

## 主会话系统迁移（S16进行中）

`gateway/session_manager.py::SessionManager`已继承AsyncSystem并声明计划依赖，无参构造仅建立内存字段，virtual_awake创建索引管理器并确保随意聊聊索引；此时不创建Loop。Gateway、工具及钩子的Application.session_manager引用改为get_system(ISessionManager)。输入关闭分为freeze_inputs、stop_rounds、flush_inputs，最后者返回ShutdownInputReport；运行期Loop及退役Loop由同一Manager持有，不并发保存同一History。

主队列先同步登记InputDelivery再安排消费者，Parent/Multi逐项APPENDED/PERSISTED后回显；Loop替换保留旧回复与工具结果提交，记录原sequence转交新队列。`SubAgentOrchestrator` 已作为 framework `AsyncSystem` 迁移，Gateway及工具调用统一经 `Application.current().get_system(ISubAgentOrchestrator)` 取得；它不再由 `main.py` 注入启动用 Loop。子会话输入登记、反馈关闭交接和普通子Agent最终保存由该System持有；Gateway USER_MESSAGE 在后台任务之前的多目标接收/ready准备已由 S21 完成，Application 最终装配由 P22 完成。

## 会话离线导出

`GatewaySystem.session_exports`持有无History缓存的`SessionExportService`叶服务，不新增AsyncSystem；该属性同时由`IGatewaySystem`抽象属性声明，导出路由经`_gateway()`取到的接口实例访问，不依赖具体实现类。Gateway通过`IRuntimeSystem`、`ISessionManager`、`ISandbox`接口槽位注入其运行时依赖；它只读当前已恢复且空闲的主会话，包括已打开归档会话；使用公开隔离捕获/guard、线程侧正式History投影及确定性摘要，精确读取Sandbox文件和严格字体路径，不读取活动history.es、不补媒体身份、不写会话、不调用模型。

三个typed POST接口为`/api/sessions/{id}/export/snapshot`、`/export/resource`、`/export/verify`。资源成功为二进制+Content-Length/X-Export-Digest/X-Export-Identity；明确缺失/拒绝/单文件超限返回detail.code/source/proof并与会话404区分。快照按96MiB上限在线程侧增量编码；资源/复核请求主体在解析前有界读取。无效400、会话缺失404、忙碌/变化409、全局超限413、容量429、停止503；未知错误直接传播，不返回空History。HTTP断开取消等待方，TaskOwner继续持有实际线程收尾，容量不提前释放。

`GET /api/session-export/viewer/{asset_name}`仅接受viewer.js/viewer.css两个构建产物，缺失503、未知404、no-store/nosniff，不依赖SPA兜底。三个导出路由必须与新前端同步；旧后端没有这些POST路由时可能由GET兜底产生405，刷新前端不能补齐后端。视觉HEAD 404仍表示未部署资源，不把它转换成导出失败。

`util/local_fonts.py`抽取既有字体路径/MIME校验供在线路由和导出复用；在线行为保留，导出额外拒绝reparse。用户已有审批/History/WS协议及System拓扑保持不变。当前仅完成源码/差异审阅，未运行校验、构建或应用，人工验收见任务文件。

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

### 文件修改 Tab 的可见投影修订

文件修改REST仍从`file_changes.es`读取，摘要和分页返回当前可见文件与目录条目：会话新增目标删除后隐藏，已有路径删除显示为红色deleted条目；删除后重建同路径显示黄色modified。合成父目录只在前端存在，不计入摘要。`operation_count`包含所有成功目标操作，包括隐藏删除。
连接建立后，服务端发送：

- `build_hash`：当前前端构建哈希，变化时前端提示刷新。
- `server_info`：服务端信息。
- `handsfree_mode`：每次连接都会主动发送的当前会话权威审批模式，包含兼容布尔字段 `handsfree_mode` 与三态字段 `approval_mode`。已有会话由 `ApprovalModeStore` 从 `approval_mode.es` 的 easysave `v1` key惰性重建 `SessionApprovalModeState`；新建普通主会话、派生主会话和首次创建的“随意聊聊”默认手动模式，上下文超限产生的自动延续继承来源主会话的当前模式。前端不持久化该值。
- `history_sync`：新建/恢复连接以及每轮正典 History 写入完成后发送；顶层携带 `history_count`、`processing`、`token_usage`、`context_tokens` 和可选 `agents`，不携带正文。前端随后通过 History REST 按需加载。轮次后推送（`MessageRouter._send_history_sync`）的 `agents` 按会话当前注册 Loop 计算，不按轮次所属 Loop：ExitMultiAgent 退役 MultiAgentLoop 后，其最后一轮的轮次后推送若沿用退役 Loop 会把已清空的 agents 重新覆盖为过期列表，导致前端主徽章停留在多Agent配色。
- `agentspace_event` 初始序列：`resync`、`locks`及 watcher不可用时的 `watcher_error`；随后复用同一 EventHub订阅转发文件变化。事件突发时允许折叠为 `resync`，折叠日志按 `AGENTSPACE_WS_COALESCE_LOG_WINDOW_SECONDS` 时间窗限流并携带窗口累计 dropped；转发 task 登记在 `GatewaySystem.task_owner`，连接断开时经 `TaskOwner.cancel` 预期取消（禁止裸 `task.cancel()`，否则 Owner 会按 RV11 判定为未授权取消并报生命周期失败）并注销订阅；自动旋转复用同一物理连接和订阅。单事件发送超过 `AGENTSPACE_WS_SEND_TIMEOUT_SECONDS` 时抛哨兵异常 `AgentspaceSendTimeout`，done_callback 先经 `TaskOwner.mark_expected_failure` 标记例常预期失败（不触发应用失败关闭）再以 1011 断连驱逐慢消费者连接；该标记回调的注册顺序必须先于 `task_owner.track`（标记先于结算读取）。连接级终止分两类哨兵：`AgentspaceSendTimeout`（慢消费者，客户端仍在线但接收不过来，标记预期失败后以 1011 驱逐）与 `AgentspaceConnectionClosed`（对端已断开，由发送回调在状态预检或收到 `WebSocketDisconnect`/`ConnectionResetError`/`BrokenPipeError` 时抛出，close 帧已发出后的 `RuntimeError` 仅在连接确已断开时归类，标记预期失败后不再发送关闭帧）。两类哨兵均只终止当前连接、不触发应用失败关闭；订阅与连接登记由 `ws_chat` 的 finally 统一回收。done_callback 内判定顺序不可交换：必须先判 `requires_connection_eviction` 再判 `is_connection_termination`，因为 `AgentspaceSendTimeout` 同时满足两者，顺序颠倒会让慢消费者被静默收尾而失去 1011 驱逐能力。发送回调同时用于 `attach_agentspace_events` 的初始事件阶段，故 `ws_chat` 的外层断连分支必须同时捕获 `WebSocketDisconnect` 与 `AgentspaceConnectionClosed`。

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
| `tool_calls_discarded` | 同一模型批次中因前序工具 `accepts_following_calls=False` 被截断、在执行前视为未发生的调用；顶层携带 `session_id`、`stream_id` 与 `tool_call_ids`，前端据此移除对应实时工具卡片。 |
| `task_progress` | 任务进度更新 |
| `subagent_update` | 子会话状态更新 |
| `history_sync` | 正典历史同步元数据；普通追加与轮次状态仍走该事件，正文通过 REST 加载 |
| `history_updated` | `HistoryUpdatedEvent`：仅含固定 type 与非空 session_id。已提交历史发生非追加变更时要求前端完整重载历史骨架与按需正文；不刷新页面、不重放工具，也不依赖消息数下降。 |
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

`entity.puretype.ws` 中的 `StreamDeltaEvent` / `StreamDoneEvent` 是下行流式事件的权威模型，`StreamEvent` 以 `type` 区分两者。`FrontendSink` 直接持有并发送模型；Gateway只负责连接生命周期，不再提供 `_send_tool_event(session_id, event_type, tool_name, payload)` 字符串回调，启动时也不再注册该旧回调。Gateway经`Application.current().get_system(IFrontendSink)`取得唯一实例（`_get_ws`、HTTP confirm/ask、会话占用检查、删除关闭、Profile广播与连接释放均走此入口），不再访问`Application.frontend_sink`属性。

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
- 关闭顺序：先 `stop_accepting()` 封闭新输入（既有输出连接保留到 History 刷新完成），`cancel_background_work()` 取消自动标题/准备/恢复等路由后台任务，最后 `stop_server()` 请求 uvicorn 退出。serve 或 socket 观察超时保留真实句柄并记录资源清理待完成，不提前丢弃任务，也不把该局部超时升级为全应用失败。Gateway 是最后唤醒、首先资源注销的 System。
- uvicorn 由 GatewaySystem 子类 `_GatewayUvicornServer` 管理：禁用自身信号安装（App 统一处理信号），startup 成功后置 ready 事件；启动等待 ready、serve 提前结束与 30 秒超时三者竞速。

## HTTP 请求类型边界

Gateway 遵循快速失败：只将明确的业务异常映射为 HTTP 400/404/409 等状态；逻辑之外的异常直接传播给 FastAPI，不额外捕获后转换成通用 500，不返回空列表或默认请求继续执行。请求体 JSON 语法/编码错误返回 400，模型校验错误返回 400；原有 `default_on_json_error` 已移除，要求 JSON 请求体的端点不再用空模型替代无效 JSON（包括空 body）。

普通 HTTP 返回值保留 BaseModel，包括字典/列表中的嵌套模型，由 FastAPI 自动序列化。需要展开字段并增加兼容字段的响应暂保留字典适配；显式 `HTMLResponse` 的 JSON 正文使用 `model_dump_json(exclude_none=True)`，保持原有动态状态码及省略空字段的协议。WebSocket/SSE 不走普通 HTTP 返回值编码，仍在实际发送边界编码。HTTP 附带 WebSocket 通知在编码后跳过明确已关闭的连接，仅捕获 `WebSocketDisconnect`；模型构造、编码和其他内部错误不被吞没。

Profile API 只捕获 `ProfileNotFoundError`/`ProfileConflictError`，不捕获通用 `LookupError`/`ValueError`/`OSError`。动态沙盒空间管理仅映射 `DynamicSandboxInputError`（400）、`DynamicSandboxConflictError`（409）、`DynamicSandboxNotFoundError`（404）及既有 `SandboxError`；不靠错误文本猜测冲突，也不把类型错误当作用户输入错误。Agentspace REST 仅映射 `AgentspaceError`；意外错误直接交给 FastAPI，其 500 响应不承诺旧版自定义 JSON `detail` 结构。

Gateway REST 的 JSON 请求体在进入业务逻辑前统一解析为 `entity.puretype` 中的 Pydantic `BaseModel`。会话操作请求位于 `session.py`，confirm/ask 入站请求位于 `ws.py`，动态端点请求位于 `extools.py`，Agentspace 垃圾桶操作请求位于 `agentspace.py`。合法 JSON 中省略可选字段时沿用模型默认值；非法 JSON 不再使用默认请求，业务代码通过属性访问稳定字段。

动态端点的 `content` 使用稳定的多模态 content block 联合类型；content block 对未知扩展字段保持兼容，Gateway 在进入既有消息队列前转换为内部 `MessageContent` 结构。该转换是传输边界适配，不改变 History 或 LLM wire format。前端请求字段和 JSON wire format 保持不变。

## 全局活动事件接口

Gateway 新增只读 `/api/activity/overview` 与 `/api/activity/events`。overview 从 SessionManager/ToolRegistry读取当前会话、活跃主会话Loop、工具和工具集数量，不创建Loop；events只订阅LoggerSystem在连接建立后的增量事件，不发送历史快照或 `id:`，每个等待任务由GatewaySystem.task_owner登记，断线/取消/关闭在生成器finally中清理。

MessageRouter在主会话输入登记成功后，通过 `Application.current().get_system(IGatewaySystem).record_activity()` 发布 `message_received`，复用 `ILoggableSystem` 的活动事件转发，不直接取得Logger。GatewaySystem的Logger依赖由能力基类自动声明，构造不再重复列出。SSE订阅与取消订阅仍直接使用 `ILoggerSystem`，因为能力基类不提供订阅接口。事件载荷、发布时序和连接清理不变；本次未运行校验或应用。

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
| GET | `/api/sessions/{id}/tab-capabilities` | 只读返回媒体实例数量和变量 Tab 可见内容标志；不返回媒体载荷或变量正文，需要现存主会话 Loop，Loop 未就绪/旋转时返回409；变量目录扫描沿既有预算和错误映射执行 |

仅查询当前注册主会话Loop，不创建Loop、不另读活动磁盘History。新操作使用RUNNING准入/no-store：会话缺失或删除中404，存在但无Loop或正在旋转409；409不等于会话删除。归档已恢复Loop可GET及补齐旧身份，用户PUT403。处理中允许修改媒体开关，从保存后的下一模型请求生效，已开始请求不撤回。无新WS通知、SSE或轮询。

非法参数/ID/JSON/非boolean请求400，实例消失404，expected冲突409；预览格式不支持415、编码错误400。仅映射专门业务异常，损坏重复ID或必要写盘失败不返回默认清单。GET旧身份补齐可能严格写History，失败沿原HistoryPersistenceError可能导致500与应用失败关闭；归档“用户只读”不豁免系统元数据迁移。预览只解码一个块、无临时文件和Range；nosniff，SVG加sandbox CSP，不能把任意MIME当HTML执行。

清单支持普通/随意聊聊/多Agent主会话，不包括独立子会话或未进入History的上传/Markdown资源。关闭不减少History磁盘体积；PUT仍全量写盘，保存超时的前端须GET确认，不自动重试写入。源码已实施，未运行验证。

列表响应的 `items` 分页保持不变，另在顶层增加六个全 History 聚合字段：`enabled_count`、`disabled_count`、`enabled_inline_payload_chars`、`disabled_inline_payload_chars`、`enabled_unknown_payload_count`、`disabled_unknown_payload_count`，由 `entry/history_media.py::project_history_media` 在同次遍历中计算（含分页之外的全部实例）；`session_id`/`history_count`/`total_count`/`offset`/`limit`/`editable` 与内容端点、PUT 开关语义不变。

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

`GET /api/sessions/{id}/variables`返回SessionVariablePoolResponse，直接复用AgentspaceService.session_variables.read_pool，与ReadSessionVariables的值/meta/issues一致，不创建Loop。`GET /api/sessions/{id}/tab-capabilities`则与媒体数量合并为右侧 Tab 的能力探测：只返回媒体数量和是否存在变量条目/可展示问题，不返回变量正文；该合并端点因媒体 History 位于现存主会话Loop中，Loop未就绪或旋转时共同返回409。变量完整REST仍可在无Loop时读取，继续使用no-store、RUNNING准入、读取前后存在性/删除中复检；归档及随意聊聊可读，已删除/删除中404，即使留下变量文件也不会复活会话。

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

Cron REST、Loop路由注册/注销与会话清理统一调用 `get_system(ICronRouter)`，不再导入cron_tools获取服务。任务持久化、调度和实际命令属于CronRouter；应用冻结不同于用户取消，不删除持久任务或把未执行任务标为完成。激活由 Application 在全部 System 唤醒且 Gateway ready 后统一执行，关闭编排由 Application 统一执行。`GET /api/sessions/{id}/cron-tasks` 原样返回 `CronTaskInfo` 列表，响应新增只读字段 `is_wait`/`wait_message`（等待提醒身份与内容），路由、调度与执行语义不变。

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

自动标题、自动标签和摘要直接调用 `Application.current().get_system(ISessionMetadataService)`，不要求目标会话存在运行时 Loop。全局元数据 Profile未配置时按目标会话自己的活动 Profile回退；明确配置但不可用时返回失败，不静默回退。配置变化通过 `metadata_profile_changed`广播。删除当前元数据 Profile只清空全局引用，不自动采用删除请求中的替换 Profile。

### 全局多模态回退 Profile

| 方法 | 端点 | 说明 |
|---|---|---|
| GET | `/api/modality/profiles` | 一次返回图片、音频、视频三路全局回退 Profile 的名称、模型和可用性 |
| PUT | `/api/modality/profiles` | 请求体 `{media_type, profile_name}` 只更新其中一路；`profile_name: null` 清空该路引用 |

多模态回退引用直接保存为 `LLMProfileData` 根对象中根列表实例的引用。运行时先使用活动 Profile 的对应引用，只有该引用为空时才读取对应全局引用；活动引用存在但不可用或调用失败时不切换全局回退。三路引用独立管理，Profile 被任一路全局多模态引用时删除请求会被拒绝，用户须先清除引用。Profile 更新后的可用性和名称变化通过 `modality_profile_changed` 广播；非预期异常不被转成普通转发错误。

`/files` 的会话视觉入口支持 GET/HEAD 探测：源目录同级 `.meta` 的 `[redirect]` 只解析一层，合法目标通过 307 指向带 `visual_raw` 的原始入口，避免目标目录再次解析；最终 HEAD 响应返回 `X-Session-Visual-Version`。无效配置静默使用源目录，普通静态文件不受影响。site 的 `/zip` 源目录同样复用该规则。

`/files`、`/downloads` 与 `/zip` 均复用 `Application.current().get_system(ISandbox)`，不再临时构造 Sandbox。因此 fast 模式下可读且当前目录存在的全局动态沙盒空间也遵循同一逻辑前缀解析、遍历防护和权限检查；fallback 不启用动态空间。

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
| `tool_resources.json` | 任务进度等工具资源（旧版兼容读取） |
| `approval_mode.es` | easysave `v1` key保存的 `SessionApprovalModeState`；BaseModel直接保存并通过 stable type token重建，缺失、缺 key、损坏或类型错误时回退手动模式；模式变更先更新内存再尽力保存，安全写入与 `.bak`由 easysave负责 |

归档保留 `approval_mode.es`；永久删除会话目录时一并删除，随后清理 Store缓存。单源分支和多父合并不会复制来源模式，新会话统一写入手动模式；上下文超限产生的自动延续会继承来源主会话的当前模式。

全局会话索引：`workspace/sessions/_index.json`。

## 文件修改记录 REST 与永久删除

新增只读`GET /api/sessions/{session_id}/file-changes/summary`及`GET /api/sessions/{session_id}/file-changes?offset=0&limit=100`。通过`Application.current().get_system(IAgentspaceService).file_changes`读取唯一Store，使用线程池，不创建Loop、不读History；已归档或尚未恢复Loop的已知会话都可读。摘要只含会话、revision、文件/目录路径条目数、全局操作次数和最近UTC时间；分页附同次摘要与最多200行条目，默认100。未知/删除中404，参数越界422，停机503；返回前二次确认会话，Cache-Control=no-store。读取损坏不伪空，普通返回值保留BaseModel。

独立持久文件为会话目录内`file_changes.es`，不在ws:工作空间的sessions资源目录。新会话缺文件返回空，不回填；已有文件缺key/损坏/残留备份直接失败。

永久删除现在由既有GatewaySystem.task_owner.run_request管理完整REQUEST。原业务主体移入`_delete_session_impl`，在begin_session_delete后的try内先进入`_file_changes_delete_scope`，成功封闭统计后才按原顺序关闭连接、停止子Agent/主Loop、sm.remove、清理资源，最外层finally仍清deleting标记。block_session在线程中有界等待5秒，超时只返回409且不提前拆除连接/Loop。scope以shield等待真实封闭/收尾线程，调用方取消不放弃真实工作；会话尚在则解封，已删则forget并保留封闭标记。必要清理失败保留异常并传播，不把取消外层等待当作线程已经结束。

统计保存前验证会话目录已存在，easysave内部可建父目录但删除封闭防止迟到写入重建会话目录。封闭后的旧GET不再打开待删除统计文件，已知删除竞态映射404，其他读取异常继续传播。统计文件随会话目录删除，不删除原业务文件。仅源码实施与只读审阅，尚未运行验证。

## System 接口槽位约定（2026-10-20）

`SessionManager` 和 `GatewaySystem` 分别使用 `ISessionManager` 与 `IGatewaySystem` 作为 Application 装配槽位。Gateway 路由、会话清理、动态端点和前端连接查询均按接口取得唯一实例；GatewaySystem 仍最后唤醒、首先注销，SessionManager 的输入冻结、轮次停止和 History 刷新顺序不变。

## 单次强制调用工具入站协议（2026-10-23）

`Message`（user_message）与 `SessionRegenerateRequest` 新增 `require_tool_call: StrictBool = False`；省略保持自主选择，字符串/数字/null不转换为开启。该参数只属于当次操作，不写History、Profile或easysave。USER_MESSAGE仅为主目标创建QueuedMessage时传递，子会话转发不携带；服务端当前is_active为真时将其固定为false，正常接收补充正文，不将false提升为true。

重新生成在请求体解析前后用is_active尽力拒绝忙碌操作（409），字段错误返回既有400结构及 `invalid require_tool_call`，之后显式传给process_message。值来自当前请求，不读历史旧选择。resume协议及工具链后续请求不启用此要求。多Agent用户初始指定响应者各自首次模型请求强制一次。

is_active只覆盖已经登记活动快照的排队/准备窗口；accept登记到主loop唤醒之间仍可能短暂为false。活动复检不是强互斥，不修复所有既有History截断并发风险。前端请求发出即消费，不等待服务端确认；前后端状态延迟导致服务端按普通消息处理时也不恢复选择。已实施源码和文档，未运行校验或应用。

## 全局工具循环配置 REST（2026-10-26）

`GET /api/agent-loop/settings` 返回 `AgentLoopSettingsState`：`max_tool_turns`（自定义正整数或null）、`effective_max_tool_turns`（当前有效值）、`default_max_tool_turns`（MAX_TOOL_TURNS，当前90）。只查Runtime持有Store的缓存，不创建Loop或默认文件，响应 `Cache-Control: no-store`。

`PUT /api/agent-loop/settings` 必须显式提交 `max_tool_turns`；null恢复默认，合法整数范围1至9,007,199,254,740,991，严格拒绝布尔/字符串/小数/额外字段。入口先业务准入，经既有 `_parse_request_model` 读取后再次准入，再同步保存并返回同型权威状态。无效JSON/字段400，停止503，存储/备份冲突和内部错误沿FastAPI失败边界传播，不返回默认值或成功。保存不持Runtime接收锁跨磁盘，不新增后台任务、WS事件或广播；无会话ID、Profile和归档写入限制。

正常保存后各Agent下一次循环检查读新值，当前请求/批次继续；其它前端需主动重读。客户端超时不代表请求未提交，GET也不是旧PUT终止屏障；多个页面按服务端最后成功提交生效。新前端遇到旧后端404/HTML明确报错，不猜测默认90。仅源码实施与只读审阅，未运行校验、构建或应用，需用户同批部署验收。

## Gateway最终注销等待（2026-10-28）

stop_server仍提供既有软观察窗口；virtual_shotdown在serve仍pending时最终shield等待同一serve task真实终结，不以返回pending代替退出，不重建/取消serve。路由TaskOwner必须idle才允许资源注销，已创建的会话导出线程池实际close后才清引用；异常由Application即时记录并保留依赖到硬截止。Gateway仍先于其他System注销，输入冻结和History刷新后才结束已有输出的顺序不变。纯端口占用维持普通业务拒绝，混合启动/清理失败不得误报退出0。本次仅源码与只读审阅，未运行校验或应用。

## Runtime 依赖继承（2026-10-30）

`ISessionManager` 和 `IGatewaySystem` 改继承 `IDPRuntimeSystem`，具体实现仍只继承对应接口；构造只声明其余业务依赖，Runtime 与 Logger 依赖由公共基类链自动加入。最终依赖集合、21个槽位、服务唤醒关系与业务关闭顺序不变。`IGatewaySystem` 移除重复抽象 `runtime`，GatewaySystem 的缓存属性覆写和两个实现的 `_runtime` 引用保留，支持 framework 解绑后的现有关闭路径。

`GatewayAdmission` 和 `SessionExportService` 保持显式 Runtime 注入，MessageRouter 保留原有查询方式，均不是本次公共基类的继承对象。路由、History 提交、导出、WebSocket、SSE 和端口占用分流不改；未运行校验、构建、实际导入或应用。

## Runtime 无缓存与绑定期间关闭（2026-10-30，当前约定）

SessionManager/GatewaySystem删除`_runtime`，Gateway的具体属性覆写也移除；System业务访问继承`runtime`，初始化向GatewayAdmission/TaskOwner/SessionExportService传入的Runtime只作函数局部引用。前节缓存保留约定由本节覆盖。Session停止/Loop退役完成观察在创建时绑定失败能力，不在迟到回调重新查System。

原关闭主体移至`virtual_prepare_shutdown`，在架构仍绑定时等待回复/队列/History交接、serve终局及导出线程池close；framework真正关闭钩子仅核对准备结果。Gateway的失败awake从叶服务资源创建起进入异常边界，`prepare_failed_startup`持有唯一真实清理：端口预检失败也释放先前创建的导出服务，serve/Owner/socket/导出独立必要释放保持可审查，原始错误与清理失败保留为异常组。单纯端口占用仍是普通拒绝；未确认安全的清理不继续拆依赖。

Application仍先业务停止和History刷新、最后结束输出，再执行关闭准备与原Logger根级联。非System注入、MessageRouter查询、21槽位、协议/持久化和5秒硬截止不变；未运行校验、导入、测试、构建或应用。

## API端点组件与HTTP边界（2026-10-31，当前权威）

详细目录及新增端点步骤见[apis/DEV-README.md](apis/DEV-README.md)。组件通过parent_system取得唯一Gateway，不在模块导入/注册时查Application或创建连接；register_apis单次显式装配，重复绑定直接失败。server不再导出router、ws_chat、push_subagent_update或_flush_pending_changes；通知调用统一新路径gateway.notifications，真实Agentspace变更摘要仍经IAgentspaceService公开服务。

### 准入、校验与错误

- 原生ASGI中间件只匹配`/api`、`/dynamic`完整首段，在正文和校验之前要求RUNNING，包括查询和新建SSE。前置503明确携带request_accepted=false；在途停止503不携该保证，已提交状态不回滚。健康检查、public资源和WS原连接规则不被中间件改写。
- 请求JSON格式/Unicode、字段/Literal/StrictBool、Path/Query范围错误采用FastAPI标准422列表。导出resource/verify先有界流读，超量413/超时408，之后校验安全转换为422，排除原body/bytes/input/ctx/url。
- 明确业务拒绝统一结构化detail：会话缺失404、未恢复/旋转/忙碌409、归档聊天写403、交互过期404、Cron/Shell不存在404、Profile冲突409、文件锁423等。原Agentspace code/path/current_version（含null）/locks、变量path、导出source/proof和中断detail.result保留。未知异常不泛捕获；内部损坏不能变空数据或默认成功。
- /status的exists=false、选文件/目录取消、空资源、正常取消置顶、Shell pending、垃圾桶/文件上传部分失败和元数据/广播warnings保持原正常结果。标签更新仍保留既有成功tags=null字段；后台逐项验证后才提交，前端只有明确updated成功才采用本次提交值。
- 不提供旧顶层error/字符串detail的业务协议兼容。框架HTTP404/405按HTTP协议转换且保留Allow；非法业务路径不由SPA返回200 HTML。普通页面/文件成功、HEAD无正文、视觉307/版本头及原静态挂载次序保持。
- handle_http_exception按Starlette的ExceptionHandler回调契约声明exc: Exception，在函数入口显式收窄为StarletteHTTPException；非该异常族直接重新抛出。注册仍限定HTTPException，不注册通用Exception捕获器，也不使用cast/Any掩盖回调参数逆变约束。

### 生命周期不变量

SSE与WS的订阅/任务/连接仍属于原Gateway TaskOwner、FrontendSink与Agentspace服务；新入口准入不用于逐次阻止旧输出。关闭仍先提交History再结束输出；WS旋转、旧连接保护、4001/4004/1001/1011及预期失败回调先于Owner结算保持。删除与导出仍等待真实线程/容量交接，不将取消包装等待当资源结束。同步文件和ZIP不改async。Profile根引用、锁及保存/缓存/广播顺序不变。

源码已实施，未由开发助手AI运行任何测试、校验、导入、构建或应用；人工验收按任务文件P9/P19。须用户停机同批部署完整包与前端、构建并重启/刷新，外部调用方升级错误协议；开发助手AI不操作workspace或清理运行时残留。


