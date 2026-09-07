"""Rate limiting for the endpoints an attacker actually targets.

Two different attacks need two different limits, and conflating them protects
against neither:

  per IP     stops one machine hammering signup to mine the "email already
             has an account" response, which is an account-enumeration oracle
  per email  stops a distributed credential-stuffing run against one known
             account, where every request comes from a different address

Login gets both. Signup gets a per-IP limit only — limiting signup per email
would let anyone lock a stranger out of registering their own address.

In-process fixed windows. Honest about what that means: with more than one
worker each holds its own counters, so the effective limit multiplies by the
worker count. For a hackathon deployment on a single Render instance that is
the correct amount of machinery. Moving to Redis is a swap of the two dict
operations below, and the docstring on `_Bucket` says where.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class _Bucket:
    """Fixed-window counters. Swap this class for Redis INCR + EXPIRE to share
    limits across workers; the call sites do not change."""

    window_seconds: int
    counts: dict[tuple[str, int], int] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    def hit(self, key: str) -> int:
        now_window = int(time.time() // self.window_seconds)
        with self.lock:
            # Drop everything from earlier windows rather than growing forever.
            if len(self.counts) > 8192:
                self.counts = {
                    k: v for k, v in self.counts.items() if k[1] >= now_window - 1
                }
            k = (key, now_window)
            self.counts[k] = self.counts.get(k, 0) + 1
            return self.counts[k]

    def peek(self, key: str) -> int:
        return self.counts.get((key, int(time.time() // self.window_seconds)), 0)

    def retry_after(self) -> int:
        elapsed = int(time.time()) % self.window_seconds
        return max(1, self.window_seconds - elapsed)


@dataclass(frozen=True)
class Limit:
    name: str
    max_hits: int
    window_seconds: int


# Tuned for a real person versus a script. A human signs up once; a human
# mistypes a password three or four times, not twenty.
SIGNUP_PER_IP = Limit("signup_ip", max_hits=5, window_seconds=3600)
LOGIN_PER_IP = Limit("login_ip", max_hits=20, window_seconds=900)
LOGIN_PER_EMAIL = Limit("login_email", max_hits=6, window_seconds=900)
PASSWORD_CHECK_PER_IP = Limit("pwcheck_ip", max_hits=60, window_seconds=300)

_buckets: dict[str, _Bucket] = {}


def _bucket(limit: Limit) -> _Bucket:
    b = _buckets.get(limit.name)
    if b is None:
        b = _Bucket(window_seconds=limit.window_seconds)
        _buckets[limit.name] = b
    return b


class RateLimited(Exception):
    def __init__(self, retry_after: int, message: str):
        super().__init__(message)
        self.retry_after = retry_after
        self.message = message


def check(limit: Limit, key: str, message: str) -> None:
    """Count this attempt and raise if it puts the key over the limit."""
    b = _bucket(limit)
    if b.hit(f"{limit.name}:{key}") > limit.max_hits:
        raise RateLimited(b.retry_after(), message)


def client_ip(request) -> str:
    """Best-effort client address.

    X-Forwarded-For is trusted here because Render terminates TLS and sets it.
    Behind a proxy that does NOT set it, this header is attacker-controlled and
    the limit becomes bypassable — so a deployment on different infrastructure
    must revisit this line rather than assume it.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        # The RIGHTMOST entry: a proxy appends the address it saw, so that one
        # is the proxy's word; the leftmost is whatever the client wrote into
        # its own request. Leftmost made every per-IP limit bypassable by
        # setting the header (measured in the 2026-09-07 audit).
        return forwarded.split(",")[-1].strip()
    return getattr(request.client, "host", "unknown") or "unknown"

# ARCH 3.11: a demo replay writes a session row and runs a pipeline, anonymously.
# Generous -- a judge clicking through eight fixtures several times -- and per
# address, the same identity the sign-in limits key on.
REPLAY_PER_IP = Limit("replay_ip", max_hits=120, window_seconds=3600)
