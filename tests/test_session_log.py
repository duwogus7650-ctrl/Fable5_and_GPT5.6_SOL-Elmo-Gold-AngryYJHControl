"""Pure, offline contracts for the read-only session event log."""

from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, timezone

import pytest

import session_log


HASHED_ID_A = "elmo-sn4-sha256:" + ("a" * 64)
HASHED_ID_B = "elmo-sn4-sha256:" + ("b" * 64)


def _utc_now():
    return datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)


class _MonotonicClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        self.value += 0.1
        return self.value


def _log(*, capacity=16):
    return session_log.SessionLog(
        capacity=capacity,
        utc_now=_utc_now,
        monotonic_now=_MonotonicClock(),
    )


def _telemetry(sequence, *, mo=0, valid=True, error=None, received=99.9):
    return {
        "pos": 10,
        "vel": 0,
        "pos_err": 0,
        "iq": 0.0,
        "mo": mo,
        "telemetry_valid": valid,
        "telemetry_error": error,
        "telemetry_sequence": sequence,
        "telemetry_received_monotonic": received,
        "_sample_started_monotonic": received - 0.01,
        "_sample_finished_monotonic": received,
        "_sample_duration_s": 0.01,
        "session_coordinate_known": valid,
        "encoder_maintenance_reconnect_required": False,
    }


def test_connection_generation_makes_old_target_events_historical():
    log = _log()
    first = log.begin_connection(
        target_identity=HASHED_ID_A,
        metadata={"fw": "Twitter", "pal": "90", "boot": "DSP"},
    )
    telemetry = log.record_telemetry(_telemetry(1))

    assert first.generation == 1
    assert telemetry is not None and telemetry.generation == 1
    assert all(row["scope"] == "CURRENT" for row in log.snapshot())

    second = log.begin_connection(
        target_identity=HASHED_ID_B,
        metadata={"fw": "Twitter-2", "pal": "91", "boot": "DSP"},
    )
    rows = log.snapshot()

    assert second.generation == 2
    assert [row["scope"] for row in rows] == [
        "HISTORICAL", "HISTORICAL", "CURRENT"]
    assert rows[-1]["target_identity"] == HASHED_ID_B


def test_out_of_order_and_replayed_telemetry_is_logged_but_not_projected():
    log = _log()
    log.begin_connection(target_identity=HASHED_ID_A, metadata={})

    first = log.record_telemetry(_telemetry(10, mo=0))
    coalesced = log.record_telemetry(_telemetry(11, mo=0))
    replay = log.record_telemetry(_telemetry(10, mo=1))
    transition = log.record_telemetry(_telemetry(12, mo=1))

    assert first is not None and first.freshness == "FRESH"
    assert coalesced is None
    assert replay is not None
    assert replay.freshness == "STALE_OR_REPLAYED"
    assert replay.affects_current is False
    assert transition is not None
    assert transition.freshness == "FRESH"
    assert transition.affects_current is True


def test_invalid_telemetry_and_unknown_fault_values_fail_closed_without_crash():
    log = _log()
    log.begin_connection(target_identity=HASHED_ID_A, metadata={})

    invalid = log.record_telemetry(
        _telemetry(1, valid=False, error="identity-unverified"))
    unknown = log.record_axis_summary({
        "raw": {"MO": 0, "SO": 0, "MF": "UNKNOWN:vendor", "SR": None,
                "MS": 3},
        "errors": {"SR": "read failed"},
    })

    assert invalid is not None
    assert invalid.freshness == "INVALID"
    assert invalid.affects_current is False
    assert unknown is not None
    assert unknown.severity == "UNKNOWN"
    assert unknown.payload["raw"]["MF"] == "UNKNOWN:vendor"
    assert unknown.payload["errors"]["SR"] == "read failed"


def test_zero_raw_status_is_not_missing_or_unknown():
    log = _log()
    log.begin_connection(target_identity=HASHED_ID_A, metadata={})
    observed = log.record_axis_summary({
        "raw": {"MO": 0, "SO": 0, "MF": 0, "SR": 0, "MS": 0},
        "errors": {},
    })

    assert observed is not None
    assert observed.severity == "INFO"
    assert observed.payload["raw"] == {
        "MF": 0, "MO": 0, "MS": 0, "SO": 0, "SR": 0}


def test_known_nonzero_mf_remains_error_with_unrelated_read_error():
    log = _log()
    log.begin_connection(target_identity=HASHED_ID_A, metadata={})
    observed = log.record_axis_summary({
        "raw": {"MO": 0, "SO": 0, "MF": 8, "SR": 0, "MS": 0},
        "errors": {"CA[18]": "read failed"},
    })

    assert observed is not None
    assert observed.severity == "ERROR"
    assert observed.payload["raw"]["MF"] == 8

    partial = log.record_axis_summary({
        "raw": {"MO": 0, "MF": 8, "SR": 0, "MS": 0},
        "errors": {"SO": "read failed"},
    })
    assert partial is not None
    assert partial.severity == "ERROR"


@pytest.mark.parametrize("errors", ("transport failed", ["bad"], 7))
def test_malformed_axis_error_container_is_unknown(errors):
    log = _log()
    log.begin_connection(target_identity=HASHED_ID_A, metadata={})

    observed = log.record_axis_summary({
        "raw": {"MO": 0, "SO": 0, "MF": 0, "SR": 0, "MS": 0},
        "errors": errors,
    })

    assert observed is not None
    assert observed.severity == "UNKNOWN"
    assert observed.payload["errors_schema"] == "INVALID_NON_MAPPING"


def test_bounded_retention_preserves_monotonic_event_ids():
    log = _log(capacity=3)
    log.begin_connection(target_identity=HASHED_ID_A, metadata={})
    for index in range(5):
        log.append(
            category="workflow",
            name="step-%d" % index,
            severity="INFO",
            payload={"index": index},
        )

    rows = log.snapshot()
    assert len(rows) == 3
    assert [row["name"] for row in rows] == ["step-2", "step-3", "step-4"]
    assert [row["event_id"] for row in rows] == sorted(
        row["event_id"] for row in rows)
    assert log.dropped_count == 3


def test_payload_is_immutable_and_untrusted_identity_fields_are_redacted():
    log = _log()
    source = {
        "serial_number": "SERIAL-SECRET",
        "drive_identity": "RAW-SERIAL-SECRET",
        "nested": {"sn[4]": "ALSO-SECRET", "ok": 1},
    }
    event = log.begin_connection(
        target_identity="RAW-SERIAL-SECRET",
        metadata=source,
    )
    source["nested"]["ok"] = 999

    assert event.target_identity == "REDACTED_UNVERIFIED"
    assert event.payload["serial_number"] == "REDACTED"
    assert event.payload["drive_identity"] == "REDACTED_UNVERIFIED"
    assert event.payload["nested"]["sn[4]"] == "REDACTED"
    assert event.payload["nested"]["ok"] == 1
    with pytest.raises((AttributeError, TypeError)):
        event.payload_json = "{}"


def test_json_and_csv_exports_roundtrip_with_fixed_provenance(tmp_path):
    log = _log()
    log.begin_connection(
        target_identity=HASHED_ID_A,
        metadata={"fw": "Twitter", "pal": "90", "boot": "DSP"},
    )
    log.record_telemetry(_telemetry(1))
    log.append(
        category="recorder",
        name="READY_TO_UPLOAD",
        severity="INFO",
        payload={"detail": "finite capture"},
    )

    json_text = log.export_json_text()
    csv_text = log.export_csv_text()
    payload = json.loads(json_text)
    csv_rows = list(csv.DictReader(io.StringIO(csv_text)))

    assert payload["schema_version"] == 1
    assert payload["event_count"] == 3
    assert payload["dropped_count"] == 0
    assert payload["exported_at_utc"] == "2026-07-16T12:00:00Z"
    assert len(csv_rows) == 3
    assert json.loads(csv_rows[-1]["payload_json"])["detail"] == "finite capture"

    json_path = tmp_path / "session.json"
    csv_path = tmp_path / "session.csv"
    json_meta = log.write_json(json_path)
    csv_meta = log.write_csv(csv_path)
    assert json.loads(json_path.read_text(encoding="utf-8")) == payload
    assert list(csv.DictReader(csv_path.open(encoding="utf-8", newline=""))) == csv_rows
    assert json_meta["sha256"] == json_meta["readback_sha256"]
    assert csv_meta["sha256"] == csv_meta["readback_sha256"]


def test_default_exports_alias_target_and_redact_port_and_paths():
    log = _log()
    log.begin_connection(
        target_identity=HASHED_ID_A,
        metadata={
            "port": "COM3",
            "workspace_path": r"C:\Users\secret\private.eas",
            "detail": "=HYPERLINK(\"https://example.invalid\")",
        },
    )

    json_text = log.export_json_text()
    csv_text = log.export_csv_text()
    payload = json.loads(json_text)

    assert HASHED_ID_A not in json_text
    assert "COM3" not in json_text
    assert r"C:\Users\secret" not in json_text
    assert payload["events"][0]["target_identity"] == "target-001"
    assert payload["events"][0]["payload"]["port"] == "REDACTED"
    assert payload["events"][0]["payload"]["workspace_path"] == "REDACTED"
    assert HASHED_ID_A not in csv_text
    assert "COM3" not in csv_text


def test_atomic_replace_failure_preserves_previous_file_and_cleans_temp(
        tmp_path, monkeypatch):
    log = _log()
    log.begin_connection(target_identity=HASHED_ID_A, metadata={})
    path = tmp_path / "session.json"
    path.write_text("ORIGINAL", encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(session_log.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        log.write_json(path)

    assert path.read_text(encoding="utf-8") == "ORIGINAL"
    assert list(tmp_path.glob(".session.json.*.tmp")) == []


def test_monotonic_clock_regression_is_flagged_without_reordering():
    ticks = iter((10.0, 9.0, 11.0))
    log = session_log.SessionLog(
        capacity=8,
        utc_now=_utc_now,
        monotonic_now=lambda: next(ticks),
    )
    first = log.begin_connection(target_identity=HASHED_ID_A, metadata={})
    second = log.append(
        category="workflow", name="clock-regressed", payload={})

    assert first.event_id < second.event_id
    assert first.clock_quality == "MONOTONIC"
    assert second.clock_quality == "REGRESSED"


def test_end_connection_marks_every_event_historical_and_rejects_current_updates():
    log = _log()
    log.begin_connection(target_identity=HASHED_ID_A, metadata={})
    log.record_telemetry(_telemetry(1))
    ended = log.end_connection("operator disconnect")

    assert ended.name == "connection.closed"
    assert all(row["scope"] == "HISTORICAL" for row in log.snapshot())
    rejected = log.record_telemetry(_telemetry(2))
    assert rejected is not None
    assert rejected.freshness == "NO_ACTIVE_CONNECTION"
    assert rejected.affects_current is False
    assert rejected.generation == 0
    assert rejected.target_identity == "REDACTED_UNVERIFIED"

    axis = log.record_axis_summary({
        "raw": {"MO": 0, "SO": 0, "MF": 0, "SR": 0, "MS": 0},
        "errors": {},
    })
    assert axis is not None
    assert axis.generation == 0
    assert axis.target_identity == "REDACTED_UNVERIFIED"


def test_ui_rejected_envelope_does_not_advance_current_projection():
    log = _log()
    log.begin_connection(target_identity=HASHED_ID_A, metadata={})
    assert log.record_telemetry(_telemetry(1, mo=0)) is not None

    rejected = log.record_telemetry(
        _telemetry(2, mo=1), accepted_by_ui=False)
    corrected = log.record_telemetry(
        _telemetry(2, mo=1), accepted_by_ui=True)

    assert rejected is not None
    assert rejected.name == "telemetry.rejected"
    assert rejected.freshness == "UI_REJECTED"
    assert rejected.affects_current is False
    assert corrected is not None
    assert corrected.name == "telemetry.state"
    assert corrected.affects_current is True


def test_export_aliases_future_target_identity_references_without_hash_leak():
    log = _log()
    log.begin_connection(target_identity=HASHED_ID_A, metadata={})
    log.append(
        category="connection", name="target.change.observed",
        payload={"drive_identity": HASHED_ID_B},
    )
    log.begin_connection(target_identity=HASHED_ID_B, metadata={})

    exported = log.export_json_text()

    assert HASHED_ID_A not in exported
    assert HASHED_ID_B not in exported
    assert "target-001" in exported
    assert "target-002" in exported


def test_free_text_export_redacts_ports_user_paths_and_labeled_serials():
    log = _log()
    log.begin_connection(target_identity=HASHED_ID_A, metadata={})
    log.append(
        category="connection", name="connection.failed",
        payload={
            "detail": (
                r"COM3 failed at C:\Users\alice\private\trace.txt; "
                "serial ABC:123; SN[4]=22033647; "
                r"C:/Users/bob/private/trace.txt; target " + HASHED_ID_B)
        },
    )

    exported = log.export_json_text()

    assert "COM3" not in exported
    assert "alice" not in exported
    assert "ABC:123" not in exported
    assert "22033647" not in exported
    assert "bob" not in exported
    assert HASHED_ID_B not in exported


def test_unattributed_event_after_close_does_not_reuse_old_target_identity():
    log = _log()
    log.begin_connection(target_identity=HASHED_ID_A, metadata={})
    log.end_connection("closed")

    event = log.append(
        category="connection", name="connection.failed",
        payload={"detail": "new attempt rejected before identity admission"},
    )

    assert event.generation == 0
    assert event.target_identity == "REDACTED_UNVERIFIED"


def test_generation_state_maps_are_pruned_with_bounded_event_retention():
    log = _log(capacity=2)
    for generation in range(1, 101):
        log.begin_connection(
            target_identity=(HASHED_ID_A if generation % 2 else HASHED_ID_B),
            metadata={},
        )
        log.record_telemetry(_telemetry(1))
        log.record_axis_summary({
            "raw": {"MO": 0, "SO": 0, "MF": 0, "SR": 0, "MS": 0},
            "errors": {},
        })
        log.end_connection("cycle complete")

    retained = {row["generation"] for row in log.snapshot()
                if row["generation"] > 0}
    assert len(log.snapshot()) == 2
    assert set(log._identity_by_generation) == retained
    assert set(log._last_telemetry_sequence) <= retained
    assert set(log._last_telemetry_projection) <= retained
    assert set(log._last_axis_projection) <= retained


@pytest.mark.parametrize("prefix", ("=", "+", "-", "@", "\t", "\r"))
def test_csv_text_cells_cannot_become_spreadsheet_formulas(prefix):
    log = _log()
    log.append(
        category="local", name=prefix + "FORMULA", payload={})

    row = list(csv.DictReader(io.StringIO(log.export_csv_text())))[0]

    if prefix in ("=", "+", "-", "@"):
        assert row["name"].startswith("'" + prefix)
    else:
        assert not row["name"].startswith(prefix)


def test_snapshots_and_export_text_are_frozen_and_detached():
    log = _log()
    original = {"nested": {"value": 1}}
    log.append(category="local", name="frozen", payload=original)
    snapshot = log.snapshot()
    exported = log.export_json_text()

    original["nested"]["value"] = 2
    snapshot[0]["payload"]["nested"]["value"] = 3
    log.append(category="local", name="later", payload={})

    assert log.snapshot()[0]["payload"]["nested"]["value"] == 1
    assert json.loads(exported)["event_count"] == 1
    assert json.loads(exported)["events"][0]["payload"]["nested"]["value"] == 1


def test_oversize_event_payload_is_rejected_without_consuming_event_id():
    log = _log()

    with pytest.raises(ValueError, match="payload exceeds"):
        log.append(
            category="local", name="oversize",
            payload={"detail": "x" * (session_log.MAX_PAYLOAD_JSON_BYTES + 1)},
        )

    accepted = log.append(category="local", name="accepted", payload={})
    assert accepted.event_id == 1
    assert len(log.snapshot()) == 1


def test_serial_redaction_preserves_unrelated_diagnostic_words():
    log = _log()
    messages = (
        "snapshot creation failed",
        "serialization failed",
        "SNR estimate invalid",
        "snapped marker to sample",
    )
    log.append(
        category="local", name="diagnostics",
        payload={"messages": messages})

    assert tuple(log.snapshot()[0]["payload"]["messages"]) == messages


def test_payload_only_drive_identity_is_aliased_in_every_export():
    log = _log()
    log.append(
        category="connection", name="rejected.identity",
        payload={"drive_identity": HASHED_ID_A})

    json_text = log.export_json_text()
    csv_text = log.export_csv_text()

    assert HASHED_ID_A not in json_text
    assert HASHED_ID_A not in csv_text
    assert "target-" in json_text
    assert "target-" in csv_text


def test_all_untrusted_exported_strings_and_mapping_keys_are_redacted():
    log = _log()
    log.append(
        category=r"C:\Users\alice\private",
        name="SN[4]=22033647",
        severity="COM3",
        freshness=HASHED_ID_A,
        payload={
            r"C:\Users\bob\private.txt": "path-key",
            "SN[4]=33044758": "serial-key",
            HASHED_ID_B: "identity-key",
        })

    json_text = log.export_json_text()
    csv_text = log.export_csv_text()

    for secret in (
            "alice", "bob", "22033647", "33044758",
            "COM3", HASHED_ID_A, HASHED_ID_B):
        assert secret not in json_text
        assert secret not in csv_text


def test_csv_carries_provenance_and_drop_count_including_empty_log():
    log = _log(capacity=1)
    log.append(category="local", name="first", payload={})
    log.append(category="local", name="second", payload={})

    retained = list(csv.DictReader(io.StringIO(log.export_csv_text())))
    empty = list(csv.DictReader(io.StringIO(_log().export_csv_text())))

    assert len(retained) == 1
    assert retained[0]["row_type"] == "EVENT"
    assert retained[0]["schema_version"] == "1"
    assert retained[0]["evidence_class"] == "HOST_OBSERVED_NOT_DRIVE_HISTORY"
    assert retained[0]["event_count"] == "1"
    assert retained[0]["dropped_count"] == "1"
    assert retained[0]["exported_at_utc"] == "2026-07-16T12:00:00Z"

    assert len(empty) == 1
    assert empty[0]["row_type"] == "META"
    assert empty[0]["event_count"] == "0"
    assert empty[0]["dropped_count"] == "0"
    assert empty[0]["evidence_class"] == "HOST_OBSERVED_NOT_DRIVE_HISTORY"
