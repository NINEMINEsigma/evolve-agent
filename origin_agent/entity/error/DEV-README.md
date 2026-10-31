# entity/error/ — 异常定义包

本包是 origin仓库所有自定义异常的唯一定义位置，包括业务拒绝、生命周期失败、资源清理状态和内部控制信号。规范术语见根目录 `DEV-glossary.md`。本包集中定义类型，不集中执行错误处理，不引入统一捕获器、运行时服务或新的失败策略。

## 定义与导入约定

- 自定义异常只在本包按职责定义。业务模块负责抛出、捕获、转换和错误分类辅助函数，不重新定义同名异常，不通过旧业务路径转发或建立兼容别名。
- 公共异常在 `__init__.py` 中显式导入，并登记于 `__all__`；所有调用方统一使用 `from entity.error import X`，不依赖业务模块顺带导出的名字。
- 私有 `_SourceUnavailable` 是唯一私有导入例外：使用方从 `entity.error.session_export` 显式导入；它不进入包入口或 `__all__`，不作为公共扩展接口。
- 标准库和第三方异常仍从各自原来源导入，例如 `ValueError`、`TimeoutError`、`asyncio.CancelledError` 和框架/SDK 异常；集中约定仅覆盖 origin仓库自定义异常。
- 按职责划分子模块，而非建立一个统一业务基类。异常继续继承原有 `Exception` 家族，包括 `RuntimeError`、`ValueError`、`LookupError`、`KeyError`、`PermissionError`、`TimeoutError` 等；不强行改为 `BaseModel`，不移入消息前/消息后纯类型包。
- 保留构造签名、字段、错误文本、异常链和继承关系。迁移不改变抛出位置、捕获范围、HTTP 映射、工具错误转换、取消/停止、重试或快速失败与只崩溃软件语义；逻辑之外的错误仍交由原边界传播。

## 模块地图

| 模块 | 职责与类型 |
|---|---|
| `abstract.py` | LLM 与 MCP：`UnsupportedModalityError`、`LLMEmptyResponseError`、`LLMAPIStatusError`、`InvalidMcpUrlError`、`OAuthNonInteractiveError` |
| `entry.py` | History兼容、工具中断及主会话媒体：`IncompatibleHistoryError`、`ToolInterrupted`、`HistoryMediaNotFoundError`、`HistoryMediaConflictError`、`HistoryMediaPreviewError`、`ModalityForwardUnavailableError` |
| `gateway.py` | 端口占用与连接级控制信号：`GatewayPortBusyError`、`AgentspaceSendTimeout`、`AgentspaceConnectionClosed` |
| `session_export.py` | 唯一 `SessionExportError` 及全部公共导出子类；另含私有 `_SourceUnavailable` |
| `subagent.py` | 角色档案拒绝：`CharacterProfileError` |
| `system.py` | Shell、Sandbox、Profile、元数据、生命周期、清理、搜索、会话变量/视觉/文件统计及 Agentspace 异常族 |
| `util.py` | 元数据解析与字体读取：`MetaFormatError`、`LocalFontAccessError` |
| `__init__.py` | 公共异常的显式导出入口，不导出私有信号 |

模块名表示职责，不表示重新依赖对应业务包。本包不导入 `Application`、具体 System、Agent Loop、Gateway 实现或前置辅助模块，不在导入时启动服务、连接或后台任务。本包在运行时仅依赖标准库；`system.py` 仅在 `TYPE_CHECKING` 下从 `entity.puretype.resource_cleanup` 导入 `CleanupWarning` 供类型检查，不构成运行时依赖。新增依赖前须确认不会反向引入业务实现或形成循环。

## 关键类型一致性

### 会话离线导出

`SessionExportError(ValueError)` 只定义一次，`SessionExportInputError`、`SessionExportNotFoundError`、`SessionExportNotReadyError`、`SessionExportCapacityError`、`SessionExportMetricsError`、`SessionExportLimitError`、`SessionExportChangedError`、`SessionExportTimeoutError`、`SessionExportBusyError` 全部直接继承同一个基类。entry 的 History 捕获、system 的导出服务和 Gateway HTTP 映射统一引用这一族，不能在各层建立同名类型或不同基类，避免捕获类型不一致。

`_SourceUnavailable(Exception)` 保持独立的线程侧内部信号，用 `status` 与 `code` 表达明确资源不可用；它不属于公共 `SessionExportError` 子类，不因集中定义而扩大为一般错误降级入口。

### 生命周期与内部控制信号

`HistoryPersistenceError`、`SessionFileChangesPersistenceFailure`、`SessionVariableCleanupFailure` 仍继承 `LifecycleFailure`，原异常组识别与必要失败传播保持。`ResourceCleanupTimeout` 保留 `warning` 与原观察超时语义，不能据目录迁移推断所有清理错误都可降级。

`ToolInterrupted`、`AgentspaceSendTimeout`、`AgentspaceConnectionClosed` 等内部控制信号也在本包定义；原工具中断配对、慢消费者驱逐、对端断线处理及 TaskOwner 预期失败登记仍在各业务模块执行。

## 旧路径与部署边界

- `system/agentspace/errors.py` 已删除；Agentspace 异常定义位于本包 `system.py`。`system/agentspace/__init__.py` 不再提供异常导出入口。
- `system/lifecycle_errors.py` 作为纯转发模块已删除，不再作为定义或兼容导入入口。生命周期分类、聚合与资源清理辅助函数仍留在所属业务模块，不随异常类型移动。
- `abstract/llm/client.py`、`entry/tool_executor.py`、`entry/session_export.py`、`system/session_export.py`、`subagent/profile.py`、`util/file_metadata.py`、`util/local_fonts.py` 等旧定义位置均只消费统一类型，调用方不能继续依赖旧路径导入。`entry/base_agent_loop.py` 只是异常调用方，不属于旧异常定义位置。
- 用户须停机后完整部署本包与全部调用方并重启进程，避免旧模块缓存中的异常类对象与新类型混用。`run.py` 的合并复制不会自动删除目标侧独有旧文件；`force_init` 对 fast仓库同样只合并覆盖。用户应保护本地进化修改后，按实际部署范围定向处理旧文件，不删除整个业务包或整个运行时根目录。
- 开发助手AI不读取、搜索、修改或清理 `workspace/` 下的代码；部署提示不构成运行时操作授权。

## 持久化与验收状态

异常不加入 easysave 或 `entity/typeref.py`，本次源码迁移不改变持久化模型、存储结构或 easysave key，也不新增 System、装配依赖或前端协议。若未来发生真实持久化结构变化，仍须遵守原版本升级约定，不能把本次 key 未变当作通用豁免。

本次仅进行源码迁移及文档同步，未运行测试、实际导入、构建、校验或应用。文档与只读文本审阅不代表运行通过，完整部署后的运行验收由用户执行。

## HTTP端点组件的错误边界（2026-10-31）

本轮网关组件化没有新增origin仓库自定义异常或统一异常基类；业务异常仍按本包原定义显式导入，HTTPException/RequestValidationError来自框架。HTTPErrorDetail位于entity/puretype/http.py，是不持久化的纯传输数据，不是异常类型，不进入typeref/easysave。

Gateway只把明确业务拒绝映射非2xx和结构化detail；格式/字段/参数校验保持标准422列表，特殊有界导出校验排除原输入bytes和ctx异常对象。HTTPException族与HTTP在途ApplicationStoppingError有专用边界；后者不注册全局以误接WS。没有新增Exception/RuntimeError/OSError全局捕获，存储损坏、必要保存失败和其他逻辑之外错误继续传播；明确返回的正常pending/部分结果也不一律抛异常。

BaseAgentLoop合并缺内部依赖直接用标准RuntimeError，不在业务包新建异常。原业务异常继承/所有权/存储版本不变；用户需同批部署网关和前端，人工验收仍未执行。
