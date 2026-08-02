#!/usr/bin/env python3
"""
pmpointer.py - Pointer chain scanner (Cheat Engine Pointer Scan style).

Find static pointer paths to a dynamic address. Essential for game hacking
since game addresses change on every restart.

Usage:
  # Scan for pointer chains to a target address
  pmpointer.py scan --pid 1234 --target 0x1A3B4C5D6 --max-level 5 --max-offset 0x1000

  # Verify a pointer chain
  pmpointer.py verify --pid 1234 --chain 'game.exe+0x123456,0x80,0x10,0x28'

  # Resolve a pointer chain to get final address
  pmpointer.py resolve --pid 1234 --chain 'game.exe+0x123456,0x80,0x10,0x28'

  # Re-scan pointer chains for a new target (after game restart)
  pmpointer.py rescan --pid 1234 --chains chains.json --target-value 9999 --type int4
"""

import argparse
import json
import os
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import pymem
    import pymem.process
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


def _get_readable_regions(pm) -> list:
    """Return readable committed memory regions."""
    regions = []
    try:
        mbi_list = pm.list_allocated_memory()
    except Exception:  # noqa: BLE001
        return regions

    for mbi in mbi_list:
        try:
            state = getattr(mbi, 'State', 0)
            protect = getattr(mbi, 'Protect', 0)
            if state != 0x1000:
                continue
            if protect & 0x01:
                continue
            if protect & 0x100:
                continue
            base = getattr(mbi, 'BaseAddress', 0)
            size = getattr(mbi, 'RegionSize', 0)
            if size > 0:
                regions.append((base, size))
        except Exception:  # noqa: BLE001
            continue
    return regions


def _get_modules(pm) -> dict:
    """Return {module_name_lower: base_address}."""
    modules = {}
    for mod in pm.list_modules():
        name = getattr(mod, 'name', '')
        base = getattr(mod, 'lpBaseOfDll', None)
        if name and base:
            modules[name.lower()] = base
    return modules


def _read_ptr(pm, addr: int) -> int:
    """Read a pointer (8 bytes on x64, 4 on x86)."""
    try:
        data = pm.read_bytes(addr, 8)
        val = struct.unpack("<Q", data)[0]
        # Validate: must be in user-space range
        if 0x10000 <= val <= 0x7FFF00000000:
            return val
        return 0
    except Exception:  # noqa: BLE001
        return 0


def _find_pointers_to_target(pm, regions: list, target: int,
                              max_offset: int, threads: int) -> list:
    """
    Find all addresses whose value (as pointer) points within
    [target - max_offset, target].
    Returns list of (pointer_addr, offset).
    """
    target_low = target - max_offset
    results = []

    def scan_region(args):
        pm, base, size, target, target_low = args
        local = []
        try:
            data = pm.read_bytes(base, size)
        except Exception:  # noqa: BLE001
            return local

        # Scan for 8-byte aligned pointer values
        for off in range(0, size - 7, 8):
            try:
                val = struct.unpack_from("<Q", data, off)[0]
            except struct.error:
                continue
            if target_low <= val <= target:
                ptr_addr = base + off
                offset = target - val
                local.append((ptr_addr, offset))
        return local

    work = [(pm, base, size, target, target_low) for base, size in regions]
    with ThreadPoolExecutor(max_workers=threads) as ex:
        futures = [ex.submit(scan_region, w) for w in work]
        for fut in as_completed(futures):
            res = fut.result()
            results.extend(res)

    return results


def _build_chain_str(base_module: str, base_offset: int, offsets: list) -> str:
    """Build human-readable chain string."""
    parts = [f"{base_module}+{base_offset:X}"]
    for o in offsets:
        sign = "" if o >= 0 else "-"
        parts.append(f"{sign}0x{abs(o):X}")
    return " -> ".join(parts)


def _resolve_chain(pm, modules: dict, chain_str: str) -> int:
    """
    Resolve a pointer chain string to a final address.
    Format: 'module+offset,offset,offset,...'
    """
    parts = chain_str.replace(" ", "").split(",")
    base_part = parts[0]

    if "+" in base_part:
        mod_name, off_str = base_part.split("+")
        mod_name = mod_name.strip().lower()
        # Handle 0x prefix
        base_off = int(off_str, 0)
        if mod_name in modules:
            addr = modules[mod_name] + base_off
        else:
            # Try as absolute address
            addr = int(base_part, 0)
    else:
        addr = int(base_part, 0)

    for offset_str in parts[1:]:
        offset = int(offset_str, 0)
        # Read pointer at addr
        ptr = _read_ptr(pm, addr)
        if ptr == 0:
            return 0
        addr = ptr + offset

    return addr


def _verify_chain(pm, modules: dict, chain_str: str, expected: int) -> bool:
    """Verify that a chain resolves to expected address."""
    result = _resolve_chain(pm, modules, chain_str)
    return result == expected


def _is_static_pointer(addr: int, modules: dict) -> tuple:
    """Check if address is inside a module. Return (module_name, offset) or None."""
    for mod_name, mod_base in modules.items():
        try:
            # Get module size
            # We only have base, so we assume a reasonable max size
            if mod_base <= addr <= mod_base + 0x10000000:  # 256MB max
                return (mod_name, addr - mod_base)
        except Exception:  # noqa: BLE001
            continue
    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_scan(args):
    if not HAS_PMEM:
        sys.exit("pymem not available.")

    pm = pymem.Pymem(args.pid) if args.pid else pymem.Pymem(args.name)
    target = int(args.target, 0)
    max_level = args.max_level
    max_offset = int(args.max_offset, 0)
    threads = args.threads

    regions = _get_readable_regions(pm)
    modules = _get_modules(pm)

    if not regions:
        sys.exit("No readable memory regions.")

    print(json.dumps({"status": "scanning", "target": f"0x{target:X}",
                      "max_level": max_level, "max_offset": f"0x{max_offset:X}"}),
          flush=True)

    start_time = time.time()

    # Level 0: Find pointers that point near target
    level_results = {0: [(target, [])]}  # level -> [(addr, offsets_list)]

    all_chains = []

    for level in range(1, max_level + 1):
        prev_addrs = [addr for addr, _ in level_results.get(level - 1, [])]
        if not prev_addrs:
            break

        # For efficiency, take unique addresses
        unique_addrs = list(set(prev_addrs))

        # Find pointers to any of these addresses
        current_level = []
        seen_ptrs = set()

        for check_addr in unique_addrs:
            ptrs = _find_pointers_to_target(pm, regions, check_addr, max_offset, threads)
            for ptr_addr, offset in ptrs:
                if ptr_addr in seen_ptrs:
                    continue
                seen_ptrs.add(ptr_addr)

                # Build offset chain
                for prev_addr, prev_offsets in level_results[level - 1]:
                    if prev_addr == check_addr:
                        new_offsets = [offset] + prev_offsets
                        current_level.append((ptr_addr, new_offsets))

                        # Check if this is a static pointer
                        static = _is_static_pointer(ptr_addr, modules)
                        if static:
                            mod_name, mod_off = static
                            chain_str = _build_chain_str(mod_name, mod_off, new_offsets)
                            chain_data = {
                                "chain": chain_str,
                                "base_module": mod_name,
                                "base_offset": mod_off,
                                "offsets": new_offsets,
                                "level": level,
                            }
                            # Verify
                            resolved = _resolve_chain(pm, modules, f"{mod_name}+{mod_off:X},{','.join(f'0x{o:X}' for o in new_offsets)}")
                            chain_data["resolved"] = f"0x{resolved:X}"
                            chain_data["target"] = f"0x{target:X}"
                            chain_data["valid"] = (resolved == target)
                            all_chains.append(chain_data)

        level_results[level] = current_level

        if args.stop_on_static and any(_is_static_pointer(a, modules) for a, _ in current_level):
            break

    elapsed = time.time() - start_time

    # Sort by level, prefer shorter chains
    all_chains.sort(key=lambda x: (x["level"], not x["valid"]))

    output = {
        "target": f"0x{target:X}",
        "chains_found": len(all_chains),
        "elapsed_sec": round(elapsed, 2),
        "chains": all_chains[:args.max_results],
    }
    print(json.dumps(output))

    # Save if requested
    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)


def cmd_verify(args):
    if not HAS_PMEM:
        sys.exit("pymem not available.")

    pm = pymem.Pymem(args.pid) if args.pid else pymem.Pymem(args.name)
    modules = _get_modules(pm)

    chain_str = args.chain
    expected = int(args.expected, 0) if args.expected else None

    resolved = _resolve_chain(pm, modules, chain_str)

    result = {
        "chain": chain_str,
        "resolved": f"0x{resolved:X}",
    }
    if expected:
        result["expected"] = f"0x{expected:X}"
        result["valid"] = (resolved == expected)

    print(json.dumps(result))


def cmd_resolve(args):
    if not HAS_PMEM:
        sys.exit("pymem not available.")

    pm = pymem.Pymem(args.pid) if args.pid else pymem.Pymem(args.name)
    modules = _get_modules(pm)

    resolved = _resolve_chain(pm, modules, args.chain)

    # Read value at resolved address if type specified
    if args.type and resolved:
        fmt, size = TYPE_MAP[args.type]
        try:
            data = pm.read_bytes(resolved, size)
            val = struct.unpack(f"<{fmt}", data)[0]
            print(json.dumps({"chain": args.chain, "resolved": f"0x{resolved:X}", "value": val}))
            return
        except Exception:  # noqa: BLE001
            pass

    print(json.dumps({"chain": args.chain, "resolved": f"0x{resolved:X}"}))


def cmd_rescan(args):
    """Re-scan saved pointer chains for a new target value."""
    if not HAS_PMEM:
        sys.exit("pymem not available.")

    pm = pymem.Pymem(args.pid) if args.pid else pymem.Pymem(args.name)
    modules = _get_modules(pm)

    with open(args.chains_file, "r") as f:
        data = json.load(f)

    chains = data.get("chains", [])
    target_value = _parse_value(args.target_value, args.type) if args.target_value else None

    valid_chains = []
    for chain_info in chains:
        chain_str = chain_info.get("chain", "")
        resolved = _resolve_chain(pm, modules, chain_str)

        if resolved == 0:
            continue

        entry = {
            "chain": chain_str,
            "resolved": f"0x{resolved:X}",
        }

        if target_value is not None:
            fmt, size = TYPE_MAP[args.type]
            try:
                data = pm.read_bytes(resolved, size)
                val = struct.unpack(f"<{fmt}", data)[0]
                entry["value"] = val
                entry["matches"] = (val == target_value)
                if val == target_value:
                    valid_chains.append(entry)
            except Exception:  # noqa: BLE001
                entry["value"] = None
        else:
            valid_chains.append(entry)

    print(json.dumps({
        "total_chains": len(chains),
        "valid": len(valid_chains),
        "chains": valid_chains,
    }))


def _parse_value(value_str, value_type: str):
    if value_type in ("float", "double"):
        return float(value_str)
    return int(value_str, 0)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(description="pmpointer - Pointer chain scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    scan = sub.add_parser("scan", help="Scan for pointer chains")
    tgt = scan.add_mutually_exclusive_group(required=True)
    tgt.add_argument("--pid", type=int)
    tgt.add_argument("--name")
    scan.add_argument("--target", required=True, help="Target address")
    scan.add_argument("--max-level", type=int, default=5, help="Max pointer depth")
    scan.add_argument("--max-offset", default="0x1000", help="Max offset from pointer")
    scan.add_argument("--threads", type=int, default=4)
    scan.add_argument("--max-results", type=int, default=100)
    scan.add_argument("--stop-on-static", action="store_true",
                      help="Stop when static pointers found")
    scan.add_argument("--output", help="Save results to file")
    scan.set_defaults(func=cmd_scan)

    # verify
    verify = sub.add_parser("verify", help="Verify a pointer chain")
    tgt2 = verify.add_mutually_exclusive_group(required=True)
    tgt2.add_argument("--pid", type=int)
    tgt2.add_argument("--name")
    verify.add_argument("--chain", required=True, help="Chain string: module+off,off,off")
    verify.add_argument("--expected", help="Expected final address")
    verify.set_defaults(func=cmd_verify)

    # resolve
    resolve = sub.add_parser("resolve", help="Resolve chain to address")
    tgt3 = resolve.add_mutually_exclusive_group(required=True)
    tgt3.add_argument("--pid", type=int)
    tgt3.add_argument("--name")
    resolve.add_argument("--chain", required=True)
    resolve.add_argument("--type", choices=list(TYPE_MAP.keys()),
                         help="Read value at resolved address")
    resolve.set_defaults(func=cmd_resolve)

    # rescan
    rescan = sub.add_parser("rescan", help="Re-scan chains for new target")
    tgt4 = rescan.add_mutually_exclusive_group(required=True)
    tgt4.add_argument("--pid", type=int)
    tgt4.add_argument("--name")
    rescan.add_argument("--chains-file", required=True)
    rescan.add_argument("--target-value")
    rescan.add_argument("--type", required=True, choices=list(TYPE_MAP.keys()))
    rescan.set_defaults(func=cmd_rescan)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
