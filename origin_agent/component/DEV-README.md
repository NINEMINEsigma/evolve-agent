# component/ — 工具、审批、MCP 与 Cron

`component/` 是 Evolve Agent 的具体能力实现层。它包含所有可直接调用的工具、审批系统（目录化）、MCP 桥接以及 Cron 任务路由。

---

## 文件结构

```
component/
├── approval/                ← 审批系统（目录化）
│   ├── __init__.py           ← 公共接口重新导出
│   ├── backend.py            ← ApprovalBackend 抽象 + Local/Remote 实现
│   ├── core.py               ← request_user_confirm / ask_agent_reason
│   ├── executor.py           ← execute_with_approval 统一执行器
│   ├── handsfree.py          ← 审批模式公共入口 + LLM 审批流程
│   ├── mode_store.py         ← Application 持有的会话级审批模式缓存与持久化服务
│   ├── allowlist.py           ← 工具 allowlist 持久化
│   └── policy.py             ← 审批策略（needs_approval + 预设策略常量）
├── tools/                    ← 核心工具
├── extools/                  ← 扩展工具集
├── multiagenttools/          ← 多代理 / 子代理工具
├── browser/                  ← 浏览器控制工具
├── automation/               ← 桌面自动化工具
├── mcp_tools.py              ← MCP 工具桥接
└── cron_router.py            ← Cron 任务路由
```

---

## 工具系统

### 注册与发现

`component/` 下全部工具来源（`tools/` 18、`extools/` 5、`multiagenttools/` 9、`browser/` 10、`automation/` 9 个模块）均已迁移为 `BaseTool` 子类与顶层 `TOOLSET = BaseToolSet(...)` 声明；每个模块导入只创建无连接工具对象，不取得 Application、不注册、不创建运行时连接。自定义工具与 MCP 来源使用同一对象契约。来源迁移与静态复核仍在收尾，完整任务复核与用户验收待完成，不能启动中间源码。

`ToolRegistry` 是依赖 RuntimeSystem 的 AsyncSystem，运行期通过 `get_system(ToolRegistry)` 取得唯一实例；注册期由 `ToolDiscoverySystem` 按 AST 识别顶层 `TOOLSET` 后，以 `register_toolset(toolset, merge=True)` 装载并执行一次 `preheat()`。模块级 registry 单例、函数式 `register`、`ToolEntry`/`ToolsetEntry` 镜像、`HandlerToolAdapter` 与 `UIEventRouter` 均已移除；AST 发现对退役的 `register_tools`、旧全局注册表导入与导入期注册直接失败。

工具四阶段（工具调用前 `before_handle`、工具主体 `handle`、工具调用后处理 `after_handle`）与工具集 `preheat()` 的完整契约见 `abstract/DEV-README.md`。专属后处理示例：

- 进度/剪贴板的四个工具在主体内保留原会话资源更新逻辑，`after_handle` 直接通过当前 Sink 发送原 payload，业务 error 不发送成功 UI 更新。
- `EvolveCode` 在保存后的 `after_handle` 唯一请求进化关闭。
- `Enter/ExitMultiAgent` 主体只准备材料，`after_handle` 执行子Agent关闭（进入时）、目标 Loop 构造与 SessionManager 交接，完成后立即停止旧轮次。

公开 schema、危险等级、可用范围和工具名称按原声明保留。

工具来源包括：

- `component/tools/` — 核心工具
- `component/extools/` — 扩展工具
- `component/multiagenttools/` — 多代理工具
- `component/browser/` — 浏览器控制工具
- `component/automation/` — 桌面自动化工具
- `custom_tools/` — 用户自定义工具（若目录存在）
- MCP server — 由 `MCPSystem` 连接和注册远程工具；`component/mcp_tools.py` 仅显式声明管理工具

### 核心工具（`component/tools/`）

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
| `clipboard_display_tools.py` | `UpdateClipboardDisplay`, `ClearClipboardDisplay` | 剪贴板展示 |
| `show_tool.py` | `ShowTool` | 查看工具/工具集元数据；可见性按当前 Loop 口径分派，子Agent（SubAgentLoop/TaskAgentLoop）按动态口径（已加载工具集 ∩ scope ∩ check_fn）返回，与各自 LLM 工具表一致 |
| `list_uploads.py` | `ListUploads` | 列出上传文件 |
| `compress_history.py` | `CompressHistory`（`CompressHistoryTool` + `TOOLSET`） | 会话历史压缩：`handle` 只校验参数并把 `summary`、保留轮次起点登记为调用态材料；结果提交后的 `after_handle` 重新扫描历史，把旧轮次替换为 Agent 撰写的会话摘要，并把保留轮次内的完整工具链重打包为伪造的 `CompressedToolChain` 调用 + 工具链摘要 Profile 生成的链摘要（`no_timeout`）。摘要模型调用前发「正在压缩历史...」，替换、`save_history()` 与 `reset_context_tokens()` 成功后发「压缩完成」；链摘要任一步失败直接传播、历史不变。排除当前调用所在链，故当前轮不被压缩 |
| `compress_tool_chains.py` | `CompressToolChains`（`CompressToolChainsTool` + `TOOLSET`） | 无业务参数；`after_handle` 在自身结果提交后扫描全部历史中的完整工具链并替换为链摘要，不截断轮次或插入会话摘要；普通用户消息与不带工具调用的回复保留，未完成链及纯压缩占位链跳过；本次调用自身所在链此时已完整，可一并被压缩（D11）。`core` / `MAIN` / `critical` / `no_timeout`，无符合条件链时更新已保存结果为零计数且不写历史 |
| `session_variables.py` | `ReadSessionVariables` | filesystem工具集的safe整池只读工具；按ToolContext.resource_session_id读取全部数字/字符串、meta和问题，写入仍使用通用文件工具 |
| `session_search.py` | `SessionSearch` | 会话内容搜索 |
| `lsp.py` | LSP 诊断 | LSP 服务器进程管理与代码诊断 |

### 压缩工具共享逻辑

`tools/_history_compression.py` 是两种压缩工具共享、无 History 副作用的模块：

- `prepare_tool_chain_replacements(messages, *, session_id, metadata_service, start_index=0, excluded_tool_call_ids=None)` 返回非持久化 `ToolChainReplacement` 列表，不修改 History。任一链的 tool_call_id 命中 `excluded_tool_call_ids` 时整条链跳过：`CompressHistory` 传 `{当前 tool_call_id}` 保护本轮，`CompressToolChains` 传空集合扫描全历史（含本次调用自身）。该消息后纯类型定义于 `entity/puretype_after/session.py`，通过 `entity.puretype_after` 显式导入，直接引用正式 `BaseMessage`，不由工具模块调用 `model_rebuild` 补装配；只有索引字段的 `ToolChainSpan` 仍属于消息前纯类型。
- `collect_tool_call_ids(messages, ranges)` 收集给定半开区间 [start, end) 内的真实 tool_call_id，供 after 保留内部移除事实及 suppress 资格校验；前端由独立 history_updated 指令重载，不按该列表重构正典历史。

链摘要统一由 `SessionMetadataService.generate_tool_chain_summary()` 生成，未设置工具链摘要 Profile 时回退目标会话活动 Profile。阈值复用 `TOOL_CHAIN_COMPRESS_MIN_CHARS`（4000 字符），不新增配置或模型用途引用。

两个工具的 `handle` 都不修改 History：`CompressHistory.handle` 只做参数边界校验并把 `summary`、`keep_start_idx` 作为调用态材料登记到 `ToolExecution.state`（业务错误时该材料为空，after 直接返回空效果）；`CompressToolChains.handle` 不接收业务参数。摘要准备、替换、保存、计数通知全部在结果写入并保存后的 `after_handle` 中执行：按 `start_index`/`excluded_tool_call_ids` 重新检测并预生成全部链摘要，任一摘要失败或期间协作式中断都直接传播、不提交压缩；全部摘要成功后才按逆序 `History.replace_range()`（`CompressHistory` 随后 `truncate_from(keep_start_idx)` 并在头部插入摘要消息），再 `save_history()`、`reset_context_tokens()`、完成通知。保存错误沿已有 History 生命周期传播，不声称写盘失败会自动回滚已修改的内存。

两者返回 `ToolPostprocessEffect`：`replacement_result` 携带 `success`、`tool_chains_compressed`、`messages_removed`（消息数净减少量）、`remaining`（压缩后的 History 消息数），由 post-commit 通道同步更新已保存的工具结果与通知（无符合条件链时为零计数，避免遗留 `_compression_pending` 占位）；`discarded_tool_call_ids` 为被替换/截断区间内的全部真实调用 ID，仅用于内部移除事实与 suppress 资格校验，不再作为丢弃批次后缀的协议发送。真实压缩保存成功后同步调用 `execution.mark_history_updated()`；ToolPostprocessor在必要结果回填保存后发送独立 `history_updated` 指令，前端完整重载骨架与按需正文。原完成系统通知通过效果的 `system_message` 延至指令后发送，取消/失败不发成功通知；保存成功后的取消仍根据调用级标记尝试发失效指令。`CompressToolChains` 仅当自身 ID 被 discard（自身链被替换）时 `suppress_tool_result_event=True`，此时不更新自身结果（该结果已随链离开 History，收尾通道会拒绝更新已移除的消息），否则正常更新并发送工具结果；`CompressHistory` 的当前调用位于保留轮次且其链被排除，因此始终不 suppress、始终更新自身结果。

链内工具调用消息的正文及媒体也会被摘要替代，只有链外消息保持原样；字符阈值不保证摘要 token 数一定更少。

两工具的 `critical` 在手动/脱手模式由用户审批，YOLO 模式免审批。`MAIN` 范围保留普通模式和随意聊聊会话，不向多Agent模式、子Agent或临时Agent扩展。本次没有新增 UI 事件或工具集；源码已实施，未运行构建、校验或应用验收。

### 会话变量工具

`ReadSessionVariables` 位于filesystem工具集，需先LoadToolset加载，safe、EVERY、同步handler由既有ToolRegistry执行器持有。没有会话选择参数，普通子Agent/临时Agent读父主会话池；临时Agent仍仅已加载∩TASKAGENT∩safe。service由`get_system(AgentspaceService).session_variables`取得，读取的每个明确文件登记既有回复轮次接触，不锁整树，不创建UI事件。

返回完整原值、raw_value、raw_metadata、normalized metadata、条目/池级issues及scan_complete；工具与REST复用read_pool。无法完整扫描时显式诊断，池级预算拒绝返回error，不返回伪空列表。写入通过Read/Write/PatchEdit管理`ws:sessions/<sid>/variables/`中的JSON标量与同级.meta，数值限制仅提示，percent=true仅显示×100。主Agent统一共享结算，不提供原子增减或聊天回滚。

### 多模态能力生命周期（S14）

Read的能力缓存查询、自动探测与转发经 `get_system(ModalityCapabilitySystem)` 调用；System持有共享锁、探针媒体、缓存路径和完整请求任务，纯媒体内容块构造仍从模块导入。关闭封闭新模型请求并等待六路子探针真实结束后再释放锁；明确停止和生命周期异常不得转换为普通工具结果。缓存与Read的媒体协议保持。

### BrowserSystem 生命周期迁移（S13）

`component/browser/system.py::BrowserSystem` 依赖 RuntimeSystem，唯一持有 Playwright、CDP连接、当前端点及应用启动的无头进程。virtual_awake不加载Playwright或启动浏览器；工具运行期通过get_system(BrowserSystem)查询，原_connection仅保留无状态探测、标签页定位与DOM函数，常量由entity/constant/browser.py导出。

连接请求经TaskOwner.run_request管理并以连接锁串行化，部分连接失败释放已取得资源。断连及原生进程回收各有明确持有的清理任务，取消调用方等待不取消真实释放；关闭超时/失败上报并保留资源引用。多次无头启动保留每个自有进程句柄，不覆盖丢失旧进程；只有这些登记进程会被终止，用户自己启动的浏览器不被杀死。最终注销先停止请求，再尝试独立资源释放并传播全部失败，main.py不再重复cleanup。工具handler任务与其他浏览器操作先由ToolRegistry收尾，应用级关闭编排由 Application 统一执行。

### LSP 工具生命周期

LSP工具与文件修改后的诊断附加统一通过 `Application.current().get_system(LSPManager)` 调用。System唤醒只绑定Runtime主loop与Sandbox，pyright仍由LSPStart按需启动；工具不再传入Sandbox或创建独立manager。启动/替换和关闭均确认进程及reader线程实际结局，关闭失败传播，main.py不再执行另一套cleanup。

### Read 正文单行限制

`Read` 的可选参数 `max_line_chars` 默认 1000，只接受大于等于 1 的整数；可以显式提高或降低，没有关闭值或额外硬上限。handler 在路径解析之前校验所有分支的参数：bool、浮点数（包括 1000.0）、字符串、null、0、负数、数组和对象均返回 `max_line_chars must be a positive integer`。只有省略参数才使用默认值；合法值在目录和媒体分支中忽略，不影响它们的返回结构。

文本先按 `offset`/`limit` 分页，再由 `system/text_preview.py::truncate_lf_lines` 逐行处理展示内容。函数没有 I/O，只复用 `system.text_codec` 的 LF 分行/行尾处理，不改变 `Sandbox.read()` 的原文读取和内部 `limit=0` 路径。正文按 Python str 的 Unicode 码点计数，不按字节或字素簇计数；空格、制表符及孤立 CR 计入，LF/CRLF 行尾不计入，组合字符或 ZWJ 序列可能在边界处被切开。

超限行保留前 N 个码点，附加 ` ... [truncated]`（含前导空格），再接原行尾；标识和行尾不占 N 的额度。未超限行保持原文，不插入行号、不折行、不补末尾换行；仅 LF 分行，保留原有 LF/CRLF。成功文本结果增加：

- `max_line_chars`：本次有效上限。
- `truncated`：本次正文是否至少一行发生字符截断，非分页状态。
- `truncated_lines`：实际截断行在原文件中的绝对 **0-indexed** 索引，和 offset 口径一致；未截断时为空列表，原文已有标识不影响判断。

空文件或 offset 到达/越过 EOF 时正文为空、`truncated=false`、截断索引为空列表。`total_lines`、`remaining` 均在展示截断前按原文统计；`remaining=0` 仍可同时 `truncated=true`。例如无末尾换行的 `abcdef`，上限 3 时返回 `abc ... [truncated]`，截断索引为 `[0]`。需要完整长行时保持 offset/limit 并显式提高有限的 max_line_chars 重读；没有字符 offset 续读或无限制模式。

截断标识不是原文件内容，截断行不是完整原文；使用 PatchEdit 时不得把人工标识当作匹配或写回内容，也不得把可见前缀误当成整行。PatchEdit 的内部完整读取、原文匹配和写回行为不变。

单行保护不保证结果总量有界，也不减少 Sandbox 全文件读取、解码及重复计行的内存/I/O 开销。目录条目、媒体载荷及转发描述、自动附带 `meta` 均不应用该限制，未添加上述文本结果字段。显式把 `.meta` 作为文本目标则应用该限制，详见下节。

### Read 元数据文件

仅 `Read` 支持自动附带元数据文件：目标完整名称追加 `.meta`，例如 `ws:a.md` 对应 `ws:a.md.meta`，`ws:docs/` 对应同级 `ws:docs.meta`，不是目录内部的 `.meta`。命名空间根目录（含等价当前目录写法或指向根目录的别名）不附带元数据；显式读取后缀为 `.meta` 的目标不继续嵌套。后缀识别不区分大小写，自动查找统一追加小写 `.meta`。

- 目录列表隐藏后缀匹配且为文件的条目，保留同后缀目录；`count` 为过滤后数量。`Sandbox.list_dir`、SearchFiles、Grep、Agentspace 文件树和写入/移动/删除工具不变。
- `system/file_metadata.py::parse_meta_content(content)` 是不执行 I/O 的共享解析入口。独立成行的 `[key]` 开始字段，键名不 trim、区分大小写，不允许空/纯空白键或键内方括号、CR、LF。标记行外侧没有空白；LF/CRLF 为行界，孤立 CR 仍是内容。
- 每个值一直延续到下一个键标记或文件末尾，缩进、空行、CRLF、孤立 CR 与末尾换行原样保留。独立的 `[text]` 是新键，不提供转义语法。
- 空文件或全空白文件得到 `{}`；无值键得到空字符串。重复键、非法的整行方括号标记、首个键前的非空文字抛带行号的 `MetaFormatError`，不返回部分解析字典。
- 文本、图片、音频、视频和目录成功结果均可包含普通 `meta` 字段：正常为 `dict[str, str]`，缺失省略，读取/登记/解析失败为错误字符串，不影响原目标结果；不同于内部工具统计字段 `_meta`。
- 自动附带的元数据经 `Sandbox.resolve_read` 与 `Sandbox.read(limit=0)` 完整读取和现有编码探测，不使用正文 offset/limit/max_line_chars；显式将 `.meta` 作为 Read 文本目标时，正文应用分页和单行字符限制，仍不查找 `.meta.meta`。明确 `ws:` 元数据文件登记当前回复轮次文件接触，登记失败不读取。各媒体 `_blocks`、`_user_blocks` 和转发 description 保持不变。
- 当前只返回元数据，不解释或执行键的业务含义，不自动生成或随移动/删除维护文件。会话视觉源目录的 `redirect` 字段由会话视觉资源服务按单层规则消费；`Read` 仍只返回原目录元数据，不跟随目标目录。

### 扩展工具集（`component/extools/`）

| 工具文件 | 用途 |
|----------|------|
| `web_fetch.py` | 获取指定 URL 的网页内容 |
| `cron_tools.py` | 一次性/周期性后台定时任务 |
| `dynamic_endpoint_tools.py` | 动态端点工具（仅参数解析与 `DynamicEndpointSystem` 结果适配） |

`component/dynamic_endpoints.py::DynamicEndpointSystem` 是依赖 `RuntimeSystem`、`SessionManager` 的 framework `AsyncSystem`，唯一持有动态端点字典、锁和 `dynamic_endpoints.json`。`virtual_awake` 严格恢复合法记录，缺失会话只跳过内存加载但保留磁盘条目；损坏文件、非法记录和持久化失败直接传播。工具、Gateway、会话删除和旋转只通过 `get_system(DynamicEndpointSystem)` 调用公开实例方法。`close_admission()` 只停止新注册、迁移和显式注销，不删除持久端点配置；永久删除会话的清理由独立公开清理方法负责。
| `archive_tools.py` | 归档工具 |
| `diff_tools.py` | diff 工具 |

> **已移除的工具**：CSV / Excel / DOCX / PDF / 音视频处理 / 浏览器自动化 / GUI 自动化 / 图表生成等文档与媒体处理能力已从 extools 中移除。这些能力应通过 skill 实现（在 `pre-skills/` 或 `skills/` 中编写对应的 `SKILL.md` 和辅助脚本）。

### 多代理工具（`component/multiagenttools/`）

详见 `../subagent/DEV-README.md`。子Agent和临时Agent没有应用层数量上限；启动成功返回 `success` 与 `session_id`，不再返回旧排队字段。停止普通子Agent时通过 `session_path` 返回历史路径；停止响应不含旧队列晋升记录或排队提示。

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

---

## Shell会话工具集

`ShellInfo.termination` 使用 `natural`、`forced`、`error` 区分 Shell 终止方式；`exit_code` 仍仅表示被托管进程的退出码，`StopShell` 返回 `stopped=true` 时不因非零退出码失败。输出规范化器折叠 PowerShell/PSReadLine 的 CR、退格和 CSI 重绘，启动阶段先等待当前 PTY 的初始输出稳定再写首条命令。

powershell/pwsh 使用 `-NoProfile`，并在启动阶段通过内部 `-Command` 优先尝试移除 PSReadLine；移除失败时回退为关闭预测。第一阶段不提供 PowerShell 历史、预测、方向键等行编辑能力。Shell 单行输入使用单独 CR（`\r`）提交。Agent 使用显式 `EVOLVE_PYTHON` 和 namespace 环境变量，不依赖用户 Profile 中的别名、函数或自动激活环境。

ShellManager 使用 pywinpty 高层 `PtyProcess` 的 socket reader；通过受保护的 `PYWINPTY_BACKEND=0` 环境切换强制 ConPTY，停止使用 `close(force=True)`，不直接依赖低层 PTY 读取/关闭 API。每个原始输出块都会刷新活动时间；无换行提示符在静默窗口后提交并立即以 `quiet` 返回，不等待 30 秒硬截止。Shell会话跨命令和回复轮次复用；单条命令完成、读等待超时或当前回复结束均不要求 `StopShell`，只有明确需要终结整个 Shell 时才调用。单个 Shell会话的原生 PTY 控制调用使用独立同步边界；停止先终止托管进程并等待 reader 收尾，再关闭 PTY，超时路径记录诊断日志且不把 reader 的阻塞读取包在控制锁内。

旧 `RunCommand`、`RunPython`、`InstallPackage`、`StartBackgroundService`、`StopBackgroundService`、`StartWatchingService` 及 `python`/`background` 工具集已移除；内部 `SubprocessRunner` 继续供验证、搜索等基础设施使用。

## 全局动态沙盒空间工具集

- `sandbox` 是 fast-only 的按需加载工具集，不属于默认 `core`；主Agent先通过 `LoadToolset` 加载。
- `AddSandboxSpace` 要求显式提供名称、规范化绝对路径、用途描述、`is_readonly` 和审批原因；同名同配置幂等，同名不同配置拒绝覆盖。
- `RemoveSandboxSpace` 按名称撤销后续逻辑路径解析；缺失名称幂等。
- 两个工具均为 critical：手动/脱手模式由用户亲自审批，YOLO 按全局语义自动批准。
- 普通模式与多Agent模式主Agent可修改；非主参与Agent不接收工具定义且 handler 二次拒绝。随意聊聊会话的工具集白名单有意不包含 `sandbox`。
- 已配置空间由 fast 模式所有 Agent 共享。动态只读与内置只读空间一致，只限制标准 Sandbox 文件 API，不是 Shell/Python/后台进程的 OS 级 ACL。

## Agentspace 文件接触登记

内置工具通过 `ToolContext.agentspace_access()` 把明确的 `ws:` 路径登记到当前 Agent 回复轮次：

- `Read` 与单文件 `Grep` 登记精确文件；目录读取/搜索不锁整树。
- `Write`、`PatchEdit` 登记目标；`Copy`、`Move` 同时登记源和目标；目录 `Move/Delete` 使用递归锁。
- `StartShell` 在 `cwd` 为 `ws:` 时登记当前回复轮次的递归 cwd；Shell会话返回后继续运行，因此该登记不宣称覆盖后台阶段。
- 登记失败时工具 fail-closed；非 `ws:` 命名空间保持原行为。
- `Delete` 的 schema、危险等级、审批和永久删除行为完全不变。Agentspace 垃圾桶只属于网页编辑器的用户删除 API。
- custom tools、MCP 和绕过应用的外部进程无法可靠事前识别路径，由 watcher 与版本冲突机制处理，不宣称预锁。

---

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
- `initialize_session()` 只接受新会话 ID并初始化手动模式，不提供来源会话复制能力。普通新会话、自动延续、单源分支、多父合并及首次创建“随意聊聊”均使用该入口。
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

固定说明分别位于 `templates/base.txt`（主Agent）、`templates/multiagent/multi_agent_system_prompt.txt`（全部多Agent参与者）和 `templates/subagent/subagent_system.txt`（普通子会话）。普通子会话使用不同审批出口，详见 `subagent/DEV-README.md`；临时Agent保持无系统提示词和 safe-only 权限。本次说明纠正不改变 `session_meta_hook` 的模式状态传递方式。

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

- `CronRouter` 已改为依赖 RuntimeSystem、Sandbox、SubprocessRunner 的 AsyncSystem，经 `get_system(CronRouter)` 访问。`_CronTask` 与原时间解析迁至 `component/cron_tasks.py`；工具层只解析参数、调用公开 `schedule_task/reschedule_task/list/trigger/cancel` 方法并适配结果，不读取注册表或调用私有调度/持久化。
- `virtual_awake` 严格加载原 JSON 并校验身份/调度；缺文件可初始化，已有文件损坏或任务非法直接失败。此阶段不安排 Timer；全应用 RUNNING 后由 `activate` 开放调度。
- Timer 直接执行单次命令，所有真实 Timer（含已取消尚未退出）保留在实例集合中，只有 join/实际结束确认后移除。回调登记、立即触发与冻结受接收边界和实例锁协调；已被替换/取消的 Timer 不能执行另一轮。任务与运行中命令分别登记，删除会话或取消任务不会丢失尚在执行的进程所有权。
- 命令统一通过 SubprocessRunner 执行，使用独立 `CRON_PROCESS_SESSION_PREFIX` 键；关闭先冻结和终止命令，再在线程中 join 全部 Timer。期限内未结束保留资源、错误汇总传播；不以清空集合宣告成功，主事件循环不阻塞 join。
- 全局冻结不修改持久 `should_schedule`；已实际执行的一次性任务才提交计数/结束状态。JSON 快照及原子写全过程使用同一锁，持久化失败报告生命周期失败；会话迁移在同一锁内更新所属会话，继续持有正在运行的任务。关闭后的迟到输出仅保留执行结局/日志，不向模型投递新工作。
- 结果仍经主会话队列或子会话 Inbox 投递；输入投递记录及只落History关闭在 S16/S17 完成，激活/停止由 Application 统一编排。REST 协议保持 `/api/sessions/{id}/cron-tasks/...`。
- `entity/puretype/extools.py::CronTaskInfo` 增加只读字段 `is_wait: bool = False` 与 `wait_message: str = ""`，由 `_build_task_info` 显式映射 `_CronTask.is_wait`/`wait_message`（普通 Cron 为 false/空串，不按 name/command 猜测）；不改调度、持久化、审批、Timer 或执行语义。

---

## Read媒体来源与主会话发送开关

Read原有能力路由、审批与返回结构保持；`prepare_tool_result`把tool_call_id传给 `tool_result_to_content` / `tool_result_to_follow_up`，实际媒体块记录逻辑path和来源工具ID，不采信absolute_path。user路径follow-up虽然是system角色用户消息，也有可定位的独立媒体实例；客户端传入的内部media_id/send_multimodal/verified不被blocks_from_dicts采纳。

主会话媒体输入Tab控制已经进入History的独立块，不禁止重新Read；每次重新Read的新块默认开启。关闭不会删除原媒体，不影响自定义ReadForward明确把媒体发给指定Profile的用途，也不改变工具集权限或审批。

ModalityCapabilitySystem新 `describe_media_block`返回结构化成功描述/明确不可用；只对明确UnsupportedModality或窄400模态拒绝允许不可用，网络/认证/超时/未知400/空描述失败。主请求准备只缓存成功描述，不再把旧错误模板当成功文字。原Read的 `forward_modality_to_ref_profile`仍返回原str/错误模板协议，正式媒体描述请求复用共享单跳调用，旧空媒体文字提示分支保留；不把工具旧返回格式扩展为本次新REST类型。

旧描述字段未证明成功时，主会话需要描述会重新取得一次成功结果。关闭仍允许向转发模型发原媒体，不是所有模型的隐私禁传。已实施，未运行验证。

---

## 会话视觉资源重定向

`stage/`、`site/` 与 `chat-style/` 的源目录可以使用同级 `.meta` 文件的 `[redirect]` 字段复用其他逻辑目录。服务端只解析源目录一次，合法目标由稳定视觉入口通过 HTTP 307 使用；缺失或非法配置静默回退源目录。前端 Hook 不解析 `.meta`，只消费最终入口并通过 Agentspace 事件与 HEAD 版本探测刷新。会话状态 REST 和根目录 `custom_hooks/session_meta_hook.py` 可读取三项非持久化视觉资源状态。`Read` 对源目录保留原始元数据语义，并只将非法 `redirect` 原因放入 `meta.redirect`。