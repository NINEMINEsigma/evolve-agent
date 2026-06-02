# Evolve Agent

一个具备自我代码进化能力的人工智能代理。Agent 在运行时分析自身, 将改进后的代码写入进化目标目录, 通过验证后触发 **fast-slow 交换**——编排器自动备份当前版本并热替换为新代码, 重启后以进化后的形态继续运行。

## 安装

```bash
git clone ... --recurse-submodules
git submodule update --init --recursive
# git pull --recurse-submodules
```

## 核心机制：Fast-Slow-Fallback 演化循环

以下为默认配置时的参考

```
origin_agent/           ← origin源仓库
workspace/
  fast_agent_space/     ← fast仓库, 当前运行的 agent 副本
  slow_agent_space/     ← slow仓库/fork仓库, 初始化和进化后的一个滞后 agent 副本
  .fallback/            ← 上一次 fast 的备份, 用于进化失败后的修正
  logs/                 ← 运行时日志、会话历史、进化状态
  agentspace/           ← agent 所使用的工作目录
```

1. `run.py` 将 `origin_agent/` 完整复制到 `fast_agent_space/` 和 `slow_agent_space/`, 启动 `fast_agent_space/`。
2. LLM 通过工具链 **读取自身源码 → 写入 fork: 命名空间 → 语法验证 → 触发进化**, 以退出码 -1 通知编排器。
3. 编排器执行 `fast → .fallback` 备份 + `slow → fast` 交换, 重启 agent。
4. 若进化后运行出错, 编排器自动进入 **fallback 模式**：启动 `.fallback/` 中的备份代码修复 `fast_agent_space/`, 修复成功后恢复正常运行。

## 项目结构

```
origin_agent/
├── abstract/              ← 抽象层（工具注册、内存管理、插件发现、MCP、技能管理）
│   ├── tools/             ← 工具注册表 + AST 扫描自动发现
│   ├── memory/            ← Memory Provider 管理器 + 流式上下文清洗
│   ├── plugins/           ← 基于目录的插件发现系统
│   ├── mcp/               ← MCP 客户端（client）、OAuth 管理（oauth_manager, oauth）
│   └── skills/            ← 技能管理器（frontmatter 解析、加载、生命周期管理）
├── component/             ← 具体实现
│   ├── tools/             ← 核心工具（filesystem, code, shell, frontend, skills, read_image, run_python）
│   ├── extools/           ← 扩展工具集
│   ├── llm.py             ← LLM 客户端
│   └── mcp_tools.py       ← MCP 工具桥接
├── system/                ← 基础设施
│   ├── sandbox.py         ← 路径沙盒（self:/fork:/ws:/fix: 命名空间）
│   ├── prompt.py          ← System Prompt 组装
│   ├── context.py         ← RuntimeContext
│   └── pathutils.py       ← 路径工具
├── evolve/                ← 进化系统
│   ├── code.py            ← 进化编排（验证 + 触发交换）
│   └── validator.py       ← 语法 + 编译检查
├── entry/                 ← Agent 主循环
│   └── agent.py           ← 消息处理、工具调用、上下文压缩
├── gateway/               ← WebSocket + HTTP 网关
│   ├── server.py          ← FastAPI 服务器
│   └── chat.py            ← 聊天协议
├── dashboard/             ← Web 管理面板
├── memory/                ← Memory Provider 实现
├── templates/             ← Prompt 模板（中/英文）
│   ├── modes/             ← 运行时模式模板（fast, fallback）
│   └── zh/
│       └── modes/         ← 中文模式模板
├── frontend/              ← React + Vite + TypeScript 前端
│   ├── src/               ← 源码（App.tsx, App.css）
│   ├── index.html, vite.config.ts, tsconfig*.json, package.json
├── __main__.py            ← 入口点
└── main.py                ← App 生命周期管理
```

### abstract — 抽象层

`abstract/` 提供了独立于具体 agent 实现的通用基础设施：

- **工具注册表**（`abstract/tools/registry.py`）：线程安全的中央注册表, 支持工具注册、注销、按 toolset 分组、检查函数缓存、schema 动态覆盖。提供 `registry.register()` 模块级注册模式和 `registry.dispatch()` 按名分发。
- **AST 扫描自动发现**（`abstract/tools/discover.py`）：纯 stdlib 实现, 通过 AST 解析扫描 `.py` 文件中的 `registry.register()` 调用, 无需显式导入即可自动发现工具模块。
- **Memory Manager**（`abstract/memory/manager.py`）：编排内置 + 最多一个外部 memory provider, 提供预取、回合同步、流式上下文清洗（跨 chunk 的 `<memory-context>` 标签剥离）等能力。
- **插件发现**（`abstract/plugins/discover.py`）：基于目录的插件扫描, 启发式检测插件类型（MemoryProvider、ContextEngine、ToolProvider 等）, 不依赖 PyYAML 即可解析 `plugin.yaml` 元数据。
- **MCP 客户端**（`abstract/mcp/client.py`）：MCP 协议客户端实现, 支持多 server 连接、OAuth 认证（`oauth.py` / `oauth_manager.py`）、工具调用转发。
- **技能管理**（`abstract/skills/`）：从 frontmatter 元数据解析到技能加载、生命周期管理的完整技能系统（`manager.py`, `loader.py`, `frontmatter.py`）。

### extools — 扩展工具集

`component/extools/` 提供了一系列扩展工具, 在模块导入时自动注册到工具注册表：

| 工具 | 能力 |
|------|------|
| `web_search` | 搜索引擎查询 |
| `web_fetch` | 网页内容抓取 |
| `csv_tools` | CSV 文件读写 |
| `excel_tools` | Excel（.xlsx）文件读写 |
| `docx_tools` | Word（.docx）文档读取 |
| `pdf_tools` | PDF 文档读取 |
| `diff_tools` | 文件差异对比与 patch 应用 |
| `ffmpeg_tools` | FFmpeg 多媒体处理工具集 |

### 路径沙盒

所有文件操作必须使用逻辑路径前缀, 禁止裸路径和 `..` 遍历：

| 前缀 | 映射 | 模式 | 用途 |
|------|------|------|------|
| `self:` | `fast_agent_space/` | fast | 只读 — 读自身源码 |
| `fork:` | `slow_agent_space/` | fast | 写入进化代码 |
| `ws:` | `agentspace/` | fast / fallback | 通用 I/O |
| `fix:` | `.fallback/` | fallback | 修复目标 |

### pre-skills — 内建推荐技能

`pre-skills/` 包含面向 Evolve Agent 自我进化的内建技能指南, 可直接作为 agent 的技能文件使用：

| 技能 | 用途 |
|------|------|
| `evolve-architect` | 系统架构设计与模块规划 |
| `evolve-code-engineer` | 代码进化安全指南（fast-slow-fallback 流程） |
| `evolve-code-validator` | 进化代码验证策略 |
| `evolve-debugger` | 运行时错误诊断与修复 |
| `evolve-frontend-builder` | 前端构建与部署 |
| `evolve-memory-manager` | Memory Provider 管理 |
| `evolve-prompt-engineer` | System Prompt 模板优化 |
| `evolve-refactoring` | 代码重构最佳实践 |
| `evolve-sandbox-operator` | 路径沙盒操作指南 |
| `evolve-testing` | 进化代码的测试策略 |
| `evolve-tool-creator` | 新工具开发模板与规范 |
| `pymem-memory` | Python 内存分析工具集（进程扫描、指针追踪、内存冻结） |

诸如此类

## 快速开始

### 环境要求

- Python 3.10+
- pnpm（用于前端构建）
- Windows 上需确保 `pnpm.cmd` 在 PATH 中

### 安装

```bash
pip install -r requirements.txt
```

### 配置

设置环境变量：

```bash
$env:OPENAI_API_KEY = "your-api-key"        # 必需
$env:OPENAI_BASE_URL = "https://api.deepseek.com"  # 可选, 覆盖默认地址
```

在 `config.py` 中可调整：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `llm_base_url` | LLM API 地址 | `https://api.deepseek.com` |
| `llm_model` | 模型名称 | `deepseek-v4-flash` |
| `llm_max_context_tokens` | 最大上下文 token 数 | `1000000` |
| `llm_context_upbound` | 上下文压缩触发阈值（比例） | `0.9` |
| `llm_max_output_tokens` | 最大输出 token 数 | `384000` |
| `llm_temperature` | 温度 | `0.95` |
| `gateway_host` / `gateway_port` | Web 界面地址 | `127.0.0.1:8765` |
| `fouce_init` | 设为 `True` 强制重新初始化 workspace | `False` |
| `console_log` | 同时在控制台输出日志 | `True` |
| `mcp_config_path` | MCP 服务器配置文件路径 | `workspace/mcp_config.json` |

### 启动

```bash
python run.py
```

启动后访问 `http://127.0.0.1:8765` 进入 Web 聊天界面。

### 进化流程

在对话中, agent 可以通过以下工具链完成自我进化：

1. `read_file` — 通过 `self:` 前缀读取自身源码（`read_own_source` 已废弃）
2. `write_fork` — 将改进代码写入 `fork:` 命名空间（支持完全覆盖或增量编辑）
3. `validate_code` — Python 语法检查
4. `validate_frontend` — （可选）如修改了前端文件，需执行此工具验证构建
5. `evolve_code` — 深度验证（含 `py_compile`）并触发 fast-slow 交换

验证通过后 agent 以退出码 -1 退出, `run.py` 自动执行 slow→fast 交换并重启。前端将在后端重启后自行重连（超时过长时可刷新页面重连）。