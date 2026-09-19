"""A prompt and fast reply must coexist in the pending transcript."""
from cp_discord.reporter import Mailbox, ReportEvent


def test_pending_prompt_and_answer_are_delivered_in_order():
    events = []
    mailbox = Mailbox(events.append, autostart=False)
    mailbox.post_report(ReportEvent(("Terminal input", "long prompt part two")))
    mailbox.post_report(ReportEvent(("Assistant reply",)))
    mailbox.drain_now()
    assert events == [ReportEvent(("Terminal input", "long prompt part two", "Assistant reply"))]
    mailbox.close()


def test_pending_transcript_is_bounded_with_visible_overflow():
    events = []
    mailbox = Mailbox(events.append, autostart=False)
    for index in range(200):
        mailbox.post_report(ReportEvent((str(index),)))
    mailbox.drain_now()
    chunks = events[0].chunks
    assert len(chunks) == 128
    assert chunks[0] == "[Earlier pending transcript chunks omitted]"
    assert chunks[1:] == tuple(str(index) for index in range(73, 200))
    mailbox.close()


def test_closed_mailbox_ignores_new_transcript():
    events = []
    mailbox = Mailbox(events.append, autostart=False)
    mailbox.close()
    mailbox.post_report(ReportEvent(("late prompt",)))
    mailbox.drain_now()
    assert not any(isinstance(event, ReportEvent) for event in events)
