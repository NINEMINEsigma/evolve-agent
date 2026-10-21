import {Player, type PlayerRef} from "@remotion/player";
import {useCallback, useEffect, useRef, useState} from "react";
import {prefetch} from "remotion";
import {ASSETS} from "../src/assets";
import {Promo} from "../src/Promo";
import timing from "../src/timing.json";
import {WEB} from "./config";

const TOTAL = Math.round(timing.duration * timing.fps);
const AUDIO_MODE = timing.audio?.mode ?? "music";
const HAS_AUDIO = AUDIO_MODE !== "silent";
const INPUT = {withAudio: HAS_AUDIO, webMode: true};
type Stage = "poster" | "playing" | "paused" | "ended";

export const App = () => {
  const player = useRef<PlayerRef>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const frameRef = useRef(0);
  const playBaseFrame = useRef(0);
  const playStartedAt = useRef(0);
  const bar = useRef<HTMLDivElement>(null);
  const [stage, setStage] = useState<Stage>("poster");
  const [loaded, setLoaded] = useState(ASSETS.length === 0 ? 1 : 0);

  useEffect(() => {
    if (!ASSETS.length) return;
    let done = 0;
    const jobs = ASSETS.map((asset) => prefetch(`./${asset}`, {method: "blob-url"}));
    jobs.forEach((job) => job.waitUntilDone().finally(() => {done += 1; setLoaded(done / jobs.length);}));
  }, []);

  useEffect(() => {
    if (!HAS_AUDIO) return;
    const element = new Audio("./audio/mix.wav");
    element.preload = "auto";
    audio.current = element;
    const onEnded = () => {frameRef.current = TOTAL - 1; player.current?.seekTo(TOTAL - 1); setStage("ended");};
    element.addEventListener("ended", onEnded);
    return () => {element.pause(); element.removeEventListener("ended", onEnded);};
  }, []);

  useEffect(() => {
    if (stage !== "playing") return;
    let raf = 0;
    const tick = (now: number) => {
      const element = audio.current;
      const next = element
        ? Math.min(TOTAL - 1, Math.floor(element.currentTime * timing.fps))
        : Math.min(TOTAL - 1, playBaseFrame.current + Math.floor((now - playStartedAt.current) * timing.fps / 1000));
      if (next !== frameRef.current) {
        frameRef.current = next;
        player.current?.seekTo(next);
        if (bar.current) bar.current.style.transform = `scaleX(${next / Math.max(1, TOTAL - 1)})`;
      }
      if (!element && next >= TOTAL - 1) {setStage("ended"); return;}
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [stage]);

  const start = useCallback(() => {
    frameRef.current = 0;
    playBaseFrame.current = 0;
    playStartedAt.current = performance.now();
    player.current?.seekTo(0);
    if (audio.current) {audio.current.currentTime = 0; void audio.current.play();}
    setStage("playing");
  }, []);

  const togglePause = useCallback(() => {
    if (stage === "playing") {
      audio.current?.pause();
      playBaseFrame.current = frameRef.current;
      setStage("paused");
    } else if (stage === "paused") {
      playStartedAt.current = performance.now();
      if (audio.current) void audio.current.play();
      setStage("playing");
    }
  }, [stage]);

  const showCta = stage === "poster" || stage === "ended";
  return (
    <main className="page" style={{["--ratio" as string]: `${timing.width} / ${timing.height}`}}>
      <header className={`brand ${showCta ? "" : "brand--hidden"}`}><img src={WEB.logo} alt=""/><span>{WEB.brand}</span></header>
      <div className="stage"><div className="frame" onClick={togglePause}>
        <Player ref={player} component={Promo} inputProps={INPUT} durationInFrames={TOTAL} fps={timing.fps} compositionWidth={timing.width} compositionHeight={timing.height} initialFrame={TOTAL - 1} moveToBeginningWhenEnded={false} controls={false} clickToPlay={false} doubleClickToFullscreen={false} spaceKeyToPlayOrPause={false} numberOfSharedAudioTags={0} acknowledgeRemotionLicense style={{width: "100%", height: "100%"}} />
        {showCta && <div className="cta" onClick={(event) => event.stopPropagation()}><div className="cta__row">
          {stage === "poster" ? <><button className="btn btn--primary" onClick={start} disabled={loaded < 1}>{loaded < 1 ? `加载中 ${Math.round(loaded * 100)}%` : <>▶ 播放 <em>{Math.round(timing.duration)} 秒</em></>}</button><a className="btn btn--ghost" href={WEB.primary.url} target="_blank" rel="noreferrer">{WEB.primary.label}</a></> : <><a className="btn btn--primary" href={WEB.primary.url} target="_blank" rel="noreferrer">{WEB.primary.label}</a><a className="btn btn--ghost" href={WEB.secondary.url} target="_blank" rel="noreferrer">{WEB.secondary.label}</a><button className="btn btn--text" onClick={start}>↺ 重播</button></>}
        </div><div className="cta__note">{stage === "poster" ? WEB.posterNote : WEB.endNote}</div></div>}
        {stage === "paused" && <div className="paused">▶</div>}
        {!showCta && <div className="progress"><div ref={bar}/></div>}
      </div></div>
    </main>
  );
};
