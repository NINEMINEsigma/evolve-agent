#!/usr/bin/env python3
"""截图裁剪辅助（截图本身由浏览器工具集完成）。

用法:
  python shot.py <已截图的png路径> [--crop 0.28,0.24,0.52,0.52]
                 # 相对坐标 left,top,right,bottom (0~1)

截图流程已改用浏览器工具集:
  browser_screenshot(tab=<idx>, full_page=true) → ws:logs/browser_screenshots/{uuid}.png
  再用本脚本对返回的 saved_to 路径做局部裁剪放大复查。

示例:
  python shot.py ws:logs/browser_screenshots/abc.png --crop 0.28,0.24,0.52,0.52
  → 输出 ws:logs/browser_screenshots/abc_crop.png
"""
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('img', help='browser_screenshot 返回的 png 路径')
    ap.add_argument('--crop', default=None, help='相对坐标 l,t,r,b (0~1)')
    a = ap.parse_args()

    if not a.crop:
        print('no crop requested; nothing to do. screenshot:', a.img)
        return

    from PIL import Image
    l, t, rt, b = [float(v) for v in a.crop.split(',')]
    im = Image.open(a.img)
    W, H = im.size
    crop = im.crop((int(W * l), int(H * t), int(W * rt), int(H * b)))
    crop_path = a.img.replace('.png', '_crop.png')
    crop.save(crop_path)
    print('crop:', crop_path)


if __name__ == '__main__':
    main()
