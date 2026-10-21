# -*- coding: utf-8 -*-
"""240x135 逻辑像素 → 月下猫耳少女夜景（v6 高分辨率 + 面部精修）
   render --scale 6 → 1440x810
"""
import math, json, sys

W, H = 240, 135
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

BAYER4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))

def bthr(x, y):
    return (BAYER4[int(y) & 3][int(x) & 3] + 0.5) / 16.0

def dith(c1, c2, t, x, y):
    return c2 if t > bthr(x, y) else c1

def ramp(stops, t, x, y, soft=0.16):
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

def ellipse(cx, cy, rx, ry, c):
    for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
        for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
            if ((x - cx) / max(rx, 0.6)) ** 2 + ((y - cy) / max(ry, 0.6)) ** 2 <= 1.0:
                put(x, y, c)

def poly(pts, c):
    ys = [p[1] for p in pts]
    for y in range(int(min(ys)), int(max(ys)) + 1):
        xs = []
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]; x2, y2 = pts[(i + 1) % n]
            if (y1 <= y < y2) or (y2 <= y < y1):
                xs.append(x1 + (x2 - x1) * (y - y1) / (y2 - y1))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            for x in range(int(round(xs[i])), int(round(xs[i + 1])) + 1):
                put(x, y, c)

def limb(x0, y0, x1, y1, w, c):
    n = max(3, int(max(abs(x1 - x0), abs(y1 - y0)) * 3))
    r = w / 2.0
    R = int(r) + 1
    for i in range(n + 1):
        t = i / float(n)
        cx = x0 + (x1 - x0) * t
        cy = y0 + (y1 - y0) * t
        for dy in range(-R, R + 1):
            for dx in range(-R, R + 1):
                d = dx * dx + dy * dy
                if d <= r * r + 0.3:
                    put(cx + dx, cy + dy, c)
                elif d <= r * r + r * 0.8:
                    put(cx + dx, cy + dy, c)

def hnoise(x, y, seed=0):
    n = (int(x) * 374761393 + int(y) * 668265263 + seed * 2654435761) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0

# ---------- 色板 ----------
SKY_STOPS  = [(0.0, "#0a1726"), (0.40, "#132840"), (0.72, "#1b3852"), (1.0, "#224867")]
WAT_STOPS  = [(0.0, "#224867"), (0.50, "#173952"), (1.0, "#0c2439")]
MOON       = "#f2f9fd"
MOON_D     = "#d3e6ef"
MOON_GLOW  = "#86aec6"
TREE       = "#0c1b25"
TREE_L     = "#152e3a"
WILLOW     = "#122320"
WILLOW_L   = "#1d332a"
STONE      = "#48525f"
STONE_D    = "#232c37"
STONE_L    = "#74828f"
LAMP_GLOW  = "#ffb254"
LAMP_CORE  = "#ffe9b8"
LAMP_WARM  = "#e08238"
LAMP_DEEP  = "#c05a1e"

# 皮肤（三阶）
SKIN_HL    = "#fff0e2"
SKIN       = "#f8d5bb"
SKIN_S     = "#e0ae90"
SKIN_SS    = "#bd8267"
# 头发（四阶 + 发梢）
HAIR_HL    = "#ffffff"
HAIR       = "#eaf2f9"
HAIR_S     = "#c3d6e6"
HAIR_SS    = "#93aec4"
HAIR_T     = "#a9dccb"
# 眼睛
EYE_W      = "#f7fbfe"
EYE_IRIS   = "#4d8fb5"
EYE_IRIS_L = "#8fd0e4"
EYE_IRIS_D = "#2d5b7a"
EYE_PUPIL  = "#182a3c"
EYE_LASH   = "#243546"
BLUSH      = "#f0a08e"
LIP        = "#d07a72"

DRESS      = "#0c1119"
DRESS_H    = "#1e2b3a"
DRESS_HL   = "#33465a"
WATER_L    = "#44739a"
REFLECT    = "#dcebf5"
FIREFLY    = "#ffeaa8"
INK        = "#070d15"

# ---------- 1. 夜空 ----------
for y in range(0, H):
    t = min(1.0, (y / float(H)) * 1.45)
    for x in range(W):
        put(x, y, ramp(SKY_STOPS, t, x, y))

# ---------- 2. 月亮 ----------
MCX, MCY, MR = 54, 22, 19
for dy in range(-MR - 11, MR + 12):
    for dx in range(-MR - 11, MR + 12):
        x, y = MCX + dx, MCY + dy
        if not (0 <= x < W and 0 <= y < H):
            continue
        d = math.hypot(dx, dy)
        base = ramp(SKY_STOPS, min(1.0, (y / float(H)) * 1.45), x, y)
        if d <= MR - 0.5:
            c = MOON if hnoise(x, y, 3) > 0.12 else MOON_D
        elif d <= MR + 1.0:
            c = dith(MOON, base, (d - MR + 0.5) / 1.5, x, y)
        elif d <= MR + 11:
            g = (1.0 - (d - MR) / 11.0) * 0.62
            c = mix(base, MOON_GLOW, round(g * 5) / 5.0)
        else:
            continue
        put(x, y, c)
# 月面淡斑（低对比，柔和不破形）
for (dx, dy, rr) in ((-6, -7, 3), (7, 4, 3), (-2, 9, 2), (10, -6, 2), (-10, 3, 2)):
    ellipse(MCX + dx, MCY + dy, rr, rr, MOON_D)

# ---------- 3. 云 ----------
def cloud_band(y0, h, x0, x1, color):
    for x in range(max(0, x0), min(W - 1, x1) + 1):
        t = (x - x0) / max(1.0, float(x1 - x0))
        taper = min(1.0, min(t, 1.0 - t) * 5.0)
        if taper <= 0.08:
            continue
        wob = math.sin(t * 5.0 + y0) * (h * 0.8) + math.sin(t * 13.0) * (h * 0.35)
        for dy in range(max(1, int(h * taper))):
            if hnoise(x, y0 + dy, 9) < 0.18:
                continue
            put(x, y0 + wob + dy, color)

cloud_band(8, 4, 84, 168, "#0f1f30")
cloud_band(34, 3, 96, 188, "#102132")
cloud_band(48, 2, 108, 176, "#132638")

# ---------- 4. 远山与树林 ----------
for x in range(W):
    v = 46 + 7 * math.sin(x * 0.13) + 4 * math.sin(x * 0.36 + 1.1) + 3 * math.sin(x * 0.81)
    for y in range(int(v), 86):
        put(x, y, TREE if y < 70 else mix(TREE, TREE_L, (y - 70) / 16.0))
for x in range(90, 200, 4):
    h = int(3 + 5 * abs(math.sin(x * 0.53)))
    for k in range(h):
        put(x, int(46 + 5 * math.sin(x * 0.13)) - k, TREE)
        if k < h - 1:
            put(x + 1, int(46 + 5 * math.sin(x * 0.13)) - k, TREE)

# ---------- 5. 水面 ----------
for y in range(76, H):
    for x in range(0, W):
        put(x, y, ramp(WAT_STOPS, (y - 76) / float(H - 76), x, y))

# 月光倒影
for y in range(79, H):
    d = (y - 79) / float(H - 79)
    half = 7 + d * 26
    cx = 54 + math.sin(y * 0.62) * (1.5 + d * 3.5)
    if (y // 2) % 3 != 1:
        for x in range(int(cx - half), int(cx + half) + 1):
            if hnoise(int(x), y, 31) < 0.36:
                put(x, y, REFLECT if abs(x - cx) < half * 0.5 else WATER_L)

# 细波纹
for i in range(80):
    x = int(hnoise(i, 7, 51) * 142)
    y = 79 + int(hnoise(i, 11, 53) * 54)
    ln = 3 + int(hnoise(i, 13, 55) * 8)
    for k in range(ln):
        put(x + k, y, WATER_L)

# ---------- 6. 石台 ----------
def stone_block(x0, y0, x1, y1, base, dark, light):
    for y in range(int(y0), int(y1) + 1):
        for x in range(int(x0), int(x1) + 1):
            v = (y - y0) / max(1.0, float(y1 - y0))
            c = base
            if v < 0.22:
                c = light
            elif v > 0.76:
                c = dark
            if hnoise(x, y, 61) < 0.12:
                c = mix(c, dark, 0.35)
            put(x, y, c)

stone_block(164, 100, 240, 112, STONE, STONE_D, STONE_L)
stone_block(178, 113, 240, 124, STONE_D, "#182029", STONE)
stone_block(194, 125, 240, 134, "#1e2833", "#10161e", STONE_D)

# 台沿受光（左端月光、右端灯光）
for x in range(164, 240):
    if hnoise(x, 100, 71) < 0.85:
        put(x, 100, mix(STONE_L, MOON_GLOW, 0.28) if x < 196 else mix(STONE_L, LAMP_GLOW, 0.4))
for x in range(164, 240):
    put(x, 112, mix(STONE_D, STONE, 0.45))
for x in range(178, 240):
    put(x, 113, mix(STONE_L, MOON_GLOW, 0.22))
    put(x, 124, mix(STONE_D, STONE, 0.45))
for x in range(194, 240):
    put(x, 125, mix(STONE_L, MOON_GLOW, 0.18))

# 台面分缝
for gx in range(176, 240, 16):
    for y in range(100, 112):
        if px.get((gx, y)) in (STONE, STONE_L):
            put(gx, y, STONE_D)
# 临水边缘湿痕
for y in range(98, 101):
    for x in range(160, 240):
        if px.get((x, y)) in (STONE, STONE_D, STONE_L) and hnoise(x, y, 132) < 0.6:
            put(x, y, mix(px[(x, y)], WATER_L, 0.4))
for y in range(111, 114):
    for x in range(174, 240):
        if px.get((x, y)) in (STONE, STONE_D, STONE_L) and hnoise(x, y, 134) < 0.55:
            put(x, y, mix(px[(x, y)], WATER_L, 0.35))

# ---------- 7. 池边细节（踏脚石 / 芦苇 / 苔痕）----------

# 7.1 水中与岸边踏脚石
def pond_stone(cx, cy, rx, ry):
    for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
        for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
            d = ((x - cx) / max(rx, 0.6)) ** 2 + ((y - cy) / max(ry, 0.6)) ** 2
            if d > 1.0:
                continue
            if d < 0.50:
                put(x, y, STONE_L if hnoise(x, y, 120) < 0.42 else STONE)
            elif d < 0.84:
                put(x, y, STONE if hnoise(x, y, 121) < 0.6 else STONE_D)
            else:
                put(x, y, mix(STONE_D, MOON_GLOW, 0.28) if hnoise(x, y, 122) < 0.42 else STONE_D)
    # 没入水面的白痕
    for x in range(int(cx - rx) + 1, int(cx + rx)):
        if hnoise(x, int(cy + ry), 123) < 0.55:
            put(x, int(cy + ry) + 1, REFLECT)
            if hnoise(x, int(cy + ry), 124) < 0.3:
                put(x, int(cy + ry) + 2, mix(REFLECT, WATER_L, 0.5))

pond_stone(100, 120, 9, 4)
pond_stone(118, 129, 7, 3)
pond_stone(80, 114, 6, 3)
pond_stone(64, 124, 5, 2.5)

# 7.2 水边芦苇丛
def reed(x0, y0, h, seed):
    x = float(x0)
    for i in range(int(h)):
        x += math.sin(i * 0.26 + seed) * 0.40
        put(x, y0 - i, WILLOW_L if i % 4 else WILLOW)
        if i % 5 == 2 and i > 3:
            put(x + 1, y0 - i, WILLOW)
    put(x, y0 - h - 1, "#38493a")
    put(x, y0 - h, "#445545")
    put(x + 1, y0 - h, "#38493a")

for i in range(11):
    reed(3 + i * 2.6, 101 + int(hnoise(i, 1, 125) * 9),
         11 + int(hnoise(i, 2, 126) * 9), i * 0.63)

# 7.3 石台苔痕与水渍
for y in range(96, 135):
    for x in range(138, 240):
        c = px.get((x, y))
        if c in (STONE, STONE_D, STONE_L):
            if hnoise(x, y, 129) < 0.05:
                put(x, y, "#2c3c32")
            elif hnoise(x, y, 130) < 0.05:
                put(x, y, mix(c, MOON_GLOW, 0.18))
# 石台临水边缘的湿痕
for y in range(94, 98):
    for x in range(132, 240):
        if px.get((x, y)) in (STONE, STONE_D, STONE_L) and hnoise(x, y, 131) < 0.55:
            put(x, y, mix(px[(x, y)], WATER_L, 0.35))

# ---------- 8. 石灯笼 ----------
def stone_lantern(cx, top, h, w):
    poly([(cx - w - 2, top + h), (cx + w + 2, top + h),
          (cx + w + 1, top + h + 4), (cx - w - 1, top + h + 4)], STONE_D)
    for y in range(top + int(h * 0.5), top + h):
        for x in range(cx - 3, cx + 4):
            put(x, y, STONE if hnoise(x, y, 108) > 0.2 else STONE_L)
    poly([(cx - w, top + int(h * 0.36)), (cx + w, top + int(h * 0.36)),
          (cx + w, top + int(h * 0.52)), (cx - w, top + int(h * 0.52))], STONE)
    for y in range(top + int(h * 0.39), top + int(h * 0.50)):
        for x in range(cx - w + 1, cx + w):
            put(x, y, LAMP_CORE if hnoise(x, y, 109) > 0.28 else LAMP_GLOW)
    poly([(cx - w - 3, top + int(h * 0.36)), (cx + w + 3, top + int(h * 0.36)),
          (cx + w - 4, top + int(h * 0.24)), (cx - w + 4, top + int(h * 0.24))], STONE_L)
    put(cx, top + int(h * 0.22), STONE_L)
    put(cx, top + int(h * 0.18), STONE)

stone_lantern(18, 60, 20, 6)
stone_lantern(120, 58, 17, 5)

# ---------- 9. 大灯笼 ----------
LCX, LTOP, LW, LH = 212, 16, 17, 44
for y in range(LTOP + LH, LTOP + LH + 12):
    for x in range(LCX - LW - 2, LCX + LW + 3):
        put(x, y, STONE_D if hnoise(x, y, 110) > 0.28 else "#141b23")
for y in range(LTOP + 14, LTOP + LH):
    for x in range(LCX - LW, LCX + LW + 1):
        put(x, y, "#5a4029")
for y in range(LTOP + 15, LTOP + LH - 1):
    for x in range(LCX - LW + 1, LCX + LW):
        d = math.hypot((x - LCX) / float(LW - 1), (y - (LTOP + 29)) / 13.0)
        if d < 1.0:
            put(x, y, LAMP_CORE if d < 0.5 else LAMP_GLOW)
# 木棂
for gx in range(LCX - LW + 3, LCX + LW - 1, 5):
    for y in range(LTOP + 15, LTOP + LH - 1):
        put(gx, y, "#6e4f22")
for y in range(LTOP + 15, LTOP + LH - 1):
    put(LCX - LW, y, "#6e4f22"); put(LCX + LW, y, "#6e4f22")
# 灯顶
poly([(LCX - LW - 3, LTOP + 15), (LCX + LW + 4, LTOP + 15),
      (LCX + LW - 3, LTOP + 5), (LCX - LW + 2, LTOP + 5)], STONE_L)
poly([(LCX - LW + 2, LTOP + 5), (LCX + LW - 3, LTOP + 5),
      (LCX + 4, LTOP - 3), (LCX - 3, LTOP - 3)], STONE)
put(LCX, LTOP - 4, STONE_L); put(LCX, LTOP - 5, STONE_L)
# 光晕
for dy in range(-26, 32):
    for dx in range(-40, 41):
        x, y = LCX + dx, LTOP + 30 + dy
        if not (0 <= x < W and 0 <= y < H):
            continue
        d = math.hypot(dx / 40.0, dy / 30.0)
        if 1.0 < d < 1.6 and hnoise(x, y, 111) < 0.16:
            put(x, y, mix(px.get((x, y), INK), LAMP_WARM, 0.30))
        elif d <= 1.0 and hnoise(x, y, 112) < 0.10:
            put(x, y, mix(px.get((x, y), INK), LAMP_DEEP, 0.2))

# ---------- 10. 柳枝 ----------
def willow(x0, y0, length, seed):
    x, y = float(x0), float(y0)
    for i in range(int(length)):
        x += math.sin(i * 0.17 + seed) * 0.42
        y += 1.0
        put(x, y, WILLOW if i % 7 else WILLOW_L)
        if i % 5 == 0 and i > 8:
            put(x + 1, y, WILLOW)
        if i % 3 == 0 and i > 10:
            put(x + 1, y + 1, WILLOW_L)
            put(x + 2, y + 1, WILLOW)
        if i % 7 == 4 and i > 14:
            put(x - 1, y + 1, WILLOW_L)

for i in range(9):
    willow(1 + i * 4.0, -4, 40 + 30 * abs(math.sin(i * 1.7)), i * 0.8)
for i in range(5):
    willow(222 + i * 4.2, -4, 34 + 24 * abs(math.cos(i * 1.9)), 2 + i * 1.2)

# ---------- 11. 萤火 ----------
for i in range(40):
    x = int(hnoise(i, 3, 113) * 180)
    y = 70 + int(hnoise(i, 5, 115) * 58)
    if hnoise(i, 9, 117) < 0.6:
        put(x, y, FIREFLY)
    else:
        put(x, y, "#fff6d8")
        put(x + 1, y, FIREFLY)

# ---------- 12. 灯笼水中倒影 ----------
for y in range(78, 100):
    d = (y - 78) / 22.0
    cx = 210 + math.sin(y * 0.9) * 3
    half = 5 + d * 14
    for x in range(int(cx - half), int(cx + half) + 1):
        if 0 <= x < W and hnoise(x, y, 118) < 0.32:
            put(x, y, mix(px.get((x, y), INK), LAMP_GLOW, 0.5))

# ---------- ASCII 预览 ----------
if "--ascii" in sys.argv:
    CH = " .:-=+*#%@"
    for yy in range(0, H, 3):
        line = ""
        for xx in range(0, W, 2):
            r, g, b = h2r(px.get((xx, yy), "#000000"))
            lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
            line += CH[min(9, int(lum * 9.99))]
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

print("canvas=%dx%d pixels=%d colors=%d ops=%d -> %s" % (W, H, len(px), len(by_color), len(ops), out))
