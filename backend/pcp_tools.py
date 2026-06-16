"""
The PCP's one tool is message_specialist. Cross-principal transport lives in router.py, alongside the
guardrails (hop limit, one-directional). 
"""

from __future__ import annotations

PCP_TOOLS = [
    {
        "name": "message_specialist",
        "description": (
            "Send this referral to the specialist's clinical agent and get their "
            "assessment back. Call this once you've decided the case warrants a "
            "specialist's review. Returns the specialist's written assessment, "
            "which you should then summarize for the patient's chart. You do not "
            "have direct access to the records, the specialist reviews them under "
            "the patient's consent and reports back."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": (
                        "What you're asking the specialist to do, in plain language "
                        "(e.g. 'assessment before surgery')."
                    ),
                }
            },
            "required": ["intent"],
        },
    }
]
