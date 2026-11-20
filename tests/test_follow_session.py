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
