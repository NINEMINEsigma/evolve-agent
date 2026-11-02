# component/ — MCP、Cron 与动态端点服务

`component/` 当前保留 MCP 管理入口、Cron 路由与任务模型、动态端点服务。审批系统已整体迁入 [`system/approval/`](../system/approval/DEV-README.md)；五个内置工具子包已整体迁至 [`buildin_tools/`](../buildin_tools/DEV-README.md)，工具发现、工具契约、Shell、文件操作、Read、多模态、LSP、会话视觉资源及 BrowserSystem 的约定统一见该文档。

目录目标是承载架构 Component 相关实现，但当前仍保留 Cron、动态端点等历史服务，尚未完成最终 Component 专用整理。本次只迁审批，不搬迁 `ActivityLoggerComponent`，也不扩大为其他目录职责重构。

---

## 文件结构

```
component/
├── __init__.py              ← 包入口
├── mcp_tools.py              ← MCP 管理工具独立入口
├── cron_router.py            ← Cron 任务路由
├── cron_tasks.py             ← Cron 任务模型与时间解析
└── dynamic_endpoints.py      ← 动态端点 System
```

工具的五包结构、50 个 `TOOLSET` 声明模块、发现顺序及共享模块边界见 [`buildin_tools/DEV-README.md`](../buildin_tools/DEV-README.md)。`component.mcp_tools` 保持独立显式注册，不随五包迁移；旧五包无兼容代理。运行时合并复制的残留风险、停机完整部署与定向处理边界见该文档的[包迁移与完整部署边界](../buildin_tools/DEV-README.md#包迁移与完整部署边界)，开发助手AI不操作运行时副本。

---

## 异常定义包（2026-10-30）

本包 MCP、Cron 与动态端点业务使用的公共自定义异常统一 `from entity.error import X`；全部 origin仓库自定义异常（含内部控制信号）只在 [异常定义包](../entity/error/DEV-README.md) 按职责子模块定义，并由 `__init__.py` 显式导出，不散放在本包业务模块。标准库/第三方异常仍从原来源导入。私有 `_SourceUnavailable` 仅从 `entity.error.session_export` 显式导入，不公开。

异常继续继承原 Exception 家族，不强行改 BaseModel，不改变任务执行、取消/停止、必要持久化失败、资源清理与快速失败策略。`SessionExportError` 及全部公共子类仍为唯一定义的同一族；本包不建立重复类型或旧路径兼容入口。纯转发 `system/lifecycle_errors.py` 已删除，生命周期分类函数仍留原业务职责。

异常不加入 easysave/typeref，存储 key 未变，System装配和资源所有权不变。本次仅源码迁移与文档同步，未运行测试、实际导入、构建、校验或应用；用户须停机完整部署新包与全部调用方并重启，注意合并复制残留，开发助手AI不操作 workspace。

## 审批系统迁出（2026-11-02）

原 `component/approval/` 的10个Python文件整体迁至 `system/approval/`，公共入口为 `system.approval`，旧路径不保留源码或兼容转发。审批模式、Profile后端、白名单、主/子会话策略、接口槽位与关闭准备的完整规范已迁入[审批系统开发文档](../system/approval/DEV-README.md)，本包不再维护第二份审批说明。

唯一非路径逻辑补齐是在模式load前contains确认目标key，缺key仍warning后手动模式且不写盘；持久化模型、key及type token不变。用户完整部署新包与调用方并重启，定向处理旧审批源码残留，保留本包其他服务及所有持久化数据；共享宿主扩展与所有可能运行、提升或承担修复的代码副本须配套。开发助手AI未操作运行时副本，也未运行校验、导入、测试、构建或应用。

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

## System 接口槽位约定（2026-10-20，归属更新于2026-11-02）

CronRouter 和 DynamicEndpointSystem 分别使用 `ICronRouter` 和 `IDynamicEndpointSystem` 作为依赖、查询和 Application 注册槽位。工具模块只通过这些接口访问运行期服务；Timer 与动态端点的资源所有权仍由具体实现持有。ApprovalSystem 的原 `IApprovalSystem` 槽位保持，相关实现与说明见[审批系统](../system/approval/DEV-README.md)。BrowserSystem 的 `IBrowserSystem` 槽位与浏览器资源约定见 [`buildin_tools/DEV-README.md`](../buildin_tools/DEV-README.md#browser-接口槽位最终资源等待与-runtime-约定)，Application 装配不变。

## Cron故障诊断与最终资源等待（2026-10-28）

命令型Cron仍在Timer线程调用同步Runner，Runner通过线程安全提交将清理交给Runtime loop；不在Timer线程直接create_task。wait任务不创建子进程，不会进入这条清理路径。命令非零退出仍作为任务结果，成功返回后才更新计数/should_schedule并保存；不增加自动重试或更改持久化格式。

Timer回调意外失败先交Runtime即时记录完整栈并请求失败关闭，再追加session_id/task_id/is_wait安全定位，不新增命令正文日志。附加诊断失败不覆盖原异常；真实持久化或内部错误不降级。资源清理观察超时仍维持pending，不据此单独关闭应用。

Browser 最终注销、自有无头进程等待与 CDP/driver 释放约定已迁至 [`buildin_tools/DEV-README.md`](../buildin_tools/DEV-README.md#browser-接口槽位最终资源等待与-runtime-约定)。当前仅源码实施与只读审阅，未运行校验、构建或应用；用户需部署后验收。

## Runtime 依赖继承（2026-10-30，归属更新于2026-11-02）

`ICronRouter`、`IDynamicEndpointSystem` 改继承 `IDPRuntimeSystem`，两个具体实现仍只继承各自接口。构造移除重复 Runtime 声明，其余业务依赖不变；Runtime 与 Logger 依赖由公共基类链自动加入，最终依赖集合和注册槽位不变。审批接口同样保持原继承链，详见[审批系统文档](../system/approval/DEV-README.md)。Browser 对应接口的继承与实现约定见 [`buildin_tools/DEV-README.md`](../buildin_tools/DEV-README.md#browser-接口槽位最终资源等待与-runtime-约定)。

历史缓存保留约定：Cron、DynamicEndpoint 接口移除重复抽象 `runtime` 后，具体实现的缓存属性覆写、唤醒赋值和已有 `_runtime` 引用当时仍保留，framework解绑后的关闭期使用已有引用。该描述由下一节无缓存与关闭准备约定覆盖；业务和资源所有权保持，无持久化或前端变更。未运行校验、构建、实际导入或应用。

## Runtime 属性与关闭准备（2026-10-30，当前约定）

Cron/DynamicEndpoint移除Runtime缓存与具体属性覆写，统一继承`runtime`；前节缓存保留约定由本节覆盖。关闭主体更名为`virtual_prepare_shutdown`，Application在绑定期间等待它们，真正framework钩子只核对结果。释放服务前先有Registry真实工作屏障，不把图上独立视为工具运行时不会使用这些服务。Approval 的对应请求等待与关闭约定见[审批系统](../system/approval/DEV-README.md)；Browser 的对应关闭准备、登记器 release 闭包与真实资源等待约定见 [`buildin_tools/DEV-README.md`](../buildin_tools/DEV-README.md#browser-接口槽位最终资源等待与-runtime-约定)。

Cron的停止观察预绑定`on_failure`，保持错误列表、Runtime→Cron锁序、持久任务语义和真实Timer join；失败不继续拆依赖。DynamicEndpoint持久数据语义不改。

无新增槽位或依赖边，不改third、前端、持久化、审批授权或5秒硬截止。日志退出和工具线程池软观察的既存限制不在本轮扩大修复。仅源码及只读审阅，未运行校验、导入、测试、构建或应用。
