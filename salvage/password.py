"""Password policy, strength scoring, and breach lookup.

A deliberate note on what this does NOT do: it does not send the password to a
language model. An LLM cannot tell you anything about a password that arithmetic
cannot, and asking one means transmitting a plaintext credential to a third
party, having it sit in their request logs, and paying a network round trip on
every signup. The useful, checkable signal is:

  1. composition and length  -- arithmetic, instant, local
  2. predictability          -- is it a keyboard run, a repeat, a common word
  3. has it already leaked   -- the only question needing an external service

Point 3 is what Supabase actually does, and it is done without revealing the
password: SHA-1 the password, send the FIRST FIVE hex characters of the hash to
Have I Been Pwned, and search the returned suffix list locally. The service
never learns the password or even the full hash. That is k-anonymity, and it is
strictly better than an AI opinion because the answer is a fact: this exact
password appears in N known breaches.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

MIN_LENGTH = 10
MAX_LENGTH = 200  # hashing a megabyte of input is a free denial of service

HIBP_URL = "https://api.pwnedpasswords.com/range/{prefix}"
HIBP_TIMEOUT = 3.0

# Sequences people reach for when told "add a number and a symbol".
KEYBOARD_RUNS = (
    "qwertyuiop", "asdfghjkl", "zxcvbnm", "1234567890", "!@#$%^&*()",
)

COMMON = {
    "password", "passw0rd", "letmein", "welcome", "admin", "qwerty",
    "iloveyou", "monkey", "dragon", "football", "baseball", "sunshine",
    "princess", "superman", "trustno1", "changeme", "secret", "master",
    "hello", "freedom", "whatever", "starwars", "abc123", "123456",
}


@dataclass
class Verdict:
    ok: bool
    score: int                       # 0-4, the scale people already know
    label: str                       # spoken-plain summary
    problems: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    breached: int = 0                # times seen in known breaches
    breach_checked: bool = False

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "score": self.score,
            "label": self.label,
            "problems": self.problems,
            "suggestions": self.suggestions,
            "breached": self.breached,
            "breach_checked": self.breach_checked,
        }


# --------------------------------------------------------------------------
# composition
# --------------------------------------------------------------------------

def _classes(password: str) -> dict[str, bool]:
    return {
        "lower": bool(re.search(r"[a-z]", password)),
        "upper": bool(re.search(r"[A-Z]", password)),
        "digit": bool(re.search(r"\d", password)),
        "symbol": bool(re.search(r"[^A-Za-z0-9]", password)),
    }


def _predictable(password: str) -> list[str]:
    """Cheap pattern checks that catch the passwords rules alone let through.

    "Password1!" satisfies every composition rule and is one of the most
    common passwords in existence, so composition alone is not a policy.
    """
    found = []
    low = password.lower()

    stripped = re.sub(r"[^a-z]", "", low)
    if stripped and stripped in COMMON:
        found.append("It is a very common password with numbers or symbols bolted on.")
    elif low in COMMON:
        found.append("It is one of the most common passwords in use.")

    for run in KEYBOARD_RUNS:
        for size in range(4, 7):
            for i in range(len(run) - size + 1):
                chunk = run[i : i + size]
                if chunk in low or chunk[::-1] in low:
                    found.append("It contains a straight run across the keyboard.")
                    return found

    if re.search(r"(.)\1{2,}", password):
        found.append("It repeats the same character three or more times.")

    if len(set(password)) <= max(2, len(password) // 4):
        found.append("It uses too few distinct characters.")

    if re.fullmatch(r"\D*\d{1,4}[!@#$%^&*]?", password or "x"):
        # e.g. "Summer2024!" -- word, year, punctuation
        found.append("Word-then-number-then-symbol is the first thing an attacker tries.")

    return found


def evaluate(password: str, *, email: str = "", name: str = "", company: str = "") -> Verdict:
    """Local judgement. No network, no model, no plaintext leaving the process."""
    problems: list[str] = []
    suggestions: list[str] = []

    if len(password) > MAX_LENGTH:
        return Verdict(
            ok=False, score=0, label="Too long",
            problems=[f"Keep it under {MAX_LENGTH} characters."],
        )

    if len(password) < MIN_LENGTH:
        problems.append(f"Use at least {MIN_LENGTH} characters.")

    cls = _classes(password)
    missing = []
    if not (cls["lower"] or cls["upper"]):
        missing.append("a letter")
    if not cls["digit"]:
        missing.append("a number")
    if not cls["symbol"]:
        missing.append("a symbol")
    if missing:
        problems.append("Include " + ", ".join(missing) + ".")

    # Personal data in a password is the first guess anyone makes.
    low = password.lower()
    for label, value in (("email", email.split("@")[0]), ("name", name), ("company", company)):
        token = (value or "").strip().lower()
        if len(token) >= 4 and token in low:
            problems.append(f"Do not put your {label} in your password.")

    problems.extend(_predictable(password))

    # Score: length does most of the work, variety and unpredictability the rest.
    score = 0
    if len(password) >= MIN_LENGTH:
        score += 1
    if len(password) >= 14:
        score += 1
    if sum(cls.values()) >= 3:
        score += 1
    if len(set(password)) >= 8 and not _predictable(password):
        score += 1
    score = max(0, min(4, score - (1 if problems else 0)))

    if len(password) < 14:
        suggestions.append("Length beats cleverness — four unrelated words are stronger than one word with substitutions.")
    if not problems and score < 3:
        suggestions.append("Add a few more characters to make it comfortably strong.")

    labels = ["Very weak", "Weak", "Fair", "Strong", "Very strong"]
    return Verdict(
        ok=not problems,
        score=score,
        label=labels[score],
        problems=problems,
        suggestions=suggestions,
    )


# --------------------------------------------------------------------------
# breach lookup (k-anonymity)
# --------------------------------------------------------------------------

async def breach_count(password: str) -> int | None:
    """How many known breaches contain this exact password.

    Sends only the first five hex characters of the SHA-1 hash. Have I Been
    Pwned returns every suffix sharing that prefix -- tens of thousands of
    them -- and the match happens here. The service cannot tell which one was
    being asked about, and never sees the password.

    Returns None when the lookup could not be made. The caller must treat that
    as "unknown", never as "safe" and never as a reason to block a signup: an
    outage at a third party must not stop a person creating an account.
    """
    digest = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]

    try:
        async with httpx.AsyncClient(timeout=HIBP_TIMEOUT) as client:
            resp = await client.get(
                HIBP_URL.format(prefix=prefix),
                headers={
                    "Add-Padding": "true",       # pad the response so its size leaks nothing
                    "User-Agent": "Closeout-Hackathon",
                },
            )
            resp.raise_for_status()
    except Exception as exc:
        log.info("breach lookup unavailable: %s", exc)
        return None

    for line in resp.text.splitlines():
        candidate, _, count = line.partition(":")
        if candidate.strip() == suffix:
            try:
                return int(count.strip())
            except ValueError:
                return 1
    return 0


async def full_check(
    password: str, *, email: str = "", name: str = "", company: str = ""
) -> Verdict:
    """Local policy first, then the breach lookup only if the policy passed.

    Ordering matters: a password already rejected for being eight characters
    long does not need a network call, and skipping it keeps the common
    rejection path instant.
    """
    verdict = evaluate(password, email=email, name=name, company=company)
    if not verdict.ok:
        return verdict

    count = await breach_count(password)
    if count is None:
        verdict.breach_checked = False
        return verdict

    verdict.breach_checked = True
    verdict.breached = count
    if count > 0:
        verdict.ok = False
        verdict.score = 0
        verdict.label = "Found in a data breach"
        verdict.problems.append(
            f"This password appears in {count:,} known breaches. "
            "Attackers try leaked passwords first — pick a different one."
        )
    return verdict
