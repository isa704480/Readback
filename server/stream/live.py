# live.py -- the AssemblyAI Universal Streaming implementation of the source
# contract. Written in full, NOT RUNNABLE TODAY: there is no API key until this
# evening. The intended diff tonight is one line in .env and nothing else.
#
# Everything here is written against the documented protocol. Where the
# documentation does not settle a detail, the code takes the documented reading
# and carries a TODO(day1-NN) naming exactly what must be observed on the first
# connection. Those TODOs are the checklist for the first ten minutes with a
# key; none of them changes the shape of this class, only its constants and its
# parsing of one frame type.
#
# The falsification experiment (README, ARCHITECTURE 6) runs through this class:
# `raw_frames` keeps every decoded frame so words-per-spelled-character and the
# confidence AUC can be computed from a recorded session, and `to_fixture()`
# turns that recording into a replay fixture with no conversion step.
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.parse
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from .source import (
    BaseTranscriptSource,
    SourceClosed,
    SourceConfig,
    SourceError,
    Turn,
    validate_turn,
)

# Imported lazily so this module can be imported, type-checked and unit-tested
# on a machine that has never installed a websocket client -- which is the case
# in CI and was the case for most of today.
try:
    from websockets.asyncio.client import connect as _ws_connect
    _WS_IMPORT_ERROR: Exception | None = None
except Exception as exc:                                    # pragma: no cover
    _ws_connect = None                                      # type: ignore[assignment]
    _WS_IMPORT_ERROR = exc


DEFAULT_URL = "wss://streaming.assemblyai.com/v3/ws"

# ARCHITECTURE 3.1. 16 kHz is not a compromise with the accent analysis's "keep
# 24 kHz end to end": what destroys the S/F contrast is the 300-3400 Hz
# telephone band, and /s/ energy at 4-8 kHz survives an 8 kHz Nyquist intact.
DEFAULT_SAMPLE_RATE = 16_000
DEFAULT_ENCODING = "pcm_s16le"
DEFAULT_SPEECH_MODEL = "universal-3-5-pro"

# format_turns MUST stay false. Formatting collapses "fifteen" and "one five"
# into the same string, and that distinction is the evidence the arity branch in
# normalise.py runs on (3.5). This is a correctness constraint, not a preference.
FORMAT_TURNS = False

# Billing is socket wall-clock including silence, and unclosed sessions are the
# documented first cause of surprise charges (3.11). inactivity_timeout is the
# backstop; KeepAlive is never sent, by policy -- in an always-listening product
# it is the burn-credits button.
DEFAULT_INACTIVITY_TIMEOUT_S = 15


class LiveSource(BaseTranscriptSource):
    """AssemblyAI Universal Streaming STT over a WebSocket.

    Deliberately not the Voice Agent API: `transcript.user` carries a flat
    string with no `words` and no `confidence`, and per-word confidence is the
    substrate of the entire posterior (3.1). There is no version of this product
    on that transport.
    """

    def __init__(
        self,
        api_key: str,
        *,
        config: SourceConfig | None = None,
        url: str = DEFAULT_URL,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        encoding: str = DEFAULT_ENCODING,
        speech_model: str = DEFAULT_SPEECH_MODEL,
        inactivity_timeout: int = DEFAULT_INACTIVITY_TIMEOUT_S,
        connect_timeout: float = 10.0,
        extra_params: dict[str, Any] | None = None,
        record_raw: bool = True,
    ) -> None:
        super().__init__(config)
        if not api_key:
            raise SourceError("no API key: set ASSEMBLYAI_API_KEY in .env")
        self._api_key = api_key
        self._url = url
        self.sample_rate = sample_rate
        self.encoding = encoding
        self.speech_model = speech_model
        self.inactivity_timeout = inactivity_timeout
        self.connect_timeout = connect_timeout
        self._extra_params = dict(extra_params or {})
        self._ws: Any = None
        self._send_lock = asyncio.Lock()
        self._connected_at: float | None = None
        self.expires_at: int | None = None
        self.audio_duration_seconds: float | None = None
        # The day-1 experiment computes its two numbers off this list, and a
        # recorded session becomes a replay fixture from it. Turned off for long
        # production sessions, where the tape's 45 s bound is the whole point.
        self.record_raw = record_raw
        self.raw_frames: list[dict[str, Any]] = []
        self.unknown_frame_types: dict[str, int] = {}

    # -- construction ---------------------------------------------------------
    @classmethod
    def from_env(cls, **kwargs: Any) -> LiveSource:
        """Build from whichever name the key was written under.

        There used to be two names and they were a trap. server/config.py reads
        READBACK_ASSEMBLYAI_API_KEY, because every other setting in this system
        is prefixed; this module hand-parsed .env looking for a bare
        ASSEMBLYAI_API_KEY, because that is the name the AssemblyAI docs use.
        Each was reasonable on its own, and together they meant that writing one
        line into .env satisfied exactly one half of the system -- and which half
        broke depended on which name you happened to pick. Settings is the source
        of truth now; the bare name is still accepted so that muscle memory and
        a copy-pasted docs example both work.
        """
        key = _resolve_api_key()
        if not key:
            raise SourceError(
                "No AssemblyAI key found. Put it in the environment or in "
                f"{_dotenv_path()} as READBACK_ASSEMBLYAI_API_KEY=... "
                "(a bare ASSEMBLYAI_API_KEY=... is accepted too)."
            )
        return cls(key, **kwargs)

    # -- connection -----------------------------------------------------------
    def connect_params(self) -> dict[str, Any]:
        """The connect-time configuration, as ARCHITECTURE 3.1 specifies it.

        TODO(day1-01): confirm whether v3 takes these as query-string parameters
        or as a first JSON configuration message on the open socket. The code
        below sends them as query parameters, which is the documented v3 form.
        If a config message is required instead, `_open()` gains one send and
        nothing else in this class moves.

        TODO(day1-03): confirm which of `mode`, `voice_focus`,
        `voice_focus_threshold`, `vad_threshold`, `continuous_partials`,
        `include_partial_turns`, `previous_context_n_turns`, `prompt`,
        `session_heartbeat` and `language_codes` are accepted by
        universal-3-5-pro, and their exact parameter names. An unrecognised
        parameter must be observed to be ignored rather than fatal -- if it is
        fatal, this dict has to be trimmed to the confirmed set before the demo.
        """
        params: dict[str, Any] = {
            "sample_rate": self.sample_rate,
            "encoding": self.encoding,
            "speech_model": self.speech_model,
            "format_turns": _bool_param(FORMAT_TURNS),
            "mode": "max_accuracy",
            "language_codes": "en",
            "voice_focus": "near-field",
            "voice_focus_threshold": 0.7,
            "vad_threshold": 0.2,
            "continuous_partials": _bool_param(True),
            "include_partial_turns": _bool_param(True),
            "previous_context_n_turns": 5,
            "session_heartbeat": _bool_param(True),
            "inactivity_timeout": self.inactivity_timeout,
            "speaker_labels": _bool_param(False),
            "max_turn_silence": self._config.max_turn_silence,
        }
        if self._config.end_of_turn_confidence_threshold is not None:
            params["end_of_turn_confidence_threshold"] = (
                self._config.end_of_turn_confidence_threshold
            )
        if self._config.prompt:
            params["prompt"] = self._config.prompt
        if self._config.keyterms:
            params["keyterms_prompt"] = _encode_keyterms(self._config.keyterms)
        params.update(self._extra_params)
        return params

    def connect_url(self) -> str:
        return f"{self._url}?{urllib.parse.urlencode(self.connect_params())}"

    async def connect(self) -> None:
        """Open the socket. Idempotent; `_frames()` calls it if you have not."""
        if self._ws is not None:
            return
        if self._closed:
            raise SourceClosed("connect on a terminated source")
        if _ws_connect is None:                                # pragma: no cover
            raise SourceError(
                "the `websockets` package is required for LiveSource: pip install websockets"
            ) from _WS_IMPORT_ERROR
        self._config.validate()
        self._ws = await asyncio.wait_for(
            _ws_connect(
                self.connect_url(),
                # v3 authenticates with the raw key in Authorization, with no
                # Bearer prefix. The browser never sees this: the credential and
                # therefore the money and the consent state are server-side (3.2).
                additional_headers={"Authorization": self._api_key},
                # Frames are small JSON; a generous cap only hides a bug.
                max_size=2**20,
                # The socket is billed by wall-clock, so a half-open connection
                # is a charge with no transcript. Ping often enough to notice.
                ping_interval=20,
                ping_timeout=20,
            ),
            timeout=self.connect_timeout,
        )
        self._connected_at = time.monotonic()
        self._t0 = self._connected_at

    # -- control --------------------------------------------------------------
    async def send_audio(self, pcm: bytes) -> None:
        """Send one chunk of PCM upstream as a binary frame.

        The client opens the socket on VAD onset and flushes its 3-second ring
        buffer first, faster than realtime, so the gate is lossless and costs
        roughly nothing billed (3.2). That flush arrives here as a burst.
        """
        if self._closed:
            raise SourceClosed("send_audio on a terminated source")
        if self._ws is None:
            raise SourceError("send_audio before connect()")
        async with self._send_lock:
            await self._ws.send(pcm)

    async def _on_update_configuration(self, config: SourceConfig) -> None:
        """Send UpdateConfiguration now; it becomes effective at the next turn
        boundary, which the base class models and the replay reproduces.

        TODO(day1-06): confirm the server acknowledges this (and with what frame
        type), and measure how many turns pass before the new keyterms bias the
        output. The whole ARM path assumes exactly one boundary. If it is two,
        `_begin_turn` needs a delay of one turn and the replay's variant gating
        needs the same change -- which is why both live in one place.
        """
        if self._ws is None:
            return                      # queued; connect() will carry it in the URL
        payload: dict[str, Any] = {
            "type": "UpdateConfiguration",
            "max_turn_silence": config.max_turn_silence,
        }
        if config.keyterms:
            # TODO(day1-02): confirm the on-socket encoding of keyterms_prompt --
            # a JSON array here, versus the repeated/JSON-encoded query parameter
            # in connect_params(). Confirm too that exceeding 100 terms or 50
            # chars is an error frame rather than a socket close: arming sits
            # right against that ceiling by design (3.6).
            payload["keyterms_prompt"] = list(config.keyterms)
        if config.prompt is not None:
            payload["prompt"] = config.prompt
        if config.end_of_turn_confidence_threshold is not None:
            payload["end_of_turn_confidence_threshold"] = (
                config.end_of_turn_confidence_threshold
            )
        await self._send_json(payload)

    async def force_endpoint(self) -> None:
        """Close the turn in flight now.

        Sent once the candidate is length-complete, to claw back the ~1.5 s the
        raised ARMED `max_turn_silence` cost (3.6). That reclaim is what makes a
        2500 ms endpoint affordable inside a 2-second interrupt budget.

        TODO(day1-07): confirm the exact frame name (`ForceEndpoint`), that it
        produces a Turn with `end_of_turn` true within the endpoint latency, and
        whether `turn_order` advances. Confirm also that in-flight partials for
        that turn are dropped rather than delivered late -- the replay models
        them as dropped.
        """
        if self._closed:
            raise SourceClosed("force_endpoint on a terminated source")
        if self._ws is None:
            raise SourceError("force_endpoint before connect()")
        self._log_control("force_endpoint")
        await self._send_json({"type": "ForceEndpoint"})

    async def terminate(self) -> None:
        """Send Terminate and close.

        The single most expensive method in the codebase to forget: billing is
        socket wall-clock including silence, sessions hard-close at 3 h, and you
        are billed for all of it (3.11).
        """
        if self._closed:
            return
        self._closed = True
        event = self._log_control("terminate")
        if self._ws is not None:
            try:
                await self._send_json({"type": "Terminate"})
                # TODO(day1-12): confirm the server replies with a Termination
                # frame and closes, and how long it takes. If it does not close,
                # this needs a timeout before close() or the socket keeps billing.
                await asyncio.wait_for(self._ws.close(), timeout=5.0)
            except Exception as exc:                            # pragma: no cover
                event.detail["close_error"] = repr(exc)
            finally:
                self._ws = None
        if self.billed_seconds is None and self._connected_at is not None:
            # Fallback only. The ledger reconciles against the Termination frame
            # (3.11); a locally measured duration is an estimate, not the bill.
            self.billed_seconds = round(time.monotonic() - self._connected_at, 3)
            event.detail["billed_seconds_source"] = "local_clock"
        event.detail["billed_seconds"] = self.billed_seconds

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise SourceError(f"{payload.get('type')} before connect()")
        async with self._send_lock:
            await self._ws.send(json.dumps(payload))

    # -- the stream -----------------------------------------------------------
    async def _frames(self) -> AsyncIterator[Turn]:
        await self.connect()
        assert self._ws is not None
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    # Nothing in the documented protocol comes back as binary.
                    # Count it rather than crash, and say so on first connection.
                    self.unknown_frame_types["<binary>"] = (
                        self.unknown_frame_types.get("<binary>", 0) + 1
                    )
                    continue
                message = json.loads(raw)
                if self.record_raw:
                    self.raw_frames.append(
                        {"recv_ms": self.now_ms(), "frame": message}
                    )
                kind = message.get("type")
                if kind == "Turn":
                    # TODO(day1-04): THE load-bearing measurement. Does "em ess
                    # kay you" come back as four Word objects, one, or a single
                    # word "emesskayyou"? Everything downstream branches on it
                    # (README, ARCHITECTURE 6 branch table) and the regime
                    # detector (3.7) is what keeps a wrong answer to a degraded
                    # demo rather than a dead build.
                    #
                    # TODO(day1-05): confirm `confidence` and `word_is_final`
                    # are present on words inside PARTIAL turns, not only final
                    # ones. The detector runs on every partial; if confidence
                    # only arrives with the final, the ARM path has to move to
                    # the final and the 1.5 s politeness delay absorbs it.
                    turn = validate_turn(message, "live frame")
                    order = turn["turn_order"]
                    # Forward-only: a turn's final arrives after the endpoint
                    # timer, by which time the next turn's partials may already
                    # have started, and that late frame is not a turn beginning.
                    if self._current_turn is None or order > self._current_turn:
                        # TODO(day1-11): confirm turn_order is monotone within a
                        # session and never resets. The tape keys replacement on
                        # it, so a reset silently overwrites a committed turn.
                        self._begin_turn(order)
                    yield turn
                elif kind == "Begin":
                    self.session_id = message.get("id")
                    self.expires_at = message.get("expires_at")
                elif kind == "Termination":
                    # TODO(day1-08): confirm these two field names. The billing
                    # ledger multiplies session_duration_seconds by the socket
                    # count (3.11), and the A/B demo runs two sockets, so a
                    # wrong field here understates the bill by 2x.
                    self.audio_duration_seconds = message.get("audio_duration_seconds")
                    self.billed_seconds = message.get("session_duration_seconds")
                    break
                elif kind in ("Error", "error"):
                    # TODO(day1-10): confirm the error frame shape and the close
                    # codes for auth failure, quota exhaustion and a rejected
                    # parameter. The budget gate has to tell "out of credit"
                    # from "bad keyterm" to decide between the queue screen and
                    # replay mode (3.11).
                    raise SourceError(f"upstream error frame: {message}")
                else:
                    # TODO(day1-09): confirm the Heartbeat frame's name and
                    # fields. `total_duration_ms` enforces the 150 s per-session
                    # cap and `max_speech_probability` is one of the four
                    # conditions on speaking at all (4.8), so this branch is
                    # temporary: heartbeats get a real handler on day 1.
                    if kind:
                        self.unknown_frame_types[kind] = (
                            self.unknown_frame_types.get(kind, 0) + 1
                        )
        finally:
            if not self._closed:
                await self.terminate()

    # -- turning a live session into a fixture ---------------------------------
    def to_fixture_dict(self, name: str, description: str = "") -> dict[str, Any]:
        """Recorded session -> replay fixture, with no conversion of the frames.

        This is the reason the wire types are TypedDicts: what comes off the
        socket is what goes in the file is what the replay yields. Today's
        fixtures are hand-generated against the documented shape; from tonight
        they are recordings, and nothing downstream notices the difference.
        """
        return {
            "schema": "readback.fixture/1",
            "name": name,
            "description": description,
            "notes": [
                f"recorded from a live session, session_id={self.session_id}",
                f"speech_model={self.speech_model} sample_rate={self.sample_rate}",
            ],
            "frames": [
                {"emit_ms": item["recv_ms"], "frame": item["frame"]}
                for item in self.raw_frames
                if item["frame"].get("type") == "Turn"
            ],
        }


# ------------------------------------------------------------------ helpers --
def _bool_param(value: bool) -> str:
    """Query-string booleans, lowercase. Python's str(True) is "True", which
    several gateways read as a string and quietly treat as truthy either way --
    a class of bug that only shows up as "format_turns did not turn off"."""
    return "true" if value else "false"


def _encode_keyterms(keyterms: Sequence[str]) -> str:
    """TODO(day1-02): a JSON array in one query parameter is the documented
    form. If the server expects a repeated parameter instead, this becomes a
    list and `urlencode` gains doseq=True."""
    return json.dumps(list(keyterms))


def _dotenv_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def _resolve_api_key() -> str | None:
    """Settings first, then the unprefixed name. One function, both spellings.

    Settings is imported here rather than at module scope because this file is
    deliberately importable on a machine with no configuration at all -- that is
    what let every line of it be written and unit-tested before a key existed.
    """
    try:
        from server.config import get_settings

        key = get_settings().assemblyai_api_key.get_secret_value()
        if key:
            return key
    except Exception:                                       # pragma: no cover
        # A malformed .env or a missing dependency must not make the bare-name
        # fallback unreachable; a key that is present under the other spelling
        # is still a key.
        pass
    return os.environ.get("ASSEMBLYAI_API_KEY") or _key_from_dotenv()


def _key_from_dotenv() -> str | None:
    """Six lines instead of a dependency. The .env is gitignored and holds one
    key; anything more structured than this belongs in a settings module that
    does not exist yet."""
    path = _dotenv_path()
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("ASSEMBLYAI_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


__all__ = [
    "DEFAULT_ENCODING",
    "DEFAULT_SAMPLE_RATE",
    "DEFAULT_SPEECH_MODEL",
    "DEFAULT_URL",
    "FORMAT_TURNS",
    "LiveSource",
]
