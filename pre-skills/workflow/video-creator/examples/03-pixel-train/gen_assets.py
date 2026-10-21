"""像素风列车场景素材生成器（v3：远景列车 + 近景草木的纵深构图）。

按 pixbead 的范式：用 Python 把造型栅格化成 batch ops，交给 pixbead 执行与渲染。
逻辑画布 320×180，最终由 Remotion 放大 6 倍到 1920×1080。

垂直布局（"列车挡太阳"能成立的关键）：
  y=0..138     天空（黄昏金橙色带）
  y=109..123   太阳（r=7，贴地平线，落在远山上方）
  y=114..140   三层山脊
  y=138..142   路基 / 道砟
  y=140..141   钢轨（列车压在上面）
  y=106..140   列车（车顶 y=112，遮住太阳的 112..123，只在顶上漏一线光）
  y=145..180   中景草 → 近景草 → 前景芦苇

纵向关系：列车在远景（高 34px），近景草 16~22px 但基座在 y=168~180，
透视上比列车"大"，形成长焦压缩后的纵深。
"""
import json
import math
import os
import subprocess
import sys

W, H = 320, 180
HORIZON = 138
SUN = (250, 116)
SUN_R = 7
RAIL_Y = 140
HERE = os.path.dirname(os.path.abspath(__file__))
# 中间文件（.pix 画布 / .ops.json 批处理）与检查图放这里，不污染样例目录
WORK = os.path.join(HERE, ".work")
# pixbead 与本技能同属 skills/workflow/ 下的兄弟技能；可用 PIXBEAD_SCRIPT 环境变量覆盖
PIXBEAD = os.environ.get("PIXBEAD_SCRIPT") or os.path.abspath(
    os.path.join(HERE, "..", "..", "..", "pixbead", "scripts", "pixbead.py")
)
# 素材默认输出到本样例目录的 assets/；放进 Remotion 工程时用 PIXEL_ASSETS 指向 public/pixel
ASSETS = os.environ.get("PIXEL_ASSETS") or os.path.join(HERE, "assets")

SKY_STOPS = [
    (0.00, (36, 22, 58)),
    (0.12, (52, 28, 70)),
    (0.24, (78, 38, 86)),
    (0.36, (110, 52, 94)),
    (0.46, (146, 66, 92)),
    (0.56, (184, 84, 82)),
    (0.66, (214, 108, 64)),
    (0.78, (240, 146, 56)),
    (0.88, (252, 182, 70)),
    (0.96, (255, 214, 112)),
    (1.00, (255, 236, 164)),
]
SUN_CORE = (255, 250, 216)
SUN_EDGE = (255, 232, 150)
GLOW = (255, 198, 96)

M_FAR = (176, 106, 126)
M_MID = (125, 70, 97)
M_NEAR = (69, 43, 73)

G_BED = (42, 31, 48)
G_NEAR = (30, 21, 35)
G_PEBBLE_L = (74, 54, 72)
G_PEBBLE_D = (24, 16, 29)

RAIL = (206, 138, 100)
SLEEPER = (58, 42, 56)

BODY = (42, 33, 48)
BODY_LOW = (54, 41, 61)
WIN = (255, 184, 92)
WIN_TOP = (233, 146, 78)
RIM = (255, 222, 150)
BOGIE = (26, 19, 31)
WHEEL = (96, 70, 68)
PANT = (34, 25, 40)

GRASS = (28, 20, 36)
GRASS_RIM = (217, 154, 94)

BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def hash01(x, y, seed=0):
    n = (x * 374761393 + y * 668265263 + seed * 1442695040888963407) & 0xFFFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFFFFFF) / 0xFFFFFFFF


def bayer(x, y):
    return BAYER[y % 4][x % 4] / 16.0


def hx(c):
    return "#%02x%02x%02x" % c


class Layer:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = {}

    def set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[(int(x), int(y))] = color

    def ops(self):
        items = ["%d,%d,%s" % (x, y, hx(c)) for (x, y), c in sorted(self.px.items())]
        out = []
        for i in range(0, len(items), 800):
            out.append({"op": "pixel", "set": ";".join(items[i:i + 800])})
        return out


def sky_color(y):
    t = y / (HORIZON - 1)
    for i in range(len(SKY_STOPS) - 1):
        a, ca = SKY_STOPS[i]
        b, cb = SKY_STOPS[i + 1]
        if a <= t <= b:
            return ca, cb, (t - a) / max(b - a, 1e-6)
    return SKY_STOPS[-1][1], SKY_STOPS[-1][1], 0.0


def build_sky():
    L = Layer(W, H)
    soft = 0.34
    for y in range(HORIZON):
        ca, cb, f = sky_color(y)
        for x in range(W):
            if f <= 0.5 - soft / 2:
                c = ca
            elif f >= 0.5 + soft / 2:
                c = cb
            else:
                k = (f - (0.5 - soft / 2)) / soft
                c = cb if bayer(x, y) < k else ca
            # 打散水平色带的观感：纯色区里掺 4% 相邻色
            r = hash01(x, y, 3)
            if r < 0.02:
                c = ca if c == cb else cb
            L.set(x, y, c)
    # 太阳
    for y in range(HORIZON):
        for x in range(W):
            d = math.hypot(x - SUN[0], y - SUN[1])
            if d <= SUN_R - 2:
                L.set(x, y, SUN_CORE)
            elif d <= SUN_R:
                L.set(x, y, SUN_EDGE)
    # 光晕
    for y in range(HORIZON):
        for x in range(W):
            d = math.hypot(x - SUN[0], y - SUN[1])
            if SUN_R < d <= 28:
                strength = (1 - (d - SUN_R) / 21.0) ** 1.5
                if hash01(x, y, 7) < strength * 0.82:
                    L.set(x, y, GLOW)
    return L


# ---------------------------------------------------------------- 云（晚霞积云）
CLOUD_STOPS = [
    (0.00, (107, 74, 120)),
    (0.20, (143, 95, 131)),
    (0.38, (201, 122, 140)),
    (0.55, (245, 155, 115)),
    (0.72, (255, 196, 107)),
    (0.88, (255, 233, 168)),
]

# 椭圆的并集定轮廓：主云竖向堆叠成高耸的积云，右侧两朵小的做纵深
CLOUD_PUFFS = [
    (52, 96, 46, 26),
    (34, 78, 34, 24),
    (74, 74, 36, 26),
    (56, 60, 28, 20),
    (40, 46, 22, 16),
    (88, 92, 30, 22),
    (18, 100, 30, 20),
    (104, 62, 24, 18),
    (66, 34, 18, 13),
    (12, 84, 24, 18),
    (168, 52, 13, 9),
    (187, 61, 10, 7),
]


def sample_stops(stops, f, x, y, soft=0.35):
    """把 0~1 的连续值映射到限色色带，交界处用 Bayer 抖动"""
    for i in range(len(stops) - 1):
        a, ca = stops[i]
        b, cb = stops[i + 1]
        if a <= f <= b:
            k = (f - a) / max(b - a, 1e-6)
            if k < 0.5 - soft / 2:
                return ca
            if k > 0.5 + soft / 2:
                return cb
            return cb if bayer(x, y) < (k - (0.5 - soft / 2)) / soft else ca
    return stops[-1][1]


# 云内部的裂隙：挖穿这些椭圆，形成云朵之间的缝隙
CLOUD_HOLES = [
    (30, 97, 12, 8),
    (68, 81, 10, 7),
    (86, 59, 9, 6),
    (48, 46, 7, 5),
]


def cloud_membership(x, y):
    """>0 表示落在云内，值越大越靠内。每个瓣的半径按极角调制，轮廓呈波浪状而不是正椭圆"""
    best = -1.0
    for i, (cx, cy, rx, ry) in enumerate(CLOUD_PUFFS):
        dx = x - cx
        dy = y - cy
        ang = math.atan2(dy / max(ry, 1.0), dx / max(rx, 1.0))
        wob = 1.0 + 0.20 * math.sin(ang * 3 + i * 1.7) + 0.11 * math.sin(ang * 5 - i * 2.3)
        v = 1.0 - (dx / (rx * wob)) ** 2 - (dy / (ry * wob)) ** 2
        if v > best:
            best = v
    return best


def build_clouds():
    L = Layer(W, H)
    for y in range(18, HORIZON + 2):
        for x in range(W):
            m = cloud_membership(x, y)
            if m <= 0:
                continue
            # 轮廓边缘 50% 概率缺一块，形成破碎起伏
            if m < 0.12 and hash01(x, y, 13) < 0.5:
                continue
            # 明暗：夕阳从下方照亮云底，高度是主因，离太阳远近为辅
            ds = math.hypot((x - SUN[0]) * 0.85, (y - SUN[1]) * 0.55) / 190.0
            bright = 0.25 * (1 - min(1.0, ds)) + 0.75 * (y / HORIZON)
            bright += (hash01(x, y, 5) - 0.5) * 0.09
            # 裂隙：不挖穿，压暗一档形成云内部的凹处与层次
            for hx, hy, hrx, hry in CLOUD_HOLES:
                if ((x - hx) / hrx) ** 2 + ((y - hy) / hry) ** 2 <= 1:
                    bright -= 0.22
                    break
            bright = max(0.0, min(1.0, bright))
            L.set(x, y, sample_stops(CLOUD_STOPS, bright, x, y))
    return L


def ridge_y(x, pts):
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        if x0 <= x <= x1:
            f = (x - x0) / max(x1 - x0, 1e-6)
            return y0 + (y1 - y0) * f
    return pts[-1][1]


def build_mountains():
    L = Layer(W, H)
    layers = [
        (
            [(0, 120), (40, 114), (80, 124), (120, 116), (160, 126), (200, 118), (232, 126), (258, 127), (286, 118), (320, 124)],
            M_FAR,
            11,
        ),
        (
            [(0, 128), (44, 123), (92, 131), (140, 125), (186, 133), (228, 130), (272, 126), (320, 131)],
            M_MID,
            21,
        ),
        (
            [(0, 135), (56, 132), (112, 139), (168, 134), (220, 141), (280, 136), (320, 141)],
            M_NEAR,
            33,
        ),
    ]
    for pts, color, seed in layers:
        for x in range(W):
            ry = ridge_y(x, pts)
            ry += (hash01(x, 0, seed) - 0.5) * 2
            for y in range(int(ry), HORIZON + 8):
                L.set(x, y, color)
    return L


def build_ground():
    L = Layer(W, H)
    # 路基（轨道那一带）与近景草地
    for y in range(HORIZON, H):
        c = G_BED if y < 148 else G_NEAR
        for x in range(W):
            L.set(x, y, c)
    # 草色过渡：越近越暗，掺入少量亮点
    for y in range(HORIZON, H):
        for x in range(W):
            t = (y - HORIZON) / (H - HORIZON)
            if hash01(x, y, 17) < 0.05:
                L.set(x, y, (46, 33, 52) if t < 0.5 else (40, 28, 46))
    # 碎石
    for y in range(HORIZON, H):
        for x in range(W):
            density = 0.02 + (y - HORIZON) / (H - HORIZON) * 0.05
            if hash01(x, y, 55) < density:
                L.set(x, y, G_PEBBLE_L if hash01(x, y, 77) > 0.45 else G_PEBBLE_D)
    # 钢轨顶面
    for y in (RAIL_Y, RAIL_Y + 1):
        for x in range(W):
            L.set(x, y, RAIL)
    # 枕木
    for x in range(0, W, 12):
        for dx in range(7):
            for y in (RAIL_Y + 2, RAIL_Y + 3, RAIL_Y + 4):
                L.set(x + dx, y, SLEEPER)
    return L


def build_train():
    """电力动车侧视，朝左，460×34（比画面还长，能出现"完全贯穿左右"的瞬间）"""
    TW, TH = 460, 34
    L = Layer(TW, TH)
    roof = 6
    body_bot = 26
    nose = 48

    def top_at(x):
        if x < nose:
            return roof + int(10 * ((nose - x) / nose) ** 2.2)
        return roof

    for x in range(TW):
        t = top_at(x)
        for y in range(t, body_bot):
            L.set(x, y, BODY_LOW if y > body_bot - 5 else BODY)
    # 车顶轮廓光
    for x in range(TW):
        L.set(x, top_at(x), RIM)
    # 车窗：16 个
    for x in range(66, TW - 12, 24):
        for dx in range(14):
            xx = x + dx
            if xx >= TW - 6:
                continue
            L.set(xx, 11, WIN_TOP)
            for y in range(12, 19):
                L.set(xx, y, WIN)
    # 车头驾驶窗
    for x in range(14, nose):
        for y in range(10, 20):
            if y >= top_at(x) + 1:
                L.set(x, y, WIN)
    # 车头前缘光
    for x in range(nose):
        t = top_at(x)
        L.set(x, t + 1, RIM)
    # 裙板
    for x in range(TW):
        for y in range(body_bot - 4, body_bot):
            L.set(x, y, BOGIE)
    # 四组转向架
    for bx in (60, 175, 290, 400):
        for x in range(bx, bx + 26):
            if x >= TW:
                continue
            for y in range(body_bot, body_bot + 8):
                L.set(x, y, BOGIE)
        for wx in (bx + 3, bx + 16):
            for x in range(wx, wx + 9):
                if x >= TW:
                    continue
                for y in range(body_bot + 1, body_bot + 8):
                    d = math.hypot(x - (wx + 4), y - (body_bot + 4))
                    if d < 3.6:
                        L.set(x, y, (16, 11, 20))
                    elif d < 4.3:
                        L.set(x, y, WHEEL)
    # 三组受电弓
    for px0 in (140, 270, 390):
        pant = [(px0, 6), (px0 + 8, 1), (px0 + 20, 1), (px0 + 28, 6)]
        for i in range(len(pant) - 1):
            x0, y0 = pant[i]
            x1, y1 = pant[i + 1]
            steps = int(max(abs(x1 - x0), abs(y1 - y0), 1))
            for s in range(steps + 1):
                f = s / steps
                L.set(round(x0 + (x1 - x0) * f), round(y0 + (y1 - y0) * f), PANT)
    return L


def grass_blade(L, x0, y0, x1, y1, color, rim=None):
    steps = int(max(abs(x1 - x0), abs(y1 - y0), 1))
    for s in range(steps + 1):
        f = s / steps
        L.set(round(x0 + (x1 - x0) * f), round(y0 + (y1 - y0) * f), color)
    if rim:
        L.set(round(x1), round(y1), rim)


def build_grass(seed, count, size, base_y_range, x_range, big=False, var_index=0, n_var=1):
    """按 var_index 把草分散到 n_var 个变体层，Remotion 里各层独立做风摆"""
    L = Layer(W, H)
    for i in range(count):
        if i % n_var != var_index:
            continue
        cx = int(x_range[0] + hash01(i, 1, seed) * (x_range[1] - x_range[0]))
        by = int(base_y_range[0] + hash01(i, 2, seed) * (base_y_range[1] - base_y_range[0]))
        hgt = size * (0.6 + hash01(i, 3, seed) * 0.8)
        n = 3 if big else 2
        for b in range(n):
            off = (b - (n - 1) / 2) * (size * 0.34)
            tilt = (hash01(i, 10 + b, seed) - 0.5) * size * 0.55
            rim = GRASS_RIM if (big and hash01(i, 99, seed) > 0.55) else None
            grass_blade(L, cx + off * 0.5, by, cx + off + tilt, by - hgt, GRASS, rim)
    return L


def build_reeds(var_index=0, n_var=1):
    """右下角前景芦苇：高、向外弯，压住画面一角；按变体拆分以便摆动"""
    L = Layer(W, H)
    clusters = [(302, 180, 54), (316, 180, 64), (286, 180, 40)]
    for ci, (cx, by, hgt) in enumerate(clusters):
        if ci % n_var != var_index:
            continue
        for b in range(5):
            off = (b - 2) * 3
            leaf_x = cx + off + (hash01(cx, b, 5) - 0.5) * 10
            mx = (cx + off + leaf_x) / 2 - 7
            my = by - hgt * 0.55
            for s in range(41):
                f = s / 40
                x = (1 - f) ** 2 * (cx + off) + 2 * (1 - f) * f * mx + f * f * leaf_x
                y = (1 - f) ** 2 * by + 2 * (1 - f) * f * my + f * f * (by - hgt)
                L.set(round(x), round(y), GRASS)
            L.set(round(leaf_x), round(by - hgt), GRASS_RIM)
    return L


def run_pixbead(name, layer):
    os.makedirs(ASSETS, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    pix = os.path.join(WORK, name + ".pix")
    ops_path = os.path.join(WORK, name + ".ops.json")
    png = os.path.join(ASSETS, name + ".png")
    with open(ops_path, "w", encoding="utf-8") as f:
        json.dump(layer.ops(), f)
    subprocess.run([sys.executable, PIXBEAD, "init", pix, "--width", str(layer.w), "--height", str(layer.h)], check=True, capture_output=True)
    subprocess.run([sys.executable, PIXBEAD, "batch", pix, "--ops", ops_path], check=True, capture_output=True)
    subprocess.run([sys.executable, PIXBEAD, "render", pix, "--out", png, "--scale", "1"], check=True, capture_output=True)
    print("%-12s %6d px -> %s" % (name, len(layer.px), os.path.basename(png)))


def main():
    layers = {
        "sky": build_sky(),
        "clouds": build_clouds(),
        "mountains": build_mountains(),
        "ground": build_ground(),
        "train": build_train(),
    }
    # 草按 3 个变体拆分：Remotion 里各层用不同相位做风摆，形成波浪感
    for v in range(3):
        layers["grass_mid_%d" % v] = build_grass(11, 66, 8, (144, 164), (4, 300), False, v, 3)
        layers["grass_fg_%d" % v] = build_grass(23, 39, 18, (166, 180), (2, 316), True, v, 3)
        layers["reeds_%d" % v] = build_reeds(v, 3)
    for name, layer in layers.items():
        run_pixbead(name, layer)

    from PIL import Image

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    for name in ["sky", "clouds", "mountains", "ground"] + ["grass_mid_%d" % v for v in range(3)]:
        canvas.alpha_composite(Image.open(os.path.join(ASSETS, name + ".png")).convert("RGBA"), (0, 0))
    canvas.alpha_composite(Image.open(os.path.join(ASSETS, "train.png")).convert("RGBA"), (150, RAIL_Y - 34))
    for name in ["grass_fg_%d" % v for v in range(3)] + ["reeds_%d" % v for v in range(3)]:
        canvas.alpha_composite(Image.open(os.path.join(ASSETS, name + ".png")).convert("RGBA"), (0, 0))
    canvas.resize((W * 4, H * 4), Image.NEAREST).save(os.path.join(WORK, "composite_check.png"))
    # 无列车版：检查太阳、山与草的关系
    flat = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    for name in (
        ["sky", "clouds", "mountains", "ground"]
        + ["grass_mid_%d" % v for v in range(3)]
        + ["grass_fg_%d" % v for v in range(3)]
        + ["reeds_%d" % v for v in range(3)]
    ):
        flat.alpha_composite(Image.open(os.path.join(ASSETS, name + ".png")).convert("RGBA"), (0, 0))
    flat.resize((W * 4, H * 4), Image.NEAREST).save(os.path.join(WORK, "composite_hero.png"))
    print("composite_check.png / composite_hero.png 已生成")


if __name__ == "__main__":
    main()
