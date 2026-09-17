r"""render_frames.py — 动画分段渲染模板，支持断点续渲（在 Blender 内运行）。

用法（路径由调用方解析，不要写死盘符）：
    & $blender -b $blendPath --factory-startup --python-exit-code 1 -P render_frames.py -- `
        --output $outDir --start 1 --end 120 --skip-existing

要点：
- 逐帧渲染 PNG，已存在的帧自动跳过（多机分片渲染时各机器给不同 --start/--end）。
- 可临时覆盖引擎与采样数做快渲验证。
- `--python-exit-code 1` 必须在 `--` 之前。
"""
import bpy
import sys
import os
import argparse


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(description="动画分段渲染（断点续渲）")
    p.add_argument("--output", required=True, help="输出目录（PNG 序列）")
    p.add_argument("--start", type=int, default=None, help="起始帧，默认取场景 frame_start")
    p.add_argument("--end", type=int, default=None, help="结束帧，默认取场景 frame_end")
    p.add_argument("--engine", default="", choices=["", "EEVEE", "CYCLES", "WORKBENCH"],
                   help="覆盖渲染引擎，默认用 blend 内设置")
    p.add_argument("--samples", type=int, default=0, help="覆盖 Cycles 采样数，0=不覆盖")
    p.add_argument("--skip-existing", action="store_true", help="跳过已存在的帧文件")
    p.add_argument("--prefix", default="frame_", help="文件名前缀")
    return p.parse_args(argv)


def set_engine(scene, want):
    candidates = {
        "EEVEE": ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"],
        "CYCLES": ["CYCLES"],
        "WORKBENCH": ["BLENDER_WORKBENCH"],
    }[want.upper()]
    for c in candidates:
        try:
            scene.render.engine = c
            return c
        except TypeError:
            continue
    raise RuntimeError(f"无可用引擎: {want}")


def main():
    args = parse_args()
    scene = bpy.context.scene

    if args.engine:
        print(f"[engine] 覆盖为 {set_engine(scene, args.engine)}")
    if args.samples > 0 and scene.render.engine == "CYCLES":
        scene.cycles.samples = args.samples
        print(f"[samples] 覆盖为 {args.samples}")

    out_dir = bpy.path.abspath(args.output)
    os.makedirs(out_dir, exist_ok=True)
    start = args.start if args.start is not None else scene.frame_start
    end = args.end if args.end is not None else scene.frame_end

    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"

    if scene.camera is None:
        raise RuntimeError("场景没有相机（scene.camera 为 None）")

    total = end - start + 1
    done = skipped = 0
    for f in range(start, end + 1):
        path = os.path.join(out_dir, f"{args.prefix}{f:04d}.png")
        if args.skip_existing and os.path.exists(path) and os.path.getsize(path) > 0:
            skipped += 1
            continue
        scene.frame_set(f)
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        done += 1
        print(f"[frame] {f} ({done + skipped}/{total})", flush=True)

    print(f"[summary] 渲染 {done} 帧，跳过 {skipped} 帧，输出目录: {out_dir}")


if __name__ == "__main__":
    main()
