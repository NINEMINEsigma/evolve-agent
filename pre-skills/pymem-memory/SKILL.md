---
name: pymem-memory
description: Windows game memory editing and process manipulation using pymem. Cheat Engine-style iterative memory scanning (exact/unknown/changed/unchanged/increased/decreased), value freezing (locking), pointer chain scanning, pattern matching, typed memory read/write, DLL injection, and batch operations. Use when the task involves game hacking, memory editing, finding game values (health, ammo, money, scores), freezing values, finding pointer chains for dynamic addresses, or any Windows process memory manipulation.
compatibility: Windows only. Requires pymem (`pip install pymem`) and administrator privileges.
---

# pymem-memory

Windows game memory editing toolkit. Cheat Engine-style workflow with
iterative scanning, value freezing, and pointer chain resolution.

## Scripts

All scripts output JSON to stdout. All support `--pid` or `--name` for
targeting.

### pmscan.py - Iterative Memory Scanner (primary tool)

Cheat Engine-style first scan / next scan workflow.

**First scan types**: `exact`, `unknown`, `bigger_than`, `smaller_than`, `between`
**Next scan types**: `exact`, `changed`, `unchanged`, `increased`, `decreased`,
`increased_by`, `decreased_by`, `bigger_than`, `smaller_than`, `between`, `same_as_first`
**Value types**: `int1/2/4/8`, `uint1/2/4/8`, `float`, `double`

```bash
# 1. First scan - exact value
python scripts/pmscan.py first --name game.exe --type int4 --scan-type exact --value 100 --session hp

# 1b. Or unknown initial value (when you don't know the value)
python scripts/pmscan.py first --name game.exe --type int4 --scan-type unknown --session hp

# 2. Change the value in-game, then next scan
python scripts/pmscan.py next --session hp --scan-type decreased

# 2b. Or exact next scan
python scripts/pmscan.py next --session hp --scan-type exact --value 95

# 3. Repeat next scans until few results remain
# 4. Undo a wrong scan
python scripts/pmscan.py undo --session hp

# 5. View results with current values
python scripts/pmscan.py results --session hp --with-values --limit 20

# 6. Freeze the value (locks it)
python scripts/pmscan.py freeze --session hp --value 9999
```

Sessions auto-save to `~/.pmscan/` and persist between runs.
See `references/pmscan.md` for full details.

### pmfreeze.py - Value Freezer

Lock memory values (CE "Active" checkbox). Runs at 100Hz.

```bash
# Freeze single address
python scripts/pmfreeze.py --name game.exe --address 0x7FF60000 --type int4 --value 9999

# Freeze scan session results
python scripts/pmfreeze.py --name game.exe --session hp --type int4 --value 9999

# Daemon mode (background)
python scripts/pmfreeze.py --name game.exe --address 0x7FF60000 --type int4 --value 9999 --daemon-id hp &
python scripts/pmfreeze.py stop --daemon-id hp
```

See `references/pmfreeze.md`.

### pmpointer.py - Pointer Chain Scanner

Find static pointer paths to dynamic addresses. Use after game restart
when addresses change.

```bash
# Scan for pointer chains to a target address
python scripts/pmpointer.py scan --name game.exe --target 0x1A3B4C5D6 --max-level 5

# Verify a chain
python scripts/pmpointer.py verify --name game.exe --chain 'game.exe+123456,80,10,28'

# Resolve chain and read value
python scripts/pmpointer.py resolve --name game.exe --chain 'game.exe+123456,80,10,28' --type int4

# Re-scan saved chains after game restart
python scripts/pmpointer.py rescan --name game.exe --chains-file chains.json --target-value 9999 --type int4
```

See `references/pmpointer.md`.

### pmcli.py - Core Memory Operations

Lower-level memory read/write/scan when pmscan workflow is not needed.

```bash
# Process info
python scripts/pmcli.py process list
python scripts/pmcli.py process find --name game.exe

# Typed read/write
python scripts/pmcli.py read int4 --name game.exe --address 0x7FF60000
python scripts/pmcli.py write int4 --name game.exe --address 0x7FF60000 --data 9999

# Byte pattern scan (AOB)
python scripts/pmcli.py scan pattern --name game.exe --pattern "48 8B 05 ?? ?? ?? ??"

# Typed value scan (non-iterative)
python scripts/pmcli.py scan value --name game.exe --value 100 --type int4

# Module base address
python scripts/pmcli.py module base --name game.exe --module game.exe

# Memory protection, allocation, dump
python scripts/pmcli.py protect --name game.exe --address 0x7FF60000 --size 4096 --flag rwx
python scripts/pmcli.py allocate --name game.exe --size 4096
python scripts/pmcli.py dump --name game.exe --address 0x7FF60000 --size 4096 --output dump.bin
```

See `references/pmcli.md`.

### pmwatch.py - Memory Change Monitor

Poll addresses and emit JSON on changes.

```bash
python scripts/pmwatch.py --name game.exe --address 0x7FF60000 --type int4 --interval 0.5
python scripts/pmwatch.py --name game.exe --session hp --type int4
```

### pmbatch.py - Batch Read/Write

Multiple operations in one call via JSON spec.

```bash
python scripts/pmbatch.py read --name game.exe --spec '[
  {"address": "0x7FF60000", "type": "int4", "label": "health"},
  {"address": "0x7FF60004", "type": "float", "label": "speed"}
]'

python scripts/pmbatch.py write --name game.exe --spec '[
  {"address": "0x7FF60000", "type": "int4", "value": 9999, "label": "health"},
  {"address": "0x7FF60004", "type": "float", "value": 99.9, "label": "speed"}
]'
```

### pmload.py - DLL Injection

```bash
python scripts/pmload.py inject --name game.exe --dll C:\path\to\mylib.dll
python scripts/pmload.py eject --name game.exe --dll mylib.dll
```

## Game Hacking Workflow

**Finding a value (e.g., health):**

1. Find process: `pmcli.py process find --name <game>`
2. First scan: `pmscan.py first --name <game> --type int4 --scan-type exact --value <current> --session hp`
3. Change value in-game
4. Next scan: `pmscan.py next --session hp --scan-type <changed/decreased/exact>`
5. Repeat steps 3-4 until 1-5 addresses remain
6. Verify: `pmscan.py results --session hp --with-values`
7. Freeze: `pmscan.py freeze --session hp --value 9999` (or use pmfreeze.py)

**For dynamic addresses (changes on restart):**

8. Note the dynamic address from results
9. Pointer scan: `pmpointer.py scan --name <game> --target <addr> --max-level 5`
10. Save chains: chains are in the scan output
11. After restart: `pmpointer.py rescan --name <game> --chains-file chains.json`

**For encrypted values:**

- Use `--scan-type unknown` for first scan
- Use `changed` / `unchanged` next scans (not increased/decreased)
- The real value may never be in memory; try finding what accesses the address

## Important Notes

- Windows only. All scripts require `pip install pymem`.
- Run as administrator for most games.
- `--name` uses process executable name; `--pid` uses process ID.
- Addresses accept `0x` prefix.
- Byte patterns use `??` for wildcards: `"48 8B 05 ?? ?? ?? ??"`
- JSON output: parse stdout with `json.loads()`.
