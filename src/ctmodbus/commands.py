# Copyright (C) 2018  Justin Searle
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details at <http://www.gnu.org/licenses/>.

import shlex
import re
from pymodbus.client.sync import ModbusTcpClient, ModbusUdpClient, ModbusSerialClient
from pymodbus.mei_message import * #ReadDeviceInformationRequest
import time
from prompt_toolkit.application.current import get_app
from prompt_toolkit.document import Document
from tabulate import tabulate
from os.path import expanduser


class Commands(object):
    """Commands that users may use at the application prompt."""
    # Each function that users can call must:
    #     - start with a do_
    #     - accept self, input_text, output_text, and event as params
    #     - return a string to print, None, or False
    # Returning a False does nothing, forcing users to correct mistakes


    def execute(self, input_text, output_text, event):
        """Extract command and call appropriate function."""
        parts = input_text.strip().split(maxsplit=1)
        command = parts[0].lower()
        if len(parts) == 2:
            arg = parts[1]
        else:
            arg = ''
        try:
            func = getattr(self, 'do_' + command)
        except AttributeError:
            return False
        return func(arg, output_text, event)


    def commands(self):
        commands = [a[3:] for a in dir(self.__class__) if a.startswith('do_')]
        return commands


    def meta_dict(self):
        meta_dict = {}
        for command in self.commands():
            # TODO: find a better way to do this than eval
            meta_dict[command] = eval('self.do_' + command + '.__doc__')
        return meta_dict


    def do_clear(self, input_text, output_text, event):
        """Clear the screen."""
        return ''


    def do_connect(self, input_text, output_text, event):
        """Connect to tcp:10.10.10.1[:502] or rtu:/dev/serial or ascii:/dev/serial."""
        parts = input_text.split()
        if len(parts) == 1:
            target = dict()
            encoded_target = parts[0]
            if encoded_target.count(':') > 0:
                encoded_target = encoded_target.split(':')
                proto = encoded_target[0].lower()
                ip_dev = encoded_target[1]
                #TODO verify IP or DEV file and separate variables
                if len(encoded_target) == 3:
                    port = encoded_target[2]
                else:
                    port = 502
            if proto == 'tcp':
                event.app.session = ModbusTcpClient(ip_dev, port)
            elif proto == 'udp':
                event.app.session = ModbusUdpClient(ip_dev, port)
            elif proto == 'rtu':
                event.app.session = ModbusSerialClient(method='rtu', port=ip_dev, timeout=1)
            elif proto == 'ascii':
                event.app.session = ModbusSerialClient(method='ascii', port=ip_dev, timeout=1)
            # initiate a modbus session and return success message
            output_text += 'Connect session opened with {}\n'.format(parts[0])
            return output_text
        # Return False to force users to fix broken target
        return False


    def do_close(self, input_text, output_text, event):
        """Close a session."""
        if type(event.app.session) == str:
            output_text += 'Connect to a device first\n'
            return output_text
        event.app.session.close()
        output_text += 'Session closed.\n'
        event.app.session = ''
        return output_text


    def do_help(self, input_text, output_text, event):
        """Print application help."""
        output_text += '==================== Help ====================\n'
        output_text += 'Welcome to Control Things Modbus, or ctmodbus\n\n'
        output_text += 'This application allows you to interact directly with '
        output_text += 'Modbus devices.  You can do this by typing commands at '
        output_text += 'the prompt above, the output of which will appear in '
        output_text += 'this space.\n\n'
        table = []
        for key, value in self.meta_dict().items():
            table.append([key, value])
        output_text += tabulate(table, tablefmt="plain") + '\n'
        output_text += '==============================================\n'
        return output_text


    def do_history(self, input_text, output_text, event):
        """Print current history."""
        output_text += ''.join(event.app.history)
        return output_text


    def do_exit(self, input_text, output_text, event):
        """Exit the application."""
        #if type(event.app.session) == serial.Serial:
            # event.app.session.close()
        #event.app.session.close()
        event.app.exit()
        output_text += 'Closing application and all sessions.\n'
        return output_text


    # def _write(session, addr, typ, data):
    #     """Reads data from endpoint
    #     @param session: Handler for modbus connection
    #     @param args: Arguments pass via the commandline
    #     @return: List of address and read result pairs
    #     """
    #     #if DEBUG:
    #     #    print(addr, typ, data)
    #     int_words = []
    #     for item in data:
    #         #print("Evaluating: {}".format(item[:2]))
    #         if item.isdigit():
    #             int_words.append(int(item))
    #         elif item[:2].lower() == '0x' and (len(item) == 2 or len(item) == 4):
    #             #print('Found Hex')
    #             int_item = int.from_bytes(bytes.fromhex(item[2:]),'big')
    #             if 0 <= int_item <= 65535:
    #                 int_words.append(int_item)
    #             else:
    #                 print('Hex value {} not between 0x00 and 0xFFFF'.format(item))
    #                 return False
    #         elif item[:2].lower() == '0b':
    #             #print('Found Binary')
    #             int_item = int(item[2:], 2)
    #             if 0 <= int_item <= 65535:
    #                 int_words.append(int_item)
    #             else:
    #                 print('Binary value {} not between 0b0 and 0b1111111111111111 (sixteen 1s)'.format(item))
    #                 return False
    #         else:
    #             for char in item:
    #                 #print('Looks like a string')
    #                 int_words.append(ord(char))
    #     if any(s.startswith(typ) for s in ['bits', 'coils', 'inputs']):
    #         for bit in bin(data):
    #             print(bit)
    #             #session.write_coils(addr, True, unit=0x01)
    #         return 'Success'
    #     elif any(s.startswith(typ) for s in ['words', 'registers']):
    #         print('Start writing at register {}: {}'.format(addr, int_words))
    #         session.write_registers(addr, int_words, unit=0x01)
    #         print('Confirming write success with a read')
    #         read(session=session, ioh='output', typ=typ, addr=addr, num=len(int_words))
    #     else:
    #         print('Write coils/bits or registers/words?')
    #     return True


    def do_device_information(self, input_text, output_text, event):
        """Read device identification data."""
        if type(event.app.session) == str:
            output_text += 'Connect to a device first\n'
            return output_text
        request = ReadDeviceInformationRequest(unit=1)
        response = event.app.session.execute(request)
        output_text += str(response) + '\n'
        # information = {}
        # rr = None
        #
        # while not rr or rr.more_follows:
        #     next_object_id = rr.next_object_id if rr else 0
        #     rq = ReadDeviceInformationRequest(read_code=0x03, unit=1,
        #                                       object_id=next_object_id)
        #     rr = event.app.session.execute(rq)
        #     information.update(rr.information)
        #     log.debug(rr)
        #
        # for key in information.keys():
        #     output_text += key + information[key] + '\n'
        return output_text


    def _format_output(self, raw_bytes, output_format, prefix=''):
        """ Return hex and utf-8 decodes aligned on two lines """
        if len(raw_bytes) == 0:
            return prefix + 'None'
        table = []
        if output_format == 'hex' or output_format == 'mixed':
            hex_out = [prefix] + list(bytes([x]).hex() for x in raw_bytes)
            table.append(hex_out)
        if output_format == 'ascii' or output_format == 'mixed':
            ascii_out = [' ' * len(prefix)] + list(raw_bytes.decode('ascii', 'replace'))
            table.append(ascii_out)
        if output_format == 'utf-8':
            # TODO: track \xefbfdb and replace with actual sent character
            utf8 = raw_bytes.decode('utf-8', 'replace')
            utf8_hex_out = [prefix] + list(x.encode('utf-8').hex() for x in utf8)
            utf8_str_out = [' ' * len(prefix)] + list(utf8)
            table = [utf8_hex_out, utf8_str_out]
        return tabulate(table, tablefmt="plain", stralign='right')


    def do_read_discrete_inputs(self, input_text, output_text, event):
        """Read digital inputs in format: 30,50,70-99,105."""
        if type(event.app.session) == str:
            output_text += 'Connect to a device first\n'
            return output_text
        if len(input_text.split()) == 1:
            addr_globs = input_text.split(',')
            results = {}
            for glob in addr_globs:
                addr_glob = glob.split('-')
                if len(addr_glob) == 1:
                    try:
                        addr = int(addr_glob[0])
                        if addr > 65535:
                            return False
                        response = event.app.session.read_discrete_inputs(addr, 1, unit=1)
                        results[addr] = int(response.bits[0])
                    except:
                        output_text += str(response) + '\n'
                        return output_text
                elif len(addr_glob) == 2:
                    try:
                        addr1, addr2 = [int(x) for x in addr_glob]
                        if addr1 > 65535 or addr2 > 65535:
                            return False
                        addr2 += 1
                        count = addr2 - addr1
                        step = 1000
                        for i in range(0, count, step):
                            response = event.app.session.read_discrete_inputs(addr1+i, min(step, count-i), unit=1)
                            for address, result in zip(range(addr1+i, addr1+i+min(step, count-i)), response.bits):
                                results[address] = int(result)
                    except:
                        output_text += str(response) + '\n'
                        return output_text
            output_text += '### Reading Coils {} ###\n'.format(input_text)
            last_address, last_result, first_address = None, None, None
            for address, result in results.items():
                if address - 1 == last_address and result == last_result:
                    if first_address == None:
                        first_address = last_address
                elif last_address != None:
                    if first_address == None:
                        output_text += '{0} = {1}\n'.format(last_address, last_result)
                        first_address = None
                    else:
                        output_text += '{0}-{1} = {2}\n'.format(first_address, last_address, last_result)
                        first_address = None
                last_address, last_result = address, result
            # Print final output from for loop
            if first_address == None:
                output_text += '{0} = {1}\n'.format(last_address, last_result)
            else:
                output_text += '{0}-{1} = {2}\n'.format(first_address, last_address, last_result)
            return output_text
        # Force users to correct their mistakes
        return False


    def do_read_coils(self, input_text, output_text, event):
        """Read digital outputs in format: 30,50,70-99,105."""
        if type(event.app.session) == str:
            output_text += 'Connect to a device first\n'
            return output_text
        if len(input_text.split()) == 1:
            addr_globs = input_text.split(',')
            results = {}
            for glob in addr_globs:
                addr_glob = glob.split('-')
                if len(addr_glob) == 1:
                    try:
                        addr = int(addr_glob[0])
                        if addr > 65535:
                            return False
                        response = event.app.session.read_coils(addr, 1, unit=1)
                        results[addr] = int(response.bits[0])
                    except:
                        output_text += str(response) + '\n'
                        return output_text
                elif len(addr_glob) == 2:
                    try:
                        addr1, addr2 = [int(x) for x in addr_glob]
                        if addr1 > 65535 or addr2 > 65535:
                            return False
                        addr2 += 1
                        count = addr2 - addr1
                        step = 1000
                        for i in range(0, count, step):
                            response = event.app.session.read_coils(addr1+i, min(step, count-i), unit=1)
                            for address, result in zip(range(addr1+i, addr1+i+min(step, count-i)), response.bits):
                                results[address] = int(result)
                    except:
                        output_text += str(response) + '\n'
                        return output_text
            output_text += '### Reading Coils {} ###\n'.format(input_text)
            last_address, last_result, first_address = None, None, None
            for address, result in results.items():
                if address - 1 == last_address and result == last_result:
                    if first_address == None:
                        first_address = last_address
                elif last_address != None:
                    if first_address == None:
                        output_text += '{0} = {1}\n'.format(last_address, last_result)
                        first_address = None
                    else:
                        output_text += '{0}-{1} = {2}\n'.format(first_address, last_address, last_result)
                        first_address = None
                last_address, last_result = address, result
            # Print final output from for loop
            if first_address == None:
                output_text += '{0} = {1}\n'.format(last_address, last_result)
            else:
                output_text += '{0}-{1} = {2}\n'.format(first_address, last_address, last_result)
            return output_text
        # Force users to correct their mistakes
        return False


    def do_read_input_registers(self, input_text, output_text, event):
        """Read analog inputs or internal registers in format: 30,50,70-99,105."""
        if type(event.app.session) == str:
            output_text += 'Connect to a device first\n'
            return output_text
        if len(input_text.split()) == 1:
            addr_globs = input_text.split(',')
            results = {}
            for glob in addr_globs:
                addr_glob = glob.split('-')
                if len(addr_glob) == 1:
                    try:
                        addr = int(addr_glob[0])
                        if addr > 65535:
                            return False
                        response = event.app.session.read_input_registers(addr, 1, unit=1)
                        results[addr] = int(response.registers[0])
                    except:
                        output_text += str(response) + '\n'
                        return output_text
                elif len(addr_glob) == 2:
                    try:
                        addr1, addr2 = [int(x) for x in addr_glob]
                        if addr1 > 65535 or addr2 > 65535:
                            return False
                        addr2 += 1
                        count = addr2 - addr1
                        step = 100
                        for i in range(0, count, step):
                            response = event.app.session.read_input_registers(addr1+i, min(step, count-i), unit=1)
                            for address, result in zip(range(addr1+i, addr1+i+min(step, count-i)), response.registers):
                                results[address] = int(result)
                    except:
                        output_text += str(response) + '\n'
                        return output_text
            output_text += '### Reading Coils {} ###\n'.format(input_text)
            last_address, last_result, first_address = None, None, None
            for address, result in results.items():
                if address - 1 == last_address and result == last_result:
                    if first_address == None:
                        first_address = last_address
                elif last_address != None:
                    if first_address == None:
                        output_text += '{0} = {1}\n'.format(last_address, last_result)
                        first_address = None
                    else:
                        output_text += '{0}-{1} = {2}\n'.format(first_address, last_address, last_result)
                        first_address = None
                last_address, last_result = address, result
            # Print final output from for loop
            if first_address == None:
                output_text += '{0} = {1}\n'.format(last_address, last_result)
            else:
                output_text += '{0}-{1} = {2}\n'.format(first_address, last_address, last_result)
            return output_text
        # Force users to correct their mistakes
        return False


    def do_read_holding_registers(self, input_text, output_text, event):
        """Read digital inputs in format: 30,50,70-99,105."""
        if type(event.app.session) == str:
            output_text += 'Connect to a device first\n'
            return output_text
        if len(input_text.split()) == 1:
            addr_globs = input_text.split(',')
            results = {}
            for glob in addr_globs:
                addr_glob = glob.split('-')
                if len(addr_glob) == 1:
                    try:
                        addr = int(addr_glob[0])
                        if addr > 65535:
                            return False
                        response = event.app.session.read_holding_registers(addr, 1, unit=1)
                        results[addr] = int(response.registers[0])
                    except:
                        output_text += str(response) + '\n'
                        return output_text
                elif len(addr_glob) == 2:
                    try:
                        addr1, addr2 = [int(x) for x in addr_glob]
                        if addr1 > 65535 or addr2 > 65535:
                            return False
                        addr2 += 1
                        count = addr2 - addr1
                        step = 100
                        for i in range(0, count, step):
                            response = event.app.session.read_holding_registers(addr1+i, min(step, count-i), unit=1)
                            for address, result in zip(range(addr1+i, addr1+i+min(step, count-i)), response.registers):
                                results[address] = int(result)
                    except:
                        output_text += str(response) + '\n'
                        return output_text
            output_text += '### Reading Coils {} ###\n'.format(input_text)
            last_address, last_result, first_address = None, None, None
            for address, result in results.items():
                if address - 1 == last_address and result == last_result:
                    if first_address == None:
                        first_address = last_address
                elif last_address != None:
                    if first_address == None:
                        output_text += '{0} = {1}\n'.format(last_address, last_result)
                        first_address = None
                    else:
                        output_text += '{0}-{1} = {2}\n'.format(first_address, last_address, last_result)
                        first_address = None
                last_address, last_result = address, result
            # Print final output from for loop
            if first_address == None:
                output_text += '{0} = {1}\n'.format(last_address, last_result)
            else:
                output_text += '{0}-{1} = {2}\n'.format(first_address, last_address, last_result)
            return output_text
        # Force users to correct their mistakes
        return False
