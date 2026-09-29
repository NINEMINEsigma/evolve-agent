# Evolve Agent — 开发者文档

本文档面向需要理解、修改或扩展 Evolve Agent 的开发者。若你只是想安装和使用，请阅读根目录的 `README.md`。

---

## 设计目标

Evolve Agent 是一个以**运行时自我代码进化**为核心目标的 Agent。其设计围绕以下原则：

- **唯一持久化源码**：`origin_agent/` 是唯一的源码真相源。所有运行时副本均由其派生，修改只对源码生效。
- **运行时副本隔离**：`workspace/fast_agent_space/`、`workspace/slow_agent_space/`、`workspace/.fallback/` 彼此隔离，任何进化失败都不会直接破坏当前运行实例。
- **fast-slow-fallback 进化循环**：Agent 通过工具链修改进化目标副本，验证通过后触发热交换；若新代码运行异常，自动回退到备份。
- **会话级隔离 + 全局索引**：每个用户连接对应独立会话，会话历史、资源、子代理均按会话隔离，同时维护全局索引支持检索与管理。

---

## 源码与运行时布局

> workspace 及其内部目录（fast/slow 空间、agentspace、logs）均为**默认配置名**，可由 config.py 参数（`workspace_path`、`fast_agent_space_path`、`slow_agent_space_path`、`agentspace_path_name`、`logs_path_name`）覆盖；只有 `.fallback/` 为 run.py 硬编码固定名。下列以默认名描述。

```
origin_agent/              <- origin仓库：唯一持久化源码真相源（修改这里）
workspace/                 <- 运行时根（默认名；整体被 gitignore）
  fast_agent_space/        <- fast仓库：当前运行的 agent 副本（默认名）
  slow_agent_space/        <- slow仓库：进化目标副本（fork: 命名空间）（默认名）
  .fallback/               <- fallback仓库：上一次 fast 的备份 / 回退修复体（固定名）
  agentspace/              <- 工作空间：agent 工作目录（ws: 命名空间）（默认名）
  dynamic_sandbox_spaces.es <- fast 模式全局动态沙盒空间配置（独立 easysave 根对象）
  sessions/                <- 会话持久化（各主会话含 approval_mode.es 审批模式状态）
  logs/                    <- 运行时日志、进化状态（默认名）
```

## origin仓库内容边界

`origin_agent/` 会被整体派生为 fast仓库、slow仓库和 fallback仓库，因此只允许包含正式运行源码和构建必需文件。禁止在其中新增或保留自动化测试源、测试运行配置、测试夹具和测试专用入口。发现违规内容时，应从 origin仓库定向移除，不得通过复制过滤、`.gitignore` 或其他忽略规则隐藏；运行时仓库的复制语义保持不变。

---

## 启动与生命周期

1. `run.py` 将 `origin_agent/` 复制到 `fast_agent_space/` 和 `slow_agent_space/`。
2. 启动 `fast_agent_space/__main__.py`。
3. `__main__.py` 解析 CLI、构造 `RuntimeContext`、构建前端。
4. `main.py` 中的 `Application` 单例初始化 gateway、沙盒、`AgentspaceService`、`LLMProfileStore`、`SessionMetadataService`、`ApprovalModeStore`、工具发现、审批后端、SessionManager、ParentAgentLoop、SubAgentOrchestrator。
5. `AgentspaceService` 在 Gateway 接受请求前启动垃圾桶恢复与文件变化 watcher；watcher 不可用时降级但不影响 REST、版本校验和文件锁。
6. 启动 uvicorn，监听 `WS /ws/chat`、REST API 与 Agentspace SSE。聊天页的 Agent 舞台层、会话网页和会话聊天区自定义样式复用各自已有的会话 WebSocket接收 typed `agentspace_event`，不再建立额外 SSE；独立 Agentspace 编辑器继续使用一条 SSE。关闭时 `main.py::App` 设置由 `Application.shutdown_event` 暴露的进程关闭信号，事件流据此退出；`App._stop_gateway()` 再设置 uvicorn 的退出标志，等待 Gateway 完成连接与 lifespan 清理，超过 `GATEWAY_SHUTDOWN_TIMEOUT_SECONDS` 才强制取消任务，以免正常手动结束或进化热交换时打印 `CancelledError` 堆栈。
7. 用户连接后，`SessionManager` 创建新的 `ParentAgentLoop` 实例并绑定 `FrontendSink`。

Shell会话由 `Application.shell_manager` 统一持有。Agent 通过五个 Shell 工具跨工具调用操作 Windows ConPTY；单条命令完成或当前回复结束不触发停止，未完成任务或后续可复用时保留 Shell会话，只有明确需要销毁整个 Shell 时才调用 `StopShell`。WebSocket 断线不停止，自动旋转迁移到延续会话，手动终结、永久删除、进化热交换与应用关闭时停止。Shell 输出仅由 Agent 拉取，前端资源抽屉只显示元数据与停止按钮。单个 Shell会话的原生 PTY 访问通过生命周期同步边界收敛，停止流程先等待 reader 收尾再关闭原生对象，并保留超时兜底日志；该防御性处理不等同于已确认 `0xC0000005` 根因。

主会话永久删除使用进程内删除中标记封闭并发恢复：Gateway 先使现有 WebSocket失效并停止子Agent，再回收活动回复、运行时 Loop、消息队列、客户端信息和 Cron 注册，最后删除持久化索引/目录及附带资源。已建立连接以 WebSocket 4004关闭码停止旧 ID重连；握手前拒绝通过会话状态接口二次确认。显式恢复已经删除或删除中的 ID不会创建随机新会话，当前前端固定切换到“随意聊聊”。

进化流程：

1. Agent 通过工具链读取 `fork:` 命名空间中的源码，修改后写入 `slow_agent_space/`。
2. 调用 `validate_code` / `validate_frontend` 完成语法与构建验证。
3. 调用 `evolve_code` 完成深度验证并请求以退出码 `-1` 退出。
4. `run.py` 执行 `fast -> .fallback` 备份、`slow -> fast` 交换，重启 agent。
5. 若进化后运行出错，进入 fallback 模式，由 `.fallback/` 修复 `fast_agent_space/`。

---

## 模块地图

| 模块 | 职责 | 详细文档 |
|---|---|---|
| `entry/` | Agent 主循环与抽象：`BaseAgentLoop`、`ParentAgentLoop`、`ColloquyLoop`、`MultiAgentLoop`、`LoopSessionManager`、`AgentSink`、`ToolExecutor`、`StreamConsumer`、`SessionMessageQueue`（会话级消息队列）、`tool_post_dispatch.finalize_tool_result`（工具结果统一后处理） | [entry/DEV-README.md](origin_agent/entry/DEV-README.md) |
| `subagent/` | 子代理编排与生命周期：`SubAgentOrchestrator`、`SubAgentLoop`、`TaskAgentLoop`（临时Agent：无系统提示词、无持久化、纯文本回复即终止） | [subagent/DEV-README.md](origin_agent/subagent/DEV-README.md) |
| `gateway/` | WebSocket / HTTP 网关、消息路由、会话管理 | [gateway/DEV-README.md](origin_agent/gateway/DEV-README.md) |
| `component/` | 工具实现、审批系统（目录化）、MCP 桥接、Cron 路由、桌面自动化（`automation/`）、浏览器控制（`browser/`） | [component/DEV-README.md](origin_agent/component/DEV-README.md) |
| `abstract/` | 抽象层：LLM 客户端、工具注册表（含 `ToolsetEntry` 工具集元数据与渐进式加载）、AST 发现、技能、插件、MCP 客户端 | [abstract/DEV-README.md](origin_agent/abstract/DEV-README.md) |
| `frontend/` | React + Vite + TypeScript 前端 | [frontend/DEV-README.md](origin_agent/frontend/DEV-README.md) |
| `system/` | 基础设施：`Application`、`RuntimeContext`、沙盒、路径工具、会话存储、模板、LSP（`lsp.py`）、转换工具 | 见下文 |
| `evolve/` | 进化系统：代码交换与验证 | 见下文 |
| `entity/` | 常量与纯类型定义：`messages.py`（`BaseMessage` 体系）、`puretype/`（包）、`constant/`（按职责拆分的全局常量包，`__init__.py` 统一导出） | 见相关模块文档 |
| `templates/` | Prompt 模板 `.txt` 文件与模式切换（含 `modes/`、`multiagent/`、`subagent/`、`approval/`、`evolve/`、`llm/`、`messages/` 子目录） | 见 `system/prompt.py` |

---

## 端到端数据流

```mermaid
sequenceDiagram
    participant FE as 前端 (React)
    participant GW as gateway/server.py
    participant MR as gateway/message_router.py
    participant SM as gateway/session_manager.py
    participant PAL as entry/parent_agent_loop.py
    participant LLM as abstract/llm/ (BaseLLMClient)
    participant TR as abstract/tools/registry.py
    participant APP as component/approval/

    FE->>GW: WS user_message
    GW->>MR: MessageRouter.route()
    MR->>SM: route to ParentAgentLoop
    SM->>PAL: process_message()
    PAL->>PAL: append_user_message, build system prompt + hooks + memory
    PAL->>LLM: chat_stream(BaseMessage[])
    LLM-->>PAL: StreamChunk (text delta / tool_calls)
    PAL-->>GW: stream_delta / tool_call events
    GW-->>FE: 实时渲染
    PAL->>TR: dispatch(tool_name)
    TR->>APP: request_approval (if needed)
    APP-->>PAL: approval decision
    PAL->>PAL: append tool result, continue loop
    PAL-->>GW: stream_done
    GW-->>FE: stream_done
```

主要阶段说明：

- **消息接收**：`gateway/server.py` 通过 WebSocket 接收 `user_message`，经 `gateway/message_router.py` 路由，交给 `SessionManager` 分配到对应 `ParentAgentLoop`。
- **上下文组装**：`entry/agent_support/messages.py` 加载 `custom_hooks`、memory 上下文、system prompt，组装成 `BaseMessage` 列表。
- **流式生成**：通过 `abstract/llm/` 抽象层的 `BaseLLMClient.chat_stream()` 调用大模型（具体后端由 `custom_llm_client/` 插件提供），`ParentAgentLoop` 实时解析 `StreamChunk` 中的文本增量与工具调用。
- **工具执行**：通过 `abstract/tools/registry.py` 按名分发；工具集加载检查在 `dispatch`/`async_dispatch` 中统一拦截未加载工具，`ToolExecutor` 在审批前做前置快速拒绝；只读 / 白名单工具直接执行，其余进入审批流程（`component/approval/`）。工具定义按会话已加载工具集动态生成（渐进式加载），首轮只加载 `core` 工具集，其他工具集通过 `LoadToolset` 按需加载。手动/脱手/YOLO 模式由 Application持有的 `ApprovalModeStore` 按主会话缓存，并将 `SessionApprovalModeState` BaseModel直接交给 easysave保存到 `approval_mode.es`；Gateway连接时读取恢复后的服务端权威值，前端不持久化该模式。
- **前端推送**：实时事件（流式文本、工具调用、工具结果、任务进度、子代理更新）通过 `FrontendSink` 经 WebSocket 推回前端。正典聊天历史不再在连接时整体回放：Gateway 先发送 typed `history_sync` 元数据，前端再通过 REST 取得全历史骨架与可见范围的历史内容页；`History` / `history.es` 仍保持整体存储。工具请求和匹配结果在前端以每个 `tool_call_id` 一张工具调用卡片显示，孤立结果保留降级行。聊天页会话视觉所需的 Agentspace 变化也通过同一会话 WebSocket的 typed `agentspace_event`推送，页面内事件总线扇出到三个视觉 hook；独立 Agentspace 编辑器仍使用 SSE。会话状态预检、History骨架和历史内容页具有15秒硬截止；超时显示持久通知，并在 WebSocket可用时以不进入 History 的脱敏 `client_diagnostic`记录 Gateway warning。

- 前端主聊天区使用全历史骨架 + 历史内容页：Gateway 进程内 `History` 仍是正典对象，连接与轮次结束仅通过 `history_sync` 宣告消息数，正文按 History 索引范围读取。前端以 Virtuoso 只挂载可视行；工具调用请求与匹配的工具结果按 `tool_call_id` 合并为同一工具调用卡片，实时 user/assistant/tool/system 行都通过明确的 `live_id → history_row_id` 关联提升到正典位置，只有完成交接的行才从实时尾部清理。
- 主聊天区被动追底由 `useChatScrollController` 统一协调：实时提交和列表总高度变化只提交可取消的单帧追底请求，执行时以 Virtuoso scroller 的物理底部为唯一锚点；最新流式消息超过视口时不定位到消息顶部。用户主动滚动、主动改变消息高度、小地图拖拽或会话状态离开 `following` 时取消待执行追底；`atBottomStateChange(false)` 不独立触发反馈循环。
- 流式结束时位于聊天视口内的普通长回复保留展开；后端在存入 History 后、对应 `history_sync` 前通过 `system.stream_meta` 发送 `stream_id`、History 索引和可选 `live_history_links`权威关联，前端在 skeleton 已包含目标行时先提升到正典位置，REST 内容页到达后覆盖临时内容并原子传递展开选择。缺失关联时保留实时行并记录诊断，不按正文或顺序猜测。
- 主聊天区 Minimap 使用逻辑 Minimap 映射，不测量离屏消息像素；本地性能遥测由用户在顶部栏命令菜单手动启用，默认关闭且不上传消息正文。

---

## 子代理与多代理系统

Evolve Agent 内置两套多代理运行时：

### 子代理模式（SubAgent）

- `subagent/orchestrator.py` 的 `SubAgentOrchestrator` 按父会话维护子代理上下文。
- 每个子代理是独立的 `SubAgentLoop`（继承 `BasePrivateChatAgentLoop`），拥有独立的 LLM 配置与历史。
- `subagent/profile.py::CharacterProfileResolver` 每次动态扫描 `ws:characters/roleplay/` 与 `ws:characters/task/`，从 `profile.md.meta` 的 `[llm_profile]` 解析当前 LLM Profile；角色名称跨类型全局唯一。
- `component/multiagenttools/` 提供动态发现、启动、对话、审批、停止和列表工具，不再提供显式注册工具。
- 子代理的工具可见性由 `availability` 位掩码控制：通常只能看到标记为 `SUBAGENT` 或 `EVERY` 的工具。
- 审批结果和子代理输出会周期性注入父 Agent 的消息循环。

详见 [subagent/DEV-README.md](origin_agent/subagent/DEV-README.md)。

### 临时Agent（TaskAgent）

- `RunTaskAgent` 只接收单个 prompt，并在调用发生时取得父主会话活动 LLM Profile的非持久化深快照；后续 Profile切换或编辑不影响已经启动的临时Agent。
- 临时Agent无系统提示词、无历史持久化，产生纯文本结果后立即终止；并发槽位已满时直接失败，不进入等待队列。
- 工具范围严格为“已加载工具集 ∩ `TASKAGENT` 可用范围 ∩ `safe` 危险等级”，定义生成和执行期均校验，因此不会进入审批流程。
- 初始工具集状态默认从 `core` 开始；符合相同权限交集的 `LoadToolset` 可以加载其他工具集，但加载本身不扩大授权范围。

### 多 Agent 协作模式（MultiAgent）

- 通过 `enter_multi_agent` 工具切换，不可逆。切换后所有用户消息由 `MultiAgentLoop` 处理。
- 所有参与 Agent 共享同一份对话历史，每条用户消息触发一轮并发响应。
- Agent 可在回复中通过 `response_characters` 指定下一轮的响应者，按轮次级联直到无人指定或达到最大深度。
- `MultiAgentWorker` 是单个 Agent 的一轮响应执行器，由 `MultiAgentLoop` 创建并聚合 token 统计。
- 多 Agent 模式下 multiagent 工具集被禁用。

### Colloquy（随意聊聊）

- 内置的固定闲聊会话（session ID `____buildin_colloquy__`，常量 `COLLOQUY_SESSION_ID`），启动时由 `main.py` 调用 `SessionManager.ensure_colloquy_session()` 确保存在，不出现在普通会话列表中且不可删除。
- 由 `entry/colloquy_loop.py::ColloquyLoop`（继承 `ParentAgentLoop`）处理，仅暴露白名单工具集（`COLLOQUY_TOOLSET_WHITELIST`，filesystem/core/shell/python 等，不含进化工具），超长历史按 `COLLOQUY_COMPRESS_RATIO` 滑动窗口压缩为摘要。

---

## 路径沙盒

所有文件操作必须使用逻辑路径前缀，禁止裸路径、`..` 遍历和绝对路径。

> 下表映射目录所涉 workspace 内部名为**默认配置名**，实际由 config.py 参数决定（`slow_agent_space_path`、`agentspace_path_name` 等）；`.fallback/` 为硬编码固定名。权威映射见 `system/sandbox.py::namespace_bases()`。

| 前缀 | 映射目录 | 模式 | 用途 |
|------|----------|------|------|
| `fork:` | `workspace/slow_agent_space/` | fast | 读写进化代码 |
| `ws:` | `workspace/agentspace/` | fast / fallback | 通用 I/O |
| `fix:` | `workspace/.fallback/` | fallback | 修复目标 |
| `skills:` | `skills/` | fast / fallback | 技能读写 |
| `third:` | `third/` | fast / fallback | 第三方子模块（只读） |
| `custom_hooks:` | `custom_hooks/` | fast / fallback | 自定义钩子（只读） |
| `custom_llm_client:` | `custom_llm_client/` | fast / fallback | 自定义 LLM 客户端（只读） |
| `custom_tools:` | `custom_tools/` | fast / fallback | 自定义工具（只读） |
| 用户定义的动态前缀 | 用户授权的规范化绝对目录 | fast | 全局共享；每项为工具层只读或读写 |

fast 模式的动态沙盒空间由 Application 持有的 Sandbox 单例统一管理，配置直接以
`DynamicSandboxSpaceData` 根对象保存到 `RuntimeContext.workspace/dynamic_sandbox_spaces.es`，
不属于 `ws:`、会话或 LLM Profile。目录可暂时不存在；不存在时配置保留但该空间
不可读写，目录恢复后自动恢复。所有 Agent 共享动态映射；只有普通模式和多Agent模式
主Agent可在加载 `sandbox` 工具集后，通过 critical 的 `AddSandboxSpace` /
`RemoveSandboxSpace` 修改。用户也可从所有会话的顶部栏命令菜单打开动态沙盒空间管理弹窗，
通过 REST 接口直接查询、创建、更新和删除配置；更新不通过删除后重新添加，空间名称不可修改。
随意聊聊会话只能使用已有空间，临时Agent无动态空间提示词。
动态只读权限与现有只读空间相同，仅约束标准 Sandbox 文件 API，并非 OS 级 ACL。

**没有 `self:` 命名空间** — agent 不能读取或修改自身运行时副本，进化完全通过 `fork:`/`fix:` 实现。

沙盒实现位于 `system/sandbox.py`（权限表 `_PERMISSIONS`，映射 `namespace_bases()`）。

---

## Agentspace 编辑器数据流

- 用户文件操作由前端 `agentspaceApi.ts` 调用 Gateway typed REST，再委托 `Application.agentspace_service`；Service 负责路径校验、按目录优先自然排序、内容 SHA-256 版本与原子写。
- 前端本地版本计算优先使用浏览器原生 Web Crypto；远程普通 HTTP 部署下 `crypto.subtle` 不可用时自动回退到纯 TypeScript SHA-256 实现（`utils/sha256.ts`），结果与服务端 Python `hashlib.sha256` 完全一致，不改变版本/冲突流程。
- 用户删除进入 `ws:.trash/` 的事务垃圾桶；Evolve Agent `Delete` 的永久删除与审批语义保持不变。
- 内置 Agent 文件工具在明确接触 `ws:` 路径时登记回复轮次文件锁，主Agent、参与Agent、子Agent与临时Agent在各自回复收尾后释放。
- `watchdog` 把外部变化送入事件总线。独立 Agentspace 编辑器通过 `GET /api/agentspace/events` SSE 接收缓存失效信号；聊天页会话视觉通过已有会话 WebSocket的 `agentspace_event`接收同源事件，避免每个视觉功能建立长连接。两者都通过 REST 重新取得权威快照；依赖不可用时界面显示同步降级。
- 编辑器保存携带预期版本；冲突返回 HTTP 409，前端保留本地草稿并显示 Monaco 差异比较，禁止静默覆盖。
- Monaco Editor 和 DiffEditor 的 Web Worker 由 `services/monacoEnvironment.ts` 集中配置，应用入口在 React 渲染前初始化；Worker 通过 Vite `?worker` 打包为同源构建资源，远程普通 HTTP 部署下从当前应用地址加载。

---

## 扩展点

系统提供多个热扩展点，无需修改核心源码：

- **自定义工具**：在 `custom_tools/` 目录下编写 `.py` 文件，使用 `registry.register()` 注册，启动时由 AST 扫描自动发现。
- **自定义 LLM 客户端**：在 `custom_llm_client/` 目录下编写 `.py` 文件，暴露 `create_llm_client(runtime_context, profile)` 工厂函数，返回 `BaseLLMClient` 子类实例。内置 `openai_client.py`、`anthropic_client.py`、`kscc_client.py` 和 `lmstudio_client.py`。
- **自定义钩子**：在 `custom_hooks/` 下实现 `hook_tag_name()` 与 `hook_message()`，返回的上下文块会追加到用户消息末尾。
- **本地模型**：在 `custom_models/` 下放置 `.gguf` 文件，可作为审批模型自动加载。
- **技能文件**：运行时 `skills/` 目录存放 `SKILL.md`，通过 `load_skill` / `list_skills` 工具加载。`pre-skills/` 提供参考模板。
- **插件**：`abstract/plugins/discover.py` 基于目录扫描插件，解析 `plugin.yaml`，启发式检测 provider 类型。
- **MCP**：`component/mcp_tools.py` 读取 `workspace/mcp_config.json`（默认），通过 `abstract/mcp/client.py` 连接并桥接工具；`abstract/mcp/schema.py` 在注册和 sampling 的 provider 边界规范化工具参数 schema。该层按 JSON Schema 结构位置处理嵌套内容，保护名为 `properties` 的业务参数，并将异常 `additionalProperties` 转为合法形式；它不改变实际 MCP `tools/call` 参数。
- **Agent 舞台层**：会话级背景渲染层，位于聊天区背景之上、聊天气泡之下。Agent 通过 `ws:sessions/<session_id>/stage/` 目录写入 `index.html` 及图集/动画资源，前端以透明 iframe 渲染，默认鼠标穿透。`Layout` 统一管理舞台层探测并订阅聊天 WebSocket扇出的 Agentspace事件，AgentStageLayer 只负责渲染；`stage/index.html` 是部署提交标记，资源应先写、入口最后写，只有入口文件的新内容版本经 1 秒安静窗口后重建 iframe。`resync` 和非入口资源变化不会重置正在运行的舞台。独立于会话网页 `site/`。系统提示词通过 `build_session_stage_block()` 注入。
- **会话网页**：独立于 Agent 舞台层的完整网页预览。Agent 通过 `ws:sessions/<session_id>/site/` 部署 `index.html` 及引用资源；前端探测入口文件并监听聊天 WebSocket中的该目录 Agentspace事件，部署完成后自动显示右侧会话网页入口，资源连续变化时等待 1 秒安静窗口后热刷新 iframe，入口文件或整个目录被删除/移走后自动隐藏入口。
- **会话聊天区自定义样式**：会话级聊天区 CSS 覆盖层。Agent 通过 `ws:sessions/<session_id>/chat-style/index.css` 写入 CSS，前端探测并经 PostCSS 作用域处理后注入 `<style>` 标签，仅作用于 `.chat-area` 聊天区。禁止 `@import`，允许 `@font-face`（`ChatStyle-` 前缀）和 `@keyframes`。CSS 缺失、超限（256 KiB）或作用域处理失败时恢复默认样式。用户可通过顶部栏命令菜单独立暂停 Agent 舞台层和聊天区自定义样式。系统提示词通过 `build_session_chat_style_block()` 注入。

---

## 基础设施与未拆分模块

- **会话视觉资源重定向**：`stage.meta`、`site.meta`、`chat-style.meta` 的 `[redirect]` 由 Gateway 服务端单层解析，稳定入口用 HTTP 307 指向有效逻辑目录；非法配置静默回退，前端 Hook 只消费最终 URL并自动刷新。
- **会话视觉资源状态**：会话 status REST 和 `session_meta_hook` 读取的非持久化 `visual_resources`，包含 stage/site/chat_style 的状态、源目录、有效目录、重定向标志和错误原因，不写入 History 或会话索引。

### system/

- `system/application.py`：`Application` 进程级唯一单例，持有所有子系统引用（`RuntimeContext`、`LLMProfileStore`、共享 Profile 锁、`SessionMetadataService`、`ApprovalModeStore`、`AgentspaceService`、`SessionVisualResourceService`、`SessionManager`、`ToolRegistry`、`ApprovalBackend`、`CronRouter`、`SubAgentOrchestrator` 等）。通过 `Application.current()` 访问，避免模块级全局变量。
- `component/approval/mode_store.py`：Application 持有的唯一会话级审批模式存储。按会话惰性读取 `approval_mode.es` 的 easysave `v1` key，并通过 `entity/typeref.py` 的 stable type token重建 `SessionApprovalModeState`；业务 `RLock`保护缓存事务，easysave负责路径锁、前置 `.bak`、同目录临时文件与原子替换。模式变更先更新内存再尽力保存，写入失败不回滚；损坏、缺 key或类型错误回退手动模式。新建及自动延续、单源分支、多父合并产生的主会话统一初始化为手动模式，归档保留，永久删除随会话目录清理。
- `system/agentspace/`：Agentspace 编辑器后端业务包。`AgentspaceService` 统一版本化 CRUD、用户垃圾桶、按 Agent 回复轮次持有的文件锁、文件变化 watcher、`AgentspaceEventHub`和用户变更摘要；Gateway 将同一事件总线适配为独立编辑器 SSE与聊天 WebSocket typed事件，内置工具通过该服务协作。
- `system/llm_profile_store.py`：进程内唯一的 LLM Profile 注册表。仅支持 `llm_profiles.es` 的 `v2` key，直接持有并保存 `LLMProfileData` 根对象；Profile 间多模态分工、审批 Profile和全局元数据 Profile均使用根列表中的实例引用，Gateway 通过单 Profile CRUD 修改。
- 前端模型配置抽屉通过“模型配置 / 全局配置引用”分页分别管理 Profile 定义和全局用途引用。模型定义按客户端、端点纵向分组，详情单项展开、先只读后编辑；切分页保留内存草稿，离开未保存配置时明确确认。会话待用 Profile 选择只在顶部栏修改，浏览器按会话独立保存名称；无本地覆盖时通过 `GET /api/sessions/{id}/llm-profile` 读取持久化指针及既有全局最近使用回退。选择本身不写服务端，发送到主会话或重新生成才提交；`resume` 保持后端当前配置。旧浏览器全局选择不猜测迁移到任何会话。
- `system/session_metadata.py`：Application 持有的唯一会话元数据服务。全局元数据 Profile优先；未配置时按目标会话持久化的活动 Profile回退。统一生成标题、标签和摘要，并为分支、合并与自动旋转提供摘要保障。明确配置不可用时不静默回退。
- `system/context.py`：`RuntimeContext`，贯穿整个应用的生命周期上下文。
- `system/sandbox.py`：路径沙盒、固定命名空间解析，以及 fast 模式全局动态沙盒空间的严格加载、原子持久化、增删改、目录可用性和权限管理；文本 `Read` 按 UTF-8、系统编码和 Windows 常见编码自动探测，文本内容按原样返回，分页只按 LF 定位原文行片段，保留 CRLF、孤立 CR 与末尾换行；编辑和 LSP 使用的 `limit=0` 路径返回完整解码原文。`write()` / `append()` 禁用平台换行转换，按传入文本原样写入 UTF-8，避免 Windows 上 `PatchEdit` 写回时给已有 CRLF 增加一个 CR；`PatchEdit` 按原文匹配与替换，已有异常换行不自动修复。动态配置位于 workspace 根且由 Application 的唯一 Sandbox 实例持有。用户管理弹窗通过 Gateway REST 复用该单例。
- `system/file_metadata.py`：Read 的元数据文件纯文本解析器，`parse_meta_content(content)` 按独立的 `[key]` 行解析一层字符串字典，保留值的原始空白和换行；非法/重复键及前导非空文字抛带行号的 `MetaFormatError`。`component/tools/filesystem.py` 负责通过 Sandbox 读取目标完整名称追加 `.meta` 的同级文件，目录也使用同级 `目录名.meta`；命名空间根目录不附带，显式 `.meta` 不继续嵌套。成功时结果附加 `meta` 字典，缺失省略，元数据访问/解析失败附加错误字符串而保留原结果。会话视觉源目录的 `redirect` 由 `system/session_visual_resources.py` 单层消费，Read 只在 `meta.redirect` 中报告错误，不跟随目标。目录列表隐藏 `.meta` 文件（后缀不区分大小写，保留同后缀目录），其他文件工具与前端文件树不变。元数据完整读取不受正文分页影响，ws: 元数据文件沿用回复轮次文件接触登记；当前不自动维护文件。
- `system/session_store.py`：单个会话的文件读写（`history.es`、`summary.txt`、`token_usage.json`、`tool_resources.json` 等）；活动 LLM Profile 仅以 `{"profile_name": ...}` 名称指针保存。旧版 `messages.jsonl` 已由 `scripts/migrate_v0_to_v1.py` 迁移到会话 v1 格式。`history.es` 通过 easysave 的安全写入事务保存：同目录临时文件、刷新/同步、原子替换和前置备份；残留 `.bak` 会阻断后续保存并要求人工处理，读取侧不自动恢复损坏文件。
- `system/prompt.py` / `system/templates.py`：System Prompt 组装与模板渲染。
- `system/convert.py`：类型转换工具（`as_enum()`、`as_bool()`）。
- `system/error_utils.py`：异常降级与日志辅助，用于可恢复副作用失败时记录日志但不中断主流程。
- `system/pathutils.py` / `system/atomic_io.py`：路径与原子 IO 工具。
- `system/subprocess_utils.py`：内部子进程同步/异步执行、活动进程登记与中断终止；代码验证、搜索、LSP 等基础设施继续复用。
- `StartShell` 在 Windows 上启动 powershell/pwsh 时使用 `-NoProfile`，并通过启动阶段内部 `-Command` 优先尝试移除 PSReadLine，失败时回退为关闭预测；第一阶段不提供历史、预测和方向键等行编辑能力。Agent 依赖显式的 `EVOLVE_PYTHON` 与 namespace 环境变量。
- Shell 单行输入通过 ConPTY 发送单独的 CR（`\r`）作为 Enter，不发送 CRLF；未换行提示符作为待提交逻辑行，在最后原始输出静默 0.4 秒后提交并立即返回，因此 InterruptShell 和 ReadShell 不必等待 30 秒硬截止。
- `system/search_engine.py`：`SearchFiles` / `Grep` 的搜索引擎封装。Windows x64 优先使用随 Agent 分发的固定版本 `ripgrep`（`origin_agent/vendor/ripgrep/win32-x64/rg.exe`），不可用、校验失败或单次兼容错误时回退 Python；ripgrep 匹配、Python 回退和上下文读取均按 LF 计行，孤立 CR 不会错位；统一处理 ignore/hidden 过滤、`limit` 截断、`full_scan`、`exhaustive`、`engine` 与 `warning` 返回字段。
- 主会话强制中断：`IMainSessionLoop` 只登记已经取得处理锁的单次回复 task；长期 `SessionMessageQueue` consumer 不属于中断目标。`request_interrupt()` 先设置轮次取消事件并等待协作式收尾，超时后只强制取消该轮 task；轮次 finally 在下一条消息开始前清除取消状态。`StreamConsumer` 自行竞速取消信号与流读取，并作为异步迭代器的唯一关闭者。前端以 `history_sync.processing` 的 true/false 为主会话处理状态权威。
- `system/lsp.py`：LSP 服务器进程管理与诊断（`component/tools/lsp.py` 工具调用；App 关闭时清理 LSP 进程）。
- `system/modality_capability.py`：多模态能力探测与缓存（探针已内化为系统自动行为：伪装 Read 工具调用，按 模态 × 消息路径六路并发探测 tool/user 消息的图片/音频/视频支持；easysave 缓存按 model+base_url 联合索引；`build_modality_prompt_block()` 每轮生成 system prompt 注入块；`forward_modality_to_ref_profile()` 把活跃模型不支持的模态转发到 profile 引用的其他模型）。`build_media_content_block()` 提供不附加 prompt 的共享单媒体块构造入口。自定义工具 `ReadForward` 使用该入口按 `paths` 顺序构造“文件标签 + 媒体块”，末尾只附加一次 prompt，并通过单条 user 消息和一次 LLM 调用转发混合模态；工具生成的紧凑 JSON 内容块载荷上限为 45 MiB，任意文件无效时整体失败。

### `evolve/`

- `evolve/code.py`：进化编排，提供 `finalize_evolution()` 触发退出码 `-1`。
- `evolve/validator.py`：Python 语法与 `py_compile` 目录级检查。

### `entity/`

- `entity/messages.py`：`BaseMessage` 消息体系，包括 `BaseMessage`、`CharacterConversationMessage`、`CharacterSystemMessage`、`ToolResultMessage`、`History` 等。所有 LLM 调用统一使用 `list[BaseMessage]` 而非 `list[dict]`。
- `entity/puretype/`：纯数据类型包，按职责拆分为 `_base`、`approval`、`llm`、`skills`、`session`、`agent`、`ws`、`lsp`、`runtime`、`extools` 子模块。包括 `LLMResponse`、`StreamChunk`、`Role`、`ToolAvailability`、`ToolDangerLevel` 等。
- `entity/gentype.py`：泛型工具类型（`RefWrapper[T]` 可变引用容器，供 loop 与 `ToolExecutor` 等组件共享可变值，如工具循环计数器）。
- `entity/constant/`：按职责拆分的全局常量包。`constant/__init__.py` 显式重新导出历史公共名称，保持 `from entity.constant import ...` 兼容；`sandbox.py` 保留 `Namespace` 与 `is_namespaced_path()`，其余常量按基础、限制、超时、协议、Shell、文件系统、搜索、Agentspace、上传、聊天样式、HTTP、LLM、Agent、子Agent、多Agent、Cron、会话搜索、Watching、Skill、随意聊聊和 easysave 版本职责分模块维护。

---

## 开发者阅读顺序建议

1. 先通读本文件，建立整体架构认知。
2. 根据你关心的领域阅读对应子模块 DEV-README：
   - 改主循环、消息处理 -> `entry/DEV-README.md`
   - 改网关、会话、前端协议 -> `gateway/DEV-README.md`
   - 改工具、审批、MCP -> `component/DEV-README.md`
   - 改抽象层、注册表、LLM 客户端 -> `abstract/DEV-README.md`
   - 改前端 UI -> `frontend/DEV-README.md`
   - 改子代理 -> `subagent/DEV-README.md`
3. 深入具体源码时，从 `__main__.py` -> `main.py` -> `system/application.py` -> `gateway/server.py` -> `entry/parent_agent_loop.py` 这条主线开始追踪。