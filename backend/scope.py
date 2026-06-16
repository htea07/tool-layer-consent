"""The core: minimum-necessary disclosure enforcement.

This is a pure function. It decides
what a specialist agent is allowed to see *before* any of that data reaches the
model's context. That's the thesis, permissions live here, in the tool layer,
not in a prompt instruction the model can be talked out of.
"""

# The standard structure for medical records is FHIR. We simplify it here so that
# specialty_tag stands in for code-based relevance mapping. In real FHIR you'd map
# ICD-10/SNOMED codes to a specialty rather than hand-tagging each record.

from __future__ import annotations

from audit import AuditLog, DecisionEntry
from models import PROTECTED_CATEGORIES, Consent, Patient, Record, Referral, Scope


def disclosable_records(
    patient: Patient,
    referral: Referral,
    consent: Consent,
    *,
    audit_log: AuditLog | None = None,
) -> tuple[list[Record], list[Record]]:
    """Return (disclosed, withheld) records for one referral under one consent.

    The contract every caller relies on:
      - disclosed + withheld together account for ALL of the patient's records
        (nothing silently vanishes, withheld is auditable).
      - the model only ever receives `disclosed`.
      - if `audit_log` is given, EVERY call records one structured decision (not
        just break-glass), that's what makes the boundary provable after the fact.

    Scope semantics:
      DENIED            -> nothing
      DEMOGRAPHICS_ONLY -> nothing (demographics are exposed via a separate path)
      REFERRAL_RELEVANT -> ordinary records whose specialty_tag is in referral.relevant_tags,
                           PLUS protected-category records ONLY where the patient gave a
                           specific authorization for that category (relevance can't reach them)
      EMERGENCY         -> everything, but flagged break-glass in the decision log
    """
    # Defensive: a consent for a different patient/referral must never apply here.
    mismatch = consent.patient_id != patient.id or consent.referral_id != referral.id

    if mismatch or consent.scope in (Scope.DENIED, Scope.DEMOGRAPHICS_ONLY):
        # No clinical records cross the boundary.
        disclosed, withheld, decision, break_glass = [], list(patient.records), "denied", False
    elif consent.scope == Scope.EMERGENCY:
        # Break-glass: even protected categories are released (42 CFR §2.51 emergency
        # exception), but the override is logged for mandatory after-the-fact review.
        disclosed, withheld, decision, break_glass = list(patient.records), [], "full", True
    else:  # REFERRAL_RELEVANT
        disclosed, withheld = [], []
        for r in patient.records:
            if r.protected_category is not None:
                # Protected: specific authorization required, regardless of relevance.
                ok = r.protected_category in consent.authorized_categories
            else:
                # Ordinary: minimum-necessary relevance.
                ok = r.specialty_tag in referral.relevant_tags
            (disclosed if ok else withheld).append(r)
        decision, break_glass = "partial", False

    if audit_log is not None:
        audit_log.record(
            DecisionEntry(
                action="disclose_records",
                patient_id=patient.id,
                referral_id=referral.id,
                specialist_org=consent.specialist_org,
                scope=consent.scope.name,
                decision=decision,
                disclosed_ids=tuple(r.id for r in disclosed),
                withheld_ids=tuple(r.id for r in withheld),
                break_glass=break_glass,
            )
        )

    return disclosed, withheld


def evaluate_escalation(consent: Consent, requested_tag: str) -> tuple[bool, str]:
    """Decide whether to grant an additional specialty tag on clinical escalation.

    This is the patient consent policy's call, NOT the specialist's. The specialist
    asks; this function, running in the tool layer, not the model, answers. Grant
    only what the patient pre-consented to release on escalation; everything else is
    routed for manual review (i.e., denied here). Returns (granted, rationale).
    """
    if consent.scope == Scope.DENIED:
        return False, "consent is denied for this referral; no escalation is possible"
    if requested_tag in PROTECTED_CATEGORIES:
        # Part 2 / psychotherapy / HIV: these need a specific written authorization the
        # patient signs, an autonomous agent escalation can never stand in for that.
        return False, (
            f"'{requested_tag}' is a specially protected category requiring specific written "
            "patient authorization (42 CFR Part 2 / psychotherapy notes / HIV statute); "
            "it cannot be granted via agent escalation"
        )
    if requested_tag in consent.escalation_allowed_tags:
        return True, f"patient pre-consented to release '{requested_tag}' on justified escalation"
    return False, (
        f"patient has not pre-consented to release '{requested_tag}'; "
        "routed for manual review, proceed on disclosed information only"
    )


def demographics_visible(consent: Consent) -> bool:
    """Demographics are released at DEMOGRAPHICS_ONLY and above (for scheduling)."""
    return consent.scope >= Scope.DEMOGRAPHICS_ONLY
