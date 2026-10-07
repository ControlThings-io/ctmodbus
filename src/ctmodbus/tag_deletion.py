"""Confirmed tag deletion with atomic removal of saved server tag rules."""

import asyncio

from ctui import CommandError, CommandResult, ConfirmationRequired

from ctmodbus import server_config


class TagDeletionMixin:
    """Prepare exact deletion targets under dispatch guards before confirmation."""

    async def plan_tag_deletion(
        self, name=None, all_tags=False, remove_server_rules=False, confirm=False
    ):
        """Validate exclusive NAME/--all selection and snapshot affected config.

        Referenced rules require --remove-server-rules. Bulk deletion, rule
        removal, or retained hooks require approval unless --confirm is supplied.
        Never inspect or change companion Python files; warn about their references.
        """
        if (name is None) == (not all_tags):
            raise CommandError("Specify a tag name or --all, never both")
        selected = await self.tags.list() if all_tags else [await self.tags.get(name)]
        names = tuple(tag.name for tag in selected)
        if not names:
            return {"names": names}
        stored = (await self.configs.list()).get(server_config.CONFIG_NAME)
        config = server_config.validate(stored) if stored is not None else None
        references = sorted(set(names) & set(config["tags"])) if config else []
        if references and not remove_server_rules:
            raise CommandError(
                "Saved server tag rules reference: "
                + ", ".join(references)
                + ". Use --remove-server-rules to delete these entries with the tags."
            )
        warning = (
            "Warning: retained Python hooks may reference deleted tags; "
            "update them manually."
            if config and config["hooks"]
            else ""
        )
        message = (
            f"Delete {len(names)} project tags and remove "
            f"{len(references)} server tag rules?"
        )
        if warning:
            message += "\n" + warning
        message += "\nUse --confirm to approve without prompting."
        replacement = None
        if references:
            for target in references:
                del config["tags"][target]
            replacement = server_config.validate(config)
        return {
            "names": names,
            "stored": stored,
            "replacement": replacement,
            "rule_count": len(references),
            "warning": warning,
            "message": message,
            "needs_confirmation": bool(all_tags or references or warning)
            and not confirm,
        }

    async def prepare_tag_deletion(self, text, kwargs):
        """Confirm through ctui's requesting UI callback, retaining exact targets.

        CLI without --confirm raises ConfirmationRequired. Decline or cancellation
        changes nothing. Project/tag/server guards remain reserved during approval.
        """
        item, arguments = self.commands.resolve(text)
        arguments = await item.expand_unique_arguments(arguments, self)
        plan = await self.plan_tag_deletion(**item.parse_args(arguments))
        if plan.get("needs_confirmation"):
            if not await self.confirm_replacement(plan["message"], kwargs):
                return CommandResult.rejected()
        self._prepared_tag_deletions[asyncio.current_task()] = plan
        return None

    async def delete_tag_definitions(
        self, name, all_tags, remove_server_rules, confirm
    ):
        """Commit the exact prepared deletion and server rule changes together.

        Direct method calls still validate and require --confirm for destructive
        selections. Dispatch handles normal UI approval and result MessageDialogs.
        Raw rules, hooks, saved settings and external files remain unchanged.
        """
        plan = self._prepared_tag_deletions.get(asyncio.current_task())
        if plan is None:
            plan = await self.plan_tag_deletion(
                name, all_tags, remove_server_rules, confirm
            )
            if plan.get("needs_confirmation"):
                raise ConfirmationRequired(plan["message"])
        if not plan["names"]:
            return "No tags to delete."
        await self.tags.delete_selected(
            plan["names"],
            server_config.CONFIG_NAME,
            plan["stored"],
            plan["replacement"],
        )
        result = (
            f"Deleted {len(plan['names'])} project tags; "
            f"removed {plan['rule_count']} server tag rules."
        )
        return result + ("\n" + plan["warning"] if plan["warning"] else "")
