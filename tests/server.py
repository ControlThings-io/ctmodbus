"""Local fixtures for automated tests and manual device-client checks.

Example: uv run python tests/server.py tcp --port 5020
"""

import argparse
import asyncio

from pymodbus import FramerType
from pymodbus.pdu.device import ModbusDeviceIdentification
from pymodbus.server import ModbusSerialServer, ModbusTcpServer, ModbusUdpServer
from pymodbus.simulator import DataType, SimData, SimDevice


def device():
    identity = ModbusDeviceIdentification()
    identity.VendorName = "ControlThings"
    identity.ProductCode = "ctmodbus-test"
    identity.MajorMinorRevision = "1.0"
    return SimDevice(
        id=1,
        identity=identity,
        simdata=(
            [SimData(0, count=4096, values=False, datatype=DataType.BITS)],
            [SimData(0, count=4096, values=True, datatype=DataType.BITS)],
            [SimData(0, count=512, values=17, datatype=DataType.REGISTERS)],
            [SimData(0, count=512, values=42, datatype=DataType.REGISTERS)],
        ),
    )


def make_server(transport, target="127.0.0.1", port=0):
    if transport in ("tcp", "udp"):
        cls = ModbusTcpServer if transport == "tcp" else ModbusUdpServer
        return cls(device(), address=(target, port))
    return ModbusSerialServer(
        device(),
        port=target,
        framer=FramerType.RTU if transport == "rtu" else FramerType.ASCII,
        baudrate=9600,
    )


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transport", choices=("tcp", "udp", "rtu", "ascii"))
    parser.add_argument(
        "--target", default="127.0.0.1", help="Bind address or serial device path"
    )
    parser.add_argument("--port", type=int, default=5020)
    args = parser.parse_args()
    server = make_server(args.transport, args.target, args.port)
    try:
        await server.serve_forever()
    finally:
        await server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
