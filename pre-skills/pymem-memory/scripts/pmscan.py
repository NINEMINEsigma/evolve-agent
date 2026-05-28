#!/usr/bin/env python3
"""
pmscan.py - Cheat Engine-style iterative memory scanner.

Core workflow (same as Cheat Engine):
  1. First Scan  -> capture initial memory snapshot + filter
  2. Next Scan   -> refine against previous results
  3. Undo Scan   -> revert to previous scan state
  4. Freeze      -> lock found addresses

Scan types:
  First scan:  exact, unknown, bigger_than, smaller_than, between
  Next scan:   exact, bigger_than, smaller_than, between,
               changed, unchanged, increased, decreased,
               increased_by, decreased_by, same_as_first

Usage:
  # First scan - exact value
  pmscan.py first --pid 1234 --value 100 --type int4 --session myscan

  # Next scan - decreased value
  pmscan.py next --session myscan --type decreased

  # Next scan - exact value
  pmscan.py next --session myscan --type exact --value 95

  # Undo last scan
  pmscan.py undo --session myscan

  # Show current results
  pmscan.py results --session myscan

  # Save/Load sessions
  pmscan.py save --session myscan --file scan.json
  pmscan.py load --file scan.json --session myscan2
"""

import argparse
import json
import os
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import IntEnum

try:
    import pymem
    import pymem.process
    HAS_PMEM = True
except Exception:  # noqa: BLE001
    HAS_PMEM = False

# ---------------------------------------------------------------------------
# Data type definitions
# ---------------------------------------------------------------------------

TYPE_MAP = {
    "int1": ("b", 1), "uint1": ("B", 1),
    "int2": ("h", 2), "uint2": ("H", 2),
    "int4": ("i", 4), "uint4": ("I", 4),
    "int8": ("q", 8), "uint8": ("Q", 8),
    "float": ("f", 4), "double": ("d", 8),
}

SCAN_ALIGN = {
    "int1": 1, "uint1": 1,
    "int2": 2, "uint2": 2,
    "int4": 4, "uint4": 4,
    "int8": 8, "uint8": 8,
    "float": 4, "double": 8,
}


class ScanType:
    # First scan types
    EXACT = "exact"
    UNKNOWN = "unknown"
    BIGGER_THAN = "bigger_than"
    SMALLER_THAN = "smaller_than"
    BETWEEN = "between"
    # Next scan types
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    INCREASED = "increased"
    DECREASED = "decreased"
    INCREASED_BY = "increased_by"
    DECREASED_BY = "decreased_by"
    SAME_AS_FIRST = "same_as_first"


FIRST_SCAN_TYPES = [ScanType.EXACT, ScanType.UNKNOWN, ScanType.BIGGER_THAN,
                    ScanType.SMALLER_THAN, ScanType.BETWEEN]
NEXT_SCAN_TYPES = [ScanType.EXACT, ScanType.BIGGER_THAN, ScanType.SMALLER_THAN,
                   ScanType.BETWEEN, ScanType.CHANGED, ScanType.UNCHANGED,
                   ScanType.INCREASED, ScanType.DECREASED,
                   ScanType.INCREASED_BY, ScanType.DECREASED_BY,
                   ScanType.SAME_AS_FIRST]


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

SESSIONS = {}  # in-memory sessions
SESSION_DIR = os.path.join(os.path.expanduser("~"), ".pmscan")


def _session_path(name: str) -> str:
    os.makedirs(SESSION_DIR, exist_ok=True)
    return os.path.join(SESSION_DIR, f"{name}.json")


def load_session(name: str) -> dict:
    """Load session from memory or disk."""
    if name in SESSIONS:
        return SESSIONS[name]
    path = _session_path(name)
    if os.path.exists(path):
        with open(path, "r") as f:
            sess = json.load(f)
        # Convert address keys back to strings for JSON compatibility
        SESSIONS[name] = sess
        return sess
    return None


def save_session(name: str, sess: dict):
    """Save session to memory and disk."""
    SESSIONS[name] = sess
    path = _session_path(name)
    with open(path, "w") as f:
        json.dump(sess, f, indent=2)


def init_session(name: str, pid: int, value_type: str) -> dict:
    """Create a new empty session."""
    sess = {
        "pid": pid,
        "value_type": value_type,
        "align": SCAN_ALIGN.get(value_type, 1),
        "scans": [],  # list of scan results
        "frozen": {},  # addr -> value for freeze
        "created": time.time(),
    }
    save_session(name, sess)
    return sess


# ---------------------------------------------------------------------------
# Memory reading helpers
# ---------------------------------------------------------------------------

def get_readable_regions(pm) -> list:
    """Return list of readable, committed memory regions."""
    regions = []
    try:
        mbi_list = pm.list_allocated_memory()
    except Exception:  # noqa: BLE001
        # Fallback: use VirtualQueryEx manually
        mbi_list = _query_memory_regions(pm.process_handle)

    for mbi in mbi_list:
        try:
            # Check if region is committed and readable
            state = getattr(mbi, 'State', 0)
            protect = getattr(mbi, 'Protect', 0)
            if state != 0x1000:  # MEM_COMMIT
                continue
            # Skip no-access and guard pages
            if protect & 0x01:  # PAGE_NOACCESS
                continue
            if protect & 0x100:  # PAGE_GUARD
                continue
            base = getattr(mbi, 'BaseAddress', 0)
            size = getattr(mbi, 'RegionSize', 0)
            if size > 0:
                regions.append((base, size))
        except Exception:  # noqa: BLE001
            continue
    return regions


def _query_memory_regions(handle) -> list:
    """Fallback memory region enumeration using VirtualQueryEx."""
    try:
        from ctypes import wintypes
        import ctypes

        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD),
                ("RegionSize", ctypes.c_size_t),
                ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD),
                ("Type", wintypes.DWORD),
            ]

        kernel32 = ctypes.windll.kernel32
        VirtualQueryEx = kernel32.VirtualQueryEx
        VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                   ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
        VirtualQueryEx.restype = ctypes.c_size_t

        regions = []
        addr = 0
        mbi = MEMORY_BASIC_INFORMATION()
        while VirtualQueryEx(handle, addr, ctypes.byref(mbi), ctypes.sizeof(mbi)):
            regions.append(mbi)
            addr = mbi.BaseAddress + mbi.RegionSize
            if addr > 0x7FFF00000000:  # stop at user-space limit for x64
                break
            mbi = MEMORY_BASIC_INFORMATION()
        return regions
    except Exception:  # noqa: BLE001
        return []


def read_region(pm, base: int, size: int) -> bytes:
    """Read a memory region, return empty bytes on failure."""
    try:
        return pm.read_bytes(base, size)
    except Exception:  # noqa: BLE001
        return b""


# ---------------------------------------------------------------------------
# Scanning engine
# ---------------------------------------------------------------------------

def _unpack_value(data: bytes, offset: int, value_type: str):
    """Unpack a value from bytes at offset."""
    fmt, size = TYPE_MAP[value_type]
    if offset + size > len(data):
        return None
    try:
        return struct.unpack_from(f"<{fmt}", data, offset)[0]
    except struct.error:
        return None


def _pack_value(value, value_type: str) -> bytes:
    """Pack a value to bytes."""
    fmt, _ = TYPE_MAP[value_type]
    return struct.pack(f"<{fmt}", value)


def _scan_region_exact(args):
    """Worker: scan a region for exact value (first scan)."""
    pm, base, size, value, value_type, align = args
    data = read_region(pm, base, size)
    if not data:
        return []
    fmt_info = TYPE_MAP[value_type]
    val_size = fmt_info[1]
    packed = _pack_value(value, value_type)
    matches = []
    for off in range(0, len(data) - val_size + 1, align):
        if data[off:off + val_size] == packed:
            matches.append(f"0x{base + off:X}")
    return matches


def _scan_region_unknown(args):
    """Worker: scan a region, return all aligned addresses (first scan)."""
    pm, base, size, _, value_type, align = args
    data = read_region(pm, base, size)
    if not data:
        return []
    val_size = TYPE_MAP[value_type][1]
    return [f"0x{base + off:X}" for off in range(0, len(data) - val_size + 1, align)]


def _scan_region_range(args):
    """Worker: scan a region for values in range (first scan)."""
    pm, base, size, value_range, value_type, align = args
    data = read_region(pm, base, size)
    if not data:
        return []
    lo, hi = value_range
    val_size = TYPE_MAP[value_type][1]
    matches = []
    for off in range(0, len(data) - val_size + 1, align):
        val = _unpack_value(data, off, value_type)
        if val is not None and lo <= val <= hi:
            matches.append(f"0x{base + off:X}")
    return matches


def _scan_region_next(args):
    """Worker: next scan against previous results."""
    pm, prev_addrs, scan_type, value, value_type, align = args
    # Group addresses by page for efficient reading
    results = []
    if not prev_addrs:
        return results

    # Read memory at each previous address
    fmt, val_size = TYPE_MAP[value_type]

    for addr_str in prev_addrs:
        addr = int(addr_str, 0)
        try:
            current_data = pm.read_bytes(addr, val_size)
            current_val = struct.unpack(f"<{fmt}", current_data)[0]
        except Exception:  # noqa: BLE001
            continue

        prev_val = value  # For exact/range comparisons

        if scan_type == ScanType.EXACT:
            if current_val == prev_val:
                results.append(addr_str)
        elif scan_type == ScanType.BIGGER_THAN:
            if current_val > prev_val:
                results.append(addr_str)
        elif scan_type == ScanType.SMALLER_THAN:
            if current_val < prev_val:
                results.append(addr_str)
        elif scan_type == ScanType.BETWEEN:
            lo, hi = value
            if lo <= current_val <= hi:
                results.append(addr_str)
        elif scan_type in (ScanType.CHANGED, ScanType.UNCHANGED,
                           ScanType.INCREASED, ScanType.DECREASED,
                           ScanType.INCREASED_BY, ScanType.DECREASED_BY,
                           ScanType.SAME_AS_FIRST):
            # These need the snapshot from first scan
            # Will be handled in the caller
            results.append((addr_str, current_val))
        else:
            results.append(addr_str)

    return results


def _filter_with_snapshot(prev_addrs: list, scan_type: str, value, snapshot: dict,
                          scan_value_type: str) -> list:
    """Filter addresses using the first-scan snapshot."""
    results = []
    fmt, val_size = TYPE_MAP[scan_value_type]

    for addr_str in prev_addrs:
        if addr_str not in snapshot:
            continue
        first_val = snapshot[addr_str]

        # Read current value
        try:
            # We need a pm object here but we don't have one in this context
            # The snapshot already has the first-scan values
            # For next scans that need current values, they were already read
            pass
        except Exception:  # noqa: BLE001
            continue

    # This function is called with current values already read
    # The _scan_region_next function returns tuples for snapshot-based scans
    return results


def _scan_region_next_with_snapshot(args):
    """Worker: next scan that requires snapshot comparison."""
    pm, prev_addrs_with_values, scan_type, value, value_type, snapshot = args
    results = []
    fmt, val_size = TYPE_MAP[value_type]

    for item in prev_addrs_with_values:
        if isinstance(item, tuple):
            addr_str, current_val = item
        else:
            addr_str = item
            addr = int(addr_str, 0)
            try:
                current_data = pm.read_bytes(addr, val_size)
                current_val = struct.unpack(f"<{fmt}", current_data)[0]
            except Exception:  # noqa: BLE001
                continue

        if addr_str not in snapshot:
            continue

        first_val = snapshot[addr_str]

        if scan_type == ScanType.CHANGED:
            if current_val != first_val:
                results.append(addr_str)
        elif scan_type == ScanType.UNCHANGED:
            if current_val == first_val:
                results.append(addr_str)
        elif scan_type == ScanType.INCREASED:
            if current_val > first_val:
                results.append(addr_str)
        elif scan_type == ScanType.DECREASED:
            if current_val < first_val:
                results.append(addr_str)
        elif scan_type == ScanType.INCREASED_BY:
            delta = value
            if current_val == first_val + delta:
                results.append(addr_str)
        elif scan_type == ScanType.DECREASED_BY:
            delta = value
            if current_val == first_val - delta:
                results.append(addr_str)
        elif scan_type == ScanType.SAME_AS_FIRST:
            if current_val == first_val:
                results.append(addr_str)

    return results


def _scan_region_range_first(args):
    """Worker: first scan with bigger_than / smaller_than."""
    pm, base, size, value, value_type, align, op = args
    data = read_region(pm, base, size)
    if not data:
        return []
    val_size = TYPE_MAP[value_type][1]
    matches = []
    threshold = value
    for off in range(0, len(data) - val_size + 1, align):
        val = _unpack_value(data, off, value_type)
        if val is None:
            continue
        if op == ">" and val > threshold:
            matches.append(f"0x{base + off:X}")
        elif op == "<" and val < threshold:
            matches.append(f"0x{base + off:X}")
    return matches


def _take_snapshot(pm, addrs: list, value_type: str) -> dict:
    """Take a snapshot of values at given addresses."""
    fmt, val_size = TYPE_MAP[value_type]
    snapshot = {}
    for addr_str in addrs:
        addr = int(addr_str, 0)
        try:
            data = pm.read_bytes(addr, val_size)
            val = struct.unpack(f"<{fmt}", data)[0]
            snapshot[addr_str] = val
        except Exception:  # noqa: BLE001
            pass
    return snapshot


def _read_current_values(pm, addrs: list, value_type: str) -> list:
    """Read current values at addresses, return list of (addr, value)."""
    fmt, val_size = TYPE_MAP[value_type]
    results = []
    for addr_str in addrs:
        addr = int(addr_str, 0)
        try:
            data = pm.read_bytes(addr, val_size)
            val = struct.unpack(f"<{fmt}", data)[0]
            results.append((addr_str, val))
        except Exception:  # noqa: BLE001
            pass
    return results


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_first(args):
    if not HAS_PMEM:
        sys.exit("pymem not available. Install: pip install pymem")

    pm = pymem.Pymem(args.pid) if args.pid else pymem.Pymem(args.name)
    sess = init_session(args.session, pm.process_id, args.type)

    regions = get_readable_regions(pm)
    if not regions:
        sys.exit("No readable memory regions found.")

    scan_type = args.scan_type
    align = args.align or sess["align"]

    # Build work items
    work_items = []
    for base, size in regions:
        work_items.append((pm, base, size, None, args.type, align))

    start_time = time.time()
    all_matches = []

    if scan_type == ScanType.UNKNOWN:
        # Unknown initial value: capture all aligned addresses as snapshot
        worker = _scan_region_unknown
        with ThreadPoolExecutor(max_workers=args.threads) as ex:
            futures = {ex.submit(worker, wi): i for i, wi in enumerate(work_items)}
            for fut in as_completed(futures):
                matches = fut.result()
                if matches:
                    all_matches.extend(matches)

        # Take snapshot of all values
        snapshot = _take_snapshot(pm, all_matches, args.type)
        sess["scans"].append({
            "type": "first",
            "scan_type": scan_type,
            "match_count": len(all_matches),
            "timestamp": time.time(),
            "snapshot": snapshot,
            "results": all_matches[:args.max_results],
        })

    elif scan_type == ScanType.EXACT:
        value = _parse_value(args.value, args.type)
        worker = _scan_region_exact
        work_items = [(pm, base, size, value, args.type, align) for base, size in regions]

        with ThreadPoolExecutor(max_workers=args.threads) as ex:
            futures = {ex.submit(worker, wi): i for i, wi in enumerate(work_items)}
            for fut in as_completed(futures):
                matches = fut.result()
                if matches:
                    all_matches.extend(matches)

        snapshot = _take_snapshot(pm, all_matches, args.type)
        sess["scans"].append({
            "type": "first",
            "scan_type": scan_type,
            "value": value,
            "match_count": len(all_matches),
            "timestamp": time.time(),
            "snapshot": snapshot,
            "results": all_matches[:args.max_results],
        })

    elif scan_type in (ScanType.BIGGER_THAN, ScanType.SMALLER_THAN):
        value = _parse_value(args.value, args.type)
        op = ">" if scan_type == ScanType.BIGGER_THAN else "<"
        work_items = [(pm, base, size, value, args.type, align, op) for base, size in regions]

        with ThreadPoolExecutor(max_workers=args.threads) as ex:
            futures = {ex.submit(_scan_region_range_first, wi) for wi in work_items}
            for fut in as_completed(futures):
                matches = fut.result()
                if matches:
                    all_matches.extend(matches)

        snapshot = _take_snapshot(pm, all_matches, args.type)
        sess["scans"].append({
            "type": "first",
            "scan_type": scan_type,
            "value": value,
            "match_count": len(all_matches),
            "timestamp": time.time(),
            "snapshot": snapshot,
            "results": all_matches[:args.max_results],
        })

    elif scan_type == ScanType.BETWEEN:
        lo = _parse_value(args.value, args.type)
        hi = _parse_value(args.value2, args.type)
        work_items = [(pm, base, size, (lo, hi), args.type, align) for base, size in regions]

        with ThreadPoolExecutor(max_workers=args.threads) as ex:
            futures = {ex.submit(_scan_region_range, wi) for wi in work_items}
            for fut in as_completed(futures):
                matches = fut.result()
                if matches:
                    all_matches.extend(matches)

        snapshot = _take_snapshot(pm, all_matches, args.type)
        sess["scans"].append({
            "type": "first",
            "scan_type": scan_type,
            "value_lo": lo,
            "value_hi": hi,
            "match_count": len(all_matches),
            "timestamp": time.time(),
            "snapshot": snapshot,
            "results": all_matches[:args.max_results],
        })

    elapsed = time.time() - start_time
    save_session(args.session, sess)

    output = {
        "scan": "first",
        "type": scan_type,
        "matches": len(all_matches),
        "elapsed_sec": round(elapsed, 2),
        "results": all_matches[:args.max_results],
    }
    print(json.dumps(output))


def cmd_next(args):
    if not HAS_PMEM:
        sys.exit("pymem not available.")

    sess = load_session(args.session)
    if not sess:
        sys.exit(f"Session '{args.session}' not found. Run a first scan first.")
    if not sess["scans"]:
        sys.exit("No previous scans. Run a first scan first.")

    pm = pymem.Pymem(sess["pid"])
    last_scan = sess["scans"][-1]
    prev_results = last_scan.get("results", [])
    snapshot = last_scan.get("snapshot", {})

    if not prev_results:
        sys.exit("No results from previous scan to refine.")

    scan_type = args.scan_type
    value_type = sess["value_type"]

    start_time = time.time()

    # Read current values at all previous addresses
    current_values = _read_current_values(pm, prev_results, value_type)

    if scan_type in (ScanType.CHANGED, ScanType.UNCHANGED,
                     ScanType.INCREASED, ScanType.DECREASED,
                     ScanType.INCREASED_BY, ScanType.DECREASED_BY,
                     ScanType.SAME_AS_FIRST):
        # These need snapshot comparison
        all_matches = []
        for addr_str, current_val in current_values:
            if addr_str not in snapshot:
                continue
            first_val = snapshot[addr_str]

            if scan_type == ScanType.CHANGED:
                if current_val != first_val:
                    all_matches.append(addr_str)
            elif scan_type == ScanType.UNCHANGED:
                if current_val == first_val:
                    all_matches.append(addr_str)
            elif scan_type == ScanType.INCREASED:
                if current_val > first_val:
                    all_matches.append(addr_str)
            elif scan_type == ScanType.DECREASED:
                if current_val < first_val:
                    all_matches.append(addr_str)
            elif scan_type == ScanType.INCREASED_BY:
                delta = _parse_value(args.value, value_type)
                if current_val == first_val + delta:
                    all_matches.append(addr_str)
            elif scan_type == ScanType.DECREASED_BY:
                delta = _parse_value(args.value, value_type)
                if current_val == first_val - delta:
                    all_matches.append(addr_str)
            elif scan_type == ScanType.SAME_AS_FIRST:
                if current_val == first_val:
                    all_matches.append(addr_str)

        # Build new snapshot for matched addresses
        new_snapshot = {addr: snapshot.get(addr) for addr in all_matches if addr in snapshot}

    elif scan_type == ScanType.EXACT:
        target = _parse_value(args.value, value_type)
        all_matches = [addr for addr, val in current_values if val == target]
        new_snapshot = {addr: val for addr, val in current_values if val == target}

    elif scan_type == ScanType.BIGGER_THAN:
        target = _parse_value(args.value, value_type)
        all_matches = [addr for addr, val in current_values if val > target]
        new_snapshot = {addr: val for addr, val in current_values if val > target}

    elif scan_type == ScanType.SMALLER_THAN:
        target = _parse_value(args.value, value_type)
        all_matches = [addr for addr, val in current_values if val < target]
        new_snapshot = {addr: val for addr, val in current_values if val < target}

    elif scan_type == ScanType.BETWEEN:
        lo = _parse_value(args.value, value_type)
        hi = _parse_value(args.value2, value_type)
        all_matches = [addr for addr, val in current_values if lo <= val <= hi]
        new_snapshot = {addr: val for addr, val in current_values if lo <= val <= hi}

    else:
        sys.exit(f"Unknown scan type: {scan_type}")

    elapsed = time.time() - start_time

    sess["scans"].append({
        "type": "next",
        "scan_type": scan_type,
        "match_count": len(all_matches),
        "timestamp": time.time(),
        "snapshot": new_snapshot,
        "results": all_matches[:args.max_results],
    })
    save_session(args.session, sess)

    output = {
        "scan": "next",
        "type": scan_type,
        "matches": len(all_matches),
        "elapsed_sec": round(elapsed, 2),
        "results": all_matches[:args.max_results],
    }
    print(json.dumps(output))


def cmd_undo(args):
    sess = load_session(args.session)
    if not sess:
        sys.exit(f"Session '{args.session}' not found.")
    if len(sess["scans"]) <= 1:
        sys.exit("Cannot undo: only one scan in history.")

    removed = sess["scans"].pop()
    save_session(args.session, sess)

    last_scan = sess["scans"][-1] if sess["scans"] else None
    print(json.dumps({
        "undone": removed["type"],
        "scan_type": removed.get("scan_type"),
        "current_matches": last_scan["match_count"] if last_scan else 0,
        "current_results": last_scan.get("results", [])[:100] if last_scan else [],
    }))


def cmd_results(args):
    sess = load_session(args.session)
    if not sess:
        sys.exit(f"Session '{args.session}' not found.")
    if not sess["scans"]:
        sys.exit("No scans in session.")

    last_scan = sess["scans"][-1]
    results = last_scan.get("results", [])

    # Read current values for display
    if HAS_PMEM and args.with_values:
        pm = pymem.Pymem(sess["pid"])
        fmt, val_size = TYPE_MAP[sess["value_type"]]
        enriched = []
        for addr_str in results[:args.limit]:
            addr = int(addr_str, 0)
            try:
                data = pm.read_bytes(addr, val_size)
                val = struct.unpack(f"<{fmt}", data)[0]
                enriched.append({"address": addr_str, "value": val})
            except Exception:  # noqa: BLE001
                enriched.append({"address": addr_str, "value": None})
        print(json.dumps({
            "session": args.session,
            "pid": sess["pid"],
            "value_type": sess["value_type"],
            "total_scans": len(sess["scans"]),
            "current_matches": last_scan["match_count"],
            "results": enriched,
        }))
    else:
        print(json.dumps({
            "session": args.session,
            "pid": sess["pid"],
            "value_type": sess["value_type"],
            "total_scans": len(sess["scans"]),
            "current_matches": last_scan["match_count"],
            "results": results[:args.limit],
        }))


def cmd_history(args):
    sess = load_session(args.session)
    if not sess:
        sys.exit(f"Session '{args.session}' not found.")

    history = []
    for i, scan in enumerate(sess["scans"]):
        history.append({
            "index": i + 1,
            "type": scan["type"],
            "scan_type": scan.get("scan_type"),
            "matches": scan["match_count"],
            "timestamp": scan["timestamp"],
        })

    print(json.dumps({
        "session": args.session,
        "pid": sess["pid"],
        "value_type": sess["value_type"],
        "history": history,
    }))


def cmd_save(args):
    sess = load_session(args.session)
    if not sess:
        sys.exit(f"Session '{args.session}' not found.")

    path = os.path.abspath(args.file)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(sess, f, indent=2)
    print(json.dumps({"saved": path, "session": args.session}))


def cmd_load(args):
    path = os.path.abspath(args.file)
    if not os.path.exists(path):
        sys.exit(f"File not found: {path}")
    with open(path, "r") as f:
        sess = json.load(f)

    name = args.session or os.path.splitext(os.path.basename(path))[0]
    save_session(name, sess)
    print(json.dumps({
        "loaded": path,
        "session": name,
        "pid": sess["pid"],
        "value_type": sess["value_type"],
        "total_scans": len(sess["scans"]),
    }))


def cmd_freeze(args):
    """Freeze (lock) values at found addresses - runs in foreground."""
    if not HAS_PMEM:
        sys.exit("pymem not available.")

    sess = load_session(args.session)
    if not sess:
        sys.exit(f"Session '{args.session}' not found.")

    pm = pymem.Pymem(sess["pid"])
    fmt, val_size = TYPE_MAP[sess["value_type"]]

    # Determine which addresses to freeze
    freeze_addrs = {}
    if args.addresses:
        for a in args.addresses:
            freeze_addrs[a] = None  # Will read current value
    else:
        # Freeze all current results
        last_scan = sess["scans"][-1] if sess["scans"] else None
        if last_scan:
            for a in last_scan.get("results", []):
                freeze_addrs[a] = None

    if not freeze_addrs:
        sys.exit("No addresses to freeze.")

    # Read current values to use as freeze targets
    for addr_str in list(freeze_addrs.keys()):
        addr = int(addr_str, 0)
        try:
            if args.value is not None:
                freeze_addrs[addr_str] = _parse_value(args.value, sess["value_type"])
            else:
                data = pm.read_bytes(addr, val_size)
                freeze_addrs[addr_str] = struct.unpack(f"<{fmt}", data)[0]
        except Exception:  # noqa: BLE001
            del freeze_addrs[addr_str]

    print(json.dumps({
        "status": "freezing",
        "session": args.session,
        "addresses": len(freeze_addrs),
        "targets": [{"address": a, "value": v} for a, v in freeze_addrs.items()],
    }), flush=True)

    # Freeze loop
    try:
        packed = {a: _pack_value(v, sess["value_type"]) for a, v in freeze_addrs.items()}
        while True:
            for addr_str, pval in packed.items():
                try:
                    pm.write_bytes(int(addr_str, 0), pval, len(pval))
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(0.01)  # 100Hz refresh
    except KeyboardInterrupt:
        print(json.dumps({"status": "unfrozen", "session": args.session}))


def cmd_sessions(_args):
    """List all saved sessions."""
    os.makedirs(SESSION_DIR, exist_ok=True)
    sessions = []
    for f in os.listdir(SESSION_DIR):
        if f.endswith(".json"):
            name = f[:-5]
            try:
                sess = load_session(name)
                sessions.append({
                    "name": name,
                    "pid": sess["pid"],
                    "value_type": sess["value_type"],
                    "scans": len(sess["scans"]),
                })
            except Exception:  # noqa: BLE001
                pass
    print(json.dumps(sessions))


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------

def _parse_value(value_str, value_type: str):
    """Parse a string value to the appropriate Python type."""
    if value_type in ("float", "double"):
        return float(value_str)
    return int(value_str, 0)  # supports 0x prefix


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(description="pmscan - CE-style iterative memory scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    # first scan
    first = sub.add_parser("first", help="First scan")
    tgt = first.add_mutually_exclusive_group(required=True)
    tgt.add_argument("--pid", type=int)
    tgt.add_argument("--name")
    first.add_argument("--type", required=True, choices=list(TYPE_MAP.keys()),
                       help="Value type (int1/2/4/8, uint1/2/4/8, float, double)")
    first.add_argument("--scan-type", required=True,
                       choices=FIRST_SCAN_TYPES,
                       help="First scan type")
    first.add_argument("--value", help="Value to search (for exact/bigger/smaller)")
    first.add_argument("--value2", help="Upper bound for between scan")
    first.add_argument("--session", required=True, help="Session name")
    first.add_argument("--threads", type=int, default=4, help="Scan threads")
    first.add_argument("--align", type=int, help="Alignment (default=type size)")
    first.add_argument("--max-results", type=int, default=10000,
                       help="Max results to keep")
    first.set_defaults(func=cmd_first)

    # next scan
    nxt = sub.add_parser("next", help="Next scan (refine results)")
    nxt.add_argument("--session", required=True)
    nxt.add_argument("--scan-type", required=True, choices=NEXT_SCAN_TYPES,
                     help="Next scan type")
    nxt.add_argument("--value", help="Value for exact/bigger/smaller/increased_by/decreased_by")
    nxt.add_argument("--value2", help="Upper bound for between scan")
    nxt.add_argument("--max-results", type=int, default=10000)
    nxt.set_defaults(func=cmd_next)

    # undo
    undo = sub.add_parser("undo", help="Undo last scan")
    undo.add_argument("--session", required=True)
    undo.set_defaults(func=cmd_undo)

    # results
    res = sub.add_parser("results", help="Show current results")
    res.add_argument("--session", required=True)
    res.add_argument("--limit", type=int, default=100)
    res.add_argument("--with-values", action="store_true",
                     help="Show current values at each address")
    res.set_defaults(func=cmd_results)

    # history
    hist = sub.add_parser("history", help="Show scan history")
    hist.add_argument("--session", required=True)
    hist.set_defaults(func=cmd_history)

    # save
    save = sub.add_parser("save", help="Save session to file")
    save.add_argument("--session", required=True)
    save.add_argument("--file", required=True)
    save.set_defaults(func=cmd_save)

    # load
    load = sub.add_parser("load", help="Load session from file")
    load.add_argument("--file", required=True)
    load.add_argument("--session", help="New session name (defaults to filename)")
    load.set_defaults(func=cmd_load)

    # freeze
    freeze = sub.add_parser("freeze", help="Freeze (lock) values at found addresses")
    freeze.add_argument("--session", required=True)
    freeze.add_argument("--value", help="Value to freeze to (default=current value)")
    freeze.add_argument("--addresses", nargs="+", help="Specific addresses to freeze")
    freeze.set_defaults(func=cmd_freeze)

    # sessions
    sess = sub.add_parser("sessions", help="List all saved sessions")
    sess.set_defaults(func=cmd_sessions)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
