import fs from "node:fs";
import assert from "node:assert/strict";
const root = new URL("..", import.meta.url).pathname.replace(/^\/[A-Za-z]:/, (x) => x.slice(1));
const timing = JSON.parse(fs.readFileSync(new URL("../src/timing.json", import.meta.url), "utf8"));
assert.ok(Number.isFinite(timing.fps) && timing.fps > 0, "fps must be positive");
assert.ok(Number.isFinite(timing.duration) && timing.duration > 0, "duration must be positive");
assert.ok(timing.width > 0 && timing.height > 0, "dimensions must be positive");
const scenes = Object.entries(timing.scenes || {});
assert.ok(scenes.length > 0, "at least one scene is required");
let previous = 0;
for (const [name, span] of scenes) {
  assert.equal(span.length, 2, `${name} must have [start,end]`);
  assert.ok(span[0] >= previous - 1e-6, `${name} overlaps a previous scene`);
  assert.ok(span[1] > span[0], `${name} has non-positive duration`);
  previous = span[1];
}
assert.ok(Math.abs(previous - timing.duration) < 0.05, `last scene ends at ${previous}, duration is ${timing.duration}`);
const subtitles = timing.subtitles || timing.captions || [];
for (const item of subtitles) {
  assert.ok(item.end > item.at, `subtitle ${item.id || "?"} has invalid time`);
  assert.ok(item.at >= -0.01 && item.end <= timing.duration + 0.05, `subtitle ${item.id || "?"} is outside video`);
  assert.ok(String(item.text || "").trim(), `subtitle ${item.id || "?"} is empty`);
}
const mode = timing.audio?.mode || (timing.voice?.lines?.length ? "voice" : "music");
assert.ok(["silent", "music", "voice"].includes(mode), `unknown audio mode: ${mode}`);
console.log(JSON.stringify({pass: true, fps: timing.fps, duration: timing.duration, scenes: scenes.length, subtitles: subtitles.length, audioMode: mode}));
