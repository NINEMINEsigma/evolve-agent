# 导入 / 导出与批量格式转换

> 4.x 起导入器全面重写为 C++ 实现（快 10-100 倍），算子名随之变化。本文按 5.x/4.x 新算子编写，并给出旧版对照。

## 1. 算子速查表

| 格式 | 导入（5.x / 4.1+） | 导出 |
|---|---|---|
| OBJ | `bpy.ops.wm.obj_import(filepath=...)` | `bpy.ops.wm.obj_export(filepath=...)` |
| STL | `bpy.ops.wm.stl_import(filepath=...)` | `bpy.ops.wm.stl_export(filepath=...)` |
| PLY | `bpy.ops.wm.ply_import(filepath=...)` | `bpy.ops.wm.ply_export(filepath=...)` |
| FBX | `bpy.ops.import_scene.fbx(filepath=...)` | `bpy.ops.export_scene.fbx(filepath=...)` |
| glTF/GLB | `bpy.ops.import_scene.gltf(filepath=...)` | `bpy.ops.export_scene.gltf(filepath=...)` |
| USD | `bpy.ops.wm.usd_import(filepath=...)` | `bpy.ops.wm.usd_export(filepath=...)` |
| Alembic | `bpy.ops.wm.alembic_import(filepath=...)` | `bpy.ops.wm.alembic_export(filepath=...)` |
| Collada (.dae) | `bpy.ops.wm.collada_import(filepath=...)` | `bpy.ops.wm.collada_export(filepath=...)` |

> ≤4.0 旧算子对照：`import_scene.obj`、`import_mesh.stl`、`import_mesh.ply`。写兼容脚本时用 `hasattr(bpy.ops.wm, "obj_import")` 判断。

## 2. 导入

```python
# OBJ（常用参数）
bpy.ops.wm.obj_import(
    filepath=r"D:\in\model.obj",
    forward_axis="NEGATIVE_Z",   # 与上游软件的轴向约定有关，导入后倒了就改这个
    up_axis="Y",
    validate_meshes=True,
)

# FBX
bpy.ops.import_scene.fbx(
    filepath=r"D:\in\model.fbx",
    use_anim=True,
    ignore_leaf_bones=True,        # 骨架子叶骨噪声多时有用
    automatic_bone_orientation=False,  # 骨骼朝向异常时试 True
)

# glTF/GLB（Web 管线最常用）
bpy.ops.import_scene.gltf(filepath=r"D:\in\model.glb")

# STL（3D 打印；无材质无单位，导入后常需检查缩放）
bpy.ops.wm.stl_import(filepath=r"D:\in\part.stl")
```

**导入后拿到了什么**：新对象会被选中——`bpy.context.selected_objects` 即是本次导入的对象列表（后台模式同样有效，这是定位导入结果的通用技巧）。

## 3. 导入后清理三件套

```python
import bpy

def cleanup_imported(objs):
    for obj in objs:
        if obj.type != "MESH":
            continue
        # 1) 应用导入缩放/旋转（把变换烘进顶点数据）
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        # 2) 自动平滑（5.x: modifier 节点方案；通用方案直接设置多边形平滑）
        for p in obj.data.polygons:
            p.use_smooth = True
        obj.select_set(False)

cleanup_imported(bpy.context.selected_objects)
```

单位问题：FBX/OBJ 的"单位"由导出方决定，尺寸差 100 倍多半是厘米/米问题——用 `bpy.ops.wm.obj_import(global_scale=...)` 或导入后统一 `obj.scale` 再 `transform_apply`。

## 4. 导出

```python
# glTF/GLB（推荐交换格式，材质/动画/骨骼保留最好）
bpy.ops.export_scene.gltf(
    filepath=r"D:\out\model.glb",
    export_format="GLB",            # 单文件内嵌贴图；要分离纹理用 "GLTF_SEPARATE"
    export_apply=True,              # 应用修改器
    export_animations=True,
    export_yup=True,                # +Y up（glTF 标准）
)

# FBX（进 Unity/UE）
bpy.ops.export_scene.fbx(
    filepath=r"D:\out\model.fbx",
    apply_scale_options="FBX_SCALE_ALL",   # 避免 Unity 里 0.01 缩放问题
    add_leaf_bones=False,
    bake_anim=True,
)

# OBJ
bpy.ops.wm.obj_export(filepath=r"D:\out\model.obj", export_selected_objects=True)

# STL（3D 打印；通常要求毫米单位 + 应用缩放）
bpy.ops.wm.stl_export(filepath=r"D:\out\part.stl", ascii_format=False)
```

**只导出选中对象**：先把目标 `select_set(True)`、其他全取消，导出参数带 `use_selection=True`（FBX）/ `export_selected_objects=True`（OBJ）/ `use_selection=True`（glTF）。

## 5. 批量转换（完整方案）

脚本模板见 ../scripts/batch_convert.py，核心循环：

```python
import bpy, os, glob

IMPORTERS = {
    ".obj":  lambda p: bpy.ops.wm.obj_import(filepath=p),
    ".stl":  lambda p: bpy.ops.wm.stl_import(filepath=p),
    ".ply":  lambda p: bpy.ops.wm.ply_import(filepath=p),
    ".fbx":  lambda p: bpy.ops.import_scene.fbx(filepath=p),
    ".glb":  lambda p: bpy.ops.import_scene.gltf(filepath=p),
    ".gltf": lambda p: bpy.ops.import_scene.gltf(filepath=p),
    ".usd":  lambda p: bpy.ops.wm.usd_import(filepath=p),
    ".usda": lambda p: bpy.ops.wm.usd_import(filepath=p),
    ".usdc": lambda p: bpy.ops.wm.usd_import(filepath=p),
}

for src in glob.glob(r"D:\in\*.obj"):
    bpy.ops.wm.read_factory_settings(use_empty=True)   # 每个文件从空场景开始，防污染
    IMPORTERS[os.path.splitext(src)[1].lower()](src)
    dst = os.path.join(r"D:\out", os.path.splitext(os.path.basename(src))[0] + ".glb")
    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", export_apply=True)
    print(f"[ok] {src} -> {dst}", flush=True)
```

要点：
- **每个文件之间重置场景**（`read_factory_settings(use_empty=True)`），否则材质名 `Material.001` 越攒越多、结果互相污染。
- 失败的文件 try/except 包住记日志，别让一个坏文件中断整批。
- 批量任务务必在 `--` **之前**加 `--python-exit-code 1`，但脚本内部自己消化单文件异常。

## 6. .blend 之间的数据复用（追加/链接）

```python
# 从另一个 blend 追加一个集合
with bpy.data.libraries.load(r"D:\assets\props.blend", link=False) as (data_from, data_to):
    data_to.collections = [c for c in data_from.collections if c.startswith("Prop")]
for coll in data_to.collections:
    if coll:
        bpy.context.scene.collection.children.link(coll)
```

`link=True` 为链接（引用原文件，改源即更新）；`link=False` 为追加（拷贝进来）。
