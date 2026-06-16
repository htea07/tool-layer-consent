"""Cross-principal handoff: PCP agent -> specialist agent -> reply.

The two guardrails that keep it from spinning:
  1. a hop counter (the specialist agent already enforces MAX_HOPS internally,
     and the PCP->specialist handoff counts as one hop here),
  2. the specialist's agent does NOT get a tool to call back out to other
     agents, the handoff is one-directional, depth 1.
"""

from __future__ import annotations

from agent import run_specialist_agent

MAX_AGENT_HOPS = 1  # PCP agent may consult a specialist agent, but no deeper.


def request_to_specialist(referral_id: str, intent: str, _hop: int = 0) -> str:
    """Run the specialist's agent on behalf of the PCP agent and return its reply.

    This is the body of what would be the PCP agent's `message_specialist` tool.
    Note it's a plain function call into another agent loop, that's the whole
    trick. The specialist runs with scope.py-filtered tools (see tools.py), so
    the cross-principal boundary is enforced exactly where the single-principal
    boundary is.
    """
    if _hop >= MAX_AGENT_HOPS:
        return "[agent hop limit reached, refusing further delegation]"

    return run_specialist_agent(referral_id=referral_id, task=intent)


# TODO (week 3): build the PCP-side agent loop that exposes message_specialist
# as a tool whose implementation is request_to_specialist(). Mirror agent.py's
# structure; give the PCP agent create_referral + message_specialist, and do NOT
# give the specialist agent any outbound-messaging tool.
