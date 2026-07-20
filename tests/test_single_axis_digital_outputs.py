"""Contracts for the bounded Single Axis digital-output reader."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import math
from pathlib import Path

import pytest

import single_axis_digital_outputs as digital_outputs


def _raw(**updates):
    values = {
        "OP": (1 << 0) | (1 << 3),
        "OL[1]": 1,   # general purpose, active high
        "OL[2]": 4,   # brake, active low
        "OL[3]": 7,   # servo state, active high
        "OL[4]": 11,  # target reached, active high
        "GO[1]": 0,
        "GO[2]": 1,
        "GO[3]": 2,
        "GO[4]": 7,
    }
    values.update(updates)
    return values


class _Drive:
    def __init__(self, values, clocks=None):
        self.values = dict(values)
        self.commands = []
        self.session = object()
        self.clocks = iter(clocks or (20.0, 20.1))

    def transaction_session_identity(self):
        return self.session

    def command(self, command, **kwargs):
        self.commands.append((command, dict(kwargs)))
        value = self.values[command]
        if isinstance(value, Exception):
            raise value
        return str(value)

    def clock(self):
        return next(self.clocks)


def test_valid_snapshot_decodes_exact_four_output_read_only_rows():
    snapshot = digital_outputs.decode_digital_output_snapshot(
        _raw(), sample_duration_s=0.125)

    assert snapshot.state == digital_outputs.CURRENT
    assert snapshot.authority == digital_outputs.CURRENT_DRIVE_READ_ONLY
    assert snapshot.sample_duration_s == pytest.approx(0.125)
    assert len(snapshot.outputs) == 4
    assert tuple(row.number for row in snapshot.outputs) == (1, 2, 3, 4)
    assert tuple(row.logic_voltage for row in snapshot.outputs) == (
        "5 V logic", "5 V logic", "3.3 V logic", "3.3 V logic")
    assert tuple(row.active for row in snapshot.outputs) == (
        True, False, False, True)
    assert snapshot.outputs[0].state_label == (
        "ACTIVE · DRIVE LOGICAL ACTIVATION")
    assert snapshot.outputs[1].state_label == (
        "INACTIVE · DRIVE LOGICAL ACTIVATION")
    assert snapshot.outputs[0].function_label == "General purpose"
    assert snapshot.outputs[1].function_label == "Brake"
    assert snapshot.outputs[2].function_label == "Servo state (MO)"
    assert snapshot.outputs[3].function_label == "Target reached (MS)"
    assert snapshot.outputs[0].polarity == "ACTIVE_HIGH"
    assert snapshot.outputs[1].polarity == "ACTIVE_LOW"
    assert snapshot.outputs[0].route_label == "Function via OL[N]"
    assert snapshot.outputs[1].route_label == "Port B output compare"
    assert snapshot.outputs[2].route_label == "Port A output compare"
    assert snapshot.outputs[3].route_label == (
        "STO status indication · NOT STO TEST")
    assert snapshot.outputs[0].physical_level == "UNVERIFIED"
    assert "OUTPUTS 1..4 ONLY" in snapshot.evidence_label
    assert "NOT PHYSICAL PIN" in snapshot.evidence_label
    assert "NOT STO TEST EVIDENCE" in snapshot.evidence_label
    with pytest.raises(FrozenInstanceError):
        snapshot.outputs[0].active = False


def test_documented_function_and_route_codes_are_named_without_safety_grant():
    assert digital_outputs.FUNCTION_LABELS == (
        "General purpose",
        "Amplifier OK (AOK)",
        "Brake",
        "Servo state (MO)",
        "Motor fault (MF)",
        "Target reached (MS)",
    )
    assert digital_outputs.ROUTE_LABELS == {
        0: "Function via OL[N]",
        1: "Port B output compare",
        2: "Port A output compare",
        7: "STO status indication · NOT STO TEST",
    }
    assert any(
        "OL_RANGE_CONFLICT" in item
        for item in digital_outputs.DOCUMENT_CONFLICTS)
    combined = " ".join(digital_outputs.ROUTE_LABELS.values()).upper()
    assert "STO STATUS INDICATION" in combined
    assert "STO TEST" in combined
    assert "STO PASSED" not in combined
    assert "SAFE TO MOVE" not in combined


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("OP", None),
        ("OP", True),
        ("OP", -1),
        ("OP", 1 << 32),
        ("OP", 1.5),
        ("OL[1]", True),
        ("OL[1]", -1),
        ("OL[1]", 12),
        ("OL[1]", 1.5),
        ("GO[1]", -1),
        ("GO[1]", 3),
        ("GO[1]", 8),
        ("GO[1]", math.nan),
        ("GO[1]", True),
    ),
)
def test_invalid_value_fails_entire_snapshot_closed(key, value):
    snapshot = digital_outputs.decode_digital_output_snapshot(
        _raw(**{key: value}), sample_duration_s=0.1)

    assert snapshot.state == digital_outputs.UNKNOWN
    assert snapshot.authority == digital_outputs.AUTHORITY_UNKNOWN
    assert snapshot.outputs == ()
    assert snapshot.raw == {}
    assert key in snapshot.reason


def test_missing_required_register_fails_entire_snapshot_closed():
    raw = _raw()
    del raw["GO[4]"]

    snapshot = digital_outputs.decode_digital_output_snapshot(
        raw, sample_duration_s=0.1)

    assert snapshot.state == digital_outputs.UNKNOWN
    assert snapshot.outputs == ()
    assert "GO[4]" in snapshot.reason


@pytest.mark.parametrize("duration", (-0.1, math.nan, math.inf, 2.001))
def test_invalid_or_stale_acquisition_duration_fails_closed(duration):
    snapshot = digital_outputs.decode_digital_output_snapshot(
        _raw(), sample_duration_s=duration)

    assert snapshot.state == digital_outputs.UNKNOWN
    assert snapshot.outputs == ()
    assert "duration" in snapshot.reason.lower()


def test_reader_issues_exact_bounded_queries_and_never_assigns_output():
    drive = _Drive(_raw())

    snapshot = digital_outputs.read_digital_output_snapshot(
        drive, clock_fn=drive.clock)

    assert snapshot.state == digital_outputs.CURRENT
    assert tuple(command for command, _kwargs in drive.commands) == (
        *(f"OL[{index}]" for index in range(1, 5)),
        *(f"GO[{index}]" for index in range(1, 5)),
        "OP",
    )
    assert all(
        kwargs == {"timeout_ms": digital_outputs.READ_TIMEOUT_MS}
        for _command, kwargs in drive.commands)
    assert all("=" not in command for command, _kwargs in drive.commands)
    assert all(
        not command.startswith(("OB[", "OC[", "XO["))
        for command, _kwargs in drive.commands)


def test_reader_fails_closed_on_read_error_or_session_change():
    failed = _Drive(_raw(**{"GO[3]": IOError("read failed")}))
    failed_snapshot = digital_outputs.read_digital_output_snapshot(
        failed, clock_fn=failed.clock)
    assert failed_snapshot.state == digital_outputs.UNKNOWN
    assert "GO[3]" in failed_snapshot.reason

    changed = _Drive(_raw())
    original_command = changed.command

    def rotating_command(command, **kwargs):
        result = original_command(command, **kwargs)
        if command == "GO[2]":
            changed.session = object()
        return result

    changed.command = rotating_command
    changed_snapshot = digital_outputs.read_digital_output_snapshot(
        changed, clock_fn=changed.clock)
    assert changed_snapshot.state == digital_outputs.UNKNOWN
    assert "session" in changed_snapshot.reason.lower()


def test_source_identity_is_frozen_to_installed_gold_documentation():
    sources = {source.key: source.sha256 for source in digital_outputs.SOURCES}

    assert sources == {
        "op": (
            "BFDE83C2EC00D1FCD3F2A8ADA8CCF7288836DE0E510431591E8A7078EF61FDF6"
        ),
        "go": (
            "4D4E7CBCE1EADBA8ED820224B441AFC370D5E264676A4AD22CC399361CE247BE"
        ),
        "ol": (
            "F6A33CF4609B61AA31EB36F3B811387537A8208B495ACCA81CFB9A7B93331291"
        ),
        "gold_twitter_installation_guide": (
            "F8AE035E8A1E621BEA7679B4B042551AB7F23AC203E3D59AA681ABC53A2E64F7"
        ),
    }
    for source in digital_outputs.SOURCES:
        with Path(source.location).open("rb") as handle:
            observed = hashlib.file_digest(handle, "sha256").hexdigest().upper()
        assert observed == source.sha256
