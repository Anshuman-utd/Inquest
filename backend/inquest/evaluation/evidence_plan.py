from inquest.investigation.graph import State, Steps

# One pass through the signals used by the decision rubric; no LLM planner calls.
EVIDENCE_PLAN = (
    "velocity_check",
    "device_check",
    "merchant_risk_lookup",
    "geo_mismatch_check",
    "search_policy_docs",
)

FIELDS: dict[str, tuple[str, ...]] = {
    "get_transaction": ("transaction",),
    "velocity_check": ("last_5m", "last_1h"),
    "device_check": ("customer_attempts_on_device_30d", "distinct_customers_1h"),
    "merchant_risk_lookup": ("customer_attempts_at_merchant_30d", "distinct_customers_5m"),
    "geo_mismatch_check": ("implied_speed_kmh",),
    "search_policy_docs": ("matches",),
}


def next_evidence(state: State, *, policy: bool) -> State:
    observations = state.get("observations", [])
    remaining = EVIDENCE_PLAN if policy else EVIDENCE_PLAN[:-1]
    index = len(observations) - 1  # Triage gathered the focal transaction.
    if index >= len(remaining):
        return {"request": None}
    tool = remaining[index]
    if tool != "search_policy_docs":
        return {"request": {"tool": tool}}
    payment = observations[0].get("observation", {}).get("transaction", {})
    velocity = observations[1].get("observation", {}).get("last_5m", {})
    device = observations[2].get("observation", {})
    merchant = observations[3].get("observation", {})
    geo = observations[4].get("observation", {})
    if payment.get("recent_reregistration"):
        query = "SIM swap UPI re-registration takeover"
    elif payment.get("flow") == "collect":
        query = "UPI collect request payer debit"
    elif (geo.get("implied_speed_kmh") or 0) >= 900:
        query = "impossible travel physical distance elapsed"
    elif merchant.get("distinct_customers_5m", 0) >= 3 and payment.get("channel") == "upi":
        query = "mule cash out recipient concentration several customers UPI"
    elif device.get("distinct_customers_1h", 0) >= 2:
        query = "card testing shared device small authorizations"
    elif velocity.get("attempts", 0) >= 3:
        query = "velocity burst retry customer attempts"
    else:
        query = "release affirmative historical evidence familiar device merchant"
    return {"request": {"tool": tool, "query": query}}


def compact_evidence(state: State) -> State:
    results = []
    for result in state.get("observations", []):
        observation = result.get("observation", {})
        tool = observation.get("tool")
        if tool not in FIELDS:
            continue
        selected = {key: observation[key] for key in FIELDS[tool] if key in observation}
        if tool == "get_transaction":
            payment = selected["transaction"]
            selected["transaction"] = {
                key: payment[key]
                for key in ("source_sequence", "channel", "flow", "amount_minor", "declined")
            }
        elif tool == "search_policy_docs" and selected.get("matches"):
            policy = selected["matches"][0]
            selected["matches"] = [
                {
                    "section_id": policy["section_id"],
                    "excerpt": policy["excerpt"],
                }
            ]
        results.append({**result, "observation": {"tool": tool, **selected}})
    return {**state, "observations": results}


def synthesize_evidence(steps: Steps, state: State) -> State:
    # The validator retains the full observations and checks any cited value.
    return Steps.synthesize(steps, compact_evidence(state))
