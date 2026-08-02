#!/usr/bin/env python3
"""
pmfreeze.py - Freeze (lock) memory values, Cheat Engine style.

Continuously overwrite memory addresses to keep values locked.
Supports both foreground (Ctrl+C) and daemon mode (start/stop via file).

Usage:
  # Freeze a single address
  pmfreeze.py --pid 1234 --address 0x7FF60000 --type int4 --value 9999

  # Freeze multiple addresses from a session
  pmfreeze.py --pid 1234 --session myscan --type int4

  # Freeze with specific addresses
  pmfreeze.py --pid 1234 --type float --addresses 0x7FF60000 0x7FF60004 --value 99.9

  # Daemon mode - run in background, stop via stop file
  pmfreeze.py --pid 1234 --address 0x7FF60000 --type int4 --daemon --daemon-id hpfreeze
  pmfreeze.py --stop --daemon-id hpfreeze
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

DAEMON_DIR = os.path.join(os.path.expanduser("~"), ".pmfreeze")


def _stop_file_path(daemon_id: str) -> str:
    os.makedirs(DAEMON_DIR, exist_ok=True)
    return os.path.join(DAEMON_DIR, f"{daemon_id}.stop")


def _pid_file_path(daemon_id: str) -> str:
    os.makedirs(DAEMON_DIR, exist_ok=True)
    return os.path.join(DAEMON_DIR, f"{daemon_id}.pid")


def _pack_value(value, value_type: str) -> bytes:
    fmt, _ = TYPE_MAP[value_type]
    return struct.pack(f"<{fmt}", value)


def _parse_value(value_str, value_type: str):
    if value_type in ("float", "double"):
        return float(value_str)
    return int(value_str, 0)


def run_freeze(pm, targets: dict, value_type: str, daemon_id: str = None):
    """
    targets: {address_str: value}
    Runs until interrupted or stop file appears.
    """
    packed = {}
    for addr_str, val in targets.items():
        try:
            pval = _pack_value(val, value_type) if val is not None else None
            packed[addr_str] = pval
        except Exception:  # noqa: BLE001
            pass

    if not packed:
        sys.exit("No valid freeze targets.")

    # Read current values if not specified
    fmt, val_size = TYPE_MAP[value_type]
    for addr_str in list(packed.keys()):
        if packed[addr_str] is None:
            try:
                data = pm.read_bytes(int(addr_str, 0), val_size)
                packed[addr_str] = _pack_value(struct.unpack(f"<{fmt}", data)[0], value_type)
            except Exception:  # noqa: BLE001
                del packed[addr_str]

    if daemon_id:
        print(json.dumps({
            "status": "daemon_started",
            "daemon_id": daemon_id,
            "targets": len(packed),
            "addresses": list(packed.keys()),
        }), flush=True)

    stop_file = _stop_file_path(daemon_id) if daemon_id else None

    try:
        while True:
            # Check stop file
            if stop_file and os.path.exists(stop_file):
                os.remove(stop_file)
                break

            for addr_str, pval in packed.items():
                try:
                    pm.write_bytes(int(addr_str, 0), pval, len(pval))
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(0.01)  # 100Hz
    except KeyboardInterrupt:
        pass

    if daemon_id:
        print(json.dumps({"status": "stopped", "daemon_id": daemon_id}))


def cmd_freeze(args):
    if not HAS_PMEM:
        sys.exit("pymem not available.")

    pm = pymem.Pymem(args.pid) if args.pid else pymem.Pymem(args.name)
    val_type = args.type

    targets = {}

    # Load from session
    if args.session:
        session_dir = os.path.join(os.path.expanduser("~"), ".pmscan")
        session_path = os.path.join(session_dir, f"{args.session}.json")
        if not os.path.exists(session_path):
            sys.exit(f"Session not found: {args.session}")
        with open(session_path, "r") as f:
            sess = json.load(f)
        last_scan = sess["scans"][-1] if sess["scans"] else None
        if last_scan:
            for a in last_scan.get("results", [])[:args.max]:
                targets[a] = args.value  # Use specified value or will read current

    # Load specific addresses
    if args.addresses:
        for a in args.addresses:
            targets[a] = args.value

    # Single address mode
    if args.address:
        targets[f"0x{int(args.address, 0):X}"] = args.value

    if not targets:
        sys.exit("No addresses to freeze. Use --address, --addresses, or --session.")

    run_freeze(pm, targets, val_type, args.daemon_id)


def cmd_stop(args):
    """Signal a daemon to stop."""
    stop_file = _stop_file_path(args.daemon_id)
    with open(stop_file, "w") as f:
        f.write("stop")
    print(json.dumps({"status": "stop_signal_sent", "daemon_id": args.daemon_id}))


def cmd_list(_args):
    """List running freeze daemons."""
    os.makedirs(DAEMON_DIR, exist_ok=True)
    daemons = []
    for f in os.listdir(DAEMON_DIR):
        if f.endswith(".pid"):
            daemon_id = f[:-4]
            try:
                with open(os.path.join(DAEMON_DIR, f), "r") as fh:
                    info = json.load(fh)
                daemons.append(info)
            except Exception:  # noqa: BLE001
                daemons.append({"daemon_id": daemon_id, "status": "unknown"})
    print(json.dumps(daemons))


def build_parser():
    parser = argparse.ArgumentParser(description="pmfreeze - Lock memory values")
    sub = parser.add_subparsers(dest="command", required=True)

    freeze = sub.add_parser("freeze", help="Freeze values")
    tgt = freeze.add_mutually_exclusive_group(required=True)
    tgt.add_argument("--pid", type=int)
    tgt.add_argument("--name")
    freeze.add_argument("--type", required=True, choices=list(TYPE_MAP.keys()))
    freeze.add_argument("--value", help="Value to freeze (default=current)")
    freeze.add_argument("--address", help="Single address to freeze")
    freeze.add_argument("--addresses", nargs="+", help="Multiple addresses")
    freeze.add_argument("--session", help="Use addresses from scan session")
    freeze.add_argument("--max", type=int, default=100, help="Max addresses from session")
    freeze.add_argument("--daemon-id", help="Run as daemon with ID")
    freeze.set_defaults(func=cmd_freeze)

    stop = sub.add_parser("stop", help="Stop a daemon")
    stop.add_argument("--daemon-id", required=True)
    stop.set_defaults(func=cmd_stop)

    lst = sub.add_parser("list", help="List running daemons")
    lst.set_defaults(func=cmd_list)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
