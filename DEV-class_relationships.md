# Agent Loop 类关系图

## 继承关系（mermaid）

```mermaid
classDiagram
    class BaseAgentLoop {
        +session_id
        +app
        #_inbox
        #_cancel_event
        #_message_hooks_cache
        #_history
        #_session_store
        #_token_usage
        #_last_prompt_tokens
        +history_store_dir
        +inbox
        +interrupt()
        +is_interrupted()
        +get_token_usage()
        +get_context_tokens()
        +get_session_messages()
        +get_session_history_skeleton()
        +get_session_history_page()
        +get_session_history_resources()
        +edit_session_message()
        +delete_session_messages()
        +regenerate_response()
        +get_tool_resources()
        +pop_session_rotated()
        +is_processing()
        +terminate_session()
        +merge_sessions()
        +persist_history()
        +load_history()
        #_check_cancel()
        #_push_usage_update()
        #_persist_token_usage()
        #_persist_message()
        #_overwrite_history_file()
        #_remove_last_user_message()
        #_load_message_hooks()
        #_collect_hooks_context()
        #_get_hooks_context()
        #_set_dynamic_suffix()
        #_get_sink()*
        #user_character_name*
        #append_user_message()*
        #process_message()*
    }

    class BasePrivateChatAgentLoop {
        #_get_llm_client()*
        #_get_context()*
        #_get_tool_definitions()*
        #_on_context_over_limit()*
        #_build_system_prompt()*
        #_is_auto_executable()
        #_is_auto_approved_tool()
        #_execute_tool()
        #_get_history()
        #_append_history()
        #_build_history_messages()
    }

    class IMainSessionLoop {
        +loop
        +current_character_agent*
        +pop_session_rotated()*
        +get_token_usage()*
        +get_context_tokens()*
        #_interrupt_lock
        #_active_round_task
        #_init_round_registry()
        +register_round_task()
        +unregister_round_task()
        +has_active_round()
        +request_interrupt()
    }

    class ParentAgentLoop {
        #_frontend_sink
        #_llm
        #_lifecycle
        #_tool_executor
        #_stream_consumer
        #_tool_event_callback
        #_processing
        #_process_lock
        #_event_loop
        +subagent_orchestrator
        #_session_manager
        +set_tool_event_callback()
        +set_session_manager()
        +add_memory_provider()
        +get_all_tool_stats()
        +process_message()
        +process_inbox()
        +schedule_inbox_processing()
        +append_user_message()
        +terminate_session()
        +merge_sessions()
        #_run_tool_loop()
        #_maybe_inject_inbox()
        #_append()
        #_blocks_from_dicts()
        #_get_full_history()
        #_store_assistant_with_tools()
        #_extract_text()
        #_collect_skill_prompts()
        #_emit_stream_done()
        #_load_history_from_disk()
    }

    class MultiAgentLoop {
        #_history
        #_agents
        #_sink
        #_agent_names
        #_session_store
        #_token_usage
        #_last_prompt_tokens
        +_get_sink()
        +user_character_name
        +append_user_message()
        +current_character_agent
        +get_token_usage()
        +get_context_tokens()
        #_resolve_llm_client()
        +get_session_messages()
        +clear_session()
        +edit_session_message()
        +regenerate_response()
        #_execute_tool()
        +get_tool_resources()
        +terminate_session()
        +merge_sessions()
        +process_message()
        #_get_available_subagents()
        #_cascade()
        #_run_single_agent()
        #_aggregate_worker_usage()
    }

    class MultiAgentWorker {
        +character_name
        #_system_prompts
        #_messages
        #_tools
        #_llm
        #_sink
        #_loop
        #_stream_consumer
        #_tool_executor
        #_total_token_usage
        #_last_prompt_tokens
        +run()
        #_parse_routing_tags()
        #_error_result()
        #_emit_text()
    }

    class ToolExecutor {
        #_loop
        #_llm
        #_tool_stats
        +get_tool_stats()
        +execute()
    }

    class SessionMessageQueue {
        #_loop
        #_pending
        #_wakeup
        #_event_loop
        #_consumer_task
        #_stopped
        +last_known_sid
        +push()
        +drain_injected()
        +stop()
        +mark_stopped()
    }

    class StreamConsumer {
        #_llm
        #_sink
        #_character_name
        #_cancel_event
        +consume()
    }

    class AgentSink {
        +ask_question()*
        +request_approval()*
        +emit_tool_call()*
        +emit_tool_result()*
        +emit_user_message()*
        +emit_assistant_message()*
        +emit_stream_delta()*
        +emit_stream_done()*
        +emit_usage_update()*
        +emit_progress()*
        +emit_clipboard_display()*
        +emit_subagent_update()*
        +emit_system_message()*
    }

    class FrontendSink {
        #_ws_sinks
        #_pending_confirms
        #_confirm_session_map
        #_pending_asks
        #_ask_session_map
        +register_ws()
        +unregister_ws()
        +close_session()
        +get_ws()
        +get_all_ws()
        +request_approval()
        +resolve_confirm()
        #_deny_session_confirms()
        +ask_question()
        +resolve_ask()
        #_deny_session_asks()
        #_send_msg()
    }

    class ParentAgentSink {
        #_loop
        +ask_question()
        +request_approval()
        +emit_tool_call()
        +emit_tool_result()
        +emit_user_message()
        +emit_assistant_message()
        +emit_stream_delta()
        +emit_stream_done()
        +emit_usage_update()
        +emit_progress()
        +emit_clipboard_display()
        +emit_subagent_update()
        +emit_system_message()
    }

    class SubAgentLoop {
        #_name
        #_ctx
        #_parent_session_id
        #_parent_character_agent
        #_tools
        #_allowed_tool_names
        #_llm
        #_on_message
        #_outbox
        #_pending_approvals
        #_max_turns
        #_last_message_from_parent
        #_paused_event
        #_wake_event
        #_completed
        #_terminated
        #_round_active
        #_build_llm_client()
        +current_character_agent
        +user_character_name
        #_get_llm_client()
        #_get_context()
        #_get_sink()
        #_get_tool_definitions()
        #_build_system_prompt()
        #_on_context_over_limit()
        +append_user_message()
        +run()
        +stop()
        +save_history()
        +inject_parent_message()
        #_maybe_inject_inbox()
        #_queue_for_approval()
        #_execute_approved_tool()
        #_make_tool_msg()
        #_emit()
    }

    class TaskAgentLoop {
        #_build_system_prompt()
        #_is_task_tool_authorized()
        #_get_effective_tool_definitions()
        +run()
    }

    class LoopSessionManager {
        #_loop
        #_history_store_dir
        #_session_rotated_notify
        +initialize()
        +is_context_over_limit()
        +rotate_session_for_continuation()
        +terminate_session()
        +pop_session_rotated()
    }

    class _OrchestratorContext {
        #_parent_session_id
        #_agent_loop
        #_active
        #_active_task
        #_waiting_queue
        #_subagent_names
        #_background_task
        #_interrupted
        #_shutting_down
        +launch()
        +chat_user_direct()
        +chat()
        +approve()
        +stop()
        +get_snapshot()
        +shutdown()
        #_drain_outbox()
        #_push_subagent_ws()
        #_start_subagent()
        #_activate_next()
        #_cycle_loop()
        #_collect_and_inject()
    }

    class SessionManager {
        #_app
        #_chat_sm
        #_loops
        #_store_path
        #_deleting_sessions
        #_deleting_sessions_lock
        +create_session()
        +get_loop()
        +terminate_session()
        +delete_session_runtime()
        +begin_session_delete()
        +is_session_deleting()
        +end_session_delete()
        +replace_loop()
        +rotate_session()
    }

    class MessageRouter {
        +ws
        +sid
        +agentspace_path
        +route()
        #handle_user_message()
        #handle_confirm_response()
        #handle_ask_response()
        #handle_interrupt()
        #handle_file_upload()
        #handle_handsfree_mode()
        #handle_ping()
        #handle_system_message()
        #handle_unsupported()
        #_auto_generate_title()
        #_dispatch_subagent_messages()
        #_process_main_session()
        #_handle_session_rotation()
        #_emit_assistant_reply()
        #_send_token_update()
    }

    class LLMProfileStore {
        #_data
        #_lock
        +list_profiles()
        +get_profile()
        +create_profile()
        +update_profile()
        +remove_profile()
        +to_payload()
    }

    class SessionMetadataService {
        #_runtime_context
        #_llm_profile_store
        #_profile_lock
        #_session_store
        +get_state()
        +select_profile()
        +generate_title()
        +generate_tags()
        +generate_summary()
        +regenerate_summary()
        +ensure_summary()
    }

    class LLMProfileData {
        +profiles
        +approval_profile
        +metadata_profile
    }

    class Application {
        +runtime_context
        +session_metadata_service
        +agentspace_service
        +session_manager
        +approval_mode_store
        +approval_backend_manager
        +cron_router
        +tool_registry
        +frontend_sink
        +subagent_orchestrator
        +subprocess_runner
        #_shutdown_event
        +current()$
        +link_shutdown_event()
        +shutdown_event
        +shutdown()
    }

    class ApprovalModeStore {
        #_sessions_dir
        #_modes
        #_lock
        +get_mode()
        +initialize_session()
        +set_mode()
        +forget_session()
        +reset_all_non_manual_modes()
    }

    class ApprovalBackendManager {
        #_ctx
        #_backend
        #_failed
        +get_backend()
        +shutdown()
    }

    class BaseLLMClient {
        +chat()*
        +chat_stream()*
    }

    class AgentProfile {
        +character_name
        +system_prompts
        +tools
        +llm_client
    }

    class AgentResponse {
        +content
        +visible_characters
        +response_characters
        +reasoning
    }

    class WorkerResult {
        +character_name
        +parsed_json
        +raw_json
        +stream_buffer
        +stream_id
        +total_token_usage
        +last_prompt_tokens
        +reasoning
    }

    class AgentspaceService {
        #_event_hub
        #_lock_registry
        #_operation_gate
        #_trash_store
        #_watcher
        +start()
        +shutdown()
        +list_directory()
        +read_file()
        +write_file()
        +rename_path()
        +move_to_trash()
        +restore_trash()
        +agent_access()
        +release_agent_access()
    }

    class AgentspaceLockRegistry {
        +acquire()
        +release_round()
        +matching()
        +snapshot()
    }

    class AgentspaceEventHub {
        +bind_loop()
        +subscribe()
        +publish_threadsafe()
        +close()
    }

    class Sandbox {
        #_ctx
        #_runner
        #_dynamic_spaces_path
        #_dynamic_spaces_lock
        #_dynamic_spaces_data
        #_dynamic_space_availability
        +list_dynamic_spaces()
        +list_dynamic_spaces_with_availability()
        +normalize_dynamic_space_path()
        +add_dynamic_space()
        +update_dynamic_space()
        +remove_dynamic_space()
        +is_namespaced_path()
        +namespace_bases()
        +resolve()
        +resolve_read()
        +resolve_write()
        +run()
        +run_async()
        +run_async_line_processor()
        +kill_active()
    }

    class ShellManager {
        #_sandbox
        #_shells
        #_session_aliases
        #_registry_lock
        +start_shell()
        +read_shell()
        +write_shell()
        +interrupt_shell()
        +stop_shell()
        +list_shells()
        +stop_shell_for_user()
        +migrate_session()
        +stop_session()
        +shutdown()
    }

    class _ShellSession {
        +shell_id
        +session_id
        +character_name
        +shell_type
        +cwd
        +pid
        #pty
        #reader_thread
        #operation_lock
        #output_event
        #normalizer
        #raw_text
        #text
        #base_offset
        #total_chars
    }

    class SubprocessRunner {
        #_active_procs
        #_procs_lock
        +run()
        +run_async()
        +run_async_line_processor()
        +kill_active()
    }

    class _CronTask {
        +task_id
        +session_id
        +name
        +schedule_type
        +schedule_value
        +command
        +cwd
        +should_schedule
        +next_run
        +run_count
        +last_run
        +log_path
        +skip_agent_notify
        +is_wait
        +wait_message
        #_timer
    }

    class CronRouter {
        #_tasks
        #_lock
        +register()
        +unregister()
        +dispatch()
        +cleanup_session_cron_jobs()
        +migrate_session_cron_jobs()
        +list_cron_tasks_for_session()
    }

    BaseAgentLoop <|-- BasePrivateChatAgentLoop
    BaseAgentLoop <|-- MultiAgentLoop
    BasePrivateChatAgentLoop <|-- ParentAgentLoop
    BasePrivateChatAgentLoop <|-- SubAgentLoop
    SubAgentLoop <|-- TaskAgentLoop
    IMainSessionLoop <|.. ParentAgentLoop
    IMainSessionLoop <|.. MultiAgentLoop
    AgentSink <|-- FrontendSink
    AgentSink <|-- ParentAgentSink
    BaseLLMClient <|-- OpenAIClient
    BaseLLMClient <|-- AnthropicClient
    BaseLLMClient <|-- KsccClient
    MultiAgentLoop --> MultiAgentWorker : creates
    MultiAgentLoop --> AgentProfile : holds
    MultiAgentWorker --> WorkerResult : returns
    MultiAgentWorker --> AgentResponse : parses
    ParentAgentLoop --> ToolExecutor : creates
    ParentAgentLoop --> StreamConsumer : creates
    ParentAgentLoop --> FrontendSink : holds
    ParentAgentLoop --> LoopSessionManager : creates
    ParentAgentLoop --> SessionMessageQueue : holds
    MultiAgentLoop --> SessionMessageQueue : holds
    ParentAgentLoop --> _OrchestratorContext : has via SubAgentOrchestrator
    ParentAgentLoop --> SessionManager : registered by
    SubAgentLoop --> ParentAgentSink : creates
    _OrchestratorContext --> SubAgentLoop : manages
    SessionManager --> IMainSessionLoop : manages
    MessageRouter --> SessionManager : uses
    MessageRouter --> IMainSessionLoop : routes to
    Application --> LLMProfileStore : holds
    Application --> SessionMetadataService : holds
    SessionMetadataService --> LLMProfileStore : resolves Profile
    SessionMetadataService --> SessionStore : reads target session
    LLMProfileStore --> LLMProfileData : owns root
    Application --> SessionManager : holds
    Application --> ApprovalModeStore : holds
    Application --> ApprovalBackendManager : holds
    Application --> FrontendSink : holds
    Application --> SubAgentOrchestrator : holds
    Application --> SubprocessRunner : holds
    Application --> ShellManager : holds
    ShellManager --> _ShellSession : owns
    ShellManager --> Sandbox : resolves cwd and namespaces
    Application --> AgentspaceService : holds
    AgentspaceService --> Sandbox : uses
    AgentspaceService --> AgentspaceLockRegistry : owns
    AgentspaceService --> AgentspaceEventHub : owns
    ApprovalBackendManager --> ApprovalBackend : manages
    Sandbox --> RuntimeContext : holds
    Sandbox --> SubprocessRunner : delegates
    CronRouter --> _CronTask : manages
```

---

## 字段归属（已确认）

| 字段 | 定义类 | 类型 | 说明 |
|---|---|---|---|
| `_inbox` | `BaseAgentLoop` | `Inbox` | 收件箱；子类通过 `self._inbox` 访问属合法继承 |
| `_cancel_event` | `BaseAgentLoop` | `asyncio.Event` | 取消/中断信号；`ToolContext.is_interrupted` 读取 `loop._cancel_event` |
| `_message_hooks_cache` | `BaseAgentLoop` | `list[dict] \| None` | hook 缓存 |
| `_history` | `BaseAgentLoop` / `MultiAgentLoop` | `History` | BaseAgentLoop 定义；MultiAgentLoop 覆盖传入 |
| `_session_store` | `BaseAgentLoop` / `MultiAgentLoop` | `SessionStore \| None` | BaseAgentLoop 定义；MultiAgentLoop 覆盖 |
| `_token_usage` | `BaseAgentLoop` / `MultiAgentLoop` | `int` | 累计 token；MultiAgentLoop 独立维护 |
| `_last_prompt_tokens` | `BaseAgentLoop` | `int` | 最近一次 prompt tokens |
| `_agentspace_round_ids` | `BaseAgentLoop` | `dict[str, str]` | 角色名到当前 Agentspace 回复轮次 ID；完整收尾后释放路径锁 |
| `_loaded_toolsets` | `BaseAgentLoop` | `set[str]` | 会话级已加载工具集名称集合；由 `_restore_loaded_toolsets` 从 SessionStore 恢复 |
| `_toolsets` | `ToolRegistry` | `dict[str, ToolsetEntry]` | 工具集元数据表；由 `register_toolset` 或工具注册时自动创建 |
| `round_id` | `ToolContext` | `str` | 当前 Agent 回复轮次唯一 ID，明确 `ws:` 文件接触登记的 owner |
| `_get_sink()` | `BaseAgentLoop` | abstract method | `ToolContext.sink` 调用 `loop._get_sink()` |
| `_overwrite_history_file()` | `BaseAgentLoop` | method | 类内部使用 |
| `_remove_last_user_message()` | `BaseAgentLoop` | method | 类内部使用 |
| `_update_last_user_message()` | `History` | method | 被 `BaseAgentLoop._remove_last_user_message()` 调用，属于跨类访问 |
| `_frontend_sink` | `ParentAgentLoop` | `FrontendSink` | sink 实例 |
| `_llm` | `ParentAgentLoop` | `BaseLLMClient` | LLM 客户端（通过 `create_llm_client()` 工厂构造） |
| `_lifecycle` | `ParentAgentLoop` | `LoopSessionManager` | session 生命周期管理 |
| `_tool_executor` | `ParentAgentLoop` | `ToolExecutor` | 工具执行器 |
| `_stream_consumer` | `ParentAgentLoop` | `StreamConsumer` | 流消费器 |
| `_tool_event_callback` | `ParentAgentLoop` | `Callable \| None` | 工具事件回调 |
| `_processing` | `ParentAgentLoop` | `bool` | 是否正在处理 |
| `_process_lock` | `ParentAgentLoop` | `asyncio.Lock` | 处理锁 |
| `_event_loop` | `ParentAgentLoop` | `asyncio.AbstractEventLoop \| None` | 事件循环引用 |
| `_session_manager` | `ParentAgentLoop` | `SessionManager \| None` | gateway session manager |
| `_interrupt_lock` | `IMainSessionLoop`（公共实现） | `asyncio.Lock` | 同会话中断请求互斥锁 |
| `_active_round_task` | `IMainSessionLoop`（公共实现） | `asyncio.Task \| None` | 已取得 `_process_lock` 的当前单次主会话回复 task；长期队列 consumer 与等待处理锁的 child 不登记 |
| `_agents` | `MultiAgentLoop` | `dict[str, AgentProfile]` | Agent 配置档案 |
| `_sink` | `MultiAgentLoop` | `AgentSink` | sink |
| `_agent_names` | `MultiAgentLoop` | `list[str]` | agent 名列表 |
| `_system_prompts` | `MultiAgentWorker` | `list[str]` | Agent 系统提示词 |
| `_messages` | `MultiAgentWorker` | `list[BaseMessage]` | 该 Agent 视角的历史消息 |
| `_tools` | `MultiAgentWorker` | `list[dict]` | 该 Agent 可用的工具定义 |
| `_llm` | `MultiAgentWorker` | `BaseLLMClient` | LLM 客户端 |
| `_sink` | `MultiAgentWorker` | `AgentSink` | 前端流式输出 sink |
| `_loop` | `MultiAgentWorker` | `IMainSessionLoop` | 所属 MultiAgentLoop 引用 |
| `_stream_consumer` | `MultiAgentWorker` | `StreamConsumer` | 流消费器（每轮独立 stream_id） |
| `_tool_executor` | `MultiAgentWorker` | `ToolExecutor` | 工具执行器（复用统一逻辑） |
| `_total_token_usage` | `MultiAgentWorker` | `int` | 被 `MultiAgentLoop._aggregate_worker_usage` 读取 |
| `_last_prompt_tokens` | `MultiAgentWorker` | `int` | 被 `MultiAgentLoop._aggregate_worker_usage` 读取 |
| `_llm` | `StreamConsumer` | `BaseLLMClient` | LLM 客户端 |
| `_sink` | `StreamConsumer` | `AgentSink` | 前端 sink |
| `_character_name` | `StreamConsumer` | `str` | 当前角色名 |
| `_cancel_event` | `StreamConsumer` | `asyncio.Event` | 共享的当前回复轮次取消信号；消费器将其与流读取竞速 |
| `_last_partial` | `StreamConsumer` | `LLMResponse \| None` | 当前 stream 正常结束或强制取消前保存的部分结果；每次 `consume()` 开始时重置 |
| `_loop` | `ToolExecutor` | `IMainSessionLoop` | 持有 loop 引用，访问其内部字段 |
| `_llm` | `ToolExecutor` | `BaseLLMClient` | LLM 客户端（用于 ask_agent_reason） |
| `_tool_stats` | `ToolExecutor` | `dict[str, dict[str, int]]` | 工具调用统计 |
| `_cancel_cleanup_tasks` | `ToolExecutor` | `set[asyncio.Task[Any]]` | 超过同步清理窗口的已取消 handler task 强引用集合；done callback 负责观察异常并移除 |
| `_loop` | `SessionMessageQueue` | `IMainSessionLoop` | 所属主会话 loop |
| `_pending` | `SessionMessageQueue` | `deque[QueuedMessage]` | 待消费 FIFO；每次只取一条消息，每条保留自己的 `llm_profile_name`；当前工具轮不再 drain 用户消息 |
| `_wakeup` | `SessionMessageQueue` | `asyncio.Event \| None` | 空闲消费循环的唤醒事件 |
| `_event_loop` | `SessionMessageQueue` | `asyncio.AbstractEventLoop` | 构造时捕获运行中的事件循环，供跨线程入队 |
| `_consumer_task` | `SessionMessageQueue` | `asyncio.Task \| None` | 懒启动的空闲消费任务 |
| `_stopped` | `SessionMessageQueue` | `bool` | `stop()` / `mark_stopped()` 置位 |
| `last_known_sid` | `SessionMessageQueue` | `str` | 旋转检测：与当前 session_id 比对 |
| `_llm_profile` | `SubAgentLoop` | `LLMProfile \| None` | 临时Agent使用调用时 Profile 快照；普通角色子Agent的运行字段来自动态角色档案引用的 Profile |
| `llm_profile` | `SubRuntimeContext` | `LLMProfile \| None` | TaskAgent持有调用时活动 Profile的非持久化深快照；普通角色子Agent不持久化独立配置 |
| （无新增字段） | `TaskAgentLoop` | — | 全部继承 `SubAgentLoop`；覆写无系统提示词、`TASKAGENT ∩ safe` 定义/执行授权及完成即终止行为 |
| `_ws_sinks` | `FrontendSink` | `dict[str, WebSocket]` | session_id → WebSocket 映射 |
| `_pending_confirms` | `FrontendSink` | `dict[str, Future]` | 外部解析确认结果 |
| `_confirm_session_map` | `FrontendSink` | `dict[str, str]` | 外部映射确认到 session |
| `_pending_asks` | `FrontendSink` | `dict[str, Future]` | 外部解析提问结果 |
| `_ask_session_map` | `FrontendSink` | `dict[str, str]` | 外部映射提问到 session |
| `_loop` | `ParentAgentSink` | `SubAgentLoop` | 持有 SubAgentLoop 引用，访问其内部字段 |
| `_outbox` | `SubAgentLoop` | `list[str]` | 被 orchestrator 读取 |
| `_pending_approvals` | `SubAgentLoop` | `list[PendingToolCall]` | 被 `ParentAgentSink` 读取/写入 |
| `_paused_event` | `SubAgentLoop` | `asyncio.Event` | 被 `ParentAgentSink` 读取/设置 |
| `_emit()` | `SubAgentLoop` | method | 被 `ParentAgentSink` 调用 |
| `_parent_session_id` | `SubAgentLoop` | `str` | 被 `ParentAgentSink` 读取 |
| `_loop` | `LoopSessionManager` | `ParentAgentLoop` | 大量访问 loop 的 protected 字段 |
| `_history_store_dir` | `LoopSessionManager` | `Path \| None` | 历史存储目录 |
| `_session_rotated_notify` | `LoopSessionManager` | `dict[str, str]` | session 旋转通知 |
| `_agent_loop` | `_OrchestratorContext` | `ParentAgentLoop` | 访问父 loop 的 `current_character_agent` 等 |
| `_active` / `_active_task` | `_OrchestratorContext` | `dict` | 管理 SubAgentLoop 实例 |
| `_loops` | `SessionManager` | `dict[str, IMainSessionLoop]` | 管理 loop 映射 |
| `_deleting_sessions` | `SessionManager` | `set[str]` | 正在永久删除的主会话 ID；Gateway 在持久化移除完成前据此拒绝恢复连接 |
| `_deleting_sessions_lock` | `SessionManager` | `threading.Lock` | 删除中集合的检查并添加、查询和移除同步边界 |
| `ws` | `MessageRouter` | `WebSocket` | WebSocket 连接引用 |
| `sid` | `MessageRouter` | `str` | 当前 session_id（旋转时更新） |
| `agentspace_path` | `MessageRouter` | `Path \| None` | 文件上传目标目录 |
| `_shutdown_event` | `Application` | `asyncio.Event \| None` | `main.py::App` 绑定的进程关闭信号；Gateway 通过只读 `shutdown_event` 属性让 SSE 长连接正常退出 |
| `runtime_context` | `Application` | `RuntimeContext` | 运行时上下文 |
| `_profile_lock` | `Application` | `threading.RLock` | Profile 根对象、名称指针与会话选择共用的进程锁 |
| `_llm_profile_store` | `Application` | `LLMProfileStore \| None` | 进程内唯一的 `LLMProfileData` 根对象存储 |
| `_session_metadata_service` | `Application` | `SessionMetadataService \| None` | 进程内唯一的标题、标签、摘要生成服务；解析全局元数据 Profile与目标会话回退 |
| `_approval_mode_store` | `Application` | `ApprovalModeStore \| None` | 进程内唯一的主会话审批模式缓存与持久化服务 |
| `_sessions_dir` | `ApprovalModeStore` | `Path` | sessions 根目录；各主会话模式保存到自身目录的 `approval_mode.es` |
| `_modes` | `ApprovalModeStore` | `dict[str, ApprovalMode]` | 已惰性读取或当前进程已修改的会话审批模式缓存 |
| `_lock` | `ApprovalModeStore` | `threading.RLock` | 缓存读取、磁盘恢复、模式更新和兼容批量重置的同步边界 |
| `_runtime_context` | `SessionMetadataService` | `RuntimeContext` | 创建单次元数据 LLM 客户端所需的运行时上下文 |
| `_llm_profile_store` | `SessionMetadataService` | `LLMProfileStore` | 读取全局元数据 Profile和目标会话回退 Profile |
| `_profile_lock` | `SessionMetadataService` | `threading.RLock` | 解析根对象并复制单次 Profile快照的同步边界 |
| `_session_store` | `SessionMetadataService` | `SessionStore` | 读取目标会话 Profile名称指针、History和摘要 |
| `_subprocess_runner` | `Application` | `SubprocessRunner \| None` | 进程内唯一的内部子进程执行器（同步、真异步与逐行消费），注入 Sandbox 委托 |
| `_shell_manager` | `Application` | `ShellManager \| None` | 进程内唯一的 Windows ConPTY Shell会话管理器；持有长期交互式 Shell |
| `_shells` | `ShellManager` | `dict[str, _ShellSession]` | Shell ID 到运行时会话状态的唯一注册表 |
| `_session_aliases` | `ShellManager` | `dict[str, str]` | 自动旋转后的旧主会话 ID 到新 ID 别名，仅供活动旧上下文解析 |
| `_registry_lock` | `ShellManager` | `threading.RLock` | Shell 注册表、所有权迁移和别名链的同步边界 |
| `pty` / `reader_thread` | `_ShellSession` | `PTY` / `threading.Thread \| None` | ConPTY 对象与唯一输出读取线程 |
| `operation_lock` / `output_event` | `_ShellSession` | `asyncio.Lock` / `asyncio.Event` | Agent 操作串行化与输出/退出唤醒 |
| `raw_text` / `text` / `base_offset` / `total_chars` | `_ShellSession` | `str` / `str` / `int` / `int` | 有界原始与规范化输出及绝对字符位置边界 |
| `_agentspace_service` | `Application` | `AgentspaceService \| None` | Agentspace 版本化 CRUD、文件锁、垃圾桶、watcher 与 `AgentspaceEventHub` 的唯一业务服务；Gateway适配为独立编辑器 SSE和聊天 WebSocket事件 |
| `session_manager` | `Application` | `SessionManager \| None` | session 管理器 |
| `approval_mode_store` | `Application` | `ApprovalModeStore \| None` | 主会话审批模式存储，只读属性暴露 Application持有实例 |
| `approval_backend_manager` | `Application` | `ApprovalBackendManager \| None` | 审批后端管理器 |
| `cron_router` | `Application` | `CronRouter \| None` | Cron 路由器 |
| `tool_registry` | `Application` | `ToolRegistry \| None` | 工具注册表 |
| `frontend_sink` | `Application` | `FrontendSink \| None` | 前端 sink |
| `subagent_orchestrator` | `Application` | `SubAgentOrchestrator \| None` | 子 Agent 编排器 |
| `_backend` | `ApprovalBackendManager` | `ApprovalBackend \| None` | 审批后端实例（懒加载） |
| `_failed` | `ApprovalBackendManager` | `bool` | 审批后端是否不可用 |
| `character_name` | `AgentProfile` | `str` | Agent 角色名 |
| `system_prompts` | `AgentProfile` | `list[str]` | 系统提示词列表 |
| `tools` | `AgentProfile` | `list[dict]` | 工具定义列表 |
| `llm_client` | `AgentProfile` | `BaseLLMClient` | LLM 客户端实例 |
| `_ctx` | `Sandbox` | `RuntimeContext` | 被多个 extools 直接访问 `sb._ctx.agentspace` |
| `_runner` | `Sandbox` | `SubprocessRunner \| None` | 子进程执行委托目标；`None` 时惰性获取 `Application.current().subprocess_runner` |
| `_dynamic_spaces_path` | `Sandbox` | `Path` | workspace 根下独立动态空间 easysave 文件路径 |
| `_dynamic_spaces_lock` | `Sandbox` | `threading.RLock` | 动态空间根对象、持久化和可用性状态的并发边界 |
| `_dynamic_spaces_data` | `Sandbox` | `DynamicSandboxSpaceData` | fast 模式全局动态沙盒空间持久化根对象；fallback 为空 |
| `_dynamic_space_availability` | `Sandbox` | `dict[str, bool]` | 上次记录的目录可用性，用于状态变化日志去重 |
| `_active_procs` | `SubprocessRunner` | `dict[str, list[Popen \| Process]]` | session_id → 活动子进程登记（同步 `Popen` 与异步 `Process` 混合） |
| `_procs_lock` | `SubprocessRunner` | `threading.Lock` | 活动进程登记表锁 |
| `_tasks` | `CronRouter` | `dict[str, dict[str, _CronTask]]` | 被 cron_tools 模块级函数直接访问 |
| `_lock` | `CronRouter` | `threading.Lock` | 被 cron_tools 模块级函数直接访问 |
| `_timer` | `_CronTask` | `threading.Timer` | 被 cron_tools 模块级函数直接访问 |

---

## 已识别的外部访问（跨类/跨模块）

| 访问方 | 被访问字段 | 被访问类 | 位置 | 说明 |
|---|---|---|---|---|
| `ToolContext.resource_session_id` | `parent_session_id`（若公开且非空） | `SubAgentLoop` / `TaskAgentLoop` | `entry/base_agent_loop.py` | 为长期资源选择父主会话 ID；其他 Loop 回退当前 session_id |
| `RunTaskAgent` handler | `llm_profile` / `snapshot_profile()` | `ToolContext` / `LLMProfileStore` | `component/multiagenttools/run_taskagent.py` | 通过公开工具上下文取得活动 Profile，并在 Store共享锁内创建非持久化深快照；不访问主会话 protected字段 |
| Shell 工具 handlers | `shell_manager` | `Application` | `component/tools/shell.py` | 按资源主会话 ID 与角色名创建或操作 Shell会话 |
| 会话终结/旋转 | `stop_session()` / `migrate_session()` | `ShellManager` | `entry/session_manager.py`、`entry/multi_agent_loop.py` | 手动终结停止；自动旋转迁移 Shell 所有权 |
| Gateway Shell REST | `list_shells()` / `stop_shell_for_user()` | `ShellManager` | `gateway/server.py` | 用户查看同会话元数据并直接停止 Shell |
| `ToolContext.sink` | `_get_sink()` | `BaseAgentLoop` | `entry/base_agent_loop.py` | 工具通过 `ctx.sink` 访问 loop 的 sink |
| `ToolContext.is_interrupted` | `_cancel_event` | `BaseAgentLoop` | `entry/base_agent_loop.py` | 工具通过 `ctx.is_interrupted` 读取取消状态 |
| `ToolContext.agentspace_access` | `agentspace_service` | `Application` | `entry/base_agent_loop.py` | 以 `round_id` 向 `AgentspaceService` fail-closed 登记明确 `ws:` 路径 |
| `ToolExecutor.execute` | `is_toolset_loaded()` | `BaseAgentLoop` | `entry/tool_executor.py` | 审批前检查工具集加载状态 |
| `ToolRegistry.dispatch/async_dispatch` | `is_toolset_loaded()` | `BaseAgentLoop` (via `ToolContext.loop`) | `abstract/tools/registry.py` | 分发前统一拦截未加载工具 |
| `build_system_prompt` | `get_loaded_toolsets()` | `BaseAgentLoop` | `system/prompt.py` | 构造工具集目录提示词块 |
| `LoadToolset handler` | `load_toolsets()` | `BaseAgentLoop` (via `ToolContext.loop`) | `component/tools/load_toolset.py` | 加载工具集并持久化 |
| 各 Agent Loop 回复收尾 | `release_agent_access()` | `AgentspaceService` | `entry/parent_agent_loop.py`、`entry/multi_agent_loop.py`、`subagent/loop.py`、`subagent/taskloop.py` | 主Agent、参与Agent、子Agent与临时Agent在匹配 round `finally` 释放 |
| `BaseAgentLoop._remove_last_user_message` | `_update_last_user_message()` | `History` | `entry/base_agent_loop.py` | 跨类调用 History 的 protected 方法 |
| `MultiAgentLoop._aggregate_worker_usage` | `_total_token_usage` | `MultiAgentWorker` | `entry/multi_agent_loop.py` | 读取 worker 内部 token 统计 |
| `MultiAgentLoop._aggregate_worker_usage` | `_last_prompt_tokens` | `MultiAgentWorker` | `entry/multi_agent_loop.py` | 读取 worker 内部 token 统计 |
| `MultiAgentLoop._run_single_agent` | `cancel_event` / `history` / `persist_history` / `session_id` | `BaseAgentLoop` (via `IMainSessionLoop.loop`) | `entry/multi_agent_loop.py` | 通过 `self._loop.loop._xxx` 访问 loop 内部 |
| `MultiAgentWorker.__init__` | `_cancel_event` | `BaseAgentLoop` (via `IMainSessionLoop.loop`) | `entry/multi_agent_worker.py` | 通过 `self._loop.loop.cancel_event` 读取 |
| `MultiAgentWorker.run` | `_history` / `persist_history()` | `MultiAgentLoop` (via `IMainSessionLoop.loop`) | `entry/multi_agent_worker.py` | 通过 `self._loop.loop.history` / `persist_history` 访问 |
| `ToolExecutor.execute` | `cancel_event` / `get_sink()` / `get_hooks_context()` / `session_id` | `BaseAgentLoop` (via `IMainSessionLoop.loop`) | `entry/tool_executor.py` | 通过 `self._loop.loop._xxx` 访问 loop 内部 |
| `ToolExecutor.execute` | `is_interrupted()` / `current_character_agent` | `IMainSessionLoop` / `BaseAgentLoop` | `entry/tool_executor.py` | 访问 loop 状态 |
| `ParentAgentSink.request_approval` | `_parent_session_id`, `_pending_approvals`, `_paused_event`, `_emit()` | `SubAgentLoop` | `entry/agent_sink.py` | 直接访问子 agent 内部字段/方法 |
| `ParentAgentSink.emit_*` | `_emit()` / `_parent_session_id` | `SubAgentLoop` | `entry/agent_sink.py` | 转发事件时读取子 agent 内部 |
| `ParentAgentSink.emit_stream_done` | `frontend_sink` | `Application` | `entry/agent_sink.py` | 通过 `Application.current().frontend_sink` 转发到父会话前端 |
| `LoopSessionManager.initialize` | `_session_store`, `_history`, `session_id` | `ParentAgentLoop` | `entry/session_manager.py` | 初始化时读写 loop 内部 |
| `LoopSessionManager.is_context_over_limit` | `_last_prompt_tokens`, `app.runtime_context` | `ParentAgentLoop` | `entry/session_manager.py` | 读取 loop 内部 token 和配置 |
| `LoopSessionManager.rotate_session_for_continuation` | `_remove_last_user_message`, `_append`, `_history`, `_last_prompt_tokens`, `_session_store`, `_session_manager`, `_llm`, `load_history`, `persist_history` | `ParentAgentLoop` | `entry/session_manager.py` | 旋转时大量调用 loop 内部 |
| `LoopSessionManager._terminate_session` | `_session_manager`, `_session_store`, `_history`, `_llm`, `get_full_history` | `ParentAgentLoop` | `entry/session_manager.py` | 终结会话时大量调用 loop 内部 |
| `TaskAgentLoop`（模块级 import） | `_interrupted_result()` | `entry/tool_executor.py`（模块级函数） | `subagent/taskloop.py` | 跨模块导入 protected 函数，构造中断/异常时的工具结果占位 |
| `_OrchestratorContext._drain_outbox` | `_outbox` | `SubAgentLoop` | `subagent/orchestrator.py` | 直接读取并清空 outbox |
| `_OrchestratorContext.get_snapshot` | `_history.messages`, `pending_approvals_info` | `SubAgentLoop` | `subagent/orchestrator.py` | 读取子 agent 历史 |
| `_OrchestratorContext._start_subagent` | `_history` | `SubAgentLoop` | `subagent/orchestrator.py` | 加载历史时覆盖 `_history` |
| `_OrchestratorContext._collect_and_inject` | `outbox` / `_outbox` | `SubAgentLoop` | `subagent/orchestrator.py` | 收集并清空 outbox |
| `_OrchestratorContext._collect_and_inject` | `process_message()` | `ParentAgentLoop` | `subagent/orchestrator.py` | 调用父 loop 公共方法 |
| `MessageRouter.route` | `get_loop()` | `SessionManager` | `gateway/message_router.py` | 通过 `_get_sm().get_loop()` 获取 loop |
| `MessageRouter._handle_session_rotation` | `unregister_ws()` / `register_ws()` | `FrontendSink` | `gateway/message_router.py` | 旋转时更新 WebSocket 映射 |
| Gateway 永久删除 | `close_session()` | `FrontendSink` | `gateway/server.py::delete_session` | 先移除连接映射、拒绝待处理交互，再以 4004关闭已建立的被删除会话连接 |
| Gateway 永久删除与恢复 | `begin_session_delete()` / `is_session_deleting()` / `end_session_delete()` / `delete_session_runtime()` | `SessionManager` | `gateway/server.py` | 封闭删除期间的连接重建竞态，并回收 Loop、活动回复、消息队列、客户端信息和 Cron 注册 |
| `MessageRouter._dispatch_subagent_messages` | `get_snapshot()` / `chat_user_direct()` | `SubAgentOrchestrator` | `gateway/message_router.py` | 转发消息到子 Agent |
| `gateway/session_manager.replace_loop` | `_agents` | `MultiAgentLoop` | `gateway/session_manager.py` | 读取 multi loop 的 agents |
| `gateway/session_manager.replace_loop` / `rotate_session` | `session_id` | `BaseAgentLoop` | `gateway/session_manager.py` | 写入 loop 的 session_id |
| `FrontendSink` 外部 | `_ws_sinks`, `_pending_confirms`, `_confirm_session_map`, `_pending_asks`, `_ask_session_map` | `FrontendSink` | `gateway/message_router.py` | MessageRouter 解析确认和提问结果 |
| `SubAgentLoop` 外部 | `_outbox` | `SubAgentLoop` | `subagent/orchestrator.py` | orchestrator 读取子 agent outbox |
| `SubAgentLoop` 外部 | `_history` | `SubAgentLoop` | `subagent/orchestrator.py` | orchestrator 读取子 agent history |
| `cron_tools` 模块函数 | `_lock`, `_tasks` | `CronRouter` | `component/extools/cron_tools.py` | 直接访问 CronRouter 内部字段 |
| `cron_tools` 模块函数 | `_timer` | `_CronTask` | `component/extools/cron_tools.py` | 直接访问任务内部 timer |
| `diagram.py` / `mermaid_tools.py` / `docgen_tools.py` / `web_browser.py` | `_ctx` | `Sandbox` | `component/extools/*.py` | 直接访问 Sandbox 的 `_ctx` 获取 agentspace |
| 全局 `Application.current()` | `session_manager`, `frontend_sink`, `subagent_orchestrator`, `approval_mode_store`, `approval_backend_manager` | `Application` | 多处 | 各模块通过单例访问子系统 |
| 审批模式公共函数 | `get_mode()` / `set_mode()` / `reset_all_non_manual_modes()` | `ApprovalModeStore` | `component/approval/handsfree.py` | 保持公共审批 API稳定，统一委托 Application持有的 Store恢复、更新和显式重置模式 |
| Gateway主会话生命周期 | `initialize_session()` / `forget_session()` | `ApprovalModeStore` | `gateway/session_manager.py` | 新建普通/派生/随意聊聊主会话时初始化手动模式；永久删除成功后清理缓存，不复制来源模式 |
| Gateway / Agent Loop 会话元数据入口 | `session_metadata_service` | `Application` | `gateway/server.py`、`entry/base_agent_loop.py`、`entry/session_manager.py`、`entry/multi_agent_loop.py`、`entry/colloquy_loop.py` | 标题、标签、摘要及延续摘要保障统一经全局元数据服务，Loop 不再自行选择元数据客户端 |
| 动态空间管理工具与管理弹窗 | `add_dynamic_space()` / `update_dynamic_space()` / `remove_dynamic_space()` / `normalize_dynamic_space_path()` | `Sandbox` | `component/tools/sandbox_spaces.py`、`gateway/server.py` | Agent 工具经 critical 审批；用户命令菜单管理弹窗经 REST 直接修改，均复用 Sandbox 校验 |
| 动态空间 Prompt 构建器 | `list_dynamic_spaces_with_availability()` | `Sandbox` | `system/prompt.py` | 生成结构化动态命名空间系统提示词块 |
| Gateway Agentspace SSE | `shutdown_event` | `Application` | `gateway/server.py::agentspace_events` | 独立 Agentspace 编辑器通过共享进程关闭信号主动结束 SSE，避免阻塞 uvicorn 优雅关闭 |
| Gateway聊天 WebSocket Agentspace桥接 | `subscribe_events()` / `unsubscribe_events()` | `AgentspaceService` | `gateway/server.py::ws_chat`、`gateway/agentspace_event_bridge.py` | 每条聊天连接订阅一次 EventHub，发送初始 `resync/locks/watcher_error`，积压折叠为 `resync`，断线时取消 task并注销；自动旋转复用物理连接与订阅 |
| Gateway History REST | `get_session_history_skeleton()` / `get_session_history_page()` / `get_session_history_resources()` | `BaseAgentLoop` (via `IMainSessionLoop.loop`) | `gateway/server.py` | 主会话只读投影；子Agent虽继承实现但没有对应 Gateway 路由 |
| Gateway / 搜索 / LSP | `resolve_read()` / `namespace_bases()` | `Sandbox` | `gateway/server.py`、`system/search_engine.py`、`system/lsp.py` | 复用唯一 Sandbox 的动态映射与有效 base |

> 注：子类对父类 protected 字段的 `self._x` 访问（如 `ParentAgentLoop` 访问 `self._history`）属于合法继承访问，不列入"外部访问"。

---

### 会话视觉资源服务

`Application` 持有 `SessionVisualResourceService`，Gateway 的视觉入口、会话 status REST、`component/tools/filesystem.py` 的视觉源 `Read` 错误转换以及根目录 `custom_hooks/session_meta_hook.py` 均通过其公开接口读取状态。该服务只解析源目录 `.meta` 一次，不持久化视觉状态，不访问目标目录 `.meta`；新增纯数据模型位于 `entity/puretype/session_visual.py`。



`BaseAgentLoop` 新增 `_main_session_activity` 与 `_main_session_activity_revision`，并提供 `ensure_main_session_activity()`、`set_main_session_activity_phase()`、`get_main_session_activity()`、`finish_main_session_activity()`、`is_active()`。`SessionMessageQueue`、`ParentAgentLoop`、`MultiAgentLoop`、`MultiAgentWorker`、`StreamConsumer` 和 `ToolExecutor` 只通过这些生命周期入口更新活动状态。Gateway 读取快照并返回给前端，前端不依赖新的 WebSocket 活动事件。

### Pydantic 数据模型

以下类继承 `pydantic.BaseModel`，属于纯数据结构或带轻量验证的响应模型：

| 类 | 定义文件 | 继承 | 说明 |
|---|---|---|---|
| `SessionHistorySkeletonRow` / `SessionHistorySkeletonResponse` | `entity/puretype/session.py` | `BaseModel` | 前端全历史骨架及后缀响应，不含正文或富媒体 |
| `SessionHistoryContentRow` / `SessionHistoryPageResponse` | `entity/puretype/session.py` | `BaseModel` | 按 History 索引范围返回的完整前端投影行 |
| `SessionHistoryImageResource` / `SessionHistoryDownloadResource` / `SessionHistoryResourcesResponse` | `entity/puretype/session.py` | `BaseModel` | 完整 History 的图片与下载资源索引 |
| `SessionTerminationResult` | `entity/puretype/session.py` | `BaseModel` | 会话终结结果；元数据失败通过 `metadata_warnings`返回但不改变归档成功 |
| `MetadataProfileUpdateRequest` / `MetadataProfileState` / `MetadataProfileMutationResponse` | `entity/puretype/metadata.py` | `BaseModel` | 全局元数据 Profile REST 请求、权威状态与变更响应 |
| `SessionApprovalModeState` | `entity/puretype/approval.py` | `BaseModel` | easysave类型保留的会话审批模式根对象，只含 `ApprovalMode`；文件版本由 ES key、类型稳定性由 typeref stable type token管理 |
| `InboxMessage` | `entry/base_agent_loop.py` | `BaseModel` | 收件箱消息基类，含 `to_text()` |
| `UserMessage` | `entry/base_agent_loop.py` | `InboxMessage` | 用户消息 |
| `ApprovalDecisionMessage` | `entry/base_agent_loop.py` | `InboxMessage` | 审批决定消息（当前未使用） |
| `CronResultMessage` | `entry/base_agent_loop.py` | `InboxMessage` | Cron 任务结果消息 |
| `ContextLimitMessage` | `entry/base_agent_loop.py` | `InboxMessage` | 上下文超限消息 |
| `InterruptMessage` | `entry/base_agent_loop.py` | `InboxMessage` | 中断消息 |
| `AgentResponse` | `entry/multi_agent_worker.py` | `BaseModel` | 多 Agent 模式下单 Agent 的解析后响应 |
| `WorkerResult` | `entry/multi_agent_worker.py` | `BaseModel` | Worker 执行结果，含 DSL 路由元数据 |
| `ShellInfo` | `entity/puretype/shell.py` | `BaseModel` | Shell会话元数据快照，`termination` 区分 natural/forced/error，`exit_code` 仅为进程退出码 |
| `ShellOutputSlice` | `entity/puretype/shell.py` | `BaseModel` | 规范化输出的绝对字符位置切片 |
| `ProcessLineStreamResult` | `entity/puretype/runtime.py` | `BaseModel` | 逐行消费子进程输出后的退出码、stderr、截断与行数摘要 |
| `ClientDiagnostic` / `ClientDiagnosticKind` / `ClientDiagnosticPhase` | `entity/puretype/ws.py` | `BaseModel` / `Enum` | 会话预检与 History关键请求超时的脱敏传输诊断；只写 Gateway日志，不进入 History |
| `HistoryRowLink` | `entity/puretype/ws.py` | `BaseModel` | WebSocket实时行 ID到正典 History投影行 ID的非持久化关联 |
| `DynamicSandboxSpace` | `entity/puretype/sandbox.py` | `BaseModel` | 单个全局动态沙盒空间的名称、绝对路径、用途描述和工具层只读标志 |
| `DynamicSandboxSpaceData` | `entity/puretype/sandbox.py` | `BaseModel` | `dynamic_sandbox_spaces.es` v1 的持久化根对象 |
| `RefWrapper[T]` | `entity/gentype.py` | `BaseModel, Generic[T]` | 可变引用容器，供 loop 与 `ToolExecutor` 等组件共享可变值 |
| `LLMProfile` | `entity/puretype/llm.py` | `BaseModel` | LLM 配置；三个多模态字段为根对象内实例引用 |
| `LLMProfileData` | `entity/puretype/llm.py` | `BaseModel` | `llm_profiles.es` v2 的持久化根对象 |
| `LLMProfilePayload` | `entity/puretype/llm.py` | `BaseModel` | HTTP 扁平 Profile DTO，以名称/null 表达引用 |

---

## 关键设计变更记录

### 主聊天历史骨架、内容页与虚拟化

`History` 与 `history.es` 保持整体类型保留存储；`BaseAgentLoop` 新增三个只读投影接口，经 `entry/history_projection.py` 输出全历史骨架、按 History 索引范围的历史内容页和完整资源索引。Gateway 只向主会话暴露三个 REST，并以 `history_sync` 通知正典历史数量。前端使用 Zustand 隔离高频状态、Virtuoso 只挂载可视消息行，主聊天区 Minimap 改为逻辑映射；工具调用请求和匹配结果在只读投影层按 `tool_call_id` 聚合为一张工具调用卡片，结果可跨内容页返回，匹配结果不再产生独立视觉行；当前轮 live 行在内容页完成正典合并后再清理。

### 主聊天滚动追底协调

`useChatScrollController` 是主聊天区被动追底的唯一协调入口。实时内容提交与列表总高度变化只申请一个可取消的 `requestAnimationFrame` 任务，任务执行时读取 Virtuoso scroller 的最新 `scrollTop`、`scrollHeight` 和 `clientHeight`，并以 `scrollHeight - clientHeight` 为物理底部目标。`atBottomStateChange(false)` 仅更新观察状态，不因自动滚动再次独立创建追底任务；连续流式增长允许按有效布局帧更新底部，但同一帧内不会重复写入滚动位置。

用户滚动意图、消息高度变更、小地图拖拽、会话重置或状态离开 `following` 时取消待执行任务。显式回到底部和小地图提交继续使用独立的用户动作路径。最新流式消息超过视口时保持物理底部锚点，不切换到消息顶部，也不改变 History、Virtuoso 行顺序或消息协议。


### Memory 系统移除

`ParentAgentLoop` 中原有的 `_memory`（`MemoryManager`）和 `_memory_initialized_ids`（`set[int]`）字段已移除。`add_memory_provider()` 方法也已完全移除（不再保留空实现）。`LoopSessionManager` 中涉及 memory 的迁移逻辑已移除。记忆功能现由运行时扩展实现：`custom_tools/memory_tools/`（remember/forget 工具）+ `custom_hooks/memory_hook.py`（每轮注入上下文）。

### LLM 抽象层引入

`ParentAgentLoop._llm` 类型从具体的 `LLMClient` 变为 `BaseLLMClient`（抽象基类）。实际客户端通过 `abstract/llm/loader.py::create_llm_client()` 工厂从 `custom_llm_client/` 动态加载。内置实现：`openai_client.py`、`anthropic_client.py`。

`abstract/llm/formats.py` 提供 `to_openai_message()` 和 `messages_to_anthropic_list()` 两种 wire format 转换器，供 LLM 客户端复用。

### Application 单例

`system/application.py::Application` 作为进程级唯一单例，替代了原有的模块级全局变量。所有子系统（`LLMProfileStore`、共享 Profile 锁、`SessionMetadataService`、`SessionManager`、`FrontendSink`、`SubAgentOrchestrator`、`ApprovalBackendManager`、`CronRouter`、`ToolRegistry`）通过 `Application.current()` 访问。

### Approval 目录化

`component/approval/` 从单文件重构为目录，包含：`__init__.py`（公共接口）、`core.py`（`request_user_confirm` 统一审批入口；`ask_agent_reason` 脱手模式向 Agent 主模型提问取上下文）、`policy.py`（预设策略 `MAIN_SESSION_POLICY` / `SUB_SESSION_POLICY` 与 `needs_approval()`；数据类 `ApprovalPolicy` 定义在 `entity/puretype/approval`）、`backend.py`（`ApprovalBackend` / `LocalApprovalBackend`）、`executor.py`（`execute_with_approval`）、`allowlist.py`（白名单逻辑）、`handsfree.py`（脱手模式）。`ApprovalBackendManager` 由 `Application` 持有，管理审批后端的懒加载和生命周期。

### MessageRouter 拆分

`gateway/message_router.py::MessageRouter` 从 `gateway/server.py` 的 `ws_chat` 中拆分，负责所有 WebSocket 消息类型的分发处理。`server.py` 仅保留 WebSocket 连接生命周期管理。

### MultiAgentWorker 独立工具执行

`MultiAgentWorker` 内部创建独立的 `StreamConsumer` 和 `ToolExecutor` 实例，复用 `ParentAgentLoop` 的统一工具执行逻辑，但拥有独立的 stream_id 生成和 token 统计。

### 工具结果后处理统一

`entry/tool_post_dispatch.py::finalize_tool_result` 提取 `ToolExecutor.execute` 与 `SubAgentLoop._execute_approved_tool` 中重复的后处理：构建 `ToolCallMeta` 并注入 `_meta`、经 `ResultFieldInjector` 将消息队列写入内部 `_queued_messages`、提取后通过 `tool_result.embedded_messages` 独立推送前端，并经 `ui_event_router` 路由 UI 事件，返回可持久化的 `ToolResultMessage`。History 投影同样从内部字段提取嵌入消息；旧版 `queued_messages` 仅作兼容读取。

### 会话级消息队列（SP-4/SP-5）

`entry/session_message_queue.py::SessionMessageQueue` 由 `ParentAgentLoop` / `MultiAgentLoop`（及继承的 `ColloquyLoop`）持有。生产侧仍经 `call_soon_threadsafe` 落回事件循环；消费侧改为严格逐条 FIFO，每条前端消息保存自己的 `llm_profile_name` 并在执行前重新解析。当前工具轮期间到达的用户消息不再由 `drain_injected` 移出，而是在当前轮结束后依次执行。gateway 在 loop 消亡时调 `stop()`；`replace_loop` 场景用 `mark_stopped()` 标记停止而不 cancel。

### LLM Profile 根对象与名称边界

`Application` 持有唯一 `LLMProfileStore`、共享进程锁和 `SessionMetadataService`。`llm_profiles.es` 仅支持 v2 `LLMProfileData` 根对象，三个多模态分工字段、审批 Profile与全局元数据 Profile直接保存根列表中的 `LLMProfile` 实例引用；不存在 UID 或 v1 迁移。Gateway 只接收扁平名称 DTO 和单 Profile CRUD。主会话活动配置以名称指针持久化，每条前端消息只传 `llm_profile_name`；`IMainSessionLoop.set_profile()` 由 Parent/Multi 实现。`/regenerate` 请求明确接收 `llm_profile_name` 并在生成前更新活动 Profile；`/resume` 仅从当前历史恢复工具链，不接收、不更新 Profile，使用 `ParentAgentLoop` 当前已持有的活动 Profile。

### 模型配置分页与会话待用选择

新增只读 HTTP DTO `SessionLlmProfileState`（`entity/puretype/llm.py`，纯字段 BaseModel），通过 `GET /api/sessions/{id}/llm-profile` 返回会话持久化名称及既有全局最近使用回退、名称可用性。Gateway 在 Application 已有 `profile_lock` 内读取无状态 `SessionStore`；不创建 Loop、不新增生命周期对象、不写名称指针。响应不是正在执行的客户端快照。

前端 `useLlmProfiles(sessionId)` 组合 `useSessionLlmSelection`，将浏览器待用名称按主会话隔离。显式本地选择优先，无本地覆盖时读取服务端；每条主会话消息/重新生成仍独立捕获名称，resume不提交本地选择。模型抽屉仅管理定义和全局引用，唯一会话选择入口为顶部栏的独立浮层菜单。`useLlmProfileEditor` 独立管理内存草稿，切分页不重建草稿；没有新增 Agent Loop 字段或 protected 访问。

### 全局元数据 Profile 与延续摘要保障

`SessionMetadataService`是标题、标签和摘要生成的唯一业务入口。它优先使用 `LLMProfileData.metadata_profile`；仅在全局引用为空时通过 `SessionStore.read_active_profile_name(session_id)`按目标会话回退，并对选定 Profile执行浅拷贝形成单次调用快照。明确配置但无效或调用失败时禁止静默回退。手动终结中的摘要和标签为 best-effort，失败通过 `SessionTerminationResult.metadata_warnings`返回但仍归档；分支、合并与自动超限旋转必须先取得摘要。自动旋转在摘要或延续初始化失败时保持旧会话 active、保留触发消息并追加对 LLM 不可见的系统状态，成功初始化延续 History后才归档旧会话。

### 多模态能力探测内化

原探针工具已内化为 `system/modality_capability.py` 的系统自动行为：需要给活跃模型传递多模态块时先查 easysave 缓存（`modality_capability_cache.es`，按 model+base_url 联合索引、六项能力齐全才命中），未探测则伪装 Read 工具调用按 模态 × 消息路径（tool/user）六路并发探测；400 类错误及客户端明确的 `UnsupportedModalityError` 判为对应模态不支持，网络/认证/超时等非模态错误上抛不写缓存。`build_modality_prompt_block()` 每轮生成 system prompt 注入块；活跃模型不支持某模态时经 `forward_modality_to_ref_profile()` 转发到 profile 引用的其他模型。

### Agentspace 编辑器业务服务与回复轮次文件锁

`Application` 新增唯一 `AgentspaceService`。该服务把原先位于 Gateway 的全局布尔锁和直接文件操作替换为版本化 CRUD、`AgentspaceLockRegistry`、`AgentspaceOperationGate`、事务垃圾桶、`watchdog` watcher 与 `AgentspaceEventHub`。Gateway负责 typed HTTP及两种传输适配：独立 Agentspace 编辑器使用 SSE；聊天页会话视觉复用各自已有会话 WebSocket的 typed `agentspace_event`，每条连接订阅一次并在断线时注销，事件积压折叠为 `resync`。

`ToolContext` 携带必填 `round_id`。主Agent、参与Agent、子Agent与临时Agent在各自完整回复开始时创建 round，并在 History/事件/metrics 收尾后的 `finally` 幂等释放。内置文件、Shell 与 Python 工具只登记明确 `ws:` 路径；`Delete` 的永久删除和审批语义不变。用户从 Agentspace 编辑器删除时独立进入 `ws:.trash/`。

### MCP schema 规范化

`abstract/mcp/schema.py::normalize_mcp_input_schema()` 是 MCP 工具定义进入 LLM provider 前的独立兼容层。`abstract/mcp/client.py` 的工具发现和 sampling 路径共用该规范化入口，按 JSON Schema 结构位置递归处理映射、数组、组合分支、定义和 `additionalProperties`，避免业务参数名 `properties` 被误判为 schema 结构。异常值通过路径化诊断降级为 provider 可接受的形式；该过程只复制和调整 LLM-facing schema，不修改 MCP `tools/call` 的原始参数，也不新增 Agent Loop 字段或 protected 字段。

### LLM Profile 转发引用限制移除

`LLMProfileStore._validate_root()` 移除了自引用检查（`reference is profile`）与循环引用 DFS 检测（`visiting`/`visited` 集合）。Profile 间多模态分工字段（`vision_image_profile`/`audio_profile`/`vision_video_profile`）现允许自引用和循环引用。转发运行时 `forward_modality_to_ref_profile()` 为单跳机制，不递归触发转发，循环/自引用不会产生无限递归。保留的校验：引用必须为 `LLMProfile` 类型且在根列表内。前端 `LlmProfileDrawer.tsx` 同步移除三个多模态分工下拉框对当前编辑项的过滤。

### 子进程执行层抽取为 SubprocessRunner

`Sandbox` 原有的子进程执行逻辑（`run()`、`kill_active()`、`_kill_proc_tree()`、`_active_procs`/`_procs_lock` 登记表）迁移至 `system/subprocess_utils.py::SubprocessRunner`。`Application` 持有其全局单例（`_subprocess_runner`），在 `init()` 中创建并注入 `Sandbox(ctx, runner)`。`Sandbox` 保留命名空间校验与 cwd 解析层，`run()`/`kill_active()` 变为薄委托，并提供 `async run_async()` 与 `async run_async_line_processor()` 委托。`SubprocessRunner` 提供同步 `run()`、真异步 `run_async()`（`asyncio.create_subprocess_exec` + `wait_for(communicate())`）及逐行消费 `run_async_line_processor()`；后者供 `SearchFiles`/`Grep` 在达到结果上限时终止进程树并限制 stderr 缓冲。取消语义为自清理（杀树+限量 wait+re-raise）+ `kill_active` 兜底双保险。异步入口超时抛 `subprocess.TimeoutExpired`，取消 re-raise `CancelledError`（保 `ToolInterrupted("dispatch")` 语义）。`Sandbox.__init__` 的 `runner` 参数仍为可选（默认 `None`），委托方法可惰性获取 `Application.current().subprocess_runner`；业务运行时的临时 `Sandbox(...)` 构造已在全局动态空间改造中收敛到 `Application.sandbox`，保证动态注册表只有一个内存真相源。

根因：`RunCommand`/`RunPython`/`InstallPackage` 三工具注册 `is_async=True` 但内部调用同步阻塞子进程 API（`proc.communicate()`），被直接 await 在事件循环上冻结整个 loop——agent 用 run 系列工具执行 curl 打自己的动态端点时形成自死锁（uvicorn 无法处理请求直至 `tool_timeout`）。真异步化后子进程等待为协程挂起，事件循环保持响应。

### `soul_file` 移入 LLMProfile 与 `yolo` 升级为三态审批模式

两项全局配置从 `config.py`/CLI/`RuntimeContext` 移除：

1. **`soul_file`** 从 `RuntimeContext.soul_file` 迁移到 `LLMProfile.soul_file` 字段（每 Profile 独立，通过 `llm_profiles.es` 持久化）。`LLMProfile` 中已有字段定义但未接线，本次完成 DTO（`LLMProfilePayload.soul_file`）、Store（`_PROFILE_FIELDS`、`to_payload`、`create_profile`、`_assign_payload`、验证）和 Prompt 构建（`system/prompt.py::build_system_prompt()` 从 `profile.soul_file` 读取）的完整接线。`run.py` 初始 SOUL 文件复制改用硬编码 `"SOUL.md"`。

2. **`yolo`** 从 `RuntimeContext.yolo` 全局配置升级为会话级三态审批模式之一。新增 `ApprovalMode(str, Enum)` 枚举（MANUAL/HANDSFREE/YOLO）定义在 `entity/puretype/approval.py`。`component/approval/handsfree.py` 的 `_handsfree_sessions: dict[str, bool]` 升级为 `_approval_modes: dict[str, ApprovalMode]`，新增 `set_approval_mode()`/`get_approval_mode()`/`disable_all_non_manual_modes()`，保留旧函数（`set_handsfree_mode`/`is_handsfree_mode`/`disable_all_handsfree_modes`）作为兼容包装。`component/approval/policy.py::needs_approval()` 参数从 `handsfree: bool` 改为 `approval_mode: ApprovalMode`。`executor.py`、`subagent/loop.py` 的 YOLO 检查从 `get_runtime_context().yolo` 改为 `get_approval_mode(sid) == ApprovalMode.YOLO`。WS 协议中 `Message` 新增 `approval_mode` 字段（`handsfree_mode` 保留向后兼容）。前端 `useSessionStore` 新增 `approvalMode` 状态，`Header.tsx` 升级为三态审批模式选择器。

### 审批模式按主会话持久化

会话级三态审批模式从 `component/approval/handsfree.py` 的模块级字典迁移到 Application持有的唯一 `ApprovalModeStore`。Store 以业务 `RLock` 保护缓存与“先更新内存、后尽力保存”的顺序，按主会话惰性加载 `approval_mode.es` 的 easysave `v1` key；`SessionApprovalModeState` 直接交给 `save()`，通过 `entity/typeref.py` 中的 `v1::SessionApprovalModeState` stable type token重建，禁止 `.model_dump()` 降级。easysave负责路径锁、前置 `.bak`、同目录临时文件、`fsync`与原子替换；写入失败只记录日志且不回滚内存。旧会话缺文件以及损坏、缺 key或类型错误均回退手动模式。

普通新会话、自动延续、单源分支、多父合并和首次创建的“随意聊聊”都经 Gateway `SessionManager` 统一初始化为手动模式，不复制来源模式；归档保留状态，永久删除会话目录后清理 Store缓存。审批 Profile清空、删除或配置失效不再调用模式批量重置，也不通过 Profile广播携带 `handsfree_mode=false`；已恢复的脱手模式保持不变，实际审批后端不可用时继续按既有失败路径拒绝。

### Agent 运行工具被 Shell会话取代

- `ShellManager` 使用 pywinpty 高层 `PtyProcess` 的 socket reader；通过受保护的 `PYWINPTY_BACKEND=0` 环境切换强制 ConPTY，停止时使用 `close(force=True)`，不直接依赖低层 PTY 读取/关闭 API。
- powershell/pwsh 使用 `-NoProfile`，并在启动阶段优先移除 PSReadLine、失败时回退为关闭预测；第一阶段不提供 PowerShell 行编辑能力。单行输入使用单独 CR；未换行提示符通过原始输出活动版本触发静默提交，规范化字符 offset 只在实际提交时增长。

### 全局动态沙盒空间

动态沙盒空间从会话和 LLM Profile 生命周期中独立，使用 workspace 根下的 `dynamic_sandbox_spaces.es` v1 根对象持久化，由 Application 持有的唯一 Sandbox 加载和修改。仅 fast 模式启用，但所有 Agent 共享解析能力；普通模式和多Agent模式主Agent通过按需加载的 `sandbox` 工具集执行 critical 增删，随意聊聊会话有意不能管理。Sandbox 统一提供动态前缀识别、目录可用性、工具层读写权限和 Prompt 快照；运行时临时 Sandbox 构造已收敛到 Application 单例。

### 主会话中断生命周期收敛

主会话的活动任务从长期 `SessionMessageQueue` consumer 收敛为已经取得 `_process_lock` 的单次回复 task。队列 consumer 为每批消息创建 child 并持续承载 FIFO；用户中断只设置该轮取消事件并等待/取消活动回复，不销毁 consumer。普通模式、多Agent模式及恢复/重新生成入口均在外层轮次开始时初始化控制事件，并在同轮 finally 清除后再注销 task。

`StreamConsumer` 通过共享取消事件自行终止当前 `__anext__()`，并作为异步迭代器唯一关闭者；外部不再并发 `aclose()`。工具 handler task 的取消使用有限清理窗口，超时 task 由 `ToolExecutor._cancel_cleanup_tasks` 强引用并观察。前端对 `history_sync.processing` 的 true/false 都按服务端权威值覆盖本地状态。

### 主会话永久删除与连接失效收敛

永久删除由 Gateway 分层执行：`SessionManager` 的删除中集合先封闭新连接与 Loop重建竞态，`FrontendSink.close_session()`从连接映射移除会话并以 4004关闭已建立连接，`delete_session_runtime()`再中断活动回复、停止长期消息队列、清除客户端信息并注销 Cron，最后由 `gateway.chat.SessionManager.remove()`统一删除索引与会话目录。握手前无法可靠向浏览器传递私有关闭码，因此前端通过 `/api/sessions/{id}/status` 的删除感知 `exists`字段二次确认；显式恢复已经删除或删除中的 ID不再创建随机新会话。

### 临时Agent继承活动 LLM Profile与工具权限收敛

`RunTaskAgent` 通过公开 `ToolContext.llm_profile` 取得调用发生时父主会话的活动 Profile，并由 `LLMProfileStore.snapshot_profile()` 在共享锁内验证根对象身份后创建非持久化深快照。快照完整保留客户端、采样、多模态分工等配置；临时Agent不再从 `SubRuntimeContext` 空默认值构造 `custom_llm_client.`，也不再暴露单次 temperature参数。普通角色子Agent不再使用注册配置，而是通过 `subagent/profile.py::CharacterProfileResolver` 动态读取角色档案；`AgentConfig` 仅作为 `AgentProfile` 的运行时适配对象。`TaskAgent` 仍只使用活动 LLM Profile 的非持久化快照。

`TaskAgentLoop` 不新增字段。它复用 `SubAgentLoop._allowed_tool_names` 与会话级已加载工具集，并在模型定义生成和执行期统一要求“已加载工具集 ∩ `TASKAGENT` 可用范围 ∩ `safe` 危险等级”。允许工具直接执行，越权调用直接返回失败工具结果，不进入父Agent或审批模型流程。`LoadToolset` 只扩展已加载集合，不扩大权限交集。

### 主聊天实时行到正典 History 行交接

实时行到正典 History 行的交接继续以明确 `live_id → history_row_id` 关联为准；滚动位置不参与消息身份或交接判断。工具调用请求和结果通过同一工具卡片关联，滚动控制器只负责视口物理位置，不改变正典交接语义。

`entry/stream_history_link.py` 统一发送 `stream_id/history_index` 与 `live_history_links`。`ParentAgentLoop`（含继承的 `ColloquyLoop`）和 `MultiAgentWorker`只使用实际 `History.add_message()`返回索引构造关联；`MultiAgentLoop._cascade()`继续负责最终 assistant 行。工具请求和匹配结果使用统一 `tool-card:<tool_call_id>` live ID，指向请求锚定的 `history:<index>:tool:<tool_index>` 工具调用卡片行；History 持久化顺序不变。`FrontendSink`必须透传 `tool_call_id`，持久化 system 状态携带 `index/is_system_status`。缺失、重复、孤立或非法倒序的 `tool_call_id` 不猜配：后端记录 warning，前端保留缺失结果卡片或独立降级行。子Agent与临时Agent的独立 History不映射到主会话。

前端 `chatRuntimeStore`持有通用实时行映射。user/assistant/tool/system 行只有在 skeleton 已存在目标行并完成正典交接后才从实时 footer移除；未映射、目标未出现或History请求失败的行保留并产生诊断。History数量减少表示结构代际替换，旧映射和旧实时尾部统一失效。