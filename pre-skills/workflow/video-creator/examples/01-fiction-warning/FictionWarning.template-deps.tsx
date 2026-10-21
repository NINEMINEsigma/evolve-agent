import React from "react";
import {AbsoluteFill} from "remotion";
import timing from "../timing.json";
import {EASE, ramp} from "../lib/anim";

/**
 * 场景 01-A：黑屏免责声明
 *
 * 版式取自参考原片 A-0031 的 0–4s 段：中文两行居中、英文两行小字在下、
 * 左下角机读编号、右下角分辨率、左上角一个小红点，全部淡入后于段尾淡出。
 */

const W = timing.width;
const H = timing.height;

const ZH = [
  "本片所包含的时间、地点、人物及其他内容均为虚构",
  "与真实人物、机构或事件无关。如有雷同，纯属巧合。",
];
const EN = [
  "All times, places, persons and other content in this film are fictional and",
  "have no connection to real persons, institutions or events. Any similarity is coincidental.",
];

const ZH_FONT = '"PF", "PingFang SC", "Microsoft YaHei", sans-serif';
const MONO = '"TechMono", Consolas, "Courier New", monospace';

const INK_ZH = "#b9b9bc";
const INK_EN = "#6c6c70";
const INK_CORNER = "#3c3c40";

export const FictionWarning: React.FC<{t: number}> = ({t}) => {
  const [start, end] = timing.scenes.open;
  const dur = end - start;
  if (t < start || t >= end) return null;

  const lt = t - start;
  const fadeOut = ramp(lt, [dur - 0.5, dur - 0.04], [0, 1], EASE.in);
  const body = Math.min(ramp(lt, [0.22, 1.05]), 1 - fadeOut);
  const corner = Math.min(ramp(lt, [0.85, 1.55]), 1 - fadeOut);

  return (
    <AbsoluteFill style={{background: "#000000"}}>
      {/* 左上角红色标记点 */}
      <div
        style={{
          position: "absolute",
          left: 116,
          top: 64,
          width: 7,
          height: 7,
          background: "#6e1119",
          opacity: corner * 0.9,
        }}
      />

      {/* 中文声明 */}
      <div style={{position: "absolute", left: 0, top: 446, width: W, textAlign: "center"}}>
        {ZH.map((line) => (
          <div
            key={line}
            style={{
              fontFamily: ZH_FONT,
              fontSize: 19,
              letterSpacing: "2.6px",
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
      <div style={{position: "absolute", left: 0, top: 588, width: W, textAlign: "center"}}>
        {EN.map((line) => (
          <div
            key={line}
            style={{
              fontFamily: MONO,
              fontSize: 12.5,
              letterSpacing: "0.4px",
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
          left: 104,
          top: 1042,
          fontFamily: MONO,
          fontSize: 11,
          letterSpacing: "2.2px",
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
          right: 106,
          top: 1042,
          fontFamily: MONO,
          fontSize: 11,
          letterSpacing: "2.2px",
          color: INK_CORNER,
          opacity: corner,
        }}
      >
        1920 × 1080
      </div>

      {/* 极轻的暗角，避免纯黑过平 */}
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{position: "absolute", inset: 0}}>
        <defs>
          <radialGradient id="fw-vig" cx="50%" cy="48%" r="72%">
            <stop offset="0.55" stopColor="#000000" stopOpacity="0" />
            <stop offset="1" stopColor="#000000" stopOpacity="0.55" />
          </radialGradient>
        </defs>
        <rect width={W} height={H} fill="url(#fw-vig)" opacity={body * 0.8} />
      </svg>
    </AbsoluteFill>
  );
};
