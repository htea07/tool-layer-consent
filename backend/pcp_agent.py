"""The PCP agent's tool-calling loop, written by hand.

This is the manual agentic loop (not the SDK's auto tool-runner) on purpose:
you should see the call -> tool_use -> tool_result -> call cycle explicitly,
because that cycle IS the skill you're here to learn. Once you've felt it raw,
you'll understand what a framework abstracts.

The PCP agent's one tool is message_specialist, whose implementation hands off to
the specialist agent through router.py (one-directional, depth 1).

Run directly to drive the PCP agent over the seeded referral:
    python pcp_agent.py
(requires ANTHROPIC_API_KEY in the environment)
"""

from __future__ import annotations

import json

import anthropic

import pcp_tools

import router 

MODEL = "claude-opus-4-8"
MAX_HOPS = 8  # safety cap so a misbehaving loop can't run forever


def run_pcp_agent(referral_id: str, task: str) -> str:
    """Run the PCP's agent over one referral and return its final text.

    `task` is the kickoff instruction. The PCP agent decides when to call
    message_specialist; we execute that handoff through router.py, which runs the
    specialist agent under the scope-enforcing tool layer and returns its reply.
    """
    client = anthropic.Anthropic()

    system = (
        "You are a primary care physician's agent coordinating a referral. "
        "Use the message_specialist tool to send the case to the specialist and get their " 
        "assessment. Then summarize their findings and any flagged concerns for the patient's chart."
    )
    messages: list[dict] = [{"role": "user", "content": task}]

    for _ in range(MAX_HOPS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=system,
            tools=pcp_tools.PCP_TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            # Done, return the final text block.
            return next((b.text for b in response.content if b.type == "text"), "")

        # Append the assistant turn (with its tool_use blocks) before answering.
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "message_specialist":
                intent = block.input["intent"] # reading arg model supplied when called tool
                result = router.request_to_specialist(referral_id, intent)
            else:
                result = json.dumps({"error": f"unknown tool {block.name}"})
            # Print the enforcement decision so the demo trace is legible.
            print(f"[tool] message_specialist -> specialist replied ({len(result)} chars)")
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return "[hop limit reached without a final answer]"


if __name__ == "__main__":
    answer = run_pcp_agent(
        referral_id="ref_001",
        task=(
            "A PCP has referred a patient to cardiology for an arrhythmia workup "
            "ahead of elective surgery. Review the case and flag any concerns."
        ),
    )
    print("\n=== pcp agent ===\n")
    print(answer)
