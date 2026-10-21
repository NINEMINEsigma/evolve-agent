# abstract/ — 抽象层

`abstract/` 是 Evolve Agent 的抽象层，定义 LLM 客户端、工具注册表、AST 发现、技能、插件、MCP 客户端等核心抽象。这些模块不依赖具体实现，可被 `component/`、`custom_tools/`、`custom_llm_client/` 等复用。

---

## 文件结构

```
abstract/
├── llm/                        ← LLM 客户端抽象层
│   ├── client.py               ← BaseLLMClient 抽象基类
│   ├── retry.py                ← 空响应有界重试装饰器
│   ├── loader.py               ← 动态加载器（create_llm_client 工厂）
│   └── formats.py              ← wire format 转换器（OpenAI / Anthropic）
├── tools/
│   ├── tool.py                 ← BaseTool / BaseToolSet / ToolExecution 运行时契约
│   ├── registry.py             ← 对象工具注册表
│   ├── discover.py             ← AST 自动发现（顶层 TOOLSET）
│   └── toolsets_meta.py        ← 内置工具集元数据对象
├── skills/
│   ├── frontmatter.py          ← frontmatter 解析
│   ├── loader.py               ← 技能加载
│   └── manager.py              ← 技能生命周期管理
├── plugins/
│   └── discover.py             ← 插件发现
└── mcp/
    ├── client.py               ← MCP 客户端
    ├── schema.py               ← MCP 输入 schema 结构位置规范化
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
- 多模态内容块必须忠实转换并发送；客户端或 wire format 无法表达某种模态时应抛出 `UnsupportedModalityError`（第三方实现也可抛出自身明确异常），禁止静默删除、替换为普通文本或伪造成功。
- 客户端把各自 SDK 的 API 状态错误归一化为 `LLMAPIStatusError`（携带 `status_code`，继承 `RuntimeError` 保证既有 `except RuntimeError` 捕获点行为不变）：非流式路径直接转换抛出（`raise ... from` 保留异常链）；流式路径经 `StreamChunk.error` + `StreamChunk.error_code` 传递，`chat()` 的流式回退收集路径据此重建同一类型。上层（探针/转发）只识别 abstract 异常，不依赖具体 SDK 异常族。
- 多模态转发的目标解析由上层传入活动 Profile 与对应全局回退 Profile；活动引用优先、全局引用只补足空引用。明确的 Provider 模态请求失败可转换为转发错误，其他异常必须继续向上抛出。
- 子类必须实现 `_convert_messages()` 将 `list[BaseMessage]` 转换为对应 LLM 后端的 wire format。

#### `abstract/llm/loader.py` — `create_llm_client()`

动态加载器，按名称从 `custom_llm_client/<name>.py` 加载实现模块：

```
create_llm_client(name, runtime_context, profile) -> BaseLLMClient
```

- 通过 `_ensure_namespace_package()` 将 `custom_llm_client/` 注册为命名空间包（无需 `__init__.py`）。
- 调用模块暴露的 `create_llm_client(runtime_context, profile)` 工厂函数构造客户端实例。
- 校验返回值是否为 `BaseLLMClient` 子类，随后统一包装为 `EmptyResponseRetryClient`，公开签名保持不变。插件工厂仍只构造Provider客户端，正式加载器只装饰一次；直接调用插件工厂不具备这层统一保证。
- `list_llm_clients()` 返回目录下所有可选客户端模块名。

#### `abstract/llm/retry.py` — `EmptyResponseRetryClient`

该装饰器在正式加载入口统一覆盖普通模式、多Agent模式、随意聊聊、子Agent、临时Agent，以及元数据、审批与多模态调用。`LLM_EMPTY_RESPONSE_MAX_ATTEMPTS=3` 表示初次请求加最多两次重试，复用 `BACKOFF_BASE` 等待1秒、2秒；每次仍向同一底层客户端传递原请求参数，不追加空assistant/续传提示，不执行或重放工具，不额外消耗工具循环轮数。`chat()` 仅在 `content` 长度为零且 `tool_calls` 为空时重试，思考内容不能代替有效完成；纯工具调用合法，非零长度空白正文保持原语义。耗尽抛出 `client.py::LLMEmptyResponseError(RuntimeError)`，由现有调用错误出口处理。

流式事件语义在本装饰层确定，`StreamConsumer` 继续负责聚合、计时、取消及前端发送：

- 正文、思考、工具调用和工具参数增量实时透传，使用上层原有流标识。各空尝试的思考在同一逻辑流中连续展示并聚合，接受这一展示权衡，但不把它们加入重试输入或单独写成assistant消息。
- 每次尝试的 `finish_reason` 暂存至底层自然结束且关闭成功后才交付。尚无正文或完整工具调用时按原序暂存 `usage`，首次有效输出时释放；失败空尝试的用量与结束原因丢弃。成功用量沿既有统计口径，不代表所有尝试的供应商账单用量。
- 原chunk暂存usage/finish后即使全空仍透传一次，保留真实数据到达进展，使现有空闲超时照常重置；不伪造usage或完成事件。只有工具参数片段却无完整调用且正文为空时明确抛错、不重试，避免重复可见工具卡片。
- `StreamChunk.error` 原样透传并结束；直接异常、解析错误、取消与关闭失败均传播，不纳入空响应重试。返回的Provider迭代器必须支持 `aclose()`，装饰器以 `aclosing` 负责内层流，消费侧仍唯一负责外层流；内层关闭成功后才可重试，不创建后台清理任务。

本层不替代或扩大 Provider 的网络错误重试。单次逻辑调用本层最多3次底层调用、3秒自身退避；底层客户端和 SDK 若另有重试或调用回退，其请求次数、等待与网络耗时会叠加，不能由本层预算推导固定 HTTP 次数或总耗时。本层没有新增硬总截止。六路模态探测分别拥有预算，单调用上界不是整次探测上界。

能力探针以前把无异常的空结果也视为支持；现在持续空时重试耗尽、六路TaskGroup收尾失败且不写支持/不支持缓存，不修改既有异常组传播政策，因此首次媒体请求可能失败。缓存命中仍不请求模型。审批持续空沿既有失败路径拒绝，不默许工具；元数据/转发维持各自原失败出口。仅完成源码与只读审阅，尚未运行校验或应用，场景验收由用户完成。

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
  - 图片忠实转换为 Anthropic image block；音频和视频无法表达时抛出 `UnsupportedModalityError`，不再替换为文本占位符。

---

### 主会话媒体输入的上层边界

主会话每请求由 `entry.agent_support.multimodal.prepare_main_multimodal_request`固定独立媒体实例开关，发送原块、已验证描述或明确未提供内容的TextBlock；原History媒体始终保留。客户端收到的MediaBlock.as_object仍为原图片/音频/视频wire结构，不携带media_id、开关或内部来源字段，不在格式转换器静默删媒体。

关闭时的描述经ModalityCapabilitySystem.describe_media_block单跳取得，成功与明确不可用分开；网络/认证/超时/未知400/空描述继续失败。活动Profile的对应引用优先，全局仅补空引用；明确活动引用不可用不改全局目标。URL直接由目标客户端协议处理，服务器不额外抓取。

普通主会话准备副本后将last_user_message精确重连，保持当前后缀；多Agent继续None，不附带改变后缀注入。子Agent/临时Agent独立调用未接入主会话控制。以上为源码实施约定，未运行验证。

---

## 工具对象与四阶段执行（2026-10-15）

源码按任务文件 v8 实施对象工具契约：`BaseTool`、`BaseToolSet`、`ToolExecution`、`ToolHandlerResult` 和 `ToolPostprocessEffect` 位于 `tools/tool.py`，为带方法或显式构造的运行时类，不进入 easysave；`ToolBatchDecision` 是消息前纯类型，位于 `entity/puretype/tool.py`。完整任务复核与用户验收仍待完成，不得据此宣称已通过运行验证。

ToolRegistry 的 `_tools` 直接保存 `BaseTool` 对象，工具集元数据直接使用 `BaseToolSet`，运行期成员唯一索引为 `_tool_names_by_toolset`（不从声明 `tuple` 猜测 MCP 当前成员）；`ToolEntry`/`ToolsetEntry` 元数据镜像、函数式 `register`、`get_entry`/`get_toolset_entry` 查询均已删除。`plan_tool_batch()` 在执行和审批前按 `accepts_following_calls` 取接受前缀。`async_dispatch(execution)` 只执行工具调用前的 `before_handle` 与工具主体 `handle`，写回 `body_executed`、`body_completed_normally`、`result` 和 `state`。`async_postprocess(execution)` 托管结果提交后的 `after_handle`；两者复用唯一 TaskOwner、ThreadPoolExecutor 和原生 Future 记录，取消包装等待不代表工作已经退出。

模块级 `TOOLSET` 注册时对每个声明对象执行一次 `preheat()`，异常直接传播；预热不启动浏览器/语言服务器，也不替代运行期 `check_fn`。全部工具来源（核心、扩展、多Agent、浏览器、自动化、自定义工具与 MCP）均已改为 `BaseTool` 子类与顶层 `TOOLSET` 声明，不再有 `HandlerToolAdapter`、`register_tools` 发现分支或 `UIEventRouter`；各来源由并行流程迁移，逐文件最终对照仍在收尾。两种压缩工具、身份刷新、代码验证/进化等专属后处理统一在 `after_handle` 中完成；EvolveCode 在 after 中唯一消费进化标记并请求关闭，通用 History 提交不再包含进化特判。

## 历史更新的调用级材料（2026-10-15）

`ToolExecution.history_updated` 默认为false，`mark_history_updated()`只在结构修改的必要保存成功后调用，材料仍属于单次调用而非共享工具实例。它与after返回效果分离，避免保存成功后的取消丢掉通知事实；`ToolPostprocessEffect.system_message`承载后处理完成的系统通知，原`completion_message`仍只用于进化等assistant收尾。`ToolPostprocessor`唯一消费标记并经Sink发送独立`history_updated`，普通结果追加与批次声明不改变。该标记/系统通知不持久化，错误与取消继续传播，网络送达仍不承诺可靠确认。

## 工具注册表

### `abstract/tools/registry.py`

`ToolRegistry` 已迁移为依赖 `RuntimeSystem` 的 framework `AsyncSystem`，通过 `app.get_system(IToolRegistry)` 取得唯一实例。工具表、工具集元数据、检查缓存及锁均由该实例持有，不再提供模块级 `registry` 单例或兼容代理。

工具模块通过顶层固定名称 `TOOLSET = BaseToolSet(...)` 显式声明；导入模块不取得 Application、不修改注册表。ToolDiscoverySystem 持有本次已注册模块集合并交给唯一 `ToolRegistry`。下文 `registry` 表示运行期经 `app.get_system(IToolRegistry)` 取得的实例，而非可导入的全局对象。

提供：

- `registry.register_tool(tool: BaseTool, *, replace=False)`：按名注册 `BaseTool` 对象，声明 schema、危险等级、`availability` 位掩码等；MCP 动态刷新用 `replace=True` 原子替换同名工具。
- `registry.register_toolset(toolset: BaseToolSet, *, merge=False)`：注册 `BaseToolSet` 对象（名称、描述、usage_guide、是否默认加载）；分布式声明用 `merge=True` 合并元数据，每个声明对象只预热一次。
- `registry.dispatch(execution)` / `registry.async_dispatch(execution)`：接收已创建的 `ToolExecution`，按 `tool.is_async` 执行工具调用前 `before_handle` 与工具主体 `handle` 并写回 `body_executed`/`body_completed_normally`/`result`/`state`；同步入口仅允许在非事件循环线程调用，两者在分发前统一拦截未加载工具（`is_toolset_loaded`）。`registry.async_postprocess(execution)` 在结果提交 History 后托管 `after_handle`，与 dispatch 复用同一 TaskOwner 与真实同步 Future。
- `registry.get_definitions_for_loaded_toolsets(scope, loaded_toolsets)`：按已加载工具集和 scope 返回工具 schema（渐进式加载核心方法）。
- `registry.get_toolset_catalog(scope, loaded_toolsets)`：返回按当前 Loop 过滤后的工具集目录（用于系统提示词）。
- toolset 别名、schema 覆盖、动态 schema（`check_fn` + 30s TTL 缓存）。
- 按 `availability` 位掩码过滤：`MAIN`（普通模式主Agent）、`SUBAGENT`（子Agent）、`MULTI_AGENT`（多Agent模式）、`TASKAGENT`（临时Agent）、`EVERY`（全部范围）。
- 已加载工具集与 `availability` 是注册表的通用过滤层；具体 Loop可在其上继续施加危险等级等策略。临时Agent的额外策略为 `TASKAGENT ∩ safe`，定义生成与执行期均校验。

注册表按名保存 `BaseTool` 对象，公开字段包含：

- `name`, `toolset`, `schema`
- `before_handle` / `handle` / `after_handle`（同步或异步）
- `is_async`, `danger_level`, `no_timeout`, `accepts_following_calls`
- `availability`：位掩码
- `check_fn` / `requires_env`：运行期可用性与环境检查

工具集元数据由 `BaseToolSet` 对象承载，通过 `register_toolset(toolset, merge=True)` 装载或合并，可用时经 `get_toolset(name)` 查询。`abstract/tools/toolsets_meta.py` 在启动时为所有内置工具集注册简短描述及加载后的使用说明；其中 shell 工具集说明要求跨命令和回复轮次复用 Shell会话，不因单次命令或回复完成而例行调用 `StopShell`。`skills` 工具集已并入 `core`。

### 工具执行与关闭所有权

`virtual_awake` 创建唯一 ThreadPoolExecutor。同步入口仅允许在非事件循环线程调用，同步与异步分发中的同步 handler 均经该执行器运行；`contextvars.copy_context()` 保留调用上下文。原生 Future 在 handler 开始前完成登记，取消异步等待只解除请求等待责任，不删除尚未完成的线程记录；真实完成与结果交接均发生后才回收。取消后迟到的执行失败与明确生命周期失败报告 Runtime，普通请求错误仍交回调用方。

异步分发以 `TaskOwner.run_request` 托管完整 handler 操作，使用 Runtime 的同步接收边界及开始前复查。`close_dispatch` 在 STOPPING 期间仍可调用；`cancel_pending_calls` 取消并等待请求任务与结果交接；`wait_idle` 还等待真实同步工作，不用清表表示结束。超时保留资源并抛出生命周期失败。最终关闭仅在没有活工作时通过独立、受持有的异步任务在线程中执行 `executor.shutdown(wait=True)`；主事件循环不阻塞 join，关闭失败继续传播。

### 会话变量只读注册

`component/tools/session_variables.py` 以顶层 `TOOLSET` 声明在 filesystem 工具集注册 safe/EVERY 的同步 `ReadSessionVariables`，不新增工具集、UI 事件或模块实例。其原生工作由 ToolRegistry 既有执行器持有，执行结果由服务主动检查 UTF-8 响应预算，不能把未使用的 get_max_result_size 查询当截断保障。filesystem 仍非默认加载；主/参与/普通子/临时Agent均先通过已有 LoadToolset 加载，临时Agent不获得写权限。usage_guide 说明完整读取、原值/meta/问题结构和主Agent单写者约定。

### `abstract/tools/discover.py`

`discover_builtin_tools(tools_dir, package_prefix, *, registry)` 严格读取并解析候选 `.py`，只识别顶层固定名称 `TOOLSET` 声明，按路径顺序导入后以 `registry.register_toolset(toolset, merge=True)` 注册。辅助模块正常跳过；退役的 `register_tools` 函数、旧全局注册表导入、`abstract.tools.ui_event_router` 导入、导入期注册以及语法/读取/导入/注册错误直接失败。命名冲突未授权覆盖时 ToolRegistry 抛错，不把拒绝注册计为成功。

`ToolDiscoverySystem` 是 framework AsyncSystem，依赖已就绪的工具所需业务系统（包括 MCPSystem），构造不发现工具。`virtual_awake` 扫描原五个 component 子目录与可选 custom_tools，显式注册 MCPRefresh，最后登记工具集元数据；缺失内置目录失败，只有不存在的 custom_tools 可跳过。实例保存唯一已注册模块名集合，同一次装配重复注册直接失败。Python 模块缓存照常保留，每次显式调用入口，不重载或修改 sys.modules；宿主根导入路径沿原启动方式加入，只有本次添加的路径才在失败/注销时释放。

发现失败终止启动，不提供半套工具继续服务、不重试注册或创建第二个注册表；已提交条目仍由原 ToolRegistry 持有。最终注销只清除本次发现记录和导入路径，不卸载模块，不重连 MCP。

### UI 事件路由

`abstract/tools/ui_event_router.py` 与 `UIEventRouter` 已删除。工具的后处理不再经独立事件路由，而是在结果提交 History 后通过工具实例的 `after_handle(execution)` 直接向前端 Sink 发送事件（如任务进度、剪贴板展示），发送任务与取消清理责任仍由所属 Loop 与 FrontendSink 承担。

---

## 调用级取消事实与文件目标统计

`ToolExecution`新增私有`threading.Event`取消事实，通过`mark_cancelled()`和只读`cancel_requested`公开。状态只属于单次非持久化调用，不写入共享工具、Application、History或统计根。ToolRegistry在原生同步等待的CancelledError出口、及async_dispatch包装出口幂等登记，再沿原流程传播取消并交接请求；不清除仍运行的真实Future，不更改既有Owner清理截止。

文件工具的记录器结合该事实与`ToolContext.is_interrupted`，在必要统计保存前采样；已经成功保存的目标保留，取消登记后迟到的目标不再提交。该事实不表示原生线程已经结束，也不把统计转移到History提交后的after_handle：文件操作可以早于History落盘，统计独立保留实际成功目标。

统计保存的`SessionFileChangesPersistenceFailure`继承LifecycleFailure，按既有注册表/Runtime路径使应用失败关闭；一般GET读取失败仍由FastAPI请求边界处理。四阶段执行顺序、工具发现、审批和权限均不变。本次未运行校验或应用。

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
- **内部键剥离**：`_make_tool_handler` 下发 `tools/call` 前剥离 `entity/constant/tools.py::TOOL_INTERNAL_ARG_KEYS`（`_session_id` / `_pre_approved` / `_approval_action`）——这些键由分发层与审批执行器注入 args，严格 schema（`additionalProperties: false`）的外部服务端会拒收；内置工具 handler 依赖主动读取这些键，剥离只发生在 MCP 分发边界，不经公共分发层。

配置入口已迁入 `MCPSystem.virtual_awake()`，`component/mcp_tools.py` 以 `MCPRefreshTool` 与顶层 `TOOLSET` 声明 `MCPRefresh`，不在导入期安装回调或创建连接。远端工具与资源/提示词辅助操作由 `MCPTool`/`MCPToolSet` 接入统一四阶段：`MCPToolSet` 只声明 `mcp-{server}` 元数据、不持有连接，`MCPTool.handle()` 调用无状态 `_make_tool_handler()` factory；刷新经 `registry.register_tool(MCPTool(...), replace=True)` 在锁内原子替换同名工具，只注销新集合已消失的名称（含辅助工具）。`MCPCore` 完整持有服务器表、专用 loop/thread、stdio 进程、stderr 句柄、断路器状态及 OAuth Manager；OAuth 认证任务、回调 HTTP 线程、401 dedup 和 stdio 进程生命周期均经独立静态复核确认闭合。初始并发连接失败清理所有部分成功连接后传播，运行期刷新保留新增/移除结果；`close_admission` 拒绝新工作，`stop_calls` 确认真实任务退出，`shutdown` 等待全部资源（OAuth、stdio、cleanup、loop thread）实际完成后才释放。


`normalize_mcp_input_schema(schema, diagnostic=None)` 是 MCP 工具输入 schema 的 provider 兼容层。它不依赖 MCP SDK、ToolRegistry 或 LLM 客户端，使用深拷贝按 JSON Schema 的结构位置递归处理：`properties`/`patternProperties`/`$defs`/`definitions` 是映射边界，`items`、组合关键字和 `additionalProperties` 才进入子 schema。这样业务参数名为 `properties`、`type` 或 `required` 时不会被误认为结构关键字。

该模块保留本地定义引用重写、nullable union 折叠和 `required` 清理；对 `additionalProperties` 保留布尔值和 schema 对象，标准类型字符串转换为 schema，未知字符串或无效值降级为 `true` 并通过仅含路径与类别的诊断回调记录。`null` 裸字符串不直接生成 `type: "null"`。规范化只改变发送给 LLM 的 schema，不改变随后传给 MCP `tools/call` 的参数字典。

`abstract/mcp/client.py` 的 `_normalize_mcp_input_schema()` 仍是兼容包装入口，MCP 工具发现和 server-initiated sampling 均通过同一实现，避免不同路径产生不一致的 schema。

---

## 与其他模块的关系

`abstract/` 定义接口与通用逻辑，`component/` 和 `custom_*/` 提供具体实现：

| abstract | 具体实现 |
|---|---|
| `BaseLLMClient` | `custom_llm_client/<name>.py` 暴露的工厂返回符合公共接口的客户端实例 |
| `to_openai_message()` / `messages_to_anthropic_list()` | 被 `custom_llm_client/` 中的客户端调用 |
| `ToolRegistry` | `component/extools/`、`component/multiagenttools/`、`custom_tools/` |
| `SkillManager` | `component/extools/` 中的 `load_skill` / `list_skills` 工具 |
| `MCPClient` | `component/mcp_tools.py` |
| `PluginDiscover` | 启动时扫描 `plugins/` 目录 |

### 扩展点

- **自定义 LLM 客户端**：在 `custom_llm_client/` 下编写 `.py` 文件，暴露 `create_llm_client(runtime_context, profile)` 工厂函数，返回 `BaseLLMClient` 子类实例。
- **自定义工具**：在 `custom_tools/` 下编写 `.py` 文件，声明顶层固定名称 `TOOLSET = BaseToolSet(...)` 并在其中持有 `BaseTool` 子类实例；ToolDiscoverySystem 按 AST 发现后交给唯一 ToolRegistry 注册并预热，导入模块只创建无连接工具对象、不注册也不取得运行时服务。
- **自定义钩子**：在 `custom_hooks/` 下实现 `hook_tag_name()` 与 `hook_message()`，返回的上下文块会追加到用户消息末尾。

## System 接口槽位约定（2026-10-20）

`ToolRegistry`、`ToolDiscoverySystem` 和 `MCPSystem` 分别继承 `IToolRegistry`、`IToolDiscoverySystem` 和 `IMCPSystem`。工具发现使用 `IToolRegistry` 查询注册表，MCP 使用 `IMCPSystem` 作为运行期槽位；具体实现仍负责对象工具注册、发现记录和原生资源清理。抽象层不得通过具体 System 类型查询 Application。
