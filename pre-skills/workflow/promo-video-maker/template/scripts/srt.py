"""Export timing.json subtitles to an UTF-8 SRT file.

Usage: python scripts/srt.py [output.srt]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
timing = json.load(open(os.path.join(ROOT, "src", "timing.json"), encoding="utf-8"))
items = timing.get("subtitles") or timing.get("captions") or []
if not items:
    print("timing.json 没有 subtitles/captions，未生成 SRT")
    raise SystemExit(0)

def stamp(seconds):
    ms = max(0, round(float(seconds) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "out", "字幕.srt")
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
with open(out, "w", encoding="utf-8", newline="\n") as f:
    for i, item in enumerate(items, 1):
        text = item.get("text", "").strip()
        if not text:
            continue
        f.write(f"{i}\n{stamp(item['at'])} --> {stamp(item['end'])}\n{text}\n\n")
print(out, len(items))
