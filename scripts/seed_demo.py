"""Give a real account real captures, by making it do real work.

DESIGN-BRIEF: nothing on screen may be fake. So this script writes no rows. It
signs in the way a person signs in, takes the bearer token that comes back, and
POSTs to `/api/demo/replay` with it -- the same endpoint the browser calls, the
same `run_session` the live socket drives, the same detector, solver and decider,
over the fixtures that ship in tests/fixtures. Every capture it produces was
produced by the pipeline, and it belongs to the organisation that asked for it
because the token said so.

What it deliberately does NOT do:

  * insert Capture or Session rows directly -- a hand-written row is a fake row
    however plausible it looks;
  * reassign the existing demo sessions. Those runs really were performed by an
    anonymous visitor against the demo tenant, and moving them to an account
    that did not run them would be rewriting history, which is the same lie in
    a different column.

By default it drives the ASGI application in this process, against the database
`READBACK_DATABASE_URL` names (sqlite:///./readback.db unless overridden), so no
server needs to be running. `--base-url` points it at a deployment instead, over
plain HTTP, which is the same request either way.

    PYTHONPATH=. python scripts/seed_demo.py --email ada@example.com --rounds 3
    READBACK_SEED_PASSWORD=... PYTHONPATH=. python scripts/seed_demo.py --base-url http://127.0.0.1:8000

The password is read from --password or READBACK_SEED_PASSWORD and is never
written to a file, never logged, and never passed anywhere but /api/auth/login.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from server.config import get_settings
from server.db import make_engine
from server.models import Capture, Organisation, Session
from server.stream.replay import fixture_dir

# The five recordings tests/test_pipeline_e2e.py drives end to end, in that
# order: a clean read, a substitution the operator can hear, one they cannot, an
# identifier split across three turns, and a conversation with no identifier in
# it at all. Deliberately the same five, so what this seeds is exactly what the
# suite proves the pipeline does. `--all-fixtures` widens it to every recording
# on disk, which today adds the three the detector is measured against rather
# than demonstrated with.
FIXTURES = ("iso_clean_single_turn", "iso_visible_substitution",
            "iso_blind_substitution", "iso_straddle_three_turns",
            "conversation_no_identifier")


def all_fixtures() -> list[str]:
    return sorted(p.stem for p in fixture_dir().glob("*.json"))


class _InProcess:
    """The application itself, driven through Starlette's test transport.

    Not a shortcut around the endpoint -- it is the endpoint: real routing, real
    dependencies, real lifespan (which is what creates the demo organisation),
    real database. The only thing missing is a socket.
    """

    def __init__(self) -> None:
        from fastapi.testclient import TestClient

        from server.main import app

        self._ctx = TestClient(app)
        self.client = self._ctx.__enter__()

    def post(self, path: str, json: dict, headers: dict | None = None):
        return self.client.post(path, json=json, headers=headers or {})

    def close(self) -> None:
        self._ctx.__exit__(None, None, None)


class _OverHttp:
    def __init__(self, base_url: str) -> None:
        import httpx

        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=120.0)

    def post(self, path: str, json: dict, headers: dict | None = None):
        return self.client.post(path, json=json, headers=headers or {})

    def close(self) -> None:
        self.client.close()


def sign_in(caller, email: str, password: str) -> tuple[str, str]:
    """Bearer token and organisation name, or a clear failure.

    Login, not signup. This script's job is to attribute work to an account that
    already exists; creating one would be inventing the operator as well as the
    data.
    """
    r = caller.post("/api/auth/login", {"email": email, "password": password})
    if r.status_code != 200:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        raise SystemExit(f"sign-in failed for {email}: {r.status_code} "
                         f"{body.get('message') or r.text[:200]}")
    payload = r.json()
    account = payload.get("account") or {}
    org = account.get("organisation") or {}
    return payload["token"], str(org.get("name") or org.get("id") or "unknown")


def counts_by_organisation() -> list[tuple[str, str, int, int]]:
    """(organisation name, id, sessions, captures) straight out of the database.

    Read here rather than inferred from the responses, because the number that
    matters is the one a dashboard query would find.
    """
    engine = make_engine(settings=get_settings())
    Factory = sessionmaker(bind=engine, expire_on_commit=False)
    rows: list[tuple[str, str, int, int]] = []
    with Factory() as db:
        for org in db.scalars(select(Organisation).order_by(Organisation.name)):
            sessions = int(db.scalar(
                select(func.count(Session.id))
                .where(Session.organisation_id == org.id)) or 0)
            captures = int(db.scalar(
                select(func.count(Capture.id))
                .join(Session, Capture.session_id == Session.id)
                .where(Session.organisation_id == org.id)) or 0)
            rows.append((org.name, str(org.id), sessions, captures))
    engine.dispose()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", default="ada@example.com")
    ap.add_argument("--password", default=os.environ.get("READBACK_SEED_PASSWORD", ""))
    ap.add_argument("--rounds", type=int, default=3,
                    help="passes over every fixture (default 3)")
    ap.add_argument("--base-url", default="",
                    help="drive a running deployment instead of this process")
    ap.add_argument("--answer-timeout-ms", type=int, default=200,
                    help="the dead-man timer for a question nobody answers")
    ap.add_argument("--all-fixtures", action="store_true",
                    help="every recording on disk, not just the demonstrated five")
    args = ap.parse_args()

    password = args.password or getpass.getpass(f"password for {args.email}: ")
    fixtures = all_fixtures() if args.all_fixtures else list(FIXTURES)
    if not fixtures:
        raise SystemExit(f"no fixtures under {fixture_dir()}")

    caller = _OverHttp(args.base_url) if args.base_url else _InProcess()
    try:
        token, org_name = sign_in(caller, args.email, password)
        headers = {"Authorization": f"Bearer {token}"}
        print(f"signed in as {args.email} -- organisation {org_name!r}")
        print(f"{len(fixtures)} fixtures x {args.rounds} rounds\n")

        produced = 0
        sessions: list[str] = []
        failures = 0
        for round_no in range(1, args.rounds + 1):
            for fixture in fixtures:
                r = caller.post("/api/demo/replay",
                                {"fixture": fixture, "speed": 0.0, "wait": True,
                                 "answer_timeout_ms": args.answer_timeout_ms},
                                headers)
                if r.status_code != 200:
                    failures += 1
                    print(f"  round {round_no}  {fixture:<34} FAILED "
                          f"{r.status_code} {r.text[:120]}")
                    continue
                body = r.json()
                n = int(body["counters"]["captures"])
                produced += n
                sessions.append(body["session_id"])
                print(f"  round {round_no}  {fixture:<34} {n} capture(s)")
    finally:
        caller.close()

    print(f"\n{len(sessions)} sessions ran, {produced} captures produced, "
          f"{failures} failed request(s)")

    # A replay produces no capture for the two fixtures that contain no
    # identifier, which is the correct outcome and not a seeding failure.
    print("\norganisation                             sessions  captures")
    for name, org_id, s, c in counts_by_organisation():
        print(f"  {name[:30]:<30} {org_id[:8]}  {s:>8}  {c:>8}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
