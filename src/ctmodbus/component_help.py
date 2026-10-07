"""Example-led component overview popups, separate from generated command help.

ctui currently exposes popup help through its internal _HelpResult protocol.
Keep that small adapter here; both terminal and browser use format_ui_help.
Normal help targets continue through ctui's generated formatter unchanged.
"""

from ctui import command
from ctui.commands import _HelpResult

OVERVIEWS = {
    "client": """Client — select settings, connect, inspect, and stop.

client discover
client start tcp localhost --port 502
client config set --transport tls --target device --port 802
client config save lab
client config load lab
client config show
client start
client status
client stop [--confirm]

Loading or editing settings requires a stopped client and never connects.
Stopping also stops an active proxy after confirmation.
Use help client for the full generated command reference.""",
    "server": """Server — configure local behavior, then start a listener.

server config import examples/device.toml
server config show
server config set holding_registers 0-3 42
server config validate
server start tcp 127.0.0.1 --port 5020
server status
server reset --confirm
server logging off
server stop [--confirm]

Configuration and hooks are edited while stopped. Status includes runtime
values and downstream evidence; reset restores local simulation state.
Use help server for transports, config editing, export, and hook options.""",
    "proxy": """Proxy — forward server requests through the connected client.

client start tcp upstream --retries 0
server start tcp 127.0.0.1 --port 5020
proxy start [--quiet]
proxy status
proxy logging off
proxy stop

Both client and server must be running. New requests return to local
simulation after proxy stop; already routed exchanges finish normally.
Use help proxy for the full generated command reference.""",
}


class ComponentHelpMixin:
    """Return overview help using ctui's shared TUI/WUI popup result protocol."""

    def format_ui_help(self, target=None):
        """Render custom overview sentinels; preserve generated help targets."""
        if target and target.startswith("@overview:"):
            return OVERVIEWS[target.removeprefix("@overview:")]
        return super().format_ui_help(target)

    @command(name="client")
    def client_overview(self):
        """Open concise client examples."""
        return _HelpResult(output=OVERVIEWS["client"], target="@overview:client")

    @command(name="server")
    def server_overview(self):
        """Open concise server examples."""
        return _HelpResult(output=OVERVIEWS["server"], target="@overview:server")

    @command(name="proxy")
    def proxy_overview(self):
        """Open concise proxy examples."""
        return _HelpResult(output=OVERVIEWS["proxy"], target="@overview:proxy")
