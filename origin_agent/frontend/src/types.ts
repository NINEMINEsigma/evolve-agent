export interface FileEntry {
  name: string;
  type: "file" | "dir";
}

export interface OpenTab {
  id: string;
  path: string;
  name: string;
  content: string;
  originalContent: string;
  isDirty: boolean;
  language: string;
}

export interface TextContentBlock {
  type: "text";
  text: string;
}

export interface ImageContentBlock {
  type: "image_url";
  image_url: { url: string };
}

export type ContentBlock = TextContentBlock | ImageContentBlock;
export type MessageContent = string | ContentBlock[];

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
  | "ping"
  | "pong";

export interface WSMessage {
  type: MessageType;
  session_id?: string;
  content?: MessageContent;
  message?: string;
  tool?: string;
  args?: Record<string, unknown>;
  result?: string;
  request_id?: string;
  approved?: boolean;
  action?: string;
  question?: string;
  options?: Array<{ label: string; value: string }>;
  option?: string;
  custom_text?: string;
  stream_id?: string;
  delta?: string;
  reasoning_delta?: string;
  finish_reason?: string;
  target_sessions?: string[];
  visible_characters?: string[];   // 多 Agent 模式：可见角色列表
  response_characters?: string[];  // 多 Agent 模式：需响应角色列表
  character_name?: string;
  index?: number;
  client_message_id?: string;
  tool_call_meta?: ToolCallMeta;   // TOOL_RESULT：工具调用时间元信息
  emoji?: string;                  // 工具调用/审批请求的图标
}

export interface ToolCallMeta {
  application_time: string;         // 人类可读的申请时间，如 "2026-07-11 14:30:25.123"
  application_time_ms: number;      // 绝对毫秒时间戳
  approval_duration_ms: number;     // 审批耗时（毫秒），readonly 工具为 0
  invocation_start_offset_ms: number; // 从申请到开始调用 handler 的毫秒偏移
  invocation_duration_ms: number;   // handler 实际执行的毫秒数
  end_time_offset_ms: number;       // 从申请到工具调用完成的毫秒偏移
}

export interface ConfirmRequest {
  request_id: string;
  content: string;
  command?: string[];
  reason?: string;
  tool?: string;
  emoji?: string;
}

export interface AskRequest {
  request_id: string;
  question: string;
  options?: Array<{ label: string; value: string }>;
}

export interface DownloadInfo {
  url: string;
  filename: string;
  description?: string;
  size?: number;
}

export interface PlaylistEntry {
  audio_url: string;
  mime: string;
  size: number;
  title: string;
  path?: string | null;
  url?: string | null;
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
  imageMarkdown?: string;
  downloadInfo?: DownloadInfo;
  audioUrl?: string;
  audioAutoplay?: boolean;
  playlist?: PlaylistEntry[];
  playlistAutoplay?: boolean;
  reasoningContent?: string;
  reasoningDuration?: number;
  characterName?: string;
  visibleCharacters?: string[];
  requiresResponse?: boolean;
  responseCharacters?: string[];
  messageSuffix?: string;
  dynamicMessageSuffix?: string;
  toolCallMeta?: ToolCallMeta;   // 工具调用时间元信息
  emoji?: string;                  // 工具调用/审批请求的图标
  isError?: boolean;               // 工具结果是否为错误
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
  emoji?: string;
}

export interface SubagentSession {
  session_id: string;
  name: string;
  status: "running" | "waiting" | "completed" | "terminated";
  feedback: SubagentMessage[];
  pending_approvals: PendingApproval[];
}

export interface TargetSessionOption {
  id: string;
  name: string;
  status?: SubagentSession["status"];
}
