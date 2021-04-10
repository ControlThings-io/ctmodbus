import logging

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
    ModbusSparseDataBlock,
)
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.server.sync import StartSerialServer
from pymodbus.transaction import ModbusBinaryFramer, ModbusRtuFramer
from pymodbus.version import version

FORMAT = (
    "%(asctime)-15s %(threadName)-15s"
    " %(levelname)-8s %(module)-15s:%(lineno)-8s %(message)s"
)
logging.basicConfig(format=FORMAT)
log = logging.getLogger()
log.setLevel(logging.DEBUG)


def run_server():
    store = ModbusSlaveContext(
        di=ModbusSequentialDataBlock(0, [17] * 100),
        co=ModbusSequentialDataBlock(0, [17] * 100),
        hr=ModbusSequentialDataBlock(0, [17] * 100),
        ir=ModbusSequentialDataBlock(0, [17] * 100),
    )

    context = ModbusServerContext(slaves=store, single=True)

    identity = ModbusDeviceIdentification()
    identity.VendorName = "Pymodbus"
    identity.ProductCode = "PM"
    identity.VendorUrl = "http://github.com/riptideio/pymodbus/"
    identity.ProductName = "Pymodbus Server"
    identity.ModelName = "Pymodbus Server"
    identity.MajorMinorRevision = version.short()

    # socat -d -d PTY,link=/tmp/ptyp0,raw,echo=0,ispeed=9600 PTY,link=/tmp/ttyp0,raw,echo=0,ospeed=9600

    StartSerialServer(context, identity=identity, port="/dev/ttyp0", timeout=1)


if __name__ == "__main__":
    run_server()
