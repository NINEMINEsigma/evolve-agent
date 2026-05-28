#!/usr/bin/env python3
"""
pmbatch.py - Batch read/write multiple memory addresses.

Execute multiple memory operations in a single call via JSON spec.

Read:
  pmbatch.py read --pid 1234 --spec '[
    {"address": "0x7FF60000", "type": "int4", "label": "health"},
    {"address": "0x7FF60004", "type": "float", "label": "speed"},
    {"address": "0x7FF60010", "type": "string", "label": "name", "size": 32}
  ]'

Write:
  pmbatch.py write --pid 1234 --spec '[
    {"address": "0x7FF60000", "type": "int4", "value": 9999, "label": "health"},
    {"address": "0x7FF60004", "type": "float", "value": 99.9, "label": "speed"}
  ]'
"""

import argparse
import base64
import json
import struct
import sys

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


def _read(pm, item: dict) -> dict:
    addr = int(item["address"], 0)
    vt = item["type"]
    label = item.get("label", f"0x{addr:X}")
    size = item.get("size", 64)
    fmt, _ = TYPE_MAP.get(vt, ("B", 1))

    try:
        if vt in TYPE_MAP:
            data = pm.read_bytes(addr, TYPE_MAP[vt][1])
            val = struct.unpack(f"<{fmt}", data)[0]
        elif vt == "bytes":
            data = pm.read_bytes(addr, size)
            val = {"hex": data.hex(), "base64": base64.b64encode(data).decode()}
        elif vt == "string":
            raw = pm.read_bytes(addr, size)
            null_idx = raw.find(b"\x00")
            val = raw[:null_idx].decode("utf-8", errors="replace") if null_idx != -1 else raw.decode("utf-8", errors="replace")
        elif vt == "wstring":
            raw = pm.read_bytes(addr, size)
            val = raw.decode("utf-16-le", errors="replace").split("\x00")[0]
        else:
            val = f"<unknown: {vt}>"
    except Exception as exc:  # noqa: BLE001
        val = f"<error: {exc}>"

    return {"label": label, "address": f"0x{addr:X}", "type": vt, "value": val}


def _write(pm, item: dict) -> dict:
    addr = int(item["address"], 0)
    vt = item["type"]
    label = item.get("label", f"0x{addr:X}")

    try:
        if vt in TYPE_MAP:
            fmt, size = TYPE_MAP[vt]
            if vt in ("float", "double"):
                val = float(item["value"])
            else:
                val = int(item["value"])
            data = struct.pack(f"<{fmt}", val)
            pm.write_bytes(addr, data, size)
        elif vt in ("bytes", "hex"):
            data = bytes.fromhex(item["value"].replace(" ", ""))
            pm.write_bytes(addr, data, len(data))
        elif vt == "string":
            data = item["value"].encode("utf-8")
            pm.write_bytes(addr, data, len(data))
        elif vt == "wstring":
            data = item["value"].encode("utf-16-le")
            pm.write_bytes(addr, data, len(data))
        else:
            return {"label": label, "address": f"0x{addr:X}", "status": f"<unknown: {vt}>"}
    except Exception as exc:  # noqa: BLE001
        return {"label": label, "address": f"0x{addr:X}", "status": f"<error: {exc}>"}

    return {"label": label, "address": f"0x{addr:X}", "status": "ok"}


def cmd_read(args):
    if not HAS_PMEM:
        sys.exit("pymem not available.")
    pm = pymem.Pymem(args.pid) if args.pid else pymem.Pymem(args.name)
    spec = json.loads(args.spec)
    print(json.dumps([_read(pm, item) for item in spec]))


def cmd_write(args):
    if not HAS_PMEM:
        sys.exit("pymem not available.")
    pm = pymem.Pymem(args.pid) if args.pid else pymem.Pymem(args.name)
    spec = json.loads(args.spec)
    print(json.dumps([_write(pm, item) for item in spec]))


def main():
    parser = argparse.ArgumentParser(description="pmbatch - Batch memory operations")
    sub = parser.add_subparsers(dest="cmd", required=True)

    rd = sub.add_parser("read")
    t = rd.add_mutually_exclusive_group(required=True)
    t.add_argument("--pid", type=int)
    t.add_argument("--name")
    rd.add_argument("--spec", required=True)
    rd.set_defaults(func=cmd_read)

    wr = sub.add_parser("write")
    t2 = wr.add_mutually_exclusive_group(required=True)
    t2.add_argument("--pid", type=int)
    t2.add_argument("--name")
    wr.add_argument("--spec", required=True)
    wr.set_defaults(func=cmd_write)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
