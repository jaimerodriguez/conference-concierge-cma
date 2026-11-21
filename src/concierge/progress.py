"""Live progress for any command that runs a session.

One renderer for every session-running command, so the output reads the same everywhere:
which agent is acting, what a tool call is doing in plain words, and what the grader said
and whether the person has to do anything. ``--verbose`` adds the raw tool names.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import PurePath
from typing import Any

from rich.console import Console
from rich.markup import escape

from concierge.sessions import ADVISOR_AGENT

_FILE_TOOLS = {"bash", "read", "write", "edit", "glob", "grep", "web_fetch", "web_search"}
_LEAD_IN = re.compile(
    r"^(an?\s+independent\s+grader|the\s+grader)\s+(has\s+)?"
    r"(found|reviewed|evaluated|checked|determined|says|said)\s+(that\s+)?",
    re.IGNORECASE,
)
_TRAILING_ASK = re.compile(r"\s*(please\s+(revise|fix|update|address)\b.*)$", re.IGNORECASE)
# "the following criteria are not fully met: - Daily review digest (partially met):"
_CRITERIA_HEADER = re.compile(
    r"^(the\s+)?following\s+criteria\s+(are|were)\s+not\s+(fully\s+)?met:\s*", re.IGNORECASE
)
_CRITERION_LABEL = re.compile(
    r"^-\s*[^:()]{1,80}\((partially\s+met|not\s+met)\):\s*", re.IGNORECASE
)
# Where the grader turns from what passed to what did not.
_SHORTFALL = re.compile(
    r"\b(falls?\s+short|is\s+missing|are\s+missing|lacks|there\s+is\s+no|has\s+no|"
    r"does\s+not|doesn't|fails?\s+to)\b",
    re.IGNORECASE,
)
_PATH_TOOLS = {"read": "reading", "write": "writing", "edit": "editing"}


def summarize_feedback(text: str, limit: int = 200) -> str:
    """Boil the grader's message to the agent down to the reason, in at most ``limit`` chars.

    The grader writes to the agent ("An independent grader found ... Please revise"), so the
    framing is dropped and the first sentences are kept. The full text is for --verbose.
    """
    cleaned = " ".join((text or "").split())
    cleaned = _TRAILING_ASK.sub("", cleaned)
    cleaned = _LEAD_IN.sub("", cleaned).strip()
    cleaned = _CRITERIA_HEADER.sub("", cleaned)
    cleaned = _CRITERION_LABEL.sub("", cleaned).strip()
    cleaned = _from_shortfall(cleaned)
    if not cleaned:
        return "(no reason given)"
    cleaned = cleaned[0].upper() + cleaned[1:]
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit]
    sentence_end = max(cut.rfind(". "), cut.rfind("; "))
    if sentence_end > limit // 2:
        return cut[: sentence_end + 1]
    return cut.rstrip(" ,;:") + "…"


def _from_shortfall(text: str) -> str:
    """Start at the sentence where the grader says what is wrong, skipping the praise.

    The grader often lists everything that passed before "It falls short on ...". Only the
    shortfall tells the person why the work went back.
    """
    match = _SHORTFALL.search(text)
    if not match:
        return text
    start = max(text.rfind(". ", 0, match.start()), text.rfind(": ", 0, match.start()))
    return text if start < 0 else text[start + 2 :]


def pretty_name(name: str) -> str:
    name = name.removeprefix("anthropic.")  # the built-in advisor is "anthropic.advisor"
    words = name.replace("-", " ").replace("_", " ").split()
    return " ".join("CFP" if word.lower() == "cfp" else word.capitalize() for word in words)


def pretty_model(model: str) -> str:
    """ "claude-opus-5-5" -> "Opus 5.5"; a dated suffix such as -20250929 is dropped."""
    parts = [
        p for p in model.removeprefix("claude-").split("-") if not (p.isdigit() and len(p) == 8)
    ]
    words = [p.capitalize() for p in parts if not p.isdigit()]
    version = ".".join(p for p in parts if p.isdigit())
    return " ".join([*words, version]) if version else " ".join(words) or model


def describe_advice(report: Any, lead: str, verbose: bool = False) -> str:
    """One line for a finished advisor consultation, from the advisor thread's record."""
    facts = [
        pretty_model(report.model) if report.model else None,
        f"{round(report.seconds)} s" if report.seconds is not None else None,
        f"${report.cost_cents / 100:.2f}" if report.cost_cents is not None else None,
    ]
    known = ", ".join(f for f in facts if f)
    line = f"advised the {lead}" + (f" ({known})" if known else "")
    if verbose and report.input_tokens is not None and report.output_tokens is not None:
        line += (
            f"; read {report.input_tokens:,} tokens of the {lead}'s conversation and wrote "
            f"{report.output_tokens:,} tokens of advice"
        )
    return line + f". The advice goes only to the {lead}; this client gets it encrypted."


def describe_tool(server: str | None, name: str, tool_input: dict[str, Any]) -> str | None:
    """Plain-language line for a tool call, or None for the generic file/shell tools."""
    get = tool_input.get
    if server == "eventdb":
        status = get("status")
        match name:
            case "list_proposals":
                return f"reading the {status} proposals" if status else "reading the proposals"
            case "get_proposal":
                return f"reading proposal {get('proposal_id', '')}".strip()
            case "record_review":
                detail = ", ".join(
                    str(part)
                    for part in (
                        f"score {get('overall')}" if get("overall") is not None else None,
                        get("recommendation"),
                    )
                    if part
                )
                return f"saving the review for {get('proposal_id', 'a proposal')}" + (
                    f" ({detail})" if detail else ""
                )
            case "set_proposal_status":
                return f"marking {get('proposal_id', 'a proposal')} as {get('status', '?')}"
            case "list_members":
                return "looking up members"
            case "record_perk":
                return f"recording a perk code for {get('member_id', 'a speaker')}"
            case "get_event":
                return "reading the event details"
            case "check_agenda_fit":
                ids = get("add_proposal_ids") or []
                if not ids:
                    return "checking that the accepted proposals fit in the evening"
                count = len(ids)
                proposals = "1 more proposal fits" if count == 1 else f"{count} more proposals fit"
                return f"checking whether {proposals} in the evening"
    if server == "calendar":
        match name:
            case "list_events":
                return "checking what is already on the calendar"
            case "find_free_slots":
                return "looking for free time slots"
            case "create_event":
                return f"booking {get('title', 'a slot')} in {get('room', 'a room')}"
    if server is None and name.lower() in _PATH_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("path")
        if path:
            return f"{_PATH_TOOLS[name.lower()]} {PurePath(str(path)).name}"
    if server is None and name.lower() in _FILE_TOOLS:
        return None
    label = f"{server}.{name}" if server else name
    return f"using {label}"


def _clock(value: Any) -> str:
    """ "2026-12-10T18:55" -> "18:55"; anything else unchanged."""
    text = str(value or "?")
    return text.split("T", 1)[1][:5] if "T" in text else text


_PERK_CALL = re.compile(r"/credits/api/codes\b")
_MEMBER_ID = re.compile(r'\\?"member_id\\?"\s*:\s*\\?"([^"\\]+)')
_AMOUNT = re.compile(r'\\?"amount_usd\\?"\s*:\s*(\d+)')


def perk_call(tool_name: str, tool_input: dict[str, Any]) -> tuple[str, int | None] | None:
    """(member id, amount) when a bash call issues one CloudCredits perk code, else None."""
    command = str(tool_input.get("command", "")) if tool_name == "bash" else ""
    if not _PERK_CALL.search(command):
        return None
    members = set(_MEMBER_ID.findall(command))
    if len(members) != 1 or not all(m.replace("_", "").isalnum() for m in members):
        return None  # a loop or several codes at once: show it as a plain command instead
    amount = _AMOUNT.search(command)
    return members.pop(), int(amount.group(1)) if amount else None


def describe_approval(
    server: str | None,
    name: str,
    tool_input: dict[str, Any],
    member_contact: Callable[[str], str | None] | None = None,
) -> str:
    """One plain question for a call waiting on the person, e.g. a calendar booking."""
    perk = perk_call(name, tool_input) if server is None else None
    if perk is not None:
        member_id, amount = perk
        speaker = member_contact(member_id) if member_contact else None
        who = f"{speaker} ({member_id})" if speaker else member_id
        worth = f" (${amount})" if amount else ""
        return f"Issue a CloudCredits perk code{worth} for {who}?"
    if server is None and name == "bash":
        command = " ".join(str(tool_input.get("command", "")).split())
        return f"Run this command? {command[:100]}" + ("…" if len(command) > 100 else "")
    if server == "calendar" and name == "create_event":
        return (
            f"Book '{tool_input.get('title', 'a slot')}' in {tool_input.get('room', 'a room')}, "
            f"{_clock(tool_input.get('starts_at'))}-{_clock(tool_input.get('ends_at'))}?"
        )
    action = describe_tool(server, name, tool_input) or f"run {name}"
    return f"Allow {action}?"


def first_sentence(text: str, limit: int = 110) -> str:
    """The opening of an agent message, on one line, for the live output."""
    line = " ".join(text.replace("*", "").replace("#", "").split())
    end = line.find(". ")
    if 0 < end < limit:
        return line[: end + 1]
    return line if len(line) <= limit else line[:limit].rstrip(" ,;:") + "…"


class Progress:
    """Callable for ``on_event``: prints one readable line per meaningful event."""

    def __init__(
        self,
        console: Console,
        *,
        lead: str,
        verbose: bool = False,
        max_rounds: int | None = None,
    ) -> None:
        self.console = console
        self.lead = lead
        self.verbose = verbose
        self.max_rounds = max_rounds
        self._threads: dict[str, str] = {}
        self._last: tuple[str, str] | None = None
        # Workflow runs (Guide 08): who is in each run, who is working right now, and which
        # reviewer saved the review of which proposal.
        self._phases: dict[str, str] = {}  # phase id -> name
        self._run_size: dict[str, int] = {}  # run id -> threads started so far
        self._run_threads: set[str] = set()
        self._working: set[str] = set()
        self._reviewed_by: dict[str, str] = {}  # proposal id -> reviewer label
        self._runs_ended = False

    # -- helpers -----------------------------------------------------------------

    def _who(self, event: Any) -> str:
        thread = getattr(event, "session_thread_id", None)
        return self._threads.get(thread, self.lead) if thread else self.lead

    def _say(self, who: str, text: str, style: str = "dim") -> None:
        if self._last == (who, text):
            return  # the same step repeated (many file tools in a row)
        self._last = (who, text)
        self.console.print(f"[{style}]\\[{escape(who)}][/{style}] {escape(text)}")

    def _round(self, iteration: int) -> str:
        total = f" of {self.max_rounds}" if self.max_rounds else ""
        return f"Grader, round {iteration + 1}{total}"

    # -- the callback ------------------------------------------------------------

    def __call__(self, event: Any) -> None:
        match event.type:
            case "session.thread_status_running" | "session.thread_status_idle":
                # Learn names here too: after a re-attach the thread_created events are old.
                if getattr(event, "agent_name", None) and event.session_thread_id:
                    self._threads.setdefault(event.session_thread_id, pretty_name(event.agent_name))
                if (
                    event.type == "session.thread_status_running"
                    and event.session_thread_id in self._run_threads
                    and event.session_thread_id not in self._working
                ):
                    self._working.add(event.session_thread_id)
                    count = len(self._working)
                    self._say(
                        self._who(event),
                        "started" + (f" ({count} running at once)" if count > 1 else ""),
                        "cyan",
                    )
            case "session.thread_created" if getattr(event, "agent_name", None) == ADVISOR_AGENT:
                # Guide 09: the platform starts an advisor thread for each consultation.
                self._threads[event.session_thread_id] = "Advisor"
                self._say(
                    self.lead,
                    "consulting its advisor, which reads the whole conversation so far "
                    "and replies with advice",
                    "cyan",
                )
            case "concierge.advice_given":
                self._say("Advisor", describe_advice(event, self.lead, self.verbose), "cyan")
            case "session.thread_created" if getattr(event, "workflow_run_id", None):
                # A run's threads all run the same agent, so number them: CFP Reviewer 1, 2...
                run = event.workflow_run_id
                self._run_size[run] = self._run_size.get(run, 0) + 1
                label = f"{pretty_name(event.agent_name)} {self._run_size[run]}"
                self._threads[event.session_thread_id] = label
                self._run_threads.add(event.session_thread_id)
                if self.verbose:
                    self._say("Workflow run", f"bringing in {label}", "magenta")
            case "session.thread_created":
                self._threads[event.session_thread_id] = pretty_name(event.agent_name)
                if self.verbose:
                    self._say(self.lead, f"bringing in {pretty_name(event.agent_name)}", "cyan")
            case "concierge.thread_finished":
                self._thread_finished(event)
            case "agent.thread_message_sent":
                target = pretty_name(event.to_agent_name) if event.to_agent_name else "a teammate"
                text = next((b.text for b in event.content if b.type == "text"), "")
                self._say(
                    self._who(event), f"asking the {target}: {first_sentence(text, 80)}", "cyan"
                )
            case "agent.thread_message_received":
                sender = event.from_agent_name or self._threads.get(event.from_session_thread_id)
                who = pretty_name(sender) if sender else "a teammate"
                text = next((b.text for b in event.content if b.type == "text"), "")
                if text.strip():
                    self._say(who, f"reported back: {first_sentence(text, 90)}", style="cyan")
                elif self.verbose:  # the advice is redacted; concierge.advice_given says more
                    self._say(who, "advice delivered [agent.thread_message_received, redacted]")
            case "workflow_run.created":
                for phase in getattr(event, "phases", None) or []:
                    self._phases[phase.id] = phase.name
                plan = getattr(event, "description", None)
                self._say(
                    self.lead,
                    f"starting a workflow run ({event.name})"
                    + (f": {first_sentence(plan, 100)}" if plan else ""),
                    style="magenta",
                )
            case "workflow_run.phase_started":
                name = self._phases.get(event.workflow_run_phase_id, "unnamed")
                self._say("Workflow run", f"phase started: {name}", "magenta")
            case "workflow_run.phase_ended" if self.verbose:
                name = self._phases.get(event.workflow_run_phase_id, "unnamed")
                self._say("Workflow run", f"phase ended: {name}", "magenta")
            case "workflow_run.error":
                self._say("Workflow run", f"error: {event.error.message}", "red")
            case "workflow_run.status_ended":
                self._runs_ended = True
                count = self._run_size.get(event.workflow_run_id, 0)
                threads = f" ({count} agent thread{'' if count == 1 else 's'})" if count else ""
                self._say(
                    self.lead, f"the workflow run ended: {event.result.type}{threads}", "magenta"
                )
            case "agent.mcp_tool_use" if _waits_for_person(event) and not self.verbose:
                pass  # the approval question says the same thing, so one line, not two
            case "agent.mcp_tool_use":
                text = self._reading_results(event) or describe_tool(
                    event.mcp_server_name, event.name, event.input
                )
                text = text or f"using {event.mcp_server_name}.{event.name}"
                if self.verbose:
                    text += f" [{event.mcp_server_name}.{event.name}]"
                self._say(self._who(event), text)
            case "agent.tool_use":
                text = describe_tool(None, event.name, event.input)
                if self.verbose:
                    self._say(self._who(event), f"tool {event.name}")
                elif text is not None:
                    self._say(self._who(event), text)  # shell and search tools say nothing useful
            case "span.outcome_evaluation_start":
                if self.verbose:
                    self.console.print(f"[green]{self._round(event.iteration)}:[/green] checking")
            case "span.outcome_evaluation_end":
                rounds = self.max_rounds or "?"
                self.console.print(
                    f"[green]{self._round(event.iteration)}:[/green] "
                    + _grade(event, rounds, self.verbose)
                )
            case "session.error":
                self.console.print(f"[red]Problem reported:[/red] {event.error.message}")

    # -- workflow runs -----------------------------------------------------------

    def _thread_finished(self, report: Any) -> None:
        """One line for a run thread that ended: what it saved, read from its own events."""
        who = self._threads.get(report.session_thread_id, pretty_name(report.agent_name))
        self._working.discard(report.session_thread_id)
        tool_calls = [e for e in report.events if e.type == "agent.mcp_tool_use"]
        if self.verbose:  # the thread's own tool calls, which the session stream never shows
            for call in report.events:
                if call.type == "agent.mcp_tool_use":
                    line = describe_tool(call.mcp_server_name, call.name, call.input)
                    self._say(who, f"{line} [{call.mcp_server_name}.{call.name}]")
                elif call.type == "agent.tool_use":
                    self._say(who, f"tool {call.name}")
        saved = [c for c in tool_calls if c.name == "record_review"]
        if saved:
            done = "; ".join(
                (describe_tool("eventdb", c.name, c.input) or "").replace("saving", "saved", 1)
                for c in saved
            )
            for call in saved:
                if call.input.get("proposal_id"):
                    self._reviewed_by[call.input["proposal_id"]] = who
        else:
            read = [c.input.get("proposal_id") for c in tool_calls if c.name == "get_proposal"]
            done = f"read {', '.join(p for p in read if p)} but saved no review" if read else ""
        for problem in (e for e in report.events if e.type == "session.error"):
            self._say(who, f"problem: {problem.error.message}", "red")
        left = len(self._working)
        status = f"{left} still running" if left else "the last one to finish"
        self._say(who, f"finished, {done}; {status}" if done else f"finished; {status}", "cyan")

    def _reading_results(self, event: Any) -> str | None:
        """Name the coordinator's reads after a run for what they are: collecting results."""
        if self._who(event) != self.lead or event.mcp_server_name != "eventdb":
            return None
        proposal = event.input.get("proposal_id")
        if event.name == "get_proposal" and proposal in self._reviewed_by:
            return f"reading the review {self._reviewed_by[proposal]} saved for {proposal}"
        if event.name == "list_proposals" and self._runs_ended:
            return f"{describe_tool('eventdb', event.name, event.input)} to collect the results"
        return None


def _waits_for_person(event: Any) -> bool:
    return getattr(event, "evaluated_permission", None) == "ask"


def _grade(event: Any, rounds: Any, verbose: bool) -> str:
    reason = summarize_feedback(event.explanation or "")
    match event.result:
        case "satisfied":
            line = "approved."
        case "needs_revision":
            line = (
                f"sent the work back. Reason: {reason}\n"
                "  The agent is revising on its own; there is nothing for you to do."
            )
        case "max_iterations_reached":
            line = (
                f"still not approved, and {rounds} rounds is the most the grader allows. The "
                "agent's last version is what you get, and it is unverified.\n"
                f"  Last reason: {reason}\n"
                "  Read it before relying on it, or run again to start a fresh attempt."
            )
        case "failed":
            line = (
                "could not grade it: the rubric does not fit what was produced.\n"
                f"  Reason: {reason}"
            )
        case "interrupted":
            line = "interrupted before it finished."
        case other:
            line = f"{other}. {reason}"
    if verbose and event.explanation and event.result != "satisfied":
        full = "\n    ".join(event.explanation.splitlines())
        line += f"\n  Full grader message:\n    {full}"
    return line
