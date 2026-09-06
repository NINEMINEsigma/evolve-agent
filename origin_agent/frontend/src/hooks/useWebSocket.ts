import { useCallback, useEffect, useMemo, useRef } from "react";
import { MessageContent, WSMessage, SubagentSession, AskRequest, ConfirmRequest } from "../types";
import { generateUUID } from "../utils";
import { WS_IN, WS_OUT } from "../constants/ws";
import { COLLOQUY_SID } from "../constants/session";
import { TIMING } from "../constants/timing";
import { DIMENSIONS } from "../constants/dimensions";
import { collectClientInfo } from "../constants/clientInfo";
import { useWebSocketConnection } from "./useWebSocketConnection";
import { useSessionStore } from "./useSessionStore";
import { useUploadManager } from "./useUploadManager";
import { useSubagentManager } from "./useSubagentManager";
import { useLlmProfiles } from "./useLlmProfiles";
import type { SessionStore } from "./useSessionStore";
import type { UploadManager } from "./useUploadManager";

export type { PendingImage, PendingAudio, PendingVideo } from "./useUploadManager";
export type WebSocketState = ReturnType<typeof useWebSocket>;

const NESTED_SCROLL_SELECTOR = [
  ".tool-call-detail",
  ".message-content-collapsed",
  ".reasoning-content",
  ".context-extension-content",
].join(", ");
const HANDOFF_SCROLL_SELECTOR = ".tool-call-detail, .message-content-collapsed";

function eventTargetElement(target: EventTarget | null): Element | null {
  return target instanceof Element ? target : null;
}

function findScrollableElement(target: EventTarget | null, selector: string): HTMLElement | null {
  let current = eventTargetElement(target);
  while (current) {
    if (current instanceof HTMLElement && current.matches(selector) && current.scrollHeight > current.clientHeight) {
      return current;
    }
    current = current.parentElement;
  }
  return null;
}

function findNestedScrollContainer(target: EventTarget | null): HTMLElement | null {
  return findScrollableElement(target, NESTED_SCROLL_SELECTOR);
}

function isInsideNestedScrollContainer(target: EventTarget | null): boolean {
  return findNestedScrollContainer(target) !== null;
}

function isNestedHandoffTargetAtBoundary(target: EventTarget | null, deltaY: number): boolean {
  const container = findNestedScrollContainer(target);
  if (!container || !container.matches(HANDOFF_SCROLL_SELECTOR) || deltaY === 0) return false;
  const atTop = container.scrollTop <= 0;
  const atBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 1;
  return (deltaY < 0 && atTop) || (deltaY > 0 && atBottom);
}

const KEYBOARD_SCROLL_KEYS = new Set([
  "ArrowDown",
  "ArrowUp",
  "End",
  "Home",
  "PageDown",
  "PageUp",
  " ",
]);

function isKeyboardScrollTarget(target: EventTarget | null, chat: HTMLElement): boolean {
  const element = eventTargetElement(target);
  if (!element || !chat.contains(element)) return false;
  return element.closest("input, textarea, button, [contenteditable=\"true\"]") === null;
}

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
    const activeSid = sessionRef.current?.sessionId;
    // sessionId 为空（newChat 后新 sid 未返回）时拒绝应用任何 in-flight 数据，
    // 否则旧会话资源会串入新会话（原 `|| sid` 竞态缺陷）
    if (!activeSid || activeSid !== sid) return;
    if (toolRes.status === "fulfilled") {
      const data = toolRes.value;
      sessionRef.current?.setTaskProgress(data.task_progress || {});
      sessionRef.current?.setClipboardDisplays(data.clipboard_display || {});
      sessionRef.current?.setDynamicEndpoints(data.dynamic_endpoints || []);
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
  const llmProfiles = useLlmProfiles();

  useEffect(() => { connRef.current = conn; }, [conn]);
  useEffect(() => { sessionRef.current = session; }, [session]);
  useEffect(() => { uploadRef.current = upload; }, [upload]);
  useEffect(() => { subagentRef.current = subagent; }, [subagent]);

  const llmProfilesRef = useRef(llmProfiles);
  useEffect(() => { llmProfilesRef.current = llmProfiles; }, [llmProfiles]);

  // ── scroll anchors ──
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const chatAreaRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const isAtBottomRef = useRef(true);
  const programmaticScrollingRef = useRef(false);
  const scrollGenerationRef = useRef(0);
  const pendingScrollFrameRef = useRef<number | null>(null);
  const pendingScrollForceRef = useRef(false);
  const programmaticResetFrameRef = useRef<number | null>(null);
  const observerRetryFrameRef = useRef<number | null>(null);
  const userScrollIntentUntilRef = useRef(0);
  const userScrollIntentTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const nestedHandoffUntilRef = useRef(0);
  const smoothScrollCleanupRef = useRef<(() => void) | null>(null);
  const scrollListenerCleanupRef = useRef<(() => void) | null>(null);
  const scrollSessionIdRef = useRef(session.sessionId);

  // ── websocket handlers ──
  const handleMessage = useCallback((msg: WSMessage) => {
    if (msg.type === WS_IN.LLM_PROFILE_CHANGED) {
      llmProfilesRef.current.handleProfileChanged(msg);
      return;
    }
    if (msg.type === WS_IN.APPROVAL_PROFILE_CHANGED) {
      llmProfilesRef.current.handleApprovalProfileChanged(msg);
      if (msg.handsfree_mode === false) {
        sessionRef.current?.setHandsfreeMode(false);
      }
      return;
    }
    if (msg.type === WS_IN.HANDSFREE_MODE) {
      if (msg.handsfree_mode !== undefined && msg.handsfree_mode !== null) {
        sessionRef.current?.setHandsfreeMode(msg.handsfree_mode);
      }
      if (msg.approval_mode !== undefined && msg.approval_mode !== null) {
        sessionRef.current?.setApprovalMode(msg.approval_mode);
        sessionRef.current?.setYoloMode(msg.approval_mode === "yolo");
      }
      return;
    }
    sessionRef.current?.handleMessage(msg);
    subagentRef.current.handleMessage(msg, sessionRef.current?.sessionId ?? "");
  }, []);

  const onOpen = useCallback(() => {
    if (!sessionRef.current) return;
    sessionRef.current.ignoreStaleRef.current = false;
    isAtBottomRef.current = true;
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
    conn.connect();
    return () => conn.disconnect();
  }, [conn.connect, conn.disconnect]);

  // ── fetch sessions when locked, so sidebar shows available sessions ──
  useEffect(() => {
    if (conn.sessionLocked) {
      session.fetchSessions();
    }
  }, [conn.sessionLocked]);

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
  const resetProgrammaticScrollGuard = useCallback(() => {
    if (programmaticResetFrameRef.current !== null) {
      cancelAnimationFrame(programmaticResetFrameRef.current);
      programmaticResetFrameRef.current = null;
    }
    programmaticScrollingRef.current = false;
  }, []);

  const cancelScheduledScroll = useCallback(() => {
    if (pendingScrollFrameRef.current !== null) {
      cancelAnimationFrame(pendingScrollFrameRef.current);
      pendingScrollFrameRef.current = null;
    }
    pendingScrollForceRef.current = false;
    resetProgrammaticScrollGuard();
  }, [resetProgrammaticScrollGuard]);

  const cleanupScrollResources = useCallback(() => {
    cancelScheduledScroll();
    if (observerRetryFrameRef.current !== null) {
      cancelAnimationFrame(observerRetryFrameRef.current);
      observerRetryFrameRef.current = null;
    }
    const activeSmoothCleanup = smoothScrollCleanupRef.current;
    if (activeSmoothCleanup) {
      activeSmoothCleanup();
      smoothScrollCleanupRef.current = null;
    }
    if (userScrollIntentTimerRef.current !== undefined) {
      clearTimeout(userScrollIntentTimerRef.current);
      userScrollIntentTimerRef.current = undefined;
    }
    userScrollIntentUntilRef.current = 0;
    nestedHandoffUntilRef.current = 0;
  }, [cancelScheduledScroll]);

  const disposeScrollResources = useCallback(() => {
    cleanupScrollResources();
    const listenerCleanup = scrollListenerCleanupRef.current;
    if (listenerCleanup) {
      listenerCleanup();
      scrollListenerCleanupRef.current = null;
    }
  }, [cleanupScrollResources]);

  const markUserScrollIntent = useCallback(() => {
    const activeSmoothCleanup = smoothScrollCleanupRef.current;
    if (activeSmoothCleanup) {
      activeSmoothCleanup();
      smoothScrollCleanupRef.current = null;
    }
    cancelScheduledScroll();
    const generation = scrollGenerationRef.current;
    const expiresAt = performance.now() + TIMING.USER_SCROLL_INTENT_WINDOW;
    userScrollIntentUntilRef.current = expiresAt;
    if (userScrollIntentTimerRef.current !== undefined) {
      clearTimeout(userScrollIntentTimerRef.current);
    }
    userScrollIntentTimerRef.current = setTimeout(() => {
      if (scrollGenerationRef.current !== generation) return;
      if (userScrollIntentUntilRef.current !== expiresAt) return;
      if (performance.now() >= expiresAt) {
        userScrollIntentUntilRef.current = 0;
        userScrollIntentTimerRef.current = undefined;
      }
    }, TIMING.USER_SCROLL_INTENT_WINDOW);
  }, [cancelScheduledScroll]);

  const invalidateScrollGeneration = useCallback(() => {
    cleanupScrollResources();
    programmaticScrollingRef.current = false;
    isAtBottomRef.current = true;
    scrollGenerationRef.current += 1;
  }, [cleanupScrollResources]);

  useEffect(() => {
    if (scrollSessionIdRef.current === session.sessionId) return;
    invalidateScrollGeneration();
    scrollSessionIdRef.current = session.sessionId;
  }, [session.sessionId, invalidateScrollGeneration]);

  const handleUserScroll = useCallback(() => {
    const chat = chatAreaRef.current;
    if (!chat) return;
    const now = performance.now();
    const hasUserIntent = userScrollIntentUntilRef.current > now;
    const hasNestedHandoff = nestedHandoffUntilRef.current > now;
    if (programmaticScrollingRef.current && !hasUserIntent && !hasNestedHandoff) return;
    if (!hasUserIntent && !hasNestedHandoff) return;
    if (!hasNestedHandoff) nestedHandoffUntilRef.current = 0;
    const isAtBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight <= DIMENSIONS.SCROLL_BOTTOM_THRESHOLD;
    isAtBottomRef.current = isAtBottom;
  }, []);

  const attachScrollListener = useCallback((): (() => void) | null => {
    const chat = chatAreaRef.current;
    if (!chat) return null;

    const onScroll = () => handleUserScroll();
    const onWheel = (event: WheelEvent) => {
      if (event.deltaY === 0) return;
      if (isInsideNestedScrollContainer(event.target)) {
        if (isNestedHandoffTargetAtBoundary(event.target, event.deltaY)) {
          nestedHandoffUntilRef.current = performance.now() + TIMING.USER_SCROLL_INTENT_WINDOW;
          markUserScrollIntent();
        }
        return;
      }
      markUserScrollIntent();
    };
    const onTouchStart = (event: TouchEvent) => {
      if (!isInsideNestedScrollContainer(event.target)) markUserScrollIntent();
    };
    const onTouchMove = (event: TouchEvent) => {
      if (!isInsideNestedScrollContainer(event.target)) markUserScrollIntent();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (KEYBOARD_SCROLL_KEYS.has(event.key) && isKeyboardScrollTarget(event.target, chat)) {
        markUserScrollIntent();
      }
    };

    chat.addEventListener("scroll", onScroll, { passive: true });
    chat.addEventListener("wheel", onWheel, { passive: true });
    chat.addEventListener("touchstart", onTouchStart, { passive: true });
    chat.addEventListener("touchmove", onTouchMove, { passive: true });
    chat.addEventListener("keydown", onKeyDown);

    const cleanup = () => {
      chat.removeEventListener("scroll", onScroll);
      chat.removeEventListener("wheel", onWheel);
      chat.removeEventListener("touchstart", onTouchStart);
      chat.removeEventListener("touchmove", onTouchMove);
      chat.removeEventListener("keydown", onKeyDown);
      if (scrollListenerCleanupRef.current === cleanup) {
        scrollListenerCleanupRef.current = null;
      }
    };
    const previousCleanup = scrollListenerCleanupRef.current;
    if (previousCleanup) previousCleanup();
    scrollListenerCleanupRef.current = cleanup;
    return cleanup;
  }, [handleUserScroll, markUserScrollIntent]);

  const scheduleScrollToBottom = useCallback((force = false) => {
    const chat = chatAreaRef.current;
    if (!chat) return;
    if (!force && !isAtBottomRef.current) return;
    if (!force && userScrollIntentUntilRef.current > performance.now()) return;

    const activeSmoothCleanup = smoothScrollCleanupRef.current;
    if (activeSmoothCleanup) {
      activeSmoothCleanup();
      smoothScrollCleanupRef.current = null;
    }
    if (force) pendingScrollForceRef.current = true;
    if (pendingScrollFrameRef.current !== null) return;

    const generation = scrollGenerationRef.current;
    let frameId = 0;
    frameId = requestAnimationFrame(() => {
      if (pendingScrollFrameRef.current !== frameId) return;
      pendingScrollFrameRef.current = null;
      if (scrollGenerationRef.current !== generation) return;

      const shouldForce = pendingScrollForceRef.current;
      pendingScrollForceRef.current = false;
      const currentChat = chatAreaRef.current;
      if (!currentChat || (!shouldForce && !isAtBottomRef.current)) return;

      const maxScrollTop = Math.max(0, currentChat.scrollHeight - currentChat.clientHeight);
      programmaticScrollingRef.current = true;
      currentChat.scrollTo({ top: maxScrollTop, behavior: "auto" });

      if (programmaticResetFrameRef.current !== null) {
        cancelAnimationFrame(programmaticResetFrameRef.current);
      }
      const resetGeneration = generation;
      let resetFrameId = 0;
      resetFrameId = requestAnimationFrame(() => {
        if (programmaticResetFrameRef.current !== resetFrameId) return;
        programmaticResetFrameRef.current = null;
        if (scrollGenerationRef.current !== resetGeneration) return;
        programmaticScrollingRef.current = false;
      });
      programmaticResetFrameRef.current = resetFrameId;
    });
    pendingScrollFrameRef.current = frameId;
  }, []);

  const scrollToBottomIfAtBottom = useCallback((force = false) => {
    scheduleScrollToBottom(force);
  }, [scheduleScrollToBottom]);

  const scrollToBottomSmooth = useCallback(() => {
    const chat = chatAreaRef.current;
    if (!chat) return;

    cancelScheduledScroll();
    const previousCleanup = smoothScrollCleanupRef.current;
    if (previousCleanup) previousCleanup();

    const generation = scrollGenerationRef.current;
    isAtBottomRef.current = true;
    programmaticScrollingRef.current = true;

    let done = false;
    let fallbackTimer: ReturnType<typeof setTimeout> | undefined;
    const onScrollEnd = () => finish();
    const cleanup = () => {
      if (done) return;
      done = true;
      if (fallbackTimer !== undefined) clearTimeout(fallbackTimer);
      chat.removeEventListener("scrollend", onScrollEnd);
      if (smoothScrollCleanupRef.current === cleanup) {
        smoothScrollCleanupRef.current = null;
      }
      if (scrollGenerationRef.current === generation) {
        resetProgrammaticScrollGuard();
      }
    };
    const finish = () => {
      if (scrollGenerationRef.current !== generation) {
        cleanup();
        return;
      }
      cleanup();
    };

    smoothScrollCleanupRef.current = cleanup;
    fallbackTimer = setTimeout(finish, TIMING.SMOOTH_SCROLL_FALLBACK);
    chat.addEventListener("scrollend", onScrollEnd);
    chat.scrollTo({ top: chat.scrollHeight, behavior: "smooth" });
  }, [cancelScheduledScroll, resetProgrammaticScrollGuard]);

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

    const blocks = u.extractContentBlocks(u.inputRef.current, u.pendingImages, u.pendingAudios, u.pendingVideos);
    const hasContent = blocks.length > 0;
    if (!hasContent) return;

    const content: MessageContent = blocks.length === 1 && blocks[0].type === "text" ? blocks[0].text : blocks;
    const clientMessageId = generateUUID();

    s.addPendingMessage(clientMessageId, content);

    c.send({
      type: WS_OUT.USER_MESSAGE,
      content,
      target_sessions: targetSessions,
      client_message_id: clientMessageId,
      client_info: collectClientInfo(),
      llm_profile_name: llmProfilesRef.current.toProfileName(),
      ...(visible_characters ? { visible_characters } : {}),
      ...(response_characters ? { response_characters } : {}),
    });
    s.setInput("");
    u.setPendingImages([]);
    u.setPendingAudios([]);
    u.setPendingVideos([]);
    s.setWaiting(true);
    s.ignoreStaleRef.current = false;
    s.streamDoneRef.current = false;
    isAtBottomRef.current = true;
    scrollToBottomIfAtBottom(true);
  }, [scrollToBottomIfAtBottom]);

  // ── actions ──
  const newChat = useCallback(() => {
    if (!sessionRef.current) return;
    invalidateScrollGeneration();
    window.history.replaceState({}, "", "/");
    conn.disconnect();
    sessionRef.current.newChat();
    conn.connect();
  }, [conn.connect, conn.disconnect, invalidateScrollGeneration]);

  const switchSession = useCallback((sid: string) => {
    if (!sessionRef.current) return;
    invalidateScrollGeneration();
    window.history.replaceState({}, "", `/?session=${sid}`);
    conn.disconnect();
    sessionRef.current.switchSession(sid);
    conn.connect(sid);
  }, [conn.connect, conn.disconnect, invalidateScrollGeneration]);

  const enterColloquy = useCallback(() => {
    if (!sessionRef.current) return;
    invalidateScrollGeneration();
    connRef.current.disconnect();
    sessionRef.current.switchSession(COLLOQUY_SID);
    connRef.current.connect(COLLOQUY_SID);
  }, [invalidateScrollGeneration]);

  const mergeSessions = useCallback(async (sources: string[]) => {
    if (!sessionRef.current) return;
    const newSid = await session.mergeSessions(sources);
    if (newSid) {
      invalidateScrollGeneration();
      window.history.replaceState({}, "", `/?session=${newSid}`);
      conn.disconnect();
      sessionRef.current.switchSession(newSid);
      conn.connect(newSid);
    }
  }, [conn.connect, conn.disconnect, invalidateScrollGeneration, session.mergeSessions]);

  const branchSession = useCallback(async (sid: string) => {
    if (!sessionRef.current) return;
    const newSid = await sessionRef.current.mergeSessions([sid]);
    if (newSid) {
      invalidateScrollGeneration();
      window.history.replaceState({}, "", `/?session=${newSid}`);
      conn.disconnect();
      sessionRef.current.switchSession(newSid);
      conn.connect(newSid);
    }
  }, [conn.connect, conn.disconnect, invalidateScrollGeneration]);

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
          switchSession(COLLOQUY_SID);
        }
      })
      .catch(() => {});
  }, [switchSession]);

  const setApprovalMode = useCallback((mode: string) => {
    const s = sessionRef.current;
    const c = connRef.current;
    if (!s) return;
    // 不乐观更新；等待服务端 HANDSFREE_MODE 回执
    if (c.wsRef.current?.readyState === WebSocket.OPEN) {
      c.send({
        type: WS_OUT.HANDSFREE_MODE,
        content: mode,
      });
    }
  }, []);

  const toggleHandsfree = useCallback((enabled: boolean) => {
    setApprovalMode(enabled ? "handsfree" : "manual");
  }, [setApprovalMode]);

  const interrupt = useCallback(() => {
    const s = sessionRef.current;
    if (!s) return;
    s.ignoreStaleRef.current = true;
    s.setWaiting(false);
    s.setPendingMessages({});
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
    // 中断时清空挂起的 ask/confirm 队列并逐项自动应答，解除后端悬挂 Future
    s.clearPendingInteractions();
    fetch(`/api/interrupt/${s.sessionId || "unknown"}`, { method: "POST" }).catch(() => {});
  }, []);

  const disgust = useCallback(() => {
    const s = sessionRef.current;
    if (!s) return;
    // 厌恶：不停止流式消息、不设置 ignoreStaleRef
    // 仅添加系统消息并通知后端
    s.setMessages((prev) => [
      ...prev,
      { role: "system" as const, content: "👎 用户表达了强烈不满", id: generateUUID() },
    ]);
    fetch(`/api/disgust/${s.sessionId || "unknown"}`, { method: "POST" }).catch(() => {});
  }, []);

  const resume = useCallback(() => {
    const s = sessionRef.current;
    if (!s) return;
    s.resumeSession();
  }, []);

  const respondConfirm = useCallback((request: ConfirmRequest | null, action: string, denyReasonText?: string, deniedBy?: string) => {
    const s = sessionRef.current;
    if (!s) return;
    s.respondConfirm(request, action, denyReasonText, deniedBy);
  }, []);

  const respondAsk = useCallback((request: AskRequest | null, option?: string, customText?: string) => {
    const s = sessionRef.current;
    if (!s) return;
    s.respondAsk(request, option, customText);
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
      // 动态端点等 tool-resources 随轮询刷新：agent 注册/注销端点后资源面板自动更新
      fetchToolResourcesRef.current(sid);
    };
    fetchTasks();
    const iv = setInterval(fetchTasks, TIMING.TASK_POLL_INTERVAL);
    return () => clearInterval(iv);
  }, [session.sessionId]);

  // ── auto scroll ──
  useEffect(() => {
    if (session.messages.length === 0) return;
    scrollToBottomIfAtBottom();
  }, [session.messages.length, scrollToBottomIfAtBottom]);

  useEffect(() => {
    if (session.streamingMessage || session.waiting) {
      scrollToBottomIfAtBottom();
    }
  }, [
    session.streamingMessage?.content,
    session.streamingMessage?.reasoningContent,
    session.streamingMessage?.toolName,
    session.streamingMessage?.toolArgs,
    session.streamingMessage?.activeToolCallKey,
    session.waiting,
    scrollToBottomIfAtBottom,
  ]);

  // ── ResizeObserver 追底: 异步渲染导致内容高度增长时自动追底 ──
  useEffect(() => {
    let active = true;
    let observer: ResizeObserver | null = null;
    let retryUsed = false;
    const generation = scrollGenerationRef.current;

    const observeContent = () => {
      if (!active || conn.sessionLocked || scrollGenerationRef.current !== generation) return;
      const content = contentRef.current;
      if (!content) {
        if (retryUsed) return;
        retryUsed = true;
        let retryFrameId = 0;
        retryFrameId = requestAnimationFrame(() => {
          if (observerRetryFrameRef.current !== retryFrameId) return;
          observerRetryFrameRef.current = null;
          observeContent();
        });
        observerRetryFrameRef.current = retryFrameId;
        return;
      }
      if (typeof ResizeObserver === "undefined") {
        scheduleScrollToBottom();
        return;
      }

      observer = new ResizeObserver(() => {
        if (active && !conn.sessionLocked) {
          scheduleScrollToBottom();
        }
      });
      observer.observe(content);
      scheduleScrollToBottom();
    };

    if (!conn.sessionLocked) observeContent();

    return () => {
      active = false;
      if (observer) observer.disconnect();
      if (observerRetryFrameRef.current !== null) {
        cancelAnimationFrame(observerRetryFrameRef.current);
        observerRetryFrameRef.current = null;
      }
      cleanupScrollResources();
    };
  }, [conn.sessionLocked, scheduleScrollToBottom, cleanupScrollResources]);

  useEffect(() => {
    return () => {
      invalidateScrollGeneration();
      disposeScrollResources();
    };
  }, [invalidateScrollGeneration, disposeScrollResources]);

  // ── sync URL with session id ──
  useEffect(() => {
    if (!session.sessionId) return;
    const urlSid = new URLSearchParams(window.location.search).get("session");
    if (urlSid !== session.sessionId) {
      window.history.replaceState({}, "", `/?session=${session.sessionId}`);
    }
  }, [session.sessionId]);

  // ── computed ──
  const isReady = conn.status === "已连接";

  return {
    // state
    messages: session.messages,
    setMessages: session.setMessages,
    input: session.input,
    setInput: session.setInput,
    status: conn.status,
    waiting: session.waiting,
    setWaiting: session.setWaiting,
    pendingConfirms: session.pendingConfirms,
    pendingAsks: session.pendingAsks,
    clearPendingInteractions: session.clearPendingInteractions,
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
    approvalMode: session.approvalMode,
    yoloMode: session.yoloMode,
    setYoloMode: session.setYoloMode,
    taskProgress: session.taskProgress,
    setTaskProgress: session.setTaskProgress,
    clipboardDisplays: session.clipboardDisplays,
    setClipboardDisplays: session.setClipboardDisplays,
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
    bgTasks: session.bgTasks,
    setBgTasks: session.setBgTasks,
    cronTasks: session.cronTasks,
    setCronTasks: session.setCronTasks,
    subagentIdleCountdown: subagent.subagentIdleCountdown,
    terminatingSessions: session.terminatingSessions,
    generatingTitleSessions: session.generatingTitleSessions,
    generatingTagSessions: session.generatingTagSessions,
    pendingImages: upload.pendingImages,
    pendingAudios: upload.pendingAudios,
    pendingVideos: upload.pendingVideos,
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
    addPendingAudio: upload.addPendingAudio,
    removePendingAudio: upload.removePendingAudio,
    handlePasteAudios: upload.handlePasteAudios,
    addPendingVideo: upload.addPendingVideo,
    removePendingVideo: upload.removePendingVideo,
    handlePasteVideos: upload.handlePasteVideos,
    inputRef: upload.inputRef,
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
    toggleHandsfree,
    setApprovalMode,
    interrupt,
    disgust,
    resume,
    toggleMessageCollapse: session.toggleMessageCollapse,
    editMessage: session.editMessage,
    deleteMessages: session.deleteMessages,
    deleteSingleMessage: session.deleteSingleMessage,
    regenerateResponse: (messageIndex: number) => session.regenerateResponse(messageIndex, llmProfilesRef.current.toProfileName()),
    updateMessageVisibility: session.updateMessageVisibility,
    addMessage: session.addMessage,
    pendingMessages: session.pendingMessages,
    fetchSessions: session.fetchSessions,
    fetchAllTags: session.fetchAllTags,
    connect: conn.connect,
    updateSessionTags: session.updateSessionTags,
    attachScrollListener,
    scrollToBottomIfAtBottom,
    scrollToBottomSmooth,
    // refs
    wsRef: conn.wsRef,
    bottomRef,
    chatAreaRef,
    contentRef,
    isAtBottomRef,
    fileInputRef: upload.fileInputRef,
    // computed
    isReady,
    sessionLocked: conn.sessionLocked,
    retryConnect: conn.retryConnect,
    sidebarItems: session.sidebarItems,
    expandedClusters: session.expandedClusters,
    toggleCluster: session.toggleCluster,
    sessionResources: session.sessionResources,
  };
}