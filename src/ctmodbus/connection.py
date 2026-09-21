"""Native async transports and serialized, cancellable connection ownership.

Construct validated ConnectionSettings, await Connection.connect(settings), then
use ``async with connection.operation()`` around related request calls. Clients
and tasks are runtime state; only settings are serializable. Transport failures
become CommandError. Protocol shape validation belongs to operations.py.
"""

import asyncio
import inspect
import math
import ssl
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import Literal

from ctui import CommandError
from pymodbus import FramerType
from pymodbus.client import (
    AsyncModbusSerialClient,
    AsyncModbusTcpClient,
    AsyncModbusTlsClient,
    AsyncModbusUdpClient,
)
from pymodbus.exceptions import ModbusException

Transport = Literal["tcp", "udp", "tls", "rtu", "ascii"]


@dataclass(frozen=True)
class ConnectionSettings:
    """Immutable, JSON-compatible endpoint and transport configuration.

    Construction raises CommandError for invalid settings: unit 1–247, port
    1–65535, retries 0–10, finite timeout in (0, 300] seconds, baudrate
    1–4,000,000, 7/8 data bits, N/E/O parity, and 1/2 stop bits. TLS options
    require TLS; a separate key requires a certificate. File existence and
    certificate validity are checked when creating the client, not here.
    Direct construction defaults to port 502; the TLS command supplies 802.
    """

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
    ca_file: str | None = None
    cert_file: str | None = None
    key_file: str | None = None
    insecure: bool = False

    def __post_init__(self):
        """Validate all fields immediately; raise CommandError before device I/O."""
        if self.transport not in ("tcp", "udp", "tls", "rtu", "ascii"):
            raise CommandError("Transport must be tcp, udp, tls, rtu, or ascii")
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

        for name in ("ca_file", "cert_file", "key_file"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise CommandError(f"{name} must be a nonempty file path")
        if type(self.insecure) is not bool:
            raise CommandError("insecure must be a boolean")
        if self.key_file and not self.cert_file:
            raise CommandError("key-file requires cert-file")
        if self.transport != "tls" and any(
            (self.ca_file, self.cert_file, self.key_file, self.insecure)
        ):
            raise CommandError("Certificate options require a TLS connection")

    def as_dict(self):
        """Return only JSON-compatible connection settings."""
        return asdict(self)

    @property
    def label(self):
        """Return an endpoint label shared by logs and the status bar."""
        target = (
            f"{self.target}:{self.port}"
            if self.transport in ("tcp", "udp", "tls")
            else self.target
        )
        return f"{self.transport.upper()} {target} unit {self.unit}"


def tls_context(settings):
    """Return an SSLContext with trust and hostname verification by default.

    This synchronous function loads files; async callers must offload it.
    Explicit insecure settings disable verification. An empty key password
    prevents terminal prompts; encrypted keys are unsupported. SSL and file
    errors propagate to the connection-opening error boundary.
    """
    context = ssl.create_default_context(cafile=settings.ca_file)
    if settings.insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    if settings.cert_file:
        # An explicit empty password prevents OpenSSL prompting on stdin for an
        # encrypted key. Password-bearing credentials are not stored in profiles.
        context.load_cert_chain(settings.cert_file, settings.key_file, password="")
    return context


async def create_client(settings):
    """Return an unopened native async client for validated settings.

    Run in an event loop; certificate loading uses a worker thread. The caller
    owns connection and cleanup. File/client-construction errors propagate.
    Reconnect delay is zero so interrupted work requires explicit reconnection.
    """
    options = {
        "timeout": settings.timeout,
        "retries": settings.retries,
        "reconnect_delay": 0,
    }
    if settings.transport == "tls":
        context = await asyncio.to_thread(tls_context, settings)
        return AsyncModbusTlsClient(
            settings.target, port=settings.port, sslctx=context, **options
        )
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
    """Own one client and serialize operations within a single event loop.

    A generation counter prevents queued operations using a replaced transport.
    The injected factory may return a client or an awaitable client. Callers
    must reserve operation() before request(); request() does not take the lock.
    """

    def __init__(self, client_factory=create_client):
        """Initialize disconnected state without opening a socket or serial port."""
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
        """Open settings under the lock and return None on success.

        Reject an existing client or obsolete generation. Client.connect is
        bounded by timeout + 1 seconds; factory creation precedes that bound.
        Failed opens close the candidate. Transport errors and cancellation
        become CommandError; other factory errors propagate.
        """
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
                if inspect.isawaitable(client):
                    client = await client
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
        """Yield (client, settings) while exclusively reserving this session.

        Raise CommandError for absent, disconnected, or replaced sessions.
        Release the lock and task registration on any exit. This context does
        not itself close the transport when its body fails or is cancelled.
        """
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
        """Invalidate queued work, cancel/drain other tasks, then clear state.

        Return None; repeated calls are harmless. This low-level drain has no
        timeout; the application supplies its own bounded shutdown path.
        """
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
        """Synchronously close and clear transport/settings; increment generation.

        Return None without awaiting or cancelling tasks. Generation checks
        reject queued work, and callers remain responsible for draining tasks.
        """
        self.generation += 1
        if self.client is not None:
            self.client.close()
        self.client = self.settings = None

    async def request(self, method, **kwargs):
        """Await method(device_id=unit, **kwargs) and return a non-error reply.

        Requires an active operation() reservation. Bound execution by
        (timeout + 1) * (retries + 1) seconds; map transport/timeout failures,
        absent replies, and Modbus exception replies to CommandError.
        Cancellation propagates; callers decide read/write uncertainty.
        """
        settings = self.settings
        try:
            async with asyncio.timeout((settings.timeout + 1) * (settings.retries + 1)):
                response = await method(device_id=settings.unit, **kwargs)
        except (OSError, ModbusException, TimeoutError) as error:
            raise CommandError(f"Modbus request failed: {error}") from error
        if response is None or response.isError():
            raise CommandError(f"Modbus error response: {response}")
        return response
