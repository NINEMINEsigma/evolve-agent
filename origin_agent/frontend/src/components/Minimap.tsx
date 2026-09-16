import { useEffect, useRef, useState, useCallback } from "react";
import { ChatMessage } from "../types";
import { DIMENSIONS } from "../constants/dimensions";

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

const GEOMETRY_EPSILON = 0.1;

function blocksEqual(previous: MinimapBlock[], next: MinimapBlock[]): boolean {
  if (previous.length !== next.length) return false;
  return previous.every((block, index) => {
    const candidate = next[index];
    return block.id === candidate.id
      && block.color === candidate.color
      && Math.abs(block.top - candidate.top) < GEOMETRY_EPSILON
      && Math.abs(block.height - candidate.height) < GEOMETRY_EPSILON;
  });
}

function viewportEqual(
  previous: { top: number; height: number },
  next: { top: number; height: number },
): boolean {
  return Math.abs(previous.top - next.top) < GEOMETRY_EPSILON
    && Math.abs(previous.height - next.height) < GEOMETRY_EPSILON;
}

export default function Minimap({ messages, chatAreaRef }: MinimapProps) {
  const [blocks, setBlocks] = useState<MinimapBlock[]>([]);
  const [viewport, setViewport] = useState({ top: 0, height: 0 });
  const [minimapHeight, setMinimapHeight] = useState(0);
  const minimapRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);
  const blocksRef = useRef<MinimapBlock[]>([]);
  const viewportRef = useRef({ top: 0, height: 0 });
  const minimapHeightRef = useRef(0);
  const layoutFrameRef = useRef<number | null>(null);
  const viewportFrameRef = useRef<number | null>(null);

  const refreshViewport = useCallback(() => {
    const chat = chatAreaRef.current;
    if (!chat) return;

    const scrollHeight = chat.scrollHeight;
    const clientHeight = chat.clientHeight;
    const scale = scrollHeight > 0 ? clientHeight / scrollHeight : 0;
    const nextViewport = scrollHeight > 0
      ? {
          top: (chat.scrollTop / scrollHeight) * clientHeight,
          height: Math.max(clientHeight * scale, DIMENSIONS.MINIMAP_MIN_HEIGHT),
        }
      : { top: 0, height: 0 };

    if (minimapHeightRef.current !== clientHeight) {
      minimapHeightRef.current = clientHeight;
      setMinimapHeight(clientHeight);
    }
    if (!viewportEqual(viewportRef.current, nextViewport)) {
      viewportRef.current = nextViewport;
      setViewport(nextViewport);
    }
  }, [chatAreaRef]);

  const measureLayout = useCallback(() => {
    const chat = chatAreaRef.current;
    if (!chat) return;

    const msgEls = chat.querySelectorAll<HTMLElement>(".message");
    const scrollHeight = chat.scrollHeight;
    const clientHeight = chat.clientHeight;
    const nextBlocks: MinimapBlock[] = [];

    if (scrollHeight > 0) {
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
        nextBlocks.push({
          id,
          top,
          height,
          color: ROLE_COLORS[role] || ROLE_COLORS.system,
        });
      });
    }

    if (!blocksEqual(blocksRef.current, nextBlocks)) {
      blocksRef.current = nextBlocks;
      setBlocks(nextBlocks);
    }
    refreshViewport();
  }, [chatAreaRef, refreshViewport]);

  const scheduleViewportRefresh = useCallback(() => {
    if (viewportFrameRef.current !== null) return;
    viewportFrameRef.current = requestAnimationFrame(() => {
      viewportFrameRef.current = null;
      refreshViewport();
    });
  }, [refreshViewport]);

  const scheduleLayoutMeasure = useCallback(() => {
    if (layoutFrameRef.current !== null) return;
    layoutFrameRef.current = requestAnimationFrame(() => {
      layoutFrameRef.current = null;
      measureLayout();
    });
  }, [measureLayout]);

  useEffect(() => {
    const chat = chatAreaRef.current;
    if (!chat) return;

    scheduleLayoutMeasure();
    chat.addEventListener("scroll", scheduleViewportRefresh, { passive: true });

    let resizeObserver: ResizeObserver | null = null;
    let resizeFallback: (() => void) | null = null;
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(scheduleLayoutMeasure);
      resizeObserver.observe(chat);
      const content = chat.querySelector<HTMLElement>(".chat-content");
      if (content) resizeObserver.observe(content);
    } else {
      resizeFallback = scheduleLayoutMeasure;
      window.addEventListener("resize", resizeFallback);
    }

    return () => {
      chat.removeEventListener("scroll", scheduleViewportRefresh);
      resizeObserver?.disconnect();
      if (resizeFallback) window.removeEventListener("resize", resizeFallback);
      if (layoutFrameRef.current !== null) {
        cancelAnimationFrame(layoutFrameRef.current);
        layoutFrameRef.current = null;
      }
      if (viewportFrameRef.current !== null) {
        cancelAnimationFrame(viewportFrameRef.current);
        viewportFrameRef.current = null;
      }
    };
  }, [chatAreaRef, scheduleLayoutMeasure, scheduleViewportRefresh]);

  useEffect(() => {
    scheduleLayoutMeasure();
  }, [messages, scheduleLayoutMeasure]);

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