import { useCallback, useEffect, useMemo, useRef } from "react";
import type {
  ApprovalMode,
  AskRequest,
  ClientDiagnostic,
  ConfirmRequest,
  HistoryRowLink,
  InterruptResponse,
  MessageContent,
  SubagentSession,
  WSMessage,
} from "../types";
import { collectClientInfo } from "../constants/clientInfo";
import { COLLOQUY_SID } from "../constants/session";
import { STORAGE_KEYS } from "../constants/storage";
import { TIMING } from "../constants/timing";
import { WS_IN, WS_OUT } from "../constants/ws";
import { generateUUID, parseToolResult } from "../utils";
import { chatRuntimeController } from "../features/chat/chatRuntimeController";
import { useChatRuntimeStore } from "../features/chat/chatRuntimeStore";
import { hasMountedLiveFooter } from "../features/chat/chatViewport";
import { createStreamFrameBuffer, type StreamFrameBuffer } from "../features/chat/streamFrameBuffer";
import { useLlmProfiles } from "./useLlmProfiles";
import { useSessionStore, type SessionStore } from "./useSessionStore";
import { publishChatAgentspaceEvent } from "../services/chatAgentspaceEventBus";
import { clientDiagnosticFrame, routeChatTransportMessage } from "./chatTransportRouting";
import { useMainSessionActivityPolling } from "../features/chat/useMainSessionActivityPolling";
import { useSubagentManager } from "./useSubagentManager";
import { useUploadManager, type UploadManager } from "./useUploadManager";
import { useWebSocketConnection } from "./useWebSocketConnection";

export type { PendingImage, PendingAudio, PendingVideo } from "./useUploadManager";
export type WebSocketState = ReturnType<typeof useWebSocket>;

function isApprovalMode(value: unknown): value is ApprovalMode {
  return value === "manual" || value === "handsfree" || value === "yolo";
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
  // 只用于阻止切会话期间提交旧身份；不承载新的会话真相源。
  const sessionTransitionRef = useRef(true);

  const fetchToolResourcesRef = useRef(async (sid: string) => {
    if (!sid) return;
    const [toolRes, subagentRes] = await Promise.allSettled([
      fetch(`/api/sessions/${sid}/tool-resources`).then((response) => response.json()),
      fetch(`/api/sessions/${sid}/subagents`).then((response) => response.json()),
    ]);
    if (sessionRef.current?.sessionId !== sid) return;
    if (toolRes.status === "fulfilled") {
      sessionRef.current.setTaskProgress(toolRes.value.task_progress || {});
      sessionRef.current.setClipboardDisplays(toolRes.value.clipboard_display || {});
      sessionRef.current.setDynamicEndpoints(toolRes.value.dynamic_endpoints || []);
    }
    if (subagentRes.status === "fulfilled" && subagentRes.value.subagents) {
      subagentRef.current.mergeSnapshot(sid, {
        subagents: subagentRes.value.subagents as Record<string, SubagentSession>,
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
  useEffect(() => { sessionRef.current = session; }, [session]);
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

  const handleHistorySync = useCallback((message: WSMessage) => {
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
    if (message.processing) useChatRuntimeStore.getState().setProcessing(true);
    if (runtime.sessionId !== sid) {
      chatRuntimeController.beginSession(sid);
      useChatRuntimeStore.setState({ knownHistoryCount: historyCount });
      void chatRuntimeController.initialize(sid, historyCount);
    } else if (runtime.skeleton.length === 0 && !runtime.initialReady) {
      useChatRuntimeStore.setState({ knownHistoryCount: historyCount });
      void chatRuntimeController.initialize(sid, historyCount);
    } else {
      void chatRuntimeController.syncCanonicalHistory(historyCount);
    }
    fetchToolResourcesRef.current(sid);
    sessionRef.current?.fetchSessions();
  }, []);

  const handleMessage = useCallback((message: WSMessage) => {
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
    if (message.type === WS_IN.STREAM_DELTA) {
      streamDoneSeenRef.current = false;
      frameBufferRef.current?.push(message);
      return;
    }
    if (message.type === WS_IN.STREAM_DONE) {
      frameBufferRef.current?.flush();
      const streamId = message.stream_id || useChatRuntimeStore.getState().currentStreamId || "";
      if (streamId) {
        const store = useChatRuntimeStore.getState();
        const content = typeof message.content === "string" ? message.content : undefined;
        const finishReason = message.finish_reason || "stop";
        if (hasMountedLiveFooter()) store.queueStreamFinish(streamId, content, message.metrics, finishReason);
        else store.finishStream(streamId, content, message.metrics, false, finishReason);
      }
      streamDoneSeenRef.current = true;
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
      } catch {
        // 普通文本 system 消息继续进入聊天区；协议 JSON 不作为聊天正文渲染。
      }
      if (!isProtocolMeta && !parsed?.uploaded && (message.is_system_status || !parsed)) {
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
    const clientMessageId = generateUUID();
    runtime.addPendingMessage(clientMessageId, content);
    if (sendsToMain) {
      runtime.beginOptimisticMainSessionActivity(clientMessageId, "user_message");
    }
    currentConnection.send({
      type: WS_OUT.USER_MESSAGE,
      content,
      target_sessions: targetSessions,
      client_message_id: clientMessageId,
      client_info: collectClientInfo(),
      llm_profile_name: profileName ?? "",
      ...(visibleCharacters ? { visible_characters: visibleCharacters } : {}),
      ...(responseCharacters ? { response_characters: responseCharacters } : {}),
    });
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
  const respondAsk = useCallback((request: AskRequest | null, option?: string, customText?: string) => {
    sessionRef.current?.respondAsk(request, option, customText);
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
    useChatRuntimeStore.getState().beginOptimisticMainSessionActivity(`regenerate-${messageIndex}-${Date.now()}`, "regenerate");
    useChatRuntimeStore.getState().setProcessing(true);
    try {
      const response = await fetch(`/api/sessions/${encodeURIComponent(sid)}/regenerate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_index: messageIndex, llm_profile_name: profileName }),
      });
      const data = await response.json().catch(() => ({}));
      if (sessionRef.current?.sessionId !== sid || useChatRuntimeStore.getState().sessionId !== sid) return;
      if (!response.ok || !data.regenerate) {
        useChatRuntimeStore.getState().clearMainSessionActivityPlaceholders();
        appendLocalMessage("error", `重新生成失败：${data.error || "unknown error"}`);
      }
    } catch (cause) {
      if (sessionRef.current?.sessionId !== sid || useChatRuntimeStore.getState().sessionId !== sid) return;
      useChatRuntimeStore.getState().clearMainSessionActivityPlaceholders();
      sessionRef.current?.showOperationNotice({ kind: "error", message: `重新生成请求失败：${cause instanceof Error ? cause.message : "网络错误"}` });
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
      fetch(`/api/sessions/${sid}/shells`).then((response) => response.json())
        .then((data) => sessionRef.current?.setShells(data.shells || [])).catch(() => {});
      fetch(`/api/sessions/${sid}/cron-tasks`).then((response) => response.json())
        .then((data) => sessionRef.current?.setCronTasks(data.tasks || [])).catch(() => {});
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
