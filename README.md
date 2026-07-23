# Enforcing Patient Consent Using AI Agents 

▶ Live demo: https://cross-principal-medical-referral.streamlit.app/

A working demonstrator of **minimum-necessary disclosure enforcement for
cross-principal agent communication**, grounded in healthcare referral. The thesis 
was the following:  "Don't ask the model to keep a secret; don't give it the secret."

Healthcare is a great example for how to direct two agents acting for different parties and exchanging sensitive data because the rules are legally defined and easy to verify. 

There are two agents acting for *different principals* with misaligned interests: a
referring physician's agent and a specialist's agent. They exchange clinical
information to coordinate care, under a permission boundary enforced in the
**tool layer**, not in a prompt.

> This is a demonstrator on **synthetic data**, not a HIPAA-compliant system.
> No real PHI is involved. It shows the *architecture* that HIPAA's
> "minimum necessary" rule and the special-category consent statutes demand; it
> is not compliance tooling.

## Why permissions live in the tool layer, not the prompt

The specialist's agent can only read clinical data by calling a tool. That
tool's implementation (`specialist_tools.py`) routes every read through
`scope.py`, which returns only the records the patient consented to disclose
*for this referral*. Out-of-scope records, such as a psychotherapy note on a cardiology
referral, are never returned, so they never enter the model's context.

The alternative, loading every record and instructing the model "don't reveal
the psych notes," is security theater: the data is already in context, and a
jailbreak or model error leaks it. **Don't ask the model to keep a secret;
don't give it the secret.**

## Two gates, because real consent has two shapes

`scope.py` decides disclosure with two independent gates:

1. **Minimum-necessary relevance** (ordinary records). A record's `specialty_tag`
   must be in the referral's `relevant_tags`. Cardiology records cross to a
   cardiology referral; an unrelated primary-care note does not. This is HIPAA's
   "minimum necessary" in code.

2. **Specific authorization** (protected records). Some categories like
   substance-use-disorder records (42 CFR Part 2), psychotherapy notes
   (HIPAA §164.508(a)(2)), and HIV status (state statutes) legally require a
   specific signed patient authorization, regardless of clinical relevance. A
   record marked `protected_category` is withheld **unless the patient authorized
   that exact category**, and relevance can never reach it. The escalation path
   refuses to widen into a protected category for the same reason: an autonomous
   agent can't stand in for a signature the patient never gave.

The escalation loop (`request_additional_scope`) is the dynamic half: when the
specialist surfaces an off-pathway concern, it can *ask* the patient's consent
policy to widen scope, but it can never widen its own access. The policy
(`scope.evaluate_escalation`) grants only what the patient pre-consented to;
everything else, and every protected category, is denied or routed to manual
review. Every decision/disclosure/escalation, granted or denied, is
written to a structured, attributable **decision log** (`audit.py`).

## Layout

```
backend/
  models.py            # data types: Scope, Patient, Record, Referral, Consent + PROTECTED_CATEGORIES
  scope.py             # THE core: disclosable_records() + evaluate_escalation() — pure, tested
  audit.py             # structured decision log: every disclosure/escalation decision, attributable
  data.py              # in-memory synthetic data (swap for Firestore later)
  specialist_tools.py  # specialist's tools (request_records, request_additional_scope); reads route through scope.py
  pcp_tools.py         # PCP's tool (message_specialist)
  agent.py             # specialist agent, hand-written tool-calling loop + session decision log
  pcp_agent.py         # PCP agent, hand-written tool-calling loop
  router.py            # cross-principal handoff PCP -> specialist (one-directional, depth 1)
  demo.py              # no-API walkthrough of the whole enforcement story
  tests/test_scope.py, tests/test_escalation.py
```

## Prior work & connection to this work

Tool-layer authorization for LLM agents is established practice (OWASP AI Agent
Security Cheat Sheet; Oso, Cerbos). The MCP authorization spec and Google's A2A
protocol tackle agent-to-agent delegation. What's under-explored is the **cross-principal** case, two agents with conflicting interests
negotiating **purpose-scoped, minimum-necessary** disclosure, including the
special-category consent (psychotherapy / HIV statuses) that genuinely requires
explicit patient authorization, as a concrete demonstrator.

## Run Locally

1. Clone
git clone https://github.com/htea07/tool-layer-consent.git
cd tool-layer-consent

2. (optional) virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

3. Install dependencies
pip install -r backend/requirements.txt

4. Launch the dashboard
cd backend
streamlit run app.py

