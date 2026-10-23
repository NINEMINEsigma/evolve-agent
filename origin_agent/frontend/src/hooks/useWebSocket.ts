import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from "react";
import type {
  ApprovalMode,
  AskAnswerItem,
  AskRequest,
  ClipboardDisplay,
  ClientDiagnostic,
  ConfirmRequest,
  CronTask,
  DynamicEndpoint,
  HistoryRowLink,
  InterruptResponse,
  MessageContent,
  NonStreamWSMessage,
  ShellInfo,
  SubagentSession,
  TaskProgress,
  WSMessage,
} from "../types";
import type { SessionToolResourcesDto } from "../types/sessionResources";
import { collectClientInfo } from "../constants/clientInfo";
import { COLLOQUY_SID } from "../constants/session";
import { STORAGE_KEYS } from "../constants/storage";
import { TIMING } from "../constants/timing";
import { WS_CONNECTION_WELCOME_TEXT, WS_IN, WS_OUT } from "../constants/ws";
import { generateUUID, parseToolResult } from "../utils";
import { chatRuntimeController } from "../features/chat/chatRuntimeController";
import { useChatRuntimeStore } from "../features/chat/chatRuntimeStore";
import { isRegenerateTrimPayload } from "../features/chat/regenerateTrim";
import {
  isMainSessionBusyForToolCall,
  shouldRequireToolCall,
  TOOL_CALL_REQUIREMENT_LABELS,
} from "../features/chat/toolCallRequirement";
import { hasMountedChatList } from "../features/chat/chatViewport";
import { createStreamFrameBuffer, type StreamFrameBuffer } from "../features/chat/streamFrameBuffer";
import { useLlmProfiles } from "./useLlmProfiles";
import { useSessionStore, type SessionStore } from "./useSessionStore";
import { publishChatAgentspaceEvent } from "../services/chatAgentspaceEventBus";
import { fetchJsonWithTimeout } from "../services/fetchJsonWithTimeout";
import { clientDiagnosticFrame, routeChatTransportMessage } from "./chatTransportRouting";
import { decodeShellInfo } from "../services/shellResourcesApi";
import { useMainSessionActivityPolling } from "../features/chat/useMainSessionActivityPolling";
import { useSubagentManager } from "./useSubagentManager";
import { useUploadManager, type UploadManager } from "./useUploadManager";
import { useWebSocketConnection } from "./useWebSocketConnection";

export type { PendingImage, PendingAudio, PendingVideo } from "./useUploadManager";
export type WebSocketState = ReturnType<typeof useWebSocket>;

const CRITICAL_TIMEOUT_MS = TIMING.CRITICAL_REQUEST_TIMEOUT;

function isApprovalMode(value: unknown): value is ApprovalMode {
  return value === "manual" || value === "handsfree" || value === "yolo";
}

function objectValue(payload: unknown): Record<string, unknown> {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Expected a JSON object");
  }
  return payload as Record<string, unknown>;
}

/** Shell 列表：列表必须存在且为数组；逐项核对归属、running 与身份字段类型。 */
function decodeSessionShells(payload: unknown, sessionId: string): ShellInfo[] {
  const value = objectValue(payload);
  const raw = value.shells;
  if (!Array.isArray(raw)) throw new Error("Shells payload is not an array");
  return raw.map((entry) => decodeShellInfo(entry, sessionId));
}

/** Cron 列表：列表必须存在且为数组；should_schedule 为 boolean、next_run 为 string|null。 */
function decodeSessionCronTasks(payload: unknown): CronTask[] {
  const value = objectValue(payload);
  const raw = value.tasks;
  if (!Array.isArray(raw)) throw new Error("Cron tasks payload is not an array");
  return raw.map((entry) => {
    const item = objectValue(entry);
    if (typeof item.task_id !== "string" || typeof item.should_schedule !== "boolean") {
      throw new Error("Invalid cron task entry");
    }
    if (item.next_run !== null && typeof item.next_run !== "string") {
      throw new Error("Invalid cron next_run");
    }
    if (item.is_wait !== undefined && typeof item.is_wait !== "boolean") {
      throw new Error("Invalid cron wait flag");
    }
    if (item.wait_message !== undefined && typeof item.wait_message !== "string") {
      throw new Error("Invalid cron wait message");
    }
    return entry as CronTask;
  });
}

/** 工具资源：顶层 session_id 必须等于请求 Scope，容器类型逐项校验。 */
function decodeSessionToolResources(payload: unknown, sessionId: string): SessionToolResourcesDto {
  const value = objectValue(payload);
  if (value.session_id !== sessionId) throw new Error("Tool resources belong to a different session");
  const taskProgress = objectValue(value.task_progress);
  const clipboard = objectValue(value.clipboard_display);
  const rawEndpoints = value.dynamic_endpoints;
  if (!Array.isArray(rawEndpoints)) throw new Error("Invalid dynamic endpoints payload");
  const dynamicEndpoints = rawEndpoints.map((entry) => {
    const item = objectValue(entry);
    if (typeof item.name !== "string" || typeof item.url !== "string"
      || typeof item.agent_name !== "string" || typeof item.created_at !== "number"
      || !Number.isFinite(item.created_at)) {
      throw new Error("Invalid dynamic endpoint entry");
    }
    return entry as DynamicEndpoint;
  });
  return {
    session_id: sessionId,
    task_progress: taskProgress as Record<string, TaskProgress>,
    clipboard_display: clipboard as Record<string, ClipboardDisplay>,
    dynamic_endpoints: dynamicEndpoints,
  };
}

/** 子会话快照：外层 session_id 与请求 Scope 一致，subagents 为非数组对象。 */
function decodeSessionSubagents(payload: unknown, sessionId: string): Record<string, SubagentSession> {
  const value = objectValue(payload);
  if (value.session_id !== sessionId) throw new Error("Subagents belong to a different session");
  const subagents = value.subagents;
  if (subagents === null || typeof subagents !== "object" || Array.isArray(subagents)) {
    throw new Error("Invalid subagents payload");
  }
  for (const entry of Object.values(subagents as Record<string, unknown>)) {
    const item = objectValue(entry);
    if (typeof item.session_id !== "string" || typeof item.name !== "string") {
      throw new Error("Invalid subagent entry");
    }
    if (item.status !== "running" && item.status !== "completed" && item.status !== "terminated") {
      throw new Error("Invalid subagent status");
    }
    if (!Array.isArray(item.feedback) || !Array.isArray(item.pending_approvals)) {
      throw new Error("Invalid subagent lists");
    }
    if (item.interactive !== undefined && typeof item.interactive !== "boolean") {
      throw new Error("Invalid subagent interactive flag");
    }
  }
  return subagents as Record<string, SubagentSession>;
}

export function useWebSocket() {
  const conn = useWebSocketConnection();
  const subagent = useSubagentManager();
  const processing = useChatRuntimeStore((state) => state.processing);
  const sessionRef = useRef<SessionStore | null>(null);
  const uploadRef = useRef<UploadManager | null>(null);
  const connRef = useRef(conn);
  const subagentRef = useRef(subagent);
  const streamDoneSeenRef = useRef(false);
  const regenerateRequestSequenceRef = useRef(0);
  const regenerateRequestRef = useRef<{
    sequence: number;
    sessionId: string;
    socket: WebSocket;
    messageIndex: number;
    optimisticActivityId: string | null;
    trimConfirmed: boolean;
  } | null>(null);
  const historyHandshakeRef = useRef<{
    sessionId: string; generation: number; liveVersion: number;
  } | null>(null);
  // 只用于阻止切会话期间提交旧身份；不承载新的会话真相源。
  const sessionTransitionRef = useRef(true);

  const fetchToolResourcesRef = useRef(async (sid: string) => {
    if (!sid) return;
    const owner = sessionRef.current;
    if (!owner || owner.sessionId !== sid) return;
    // 端点快照使用自己的 Token（同一 sid 同源在途读取合并）；子会话读取独立进行。
    const endpointToken = owner.dynamicEndpointResource.beginRequest();
    const scope = { sessionId: sid, generation: owner.resourceScope.generation };
    const [toolRes, subagentRes] = await Promise.allSettled([
      endpointToken
        ? fetchJsonWithTimeout(
            `/api/sessions/${sid}/tool-resources`, { signal: endpointToken.signal },
            { timeoutMs: CRITICAL_TIMEOUT_MS, phase: "tool-resources" },
            (payload) => decodeSessionToolResources(payload, sid),
          )
        : Promise.reject(new Error("Tool resources read skipped")),
      fetchJsonWithTimeout(
        `/api/sessions/${sid}/subagents`, {},
        { timeoutMs: CRITICAL_TIMEOUT_MS, phase: "subagents" },
        (payload) => decodeSessionSubagents(payload, sid),
      ),
    ]);
    if (!owner.isResourceScopeCurrent(scope)) return;
    if (endpointToken) {
      if (toolRes.status === "fulfilled") {
        owner.setTaskProgress(toolRes.value.task_progress);
        owner.setClipboardDisplays(toolRes.value.clipboard_display);
        owner.dynamicEndpointResource.completeRequest(endpointToken, toolRes.value.dynamic_endpoints);
      } else {
        owner.dynamicEndpointResource.failRequest(endpointToken, "tool-resources 请求失败");
      }
    }
    if (subagentRes.status === "fulfilled") {
      subagentRef.current.mergeSnapshot(sid, {
        subagents: subagentRes.value,
      });
    }
  });

  const session = useSessionStore({
    onSessionRotated: (newSid, oldSid) => {
      sessionTransitionRef.current = true;
      subagentRef.current.setSubagentSessionsMap((previous) => ({ ...previous, [oldSid]: {} }));
      chatRuntimeController.beginSession(newSid);
    },
  });

  const appendLocalMessage = useCallback((
    role: "user" | "assistant" | "system" | "error" | "tool",
    content: MessageContent,
  ) => {
    useChatRuntimeStore.getState().appendLiveMessage({ role, content, id: generateUUID() });
  }, []);

  const upload = useUploadManager({
    wsRef: conn.wsRef,
    sessions: session.sessions,
    sessionId: session.sessionId,
    addMessage: (role, content) => appendLocalMessage(role, content),
  });
  const llmProfiles = useLlmProfiles(session.sessionId);
  const llmProfilesRef = useRef(llmProfiles);
  useMainSessionActivityPolling(session.sessionId, conn.connected);

  const frameBufferRef = useRef<StreamFrameBuffer | null>(null);
  if (frameBufferRef.current === null) {
    frameBufferRef.current = createStreamFrameBuffer((batch) => {
      useChatRuntimeStore.getState().applyStreamBatch(batch);
    });
  }

  useEffect(() => { connRef.current = conn; }, [conn]);
  useLayoutEffect(() => { sessionRef.current = session; }, [session]);
  useEffect(() => { uploadRef.current = upload; }, [upload]);
  useEffect(() => { subagentRef.current = subagent; }, [subagent]);
  useEffect(() => { llmProfilesRef.current = llmProfiles; }, [llmProfiles]);
  useEffect(() => {
    const sid = session.sessionId;
    sessionTransitionRef.current = !sid || sid !== llmProfiles.sessionId
      || sid !== useChatRuntimeStore.getState().sessionId;
  });

  const reportTransportDiagnostic = useCallback((diagnostic: ClientDiagnostic) => {
    const sid = sessionRef.current?.sessionId || "";
    const now = Date.now();
    const socket = connRef.current?.wsRef.current;
    const state = socket?.readyState === WebSocket.OPEN ? "OPEN"
      : socket?.readyState === WebSocket.CONNECTING ? "CONNECTING"
        : socket?.readyState === WebSocket.CLOSING ? "CLOSING"
          : socket ? "CLOSED" : diagnostic.websocket_state;
    const payload: ClientDiagnostic = {
      kind: diagnostic.kind,
      phase: diagnostic.phase,
      duration_ms: diagnostic.duration_ms,
      websocket_state: state,
      last_recv_age_ms: Math.max(0, now - (connRef.current?.lastRecvAtRef.current ?? now)),
      last_pong_age_ms: Math.max(0, now - (connRef.current?.lastPongAtRef.current ?? now)),
    };
    sessionRef.current?.showOperationNotice({
      kind: "error",
      message: `会话 ${sid || "未连接"} 的${payload.phase}请求等待 ${(payload.duration_ms / 1000).toFixed(1)} 秒后超时，请重试。`,
    });
    if (socket?.readyState === WebSocket.OPEN) {
      connRef.current.send(clientDiagnosticFrame(sid, payload));
    }
  }, []);

  useEffect(() => {
    chatRuntimeController.setDiagnosticReporter(reportTransportDiagnostic);
    return () => chatRuntimeController.setDiagnosticReporter(null);
  }, [reportTransportDiagnostic]);

  const handleHistorySync = useCallback((message: NonStreamWSMessage) => {
    const sid = message.session_id || sessionRef.current?.sessionId || "";
    if (!sid) return;
    if (sessionRef.current?.sessionId !== sid) {
      sessionTransitionRef.current = true;
      sessionRef.current?.setSessionId(sid);
      localStorage.setItem(STORAGE_KEYS.SESSION_ID, sid);
    }
    const runtime = useChatRuntimeStore.getState();
    if (typeof message.token_usage === "number") sessionRef.current?.setTokenUsage(message.token_usage);
    if (typeof message.context_tokens === "number") sessionRef.current?.setContextTokens(message.context_tokens);
    if (Array.isArray(message.agents)) sessionRef.current?.setAgents(message.agents);
    else if (message.agents === null) sessionRef.current?.setAgents([]);
    const historyCount = message.history_count ?? 0;
    if (typeof message.processing === "boolean") useChatRuntimeStore.getState().setProcessing(message.processing);
    const handshake = historyHandshakeRef.current;
    historyHandshakeRef.current = null;
    if (runtime.sessionId !== sid) {
      chatRuntimeController.beginSession(sid);
      useChatRuntimeStore.setState({ knownHistoryCount: historyCount });
      void chatRuntimeController.initialize(sid, historyCount);
    } else if (handshake?.sessionId === sid && handshake.generation === runtime.generation) {
      // 重连也必须完整读取，恢复断线期间可能遗漏的历史更新指令。
      void chatRuntimeController.reloadHistory(sid, handshake.liveVersion);
    } else if (runtime.historyReloadRequired) {
      void chatRuntimeController.syncCanonicalHistory(historyCount);
    } else if (runtime.skeleton.length === 0 && !runtime.initialReady) {
      useChatRuntimeStore.setState({ knownHistoryCount: historyCount });
      void chatRuntimeController.initialize(sid, historyCount);
    } else {
      void chatRuntimeController.syncCanonicalHistory(historyCount);
    }
    useChatRuntimeStore.getState().setCanonicalHandoffReady(true);
    fetchToolResourcesRef.current(sid);
    sessionRef.current?.fetchSessions();
  }, []);

  const handleNonStreamMessage = useCallback((message: NonStreamWSMessage) => {
    if (routeChatTransportMessage(
      message,
      sessionRef.current?.sessionId || "",
      publishChatAgentspaceEvent,
    )) return;
    if (message.type === WS_IN.LLM_PROFILE_CHANGED) {
      llmProfilesRef.current.handleProfileChanged(message);
      return;
    }
    if (message.type === WS_IN.APPROVAL_PROFILE_CHANGED) {
      llmProfilesRef.current.handleApprovalProfileChanged(message);
      return;
    }
    if (message.type === WS_IN.METADATA_PROFILE_CHANGED) {
      llmProfilesRef.current.handleMetadataProfileChanged(message);
      return;
    }
    if (message.type === WS_IN.TOOLCHAIN_SUMMARY_PROFILE_CHANGED) {
      llmProfilesRef.current.handleToolchainSummaryProfileChanged(message);
      return;
    }
    if (message.type === WS_IN.MODALITY_PROFILE_CHANGED) {
      llmProfilesRef.current.handleModalityProfileChanged(message);
      return;
    }
    if (message.type === WS_IN.HANDSFREE_MODE) {
      const mode = isApprovalMode(message.approval_mode)
        ? message.approval_mode
        : typeof message.handsfree_mode === "boolean"
          ? message.handsfree_mode ? "handsfree" : "manual"
          : null;
      if (mode) {
        sessionRef.current?.setApprovalMode(mode);
        sessionRef.current?.setApprovalModeSyncStatus("ready");
      }
      return;
    }
    if (message.type === WS_IN.HISTORY_SYNC) {
      frameBufferRef.current?.flush();
      handleHistorySync(message);
      return;
    }
    if (message.type === WS_IN.USER_MESSAGE) {
      const clientId = message.client_message_id;
      const liveId = clientId || generateUUID();
      useChatRuntimeStore.getState().appendLiveMessage({
        role: "user",
        content: message.content ?? "",
        id: liveId,
        clientMessageId: clientId,
        characterName: message.character_name,
        messageIndex: message.index,
        visibleCharacters: message.visible_characters,
        responseCharacters: message.response_characters,
        messageSuffix: message.message_suffix,
        dynamicMessageSuffix: message.dynamic_message_suffix,
      });
      if (Number.isSafeInteger(message.index) && (message.index ?? -1) >= 0) {
        useChatRuntimeStore.getState().linkLiveHistory(liveId, `history:${message.index}:message`);
        useChatRuntimeStore.getState().promoteMappedLiveRows();
      } else {
        console.error("USER_MESSAGE缺少有效History index", { sessionId: useChatRuntimeStore.getState().sessionId, liveId });
      }
      if (clientId) useChatRuntimeStore.getState().removePendingMessages([clientId]);
      useChatRuntimeStore.getState().placeProvisionalActivityAfterUser();
      return;
    }
    if (message.type === WS_IN.TOOL_CALLS_DISCARDED) {
      frameBufferRef.current?.flush();
      // session_id / stream_id / tool_call_ids 已由解码层严格校验；
      // Store 只接受当前会话的权威丢弃事件，按 tool_call_id 删除实时卡片及映射/高度。
      if (message.tool_call_ids?.length && message.session_id) {
        useChatRuntimeStore.getState().discardLiveToolCalls(
          message.tool_call_ids, message.session_id,
        );
      }
      return;
    }
    if (message.type === WS_IN.TOOL_CALL) {
      frameBufferRef.current?.flush();
      if (!message.tool_call_id) {
        const liveId = generateUUID();
        console.error("TOOL_CALL缺少tool_call_id", { liveId });
        useChatRuntimeStore.getState().appendLiveMessage({
          role: "tool",
          content: `${message.character_name ? `${message.character_name} ` : ""}⚡ ${message.tool || "tool"}`,
          id: liveId,
          toolName: message.tool,
          toolArgs: message.args,
          characterName: message.character_name,
        });
        return;
      }
      useChatRuntimeStore.getState().upsertLiveToolCall(
        message.tool_call_id,
        message.tool,
        message.args,
        message.character_name,
      );
      return;
    }
    if (message.type === WS_IN.TOOL_RESULT) {
      frameBufferRef.current?.flush();
      const parsed = parseToolResult(message.result ?? "", message.tool);
      if (!message.tool_call_id) {
        const liveId = generateUUID();
        console.error("TOOL_RESULT缺少tool_call_id", { liveId });
        useChatRuntimeStore.getState().appendLiveMessage({
          role: "tool",
          content: parsed.content ?? message.result ?? "",
          id: liveId,
          toolName: message.tool,
          characterName: message.character_name,
          imageMarkdown: parsed.imageMarkdown,
          downloadInfo: parsed.downloadInfo,
          toolCallMeta: message.tool_call_meta,
          embeddedMessages: message.embedded_messages ?? parsed.embeddedMessages,
          isError: parsed.isError,
        });
      } else {
        useChatRuntimeStore.getState().completeLiveToolCall(
          message.tool_call_id,
          message.tool,
          {
            content: parsed.content ?? message.result ?? "",
            imageMarkdown: parsed.imageMarkdown,
            downloadInfo: parsed.downloadInfo,
            toolCallMeta: message.tool_call_meta,
            embeddedMessages: message.embedded_messages ?? parsed.embeddedMessages,
            isError: parsed.isError,
          },
          message.character_name,
        );
      }
      if (message.consumed_client_message_ids?.length) {
        useChatRuntimeStore.getState().removePendingMessages(message.consumed_client_message_ids);
      }
      return;
    }
    if (message.type === WS_IN.ASSISTANT_MESSAGE) {
      if (streamDoneSeenRef.current) {
        streamDoneSeenRef.current = false;
        return;
      }
      useChatRuntimeStore.getState().appendLiveMessage({
        role: "assistant",
        content: message.content ?? "",
        id: generateUUID(),
        characterName: message.character_name,
        visibleCharacters: message.visible_characters,
        responseCharacters: message.response_characters,
      });
      return;
    }
    if (message.type === WS_IN.ERROR) {
      appendLocalMessage("error", message.message || "未知错误");
      return;
    }
    if (message.type === WS_IN.SYSTEM && typeof message.content === "string") {
      let parsed: Record<string, any> | null = null;
      let isProtocolMeta = false;
      try {
        parsed = JSON.parse(message.content);
      } catch {
        // 普通文本 system 消息继续进入聊天区；协议处理错误不在解析边界吞掉。
      }
      if (parsed?.regenerate_trim === true) {
        const sid = message.session_id;
        if (!sid || sessionRef.current?.sessionId !== sid
          || useChatRuntimeStore.getState().sessionId !== sid) return;
        if (!isRegenerateTrimPayload(parsed)) {
          console.error("Invalid regenerate trim payload");
          sessionRef.current?.showOperationNotice({
            kind: "error",
            message: "\u91cd\u65b0\u751f\u6210\u7684\u5386\u53f2\u622a\u65ad\u901a\u77e5\u65e0\u6548\uff0c\u8bf7\u5237\u65b0\u9875\u9762\u540c\u6b65\u5386\u53f2\u3002",
          });
          return;
        }
        const request = regenerateRequestRef.current;
        if (request && regenerateRequestRef.current === request
          && request.sequence === regenerateRequestSequenceRef.current
          && request.sessionId === sid && request.socket === connRef.current.wsRef.current
          && request.messageIndex === parsed.message_index) {
          request.trimConfirmed = true;
        }
        // 通知后的新流尚未入队；取消旧帧，不能把旧正文刷新到新历史代际。
        frameBufferRef.current?.cancel();
        streamDoneSeenRef.current = false;
        chatRuntimeController.applyRegenerateTrim(sid, parsed);
        return;
      }
      const streamMeta = parsed?.stream_meta;
      if (streamMeta && typeof streamMeta === "object") {
        isProtocolMeta = true;
        if (typeof streamMeta.stream_id === "string" && streamMeta.stream_id
          && Number.isSafeInteger(streamMeta.history_index) && streamMeta.history_index >= 0
          && (!message.session_id || message.session_id === useChatRuntimeStore.getState().sessionId)) {
          useChatRuntimeStore.getState().linkStreamHistory(
            streamMeta.stream_id, streamMeta.history_index,
          );
        }
        if (Array.isArray(streamMeta.live_history_links)) {
          for (const link of streamMeta.live_history_links as HistoryRowLink[]) {
            if (typeof link?.live_id !== "string" || typeof link?.history_row_id !== "string") {
              console.error("无效的live_history_links映射", { link });
              continue;
            }
            useChatRuntimeStore.getState().linkLiveHistory(link.live_id, link.history_row_id);
          }
          useChatRuntimeStore.getState().promoteMappedLiveRows();
        }
      }
      if (parsed?.uploaded) {
        appendLocalMessage("system", `上传成功：${parsed.filename || "文件"} → ${parsed.path}`);
      }
      const isConnectionWelcome = message.content === WS_CONNECTION_WELCOME_TEXT
        && message.index == null && message.is_system_status !== true;
      if (!isConnectionWelcome && !isProtocolMeta && !parsed?.uploaded && (message.is_system_status || !parsed)) {
        const liveId = Number.isSafeInteger(message.index) && (message.index ?? -1) >= 0
          ? `system:${message.index}` : generateUUID();
        useChatRuntimeStore.getState().appendLiveMessage({
          role: "system",
          content: message.content,
          id: liveId,
          messageIndex: message.index,
          isSystemStatus: message.is_system_status,
        });
        if (Number.isSafeInteger(message.index) && (message.index ?? -1) >= 0) {
          useChatRuntimeStore.getState().linkLiveHistory(
            liveId, `history:${message.index}:message`,
          );
          useChatRuntimeStore.getState().promoteMappedLiveRows();
        }
      }
    }
    sessionRef.current?.handleMessage(message);
    subagentRef.current.handleMessage(message, sessionRef.current?.sessionId ?? "");
  }, [appendLocalMessage, handleHistorySync]);

  /**
   * WebSocket 入站消息统一入口。
   * 解码层（wsMessageDecoder）已完成 JSON 解析、流式结构校验与未知类型丢弃；
   * 此处按判别联合的 type 字面量分流：流式事件直接消费，非流事件交给 helpers。
   */
  const handleMessage = useCallback((message: WSMessage) => {
    if (message.type === WS_IN.HISTORY_UPDATED) {
      if (message.session_id !== useChatRuntimeStore.getState().sessionId) return;
      frameBufferRef.current?.flush();
      frameBufferRef.current?.cancel();
      historyHandshakeRef.current = null;
      void chatRuntimeController.reloadHistory(message.session_id);
      return;
    }
    if (message.type === WS_IN.STREAM_DELTA) {
      streamDoneSeenRef.current = false;
      frameBufferRef.current?.push(message);
      return;
    }
    if (message.type === WS_IN.STREAM_DONE) {
      frameBufferRef.current?.flush();
      // stream_id 由解码层校验保证非空，不再猜测缺失 stream_id
      const streamId = message.stream_id;
      const store = useChatRuntimeStore.getState();
      const content = typeof message.content === "string" ? message.content : undefined;
      const finishReason = message.finish_reason || "stop";
      if (hasMountedChatList()) store.queueStreamFinish(streamId, content, message.metrics, finishReason);
      else store.finishStream(streamId, content, message.metrics, false, finishReason);
      streamDoneSeenRef.current = true;
      return;
    }
    handleNonStreamMessage(message);
  }, [handleNonStreamMessage]);

  const newChat = useCallback(() => {
    window.history.replaceState({}, "", "/");
    sessionTransitionRef.current = true;
    conn.disconnect();
    sessionRef.current?.newChat();
    chatRuntimeController.beginSession("");
    conn.connect();
  }, [conn.connect, conn.disconnect]);

  const switchSession = useCallback((sid: string) => {
    if (sessionRef.current?.sessionId === sid) return;
    sessionTransitionRef.current = true;
    window.history.replaceState({}, "", `/?session=${sid}`);
    conn.disconnect();
    sessionRef.current?.switchSession(sid);
    chatRuntimeController.beginSession(sid);
    conn.connect(sid);
  }, [conn.connect, conn.disconnect]);

  const enterColloquy = useCallback(() => switchSession(COLLOQUY_SID), [switchSession]);

  const onOpen = useCallback(() => {
    const runtime = useChatRuntimeStore.getState();
    historyHandshakeRef.current = {
      sessionId: runtime.sessionId, generation: runtime.generation, liveVersion: runtime.liveVersion,
    };
    void llmProfilesRef.current.refreshProfiles().catch(() => {});
    void llmProfilesRef.current.refreshSessionSelection();
    sessionRef.current?.setApprovalModeSyncStatus("loading");
    if (sessionRef.current) sessionRef.current.ignoreStaleRef.current = false;
    sessionRef.current?.fetchSessions();
  }, []);

  const onClose = useCallback(() => {
    // 断线不等同于 Loop 空闲；活动轮询在重连后负责恢复权威状态。
    sessionRef.current?.setApprovalModeSyncStatus("unavailable");
  }, []);

  const onSessionDeleted = useCallback(() => {
    const deletedSid = sessionRef.current?.sessionId;
    if (deletedSid) llmProfilesRef.current.forgetSessionSelection(deletedSid);
    if (deletedSid === COLLOQUY_SID) return;
    switchSession(COLLOQUY_SID);
  }, [switchSession]);

  useEffect(() => {
    conn.setHandlers({
      onOpen,
      onMessage: handleMessage,
      onClose,
      onSessionDeleted,
      onTransportDiagnostic: reportTransportDiagnostic,
    });
  }, [conn, handleMessage, onClose, onOpen, onSessionDeleted, reportTransportDiagnostic]);

  useEffect(() => {
    conn.connect();
    return () => {
      frameBufferRef.current?.cancel();
      chatRuntimeController.abortAll();
      conn.disconnect();
    };
  }, [conn.connect, conn.disconnect]);

  useEffect(() => {
    if (conn.sessionLocked) session.fetchSessions();
  }, [conn.sessionLocked, session.fetchSessions]);

  useEffect(() => {
    if (session.sessionId) fetchToolResourcesRef.current(session.sessionId);
  }, [session.sessionId]);

  const subagentSessions = useMemo(
    () => subagent.subagentSessionsMap[session.sessionId] || {},
    [session.sessionId, subagent.subagentSessionsMap],
  );

  const send = useCallback((
    targetSessions: string[],
    visibleCharacters?: string[],
    responseCharacters?: string[],
  ) => {
    const runtime = useChatRuntimeStore.getState();
    const currentSession = sessionRef.current;
    const currentUpload = uploadRef.current;
    const currentConnection = connRef.current;
    if (!currentSession || !currentUpload || !currentConnection.wsRef.current) return;
    const archived = currentSession.sessions.find((item) => item.id === currentSession.sessionId)?.status === "archived";
    if (archived || currentConnection.wsRef.current.readyState !== WebSocket.OPEN) return;
    const sid = currentSession.sessionId;
    const manager = llmProfilesRef.current;
    if (sessionTransitionRef.current || !sid || runtime.sessionId !== sid || manager.sessionId !== sid) {
      currentSession.showOperationNotice({ kind: "warning", message: "正在切换会话，请稍候再发送。" });
      return;
    }
    const profileName = manager.toProfileName(sid);
    const sendsToMain = targetSessions.length === 0 || targetSessions.includes("main");
    if (sendsToMain && !profileName) {
      currentSession.showOperationNotice({ kind: "warning", message: manager.selectionError
        || (manager.selectionStatus === "loading" ? "正在读取该会话的模型配置，请稍候。" : "请先在顶部栏选择该会话的待用模型。") });
      return;
    }
    const blocks = currentUpload.extractContentBlocks(
      currentUpload.inputRef.current,
      currentUpload.pendingImages,
      currentUpload.pendingAudios,
      currentUpload.pendingVideos,
    );
    if (!blocks.length) return;
    const content: MessageContent = blocks.length === 1 && blocks[0].type === "text"
      ? blocks[0].text
      : blocks;
    const requireToolCall = shouldRequireToolCall(runtime, sendsToMain);
    const clientMessageId = generateUUID();
    runtime.addPendingMessage(clientMessageId, content);
    if (sendsToMain) {
      runtime.beginOptimisticMainSessionActivity(clientMessageId, "user_message");
    }
    const releaseUnsentMessage = () => {
      const current = useChatRuntimeStore.getState();
      if (current.sessionId !== sid) return;
      current.removePendingMessages([clientMessageId]);
      if (sendsToMain) {
        current.cancelOptimisticMainSessionActivity(`local:${clientMessageId}`);
      }
    };
    let sent: boolean;
    try {
      sent = currentConnection.send({
        type: WS_OUT.USER_MESSAGE,
        content,
        target_sessions: targetSessions,
        client_message_id: clientMessageId,
        client_info: collectClientInfo(),
        llm_profile_name: profileName ?? "",
        require_tool_call: requireToolCall,
        ...(visibleCharacters ? { visible_characters: visibleCharacters } : {}),
        ...(responseCharacters ? { response_characters: responseCharacters } : {}),
      });
    } catch (cause) {
      releaseUnsentMessage();
      throw cause;
    }
    if (!sent) {
      releaseUnsentMessage();
      return;
    }
    if (requireToolCall) runtime.clearRequireToolCall(sid);
    runtime.setDraft("", "");
    currentUpload.setPendingImages([]);
    currentUpload.setPendingAudios([]);
    currentUpload.setPendingVideos([]);
    runtime.setProcessing(true);
  }, []);

  const mergeSessions = useCallback(async (sources: string[]) => {
    const newSid = await session.mergeSessions(sources);
    if (newSid) switchSession(newSid);
  }, [session.mergeSessions, switchSession]);

  const branchSession = useCallback(async (sid: string) => {
    const newSid = await sessionRef.current?.mergeSessions([sid]);
    if (newSid) switchSession(newSid);
  }, [switchSession]);

  const deleteSession = useCallback(async (sid: string) => {
    if (!confirm("确定要删除这个会话吗？此操作不可撤销。")) return;
    const activeSessionAtStart = sessionRef.current?.sessionId;
    try {
      const response = await fetch(`/api/sessions/${sid}`, { method: "DELETE" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.deleted) {
        const reason = typeof data.error === "string"
          ? data.error
          : `HTTP ${response.status}`;
        appendLocalMessage("error", `删除会话失败：${reason}`);
        return;
      }
      llmProfilesRef.current.forgetSessionSelection(sid);
      sessionRef.current?.setSessions((previous) => previous.filter((item) => item.id !== sid));
      if (activeSessionAtStart === sid && sessionRef.current?.sessionId === sid) {
        switchSession(COLLOQUY_SID);
      }
    } catch (error) {
      appendLocalMessage(
        "error",
        `删除会话失败：${error instanceof Error ? error.message : "网络错误"}`,
      );
    }
  }, [appendLocalMessage, switchSession]);

  const setApprovalMode = useCallback((mode: ApprovalMode) => {
    const currentSession = sessionRef.current;
    const currentConnection = connRef.current;
    if (!currentSession || currentSession.approvalModeSyncStatus !== "ready") return;
    if (currentConnection.wsRef.current?.readyState === WebSocket.OPEN) {
      currentConnection.send({ type: WS_OUT.HANDSFREE_MODE, content: mode });
      currentSession.setApprovalModeSyncStatus("loading");
    }
  }, []);

  const interrupt = useCallback(async () => {
    const currentSession = sessionRef.current;
    if (!currentSession?.sessionId || currentSession.interruptStatus === "interrupting") return;
    currentSession.setInterruptStatus("interrupting");
    currentSession.clearPendingInteractions();
    try {
      const response = await fetch(`/api/interrupt/${currentSession.sessionId}`, { method: "POST" });
      const data: InterruptResponse = await response.json().catch(() => ({}));
      if (data.status === "cancelled") currentSession.setInterruptStatus("cancelled");
      else if (data.status === "idle") currentSession.setInterruptStatus("idle");
      else currentSession.setInterruptStatus("failed");
      if (data.status === "cancelled" || data.status === "idle") {
        useChatRuntimeStore.getState().clearMainSessionActivityPlaceholders();
      }
    } catch {
      currentSession.setInterruptStatus("failed");
    }
  }, []);

  const disgust = useCallback(() => {
    const sid = sessionRef.current?.sessionId || "unknown";
    appendLocalMessage("system", "用户表达了强烈不满");
    fetch(`/api/disgust/${sid}`, { method: "POST" }).catch(() => {});
  }, [appendLocalMessage]);

  const resume = useCallback(async () => {
    const sid = sessionRef.current?.sessionId;
    if (!sid) return;
    useChatRuntimeStore.getState().beginOptimisticMainSessionActivity(`resume-${Date.now()}`, "resume");
    useChatRuntimeStore.getState().setProcessing(true);
    try {
      const response = await fetch(`/api/sessions/${sid}/resume`, { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.resumed) {
        useChatRuntimeStore.getState().clearMainSessionActivityPlaceholders();
        appendLocalMessage("error", `恢复失败：${data.error || "unknown error"}`);
      }
    } catch (error) {
      useChatRuntimeStore.getState().clearMainSessionActivityPlaceholders();
      appendLocalMessage("error", `恢复失败：${error instanceof Error ? error.message : "网络错误"}`);
    }
  }, [appendLocalMessage]);
  const respondConfirm = useCallback((request: ConfirmRequest | null, action: string, reason?: string, deniedBy?: string) => {
    sessionRef.current?.respondConfirm(request, action, reason, deniedBy);
  }, []);
  const respondAsk = useCallback((request: AskRequest | null, answers?: AskAnswerItem[] | null) => {
    sessionRef.current?.respondAsk(request, answers);
  }, []);

  const editMessage = useCallback(async (id: string, content: MessageContent) => {
    const message = useChatRuntimeStore.getState().contentByRowId[id];
    if (typeof message?.messageIndex !== "number") return;
    const response = await fetch(`/api/sessions/${sessionRef.current?.sessionId}/messages/${message.messageIndex}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (response.status === 409) {
      appendLocalMessage("error", "Agent 正在处理，暂时不能修改历史消息。");
      return;
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.updated) {
      appendLocalMessage("error", `消息编辑失败：${data.error || "unknown error"}`);
      return;
    }
    useChatRuntimeStore.setState((state) => ({
      contentByRowId: {
        ...state.contentByRowId,
        [id]: { ...message, content: data.content ?? content, edited: true },
      },
    }));
  }, [appendLocalMessage]);

  const deleteMessages = useCallback(async (count = 1) => {
    const response = await fetch(`/api/sessions/${sessionRef.current?.sessionId}/messages?count=${count}`, { method: "DELETE" });
    const data = await response.json().catch(() => ({}));
    if (response.status === 409) {
      appendLocalMessage("error", "Agent 正在处理，暂时不能删除历史消息。");
    } else if (response.ok && data.deleted) {
      await chatRuntimeController.invalidateAfterMutation(data.history_count);
    }
  }, [appendLocalMessage]);

  const deleteSingleMessage = useCallback(async (index: number) => {
    const response = await fetch(`/api/sessions/${sessionRef.current?.sessionId}/messages/single?index=${index}`, { method: "DELETE" });
    const data = await response.json().catch(() => ({}));
    if (response.status === 409) {
      appendLocalMessage("error", "Agent 正在处理，暂时不能删除历史消息。");
    } else if (response.ok && data.deleted) {
      await chatRuntimeController.invalidateAfterMutation(data.history_count);
      if (typeof data.token_usage === "number") sessionRef.current?.setTokenUsage(data.token_usage);
      if (typeof data.context_tokens === "number") sessionRef.current?.setContextTokens(data.context_tokens);
    }
  }, [appendLocalMessage]);

  const regenerateResponse = useCallback(async (messageIndex: number) => {
    const sid = sessionRef.current?.sessionId;
    const manager = llmProfilesRef.current;
    const profileName = sid ? manager.toProfileName(sid) : null;
    if (sessionTransitionRef.current || !sid || manager.sessionId !== sid
      || useChatRuntimeStore.getState().sessionId !== sid || !profileName) {
      sessionRef.current?.showOperationNotice({ kind: "warning", message: "请等待会话就绪，并在顶部栏选择待用模型后重新生成。" });
      return;
    }
    const socket = connRef.current.wsRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      sessionRef.current?.showOperationNotice({
        kind: "warning",
        message: "\u8bf7\u7b49\u5f85\u8fde\u63a5\u6062\u590d\u540e\u91cd\u65b0\u751f\u6210",
      });
      return;
    }
    const runtime = useChatRuntimeStore.getState();
    if (isMainSessionBusyForToolCall(runtime)) {
      sessionRef.current?.showOperationNotice({
        kind: "warning",
        message: TOOL_CALL_REQUIREMENT_LABELS.busyRegenerateNotice,
      });
      return;
    }
    const requireToolCall = runtime.requireToolCall;
    const sequence = ++regenerateRequestSequenceRef.current;
    const localId = `regenerate-${sequence}-${messageIndex}-${Date.now()}`;
    const optimisticActivityId = `local:${localId}`;
    useChatRuntimeStore.getState().beginOptimisticMainSessionActivity(localId, "regenerate");
    useChatRuntimeStore.getState().setProcessing(true);
    const request = {
      sequence,
      sessionId: sid,
      socket,
      messageIndex,
      optimisticActivityId: useChatRuntimeStore.getState().mainSessionActivity?.activity_id === optimisticActivityId
        ? optimisticActivityId : null,
      trimConfirmed: false,
    };
    regenerateRequestRef.current = request;
    const ownsRequest = () => regenerateRequestRef.current === request
      && regenerateRequestSequenceRef.current === sequence
      && sessionRef.current?.sessionId === sid
      && useChatRuntimeStore.getState().sessionId === sid
      && connRef.current.wsRef.current === socket;
    const cancelUnconfirmedPlaceholder = () => {
      if (!request.trimConfirmed && request.optimisticActivityId) {
        useChatRuntimeStore.getState().cancelOptimisticMainSessionActivity(request.optimisticActivityId);
      }
    };
    try {
      const responsePromise = fetch(`/api/sessions/${encodeURIComponent(sid)}/regenerate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message_index: messageIndex,
          llm_profile_name: profileName,
          require_tool_call: requireToolCall,
        }),
      });
      if (requireToolCall) runtime.clearRequireToolCall(sid);
      const response = await responsePromise;
      const data = await response.json().catch(() => ({}));
      if (!ownsRequest()) return;
      if (!response.ok || !data.regenerate) {
        cancelUnconfirmedPlaceholder();
        appendLocalMessage("error", `\u91cd\u65b0\u751f\u6210\u5931\u8d25\uff1a${data.error || "unknown error"}`);
      }
    } catch (cause) {
      if (!ownsRequest()) return;
      cancelUnconfirmedPlaceholder();
      sessionRef.current?.showOperationNotice({
        kind: "error",
        message: `\u91cd\u65b0\u751f\u6210\u8bf7\u6c42\u5931\u8d25\uff1a${cause instanceof Error ? cause.message : "\u7f51\u7edc\u9519\u8bef"}`,
      });
    } finally {
      // 只释放仍由本次持有的请求记录，不改变服务端活动或新请求的状态。
      if (regenerateRequestRef.current === request) regenerateRequestRef.current = null;
    }
  }, [appendLocalMessage]);

  const updateMessageVisibility = useCallback(async (messageId: string, visibleCharacters: string[]) => {
    const message = useChatRuntimeStore.getState().contentByRowId[messageId];
    if (typeof message?.messageIndex !== "number") return;
    const response = await fetch(`/api/sessions/${sessionRef.current?.sessionId}/messages/${message.messageIndex}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visible_characters: visibleCharacters }),
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 409) {
      appendLocalMessage("error", "Agent 正在处理，暂时不能修改消息可见性。");
      return;
    }
    if (response.ok && data.updated) {
      useChatRuntimeStore.setState((state) => ({
        contentByRowId: {
          ...state.contentByRowId,
          [messageId]: { ...message, visibleCharacters: data.visible_characters ?? visibleCharacters },
        },
      }));
    }
  }, [appendLocalMessage]);

  useEffect(() => {
    if (!session.sessionId) return;
    const sid = session.sessionId;
    const fetchTasks = () => {
      const owner = sessionRef.current;
      if (!owner || owner.sessionId !== sid) return;
      const scope = { sessionId: sid, generation: owner.resourceScope.generation };
      const shellToken = owner.shellResource.beginRequest();
      const cronToken = owner.cronResource.beginRequest();
      if (shellToken) {
        fetchJsonWithTimeout(
          `/api/sessions/${sid}/shells`, { signal: shellToken.signal },
          { timeoutMs: CRITICAL_TIMEOUT_MS, phase: "shells" },
          (payload) => decodeSessionShells(payload, sid),
        ).then((shells) => {
          if (owner.isResourceScopeCurrent(scope)) owner.shellResource.completeRequest(shellToken, shells);
        }).catch(() => {
          if (owner.isResourceScopeCurrent(scope)) owner.shellResource.failRequest(shellToken, "shells 请求失败");
        });
      }
      if (cronToken) {
        fetchJsonWithTimeout(
          `/api/sessions/${sid}/cron-tasks`, { signal: cronToken.signal },
          { timeoutMs: CRITICAL_TIMEOUT_MS, phase: "cron-tasks" },
          (payload) => decodeSessionCronTasks(payload),
        ).then((tasks) => {
          if (owner.isResourceScopeCurrent(scope)) owner.cronResource.completeRequest(cronToken, tasks);
        }).catch(() => {
          if (owner.isResourceScopeCurrent(scope)) owner.cronResource.failRequest(cronToken, "cron-tasks 请求失败");
        });
      }
      fetchToolResourcesRef.current(sid);
    };
    fetchTasks();
    const interval = setInterval(fetchTasks, TIMING.TASK_POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [session.sessionId]);

  useEffect(() => {
    if (!session.sessionId) return;
    const current = new URLSearchParams(window.location.search).get("session");
    if (current !== session.sessionId) {
      window.history.replaceState({}, "", `/?session=${session.sessionId}`);
    }
  }, [session.sessionId]);

  return {
    status: conn.status,
    waiting: processing,
    pendingConfirms: session.pendingConfirms,
    pendingAsks: session.pendingAsks,
    sessionId: session.sessionId,
    tokenUsage: session.tokenUsage,
    contextTokens: session.contextTokens,
    sessions: session.sessions,
    setSessions: session.setSessions,
    searchQuery: session.searchQuery,
    setSearchQuery: session.setSearchQuery,
    uploading: upload.uploading,
    approvalMode: session.approvalMode,
    approvalModeSyncStatus: session.approvalModeSyncStatus,
    taskProgress: session.taskProgress,
    clipboardDisplays: session.clipboardDisplays,
    dynamicEndpoints: session.dynamicEndpoints,
    subagentSessions,
    llmMaxContextTokens: llmProfiles.activeProfile?.max_context_tokens ?? 0,
    llmModelName: llmProfiles.activeProfile?.model ?? "",
    llmProfiles,
    approvalModelName: llmProfiles.approvalProfileName ?? "",
    approvalModelAvailable: llmProfiles.approvalProfileState.available,
    mergeMode: session.mergeMode,
    setMergeMode: session.setMergeMode,
    selectedForMerge: session.selectedForMerge,
    setSelectedForMerge: session.setSelectedForMerge,
    shells: session.shells,
    setShells: session.setShells,
    cronTasks: session.cronTasks,
    setCronTasks: session.setCronTasks,
    resourceSnapshots: session.resourceSnapshots,
    resourceScope: session.resourceScope,
    subagentIdleCountdown: subagent.subagentIdleCountdown,
    terminatingSessions: session.terminatingSessions,
    generatingTitleSessions: session.generatingTitleSessions,
    generatingTagSessions: session.generatingTagSessions,
    generatingSummarySessions: session.generatingSummarySessions,
    operationNotice: session.operationNotice,
    dismissOperationNotice: session.dismissOperationNotice,
    pendingImages: upload.pendingImages,
    pendingAudios: upload.pendingAudios,
    pendingVideos: upload.pendingVideos,
    allTags: session.allTags,
    agents: session.agents,
    ignoreStaleRef: session.ignoreStaleRef,
    lastRecvAtRef: conn.lastRecvAtRef,
    lastPongAtRef: conn.lastPongAtRef,
    recvTick: conn.recvTick,
    send,
    handleFileUpload: upload.handleFileUpload,
    handleFileInputChange: upload.handleFileInputChange,
    handleUploadClick: upload.handleUploadClick,
    removePendingImage: upload.removePendingImage,
    handlePasteImages: upload.handlePasteImages,
    removePendingAudio: upload.removePendingAudio,
    handlePasteAudios: upload.handlePasteAudios,
    removePendingVideo: upload.removePendingVideo,
    handlePasteVideos: upload.handlePasteVideos,
    inputRef: upload.inputRef,
    fileInputRef: upload.fileInputRef,
    newChat,
    enterColloquy,
    switchSession,
    deleteSession,
    autoTitleSession: session.autoTitleSession,
    autoTagSession: session.autoTagSession,
    regenerateSummary: session.regenerateSummary,
    terminateSession: session.terminateSession,
    togglePinSession: session.togglePinSession,
    renamingSessionId: session.renamingSessionId,
    setRenamingSessionId: session.setRenamingSessionId,
    renameSession: session.renameSession,
    mergeSessions,
    branchSession,
    toggleMergeSelect: session.toggleMergeSelect,
    respondConfirm,
    respondAsk,
    setApprovalMode,
    interrupt,
    disgust,
    resume,
    editMessage,
    deleteMessages,
    deleteSingleMessage,
    regenerateResponse,
    updateMessageVisibility,
    interruptStatus: session.interruptStatus,
    fetchSessions: session.fetchSessions,
    fetchAllTags: session.fetchAllTags,
    updateSessionTags: session.updateSessionTags,
    isReady: conn.status === "已连接",
    sessionLocked: conn.sessionLocked,
    retryConnect: conn.retryConnect,
    sidebarItems: session.sidebarItems,
    expandedClusters: session.expandedClusters,
    toggleCluster: session.toggleCluster,
  };
}
