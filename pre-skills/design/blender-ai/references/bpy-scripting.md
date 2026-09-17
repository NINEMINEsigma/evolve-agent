# bpy 脚本教程：数据模型与场景构建

> 在 Blender 内运行的 Python（`blender -b -P script.py`）。官方 API 文档：https://docs.blender.org/api/current/ 。本文按"从零建场景"的顺序讲核心概念与可直接套用的代码。

## 目录

1. 数据模型：bpy.data / bpy.context / bpy.ops
2. 脚本骨架与参数解析
3. 清空场景
4. 创建对象（图元、网格、曲线、文字）
5. 变换与父级
6. 集合（Collection）管理
7. 修改器
8. 材质与着色节点
9. 灯光
10. 相机与自动取景
11. 世界环境
12. 单位与场景设置
13. 后台模式的上下文规则（必读）

## 1. 数据模型：三个入口

- **`bpy.data`**：整个 .blend 文件的"数据库"——`bpy.data.objects`、`.meshes`、`.materials`、`.cameras`、`.images` 等。**数据 API 不依赖 UI 上下文，后台模式首选。**
- **`bpy.context`**：当前上下文（活动对象、选中项、当前场景）。后台模式下很多字段是 `None`。
- **`bpy.ops`**：算子，模拟用户按键操作，多数依赖上下文。能用数据 API 就不用算子。

一条数据 = 一个 ID 数据块（datablock）。对象（Object）只是"实例"，真正存几何的是 Mesh/Curve 等数据块，一个 Mesh 可以被多个 Object 引用。

## 2. 脚本骨架与参数解析

```python
import bpy, sys, argparse

def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(description="任务说明")
    p.add_argument("--output", default="//out.png")
    return p.parse_args(argv)

def main():
    args = parse_args()
    ...

if __name__ == "__main__":
    main()
```

调用：`& $blender -b --factory-startup --python-exit-code 1 -P script.py -- --output $outPng`

## 3. 清空场景

```python
# 方式一：恢复出厂空场景（连默认立方体都不要）
bpy.ops.wm.read_factory_settings(use_empty=True)

# 方式二：只删对象（保留场景设置）
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
# 顺手清理孤儿数据块（网格、材质等）
for coll in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
    for block in list(coll):
        if block.users == 0:
            coll.remove(block)
```

## 4. 创建对象

### 4.1 图元（算子，最简单，但依赖上下文）

```python
bpy.ops.mesh.primitive_cube_add(location=(0, 0, 1))
cube = bpy.context.active_object          # 算子新建的对象会成为 active
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, location=(2, 0, 1))
bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=2, location=(-2, 0, 1))
bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
bpy.ops.mesh.primitive_torus_add(major_radius=1.0, minor_radius=0.3)
bpy.ops.mesh.primitive_cone_add(radius1=1, radius2=0, depth=2)   # 圆锥
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1)
```

> 后台模式下 `primitive_*_add` 是少数上下文要求很低的算子（4.x/5.x 均可用），但仍建议配合 `--factory-startup` 使用。

### 4.2 纯数据 API 建网格（推荐，零上下文依赖）

```python
import bpy
from mathutils import Vector

verts = [(0,0,0), (1,0,0), (1,1,0), (0,1,0), (0.5,0.5,1)]   # 顶点坐标
faces = [(0,1,2,3), (0,1,4), (1,2,4), (2,3,4), (3,0,4)]     # 面（顶点索引）

mesh = bpy.data.meshes.new("PyramidMesh")
mesh.from_pydata(verts, [], faces)     # (顶点, 边, 面)；边可留空自动推断
mesh.update()

obj = bpy.data.objects.new("Pyramid", mesh)
bpy.context.scene.collection.objects.link(obj)   # 必须 link 到集合才会出现在场景里
```

平滑着色（数据 API 写法，5.x/4.1+）：

```python
for poly in mesh.polygons:
    poly.use_smooth = True
```

### 4.3 曲线 / 文字

```python
# 文字对象
font_curve = bpy.data.curves.new("TextCurve", type="FONT")
font_curve.body = "HELLO"
font_curve.extrude = 0.05               # 挤出厚度
font_curve.bevel_depth = 0.01           # 倒角
text_obj = bpy.data.objects.new("Text", font_curve)
text_obj.location = (0, 0, 2)
bpy.context.scene.collection.objects.link(text_obj)

# 贝塞尔/多段线（POLY 样条）
curve = bpy.data.curves.new("Path", type="CURVE")
curve.dimensions = "3D"
spline = curve.splines.new("BEZIER")
spline.bezier_points.add(2)
for bp, co in zip(spline.bezier_points, [(0,0,0), (2,0,1), (4,0,0)]):
    bp.co = co
    bp.handle_left_type = bp.handle_right_type = "AUTO"
curve.bevel_depth = 0.05                # 给曲线一个管状截面
path_obj = bpy.data.objects.new("Path", curve)
bpy.context.scene.collection.objects.link(path_obj)
```

## 5. 变换与父级

```python
obj.location = (1, 2, 3)
obj.rotation_euler = (0.0, 0.0, 1.5708)          # 弧度；XYZ 欧拉
obj.scale = (2, 2, 2)
obj.rotation_mode = "QUATERNION"                  # 需要四元数时
obj.rotation_quaternion = (1, 0, 0, 0)            # (w, x, y, z)

obj.parent = parent_obj                           # 设父级（保持当前世界变换需用 matrix_world 技巧）
mw = obj.matrix_world.copy()
obj.parent = parent_obj
obj.matrix_world = mw
```

应用变换（把缩放"烘"进网格，导出前常需要）：

```python
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
```

## 6. 集合管理

```python
coll = bpy.data.collections.new("Props")
bpy.context.scene.collection.children.link(coll)   # 挂到场景根集合
coll.objects.link(obj)                             # 把对象移入
# 从其他集合移除
for c in list(obj.users_collection):
    if c != coll:
        c.objects.unlink(obj)
```

## 7. 修改器（非破坏性建模）

```python
mod = obj.modifiers.new(name="Bevel", type="BEVEL")
mod.width = 0.05
mod.segments = 3

sub = obj.modifiers.new(name="Subsurf", type="SUBSURF")
sub.levels = 2            # 视口级数
sub.render_levels = 3     # 渲染级数

array = obj.modifiers.new(name="Array", type="ARRAY")
array.count = 5
array.relative_offset_displace = (1.2, 0, 0)

boolean = obj.modifiers.new(name="Bool", type="BOOLEAN")
boolean.operation = "DIFFERENCE"
boolean.object = cutter_obj
```

应用修改器（需要对象处于活动状态）：

```python
bpy.context.view_layer.objects.active = obj
bpy.ops.object.modifier_apply(modifier="Bevel")
```

## 8. 材质与着色节点

### 8.1 最小可用材质（Principled BSDF）

```python
mat = bpy.data.materials.new("Metal")
mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.8, 0.2, 0.1, 1.0)   # RGBA
bsdf.inputs["Metallic"].default_value = 1.0
bsdf.inputs["Roughness"].default_value = 0.25

obj.data.materials.append(mat)          # 网格对象挂材质
# 曲线/文字：font_curve.materials.append(mat)
```

> 5.x 的 Principled BSDF 输入名：`Base Color`、`Metallic`、`Roughness`、`IOR`、`Alpha`、`Emission Color`、`Emission Strength`、`Coat Weight` 等。版本间输入名会变，稳妥写法是 `bsdf.inputs.get("Coat Weight") or bsdf.inputs.get("Clearcoat")` 这种兼容取法。

### 8.2 贴图材质（图片纹理）

```python
mat = bpy.data.materials.new("Textured")
mat.use_nodes = True
nt = mat.node_tree
bsdf = nt.nodes["Principled BSDF"]

tex = nt.nodes.new("ShaderNodeTexImage")
tex.image = bpy.data.images.load(r"D:\assets\albedo.jpg")
nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

# 法线贴图要过 Normal Map 节点
nmap_tex = nt.nodes.new("ShaderNodeTexImage")
nmap_tex.image = bpy.data.images.load(r"D:\assets\normal.png")
nmap_tex.image.colorspace_settings.name = "Non-Color"   # 法线/粗糙度贴图必须 Non-Color
nmap = nt.nodes.new("ShaderNodeNormalMap")
nt.links.new(nmap_tex.outputs["Color"], nmap.inputs["Color"])
nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
```

### 8.3 程序化纹理示例（噪波 → 颜色渐变）

```python
noise = nt.nodes.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 5.0
ramp = nt.nodes.new("ShaderNodeValToRGB")
ramp.color_ramp.elements[0].color = (0.02, 0.05, 0.2, 1)
ramp.color_ramp.elements[1].color = (0.9, 0.4, 0.05, 1)
nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
```

### 8.4 发光与透明

```python
bsdf.inputs["Emission Color"].default_value = (1.0, 0.6, 0.1, 1)
bsdf.inputs["Emission Strength"].default_value = 5.0     # EEVEE/Cycles 均可发光
# 玻璃质感
bsdf.inputs["Roughness"].default_value = 0.05
bsdf.inputs["Transmission Weight"].default_value = 1.0   # 4.x/5.x 名；旧版叫 "Transmission"
```

## 9. 灯光

```python
def add_light(name, light_type, location, energy, color=(1, 1, 1), **kw):
    data = bpy.data.lights.new(name, type=light_type)   # 'POINT' 'SUN' 'SPOT' 'AREA'
    data.energy = energy                                 # 瓦特（SUN 是强度）
    data.color = color
    for k, v in kw.items():                              # 如 size=5 (AREA), spot_size=... (SPOT)
        setattr(data, k, v)
    obj = bpy.data.objects.new(name, data)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj

key  = add_light("Key",  "AREA", (4, -4, 6), 1000, size=5)
fill = add_light("Fill", "AREA", (-4, -2, 3), 400, color=(0.7, 0.8, 1.0), size=4)
sun  = add_light("Sun",  "SUN",  (0, 0, 10), 3.0)
sun.rotation_euler = (0.6, 0.1, 0.8)     # SUN 的方向由旋转决定，位置无所谓
```

让灯/相机"看向"某点：

```python
def point_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
```

## 10. 相机与自动取景

```python
cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 50                       # 焦距 mm
cam = bpy.data.objects.new("Cam", cam_data)
bpy.context.scene.collection.objects.link(cam)
bpy.context.scene.camera = cam           # 设为场景相机（必须，否则渲染报 No camera）
```

**自动取景**：计算所有对象包围盒，把相机放到能看全的距离：

```python
from mathutils import Vector
import math

def frame_objects(cam, objects, margin=1.3):
    pts = []
    for o in objects:
        pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
    center = sum(pts, Vector()) / len(pts)
    radius = max((p - center).length for p in pts)
    # 由传感器与焦距求视场角，退到刚好容纳包围球
    fov = 2 * math.atan(cam.data.sensor_width / (2 * cam.data.lens))
    dist = radius / math.sin(fov / 2) * margin
    cam.location = center + Vector((1, -1, 0.6)).normalized() * dist
    point_at(cam, center)

frame_objects(cam, [o for o in bpy.context.scene.objects if o.type == "MESH"])
```

正交相机：`cam_data.type = "ORTHO"; cam_data.ortho_scale = 10`（视野宽度，米）。景深：`cam_data.dof.use_dof = True; cam_data.dof.focus_object = target; cam_data.dof.aperture_fstop = 2.8`。

## 11. 世界环境（背景光）

```python
world = bpy.data.worlds.new("World")
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.05, 0.05, 0.08, 1)
bg.inputs["Strength"].default_value = 0.3
bpy.context.scene.world = world

# 用 HDRI：
env = world.node_tree.nodes.new("ShaderNodeTexEnvironment")
env.image = bpy.data.images.load(r"D:\hdri\studio.hdr")
world.node_tree.links.new(env.outputs["Color"], bg.inputs["Color"])
```

## 12. 单位与场景设置

```python
scene = bpy.context.scene
scene.unit_settings.system = "METRIC"      # 'METRIC' / 'IMPERIAL' / 'NONE'
scene.unit_settings.scale_length = 1.0     # 1 个 BU = 多少米
scene.render.engine = "BLENDER_EEVEE"      # 5.x；4.2-4.5 用 "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = 1920
scene.render.resolution_y = 1080
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.image_settings.color_mode = "RGBA"
scene.render.filepath = "//out/render.png"
scene.render.film_transparent = True       # 透明背景
scene.render.image_settings.color_depth = "8"
scene.render.resolution_percentage = 50    # 快速预览技巧：百分比缩半
```

## 13. 后台模式的上下文规则（必读）

1. `primitive_*_add` 等建图元算子在后台可用；但凡报 `context is None` / `poll() failed` 的算子，先想数据 API 替代方案。
2. 必须用算子时，确保：对象已 `link` 进场景集合 → `bpy.context.view_layer.objects.active = obj` → `obj.select_set(True)`，必要时 `bpy.context.view_layer.update()`。
3. `bpy.context.scene` 在后台模式可用且可靠。
4. `bpy.ops.wm.save_as_mainfile`、`bpy.ops.render.render`、导入导出算子（`wm.obj_import` 等）在后台模式正常工作。
5. 改完数据后渲染前调用 `bpy.context.view_layer.update()` 确保依赖图刷新（特别是驱动器/约束链）。
