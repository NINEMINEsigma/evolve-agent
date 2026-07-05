# abstract/ — 抽象层

`abstract/` 是 Evolve Agent 的抽象层，定义工具注册表、AST 发现、记忆、技能、插件、MCP 客户端等核心抽象。这些模块不依赖具体实现，可被 `component/`、`memory/`、`custom_tools/` 等复用。

---

## 文件结构

```
abstract/
├── tools/
│   ├── registry.py          ← 工具注册表
│   ├── discover.py          ← AST 自动发现
│   └── ui_event_router.py   ← UI 事件路由
├── memory/
│   ├── provider.py          ← MemoryProvider 抽象基类
│   ├── manager.py           ← MemoryManager 编排
│   └── sanitize.py          ← 上下文清洗
├── skills/
│   ├── frontmatter.py       ← frontmatter 解析
│   ├── loader.py            ← 技能加载
│   └── manager.py           ← 技能生命周期管理
├── plugins/
│   └── discover.py          ← 插件发现
└── mcp/
    ├── client.py            ← MCP 客户端
    ├── oauth.py             ← OAuth 认证
    └── oauth_manager.py     ← OAuth 管理
```

---

## 工具注册表

### `abstract/tools/registry.py`

`ToolRegistry` 是线程安全的中央注册表单例，提供：

- `registry.register()`：模块级注册，声明 schema、handler、toolset、危险等级、`availability` 位掩码等。
- `registry.dispatch(name, args, context)`：按名分发工具调用。
- toolset 别名、schema 覆盖、动态 schema（`check_fn` + 30s TTL 缓存）。
- 按 `availability` 过滤：`MAIN`（主 Agent）、`SUBAGENT`（子 Agent）、`EVERY`（两者）。

每个工具注册后生成 `ToolEntry`，包含：

- `name`, `toolset`, `schema`
- `handler`（同步或异步）
- `is_async`, `danger_level`
- `availability`：位掩码
- `emit_for`：需要向前端推送的事件类型列表

### `abstract/tools/discover.py`

纯 stdlib 实现：

- 扫描指定目录下的 `.py` 文件。
- 检测模块级别的 `registry.register()` 调用。
- 自动 `importlib.import_module()` 加载工具模块。
- 无需在核心代码中显式导入新工具文件。

### `abstract/tools/ui_event_router.py`

- 提供工具级前端 emit handler 注册。
- 工具执行后由 `emit_for()` 统一分发事件到前端，例如 `task_progress`、`clipboard_display`、`subagent_update`。
- 避免工具直接耦合 WebSocket 细节。

---

## 记忆系统

### `abstract/memory/provider.py`

`MemoryProvider` 抽象基类，定义：

- `prefetch(session_id, context)`：预取记忆上下文。
- `sync(session_id, history)`：同步历史到记忆。
- `tools()`：返回该 provider 提供的工具（如 `recall_memory`、`remember`）。

### `abstract/memory/manager.py`

`MemoryManager` 编排：

- 一个内置 memory provider + 最多一个外部 provider。
- `prefetch_all()`：预取所有 provider 的上下文。
- `sync_all()`：将历史同步到所有 provider。
- 流式/一次性上下文清洗，剥离 memory context fence tag。

### `abstract/memory/sanitize.py`

独立的上下文清洗器，用于剥离记忆相关的 fence tag。注意：当前与 `manager.py` 使用的 fence tag 不完全一致（manager 用 `<|im_memory_context_start|>`，sanitize 用 `<memory-context>`），这是已知实现分裂。

---

## 技能系统

### `abstract/skills/`

- `frontmatter.py`：解析 `SKILL.md` 的 YAML frontmatter 元数据。
- `loader.py`：加载技能文件内容。
- `manager.py`：技能的增删改查、frontmatter 脚手架、子目录文件（`references/`、`templates/`、`scripts/`、`assets/`）管理。

技能文件位于运行时 `skills/` 目录，通过 `load_skill` / `list_skills` 工具加载，并作为提示块注入 system prompt。

---

## 插件发现

### `abstract/plugins/discover.py`

- 基于目录扫描插件子目录。
- 要求子目录含非空 `__init__.py`。
- 启发式检测类型：`MemoryProvider`、`ContextEngine`、`ModelProvider`、`ToolProvider`、`ImageGenProvider` 等。
- 读取简化版 `plugin.yaml` 元数据。

---

## MCP 客户端

### `abstract/mcp/client.py`

多 server MCP 客户端，支持：

- **传输**：stdio、HTTP/StreamableHTTP、SSE。
- **认证**：OAuth 2.1 PKCE。
- **Server-initiated sampling**：`sampling/createMessage`。
- **动态工具刷新**：`notifications/tools/list_changed`。
- **并发工具调用**：可开关。
- 凭据脱敏、提示注入扫描、重连退避。

配置默认从 `~/.hermes/config.yaml` 的 `mcp_servers` 键读取；当通过 `component/mcp_tools.py` 调用 `register_mcp_servers(servers)` 时，使用传入的配置。

---

## 与 component/ 的关系

`abstract/` 定义接口与通用逻辑，`component/` 提供具体实现：

| abstract | component |
|---|---|
| `ToolRegistry` | `component/tools/`, `component/extools/`, `component/mutliagenttools/` |
| `MemoryProvider` | `memory/provider.py` |
| `MemoryManager` | 被 `ParentAgentLoop` 使用 |
| `SkillManager` | `component/tools/skills.py` |
| `MCPClient` | `component/mcp_tools.py` |
| `PluginDiscover` | 启动时扫描 `plugins/` 目录 |