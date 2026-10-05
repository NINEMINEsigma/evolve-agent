import { WS_IN } from "../../constants/ws";
import type {
  MessageMetrics,
  StreamDeltaEvent,
  StreamDoneEvent,
  StreamToolCall,
  StreamToolCallDelta,
} from "../../types";

/**
 * 流式事件结构守卫。
 *
 * 后端 stream_delta / stream_done 以具体 BaseModel（extra=forbid）序列化下发，
 * 进程内无 JSON 往返；前端在 WebSocket 边界以 unknown 实际校验后再判别联合收窄。
 * 非法流式载荷丢弃并输出不含正文/参数的诊断，不得静默成为其他消息或污染 store。
 *
 * 约定（对齐后端 entity/puretype/ws.py 与 llm.py）：
 * - session_id / stream_id 必须为非空字符串（Field(min_length=1)）。
 * - 可选字段后端 None 一律省略，不发送 null；出现即视为非法。
 * - StreamDeltaEvent 后端 extra=forbid：出现非约定字段（含旧版 content 内嵌 JSON）
 *   必须拒绝，不能作为无工具事件静默通过。
 * - tool_call.id / tool_call_delta.id 后端仅 str，允许空字符串；守卫不额外限制非空。
 * - tool_call_delta.index 仅要求整数，不额外限定非负。
 * - metrics 沿用现有 MessageMetrics（int,int,int,float），不增加正数约束。
 */

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === "string";
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function isStringRecord(value: unknown): value is Record<string, unknown> {
  return isObject(value);
}

/** StreamDeltaEvent 约定的可选键；其余键（含旧版 content）一律拒绝。 */
const STREAM_DELTA_KEYS = new Set([
  "type", "session_id", "stream_id", "delta", "reasoning_delta",
  "character_name", "tool_call", "tool_call_delta",
]);

/** StreamDoneEvent 约定的可选键；其余键一律拒绝。 */
const STREAM_DONE_KEYS = new Set([
  "type", "session_id", "stream_id", "finish_reason", "content", "metrics",
]);

function hasNoExtraKeys(value: Record<string, unknown>, allowed: Set<string>): boolean {
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) return false;
  }
  return true;
}

function isValidToolCall(value: unknown): value is StreamToolCall {
  if (!isObject(value)) return false;
  const { id, name, arguments: args } = value;
  // id 后端仅 str，允许空字符串
  if (typeof id !== "string") return false;
  if (typeof name !== "string") return false;
  if (!isStringRecord(args)) return false;
  return true;
}

function isValidToolCallDelta(value: unknown): value is StreamToolCallDelta {
  if (!isObject(value)) return false;
  const { id, index, name, args_delta, phase } = value;
  // id 允许空字符串，但必须是字符串
  if (typeof id !== "string") return false;
  // index 仅要求整数，不额外限定非负
  if (!isInteger(index)) return false;
  if (typeof name !== "string") return false;
  if (typeof args_delta !== "string") return false;
  if (phase !== "start" && phase !== "append" && phase !== "done") return false;
  return true;
}

function isValidMetrics(value: unknown): value is MessageMetrics {
  if (!isObject(value)) return false;
  const {
    reasoning_duration_ms,
    content_duration_ms,
    completion_tokens,
    tokens_per_second,
  } = value;
  // int, int, int, float；仅要求数字有限且前三个为整数，不增加正数约束
  if (!isInteger(reasoning_duration_ms)) return false;
  if (!isInteger(content_duration_ms)) return false;
  if (!isInteger(completion_tokens)) return false;
  if (!isFiniteNumber(tokens_per_second)) return false;
  return true;
}

/**
 * 校验 stream_delta 事件载荷（extra=forbid）。
 * 仅返回类型谓词，不输出诊断；调用方负责丢弃与日志。
 */
export function isStreamDeltaEvent(value: unknown): value is StreamDeltaEvent {
  if (!isObject(value)) return false;
  if (value.type !== WS_IN.STREAM_DELTA) return false;
  // 后端 extra=forbid：出现任何非约定键（含旧版 content 内嵌 JSON）即拒绝
  if (!hasNoExtraKeys(value, STREAM_DELTA_KEYS)) return false;
  const { session_id, stream_id, delta, reasoning_delta, character_name, tool_call, tool_call_delta } = value;
  if (!isNonEmptyString(session_id)) return false;
  if (!isNonEmptyString(stream_id)) return false;
  if (!isOptionalString(delta)) return false;
  if (!isOptionalString(reasoning_delta)) return false;
  if (!isOptionalString(character_name)) return false;
  if (tool_call !== undefined && !isValidToolCall(tool_call)) return false;
  if (tool_call_delta !== undefined && !isValidToolCallDelta(tool_call_delta)) return false;
  return true;
}

/**
 * 校验 stream_done 事件载荷（extra=forbid）。
 * content 缺失与空字符串语义不同；metrics 可选，存在则必须合法。
 */
export function isStreamDoneEvent(value: unknown): value is StreamDoneEvent {
  if (!isObject(value)) return false;
  if (value.type !== WS_IN.STREAM_DONE) return false;
  if (!hasNoExtraKeys(value, STREAM_DONE_KEYS)) return false;
  const { session_id, stream_id, finish_reason, content, metrics } = value;
  if (!isNonEmptyString(session_id)) return false;
  if (!isNonEmptyString(stream_id)) return false;
  if (typeof finish_reason !== "string") return false;
  if (!isOptionalString(content)) return false;
  if (metrics !== undefined && !isValidMetrics(metrics)) return false;
  return true;
}
