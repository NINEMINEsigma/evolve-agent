#!/usr/bin/env python3
"""
pmwatch.py - Watch memory addresses for changes.

Polls addresses and emits JSON when values change. Supports single address
or multiple addresses (from a scan session). Press Ctrl+C to stop.

Usage:
  pmwatch.py --pid 1234 --address 0x7FF60000 --type int4
  pmwatch.py --name game.exe --address 0x7FF60000 --type float --interval 0.5
  pmwatch.py --pid 1234 --session myscan --type int4 --limit 5
"""

import argparse
import json
import os
import struct
import sys
import time

try:
    import pymem
    HAS_PMEM = True
except Exception:  # noqa: BLE001
    HAS_PMEM = False

TYPE_MAP = {
    "int1": ("b", 1), "uint1": ("B", 1),
    "int2": ("h", 2), "uint2": ("H", 2),
    "int4": ("i", 4), "uint4": ("I", 4),
    "int8": ("q", 8), "uint8": ("Q", 8),
    "float": ("f", 4), "double": ("d", 8),
}


def watch(pm, addrs: list, val_type: str, interval: float, limit: int = None):
    fmt, size = TYPE_MAP[val_type]
    last = {}
    poll = 0

    try:
        while True:
            changes = []
            for addr_str in addrs:
                addr = int(addr_str, 0)
                try:
                    data = pm.read_bytes(addr, size)
                    val = struct.unpack(f"<{fmt}", data)[0]
                except Exception as exc:  # noqa: BLE001
                    val = f"<error: {exc}>"

                prev = last.get(addr_str)
                if val != prev:
                    changes.append({
                        "address": addr_str,
                        "value": val,
                        "previous": prev,
                    })
                    last[addr_str] = val

            if changes:
                poll += 1
                print(json.dumps({"poll": poll, "changes": changes}), flush=True)

            time.sleep(interval)
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(description="Watch memory for changes")
    tgt = parser.add_mutually_exclusive_group(required=True)
    tgt.add_argument("--pid", type=int)
    tgt.add_argument("--name")
    parser.add_argument("--address", help="Single address")
    parser.add_argument("--session", help="Use addresses from scan session")
    parser.add_argument("--type", required=True, choices=list(TYPE_MAP.keys()))
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=10, help="Max addresses from session")
    args = parser.parse_args()

    if not HAS_PMEM:
        sys.exit("pymem not available.")

    pm = pymem.Pymem(args.pid) if args.pid else pymem.Pymem(args.name)

    addrs = []
    if args.address:
        addrs = [args.address]
    elif args.session:
        sess_path = os.path.join(os.path.expanduser("~"), ".pmscan", f"{args.session}.json")
        if not os.path.exists(sess_path):
            sys.exit(f"Session not found: {args.session}")
        with open(sess_path) as f:
            sess = json.load(f)
        last_scan = sess["scans"][-1] if sess["scans"] else None
        if last_scan:
            addrs = last_scan.get("results", [])[:args.limit]

    if not addrs:
        sys.exit("No addresses to watch.")

    watch(pm, addrs, args.type, args.interval, args.limit)


if __name__ == "__main__":
    main()
