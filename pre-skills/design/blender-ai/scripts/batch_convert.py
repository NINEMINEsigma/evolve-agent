r"""batch_convert.py — 批量 3D 格式转换（在 Blender 内运行）。

用法（路径由调用方解析，不要写死盘符）：
    & $blender -b --factory-startup --python-exit-code 1 -P batch_convert.py -- `
        --input $inDir --to glb --output $outDir --apply-transform

支持输入: obj / stl / ply / fbx / glb / gltf / usd / usda / usdc
支持输出: obj / stl / ply / fbx / glb / gltf / usd / blend
每个文件从空场景开始转换，单文件失败不中断整批。

`--python-exit-code 1` 必须在 `--` 之前。
"""
import bpy
import sys
import os
import glob
import argparse
import traceback


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(description="批量 3D 格式转换")
    p.add_argument("--input", required=True, help="输入目录或单个文件路径")
    p.add_argument("--to", required=True,
                   choices=["obj", "stl", "ply", "fbx", "glb", "gltf", "usd", "blend"])
    p.add_argument("--output", required=True, help="输出目录")
    p.add_argument("--scale", type=float, default=1.0, help="导入后统一缩放")
    p.add_argument("--apply-transform", action="store_true",
                   help="烘焙旋转/缩放进顶点数据（导出 STL/3D 打印建议开启）")
    return p.parse_args(argv)


def import_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".stl":
        bpy.ops.wm.stl_import(filepath=path)
    elif ext == ".ply":
        bpy.ops.wm.ply_import(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext in (".usd", ".usda", ".usdc"):
        bpy.ops.wm.usd_import(filepath=path)
    else:
        raise ValueError(f"不支持的输入格式: {ext}")
    return list(bpy.context.selected_objects)


def apply_transform(objs):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objs:
        if obj.type == "MESH":
            obj.select_set(True)
    if bpy.context.selected_objects:
        bpy.context.view_layer.objects.active = bpy.context.selected_objects[0]
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def export_file(path, fmt):
    if fmt == "obj":
        bpy.ops.wm.obj_export(filepath=path)
    elif fmt == "stl":
        bpy.ops.wm.stl_export(filepath=path)
    elif fmt == "ply":
        bpy.ops.wm.ply_export(filepath=path)
    elif fmt == "fbx":
        bpy.ops.export_scene.fbx(filepath=path, apply_scale_options="FBX_SCALE_ALL")
    elif fmt in ("glb", "gltf"):
        bpy.ops.export_scene.gltf(
            filepath=path,
            export_format="GLB" if fmt == "glb" else "GLTF_SEPARATE",
            export_apply=True,
        )
    elif fmt == "usd":
        bpy.ops.wm.usd_export(filepath=path)
    elif fmt == "blend":
        bpy.ops.wm.save_as_mainfile(filepath=path)


def main():
    args = parse_args()
    os.makedirs(args.output, exist_ok=True)

    if os.path.isfile(args.input):
        files = [args.input]
    else:
        exts = ("*.obj", "*.stl", "*.ply", "*.fbx", "*.glb", "*.gltf", "*.usd", "*.usda", "*.usdc")
        files = sorted(f for e in exts for f in glob.glob(os.path.join(args.input, "**", e), recursive=True))

    print(f"[scan] 发现 {len(files)} 个文件")
    ok, failed = 0, []
    for src in files:
        name = os.path.splitext(os.path.basename(src))[0]
        dst = os.path.join(args.output, f"{name}.{args.to}")
        try:
            bpy.ops.wm.read_factory_settings(use_empty=True)  # 每个文件从空场景开始
            objs = import_file(src)
            if args.scale != 1.0:
                for o in objs:
                    o.scale = [s * args.scale for s in o.scale]
            if args.apply_transform:
                apply_transform(objs)
            export_file(dst, args.to)
            ok += 1
            print(f"[ok] {src} -> {dst}", flush=True)
        except Exception:
            failed.append(src)
            print(f"[fail] {src}\n{traceback.format_exc()}", flush=True)

    print(f"[summary] 成功 {ok} / 共 {len(files)}")
    if failed:
        print("[failed-list] " + "; ".join(failed))
        sys.exit(2)  # SystemExit 的退出码会传导给 blender 进程，让外层感知部分失败


if __name__ == "__main__":
    main()
