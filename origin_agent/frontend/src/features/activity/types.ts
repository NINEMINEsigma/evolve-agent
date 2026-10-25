export type ActivityEventKind = "message_received" | "agent_response" | "tool_call";
export type ActivityEventPhase = "observed" | "started" | "completed";
export type ActivityEventStatus =
  | "observed"
  | "active"
  | "succeeded"
  | "failed"
  | "denied"
  | "interrupted";

export interface ActivityEvent {
  sequence: number;
  timestamp: string;
  kind: ActivityEventKind;
  phase: ActivityEventPhase;
  status: ActivityEventStatus;
  session_id: string;
  activity_id: string | null;
  input_sequences: number[];
  stream_id: string | null;
  tool_call_id: string | null;
  character_name: string | null;
  tool_name: string | null;
  duration_ms: number | null;
}

export interface ActivityStreamGap {
  type: "gap";
  dropped: number;
  timestamp: string;
}

export type ActivityStreamItem = ActivityEvent | ActivityStreamGap;

export interface ActivityOverview {
  session_count: number;
  active_loop_count: number;
  tool_count: number;
  toolset_count: number;
}

export type ActivityConnectionState =
  | "idle"
  | "connecting"
  | "live"
  | "degraded"
  | "closed";

export interface ActivityObservedCounts {
  events: number;
  messages: number;
  responses: number;
  tools: number;
}
