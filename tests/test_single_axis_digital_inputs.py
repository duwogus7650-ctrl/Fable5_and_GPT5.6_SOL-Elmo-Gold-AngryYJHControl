"""Contracts for the bounded Single Axis digital-input reader."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import math
from pathlib import Path

import pytest

import single_axis_digital_inputs as digital_inputs


def _raw(**updates):
    values = {"IP": (1 << 16) | (1 << 19)}
    values.update({
        "IL[1]": 7,       # general purpose, active high
        "IL[2]": 6,       # general purpose, active low
        "IL[3]": 11,      # forward limit, active high
        "IL[4]": 10,      # forward limit, active low
        "IL[5]": 17,      # main home, active high
        "IL[6]": 263,     # sticky general purpose, active high
    })
    values.update({
        "IF[1]": 0.0,
        "IF[2]": 0.25,
        "IF[3]": 1.0,
        "IF[4]": 1.25,
        "IF[5]": 10.0,
        "IF[6]": 500.0,
    })
    values.update(updates)
    return values


class _Drive:
    def __init__(self, values, clocks=None):
        self.values = dict(values)
        self.commands = []
        self.session = object()
        self.clocks = iter(clocks or (10.0, 10.1))

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


def test_valid_snapshot_decodes_exact_six_input_read_only_rows():
    snapshot = digital_inputs.decode_digital_input_snapshot(
        _raw(), sample_duration_s=0.125)

    assert snapshot.state == digital_inputs.CURRENT
    assert snapshot.authority == digital_inputs.CURRENT_DRIVE_READ_ONLY
    assert snapshot.sample_duration_s == pytest.approx(0.125)
    assert len(snapshot.inputs) == 6
    assert tuple(row.number for row in snapshot.inputs) == tuple(range(1, 7))
    assert tuple(row.active for row in snapshot.inputs) == (
        True, False, False, True, False, False)
    assert snapshot.inputs[0].function_code == 3
    assert snapshot.inputs[0].function_label == "General purpose"
    assert snapshot.inputs[0].polarity == "ACTIVE_HIGH"
    assert snapshot.inputs[1].polarity == "ACTIVE_LOW"
    assert snapshot.inputs[2].function_label == "Forward limit (FLS)"
    assert snapshot.inputs[5].sticky is True
    assert snapshot.inputs[5].filter_ms == pytest.approx(500.0)
    assert snapshot.inputs[0].state_label == "ACTIVE · DRIVE LOGICAL"
    assert snapshot.inputs[1].state_label == "INACTIVE · DRIVE LOGICAL"
    assert "INPUTS 1..6 ONLY" in snapshot.evidence_label
    assert "NOT PHYSICAL PIN VOLTAGE" in snapshot.evidence_label
    assert "NOT STO/E-STOP EVIDENCE" in snapshot.evidence_label
    with pytest.raises(FrozenInstanceError):
        snapshot.inputs[0].active = False


def test_all_documented_function_codes_are_named_without_granting_safety():
    expected = (
        "Inhibit / freewheel",
        "Hardware + auxiliary stop",
        "Ignore",
        "General purpose",
        "Reverse limit (RLS)",
        "Forward limit (FLS)",
        "Begin motion (BG)",
        "Soft stop (ST)",
        "Main home",
        "Auxiliary home",
        "Hardware + software stop",
        "Abort / freewheel",
        "Reserved safety-compatibility code",
        "Additional abort / freewheel",
        "Engage follower / ECAM",
        "Disengage follower / ECAM",
    )

    assert digital_inputs.FUNCTION_LABELS == expected
    combined = " ".join(expected).upper()
    assert "SAFE TO MOVE" not in combined
    assert "SAFETY PASSED" not in combined
    assert "STO PASSED" not in combined


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("IP", None),
        ("IP", True),
        ("IP", -1),
        ("IP", 1 << 32),
        ("IP", 1.5),
        ("IL[1]", True),
        ("IL[1]", -1),
        ("IL[1]", 1 << 5),       # reserved bit
        ("IL[1]", 1 << 9),       # reserved bit
        ("IL[1]", 1.5),
        ("IF[1]", -0.1),
        ("IF[1]", 500.1),
        ("IF[1]", math.nan),
        ("IF[1]", math.inf),
        ("IF[1]", True),
    ),
)
def test_invalid_value_fails_entire_snapshot_closed(key, value):
    snapshot = digital_inputs.decode_digital_input_snapshot(
        _raw(**{key: value}), sample_duration_s=0.1)

    assert snapshot.state == digital_inputs.UNKNOWN
    assert snapshot.authority == digital_inputs.AUTHORITY_UNKNOWN
    assert snapshot.inputs == ()
    assert snapshot.raw == {}
    assert key in snapshot.reason


def test_missing_required_register_fails_entire_snapshot_closed():
    raw = _raw()
    del raw["IF[6]"]

    snapshot = digital_inputs.decode_digital_input_snapshot(
        raw, sample_duration_s=0.1)

    assert snapshot.state == digital_inputs.UNKNOWN
    assert snapshot.inputs == ()
    assert "IF[6]" in snapshot.reason


@pytest.mark.parametrize("duration", (-0.1, math.nan, math.inf, 2.001))
def test_invalid_or_stale_acquisition_duration_fails_closed(duration):
    snapshot = digital_inputs.decode_digital_input_snapshot(
        _raw(), sample_duration_s=duration)

    assert snapshot.state == digital_inputs.UNKNOWN
    assert snapshot.inputs == ()
    assert "duration" in snapshot.reason.lower()


def test_reader_issues_exact_bounded_queries_and_never_uses_sticky_clear():
    drive = _Drive(_raw())

    snapshot = digital_inputs.read_digital_input_snapshot(
        drive, clock_fn=drive.clock)

    assert snapshot.state == digital_inputs.CURRENT
    assert tuple(command for command, _kwargs in drive.commands) == (
        *(f"IL[{index}]" for index in range(1, 7)),
        *(f"IF[{index}]" for index in range(1, 7)),
        "IP",
    )
    assert all(
        kwargs == {"timeout_ms": digital_inputs.READ_TIMEOUT_MS}
        for _command, kwargs in drive.commands)
    assert all("=" not in command for command, _kwargs in drive.commands)
    assert all(not command.startswith("IB[") for command, _kwargs in drive.commands)


def test_reader_fails_closed_on_read_error_or_session_change():
    failed = _Drive(_raw(**{"IL[4]": IOError("read failed")}))
    failed_snapshot = digital_inputs.read_digital_input_snapshot(
        failed, clock_fn=failed.clock)
    assert failed_snapshot.state == digital_inputs.UNKNOWN
    assert "IL[4]" in failed_snapshot.reason

    changed = _Drive(_raw())
    original_command = changed.command

    def rotating_command(command, **kwargs):
        result = original_command(command, **kwargs)
        if command == "IF[3]":
            changed.session = object()
        return result

    changed.command = rotating_command
    changed_snapshot = digital_inputs.read_digital_input_snapshot(
        changed, clock_fn=changed.clock)
    assert changed_snapshot.state == digital_inputs.UNKNOWN
    assert "session" in changed_snapshot.reason.lower()


def test_source_identity_is_frozen_to_installed_gold_documentation():
    sources = {source.key: source.sha256 for source in digital_inputs.SOURCES}

    assert sources == {
        "single_axis_help": (
            "BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE"
        ),
        "ip": (
            "0594BD5A9A1B8DCC0128985747E0ED86861A917A87CB292528180B186A413336"
        ),
        "il": (
            "F5C058B8A2CE435411A8114D7BB30ADD4E640D5BBA8B14737702096BF60F99C2"
        ),
        "if": (
            "1803C3A188B45B4E0945D161211FDD04887B12727F209977C52871F4292260BA"
        ),
    }
    for source in digital_inputs.SOURCES:
        with Path(source.location).open("rb") as handle:
            observed = hashlib.file_digest(handle, "sha256").hexdigest().upper()
        assert observed == source.sha256
