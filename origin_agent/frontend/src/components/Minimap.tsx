import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import type { ChatMessage } from "../types";
import { DIMENSIONS } from "../constants/dimensions";
import { useChatRuntimeStore } from "../features/chat/chatRuntimeStore";
import {
  MINIMAP_THUMB_MIN_HIT_PX,
} from "../constants/history";
import {
  buildHeightWeightedSegments,
  minimapDragTarget,
  minimapHitGeometry,
  minimapViewportGeometry,
} from "../features/chat/minimapGeometry";

interface LogicalMinimapProps {
  onDragStart: () => void;
  onPreviewScrollTop: (scrollTop: number) => void;
  onDragEnd: (scrollTop: number) => void | Promise<void>;
  messages?: never;
  chatAreaRef?: never;
}

interface LegacyMinimapProps {
  messages: ChatMessage[];
  chatAreaRef: RefObject<HTMLDivElement | null>;
  onDragStart?: never;
  onPreviewScrollTop?: never;
  onDragEnd?: never;
}

type MinimapProps = LogicalMinimapProps | LegacyMinimapProps;

interface LegacyBlock {
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

export function minimapIndexFromRatio(ratio: number, rowCount: number): number {
  if (rowCount <= 0) return 0;
  const normalized = Math.max(0, Math.min(1, ratio));
  return Math.min(rowCount - 1, Math.floor(normalized * rowCount));
}

export function minimapRoleBuckets(roles: string[], bucketCount: number): string[] {
  if (!roles.length || bucketCount <= 0) return [];
  return Array.from({ length: bucketCount }, (_, bucket) => {
    const start = Math.floor((bucket / bucketCount) * roles.length);
    const end = Math.max(start + 1, Math.floor(((bucket + 1) / bucketCount) * roles.length));
    const counts: Record<string, number> = {};
    for (let index = start; index < Math.min(end, roles.length); index += 1) {
      counts[roles[index]] = (counts[roles[index]] || 0) + 1;
    }
    return Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || "system";
  });
}

function LogicalMinimap({ onDragStart, onPreviewScrollTop, onDragEnd }: LogicalMinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<number | null>(null);
  const draggingRef = useRef(false);
  const pointerIdRef = useRef<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const grabOffsetRef = useRef(0);
  const targetScrollTopRef = useRef(0);
  const [height, setHeight] = useState(0);
  const sessionGeneration = useChatRuntimeStore((state) => state.generation);
  const skeleton = useChatRuntimeStore((state) => state.skeleton);
  const liveRows = useChatRuntimeStore((state) => state.liveRows);
  const rowHeights = useChatRuntimeStore((state) => state.rowHeights);
  const scrollMetrics = useChatRuntimeStore((state) => state.scrollMetrics);
  // 流式增量只改变正文；未改变行 ID/Role 时无需重算整份历史权重。
  const liveOutlineKey = liveRows.map((row) => `${row.id}:${row.message.role}`).join("|");
  const segments = useMemo(
    () => buildHeightWeightedSegments(skeleton, liveRows, rowHeights),
    // liveRows 的完整对象只在行身份或角色变化时影响权重，其余由 rowHeights 更新。
    [skeleton, rowHeights, liveOutlineKey],
  );
  const hasLogicalRows = segments.length > 0;
  const viewport = minimapViewportGeometry(scrollMetrics, height);
  const hitGeometry = minimapHitGeometry(viewport, height, MINIMAP_THUMB_MIN_HIT_PX);

  useEffect(() => {
    draggingRef.current = false;
    setDragging(false);
    if (frameRef.current !== null) {
      cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
    const root = rootRef.current;
    const pointerId = pointerIdRef.current;
    if (root && pointerId !== null && root.hasPointerCapture(pointerId)) {
      root.releasePointerCapture(pointerId);
    }
    pointerIdRef.current = null;
  }, [sessionGeneration]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const update = () => setHeight(root.clientHeight);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(root);
    return () => observer.disconnect();
  }, [hasLogicalRows]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || height <= 0 || segments.length === 0) return;
    const width = canvas.clientWidth;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(width * dpr));
    canvas.height = Math.max(1, Math.round(height * dpr));
    const context = canvas.getContext("2d");
    if (!context) return;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, width, height);
    context.globalAlpha = 0.55;
    const buckets = Math.max(1, Math.floor(height));
    let segmentIndex = 0;
    for (let bucket = 0; bucket < buckets; bucket += 1) {
      const ratio = (bucket + 0.5) / buckets;
      while (
        segmentIndex < segments.length - 1
        && segments[segmentIndex].endRatio < ratio
      ) segmentIndex += 1;
      const role = segments[segmentIndex]?.role || "system";
      context.fillStyle = ROLE_COLORS[role] || ROLE_COLORS.system;
      context.fillRect(6, bucket, Math.max(1, width - 12), 1);
    }
  }, [height, segments]);

  const targetFromPointer = useCallback((clientY: number): number => {
    const root = rootRef.current;
    if (!root || height <= 0 || scrollMetrics.scrollHeight <= 0) return 0;
    return minimapDragTarget(
      clientY,
      root.getBoundingClientRect().top,
      height,
      viewport,
      grabOffsetRef.current,
      scrollMetrics,
    ).scrollTop;
  }, [height, scrollMetrics, viewport]);

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    const root = rootRef.current;
    if (
      !root || !hasLogicalRows || height <= 0
      || !Number.isFinite(scrollMetrics.scrollHeight)
      || !Number.isFinite(scrollMetrics.viewportHeight)
      || scrollMetrics.viewportHeight <= 0
      || scrollMetrics.scrollHeight < scrollMetrics.viewportHeight
    ) return;
    event.preventDefault();
    const pointerY = event.clientY - root.getBoundingClientRect().top;
    const insideHit = pointerY >= hitGeometry.top
      && pointerY <= hitGeometry.top + hitGeometry.height;
    grabOffsetRef.current = insideHit
      ? viewport.height < hitGeometry.height
        ? viewport.height / 2
        : pointerY - viewport.top
      : viewport.height / 2;
    draggingRef.current = true;
    setDragging(true);
    pointerIdRef.current = event.pointerId;
    event.currentTarget.setPointerCapture(event.pointerId);
    onDragStart();
    const target = targetFromPointer(event.clientY);
    targetScrollTopRef.current = target;
    onPreviewScrollTop(target);
  };
  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current || pointerIdRef.current !== event.pointerId) return;
    const target = targetFromPointer(event.clientY);
    targetScrollTopRef.current = target;
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = null;
      onPreviewScrollTop(target);
    });
  };
  const finishDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current || pointerIdRef.current !== event.pointerId) return;
    draggingRef.current = false;
    pointerIdRef.current = null;
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    frameRef.current = null;
    const target = targetFromPointer(event.clientY);
    targetScrollTopRef.current = target;
    void onDragEnd(targetScrollTopRef.current);
  };

  if (!hasLogicalRows) return null;
  return (
    <div ref={rootRef} className={`minimap${dragging ? " minimap-dragging" : ""}`} onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={finishDrag} onPointerCancel={finishDrag}>
      <canvas ref={canvasRef} className="minimap-canvas" />
      <div className="minimap-dim-top" style={{ height: viewport.top }} />
      <div className="minimap-dim-bottom" style={{ top: viewport.top + viewport.height }} />
      <div className="minimap-viewport" style={{ top: viewport.top, height: viewport.height }} />
    </div>
  );
}

function LegacyMinimap({ messages, chatAreaRef }: LegacyMinimapProps) {
  const [blocks, setBlocks] = useState<LegacyBlock[]>([]);
  const [viewport, setViewport] = useState({ top: 0, height: 0 });
  const [height, setHeight] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<number | null>(null);
  const draggingRef = useRef(false);

  const measure = useCallback(() => {
    const chat = chatAreaRef.current;
    if (!chat) return;
    const scrollHeight = Math.max(1, chat.scrollHeight);
    const clientHeight = chat.clientHeight;
    setHeight(clientHeight);
    setBlocks(Array.from(chat.querySelectorAll<HTMLElement>(".message")).map((element) => {
      const role = element.classList.contains("message-user") ? "user"
        : element.classList.contains("message-assistant") ? "assistant"
          : element.classList.contains("message-tool") ? "tool"
            : element.classList.contains("message-error") ? "error" : "system";
      return {
        id: element.dataset.messageId || String(element.offsetTop),
        top: element.offsetTop / scrollHeight * clientHeight,
        height: Math.max(2, element.offsetHeight / scrollHeight * clientHeight),
        color: ROLE_COLORS[role],
      };
    }));
    setViewport({
      top: chat.scrollTop / scrollHeight * clientHeight,
      height: Math.max(clientHeight * clientHeight / scrollHeight, DIMENSIONS.MINIMAP_MIN_HEIGHT),
    });
  }, [chatAreaRef]);

  useEffect(() => {
    const chat = chatAreaRef.current;
    if (!chat) return;
    const schedule = () => {
      if (frameRef.current !== null) return;
      frameRef.current = requestAnimationFrame(() => { frameRef.current = null; measure(); });
    };
    schedule();
    chat.addEventListener("scroll", schedule, { passive: true });
    const observer = new ResizeObserver(schedule);
    observer.observe(chat);
    const content = chat.querySelector<HTMLElement>(".chat-content");
    if (content) observer.observe(content);
    return () => {
      chat.removeEventListener("scroll", schedule);
      observer.disconnect();
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, [chatAreaRef, measure, messages]);

  if (!messages.length) return null;
  const jump = (clientY: number) => {
    const root = rootRef.current;
    const chat = chatAreaRef.current;
    if (!root || !chat || height <= 0) return;
    const ratio = Math.max(0, Math.min(1, (clientY - root.getBoundingClientRect().top) / height));
    chat.scrollTop = ratio * chat.scrollHeight;
  };
  return (
    <div
      ref={rootRef}
      className="minimap"
      onPointerDown={(event) => {
        draggingRef.current = true;
        event.currentTarget.setPointerCapture(event.pointerId);
        jump(event.clientY);
      }}
      onPointerMove={(event) => { if (draggingRef.current) jump(event.clientY); }}
      onPointerUp={() => { draggingRef.current = false; }}
      onPointerCancel={() => { draggingRef.current = false; }}
    >
      <div className="minimap-track">
        {blocks.map((block) => <div key={block.id} className="minimap-block" style={{ top: block.top, height: block.height, backgroundColor: block.color }} />)}
      </div>
      <div className="minimap-dim-top" style={{ height: viewport.top }} />
      <div className="minimap-dim-bottom" style={{ top: viewport.top + viewport.height }} />
      <div className="minimap-viewport" style={{ top: viewport.top, height: viewport.height }} />
    </div>
  );
}

function isLegacyMinimapProps(props: MinimapProps): props is LegacyMinimapProps {
  return Array.isArray(props.messages);
}

export default function Minimap(props: MinimapProps) {
  if (isLegacyMinimapProps(props)) {
    return (
      <LegacyMinimap
        messages={props.messages}
        chatAreaRef={props.chatAreaRef}
      />
    );
  }
  return (
    <LogicalMinimap
      onDragStart={props.onDragStart}
      onPreviewScrollTop={props.onPreviewScrollTop}
      onDragEnd={props.onDragEnd}
    />
  );
}
