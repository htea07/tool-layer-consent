"""In-memory synthetic data. Swap this module for Firestore later

NOTE: This is fabricated data for a demonstrator. No real PHI ever lives here,
which is the responsible choice and worth stating in the README.
"""

from __future__ import annotations

import dataclasses

from models import Consent, Patient, Record, Referral, Scope

# One synthetic patient whose chart deliberately mixes three kinds of record:
#   - ordinary + referral-relevant (cardiology) -> disclosed
#   - ordinary + not relevant (primary_care, pulmonology) -> withheld by minimum-necessary
#   - specially protected (psychotherapy/SUD/HIV) -> withheld unless SPECIFICALLY authorized,
#     no matter how relevant; these are the categories real patients must sign to release.
# The patient below signed an ordinary referral consent and NO special-category authorization,
# so all three protected records stay out of the specialist's context. That's the money shot.
_PATIENTS: dict[str, Patient] = {
    "pat_001": Patient(
        id="pat_001",
        name="Jordan Rivera",
        dob="1979-03-14",
        insurance="BlueCross #BC-4471",
        records=(
            Record("rec_a", "cardiology", "Atrial fibrillation, dx 2021. On warfarin 5mg daily."),
            Record("rec_b", "cardiology",
                   "ECG on 2026-01-08 ordered by Dr. Alan Cho (MRN R445789, callback "
                   "617-555-0142): irregular rhythm, controlled rate."),
            Record("rec_e", "primary_care", "Annual physical 2026-02: BMI 24, BP 128/82."),
            # Ordinary but out of scope for a cardiology referral, until the workup raises a
            # clot/anticoagulation question and the patient pre-consented to it: the escalation demo.
            Record("rec_f", "pulmonology", "Provoked PE 2023 post-op; completed 6mo anticoagulation."),
            # Specially protected categories, each needs its own signed authorization.
            Record("rec_c", "behavioral_health",
                   "Psychotherapy note: processing work-related anxiety; CBT ongoing.",
                   protected_category="psychotherapy"),
            Record("rec_g", "addiction_medicine",
                   "Alcohol use disorder, in sustained remission; completed SUD program 2022.",
                   protected_category="sud"),
            Record("rec_d", "infectious_disease",
                   "HIV-1 positive 2019; undetectable viral load on ART.",
                   protected_category="hiv"),
        ),
    ),
}

_REFERRALS: dict[str, Referral] = {
    "ref_001": Referral(
        id="ref_001",
        patient_id="pat_001",
        specialist_org="cardiology_associates",
        reason="Arrhythmia workup, evaluate AFib management before elective surgery.",
        relevant_tags=frozenset({"cardiology"}),
    ),
}

_CONSENTS: dict[tuple[str, str, str], Consent] = {
    ("pat_001", "cardiology_associates", "ref_001"): Consent(
        patient_id="pat_001",
        specialist_org="cardiology_associates",
        referral_id="ref_001",
        scope=Scope.REFERRAL_RELEVANT,
        # Patient will release pulmonology on a justified escalation...
        escalation_allowed_tags=frozenset({"pulmonology"}),
        # ...but signed NO special-category authorization, so psychotherapy / SUD / HIV
        # stay withheld regardless of relevance, and can't be reached by escalation.
        authorized_categories=frozenset(),
    ),
}


def get_patient(patient_id: str) -> Patient | None:
    return _PATIENTS.get(patient_id)


def get_referral(referral_id: str) -> Referral | None:
    return _REFERRALS.get(referral_id)


def get_consent(patient_id: str, specialist_org: str, referral_id: str) -> Consent | None:
    return _CONSENTS.get((patient_id, specialist_org, referral_id))


def grant_additional_tag(referral_id: str, tag: str) -> Referral | None:
    """Broaden a referral's relevant_tags so newly in-scope records can be disclosed.

    This is the *effect* of a granted escalation, the policy decision itself lives in
    scope.evaluate_escalation(). Mutating the store here (vs. the frozen Referral) keeps
    the swap-for-a-real-DB story honest: in Firestore this is an UPDATE, nothing more.
    """
    ref = _REFERRALS.get(referral_id)
    if ref is None:
        return None
    _REFERRALS[referral_id] = dataclasses.replace(ref, relevant_tags=ref.relevant_tags | {tag})
    return _REFERRALS[referral_id]
