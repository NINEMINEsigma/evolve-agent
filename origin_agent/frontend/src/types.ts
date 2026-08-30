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
  detail?: string;                    // ASK_REQUEST：问题详细说明（markdown）
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
  danger_level?: string;           // CONFIRM_REQUEST：工具危险等级
  client_info?: Record<string, string>;   // USER_MESSAGE：前端客户端信息
  metrics?: MessageMetrics;              // STREAM_DONE：计时元信息
}

export interface ToolCallMeta {
  application_time: string;         // 人类可读的申请时间，如 "2026-07-11 14:30:25.123"
  application_time_ms: number;      // 绝对毫秒时间戳
  approval_duration_ms: number;     // 审批耗时（毫秒），safe 工具为 0
  invocation_start_offset_ms: number; // 从申请到开始调用 handler 的毫秒偏移
  invocation_duration_ms: number;   // handler 实际执行的毫秒数
  end_time_offset_ms: number;       // 从申请到工具调用完成的毫秒偏移
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
  emoji?: string;
  danger_level?: string;
  args?: Record<string, unknown>;   // CONFIRM_REQUEST：完整工具参数 dict（JsonView 渲染用）
}

export interface AskRequest {
  request_id: string;
  question: string;
  detail?: string;                   // 问题详细说明（markdown 渲染）
  options?: Array<{ label: string; value: string }>;
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
  emoji?: string;
}

export interface SubagentSession {
  session_id: string;
  name: string;
  status: "running" | "waiting" | "completed" | "terminated";
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
  uid: string;
  vision_image_profile: string;
  audio_profile: string;
  vision_video_profile: string;
}
