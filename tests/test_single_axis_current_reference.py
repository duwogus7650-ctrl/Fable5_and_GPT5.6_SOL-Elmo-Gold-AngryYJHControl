"""Pure contracts for the bounded Single Axis current-reference reader."""

from __future__ import annotations

from dataclasses import replace
import math

import pytest

import single_axis_current_reference as current_reference


def _raw(**updates):
    sr = (1 << 14) | (1 << 15)
    values = {
        "MO_PRE": 0,
        "SO_PRE": 0,
        "MF_PRE": 0,
        "SR_PRE": sr,
        "UM": 5,
        "TC": 0.0,
        "IQ": 0.0,
        "ID": 0.0,
        "CL[1]": 2.0,
        "PL[1]": 4.0,
        "LC": 0,
        "MC": 5.0,
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
            5, 0.0, 0.0, 0.0, 2.0, 4.0, 0, 5.0,
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


def test_document_sources_and_write_boundary_are_frozen():
    assert tuple(source.key for source in current_reference.SOURCES) == (
        "tc", "cl", "pl", "lc", "mc", "id_iq", "um", "mo_so", "sr",
    )
    assert current_reference.SOURCES[0].sha256 == (
        "E9152A936F2717C747A0382B215D5463966A56B36F7D203D126251C068856CA9"
    )
    assert current_reference.SOURCES[-1].sha256 == (
        "7DA74A9E02133827EF962D73673FC34FF7F5B25259AFD38C459A07F8681BE1AF"
    )
    contract = current_reference.COMMAND_CONTRACT
    assert contract.implemented is False
    assert contract.operation_status == "NEED_DATA"
    assert contract.requires_motor_on is True
    assert contract.requires_servo_ready is True
    assert contract.forces_current_loop is True
    assert contract.requires_watchdog is True
    assert contract.requires_stop_disable_closeout is True
    assert "TC" in contract.boundary
    assert "MO=1" in contract.boundary


def test_disabled_snapshot_is_current_read_only_and_does_not_claim_measured_current():
    snapshot = current_reference.decode_current_reference_snapshot(
        _raw(), sample_duration_s=0.08)

    assert snapshot.state == current_reference.CURRENT
    assert snapshot.authority == current_reference.CURRENT_DRIVE_READ_ONLY
    assert snapshot.motor_state == "DISABLED REPORTED"
    assert snapshot.mode_value == 5
    assert snapshot.mode_name == "Position"
    assert snapshot.tc_a == 0.0
    assert snapshot.iq_a == 0.0
    assert snapshot.id_a == 0.0
    assert snapshot.continuous_limit_a == 2.0
    assert snapshot.peak_limit_a == 4.0
    assert snapshot.maximum_drive_current_a == 5.0
    assert snapshot.current_limit_active is False
    assert snapshot.command_authority == current_reference.COMMAND_LOCKED_NEED_DATA
    assert "READ" in snapshot.evidence_label
    assert "NO TC ASSIGNMENT" in snapshot.evidence_label


def test_enabled_snapshot_reports_drive_values_without_granting_command_authority():
    sr = (
        (1 << 4) | (1 << 14) | (1 << 15) | (1 << 22)
    )
    snapshot = current_reference.decode_current_reference_snapshot(
        _raw(
            MO_PRE=1, SO_PRE=1, SR_PRE=sr,
            TC=0.25, IQ=0.24, ID=0.01,
            MO_POST=1, SO_POST=1, SR_POST=sr,
        ),
        sample_duration_s=0.08,
    )

    assert snapshot.state == current_reference.CURRENT
    assert snapshot.motor_state == "ENABLED REPORTED · ENERGIZED"
    assert snapshot.tc_a == pytest.approx(0.25)
    assert snapshot.iq_a == pytest.approx(0.24)
    assert snapshot.command_authority == current_reference.COMMAND_LOCKED_NEED_DATA


@pytest.mark.parametrize(
    ("updates", "reason"),
    (
        ({"MO_POST": 1}, "changed"),
        ({"SO_POST": 1}, "changed"),
        ({"MF_POST": 1}, "changed"),
        ({"SR_PRE": (1 << 22)}, "SR_PRE"),
        ({"SR_POST": (1 << 22)}, "SR_POST"),
        ({"LC": 1}, "current-limit"),
        ({"PL[1]": 6.0}, "MC"),
        ({"TC": 4.1}, "PL[1]"),
        ({"IQ": 6.0}, "MC"),
        ({"ID": -6.0}, "MC"),
    ),
)
def test_inconsistent_or_out_of_range_evidence_fails_closed(updates, reason):
    snapshot = current_reference.decode_current_reference_snapshot(
        _raw(**updates), sample_duration_s=0.08)

    assert snapshot.state == current_reference.UNKNOWN
    assert snapshot.authority == current_reference.AUTHORITY_UNKNOWN
    assert snapshot.raw == {}
    assert reason.lower() in snapshot.reason.lower()


@pytest.mark.parametrize("value", (None, True, "", "abc", math.nan, math.inf))
def test_nonfinite_or_nonnumeric_current_evidence_fails_closed(value):
    snapshot = current_reference.decode_current_reference_snapshot(
        _raw(TC=value), sample_duration_s=0.08)

    assert snapshot.state == current_reference.UNKNOWN
    assert "TC" in snapshot.reason


@pytest.mark.parametrize("duration", (-0.01, math.nan, math.inf, 1.501))
def test_stale_or_invalid_acquisition_duration_fails_closed(duration):
    snapshot = current_reference.decode_current_reference_snapshot(
        _raw(), sample_duration_s=duration)

    assert snapshot.state == current_reference.UNKNOWN
    assert "duration" in snapshot.reason.lower()


def test_reader_issues_only_the_exact_bounded_query_sequence():
    drive = _Drive()

    snapshot = current_reference.read_current_reference_snapshot(
        drive, clock_fn=drive.clock)

    assert snapshot.state == current_reference.CURRENT
    assert tuple(command for command, _kwargs in drive.commands) == tuple(
        command for _key, command in current_reference.READ_STEPS)
    assert all(
        kwargs == {"timeout_ms": current_reference.READ_TIMEOUT_MS}
        for _command, kwargs in drive.commands)
    assert all("=" not in command for command, _kwargs in drive.commands)
    assert len(drive.commands) == 16


def test_reader_fails_closed_on_query_error_or_session_rotation():
    failed = _Drive(error_at=6)
    failed_snapshot = current_reference.read_current_reference_snapshot(
        failed, clock_fn=failed.clock)
    assert failed_snapshot.state == current_reference.UNKNOWN
    assert "TC" in failed_snapshot.reason

    changed = _Drive()
    original = changed.command

    def rotating_command(command, **kwargs):
        result = original(command, **kwargs)
        if len(changed.commands) == 8:
            changed.session = object()
        return result

    changed.command = rotating_command
    changed_snapshot = current_reference.read_current_reference_snapshot(
        changed, clock_fn=changed.clock)
    assert changed_snapshot.state == current_reference.UNKNOWN
    assert "session" in changed_snapshot.reason.lower()


def test_snapshot_is_frozen_and_canonical_redecode_rejects_forged_claims():
    snapshot = current_reference.decode_current_reference_snapshot(
        _raw(), sample_duration_s=0.08)

    with pytest.raises(Exception):
        snapshot.raw["TC"] = 1.0
    forged = replace(snapshot, evidence_label="FORGED")
    canonical = current_reference.decode_current_reference_snapshot(
        forged.raw, sample_duration_s=forged.sample_duration_s)
    assert forged != canonical
