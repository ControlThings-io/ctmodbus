"""
Control Things Modbus, aka ctmodbus.py

# Copyright (C) 2019  Justin Searle
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details at <http://www.gnu.org/licenses/>.
"""

import operator
import socket
from datetime import datetime

from ctui.dialogs import message_dialog
from psutil import Process, net_connections
from serial.tools.list_ports import comports
from tabulate import tabulate


class Loops(object):
    """Object that contains and calculates a list of range parameters"""

    from sys import maxsize

    def __init__(self, csr=None, minimum=-maxsize, maximum=maxsize):
        assert isinstance(csr, str) or csr == None, "csr must be a string"
        self.csr = csr or None
        self.loops = []
        self.length = 0
        self.enum_length = 0
        if csr:
            self._from_int_csr(csr, minimum, maximum)

    def __repr__(self):
        return repr(self.loops)

    def __len__(self):
        return self.length

    def __iter__(self):
        for loop in self.loops:
            yield loop

    def max_count(self, max_count):
        assert isinstance(max_count, int), "max_count must be int"
        for loop in self.loops:
            for i in range(0, loop["count"], max_count):
                start, stop, count = loop.values()
                yield {
                    "start": start + i,
                    "stop": min(start + max_count + i, stop),
                    "count": min(max_count, count - i),
                }

    def append(self, start, stop=None, count=None):
        """Append a new loop"""
        assert isinstance(start, int), "start must be an int"
        assert stop or count, "must set stop or count"
        if stop and not count:
            count = stop - start + 1
        elif count and not stop:
            stop = start + count - 1
        assert count == stop - start + 1, "count must equal stop - start + 1"
        self.loops.append({"start": start, "stop": stop, "count": count})
        self.length += 1
        self.enum_length += count

    def enum(self, func=None):
        """Use ranges to enumerate every increment"""
        for loop in self.loops:
            for x in range(loop["start"], loop["stop"]):
                if func:
                    yield func(x)
                else:
                    yield x

    def _from_int_csr(self, csr, minimum, maximum):
        """Converts comma separated int ranges to range() functions"""
        assert isinstance(csr, str), 'csr must be a string like "1-5,10,13-15"'
        assert isinstance(minimum, int), "minimum must be int"
        self.minimum = minimum
        assert isinstance(maximum, int), "maximum must be int"
        self.maximum = maximum
        parts = csr.split(",")
        for single_or_range in parts:
            if single_or_range.isdigit():
                single = int(single_or_range)
                assert (
                    minimum <= single <= maximum
                ), "{} is not between {} and {}".format(single, minimum, maximum)
                self.loops.append({"start": single, "stop": single + 1, "count": 1})
                self.length += 1
                self.enum_length += 1
            else:
                a_range = single_or_range.split("-")
                assert len(a_range) == 2, "{} is not a valid range".format(a_range)
                start, stop = a_range
                assert (
                    start.isdigit() and stop.isdigit()
                ), "{} and {} must be integers".format(start, stop)
                start, stop = int(start), int(stop)
                assert (
                    minimum <= start <= maximum
                ), "{} is not between {} and {}".format(start, minimum, maximum)
                assert minimum <= stop <= maximum, "{} is not between {} and {}".format(
                    stop, minimum, maximum
                )
                assert start < stop, "{} must be less than {}".format(start, stop)
                count = stop - start + 1
                self.loops.append({"start": start, "stop": stop + 1, "count": count})
                self.length += 1
                self.enum_length += count


def validate_ip_service(host, port, proto):
    """
    Verify port is open

    :PARAM: host: Any valid hostname or ipv4/6 ip address
    :PARAM: port: Any valid port name or number
    :PARAM: proto: Any valid socket.IPPROTO_*
    """
    l = socket.getaddrinfo(host, port, proto=proto)[0]
    af, socktype, proto, canonname, sa = l
    with socket.socket(af, socktype, proto) as s:
        assert s.connect_ex(sa) == 0, "Can not connect to {}:{}".format(host, port)


def validate_serial_device(device):
    """
    Verify requested serial device is connected to the system

    :PARAM: device: A device file path or comm port
    """
    devices = [x.device for x in comports()]
    assert device in devices, "{} is not in: \n{} ".format(
        device, list_serial_devices()
    )
    return device


def list_serial_devices():
    headers = ["DEVICE", "MANUFACTURER", "PRODUCT ID"]
    rows = []
    for dev in comports():
        columns = []
        columns.append(dev.device)
        columns.append(dev.manufacturer)
        columns.append(dev.product)
        rows.append(columns)
    table = sorted(rows, key=operator.itemgetter(0))
    return tabulate(table, headers=headers, tablefmt="fancy_grid")


def list_listening_ports():
    conns = net_connections()
    headers = ["IP", "PORT", "PROCESS"]
    rows = []
    for conn in conns:
        if conn[5] == "LISTEN":
            collumns = []
            collumns.append(conn[3][0])
            collumns.append(conn[3][1])
            if conn[6]:
                process = Process(conn[6])
                collumns.append(process.name())
            else:
                collumns.append("")
            rows.append(collumns)
    table = sorted(rows, key=operator.itemgetter(1))
    return tabulate(table, headers=headers, tablefmt="fancy_grid")


def parse_ip_port(ip_port):
    """
    Separate ip/host and port from unified address

    :PARAM: ip_port: Any address in ip or ip:port format
    """
    parts = ip_port.rsplit(":", 1)
    host = parts[0]
    port = 502
    if len(parts) == 2:
        port = int(parts[1])
    return host, port


def log_and_output_bits(desc, start, stop, results):
    """
    Log in project database and output to screen

    :PARAM:
    """
    date, time = str(datetime.today()).split()
    output_text = "{} {} - {} {}-{}: ".format(date, time, desc, start, stop - 1)
    i = 0
    for address in range(start, stop):
        # Print next bit
        output_text += str(results[address])
        # Print spaces ever 4 bits
        i += 1
        if i % 5 == 0:
            output_text += " "
    # TODO: Add to self.storage
    output_text += "\n"
    return output_text


def log_and_output_words(desc, start, stop, results):
    """
    Log in project database and output to screen

    :PARAM:
    """
    date, time = str(datetime.today()).split()
    output_text = "{} {} - {} {}-{}: ".format(date, time, desc, start, stop - 1)
    i = 0
    for address in range(start, stop):
        # Print spaces ever word
        output_text += "{:04x}".format(results[address]) + " "
        # Print extra spaces ever 5 words
        i += 1
        if i % 5 == 0:
            output_text += " "
    # TODO: Add to storage
    output_text += "\n"
    return output_text


def summarize_bit_responses(message, results):
    """
    Summarize bit responses in message dialog

    :PARAM:
    """
    la, lr, fa = None, None, None  # last_addres, last_result, first_address
    table = [["Addr", "Bit"]]
    for address, result in results.items():
        if address - 1 == la and result == lr:
            if fa == None:
                fa = la
        elif la != None:
            if fa == None:
                table.append([la, lr])
                fa = None
            else:
                s = "{0}-{1}".format(fa, la)
                table.append([s, lr])
                fa = None
        la, lr = address, result
    # Print final output from for loop
    if fa == None:
        table.append([la, lr])
    else:
        s = "{0}-{1}".format(fa, la)
        table.append([s, lr])
    message += tabulate(table, headers="firstrow", tablefmt="simple")
    message_dialog(title="Success", text=message)


def summarize_word_responses(message, results):
    """
    Summarize word reseponses in message dialog

    :PARAM:
    """
    la, lr, fa = None, None, None  # last_addres, last_result, first_address
    table = [["Addr", "Int", "HEX", "UTF-8"]]
    for address, result in results.items():
        if address - 1 == la and result == lr:
            if fa == None:
                fa = la
        elif la != None:
            if fa == None:
                table.append([la, lr, "{:04x}".format(lr), str(chr(lr))])
                fa = None
            else:
                s = "{0}-{1}".format(fa, la)
                table.append([s, lr, "{:04x}".format(lr), str(chr(lr))])
                fa = None
        la, lr = address, result
    # Print final output from for loop
    if fa == None:
        table.append([la, lr, "{:04x}".format(lr), str(chr(lr))])
    else:
        s = "{0}-{1}".format(fa, la)
        table.append([s, lr, "{:04x}".format(lr), str(chr(lr))])
    message += tabulate(table, headers="firstrow", tablefmt="simple")
    message_dialog(title="Success", text=message)


def csr_to_ranges(csr, max):
    """
    Generator to convert csr to ranges

    :PARAM: csr: Comma separated list of values or ranges
    :PARAM: max: Maximum number a range can have
    """
    loops = Loops(csr, minimum=0, maximum=65535)
    for loop in loops.max_count(max):
        yield loop.values()
