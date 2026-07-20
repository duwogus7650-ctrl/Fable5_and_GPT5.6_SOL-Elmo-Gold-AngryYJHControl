"""Pure contracts for the read-only Single Axis enable-state projection."""

from __future__ import annotations

from dataclasses import replace

import pytest

import single_axis_enable_contract as enable_contract
import single_axis_status


def _snapshot(*, mo=0, so=0, mf=0, amplifier_code=0,
              enabled_fault=False, sto_diagnostics_error=False):
    sr = (
        int(amplifier_code)
        | ((1 << 4) if so else 0)
        | ((1 << 6) if enabled_fault else 0)
        | (1 << 14)
        | (1 << 15)
        | ((1 << 22) if mo else 0)
        | ((1 << 27) if sto_diagnostics_error else 0)
    )
    return single_axis_status.decode_axis_safety_snapshot({
        "MO": mo,
        "SO": so,
        "MF": mf,
        "PS": -2,
        "SR": sr,
        "MS": 3,
    })


@pytest.mark.parametrize(
    ("snapshot", "state", "label"),
    (
        (
            _snapshot(mo=0, so=0),
            enable_contract.DISABLED_REPORTED,
            "DISABLED REPORTED",
        ),
        (
            _snapshot(mo=1, so=0),
            enable_contract.ENABLE_REQUESTED_WAITING,
            "ENABLE REQUESTED",
        ),
        (
            _snapshot(mo=1, so=1),
            enable_contract.ENABLED_REPORTED,
            "ENABLED REPORTED",
        ),
        (
            _snapshot(mo=0, so=1),
            enable_contract.DISABLING_BRAKE_HOLD_REPORTED,
            "DISABLING / BRAKE HOLD",
        ),
    ),
)
def test_documented_mo_so_states_are_distinct_without_granting_authority(
        snapshot, state, label):
    projection = enable_contract.project_enable_state(snapshot)

    assert projection.state == state
    assert label in projection.label
    assert projection.enable_executable is False
    assert projection.enable_operation_id == "motor.enable"
    assert projection.disable_operation_id == "drive.stop"
    assert projection.disable_route == "ST -> MO=0 -> terminal readback"
    assert "LOCKED" in projection.enable_boundary
    assert "NEED-DATA" in projection.enable_boundary
    assert "DRIVE-REPORTED" in projection.evidence_label
    assert "NOT STO TEST EVIDENCE" in projection.evidence_label
    combined = " ".join((
        projection.label,
        projection.detail,
        projection.enable_boundary,
        projection.evidence_label,
    )).lower()
    assert "safe to enable" not in combined
    assert "ready to enable" not in combined


def test_enable_requested_waits_for_so_before_any_reference_is_allowed():
    projection = enable_contract.project_enable_state(
        _snapshot(mo=1, so=0))

    assert projection.state == enable_contract.ENABLE_REQUESTED_WAITING
    assert "SO=0" in projection.label
    assert "reference" in projection.detail.lower()
    assert "wait" in projection.detail.lower()
    assert "MO=1" in projection.conditions
    assert "SO=0" in projection.conditions


def test_mo_zero_so_one_is_documented_brake_hold_not_a_false_disabled_claim():
    projection = enable_contract.project_enable_state(
        _snapshot(mo=0, so=1))

    assert (
        projection.state
        == enable_contract.DISABLING_BRAKE_HOLD_REPORTED
    )
    assert "brake" in projection.detail.lower()
    assert "SO=1" in projection.label
    assert "disabled verified" not in projection.detail.lower()


@pytest.mark.parametrize(
    "snapshot",
    (
        _snapshot(mf=9),
        _snapshot(amplifier_code=0x5),
        _snapshot(mo=1, so=1, enabled_fault=True),
        _snapshot(sto_diagnostics_error=True),
    ),
)
def test_any_fault_observation_overrides_normal_enable_state(snapshot):
    projection = enable_contract.project_enable_state(snapshot)

    assert projection.state == enable_contract.FAULT_REPORTED
    assert projection.label == "FAULT REPORTED - NO AUTO-RETRY"
    assert "STOP" in projection.detail
    assert "inspect" in projection.detail.lower()
    assert projection.enable_executable is False


def test_sto_diagnostics_error_is_named_in_fault_conditions():
    projection = enable_contract.project_enable_state(
        _snapshot(sto_diagnostics_error=True))

    assert projection.state == enable_contract.FAULT_REPORTED
    assert "SR27 STO diagnostics error=1" in projection.conditions


@pytest.mark.parametrize(
    "snapshot",
    (
        None,
        object(),
        single_axis_status.decode_axis_safety_snapshot(None),
        single_axis_status.decode_axis_safety_snapshot({
            "MO": 0,
            "SO": 1,
            "MF": 0,
            "PS": -2,
            "SR": (1 << 14) | (1 << 15),
            "MS": 3,
        }),
    ),
)
def test_missing_unknown_or_inconsistent_snapshot_fails_closed(snapshot):
    projection = enable_contract.project_enable_state(snapshot)

    assert projection.state == enable_contract.UNKNOWN
    assert projection.label == "UNKNOWN - ENABLE LOCKED"
    assert projection.enable_executable is False
    assert projection.conditions == ()


def test_structurally_forged_current_snapshot_fails_closed():
    valid = _snapshot()
    forged = replace(valid, evidence_label="FORGED")

    projection = enable_contract.project_enable_state(forged)

    assert projection.state == enable_contract.UNKNOWN
    assert "evidence" in projection.detail.lower()


def test_projection_does_not_mutate_the_frozen_source_snapshot():
    snapshot = _snapshot(mo=1, so=0)
    before = snapshot

    enable_contract.project_enable_state(snapshot)

    assert snapshot == before
