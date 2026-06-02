import { useEffect, useRef, useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

type MessageType = "system" | "user_message" | "agent_message" | "tool_call" | "tool_result" | "confirm_request" | "ask_request" | "error";

interface WSMessage {
  type: MessageType;
  session_id?: string;
  content?: string;
  message?: string;
  tool?: string;
  args?: Record<string, unknown>;
  result?: string;
  request_id?: string;
  approved?: boolean;
  action?: string;
  question?: string;
  options?: Array<{ label: string; value: string }>;
  allow_custom?: boolean;
  option?: string;
  custom_text?: string;
}

interface ConfirmRequest {
  request_id: string;
  content: string;
  command?: string[];
  reason?: string;
}

interface AskRequest {
  request_id: string;
  question: string;
  options?: Array<{ label: string; value: string }>;
  allow_custom?: boolean;
}

interface DownloadInfo {
  url: string;
  filename: string;
  description?: string;
  size?: number;
}

interface ChatMessage {
  role: "user" | "agent" | "system" | "error" | "tool";
  content: string;
  id: string;
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  imageMarkdown?: string;
  downloadInfo?: DownloadInfo;
  reasoningContent?: string;
}

interface SessionInfo {
  id: string;
  created_at: number;
  status: string;
  title?: string;
}

function formatTime(ts: number): string {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  return `${Math.floor(diff / 86400)}天前`;
}

function getDateGroup(ts: number): string {
  if (!ts) return "未知";
  const now = new Date();
  const date = new Date(ts * 1000);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dateDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.floor((today.getTime() - dateDay.getTime()) / 86400000);
  if (diffDays === 0) return "今天";
  if (diffDays === 1) return "昨天";
  if (diffDays < 7) return "最近7天";
  return date.toLocaleDateString("zh-CN");
}

interface SessionGroup {
  label: string;
  sessions: SessionInfo[];
}

function groupSessions(sessions: SessionInfo[]): SessionGroup[] {
  const map = new Map<string, SessionInfo[]>();
  for (const s of sessions) {
    const g = getDateGroup(s.created_at);
    if (!map.has(g)) map.set(g, []);
    map.get(g)!.push(s);
  }
  const order = ["今天", "昨天", "最近7天"];
  const result: SessionGroup[] = [];
  for (const label of order) {
    if (map.has(label)) {
      result.push({ label, sessions: map.get(label)! });
      map.delete(label);
    }
  }
  for (const [label, list] of map) {
    result.push({ label, sessions: list });
  }
  return result;
}

export default function App() {
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
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; sid: string } | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [adventureMode, setAdventureMode] = useState(false);
  const [llmMaxContextTokens, setLlmMaxContextTokens] = useState(0);
  const [approvalModelName, setApprovalModelName] = useState("");
  const [approvalModelAvailable, setApprovalModelAvailable] = useState(false);

  // ── lightbox: Escape 关闭 ──
  useEffect(() => {
    if (!lightboxSrc) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setLightboxSrc(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lightboxSrc]);

  const fetchSessions = useCallback(() => {
    fetch("/api/sessions")
      .then((r) => r.json())
      .then((data) => setSessions(data.sessions || []))
      .catch(() => {});
  }, []);

  const addMessage = useCallback((role: ChatMessage["role"], content: string, imageMarkdown?: string, downloadInfo?: DownloadInfo) => {
    const id = crypto.randomUUID();
    setMessages((prev) => [...prev, { role, content, id, imageMarkdown, downloadInfo }]);
  }, []);

  // ── WebSocket with auto-reconnect ───────────────────────────────────
  const reconnectRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const manualRef = useRef(false);  // true during manual reconnect (newChat/switchSession)
  const ignoreStaleRef = useRef(false);  // true after interrupt — discard stale tool events

  const connect = useCallback(() => {
    const lastSid = localStorage.getItem("evolve_session_id") || "";
    const qs = lastSid ? `?resume=${lastSid}` : "";
    const ws = new WebSocket(`ws://${location.host}/ws/chat${qs}`);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectRef.current = 0;
      setStatus("已连接");
      addMessage("system", "已连接到 Evolve Agent");
      fetchSessions();
    };

    ws.onclose = () => {
      setStatus("已断开");
      setWaiting(false);
      if (manualRef.current) return;  // manual switch — skip auto-reconnect
      if (reconnectRef.current >= 10) {
        setStatus("连接失败 — 已达到最大重试次数");
        return;
      }
      // Exponential backoff: 1s → 2s → 4s → ... max 30s
      const delay = Math.min(1000 * Math.pow(2, reconnectRef.current), 30000);
      reconnectRef.current += 1;
      setStatus(`重连中 (${(delay / 1000).toFixed(0)}s)...`);
      timerRef.current = setTimeout(connect, delay);
    };

    ws.onmessage = (e) => {
      const msg: WSMessage = JSON.parse(e.data);
      if (msg.type === "system") {
        // Check if content is JSON (session_history + token_usage on resume)
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
            return;  // silent — don't show hash as a chat message
          }
          if (data.server_info) {
            const info = data.server_info;
            if (info.llm_max_context_tokens) setLlmMaxContextTokens(info.llm_max_context_tokens);
            setApprovalModelName(info.approval_model_name || "");
            setApprovalModelAvailable(info.approval_model_available || false);
            return;  // silent — server metadata only
          }
          if (data.session_history) {
            // Session resume — replay conversation history
            const history = data.session_history.map((m: any) => {
              const entry: any = {
                role: m.role,
                content: m.content,
                id: crypto.randomUUID(),
              };
              if (m.reasoning_content) {
                entry.reasoningContent = m.reasoning_content;
              }
              // Parse tool message content to restore downloadInfo and imageMarkdown
              if (m.role === "tool" && typeof m.content === "string") {
                try {
                  const parsed = JSON.parse(m.content);
                  if (parsed.markdown) {
                    entry.imageMarkdown = parsed.markdown;
                  }
                  if (parsed.download_url) {
                    entry.downloadInfo = {
                      url: parsed.download_url,
                      filename: parsed.filename || "download",
                      description: parsed.description,
                      size: parsed.size,
                    };
                  }
                } catch {
                  // not JSON — leave as plain text
                }
              }
              return entry;
            });
            if (history.length) setMessages(history);
            if (data.token_usage !== undefined) setTokenUsage(data.token_usage);
            if (data.context_tokens !== undefined) setContextTokens(data.context_tokens);
            return;  // skip normal system message handling
          }
          if (data.token_usage !== undefined) {
            setTokenUsage(data.token_usage);
          }
          if (data.context_tokens !== undefined) {
            setContextTokens(data.context_tokens);
          }
          if (data.token_usage !== undefined || data.context_tokens !== undefined) {
            return;
          }
          if (data.action === "session_rotated") {
            setSessionId(data.new_sid);
            localStorage.setItem("evolve_session_id", data.new_sid);
            setMessages([]);
            setTokenUsage(0);
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
        ignoreStaleRef.current = false;  // new response — reset stale guard
        addMessage("agent", msg.content ?? "");
        fetchSessions();
      }
      else if (msg.type === "tool_call") {
        if (ignoreStaleRef.current) return;  // stale after interrupt
        const argsStr = msg.args
          ? "(" + Object.entries(msg.args)
              .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
              .join(", ") + ")"
          : "";
        addMessage("tool", `⚡ ${msg.tool} ${argsStr}`);
      }
      else if (msg.type === "tool_result") {
        if (ignoreStaleRef.current) return;  // stale after interrupt
        const raw = msg.result ?? "";
        let text = `✅ ${msg.tool} → `;
        let imageMarkdown: string | undefined;
        let downloadInfo: DownloadInfo | undefined;
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
          } else if (parsed.message) {
            text += parsed.message.slice(0, 200);
          } else {
            text += raw.slice(0, 2000);
          }
        } catch {
          text += raw.slice(0, 2000);
        }
        addMessage("tool", text, imageMarkdown, downloadInfo);
      }
      else if (msg.type === "error") addMessage("error", msg.message ?? "");
      else if (msg.type === "confirm_request") {
        // Show confirmation dialog — only if there's a request_id
        if (msg.request_id) {
          setDenyReason("此操作可能带来安全风险");
          setPendingConfirm({
            request_id: msg.request_id,
            content: msg.content ?? "运行命令?",
            command: (msg.args as Record<string, unknown>)?.command as string[] | undefined,
            reason: (msg.args as Record<string, unknown>)?.reason as string | undefined,
          });
        }
      }
      else if (msg.type === "ask_request") {
        // Show ask dialog
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
  }, [addMessage, fetchSessions]);

  // ── confirm response ──
  const respondConfirm = useCallback((action: string, denyReasonText?: string, deniedBy?: string) => {
    if (!pendingConfirm) return;
    const payload: Record<string, string> = { action };
    if (action === "deny" && denyReasonText) {
      payload.deny_reason = denyReasonText;
      payload.denied_by = deniedBy || "user";
    }
    console.log("[confirm] HTTP POST", pendingConfirm.request_id, payload);
    fetch(`/api/confirm/${pendingConfirm.request_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch((err) => console.error("[confirm] fetch failed", err));
    setPendingConfirm(null);
  }, [pendingConfirm]);

  // ── ask response ──
  const respondAsk = useCallback((option?: string, customText?: string) => {
    if (!pendingAsk) return;
    const payload: Record<string, string | null> = { option: option ?? null, custom_text: customText ?? null };
    console.log("[ask] HTTP POST", pendingAsk.request_id, payload);
    fetch(`/api/ask/${pendingAsk.request_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch((err) => console.error("[ask] fetch failed", err));
    setPendingAsk(null);
    setAskCustomText("");
    setAskSelectedOption(null);
  }, [pendingAsk]);

  useEffect(() => {
    connect();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ── close context menu on outside click ──
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setContextMenu(null);
      }
    };
    const escHandler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setContextMenu(null);
    };
    if (contextMenu) {
      document.addEventListener("mousedown", handler);
      document.addEventListener("keydown", escHandler);
    }
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("keydown", escHandler);
    };
  }, [contextMenu]);

  const send = () => {
    const text = input.trim();
    if (!text || !wsRef.current || waiting || wsRef.current.readyState !== WebSocket.OPEN) return;
    addMessage("user", text);
    wsRef.current.send(
      JSON.stringify({ type: "user_message", content: text })
    );
    setInput("");
    setWaiting(true);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    // 限制文件大小：20MB
    if (file.size > 20 * 1024 * 1024) {
      addMessage("error", `文件过大：${(file.size / 1024 / 1024).toFixed(1)}MB（最大 20MB）`);
      return;
    }

    setUploading(true);
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
      setUploading(false);
      // 重置 input 以允许重复上传同名文件
      if (fileInputRef.current) fileInputRef.current.value = "";
    };
    reader.onerror = () => {
      addMessage("error", `文件读取失败：${file.name}`);
      setUploading(false);
    };
    reader.readAsDataURL(file);
  };

  const newChat = () => {
    manualRef.current = true;
    if (wsRef.current) wsRef.current.close();
    localStorage.removeItem("evolve_session_id");
    setMessages([]);
    setSessionId("");
    setWaiting(false);
    setPendingConfirm(null);
    setAdventureMode(false);
    clearTimeout(timerRef.current);
    manualRef.current = false;
    connect();
  };

  const switchSession = (sid: string) => {
    if (sid === sessionId) return;
    manualRef.current = true;
    if (wsRef.current) wsRef.current.close();
    localStorage.setItem("evolve_session_id", sid);
    setMessages([]);
    setSessionId(sid);
    setWaiting(false);
    setPendingConfirm(null);
    clearTimeout(timerRef.current);
    manualRef.current = false;
    connect();
  };

  const deleteSession = (sid: string) => {
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
  };

  // ── rename ──
  const startRename = (sid: string, currentTitle: string) => {
    setContextMenu(null);
    setRenamingId(sid);
    setRenameValue(currentTitle || sid.slice(0, 8) + "...");
  };

  const submitRename = (sid: string) => {
    const title = renameValue.trim();
    if (title) {
      fetch(`/api/sessions/${sid}/title`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      }).then(() => {
        setSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, title } : s)));
        fetchSessions(); // sync from server
      }).catch(() => {});
    }
    setRenamingId(null);
  };

  const cancelRename = () => {
    setRenamingId(null);
  };

  // ── auto-title ──
  const autoTitleSession = (sid: string) => {
    setContextMenu(null);
    // Show temporary loading indicator by clearing the title display
    fetch(`/api/sessions/${sid}/auto-title`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        if (data.title) {
          setSessions((prev) => prev.map((s) => (s.id === sid ? { ...s, title: data.title } : s)));
          fetchSessions();
        }
      })
      .catch(() => {});
  };

  // ── context menu ──
  const handleContextMenu = (e: React.MouseEvent, sid: string) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, sid });
  };

  return (
    <div className="app">
      <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
        <div className="sidebar-header">
          <div className="sidebar-title">💬 会话</div>
          <button className="new-chat-btn" onClick={newChat}>+ 新对话</button>
          <div className="sidebar-search">
            <input
              className="search-input"
              type="text"
              placeholder="搜索会话..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>
        <div className="session-list">
          {(() => {
            const q = searchQuery.toLowerCase();
            const filtered = q
              ? sessions.filter((s) => (s.title || s.id).toLowerCase().includes(q))
              : sessions;
            const groups = groupSessions(filtered);
            if (groups.length === 0) {
              return <div className="session-empty">无匹配会话</div>;
            }
            return groups.map((g) => (
              <div key={g.label}>
                <div className="session-group-header">{g.label}</div>
                {g.sessions.map((s) => (
                  <div
                    key={s.id}
                    className={`session-item ${s.id === sessionId ? "active" : ""} ${s.status === "archived" ? "archived" : ""}`}
                    onClick={() => { if (s.status !== "archived") switchSession(s.id); }}
                    onContextMenu={(e) => handleContextMenu(e, s.id)}
                  >
                    <div className="session-item-content">
                      {renamingId === s.id ? (
                        <input
                          className="rename-input"
                          type="text"
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") submitRename(s.id);
                            else if (e.key === "Escape") cancelRename();
                          }}
                          onBlur={() => submitRename(s.id)}
                          autoFocus
                          onClick={(e) => e.stopPropagation()}
                        />
                      ) : (
                        <div className="session-item-title">
                          {s.title || s.id.slice(0, 8) + "..."}
                          {s.status === "archived" && <span className="archived-badge">已归档</span>}
                        </div>
                      )}
                      <div className="session-item-sub">
                        <span className="session-item-id">{s.id}</span>
                        <span className="session-item-time">{formatTime(s.created_at)}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ));
          })()}
        </div>
      </aside>
      {contextMenu && (
        <div
          ref={menuRef}
          className="context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <div className="context-menu-item" onClick={() => { const s = sessions.find(s => s.id === contextMenu.sid); if (s) startRename(s.id, s.title || ""); }}>
            重命名
          </div>
          <div className="context-menu-item" onClick={() => autoTitleSession(contextMenu.sid)}>
            自动命名
          </div>
          <div className="context-menu-separator" />
          <div className="context-menu-item context-menu-item-danger" onClick={() => { setContextMenu(null); deleteSession(contextMenu.sid); }}>
            删除会话
          </div>
        </div>
      )}
      <div className="main-content">
        <header className="app-header">
        <div className="header-left">
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed(v => !v)}
            title={sidebarCollapsed ? "展开侧栏" : "收起侧栏"}
          >
            {sidebarCollapsed ? (
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M9 18l6-6-6-6" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 18l-6-6 6-6" />
              </svg>
            )}
          </button>
          <div className="model-icon">⚡</div>
          <div>
            <div className="model-name">Evolve Agent</div>
            <div className={`model-status ${status === "已连接" ? "connected" : ""}`}>
              <span className="status-dot" />
              {status}
            </div>
          </div>
        </div>
        {sessionId && (
          <div className="header-right">
            {approvalModelAvailable && (
              <label className="adventure-toggle" title={adventureMode ? "冒险模式已开启 — 工具调用由 AI 自动审批" : "冒险模式已关闭 — 工具调用需用户审批"}>
                <span className="adventure-label">冒险</span>
                <input
                  type="checkbox"
                  checked={adventureMode}
                  onChange={(e) => {
                    const enabled = e.target.checked;
                    setAdventureMode(enabled);
                    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                      wsRef.current.send(JSON.stringify({
                        type: "adventure_mode",
                        content: enabled ? "true" : "false",
                      }));
                    }
                  }}
                />
                <span className="adventure-slider" />
              </label>
            )}
            {adventureMode && approvalModelName && (
              <span className="approval-model-badge" title={`审批模型: ${approvalModelName}`}>
                {approvalModelName}
              </span>
            )}
            <span className="session-badge" title="刷新页面后自动恢复此会话">
              {sessionId}
            </span>
            <span className="token-badge" title={`累计消耗: ${tokenUsage.toLocaleString()}  |  已用上下文: ${contextTokens.toLocaleString()}  |  最大上下文: ${llmMaxContextTokens > 0 ? llmMaxContextTokens.toLocaleString() : "?"}`}>
              累计 {tokenUsage.toLocaleString()} / 上下文 {contextTokens.toLocaleString()} / 上限 {llmMaxContextTokens > 0 ? llmMaxContextTokens.toLocaleString() : "?"}
            </span>
          </div>
        )}
      </header>

      <main className="chat-area">
        {messages.map((m) => (
          <div key={m.id} className={`message message-${m.role}`}>
            <div className="message-avatar">
              {m.role === "user" ? "U" : m.role === "agent" ? "⚡" : m.role === "error" ? "!" : m.role === "tool" ? "🔧" : "●"}
            </div>
            <div className="message-bubble">
              {m.role === "tool" ? (
                <details className="tool-call-block">
                  <summary className="tool-call-summary">
                    {m.content.length > 80 ? m.content.slice(0, 80) + '...' : m.content}
                  </summary>
                  <div className="tool-call-detail">
                    <pre className="message-text message-text-tool">{m.content}</pre>
                  {m.imageMarkdown && (() => {
                    const md = m.imageMarkdown;
                    const match = md.match(/!\[(.*?)\]\(([^)]+)\)/);
                    const altText = match ? match[1] : "";
                    const imgSrc = match ? match[2] : "";
                    return imgSrc ? (
                      <a href="#" onClick={(e) => { e.preventDefault(); setLightboxSrc(imgSrc); }} className="tool-image-link">
                        <img src={imgSrc} alt={altText} className="tool-image" />
                      </a>
                    ) : null;
                  })()}
                  {m.downloadInfo && (
                    <div className="tool-download">
                      <a
                        href={m.downloadInfo.url}
                        className="download-btn"
                        download={m.downloadInfo.filename}
                      >
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                          <polyline points="7 10 12 15 17 10" />
                          <line x1="12" y1="15" x2="12" y2="3" />
                        </svg>
                        下载 {m.downloadInfo.filename}
                      </a>
                      {m.downloadInfo.size != null && (
                        <span className="download-size">（{(m.downloadInfo.size / 1024).toFixed(1)} KB）</span>
                      )}
                    </div>
                  )}
                    </div>
                </details>
              ) : m.role === "agent" ? (
                <>
                  {m.reasoningContent && (
                    <details className="reasoning-block">
                      <summary className="reasoning-summary">思考过程</summary>
                      <div className="reasoning-content">{m.reasoningContent}</div>
                    </details>
                  )}
                  <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    code({ className, children, ...props }) {
                      const match = /language-(\w+)/.exec(className || "");
                      const code = String(children).replace(/\n$/, "");
                      if (match) {
                        return (
                          <SyntaxHighlighter
                            style={oneDark}
                            language={match[1]}
                            PreTag="div"
                            customStyle={{ margin: 0, borderRadius: 6 }}
                          >
                            {code}
                          </SyntaxHighlighter>
                        );
                      }
                      return (
                        <code className={className} {...props}>
                          {children}
                        </code>
                      );
                    },
                    p({ children }) {
                      return <p style={{ margin: "0.4em 0" }}>{children}</p>;
                    },
                    ul({ children }) {
                      return <ul style={{ margin: "0.3em 0", paddingLeft: "1.5em" }}>{children}</ul>;
                    },
                    ol({ children }) {
                      return <ol style={{ margin: "0.3em 0", paddingLeft: "1.5em" }}>{children}</ol>;
                    },
                    table({ children }) {
                      return (
                        <div style={{ overflowX: "auto" }}>
                          <table style={{ borderCollapse: "collapse", width: "100%" }}>{children}</table>
                        </div>
                      );
                    },
                    th({ children }) {
                      return (
                        <th style={{ border: "1px solid #444", padding: "6px 10px", background: "#2a2a2a" }}>
                          {children}
                        </th>
                      );
                    },
                    td({ children }) {
                      return <td style={{ border: "1px solid #444", padding: "6px 10px" }}>{children}</td>;
                    },
                    a({ href, children }) {
                      return (
                        <a href={href} target="_blank" rel="noopener noreferrer">
                          {children}
                        </a>
                      );
                    },
                    img({ src, alt }) {
                      return (
                        <a href="#" onClick={(e) => { e.preventDefault(); setLightboxSrc(src!); }} className="message-img-link">
                          <img src={src} alt={alt || ''} className="message-img" />
                        </a>
                      );
                    },
                  }}
                >
                  {m.content}
                </ReactMarkdown>
                </>
              ) : (
                <pre className={`message-text message-text-${m.role}`}>{m.content}</pre>
              )}
            </div>
          </div>
        ))}

        {waiting && (
          <div className="message message-agent">
            <div className="message-avatar">⚡</div>
            <div className="message-bubble">
              <div className="typing-indicator">
                <span /><span /><span />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      {/* ── Confirm dialog for shell commands ── */}
      {pendingConfirm && (
        <div className="confirm-overlay">
          <div className="confirm-dialog">
            <div className="confirm-title">确认执行命令</div>
            <div className="confirm-body">
              <pre className="confirm-cmd">
                {pendingConfirm.command?.join(" ") ?? pendingConfirm.content}
              </pre>
              {pendingConfirm.reason && (
                <div className="confirm-reason">原因: {pendingConfirm.reason}</div>
              )}
              <textarea
                className="confirm-deny-reason"
                value={denyReason}
                onChange={(e) => setDenyReason(e.target.value)}
                placeholder="输入拒绝原因..."
                rows={2}
              />
            </div>
            <div className="confirm-actions">
              <button
                className="confirm-deny"
                onClick={() => respondConfirm("deny", denyReason, "user")}>
                拒绝
              </button>
              <button className="confirm-once" onClick={() => respondConfirm("allow_once")}>
                允许一次
              </button>
              <button className="confirm-always" onClick={() => respondConfirm("allow_always")}>
                始终允许
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Ask dialog for agent questions ── */}
      {pendingAsk && (
        <div className="confirm-overlay" onClick={() => {}}>
          <div className="confirm-dialog ask-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="confirm-title">❓ {pendingAsk.question}</div>
            <div className="confirm-body">
              {pendingAsk.options && pendingAsk.options.length > 0 && (
                <div className="ask-options">
                  {pendingAsk.options.map((opt) => (
                    <button
                      key={opt.value}
                      className={`ask-option-btn ${askSelectedOption === opt.value ? "ask-option-selected" : ""}`}
                      onClick={() => {
                        setAskSelectedOption(opt.value);
                        setAskCustomText("");
                      }}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
              {pendingAsk.allow_custom !== false && (
                <textarea
                  className="ask-custom-input"
                  value={askCustomText}
                  onChange={(e) => {
                    setAskCustomText(e.target.value);
                    if (e.target.value) setAskSelectedOption(null);
                  }}
                  placeholder="输入自定义内容..."
                  rows={3}
                />
              )}
            </div>
            <div className="confirm-actions">
              <button
                className="confirm-deny"
                onClick={() => respondAsk(undefined, undefined)}
              >
                跳过
              </button>
              <button
                className="confirm-always"
                disabled={!askSelectedOption && !askCustomText.trim()}
                onClick={() => respondAsk(askSelectedOption ?? undefined, askCustomText.trim() || undefined)}
              >
                提交
              </button>
            </div>
          </div>
        </div>
      )}

      <footer className="input-bar">
        <textarea
          className="input-field"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          onInput={(e) => {
            const el = e.currentTarget;
            el.style.height = "auto";
            el.style.height = el.scrollHeight + "px";
          }}
          placeholder="输入消息..."
          autoFocus
          disabled={waiting}
          rows={1}
        />
        <input
          ref={fileInputRef}
          type="file"
          className="file-input-hidden"
          onChange={handleFileUpload}
          accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt,.json,.py,.js,.ts,.html,.css,.md,.zip,.tar,.gz"
          disabled={uploading}
        />
        <button
          className="upload-btn"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          title="上传文件"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
        </button>
        <button className="send-btn" onClick={send} disabled={waiting || !input.trim()}>
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M22 2L11 13" /><path d="M22 2L15 22L11 13L2 9L22 2Z" />
          </svg>
        </button>
        {waiting && (
          <button
            className="interrupt-btn"
            onClick={() => {
              ignoreStaleRef.current = true;
              setWaiting(false);
              addMessage("system", "⏹ 已中断");
              fetch(`/api/interrupt/${sessionId || "unknown"}`, { method: "POST" })
                .catch(() => {});
            }}
          >
            ⏹
          </button>
        )}
      </footer>
      </div>
      {/* ── lightbox 遮罩 ── */}
      {lightboxSrc && (
        <div className="lightbox-backdrop" onClick={() => setLightboxSrc(null)}>
          <img src={lightboxSrc} className="lightbox-img" onClick={(e) => e.stopPropagation()} />
        </div>
      )}
    </div>
  );
}