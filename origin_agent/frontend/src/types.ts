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
  | "agent_message"
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
  allow_custom?: boolean;
  option?: string;
  custom_text?: string;
  stream_id?: string;
  delta?: string;
  reasoning_delta?: string;
  finish_reason?: string;
}

export interface ConfirmRequest {
  request_id: string;
  content: string;
  command?: string[];
  reason?: string;
  tool?: string;
}

export interface AskRequest {
  request_id: string;
  question: string;
  options?: Array<{ label: string; value: string }>;
  allow_custom?: boolean;
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
  role: "user" | "agent" | "system" | "error" | "tool";
  content: MessageContent;
  id: string;
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
}

export interface SubagentSession {
  session_id: string;
  name: string;
  status: "running" | "waiting" | "completed" | "terminated";
  feedback: SubagentMessage[];
  pending_approvals: PendingApproval[];
}