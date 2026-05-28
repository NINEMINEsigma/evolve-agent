# pmfreeze.py Reference

## Overview

Lock (freeze) memory values so they cannot change. Cheat Engine equivalent
of ticking the "Active" checkbox on an address.

Runs at 100Hz, continuously overwriting the target memory.

## Commands

### Freeze Single Address

```bash
python pmfreeze.py --pid 1234 --address 0x7FF60000 --type int4 --value 9999
```

### Freeze Multiple Addresses

```bash
python pmfreeze.py --pid 1234 --type int4 --addresses 0x7FF60000 0x7FF60004 --value 9999
```

### Freeze Scan Results

```bash
python pmfreeze.py --pid 1234 --session myscan --type int4 --value 9999
python pmfreeze.py --pid 1234 --session myscan --type int4 --max 10
```

Without `--value`, freezes at current values.

### Daemon Mode (Background)

```bash
# Start in background
python pmfreeze.py --pid 1234 --address 0x7FF60000 --type int4 --value 9999 --daemon-id hpfreeze &

# Stop later
python pmfreeze.py stop --daemon-id hpfreeze
```

### List Running Daemons

```bash
python pmfreeze.py list
```

## Notes

- Press Ctrl+C to stop foreground freeze
- Daemon mode uses `.stop` files in `~/.pmfreeze/`
- `--max` limits how many addresses from a session to freeze
