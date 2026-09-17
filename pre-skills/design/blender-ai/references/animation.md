# 动画脚本教程：关键帧、驱动器、相机运动、渲染

## 1. 时间轴基础

```python
scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = 120
scene.render.fps = 24
scene.frame_set(42)          # 跳帧（会刷新依赖图）
```

## 2. 打关键帧（对象级）

```python
obj = bpy.data.objects["Cube"]
scene.frame_set(1)
obj.location = (0, 0, 1)
obj.keyframe_insert(data_path="location", frame=1)

scene.frame_set(60)
obj.location = (5, 0, 3)
obj.rotation_euler = (0, 0, 3.14159)
obj.keyframe_insert(data_path="location", frame=60)
obj.keyframe_insert(data_path="rotation_euler", frame=60)
```

对任意属性打帧：`obj.keyframe_insert(data_path='["自定义属性名"]')`、`mat.node_tree.nodes["Principled BSDF"].inputs["Roughness"].keyframe_insert("default_value", frame=30)`。

## 3. 用 FCurve 精调（插值、缓动、循环）

```python
action = obj.animation_data.action
# 5.x 起 action.fcurves 仍在（layered animation 另有一套，fcurves API 保持可用）
fc = action.fcurves.find("location", index=0)     # X 位移曲线
for kp in fc.keyframe_points:
    kp.interpolation = "BEZIER"        # CONSTANT / LINEAR / BEZIER / BACK / ELASTIC...
    kp.easing = "AUTO"

# 循环修改器（往复运动）
cyc = fc.modifiers.new("CYCLES")
cyc.mode_before = "REPEAT"
cyc.mode_after = "REPEAT"

# 读取某帧的曲线值
print(fc.evaluate(30))
```

## 4. 驱动器（属性联动）

```python
# 用 A 的 Z 位置驱动 B 的 Y 旋转
drv = wheel.driver_add("rotation_euler", 1).driver
var = drv.variables.new()
var.name = "z"
var.type = "TRANSFORMS"
var.targets[0].id = car_body
var.targets[0].transform_type = "LOC_Z"
var.targets[0].transform_space = "WORLD_SPACE"
drv.expression = "z * 10.0"
```

## 5. 相机沿路径运动

```python
# 曲线作为路径
curve_data = bpy.data.curves.new("CamPath", "CURVE")
curve_data.dimensions = "3D"
spline = curve_data.splines.new("BEZIER")
spline.bezier_points.add(3)
for bp, co in zip(spline.bezier_points, [(0,-8,3),(8,0,4),(0,8,3),(-8,0,2)]):
    bp.co = co; bp.handle_left_type = bp.handle_right_type = "AUTO"
spline.use_cyclic_u = True
path = bpy.data.objects.new("CamPath", curve_data)
bpy.context.scene.collection.objects.link(path)

# 相机加跟随路径约束
con = cam.constraints.new("FOLLOW_PATH")
con.target = path
con.use_curve_follow = True            # 相机朝向随曲线切线
curve_data.path_duration = 120         # 走完全程的帧数
scene.frame_set(1)
con.offset_factor = 0.0
con.keyframe_insert("offset_factor", frame=1)
scene.frame_set(120)
con.offset_factor = 1.0
con.keyframe_insert("offset_factor", frame=120)

# 注视目标（更稳的构图方式）
track = cam.constraints.new("TRACK_TO")
track.target = bpy.data.objects["HeroObject"]
track.track_axis = "TRACK_NEGATIVE_Z"
track.up_axis = "UP_Y"
```

## 6. 物体沿路径 / 简单物理替代

- 沿路径：同上加 `FOLLOW_PATH` 约束即可，任何对象都行。
- 复杂动力学（刚体/布料/流体）在纯脚本模式下可以 bake：`bpy.ops.ptcache.bake_all(bake=True)`，但后台 bake 慢且上下文敏感，建议在交互环境预先 bake 好，命令行只负责渲染。

## 7. 渲染动画

**命令行（首选）：**

```powershell
& $blender -b scene.blend -o "//frames/frame_####" -F PNG -s 1 -e 120 -a
```

**脚本内逐帧（可断点续渲，推荐长任务）：**

```python
import bpy, os
scene = bpy.context.scene
out_dir = bpy.path.abspath("//frames")
os.makedirs(out_dir, exist_ok=True)
for f in range(scene.frame_start, scene.frame_end + 1):
    path = os.path.join(out_dir, f"frame_{f:04d}.png")
    if os.path.exists(path):
        continue                          # 跳过已渲帧
    scene.frame_set(f)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print(f"[done] {f}", flush=True)
```

现成模板：../scripts/render_frames.py（支持 `--start/--end/--skip-existing/--engine/--samples`）。

## 8. PNG 序列合成视频

用 ffmpeg（Blender 自带的思想是交给外部工具最稳）：

```powershell
ffmpeg -framerate 24 -i frame_%04d.png -c:v libx264 -pix_fmt yuv420p -crf 18 out.mp4
```

## 9. 常见坑

- **改了属性没打帧**：动画只在 `keyframe_insert` 的帧上生效，其他帧靠插值；脚本里设值前确认当前帧 `scene.frame_set(n)`。
- **渲染出来全是第一帧**：通常是把 `-f 1` 当成了"渲染第 1 帧"却期望动画——用 `-a`；或脚本里循环渲染但忘了 `frame_set`。
- **帧率改了时长没变**：帧数不变、fps 变 → 播放时长变。时间重映射用 `scene.render.frame_map_old/new`（time remapping）。
- **5.x layered animation**：5.x 引入了分层动画底层，但 `keyframe_insert` / `action.fcurves` 工作流仍然有效；遇到 `action.fcurves` 为 None 的新结构时，用 `action.layers[0].strips[0].channelbag(...)` 相关 API 或直接用 `keyframe_insert`（推荐，兼容性最好）。
