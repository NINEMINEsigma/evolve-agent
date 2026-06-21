# Evolve Agent

一个具备自我代码进化能力的人工智能代理。Agent 在运行时通过工具链读取自身源码副本、修改进化目标、验证并触发 **fast-slow 热交换**——编排器自动备份当前版本并替换为新代码，重启后以进化后的形态继续运行。若进化后运行异常，系统会自动进入 fallback 模式，由备份修复当前副本。

## 安装

克隆仓库并拉取子模块：

```bash
git clone <repo-url> --recurse-submodules
git submodule update --init --recursive
```

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

检查环境（可选，用户按需自行执行）：

```bash
python check_env.py --cuda
```

## 启动

Evolve Agent 支持多种启动方式：

```bash
# 交互式创建或选择配置
python run.py

# 加载已保存的配置键
python run.py --load <config_key>

# 保存当前命令行参数为新配置键
python run.py --save <config_key> --llm_model deepseek-v4-flash

# 强制重新初始化 workspace（首次运行或需要重置时）
python run.py --load <config_key> --fouce_init
```

常用 CLI 参数可覆盖 `config.py` 默认值：

- `--fouce_init`：强制重新初始化 workspace
- `--llm_model`, `--llm_base_url`, `--llm_api_key`
- `--llm_temperature`, `--llm_max_context_tokens`, `--llm_max_output_tokens`, `--llm_reasoning_effort`
- `--approval_model`, `--approval_model_cuda`, `--approval_model_port`
- `--gateway_host`, `--gateway_port`
- `--console_log`

启动后访问 Web 界面：`http://127.0.0.1:8765`。

> 配置持久化在 `config.json`（已 gitignore），其中包含 API 密钥，请勿提交。

## 核心机制：Fast-Slow-Fallback 演化循环

```
origin_agent/           ← 唯一持久化源码真相源
workspace/
  fast_agent_space/     ← 当前运行的 agent 副本
  slow_agent_space/     ← 进化目标副本（fork）
  .fallback/            ← 上一次 fast 的备份
  agentspace/           ← agent 工作目录
  logs/                 ← 运行时日志、会话、进化状态
```

1. `run.py` 将 `origin_agent/` 复制到 `fast_agent_space/` 和 `slow_agent_space/`，启动 `fast_agent_space/__main__.py`。
2. Agent 通过工具链读取 `fork:` 命名空间中的源码，修改后写入 `slow_agent_space/`。
3. 调用 `validate_code` / `validate_frontend` 完成语法与构建验证。
4. 调用 `evolve_code` 完成深度验证并以退出码 `-1` 通知编排器。
5. 编排器执行 `fast → .fallback` 备份、`slow → fast` 交换，重启 agent。
6. 若进化后运行出错，编排器进入 fallback 模式，启动 `.fallback/` 中的备份修复 `fast_agent_space/`，修复成功后恢复运行。

## 项目结构

```
origin_agent/
├── abstract/              ← 抽象层
│   ├── tools/             ← 工具注册表 + AST 自动发现
│   ├── memory/            ← Memory Provider 抽象 + 上下文清洗
│   ├── plugins/           ← 基于目录的插件发现
│   ├── mcp/               ← MCP 客户端与 OAuth 管理
│   └── skills/            ← 技能解析、加载与生命周期管理
├── component/             ← 具体实现
│   ├── tools/             ← 核心工具（filesystem, code, shell, frontend 等）
│   ├── extools/           ← 扩展工具集（web_search, cron, ssh, browser 等）
│   ├── llm.py             ← LLM 客户端（chat + chat_stream）
│   ├── approval.py        ← 统一审批模块
│   └── mcp_tools.py       ← MCP 工具桥接
├── entity/                ← 常量与纯类型定义
│   ├── constant.py
│   └── puretype.py
├── system/                ← 基础设施
│   ├── sandbox.py         ← 路径沙盒（fork:/ws:/fix: 命名空间）
│   ├── prompt.py          ← System Prompt 组装
│   ├── context.py         ← RuntimeContext
│   ├── session_store.py   ← 会话持久化
│   └── pathutils.py       ← 路径工具
├── evolve/                ← 进化系统
│   ├── code.py            ← 进化编排与触发
│   └── validator.py       ← 语法 + 编译检查
├── entry/                 ← Agent 主循环
│   ├── agent.py           ← AgentLoop
│   └── agent_support/     ← 消息处理与多模态辅助
├── gateway/               ← WebSocket + HTTP 网关
│   ├── server.py          ← FastAPI 服务器
│   └── chat.py            ← 聊天协议与会话管理
├── dashboard/             ← Web 管理面板
├── memory/                ← Memory Provider 实现
│   └── provider.py
├── templates/             ← Prompt 模板
│   ├── modes/             ← fast / fallback 模式
│   ├── zh/                ← 中文模板
│   └── approval/          ← 审批相关提示词
├── frontend/              ← React + Vite + TypeScript 前端
│   ├── src/
│   │   ├── App.tsx
│   │   ├── hooks/useWebSocket.ts
│   │   ├── components/
│   │   └── styles/
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig*.json
├── __main__.py            ← 入口点
└── main.py                ← App 生命周期管理
```

### abstract — 抽象层

- **工具注册表**（`abstract/tools/registry.py`）：线程安全的中央注册表，支持注册、注销、别名、schema 覆盖与按 toolset 分组。提供 `registry.register()` 模块级注册和 `registry.dispatch()` 按名分发。
- **AST 扫描自动发现**（`abstract/tools/discover.py`）：纯 stdlib 实现，扫描 `.py` 文件中的 `registry.register()` 调用，无需显式导入即可发现工具模块。
- **Memory Manager**（`abstract/memory/manager.py`）：编排内置与外部 memory provider，提供预取、回合同步与流式上下文清洗。
- **插件发现**（`abstract/plugins/discover.py`）：基于目录扫描插件，启发式检测 MemoryProvider、ContextEngine、ToolProvider 等类型，支持 `plugin.yaml` 元数据解析。
- **MCP 客户端**（`abstract/mcp/client.py`）：支持多 server 连接、stdio / HTTP / SSE 传输、OAuth 认证与工具调用转发。
- **技能管理**（`abstract/skills/`）：从 frontmatter 解析到技能加载、生命周期管理的完整技能系统。

### component — 组件实现

- `llm.py`：统一 LLM 客户端，提供 `chat` 与 `chat_stream`。
- `approval.py`：工具审批中心，支持普通模式（前端弹窗确认）与 Adventure 模式（本地 GGUF 模型自动审批）。
- `mcp_tools.py`：将 MCP server 的工具桥接到 `ToolRegistry`。
- `tools/`：核心工具（filesystem、code、shell、frontend、skills、read_image、run_python 等）。
- `extools/`：扩展工具集（web_search、web_fetch、web_browser、ssh_tools、cron_tools、csv/excel/docx/pdf、ffmpeg、diagram、background_service、pip、gui_windows 等）。

## 工具系统

### 注册与发现

工具通过模块级 `registry.register()` 注册，启动时由 AST 扫描自动发现。来源包括：

- `component/tools/` — 核心工具
- `component/extools/` — 扩展工具
- `custom_tools/` — 用户自定义工具（若目录存在）
- MCP server — 通过 `component/mcp_tools.py` 桥接

### 核心工具

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

### 扩展工具集

`component/extools/` 包含网络、定时、文档、媒体、浏览器自动化等工具，例如：

- `web_search.py` / `web_fetch.py` / `web_browser.py` — 网络搜索、抓取、浏览器自动化
- `ssh_tools.py` — SSH 远程执行
- `cron_tools.py` — 一次性/周期性后台定时任务
- `csv_tools.py` / `excel_tools.py` / `docx_tools.py` / `pdf_tools.py` — 文档处理
- `ffmpeg_tools.py` — 音视频处理
- `diagram.py` / `mermaid_tools.py` / `excalidraw_render.py` — 图表渲染
- `background_service.py` — 后台服务管理
- `pip.py` — Python 包管理
- `gui_windows.py` — Windows GUI 自动化

## 扩展机制

### custom_tools

在 `custom_tools/` 目录下编写 `.py` 文件，使用 `registry.register()` 注册，启动时自动加载。

```python
from abstract.tools.registry import registry, tool_result

registry.register(
    name="get_secret_key",
    toolset="custom",
    schema={
        "description": "Return a fixed test secret.",
        "parameters": {"type": "object", "properties": {}},
    },
    handler=lambda _: tool_result(password="sk-test-password-12345"),
    is_async=False,
)
```

### custom_models

放置 `.gguf` 模型文件，可作为 Adventure 审批模型自动加载。配置项 `approval_model` 指向该目录下的模型文件名。

### custom_hooks

`custom_hooks/` 下 `.py` 文件实现 `hook_tag_name(session_id, workspace)` 与 `hook_message(session_id, workspace)`，返回的上下文块会追加到最后一条用户消息末尾，用于实时生成扩展上下文。

### skills

运行时 `skills/` 目录用于存放技能文件（gitignored）。启动时自动创建 `skills/self-evolution/SKILL.md`。可通过 `load_skill` / `list_skills` 工具加载。`pre-skills/` 目录提供面向自我进化的推荐技能模板。

### plugins

`abstract/plugins/discover.py` 基于目录扫描插件，解析 `plugin.yaml`，启发式检测 MemoryProvider、ContextEngine、ToolProvider 等类型。

### MCP

配置 `workspace/mcp_config.json`：

```json
{
  "time": {"command": "uvx", "args": ["mcp-server-time"]},
  "remote": {"url": "http://localhost:8000/mcp", "headers": {}}
}
```

`component/mcp_tools.py` 启动时连接 server 并注册工具。

## 路径沙盒

所有文件操作必须使用逻辑路径前缀，禁止裸路径、`..` 遍历和绝对路径。

| 前缀 | 映射目录 | 模式 | 用途 |
|------|----------|------|------|
| `fork:` | `workspace/slow_agent_space/` | fast | 读写进化代码 |
| `ws:` | `workspace/agentspace/` | fast / fallback | 通用 I/O |
| `fix:` | `workspace/.fallback/` | fallback | 修复目标 |
| `skills:` | `skills/` | fast / fallback | 技能读写 |

Agent 通过 `fork:` 读取自身源码副本，不存在 `self:` 命名空间。

## 会话与记忆

### SessionManager

`gateway/chat.py` 中的 `SessionManager` 管理会话生命周期：

- 每个会话为 12 位十六进制 ID。
- 持久化到 `workspace/logs/sessions/_index.json`。
- 支持 `title`、`status`、`pinned`、`tags`、`parents`、`continuation`、`last_activity_at` 等字段。
- 会话可按需归档、合并、分支、置顶、删除。

### SessionStore

`system/session_store.py` 持久化单个会话数据：

- `messages.jsonl`：消息历史
- `summary.txt`：会话摘要
- `token_usage.json`：token 消耗
- `tool_resources.json`：任务进度、剪贴板展示等

### 自动标题与标签

`entry/agent.py` 提供：

- `auto_generate_title(session_id)`：基于会话内容生成标题。
- `generate_session_tags(session_id, force=False)` / `regenerate_session_tags(session_id)`：基于会话摘要生成或重新生成标签。
- 首条用户消息发送时若标题为空，取前 30 字符作为初始标题。

### Memory Provider

- `abstract/memory/provider.py`：抽象基类。
- `abstract/memory/manager.py`：编排内置与外部 provider。
- `memory/provider.py`：`EasysaveMemoryProvider` 基于 `third/easysave` 持久化。
- 提供工具：`recall_memory`、`remember`。

## 网关 API

`gateway/server.py` 提供 FastAPI HTTP 与 WebSocket 服务。

### REST 端点

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/` | 前端 `index.html` |
| GET | `/health` | 健康检查 |
| GET | `/api/sessions` | 会话列表 |
| GET | `/api/tags` | 全局标签列表 |
| PUT | `/api/sessions/{id}/tags` | 更新会话标签 |
| PUT | `/api/sessions/{id}/title` | 手动设置标题 |
| POST | `/api/sessions/{id}/auto-title` | 自动生成标题 |
| POST | `/api/sessions/{id}/auto-tags` | 自动生成标签 |
| POST | `/api/sessions/{id}/terminate` | 终结会话（归档+摘要） |
| POST | `/api/sessions/{id}/pin` | 置顶切换 |
| POST | `/api/sessions/{id}/branch` | 从会话创建分支 |
| POST | `/api/sessions/merge` | 合并多个已归档会话 |
| DELETE | `/api/sessions/{id}` | 删除会话 |
| PUT | `/api/sessions/{id}/messages/{index}` | 编辑历史消息 |
| POST | `/api/confirm/{request_id}` | 审批响应 |
| POST | `/api/ask/{request_id}` | 提问响应 |
| POST | `/api/interrupt/{session_id}` | 中断会话 |
| POST | `/api/file-picker` | 系统文件选择器 |
| GET/POST | `/api/sessions/{id}/background-tasks` | 后台任务列表/停止 |
| GET/POST | `/api/sessions/{id}/cron-tasks/...` | Cron 任务列表/触发/取消 |
| POST | `/api/shutdown-approval-model` | 关闭审批模型服务 |
| GET | `/uploads/{path}` | 静态文件访问 |
| GET | `/downloads/{path}` | 文件下载 |

### WebSocket

- `WS /ws/chat`：聊天主通道。
  - 支持 `resume=?sid` 查询参数恢复会话。
  - 连接时发送 `build_hash`、`server_info`。
  - 恢复会话时回放 `session_history`。

消息类型包括：`user_message`、`agent_message`、`tool_call`、`tool_result`、`stream_delta`、`stream_done`、`confirm_request`、`ask_request`、`interrupt`、`system`、`error`、`task_progress`、`clipboard_display` 等。

## 进化流程

在对话中，agent 可通过以下工具链完成自我进化：

1. `read_file` — 通过 `fork:` 前缀读取待进化代码。
2. `write_fork` 或 `edit_file` — 将改进代码写入 `fork:` 命名空间。
3. `validate_code` — Python 语法与 AST 检查。
4. `validate_frontend` — 若修改了前端文件，执行构建验证。
5. `evolve_code` — 深度验证（含 `py_compile`）并触发 fast-slow 交换。

验证通过后 agent 以退出码 `-1` 退出，`run.py` 自动执行 slow→fast 交换并重启。前端在检测到 `build_hash` 变化时会提示刷新。

## 配置项

`config.py` 中的主要字段与默认值：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `llm_base_url` | `https://api.deepseek.com` | LLM API 地址 |
| `llm_model` | `deepseek-v4-flash` | 模型名称 |
| `llm_api_key` | `OPENAI_API_KEY` 环境变量 | API 密钥 |
| `llm_max_context_tokens` | `1000000` | 最大上下文 token |
| `llm_max_output_tokens` | `384000` | 最大输出 token |
| `llm_temperature` | `0.95` | 采样温度 |
| `llm_reasoning_effort` | `medium` | reasoning 力度 |
| `gateway_host` | `127.0.0.1` | Web 网关地址 |
| `gateway_port` | `8765` | Web 网关端口 |
| `console_log` | `True` | 是否在控制台输出日志 |
| `fouce_init` | `False` | 强制重新初始化 workspace |
| `workspace_path` | `workspace` | workspace 根目录 |
| `fast_agent_space_path` | `fast_agent_space` | fast 副本目录 |
| `slow_agent_space_path` | `slow_agent_space` | slow 副本目录 |
| `agentspace_path_name` | `agentspace` | agent 工作目录名 |
| `logs_path_name` | `logs` | 日志目录名 |
| `mcp_config_path_name` | `mcp_config.json` | MCP 配置文件名 |
| `approval_model` | `Qwen3.5-0.8B-Q8_0.gguf` | 审批模型文件名 |
| `approval_model_n_ctx` | `65536` | 审批模型上下文窗口 |
| `approval_model_cuda` | `True` | 审批模型使用 CUDA |
| `approval_model_port` | `8081` | 审批模型服务端口 |
| `merge_concat_threshold` | `50000` | 会话合并摘要截断阈值 |

## 环境要求

- Python 3.10+
- pnpm（前端构建依赖）
- Windows 上需确保 `pnpm.cmd` 在 PATH 中
- 可选：CUDA 环境与本地 GGUF 审批模型
