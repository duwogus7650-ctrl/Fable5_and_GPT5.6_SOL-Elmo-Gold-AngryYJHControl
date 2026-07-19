"""Deterministic contracts for the 2026-07-19 live EAS parity audit."""

from __future__ import annotations

from dataclasses import replace

import pytest

import eas_live_parity as parity


def test_position_audit_preserves_raw_terminal_match_and_display_mismatch():
    raw = parity.entry("single_axis.position.raw_px")
    display = parity.entry("single_axis.position.eas_display")

    assert raw.verdict == parity.VALUE_PARITY_OBSERVED
    assert raw.our_value == parity.EAS_TERMINAL_RAW_PX
    assert raw.eas_value == parity.EAS_TERMINAL_RAW_PX
    assert display.verdict == parity.MISMATCH_NEED_DATA
    assert display.eas_value == parity.EAS_SINGLE_AXIS_POSITION
    assert display.our_value == parity.OUR_RAW_PX
    assert display.eas_value - display.our_value == 1 << 25
    assert display.can_claim_eas_parity is False


def test_current_readback_is_not_misrepresented_as_eas_current_command_ui():
    current = parity.entry("single_axis.current")

    assert current.verdict == parity.UI_SEMANTICS_MISMATCH
    assert "five" in current.eas_behavior.lower()
    assert "readback" in current.our_behavior.lower()
    assert current.field_executed is False
    assert current.can_claim_eas_parity is False


def test_every_implemented_feature_group_has_an_explicit_verdict():
    feature_ids = {item.feature_id for item in parity.ENTRIES}
    expected_local_implementation_groups = frozenset({
        "motor.profile",
        "motor.persistence_transaction",
        "feedback.sensor_panels",
        "feedback.settings_preview",
        "axis.summary",
        "single_axis.session_zero",
        "single_axis.finite_ptp",
        "tuning.phase1",
        "tuning.phase2",
        "tuning.installed_gain_verify",
        "recorder.export",
        "recorder.statistics",
        "status.session_log",
        "shell.tool_organizer",
        "shell.host_status_monitor",
        "safety.drive_stop",
        "persistence.audit",
    })
    assert parity.REQUIRED_FEATURE_IDS <= feature_ids
    assert expected_local_implementation_groups <= feature_ids
    assert len(feature_ids) == len(parity.ENTRIES)
    assert len(parity.ENTRIES) >= 30
    assert {item.verdict for item in parity.ENTRIES} <= parity.VERDICTS
    assert all(item.can_claim_eas_parity is False for item in parity.ENTRIES)


def test_audit_contains_no_motion_write_or_save_execution_claim():
    assert all(item.motion_executed is False for item in parity.ENTRIES)
    assert all(item.write_executed is False for item in parity.ENTRIES)
    assert all(item.save_executed is False for item in parity.ENTRIES)
    assert parity.AUDIT_EXECUTION_BOUNDARY == (
        "READ_ONLY_UI_AND_QUERY_OBSERVATION"
    )


def test_validator_catches_mutated_position_verdict():
    entries = tuple(
        replace(item, verdict=parity.VALUE_PARITY_OBSERVED)
        if item.feature_id == "single_axis.position.eas_display"
        else item
        for item in parity.ENTRIES
    )

    with pytest.raises(ValueError, match="position display"):
        parity.validate_entries(entries)
