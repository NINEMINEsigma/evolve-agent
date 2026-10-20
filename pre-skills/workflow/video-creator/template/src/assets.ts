import timing from "./timing.json";

/** Assets the web player prefetches. Silent projects have no audio dependency. */
export const ASSETS = timing.audio?.mode === "silent" ? [] : ["audio/mix.wav"];
