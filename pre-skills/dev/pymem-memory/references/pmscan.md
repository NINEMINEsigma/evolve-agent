# pmscan.py Reference

## Overview

Cheat Engine-style iterative memory scanner. Supports first scan, next scan,
undo, session persistence, and value freezing.

## Scan Types

### First Scan Types

| Type | Description | Required Args |
|------|-------------|---------------|
| `exact` | Exact value match | `--value` |
| `unknown` | All aligned addresses (snapshot everything) | None |
| `bigger_than` | Value > threshold | `--value` |
| `smaller_than` | Value < threshold | `--value` |
| `between` | Value in range | `--value` (lo), `--value2` (hi) |

### Next Scan Types

| Type | Description | Required Args |
|------|-------------|---------------|
| `exact` | Exact current value | `--value` |
| `bigger_than` | Current > threshold | `--value` |
| `smaller_than` | Current < threshold | `--value` |
| `between` | Current in range | `--value`, `--value2` |
| `changed` | Value changed since first scan | None |
| `unchanged` | Value same as first scan | None |
| `increased` | Value increased | None |
| `decreased` | Value decreased | None |
| `increased_by` | Increased by exact delta | `--value` (delta) |
| `decreased_by` | Decreased by exact delta | `--value` (delta) |
| `same_as_first` | Same as first scan value | None |

## Value Types

`int1`, `uint1`, `int2`, `uint2`, `int4`, `uint4`, `int8`, `uint8`, `float`, `double`

## Commands

### First Scan

```bash
python pmscan.py first --pid 1234 --type int4 --scan-type exact --value 100 --session s1
python pmscan.py first --name game.exe --type float --scan-type unknown --session s1
python pmscan.py first --pid 1234 --type int4 --scan-type bigger_than --value 50 --session s1
python pmscan.py first --pid 1234 --type int4 --scan-type between --value 10 --value2 99 --session s1
```

### Next Scan

```bash
python pmscan.py next --session s1 --scan-type decreased
python pmscan.py next --session s1 --scan-type exact --value 95
python pmscan.py next --session s1 --scan-type increased_by --value 5
python pmscan.py next --session s1 --scan-type unchanged
```

### Undo

```bash
python pmscan.py undo --session s1
```

### Results

```bash
python pmscan.py results --session s1 --limit 50 --with-values
```

### History

```bash
python pmscan.py history --session s1
```

### Save / Load

```bash
python pmscan.py save --session s1 --file myscan.json
python pmscan.py load --file myscan.json --session s2
```

### Freeze

```bash
# Freeze all current results at their current values
python pmscan.py freeze --session s1

# Freeze to specific value
python pmscan.py freeze --session s1 --value 9999

# Freeze specific address
python pmscan.py freeze --session s1 --address 0x7FF60000 --value 9999
```

### List Sessions

```bash
python pmscan.py sessions
```

## Session Files

Sessions auto-save to `~/.pmscan/<name>.json`. These contain:
- Process PID
- Value type
- All scan history with snapshots
- Current results

Sessions persist between runs, so you can resume scanning later.
