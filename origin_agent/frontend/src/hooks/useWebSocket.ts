import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import {
  ChatMessage,
  ConfirmRequest,
  AskRequest,
  DownloadInfo,
  PlaylistEntry,
  TaskProgress,
  ClipboardDisplay,
  SubagentSession,
  CronTask,
  SessionInfo,
  WSMessage,
  ContentBlock,
  MessageContent,
} from "../types";
import { extractMessageResources, parseToolResult, generateUUID } from "../utils";

const MAX_PASTE_IMAGE_SIZE = 20 * 1024 * 1024;

export interface PendingImage {
  id: string;
  file: File;
  dataUrl: string;
}

export function useWebSocket() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState("connecting...");
  const [waiting, setWaiting] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<ConfirmRequest | null>(null);
  const [denyReason, setDenyReason] = useState("用户不同意工具调用");
  const [pendingAsk, setPendingAsk] = useState<AskRequest | null>(null);
  const [askCustomText, setAskCustomText] = useState("");
  const [askSelectedOption, setAskSelectedOption] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [tokenUsage, setTokenUsage] = useState(0);
  const [contextTokens, setContextTokens] = useState(0);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [uploading, setUploading] = useState(false);
  const [handsfreeMode, setHandsfreeMode] = useState(false);
  const [taskProgress, setTaskProgress] = useState<Record<string, TaskProgress>>({});
  const [clipboardDisplays, setClipboardDisplays] = useState<Record<string, ClipboardDisplay>>({});
  const [subagentSessionsMap, setSubagentSessionsMap] = useState<Record<string, Record<string, SubagentSession>>>({});
  const [agents, setAgents] = useState<string[]>([]);

  // 当前会话派生的子会话列表
  const subagentSessions = useMemo(() => subagentSessionsMap[sessionId] || {}, [subagentSessionsMap, sessionId]);
  const [llmMaxContextTokens, setLlmMaxContextTokens] = useState(0);
  const [llmModelName, setLlmModelName] = useState("");
  const [approvalModelName, setApprovalModelName] = useState("");
  const [approvalModelAvailable, setApprovalModelAvailable] = useState(false);
  const [mergeMode, setMergeMode] = useState(false);
  const [selectedForMerge, setSelectedForMerge] = useState<Set<string>>(new Set());
  const [bgTasks, setBgTasks] = useState<Array<{
    task_id: string;
    pid: number;
    command: string[];
    start_time: number;
    log_path: string;
    status: string;
  }>>([]);
  const [cronTasks, setCronTasks] = useState<CronTask[]>([]);
  const [subagentIdleCountdown, setSubagentIdleCountdown] = useState<number | null>(null);
  const [terminatingSessions, setTerminatingSessions] = useState<Set<string>>(new Set());
  const [generatingTitleSessions, setGeneratingTitleSessions] = useState<Set<string>>(new Set());
  const [generatingTagSessions, setGeneratingTagSessions] = useState<Set<string>>(new Set());
  const [pendingImages, setPendingImages] = useState<PendingImage[]>([]);
  const [streamingMessage, setStreamingMessage] = useState<ChatMessage | null>(null);
  const [allTags, setAllTags] = useState<string[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const chatAreaRef = useRef<HTMLDivElement>(null);
  const isAtBottomRef = useRef(true);
  const programmaticScrollingRef = useRef(false);
  const lastScrollTopRef = useRef(0);
  const instantScrollRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLDivElement>(null);
  const reconnectRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const keepaliveRef = useRef<ReturnType<typeof setInterval>>();
  const manualRef = useRef(false);
  const ignoreStaleRef = useRef(false);
  const lastMessageCountRef = useRef(0);
  const streamDoneRef = useRef(false);
  const reasoningStartRef = useRef<number | null>(null);
  const lastRecvAtRef = useRef<number>(Date.now());
  const lastPongAtRef = useRef<number>(Date.now());
  const [recvTick, setRecvTick] = useState(0);

  const nextMessageIndex = useCallback((items: ChatMessage[]) => {
    const indexes = items
      .map((m) => m.messageIndex)
      .filter((index): index is number => typeof index === "number");
    return indexes.length ? Math.max(...indexes) + 1 : 0;
  }, []);

  const ensureStreamingMessage = useCallback((streamId: string, characterName?: string) => {
    setStreamingMessage((prev) => {
      if (prev && prev.id === streamId) return prev;
      reasoningStartRef.current = null;
      return {
        role: "assistant",
        content: "",
        id: streamId,
        characterName,
        reasoningContent: undefined,
        messageIndex: nextMessageIndex(messagesRef.current),
      };
    });
  }, []);

  const flushStreamingMessage = useCallback(() => {
    setStreamingMessage((prev) => {
      if (!prev) return null;
      let finalPrev = prev;
      if (reasoningStartRef.current && prev.reasoningContent) {
        const duration = Math.round((Date.now() - reasoningStartRef.current) / 1000);
        finalPrev = { ...prev, reasoningDuration: duration };
        reasoningStartRef.current = null;
      }
      setMessages((m) => {
        const exists = m.some((x) => x.id === finalPrev.id);
        return exists ? m.map((x) => (x.id === finalPrev.id ? finalPrev : x)) : [...m, finalPrev];
      });
      return null;
    });
  }, []);

  const appendStreamingDelta = useCallback((streamId: string, delta: string, reasoningDelta?: string, toolCall?: unknown, characterName?: string) => {
    ensureStreamingMessage(streamId, characterName);
    if (reasoningDelta && reasoningStartRef.current == null) {
      reasoningStartRef.current = Date.now();
    }
    setStreamingMessage((prev) => {
      if (!prev) return null;
      const content = typeof prev.content === "string" ? prev.content : "";
      const reasoning = prev.reasoningContent || "";
      let nextContent: string = content;
      let nextReasoning: string | undefined = reasoning || undefined;
      let nextToolName: string | undefined = prev.toolName;
      let nextToolArgs: Record<string, unknown> | undefined = prev.toolArgs;
      if (delta) nextContent = content + delta;
      if (reasoningDelta) nextReasoning = reasoning + reasoningDelta;
      if (toolCall && typeof toolCall === "object") {
        const tc = toolCall as Record<string, unknown>;
        if (typeof tc.name === "string") nextToolName = tc.name;
        if (typeof tc.arguments === "object" && tc.arguments !== null) {
          nextToolArgs = tc.arguments as Record<string, unknown>;
        }
      }
      return { ...prev, content: nextContent, reasoningContent: nextReasoning, toolName: nextToolName, toolArgs: nextToolArgs };
    });
  }, [ensureStreamingMessage]);

  const messagesRef = useRef<ChatMessage[]>([]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const streamingMessageRef = useRef<ChatMessage | null>(null);
  useEffect(() => {
    streamingMessageRef.current = streamingMessage;
  }, [streamingMessage]);

  const addMessage = useCallback((
    role: ChatMessage["role"],
    content: MessageContent,
    imageMarkdown?: string,
    downloadInfo?: DownloadInfo,
    audioUrl?: string,
    audioAutoplay?: boolean,
    playlist?: PlaylistEntry[],
    playlistAutoplay?: boolean,
    messageIndex?: number
  ) => {
    const id = generateUUID();
    setMessages((prev) => [...prev, {
      role, content, id, imageMarkdown, downloadInfo, audioUrl, audioAutoplay, playlist, playlistAutoplay, messageIndex
    }]);
  }, []);

  const fetchSessions = useCallback(() => {
    fetch("/api/sessions")
      .then((r) => r.json())
      .then((data) => setSessions(data.sessions || []))
      .catch(() => {});
  }, []);

  const fetchAllTags = useCallback(() => {
    fetch("/api/tags")
      .then((r) => r.json())
      .then((data) => setAllTags(data.tags || []))
      .catch(() => {});
  }, []);

  const fetchToolResources = useCallback((sid: string) => {
    if (!sid) return;
    fetch(`/api/sessions/${sid}/tool-resources`)
      .then((r) => r.json())
      .then((data) => {
        const activeSid = localStorage.getItem("evolve_session_id") || sid;
        if (activeSid !== sid) return;
        setTaskProgress(data.task_progress || {});
        setClipboardDisplays(data.clipboard_display || {});
      })
      .catch(() => {});
    // 拉取子会话快照 — snapshot 来自 _history，是权威数据源
    fetch(`/api/sessions/${sid}/subagents`)
      .then((r) => r.json())
      .then((data) => {
        if (!data.subagents) return;
        setSubagentSessionsMap((prevMap) => {
          const incoming = data.subagents as Record<string, any>;
          const prev = prevMap[sid] || {};
          const merged: Record<string, any> = {};
          for (const [sKey, snap] of Object.entries(incoming)) {
            const existing = prev[sKey];
            if (!existing) {
              merged[sKey] = snap;
              continue;
            }
            const snapIds = new Set(
              (snap.feedback || []).map((f: any) =>
                `${f.role}::${f.content?.slice(0, 80)}::${f.tool_call_id || ""}`
              )
            );
            const wsOnly = (existing.feedback || []).filter((f: any) =>
              !snapIds.has(`${f.role}::${f.content?.slice(0, 80)}::${f.tool_call_id || ""}`)
            );
            merged[sKey] = {
              ...snap,
              feedback: [...(snap.feedback || []), ...wsOnly],
              pending_approvals: existing.pending_approvals?.length
                ? existing.pending_approvals
                : snap.pending_approvals,
            };
          }
          // 清理已不活跃的子会话
          for (const sKey of Object.keys(prev)) {
            if (!(sKey in incoming)) {
              delete merged[sKey];
            }
          }
          return { ...prevMap, [sid]: merged };
        });
      })
      .catch(() => {});
  }, []);

  const connect = useCallback(() => {
    const lastSid = localStorage.getItem("evolve_session_id") || "";
    const qs = lastSid ? `?resume=${lastSid}` : "";
    const ws = new WebSocket(`ws://${location.host}/ws/chat${qs}`);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectRef.current = 0;
      ignoreStaleRef.current = false;
      setStatus("已连接");
      isAtBottomRef.current = true;
      instantScrollRef.current = true;
      addMessage("system", "已连接到 Evolve Agent");
      fetchSessions();
      // 启动 keepalive，防止空闲超时被代理/浏览器断开
      if (keepaliveRef.current) clearInterval(keepaliveRef.current);
      keepaliveRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, 20000);
    };

    ws.onclose = () => {
      if (keepaliveRef.current) clearInterval(keepaliveRef.current);
      setStatus("已断开");
      setWaiting(false);
      if (manualRef.current) return;
      if (reconnectRef.current >= 10) {
        setStatus("连接失败 — 已达到最大重试次数");
        return;
      }
      const delay = Math.min(1000 * Math.pow(2, reconnectRef.current), 30000);
      reconnectRef.current += 1;
      setStatus(`重连中 (${(delay / 1000).toFixed(0)}s)...`);
      timerRef.current = setTimeout(connect, delay);
    };

    ws.onmessage = (e) => {
      const msg: WSMessage = JSON.parse(e.data);
      const now = Date.now();
      lastRecvAtRef.current = now;
      setRecvTick((v) => v + 1);
      const payloadLen = typeof e.data === "string" ? e.data.length : 0;
      console.debug(`[ws recv] type=${msg.type} len=${payloadLen} at=${now}`);
      if (msg.type === "system") {
        const raw = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content ?? "");
        try {
          const data = JSON.parse(raw);
          if (data.build_hash) {
            const lastHash = localStorage.getItem("evolve_build_hash") || "";
            if (lastHash && lastHash !== data.build_hash) {
              localStorage.setItem("evolve_build_hash", data.build_hash);
              window.location.reload();
              return;
            }
            localStorage.setItem("evolve_build_hash", data.build_hash);
            return;
          }
          if (data.server_info) {
            const info = data.server_info;
            if (info.llm_max_context_tokens) setLlmMaxContextTokens(info.llm_max_context_tokens);
            setLlmModelName(info.llm_model || "");
            setApprovalModelName(info.approval_model_name || "");
            setApprovalModelAvailable(info.approval_model_available || false);
            return;
          }
          if (data.session_history) {
            const history = data.session_history.map((m: any) => {
              const entry: any = {
                role: m.role,
                content: m.content,
                id: generateUUID(),
                messageIndex: typeof m.index === "number" ? m.index : undefined,
              };
              if (m.character_name) {
                entry.characterName = m.character_name;
              }
              if (m.visible_characters) {
                entry.visibleCharacters = m.visible_characters;
              }
              if (m.response_characters && m.response_characters.length > 0) {
                entry.responseCharacters = m.response_characters;
              }
              if (typeof m.requires_response === "boolean") {
                entry.requiresResponse = m.requires_response;
              }
              if (m.reasoning_content) {
                entry.reasoningContent = m.reasoning_content;
              }
              if (m.role === "tool" && typeof m.content === "string") {
                const parsed = parseToolResult(m.content);
                if (parsed.imageMarkdown) entry.imageMarkdown = parsed.imageMarkdown;
                if (parsed.downloadInfo) entry.downloadInfo = parsed.downloadInfo;
                if (parsed.audioUrl) {
                  entry.audioUrl = parsed.audioUrl;
                  entry.audioAutoplay = parsed.audioAutoplay;
                }
                if (parsed.playlist) {
                  entry.playlist = parsed.playlist;
                  entry.playlistAutoplay = parsed.playlistAutoplay;
                }
                if (parsed.content !== undefined) {
                  entry.content = parsed.content;
                }
              }
              return entry;
            });
            if (history.length) {
              isAtBottomRef.current = true;
              instantScrollRef.current = true;
              setMessages(history);
            }
            if (data.agents && Array.isArray(data.agents)) {
              setAgents(data.agents);
            } else if ("agents" in data) {
              setAgents([]);
            }
            if (data.token_usage !== undefined) setTokenUsage(data.token_usage);
            if (data.context_tokens !== undefined) setContextTokens(data.context_tokens);
            if (data.processing) setWaiting(true);
            if (msg.session_id) {
              setSessionId(msg.session_id);
              localStorage.setItem("evolve_session_id", msg.session_id);
              fetchToolResources(msg.session_id);
            }
            return;
          }
          if (data.token_usage !== undefined) setTokenUsage(data.token_usage);
          if (data.context_tokens !== undefined) setContextTokens(data.context_tokens);
          if (data.token_usage !== undefined || data.context_tokens !== undefined) return;
          if (data.regenerate_trim) {
            const keepCount = data.keep_count as number;
            setMessages((prev) => prev.filter((m) =>
              typeof m.messageIndex === "number" && m.messageIndex < keepCount
            ));
            return;
          }
          if (data.action === "session_rotated") {
            setSessionId(data.new_sid);
            localStorage.setItem("evolve_session_id", data.new_sid);
            setMessages([]);
            setTokenUsage(0);
            setClipboardDisplays({});
            setSubagentSessionsMap((prev) => ({ ...prev, [sessionId]: {} }));
            setTaskProgress({});
            fetchToolResources(data.new_sid);
            fetchSessions();
            return;
          }
          if (data.uploaded) {
            addMessage("system", `✅ 上传成功：${data.filename || "文件"} → ${data.path}`);
            return;
          }
          if (data.agents && Array.isArray(data.agents)) {
            setAgents(data.agents);
            return;
          }
          if ("agents" in data) {
            setAgents([]);
            return;
          }
          if (data.stream_meta) {
            const meta = data.stream_meta as { stream_id: string; visible_characters?: string[]; response_characters?: string[] };
            setMessages((prev) => prev.map((m) =>
              m.id === meta.stream_id ? {
                ...m,
                visibleCharacters: meta.visible_characters,
                responseCharacters: meta.response_characters,
              } : m
            ));
            return;
          }
          if (data.assistant_text) {
            const p = JSON.parse(data.assistant_text);
            const id = generateUUID();
            setMessages((prev) => [...prev, {
              role: "assistant",
              content: p.content || "",
              id,
              reasoningContent: p.reasoning || undefined,
              messageIndex: nextMessageIndex(prev),
            }]);
            return;
          }
        } catch {}
        addMessage("system", raw);
        if (msg.session_id) {
          setSessionId(msg.session_id);
          localStorage.setItem("evolve_session_id", msg.session_id);
          fetchToolResources(msg.session_id);
        }
      }
      else if (msg.type === "user_message") {
        setMessages((prev) => [...prev, {
          role: "user",
          content: msg.content ?? "",
          id: generateUUID(),
          characterName: msg.character_name,
          messageIndex: typeof msg.index === "number" ? msg.index : undefined,
          visibleCharacters: msg.visible_characters ?? undefined,
          responseCharacters: msg.response_characters ?? undefined,
        }]);
      }
      else if (msg.type === "assistant_message") {
        setWaiting(false);
        ignoreStaleRef.current = false;
        // stream_done 之后后端会发 assistant_message 作为兜底，此时流式消息已固化，直接跳过
        if (streamDoneRef.current) {
          streamDoneRef.current = false;
          fetchSessions();
          return;
        }
        // 如果存在同 stream_id 的流式消息，则刷新它；否则追加一条新消息
        if (msg.session_id && streamingMessageRef.current && streamingMessageRef.current.id === msg.stream_id) {
          flushStreamingMessage();
        } else {
          setMessages((prev) => [...prev, {
            role: "assistant",
            content: msg.content ?? "",
            id: generateUUID(),
            characterName: msg.character_name,
            messageIndex: nextMessageIndex(prev),
            visibleCharacters: msg.visible_characters ?? undefined,
            responseCharacters: msg.response_characters ?? undefined,
          }]);
        }
        fetchSessions();
      }
      else if (msg.type === "stream_delta") {
        if (ignoreStaleRef.current) return;
        const delta = msg.delta || "";
        const reasoningDelta = msg.reasoning_delta;
        let toolCall: unknown = undefined;
        if (typeof msg.content === "string") {
          try {
            const parsed = JSON.parse(msg.content);
            toolCall = parsed?.tool_call;
          } catch {}
        }
        appendStreamingDelta(msg.stream_id || "", delta, reasoningDelta, toolCall, msg.character_name);
      }
      else if (msg.type === "stream_done") {
        setWaiting(false);
        ignoreStaleRef.current = false;
        flushStreamingMessage();
        // 标记流式已完成，紧随的 assistant_message 兜底消息应跳过
        streamDoneRef.current = true;
      }
      else if (msg.type === "tool_call") {
        if (ignoreStaleRef.current) return;
        // 工具调用前确保已产生的流式文本固化
        flushStreamingMessage();
        const argsStr = msg.args
          ? "(" + Object.entries(msg.args)
              .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
              .join(", ") + ")"
          : "";
        addMessage("tool", `⚡ ${msg.tool} ${argsStr}`);
      }
      else if (msg.type === "tool_result") {
        if (ignoreStaleRef.current) return;
        const raw = msg.result ?? "";
        const parsed = parseToolResult(raw, msg.tool);
        setMessages((prev) => [...prev, {
          role: "tool",
          content: parsed.content ?? `✅ ${msg.tool} → ${raw.slice(0, 2000)}`,
          id: generateUUID(),
          imageMarkdown: parsed.imageMarkdown,
          downloadInfo: parsed.downloadInfo,
          audioUrl: parsed.audioUrl,
          audioAutoplay: parsed.audioAutoplay ?? false,
          playlist: parsed.playlist,
          playlistAutoplay: parsed.playlistAutoplay ?? false,
          messageIndex: nextMessageIndex(prev),
        }]);
      }
      else if (msg.type === "task_progress") {
        const raw = msg.result ?? "";
        try {
          const data = JSON.parse(raw);
          if (data.cleared) {
            setTaskProgress((prev) => {
              const next = { ...prev };
              if (Array.isArray(data.cleared) && data.cleared.length) {
                for (const tid of data.cleared) delete next[tid];
              } else {
                return {};
              }
              return next;
            });
          } else if (data.task_id) {
            setTaskProgress((prev) => ({
              ...prev,
              [data.task_id]: {
                task_id: data.task_id,
                label: data.label || data.task_id,
                current: data.current ?? 0,
                total: data.total ?? 100,
                percent: data.percent ?? 0,
                status: data.status || "running",
              },
            }));
          }
        } catch {}
      }
      else if (msg.type === "clipboard_display") {
        const raw = msg.result ?? "";
        try {
          const data = JSON.parse(raw);
          if (data.cleared) {
            setClipboardDisplays((prev) => {
              const next = { ...prev };
              if (Array.isArray(data.cleared) && data.cleared.length) {
                for (const did of data.cleared) delete next[did];
              } else {
                return {};
              }
              return next;
            });
          } else if (data.display_id) {
            setClipboardDisplays((prev) => ({
              ...prev,
              [data.display_id]: {
                display_id: data.display_id,
                label: data.label || data.display_id,
                content: data.content ?? "",
              },
            }));
          }
        } catch {}
      }
      else if (msg.type === "subagent_update") {
        const raw = msg.result ?? "";
        try {
          const data = JSON.parse(raw);
          const subId = data.session_id || "";
          const parentId = msg.session_id || sessionId;
          // 倒计时值所有子会话共享，提到顶层进度条
          const rawFeedback = Array.isArray(data.feedback) ? data.feedback : [];
          for (const item of rawFeedback) {
            if (item.role === "countdown") {
              const v = parseInt(item.content, 10);
              if (!isNaN(v)) {
                setSubagentIdleCountdown(v);
              }
              break;
            }
          }
          setSubagentSessionsMap((prevMap) => {
            const prev = prevMap[parentId] || {};
            if (data._removed) {
              const next = { ...prev };
              delete next[subId];
              const nextMap = { ...prevMap, [parentId]: next };
              if (Object.keys(next).length === 0 && parentId === sessionId) {
                setSubagentIdleCountdown(null);
              }
              return nextMap;
            }
            const existing = prev[subId];
            const prevFeedback = existing?.feedback || [];
            const prevApprovals = existing?.pending_approvals || [];
            const realFeedback: Array<{role: string; content: string; tool_name?: string; tool_call_id?: string; tool_args?: Record<string, unknown>; reasoning?: string}> = [];
            for (const item of rawFeedback) {
              if (item.role === "countdown") continue;
              if (item.role === "status" && !item.content) continue;
              realFeedback.push(item);
            }
            const newApprovals = Array.isArray(data.pending_approvals) ? data.pending_approvals : [];
            return {
              ...prevMap,
              [parentId]: {
                ...prev,
                [subId]: {
                  session_id: subId,
                  name: data.name || existing?.name || "",
                  status: data.status || existing?.status || "running",
                  feedback: [...prevFeedback, ...realFeedback],
                  pending_approvals: data.pending_approvals !== undefined ? newApprovals : prevApprovals,
                },
              },
            };
          });
        } catch {}
      }
      else if (msg.type === "error") {
        addMessage("error", msg.message ?? "");
      }
      else if (msg.type === "pong") {
        lastPongAtRef.current = Date.now();
      }
      else if (msg.type === "confirm_request") {
        if (msg.request_id) {
          setDenyReason("用户不同意工具调用");
          setPendingConfirm({
            request_id: msg.request_id,
            content: typeof msg.content === "string" ? msg.content : "运行命令?",
            command: (msg.args as Record<string, unknown>)?.command as string[] | undefined,
            reason: (msg.args as Record<string, unknown>)?.reason as string | undefined,
            tool: msg.tool ?? undefined,
          });
        }
      }
      else if (msg.type === "ask_request") {
        if (msg.request_id && msg.question) {
          setAskCustomText("");
          setAskSelectedOption(null);
          setPendingAsk({
            request_id: msg.request_id,
            question: msg.question ?? "",
            options: msg.options,
            allow_custom: msg.allow_custom ?? true,
          });
        }
      }
    };
  }, [addMessage, fetchSessions, fetchToolResources, nextMessageIndex]);

  const toggleMessageCollapse = useCallback((id: string) => {
    setMessages((prev) => prev.map((m) => (
      m.id === id ? { ...m, collapsed: m.collapsed === undefined ? false : !m.collapsed } : m
    )));
  }, []);

  const editMessage = useCallback(async (id: string, content: string) => {
    const target = messages.find((m) => m.id === id);
    if (!target || typeof target.messageIndex !== "number") {
      addMessage("error", "这条消息还没有可持久化的历史索引，无法编辑。");
      return;
    }
    const resp = await fetch(`/api/sessions/${sessionId}/messages/${target.messageIndex}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.updated) {
      addMessage("error", `消息编辑失败：${data.error || "unknown error"}`);
      return;
    }
    setMessages((prev) => prev.map((m) => (
      m.id === id ? { ...m, content: data.content ?? content, edited: true } : m
    )));
  }, [addMessage, messages, sessionId]);

  const deleteMessages = useCallback(async (count: number = 1) => {
    const resp = await fetch(`/api/sessions/${sessionId}/messages?count=${count}`, {
      method: "DELETE",
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.deleted) {
      addMessage("error", `删除失败：${data.error || "unknown error"}`);
      return;
    }
    const remaining = data.remaining_count as number;
    setMessages((prev) => prev.filter((m) =>
      typeof m.messageIndex === "number" && m.messageIndex < remaining
    ));
  }, [sessionId, addMessage]);

  const regenerateResponse = useCallback(async () => {
    setWaiting(true);
    const resp = await fetch(`/api/sessions/${sessionId}/regenerate`, {
      method: "POST",
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.regenerate) {
      setWaiting(false);
      addMessage("error", `重新生成失败：${data.error || "unknown error"}`);
    }
  }, [sessionId, addMessage]);

  const updateMessageVisibility = useCallback(async (messageIndex: number, visibleCharacters: string[]) => {
    try {
      const resp = await fetch(`/api/sessions/${sessionId}/messages/${messageIndex}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visible_characters: visibleCharacters }),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok && data.updated) {
        setMessages((prev) => prev.map((m) =>
          m.messageIndex === messageIndex ? { ...m, visibleCharacters: data.visible_characters ?? visibleCharacters } : m
        ));
      }
    } catch {}
  }, [sessionId]);

  const respondConfirm = useCallback((action: string, denyReasonText?: string, deniedBy?: string) => {
    if (!pendingConfirm) return;
    const payload: Record<string, string> = { action };
    if (action === "deny" && denyReasonText) {
      payload.deny_reason = denyReasonText;
      payload.denied_by = deniedBy || "user";
    }
    fetch(`/api/confirm/${pendingConfirm.request_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch((err) => console.error("[confirm] fetch failed", err));
    setPendingConfirm(null);
  }, [pendingConfirm]);

  const respondAsk = useCallback((option?: string, customText?: string) => {
    if (!pendingAsk) return;
    const payload: Record<string, string | null> = {
      option: option ?? null,
      custom_text: customText ?? null,
    };
    fetch(`/api/ask/${pendingAsk.request_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch((err) => console.error("[ask] fetch failed", err));
    setPendingAsk(null);
    setAskCustomText("");
    setAskSelectedOption(null);
  }, [pendingAsk]);

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
    const bottom = bottomRef.current;
    if (!bottom) return;
    if (force || isAtBottomRef.current) {
      const behavior = instantScrollRef.current ? "auto" : "smooth";
      instantScrollRef.current = false;
      programmaticScrollingRef.current = true;
      bottom.scrollIntoView({ behavior });
      if (chat) {
        lastScrollTopRef.current = chat.scrollTop;
      }
      programmaticScrollingRef.current = false;
    } else {
      instantScrollRef.current = false;
    }
  }, []);

  const send = useCallback((
    targetSessions: string[],
    visible_characters?: string[],
    response_characters?: string[],
  ) => {
    const isArchived = sessions.find((s) => s.id === sessionId)?.status === "archived";
    if (!wsRef.current || waiting || wsRef.current.readyState !== WebSocket.OPEN || isArchived) return;

    const blocks = extractContentBlocks(inputRef.current, pendingImages);
    const hasContent = blocks.length > 0;
    if (!hasContent) return;

    const content: MessageContent = blocks.length === 1 && blocks[0].type === "text" ? blocks[0].text : blocks;

    wsRef.current.send(JSON.stringify({
      type: "user_message",
      content,
      target_sessions: targetSessions,
      ...(visible_characters ? { visible_characters } : {}),
      ...(response_characters ? { response_characters } : {}),
    }));
    setInput("");
    setPendingImages([]);
    setWaiting(true);
    ignoreStaleRef.current = false;
    streamDoneRef.current = false;
    isAtBottomRef.current = true;
    instantScrollRef.current = true;
    scrollToBottomIfAtBottom(true);
  }, [pendingImages, sessions, sessionId, waiting, scrollToBottomIfAtBottom]);

  const extractContentBlocks = (el: HTMLDivElement | null, images: PendingImage[]): ContentBlock[] => {
    if (!el) return [];
    const blocks: ContentBlock[] = [];
    const imageMap = new Map(images.map((img) => [img.id, img]));

    const imageNodes = el.querySelectorAll<HTMLSpanElement>(".input-inline-image");
    if (imageNodes.length === 0) {
      const text = (el.innerText || "").replace(/\u200B/g, "").replace(/\n{3,}/g, "\n\n").trim();
      if (text) blocks.push({ type: "text", text });
      return blocks;
    }

    const imagePositions = new Map<Node, PendingImage>();
    imageNodes.forEach((node) => {
      const id = node.dataset.imageId;
      const img = id ? imageMap.get(id) : undefined;
      if (img) imagePositions.set(node, img);
    });

    let currentText = "";
    const flushText = () => {
      const cleaned = currentText.replace(/\u200B/g, "").replace(/\n{3,}/g, "\n\n").trim();
      if (cleaned) blocks.push({ type: "text", text: cleaned });
      currentText = "";
    };

    const walk = (node: Node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        currentText += node.textContent || "";
        return;
      }
      if (node.nodeType === Node.ELEMENT_NODE) {
        const el = node as HTMLElement;
        if (imagePositions.has(el)) {
          flushText();
          blocks.push({ type: "image_url", image_url: { url: imagePositions.get(el)!.dataUrl } });
          return;
        }
        for (const child of Array.from(el.childNodes)) {
          if (child.nodeType === Node.ELEMENT_NODE && (child as HTMLElement).tagName === "BR") {
            currentText += "\n";
          } else {
            walk(child);
          }
        }
        if (el.tagName === "DIV") {
          currentText += "\n";
        }
      }
    };

    for (const child of Array.from(el.childNodes)) {
      walk(child);
    }
    flushText();
    return blocks;
  };

  const handleFileUpload = useCallback((files: FileList | File[] | null) => {
    const isArchived = sessions.find((s) => s.id === sessionId)?.status === "archived";
    if (!files || files.length === 0 || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || isArchived) return;

    setUploading(true);
    let completed = 0;
    const total = files.length;

    Array.from(files).forEach((file) => {
      const localPath = (file as any).path || (file as any).webkitRelativePath || "";

      if (localPath) {
        wsRef.current!.send(
          JSON.stringify({
            type: "file_upload",
            filename: file.name,
            mime_type: file.type || "application/octet-stream",
            local_path: localPath,
            file_data: "",
          })
        );
        addMessage("system", `📎 上传中（硬链接）：${file.name}`);
        completed++;
        if (completed === total) {
          setUploading(false);
          if (fileInputRef.current) fileInputRef.current.value = "";
        }
        return;
      }

      const reader = new FileReader();
      reader.onload = () => {
        const base64 = (reader.result as string).split(",")[1] || "";
        wsRef.current!.send(
          JSON.stringify({
            type: "file_upload",
            filename: file.name,
            mime_type: file.type || "application/octet-stream",
            file_data: base64,
          })
        );
        addMessage("system", `📎 正在上传：${file.name} (${(file.size / 1024).toFixed(1)}KB)...`);
        completed++;
        if (completed === total) {
          setUploading(false);
          if (fileInputRef.current) fileInputRef.current.value = "";
        }
      };
      reader.onerror = () => {
        addMessage("error", `文件读取失败：${file.name}`);
        completed++;
        if (completed === total) setUploading(false);
      };
      reader.readAsDataURL(file);
    });
  }, [sessions, sessionId, addMessage]);

  const addPendingImage = useCallback((file: File) => {
    return new Promise<{ id: string; dataUrl: string } | null>((resolve) => {
      if (!file.type.startsWith("image/")) {
        addMessage("error", "仅支持粘贴图片文件");
        resolve(null);
        return;
      }
      if (file.size > MAX_PASTE_IMAGE_SIZE) {
        addMessage("error", `图片超过 20MB 限制：${file.name}`);
        resolve(null);
        return;
      }
      const id = generateUUID();
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = reader.result as string;
        setPendingImages((prev) => [...prev, { id, file, dataUrl }]);
        resolve({ id, dataUrl });
      };
      reader.onerror = () => {
        addMessage("error", `读取图片失败：${file.name}`);
        resolve(null);
      };
      reader.readAsDataURL(file);
    });
  }, [addMessage]);

  const removePendingImage = useCallback((id: string) => {
    setPendingImages((prev) => prev.filter((img) => img.id !== id));
  }, []);

  const handlePasteImages = useCallback(async (file: File) => {
    return addPendingImage(file);
  }, [addPendingImage]);


  const isLocal = typeof window !== "undefined" &&
    (window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost");

  const handleUploadClick = useCallback(async () => {
    if (isLocal) {
      try {
        const resp = await fetch("/api/file-picker", { method: "POST" });
        const data = await resp.json();
        if (data.uploaded && data.files) {
          for (const f of data.files) {
            addMessage("system", `📎 ${f.method === "hardlink" ? "硬链接" : "复制"}: ${f.filename} (${(f.size / 1024).toFixed(1)}KB)`);
          }
        } else if (data.error) {
          addMessage("error", `文件选择失败: ${data.error}`);
          if (isLocal) fileInputRef.current?.click();
        }
      } catch (err) {
        addMessage("error", `文件选择异常: ${err}`);
        fileInputRef.current?.click();
      }
    } else {
      fileInputRef.current?.click();
    }
  }, [addMessage, isLocal]);

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    handleFileUpload(e.target.files);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, [handleFileUpload]);

  const newChat = useCallback(() => {
    manualRef.current = true;
    if (keepaliveRef.current) clearInterval(keepaliveRef.current);
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
    }
    localStorage.removeItem("evolve_session_id");
    setMessages([]);
    setSessionId("");
    setWaiting(false);
    setPendingConfirm(null);
    setHandsfreeMode(false);
    setClipboardDisplays({});
    setTaskProgress({});
    ignoreStaleRef.current = false;
    clearTimeout(timerRef.current);
    manualRef.current = false;
    connect();
  }, [connect]);

  const switchSession = useCallback((sid: string) => {
    if (sid === sessionId) return;
    manualRef.current = true;
    if (keepaliveRef.current) clearInterval(keepaliveRef.current);
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
    }
    localStorage.setItem("evolve_session_id", sid);
    setMessages([]);
    setSessionId(sid);
    setWaiting(false);
    setPendingConfirm(null);
    setClipboardDisplays({});
    setTaskProgress({});
    ignoreStaleRef.current = false;
    clearTimeout(timerRef.current);
    manualRef.current = false;
    connect();
  }, [sessionId, connect]);

  const deleteSession = useCallback((sid: string) => {
    if (!confirm("确定要删除这个会话吗？此操作不可撤销。")) return;
    const wasActive = sid === sessionId;
    fetch(`/api/sessions/${sid}`, { method: "DELETE" })
      .then(() => {
        const remaining = sessions.filter((s) => s.id !== sid);
        setSessions(remaining);
        if (wasActive) {
          if (remaining.length > 0) {
            switchSession(remaining[0].id);
          } else {
            newChat();
          }
        }
      })
      .catch(() => {});
  }, [sessions, sessionId, switchSession, newChat]);

  const autoTitleSession = useCallback((sid: string) => {
    setGeneratingTitleSessions((prev) => new Set(prev).add(sid));
    fetch(`/api/sessions/${sid}/auto-title`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        if (data.title) {
          setSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, title: data.title } : s)));
          fetchSessions();
        }
      })
      .catch(() => {})
      .finally(() => {
        setGeneratingTitleSessions((prev) => {
          const next = new Set(prev);
          next.delete(sid);
          return next;
        });
      });
  }, [fetchSessions]);

  const autoTagSession = useCallback((sid: string) => {
    setGeneratingTagSessions((prev) => new Set(prev).add(sid));
    fetch(`/api/sessions/${sid}/auto-tags`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        if (data.tags && Array.isArray(data.tags)) {
          setSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, tags: data.tags } : s)));
          fetchSessions();
          fetchAllTags();
        }
      })
      .catch(() => {})
      .finally(() => {
        setGeneratingTagSessions((prev) => {
          const next = new Set(prev);
          next.delete(sid);
          return next;
        });
      });
  }, [fetchSessions, fetchAllTags]);

  const terminateSession = useCallback((sid: string) => {
    setTerminatingSessions((prev) => new Set(prev).add(sid));
    addMessage("system", "⏳ 正在终结会话，请稍候...");
    fetch(`/api/sessions/${sid}/terminate`, { method: "POST" })
      .then(() => {
        addMessage("system", "✅ 会话已终结");
        fetchSessions();
        // 手动终结后不再自动创建新会话，也不自动路由到任何会话
      })
      .catch(() => {
        addMessage("error", "❌ 终结会话失败");
      })
      .finally(() => {
        setTerminatingSessions((prev) => {
          const next = new Set(prev);
          next.delete(sid);
          return next;
        });
      });
  }, [fetchSessions, addMessage]);



  const togglePinSession = useCallback((sid: string) => {
    fetch(`/api/sessions/${sid}/pin`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        setSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, pinned: data.pinned } : s)));
        fetchSessions();
      })
      .catch(() => {});
  }, [fetchSessions]);

  const mergeSessions = useCallback((sources: string[]) => {
    const validSources = sources.filter((sid) => {
      const session = sessions.find((s) => s.id === sid);
      return session && session.status === "archived";
    });
    if (validSources.length < 1) {
      console.warn("[merge] 没有可合并的已归档会话");
      return;
    }
    if (validSources.length !== sources.length) {
      const skipped = sources.filter((sid) => !validSources.includes(sid));
      console.warn(`[merge] 以下未归档会话被排除: ${skipped.join(", ")}`);
    }
    fetch("/api/sessions/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sources: validSources }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.session_id) {
          switchSession(data.session_id);
          fetchSessions();
        }
      })
      .catch(() => {});
  }, [switchSession, fetchSessions, sessions]);

  const branchSession = useCallback((sid: string) => mergeSessions([sid]), [mergeSessions]);

  const updateSessionTags = useCallback(async (sid: string, tags: string[]) => {
    const valid = tags
      .map((t) => t.trim())
      .filter((t) => {
        if (!t) return false;
        const zh = /^[\u4e00-\u9fa5]{1,5}$/.test(t);
        const en = /^[a-zA-Z]{1,10}$/.test(t);
        return zh || en;
      });
    const resp = await fetch(`/api/sessions/${sid}/tags`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tags: valid }),
    });
    const data = await resp.json().catch(() => ({}));
    if (data.updated) {
      setSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, tags: data.tags || valid } : s)));
      fetchSessions();
    }
    return data.tags || valid;
  }, [fetchSessions]);

  const toggleMergeSelect = useCallback((sid: string) => {
    const session = sessions.find((s) => s.id === sid);
    if (!session || session.status !== "archived") {
      console.warn(`[merge] 会话 ${sid.slice(0, 8)} 未归档，不可合并`);
      return;
    }
    setSelectedForMerge((prev) => {
      const next = new Set(prev);
      if (next.has(sid)) next.delete(sid);
      else next.add(sid);
      return next;
    });
  }, [sessions]);

  const toggleHandsfree = useCallback((enabled: boolean) => {
    setHandsfreeMode(enabled);
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: "handsfree_mode",
        content: enabled ? "true" : "false",
      }));
    }
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    fetchToolResources(sessionId);
  }, [sessionId, fetchToolResources]);

  const interrupt = useCallback(() => {
    ignoreStaleRef.current = true;
    setWaiting(false);
    // 先将流式消息固化为普通消息，再添加中断提示，保证顺序正确
    const streamed = streamingMessageRef.current;
    setStreamingMessage(null);
    setMessages((prev) => {
      let next = prev;
      if (streamed) {
        const exists = prev.some((x) => x.id === streamed.id);
        next = exists ? prev.map((x) => (x.id === streamed.id ? streamed : x)) : [...prev, streamed];
      }
      return [...next, { role: "system" as const, content: "⏹ 已中断", id: generateUUID() }];
    });
    fetch(`/api/interrupt/${sessionId || "unknown"}`, { method: "POST" })
      .catch(() => {});
  }, [sessionId]);

  // ── drawer polling ──
  useEffect(() => {
    if (!sessionId) return;
    const fetchTasks = () => {
      fetch(`/api/sessions/${sessionId}/background-tasks`).then(r => r.json()).then(d => setBgTasks(d.tasks || [])).catch(() => {});
      fetch(`/api/sessions/${sessionId}/cron-tasks`).then(r => r.json()).then(d => setCronTasks(d.tasks || [])).catch(() => {});
    };
    fetchTasks();
    const iv = setInterval(fetchTasks, 3000);
    return () => clearInterval(iv);
  }, [sessionId]);

  // 自动滚动：同时监听 messages 长度和流式消息 content 变化
  useEffect(() => {
    const previousCount = lastMessageCountRef.current;
    lastMessageCountRef.current = messages.length;
    if (messages.length === 0 || messages.length <= previousCount) return;
    scrollToBottomIfAtBottom();
  }, [messages.length, scrollToBottomIfAtBottom]);

  useEffect(() => {
    if (streamingMessage?.content || streamingMessage?.reasoningContent) {
      scrollToBottomIfAtBottom();
    }
  }, [streamingMessage?.content, streamingMessage?.reasoningContent, scrollToBottomIfAtBottom]);

  // ── connect on mount ──
  useEffect(() => {
    connect();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (keepaliveRef.current) clearInterval(keepaliveRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  const sidebarSessions = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    const filtered = q
      ? sessions.filter((s) => {
          const text = (s.title || s.id).toLowerCase();
          if (text.includes(q)) return true;
          const tags = s.tags || [];
          return tags.some((t) => t.toLowerCase().includes(q));
        })
      : sessions;
    return filtered.sort((a, b) => {
      if (Number(b.pinned) !== Number(a.pinned)) return Number(b.pinned) - Number(a.pinned);
      return (b.last_activity_at || b.created_at) - (a.last_activity_at || a.created_at);
    });
  }, [sessions, searchQuery]);

  const sessionResources = useMemo(() => extractMessageResources(messages), [messages]);

  return {
    // state
    messages,
    setMessages,
    input,
    setInput,
    status,
    waiting,
    setWaiting,
    pendingConfirm,
    setPendingConfirm,
    denyReason,
    setDenyReason,
    pendingAsk,
    setPendingAsk,
    askCustomText,
    setAskCustomText,
    askSelectedOption,
    setAskSelectedOption,
    sessionId,
    tokenUsage,
    contextTokens,
    sessions,
    setSessions,
    searchQuery,
    setSearchQuery,
    uploading,
    setUploading,
    handsfreeMode,
    setHandsfreeMode,
    taskProgress,
    setTaskProgress,
    clipboardDisplays,
    setClipboardDisplays,
    subagentSessions,
    llmMaxContextTokens,
    llmModelName,
    approvalModelName,
    approvalModelAvailable,
    mergeMode,
    setMergeMode,
    selectedForMerge,
    setSelectedForMerge,
    bgTasks,
    setBgTasks,
    cronTasks,
    setCronTasks,
    subagentIdleCountdown,
    terminatingSessions,
    generatingTitleSessions,
    generatingTagSessions,
    pendingImages,
    streamingMessage,
    allTags,
    agents,
    ignoreStaleRef,
    lastRecvAtRef,
    lastPongAtRef,
    recvTick,
    // actions
    send,
    handleFileUpload,
    handleFileInputChange,
    handleUploadClick,
    addPendingImage,
    removePendingImage,
    handlePasteImages,
    inputRef,
    newChat,
    switchSession,
    deleteSession,
    autoTitleSession,
    autoTagSession,
    terminateSession,
    togglePinSession,
    mergeSessions,
    branchSession,
    toggleMergeSelect,
    respondConfirm,
    respondAsk,
    toggleHandsfree,
    interrupt,
    toggleMessageCollapse,
    editMessage,
    deleteMessages,
    regenerateResponse,
    updateMessageVisibility,
    addMessage,
    fetchSessions,
    fetchAllTags,
    connect,
    updateSessionTags,
    attachScrollListener,
    // refs
    wsRef,
    bottomRef,
    chatAreaRef,
    isAtBottomRef,
    instantScrollRef,
    fileInputRef,
    // computed
    sidebarSessions,
    sessionResources,
  };
}