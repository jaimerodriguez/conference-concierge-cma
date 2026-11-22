"""The live output says who is acting, what a tool does, and what the grader means."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from rich.console import Console
from typer.testing import CliRunner

from concierge import cli
from concierge.progress import Progress, describe_tool, pretty_model
from concierge.sessions import AdviceGiven


def _render(events: list[NS], **kwargs: object) -> str:
    console = Console(record=True, width=120, force_terminal=False)
    progress = Progress(console, lead="Program Chair", **kwargs)  # type: ignore[arg-type]
    for event in events:
        progress(event)
    return console.export_text()


def test_tool_calls_are_described_in_plain_language() -> None:
    assert describe_tool("eventdb", "list_proposals", {"status": "submitted"}) == (
        "reading the submitted proposals"
    )
    assert (
        describe_tool(
            "eventdb",
            "record_review",
            {"proposal_id": "p1", "overall": 4.2, "recommendation": "accept"},
        )
        == "saving the review for p1 (score 4.2, accept)"
    )
    assert describe_tool("calendar", "create_event", {"title": "Talk", "room": "A"}) == (
        "booking Talk in A"
    )
    assert describe_tool("eventdb", "check_agenda_fit", {"add_proposal_ids": ["a", "b"]}) == (
        "checking whether 2 more proposals fit in the evening"
    )
    assert describe_tool("eventdb", "check_agenda_fit", {}) == (
        "checking that the accepted proposals fit in the evening"
    )
    assert describe_tool(None, "bash", {}) is None  # generic sandbox tools collapse
    assert describe_tool("other", "thing", {}) == "using other.thing"


def test_lines_name_the_agent_and_drop_shell_noise() -> None:
    created = NS(type="session.thread_created", session_thread_id="t1", agent_name="cfp-reviewer")
    review = NS(
        type="agent.mcp_tool_use",
        mcp_server_name="eventdb",
        name="get_proposal",
        input={"proposal_id": "p1"},
        session_thread_id="t1",
    )
    noise = [
        NS(type="agent.tool_use", name=name, input={}, session_thread_id=None)
        for name in ("glob", "bash", "grep")
    ]
    write = NS(
        type="agent.tool_use",
        name="write",
        input={"file_path": "/mnt/session/outputs/digest.md"},
        session_thread_id=None,
    )
    text = _render([created, review, *noise, write])
    assert "[CFP Reviewer] reading proposal p1" in text
    assert "[Program Chair] writing digest.md" in text
    assert "working with files" not in text and "glob" not in text and "bringing in" not in text
    assert "tool glob" in _render(noise[:1], verbose=True)


def test_grader_feedback_is_summarized_not_dumped() -> None:
    from concierge.progress import summarize_feedback

    message = (
        "An independent grader found that the digest says there are no proposals, but three "
        "reviews were recorded 30 minutes ago. Please revise your work so the digest lists "
        "them and removes the claim that nothing was reviewed in this run."
    )
    short = summarize_feedback(message)
    assert short.startswith("The digest says there are no proposals")
    assert "independent grader" not in short and "Please revise" not in short
    assert len(summarize_feedback("x" * 500)) <= 201


def test_grader_lines_say_what_happened_and_what_to_do() -> None:
    revise = NS(
        type="span.outcome_evaluation_end",
        iteration=0,
        result="needs_revision",
        explanation="The digest is missing the Not covered section. Please revise.",
    )
    done = NS(type="span.outcome_evaluation_end", iteration=1, result="satisfied", explanation="")
    last = NS(
        type="span.outcome_evaluation_end",
        iteration=2,
        result="max_iterations_reached",
        explanation="The table is too long.",
    )
    text = _render([revise, done, last], max_rounds=3)
    assert "Grader, round 1 of 3: sent the work back. Reason: The digest is missing the Not" in text
    assert "revising on its own" in text and "nothing for you to do" in text
    assert "Grader, round 2 of 3: approved." in text
    assert "3 rounds is the most the grader allows" in text and "unverified" in text
    assert "Full grader message" not in text
    assert "Full grader message" in _render([revise], verbose=True)


@pytest.fixture
def review_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(cli, "_client", lambda: object())
    monkeypatch.setattr(
        "concierge.review.run_scheduled_review_now",
        lambda client, on_event=None: (
            calls.append("run")
            or NS(
                session_id="s",
                text="",
                ok=True,
                stop_reason="end_turn",
                outcome_result=None,
                outcome_explanation=None,
                workflow_runs={},
                issues=[],
            )
        ),
    )
    monkeypatch.setattr("concierge.sessions.read_output_file", lambda *a, **k: None)
    monkeypatch.setattr(cli, "shutdown_telemetry", lambda: None)
    return calls


def test_review_run_skips_when_nothing_is_waiting(
    review_calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("concierge.services.store.Store.list_proposals", lambda self, **kw: [])
    result = CliRunner().invoke(cli.app, ["review", "run"])
    assert result.exit_code == 0 and review_calls == []
    assert "0 proposals waiting" in result.output and "--force" in result.output
    forced = CliRunner().invoke(cli.app, ["review", "run", "--force"])
    assert review_calls == ["run"] and "Starting the daily review (budget up to $" in forced.output


def test_review_run_reports_the_count_and_starts(
    review_calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "concierge.services.store.Store.list_proposals", lambda self, **kw: [{}, {}, {}]
    )
    result = CliRunner().invoke(cli.app, ["review", "run"])
    assert "3 proposals waiting for review" in result.output
    assert review_calls == ["run"]


def test_start_state_is_added_to_the_direct_run_kickoff() -> None:
    from pathlib import Path

    from concierge.review import load_review_kickoff

    managed = Path(__file__).resolve().parents[1] / "managed"
    plain = load_review_kickoff(managed)[0]["description"]
    assert "START STATE" in plain  # the agent records it itself on a scheduled run
    stated = load_review_kickoff(managed, ["p-1", "p-2"])[0]["description"]
    assert "2 submitted proposal(s): p-1, p-2" in stated
    empty = load_review_kickoff(managed, [])[0]["description"]
    assert "0 submitted proposal(s): none" in empty
    assert "START STATE" in load_review_kickoff(managed)[0]["description"]  # source not mutated


def test_grader_summary_skips_the_praise_and_leads_with_the_shortfall() -> None:
    from concierge.progress import summarize_feedback

    message = (
        "An independent grader found the following criteria are not fully met:\n\n"
        "- Daily review digest (partially met): The digest meets these points. It is a single "
        "file. The table has both ids. It falls short on two required sections. (1) There is no "
        "summary. (2) There is no top-three section.\n\nPlease revise your work."
    )
    short = summarize_feedback(message)
    assert short.startswith("It falls short on two required sections.")
    assert "meets these points" not in short and "partially met" not in short


def test_a_reviewers_reply_is_shown_under_its_name() -> None:
    reply = NS(
        type="agent.thread_message_received",
        from_agent_name="cfp-reviewer",
        from_session_thread_id="t1",
        content=[NS(type="text", text="**Both reviews are recorded.** prop_1: 4.3 accept")],
    )
    text = _render([reply])
    assert "[CFP Reviewer] reported back: Both reviews are recorded." in text


def test_the_review_task_names_every_part_of_the_digest() -> None:
    from pathlib import Path

    from concierge.review import load_review_kickoff

    managed = Path(__file__).resolve().parents[1] / "managed"
    task = load_review_kickoff(managed)[0]["description"]
    for part in ("one-paragraph summary", "Top three", "Respectful", "Not covered"):
        assert part in task
    assert "Wait for each reviewer's reply" in task


@pytest.fixture
def agenda_calls(monkeypatch: pytest.MonkeyPatch, settings) -> list[tuple[str, str | None]]:  # type: ignore[no-untyped-def]
    """Fake build_agenda: records (instruction, session_id), says two things, books nothing."""
    calls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(cli, "get_settings", lambda: settings)  # a temp DB, never the real one

    def fake_build(client, instruction, *, approver, on_text, on_event, session_id=None):  # type: ignore[no-untyped-def]
        calls.append((instruction, session_id))
        on_event(NS(type="agent.message", content=[]))
        on_text("Asking the scheduler now. It will book the slots.")
        on_text("## Done\n\nThe agenda is booked. Which talk should close the evening?")
        return NS(
            session_id=session_id or "sesn_new",
            text="",
            ok=True,
            stop_reason="end_turn",
            outcome_result=None,
            outcome_explanation=None,
            workflow_runs={},
            issues=[],
        )

    monkeypatch.setattr(cli, "_client", lambda: object())
    monkeypatch.setattr("concierge.review.build_agenda", fake_build)
    monkeypatch.setattr(cli, "shutdown_telemetry", lambda: None)
    return calls


def test_agenda_default_breaks_ties_and_says_when_nothing_was_booked(
    agenda_calls: list[tuple[str, str | None]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    result = CliRunner().invoke(cli.app, ["agenda", "build"])
    assert result.exit_code == 0
    instruction, session = agenda_calls[0]
    assert "variety of tracks and speakers" in instruction and "do not stop to ask" in instruction
    assert session is None
    assert "Nothing was booked" in result.output
    assert "agenda build --session sesn_new" in result.output


def test_agenda_replies_continue_the_same_session(
    agenda_calls: list[tuple[str, str | None]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    result = CliRunner().invoke(cli.app, ["agenda", "build"], input="Take prop_1 and prop_2\n\n")
    assert result.exit_code == 0
    assert [call[1] for call in agenda_calls] == [None, "sesn_new"]
    assert agenda_calls[1][0] == "Take prop_1 and prop_2"
    assert len(agenda_calls) == 2  # the empty reply ended it


def test_agenda_session_option_resumes_with_the_reply(
    agenda_calls: list[tuple[str, str | None]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    result = CliRunner().invoke(
        cli.app, ["agenda", "build", "--session", "sesn_old", "Take prop_1 and prop_2"]
    )
    assert result.exit_code == 0 and "Continuing sesn_old" in result.output
    assert agenda_calls == [("Take prop_1 and prop_2", "sesn_old")]
    attach = CliRunner().invoke(cli.app, ["agenda", "build", "--session", "sesn_old"])
    assert attach.exit_code == 0 and agenda_calls[-1] == (None, "sesn_old")  # re-attach only


def test_a_closed_stream_is_explained_not_shown_as_stopped_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "shutdown_telemetry", lambda: None)
    console = Console(record=True, width=200, force_terminal=False)
    monkeypatch.setattr(cli, "console", console)
    cli._finish(
        NS(
            session_id="s",
            ok=False,
            stop_reason=None,
            outcome_result=None,
            workflow_runs={},
            issues=[],
        )
    )
    text = console.export_text()
    assert "Stopped: None" not in text and "Lost the connection" in text
    assert "agenda build --session s" in text


def test_approval_questions_are_one_plain_line() -> None:
    from concierge.progress import describe_approval

    booking = {
        "title": "Break",
        "room": "Main Hall",
        "starts_at": "2026-12-10T19:20",
        "ends_at": "2026-12-10T19:30",
    }
    assert describe_approval("calendar", "create_event", booking) == (
        "Book 'Break' in Main Hall, 19:20-19:30?"
    )
    assert describe_approval("other", "thing", {}) == "Allow using other.thing?"


def _booking(title: str) -> NS:
    return NS(
        mcp_server_name="calendar",
        name="create_event",
        input={"title": title, "room": "Main Hall", "starts_at": "T18:30", "ends_at": "T18:55"},
    )


def test_a_approves_the_rest_and_a_reason_is_asked_only_on_no(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = Console(record=True, width=200, force_terminal=False)
    monkeypatch.setattr(cli, "console", console)
    answers = iter(["n", "too early", "a"])
    asked: list[str] = []

    def prompt(text: str, **kwargs: object) -> str:
        asked.append(text)
        return next(answers)

    monkeypatch.setattr(cli.typer, "prompt", prompt)
    approve = cli._AskPerson()
    first = approve(_booking("One"))
    assert not first.allow and first.message == "too early"
    assert approve(_booking("Two")).allow and approve(_booking("Three")).allow
    assert len(asked) == 3  # Three was approved by the earlier "a", without a question
    text = console.export_text()
    assert "Book 'One' in Main Hall, 18:30-18:55?" in text
    assert "Approved (you said yes to all): Book 'Three'" in text
    assert '"room"' not in text  # the raw JSON is for --verbose


def test_a_call_waiting_for_approval_is_not_also_a_progress_line() -> None:
    running = NS(
        type="session.thread_status_running", session_thread_id="t2", agent_name="scheduler"
    )
    ask = NS(
        type="agent.mcp_tool_use",
        mcp_server_name="calendar",
        name="create_event",
        input={"title": "Break", "room": "Main Hall"},
        evaluated_permission="ask",
        session_thread_id="t2",
    )
    lookup = NS(
        type="agent.mcp_tool_use",
        mcp_server_name="calendar",
        name="list_events",
        input={},
        evaluated_permission="allow",
        session_thread_id="t2",
    )
    text = _render([running, ask, lookup])
    assert "booking Break" not in text  # the approval question covers it
    assert "[Scheduler] checking what is already on the calendar" in text  # name from status


def test_an_advisor_consultation_shows_when_and_what_it_cost() -> None:
    created = NS(
        type="session.thread_created",
        session_thread_id="t3",
        agent_name="anthropic.advisor",
        workflow_run_id=None,
    )
    reply = NS(  # the advice itself is redacted on the stream
        type="agent.thread_message_received",
        from_agent_name="anthropic.advisor",
        from_session_thread_id="t3",
        content=[NS(type="redacted")],
    )
    done = AdviceGiven(
        "t3",
        model="claude-opus-5-5",
        seconds=19.8,
        input_tokens=11446,
        output_tokens=1908,
        cost_cents=10,
    )
    text = _render([created, reply, done])
    assert "[Program Chair] consulting its advisor" in text
    assert "[Advisor] advised the Program Chair (Opus 5.5, 20 s, $0.10)" in text
    assert "goes only to the Program Chair" in text
    assert "11,446" not in text and "redacted" not in text  # token counts are for --verbose
    verbose = _render([created, reply, done], verbose=True)
    assert "read 11,446 tokens of the Program Chair's conversation" in verbose
    assert "[agent.thread_message_received, redacted]" in verbose


def test_an_unreadable_advisor_record_still_gets_a_line() -> None:
    text = _render([AdviceGiven("t3")])
    assert "[Advisor] advised the Program Chair. The advice goes only to" in text


def test_model_ids_read_as_names() -> None:
    assert pretty_model("claude-opus-5-5") == "Opus 5.5"
    assert pretty_model("claude-sonnet-4-5-20250929") == "Sonnet 4.5"


def test_agenda_shows_one_line_while_working_and_the_last_message_in_full(
    agenda_calls: list[tuple[str, str | None]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    result = CliRunner().invoke(cli.app, ["agenda", "build"])
    assert result.exit_code == 0, result.output
    assert "[Program Chair] Asking the scheduler now." in result.output
    assert "It will book the slots" not in result.output  # only the first sentence live
    assert "Which talk should close the evening?" in result.output  # last one in full
    assert "Calendar: 0 events (0 requested in this run). Perk codes: 0 issued." in result.output


_PERK = (
    'curl -sS -X POST "https://demo.test/credits/api/codes" -H "X-Api-Key: $CLOUDCREDITS_API_KEY"'
    ' -H "Content-Type: application/json" -d \'{"member_id": "mem_1", "amount_usd": 50}\''
)


def test_a_perk_code_call_is_asked_in_plain_words() -> None:
    from concierge.progress import describe_approval

    emails = {"mem_1": "priya@example.com"}.get
    assert describe_approval(None, "bash", {"command": _PERK}, emails) == (
        "Issue a CloudCredits perk code ($50) for priya@example.com (mem_1)?"
    )
    loop = (
        'for m in mem_1 mem_2; do curl "https://x/credits/api/codes"'
        ' -d "{\\"member_id\\": \\"$m\\"}"; done'
    )
    assert describe_approval(None, "bash", {"command": loop}).startswith("Run this command? for m")


def test_a_covers_the_remaining_perk_codes_but_never_other_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = Console(record=True, width=200, force_terminal=False)
    monkeypatch.setattr(cli, "console", console)
    monkeypatch.setattr(cli, "_member_email", lambda member_id: None)
    answers = iter(["a", "n", ""])
    monkeypatch.setattr(cli.typer, "prompt", lambda text, **kw: next(answers))
    approve = cli._AskPerson()

    def bash(command: str) -> NS:
        return NS(name="bash", input={"command": command})

    assert approve(bash(_PERK)).allow
    assert approve(bash(_PERK.replace("mem_1", "mem_2"))).allow  # no question asked
    assert not approve(bash("rm -rf /tmp/x")).allow  # "a" did not cover this; it was asked
    text = console.export_text()
    assert "Approved (you said yes to all): Issue a CloudCredits perk code ($50) for mem_2" in text
    assert "Run this command? rm -rf /tmp/x" in text and "X-Api-Key" not in text


def test_a_workflow_run_shows_each_reviewer_working_in_parallel() -> None:
    from concierge.sessions import ThreadFinished

    def created(thread: str) -> NS:
        return NS(
            type="session.thread_created",
            session_thread_id=thread,
            agent_name="cfp-reviewer",
            workflow_run_id="run1",
        )

    def running(thread: str) -> NS:
        return NS(
            type="session.thread_status_running",
            session_thread_id=thread,
            agent_name="cfp-reviewer",
        )

    def finished(thread: str, proposal: str, score: float) -> ThreadFinished:
        saved = NS(
            type="agent.mcp_tool_use",
            mcp_server_name="eventdb",
            name="record_review",
            input={"proposal_id": proposal, "overall": score, "recommendation": "waitlist"},
        )
        return ThreadFinished(thread, "cfp-reviewer", "run1", [saved])

    events = [
        NS(
            type="workflow_run.created",
            name="Daily proposal review",
            description="One reviewer per proposal, in parallel.",
            phases=[NS(id="ph1", name="Review")],
        ),
        NS(type="workflow_run.phase_started", workflow_run_phase_id="ph1"),
        created("a"),
        created("b"),
        running("a"),
        running("b"),
        finished("b", "p2", 3.6),
        finished("a", "p1", 2.4),
        NS(type="workflow_run.status_ended", workflow_run_id="run1", result=NS(type="completed")),
        NS(
            type="agent.mcp_tool_use",
            mcp_server_name="eventdb",
            name="get_proposal",
            input={"proposal_id": "p1"},
            session_thread_id=None,
        ),
    ]
    text = _render(events)
    assert "starting a workflow run (Daily proposal review): One reviewer" in text
    assert "[Workflow run] phase started: Review" in text
    assert "[CFP Reviewer 2] started (2 running at once)" in text
    assert (
        "[CFP Reviewer 2] finished, saved the review for p2 (score 3.6, waitlist); 1 still" in text
    )
    assert (
        "[CFP Reviewer 1] finished, saved the review for p1 (score 2.4, waitlist); the last" in text
    )
    assert "the workflow run ended: completed (2 agent threads)" in text
    assert "[Program Chair] reading the review CFP Reviewer 1 saved for p1" in text
    assert "bringing in" not in text  # thread creation is for --verbose
