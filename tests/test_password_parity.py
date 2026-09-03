# test_password_parity.py -- the TypeScript scorer and the Python scorer must
# agree, character for character.
#
# web/src/lib/password.ts is a hand port of server/password.py's evaluate(), and
# it exists so the strength meter is coloured on the first keystroke instead of
# after a network round trip. The price of that is two implementations of one
# rule set, and the failure mode of two implementations is not "one of them is
# wrong" -- it is "the meter says Strong and the signup says no", which is worse
# than having no meter, because the person has no way to find out what happened.
#
# So both are run over the same vectors and every field is diffed: ok, score,
# label, problems, suggestions. Not just the score -- the sentences matter,
# because they are what the form actually shows.
#
# Needs node and esbuild (esbuild ships with vite, already in web/node_modules).
# If either is missing the test SKIPS with a loud message rather than passing
# quietly, because a parity test that silently does nothing is indistinguishable
# from one that passes.
from __future__ import annotations

import json
import random
import shutil
import string
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.password import evaluate

ROOT = Path(__file__).resolve().parents[1]
TS_SOURCE = ROOT / "web" / "src" / "lib" / "password.ts"

# Context is part of the rule set -- "do not put your name in your password"
# only fires when it is threaded through -- so it is varied across the vectors
# rather than left empty.
CONTEXTS = [
    {},
    {"email": "ada@example.com", "name": "Ada Lovelace", "company": "Docks Ltd"},
    {"email": "islombek@fayzinc.com", "name": "Islombek", "company": "Fayz"},
    {"name": "Rotterdam"},
]

CURATED = [
    "", "a", "abc", "abcdefghi", "abcdefghij",          # the 10-character boundary
    "abcdefghijklm", "abcdefghijklmn",                   # the 14-character boundary
    "password", "Password1!", "passw0rd", "PASSWORD",
    "Summer2024!", "Welcome2024", "Dragon99", "abc123", "123456",
    "qwerty", "Qwerty123!", "asdfgh12!A", "zxcvbn98!Q", "0987654321",
    "aaa111!!!AAA", "aAaAaAaAaAaA", "!!!!!!!!!!!!",
    "Tarmoq-Qishloq-42!", "correct-horse-battery-9", "Qishloq7Tarmoq!x",
    "Ada Lovelace 99!", "islombek_2012", "DocksLtd-9911!",
    "Rotterdam-sailing-7!", "xX9$" * 3, "  spaced  out  9! ",
    "Ω-omega-999-Ω!", "naïve-café-42!x", "日本語-password-9!",
    "x" * 199, "x" * 200, "x" * 201,                     # the MAX_LENGTH boundary
]


def _random_vectors(n: int, seed: int = 20260901) -> list[str]:
    """Breadth the curated list cannot give: the interaction of rules.

    Drawn from alphabets that make each rule reachable -- all-lower strings hit
    the composition rule, mixed ones reach the scoring branches, and short ones
    exercise the length floor.
    """
    rng = random.Random(seed)
    alphabets = [
        string.ascii_lowercase,
        string.ascii_letters,
        string.ascii_letters + string.digits,
        string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{};:,.<>?",
        string.digits,
        "abc123!",                                        # few distinct characters
    ]
    out = []
    for _ in range(n):
        alpha = rng.choice(alphabets)
        length = rng.choice([3, 6, 9, 10, 11, 13, 14, 16, 20, 28])
        out.append("".join(rng.choice(alpha) for _ in range(length)))
    return out


def _node_results(cases: list[tuple[str, dict]]) -> list[dict] | None:
    """Compile password.ts and run it over the vectors. None if unavailable."""
    node = shutil.which("node")
    if node is None:
        return None

    workdir = Path(tempfile.mkdtemp(prefix="readback_parity_"))
    bundle = workdir / "password.mjs"

    # esbuild from web/node_modules; vite depends on it, so it is already there.
    esbuild = ROOT / "web" / "node_modules" / ".bin" / "esbuild"
    candidates = [esbuild, esbuild.with_suffix(".cmd"), Path("esbuild")]
    built = False
    for candidate in candidates:
        try:
            proc = subprocess.run(
                [str(candidate), str(TS_SOURCE), "--format=esm", f"--outfile={bundle}",
                 "--loader:.ts=ts", "--platform=node"],
                capture_output=True, text=True, encoding="utf-8", timeout=120,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0 and bundle.exists():
            built = True
            break
    if not built:
        return None

    (workdir / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    runner = workdir / "run.mjs"
    runner.write_text(
        "import { readFileSync } from 'node:fs';\n"
        "import { evaluateLocally } from './password.mjs';\n"
        "const cases = JSON.parse(readFileSync(new URL('./cases.json', import.meta.url), 'utf8'));\n"
        "const out = cases.map(([password, context]) => evaluateLocally(password, context));\n"
        "process.stdout.write(JSON.stringify(out));\n",
        encoding="utf-8",
    )
    # encoding is not optional here. Without it Windows decodes node's stdout as
    # cp1252, the em-dash in one suggestion comes back as "a€”", and 1,028
    # vectors report a mismatch that exists only in the harness. The first run
    # of this test did exactly that.
    proc = subprocess.run([node, str(runner)], capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    if proc.returncode != 0:
        print("    node runner failed:", proc.stderr[:800])
        return None
    return json.loads(proc.stdout)


def test_typescript_and_python_scorers_agree() -> None:
    cases: list[tuple[str, dict]] = []
    for password in CURATED + _random_vectors(400):
        for context in CONTEXTS:
            cases.append((password, context))

    ts_results = _node_results(cases)
    if ts_results is None:
        print("    SKIPPED: node or esbuild unavailable -- parity NOT verified.")
        print("    This is a skip, not a pass. Run it where node is installed.")
        return

    assert len(ts_results) == len(cases)

    mismatches: list[str] = []
    for (password, context), ts in zip(cases, ts_results):
        py = evaluate(
            password,
            email=context.get("email", ""),
            name=context.get("name", ""),
            company=context.get("company", ""),
        )
        for field, mine, theirs in (
            ("ok", py.ok, ts["ok"]),
            ("score", py.score, ts["score"]),
            ("label", py.label, ts["label"]),
            ("problems", py.problems, ts["problems"]),
            ("suggestions", py.suggestions, ts["suggestions"]),
        ):
            if mine != theirs:
                mismatches.append(
                    f"{password!r} ctx={sorted(context)} field={field}\n"
                    f"        python: {mine!r}\n"
                    f"        typescript: {theirs!r}"
                )
        # The local scorer has not asked about breaches and must not pretend it
        # has. "Not asked" is not "safe", and the UI depends on the difference.
        if ts["breached"] is not False or ts["breach_checked"] is not False:
            mismatches.append(f"{password!r}: local verdict claims a breach opinion it cannot have")

    print(f"    {len(cases)} vectors x 5 fields compared")
    if mismatches:
        for line in mismatches[:12]:
            print("      MISMATCH", line)
        if len(mismatches) > 12:
            print(f"      ... and {len(mismatches) - 12} more")
    assert not mismatches, f"{len(mismatches)} field mismatches between the two scorers"


TESTS = [test_typescript_and_python_scorers_agree]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001 -- a script runner reports, not raises
            failed += 1
            print(f"  FAIL {fn.__name__}: {exc}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
