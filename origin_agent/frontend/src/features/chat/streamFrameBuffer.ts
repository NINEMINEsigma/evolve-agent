import type { StreamDeltaEvent } from "../../types";
import type { StreamBatch } from "./types";
import { chatTelemetry } from "./chatTelemetry";

export interface StreamFrameBuffer {
  /** 只接收已校验的 StreamDeltaEvent，直接消费顶层模型字段。 */
  push: (message: StreamDeltaEvent) => void;
  flush: () => void;
  cancel: () => void;
}

export function createStreamFrameBuffer(
  commitBatch: (batch: StreamBatch) => void,
): StreamFrameBuffer {
  let frame: number | null = null;
  let pending: StreamBatch | null = null;
  let queuedAt = 0;

  const flush = () => {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    const batch = pending;
    pending = null;
    if (!batch) return;
    commitBatch(batch);
    chatTelemetry.record({
      time: Date.now(),
      kind: "stream_batch",
      durationMs: queuedAt ? performance.now() - queuedAt : 0,
      charCount: batch.delta.length + batch.reasoningDelta.length,
      count: 1,
    });
    queuedAt = 0;
  };

  const schedule = () => {
    if (frame !== null) return;
    frame = requestAnimationFrame(() => {
      frame = null;
      flush();
    });
  };

  const push = (message: StreamDeltaEvent) => {
    const streamId = message.stream_id;
    if (!streamId) return;
    if (pending && pending.streamId !== streamId) flush();
    if (!pending) {
      pending = {
        streamId,
        characterName: message.character_name,
        delta: "",
        reasoningDelta: "",
      };
      queuedAt = performance.now();
    }
    pending.delta += message.delta || "";
    pending.reasoningDelta += message.reasoning_delta || "";
    // 顶层结构化 tool_call：完整工具调用的 name 与 arguments，仅覆盖 toolName/toolArgs；
    // 不清空此前分片累积的 toolArgsRawMap（聚合以 tool_call 为准，分片仅用于打字机渲染）。
    if (message.tool_call) {
      pending.toolName = message.tool_call.name;
      pending.toolArgs = message.tool_call.arguments;
    }
    // 顶层结构化 tool_call_delta：分片式参数增量
    if (message.tool_call_delta) {
      const delta = message.tool_call_delta;
      const key = `${delta.index}:${delta.id}`;
      const map = { ...(pending.toolArgsRawMap || {}) };
      if (delta.phase === "start") map[key] = "";
      if (delta.phase === "append") {
        map[key] = (map[key] || "") + (delta.args_delta || "");
      }
      pending.toolArgsRawMap = map;
      pending.activeToolCallKey = key;
      if (typeof delta.name === "string") pending.toolName = delta.name;
    }
    schedule();
  };

  return {
    push,
    flush,
    cancel: () => {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      pending = null;
      queuedAt = 0;
    },
  };
}
