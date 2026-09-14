"""Native async transports and serialized, cancellable connection ownership."""

import asyncio
import math
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import Literal

from ctui import CommandError
from pymodbus import FramerType
from pymodbus.client import (
    AsyncModbusSerialClient,
    AsyncModbusTcpClient,
    AsyncModbusUdpClient,
)
from pymodbus.exceptions import ModbusException

Transport = Literal["tcp", "udp", "rtu", "ascii"]


@dataclass(frozen=True)
class ConnectionSettings:
    """Serializable settings; never persist a live transport."""

    transport: Transport
    target: str
    port: int = 502
    unit: int = 1
    timeout: float = 3.0
    retries: int = 0
    baudrate: int = 9600
    bytesize: int = 8
    parity: Literal["N", "E", "O"] = "N"
    stopbits: int = 1

    def __post_init__(self):
        if self.transport not in ("tcp", "udp", "rtu", "ascii"):
            raise CommandError("Transport must be tcp, udp, rtu, or ascii")
        if not isinstance(self.target, str) or not self.target.strip():
            raise CommandError("A host or serial device is required")
        for name, low, high in (
            ("port", 1, 65535),
            ("unit", 1, 247),
            ("retries", 0, 10),
            ("baudrate", 1, 4_000_000),
            ("bytesize", 7, 8),
            ("stopbits", 1, 2),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise CommandError(
                    f"{name} must be an integer between {low} and {high}"
                )
        if (
            type(self.timeout) not in (int, float)
            or not math.isfinite(self.timeout)
            or not 0 < self.timeout <= 300
        ):
            raise CommandError(
                "timeout must be finite and between 0 (exclusive) and 300 seconds"
            )
        if self.parity not in ("N", "E", "O"):
            raise CommandError("parity must be N, E, or O")

    def as_dict(self):
        """Return only JSON-compatible connection settings."""
        return asdict(self)

    @property
    def label(self):
        """Return an endpoint label shared by logs and the status bar."""
        target = (
            f"{self.target}:{self.port}"
            if self.transport in ("tcp", "udp")
            else self.target
        )
        return f"{self.transport.upper()} {target} unit {self.unit}"


def create_client(settings):
    """Construct a client in the running event loop; disable implicit reconnects."""
    options = {
        "timeout": settings.timeout,
        "retries": settings.retries,
        "reconnect_delay": 0,
    }
    if settings.transport == "tcp":
        return AsyncModbusTcpClient(settings.target, port=settings.port, **options)
    if settings.transport == "udp":
        return AsyncModbusUdpClient(settings.target, port=settings.port, **options)
    return AsyncModbusSerialClient(
        settings.target,
        framer=FramerType.RTU if settings.transport == "rtu" else FramerType.ASCII,
        baudrate=settings.baudrate,
        bytesize=settings.bytesize,
        parity=settings.parity,
        stopbits=settings.stopbits,
        **options,
    )


class Connection:
    """Own one client, invalidate stale work, and serialize wire transactions."""

    def __init__(self, client_factory=create_client):
        self.client_factory = client_factory
        self.client = None
        self.settings = None
        self.generation = 0
        self.lock = asyncio.Lock()
        self.tasks = set()

    @property
    def connected(self):
        """Read actual transport status rather than assuming an open socket."""
        return self.client is not None and self.client.connected

    async def connect(self, settings):
        """Create and open a client, discarding failed or cancelled attempts."""
        task = asyncio.current_task()
        generation = self.generation
        self.tasks.add(task)
        try:
            async with self.lock:
                if generation != self.generation:
                    raise CommandError("Connection attempt cancelled")
                if self.client is not None:
                    raise CommandError("A session is already open; close it first")
                client = self.client_factory(settings)
                try:
                    async with asyncio.timeout(settings.timeout + 1):
                        if not await client.connect():
                            raise CommandError(f"Could not open {settings.label}")
                except BaseException:
                    client.close()
                    raise
                self.client, self.settings = client, settings
        except (OSError, ModbusException, TimeoutError) as error:
            raise CommandError(f"Connection failed: {error}") from error
        except asyncio.CancelledError as error:
            raise CommandError("Connection attempt cancelled") from error
        finally:
            self.tasks.discard(task)

    @asynccontextmanager
    async def operation(self):
        """Reserve the current session for a complete command's requests."""
        client, generation = self.client, self.generation
        if client is None:
            raise CommandError("No open session; connect first")
        task = asyncio.current_task()
        self.tasks.add(task)
        try:
            async with self.lock:
                if generation != self.generation or client is not self.client:
                    raise CommandError("Session changed before the operation started")
                if not client.connected:
                    raise CommandError("Session disconnected; close and reconnect")
                yield client, self.settings
        finally:
            self.tasks.discard(task)

    async def close(self):
        """Cancel outstanding I/O before releasing the transport."""
        self.generation += 1
        pending = self.tasks - {asyncio.current_task()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        async with self.lock:
            if self.client is not None:
                self.client.close()
            self.client = self.settings = None

    def abort(self):
        """Discard the transport after interrupted I/O and reject queued work."""
        self.generation += 1
        if self.client is not None:
            self.client.close()
        self.client = self.settings = None

    async def request(self, method, **kwargs):
        """Bound each request even if a transport stops responding."""
        settings = self.settings
        try:
            async with asyncio.timeout((settings.timeout + 1) * (settings.retries + 1)):
                response = await method(device_id=settings.unit, **kwargs)
        except (OSError, ModbusException, TimeoutError) as error:
            raise CommandError(f"Modbus request failed: {error}") from error
        if response is None or response.isError():
            raise CommandError(f"Modbus error response: {response}")
        return response
