#!/usr/bin/env python3
"""ControlThings Modbus, aka ctmodbus

Usage:
  ctmodbus [options] connect TARGET
  ctmodbus [options] read TARGET IOH TYPE ADDRESS [COUNT]
  ctmodbus [options] write TARGET TYPE ADDRESS DATA...
  ctmodbus (-h | --help)

Arguments:
  connect       Connect to TARGET and open modbus prompt for multiple commands
  read | write  Send single read or write command
  TARGET        IP or serial device in form (PROTO:IP-or-DevPath:OptPORT) such as:
                    ascii:/dev/serial
                    rtu:/dev/serial
                    tcp:10.10.10.1 or tcp:127.0.0.1:10502
                    udp:10.10.10.1 or udp:127.0.0.1:10502
  IOH           Must be "input", "output", or "holding"
  TYPE          Must be "bits", "coils", "words", "registers"
  ADDRESS       Modbus reference address to read/write (0-65535)
  COUNT         Number of Modbus addresses to read from ADDRESS (1-65536)
  DATA          uft16, integer, 0xBEEF, or 0b1111111100000000
  FILE          File with simulator settings

Options:
  -v            Enable verbose output
  -d            Enable debug outpu
  -h --help     Show this screen.
  --version     Show version.
"""

""" Future functionality to impliment
Usage:
  ctmodbus [options] connect TARGET ### FUTURE
  ctmodbus [options] func TARGET FUNCTION FUNC_DATA  ### FUTURE
  ctmodbus [options] simulate [TARGET | FILE]   ### FUTURE
Arguments:
  FUNCTION      Modbus fucntion code (0-127) representing
  FUNC_DATA     Data passed to fucntion code
"""

from docopt import docopt
import sys
import logging
from binascii import *
from pymodbus.client.sync import *
#from pymodbus.server.asyncio import *
#from pymodbus.device import ModbusDeviceIdentification
#from pymodbus.datastore import ModbusSequentialDataBlock
#from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
#from pymodbus.transaction import ModbusRtuFramer, ModbusAsciiFramer
import importlib
from prompt_toolkit.shortcuts import prompt
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.contrib.completers import WordCompleter
try:
    import better_exceptions
except ImportError as err:
    pass

sys.dont_write_bytecode = True
req_version = (3,5)
cur_version = sys.version_info
if cur_version <= req_version:
   import __future__


def parse_addr(rng):
    parts = rng.split('-')
    if 1 > len(parts) > 2:
        raise ValueError("Bad range: '%s'" % (rng,))
    parts = [int(i) for i in parts]
    start = parts[0]
    end = start if len(parts) == 1 else parts[1]
    if start > end:
        end, start = start, end
    return range(start, end + 1)


def parse_target(encoded_target):
    """Decode target for communications
    @param encoded_target: encoded target from user command prompt arguments
    @return: returns an dictionary of parsed target variables
    """
    target = dict()
    if encoded_target.count(':') > 0:
        encoded_target = encoded_target.split(':')
        target['proto'] = encoded_target[0].lower()
        target['ip_dev'] = encoded_target[1]
        #TODO verify IP or DEV file and separate variables
        if len(encoded_target) == 3:
            target['port'] = encoded_target[2]
        else:
            target['port'] = 502
    else:
        print('No TARGET specifed. Please see help page')
        sys.exit()
    return target


def connect(target):
    """Initiate connection to endpoint
    @param target: dictionary of proto, ip_dev, and maybe port
    @return: returns the correct connection object
    """

    if target['proto'] == 'tcp':
        client = ModbusTcpClient(target['ip_dev'], target['port'])
    elif target['proto'] == 'udp':
        client = ModbusUdpClient(target['ip_dev'], target['port'])
    elif target['proto'] == 'rtu':
        client = ModbusSerialClient(method='rtu', port=target['ip_dev'], timeout=1)
    elif target['proto'] == 'ascii':
        client = ModbusSerialClient(method='ascii', port=target['ip_dev'], timeout=1)
    else:
        print('Protocol must be TCP, UDP, RTU, or ASCII')
        sys.exit()
    return client


def read(client, addr, ioh, typ, num):
    """Reads data from endpoint
    @param client: Handler for modbus connection
    @param args: Arguments pass via the commandline
    @return: List of address and read result pairs
    """
    #if DEBUG:
    #    print(addr, ioh, typ, num)
    resultsd = {}
    if any(s.startswith(typ) for s in ['bits', 'coils', 'inputs']):
        if any(s.startswith(ioh) for s in ['input', 'descrete']):
            for i in range(0, num, 1000):
                results = client.read_discrete_inputs(addr+i, min(1000, num-i), unit=1).bits
                for address, result in zip(range(addr+i, addr + i + min(1000, num-i)), results):
                    resultsd[address] = result
            for address, result in resultsd.items():
                print('{0:12} = {1:<5}  {2}'.format(address, result, bool(result)))
        elif any(s.startswith(ioh) for s in ['output', 'holding']):
            for i in range(0, num, 1000):
                results = client.read_coils(addr+i, min(1000, num-i), unit=1).bits
                for address, result in zip(range(addr+i, addr + i + min(1000, num-i)), results):
                    resultsd[address] = result
            for address, result in resultsd.items():
                print('{0:12} = {1:<5}  {2}'.format(address, result, bool(result)))
        else:
            print('Did you mean input coils/bits or output coils/bits?')
            sys.exit()
    elif any(s.startswith(typ) for s in ['words', 'registers']):
        if any(s.startswith(ioh) for s in ['input']):
            for i in range(0, num, 100):
                results = client.read_input_registers(addr+i, min(100, num-i), unit=1).registers
                for address, result in zip(range(addr+i, addr + i + min(100, num-i)), results):
                    resultsd[address] = result
            for address, result in resultsd.items():
                print('{0:12} = {1:<5}  0x{1:0>4x}  0b{1:0>16b}  {1:c}'.format(address, result))
        elif any(s.startswith(ioh) for s in ['output', 'holding']):
            for i in range(0, num, 100):
                results = client.read_holding_registers(addr+i, min(100, num-i), unit=1).registers
                for address, result in zip(range(addr+i, addr + i + min(100, num-i)), results):
                    resultsd[address] = result
            for address, result in resultsd.items():
                print('{0:12} = {1:<5}  0x{1:0>4x}  0b{1:0>16b}  {1:c}'.format(address, result))
        else:
            print('Did you mean input words/registers or output/holding words/registers?')
            sys.exit()
    else:
        print('Connected, but I dont understand what you want me to read')
        print('Try something like "read holding register 0"')
        sys.exit()
    #print(results.__dict__)
    # for address, result in zip(range(addr, addr+num), results):
    #     resultsd[address] = [result.to_bytes(2, 'big')]
    return resultsd


def write(client, addr, typ, data):
    """Reads data from endpoint
    @param client: Handler for modbus connection
    @param args: Arguments pass via the commandline
    @return: List of address and read result pairs
    """
    #if DEBUG:
    #    print(addr, typ, data)
    int_words = []
    for item in data:
        #print("Evaluating: {}".format(item[:2]))
        if item.isdigit():
            int_words.append(int(item))
        elif item[:2].lower() == '0x' and (len(item) == 2 or len(item) == 4):
            #print('Found Hex')
            int_item = int.from_bytes(bytes.fromhex(item[2:]),'big')
            if 0 <= int_item <= 65535:
                int_words.append(int_item)
            else:
                print('Hex value {} not between 0x00 and 0xFFFF'.format(item))
                return False
        elif item[:2].lower() == '0b':
            #print('Found Binary')
            int_item = int(item[2:], 2)
            if 0 <= int_item <= 65535:
                int_words.append(int_item)
            else:
                print('Binary value {} not between 0b0 and 0b1111111111111111 (sixteen 1s)'.format(item))
                return False
        else:
            for char in item:
                #print('Looks like a string')
                int_words.append(ord(char))
    if any(s.startswith(typ) for s in ['bits', 'coils', 'inputs']):
        for bit in bin(data):
            print(bit)
            #client.write_coils(addr, True, unit=0x01)
        return 'Success'
    elif any(s.startswith(typ) for s in ['words', 'registers']):
        print('Start writing at register {}: {}'.format(addr, int_words))
        client.write_registers(addr, int_words, unit=0x01)
        print('Confirming write success with a read')
        read(client=client, ioh='output', typ=typ, addr=addr, num=len(int_words))
    else:
        print('Write coils/bits or registers/words?')
    return True


#def simulate(args):


def no_prompt(client, args):
    addr = int(args['ADDRESS'])
    ioh = str(args['IOH']).lower()
    typ = str(args['TYPE']).lower()
    data = args['DATA']
    num = int(args['COUNT'])
    if args['read']:
        read(client=client, addr=addr, ioh=ioh, typ=typ, num=num)
    elif args['write']:
        write(client=client, addr=addr, typ=typ, data=data)
    else:
        print('those commands are not implimented yet')
    client.close()


def modbus_prompt(client, args):
   history = InMemoryHistory()
   completer = WordCompleter(['read', 'write', 'id', 'diag'], ignore_case=True)
   while True:
       text = prompt('modbus> ', completer=completer, history=history)
       command = text.lower().split()
       if command[0] == 'read' and 4 <= len(command) <= 5:
           ioh = str(command[1]).lower()
           typ = str(command[2]).lower()
           addr = int(command[3])
           if len(command) == 4:
               num = 1
           else:
               num = int(command[4])
           read(client=client, addr=addr, ioh=ioh, typ=typ, num=num)
       elif command[0] == 'write' and len(command) >= 4:
           typ = str(command[1]).lower()
           addr = int(command[2])
           data = [x for x in command[3:]]
           write(client=client, addr=addr, typ=typ, data=data)
       elif command[0] == 'exit':
           break
       else:
           print('Supported commands are:')
           print('read IOH TYPE ADDRESS [COUNT]')
           print('write TYPE ADDRESS WORD...')
   client.close()
   print('Goodbye\n')



def main():
   args = docopt(__doc__, version='ctmodbus 0.2')
   if args['-d']:
       DEBUG = True
       print(args)
   else:
       DEBUG = False
   logging.basicConfig()
   log = logging.getLogger()
   #log.setLevel(logging.DEBUG)

   target = parse_target(args['TARGET'])
   client = connect(target)

   if args['COUNT'] == None:
       args['COUNT'] = 1

   if args['connect']:
       modbus_prompt(client, args)
   else:
       no_prompt(client, args)


if __name__ == '__main__':
   main()
