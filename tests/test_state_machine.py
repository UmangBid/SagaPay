"""Unit tests for core payment state-machine guardrails."""

import pytest

from finpay.common.state_machine import validate_transition


def test_valid_transition():
    """Sanity check: a legal transition should pass."""

    validate_transition("CREATED", "APPROVED")


def test_invalid_transition():
    """Illegal transition must raise to protect orchestration correctness."""

    with pytest.raises(ValueError):
        validate_transition("CREATED", "SETTLED")
