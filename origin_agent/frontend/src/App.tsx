import { useEffect, useRef, useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

type MessageType = "system" | "user_message" | "agent_message" | "tool_call" | "tool_result" | "confirm_request" | "error";

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
}

interface ConfirmRequest {
  request_id: string;
  content: string;
  command?: string[];
  reason?: string;
}

interface ChatMessage {
  role: "user" | "agent" | "system" | "error" | "tool";
  content: string;
  id: string;
  toolName?: string;
  toolArgs?: Record<string, unknown>;
}

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState("connecting...");
  const [waiting, setWaiting] = useState(false);
  const [pendingConfirm, setPendingConfirm] = useState<ConfirmRequest | null>(null);
  const [sessionId, setSessionId] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const addMessage = useCallback((role: ChatMessage["role"], content: string) => {
    const id = crypto.randomUUID();
    setMessages((prev) => [...prev, { role, content, id }]);
  }, []);

  // ── WebSocket with auto-reconnect ───────────────────────────────────
  const reconnectRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    const lastSid = localStorage.getItem("evolve_session_id") || "";
    const qs = lastSid ? `?resume=${lastSid}` : "";
    const ws = new WebSocket(`ws://${location.host}/ws/chat${qs}`);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectRef.current = 0;
      setStatus("已连接");
      addMessage("system", "已连接到 Evolve Agent");
    };

    ws.onclose = () => {
      setStatus("已断开");
      setWaiting(false);
      // Exponential backoff: 1s → 2s → 4s → ... max 30s
      const delay = Math.min(1000 * Math.pow(2, reconnectRef.current), 30000);
      reconnectRef.current += 1;
      setStatus(`重连中 (${(delay / 1000).toFixed(0)}s)...`);
      timerRef.current = setTimeout(connect, delay);
    };

    ws.onmessage = (e) => {
      const msg: WSMessage = JSON.parse(e.data);
      if (msg.type === "system") {
        addMessage("system", msg.content ?? "");
        if (msg.session_id) {
          setSessionId(msg.session_id);
          localStorage.setItem("evolve_session_id", msg.session_id);
        }
      }
      else if (msg.type === "agent_message") {
        setWaiting(false);
        addMessage("agent", msg.content ?? "");
      }
      else if (msg.type === "tool_call") {
        const argsStr = msg.args
          ? "(" + Object.entries(msg.args)
              .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
              .join(", ") + ")"
          : "";
        addMessage("tool", `⚡ ${msg.tool} ${argsStr}`);
      }
      else if (msg.type === "tool_result") {
        addMessage("tool", `✅ ${msg.tool} → ${(msg.result ?? "").slice(0, 100)}`);
      }
      else if (msg.type === "error") addMessage("error", msg.message ?? "");
      else if (msg.type === "confirm_request") {
        // Show confirmation dialog — only if there's a request_id
        if (msg.request_id) {
          setPendingConfirm({
            request_id: msg.request_id,
            content: msg.content ?? "运行命令?",
            command: (msg.args as Record<string, unknown>)?.command as string[] | undefined,
            reason: (msg.args as Record<string, unknown>)?.reason as string | undefined,
          });
        }
      }
    };
  }, [addMessage]);

  // ── confirm response ──
  const respondConfirm = useCallback((action: string) => {
    if (!pendingConfirm) return;
    const payload = { action };
    console.log("[confirm] HTTP POST", pendingConfirm.request_id, payload);
    fetch(`/api/confirm/${pendingConfirm.request_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch((err) => console.error("[confirm] fetch failed", err));
    setPendingConfirm(null);
  }, [pendingConfirm]);

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

  const send = () => {
    const text = input.trim();
    if (!text || !wsRef.current || waiting) return;
    addMessage("user", text);
    wsRef.current.send(
      JSON.stringify({ type: "user_message", content: text })
    );
    setInput("");
    setWaiting(true);
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
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
            <span className="session-badge" title="刷新页面后自动恢复此会话">
              {sessionId}
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
                <pre className="message-text message-text-tool">{m.content}</pre>
              ) : m.role === "agent" ? (
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
                  }}
                >
                  {m.content}
                </ReactMarkdown>
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
            <div className="confirm-title">💻 确认执行命令</div>
            <div className="confirm-body">
              <pre className="confirm-cmd">
                {pendingConfirm.command?.join(" ") ?? pendingConfirm.content}
              </pre>
              {pendingConfirm.reason && (
                <div className="confirm-reason">原因: {pendingConfirm.reason}</div>
              )}
            </div>
            <div className="confirm-actions">
              <button className="confirm-deny" onClick={() => respondConfirm("deny")}>
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

      <footer className="input-bar">
        <input
          className="input-field"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="输入消息..."
          autoFocus
          disabled={waiting}
        />
        <button className="send-btn" onClick={send} disabled={waiting || !input.trim()}>
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M22 2L11 13" /><path d="M22 2L15 22L11 13L2 9L22 2Z" />
          </svg>
        </button>
        {waiting && (
          <button
            className="interrupt-btn"
            onClick={() => {
              fetch(`/api/interrupt/${sessionId || "unknown"}`, { method: "POST" })
                .catch(() => {});
            }}
          >
            ⏹
          </button>
        )}
      </footer>
    </div>
  );
}