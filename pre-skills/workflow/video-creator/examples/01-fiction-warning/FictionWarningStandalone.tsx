/**
 * 样例 01（自包含版）：黑屏虚构声明
 *
 * 不依赖任何模板文件，可直接放进任意 Remotion 工程：
 *   <Composition id="FictionWarning" component={FictionWarningStandalone}
 *               durationInFrames={180} fps={60} width={1920} height={1080} />
 *
 * 版式按 1080p 像素坐标设计，内部用 k = height / 1080 等比缩放，
 * 因此在 720p / 4K 下同样成立（不需要改任何数值）。
 */
import React from "react";
import {AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig} from "remotion";

/** 这一段的总时长（秒）。改这里就能改节奏，淡入淡出的绝对时间不变 */
const DURATION = 3;

const ZH = [
  "本片所包含的时间、地点、人物及其他内容均为虚构",
  "与真实人物、机构或事件无关。如有雷同，纯属巧合。",
];
const EN = [
  "All times, places, persons and other content in this film are fictional and",
  "have no connection to real persons, institutions or events. Any similarity is coincidental.",
];

const ZH_FONT = '"PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif';
const MONO = 'Consolas, "Courier New", monospace';

const INK_ZH = "#b9b9bc";
const INK_EN = "#6c6c70";
const INK_CORNER = "#3c3c40";
const RED_DOT = "#6e1119";

/** 0→1 的钳位插值 */
const clip = (t: number, range: [number, number], easing: (n: number) => number = Easing.out(Easing.cubic)) =>
  interpolate(t, range, [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing});

export const FictionWarningStandalone: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const t = frame / fps;
  /** 以 1080p 为设计基准，其它分辨率等比缩放 */
  const k = height / 1080;

  const fadeOut = clip(t, [DURATION - 0.5, DURATION - 0.04], Easing.in(Easing.cubic));
  const body = Math.min(clip(t, [0.22, 1.05]), 1 - fadeOut);
  const corner = Math.min(clip(t, [0.85, 1.55]), 1 - fadeOut);

  return (
    <AbsoluteFill style={{background: "#000000"}}>
      {/* 左上角暗红标记点 */}
      <div
        style={{
          position: "absolute",
          left: 116 * k,
          top: 64 * k,
          width: 7 * k,
          height: 7 * k,
          background: RED_DOT,
          opacity: corner * 0.9,
        }}
      />

      {/* 中文声明 */}
      <div style={{position: "absolute", left: 0, top: 446 * k, width, textAlign: "center"}}>
        {ZH.map((line) => (
          <div
            key={line}
            style={{
              fontFamily: ZH_FONT,
              fontSize: 19 * k,
              letterSpacing: `${2.6 * k}px`,
              color: INK_ZH,
              lineHeight: 1.95,
              opacity: body,
            }}
          >
            {line}
          </div>
        ))}
      </div>

      {/* 英文声明 */}
      <div style={{position: "absolute", left: 0, top: 588 * k, width, textAlign: "center"}}>
        {EN.map((line) => (
          <div
            key={line}
            style={{
              fontFamily: MONO,
              fontSize: 12.5 * k,
              letterSpacing: `${0.4 * k}px`,
              color: INK_EN,
              lineHeight: 1.8,
              opacity: body * 0.95,
            }}
          >
            {line}
          </div>
        ))}
      </div>

      {/* 左下角机读编号 */}
      <div
        style={{
          position: "absolute",
          left: 104 * k,
          top: 1042 * k,
          fontFamily: MONO,
          fontSize: 11 * k,
          letterSpacing: `${2.2 * k}px`,
          color: INK_CORNER,
          opacity: corner,
        }}
      >
        RECORD A-0031 / 2029-0000 / FICTIONAL
      </div>

      {/* 右下角分辨率 */}
      <div
        style={{
          position: "absolute",
          right: 106 * k,
          top: 1042 * k,
          fontFamily: MONO,
          fontSize: 11 * k,
          letterSpacing: `${2.2 * k}px`,
          color: INK_CORNER,
          opacity: corner,
        }}
      >
        1920 × 1080
      </div>

      {/* 极轻暗角 */}
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{position: "absolute", inset: 0}}>
        <defs>
          <radialGradient id="fw-vig" cx="50%" cy="48%" r="72%">
            <stop offset="0.55" stopColor="#000000" stopOpacity="0" />
            <stop offset="1" stopColor="#000000" stopOpacity="0.55" />
          </radialGradient>
        </defs>
        <rect width={width} height={height} fill="url(#fw-vig)" opacity={body * 0.8} />
      </svg>
    </AbsoluteFill>
  );
};
