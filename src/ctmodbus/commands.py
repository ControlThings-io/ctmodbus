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

import socket

from ctui import Ctui
from ctui.dialogs import message_dialog
from ctui.types import GreedyBin, GreedyInt
from pkg_resources import get_distribution
from pymodbus.client.sync import ModbusSerialClient, ModbusTcpClient, ModbusUdpClient
from pymodbus.mei_message import ReadDeviceInformationRequest

from ctmodbus import common

ctmodbus = Ctui()
ctmodbus.name = "ctmodbus"
ctmodbus.version = get_distribution("ctmodbus").version
ctmodbus.description = (
    "a security professional's swiss army knife for interacting with Modbus devices"
)
ctmodbus.prompt = "ctmodbus> "

ctmodbus.session = None
unit_id = 1
statusbar = "Session:{}".format(ctmodbus.session)


@ctmodbus.command
def do_debug(cmd: str):
    """
    Run a python command for debugging

    :PARAM: cmd: Python command to run in debug session
    """
    message_dialog(title="Debug", text=str(eval(cmd)))


@ctmodbus.command
def do_connect():
    """Connect to modbus device/service or list suggestions"""
    output_text = "Connected Serial Devices\n"
    output_text += common.list_serial_devices()
    output_text += "\n\n\n"
    output_text += "Listening Services on Localhost\n"
    output_text += common.list_listening_ports()
    output_text += "                                                            \n"
    message_dialog(title="Suggestions", text=output_text)


@ctmodbus.command
def do_connect_ascii(device: str):
    """
    Connect to a Modbus ASCII serial device

    :PARAM: device: Serial device path or COM port
    """
    assert (
        ctmodbus.session == None
    ), "Session already open.  Close first."  # ToDo assert session type
    valid_device = common.validate_serial_device(device)
    ctmodbus.session = ModbusSerialClient(method="ascii", port=valid_device, timeout=1)
    message_dialog(title="Success", text="Session opened with {}".format(valid_device))


@ctmodbus.command
def do_connect_rtu(device: str):
    """
    Connect to a Modbus RTU serial device

    :PARAM: device: Serial device path or COM port
    """
    assert (
        ctmodbus.session == None
    ), "Session already open.  Close first."  # ToDo assert session type
    valid_device = common.validate_serial_device(device)
    ctmodbus.session = ModbusSerialClient(method="rtu", port=valid_device, timeout=1)
    message_dialog(title="Success", text="Session opened with {}".format(valid_device))


@ctmodbus.command
def do_connect_tcp(host_port: str):
    """
    Connect to a Modbus TCP device <IP/HOSTNAME>[:<PORT>]

    :PARAM: host_port: <IP/HOSTNAME>[:<PORT>]
    """
    assert (
        ctmodbus.session == None
    ), "Session already open.  Close first."  # ToDo assert session type
    host, port = common.parse_ip_port(host_port)
    common.validate_ip_service(host, port, socket.IPPROTO_TCP)
    ctmodbus.session = ModbusTcpClient(host, port, timeout=3)
    message_dialog(title="Success", text="Session opened with {}:{}".format(host, port))


@ctmodbus.command
def do_connect_udp(host_port: str):
    """
    Connect to a Modbus UDP device

    :PARAM: host_port: <IP/HOSTNAME>[:<PORT>]
    """
    assert (
        ctmodbus.session == None
    ), "Session already open.  Close first."  # ToDo assert session type
    host, port = common.parse_ip_port(host_port)
    common.validate_ip_service(host, port, socket.IPPROTO_UDP)
    ctmodbus.session = ModbusUdpClient(host, port, timeout=3)
    message_dialog(title="Success", text="Session opened with {}:{}".format(host, port))


@ctmodbus.command
def do_close():
    """
    Close the open session
    """
    assert (
        ctmodbus.session
    ), "There is not an open session.  Connect to one first."  # ToDo assert session type
    ctmodbus.session.close()
    message_dialog(
        title="Success", text="Session closed with {}".format(ctmodbus.session)
    )
    ctmodbus.session = None
    return None


@ctmodbus.command
def do_read():
    """Various modbus read fuctions..."""


@ctmodbus.command
def do_read_id():
    """
    Read device identification data
    """
    assert ctmodbus.session, "There is not an open session.  Connect to one first."
    request = ReadDeviceInformationRequest(unit=1)
    response = ctmodbus.session.execute(request)
    message_dialog(title="Response", text=str(response))
    return None


@ctmodbus.command
def do_read_discreteInputs(csr: str, max: int = 2000):
    """
    Read discrete inputs (on/off) in format: 30,50,70-99,105

    :PARAM: csr: Comma separated ranges to read
    :PARAM: max: Optional max addresses to read per request (default 2000)
    """
    assert ctmodbus.session, "There is not an open session.  Connect to one first."
    desc = "(2) Read DisIn"
    results = {}
    output_text = ctmodbus.output_text
    for start, stop, count in common.csr_to_ranges(csr, max):
        response = ctmodbus.session.read_discrete_inputs(start, count, unit=unit_id)
        assert hasattr(response, "bits"), "No response received"
        for address, result in zip(range(start, stop), response.bits):
            results[address] = int(result)
        output_text += common.log_and_output_bits(desc, start, stop, results)
    ranges = csr.split()[0]
    message = "{}: {}\n\n".format(desc, ranges)
    common.summarize_bit_responses(message, results)
    return output_text


@ctmodbus.command
def do_read_coils(csr: str, max: int = 2000):
    """
    Read coils (digital outputs and internal boolean tags) in format: 30,50,70-99,105

    :PARAM: csr: Comma separated ranges to read
    :PARAM: max: Optional max addresses to read per request (default 2000)
    """
    assert ctmodbus.session, "There is not an open session.  Connect to one first."
    desc = "(1) Read Coils"
    results = {}
    output_text = ctmodbus.output_text
    for start, stop, count in common.csr_to_ranges(csr, max):
        response = ctmodbus.session.read_coils(start, count, unit=unit_id)
        assert hasattr(response, "bits"), "No response received"
        for address, result in zip(range(start, stop), response.bits):
            results[address] = int(result)
        output_text += common.log_and_output_bits(desc, start, stop, results)
    ranges = csr.split()[0]
    message = "{}: {}\n\n".format(desc, ranges)
    common.summarize_bit_responses(message, results)
    return output_text


@ctmodbus.command
def do_read_inputRegisters(csr: str, max: int = 125):
    """
    Read input registers (analog inputs) in format: 30,50,70-99,105

    :PARAM: csr: Comma separated ranges to read
    :PARAM: max: Optional max addresses to read per request (default 125)
    """
    assert ctmodbus.session, "There is not an open session.  Connect to one first."
    desc = "(4) Read InReg"
    results = {}
    output_text = ctmodbus.output_text
    for start, stop, count in common.csr_to_ranges(csr, max):
        response = ctmodbus.session.read_input_registers(start, count, unit=unit_id)
        assert hasattr(response, "registers"), "No response received"
        for address, result in zip(range(start, stop), response.registers):
            results[address] = result
        output_text += common.log_and_output_words(desc, start, stop, results)
    ranges = csr.split()[0]
    message = "{}: {}\n\n".format(desc, ranges)
    common.summarize_word_responses(message, results)
    return output_text


@ctmodbus.command
def do_read_holdingRegisters(csr: str, max: int = 125):
    """
    Read holding registers (analog outputs and internal tags) in format: 30,50,70-99,105

    :PARAM: csr: Comma separated ranges to read
    :PARAM: max: Optional max addresses to read per request (default 125)
    """
    assert ctmodbus.session, "There is not an open session.  Connect to one first."
    desc = "(3) Read HoReg"
    results = {}
    output_text = ctmodbus.output_text
    for start, stop, count in common.csr_to_ranges(csr, max):
        response = ctmodbus.session.read_holding_registers(start, count, unit=unit_id)
        assert hasattr(response, "registers"), "No response received"
        for address, result in zip(range(start, stop), response.registers):
            results[address] = result
        output_text += common.log_and_output_words(desc, start, stop, results)
    ranges = csr.split()[0]
    message = "{}: {}\n\n".format(desc, ranges)
    common.summarize_word_responses(message, results)
    return output_text


@ctmodbus.command
def do_write():
    """Various modbus write commands..."""


@ctmodbus.command
def do_write_register(address: int, values: GreedyInt):
    """
    Write single register in format: <address> <int>

    :PARAM: address: Modbus address to start writes
    :PARAM: values: Space separated integers to write
    """
    assert ctmodbus.session, "There is not an open session.  Connect to one first."
    if len(values) == 1:
        ctmodbus.session.write_register(address, values[0], unit=unit_id)
        desc = "Modbus Function 6, Write Single Register"
    else:
        # This is currently not working, as GreedyInt doesn't pass on a list
        ctmodbus.session.write_registers(address, values, unit=unit_id)
        desc = "Modbus Function 16, Write Multiple Registers"
    message_dialog(title="Success", text=f"Wrote {values} starting at {address}")
    results = {}
    stop = address + len(values)
    for i in range(len(values)):
        results[address + i] = values[i]
    output_text = ctmodbus.output_text
    output_text += common.log_and_output_words(desc, address, stop, results)
    return output_text


@ctmodbus.command
def do_write_coil(address: int, values: GreedyBin):
    """
    Write single coil in format: <address> <0 or 1>

    :PARAM: address: Modbus address to start writes
    :PARAM: values: Space separated list of True or False to write
    """
    assert ctmodbus.session, "There is not an open session.  Connect to one first."
    if len(values) == 1:
        ctmodbus.session.write_coil(address, values[0], unit=unit_id)
        desc = "Modbus Function 5, Write Single Coil"
    else:
        # This is currently not working, as GreedyBin doesn't pass on a list
        ctmodbus.session.write_coils(address, values, unit=unit_id)
        desc = "Modbus Function 15, Write Multiple Coils"
    message_dialog(title="Success", text=f"Wrote {values} starting at {address}")
    results = {}
    stop = address + len(values)
    for i in range(len(values)):
        results[address + i] = int(values[i])
    output_text = ctmodbus.output_text
    output_text += common.log_and_output_bits(desc, address, stop, results)
    return output_text


def main():
    ctmodbus.run()


if __name__ == "__main__":
    main()
