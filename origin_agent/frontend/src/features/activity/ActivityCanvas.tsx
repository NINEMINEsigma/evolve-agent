import { useEffect, useRef } from "react";
import type { ActivityEvent } from "./types";

interface ActivityCanvasProps {
  events: ActivityEvent[];
  reducedMotion?: boolean;
}

interface HaloGeometry {
  width: number;
  height: number;
  dpr: number;
  cx: number;
  cy: number;
  radius: number;
  outerRadius: number;
  maxRadius: number;
  visibleHalfAngle: number;
}

interface RenderQuality {
  outerGroupCount: number;
  pulseShadowBlur: number;
}

interface DataSlot {
  angle: number;
  height: number;
  seed: number;
  contentSeed: number;
  flash: number;
  flashColor: string;
  motionPhase: number;
  motionSpeed: number;
  nextRefreshAt: number;
  transitionStartedAt: number;
  previousCanvas: HTMLCanvasElement | null;
  canvas: HTMLCanvasElement;
}

interface AmbientStream {
  angle: number;
  startRadius: number;
  travel: number;
  length: number;
  speed: number;
  phase: number;
  alpha: number;
  width: number;
  brightnessPhase: number;
  brightnessSpeed: number;
}

interface SlotRefreshState {
  lastRefreshAt: number;
  cursor: number;
}

interface InnerStreamLine {
  originRadius: number;
  originAngle: number;
  controlRadius: number;
  controlAngle: number;
  targetRadius: number;
  targetAngle: number;
}

interface HaloPulse {
  born: number;
  life: number;
  angle: number;
  width: number;
  color: string;
  energy: number;
  innerLines: InnerStreamLine[];
}

const COLORS: Record<ActivityEvent["kind"], string> = {
  message_received: "#98e0cf",
  agent_response: "#f4f5f7",
  tool_call: "#f0a6c6",
};

const DATA_LABELS = ["LOAD", "CFL", "REF", "METHOD", "CHECK", "RESIDUAL", "PAPER", "QUEUE", "TRACE", "DIFF"];
const DATA_KEYS = ["dt", "nu", "Re", "tol", "L2", "mass", "grid", "seed"];
const DATA_WORDS = ["READ", "BUILD", "REVIEW", "SYNC", "DIFF", "PASS", "TRACE", "PUSH"];
const SLOT_REFRESH_INTERVAL_MS = 360;

function eventColor(event: ActivityEvent): string {
  return COLORS[event.kind];
}

function hash(value: number): number {
  const x = Math.sin(value * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}

function geometryFor(width: number, height: number, dpr: number): HaloGeometry {
  const cx = width * 0.07;
  const cy = height * 0.5;
  const radius = Math.max(height * 0.78, width * 0.3);
  const band = Math.max(90, Math.min(240, height * 0.3, width * 0.13)) * 1.3;
  const outerRadius = radius + band;
  return {
    width,
    height,
    dpr,
    cx,
    cy,
    radius,
    outerRadius,
    maxRadius: Math.hypot(width - cx, height / 2) + 60,
    visibleHalfAngle: Math.asin(Math.min(1, (height / 2 + 40) / outerRadius)),
  };
}

function rotationFor(now: number): { inner: number; disk: number; outer: number; burst: number } {
  const seconds = now / 1000;
  const burstPhase = seconds % 8.4;
  const burst = burstPhase < 0.72
    ? Math.sin((burstPhase / 0.72) * Math.PI)
    : 0;
  const slowInner = seconds * 0.007;
  const slowDisk = seconds * 0.012 + burst * 0.42;
  return {
    inner: slowInner,
    disk: slowDisk,
    outer: slowDisk + burst * 0.2,
    burst,
  };
}

function clampCamera(geometry: HaloGeometry, camera: { x: number; y: number; z: number }): { x: number; y: number; z: number } {
  const halfWidth = geometry.width / (2 * camera.z);
  const halfHeight = geometry.height / (2 * camera.z);
  return {
    x: Math.max(halfWidth, Math.min(geometry.width - halfWidth, camera.x)),
    y: Math.max(halfHeight, Math.min(geometry.height - halfHeight, camera.y)),
    z: camera.z,
  };
}

function cameraFor(geometry: HaloGeometry, now: number): { x: number; y: number; z: number } {
  const middle = (geometry.radius + geometry.outerRadius) / 2;
  const point = (angle: number, distance: number) => ({
    x: geometry.cx + Math.cos(angle) * distance,
    y: geometry.cy + Math.sin(angle) * distance,
  });
  const shots = [
    { x: geometry.width / 2, y: geometry.height / 2, z: 1, hold: 4.5 },
    { ...point(-geometry.visibleHalfAngle * 0.45, middle), z: 1.8, hold: 3.4 },
    { ...point(0.04, geometry.outerRadius + (geometry.maxRadius - geometry.outerRadius) * 0.28), z: 1.35, hold: 3.2 },
    { x: geometry.width / 2, y: geometry.height / 2, z: 1, hold: 3.2 },
    { ...point(0.22, geometry.radius * 0.8), z: 1.55, hold: 3.4 },
  ];
  const moveDuration = 1.8;
  const cycle = shots.reduce((sum, shot) => sum + shot.hold + moveDuration, 0);
  let time = (now / 1000) % cycle;
  for (let index = 0; index < shots.length; index += 1) {
    const current = shots[index];
    const next = shots[(index + 1) % shots.length];
    if (time < current.hold) {
      const breathe = current.z > 1 ? Math.sin((time / current.hold) * Math.PI) * 5 : 0;
      return clampCamera(geometry, { x: current.x, y: current.y + breathe, z: current.z });
    }
    time -= current.hold;
    if (time < moveDuration) {
      const raw = Math.min(1, time / moveDuration);
      const eased = raw < 0.5 ? 4 * raw * raw * raw : 1 - Math.pow(-2 * raw + 2, 3) / 2;
      const logZoom = Math.log(current.z) + (Math.log(next.z) - Math.log(current.z)) * eased;
      return clampCamera(geometry, {
        x: current.x + (next.x - current.x) * eased,
        y: current.y + (next.y - current.y) * eased,
        z: Math.exp(logZoom),
      });
    }
    time -= moveDuration;
  }
  return clampCamera(geometry, { x: geometry.width / 2, y: geometry.height / 2, z: 1 });
}

function renderQualityFor(geometry: HaloGeometry, zoom: number): RenderQuality {
  const baseOuterGroupCount = Math.min(700, Math.round(260 + geometry.width * 0.15));
  const density = zoom >= 1.55 ? 0.34 : zoom >= 1.28 ? 0.56 : 1;
  return {
    outerGroupCount: Math.max(120, Math.round(baseOuterGroupCount * density)),
    pulseShadowBlur: zoom >= 1.28 ? 0 : 20,
  };
}

function applyCamera(context: CanvasRenderingContext2D, geometry: HaloGeometry, camera: { x: number; y: number; z: number }): void {
  context.translate(geometry.width / 2, geometry.height / 2);
  context.scale(camera.z, camera.z);
  context.translate(-camera.x, -camera.y);
}

function wrappedAngleDistance(first: number, second: number): number {
  return ((first - second + Math.PI) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2) - Math.PI;
}

function pulseEnergyAt(angle: number, pulses: HaloPulse[], now: number): number {
  let energy = 0;
  for (const pulse of pulses) {
    const progress = Math.min(1, (now - pulse.born) / pulse.life);
    if (progress >= 1) continue;
    const distance = Math.abs(wrappedAngleDistance(angle, pulse.angle));
    energy += (1 - progress) * pulse.energy * Math.exp(-((distance / Math.max(0.012, pulse.width)) ** 2));
  }
  return Math.min(1, energy);
}

function selectPulseTarget(
  geometry: HaloGeometry | null,
  pulses: HaloPulse[],
  now: number,
  sequence: number,
): { angle: number; width: number } {
  const visibleHalfAngle = geometry?.visibleHalfAngle ?? 0.42;
  const width = Math.min(0.1, Math.max(0.028, visibleHalfAngle * 0.18));
  const preferredHalfAngle = visibleHalfAngle * 0.45;
  const preferredCandidates = Array.from({ length: 9 }, (_, index) => {
    const ratio = index / 8;
    return -preferredHalfAngle + ratio * preferredHalfAngle * 2;
  });
  const visibleCandidates = Array.from({ length: 17 }, (_, index) => {
    const ratio = index / 16;
    return -visibleHalfAngle * 0.94 + ratio * visibleHalfAngle * 1.88;
  });
  const activePulses = pulses.filter((pulse) => now - pulse.born < pulse.life);
  const occupancy = (candidate: number): number => activePulses.filter(
    (pulse) => Math.abs(wrappedAngleDistance(candidate, pulse.angle)) < width * 1.6,
  ).length;
  const selectFrom = (candidates: number[], maxOccupancy: number | null): number | null => {
    const scored = candidates.map((candidate, index) => ({
      candidate,
      index,
      count: occupancy(candidate),
    }));
    const minimum = Math.min(...scored.map((item) => item.count));
    const available = maxOccupancy === null
      ? scored.filter((item) => item.count === minimum)
      : scored.filter((item) => item.count < maxOccupancy);
    if (available.length === 0) return null;
    const lowestCount = Math.min(...available.map((item) => item.count));
    const tied = available.filter((item) => item.count === lowestCount);
    return tied[Math.floor(hash(sequence * 79.1) * tied.length)].candidate;
  };

  const preferred = selectFrom(preferredCandidates, 2);
  if (preferred !== null) return { angle: preferred, width };
  const visible = selectFrom(visibleCandidates, null);
  if (visible === null) throw new Error("Activity pulse target selection produced no visible arc");
  return { angle: visible, width };
}

function buildOuterField(geometry: HaloGeometry): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.ceil(geometry.width * geometry.dpr));
  canvas.height = Math.max(1, Math.ceil(geometry.height * geometry.dpr));
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Activity outer field canvas is unavailable");
  context.setTransform(geometry.dpr, 0, 0, geometry.dpr, 0, 0);
  const span = geometry.maxRadius - geometry.outerRadius - 18;
  const groupCount = Math.min(520, Math.round(220 + geometry.width * 0.12));
  context.globalCompositeOperation = "lighter";
  context.lineCap = "butt";
  for (let group = 0; group < groupCount; group += 1) {
    const center = hash(group * 53.1) * Math.PI * 2;
    const count = 2 + Math.floor(hash(group * 54.3) * 8);
    const groupWidth = 0.004 + hash(group * 55.5) * 0.03;
    for (let line = 0; line < count; line += 1) {
      const angle = center + (line / Math.max(1, count - 1) - 0.5) * groupWidth;
      const length = span * (0.12 + hash(group * 57.7 + line) * 0.82);
      const solid = length * (0.28 + hash(group * 58.9 + line) * 0.52);
      const alpha = 0.012 + hash(group * 60.1 + line) * 0.035;
      const tint = hash(group * 62.5 + line) < 0.18
        ? "240,166,198"
        : hash(group * 63.7 + line) < 0.38
          ? "196,184,246"
          : "232,235,242";
      context.strokeStyle = `rgba(${tint},${alpha})`;
      context.lineWidth = 0.45 + hash(group * 64.9 + line) * 0.55;
      context.beginPath();
      context.moveTo(geometry.cx + Math.cos(angle) * (geometry.outerRadius + 3), geometry.cy + Math.sin(angle) * (geometry.outerRadius + 3));
      context.lineTo(geometry.cx + Math.cos(angle) * (geometry.outerRadius + 3 + solid), geometry.cy + Math.sin(angle) * (geometry.outerRadius + 3 + solid));
      context.stroke();
    }
  }
  return canvas;
}

function drawOuterStrands(
  context: CanvasRenderingContext2D,
  geometry: HaloGeometry,
  pulses: HaloPulse[],
  now: number,
  rotation: number,
  quality: RenderQuality,
  field: HTMLCanvasElement | null,
): void {
  if (field) {
    context.save();
    context.translate(geometry.cx, geometry.cy);
    context.rotate(rotation);
    context.translate(-geometry.cx, -geometry.cy);
    context.globalCompositeOperation = "lighter";
    context.drawImage(field, 0, 0, geometry.width, geometry.height);
    context.restore();
  }

  const span = geometry.maxRadius - geometry.outerRadius - 18;
  const groupCount = Math.max(24, Math.round(quality.outerGroupCount * 0.18));
  context.save();
  context.globalCompositeOperation = "lighter";
  context.lineCap = "butt";
  for (let group = 0; group < groupCount; group += 1) {
    const center = hash(group * 53.1) * Math.PI * 2 + rotation;
    const visibleCenter = Math.atan2(Math.sin(center), Math.cos(center));
    const activity = pulseEnergyAt(visibleCenter, pulses, now);
    if (activity <= 0.02) continue;
    const count = 2 + Math.floor(hash(group * 54.3) * 8);
    const groupWidth = 0.004 + hash(group * 55.5) * 0.03;
    for (let line = 0; line < count; line += 1) {
      const angle = center + (line / Math.max(1, count - 1) - 0.5) * groupWidth;
      const length = span * (0.12 + hash(group * 57.7 + line) * 0.82);
      const solid = length * (0.28 + hash(group * 58.9 + line) * 0.52);
      if (length - solid <= 8) continue;
      const alpha = activity * (0.18 + hash(group * 61.3 + line) * 0.3);
      const phase = (now * (0.0004 + hash(group * 66.1 + line) * 0.0008) + hash(group * 67.3 + line)) % 1;
      const dashStart = geometry.outerRadius + 3 + solid + (length - solid) * phase;
      const dashEnd = Math.min(geometry.outerRadius + 3 + length, dashStart + 3 + (length - solid) * 0.16);
      context.strokeStyle = `rgba(232,235,242,${Math.min(0.9, alpha * 2.8)})`;
      context.lineWidth = 0.45 + hash(group * 64.9 + line) * 0.8;
      context.beginPath();
      context.moveTo(geometry.cx + Math.cos(angle) * dashStart, geometry.cy + Math.sin(angle) * dashStart);
      context.lineTo(geometry.cx + Math.cos(angle) * dashEnd, geometry.cy + Math.sin(angle) * dashEnd);
      context.stroke();
    }
  }
  context.restore();
}

function slotValue(seed: number, index: number): number {
  return hash(seed * 17.31 + index * 41.17);
}

function slotTint(seed: number, index: number): string {
  const value = slotValue(seed, index);
  if (value < 0.12) return "196,184,246";
  if (value < 0.2) return "168,222,214";
  if (value < 0.25) return "240,166,198";
  return "232,234,240";
}

function drawSlotHeader(
  context: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  y: number,
  seed: number,
): number {
  const tint = slotTint(seed, 2);
  context.font = "700 4.3px ui-monospace, Consolas, monospace";
  context.fillStyle = `rgba(${tint},.95)`;
  context.fillText(DATA_LABELS[seed % DATA_LABELS.length], x0, y);
  context.fillStyle = `rgba(${tint},.55)`;
  context.textAlign = "right";
  context.fillText(String(Math.floor(slotValue(seed, 3) * 99)).padStart(2, "0"), x1, y);
  context.textAlign = "left";
  context.fillStyle = `rgba(${tint},.32)`;
  context.fillRect(x0, y + 5.6, x1 - x0, 0.45);
  return y + 7.5;
}

function drawSlotCode(
  context: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  y0: number,
  y1: number,
  seed: number,
): void {
  let y = drawSlotHeader(context, x0, x1, y0, seed);
  const words = ["map", "step", "solve", "emit", "read", "merge", "check", "clip"];
  context.font = "500 3.5px ui-monospace, Consolas, monospace";
  let row = 0;
  while (y < y1 - 3.5) {
    context.fillStyle = `rgba(232,234,240,${0.3 + slotValue(seed, row + 8) * 0.25})`;
    context.fillText(String(1 + Math.floor(slotValue(seed, row + 9) * 40)).padStart(3, "0"), x0, y);
    let x = x0 + 9;
    const count = 1 + Math.floor(slotValue(seed, row + 10) * 3);
    for (let index = 0; index < count && x < x1 - 4; index += 1) {
      const word = words[(seed + row + index) % words.length];
      context.fillStyle = `rgba(${slotTint(seed, row + index + 11)},${0.55 + slotValue(seed, row + index + 12) * 0.4})`;
      context.fillText(word, x, y);
      x += word.length * 2.15 + 2;
    }
    y += 4.6;
    row += 1;
  }
}

function drawSlotKeyValues(
  context: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  y0: number,
  y1: number,
  seed: number,
): void {
  let y = y1 - y0 > 18 ? drawSlotHeader(context, x0, x1, y0, seed) : y0 + 1;
  context.font = "500 3.6px ui-monospace, Consolas, monospace";
  let row = 0;
  while (y < y1 - 4) {
    const key = DATA_KEYS[(seed + row) % DATA_KEYS.length];
    const value = slotValue(seed, row + 20);
    context.fillStyle = `rgba(232,234,240,.58)`;
    context.fillText(key, x0, y);
    context.fillStyle = `rgba(${slotTint(seed, row + 21)},.95)`;
    context.textAlign = "right";
    context.fillText(value < 0.35 ? value.toFixed(3) : `${Math.floor(value * 999)}`, x1, y);
    context.textAlign = "left";
    const barX = x0 + 14;
    const barWidth = Math.max(0, x1 - barX - 17);
    context.fillStyle = "rgba(232,234,240,.14)";
    context.fillRect(barX, y + 1.2, barWidth, 1.2);
    context.fillStyle = `rgba(${slotTint(seed, row + 22)},.72)`;
    context.fillRect(barX, y + 1.2, barWidth * value, 1.2);
    y += 5.2;
    row += 1;
  }
}

function drawSlotSparkline(
  context: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  y0: number,
  y1: number,
  seed: number,
): void {
  const y = drawSlotHeader(context, x0, x1, y0, seed);
  const top = y + 1;
  const bottom = y1 - 2;
  context.fillStyle = "rgba(232,234,240,.18)";
  context.fillRect(x0, bottom, x1 - x0, 0.4);
  context.fillRect(x0, (top + bottom) / 2, x1 - x0, 0.25);
  context.strokeStyle = `rgba(${slotTint(seed, 31)},.95)`;
  context.lineWidth = 0.55;
  context.beginPath();
  const pointCount = Math.max(8, Math.floor((x1 - x0) / 2));
  for (let index = 0; index <= pointCount; index += 1) {
    const x = x0 + (x1 - x0) * index / pointCount;
    const value = 0.5 + Math.sin(index * (0.45 + slotValue(seed, 32) * 0.35) + seed) * 0.3 + (slotValue(seed, index + 33) - 0.5) * 0.18;
    const yPoint = bottom - Math.max(0, Math.min(1, value)) * (bottom - top);
    if (index === 0) context.moveTo(x, yPoint);
    else context.lineTo(x, yPoint);
  }
  context.stroke();
}

function drawSlotBars(
  context: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  y0: number,
  y1: number,
  seed: number,
): void {
  const y = drawSlotHeader(context, x0, x1, y0, seed);
  const count = Math.max(3, Math.floor((y1 - y) / 4));
  const height = Math.max(1, (y1 - y - 1) / count);
  context.font = "500 3px ui-monospace, Consolas, monospace";
  for (let index = 0; index < count; index += 1) {
    const rowY = y + index * height;
    const value = 0.1 + slotValue(seed, index + 42) * 0.9;
    context.fillStyle = "rgba(232,234,240,.38)";
    context.fillText(String(index).padStart(2, "0"), x0, rowY);
    context.fillStyle = `rgba(${slotTint(seed, index + 43)},${value > 0.82 ? 1 : 0.68})`;
    context.fillRect(x0 + 7, rowY + 0.4, (x1 - x0 - 7) * value, Math.max(0.8, height - 1.2));
  }
}

function drawSlotProgress(
  context: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  y0: number,
  y1: number,
  seed: number,
): void {
  let y = y1 - y0 > 18 ? drawSlotHeader(context, x0, x1, y0, seed) : y0 + 1;
  context.font = "500 3.4px ui-monospace, Consolas, monospace";
  let row = 0;
  while (y < y1 - 5) {
    const value = slotValue(seed, row + 51);
    context.fillStyle = `rgba(${slotTint(seed, row + 52)},.62)`;
    context.fillText(DATA_WORDS[(seed + row) % DATA_WORDS.length], x0, y);
    context.fillStyle = "rgba(232,234,240,.95)";
    context.textAlign = "right";
    context.fillText(`${Math.floor(value * 100)}%`, x1, y);
    context.textAlign = "left";
    const barX = x0 + 15;
    const barWidth = Math.max(0, x1 - x0 - 26);
    for (let segment = 0; segment < 10; segment += 1) {
      context.fillStyle = segment / 10 < value ? `rgba(${slotTint(seed, row + 53)},.82)` : "rgba(232,234,240,.14)";
      context.fillRect(barX + segment * barWidth / 10, y + 0.6, barWidth / 10 - 0.6, 2);
    }
    y += 5.4;
    row += 1;
  }
}

function drawSlotGrid(
  context: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  y0: number,
  y1: number,
  seed: number,
): void {
  const y = y1 - y0 > 20 ? drawSlotHeader(context, x0, x1, y0, seed) : y0 + 1;
  const size = 2.7;
  for (let yy = y; yy < y1 - size; yy += size) {
    for (let xx = x0; xx < x1 - size; xx += size) {
      const value = slotValue(seed, Math.floor(xx * 3 + yy * 7));
      context.fillStyle = value > 0.92
        ? "rgba(240,166,198,.95)"
        : `rgba(${slotTint(seed, Math.floor(xx + yy) + 61)},${0.08 + value * value * 0.8})`;
      context.fillRect(xx, yy, size - 0.6, size - 0.6);
    }
  }
}

function drawSlotGauge(
  context: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  y0: number,
  y1: number,
  seed: number,
): void {
  const radius = Math.min((y1 - y0) / 2 - 1.5, 9);
  const centerX = x0 + radius + 1;
  const centerY = (y0 + y1) / 2;
  const value = slotValue(seed, 71);
  context.lineWidth = 1.2;
  context.strokeStyle = "rgba(232,234,240,.18)";
  context.beginPath();
  context.arc(centerX, centerY, radius, 0, Math.PI * 2);
  context.stroke();
  context.strokeStyle = `rgba(${slotTint(seed, 72)},.95)`;
  context.beginPath();
  context.arc(centerX, centerY, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * value);
  context.stroke();
  context.font = `${Math.max(3.2, radius * 0.55)}px ui-monospace, Consolas, monospace`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillStyle = "rgba(232,234,240,.92)";
  context.fillText(`${Math.floor(value * 100)}`, centerX, centerY);
  context.textAlign = "left";
  context.textBaseline = "top";
  if (x1 - (centerX + radius) > 20) drawSlotKeyValues(context, centerX + radius + 4, x1, y0, y1, seed + 1);
}

function drawSlotWave(
  context: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  y0: number,
  y1: number,
  seed: number,
): void {
  const y = drawSlotHeader(context, x0, x1, y0, seed);
  const middle = (y + y1) / 2;
  const amplitude = (y1 - y) * 0.38;
  for (const [alpha, factor] of [[0.95, 1], [0.4, -0.6]] as const) {
    context.strokeStyle = `rgba(${slotTint(seed, 81)},${alpha})`;
    context.lineWidth = 0.5;
    context.beginPath();
    for (let x = x0; x <= x1; x += 0.8) {
      const wave = Math.sin(x * (0.15 + slotValue(seed, 82) * 0.25) + seed) * 0.7
        + Math.sin(x * (0.5 + slotValue(seed, 83) * 0.7)) * 0.3;
      const waveY = middle + amplitude * factor * wave;
      if (x === x0) context.moveTo(x, waveY);
      else context.lineTo(x, waveY);
    }
    context.stroke();
  }
}

function drawSlotMatrix(
  context: CanvasRenderingContext2D,
  x0: number,
  x1: number,
  y0: number,
  y1: number,
  seed: number,
): void {
  const size = 2.3;
  for (let y = y0; y < y1 - 1; y += size) {
    for (let x = x0; x < x1; x += size) {
      const value = slotValue(seed, Math.floor(x * 5 + y * 11));
      if (value < 0.42) continue;
      context.fillStyle = `rgba(${slotTint(seed, Math.floor(x + y) + 91)},${0.45 + value * 0.5})`;
      context.fillRect(x, y, 1.4, 1.4);
    }
  }
}

function buildDataSlotCanvas(geometry: HaloGeometry, height: number, seed: number): HTMLCanvasElement {
  const band = geometry.outerRadius - geometry.radius;
  const slotHeight = height + 2;
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.ceil(band * geometry.dpr));
  canvas.height = Math.max(1, Math.ceil(slotHeight * geometry.dpr));
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Activity data slot canvas is unavailable");
  context.setTransform(geometry.dpr, 0, 0, geometry.dpr, 0, 0);
  context.textBaseline = "top";
  context.strokeStyle = "rgba(232,234,240,.72)";
  context.lineWidth = 0.5;
  context.strokeRect(0.25, 0.25, band - 0.5, slotHeight - 0.5);

  const contentX = 5;
  const contentEnd = band * 0.73;
  context.save();
  context.beginPath();
  context.rect(contentX, 1, Math.max(0, contentEnd - contentX), Math.max(0, height));
  context.clip();
  const variant = seed % 11;
  if (variant === 0 || variant === 1) drawSlotCode(context, contentX, contentEnd, 1, height + 1, seed);
  else if (variant === 2 || variant === 3) drawSlotKeyValues(context, contentX, contentEnd, 1, height + 1, seed);
  else if (variant === 4) drawSlotSparkline(context, contentX, contentEnd, 1, height + 1, seed);
  else if (variant === 5) drawSlotBars(context, contentX, contentEnd, 1, height + 1, seed);
  else if (variant === 6) drawSlotProgress(context, contentX, contentEnd, 1, height + 1, seed);
  else if (variant === 7) drawSlotGrid(context, contentX, contentEnd, 1, height + 1, seed);
  else if (variant === 8) drawSlotGauge(context, contentX, contentEnd, 1, height + 1, seed);
  else if (variant === 9) drawSlotMatrix(context, contentX, contentEnd, 1, height + 1, seed);
  else drawSlotWave(context, contentX, contentEnd, 1, height + 1, seed);
  context.restore();

  // The outer index rail is intentionally dense: it gives the rotating disk a physical measurement scale.
  context.font = "500 3.1px ui-monospace, Consolas, monospace";
  for (let row = 0; row < Math.max(2, Math.floor(height / 7)); row += 1) {
    const y = 3 + row * 7;
    const index = Math.floor(slotValue(seed, row + 101) * 999).toString().padStart(3, "0");
    context.fillStyle = `rgba(225,228,236,${0.55 + slotValue(seed, row + 102) * 0.35})`;
    context.fillText(index, band * 0.78, y);
    let x = band * 0.78 + 9;
    const marks = 1 + Math.floor(slotValue(seed, row + 103) * 3);
    for (let mark = 0; mark < marks && x < band - 3; mark += 1) {
      context.fillRect(x, y + 1, 1.2 + slotValue(seed, row + mark + 104) * 1.2, 1.2);
      x += 2.6 + slotValue(seed, row + mark + 105) * 1.4;
    }
  }

  context.fillStyle = `rgba(${slotTint(seed, 110)},.7)`;
  for (let x = contentX; x < band * 0.76; x += 3 + slotValue(seed, Math.floor(x) + 111) * 2) {
    context.fillRect(x, height + 0.5, 1.1, 1.1);
  }
  return canvas;
}

function buildAmbientStreams(): AmbientStream[] {
  return Array.from({ length: 56 }, (_, index) => ({
    angle: hash(index * 91.1) * Math.PI * 2,
    startRadius: 0.08 + hash(index * 92.3) * 0.58,
    travel: 0.24 + hash(index * 93.5) * 0.62,
    length: 0.08 + hash(index * 94.7) * 0.18,
    speed: 0.00022 + hash(index * 95.9) * 0.00042,
    phase: hash(index * 97.1),
    alpha: 0.12 + hash(index * 98.3) * 0.18,
    width: 0.65 + hash(index * 99.5) * 0.65,
    brightnessPhase: hash(index * 100.7) * Math.PI * 2,
    brightnessSpeed: 0.00012 + hash(index * 101.9) * 0.00024,
  }));
}

function buildInnerField(geometry: HaloGeometry): HTMLCanvasElement {
  const radius = geometry.radius;
  const size = radius * 2;
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.ceil(size * geometry.dpr));
  canvas.height = Math.max(1, Math.ceil(size * geometry.dpr));
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Activity inner field canvas is unavailable");
  context.setTransform(geometry.dpr, 0, 0, geometry.dpr, 0, 0);
  context.save();
  context.beginPath();
  context.arc(radius, radius, radius, 0, Math.PI * 2);
  context.clip();
  const gradient = context.createRadialGradient(radius, radius, radius * 0.1, radius, radius, radius);
  gradient.addColorStop(0, "#111215");
  gradient.addColorStop(1, "#0c0d0f");
  context.fillStyle = gradient;
  context.fillRect(0, 0, size, size);

  const curveCount = Math.min(720, Math.round(360 + geometry.width * geometry.height / 2200));
  for (let index = 0; index < curveCount; index += 1) {
    const startAngle = hash(index * 2.1) * Math.PI * 2;
    const endAngle = startAngle + 0.6 + hash(index * 3.7) * Math.PI * 1.2;
    const startRadius = Math.sqrt(hash(index * 5.2)) * radius;
    const endRadius = Math.sqrt(hash(index * 6.4)) * radius;
    const controlRadius = Math.sqrt(hash(index * 8.1)) * radius * 0.85;
    const controlAngle = hash(index * 9.3) * Math.PI * 2;
    const tint = hash(index * 10.2) < 0.05
      ? "240,166,198"
      : hash(index * 11.4) < 0.12
        ? "196,184,246"
        : "228,231,238";
    context.strokeStyle = `rgba(${tint},${0.025 + hash(index * 12.6) * 0.2})`;
    context.lineWidth = 0.4 + hash(index * 13.8) * 0.7;
    context.beginPath();
    context.moveTo(radius + Math.cos(startAngle) * startRadius, radius + Math.sin(startAngle) * startRadius);
    context.quadraticCurveTo(
      radius + Math.cos(controlAngle) * controlRadius,
      radius + Math.sin(controlAngle) * controlRadius,
      radius + Math.cos(endAngle) * endRadius,
      radius + Math.sin(endAngle) * endRadius,
    );
    context.stroke();
  }

  context.strokeStyle = "rgba(235,238,244,.55)";
  context.lineWidth = 0.8;
  for (let index = 0; index < 52; index += 1) {
    const angle = hash(index * 17.1) * Math.PI * 2;
    const distance = Math.sqrt(hash(index * 18.3)) * radius * 0.92;
    const x = radius + Math.cos(angle) * distance;
    const y = radius + Math.sin(angle) * distance;
    const sizeHint = 2 + hash(index * 19.5) * 3;
    context.beginPath();
    context.arc(x, y, sizeHint, 0, Math.PI * 2);
    context.stroke();
  }
  context.restore();

  // Force alpha to zero outside the circular cache, independent of source content.
  context.globalCompositeOperation = "destination-in";
  context.beginPath();
  context.arc(radius, radius, radius, 0, Math.PI * 2);
  context.fillStyle = "#ffffff";
  context.fill();
  context.globalCompositeOperation = "source-over";
  return canvas;
}

function buildField(geometry: HaloGeometry): { canvas: HTMLCanvasElement; slots: DataSlot[]; ambientStreams: AmbientStream[] } {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.ceil(geometry.width * geometry.dpr));
  canvas.height = Math.max(1, Math.ceil(geometry.height * geometry.dpr));
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Activity field canvas is unavailable");
  context.setTransform(geometry.dpr, 0, 0, geometry.dpr, 0, 0);

  context.save();
  context.beginPath();
  context.arc(geometry.cx, geometry.cy, geometry.radius, 0, Math.PI * 2);
  context.clip();
  const webGradient = context.createRadialGradient(
    geometry.cx, geometry.cy, geometry.radius * 0.1,
    geometry.cx, geometry.cy, geometry.radius,
  );
  webGradient.addColorStop(0, "#111215");
  webGradient.addColorStop(1, "#0c0d0f");
  context.fillStyle = webGradient;
  context.fillRect(0, 0, geometry.width, geometry.height);

  const curveCount = Math.min(720, Math.round(360 + geometry.width * geometry.height / 2200));
  for (let index = 0; index < curveCount; index += 1) {
    const startAngle = hash(index * 2.1) * Math.PI * 2;
    const endAngle = startAngle + 0.6 + hash(index * 3.7) * Math.PI * 1.2;
    const startRadius = Math.sqrt(hash(index * 5.2)) * geometry.radius;
    const endRadius = Math.sqrt(hash(index * 6.4)) * geometry.radius;
    const controlRadius = Math.sqrt(hash(index * 8.1)) * geometry.radius * 0.85;
    const controlAngle = hash(index * 9.3) * Math.PI * 2;
    const x0 = geometry.cx + Math.cos(startAngle) * startRadius;
    const y0 = geometry.cy + Math.sin(startAngle) * startRadius;
    const x1 = geometry.cx + Math.cos(endAngle) * endRadius;
    const y1 = geometry.cy + Math.sin(endAngle) * endRadius;
    const controlX = geometry.cx + Math.cos(controlAngle) * controlRadius;
    const controlY = geometry.cy + Math.sin(controlAngle) * controlRadius;
    const tint = hash(index * 10.2) < 0.05 ? "240,166,198" : hash(index * 11.4) < 0.12 ? "196,184,246" : "228,231,238";
    const alpha = 0.025 + hash(index * 12.6) * 0.2;
    context.strokeStyle = `rgba(${tint},${alpha})`;
    context.lineWidth = 0.4 + hash(index * 13.8) * 0.7;
    context.beginPath();
    context.moveTo(x0, y0);
    context.quadraticCurveTo(controlX, controlY, x1, y1);
    context.stroke();
  }

  context.font = "6px ui-monospace, Consolas, monospace";
  context.textBaseline = "middle";
  for (let index = 0; index < 70; index += 1) {
    const angle = hash(index * 17.1) * Math.PI * 2;
    const distance = Math.sqrt(hash(index * 18.3)) * geometry.radius * 0.92;
    const x = geometry.cx + Math.cos(angle) * distance;
    const y = geometry.cy + Math.sin(angle) * distance;
    const size = 2 + hash(index * 19.5) * 3;
    context.strokeStyle = `rgba(235,238,244,${0.3 + hash(index * 20.7) * 0.45})`;
    context.lineWidth = 0.8;
    context.beginPath();
    context.arc(x, y, size, 0, Math.PI * 2);
    context.stroke();
    if (hash(index * 21.9) < 0.35) {
      context.fillStyle = "rgba(200,204,212,.45)";
      context.fillText(`n${Math.floor(hash(index * 23.1) * 99)}`, x + 7, y);
    }
  }
  context.restore();

  const slots: DataSlot[] = [];
  const band = geometry.outerRadius - geometry.radius;
  const mid = geometry.radius + band * 0.42;
  let angle = 0;
  let index = 0;
  while (angle < Math.PI * 2 - 0.03) {
    const slotHeight = 16 + hash(index * 31.7) * 46;
    const angleSpan = slotHeight / mid;
    const gap = (3 + hash(index * 32.9) * 6) / mid;
    slots.push({
      angle: angle + angleSpan / 2,
      height: slotHeight,
      seed: index,
      contentSeed: index,
      flash: 0,
      flashColor: "#f4f5f7",
      motionPhase: hash(index * 37.1),
      motionSpeed: 0.00018 + hash(index * 38.7) * 0.00032,
      nextRefreshAt: 0,
      transitionStartedAt: 0,
      previousCanvas: null,
      canvas: buildDataSlotCanvas(geometry, slotHeight, index),
    });
    angle += angleSpan + gap;
    index += 1;
  }
  const innerCanvas = buildInnerField(geometry);
  return { canvas: innerCanvas, slots, ambientStreams: buildAmbientStreams() };
}

function drawInnerNetwork(
  context: CanvasRenderingContext2D,
  geometry: HaloGeometry,
  rotation: number,
  field: HTMLCanvasElement | null,
  ambientStreams: AmbientStream[],
  now: number,
  reducedMotion: boolean,
): void {
  if (!field) return;
  context.save();
  context.translate(geometry.cx, geometry.cy);
  context.rotate(rotation);
  context.beginPath();
  context.arc(0, 0, geometry.radius, 0, Math.PI * 2);
  context.clip();
  context.drawImage(field, -geometry.radius, -geometry.radius, geometry.radius * 2, geometry.radius * 2);

  context.globalCompositeOperation = "lighter";
  context.lineCap = "round";
  for (const stream of ambientStreams) {
    const phase = reducedMotion ? stream.phase : (now * stream.speed + stream.phase) % 1;
    const head = stream.startRadius + stream.travel * phase;
    const tail = Math.max(stream.startRadius, head - stream.length);
    const angle = stream.angle;
    const headRadius = head * geometry.radius;
    const tailRadius = tail * geometry.radius;
    const brightness = reducedMotion
      ? 0.72
      : 0.28 + 0.72 * (0.5 + 0.5 * Math.sin(now * stream.brightnessSpeed + stream.brightnessPhase));
    const motionBrightness = 0.72 + 0.28 * Math.sin((phase + stream.phase) * Math.PI * 2);
    context.globalAlpha = stream.alpha * brightness * motionBrightness;
    context.strokeStyle = "#d9e1ec";
    context.lineWidth = stream.width * (0.86 + brightness * 0.14);
    context.beginPath();
    context.moveTo(Math.cos(angle) * tailRadius, Math.sin(angle) * tailRadius);
    context.lineTo(Math.cos(angle) * headRadius, Math.sin(angle) * headRadius);
    context.stroke();
  }
  context.globalAlpha = 1;
  context.restore();
}

function updateDataSlotContent(
  geometry: HaloGeometry,
  slot: DataSlot,
  now: number,
  allowRefresh: boolean,
): boolean {
  if (slot.nextRefreshAt === 0) {
    slot.nextRefreshAt = now + 1200 + hash(slot.seed * 43.9) * 1800;
    return false;
  }
  if (!allowRefresh || now < slot.nextRefreshAt) return false;

  slot.previousCanvas = slot.canvas;
  slot.contentSeed += 1 + Math.floor(hash(slot.contentSeed * 47.3) * 3);
  slot.canvas = buildDataSlotCanvas(geometry, slot.height, slot.contentSeed);
  slot.transitionStartedAt = now;
  slot.nextRefreshAt = now + 1600 + hash(slot.contentSeed * 49.1) * 2600;
  return true;
}

function drawDataSlotMotion(
  context: CanvasRenderingContext2D,
  geometry: HaloGeometry,
  slot: DataSlot,
  slotHeight: number,
  now: number,
): void {
  const band = geometry.outerRadius - geometry.radius;
  const progress = (now * slot.motionSpeed + slot.motionPhase) % 1;
  const scanX = geometry.radius + band * (0.08 + progress * 0.84);
  const scanWidth = Math.max(1.5, band * 0.035);
  const pulse = 0.18 + 0.16 * (0.5 + 0.5 * Math.sin((progress + slot.motionPhase) * Math.PI * 2));

  context.save();
  context.beginPath();
  context.rect(geometry.radius, -slotHeight / 2, band, slotHeight);
  context.clip();
  context.globalCompositeOperation = "lighter";
  const gradient = context.createLinearGradient(scanX - scanWidth, 0, scanX + scanWidth, 0);
  gradient.addColorStop(0, "rgba(232,235,242,0)");
  gradient.addColorStop(0.5, `rgba(232,235,242,${pulse})`);
  gradient.addColorStop(1, "rgba(232,235,242,0)");
  context.fillStyle = gradient;
  context.fillRect(scanX - scanWidth, -slotHeight / 2, scanWidth * 2, slotHeight);

  context.fillStyle = "rgba(232,235,242,.42)";
  const markerY = -slotHeight / 2 + slotHeight * (0.22 + 0.56 * ((progress * 1.7) % 1));
  context.fillRect(scanX - 1, markerY, 2.5, 1);
  context.restore();
}

function drawDataSlotCanvasWithTransition(
  context: CanvasRenderingContext2D,
  geometry: HaloGeometry,
  slot: DataSlot,
  slotHeight: number,
  now: number,
): void {
  const band = geometry.outerRadius - geometry.radius;
  const transitionProgress = slot.transitionStartedAt === 0
    ? 1
    : Math.min(1, (now - slot.transitionStartedAt) / 620);
  const oldAlpha = slot.previousCanvas ? 1 - transitionProgress : 0;
  const newAlpha = slot.previousCanvas ? transitionProgress : 1;

  context.globalAlpha = 0.68 * oldAlpha;
  if (slot.previousCanvas) {
    context.drawImage(slot.previousCanvas, geometry.radius, -slotHeight / 2, band, slotHeight);
  }
  context.globalAlpha = 0.68 * newAlpha;
  context.drawImage(slot.canvas, geometry.radius, -slotHeight / 2, band, slotHeight);
  context.globalAlpha = 1;

  if (slot.previousCanvas && transitionProgress >= 1) {
    slot.previousCanvas = null;
    slot.transitionStartedAt = 0;
  }
  drawDataSlotMotion(context, geometry, slot, slotHeight, now);
}

function drawDataDisk(
  context: CanvasRenderingContext2D,
  geometry: HaloGeometry,
  slots: DataSlot[],
  rotation: number,
  now: number,
  refreshState: SlotRefreshState,
): void {
  const band = geometry.outerRadius - geometry.radius;
  context.save();
  context.translate(geometry.cx, geometry.cy);

  // The ring is a separate visual plane: its solid mask hides the inner network and gives the data blocks a physical track.
  context.beginPath();
  context.arc(0, 0, geometry.outerRadius, 0, Math.PI * 2);
  context.arc(0, 0, geometry.radius, 0, Math.PI * 2, true);
  context.fillStyle = "#040506";
  context.fill("evenodd");

  // Fine lanes make the disk read as a transformed measurement surface rather than a single flat outline.
  context.globalCompositeOperation = "lighter";
  context.strokeStyle = "rgba(232,235,242,.12)";
  context.lineWidth = 0.55;
  for (const ratio of [0.18, 0.42, 0.68, 0.86]) {
    context.beginPath();
    context.arc(0, 0, geometry.radius + band * ratio, -geometry.visibleHalfAngle, geometry.visibleHalfAngle);
    context.stroke();
  }
  context.globalCompositeOperation = "source-over";

  for (const slot of slots) {
    updateDataSlotContent(geometry, slot, now, false);
  }
  if (slots.length > 0 && now - refreshState.lastRefreshAt >= SLOT_REFRESH_INTERVAL_MS) {
    for (let offset = 0; offset < slots.length; offset += 1) {
      const index = (refreshState.cursor + offset) % slots.length;
      const slot = slots[index];
      if (now < slot.nextRefreshAt) continue;
      if (updateDataSlotContent(geometry, slot, now, true)) {
        refreshState.lastRefreshAt = now;
        refreshState.cursor = (index + 1) % slots.length;
        break;
      }
    }
  }

  for (const slot of slots) {
    slot.flash = Math.max(0, slot.flash - 0.025);
    const angle = slot.angle + rotation;
    context.save();
    context.rotate(angle);
    const slotHeight = slot.height + 2;
    drawDataSlotCanvasWithTransition(context, geometry, slot, slotHeight, now);
    if (slot.flash > 0.02) {
      context.globalCompositeOperation = "lighter";
      context.globalAlpha = slot.flash;
      context.drawImage(slot.canvas, geometry.radius, -slotHeight / 2, band, slotHeight);
      context.strokeStyle = slot.flashColor;
      context.lineWidth = 1 + slot.flash;
      context.beginPath();
      context.moveTo(geometry.radius + 2, -slotHeight / 2);
      context.lineTo(geometry.radius + band * 0.16, -slotHeight / 2);
      context.moveTo(geometry.radius + 2, slotHeight / 2);
      context.lineTo(geometry.radius + band * 0.16, slotHeight / 2);
      context.stroke();
      context.globalCompositeOperation = "source-over";
    }
    context.restore();
  }

  context.strokeStyle = "rgba(240,242,248,.82)";
  context.lineWidth = 0.8;
  context.beginPath();
  context.arc(0, 0, geometry.radius, -geometry.visibleHalfAngle, geometry.visibleHalfAngle);
  context.stroke();
  context.beginPath();
  context.arc(0, 0, geometry.outerRadius, -geometry.visibleHalfAngle, geometry.visibleHalfAngle);
  context.stroke();

  // A sparse set of long marks provides the angular transformation reference used by the ring blocks.
  context.strokeStyle = "rgba(230,233,240,.35)";
  context.lineWidth = 0.5;
  for (let tick = -geometry.visibleHalfAngle; tick <= geometry.visibleHalfAngle; tick += Math.PI / 180) {
    const tickAngle = tick + rotation;
    const major = Math.abs(Math.round(tick / (Math.PI / 15)) * (Math.PI / 15) - tick) < 0.004;
    const inner = major ? geometry.radius - 7 : geometry.radius - 3;
    const outer = major ? geometry.outerRadius + 7 : geometry.outerRadius + 3;
    context.beginPath();
    context.moveTo(Math.cos(tickAngle) * inner, Math.sin(tickAngle) * inner);
    context.lineTo(Math.cos(tickAngle) * geometry.radius, Math.sin(tickAngle) * geometry.radius);
    context.moveTo(Math.cos(tickAngle) * geometry.outerRadius, Math.sin(tickAngle) * geometry.outerRadius);
    context.lineTo(Math.cos(tickAngle) * outer, Math.sin(tickAngle) * outer);
    context.stroke();
  }

  // Two small calibration brackets rotate with the disk and remain visible in the reference sector.
  context.strokeStyle = "rgba(196,184,246,.6)";
  context.lineWidth = 0.8;
  for (const bracketAngle of [rotation - geometry.visibleHalfAngle * 0.68, rotation + geometry.visibleHalfAngle * 0.68]) {
    const inner = geometry.radius + band * 0.08;
    const outer = geometry.radius + band * 0.26;
    context.beginPath();
    context.moveTo(Math.cos(bracketAngle) * inner, Math.sin(bracketAngle) * inner);
    context.lineTo(Math.cos(bracketAngle) * outer, Math.sin(bracketAngle) * outer);
    context.stroke();
  }
  context.restore();
}

function streamPoint(
  geometry: HaloGeometry,
  line: InnerStreamLine,
  t: number,
  rotation: number,
): { x: number; y: number } {
  const u = 1 - t;
  const originRadius = line.originRadius * geometry.radius;
  const controlRadius = line.controlRadius * geometry.radius;
  const targetRadius = line.targetRadius * geometry.radius;
  const origin = {
    x: geometry.cx + Math.cos(line.originAngle + rotation) * originRadius,
    y: geometry.cy + Math.sin(line.originAngle + rotation) * originRadius,
  };
  const control = {
    x: geometry.cx + Math.cos(line.controlAngle + rotation) * controlRadius,
    y: geometry.cy + Math.sin(line.controlAngle + rotation) * controlRadius,
  };
  const target = {
    x: geometry.cx + Math.cos(line.targetAngle) * targetRadius,
    y: geometry.cy + Math.sin(line.targetAngle) * targetRadius,
  };
  return {
    x: u * u * origin.x + 2 * u * t * control.x + t * t * target.x,
    y: u * u * origin.y + 2 * u * t * control.y + t * t * target.y,
  };
}

function drawPulse(
  context: CanvasRenderingContext2D,
  geometry: HaloGeometry,
  pulse: HaloPulse,
  now: number,
  reducedMotion: boolean,
  innerRotation: number,
  quality: RenderQuality,
): boolean {
  const elapsed = now - pulse.born;
  const progress = Math.min(1, elapsed / pulse.life);
  if (progress >= 1) return false;
  const fade = (1 - progress) * pulse.energy;
  const innerPhaseEnd = 0.64;
  const outerProgress = progress <= innerPhaseEnd
    ? 0
    : Math.min(1, (progress - innerPhaseEnd) / (1 - innerPhaseEnd));
  const waveRadius = geometry.outerRadius + (geometry.maxRadius - geometry.outerRadius) * outerProgress;
  const lineCount = reducedMotion ? Math.min(12, pulse.innerLines.length) : pulse.innerLines.length;
  context.save();
  context.globalCompositeOperation = "lighter";
  context.globalAlpha = fade;
  context.strokeStyle = pulse.color;
  context.shadowColor = pulse.color;
  context.shadowBlur = reducedMotion ? 0 : quality.pulseShadowBlur;
  context.lineWidth = reducedMotion ? 1 : 1.1 + (1 - progress) * 2;

  // The inner stream reaches its selected arc before the outer column starts.
  const innerHead = Math.min(1, progress / innerPhaseEnd);
  const innerTail = Math.max(0, innerHead - (reducedMotion ? 0.24 : 0.18));
  for (let index = 0; index < lineCount; index += 1) {
    const line = pulse.innerLines[index % pulse.innerLines.length];
    const steps = reducedMotion ? 2 : 8;
    context.beginPath();
    for (let step = 0; step <= steps; step += 1) {
      const t = innerTail + (innerHead - innerTail) * (step / steps);
      const point = streamPoint(geometry, line, t, innerRotation);
      if (step === 0) context.moveTo(point.x, point.y);
      else context.lineTo(point.x, point.y);
    }
    context.stroke();
  }

  // The outer stream uses the exact same world-space endpoint as the inner stream.
  if (outerProgress > 0) {
    const outerHead = Math.min(1, outerProgress * 1.25);
    const outerTail = Math.max(0, outerHead - (reducedMotion ? 0.24 : 0.16));
    for (let index = 0; index < lineCount; index += 1) {
      const spread = (index / Math.max(1, lineCount - 1) - 0.5) * pulse.width;
      const angle = pulse.angle + spread;
      const start = geometry.outerRadius + 4;
      const finalLength = (geometry.maxRadius - start) * (0.45 + hash(index * 41.3 + pulse.angle) * 0.45);
      const lineStart = start + finalLength * outerTail;
      const lineEnd = start + finalLength * outerHead;
      context.beginPath();
      context.moveTo(geometry.cx + Math.cos(angle) * lineStart, geometry.cy + Math.sin(angle) * lineStart);
      context.lineTo(geometry.cx + Math.cos(angle) * lineEnd, geometry.cy + Math.sin(angle) * lineEnd);
      context.stroke();
    }
    context.fillStyle = pulse.color;
    context.beginPath();
    context.arc(
      geometry.cx + Math.cos(pulse.angle) * waveRadius,
      geometry.cy + Math.sin(pulse.angle) * waveRadius,
      reducedMotion ? 2 : 3 + (1 - outerProgress) * 5,
      0,
      Math.PI * 2,
    );
    context.fill();
  }
  context.restore();
  return true;
}

export default function ActivityCanvas({ events, reducedMotion = false }: ActivityCanvasProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const geometryRef = useRef<HaloGeometry | null>(null);
  const innerFieldRef = useRef<HTMLCanvasElement | null>(null);
  const outerFieldRef = useRef<HTMLCanvasElement | null>(null);
  const ambientStreamsRef = useRef<AmbientStream[]>([]);
  const slotsRef = useRef<DataSlot[]>([]);
  const slotRefreshStateRef = useRef<SlotRefreshState>({ lastRefreshAt: Number.NEGATIVE_INFINITY, cursor: 0 });
  const pulsesRef = useRef<HaloPulse[]>([]);
  const latestSequenceRef = useRef(0);
  const frameRef = useRef(0);
  const renderRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const newEvents = events.filter((event) => event.sequence > latestSequenceRef.current);
    if (newEvents.length === 0) return;
    const now = performance.now();
    for (const event of newEvents) {
      const sequence = event.sequence;
      if (slotsRef.current.length > 0) {
        const slot = slotsRef.current[sequence % slotsRef.current.length];
        slot.flash = 1;
        slot.flashColor = eventColor(event);
      }
      const target = selectPulseTarget(geometryRef.current, pulsesRef.current, now, sequence);
      const pulseAngle = target.angle;
      const pulseWidth = target.width;
      const innerLineCount = 12;
      pulsesRef.current.push({
        born: now,
        life: event.phase === "completed" ? 1500 : 2300,
        angle: pulseAngle,
        width: pulseWidth,
        color: eventColor(event),
        energy: event.phase === "started" ? 1 : 0.72,
        innerLines: Array.from({ length: innerLineCount }, (_, index) => ({
          originRadius: Math.sqrt(hash(sequence * 69.1 + index)) * 0.84,
          originAngle: hash(sequence * 70.3 + index) * Math.PI * 2,
          controlRadius: 0.34 + hash(sequence * 71.5 + index) * 0.38,
          controlAngle: hash(sequence * 72.7 + index) * Math.PI * 2,
          targetRadius: 0.94 + hash(sequence * 73.9 + index) * 0.035,
          targetAngle: pulseAngle + (index / (innerLineCount - 1) - 0.5) * pulseWidth,
        })),
      });
    }
    latestSequenceRef.current = Math.max(...newEvents.map((event) => event.sequence));
    renderRef.current?.();
  }, [events]);

  useEffect(() => {
    const host = hostRef.current;
    const canvas = canvasRef.current;
    if (!host || !canvas) return undefined;
    const context = canvas.getContext("2d");
    if (!context) return undefined;

    let disposed = false;
    let width = 0;
    let height = 0;
    let dpr = 1;

    const draw = (now: number) => {
      if (disposed) return;
      const geometry = geometryRef.current;
      if (!geometry) return;
      context.setTransform(geometry.dpr, 0, 0, geometry.dpr, 0, 0);
      context.clearRect(0, 0, geometry.width, geometry.height);
      context.fillStyle = "#08090b";
      context.fillRect(0, 0, geometry.width, geometry.height);
      const camera = cameraFor(geometry, now);
      const quality = renderQualityFor(geometry, camera.z);
      const rotations = rotationFor(now);
      const livePulses = pulsesRef.current;
      context.save();
      applyCamera(context, geometry, camera);
      drawInnerNetwork(
        context,
        geometry,
        rotations.inner,
        innerFieldRef.current,
        ambientStreamsRef.current,
        now,
        reducedMotion,
      );
      drawOuterStrands(context, geometry, livePulses, now, rotations.outer, quality, outerFieldRef.current);
      drawDataDisk(context, geometry, slotsRef.current, rotations.disk, now, slotRefreshStateRef.current);
      pulsesRef.current = livePulses.filter((pulse) => drawPulse(
        context,
        geometry,
        pulse,
        now,
        reducedMotion,
        rotations.inner,
        quality,
      ));
      context.restore();
      if (!reducedMotion) {
        frameRef.current = window.requestAnimationFrame(draw);
      } else {
        frameRef.current = 0;
      }
    };

    const requestRender = () => {
      if (frameRef.current === 0) frameRef.current = window.requestAnimationFrame(draw);
    };
    renderRef.current = requestRender;

    const resize = () => {
      const rect = host.getBoundingClientRect();
      width = Math.max(1, rect.width);
      height = Math.max(1, rect.height);
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      const geometry = geometryFor(width, height, dpr);
      geometryRef.current = geometry;
      const field = buildField(geometry);
      innerFieldRef.current = field.canvas;
      outerFieldRef.current = buildOuterField(geometry);
      ambientStreamsRef.current = field.ambientStreams;
      slotsRef.current = field.slots;
      slotRefreshStateRef.current = { lastRefreshAt: Number.NEGATIVE_INFINITY, cursor: 0 };
      requestRender();
    };

    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();

    return () => {
      disposed = true;
      renderRef.current = null;
      if (frameRef.current !== 0) window.cancelAnimationFrame(frameRef.current);
      frameRef.current = 0;
      observer.disconnect();
    };
  }, [reducedMotion]);

  return (
    <div className="activity-canvas-host" ref={hostRef} aria-hidden="true">
      <canvas ref={canvasRef} className="activity-canvas" />
      <div className="activity-canvas-vignette" />
    </div>
  );
}
