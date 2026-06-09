import { useEffect, useRef, useState, useCallback, useMemo, memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore clipboard errors
    }
  };
  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <span className="code-block-lang">{language}</span>
        <button className="code-block-copy" onClick={handleCopy}>
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      <SyntaxHighlighter
        style={oneDark}
        language={language}
        PreTag="div"
        customStyle={{ margin: 0, borderRadius: "0 0 6px 6px" }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}

const markdownComponentsBase = {
  code({ className, children, ...props }: any) {
    const match = /language-(\w+)/.exec(className || "");
    const code = String(children).replace(/\n$/, "");
    if (match) {
      return <CodeBlock language={match[1]} code={code} />;
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
  p({ children }: any) {
    return <p style={{ margin: "0.4em 0" }}>{children}</p>;
  },
  ul({ children }: any) {
    return <ul style={{ margin: "0.3em 0", paddingLeft: "1.5em" }}>{children}</ul>;
  },
  ol({ children }: any) {
    return <ol style={{ margin: "0.3em 0", paddingLeft: "1.5em" }}>{children}</ol>;
  },
  table({ children }: any) {
    return (
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>{children}</table>
      </div>
    );
  },
  th({ children }: any) {
    return (
      <th style={{ border: "1px solid #444", padding: "6px 10px", background: "#2a2a2a" }}>
        {children}
      </th>
    );
  },
  td({ children }: any) {
    return <td style={{ border: "1px solid #444", padding: "6px 10px" }}>{children}</td>;
  },
  a({ href, children }: any) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },
};

const MessageItem = memo(function MessageItem({ message, onImageClick }: {
  message: ChatMessage;
  onImageClick: (src: string) => void;
}) {
  const m = message;

  const mdComponents = useMemo(() => ({
    ...markdownComponentsBase,
    img({ src, alt }: any) {
      return (
        <a href="#" onClick={(e) => { e.preventDefault(); onImageClick(src!); }} className="message-img-link">
          <img src={src} alt={alt || ''} className="message-img" />
        </a>
      );
    },
  }), [onImageClick]);

  return (
    <div className={`message message-${m.role}`}>
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
                  <a href="#" onClick={(e) => { e.preventDefault(); onImageClick(imgSrc); }} className="tool-image-link">
                    <img src={imgSrc} alt={altText} className="tool-image" />
                  </a>
                ) : null;
              })()}
              {m.audioUrl && (
                <div className="tool-audio">
                  <audio controls={true} autoPlay={m.audioAutoplay} src={m.audioUrl} className="tool-audio-player">
                    您的浏览器不支持音频播放
                  </audio>
                </div>
              )}
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
              components={mdComponents}
            >
              {m.content}
            </ReactMarkdown>
          </>
        ) : (
          <pre className={`message-text message-text-${m.role}`}>{m.content}</pre>
        )}
      </div>
    </div>
  );
});

type MessageType = "system" | "user_message" | "agent_message" | "tool_call" | "tool_result" | "task_progress" | "clipboard_display" | "confirm_request" | "ask_request" | "error";

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

interface TaskProgress {
  task_id: string;
  label: string;
  current: number;
  total: number;
  percent: number;
  status: string;
}

interface ClipboardDisplay {
  display_id: string;
  label: string;
  content: string;
}

interface ChatMessage {
  role: "user" | "agent" | "system" | "error" | "tool";
  content: string;
  id: string;
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  imageMarkdown?: string;
  downloadInfo?: DownloadInfo;
  audioUrl?: string;
  audioAutoplay?: boolean;
  reasoningContent?: string;
}

interface SessionInfo {
  id: string;
  created_at: number;
  status: string;
  title?: string;
  pinned?: boolean;
  last_activity_at?: number;
  parents?: string[];
  parent?: string | null;
  continuation?: string | null;
}

function formatTime(ts: number): string {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  return `${Math.floor(diff / 86400)}天前`;
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
  const menuRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const instantScrollRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [handsfreeMode, setHandsfreeMode] = useState(false);
  const [taskProgress, setTaskProgress] = useState<Record<string, TaskProgress>>({});
  const [clipboardDisplays, setClipboardDisplays] = useState<Record<string, ClipboardDisplay>>({});
  const [llmMaxContextTokens, setLlmMaxContextTokens] = useState(0);
  const [approvalModelName, setApprovalModelName] = useState("");
  const [approvalModelAvailable, setApprovalModelAvailable] = useState(false);
  const [mergeMode, setMergeMode] = useState(false);
  const [selectedForMerge, setSelectedForMerge] = useState<Set<string>>(new Set());

  const messageList = useMemo(() =>
    messages.map((m) => (
      <MessageItem key={m.id} message={m} onImageClick={setLightboxSrc} />
    )),
    [messages]
  );

  const sidebarSessions = useMemo(() => {
    const q = searchQuery.toLowerCase();
    const filtered = q
      ? sessions.filter((s) => (s.title || s.id).toLowerCase().includes(q))
      : sessions;
    const current = sessions.find((s) => s.id === sessionId);
    const parentIds = new Set(current?.parents || []);
    return filtered.sort((a, b) => {
      const scoreA = (a.pinned ? 2 : 0) + (parentIds.has(a.id) ? 1 : 0);
      const scoreB = (b.pinned ? 2 : 0) + (parentIds.has(b.id) ? 1 : 0);
      if (scoreB !== scoreA) return scoreB - scoreA;
      return (b.last_activity_at || b.created_at) - (a.last_activity_at || a.created_at);
    });
  }, [sessions, searchQuery, sessionId]);

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

  const addMessage = useCallback((role: ChatMessage["role"], content: string, imageMarkdown?: string, downloadInfo?: DownloadInfo, audioUrl?: string, audioAutoplay?: boolean) => {
    const id = crypto.randomUUID();
    setMessages((prev) => [...prev, { role, content, id, imageMarkdown, downloadInfo, audioUrl, audioAutoplay }]);
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
      instantScrollRef.current = true;
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
              // Parse tool message content to restore downloadInfo, imageMarkdown and audioUrl
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
                  if (parsed.audio_url) {
                    entry.audioUrl = parsed.audio_url;
                    entry.audioAutoplay = parsed.autoplay === true;
                  }
                  // Use the readable message instead of raw JSON
                  if (parsed.message && typeof parsed.message === "string") {
                    entry.content = parsed.message;
                  }
                } catch {
                  // not JSON — leave as plain text
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
        let audioUrl: string | undefined;
        let audioAutoplay = false;
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
          } else if (parsed.message) {
            text += parsed.message.slice(0, 200);
          } else {
            text += raw.slice(0, 2000);
          }
        } catch {
          text += raw.slice(0, 2000);
        }
        addMessage("tool", text, imageMarkdown, downloadInfo, audioUrl, audioAutoplay);
      }
      else if (msg.type === "task_progress") {
        const raw = msg.result ?? "";
        try {
          const data = JSON.parse(raw);
          if (data.cleared) {
            // clear_task_progress — 移除指定或全部进度条
            setTaskProgress((prev) => {
              const next = { ...prev };
              if (Array.isArray(data.cleared) && data.cleared.length) {
                for (const tid of data.cleared) delete next[tid];
              } else {
                // 无明确 task_id 时全部清除
                return {};
              }
              return next;
            });
          } else if (data.task_id) {
            // set_task_progress — 更新或创建
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
        } catch {
          // ignore malformed progress payload
        }
      }
      else if (msg.type === "clipboard_display") {
        const raw = msg.result ?? "";
        try {
          const data = JSON.parse(raw);
          if (data.cleared) {
            // clear_clipboard_display — 移除指定或全部展示区域
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
            // set_clipboard_display — 更新或创建
            setClipboardDisplays((prev) => ({
              ...prev,
              [data.display_id]: {
                display_id: data.display_id,
                label: data.label || data.display_id,
                content: data.content ?? "",
              },
            }));
          }
        } catch {
          // ignore malformed clipboard display payload
        }
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
    if (messages.length === 0) return;
    const behavior = instantScrollRef.current ? "auto" : "smooth";
    instantScrollRef.current = false;
    bottomRef.current?.scrollIntoView({ behavior });
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
    const isArchived = sessions.find((s) => s.id === sessionId)?.status === "archived";
    if (!text || !wsRef.current || waiting || wsRef.current.readyState !== WebSocket.OPEN || isArchived) return;
    addMessage("user", text);
    wsRef.current.send(
      JSON.stringify({ type: "user_message", content: text })
    );
    setInput("");
    setWaiting(true);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    const isArchived = sessions.find((s) => s.id === sessionId)?.status === "archived";
    if (!files || files.length === 0 || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN || isArchived) return;

    setUploading(true);
    let completed = 0;

    Array.from(files).forEach((file) => {
      // 尝试获取本地路径（部分浏览器在 localhost 下暴露 file.path）
      const localPath = (file as any).path || (file as any).webkitRelativePath || "";

      // 如果有本地路径且和 uploads 在同一盘，后端会优先硬链接，不需要读 base64
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
          // 重置 input 以允许重复上传
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
  };

  const isLocal = window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost";

  const handleUploadClick = async () => {
    if (isLocal) {
      // 本机 → 后端打开原生 Windows 文件对话框，走硬链接
      try {
        const resp = await fetch("/api/file-picker", { method: "POST" });
        const data = await resp.json();
        if (data.uploaded && data.files) {
          for (const f of data.files) {
            addMessage("system", `📎 ${f.method === "hardlink" ? "硬链接" : "复制"}: ${f.filename} (${(f.size / 1024).toFixed(1)}KB)`);
          }
        } else if (data.error) {
          addMessage("error", `文件选择失败: ${data.error}`);
          // fallback: 走浏览器上传
          if (isLocal) fileInputRef.current?.click();
        }
      } catch (err) {
        addMessage("error", `文件选择异常: ${err}`);
        fileInputRef.current?.click();
      }
    } else {
      // 远程 → 浏览器 file input + base64
      fileInputRef.current?.click();
    }
  };

  const newChat = () => {
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
    setClipboardDisplays({});
    setTaskProgress({});
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

  // ── archive ──
  const archiveSession = (sid: string) => {
    setContextMenu(null);
    fetch(`/api/sessions/${sid}/archive`, { method: "POST" })
      .then(() => {
        fetchSessions();
        if (sid === sessionId) {
          newChat();
        }
      })
      .catch(() => {});
  };

  // ── compress ──
  const compressSession = (sid: string) => {
    setContextMenu(null);
    fetch(`/api/sessions/${sid}/compress`, { method: "POST" })
      .then(() => {
        fetchSessions();
        if (sid === sessionId) {
          newChat();
        }
      })
      .catch(() => {});
  };

  // ── pin ──
  const togglePinSession = (sid: string) => {
    setContextMenu(null);
    fetch(`/api/sessions/${sid}/pin`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        setSessions((prev) =>
          prev.map((s) => (s.id === sid ? { ...s, pinned: data.pinned } : s))
        );
        fetchSessions();
      })
      .catch(() => {});
  };

  // ── merge / branch ──
  const mergeSessions = (sources: string[]) => {
    setContextMenu(null);
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
  };

  const branchSession = (sid: string) => mergeSessions([sid]);

  const toggleMergeSelect = (sid: string) => {
    setSelectedForMerge((prev) => {
      const next = new Set(prev);
      if (next.has(sid)) next.delete(sid);
      else next.add(sid);
      return next;
    });
  };

  // ── context menu ──
  const handleContextMenu = (e: React.MouseEvent, sid: string) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, sid });
  };

  // ── session list item (flat, no tree) ──
  function SessionListItem({ session: s }: { session: SessionInfo }) {
    const isArchived = s.status === "archived";
    const current = sessions.find((cs) => cs.id === sessionId);
    const isParentOfCurrent = current?.parents?.includes(s.id) ?? false;

    return (
      <div
        className={`session-item ${s.id === sessionId ? "active" : ""} ${isArchived ? "archived" : ""} ${isParentOfCurrent ? "parent-session" : ""}`}
        onClick={() => {
          if (mergeMode) toggleMergeSelect(s.id);
          else switchSession(s.id);
        }}
        onContextMenu={(e) => {
          if (!mergeMode) handleContextMenu(e, s.id);
        }}
      >
        <div className="session-item-content">
          <div className="session-item-row">
            {mergeMode && (
              <input
                type="checkbox"
                checked={selectedForMerge.has(s.id)}
                onChange={() => toggleMergeSelect(s.id)}
                onClick={(e) => e.stopPropagation()}
              />
            )}
            <div className="session-item-title">
              {isParentOfCurrent && <span className="parent-mark" />}
              {s.pinned && <span className="pin-badge">★</span>}
              {s.title || s.id.slice(0, 8) + "..."}
              {isArchived && <span className="archived-badge">已归档</span>}
            </div>
          </div>
          <div className="session-item-sub">
            <span className="session-item-id">{s.id}</span>
            <span className="session-item-time">{formatTime(s.last_activity_at || s.created_at)}</span>
          </div>
        </div>
      </div>
    );
  }

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
          <button
            className={`merge-mode-toggle ${mergeMode ? 'active' : ''}`}
            onClick={() => {
              setMergeMode(!mergeMode);
              setSelectedForMerge(new Set());
            }}
          >
            {mergeMode ? '退出多选' : '多选合并'}
          </button>
        </div>
        <div className="session-list">
          {sidebarSessions.length === 0 ? (
            <div className="session-empty">无匹配会话</div>
          ) : (
            sidebarSessions.map((s) => (
              <SessionListItem key={s.id} session={s} />
            ))
          )}
        </div>
        {mergeMode && selectedForMerge.size >= 2 && (
          <div className="merge-bar">
            <span>已选 {selectedForMerge.size} 个会话</span>
            <button onClick={() => { mergeSessions(Array.from(selectedForMerge)); setMergeMode(false); setSelectedForMerge(new Set()); }}>
              合并延续
            </button>
          </div>
        )}
      </aside>
      {contextMenu && (
        <div
          ref={menuRef}
          className="context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <div className="context-menu-item" onClick={() => autoTitleSession(contextMenu.sid)}>
            自动命名
          </div>
          <div className="context-menu-item" onClick={() => { setContextMenu(null); togglePinSession(contextMenu.sid); }}>
            {(() => { const s = sessions.find(s => s.id === contextMenu.sid); return s?.pinned ? "取消收藏" : "收藏"; })()}
          </div>
          {(() => { const s = sessions.find(s => s.id === contextMenu.sid); return s?.status === "archived" ? (
            <div className="context-menu-item" onClick={() => { setContextMenu(null); branchSession(contextMenu.sid); }}>
              继续此会话
            </div>
          ) : null; })()}
          <div className="context-menu-item" onClick={() => { setContextMenu(null); compressSession(contextMenu.sid); }}>
            压缩记忆
          </div>
          <div className="context-menu-item" onClick={() => { setContextMenu(null); archiveSession(contextMenu.sid); }}>
            归档
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
              <label className="handsfree-toggle" title={handsfreeMode ? "脱手模式已开启 — 工具调用由 AI 自动审批" : "脱手模式已关闭 — 工具调用需用户审批"}>
                <span className="handsfree-label">脱手</span>
                <input
                  type="checkbox"
                  checked={handsfreeMode}
                  onChange={(e) => {
                    const enabled = e.target.checked;
                    setHandsfreeMode(enabled);
                    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                      wsRef.current.send(JSON.stringify({
                        type: "handsfree_mode",
                        content: enabled ? "true" : "false",
                      }));
                    }
                  }}
                />
                <span className="handsfree-slider" />
              </label>
            )}
            {handsfreeMode && approvalModelName && (
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
            {(() => {
              const isArchived = sessions.find((s) => s.id === sessionId)?.status === "archived";
              return (
                <>
                  <button className="header-action-btn" onClick={() => archiveSession(sessionId)} title="归档当前会话" disabled={isArchived}>
                    归档
                  </button>
                  <button className="header-action-btn" onClick={() => compressSession(sessionId)} title="压缩记忆并归档" disabled={isArchived}>
                    压缩
                  </button>
                </>
              );
            })()}
          </div>
        )}
      </header>

      {/* ── 任务进度条面板（固定在 header 下方，不随消息滚动）── */}
      {Object.keys(taskProgress).length > 0 && (
        <div className="task-progress-panel">
          {Object.values(taskProgress).map((tp) => (
            <div key={tp.task_id} className="task-progress-item">
              <div className="task-progress-header">
                <span className="task-progress-label">{tp.label}</span>
                <span className="task-progress-status">{tp.status}</span>
                <span className="task-progress-percent">{tp.percent}%</span>
              </div>
              <div className="task-progress-bar-bg">
                <div
                  className="task-progress-bar-fill"
                  style={{ width: `${tp.percent}%` }}
                />
              </div>
              <div className="task-progress-detail">
                {tp.current} / {tp.total}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── 剪贴板展示面板（固定在 header 下方，不随消息滚动）── */}
      {Object.keys(clipboardDisplays).length > 0 && (
        <div className="clipboard-display-panel">
          {Object.values(clipboardDisplays).map((cd) => (
            <div key={cd.display_id} className="clipboard-display-item">
              <div className="clipboard-display-header">
                <span className="clipboard-display-label">{cd.label}</span>
                <button
                  className="clipboard-display-copy"
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(cd.content);
                    } catch {
                      // ignore
                    }
                  }}
                >
                  复制
                </button>
              </div>
              <pre className="clipboard-display-content">{cd.content}</pre>
            </div>
          ))}
        </div>
      )}

      <main className="chat-area">
        {messageList}

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

      {(() => {
        const isArchived = sessions.find((s) => s.id === sessionId)?.status === "archived";
        return (
          <footer className="input-bar">
            {isArchived ? (
              <div className="archived-notice">此会话已归档，无法发送消息</div>
            ) : (
              <div className="input-bar-inner">
                  <div className="input-bar-row">
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
                  multiple
                  disabled={uploading}
                />
                <button
                  className="upload-btn"
                  onClick={handleUploadClick}
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
                  </div>
              </div>
            )}
          </footer>
        );
      })()}
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