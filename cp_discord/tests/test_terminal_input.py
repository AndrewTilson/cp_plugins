"""Prompt mirroring contract tests against core's real CLI/queue boundaries."""

import asyncio
from types import SimpleNamespace

import pytest
from unittest.mock import patch

from code_puppy import callbacks, plugins

# cli_runner loads user plugins at import time; never discover runtime plugins.
with patch.object(plugins, "load_plugin_callbacks"):
    from code_puppy import cli_runner
from code_puppy.agent_execution_context import executing_agent_context
from code_puppy.agents._runtime import _sanitize_prompt
from code_puppy.messaging import run_ui
from code_puppy.messaging.pause_controller import PauseController

from cp_discord import inbound, reporter, terminal_input as mirror
from cp_discord.chunking import chunk_message


@pytest.fixture
def bridge(monkeypatch):
    mirror.uninstall()
    events = []
    mailbox = reporter.Mailbox(events.append)
    monkeypatch.setattr(reporter, "active_mailbox", lambda: mailbox)
    # Keep the real CLI attachment parser and task creation, but no UI/network.
    mirror.install()
    yield mailbox, events
    mirror.uninstall()


class HookAgent:
    async def run_with_mcp(self, prompt, **kwargs):
        sanitized = _sanitize_prompt(prompt)
        results = await callbacks.on_user_prompt_submit(sanitized, "run-id")
        assert all(result is None for result in results)
        return sanitized


async def submit(prompt):
    result, _task = await cli_runner.run_prompt_with_attachments(
        HookAgent(), prompt, use_run_ui=False
    )
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", ["hello", "a" * 6000, "multiline\ntext", "caf\u00e9 \u6f22\u5b57"])
async def test_terminal_report_and_chunking(bridge, prompt):
    mailbox, events = bridge
    result = await submit(prompt)
    mailbox.drain_now()
    assert len(events) == 1
    assert isinstance(events[0], reporter.ReportEvent)
    assert events[0].chunks == tuple(chunk_message(f"**Terminal input**\n\n{result}"))
    assert all(len(chunk) <= 2000 for chunk in events[0].chunks)
    assert mirror._origin.get() is None


@pytest.mark.asyncio
async def test_real_queue_idle_parser_sanitizer_preserve_provenance(bridge, monkeypatch):
    mailbox, events = bridge
    controller = PauseController()
    monkeypatch.setattr(
        "code_puppy.messaging.pause_controller.get_pause_controller", lambda: controller
    )
    inbound._default_steer("identical text", "queue")
    queued = controller.pop_next_steer_queued()
    assert isinstance(queued, mirror.DiscordPrompt)
    assert queued == "identical text"
    queue = asyncio.Queue()
    monkeypatch.setattr(run_ui, "_loop", asyncio.get_running_loop())
    monkeypatch.setattr(run_ui, "_idle_queue", queue)
    run_ui._push_idle(queued)
    delivered = await asyncio.wait_for(queue.get(), timeout=1)
    assert delivered is queued
    assert await submit(delivered) == "identical text"
    mailbox.drain_now()
    assert events == []
    # Neither a text cache nor a stale ContextVar may suppress this human turn.
    await submit("identical text")
    mailbox.drain_now()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_nested_and_unattributed_internal_prompts_filtered(bridge):
    mailbox, events = bridge
    await mirror.on_user_prompt_submit("direct internal", "anything")
    with executing_agent_context(SimpleNamespace(name="parent")):
        await submit("nested agent")
    token = mirror._origin.set("terminal")
    try:
        await submit("nested CLI wrapper")
    finally:
        mirror._origin.reset(token)
    mailbox.drain_now()
    assert events == []
    await submit("real terminal")
    mailbox.drain_now()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_cli_continuation_filtered_by_identity_not_text(bridge):
    mailbox, events = bridge
    # Model the actual CLI continuation call site, including its local variable.
    namespace = {"__name__": "code_puppy.cli_runner", "submit": submit,
                 "run": cli_runner.run_prompt_with_attachments, "agent": HookAgent()}
    import linecache
    source = ("async def continuation():\n"
              "    next_prompt = 'follow up'\n"
              "    return await run(\n"
              "        agent,\n"
              "        next_prompt,\n"
              "        use_run_ui=False)\n")
    filename = "<cp_discord_continuation_test>"
    linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)
    try:
        exec(compile(source, filename, "exec"), namespace)
        await namespace["continuation"]()
    finally:
        linecache.cache.pop(filename, None)
    mailbox.drain_now()
    assert events == []
    await submit("follow up")
    mailbox.drain_now()
    assert len(events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", ["", "   ", None, 123, mirror.DiscordPrompt("remote")])
async def test_empty_invalid_and_marked_hook_values(bridge, prompt):
    mailbox, events = bridge
    token = mirror._origin.set("terminal")
    try:
        assert await mirror.on_user_prompt_submit(prompt, None) is None
    finally:
        mirror._origin.reset(token)
    mailbox.drain_now()
    assert events == []


@pytest.mark.asyncio
async def test_report_failure_does_not_change_prompt_or_leak_secrets(bridge, monkeypatch, caplog):
    mailbox, events = bridge
    def fail(event):
        raise RuntimeError("secret")
    monkeypatch.setattr(mailbox, "post_report", fail)
    with caplog.at_level("DEBUG", logger=mirror.__name__):
        assert await submit("secret") == "secret"
    assert "secret" not in caplog.text
    assert events == []


@pytest.mark.asyncio
async def test_wrapper_resets_context_on_error(bridge):
    class BrokenAgent:
        async def run_with_mcp(self, *args, **kwargs):
            raise RuntimeError("broken")
    with pytest.raises(RuntimeError, match="broken"):
        await cli_runner.run_prompt_with_attachments(BrokenAgent(), "text", use_run_ui=False)
    assert mirror._origin.get() is None


def test_lifecycle_restores_and_deduplicates(bridge):
    wrapper = cli_runner.run_prompt_with_attachments
    original = mirror._original_run
    mirror.install()
    assert cli_runner.run_prompt_with_attachments is wrapper
    mirror.uninstall()
    mirror.uninstall()
    assert cli_runner.run_prompt_with_attachments is original
    assert mirror._mailbox is None
    mirror.install()
    assert cli_runner.run_prompt_with_attachments is not original


def test_missing_mailbox_does_not_patch(monkeypatch):
    mirror.uninstall()
    original = cli_runner.run_prompt_with_attachments
    monkeypatch.setattr(reporter, "active_mailbox", lambda: None)
    with pytest.raises(RuntimeError, match="state reporter"):
        mirror.install()
    assert cli_runner.run_prompt_with_attachments is original


@pytest.mark.asyncio
async def test_concurrent_origins_do_not_leak(bridge):
    mailbox, events = bridge
    await asyncio.gather(submit(mirror.DiscordPrompt("remote")), submit("human"))
    mailbox.drain_now()
    assert len(events) == 1
    assert events[0].chunks == tuple(chunk_message("**Terminal input**\n\nhuman"))


@pytest.mark.asyncio
async def test_uninstall_unregisters_hook(bridge):
    mailbox, events = bridge
    mirror.uninstall()
    token = mirror._origin.set("terminal")
    try:
        assert mirror.on_user_prompt_submit not in callbacks._callbacks["user_prompt_submit"]
        await callbacks.on_user_prompt_submit("human", "run")
    finally:
        mirror._origin.reset(token)
    mailbox.drain_now()
    assert events == []


def test_uninstall_respects_other_wrapper(bridge):
    original = mirror._original_run
    async def other(*args, **kwargs):
        return None
    cli_runner.run_prompt_with_attachments = other
    try:
        mirror.uninstall()
        assert cli_runner.run_prompt_with_attachments is other
    finally:
        cli_runner.run_prompt_with_attachments = original


@pytest.mark.asyncio
async def test_stale_continuation_local_does_not_hide_identical_terminal(bridge):
    mailbox, events = bridge
    namespace = {"__name__": "code_puppy.cli_runner",
                 "run": cli_runner.run_prompt_with_attachments, "agent": HookAgent()}
    exec("async def human_turn():\n"
         "    next_prompt = 'same'\n"
         "    task = next_prompt\n"
         "    return await run(agent, task, use_run_ui=False)\n", namespace)
    await namespace["human_turn"]()
    mailbox.drain_now()
    assert len(events) == 1


def test_component_order():
    from cp_discord.register_callbacks import COMPONENTS
    modules = [component.module for component in COMPONENTS]
    assert modules.index("reporter") < modules.index("terminal_input") < modules.index("inbound")
