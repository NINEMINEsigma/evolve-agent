# -*- coding: utf-8 -*-
"""128x128 逻辑像素 → 浮世绘《富士与青海波》像素画
   render --scale 8 → 1024x1024
   技法：Bayer4 有序抖动 + 限色（约 20 色）+ 手绘扰动
"""
import math, json, sys

W = H = 128
px = {}

def put(x, y, c):
    x = int(x); y = int(y)
    if 0 <= x < W and 0 <= y < H:
        px[(x, y)] = c

def h2r(c):
    c = c.lstrip('#')
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))

def r2h(r, g, b):
    f = lambda v: max(0, min(255, int(round(v))))
    return "#%02x%02x%02x" % (f(r), f(g), f(b))

def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    ra, ga, ba = h2r(a); rb, gb, bb = h2r(b)
    return r2h(ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t)

def rect(x0, y0, x1, y1, c):
    for y in range(int(y0), int(y1) + 1):
        for x in range(int(x0), int(x1) + 1):
            put(x, y, c)

# ---------- 抖动与噪声 ----------
BAYER4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))

def bthr(x, y):
    return (BAYER4[y & 3][x & 3] + 0.5) / 16.0

def dith(c1, c2, t, x, y):
    return c2 if t > bthr(x, y) else c1

def ramp_dith(stops, t, x, y, soft=0.18):
    """色带化渐变：每个色阶内平涂纯色，只在色阶交界处用固定宽度抖动过渡"""
    if t <= stops[0][0]:
        return stops[0][1]
    if t >= stops[-1][0]:
        return stops[-1][1]
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]; p1, c1 = stops[i + 1]
        if p0 <= t <= p1:
            f = (t - p0) / max(1e-6, (p1 - p0))
            if f > 1.0 - soft:
                return dith(c0, c1, (f - (1.0 - soft)) / soft, x, y)
            return c0
    return stops[-1][1]

def hnoise(x, y, seed=0):
    n = (int(x) * 374761393 + int(y) * 668265263 + seed * 2654435761) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0

# ---------- 限色板 ----------
INK     = "#152230"
PAPER   = "#f2e8cd"
SEAL    = "#b8382a"
SUN     = "#c9462e"
SUN_D   = "#a93a22"

SKY_STOPS = [(0.0, "#f2e8cd"), (0.36, "#ebdfbe"), (0.70, "#e0d0a9"), (1.0, "#d5c396")]
MT_STOPS  = [(0.0, "#1b2f3f"), (0.35, "#28465a"), (0.70, "#39617a"), (1.0, "#4c7689")]
SEA_STOPS = [(0.0, "#17496f"), (0.55, "#113d60"), (1.0, "#0b2f50")]

SNOW   = "#f8f6ec"
SNOW_S = "#cdd8d2"
WAVE_L = "#f1eedd"
WAVE_M = "#a6c9d2"
WAVE_D = "#0a2a46"

HORIZON = 90
FUJI_CX, FUJI_TOP, FUJI_BOT, FUJI_HALF = 64, 32, 93, 44
GROOVES = (-0.82, -0.50, -0.18, 0.16, 0.50, 0.82)

# ---------- 1. 天空 ----------
for y in range(0, HORIZON + 1):
    t = y / float(HORIZON)
    for x in range(W):
        put(x, y, ramp_dith(SKY_STOPS, t, x, y))

# ---------- 2. 旭日 ----------
SUN_CX, SUN_CY, SUN_R = 26, 25, 8
for dy in range(-SUN_R - 1, SUN_R + 2):
    for dx in range(-SUN_R - 1, SUN_R + 2):
        d = math.hypot(dx, dy)
        x, y = SUN_CX + dx, SUN_CY + dy
        base = ramp_dith(SKY_STOPS, max(0.0, min(1.0, y / float(HORIZON))), x, y)
        if d <= SUN_R - 1.0:
            c = SUN if hnoise(x, y, 3) > 0.16 else SUN_D
        elif d <= SUN_R + 0.6:
            c = dith(SUN, base, (d - SUN_R + 1.0) / 1.6, x, y)
        else:
            continue
        put(x, y, c)

# ---------- 3. 云带 ----------
def band_cloud(x0, x1, y0, h, color):
    for x in range(max(0, x0), min(W - 1, x1) + 1):
        t = (x - x0) / max(1.0, float(x1 - x0))
        taper = min(1.0, min(t, 1.0 - t) * 6.0)
        if taper <= 0.08:
            continue
        hh = max(1.0, h * taper)
        wob = math.sin(t * 5.0 + 0.7) * (h * 0.6) + math.sin(t * 12.0) * (h * 0.25)
        for dy in range(int(round(hh))):
            if hnoise(x, y0 + dy, 5) < 0.12:
                continue
            put(x, y0 + wob + dy, color)

band_cloud(-4, 62, 12, 3, "#d5c296")
band_cloud(48, 104, 20, 2, "#d5c296")
band_cloud(76, 132, 13, 3, "#ddcb9f")
band_cloud(-4, 40, 36, 2, "#e3d5ac")

# ---------- 4. 富士山 ----------
def fuji():
    span = float(FUJI_BOT - FUJI_TOP)
    for y in range(FUJI_TOP, FUJI_BOT + 1):
        t = (y - FUJI_TOP) / span
        w = FUJI_HALF * (t ** 0.95) + 1.1 * math.sin(t * 8.0 + 0.6) * t
        x0, x1 = int(round(FUJI_CX - w)), int(round(FUJI_CX + w))
        for x in range(x0, x1 + 1):
            u = max(0.0, min(1.0, (x - x0) / max(1.0, float(x1 - x0))))
            put(x, y, ramp_dith(MT_STOPS, u ** 0.9, x, y))
    # 山脊沟槽（断续、渐隐）
    for idx, k in enumerate(GROOVES):
        for y in range(FUJI_TOP + 1, FUJI_BOT + 1):
            t = (y - FUJI_TOP) / span
            if hnoise(idx * 17, y, 21) < 0.16:
                continue
            if t > 0.72:
                continue
            w = FUJI_HALF * (t ** 0.95)
            bend = math.sin(t * 3.1 + idx * 1.3) * 0.05 * t
            put(FUJI_CX + (k + bend) * w, y, mix(ramp_dith(MT_STOPS, 0.55, 0, y), INK, 0.30))
    # 雪顶
    snow_base = 0.27
    for y in range(FUJI_TOP, FUJI_TOP + int(span * 0.46) + 1):
        t = (y - FUJI_TOP) / span
        w = FUJI_HALF * (t ** 0.95)
        if w < 1.0:
            continue
        for x in range(int(round(FUJI_CX - w)), int(round(FUJI_CX + w)) + 1):
            u = (x - FUJI_CX) / w
            if abs(u) > 1.0:
                continue
            depth = snow_base + 0.020 * math.sin(u * 9.0)
            for gi, k in enumerate(GROOVES):
                if gi % 2:
                    continue
                dd = abs(u - k)
                if dd < 0.055:
                    depth += 0.15
                elif dd < 0.10:
                    depth += 0.06
            if t < depth:
                put(x, y, dith(SNOW, SNOW_S, 0.32 + 0.26 * math.sin(u * 13.0), x, y))
    # 山顶点苔
    for (dx, dy) in ((0, 0), (-1, 1), (1, 1)):
        put(FUJI_CX + dx, FUJI_TOP + dy, INK)

fuji()

# ---------- 5. 海面 ----------
for y in range(HORIZON, H):
    t = (y - HORIZON) / float(H - HORIZON)
    for x in range(W):
        put(x, y, ramp_dith(SEA_STOPS, t, x, y))

for x in range(W):
    put(x, HORIZON, INK)

# 山脚碎浪
x = 18
while x < 112:
    seg = int(2 + 3 * abs(math.sin(x * 0.35)))
    for i in range(seg):
        put(x + i, HORIZON - 1, WAVE_L)
    x += seg + int(2 + 4 * abs(math.sin(x * 0.61)))

# ---------- 6. 青海波 ----------
def arc(cx, cy, r, color, seed):
    n = max(8, int(r * 6))
    for i in range(n + 1):
        a = math.pi + math.pi * (i / float(n))
        rr = r + (hnoise(i, seed, 41) - 0.5) * 1.2
        put(cx + rr * math.cos(a), cy + rr * math.sin(a), color)

R = 11
rings = [(R, WAVE_L, 41), (R - 3.5, WAVE_M, 42), (R - 7, WAVE_L, 43)]
j = 0
cy = HORIZON + R
while cy < H + R:
    off = (j % 2) * R
    k = -1
    while off + k * 2 * R - R < W + R:
        cx = off + k * 2 * R - R
        for (r, col, sd) in rings:
            arc(cx, cy, r, col, sd + j * 7 + k * 3)
        k += 1
    j += 1
    cy += R

# ---------- 7. 飞鸟 ----------
def bird(bx, by):
    put(bx - 1, by, INK)
    put(bx, by + 1, INK)
    put(bx + 1, by, INK)

for (bx, by) in ((44, 9), (54, 6), (63, 11), (94, 22)):
    bird(bx, by)

# ---------- 8. 印章 ----------
rect(104, 5, 118, 19, SEAL)
rect(106, 7, 116, 17, PAPER)
for (bx, by, bw, bh) in [(107, 8, 8, 1), (107, 11, 8, 1), (107, 14, 8, 1), (110, 8, 1, 7)]:
    rect(bx, by, bx + bw - 1, by + bh - 1, SEAL)
for y in range(4, 21):
    for x in range(103, 120):
        if hnoise(x, y, 55) < 0.14:
            nx = px.get((x, y))
            if nx is not None:
                put(x, y, mix(nx, PAPER, 0.5))

# ---------- 9. ASCII 预览 ----------
if "--ascii" in sys.argv:
    CHARS = " .:-=+*#%@"
    for yy in range(0, H, 2):
        line = ""
        for xx in range(0, W, 1):
            r, g, b = h2r(px.get((xx, yy), "#000000"))
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            line += CHARS[min(9, int(lum * 9.99))]
        print("%3d|%s" % (yy, line))

# ---------- 导出 ----------
out = "ops.json"
for a in sys.argv[1:]:
    if not a.startswith("--"):
        out = a
from collections import defaultdict
by_color = defaultdict(list)
for (x, y), c in px.items():
    by_color[c].append((x, y))

ops = []
for c, pts in by_color.items():
    entries = ["%d,%d,%s" % (x, y, c) for x, y in pts]
    for i in range(0, len(entries), 800):
        ops.append({"op": "pixel", "set": ";".join(entries[i:i + 800])})

with open(out, "w", encoding="utf-8") as f:
    json.dump(ops, f)

print("pixels=%d colors=%d ops=%d -> %s" % (len(px), len(by_color), len(ops), out))
