# system/ — 基础设施与异步生命周期

## 前置辅助模块边界（2026-10-22）

`pathutils`、`templates`、`text_codec`、`text_preview`、`convert`、`error_utils`、`file_metadata`、`local_fonts`、`pkgmgr`、`atomic_io` 十个整文件已迁入同级 `util/`，原路径不保留转发；模块地图和依赖约束见 [util/DEV-README.md](../util/DEV-README.md)。System、叶服务、RuntimeContext、TaskOwner、ShellTextNormalizer 及业务组装模块仍留在本包，20 个 System 的装配和资源所有权不变。

`prompt.py`、角色数据组装与搜索仍依赖具体业务实现，本次只更新其辅助模块导入，不作为前置辅助模块迁移。`util/__init__.py` 保持为空；`atomic_io` 的 Windows DLL 绑定仅随该模块的显式导入发生。函数契约、错误策略与持久化格式保持；只做源码和静态审阅，未运行校验、构建或应用。

## 迁移状态

本包已按 `.tasks/2026-10-07_1_async-architecture-system-lifecycle.md` 完成 framework 迁移：20 个 AsyncSystem（RuntimeSystem→…→ToolDiscoverySystem→GatewaySystem）由 `Application.start()` 按固定拓扑顺序串行注册，先用 graphlib 校验依赖图；全部唤醒后 `RuntimeSystem.mark_running()` 并激活 Cron，输入接收才开放。`Application.shutdown()` 是唯一关闭协调任务：先冻结输入并停止生成，子会话输入与反馈交接后主/多会话按 sequence 只落 History 并严格写盘，随后结束 SSE/WS 与 uvicorn，最后按装配逆序注销；必要写盘或资源释放失败合并上抛（退出码 1，绝不返回进化成功 -1）。S16/S17 的 InputDelivery、退役 Loop 与反馈交接、S21 的 Gateway 接收登记均已接入。上述均为源码实施与定向静态审阅结果，尚未运行验证。

## 已实现的所有权

| 类型 | 职责 | 依赖 |
|---|---|---|
| Application | 唯一AsyncArchitecture实例及完整依赖图检查；最终装配另阶段接通 | 注册表由framework持有 |
| RuntimeSystem | 唯一RuntimeContext、主事件循环、输入接收锁、序号、关闭信号和失败记录 | 无 |
| SubprocessRunner | 同步/异步内部子进程、正在创建的进程及实际操作完成记录 | RuntimeSystem |
| Sandbox | 固定命名空间、全局动态空间、文件I/O及子进程委托 | RuntimeSystem、SubprocessRunner |
| ShellManager | Shell会话、原生PTY、reader线程和业务/原生/关闭任务 | RuntimeSystem、Sandbox |
| AgentspaceService | 文件操作、文件锁、垃圾桶恢复、事件总线、watcher及视觉资源叶服务 | RuntimeSystem、Sandbox |
| LLMProfileStore | 唯一LLMProfileData根对象、所有Profile CRUD与共享RLock | RuntimeSystem |
| SessionMetadataService | 会话标题/标签/摘要生成及其在途元数据任务 | RuntimeSystem、LLMProfileStore |
| ApprovalSystem | 审批模式、白名单、后端与模型审批请求 | RuntimeSystem、LLMProfileStore |
| FrontendSink | 前端连接、交互及真实发送任务 | RuntimeSystem |
| ToolRegistry | 工具表、检查缓存、异步请求与真实同步Future | RuntimeSystem |
| LSPManager | pyright进程、读取线程、响应等待及清理任务 | RuntimeSystem、Sandbox |
| BrowserSystem | CDP/Playwright、自有无头进程及清理任务 | RuntimeSystem |
| ModalityCapabilitySystem | 探测锁、媒体、缓存路径、探测与转发请求 | RuntimeSystem、LLMProfileStore |

RuntimeContext继续是不可变BaseModel；system.context不再提供模块级配置单例。业务通过已持有的app获取`get_system(IRuntimeSystem).context`，不创建备用上下文。Application.current()/get()只取得同一个已创建实例，不调用framework的默认惰性工厂。

## 生命周期公共工具

`system/lifecycle.py::TaskOwner`仅由所属System持有，不扫描`asyncio.all_tasks()`。`create/track`明确管理后台任务，意外异常或无来源取消会向System上报；有明确调用方等待结果的工作使用`run_request(factory, admission=...)`，普通异常交回请求方，预期请求取消不触发整个应用失败。`LifecycleFailure`及含有它的异常组始终上报，不能被请求级分类隐藏。例常的连接级失败可在结算前经`mark_expected_failure(task)`标记为预期失败（仅豁免BACKGROUND任务）：结算时不向所属System上报，`LifecycleFailure`及其异常组仍始终上报不被豁免；标记须在首次结算（`terminal_reported`置位）前完成，经done_callback调用时（task已结束、结算未发生）置位仍先于结算生效，返回False表示已错过；调用方需保证标记回调的注册先于`track`的结算回调。

请求任务在执行工厂前通过启动屏障完成所有权登记，并再次检查接收状态。`cancel(task)`先标记预期取消再发出一次取消，不重复打断finally或重置清理截止。请求方再次取消时，可以退出等待，但Owner继续持有同一清理任务；实际子任务超时未退出仍保留强引用并报告失败。`pending`表示活任务，`is_idle`还要求请求结果/取消交接完成。整个Owner关闭只汇总后台与生命周期失败，已交给请求方处理的普通异常不在之后重复上报。

所有记录绑定所属事件循环；原生线程和子进程仍由各System登记真实Future/进程，TaskOwner任务结束不等于这些资源已释放。

`close_resources()`只用于必要释放：尝试完成各独立释放动作，然后以BaseExceptionGroup保留原异常；它不是继续业务的通用异常降级器。

`entity/puretype/lifecycle.py`中的输入投递记录、关闭统计和工具通知都是非持久化模型，不改变History文件格式。子会话反馈交接数据定义在puretype/subagent.py。

## RuntimeSystem

System构造不取得外部资源；virtual_awake绑定主事件循环并进入STARTING。整个应用就绪后才允许mark_running，STOPPING不能被覆盖回RUNNING。

admission同步区间用于同时校验运行状态和登记完整输入，不允许在其中await、访问磁盘或调用模型。request_shutdown在锁内封闭接收，通过call_soon_threadsafe设置主loop事件；record_failure先分离明确的资源清理超时，只保留其余失败并请求失败关闭。

关闭硬截止由该实例持有的daemon Timer执行，超时只执行失败退出，不获取业务锁或日志锁。它不能在framework注销RuntimeSystem时提前取消；最终取消位置在后续App/asyncio.run外层接线。资源清理待完成不能被报告为进化成功，也不能单独把正常退出改成失败。

## 资源清理登记

`system/resource_cleanup.py` 是 RuntimeSystem 持有的进程级叶对象。资源所有者在创建前取得 reservation，在释放时登记唯一真实任务。观察超时返回 `CleanupReport(complete=false)`，不取消真实清理，也不按异常文本猜测可恢复性。无法证明原始进程身份时禁止查杀，保留引用并保持未完成。

## SubprocessRunner

三种run入口在进程创建前登记操作。同步Popen和异步创建任务都拥有明确完成记录；调用方取消等待，不会直接从登记表删除尚未退出的进程。异步创建使用独立且受跟踪的任务，取消时仍取得/回收创建结果。

kill_active只请求终止，不清空注册表。原run操作在确认进程退出、完成管道/读取任务收尾后才解除登记。terminate_all关闭接收并终止已登记进程，晚完成创建的操作自行终止；wait_idle同时等待正在创建及执行的操作，不使用未填充的等待集合冒充空闲。

清理失败继续传播且保留资源记录；同步wait通过工作线程执行，不在主loop等待Popen退出。同步/异步调用的TimeoutExpired语义、stdout/stderr解码和逐行输出截断策略保持。

## Sandbox

Sandbox为无参AsyncSystem，virtual_awake取得唯一RuntimeContext和SubprocessRunner，加载fast模式全局动态空间。fallback仍不读取或启用这些动态配置；目录暂时不可用仍是原有业务状态，不改变权限规则。

业务通过get_system(ISandbox)取得唯一实例，禁止从另一个工具模块导入私有_s入口。它没有自有进程线程，关闭不删除动态空间文件或清空持久映射。

## ShellManager

业务操作从接收开始到锁等待、原生调用及结果返回均有任务归属；原生线程调用使用独立受跟踪的任务，取消外层协程不等于原生工作完成。创建中的PTY先登记状态，取消或关闭发生在创建期间也会回收最终结果。

关闭先停止接收并中断活动操作，等待仍会写业务状态的原生任务结束，再把纯资源释放交给清理登记器。每个 Shell 只有一个实际关闭任务；全部释放确认后才从会话表移除。显式停止返回 `ShellStopResult`，`stopped` 只能等于 `cleanup.complete`。

先请求一次已授权的进程树终止，再在原生操作锁内关闭 PTY，然后等待 reader 退出。reader 或锁观察超时保持同一任务继续，不并发第二次 close，也不把清理超时升级为全应用失败。原有会话/角色所有权、旋转迁移和 WebSocket 断线不停止 Shell 的约定不变。

已知待处理问题：2026-10-13会话终结及2026-10-16显式StopShell均观察到reader未在5秒内退出，沿既有生命周期失败策略导致应用关闭；本次工具对象化未修改该停止实现。`_stop_state_blocking()`的reader等待处已登记TODO，调查pywinpty/ConPTY读取唤醒及PTY释放顺序，根因尚未确认。当前仅记录复现，不吞清理失败、不取消真实线程退出确认、不扩大等待期限。

## AgentspaceService

virtual_awake完成原构造与start：取得Sandbox，构造事件总线/文件锁/垃圾桶/watcher和visual_resources叶服务，绑定loop，恢复垃圾桶，启动watcher。已启用watcher启动失败会导致初始化失败，不降级为启动成功。

Agentspace 逻辑路径由 `AgentspaceService._normalize()` 统一规范化：命名空间前缀后只能是相对路径，路径段之间使用 `/`，不能以 `/` 或 `\` 开始或结束，也不能包含 `\`、空路径段、`.` 或 `..`。目录路径不使用末尾斜杠；文档中目录示例的末尾 `/` 只是说明性记号，不能原样传给文件工具。路径不自动删除末尾斜杠或把反斜杠转换成正斜杠。Agent 文件工具会在实际读写前登记 `ws:` 路径锁，路径不符合规范时先报 `Agentspace access lock failed`，不会继续执行文件操作。统一规范化保证路径锁、父子路径匹配、文件变化事件和文件修改记录使用同一个逻辑路径身份。

初始化失败时也等待正在恢复垃圾桶的线程结束并释放已取得资源；Observer在start前即记录，部分启动可以找到资源并停止。最终virtual_shotdown在后续应用编排完成History提交及Gateway事件流关闭后执行。

watcher停止时封闭新的debounce安排，取消并join已持有Timer及Observer，检查实际存活状态；超时是资源清理失败。SessionVisualResourceService仍为独立可复用业务类，由`get_system(IAgentspaceService).visual_resources`暴露，不自行创建另一份Sandbox。

## LLMProfileStore

注册为framework AsyncSystem，依赖RuntimeSystem；无参构造，virtual_awake取得RuntimeContext确定agentspace路径并加载v2根对象。Store自身创建唯一的共享``threading.RLock``，通过``locked()``上下文管理器暴露同一把锁，替代原Application.profile_lock；SessionMetadataService、审批后端及Gateway Profile CRUD均经此接口进入事务边界，不再注入第二把锁。

原六写方法的「先准备候选、保存成功后提交共享内存」顺序不变；update的两阶段复制并重连引用图、Profile实例身份与根对象引用图、先save后commit、easysave直接保存LLMProfileData的约定完全保留。未替换easysave为framework存储，未复制实例替代注册表根。业务经``get_system(ILLMProfileStore)``取得唯一实例。

## SessionMetadataService

注册为framework AsyncSystem，依赖RuntimeSystem与LLMProfileStore；无参构造，virtual_awake取得依赖并创建本服务的SessionStore。不创建独立Profile事务锁，所有原``_profile_lock``语义统一经``LLMProfileStore.locked()``访问同一把共享RLock。

五个公开异步入口（generate_title、generate_tags、generate_summary、regenerate_summary、ensure_summary）通过TaskOwner.run_request登记完整操作，覆盖历史读取、Profile选择、模型调用、解析和必要写盘。内部ensure→regenerate→generate仅调用内部实现，不嵌套公开请求包装；原来只登记client.chat的_run_llm_call已移除。所有公开返回类型保持不变。

_admit_generation在Runtime接收锁内只校验服务接收状态，不执行I/O或模型调用；_create_client在新模型调用前再次检查状态。close_admission在所属loop同步设置服务关闭标志，STOPPING时也合法；cancel_pending先封闭接收再等待Owner的任务和结果交接，virtual_shotdown即使pending为空也核对Owner历史失败，不在解绑后get_system。普通元数据错误仍交原业务边界；生命周期失败、取消及相关异常组继续传播，不能被包装成普通MetadataGenerationError。

元数据Profile优先与会话回退语义不变；关闭消息刷新不调用本服务生成接口，仅允许既有钩子做只读查询。既有业务Profile选择及fallback保持；Runtime停止后不新启LLM。全量Application.session_metadata_service引用已迁移为``get_system(ISessionMetadataService)``。

首条用户消息自动标题：MessageRouter在准备任务内调用同步入口``maybe_generate_first_title(session_id, text)``（前置「标题为空+文本非空」判定保留在路由层）。入口在同一同步代码段内完成per-session防重集合（``_first_title_pending``）的检查+登记，经``task_owner.create``派发一次性后台任务（不套run_request，与内部实现不嵌套公开包装的惯例一致）。任务体``_first_title_task``按固定分流：LLM成功→``_apply_first_title``写入标题（内存+磁盘）并经SYSTEM消息推送``session_title_updated``；``SessionMetadataError``及未知业务异常→30字符截取回退（``_fallback_title``）后同样写入推送；``ApplicationStoppingError``停机竞态与``LifecycleFailure``（create入口捕获）均静默放弃不写标题，避免把正常停止翻转为失败关闭；``CancelledError``传播；finally对称清理防重集合。``_apply_first_title``中SessionManager/FrontendSink经``Application.current().get_system``动态取得（依赖图不变），update_title磁盘失败与推送失败均仅warning降级不回滚。

## 审批系统接入

`component/approval/system.py::ApprovalSystem`已实现，依赖RuntimeSystem和LLMProfileStore；会话审批模式、后端管理器和白名单均为该System的叶对象。Application不再定义ApprovalBackendManager或提供审批服务属性。模型请求采用TaskOwner.run_request，关闭先结束实际请求再清除后端缓存引用；审批Profile未配置仍是原有业务状态，三种审批模式与白名单持久化策略保持。

## FrontendSink接入

`entry/agent_sink.py::FrontendSink`只继承`IFrontendSink`（该接口本身是`AsyncSystem`子类并继承`IAgentSink`），依赖RuntimeSystem；无参构造只创建内存字段，`virtual_awake`取得RuntimeSystem并创建TaskOwner。Application不再提供`frontend_sink`属性；全量`app.frontend_sink`/`Application.current().frontend_sink`引用已迁移为`get_system(IFrontendSink)`，包括Gateway、MessageRouter、SessionManager、main.py引导Loop、审批core、ask_question工具与ParentAgentSink转发路径。

发送与交互属有调用方等待的请求级操作，经`TaskOwner.run_request`登记。新交互（`request_approval`/`ask_question`）只在RUNNING接收：`_admit_interaction`经`RuntimeSystem.require_running`校验并检查`_interaction_closed`，关闭后返回ApplicationStoppingError而非发起模型或等待前端。既有结果与History回显（`emit_*`与四个broadcast）在STOPPING仍允许到关闭输出：`_admit_send`只检查`_send_closed`，不要求RUNNING，使关闭刷新的发送不被Runtime.require_running拒绝。

关闭发送期限不超过`SHUTDOWN_SEND_TIMEOUT_SECONDS`（1秒）。网络断线/明确发送超时只跳过网络输出，不回滚History；模型构造/序列化错误与其他内部错误传播——`_send_stream_event`与`_send_message_model`将模型构造与JSON序列化置于网络try之外，序列化错误不被`except Exception`吞掉。

`cancel_pending_interactions`同步解除所有待审批与提问Future。`close_all_connections`以标准1001关闭所有连接，结束连接前调用`cancel_and_wait`等待/取消真实发送任务及交接；本方法不登记进同一TaskOwner再等待自己，由独立应用关闭任务协调；`_closing_connections`标志防止重复close并发。`close_session`保留永久删除4004语义，与应用退出1001分开。`virtual_shotdown`关闭接收、取消在途请求并关闭连接，资源/内部错误传播。

ParentAgentSink不作为System；它直接实现`IAgentSink`，其转发方法经`Application.current().get_system(IFrontendSink)`取得唯一实例，不在运行时新建单例。所有原emit签名与消息协议保持不变；typed stream boundary不退化，`_send_stream_event`仍是流式事件唯一序列化发送边界。

## ToolRegistry接入

`abstract/tools/registry.py::ToolRegistry` 是依赖 RuntimeSystem 的 AsyncSystem，拥有工具/工具集/可用性缓存及唯一执行器。工具表按名保存 `BaseTool` 对象，工具集元数据使用 `BaseToolSet`，运行期成员索引为 `_tool_names_by_toolset`；模块级单例与兼容代理均已删除，运行期使用 `get_system(IToolRegistry)`。注册期由 `ToolDiscoverySystem` 按 AST 识别顶层 `TOOLSET` 后，以 `register_toolset(toolset, merge=True)` 装载 `BaseToolSet` 并执行一次 `preheat()`；`register_tool(tool, replace=True)` 供 MCP 动态刷新原子替换同名工具；查询入口为 `get_tool`/`get_toolset`，不再有 `get_entry`/`get_toolset_entry` 或函数式 `register`。

异步请求通过 TaskOwner.run_request 托管；同步 handler 通过 contextvars.copy_context 和 executor.submit 保留上下文及真实 Future。SyncToolCallRecord 是非持久化纯数据记录，真实线程结束且请求交接完成后才解除登记。请求取消不提前清除原生工作，迟到失败仍报告 Runtime。关闭先封闭接收、取消并等待请求，再等待真实线程；线程池 join 在线程中执行并持有关闭任务，超时/清理失败传播，不以清表或 wait=False 伪装释放完成。关闭编排由 Application 统一执行。

## 工具事件路由移除

`UIEventRouter` 与 `abstract/tools/ui_event_router.py` 已删除，Application 拓扑相应由 21 个 System 减为 20 个。工具后处理不再经独立事件路由，而是在结果提交 History 后通过工具实例的 `after_handle(execution)` 直接向前端 Sink 发送事件（如任务进度、剪贴板展示）；发送与取消清理责任仍由所属 Loop 与 FrontendSink 承担。

## LSPManager接入

LSPManager继承AsyncSystem并依赖RuntimeSystem、Sandbox；virtual_awake只保存唯一Sandbox和Runtime主loop，pyright仍按需启动，不从工具线程新建事件循环。旧get_lsp_manager/cleanup_lsp模块入口已删除，工具和文件诊断附加经get_system(ILSPManager)查询；公开业务方法不再传入可由System取得的Sandbox。

启动/替换与最终原生清理由独立operation锁串行化，状态锁不覆盖等待或join。握手与后续响应都由同一stdout reader读取，启动线程通过pending Event有界等待，避免直接readline绕过截止。异步请求的原生Event等待任务单独持有，取消请求的异步等待不取消真实线程。close_admission唤醒现有请求，拒绝新操作；最终关闭在线程中杀进程、等待进程退出、join reader/stderr线程并关闭管道，全部成功才移除句柄。清理失败/超时保留引用并传播，独立原生清理task受实例持有，主loop不阻塞join。最终注销由 Application 逆拓扑统一执行。

关闭使用独立释放动作聚合：原生清理失败或超时仍检查响应等待线程，所有错误最终一起传播；不会因首个清理异常跳过其他已持有工作。文件写入完成后仅将明确的ApplicationStoppingError转换为跳过可选诊断，其他异常继续传播，保留真实写入结果。原生响应线程的异步包装使用shield隔离正常请求取消，直接取消原生包装仍属生命周期失败，不借TaskOwner取消包装冒充原生线程结束。

## BrowserSystem接入

component/browser/system.py 的 BrowserSystem 为依赖RuntimeSystem的AsyncSystem。CDP/Playwright/端点与所有应用自有无头进程仅由该System持有，唤醒不启动可选浏览器；_connection保留纯函数。请求使用TaskOwner，独立断连/原生进程回收任务保留至真实结束，取消异步等待不代表原生结束。只停止已登记无头进程，普通CDP连接仅断开，不停止用户浏览器。多进程句柄不互相覆盖，释放错误汇总传播。Application 关闭先停止在途工具调用，再逆拓扑注销并释放浏览器资源。

## ModalityCapabilitySystem接入

system/modality_capability.py 的 ModalityCapabilitySystem依赖RuntimeSystem与LLMProfileStore，唯一持有探测锁、生成音频/载入视频探针及缓存文件路径；媒体构造、显式Profile引用解析与文本格式化保持无状态函数。导入模块不再读取探针模板或创建共享锁，virtual_awake完成媒体准备，关闭不删除持久化能力缓存。

run_modality_probe/ensure_modality_capability与多模态转发使用TaskOwner.run_request托管完整操作，开始与同模型锁等待后检查Runtime；六路子探针由TaskGroup持有，全部结束/清理后才返回或传播错误，锁与媒体只在实际任务完成后释放。HTTP 400 模态拒绝经模块级 `_is_modality_rejection` 统一判定，只识别客户端归一化的 abstract 层 `LLMAPIStatusError(400)`（openai/anthropic 协议非流式路径由客户端转换抛出、流式回退路径经 `StreamChunk.error_code` 重建），system 层不依赖具体 SDK 异常族；认证/限流/服务端错误继续传播且不写缓存。不同模型探测保存前重新合并最新缓存根，保留其他已完成探测；仍直接交easysave保存ModalityCapability实例。缓存可丢弃的既有读取/保存策略不因System迁移扩大为其他存储策略。

全部有状态缓存/探测/有效Profile解析/提示词查询经get_system(IModalityCapabilitySystem)，关闭刷新只允许只读查询，不触发模型。

## CronRouter接入

CronRouter依赖RuntimeSystem/Sandbox/SubprocessRunner，唯一持有任务、路由、全部Timer、运行中命令记录和原生停止任务。唤醒严格加载并验证原JSON，不启动Timer；activate仅在RUNNING开放。工具/API/会话生命周期统一get_system(ICronRouter)，工具层不再读写任务内部状态。_CronTask与时间解析位于component/cron_tasks.py，JSON字段不变。

接收与Timer登记锁序固定Runtime→Cron，磁盘快照及同路径原子写只在Cron事务锁内串行执行，不在Runtime接收锁内I/O。freeze取消Timer但保留should_schedule和真实线程引用；实际回调完成后也须join确认才移除。运行命令按独立cron前缀登记SubprocessRunner，停止先kill再join，工作线程中完成原生等待；关闭任务自身强引用并免受调用方取消传播，失败汇总，超时保留活资源。

SubprocessRunner登记迟到创建的进程后再次检查Runtime状态，修复全局STOPPING后kill快照遗漏正在创建的Cron进程窗口；该检查在进程锁外，不反转Runtime锁顺序。关闭后的Cron结果只保留执行结局，不唤醒模型。输入持久化闭合已随 S16/S17 完成，最终装配件 Application 统一执行。

## SessionManager接入（S16进行中）

Gateway SessionManager无参构造并继承AsyncSystem，dependencies按计划包含Runtime、Profile/元数据/审批、FrontendSink、工具/事件注册表、Cron、Agentspace、Shell和模态系统。virtual_awake才加载索引和确保随意聊聊索引，不创建Loop或提前取得尚未唤醒的自身；运行入口经get_system(ISessionManager)，不保留Application镜像属性。

输入登记与接收关闭同步，记录状态与严格History保存绑定，主/多Agent共享准备后提交工具结果协议。SessionManager持有退役Loop与交接任务，等待所有可能写入History的回复任务后才串行刷新；反馈关闭交接沿用子会话已分配sequence，不重开普通接收。原任务和原始错误保留；System 最后注销与 60 秒硬截止由 Application/RuntimeSystem 在 P22 统一接通。Gateway 跨连接输入的提前承诺已由 S21 完成（路由内同步登记 + ready 准备任务）。

## GatewaySystem接入（S21完成）

`gateway/system.py::GatewaySystem` 是 FastAPI/uvicorn/socket 与全部路由后台工作的唯一所有者，依赖 RuntimeSystem、ToolDiscoverySystem、SessionManager、SubAgentOrchestrator、DynamicEndpointSystem、FrontendSink、AgentspaceService、ApprovalSystem、LLMProfileStore、SessionMetadataService、CronRouter、ShellManager、Sandbox，按 P1 最后唤醒、首先注销。`gateway/server.py` 仅保留静态 `APIRouter` 与 `build_router_app()` 工厂，模块级 FastAPI 实例、`_agentspace_path`/`_BUILD_HASH` 运行快照、`set_agentspace_path` 与旧 `create_server` 已删除。`gateway/lifecycle.py` 提供输入准入与真实 ready 跟踪；启动由 `_GatewayUvicornServer` 在 startup 成功后置 ready，等待 ready/serve 提前结束/30 秒超时三者竞速，禁用 uvicorn 自身信号安装。USER_MESSAGE 在路由内同步完成目标/字段/Profile 校验并登记输入记录（ready=False），准备任务完成 Profile 就绪、标题与子会话转发后 `mark_ready`；准备任务非取消异常按 RV9 记录应用失败。关闭顺序为 `stop_accepting()`（HTTP 新业务 503、WS 1001）→ `cancel_background_work()` → `stop_server()`，既有输出连接保留到 History 刷新完成；最终注销由 Application 逆拓扑统一执行。

## ToolDiscoverySystem接入

`abstract/tools/discover.py::ToolDiscoverySystem` 依赖已就绪的工具注册表、工具业务 System 及 MCPSystem，按 P1 顺序在 MCPSystem 之后、Gateway 之前唤醒。模块只导出对象声明，导入不创建运行实例。发现器按路径读取/解析/导入，AST 只识别顶层固定名称 `TOOLSET`，唯一已注册模块集合由该 System 持有；遇到退役的 `register_tools`、旧全局注册表导入、`ui_event_router` 导入、导入期注册或任何读取/语法/导入/注册错误直接失败，缺失内置目录同样失败，可选 custom_tools 不存在才跳过。

复用已缓存模块仍以 `register_toolset(toolset, merge=True)` 显式注册对象声明，不重新加载或改写 sys.modules。发现后注册 MCP 管理工具（`MCP_TOOL_MODULE`）和固定 `BaseToolSet` 元数据，远程连接归 MCPSystem；最终注销仅释放发现记录和本次加入的宿主导入路径，注册表条目归原 ToolRegistry。Application 完整注册已由 P22 接通；构造发现器不执行扫描或调用 Application.current()。

## 会话变量池

`AgentspaceService.session_variables` 持有唯一无缓存 `SessionVariableService` 叶服务，使用已有 Sandbox，不增加 AsyncSystem、线程、watcher或后台复制任务。逻辑根为 `ws:sessions/<主会话ID>/variables/`，与聊天 History 的 workspace/sessions 根不同；普通子Agent使用父主会话目录，临时Agent不扩大现有工具授权。

JSON文件保存单个数字/字符串，同级完整名称追加 `.meta`。业务键为 label、description、min、max、integer、percent、display；布尔只接受小写true/false，百分比只把显示值乘100。无效值保留原文、配置错误与constraint分别报告，不自动裁剪或改写。`read_pool` 同时供safe工具和REST使用，文件为唯一真相，scan_complete=false明确表示不受支持子树未读取。`has_visible_content(session_id)`复用同一受预算扫描但不构造完整响应，用于会话 Tab 能力探测：任何变量值文件、`.json.meta`孤立元数据、节点/顶层问题或不完整扫描均视为可展示内容；普通无问题的 `foo.meta` 和空目录不启用 Tab。扫描异常补齐变量根路径后沿既有错误边界传播，不返回默认空结果。

读取预算：512变量、4096节点、16层、64KiB单文件、512KiB逻辑内容、1MiB响应与2秒软截止。继承全部来源合计逻辑512KiB，额外复核512KiB，实际读1MiB；超预算明确拒绝，不静默截断。根与子树拒绝符号链接/reparse point，Windows显式检查属性；Sandbox是应用级边界，不是OS ACL。

`capture_inheritance` 捕获全部普通文件原bytes及空目录并复核内容版本；坏JSON/meta仍原bytes继承，无法完整读取则拒绝。`install_inheritance` 独占创建目标，不合并覆盖，初始化scope失败仅按目录身份回收本次目标；原失败与必要清理失败以异常组保留，LifecycleFailure不降级。复制材料及身份均非持久化模型，无easysave格式迁移。

直接Write不是原子覆盖，读整池不是跨文件事务，文件锁不互斥多个Agent。主Agent统一结算，重新生成/删除消息不回滚；旧子Agent旋转后仍写旧父目录，捕获后的变化不自动同步；正常永久删除会话不清理变量文件。

## 会话文件操作聚合叶服务

`system/session_file_changes.py::SessionFileChangeStore`由AgentspaceService.virtual_awake构造，经只读file_changes属性取得；没有额外AsyncSystem、后台Owner、watcher、原生资源或模块级单例，20个System的装配与关闭拓扑不变。ToolRegistry在逆拓扑中早于AgentspaceService释放，调用级记录器持有必要Store引用，迟到收尾不重查已经注销的System。

每会话RLock保护严格惰性加载、候选聚合、easysave必要保存与缓存发布。根位于RuntimeContext.workspace/sessions/<主会话ID>/file_changes.es，v1 key，Data/Entry/Actor使用typeref稳定映射，直接保存BaseModel；UTC时间只存毫秒精度+00:00字符串。根revision等于成功目标全局次数；Move两行各加路径次数但只加一次revision，后续操作可分别更新时间/序号。所有计数、键、作者和源/目的关系在业务层显式校验，不使用反射或model_dump降级。

目录仅记显式目标、逻辑路径聚合不读文件正文。无记录GET不创建文件，已有根缺key、损坏、孤立备份拒绝，不自动恢复。缓存根不暴露可变引用给HTTP调用者，分页只限制传输行数，底层仍整体快照保存。必要记录保存失败使应用失败关闭；HTTP只读错误不主动报告全应用失败，文件与记录/History不构成跨文件事务。

block_session与相同会话锁同步，在拆除运行时前封闭记录，锁争用5秒为删除业务409；unblock/forget是有界必要收尾。forget清缓存但保留进程内锁与封闭标记，避免旧线程获得另一把锁或重建会话目录；内存随访问/删除会话数增长，不扫描会话目录。归档保留，分支/合并/旋转不继承；旧子Agent按原父会话归属。

Sandbox.copy/copy_folder/move新增真实目的ResolvedPath返回，消费shutil返回值并沿本次逻辑目的拼接子路径；不重新解析后来变化的动态映射，不改变原磁盘语义或权限。`ensure_parent_directories(logical)`在Write/Copy/Move需要时创建缺失父目录并返回本次新建的逻辑目录，文件工具在目标成功后逐条记录，已存在父目录不重复计数。ToolExecution只新增调用级取消事实，不以外层等待结束冒充线程退出。

## 文件修改聚合状态

`SessionFileChangeEntry.display_state`与`created_by_session`保存当前逻辑路径生命周期：首次成功创建/复制目的/移动目的为`created`；对created路径的修改保持created；删除已有路径为`deleted`且可见为红色，删除会话新增路径为deleted但由当前Tab隐藏；删除后同路径再次创建、复制目的或移动目的为`modified`。Store的分页和摘要只投影可见条目（文件或目录），合成父目录由前端树构造，不写入目录条目。`operation_count`仍来自全部成功目标操作，隐藏删除不丢失。

Move在一次revision中更新源和目的两行，源为deleted、目的按历史决定created/modified；Copy只更新目的。加载校验允许deleted条目存在，删除后重建不能把历史路径误判为首次新增。前端完整树只在同一revision的全部可见分页取得后替换，半页结果不渲染。

## 会话离线导出叶服务

`system/session_export.py::SessionExportService`由GatewaySystem唯一持有，经`IRuntimeSystem`、`ISessionManager`、`ISandbox`接口注入运行时依赖，并接收既有SessionVisualResourceService；无长期导出job或History缓存，不新增System。重操作1路、资源读取2路，达到容量立即429；独立线程池的工作在真实结束后释放容量，取消不会让线程失去所有权，Gateway退出关闭线程池。

capture使用Loop公开分段隔离输入，线程读取严格metrics并计算完整摘要/展示投影；保存原metrics字节状态以区分缺失和空文件，损坏明确拒绝。视觉签名覆盖源meta原字节、源目录身份、有效逻辑目标及入口实际内容/身份；不把stage旧version当成全部素材签名，也不枚举打包整个有效目录。configured/availability区分未配置、入口缺失、配置损坏和权限问题。

资源只按明确逻辑文件或已有字体规则读取，原路径组件及最终映射拒绝symlink/junction/reparse；读取前后身份/mtime/ctime/size和SHA参与proof。Windows下路径stat/lstat与文件描述符fstat的字段可能具有不同表示/精度，禁止直接交叉全量比较；metrics和资源共用同一校验入口，分别比较同来源的路径前后状态、同句柄前后状态及实际读取字节数，非Windows平台另检查打开身份。原路径映射/reparse和最终SHA/proof复核保持，检查失败以WARNING记录kind、脱敏source_ref、reason和数值签名，不输出物理路径或内容。已保存文件在verify变化则整体409，不伪装缺媒体成功；明确初始缺失/权限拒绝/单文件超限才资源级降级。读取、编码和复核均有独立字节/时间预算，最终guard与会话存在性/空闲状态复检，不宣称跨文件原子事务。

`util/local_fonts.py`的`resolve_local_font`和MIME函数复用既有在线规则，strict_reparse仅用于导出，不改变在线字体权限口径。新增纯字段类型按消息依赖位于puretype/puretype_after，带校验器的资源读取结果留在业务模块；不加入easysave/typeref，不写workspace、不调用模型。源码已接入，未运行构建、校验或应用。

## 验证约束

本次迁移未由开发助手AI运行测试、类型检查、Lint、构建或应用。只做源文件读取和定向差异审阅；正式运行验证由用户在完整迁移完成后执行。

## System 接口槽位约定（2026-10-20）

本包的 Runtime、SubprocessRunner、Sandbox、Shell、Agentspace、Profile、元数据、LSP 和多模态等 System 均继承对应 `interface/` 接口。它们的 `dependencies` 和内部 `get_system()` 查询只使用接口类型；Application 负责将实现实例注册到接口槽位。资源所有权、virtual lifecycle 和关闭错误传播仍由具体实现负责，接口不声明这些 framework 生命周期成员。

