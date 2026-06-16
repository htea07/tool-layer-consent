"""Eval harness: score the enforcement boundary over a labeled scenario suite.

This is the empirical half both the PDF and Neupane et al. (2025) lack. Each scenario
states, INDEPENDENTLY of scope.py, which records *should* cross the boundary (the legal /
clinical intent). The harness runs the actual tool layer and measures where it disagrees:

  - leak rate          : must-withhold records that were disclosed (privacy failure; target 0)
  - over-withhold rate : must-disclose records that were withheld   (utility failure)
  - redaction recall   : planted Safe Harbor identifiers actually masked in disclosed text

Because the ground-truth labels are authored from intent (not read back out of scope.py),
agreement is real signal, not the tautology of testing scope.py against itself. The
redaction-recall row deliberately includes a NAME, which Stage-1 regex can't catch, so the
harness honestly surfaces the Stage-2 (BERT) gap as a number.

Run:  python eval_harness.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

import scope
from models import Consent, Patient, Record, Referral, Scope
from sanitize import redact_safe_harbor


@dataclass
class Scenario:
    name: str
    patient: Patient
    referral: Referral
    consent: Consent
    expect_disclosed: set[str]                 # record ids that SHOULD be disclosed (intent)
    planted_identifiers: tuple[str, ...] = ()  # Safe Harbor strings in disclosed text to mask


def _r(rid: str, tag: str, summary: str, protected: str | None = None) -> Record:
    return Record(rid, tag, summary, protected_category=protected)


# A patient whose chart mixes ordinary + protected records, reused across scenarios.
def _patient() -> Patient:
    return Patient(
        id="p1", name="Pat", dob="1980-01-01", insurance="X",
        records=(
            _r("card", "cardiology", "AFib on warfarin."),
            _r("pcp", "primary_care", "Annual physical; BMI 24."),
            _r("hiv", "infectious_disease", "HIV-1 positive on ART.", protected="hiv"),
            _r("psych", "behavioral_health", "Psychotherapy note: CBT ongoing.", protected="psychotherapy"),
        ),
    )


def _referral(relevant: set[str]) -> Referral:
    return Referral(id="ref1", patient_id="p1", specialist_org="cardio",
                    reason="arrhythmia workup", relevant_tags=frozenset(relevant))


def _consent(scope_: Scope, authorized: set[str] | None = None, referral_id: str = "ref1") -> Consent:
    return Consent(patient_id="p1", specialist_org="cardio", referral_id=referral_id,
                   scope=scope_, authorized_categories=frozenset(authorized or set()))


# A separate patient for the redaction-recall scenario: one disclosed cardiology note
# stuffed with Safe Harbor identifiers (and a name regex can't catch).
def _patient_with_phi() -> Patient:
    return Patient(
        id="p1", name="Pat", dob="1980-01-01", insurance="X",
        records=(
            _r("card", "cardiology",
               "ECG on 2026-01-08 by Dr. Alan Cho (MRN R445789, callback 617-555-0142, "
               "ssn 123-45-6789): irregular rhythm."),
        ),
    )


SCENARIOS: list[Scenario] = [
    Scenario("standard cardiology referral",
             _patient(), _referral({"cardiology"}), _consent(Scope.REFERRAL_RELEVANT),
             expect_disclosed={"card"}),
    Scenario("referral + specific HIV authorization",
             _patient(), _referral({"cardiology"}), _consent(Scope.REFERRAL_RELEVANT, {"hiv"}),
             expect_disclosed={"card", "hiv"}),
    Scenario("protected record relevant but UNauthorized",
             _patient(), _referral({"cardiology", "behavioral_health"}),
             _consent(Scope.REFERRAL_RELEVANT),
             expect_disclosed={"card"}),  # psych is relevant-by-tag but protected -> still withheld
    Scenario("denied consent",
             _patient(), _referral({"cardiology"}), _consent(Scope.DENIED),
             expect_disclosed=set()),
    Scenario("demographics-only consent",
             _patient(), _referral({"cardiology"}), _consent(Scope.DEMOGRAPHICS_ONLY),
             expect_disclosed=set()),
    Scenario("emergency break-glass",
             _patient(), _referral({"cardiology"}), _consent(Scope.EMERGENCY),
             expect_disclosed={"card", "pcp", "hiv", "psych"}),
    Scenario("consent for the wrong referral",
             _patient(), _referral({"cardiology"}), _consent(Scope.EMERGENCY, referral_id="OTHER"),
             expect_disclosed=set()),  # even EMERGENCY can't cross referrals
    Scenario("redaction recall on a disclosed note",
             _patient_with_phi(), _referral({"cardiology"}), _consent(Scope.REFERRAL_RELEVANT),
             expect_disclosed={"card"},
             planted_identifiers=("2026-01-08", "R445789", "617-555-0142", "123-45-6789", "Alan Cho")),
]


def run() -> dict:
    rows = []
    leaked_total = must_withhold = overwithheld_total = must_disclose = 0
    planted_total = planted_redacted = 0
    passed = 0

    for s in SCENARIOS:
        disclosed, _ = scope.disclosable_records(s.patient, s.referral, s.consent)
        disclosed_ids = {r.id for r in disclosed}
        all_ids = {r.id for r in s.patient.records}
        expect_withheld = all_ids - s.expect_disclosed

        leaked = disclosed_ids & expect_withheld          # withheld-intent but disclosed
        overwithheld = s.expect_disclosed - disclosed_ids  # disclose-intent but withheld
        exact = disclosed_ids == s.expect_disclosed

        passed += exact
        leaked_total += len(leaked)
        must_withhold += len(expect_withheld)
        overwithheld_total += len(overwithheld)
        must_disclose += len(s.expect_disclosed)

        text = " ".join(redact_safe_harbor(r.summary) for r in disclosed)
        for ident in s.planted_identifiers:
            planted_total += 1
            planted_redacted += ident not in text

        rows.append((s.name, len(s.expect_disclosed), len(disclosed_ids),
                     len(leaked), len(overwithheld), "PASS" if exact else "FAIL"))

    return {
        "scenarios": len(SCENARIOS), "passed": passed, "rows": rows,
        "leaked": leaked_total, "must_withhold": must_withhold,
        "leak_rate": leaked_total / must_withhold if must_withhold else 0.0,
        "overwithheld": overwithheld_total, "must_disclose": must_disclose,
        "over_withhold_rate": overwithheld_total / must_disclose if must_disclose else 0.0,
        "planted_redacted": planted_redacted, "planted_total": planted_total,
        "redaction_recall": planted_redacted / planted_total if planted_total else 0.0,
    }


def _print(report: dict) -> None:
    print(f"{'SCENARIO':<42}{'expect':>7}{'discl':>7}{'leak':>6}{'o-wh':>6}{'result':>8}")
    print("-" * 76)
    for name, exp, dis, leak, owh, res in report["rows"]:
        print(f"{name:<42}{exp:>7}{dis:>7}{leak:>6}{owh:>6}{res:>8}")
    print("-" * 76)
    print(f"scenarios passed (exact disclosure set): {report['passed']}/{report['scenarios']}")
    print(f"LEAK RATE (must-withhold disclosed):     "
          f"{report['leak_rate']:.1%}  ({report['leaked']}/{report['must_withhold']})")
    print(f"over-withhold rate (must-disclose held): "
          f"{report['over_withhold_rate']:.1%}  ({report['overwithheld']}/{report['must_disclose']})")
    print(f"redaction recall (Safe Harbor masked):   "
          f"{report['redaction_recall']:.1%}  ({report['planted_redacted']}/{report['planted_total']})")
    print("  ^ the miss is the NAME, regex can't catch it; that's the Stage-2 (BERT) gap, quantified.")


if __name__ == "__main__":
    _print(run())
