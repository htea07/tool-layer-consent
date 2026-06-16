"""Turn a Sample into a PCP<->specialist conversation, driven by the real tool layer.

The disclosure/escalation decisions here are NOT scripted, they're computed by scope.py
and recorded in a hash-chained ledger, exactly as the live agents would. Only the agents'
natural-language wording is templated (there's no LLM in this path, so it needs no API key).
Swap the SPEC turns for agent.py output to get live model reasoning.
"""

from __future__ import annotations

import dataclasses

import scope
from audit import AuditLog, DecisionEntry
from models import Scope
from sanitize import redact_safe_harbor
from samples import Sample

PCP = "pcp"
SPEC = "specialist"
SYS = "system"


def _why(rec, consent) -> str:
    if consent.scope == Scope.DENIED:
        return "consent denied for this referral"
    if consent.scope == Scope.DEMOGRAPHICS_ONLY:
        return "demographics-only scope: no clinical records"
    if rec.protected_category is not None:
        return f"protected category, no specific authorization on file"
    return "not clinically relevant to this referral"


def _disclosure_md(disclosed, withheld, consent) -> str:
    lines = [f"`request_records` → **{len(disclosed)} disclosed, {len(withheld)} withheld**"]
    for r in disclosed:
        lines.append(f"- ✅ `{r.specialty_tag}`: {redact_safe_harbor(r.summary)}")
    if withheld:
        lines.append(f"- ⛔ **{len(withheld)} withheld** (never enter the specialist's context):")
        for r in withheld:
            lock = f" 🔒{r.protected_category}" if r.protected_category else ""
            lines.append(f"    - `{r.specialty_tag}`{lock}: {_why(r, consent)}")
    return "\n".join(lines)


def _chart_summary(sample: Sample, disclosed, withheld, audit: AuditLog) -> str:
    """The note the PCP receives back for the patient's chart, plain English, deterministic."""
    org = sample.referral.specialist_org
    reason = sample.referral.reason
    n, m = len(disclosed), len(withheld)
    broke = any(e.break_glass for e in audit if e.action == "disclose_records")

    if n == 0 and sample.consent.scope == Scope.DEMOGRAPHICS_ONLY:
        return (
            "**Intake:** scheduling demographics (name, DOB, insurance) released for appointment "
            "setup. **No clinical records were shared**, none are needed to book a visit. "
            "Decision ledger sealed and verified."
        )
    if n == 0:
        return (
            f"**Referral:** {reason}\n\n"
            f"**Outcome:** No records were shared under the patient's consent, so {org} could "
            f"not complete an assessment. Obtain the appropriate consent or clarify the referral "
            f"before re-sending.\n\n"
            f"**Privacy:** {m} record(s) withheld; decision ledger sealed and verified."
        )
    specialties = ", ".join(sorted({r.specialty_tag for r in disclosed}))
    glass = ", via an emergency break-glass override, logged for mandatory review" if broke else ""
    withheld_line = (
        f"{m} record(s) were withheld under the patient's consent (protected categories and "
        f"out-of-scope history) and were not reviewed."
        if m else "All of the patient's records were in scope for this referral."
    )
    return (
        f"**Referral:** {reason}\n\n"
        f"**Specialist ({org}){glass}:** reviewed {n} record(s) covering {specialties}; "
        f"assessment completed on the disclosed records only.\n\n"
        f"**Privacy:** {withheld_line} Decision ledger sealed and verified."
    )


def build_transcript(sample: Sample) -> tuple[list[tuple[str, str]], AuditLog, str]:
    audit = AuditLog()
    turns: list[tuple[str, str]] = []
    patient, referral, consent = sample.patient, sample.referral, sample.consent

    turns.append((PCP, f"Referring this patient to **{referral.specialist_org}**. "
                       f"Reason: _{referral.reason}_. Please review and advise."))
    turns.append((SPEC, "Acknowledged. Requesting the records I'm permitted to see for this referral."))

    disclosed, withheld = scope.disclosable_records(patient, referral, consent, audit_log=audit)
    if audit[-1].break_glass:
        turns.append((SYS, "⚠️ **Emergency override (break-glass):** full access granted and logged "
                           "for mandatory review."))
    turns.append((SYS, _disclosure_md(disclosed, withheld, consent)))

    if consent.scope == Scope.DEMOGRAPHICS_ONLY and scope.demographics_visible(consent):
        d = patient.demographics()
        turns.append((SYS, f"📇 Demographics released for scheduling only: "
                           f"{d['name']} · {d['dob']} · {d['insurance']}, no clinical records."))

    for tag, reason in sample.escalations:
        turns.append((SPEC, f"My review raises an off-pathway concern. Requesting additional scope: "
                            f"**{tag}**: {reason}."))
        granted, rationale = scope.evaluate_escalation(consent, tag)
        audit.record(DecisionEntry(
            action="escalation_request", patient_id=patient.id, referral_id=referral.id,
            specialist_org=referral.specialist_org, scope=consent.scope.name,
            decision="granted" if granted else "denied", requested_tag=tag, reason=reason,
        ))
        turns.append((SYS, f"{'✅ **GRANTED**' if granted else '⛔ **DENIED**'}: {rationale}"))
        if granted:
            referral = dataclasses.replace(referral, relevant_tags=referral.relevant_tags | {tag})
            turns.append((SPEC, "Thank you. Re-requesting records now that scope is widened."))
            disclosed, withheld = scope.disclosable_records(patient, referral, consent, audit_log=audit)
            turns.append((SYS, _disclosure_md(disclosed, withheld, consent)))

    if disclosed:
        specialties = ", ".join(sorted({r.specialty_tag for r in disclosed}))
        turns.append((SPEC, f"Assessment (on the disclosed records only): reviewed "
                            f"{len(disclosed)} record(s) covering {specialties}. I won't speculate "
                            f"about withheld content."))
    else:
        turns.append((SPEC, "No records were disclosed under the current consent, so I cannot "
                            "provide a clinical assessment."))
    turns.append((PCP, "Understood. Summarizing for the patient's chart."))
    summary = _chart_summary(sample, disclosed, withheld, audit)
    return turns, audit, summary
