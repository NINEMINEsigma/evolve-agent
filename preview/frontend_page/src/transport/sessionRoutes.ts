import type { MessageContent } from "@origin/types";
import type { SessionMediaListResponseDto } from "@origin/features/sessionMedia/types";
import type { PreviewRuntime } from "../types";
import { COLLOQUY_SID } from "@origin/constants/session";
import { PREVIEW } from "../constants";
import { enqueueReply, finishInterruptedReply, syncHistory } from "../runtime/conversation";
import { PreviewHttpError, flag, integer, jsonResponse, queryInteger, readBody, strings, text } from "./contracts";
import labels from "../content/zh-CN.json";

export async function handleSessionRequest(request: Request, runtime: PreviewRuntime): Promise<Response | null> {
  const url = new URL(request.url);
  const path = url.pathname;
  const method = request.method;
  const store = runtime.store;
  if (path === "/api/sessions" && method === "GET") return jsonResponse({ sessions: store.listSessions() });
  if (path === "/api/tags" && method === "GET") return jsonResponse({ tags: [...new Set(store.listSessions().flatMap((item) => item.tags ?? []))] });
  if (path === "/api/sessions/merge" && method === "POST") {
    const sources = strings((await readBody(request)).sources);
    if (!sources.length) throw new PreviewHttpError(422, "A continuation needs sources");
    return jsonResponse({ merged: true, session_id: store.createSession(sources).info.id });
  }
  const interaction = path.match(/^\/api\/(confirm|ask)\/([^/]+)$/);
  if (interaction && method === "POST") {
    const id = decodeURIComponent(interaction[2]);
    const body = await readBody(request);
    for (const session of store.sessions.values()) {
      if (session.confirm?.request_id !== id && session.ask?.request_id !== id) continue;
      const denied = interaction[1] === "confirm" && text(body.action) === "deny";
      session.confirm = null; session.ask = null;
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
    }
    return jsonResponse({ accepted: true });
  }
  const interrupt = path.match(/^\/api\/(interrupt|disgust)\/([^/]+)$/);
  if (interrupt && method === "POST") {
    const id = decodeURIComponent(interrupt[2]);
    const session = store.session(id);
    if (interrupt[1] === "disgust") return jsonResponse({ accepted: true });
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
    if (id === COLLOQUY_SID) throw new PreviewHttpError(403, "Built-in session cannot be deleted");
    runtime.events.closeSession(id, 4004); store.drafts.delete(id); store.sessions.delete(id);
    return jsonResponse({ deleted: true });
  }
  if (method === "GET") {
    switch (suffix) {
      case "llm-profile": return jsonResponse({ session_id: id, profile_name: session.profileName, available: store.profiles.some((item) => item.name === session.profileName) });
      case "history/skeleton": return jsonResponse(store.skeleton(id, queryInteger(url, "start_index", 0)));
      case "history/page": return jsonResponse(store.page(id, queryInteger(url, "start_index", 0), queryInteger(url, "limit", 100)));
      case "history/resources": return jsonResponse(store.resources(id));
      case "tool-resources": return jsonResponse({ session_id: id, task_progress: session.taskProgress, dynamic_endpoints: session.endpoints });
      case "shells": return jsonResponse({ shells: session.shells });
      case "cron-tasks": return jsonResponse({ tasks: session.cronTasks });
      case "subagents": return jsonResponse({ session_id: id, subagents: session.subagents });
      case "tab-capabilities": return jsonResponse({ session_id: id, media_count: session.media.length, variables_available: session.variables.variables.length > 0 || session.variables.issues.length > 0 });
      case "variables": return jsonResponse(session.variables);
      case "file-changes/summary": return jsonResponse(store.summary(id));
      case "file-changes": {
        const offset = queryInteger(url, "offset", 0), limit = queryInteger(url, "limit", 100);
        return jsonResponse({ summary: store.summary(id), offset, limit, total_count: session.changes.length, items: session.changes.slice(offset, offset + limit) });
      }
      case "history/media": {
        const offset = queryInteger(url, "offset", 0), limit = queryInteger(url, "limit", 100);
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
      case "regenerate-summary": return jsonResponse({ success: true, summary: labels.script.summary });
      case "pin": session.info.pinned = !session.info.pinned; return jsonResponse({ pinned: session.info.pinned });
      case "terminate":
        runtime.events.cancelSession(id, true); finishInterruptedReply(runtime, id); session.confirm = null; session.ask = null;
        session.info.status = "archived"; syncHistory(runtime, id);
        return jsonResponse({ terminated: true, metadata_warnings: [] });
      case "regenerate": {
        store.idle(id);
        const body = await readBody(request), index = integer(body.message_index);
        const row = session.rows.find((item) => item.history_index === index && item.role === "user");
        if (!row) throw new PreviewHttpError(404, "User message does not exist");
        const profileName = text(body.llm_profile_name);
        if (!store.profiles.some((item) => item.name === profileName)) throw new PreviewHttpError(422, "Unknown profile");
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
      if (!entry) throw new PreviewHttpError(404, "Shell does not exist");
      entry.running = false; entry.termination = "forced"; entry.exit_code = 0;
      entry.cleanup = { complete: true, pending_resources: [], warnings: [] };
      return jsonResponse({ stopped: true, shell: entry, cleanup: entry.cleanup });
    }
    const cron = suffix.match(/^cron-tasks\/([^/]+)\/(trigger|cancel)$/);
    if (cron) {
      const entry = session.cronTasks.find((item) => item.task_id === decodeURIComponent(cron[1]));
      if (!entry) throw new PreviewHttpError(404, "Cron task does not exist");
      if (cron[2] === "cancel") session.cronTasks = session.cronTasks.filter((item) => item !== entry);
      else entry.run_count += 1;
      return jsonResponse({ success: true });
    }
  }
  if (method === "PUT") {
    const body = await readBody(request);
    if (suffix === "title") { session.info.title = text(body.title).slice(0, 50); return jsonResponse({ updated: true, title: session.info.title }); }
    if (suffix === "tags") { session.info.tags = strings(body.tags); return jsonResponse({ updated: true, tags: session.info.tags }); }
    const media = suffix.match(/^history\/media\/([^/]+)$/);
    if (media) {
      store.writable(id);
      const entry = session.media.find((item) => item.media_id === decodeURIComponent(media[1]));
      if (!entry) throw new PreviewHttpError(404, "Media instance does not exist");
      if (entry.send_multimodal !== flag(body.expected_send_multimodal)) throw new PreviewHttpError(409, "Media state has changed");
      entry.send_multimodal = flag(body.send_multimodal);
      return jsonResponse({ session_id: id, item: entry });
    }
    const message = suffix.match(/^messages\/(\d+)$/);
    if (message) {
      store.idle(id);
      const row = session.rows.find((item) => item.history_index === Number(message[1]));
      if (!row) throw new PreviewHttpError(404, "Message does not exist");
      if (body.content !== undefined) {
        if (typeof body.content !== "string" && !Array.isArray(body.content)) throw new PreviewHttpError(422, "Invalid message content");
        row.content = body.content as MessageContent;
        store.syncMessageMedia(id, row);
        row.content_excerpt = typeof row.content === "string" ? row.content.slice(0, 80) : null;
      }
      if (body.visible_characters !== undefined) row.visible_characters = strings(body.visible_characters);
      runtime.events.emitSession(id, { type: "history_updated", session_id: id });
      return jsonResponse({ updated: true, content: row.content, visible_characters: row.visible_characters, session_id: id, index: row.history_index });
    }
  }
  if (method === "DELETE" && (suffix === "messages" || suffix === "messages/single")) {
    store.idle(id);
    if (suffix === "messages/single") store.deleteAt(id, queryInteger(url, "index", 0));
    else {
      const count = queryInteger(url, "count", 1);
      for (let index = 0; index < count && session.rows.length; index += 1) store.deleteAt(id, session.rows[session.rows.length - 1].history_index);
    }
    runtime.events.emitSession(id, { type: "history_updated", session_id: id });
    return jsonResponse({ deleted: true, history_count: session.historyCount, token_usage: session.tokenUsage, context_tokens: session.contextTokens });
  }
  return null;
}
