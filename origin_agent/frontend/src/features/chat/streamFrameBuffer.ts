import type { WSMessage } from "../../types";
import type { StreamBatch } from "./types";
import { chatTelemetry } from "./chatTelemetry";

export interface StreamFrameBuffer {
  push: (message: WSMessage) => void;
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

  const push = (message: WSMessage) => {
    const streamId = message.stream_id || "";
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
    if (typeof message.content === "string") {
      try {
        const parsed = JSON.parse(message.content) as {
          tool_call?: { name?: string; arguments?: Record<string, unknown> };
          tool_call_delta?: Record<string, unknown>;
        };
        if (parsed.tool_call) {
          pending.toolName = parsed.tool_call.name;
          pending.toolArgs = parsed.tool_call.arguments;
        }
        if (parsed.tool_call_delta) {
          const delta = parsed.tool_call_delta;
          const key = `${delta.index ?? 0}:${delta.id ?? ""}`;
          const map = { ...(pending.toolArgsRawMap || {}) };
          if (delta.phase === "start") map[key] = "";
          if (delta.phase === "append") {
            map[key] = (map[key] || "") + String(delta.args_delta || "");
          }
          pending.toolArgsRawMap = map;
          pending.activeToolCallKey = key;
          if (typeof delta.name === "string") pending.toolName = delta.name;
        }
      } catch {
        // 普通文本 content 不影响流式正文。
      }
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
