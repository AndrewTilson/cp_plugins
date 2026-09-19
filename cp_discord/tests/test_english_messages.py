"""Pin the English messages shown in Discord, including fallback text."""

import pytest

from cp_discord import approvals, broker_gates, collector, reporter


@pytest.mark.parametrize(
    ("actual", "expected"),
    [
        (approvals.DECIDED_IN_TERMINAL, "decided in the terminal"),
        (approvals.DECIDED_IN_DISCORD, "decided in Discord"),
        (approvals.GATE_EXPIRED, "expired - can only be answered on the PC now"),
        (broker_gates.UNDELIVERABLE,
         "Delivery failed — the session is not responding."),
        (reporter.BLOCKED_ON_GATE, "waiting for your approval"),
        (reporter.LOCAL_ONLY_MARKER, "can only be answered on the PC"),
        (reporter.BLOCKED_LOCALLY,
         "waiting for input — can only be answered on the PC"),
        (collector.TRUNCATION_MARKER, "… (beginning truncated)"),
    ],
)
def test_user_facing_messages_are_english(actual, expected):
    assert actual == expected


@pytest.mark.parametrize("count", [0, 1, 50, 1000])
def test_overflow_message_preserves_count(count):
    assert collector.OVERFLOW_TEMPLATE.format(count=count) == f"… ({count} more)"


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, "decided"),
        ({"outcome": None, "title": None}, "decided"),
        ({"outcome": "  ", "title": "\t"}, "decided"),
        ({"outcome": " approved "}, "approved"),
        ({"title": " Gate "}, "Gate"),
        ({"outcome": " approved ", "title": " Gate "},
         "**Gate** — approved"),
    ],
)
def test_closing_text_keeps_format_and_uses_english_fallback(params, expected):
    assert broker_gates.closing_text(params) == expected
