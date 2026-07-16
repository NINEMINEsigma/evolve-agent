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
│   ├── handsfree.py          ← 脱手模式状态管理 + LLM 审批流程
│   └── allowlist.py           ← 工具 allowlist 持久化
├── tools/                    ← 核心工具
├── extools/                  ← 扩展工具集（下划线前缀为重模块的惰性导入）
├── mutliagenttools/          ← 多代理 / 子代理工具
├── mcp_tools.py              ← MCP 工具桥接
└── cron_router.py            ← Cron 任务路由
```

---

## 工具系统

### 注册与发现

工具通过模块级 `registry.register()` 注册，启动时由 `abstract/tools/discover.py` 的 AST 扫描自动发现。来源包括：

- `component/tools/` — 核心工具
- `component/extools/` — 扩展工具
- `component/mutliagenttools/` — 多代理工具
- `custom_tools/` — 用户自定义工具（若目录存在）
- MCP server — 通过 `component/mcp_tools.py` 桥接

### 核心工具（`component/tools/`）

| 工具文件 | 主要工具 | 用途 |
|----------|----------|------|
| `filesystem.py` | `read_file`, `write_file`, `edit_file`, `list_directory`, `delete_file`, `copy_file`, `move_file`, `rename_file`, `search_files`, `grep`, `file_exists` | 沙盒内文件操作 |
| `code.py` | `validate_code`, `evolve_code` | 自我进化 |
| `shell.py` | `run_command` 等 | 子进程执行 |
| `frontend.py` | `validate_frontend` | 前端构建验证 |
| `skills.py` | `load_skill`, `list_skills` | 技能管理 |
| `read_image.py` | `read_image` | 图像读取 |
| `run_python.py` | `run_python` | Python 代码执行 |
| `ask_question.py` | `ask_question` | 向前端提问 |
| `progress_tools.py` | `update_task_progress`, `clear_task_progress` | 任务进度 |
| `clipboard_display_tools.py` | `update_clipboard_display`, `clear_clipboard_display` | 剪贴板展示 |
| `list_tools.py` | `list_tools` | 列出工具 |
| `list_uploads.py` | `list_uploads` | 列出上传文件 |
| `probe_vision.py` | `probe_vision` | 探测模型视觉能力 |

### 扩展工具集（`component/extools/`）

> **命名约定变更**：重型导入的扩展工具文件已使用下划线前缀（`_csv_tools.py`、`_docx_tools.py` 等），通过惰性导入避免启动时加载不必要的依赖。无前缀的文件（`archive_tools.py`、`cron_tools.py` 等）为轻量工具，直接导入。

| 工具文件 | 用途 |
|----------|------|
| `web_search.py` / `web_fetch.py` / `_web_browser.py` | 网络搜索、抓取、浏览器自动化 |
| `ssh_tools.py` | SSH 远程执行 |
| `cron_tools.py` | 一次性/周期性后台定时任务 |
| `_csv_tools.py` / `excel_tools.py` / `_docx_tools.py` / `_pdf_tools.py` | 文档处理 |
| `_ffmpeg_tools.py` | 音视频处理 |
| `diagram.py` / `mermaid_tools.py` / `_docgen_tools.py` | 图表与文档渲染 |
| `background_service.py` | 后台服务管理 |
| `pip.py` | Python 包管理 |
| `_gui_windows.py` | Windows GUI 自动化 |
| `archive_tools.py` | 归档工具 |
| `diff_tools.py` | diff 工具 |
| `display.py` | 显示工具 |

### 多代理工具（`component/mutliagenttools/`）

详见 `../subagent/DEV-README.md`。

| 工具文件 | 主要工具 | 用途 |
|----------|----------|------|
| `register_subagent.py` | `register_subagent` | 注册子 Agent |
| `unregister_subagent.py` | `unregister_subagent` | 注销子 Agent |
| `list_subagents.py` | `list_subagents` | 列出子 Agent |
| `run_subagent.py` | `run_subagent` | 启动子 Agent |
| `chat_subagent.py` | `chat_subagent` | 向子 Agent 发消息 |
| `stop_subagent.py` | `stop_subagent` | 停止子 Agent |
| `approval_subagent.py` | `approval_subagent` | 审批子 Agent 的工具调用 |
| `enter_multi_agent.py` | `enter_multi_agent` | 切换到多 Agent 协作模式（不可逆） |
| `agents_group.py` | `agents_group` | Agent 分组管理 |
| `_store.py` | — | `SubagentStore`：子 Agent 注册表磁盘存储 |
| `profile_builder.py` | — | `build_multi_agent_tools()`：多 Agent 模式工具过滤 |

---

## 审批系统

### `component/approval/`（目录化重构）

原 `component/approval.py` 单文件已重构为目录，按职责拆分为 5 个子模块。`__init__.py` 重新导出所有公共接口，保持 `from component.approval import Xxx` 旧路径兼容。

#### `approval/backend.py` — 审批后端

- `ApprovalBackend`（ABC）：脱手模式审批后端抽象，声明 `chat()` 和 `is_available()` 接口。
- `LocalApprovalBackend`：本地 GGUF 模型审批，通过 `third/llamaapis` 的 `InferenceEngine` 推理。
- `RemoteApprovalBackend`：远程 OpenAI 兼容 API 审批。
- `FailedApprovalBackend`：哨兵子类，表示初始化失败。
- `create_approval_backend(ctx)`：工厂函数，根据 `RuntimeContext` 配置选择本地或远程后端。
- `is_local_approval_enabled()`：检测本地审批是否可用。

审批后端的生命周期由 `system/application.py::ApprovalBackendManager` 管理（懒加载 + 优雅卸载）。

#### `approval/core.py` — 统一审批入口

- `request_user_confirm(session_id, tool_name, args, ...) -> ApprovalResult`：统一审批入口，自动分流脱手模式与正常模式。
- `ask_agent_reason(llm, tool_name, args, question, ...) -> str`：脱手模式专用，向 Agent 主模型提问获取上下文。

#### `approval/executor.py` — 工具审批执行器

- `execute_with_approval(tool_name, args, session_id, sink, ...) -> ApprovalOutcome`：提取 `ParentAgentLoop` 与 `MultiAgentLoop` 中重复的审批逻辑，封装 dangerous/write 判断、白名单检查、脱手/正常两种审批模式、拒绝结果构建和 `allow_always` 加白名单。

#### `approval/handsfree.py` — 脱手模式

- `set_handsfree_mode(session_id, enabled)` / `is_handsfree_mode(session_id)`：脱手模式 session 级状态管理。
- `APPROVAL_JSON_SCHEMA`：审批决策的 JSON Schema 定义。
- `_handsfree_confirm()`：核心流程，通过 `ApprovalBackend.chat()` 调用本地/远程模型评估工具调用风险。

#### `approval/allowlist.py` — 工具白名单

- `is_allowed(tool_name, session_id)` / `add_allowed(tool_name, session_id)`：工具 allowlist 持久化，命中白名单的工具无需弹窗或模型审批。

### 审批流程

1. `ToolExecutor.execute()` 或 `MultiAgentLoop._execute_tool()` 调用 `execute_with_approval()`。
2. `execute_with_approval` 判断工具危险等级与白名单。
3. 若工具在 allowlist 中或危险等级为 `readonly`，直接执行。
4. 否则进入审批流程：
   - **正常模式**：通过 `AgentSink.request_approval()` 弹出前端确认请求，等待用户决策。
   - **脱手模式**：通过 `ApprovalBackend.chat()` 调用本地/远程模型自动评估。
5. 审批结果回传后，允许执行或返回拒绝结果。

---

## MCP 桥接

### `component/mcp_tools.py`

- 从 `RuntimeContext.mcp_config_path`（默认 `workspace/mcp_config.json`）读取 MCP 配置。
- 调用 `abstract/mcp/client.py` 的 `register_mcp_servers()` 连接 server。
- 将 MCP server 提供的工具动态注册到 `ToolRegistry`，对主 Agent 可见。
- 应用关闭时调用 `shutdown_mcp_servers()` 清理连接。

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
- 通过 inbox 将 Cron 结果注入对应 `ParentAgentLoop`。
- 提供 REST API：`/api/sessions/{id}/cron-tasks/...`。
- 生命周期由 `Application.shutdown()` 管理。