# Agent Loop 类关系图

> **迁移前基线说明**：本文件的继承关系图、`## 字段归属（已确认）` 表中的 `_toolsets` 行，以及 `### 工具注册表生命周期迁移（S10）`、`### 工具显式注册与发现生命周期迁移（S20）` 两节，记录的是对象工具化迁移之前的实现。自 2026-10-15 起，唯一权威的工具对象与四阶段执行契约见文末 `### 对象工具与四阶段执行迁移（2026-10-15，权威）`；`ToolEntry`/`ToolsetEntry` 元数据镜像、`register_tools(registry, ui_events)` 函数注册协议、`registry.register()` 顶层注册与 `UIEventRouter` 均已退役。本文件其余历史章节保持原文，不因本次迁移改写。

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
        +reset_context_tokens()
        +get_session_messages()
        +get_session_history_skeleton()
        +get_session_history_page()
        +get_session_history_resources()
        +edit_session_message()
        +delete_session_messages()
        +delete_single_message()
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

    class History {
        +remove_message_with_pairing()
        +replace_range()
    }

    class SessionMessageEditResult {
        +updated
        +session_id
        +index
        +role
        +content
        +visible_characters
        +error
    }

    class SessionMessageDeletionResult {
        +deleted
        +session_id
        +removed_indices
        +remaining_count
        +history_count
        +token_usage
        +context_tokens
        +error
    }

    class SessionRegenerateResult {
        +regenerate
        +session_id
        +last_user_content
        +remaining_count
        +message_index
        +message_suffix
        +dynamic_message_suffix
        +visible_characters
        +response_characters
        +error
    }

    class SessionToolResources {
        +session_id
        +task_progress
        +clipboard_display
        +dynamic_endpoints
    }

    class SessionRuntimeResourceTransferResult {
        +old_sid
        +new_sid
        +tool_resources_error
    }

    class SubAgentLaunchResult {
        +success
        +session_id
        +error
    }

    class SubAgentChatResult {
        +success
        +session_id
        +feedback
        +note
        +error
    }

    class SubAgentApprovalResult {
        +success
        +session_id
        +processed
        +results
        +feedback
        +error
    }

    class SubAgentStopResult {
        +success
        +session_id
        +session_path
        +error
    }

    class SubAgentSnapshot {
        +session_id
        +name
        +status
        +feedback
        +pending_approvals
        +interactive
    }

    class SubAgentSnapshotResponse {
        +session_id
        +subagents
    }

    class SubAgentUpdate {
        +session_id
        +name
        +status
        +feedback
        +pending_approvals
        +removed
        +interactive
    }

    class SessionMergeResult {
        +merged
        +session_id
        +sources
        +error
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
        #_processing
        #_process_lock
        #_event_loop
        +subagent_orchestrator
        #_session_manager
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
        #_send_stream_event(StreamEvent)
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
        +get_effective_visible_tool_names()
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
        #_subagent_names
        #_starting
        #_startup_tasks
        #_waiter_tasks
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
        +get_toolchain_summary_profile()
        +set_toolchain_summary_profile()
        +to_payload()
    }

    class SessionMetadataService {
        #_runtime_context
        #_llm_profile_store
        #_profile_lock
        #_session_store
        +get_state()
        +select_profile()
        +get_toolchain_summary_state()
        +select_toolchain_summary_profile()
        +generate_title()
        +generate_tags()
        +generate_summary()
        +regenerate_summary()
        +ensure_summary()
        +generate_tool_chain_summary()
    }

    class LLMProfileData {
        +profiles
        +approval_profile
        +metadata_profile
        +toolchain_summary_profile
        +global_vision_image_profile
        +global_audio_profile
        +global_vision_video_profile
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

    class EmptyResponseRetryClient {
        #_client
        +chat()
        +chat_stream()
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

    BaseAgentLoop --> SessionMessageEditResult : returns
    BaseAgentLoop --> SessionMessageDeletionResult : returns
    BaseAgentLoop --> SessionRegenerateResult : returns
    BaseAgentLoop --> SessionToolResources : returns
    BaseAgentLoop --> SessionMergeResult : returns
    LoopSessionManager --> SessionRuntimeResourceTransferResult : returns
    _OrchestratorContext --> SubAgentLaunchResult : returns
    _OrchestratorContext --> SubAgentChatResult : returns
    _OrchestratorContext --> SubAgentApprovalResult : returns
    _OrchestratorContext --> SubAgentStopResult : returns
    _OrchestratorContext --> SubAgentSnapshotResponse : returns
    SubAgentOrchestrator --> SubAgentLaunchResult : returns
    SubAgentOrchestrator --> SubAgentChatResult : returns
    SubAgentOrchestrator --> SubAgentApprovalResult : returns
    SubAgentOrchestrator --> SubAgentStopResult : returns
    SubAgentOrchestrator --> SubAgentSnapshotResponse : returns
    SubAgentSnapshotResponse --> SubAgentSnapshot : contains
    SubAgentSnapshot --> SubAgentFeedback : contains
    SubAgentSnapshot --> SubAgentPendingApproval : contains
    SubAgentUpdate --> SubAgentFeedback : contains
    SubAgentUpdate --> SubAgentPendingApproval : contains
    History --> SessionMessageDeletionResult : returns
    BaseAgentLoop <|-- MultiAgentLoop
    BasePrivateChatAgentLoop <|-- ParentAgentLoop
    BasePrivateChatAgentLoop <|-- SubAgentLoop
    SubAgentLoop <|-- TaskAgentLoop
    IMainSessionLoop <|.. ParentAgentLoop
    IMainSessionLoop <|.. MultiAgentLoop
    AgentSink <|-- FrontendSink
    AgentSink <|-- ParentAgentSink
    FrontendSink --> StreamDeltaEvent : constructs and sends
    FrontendSink --> StreamDoneEvent : constructs and sends
    StreamDeltaEvent --> ToolCallRequest : contains
    StreamDeltaEvent --> ToolCallDelta : contains
    StreamDoneEvent --> MessageMetrics : contains
    BaseLLMClient <|-- EmptyResponseRetryClient
    EmptyResponseRetryClient --> BaseLLMClient : decorates one provider client
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
| `_client` | `EmptyResponseRetryClient` | `BaseLLMClient` | 正式加载器创建的底层Provider客户端；计数、流式有效输出标记、待交付usage/finish均为单次调用局部状态，不新增Loop字段或外部protected访问 |
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
| `_tools` | `SubAgentLoop` | `list[dict]` | 构造期静态全量 SUBAGENT 工具 schema 清单；**仅作静态授权清单派生源**（`_allowed_tool_names`），不再作为 LLM 工具表来源（LLM 调用点动态走 `_get_tool_definitions()`） |
| `_allowed_tool_names` | `SubAgentLoop` | `set[str]` | 从构造传入 tools 派生的静态授权清单；执行期闸门使用，并在 `_execute_approved_tool` 中叠加「已加载工具集」检查；`allowed_tool_names` property 返回其副本（ShowTool 已改走动态口径） |
| `get_effective_visible_tool_names()` | `SubAgentLoop` | public method | 按动态口径（loaded ∩ scope ∩ check_fn）返回可见工具名集合，供 ShowTool 复用；TaskAgentLoop 经虚分派自动叠加 safe 过滤 |
| `llm_profile` | `SubRuntimeContext` | `LLMProfile \| None` | TaskAgent持有调用时活动 Profile的非持久化深快照；普通角色子Agent不持久化独立配置 |
| （无新增字段） | `TaskAgentLoop` | — | 全部继承 `SubAgentLoop`；覆写无系统提示词、`TASKAGENT ∩ safe` 定义/执行授权及完成即终止行为 |
| `_ws_sinks` | `FrontendSink` | `dict[str, WebSocket]` | session_id → WebSocket 映射 |
| `_pending_confirms` | `FrontendSink` | `dict[str, Future]` | 外部解析确认结果 |
| `_confirm_session_map` | `FrontendSink` | `dict[str, str]` | 外部映射确认到 session |
| `_pending_asks` | `FrontendSink` | `dict[str, Future]` | 外部解析提问结果 |
| `_ask_session_map` | `FrontendSink` | `dict[str, str]` | 外部映射提问到 session |
| `_loop` | `ParentAgentSink` | `SubAgentLoop` | 持有 SubAgentLoop 引用，访问其内部字段 |
| `feedback_event` / `_feedback_records` | `SubAgentLoop` | `asyncio.Event` / `list[SubAgentFeedbackDelivery]` | 反馈记录由子Agent公开追加与确认，编排器不再清空裸 outbox |
| `_pending_approvals` | `SubAgentLoop` | `list[PendingToolCall]` | 被 `ParentAgentSink` 读取/写入 |
| `_paused_event` | `SubAgentLoop` | `asyncio.Event` | 被 `ParentAgentSink` 读取/设置 |
| `_emit()` | `SubAgentLoop` | method | 被 `ParentAgentSink` 调用 |
| `_parent_session_id` | `SubAgentLoop` | `str` | 被 `ParentAgentSink` 读取 |
| `_loop` | `LoopSessionManager` | `ParentAgentLoop` | 大量访问 loop 的 protected 字段 |
| `_history_store_dir` | `LoopSessionManager` | `Path \| None` | 历史存储目录 |
| `_session_rotated_notify` | `LoopSessionManager` | `dict[str, str]` | session 旋转通知 |
| `_session_manager` | `_OrchestratorContext` | `SessionManager` | 只通过管理器查询真实父会话Loop，不保留启动用Loop回退 |
| `_active` / `_active_task` | `_OrchestratorContext` | `dict` | 管理已提交的 SubAgentLoop 实例及其运行任务 |
| `_starting` / `_startup_tasks` | `_OrchestratorContext` | `dict` | 登记启动中的子Agent并跟踪可取消的初始化任务；用于重复启动防护和失败回滚，不限制数量 |
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
| ~~`frontend_sink`~~ | ~~`Application`~~ | ~~`FrontendSink \| None`~~ | 已迁移为 `AsyncSystem`，经 `get_system(FrontendSink)` 取得（S09） |
| `SubAgentOrchestrator` | `SubAgentOrchestrator` | `AsyncSystem` | 由 framework 注册表持有，经 `get_system(SubAgentOrchestrator)` 取得 |
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
| `ParentAgentSink.emit_stream_done` | `get_system(FrontendSink)` | `Application` | `entry/agent_sink.py` | 通过 `Application.current().get_system(FrontendSink)` 转发到父会话前端 |
| `ShowTool._visible_tool_names` | `get_effective_visible_tool_names()` | `SubAgentLoop`（TaskAgentLoop 经虚分派覆写） | `component/tools/show_tool.py` | 子Agent可见性查询走公开方法，动态口径（loaded ∩ scope ∩ check_fn） |
| `LoopSessionManager.initialize` | `_session_store`, `_history`, `session_id` | `ParentAgentLoop` | `entry/session_manager.py` | 初始化时读写 loop 内部 |
| `LoopSessionManager.is_context_over_limit` | `_last_prompt_tokens`, `app.runtime_context` | `ParentAgentLoop` | `entry/session_manager.py` | 读取 loop 内部 token 和配置 |
| `LoopSessionManager.rotate_session_for_continuation` | `_remove_last_user_message`, `_append`, `_history`, `_last_prompt_tokens`, `_session_store`, `_session_manager`, `_llm`, `load_history`, `persist_history` | `ParentAgentLoop` | `entry/session_manager.py` | 旋转时大量调用 loop 内部 |
| `LoopSessionManager._terminate_session` | `_session_manager`, `_session_store`, `_history`, `_llm`, `get_full_history` | `ParentAgentLoop` | `entry/session_manager.py` | 终结会话时大量调用 loop 内部 |
| `TaskAgentLoop`（模块级 import） | `_interrupted_result()` | `entry/tool_executor.py`（模块级函数） | `subagent/taskloop.py` | 跨模块导入 protected 函数，构造中断/异常时的工具结果占位 |
| `_OrchestratorContext._drain_outbox` | `get_pending_feedback()` / `mark_feedback_delivered()` | `SubAgentLoop` | 仅通过反馈公开接口确认一次性交付 |
| `_OrchestratorContext.get_snapshot` | `_history.messages`, `pending_approvals_info` | `SubAgentLoop` | `subagent/orchestrator.py` | 读取子 agent 历史 |
| `_OrchestratorContext._start_subagent` | `_history` | `SubAgentLoop` | `subagent/orchestrator.py` | 加载历史时覆盖 `_history` |
| `_OrchestratorContext._flush_subagent_message` | `get_pending_feedback()` / `mark_feedback_delivered()` | `SubAgentLoop` | 正常运行反馈投递；关闭时改走SessionManager专用交接 |
| `_OrchestratorContext._collect_and_inject` | `process_message()` | `ParentAgentLoop` | `subagent/orchestrator.py` | 调用父 loop 公共方法 |
| `MessageRouter.route` | `get_loop()` | `SessionManager` | `gateway/message_router.py` | 通过 `_get_sm().get_loop()` 获取 loop |
| `MessageRouter._handle_session_rotation` | `unregister_ws()` / `register_ws()` | `FrontendSink` | `gateway/message_router.py` | 旋转时更新 WebSocket 映射 |
| Gateway 永久删除 | `close_session()` | `FrontendSink` | `gateway/server.py::delete_session` | 先移除连接映射、拒绝待处理交互，再以 4004关闭已建立的被删除会话连接 |
| Gateway 永久删除与恢复 | `begin_session_delete()` / `is_session_deleting()` / `end_session_delete()` / `delete_session_runtime()` | `SessionManager` | `gateway/server.py` | 封闭删除期间的连接重建竞态，并回收 Loop、活动回复、消息队列、客户端信息和 Cron 注册 |
| `MessageRouter._dispatch_subagent_messages` | `get_snapshot()` / `chat_user_direct()` | `SubAgentOrchestrator` | `gateway/message_router.py` | 转发消息到子 Agent |
| `gateway/session_manager.replace_loop` | `_agents` | `MultiAgentLoop` | `gateway/session_manager.py` | 读取 multi loop 的 agents |
| `gateway/session_manager.replace_loop` / `rotate_session` | `session_id` | `BaseAgentLoop` | `gateway/session_manager.py` | 写入 loop 的 session_id |
| `FrontendSink` 外部 | `_ws_sinks`, `_pending_confirms`, `_confirm_session_map`, `_pending_asks`, `_ask_session_map` | `FrontendSink` | `gateway/message_router.py` | MessageRouter 解析确认和提问结果 |
| `SubAgentLoop` 外部 | `get_pending_feedback()` / `mark_feedback_delivered()` | `SubAgentLoop` | `subagent/orchestrator.py` | 编排器只通过公开反馈记录接口交接 |
| `SubAgentLoop` 外部 | `_history` | `SubAgentLoop` | `subagent/orchestrator.py` | orchestrator 读取子 agent history |
| `cron_tools` 模块函数 | `_lock`, `_tasks` | `CronRouter` | `component/extools/cron_tools.py` | 直接访问 CronRouter 内部字段 |
| `cron_tools` 模块函数 | `_timer` | `_CronTask` | `component/extools/cron_tools.py` | 直接访问任务内部 timer |
| `diagram.py` / `mermaid_tools.py` / `docgen_tools.py` / `web_browser.py` | `_ctx` | `Sandbox` | `component/extools/*.py` | 直接访问 Sandbox 的 `_ctx` 获取 agentspace |
| 全局 `Application.current()` | `session_manager`, `get_system(FrontendSink)`, `get_system(SubAgentOrchestrator)`, `get_system(ApprovalSystem)` | `Application` | 多处 | 各模块通过单例访问子系统；编排器、frontend_sink与审批均迁移为 `get_system(T)` |
| 审批模式公共函数 | `get_mode()` / `set_mode()` / `reset_all_non_manual_modes()` | `ApprovalModeStore` | `component/approval/handsfree.py` | 保持公共审批 API稳定，统一委托 Application持有的 Store恢复、更新和显式重置模式 |
| Gateway主会话生命周期 | `initialize_session()` / `forget_session()` | `ApprovalModeStore` | `gateway/session_manager.py` | 新建普通/派生/随意聊聊主会话时初始化手动模式；永久删除成功后清理缓存，不复制来源模式 |
| Gateway / Agent Loop 会话元数据入口 | `session_metadata_service` | `Application` | `gateway/server.py`、`gateway/message_router.py`（首条用户消息经 `maybe_generate_first_title` 触发一次性 LLM 标题生成+截取回退，SessionManager/FrontendSink 由服务动态取得）、`entry/base_agent_loop.py`、`entry/session_manager.py`、`entry/multi_agent_loop.py`、`entry/colloquy_loop.py` | 标题、标签、摘要及延续摘要保障统一经全局元数据服务，Loop 不再自行选择元数据客户端 |
| 动态空间管理工具与管理弹窗 | `add_dynamic_space()` / `update_dynamic_space()` / `remove_dynamic_space()` / `normalize_dynamic_space_path()` | `Sandbox` | `component/tools/sandbox_spaces.py`、`gateway/server.py` | Agent 工具经 critical 审批；用户命令菜单管理弹窗经 REST 直接修改，均复用 Sandbox 校验 |
| 动态空间 Prompt 构建器 | `list_dynamic_spaces_with_availability()` | `Sandbox` | `system/prompt.py` | 生成结构化动态命名空间系统提示词块 |
| Gateway Agentspace SSE | `RuntimeSystem.shutdown_event` | `RuntimeSystem` | `gateway/server.py::agentspace_events` | 独立 Agentspace 编辑器通过共享进程关闭信号主动结束 SSE，等待任务经 `GatewaySystem.task_owner` 登记，避免阻塞 uvicorn 优雅关闭 |
| Gateway聊天 WebSocket Agentspace桥接 | `subscribe_events()` / `unsubscribe_events()` | `AgentspaceService` | `gateway/server.py::ws_chat`、`gateway/agentspace_event_bridge.py` | 每条聊天连接订阅一次 EventHub，发送初始 `resync/locks/watcher_error`，积压折叠为 `resync`（日志按时间窗限流携带累计 dropped），断线时取消 task并注销；自动旋转复用物理连接与订阅；单事件发送超时抛 `AgentspaceSendTimeout`，回调经 `TaskOwner.mark_expected_failure` 标记例常驱逐后 1011 断连 |
| Gateway History REST | `get_session_history_skeleton()` / `get_session_history_page()` / `get_session_history_resources()` | `BaseAgentLoop` (via `IMainSessionLoop.loop`) | `gateway/server.py` | 主会话只读投影；子Agent虽继承实现但没有对应 Gateway 路由 |
| Gateway / 搜索 / LSP | `resolve_read()` / `namespace_bases()` | `Sandbox` | `gateway/server.py`、`system/search_engine.py`、`system/lsp.py` | 复用唯一 Sandbox 的动态映射与有效 base |

> 注：子类对父类 protected 字段的 `self._x` 访问（如 `ParentAgentLoop` 访问 `self._history`）属于合法继承访问，不列入"外部访问"。

---

### 会话视觉资源服务

`Application` 持有 `SessionVisualResourceService`；Gateway 的视觉入口、会话 status REST、`component/tools/filesystem.py` 的视觉源 `Read` 错误转换及扩展调用方通过其公开接口读取状态。该服务只解析源目录 `.meta` 一次，不持久化视觉状态，不访问目标目录 `.meta`；新增纯数据模型位于 `entity/puretype/session_visual.py`。



`BaseAgentLoop` 新增 `_main_session_activity` 与 `_main_session_activity_revision`，并提供 `ensure_main_session_activity()`、`set_main_session_activity_phase()`、`get_main_session_activity()`、`finish_main_session_activity()`、`is_active()`。`SessionMessageQueue`、`ParentAgentLoop`、`MultiAgentLoop`、`MultiAgentWorker`、`StreamConsumer` 和 `ToolExecutor` 只通过这些生命周期入口更新活动状态。Gateway 读取快照并返回给前端，前端不依赖新的 WebSocket 活动事件。

### Pydantic 数据模型

以下类继承 `pydantic.BaseModel`，属于纯数据结构或带轻量验证的响应模型：

| 类 | 定义文件 | 继承 | 说明 |
|---|---|---|---|
| `SessionTagsUpdateRequest` / `SessionTitleUpdateRequest` / `SessionMessageEditRequest` / `SessionRegenerateRequest` / `SessionMergeRequest` | `entity/puretype/session.py` | `BaseModel` | Gateway 会话 REST 入站请求模型；HTTP 边界解析后通过属性访问，保持既有默认值和错误语义 | 
| `ConfirmResponseRequest` / `AskResponseRequest` | `entity/puretype/ws.py` | `BaseModel` | Gateway HTTP 交互响应请求模型；分别承载 confirm 和 ask 的稳定字段 | 
| `DynamicEndpointRequest` | `entity/puretype/extools.py` | `BaseModel` | 动态端点 HTTP 入站请求；content 使用稳定多模态 block 联合类型 | 
| `AgentspaceOperationRequest` | `entity/puretype/agentspace.py` | `BaseModel` | Agentspace 垃圾桶恢复、永久删除和清空请求中的 operation_id | 
| `TextContentBlock` / `ImageContentBlock` / `AudioContentBlock` / `VideoContentBlock` | `entity/puretype/_base.py` | `BaseModel` | Gateway 入站多模态 content block；未知扩展字段保持兼容 | 
| `SessionHistorySkeletonRow` / `SessionHistorySkeletonResponse` | `entity/puretype/session.py` | `BaseModel` | 前端全历史骨架及后缀响应，不含正文或富媒体 |
| `SessionHistoryContentRow` / `SessionHistoryPageResponse` | `entity/puretype/session.py` | `BaseModel` | 按 History 索引范围返回的完整前端投影行 |
| `SessionHistoryImageResource` / `SessionHistoryDownloadResource` / `SessionHistoryResourcesResponse` | `entity/puretype/session.py` | `BaseModel` | 完整 History 的图片与下载资源索引 |
| `SessionTerminationResult` | `entity/puretype/session.py` | `BaseModel` | 会话终结结果；元数据失败通过 `metadata_warnings`返回但不改变归档成功 |
| `SessionMessageEditResult` / `SessionMessageDeletionResult` / `SessionRegenerateResult` | `entity/puretype/session.py` | `BaseModel` | `BaseAgentLoop` 消息编辑、删除和重新生成前置处理的稳定结果；Gateway 通过属性访问，HTTP边界再序列化 |
| `SessionToolResources` / `SessionMergeResult` | `entity/puretype/session.py` | `BaseModel` | `BaseAgentLoop` 工具资源快照与会话合并/分支结果 |
| `SessionRuntimeResourceTransferResult` | `entity/puretype/session.py` | `BaseModel` | `LoopSessionManager` 会话旋转时运行态资源迁移的稳定结果 |
| `SubAgentLaunchResult` / `SubAgentChatResult` / `SubAgentApprovalResult` / `SubAgentStopResult` | `entity/puretype/subagent.py` | `BaseModel` | `SubAgentOrchestrator` 与 `_OrchestratorContext` 的启动、对话、审批和停止稳定结果；工具层只在边界序列化 |
| `SubAgentSnapshot` / `SubAgentSnapshotResponse` / `SubAgentUpdate` | `entity/puretype/subagent.py` | `BaseModel` | 统一子Agent快照与前端状态更新中的 `status`、`feedback`、`pending_approvals`、`interactive` 字段 |
| `MetadataProfileUpdateRequest` / `MetadataProfileState` / `MetadataProfileMutationResponse` | `entity/puretype/metadata.py` | `BaseModel` | 全局元数据 Profile REST 请求、权威状态与变更响应 |
| `ToolchainSummaryProfileUpdateRequest` / `ToolchainSummaryProfileState` / `ToolchainSummaryProfileMutationResponse` | `entity/puretype/metadata.py` | `BaseModel` | 工具链摘要 Profile REST 请求、权威状态与变更响应 |
| `ToolChainSpan` | `entity/puretype/session.py` | `BaseModel` | 可压缩工具链在 History 中的半开索引区间 [start, end) |
| `ToolChainReplacement` | `entity/puretype_after/session.py` | `BaseModel` | 消息后纯类型的非持久化替换材料：`start` / `end` 与直接引用正式消息类的 `messages: list[BaseMessage]`，供两个压缩工具共用摘要准备逻辑 |
| `ModalityProfileState` / `ModalityProfileUpdateRequest` / `ModalityProfileMutationResponse` / `ModalityProfileStates` | `entity/puretype/modality.py` | `BaseModel` | 图片、音频、视频三路全局回退 Profile 的 REST 状态、更新请求和完整状态快照 |
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
| `StreamDeltaEvent` / `StreamDoneEvent` | `entity/puretype/ws.py` | `BaseModel` | 按固定 `type` 区分的下行流式事件，`StreamEvent` 为其判别联合；必填非空会话/流标识，工具载荷和计时模型在唯一发送边界序列化 |
| `HistoryRowLink` | `entity/puretype/ws.py` | `BaseModel` | WebSocket实时行 ID到正典 History投影行 ID的非持久化关联 |
| `DynamicSandboxSpace` | `entity/puretype/sandbox.py` | `BaseModel` | 单个全局动态沙盒空间的名称、绝对路径、用途描述和工具层只读标志 |
| `DynamicSandboxSpaceData` | `entity/puretype/sandbox.py` | `BaseModel` | `dynamic_sandbox_spaces.es` v1 的持久化根对象 |
| `RefWrapper[T]` | `entity/gentype.py` | `BaseModel, Generic[T]` | 可变引用容器，供 loop 与 `ToolExecutor` 等组件共享可变值 |
| `LLMProfile` | `entity/puretype/llm.py` | `BaseModel` | LLM 配置；三个多模态字段为根对象内实例引用 |
| `LLMProfileData` | `entity/puretype/llm.py` | `BaseModel` | `llm_profiles.es` v2 的持久化根对象 |
| `LLMProfilePayload` | `entity/puretype/llm.py` | `BaseModel` | HTTP 扁平 Profile DTO，以名称/null 表达引用 |

---

## 会话变量池叶服务（2026-10-13）

`AgentspaceService`新增protected字段`_session_variables: SessionVariableService | None`，仅由其virtual_awake在取得唯一Sandbox后构造；公开只读`session_variables`属性。无新AsyncSystem、后台Owner、watcher或模块单例，Application拓扑仍为21个System。业务类位于system/session_variables.py，纯字段响应/继承材料位于entity/puretype/session_variables.py，未进入easysave或typeref。

`ReadSessionVariables`及Gateway变量REST经`get_system(AgentspaceService).session_variables.read_pool`调用共享解析；工具通过公开ToolContext.resource_session_id取得主会话归属，并经agentspace_access登记精确文件。Parent/Multi/Sub提示词只用公开构建器追加协议，不读取变量、不新增Loop protected字段；临时Agent空prompt与safe交集不变。

`terminate_and_rotate_session`和BaseAgentLoop.merge_sessions调用capture_inheritance/install_inheritance，在同步初始化scope内完整复制并复查来源/目标、写History，之后归档。安装失败按独占目录二元身份回收，文件四元身份只用于读取变动检测；取消/History/必要清理失败传播，多个失败异常组保留，提交后错误不删除已提交副本。普通子Agent旧parent_session_id不自动重绑，不把独立文件继承宣称为跨文件事务。正常永久删除不清理工作空间变量文件，History重新生成不回滚变量。上述仅源码实施与静态复核，未运行验证。

## 关键设计变更记录

### LLM空响应有界重试（2026-10-16）

`abstract/llm/loader.py::create_llm_client` 在验证插件工厂返回类型后只包装一次 `EmptyResponseRetryClient`，其继承 `BaseLLMClient`，唯一 `_client` 字段持有原Provider对象；Application经原有Loop/System间接持有两者，不新增全局对象、连接、Loop字段或跨类protected访问。装饰器不读取底层私有状态，原公共参数和返回类型不变，插件继续只负责原Provider实现。`client.py::LLMEmptyResponseError` 是非持久化RuntimeError子类，`LLM_EMPTY_RESPONSE_MAX_ATTEMPTS`集中定义并导出。

正文零长度且无工具调用的正常返回最多3次尝试；完整工具调用合法，只有工具参数增量而无正文/完整调用时失败不重播。每次使用原请求，不重跑工具/业务输入。流式reasoning保持连续展示，失败空尝试的usage/finish不作为完成；装饰层决定事件交付语义，StreamConsumer仍聚合/计时并关闭外层流，装饰器以aclosing关闭内层流，关闭失败/取消不重试。每次调用的状态局部隔离，不持久化、不修改消息类型或前端协议。

正式入口覆盖辅助模型：模态探针持续空时整次TaskGroup失败且不写能力缓存，保留既有异常组传播政策；审批不放行，元数据/转发维持失败出口。新策略与Provider/SDK重试组合的请求次数/等待边界见abstract开发文档，单调用预算不代表六路探测或账单总量。已完成源码实施与只读审阅，未运行校验、构建或应用，用户人工验收待完成。

### 消息前/后纯类型划分（2026-10-14）

保留 `entity.puretype` 作为消息前纯类型包，新增同级 `entity.puretype_after` 作为消息后纯类型包。依赖方向为 `puretype_after → messages → puretype`，后期包也可直接依赖前期包；两个时期表示类型依赖顺序，不对应 Application 生命周期阶段。前期包不得直接、间接或仅在 `TYPE_CHECKING` 下引用消息体系或后期包，消息定义层的模块级依赖不得反向导入后期包。两个包分别通过各自 `__init__.py` 显式导出，不建立统一聚合或旧入口的后期类型兼容别名。

`ToolChainSpan` 只有索引字段，继续留在 `puretype/session.py`；与它配合的 `ToolChainReplacement` 因持有正式消息实例列表迁入 `puretype_after/session.py`，直接导入 `BaseMessage`。共享压缩准备入口同步迁移导入并删除跨层 `model_rebuild`，函数签名、摘要准备与提交行为保持。已有持久化类型路径、type token、typeref 映射和存储版本均不变，后期替换材料仍不持久化；没有新增 System、运行时初始化或 Agent Loop 字段。本次已实施源码，未运行导入验证、构建或应用验收。

### 独立工具链压缩（2026-10-14）

新增 `CompressToolChains` 与现有 `CompressHistory` 分工：前者仅替换全部历史中的完整工具链，不截断轮次、不插入会话摘要，后者保持旧轮次截断及保留轮次链压缩。两个 handler 共用 `component/tools/_history_compression.py::prepare_tool_chain_replacements(messages, *, session_id, metadata_service, start_index=0)`，该入口只准备摘要及 `ToolChainReplacement`，不修改 History、不查询 Application；唯一摘要服务仍由 handler 的 `ToolContext.app.get_system(SessionMetadataService)` 取得，无新 System、缓存或全局生命周期对象。

`ToolChainReplacement` 为 `entity/puretype_after/session.py` 中的消息后纯类型 BaseModel，包含半开区间与正式 `BaseMessage` 列表，经 `entity.puretype_after` 显式导出，不加入 easysave/typeref。它在定义模块中直接导入真实 `BaseMessage`，不再放在消息前纯类型包中，也不再由共享准备模块调用 `model_rebuild` 补装配；导入期不查询运行时或注册工具。

`BaseAgentLoop.reset_context_tokens()` 是新公开接口，仅清零原 `_token_record.prompt_tokens`；两工具通过它替代跨类私有字段访问，不新增 protected 字段。检测层要求链包含真实调用，跳过纯 `CompressedToolChain` 占位链。摘要全部成功才逆序替换，保存沿原 `save_history` 责任；新工具提交前检查协作式中断，无符合条件链时不保存或调用模型。原 `MAIN` / `critical` / `no_timeout` 范围保持，不扩展其他 Loop；本轮未完成的压缩调用不被配对清理删除。源码已实施，未运行验证。

> **异步架构迁移（已完成源码实施）**（按 `.tasks/2026-10-07_1_async-architecture-system-lifecycle.md`）：`Application` 继承 `AsyncArchitecture`，不持有服务镜像字段；21 个 framework `AsyncSystem` 由 `Application.start()` 按固定拓扑顺序串行注册，业务系统一律经 `app.get_system(T)` 取得。`LLMProfileStore.locked()` 暴露唯一共享 RLock。`Application.frontend_sink` 等旧属性已移除，全量引用迁移为 `get_system(FrontendSink)`；`SubAgentOrchestrator` 为依赖 `SessionManager` 的 `AsyncSystem`。关闭由 `Application.shutdown()` 统一编排并逆拓扑注销。上述为源码实施与静态审阅结果，尚未运行验证。

### 工具注册表生命周期迁移（S10）

`ToolRegistry` 继承 AsyncSystem，依赖 RuntimeSystem；工具表、工具集元数据、检查缓存/锁及唯一 ThreadPoolExecutor 均为实例字段。运行期统一 `app.get_system(ToolRegistry)`，不提供模块级单例或代理；声明期注册协议留待 S20。异步 handler 使用 TaskOwner 的 REQUEST 责任，原生线程使用 puretype/lifecycle.py 的 SyncToolCallRecord 保存真实 Future 和请求释放状态，取消包装任务不能代表线程已结束。关闭超时保留活记录，完成实际工作后再在线程中 join 执行器。调用方明确透传停止、生命周期与持久化失败，不将其作为普通工具失败继续执行。

### 工具显式注册与发现生命周期迁移（S20）

`ToolDiscoverySystem` 定义于 `abstract/tools/discover.py`，依赖已就绪的 Runtime、ToolRegistry、UIEventRouter 和 P1 列出的业务 System，包括 MCPSystem。构造仅声明依赖和建立内存记录，唤醒按固定顺序扫描五个内置子包及可选 custom_tools，再显式注册 MCP 管理工具和工具集元数据；不持有第二个注册表或重新连接 MCP。

工具模块顶层同步 `register_tools(registry, ui_events)` 是唯一声明入口，工具/事件注册迁入该函数，handler 运行时再取得业务 System。`_loaded_modules` 是实例拥有的唯一已成功注册模块名集合；同一次发现重复注册拒绝，Python 模块缓存保留，发现过程不重载/卸载/注入 sys.modules。读文件、AST、导入和注册失败传播，旧全局导入与顶层注册明确报迁移错误；ToolRegistry 未授权跨工具集名称覆盖现在抛错，不再仅日志后返回。

System 注销只清本次发现记录和自身添加的宿主导入路径，工具和事件条目继续由原 Registry/Router 管理。此次无新增 Agent Loop protected 字段或跨类状态访问。

### 主会话输入与工具提交迁移（S16进行中）

SessionManager已继承AsyncSystem并按依赖图获取服务，virtual_awake加载索引及随意聊聊索引，无构造期Application查询/磁盘I/O。外部系统引用经get_system(SessionManager)，原Application.session_manager字段与旧构造签名不再有效。Manager新增退役Loop/交接任务、唯一停止任务和显式删除排除记录。

InputDeliveryBuffer是主队列唯一投递记录表，返回sequence之前同步登记，回调只唤醒。Parent/Multi的run_pending_round接收InputDelivery列表，消息构造保持角色/媒体/hook语义；append→标APPENDED→严格save→标PERSISTED之间不await，回显最后执行。累计报告独立于成功记录清理，保存失败由BaseAgentLoop持有并请求Runtime失败关闭，不重试。

PreparedToolResult是带方法的非持久化业务模型，ToolInputReservation持有真实消息引用；prepare只构造，store_tool_result提交消息与预订，emit发送既有事件。所有主会话ToolExecutor结果分支采用该返回类型，子会话旧finalize路径保留到S17。IMainSessionLoop.reply_scope登记等待锁/活动回复，SessionManager先结束consumer/reply/退役交接，再按全局sequence串行只落History；旧Loop未结束不得释放。完整失败/旋转边界仍需S16后续静态收尾，Gateway提前接收和应用装配在S21/P22完成。

### Cron 生命周期迁移（S15）

CronRouter继承AsyncSystem，依赖RuntimeSystem/Sandbox/SubprocessRunner；_CronTask及纯时间解析迁至component/cron_tasks.py。任务、路由、全部Timer、运行中命令及原生停止任务均归Router，工具不再访问_lock/_tasks/_timer或私有持久化/调度方法。get_system(CronRouter)替代Application.cron_router，Gateway REST、会话注册/注销、旋转与主/子会话工具同步迁移。

唤醒严格加载不调度，RUNNING后activate；freeze不清除持久调度标记，callback只在统一接收边界内开始。Timer直接执行命令，退出确认后才移除真实线程，取消或删除任务仍保留运行中命令所有权。关闭先终止再join，不吞释放/保存错误；SubprocessRunner对迟到创建重新检查Runtime封闭状态。旧类图/字段表中的Cron工具跨类写字段描述为迁移前记录，实际以此节为准；输入与最终装配仍待S16/S17/P22。

### 多模态生命周期迁移（S14）

ModalityCapabilitySystem依赖RuntimeSystem/LLMProfileStore，持有_probe_locks、音频/视频探针、缓存路径及TaskOwner；virtual_awake准备媒体，模块导入无模板I/O。缓存查询、探测、有效Profile解析、转发与提示词查询改为实例入口；纯内容块构造/格式化与显式profile_data的引用解析保持独立函数。完整请求经run_request管理，六路TaskGroup子任务实际结束后才交还结果；取消请求不提前清除共享锁，关闭不启动新模型。缓存继续直接保存ModalityCapability对象，存储格式和引用规则保持。

### 浏览器生命周期迁移（S13）

BrowserSystem依赖RuntimeSystem，唯一持有_pw/_browser/_endpoint、按PID登记的_headless_procs以及连接锁和清理任务。多次无头启动不能覆盖尚未释放的旧进程；只有已登记自有无头进程会被终止。工具经Application.get_system(BrowserSystem)调用明确实例API，_connection无可变连接状态，常量在entity/constant/browser.py。get_browser使用TaskOwner请求，断连和原生进程释放持有独立任务并在真实完成后回收，取消/超时不清空活句柄。

### LSP 生命周期迁移（S12）

`LSPManager` 是依赖 RuntimeSystem/Sandbox 的 AsyncSystem，持有 pyright 进程、唯一 stdout reader、stderr reader、pending 请求、原生响应等待与关闭任务。组件工具及文件修改后的诊断附加经 `get_system(LSPManager)` 调用，移除独立 getter/cleanup。`start(root_logical)` 以及查询/通知方法复用唤醒时保存的 Sandbox，不再由外部传入；主loop固定为 Runtime.loop。替换/释放使用独立operation锁，状态锁不覆盖thread.join；实际退出后才清除资源句柄，失败传播。

### Gateway 快速失败与 Profile 提交顺序

Gateway 普通 HTTP 响应保留 BaseModel（含字典/列表中的嵌套模型），由 FastAPI 编码；显式 Response、WebSocket 和 SSE 仍在实际传输边界序列化。接口只转换专门的业务异常，意外错误不再被通用 `Exception`/`OSError` 包装成固定 500，也不返回空结果或默认请求掩盖失败。Profile 的 `ProfileNotFoundError`/`ProfileConflictError` 和动态沙盒空间的 `DynamicSandboxInputError`/`DynamicSandboxConflictError`/`DynamicSandboxNotFoundError` 均定义在所属业务模块，不新增全局生命周期对象。

`LLMProfileStore` 六个写方法改为候选根先保存、成功后提交共享内存；更新候选图先复制全部 Profile，再按对象身份重连三个 Profile 引用和六个全局引用，提交时仍更新原实例。不再维护 `_snapshot_profile`/`_restore_profile` 或失败回滚。`assert_removable`/`remove_profile` 的 `clear_global_selections` 关键字参数允许在一次根对象写入中清空指向删除目标的审批/元数据/工具链摘要引用，其他 Profile 与全局多模态引用依然阻止删除。先完成业务检查再修改，避免拒绝删除时已经清空全局选择；跨 Profile 文件、会话名称指针和通知仍无整体事务。

`ws_chat` 的初始化归入连接生命周期 `finally`，取消与意外错误继续传播；订阅清理即使失败也释放属于本连接的交互和连接登记。重新生成入口在 `finally` 中结束匹配的活动标识，包括请求取消与通知编码失败；不改变 Loop 的 task 登记归属。无新增 protected 字段或跨类访问。

### 流式事件模型与发送边界收敛

`AgentSink.emit_stream_delta()` 及两个实现均接收 `ToolCallRequest` / `ToolCallDelta`，`StreamConsumer` 不再在调用前降级为 dict。`FrontendSink` 构造 `entity.puretype.ws` 中的 `StreamDeltaEvent` / `StreamDoneEvent`，以 `StreamEvent` 判别联合约束 `_send_stream_event()`，仅在此执行 `model_dump_json(exclude_none=True)` 并发送；模型/序列化错误不作为网络错误吞掉。`MessageMetrics` 全程保持实例，`ParentAgentSink` 通过属性适配原子会话反馈通道，主/子会话路由、History与中断收尾顺序不变。

`stream_delta` 的工具载荷改为顶层对象，前端两种流式事件在 `WSMessage` 中拥有独立类型，旧消息分支排除这两种 `type`，接收时校验实际结构。`stream_done` 的可选正文区分缺失与显式空字符串，既有 `emit_stream_done(content="")` 调用仍按原行为省略正文。前后端同步部署，不保留旧工具载荷内嵌 JSON。

删除未被调用的 `gateway.server._send_tool_event()`、`ParentAgentLoop._tool_event_callback` / `set_tool_event_callback()` 和 `main.py` 注册代码，避免重复编码逻辑继续漂移。无新增全局生命周期对象或跨类 protected访问；协议类型直接依赖 `entity.puretype`，不经 `gateway.chat` 反向导入。

### 子Agent数量限制与旧排队协议移除

普通子Agent和临时Agent直接进入启动流程，不再维护数量上限或等待队列；启动登记、重复角色防护、失败回滚及任务清理保持不变。移除非持久化编排响应中的 `waiting`、`queue_position`、`promoted` 和停止结果中仅用于排队提示的 `note`，删除 `SubAgentPromotion` 及其导出。子会话状态统一为 `running` / `completed` / `terminated`，前后端同步移除旧 `waiting` 状态，不保留兼容字段；History 持久化结构不变。

### system 角色用户消息前端显示偏好

前端 `chatRuntimeStore` 持有浏览器全局 `showSystemUserMessages` 偏好及更新入口，默认显示，localStorage 恢复/保存，独立于会话重置字段。`messageVisibility.ts` 提供无状态判断，主聊天统一行、子会话与工具结果嵌入消息共用；仅筛选 Role 为 `user` 且角色名为 `system` 的消息。`selectChatRenderRows` 在完整正典/实时关联之后过滤，Virtuoso 与小地图共用展示顺序，`chatRuntimeController` 把展示索引转换为原始 History 索引后请求内容页，滚动控制器同步处理显示切换与回底目标。无后端类、字段、protected 访问、History 存储或消息协议变更。

### 主聊天历史骨架、内容页与虚拟化

`History` 与 `history.es` 保持整体类型保留存储；`BaseAgentLoop` 新增三个只读投影接口，经 `entry/history_projection.py` 输出全历史骨架、按 History 索引范围的历史内容页和完整资源索引。Gateway 只向主会话暴露三个 REST，并以 `history_sync` 通知正典历史数量。前端使用 Zustand 隔离高频状态、Virtuoso 只挂载可视消息行，主聊天区 Minimap 改为逻辑映射；工具调用请求和匹配结果在只读投影层按 `tool_call_id` 聚合为一张工具调用卡片，结果可跨内容页返回，匹配结果不再产生独立视觉行；当前轮 live 行在内容页完成正典合并后再清理。

### 主聊天滚动追底协调

`useChatScrollController` 是主聊天区被动追底的唯一协调入口。实时内容提交、skeleton/liveRows 正典交接的布局提交与列表总高度变化先复用同一调度；被动追底只申请一个可取消的 `requestAnimationFrame` 任务，任务执行时读取 Virtuoso scroller 的最新 `scrollTop`、`scrollHeight` 和 `clientHeight`，并以 `scrollHeight - clientHeight` 为物理底部目标。`atBottomStateChange` 仅触发统一物理指标采样，不因自动滚动再次独立创建追底任务；连续流式增长允许按有效布局帧更新底部，但同一帧内不会重复写入被动追底位置。

用户滚动意图、消息高度变更、小地图拖拽、会话重置或状态离开 `following` 时取消待执行任务。Minimap 拖拽状态独占，物理底部观察和高度操作收尾不得提前退出；提交按实际 scroller 位置判断到底。显式回底由同一 Hook 持有局部动作序号、会话代际和可取消布局帧，页加载失败回到离底状态，用户新操作与生命周期变化使旧动作失效。快速滚动占位使用 Virtuoso 原行高度；物理离底指标仅驱动底部状态、自动追底和显式回底动作，`.scroll-to-bottom` 节点由 `ChatArea` 挂载时结构性常驻，不以 `detached`、`initialReady` 或其他滚动状态控制。最新流式消息超过视口时保持物理底部锚点，不切换到消息顶部，也不改变 History、Virtuoso 行顺序或消息协议。


### Memory 系统移除

`ParentAgentLoop` 中原有的 `_memory`（`MemoryManager`）和 `_memory_initialized_ids`（`set[int]`）字段已移除。`add_memory_provider()` 方法也已完全移除（不再保留空实现）。`LoopSessionManager` 中涉及 memory 的迁移逻辑已移除。记忆能力不再由核心管理；扩展可通过通用工具接口与上下文钩子接入。

### LLM 抽象层引入

`ParentAgentLoop._llm` 类型从具体的 `LLMClient` 变为 `BaseLLMClient`（抽象基类）。实际客户端通过 `abstract/llm/loader.py::create_llm_client()` 工厂从 `custom_llm_client/` 动态加载。

`abstract/llm/formats.py` 提供 `to_openai_message()` 和 `messages_to_anthropic_list()` 两种 wire format 转换器，供 LLM 客户端复用。

### 子Agent编排返回值稳定类型化

`SubAgentOrchestrator` 与 `_OrchestratorContext` 的 `launch()`、`chat()`、`approve()`、`stop()`、`get_snapshot()` 统一返回 `entity/puretype/subagent.py` 中的 BaseModel。`SubAgentSnapshot`、`SubAgentUpdate` 共同定义状态、反馈、待审批调用和交互标志；`ListSubAgents`、Gateway 和消息路由通过属性读取。工具结果和 WebSocket/HTTP 仍在传输边界序列化，避免 `info.get(...)`、嵌套字典键漂移和 `tool_result(**result)` 的隐式字段耦合。


`abstract/mcp/system.py::MCPSystem` 依赖 `RuntimeSystem` 与 `ToolRegistry`，持有 `abstract.mcp.client::MCPCore`；服务器表、断路器、专用 loop/thread、stdio 进程、stderr 句柄和 OAuth Manager 均由 Core 唯一持有。`MCPServerTask` 的连接请求经 `TaskOwner` 管理，取消不丢 Future；stdio 进程由 `MCPStdioTransport` 直接持有真实句柄，Windows Job 通过 SDK `_job_object` 显式绑定。OAuth 认证任务、回调 HTTP 线程和 401 dedup 均由 `MCPOAuthManager` 收口，`close_admission` 主动停止回调线程，`aclose` 经 shield 等待真实 join。2026-10-09 独立静态复核确认无阻塞级缺陷，S19 已补齐。

`SubAgentOrchestrator` 现继承 framework `AsyncSystem`，通过依赖声明取得 `RuntimeSystem`、`SessionManager` 及子Agent业务System；`_OrchestratorContext` 只保存 `SessionManager`，不保存启动用父Loop。`Inbox` 使用 `InputDeliveryBuffer[InboxMessage]`，初始prompt与父消息共用sequence；反馈使用 `SubAgentFeedbackDelivery`，正常投递和关闭交接分别确认，普通子Agent停止先等待运行任务再刷新并保存，TaskAgent不保存。

`system/application.py::Application` 作为进程级唯一单例，替代了原有的模块级全局变量。所有子系统（`LLMProfileStore`、共享 Profile 锁、`SessionMetadataService`、`SessionManager`、`FrontendSink`、`SubAgentOrchestrator`、`ApprovalBackendManager`、`CronRouter`、`ToolRegistry`）通过 `Application.current()` 访问。

### Approval 目录化

`component/approval/` 从单文件重构为目录，包含：`__init__.py`（公共接口）、`core.py`（`request_user_confirm` 统一审批入口；`ask_agent_reason` 脱手模式向 Agent 主模型提问取上下文）、`policy.py`（预设策略 `MAIN_SESSION_POLICY` / `SUB_SESSION_POLICY` 与 `needs_approval()`；数据类 `ApprovalPolicy` 定义在 `entity/puretype/approval`）、`backend.py`（`ApprovalBackend` / `LocalApprovalBackend`）、`executor.py`（`execute_with_approval`）、`allowlist.py`（白名单逻辑）、`handsfree.py`（脱手模式）。`ApprovalBackendManager` 由 `Application` 持有，管理审批后端的懒加载和生命周期。

### MessageRouter 拆分

`gateway/message_router.py::MessageRouter` 从 `gateway/server.py` 的 `ws_chat` 中拆分，负责所有 WebSocket 消息类型的分发处理。`server.py` 仅保留静态路由表、连接生命周期管理与 `build_router_app()` 工厂。

### GatewaySystem 生命周期（S21）

`gateway/system.py::GatewaySystem` 是 FastAPI/uvicorn/socket 的唯一所有者（依赖 RuntimeSystem、ToolDiscoverySystem、SessionManager、SubAgentOrchestrator、DynamicEndpointSystem、FrontendSink、AgentspaceService、ApprovalSystem、LLMProfileStore、SessionMetadataService、CronRouter、ShellManager、Sandbox，最后唤醒、首先注销）。`gateway/server.py` 只含模块级静态 `APIRouter` 与 `build_router_app() -> FastAPI`；模块级 `_agentspace_path`/`_BUILD_HASH`/`set_agentspace_path`/旧 `create_server` 已删除，文件上传路径经 `RuntimeSystem.context.agentspace`，构建哈希存于运行实例 `app.state.build_hash`。`gateway/lifecycle.py::GatewayAdmission` 区分新业务（RUNNING + `admit_business`，HTTP 503）、WS 连接（STARTING/RUNNING + `admit_connection`）与已建连接每条输入（`require_open_connection`，1001）。路由启动的后台任务（USER_MESSAGE 准备、子会话转发、WS 中断、Agentspace 桥接、SSE 等待）全部经 `GatewaySystem.spawn_work`/`task_owner.track` 登记；关闭顺序为 `stop_accepting()` → `cancel_background_work()` → `stop_server()`。uvicorn 由 `_GatewayUvicornServer` 子类管理：禁用自身信号安装，startup 成功后置 `GatewayReadyTracker`；启动等待 ready、serve 提前结束、`GATEWAY_START_TIMEOUT_SECONDS` 三者竞速。启动前端口占用经 `check_port_available` 探测并抛 `GatewayPortBusyError`（按退出 0 的普通业务拒绝），bind 竞态失败属启动失败。

### MultiAgentWorker 独立工具执行

`MultiAgentWorker` 内部创建独立的 `StreamConsumer` 和 `ToolExecutor` 实例，复用 `ParentAgentLoop` 的统一工具执行逻辑，但拥有独立的 stream_id 生成和 token 统计。

### 工具结果后处理统一

`entry/tool_post_dispatch.py` 提供 `PreparedToolResult`，`SubAgentLoop` 与主会话统一使用 `prepare_tool_result → store_tool_result → emit`；普通子Agent先提交内存History，停止时严格保存，TaskAgent不新增持久化。

### 调用级进化意图（RV4）

进化不再解析工具结果文本，也不由 `finalize_evolution` 直接修改运行器：EvolveCode 验证通过只调用 `ToolContext.request_evolution()` 登记本次调用的非持久化标记；`ToolExecutor` 在构造 `PreparedToolResult` 时消费该标记为 `evolution_requested`；所属 Loop 的 `store_tool_result` 在真实消息严格保存成功后才调用 `RuntimeSystem.request_shutdown(EVOLUTION)`（D6），保存失败或中断占位不产生进化成功。请求之后 Runtime 进入 STOPPING，后续 tool_calls 经接收边界拒绝并补现有中断占位。`main.request_evolution`/`trigger_evolution_shutdown` 与 Gateway 文本回调触发路径已删除；进程退出码由 `App.run` 按关闭结果与 `RuntimeSystem.exit_code` 映射。

### 会话级消息队列（SP-4/SP-5）

`entry/session_message_queue.py::SessionMessageQueue` 由 `ParentAgentLoop` / `MultiAgentLoop`（及继承的 `ColloquyLoop`）持有。生产侧仍经 `call_soon_threadsafe` 落回事件循环；消费侧改为严格逐条 FIFO，每条前端消息保存自己的 `llm_profile_name` 并在执行前重新解析。当前工具轮期间到达的用户消息不再由 `drain_injected` 移出，而是在当前轮结束后依次执行。gateway 在 loop 消亡时调 `stop()`；`replace_loop` 场景用 `mark_stopped()` 标记停止而不 cancel。

### LLM Profile 根对象与名称边界

`Application` 持有唯一 `LLMProfileStore`、共享进程锁和 `SessionMetadataService`。`llm_profiles.es` 仅支持 v2 `LLMProfileData` 根对象，三个多模态分工字段、审批 Profile、全局元数据 Profile以及全局图片/音频/视频回退 Profile直接保存根列表中的 `LLMProfile` 实例引用；不存在 UID 或 v1 迁移。Gateway 只接收扁平名称 DTO 和单 Profile CRUD，三路全局回退通过独立 `/api/modality/profiles` 协议管理。主会话活动配置以名称指针持久化，每条前端消息只传 `llm_profile_name`；`IMainSessionLoop.set_profile()` 由 Parent/Multi 实现。`/regenerate` 请求明确接收 `llm_profile_name` 并在生成前更新活动 Profile；`/resume` 仅从当前历史恢复工具链，不接收、不更新 Profile，使用 `ParentAgentLoop` 当前已持有的活动 Profile。

### 模型配置分页与会话待用选择

新增只读 HTTP DTO `SessionLlmProfileState`（`entity/puretype/llm.py`，纯字段 BaseModel），通过 `GET /api/sessions/{id}/llm-profile` 返回会话持久化名称及既有全局最近使用回退、名称可用性。Gateway 在 Application 已有 `profile_lock` 内读取无状态 `SessionStore`；不创建 Loop、不新增生命周期对象、不写名称指针。响应不是正在执行的客户端快照。

前端 `useLlmProfiles(sessionId)` 组合 `useSessionLlmSelection`，将浏览器待用名称按主会话隔离。显式本地选择优先，无本地覆盖时读取服务端；每条主会话消息/重新生成仍独立捕获名称，resume不提交本地选择。模型抽屉仅管理定义和全局引用，唯一会话选择入口为顶部栏的独立浮层菜单。`useLlmProfileEditor` 独立管理内存草稿，切分页不重建草稿；没有新增 Agent Loop 字段或 protected 访问。

### 全局元数据 Profile 与延续摘要保障

`SessionMetadataService`是标题、标签和摘要生成的唯一业务入口。它优先使用 `LLMProfileData.metadata_profile`；仅在全局引用为空时通过 `SessionStore.read_active_profile_name(session_id)`按目标会话回退，并对选定 Profile执行浅拷贝形成单次调用快照。明确配置但无效或调用失败时禁止静默回退。手动终结中的摘要和标签为 best-effort，失败通过 `SessionTerminationResult.metadata_warnings`返回但仍归档；分支、合并与自动超限旋转必须先取得摘要。自动旋转在摘要或延续初始化失败时保持旧会话 active、保留触发消息并追加对 LLM 不可见的系统状态，成功初始化延续 History后才归档旧会话。

### 多模态能力探测内化

原探针工具已内化为 `system/modality_capability.py` 的系统自动行为：需要给活跃模型传递多模态块时先查 easysave 缓存（`modality_capability_cache.es`，按 model+base_url 联合索引、六项能力齐全才命中），未探测则伪装 Read 工具调用按 模态 × 消息路径（tool/user）六路并发探测；HTTP 400 类错误经模块级 `_is_modality_rejection` 统一判定，只识别客户端归一化的 abstract 层 `LLMAPIStatusError(400)`（openai/anthropic 协议非流式路径由客户端转换抛出、流式回退路径经 `StreamChunk.error_code` 重建），system 层不依赖具体 SDK 异常族；及客户端明确的 `UnsupportedModalityError` 判为对应模态不支持，网络/认证/超时等非模态错误上抛不写缓存。`build_modality_prompt_block()` 每轮生成 system prompt 注入块；活跃模型不支持某模态时经 `resolve_modality_reference_profile()` 按活动引用优先、全局对应媒体回退引用次之解析，再由 `forward_modality_to_ref_profile()` 单跳转发。全局三路引用保存为 `LLMProfileData` 根列表中的实例引用，Profile 被引用时受删除保护；显式活动引用失败不切换全局回退，非预期异常不被吞没。多模态预检调用（`ParentAgentLoop._run_tool_loop` 与 `MultiAgentWorker`）纳入模型错误转换边界：无法转发（`ModalityForwardUnavailableError`）时终止本轮并把配置指引持久化展示给前端，provider 错误降级为用户可见错误，不穿透炸轮次。

### 多模态探针 400 误判修复与无法转发的前端可见拒绝

2026-10-10 事故：glm-5.3（Anthropic 协议）图片探测收到 HTTP 400「Model only supports text input」，异常经客户端流式回退路径降级为裸 `RuntimeError`（状态码语义丢失），探针 except 链只识别 openai 族 400 而误判为致命错误上抛，从无保护的预检调用点穿透炸掉轮次并在 shutdown 时层层重抛（`Application shutdown failed`）。修复分四层：

1. `StreamChunk` 新增 `error_code: int | None`（`entity/puretype/llm.py`），客户端流式 400 在 error chunk 附带 HTTP 状态码；
2. `abstract/llm/client.py` 新增 `LLMAPIStatusError(RuntimeError)`（携带 `status_code`，继承 RuntimeError 保证既有 `except RuntimeError` 捕获点行为不变），作为客户端 API 状态错误的统一 abstract 层表达：客户端 API 状态错误须转换为统一的 `LLMAPIStatusError`（`raise ... from` 保留异常链）；流式错误块通过 `error_code` 保留 HTTP 状态码，回退收集路径据此重建同一类型，其余错误块维持原错误语义；
3. `system/modality_capability.py` 新增模块级 `_is_modality_rejection`，只识别 abstract 层 `LLMAPIStatusError(400)` 单一来源，system 核心不 import 任何具体 SDK（消除原探针对 openai 族异常的内联依赖与「openai 协议 = openai 库」假设，原 TODO 完成）；两个探针函数与 `_forward_modality_to_ref_profile` 的 400 判断全部收敛到该 helper；
4. `entry/agent_support/multimodal.py` 新增 `ModalityForwardUnavailableError(ValueError)`（无引用 Profile 时抛出，含配置指引文本）；`ParentAgentLoop._run_tool_loop`（`stream_id` 提前生成）与 `MultiAgentWorker` 的预检调用纳入与模型错误路径同构的边界转换——无法转发终止本轮并把指引持久化展示给前端，provider 错误降级为用户可见错误，生命周期异常照常放行。

修复合并了探针日志笔误（tool 路径 400 日志补 `single_probe(tool)` 后缀）。

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

### 轮次后 HISTORY_SYNC 的 agents 口径修正

`MessageRouter._send_history_sync` 的 `agents` 字段从"轮次所属 Loop"改为"会话当前注册 Loop"（`_get_loop(self.sid)`）计算，与 `server.py` 握手处 HISTORY_SYNC 口径一致。原实现下 `ExitMultiAgent` 在旧 MultiAgentLoop 轮次内调用 `replace_loop`（推送 `{"agents": []}` 并注册 ParentAgentLoop）后，退役 loop 最后一轮收尾仍会执行轮次后回调：按退役 MultiAgentLoop 的 `_agent_names` 计算 agents 并随 HISTORY_SYNC 推送，把清空通知覆盖回过期多Agent列表，前端主徽章停留在多Agent配色。新 ParentAgentLoop 各轮 HISTORY_SYNC 中 `agents=None` 被 `exclude_none` 省略，前端 `setAgents` 两个分支均不触发，过期状态不会自愈。`agents` 属于会话级模式状态而非轮次级数据，因此取当前注册 Loop；token 统计等轮次级字段仍按轮次所属 Loop。

### 主会话永久删除与连接失效收敛

永久删除由 Gateway 分层执行：`SessionManager` 的删除中集合先封闭新连接与 Loop重建竞态，`FrontendSink.close_session()`从连接映射移除会话并以 4004关闭已建立连接，`delete_session_runtime()`再中断活动回复、停止长期消息队列、清除客户端信息并注销 Cron，最后由 `gateway.chat.SessionManager.remove()`统一删除索引与会话目录。握手前无法可靠向浏览器传递私有关闭码，因此前端通过 `/api/sessions/{id}/status` 的删除感知 `exists`字段二次确认；显式恢复已经删除或删除中的 ID不再创建随机新会话。

### 临时Agent继承活动 LLM Profile与工具权限收敛

`RunTaskAgent` 通过公开 `ToolContext.llm_profile` 取得调用发生时父主会话的活动 Profile，并由 `LLMProfileStore.snapshot_profile()` 在共享锁内验证根对象身份后创建非持久化深快照。快照完整保留客户端、采样、多模态分工等配置；临时Agent不再从 `SubRuntimeContext` 空默认值构造 `custom_llm_client.`，也不再暴露单次 temperature参数。普通角色子Agent不再使用注册配置，而是通过 `subagent/profile.py::CharacterProfileResolver` 动态读取角色档案；`AgentConfig` 仅作为 `AgentProfile` 的运行时适配对象。`TaskAgent` 仍只使用活动 LLM Profile 的非持久化快照。

`TaskAgentLoop` 不新增字段。它复用 `SubAgentLoop._allowed_tool_names` 与会话级已加载工具集，并在模型定义生成和执行期统一要求“已加载工具集 ∩ `TASKAGENT` 可用范围 ∩ `safe` 危险等级”。允许工具直接执行，越权调用直接返回失败工具结果，不进入父Agent或审批模型流程。`LoadToolset` 只扩展已加载集合，不扩大权限交集。

### 主聊天实时行到正典 History 行交接

实时行到正典 History 行的交接继续以明确 `live_id → history_row_id` 关联为准；滚动位置不参与消息身份或交接判断。工具调用请求和结果通过同一工具卡片关联，滚动控制器只负责视口物理位置，不改变正典交接语义。

`entry/stream_history_link.py` 统一发送 `stream_id/history_index` 与 `live_history_links`。`ParentAgentLoop`（含继承的 `ColloquyLoop`）和 `MultiAgentWorker`只使用实际 `History.add_message()`返回索引构造关联；`MultiAgentLoop._cascade()`继续负责最终 assistant 行。工具请求和匹配结果使用统一 `tool-card:<tool_call_id>` live ID，指向请求锚定的 `history:<index>:tool:<tool_index>` 工具调用卡片行；History 持久化顺序不变。`FrontendSink`必须透传 `tool_call_id`，持久化 system 状态携带 `index/is_system_status`。缺失、重复、孤立或非法倒序的 `tool_call_id` 不猜配：后端记录 warning，前端保留缺失结果卡片或独立降级行。子Agent与临时Agent的独立 History不映射到主会话。

前端 `chatRuntimeStore`持有通用实时行映射。user/assistant/tool/system 行只有在 skeleton 已存在目标行并完成正典交接后才从实时 footer移除；未映射、目标未出现或History请求失败的行保留并产生诊断。History数量减少表示结构代际替换，旧映射和旧实时尾部统一失效。

### 异步架构迁移：TaskOwner结果归属（RV11）

`SessionMetadataService`持有`TaskOwner`，通过`run_request`登记完整标题/标签/摘要操作，公开方法的请求方负责取得普通异常及取消。内部实现只调用内部方法，不重复登记同一操作。后台任务使用`create/track`，其意外失败由所属System报告；两者在创建时通过`TaskOwnership`确定，不依据是否有人偶然await动态分类。

`TaskOwner._records`持有`ManagedTaskRecord`，记录实际Task、请求等待方、预期取消、唯一清理task、固定取消截止、终局错误及交接状态；纯字段模型位于`entity/puretype/lifecycle.py`，不写入History或easysave。`pending`只列活任务，`is_idle`还包含未完成交接；请求异常已交还后不进入应用关闭失败集合。`LifecycleFailure`及异常组中的该类型始终上报，取消清理超时保留活任务及其依赖。

新增公共操作为`run_request/cancel/is_idle`，业务类不得跨类修改记录表。本节描述已实施公共契约，不表示运行验证已通过。

### 轮次导航条替换小地图（2026-10-12）

主聊天区逻辑小地图（Canvas 逻辑映射 + 视口高亮 + 拖拽跳转）与子会话卡片 Legacy 小地图（DOM 几何预览）整体退役，替换为「轮次导航条」（`RoundNavRail`，规范称谓见 DEV-glossary §11，旧称已入 §13 退役表）。每条目对应一条 Role 为 `user` 的展示行，杠+内容文本一体，杠按作者角色名 hue 散列着色（`utils/color.ts` 的 `hueFromString`，与头像一致），当前轮由 `ChatArea` 按 DOM 参考线判定（已渲染行中最后位于「视口顶 + `ROUND_NAV_JUMP_OFFSET_RATIO` 视口高度」以上的行所归属的条目）并放大+花纹凸显；点击跳转经 `useChatScrollController.jumpToRound(rowIndex)`（未加载先 `jumpToLogicalRow` 取页，再 `scrollToIndex` 定位到视口中部略偏上，近平滑远瞬时）。rail 常驻窄条、无折叠按钮，桌面 hover/focus 展开居中浮层，条目过多时虚拟滚动、过少时垂直居中。`ChatFollowMode` 移除 `minimap_dragging`，`ScrollEvent` 移除 `MINIMAP_START/MINIMAP_END`，`ChatVirtualListHandle` 的三方法（beginMinimapDrag/previewMinimapScrollTop/commitMinimapDrag）由 `jumpToRound` 取代；`minimapGeometry.ts` 删除，幸存的 `normalizeScrollMetrics`/`measuredHistoryRowHeights` 迁入 `scrollGeometry.ts`。骨架投影 `SessionHistorySkeletonRow` 新增 `content_excerpt`（仅 user 普通消息行填充，截断长度 `HISTORY_SKELETON_USER_EXCERPT_CHARS`），供轮次导航条展示未加载页的条目文本。无新增 Loop protected 字段或跨类访问。

### TaskOwner 预期失败标记与聊天 WS Agentspace 超时驱逐（2026-10-13）

`ManagedTaskRecord` 新增 `expected_failure` 字段，`TaskOwner.mark_expected_failure(task)` 在任务结算前标记例常预期失败；`_settle` 对已标记的 BACKGROUND 终局异常不再上报所属 System（`LifecycleFailure` 及含它的异常组仍始终上报，不豁免）。首个消费者为聊天 WebSocket 的 Agentspace 事件转发：`forward_agentspace_events` 单事件发送超 `AGENTSPACE_WS_SEND_TIMEOUT_SECONDS` 秒抛 `AgentspaceSendTimeout`（TimeoutError 子类哨兵），`_close_on_agentspace_failure` 先标记预期失败再以 1011 断连驱逐慢消费者连接，折叠日志按 `AGENTSPACE_WS_COALESCE_LOG_WINDOW_SECONDS` 时间窗限流携带窗口累计 dropped（日志级别维持 28bab6b 已定的 debug）。慢消费者超时定性为连接级例常事件而非进程级失败，不再触发应用失败关闭；done_callback 的注册顺序（标记回调先于 track 的结算回调）是该机制的正确性前提。

### 主会话媒体实例发送控制（2026-10-13）

新增继承关系：`MessageBlock → MediaBlock → ImageBlock / AudioBlock / VideoBlock`；`TextBlock`仍直接继承MessageBlock。媒体类的模块路径/type token和as_object输出不变。MediaBlock新增 `media_id: str`、`send_multimodal: bool`、`source_path: str | None`、`source_tool_call_id: str | None`、`forward_result_verified: bool`，原forward_result_content仍归MessageBlock。它们与原媒体同属History对象图，直接由easysave存储，不新增全局媒体System或状态镜像。

| 归属 | 新接口/模型 | 外部访问与责任 |
|---|---|---|
| BaseAgentLoop | `_persist_history_value(session_id, history)` | 类内严格保存候选，沿原HistoryPersistenceError/Runtime失败责任 |
| BaseAgentLoop | `ensure_media_identity`、`get_session_media`、`get_session_media_block` | Gateway和请求准备经公开接口读取；补缺身份先保存，不按历史索引持久控制 |
| BaseAgentLoop | `set_session_media_enabled` | Gateway解析StrictBool后同步调用，候选先保存再更新原实例，处理中不等process锁 |
| BaseAgentLoop | `commit_media_description` | 请求准备提交成功描述，校验旧sid/History/ID，first-success-wins，只改缓存不覆盖开关 |
| entry/history_media.py | HistoryMediaOccurrence与纯函数 | 通过History公开迭代/set_message组织身份、定位、投影和候选，不做I/O或Application查询 |
| entry/agent_support/multimodal.py | PreparedMultimodalRequest.capture | 非持久业务模型，消息/媒体浅副本固定开关；最后用户指针关联副本而非原对象 |
| ModalityCapabilitySystem | `describe_media_block` | TaskOwner持有单跳描述请求；通过ToolContext.app公开get_system取得LLMProfileStore，在共享锁内解析并快照引用 |
| entity/puretype/session_media.py | 四个REST纯模型 | Gateway保留BaseModel返回，前端完整解码轻量协议；无媒体载荷 |

ParentAgentLoop每轮消费独立request.messages，不覆盖原messages。MultiAgentWorker保留原full_messages，使同worker重新开启可恢复媒体；它继续传None，不扩展当前动态后缀行为。临时/普通子Agent独立History不进入新准备路径。工具结果来源由tool_post_dispatch传入转换函数，客户端输入不能覆盖内部身份/开关。

已实施字段/API与请求路径；没有新增protected状态字段、跨类私有字段写入或新的System拓扑。未运行验证，必要写盘失败可能沿现有生命周期终止应用。

### 媒体输入Tab中文相册展示修订（2026-10-14）

按用户反馈，旧MediaInputCard移除；前端新增 `MediaGalleryTile`（预览/名称/状态角标）与 `MediaDetailsWindow`（现有ModalWindow+portal、大预览/信息/发送开关），共用 `MediaPreview`。MediaInputTab只持有selectedMediaId和焦点锚点，详情数据始终从权威页按ID查，不保存独立过期副本；切会话/页/Tab或实例删除关闭，关闭后只对当前有效视图恢复焦点。thumbnail无交互媒体controls或开关，detail才启用播放器；组件清理停止音视频并恢复StrictMode effect重放后的src。

`zh-CN.json`为正式非代码文案资源，`labels.ts`用Vite raw机制显式校验后导出中文UI文本，源码标识与错误类型保持英文；服务端/协议错误作为中文错误详情区技术数据保留。常量/展示props在原frontend功能包内，无新增全局System、存储或模型接口；后端独立实例/转发/候选写盘契约完全不变。未运行验证。

### History辅助读取复用正式类型（2026-10-14）

开发助手AI专用 `dev_helpers/read_history.py` 复用 `entity.messages.History` / `MediaBlock` / 三种媒体子类、`entity.typeref.make_config()`、`History_Version` 和只读 `third/easysave.raw_load()`，不再维护独立对象图解码器或模型字段表。它只访问History的公开 `messages` / `last_user_message`、消息Role、媒体字段及BaseModel公开迭代接口；不调用配对清理、任何写盘方法或Application，不新增运行时System/protected字段，也不修改还原后的模型。媒体占位只存在于输出字典，未识别媒体类型快速失败。导入origin库是AGENTS.md登记的开发辅助例外，不授权直接启动origin仓库应用；easysave动态类型加载只用于受信任的本地项目历史。

### 右侧 Tab 悬停预览与会话资源 Scope 快照（2026-10-14）

新增只读前端能力，不改变 Agent Loop 继承关系、protected 字段归属或任何后端 System：

- `entity/puretype/extools.py::CronTaskInfo` 增加只读响应字段 `is_wait`/`wait_message`（`component/cron_router.py::_build_task_info` 显式映射 `_CronTask`），前端 `types.ts::CronTask` 增加对应可选字段；不改调度/持久化/审批/Timer/执行。
- `entity/puretype/session_media.py::SessionMediaListResponse` 增加六个全 History 聚合字段，由 `entry/history_media.py::project_history_media` 在同次遍历计算；分页与内容端点/开关语义不变。前端 `UseSessionMediaState` 增加独立 `aggregate`（翻页保留、切会话/404 清空）。
- 前端会话资源三源（Shell/Cron/动态端点）改由 `hooks/useSessionStore.ts` 的 `SessionResourceScope`（sessionId+generation）快照承载，`hooks/useSessionResourceSnapshot.ts` 提供唯一 data + 在途读与 Token 校验，`hooks/useWebSocket.ts` 原轮询经 Token/Scope 提交；旧数组 API 由同一快照派生，不再是第二份 state。
- 共享数据：`features/tabs/TabDataContext.tsx` 唯一 Provider 持有 characters/sandbox/media/variables 四个 hook 各一份，正式 Tab 与只读预览共享。悬停预览（`useTabPreview`/`tabPreviewSelectors`/`TabHoverPreview`/`useAnchoredHoverPreview`/`tabPreviewLabels.json`/`constants/tabPreview.ts`）只消费已加载快照，不发请求、不刷新、不切换 activeTab。
- 无 Loop protected 字段新增，无 Application 单例或持久化迁移；中文文案为正式 JSON 数据资源，源码标识保持英文。

### 会话网页首次激活加载（2026-10-14）

会话网页的入口探测与正文加载分离：`features/tabs/useTabSystem.ts` 仍持有唯一 `useSessionSite`，提前 HEAD 探测并复用原 WebSocket Agentspace 事件/HEAD 版本轮询；`SiteTab` 只有首次激活且入口 ready、URL 可用时才创建 iframe 与工具栏，未点击时不加载网页正文或运行脚本。局部 `hasBeenActivated` 在同会话切 Tab 后保留，原部署热刷新与按钮行为保持；首次激活后隐藏 Tab 也可热刷新，入口删除后同会话重部署可自动重建。

`useTabSystem` 的局部 `activeTabState` 携带 sessionId，render 同步将归属不匹配的旧活跃状态派生为 chat，再由 effect 提交当前会话聊天状态，避免旧 site 激活值在新会话首次 render 触发加载。注册表仅给 `SiteTab` 增加 sessionId React key，切会话重建其激活/全屏状态与 ref，返回原会话也重新等待点击；其他 Tab 外层、共享 Provider 与模型/动态沙盒草稿不重建，主界面区域仍使用 grid/visibility。

本次无后端类、Agent Loop protected 字段、跨类私有访问、System 拓扑、网络协议或持久化格式变化，无新增依赖。已按任务文件 v2 清单实施源码，尚未运行构建、类型检查或应用验收。

### 重新生成的前端局部历史截断（2026-10-15）

新增接口均属于既有前端状态/请求链路，不改变后端 Agent Loop 类关系或生命周期所有权：

| 归属 | 新增/调整接口 | 责任 |
|---|---|---|
| `features/chat/types.ts` | `RegenerateTrimPayload` | 既有 SYSTEM JSON 截断载荷的前端静态类型，无持久化或新 wire 字段 |
| `features/chat/regenerateTrim.ts` | `isRegenerateTrimPayload(value)` | 纯守卫，严格确认索引数量关系与 suffix 类型，无 I/O、状态或运行时查询 |
| `ChatRuntimeController` | `applyRegenerateTrim(sessionId, trim)` | 会话先检、取消旧历史请求、同步委托 Store；缺目标 user 骨架时按新代际补取 |
| `ChatRuntimeState` | `trimHistoryForRegeneration(trim)` | 单次状态提交截断骨架/正文/实时尾部及关联，保留前缀、草稿和当前活动；返回新 generation |
| `ChatRuntimeState` | `cancelOptimisticMainSessionActivity(activityId)` | 只清理精确匹配、仍 provisional 且语义为空的本地活动，不清已被实际流或轮询收编的状态 |
| `ChatRuntimeState` | `replaceSkeleton(rows, historyCount)` | 不再隐式清空同代际新到的实时映射及待结束流，历史结构边界负责旧流失效 |
| `useWebSocket` | 截断通知路由与重新生成请求归属 ref | 严格会话双检、帧缓冲取消、同步删除；本地请求序号/socket/目标索引关联 HTTP 终态，截断确认后请求失败不清服务端活动 |

工具请求按 skeleton 行和 `tool_call_id` 定位，结果用 `toolCard.result.historyIndex` 校验范围；实时结果无索引只可引用同请求的正典结果证据，无法证明时使正文与 loaded 标记失效而非保留旧工具附件。generation 复用既有 History 请求、活动轮询和滚动取消边界，无第二份 History 或活动真相源。

本次未新增 Application/AsyncSystem、Agent Loop protected 字段、跨类私有访问、后端接口、依赖或存储版本；通用自动重连策略不变，漏通知且数量未下降的恢复问题明确延期。源码已按 PLAN v2.1 实施并定向静态审阅，未运行类型检查、构建或应用，用户验收仍待完成。

### 对象工具与四阶段执行迁移（2026-10-15，权威）

> 本节按 `.tasks/2026-10-14_3_oop-tool-lifecycle.md` 的计划 v8 记录当前源码契约；本节与文末顺序均为追加，未改写本文件其余历史章节。前文继承关系图、字段归属表 `_toolsets` 行与 S10/S20 两节描述迁移前实现，已在该节顶部统一标注。

**运行时类与四阶段**

- `abstract/tools/tool.py` 新增运行时类，均为带方法/显式构造的非持久化对象，不进入 easysave，也不是 `BaseModel`：
  - `BaseTool`（ABC）：声明 `name`、`toolset`、`schema`、`is_async`、`description`、`max_result_size_chars`、`dynamic_schema_overrides`、`danger_level`、`no_timeout`、`availability`、`resets_turn_counter`、`accepts_following_calls`、`check_fn`、`requires_env`；阶段方法为 `before_handle(execution)`（工具调用前）、抽象 `handle(execution)`（工具主体，返回 `ToolHandlerResult`）、`after_handle(execution)`（工具调用后处理，默认返回空 `ToolPostprocessEffect`），另有 `ensure_arguments()`。
  - `BaseToolSet`：工具集对象，持有 `tools: tuple[BaseTool, ...]`、`description`、`usage_guide`、`loaded_by_default`、`check_fn`、`requires_env`；构造时校验每个工具的 `toolset` 与集合名一致；`preheat()` 在注册时对每个声明执行一次可用性检查，不启动浏览器/语言服务器等重量资源。
  - `ToolExecution`：单次调用材料，字段为 `tool`、`arguments`、`context`、`tool_call_id`、`result`、`state`、`body_executed`、`body_completed_normally`、`history_index`、`result_message`；材料属于单次调用，禁止写入共享工具实例、Application 或持久化存储。
  - `ToolHandlerResult(result, state)`、`ToolPostprocessEffect`（`suppress_tool_result_event`、`discarded_tool_call_ids`、`replacement_result`、`stop_current_round`、`loop_replaced`、`evolution_requested`、`completion_message`）。
- `entity/puretype/tool.py::ToolBatchDecision`（消息前纯类型）承载 `accepted`、`discarded`、`cutoff_tool_call_id`；由 `ToolRegistry.plan_tool_batch()` 生成，声明边界在审批与执行前确定。

**注册表与发现**

- `abstract/tools/registry.py::ToolRegistry`（依赖 RuntimeSystem 的 AsyncSystem）：`_tools: dict[str, BaseTool]` 直接保存对象，`_toolsets: dict[str, BaseToolSet]` 直接保存工具集对象，`_tool_names_by_toolset: dict[str, set[str]]` 是运行期成员唯一索引（不从声明 `tuple` 猜测 MCP 当前成员），`_preheated_toolsets` 保证每个声明对象只预热一次。
- 写入入口：`register_toolset(toolset: BaseToolSet, *, merge: bool = False)` 装载或合并声明（分布式声明传 `merge=True` 合并描述/usage_guide/check_fn/requires_env），`register_tool(tool: BaseTool, *, replace: bool = False)` 供 MCP 动态刷新传 `replace=True` 原子替换同名工具；跨工具集名称冲突快速失败。查询入口为 `get_tool`/`get_toolset`，不存在 `get_entry`/`get_toolset_entry` 或函数式 `register`。
- `abstract/tools/toolsets_meta.py`：固定 `BaseToolSet` 对象元数据（`BUILTIN_TOOLSETS`），经 `register_builtin_toolset_descriptions(registry)` 以 `register_toolset(toolset, merge=True)` 合并。
- `abstract/tools/discover.py::ToolDiscoverySystem`（依赖 Runtime、ToolRegistry、Sandbox、ShellManager、AgentspaceService、SessionMetadataService、ApprovalSystem、LSPManager、BrowserSystem、ModalityCapabilitySystem、CronRouter、SessionManager、SubAgentOrchestrator、DynamicEndpointSystem、MCPSystem）：AST 只识别顶层固定名称 `TOOLSET`（常量 `entity/constant/tools.py::TOOLSET_DECLARATION_NAME`），显式拒绝 `register_tools` 函数、`abstract.tools.ui_event_router` 导入、`registry` 全局导入与导入期 `register`/`register_tool`/`register_toolset` 调用；扫描顺序为内置五包→可选 custom_tools→MCP 管理模块→工具集元数据。

**阶段执行链与跨模块访问**

- `entry/tool_execution.py::accept_tool_batch(response, registry, sink, session_id, stream_id)` 在 assistant 消息提交前调用 `registry.plan_tool_batch()`，只保留接受前缀，被丢弃项经 `sink.emit_tool_calls_discarded(...)` 发送 `tool_calls_discarded`（携带 `session_id`/`stream_id`/`tool_call_ids`），返回只含 accepted 的 `LLMResponse` 副本。
- `ToolRegistry.async_dispatch(execution)` 只执行 before/handle，写回 `body_executed`/`body_completed_normally`/`result`/`state`；主体业务异常转为 error 且保持 `body_completed_normally=False`，after 不执行；生命周期异常传播。`ToolRegistry.async_postprocess(execution)` 在结果提交后托管 after，与 dispatch 复用同一 TaskOwner、ThreadPoolExecutor 与真实同步 Future。
- `entry/tool_post_dispatch.py`：`PreparedToolResult`（`BaseModel`）持有 `execution`、`message`、`update_result_payload()`、`mark_appended`/`mark_persisted`/`abort`/`emit(sink)`；`ToolPostprocessor.after_committed(prepared, sink)` 仅在 `execution` 非空且 `body_completed_normally=True` 时请求 `registry.async_postprocess(execution)`，校验已提交身份、要求 suppress 必须显式 discard、要求 replacement 仍在 History 中并保留耗时/输入预订元信息。主会话 `ToolExecutor` 与子会话 Loop 各持一个实例。
- `entry/tool_pairing.py` 是共享中断配对辅助，只导入 `entity.messages`、`entity.puretype.llm.ToolCallRequest` 与 `entity.puretype.Role`，不导入 `entry.tool_executor` 或 `entry.base_agent_loop`，提供 `interrupted_tool_result()` 与 `collect_unexecuted_tool_results()`，避免 BaseAgentLoop↔ToolExecutor 循环。`tool_executor.py` 的中断结果构造改为从该模块导入。
- Loop 写回：`store_tool_result()` 在 History add/save 成功后把返回索引写入 `execution.history_index`、把真实 `PreparedToolResult.message` 写入 `execution.result_message`；`stop_current_round=True` 的四类 Loop 使用 `ToolBatchDecision.accepted` 计算已执行 ID、写入未执行 accepted 调用的中断配对结果后保存并结束本轮；被 discarded 的 `tool_call_id` 永不补齐。

**MCP 对象化**

- `abstract/mcp/client.py`：`MCPToolSet(BaseToolSet)` 只声明 `mcp-{server}` 元数据、不持有连接；`MCPTool(BaseTool)` 把远端操作桥接进统一四阶段，`handle()` 调用无状态 `_make_tool_handler()` factory。参数剥离（`TOOL_INTERNAL_ARG_KEYS`）、schema 规范化、断路器、连接与原生资源仍由 `MCPCore` 持有。
- `_register_server_tools()` 用 `registry.register_tool(MCPTool(...), replace=True)` 注册远程工具与资源/提示词辅助工具，跨 toolset 名称冲突快速失败，`mcp-{server}` 与裸 server 名别名保留。刷新在同名同集锁内替换，只注销新集合中已消失的名称（含 utility），在途 `execution` 继续持有原实例。
- `component/mcp_tools.py::MCPRefreshTool`（`toolset="mcp"`、`is_async=True`、`safe`、`MAIN`）经 `execution.context.app.get_system(MCPSystem).refresh()` 刷新；顶层 `TOOLSET = BaseToolSet(name="mcp", tools=(MCPRefreshTool(),))`。对外工具名 `MCPRefresh` 不变。

**System 拓扑**

- `system/application.py::_build_system_manifest()` 删除 `UIEventRouter` 后为 **20 个 System**：RuntimeSystem、SubprocessRunner、Sandbox、ShellManager、AgentspaceService、LLMProfileStore、SessionMetadataService、ApprovalSystem、FrontendSink、ToolRegistry、LSPManager、BrowserSystem、ModalityCapabilitySystem、CronRouter、SessionManager、SubAgentOrchestrator、DynamicEndpointSystem、MCPSystem、ToolDiscoverySystem、GatewaySystem；除该拆除外依赖与关闭顺序不变。`abstract/tools/ui_event_router.py`、`HandlerToolAdapter`、`finalize_tool_result`、`get_toolset_entry` 均已从源码移除。

**状态边界**

- 上述为源码实施与定向静态复核结果；本轮未运行测试、校验、类型检查、构建、导入或应用，未读取或修改 `workspace/`，Git 仅使用 `diff`/`log`。完整任务复核与用户验收仍待完成，不得据此宣称可启动或已通过运行验证。前端压缩后的 History 结构交接存在待批准的偏差（主流程已返回 PLAN 记录），不属于本节已定契约。

### 独立历史更新指令（2026-10-15，批准后的局部修订）

本次合并保留远程重新生成的局部截断与请求归属，同时保留本地历史更新完整重载。前节关于“重连恢复问题延期”的描述属于远程改动当时的边界；合并后由本节记录的onOpen首次同步完整重载处理，不删除或替换局部regenerate_trim路径。以上为静态合并结果，尚未运行验证。

前节“待批准”的历史状态由本节及任务文件19:42:55/19:52:42局部修订覆盖。`entity.puretype.ws.HistoryUpdatedEvent`是仅含固定`history_updated`与非空session_id的strict/frozen消息前纯类型，经puretype显式导出；`AgentSink.emit_history_updated(session_id)`由FrontendSink沿现有TaskOwner发送边界投递，ParentAgentSink不向父主会话投递子History变化。无新System、持久化字段或存储版本。

`ToolExecution`新增调用级`history_updated`及同步`mark_history_updated()`；两压缩工具必要保存成功后无await登记该事实。`ToolPostprocessEffect.system_message`保存原系统完成通知，不与assistant`completion_message`混用。ToolPostprocessor在正常返回后的结果回填保存之后、普通结果/新索引关联之前发送更新指令，再发系统完成通知；取消或后续失败也根据已提交事实尝试通知并传播原异常，通知失败并组保留。内部移除ID仅校验suppress，不再由Postprocessor发tool_calls_discarded；批次后缀仍由accept_tool_batch单独发。

前端Controller新增重载请求记录，Store新增historyReloadRequired、invalidateHistory及applyHistoryReload。旧请求/缓存/链接在指令边界失效，新快照原子安装不删除后到实时行/链接；草稿/排队输入/会话业务状态保留。initialize、history_sync和页/资源入口复用当前重载，失败重试不二次清新流；onOpen记录首次同步边界，使同session重连也完整加载历史。网络不承诺可靠通知，重连不恢复未提交流片段。本修订已实施源码，尚未运行校验、构建或用户验收。

### 会话 Tab 能力探测（2026-10-17）

`SessionTabCapabilities` 是 `entity/puretype/session.py` 中的非持久化纯响应模型，由 Gateway 返回媒体实例计数和变量 Tab 可见内容标志。`BaseAgentLoop.get_session_media_count()` 通过 `entry/history_media.py::count_history_media()` 只读遍历 History；Gateway 通过公开方法访问，不读取 protected 字段，不改变 `IMainSessionLoop` 或 Application/System 拓扑。`SessionVariableService.has_visible_content()` 是 `AgentspaceService` 持有的无缓存叶服务公开入口，复用变量扫描预算并按值文件、`.json.meta`、节点/顶层问题和 `scan_complete` 判定可见内容；Gateway 通过 `get_system(AgentspaceService).session_variables` 在线程池调用。

前端 `useSessionTabCapabilities` 通过 `GET /api/sessions/{id}/tab-capabilities` 获取轻量状态，按 sessionId/generation 丢弃迟到响应，使用 History 低频信号和变量 Agentspace 事件去抖刷新。首次未知、会话切换和失败时禁用目标 Tab；同会话后台 refreshing 保留已确认快照，成功确认空内容后由 `useTabSystem` 触发现有 active-tab 回退。`fetchJsonWithTimeout` 的可选 `createHttpError` 只被新能力 API 使用，既有调用方未传该选项时保持原行为。无新增 protected 字段、持久化版本、System 或测试源。

### 会话文件修改记录（2026-10-17）

本节记录文件修改 Tab 的当前所有权；对象工具迁移章节删除UIEventRouter后的20个System仍为权威拓扑，早期章节的21个System仅属历史阶段，本次不改写那些历史段落。

| 归属 | 新字段/公开接口 | 生命周期与外部访问 |
|---|---|---|
| AgentspaceService | `_file_changes: SessionFileChangeStore`、只读 `file_changes` | virtual_awake只构造一个无后台任务的Store；工具与Gateway通过公开属性取得 |
| SessionFileChangeStore | `_cache`、`_locks`、`_registry_lock`、`_closed_sessions`；record_success/get_summary/get_page/block_session/unblock_session/forget_session | 每主会话RLock保护候选保存与缓存发布；删除封闭与缓存/锁不通过外部protected访问修改 |
| ToolExecution | `_cancel_requested: threading.Event`；mark_cancelled/cancel_requested | 单次非持久化取消事实；ToolRegistry取消出口登记，记录器只读公开属性，不改变真实Future所有权 |
| FileChangeRecorder | 固定工具调用的主会话、修改者与Store引用 | 只通过ToolContext.resource_session_id/session_id/character_name及公开Loop角色接口，迟到工作不重查旋转后的ID |
| Sandbox | copy/copy_folder/move返回ResolvedPath | 文件工具消费真实shutil返回目的，调用者可忽略新增返回值；权限和命名空间装配不变 |
| Gateway | 两条文件修改只读GET、受现有TaskOwner管理的删除REQUEST与删除scope | GET不创建Loop；删除先封闭再拆除，取消仍观察真实线程并按会话是否已删解封/保留封闭 |

六个纯模型位于 `entity/puretype/session_file_changes.py`，不依赖正式消息类；仅Data/Entry/Actor进入typeref稳定映射，独立 `file_changes.es` 保存BaseModel根，UTC时间为字符串。非持久化Operation不加入History。必要记录失败沿LifecycleFailure触发应用级失败关闭；GET错误不主动上报应用失败。不增加Loop字段、跨类protected访问、AsyncSystem、watcher或WebSocket类型。

前端新状态唯一持有者为 `useTabSystem` 内的 `useSessionFileChanges`，正式Tab与预览经同一渲染上下文读取；既有TabDataProvider四类Hook仍各自唯一。注册表十项，摘要串行轮询与分页分别维护请求代际，切会话同步隐藏旧快照。当前只完成源码和定向只读复核，尚无运行验收结论。

### 文件修改目录树状态修订（2026-10-18）

`SessionFileChangeEntry.display_state`是持久化当前生命周期状态：`created`、`modified`或`deleted`。Store保留deleted条目但摘要/分页只投影可见文件，父目录由前端纯函数合成。首次创建/复制目的/移动目的为created；created文件继续修改保持created；删除隐藏；删除后同路径再次创建/复制目的/移动目的为modified。Move源隐藏、目的按是否有历史决定颜色状态。最后操作仍单独由`last_operation`徽章显示，不能用它替代display_state。

一次激活的文件修改Tab在完整可见分页全部到达且revision一致后才替换目录树；目录节点只读可折叠，文件节点按display_state使用绿色/黄色/隐藏规则。目录目标不产生可见条目，操作总数仍包括隐藏删除；无可见文件时Tab禁用或显示空态。


