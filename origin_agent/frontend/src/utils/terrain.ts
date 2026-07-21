import type { ChatMessage } from "../types";

export interface MessageInfluence {
  y0: number;
  y1: number;
  strength: number;
  u: number;
}

export interface TerrainParams {
  seed: number;
  width: number;
  influences: MessageInfluence[];
}

export interface ContourRegion {
  x0: number;
  y0: number;
  w: number;
  h: number;
}

export interface ContourStyleOptions {
  cell: number;
  levels: number;
  majorEvery: number;
  minorStyle: string;
  majorStyle: string;
  glowStyle: string;
}

/* ── 地形常量 ── */
// 基础地貌幅度
const BASE_AMP = 0.55;
// 消息隆起最大幅度（弱联动：压低上限）
const UPLIFT_MAX = 0.9;
// 基础噪声特征尺度（px）
const NOISE_SCALE = 260;
// 域扭曲幅度（px）
const WARP_AMP = 160;
// 域扭曲噪声特征尺度（px）
const WARP_SCALE = 380;
// 消息纵向高斯 σ 的最小值（px）
const MIN_BAND_SIGMA = 120;
// 消息纵向高斯 σ 相对消息高度的比例
const BAND_SIGMA_RATIO = 0.8;
// 等值线起始层级与步进
const LEVEL_START = 0.2;
const LEVEL_STEP = 0.08;
// 图片内容块的等效字符数
const IMAGE_BLOCK_CHARS = 200;

/* ── 格点哈希 → [0, 1) ── */
function hash2(ix: number, iy: number, seed: number): number {
  let h = (ix * 374761393 + iy * 668265263 + seed * 144665) | 0;
  h = (h ^ (h >> 13)) | 0;
  h = Math.imul(h, 1274126177);
  h = (h ^ (h >> 16)) >>> 0;
  return h / 4294967296;
}

function smoothstep(t: number): number {
  return t * t * (3 - 2 * t);
}

/* ── 双线性插值值噪声 ── */
function valueNoise(x: number, y: number, seed: number): number {
  const ix = Math.floor(x);
  const iy = Math.floor(y);
  const fx = smoothstep(x - ix);
  const fy = smoothstep(y - iy);
  const v00 = hash2(ix, iy, seed);
  const v10 = hash2(ix + 1, iy, seed);
  const v01 = hash2(ix, iy + 1, seed);
  const v11 = hash2(ix + 1, iy + 1, seed);
  const top = v00 + (v10 - v00) * fx;
  const bottom = v01 + (v11 - v01) * fx;
  return top + (bottom - top) * fy;
}

/* ── 分形叠加（lacunarity 2, gain 0.5） ── */
function fbm(x: number, y: number, seed: number, octaves = 4): number {
  let sum = 0;
  let amp = 0.5;
  let freq = 1;
  let norm = 0;
  for (let i = 0; i < octaves; i++) {
    sum += amp * valueNoise(x * freq, y * freq, seed + i * 1013);
    norm += amp;
    amp *= 0.5;
    freq *= 2;
  }
  return sum / norm;
}

/* ── 字符串 → uint32 种子（FNV-1a） ── */
export function seedFromString(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/* ── 消息内容等效长度 ── */
export function messageLength(m: ChatMessage): number {
  if (typeof m.content === "string") return m.content.length;
  let len = 0;
  for (const block of m.content) {
    len += block.type === "text" ? block.text.length : IMAGE_BLOCK_CHARS;
  }
  return len;
}

/* ── 文档坐标 (x, y) 处的地形高度 ── */
export function terrainHeight(x: number, y: number, params: TerrainParams): number {
  // 域扭曲：两个独立低频噪声分别扰动 x/y，打散全幅面的规则秩序
  const qx = fbm(x / WARP_SCALE, y / WARP_SCALE, params.seed + 7001, 3);
  const qy = fbm(x / WARP_SCALE, y / WARP_SCALE, params.seed + 13003, 3);
  const wx = x + (qx - 0.5) * 2 * WARP_AMP;
  const wy = y + (qy - 0.5) * 2 * WARP_AMP;

  const base = BASE_AMP * fbm(wx / NOISE_SCALE, wy / NOISE_SCALE, params.seed);
  let uplift = 0;
  for (const inf of params.influences) {
    const cy = (inf.y0 + inf.y1) / 2;
    const sigma = Math.max(MIN_BAND_SIGMA, (inf.y1 - inf.y0) * BAND_SIGMA_RATIO);
    const dy = wy - cy;
    // 3σ 之外的高斯贡献可忽略，长会话下显著减少计算量
    if (Math.abs(dy) > 3 * sigma) continue;
    const dx = wx - inf.u * params.width;
    uplift += inf.strength * Math.exp(-(dx * dx + dy * dy) / (2 * sigma * sigma));
  }
  return base + uplift * UPLIFT_MAX;
}

/* ── 让出主线程的时间切片点 ── */
function yieldMain(): Promise<void> {
  return new Promise((r) => setTimeout(r, 0));
}

/* ── marching squares：对 region 内的每个等值层级描边（分片异步，可中止） ── */
export async function strokeContours(
  ctx: CanvasRenderingContext2D,
  params: TerrainParams,
  region: ContourRegion,
  opts: ContourStyleOptions,
  shouldAbort?: () => boolean
): Promise<void> {
  const { cell, levels, majorEvery, minorStyle, majorStyle, glowStyle } = opts;
  const cols = Math.ceil(region.w / cell) + 1;
  const rows = Math.ceil(region.h / cell) + 1;
  if (cols < 2 || rows < 2) return;

  // 采样是 CPU 大头，按行块切片让出主线程
  const grid = new Float32Array(cols * rows);
  const ROW_CHUNK = 32;
  for (let r0 = 0; r0 < rows; r0 += ROW_CHUNK) {
    const rEnd = Math.min(rows, r0 + ROW_CHUNK);
    for (let r = r0; r < rEnd; r++) {
      for (let c = 0; c < cols; c++) {
        grid[r * cols + c] = terrainHeight(region.x0 + c * cell, region.y0 + r * cell, params);
      }
    }
    await yieldMain();
    if (shouldAbort?.()) return;
  }

  for (let li = 0; li < levels; li++) {
    const level = LEVEL_START + li * LEVEL_STEP;
    const major = li % majorEvery === 0;
    ctx.beginPath();
    for (let r = 0; r < rows - 1; r++) {
      for (let c = 0; c < cols - 1; c++) {
        const x = region.x0 + c * cell;
        const y = region.y0 + r * cell;
        const tl = grid[r * cols + c];
        const tr = grid[r * cols + c + 1];
        const br = grid[(r + 1) * cols + c + 1];
        const bl = grid[(r + 1) * cols + c];
        let caseIdx = 0;
        if (tl > level) caseIdx |= 8;
        if (tr > level) caseIdx |= 4;
        if (br > level) caseIdx |= 2;
        if (bl > level) caseIdx |= 1;
        if (caseIdx === 0 || caseIdx === 15) continue;

        // 各边与等值线的交点（线性插值）
        const lerp = (a: number, b: number) => (level - a) / (b - a);
        const top = (): [number, number] => [x + cell * lerp(tl, tr), y];
        const right = (): [number, number] => [x + cell, y + cell * lerp(tr, br)];
        const bottom = (): [number, number] => [x + cell * lerp(bl, br), y + cell];
        const left = (): [number, number] => [x, y + cell * lerp(tl, bl)];

        const seg = (p1: [number, number], p2: [number, number]) => {
          ctx.moveTo(p1[0], p1[1]);
          ctx.lineTo(p2[0], p2[1]);
        };

        switch (caseIdx) {
          case 1: case 14: seg(left(), bottom()); break;
          case 2: case 13: seg(bottom(), right()); break;
          case 3: case 12: seg(left(), right()); break;
          case 4: case 11: seg(top(), right()); break;
          case 6: case 9: seg(top(), bottom()); break;
          case 7: case 8: seg(left(), top()); break;
          case 5: seg(left(), top()); seg(bottom(), right()); break;
          case 10: seg(top(), right()); seg(left(), bottom()); break;
        }
      }
    }
    // 先描宽而淡的泛光层，再描主线（比 shadowBlur 开销低）
    ctx.strokeStyle = glowStyle;
    ctx.lineWidth = major ? 6 : 3.5;
    ctx.stroke();
    // 计曲线（主线）加粗加深，首曲线（副线）细浅
    ctx.strokeStyle = major ? majorStyle : minorStyle;
    ctx.lineWidth = major ? 2.5 : 1.5;
    ctx.stroke();
    // 每个层级描完后让出主线程
    await yieldMain();
    if (shouldAbort?.()) return;
  }
}
