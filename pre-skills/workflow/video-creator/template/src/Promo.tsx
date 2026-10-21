import React from "react";
import {Audio} from "@remotion/media";
import {AbsoluteFill, Html5Audio, staticFile} from "remotion";
import "./lib/fonts";
import {useTime} from "./lib/anim";
import {C} from "./lib/theme";
import timing from "./timing.json";
import {Example} from "./scenes/Example";

export type PromoProps = {withAudio?: boolean; webMode?: boolean};
const audioMode = timing.audio?.mode ?? (timing.voice?.lines?.length ? "voice" : "music");
/** Scenes are deterministic. Audio is optional: silent projects render without an audio asset. */
export const Promo: React.FC<PromoProps> = ({withAudio = true, webMode = false}) => {
  const t = useTime();
  const shouldRenderAudio = withAudio && audioMode !== "silent";
  const audioSrc = webMode ? "./audio/mix.wav" : staticFile("audio/mix.wav");
  return (
    <AbsoluteFill style={{background: C.bg}}>
      <Example t={t} />
      {shouldRenderAudio && (webMode ? <Html5Audio src={audioSrc} /> : <Audio src={audioSrc} />)}
    </AbsoluteFill>
  );
};
