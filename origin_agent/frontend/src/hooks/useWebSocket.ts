import { useCallback, useEffect, useMemo, useRef } from "react";
import { MessageContent, WSMessage, SubagentSession } from "../types";
import { generateUUID } from "../utils";
import { useWebSocketConnection } from "./useWebSocketConnection";
import { useSessionStore } from "./useSessionStore";
import { useUploadManager } from "./useUploadManager";
import { useSubagentManager } from "./useSubagentManager";
import type { SessionStore } from "./useSessionStore";
import type { UploadManager } from "./useUploadManager";

export type { PendingImage } from "./useUploadManager";
export type WebSocketState = ReturnType<typeof useWebSocket>;

export function useWebSocket() {
  const conn = useWebSocketConnection();
  const subagent = useSubagentManager();

  const connRef = useRef(conn);
  const sessionRef = useRef<SessionStore | null>(null);
  const uploadRef = useRef<UploadManager | null>(null);
  const subagentRef = useRef(subagent);

  // ── cross-cutting resource fetcher ──
  const fetchToolResourcesRef = useRef(async (sid: string) => {
    if (!sid) return;
    const [toolRes, subagentRes] = await Promise.allSettled([
      fetch(`/api/sessions/${sid}/tool-resources`).then((r) => r.json()),
      fetch(`/api/sessions/${sid}/subagents`).then((r) => r.json()),
    ]);
    const activeSid = localStorage.getItem("evolve_session_id") || sid;
    if (activeSid !== sid) return;
    if (toolRes.status === "fulfilled") {
      const data = toolRes.value;
      sessionRef.current?.setTaskProgress(data.task_progress || {});
      sessionRef.current?.setClipboardDisplays(data.clipboard_display || {});
    }
    if (subagentRes.status === "fulfilled") {
      const data = subagentRes.value;
      if (data.subagents) {
        subagentRef.current.mergeSnapshot(sid, { subagents: data.subagents as Record<string, SubagentSession> });
      }
    }
  });

  const session = useSessionStore({
    onSessionHistory: (sid: string) => fetchToolResourcesRef.current(sid),
    onSessionRotated: (_newSid: string, oldSid: string) => {
      subagentRef.current.setSubagentSessionsMap((prev) => ({ ...prev, [oldSid]: {} }));
    },
  });
  const upload = useUploadManager({
    wsRef: conn.wsRef,
    sessions: session.sessions,
    sessionId: session.sessionId,
    addMessage: session.addMessage,
  });

  useEffect(() => { connRef.current = conn; }, [conn]);
  useEffect(() => { sessionRef.current = session; }, [session]);
  useEffect(() => { uploadRef.current = upload; }, [upload]);
  useEffect(() => { subagentRef.current = subagent; }, [subagent]);

  // ── scroll anchors ──
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const chatAreaRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const isAtBottomRef = useRef(true);
  const instantScrollRef = useRef(false);
  const programmaticScrollingRef = useRef(false);
  const lastScrollTopRef = useRef(0);
  const lastMessageCountRef = useRef(0);

  // ── websocket handlers ──
  const handleMessage = useCallback((msg: WSMessage) => {
    sessionRef.current?.handleMessage(msg);
    subagentRef.current.handleMessage(msg, sessionRef.current?.sessionId ?? "");
  }, []);

  const onOpen = useCallback(() => {
    if (!sessionRef.current) return;
    sessionRef.current.ignoreStaleRef.current = false;
    isAtBottomRef.current = true;
    instantScrollRef.current = true;
    sessionRef.current.addMessage("system", "已连接到 Evolve Agent");
    sessionRef.current.fetchSessions();
  }, []);

  const onClose = useCallback(() => {
    sessionRef.current?.setWaiting(false);
  }, []);

  useEffect(() => {
    conn.setHandlers({ onOpen, onMessage: handleMessage, onClose });
  }, [conn, onOpen, handleMessage, onClose]);

  // ── connect on mount ──
  useEffect(() => {
    const lastSid = localStorage.getItem("evolve_session_id") || "";
    conn.connect(lastSid);
    return () => conn.disconnect();
  }, [conn.connect, conn.disconnect]);

  // ── fetch tool resources when session changes ──
  useEffect(() => {
    if (!session.sessionId) return;
    fetchToolResourcesRef.current(session.sessionId);
  }, [session.sessionId]);

  const subagentSessions = useMemo(
    () => subagent.subagentSessionsMap[session.sessionId] || {},
    [subagent.subagentSessionsMap, session.sessionId]
  );

  // ── scroll helpers ──
  const handleUserScroll = useCallback(() => {
    const chat = chatAreaRef.current;
    if (!chat) return;
    if (programmaticScrollingRef.current) {
      lastScrollTopRef.current = chat.scrollTop;
      return;
    }
    const currentScrollTop = chat.scrollTop;
    const previousScrollTop = lastScrollTopRef.current;
    const isAtBottom = chat.scrollHeight - currentScrollTop - chat.clientHeight <= 1;
    if (currentScrollTop < previousScrollTop) {
      isAtBottomRef.current = false;
    } else if (currentScrollTop > previousScrollTop && isAtBottom) {
      isAtBottomRef.current = true;
    }
    lastScrollTopRef.current = currentScrollTop;
  }, []);

  const attachScrollListener = useCallback(() => {
    const chat = chatAreaRef.current;
    if (!chat) return () => {};
    lastScrollTopRef.current = chat.scrollTop;
    const onScroll = () => handleUserScroll();
    chat.addEventListener("scroll", onScroll, { passive: true });
    return () => chat.removeEventListener("scroll", onScroll);
  }, [handleUserScroll]);

  const scrollToBottomIfAtBottom = useCallback((force = false) => {
    const chat = chatAreaRef.current;
    if (!chat) return;
    if (force || isAtBottomRef.current) {
      const behavior = instantScrollRef.current ? "auto" : "smooth";
      instantScrollRef.current = false;
      programmaticScrollingRef.current = true;
      chat.scrollTo({ top: chat.scrollHeight, behavior });
      lastScrollTopRef.current = chat.scrollTop;
      programmaticScrollingRef.current = false;
    } else {
      instantScrollRef.current = false;
    }
  }, []);

  // ── message sending ──
  const send = useCallback((
    targetSessions: string[],
    visible_characters?: string[],
    response_characters?: string[],
  ) => {
    const s = sessionRef.current;
    const u = uploadRef.current;
    const c = connRef.current;
    if (!s || !u) return;
    const isArchived = s.sessions.find((sess) => sess.id === s.sessionId)?.status === "archived";
    if (!c.wsRef.current || s.waiting || c.wsRef.current.readyState !== WebSocket.OPEN || isArchived) return;

    const blocks = u.extractContentBlocks(u.inputRef.current, u.pendingImages);
    const hasContent = blocks.length > 0;
    if (!hasContent) return;

    const content: MessageContent = blocks.length === 1 && blocks[0].type === "text" ? blocks[0].text : blocks;
    const clientMessageId = generateUUID();

    s.setMessages((prev) => [...prev, {
      role: "user",
      content,
      id: clientMessageId,
      clientMessageId,
      visibleCharacters: visible_characters,
      responseCharacters: response_characters,
    }]);

    c.send({
      type: "user_message",
      content,
      target_sessions: targetSessions,
      client_message_id: clientMessageId,
      ...(visible_characters ? { visible_characters } : {}),
      ...(response_characters ? { response_characters } : {}),
    });
    s.setInput("");
    u.setPendingImages([]);
    s.setWaiting(true);
    s.ignoreStaleRef.current = false;
    s.streamDoneRef.current = false;
    isAtBottomRef.current = true;
    instantScrollRef.current = true;
    scrollToBottomIfAtBottom(true);
  }, []);

  // ── actions ──
  const newChat = useCallback(() => {
    if (!sessionRef.current) return;
    connRef.current.disconnect();
    sessionRef.current.newChat();
    connRef.current.connect();
  }, []);

  const switchSession = useCallback((sid: string) => {
    if (!sessionRef.current) return;
    connRef.current.disconnect();
    sessionRef.current.switchSession(sid);
    connRef.current.connect(sid);
  }, []);

  const mergeSessions = useCallback(async (sources: string[]) => {
    if (!sessionRef.current) return;
    const newSid = await session.mergeSessions(sources);
    if (newSid) {
      connRef.current.disconnect();
      sessionRef.current.switchSession(newSid);
      connRef.current.connect(newSid);
    }
  }, [session.mergeSessions]);

  const branchSession = useCallback(async (sid: string) => {
    if (!sessionRef.current) return;
    const newSid = await sessionRef.current.mergeSessions([sid]);
    if (newSid) {
      connRef.current.disconnect();
      sessionRef.current.switchSession(newSid);
      connRef.current.connect(newSid);
    }
  }, []);

  const deleteSession = useCallback((sid: string) => {
    if (!sessionRef.current) return;
    if (!confirm("确定要删除这个会话吗？此操作不可撤销。")) return;
    const s = sessionRef.current;
    const wasActive = sid === s.sessionId;
    fetch(`/api/sessions/${sid}`, { method: "DELETE" })
      .then(() => {
        const remaining = s.sessions.filter((sess) => sess.id !== sid);
        s.setSessions(remaining);
        if (wasActive) {
          if (remaining.length > 0) {
            switchSession(remaining[0].id);
          } else {
            newChat();
          }
        }
      })
      .catch(() => {});
  }, [newChat, switchSession]);

  const toggleHandsfree = useCallback((enabled: boolean) => {
    const s = sessionRef.current;
    const c = connRef.current;
    if (!s) return;
    s.setHandsfreeMode(enabled);
    if (c.wsRef.current?.readyState === WebSocket.OPEN) {
      c.send({
        type: "handsfree_mode",
        content: enabled ? "true" : "false",
      });
    }
  }, []);

  const interrupt = useCallback(() => {
    const s = sessionRef.current;
    if (!s) return;
    s.ignoreStaleRef.current = true;
    s.setWaiting(false);
    const streamed = s.streamingMessageRef.current;
    s.setStreamingMessage(null);
    s.setMessages((prev) => {
      let next = prev;
      if (streamed) {
        const exists = prev.some((x) => x.id === streamed.id);
        next = exists ? prev.map((x) => (x.id === streamed.id ? streamed : x)) : [...prev, streamed];
      }
      return [...next, { role: "system" as const, content: "⏹ 已中断", id: generateUUID() }];
    });
    fetch(`/api/interrupt/${s.sessionId || "unknown"}`, { method: "POST" }).catch(() => {});
  }, []);

  const respondConfirm = useCallback((action: string, denyReasonText?: string, deniedBy?: string) => {
    const s = sessionRef.current;
    if (!s) return;
    s.respondConfirm(s.pendingConfirm, action, denyReasonText, deniedBy);
  }, []);

  const respondAsk = useCallback((option?: string, customText?: string) => {
    const s = sessionRef.current;
    if (!s) return;
    s.respondAsk(s.pendingAsk, option, customText);
  }, []);

  // ── drawer polling ──
  useEffect(() => {
    if (!session.sessionId) return;
    const sid = session.sessionId;
    const fetchTasks = () => {
      fetch(`/api/sessions/${sid}/background-tasks`)
        .then((r) => r.json())
        .then((d) => sessionRef.current?.setBgTasks(d.tasks || []))
        .catch(() => {});
      fetch(`/api/sessions/${sid}/cron-tasks`)
        .then((r) => r.json())
        .then((d) => sessionRef.current?.setCronTasks(d.tasks || []))
        .catch(() => {});
    };
    fetchTasks();
    const iv = setInterval(fetchTasks, 3000);
    return () => clearInterval(iv);
  }, [session.sessionId]);

  // ── auto scroll ──
  useEffect(() => {
    const previousCount = lastMessageCountRef.current;
    lastMessageCountRef.current = session.messages.length;
    if (session.messages.length === 0 || session.messages.length <= previousCount) return;
    scrollToBottomIfAtBottom();
  }, [session.messages.length, scrollToBottomIfAtBottom]);

  useEffect(() => {
    if (session.streamingMessage?.content || session.streamingMessage?.reasoningContent) {
      scrollToBottomIfAtBottom();
    }
  }, [session.streamingMessage?.content, session.streamingMessage?.reasoningContent, scrollToBottomIfAtBottom]);

  // ── ResizeObserver 追底: 异步渲染导致内容高度增长时自动追底 ──
  useEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    const observer = new ResizeObserver(() => {
      if (isAtBottomRef.current) {
        instantScrollRef.current = true;
        scrollToBottomIfAtBottom(true);
      }
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [scrollToBottomIfAtBottom]);

  return {
    // state
    messages: session.messages,
    setMessages: session.setMessages,
    input: session.input,
    setInput: session.setInput,
    status: conn.status,
    waiting: session.waiting,
    setWaiting: session.setWaiting,
    pendingConfirm: session.pendingConfirm,
    setPendingConfirm: session.setPendingConfirm,
    denyReason: session.denyReason,
    setDenyReason: session.setDenyReason,
    pendingAsk: session.pendingAsk,
    setPendingAsk: session.setPendingAsk,
    askCustomText: session.askCustomText,
    setAskCustomText: session.setAskCustomText,
    askSelectedOption: session.askSelectedOption,
    setAskSelectedOption: session.setAskSelectedOption,
    sessionId: session.sessionId,
    tokenUsage: session.tokenUsage,
    contextTokens: session.contextTokens,
    sessions: session.sessions,
    setSessions: session.setSessions,
    searchQuery: session.searchQuery,
    setSearchQuery: session.setSearchQuery,
    uploading: upload.uploading,
    handsfreeMode: session.handsfreeMode,
    setHandsfreeMode: session.setHandsfreeMode,
    taskProgress: session.taskProgress,
    setTaskProgress: session.setTaskProgress,
    clipboardDisplays: session.clipboardDisplays,
    setClipboardDisplays: session.setClipboardDisplays,
    subagentSessions,
    llmMaxContextTokens: session.llmMaxContextTokens,
    llmModelName: session.llmModelName,
    approvalModelName: session.approvalModelName,
    approvalModelAvailable: session.approvalModelAvailable,
    mergeMode: session.mergeMode,
    setMergeMode: session.setMergeMode,
    selectedForMerge: session.selectedForMerge,
    setSelectedForMerge: session.setSelectedForMerge,
    bgTasks: session.bgTasks,
    setBgTasks: session.setBgTasks,
    cronTasks: session.cronTasks,
    setCronTasks: session.setCronTasks,
    subagentIdleCountdown: subagent.subagentIdleCountdown,
    terminatingSessions: session.terminatingSessions,
    generatingTitleSessions: session.generatingTitleSessions,
    generatingTagSessions: session.generatingTagSessions,
    pendingImages: upload.pendingImages,
    streamingMessage: session.streamingMessage,
    allTags: session.allTags,
    agents: session.agents,
    ignoreStaleRef: session.ignoreStaleRef,
    lastRecvAtRef: conn.lastRecvAtRef,
    lastPongAtRef: conn.lastPongAtRef,
    recvTick: conn.recvTick,
    // actions
    send,
    handleFileUpload: upload.handleFileUpload,
    handleFileInputChange: upload.handleFileInputChange,
    handleUploadClick: upload.handleUploadClick,
    addPendingImage: upload.addPendingImage,
    removePendingImage: upload.removePendingImage,
    handlePasteImages: upload.handlePasteImages,
    inputRef: upload.inputRef,
    newChat,
    switchSession,
    deleteSession,
    autoTitleSession: session.autoTitleSession,
    autoTagSession: session.autoTagSession,
    regenerateSummary: session.regenerateSummary,
    terminateSession: session.terminateSession,
    togglePinSession: session.togglePinSession,
    mergeSessions,
    branchSession,
    toggleMergeSelect: session.toggleMergeSelect,
    respondConfirm,
    respondAsk,
    toggleHandsfree,
    interrupt,
    toggleMessageCollapse: session.toggleMessageCollapse,
    editMessage: session.editMessage,
    deleteMessages: session.deleteMessages,
    regenerateResponse: session.regenerateResponse,
    updateMessageVisibility: session.updateMessageVisibility,
    addMessage: session.addMessage,
    fetchSessions: session.fetchSessions,
    fetchAllTags: session.fetchAllTags,
    connect: conn.connect,
    updateSessionTags: session.updateSessionTags,
    attachScrollListener,
    scrollToBottomIfAtBottom,
    // refs
    wsRef: conn.wsRef,
    bottomRef,
    chatAreaRef,
    contentRef,
    isAtBottomRef,
    instantScrollRef,
    fileInputRef: upload.fileInputRef,
    // computed
    sidebarItems: session.sidebarItems,
    expandedClusters: session.expandedClusters,
    toggleCluster: session.toggleCluster,
    sessionResources: session.sessionResources,
  };
}