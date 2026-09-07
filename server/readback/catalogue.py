"""ARCH 3.9: part numbers with no checksum at all. The catalogue is the
constraint.

A hypothesis is valid iff a row exists within edit distance 2 -- and UNIQUELY
so. Two rows equally close is not a match, it is the question the agent has
to ask; guessing between them would be the silent-wrong write this whole
product exists to refuse.

`signature` collapses acoustically confusable characters to one class
(solver.RHYME: B/D/E/P/T/V/Z/3 rhyme, A/H/J/K/8 rhyme, ...) so that a
mishear the ear cannot separate becomes an identity on the signature, and the
whole confusable neighbourhood of a heard string can be found with one equality
probe on catalogue_part.rhyme_signature before any edit distance is computed.
The in-memory index below scans instead -- a catalogue is a few hundred rows
and correctness is the point -- but it stores the same signature the table
does, so the two can never disagree about what rhymes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from server.readback.solver import RHYME

MAX_DISTANCE = 2


def normalise(value: str) -> str:
    """Upper-case alphanumerics only. 'bx-4471-a' and 'BX4471A' are one
    part number, and a run of spoken characters carries no hyphens."""
    return "".join(ch for ch in value.upper() if ch.isalnum())


def signature(value: str) -> str:
    """The rhyme class of every character, in order. Characters outside the
    table (nothing alphanumeric is) stand for themselves."""
    return "".join(RHYME.get(ch, ch) for ch in normalise(value))


def edit_distance(a: str, b: str, cap: int = MAX_DISTANCE) -> int:
    """Levenshtein, giving up at cap+1: nothing past the cap is ever used."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


@dataclass(frozen=True, slots=True)
class CatalogueMatch:
    sku: str            # as the catalogue spells it
    description: str
    distance: int       # 0 = heard exactly; 1-2 = the catalogue corrected it
    heard: str          # the normalised run that matched


@dataclass(frozen=True, slots=True)
class _Row:
    sku: str
    description: str
    norm: str
    sig: str


class CatalogueIndex:
    """The organisation's parts, ready to be asked "is this one of yours?"."""

    def __init__(self, rows: Iterable[tuple[str, str]]) -> None:
        seen: dict[str, _Row] = {}
        for sku, description in rows:
            norm = normalise(sku)
            if not norm or norm in seen:
                continue
            seen[norm] = _Row(sku.strip(), description, norm, signature(sku))
        self._rows: tuple[_Row, ...] = tuple(seen.values())
        self._by_norm = seen

    def __len__(self) -> int:
        return len(self._rows)

    @property
    def skus(self) -> tuple[str, ...]:
        """For the ARMED keyterm list: the recogniser is told what to expect."""
        return tuple(r.sku for r in self._rows)

    def match(self, candidate: str) -> CatalogueMatch | None:
        cand = normalise(candidate)
        if not cand:
            return None
        exact = self._by_norm.get(cand)
        if exact is not None:
            return CatalogueMatch(exact.sku, exact.description, 0, cand)
        scored: list[tuple[int, _Row]] = []
        for row in self._rows:
            d = edit_distance(cand, row.norm)
            if d <= MAX_DISTANCE:
                scored.append((d, row))
        if not scored:
            return None
        best = min(d for d, _ in scored)
        ties = [row for d, row in scored if d == best]
        if len(ties) != 1:
            # Ambiguous. Not a guess: the constraint cannot choose, so neither
            # may we. The caller treats None as "nothing to write".
            return None
        return CatalogueMatch(ties[0].sku, ties[0].description, best, cand)
