"""Contracts for the bounded Single Axis UM read-only snapshot."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import math
from pathlib import Path

import pytest

import single_axis_drive_mode as drive_mode


class _Drive:
    def __init__(self, value="5", clocks=None):
        self.value = value
        self.commands = []
        self.session = object()
        self.clocks = iter(clocks or (10.0, 10.05))

    def transaction_session_identity(self):
        return self.session

    def command(self, command, **kwargs):
        self.commands.append((command, dict(kwargs)))
        if isinstance(self.value, Exception):
            raise self.value
        return self.value

    def clock(self):
        return next(self.clocks)


def test_documented_um_modes_and_change_boundary_are_exact_and_immutable():
    assert tuple(drive_mode.MODE_SPECS) == (1, 2, 3, 5, 6)
    assert drive_mode.MODE_SPECS[1].name == "Torque"
    assert drive_mode.MODE_SPECS[2].name == "Speed"
    assert drive_mode.MODE_SPECS[3].name == "Stepper"
    assert drive_mode.MODE_SPECS[5].name == "Position"
    assert drive_mode.MODE_SPECS[6].name == "Stepper open/closed loop"
    assert drive_mode.RESERVED_MODES == {4: "Reserved"}

    contract = drive_mode.CHANGE_CONTRACT
    assert contract.implemented is False
    assert contract.nonvolatile is True
    assert contract.motor_must_be_off is True
    assert contract.requires_exact_readback is True
    assert contract.requires_rollback_authority is True
    assert contract.operation_status == "NEED_DATA"
    with pytest.raises(FrozenInstanceError):
        contract.implemented = True


@pytest.mark.parametrize(
    ("value", "name", "reference"),
    (
        (1, "Torque", "TC"),
        (2, "Speed", "JV"),
        (3, "Stepper", "PA / PR / JV / TC"),
        (5, "Position", "PA / PR"),
        (6, "Stepper open/closed loop", "HT[] / FF[]"),
    ),
)
def test_supported_um_value_decodes_to_current_read_only_mode(
        value, name, reference):
    snapshot = drive_mode.decode_drive_mode_snapshot(
        {"UM": value}, sample_duration_s=0.05)

    assert snapshot.state == drive_mode.CURRENT
    assert snapshot.authority == drive_mode.CURRENT_DRIVE_READ_ONLY
    assert snapshot.raw == {"UM": value}
    assert snapshot.mode is drive_mode.MODE_SPECS[value]
    assert snapshot.mode.name == name
    assert reference in snapshot.mode.reference_contract
    assert "CURRENT DRIVE READ" in snapshot.evidence_label
    assert "NO MODE CHANGE" in snapshot.evidence_label


@pytest.mark.parametrize(
    "value",
    (None, True, False, "", "abc", 0, 4, 7, 1.5, math.nan, math.inf),
)
def test_invalid_reserved_or_nonintegral_um_fails_entire_snapshot_closed(value):
    snapshot = drive_mode.decode_drive_mode_snapshot(
        {"UM": value}, sample_duration_s=0.05)

    assert snapshot.state == drive_mode.UNKNOWN
    assert snapshot.authority == drive_mode.AUTHORITY_UNKNOWN
    assert snapshot.mode is None
    assert snapshot.raw == {}
    assert snapshot.reason


@pytest.mark.parametrize("duration", (-0.1, math.nan, math.inf, 0.501))
def test_invalid_or_stale_um_acquisition_duration_fails_closed(duration):
    snapshot = drive_mode.decode_drive_mode_snapshot(
        {"UM": 5}, sample_duration_s=duration)

    assert snapshot.state == drive_mode.UNKNOWN
    assert snapshot.raw == {}
    assert "duration" in snapshot.reason.lower()


def test_reader_issues_exactly_one_bounded_um_query_and_never_assigns():
    drive = _Drive()

    snapshot = drive_mode.read_drive_mode_snapshot(
        drive, clock_fn=drive.clock)

    assert snapshot.state == drive_mode.CURRENT
    assert drive.commands == [
        ("UM", {"timeout_ms": drive_mode.READ_TIMEOUT_MS}),
    ]
    assert all("=" not in command for command, _kwargs in drive.commands)


def test_reader_fails_closed_on_read_error_or_session_change():
    failed = _Drive(IOError("read failed"))
    failed_snapshot = drive_mode.read_drive_mode_snapshot(
        failed, clock_fn=failed.clock)
    assert failed_snapshot.state == drive_mode.UNKNOWN
    assert "UM" in failed_snapshot.reason

    changed = _Drive()
    original_command = changed.command

    def rotating_command(command, **kwargs):
        result = original_command(command, **kwargs)
        changed.session = object()
        return result

    changed.command = rotating_command
    changed_snapshot = drive_mode.read_drive_mode_snapshot(
        changed, clock_fn=changed.clock)
    assert changed_snapshot.state == drive_mode.UNKNOWN
    assert "session" in changed_snapshot.reason.lower()


def test_source_identity_is_frozen_to_installed_gold_um_documentation():
    assert tuple(source.key for source in drive_mode.SOURCES) == ("gold_um",)
    source = drive_mode.SOURCES[0]
    assert source.sha256 == (
        "8E50AC03CD82F119EEAB3A2BC8C311086EF4CB9F03C06F597084EC79BB3277F8"
    )
    with Path(source.location).open("rb") as handle:
        observed = hashlib.file_digest(handle, "sha256").hexdigest().upper()
    assert observed == source.sha256
