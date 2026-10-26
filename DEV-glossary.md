# Evolve Agent — 项目术语表

> **三位一体**：本表统一开发者/用户、开发助手AI、Evolve Agent 三方沟通口径。新增术语必须先登记后使用。

**防漂移规则**：

1. **新增术语先登记后使用** — 任何在文档、对话、prompt 中频繁出现的概念，必须先在本表登记规范称谓，后方可使用。
2. **Agent 一律大写 A** — Evolve Agent、Cursor AI、主Agent、子Agent、临时Agent、多Agent模式主会话等，"Agent" 永远大写。代码标识按源码原样（`SubAgentLoop`、`subagent` 工具集名等）。
3. **中英双锁定** — 每条术语锁定中文规范称谓与英文锚点；面向 Evolve Agent 的 prompt 模板使用规范英文形态。

---

## §1 元规则

| 规范称谓 | 定义 |
|---|---|
| 快速失败（Fail-Fast） | 已识别的业务拒绝在操作入口明确返回；逻辑之外的错误直接传播，不伪装为默认值、空结果或成功，不按宽泛异常类型猜测可恢复性 |
| 只崩溃软件（Crash-only software） | 失败终止当前执行单元，由已有运行边界负责失败处理；HTTP 请求由 FastAPI 处理，不能据此假定共享内存或已完成的磁盘写入会自动回滚。资源释放与原子写仍属于正常生命周期约束 |
| 角色术语与实例名分层 | 文档默认用角色术语；实例名仅特指当前部署时使用 |
| Role 不译 | 固定搭配，直指 `puretype.Role` 枚举（user/assistant/system/tool） |
| 术语双锁定 | 中文规范称谓 + 英文锚点；prompt 模板使用规范英文形态 |
| 前置辅助模块 | 英文锚点：pre-runtime utility module。`origin_agent/util/` 中无需 Application 装配即可导入和复用的辅助函数模块；项目内依赖限于已核实无反向业务依赖的 `entity/`、`interface/` 子模块及其他前置辅助模块。不依赖具体 System、Agent Loop 或业务实现，不拥有业务生命周期；不等于无 I/O 纯函数，也不要求早于全部 entity 模块统一导入。 |

---

## §2 协作角色

| 规范称谓 | 指代 | 英文锚点 |
|---|---|---|
| 用户（场景别名：开发者） | 人类 | user / developer |
| 开发助手AI | 开发侧协助的 AI（角色术语；当前实例为 Cursor AI，未来可替换） | dev assistant AI |
| Cursor AI | 当前承担「开发助手AI」角色的具体 AI 实例 | Cursor AI |
| Evolve Agent（通称：项目 Agent） | 本项目的运行时 agent | Evolve Agent |
| 主Agent | 系统提示词含 SOUL 的 Agent，任意 loop 下保证存在 | 默认角色名 `DEFAULT_MAIN_AGENT_CHARACTER_NAME = "main-agent"`，运行时由 `SOUL.md.meta` 的 `[character_name]` 覆盖，经 `RefreshIdentity` 工具刷新 |

---

## §3 空间与沙盒

| 规范称谓 | 目录 | 沙盒前缀 | 角色 |
|---|---|---|---|
| origin仓库 | `origin_agent/` | 无 | 源码真相源：唯一持久化源码 |
| fast仓库 | `workspace/fast_agent_space/` | 无（无 `self:`） | 当前运行副本 |
| slow仓库 | `workspace/slow_agent_space/` | `fork:` | 进化目标副本 |
| fallback仓库 | `workspace/.fallback/` | `fix:` | 上一次 fast 仓库的备份 / 回退修复体 |
| 工作空间 | `workspace/agentspace/` | `ws:` | agent 的 workspace，通用 I/O |

> **设计注记**：fast/slow 借用快慢指针命名——fast 是当前执行位置，slow 是待提升位置，热交换即 slow 提升为 fast。
> 「副本」为角色描述词，不作名词术语。fast 模式 / fallback 模式保留英文形态。「回退」为 fallback 中文规范译法。
> **目录列均为默认配置名**——workspace 根与 fast/slow 空间、工作空间、logs 的实际目录名由 config.py 参数（`workspace_path`、`fast_agent_space_path`、`slow_agent_space_path`、`agentspace_path_name`、`logs_path_name`）覆盖；本表锁定的是角色称谓而非物理目录名。仅 `.fallback/` 为 run.py 硬编码固定名。

| 规范称谓 | 定义 |
|---|---|
| 沙盒命名空间 | `fork:`/`ws:`/`fix:`/`skills:`/`third:`/`custom_*:` 逻辑前缀体系；内置前缀由 `Namespace` 枚举定义 |
| 动态沙盒空间 | 用户授权的全局逻辑路径映射（英文锚点：`global dynamic sandbox space`）；独立持久化、仅 fast 模式启用，由 Sandbox 单例管理并供所有 Agent 共享。`is_readonly` 仅表示标准 Sandbox 文件 API 层只读，不是操作系统 ACL |
| 动态沙盒空间 Tab | 右侧 Tab 栏的动态沙盒空间 tab（`SandboxTab`，原命令菜单弹窗去模态化迁移）的用户管理界面；通过 REST 接口查询、创建、更新和删除全局动态沙盒空间，不经过 Agent 工具审批（英文锚点：`dynamic sandbox spaces tab`） |
| 逻辑路径 / 物理路径 | 带命名空间前缀的路径（如 `fork:main.py`）/ 真实文件系统路径。逻辑路径格式为 `命名空间:相对路径`，路径段之间统一使用 `/`；不能以 `/` 或 `\` 开始或结束，也不能包含 `\`。文档中目录示例的末尾 `/` 只是目录说明，不是文件工具参数的一部分 |
| 元数据文件 | 英文锚点：metadata file。目标完整名称追加 `.meta` 的同级文本文件；Read 以独立成行的 `[key]` 分段解析为一层 `dict[str, str]`，值原样保留。正常结果附加 `meta`，缺失省略，读取/解析错误返回错误字符串；命名空间根目录不附带，显式读取 `.meta` 不嵌套。Read 默认仅返回数据；会话视觉源目录的 `redirect` 字段约定由会话视觉资源服务解释，Read 本身不跟随重定向。与会话元数据及工具内部 `_meta` 字段不同。会话视觉重定向实现进度以对应任务文件为准。 |
| 主Agent角色名 | 运行时由 `RuntimeSystem.main_agent_character_name` 持有的进程级名称，用于 History 角色标记、前端展示与多Agent路由匹配。启动时从 `ws:SOUL.md.meta` 的 `[character_name]` 读取一次，缺失或异常时回退到 `DEFAULT_MAIN_AGENT_CHARACTER_NAME`（"main-agent"）；运行期由 `RefreshIdentity` 工具（`component/tools/refresh_identity.py`，MAIN scope）重新读取。该机制供未来 `SOUL.md.meta` 扩展更多运行时设定复用。 |
| 角色头像（character avatar） | 元数据键 `[avatar]` 声明的角色自定义头像（英文锚点：character avatar）。主Agent键在 `ws:SOUL.md.meta`，子Agent键在角色目录 `profile.md.meta`；值为一行任意可读命名空间逻辑路径。服务端仅校验可读、是文件与 ≤`AVATAR_MAX_BYTES`（5 MiB），不限扩展名，浏览器自动尝试加载；经 `GET /api/characters/avatars` 实时组装、`/files` 前缀服务，前端按角色名映射并回退首字母头像。编辑 meta 后前端经 Agentspace 事件去抖自动刷新，无需调用工具；非 agentspace 命名空间的头像文件本体替换不触发自动重拉（重连 `resync` 或重新挂载时生效）。 |
| `.docs/` | 项目示例与引用资料目录 |

---

## §4 会话与 Loop

| 规范称谓 | 指代 | 代码锚点 |
|---|---|---|
| 主会话 | 三种 loop 承载的顶层会话统称 | — |
| 普通模式主会话 | `ParentAgentLoop` 的会话 | `Loop.parent` |
| 多Agent模式主会话 | `MultiAgentLoop` 的会话 | `Loop.multi` |
| 随意聊聊会话 | `ColloquyLoop` 的内置会话 | `Loop.colloquy` / `COLLOQUY_SESSION_ID` |
| 子会话 | `SubAgentLoop` 的会话（与前端 UI「子会话 Tab」对齐） | — |
| 临时子会话 | `TaskAgentLoop` 的会话 | — |
| 子Agent / subagent | `SubAgentLoop` 运行体；亦指多Agent模式中从动态角色档案加载的非主参与者（两语境互斥，复用不歧义） | — |
| 临时Agent / taskagent | `TaskAgentLoop` 运行体（无系统提示词、无持久化、完成即终止） | — |
| 角色档案 | `ws:characters/roleplay/<角色名>/` 或 `ws:characters/task/<角色名>/` 中的 `profile.md` 与 `profile.md.meta`；`[description]` 提供角色发现目录和主Agent系统提示词使用的简介；`profile.md` 和元数据 `[profile]` 声明的多行命名空间路径共同提供子Agent独立系统提示词，`[llm_profile]` 提供 LLM Profile 名称引用 | character profile |
| 动态角色档案解析器 | 每次扫描角色目录、读取 `profile.md` 与元数据并解析当前 LLM Profile 的运行时组件 | dynamic character profile resolver |
| 角色类型 | `roleplay` 或 `task`；仅用于分类，角色名称仍跨类型全局唯一 | character type |
| （子Agent的）档案 | 角色目录中的 `profile.md` 与 `profile.md.meta`；`[profile]` 可按行声明多个独立系统提示词路径 | character profile prompts |
| 运行时Profile | 多Agent参与者的运行时形态 | `AgentProfile` 类 |
| 参与Agent | 多Agent模式主会话中的参与者（主Agent 必居其一） | — |
| 工具循环 | LLM→工具调用→结果回写→LLM 轮次循环（上限 90） | `MAX_TOOL_TURNS` |
| 强制调用工具 | 用户为下一次空闲主会话发送或重新生成选择的一次性要求：首次模型逻辑请求必须发出任意至少一个工具调用；多Agent模式各初始响应者分别一次。请求发出后关闭，resume、忙碌期间补充发送及工具链续轮不使用、不消费。不是审批模式，不保证工具执行成功，依赖模型服务的原生参数契约 | require tool call / `require_tool_call` |
| 级联 | 多Agent模式 `response_characters` 驱动的串行响应队列调度 | `_cascade` |

---

## §5 编排与进化

| 规范称谓 | 指代 | 英文锚点 |
|---|---|---|
| 启动入口 | `run.py` | launch entry |
| 子代理编排器 | `SubAgentOrchestrator`（禁用"调度器"叫法） | SubAgentOrchestrator |
| 进化触发模块 | `evolve/code.py` | — |
| 进化 | 词根统一（"演化"为待改写遗留） | evolution |
| 进化工具链 | read/edit（fork:）→ validate_code/validate_frontend → evolve_code | — |
| 热交换 | slow→fast 交换并重启 | fast-slow swap |
| 进化循环 | fast-slow-fallback 全流程统称 | evolution cycle |
| 回退修复 | fallback 模式下由 fallback仓库 修复 fast仓库 | fallback repair |
| Shell会话 | 由 Agent 通过 ConPTY 持有、可跨多次工具调用持续读写的长期交互式命令解释器实例 | Shell session |
| 启动Shell | 创建独立 Shell会话并写入首条命令的工具 | `StartShell` |
| 读取Shell | 按绝对字符位置读取 Shell会话规范化输出的工具 | `ReadShell` |
| 写入Shell | 向已有 Shell会话发送一行文本的工具 | `WriteShell` |
| 中断Shell | 向已有 Shell会话发送 Ctrl-C、但不终结 Shell 的工具 | `InterruptShell` |
| 停止Shell | 强制终结 Shell会话及其进程树的工具 | `StopShell` |
| 进化状态 | `workspace/logs/evolution.status` 记录的进化结果状态 | evolution status |
| 安全写入 | 先写同目录临时文件，再原子替换目标；进程中断时主文件保持完整旧版本或完整新版本 | safe write |
| 原子写 | 不以截断方式直接覆盖目标，而是在完整临时文件准备好后一次性替换目标 | atomic write |
| 备份冲突 | 目标路径对应的 `.bak` 已存在时，`save()` 拒绝继续并要求人工检查 | backup conflict |
| 原生 PTY 访问串行化 | 对同一 ConPTY 原生对象的写入、中断、关闭和状态查询使用统一生命周期同步边界 | native PTY access serialization |

---

## §6 审批系统

| 规范称谓 | 定义 | 英文锚点 |
|---|---|---|
| 手动模式 | 会话级审批模式：主会话 safe/write 直接执行，dangerous 在未命中白名单时由用户弹窗审批，critical 始终由用户弹窗审批；普通子会话需审批调用由父Agent处理；由服务端按主会话持久化并跨程序重启恢复；新建、单源分支和多父合并产生的主会话默认使用该模式，上下文超限产生的自动延续继承来源主会话的当前模式 | manual mode |
| 脱手模式 | 会话级审批模式：safe 直接执行，主会话未命中白名单的 write/dangerous 由审批模型审批，critical 仍由用户弹窗审批；普通子会话需审批调用走审批模型；由服务端按主会话持久化并跨程序重启恢复；审批 Profile不可用不会改写已恢复模式，实际模型审批按失败路径拒绝 | handsfree mode |
| YOLO 模式 | "You Only Live Once"：AI 工具的免确认自动执行模式——含 critical 全部自动批准、无审批模型参与；与手动/脱手模式三选一互斥，可运行时自由切换，并由服务端按主会话持久化后跨程序重启恢复 | YOLO mode |
| 审批模型 | 脱手模式下执行审批的 LLM；由 `LLMProfileData.approval_profile` 引用根对象中的一个 LLMProfile 实例 | approval model |
| 审批 Profile 名称指针 | 项目级审批 Profile 在 `LLMProfileData.approval_profile` 中的对象引用（英文锚点：`approval Profile reference`）；通过前端「模型配置」抽屉选择，easysave 保留对象身份 |
| 危险等级 | `danger_level` 四级：safe / write / dangerous / critical | danger level |
| 可用范围 | `availability` 位掩码：MAIN / SUBAGENT / MULTI_AGENT / TASKAGENT / EVERY | availability |
| 审批动作 | allow_once（允许一次）/ allow_always（始终允许，入白名单）/ deny（拒绝） | approval action |
| 审批策略 | `ApprovalPolicy`：手动模式与脱手模式各自需审批的危险等级集合 | approval policy |
| 白名单 / allowlist | 中文规范"白名单"、英文标识 allowlist | allowlist |
| 工具白名单 | `tool_allowlist.json` 持久化的"始终允许"记录 | tool allowlist |

---

## §7 消息与事件

| 规范称谓 | 指代 |
|---|---|
| Role（不译） | `puretype.Role` 协议层枚举（user/assistant/system/tool） |
| 角色（character）/ 角色名（character_name） | 会话参与者层标识（main-agent/end-user/system/子Agent名） |
| 事件出口 | sink 体系：`AgentSink` 抽象；`FrontendSink` = 前端事件出口；`ParentAgentSink` = 父会话事件出口 |
| 入站缓冲 / 出站缓冲 | inbox / outbox（异步消息缓冲；代码标识改名为可选遗留） |
| 消息体系 | `entity/messages.py` 的 `BaseMessage` 多态模型与 `History` |
| 消息前纯类型 | 英文锚点：pre-message pure types。`entity.puretype` 中不依赖正式消息类的纯数据类型，可在 `entity.messages` 定义前加载；不得直接、间接或仅在 `TYPE_CHECKING` 下反向依赖消息体系或消息后纯类型 |
| 消息后纯类型 | 英文锚点：post-message pure types。`entity.puretype_after` 中依赖正式消息类的纯数据类型，在消息定义完成后直接引用真实类型；可以依赖消息体系及消息前纯类型，由本包独立导出，前期包和消息定义层不得反向导入它。这里的先后表示类型依赖顺序，不是应用生命周期阶段 |
| History辅助读取 | 开发助手AI使用 `dev_helpers/read_history.py` 复用正式History/媒体类型、项目类型映射和只读easysave库，还原真实History后输出保留消息类型与媒体元信息、以占位符替换媒体载荷的 JSON；不启动应用、不改原模型、不写回历史，也不清理未配对工具调用，仅处理受信任的本地项目历史（英文锚点：History diagnostic reader） |
| 客户端传输诊断 | 前端检测会话预检或 History关键 REST等待超过15秒时产生的脱敏 `client_diagnostic`；显示持久通知，并在会话 WebSocket可用时只写 Gateway warning，不进入聊天 History（英文锚点：`client transport diagnostic`） |
| Agentspace事件 | `AgentspaceEvent` 文件/锁/重同步元数据；聊天页通过 typed `agentspace_event`复用会话 WebSocket，独立 Agentspace 编辑器通过 SSE接收，载荷沿用既有同源元数据范围 |
| 历史更新指令 | 后端在已提交的 History 发生非追加变更后发送的 `history_updated` 下行通知（英文锚点：history updated event）；要求前端使旧历史视图/请求失效并完整重载骨架与按需正文，不刷新页面、不重放工具。普通追加仍用 `history_sync`，未接受的批次后缀仍用 `tool_calls_discarded` |
| 流式增量 | `StreamChunk`（content_delta / reasoning_delta），LLM 客户端到流消费器的数据 |
| 流式事件 | 前端实时输出的 `StreamDeltaEvent` / `StreamDoneEvent`；按 `type` 区分的纯数据模型，进程内保留工具载荷与计时模型，WebSocket发送边界才序列化；不同于 Provider 产生的 `StreamChunk`（英文锚点：stream event） |
| 空响应（empty LLM response） | LLM正常返回但正文长度为零且没有工具调用的异常结果；思考内容不构成有效完成。正式客户端加载入口对这类结果最多尝试3次（初次加2次重试，等待1秒、2秒），耗尽明确失败，不写空assistant消息。纯工具调用合法，非零长度空白正文保持原语义；已有工具参数增量但没有完整工具调用且无正文时明确失败、不重试。流式重试保留同一流标识与连续思考展示，不把失败尝试加入重试输入；其usage和结束原因不作为成功终态。辅助模型调用同样适用，能力探针持续空时失败而不缓存支持/不支持。 |
| 思考内容 | reasoning_content / reasoning_delta，模型响应中的思考正文或流式思考增量 |
| 工具结果嵌入消息 | 工具调用期间排队、随后被下一个工具结果携带展示的用户消息；内部以 `_queued_messages` 保存，通过 `embedded_messages` 独立传输，在工具调用卡片结果区特殊渲染，不作为普通 JSON 正文显示 | embedded tool message |

---

## §7 会话运行状态

| 规范称谓 | 指代 | 英文锚点 |
|---|---|---|
| 主会话活动快照 | 当前主会话 Loop 的非持久化运行状态，包含活动来源、阶段、活动标识和当前 LLM 流标识；由前端通过会话状态 REST 查询 | main session activity snapshot |
| 活动标识 | 一次主会话回复活动的 `activity_id`；一次活动可先后包含多个 `stream_id` | activity ID |
| 流标识 | 单次 LLM 流式调用的 `stream_id`，对应一个前端实时 assistant 气泡和其 History 映射 | stream ID |

## §8 上下文管理

| 规范称谓 | 定义 |
|---|---|
| 媒体实例 | History 中每次进入的独立图片、音频或视频块（英文锚点：History media instance）；即使来源文件或内容相同也分别控制。持久身份与多模态发送开关随 History 保存，新实例默认开启；关闭只改变后续主会话模型请求视图，不删除原媒体，也不禁止向转发模型发送原媒体 |
| 压缩 | 将早期消息压缩为摘要以释放上下文（`CompressHistory` 工具；随意聊聊会话用滑动窗口压缩最早 30%）；只压缩工具链时使用独立工具 `CompressToolChains`，不截断会话轮次 |
| 工具链 | 历史中一段仅由「带 tool_calls 的 assistant 消息」和 ToolResultMessage 组成的连续消息段；遇到 user / 纯文本 assistant / system 消息即结束（英文锚点：tool chain） |
| 工具链压缩 | 把完整工具链整段替换为「一次伪造的不可调用工具调用（`CompressedToolChain`）+ 携带链摘要的配对工具结果」；可压缩链要求全部 tool_call 已配对结果（进行中的本轮链天然排除）、包含真实工具调用且原始体积达阈值；纯压缩占位链跳过，与新增真实调用组成的完整链仍可压缩。摘要由工具链摘要 Profile 生成；`CompressHistory` 压缩保留轮次内的链，`CompressToolChains` 无业务参数、扫描全部历史且不替换会话对话，二者共享摘要准备逻辑（英文锚点：tool chain compression） |
| 工具链摘要 Profile | `LLMProfileData.toolchain_summary_profile` 全局实例引用（英文锚点：toolchain summary Profile）；为被折叠的工具链生成紧凑摘要；未配置时回退到目标会话主Agent正在使用的活动 Profile；通过前端「模型配置 Tab → 全局配置引用」页选择 |
| 摘要 | 会话级总结文本（`summary.txt`，终结/旋转时生成） |
| 旋转（rotation） | 上下文超限时自动终结当前会话并产生子会话的机制 |
| 延续（continuation） | **动作**：继承已终结父会话产生子会话——手动（一个或多个父会话，含合并）或旋转自动触发 |
| 延续会话 | 延续动作产生的子会话（`SessionInfo.continuation` 指向者） |
| 父会话 | `SessionInfo.parents` 指向的会话（支持多父） |

> 三机制分工：压缩保会话、旋转换会话、摘要作载体。

---

## §9 扩展点

| 规范称谓 | 定义 |
|---|---|
| 钩子 | `custom_hooks/` 下实现 `hook_tag_name` + `hook_message`/`hook_fixator` |
| 上下文扩展块 | 钩子返回、附加到用户消息末尾的内容块（前端渲染类名 `context-extension-part`） |
| 固着器（fixator） | 实现 `hook_fixator` 的钩子：产出**持久化**扩展块（`message_suffix`，写盘保留） |
| 非固着器 | 仅实现 `hook_message` 的钩子：产出**非持久化**扩展块（`dynamic_message_suffix`，当轮注入） |
| 技能 | `skills/` 下 `SKILL.md`，经 `load_skill`/`list_skills` 加载 |
| 插件 | `abstract/plugins` 目录扫描 + `plugin.yaml` 元数据 |
| 自定义工具 | `custom_tools/` 下的 `.py` 工具扩展，声明模块级 `TOOLSET: BaseToolSet` 对象，由 ToolDiscoverySystem 发现并注册 | custom tool |
| 工具集对象声明 | 模块级固定名称 `TOOLSET` 的 `BaseToolSet` 实例；导入期只创建无连接工具对象，注册期由 ToolRegistry 执行预热 | TOOLSET object declaration |
| 工具调用前 | 工具实例 `before_handle(execution)` 阶段；发生在审批通过后、工具主体之前，只处理当前调用准备 | before handle |
| 工具主体 | 工具实例 `handle(execution)` 阶段，执行实际业务操作 | handle |
| 工具调用后处理 | 工具实例 `after_handle(execution)` 阶段；History 成功提交后执行，默认空实现，异常按快速失败传播 | after handle |
| 同批后续调用接收声明 | 工具实例 `accepts_following_calls` 元数据；默认 true，false 时同一模型响应中其后的 tool calls 在执行前视为未发生 | accepts-following-calls declaration |
| 工具集预热 | `BaseToolSet.preheat()` 在工具集注册时执行一次的可用性检查；不替代运行期 check_fn/环境检查 | toolset preheat |
| 显式工具注册入口（退役） | 旧 `register_tools(registry, ui_events)` 函数注册协议；新工具必须使用 `TOOLSET` 对象声明 | _Avoid_: register_tools |
| 工具集条目（退役） | 旧 `ToolsetEntry` 元数据镜像；新工具集使用 `BaseToolSet` 对象 | _Avoid_: ToolsetEntry |
| 自定义LLM客户端 | `custom_llm_client/` 下的 `.py` LLM 客户端扩展 |
| 自定义模型 | `custom_models/` 下的 `.gguf` 模型文件（当前无运行时接入，保留目录供未来用途） |
| MCP 桥接 | `component/mcp_tools.py` 将外部 MCP server 工具注册进工具注册表 |
| 工具集加载意图 | 会话曾经调用 `LoadToolset` 加载过的工具集名称集合，持久化在 SessionStore（`loaded_toolsets.json`） | loaded toolsets |
| 有效工具集合 | 按"已加载工具集 + 当前 Loop 可见性（`ToolAvailability`）+ `check_fn` 可用性"动态计算的实际工具列表 | effective tools |
| LLM Profile 根对象 | `LLMProfileData`（英文锚点：`LLM Profile root`）；`llm_profiles.es` v2 中唯一的持久化根，持有全部 Profile 及实例引用关系 |
| 全局元数据 Profile | `LLMProfileData.metadata_profile`（英文锚点：`global metadata Profile`）；项目级元数据生成 Profile，统一服务所有会话的自动标题、自动标签和摘要；未配置时按目标会话活动 Profile 回退 |
| 会话待用 Profile 选择 | 浏览器按主会话保存的 Profile 名称，供下一条发送给主会话的消息或重新生成提交使用；选择操作本身不更新后端，可能与后端已保存的名称不同（英文锚点：`pending session Profile selection`） |
| 抽屉分页按钮 | 模型配置 Tab顶部切换“模型配置”和“全局配置引用”的按钮组；不称作左侧导航栏（英文锚点：`drawer tabs`） |
| Profile 名称指针 | 会话级或全局最近使用的 Profile 名称（英文锚点：`Profile name pointer`）；只保存名称，不复制端点、密钥或 Profile 对象 |
| Profile 实例引用 | `LLMProfile` 多模态分工字段直接指向根列表中的另一个 `LLMProfile` 实例（英文锚点：`Profile object reference`） |

---

## §10 会话操作

| 规范称谓 | 定义 |
|---|---|
| 归档 | 会话只读化（`status = "archived"`），可参与合并 |
| 终结 | 归档 + 尝试生成摘要与标签；元数据失败以警告返回但不阻止归档 |
| 合并 | 多父延续：将多个已归档会话合并为一个新会话 |
| 分支 | 从当前会话创建子会话 |
| 置顶 | `pinned` 标记，置顶显示 |
| 会话离线导出（offline session export） | 将当前主会话完整现存聊天、工具调用、消息内多媒体、聊天区自定义样式及 Agent 舞台层保存为脱离 Evolve Agent 和网络可打开的只读网页包；与会话网页 `site/` 及会话备份不同。无法保存的资源明确报告，不恢复已删除或已压缩的原文；仅空闲时允许，内容变化拒绝导出。实施进度以对应任务文件为准。 |

---

## §11 前端 UI

> 用户口径优先：如「导航栏」专指**左侧 Sidebar**，不是顶部 Header。

### 页面布局总览

```
┌──────────┬────────────────────────────────────────────┬──────┐
│          │  顶部栏 (Header，28px 常驻)                  │      │
│  左侧    ├────────────────────────────────────────────┤  右  │
│  导航栏  │  主界面区域 (TabStage)                      │  侧  │
│          │  ├ 聊天 Tab（ChatArea + 输入栏）            │  Tab │
│ (Sidebar,│  ├ 资源 Tab / 子会话 Tab / 角色档案 Tab     │  栏  │
│  浮层)   │  ├ 会话网页 Tab / 模型配置 Tab               │      │
│          │  └ 动态沙盒空间 Tab                          │      │
│          │    （同一时刻显示一个）                      │(Rail)│
└──────────┴────────────────────────────────────────────┴──────┘
```

> 启动屏（`SplashScreen`）和骨架屏（`SkeletonScreen`）作为覆盖层叠加在整体布局之上，分别用于开屏动画和首次连接前的占位。
> 各 tab 外层常驻挂载（grid 叠放 + `visibility` 切换，同会话切 Tab 不卸载），切换会话或页面刷新统一回到聊天 Tab。会话网页内部 iframe 仅在首次激活该 Tab 后创建，之后同会话保留；SiteTab 按 sessionId key 在切会话时重建，返回原会话也重新等待点击。提前运行的 HEAD 入口探测不等于加载网页正文。
> 会话锁定（`SessionLockOverlay`）时主界面区域与右侧 Tab 栏整体替换为锁定提示页。

### Tab 导航体系

文件：`origin_agent/frontend/src/features/tabs/`（`registry.tsx` · `useTabSystem.ts` · `sessionTabCapabilitiesApi.ts` · `useSessionTabCapabilities.ts` · `TabRail.tsx` · `TabStage.tsx` · `TabDataContext.tsx` · `useTabPreview.ts` · `TabHoverPreview.tsx` · `tabPreviewTypes.ts` · `tabPreviewSelectors.ts` · `tabPreviewLabels.json` · `useDynamicSandboxSpaces.ts` · `ChatTab.tsx` · `ResourcesTab.tsx` · `FileChangesTab.tsx` · `SubagentsTab.tsx` · `CharactersTab.tsx` · `useCharacterProfiles.ts` · `SiteTab.tsx` · `LlmTab.tsx` · `SandboxTab.tsx`）· `styles/tabs.css`

| 规范称谓 | 代码锚点 | 定义 | 英文锚点 |
|---|---|---|---|
| 会话 Tab 能力探测 | `useSessionTabCapabilities` / `GET /api/sessions/{id}/tab-capabilities` | 不读取完整媒体载荷或变量正文的只读能力链路；返回当前 History 媒体实例数量和变量 Tab 是否有可展示内容。首次未知、会话切换或失败时目标 Tab 禁用；同一会话后台 refreshing 保留已确认快照，成功确认空内容后禁用 | session tab capability probe |
| 右侧 Tab 栏 | `TabRail` / `.tab-rail-column` | 屏幕右缘 44px 常驻竖排 Tab 列（移动端 40px），由可滚动图标区和固定底部控制区组成；图标无内容或能力未确认时为禁用态不可点击，底部控制区上方为审批模式三态切换、下方为命令菜单 | tab rail |
| Tab 注册表 | `features/tabs/registry.tsx::TAB_REGISTRY` | 声明式注册表（id/标题/图标/render）；当前共十个 Tab，顺序为聊天、资源、文件修改、媒体输入、会话变量、子会话、角色档案、会话网页、模型配置、动态沙盒空间；新增 tab 需要注册条目、`useTabSystem` 启用派生和必要的数据能力来源 | tab registry |
| 主界面区域 | `TabStage` / `.tab-stage` | `.tab-body` 内的 grid 叠放容器，全部 tab 外层常驻挂载、`visibility` 切换（禁用 `display:none`，保护聊天滚动与已加载 iframe 生命周期）；会话网页内部 iframe 首次激活才创建，SiteTab 按 sessionId key 重置 | tab stage |
| 聊天 Tab | `ChatTab` / `[data-tab-panel="chat"]` | 默认激活 tab；ChatArea、剪贴板面板、倒计时条与输入栏全部归属此 tab，随 tab 隐藏（保持挂载） | chat tab |
| 文件修改 Tab | `FileChangesTab` / `[data-tab-panel="changes"]` | 按主会话汇总内置五种文件工具成功目标操作的只读目录树；显示当前可见文件和目录条目，父目录仅为结构节点；首次创建绿色、已有路径修改黄色、已有路径删除红色，会话新增路径删除后隐藏；每个可见条目附最后操作徽章 | session file changes tab |
| 操作次数 | `SessionFileChangesSummary.operation_count` | 所有成功目标操作总数；隐藏的删除操作仍计入，一次移动全局只计一次，不等于树中路径行次数之和 | successful target operation count |
| 逻辑路径条目数 | `file_count` / `directory_count` | 当前可见文件/目录条目数；删除条目不计入，目录树父节点是合成结构不计入；不表示磁盘存量或跨重命名物理文件数 | logical path entry count |
| 资源 Tab | `ResourcesTab` / `[data-tab-panel="resources"]` | 会话资源、Shell 会话、定时任务与动态端点；资源按 tab 激活懒加载 | resources tab |
| 媒体输入 Tab | `MediaInputTab` / `[data-tab-panel="media"]` | 显示标题「媒体输入」；仅当会话 Tab 能力探测确认当前主会话 History 存在媒体实例时右侧图标可用；进入后以中文相册式网格展示独立媒体实例，默认可见图片预览，点击再显示详情和发送开关。关闭时优先转发描述，无可用转发时占位；下一模型请求生效，原媒体展示保留，子会话不纳入 | media input tab |
| 会话变量池 | `SessionVariableService` / `ws:sessions/<session_id>/variables/` | 会话归属的数字/字符串 JSON 标量文件集合，同级 `.meta` 配置显示与约束；文件为唯一真相，通用文件工具写入、`ReadSessionVariables` 全量读取；单父继承复制，多父按来源分组，非事务且不随聊天重新生成回滚 | session variable pool |
| 会话变量 Tab | `VariablesTab` / `[data-tab-panel="variables"]` | 只有会话 Tab 能力探测确认存在变量条目或可展示问题时右侧图标可用；进入后只读展示会话变量池，支持目录分组、数值、进度条、环形仪表及纯文本；普通空目录或无问题的普通 `.meta` 不启用；通过会话 REST 与现有 Agentspace 事件同步 | session variables tab |
| 子会话 Tab | `SubagentsTab` / `[data-tab-panel="subagents"]` | 单个顶层 tab，多个子会话作为其内部子级 tab 切换；无子会话时禁用 | subagents tab |
| 角色档案 Tab | `CharactersTab` / `[data-tab-panel="characters"]` | 全部子Agent 角色档案的只读配置目录（列表+展开详情，含错误条目与提示词全文）；无角色时空态引导；数据源 `GET /api/characters/profiles`，按 tab 激活重拉并经 Agentspace 事件去抖刷新 | character profiles tab |
| 会话网页 Tab | `SiteTab` / `[data-tab-panel="site"]` | 会话网页 iframe 预览，首次激活且入口可用时才加载正文；同会话切 Tab 保留 iframe，切会话/刷新后重新等待点击；首次激活后隐藏 Tab 仍可热刷新，入口删除后同会话重部署可自动重建。按钮栏在可视底部常驻并独占一行、不遮挡网页；页面依赖结构性 28px 顶部栏，不再接受浮层顶部覆盖；site 未部署时禁用；提前运行的 HEAD 探测唯一源在 `useTabSystem` 的 `useSessionSite` | session site tab |
| 模型配置 Tab | `LlmTab` / `[data-tab-panel="llm"]` | 去模态化的模型配置面板（无遮罩/焦点陷阱/关闭按钮）；编辑草稿跨 tab 与跨会话保留，`beforeunload` 刷新守卫保留 | LLM profiles tab |
| 动态沙盒空间 Tab | `SandboxTab` / `[data-tab-panel="sandbox"]` | 去模态化的全局动态沙盒空间管理面板（自命令菜单弹窗迁移）；列表按 `activeTab` 懒加载（切入即重拉）；编辑草稿跨 tab 与跨会话保留，`beforeunload` 刷新守卫仅编辑态生效；会话锁定期间随 Tab 栏不可达 | dynamic sandbox spaces tab |
| Tab 顶部安全区 | `--header-height` | 结构性顶部栏已占据页面顶部空间，Tab 内容不再额外渲染 56px 浮层避让空白；会话网页 Tab 的底部按钮栏保持独立布局 | tab top safe area |
| 右侧 Tab 预览小窗 | `TabHoverPreview` / `.tab-hover-preview` | 鼠标悬停或键盘聚焦启用且非当前的 Tab 图标时，在图标左侧显示的只读摘要小窗；只消费页面已加载快照，不发请求、不刷新、不切换 Tab；点击卡片不切 Tab，Escape 关闭且同次悬停不重开；与名称 tooltip 互斥 | tab rail hover preview |
| 只读已有数据 | — | 预览只读取各 Tab 已取得的完整快照（`data` 为 null 表示尚未读取，`[]` 才是已知空）；媒体输入/会话变量 Tab 还受会话 Tab 能力探测控制，能力未知或失败时不启用、不悬停预览；未知不伪装为 0，读取中/旧快照/读取失败分项表达 | read-only loaded data |

### Agentspace 编辑器

| 规范称谓 | 代码锚点 | 定义 | 英文锚点 |
|---|---|---|---|
| Agentspace 编辑器 | `pages/Agentspace.tsx` | 独立的工作空间文件浏览与文本编辑页面 | Agentspace editor |
| Agentspace 文件树 | `components/agentspace/FileTree.tsx` | Agentspace 编辑器左侧的目录与文件树；不称作「导航栏」 | Agentspace file tree |
| Agentspace 垃圾桶 | `ws:.trash/` | 仅承接用户从 Agentspace 编辑器发起的可恢复删除；不改变 Evolve Agent `Delete` 工具 | Agentspace trash |
| 文件锁 | `AgentspaceLockRegistry` | Agent 在单次回复轮次中明确接触 `ws:` 路径后持有的路径锁；轮次收尾时释放 | file lock |

> 「导航栏」仍然只指聊天页面左侧 Sidebar。Agentspace 文件树与导航栏是两个不同区域。

### 应用框架与加载层

文件：`origin_agent/frontend/src/App.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 应用根组件 | `App` / `ChatApp` | 路由入口；管理 `SplashScreen`、`ChatContextMenu`、`TagEditor` 等顶层覆盖层；外层套 `ErrorBoundary` |
| 错误边界 | `ErrorBoundary` / `.error-boundary` | 组件渲染异常兜底，显示「界面渲染出错」+ 刷新按钮 |
| 连接诊断上下文 | `ConnectionDiagnosticsProvider` / `useConnectionDiagnostics` | 只提供低频 WebSocket 连接时间戳、接收 tick 与待审批状态；processing/stream ID 由聊天运行时 selector 直接提供 |

文件：`origin_agent/frontend/src/components/SplashScreen.tsx` · `origin_agent/frontend/src/components/SkeletonScreen.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 启动屏 | `SplashScreen` / `.splash-screen` | 开屏动画，最少停留 800ms、最多 3000ms，可点击跳过 |
| 骨架屏 | `SkeletonScreen` / `.skeleton-screen` | 首次 WebSocket 连接前的布局骨架占位（Header + Sidebar + 消息区轮廓） |

### 左侧导航栏（Sidebar）

> 用户所称「导航栏」「会话按钮和搜索框那一块」即此区域。

文件：`origin_agent/frontend/src/components/Sidebar.tsx` · `origin_agent/frontend/src/styles/sidebar.css`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 左侧导航栏 / 侧栏 | `Sidebar` / `.sidebar` | 展开宽 220px，`.collapsed` 时宽 0 完全隐藏 |
| 侧栏头部 | `.sidebar-header` | 顶部区域，含工具栏 |
| 侧栏工具栏 | `.sidebar-toolbar` | 搜索框 + 多选合并按钮 + 新建会话按钮 |
| 搜索框 | `.search-input`（容器 `.sidebar-search`） | 单行 28px，聚焦时展开为 96px 多行 |
| 标签云 | `.search-tag-cloud` / `.search-tag-btn` | 搜索聚焦或有搜索词时显示的标签快捷筛选 |
| 多选合并按钮 | `.icon-btn`（mergeMode 开关） | 进入/退出归档会话多选合并模式 |
| 新建会话按钮 | `.icon-btn`（onNewChat） | — |
| 会话列表 | `.session-list` | 可滚动区域，渲染平铺会话与会话簇 |
| 会话项 | `SessionListItem` / `.session-item` | 左侧 2px 竖线标识：蓝=当前，绿=父会话 |
| 会话簇 | `ClusterItem` / `.cluster` | 多个会话的聚合分组，可展开/折叠 |
| 关联会话快捷入口 | `RelatedSessionShortcut` / `.relation-shortcut` | 当前会话的父会话/延续会话跳转按钮 |
| 合并操作栏 | `.merge-bar` | 合并模式底部悬浮栏（已选数 + 合并按钮） |
| 侧栏遮罩 | `.sidebar-backdrop` | 移动端侧栏浮层展开时的背景遮罩 |
| 抽屉热区 | `.sidebar-hotzone` | 桌面端屏幕左缘 24px 隐形触发区，鼠标靠近时抽屉微微拉出 |
| 抽屉状态 | `.drawer-hidden` / `.drawer-peek` / `.drawer-open` | 桌面端侧栏三态：隐藏 / 微微拉出 / 彻底拉出（磨砂玻璃浮层） |
| 抽屉状态机 | `useEdgeDrawer` | 左侧导航栏边缘抽屉三态状态机（hidden/peek/open）；`pinned` 选项在左侧导航栏弹出层展开期间钉住抽屉 |

### 顶部栏（Header）

> 注意：用户口径中「导航栏」**不指这里**。

文件：`origin_agent/frontend/src/components/Header.tsx` · `origin_agent/frontend/src/styles/header.css`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 顶部栏 / 页头 | `Header` / `.app-header` | 28px 结构性常驻顶部栏，跨越视口从左到右；左侧是会话标题/ID内陷区域，右侧是直角梯形容器，内部依次为主徽章、上下文进度徽章和连接健康灯 |
| 顶部栏覆盖层 | — | 已退役；常驻 Header 通过结构性布局占据顶部空间，不使用 absolute 浮层 |
| 顶部栏热区 | — | 已退役；常驻 Header 不通过顶部隐形热区召唤 |
| 主徽章 | `HeaderPill` / `.header-pill` | 顶部栏右侧梯形中的圆角矩形主徽章；保留连接上下文和当前会话待用模型选择入口，模型菜单由独立浮层承载 |
| 顶部抽屉状态 | — | 已退役；Header 始终常驻，不再隐藏、探出或展开 |
| 侧栏开关按钮 | `.sidebar-toggle` | 位于顶部栏左侧，控制左侧导航栏收起/展开 |
| 会话身份区域 | `SessionIdentity` / `.session-identity` | 顶部栏左侧内陷蚀刻区域；默认显示会话标题，悬停或聚焦显示完整会话 ID，激活后复制 ID |
| 连接健康灯 | `ConnectionStatusLight` / `.connection-status-light` | 顶部栏梯形中的纯色实心圆；绿色表示接收和心跳正常，黄色表示警告，红色表示连接或接收故障；详细诊断通过 tooltip 展示 |
| 命令菜单 | `CommandMenu` / `.cmd-menu-dropdown` | 右侧 Tab 栏底部最下方的按钮触发；提供本地性能遥测、system 角色用户消息显示开关和会话视觉开关 |
| system 角色用户消息显示开关 | `showSystemUserMessages` | 控制 Role 为 `user` 且角色名为 `system` 的消息是否显示；默认显示，作为浏览器全局偏好保存，覆盖主聊天区、子会话和工具结果嵌入消息；不影响 History、模型上下文或系统状态提示（英文锚点：system-character user message visibility toggle） |
| 状态胶囊 | `HeaderPill` / `.header-pill` | 顶部栏右侧梯形中的圆角矩形主徽章；保留待用模型入口，连接健康由独立亮灯表达 |
| 模型选择菜单 | `ModelProfileMenu` / `.model-profile-menu` | 顶部栏唯一的会话待用 Profile 选择入口，body独立浮层；选择仅更新当前会话浏览器值，发送或重新生成时提交 |
| 审批模式切换 | `ApprovalModeBadge` / `.approval-model-badge` | 右侧 Tab 栏底部固定控制区上方的手动/脱手/YOLO 三态切换入口；没有会话时显示不可操作状态 |
| 上下文进度徽章 | `ContextProgressBadge` / `.context-progress-badge` | 顶部栏右侧梯形中的进度条，显示上下文使用百分比；悬停显示累计 token、已用上下文和上限 |
| 顶部栏折叠按钮 | — | 已退役；顶部栏常驻，不再提供移动端折叠入口 |

### 主内容区（Layout 其余区域）

文件：`origin_agent/frontend/src/components/Layout.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 主内容区 | `.main-content` | 位于常驻顶部栏和左侧导航栏主体之后的主界面区域；内部为 `.tab-body`（主界面区域 `TabStage` + 右侧 Tab 栏 `TabRail`） |
| 任务进度面板 | `TaskProgressPanel` | 输入栏抽屉面内（聊天 Tab），仅非空会话显示 |
| 统一面板（剪贴板） | `UnifiedPanel` | 剪贴板面板 `ClipboardPanel`，归属聊天 Tab，随 tab 隐藏（保持挂载） |
| 聊天区 | `ChatArea` | 消息流；归属聊天 Tab（`ChatTab` 包裹） |
| 输入栏 | `InputBar` | 底部输入区；归属聊天 Tab；普通单Agent桌面会话在已有消息后使用独立底部玻璃热区控制 hidden/peek/open 三态抽屉，空会话保留居中的完整输入栏；非空会话空闲时默认收缩，抵达聊天区底部时自动展开，离开底部后恢复收缩，热区悬停、聚焦及附件、上传、录音、任务进度等交互期间保持展开；ask/审批变形同样遵循三态收起规则（不位于底部或不聚焦输入框时收起），变形待办通过热区呼吸光效与角标提示，聚焦变形按钮会钉住展开；触摸设备保持完整形态 |
| 图片灯箱 | `Lightbox` | 图片放大查看 |
| 确认对话框 | `ConfirmDialog` | 工具调用审批弹窗 |
| 询问对话框 | `AskDialog` | Agent 提问弹窗 |

### 聊天区内部组件

文件：`origin_agent/frontend/src/components/ChatArea.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 消息项 | `MessageItem` / `.message` | 单条消息容器：头像、角色名、长消息折叠（>1200 字符或 >18 行）、编辑入口 |
| 消息体 | `MessageBody` | Markdown 渲染（GFM + breaks + raw）；reasoning 折叠；检测 `<script>`/`<style>` 等标签时切换到 `SafeHtml` 沙箱 |
| 消息编辑器 | `MessageEditor` / `.message-edit-box` | 用户消息内联编辑（textarea + 保存/取消） |
| 消息附件 | `MessageAttachments` | 图片缩略图、音频播放器、下载链接、播放列表 |
| 工具调用卡片 | `ToolCallCard` / tool call card | 主聊天区和子会话 Tab中以 `tool_call_id` 一对一聚合工具调用请求、执行状态与工具结果的可折叠视觉单元；不改变 History 中 assistant `tool_calls` 与 `ToolResultMessage` 的存储顺序 |
| 代码块 | `CodeBlock` / `.code-block-wrapper` | 语法高亮（Prism oneDark）+ 一键复制 |
| Mermaid 渲染器 | `MermaidRenderer` | Mermaid 图表渲染；点击放大为灯箱（缩放/平移，react-zoom-pan-pinch） |
| 安全 HTML | `SafeHtml` | iframe 沙箱渲染 agent 输出的原始 HTML，postMessage 同步高度，避免流式闪烁 |
| 等高线背景 | `ContourBackground` | 聊天区 canvas 等高线动态背景，受消息内容长度与 seed 影响 |
| Agent 舞台层 | `AgentStageLayer` / `.agent-stage-layer` | 位于聊天区背景之上、聊天气泡和输入栏之下的会话级渲染层；Agent 通过 `ws:sessions/<session_id>/stage/` 目录写入内容，`index.html` 作为资源完成后的部署提交标记；前端以透明 iframe 渲染且默认鼠标穿透，变化事件通过已有会话 WebSocket接收 |
| 会话网页 | `SiteTab`（会话网页 Tab） | 会话网页 Tab 内 iframe 首次激活时加载 `ws:sessions/<session_id>/site/index.html`，用于完整网页预览；仅当前会话已部署 `index.html` 时右侧 Tab 栏图标可用，HEAD 探测不加载正文；同会话切 Tab 保留网页，切会话/刷新后重置；与 Agent 舞台层 `stage/` 分离，变化事件通过已有会话 WebSocket接收 |
| 轮次导航条 | `RoundNavRail` / `.round-nav` | 主聊天区与子会话卡片共用的轮次导航组件：每条目对应一条 Role 为 `user` 的展示行（杠+内容文本一体），杠按作者角色名 hue 散列着色（与头像一致），当前轮放大+花纹凸显，点击跳转目标消息至视口中部略偏上，桌面 hover/focus 展开浮层显示条目文本，条目过多时虚拟滚动，少轮次时列表垂直居中；窄条常驻（无折叠按钮），触摸端点杠直接跳转 | round navigation rail |
| 回到底部按钮 | `.scroll-to-bottom` | `ChatArea` 挂载时常驻的主动回底控制件，不受滚动状态、初始化状态、内容数量或处理状态控制；无内容或没有滚动距离时仍保留，但不要求产生位移 |

### 输入栏内部组件

文件：`origin_agent/frontend/src/components/InputBar.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 富文本输入 | `RichInput` | contenteditable 富文本输入框，支持图片粘贴、`@` 提及（文件/skill）、`/` 命令 |
| @ 提及菜单 | `MentionMenu` / `.mention-menu` | `@` 或 `/` 触发的文件/skill 列表，Portal 渲染到 body，30s TTL 缓存 |
| 待上传图片预览 | `pendingImages` / `.pending-image` | 输入栏上方显示待发送的图片缩略图，可移除 |
| 目标会话选择器 | `targetSessions` | 选择消息发送目标（main / 子会话），位于输入栏工具区 |
| 角色可见性控制 | `visibleCharacters` / `responseCharacters` | 多 Agent 模式下控制消息可见范围与响应角色 |
| 上下文徽章 | `TokenRing`（独立组件） | 输入栏右下角环形上下文用量徽章（contextTokens/llmMaxContextTokens 百分比），悬浮/点击展示累计·已用·上限 | context badge |
| 输入栏功能组 | `.input-bar-actions-left` | 输入栏下行左侧功能按钮组（中断/厌恶/上传/剪贴板/录音/Agentspace/恢复），超宽收起为菜单 | input actions group |
| 功能组菜单 | `.input-actions-menu` | 功能组收起后的纵向菜单（图标+文字），PopupLayer 承载 | input actions menu |

### 会话操作弹层

文件：`origin_agent/frontend/src/components/ChatContextMenu.tsx` · `TagEditor.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 聊天右键菜单 | `ChatContextMenu` | 会话项右键菜单：自动标题、自动标签、置顶、分支、终止、删除、重生成摘要 |
| 标签编辑器 | `TagEditor` | 会话标签编辑弹窗（仅限 1-5 个汉字或 1-10 个英文字母） |

### 子会话与定时任务

文件：`origin_agent/frontend/src/components/SubagentCard.tsx` · `SubagentCountdown.tsx` · `CronCountdown.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 子会话卡片 | `SubagentCard` | 子会话 Tab内的单卡片视图，含消息流和轮次导航条；子级 tab 活跃项按会话持久化（`ACTIVE_SUBAGENT_ID`） |
| 子会话倒计时 | `SubagentCountdown` / `.cron-countdown-strip` | 子会话空闲收集倒计时条（≤30s 显示）；归属聊天 Tab |
| Cron 倒计时 | `CronCountdown` / `.cron-countdown-strip` | 定时任务下次执行倒计时条（≤60s 显示）；归属聊天 Tab |

### 资源 Tab 内部

文件：`origin_agent/frontend/src/features/tabs/ResourcesTab.tsx`

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 播放列表播放器 | `PlaylistPlayer` | 音频播放列表 UI（上一首/下一首/进度条/展开折叠） |

### 遗留组件

| 中文名称 | 代码标识 | 说明 |
|---|---|---|
| 剪贴板面板（旧版） | `ClipboardPanel` / `.clipboard-display-panel` | 与 `UnifiedPanel` 功能重叠的旧版组件，已被 `UnifiedPanel` 替代 |

---

### 聊天历史与性能

| 规范称谓 | 定义 | 英文锚点 |
|---|---|---|
| 全历史骨架 | 会话中全部前端消息行的轻量顺序与角色信息，不含正文或富媒体；不是 `history.es` 的分页存储 | full history skeleton |
| 历史内容页 | Gateway 按 History 消息索引范围返回的完整前端渲染内容；不改变 `History` 的整体存储 | history content page |
| 实时行映射 | WebSocket实时行 ID到正典 History投影行 ID的权威关联；只使用后端实际 History索引，不按正文或顺序猜测 | live History row link |
| 正典交接 | skeleton目标存在时把实时行提升到正典位置、再由History内容页覆盖临时内容并移除实时副本的过程 | canonical handoff |
| 本地性能遥测 | 用户手动开启、仅在浏览器本地记录并导出技术指标、默认关闭且不上传消息内容的诊断能力 | local performance telemetry |

## §12 前端会话视觉

| 规范称谓 | 定义 | 英文锚点 |
|---|---|---|
| 会话视觉资源重定向 | 由会话源目录同级 `stage.meta`、`site.meta` 或 `chat-style.meta` 的 `[redirect]` 指定带沙盒命名空间的目标目录。服务端仅解释源目录配置一层；缺失时保持原目录，非法时静默回退，Read 不跟随目标。此为已批准设计约定，运行时接入进度见任务文件 | session visual resource redirect |
| 会话视觉资源状态 | 服务端按需提供的 stage、site、chat_style 三项非持久化会话快照，包含资源可用状态、源目录、有效目录、是否实际重定向和错误原因；不表示浏览器已渲染成功，不随分支或合并复制。此为已批准设计约定，运行时接入进度见任务文件 | session visual resource state |
| 会话聊天区自定义样式 | 会话级 CSS 覆盖层，Agent 通过 `ws:sessions/<session_id>/chat-style/index.css` 写入，仅作用于 `.chat-area` 聊天区；变化事件通过已有会话 WebSocket接收 | Session Chat Style |
| 聊天区样式暂停开关 | 用户在右侧 Tab 栏底部命令菜单中独立暂停聊天区自定义样式的开关，按会话持久化 | chat style pause toggle |
| 舞台层暂停开关 | 用户在右侧 Tab 栏底部命令菜单中独立暂停 Agent 舞台层的开关，按会话持久化 | stage pause toggle |
| 公开样式选择器契约 | 以 `data-chat-scope` 和 `data-message-role` 属性构成的稳定选择器集合，向 Evolve Agent 承诺跨版本兼容 | public style selector contract |

---

## 应用生命周期

| 规范称谓 | 定义 | 英文锚点 |
|---|---|---|
| 运行时系统 | Application 内的唯一配置与进程生命周期系统；持有运行状态、输入接收同步边界、关闭信号及失败记录，不代替各业务 System 的资源所有权 | RuntimeSystem |
| 输入投递记录 | 关闭前已接受输入的非持久化提交记录，包含进程内序号、原始消息、准备状态和 History 提交状态；不同于 client_message_id，也不是可在重启后自动执行的持久队列 | InputDelivery |
| 只落历史关闭 | 停止新工作与模型生成，把已接受但未提交的输入加入所属会话 History 并按原约定保存；重启不自动补跑，临时Agent不新增持久化 | history-only shutdown |
| 资源清理待完成 | 外部资源清理已超过前台观察期限，但进程、线程、连接或 SDK 上下文尚未证明释放。应用停用该旧实例并保留引用继续收尾，不因该明确清理超时请求全应用失败；持久化失败、内部逻辑错误、必要业务交接失败和 60 秒最终退出保护不降级。自动收尾只记录日志；显式停止操作返回真实未完成状态，不宣称释放成功 | resource cleanup pending |

上述约定按异步架构迁移阶段接入，当前实施进度见 `.tasks/2026-10-07_1_async-architecture-system-lifecycle.md`。资源清理待完成的决策边界见 `.tasks/2026-10-22_2_external-resource-cleanup-timeout.md`。

---

## §13 退役术语

以下术语已过时或被取代，禁止在新内容中使用：

| 退役术语 | 替代术语 | 说明 |
|---|---|---|
| 冒险模式 / Adventure / Adventure Mode | 脱手模式（handsfree mode） | 非常旧的名称，已全面退役 |
| 演化 / 演化循环 | 进化 / 进化循环 | 词根统一为"进化" |
| 子代理调度器 | 子代理编排器 | `SubAgentOrchestrator` 的禁用叫法 |
| 正常模式 | 手动模式 | 审批模式名称，取代"正常模式" |
| RIPER Yolo | （已删除） | RIPER-5 协议中已过时的 Yolo 概念，已从 `.agents/skills/riper-core/SKILL.md` 移除 |
| 允许列表 | 白名单 | 统一为"白名单" |
| orchestrator（裸称） | 启动入口（launch entry） | prompt 模板中裸称 orchestrator 指代 run.py 的写法已退役；`SubAgentOrchestrator` 合法保留 |
| 右侧触发条 | 右侧 Tab 栏（tab rail） | `.right-trigger-strip` 体系已被右侧 Tab 栏替换；2026-10-12 起 Tab 导航改造退役 |
| 资源抽屉 / 模型配置抽屉 / 会话网页抽屉 / 子会话面板 | 资源 Tab / 模型配置 Tab / 会话网页 Tab / 子会话 Tab | 右侧抽屉体系 tab 化后退役；规范称谓见 §11「Tab 导航体系」 |
| 小地图 / 逻辑 Minimap 映射 | 轮次导航条（round navigation rail，`RoundNavRail`） | 2026-10-12 起轮次导航改造退役；主聊天区与子会话的小地图（Canvas 逻辑映射 / DOM 几何预览）整体替换为轮次导航条 |
| 动态沙盒空间管理弹窗 | 动态沙盒空间 Tab | 命令菜单弹窗 tab 化后退役（2026-10-12）；规范称谓见 §11「Tab 导航体系」 |

## §14 全局活动看板

| 规范称谓 | 定义 | 英文锚点 |
|---|---|---|
| Logger System | Application 注册的进程级结构化活动事件 System；与标准 Python `logging` 并存，首版仅保存有界内存活动事件，不替代诊断日志 | Logger System |
| 结构化活动事件 | 主会话消息接收、Agent 响应流和工具调用的安全元数据事件；不包含用户正文、Agent 正文、工具参数、工具结果或密钥 | structured activity event |
| 全局活动状态看板 Tab | 右侧 Tab 栏中的只读进程级活动视效 Tab；使用当前 KPI 快照和打开后的活动事件增量，不提供导航或业务控制 | global activity dashboard tab |
| 活动事件 SSE | Activity Tab 使用的单一全局 Server-Sent Events 连接；只发送订阅建立后的事件，不发送历史快照或断线期间事件 | activity event SSE |
