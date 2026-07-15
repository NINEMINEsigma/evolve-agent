# abstract/ — 抽象层

`abstract/` 是 Evolve Agent 的抽象层，定义 LLM 客户端、工具注册表、AST 发现、技能、插件、MCP 客户端等核心抽象。这些模块不依赖具体实现，可被 `component/`、`custom_tools/`、`custom_llm_client/` 等复用。

---

## 文件结构

```
abstract/
├── llm/                        ← LLM 客户端抽象层
│   ├── client.py               ← BaseLLMClient 抽象基类
│   ├── loader.py               ← 动态加载器（create_llm_client 工厂）
│   └── formats.py              ← wire format 转换器（OpenAI / Anthropic）
├── tools/
│   ├── registry.py             ← 工具注册表
│   ├── discover.py             ← AST 自动发现
│   └── ui_event_router.py      ← UI 事件路由
├── skills/
│   ├── frontmatter.py          ← frontmatter 解析
│   ├── loader.py               ← 技能加载
│   └── manager.py              ← 技能生命周期管理
├── plugins/
│   └── discover.py             ← 插件发现
└── mcp/
    ├── client.py               ← MCP 客户端
    ├── oauth.py                ← OAuth 认证
    └── oauth_manager.py        ← OAuth 管理
```

---

## LLM 客户端抽象层

### `abstract/llm/`

新增的 LLM 抽象层，将 LLM 调用从具体后端解耦。所有 Agent 循环（`ParentAgentLoop`、`MultiAgentWorker`、`SubAgentLoop`）通过 `BaseLLMClient` 接口调用大模型，具体实现由 `custom_llm_client/` 插件提供。

#### `abstract/llm/client.py` — `BaseLLMClient`

抽象基类（继承 `ABC`），声明所有 LLM 后端必须支持的两个接口：

- `chat(messages, tools, response_format, character) -> LLMResponse`：非流式调用，返回完整结构化响应。
- `chat_stream(messages, tools, response_format, character) -> AsyncIterator[StreamChunk]`：流式调用，逐块 yield 增量。

**关键设计**：
- 抽象层不依赖 `RuntimeContext`，保持后端无关。
- `messages` 参数类型为 `list[BaseMessage]`（非 `list[dict]`），子类在发送前自行调用 `to_openai_message()` 或 `messages_to_anthropic_list()` 转换为 wire format。
- `character` 参数为当前运行中的 agent 角色名，用于消息转换时的可见性过滤和前缀修饰。
- 子类必须实现 `_convert_messages()` 将 `list[BaseMessage]` 转换为对应 LLM 后端的 wire format。

#### `abstract/llm/loader.py` — `create_llm_client()`

动态加载器，按名称从 `custom_llm_client/<name>.py` 加载实现模块：

```
create_llm_client(name, runtime_context, profile) -> BaseLLMClient
```

- 通过 `_ensure_namespace_package()` 将 `custom_llm_client/` 注册为命名空间包（无需 `__init__.py`）。
- 调用模块暴露的 `create_llm_client(runtime_context, profile)` 工厂函数构造客户端实例。
- 校验返回值是否为 `BaseLLMClient` 子类。
- `list_llm_clients()` 返回目录下所有可选客户端模块名。
- 内置实现：`openai_client.py`、`anthropic_client.py`。

#### `abstract/llm/formats.py` — wire format 转换器

提供两种 LLM wire format 的消息转换器，供 `custom_llm_client/` 中的具体客户端复用：

**OpenAI 格式**：
- `to_openai_message(message, current_character_agent) -> dict | None`：单条消息转换，按 `isinstance` 分派到三个私有转换器。返回 `None` 表示该消息对当前 agent 不可见。
- `messages_to_openai_list(messages, current_character_agent) -> list[dict]`：批量转换。
- `to_summary_dict(message, current_character_agent) -> dict | None`：生成最小化 `{"role": ..., "content": raw_text}` 用于 prompt 模板（auto-title / auto-tag / summary）。

**Anthropic 格式**：
- `messages_to_anthropic_list(messages, current_character_agent) -> (anthropic_messages, system_text)`：直接从 `list[BaseMessage]` 构建 Anthropic Messages API 格式，无需经过 OpenAI 中间层。
  - system 消息提取到顶层 `system` 参数。
  - 工具调用结果转为 `tool_result` content block，放在 user 消息中。
  - 助手消息的 `tool_calls` 转为 `tool_use` content block。
  - reasoning 内容转为 `thinking` content block。

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

## 与其他模块的关系

`abstract/` 定义接口与通用逻辑，`component/` 和 `custom_*/` 提供具体实现：

| abstract | 具体实现 |
|---|---|
| `BaseLLMClient` | `custom_llm_client/openai_client.py`、`custom_llm_client/anthropic_client.py` |
| `to_openai_message()` / `messages_to_anthropic_list()` | 被 `custom_llm_client/` 中的客户端调用 |
| `ToolRegistry` | `component/extools/`、`component/mutliagenttools/`、`custom_tools/` |
| `SkillManager` | `component/extools/` 中的 `load_skill` / `list_skills` 工具 |
| `MCPClient` | `component/mcp_tools.py` |
| `PluginDiscover` | 启动时扫描 `plugins/` 目录 |

### 扩展点

- **自定义 LLM 客户端**：在 `custom_llm_client/` 下编写 `.py` 文件，暴露 `create_llm_client(runtime_context, profile)` 工厂函数，返回 `BaseLLMClient` 子类实例。
- **自定义工具**：在 `custom_tools/` 目录下编写 `.py` 文件，使用 `registry.register()` 注册，启动时由 AST 扫描自动发现。
- **自定义钩子**：在 `custom_hooks/` 下实现 `hook_tag_name()` 与 `hook_message()`，返回的上下文块会追加到用户消息末尾。