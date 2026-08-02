#!/usr/bin/env python3
"""
pmload.py - DLL injection and ejection helper.

Usage:
  pmload.py inject --pid 1234 --dll C:\\path\\to\\mylib.dll
  pmload.py inject --name game.exe --dll mylib.dll
  pmload.py eject --pid 1234 --dll mylib.dll
"""

import argparse
import json
import os
import sys

try:
    import pymem
    import pymem.process
    HAS_PMEM = True
except Exception:  # noqa: BLE001
    HAS_PMEM = False


def cmd_inject(args):
    if not HAS_PMEM:
        sys.exit("pymem not available.")
    pm = pymem.Pymem(args.pid) if args.pid else pymem.Pymem(args.name)
    dll_path = os.path.abspath(args.dll)
    if not os.path.isfile(dll_path):
        sys.exit(f"DLL not found: {dll_path}")
    try:
        pymem.process.inject_dll(pm.process_handle, dll_path.encode())
        print(json.dumps({"status": "injected", "dll": dll_path, "pid": pm.process_id}))
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Injection failed: {exc}")


def cmd_eject(args):
    if not HAS_PMEM:
        sys.exit("pymem not available.")
    pm = pymem.Pymem(args.pid) if args.pid else pymem.Pymem(args.name)
    dll_name = os.path.basename(args.dll).lower()
    found = False
    for mod in pm.list_modules():
        mod_name = getattr(mod, "name", "").lower()
        mod_file = getattr(mod, "filename", "").lower()
        if dll_name in mod_name or dll_name in mod_file:
            try:
                pymem.process.eject_dll(pm.process_handle, mod)
                print(json.dumps({"status": "ejected", "dll": mod_file or mod_name, "pid": pm.process_id}))
                found = True
                break
            except Exception as exc:  # noqa: BLE001
                sys.exit(f"Ejection failed: {exc}")
    if not found:
        sys.exit(f"Module not found: {args.dll}")


def main():
    parser = argparse.ArgumentParser(description="pmload - DLL injection")
    sub = parser.add_subparsers(dest="cmd", required=True)

    inj = sub.add_parser("inject")
    t = inj.add_mutually_exclusive_group(required=True)
    t.add_argument("--pid", type=int)
    t.add_argument("--name")
    inj.add_argument("--dll", required=True)
    inj.set_defaults(func=cmd_inject)

    ej = sub.add_parser("eject")
    t2 = ej.add_mutually_exclusive_group(required=True)
    t2.add_argument("--pid", type=int)
    t2.add_argument("--name")
    ej.add_argument("--dll", required=True)
    ej.set_defaults(func=cmd_eject)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
