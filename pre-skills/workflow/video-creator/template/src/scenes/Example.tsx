import React from "react";
import {AbsoluteFill} from "remotion";
import timing from "../timing.json";
import {EASE, ramp} from "../lib/anim";
import {C, FONT} from "../lib/theme";

const entries = Object.entries(timing.scenes) as Array<[string, [number, number]]>;

/** Neutral starter scene: replace this component with project-specific scenes after copying template. */
export const Example: React.FC<{t: number}> = ({t}) => {
  const hit = entries.find(([, [start, end]]) => t >= start && t < end);
  if (!hit) return null;
  const [name, [start, end]] = hit;
  const enter = ramp(t, [start, Math.min(start + 0.6, end)]);
  const leave = ramp(t, [Math.max(start, end - 0.3), end], [0, 1], EASE.in);
  return (
    <AbsoluteFill style={{alignItems: "center", justifyContent: "center"}}>
      <div style={{fontFamily: FONT.display, fontSize: 120, color: C.fg, opacity: enter * (1 - leave), transform: `translateY(${(1 - enter) * 40}px) scale(${1 + leave * 0.1})`}}>
        {name}
      </div>
    </AbsoluteFill>
  );
};
