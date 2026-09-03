"""LLM Gateway — the second signal, and nothing else.

ARCHITECTURE 3.8 says a format may not be asserted on shape alone: it needs a
carrier phrase, a registered owner-code prefix, or an LLM format-ID at >= 0.8.
The first two are lexical and already implemented in the detector. This is the
third, and it is the only place in this system that talks to a language model.

WHAT IT IS ALLOWED TO SEE, AND WHY THAT IS THE WHOLE DESIGN
-----------------------------------------------------------
Readback's promise is that the conversation around an identifier is never
persisted. Shipping that conversation to a third-party model would be worse than
persisting it — it would leave the building. So this module is given the
normalised character run and, at most, the carrier phrase that named it. Never
the tape, never the turn, never the words either side.

That is not a policy note; `identify_format` physically cannot see more, because
its only parameters are a candidate string and an optional carrier. There is no
argument through which a transcript could reach it. If a future caller wants to
"just add a bit of context for accuracy", that is the change to refuse.

The cost of the restriction is real: the model is classifying an 11-character
string with no conversational context, which is a harder problem than it would
be with the sentence around it. The measurement in `experiments/day1/llm_probe.py`
is what says whether that is good enough for the 0.8 gate.

WHY A MODEL AT ALL
------------------
Shape is a poor discriminator between the bare-digit formats — NHS is ten digits
and Luhn16 is sixteen, and the false-capture work (docs/FINDINGS.md) showed that
an evenly-read phone number produces exactly the same evidence a real NHS number
does. The check digit then resolves it 1-in-11 of the time by luck. A second
signal is what stops a coincidence being written down, and for a bare-digit run
with no carrier phrase there is no lexical signal available. This is that gap.

WHAT IT MUST NEVER DO
---------------------
Decide the characters. The model is asked WHICH FORMAT, never WHAT WAS SAID. The
solver owns the string; the arithmetic owns correctness. A model that could edit
the identifier would make every guarantee in docs/FINDINGS.md unprovable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Final

import httpx

log = logging.getLogger(__name__)

US_URL: Final = "https://llm-gateway.assemblyai.com/v1/chat/completions"
EU_URL: Final = "https://llm-gateway.eu.assemblyai.com/v1/chat/completions"

# Raw key, no Bearer. The Voice Agent API is the one product that wants Bearer,
# and this is not it -- getting that backwards is a 401 that reads like a bad key.
#
# MODEL CHOICE IS NOT A CHOICE ON THIS ACCOUNT, AND THAT IS MEASURED.
#
# The published catalogue lists 30-odd model ids. Probed one at a time against
# this key (experiments/day1, "model access"), exactly one of them answers:
#
#     qwen3.5-4b-32k-fast        200 OK
#     gpt-oss-20b / gemma-4-31b / qwen3-32B / gemini-* / gpt-5-* / claude-*
#                                400 "Your account does not have access to this
#                                     LLM Gateway model"
#
# So there is one model and there is no fallback. FALLBACK_MODELS is kept because
# access is an account property that can change, and a list of one is not worth a
# special case -- but nothing in this file should be written as though a second
# model exists today.
#
# And the one model that answers refuses structured output:
#
#     400  "model qwen3.5-4b-32k-fast does not support response_format"
#
# which the docs did not predict: they list "Alibaba Cloud Qwen" as supporting
# structured outputs, and that provider-family statement does not map onto this
# specific AssemblyAI-hosted variant. So the JSON has to be asked for in the
# prompt and parsed defensively, and `_parse_verdict` below has to treat
# unparseable output as a failure rather than guess -- because the failure mode
# of guessing is asserting a format, and asserting a wrong format is how a phone
# number gets written into a medical record.
DEFAULT_MODEL: Final = "qwen3.5-4b-32k-fast"
FALLBACK_MODELS: Final = ("gemini-3.5-flash-lite", "claude-haiku-4-5-20251001")

# Models known to accept `response_format`. Everything else is asked for JSON in
# the prompt instead. Membership is measured, never assumed from the provider.
STRUCTURED_OUTPUT_MODELS: Final = frozenset({
    "gemini-3.5-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash",
    "gpt-5-nano", "gpt-5-mini", "gpt-5.2",
    "claude-haiku-4-5-20251001", "claude-sonnet-4-6",
})

# Appended to the system prompt when the model cannot be constrained by schema.
# Explicit about the shape because a model that free-associates a sentence here
# produces an LLMUnavailable, which costs a second signal the capture needed.
JSON_INSTRUCTION: Final = """

Reply with a single JSON object and nothing else. No prose, no code fence.
{"format": "<one of the names above, or not_an_identifier>", \
"confidence": <number between 0 and 1>, "reason": "<one short sentence>"}"""

TIMEOUT_S: Final = 4.0
MAX_TOKENS: Final = 200

# The same enum the detector uses, so a hypothesis from here and one from the
# lexical cues are the same string and can be compared without translation.
FORMATS: Final = ("iso6346", "vin", "iban", "nhs", "luhn16", "catalogue",
                  "booking_ref", "not_an_identifier")

# ARCHITECTURE 3.8. Below this the format is not asserted and the capture stays
# unverified -- which is a question to the human, not a guess.
SECOND_SIGNAL_MIN_CONFIDENCE: Final = 0.8

SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "format": {"type": "string", "enum": list(FORMATS)},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["format", "confidence", "reason"],
    "additionalProperties": False,
}

# `not_an_identifier` is in the enum on purpose and is the most important value
# in it. A five-way forced choice would classify a phone number as an NHS number
# with high confidence, because among five wrong answers one is least wrong. The
# escape hatch is what lets the model decline, and declining is what the false-
# capture work showed this system needs most.
SYSTEM_PROMPT: Final = """\
You classify a string of characters that a person read aloud over the phone. \
You are told the characters and nothing else. Decide which reference format it \
is, if any.

iso6346  shipping container: 4 letters then 7 digits, 4th letter usually U
vin      vehicle identification: 17 characters, never I, O or Q
iban     UK bank account: GB, 2 digits, 4 letters, 14 digits
nhs      UK patient number: exactly 10 digits
luhn16   payment card: exactly 16 digits
catalogue    a part or stock number
booking_ref  a booking or order reference

Answer not_an_identifier when the digits are more likely a phone number, a date, \
a quantity, a price, or a time. A UK phone number is 11 digits and often starts \
07 or 02; a 10-digit run is NOT automatically an NHS number.

confidence is your probability that the format is correct, 0 to 1. Be \
conservative: a wrong format assertion causes a wrong number to be written down \
in a medical or shipping record. If two formats fit equally, say so in reason \
and give a confidence below 0.5."""


# MEASURED: the model is ANTI-CORRELATED on exactly the discrimination this
# component was built for, so it is not allowed to make it.
#
# NHS and Luhn16 are bare digit runs with no lexical surface. That is the gap the
# second signal was supposed to fill, because shape and rhythm cannot separate a
# ten-digit patient number from ten digits of a phone number. Measured over
# experiments/day1/llm_probe.py:
#
#   7700900123  a 10-digit window of a UK mobile   -> nhs, confidence 0.90
#               reason: "matches the UK NHS patient number format"
#   2026090114  a date and a time run together     -> nhs, confidence 0.80
#   9434765919  a REAL NHS number                  -> not_an_identifier, 0.70
#               reason: "likely a phone number rather than a patient number"
#
# It did not get these 70% right. It got them backwards: the phone number was
# called a patient number above the gate, and the patient number was called a
# phone number. On the lexically distinctive formats it is genuinely good --
# ISO 6346 0.85-0.95, IBAN 1.00, VIN 0.95, 6/6 -- because those have a shape a
# model can actually see. Bare digits have nothing to see, and a confident answer
# about nothing is worse than no answer, because no answer already means "ask the
# human" and this means "write it down".
#
# So the gate refuses them structurally. A future model that measures better can
# be let in by editing this set and re-running the probe -- and not otherwise.
BARE_DIGIT_FORMATS: Final = frozenset({"nhs", "luhn16"})


@dataclass(frozen=True, slots=True)
class FormatID:
    fmt: str
    confidence: float
    reason: str
    model: str

    @property
    def bare_digit(self) -> bool:
        return self.fmt in BARE_DIGIT_FORMATS

    @property
    def asserts(self) -> bool:
        """Does this clear the 3.8 gate?

        Confidence alone is not enough, and the extra condition is not caution --
        it is a measurement. See BARE_DIGIT_FORMATS above.
        """
        if self.fmt in ("not_an_identifier", "") or self.bare_digit:
            return False
        return self.confidence >= SECOND_SIGNAL_MIN_CONFIDENCE

    @property
    def refusal_reason(self) -> str | None:
        """Why a confident-looking verdict was still not allowed to assert."""
        if self.bare_digit and self.confidence >= SECOND_SIGNAL_MIN_CONFIDENCE:
            return (f"{self.fmt} is a bare-digit format; the model is measured "
                    f"anti-correlated on those and may not assert one")
        return None


def _parse_verdict(content: Any) -> tuple[str, float, str]:
    """Pull the verdict out of whatever came back. Fail rather than guess.

    With `response_format` the content is already the JSON object. Without it --
    which is the only path available on this account -- the model has been asked
    for bare JSON and usually complies, but may wrap it in a code fence or a
    sentence. Taking the outermost brace-delimited span handles both.

    What this deliberately does NOT do is fall back to keyword-matching the prose
    ("it looks like a container number"). A regex over free text would produce a
    format assertion from a sentence that might have been hedging, and this
    function's output goes on to gate whether a number is written down. There is
    no reading of a malformed answer that is safer than having no answer, because
    having no answer already has a defined behaviour: the capture stays
    unverified and the human is asked.
    """
    if isinstance(content, dict):
        parsed: Any = content
    else:
        text = str(content).strip()
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMUnavailable(f"no JSON object in response: {text[:120]!r}")
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise LLMUnavailable(f"malformed JSON: {exc}; got {text[:120]!r}") from exc

    if not isinstance(parsed, dict):
        raise LLMUnavailable(f"expected an object, got {type(parsed).__name__}")
    try:
        fmt = str(parsed["format"]).strip()
        confidence = float(parsed["confidence"])
    except (KeyError, TypeError, ValueError) as exc:
        raise LLMUnavailable(f"missing or unusable fields: {exc}") from exc
    return fmt, confidence, str(parsed.get("reason", ""))


class LLMUnavailable(Exception):
    """The gateway did not answer. Never a reason to assert a format, and never
    a reason to fail a capture: no second signal means the capture stays
    unverified and the human is asked, which is the same outcome as a low
    confidence."""


async def identify_format(
    candidate: str,
    *,
    api_key: str,
    carrier: str | None = None,
    model: str = DEFAULT_MODEL,
    base_url: str = US_URL,
    client: httpx.AsyncClient | None = None,
) -> FormatID:
    """Which format is this string, and how sure are you?

    `candidate` is the normalised character run — "MSKU4158005", not the audio
    and not the sentence. `carrier` is at most the phrase that named it ("container
    number"), because that phrase is already a cue in its own right and passing it
    lets the model agree or disagree with the detector rather than duplicate it.

    There is deliberately no parameter for surrounding text. See the module
    docstring.
    """
    if not candidate:
        raise ValueError("candidate is empty")

    user = f"Characters: {candidate}"
    if carrier:
        user += f'\nThe speaker said the words: "{carrier}"'

    structured = model in STRUCTURED_OUTPUT_MODELS
    system = SYSTEM_PROMPT if structured else SYSTEM_PROMPT + JSON_INSTRUCTION

    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": MAX_TOKENS,
    }
    if structured:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "format_id", "schema": SCHEMA, "strict": True},
        }

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_S)
    try:
        response = await client.post(
            base_url,
            headers={"authorization": api_key, "content-type": "application/json"},
            json=body,
        )
        if response.status_code >= 400:
            raise LLMUnavailable(f"{response.status_code}: {response.text[:200]}")
        payload = response.json()
    except httpx.HTTPError as exc:
        raise LLMUnavailable(str(exc)) from exc
    finally:
        if owns_client:
            await client.aclose()

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMUnavailable(f"no content in response: {exc}") from exc

    fmt, confidence, reason = _parse_verdict(content)

    if fmt not in FORMATS:
        raise LLMUnavailable(f"model returned a format outside the enum: {fmt!r}")

    # Clamped rather than trusted. A model is free to return 1.4, and a
    # confidence above 1 sailing through the 0.8 gate would be the gate failing
    # open -- which is the direction that writes wrong numbers down.
    confidence = max(0.0, min(1.0, confidence))
    return FormatID(fmt=fmt, confidence=confidence, reason=reason, model=model)


async def identify_with_fallback(
    candidate: str,
    *,
    api_key: str,
    carrier: str | None = None,
    models: tuple[str, ...] = (DEFAULT_MODEL, *FALLBACK_MODELS),
    base_url: str = US_URL,
) -> FormatID | None:
    """Try each model in order. None when every one of them failed.

    None is not "not an identifier" and callers must not collapse the two: one
    means the model declined, the other means nobody answered. Only the first is
    evidence.
    """
    last: Exception | None = None
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        for name in models:
            try:
                return await identify_format(
                    candidate, api_key=api_key, carrier=carrier,
                    model=name, base_url=base_url, client=client,
                )
            except LLMUnavailable as exc:
                last = exc
                log.info("format-id model %s unavailable: %s", name, exc)
    log.warning("format-id: every model failed, last error %s", last)
    return None
