Control Things Modbus
=====================

This is a commandline tool for interacting with the Modbus protocol.  Once completed, features will include support for:

 - RTU and ASCII versions of serial Modbus  (DONE in lib)
 - TCP and UDP versions of TCP/IP Modbus  (DONE in lib)
 - Client and server options  (DONE in lib)
 - All standard Modbus functions  (Reads DONE, writes IN PROGRESS)
 - Arbitrary custom Modbus functions
 - Reading addresses specified in lists and ranges
 - Interval based polling
 - Sync files with complex interval polls
 - Clone feature to quickly create base data for server
 - Proxy feature between two modbus endpoints
 - Export to cthistorian and database

Examples of current commandline usage:

     $ ctmodbus tcp:10.10.10.10 read input register 0
     $ ctmodbus tcp:10.10.10.10 read holding register 0 65535
     $ ctmodbus rtu:/dev/ttyUSB0 read output coil 33

Planned commandline usage once complete:

     $ ctmodbus tcp:10.10.10.10 tags ~/tags.txt
     $ ctmodbus clone tcp:10.10.10.10 -f ~/server.conf
     $ ctmodbus server tcp:127.0.0.1:8503 -f ~/server.conf
     $ ctmodbus sync -f ~/sync.conf
     $ ctmodbus proxy tcp:10.10.10.1:10502 rtu:/dev/ttyUSB0

Planned interactive usage once complete:

    $ ctmodbus
    > connect /dev/ttyUSB0
    > read id
    > read input coil 1
    > read holding coil 1,3,5,7
    > read input register 5,10,100-200
    > read holding register 1000-1200,1400-1450 -i 15
    > write coil 128 00110101
    > write register 1000 "My name is Mud"
    > write register 1400 0xDEAD 0xBEEF
    > function 16 1400 0xDEAD 0xBEEF
    > dump
    > export dump ~/recording.dump
    > export historian 127.0.0.1:9300
    > server 127.0.0.1:8503
    > status
    > export sync ~/sync.conf
    > exit


This is based on the excellent pymodbus library:

    https://github.com/bashwork/pymodbus

And includes asyncio additions by:

    https://github.com/moltob/pymodbus



Copyright 2017 Justin Searle

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program.  If not, see <http://www.gnu.org/licenses/>.
