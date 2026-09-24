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

工具通过模块级 `registry.register()` 注册，启动时由 `abstract/tools/discover.py` 的 AST 扫描自动发现。来源包括：

- `component/tools/` — 核心工具
- `component/extools/` — 扩展工具
- `component/multiagenttools/` — 多代理工具
- `component/browser/` — 浏览器控制工具
- `component/automation/` — 桌面自动化工具
- `custom_tools/` — 用户自定义工具（若目录存在）
- MCP server — 通过 `component/mcp_tools.py` 桥接

### 核心工具（`component/tools/`）

| 工具文件 | 主要工具 | 用途 |
|----------|----------|------|
| `filesystem.py` | `Read`, `Write`, `PatchEdit`, `Delete`, `Copy`, `Move`, `SearchFiles`, `Grep`, `file_exists` | 沙盒内文件操作；`Read` 文本分支自动尝试 UTF-8、系统编码和 Windows 常见编码，`content` 返回原文行片段，不添加行号或规范化换行，分页保留 CRLF、孤立 CR 与末尾 LF，行位置由 `offset`/`total_lines` 给出；`PatchEdit` 的 exact/range 均按原始 UTF-8 文本逐字符匹配并原样写入 `new_string`，regex 仅按 Python `re.sub` 语法展开显式引用；三种模式都不自动补换行。`Sandbox.write()`/`append()` 禁用操作系统换行转换；`SearchFiles`/`Grep` 在 Windows x64 优先使用内置 `ripgrep`，不可用或单次不兼容时回退 Python；`Grep` 上下文与回退行号都按 LF 分行；默认遵循 ignore/hidden 过滤，返回 `engine`、`truncated`，`full_scan` 可完整包含隐藏/忽略路径，`exhaustive` 可完整扫描并写超限日志 |
| `code.py` | `ValidateCode`, `EvolveCode` | 自我进化 |
| `shell.py` | `StartShell`、`ReadShell`、`WriteShell`、`InterruptShell`、`StopShell` | Windows ConPTY 长期 Shell会话：启动并输入、字符位置读取、复用输入、Ctrl-C 与强制停止 |
| `frontend.py` | `ValidateFrontend` | 前端构建验证 |
| `skills.py` | `RecallSkill`, `CreateSkill` | 技能管理（已并入 core 工具集） |
| `load_toolset.py` | `LoadToolset` | 按需加载工具集到当前会话（core 工具集，EVERY 可见性）；加载只改变已加载集合，返回名称仅供发现，工具仍须通过当前 Loop 的 scope、危险等级与运行时权限过滤 |
| `sandbox_spaces.py` | `AddSandboxSpace`、`RemoveSandboxSpace` | fast 模式全局动态沙盒空间增删；位于按需加载的 `sandbox` 工具集，critical，仅普通/多Agent模式主Agent可修改；用户也可通过命令菜单中的动态沙盒空间管理弹窗直接执行 REST CRUD |
| `ask_question.py` | `Ask` | 向前端提问 |
| `progress_tools.py` | `UpdateTaskProgress`, `ClearTaskProgress` | 任务进度 |
| `clipboard_display_tools.py` | `UpdateClipboardDisplay`, `ClearClipboardDisplay` | 剪贴板展示 |
| `show_tool.py` | `ShowTool` | 查看工具/工具集元数据 |
| `list_uploads.py` | `ListUploads` | 列出上传文件 |
| `compress_history.py` | `CompressHistory` | 会话历史压缩 |
| `session_search.py` | `SessionSearch` | 会话内容搜索 |
| `lsp.py` | LSP 诊断 | LSP 服务器进程管理与代码诊断 |

### Read 元数据文件

仅 `Read` 支持自动附带元数据文件：目标完整名称追加 `.meta`，例如 `ws:a.md` 对应 `ws:a.md.meta`，`ws:docs/` 对应同级 `ws:docs.meta`，不是目录内部的 `.meta`。命名空间根目录（含等价当前目录写法或指向根目录的别名）不附带元数据；显式读取后缀为 `.meta` 的目标不继续嵌套。后缀识别不区分大小写，自动查找统一追加小写 `.meta`。

- 目录列表隐藏后缀匹配且为文件的条目，保留同后缀目录；`count` 为过滤后数量。`Sandbox.list_dir`、SearchFiles、Grep、Agentspace 文件树和写入/移动/删除工具不变。
- `system/file_metadata.py::parse_meta_content(content)` 是不执行 I/O 的共享解析入口。独立成行的 `[key]` 开始字段，键名不 trim、区分大小写，不允许空/纯空白键或键内方括号、CR、LF。标记行外侧没有空白；LF/CRLF 为行界，孤立 CR 仍是内容。
- 每个值一直延续到下一个键标记或文件末尾，缩进、空行、CRLF、孤立 CR 与末尾换行原样保留。独立的 `[text]` 是新键，不提供转义语法。
- 空文件或全空白文件得到 `{}`；无值键得到空字符串。重复键、非法的整行方括号标记、首个键前的非空文字抛带行号的 `MetaFormatError`，不返回部分解析字典。
- 文本、图片、音频、视频和目录成功结果均可包含普通 `meta` 字段：正常为 `dict[str, str]`，缺失省略，读取/登记/解析失败为错误字符串，不影响原目标结果；不同于内部工具统计字段 `_meta`。
- 元数据经 `Sandbox.resolve_read` 与 `Sandbox.read(limit=0)` 完整读取和现有编码探测，不使用正文 offset/limit；明确 `ws:` 元数据文件登记当前回复轮次文件接触，登记失败不读取。各媒体 `_blocks`、`_user_blocks` 和转发 description 保持不变。
- 只返回元数据，不解释或执行键的业务含义，不自动生成或随移动/删除维护文件。当前按完整读取契约不新增大小截断或单独上限，大文件的资源成本由调用方关注。

### 扩展工具集（`component/extools/`）

| 工具文件 | 用途 |
|----------|------|
| `web_search.py` / `web_fetch.py` | 网络搜索与抓取 |
| `cron_tools.py` | 一次性/周期性后台定时任务 |
| `dynamic_endpoint_tools.py` | 动态端点工具 |
| `archive_tools.py` | 归档工具 |
| `diff_tools.py` | diff 工具 |

> **已移除的工具**：CSV / Excel / DOCX / PDF / 音视频处理 / 浏览器自动化 / GUI 自动化 / 图表生成等文档与媒体处理能力已从 extools 中移除。这些能力应通过 skill 实现（在 `pre-skills/` 或 `skills/` 中编写对应的 `SKILL.md` 和辅助脚本）。

### 多代理工具（`component/multiagenttools/`）

详见 `../subagent/DEV-README.md`。

| 工具文件 | 主要工具 | 用途 |
|----------|----------|------|
| `register_subagent.py` | `RegisterSubAgent` | 注册子 Agent |
| `unregister_subagent.py` | `UnregisterSubAgent` | 注销子 Agent |
| `list_subagents.py` | `ListSubAgents` | 列出子 Agent |
| `run_subagent.py` | `RunSubAgent` | 启动子 Agent |
| `run_taskagent.py` | `RunTaskAgent` | 只接收单个 prompt；继承调用时父主会话活动 LLM Profile快照，启动仅可使用“已加载工具集 ∩ TASKAGENT ∩ safe”的临时Agent |
| `stop_taskagent.py` | `StopTaskAgent` | 提前终止临时Agent，不保存历史 |
| `chat_subagent.py` | `ChatSubAgent` | 向子 Agent 发消息 |
| `stop_subagent.py` | `StopSubAgent` | 停止子 Agent |
| `approval_subagent.py` | `ApprovalSubAgent` | 审批子 Agent 的工具调用 |
| `enter_multi_agent.py` | `EnterMultiAgent` | 切换到多 Agent 协作模式 |
| `exit_multi_agent.py` | `ExitMultiAgent` | 退出多 Agent 协作模式 |
| `agents_group.py` | `AgentsGroup` | Agent 分组管理（当前未实现） |
| `_store.py` | — | `SubagentStore`：子 Agent 注册表磁盘存储 |
| `profile_builder.py` | — | `build_multi_agent_tools()`：多 Agent 模式工具过滤 |

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

审批后端的生命周期由 `system/application.py::ApprovalBackendManager` 管理（同步 get_backend/get_state/invalidate + 异步 shutdown）。

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

- `is_allowed(tool_name, session_id)` / `add_allowed(tool_name, session_id)`：工具 allowlist 持久化，命中白名单的工具无需弹窗或模型审批。

#### `approval/policy.py` — 审批策略

- `needs_approval(policy, danger_level, approval_mode: ApprovalMode) -> bool`：根据策略和审批模式判断工具是否需要审批。
- `MAIN_SESSION_POLICY`：主会话策略（手动模式仅 dangerous+critical 需审批，脱手模式 write+dangerous+critical 需审批）。
- `SUB_SESSION_POLICY`：子会话策略（write+dangerous+critical 在两种模式下均需审批）。
- `ApprovalPolicy` 数据类定义在 `entity/puretype/`（`approval` 子模块）。

### 审批流程

1. `ToolExecutor.execute()` 调用 `execute_with_approval()`。
2. `execute_with_approval` 判断工具危险等级与白名单。
3. 若工具在 allowlist 中或危险等级为 `safe`，直接执行。
4. 否则进入审批流程：
   - **手动模式**：通过 `AgentSink.request_approval()` 弹出前端确认请求，等待用户决策。
   - **脱手模式**：通过审批 Profile 模型自动评估，使用普通文本决策标记。
5. 审批结果回传后，允许执行或返回拒绝结果。

---

## MCP 桥接

### `component/mcp_tools.py`

- 从 `RuntimeContext.mcp_config_path`（默认 `workspace/mcp_config.json`）读取 MCP 配置。
- 调用 `abstract/mcp/client.py` 的 `register_mcp_servers()` 连接 server。
- 将 MCP server 提供的工具动态注册到 `ToolRegistry`，对主 Agent 可见。
- 应用关闭时调用 `shutdown_mcp_servers()` 清理连接。
- MCP 工具注册前由 `abstract/mcp/schema.py::normalize_mcp_input_schema()` 做 provider 兼容规范化：按 schema 结构位置递归处理 `properties`、`items`、组合分支、`$defs`/`definitions` 和 `additionalProperties`，不会把业务参数 `properties` 误当作 JSON Schema 映射表。
- 规范化只作用于发送给 LLM 的 `function.parameters`；MCP handler 仍将模型生成的原始参数字典传递给 `session.call_tool()`，不使用规范化 schema 反向改写调用参数。

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

- `CronRouter` 接收 Cron 工具创建的后台任务。
- 维护任务注册表（`_CronTask`）与触发调度。
- 通过 SessionMessageQueue（主会话）或 inbox（子 Agent）将 Cron 结果投递到对应 loop。
- 提供 REST API：`/api/sessions/{id}/cron-tasks/...`。
- 生命周期由 `Application.shutdown()` 管理。