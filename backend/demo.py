"""Plain, no-API walkthrough of the enforcement story, run it to SEE the trace.

    python demo.py

No ANTHROPIC_API_KEY needed: this drives the tool layer directly (the same
functions the agent calls), so you can watch every disclosure / escalation
decision land in the audit log without spending a token.
"""

from __future__ import annotations

import specialist_tools as st
from audit import AuditLog


def main() -> None:
    audit = AuditLog()

    print("STEP 1: specialist requests records on a cardiology referral")
    r = st.run_request_records("ref_001", audit_log=audit)
    print(f"        disclosed: {[x['specialty'] for x in r['disclosed_records']]}  "
          f"withheld: {r['withheld_count']}")
    print("        (withheld = unrelated primary-care/pulmonology AND protected "
          "psychotherapy/SUD/HIV the patient never authorized)")
    for rec in r["disclosed_records"]:
        print(f"          - {rec['summary']}")
    print("        ^ note the Safe Harbor identifiers (date/MRN/phone) redacted in the text\n")

    print("STEP 2: escalate, asking for pulmonology (ordinary, patient pre-consented)")
    e = st.run_request_additional_scope(
        "ref_001", "pulmonology", "AFib + planned surgery: need prior clot/anticoag history",
        audit_log=audit,
    )
    print(f"        granted: {e['granted']}  ({e['rationale']})\n")

    print("STEP 3: escalate, asking for sud (protected: 42 CFR Part 2)")
    e = st.run_request_additional_scope(
        "ref_001", "sud", "anticoagulation interacts with alcohol use", audit_log=audit,
    )
    print(f"        granted: {e['granted']}  ({e['rationale']})\n")

    print("STEP 4: re-request records after the pulmonology grant")
    r = st.run_request_records("ref_001", audit_log=audit)
    print(f"        disclosed: {[x['specialty'] for x in r['disclosed_records']]}  "
          f"withheld: {r['withheld_count']}")
    print("        (pulmonology now in scope; the three protected records remain withheld)\n")

    print("=== full decision log (every tool-layer decision, attributable) ===")
    print(audit.pretty())
    print(f"\nledger integrity verified (hash chain intact): {audit.verify()}")


if __name__ == "__main__":
    main()
