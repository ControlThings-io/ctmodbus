# ControlThings Modbus

A highly flexible Modbus tool made for penetration testers.

# Installation:

As long as you have git and Python 3.8 or later installed, all you should need to do is:

```bash
pip3 install ctmodbus
```

Or better yet, if you have `uv` installed, install it in an isolated environment with:

```bash
uv tool install ctmodbus
```

`uv` also lets you try the tool out without installing it by running:

```bash
uvx ctmodbus
```

## Examples of current user interface commands once you start ctmodbus:

```bash
ctmodbus> connect tcp 10.10.10.1                          # start a client session
ctmodbus> connect rtu /dev/serial                         # works with serial too
ctmodbus> connect ascii COM2                              # and and windows
ctmodbus> connect udp 10.10.10.1:10502                    # even udp with custom ports
ctmodbus> read id                                         # read device identifiers
ctmodbus> read discrete_inputs 1                          # read coils and registers
ctmodbus> read coils 1,3,5,7                              # with comma separated values
ctmodbus> read input_register 5,10-30,90-99               # and ranges
ctmodbus> read holding_register 50 9                      # or start address and count
ctmodbus> write coils 128 0                               # write single values
```

## Planned UI commands once complete:

```bash
ctmodbus> write coils 76 01101001                         # or multiple values
ctmodbus> write holding_register 1000 14302 188 305       # registers support int
ctmodbus> write holding_register 1000 "My name is Mud"    # and strings
ctmodbus> write holding_register 1400 DEADBEEF            # or raw hex
ctmodbus> poll holding_register 1-10,15-19 1              # poll registers every second
ctmodbus> tags add input1 input_register 1                # define tag names
ctmodbus> tags add config2 holding_register 50-69         # tags can define ranges
ctmodbus> tags add config3 holding_register 70 20         # and work with start & count
ctmodbus> read tags input1 config2 config3                # tags simplify reads & writes
ctmodbus> tags group configs config1 config2 config3      # create tag groups
ctmodbus> tags export saved.tags                          # export and share tags
ctmodbus> tags import saved.tags                          # import other's tags
ctmodbus> clone tcp:10.10.10.10 coils 1-100               # clone coils from a device
ctmodbus> clone tcp:10.10.10.10 all 1-100                 # or all types of values
ctmodbus> simulate tcp:127.0.0.1:10502                    # so you can later simulate
ctmodbus> proxy tcp:10.10.10.1:10502 rtu:com4             # proxy requests to device
ctmodbus> function 33 0000 DEADBEEF                       # send custom functions
ctmodbus> function 8 [0000-FFFF] 0000                     # brackets for enumeration
ctmodbus> function 8 [0000-00FF] (0000)5                  # parenths for random fuzzing
ctmodbus> raw 1234 0001 06 01 0000 0010                   # or full raw modbus payloads
ctmodbus> tunnel listen tcp::6666                         # setup modbus tunnel service
ctmodbus> tunnel connect tcp:10.1.1.1:6666                # connect from another comp
ctmodbus> tunnel send exfiltration.txt                    # send files through tunnel
ctmodbus> tunnel shell                                    # or open a terminal session
ctmodbus> historian tcp:10.1.1.1:9300                     # transactions to cthistorian
```

## This tool is built upon these to key library:

- [Control Things User Interface](https://github.com/ControlThingsTools/ctui)
- [PyModbus](https://github.com/bashwork/pymodbus)


## Copyright 2025 Justin Searle

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program.  If not, see <http://www.gnu.org/licenses/>.
