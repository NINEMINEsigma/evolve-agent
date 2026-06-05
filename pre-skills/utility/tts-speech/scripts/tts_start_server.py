#!/usr/bin/env python3
"""
tts_start_server.py — 启动 TTS 服务器

检查服务器状态，如果未运行则启动。

用法:
  python tts_start_server.py
  python tts_start_server.py --port 53342
  python tts_start_server.py --status   # 仅检查状态
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import requests

TTS_DIR = Path("D:/evolve-agent/workspace/agentspace/tts3")
VENV_PYTHON = TTS_DIR / "venv" / "Scripts" / "python.exe"
DEFAULT_PORT = 53342


def check_server(port: int) -> dict | None:
    """检查 TTS 服务器是否运行。返回 health JSON 或 None。"""
    try:
        r = requests.get(f"http://127.0.0.1:{port}/api/health", timeout=3)
        return r.json()
    except Exception:
        return None


def start_server(port: int) -> int:
    """启动 TTS 服务器，返回进程 PID。"""
    cmd = [
        str(VENV_PYTHON), "run.py",
        "--port", str(port),
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(TTS_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return proc.pid


def main():
    parser = argparse.ArgumentParser(description="启动 TTS 服务器")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--status", action="store_true", help="仅检查状态")
    parser.add_argument("--wait", action="store_true", help="等待服务器就绪")
    args = parser.parse_args()

    health = check_server(args.port)

    if args.status:
        if health:
            print(json.dumps({
                "running": True,
                "port": args.port,
                "model_loaded": health.get("model_loaded"),
                "speakers": list(health.get("speakers_detail", {}).keys()),
            }))
        else:
            print(json.dumps({"running": False, "port": args.port}))
        return

    if health:
        print(json.dumps({
            "message": "TTS 服务器已在运行",
            "port": args.port,
            "speakers": list(health.get("speakers_detail", {}).keys()),
            "api_url": f"http://127.0.0.1:{args.port}",
        }, ensure_ascii=False))
        return

    print(f"正在启动 TTS 服务器 (端口 {args.port})...", file=sys.stderr)
    pid = start_server(args.port)
    print(f"进程 PID: {pid}", file=sys.stderr)

    if args.wait:
        for i in range(30):
            time.sleep(1)
            health = check_server(args.port)
            if health:
                print(json.dumps({
                    "message": "TTS 服务器启动成功",
                    "pid": pid,
                    "port": args.port,
                    "speakers": list(health.get("speakers_detail", {}).keys()),
                    "api_url": f"http://127.0.0.1:{args.port}",
                }, ensure_ascii=False))
                return
        print(json.dumps({"error": "TTS 服务器启动超时"}), file=sys.stderr)
        sys.exit(1)
    else:
        print(json.dumps({
            "message": "TTS 服务器启动中 (后台)",
            "pid": pid,
            "port": args.port,
            "check_cmd": f'python tts_start_server.py --status --port {args.port}',
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
