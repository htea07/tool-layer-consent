"""A single tool-calling agent loop, written by hand.

This is the manual agentic loop (not the SDK's auto tool-runner) on purpose:
you should see the call -> tool_use -> tool_result -> call cycle explicitly,
because that cycle IS the skill you're here to learn. Once you've felt it raw,
you'll understand what a framework abstracts.

Run directly to drive the specialist agent against the seeded referral:
    python agent.py
(requires ANTHROPIC_API_KEY in the environment)
"""

from __future__ import annotations

import json

import anthropic

import specialist_tools
from audit import AuditLog

MODEL = "claude-opus-4-8"
MAX_HOPS = 8  # safety cap so a misbehaving loop can't run forever


def run_specialist_agent(referral_id: str, task: str) -> str:
    """Run the specialist's agent over one referral and return its final text.

    `task` is the human/PCP instruction (the kickoff). The agent decides when to
    call request_records; we execute it through the scope-enforcing tool layer.
    """
    client = anthropic.Anthropic()

    system = (
        "You are a specialist physician's clinical agent reviewing an incoming "
        "referral. Request the records you're permitted to see, then give a brief "
        "assessment. If records were withheld as out-of-scope, acknowledge that "
        "you proceeded only on the disclosed information, do not speculate about "
        "withheld content. If your review surfaces a concern on a DIFFERENT clinical "
        "pathway that the disclosed records can't address, you may use "
        "request_additional_scope to ask the patient's consent policy to widen scope; "
        "you cannot widen it yourself, and it may be denied."
    )
    messages: list[dict] = [{"role": "user", "content": task}]
    audit = AuditLog()  # one decision log for the whole session

    for _ in range(MAX_HOPS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=system,
            tools=specialist_tools.SPECIALIST_TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            # Done, print the full decision log, then return the final text block.
            print("\n=== decision log (every tool-layer decision) ===")
            print(audit.pretty())
            return next((b.text for b in response.content if b.type == "text"), "")

        # Append the assistant turn (with its tool_use blocks) before answering.
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "request_records":
                result = specialist_tools.run_request_records(referral_id, audit_log=audit)
                # Print the enforcement decision so the demo trace is legible.
                print(
                    f"  [tool] request_records -> {len(result['disclosed_records'])} "
                    f"disclosed, {result['withheld_count']} withheld (out of scope)"
                )
            elif block.name == "request_additional_scope":
                result = specialist_tools.run_request_additional_scope(
                    referral_id,
                    block.input["requested_tag"],
                    block.input["reason"],
                    audit_log=audit,
                )
                verb = "GRANTED" if result.get("granted") else "DENIED"
                print(
                    f"  [tool] request_additional_scope({result.get('requested_tag')}) -> {verb}"
                )
            else:
                result = {"error": f"unknown tool {block.name}"}
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    print("\n=== decision log (every tool-layer decision) ===")
    print(audit.pretty())
    return "[hop limit reached without a final answer]"


if __name__ == "__main__":
    answer = run_specialist_agent(
        referral_id="ref_001",
        task=(
            "A PCP has referred a patient to cardiology for an arrhythmia workup "
            "ahead of elective surgery. Review the case and flag any concerns."
        ),
    )
    print("\n=== specialist agent ===\n")
    print(answer)
