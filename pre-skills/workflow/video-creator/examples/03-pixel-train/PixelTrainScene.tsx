import React, {useLayoutEffect, useRef} from "react";
import {AbsoluteFill, Img, random, staticFile, useCurrentFrame, useVideoConfig} from "remotion";

/**
 * 样例场景 03：像素风列车过境（黄昏背光）
 *
 * 素材由 pixbead 生成（见同目录 gen_assets.py）：天空+太阳+光晕、晚霞积云、三层山脊、
 * 地面+钢轨、电力动车、以及三组草/芦苇变体层。
 *
 * 【素材放置】把本目录 assets/ 里的 13 张 PNG 复制到工程的 public/pixel/ 下，
 * 下面的 staticFile("pixel/...") 才找得到。要重新生成素材就运行 gen_assets.py。
 *
 * 动画层：
 * - 列车：从右侧匀速驶入，3 秒结束时车头已出画、车身仍在画面内（不必走完）
 * - 丁达尔光柱：从太阳向下放射的 9 道像素光带，逐块绘制；
 *   被列车挡住的部分直接不画，太阳被遮时整束减弱 —— 用光被切断表现遮挡，而不是整体压暗
 * - 风：草与芦苇各分 3 个变体层，不同相位的正弦做整数像素位移（始终像素对齐）
 * - 气流：列车在画面内时，近景草与芦苇再向右偏 2px
 * - 粒子：暖色尘埃自右向左飘，越靠前越快
 *
 * 逻辑画布 320×180，按 S = width/320 放大（1920 时 S=6）。
 */

const LW = 320;
const LH = 180;

const STILL = ["mountains", "ground"];
const GRASS_MID = [0, 1, 2].map((v) => `pixel/grass_mid_${v}.png`);
const GRASS_FG = [0, 1, 2].map((v) => `pixel/grass_fg_${v}.png`);
const REED = [0, 1, 2].map((v) => `pixel/reeds_${v}.png`);

/**
 * 列车：长 460（画面 320 的 1.44 倍），所以存在一段「车头已出左边界、车尾还在右边界外」的
 * 完全贯穿时间：窗口宽度 = 460 − 320 = 140px，速度 245px/s 时约 0.57 秒。
 * 车顶 y=112，车底 y=140 压在钢轨上。
 */
const TRAIN_W = 460;
const TRAIN_TOP = 106;
const ENTER_AT = 0.1;
const SPEED = 245;
const START_X = 330;

/** 太阳（与生成器一致） */
const SUN_X = 250;
const SUN_Y = 116;
const SUN_R = 7;

/** 丁达尔光柱的角度（相对竖直向下，负值偏左） */
const RAYS = [-88, -76, -64, -52, -40, -28, -16, -4, 8, 20, 32];

type Particle = {y: number; speed: number; offset: number; big: boolean};

const PARTICLES: Particle[] = Array.from({length: 18}, (_, i) => ({
  y: 96 + random(`px-y-${i}`) * 78,
  speed: 46 + random(`px-sp-${i}`) * 78,
  offset: random(`px-off-${i}`) * LW,
  big: random(`px-big-${i}`) > 0.72,
}));

/** 确定性噪声：让光柱断断续续，像光里的浮尘 */
const hash01 = (x: number, y: number) => {
  let n = (x * 374761393 + y * 668265263) & 0xffffffff;
  n = (n ^ (n >>> 13)) * 1274126177 & 0xffffffff;
  return ((n ^ (n >>> 16)) & 0xffffffff) / 0xffffffff;
};

export const PixelTrainScene: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const t = frame / fps;
  const S = width / LW;

  const rawX = START_X - SPEED * Math.max(0, t - ENTER_AT);
  const trainX = Math.round(rawX);
  const trainInFrame = rawX < LW && rawX + TRAIN_W > -10;

  // 太阳被遮挡比例（水平重叠 / 太阳直径）
  const overlap = Math.max(0, Math.min(rawX + TRAIN_W, SUN_X + SUN_R) - Math.max(rawX, SUN_X - SUN_R));
  const occlusion = Math.min(1, overlap / (SUN_R * 2));

  const sway = (phase: number, amp: number) => Math.round(Math.sin(t * 2.35 + phase) * amp);
  const gust = trainInFrame ? 2 : 0;

  // ---- 丁达尔光柱（画在逻辑分辨率的 canvas 上，再整体放大保持像素感） ----
  const raysRef = useRef<HTMLCanvasElement | null>(null);
  useLayoutEffect(() => {
    const cv = raysRef.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, LW, LH);

    const blocked = (x: number, y: number) =>
      x >= trainX && x <= trainX + TRAIN_W && y >= TRAIN_TOP && y <= 140;
    // 光源被遮时整束熄灭（而不是整幅画面压暗）
    const fade = 1 - occlusion * 0.92;
    // 极慢的呼吸，让光有空气感
    const breathe = 0.92 + 0.08 * Math.sin(t * 2.6);

    for (const angle of RAYS) {
      const rad = (angle * Math.PI) / 180;
      const dx = Math.sin(rad);
      const dy = Math.cos(rad);
      for (let d = 5; d < 175; d += 3) {
        const x = SUN_X + dx * d;
        const y = SUN_Y + dy * d;
        if (x < -4 || x > LW + 4 || y > LH) continue;
        if (blocked(x, y)) continue;
        const ix = Math.round(x);
        const iy = Math.round(y);
        if (hash01(ix, iy) < 0.12) continue; // 光里的浮尘空隙
        const w = 1 + Math.floor(d / 34);
        const a = Math.max(0, 0.68 * Math.pow(1 - d / 178, 0.8)) * fade * breathe;
        if (a <= 0.012) continue;
        ctx.fillStyle = `rgba(255,206,120,${a.toFixed(3)})`;
        ctx.fillRect(ix, iy, w, w);
        // 光束芯部再叠一层亮色，形成明显的光丝
        if (w > 1) {
          ctx.fillStyle = `rgba(255,242,200,${(a * 0.75).toFixed(3)})`;
          ctx.fillRect(ix + (w >> 1), iy, Math.max(1, w - 1), Math.max(1, w - 1));
        }
      }
    }
  }, [trainX, occlusion, t]);

  const layer = (src: string, dx = 0, dy = 0, key?: string) => (
    <div
      key={key ?? src}
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width,
        height,
        transform: `translate(${dx * S}px, ${dy * S}px)`,
      }}
    >
      <Img src={staticFile(src)} style={{width, height, imageRendering: "pixelated", display: "block"}} />
    </div>
  );

  return (
    <AbsoluteFill style={{background: "#241a2c", overflow: "hidden"}}>
      {/* 远景 */}
      {layer("pixel/sky.png")}
      {/* 晚霞积云：随风缓慢左移，位移取整保持像素对齐 */}
      {layer("pixel/clouds.png", Math.round(-t * 1.4), 0, "clouds")}
      {STILL.map((name) => layer(`pixel/${name}.png`))}

      {/* 丁达尔光柱（在列车之后画，所以被列车截断） */}
      <canvas
        ref={raysRef}
        width={LW}
        height={LH}
        style={{position: "absolute", inset: 0, width, height, imageRendering: "pixelated"}}
      />

      {/* 中景草 */}
      {GRASS_MID.map((src, i) => layer(src, sway(i * 2.1, 1), 0, `gm-${i}`))}

      {/* 列车 */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width,
          height,
          transform: `translate(${trainX * S}px, ${TRAIN_TOP * S}px)`,
        }}
      >
        <Img
          src={staticFile("pixel/train.png")}
          style={{width: TRAIN_W * S, height: 34 * S, imageRendering: "pixelated", display: "block"}}
        />
      </div>

      {/* 近景草（在列车之前，受气流影响） */}
      {GRASS_FG.map((src, i) => layer(src, sway(i * 2.1 + 1, 1) + gust, 0, `gf-${i}`))}

      {/* 前景芦苇 */}
      {REED.map((src, i) => layer(src, sway(i * 1.7 + 0.6, 2) + gust, 0, `rd-${i}`))}

      {/* 风中的尘埃 */}
      {PARTICLES.map((p, i) => {
        const x = (((p.offset - t * p.speed) % LW) + LW) % LW;
        const wobble = Math.sin(t * 3 + i) * 1.5;
        const size = (p.big ? 2 : 1) * S;
        return (
          <div
            key={`p-${i}`}
            style={{
              position: "absolute",
              left: Math.round(x) * S,
              top: Math.round(p.y + wobble) * S,
              width: size,
              height: size,
              background: "#ffcf6b",
              opacity: 0.22 + (p.big ? 0.22 : 0.1),
            }}
          />
        );
      })}

      {/* 极轻的暗角（固定，不随遮挡变化） */}
      <svg width={width} height={height} style={{position: "absolute", inset: 0}}>
        <defs>
          <radialGradient id="px-vig" cx="50%" cy="52%" r="72%">
            <stop offset="0.45" stopColor="#140a1a" stopOpacity="0" />
            <stop offset="1" stopColor="#140a1a" stopOpacity="0.4" />
          </radialGradient>
        </defs>
        <rect width={width} height={height} fill="url(#px-vig)" />
      </svg>
    </AbsoluteFill>
  );
};
