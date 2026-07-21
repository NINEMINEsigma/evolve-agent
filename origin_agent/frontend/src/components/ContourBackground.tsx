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
  // 缓存 .chat-area 的 padding，避免每次测量都调用 getComputedStyle
  const paddingRef = useRef({ top: 0, bottom: 0 });
  const seed = seedKey ? seedFromString(seedKey) : FALLBACK_SEED;
  // 三阶段状态机：idle → buffering（仅模糊） → computing（离屏渲染） → idle
  const phaseRef = useRef<'idle' | 'buffering' | 'computing'>('idle');
  const [buffering, setBuffering] = useState(false);

  // 会话切换 → 重新隐藏，待新一轮异步渲染完成后淡入
  useEffect(() => {
    readyRef.current = false;
    phaseRef.current = 'idle';
    setReady(false);
    setBuffering(false);
    if (debounceTimer.current != null) {
      window.clearTimeout(debounceTimer.current);
      debounceTimer.current = null;
    }
  }, [seedKey]);

  // 移动端隐藏背景
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    const onChange = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    setIsMobile(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // 初始化 padding 缓存，用于计算基于内容高度的有效 scrollHeight
  useEffect(() => {
    const main = scrollRef.current;
    if (!main) return;
    const style = getComputedStyle(main);
    paddingRef.current = {
      top: parseInt(style.paddingTop) || 0,
      bottom: parseInt(style.paddingBottom) || 0,
    };
  }, [scrollRef]);

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

  // 绘制单个块：离屏渲染完成后同步拷贝到可见 canvas，被中止则丢弃离屏内容
  const renderTile = useCallback(async (index: number) => {
    const canvas = canvasMap.current.get(index);
    const main = scrollRef.current;
    const content = contentRef.current;
    if (!canvas || !main) return;
    const w = main.clientWidth;
    const y0 = index * TILE_HEIGHT;
    // 用 .chat-content 的 scrollHeight 加 padding 替代 .chat-area 的 scrollHeight，
    // 避免 absolute positioned canvas 块撑大 scrollHeight 形成循环依赖
    const effectiveScrollHeight = content
      ? content.scrollHeight + paddingRef.current.top + paddingRef.current.bottom
      : main.scrollHeight;
    const h = Math.min(TILE_HEIGHT, Math.max(0, effectiveScrollHeight - y0));
    if (w <= 0 || h <= 0) {
      // 标记完成以避免该 tile 阻塞整体退出
      renderedVersion.current.set(index, versionRef.current);
      return;
    }

    let rgb = FALLBACK_RGB;
    const raw = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
    const hexMatch = raw.match(/^#([0-9a-f]{6})$/i);
    if (hexMatch) {
      const v = parseInt(hexMatch[1], 16);
      rgb = `${(v >> 16) & 255}, ${(v >> 8) & 255}, ${v & 255}`;
    }

    // 离屏 canvas：新内容先画到这里，完成后一次性拷贝到可见 canvas
    const offscreen = document.createElement('canvas');
    offscreen.width = w;
    offscreen.height = h;
    const offCtx = offscreen.getContext('2d');
    if (!offCtx) return;

    const params: TerrainParams = { seed, width: w, influences: influencesRef.current };
    const v = versionRef.current;
    offCtx.save();
    offCtx.translate(0, -y0);
    await strokeContours(offCtx, params, { x0: 0, y0, w, h }, {
      cell: CELL,
      levels: LEVELS,
      majorEvery: MAJOR_EVERY,
      minorStyle: `rgba(${rgb}, ${MINOR_ALPHA})`,
      majorStyle: `rgba(${rgb}, ${MAJOR_ALPHA})`,
      glowStyle: `rgba(${rgb}, ${GLOW_ALPHA})`,
    }, () => versionRef.current !== v);
    offCtx.restore();

    // 渲染被中止：丢弃离屏内容，不拷贝，不登记版本
    if (versionRef.current !== v) return;

    // 同步拷贝离屏 → 可见（亚毫秒级，用户无感知）
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, w, h);
    ctx.drawImage(offscreen, 0, 0);

    renderedVersion.current.set(index, v);

    // 所有可见 tile 完成 → 退出缓冲/完成初始化
    if (visibleTiles.current.size > 0) {
      let allDone = true;
      visibleTiles.current.forEach((i) => {
        if (renderedVersion.current.get(i) !== versionRef.current) allDone = false;
      });
      if (allDone) {
        phaseRef.current = 'idle';
        setBuffering(false);
        if (!readyRef.current) {
          readyRef.current = true;
          setReady(true);
        }
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

    // 已初始化 → 进入缓冲态（仅 CSS 模糊，不计算）
    if (readyRef.current) {
      phaseRef.current = 'buffering';
      setBuffering(true);
    }

    debounceTimer.current = window.setTimeout(() => {
      debounceTimer.current = null;
      measure();
      versionRef.current += 1;
      phaseRef.current = 'computing';

      const main = scrollRef.current;
      const content = contentRef.current;
      // 用 .chat-content 的 scrollHeight 加 padding 替代 .chat-area 的 scrollHeight，
      // 避免 absolute positioned canvas 块撑大 scrollHeight 形成循环依赖
      const scrollHeight = content
        ? content.scrollHeight + paddingRef.current.top + paddingRef.current.bottom
        : (main ? main.scrollHeight : 0);
      const tileCount = Math.ceil(scrollHeight / TILE_HEIGHT);
      setLayout((prev) =>
        prev.scrollHeight === scrollHeight && prev.tileCount === tileCount
          ? prev
          : { scrollHeight, tileCount }
      );

      // 边界：无可见 tile → 直接退出缓冲
      if (visibleTiles.current.size === 0) {
        phaseRef.current = 'idle';
        setBuffering(false);
        if (!readyRef.current) {
          readyRef.current = true;
          setReady(true);
        }
        return;
      }

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
    // tileCount 变化时清理残留的 visibleTiles，避免已卸载的 tile index 阻止 ready
    visibleTiles.current.clear();
    renderedVersion.current.clear();
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const index = Number((entry.target as HTMLElement).dataset.tileIndex);
          if (Number.isNaN(index)) continue;
          if (entry.isIntersecting) {
            visibleTiles.current.add(index);
            if (phaseRef.current !== 'buffering' && renderedVersion.current.get(index) !== versionRef.current) renderTile(index);
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
    <div className={`contour-bg${ready ? " ready" : ""}${buffering ? " buffering" : ""}`} aria-hidden="true">
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
