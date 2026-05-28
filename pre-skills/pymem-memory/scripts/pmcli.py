#!/usr/bin/env python3
"""
pmcli.py - Core memory operations CLI for game hacking.

Provides: process listing, typed memory read/write, byte pattern scan,
module introspection, memory protection, allocation, and dumping.
All output is JSON for agent parsing.

Usage:
  pmcli.py process list
  pmcli.py process find --name game.exe
  pmcli.py read int4 --pid 1234 --address 0x7FF60000
  pmcli.py write int4 --pid 1234 --address 0x7FF60000 --data 9999
  pmcli.py scan pattern --pid 1234 --pattern "48 8B 05 ?? ?? ?? ??"
  pmcli.py scan value --pid 1234 --value 100 --type int4
  pmcli.py module list --pid 1234
  pmcli.py module base --pid 1234 --module game.exe
  pmcli.py protect --pid 1234 --address 0x7FF60000 --size 4096 --flag rwx
  pmcli.py allocate --pid 1234 --size 4096
  pmcli.py dump --pid 1234 --address 0x7FF60000 --size 4096 --output dump.bin
  pmcli.py info --pid 1234                    # process memory layout info
  pmcli.py regions --pid 1234                 # list memory regions
"""

import argparse
import base64
import json
import struct
import sys

try:
    import pymem
    import pymem.process
    import pymem.memory
    import pymem.pattern
    import pymem.ressources.structure
    HAS_PMEM = True
except Exception:  # noqa: BLE001
    HAS_PMEM = False

# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------

READERS = {}
WRITERS = {}
TYPE_INFO = {
    "int1": ("b", 1), "uint1": ("B", 1),
    "int2": ("h", 2), "uint2": ("H", 2),
    "int4": ("i", 4), "uint4": ("I", 4),
    "int8": ("q", 8), "uint8": ("Q", 8),
    "float": ("f", 4), "double": ("d", 8),
}

ALL_TYPES = list(TYPE_INFO.keys())


def _open(args):
    if not HAS_PMEM:
        sys.exit("pymem not available. Install: pip install pymem")
    try:
        return pymem.Pymem(args.pid) if getattr(args, "pid", None) else pymem.Pymem(args.name)
    except Exception as exc:  # noqa: BLE001
        target = f"PID {args.pid}" if getattr(args, "pid", None) else f"'{args.name}'"
        sys.exit(f"Failed to open {target}: {exc}")


def _addr(a: str) -> int:
    return int(a, 0)


def _hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def _parse_write_data(data_str: str, val_type: str) -> bytes:
    data_str = data_str.strip()
    if val_type in ("int1", "int2", "int4", "int8"):
        return struct.pack(f"<{TYPE_INFO[val_type][0]}", int(data_str))
    if val_type in ("uint1", "uint2", "uint4", "uint8"):
        return struct.pack(f"<{TYPE_INFO[val_type][0]}", int(data_str))
    if val_type == "float":
        return struct.pack("<f", float(data_str))
    if val_type == "double":
        return struct.pack("<d", float(data_str))
    sys.exit(f"Use 'write bytes' for raw byte data: {val_type}")


# ---------------------------------------------------------------------------
# process
# ---------------------------------------------------------------------------

def cmd_process_list(_args):
    if not HAS_PMEM:
        sys.exit("pymem not available.")
    procs = []
    for proc in pymem.process.list_processes():
        try:
            name = proc.name()
        except Exception:  # noqa: BLE001
            name = "?"
        procs.append({"pid": proc.pid, "name": name})
    print(json.dumps(procs))


def cmd_process_find(args):
    if not HAS_PMEM:
        sys.exit("pymem not available.")
    results = []
    for proc in pymem.process.list_processes():
        try:
            name = proc.name()
        except Exception:  # noqa: BLE001
            continue
        if args.name and args.name.lower() not in name.lower():
            continue
        if args.pid and proc.pid != args.pid:
            continue
        results.append({"pid": proc.pid, "name": name})
    if not results:
        sys.exit(1)
    print(json.dumps(results))


def cmd_process_info(args):
    """Show process memory layout overview."""
    pm = _open(args)
    info = {
        "pid": pm.process_id,
        "base": None,
        "modules": [],
    }
    try:
        for mod in pm.list_modules():
            mod_info = {
                "name": getattr(mod, "name", "?"),
                "base": f"0x{getattr(mod, 'lpBaseOfDll', 0):X}",
                "size": getattr(mod, "SizeOfImage", 0),
            }
            info["modules"].append(mod_info)
            if mod_info["name"].lower() == pm.process_id:
                info["base"] = mod_info["base"]
    except Exception as exc:  # noqa: BLE001
        info["error"] = str(exc)
    print(json.dumps(info))


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------

def cmd_read(args):
    pm = _open(args)
    addr = _addr(args.address)
    vt = args.type
    fmt, size = TYPE_INFO[vt]

    if vt in ("int1", "int2", "int4", "int8", "uint1", "uint2", "uint4", "uint8"):
        val = struct.unpack(f"<{fmt}", pm.read_bytes(addr, size))[0]
        print(json.dumps({"address": f"0x{addr:X}", "type": vt, "value": val}))
    elif vt == "float":
        val = struct.unpack("<f", pm.read_bytes(addr, size))[0]
        print(json.dumps({"address": f"0x{addr:X}", "type": vt, "value": val}))
    elif vt == "double":
        val = struct.unpack("<d", pm.read_bytes(addr, size))[0]
        print(json.dumps({"address": f"0x{addr:X}", "type": vt, "value": val}))
    elif vt == "bytes":
        data = pm.read_bytes(addr, args.size)
        print(json.dumps({"address": f"0x{addr:X}", "type": vt, "hex": _hex(data),
                          "base64": base64.b64encode(data).decode(), "size": len(data)}))
    elif vt == "string":
        raw = pm.read_bytes(addr, args.size)
        null_idx = raw.find(b"\x00")
        s = raw[:null_idx].decode("utf-8", errors="replace") if null_idx != -1 else raw.decode("utf-8", errors="replace")
        print(json.dumps({"address": f"0x{addr:X}", "type": vt, "value": s, "hex": _hex(raw)}))


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------

def cmd_write(args):
    pm = _open(args)
    addr = _addr(args.address)
    vt = args.type

    if vt == "bytes":
        parts = args.data.strip().split()
        data = bytes(int(p, 16) for p in parts)
        pm.write_bytes(addr, data, len(data))
        print(json.dumps({"address": f"0x{addr:X}", "type": vt, "bytes_written": len(data)}))
    elif vt == "string":
        data = args.data.encode("utf-8")
        pm.write_bytes(addr, data, len(data))
        print(json.dumps({"address": f"0x{addr:X}", "type": vt, "bytes_written": len(data)}))
    elif vt in TYPE_INFO:
        data = _parse_write_data(args.data, vt)
        pm.write_bytes(addr, data, len(data))
        print(json.dumps({"address": f"0x{addr:X}", "type": vt, "bytes_written": len(data)}))
    else:
        sys.exit(f"Unknown type: {vt}")


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

def _find_pattern(data: bytes, pattern: str) -> list:
    tokens = pattern.split()
    mask = []
    needle = []
    for tok in tokens:
        if tok in ("??", "?"):
            mask.append(0)
            needle.append(0)
        else:
            mask.append(1)
            needle.append(int(tok, 16))
    needle = bytes(needle)
    mask = bytes(mask)
    n = len(mask)
    results = []
    for i in range(len(data) - n + 1):
        match = True
        for j in range(n):
            if mask[j] and data[i + j] != needle[j]:
                match = False
                break
        if match:
            results.append(i)
    return results


def _get_regions(pm):
    regions = []
    try:
        for mbi in pm.list_allocated_memory():
            state = getattr(mbi, 'State', 0)
            protect = getattr(mbi, 'Protect', 0)
            if state != 0x1000 or protect & 0x01 or protect & 0x100:
                continue
            base = getattr(mbi, 'BaseAddress', 0)
            size = getattr(mbi, 'RegionSize', 0)
            if size > 0:
                regions.append((base, size))
    except Exception:  # noqa: BLE001
        pass
    return regions


def cmd_scan_pattern(args):
    pm = _open(args)
    pattern = args.pattern.strip()
    regions = _get_regions(pm)
    matches = []
    for base, size in regions:
        try:
            data = pm.read_bytes(base, size)
        except Exception:  # noqa: BLE001
            continue
        offsets = _find_pattern(data, pattern)
        for off in offsets:
            matches.append(f"0x{base + off:X}")
    print(json.dumps({"pattern": pattern, "matches": matches, "count": len(matches)}))


def cmd_scan_value(args):
    pm = _open(args)
    regions = _get_regions(pm)
    val_type = args.type
    fmt, size = TYPE_INFO[val_type]

    if val_type in ("float", "double"):
        target = float(args.value)
    else:
        target = int(args.value, 0)
    needle = struct.pack(f"<{fmt}", target)

    matches = []
    for base, rsize in regions:
        try:
            data = pm.read_bytes(base, rsize)
        except Exception:  # noqa: BLE001
            continue
        start = 0
        while True:
            idx = data.find(needle, start)
            if idx == -1:
                break
            matches.append(f"0x{base + idx:X}")
            start = idx + 1

    print(json.dumps({"value": args.value, "type": val_type, "matches": matches, "count": len(matches)}))


# ---------------------------------------------------------------------------
# module
# ---------------------------------------------------------------------------

def cmd_module_list(args):
    pm = _open(args)
    modules = []
    for mod in pm.list_modules():
        modules.append({
            "name": getattr(mod, "name", "?"),
            "base": f"0x{getattr(mod, 'lpBaseOfDll', 0):X}",
            "size": getattr(mod, "SizeOfImage", 0),
            "path": getattr(mod, "filename", ""),
        })
    print(json.dumps(modules))


def cmd_module_base(args):
    pm = _open(args)
    base = pymem.process.module_from_name(pm.process_handle, args.module)
    if base is None:
        sys.exit(1)
    print(json.dumps({
        "module": args.module,
        "base": f"0x{base.lpBaseOfDll:X}",
        "size": base.SizeOfImage,
    }))


# ---------------------------------------------------------------------------
# protect
# ---------------------------------------------------------------------------

def cmd_protect(args):
    pm = _open(args)
    addr = _addr(args.address)
    size = args.size
    protect_map = {"r": 0x02, "rw": 0x04, "rx": 0x20, "rwx": 0x40,
                   "w": 0x04, "x": 0x20, "noaccess": 0x01}
    prot = protect_map.get(args.flag.lower())
    if prot is None:
        sys.exit(f"Unknown protection: {args.flag}")
    old = pymem.memory.set_memory_protection(pm.process_handle, addr, size, prot)
    print(json.dumps({"address": f"0x{addr:X}", "size": size, "protection": args.flag, "old": old}))


# ---------------------------------------------------------------------------
# allocate
# ---------------------------------------------------------------------------

def cmd_allocate(args):
    pm = _open(args)
    addr = pymem.memory.allocate_memory(pm.process_handle, args.size)
    print(json.dumps({"address": f"0x{addr:X}", "size": args.size}))


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------

def cmd_dump(args):
    pm = _open(args)
    addr = _addr(args.address)
    size = args.size
    data = pm.read_bytes(addr, size)
    if args.output:
        with open(args.output, "wb") as f:
            f.write(data)
        print(json.dumps({"address": f"0x{addr:X}", "size": size, "file": args.output}))
    else:
        print(json.dumps({"address": f"0x{addr:X}", "size": size, "hex": _hex(data)}))


# ---------------------------------------------------------------------------
# regions
# ---------------------------------------------------------------------------

def cmd_regions(args):
    pm = _open(args)
    regions = []
    try:
        for mbi in pm.list_allocated_memory():
            state = getattr(mbi, 'State', 0)
            protect = getattr(mbi, 'Protect', 0)
            base = getattr(mbi, 'BaseAddress', 0)
            rsize = getattr(mbi, 'RegionSize', 0)
            regions.append({
                "base": f"0x{base:X}",
                "size": rsize,
                "state": "commit" if state == 0x1000 else "reserve" if state == 0x2000 else "free",
                "protect": protect,
            })
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}))
        return
    print(json.dumps({"count": len(regions), "regions": regions[:args.limit]}))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(description="pmcli - Core memory operations")
    sub = parser.add_subparsers(dest="command", required=True)

    # process
    proc = sub.add_parser("process", help="Process operations")
    proc_sub = proc.add_subparsers(dest="subcmd", required=True)
    pl = proc_sub.add_parser("list", help="List processes")
    pl.set_defaults(func=cmd_process_list)
    pf = proc_sub.add_parser("find", help="Find process")
    pf.add_argument("--name")
    pf.add_argument("--pid", type=int)
    pf.set_defaults(func=cmd_process_find)
    pi = proc_sub.add_parser("info", help="Process info")
    pit = pi.add_mutually_exclusive_group(required=True)
    pit.add_argument("--pid", type=int)
    pit.add_argument("--name")
    pi.set_defaults(func=cmd_process_info)

    # read
    rd = sub.add_parser("read", help="Read memory")
    rd.add_argument("type", choices=ALL_TYPES + ["bytes", "string"])
    rt = rd.add_mutually_exclusive_group(required=True)
    rt.add_argument("--pid", type=int)
    rt.add_argument("--name")
    rd.add_argument("--address", required=True)
    rd.add_argument("--size", type=int, default=64)
    rd.set_defaults(func=cmd_read)

    # write
    wr = sub.add_parser("write", help="Write memory")
    wr.add_argument("type", choices=ALL_TYPES + ["bytes", "string"])
    wt = wr.add_mutually_exclusive_group(required=True)
    wt.add_argument("--pid", type=int)
    wt.add_argument("--name")
    wr.add_argument("--address", required=True)
    wr.add_argument("--data", required=True)
    wr.set_defaults(func=cmd_write)

    # scan
    scan = sub.add_parser("scan", help="Scan memory")
    scan_sub = scan.add_subparsers(dest="subcmd", required=True)
    sp = scan_sub.add_parser("pattern", help="Byte pattern scan")
    spt = sp.add_mutually_exclusive_group(required=True)
    spt.add_argument("--pid", type=int)
    spt.add_argument("--name")
    sp.add_argument("--pattern", required=True)
    sp.set_defaults(func=cmd_scan_pattern)
    sv = scan_sub.add_parser("value", help="Value scan")
    svt = sv.add_mutually_exclusive_group(required=True)
    svt.add_argument("--pid", type=int)
    svt.add_argument("--name")
    sv.add_argument("--value", required=True)
    sv.add_argument("--type", required=True, choices=ALL_TYPES)
    sv.set_defaults(func=cmd_scan_value)

    # module
    mod = sub.add_parser("module", help="Module operations")
    mod_sub = mod.add_subparsers(dest="subcmd", required=True)
    ml = mod_sub.add_parser("list", help="List modules")
    mlt = ml.add_mutually_exclusive_group(required=True)
    mlt.add_argument("--pid", type=int)
    mlt.add_argument("--name")
    ml.set_defaults(func=cmd_module_list)
    mb = mod_sub.add_parser("base", help="Get module base")
    mbt = mb.add_mutually_exclusive_group(required=True)
    mbt.add_argument("--pid", type=int)
    mbt.add_argument("--name")
    mb.add_argument("--module", required=True)
    mb.set_defaults(func=cmd_module_base)

    # protect
    prot = sub.add_parser("protect", help="Change memory protection")
    pt = prot.add_mutually_exclusive_group(required=True)
    pt.add_argument("--pid", type=int)
    pt.add_argument("--name")
    prot.add_argument("--address", required=True)
    prot.add_argument("--size", type=int, required=True)
    prot.add_argument("--flag", required=True, help="r/rw/rx/rwx/noaccess")
    prot.set_defaults(func=cmd_protect)

    # allocate
    alloc = sub.add_parser("allocate", help="Allocate memory")
    at = alloc.add_mutually_exclusive_group(required=True)
    at.add_argument("--pid", type=int)
    at.add_argument("--name")
    alloc.add_argument("--size", type=int, required=True)
    alloc.set_defaults(func=cmd_allocate)

    # dump
    dump = sub.add_parser("dump", help="Dump memory")
    dt = dump.add_mutually_exclusive_group(required=True)
    dt.add_argument("--pid", type=int)
    dt.add_argument("--name")
    dump.add_argument("--address", required=True)
    dump.add_argument("--size", type=int, required=True)
    dump.add_argument("--output")
    dump.set_defaults(func=cmd_dump)

    # regions
    reg = sub.add_parser("regions", help="List memory regions")
    rt2 = reg.add_mutually_exclusive_group(required=True)
    rt2.add_argument("--pid", type=int)
    rt2.add_argument("--name")
    reg.add_argument("--limit", type=int, default=1000)
    reg.set_defaults(func=cmd_regions)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
