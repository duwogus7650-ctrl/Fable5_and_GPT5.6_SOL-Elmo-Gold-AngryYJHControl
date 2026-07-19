"""Pure contracts for the read-only Single Axis safety snapshot."""

from __future__ import annotations

import math

import pytest

import single_axis_status as status


def _raw(**updates):
    values = {
        "MO": 0,
        "SO": 0,
        "MF": 0,
        "PS": -2,
        "SR": (1 << 14) | (1 << 15),
        "MS": 3,
    }
    values.update(updates)
    return values


def test_valid_disabled_snapshot_decodes_only_drive_reported_model_bits():
    snapshot = status.decode_axis_safety_snapshot(_raw())

    assert snapshot.state == status.CURRENT
    assert snapshot.authority == status.MODEL_CURRENT
    assert snapshot.raw == _raw()
    assert snapshot.amplifier_code == 0
    assert snapshot.servo_enabled_reported is False
    assert snapshot.user_program_reported is False
    assert snapshot.current_limit_reported is False
    assert snapshot.sto1_permission_reported is True
    assert snapshot.sto2_permission_reported is True
    assert snapshot.profiler_code == 0
    assert snapshot.conflicts == ()
    assert "DRIVE-REPORTED" in snapshot.evidence_label
    assert "MODEL" in snapshot.evidence_label
    assert "NOT STO TEST EVIDENCE" in snapshot.evidence_label
    assert "safe" not in snapshot.evidence_label.lower()
    assert "all ok" not in snapshot.amplifier_label.lower()


def test_live_twitter_sr23_snapshot_is_defined_and_source_bound():
    snapshot = status.decode_axis_safety_snapshot(
        _raw(SR=0x0080C000))

    assert snapshot.state == status.CURRENT
    assert snapshot.raw["SR"] == 0x0080C000
    assert snapshot.motor_on_reported is False
    assert snapshot.movement_bit_reported is True
    assert snapshot.sto_diagnostics_error_reported is False
    assert any(
        "SR23 movement/standstill indication=1" in item
        for item in snapshot.conditions
    )
    assert "reserved" not in snapshot.reason.lower()


def test_current_installed_defined_bits_are_not_rejected_as_reserved():
    sr = (
        (1 << 14)
        | (1 << 15)
        | (1 << 21)
        | (1 << 23)
        | (1 << 27)
        | (1 << 30)
    )
    snapshot = status.decode_axis_safety_snapshot(_raw(SR=sr))

    assert snapshot.state == status.CURRENT
    assert snapshot.shunt_bit_reported is True
    assert snapshot.movement_bit_reported is True
    assert snapshot.sto_diagnostics_error_reported is True
    assert snapshot.ptp_buffer_full_reported is True
    assert any(
        "SR27 STO diagnostics error report=1" in item
        for item in snapshot.conditions
    )


def test_one_sto_channel_low_is_visible_without_becoming_a_safety_verdict():
    snapshot = status.decode_axis_safety_snapshot(
        _raw(SR=(1 << 14)))

    assert snapshot.state == status.CURRENT
    assert snapshot.authority == status.MODEL_CURRENT
    assert snapshot.sto1_permission_reported is True
    assert snapshot.sto2_permission_reported is False
    assert "STO2 drive-reported permission=0" in snapshot.conditions
    assert all("safe" not in item.lower() for item in snapshot.conditions)


def test_fault_program_limit_and_profiler_bits_remain_separate_observations():
    sr = (
        0x5
        | (1 << 4)
        | (3 << 8)
        | (1 << 12)
        | (1 << 13)
        | (1 << 22)
    )
    snapshot = status.decode_axis_safety_snapshot(
        _raw(MO=1, SO=1, MF=9, PS=1, SR=sr, MS=2))

    assert snapshot.state == status.CURRENT
    assert snapshot.amplifier_code == 0x5
    assert "overvoltage" in snapshot.amplifier_label.lower()
    assert snapshot.servo_enabled_reported is True
    assert snapshot.user_program_reported is True
    assert snapshot.current_limit_reported is True
    assert snapshot.profiler_code == 3
    assert snapshot.raw["MF"] == 9
    assert snapshot.raw["MS"] == 2


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("SR", None),
        ("SR", True),
        ("SR", 1.5),
        ("SR", math.nan),
        ("SR", math.inf),
        ("SR", 10 ** 400),
        ("SR", (1 << 14) | (1 << 15) | (1 << 5)),
        ("SR", (1 << 14) | (1 << 15) | (1 << 29)),
        ("SR", (1 << 14) | (1 << 15) | 0x1),
        ("SR", (1 << 14) | (1 << 15) | (11 << 8)),
        ("SR", (1 << 14) | (1 << 15) | (15 << 8)),
        ("SR", -1),
        ("SR", 1 << 32),
        ("MO", 2),
        ("SO", False),
        ("MF", -1),
        ("PS", 2),
        ("MS", 4),
    ),
)
def test_invalid_or_out_of_contract_value_fails_the_entire_projection_closed(
        key, value):
    snapshot = status.decode_axis_safety_snapshot(_raw(**{key: value}))

    assert snapshot.state == status.UNKNOWN
    assert snapshot.authority == status.MODEL_UNKNOWN
    assert snapshot.raw == {}
    assert snapshot.amplifier_code is None
    assert snapshot.servo_enabled_reported is None
    assert snapshot.sto1_permission_reported is None
    assert snapshot.sto2_permission_reported is None
    assert snapshot.conflicts == ()
    assert key in snapshot.reason


def test_missing_required_field_fails_closed_without_partial_semantics():
    raw = _raw()
    del raw["PS"]

    snapshot = status.decode_axis_safety_snapshot(raw)

    assert snapshot.state == status.UNKNOWN
    assert snapshot.authority == status.MODEL_UNKNOWN
    assert snapshot.raw == {}
    assert snapshot.user_program_reported is None
    assert "PS" in snapshot.reason


@pytest.mark.parametrize(
    "raw",
    (
        _raw(SO=1),
        _raw(PS=1),
    ),
)
def test_redundant_so_or_program_disagreement_revokes_model_authority(raw):
    snapshot = status.decode_axis_safety_snapshot(raw)

    assert snapshot.state == status.INCONSISTENT
    assert snapshot.authority == status.MODEL_UNKNOWN
    assert snapshot.conflicts
    assert snapshot.raw == raw


def test_redundant_mo_sr22_disagreement_revokes_model_authority():
    snapshot = status.decode_axis_safety_snapshot(_raw(MO=1))

    assert snapshot.state == status.INCONSISTENT
    assert snapshot.authority == status.MODEL_UNKNOWN
    assert "MO=1 disagrees with SR22=0" in snapshot.reason


def test_input_mapping_is_not_modified():
    raw = _raw()
    before = dict(raw)

    status.decode_axis_safety_snapshot(raw)

    assert raw == before
