/**
 * 样例代码 02：城市体积模型档案界面（自包含版）
 *
 * 画面内容：约 3000 栋白模建筑组成的俯视城市 + 投影阴影 + 红色标注层 + 档案 HUD。
 * 不依赖任何模板文件，可直接放进任意 Remotion 工程：
 *
 *   <Composition id="CityArchive" component={CityArchiveStandalone}
 *               durationInFrames={480} fps={60} width={1920} height={1080} />
 *
 * 设计基准 1080p，内部按 k = height / 1080 等比缩放，720p / 4K 下无需改数值。
 *
 * ---------------------------------------------------------------------------
 * 字体准备（本组件不自带字体文件）：
 *
 *   import {loadFont} from "@remotion/fonts";
 *   import {staticFile} from "remotion";
 *
 *   loadFont({family: "Quicksand", url: staticFile("fonts/Quicksand-600.woff2"), weight: "600"});
 *   loadFont({family: "YouYuan",  url: staticFile("fonts/YY-Regular.woff2"),     weight: "400"});
 *
 *   - 西文/数字：Quicksand（几何圆体，OFL）或 Rajdhani（窄体技术感，OFL）
 *   - 中文：幼圆 YouYuan（Windows 自带 SIMYOU.TTF，需自行子集化成 woff2）
 *   改 FONT_ROUND / FONT_ZH 两个常量即可换成别的字体组合。
 * ---------------------------------------------------------------------------
 */
import React, {useLayoutEffect, useRef} from "react";
import {AbsoluteFill, Easing, interpolate, random, useCurrentFrame, useVideoConfig} from "remotion";

/* ============================ 参数区 ============================ */

/** 这一段的总时长（秒） */
const DURATION = 8;

/** 网格边长与单位格尺寸：N * U = 2356 世界像素。
 *  等距菱形要包住 1920×1080 画布四角，需满足 N*U ≥ W/2/cos30 + H/2/0.5 ≈ 2189 */
const N = 62;
const U = 38;
const COS30 = Math.cos(Math.PI / 6);
const PERSP = 0.09; // 透视强度：远处 0.91 / 近处 1.09
const STREET = 7; // 每 7 格一条街道

const INK = "#14161a";
const INK2 = "#5c6165";
const GRAY = "#9aa0a5";
const RED = "#c81623";

/** 字体栈：按上面的说明替换 */
const FONT_ROUND = '"Quicksand", "PingFang SC", sans-serif';
const FONT_ZH = '"YouYuan", "PingFang SC", "Microsoft YaHei", sans-serif';

/* ============================ 缓动工具 ============================ */

const EASE = {
  linear: Easing.linear,
  out: Easing.out(Easing.cubic),
  in: Easing.in(Easing.cubic),
};

const ramp = (t: number, range: [number, number], out: [number, number] = [0, 1], easing = EASE.out) =>
  interpolate(t, range, out, {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing});

const keys = (t: number, input: number[], output: number[], easing = EASE.out) =>
  interpolate(t, input, output, {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing});

/* ============================ 城市生成 ============================ */

type Block = {gx: number; gy: number; nx: number; ny: number; h: number; depth: number};

/** 模块加载时确定性生成一次，之后每帧只做投影计算 */
const CITY: Block[] = (() => {
  const taken = new Set<string>();
  const out: Block[] = [];
  const free = (gx: number, gy: number, nx: number, ny: number) => {
    if (gx < 0 || gy < 0 || gx + nx > N || gy + ny > N) return false;
    for (let a = 0; a < nx; a++) {
      for (let b = 0; b < ny; b++) {
        if (taken.has(`${gx + a},${gy + b}`)) return false;
      }
    }
    return true;
  };
  for (let gy = 0; gy < N; gy++) {
    for (let gx = 0; gx < N; gx++) {
      if (taken.has(`${gx},${gy}`)) continue;
      // 街道：形成街区网格
      if (gx % STREET === 0 || gy % STREET === 0) continue;
      // 街区内留少量空地
      if (random(`gap-${gx}-${gy}`) < 0.1) continue;
      const roll = random(`size-${gx}-${gy}`);
      let nx = 1;
      let ny = 1;
      if (roll > 0.94) {
        nx = 2;
        ny = 2;
      } else if (roll > 0.8) {
        if (random(`ori-${gx}-${gy}`) > 0.5) nx = 2;
        else ny = 2;
      }
      if (!free(gx, gy, nx, ny)) {
        nx = 1;
        ny = 1;
        if (!free(gx, gy, 1, 1)) continue;
      }
      for (let a = 0; a < nx; a++) {
        for (let b = 0; b < ny; b++) taken.add(`${gx + a},${gy + b}`);
      }
      // 天际线：绝大多数中低层，约 4% 高塔
      const r1 = random(`h1-${gx}-${gy}`);
      const r2 = random(`h2-${gx}-${gy}`);
      let unit = 0.35 + Math.pow(r1, 2.4) * 2;
      if (r2 > 0.96) unit *= 2.2;
      out.push({gx, gy, nx, ny, h: unit * U, depth: gx + nx + gy + ny});
    }
  }
  // 旋转幅度只有 ±1.6°，用未旋转深度预排序即可
  return out.sort((a, b) => a.depth - b.depth);
})();

const HALF = (N * U) / 2;

/** 红色标注块：贴地的斜方块，集中在中部 */
const HOT = Array.from({length: 20}, (_, i) => {
  const ang = random(`hot-ang-${i}`) * Math.PI * 2;
  const dist = Math.pow(random(`hot-dist-${i}`), 0.6) * 620;
  return {
    x: HALF + Math.cos(ang) * dist * 1.3,
    y: HALF + Math.sin(ang) * dist * 0.9,
    s: 34 + random(`hot-size-${i}`) * 72,
    rot: (random(`hot-rot-${i}`) - 0.5) * 0.45,
    at: 1.5 + random(`hot-at-${i}`) * 1.8,
  };
});

/** 红色标注点 */
const DOTS = Array.from({length: 14}, (_, i) => {
  const ang = random(`dot-ang-${i}`) * Math.PI * 2;
  const dist = Math.pow(random(`dot-dist-${i}`), 0.68) * 560;
  return {
    x: HALF + Math.cos(ang) * dist * 1.35,
    y: HALF + Math.sin(ang) * dist * 0.92,
    at: 1.1 + i * 0.08,
  };
});

/* ============================ 噪点贴图 ============================ */

let noiseTile: HTMLCanvasElement | null = null;

const makeNoise = () => {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 256;
  const g = c.getContext("2d");
  if (!g) return c;
  const img = g.createImageData(256, 256);
  let seed = 20290320;
  const rnd = () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
  for (let i = 0; i < img.data.length; i += 4) {
    const v = 120 + rnd() * 80;
    img.data[i] = v;
    img.data[i + 1] = v;
    img.data[i + 2] = v;
    img.data[i + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  return c;
};

/* ============================ 绘制 ============================ */

const drawCity = (ctx: CanvasRenderingContext2D, t: number, k: number, W: number, H: number) => {
  const lt = t;

  // 运镜：绕竖直轴缓慢旋转 + 缓慢推近 + 轻微平移
  const spin = keys(t, [0, DURATION], [-0.028, 0.021], EASE.linear);
  const zoom = keys(t, [0, DURATION], [1, 1.075], EASE.linear);
  const panX = keys(t, [0, DURATION], [-14, 10], EASE.linear);
  const panY = keys(t, [0, DURATION], [9, -7], EASE.linear);
  const cr = Math.cos(spin);
  const sr = Math.sin(spin);

  /** 世界坐标 → 基准屏幕坐标（含透视），out[2] 是该点的透视系数 */
  const P = (wx: number, wy: number, out: [number, number, number]) => {
    const x = wx - HALF;
    const y = wy - HALF;
    const xr = x * cr - y * sr;
    const yr = x * sr + y * cr;
    const sx = (xr - yr) * COS30;
    const sy = (xr + yr) * 0.5;
    const f = 1 + (PERSP * sy) / HALF;
    out[0] = sx * f;
    out[1] = sy * f;
    out[2] = f;
  };

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, W, H);

  // 背景
  const sky = ctx.createLinearGradient(0, 0, W * 0.35, H);
  sky.addColorStop(0, "#fafbfc");
  sky.addColorStop(0.45, "#f2f4f6");
  sky.addColorStop(1, "#e7eaed");
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, W, H);

  ctx.save();
  ctx.translate(W / 2 + panX * k, H / 2 + panY * k);
  ctx.scale(k * zoom, k * zoom);

  const p00: [number, number, number] = [0, 0, 1];
  const p10: [number, number, number] = [0, 0, 1];
  const p11: [number, number, number] = [0, 0, 1];
  const p01: [number, number, number] = [0, 0, 1];
  const tmp: [number, number, number] = [0, 0, 1];

  // 阴影：3000 个四边形合并成一条 path，只填充一次
  ctx.beginPath();
  for (const b of CITY) {
    const x0 = b.gx * U;
    const y0 = b.gy * U;
    const x1 = x0 + b.nx * U;
    const y1 = y0 + b.ny * U;
    const d = b.h * 0.4;
    P(x0, y0, p00);
    P(x1, y0, p10);
    P(x1 + d, y1 + d, p11);
    P(x0 + d, y1 + d, p01);
    ctx.moveTo(p00[0], p00[1]);
    ctx.lineTo(p10[0], p10[1]);
    ctx.lineTo(p11[0], p11[1]);
    ctx.lineTo(p01[0], p01[1]);
    ctx.closePath();
  }
  ctx.fillStyle = "rgba(148,156,167,0.19)";
  ctx.fill();

  // 建筑三面：左面（暗）/ 右面（更暗）/ 顶面（纯白 + 细描边）
  for (const b of CITY) {
    const x0 = b.gx * U;
    const y0 = b.gy * U;
    const x1 = x0 + b.nx * U;
    const y1 = y0 + b.ny * U;
    P(x0, y0, p00);
    P(x1, y0, p10);
    P(x1, y1, p11);
    P(x0, y1, p01);
    const h = b.h;
    const h00 = h * p00[2];
    const h10 = h * p10[2];
    const h11 = h * p11[2];
    const h01 = h * p01[2];

    ctx.beginPath();
    ctx.moveTo(p11[0], p11[1] - h11);
    ctx.lineTo(p01[0], p01[1] - h01);
    ctx.lineTo(p01[0], p01[1]);
    ctx.lineTo(p11[0], p11[1]);
    ctx.closePath();
    ctx.fillStyle = "#e9ecf0";
    ctx.fill();

    ctx.beginPath();
    ctx.moveTo(p10[0], p10[1] - h10);
    ctx.lineTo(p11[0], p11[1] - h11);
    ctx.lineTo(p11[0], p11[1]);
    ctx.lineTo(p10[0], p10[1]);
    ctx.closePath();
    ctx.fillStyle = "#dce1e7";
    ctx.fill();

    ctx.beginPath();
    ctx.moveTo(p00[0], p00[1] - h00);
    ctx.lineTo(p10[0], p10[1] - h10);
    ctx.lineTo(p11[0], p11[1] - h11);
    ctx.lineTo(p01[0], p01[1] - h01);
    ctx.closePath();
    ctx.fillStyle = "#ffffff";
    ctx.fill();
    ctx.strokeStyle = "rgba(24,30,42,0.13)";
    ctx.lineWidth = 0.7;
    ctx.stroke();
  }

  // 红色标注块
  for (let i = 0; i < HOT.length; i++) {
    const cell = HOT[i];
    const p = ramp(lt, [cell.at, cell.at + 0.5]);
    if (p <= 0) continue;
    const s = cell.s * p;
    const kk = Math.SQRT1_2 * s;
    const cs = Math.cos(cell.rot);
    const sn = Math.sin(cell.rot);
    const corners: Array<[number, number]> = [
      [cell.x + (cs - sn) * kk, cell.y + (sn + cs) * kk],
      [cell.x + (-cs - sn) * kk, cell.y + (-sn + cs) * kk],
      [cell.x - (cs - sn) * kk, cell.y - (sn + cs) * kk],
      [cell.x + (cs + sn) * kk, cell.y + (sn - cs) * kk],
    ];
    ctx.beginPath();
    for (let j = 0; j < 4; j++) {
      P(corners[j][0], corners[j][1], tmp);
      if (j === 0) ctx.moveTo(tmp[0], tmp[1]);
      else ctx.lineTo(tmp[0], tmp[1]);
    }
    ctx.closePath();
    ctx.fillStyle = "rgba(200,22,35,0.17)";
    ctx.fill();
    ctx.strokeStyle = "rgba(200,22,35,0.5)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  // 红色标注点
  for (let i = 0; i < DOTS.length; i++) {
    const dot = DOTS[i];
    const p = ramp(lt, [dot.at, dot.at + 0.4]);
    if (p <= 0) continue;
    P(dot.x, dot.y, tmp);
    ctx.beginPath();
    ctx.arc(tmp[0], tmp[1], 4.6 * p, 0, Math.PI * 2);
    ctx.fillStyle = RED;
    ctx.fill();
    ctx.beginPath();
    ctx.arc(tmp[0], tmp[1], 8.5 * p, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(200,22,35,0.4)";
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  ctx.restore();

  // 跨屏斜向红色网格线（2.5s 后逐渐出现）
  const scan = ramp(lt, [2.5, 4.0]);
  if (scan > 0) {
    ctx.save();
    ctx.translate(W / 2, H / 2);
    ctx.rotate((-27 * Math.PI) / 180);
    ctx.globalAlpha = scan;
    for (let i = 0; i < 10; i++) {
      const x = (-460 + i * 320) * k;
      ctx.beginPath();
      ctx.moveTo(x, -800 * k);
      ctx.lineTo(x, 1800 * k);
      ctx.strokeStyle = i % 3 === 0 ? "rgba(200,22,35,0.42)" : "rgba(200,22,35,0.24)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    ctx.restore();
    ctx.globalAlpha = 1;
  }

  // 暗角：边缘渐白，模拟远景雾
  const vig = ctx.createRadialGradient(W / 2, H * 0.48, H * 0.28, W / 2, H * 0.48, H * 0.95);
  vig.addColorStop(0, "rgba(255,255,255,0)");
  vig.addColorStop(0.72, "rgba(255,255,255,0.16)");
  vig.addColorStop(1, "rgba(255,255,255,0.68)");
  ctx.fillStyle = vig;
  ctx.fillRect(0, 0, W, H);

  // 极淡色差：左偏红、右偏青
  const ca = ctx.createLinearGradient(0, 0, W, H * 0.2);
  ca.addColorStop(0, "rgba(200,22,35,0.055)");
  ca.addColorStop(0.45, "rgba(200,22,35,0)");
  ca.addColorStop(0.55, "rgba(28,95,138,0)");
  ca.addColorStop(1, "rgba(28,95,138,0.05)");
  ctx.fillStyle = ca;
  ctx.fillRect(0, 0, W, H);

  // 细颗粒噪点
  if (!noiseTile) noiseTile = makeNoise();
  const pat = ctx.createPattern(noiseTile, "repeat");
  if (pat) {
    ctx.globalAlpha = 0.05;
    ctx.fillStyle = pat;
    ctx.fillRect(0, 0, W, H);
    ctx.globalAlpha = 1;
  }
};

/* ============================ 组件 ============================ */

export const CityArchiveStandalone: React.FC = () => {
  const ref = useRef<HTMLCanvasElement | null>(null);
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const t = frame / fps;
  const k = height / 1080;

  useLayoutEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    drawCity(ctx, t, k, width, height);
  }, [t, k, width, height]);

  const hud = (at: number, len = 0.55) => ramp(t, [at, at + len]);

  return (
    <AbsoluteFill style={{background: "#eceef0"}}>
      <canvas ref={ref} width={width} height={height} style={{position: "absolute", inset: 0, width, height}} />

      {/* 左上标识 */}
      <div
        style={{
          position: "absolute",
          left: 54 * k,
          top: 30 * k,
          transform: `scaleX(0.82) scale(${k})`,
          transformOrigin: "left top",
          opacity: hud(0.06, 0.5),
        }}
      >
        <div style={{display: "flex", alignItems: "baseline", gap: 26, fontFamily: FONT_ROUND, fontWeight: 600}}>
          <span style={{fontSize: 50, color: INK, letterSpacing: "0.5px"}}>
            ARCHIVE A<span style={{fontSize: 22, verticalAlign: "super"}}>®</span>
          </span>
          <span style={{fontSize: 44, color: INK}}>THIRD-PARTY</span>
        </div>
        <div style={{fontFamily: FONT_ROUND, fontWeight: 600, fontSize: 26, color: INK2, marginTop: 2}}>03.20</div>
      </div>

      {/* 左侧竖排编号 */}
      <div
        style={{
          position: "absolute",
          left: 16 * k,
          top: 470 * k,
          transform: `rotate(-90deg) scale(${k})`,
          transformOrigin: "left top",
          fontFamily: FONT_ROUND,
          fontWeight: 600,
          fontSize: 13,
          letterSpacing: "3.4px",
          color: INK2,
          whiteSpace: "nowrap",
          opacity: hud(0.3, 0.55),
        }}
      >
        DO NOT DISTRIBUTE&nbsp;&nbsp;/&nbsp;&nbsp;严格分发&nbsp;&nbsp;/&nbsp;&nbsp;A-0031
      </div>

      {/* 左中：体积模型 */}
      <div style={{position: "absolute", left: 54 * k, top: 268 * k, opacity: hud(0.5, 0.55)}}>
        <div style={{display: "flex", alignItems: "center", gap: 9, transform: `scale(${k})`, transformOrigin: "left top"}}>
          <span style={{width: 7, height: 7, background: RED, display: "inline-block"}} />
          <span style={{fontFamily: FONT_ZH, fontSize: 15, letterSpacing: "2.4px", color: INK2}}>城市体积模型</span>
          <span style={{fontFamily: FONT_ROUND, fontSize: 11, letterSpacing: "1.6px", color: GRAY}}>/ VOLUMETRIC MODEL</span>
        </div>
        <div
          style={{
            fontFamily: FONT_ROUND,
            fontWeight: 600,
            fontSize: 52 * k,
            color: INK,
            lineHeight: 1.15,
            marginTop: 4 * k,
          }}
        >
          03.20
        </div>
      </div>

      {/* 右上：录制信息 */}
      <div
        style={{
          position: "absolute",
          right: 56 * k,
          top: 34 * k,
          textAlign: "right",
          transform: `scale(${k})`,
          transformOrigin: "right top",
          opacity: hud(0.14, 0.5),
        }}
      >
        <div style={{display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8}}>
          <span style={{width: 7, height: 7, background: RED, display: "inline-block"}} />
          <span style={{fontFamily: FONT_ROUND, fontSize: 12, letterSpacing: "1.6px", color: INK2}}>REC 0031</span>
          <span style={{width: 9, height: 9, border: `1.5px solid ${RED}`, borderRadius: "50%", display: "inline-block"}} />
          <span style={{fontFamily: FONT_ROUND, fontSize: 12, letterSpacing: "1.6px", color: INK2}}>REC+8</span>
        </div>
        <div style={{fontFamily: FONT_ROUND, fontSize: 12, letterSpacing: "1.6px", color: GRAY, marginTop: 5}}>T+13.12</div>
      </div>

      {/* 右中：图幅信息 */}
      <div
        style={{
          position: "absolute",
          right: 56 * k,
          top: 246 * k,
          textAlign: "right",
          transform: `scale(${k})`,
          transformOrigin: "right top",
          opacity: hud(0.66, 0.55),
        }}
      >
        {[
          ["GRID", "44N"],
          ["SCALE", "1:25 000"],
          ["SUBJECT", "P-042"],
        ].map(([key, val]) => (
          <div key={key} style={{display: "flex", justifyContent: "flex-end", gap: 12, marginBottom: 7}}>
            <span style={{fontFamily: FONT_ROUND, fontSize: 11, letterSpacing: "1.8px", color: GRAY, paddingTop: 3}}>{key}</span>
            <span style={{fontFamily: FONT_ROUND, fontWeight: 600, fontSize: 17, color: INK, letterSpacing: "0.6px"}}>{val}</span>
          </div>
        ))}
      </div>

      {/* 底部档案字幕 */}
      <div style={{position: "absolute", left: 54 * k, top: 992 * k, opacity: hud(1.0, 0.6)}}>
        <div style={{display: "flex", alignItems: "center", gap: 16, transform: `scale(${k})`, transformOrigin: "left bottom"}}>
          <span style={{width: 3, height: 32, background: RED, display: "inline-block"}} />
          <span style={{fontFamily: FONT_ROUND, fontWeight: 600, fontSize: 30, color: INK}}>03.20</span>
          <span style={{fontFamily: FONT_ZH, fontSize: 24, letterSpacing: "1.4px", color: INK}}>
            六十八份记录里，只有这一份还能打开。
          </span>
        </div>
        <div
          style={{
            fontFamily: FONT_ROUND,
            fontSize: 11 * k,
            letterSpacing: `${2 * k}px`,
            color: GRAY,
            marginTop: 9 * k,
            marginLeft: 19 * k,
          }}
        >
          11 NIGHT SHIFTS / ZONE B-7
        </div>
      </div>

      {/* HUD 边框线 */}
      <div
        style={{
          position: "absolute",
          left: 54 * k,
          right: 56 * k,
          top: 96 * k,
          height: 1,
          background: "rgba(20,22,26,0.14)",
          opacity: hud(0.2, 0.6),
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 54 * k,
          right: 56 * k,
          top: 972 * k,
          height: 1,
          background: "rgba(20,22,26,0.14)",
          opacity: hud(0.9, 0.6),
        }}
      />
    </AbsoluteFill>
  );
};
