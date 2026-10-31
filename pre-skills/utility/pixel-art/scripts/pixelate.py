#!/usr/bin/env python3
"""pixelate.py - 图片像素风格化

先降采样到“小图”，再用最近邻放大回原尺寸，使画面呈现均匀的像素块。
降采样采用中心映射后向零取整采样。
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image


def downsample(arr, W, H):
    """中心映射 + 取整采样，返回 (H, W[, C]) 小图。"""
    h, w = arr.shape[:2]
    W = max(1, min(W, w))
    H = max(1, min(H, h))
    ys = np.clip((((np.arange(H) + 0.5) * h / H) - 0.5).astype(np.int64), 0, h - 1)
    xs = np.clip((((np.arange(W) + 0.5) * w / W) - 0.5).astype(np.int64), 0, w - 1)
    return arr[np.ix_(ys, xs)]


def upsample(small, w, h):
    """最近邻放大到 (w, h)，每个小像素映射为等大像素块。"""
    H, W = small.shape[:2]
    yi = np.clip(((np.arange(h) + 0.5) * H / h).astype(np.int64), 0, H - 1)
    xi = np.clip(((np.arange(w) + 0.5) * W / w).astype(np.int64), 0, W - 1)
    return small[yi][:, xi]


def quantize(small_arr, n):
    """中位切分限色；传入抖动参数，但不保证当前 Pillow 路径实际应用抖动。"""
    img = Image.fromarray(small_arr)
    has_alpha = img.mode == "RGBA"
    q = (
        img.convert("RGB")
        .quantize(colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
        .convert("RGB")
    )
    if has_alpha:
        q = q.convert("RGBA")
        q.putalpha(Image.fromarray(small_arr[..., 3]))
    return np.asarray(q)


def main():
    p = argparse.ArgumentParser(description="将图片转换为像素风格")
    p.add_argument("input", help="输入图片路径")
    p.add_argument("-o", "--output", help="输出路径（默认 <原名>.pixel.png）")
    p.add_argument("-s", "--block", type=int, default=8,
                   help="输出图中每个大像素的边长（像素），越大越粗犷（默认 8）")
    p.add_argument("--small", metavar="WxH", help="直接指定小图尺寸，如 181x136（优先于 -s）")
    p.add_argument("--small-only", action="store_true",
                   help="只输出降采样后的小图（像素画稿），不做放大")
    p.add_argument("--palette", type=int, metavar="N",
                   help="可选：把小图量化到 N 色（复古游戏机风格）")
    args = p.parse_args()

    if not os.path.isfile(args.input):
        sys.exit(f"输入文件不存在: {args.input}")
    if args.block < 1:
        sys.exit("-s/--block 必须 >= 1")
    if args.palette is not None and not (2 <= args.palette <= 256):
        sys.exit("--palette 必须在 2..256 之间")

    with Image.open(args.input) as source:
        has_alpha = "A" in source.getbands() or "transparency" in source.info
        img = source.convert("RGBA" if has_alpha else "RGB")
    arr = np.asarray(img)
    h, w = arr.shape[:2]

    if args.small:
        try:
            W, H = map(int, args.small.lower().split("x"))
        except ValueError:
            sys.exit("--small 格式应为 WxH，如 181x136")
        if W < 1 or H < 1:
            sys.exit("--small 的宽度和高度必须 >= 1")
    else:
        W = max(1, round(w / args.block))
        H = max(1, round(h / args.block))

    small = downsample(arr, W, H)
    H, W = small.shape[:2]
    if args.palette:
        small = quantize(small, args.palette)

    out = small if args.small_only else upsample(small, w, h)
    out_img = Image.fromarray(out)

    out_path = args.output
    if not out_path:
        stem, _ = os.path.splitext(args.input)
        suffix = ".small.png" if args.small_only else ".pixel.png"
        out_path = stem + suffix
    out_img.save(out_path)

    oh, ow = out.shape[:2]
    print(f"完成: {args.input} ({w}x{h}) -> {out_path} ({ow}x{oh}, 小图 {W}x{H})")


if __name__ == "__main__":
    main()
