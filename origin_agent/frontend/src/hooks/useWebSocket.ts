import { useCallback, useEffect, useMemo, useRef } from "react";
import type {
  ApprovalMode,
  AskRequest,
  ConfirmRequest,
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
  const llmProfiles = useLlmProfiles();
  const llmProfilesRef = useRef(llmProfiles);

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

  const handleHistorySync = useCallback((message: WSMessage) => {
    const sid = message.session_id || sessionRef.current?.sessionId || "";
    if (!sid) return;
    if (sessionRef.current?.sessionId !== sid) {
      sessionRef.current?.setSessionId(sid);
      localStorage.setItem(STORAGE_KEYS.SESSION_ID, sid);
    }
    const runtime = useChatRuntimeStore.getState();
    if (typeof message.token_usage === "number") sessionRef.current?.setTokenUsage(message.token_usage);
    if (typeof message.context_tokens === "number") sessionRef.current?.setContextTokens(message.context_tokens);
    if (Array.isArray(message.agents)) sessionRef.current?.setAgents(message.agents);
    else if (message.agents === null) sessionRef.current?.setAgents([]);
    const historyCount = message.history_count ?? 0;
    useChatRuntimeStore.getState().setProcessing(Boolean(message.processing));
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
    if (message.type === WS_IN.LLM_PROFILE_CHANGED) {
      llmProfilesRef.current.handleProfileChanged(message);
      return;
    }
    if (message.type === WS_IN.APPROVAL_PROFILE_CHANGED) {
      llmProfilesRef.current.handleApprovalProfileChanged(message);
      if (message.handsfree_mode === false) {
        sessionRef.current?.setApprovalMode("manual");
        sessionRef.current?.setApprovalModeSyncStatus("ready");
      }
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
        if (hasMountedLiveFooter()) store.queueStreamFinish(streamId, content, message.metrics);
        else store.finishStream(streamId, content, message.metrics, false);
      }
      streamDoneSeenRef.current = true;
      return;
    }
    if (message.type === WS_IN.USER_MESSAGE) {
      const clientId = message.client_message_id;
      useChatRuntimeStore.getState().appendLiveMessage({
        role: "user",
        content: message.content ?? "",
        id: clientId || generateUUID(),
        clientMessageId: clientId,
        characterName: message.character_name,
        messageIndex: message.index,
        visibleCharacters: message.visible_characters,
        responseCharacters: message.response_characters,
        messageSuffix: message.message_suffix,
        dynamicMessageSuffix: message.dynamic_message_suffix,
      });
      if (clientId) useChatRuntimeStore.getState().removePendingMessages([clientId]);
      return;
    }
    if (message.type === WS_IN.TOOL_CALL) {
      frameBufferRef.current?.flush();
      useChatRuntimeStore.getState().appendLiveMessage({
        role: "tool",
        content: `${message.character_name ? `${message.character_name} ` : ""}⚡ ${message.tool || "tool"}`,
        id: message.tool_call_id || generateUUID(),
        toolName: message.tool,
        toolArgs: message.args,
        characterName: message.character_name,
      });
      return;
    }
    if (message.type === WS_IN.TOOL_RESULT) {
      frameBufferRef.current?.flush();
      const parsed = parseToolResult(message.result ?? "", message.tool);
      useChatRuntimeStore.getState().appendLiveMessage({
        role: "tool",
        content: parsed.content ?? message.result ?? "",
        id: generateUUID(),
        toolName: message.tool,
        characterName: message.character_name,
        imageMarkdown: parsed.imageMarkdown,
        downloadInfo: parsed.downloadInfo,
        toolCallMeta: message.tool_call_meta,
        isError: parsed.isError,
      });
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
      try {
        const parsed = JSON.parse(message.content);
        const streamMeta = parsed?.stream_meta;
        if (streamMeta && typeof streamMeta.stream_id === "string" && streamMeta.stream_id
          && Number.isSafeInteger(streamMeta.history_index) && streamMeta.history_index >= 0
          && (!message.session_id || message.session_id === useChatRuntimeStore.getState().sessionId)) {
          useChatRuntimeStore.getState().linkStreamHistory(streamMeta.stream_id, streamMeta.history_index);
        }
        if (parsed.uploaded) {
          appendLocalMessage("system", `上传成功：${parsed.filename || "文件"} → ${parsed.path}`);
        }
      } catch {
        // 普通 system 文本继续交由会话元数据 store 处理。
      }
    }
    sessionRef.current?.handleMessage(message);
    subagentRef.current.handleMessage(message, sessionRef.current?.sessionId ?? "");
  }, [appendLocalMessage, handleHistorySync]);

  const onOpen = useCallback(() => {
    sessionRef.current?.setApprovalModeSyncStatus("loading");
    if (sessionRef.current) sessionRef.current.ignoreStaleRef.current = false;
    sessionRef.current?.fetchSessions();
  }, []);

  const onClose = useCallback(() => {
    useChatRuntimeStore.getState().setProcessing(false);
    sessionRef.current?.setApprovalModeSyncStatus("unavailable");
  }, []);

  useEffect(() => {
    conn.setHandlers({ onOpen, onMessage: handleMessage, onClose });
  }, [conn, handleMessage, onClose, onOpen]);

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
    currentConnection.send({
      type: WS_OUT.USER_MESSAGE,
      content,
      target_sessions: targetSessions,
      client_message_id: clientMessageId,
      client_info: collectClientInfo(),
      llm_profile_name: llmProfilesRef.current.toProfileName(),
      ...(visibleCharacters ? { visible_characters: visibleCharacters } : {}),
      ...(responseCharacters ? { response_characters: responseCharacters } : {}),
    });
    runtime.setDraft("", "");
    currentUpload.setPendingImages([]);
    currentUpload.setPendingAudios([]);
    currentUpload.setPendingVideos([]);
    runtime.setProcessing(true);
  }, []);

  const newChat = useCallback(() => {
    window.history.replaceState({}, "", "/");
    conn.disconnect();
    sessionRef.current?.newChat();
    chatRuntimeController.beginSession("");
    conn.connect();
  }, [conn.connect, conn.disconnect]);

  const switchSession = useCallback((sid: string) => {
    window.history.replaceState({}, "", `/?session=${sid}`);
    conn.disconnect();
    sessionRef.current?.switchSession(sid);
    chatRuntimeController.beginSession(sid);
    conn.connect(sid);
  }, [conn.connect, conn.disconnect]);

  const enterColloquy = useCallback(() => switchSession(COLLOQUY_SID), [switchSession]);

  const mergeSessions = useCallback(async (sources: string[]) => {
    const newSid = await session.mergeSessions(sources);
    if (newSid) switchSession(newSid);
  }, [session.mergeSessions, switchSession]);

  const branchSession = useCallback(async (sid: string) => {
    const newSid = await sessionRef.current?.mergeSessions([sid]);
    if (newSid) switchSession(newSid);
  }, [switchSession]);

  const deleteSession = useCallback((sid: string) => {
    if (!confirm("确定要删除这个会话吗？此操作不可撤销。")) return;
    const wasActive = sid === sessionRef.current?.sessionId;
    fetch(`/api/sessions/${sid}`, { method: "DELETE" })
      .then(() => {
        sessionRef.current?.setSessions((previous) => previous.filter((item) => item.id !== sid));
        if (wasActive) switchSession(COLLOQUY_SID);
      })
      .catch(() => {});
  }, [switchSession]);

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
        useChatRuntimeStore.getState().setProcessing(false);
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
    useChatRuntimeStore.getState().setProcessing(true);
    try {
      const response = await fetch(`/api/sessions/${sid}/resume`, { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.resumed) {
        useChatRuntimeStore.getState().setProcessing(false);
        appendLocalMessage("error", `恢复失败：${data.error || "unknown error"}`);
      }
    } catch (error) {
      useChatRuntimeStore.getState().setProcessing(false);
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
    useChatRuntimeStore.getState().setProcessing(true);
    const response = await fetch(`/api/sessions/${sessionRef.current?.sessionId}/regenerate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message_index: messageIndex,
        llm_profile_name: llmProfilesRef.current.toProfileName(),
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.regenerate) {
      useChatRuntimeStore.getState().setProcessing(false);
      appendLocalMessage("error", `重新生成失败：${data.error || "unknown error"}`);
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
