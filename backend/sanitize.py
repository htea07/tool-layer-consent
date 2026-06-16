"""Stage 1 of the hybrid sanitization pipeline: regex Safe Harbor de-identification.

Defense-in-depth on records we've ALREADY decided to disclose. The scope gates work
on whole records by tag; this works on the *text inside* a disclosed record, masking
the structured HIPAA Safe Harbor identifiers (SSN, phone, MRN, dates, email) that can
leak inside an otherwise-relevant note.

This mirrors Stage 1 of Neupane et al. (2025), "Towards a HIPAA Compliant Agentic AI
System in Healthcare." It is deliberately deterministic and dependency-free.

HONEST LIMITATION: regex cannot reliably catch *names* or other free-text contextual
PHI, that is exactly the job of the BERT/NER Stage 2 (deferred). So this layer is
necessary but not sufficient; it is the cheap, exact half of de-identification.
"""

from __future__ import annotations

import re

# Order matters: SSN (3-2-4) is checked before the phone pattern so it can't be
# mis-tagged. Each entry redacts to a labelled placeholder so the model still knows
# *that* something was removed (and what kind) without seeing the value.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("PHONE", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("MRN", re.compile(r"\b[A-Z]\d{6}\b")),
    ("DATE", re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b")),
]


def redact_safe_harbor(text: str) -> str:
    """Mask structured Safe Harbor identifiers in free text, leaving clinical content."""
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"[REDACTED: {label}]", text)
    return text
