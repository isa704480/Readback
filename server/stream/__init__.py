"""Transcript sources: the seam between the detector and whatever produces turns.

`source.py` defines the contract. `replay.py` satisfies it from a file today;
`live.py` satisfies it from the AssemblyAI socket the moment a key exists.
Nothing downstream is allowed to know which one it holds.
"""

from .source import (
    ControlEvent,
    KEYTERM_LIMIT,
    KEYTERM_MAX_CHARS,
    BaseTranscriptSource,
    ConfigurationError,
    SourceClosed,
    SourceConfig,
    SourceError,
    TranscriptSource,
    Turn,
    Word,
    final_words,
    validate_turn,
)
from .tape import Tape

__all__ = [
    "BaseTranscriptSource",
    "ConfigurationError",
    "ControlEvent",
    "KEYTERM_LIMIT",
    "KEYTERM_MAX_CHARS",
    "SourceClosed",
    "SourceConfig",
    "SourceError",
    "Tape",
    "TranscriptSource",
    "Turn",
    "Word",
    "final_words",
    "validate_turn",
]
