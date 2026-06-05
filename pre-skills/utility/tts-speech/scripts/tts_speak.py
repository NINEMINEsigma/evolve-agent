#!/usr/bin/env python3
"""
tts_speak.py — TTS 语音合成脚本

一键合成语音并发布到前端供用户播放/下载。

用法:
  python tts_speak.py --speaker sui --text "你好世界"
  python tts_speak.py --speaker sui --text "你好" --server http://127.0.0.1:53342

流程:
  1. 调用 TTS API 合成语音 (WAV)
  2. 转 MP3 缩小体积
  3. 保存到 ws:output/ 供前端访问
  4. 打印结果 JSON（含下载链接路径）
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import requests

# ── 常量 ────────────────────────────────────────────────────────────
TTS_SERVER = "http://127.0.0.1:53342"
AGENTSPACE = Path("D:/evolve-agent/workspace/agentspace")
OUTPUT_DIR = AGENTSPACE / "output"


def synthesize(speaker_id: str, text: str, server: str) -> dict:
    """调用 TTS API 合成语音。"""
    resp = requests.post(
        f"{server}/api/synthesize",
        json={"speaker_id": speaker_id, "text": text, "line_id": "skill_tts"},
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()


def download_audio(voice_url: str, server: str, dest: Path) -> None:
    """下载合成的音频文件。"""
    resp = requests.get(f"{server}{voice_url}", timeout=60)
    resp.raise_for_status()
    dest.write_bytes(resp.content)


def convert_to_mp3(wav_path: Path, mp3_path: Path) -> Path:
    """将 WAV 转 MP3。"""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path),
             "-codec:a", "libmp3lame", "-b:a", "128k", str(mp3_path)],
            check=True, capture_output=True, timeout=30,
        )
        return mp3_path
    except Exception:
        return wav_path


def main():
    parser = argparse.ArgumentParser(description="TTS 语音合成")
    parser.add_argument("--speaker", "-s", default="sui", help="说话人 ID")
    parser.add_argument("--text", "-t", required=True, help="合成文本")
    parser.add_argument("--server", default=TTS_SERVER, help="TTS 服务器地址")
    args = parser.parse_args()

    text = args.text.strip()
    if not text:
        print(json.dumps({"error": "文本不能为空"}), file=sys.stderr)
        sys.exit(1)

    # 检查服务器
    try:
        health = requests.get(f"{args.server}/api/health", timeout=5).json()
    except Exception as e:
        print(json.dumps({"error": f"无法连接 TTS 服务器: {e}",
                          "hint": "请先启动 TTS 服务器"}), file=sys.stderr)
        sys.exit(1)

    speakers = list(health.get("speakers_detail", {}).keys())
    if args.speaker not in speakers:
        print(json.dumps({"error": f"说话人 '{args.speaker}' 未注册",
                          "available_speakers": speakers}), file=sys.stderr)
        sys.exit(1)

    # 1. 合成
    print(f"正在合成: '{text[:40]}...' (说话人: {args.speaker})", file=sys.stderr)
    result = synthesize(args.speaker, text, args.server)
    if result.get("error"):
        print(json.dumps({"error": f"合成失败: {result['error']}"}), file=sys.stderr)
        sys.exit(1)

    voice_url = result["voice_url"]
    print(f"合成成功: {voice_url}", file=sys.stderr)

    # 2. 保存文件
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md5 = hashlib.md5(f"{args.speaker}{text}".encode()).hexdigest()[:12]
    mp3_path = OUTPUT_DIR / f"tts_{md5}.mp3"
    wav_path = mp3_path.with_suffix(".wav")

    download_audio(voice_url, args.server, wav_path)
    final_path = convert_to_mp3(wav_path, mp3_path)

    if final_path != wav_path and wav_path.exists():
        wav_path.unlink()

    ws_path = f"ws:output/{final_path.name}"
    file_size = final_path.stat().st_size

    # 3. 输出结果
    output = {
        "success": True,
        "speaker": args.speaker,
        "text": text,
        "audio_path": ws_path,
        "file_size_kb": round(file_size / 1024, 1),
        "frontend_url": f"/downloads/output/{final_path.name}",
        "publish_cmd": f'publish_file(path="{ws_path}", filename="{final_path.stem}.mp3", description="TTS语音: {text[:30]}")',
        "message": f"语音合成成功！使用 publish_file 发布给用户",
    }
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
