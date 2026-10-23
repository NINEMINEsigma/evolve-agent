# Decision Log — 外部资源清理超时降级

**Date**: 2026-10-22
**Topic**: 外部资源清理超时不触发全应用崩溃
**Depth**: light（四轮逐项质询）
**Status**: complete（需求边界已确认；实现设计未开始）
**Task**: `.tasks/2026-10-22_2_external-resource-cleanup-timeout.md`

本文件是本次RESEARCH的决策记录，采用追加修订，不覆盖已确认决策；不是实施授权。

## Decisions

### D1: 降级范围
**Status**: [RESOLVED]
**Question**: 这次“清理超时只记录日志、不触发全应用崩溃”的规则，要覆盖哪一范围？
**Answer**: 统一覆盖外部资源清理超时：子进程、Shell、浏览器、MCP、语言服务和文件监听等；持久化失败与内部逻辑错误不降级。
**Trade-off accepted**: 跨模块研究与后续修改范围扩大，但降级限定于清理阶段超时，不吞掉普通业务错误或全部生命周期异常。
**Local evidence**: SubprocessRunner、ShellManager、BrowserSystem、LSPManager、MCP以及AgentspaceWatcher存在清理超时进入LifecycleFailure/record_failure或关闭异常组的路径。
**External evidence**: Python官方asyncio子进程文档说明PIPE消费不足可能阻塞Process.wait；https://docs.python.org/3/library/asyncio-subprocess.html 。这说明清理等待超时并非业务或数据状态必然损坏的证据，不代表所有超时都可恢复。
**Terms defined**: 未引入新项目术语。
**Downstream impact**: 后续分类必须区分清理期限、业务请求期限、必要保存失败与内部约定破坏；混合异常保留非降级部分。

### D2: 超时后的资源处理
**Status**: [RESOLVED]
**Question**: 清理超时后，如果进程、线程或连接仍未确认退出，你希望应用如何处理？
**Answer**: 停用受影响的旧实例，保留引用并跟踪后续收尾；其他功能继续，只拒绝有资源冲突的操作。
**Trade-off accepted**: 接受暂时残留资源及局部操作受限，不牺牲全应用可用性；不承诺仅靠内部停用状态就能终止外部命令的副作用。
**Local evidence**: 多个模块已有shield和资源登记；部分失败清理任务被缓存，保留引用本身不保证下一次清理会继续。共享浏览器、语言服务及MCP连接存在替换时的资源冲突边界。
**External evidence**: 同D1；进程退出与管道收尾需分别确认。未运行底层故障复现。
**Terms defined**: 无。
**Downstream impact**: 需要明确旧实例身份、后续收尾责任、终局移除、冲突拒绝及迟到回调边界；未授权无限重试或重放业务操作。

### D3: 保留最终退出保护
**Status**: [RESOLVED]
**Question**: 应用已经进入关闭流程后，60秒仍无法结束时，是否保留当前的强制失败退出保护？
**Answer**: 保留60秒最终退出保护；局部清理超时降级，但整个关闭流程卡死超时仍强制失败退出。
**Trade-off accepted**: 运行中不因局部清理超时主动关闭；用户已经要求退出后若全流程卡死，仍可能以失败码强制结束，而非保证全部情况优雅退出。
**Local evidence**: RuntimeSystem.arm_shutdown_deadline使用Timer调用os._exit(EXIT_FAILURE)；__main__在asyncio.run及其线程池收尾后解除保护。
**External evidence**: 未为此决策另行查询外部资料；以项目现有退出协议为依据。
**Terms defined**: 无。
**Downstream impact**: 不能通过提前解除保护或将强制退出改成成功码实现降级；正常完成关闭时，已降级的资源超时不单独改写原退出原因。

### D4: 显式停止操作准确反馈
**Status**: [RESOLVED]
**Question**: 清理超时是否需要在显式StopShell、BrowserClose等操作的返回结果中体现？
**Answer**: 自动收尾只记录日志；显式停止操作返回准确的未完成状态或警告，原业务错误照常返回，不新增弹窗。
**Trade-off accepted**: 调用方可能收到局部未完成状态，但应用和其他会话继续；不能为了保持成功返回而谎报资源已经释放。
**Local evidence**: BrowserClose现有成功结果包含closed=True和cdp_disconnected=True；ShellInfo包含running/exit_code等状态但尚无清理完成字段。通用工具分发区分普通错误和生命周期异常。
**External evidence**: 未另行查询；来自当前接口语义。
**Terms defined**: 无。
**Downstream impact**: 具体结果字段与调用方兼容性在PLAN决定；原Grep错误、业务失败和取消语义不被附带清理警告覆盖。

## Risk Register

| ID | Risk | Severity | Mitigation / 已确认约束 | Owner |
|---|---|---|---|---|
| R1 | 资源层降级后被TaskOwner、done callback或关闭汇总再次升级 | high | 后续逐条核实完整传播链及混合异常，不只改一个catch | 后续实施者 |
| R2 | 吞掉持久化失败、内部错误或尚未停止的业务任务 | high | 只认明确外部资源清理超时，不全局屏蔽LifecycleFailure/TimeoutError | 后续实施者 |
| R3 | 旧资源被错误复用或迟到回调破坏新实例 | high | 保留身份与所有权，只拒绝冲突操作 | 后续实施者 |
| R4 | 残留线程、进程、句柄及日志持续累积 | high | 后续设计有限主动收尾与终局观察，避免无界重试 | 后续实施者 |
| R5 | 底层线程卡死导致最终无法退出 | high | 用户明确保留60秒最终失败退出保护 | 用户/后续实施者 |
| R6 | 误杀非应用持有的进程 | high | 终止仅限已明确持有的资源；未知端口占用必须报告 | 后续实施者 |
| R7 | 只改返回路径造成虚假释放成功 | medium | 显式停止准确反馈未完成状态；自动收尾记录真实残留 | 后续实施者 |

## Terminology Updates
未新增项目术语，未修改DEV-glossary.md或创建CONTEXT.md。

## ADRs Created
未创建ADR。本任务文件与本决策日志记录当前边界，不另建架构决策文件。

## Open Questions (Deferred)
用户层面的范围、资源残留处理、最终退出保护和调用可见性均已解决。以下属于后续技术设计，不是假定已经批准的方案：
- 超时分类如何贯穿异常组、取消包装、回调及历史失败汇总——进入PLAN时明确。
- 各资源的继续收尾机制、预算、诊断节流和状态冲突处理——进入PLAN时明确。
- 现有工具/API如何表达清理未完成且不伪造成功——进入PLAN时明确。
- 其他尚未穷尽的外部资源释放入口及相应文档——进入PLAN前后补齐定向调查。

## Handoff Notes
Recommended next step: 等待用户授权进入RIPER-5 PLAN；不自动切换。
Key context for implementer: 当前Shell源码已有部分降级且停止顺序已调整，不按旧文档覆盖现有修改。公共TaskOwner与Application存在重复升级风险。Grep超长行问题不属于此次自动实施范围。未运行校验、构建、故障复现或应用；没有修改正式源码、workspace或third。

---

# Decision Log — 用户单次响应强制调用工具

**Date**: 2026-10-23
**Topic**: 用户发送/重新生成时一次性选择首次模型响应必须调用任意至少一个工具
**Depth**: medium（八项决策，包含选择修正、场景与事前失效分析）
**Status**: complete（需求研究完成；未进入实施设计）
**Task**: `.tasks/2026-10-23_1_require-tool-on-user-response.md`

以下 D1–D8 仅属于本任务，前一任务的同名编号和全部记录保持原样。当前时间/用户曾通过 Get-Date 与 whoami 取得：2026-10-23_16:10:08，desktop-bmj4oud\liubai。

## Decisions

### D1: 首次响应产生调用
**Status**: [RESOLVED]
**Question**: 强制保证首次响应发出工具调用，还是工具执行成功，或每次响应都调用？
**Answer**: 用户选择首次响应至少发出一个工具调用；后续恢复自主选择，不要求执行成功。
**Trade-off accepted**: 工具仍可能被审批拒绝或执行失败，不改变权限和审批，不承诺业务成功。
**Local evidence**: ParentAgentLoop._run_tool_loop 当前无工具调用即保存文字并结束；有调用则执行并继续请求。
**External evidence**: 官方文档访问受限，未获得有效外部核验。
**Terms defined**: 使用用户原称“强制调用工具”，未新增正式术语。
**Downstream impact**: 必须区分首次响应与工具结果后的后续请求。

### D2: 全部主会话
**Status**: [RESOLVED]
**Question**: 选项覆盖哪些会话？
**Answer**: 全部主会话，包含普通模式、随意聊聊及多Agent模式；直接发送子会话不支持。
**Trade-off accepted**: 本次不扩展独立子会话、临时Agent和辅助模型。
**Local evidence**: useWebSocket.send 与 MessageRouter 支持主/子会话多目标；子会话独立转发。
**External evidence**: 未另行查询；这是项目产品范围。
**Terms defined**: 无。
**Downstream impact**: 混合发送不得向子会话泄露此约束。

### D3: 每个用户指定响应者
**Status**: [RESOLVED]
**Question**: 多Agent模式强制哪些参与Agent？
**Answer**: 最初选择 first_only；用户随后明确修正：“不对, 还是按指定响应的每一个”。最终为用户本次指定响应的每个参与Agent各自首次响应强制；工具后续请求及后续级联/自动回调不强制。first_only 作废。
**Trade-off accepted**: 一条用户消息可能触发多个工具调用，而不是全会话只需一个。
**Local evidence**: MultiAgentLoop._cascade 混合初始队列、动态响应队列和自动回调，每次通过 MultiAgentWorker 运行独立工具循环。
**External evidence**: 未另行查询。
**Terms defined**: 无。
**Downstream impact**: 不能用整个级联 step==0 或每个 Worker 无条件开启来表达需求。

### D4: 发送后自动关闭
**Status**: [RESOLVED]
**Question**: 发送后自动关闭还是保留直到手动关闭？
**Answer**: “发送后自动关闭”。默认关闭，仅当前符合条件的操作消费；具体时点见 D8。
**Trade-off accepted**: 下次需要强制时重新开启。
**Local evidence**: InputBar 发送按钮和 RichInput 共用 onSend，useWebSocket.send 统一构造请求。
**External evidence**: 未另行查询。
**Terms defined**: 无。
**Downstream impact**: 请求捕获值与前端复位后的值必须分离。

### D5: 依赖 tool_choice，不做违约检测
**Status**: [RESOLVED]
**Question**: 已开启但模型返回文字、未调用工具时怎样处理？
**Answer**: 用户原文：“认定模型提供商能指定tool_choice的行为时一定有效, 否则其请求肯定报错, 忽略调这种情况”。不增加返回值检查、补救提示或专门重试；服务报错沿原处理。
**Trade-off accepted**: 不为服务静默忽略参数提供应用层保障；这是需求前提，并非已验证事实。
**Local evidence**: BaseLLMClient 尚无 tool_choice 参数；EmptyResponseRetryClient 仅处理无正文且无调用的空响应。
**External evidence**: OpenAI 官方页 HTTP 403；Anthropic 官方页地区受限；不以失败访问支持服务兼容性结论。
**Terms defined**: tool_choice 为用户使用的 API 参数名。
**Downstream impact**: 保持现有网络/空响应策略，不增加功能专用重试层。

### D6: 重新生成使用当前开关，resume 不消费
**Status**: [RESOLVED]
**Question**: 重新生成是否继承强制要求？
**Answer**: 用户原文：“开启强制调用工具时, 重新生成需要强制调用, 然后前端还是一样使用后就关闭, resume继续不生效也不消费这个状态. 工具链过程中也不生效和消费强制调用工具的指定”。重新生成使用当前选择，不继承历史旧选择；resume 不使用、不关闭。
**Trade-off accepted**: 历史消息不是开关真相源，不需要为此持久化用户消息字段。
**Local evidence**: Gateway regenerate 截断后调用 process_message；ParentAgentLoop.resume 也复用工具循环，但语义不同。
**External evidence**: 未另行查询。
**Terms defined**: 无。
**Downstream impact**: 前端发送和重新生成共享单次选择，恢复与自动继续必须隔离。

### D7: 工具链期间补充发送保留开关
**Status**: [RESOLVED]
**Question**: Agent 正在执行工具时，开启开关再发送补充消息，应怎样处理？
**Answer**: 用户选择 keep_for_next_idle：补充消息正常发送，不携带强制；开关保持开启，留给之后空闲时发送或重新生成。
**Trade-off accepted**: 不强制把这条补充消息独立排队响应；即使稍后才消费也不追溯附加要求。
**Local evidence**: ToolInputReservation 使用 InputDeliveryBuffer.reserve_pending 将消息嵌入工具结果；当前源码允许合批和链中注入，与部分文档逐条处理描述不一致。
**External evidence**: 未另行查询。
**Terms defined**: 无。
**Downstream impact**: 后续设计需覆盖请求归属与活动状态竞态，不附带重构队列。

### D8: 请求发出即消费
**Status**: [RESOLVED]
**Question**: 符合条件的请求发出时关闭，还是等待服务端确认接受后关闭？
**Answer**: 用户选择 on_dispatch：本地前置检查通过且发出请求即关闭；本地未发出保留；后续服务拒绝、网络或模型错误不自动恢复。
**Trade-off accepted**: 不等待服务端确认；请求后来被拒绝也已消费。旧请求终态不得清除等待期间用户新开启的状态。
**Local evidence**: useWebSocket.send 有本地前置检查；regenerateResponse 有请求身份/截断确认边界，不能用旧请求完成回调无条件复位。
**External evidence**: 未另行查询。
**Terms defined**: 无。
**Downstream impact**: 消费限定于正确请求发出边界，不放在点击入口或异步终态。

## Risk Register

| ID | Risk | Severity | Mitigation / 约束 | Owner |
|---|---|---|---|---|
| R1 | 链中注入或批次合并误用强制标志 | high | 后续设计以实际源码为准；不允许工具结果后的请求消费前端状态 | 后续设计者 |
| R2 | 多Agent后续级联重复强制或漏掉某个初始参与者 | high | 按用户指定响应者的首次模型请求区分，不按整个级联首步判断 | 后续设计者 |
| R3 | 前端旧响应清掉用户新开启的开关 | medium | 发出请求时消费，旧请求终态不修改新选择 | 后续设计者 |
| R4 | 公共接口、重试装饰器或派生客户端漏传参数 | high | 后续核实全部对应接口和覆写；不在共享客户端保存单次可变标志 | 后续设计者 |
| R5 | 兼容服务静默忽略 tool_choice | medium | 用户明确接受服务契约前提；本功能不增加检测/补救 | 用户 |
| R6 | 前后端活动状态有延迟 | medium | D8 不等待确认；后续仍需保护首次响应与工具链续轮边界 | 后续设计者 |

## Terminology Updates
未新增正式术语，未修改 DEV-glossary.md，未创建 CONTEXT.md。

## ADRs Created
未创建；本任务文件与追加决策日志足以保留需求和权衡。

## Open Questions (Deferred)
需求核心决策已解决。以下技术细节交给用户授权后的 PLAN，不是已批准实施方案：开关具体位置及非持久会话隔离、前后端活动竞态、合批记录的约束归属、多Agent初始响应者与动态调度区分、客户端原生参数映射及内部续传边界。若技术研究揭示新的产品取舍，再单项请用户确认。

## Handoff Notes
Recommended next step: 等待用户明确授权进入 RIPER-5 PLAN，不自动切换。
Key context for implementer: 使用当前前端开关，不保存历史旧选择；发送/重新生成发出即消费，resume 与链中补充发送不消费。实际队列仍有合批和链中注入，不能依照文档将其假设为严格逐条。未运行测试、校验、构建或应用，未修改正式源码、workspace 或 third。

