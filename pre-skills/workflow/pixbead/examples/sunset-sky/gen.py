# -*- coding: utf-8 -*-
"""黄昏天空横幅 —— 生成器模式范例

逻辑画布 128x96 (4:3), render --scale 4 => 512x384

技法要点:
  1. 云用"多瓣并集定轮廓 + 全局高度场定明暗":
     - 轮廓: 若干椭圆瓣的并集, 每个瓣的边界用值噪声打散 -> 边缘圆润且不规则
     - 明暗: 按 (y - 该列云顶高度) / 云总高 归一化后映射到 12 阶云色带
       (不能每个瓣各自渐变, 否则会变成"葡萄串")
     - 瓣接缝处加 0.16 的阴影量, 保留内部层次
     - 云最外层 (nd>0.80) 压一档暗色, 让轮廓发实
  2. 天空渐变用 9 阶紫灰->粉, 叠斜向云丝 (条带坐标 = 0.55x + 0.83y)
  3. 海面用横向色带 + 断续波纹, 每 5px 一条色带打破平涂
  4. 所有色阶交界只留 soft=0.16 的窄抖动带 (团状噪声阈值, 不用 Bayer)

用法:
  python gen.py ops.json
  python scripts/pixbead.py init art.pix --width 128 --height 96 --background "#736a90"
  python scripts/pixbead.py batch art.pix --ops ops.json
  python scripts/pixbead.py render art.pix --out out.png --scale 4
"""
import math, json, sys
from collections import defaultdict

W, H = 128, 96
px = {}

def put(x, y, c):
    x, y = int(round(x)), int(round(y))
    if 0 <= x < W and 0 <= y < H:
        px[(x, y)] = c

def hnoise(x, y, seed=0):
    n = (int(x) * 374761393 + int(y) * 668265263 + int(seed) * 2654435761) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0

def vnoise(x, y, seed=0):
    xi, yi = int(math.floor(x)), int(math.floor(y))
    xf, yf = x - xi, y - yi
    def sm(t):
        return t * t * (3 - 2 * t)
    a = hnoise(xi, yi, seed);     b = hnoise(xi + 1, yi, seed)
    c = hnoise(xi, yi + 1, seed); d = hnoise(xi + 1, yi + 1, seed)
    u, v = sm(xf), sm(yf)
    return (a * (1 - u) + b * u) * (1 - v) + (c * (1 - u) + d * u) * v

def thr(x, y, seed=0):
    return 0.62 * vnoise(x * 0.31, y * 0.31, seed + 101) + 0.38 * hnoise(x, y, seed + 103)

def ramp(stops, t, x, y, soft=0.14):
    if t <= stops[0][0]:
        return stops[0][1]
    if t >= stops[-1][0]:
        return stops[-1][1]
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]; p1, c1 = stops[i + 1]
        if p0 <= t <= p1:
            f = (t - p0) / max(1e-6, (p1 - p0))
            if f > 1.0 - soft:
                return c1 if ((f - (1.0 - soft)) / soft) > thr(x, y) else c0
            return c0
    return stops[-1][1]

# ---------------- 色板 ----------------
SKY = ["#736a90", "#7f769a", "#8c82a4", "#998ead", "#a79ab5",
       "#b4a4ba", "#c0adbc", "#cbafb8", "#d4b0ae"]
SKY_STREAK = ["#7c7399", "#8980a3", "#958ba9", "#a297b2", "#afa2ba",
              "#bbacbf", "#c6b5c1", "#d0b7bd", "#d8b8b3"]

CLOUD = [(0.00, "#fffbe0"), (0.09, "#fdf1bd"), (0.18, "#fbe2a2"),
         (0.27, "#f8d08c"), (0.36, "#f2bb7a"), (0.45, "#eaa36e"),
         (0.54, "#df8b6b"), (0.63, "#cf766e"), (0.72, "#b9636f"),
         (0.82, "#9e5570"), (0.91, "#83506f"), (1.00, "#6c4a6a")]
CLOUD_EDGE = "#7d4f68"
CLOUD_FAR = [(0.00, "#fce0bc"), (0.25, "#f6ccaa"), (0.50, "#e9b49c"),
             (0.75, "#d49a96"), (1.00, "#b5808f")]

LAND = ["#4b3e66", "#3d3358", "#302848"]

SEA = [(0.00, "#f2ab7c"), (0.10, "#eb9a72"), (0.22, "#e08a6c"),
       (0.34, "#d1786e"), (0.46, "#bd6c74"), (0.58, "#a5627c"),
       (0.70, "#8d5a82"), (0.82, "#7a5484"), (1.00, "#6a4e7c")]

SUN   = "#fffbd8"
SUN_G = "#faeaa8"
STAR  = "#f6f1fa"

HORIZON = 62
SEA_TOP = 66

# ================================================================
# 1) 天空
# ================================================================
for y in range(0, HORIZON + 4):
    t = y / float(HORIZON)
    i = max(0, min(len(SKY) - 1, int(round(t * (len(SKY) - 1)))))
    for x in range(W):
        s = x * 0.55 + y * 0.83
        band = int(s) % 12
        if band in (0, 1) and hnoise(x, y, 3) > 0.48:
            c = SKY_STREAK[max(0, min(len(SKY_STREAK) - 1, i))]
        else:
            c = SKY[i]
        if hnoise(x, y, 9) > 0.91:
            c = SKY[max(0, i - 1)]
        put(x, y, c)

# 星星
for (sx, sy) in [(16, 8), (30, 17), (43, 5), (58, 11), (74, 7),
                 (99, 6), (112, 19), (86, 15), (121, 10)]:
    put(sx, sy, STAR)
put(16, 9, STAR); put(99, 7, STAR); put(74, 8, STAR)

# 太阳
SCX, SCY, SR = 27, 25, 3
for dy in range(-SR - 2, SR + 3):
    for dx in range(-SR - 2, SR + 3):
        d = math.hypot(dx, dy)
        x, y = SCX + dx, SCY + dy
        if not (0 <= x < W and 0 <= y < H):
            continue
        if d <= SR - 0.6:
            put(x, y, SUN)
        elif d <= SR + 0.9 and (d <= SR + 0.3 or hnoise(x, y, 15) > 0.4):
            put(x, y, SUN_G)

# ================================================================
# 2) 主积云(横幅排布: 铺满右侧, 云底压远岛)
# ================================================================
MAIN_BULGES = [
    (92, 58, 42, 9), (66, 56, 26, 10), (114, 57, 22, 10),
    (80, 48, 24, 12), (108, 47, 21, 11),
    (64, 40, 16, 11), (90, 39, 19, 12), (116, 41, 13, 10),
    (76, 30, 14, 11), (100, 29, 16, 11), (118, 33, 10, 9),
    (86, 21, 11, 9), (110, 22, 9, 8),
    (98, 16, 8, 7),
]
FAR_BULGES = [(8, 50, 12, 6), (21, 52, 10, 5), (33, 49, 8, 4),
              (45, 53, 8, 4), (1, 47, 7, 4), (55, 54, 6, 3)]

def bulge_nd(x, y, cx, cy, rx, ry, seed):
    nd = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
    nd += (vnoise(x * 0.30, y * 0.30, seed) - 0.5) * 0.40
    return nd

def cloud_top(x, bulges):
    t = None
    for (cx, cy, rx, ry) in bulges:
        if abs(x - cx) < rx:
            u = (x - cx) / float(rx)
            ytop = cy - ry * math.sqrt(max(0.0, 1.0 - u * u))
            if t is None or ytop < t:
                t = ytop
    return t

def paint_cloud(bulges, stops, seed, y_bottom, edge_col=None):
    for x in range(W):
        yt = cloud_top(x, bulges)
        if yt is None:
            continue
        span = max(4.0, y_bottom - yt)
        for y in range(int(yt) - 1, y_bottom + 1):
            if not (0 <= y < H):
                continue
            inside = False
            seam = 0.0
            min_nd = 9.0
            for (cx, cy, rx, ry) in bulges:
                if abs(x - cx) > rx + 2 or abs(y - cy) > ry + 2:
                    continue
                nd = bulge_nd(x, y, cx, cy, rx, ry, seed)
                if nd <= 1.0:
                    inside = True
                    min_nd = min(min_nd, nd)
                if 0.70 <= nd <= 1.06:
                    seam = max(seam, 0.16)
            if not inside:
                continue
            v = (y - yt) / span
            v = v * 0.86 + ((x - W * 0.26) / float(W)) * 0.13 + seam
            v += (hnoise(x, y, seed + 2) - 0.5) * 0.07
            v = max(0.0, min(1.0, v))
            c = ramp(stops, v, x, y, soft=0.16)
            if edge_col and min_nd > 0.80 and hnoise(x, y, seed + 5) > 0.40:
                c = edge_col
            put(x, y, c)

paint_cloud(MAIN_BULGES, CLOUD, 7, HORIZON + 1, CLOUD_EDGE)
paint_cloud(FAR_BULGES, CLOUD_FAR, 27, HORIZON + 1)

# ================================================================
# 3) 远岛剪影
# ================================================================
def land_top(x):
    b = HORIZON - 2
    b += 1.3 * math.sin(x * 0.16 + 0.7) + 0.9 * math.sin(x * 0.38 + 2.1)
    b += (vnoise(x * 0.20, 2.0, 41) - 0.5) * 1.1
    if hnoise(x, 3, 42) > 0.92:
        b -= 1.2
    return b

for x in range(W):
    yt = land_top(x)
    for y in range(int(yt), SEA_TOP + 1):
        put(x, y, LAND[0] if y < yt + 2 else LAND[1])
    put(x, SEA_TOP + 1, LAND[2])

# ================================================================
# 4) 一截海面
# ================================================================
for y in range(SEA_TOP, H):
    t = (y - SEA_TOP) / float(H - SEA_TOP)
    for x in range(W):
        put(x, y, ramp(SEA, t, x, y, soft=0.18))

for y in range(SEA_TOP + 1, SEA_TOP + 4):
    for x in range(W):
        if hnoise(x, y, 55) > 0.30:
            put(x, y, "#f5b788" if y < SEA_TOP + 3 else "#eaa87e")

BANDS = [(74, "#c9808a"), (79, "#a86a86"), (84, "#8f5f8a"),
         (89, "#7a5782"), (94, "#6d5179")]
for (by, bc) in BANDS:
    for x in range(W):
        if hnoise(x, by, 57) > 0.22:
            put(x, by, bc)
            if hnoise(x, by, 58) > 0.72:
                put(x, by + 1, bc)

WV = [(70, 12), (73, 15), (77, 11), (81, 16), (86, 13),
      (90, 18), (95, 14)]
for (wy, seg) in WV:
    x = int(hnoise(wy, 1, 51) * 30)
    while x < W:
        ln = int(seg * (0.5 + hnoise(x, wy, 51)))
        if hnoise(x, wy, 52) > 0.28:
            for i in range(ln):
                xx = x + i
                if xx >= W:
                    break
                yy = wy + int(math.sin(xx * 0.11 + wy) * 1.0)
                if hnoise(xx, yy, 53) > 0.32:
                    put(xx, yy, "#e8a488" if wy < 82 else "#9d84ad")
        x += ln + int(5 + hnoise(x, wy, 72) * 14)

# ================================================================
by_color = defaultdict(list)
for (x, y), c in px.items():
    by_color[c].append((x, y))
ops = []
for c in sorted(by_color):
    pts = by_color[c]
    for i in range(0, len(pts), 1200):
        chunk = pts[i:i + 1200]
        ops.append({"op": "pixel",
                    "set": ";".join("%d,%d,%s" % (x, y, c) for x, y in chunk)})

out = sys.argv[1] if len(sys.argv) > 1 else "ops_sky.json"
json.dump(ops, open(out, "w", encoding="utf-8"), ensure_ascii=False)
print("pixels=%d  ops=%d  colors=%d" % (len(px), len(ops), len(by_color)))
