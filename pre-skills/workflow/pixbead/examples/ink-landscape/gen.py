# -*- coding: utf-8 -*-
"""水墨山水 —— 生成器模式范例

逻辑画布 400x225 (16:9), render --scale 4 => 1600x900

技法要点:
  1. 墨浓度场: 每像素先算 0..1 着墨浓度, 再统一映射到 8 阶限定墨色
     - t <  0.22  概率点阵 (模拟墨在纸上化开的颗粒, 覆盖率 = 浓度)
     - t >= 0.22  平涂色阶   (相邻阶之间只有 soft=0.26 的窄抖动带)
     -> 约 70% 落墨像素在平涂区, 避免整幅变成网点
  2. 抖动阈值用 团状随机噪声(低频成团 + 高频颗粒), 不用 Bayer 矩阵
     (Bayer 周期 4 逻辑像素, 放大 4 倍后是 16 屏幕像素的规则网格)
  3. 山脊用显式控制点线性插值, 不用幂律函数 (幂律必然得到光滑圆锥)
  4. 三层山叠压(远/中/主) + 山脚指数衰减 + 离散云团遮挡 = 纵深与"云断山腰"
  5. 松针用放射状针球; 皴/苔点/飞鸟/题款/印章 均为纯色单像素

用法:
  python gen.py ops.json
  python scripts/pixbead.py init art.pix --width 400 --height 225 --background "#f4efe3"
  python scripts/pixbead.py batch art.pix --ops ops.json
  python scripts/pixbead.py render art.pix --out out.png --scale 4
"""
import math, json, sys
from collections import defaultdict

W, H = 400, 225
px = {}

PAPER   = "#f4efe3"
PAPER_T = "#ece2cd"
INK = ["#d7d0c0", "#bfb8a7", "#a49d8e", "#8b8476",
       "#6f6a5f", "#555046", "#3b3830", "#232019"]
SEAL   = "#a93c2c"
SEAL_D = "#7c2a1e"

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
    return 0.60 * vnoise(x * 0.21, y * 0.21, seed + 101) + 0.40 * hnoise(x, y, seed + 103)

def ink_px(t, x, y):
    if t <= 0.012:
        return None
    if t < 0.22:
        cov = (t / 0.22) ** 0.85
        return INK[0] if thr(x, y) < cov else None
    u = (t - 0.22) / 0.78
    p = u * 7.0
    i = int(p)
    if i >= 7:
        return INK[7]
    f = p - i
    soft = 0.26
    if f > 1.0 - soft:
        return INK[i + 1] if ((f - (1.0 - soft)) / soft) > thr(x, y) else INK[i]
    return INK[i]

def wash(x, y, t):
    c = ink_px(t, x, y)
    if c is not None:
        put(x, y, c)

def make_ridge(pts, seed, amp=1.5):
    def f(x):
        if x < pts[0][0] or x > pts[-1][0]:
            return None
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]; x1, y1 = pts[i + 1]
            if x0 <= x <= x1:
                u = (x - x0) / max(1e-6, (x1 - x0))
                y = y0 + (y1 - y0) * u
                y += (vnoise(x * 0.19, seed * 9.0, seed) - 0.5) * amp * 2
                y += (hnoise(x, seed, seed + 55) - 0.5) * 1.1     # 碎石级细扰
                return y
        return None
    return f

FAR = make_ridge([(-10, 150), (8, 138), (26, 143), (44, 128), (62, 136),
                  (80, 120), (96, 130), (112, 122), (130, 134), (150, 144),
                  (176, 150), (250, 156)], 3, 0.9)

# 中山: 稀疏控制点 = 平缓远丘
MID = make_ridge([(138, 158), (154, 145), (170, 134), (186, 142), (202, 128),
                  (218, 138), (234, 130), (250, 140), (266, 150), (282, 160)], 7, 1.4)

# 主峰: 双尖 + 崖台 + 凹槽
MAIN = make_ridge([(226, 168), (236, 159), (245, 149), (253, 136), (259, 120),
                   (265, 104), (270, 93), (275, 102), (280, 114), (285, 119),
                   (290, 105), (296, 87), (302, 68), (307, 52), (311, 43),
                   (316, 34), (320, 31), (323, 35), (326, 30), (330, 40),
                   (334, 56), (338, 74), (342, 90), (345, 97), (348, 86),
                   (352, 70), (357, 54), (361, 47), (364, 43), (367, 47),
                   (371, 43), (375, 54), (379, 60), (383, 50), (387, 42),
                   (391, 54), (396, 72), (400, 84)], 11, 2.4)

CLOUDS = [(246, 130, 56, 20, 0.28), (304, 148, 44, 17, 0.24), (364, 132, 40, 16, 0.32)]

def cloud_f(x, y):
    f = 1.0
    for (cx, cy, rx, ry, fl) in CLOUDS:
        d = math.hypot((x - cx) / rx, (y - cy) / ry)
        d += (vnoise(x * 0.05, y * 0.06, 37) - 0.5) * 0.55
        if d < 1.0:
            f = min(f, fl + (1.0 - fl) * (abs(d) ** 0.55))
    return f

def mass(ridge, t_top, seed, decay=1.15, lf=0.030, cloud=True, y_stop=H):
    for x in range(W):
        yt = ridge(x)
        if yt is None:
            continue
        for y in range(int(yt), y_stop):
            d = (y - yt) / 120.0
            t = t_top * math.exp(-decay * d)
            t *= 0.40 + 1.00 * vnoise(x * lf, y * lf * 1.5, seed)
            t *= 0.86 + 0.28 * vnoise(x * 0.33, y * 0.33, seed + 3)
            if y - yt < 2:
                t = max(t, t_top * 1.30)
            if cloud:
                t *= cloud_f(x, y)
            if t > 0.012:
                wash(x, y, t)

def cun(ridge, seed, count, dark=5, xmin=0, xmax=W, ymax=H, ln0=4, ln1=9):
    for i in range(count):
        x = xmin + int(hnoise(i, 1, seed) * (xmax - xmin))
        yt = ridge(x)
        if yt is None:
            continue
        y = int(yt) + 3 + int(hnoise(i, 2, seed) * 36)
        L = ln0 + int(hnoise(i, 3, seed) * ln1)
        drift = (hnoise(i, 4, seed) - 0.5) * 1.5
        for k in range(L):
            xx = int(x + drift * k)
            yy = y + k
            if not (0 <= xx < W and yy < ymax):
                continue
            if hnoise(xx, yy, seed + 5) < 0.28:
                continue
            put(xx, yy, INK[dark] if k < L * 0.5 else INK[max(0, dark - 2)])

# ---------------------------------------------------------------- 纸纹
for y in range(H):
    for x in range(W):
        if hnoise(x, y, 5) > 0.972:
            put(x, y, PAPER_T)

# ---------------------------------------------------------------- 山
mass(FAR, 0.32, 41, decay=2.2, lf=0.040)
mass(MID, 0.44, 43, decay=1.55, lf=0.034)
mass(MAIN, 0.92, 47, decay=1.15, lf=0.028)

cun(MAIN, 53, 120, dark=5, xmin=230, xmax=W, ymax=182)
cun(MAIN, 57, 60, dark=4, xmin=230, xmax=W, ymax=172, ln0=3, ln1=6)
cun(MID, 59, 50, dark=3, xmin=138, xmax=284, ymax=172)

for x in range(228, W):
    yt = MAIN(x)
    if yt is None or hnoise(x, 0, 71) < 0.42:
        continue
    put(x, int(yt), INK[7])
    if hnoise(x, 1, 71) > 0.60:
        put(x, int(yt) + 1, INK[5])
    if hnoise(x, 2, 71) > 0.90:
        put(x, int(yt) - 1, INK[4])

for i in range(230):
    x = 236 + int(hnoise(i, 3, 81) * 162)
    yt = MAIN(x)
    if yt is None:
        continue
    y = int(yt) + 2 + int(hnoise(i, 5, 83) * 36)
    if y < 180:
        put(x, y, INK[7])
        if hnoise(i, 7, 85) > 0.45:
            put(x + 1, y, INK[6])
        if hnoise(i, 9, 87) > 0.75:
            put(x, y + 1, INK[6])

# ---------------------------------------------------------------- 瀑布
FX, FY0, FY1 = 345, 106, 162
for y in range(FY0, FY1):
    t = (y - FY0) / float(FY1 - FY0)
    w = 1.2 + 1.0 * t + 0.7 * math.sin(y * 0.25) * (0.4 + t)
    x0 = int(FX - w + math.sin(y * 0.15) * 1.2)
    x1 = int(FX + w)
    for x in range(x0, x1 + 1):
        edge = min(x - x0, x1 - x)
        put(x, y, PAPER if edge <= 0 else INK[0])      # 中心白, 两侧极淡
        if hnoise(x, y, 60) > 0.93 and edge > 0:
            put(x, y, INK[2])
    if hnoise(x0, y, 61) > 0.74 and 0.2 < t < 0.7:
        put(x0 + 1, y, INK[4])

for y in range(FY1 - 4, FY1 + 18):
    for x in range(FX - 22, FX + 22):
        d = math.hypot((x - FX) / 20.0, (y - (FY1 + 4)) / 17.0)
        if d < 1.0 and hnoise(x, y, 63) > d * 0.85:
            wash(x, y, 0.30 * (1 - d) + 0.10)

# ---------------------------------------------------------------- 水面
for y in range(152, 188):
    for x in range(266, 400):
        if hnoise(x, y, 65) < 0.55:
            continue
        t = 0.26 * (1 - (y - 152) / 38.0) ** 1.2
        t *= 0.55 + 0.9 * vnoise(x * 0.075, y * 0.24, 67)
        if (x // 3) % 2 == 0:
            wash(x, y, t)

WV = [(156, 0.40, 26), (161, 0.28, 18), (167, 0.38, 30), (173, 0.26, 22),
      (181, 0.34, 34), (189, 0.24, 24), (197, 0.30, 28), (205, 0.22, 22),
      (214, 0.26, 26), (222, 0.17, 20)]
for (wy, wa, seg) in WV:
    x = int(hnoise(wy, 1, 69) * 34)
    while x < W:
        ln = int(seg * (0.5 + hnoise(x, wy, 69)))
        if hnoise(x, wy, 70) > 0.22:
            for i in range(ln):
                xx = x + i
                yy = wy + int(math.sin(xx * 0.07 + wy * 0.7) * 1.2)
                ed = 1.0 - abs(i - ln / 2.0) / (ln / 2.0 + 1)
                wash(xx, yy, wa * ed + 0.06)
        x += ln + int(4 + hnoise(x, wy, 72) * 16)

# ---------------------------------------------------------------- 坡石
def bank_top(x):
    if x > 132:
        return None
    b = 198 + 7.0 * math.sin(x * 0.052 + 0.4) + 4.0 * math.sin(x * 0.135 + 2.1)
    b += (vnoise(x * 0.14, 3.5, 33) - 0.5) * 10.0
    return b

for x in range(0, 133):
    yt = bank_top(x)
    if yt is None:
        continue
    for y in range(int(yt), H):
        d = (y - yt) / max(1.0, H - yt)
        t = 0.80 * (1 - d * 0.40) * (0.42 + 1.00 * vnoise(x * 0.13, y * 0.11, 35))
        if d < 0.12:
            t *= 1.18
        wash(x, y, t)

for x in range(0, 133):
    yt = bank_top(x)
    if yt is None:
        continue
    if hnoise(x, 0, 37) > 0.18:
        put(x, int(yt), INK[7])
    if hnoise(x, 7, 39) > 0.58:
        y = int(yt) + 1 + int(hnoise(x, 8, 40) * 24)
        put(x, y, INK[7])
        if hnoise(x, 9, 41) > 0.55:
            put(x + 1, y, INK[6])

for i in range(330):
    x = int(hnoise(i, 11, 43) * 132)
    yt = bank_top(x)
    if yt is None:
        continue
    y = int(yt) + 2 + int(hnoise(i, 13, 45) * 24)
    if y >= H - 1:
        continue
    L = 3 + int(hnoise(i, 15, 47) * 6)
    dr = 0.7 if hnoise(i, 17, 48) > 0.5 else -0.35
    for k in range(L):
        xx = int(x + dr * k)
        yy = y + k
        if 0 <= xx < W and yy < H and hnoise(xx, yy, 49) > 0.26:
            put(xx, yy, INK[4] if k < L - 1 else INK[6])

# ---------------------------------------------------------------- 松树
def needle_ball(cx, cy, r, seed, dark=INK[7], sub=INK[4]):
    n = 9 + int(hnoise(cx, cy, seed) * 5)
    for i in range(n):
        a = (i / float(n)) * math.pi * 2 + (hnoise(i, cx, seed + 1) - 0.5) * 0.6
        L = r * (0.62 + 0.52 * hnoise(i, cy, seed + 2))
        for k in range(1, int(L) + 1):
            x = cx + math.cos(a) * k
            y = cy + math.sin(a) * k * 0.88
            put(x, y, dark if k < L * 0.55 else sub)
    put(cx, cy, dark)

def trunk(x0, y0, h, lean, seed):
    for i in range(h):
        t = i / float(h)
        w = 1 + int(round(3.6 * (1 - t) ** 0.72))
        cx = x0 + lean * h * 0.40 * (t ** 1.15) + 2.6 * math.sin(t * 4.4 + seed) \
             + 1.5 * math.sin(t * 10.0 + seed * 2)
        for k in range(w):
            xx = int(round(cx)) - w // 2 + k
            put(xx, y0 - i, INK[7] if (k == 0 or k == w - 1) else INK[5])
        if hnoise(int(cx), y0 - i, seed + 4) > 0.80:
            put(int(round(cx)), y0 - i, INK[3])
    return lambda t: (x0 + lean * h * 0.40 * (t ** 1.15) + 2.6 * math.sin(t * 4.4 + seed)
                      + 1.5 * math.sin(t * 10.0 + seed * 2))

def pine(x0, y0, h, lean, seed, nb=5, rr=6):
    fx = trunk(x0, y0, h, lean, seed)
    for b in range(nb):
        ft = 0.30 + 0.64 * (b + 0.55 * hnoise(b, 0, seed)) / nb
        yb = y0 - int(h * ft)
        xb = fx(ft)
        dirn = -1 if (b % 2 == 0) else 1
        ang = math.radians(-152 if dirn < 0 else -28)
        L = int((10 + 11 * hnoise(b, 1, seed)) * (1.20 - ft * 0.42))
        ex, ey = xb, yb
        for i in range(L):
            ex = xb + math.cos(ang) * i
            ey = yb + math.sin(ang) * i + 0.55 * ((i / max(1.0, L)) ** 2) * 4
            put(ex, ey, INK[7] if hnoise(i, seed, seed + 1) > 0.2 else INK[6])
        needle_ball(ex, ey - 2, rr * (0.85 + 0.25 * hnoise(b, 2, seed)), seed + b * 9)
        if L > 14:
            needle_ball(xb + math.cos(ang) * L * 0.55,
                        yb + math.sin(ang) * L * 0.55 - 2,
                        rr * 0.72, seed + b * 9 + 3)
    topx = fx(1.0)
    needle_ball(topx, y0 - h - 1, rr * 1.05, seed + 88)
    needle_ball(topx - 4, y0 - h + 4, rr * 0.75, seed + 92)
    needle_ball(topx + 4, y0 - h + 7, rr * 0.68, seed + 96)

pine(32, 204, 84, -0.32, 101, nb=6, rr=6.5)
pine(63, 201, 58, 0.28, 111, nb=5, rr=5.0)
pine(96, 207, 42, -0.12, 121, nb=4, rr=3.8)

# ---------------------------------------------------------------- 小舟
BX, BY = 170, 184
for i in range(30):
    t = i / 29.0
    x = BX + i
    y = BY + 2 - int(3.2 * math.sin(t * math.pi)) + int(((t - 0.5) * 2) ** 2 * 3)
    put(x, y, INK[7]); put(x, y + 1, INK[5])
    if t < 0.10 or t > 0.90:
        put(x, y - 1, INK[7])
gx = BX + 15
for i in range(-3, 4):
    put(gx + i, BY - 9 + (1 if abs(i) == 3 else 0), INK[7])
for i in range(-2, 3):
    put(gx + i, BY - 10, INK[6])
for yy in range(BY - 8, BY - 4):
    put(gx, yy, INK[7]); put(gx + 1, yy, INK[7])
put(gx - 1, BY - 5, INK[7]); put(gx + 2, BY - 6, INK[6])
for i in range(14):
    put(gx - 2 - i, BY - 6 - int(i * 0.60), INK[5] if i > 3 else INK[7])
for i in range(5):
    put(gx - 16, BY - 5 + i, INK[4])
for y in range(BY + 5, BY + 12):
    for x in range(BX, BX + 30):
        if hnoise(x, y, 91) > 0.42:
            wash(x, y, 0.28 * (1 - (y - BY - 5) / 8.0))

# ---------------------------------------------------------------- 飞鸟
def bird(x, y, s, c):
    for i in range(1, s + 1):
        put(x - i, y - int(i * 0.85), c)
        put(x + i, y - int(i * 0.85), c)
    put(x, y, c)

bird(116, 68, 3, INK[3]); bird(130, 58, 2, INK[3]); bird(144, 72, 3, INK[3])
bird(159, 62, 2, INK[2]); bird(174, 74, 2, INK[2]); bird(188, 66, 2, INK[2])
bird(203, 56, 2, INK[2])

# ---------------------------------------------------------------- 题款/印
def fake_char(x0, y0, seed, s=5, col=INK[6]):
    n = 5 + int(hnoise(seed, 0, 5) * 2)
    for k in range(n):
        r = hnoise(seed, k, 11)
        if r < 0.46:
            yy = y0 + int(hnoise(seed, k, 12) * s)
            ln = 3 + int(hnoise(seed, k, 13) * (s - 2))
            sx = x0 + int(hnoise(seed, k, 14) * (s - ln + 1))
            for i in range(ln):
                put(sx + i, yy, col)
        elif r < 0.84:
            xx = x0 + int(hnoise(seed, k, 15) * s)
            ln = 3 + int(hnoise(seed, k, 16) * (s - 2))
            sy = y0 + int(hnoise(seed, k, 17) * (s - ln + 1))
            for i in range(ln):
                put(xx, sy + i, col)
        else:
            xx = x0 + int(hnoise(seed, k, 18) * s)
            yy = y0 + int(hnoise(seed, k, 19) * s)
            put(xx, yy, col)
            put(xx + 1, yy + 1, col) if hnoise(seed, k, 20) > 0.5 else put(xx - 1, yy + 1, col)

for i in range(9):
    fake_char(36, 17 + i * 7, 200 + i * 37)
for i in range(6):
    fake_char(27, 25 + i * 7, 260 + i * 53)

def seal_box(x0, y0, s=13):
    for y in range(s):
        for x in range(s):
            if hnoise(x0 + x, y0 + y, 91) < 0.12:
                continue
            put(x0 + x, y0 + y, SEAL if hnoise(x0 + x, y0 + y, 92) > 0.28 else SEAL_D)
    for cy in (2, 8):
        for cx in (2, 8):
            fake_char(x0 + cx, y0 + cy, 400 + cx * 7 + cy * 13, s=4, col=PAPER)

seal_box(28, 83, 13)

for y in range(9):
    for x in range(7):
        if hnoise(372 + x, 210 + y, 95) < 0.16:
            continue
        put(372 + x, 210 + y, SEAL if hnoise(372 + x, 210 + y, 96) > 0.3 else SEAL_D)
for i in range(4):
    put(374 + i, 213, PAPER)
put(375, 215, PAPER); put(375, 216, PAPER); put(375, 217, PAPER)

# ---------------------------------------------------------------- 导出
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

out = sys.argv[1] if len(sys.argv) > 1 else "ops.json"
json.dump(ops, open(out, "w", encoding="utf-8"), ensure_ascii=False)
print("pixels=%d  ops=%d  colors=%d" % (len(px), len(ops), len(by_color)))
for c in sorted(by_color):
    print("   %s %6d" % (c, len(by_color[c])))
