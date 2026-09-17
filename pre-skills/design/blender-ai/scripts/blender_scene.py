r"""blender_scene.py — 从零构建演示场景并渲染静帧（bpy 脚本模板）。

用法（Evolve Agent / PowerShell，路径由探测脚本解析，不要写死）：
    $blender = (& $env:EVOLVE_PYTHON (Join-Path $env:EVOLVE_SKILLS 'design\blender-ai\scripts\locate_blender.py')).Trim()
    $script  = Join-Path $env:EVOLVE_SKILLS 'design\blender-ai\scripts\blender_scene.py'
    $out     = Join-Path $env:EVOLVE_WS 'tmp\blender-out\demo.png'
    & $blender -b --factory-startup --python-exit-code 1 -P $script -- `
        --output $out --engine EEVEE --width 1920 --height 1080

覆盖知识点：-- 参数解析、4.x/5.x 引擎兼容、数据 API 与图元算子、
材质节点、三点光、相机自动取景、透明背景、保存 blend。

`--python-exit-code 1` 是 Blender 开关，必须放在 `--` 之前；放到 `--` 之后会被 argparse 当成未知参数。
"""
import bpy
import sys
import os
import math
import argparse
from mathutils import Vector


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(description="构建演示场景并渲染")
    p.add_argument("--output", default="//demo.png", help="输出图像路径")
    p.add_argument("--engine", default="EEVEE", choices=["EEVEE", "CYCLES", "WORKBENCH"])
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--transparent", action="store_true", help="透明背景")
    p.add_argument("--save-blend", default="", help="额外保存 .blend 到该路径")
    return p.parse_args(argv)


def set_engine(scene, want):
    """跨版本引擎设置：5.x 为 BLENDER_EEVEE，4.2-4.5 为 BLENDER_EEVEE_NEXT。"""
    candidates = {
        "EEVEE": ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"],
        "CYCLES": ["CYCLES"],
        "WORKBENCH": ["BLENDER_WORKBENCH"],
    }[want.upper()]
    for c in candidates:
        try:
            scene.render.engine = c
            print(f"[engine] {c}")
            return c
        except TypeError:
            continue
    raise RuntimeError(f"无可用引擎: {want}")


def make_material(name, color, metallic=0.0, roughness=0.5):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def add_light(name, light_type, location, energy, color=(1, 1, 1), size=5.0):
    data = bpy.data.lights.new(name, type=light_type)
    data.energy = energy
    data.color = color
    if light_type == "AREA":
        data.size = size
    obj = bpy.data.objects.new(name, data)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


def point_at(obj, target):
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def frame_objects(cam, objects, margin=1.25):
    """把相机放到刚好容纳所有对象包围盒的位置。"""
    pts = []
    for o in objects:
        pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
    center = sum(pts, Vector()) / len(pts)
    radius = max((p - center).length for p in pts) or 1.0
    fov = 2 * math.atan(cam.data.sensor_width / (2 * cam.data.lens))
    dist = radius / math.sin(fov / 2) * margin
    cam.location = center + Vector((1, -1, 0.55)).normalized() * dist
    point_at(cam, center)


def main():
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    # --- 地面 ---
    bpy.ops.mesh.primitive_plane_add(size=30, location=(0, 0, 0))
    ground = bpy.context.active_object
    ground.name = "Ground"
    ground.data.materials.append(make_material("GroundMat", (0.12, 0.12, 0.14), roughness=0.9))

    # --- 三个演示几何体 ---
    bpy.ops.mesh.primitive_cube_add(size=2, location=(-2.5, 0, 1))
    cube = bpy.context.active_object
    cube.data.materials.append(make_material("Red", (0.7, 0.08, 0.05), roughness=0.4))

    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.2, location=(0.8, 0.3, 1.2), segments=64, ring_count=32)
    sphere = bpy.context.active_object
    for poly in sphere.data.polygons:
        poly.use_smooth = True
    sphere.data.materials.append(make_material("Metal", (0.8, 0.8, 0.85), metallic=1.0, roughness=0.15))

    bpy.ops.mesh.primitive_torus_add(major_radius=1.0, minor_radius=0.35, location=(3.5, 0.5, 1.0))
    torus = bpy.context.active_object
    for poly in torus.data.polygons:
        poly.use_smooth = True
    torus.data.materials.append(make_material("Gold", (0.9, 0.6, 0.1), metallic=1.0, roughness=0.3))

    # --- 三点光 ---
    key = add_light("Key", "AREA", (4, -4, 7), 1200, size=5)
    point_at(key, (0, 0, 1))
    fill = add_light("Fill", "AREA", (-5, -2, 4), 500, color=(0.7, 0.8, 1.0), size=4)
    point_at(fill, (0, 0, 1))
    add_light("Rim", "AREA", (0, 5, 5), 800, color=(1.0, 0.85, 0.7), size=3)

    # --- 世界背景 ---
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.03, 0.04, 0.06, 1.0)
    bg.inputs["Strength"].default_value = 0.4
    scene.world = world

    # --- 相机 ---
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    frame_objects(cam, [cube, sphere, torus])

    # --- 渲染设置 ---
    set_engine(scene, args.engine)
    r = scene.render
    r.resolution_x = args.width
    r.resolution_y = args.height
    r.resolution_percentage = 100
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA"
    r.film_transparent = args.transparent
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = args.samples
        scene.cycles.use_denoising = True
    try:
        scene.view_settings.view_transform = "AgX"
    except TypeError:
        pass

    out_path = bpy.path.abspath(args.output)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    r.filepath = out_path

    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=bpy.path.abspath(args.save_blend))
        print(f"[saved] {args.save_blend}")

    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=True)
    print(f"[done] 渲染完成 -> {out_path}")


if __name__ == "__main__":
    main()
