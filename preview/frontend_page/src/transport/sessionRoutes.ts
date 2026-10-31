import type { MessageContent } from "@origin/types";
import type { SessionMediaListResponseDto } from "@origin/features/sessionMedia/types";
import type { PreviewRuntime } from "../types";
import { COLLOQUY_SID } from "@origin/constants/session";
import { SESSION_MEDIA } from "@origin/constants/sessionMedia";
import { enqueueReply, finishInterruptedReply, syncHistory } from "../runtime/conversation";
import { PreviewHttpError, PreviewValidationError, flag, integer, jsonResponse, queryInteger, readBody, strings, text } from "./contracts";
import labels from "../content/zh-CN.json";

export async function handleSessionRequest(request: Request, runtime: PreviewRuntime): Promise<Response | null> {
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method;
  const store = runtime.store;
  if (path === "/api/sessions" && method === "GET") return jsonResponse({ sessions: store.listSessions() });
  if (path === "/api/tags" && method === "GET") return jsonResponse({ tags: [...new Set(store.listSessions().flatMap((item) => item.tags ?? []))] });
  if (path === "/api/sessions/merge" && method === "POST") {
    const sources = strings((await readBody(request)).sources, ["body", "sources"]);
    if (!sources.length) throw new PreviewValidationError([{ loc: ["body", "sources"], msg: "A continuation needs sources", type: "too_short" }]);
    return jsonResponse({ merged: true, session_id: store.createSession(sources).info.id });
  }
  const interaction = path.match(/^\/api\/(confirm|ask)\/([^/]+)$/);
  if (interaction && method === "POST") {
    const id = decodeURIComponent(interaction[2]);
    if (!request.body) throw new PreviewValidationError([{ loc: ["body"], msg: "Field required", type: "missing" }]);
    const body = await readBody(request);
    const kind = interaction[1];
    const action = kind === "confirm" ? body.action === undefined ? "deny" : body.action : null;
    if (kind === "confirm" && action !== "deny" && action !== "allow_once" && action !== "allow_always") {
      throw new PreviewValidationError([{ loc: ["body", "action"], msg: "Invalid approval action", type: "literal_error" }]);
    }
    if (kind === "confirm") {
      if (body.deny_reason !== undefined && body.deny_reason !== null) text(body.deny_reason, ["body", "deny_reason"]);
      if (body.denied_by !== undefined && body.denied_by !== null) text(body.denied_by, ["body", "denied_by"]);
    }
    const answers = body.answers ?? null;
    if (kind === "ask" && answers !== null) {
      if (!Array.isArray(answers)) throw new PreviewValidationError([{ loc: ["body", "answers"], msg: "Expected answer items", type: "list_type" }]);
      answers.forEach((answer: unknown, index) => {
        if (!answer || typeof answer !== "object" || Array.isArray(answer)) throw new PreviewValidationError([{ loc: ["body", "answers", index], msg: "Expected an answer object", type: "model_attributes_type" }]);
        const value = answer as Record<string, unknown>;
        if (value.custom_text !== undefined && value.custom_text !== null) text(value.custom_text, ["body", "answers", index, "custom_text"]);
        if (value.selected !== undefined) strings(value.selected, ["body", "answers", index, "selected"]);
      });
    }
    for (const session of store.sessions.values()) {
      if ((kind === "confirm" ? session.confirm?.request_id : session.ask?.request_id) !== id) continue;
      const denied = kind === "confirm" && action === "deny";
      if (kind === "confirm") session.confirm = null;
      else session.ask = null;
      for (const row of session.rows) {
        if (row.tool_card?.status !== "running") continue;
        row.tool_card.status = denied ? "failed" : "succeeded";
        row.tool_card.is_error = denied;
        row.tool_card.result_content = denied ? labels.script.denied : labels.script.toolResult;
        row.tool_card.result_history_index = session.historyCount++;
      }
      session.activity = null;
      runtime.events.emitSession(session.info.id, { type: "history_updated", session_id: session.info.id });
      if (denied) {
        store.appendMessage(session.info.id, "assistant", labels.script.denied, "main-agent");
        syncHistory(runtime, session.info.id);
      } else enqueueReply(runtime, session.info.id, { content: "", regenerate: true });
      return jsonResponse(kind === "confirm" ? { resolved: true, request_id: id, action } : { resolved: true, request_id: id, answers: answers ?? [] });
    }
    throw new PreviewHttpError(404, "interaction_not_found", "Interaction not found or already answered", { request_id: id });
  }
  const interrupt = path.match(/^\/api\/(interrupt|disgust)\/([^/]+)$/);
  if (interrupt && method === "POST") {
    const id = decodeURIComponent(interrupt[2]);
    const session = store.session(id);
    if (interrupt[1] === "disgust") return jsonResponse({ disgusted: true, session_id: id });
    const busy = session.activity !== null;
    runtime.events.cancelSession(id); finishInterruptedReply(runtime, id); session.confirm = null; session.ask = null;
    syncHistory(runtime, id);
    return jsonResponse({ interrupted: busy, status: busy ? "cancelled" : "idle", session_id: id });
  }
  const match = path.match(/^\/api\/sessions\/([^/]+)(?:\/(.*))?$/);
  if (!match) return null;
  const id = decodeURIComponent(match[1]);
  const suffix = match[2] ?? "";
  if (suffix === "status" && method === "GET") {
    const session = store.sessions.get(id);
    return jsonResponse({ session_id: id, exists: !!session, occupied: false, processing: !!session?.activity, activity: session?.activity ?? null });
  }
  const session = store.session(id);
  if (!suffix && method === "DELETE") {
    if (id === COLLOQUY_SID) throw new PreviewHttpError(403, "colloquy_operation_forbidden", "Built-in session cannot be deleted", { session_id: id });
    runtime.events.closeSession(id, 4004); store.drafts.delete(id); store.sessions.delete(id);
    return jsonResponse({ deleted: true });
  }
  if (method === "GET") {
    switch (suffix) {
      case "llm-profile": return jsonResponse({ session_id: id, profile_name: session.profileName, available: store.profiles.some((item) => item.name === session.profileName) });
      case "history/skeleton": {
        const start = queryInteger(url, "start_index", 0);
        if (start > session.historyCount) throw new PreviewHttpError(400, "history_index_out_of_range", "History index exceeds the current count", { session_id: id });
        return jsonResponse(store.skeleton(id, start));
      }
      case "history/page": return jsonResponse(store.page(id, queryInteger(url, "start_index", 0), queryInteger(url, "limit", 100, ["query", "limit"], 1, 200)));
      case "history/resources": return jsonResponse(store.resources(id));
      case "tool-resources": return jsonResponse({ session_id: id, task_progress: session.taskProgress, dynamic_endpoints: session.endpoints });
      case "shells": return jsonResponse({ shells: session.shells });
      case "cron-tasks": return jsonResponse({ tasks: session.cronTasks });
      case "subagents": return jsonResponse({ session_id: id, subagents: session.subagents });
      case "tab-capabilities": return jsonResponse({ session_id: id, media_count: session.media.length, variables_available: session.variables.variables.length > 0 || session.variables.issues.length > 0 });
      case "variables": return jsonResponse(session.variables);
      case "file-changes/summary": return jsonResponse(store.summary(id));
      case "file-changes": {
        const offset = queryInteger(url, "offset", 0), limit = queryInteger(url, "limit", 100, ["query", "limit"], 1, 200);
        return jsonResponse({ summary: store.summary(id), offset, limit, total_count: session.changes.length, items: session.changes.slice(offset, offset + limit) });
      }
      case "history/media": {
        const offset = queryInteger(url, "offset", 0), limit = queryInteger(url, "limit", 100, ["query", "limit"], 1, 500);
        const enabled = session.media.filter((item) => item.send_multimodal);
        const disabled = session.media.filter((item) => !item.send_multimodal);
        const data: SessionMediaListResponseDto = {
          session_id: id, history_count: session.historyCount, total_count: session.media.length, offset, limit,
          editable: session.info.status !== "archived", items: session.media.slice(offset, offset + limit),
          enabled_count: enabled.length, disabled_count: disabled.length,
          enabled_inline_payload_chars: enabled.reduce((sum, item) => sum + (item.inline_payload_chars ?? 0), 0),
          disabled_inline_payload_chars: disabled.reduce((sum, item) => sum + (item.inline_payload_chars ?? 0), 0),
          enabled_unknown_payload_count: enabled.filter((item) => item.inline_payload_chars === null).length,
          disabled_unknown_payload_count: disabled.filter((item) => item.inline_payload_chars === null).length,
        };
        return jsonResponse(data);
      }
    }
  }
  if (method === "POST") {
    switch (suffix) {
      case "auto-title": session.info.title = labels.script.title; return jsonResponse({ title: session.info.title });
      case "auto-tags": session.info.tags = [...labels.script.tags]; return jsonResponse({ tags: session.info.tags });
      case "regenerate-summary":
        if (id === COLLOQUY_SID) throw new PreviewHttpError(403, "colloquy_operation_forbidden", "Built-in session summary cannot be regenerated", { session_id: id });
        return jsonResponse({ success: true, summary: labels.script.summary });
      case "pin": session.info.pinned = !session.info.pinned; return jsonResponse({ pinned: session.info.pinned });
      case "terminate":
        if (id === COLLOQUY_SID) throw new PreviewHttpError(403, "colloquy_operation_forbidden", "Built-in session cannot be terminated", { session_id: id });
        runtime.events.cancelSession(id, true); finishInterruptedReply(runtime, id); session.confirm = null; session.ask = null;
        session.info.status = "archived"; syncHistory(runtime, id);
        return jsonResponse({ terminated: true, metadata_warnings: [] });
      case "regenerate": {
        store.idle(id);
        const body = await readBody(request), index = integer(body.message_index, 0, ["body", "message_index"]);
        const row = session.rows.find((item) => item.history_index === index && item.role === "user");
        if (!row) throw new PreviewHttpError(400, "regenerate_rejected", "User message does not exist", { session_id: id, message_index: index });
        const profileName = text(body.llm_profile_name, ["body", "llm_profile_name"]);
        if (!store.profiles.some((item) => item.name === profileName)) throw new PreviewHttpError(404, "profile_not_found", "Unknown profile");
        if (body.require_tool_call !== undefined) flag(body.require_tool_call, ["body", "require_tool_call"]);
        store.trim(id, index + 1);
        runtime.events.emitSession(id, { type: "system", session_id: id, content: JSON.stringify({ regenerate_trim: true, keep_count: index + 1, message_index: index }) });
        enqueueReply(runtime, id, { content: row.content, profileName, requireToolCall: body.require_tool_call === true, regenerate: true });
        return jsonResponse({ regenerate: true });
      }
      case "resume": store.idle(id); enqueueReply(runtime, id, { content: "", regenerate: true }); return jsonResponse({ resumed: true });
    }
    const shell = suffix.match(/^shells\/([^/]+)\/stop$/);
    if (shell) {
      const entry = session.shells.find((item) => item.shell_id === decodeURIComponent(shell[1]));
      if (!entry) throw new PreviewHttpError(404, "shell_not_found", "Shell does not exist", { session_id: id, shell_id: decodeURIComponent(shell[1]) });
      entry.running = false; entry.termination = "forced"; entry.exit_code = 0;
      entry.cleanup = { complete: true, pending_resources: [], warnings: [] };
      return jsonResponse({ stopped: true, shell: entry, cleanup: entry.cleanup });
    }
    const cron = suffix.match(/^cron-tasks\/([^/]+)\/(trigger|cancel)$/);
    if (cron) {
      const entry = session.cronTasks.find((item) => item.task_id === decodeURIComponent(cron[1]));
      if (!entry) throw new PreviewHttpError(404, "cron_task_not_found", "Cron task does not exist", { session_id: id, task_id: decodeURIComponent(cron[1]) });
      if (cron[2] === "cancel") session.cronTasks = session.cronTasks.filter((item) => item !== entry);
      else entry.run_count += 1;
      return jsonResponse({ success: true });
    }
  }
  if (method === "PUT") {
    const body = await readBody(request);
    if (suffix === "title") { session.info.title = text(body.title, ["body", "title"]).trim().slice(0, 50); return jsonResponse({ updated: true, title: session.info.title }); }
    if (suffix === "tags") {
      const tags = strings(body.tags, ["body", "tags"]).map((tag) => tag.trim());
      if (tags.some((tag) => !/^[\u4e00-\u9fa5]{1,5}$/.test(tag) && !/^[a-zA-Z]{1,10}$/.test(tag))) throw new PreviewHttpError(400, "invalid_tags", "Invalid session tags");
      session.info.tags = tags;
      return jsonResponse({ updated: true, session_id: id, tags: null });
    }
    const media = suffix.match(/^history\/media\/([^/]+)$/);
    if (media) {
      const mediaId = decodeURIComponent(media[1]);
      if (!SESSION_MEDIA.ID_PATTERN.test(mediaId)) throw new PreviewValidationError([{ loc: ["path", "media_id"], msg: "Invalid media instance identity", type: "string_pattern_mismatch" }]);
      store.writable(id);
      const entry = session.media.find((item) => item.media_id === mediaId);
      const enabled = flag(body.send_multimodal, ["body", "send_multimodal"]);
      const expected = flag(body.expected_send_multimodal, ["body", "expected_send_multimodal"]);
      if (!entry) throw new PreviewHttpError(404, "media_not_found", "Media instance does not exist", { media_id: decodeURIComponent(media[1]) });
      if (entry.send_multimodal !== expected) throw new PreviewHttpError(409, "media_conflict", "Media state has changed", { media_id: entry.media_id });
      entry.send_multimodal = enabled;
      return jsonResponse({ session_id: id, item: entry });
    }
    const message = suffix.match(/^messages\/([^/]+)$/);
    if (message) {
      const messageIndex = integer(/^\d+$/.test(message[1]) ? Number(message[1]) : NaN, 0, ["path", "message_index"]);
      store.idle(id);
      const row = session.rows.find((item) => item.history_index === messageIndex);
      if (!row) throw new PreviewHttpError(400, "message_edit_rejected", "Message does not exist", { session_id: id, message_index: messageIndex });
      const visible = body.visible_characters === undefined ? undefined : strings(body.visible_characters, ["body", "visible_characters"]);
      if (body.content !== undefined) {
        if (typeof body.content !== "string" && !Array.isArray(body.content)) throw new PreviewValidationError([{ loc: ["body", "content"], msg: "Invalid message content", type: "value_error" }]);
        row.content = body.content as MessageContent;
        store.syncMessageMedia(id, row);
        row.content_excerpt = typeof row.content === "string" ? row.content.slice(0, 80) : null;
      }
      if (visible !== undefined) row.visible_characters = visible;
      runtime.events.emitSession(id, { type: "history_updated", session_id: id });
      return jsonResponse({ updated: true, content: row.content, visible_characters: row.visible_characters, session_id: id, index: row.history_index });
    }
  }
  if (method === "DELETE" && (suffix === "messages" || suffix === "messages/single")) {
    store.idle(id);
    if (suffix === "messages/single") {
      if (!url.searchParams.has("index")) throw new PreviewValidationError([{ loc: ["query", "index"], msg: "Field required", type: "missing" }]);
      store.deleteAt(id, queryInteger(url, "index", 0));
    }
    else {
      const count = queryInteger(url, "count", 1, ["query", "count"], 1);
      for (let index = 0; index < count && session.rows.length; index += 1) store.deleteAt(id, session.rows[session.rows.length - 1].history_index);
    }
    runtime.events.emitSession(id, { type: "history_updated", session_id: id });
    return jsonResponse({ deleted: true, session_id: id, history_count: session.historyCount, token_usage: session.tokenUsage, context_tokens: session.contextTokens });
  }
  return null;
}
