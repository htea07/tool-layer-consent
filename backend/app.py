"""Streamlit dashboard for the cross-principal referral enforcement demo.

Three tabs:
  - How it works: the why behind the project (the explainer page).
  - Cases: pick a sample -> PCP/specialist conversation (animated) -> the PCP's chart summary,
    plus a tamper-evident ledger you can try to break and a what-if consent control.
  - Automated checks: the eval harness numbers over a labeled scenario suite.

Everything here is deterministic (computed by scope.py), no LLM, no API key.

Run:  streamlit run app.py
"""

from __future__ import annotations

import dataclasses
import time

import streamlit as st

import conversation as conv
import eval_harness
import samples
from models import PROTECTED_CATEGORIES, Scope

st.set_page_config(page_title="agent-referral", layout="wide")

SCOPE_LABEL = {
    "DENIED": "Denied: no records shared at all",
    "DEMOGRAPHICS_ONLY": "Demographics only: scheduling info (name/DOB/insurance), no clinical records",
    "REFERRAL_RELEVANT": "Referral-relevant only: records clinically related to this referral",
    "EMERGENCY": "Emergency (break-glass): full access in a life-safety emergency, logged for review",
}

ABOUT_MD = """
Background. The architecture follows the three-pillar framework in Neupane, Mittal & Rahimi,
*"Towards a HIPAA Compliant Agentic AI System in Healthcare"*
([arXiv:2504.17669](https://arxiv.org/abs/2504.17669), 2025): attribute-based access control,
hybrid PHI sanitization, and immutable audit. The consent model mirrors the real-world HL7 FHIR
Consent resource (and SAMHSA's Consent2Share), which encode machine-readable, purpose-scoped
patient consent.

---

## What this is

A working demonstrator, on synthetic data, of patient-consent enforcement between two AI agents
that work for different organizations. A referring clinic's agent sends a patient to a specialist's
agent; the two coordinate care, but the specialist only ever receives the records the patient agreed
to share. The boundary lives in code (the "tool layer"), so anything out of scope never reaches the
AI at all.

## Why is this important

A single medical referral pulls three parties with conflicting interests into the same exchange:

- **The patient** *(data owner)*: wants to minimize exposure of personal, genetic, and historical
  records to outside systems.
- **The referring clinic's agent** *(data custodian)*: is legally bound to disclose **only** what's
  relevant to this specific referral.
- **The specialist's agent** *(data consumer)*: needs enough clinical context to make safe decisions
  and avoid, for example, dangerous drug interactions.

U.S. law makes the patient the policy owner: HIPAA's "minimum necessary" rule, plus special-category
statutes for substance use (42 CFR Part 2), psychotherapy notes, HIV, and genetic data that each
require the patient's *specific* permission. As autonomous AI agents start coordinating care across
organizations, enforcing those boundaries on the AI itself becomes a real, unsolved problem, and
getting it wrong leaks protected health information.

## The wrong way

Load the patient's whole record into the AI and instruct it: *"here's everything, just don't reveal
the sensitive parts."* This is security theater. The sensitive data is now sitting in the model's
context, one prompt-injection, jailbreak, or model slip away from leaking. You're trusting the model
to keep a secret you already handed it.

## The right way

The AI can only read records by calling a tool, and that tool decides, in code and before anything
reaches the model, exactly what the patient consented to share. Everything else is never loaded.

> Don't ask the model to keep a secret; don't give it the secret.

Three things make that boundary trustworthy:

- **Two gates on every record.** *(1) Minimum-necessary relevance*: ordinary records are shared only
  if clinically related to this referral. *(2) Specific authorization*: protected categories
  (psychotherapy, substance use, HIV, genetic) are withheld no matter how relevant, unless the
  patient signed a specific authorization.
- **Escalation only an outside party can grant.** If the specialist hits a new concern mid-case, it
  can *ask* to widen sharing, but it can **never** widen its own access, and protected categories
  can't be unlocked this way (they need a real signature). Authority only shrinks unless the patient
  or referring clinic widens it.
- **A tamper-evident audit log.** Every decision is recorded in a cryptographic hash chain, so any
  later edit is detectable, giving a trustworthy record of who got what.

## The audit log and compliance

HIPAA compliance is not only about enforcing the rule in the moment. It is about being able to prove
afterward what happened, for breach investigations, regulator audits, and patient access reports
(45 CFR §164.312(b) audit controls; §164.316 requires six-year retention). A privacy system that
cannot produce a trustworthy record of who accessed what is not compliant, however good its
enforcement.

A complete design keeps two logs, for two different jobs:

- **Interaction log (clinical state audit):** the full, raw dialogue of the specialist agent's
  reasoning loop, including its intermediate thinking, the prompt templates it ran, and every raw
  tool call. This is the clinical and debugging trail: what the agent saw and how it reasoned.
- **Decision log (compliance policy audit):** the structured metadata of every policy decision the
  enforcement layer made (what was disclosed, what was withheld, escalations, break-glass). This is
  the compliance record.

This project implements the decision log as a hash-chained, tamper-evident ledger (shown in each case
under "Audit log"), so the record of every sharing decision is both auditable and provably unaltered.

## Redacting identifiers (regex + NER)

Deciding which whole records to share is only half of "minimum necessary." A record cleared for
disclosure (say, a relevant cardiology note) can still contain identifiers buried in its free text.
So before any disclosed text reaches the specialist, it passes through a hybrid sanitization pipeline:

- **Stage 1 (regex):** Pattern-matches the structured HIPAA Safe Harbor identifiers (SSN,
  phone, MRN, dates, email) and masks them. Deterministic, fast, and exact for anything with a
  predictable shape.
- **Stage 2 (clinical NER):** A medical language model (for example BioBERT) *would* catch the
  contextual identifiers regex cannot, above all **names**, which have no fixed pattern.

Only Stage 1 exists today. The two stages are complementary: regex is precise but blind to names,
while an NER model would handle the fuzzy cases. Redaction recall sits at 80%, and the missing 20% is
the names that the not-yet-built Stage 2 would catch.

---

*Everything here is synthetic: no real patient data. The share / withhold / escalation / redaction
decisions are computed by the real enforcement code (and unit-tested); the agents' chat wording is
templated (no live model in this view).*
"""

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Sora:wght@600;700&display=swap');

      html, body, .stApp, .stMarkdown, .stMarkdown p, .stMarkdown li, .stChatMessage {
          font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      }
      h1, h2, h3, h4 { font-family: 'Sora', 'Inter', sans-serif; letter-spacing: -0.01em; }

      /* readable, larger body copy (esp. the About page) */
      .stMarkdown p, .stMarkdown li { font-size: 1.1rem; line-height: 1.7; }
      .stMarkdown h2 { font-size: 1.75rem; margin-top: 1.7rem; border-left: 4px solid #1F7A8C; padding-left: 0.6rem; }
      .stMarkdown h3 { font-size: 1.3rem; }
      .stMarkdown h4 { font-size: 1.5rem; font-weight: 600; }

      /* Make the What-if / New-here bars match the "Choose a sample case" selectbox bar */
      [data-testid="stExpander"] {
          background: #FFFFFF;
          border: 1px solid rgba(49, 51, 63, 0.2);
          border-radius: 0.5rem;
      }
      [data-testid="stExpander"] summary { display: flex; align-items: center; padding: 0.55rem 0.9rem; }
      [data-testid="stExpander"] summary p { font-size: 1.1rem !important; font-weight: 400; margin: 0; }
      /* Put the expander arrow on the right, matching the dropdown bars */
      [data-testid="stExpander"] summary svg { order: 99; margin-left: auto !important; }
      .stMarkdown blockquote { font-size: 1.2rem; font-style: italic; color: #0E4A54; }
      .stChatMessage p { font-size: 1.06rem; }
      .stChatMessage code, .stMarkdown code { font-size: 1em; }
      /* per-speaker bubble tints */
      [class*="st-key-msg-pcp"] [data-testid="stChatMessage"] { background: #EAF2FB; }
      [class*="st-key-msg-specialist"] [data-testid="stChatMessage"] { background: #E7F4F1; }
      [class*="st-key-msg-system"] [data-testid="stChatMessage"] { background: #FBF3E6; }
      div[data-baseweb='select'] > div { font-size: 1.1rem; }
      .stTabs [data-baseweb="tab"] { font-size: 1.35rem; font-weight: 600; }
      .stTabs [data-baseweb="tab"] p { font-size: 1.35rem !important; font-weight: 600; }

      /* hero headline */
      .hero { background: #EEF6F7; border: 1px solid #D8E8EA; border-radius: 0.6rem;
              padding: 1.1rem 1.3rem; margin-bottom: 1.3rem; }
      .hero h1 { font-size: 2.7rem; line-height: 1.12; margin: 0 0 .5rem; color: #0E2233; }
      .hero p  { font-size: 1.3rem; line-height: 1.5; color: #45566B; margin: 0; max-width: 64ch; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
      <h1>Cross-principal healthcare referrals</h1>
      <p>Two AI agents, two organizations, one patient's consent: sharing only what the patient
      agreed to, enforced in code where prompt-injection and jailbreaks can't reach it.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

about_tab, cases_tab, eval_tab = st.tabs(
    ["How it works", "Cases", "Automated checks"]
)

with about_tab:
    st.markdown(ABOUT_MD)

# =========================================================================================
# CASES
# =========================================================================================
with cases_tab:
    with st.expander("New here? What the terms mean"):
        st.markdown(
            "- **Disclosed / withheld:** whether a record was shared with the specialist. "
            "Withheld records never reach the specialist *at all*.\n"
            "- **Referral-relevant:** only records clinically related to *this* referral are "
            'shared (the HIPAA "minimum necessary" rule).\n'
            "- **Protected category:** extra-sensitive data (psychotherapy, substance use, HIV, "
            "genetic) that needs the patient's *specific* written OK, no matter how relevant.\n"
            "- **Escalation:** if the specialist spots a new concern, they can *ask* to widen "
            "sharing; the patient's policy grants or denies. They can't widen it themselves.\n"
            "- **Break-glass:** an emergency full-access override, always logged for review.\n"
            "- **[REDACTED: …]:** identifiers (names, dates, MRNs, phone numbers) masked in shared notes.\n"
            "- **Sealed ledger:** every decision is recorded in a tamper-evident hash chain."
        )

    st.markdown("#### Choose a sample case")
    titles = [s.title for s in samples.SAMPLES]
    pick = st.selectbox("sample case", titles, index=0, label_visibility="collapsed")
    sample = next(s for s in samples.SAMPLES if s.title == pick)
    c = sample.consent

    # What-if: let the viewer re-decide the case under a different consent.
    with st.expander("What-if: change this patient's consent and re-run the case"):
        scope_names = [s.name for s in Scope]
        ws = st.selectbox("Sharing level", scope_names, index=scope_names.index(c.scope.name),
                          format_func=lambda n: SCOPE_LABEL[n], key=f"scope::{pick}")
        wa = st.multiselect("Specifically authorized categories", sorted(PROTECTED_CATEGORIES),
                            default=sorted(c.authorized_categories), key=f"auth::{pick}")
    eff_consent = dataclasses.replace(c, scope=Scope[ws], authorized_categories=frozenset(wa))
    eff_sample = dataclasses.replace(sample, consent=eff_consent)
    changed = eff_consent.scope != c.scope or set(wa) != set(c.authorized_categories)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**PCP request**")
        st.info(f"To **{sample.referral.specialist_org}**\n\nReason: _{sample.referral.reason}_")
    with col2:
        st.markdown("**Patient consent**" + ("  ·  *hypothetical*" if changed else ""))
        auth = ", ".join(sorted(eff_consent.authorized_categories)) or "none"
        esc = ", ".join(sorted(eff_consent.escalation_allowed_tags)) or "none"
        st.warning(
            f"**Sharing level:** {SCOPE_LABEL[eff_consent.scope.name]}\n\n"
            f"**Extra-sensitive categories specifically allowed:** {auth}\n\n"
            f"**If a new concern arises, widening pre-approved for:** {esc}"
        )
        if changed:
            st.caption(
                "You changed the consent above, so this is a hypothetical. The patient's real "
                f"consent for this case is: {SCOPE_LABEL[c.scope.name]}."
            )

    st.markdown("### Conversation")
    turns, audit, summary = conv.build_transcript(eff_sample)
    meta = {
        conv.PCP: ("PCP agent", "🧑‍⚕️"),
        conv.SPEC: ("Specialist agent", "🩺"),
        conv.SYS: ("Consent enforcement", "🔒"),
    }
    # Animate the reveal once per (case + consent) state; instant on later reruns so clicking
    # tamper/what-if doesn't replay the whole thing.
    play_key = (
        f"played::{pick}::{eff_consent.scope.name}::"
        f"{','.join(sorted(eff_consent.authorized_categories))}"
    )
    if st.button("Replay conversation", type="primary"):
        st.session_state.pop(play_key, None)
        st.rerun()
    st.caption("After changing the what-if consent above, hit Replay to watch the case re-decide.")

    animate = play_key not in st.session_state
    for i, (role, text) in enumerate(turns):
        name, avatar = meta[role]
        with st.container(key=f"msg-{role}-{i}"):
            with st.chat_message(name, avatar=avatar):
                if animate:
                    ph = st.empty()
                    ph.markdown(f"**{name}**  \n*▌ typing…*")
                    time.sleep(0.7)
                    ph.markdown(f"**{name}**  \n{text}")
                    time.sleep(0.4)
                else:
                    st.markdown(f"**{name}**  \n{text}")
    st.session_state[play_key] = True

    st.markdown("### Summary the PCP gets for the chart")
    st.success(summary)

    st.markdown("### Audit log")
    st.caption(
        "Every sharing decision is recorded here in order, as a tamper-evident hash chain: each "
        "line starts with a short fingerprint (a SHA-256 hash of that line plus the previous "
        "line's fingerprint), so any later edit to the record is detectable. HIPAA requires "
        "keeping an auditable record of who accessed what (45 CFR §164.312)."
    )
    for e in audit:
        st.code(f"[{e.entry_hash[:8]}] {e.summary()}", language=None)

# =========================================================================================
# AUTOMATED CHECKS
# =========================================================================================
with eval_tab:
    st.markdown(
        "**Automatic checks** replay the enforcement engine against example situations that have "
        "a *known-correct* answer, to prove it behaves. (This is the part most privacy demos skip.)"
    )
    st.markdown(
        "- **Leak rate:** did it ever share a record it *shouldn't*? (target: 0%)\n"
        "- **Over-withhold:** did it hold back a record it *should* have shared?\n"
        "- **Redaction recall:** of identifiers planted in shared notes, how many got masked?"
    )
    rep = eval_harness.run()
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Situations passed", f"{rep['passed']}/{rep['scenarios']}")
    e2.metric("Leak rate", f"{rep['leak_rate']:.0%}")
    e3.metric("Over-withhold", f"{rep['over_withhold_rate']:.0%}")
    e4.metric("Redaction recall", f"{rep['redaction_recall']:.0%}")
    st.dataframe(
        [
            {"situation": r[0], "should share": r[1], "shared": r[2],
             "leaked": r[3], "over-withheld": r[4], "result": r[5]}
            for r in rep["rows"]
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "Each row is one situation; result = PASS when the system's sharing decision matched the "
        "known-correct answer. Redaction recall below 100% is the names regex can't catch; a clinical "
        "NER stage (the planned next step, not yet built) would close that gap."
    )
