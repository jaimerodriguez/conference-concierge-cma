"""follow_session survives a closed stream and re-attaches to a session waiting on us."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace as NS
from typing import Any

import pytest

from concierge import sessions
from concierge.sessions import Decision, follow_session


def _idle(event_id: str, reason: str) -> NS:
    return NS(type="session.status_idle", id=event_id, stop_reason=NS(type=reason))


def _ask(event_id: str) -> NS:
    return NS(
        type="agent.mcp_tool_use",
        id=event_id,
        name="create_event",
        mcp_server_name="calendar",
        input={"title": event_id},
        evaluated_permission="ask",
    )


def _message(event_id: str, text: str) -> NS:
    return NS(type="agent.message", id=event_id, content=[NS(type="text", text=text)])


class FakeClient:
    """Streams hand out one list each and then close; history is everything so far."""

    def __init__(self, history: list[NS], streams: list[list[NS]]) -> None:
        self.history = history
        self.streams = streams
        self.sent: list[dict[str, Any]] = []
        self.opened = 0
        events = NS(stream=self._stream, list=self._list, send=self._send)
        self.beta = NS(sessions=NS(events=events))

    @contextmanager
    def _stream(self, session_id: str):  # type: ignore[no-untyped-def]
        batch = self.streams[self.opened] if self.opened < len(self.streams) else []
        self.opened += 1
        yield iter(batch)

    def _list(self, session_id: str, order: str = "asc") -> list[NS]:
        return list(self.history)

    def _send(self, session_id: str, events: list[dict[str, Any]]) -> None:
        for event in events:
            self.sent.append(event)
            if event["type"] == "user.tool_confirmation":
                self.history.append(
                    NS(
                        type="user.tool_confirmation",
                        id=f"conf-{event['tool_use_id']}",
                        tool_use_id=event["tool_use_id"],
                    )
                )


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions.time, "sleep", lambda seconds: None)


def test_a_closed_stream_is_reopened_and_caught_up_without_repeats() -> None:
    first = [_message("m1", "booking now"), _ask("t1")]
    # While the person decided, the stream closed and the agent carried on.
    later = [_message("m2", "all booked"), _idle("i2", "end_turn")]
    client = FakeClient(history=[*first], streams=[first, []])
    asked: list[str] = []
    shown: list[str] = []

    def approver(event: Any) -> Decision:
        asked.append(event.id)
        client.history.extend(later)  # what happens on the server after the answer
        return Decision(allow=True)

    result = follow_session(
        client,  # type: ignore[arg-type]
        "s",
        approver=approver,
        on_event=lambda event: shown.append(event.id),
    )
    assert result.stop_reason == "end_turn" and not result.reconnects_exhausted
    assert asked == ["t1"]  # asked once, not again on catch-up
    assert shown.count("m1") == 1 and "m2" in shown  # missed events shown once
    assert result.text == "booking now\nall booked"


def test_it_gives_up_after_the_reconnect_limit() -> None:
    client = FakeClient(history=[_message("m1", "working")], streams=[])
    result = follow_session(client, "s")  # type: ignore[arg-type]
    assert result.stop_reason is None and result.reconnects_exhausted
    assert client.opened == sessions.MAX_RECONNECTS + 1


def test_re_attach_answers_only_the_approval_still_waiting() -> None:
    history = [
        NS(type="user.message", id="u1"),
        _idle("i0", "end_turn"),  # an earlier turn: must not end the follow
        NS(type="user.message", id="u2"),
        _ask("t1"),
        NS(type="user.tool_confirmation", id="c1", tool_use_id="t1"),
        _ask("t2"),
        _idle("i1", "requires_action"),
    ]
    client = FakeClient(
        history=history, streams=[[_message("m3", "done"), _idle("i3", "end_turn")]]
    )
    asked: list[str] = []
    shown: list[str] = []

    def approver(event: Any) -> Decision:
        asked.append(event.id)
        return Decision(allow=True)

    result = follow_session(
        client,  # type: ignore[arg-type]
        "s",
        attach=True,
        approver=approver,
        on_event=lambda event: shown.append(event.id),
    )
    assert asked == ["t2"]
    assert client.sent == [
        {"type": "user.tool_confirmation", "tool_use_id": "t2", "result": "allow"}
    ]
    assert shown == ["m3", "i3"]  # history is not reprinted on re-attach
    assert result.stop_reason == "end_turn"


def test_re_attach_to_a_finished_session_ends_at_once() -> None:
    client = FakeClient(
        history=[NS(type="user.message", id="u1"), _idle("i1", "end_turn")], streams=[]
    )
    result = follow_session(client, "s", attach=True)  # type: ignore[arg-type]
    assert result.stop_reason == "end_turn" and client.opened == 1


def test_a_reply_to_a_finished_session_waits_for_and_shows_the_answer() -> None:
    # The CLI's reply loop: the last turn ended, the person replies in the same session.
    # The idle that ended the last turn must not end the follow before the answer arrives.
    client = FakeClient(
        history=[NS(type="user.message", id="u1"), _idle("i1", "end_turn")],
        streams=[[_message("m2", "Understood."), _idle("i2", "end_turn")]],
    )
    shown: list[str] = []
    result = follow_session(
        client,  # type: ignore[arg-type]
        "s",
        send=[sessions.user_message("The email is valid.")],
        attach=True,
        on_text=shown.append,
    )
    assert client.sent[0]["type"] == "user.message"
    assert shown == ["Understood."]
    assert result.text == "Understood." and result.stop_reason == "end_turn"


def test_a_finished_workflow_thread_is_reported_with_its_own_events() -> None:
    reviewer_events = [
        NS(
            type="agent.mcp_tool_use",
            id="r1",
            mcp_server_name="eventdb",
            name="record_review",
            input={"proposal_id": "p1", "overall": 4, "recommendation": "accept"},
        )
    ]
    stream = [
        NS(type="workflow_run.created", id="w0", workflow_run_id="run1"),
        NS(
            type="session.thread_created",
            id="c1",
            session_thread_id="th1",
            agent_name="cfp-reviewer",
            workflow_run_id="run1",
        ),
        NS(type="session.thread_status_terminated", id="x1", session_thread_id="th1"),
        NS(
            type="workflow_run.status_ended",
            id="w1",
            workflow_run_id="run1",
            result=NS(type="completed"),
        ),
        _idle("i1", "end_turn"),
    ]
    client = FakeClient(history=[], streams=[stream])
    asked_for: list[tuple[str, str]] = []

    def thread_events(thread_id: str, *, session_id: str) -> list[NS]:
        asked_for.append((session_id, thread_id))
        return reviewer_events

    client.beta.sessions.threads = NS(events=NS(list=thread_events))
    shown: list[Any] = []
    result = follow_session(client, "s", on_event=shown.append)  # type: ignore[arg-type]
    reports = [e for e in shown if e.type == "concierge.thread_finished"]
    assert asked_for == [("s", "th1")]
    assert len(reports) == 1 and reports[0].events == reviewer_events
    assert reports[0].agent_name == "cfp-reviewer" and reports[0].workflow_run_id == "run1"
    assert result.workflow_runs == {"run1": "completed"}


def test_an_advisor_consultation_is_reported_with_its_threads_record() -> None:
    stream = [
        NS(
            type="session.thread_created",
            id="c1",
            session_thread_id="adv",
            agent_name="anthropic.advisor",
            workflow_run_id=None,
        ),
        NS(
            type="session.thread_status_terminated",
            id="x1",
            session_thread_id="adv",
            agent_name="anthropic.advisor",
        ),
        _idle("i1", "end_turn"),
    ]
    client = FakeClient(history=[], streams=[stream])
    record = NS(
        agent=NS(model="claude-opus-5-5", type="advisor"),
        stats=NS(duration_seconds=19.8),
        usage=NS(
            input_tokens=4,
            cache_read_input_tokens=0,
            cache_creation=NS(ephemeral_5m_input_tokens=11442, ephemeral_1h_input_tokens=0),
            output_tokens=1908,
            list_cost=NS(amount="10", currency="USD"),
        ),
    )
    asked_for: list[tuple[str, str]] = []

    def retrieve(thread_id: str, *, session_id: str) -> NS:
        asked_for.append((session_id, thread_id))
        return record

    client.beta.sessions.threads = NS(retrieve=retrieve)
    shown: list[Any] = []
    follow_session(client, "s", on_event=shown.append)  # type: ignore[arg-type]
    reports = [e for e in shown if e.type == "concierge.advice_given"]
    assert asked_for == [("s", "adv")]
    assert reports == [
        sessions.AdviceGiven(
            "adv",
            model="claude-opus-5-5",
            seconds=19.8,
            input_tokens=11446,
            output_tokens=1908,
            cost_cents=10,
        )
    ]
