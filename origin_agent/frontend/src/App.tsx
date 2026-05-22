import { useEffect, useRef, useState, useCallback } from "react";

type MessageType = "system" | "agent_message" | "error";

interface Message {
  type: MessageType;
  session_id?: string;
  content?: string;
  message?: string;
}

export default function App() {
  const [lines, setLines] = useState<{ cls: string; text: string }[]>([]);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState("connecting...");
  const wsRef = useRef<WebSocket | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  const addLine = useCallback((cls: string, text: string) => {
    setLines((prev) => [...prev, { cls, text }]);
  }, []);

  useEffect(() => {
    const ws = new WebSocket(`ws://${location.host}/ws/chat`);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("已连接");
      addLine("sys", "已连接到 Evolve Agent");
    };
    ws.onclose = () => {
      setStatus("已断开");
      addLine("sys", "连接已断开");
    };
    ws.onmessage = (e) => {
      const msg: Message = JSON.parse(e.data);
      if (msg.type === "system") addLine("sys", msg.content ?? "");
      else if (msg.type === "agent_message") addLine("agent", msg.content ?? "");
      else if (msg.type === "error") addLine("err", msg.message ?? "");
    };

    return () => ws.close();
  }, [addLine]);

  useEffect(() => {
    logRef.current?.scrollTo(0, logRef.current.scrollHeight);
  }, [lines]);

  const send = () => {
    const text = input.trim();
    if (!text || !wsRef.current) return;
    addLine("user", text);
    wsRef.current.send(JSON.stringify({ type: "user_message", content: text }));
    setInput("");
  };

  return (
    <div style={{ maxWidth: 640, margin: "40px auto", padding: "0 16px", fontFamily: "system-ui, sans-serif" }}>
      <h2>Evolve Agent Chat</h2>
      <div style={{ fontSize: 12, color: "#888", marginBottom: 8 }}>{status}</div>
      <div
        ref={logRef}
        style={{
          height: 360, overflowY: "auto", border: "1px solid #ccc",
          padding: 12, marginBottom: 12, background: "#fafafa", fontSize: 14,
        }}
      >
        {lines.map((l, i) => (
          <div key={i} className={`line-${l.cls}`}>{l.text}</div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="输入消息..."
          style={{ flex: 1, padding: 8, fontSize: 14 }}
          autoFocus
        />
        <button onClick={send} style={{ padding: "8px 16px", cursor: "pointer" }}>发送</button>
      </div>
    </div>
  );
}