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
