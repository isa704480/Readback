# config.py -- settings. One place for the money, the consent and the seam.
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Every value that ships as a default and must never ship as a deployment. Kept
# next to the class rather than inline in the validator so the field default and
# the refusal cannot drift apart without the diff showing both.
_PLACEHOLDER_SECRETS: tuple[tuple[str, str], ...] = (
    ("session_secret", "dev-secret-not-for-production"),
    ("ip_hash_salt", "dev-salt-not-for-production"),
)


class Settings(BaseSettings):
    """Everything read from the environment, prefix READBACK_.

    Two of these fields are not configuration in the ordinary sense.
    `assemblyai_api_key` is the seam the whole build is arranged around, and
    `consent_required` is a non-negotiable that is only a field so that tests
    can exist. Both are commented where they are declared.
    """

    model_config = SettingsConfigDict(
        env_prefix="READBACK_", env_file=".env", env_file_encoding="utf-8",
        extra="ignore", frozen=True,
    )

    # -------------------------------------------------------------- the seam --
    # Empty is legal and is today's state: the key arrives this evening. Nothing
    # downstream may test this field directly -- branch on `live_capture`, so
    # that the key turning up is a .env edit and not a diff. The value is a
    # SecretStr because ARCH 3.9 forbids sensitive strings reaching logs and
    # stack traces, and pydantic repr's a SecretStr as '**********' for free.
    assemblyai_api_key: SecretStr = SecretStr("")
    assemblyai_url: str = "wss://streaming.assemblyai.com/v3/ws"

    # Replay mode reads recorded Turn frames from disk instead of opening a
    # socket. It is the kill switch at 100% of the daily budget (ARCH 3.11) and
    # it is also how every line of this system is testable before a key exists,
    # which is why the fixture directory is configuration and not a constant:
    # the replay source and the live source must be swappable without a rebuild.
    replay_mode: bool = False
    replay_fixture_dir: str = "tests/fixtures/turns"

    # ------------------------------------------------------------ the money --
    # universal-3-5-pro 0.45 + voice_focus 0.10 + prompting 0.05 = $0.60/hr per
    # socket = $0.000167 per socket-second. ARCH 3.11's $20/day ceiling is
    # therefore 120,000 socket-seconds, which is the same 400 dual-socket 150 s
    # sessions that section quotes -- the two numbers were derived independently
    # and agree, so the conversion is right. Seconds rather than dollars because
    # seconds are what Termination.session_duration_seconds reports and what a
    # nightly reconciliation can check; a dollar figure here would be a price
    # list going stale in the wrong file.
    daily_budget_seconds: int = 120_000
    budget_alarm_fraction: float = Field(default=0.60, ge=0.0, le=1.0)

    # ARCH 3.11 per-session hard cap, enforced server-side off
    # Heartbeat.total_duration_ms. Wall-clock socket-open including silence,
    # per socket -- an A/B session at 150 s spends 300 socket-seconds.
    session_cap_seconds: int = Field(default=150, gt=0)
    demo_sockets: int = Field(default=2, ge=1, le=2)

    # ARCH 3.11 admission control. Per-IP counts are over the salted hash, never
    # the address.
    per_ip_per_hour: int = 3
    per_ip_per_day: int = 10
    max_concurrent_sessions: int = 3
    admissions_per_minute: int = 2

    # ---------------------------------------------------------- the consent --
    # ARCH 3.12: always all-party consent, no jurisdiction toggle, because a
    # toggle is a liability generator that will eventually be set wrong. This
    # field is not that toggle -- the validator below refuses to construct
    # Settings with consent off unless replay mode is also on, i.e. unless there
    # is no microphone and no second human in the loop at all. It exists so a
    # fixture test does not have to fabricate a consent record.
    consent_required: bool = True
    consent_version: str = "2026-09-01"

    # ARCH 3.12 states a 24-hour auto-purge and implements it. These are the
    # windows the purge job reads; the models carry the same numbers as
    # RETENTION attributes so a table and its window cannot drift apart.
    capture_retention_days: int = 30
    question_retention_days: int = 7
    ip_hash_retention_hours: int = 24
    demo_purge_hours: int = 24

    # Rate limiting has to recognise a repeat visitor without learning who they
    # are. Rotating this salt daily bounds re-identification to one day, which
    # is the same window as ip_hash_retention_hours by design.
    ip_hash_salt: SecretStr = SecretStr("dev-salt-not-for-production")

    # ------------------------------------------------------------- the auth --
    # Signs session tokens. A changed secret invalidates every outstanding
    # token, which is the intended way to sign everybody out. The default is
    # deliberately an obvious placeholder rather than a random value generated
    # at import: a random default would work in dev and then silently sign
    # people out on every restart in production, which is a bug that looks like
    # a flaky login. `_check_invariants` below refuses to construct Settings on
    # this default in any deployment shape (a key present and a non-SQLite
    # database); server/auth.py does not check it and must not grow a second
    # opinion.
    session_secret: SecretStr = SecretStr("dev-secret-not-for-production")
    session_ttl_hours: int = Field(default=720, gt=0)   # 30 days

    # Comma-separated, because a list in an env var is a parsing argument
    # nobody wins. The Vite dev server is 5173; 4173 is `vite preview`; the rest
    # are the ports this project's agents have been told to use so that a
    # verification run does not fail on CORS and get diagnosed as a bug.
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173,"
        "http://localhost:5174,http://localhost:5180,"
        "http://localhost:5181,http://localhost:5182"
    )

    # --------------------------------------------------------------- the db --
    database_url: str = "sqlite:///./readback.db"
    sql_echo: bool = False

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @property
    def live_capture(self) -> bool:
        """True when a real socket may be opened. The single branch point.

        A missing key and an exhausted budget are the same condition as far as
        every caller is concerned: use fixtures. Collapsing them here means the
        replay path is exercised on every run today rather than being the branch
        nobody tried until the day it was needed.
        """
        return bool(self.assemblyai_api_key.get_secret_value()) and not self.replay_mode

    @property
    def cors_origin_list(self) -> list[str]:
        """Explicit origins only. Never "*": the API answers with credentials in
        the Authorization header, and a wildcard origin plus credentials is the
        combination browsers refuse anyway -- better to be specific here than to
        debug it in a console at midnight."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def session_socket_seconds(self) -> int:
        """Worst-case socket-seconds one session can spend, for admission."""
        return self.session_cap_seconds * self.demo_sockets

    @property
    def budget_alarm_seconds(self) -> int:
        return int(self.daily_budget_seconds * self.budget_alarm_fraction)

    @model_validator(mode="after")
    def _check_invariants(self) -> "Settings":
        if not self.consent_required and not self.replay_mode:
            raise ValueError(
                "READBACK_CONSENT_REQUIRED=false is only permitted with "
                "READBACK_REPLAY_MODE=true: consent can be waived for recorded "
                "fixtures, never for a live microphone (ARCH 3.12)."
            )
        if self.daily_budget_seconds < self.session_socket_seconds:
            raise ValueError(
                "daily_budget_seconds is below the cost of a single session; "
                "the budget gate would reject every admission."
            )
        # A deployment is "a key that can spend money and a database that is
        # not a local file". On that shape the two placeholder secrets are
        # refused at construction, so the process never binds a port: Render's
        # health check fails, the log carries this sentence, and nobody signs
        # in with a token anyone can forge. SQLite with a key is left alone on
        # purpose -- that is a developer's laptop, and the tests construct
        # Settings with placeholder keys against the default database.
        # Key or no key: a replay-only deployment on a real database still
        # issues tokens, and a placeholder session secret makes every one of
        # them forgeable. The audit of 2026-09-07 found the `and` above this
        # line left exactly that shape unguarded.
        if not self.database_url.startswith("sqlite"):
            for name, value in _PLACEHOLDER_SECRETS:
                # Empty counts as placeholder: pydantic-settings hands an env var
                # that is set-but-blank through as "", not as the default, and
                # an HMAC over an empty key is not a secret either.
                if getattr(self, name).get_secret_value() in ("", value):
                    # RuntimeError, not ValueError, on purpose: pydantic wraps a
                    # ValueError in a ValidationError that echoes the input
                    # dict -- including the first characters of the API key --
                    # into the message, and the message goes to the deploy log.
                    # Any other exception type propagates untouched.
                    raise RuntimeError(
                        f"READBACK_{name.upper()} is empty or still the development "
                        f"placeholder. A deployment with an AssemblyAI key and a "
                        f"real database must set its own value: "
                        f"python -c \"import secrets; print(secrets.token_urlsafe(48))\""
                    )
        return self

    @property
    def live_capture_possible(self) -> bool:
        """A key is present, whether or not replay_mode currently masks it.

        `live_capture` is the branch point for sessions; this is the branch
        point for the secrets check, and they differ on purpose. Flipping
        READBACK_REPLAY_MODE=true is the budget kill switch (3.11) and must not
        silently re-admit a placeholder session secret on the same deployment.
        """
        return bool(self.assemblyai_api_key.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached because Settings is frozen and reading .env per request is waste.

    Tests that need different values call get_settings.cache_clear() after
    setting the environment, rather than mutating a live instance -- frozen=True
    makes the second option impossible on purpose.
    """
    return Settings()
