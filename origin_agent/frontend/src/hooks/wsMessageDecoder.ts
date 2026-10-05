import { WS_IN } from "../constants/ws";
import type { NonStreamWSMessage, WSMessage } from "../types";
import { isStreamDeltaEvent, isStreamDoneEvent } from "../features/chat/streamEventGuards";

/** 已知的入站 type 字面量集合（与 constants/ws.ts::WS_IN 对应）。 */
const KNOWN_INBOUND_TYPES = new Set<string>(Object.values(WS_IN));

/**
 * WebSocket 入站消息统一解码器：把原始 JSON 字符串转为判别联合 WSMessage。
 *
 * 处理顺序：
 * 1. JSON.parse 失败 → 丢弃并输出不含正文的诊断；
 * 2. 基础对象/type 检查（type 必须为已知入站 type 字面量，否则按未知类型丢弃）；
 * 3. 流式事件（stream_delta / stream_done）经 streamEventGuards 实际结构校验，
 *    非法载荷丢弃并输出不含正文/参数的诊断，不得静默成为其他消息或污染 store；
 * 4. 旧非流事件暂仅基础检查后透传为 NonStreamWSMessage，未在本次全面迁移；
 * 5. 未知 type 丢弃。
 *
 * 日志只输出已验证且已知的消息 type，避免原始 typeField 包含对象/正文导致泄露或字符串转换异常。
 *
 * @returns 解码成功的 WSMessage；非法 JSON / 非法流式载荷 / 未知类型均返回 null（已记日志）。
 */
export function decodeWSMessage(raw: string): WSMessage | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    console.error("[ws decode] 非法 JSON，已丢弃", { len: raw.length });
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    console.error("[ws decode] 消息必须为对象，已丢弃");
    return null;
  }
  const obj = parsed as { type?: unknown };
  const typeField = obj.type;
  if (typeof typeField !== "string" || !KNOWN_INBOUND_TYPES.has(typeField)) {
    // 未知 type：不输出 typeField 原值，避免泄露或字符串转换异常
    console.error("[ws decode] 未知消息类型，已丢弃");
    return null;
  }

  // 流式事件：实际结构校验
  if (typeField === WS_IN.STREAM_DELTA) {
    if (!isStreamDeltaEvent(parsed)) {
      console.error("[ws decode] stream_delta 载荷非法，已丢弃", { type: WS_IN.STREAM_DELTA });
      return null;
    }
    return parsed;
  }
  if (typeField === WS_IN.STREAM_DONE) {
    if (!isStreamDoneEvent(parsed)) {
      console.error("[ws decode] stream_done 载荷非法，已丢弃", { type: WS_IN.STREAM_DONE });
      return null;
    }
    return parsed;
  }

  // 非流式事件：基础检查后透传（暂不全面迁移）
  return parsed as NonStreamWSMessage;
}
