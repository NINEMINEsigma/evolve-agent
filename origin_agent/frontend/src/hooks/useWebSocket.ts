import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import {
  ChatMessage,
  ConfirmRequest,
  AskRequest,
  DownloadInfo,
  PlaylistEntry,
  TaskProgress,
  ClipboardDisplay,
  CronTask,
  SessionInfo,
  WSMessage,
} from "../types";

export function useWebSocket() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState("connecting...");
  const [waiting, setWaiting] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<ConfirmRequest | null>(null);
  const [denyReason, setDenyReason] = useState("此操作可能带来安全风险");
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
  const [llmMaxContextTokens, setLlmMaxContextTokens] = useState(0);
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
  const [terminatingSessions, setTerminatingSessions] = useState<Set<string>>(new Set());

  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const instantScrollRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const reconnectRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const manualRef = useRef(false);
  const ignoreStaleRef = useRef(false);
  const lastMessageCountRef = useRef(0);

  const nextMessageIndex = useCallback((items: ChatMessage[]) => {
    const indexes = items
      .map((m) => m.messageIndex)
      .filter((index): index is number => typeof index === "number");
    return indexes.length ? Math.max(...indexes) + 1 : 0;
  }, []);

  const addMessage = useCallback((
    role: ChatMessage["role"],
    content: string,
    imageMarkdown?: string,
    downloadInfo?: DownloadInfo,
    audioUrl?: string,
    audioAutoplay?: boolean,
    playlist?: PlaylistEntry[],
    playlistAutoplay?: boolean,
    messageIndex?: number
  ) => {
    const id = crypto.randomUUID();
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

  const connect = useCallback(() => {
    const lastSid = localStorage.getItem("evolve_session_id") || "";
    const qs = lastSid ? `?resume=${lastSid}` : "";
    const ws = new WebSocket(`ws://${location.host}/ws/chat${qs}`);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectRef.current = 0;
      setStatus("已连接");
      instantScrollRef.current = true;
      addMessage("system", "已连接到 Evolve Agent");
      fetchSessions();
    };

    ws.onclose = () => {
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
      if (msg.type === "system") {
        const raw = msg.content ?? "";
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
            setApprovalModelName(info.approval_model_name || "");
            setApprovalModelAvailable(info.approval_model_available || false);
            return;
          }
          if (data.session_history) {
            const history = data.session_history.map((m: any) => {
              const entry: any = {
                role: m.role,
                content: m.content,
                id: crypto.randomUUID(),
                messageIndex: typeof m.index === "number" ? m.index : undefined,
              };
              if (m.reasoning_content) {
                entry.reasoningContent = m.reasoning_content;
              }
              if (m.role === "tool" && typeof m.content === "string") {
                try {
                  const parsed = JSON.parse(m.content);
                  if (parsed.markdown) entry.imageMarkdown = parsed.markdown;
                  if (parsed.download_url) {
                    entry.downloadInfo = {
                      url: parsed.download_url,
                      filename: parsed.filename || "download",
                      description: parsed.description,
                      size: parsed.size,
                    };
                  }
                  if (parsed.audio_url) {
                    entry.audioUrl = parsed.audio_url;
                    entry.audioAutoplay = false;
                  }
                  if (parsed.playlist) {
                    entry.playlist = parsed.playlist;
                    entry.playlistAutoplay = false;
                  }
                  if (parsed.message && typeof parsed.message === "string") {
                    entry.content = parsed.message;
                  }
                } catch {
                  // not JSON
                }
              }
              return entry;
            });
            if (history.length) {
              instantScrollRef.current = true;
              setMessages(history);
            }
            if (data.token_usage !== undefined) setTokenUsage(data.token_usage);
            if (data.context_tokens !== undefined) setContextTokens(data.context_tokens);
            return;
          }
          if (data.token_usage !== undefined) setTokenUsage(data.token_usage);
          if (data.context_tokens !== undefined) setContextTokens(data.context_tokens);
          if (data.token_usage !== undefined || data.context_tokens !== undefined) return;
          if (data.action === "session_rotated") {
            setSessionId(data.new_sid);
            localStorage.setItem("evolve_session_id", data.new_sid);
            setMessages([]);
            setTokenUsage(0);
            setClipboardDisplays({});
            setTaskProgress({});
            fetchSessions();
            return;
          }
          if (data.uploaded) {
            addMessage("system", `✅ 上传成功：${data.filename || "文件"} → ${data.path}`);
            return;
          }
          if (data.assistant_text) {
            const p = JSON.parse(data.assistant_text);
            const id = crypto.randomUUID();
            setMessages((prev) => [...prev, {
              role: "agent",
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
        }
      }
      else if (msg.type === "agent_message") {
        setWaiting(false);
        ignoreStaleRef.current = false;
        setMessages((prev) => [...prev, {
          role: "agent",
          content: msg.content ?? "",
          id: crypto.randomUUID(),
          messageIndex: nextMessageIndex(prev),
        }]);
        fetchSessions();
      }
      else if (msg.type === "tool_call") {
        if (ignoreStaleRef.current) return;
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
        let text = `✅ ${msg.tool} → `;
        let imageMarkdown: string | undefined;
        let downloadInfo: DownloadInfo | undefined;
        let audioUrl: string | undefined;
        let audioAutoplay = false;
        let playlist: PlaylistEntry[] | undefined;
        let playlistAutoplay = false;
        try {
          const parsed = JSON.parse(raw);
          if (parsed.markdown) {
            imageMarkdown = parsed.markdown;
            text += (parsed.message ?? "").slice(0, 200);
          } else if (parsed.download_url) {
            downloadInfo = {
              url: parsed.download_url,
              filename: parsed.filename || "download",
              description: parsed.description,
              size: parsed.size,
            };
            text += (parsed.message ?? "").slice(0, 200);
          } else if (parsed.audio_url) {
            audioUrl = parsed.audio_url;
            audioAutoplay = parsed.autoplay === true;
            text += (parsed.message ?? "").slice(0, 200);
          } else if (parsed.playlist) {
            playlist = parsed.playlist;
            playlistAutoplay = parsed.autoplay === true;
            text += (parsed.message ?? "").slice(0, 200);
          } else if (parsed.message) {
            text += parsed.message.slice(0, 200);
          } else {
            text += raw.slice(0, 2000);
          }
        } catch {
          text += raw.slice(0, 2000);
        }
        setMessages((prev) => [...prev, {
          role: "tool",
          content: text,
          id: crypto.randomUUID(),
          imageMarkdown,
          downloadInfo,
          audioUrl,
          audioAutoplay,
          playlist,
          playlistAutoplay,
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
      else if (msg.type === "error") {
        addMessage("error", msg.message ?? "");
      }
      else if (msg.type === "confirm_request") {
        if (msg.request_id) {
          setDenyReason("此操作可能带来安全风险");
          setPendingConfirm({
            request_id: msg.request_id,
            content: msg.content ?? "运行命令?",
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
  }, [addMessage, fetchSessions, nextMessageIndex]);

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

  const send = useCallback(() => {
    const text = input.trim();
    const isArchived = sessions.find((s) => s.id === sessionId)?.status === "archived";
    if (!text || !wsRef.current || waiting || wsRef.current.readyState !== WebSocket.OPEN || isArchived) return;
    setMessages((prev) => [...prev, {
      role: "user",
      content: text,
      id: crypto.randomUUID(),
      messageIndex: nextMessageIndex(prev),
    }]);
    wsRef.current.send(JSON.stringify({ type: "user_message", content: text }));
    setInput("");
    setWaiting(true);
  }, [input, sessions, sessionId, waiting, nextMessageIndex]);

  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    const isArchived = sessions.find((s) => s.id === sessionId)?.status === "archived";
    if (!files || files.length === 0 || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || isArchived) return;

    setUploading(true);
    let completed = 0;

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
        if (completed === files.length) {
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
        if (completed === files.length) {
          setUploading(false);
          if (fileInputRef.current) fileInputRef.current.value = "";
        }
      };
      reader.onerror = () => {
        addMessage("error", `文件读取失败：${file.name}`);
        completed++;
        if (completed === files.length) setUploading(false);
      };
      reader.readAsDataURL(file);
    });
  }, [sessions, sessionId, addMessage]);

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

  const newChat = useCallback(() => {
    manualRef.current = true;
    if (wsRef.current) wsRef.current.close();
    localStorage.removeItem("evolve_session_id");
    setMessages([]);
    setSessionId("");
    setWaiting(false);
    setPendingConfirm(null);
    setHandsfreeMode(false);
    setClipboardDisplays({});
    setTaskProgress({});
    clearTimeout(timerRef.current);
    manualRef.current = false;
    connect();
  }, [connect]);

  const switchSession = useCallback((sid: string) => {
    if (sid === sessionId) return;
    manualRef.current = true;
    if (wsRef.current) wsRef.current.close();
    localStorage.setItem("evolve_session_id", sid);
    setMessages([]);
    setSessionId(sid);
    setWaiting(false);
    setPendingConfirm(null);
    setClipboardDisplays({});
    setTaskProgress({});
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
    fetch(`/api/sessions/${sid}/auto-title`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        if (data.title) {
          setSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, title: data.title } : s)));
          fetchSessions();
        }
      })
      .catch(() => {});
  }, [fetchSessions]);

  const terminateSession = useCallback((sid: string) => {
    setTerminatingSessions((prev) => new Set(prev).add(sid));
    addMessage("system", "⏳ 正在终结会话，请稍候...");
    fetch(`/api/sessions/${sid}/terminate`, { method: "POST" })
      .then(() => {
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
    fetch("/api/sessions/merge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sources }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.session_id) {
          switchSession(data.session_id);
          fetchSessions();
        }
      })
      .catch(() => {});
  }, [switchSession, fetchSessions]);

  const branchSession = useCallback((sid: string) => mergeSessions([sid]), [mergeSessions]);

  const toggleMergeSelect = useCallback((sid: string) => {
    setSelectedForMerge((prev) => {
      const next = new Set(prev);
      if (next.has(sid)) next.delete(sid);
      else next.add(sid);
      return next;
    });
  }, []);

  const toggleHandsfree = useCallback((enabled: boolean) => {
    setHandsfreeMode(enabled);
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: "handsfree_mode",
        content: enabled ? "true" : "false",
      }));
    }
  }, []);

  const interrupt = useCallback(() => {
    ignoreStaleRef.current = true;
    setWaiting(false);
    addMessage("system", "⏹ 已中断");
    fetch(`/api/interrupt/${sessionId || "unknown"}`, { method: "POST" })
      .catch(() => {});
  }, [sessionId, addMessage]);

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

  // ── auto scroll ──
  useEffect(() => {
    const previousCount = lastMessageCountRef.current;
    lastMessageCountRef.current = messages.length;
    if (messages.length === 0 || messages.length <= previousCount) return;
    const behavior = instantScrollRef.current ? "auto" : "smooth";
    instantScrollRef.current = false;
    bottomRef.current?.scrollIntoView({ behavior });
  }, [messages.length]);

  // ── connect on mount ──
  useEffect(() => {
    connect();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  const sidebarSessions = useMemo(() => {
    const q = searchQuery.toLowerCase();
    const filtered = q
      ? sessions.filter((s) => (s.title || s.id).toLowerCase().includes(q))
      : sessions;
    return filtered.sort((a, b) => {
      if (Number(b.pinned) !== Number(a.pinned)) return Number(b.pinned) - Number(a.pinned);
      return (b.last_activity_at || b.created_at) - (a.last_activity_at || a.created_at);
    });
  }, [sessions, searchQuery]);

  const sessionResources = useMemo(() => {
    const images: Array<{ id: string; src: string; alt: string }> = [];
    const audios: Array<{ id: string; url: string; autoplay?: boolean }> = [];
    const downloads: Array<{ id: string; url: string; filename: string; size?: number }> = [];
    const seen = new Set<string>();
    messages.forEach((m) => {
      if (m.imageMarkdown) {
        const match = m.imageMarkdown.match(/!\[(.*?)\]\(([^)]+)\)/);
        if (match) {
          const src = match[2];
          if (!seen.has(src)) {
            seen.add(src);
            images.push({ id: m.id + "-img", src, alt: match[1] || "" });
          }
        }
      }
      if (m.audioUrl && !seen.has(m.audioUrl)) {
        seen.add(m.audioUrl);
        audios.push({ id: m.id + "-audio", url: m.audioUrl, autoplay: m.audioAutoplay });
      }
      if (m.downloadInfo && !seen.has(m.downloadInfo.url)) {
        seen.add(m.downloadInfo.url);
        downloads.push({ id: m.id + "-dl", url: m.downloadInfo.url, filename: m.downloadInfo.filename, size: m.downloadInfo.size });
      }
      if (m.role === "agent") {
        const imgMatches = m.content.matchAll(/!\[(.*?)\]\(([^)]+)\)/g);
        for (const match of imgMatches) {
          const src = match[2];
          if (!seen.has(src)) {
            seen.add(src);
            images.push({ id: m.id + "-mdimg-" + src.slice(-8), src, alt: match[1] || "" });
          }
        }
      }
    });
    return { images, audios, downloads };
  }, [messages]);

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
    llmMaxContextTokens,
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
    terminatingSessions,
    // actions
    send,
    handleFileUpload,
    handleUploadClick,
    newChat,
    switchSession,
    deleteSession,
    autoTitleSession,
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
    addMessage,
    fetchSessions,
    connect,
    // refs
    wsRef,
    bottomRef,
    instantScrollRef,
    fileInputRef,
    // computed
    sidebarSessions,
    sessionResources,
  };
}