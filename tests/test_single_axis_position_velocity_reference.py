"""Pure contracts for the bounded Single Axis position/velocity reader."""

from __future__ import annotations

from dataclasses import replace
import math

import pytest

import single_axis_position_velocity_reference as position_velocity


_INT32_MAX = (1 << 31) - 1
_INT32_MIN = -(1 << 31)


def _raw(**updates):
    sr = (1 << 14) | (1 << 15)
    values = {
        "MO_PRE": 0,
        "SO_PRE": 0,
        "MF_PRE": 0,
        "SR_PRE": sr,
        "UM": 5,
        "PA[1]": 12000,
        "PR[1]": -500,
        "JV": 2500,
        "SP[1]": 10000,
        "AC[1]": 20000,
        "DC": 18000,
        "SD": 15000,
        "PX": 11500,
        "PU": 33565932,
        "XM[1]": 0,
        "XM[2]": 0,
        "FC[1]": 1,
        "FC[2]": 1,
        "FC[5]": 1,
        "FC[6]": 1,
        "FC[7]": 1,
        "FC[8]": 1,
        "CA[45]": 1,
        "VX": 0.0,
        "MO_POST": 0,
        "SO_POST": 0,
        "MF_POST": 0,
        "SR_POST": sr,
    }
    values.update(updates)
    return values


class _Drive:
    def __init__(self, results=None, error_at=None):
        self.session = object()
        self.results = list(results or (
            0, 0, 0, (1 << 14) | (1 << 15),
            5, 12000, -500, 2500, 10000, 20000, 18000, 15000,
            11500, 33565932,
            0, 0,
            1, 1, 1, 1, 1, 1,
            1, 0.0,
            0, 0, 0, (1 << 14) | (1 << 15),
        ))
        self.error_at = error_at
        self.commands = []
        self.now = 10.0

    def transaction_session_identity(self):
        return self.session

    def command(self, command, **kwargs):
        self.commands.append((command, kwargs))
        if self.error_at == len(self.commands):
            raise IOError("read failed")
        return self.results[len(self.commands) - 1]

    def clock(self):
        self.now += 0.01
        return self.now


def test_document_sources_and_command_boundary_are_frozen():
    assert tuple(source.key for source in position_velocity.SOURCES) == (
        "pa", "pr", "jv", "sp", "ac", "dc", "sd", "px", "pu",
        "xm", "fc", "ca", "vx",
        "um", "mo_so", "mf", "sr",
    )
    assert position_velocity.SOURCES[0].sha256 == (
        "40F8B55DDCED8C0BE6A3ACB88BD0E15A8E35C4CD12C22C5BF0047E4BBE4978F9"
    )
    assert position_velocity.SOURCES[12].sha256 == (
        "A6D910DFCB93AD746B57EE8D12A6EC807BCB573FE05ACF4F1A2D3FDE0D74CD7A"
    )
    assert position_velocity.SOURCES[-1].sha256 == (
        "7DA74A9E02133827EF962D73673FC34FF7F5B25259AFD38C459A07F8681BE1AF"
    )

    contract = position_velocity.COMMAND_CONTRACT
    assert contract.implemented is False
    assert contract.operation_status == "NEED_DATA"
    assert contract.requires_motor_on is True
    assert contract.requires_servo_ready is True
    assert contract.requires_begin_motion is True
    assert contract.requires_position_and_velocity_limits is True
    assert contract.requires_watchdog is True
    assert contract.requires_stop_disable_closeout is True
    assert "BG" in contract.boundary
    assert "not implemented" in contract.boundary.lower()


def test_read_steps_are_exact_queries_with_no_motion_or_assignment():
    assert position_velocity.READ_STEPS == (
        ("MO_PRE", "MO"),
        ("SO_PRE", "SO"),
        ("MF_PRE", "MF"),
        ("SR_PRE", "SR"),
        ("UM", "UM"),
        ("PA[1]", "PA[1]"),
        ("PR[1]", "PR[1]"),
        ("JV", "JV"),
        ("SP[1]", "SP[1]"),
        ("AC[1]", "AC[1]"),
        ("DC", "DC"),
        ("SD", "SD"),
        ("PX", "PX"),
        ("PU", "PU"),
        ("XM[1]", "XM[1]"),
        ("XM[2]", "XM[2]"),
        ("FC[1]", "FC[1]"),
        ("FC[2]", "FC[2]"),
        ("FC[5]", "FC[5]"),
        ("FC[6]", "FC[6]"),
        ("FC[7]", "FC[7]"),
        ("FC[8]", "FC[8]"),
        ("CA[45]", "CA[45]"),
        ("VX", "VX"),
        ("MO_POST", "MO"),
        ("SO_POST", "SO"),
        ("MF_POST", "MF"),
        ("SR_POST", "SR"),
    )
    commands = tuple(command for _key, command in position_velocity.READ_STEPS)
    assert all("=" not in command for command in commands)
    assert "BG" not in commands
    assert "MO=1" not in commands


def test_disabled_snapshot_is_current_read_only_and_distinguishes_references():
    snapshot = position_velocity.decode_position_velocity_snapshot(
        _raw(), sample_duration_s=0.08)

    assert snapshot.state == position_velocity.CURRENT
    assert snapshot.authority == position_velocity.CURRENT_DRIVE_READ_ONLY
    assert snapshot.motor_state == "DISABLED REPORTED"
    assert snapshot.mode_value == 5
    assert snapshot.mode_name == "Position"
    assert snapshot.absolute_target_count == 12000
    assert snapshot.relative_target_count == -500
    assert snapshot.jog_velocity_count_per_s == 2500
    assert snapshot.profile_speed_count_per_s == 10000
    assert snapshot.acceleration_count_per_s2 == 20000
    assert snapshot.deceleration_count_per_s2 == 18000
    assert snapshot.stop_deceleration_count_per_s2 == 15000
    assert snapshot.feedback_position_count == 11500
    assert snapshot.eas_position_user_unit == 33565932
    assert snapshot.eas_to_raw_position_delta == 1 << 25
    assert snapshot.position_coordinate_status == "DIVERGED / NEED-DATA"
    assert snapshot.main_position_socket == 1
    assert snapshot.position_modulo_min == 0
    assert snapshot.position_modulo_max == 0
    assert snapshot.position_scale_numerator == 1
    assert snapshot.position_scale_denominator == 1
    assert snapshot.feedback_velocity_count_per_s == 0.0
    assert snapshot.effective_acceleration_count_per_s2 == 15000
    assert snapshot.effective_deceleration_count_per_s2 == 15000
    assert snapshot.command_authority == (
        position_velocity.COMMAND_LOCKED_NEED_DATA)
    assert "CONFIGURED" in snapshot.reference_semantics
    assert "NOT ACTIVE COMMAND" in snapshot.reference_semantics
    assert "QUERY ONLY" in snapshot.evidence_label
    assert "NO BG" in snapshot.evidence_label
    assert "EAS SINGLE AXIS USES PU" in snapshot.reference_semantics


def test_aligned_px_and_pu_are_reported_without_inventing_an_offset():
    snapshot = position_velocity.decode_position_velocity_snapshot(
        _raw(PU=11500), sample_duration_s=0.08)

    assert snapshot.state == position_velocity.CURRENT
    assert snapshot.eas_to_raw_position_delta == 0
    assert snapshot.position_coordinate_status == "ALIGNED"


def test_enabled_snapshot_reports_readback_without_granting_command_authority():
    sr = (1 << 4) | (1 << 14) | (1 << 15) | (1 << 22)
    snapshot = position_velocity.decode_position_velocity_snapshot(
        _raw(
            MO_PRE=1,
            SO_PRE=1,
            SR_PRE=sr,
            VX=12.5,
            MO_POST=1,
            SO_POST=1,
            SR_POST=sr,
        ),
        sample_duration_s=0.08,
    )

    assert snapshot.state == position_velocity.CURRENT
    assert snapshot.motor_state == "ENABLED REPORTED / ENERGIZED"
    assert snapshot.feedback_velocity_count_per_s == pytest.approx(12.5)
    assert snapshot.command_authority == (
        position_velocity.COMMAND_LOCKED_NEED_DATA)


@pytest.mark.parametrize(
    ("updates", "reason"),
    (
        ({"MO_POST": 1}, "changed"),
        ({"SO_POST": 1}, "changed"),
        ({"MF_POST": 1}, "changed"),
        ({"SR_PRE": (1 << 22)}, "SR_PRE"),
        ({"SR_POST": (1 << 22)}, "SR_POST"),
        ({"UM": 4}, "reserved"),
        ({"PA[1]": _INT32_MAX + 1}, "PA[1]"),
        ({"PR[1]": _INT32_MIN - 1}, "PR[1]"),
        ({"JV": _INT32_MAX + 1}, "JV"),
        ({"SP[1]": -1}, "SP[1]"),
        ({"AC[1]": 0}, "AC[1]"),
        ({"DC": 0}, "DC"),
        ({"SD": 0}, "SD"),
        ({"PX": _INT32_MAX + 1}, "PX"),
        ({"PU": _INT32_MAX + 1}, "PU"),
        ({"XM[1]": _INT32_MIN - 1}, "XM[1]"),
        ({"XM[2]": _INT32_MAX + 1}, "XM[2]"),
        ({"FC[1]": 0}, "FC[1]"),
        ({"FC[8]": _INT32_MAX + 1}, "FC[8]"),
        ({"CA[45]": 0}, "CA[45]"),
        ({"CA[45]": 5}, "CA[45]"),
        ({"VX": 2_000_000_001.0}, "VX"),
    ),
)
def test_inconsistent_or_out_of_range_evidence_fails_closed(updates, reason):
    snapshot = position_velocity.decode_position_velocity_snapshot(
        _raw(**updates), sample_duration_s=0.08)

    assert snapshot.state == position_velocity.UNKNOWN
    assert snapshot.authority == position_velocity.AUTHORITY_UNKNOWN
    assert snapshot.raw == {}
    assert reason.lower() in snapshot.reason.lower()


@pytest.mark.parametrize(
    "key",
    (
        "PA[1]", "PR[1]", "JV", "PX", "PU", "XM[1]", "XM[2]",
        "FC[1]", "FC[2]", "FC[5]", "FC[6]", "FC[7]", "FC[8]", "CA[45]",
    ),
)
@pytest.mark.parametrize("value", (None, True, "", "abc", 1.5, math.nan))
def test_integer_evidence_rejects_noninteger_or_nonnumeric_values(key, value):
    snapshot = position_velocity.decode_position_velocity_snapshot(
        _raw(**{key: value}), sample_duration_s=0.08)

    assert snapshot.state == position_velocity.UNKNOWN
    assert key in snapshot.reason


@pytest.mark.parametrize("value", (None, True, "", "abc", math.nan, math.inf))
def test_velocity_evidence_rejects_nonfinite_or_nonnumeric_values(value):
    snapshot = position_velocity.decode_position_velocity_snapshot(
        _raw(VX=value), sample_duration_s=0.08)

    assert snapshot.state == position_velocity.UNKNOWN
    assert "VX" in snapshot.reason


@pytest.mark.parametrize("duration", (-0.01, math.nan, math.inf, 1.501))
def test_stale_or_invalid_acquisition_duration_fails_closed(duration):
    snapshot = position_velocity.decode_position_velocity_snapshot(
        _raw(), sample_duration_s=duration)

    assert snapshot.state == position_velocity.UNKNOWN
    assert "duration" in snapshot.reason.lower()


def test_reader_issues_only_the_exact_bounded_query_sequence():
    drive = _Drive()

    snapshot = position_velocity.read_position_velocity_snapshot(
        drive, clock_fn=drive.clock)

    assert snapshot.state == position_velocity.CURRENT
    assert tuple(command for command, _kwargs in drive.commands) == tuple(
        command for _key, command in position_velocity.READ_STEPS)
    assert all(
        kwargs == {"timeout_ms": position_velocity.READ_TIMEOUT_MS}
        for _command, kwargs in drive.commands)
    assert all("=" not in command for command, _kwargs in drive.commands)
    assert len(drive.commands) == 28


def test_reader_fails_closed_on_query_error_or_session_rotation():
    failed = _Drive(error_at=6)
    failed_snapshot = position_velocity.read_position_velocity_snapshot(
        failed, clock_fn=failed.clock)
    assert failed_snapshot.state == position_velocity.UNKNOWN
    assert "PA[1]" in failed_snapshot.reason

    changed = _Drive()
    original = changed.command

    def rotating_command(command, **kwargs):
        result = original(command, **kwargs)
        if len(changed.commands) == 9:
            changed.session = object()
        return result

    changed.command = rotating_command
    changed_snapshot = position_velocity.read_position_velocity_snapshot(
        changed, clock_fn=changed.clock)
    assert changed_snapshot.state == position_velocity.UNKNOWN
    assert "session" in changed_snapshot.reason.lower()


def test_snapshot_is_frozen_and_canonical_redecode_rejects_forged_claims():
    snapshot = position_velocity.decode_position_velocity_snapshot(
        _raw(), sample_duration_s=0.08)

    with pytest.raises(Exception):
        snapshot.raw["PA[1]"] = 1
    forged = replace(snapshot, evidence_label="FORGED")
    canonical = position_velocity.decode_position_velocity_snapshot(
        forged.raw, sample_duration_s=forged.sample_duration_s)
    assert forged != canonical
