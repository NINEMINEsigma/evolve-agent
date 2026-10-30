# component/ — 审批、MCP、Cron 与动态端点服务

`component/` 当前保留审批系统、MCP 管理入口、Cron 路由与任务模型、动态端点服务。五个内置工具子包已整体迁至 [`buildin_tools/`](../buildin_tools/DEV-README.md)，工具发现、工具契约、Shell、文件操作、Read、多模态、LSP、会话视觉资源及 BrowserSystem 的约定统一见该文档。

目录目标是承载架构 Component 相关实现，但本轮只迁五包，仍保留审批、Cron、动态端点等历史服务，尚未完成最终 Component 专用整理。本轮不搬迁 `ActivityLoggerComponent`，也不扩大为其他目录职责重构。

---

## 文件结构

```
component/
├── __init__.py              ← 包入口
├── approval/                ← 审批系统（目录化）
│   ├── __init__.py           ← 公共接口重新导出
│   ├── backend.py            ← ApprovalBackend 抽象 + Local/Remote 实现
│   ├── core.py               ← request_user_confirm / ask_agent_reason
│   ├── executor.py           ← execute_with_approval 统一执行器
│   ├── handsfree.py          ← 审批模式公共入口 + LLM 审批流程
│   ├── mode_store.py         ← Application 持有的会话级审批模式缓存与持久化服务
│   ├── allowlist.py          ← 工具 allowlist 持久化
│   └── policy.py             ← 审批策略（needs_approval + 预设策略常量）
├── mcp_tools.py              ← MCP 管理工具独立入口
├── cron_router.py            ← Cron 任务路由
├── cron_tasks.py             ← Cron 任务模型与时间解析
└── dynamic_endpoints.py      ← 动态端点 System
```

工具的五包结构、50 个 `TOOLSET` 声明模块、发现顺序及共享模块边界见 [`buildin_tools/DEV-README.md`](../buildin_tools/DEV-README.md)。`component.mcp_tools` 保持独立显式注册，不随五包迁移；旧五包无兼容代理。运行时合并复制的残留风险、停机完整部署与定向处理边界见该文档的[包迁移与完整部署边界](../buildin_tools/DEV-README.md#包迁移与完整部署边界)，开发助手AI不操作运行时副本。

---

## 异常定义包（2026-10-30）

本包审批、MCP、Cron 与动态端点业务使用的公共自定义异常统一 `from entity.error import X`；全部 origin仓库自定义异常（含内部控制信号）只在 [异常定义包](../entity/error/DEV-README.md) 按职责子模块定义，并由 `__init__.py` 显式导出，不散放在本包业务模块。标准库/第三方异常仍从原来源导入。私有 `_SourceUnavailable` 仅从 `entity.error.session_export` 显式导入，不公开。

异常继续继承原 Exception 家族，不强行改 BaseModel，不改变审批拒绝、任务执行、取消/停止、必要持久化失败、资源清理与快速失败策略。`SessionExportError` 及全部公共子类仍为唯一定义的同一族；本包不建立重复类型或旧路径兼容入口。纯转发 `system/lifecycle_errors.py` 已删除，生命周期分类函数仍留原业务职责。

异常不加入 easysave/typeref，存储 key 未变，System装配和资源所有权不变。本次仅源码迁移与文档同步，未运行测试、实际导入、构建、校验或应用；用户须停机完整部署新包与全部调用方并重启，注意合并复制残留，开发助手AI不操作 workspace。

## 审批系统

### `component/approval/`（目录化重构）

原 `component/approval.py` 单文件已重构为目录，按职责拆分为 8 个子模块。`__init__.py` 重新导出所有公共接口，保持 `from component.approval import Xxx` 旧路径兼容。

#### `approval/backend.py` — 审批后端

- `ApprovalBackend`（ABC）：脱手模式审批后端抽象，声明异步 `chat()` 和同步 `is_available()` 接口。
- `ProfileApprovalBackend`：通过 `LLMProfileStore` 读取 `LLMProfileData.approval_profile` 根对象引用，连接外部管理的 LLM Profile 端点。使用五字段连接指纹缓存客户端，Profile 内容变更时自动重建。
- 不再有本地/远程双后端、`FailedApprovalBackend`、工厂函数或本地检测函数。

审批进程生命周期由 `component/approval/system.py::ApprovalSystem`（AsyncSystem）统一管理，依赖 RuntimeSystem、LLMProfileStore。`mode_store`、`backend_manager`、`allowlist` 是它唯一持有的叶对象；原 ApprovalBackendManager 已移至 `component/approval/manager.py`，不再定义在 Application 中。后端 get_backend/get_state/invalidate 的业务语义保持。

模型审批通过 `ApprovalSystem.chat()` 的 TaskOwner.run_request 登记，普通模型调用失败继续按原审批拒绝路径处理，用户取消不升级为进程失败；生命周期失败不能被拒绝结果吞掉。关闭先停止接收并取消等待审批请求，确认请求实际结束后再清除后端缓存引用，不停止用户外部模型服务。共享 Profile 查询与缓存更新使用 LLMProfileStore.locked()。

#### `approval/core.py` — 统一审批入口

- `request_user_confirm(session_id, tool_name, args, ...) -> ApprovalResult`：统一审批入口，自动分流脱手模式与手动模式。
- `build_denied_tool_result(approval) -> dict`：按拒绝来源（model/user/parent_agent/system）构建统一的工具拒绝结果。

#### `approval/executor.py` — 工具审批执行器

- `execute_with_approval(tool_name, args, session_id, sink, ...) -> ApprovalOutcome`：封装 dangerous/write 判断、白名单检查、脱手/手动两种审批模式、拒绝结果构建和 `allow_always` 加白名单。

#### `approval/handsfree.py` — 审批模式公共入口

- `set_approval_mode(session_id, mode: ApprovalMode) -> ApprovalMode`：设置会话审批模式（MANUAL/HANDSFREE/YOLO）；用户当前请求新开 HANDSFREE 且审批 Profile不可用时仍回退 MANUAL，实际模式随后交给 `ApprovalModeStore` 缓存并尽力持久化。
- `get_approval_mode(session_id) -> ApprovalMode`：委托 `ApprovalModeStore` 返回内存值或从会话文件惰性恢复；恢复 HANDSFREE 时不检查审批 Profile可用性。
- `disable_all_non_manual_modes() -> list[str]`：保留的显式兼容管理入口，委托 Store遍历现存会话并尽力写回 MANUAL；审批 Profile生命周期不调用该函数。
- `is_handsfree_available() -> bool`：检查审批 Profile 是否已配置。
- `_handsfree_confirm()`：核心流程，通过审批 Profile 模型评估工具调用风险。审批请求包含工具的参数 schema（使模型能区分必填与可选参数）、实际参数值和 reason（补充说明）。审批输出使用普通文本决策标记（`[ALLOW]`/`[APPROVE]`/`[DENY]`/`[REJECT]`/`[拒绝]`/`[否决]`），不使用 JSON。审批 system prompt（`templates/approval/system_prompt.md`）明确审批模型只见单次调用、不读用户消息；schema description 是写给调用方 Agent 的指令而非审批判据；审批模型只判断该次调用本身是否安全，不检查前置条件/用户同意/流程合规，本质只读的操作（含 `ssh <host> <只读命令>`）必须放行。
- 兼容包装：`set_handsfree_mode()`/`is_handsfree_mode()`/`disable_all_handsfree_modes()` 保留，分别委托到统一入口。

#### `approval/mode_store.py` — 会话级审批模式存储

- `ApprovalModeStore` 由 Application唯一持有，物理根为 sessions 目录；每个主会话使用 `approval_mode.es`，文件内逻辑根 key 为 `v1`，根对象为直接保存的 `SessionApprovalModeState`。
- `get_mode()` 首次访问时通过 `load(v1, make_config(path), SessionApprovalModeState, ignore_missing_fields=True)` 惰性重建真实 BaseModel实例；旧会话缺文件静默使用手动模式，缺 key、损坏、类型 token错误、根类型或 `mode`类型错误记录 warning 后回退手动模式。
- `set_mode()` 在业务 `RLock` 内先更新内存，再把 `SessionApprovalModeState`实例直接传给 easysave `save()`，禁止 `.model_dump()`降级。easysave负责路径锁、前置 `.bak`、同目录临时文件、`fsync`和原子替换；任何写入异常只记录会话 ID、目标模式、路径和堆栈，不回滚内存、不自动处理备份、不向前端报错。
- `initialize_session()` 只接受新会话 ID并初始化手动模式；普通新会话、单源分支、多父合并及首次创建“随意聊聊”均使用该入口。上下文超限产生自动延续后，由 `inherit_session()` 显式继承来源主会话的当前模式；该继承发生在新会话创建后、来源会话归档前。
- `forget_session()` 只清理缓存；`approval_mode.es` 随永久删除的会话目录统一清理。归档不删除状态。
- `reset_all_non_manual_modes()` 仅为兼容显式调用保留，扫描 sessions 直接子目录并复用同一会话 ID校验与尽力写入规则；sessions 根不存在时不调用 `save()`，避免创建孤立目录。
- `entity/typeref.py` 为持久化根登记 `v1::SessionApprovalModeState` stable type token；ES key版本与类型 token版本分别使用独立常量，职责不得混用。
- 审批 Profile清空、删除或配置无效只更新 Profile状态和审批后端缓存，不改写任何会话模式。已恢复的脱手模式在实际审批后端不可用时按既有系统拒绝路径报错；YOLO不依赖审批 Profile。

#### `approval/allowlist.py` — 工具白名单

白名单路径及RLock由 `ApprovalSystem.allowlist` 的唯一 `ToolAllowlistStore` 持有；模块中只保留无状态格式化和委托业务入口，没有独立锁或配置单例。原JSON格式与读取/尽力保存规则保持，不改变既有授权语义。

- `is_allowed(tool_name, args)` / `add_allowed(tool_name, args)`：按工具名与规范化参数精确匹配；排除键集合为 `entity/constant/tools.py::TOOL_INTERNAL_ARG_KEYS`（`_session_id`、`_pre_approved`、`_approval_action`）加 `reason`，并非对该工具所有参数组合授权。主会话 critical 在手动/脱手模式不使用白名单。

#### `approval/policy.py` — 审批策略

- `needs_approval(policy, danger_level, approval_mode: ApprovalMode) -> bool`：根据策略和审批模式判断工具是否需要审批。
- `MAIN_SESSION_POLICY`：主会话策略（手动模式仅 dangerous+critical 需审批，脱手模式 write+dangerous+critical 需审批）。
- `SUB_SESSION_POLICY`：子会话策略（write+dangerous+critical 在两种模式下均需审批）。
- `ApprovalPolicy` 数据类定义在 `entity/puretype/`（`approval` 子模块）。

### 主会话审批流程

1. `ToolExecutor.execute()` 调用 `execute_with_approval()`；普通模式、随意聊聊及多Agent模式中的所有参与Agent均走此流程。
2. YOLO 首先放行所有危险等级，包括 critical；免审批不绕过工具可用范围、沙盒权限或参数校验。
3. 其余模式按 `MAIN_SESSION_POLICY` 选择阈值：safe 始终直接执行，write 在手动模式也直接执行，不弹审批弹窗。
4. 需要审批的非 critical 调用若命中工具名和参数白名单则直接放行；critical 跳过白名单。
5. 剩余调用分流：手动模式 dangerous/critical 由用户弹窗审批；脱手模式 write/dangerous 由审批模型处理，critical 仍由用户弹窗审批。
6. 允许后继续执行；拒绝才返回拒绝工具结果。仅手动模式非 critical 的 `allow_always` 写入白名单。

固定说明分别位于 `templates/base.txt`（主Agent）、`templates/multiagent/multi_agent_system_prompt.txt`（全部多Agent参与者）和 `templates/subagent/subagent_system.txt`（普通子会话）。普通子会话使用不同审批出口，详见 [`subagent/DEV-README.md`](../subagent/DEV-README.md)；临时Agent保持无系统提示词和 safe-only 权限。

---

## MCP 桥接

### `component/mcp_tools.py`

- 以 `MCPRefreshTool` 与顶层 `TOOLSET = BaseToolSet(name="mcp", tools=(MCPRefreshTool(),))` 声明安全的 `MCPRefresh` 异步工具；导入模块不创建连接、不安装回调、不持有 MCP 状态。
- `MCPSystem` 的配置和 Core 边界已建立，远程工具沿用同一 `ToolRegistry`；运行期刷新保留新增/移除结果。OAuth、stdio 进程、连接请求和失败清理均经独立静态复核确认闭合；初始连接失败清理部分成功连接后传播。
- MCP 连接和资源释放的目标所有者为 `MCPSystem`/`MCPCore`；本模块和 `main.py` 已删除重复清理。

MCP 配置示例（`workspace/mcp_config.json`）：

```json
{
  "time": {"command": "uvx", "args": ["mcp-server-time"]},
  "remote": {"url": "http://localhost:8000/mcp", "headers": {}}
}
```

---

## Cron 路由

### `component/cron_router.py`

- `CronRouter` 已改为依赖 RuntimeSystem、Sandbox、SubprocessRunner 的 AsyncSystem，经 `get_system(ICronRouter)` 访问。`_CronTask` 与原时间解析迁至 `component/cron_tasks.py`；工具层只解析参数、调用公开 `schedule_task/reschedule_task/list/trigger/cancel` 方法并适配结果，不读取注册表或调用私有调度/持久化。
- `virtual_awake` 严格加载原 JSON 并校验身份/调度；缺文件可初始化，已有文件损坏或任务非法直接失败。此阶段不安排 Timer；全应用 RUNNING 后由 `activate` 开放调度。
- Timer 直接执行单次命令，所有真实 Timer（含已取消尚未退出）保留在实例集合中，只有 join/实际结束确认后移除。回调登记、立即触发与冻结受接收边界和实例锁协调；已被替换/取消的 Timer 不能执行另一轮。任务与运行中命令分别登记，删除会话或取消任务不会丢失尚在执行的进程所有权。
- 命令统一通过 SubprocessRunner 执行，使用独立 `CRON_PROCESS_SESSION_PREFIX` 键；关闭先冻结和终止命令，再在线程中 join 全部 Timer。期限内未结束保留资源、错误汇总传播；不以清空集合宣告成功，主事件循环不阻塞 join。
- 全局冻结不修改持久 `should_schedule`；已实际执行的一次性任务才提交计数/结束状态。JSON 快照及原子写全过程使用同一锁，持久化失败报告生命周期失败；会话迁移在同一锁内更新所属会话，继续持有正在运行的任务。关闭后的迟到输出仅保留执行结局/日志，不向模型投递新工作。
- 结果仍经主会话队列或子会话 Inbox 投递；输入投递记录及只落History关闭在 S16/S17 完成，激活/停止由 Application 统一编排。REST 协议保持 `/api/sessions/{id}/cron-tasks/...`。
- `entity/puretype/extools.py::CronTaskInfo` 增加只读字段 `is_wait: bool = False` 与 `wait_message: str = ""`，由 `_build_task_info` 显式映射 `_CronTask.is_wait`/`wait_message`（普通 Cron 为 false/空串，不按 name/command 猜测）；不改调度、持久化、审批、Timer 或执行语义。

工具适配层现位于 `buildin_tools/extools/cron_tools.py`，继续依赖 `component.cron_tasks`，不迁移本节服务或任务模型。

---

## 动态端点服务

`component/dynamic_endpoints.py::DynamicEndpointSystem` 是依赖 `RuntimeSystem`、`SessionManager` 的 framework `AsyncSystem`，唯一持有动态端点字典、锁和 `dynamic_endpoints.json`。`virtual_awake` 严格恢复合法记录，缺失会话只跳过内存加载但保留磁盘条目；损坏文件、非法记录和持久化失败直接传播。工具、Gateway、会话删除和旋转只通过 `get_system(IDynamicEndpointSystem)` 调用公开实例方法。`close_admission()` 只停止新注册、迁移和显式注销，不删除持久端点配置；永久删除会话的清理由独立公开清理方法负责。

工具适配层现位于 `buildin_tools/extools/dynamic_endpoint_tools.py`，仅解析参数并适配公开服务结果；动态端点的恢复、持久化与关闭所有权仍留在本模块，不随工具迁移。

## System 接口槽位约定（2026-10-20）

ApprovalSystem、CronRouter 和 DynamicEndpointSystem 分别使用 `IApprovalSystem`、`ICronRouter` 和 `IDynamicEndpointSystem` 作为依赖、查询和 Application 注册槽位。工具模块只通过这些接口访问运行期服务；审批、Timer 与动态端点的资源所有权仍由具体实现持有。BrowserSystem 的 `IBrowserSystem` 槽位与浏览器资源约定见 [`buildin_tools/DEV-README.md`](../buildin_tools/DEV-README.md#browser-接口槽位最终资源等待与-runtime-约定)，Application 装配不变。

## Cron故障诊断与最终资源等待（2026-10-28）

命令型Cron仍在Timer线程调用同步Runner，Runner通过线程安全提交将清理交给Runtime loop；不在Timer线程直接create_task。wait任务不创建子进程，不会进入这条清理路径。命令非零退出仍作为任务结果，成功返回后才更新计数/should_schedule并保存；不增加自动重试或更改持久化格式。

Timer回调意外失败先交Runtime即时记录完整栈并请求失败关闭，再追加session_id/task_id/is_wait安全定位，不新增命令正文日志。附加诊断失败不覆盖原异常；真实持久化或内部错误不降级。资源清理观察超时仍维持pending，不据此单独关闭应用。

Browser 最终注销、自有无头进程等待与 CDP/driver 释放约定已迁至 [`buildin_tools/DEV-README.md`](../buildin_tools/DEV-README.md#browser-接口槽位最终资源等待与-runtime-约定)。当前仅源码实施与只读审阅，未运行校验、构建或应用；用户需部署后验收。

## Runtime 依赖继承（2026-10-30）

`IApprovalSystem`、`ICronRouter`、`IDynamicEndpointSystem` 改继承 `IDPRuntimeSystem`，三个具体实现仍只继承各自接口。构造移除重复 Runtime 声明，其余业务依赖不变；Runtime 与 Logger 依赖由公共基类链自动加入，最终依赖集合和注册槽位不变。Browser 对应接口的继承与实现约定见 [`buildin_tools/DEV-README.md`](../buildin_tools/DEV-README.md#browser-接口槽位最终资源等待与-runtime-约定)。

Cron、DynamicEndpoint 接口移除重复抽象 `runtime`，具体实现的缓存属性覆写、唤醒赋值和已有 `_runtime` 引用均保留；Approval 原有缓存访问同样不改。framework 解绑后的关闭期仍使用已有引用，不改成公共属性的动态查询。审批、工具、Timer 与动态端点的业务和资源所有权保持，无持久化或前端变更。未运行校验、构建、实际导入或应用。

## Runtime 属性与关闭准备（2026-10-30，当前约定）

Approval/Cron/DynamicEndpoint移除Runtime缓存与具体属性覆写，统一继承`runtime`；前节缓存保留约定由本节覆盖。关闭主体更名为`virtual_prepare_shutdown`，Application在绑定期间等待它们，真正framework钩子只核对结果。释放服务前先有Registry真实工作屏障，不把图上独立视为工具运行时不会使用这些服务。Browser 的对应关闭准备、登记器 release 闭包与真实资源等待约定见 [`buildin_tools/DEV-README.md`](../buildin_tools/DEV-README.md#browser-接口槽位最终资源等待与-runtime-约定)。

Cron的停止观察预绑定`on_failure`，保持错误列表、Runtime→Cron锁序、持久任务语义和真实Timer join；失败不继续拆依赖。Approval请求及DynamicEndpoint持久数据语义不改。

无新增槽位或依赖边，不改third、前端、持久化、审批授权或5秒硬截止。日志退出和工具线程池软观察的既存限制不在本轮扩大修复。仅源码及只读审阅，未运行校验、导入、测试、构建或应用。
