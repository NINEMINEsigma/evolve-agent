export type AgentspaceEntryKind = "file" | "dir";

export interface DynamicSandboxSpace {
  name: string;
  path: string;
  description: string;
  is_readonly: boolean;
}

export type DynamicSandboxSpaceWithAvailability = DynamicSandboxSpace & {
  available: boolean;
};

export interface DynamicSandboxSpacesResponse {
  spaces: DynamicSandboxSpaceWithAvailability[];
}

export interface DynamicSandboxDirectoryPickResponse {
  selected: boolean;
  path: string | null;
}

export interface FileEntry {
  name: string;
  path: string;
  kind: AgentspaceEntryKind;
}

export interface DirectoryState {
  entries: FileEntry[];
  loading: boolean;
  error: string | null;
}

export type DirectoryStateMap = Record<string, DirectoryState>;

export interface FileSnapshot {
  path: string;
  content: string;
  version: string;
  size: number;
  modified_ns: number;
  operation_id?: string;
}

export interface FileLockOwner {
  owner_id: string;
  session_id: string;
  character_name: string;
  round_id: string;
}

export interface FileLock {
  path: string;
  recursive: boolean;
  owners: FileLockOwner[];
}

export type AgentspaceEventKind =
  | "created"
  | "modified"
  | "deleted"
  | "moved"
  | "locks"
  | "trash_changed"
  | "resync"
  | "watcher_error";

export interface AgentspaceEvent {
  sequence: number;
  kind: AgentspaceEventKind;
  source: "service" | "watcher" | "locks" | "system";
  path: string | null;
  new_path: string | null;
  is_directory: boolean | null;
  locks: FileLock[] | null;
  timestamp: string;
  operation_id: string | null;
  version: string | null;
  message: string | null;
}

export interface TrashEntry {
  entry_id: string;
  state: "ready" | "recoverable" | "corrupt";
  original_path: string | null;
  name: string | null;
  kind: AgentspaceEntryKind | null;
  deleted_at: string | null;
  size: number;
  error: string | null;
}

export interface ExternalConflict {
  kind: "modified" | "deleted";
  diskContent: string | null;
  diskVersion: string | null;
  detectedSequence: number;
}

export interface OpenTab {
  id: string;
  path: string;
  name: string;
  content: string;
  originalContent: string;
  isDirty: boolean;
  language: string;
  version: string;
  modifiedNs: number;
  isLocked: boolean;
  lockOwners: FileLockOwner[];
  conflict: ExternalConflict | null;
}

export type EntrySelection = { path: string; kind: AgentspaceEntryKind } | null;
export type CursorPosition = { line: number; column: number };
export type DirtyCloseDecision = "save" | "discard" | "cancel";
export type TrashDirtyDecision = "save-all" | "discard-all" | "cancel";
export type DangerousDecision = "confirm" | "cancel";
export type SyncState = "connecting" | "live" | "degraded";
export type AgentspaceErrorState = {
  message: string;
  retry: (() => Promise<void>) | null;
} | null;

export type AgentspaceDialogState =
  | { kind: "create-file"; parentPath: string }
  | { kind: "create-folder"; parentPath: string }
  | { kind: "rename"; entry: FileEntry }
  | { kind: "close-dirty"; tabId: string }
  | { kind: "trash-dirty"; path: string; tabIds: string[] }
  | { kind: "purge-trash"; entryId: string; displayName: string }
  | { kind: "empty-trash"; count: number };

export interface TextContentBlock {
  type: "text";
  text: string;
}

export interface ImageContentBlock {
  type: "image_url";
  image_url: { url: string };
}

export interface AudioContentBlock {
  type: "input_audio";
  input_audio: { data: string; format: string };
}

export interface VideoContentBlock {
  type: "video_url";
  video_url: { url: string };
}

export type ContentBlock = TextContentBlock | ImageContentBlock | AudioContentBlock | VideoContentBlock;
export type MessageContent = string | ContentBlock[];
export interface EmbeddedToolMessage {
  role: "user";
  character_name?: string;
  source?: string;
  timestamp?: string;
  content: MessageContent;
}

export type MainSessionActivitySource =
  | "user_message"
  | "dynamic_endpoint"
  | "subagent_feedback"
  | "cron"
  | "regenerate"
  | "resume"
  | "other"
  | "mixed";

export type MainSessionActivityPhase =
  | "queued"
  | "preparing"
  | "waiting_first_token"
  | "streaming"
  | "waiting_approval"
  | "waiting_tool";

export interface MainSessionActivitySnapshot {
  activity_id: string;
  revision: number;
  source: MainSessionActivitySource;
  phase: MainSessionActivityPhase;
  stream_id?: string | null;
  character_name?: string | null;
}

export interface SessionRuntimeStatus {
  session_id: string;
  exists: boolean;
  occupied: boolean;
  processing: boolean;
  activity?: MainSessionActivitySnapshot | null;
}

export type ApprovalMode = "manual" | "handsfree" | "yolo";
export type ApprovalModeSyncStatus = "loading" | "ready" | "unavailable";

export type ToolCardStatus = "running" | "succeeded" | "failed" | "missing_result";

export interface ToolCardRequest {
  toolCallId: string;
  toolName?: string;
  args?: Record<string, unknown>;
  argsRaw?: string;
}

export interface ToolCardResult {
  content: MessageContent;
  imageMarkdown?: string;
  downloadInfo?: DownloadInfo;
  toolCallMeta?: ToolCallMeta;
  embeddedMessages?: EmbeddedToolMessage[];
  isError?: boolean;
  historyIndex?: number;
}

export interface ToolCardData {
  request: ToolCardRequest;
  status: ToolCardStatus;
  result?: ToolCardResult;
}

/** WebSocket 入站消息的全部 type 字面量（与 constants/ws.ts::WS_IN 对应）。 */
export type MessageType =
  | "system"
  | "user_message"
  | "assistant_message"
  | "tool_call"
  | "tool_result"
  | "task_progress"
  | "clipboard_display"
  | "confirm_request"
  | "ask_request"
  | "stream_delta"
  | "stream_done"
  | "error"
  | "subagent_update"
  | "history_sync"
  | "llm_profile_changed"
  | "approval_profile_changed"
  | "metadata_profile_changed"
  | "modality_profile_changed"
  | "agentspace_event"
  | "client_diagnostic"
  | "handsfree_mode"
  | "ping"
  | "pong";

/**
 * 非流式事件的 type 集合：在 MessageType 基础上显式排除 stream_delta/stream_done。
 * 流式事件由 StreamDeltaEvent / StreamDoneEvent 承载各自的 type 字面量，
 * 非流式事件类型不得再声明这两个字面量，避免宽类型漏掉流式结构约束。
 */
export type NonStreamMessageType = Exclude<MessageType, "stream_delta" | "stream_done">;

/** stream_delta 顶层 tool_call：已确定工具调用的完整结构。 */
export interface StreamToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

/** stream_delta 顶层 tool_call_delta：分片式工具调用增量。 */
export interface StreamToolCallDelta {
  id: string;          // 允许空字符串
  index: number;      // 仅要求整数，不额外限定非负
  name: string;
  args_delta: string;
  phase: "start" | "append" | "done";
}

/**
 * 流式增量事件：后端以具体 BaseModel 序列化下发，进程内无 JSON 往返。
 * 可选字段后端 None 一律省略，不发送 null。
 */
export interface StreamDeltaEvent {
  type: "stream_delta";
  session_id: string;   // 非空
  stream_id: string;    // 非空
  delta?: string;
  reasoning_delta?: string;
  character_name?: string;
  tool_call?: StreamToolCall;
  tool_call_delta?: StreamToolCallDelta;
}

/**
 * 流式结束事件：finish_reason 必填；content 缺失与空字符串语义不同；
 * metrics 沿用现有 MessageMetrics（int,int,int,float，不增加正数约束）。
 */
export interface StreamDoneEvent {
  type: "stream_done";
  session_id: string;   // 非空
  stream_id: string;    // 非空
  finish_reason: string;
  content?: string;
  metrics?: MessageMetrics;
}

export type ClientDiagnosticKind = "critical_request_timeout";
export type ClientDiagnosticPhase =
  | "session_status_precheck"
  | "session_status_recheck"
  | "history_skeleton"
  | "history_page";

export interface ClientDiagnostic {
  kind: ClientDiagnosticKind;
  phase: ClientDiagnosticPhase;
  duration_ms: number;
  websocket_state: string;
  last_recv_age_ms?: number | null;
  last_pong_age_ms?: number | null;
}

export interface HistoryRowLink {
  live_id: string;
  history_row_id: string;
}

/**
 * 非流式 WebSocket 入站消息的统一结构。
 * type 显式排除 stream_delta/stream_done —— 流式事件由
 * StreamDeltaEvent / StreamDoneEvent 承载，不再走此宽类型。
 * 流式专用字段（stream_id/delta/reasoning_delta/finish_reason/metrics）
 * 已移至流式事件类型，此接口不再声明。
 */
export interface NonStreamWSMessage {
  type: NonStreamMessageType;
  session_id?: string;
  content?: MessageContent;
  message?: string;
  tool?: string;
  tool_call_id?: string;                  // TOOL_CALL / TOOL_RESULT：工具调用 ID
  args?: Record<string, unknown>;
  result?: string;
  request_id?: string;
  approved?: boolean;
  action?: string;
  questions?: AskQuestionItem[];      // ASK_REQUEST：多问题表单（分页向导）
  answers?: AskAnswerItem[] | null;   // ASK_RESPONSE：按题回答（null=整表跳过）
  target_sessions?: string[];
  visible_characters?: string[];   // 多 Agent 模式：可见角色列表
  response_characters?: string[];  // 多 Agent 模式：需响应角色列表
  character_name?: string;
  index?: number;
  is_system_status?: boolean;
  client_message_id?: string;
  message_suffix?: string;                // USER_MESSAGE：持久化上下文扩展块
  dynamic_message_suffix?: string;        // USER_MESSAGE：当轮动态上下文扩展块
  tool_call_meta?: ToolCallMeta;   // TOOL_RESULT：工具调用时间元信息
  embedded_messages?: EmbeddedToolMessage[]; // TOOL_RESULT：工具结果中的隐藏嵌入消息
  consumed_client_message_ids?: string[];   // TOOL_RESULT：被工具链消费的用户消息 client_message_id 列表（用于移除已排队徽章）
  danger_level?: string;           // CONFIRM_REQUEST：工具危险等级
  client_info?: Record<string, string>;   // USER_MESSAGE：前端客户端信息
  llm_profile_name?: string;                   // USER_MESSAGE：当前 Profile 名称，空字符串=无配置
  operation?: "renamed" | "deleted";          // LLM_PROFILE_CHANGED
  old_name?: string;
  new_name?: string | null;
  approval_profile_name?: string | null;    // APPROVAL_PROFILE_CHANGED
  approval_profile_model?: string | null;   // APPROVAL_PROFILE_CHANGED
  approval_profile_available?: boolean;     // APPROVAL_PROFILE_CHANGED
  metadata_profile_name?: string | null;    // METADATA_PROFILE_CHANGED
  metadata_profile_model?: string | null;   // METADATA_PROFILE_CHANGED
  metadata_profile_available?: boolean;     // METADATA_PROFILE_CHANGED
  modality_vision_image_profile_name?: string | null; // MODALITY_PROFILE_CHANGED
  modality_vision_image_profile_model?: string | null;
  modality_vision_image_profile_available?: boolean;
  modality_audio_profile_name?: string | null;
  modality_audio_profile_model?: string | null;
  modality_audio_profile_available?: boolean;
  modality_vision_video_profile_name?: string | null;
  modality_vision_video_profile_model?: string | null;
  modality_vision_video_profile_available?: boolean;
  handsfree_mode?: boolean;                  // HANDSFREE_MODE：服务端权威回执（向后兼容）
  approval_mode?: ApprovalMode;             // HANDSFREE_MODE：服务端权威审批模式（manual/handsfree/yolo）
  history_count?: number;                    // HISTORY_SYNC：当前正典 History 消息数
  processing?: boolean;                      // HISTORY_SYNC：主会话是否正在处理
  token_usage?: number;                      // HISTORY_SYNC：累计 token
  context_tokens?: number;                   // HISTORY_SYNC：当前上下文 token
  agents?: string[] | null;                  // HISTORY_SYNC：多Agent参与角色
  agentspace_event?: AgentspaceEvent;        // AGENTSPACE_EVENT：聊天页视觉资源变化
  client_diagnostic?: ClientDiagnostic;      // CLIENT_DIAGNOSTIC：脱敏传输诊断
}

/**
 * WebSocket 入站消息的判别联合：流式事件使用具体结构化类型，
 * 其余沿用 NonStreamWSMessage。以 message.type 字面量收窄区分。
 */
export type WSMessage = StreamDeltaEvent | StreamDoneEvent | NonStreamWSMessage;

export interface ToolCallMeta {
  application_time: string;         // 人类可读的申请时间，如 "2026-07-11 14:30:25.123"
  application_time_ms: number;      // 绝对毫秒时间戳
  approval_duration_ms: number;     // 审批耗时（毫秒），safe 工具为 0
  invocation_start_offset_ms: number; // 从申请到开始调用 handler 的毫秒偏移
  invocation_duration_ms: number;   // handler 实际执行的毫秒数
  end_time_offset_ms: number;       // 从申请到工具调用完成的毫秒偏移
}

// ── 主会话中断状态机（后端权威）──
export type InterruptStatus = "idle" | "interrupting" | "cancelled" | "failed";

export interface InterruptResponse {
  interrupted?: boolean;
  status?: "idle" | "cancelled" | "timeout" | "failed" | "not_found";
  session_id?: string;
  reason?: string;
  error?: string;
}

export interface MessageMetrics {
  reasoning_duration_ms: number;   // 推理阶段耗时（毫秒）
  content_duration_ms: number;      // 正文阶段耗时（毫秒）
  completion_tokens: number;         // 本轮 LLM 调用的 completion_tokens
  tokens_per_second: number;        // token 输出速度
}

export interface ConfirmRequest {
  request_id: string;
  content: string;
  command?: string[];
  reason?: string;
  tool?: string;
  danger_level?: string;
  args?: Record<string, unknown>;   // CONFIRM_REQUEST：完整工具参数 dict（JsonView 渲染用）
}

export interface AskQuestionItem {
  question: string;
  detail?: string;                   // 该题详细说明（markdown 渲染）
  options?: Array<{ label: string; value: string }>;
  multi_select?: boolean;            // true 时该题可多选（无上限）；默认单选
}

export interface AskAnswerItem {
  selected: string[];
  custom_text: string | null;
}

export interface AskRequest {
  request_id: string;
  questions: AskQuestionItem[];      // 多问题表单（分页向导，末题统一提交/跳过）
}

export interface DownloadInfo {
  url: string;
  filename: string;
  description?: string;
  size?: number;
}

export interface TaskProgress {
  task_id: string;
  label: string;
  current: number;
  total: number;
  percent: number;
  status: string;
}

export interface ClipboardDisplay {
  display_id: string;
  label: string;
  content: string;
}

export interface DynamicEndpoint {
  name: string;
  url: string;
  agent_name: string;
  created_at: number;
}

export interface ShellInfo {
  shell_id: string;
  pid: number | null;
  session_id: string;
  character_name: string;
  shell_type: string;
  cwd: string;
  started_at: number;
  last_activity_at: number;
  running: boolean;
  termination: "natural" | "forced" | "error" | null;
  exit_code: number | null;
}

export interface CronTask {
  task_id: string;
  session_id?: string;
  name: string;
  schedule_type: string;
  schedule_value: string;
  command?: string[];
  next_run: string | null;
  run_count: number;
  max_runs?: number;
  should_schedule: boolean;
  log_path: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system" | "error" | "tool";
  content: MessageContent;
  id: string;
  clientMessageId?: string;
  messageIndex?: number;
  edited?: boolean;
  collapsed?: boolean;
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  toolArgsRawMap?: Record<string, string>;   // 生成期按 tool_call 分缓冲的原始参数 JSON 片段
  activeToolCallKey?: string;                  // 最近有增量活动的 toolArgsRawMap key
  imageMarkdown?: string;
  downloadInfo?: DownloadInfo;
  reasoningContent?: string;
  reasoningDuration?: number;       // 推理耗时（毫秒，后端推送或前端粗算兜底）
  contentDuration?: number;          // 正文耗时（毫秒）
  completionTokens?: number;          // 本轮 completion_tokens
  tokensPerSecond?: number;          // token 输出速度
  characterName?: string;
  visibleCharacters?: string[];
  requiresResponse?: boolean;
  responseCharacters?: string[];
  messageSuffix?: string;
  dynamicMessageSuffix?: string;
  toolCallMeta?: ToolCallMeta;   // 工具调用时间元信息
  embeddedMessages?: EmbeddedToolMessage[]; // 无匹配 tool_call 时的工具结果嵌入消息
  toolCard?: ToolCardData;
  isError?: boolean;               // 工具结果是否为错误
  isSystemStatus?: boolean;        // 系统状态消息（对 LLM 不可见，仅前端展示）
}

export interface CharacterAvatarEntryDto {
  name: string;
  avatar_path: string;
  avatar_url: string | null;
  error: string | null;
}

export interface CharacterAvatarsResponseDto {
  main: CharacterAvatarEntryDto;
  characters: CharacterAvatarEntryDto[];
}

export interface SessionInfo {
  id: string;
  created_at: number;
  status: string;
  title?: string;
  pinned?: boolean;
  last_activity_at?: number;
  parents?: string[];
  parent?: string | null;
  continuation?: string | null;
  tags?: string[];
  loop_type?: string;
}

export interface SessionCluster {
  id: string;
  created_at: number;
  title: string;
  pinned: boolean;
  last_activity_at: number;
  members: SessionInfo[];
}

export type SidebarItem =
  | { kind: "session"; session: SessionInfo }
  | { kind: "cluster"; cluster: SessionCluster };

export interface PendingApproval {
  tool_call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}

export interface SubagentMessage {
  role: string;
  content: string;
  tool_name?: string;
  tool_call_id?: string;
  tool_args?: Record<string, unknown>;
  reasoning?: string;
  character_name?: string;
}

export interface SubagentSession {
  session_id: string;
  name: string;
  status: "running" | "completed" | "terminated";
  feedback: SubagentMessage[];
  pending_approvals: PendingApproval[];
  interactive?: boolean;
}

export interface TargetSessionOption {
  id: string;
  name: string;
  status?: SubagentSession["status"];
}

export interface PendingImage {
  id: string;
  file: File;
  dataUrl: string;
}

export interface PendingAudio {
  id: string;
  file: File;
  dataUrl: string;
  format: string;
}

export interface PendingVideo {
  id: string;
  file: File;
  dataUrl: string;
}

export interface LlmProfile {
  name: string;
  llm_client_name: string;
  base_url: string;
  model: string;
  api_key: string;
  temperature: number;
  max_output_tokens: number;
  reasoning_effort: string;
  max_context_tokens: number;
  vision_image_profile: string | null;
  audio_profile: string | null;
  vision_video_profile: string | null;
  soul_file: string;
}

export type LlmLoadStatus = "loading" | "ready" | "error";
export type SessionLlmSelectionStatus = "idle" | LlmLoadStatus;

export interface SessionLlmProfileState {
  session_id: string;
  profile_name: string | null;
  /** 只表示名称存在，不表示连接已验证。 */
  available: boolean;
}

export interface LlmProfileChangeEvent {
  operation?: "renamed" | "deleted";
  old_name?: string | null;
  new_name?: string | null;
}

export interface LlmProfileDeleteResult {
  deleted: boolean;
  profile_name: string;
  replacement_profile_name: string | null;
  switched_sessions: string[];
  pending_sessions: string[];
  notification_failures: string[];
}

export interface ApprovalProfileState {
  profile_name: string | null;
  model: string | null;
  available: boolean;
}

export interface MetadataProfileState {
  profile_name: string | null;
  model: string | null;
  available: boolean;
}

export type ModalityType = "image" | "audio" | "video";

export interface ModalityProfileState {
  profile_name: string | null;
  model: string | null;
  available: boolean;
}

export interface ModalityProfileStates {
  image: ModalityProfileState;
  audio: ModalityProfileState;
  video: ModalityProfileState;
}

export interface OperationNotice {
  kind: "error" | "warning";
  message: string;
}
