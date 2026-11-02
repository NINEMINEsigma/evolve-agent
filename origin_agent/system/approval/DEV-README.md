# system/approval/ — 审批系统

## 归属与目录迁移（2026-11-02，当前约定）

审批业务整体由 `component/approval/` 迁至 `system/approval/`。核心 `ApprovalSystem` 是通过 `IApprovalSystem` 装配的业务 System，而不是架构 Component；模式存储、审批后端、白名单与公共审批流程继续按功能聚合在本包。旧 Python 导入路径 `component.approval` 退役，不保留转发、别名、重复实现或 `sys.modules` 注入。

本包整体迁移10个Python文件，公共入口 `system.approval` 保持原24项 `__all__` 成员及顺序；`ApprovalSystem`、Store和Manager不额外加入包入口导出。父包 `system/__init__.py` 不聚合审批。除模式加载前的 `contains` 检查外，本次仅改变模块位置与必要导入，不改变审批策略、接口、System依赖、持久化格式或前端协议。

## 模块地图

| 文件 | 职责 |
|---|---|
| `__init__.py` | 重新导出公共审批入口、后端、策略与entity类型，不创建运行实例 |
| `system.py` | `ApprovalSystem`：模式存储、后端管理器、白名单与模型审批请求的唯一生命周期所有者 |
| `manager.py` | `ApprovalBackendManager`：查询Profile状态、取得后端、失效客户端缓存与关闭 |
| `backend.py` | `ApprovalBackend`抽象及`ProfileApprovalBackend`，通过项目级审批Profile访问外部模型 |
| `mode_store.py` | `ApprovalModeStore`：会话级模式缓存、恢复、尽力保存、初始化和继承 |
| `allowlist.py` | `ToolAllowlistStore`与无状态委托入口：参数精确匹配的工具白名单 |
| `policy.py` | `needs_approval`、`MAIN_SESSION_POLICY`、`SUB_SESSION_POLICY`；策略数据类仍定义于entity |
| `core.py` | `request_user_confirm`统一审批出口、`build_denied_tool_result`拒绝结果构造 |
| `executor.py` | `execute_with_approval`主会话审批流程及调用参数批准标记 |
| `handsfree.py` | 会话模式公共入口、脱手模式请求与普通文本决策解释 |

纯类型 `ApprovalMode`、`SessionApprovalModeState`、`ApprovalPolicy`、`ApprovalResult`、`ApprovalOutcome`和审批Profile响应模型仍在 `entity/puretype/approval.py`。公共异常统一从 `entity.error` 导入，本包不定义异常类型或兼容异常入口，见[异常定义包](../../entity/error/DEV-README.md)。

## System、对象归属和导入边界

`ApprovalSystem`只继承`IApprovalSystem`，构造显式声明`ILLMProfileStore`依赖；`IRuntimeSystem`和`ILoggerSystem`依赖由`IDPRuntimeSystem`继承链自动加入。Application在`_build_system_manifest(context)`内延迟导入具体实现，仍以`(IApprovalSystem, ApprovalSystem())`注册，21个接口槽位及顺序不变。业务入口统一经`Application.current().get_system(IApprovalSystem)`取得唯一实例。

`virtual_awake`取得唯一RuntimeContext与Profile Store，构造唯一`mode_store`、`backend_manager`、`allowlist`及`TaskOwner`；三个叶对象不是独立System，不建立模块级配置、锁或服务单例。`mode_store`、`backend_manager`、`allowlist`为只读属性，接口契约见[interface文档](../../interface/DEV-README.md)。接口对具体叶类型只在`TYPE_CHECKING`内导入，包内Application查询相关导入继续在函数体内，不以反射、运行时类型求值或父包聚合代替依赖约定。

模型请求通过`ApprovalSystem.chat(messages)`的`TaskOwner.run_request`登记，调用方等待真实请求结果。关闭先`close_admission`并`cancel_pending`，确认实际请求和结果交接结束后才释放后端客户端缓存；用户取消不升级为整个应用失败，生命周期/必要清理失败仍传播，不停止用户外部模型服务。

Runtime查询统一使用继承的`runtime`属性，不缓存Runtime。关闭主体为`virtual_prepare_shutdown`：Application在架构仍绑定期间等待准备，framework解绑后的公共关闭钩子只核对准备结果。Logger根级联、工具真实工作屏障与5秒关闭硬截止保持，完整约定见[system文档](../DEV-README.md)。

## 审批Profile与模型决策

`ApprovalBackend`声明异步`chat(messages: list[BaseMessage]) -> str`及同步`is_available() -> bool`；实际实现只有`ProfileApprovalBackend`，通过`ILLMProfileStore.get_approval_profile()`取得`LLMProfileData.approval_profile`根对象引用。没有本地/远程双后端、自动本地模型检测或独立模型进程。

Profile查询和客户端缓存变更复用`LLMProfileStore.locked()`。客户端按`llm_client_name/base_url/model/api_key/max_context_tokens`五字段连接指纹缓存，变化时重建；审批参数使用Profile副本，不改根对象。`ApprovalBackendManager.get_backend/get_state/invalidate/shutdown`保持原业务语义，后端不可用不自动改写已恢复的脱手模式。

`_handsfree_confirm`将工具名称、参数schema、实际参数、reason及可选上下文提交给审批Profile。模板仍在`templates/approval/system_prompt.md`，通过`util.pathutils.get_templates_dir()`定位，不依赖本包文件深度。模板声明审批模型只见单次调用，不读取用户消息；schema description是调用方Agent指令而不是审批判据，本质只读操作应放行，不新增前置条件或用户同意审查。

模型返回普通文本标记，不请求或解析JSON决策。否定标记优先：`[DENY]`/`[REJECT]`/`[拒绝]`/`[否决]`拒绝；`[ALLOW]`/`[APPROVE]`允许一次；空响应、缺决策标记、后端不可用或普通模型请求失败按原系统拒绝路径处理。`ApplicationStoppingError`及生命周期失败继续传播，不由拒绝结果吞掉。`build_denied_tool_result`保留model/user/parent_agent/system拒绝来源。

## 三种模式与主会话流程

模式由服务端按主会话保存，前端不持久化。`set_approval_mode(session_id, mode)`返回实际模式：用户新请求脱手模式而Profile不可用时回退手动；`get_approval_mode`恢复已保存脱手模式时不检查Profile可用性。审批Profile清空、删除或失效不批量改写会话模式；实际模型审批不可用时拒绝。YOLO不依赖审批Profile。

普通模式、随意聊聊及多Agent模式的所有参与Agent均通过`ToolExecutor.execute → execute_with_approval`走主会话策略：

1. YOLO全部免审批，包括critical，但不绕过工具可用范围、沙盒权限或参数校验。
2. 手动模式safe/write直接执行；dangerous/critical需要审批。脱手模式safe直接执行，write/dangerous/critical需要审批。
3. 需要审批的非critical调用可由工具名称和规范化参数白名单放行；critical在手动/脱手模式跳过白名单。
4. 手动模式剩余调用由用户审批；脱手模式write/dangerous走模型，critical仍由用户审批。
5. 拒绝返回`ApprovalOutcome.denied`及拒绝结果；允许后设置原`_pre_approved/_approval_action`标记。仅非脱手、非critical的`allow_always`加入白名单。

`set_handsfree_mode/is_handsfree_mode/disable_all_handsfree_modes`保留为既有业务兼容函数；这不表示旧模块路径仍兼容。`disable_all_non_manual_modes`是显式管理入口，委托Store遍历现存会话，Profile生命周期不调用它。

普通子会话采用`SUB_SESSION_POLICY`：write/dangerous/critical在手动/脱手模式都需审批，按父主会话模式分流，手动由父Agent审批，脱手由审批模型处理，YOLO免审批；其白名单行为保持原实现。临时Agent仍为`TASKAGENT ∩ safe`，不进入审批流程，详见[子Agent文档](../../subagent/DEV-README.md)。

## 会话审批模式存储

`ApprovalModeStore`由ApprovalSystem唯一持有，以业务`threading.RLock`保护缓存、恢复和“先更新内存、后尽力保存”的事务。根目录为`RuntimeContext.workspace / SESSIONS_DIR_NAME`，各主会话文件为`<session_id>/approval_mode.es`；迁移代码不搬动或重写运行时数据。

- 缺文件：返回手动模式，不创建文件。
- 已有文件：先建立`make_config(path)`，用`contains(SESSION_APPROVAL_MODE_ES_KEY, config)`确认目标`v1` key；缺key明确记录会话ID、路径和key的warning，返回手动，不调用load、不写盘，不假装成功读取或空数据。
- 有key：复用同一config调用`load`，保留`ignore_missing_fields=True`及根类型、mode类型检查。contains解析/I/O异常或load损坏/类型错误继续进入原warning后手动模式的保守回退路径。
- contains和load是两次独立读取，不是跨调用原子快照；期间变化仍按原加载异常策略处理。
- 保存直接传`SessionApprovalModeState` BaseModel给easysave，不先`model_dump()`。easysave负责路径锁、前置`.bak`、同目录临时文件、同步与原子替换；写入失败记录warning且不回滚内存、不自动处理备份。

文件逻辑key仍为`v1`，稳定类型名仍为`v1::SessionApprovalModeState`，定义、对象引用和存储语义均未变，无需升级版本或数据迁移脚本。ES key与类型token版本各用原独立常量，不得混用。

普通新会话、单源分支、多父合并和首次创建的随意聊聊通过`initialize_session`初始化手动模式；上下文超限自动延续在新会话创建后、来源归档前通过`inherit_session`继承当前模式。归档保留，永久删除会话目录后`forget_session`清缓存。显式批量重置复用会话ID校验和尽力保存，sessions根不存在时不创建孤立目录。

## 工具白名单

`ToolAllowlistStore`唯一持有`RuntimeContext.workspace / tool_allowlist.json`路径和RLock；模块级`is_allowed/add_allowed`仅委托所属System，不拥有第二份状态。JSON读取/尽力保存格式和错误策略不变，JSON编码使用`ToolAllowlistEntry.model_dump()`，不是easysave类型降级。

匹配按工具名与规范化参数精确进行，排除`TOOL_INTERNAL_ARG_KEYS`（`_session_id/_pre_approved/_approval_action`）及`reason`，并非允许工具的所有参数组合。主会话critical在手动/脱手模式不使用白名单。

## 完整部署与人工验收

用户须停机并保护本地进化改动后，同步本包及全部调用方、共享宿主扩展，再重新启用。所有可能启动、后续提升或承担修复的fast/slow/fallback仓库都必须具有完整新包与配套调用文件；当前不存在的运行仓库，之后创建/恢复的来源也必须是完整新版本。共享扩展不能先改用新路径，却继续配合只有旧审批包的代码副本；未知外部扩展的旧导入由用户确认和同步。不支持同进程新旧模块混装、reload或热迁移。

`run.py`合并复制不会删除目标侧独有旧文件，force_init对fast仓库亦不保证清除。用户在实际部署范围定向处理旧`component/approval/`源码残留，保留component的MCP/Cron/动态端点、其他用户内容和审批模式、白名单、History。不能删除整个component、system、workspace或会话目录代替定向处理。开发助手AI不读取、搜索或操作运行时代码，也不代部署、启动、构建或校验。

`logging.getLogger(__name__)`自然改为`system.approval.*`，使用旧logger名称筛选的外部配置由用户调整，不提供旧日志名兼容。本次没有前端协议/产物变化，无需因本次迁移重新构建前端。

用户按任务文件`.tasks/2026-11-02_3_approval-package-relocation.md`的V01–V14及R3验收部署一致性、模式切换/恢复、主/子会话策略、白名单、不可用模型、中断关闭及缺key保守回退。未运行的副本只记录部署核对，不宣称运行验收通过，也不为验收制造崩溃或触发进化。本次仅源码实施、文档同步和只读文本审阅，未运行测试、实际导入、校验、构建或应用；不宣称字节级换行一致或运行通过。
