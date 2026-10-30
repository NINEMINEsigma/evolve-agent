# 背景
文件名：2026-10-30_3_builtin-tools-package-migration.md
创建于：2026-10-30_16:38:04
创建者：desktop-lui19un\13716
主分支：master（用户提供的起始快照）
任务分支：不创建；Git 只读，仅允许 diff/log
当前 RIPER-5 阶段：RESEARCH；用户已明确授权先建立任务文件，尚未授权 PLAN 或 EXECUTE。

# 任务描述
用户最初要求：把内置工具代码迁移到 origin_agent/buildin_tools，component 目录留给架构的 Component 类型相关实现。

用户随后收窄本次范围：主要需要把 origin_agent/component/tools、origin_agent/component/multiagenttools、origin_agent/component/extools、origin_agent/component/browser、origin_agent/component/automation 这五个子包及必要内容迁出 component，移动到 buildin_tools 中。

用户本轮指令：先建立任务文件。

# 项目概览
origin_agent/ 是唯一持久化运行源码。内置工具当前分布于 component 下五个子包，通过 BaseTool 子类和模块级固定名称 TOOLSET 声明，由 ToolDiscoverySystem 发现并交给唯一 ToolRegistry 注册。运行期业务服务通过 Application 的接口槽位查询；工具名称、工具集名称、审批权限和生命周期均有既有契约。

本次目录名严格采用用户指定的 buildin_tools，不改为其他拼写。本任务与上一项 Runtime 属性及关闭准备任务独立，不修改其任务记录。

⚠️ 警告：永远不要修改此部分 ⚠️
- RIPER-5 与 Cursor 交互模式互不等同；当前保持 RESEARCH，未经用户明确授权不进入 PLAN 或 EXECUTE。
- 本轮只建立任务文件；正式源码及开发文档只读，不移动、复制、删除或修改正式文件。
- 后续任务记录只追加，不改写既有分析、决策或计划；仅当前执行步骤指针允许原地更新。
- 禁止运行校验、测试、构建、实际导入或启动应用；禁止在 origin仓库新增测试代码或测试专用入口。
- 禁止读取、搜索或修改 workspace/ 下代码；本任务未获运行时数据访问授权，也不操作运行时副本。
- third/ 只读；Git 仅允许 diff/log，不创建分支或执行任何 Git 写操作。
- 禁止批量编辑脚本；保留任务之外的用户修改。
- 实施前先完成对应开发文档阅读；若目录职责、发现约定或公共导入发生变化，同步更新受影响开发文档。
⚠️ 警告：永远不要修改此部分 ⚠️

# 分析

## 已确认的需求边界
以下为用户要求的目标对应关系，仅记录范围，不构成已批准的实施计划：

| 当前目录 | 目标目录 |
|---|---|
| origin_agent/component/tools/ | origin_agent/buildin_tools/tools/ |
| origin_agent/component/multiagenttools/ | origin_agent/buildin_tools/multiagenttools/ |
| origin_agent/component/extools/ | origin_agent/buildin_tools/extools/ |
| origin_agent/component/browser/ | origin_agent/buildin_tools/browser/ |
| origin_agent/component/automation/ | origin_agent/buildin_tools/automation/ |

保留五个子包名称及内部结构。必要内容包含包入口、包内共享模块，以及因目录迁移受到影响的导入路径、工具发现配置和开发文档。browser/system.py 与 browser/_connection.py 均在 browser 子包内，已在上一轮回复中纳入该包迁移范围；用户未提出异议，具体改动仍待 PLAN 明确。

本次不扩大为整个 component 的职责重构。component/approval/、component/cron_router.py、component/cron_tasks.py、component/dynamic_endpoints.py 与 component/mcp_tools.py 不属于五个目标子包，当前范围中保留原位；必要的跨包引用调整仍需调查。

## 已完成的前置阅读
已先读取 .gitignore、config.py、run.py，再按顺序读取根目录 DEV-README.md、DEV-glossary.md、DEV-class_relationships.md；部分大型文档返回曾被工具截断，后续对相关章节进行了分段补读，未声称完整读取全部正文。随后读取 component/DEV-README.md、abstract/DEV-README.md，以及 system/DEV-README.md 的相关内容。后续深入其他目录前仍需先读取各自开发文档。

已读取开发助手AI侧 RIPER 公共规则和 RESEARCH 规则；尚未进入 PLAN。未读取 workspace/ 代码或运行时数据。

## 已确认的源码事实
1. origin_agent/entity/constant/tools.py 中 BUILTIN_TOOL_PACKAGES 固定列出 component.tools、component.extools、component.multiagenttools、component.automation、component.browser；MCP_TOOL_MODULE 单独指向 component.mcp_tools。
2. origin_agent/abstract/tools/discover.py::ToolDiscoverySystem.virtual_awake 按 BUILTIN_TOOL_PACKAGES 顺序解析物理目录并发现工具，随后处理可选 custom_tools，最后显式注册 MCP_TOOL_MODULE 和工具集元数据。缺失内置目录会失败，迁移需同时考虑逻辑模块名与物理目录。
3. 五个子包包含工具主体之外的包入口和共享模块，例如 tools/_file_changes.py、tools/_history_compression.py、multiagenttools/profile_builder.py、browser/_connection.py 和 browser/system.py。
4. origin_agent/system/application.py::_build_system_manifest 当前从 component.browser.system 导入 BrowserSystem；其 IBrowserSystem 注册槽位与业务生命周期不因用户的目录迁移要求自动改变。
5. multiagenttools/profile_builder.py 被 gateway/session_manager.py 和 entry/multi_agent_loop.py 直接导入，也被多Agent进入工具使用，不是仅由工具发现入口访问的文件。
6. browser 下各工具当前从 component.browser 导入 _connection；automation/mouse_drag.py 从 component.automation.mouse_click 导入共享内容；两个历史压缩工具从 component.tools._history_compression 导入共享内容。
7. extools/cron_tools.py 当前依赖保留原位的 component.cron_tasks，不能将所有 component 引用一律替换为 buildin_tools。
8. extools/diff_tools.py 使用 Path(__file__).resolve().parent.parent.parent 推导当前代码副本根；目录深度与既有路径语义需要在后续计划中明确核对。
9. 当前未发现 origin_agent/buildin_tools 下已有文件；这是文件工具在目标路径返回无匹配的观察，不表示已创建该目录。

## 后续阶段仍需确认的事项
- 五个包的完整文件清单及 origin仓库以外受影响的源码、预置技能或文档引用；搜索必须限定允许目录，不能探查 workspace/。
- 新旧包入口的处理方式，以及旧路径是否保留兼容层；用户尚未批准具体方案。
- 开发文档拆分边界：component 的保留职责与 buildin_tools 的五包说明，根目录模块地图、术语表、类关系文档以及其他受影响子包文档。
- 持久化类路径/type token 是否涉及迁移文件；不能未经核对就断言无需存储版本变更，也不能仅因目录改名就修改数据结构或版本。
- run.py 合并覆盖保留目标独有文件的部署影响，尤其旧工具模块残留风险；开发助手AI不自行清理运行时副本。

# 提议的解决方案
尚未制定。本轮只记录已确认需求和研究事实；待用户明确授权进入 RIPER-5 PLAN 后再形成逐项可审查的迁移计划。

# 当前执行步骤："EXECUTE：第1—85项全部完成；仅只读审阅，等待用户部署与运行验收"

# 任务进度

## 2026-10-30_16:38:04 — 建立任务文件
- 授权来源：用户明确要求“先建立任务文件”。
- 新建本文件，登记五个子包的迁移范围、已知发现入口与跨包依赖、约束及待调查事项。
- 未修改正式源码或开发文档，未移动任何目录。
- 未运行校验、测试、构建、实际导入、应用启动或 Git 写操作。
- 当前仍为 RESEARCH，尚无已批准实施计划。

# 最终审查
尚未实施，暂无最终审查结论。

---

# 2026-10-30_16:42:07 — PLAN v1（追加；待审查和用户批准）

## 授权与前文修订
用户通过 /plan 明确授权进入 RIPER-5 PLAN，并要求补读代码、制定精确规范、写入现有任务文件及调用 generalPurpose 进行计划审查。本节替代前文“尚未授权 PLAN”“尚未制定方案”的当前状态；前文作为历史原样保留。EXECUTE 仍未授权，本轮只可更新任务文件。

本计划严格保持五个子包整体迁移范围。BrowserSystem 和共享模块随所属包移动，不额外抽取到 system/ 或 entry/，也不将审批、Cron 或 MCP 模块移入 buildin_tools。component/ 本次仍保留这些历史模块；“留给架构 Component”是后续目录方向，不能宣称本轮已经清空 component/ 或完成所有职责重构。

## P1. 架构与兼容策略

- origin_agent/buildin_tools/ 新建普通 Python 包，增加空 __init__.py；入口不重新导出工具、不注册 TOOLSET、不导入 BrowserSystem 或访问 Application。
- 原 component 下五个子包完整迁至 buildin_tools 下同名目录，文件名和目录深度保持不变。逐文件保留正文、编码及换行；只有 P3 明列的导入、注释、包说明与目录引用允许更改。
- origin仓库旧五包不保留源码、转发入口、重复 TOOLSET、兼容别名或 sys.modules 注入；component/__init__.py、approval/、cron_router.py、cron_tasks.py、dynamic_endpoints.py、mcp_tools.py 均保留。
- ToolDiscoverySystem 仍扫描 tools → extools → multiagenttools → automation → browser，只改变五个包的完整模块前缀；custom_tools 处理顺序、MCPRefresh 显式注册以及工具集元数据注册顺序保持。
- 所有工具名称、toolset 名称、schema、危险等级、availability、check_fn、requires_env、no_timeout、accepts_following_calls、preheat 及 before/handle/after 行为不变。模块级工具对象仍由唯一 Registry 共享持有，不能因迁移增加第二份注册或连接。
- BrowserSystem 继续实现 IBrowserSystem，并由原 Application 清单装配；仅具体实现模块导入改为 buildin_tools.browser.system。21个接口槽位、依赖图、Runtime 属性、关闭准备、Logger 根级联及5秒硬截止全部保持。
- 现有外部源码调用方一并更新。不承诺未知第三方扩展继续使用旧 component.* 导入；部署说明明确旧 Python 导入路径已失效，外部未纳入清单的依赖需由用户同步迁移。
- 所有正式文件迁移仅在用户授权 EXECUTE 后执行；使用专用文件读取、写入、删除工具逐文件完成，不使用批量编辑脚本、Shell 文件搬移或 Git 写操作。每个文件先读取最新原文、写入并只读对照目标，再定向删除原文件；目标已存在且非本任务产物时停止并报告，禁止静默覆盖。空旧目录不含源码，不额外调用终端删除目录。

## P2. 完整文件迁移清单

以下全部路径相对 origin_agent/；每一行的旧前缀为 component/，新前缀为 buildin_tools/。本次观察为61个 Python 文件，没有发现五包内其他类型资源。执行前逐项核对最新清单，若出现新增正式文件或与范围冲突的内容，先报告并追加计划修订，不能自行漏掉或扩大迁移。

| 子包 | 完整文件名 | 文件数 | TOOLSET 声明模块数 |
|---|---|---:|---:|
| tools/ | __init__.py、_file_changes.py、_history_compression.py、ask_question.py、code.py、compress_history.py、compress_tool_chains.py、filesystem.py、frontend.py、list_uploads.py、load_toolset.py、lsp.py、progress_tools.py、refresh_identity.py、sandbox_spaces.py、session_search.py、session_variables.py、shell.py、show_tool.py、skills.py | 20 | 17 |
| multiagenttools/ | __init__.py、agents_group.py、approval_subagent.py、chat_subagent.py、enter_multi_agent.py、exit_multi_agent.py、list_subagents.py、profile_builder.py、run_subagent.py、run_taskagent.py、stop_subagent.py、stop_taskagent.py | 12 | 9 |
| extools/ | __init__.py、archive_tools.py、cron_tools.py、diff_tools.py、dynamic_endpoint_tools.py、web_fetch.py | 6 | 5 |
| browser/ | __init__.py、_connection.py、close.py、connect.py、interact.py、launch.py、list_tabs.py、navigate.py、query.py、screenshot.py、system.py、tab.py、wait.py | 13 | 10 |
| automation/ | __init__.py、keyboard_press.py、keyboard_type.py、mouse_click.py、mouse_drag.py、screen_capture.py、template_match.py、window_enum_child.py、window_find.py、window_focus.py | 10 | 9 |

合计50个 TOOLSET 声明模块。此数量是当前正式五包的源码基线，不是执行自动校验得到的结果；不将可选 custom_tools、MCPRefresh 或远程 MCP 模块计入该基线。agents_group.py 是既有未实现入口，原样移动，不补写功能，也不新增 TOOLSET；profile_builder.py、browser/system.py 及其他辅助模块仍按已有 AST 规则跳过。

## P3. 精确修改点与函数契约

### P3.1 发现配置（1个文件）
文件：origin_agent/entity/constant/tools.py。

只修改 BUILTIN_TOOL_PACKAGES: tuple[str, ...] 中五个完整模块名，依次为 buildin_tools.tools、buildin_tools.extools、buildin_tools.multiagenttools、buildin_tools.automation、buildin_tools.browser，并更新紧邻的中文注释。MCP_TOOL_MODULE: str 仍为 component.mcp_tools；其他常量、导出名称和 entity/constant/__init__.py 不变。

origin_agent/abstract/tools/discover.py 不需要源码修改：其 virtual_awake(self) -> None 已从常量取得包名，并使用 agent_dir.joinpath(*package.split('.')) 同时计算新物理目录。discover_builtin_tools(tools_dir: str, package_prefix: str, *, registry: IToolRegistry) -> list[str]、_discover_tools 和 _register_module 的签名、失败规则、路径排序、缓存与显式注册均保持。禁止改成扫描 buildin_tools 根或同时扫描新旧两处。

### P3.2 包内导入（14个文件）
路径均为迁移后的目标路径：

| 文件 | 唯一必要导入调整 |
|---|---|
| origin_agent/buildin_tools/tools/compress_history.py | component.tools._history_compression 改为 buildin_tools.tools._history_compression，保留 collect_tool_call_ids、prepare_tool_chain_replacements |
| origin_agent/buildin_tools/tools/compress_tool_chains.py | 同上，保留原导入符号 |
| origin_agent/buildin_tools/multiagenttools/enter_multi_agent.py | 延迟导入 component.multiagenttools.profile_builder 改为 buildin_tools.multiagenttools.profile_builder，保留 build_multi_agent_tools、build_agent_profiles |
| origin_agent/buildin_tools/browser/close.py | component.browser 改为 buildin_tools.browser，仍导入 _connection |
| origin_agent/buildin_tools/browser/connect.py | 同上 |
| origin_agent/buildin_tools/browser/interact.py | 同上 |
| origin_agent/buildin_tools/browser/launch.py | 同上 |
| origin_agent/buildin_tools/browser/list_tabs.py | 同上 |
| origin_agent/buildin_tools/browser/navigate.py | 同上 |
| origin_agent/buildin_tools/browser/query.py | 同上 |
| origin_agent/buildin_tools/browser/screenshot.py | 同上 |
| origin_agent/buildin_tools/browser/tab.py | 同上 |
| origin_agent/buildin_tools/browser/wait.py | 同上 |
| origin_agent/buildin_tools/automation/mouse_drag.py | component.automation.mouse_click 改为 buildin_tools.automation.mouse_click，保留 _BUTTON_MESSAGES |

filesystem.py 的相对导入 ._file_changes 保持不变。extools/cron_tools.py 继续从 component.cron_tasks 导入 next_cron_time，相关说明中的 component/cron_tasks.py 也保留；这是刻意保留的跨包依赖，而非遗漏。

### P3.3 外部调用方（4个文件）

1. origin_agent/system/application.py：_build_system_manifest(context: RuntimeContext) -> list[tuple[type[AsyncSystem], AsyncSystem]] 只把 BrowserSystem 的具体实现导入改为 buildin_tools.browser.system；不改函数主体、实例数量、接口类型或清单顺序。
2. origin_agent/gateway/session_manager.py：SessionManager._create_multi_loop(self, session_id: str, frontend_sink: IFrontendSink, history_store_dir: Path | None = None) -> IMainSessionLoop 中，延迟导入改为 buildin_tools.multiagenttools.profile_builder；其他逻辑不改。
3. origin_agent/entry/multi_agent_loop.py：MultiAgentLoop.set_profile(self, profile: LLMProfile | None) -> None 中，_resolve_main_agent_prompts 的延迟导入改为 buildin_tools.multiagenttools.profile_builder；不把该导入提升到模块顶层。
4. custom_tools/read_forward.py：仅把 component.tools.filesystem 改为 buildin_tools.tools.filesystem；_guess_mime、_SUPPORTED_MIMES、_SUPPORTED_AUDIO_MIMES、_SUPPORTED_VIDEO_MIMES、_MAX_IMAGE_SIZE、_MAX_AUDIO_SIZE、_MAX_VIDEO_SIZE、_AUDIO_FORMAT_MAP 的符号列表不变。不在本轮抽取新的 MIME 服务或重构既有私有函数依赖；不将该扩展的专属行为写入公共 README/DEV 文档。

读取了 custom_tools/README.md 后才检查该调用方。其顶层直接导入在启动发现时执行，不调整会导致可选扩展存在时导入失败，因此列为目录迁移的必要联动，而非工具行为扩展。

### P3.4 只需更新说明的源码及依赖文件（5个文件）

- origin_agent/buildin_tools/extools/diff_tools.py：只把目录示意注释中的 component/extools/diff_tools.py 改为 buildin_tools/extools/diff_tools.py。原文件与目标均为“代码副本根 / 单层顶包 / extools / 文件”，Path(__file__).resolve().parent.parent.parent 仍恰好到代码副本根；_FAST_ROOT、_ORIGIN_ROOT、_resolve_fork_root() -> Path | None 和比较算法完全不改，不借此处理原先非默认运行布局的潜在问题。
- origin_agent/buildin_tools/tools/show_tool.py：循环依赖说明中的 component → entry/subagent 改为 buildin_tools → entry/subagent；函数主体、延迟导入和可见性策略不改。
- origin_agent/buildin_tools/browser/__init__.py：保留只含包说明的入口，说明工具共享无状态 _connection，真实连接与自有进程归本包 BrowserSystem；不再声称 _connection 持有连接单例，不新增任何导入或对象。
- origin_agent/entry/colloquy_loop.py：仅将顶部包位置说明中的 component/tools、component/extools 改为 buildin_tools/tools、buildin_tools/extools，不改变实际 COLLOQUY_TOOLSET_WHITELIST。
- requirements.txt：仅更新 playwright 前的 component/browser 路径注释为 buildin_tools/browser；依赖名称、版本、平台标记与安装策略完全保持。

component/cron_tasks.py 顶部“从 component/extools/cron_tools.py 迁入”描述的是之前的历史来源，保留原文，不机械改为新的历史来源；当前职责和最新工具调用位置由 component/DEV-README.md 说明。

### P3.5 迁移但不变更的公共与共享签名

迁移不新增、删除或改名任何函数、类、参数或模型字段。下列具有跨包/共享调用的签名特别固定：

- buildin_tools.multiagenttools.profile_builder.build_multi_agent_tools(tool_registry: IToolRegistry) -> list[dict]。
- 同模块 build_agent_profiles(agents: list[str], main_agent_name: str, parent_ctx: RuntimeContext, llm_client_factory: Callable[[str, LLMProfile | None], BaseLLMClient | None], system_prompt_template: str, sandbox: ISandbox, profiles: Mapping[str, CharacterProfile], *, session_id: str = '', skip_missing_subagent: bool = False, main_profile: LLMProfile | None = None) -> dict[str, AgentProfile]。
- 同模块 _resolve_main_agent_prompts(_name: str, _config: AgentConfig, parent_ctx: RuntimeContext, _sandbox: ISandbox, profile: LLMProfile | None = None, session_id: str = '', loaded_toolsets: set[str] | None = None) -> list[str]。
- buildin_tools.tools._history_compression.prepare_tool_chain_replacements(messages: list[BaseMessage], *, session_id: str, metadata_service: ISessionMetadataService, start_index: int = 0, excluded_tool_call_ids: set[str] | None = None) -> list[ToolChainReplacement]，保持 async。
- 同模块 collect_tool_call_ids(messages: list[BaseMessage], ranges: list[tuple[int, int]]) -> tuple[str, ...]。
- buildin_tools.tools._file_changes.FileChangeRecorder.__init__(self, execution: ToolExecution) -> None、is_cancelled(self) -> bool、record(self, operation: SessionFileChangeOperation) -> bool。
- buildin_tools.browser.system.BrowserSystem.__init__(self) -> None、virtual_awake(self) -> None、virtual_prepare_shutdown(self) -> None 均保持原实现；后两者保持 async。IBrowserSystem 的 task_owner、current_endpoint、get_browser、teardown、register_headless_proc、cleanup_headless_browser、close_admission 契约不变，interface/browser_system.py 不修改。
- 全部 BaseTool 子类的 ensure_arguments/before_handle/handle/after_handle 及工具集构造保留现状；不为此次路径迁移增加适配类、代理或装饰器。

## P4. 数据、错误和依赖边界

### 数据与持久化
核对了五包类定义、保存/读取相关引用及 origin_agent/entity/typeref.py。五包内迁移类为运行时工具、BrowserSystem、调用级辅助对象、HTMLParser 或 ctypes 结构，没有迁移 History、LLMProfileData、AgentConfig、SessionApprovalModeState、SessionFileChangesData/Entry/Actor 或 AgentLoopSettingsData。这些正式持久化类仍位于 entity，typeref 不指向五个旧工具包。

工具通过既有服务读写数据，session_search.py 读取既有 SessionStore 和 entity.messages.History；FileChangeRecorder 将 entity 纯类型交给原 Store；压缩材料 _PendingHistoryCompression 明确为调用级非持久化对象。目录迁移不改变存储数据结构、嵌套类型、引用关系或存储语义，因此不迭代 easysave key、不新增旧工具类 namespace 映射、不修改 typeref 或运行时文件。JSON 结果、TOOLSET 声明与模块导入路径是运行时接口，不作为持久化结构变更处理。

### 错误处理
保留现有快速失败：新五包缺失、AST/导入/预热/注册失败、同名冲突均沿原发现路径传播，不增加捕获、空列表、兼容旧包回退或重试。工具业务错误、取消、History 必要保存失败和资源清理 pending 的处理不改。

文件迁移遇到最新内容差异或未知目标冲突时停止当前编辑并报告，不用脚本覆盖或清理未知文件。实施期间代码可能暂不可启动，不运行应用验证“中间态”。

### 依赖
新增的只有 buildin_tools 包层级；没有新增第三方依赖。五包对 abstract、entity、interface、entry、system、util 和保留 component 服务的依赖维持原样。延迟导入位置不变，避免路径迁移顺带改变循环依赖与导入副作用。custom_tools/read_forward.py 同步改用新实现路径；其他已搜索到的正式源码调用方见 P3，历史导出 .docs/*.html 不作源码或当前文档修改。

## P5. 开发文档的精确范围（新增1份、更新9份）

1. 新增 origin_agent/buildin_tools/DEV-README.md：说明五包职责、P2 全文件清单对应的工具来源、TOOLSET 发现、核心/扩展/多Agent/浏览器/自动化工具、调用级共享模块及服务边界。由原 component/DEV-README.md 逐节迁入工具相关约定，包括“工具系统”“Shell会话工具集”“全局动态沙盒空间工具集”“成功文件目标操作记录”“文件修改目录树的记录口径”“Agentspace 文件接触登记”“Read媒体来源与主会话发送开关”“会话视觉资源重定向”。保留压缩、Read 分页/截断/meta、会话变量、LSP、多模态、Browser 的完整现有约定与未验收声明，不因迁移缩略行为规范。原“工具系统”中的 DynamicEndpointSystem 所有权说明保留在 component 文档，新工具文档通过相对链接引用；MCP 工具正文也留在 component，只说明其不属于本次五包发现范围。补充 BrowserSystem 随包但仍为 System 的事实、共享 Profile 构造的外部调用点，以及 no-compatibility 的部署边界。
2. 更新 origin_agent/component/DEV-README.md：目录树移除五包并链接新工具文档，保留 approval/、cron_router.py、cron_tasks.py、dynamic_endpoints.py、mcp_tools.py 和 __init__.py 的职责。保留“审批系统”“MCP 桥接”“Cron 路由”现有规则；独立保留 DynamicEndpointSystem 的恢复/持久化/关闭说明。将“System 接口槽位约定”“Cron故障诊断与最终资源等待”“Runtime 依赖继承”“Runtime 属性与关闭准备”中的 Browser 当前位置指向新文档，对保留的 Approval/Cron/DynamicEndpoint 约定原样保留。明确本次只迁五包，component 暂未完成最终 Component 专用整理；不迁移 ActivityLoggerComponent。
3. 更新根 DEV-README.md：模块地图新增 buildin_tools 行、收窄 component 行；当前源码定位中的五包路径、工具发现“五个 component 子包”文字改为 buildin_tools；开发阅读指引区分“工具 → buildin_tools”和“审批/MCP/Cron/动态端点 → component”。保留审批和 MCP 原路径；新增本次迁移、部署残留、未运行验收说明，不改其他生命周期历史结论。
4. 更新根 DEV-glossary.md：主Agent角色名条目中的 RefreshIdentity 路径改为 buildin_tools/tools/refresh_identity.py；登记“内置工具”对应 buildin_tools 五包的目录锚点，区分可选 custom_tools 与保留的 MCP 管理入口。已有 MCP 桥接条目的 component/mcp_tools.py 不改。
5. 更新根 DEV-class_relationships.md：当前有效的 RunTaskAgent、Shell、LoadToolset、ShowTool、动态空间工具和会话视觉文件工具位置引用新路径；新增“内置工具包迁移（2026-10-30）”记录，说明 BrowserSystem/共享 Profile 位置、外部调用点、无新增类/字段/跨类 protected 访问、无存储格式变化。文件开头明确保留的历史章节以及“关键设计变更记录”中旧模块路径不全局替换；新节明确这些历史路径由本次对应关系更新，不伪造历史事实。
6. 更新 origin_agent/abstract/DEV-README.md：发现五包说明、session_variables 位置、工具具体实现表及工具加载引用改为新包；当前 SkillManager 实现表明确 RecallSkill/CreateSkill 位于 buildin_tools/tools/skills.py，不继续指向已搬迁的 extools。MCP 管理入口与注册契约保留，abstract/tools/discover.py 源码不改。
7. 更新 origin_agent/system/DEV-README.md：BrowserSystem 当前实现位置改为 buildin_tools/browser/system.py，工具发现说明明确五包新前缀和未变的 MCP 独立入口；不改生命周期规则或装配数量。
8. 更新 origin_agent/entry/DEV-README.md：两处共享压缩准备入口定位改为 buildin_tools/tools/_history_compression.py；保留纯检测/替换/保存和 history_updated 协议。
9. 更新 origin_agent/subagent/DEV-README.md：引言、文件结构和 Profile 构造器说明中的 multiagenttools 路径更新，保留子Agent/临时Agent工具权限和持久化语义。
10. 更新 custom_mods/DEV-README.md：只修正第2节“当前实现与可复用部分”的 skills.py 源码路径及第13节职责表中工具目录引用为 buildin_tools/tools；该文件仍为设计草案，不新增 mod 实现、接口、术语或功能清单。

origin_agent/gateway/DEV-README.md 已先读，现有正文未发现五包旧路径，不做无意义修改。README.md、AGENTS.md、custom_tools/README.md 未发现必须变更的旧五包路径；本轮不加入扩展专属工具记录。.docs/ 导出示例、旧 .tasks/ 记录、已有 skills/、workspace/、third/、venv/ 均不迁移、不清理、不改写。

## P6. 部署与验收边界

### 部署说明（供用户执行，不作为开发助手AI命令）
本轮不改 run.py、.gitignore 或复制过滤规则。run.py 对 fast仓库从来不先删除，进化备份和提升也会合并覆盖；因此 origin 移除旧五包不保证运行时副本自动删除旧文件，force_init 对 fast 同样不保证清除残留。

用户需在停止应用后完整部署新 buildin_tools 和全部直接调用方，并在确认保留本地进化内容的前提下，定向处理所部署 fast/slow/fallback 仓库中旧 component 五包。只处理 tools、multiagenttools、extools、browser、automation，保留 component 的审批/Cron/动态端点/MCP 和其他用户内容；禁止以删除整个 component 或整个 workspace 作为默认操作。不由开发助手AI检查或执行运行时文件清理，也不在此引入自动删除/迁移脚本。

### 开发助手AI允许的只读审阅
- 通过专用文件读取/搜索及必要 git diff，对照61个旧/新对应项、空包入口和目标内容；确认五个旧包无源码、没有兼容别名或双份 TOOLSET。
- 核对50个原 TOOLSET 声明模块的内容没有业务变化；五个发现前缀及顺序正确，MCP_TOOL_MODULE 与 custom_tools 顺序未改。
- 在 origin_agent、custom_tools、custom_mods 的当前文档和根开发文档/requirements.txt 定向检索旧五包路径，按“应迁移当前引用/刻意保留依赖/历史记录”分类，不将历史引用等同于运行错误。不得搜索 workspace；不执行静态解析、导入检查、类型检查、测试或其他校验脚本。
- 检查 source diff 仅含迁移、P3 指定导入/注释以及 P5 文档变更；写明“只读审阅完成，运行验收未执行”，不得称测试或构建通过。

### 用户人工运行验收（开发助手AI不代执行）
| 场景 | 人工验收预期 |
|---|---|
| 完整部署并由正式入口启动 | Application 按原21槽位装配，无旧五包导入失败；发现记录仅采用新五包前缀，MCP 管理工具仍来自 component.mcp_tools |
| core 及按需加载 | 首轮 core、LoadToolset 加载 filesystem/shell 等保持，ShowTool/工具集目录/权限过滤不变 |
| 文件工具和 Read 元数据 | ws: 文件 Read/Write/PatchEdit 等既有结果、meta、截断、文件锁和修改记录保持 |
| custom_tools 直接调用方存在 | 现有扩展启动导入成功；不因 filesystem 迁移产生 ModuleNotFoundError，不新增外部模型请求作为强制验收条件 |
| 多Agent首次进入、Profile 切换、会话恢复、退出 | Profile 构造调用均走新路径，无延迟导入失败，原 History/后处理/工具权限保持 |
| browser 可选依赖缺失与已安装 | 缺失依赖仍按原 check_fn 隐藏；已安装时可选 Browser 工具及 IBrowserSystem 装配/关闭保持，不误杀用户浏览器 |
| automation 与跨模块鼠标内容复用 | 支持的平台和依赖下工具可加载，mouse_drag 共享常量导入无旧路径；不要求实际点击作为自动验收 |
| diff 工具 | 代码副本根、origin 和 fork 对比目标保持，不把 buildin_tools 误判为代码副本根 |
| 关闭及后续进化部署 | 原 Runtime 关闭准备与资源所有权保持；新旧代码不在运行进程内混装，用户按部署说明处理旧目录残留 |

本计划没有任何开发助手AI应运行的校验、构建或启动命令，也不在 origin仓库创建测试源/夹具/配置。人工验收失败由用户报告后另行调查，不能以源码静态审阅代替运行结果。

## P7. 编号实施清单（仅待用户授权 EXECUTE 后执行）

下列“迁移 X”严格表示将 origin_agent/component/X 逐文件迁为 origin_agent/buildin_tools/X，并按 P3 只做该文件已列出的必要修改；每项是一个文件的逻辑迁移，不是批量脚本。迁移项由执行时最新原文写入目标并核对后删除原文件；整个实施过程不得启动应用。P2 是完整对应清单，P3/P5 是各项的详细约束。

1. 核对 EXECUTE 授权与最新正式文件清单，确认本计划适用且无未知目标冲突。
2. 新建 origin_agent/buildin_tools/__init__.py，保持空入口。
3. 迁移 tools/__init__.py。
4. 迁移 tools/_file_changes.py。
5. 迁移 tools/_history_compression.py。
6. 迁移 tools/ask_question.py。
7. 迁移 tools/code.py。
8. 迁移 tools/compress_history.py，按 P3.2 更新共享模块导入。
9. 迁移 tools/compress_tool_chains.py，按 P3.2 更新共享模块导入。
10. 迁移 tools/filesystem.py，保留相对导入及全部文件工具行为。
11. 迁移 tools/frontend.py。
12. 迁移 tools/list_uploads.py。
13. 迁移 tools/load_toolset.py。
14. 迁移 tools/lsp.py。
15. 迁移 tools/progress_tools.py。
16. 迁移 tools/refresh_identity.py。
17. 迁移 tools/sandbox_spaces.py。
18. 迁移 tools/session_search.py。
19. 迁移 tools/session_variables.py。
20. 迁移 tools/shell.py。
21. 迁移 tools/show_tool.py，按 P3.4 更新循环依赖说明。
22. 迁移 tools/skills.py。
23. 迁移 multiagenttools/__init__.py。
24. 迁移 multiagenttools/agents_group.py，保留既有未实现入口。
25. 迁移 multiagenttools/approval_subagent.py。
26. 迁移 multiagenttools/chat_subagent.py。
27. 迁移 multiagenttools/profile_builder.py，保留全部签名和延迟导入策略。
28. 迁移 multiagenttools/enter_multi_agent.py，按 P3.2 更新共享 Profile 延迟导入。
29. 迁移 multiagenttools/exit_multi_agent.py。
30. 迁移 multiagenttools/list_subagents.py。
31. 迁移 multiagenttools/run_subagent.py。
32. 迁移 multiagenttools/run_taskagent.py。
33. 迁移 multiagenttools/stop_subagent.py。
34. 迁移 multiagenttools/stop_taskagent.py。
35. 迁移 extools/__init__.py。
36. 迁移 extools/archive_tools.py。
37. 迁移 extools/cron_tools.py，保留 component.cron_tasks 导入。
38. 迁移 extools/diff_tools.py，按 P3.4 更新目录示意注释，保持根路径推导。
39. 迁移 extools/dynamic_endpoint_tools.py。
40. 迁移 extools/web_fetch.py。
41. 迁移 browser/__init__.py，按 P3.4 校正无状态辅助模块说明。
42. 迁移 browser/_connection.py。
43. 迁移 browser/system.py，保留原接口与生命周期实现。
44. 迁移 browser/close.py，按 P3.2 更新 _connection 导入。
45. 迁移 browser/connect.py，按 P3.2 更新 _connection 导入。
46. 迁移 browser/interact.py，按 P3.2 更新 _connection 导入。
47. 迁移 browser/launch.py，按 P3.2 更新 _connection 导入。
48. 迁移 browser/list_tabs.py，按 P3.2 更新 _connection 导入。
49. 迁移 browser/navigate.py，按 P3.2 更新 _connection 导入。
50. 迁移 browser/query.py，按 P3.2 更新 _connection 导入。
51. 迁移 browser/screenshot.py，按 P3.2 更新 _connection 导入。
52. 迁移 browser/tab.py，按 P3.2 更新 _connection 导入。
53. 迁移 browser/wait.py，按 P3.2 更新 _connection 导入。
54. 迁移 automation/__init__.py。
55. 迁移 automation/keyboard_press.py。
56. 迁移 automation/keyboard_type.py。
57. 迁移 automation/mouse_click.py。
58. 迁移 automation/mouse_drag.py，按 P3.2 更新共享鼠标常量导入。
59. 迁移 automation/screen_capture.py。
60. 迁移 automation/template_match.py。
61. 迁移 automation/window_enum_child.py。
62. 迁移 automation/window_find.py。
63. 迁移 automation/window_focus.py。
64. 更新 origin_agent/entity/constant/tools.py 的五个发现前缀与注释，保留 MCP_TOOL_MODULE。
65. 更新 origin_agent/system/application.py 的 BrowserSystem 实现导入。
66. 更新 origin_agent/gateway/session_manager.py 的 Profile 构造延迟导入。
67. 更新 origin_agent/entry/multi_agent_loop.py 的主Agent提示词构造延迟导入。
68. 更新 custom_tools/read_forward.py 的 filesystem 导入前缀，保留全部符号。
69. 更新 origin_agent/entry/colloquy_loop.py 顶部路径说明。
70. 更新 requirements.txt 的浏览器工具路径注释。
71. 新增 origin_agent/buildin_tools/DEV-README.md，按 P5 完整承接工具约定和部署边界。
72. 更新 origin_agent/component/DEV-README.md，按 P5 拆分工具说明并保留服务规范。
73. 更新 DEV-glossary.md 的内置工具目录锚点和 RefreshIdentity 路径。
74. 更新 DEV-README.md 的模块地图、源码定位、阅读顺序及部署说明。
75. 更新 DEV-class_relationships.md 的当前定位并追加迁移设计记录，保留历史章节原文。
76. 更新 origin_agent/abstract/DEV-README.md 的工具来源、发现及实现表。
77. 更新 origin_agent/system/DEV-README.md 的 BrowserSystem 位置及发现边界。
78. 更新 origin_agent/entry/DEV-README.md 的共享压缩准备入口路径。
79. 更新 origin_agent/subagent/DEV-README.md 的工具包及 Profile 构造器路径。
80. 更新 custom_mods/DEV-README.md 的两处工具目录引用，不实施草案功能。
81. 只读对照61个迁移文件和50个 TOOLSET 模块的源码内容，核对旧五包无源码及无兼容代理。
82. 只读核对 P3 全部导入和发现顺序，确认保留 component 服务、MCP、延迟导入与路径深度契约。
83. 定向搜索允许源码及当前文档的旧五包引用，按 P6 分类处理，保留有意的历史记录。
84. 通过读取差异审阅本任务范围，记录无业务/持久化/依赖版本/生命周期变化及未运行验收的事实。
85. 向本任务文件追加实施记录、只读审阅结论和用户人工部署验收待办；停留 EXECUTE，等待用户验收，不自动切换 REVIEW。

## 本轮进度
2026-10-30_16:42:07：完成补充研究，确定61个文件、50个 TOOLSET 模块与4个外部导入调用方；新增必要的 custom_tools/read_forward.py 联动。形成 P1—P7 及85项编号清单，追加 PLAN v1。尚未修改正式源码/开发文档，未运行任何校验、构建、实际导入或应用。下一步只读独立审查本任务文件，审查意见和修订继续追加记录。

---

# 2026-10-30_16:49:14 — 独立计划审查与定位修正

## 独立审查结论
按用户 /plan 指令，使用 generalPurpose 执行 .cursor/agents/plan-reviewer.md 的只读计划审查；协议文件路径使用实际存在的 .agents/skills/riper-core/SKILL.md 与 .agents/skills/plan-mode/SKILL.md，未使用描述文件中已过时的 .cursor/skills 路径，也未采用其旧模型标记。

审查记录标识：66c28a35-aa3a-4aa4-914f-ba4479fc3d31。

- 必需规划元素完整性：通过；路径/签名、数据、错误处理、依赖和用户人工验收边界齐全。
- 实施清单质量：通过；85项连续编号，61个文件迁移项无遗漏，逐文件逻辑迁移粒度合理。
- PLAN 模式合规性：通过；采用追加记录，无实施代码，未授权 EXECUTE。
- 架构与设计合理性：通过；五包迁移范围、BrowserSystem 随包、component 保留服务和部署残留风险均明确。
- 可执行性：通过；特别核对了 custom_tools/read_forward.py 的全部8个导入符号与 diff_tools.py 上溯三级的相同路径深度。

总判定：可执行；无阻塞缺陷、无必须修订项，无需复审。实施仍须用户明确授权 EXECUTE，执行前按清单第1项复核最新文件基线和目标冲突。审查仅为文档/源码只读核对，不是测试、构建或运行通过。

## 自查定位修正（PLAN v1.1；仅更正文档章节号）
- 修订对象：P5 第10项对 custom_mods/DEV-README.md 第二处路径的位置说明。
- 原内容摘要：第13节职责表中工具目录引用。
- 修订后内容：第二处引用实际位于第12节“架构分层与代码接入方向”的职责表，当前为第414行；第一处仍位于第2节的 skills.py 源码参考表，当前为第43行。
- 原因：追加计划后直接读取第391—432行，确认第13节是“迁移边界”，职责表属于第12节。
- 受影响范围：只影响 P5 第10项的文字定位与清单第80项执行导航；仍是同一文件的同两处路径替换，迁移文件、代码修改、接口、数据、顺序和验收规则均不变。PLAN v1 其余全部内容和85项编号保持适用，不改写原文。
- 复审判断：属于确定性章节号校正，不改变设计或实施内容，无新增阻塞事项，无需重跑完整审查。

## 本轮完成状态
仅在本任务文件内更新步骤并追加计划、审查结论与定位修正；正式源码和正式开发文档未修改，目录未移动。未运行校验、测试、构建、实际导入或应用，未操作运行时副本或 Git 写入。当前 RIPER-5 阶段为 PLAN，计划已准备好，等待用户批准进入 EXECUTE。

---

# 任务进度 — EXECUTE

## 2026-10-30_16:52:13 — 第1—2项完成
- 授权：用户通过 /execute 明确批准执行 PLAN v1 与 v1.1 定位修正；本条替代前文“未授权 EXECUTE”的当前状态，历史原文保留。
- 已核对：component 五包文件清单仍与61项基线一致，buildin_tools 原先无文件，无未知目标冲突。
- 已修改：新建空 origin_agent/buildin_tools/__init__.py；无聚合导入、无注册或应用查询。
- 原因：建立新普通 Python 包，准备按编号逐文件迁移。
- 阻碍因素：无；当前没有专用文件移动接口，按计划使用专用 Read/Write/Delete 工具完成各文件逻辑迁移，不使用命令行或脚本编辑文件。
- 状态：源码步骤已完成；运行状态未确认。尚未运行任何校验、测试、导入、构建或应用。

## 2026-10-30_17:23:05 — 第3—22项 tools 阶段完成
- 已修改：20个 tools 文件全部迁至 buildin_tools/tools；两个压缩工具只更新共享模块导入，show_tool.py 只更新指定循环依赖注释。
- 更改：每文件读取原文、写入目标并回读对照后定向删除原文件；2047行 filesystem.py 分段完整迁移，保留相对 ._file_changes 导入和末尾 TOOLSET。
- 原因：完成五包中的核心工具整包迁移，保留原始行为。
- 只读核对：旧 component/tools 无文件，目标完整列出20文件；再次读取 filesystem.py 尾部确认正文完整至 TOOLSET。
- 阻碍因素：最初执行阶段在 filesystem.py 前遇到单次上下文容量限制，保持原件后续接，通过分段专用文件工具完成；未改变计划或使用命令行搬移。该阻碍已解除。
- 状态：文件迁移完成、人工文本对照完成；尚无字节级换行校验或运行验收，不宣称测试通过。

## 2026-10-30_17:31:32 — 第23—34项 multiagenttools 阶段完成
- 已修改：12个 multiagenttools 文件按清单顺序全部迁至 buildin_tools/multiagenttools；原文件经完整目标回读对照后删除。
- 更改：仅 enter_multi_agent.py 的共享 Profile 延迟导入改用新路径，符号和位置保持；profile_builder.py 全部签名及 agents_group.py 未实现入口保持。
- 原因：完成多Agent工具及必要共享构造器的整包迁移。
- 阻碍因素：无；未修改外部调用方或其他文件，下一阶段为第35—40项 extools。
- 状态：文件迁移与人工正文对照完成；无字节级校验或运行验收。

## 2026-10-30_17:39:36 — 第35—40项 extools 阶段完成
- 已修改：6个 extools 文件全部迁至 buildin_tools/extools，原件在完整回读对照后删除。
- 更改：仅 diff_tools.py 目录示意注释更新；其三级父路径算法保持，cron_tools.py 对 component.cron_tasks 的依赖和说明保留。
- 原因：完成扩展工具包迁移，保留既有服务边界。
- 阻碍因素：无；下一阶段为第41—53项 browser。
- 状态：迁移及人工正文对照完成；无自动校验、字节级校验或运行验收。

## 2026-10-30_17:50:43 — 第41—53项 browser 阶段完成
- 已修改：browser 的13文件迁至 buildin_tools/browser，完整目标回读后删除原件，旧包已无文件。
- 更改：10个工具模块仅改 _connection 导入前缀；包说明校正无状态辅助模块与 BrowserSystem 的归属；_connection.py、system.py 正文保持。
- 原因：浏览器工具及必要服务随包迁移，保留原接口和资源生命周期。
- 阻碍因素：无；下一阶段为第54—63项 automation。
- 状态：迁移及人工正文对照完成；没有运行校验或应用。

## 2026-10-30_18:00:46 — 第54—63项 automation 阶段完成
- 已修改：automation 的10文件全部迁至 buildin_tools/automation，完整目标回读对照后删除原件。
- 更改：仅 mouse_drag.py 的共享鼠标常量导入前缀更新；ctypes结构、平台检查、TOOLSET与业务行为保持。
- 原因：完成最后一个工具子包的整体迁移。
- 只读核对：buildin_tools 中现有61个迁移Python文件及新空顶包入口；component 中仅保留既定服务、MCP模块、包入口和开发文档，五旧包已无文件。
- 阻碍因素：无；开始第64—70项发现配置及外部引用联动。
- 状态：五包迁移完成，运行验收尚未执行。

## 2026-10-30_18:02:38 — 第64—70项联动完成
- 已修改：entity/constant/tools.py 保序更新五个发现前缀，MCP_TOOL_MODULE 保留 component.mcp_tools。
- 已修改：Application 的 BrowserSystem 实现导入、Gateway会话恢复和MultiAgentLoop的Profile延迟导入、自定义工具调用方的filesystem导入。
- 已修改：colloquy_loop.py 包位置说明和 requirements.txt 浏览器路径注释；依赖版本、实际白名单和业务逻辑未改。
- 原因：使新包成为工具发现与已知直接调用方的唯一源码入口。
- 阻碍因素：无；进入第71—80项开发文档同步。
- 状态：源码联动完成，未执行导入检查、校验、构建或应用。

## 2026-10-30_18:08:44 — 第71—72项包文档拆分完成
- 已修改：新增 buildin_tools/DEV-README.md，逐节承接五包工具契约、共享模块和BrowserSystem说明；component/DEV-README.md保留审批/MCP/Cron/动态端点规范并链接工具文档。
- 更改：五包文件/TOOLSET基线、发现顺序、包入口、Profile外部调用方、BrowserSystem归属及无兼容代理边界均已登记；补充用户停机部署和旧五包残留风险。
- 原因：目录职责变化后文档随源码分离，不丢失完整工具行为规范，不将本轮描述为Component专用整理已完成。
- 阻碍因素：无；开始第73—80项根及其他子包开发文档同步。
- 状态：文档编辑完成，正式运行验收未执行。

## 2026-10-30_18:14:54 — 第73—80项根与子包文档同步完成
- 已修改：DEV-glossary.md 登记内置工具目录锚点并更新身份刷新位置；DEV-README.md 更新模块地图、工具源码定位/发现/阅读顺序并追加迁移与部署记录。
- 已修改：DEV-class_relationships.md 更新六处当前工具位置并追加迁移设计记录，保留明确的历史章节原路径。
- 已修改：abstract/system/entry/subagent 四份开发文档更新五包发现/BrowserSystem/共享压缩/Profile构造位置；custom_mods草案仅更新两处工具目录引用。
- 原因：完整同步此次目录变更，保留既有服务、权限、持久化和生命周期规范。
- 只读初查：61个迁移文件与原删除差异的行数一致（空入口仍为空），50个TOOLSET声明保留；源码中仅剩 cron_tasks.py 的一处明确历史来源引用，custom_tools 和 custom_mods 当前调用/文档无旧五包路径。
- 阻碍因素：无；进入第81—85项最终只读审阅与记录。
- 状态：文档同步完成；没有执行测试、校验、实际导入、构建或应用。

## 2026-10-30_18:17:17 — 第81—85项只读审阅与实施记录完成

### 第81项：迁移内容与声明基线
- 汇总逐文件执行时的完整原文读取、目标回读对照和删除结果，61个文件均已完成；父方另按目录清单复核20/12/6/13/10个文件对应关系，五旧包无源码文件。
- 使用允许的 git diff --numstat 读取原路径删除行数，并与专用文本搜索工具返回的新文件行数逐项对照；所有非空迁移文件行数与原件一致，四个原空包入口仍为空，browser包入口仅说明调整且保持原行数；新顶包入口为空。
- 50个顶层TOOLSET声明模块按17/9/5/10/9基线保留，不包含custom_tools和独立MCP管理入口。无源码兼容代理、重复工具来源或新sys.modules注入。
- 这是人工源码/文本审阅，不是自动化校验或字节级编码/换行一致证明。

### 第82项：导入、发现与保留边界
- 回读五个常量确认 tools→extools→multiagenttools→automation→browser顺序保持，仅前缀改变；MCP_TOOL_MODULE仍为component.mcp_tools。
- 回读未修改的discover.py，确认仍由常量同时推导物理目录和模块名前缀，可选custom_tools随后处理，再显式注册MCP工具与元数据；不扫描旧五包或新顶包根。
- 对照已迁移共享模块导入，以及Application、会话恢复、Profile切换和custom_tools调用方的一行路径差异；原延迟导入位置和符号保持。cron_tools.py刻意继续依赖component.cron_tasks。
- 回读diff_tools.py确认三级父路径计算未改；BrowserSystem及共享Profile构造器随包且接口/业务生命周期不改。

### 第83项：旧路径分类
- origin_agent的Python源码定向搜索只剩component/cron_tasks.py的一处历史来源说明，符合P3.4明确保留要求；custom_tools当前源码无旧五包引用。
- 当前根DEV-README/DEV-glossary、abstract/system/entry/subagent开发文档及custom_mods草案的应迁移路径已更新；buildin_tools文档仅在说明旧五包已移除时保留旧位置。
- DEV-class_relationships历史条目与历史设计记录中的旧路径按计划保留，最新迁移节明确当前对应关系；不搜索或改写.docs历史导出、其他任务记录或运行时副本。

### 第84项：差异与范围
- 只读审阅git diff：四个外部调用方均仅一行导入前缀变化；constant文件仅五前缀及注释变化；colloquy与requirements仅各一行路径说明变化。
- 新增buildin_tools开发文档并完整承接工具规则；旧component文档只保留服务与交叉链接。根三份及其余六份现有开发文档按P5更新，当前引用与历史记录分开处理。
- 原审批/Cron/动态端点/MCP源码、21个System接口槽位、依赖关系、Runtime关闭准备、工具协议/schema/审批权限、持久化类型与easysave key不变；没有新增依赖版本、测试源或运行入口。
- git diff默认不包含未跟踪的新路径，因此新包内容另用专用Read/Grep/Glob读取并结合逐文件迁移对照结果审阅，不将旧路径的删除统计误当作新文件已被Git跟踪。

### 第85项：结果与待用户验收
- 实施清单第1—85项全部完成；所有阶段结果按追加方式记录，未改写既有计划。只有步骤指针原地更新。
- 本轮仅操作origin源码、计划列明的根/扩展源码与开发文档及本任务文件；没有读取、搜索或修改workspace内容，没有修改third、运行时副本或Git索引/分支。
- 文件内容编辑和迁移均使用专用文件工具，终端仅用于Get-Date和用户允许的只读git diff；没有命令行/脚本文件编辑。
- 未运行任何测试、校验、静态解析、实际导入、类型检查、构建或应用；未检查字节级行尾一致性，运行状态仍为未确认。
- 待用户：按P6停机完整部署新包和调用方，保护本地修改后定向处理运行时旧五包残留（force_init不清除fast侧残留），再按人工矩阵验收并反馈成功/不成功。开发助手AI不代执行。
- 当前阶段保持RIPER-5 EXECUTE，等待用户确认，不自动进入REVIEW。
