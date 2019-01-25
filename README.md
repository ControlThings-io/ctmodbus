# Control Things Modbus

The goal of ctmodbus is to become the security professional's Swiss army knife
for interacting with Modbus devices.  Once completed, features will include
support for:

- RTU and ASCII versions of serial Modbus  (DONE)
- TCP and UDP versions of TCP/IP Modbus  (DONE)
- Client and server options  (DONE in lib, server IN PROGRESS)
- All standard Modbus functions  (reads DONE, writes IN PROGRESS)
- Arbitrary custom Modbus functions
- Reading addresses specified in lists and ranges (DONE)
- Interval based polling
- Clone feature to quickly create base data for simulator
- Proxy feature between two modbus endpoints
- Export to cthistorian and database

# Installation:

As long as you have git and Python 3.5 or later installed, all you should need to do is:

```
git clone https://github.com/ControlThingsTools/ctmodbus.git
cd ctmodbus
pip3 install -r requirements.txt
```

## Examples of current user interface commands once you start ctmodbus:

```
> connect tcp:10.10.10.1                # start a client session
> connect rtu:/dev/serial               # works with serial too
> connect ascii:com2                    # and and windows
> connect udp:10.10.10.1:10502          # even udp with custom ports
> read id                               # read device identifiers
> read discrete_inputs 1                # read coils and registers
> read coils 1,3,5,7                    # with comma separated values
> read input_register 5,10-30,90-99     # and ranges
> read holding_register 50 9            # or start address and count
> write coils 128 0                               # write single values
> write coils 76 01101001                         # or multiple values
> write holding_register 1000 "My name is Mud"    # registers support strings
> write holding_register 1400 DEADBEEF            # or raw hex
```

## Planned ui commands once complete:

```
> poll holding_register 1-10,15-19 1              # poll registers every second
> tags add input1 input_register 1                # define tag names
> tags add config2 holding_register 50-69         # tags can define ranges
> tags add config3 holding_register 70 20         # and work with start & count
> read tags input1 config2 config3                # tags simplify reads & writes
> tags group configs config1 config2 config3      # create tag groups
> tags export saved.tags                          # export and share tags
> tags import saved.tags                          # import other's tags
> clone tcp:10.10.10.10 coils 1-100               # clone coils from a device
> clone tcp:10.10.10.10 all 1-100                 # or all types of values
> simulate tcp:127.0.0.1:10502                    # so you can later simulate
> proxy tcp:10.10.10.1:10502 rtu:com4             # proxy requests to device
> function 33 0000 DEADBEEF                       # send custom functions
> function 8 [0000-FFFF] 0000                     # brackets for enumeration
> function 8 [0000-00FF] (0000)5                  # parenths for random fuzzing
> raw 1234 0001 06 01 0000 0010                   # or full raw modbus payloads
> tunnel listen tcp::6666                         # setup modbus tunnel service
> tunnel connect tcp:10.1.1.1:6666                # connect from another comp
> tunnel send exfiltration.txt                    # send files through tunnel
> tunnel terminal                                 # or open a terminal session
> historian tcp:10.1.1.1:9300                     # transactions to cthistorian
```

## This tool uses the excellent pymodbus library:

- https://github.com/bashwork/pymodbus



Copyright 2017-2018 Justin Searle

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program.  If not, see <http://www.gnu.org/licenses/>.
