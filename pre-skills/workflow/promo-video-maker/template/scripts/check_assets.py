"""Render-time asset gate. Silent projects do not require public/audio/mix.wav."""
import glob
import json
import os
import re
import sys
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, "public")
EXT = r"png|jpe?g|webp|svg|gif|mp3|wav|mp4|webm|woff2"
errors, warns, refs = [], [], set()
timing = json.load(open(os.path.join(ROOT, "src", "timing.json"), encoding="utf-8"))
audio_mode = (timing.get("audio") or {}).get("mode", "music")
for p in glob.glob(os.path.join(ROOT, "src", "**", "*.ts*"), recursive=True) + glob.glob(os.path.join(ROOT, "web", "*.ts*")):
    text = open(p, encoding="utf-8").read()
    for m in re.finditer(rf"[\"'`]\/?([^\"'`$\s]+\.(?:{EXT}))[\"'`]", text):
        ref = m.group(1)
        if ref.startswith("./"):
            ref = ref[2:]
        refs.add((ref.lstrip("/"), os.path.relpath(p, ROOT)))
for ref, where in sorted(refs):
    if not os.path.exists(os.path.join(PUB, ref)) and not (audio_mode == "silent" and ref == "audio/mix.wav") and not (ref == "img/logo.png" and os.path.exists(os.path.join(PUB, "img", "placeholder.svg"))):
        errors.append(f"缺文件 public/{ref}（{where}）")
if audio_mode != "silent" and not os.path.exists(os.path.join(PUB, "audio", "mix.wav")):
    errors.append("缺 public/audio/mix.wav，先运行 python scripts/mix.py")
for f in glob.glob(os.path.join(PUB, "**", "*.*"), recursive=True):
    if not re.search(r"\.(png|jpe?g|webp)$", f, re.I):
        continue
    try:
        w, h = Image.open(f).size
    except Exception as exc:
        errors.append(f"图片损坏 {os.path.relpath(f, ROOT)}: {exc}")
        continue
    rel = os.path.relpath(f, ROOT)
    if max(w, h) < 1000: warns.append(f"{rel} 只有 {w}x{h}，放大可能发糊")
    if w > 3000: warns.append(f"{rel} 宽 {w}px，同屏多张时可按显示尺寸缩小")
cfg = json.load(open(os.path.join(ROOT, "fonts.json"), encoding="utf-8"))
for font in cfg["fonts"]:
    if not os.path.exists(os.path.join(PUB, "fonts", f"{font['file']}.woff2")):
        errors.append(f"缺字体 public/fonts/{font['file']}.woff2，先运行 python scripts/fonts.py")
for warning in warns: print("WARN ", warning)
for error in errors: print("ERROR", error)
print(f"引用 {len(refs)} 个文件；{len(errors)} 个错误，{len(warns)} 个提醒；audio={audio_mode}")
sys.exit(1 if errors else 0)
