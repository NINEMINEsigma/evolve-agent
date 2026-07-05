# component/ — 工具、审批、MCP 与 Cron

`component/` 是 Evolve Agent 的具体能力实现层。它包含所有可直接调用的工具、审批系统、MCP 桥接以及 Cron 任务路由。

---

## 文件结构

```
component/
├── tools/                   ← 核心工具
├── extools/                 ← 扩展工具集
├── mutliagenttools/         ← 多代理/子代理工具
├── llm.py                   ← LLM 客户端
├── approval.py              ← 统一审批模块
├── approval_allowlist.py    ← 只读/自动通过白名单
├── mcp_tools.py             ← MCP 工具桥接
└── cron_router.py           ← Cron 任务路由
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
| `code.py` | `write_fork`, `validate_code`, `evolve_code` | 自我进化 |
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

| 工具文件 | 用途 |
|----------|------|
| `web_search.py` / `web_fetch.py` / `web_browser.py` | 网络搜索、抓取、浏览器自动化 |
| `ssh_tools.py` | SSH 远程执行 |
| `cron_tools.py` | 一次性/周期性后台定时任务 |
| `csv_tools.py` / `excel_tools.py` / `docx_tools.py` / `pdf_tools.py` | 文档处理 |
| `ffmpeg_tools.py` | 音视频处理 |
| `diagram.py` / `mermaid_tools.py` / `excalidraw_render.py` | 图表渲染 |
| `background_service.py` | 后台服务管理 |
| `pip.py` | Python 包管理 |
| `gui_windows.py` | Windows GUI 自动化 |
| `archive_tools.py` | 归档工具 |
| `diff_tools.py` | diff 工具 |
| `display.py` | 显示工具 |
| `docgen_tools.py` | 文档生成 |

### 多代理工具（`component/mutliagenttools/`）

详见 `../subagent/DEV-README.md`。主要工具：

- `register_subagent` / `unregister_subagent`
- `list_subagents`
- `run_subagent` / `chat_subagent` / `stop_subagent`
- `approval_subagent`

---

## 审批系统

### `component/approval.py`

统一审批中心，职责：

- **Normal 模式**：危险操作通过前端弹窗请求用户实时确认。
- **Adventure 模式**：本地 GGUF 模型自动评估工具调用风险并决定通过/拒绝。
- 管理审批请求生命周期，与 `approval_subagent`（子代理审批）协同。

### `component/approval_allowlist.py`

定义只读 / 自动通过工具的允许列表。命中白名单的工具无需弹窗或模型审批。

### 审批流程

1. `BasePrivateChatAgentLoop._execute_tool()` 判断工具危险等级。
2. 若工具在 allowlist 中或危险等级为 `readonly`，直接执行。
3. 否则通过 `AgentSink.request_approval()` 弹出确认请求。
4. 前端用户确认或 Adventure 模型决策后，审批结果回传，继续执行。

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

- 接收 Cron 工具创建的后台任务。
- 维护任务注册表与触发调度。
- 通过 inbox 将 Cron 结果注入对应 `ParentAgentLoop`。
- 提供 REST API：`/api/sessions/{id}/cron-tasks/...`。