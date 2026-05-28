# pmpointer.py Reference

## Overview

Pointer chain scanner. Finds static pointer paths to dynamic addresses.
Critical for game hacking because game addresses change every restart.

## How Pointer Scanning Works

1. You find a dynamic address via value scanning (e.g., `0x1A3B4C5D6`)
2. Pointer scanner searches memory for all pointers that point near this address
3. Recursively searches for pointers to those pointers
4. Stops when it finds a static base (module address)
5. Result: `game.exe+0x123456 -> +0x80 -> +0x10 -> +0x28` = target

## Commands

### Scan for Pointer Chains

```bash
python pmpointer.py scan --pid 1234 --target 0x1A3B4C5D6 --max-level 5
python pmpointer.py scan --name game.exe --target 0x1A3B4C5D6 --max-level 7 --max-offset 0x2000
```

Options:
- `--target`: The dynamic address to find pointers to
- `--max-level`: Max pointer depth (default 5)
- `--max-offset`: Max offset from pointer value (default 0x1000)
- `--threads`: Scanner threads (default 4)
- `--max-results`: Max chains to return
- `--stop-on-static`: Stop when static pointers are found
- `--output`: Save results to JSON file

### Verify a Chain

```bash
python pmpointer.py verify --pid 1234 --chain 'game.exe+123456,80,10,28' --expected 0x1A3B4C5D6
```

### Resolve Chain to Address

```bash
python pmpointer.py resolve --pid 1234 --chain 'game.exe+123456,80,10,28' --type int4
```

### Re-scan Chains After Restart

```bash
python pmpointer.py rescan --pid 1234 --chains-file chains.json --target-value 9999 --type int4
```

This re-validates saved chains in a new game session.

## Chain String Format

```
module_name+base_offset,offset1,offset2,...
```

Examples:
- `game.exe+123456,80,10,28`
- `UnityPlayer.dll+A1B2C0,0,20,8`
- `0x7FF6123456` (absolute, no module)

## Output Format

```json
{
  "target": "0x1A3B4C5D6",
  "chains_found": 12,
  "chains": [
    {
      "chain": "game.exe+123456 -> +0x80 -> +0x10 -> +0x28",
      "base_module": "game.exe",
      "base_offset": 1193046,
      "offsets": [128, 16, 40],
      "level": 3,
      "resolved": "0x1A3B4C5D6",
      "valid": true
    }
  ]
}
```
