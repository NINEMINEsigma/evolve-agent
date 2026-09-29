import type {
  ChatMessage,
  MessageContent,
  MessageMetrics,
  ToolCardStatus,
} from "../../types";

export type HistoryRowKind = "message" | "tool_card";

export interface HistorySkeletonRowDto {
  row_id: string;
  history_index: number;
  row_kind: HistoryRowKind;
  role: string;
  character_name?: string | null;
  tool_index?: number | null;
  tool_call_id?: string | null;
  is_system_status: boolean;
}

export interface HistoryToolCardDto {
  tool_call_id: string;
  tool_name: string;
  request_args: Record<string, unknown>;
  request_args_raw?: string | null;
  status: ToolCardStatus;
  result_content?: MessageContent | null;
  result_history_index?: number | null;
  tool_call_meta?: import("../../types").ToolCallMeta | null;
  embedded_messages?: import("../../types").EmbeddedToolMessage[] | null;
  is_error: boolean;
}

export interface HistorySkeletonResponseDto {
  session_id: string;
  start_index: number;
  history_count: number;
  row_count: number;
  rows: HistorySkeletonRowDto[];
}

export interface HistoryContentRowDto extends HistorySkeletonRowDto {
  content: MessageContent;
  visible_characters?: string[] | null;
  response_characters?: string[] | null;
  message_suffix?: string | null;
  dynamic_message_suffix?: string | null;
  reasoning_content?: string | null;
  requires_response?: boolean | null;
  tool_card?: HistoryToolCardDto | null;
  tool_name?: string | null;
  tool_args?: Record<string, unknown> | null;
  tool_args_raw?: string | null;
  tool_call_meta?: import("../../types").ToolCallMeta | null;
  metrics?: MessageMetrics | null;
}

export interface HistoryPageResponseDto {
  session_id: string;
  start_index: number;
  end_index: number;
  history_count: number;
  rows: HistoryContentRowDto[];
}

export interface HistoryImageResourceDto {
  resource_id: string;
  url: string;
  alt: string;
}

export interface HistoryDownloadResourceDto {
  resource_id: string;
  url: string;
  filename: string;
  size?: number | null;
}

export interface HistoryResourcesResponseDto {
  session_id: string;
  history_count: number;
  images: HistoryImageResourceDto[];
  downloads: HistoryDownloadResourceDto[];
}

export interface ChatHistoryRow {
  skeleton: HistorySkeletonRowDto;
  message?: ChatMessage;
}

export interface ChatHistoryPageError {
  key: string;
  startIndex: number;
  endIndex: number;
  message: string;
  retryable: boolean;
}

export type ChatFollowMode =
  | "initializing"
  | "following"
  | "detached"
  | "minimap_dragging"
  | "returning";

export interface ChatVisibleRange {
  startIndex: number;
  endIndex: number;
}

export interface ChatScrollMetrics {
  scrollTop: number;
  scrollHeight: number;
  viewportHeight: number;
}

export interface ChatMinimapSegment {
  id: string;
  role: string;
  weight: number;
  startRatio: number;
  endRatio: number;
}

export interface LiveChatRow {
  id: string;
  version: number;
  message: ChatMessage;
  streaming: boolean;
  frozen: boolean;
  activityId?: string;
  activityPlaceholder?: boolean;
  provisional?: boolean;
  preserveExpanded?: boolean;
  collapseManuallyChanged?: boolean;
}

export interface PendingStreamFinish {
  streamId: string;
  content?: string;
  metrics?: import("../../types").MessageMetrics;
  finishReason?: string;
}

export interface StreamBatch {
  streamId: string;
  characterName?: string;
  delta: string;
  reasoningDelta: string;
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  toolArgsRawMap?: Record<string, string>;
  activeToolCallKey?: string;
}

export interface PendingChatMessage {
  content: MessageContent;
  timestamp: number;
}

export type ChatTelemetryEventKind =
  | "stream_batch"
  | "history_request"
  | "history_response"
  | "history_cancel"
  | "history_timeout"
  | "visible_range"
  | "follow_mode"
  | "initial_bottom"
  | "return_to_bottom"
  | "render_latency"
  | "long_task"
  | "event_timing"
  | "dom_sample"
  | "stage_probe"
  | "stage_reload";

export interface ChatTelemetryEvent {
  time: number;
  kind: ChatTelemetryEventKind;
  durationMs?: number;
  count?: number;
  charCount?: number;
  startIndex?: number;
  endIndex?: number;
  followMode?: ChatFollowMode;
  status?: number;
  phase?: import("../../types").ClientDiagnosticPhase;
  domCount?: number;
  iframeCount?: number;
}

export interface ChatTelemetryReport {
  version: 1;
  startedAt: string | null;
  stoppedAt: string | null;
  userAgent: string;
  events: ChatTelemetryEvent[];
}
