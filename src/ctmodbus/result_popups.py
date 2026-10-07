"""Standard ctui result dialogs for management commands, without output replacement.

Actions complete before presentation. Await dismissal to sequence command input;
background I/O and output appends continue. CLI and headless dispatch retain
plain CommandResult output. Only application-owned commands are selected.
"""

from ctui.dialogs import MessageDialog, show_dialog

ACTIONS = {
    "start": "started",
    "stop": "stopped",
    "list": "list",
    "show": "details",
    "status": "status",
    "import": "imported",
    "export": "exported",
    "discover": "discovery",
    "validate": "validation",
    "set": "updated",
    "save": "saved",
    "load": "loaded",
    "create": "created",
    "rename": "renamed",
    "delete": "deleted",
    "logging": "logging",
    "reset": "reset",
    "clear": "cleared",
    "unit": "unit updated",
    "seed": "seed updated",
    "identity": "identity updated",
    "table": "table updated",
    "random": "random rule updated",
    "sequence": "sequence rule updated",
    "remove": "rule removed",
    "read": "read hook updated",
    "write": "write hook updated",
    "tick": "tick hook updated",
}


def result_title(command_name: str) -> str | None:
    """Return a descriptive title for an owned management command, else None."""
    words = command_name.split()
    if len(words) < 2:
        return None
    component = words[0]
    if component not in {"client", "server", "proxy", "tags", "poll"}:
        return None
    if component == "poll" and words[1] not in {"status", "stop"}:
        return None
    subject = "Tags" if component == "tags" else component.capitalize()
    action = words[1]
    if action in {"config", "hook"}:
        if len(words) < 3:
            return None
        subject += " configuration" if action == "config" else " hooks"
        action = words[2]
    description = ACTIONS.get(action)
    return f"{subject} {description}" if description else None


async def show_result(title: str, text: str) -> None:
    """Await a standard scrollable dialog in the current terminal/browser view."""
    await show_dialog(
        MessageDialog(title=title, text=text, scrollbar=True, wrap_lines=False)
    )
