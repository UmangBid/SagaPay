"""Payment state machine transitions enforced by the orchestrator."""

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"RISK_REVIEW", "APPROVED", "FAILED"},
    "RISK_REVIEW": {"APPROVED", "FAILED"},
    "APPROVED": {"AUTHORIZED", "FAILED"},
    "AUTHORIZED": {"CAPTURED", "FAILED", "REVERSED"},
    "CAPTURED": {"SETTLED", "FAILED", "REVERSED"},
    "SETTLED": set(),
    "FAILED": {"REVERSED"},
    "REVERSED": set(),
}


def validate_transition(current: str, new: str) -> None:
    """Raise when a transition is not allowed by the state machine."""

    if new not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"Invalid transition: {current} -> {new}")
