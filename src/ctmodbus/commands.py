"""
Control Things Modbus, aka ctmodbus.py

# Copyright (C) 2017-2019  Justin Searle
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
from ctmodbus.common import Loops
from ctui.application import Ctui
from ctui.dialogs import message_dialog
from pymodbus.client.sync import ModbusTcpClient, ModbusUdpClient, ModbusSerialClient
from pymodbus.pdu import ModbusExceptions, ExceptionResponse, IllegalFunctionRequest
from pymodbus.mei_message import *     #ReadDeviceInformationRequest
from prompt_toolkit.document import Document
from tabulate import tabulate
from datetime import datetime
import serial.tools.list_ports
import shlex
import re

class CtModbus(Ctui):
    """Commands that users may use at the application prompt."""
    name = 'ctmodbus'
    version = '0.4'
    description = 'a security professional\'s swiss army knife for interacting with Modbus devices'
    prompt = 'ctmodbus> '
    session = None
    unit_id = 1
    statusbar = 'Session:{}'.format(session)


    def do_debug(self, args, output_text):
        message_dialog(
            title = 'Debug',
            text = str(eval(args)) )


    def validate_serial_device(self, device):
        devices = [x.device for x in serial.tools.list_ports.comports()]
        devices_pretty = '\n'.join([x for x in devices])
        assert (device in devices), '{} is not in: \n{}'.format(device, devices_pretty)
        return device


    def do_connect_ascii(self, args, output_text):
        """Connect to a Modbus ASCII serial device"""
        assert (self.session == None), 'Session already open.  Close first.'  # ToDo assert session type
        device = self.validate_serial_device(args)
        self.session = ModbusSerialClient(method='ascii', port=device, timeout=1)
        message_dialog(
            title = 'Success',
            text = 'Session opened with {}'.format(device) )


    def do_connect_rtu(self, args, output_text):
        """Connect to a Modbus RTU serial device"""
        assert (self.session == None), 'Session already open.  Close first.'  # ToDo assert session type
        device = self.validate_serial_device(args)
        self.session = ModbusSerialClient(method='rtu', port=device, timeout=1)
        message_dialog(
            title = 'Success',
            text = 'Session opened with {}'.format(device) )


    def parse_ip_port(self, ip_port):
        parts = ip_port.split(':')
        assert (0 < len(parts) < 3), 'Must be in format ip or host or ip:port or host:port'
        host = parts[0]
        port = 502
        if len(parts) == 2:
            port = int(parts[1])
        return host, port


    def do_connect_tcp(self, args, output_text):
        """Connect to a Modbus TCP device"""
        assert (self.session == None), 'Session already open.  Close first.'  # ToDo assert session type
        host, port = self.parse_ip_port(args)
        self.session = ModbusTcpClient(host, port)
        message_dialog(
            title = 'Success',
            text = 'Session opened with {}:{}'.format(host, port) )


    def do_connect_udp(self, args, output_text):
        """Connect to a Modbus UDP device"""
        assert (self.session == None), 'Session already open.  Close first.'  # ToDo assert session type
        host, port = self.parse_ip_port(args)
        self.session = ModbusUdpClient(host, port)
        message_dialog(
            title = 'Success',
            text = 'Session opened with {}:{}'.format(host, port) )


    def do_close(self, args, output_text):
        """Close a session."""
        assert (self.session), 'There is not an open session.  Connect to one first'  # ToDo assert session type
        self.session.close()
        message_dialog(
            title = 'Success',
            text = 'Session closed with {}'.format(self.session) )
        self.session = None
        return None


    def do_read_id(self, args, output_text):
        """Read device identification data."""
        assert (self.session), 'There is not an open session.  Connect to one first'  # ToDo assert session type
        request = ReadDeviceInformationRequest(unit=1)
        response = self.session.execute(request)
        output_text += str(response) + '\n'
        return output_text


    def log_and_output_bits(self, desc, start, stop, results):
        """Log in project database and output to screen"""
        date, time = str(datetime.today()).split()
        output_text = '{} {} - {}'.format(date, time, desc)
        i = 0
        for address in range(start, stop):
            # Finish line after 32 bits of output
            if i % 32 == 0: output_text += '\n{:>5}:  '.format(address)
            i += 1
            # Print next bit
            output_text += str(results[address])
            # Print spaces ever 4 bits
            if i % 4 == 0: output_text += ' '
        # TODO: Add to self.storage
        output_text += '\n'
        return output_text


    def log_and_output_words(self, desc, start, stop, results):
        """Log in project database and output to screen"""
        date, time = str(datetime.today()).split()
        output_text = '{} {} - {}'.format(date, time, desc)
        i = 0
        for address in range(start, stop):
            # Finish line after 8 words of output
            if i % 8 == 0: output_text += '\n{:>5}:  '.format(address)
            i += 1
            # Print next word
            output_text += '{:04x}'.format(results[address]) + ' '
        # TODO: Add to self.storage
        output_text += '\n'
        return output_text


    def response_message_dialog(self, message, results):
        la, lr, fa = None, None, None  #last_addres, last_result, first_address
        table = [['Addr', 'Int', 'HEX', 'ASCII']]
        for address, result in results.items():
            if address - 1 == la and result == lr:
                if fa == None:
                    fa = la
            elif la != None:
                if fa == None:
                    table.append([la, lr, '{:04x}'.format(lr), str(chr(lr))])
                    fa = None
                else:
                    s = '{0}-{1}'.format(fa, la)
                    table.append([s, lr, '{:04x}'.format(lr), str(chr(lr))])
                    fa = None
            la, lr = address, result
        # Print final output from for loop
        if fa == None:
            table.append([la, lr, '{:04x}'.format(lr), str(chr(lr))])
        else:
            s = '{0}-{1}'.format(fa, la)
            table.append([s, lr, '{:04x}'.format(lr), str(chr(lr))])
        message += tabulate(table, headers='firstrow', tablefmt='simple')
        message_dialog(title='Success', text=message)


    def read_common(self, args):
        assert (self.session), 'There is not an open session.  Connect to one first'  # TODO assert session type
        parts = args.split(maxsplit=1)
        csr = parts[0]

        max_count = 100
        if len(parts) == 2:
            assert (parts[1].isdigit()), 'max_count must be a digit'
            max_count = int(parts[1])

        loops = Loops(csr, minimum=0, maximum=65535)
        for loop in loops.max_count(max_count):
            yield loop.values()


    def do_read_discrete_inputs(self, args, output_text):
        """Read digital inputs in format: 30,50,70-99,105."""
        desc = 'Modbus Function 2, Read Discrete Inputs'
        results = {}
        for start, stop, count in self.read_common(args):
            response = self.session.read_discrete_inputs(start, count, unit=self.unit_id)
            for address, result in zip(range(start, stop), response.bits):
                results[address] = int(result)
            output_text += self.log_and_output_bits(desc, start, stop, results)
        csr = args.split()[0]
        message = '{}: {}\n\n'.format(desc, csr)
        self.response_message_dialog(message, results)
        return output_text


    def do_read_coils(self, args, output_text):
        """Read digital outputs in format: 30,50,70-99,105."""
        desc = 'Modbus Function 1, Read Coils'
        results = {}
        for start, stop, count in self.read_common(args):
            response = self.session.read_coils(start, count, unit=self.unit_id)
            for address, result in zip(range(start, stop), response.bits):
                results[address] = int(result)
            output_text += self.log_and_output_bits(desc, start, stop, results)
        csr = args.split()[0]
        message = '{}: {}\n\n'.format(desc, csr)
        self.response_message_dialog(message, results)
        return output_text


    def do_read_input_registers(self, args, output_text):
        """Read analog inputs or internal registers in format: 30,50,70-99,105."""
        desc = 'Modbus Function 4, Read Input Registers'
        results = {}
        for start, stop, count in self.read_common(args):
            response = self.session.read_input_registers(start, count, unit=self.unit_id)
            for address, result in zip(range(start, stop), response.registers):
                results[address] = result
            output_text += self.log_and_output_words(desc, start, stop, results)
        csr = args.split()[0]
        message = '{}: {}\n\n'.format(desc, csr)
        self.response_message_dialog(message, results)
        return output_text


    def do_read_holding_registers(self, args, output_text):
        """Read digital inputs in format: 30,50,70-99,105."""
        desc = 'Modbus Function 3, Read Holding Registers'
        results = {}
        for start, stop, count in self.read_common(args):
            response = self.session.read_holding_registers(start, count, unit=self.unit_id)
            for address, result in zip(range(start, stop), response.registers):
                results[address] = result
            output_text += self.log_and_output_words(desc, start, stop, results)
        csr = args.split()[0]
        message = '{}: {}\n\n'.format(desc, csr)
        self.response_message_dialog(message, results)
        return output_text


    def do_write_registers(self, args, output_text):
        """Write to registers in format: <address> <int>..."""
        start, values = args.split(maxsplit=1)
        assert (start.isdigit()), 'start must be an integer'
        int_start = int(start)
        try:
            list_int_values = [int(x) for x in values.split()]
        except:
            raise AssertionError('List of values to write must be decimals')
        if len(list_int_values) == 1:
            self.session.write_register(int_start, list_int_values[0], unit=self.unit_id)
            desc = 'Modbus Function 5, Write Single Register'
        else:
            self.session.write_registers(int_start, list_int_values, unit=self.unit_id)
            desc = 'Modbus Function 5, Write Multiple Registers'
        message_dialog(title='Success', text=f'Wrote {list_int_values} starting at {int_start}')
        results = {}
        stop = int_start + len(list_int_values)
        for i in range(len(list_int_values)):
            results[int_start + i] = list_int_values[i]
        output_text += self.log_and_output_words(desc, int_start, stop, results)
        return output_text


    def do_write_coils(self, args, output_text):
        """Write to registers in format: <address> <int>..."""
        desc = 'Modbus Function 3, Read Holding Registers'
        start, values = args.split(maxsplit=1)
        assert (start.isdigit()), 'start must be an integer'
        int_start = int(start)
        try:
            list_bool_values = [bool(int(x)) for x in values.replace(' ', '')]
        except:
            raise AssertionError('List of values to write must be decimals')
        if len(list_bool_values) == 1:
            self.session.write_coil(int_start, list_bool_values[0], unit=self.unit_id)
            desc = 'Modbus Function 5, Write Single Coil'
        else:
            self.session.write_coils(int_start, list_bool_values, unit=self.unit_id)
            desc = 'Modbus Function 15, Write Multiple Coils'
        message_dialog(title='Success', text=f'Wrote {list_bool_values} starting at {int_start}')
        results = {}
        stop = int_start + len(list_bool_values)
        for i in range(len(list_bool_values)):
            results[int_start + i] = int(list_bool_values[i])
        output_text += self.log_and_output_bits(desc, int_start, stop, results)
        return output_text


def main():
    ctmodbus = CtModbus()
    ctmodbus.run()

if __name__ == '__main__':
    main()
