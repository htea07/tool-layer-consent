"""Domain types for the cross-principal referral demonstrator.

The whole point of keeping these
dumb is that scope.py (the part that matters) can be reasoned about and tested
without any of the agent machinery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

# Categories that require SPECIFIC written patient authorization to disclose, over and
# above ordinary minimum-necessary relevance: substance-use-disorder treatment records
# (42 CFR Part 2), psychotherapy notes (HIPAA 164.508(a)(2)), HIV status (state statutes),
# and genetic information (GINA). These can never be reached by the relevance path, only
# by explicit consent (or a logged emergency override). This is where granular consent lives.
PROTECTED_CATEGORIES: frozenset[str] = frozenset({"psychotherapy", "sud", "hiv", "genetic"})


class Scope(IntEnum):
    """Consent scopes, ordered least → most disclosure.

    IntEnum so we can compare with >= : a granted scope of REFERRAL_RELEVANT
    implies everything DEMOGRAPHICS_ONLY would allow, and so on. EMERGENCY is
    the "break-glass" level, full access, but it gets logged (see scope.py).
    """
    # Enum helps ordered comparison, higher level, all lower permissions implied
    # Names instead of random numbers used to call

    DENIED = 0
    DEMOGRAPHICS_ONLY = 1
    REFERRAL_RELEVANT = 2
    EMERGENCY = 3


@dataclass(frozen=True)
class Record:
    """One clinical record.

    Two independent gates decide whether it crosses the boundary:
      - `specialty_tag` drives minimum-necessary relevance for ORDINARY records: a
        cardiology referral discloses "cardiology" and withholds "primary_care".
      - `protected_category`, if set, OVERRIDES relevance: the record is a specially
        protected category (see PROTECTED_CATEGORIES) and is withheld unless the
        patient specifically authorized THAT category, relevant or not.
    """

    id: str
    specialty_tag: str          # e.g. "cardiology", "pulmonology", "primary_care"
    summary: str                # human-readable; in a real system this is the PHI
    protected_category: str | None = None  # e.g. "psychotherapy", "sud", "hiv"; None = ordinary


@dataclass(frozen=True)
class Patient:
    id: str
    name: str
    dob: str
    insurance: str
    records: tuple[Record, ...] = ()

    def demographics(self) -> dict:
        return {"name": self.name, "dob": self.dob, "insurance": self.insurance}


@dataclass(frozen=True)
class Referral:
    """A referral from a PCP to a specialist org for a specific condition."""

    id: str
    patient_id: str
    specialist_org: str
    reason: str
    relevant_tags: frozenset[str]   # which specialty tags are "relevant" to this referral


@dataclass(frozen=True)
class Consent:
    """The patient's standing consent governing one referral's disclosure.

    Directed: it's the patient granting `scope` to `specialist_org` for
    `referral_id`. A different org, or a different referral, has its own consent.
    """

    patient_id: str
    specialist_org: str
    referral_id: str
    scope: Scope
    # Specialties the patient pre-consents to release *if* the specialist surfaces a
    # justified off-pathway concern (clinical drift). The specialist can never widen
    # its own access; this is the patient policy that an escalation is checked against.
    escalation_allowed_tags: frozenset[str] = frozenset()
    # Specially protected categories the patient signed a SPECIFIC authorization for
    # (Part 2 / psychotherapy / HIV). Empty means no special-category release, the
    # default, and the realistic case for a routine referral.
    authorized_categories: frozenset[str] = frozenset()
