"""The specialist agent's tools: schema + implementation.

This is the wall between the specialist's model and the data. Every read of
clinical data routes through scope.py here, so the model literally never
receives a record it isn't allowed to see. The Anthropic tool *schemas* (what
Claude sees) and their implementations (what actually runs) live together.

Naming: this file is the SPECIALIST's tools. The PCP's tools are in pcp_tools.py.
Cross-principal transport (running another agent) lives in router.py.
"""

from __future__ import annotations

import data
import scope
from audit import AuditLog, DecisionEntry
from sanitize import redact_safe_harbor

# Tool schemas advertised to Claude. Descriptions are prescriptive about *when*
# to call each tool, recent Opus models reach for tools conservatively, so the
# trigger condition belongs in the description, not just the system prompt.
SPECIALIST_TOOLS = [
    {
        "name": "request_records",
        "description": (
            "Request the patient's clinical records for this referral. Call this "
            "once at the start, before reasoning about the case, to pull whatever "
            "records you are permitted to see. Returns only records the patient "
            "has consented to disclose for this referral; out-of-scope records are "
            "withheld and reported as a count."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why you need the records (one sentence).",
                }
            },
            "required": ["reason"],
        },
    },
    {
        "name": "request_additional_scope",
        "description": (
            "Request that an ADDITIONAL clinical specialty be added to this referral's "
            "disclosure scope. Call this only when your review surfaces an off-pathway "
            "concern the currently disclosed records can't address (e.g. a cardiac "
            "workup raises a pulmonary/clot question). You cannot widen your own access: "
            "this routes a modification request to the patient's consent policy, which "
            "grants or denies. If granted, call request_records again to load any newly "
            "in-scope records. Provide the specialty tag and a one-sentence justification."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "requested_tag": {
                    "type": "string",
                    "description": "Specialty tag to add to scope, e.g. 'pulmonology'.",
                },
                "reason": {
                    "type": "string",
                    "description": "One-sentence clinical justification.",
                },
            },
            "required": ["requested_tag", "reason"],
        },
    },
]


def run_request_records(referral_id: str, *, audit_log: AuditLog | None = None) -> dict:
    """Tool implementation. Returns a dict that becomes the tool_result content.

    Crucially, the `withheld` records never appear in the return value, only a
    count does. The model is told *that* something was withheld (honest) without
    being shown *what* (the enforcement).
    """
    referral = data.get_referral(referral_id)
    if referral is None:
        return {"error": f"unknown referral {referral_id}"}

    patient = data.get_patient(referral.patient_id)
    consent = data.get_consent(referral.patient_id, referral.specialist_org, referral_id)
    if patient is None or consent is None:
        return {"error": "no patient or consent on file"}

    disclosed, withheld = scope.disclosable_records(
        patient, referral, consent, audit_log=audit_log
    )

    out: dict = {
        "referral_reason": referral.reason,
        # Defense-in-depth: even on records cleared for disclosure, strip structured
        # Safe Harbor identifiers from the free text before it reaches the model.
        "disclosed_records": [
            {"id": r.id, "specialty": r.specialty_tag, "summary": redact_safe_harbor(r.summary)}
            for r in disclosed
        ],
        "withheld_count": len(withheld),
    }
    if scope.demographics_visible(consent):
        out["demographics"] = patient.demographics()
    return out


def run_request_additional_scope(
    referral_id: str,
    requested_tag: str,
    reason: str,
    *,
    audit_log: AuditLog | None = None,
) -> dict:
    """Tool implementation for clinical-drift escalation.

    The specialist asks; the patient consent policy (scope.evaluate_escalation)
    answers. On a grant we broaden the referral so the *next* request_records call
    discloses the newly in-scope records, still routed through scope.py. The
    specialist never reads anything by asking; it only changes what scope.py will
    later permit. Every outcome, grant or deny, is recorded.
    """
    referral = data.get_referral(referral_id)
    if referral is None:
        return {"error": f"unknown referral {referral_id}"}

    consent = data.get_consent(referral.patient_id, referral.specialist_org, referral_id)
    if consent is None:
        return {"error": "no consent on file"}

    granted, rationale = scope.evaluate_escalation(consent, requested_tag)
    if granted:
        data.grant_additional_tag(referral_id, requested_tag)

    if audit_log is not None:
        audit_log.record(
            DecisionEntry(
                action="escalation_request",
                patient_id=referral.patient_id,
                referral_id=referral_id,
                specialist_org=referral.specialist_org,
                scope=consent.scope.name,
                decision="granted" if granted else "denied",
                requested_tag=requested_tag,
                reason=reason,
            )
        )

    return {
        "requested_tag": requested_tag,
        "granted": granted,
        "rationale": rationale,
        "next_step": (
            "call request_records again to load the newly in-scope records"
            if granted
            else "proceed on the disclosed information only; do not speculate about withheld content"
        ),
    }
