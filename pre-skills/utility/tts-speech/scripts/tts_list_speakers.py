#!/usr/bin/env python3
"""
tts_list_speakers.py — 列出 TTS 服务器上所有可用的说话人。
"""

import argparse
import json
import sys
import requests

TTS_SERVER = "http://127.0.0.1:53342"


def main():
    parser = argparse.ArgumentParser(description="列出 TTS 可用说话人")
    parser.add_argument("--server", default=TTS_SERVER)
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    try:
        health = requests.get(f"{args.server}/api/health", timeout=5).json()
    except Exception as e:
        print(f"错误: 无法连接 TTS 服务器 ({args.server}): {e}", file=sys.stderr)
        sys.exit(1)

    speakers = health.get("speakers_detail", {})
    model_loaded = health.get("model_loaded", False)

    if args.json:
        print(json.dumps({
            "server": args.server,
            "model_loaded": model_loaded,
            "speakers": list(speakers.keys()),
        }, ensure_ascii=False))
        return

    print(f"TTS 服务器: {args.server}")
    print(f"模型已加载: {'✅' if model_loaded else '❌'}")
    print(f"可用说话人 ({len(speakers)} 个):")
    for spk_id in speakers:
        print(f"  - {spk_id}")


if __name__ == "__main__":
    main()
