# pmcli.py Reference

## Overview

Core memory operations: process listing, typed read/write, pattern/value scan,
module info, memory protection, allocation, and dumping.

## Commands

### Process Operations

```bash
python pmcli.py process list
python pmcli.py process find --name game.exe
python pmcli.py process info --name game.exe
```

### Read Memory

```bash
python pmcli.py read int4  --pid 1234 --address 0x7FF60000
python pmcli.py read float --pid 1234 --address 0x7FF60004
python pmcli.py read int8  --pid 1234 --address 0x7FF60000
python pmcli.py read bytes --pid 1234 --address 0x7FF60000 --size 32
python pmcli.py read string --pid 1234 --address 0x7FF60000 --size 64
```

### Write Memory

```bash
python pmcli.py write int4   --pid 1234 --address 0x7FF60000 --data 9999
python pmcli.py write float  --pid 1234 --address 0x7FF60004 --data 99.9
python pmcli.py write double --pid 1234 --address 0x7FF60008 --data 123.456
python pmcli.py write bytes  --pid 1234 --address 0x7FF60000 --data "90 90 90 CC"
python pmcli.py write string --pid 1234 --address 0x7FF60000 --data "hello"
```

### Scan Memory

```bash
# Byte pattern with wildcards
python pmcli.py scan pattern --pid 1234 --pattern "48 8B 05 ?? ?? ?? ??"
python pmcli.py scan pattern --pid 1234 --pattern "89 87 ?? ?? 00 00"

# Typed value
python pmcli.py scan value --pid 1234 --value 100 --type int4
python pmcli.py scan value --pid 1234 --value 3.14 --type float
```

### Module Operations

```bash
python pmcli.py module list --pid 1234
python pmcli.py module base --pid 1234 --module game.exe
```

### Memory Protection

```bash
python pmcli.py protect --pid 1234 --address 0x7FF60000 --size 4096 --flag rwx
python pmcli.py protect --pid 1234 --address 0x7FF60000 --size 4096 --flag rw
```

Flags: `r`, `rw`, `rx`, `rwx`, `noaccess`

### Allocate Memory

```bash
python pmcli.py allocate --pid 1234 --size 4096
```

### Dump Memory

```bash
python pmcli.py dump --pid 1234 --address 0x7FF60000 --size 4096 --output dump.bin
python pmcli.py dump --pid 1234 --address 0x7FF60000 --size 256  # prints hex
```

### List Memory Regions

```bash
python pmcli.py regions --pid 1234
python pmcli.py regions --pid 1234 --limit 100
```

## Value Types

`int1`, `uint1`, `int2`, `uint2`, `int4`, `uint4`, `int8`, `uint8`, `float`, `double`
