"""Final MP4 gate for localized projects.

Usage: python scripts/validate-video.py out/final-1080p.mp4 [--scale 1|2]
The expected dimensions, duration, fps and audio policy come from src/timing.json.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from PIL import Image, ImageDraw
from labelfont import label_font

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parser = argparse.ArgumentParser()
parser.add_argument("video")
parser.add_argument("--log", default=os.path.join(ROOT, "out", "render.log"))
parser.add_argument("--scale", type=float, default=None)
args = parser.parse_args()

def run(command):
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")

timing = json.load(open(os.path.join(ROOT, "src", "timing.json"), encoding="utf-8"))
audio_mode = (timing.get("audio") or {}).get("mode", "music")
probe = run(["ffprobe", "-v", "error", "-count_frames", "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate,nb_read_frames,duration:format=duration", "-of", "json", args.video])
if probe.returncode:
    raise SystemExit(f"ffprobe failed: {probe.stderr}")
data = json.loads(probe.stdout)
video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
if not video:
    raise SystemExit("ERROR 没有视频流")
audio = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
duration = float((data.get("format") or {}).get("duration") or video.get("duration") or 0)
errors, notes = [], []
expected_scale = args.scale or 1
expected_size = (round(timing["width"] * expected_scale), round(timing["height"] * expected_scale))
if (video.get("width"), video.get("height")) != expected_size:
    errors.append(f"分辨率 {video.get('width')}x{video.get('height')}，预期 {expected_size[0]}x{expected_size[1]}")
expected_fps = f"{timing['fps']}/1"
if video.get("r_frame_rate") != expected_fps:
    errors.append(f"帧率 {video.get('r_frame_rate')}，预期 {expected_fps}")
expected_frames = round(timing["duration"] * timing["fps"])
actual_frames = int(video.get("nb_read_frames") or 0)
if actual_frames and actual_frames != expected_frames:
    errors.append(f"视频帧数 {actual_frames}，预期 {expected_frames}")
if abs(duration - timing["duration"]) > 0.2:
    errors.append(f"时长 {duration:.2f}s，预期 {timing['duration']}s")
if audio_mode == "silent" and audio:
    errors.append(f"静音模式却有 {len(audio)} 条音轨")
if audio_mode != "silent" and not audio:
    errors.append("当前音频模式需要音轨，但成片没有音轨")
notes.append(f"{video.get('codec_name')} {video.get('width')}x{video.get('height')} @{video.get('r_frame_rate')} {duration:.2f}s frames={actual_frames or 'unknown'} audio={len(audio)} mode={audio_mode}")
if os.path.exists(args.log):
    log = open(args.log, encoding="utf-8", errors="replace").read()
    bad = re.findall(r".*(?:cannot be decoded|EncodingError|Error:|error:|failed to load|Timeout).*", log)
    if bad: errors.append(f"渲染日志有 {len(bad)} 条错误：{bad[0].strip()[:180]}")
    else: notes.append("渲染日志无错误")
# Full decode.
decoded = run(["ffmpeg", "-v", "error", "-i", args.video, "-f", "null", "-"])
if decoded.returncode or decoded.stderr.strip(): errors.append(f"完整解码失败：{decoded.stderr.strip()[:300]}")
else: notes.append("完整解码通过")
# Black-frame check; low-motion notices are reported, not blindly treated as failures.
motion = run(["ffmpeg", "-hide_banner", "-i", args.video, "-vf", "blackdetect=d=0.1:pix_th=0.001,freezedetect=n=-50dB:d=3", "-an", "-f", "null", "-"])
black = [line for line in motion.stderr.splitlines() if "black_start:" in line]
freeze = [line for line in motion.stderr.splitlines() if "freeze_start:" in line]
if black: errors.append(f"检测到黑帧区间 {len(black)} 个")
notes.append(f"低动态提示 {len(freeze)} 个，需结合联系表与实际帧差审查")
# Build a scene contact sheet from the actual MP4.
times = [(name, start + (end - start) * 0.6) for name, (start, end) in timing.get("scenes", {}).items()]
if times:
    with tempfile.TemporaryDirectory() as temp:
        width, cols = 480, 4
        height = round(width * video["height"] / video["width"])
        sheet = Image.new("RGB", (width * cols, (height + 24) * ((len(times) + cols - 1) // cols)), "#111")
        draw, font = ImageDraw.Draw(sheet), label_font(15)
        for index, (name, at) in enumerate(times):
            frame_path = os.path.join(temp, f"{index}.jpg")
            r = run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", args.video, "-frames:v", "1", "-vf", f"scale={width}:-1", frame_path])
            if r.returncode or not os.path.exists(frame_path):
                errors.append(f"无法抽取场景帧 {name}")
                continue
            image = Image.open(frame_path).convert("RGB")
            x, y = (index % cols) * width, (index // cols) * (height + 24)
            sheet.paste(image, (x, y)); draw.text((x + 4, y + height + 3), f"{at:.1f}s {name}", fill="#ffd54a", font=font)
        dest = os.path.join(ROOT, "out", f"check_{os.path.splitext(os.path.basename(args.video))[0]}.jpg")
        os.makedirs(os.path.dirname(dest), exist_ok=True); sheet.save(dest, quality=85)
        notes.append(f"抽帧联系表：{dest}")
for note in notes: print("OK   ", note)
for error in errors: print("ERROR", error)
sys.exit(1 if errors else 0)
