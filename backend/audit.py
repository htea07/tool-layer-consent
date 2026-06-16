"""Structured, hash-chained decision log for every disclosure / escalation decision.

The thesis isn't just "withhold the right records", it's "be able to *prove*
afterward what was disclosed, what was withheld, and why, and prove the log itself
wasn't altered." So every decision the tool layer makes (not only break-glass) becomes
one structured `DecisionEntry`, and entries are hash-chained into a tamper-evident
ledger (sha256 over the previous hash + this entry's content).

This is what makes the system auditable AND evaluable: tests and the eval harness
assert against these entries, and `verify()` proves the chain is intact, matching
HIPAA's accountability expectation (45 CFR 164.316) and Neupane et al. (2025)'s
"decision logs secured via cryptographic hashing."
"""

from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

_GENESIS = "0" * 64  # prev_hash of the first entry, the root of the chain


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class DecisionEntry:
    """One immutable record of a single tool-layer decision.

    `action` is "disclose_records" or "escalation_request". The same shape covers
    both so the log reads as one ordered stream of what the boundary did. The two
    `*_hash` fields are filled in by AuditLog.record() when the entry is sealed.
    """

    action: str
    patient_id: str
    referral_id: str
    specialist_org: str
    scope: str                       # consent scope name at decision time
    decision: str                    # disclose: full|partial|denied ; escalation: granted|denied
    disclosed_ids: tuple[str, ...] = ()
    withheld_ids: tuple[str, ...] = ()
    requested_tag: str | None = None  # escalation only
    reason: str = ""
    break_glass: bool = False
    timestamp: str = field(default_factory=_now)
    prev_hash: str = ""              # hash of the previous ledger entry (chain link)
    entry_hash: str = ""             # sha256(prev_hash + content); set when recorded

    def summary(self) -> str:
        if self.action == "escalation_request":
            verb = "GRANTED" if self.decision == "granted" else "DENIED"
            return (
                f"{self.timestamp} escalation_request {verb} tag={self.requested_tag} "
                f"referral={self.referral_id} org={self.specialist_org} "
                f"reason={self.reason!r}"
            )
        bg = " [BREAK_GLASS]" if self.break_glass else ""
        return (
            f"{self.timestamp} disclose_records {self.decision}{bg} "
            f"referral={self.referral_id} org={self.specialist_org} scope={self.scope} "
            f"disclosed={list(self.disclosed_ids)} withheld={len(self.withheld_ids)}"
        )


def _payload(e: DecisionEntry) -> str:
    """Deterministic serialization of an entry's CONTENT (everything but the chain hashes)."""
    return repr((
        e.action, e.patient_id, e.referral_id, e.specialist_org, e.scope, e.decision,
        e.disclosed_ids, e.withheld_ids, e.requested_tag, e.reason, e.break_glass, e.timestamp,
    ))


@dataclass
class AuditLog:
    """Append-only, hash-chained decision ledger for one session.

    Behaves enough like a list (`len`, indexing, iteration) that tests can read it
    naturally. Its only mutation is `record()`, which seals each entry into the chain;
    `verify()` recomputes the chain and catches any later edit or reorder.
    """

    entries: list[DecisionEntry] = field(default_factory=list)

    def record(self, entry: DecisionEntry) -> DecisionEntry:
        prev = self.entries[-1].entry_hash if self.entries else _GENESIS
        digest = hashlib.sha256((prev + _payload(entry)).encode()).hexdigest()
        sealed = dataclasses.replace(entry, prev_hash=prev, entry_hash=digest)
        self.entries.append(sealed)
        return sealed

    def verify(self) -> bool:
        """Recompute the chain; return False if any entry was altered or reordered."""
        prev = _GENESIS
        for e in self.entries:
            expected = hashlib.sha256((prev + _payload(e)).encode()).hexdigest()
            if e.prev_hash != prev or e.entry_hash != expected:
                return False
            prev = e.entry_hash
        return True

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def __getitem__(self, i: int) -> DecisionEntry:
        return self.entries[i]

    def pretty(self) -> str:
        if not self.entries:
            return "  (no decisions recorded)"
        return "\n".join(f"  [{e.entry_hash[:8]}] {e.summary()}" for e in self.entries)
