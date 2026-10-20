#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pixbead — 拼豆式 CLI 像素画工具
================================
无服务端、无常驻进程：画布状态持久化在 JSON 文件中。

三步工作流:
  1) 初始化   python3 pixbead.py init  canvas.pix --width 32 --height 32
  2) 绘制     python3 pixbead.py pixel canvas.pix --set "3,4,#ff0000;5,6,#00ff00"
              python3 pixbead.py line  canvas.pix --from 0,0 --to 31,20 --color "#00f"
              python3 pixbead.py curve canvas.pix --points "0,0;16,31;31,0" --colors "red;#0f0;#0000ff"
  3) 出图     python3 pixbead.py render canvas.pix --out art.png --scale 16

批量绘制(适合 agent 一次提交大量操作):
  python3 pixbead.py batch canvas.pix --ops ops.json
  ops.json 示例:
  [
    {"op": "pixel", "set": "1,1,#f00;2,2,#0f0"},
    {"op": "line",  "from": "0,0", "to": "10,10", "color": "#00f"},
    {"op": "curve", "points": "0,0;8,16;15,0", "colors": "red;yellow;blue", "width": 2}
  ]
"""
import argparse, json, os, sys

# ---------------- 颜色解析 ----------------
NAMED = {
    "transparent": (0, 0, 0, 0),
    "black": (0, 0, 0, 255), "white": (255, 255, 255, 255),
    "red": (255, 0, 0, 255), "green": (0, 255, 0, 255), "blue": (0, 0, 255, 255),
    "yellow": (255, 255, 0, 255), "cyan": (0, 255, 255, 255), "magenta": (255, 0, 255, 255),
    "orange": (255, 165, 0, 255), "purple": (128, 0, 128, 255), "pink": (255, 192, 203, 255),
    "gray": (128, 128, 128, 255), "grey": (128, 128, 128, 255), "brown": (139, 69, 19, 255),
    "lime": (0, 128, 0, 255), "navy": (0, 0, 128, 255), "teal": (0, 128, 128, 255),
    "maroon": (128, 0, 0, 255), "olive": (128, 128, 0, 255), "silver": (192, 192, 192, 255),
}

def parse_color(s):
    """支持: 命名色 / #RGB / #RGBA / #RRGGBB / #RRGGBBAA / r,g,b[,a]"""
    s = s.strip()
    low = s.lower()
    if low in NAMED:
        return NAMED[low]
    if low.startswith("#"):
        h = low[1:]
        if len(h) == 3:
            return tuple(int(c * 2, 16) for c in h) + (255,)
        if len(h) == 4:
            return tuple(int(c * 2, 16) for c in h)
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
        if len(h) == 8:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
    parts = [int(p) for p in s.split(",")]
    if len(parts) == 3:
        parts.append(255)
    if len(parts) == 4 and all(0 <= p <= 255 for p in parts):
        return tuple(parts)
    raise ValueError(f"无法解析颜色: {s!r}")

def color_to_hex(c):
    return "#{:02x}{:02x}{:02x}{:02x}".format(*c)

def lerp_color(c1, c2, t):
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))

def gradient_color(colors, t):
    """t∈[0,1] 在节点颜色序列上线性插值(游戏引擎式渐变)"""
    if len(colors) == 1:
        return colors[0]
    pos = t * (len(colors) - 1)
    i = min(int(pos), len(colors) - 2)
    frac = pos - i
    return lerp_color(colors[i], colors[i + 1], frac)

def parse_point(s):
    x, y = s.split(",")
    return int(float(x)), int(float(y))

# ---------------- 画布读写 ----------------
def load_canvas(path):
    if not os.path.exists(path):
        sys.exit(f"画布文件不存在: {path} (先用 init 创建)")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_canvas(path, cv):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cv, f, ensure_ascii=False, separators=(",", ":"))

def put(cv, x, y, color):
    """画一颗"豆": 超出画布自动裁剪"""
    if 0 <= x < cv["width"] and 0 <= y < cv["height"]:
        if color[3] == 0:
            cv["pixels"].pop(f"{x},{y}", None)
        else:
            cv["pixels"][f"{x},{y}"] = color_to_hex(color)

def stamp(cv, x, y, color, width):
    r = width // 2
    for dx in range(-r, width - r):
        for dy in range(-r, width - r):
            put(cv, x + dx, y + dy, color)

# ---------------- 绘制算法 ----------------
def draw_line(cv, p0, p1, color_fn, width=1):
    """DDA 直线, color_fn(t) 沿 t∈[0,1] 取色"""
    x0, y0 = p0
    x1, y1 = p1
    steps = max(abs(x1 - x0), abs(y1 - y0))
    if steps == 0:
        stamp(cv, x0, y0, color_fn(0.0), width)
        return 1
    n = 0
    for i in range(steps + 1):
        t = i / steps
        x = round(x0 + (x1 - x0) * t)
        y = round(y0 + (y1 - y0) * t)
        stamp(cv, x, y, color_fn(t), width)
        n += 1
    return n

def de_casteljau(points, t):
    """任意阶贝塞尔曲线求点"""
    pts = [list(p) for p in points]
    while len(pts) > 1:
        pts = [[a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
               for a, b in zip(pts, pts[1:])]
    return pts[0]

def draw_curve(cv, points, colors, width=1, steps=None):
    n = len(points)
    if n < 2:
        sys.exit("曲线至少需要 2 个控制点")
    if steps is None:
        # 按控制点包围盒自动估算采样数, 保证不留空隙
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        steps = max(64, int((max(xs) - min(xs) + max(ys) - min(ys)) * 3))
    prev = None
    drawn = 0
    for i in range(steps + 1):
        t = i / steps
        fx, fy = de_casteljau(points, t)
        cur = (round(fx), round(fy))
        col = gradient_color(colors, t)
        if prev is None:
            stamp(cv, cur[0], cur[1], col, width)
            drawn += 1
        else:
            # 用渐变直线连接相邻采样点, 保证连续
            c0 = col
            drawn += draw_line(cv, prev, cur, lambda tt, c1=c0: c1, width)
        prev = cur
    return drawn

# ---------------- 命令实现 ----------------
def cmd_init(a):
    cv = {"width": a.width, "height": a.height, "pixels": {}}
    if a.background:
        bg = parse_color(a.background)
        for y in range(a.height):
            for x in range(a.width):
                put(cv, x, y, bg)
    save_canvas(a.file, cv)
    print(f"OK 初始化画布 {a.file}: {a.width}x{a.height}, 背景={a.background or '透明'}")

def cmd_pixel(a):
    cv = load_canvas(a.file)
    n = 0
    for item in a.set.split(";"):
        item = item.strip()
        if not item:
            continue
        xs, ys, cs = item.split(",", 2)
        put(cv, int(xs), int(ys), parse_color(cs))
        n += 1
    save_canvas(a.file, cv)
    print(f"OK 写入 {n} 个像素")

def cmd_line(a):
    cv = load_canvas(a.file)
    p0, p1 = parse_point(getattr(a, "from")), parse_point(a.to)
    if a.colors:
        colors = [parse_color(c) for c in a.colors.split(";")]
        fn = lambda t: gradient_color(colors, t)
    else:
        c = parse_color(a.color)
        fn = lambda t: c
    n = draw_line(cv, p0, p1, fn, a.width)
    save_canvas(a.file, cv)
    print(f"OK 直线 {p0} -> {p1}, 绘制 {n} 点")

def cmd_curve(a):
    cv = load_canvas(a.file)
    points = [parse_point(p) for p in a.points.split(";")]
    if a.colors:
        colors = [parse_color(c) for c in a.colors.split(";")]
        if len(colors) not in (1, len(points)):
            sys.exit(f"颜色数须为 1 或等于控制点数({len(points)}), 当前为 {len(colors)}")
    else:
        colors = [parse_color(a.color)]
    n = draw_curve(cv, points, colors, a.width, a.steps)
    save_canvas(a.file, cv)
    print(f"OK 曲线 {len(points)} 阶控制点, 绘制 {n} 点")

def cmd_rect(a):
    cv = load_canvas(a.file)
    x0, y0 = parse_point(a.origin)
    c = parse_color(a.color)
    for y in range(y0, y0 + a.h):
        for x in range(x0, x0 + a.w):
            if a.fill or x in (x0, x0 + a.w - 1) or y in (y0, y0 + a.h - 1):
                put(cv, x, y, c)
    save_canvas(a.file, cv)
    print(f"OK 矩形 ({x0},{y0}) {a.w}x{a.h}{' 填充' if a.fill else ' 边框'}")

def cmd_circle(a):
    cv = load_canvas(a.file)
    cx, cy = parse_point(a.center)
    c = parse_color(a.color)
    r = a.radius
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            if (a.fill and d2 <= r * r) or (not a.fill and abs(d2 - r * r) <= r):
                put(cv, x, y, c)
    save_canvas(a.file, cv)
    print(f"OK 圆 圆心({cx},{cy}) r={r}{' 填充' if a.fill else ' 轮廓'}")

def cmd_fill(a):
    """洪水填充: 从种子点扩散替换同色区域"""
    cv = load_canvas(a.file)
    sx, sy = parse_point(a.seed)
    target = cv["pixels"].get(f"{sx},{sy}")
    c = parse_color(a.color)
    new = color_to_hex(c)
    if target == new:
        print("OK 颜色相同, 无需填充")
        return
    stack, seen = [(sx, sy)], set()
    n = 0
    while stack:
        x, y = stack.pop()
        if (x, y) in seen or not (0 <= x < cv["width"] and 0 <= y < cv["height"]):
            continue
        seen.add((x, y))
        if cv["pixels"].get(f"{x},{y}") != target:
            continue
        put(cv, x, y, c)
        n += 1
        stack += [(x+1,y),(x-1,y),(x,y+1),(x,y-1)]
    save_canvas(a.file, cv)
    print(f"OK 填充 {n} 个像素")

def cmd_batch(a):
    ops = json.load(open(a.ops, encoding="utf-8")) if a.ops != "-" else json.load(sys.stdin)
    ns = argparse.Namespace
    for op in ops:
        kind = op.pop("op")
        if kind == "pixel":
            cmd_pixel(ns(file=a.file, **op))
        elif kind == "line":
            op.setdefault("color", "black"); op.setdefault("colors", None); op.setdefault("width", 1)
            cmd_line(ns(file=a.file, **op))
        elif kind == "curve":
            op.setdefault("color", "black"); op.setdefault("colors", None)
            op.setdefault("width", 1); op.setdefault("steps", None)
            cmd_curve(ns(file=a.file, **op))
        elif kind == "rect":
            op.setdefault("fill", False)
            cmd_rect(ns(file=a.file, **op))
        elif kind == "circle":
            op.setdefault("fill", False)
            cmd_circle(ns(file=a.file, **op))
        elif kind == "fill":
            cmd_fill(ns(file=a.file, **op))
        else:
            sys.exit(f"未知操作: {kind}")
    print(f"OK 批量完成 {len(ops)} 个操作")

def cmd_render(a):
    from PIL import Image
    cv = load_canvas(a.file)
    w, h = cv["width"], cv["height"]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for key, hx in cv["pixels"].items():
        x, y = map(int, key.split(","))
        img.putpixel((x, y), parse_color(hx))
    if a.scale != 1:
        img = img.resize((w * a.scale, h * a.scale), Image.NEAREST)
    img.save(a.out)
    print(f"OK 渲染 {a.out}: {w}x{h} (x{a.scale})")

def cmd_info(a):
    cv = load_canvas(a.file)
    print(json.dumps({"file": a.file, "width": cv["width"], "height": cv["height"],
                      "painted": len(cv["pixels"])}, ensure_ascii=False))

def main():
    ap = argparse.ArgumentParser(prog="pixbead", description="拼豆式 CLI 像素画工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="初始化画布文件")
    p.add_argument("file"); p.add_argument("--width", type=int, required=True)
    p.add_argument("--height", type=int, required=True)
    p.add_argument("--background", help="背景色, 默认透明")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("pixel", help="按像素点赋色(分号分隔多组)")
    p.add_argument("file"); p.add_argument("--set", required=True, help='"x,y,color;x,y,color"')
    p.set_defaults(fn=cmd_pixel)

    p = sub.add_parser("line", help="直线(可渐变)")
    p.add_argument("file"); p.add_argument("--from", required=True); p.add_argument("--to", required=True)
    p.add_argument("--color", default="black"); p.add_argument("--colors", help='渐变: "c1;c2;..."')
    p.add_argument("--width", type=int, default=1)
    p.set_defaults(fn=cmd_line)

    p = sub.add_parser("curve", help="贝塞尔曲线(任意阶, 节点颜色渐变)")
    p.add_argument("file"); p.add_argument("--points", required=True, help='"x,y;x,y;..."')
    p.add_argument("--color", default="black"); p.add_argument("--colors", help='每节点颜色: "c1;c2;..."')
    p.add_argument("--width", type=int, default=1); p.add_argument("--steps", type=int)
    p.set_defaults(fn=cmd_curve)

    p = sub.add_parser("rect", help="矩形")
    p.add_argument("file"); p.add_argument("--origin", required=True)
    p.add_argument("--w", type=int, required=True); p.add_argument("--h", type=int, required=True)
    p.add_argument("--color", default="black"); p.add_argument("--fill", action="store_true")
    p.set_defaults(fn=cmd_rect)

    p = sub.add_parser("circle", help="圆")
    p.add_argument("file"); p.add_argument("--center", required=True)
    p.add_argument("--radius", type=int, required=True)
    p.add_argument("--color", default="black"); p.add_argument("--fill", action="store_true")
    p.set_defaults(fn=cmd_circle)

    p = sub.add_parser("fill", help="洪水填充")
    p.add_argument("file"); p.add_argument("--seed", required=True); p.add_argument("--color", required=True)
    p.set_defaults(fn=cmd_fill)

    p = sub.add_parser("batch", help="从 JSON 批量执行操作")
    p.add_argument("file"); p.add_argument("--ops", required=True, help='JSON 文件路径, "-" 表示 stdin')
    p.set_defaults(fn=cmd_batch)

    p = sub.add_parser("render", help="渲染为 PNG")
    p.add_argument("file"); p.add_argument("--out", required=True)
    p.add_argument("--scale", type=int, default=1)
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("info", help="查看画布信息")
    p.add_argument("file")
    p.set_defaults(fn=cmd_info)

    a = ap.parse_args()
    a.fn(a)

if __name__ == "__main__":
    main()
