# buildin_tools/ — 内置工具与 BrowserSystem

`buildin_tools/` 承载从 `component/` 整体迁入的五个内置工具子包，目录名按项目约定使用 `buildin_tools`。审批、Cron 路由与任务模型、动态端点服务和 MCP 管理入口仍在 [`component/`](../component/DEV-README.md)；本次只迁五包，不代表 `component/` 已完成最终 Component 专用整理。

## 文件结构与边界

五包共 61 个 Python 文件、50 个声明 `TOOLSET` 的模块。下面的数量是正式源码基线，不是运行校验结果；不包含可选 `custom_tools/`、`MCPRefresh` 或远程 MCP 工具。

| 子包 | 完整文件名 | 文件数 | TOOLSET 声明模块数 |
|---|---|---:|---:|
| `tools/` | `__init__.py`、`_file_changes.py`、`_history_compression.py`、`ask_question.py`、`code.py`、`compress_history.py`、`compress_tool_chains.py`、`filesystem.py`、`frontend.py`、`list_uploads.py`、`load_toolset.py`、`lsp.py`、`progress_tools.py`、`refresh_identity.py`、`sandbox_spaces.py`、`session_search.py`、`session_variables.py`、`shell.py`、`show_tool.py`、`skills.py` | 20 | 17 |
| `multiagenttools/` | `__init__.py`、`agents_group.py`、`approval_subagent.py`、`chat_subagent.py`、`enter_multi_agent.py`、`exit_multi_agent.py`、`list_subagents.py`、`profile_builder.py`、`run_subagent.py`、`run_taskagent.py`、`stop_subagent.py`、`stop_taskagent.py` | 12 | 9 |
| `extools/` | `__init__.py`、`archive_tools.py`、`cron_tools.py`、`diff_tools.py`、`dynamic_endpoint_tools.py`、`web_fetch.py` | 6 | 5 |
| `browser/` | `__init__.py`、`_connection.py`、`close.py`、`connect.py`、`interact.py`、`launch.py`、`list_tabs.py`、`navigate.py`、`query.py`、`screenshot.py`、`system.py`、`tab.py`、`wait.py` | 13 | 10 |
| `automation/` | `__init__.py`、`keyboard_press.py`、`keyboard_type.py`、`mouse_click.py`、`mouse_drag.py`、`screen_capture.py`、`template_match.py`、`window_enum_child.py`、`window_find.py`、`window_focus.py` | 10 | 9 |

`buildin_tools/__init__.py` 是空包入口，不导入或重新导出工具、不注册工具、不导入 BrowserSystem、不访问 Application。五包的包入口与辅助模块不是额外工具来源；`agents_group.py` 是既有未实现入口，不补写功能或增加 `TOOLSET`。

`browser/system.py` 随包迁移但仍是实现 `IBrowserSystem` 的 System，由 Application 原装配清单注册，资源所有权与生命周期不变；`browser/_connection.py` 仅承载无状态辅助逻辑。`multiagenttools/profile_builder.py` 仍在多Agent工具包内，除进入多Agent模式工具使用外，还被 `gateway/session_manager.py` 的会话恢复构造与 `entry/multi_agent_loop.py::MultiAgentLoop.set_profile()` 调用；共享构造契约及延迟导入位置不因目录迁移改变。

---

## 异常定义包（2026-10-30）

内置工具与 BrowserSystem 消费的所有公共自定义异常统一 `from entity.error import X`，不从 Sandbox、Shell、角色档案、元数据或其他业务模块间接导入。全部 origin仓库自定义异常（含内部控制信号）只在 [异常定义包](../entity/error/DEV-README.md) 按职责子模块定义，并在 `__init__.py` 显式导出；本包不定义工具专用异常或兼容转发。标准库与第三方异常继续从原来源导入，`NotImplementedError` 等标准异常不迁移。私有 `_SourceUnavailable` 只从 `entity.error.session_export` 显式导入且不公开。

异常保留原 Exception 家族，不强行改 BaseModel；工具 before/handle/after、普通工具错误转换、审批拒绝、中断配对、必要保存失败与快速失败语义保持。`MetaFormatError` 定义已移至 `entity/error/util.py`，`util/file_metadata.py` 仍负责解析与抛出。`SessionExportError` 的所有公共子类保持同一唯一基类，不建立平行异常族。

异常不进入 easysave/typeref，存储 key、工具声明、System装配和资源所有权不变。本次仅源码迁移与文档同步，未运行测试、实际导入、构建、校验或应用。用户须停机完整部署新包与全部调用方并重启，注意合并复制旧文件残留；开发助手AI不操作 workspace。

## 工具系统

### 注册与发现

`buildin_tools/` 下全部工具来源（`tools/` 17、`extools/` 5、`multiagenttools/` 9、`browser/` 10、`automation/` 9 个模块）均已迁移为 `BaseTool` 子类与顶层 `TOOLSET = BaseToolSet(...)` 声明；每个模块导入只创建无连接工具对象，不取得 Application、不注册、不创建运行时连接。自定义工具与 MCP 来源使用同一对象契约。来源迁移与静态复核仍在收尾，完整任务复核与用户验收待完成，不能启动中间源码。

`ToolRegistry` 是依赖 RuntimeSystem 的 AsyncSystem，运行期通过 `get_system(IToolRegistry)` 取得唯一实例；注册期由 `ToolDiscoverySystem` 按 AST 识别顶层 `TOOLSET` 后，以 `register_toolset(toolset, merge=True)` 装载并执行一次 `preheat()`。模块级 registry 单例、函数式 `register`、`ToolEntry`/`ToolsetEntry` 镜像、`HandlerToolAdapter` 与 `UIEventRouter` 均已移除；AST 发现对退役的 `register_tools`、旧全局注册表导入与导入期注册直接失败。

内置发现顺序保持 `buildin_tools.tools` → `buildin_tools.extools` → `buildin_tools.multiagenttools` → `buildin_tools.automation` → `buildin_tools.browser`，各包内按路径排序；随后处理可选 `custom_tools/`，再显式注册 `component.mcp_tools` 中的 `MCPRefresh` 与工具集元数据。只扫描新五包，不同时扫描旧包或改为扫描 `buildin_tools/` 根。内置目录缺失、源码读取、AST、导入、预热、注册及同名冲突沿既有失败路径传播；仅可选 `custom_tools/` 不存在时跳过。

工具四阶段（工具调用前 `before_handle`、工具主体 `handle`、工具调用后处理 `after_handle`）与工具集 `preheat()` 的完整契约见 [`abstract/DEV-README.md`](../abstract/DEV-README.md)。专属后处理示例：

- 进度工具在主体内保留原会话资源更新逻辑，`after_handle` 直接通过当前 Sink 发送原 payload，业务 error 不发送成功 UI 更新。
- `EvolveCode` 在保存后的 `after_handle` 唯一请求进化关闭。
- `Enter/ExitMultiAgent` 主体只准备材料，`after_handle` 执行子Agent关闭（进入时）、目标 Loop 构造与 SessionManager 交接，完成后立即停止旧轮次。

公开 schema、危险等级、可用范围和工具名称按原声明保留。toolset 名称、availability、check_fn、requires_env、no_timeout、accepts_following_calls、preheat 及 before/handle/after 行为不变；模块级工具对象仍由唯一 Registry 共享持有。工具执行材料、History 引用与阶段状态属于单次调用，不写入共享工具实例或持久化存储。

工具来源包括：

- `buildin_tools/tools/` — 核心工具
- `buildin_tools/extools/` — 扩展工具
- `buildin_tools/multiagenttools/` — 多Agent工具
- `buildin_tools/browser/` — 浏览器控制工具
- `buildin_tools/automation/` — 桌面自动化工具
- `custom_tools/` — 用户自定义工具（若目录存在）
- MCP server — 由 `MCPSystem` 连接和注册远程工具；`component/mcp_tools.py` 仅显式声明管理工具，仍是五包之外的独立入口，正文见 [MCP 桥接](../component/DEV-README.md#mcp-桥接)。

### 核心工具（`buildin_tools/tools/`）

| 工具文件 | 主要工具 | 用途 |
|----------|----------|------|
| `filesystem.py` | `Read`, `Write`, `PatchEdit`, `Delete`, `Copy`, `Move`, `SearchFiles`, `Grep`, `file_exists` | 沙盒内文件操作；`Read` 文本分支自动尝试 UTF-8、系统编码和 Windows 常见编码，按 `offset`/`limit` 选择原文行后逐行应用 `max_line_chars`（默认 1000）；未截断内容保持原文，超长行返回前缀加 ` ... [truncated]`，不添加行号或规范化换行，保留 CRLF、孤立 CR 与末尾 LF，行位置仍由原文件 `offset`/`total_lines` 给出；`PatchEdit` 的 exact/range 均按原始 UTF-8 文本逐字符匹配并原样写入 `new_string`，regex 仅按 Python `re.sub` 语法展开显式引用；三种模式都不自动补换行。`Sandbox.write()`/`append()` 禁用操作系统换行转换；`SearchFiles`/`Grep` 在 Windows x64 优先使用内置 `ripgrep`，不可用或单次不兼容时回退 Python；`Grep` 上下文与回退行号都按 LF 分行；默认遵循 ignore/hidden 过滤，返回 `engine`、`truncated`，`full_scan` 可完整包含隐藏/忽略路径，`exhaustive` 可完整扫描并写超限日志 |
| `code.py` | `ValidateCode`, `EvolveCode` | 自我进化 |
| `shell.py` | `StartShell`、`ReadShell`、`WriteShell`、`InterruptShell`、`StopShell` | Windows ConPTY 长期 Shell会话：启动并输入、字符位置读取、复用输入、Ctrl-C 与强制停止 |
| `frontend.py` | `ValidateFrontend` | 前端构建验证 |
| `skills.py` | `RecallSkill`, `CreateSkill` | 技能管理（已并入 core 工具集） |
| `load_toolset.py` | `LoadToolset` | 按需加载工具集到当前会话（core 工具集，EVERY 可见性）；加载只改变已加载集合，返回名称仅供发现，工具仍须通过当前 Loop 的 scope、危险等级与运行时权限过滤 |
| `sandbox_spaces.py` | `AddSandboxSpace`、`RemoveSandboxSpace` | fast 模式全局动态沙盒空间增删；位于按需加载的 `sandbox` 工具集，critical，仅普通/多Agent模式主Agent可修改；用户也可通过命令菜单中的动态沙盒空间管理弹窗直接执行 REST CRUD |
| `ask_question.py` | `Ask` | 向前端提问（多问题表单：一次调用携带 1~N 个问题，每题独立单选/多选 + 可选自定义文本，推送 ask_request 后阻塞等待整表提交；answers 按题返回） |
| `progress_tools.py` | `UpdateTaskProgress`, `ClearTaskProgress` | 任务进度 |
| `show_tool.py` | `ShowTool` | 查看工具/工具集元数据；可见性按当前 Loop 口径分派，子Agent（SubAgentLoop/TaskAgentLoop）按动态口径（已加载工具集 ∩ scope ∩ check_fn）返回，与各自 LLM 工具表一致 |
| `list_uploads.py` | `ListUploads` | 列出上传文件 |
| `compress_history.py` | `CompressHistory`（`CompressHistoryTool` + `TOOLSET`） | 会话历史压缩：`handle` 只校验参数并把 `summary`、保留轮次起点登记为调用态材料；结果提交后的 `after_handle` 重新扫描历史，把旧轮次替换为 Agent 撰写的会话摘要，并把保留轮次内的完整工具链重打包为伪造的 `CompressedToolChain` 调用 + 工具链摘要 Profile 生成的链摘要（`no_timeout`）。摘要模型调用前发「正在压缩历史...」，替换、`save_history()` 与 `reset_context_tokens()` 成功后发「压缩完成」；链摘要任一步失败直接传播、历史不变。排除当前调用所在链，故当前轮不被压缩 |
| `compress_tool_chains.py` | `CompressToolChains`（`CompressToolChainsTool` + `TOOLSET`） | 无业务参数；`after_handle` 在自身结果提交后扫描全部历史中的完整工具链并替换为链摘要，不截断轮次或插入会话摘要；普通用户消息与不带工具调用的回复保留，未完成链及纯压缩占位链跳过；本次调用自身所在链此时已完整，可一并被压缩（D11）。`core` / `MAIN` / `critical` / `no_timeout`，无符合条件链时更新已保存结果为零计数且不写历史 |
| `session_variables.py` | `ReadSessionVariables` | filesystem工具集的safe整池只读工具；按ToolContext.resource_session_id读取全部数字/字符串、meta和问题，写入仍使用通用文件工具 |
| `session_search.py` | `SessionSearch` | 会话内容搜索；`RecallSession` 通过 `ToolRegistry` 的同步工具线程池执行全会话 History 读取与 BM25/RRF 计算，避免长时间检索占用事件循环，结果协议不变 |
| `lsp.py` | LSP 诊断 | LSP 服务器进程管理与代码诊断 |

### 压缩工具共享逻辑

`buildin_tools/tools/_history_compression.py` 是两种压缩工具共享、无 History 副作用的模块：

- `prepare_tool_chain_replacements(messages, *, session_id, metadata_service, start_index=0, excluded_tool_call_ids=None)` 返回非持久化 `ToolChainReplacement` 列表，不修改 History。任一链的 tool_call_id 命中 `excluded_tool_call_ids` 时整条链跳过：`CompressHistory` 传 `{当前 tool_call_id}` 保护本轮，`CompressToolChains` 传空集合扫描全历史（含本次调用自身）。该消息后纯类型定义于 `entity/puretype_after/session.py`，通过 `entity.puretype_after` 显式导入，直接引用正式 `BaseMessage`，不由工具模块调用 `model_rebuild` 补装配；只有索引字段的 `ToolChainSpan` 仍属于消息前纯类型。
- `collect_tool_call_ids(messages, ranges)` 收集给定半开区间 [start, end) 内的真实 tool_call_id，供 after 保留内部移除事实及 suppress 资格校验；前端由独立 history_updated 指令重载，不按该列表重构正典历史。

链摘要统一由 `SessionMetadataService.generate_tool_chain_summary()` 生成，未设置工具链摘要 Profile 时回退目标会话活动 Profile。阈值复用 `TOOL_CHAIN_COMPRESS_MIN_CHARS`（4000 字符），不新增配置或模型用途引用。

两个工具的 `handle` 都不修改 History：`CompressHistory.handle` 只做参数边界校验并把 `summary`、`keep_start_idx` 作为调用态材料登记到 `ToolExecution.state`（业务错误时该材料为空，after 直接返回空效果）；`CompressToolChains.handle` 不接收业务参数。摘要准备、替换、保存、计数通知全部在结果写入并保存后的 `after_handle` 中执行：按 `start_index`/`excluded_tool_call_ids` 重新检测并预生成全部链摘要，任一摘要失败或期间协作式中断都直接传播、不提交压缩；全部摘要成功后才按逆序 `History.replace_range()`（`CompressHistory` 随后 `truncate_from(keep_start_idx)` 并在头部插入摘要消息），再 `save_history()`、`reset_context_tokens()`、完成通知。保存错误沿已有 History 生命周期传播，不声称写盘失败会自动回滚已修改的内存。

两者返回 `ToolPostprocessEffect`：`replacement_result` 携带 `success`、`tool_chains_compressed`、`messages_removed`（消息数净减少量）、`remaining`（压缩后的 History 消息数），由 post-commit 通道同步更新已保存的工具结果与通知（无符合条件链时为零计数，避免遗留 `_compression_pending` 占位）；`discarded_tool_call_ids` 为被替换/截断区间内的全部真实调用 ID，仅用于内部移除事实与 suppress 资格校验，不再作为丢弃批次后缀的协议发送。真实压缩保存成功后同步调用 `execution.mark_history_updated()`；ToolPostprocessor在必要结果回填保存后发送独立 `history_updated` 指令，前端完整重载骨架与按需正文。原完成系统通知通过效果的 `system_message` 延至指令后发送，取消/失败不发成功通知；保存成功后的取消仍根据调用级标记尝试发失效指令。`CompressToolChains` 仅当自身 ID 被 discard（自身链被替换）时 `suppress_tool_result_event=True`，此时不更新自身结果（该结果已随链离开 History，收尾通道会拒绝更新已移除的消息），否则正常更新并发送工具结果；`CompressHistory` 的当前调用位于保留轮次且其链被排除，因此始终不 suppress、始终更新自身结果。

链内工具调用消息的正文及媒体也会被摘要替代，只有链外消息保持原样；字符阈值不保证摘要 token 数一定更少。

两工具的 `critical` 在手动/脱手模式由用户审批，YOLO 模式免审批。`MAIN` 范围保留普通模式和随意聊聊会话，不向多Agent模式、子Agent或临时Agent扩展。本次没有新增 UI 事件或工具集；源码已实施，未运行构建、校验或应用验收。

### 会话变量工具

`ReadSessionVariables` 位于filesystem工具集，需先LoadToolset加载，safe、EVERY、同步handler由既有ToolRegistry执行器持有。没有会话选择参数，普通子Agent/临时Agent读父主会话池；临时Agent仍仅已加载∩TASKAGENT∩safe。service由`get_system(IAgentspaceService).session_variables`取得，读取的每个明确文件登记既有回复轮次接触，不锁整树，不创建UI事件。

返回完整原值、raw_value、raw_metadata、normalized metadata、条目/池级issues及scan_complete；工具与REST复用read_pool。无法完整扫描时显式诊断，池级预算拒绝返回error，不返回伪空列表。写入通过Read/Write/PatchEdit管理`ws:sessions/<sid>/variables/`中的JSON标量与同级.meta，数值限制仅提示，percent=true仅显示×100。主Agent统一共享结算，不提供原子增减或聊天回滚。

### 多模态能力生命周期（S14）

Read的能力缓存查询、自动探测与转发经 `get_system(IModalityCapabilitySystem)` 调用；System持有共享锁、探针媒体、缓存路径和完整请求任务，纯媒体内容块构造仍从模块导入。关闭封闭新模型请求并等待六路子探针真实结束后再释放锁；明确停止和生命周期异常不得转换为普通工具结果。缓存与Read的媒体协议保持。

### BrowserSystem 生命周期迁移（S13）

`buildin_tools/browser/system.py::BrowserSystem` 依赖 RuntimeSystem，唯一持有 Playwright、CDP连接、当前端点及应用启动的无头进程。virtual_awake不加载Playwright或启动浏览器；工具运行期通过get_system(IBrowserSystem)查询，原_connection仅保留无状态探测、标签页定位与DOM函数，常量由entity/constant/browser.py导出。

连接请求经TaskOwner.run_request管理并以连接锁串行化，部分连接失败释放已取得资源。断连及原生进程回收各有明确持有的清理任务，取消调用方等待不取消真实释放；关闭超时/失败上报并保留资源引用。多次无头启动保留每个自有进程句柄，不覆盖丢失旧进程；只有这些登记进程会被终止，用户自己启动的浏览器不被杀死。最终注销先停止请求，再尝试独立资源释放并传播全部失败，main.py不再重复cleanup。工具handler任务与其他浏览器操作先由ToolRegistry收尾，应用级关闭编排由 Application 统一执行。

### LSP 工具生命周期

LSP工具与文件修改后的诊断附加统一通过 `Application.current().get_system(ILSPManager)` 调用。System唤醒只绑定Runtime主loop与Sandbox，pyright仍由LSPStart按需启动；工具不再传入Sandbox或创建独立manager。启动/替换和关闭均确认进程及reader线程实际结局，关闭失败传播，main.py不再执行另一套cleanup。

### Read 正文单行限制

`Read` 的可选参数 `max_line_chars` 默认 1000，只接受大于等于 1 的整数；可以显式提高或降低，没有关闭值或额外硬上限。handler 在路径解析之前校验所有分支的参数：bool、浮点数（包括 1000.0）、字符串、null、0、负数、数组和对象均返回 `max_line_chars must be a positive integer`。只有省略参数才使用默认值；合法值在目录和媒体分支中忽略，不影响它们的返回结构。

文本先按 `offset`/`limit` 分页，再由 `util/text_preview.py::truncate_lf_lines` 逐行处理展示内容。函数没有 I/O，只复用 `util.text_codec` 的 LF 分行/行尾处理，不改变 `Sandbox.read()` 的原文读取和内部 `limit=0` 路径。正文按 Python str 的 Unicode 码点计数，不按字节或字素簇计数；空格、制表符及孤立 CR 计入，LF/CRLF 行尾不计入，组合字符或 ZWJ 序列可能在边界处被切开。

超限行保留前 N 个码点，附加 ` ... [truncated]`（含前导空格），再接原行尾；标识和行尾不占 N 的额度。未超限行保持原文，不插入行号、不折行、不补末尾换行；仅 LF 分行，保留原有 LF/CRLF。成功文本结果增加：

- `max_line_chars`：本次有效上限。
- `truncated`：本次正文是否至少一行发生字符截断，非分页状态。
- `truncated_lines`：实际截断行在原文件中的绝对 **0-indexed** 索引，和 offset 口径一致；未截断时为空列表，原文已有标识不影响判断。

空文件或 offset 到达/越过 EOF 时正文为空、`truncated=false`、截断索引为空列表。`total_lines`、`remaining` 均在展示截断前按原文统计；`remaining=0` 仍可同时 `truncated=true`。例如无末尾换行的 `abcdef`，上限 3 时返回 `abc ... [truncated]`，截断索引为 `[0]`。需要完整长行时保持 offset/limit 并显式提高有限的 max_line_chars 重读；没有字符 offset 续读或无限制模式。

截断标识不是原文件内容，截断行不是完整原文；使用 PatchEdit 时不得把人工标识当作匹配或写回内容，也不得把可见前缀误当成整行。PatchEdit 的内部完整读取、原文匹配和写回行为不变。

单行保护不保证结果总量有界，也不减少 Sandbox 全文件读取、解码及重复计行的内存/I/O 开销。目录条目、媒体载荷及转发描述、自动附带 `meta` 均不应用该限制，未添加上述文本结果字段。显式把 `.meta` 作为文本目标则应用该限制，详见下节。

### Read 元数据文件

仅 `Read` 支持自动附带元数据文件：目标完整名称追加 `.meta`，例如 `ws:a.md` 对应 `ws:a.md.meta`，`ws:docs` 对应同级 `ws:docs.meta`，不是目录内部的 `.meta`。命名空间根目录（含等价当前目录写法或指向根目录的别名）不附带元数据；显式读取后缀为 `.meta` 的目标不继续嵌套。后缀识别不区分大小写，自动查找统一追加小写 `.meta`。

- 目录列表隐藏后缀匹配且为文件的条目，保留同后缀目录；`count` 为过滤后数量。`Sandbox.list_dir`、SearchFiles、Grep、Agentspace 文件树和写入/移动/删除工具不变。
- `util/file_metadata.py::parse_meta_content(content)` 是不执行 I/O 的共享解析入口。独立成行的 `[key]` 开始字段，键名不 trim、区分大小写，不允许空/纯空白键或键内方括号、CR、LF。标记行外侧没有空白；LF/CRLF 为行界，孤立 CR 仍是内容。
- 每个值一直延续到下一个键标记或文件末尾，缩进、空行、CRLF、孤立 CR 与末尾换行原样保留。独立的 `[text]` 是新键，不提供转义语法。
- 空文件或全空白文件得到 `{}`；无值键得到空字符串。重复键、非法的整行方括号标记、首个键前的非空文字抛带行号的 `MetaFormatError`，不返回部分解析字典。
- 文本、图片、音频、视频和目录成功结果均可包含普通 `meta` 字段：正常为 `dict[str, str]`，缺失省略，读取/登记/解析失败为错误字符串，不影响原目标结果；不同于内部工具统计字段 `_meta`。
- 自动附带的元数据经 `Sandbox.resolve_read` 与 `Sandbox.read(limit=0)` 完整读取和现有编码探测，不使用正文 offset/limit/max_line_chars；显式将 `.meta` 作为 Read 文本目标时，正文应用分页和单行字符限制，仍不查找 `.meta.meta`。明确 `ws:` 元数据文件登记当前回复轮次文件接触，登记失败不读取。各媒体 `_blocks`、`_user_blocks` 和转发 description 保持不变。
- 当前只返回元数据，不解释或执行键的业务含义，不自动生成或随移动/删除维护文件。会话视觉源目录的 `redirect` 字段由会话视觉资源服务按单层规则消费；`Read` 仍只返回原目录元数据，不跟随目标目录。

### 扩展工具集（`buildin_tools/extools/`）

| 工具文件 | 用途 |
|----------|------|
| `web_fetch.py` | 获取指定 URL 的网页内容 |
| `cron_tools.py` | 一次性/周期性后台定时任务 |
| `dynamic_endpoint_tools.py` | 动态端点工具（仅参数解析与 `DynamicEndpointSystem` 结果适配） |
| `archive_tools.py` | 归档工具 |
| `diff_tools.py` | diff 工具 |

动态端点的恢复、持久化、关闭与唯一所有权仍属于 `component/dynamic_endpoints.py::DynamicEndpointSystem`，详见 [动态端点服务](../component/DEV-README.md#动态端点服务)。`cron_tools.py` 仍依赖保留原位的 `component.cron_tasks`；Cron 路由、持久化和关闭约定见 [Cron 路由](../component/DEV-README.md#cron-路由)。

> **已移除的工具**：CSV / Excel / DOCX / PDF / 音视频处理 / 浏览器自动化 / GUI 自动化 / 图表生成等文档与媒体处理能力已从 extools 中移除。这些能力应通过 skill 实现（在 `pre-skills/` 或 `skills/` 中编写对应的 `SKILL.md` 和辅助脚本）。

### 多Agent工具（`buildin_tools/multiagenttools/`）

详见 [`subagent/DEV-README.md`](../subagent/DEV-README.md)。子Agent和临时Agent没有应用层数量上限；启动成功返回 `success` 与 `session_id`，不再返回旧排队字段。停止普通子Agent时通过 `session_path` 返回历史路径；停止响应不含旧队列晋升记录或排队提示。

| 工具文件 | 主要工具 | 用途 |
|----------|----------|------|
| `list_subagents.py` | `ListSubAgents` | 动态扫描角色档案，列出名称、类型、简介和运行状态 |
| `run_subagent.py` | `RunSubAgent` | 按动态角色档案启动子Agent |
| `run_taskagent.py` | `RunTaskAgent` | 使用活动 LLM Profile 快照启动临时Agent |
| `stop_taskagent.py` | `StopTaskAgent` | 提前终止临时Agent，不保存历史 |
| `stop_subagent.py` | `StopSubAgent` | 停止子Agent并保存临时 `.es` 历史 |
| `chat_subagent.py` | `ChatSubAgent` | 向子Agent发送消息 |
| `approval_subagent.py` | `ApprovalSubAgent` | 审批子Agent的工具调用 |
| `enter_multi_agent.py` | `EnterMultiAgent` | 切换到多Agent协作模式 |
| `exit_multi_agent.py` | `ExitMultiAgent` | 退出多Agent协作模式 |
| `agents_group.py` | `AgentsGroup` | Agent分组管理（当前未实现） |
| `profile_builder.py` | — | 动态角色档案到多Agent运行时 Profile 的构造 |

### 浏览器与桌面自动化工具

`browser/` 的十个工具声明模块为 `close.py`、`connect.py`、`interact.py`、`launch.py`、`list_tabs.py`、`navigate.py`、`query.py`、`screenshot.py`、`tab.py`、`wait.py`；`system.py` 和 `_connection.py` 的服务与无状态辅助边界见前述 BrowserSystem 生命周期约定。`automation/` 的九个工具声明模块为文件清单中除 `__init__.py` 外的九个模块；`mouse_drag.py` 继续复用 `buildin_tools.automation.mouse_click` 的 `_BUTTON_MESSAGES`，不引入第二份工具或资源所有者。

---

## Shell会话工具集

`ShellInfo.termination` 使用 `natural`、`forced`、`error` 区分 Shell 终止方式；`exit_code` 仍仅表示被托管进程的退出码，`StopShell` 返回 `stopped=true` 时不因非零退出码失败。输出规范化器折叠 PowerShell/PSReadLine 的 CR、退格和 CSI 重绘，启动阶段先等待当前 PTY 的初始输出稳定再写首条命令。

powershell/pwsh 使用 `-NoProfile`，并在启动阶段通过内部 `-Command` 优先尝试移除 PSReadLine；移除失败时回退为关闭预测。第一阶段不提供 PowerShell 历史、预测、方向键等行编辑能力。Shell 单行输入使用单独 CR（`\r`）提交。Agent 使用显式 `EVOLVE_PYTHON` 和 namespace 环境变量，不依赖用户 Profile 中的别名、函数或自动激活环境。

ShellManager 使用 pywinpty 高层 `PtyProcess` 的 socket reader；通过受保护的 `PYWINPTY_BACKEND=0` 环境切换强制 ConPTY，停止使用 `close(force=True)`，不直接依赖低层 PTY 读取/关闭 API。每个原始输出块都会刷新活动时间；无换行提示符在静默窗口后提交并立即以 `quiet` 返回，不等待 30 秒硬截止。Shell会话跨命令和回复轮次复用；单条命令完成、读等待超时或当前回复结束均不要求 `StopShell`，只有明确需要终结整个 Shell 时才调用。`StopShell` 的 `stopped` 表示资源清理是否确认完成；未完成时返回 cleanup pending，不删除仍在收尾的会话。

旧 `RunCommand`、`RunPython`、`InstallPackage`、`StartBackgroundService`、`StopBackgroundService`、`StartWatchingService` 及 `python`/`background` 工具集已移除；内部 `SubprocessRunner` 继续供验证、搜索等基础设施使用。

## 全局动态沙盒空间工具集

- `sandbox` 是 fast-only 的按需加载工具集，不属于默认 `core`；主Agent先通过 `LoadToolset` 加载。
- `AddSandboxSpace` 要求显式提供名称、规范化绝对路径、用途描述、`is_readonly` 和审批原因；同名同配置幂等，同名不同配置拒绝覆盖。
- `RemoveSandboxSpace` 按名称撤销后续逻辑路径解析；缺失名称幂等。
- 两个工具均为 critical：手动/脱手模式由用户亲自审批，YOLO 按全局语义自动批准。
- 普通模式与多Agent模式主Agent可修改；非主参与Agent不接收工具定义且 handler 二次拒绝。随意聊聊会话的工具集白名单有意不包含 `sandbox`。
- 已配置空间由 fast 模式所有 Agent 共享。动态只读与内置只读空间一致，只限制标准 Sandbox 文件 API，不是 Shell/Python/后台进程的 OS 级 ACL。

## 成功文件目标操作记录

`buildin_tools/tools/filesystem.py`的五种写工具私有handler统一接收`ToolExecution`；`buildin_tools/tools/_file_changes.py::FileChangeRecorder`在本次调用开始时固定`resource_session_id`、实际会话ID与角色，取得唯一`AgentspaceService.file_changes`。模块导入不访问Application，也不新增TOOLSET。

每个显式目标的文件操作成功后，同步把`SessionFileChangeOperation`纯元数据交Store保存；必要保存放在原SandboxError/Exception转换范围之外，失败沿LifecycleFailure触发应用级失败关闭，不包装为普通工具error继续批次。Write和PatchEdit先登记成功，再执行原有可选LSP诊断；公开schema、结果payload、审批与工具权限不变。

Delete逐paths目标记录，失败项继续原错误结果，成功项在catch之外保存，目录只记一条。Copy只记实际目的，Move源与实际目的两行共享一次全局操作。`Sandbox.copy/copy_folder/move`现在返回真实目的`ResolvedPath`，可继续忽略返回值；文件复制/移动到已有目录时用shutil真实返回的子路径，不猜测请求destination。

取消同时检查`ToolExecution.cancel_requested`和会话轮次中断。必要保存前最后采样已取消则不记账，保存开始后不因后来中断回滚此前成功目标；原生线程的停止/等待仍由原ToolRegistry负责。成功同内容覆盖、已存在目录创建或删除不存在文件也计操作次数。父目录自动创建与目录内部文件不展开；Shell、脚本和自定义工具不纳入此来源范围。仅完成源码与只读审阅，未运行验证。

## 文件修改目录树的记录口径

五种文件工具仍只在真实目标成功后调用`FileChangeRecorder`。目录目标也保留为目录条目显示，但不递归展开目录内部文件；父目录结构节点由前端合成且不计数。Write/Copy/Move在目标操作前由Sandbox返回本次实际递归创建的父目录，目标成功后逐条记录这些目录；已存在目录不重复记录。

`SessionFileChangeStore`为每个逻辑路径持久化`display_state`和`created_by_session`。首次创建/复制目的/移动目的为created，已有路径后续修改保持created；删除已有路径显示deleted，删除会话新增路径则隐藏；删除后再次创建/复制目的/移动目的进入modified。Move源按路径历史决定红色可见或隐藏，Move目的按历史决定created/modified。全局成功操作次数和隐藏删除次数仍保留，失败/取消边界不变。

## Agentspace 文件接触登记

内置工具通过 `ToolContext.agentspace_access()` 把明确的 `ws:` 路径登记到当前 Agent 回复轮次。

`ws:` 路径必须使用规范的逻辑路径格式：路径段之间使用 `/`，但不能以 `/` 或 `\` 开始或结束，也不能包含 `\`。例如目录应写成 `ws:reports/2026`，不能写成 `ws:reports/2026/` 或 `ws:reports\2026`。文档中用于表示目录的末尾 `/` 只是说明性记号，不是文件工具参数的一部分。不自动删除末尾斜杠或把反斜杠转换成正斜杠；不符合格式时，路径锁登记会先失败，工具返回 `Agentspace access lock failed`，不会继续执行读写或创建目录。

限制末尾斜杠是为了让 `ws:reports` 与 `ws:reports/` 不产生两个逻辑身份；限制反斜杠是为了不让 Windows 物理路径分隔符混入逻辑路径。唯一的逻辑表示可以保证路径锁、父子路径匹配、文件变化事件和文件修改记录使用同一身份。

- `Read` 与单文件 `Grep` 登记精确文件；目录读取/搜索不锁整树。
- `Write`、`PatchEdit` 登记目标；`Copy`、`Move` 同时登记源和目标；目录 `Move/Delete` 使用递归锁。
- `StartShell` 在 `cwd` 为 `ws:` 时登记当前回复轮次的递归 cwd；Shell会话返回后继续运行，因此该登记不宣称覆盖后台阶段。
- 登记失败时工具 fail-closed；非 `ws:` 命名空间保持原行为。
- `Delete` 的 schema、危险等级、审批和永久删除行为完全不变。Agentspace 垃圾桶只属于网页编辑器的用户删除 API。
- custom tools、MCP 和绕过应用的外部进程无法可靠事前识别路径，由 watcher 与版本冲突机制处理，不宣称预锁。

---

## Read媒体来源与主会话发送开关

Read原有能力路由、审批与返回结构保持；`prepare_tool_result`把tool_call_id传给 `tool_result_to_content` / `tool_result_to_follow_up`，实际媒体块记录逻辑path和来源工具ID，不采信absolute_path。user路径follow-up虽然是system角色用户消息，也有可定位的独立媒体实例；客户端传入的内部media_id/send_multimodal/verified不被blocks_from_dicts采纳。

主会话媒体输入Tab控制已经进入History的独立块，不禁止重新Read；每次重新Read的新块默认开启。关闭不会删除原媒体，也不改变工具集权限或审批。

ModalityCapabilitySystem新 `describe_media_block`返回结构化成功描述/明确不可用；只对明确UnsupportedModality或窄400模态拒绝允许不可用，网络/认证/超时/未知400/空描述失败。主请求准备只缓存成功描述，不再把旧错误模板当成功文字。原Read的 `forward_modality_to_ref_profile`仍返回原str/错误模板协议，正式媒体描述请求复用共享单跳调用，旧空媒体文字提示分支保留；不把工具旧返回格式扩展为本次新REST类型。

旧描述字段未证明成功时，主会话需要描述会重新取得一次成功结果。关闭仍允许向转发模型发原媒体，不是所有模型的隐私禁传。已实施，未运行验证。

---

## 会话视觉资源重定向

`stage/`、`site/` 与 `chat-style/` 的源目录可以使用同级 `.meta` 文件的 `[redirect]` 字段复用其他逻辑目录。服务端只解析源目录一次，合法目标由稳定视觉入口通过 HTTP 307 使用；缺失或非法配置静默回退源目录。前端 Hook 不解析 `.meta`，只消费最终入口并通过 Agentspace 事件与 HEAD 版本探测刷新。会话状态 REST 及扩展调用方可通过公开服务接口读取三项非持久化视觉资源状态。`Read` 对源目录保留原始元数据语义，并只将非法 `redirect` 原因放入 `meta.redirect`。

## Browser 接口槽位、最终资源等待与 Runtime 约定

BrowserSystem 使用 `IBrowserSystem` 作为依赖、查询和 Application 注册槽位。工具模块只通过接口访问运行期服务；浏览器资源所有权仍由具体实现持有，路径迁移不新增槽位、实例或依赖边。

Browser最终注销对已登记的自有无头Popen只请求一次终止，再观察同一实例退出；不因短窗口返回就宣称收回、不重复taskkill，不杀用户浏览器。CDP/driver真实释放仍归清理登记器。当前仅源码实施与只读审阅，未运行校验、构建或应用；用户需部署后验收。

Runtime 依赖继承记录（2026-10-30）：`IBrowserSystem` 改继承 `IDPRuntimeSystem`，具体实现仍只继承接口。构造移除重复 Runtime 声明，其余业务依赖不变；Runtime 与 Logger 依赖由公共基类链自动加入，最终依赖集合和注册槽位不变。当时 Browser 接口移除重复抽象 `runtime`，具体实现的缓存属性覆写、唤醒赋值和已有 `_runtime` 引用仍保留，framework 解绑后的关闭期仍使用已有引用，不改成公共属性的动态查询；该缓存保留约定由下述当前约定覆盖。浏览器进程的业务和资源所有权保持，无持久化或前端变更。未运行校验、构建、实际导入或应用。

Runtime 属性与关闭准备（2026-10-30，当前约定）：Browser 移除 Runtime 缓存与具体属性覆写，统一继承 `runtime`。关闭主体更名为 `virtual_prepare_shutdown`，Application 在绑定期间等待它，真正 framework 钩子只核对结果。释放 Browser 等服务前先有 Registry 真实工作屏障，不把图上独立视为工具运行时不会使用这些服务。Browser 的登记器 release 闭包仅使用既有 browser/driver 引用，纯连接释放 pending 由原登记器承接；自有进程仍实际等待，不查杀用户浏览器。

无新增槽位或依赖边，不改 third、前端、持久化、审批授权或 5 秒硬截止。日志退出和工具线程池软观察的既存限制不在本轮扩大修复。仅源码及只读审阅，未运行校验、导入、测试、构建或应用。Approval、Cron、DynamicEndpoint 的对应约定保留在 [`component/DEV-README.md`](../component/DEV-README.md#runtime-属性与关闭准备2026-10-30当前约定)。

## 包迁移与完整部署边界

origin仓库的旧 `component/tools/`、`component/extools/`、`component/multiagenttools/`、`component/browser/`、`component/automation/` 不保留兼容代理、转发入口、重复 `TOOLSET`、别名或 `sys.modules` 注入。旧五包的 Python 导入路径失效；未纳入本任务清单的外部调用方需要由用户同步迁移。工具名称、工具集名称、schema、权限、生命周期及存储语义保持，目录迁移本身不新增持久化格式或版本。

`run.py` 的合并复制不会清除目标侧独有的旧文件：fast仓库从来不先删除；进化时 fast→fallback 备份和 slow→fast 提升也采用合并覆盖。`force_init` 对 slow仓库与 fallback仓库是先删除再复制，但对 fast仓库仍只是合并覆盖，因此即使启用 `force_init`，fast 中旧五包也不会自动清除。本次不改 `run.py`、`.gitignore` 或复制过滤规则。

用户应在停止应用后完整部署新 `buildin_tools/` 和全部直接调用方，避免运行进程内混装新旧代码；在确认并保护本地进化内容与其他本地修改后，按实际部署范围定向处理 fast/slow/fallback 仓库中的旧 `component` 五包。处理对象仅为 `tools`、`extools`、`multiagenttools`、`browser`、`automation`，保留 `component` 的审批、Cron、动态端点、MCP 与其他用户内容；不能以删除整个 `component/` 或整个 `workspace/` 运行时根目录作为默认处理方式。

开发助手AI不检查、读取、修改或清理运行时副本，不替用户运行应用、实际导入、校验、测试或构建。上述部署说明供用户执行，不构成开发助手AI操作运行时副本的授权；本文保留各项既有未运行验收声明，不将文档迁移或只读审阅视为运行通过。
