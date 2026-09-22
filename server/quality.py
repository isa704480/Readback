"""How right the agent is: measured from traffic, and measured against truth.

Two instruments, because they answer different questions and neither can stand
in for the other.

TRAFFIC METRICS (`metrics`). Live calls have no ground truth -- nobody tells the
system what the caller actually meant -- so these are the proxies a voice-agent
team watches in production: how often a capture was written without speaking,
how often it asked, how often it handed over, how long it took. One of them is
close to a real accuracy signal and is the reason this module exists:

    question necessity.  When the agent asks about one character and a person
    answers, the answer IS ground truth for that position. If it differs from
    what the recogniser heard, the doubt was right and the question saved a
    wrong write. If it matches, the recogniser had it and the interruption was
    unnecessary. The ratio is the precision of the agent's doubt.

BENCHMARK (`run_benchmark`). The recorded fixtures carry `truth`, so each can be
replayed through the same runner the microphone uses and the result compared
with what was actually said. A simulated person answers every question
correctly, so a wrong result is the pipeline's, not the answerer's. It is a
regression check on a small corpus, not a statistical estimate, and the result
says so in `note`.
"""

from __future__ import annotations

import statistics
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session as SASession

from server.models import Capture, QuestionEvent, Session

# A window never reads more than this many rows into memory. Past it the
# figures are computed on the newest rows and `truncated` says so.
MAX_ROWS: Final = 100_000


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _pct(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    k = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return int(ordered[k])


def metrics(db: SASession, since: datetime, *, org_id: uuid.UUID | None = None,
            source: str | None = None) -> dict[str, Any]:
    """Traffic quality since `since`, optionally for one organisation and/or
    one source ("live" or "replay")."""
    session_filter = [Session.started_at >= since]
    if org_id is not None:
        session_filter.append(Session.organisation_id == org_id)
    if source is not None:
        session_filter.append(Session.source == source)

    caps = db.execute(
        select(Capture.format_type, Capture.status, Capture.silent, Capture.corrected,
               Capture.questions_asked, Capture.handed_over, Capture.latency_ms,
               Capture.created_at)
        .join(Session, Capture.session_id == Session.id)
        .where(*session_filter)
        .order_by(Capture.created_at.desc())
        .limit(MAX_ROWS + 1)).all()
    truncated = len(caps) > MAX_ROWS
    caps = caps[:MAX_ROWS]

    total = len(caps)
    by_status = Counter(c.status for c in caps)
    committed = [c for c in caps if c.status == "committed"]
    silent_commits = sum(1 for c in committed if c.silent)
    silent_repairs = sum(1 for c in committed if c.silent and c.corrected)
    asked = sum(1 for c in caps if c.questions_asked > 0)
    handed = sum(1 for c in caps if c.handed_over)
    latencies = [c.latency_ms for c in committed if c.latency_ms is not None]

    per_format: dict[str, list[Any]] = defaultdict(list)
    per_day: dict[str, list[Any]] = defaultdict(list)
    for c in caps:
        per_format[c.format_type].append(c)
        per_day[c.created_at.date().isoformat()].append(c)

    def block(rows: list[Any]) -> dict[str, Any]:
        done = [r for r in rows if r.status == "committed"]
        return {
            "captures": len(rows),
            "committed": len(done),
            "silent_commit_rate": _rate(sum(1 for r in done if r.silent), len(done)),
            "asked_rate": _rate(sum(1 for r in rows if r.questions_asked > 0), len(rows)),
            "handover_rate": _rate(sum(1 for r in rows if r.handed_over), len(rows)),
        }

    # Questions, joined to the capture they were about so the answer can be
    # compared with what the recogniser heard at that position.
    qrows = db.execute(
        select(QuestionEvent.spoken, QuestionEvent.answered,
               QuestionEvent.answer_in_grammar, QuestionEvent.answer_char,
               QuestionEvent.position, QuestionEvent.resolution_ms, Capture.heard_value)
        .join(Capture, QuestionEvent.capture_id == Capture.id)
        .join(Session, QuestionEvent.session_id == Session.id)
        .where(*session_filter)
        .limit(MAX_ROWS)).all()
    answered = [q for q in qrows if q.answered]
    judged = [q for q in answered
              if q.answer_char and 0 <= q.position < len(q.heard_value or "")]
    needed = sum(1 for q in judged if q.heard_value[q.position] != q.answer_char.upper())
    resolution = [q.resolution_ms for q in answered if q.resolution_ms is not None]

    regimes = Counter(r or "unknown" for r in db.scalars(
        select(Session.confidence_regime).where(*session_filter)))

    return {
        "since": since.isoformat(),
        "truncated": truncated,
        "sessions": sum(regimes.values()),
        "captures": {"total": total, "committed": by_status.get("committed", 0),
                     "flagged": by_status.get("flagged", 0),
                     "unverified": by_status.get("unverified", 0)},
        "rates": {
            # Of what was written, how much was written without a word.
            "silent_commit_rate": _rate(silent_commits, len(committed)),
            # Of what was written, how much the format repaired without asking.
            "silent_repair_rate": _rate(silent_repairs, len(committed)),
            "asked_rate": _rate(asked, total),
            "handover_rate": _rate(handed, total),
            "flag_rate": _rate(by_status.get("flagged", 0), total),
            "questions_per_capture": (round(sum(c.questions_asked for c in caps) / total, 3)
                                      if total else None),
        },
        "latency_ms": {"p50": _pct(latencies, 0.5), "p95": _pct(latencies, 0.95),
                       "n": len(latencies)},
        "questions": {
            "asked": len(qrows),
            "spoken": sum(1 for q in qrows if q.spoken),
            "answered_rate": _rate(len(answered), len(qrows)),
            "in_grammar_rate": _rate(sum(1 for q in answered if q.answer_in_grammar),
                                     len(answered)),
            # The precision of the agent's doubt -- see the module docstring.
            "judged": len(judged),
            "needed_rate": _rate(needed, len(judged)),
            "unnecessary_rate": _rate(len(judged) - needed, len(judged)),
            "resolution_ms_p50": _pct(resolution, 0.5),
        },
        "by_format": [{"format": f, **block(rows)} for f, rows in sorted(per_format.items())],
        "by_day": [{"day": d, **block(rows)} for d, rows in sorted(per_day.items())],
        "regimes": dict(regimes),
    }


# --------------------------------------------------------------- benchmark --

def _spoken(char: str) -> str:
    """How a person answers a one-character question: NATO for letters, the
    plain digit word for digits. The runner parses the answer under the same
    grammar a real caller's goes through."""
    from server.readback.question import NATO, SAY

    up = char.upper()
    return (NATO.get(up) or SAY.get(up) or up).lower()


async def run_benchmark() -> dict[str, Any]:
    """Replay every fixture with a correct human and score it against truth."""
    from server.pipeline import events as ev
    from server.pipeline.runner import Question, RunnerConfig, run_session
    from server.pipeline.store import NullStore
    from server.stream.replay import ReplaySource, load_all
    from server.stream.source import SourceConfig

    results: list[dict[str, Any]] = []
    for fx in load_all():
        truth = (fx.truth or {}).get("value")
        expect = fx.expect or {}

        async def human(q: Question, _truth: str | None = truth) -> str | None:
            if _truth is None or not 0 <= q.position < len(_truth):
                return None
            return _spoken(_truth[q.position])

        stream = ev.EventStream()
        summary = await run_session(
            ReplaySource(fx, speed=0.0, config=SourceConfig()), stream,
            store=NullStore(), answerer=human,
            config=RunnerConfig(session_id=f"benchmark-{fx.name}", source_label="replay"),
        )
        committed = [c for c in summary.captures if c.status == "committed"]
        values = [c.final_value for c in committed]
        asks = [e.data.get("position") for e in stream.history if e.type == ev.QUESTION_ASK]

        if truth is None:
            correct = not values
            silent_wrong = sum(1 for c in committed if c.silent)
        else:
            correct = bool(values) and all(v == truth for v in values)
            silent_wrong = sum(1 for c in committed if c.silent and c.final_value != truth)
        want_ask = expect.get("ask_position")
        results.append({
            "fixture": fx.name,
            "expected": truth,
            "written": values,
            "correct": correct,
            "silent_wrong": silent_wrong,
            "questions": len(asks),
            "question_positions": asks,
            "expected_question_position": want_ask,
            "asked_right_position": (None if want_ask is None else want_ask in asks),
            "silent": bool(committed) and all(c.silent for c in committed),
        })

    n = len(results)
    with_ask = [r for r in results if r["asked_right_position"] is not None]
    return {
        "fixtures": n,
        "correct": sum(1 for r in results if r["correct"]),
        "accuracy": _rate(sum(1 for r in results if r["correct"]), n),
        "silent_wrong": sum(r["silent_wrong"] for r in results),
        "questions": sum(r["questions"] for r in results),
        "questions_at_right_position": sum(1 for r in with_ask if r["asked_right_position"]),
        "questions_expected": len(with_ask),
        "median_questions": statistics.median([r["questions"] for r in results]) if n else None,
        "results": results,
        "note": (f"{n} recorded fixtures with known truth, replayed through the live "
                 "runner with a person who answers every question correctly. A "
                 "regression check on a small corpus, not a statistical accuracy "
                 "estimate -- docs/EXPERIMENT.md holds that."),
    }
