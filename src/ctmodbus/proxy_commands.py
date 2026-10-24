"""Plain proxy lifecycle and independent request display controls."""

from typing import Literal

from ctui import Argument, CommandError, CommandResult, command


class ProxyCommandMixin:
    """Route incoming server requests through the application-owned client."""

    @command(name="proxy start", arguments={"quiet": Argument(flags=("--quiet",))})
    async def proxy_start(self, quiet: bool = False):
        """Forward server-unit requests to the connected unit; local rules are
        bypassed.
        """
        if self.server.listener is None or not self.connection.connected:
            raise CommandError("Proxy requires a running server and a connected client")
        if self.connection.settings.retries:
            raise CommandError("Proxy requires a client connection with --retries 0")
        settings = self.connection.settings
        if self.server.endpoint and settings.transport in ("tcp", "udp", "tls"):
            target, port = self.server.endpoint
            local_names = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "::"}
            if port == settings.port and (
                target == settings.target
                or (target in local_names and settings.target in local_names)
            ):
                raise CommandError("Proxy cannot forward to its own listener")
        self.server.proxy = True
        self.server.proxy_logging = not quiet
        return "Proxy enabled. New requests use the upstream device."

    @command(name="proxy stop")
    async def proxy_stop(self):
        """Return new requests to local behavior; already-routed exchanges finish
        normally.
        """
        self.server.proxy = False
        return "Proxy disabled. New requests use local simulation."

    @command(name="proxy status")
    async def proxy_status(self):
        """Show forwarding mode and upstream connection readiness."""
        mode = "enabled" if self.server.proxy else "disabled"
        upstream = "connected" if self.connection.connected else "unavailable"
        return (
            f"Proxy: {mode}\nUpstream: {upstream}\n"
            f"Logging: {'on' if self.server.proxy_logging else 'off'}"
        )

    @command(
        name="proxy logging",
        arguments={
            "state": Argument(help="Enable or disable routine proxy forwarding lines")
        },
    )
    def proxy_logging(self, state: Literal["on", "off"]):
        """Change live forwarding verbosity independently of server arrival logging."""
        self.server.proxy_logging = state == "on"
        return CommandResult.append(f"Proxy request logging {state}.")
