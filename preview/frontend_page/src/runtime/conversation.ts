import type { PreviewRuntime, PreviewUserInput } from "../types";
import type { HistoryContentRowDto } from "@origin/features/chat/types";
import { PREVIEW } from "../constants";
import { pauseFor } from "./events";
import { reportPreviewFault } from "./faults";
import labels from "../content/zh-CN.json";

export function syncHistory(runtime: PreviewRuntime, id: string): void {
  const session = runtime.store.session(id);
  runtime.events.emitSession(id, { type: "history_sync", session_id: id, history_count: session.historyCount,
    processing: session.activity !== null, agents: session.agents,
    token_usage: session.tokenUsage, context_tokens: session.contextTokens });
}
function linkRow(runtime: PreviewRuntime, id: string, streamId: string, row: HistoryContentRowDto, liveId?: string): void {
  runtime.events.emitSession(id, { type: "system", session_id: id, content: JSON.stringify({ stream_meta: {
    ...(row.row_kind === "message" ? { stream_id: streamId, history_index: row.history_index } : {}),
    live_history_links: liveId ? [{ live_id: liveId, history_row_id: row.row_id }] : [],
  } }) });
}
export async function runScriptedReply(
  runtime: PreviewRuntime, sessionId: string, input: PreviewUserInput, signal: AbortSignal,
): Promise<void> {
  signal.throwIfAborted();
  const session = runtime.store.writable(sessionId);
  while (runtime.paused || session.confirm !== null || session.ask !== null) await pauseFor(80, signal);
  if (input.profileName) session.profileName = input.profileName;
  const targets = input.targetSessions?.length ? input.targetSessions : ["main"];
  for (const target of targets.filter((value) => value !== "main")) {
    const subagent = session.subagents[target];
    if (!subagent) continue;
    const feedback = [{ role: "user", content: typeof input.content === "string" ? input.content : JSON.stringify(input.content), character_name: "end-user" },
      { role: "assistant", content: labels.script.reply, character_name: subagent.name }];
    subagent.feedback.push(...feedback);
    runtime.events.emitSession(sessionId, { type: "subagent_update", session_id: sessionId, result: JSON.stringify({ ...subagent, feedback }) });
  }
  if (!targets.includes("main")) { syncHistory(runtime, sessionId); return; }
  const activityId = runtime.store.nextId("activity");
  const streamId = runtime.store.nextId("stream");
  session.activity = { activity_id: activityId, revision: 1, source: input.regenerate ? "regenerate" : "user_message", phase: "waiting_first_token", stream_id: streamId, character_name: "main-agent" };
  syncHistory(runtime, sessionId);
  await pauseFor(160, signal);
  session.activity.phase = "streaming";
  const author = session.agents[0] || "main-agent";
  const draft = { streamId, author, content: "", reasoning: labels.script.reasoning };
  runtime.store.drafts.set(sessionId, draft);
  runtime.events.emitSession(sessionId, { type: "stream_delta", session_id: sessionId, stream_id: streamId, character_name: author, reasoning_delta: labels.script.reasoning });
  if (input.requireToolCall) {
    const toolId = runtime.store.nextId("tool");
    runtime.events.emitSession(sessionId, { type: "tool_call", session_id: sessionId, tool_call_id: toolId, tool: "Write",
      args: { path: "ws:reports/brief.md", content: labels.script.toolResult }, character_name: author });
    const tool = runtime.store.appendTool(sessionId, toolId, labels.script.toolResult);
    const report = runtime.store.files.get("reports/brief.md");
    if (report) report.content = labels.script.toolResult;
    runtime.events.emitSession(sessionId, { type: "tool_result", session_id: sessionId, tool_call_id: toolId, tool: "Write",
      result: labels.script.toolResult, index: tool.tool_card?.result_history_index, character_name: author });
    linkRow(runtime, sessionId, streamId, tool, `tool-card:${toolId}`);
  }
  for (let offset = 0; offset < labels.script.reply.length; offset += PREVIEW.chunkChars) {
    while (runtime.paused) await pauseFor(80, signal);
    signal.throwIfAborted();
    const delta = labels.script.reply.slice(offset, offset + PREVIEW.chunkChars);
    draft.content += delta;
    runtime.events.emitSession(sessionId, { type: "stream_delta", session_id: sessionId, stream_id: streamId,
      character_name: author, delta });
    await pauseFor(PREVIEW.chunkDelayMs, signal);
  }
  signal.throwIfAborted();
  const row = runtime.store.appendMessage(sessionId, "assistant", labels.script.reply, author);
  row.reasoning_content = labels.script.reasoning;
  row.metrics = { reasoning_duration_ms: 640, content_duration_ms: 2600, completion_tokens: 248, tokens_per_second: 95.4 };
  session.tokenUsage += 1600; session.contextTokens += 820;
  linkRow(runtime, sessionId, streamId, row, streamId);
  runtime.events.emitSession(sessionId, { type: "stream_done", session_id: sessionId, stream_id: streamId,
    content: labels.script.reply, finish_reason: "stop", metrics: row.metrics });
  runtime.store.drafts.delete(sessionId);
  session.activity = null;
  syncHistory(runtime, sessionId);
}

export function finishInterruptedReply(runtime: PreviewRuntime, id: string): void {
  const session = runtime.store.session(id);
  const draft = runtime.store.drafts.get(id);
  const streamId = draft?.streamId ?? session.activity?.stream_id;
  if (draft?.content) {
    const row = runtime.store.appendMessage(id, "assistant", draft.content, draft.author);
    row.reasoning_content = draft.reasoning;
    linkRow(runtime, id, draft.streamId, row, draft.streamId);
  }
  if (streamId) runtime.events.emitSession(id, { type: "stream_done", session_id: id, stream_id: streamId, finish_reason: "interrupted", ...(draft?.content ? { content: draft.content } : {}) });
  runtime.store.drafts.delete(id);
  session.activity = null;
}

export function enqueueReply(runtime: PreviewRuntime, id: string, input: PreviewUserInput): void {
  runtime.store.writable(id);
  // 接收即提交并回显用户输入；回复执行可以排队，中断不会丢掉待确认消息。
  if (!input.regenerate) {
    const user = runtime.store.appendMessage(id, "user", input.content, input.characterName || "end-user");
    runtime.events.emitSession(id, { type: "user_message", session_id: id, content: user.content,
      character_name: user.character_name ?? "end-user", client_message_id: input.clientMessageId, index: user.history_index });
    syncHistory(runtime, id);
  }
  runtime.events.enqueue(id, (signal) => runScriptedReply(runtime, id, input, signal), (error) => {
    const session = runtime.store.sessions.get(id);
    if (session) { session.activity = null; syncHistory(runtime, id); }
    reportPreviewFault({ code: "script", path: id, message: error instanceof Error ? error.message : "Script failed" });
  });
}
