import { useEffect, useRef, useState, useCallback } from "react";
import { ChatMessage } from "../types";

interface MinimapProps {
  messages: ChatMessage[];
  chatAreaRef: React.RefObject<HTMLDivElement | null>;
}

interface MinimapBlock {
  id: string;
  top: number;
  height: number;
  color: string;
}

const ROLE_COLORS: Record<string, string> = {
  user: "#2563a3",
  assistant: "#15803d",
  system: "#4a4a4a",
  error: "#b91c1c",
  tool: "#b45309",
};

export default function Minimap({ messages, chatAreaRef }: MinimapProps) {
  const [blocks, setBlocks] = useState<MinimapBlock[]>([]);
  const [viewport, setViewport] = useState({ top: 0, height: 0 });
  const [minimapHeight, setMinimapHeight] = useState(0);
  const minimapRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  const refresh = useCallback(() => {
    const chat = chatAreaRef.current;
    if (!chat) return;

    const msgEls = chat.querySelectorAll<HTMLElement>(".message");
    if (msgEls.length === 0) {
      setBlocks([]);
      setViewport({ top: 0, height: 0 });
      return;
    }

    const scrollHeight = chat.scrollHeight;
    const clientHeight = chat.clientHeight;
    const scale = clientHeight / scrollHeight;

    const newBlocks: MinimapBlock[] = [];
    msgEls.forEach((el) => {
      const id = el.getAttribute("data-message-id");
      if (!id) return;
      const top = (el.offsetTop / scrollHeight) * clientHeight;
      const height = Math.max((el.offsetHeight / scrollHeight) * clientHeight, 2);
      const role = el.classList.contains("message-user")
        ? "user"
        : el.classList.contains("message-assistant")
          ? "assistant"
          : el.classList.contains("message-error")
            ? "error"
            : el.classList.contains("message-tool")
              ? "tool"
              : "system";
      newBlocks.push({
        id,
        top,
        height,
        color: ROLE_COLORS[role] || ROLE_COLORS.system,
      });
    });

    setBlocks(newBlocks);
    setMinimapHeight(clientHeight);
    setViewport({
      top: (chat.scrollTop / scrollHeight) * clientHeight,
      height: Math.max(clientHeight * scale, 24),
    });
  }, [chatAreaRef]);

  useEffect(() => {
    const chat = chatAreaRef.current;
    if (!chat) return;

    refresh();

    chat.addEventListener("scroll", refresh, { passive: true });
    const ro = new ResizeObserver(refresh);
    ro.observe(chat);

    return () => {
      chat.removeEventListener("scroll", refresh);
      ro.disconnect();
    };
  }, [chatAreaRef, refresh]);

  useEffect(() => {
    refresh();
  }, [messages, refresh]);

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const chat = chatAreaRef.current;
    const minimap = minimapRef.current;
    if (!chat || !minimap || minimapHeight === 0) return;
    e.preventDefault();
    draggingRef.current = true;

    const rect = minimap.getBoundingClientRect();
    const clickY = e.clientY - rect.top;
    const ratio = Math.max(0, Math.min(1, clickY / minimapHeight));
    chat.scrollTop = ratio * chat.scrollHeight;

    const handleMove = (ev: PointerEvent) => {
      if (!draggingRef.current) return;
      const moveRect = minimap.getBoundingClientRect();
      const moveY = ev.clientY - moveRect.top;
      const moveRatio = Math.max(0, Math.min(1, moveY / minimapHeight));
      chat.scrollTop = moveRatio * chat.scrollHeight;
    };

    const handleUp = () => {
      draggingRef.current = false;
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
  };

  if (messages.length === 0) return null;

  return (
    <div ref={minimapRef} className="minimap" onPointerDown={handlePointerDown}>
      <div className="minimap-track">
        {blocks.map((b) => (
          <div
            key={b.id}
            className="minimap-block"
            style={{
              top: b.top,
              height: b.height,
              backgroundColor: b.color,
            }}
          />
        ))}
      </div>
      <div className="minimap-dim-top" style={{ height: viewport.top }} />
      <div
        className="minimap-dim-bottom"
        style={{ top: viewport.top + viewport.height }}
      />
      <div
        className="minimap-viewport"
        style={{
          top: viewport.top,
          height: viewport.height,
        }}
      />
    </div>
  );
}