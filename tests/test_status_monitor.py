"""Pure offline contracts for the session-only Status Monitor v0.1."""

from __future__ import annotations

import ast
import builtins
from dataclasses import FrozenInstanceError
from pathlib import Path
import socket
import subprocess

import pytest

import status_monitor as sm


SIGNALS = ("PX", "VX", "PE", "IQ", "MO")
IDENTITY_A = "elmo-sn4-sha256:" + "a" * 64
IDENTITY_B = "elmo-sn4-sha256:" + "b" * 64


def _telemetry(**overrides):
    sample = {
        "pos": 123,
        "vel": -4.5,
        "pos_err": 2,
        "iq": 0.125,
        "mo": 0,
    }
    sample.update(overrides)
    return sample


def _active_model(*, generation=1, drive_identity=IDENTITY_A, config=None):
    model = sm.StatusMonitorModel(config=config)
    model.activate_generation(generation, drive_identity)
    return model


def _observe(model, telemetry=None, *, generation=1, sequence=1,
             drive_identity=IDENTITY_A, fresh=True):
    return model.observe(
        _telemetry() if telemetry is None else telemetry,
        generation=generation,
        sequence=sequence,
        drive_identity=drive_identity,
        fresh=fresh,
    )


def _assert_blank(snapshot):
    assert snapshot.current is False
    assert snapshot.sequence is None
    assert all(line.value is None for line in snapshot.lines)


def test_signal_allowlist_mapping_units_and_descriptions_are_exact_and_immutable():
    assert tuple(sm.SIGNAL_SPECS) == SIGNALS
    assert {
        code: (spec.telemetry_key, spec.unit, spec.description)
        for code, spec in sm.SIGNAL_SPECS.items()
    } == {
        "PX": ("pos", "cnt", "Position"),
        "VX": ("vel", "cnt/s", "Velocity"),
        "PE": ("pos_err", "cnt", "Position Error"),
        "IQ": ("iq", "A", "Active Current"),
        "MO": ("mo", "state", "Motor Enable"),
    }
    with pytest.raises(TypeError):
        sm.SIGNAL_SPECS["PX"] = sm.SIGNAL_SPECS["PX"]
    with pytest.raises(FrozenInstanceError):
        sm.SIGNAL_SPECS["PX"].unit = "rev"


def test_default_config_and_snapshot_are_frozen_ordered_and_blank():
    model = sm.StatusMonitorModel()

    assert model.config is sm.DEFAULT_CONFIG
    assert model.config.lines == SIGNALS
    snapshot = model.snapshot()
    _assert_blank(snapshot)
    assert snapshot.generation is None
    assert snapshot.drive_alias is None
    assert tuple(line.signal for line in snapshot.lines) == SIGNALS
    with pytest.raises(FrozenInstanceError):
        model.config.lines = ()
    with pytest.raises(FrozenInstanceError):
        snapshot.current = True
    with pytest.raises(FrozenInstanceError):
        snapshot.lines[0].value = 99


@pytest.mark.parametrize(
    "lines,error",
    (
        (("PX", "PX"), "unique"),
        (("PX", "ST"), "unknown signal"),
        (("px",), "unknown signal"),
        ((1,), "plain strings"),
        (tuple("PX" for _ in range(17)), "at most 16"),
        (["PX"], "tuple"),
    ),
)
def test_config_rejects_duplicate_unknown_non_string_oversized_or_mutable_lines(
        lines, error):
    with pytest.raises(sm.ConfigRejected, match=error):
        sm.StatusMonitorConfig(lines=lines)


def test_reordered_subset_config_is_preserved_exactly():
    config = sm.StatusMonitorConfig(lines=("MO", "IQ", "PX"))
    model = sm.StatusMonitorModel(config=config)

    assert model.config is config
    assert tuple(line.signal for line in model.snapshot().lines) == (
        "MO", "IQ", "PX")


def test_immutable_insert_delete_move_and_reset_line_editing():
    original = sm.StatusMonitorConfig(lines=("PX", "MO"))

    inserted = sm.insert_line(original, "IQ", 1)
    assert inserted.lines == ("PX", "IQ", "MO")
    assert original.lines == ("PX", "MO")

    moved = sm.move_line(inserted, "MO", -2)
    assert moved.lines == ("MO", "PX", "IQ")
    assert inserted.lines == ("PX", "IQ", "MO")

    deleted = sm.delete_line(moved, "PX")
    assert deleted.lines == ("MO", "IQ")
    assert moved.lines == ("MO", "PX", "IQ")

    assert sm.reset_lines() is sm.DEFAULT_CONFIG
    assert sm.reset_lines().lines == SIGNALS


@pytest.mark.parametrize(
    "operation,error",
    (
        (lambda c: sm.insert_line(c, "PX", 0), "already present"),
        (lambda c: sm.insert_line(c, "ST", 0), "unknown signal"),
        (lambda c: sm.insert_line(c, "IQ", True), "index"),
        (lambda c: sm.insert_line(c, "IQ", -1), "index"),
        (lambda c: sm.insert_line(c, "IQ", 3), "index"),
        (lambda c: sm.delete_line(c, "IQ"), "not present"),
        (lambda c: sm.move_line(c, "ST", 1), "unknown signal"),
        (lambda c: sm.move_line(c, "PX", True), "delta"),
        (lambda c: sm.move_line(c, "PX", -1), "outside"),
        (lambda c: sm.move_line(c, "MO", 1), "outside"),
    ),
)
def test_invalid_line_edits_are_rejected_without_mutating_input(operation, error):
    config = sm.StatusMonitorConfig(lines=("PX", "MO"))
    before = config.lines

    with pytest.raises(sm.ConfigRejected, match=error):
        operation(config)

    assert config.lines is before


def test_zero_delta_move_is_an_explicit_identity_preserving_noop():
    config = sm.StatusMonitorConfig(lines=("MO", "PX"))
    assert sm.move_line(config, "MO", 0) is config


def test_validate_config_rechecks_an_adversarially_forged_instance():
    forged = object.__new__(sm.StatusMonitorConfig)
    object.__setattr__(forged, "lines", ("PX", "drive.stop"))

    with pytest.raises(sm.ConfigRejected, match="unknown signal"):
        sm.validate_config(forged)


@pytest.mark.parametrize(
    "identity",
    (
        "elmo-sn4-sha256:" + "A" * 64,
        "elmo-sn4-sha256:" + "a" * 63,
        "elmo-sn4-sha256:" + "g" * 64,
        "sha256:" + "a" * 64,
        " " + IDENTITY_A,
        IDENTITY_A + " ",
        b"elmo-sn4-sha256:" + b"a" * 64,
        None,
    ),
)
def test_generation_activation_requires_exact_canonical_hashed_sn4_identity(identity):
    model = sm.StatusMonitorModel()
    before = model.snapshot()

    with pytest.raises(sm.StatusMonitorError, match="canonical drive identity"):
        model.activate_generation(1, identity)

    assert model.snapshot() is before
    assert model.active_generation is None
    assert model.active_drive_identity is None


@pytest.mark.parametrize("generation", (0, -1, True, 1.5, "1"))
def test_invalid_generation_activation_is_rejected_without_state_change(generation):
    model = _active_model(generation=3)
    before = model.snapshot()

    with pytest.raises(sm.StatusMonitorError, match="positive integer"):
        model.activate_generation(generation, IDENTITY_A)

    assert model.snapshot() is before
    assert model.active_generation == 3
    assert model.active_drive_identity == IDENTITY_A


def test_complete_finite_identity_bound_increasing_sample_becomes_current():
    model = _active_model(generation=7)

    snapshot = _observe(model, generation=7)

    assert snapshot.current is True
    assert snapshot.generation == 7
    assert snapshot.drive_alias == "Drive01"
    assert IDENTITY_A not in repr(snapshot)
    assert "AAAAAAAAAAAA" not in repr(snapshot)
    assert snapshot.sequence == 1
    assert snapshot.reason == "CURRENT"
    assert tuple(line.value for line in snapshot.lines) == (
        123, -4.5, 2, 0.125, 0)
    assert model.snapshot() is snapshot


@pytest.mark.parametrize(
    "mutation,generation,sequence,identity,fresh",
    (
        ({}, 1, 1, IDENTITY_A, False),
        ({}, 2, 1, IDENTITY_A, True),
        ({}, 1, 0, IDENTITY_A, True),
        ({}, 1, -1, IDENTITY_A, True),
        ({}, 1, True, IDENTITY_A, True),
        ({}, 1, 1.5, IDENTITY_A, True),
        ({}, 1, 1, IDENTITY_B, True),
        ({}, 1, 1, "elmo-sn4-sha256:" + "A" * 64, True),
        ({"pos": None}, 1, 1, IDENTITY_A, True),
        ({"vel": float("inf")}, 1, 1, IDENTITY_A, True),
        ({"pos_err": float("nan")}, 1, 1, IDENTITY_A, True),
        ({"iq": "0.1"}, 1, 1, IDENTITY_A, True),
        ({"mo": False}, 1, 1, IDENTITY_A, True),
        ({"mo": 2}, 1, 1, IDENTITY_A, True),
    ),
    ids=(
        "stale", "wrong-generation", "zero-sequence", "negative-sequence",
        "bool-sequence", "float-sequence", "wrong-identity",
        "malformed-identity", "missing-like", "infinite", "nan",
        "string-number", "bool-value", "invalid-motor-state",
    ),
)
def test_stale_wrong_authority_bad_sequence_and_nonfinite_values_revoke_all(
        mutation, generation, sequence, identity, fresh):
    model = _active_model()
    sample = _telemetry(**mutation)

    snapshot = _observe(
        model,
        sample,
        generation=generation,
        sequence=sequence,
        drive_identity=identity,
        fresh=fresh,
    )

    _assert_blank(snapshot)
    assert snapshot.generation == 1
    assert snapshot.drive_alias == "Drive01"


def test_wrong_identity_revokes_without_changing_binding_or_sequence_floor():
    model = _active_model()
    assert _observe(model, sequence=4).current

    mismatch = _observe(
        model, _telemetry(pos=999), sequence=5, drive_identity=IDENTITY_B)

    _assert_blank(mismatch)
    assert mismatch.reason == "IDENTITY_MISMATCH"
    assert model.active_drive_identity == IDENTITY_A
    assert _observe(model, _telemetry(pos=777), sequence=5).current


def test_malformed_observed_identity_is_revoked_without_raising():
    model = _active_model()

    snapshot = _observe(
        model, drive_identity="elmo-sn4-sha256:" + "A" * 64)

    _assert_blank(snapshot)
    assert snapshot.reason == "INVALID_DRIVE_IDENTITY"


@pytest.mark.parametrize("missing", ("pos", "vel", "pos_err", "iq", "mo"))
def test_any_missing_required_telemetry_field_revokes_every_line(missing):
    model = _active_model(config=sm.StatusMonitorConfig(lines=("PX",)))
    sample = _telemetry()
    del sample[missing]

    snapshot = _observe(model, sample)

    _assert_blank(snapshot)


def test_replay_revokes_values_without_lowering_the_sequence_floor():
    model = _active_model()
    assert _observe(model, sequence=4).current

    replay = _observe(model, _telemetry(pos=999), sequence=4)
    _assert_blank(replay)
    regression = _observe(model, _telemetry(pos=888), sequence=3)
    _assert_blank(regression)

    restored = _observe(model, _telemetry(pos=777), sequence=5)
    assert restored.current is True
    assert restored.sequence == 5
    assert restored.lines[0].value == 777


def test_generation_reset_allows_sequence_one_and_revokes_old_values():
    model = _active_model(generation=10)
    assert _observe(model, generation=10, sequence=99).current

    reset = model.activate_generation(11, IDENTITY_A)
    _assert_blank(reset)
    assert reset.generation == 11
    assert reset.drive_alias == "Drive01"
    current = _observe(model, _telemetry(pos=11), generation=11, sequence=1)
    assert current.current is True
    assert current.sequence == 1
    assert current.lines[0].value == 11


def test_explicit_same_generation_same_identity_reset_permits_sequence_one():
    model = _active_model(generation=3)
    _observe(model, generation=3, sequence=8)

    model.activate_generation(3, IDENTITY_A)

    assert _observe(model, generation=3, sequence=1).current


def test_same_generation_can_rebind_identity_only_through_explicit_activation():
    model = _active_model(generation=3)
    _observe(model, generation=3, sequence=8)

    mismatch = _observe(
        model, generation=3, sequence=9, drive_identity=IDENTITY_B)
    _assert_blank(mismatch)
    assert model.active_drive_identity == IDENTITY_A

    rebound = model.activate_generation(3, IDENTITY_B)
    _assert_blank(rebound)
    assert rebound.drive_alias == "Drive01"
    assert _observe(
        model,
        generation=3,
        sequence=1,
        drive_identity=IDENTITY_B,
    ).current


class _ExplodingTelemetry(dict):
    def __getitem__(self, key):
        raise RuntimeError(r"secret C:\Users\alice\target COM3 SN=123")


def test_observer_exceptions_are_contained_and_do_not_leak_local_details():
    model = _active_model()

    snapshot = _observe(model, _ExplodingTelemetry())

    _assert_blank(snapshot)
    assert snapshot.reason == "OBSERVER_ERROR_LOCAL"
    assert "alice" not in repr(snapshot)
    assert "COM3" not in repr(snapshot)


def test_explicit_revoke_is_nonthrowing_and_blanks_all_values():
    model = _active_model()
    _observe(model)

    revoked = model.revoke(object())

    _assert_blank(revoked)
    assert revoked.reason == "TELEMETRY_REVOKED"


def test_end_generation_is_nonthrowing_and_clears_all_authority_and_floor():
    model = _active_model(generation=4)
    assert _observe(model, generation=4, sequence=99).current

    ended = model.end_generation(object())

    _assert_blank(ended)
    assert ended.reason == "GENERATION_ENDED"
    assert ended.generation is None
    assert ended.drive_alias is None
    assert model.active_generation is None
    assert model.active_drive_identity is None
    _assert_blank(_observe(model, generation=4, sequence=100))

    model.activate_generation(4, IDENTITY_A)
    assert _observe(model, generation=4, sequence=1).current


def test_config_change_revokes_values_but_preserves_authority_and_sequence_floor():
    model = _active_model()
    _observe(model, sequence=1)

    changed = model.replace_config(sm.StatusMonitorConfig(lines=("MO", "PX")))

    _assert_blank(changed)
    assert changed.drive_alias == "Drive01"
    assert tuple(line.signal for line in changed.lines) == ("MO", "PX")
    _assert_blank(_observe(model, sequence=1))
    current = _observe(model, sequence=2)
    assert current.current
    assert tuple(line.value for line in current.lines) == (0, 123)


def test_config_is_session_only_and_contains_no_identity_or_persistence_api():
    config = sm.StatusMonitorConfig(lines=("MO", "PX", "IQ"))

    assert "identity" not in repr(config).lower()
    assert set(config.__dataclass_fields__) == {"lines"}
    for forbidden_api in (
            "save_config", "load_config", "encode_config", "decode_config",
            "CONFIG_SCHEMA", "MAX_CONFIG_BYTES"):
        assert not hasattr(sm, forbidden_api)


def test_pure_operations_perform_no_file_network_process_or_serial_io(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Status Monitor attempted external I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    config = sm.insert_line(sm.StatusMonitorConfig(lines=("PX",)), "MO", 1)
    config = sm.move_line(config, "MO", -1)
    config = sm.delete_line(config, "PX")
    model = _active_model(config=config)
    _observe(model)
    model.revoke("stale")
    model.replace_config(sm.reset_lines())
    model.activate_generation(2, IDENTITY_B)
    model.end_generation("connection stopped")

    assert calls == []


def test_module_is_qt_drive_serial_and_persistence_free_by_construction():
    tree = ast.parse(Path(sm.__file__).read_text(encoding="utf-8"))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(
                alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint({
        "PyQt6", "main", "elmo_link", "serial", "autotune_current",
        "autotune_velpos", "single_axis_motion", "json", "os", "pathlib",
        "tempfile", "socket", "subprocess",
    })
