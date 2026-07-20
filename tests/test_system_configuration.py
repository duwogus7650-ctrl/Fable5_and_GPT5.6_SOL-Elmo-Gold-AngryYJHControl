"""Pure offline contracts for the host-observed System Configuration inspector."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unicodedata

import pytest

import system_configuration as sc


HASH_A = "elmo-sn4-sha256:" + ("a" * 64)
HASH_B = "elmo-sn4-sha256:" + ("b" * 64)


def _metadata(identity=HASH_A, **overrides):
    value = {
        "drive_identity": identity,
        "fw": "Twitter 01.01.16.00",
        "pal": "0",
        "boot": "DSP Boot 1.0.1.6",
        "target_type": "Gold Drive",
    }
    value.update(overrides)
    return value


def _telemetry(sequence=1, *, base=100.0, mo=0, **overrides):
    value = {
        "pos": 0,
        "vel": 0,
        "pos_err": 0,
        "iq": 0.0,
        "mo": mo,
        "telemetry_valid": True,
        "telemetry_sequence": sequence,
        "telemetry_received_monotonic": base,
        "_sample_started_monotonic": base - 0.01,
        "_sample_finished_monotonic": base,
        "_sample_duration_s": 0.01,
        "session_coordinate_known": True,
        "encoder_maintenance_reconnect_required": False,
    }
    value.update(overrides)
    return value


def _admit(model, *, generation=1, identity=HASH_A, sequence=1, base=100.0):
    return model.admit_connection(
        _metadata(identity), _telemetry(sequence, base=base),
        generation=generation,
        connection_type="Direct Access USB",
        observed_at_utc="2026-07-16T13:00:00.000000Z",
    )


def test_initial_snapshot_is_frozen_and_has_no_current_target():
    model = sc.SystemConfigurationProjection()

    snapshot = model.snapshot()

    assert snapshot.state == sc.NO_CURRENT_TARGET
    assert snapshot.generation is None
    assert snapshot.identity_alias is None
    assert snapshot.target_type is None
    assert snapshot.reason == "No admitted target"
    with pytest.raises(FrozenInstanceError):
        snapshot.state = sc.CURRENT


def test_admitted_snapshot_preserves_valid_zero_and_redacts_raw_identity():
    model = sc.SystemConfigurationProjection()

    snapshot = _admit(model)

    assert snapshot.state == sc.CURRENT
    assert snapshot.generation == 1
    assert snapshot.pal == "0"
    assert snapshot.motor_enabled is False
    assert snapshot.target_alias == "Drive01"
    assert snapshot.identity_alias == "TARGET-AAAAAAAAAAAA"
    assert HASH_A not in repr(snapshot)
    assert snapshot.topology == sc.SINGLE_DIRECT_DRIVE
    assert snapshot.clock_quality == sc.HOST_RECEIVE_ONLY


@pytest.mark.parametrize("metadata,telemetry", [
    (_metadata(identity="elmo-sn4-sha256:" + ("g" * 64)), _telemetry()),
    (_metadata(fw=""), _telemetry()),
    (_metadata(), _telemetry(encoder_maintenance_reconnect_required=0)),
    (_metadata(), _telemetry(session_coordinate_known=1)),
    (_metadata(), _telemetry(pos=None)),
], ids=(
    "malformed-identity", "missing-firmware", "non-bool-reconnect-flag",
    "non-bool-coordinate-flag", "partial-telemetry",
))
def test_admission_rejects_partial_or_ambiguous_evidence(metadata, telemetry):
    model = sc.SystemConfigurationProjection()

    with pytest.raises(sc.ProjectionRejected):
        model.admit_connection(
            metadata, telemetry, generation=1,
            connection_type="Direct Access USB")

    assert model.snapshot().state == sc.NO_CURRENT_TARGET


def test_uppercase_hash_is_rejected_by_the_canonical_lowercase_contract():
    model = sc.SystemConfigurationProjection()

    with pytest.raises(sc.ProjectionRejected, match=r"strict SN\[4\] hash"):
        _admit(model, identity="elmo-sn4-sha256:" + ("A" * 64))

    assert model.snapshot().state == sc.NO_CURRENT_TARGET


@pytest.mark.parametrize("control", ("\u202e", "\u2066", "\u2028", "\ud800"))
def test_drive_metadata_rejects_unicode_display_controls(control):
    model = sc.SystemConfigurationProjection()

    with pytest.raises(sc.ProjectionRejected, match="unsupported text"):
        model.admit_connection(
            _metadata(fw="Twitter " + control + "ONLINE"), _telemetry(),
            generation=1, connection_type="Direct Access USB")

    assert model.snapshot().state == sc.NO_CURRENT_TARGET


def test_drive_metadata_is_nfc_normalized_before_display():
    model = sc.SystemConfigurationProjection()

    snapshot = model.admit_connection(
        _metadata(fw="Cafe\u0301 Drive"), _telemetry(), generation=1,
        connection_type="Direct Access USB")

    assert snapshot.firmware == "Caf\u00e9 Drive"


def test_connection_display_metadata_neutralizes_controls_and_redacts_local_data():
    safe = sc.sanitize_connection_display_metadata(_metadata(
        fw="Twitter \u202eENILNO COM3 " + HASH_B,
        pal="90 SN[4]=12345678",
        boot=r"DSP Boot C:\Users\alice\secret.bin",
    ))

    rendered = " | ".join(safe.values())
    assert all(
        unicodedata.category(char) not in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for char in rendered)
    for secret in ("COM3", HASH_B, "12345678", "alice"):
        assert secret not in rendered
    assert safe["target_type"] == "Gold Drive"


@pytest.mark.parametrize("observed", (
    "2026-07-16", "2026-07-16T13:00:00"))
def test_observed_at_utc_rejects_timezone_naive_values(observed):
    model = sc.SystemConfigurationProjection()

    with pytest.raises(sc.ProjectionRejected, match="timezone-aware"):
        model.admit_connection(
            _metadata(), _telemetry(), generation=1,
            connection_type="Direct Access USB", observed_at_utc=observed)

    assert model.snapshot().state == sc.NO_CURRENT_TARGET


def test_observed_at_utc_normalizes_aware_offsets_to_canonical_z():
    model = sc.SystemConfigurationProjection()

    snapshot = model.admit_connection(
        _metadata(), _telemetry(), generation=1,
        connection_type="Direct Access USB",
        observed_at_utc="2026-07-16T22:00:00.123456+09:00")

    assert snapshot.observed_at_utc == "2026-07-16T13:00:00.123456Z"


def test_replay_and_source_time_regression_cannot_replace_current_snapshot():
    model = sc.SystemConfigurationProjection()
    first = _admit(model, sequence=5, base=100.0)

    with pytest.raises(sc.ProjectionRejected, match="sequence"):
        model.update_telemetry(
            _telemetry(5, base=101.0), generation=1,
            drive_identity=HASH_A)
    assert model.snapshot() is first

    with pytest.raises(sc.ProjectionRejected, match="timestamp"):
        model.update_telemetry(
            _telemetry(6, base=99.0), generation=1,
            drive_identity=HASH_A)
    assert model.snapshot() is first


def test_target_swap_is_generation_bound_and_old_updates_are_ignored():
    model = sc.SystemConfigurationProjection()
    _admit(model, generation=1, identity=HASH_A, sequence=50, base=100.0)
    second = _admit(
        model, generation=2, identity=HASH_B, sequence=1, base=200.0)

    with pytest.raises(sc.ProjectionRejected, match="generation"):
        model.update_telemetry(
            _telemetry(51, base=201.0), generation=1,
            drive_identity=HASH_A)

    assert model.snapshot() is second
    assert model.snapshot().identity_alias == "TARGET-BBBBBBBBBBBB"
    assert model.snapshot().telemetry_sequence == 1


def test_same_generation_identity_mismatch_cannot_update_projection():
    model = sc.SystemConfigurationProjection()
    current = _admit(model, generation=1, identity=HASH_A)

    with pytest.raises(sc.ProjectionRejected, match="identity"):
        model.update_telemetry(
            _telemetry(2, base=101.0), generation=1,
            drive_identity=HASH_B)

    assert model.snapshot() is current


def test_revocation_redacts_current_values_but_fresh_same_generation_can_restore():
    model = sc.SystemConfigurationProjection()
    _admit(model, generation=1, sequence=1, base=100.0)

    revoked = model.revoke_live("telemetry expired", generation=1)

    assert revoked.state == sc.NO_CURRENT_TARGET
    assert revoked.identity_alias is None
    assert revoked.firmware is None
    assert revoked.reason == "telemetry expired"

    restored = model.update_telemetry(
        _telemetry(2, base=101.0), generation=1,
        drive_identity=HASH_A,
        observed_at_utc="2026-07-16T13:00:01.000000Z")
    assert restored.state == sc.CURRENT
    assert restored.telemetry_sequence == 2
    assert restored.identity_alias == "TARGET-AAAAAAAAAAAA"


def test_disconnect_clears_internal_target_and_late_update_cannot_restore_it():
    model = sc.SystemConfigurationProjection()
    _admit(model)

    ended = model.end_connection("worker stopped", generation=1)

    assert ended.state == sc.NO_CURRENT_TARGET
    assert model.active_generation is None
    with pytest.raises(sc.ProjectionRejected, match="active connection"):
        model.update_telemetry(
            _telemetry(2, base=101.0), generation=1,
            drive_identity=HASH_A)
    assert model.snapshot() is ended


def test_same_or_older_generation_cannot_be_readmitted():
    model = sc.SystemConfigurationProjection()
    _admit(model, generation=2)

    for generation in (1, 2):
        with pytest.raises(sc.ProjectionRejected, match="newer"):
            _admit(model, generation=generation, identity=HASH_B, base=200.0)

    assert model.snapshot().identity_alias == "TARGET-AAAAAAAAAAAA"


def test_connection_type_is_allowlisted_and_never_accepts_port_text():
    model = sc.SystemConfigurationProjection()

    with pytest.raises(sc.ProjectionRejected, match="connection type"):
        model.admit_connection(
            _metadata(), _telemetry(), generation=1,
            connection_type="COM3")

    assert model.snapshot().state == sc.NO_CURRENT_TARGET


def test_target_classification_is_allowlisted_not_treated_as_board_readback():
    model = sc.SystemConfigurationProjection()

    with pytest.raises(sc.ProjectionRejected, match="target type"):
        model.admit_connection(
            _metadata(target_type="GCON Rev E"), _telemetry(), generation=1,
            connection_type="Direct Access USB")

    assert sc.FIELD_PROVENANCE["target_type"] == (
        "APPLICATION CLASSIFICATION (NOT BOARD READBACK)")
    assert model.snapshot().state == sc.NO_CURRENT_TARGET


def test_display_metadata_redacts_ports_paths_serials_and_embedded_target_hashes():
    model = sc.SystemConfigurationProjection()
    metadata = _metadata(
        fw="Twitter COM3 " + HASH_B,
        pal="90 SN[4]=12345678",
        boot=r"DSP Boot C:\Users\alice\secret.bin",
    )

    snapshot = model.admit_connection(
        metadata, _telemetry(), generation=1,
        connection_type="Direct Access USB")
    rendered = " | ".join((snapshot.firmware, snapshot.pal, snapshot.boot))

    assert "COM3" not in rendered
    assert HASH_B not in rendered
    assert "12345678" not in rendered
    assert "alice" not in rendered
    assert "[PORT_REDACTED]" in rendered
    assert "[TARGET_ID_REDACTED]" in rendered
    assert "[SERIAL_REDACTED]" in rendered
    assert "[PATH_REDACTED]" in rendered


def test_offline_reason_redacts_local_identifiers_before_snapshot_or_ui():
    model = sc.SystemConfigurationProjection()
    _admit(model)
    unsafe = (
        r"COM3; C:\Users\alice\trace.txt; SN[4]=12345678; " + HASH_B)

    snapshot = model.revoke_live(unsafe, generation=1)

    assert "COM3" not in snapshot.reason
    assert "alice" not in snapshot.reason
    assert "12345678" not in snapshot.reason
    assert HASH_B not in snapshot.reason
    assert "[PORT_REDACTED]" in snapshot.reason
    assert "[PATH_REDACTED]" in snapshot.reason
    assert "[SERIAL_REDACTED]" in snapshot.reason
    assert "[TARGET_ID_REDACTED]" in snapshot.reason


def test_fail_close_reason_sanitizer_never_blocks_redaction_or_offline_transition():
    class BrokenString:
        def __str__(self):
            raise RuntimeError("no string")

    for reason in (BrokenString(), "line one\nline two COM3", "x" * 10000):
        model = sc.SystemConfigurationProjection()
        _admit(model)

        snapshot = model.end_connection(reason, generation=1)

        assert snapshot.state == sc.NO_CURRENT_TARGET
        assert model.active_generation is None
        assert "\n" not in snapshot.reason
        assert "COM3" not in snapshot.reason
        assert len(snapshot.reason) <= 500


def test_fail_close_reason_neutralizes_unicode_display_controls_without_raising():
    model = sc.SystemConfigurationProjection()
    _admit(model)

    snapshot = model.end_connection(
        "fault \u202eENILNO\u2066\u2028second line", generation=1)

    assert snapshot.state == sc.NO_CURRENT_TARGET
    assert all(
        unicodedata.category(char)
        not in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for char in snapshot.reason)
    assert "fault ENILNO second line" == snapshot.reason
