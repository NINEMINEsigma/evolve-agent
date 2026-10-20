# 像素角色绘制工作流（生成器模式）

画像素角色/复杂图案的标准流程：Python 内存画布 → 形状栅格化 → 导出 batch JSON → pixbead 执行渲染 → 目检 → 局部重画迭代。

## 1. 内存画布与形状辅助函数

```python
W = H = 128
px = {}  # (x,y) -> "#rrggbb"

def put(x, y, c):
    if 0 <= x < W and 0 <= y < H:
        px[(x, y)] = c

def ellipse(cx, cy, rx, ry, c):
    for y in range(int(cy-ry), int(cy+ry)+1):
        for x in range(int(cx-rx), int(cx+rx)+1):
            if ((x-cx)/max(rx,1))**2 + ((y-cy)/max(ry,1))**2 <= 1.0:
                put(x, y, c)

def poly(pts, c):  # 扫描线填充多边形
    ys = [p[1] for p in pts]
    for y in range(min(ys), max(ys)+1):
        xs = []
        for i in range(len(pts)):
            x1,y1 = pts[i]; x2,y2 = pts[(i+1)%len(pts)]
            if (y1 <= y < y2) or (y2 <= y < y1):
                xs.append(x1 + (x2-x1)*(y-y1)/(y2-y1))
        xs.sort()
        for i in range(0, len(xs)-1, 2):
            for x in range(round(xs[i]), round(xs[i+1])+1):
                put(x, y, c)

def rect(x0, y0, w, h, c):
    for y in range(y0, y0+h):
        for x in range(x0, x0+w):
            put(x, y, c)
```

## 2. 图层顺序（后画覆盖先画）

1. 后发/披风等最底层轮廓
2. 头饰后侧部分
3. 腿脚 → 裙摆 → 上身 → 袖子 → 手
4. 脸部底色 → 前发/刘海/鬓发 → 发饰
5. 五官：眼睛（虹膜+上深下浅+双高光+睫毛线）、眉毛、嘴、腮红
6. 细节线条（发丝、衣褶阴影）
7. 外轮廓自动描边：

```python
silhouette = set()
for (x, y) in list(px):
    for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
        if (x+dx, y+dy) not in px:
            silhouette.add((x, y))
for (x, y) in silhouette:
    px[(x, y)] = OUTLINE
```

描边在透明邻接处生成，只影响剪影边界，不会盖住内部五官；但会覆盖边界上的浅色（如白袜外缘），必要时描边后重新压上高光/五官像素。

描边后若又修改了某区域，先把该区域的旧 OUTLINE 色像素 pop 掉再重算，否则旧边界线会残留成内部黑线。

## 3. 导出 batch JSON 并执行

```python
from collections import defaultdict
import json

by_color = defaultdict(list)
for (x, y), c in px.items():
    by_color[c].append((x, y))
ops = []
for c, pts in by_color.items():
    entries = [f"{x},{y},{c}" for x, y in pts]
    for i in range(0, len(entries), 800):      # 每个 op 最多 800 像素
        ops.append({"op": "pixel", "set": ";".join(entries[i:i+800])})
json.dump(ops, open('/tmp/ops.json', 'w'))
```

```bash
python3 scripts/pixbead.py init art.pix --width 128 --height 128
python3 scripts/pixbead.py batch art.pix --ops /tmp/ops.json
python3 scripts/pixbead.py render art.pix --out art.png --scale 6
```

## 4. 目检与迭代

- 渲染 `--scale 6`（128 画布 → 768px）目检。
- 局部修正：清掉出错区域（`for y in range(...): for x in range(...): px.pop((x,y), None)`）→ 重画 → 重算轮廓 → 重新导出全部 ops 重放。重放是幂等的，成本只是几秒。
- 常见坑：
  - 清空区域后忘记补回被覆盖的上层形状 → 出现悬空色带。清空后按图层顺序重画该区域涉及的所有形状。
  - 渐变曲线颜色数必须等于控制点数（或只给 1 个色），否则 curve 报错。
  - `fill` 洪水填充要求区域封闭，生成器模式下优先用 poly/ellipse 直接填充，少依赖 fill。

## 5. 造型参考要点（Q 版全身像, 128×128）

以头顶到脚底 6~120 行布局：头饰 y2–26、头发 y20–60+、脸 y26–58、五官 y34–54、颈饰 y56–66、上身 y58–84、裙摆 y80–106、袜 y106–119、鞋 y117–125。眼睛宽 4 高 6 起步；腮红 4×2 贴眼下；微笑 3~5 像素宽。色板控制在 15 色以内：轮廓深棕黑（比纯黑柔和）、每材质一主色+一阴影+一高光。
