import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../types";
import {
  messageLength,
  seedFromString,
  strokeContours,
  type MessageInfluence,
  type TerrainParams,
} from "../utils/terrain";

interface ContourBackgroundProps {
  scrollRef: React.RefObject<HTMLElement>;
  contentRef: React.RefObject<HTMLDivElement>;
  messages: ChatMessage[];
  seedKey?: string;
}

/* ── 渲染常量 ── */
// 单个 canvas 块的文档高度（px）
const TILE_HEIGHT = 2048;
// 等值线采样网格边长（px）
const CELL = 6;
// 等值层级数量与主线间隔
const LEVELS = 14;
const MAJOR_EVERY = 5;
// 重测/重绘防抖（ms）
const DEBOUNCE = 150;
// 消息长度归一化基准（字符数）
const NORM_LEN = 2000;
// 副线/主线/泛光透明度
const MINOR_ALPHA = 0.16;
const MAJOR_ALPHA = 0.34;
const GLOW_ALPHA = 0.07;
// 无 seedKey 时的固定种子
const FALLBACK_SEED = 0x9e3779b9;
// --accent 解析失败时的回退色
const FALLBACK_RGB = "167, 139, 250";

export default function ContourBackground({ scrollRef, contentRef, messages, seedKey }: ContourBackgroundProps) {
  const [isMobile, setIsMobile] = useState(false);
  const [layout, setLayout] = useState({ scrollHeight: 0, tileCount: 0 });
  const [ready, setReady] = useState(false);
  const canvasMap = useRef(new Map<number, HTMLCanvasElement>());
  const influencesRef = useRef<MessageInfluence[]>([]);
  const versionRef = useRef(0);
  const readyRef = useRef(false);
  const renderedVersion = useRef(new Map<number, number>());
  const visibleTiles = useRef(new Set<number>());
  const debounceTimer = useRef<number | null>(null);
  const seed = seedKey ? seedFromString(seedKey) : FALLBACK_SEED;

  // 会话切换 → 重新隐藏，待新一轮异步渲染完成后淡入
  useEffect(() => {
    readyRef.current = false;
    setReady(false);
  }, [seedKey]);

  // 移动端隐藏背景
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    const onChange = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    setIsMobile(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // 测量每条消息的文档纵向条带，按内容长度换算隆起强度
  const measure = useCallback(() => {
    const main = scrollRef.current;
    const content = contentRef.current;
    if (!main || !content) return;
    const lenMap = new Map<string, number>();
    for (const m of messages) lenMap.set(m.id, messageLength(m));
    const mainRect = main.getBoundingClientRect();
    const scrollTop = main.scrollTop;
    const influences: MessageInfluence[] = [];
    content.querySelectorAll("[data-message-id]").forEach((el) => {
      const id = el.getAttribute("data-message-id");
      const len = id ? lenMap.get(id) : undefined;
      if (len == null) return;
      const rect = el.getBoundingClientRect();
      const y0 = rect.top - mainRect.top + scrollTop;
      influences.push({
        y0,
        y1: y0 + rect.height,
        strength: Math.min(1, Math.log(1 + len) / Math.log(1 + NORM_LEN)),
        // 横向位置由消息 id 哈希散布：隆起呈斑块而非全宽条带
        u: id ? seedFromString(id) / 4294967296 : 0.5,
      });
    });
    influencesRef.current = influences;
  }, [scrollRef, contentRef, messages]);

  // 绘制单个块：分片异步描等值线，被中止则保持过期标记等待重绘
  const renderTile = useCallback(async (index: number) => {
    const canvas = canvasMap.current.get(index);
    const main = scrollRef.current;
    if (!canvas || !main) return;
    const w = main.clientWidth;
    const y0 = index * TILE_HEIGHT;
    const h = Math.min(TILE_HEIGHT, Math.max(0, main.scrollHeight - y0));
    if (w <= 0 || h <= 0) return;
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let rgb = FALLBACK_RGB;
    const raw = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
    const hexMatch = raw.match(/^#([0-9a-f]{6})$/i);
    if (hexMatch) {
      const v = parseInt(hexMatch[1], 16);
      rgb = `${(v >> 16) & 255}, ${(v >> 8) & 255}, ${v & 255}`;
    }

    const params: TerrainParams = { seed, width: w, influences: influencesRef.current };
    const v = versionRef.current;
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.translate(0, -y0);
    await strokeContours(ctx, params, { x0: 0, y0, w, h }, {
      cell: CELL,
      levels: LEVELS,
      majorEvery: MAJOR_EVERY,
      minorStyle: `rgba(${rgb}, ${MINOR_ALPHA})`,
      majorStyle: `rgba(${rgb}, ${MAJOR_ALPHA})`,
      glowStyle: `rgba(${rgb}, ${GLOW_ALPHA})`,
    }, () => versionRef.current !== v);
    ctx.restore();

    // 渲染期间数据已过期：不登记版本，等待下轮防抖重绘
    if (versionRef.current !== v) return;
    renderedVersion.current.set(index, v);

    // 所有可见块首帧齐备 → 容器淡入（一次性，此后增量重绘不再重复）
    if (!readyRef.current && visibleTiles.current.size > 0) {
      let allDone = true;
      visibleTiles.current.forEach((i) => {
        if (renderedVersion.current.get(i) !== versionRef.current) allDone = false;
      });
      if (allDone) {
        readyRef.current = true;
        setReady(true);
      }
    }
  }, [scrollRef, seed]);

  // 让所有可见且过期的块重绘
  const renderVisibleStale = useCallback(() => {
    visibleTiles.current.forEach((index) => {
      if (renderedVersion.current.get(index) !== versionRef.current) renderTile(index);
    });
  }, [renderTile]);

  // 防抖重测：消息或尺寸变化后统一刷新
  const scheduleRefresh = useCallback(() => {
    if (debounceTimer.current != null) window.clearTimeout(debounceTimer.current);
    debounceTimer.current = window.setTimeout(() => {
      debounceTimer.current = null;
      measure();
      versionRef.current += 1;
      const main = scrollRef.current;
      const scrollHeight = main ? main.scrollHeight : 0;
      const tileCount = Math.ceil(scrollHeight / TILE_HEIGHT);
      setLayout((prev) =>
        prev.scrollHeight === scrollHeight && prev.tileCount === tileCount
          ? prev
          : { scrollHeight, tileCount }
      );
      renderVisibleStale();
    }, DEBOUNCE);
  }, [measure, scrollRef, renderVisibleStale]);

  // 消息变化 → 防抖重测
  useEffect(() => {
    scheduleRefresh();
    return () => {
      if (debounceTimer.current != null) window.clearTimeout(debounceTimer.current);
    };
  }, [scheduleRefresh]);

  // 尺寸变化（窗口 resize / 内容异步撑高）→ 防抖重测
  useEffect(() => {
    const main = scrollRef.current;
    const content = contentRef.current;
    if (!main || !content) return;
    const ro = new ResizeObserver(() => scheduleRefresh());
    ro.observe(main);
    ro.observe(content);
    return () => ro.disconnect();
  }, [scrollRef, contentRef, scheduleRefresh]);

  // 视口附近的块懒渲染
  useEffect(() => {
    const main = scrollRef.current;
    if (!main) return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const index = Number((entry.target as HTMLElement).dataset.tileIndex);
          if (Number.isNaN(index)) continue;
          if (entry.isIntersecting) {
            visibleTiles.current.add(index);
            if (renderedVersion.current.get(index) !== versionRef.current) renderTile(index);
          } else {
            visibleTiles.current.delete(index);
          }
        }
      },
      { root: main, rootMargin: "50% 0px" }
    );
    canvasMap.current.forEach((canvas) => io.observe(canvas));
    return () => io.disconnect();
  }, [scrollRef, layout.tileCount, renderTile]);

  if (isMobile) return null;

  return (
    <div className={`contour-bg${ready ? " ready" : ""}`} aria-hidden="true">
      {Array.from({ length: layout.tileCount }, (_, i) => {
        const tileHeight = Math.min(TILE_HEIGHT, Math.max(0, layout.scrollHeight - i * TILE_HEIGHT));
        return (
          <canvas
            key={i}
            data-tile-index={i}
            className="contour-bg-tile"
            style={{ top: i * TILE_HEIGHT, height: tileHeight }}
            ref={(el) => {
              if (el) canvasMap.current.set(i, el);
              else canvasMap.current.delete(i);
            }}
          />
        );
      })}
    </div>
  );
}
