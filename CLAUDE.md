# Readback — rules for working in this repository

Each rule is here because breaking it cost something measurable. The evidence
is in `docs/FINDINGS.md`; the section numbers point at it.

## Evidence

- **Never bias the recogniser toward the set that validates its output.** If the
  constraint is a closed list, the list stays out of `keyterms_prompt` and out
  of the vocabulary pack. A match against a list the recogniser was handed is
  not evidence. Enforced by `runner.independent_keyterms` and
  `tests/test_catalogue_independence.py`. (§9)
- **A second signal must be independent of the first.** Owner prefixes may be
  pushed as keyterms because an ISO 6346 commit rests on arithmetic the
  recogniser cannot compute. Ask that question of every new signal. (§9)
- **No unmeasured numbers.** Thresholds, silence rates, error budgets, latency:
  if the sweep has not been run, write no figure. A number in a doc gets quoted
  back as a conclusion. Existing figures name the script that produced them.
- **"Silently wrong = 0" is not a claim this system can make.** 5.3% of acoustic
  error is invisible to the ISO check digit, in twelve known pairs. Say the
  residue is bounded and measured. (§4, §5)

## Behaviour

- **Silence is the product.** An agent that asks about every identifier is the
  "can you spell that" this exists to delete. Two thirds silent is the target;
  a change that buys accuracy by asking more has to say so out loud.
- **Always show the diff.** A repair the operator cannot see is indistinguishable
  from a system that guessed.
- **A capture that cannot be resolved is handed over, never guessed.** Ambiguity
  between two catalogue rows is a question, not a coin flip.

## Testing

- **Every fixture runs at both clocks**, instant and real-time. A gate that is a
  condition on time passing is not tested by a replay that fast-forwards; that
  check found the politeness-delay bug that would have lost the demo.
- **A passing test on unrepresentative input is not evidence.** Clean
  text-to-speech gives the recogniser no reason to reach for a prior, so it
  cannot reproduce a bias failure. Say what a test does *not* cover.
- **Never edit a `.py` file while a live end-to-end run is in flight.** The dev
  server runs with `--reload` and drops `_SESSIONS` on any edit.
- `python -m pytest tests -q` is the gate. It is currently green: 156 tests.
