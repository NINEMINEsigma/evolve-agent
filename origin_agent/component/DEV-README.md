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
│   ├── handsfree.py          ← 审批模式状态管理 + LLM 审批流程
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
| `filesystem.py` | `Read`, `Write`, `PatchEdit`, `Delete`, `Copy`, `Move`, `SearchFiles`, `Grep`, `file_exists` | 沙盒内文件操作 |
| `code.py` | `ValidateCode`, `EvolveCode` | 自我进化 |
| `shell.py` | `RunCommand` 等 | 子进程执行 |
| `frontend.py` | `ValidateFrontend` | 前端构建验证 |
| `skills.py` | `RecallSkill`, `CreateSkill` | 技能管理（已并入 core 工具集） |
| `load_toolset.py` | `LoadToolset` | 按需加载工具集到当前会话（core 工具集，EVERY 可见性） |
| `run_python.py` | `RunPython` | Python 代码执行 |
| `ask_question.py` | `Ask` | 向前端提问 |
| `progress_tools.py` | `UpdateTaskProgress`, `ClearTaskProgress` | 任务进度 |
| `clipboard_display_tools.py` | `UpdateClipboardDisplay`, `ClearClipboardDisplay` | 剪贴板展示 |
| `show_tool.py` | `ShowTool` | 查看工具/工具集元数据 |
| `list_uploads.py` | `ListUploads` | 列出上传文件 |
| `compress_history.py` | `CompressHistory` | 会话历史压缩 |
| `session_search.py` | `SessionSearch` | 会话内容搜索 |
| `lsp.py` | LSP 诊断 | LSP 服务器进程管理与代码诊断 |

### 扩展工具集（`component/extools/`）

| 工具文件 | 用途 |
|----------|------|
| `web_search.py` / `web_fetch.py` | 网络搜索与抓取 |
| `cron_tools.py` | 一次性/周期性后台定时任务 |
| `background_service.py` / `bg_registry.py` | 后台服务管理与注册 |
| `dynamic_endpoint_tools.py` | 动态端点工具 |
| `pip.py` | Python 包管理 |
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
| `chat_subagent.py` | `ChatSubAgent` | 向子 Agent 发消息 |
| `stop_subagent.py` | `StopSubAgent` | 停止子 Agent |
| `approval_subagent.py` | `ApprovalSubAgent` | 审批子 Agent 的工具调用 |
| `enter_multi_agent.py` | `EnterMultiAgent` | 切换到多 Agent 协作模式 |
| `exit_multi_agent.py` | `ExitMultiAgent` | 退出多 Agent 协作模式 |
| `agents_group.py` | `AgentsGroup` | Agent 分组管理（当前未实现） |
| `_store.py` | — | `SubagentStore`：子 Agent 注册表磁盘存储 |
| `profile_builder.py` | — | `build_multi_agent_tools()`：多 Agent 模式工具过滤 |

---

## Agentspace 文件接触登记

内置工具通过 `ToolContext.agentspace_access()` 把明确的 `ws:` 路径登记到当前 Agent 回复轮次：

- `Read` 与单文件 `Grep` 登记精确文件；目录读取/搜索不锁整树。
- `Write`、`PatchEdit` 登记目标；`Copy`、`Move` 同时登记源和目标；目录 `Move/Delete` 使用递归锁。
- `RunCommand`、`RunPython` 在 `cwd` 为 `ws:` 时登记递归 cwd；`RunPython` 的明确 `ws:` script 另登记精确文件。
- 登记失败时工具 fail-closed；非 `ws:` 命名空间保持原行为。
- `Delete` 的 schema、危险等级、审批和永久删除行为完全不变。Agentspace 垃圾桶只属于网页编辑器的用户删除 API。
- custom tools、MCP 和绕过应用的外部进程无法可靠事前识别路径，由 watcher 与版本冲突机制处理，不宣称预锁。

---

## 审批系统

### `component/approval/`（目录化重构）

原 `component/approval.py` 单文件已重构为目录，按职责拆分为 7 个子模块。`__init__.py` 重新导出所有公共接口，保持 `from component.approval import Xxx` 旧路径兼容。

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

#### `approval/handsfree.py` — 审批模式状态管理

- `set_approval_mode(session_id, mode: ApprovalMode) -> ApprovalMode`：设置会话审批模式（MANUAL/HANDSFREE/YOLO），HANDSFREE 不可用时回退 MANUAL。
- `get_approval_mode(session_id) -> ApprovalMode`：返回会话当前审批模式（默认 MANUAL）。
- `disable_all_non_manual_modes() -> list[str]`：将全部非 MANUAL 的会话重置为 MANUAL。
- `is_handsfree_available() -> bool`：检查审批 Profile 是否已配置。
- `_handsfree_confirm()`：核心流程，通过审批 Profile 模型评估工具调用风险。审批请求包含工具的参数 schema（使模型能区分必填与可选参数）、实际参数值和 reason（补充说明）。审批输出使用普通文本决策标记（`[ALLOW]`/`[APPROVE]`/`[DENY]`/`[REJECT]`/`[拒绝]`/`[否决]`），不使用 JSON。审批 system prompt（`templates/approval/system_prompt.md`）明确审批模型只见单次调用、不读用户消息；schema description 是写给调用方 Agent 的指令而非审批判据；审批模型只判断该次调用本身是否安全，不检查前置条件/用户同意/流程合规，本质只读的操作（含 `ssh <host> <只读命令>`）必须放行。
- 兼容包装：`set_handsfree_mode()`/`is_handsfree_mode()`/`disable_all_handsfree_modes()` 保留，分别委托到新接口。

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