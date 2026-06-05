#!/usr/bin/env python3
"""
tts_register_speaker.py — 注册新说话人。

用法:
  # 自动扫描 StreamingAssets/vocals/
  python tts_register_speaker.py --auto

  # 手动指定
  python tts_register_speaker.py --id my_speaker --audio /path/to/vocal.wav --text "音频文本"
"""

import argparse
import json
import sys
from pathlib import Path
import requests

TTS_SERVER = "http://127.0.0.1:53342"
AGENTSPACE = Path("D:/evolve-agent/workspace/agentspace")
TTS_DIR = AGENTSPACE / "tts3"
VOCALS_DIR = TTS_DIR / "StreamingAssets" / "vocals"


def resolve_path(p: str) -> str:
    """解析路径，支持 ws: 前缀。"""
    if p.startswith("ws:"):
        return str((AGENTSPACE / p[3:]).resolve())
    return str(Path(p).resolve())


def auto_discover():
    """自动扫描 StreamingAssets/vocals。"""
    if not VOCALS_DIR.exists():
        print(f"目录不存在: {VOCALS_DIR}", file=sys.stderr)
        return {}
    speakers = {}
    for spk_dir in VOCALS_DIR.iterdir():
        if not spk_dir.is_dir():
            continue
        sid = spk_dir.name
        txt_path = spk_dir / "vocal.txt"
        if not txt_path.exists():
            continue
        vocal_text = txt_path.read_text(encoding="utf-8").strip()
        if not vocal_text:
            continue
        audio = None
        for ext in (".wav", ".mp3", ".flac", ".ogg"):
            c = spk_dir / f"vocal{ext}"
            if c.exists():
                audio = str(c.resolve())
                break
        if audio:
            speakers[sid] = {"vocal_text": vocal_text, "vocal_audio_path": audio}
    return speakers


def main():
    parser = argparse.ArgumentParser(description="注册 TTS 说话人")
    parser.add_argument("--server", default=TTS_SERVER)
    parser.add_argument("--auto", action="store_true", help="自动扫描")
    parser.add_argument("--id", dest="speaker_id", help="说话人 ID")
    parser.add_argument("--audio", help="音频路径 (支持 ws: 前缀)")
    parser.add_argument("--text", help="音频文本")
    args = parser.parse_args()

    if args.auto:
        speakers = auto_discover()
        if not speakers:
            print(f"在 {VOCALS_DIR} 中未找到新说话人", file=sys.stderr)
            return
        registered = []
        for spk_id, info in speakers.items():
            try:
                requests.post(f"{args.server}/api/register-speaker",
                              json={"speaker_id": spk_id, **info}, timeout=10).raise_for_status()
                registered.append(spk_id)
                print(f"✅ {spk_id} 注册成功", file=sys.stderr)
            except Exception as e:
                print(f"❌ {spk_id} 注册失败: {e}", file=sys.stderr)
        print(json.dumps({"success": True, "registered": registered}))
        return

    if not all([args.speaker_id, args.audio, args.text]):
        print("错误: 需要 --id, --audio, --text", file=sys.stderr)
        sys.exit(1)

    audio_path = resolve_path(args.audio)
    if not Path(audio_path).exists():
        print(f"错误: 音频文件不存在: {audio_path}", file=sys.stderr)
        sys.exit(1)

    r = requests.post(f"{args.server}/api/register-speaker", json={
        "speaker_id": args.speaker_id,
        "vocal_text": args.text,
        "vocal_audio_path": audio_path,
    }, timeout=10)
    r.raise_for_status()
    print(json.dumps({"success": True, "speaker_id": args.speaker_id,
                       "message": f"说话人 '{args.speaker_id}' 注册成功"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
