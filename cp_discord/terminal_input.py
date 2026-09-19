"""Mirror CLI prompt submissions without echoing Discord-originated turns.

Core 0.0.851 preserves string identity through request_steer and _push_idle,
then destroys subclasses in attachment parsing and UTF-8 sanitization. Carry
provenance across that boundary with a ContextVar, not a text cache. The CLI
wrapper is restored on uninstall; no installed core files are modified.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from functools import wraps
from typing import Any

from .chunking import chunk_message
from .reporter import ReportEvent

logger = logging.getLogger(__name__)
_origin: ContextVar[str | None] = ContextVar("cp_discord_prompt_origin", default=None)
_mailbox = None
_original_run = None
_run_wrapper = None


class DiscordPrompt(str):
    """Inbound text with object-local provenance; its value is unchanged."""


async def on_user_prompt_submit(prompt: str, session_id: Any) -> None:
    """Observe only CLI user turns, never replace or block their prompt."""
    try:
        from code_puppy.agent_execution_context import get_executing_agent

        # This hook precedes runtime's executing_agent_context. An existing
        # context therefore belongs to an enclosing agent (nested/internal run).
        if (
            _mailbox is None
            or _origin.get() != "terminal"
            or get_executing_agent() is not None
            or isinstance(prompt, DiscordPrompt)
            or not isinstance(prompt, str)
            or not prompt.strip()
        ):
            return None
        _mailbox.post_report(
            ReportEvent(tuple(chunk_message(f"**Terminal input**\n\n{prompt}")))
        )
    except Exception:
        # Do not log prompt text, including through an exception's message.
        logger.debug("cp_discord: terminal input mirroring failed")
    return None


def install(config: Any = None) -> None:
    """Install the observer and reversible provenance boundaries, idempotently."""
    global _mailbox, _original_run, _run_wrapper
    if _run_wrapper is not None:
        return
    from code_puppy import callbacks, cli_runner
    from .reporter import active_mailbox

    mailbox = active_mailbox()
    if mailbox is None:
        raise RuntimeError("terminal input mirroring needs the state reporter")
    original_run = cli_runner.run_prompt_with_attachments
    @wraps(original_run)
    async def run_wrapper(agent, raw_prompt, *args, **kwargs):
        # The CLI strips continuation text before this boundary. Identity is
        # insufficient if stripping changed it, so detect the CLI continuation
        # call structurally below, rather than comparing any prompt contents.
        import linecache
        import sys
        caller = sys._getframe(1)
        try:
            is_continuation = (
                caller.f_globals.get("__name__") == "code_puppy.cli_runner"
                and caller.f_locals.get("next_prompt") is raw_prompt
                # Locals survive loop iterations; identity alone can mistake
                # a later interned human string for the old continuation.
                and any(
                    line.strip() == "next_prompt,"
                    for line in linecache.getlines(caller.f_code.co_filename)[
                        caller.f_lineno - 1:caller.f_lineno + 4
                    ]
                )
            )
        finally:
            del caller
        origin = "discord" if isinstance(raw_prompt, DiscordPrompt) else "terminal"
        if is_continuation or _origin.get() is not None:
            origin = "internal"
        token = _origin.set(origin)
        try:
            return await original_run(agent, raw_prompt, *args, **kwargs)
        finally:
            _origin.reset(token)

    callbacks.register_callback("user_prompt_submit", on_user_prompt_submit)
    _mailbox = mailbox
    _original_run, _run_wrapper = original_run, run_wrapper
    cli_runner.run_prompt_with_attachments = run_wrapper


def uninstall() -> None:
    """Remove owned hooks/wrappers without overwriting another plugin's wrapper."""
    global _mailbox, _original_run, _run_wrapper
    from code_puppy import callbacks, cli_runner

    _mailbox = None
    callbacks.unregister_callback("user_prompt_submit", on_user_prompt_submit)
    if _run_wrapper is not None and cli_runner.run_prompt_with_attachments is _run_wrapper:
        cli_runner.run_prompt_with_attachments = _original_run
    _original_run = _run_wrapper = None
