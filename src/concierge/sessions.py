"""The session event loop shared by every flow in the demo.

A Managed Agents session is driven by events. This module opens the stream, follows it until
the work is done, and answers the two kinds of events that wait on *us*:

* tool calls paused for approval (permission policies, Guide 12), and
* custom tool calls that our own process must execute (used in phase 2a, Guide 20).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

import anthropic
from anthropic import Anthropic

from concierge.config import get_settings
from concierge.telemetry import get_tracer

# The session-scoped file listing needs this beta named explicitly.
MANAGED_AGENTS_BETA = "managed-agents-2026-04-01"


@dataclass(frozen=True)
class Decision:
    """The answer to a tool call that paused for approval."""

    allow: bool
    message: str | None = None  # shown to the agent when denied, so it can adjust


Approver = Callable[[Any], Decision]
CustomToolHandler = Callable[[str, dict[str, Any]], str]
EventCallback = Callable[[Any], None]


def deny_all(event: Any) -> Decision:
    """The safe default when nobody is watching: never approve on a person's behalf."""
    return Decision(allow=False, message="No one is available to approve this right now.")


@dataclass(frozen=True)
class SessionIssue:
    """One ``session.error``: its type tells what kind of problem it is, whatever the wording."""

    kind: str  # e.g. mcp_authentication_failed_error, credential_host_unreachable_error
    message: str
    mcp_server_name: str | None = None
    credential_id: str | None = None
    vault_id: str | None = None

    @classmethod
    def from_event(cls, event: Any) -> SessionIssue:
        error = event.error
        return cls(
            kind=str(getattr(error, "type", "unknown")),
            message=str(getattr(error, "message", error)),
            mcp_server_name=getattr(error, "mcp_server_name", None),
            credential_id=getattr(error, "credential_id", None),
            vault_id=getattr(error, "vault_id", None),
        )


@dataclass
class SessionResult:
    """What happened in one stretch of following a session."""

    session_id: str
    text: str = ""
    stop_reason: str | None = None  # end_turn, budget_reached, retries_exhausted, terminated...
    outcome_result: str | None = None  # satisfied, needs_revision, max_iterations_reached...
    outcome_explanation: str | None = None
    workflow_runs: dict[str, str] = field(default_factory=dict)  # run id -> how it ended
    issues: list[SessionIssue] = field(default_factory=list)  # session.error events, in order
    reconnects_exhausted: bool = False  # the stream kept closing before the session stopped

    @property
    def ok(self) -> bool:
        return self.stop_reason == "end_turn"


def console_url(session_id: str) -> str:
    """Link to the Console session viewer: transcript, tool calls, cost, threads. No setup."""
    workspace = get_settings().workspace
    return f"https://platform.claude.com/workspaces/{workspace}/sessions/{session_id}"


def budget(cents: int) -> dict[str, Any]:
    """Build a session budget.

    # Guide 12 · Approvals and budgets · Step 2: a hard dollar cap per session
    The amount is in minor units (cents) as a string: "50" is $0.50. At the cap the session
    pauses with stop_reason ``budget_reached``; it is not terminated.
    """
    return {"type": "limit", "max_list_cost": {"amount": str(cents), "currency": "USD"}}


def user_message(text: str) -> dict[str, Any]:
    return {"type": "user.message", "content": [{"type": "text", "text": text}]}


def _history_then_stream(
    client: Anthropic,
    session_id: str,
    stream: Iterable[Any],
    seen: set[str],
    answered: set[str],
    *,
    show_history: bool = True,
) -> Iterator[tuple[Any, bool, bool]]:
    """Yield ``(event, show, final_ok)`` for history not yet seen, then live events.

    The stream only delivers events emitted after it opens. A session created with
    ``initial_events`` (or fired by a deployment) is already running, and a stream can close
    mid-run, so we consolidate: read the history once, then continue with the live stream,
    skipping every event already processed (``seen``).

    ``answered`` gains every tool call the history already holds an answer for, so a call is
    never put to the person twice. ``final_ok`` is False for an idle event from history that
    a later status event superseded (an earlier turn), so it does not end the follow.
    """
    history = list(client.beta.sessions.events.list(session_id, order="asc"))
    last_status = next(
        (e.id for e in reversed(history) if e.type.startswith("session.status_")), None
    )
    for event in history:
        if event.type == "user.tool_confirmation":
            answered.add(event.tool_use_id)
        elif event.type == "user.custom_tool_result":
            answered.add(event.custom_tool_use_id)
    for event in history:
        if event.id in seen:
            continue
        seen.add(event.id)
        superseded = event.type.startswith("session.status_") and event.id != last_status
        yield event, show_history, not superseded
    for event in stream:
        event_id = getattr(event, "id", None)
        if event_id is not None:
            if event_id in seen:
                continue
            seen.add(event_id)
        yield event, True, True


def _live(stream: Iterable[Any], seen: set[str]) -> Iterator[tuple[Any, bool, bool]]:
    for event in stream:
        event_id = getattr(event, "id", None)
        if event_id is not None:
            seen.add(event_id)
        yield event, True, True


# How many times to reopen a stream that closed before the session stopped. A stream closes
# after a long quiet spell, for example while a person thinks about an approval.
MAX_RECONNECTS = 5


def follow_session(
    client: Anthropic,
    session_id: str,
    *,
    send: list[dict[str, Any]] | None = None,
    approver: Approver = deny_all,
    custom_tools: CustomToolHandler | None = None,
    on_text: Callable[[str], None] | None = None,
    on_event: EventCallback | None = None,
    include_history: bool = False,
    attach: bool = False,
) -> SessionResult:
    """Follow a session until its work is done, answering what waits on this client.

    Args:
        send: Events to send once the stream is open (stream first, then send).
        approver: Decides tool calls paused for approval. Defaults to denying everything.
        custom_tools: Executes custom tool calls and returns the result text.
        on_text: Called with each piece of agent text, for printing.
        on_event: Called with every event, for logging or a progress display.
        include_history: Also process events from before the stream opened. Use it when the
            session was started elsewhere (``initial_events`` or a scheduled deployment).
        attach: Re-attach to an existing session: read its history without printing it,
            answer anything still waiting (an approval, a custom tool call), then follow.

    If the stream closes before the session stops, it is reopened (up to ``MAX_RECONNECTS``
    times) and the missed events are caught up from the history.
    """
    result = SessionResult(session_id=session_id)
    open_runs: set[str] = set()  # workflow runs still in flight (Guide 08)
    answered: set[str] = set()
    seen: set[str] = set()
    text_parts: list[str] = []

    def handle(event: Any, show: bool, final_ok: bool) -> bool:
        """Process one event. Returns True when the session has stopped."""
        if show and on_event is not None:
            on_event(event)

        match event.type:
            case "agent.message":
                for block in event.content:
                    if block.type == "text":
                        text_parts.append(block.text)
                        if show and on_text is not None:
                            on_text(block.text)

            # Guide 12 · Approvals and budgets · Step 4: answer calls paused for approval.
            # Calls from subagent and workflow threads are cross-posted here too, so this
            # one stream is the only place we need to watch. `tool_use_id` is the EVENT id.
            case "agent.tool_use" | "agent.mcp_tool_use":
                needs_answer = getattr(event, "evaluated_permission", None) == "ask"
                if needs_answer and event.id not in answered:
                    answered.add(event.id)
                    decision = approver(event)
                    confirmation: dict[str, Any] = {
                        "type": "user.tool_confirmation",
                        "tool_use_id": event.id,
                        "result": "allow" if decision.allow else "deny",
                    }
                    if not decision.allow and decision.message:
                        confirmation["deny_message"] = decision.message
                    _send_answer(client, session_id, confirmation)

            # Guide 20 · Moving tools into your own sandbox · Step 4: custom tools run in
            # OUR process, which is where a secret can stay when no vault can inject it.
            case "agent.custom_tool_use":
                if event.id not in answered:
                    answered.add(event.id)
                    if custom_tools is None:
                        output, is_error = f"No handler for tool {event.name}.", True
                    else:
                        try:
                            output, is_error = custom_tools(event.name, dict(event.input)), False
                        except Exception as error:  # report the failure to the agent
                            output, is_error = f"{type(error).__name__}: {error}", True
                    _send_answer(
                        client,
                        session_id,
                        {
                            "type": "user.custom_tool_result",
                            "custom_tool_use_id": event.id,
                            "content": [{"type": "text", "text": output}],
                            "is_error": is_error,
                        },
                    )

            # Guide 11 · Grading work with outcomes · Step 3: read the grader's verdict.
            case "session.error":
                result.issues.append(SessionIssue.from_event(event))

            case "span.outcome_evaluation_end":
                result.outcome_result = event.result
                result.outcome_explanation = event.explanation

            # Guide 08 · Configuring your orchestrator for multi-agent · Step 5: track
            # workflow runs from created to ended. The work is not done while one is open.
            case "workflow_run.created":
                open_runs.add(event.workflow_run_id)
            case "workflow_run.status_ended":
                open_runs.discard(event.workflow_run_id)
                result.workflow_runs[event.workflow_run_id] = event.result.type

            case "session.status_idle" if final_ok:
                reason = event.stop_reason.type
                if reason == "requires_action":
                    return False  # waiting on us; the tool events above carry the answers
                if reason == "end_turn" and open_runs:
                    return False  # a workflow run is still going
                result.stop_reason = reason
                return True
            case "session.status_terminated" if final_ok:
                result.stop_reason = "terminated"
                return True
        return False

    with get_tracer().start_as_current_span("concierge.follow_session") as span:
        span.set_attribute("concierge.session_id", session_id)
        for attempt in range(MAX_RECONNECTS + 1):
            if attempt:
                print(
                    f"[concierge] the connection closed; reconnecting ({attempt} of "
                    f"{MAX_RECONNECTS})"
                )
                time.sleep(min(2**attempt, 10))
            with client.beta.sessions.events.stream(session_id) as stream:
                # Stream first, then send: events emitted before the stream opens are not
                # replayed.
                if attempt == 0 and send:
                    client.beta.sessions.events.send(session_id, events=send)
                if attempt or include_history or attach:
                    show = bool(attempt) or include_history
                    events = _history_then_stream(
                        client, session_id, stream, seen, answered, show_history=show
                    )
                else:
                    events = _live(stream, seen)
                if any(handle(event, show, final) for event, show, final in events):
                    break
        else:
            result.reconnects_exhausted = True
        span.set_attribute("concierge.stop_reason", result.stop_reason or "stream_closed")

    result.text = "\n".join(text_parts)
    return result


def _send_answer(client: Anthropic, session_id: str, event: dict[str, Any]) -> None:
    """Send a tool answer. The server may refuse one that arrives after its thread ended."""
    try:
        client.beta.sessions.events.send(session_id, events=[event])
    except anthropic.BadRequestError as error:
        print(f"[concierge] answer refused by the server: {error.message}")


def read_output_file(client: Anthropic, session_id: str, filename: str) -> bytes | None:
    """Download a file the agent wrote to ``/mnt/session/outputs/`` in this session."""
    import time

    # Output files appear a moment after the session goes idle, so retry briefly.
    for attempt in range(4):
        try:
            files = client.beta.files.list(scope_id=session_id, betas=[MANAGED_AGENTS_BETA])
        except anthropic.NotFoundError:
            return None  # a self-hosted server has no Files API (Guide 21)
        for file in files:
            if file.filename == filename or file.filename.endswith(f"/{filename}"):
                return client.beta.files.download(file.id).read()
        time.sleep(1.5 * (attempt + 1))
    return None
