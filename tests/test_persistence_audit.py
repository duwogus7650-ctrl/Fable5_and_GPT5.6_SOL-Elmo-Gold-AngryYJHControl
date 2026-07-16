import hashlib
import json
import math
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

import persistence_audit as pa


IDENTITY_A = "elmo-sn4-sha256:" + "a" * 64
IDENTITY_B = "elmo-sn4-sha256:" + "b" * 64
EPOCH_A = "11111111-1111-4111-8111-111111111111"
EPOCH_B = "22222222-2222-4222-8222-222222222222"
EPOCH_C = "33333333-3333-4333-8333-333333333333"


def _prepare(ledger, *, phase="P2", identity=IDENTITY_A,
             epoch=EPOCH_A, original=None, applied=None):
    if phase == "P1":
        original = original or {"KP[1]": 0.08, "KI[1]": 780.0}
        applied = applied or {"KP[1]": 0.09, "KI[1]": 800.0}
    else:
        original = original or {
            "KP[2]": 0.000153, "KI[2]": 20.0, "KP[3]": 180.0}
        applied = applied or {
            "KP[2]": 0.000166, "KI[2]": 10.7, "KP[3]": 85.2114}
    return ledger.prepare(
        phase=phase,
        drive_identity=identity,
        com_port="COM3",
        firmware="Twitter 01.01.16.00 08Mar2020B01G",
        pal="90",
        boot="DSP Boot 1.0.1.6 12Feb2014G",
        connect_epoch=epoch,
        original=original,
        applied=applied,
    )


def _motor_profile(**overrides):
    values = {
        "PL[1]": 10.0,
        "CL[1]": 8.0,
        "VH[2]": 100_000,
        "CA[19]": 4_000,
        "CA[28]": 2,
        "CA[18]": 4_096,
        "MC": 10.0,
        "UM": 5,
    }
    values.update(overrides)
    return values


def _prepare_motor(ledger, *, original=None, applied=None):
    return ledger.prepare(
        phase="MOTOR",
        drive_identity=IDENTITY_A,
        com_port="COM3",
        firmware="Twitter 01.01.16.00 08Mar2020B01G",
        pal="90",
        boot="DSP Boot 1.0.1.6 12Feb2014G",
        connect_epoch=EPOCH_A,
        original=original or _motor_profile(),
        applied=applied or _motor_profile(**{"CA[19]": 4_001}),
        initial_state="RAM_APPLYING",
    )


def _context(**overrides):
    values = dict(
        drive_identity=IDENTITY_A,
        firmware="Twitter 01.01.16.00 08Mar2020B01G",
        pal="90",
        boot="DSP Boot 1.0.1.6 12Feb2014G",
        connect_epoch=EPOCH_B,
    )
    values.update(overrides)
    return pa.AuditContext(**values)


def _readback(record, target="applied", **overrides):
    values = {"MO": 0.0, "SO": 0.0, "VX": 0.0}
    values.update(dict(getattr(record, target)))
    values.update(overrides)
    return values


def _audit_snapshot(record, target="applied", **overrides):
    values = _readback(record, target, **overrides)
    values.update({"PS": -2.0, "MF": 0.0})
    return values


def _audit_evidence(record, decision, context=None, target="applied"):
    context = context or _context()
    snapshot = _audit_snapshot(record, target)
    return pa.build_audit_evidence(
        record, context, snapshot, snapshot, True, decision.resolution)


def _canonical_sha(schema, payload):
    body = json.dumps(
        {"schema": schema, "payload": payload},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def test_prepare_writes_valid_identity_primary_persisting_record(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = pa.PersistenceLedger(path)

    record = _prepare(ledger)
    snapshot = ledger.load()

    assert record.state == "PERSISTING"
    assert uuid.UUID(record.record_id).version == 4
    assert snapshot.active == {IDENTITY_A: record}
    assert snapshot.resolved == {}
    assert path.is_file()
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["schema"] == pa.LEDGER_SCHEMA
    assert envelope["sha256"] == _canonical_sha(
        envelope["schema"], envelope["payload"])
    assert envelope["payload"]["active"][IDENTITY_A]["registers"] == [
        "KP[2]", "KI[2]", "KP[3]"]


def test_motor_profile_accepts_vh_max_and_pl_equal_mc(tmp_path):
    vh_max = (1 << 31) - 1
    original = _motor_profile(**{
        "PL[1]": 10.0, "CL[1]": 9.999, "VH[2]": vh_max})
    applied = _motor_profile(**{
        "PL[1]": 10.0, "CL[1]": 9.999, "VH[2]": vh_max,
        "CA[19]": 4_001,
    })

    record = _prepare_motor(
        pa.PersistenceLedger(tmp_path / "ledger.json"),
        original=original,
        applied=applied,
    )

    assert record.state == "RAM_APPLYING"
    assert record.original["VH[2]"] == float(vh_max)
    assert record.original["PL[1]"] == record.original["MC"]
    assert record.original["CL[1]"] < record.original["MC"]


@pytest.mark.parametrize("field", ["original", "applied"])
def test_motor_profile_rejects_vh_above_signed_32_bit_max(tmp_path, field):
    path = tmp_path / "ledger.json"
    profiles = {
        "original": _motor_profile(),
        "applied": _motor_profile(**{"CA[19]": 4_001}),
    }
    profiles[field] = dict(profiles[field], **{"VH[2]": 1 << 31})

    with pytest.raises(ValueError, match=r"VH\[2\].*2147483647"):
        _prepare_motor(
            pa.PersistenceLedger(path),
            original=profiles["original"],
            applied=profiles["applied"],
        )

    assert not path.exists()


@pytest.mark.parametrize("field", ["original", "applied"])
def test_motor_profile_rejects_cl_equal_to_mc(tmp_path, field):
    path = tmp_path / "ledger.json"
    profiles = {
        "original": _motor_profile(),
        "applied": _motor_profile(**{"CA[19]": 4_001}),
    }
    profiles[field] = dict(profiles[field], **{"CL[1]": 10.0})

    with pytest.raises(ValueError, match=r"CL\[1\].*strictly less than MC"):
        _prepare_motor(
            pa.PersistenceLedger(path),
            original=profiles["original"],
            applied=profiles["applied"],
        )

    assert not path.exists()


def test_prepare_refuses_second_active_incident_for_same_identity(tmp_path):
    ledger = pa.PersistenceLedger(tmp_path / "ledger.json")
    first = _prepare(ledger)

    with pytest.raises(pa.ActiveIncidentError):
        _prepare(ledger, phase="P1")

    assert ledger.active_for_identity(IDENTITY_A) == first


def test_mark_unknown_survives_new_ledger_instance(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = pa.PersistenceLedger(path)
    record = _prepare(ledger)

    unknown = ledger.mark_unknown(record.record_id, "TimeoutError")
    reloaded = pa.PersistenceLedger(path).active_for_identity(IDENTITY_A)

    assert unknown.state == "UNKNOWN"
    assert reloaded == unknown
    assert reloaded.reason == "TimeoutError"


def test_sv_success_moves_active_to_preserved_resolved_archive(tmp_path):
    ledger = pa.PersistenceLedger(tmp_path / "ledger.json")
    first = _prepare(ledger)
    resolved = ledger.resolve_sv_success(first.record_id)
    second = _prepare(ledger, phase="P1")
    ledger.mark_unknown(second.record_id, "reply-lost")
    snapshot = ledger.load()

    assert resolved.state == "RESOLVED"
    assert resolved.resolution == "SV_ACKNOWLEDGED"
    assert resolved.resolved_utc is not None
    assert snapshot.resolved[first.record_id] == resolved
    assert snapshot.active[IDENTITY_A].record_id == second.record_id


def test_resolve_from_read_only_audit_preserves_archive(tmp_path):
    ledger = pa.PersistenceLedger(tmp_path / "ledger.json")
    record = _prepare(ledger)
    ledger.mark_unknown(record.record_id, "TimeoutError")
    decision = pa.adjudicate_read_only(
        record, _context(), _readback(record), True)

    archived = ledger.resolve_from_audit(
        record.record_id, decision, _audit_evidence(record, decision))

    assert archived.resolution == "APPLIED_PROFILE_AFTER_RESET"
    assert archived.audit_evidence["operator_reset_attested"] is True
    assert archived.audit_evidence["context"]["connect_epoch"] == EPOCH_B
    assert archived.audit_evidence["first_snapshot"] == \
        archived.audit_evidence["second_snapshot"]
    assert ledger.active_for_identity(IDENTITY_A) is None
    assert ledger.load().resolved[record.record_id] == archived


def test_archived_audit_evidence_tamper_is_detected_even_with_new_outer_hash(
        tmp_path):
    path = tmp_path / "ledger.json"
    ledger = pa.PersistenceLedger(path)
    record = _prepare(ledger)
    ledger.mark_unknown(record.record_id, "TimeoutError")
    decision = pa.adjudicate_read_only(
        record, _context(), _readback(record), True)
    ledger.resolve_from_audit(
        record.record_id, decision, _audit_evidence(record, decision))
    envelope = json.loads(path.read_text(encoding="utf-8"))
    evidence = envelope["payload"]["resolved"][record.record_id][
        "audit_evidence"]
    evidence["first_snapshot"]["MF"] = 1.0
    evidence["second_snapshot"]["MF"] = 1.0
    envelope["sha256"] = _canonical_sha(
        envelope["schema"], envelope["payload"])
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(pa.LedgerIntegrityError, match="evidence sha256"):
        ledger.load()


def test_atomic_replace_failure_leaves_existing_bytes_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    ledger = pa.PersistenceLedger(path)
    _prepare(ledger)
    before = path.read_bytes()

    def fail_replace(_src, _dst):
        raise OSError("replace blocked")

    monkeypatch.setattr(pa.os, "replace", fail_replace)
    with pytest.raises(pa.LedgerWriteError):
        _prepare(ledger, identity=IDENTITY_B)

    assert path.read_bytes() == before
    assert list(pa.PersistenceLedger(path).load().active) == [IDENTITY_A]


def test_mutations_serialize_load_modify_commit_across_ledger_instances(
        tmp_path, monkeypatch):
    """Mutation tooth: a stale second load must not overwrite the first record."""
    path = tmp_path / "ledger.json"
    ledger_a = pa.PersistenceLedger(path)
    ledger_b = pa.PersistenceLedger(path)
    a_loaded = threading.Event()
    release_a = threading.Event()
    b_loaded = threading.Event()
    errors = []
    original_a_load = ledger_a.load
    original_b_load = ledger_b.load
    a_calls = 0

    def blocked_a_load():
        nonlocal a_calls
        snapshot = original_a_load()
        a_calls += 1
        if a_calls == 1:
            a_loaded.set()
            if not release_a.wait(2.0):
                raise AssertionError("test did not release first mutation")
        return snapshot

    def observed_b_load():
        b_loaded.set()
        return original_b_load()

    monkeypatch.setattr(ledger_a, "load", blocked_a_load)
    monkeypatch.setattr(ledger_b, "load", observed_b_load)

    def run(ledger, identity, epoch):
        try:
            _prepare(ledger, identity=identity, epoch=epoch)
        except Exception as exc:  # surfaced after both threads are joined
            errors.append(exc)

    first = threading.Thread(
        target=run, args=(ledger_a, IDENTITY_A, EPOCH_A), daemon=True)
    second = threading.Thread(
        target=run, args=(ledger_b, IDENTITY_B, EPOCH_B), daemon=True)
    first.start()
    assert a_loaded.wait(1.0)
    second.start()
    serialized = not b_loaded.wait(0.2)
    release_a.set()
    first.join(2.0)
    second.join(2.0)

    assert serialized, "second ledger loaded a stale snapshot during mutation"
    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    assert set(pa.PersistenceLedger(path).load().active) == {
        IDENTITY_A, IDENTITY_B}


def test_mutation_lock_blocks_a_second_python_process(tmp_path):
    path = tmp_path / "ledger.json"
    ready = tmp_path / "child-ready"
    ledger = pa.PersistenceLedger(path)
    _prepare(ledger, identity=IDENTITY_A, epoch=EPOCH_A)
    script = """
import sys
from pathlib import Path
import persistence_audit as pa
path, ready, identity, epoch = sys.argv[1:]
Path(ready).write_text('ready', encoding='ascii')
pa.PersistenceLedger(path).prepare(
    phase='P1', drive_identity=identity, com_port='COM_CHILD',
    firmware='FW', pal='90', boot='BOOT', connect_epoch=epoch,
    original={'KP[1]': 0.08, 'KI[1]': 780.0},
    applied={'KP[1]': 0.09, 'KI[1]': 800.0})
"""

    with ledger._mutation_lock():
        child = subprocess.Popen(
            [sys.executable, "-c", script, str(path), str(ready),
             IDENTITY_B, EPOCH_B], cwd=str(Path(pa.__file__).parent),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 3.0
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "child did not reach the mutation boundary"
        time.sleep(0.15)
        assert child.poll() is None, "child bypassed the interprocess file lock"

    stdout, stderr = child.communicate(timeout=5.0)
    assert child.returncode == 0, (stdout, stderr)
    assert set(ledger.load().active) == {IDENTITY_A, IDENTITY_B}


def test_invalid_checksum_is_fail_closed(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = pa.PersistenceLedger(path)
    _prepare(ledger)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["active"][IDENTITY_A]["applied"]["KI[2]"] = 99.0
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(pa.LedgerIntegrityError, match="sha256"):
        pa.PersistenceLedger(path).load()


def test_unknown_schema_is_fail_closed_even_with_matching_checksum(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = pa.PersistenceLedger(path)
    _prepare(ledger)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["schema"] = "angryyjh-persistence-ledger/v999"
    envelope["sha256"] = _canonical_sha(
        envelope["schema"], envelope["payload"])
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(pa.LedgerIntegrityError, match="schema"):
        pa.PersistenceLedger(path).load()


def test_semantically_invalid_record_is_fail_closed_with_matching_checksum(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = pa.PersistenceLedger(path)
    _prepare(ledger)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    record = envelope["payload"]["active"][IDENTITY_A]
    record["registers"] = ["KP[2]", "KI[2]"]
    envelope["sha256"] = _canonical_sha(
        envelope["schema"], envelope["payload"])
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(pa.LedgerIntegrityError, match="record"):
        pa.PersistenceLedger(path).load()


def test_malformed_json_is_fail_closed_and_not_treated_as_empty(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(pa.LedgerIntegrityError):
        pa.PersistenceLedger(path).load()


def test_missing_initialized_ledger_is_fail_closed_after_restart(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = pa.PersistenceLedger(path)
    _prepare(ledger)
    assert ledger._lock_path.exists()
    path.unlink()

    with pytest.raises(pa.LedgerIntegrityError, match="missing after initialization"):
        pa.PersistenceLedger(path).load()


def test_existing_but_unreadable_ledger_is_fail_closed(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    path.write_text("placeholder", encoding="utf-8")

    def unreadable(_self):
        raise PermissionError("denied")

    monkeypatch.setattr(type(path), "read_bytes", unreadable)
    with pytest.raises(pa.LedgerUnreadableError):
        pa.PersistenceLedger(path).load()


@pytest.mark.parametrize(
    "target, expected_status, expected_resolution",
    [
        ("applied", "RESOLVED_APPLIED_PROFILE", "APPLIED_PROFILE_AFTER_RESET"),
        ("original", "RESOLVED_ORIGINAL_PROFILE", "ORIGINAL_PROFILE_AFTER_RESET"),
    ],
)
def test_adjudicate_known_truth_for_applied_and_original(
        tmp_path, target, expected_status, expected_resolution):
    record = _prepare(pa.PersistenceLedger(tmp_path / "ledger.json"))

    decision = pa.adjudicate_read_only(
        record, _context(), _readback(record, target), True)

    assert decision.resolved
    assert decision.status == expected_status
    assert decision.resolution == expected_resolution


@pytest.mark.parametrize(
    "target, expected",
    [
        ("applied", "RESOLVED_APPLIED_PROFILE"),
        ("original", "RESOLVED_ORIGINAL_PROFILE"),
    ],
)
def test_adjudicate_p1_uses_exact_p1_register_set(tmp_path, target, expected):
    record = _prepare(
        pa.PersistenceLedger(tmp_path / "ledger.json"), phase="P1")

    decision = pa.adjudicate_read_only(
        record, _context(), _readback(record, target), True)

    assert record.registers == ("KP[1]", "KI[1]")
    assert decision.status == expected
    assert decision.resolved


def test_adjudicate_tolerance_boundary_is_inclusive(tmp_path):
    record = _prepare(pa.PersistenceLedger(tmp_path / "ledger.json"))
    boundary = _readback(record)
    boundary["KI[2]"] = record.applied["KI[2]"] * (1.0 + record.rtol)
    outside = dict(boundary)
    outside["KI[2]"] = record.applied["KI[2]"] * (1.0 + record.rtol + 1e-7)

    assert pa.adjudicate_read_only(
        record, _context(), boundary, True).status == "RESOLVED_APPLIED_PROFILE"
    assert pa.adjudicate_read_only(
        record, _context(), outside, True).status == "CONFIG_DRIFT_UNKNOWN"


@pytest.mark.parametrize(
    "context, attested, expected",
    [
        (_context(drive_identity=IDENTITY_B), True, "IDENTITY_MISMATCH"),
        (_context(firmware="different"), True, "FIRMWARE_MISMATCH"),
        (_context(pal="91"), True, "PAL_MISMATCH"),
        (_context(boot="different"), True, "BOOT_MISMATCH"),
        (_context(connect_epoch=EPOCH_A), True, "SESSION_NOT_CHANGED"),
        (_context(), False, "RESET_NOT_ATTESTED"),
    ],
)
def test_adjudicate_failed_identity_target_session_and_reset_gates_are_unresolved(
        tmp_path, context, attested, expected):
    record = _prepare(pa.PersistenceLedger(tmp_path / "ledger.json"))

    decision = pa.adjudicate_read_only(
        record, context, _readback(record), attested)

    assert not decision.resolved
    assert decision.status == expected


@pytest.mark.parametrize("name,value", [
    ("MO", 0.5), ("SO", -0.5), ("VX", 1e-12),
])
def test_adjudicate_requires_exact_disabled_stationary_zero(
        tmp_path, name, value):
    record = _prepare(pa.PersistenceLedger(tmp_path / "ledger.json"))
    readback = _readback(record, **{name: value})

    decision = pa.adjudicate_read_only(record, _context(), readback, True)

    assert not decision.resolved
    assert decision.status == "DRIVE_NOT_DISABLED_STATIONARY"


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, True, "10.7"])
def test_adjudicate_rejects_nonpositive_nonfinite_or_nonnumeric_gain(
        tmp_path, bad):
    record = _prepare(pa.PersistenceLedger(tmp_path / "ledger.json"))
    readback = _readback(record)
    readback["KI[2]"] = bad

    decision = pa.adjudicate_read_only(record, _context(), readback, True)

    assert not decision.resolved
    assert decision.status == "READBACK_INVALID"


def test_adjudicate_requires_exact_register_and_safety_key_set(tmp_path):
    record = _prepare(pa.PersistenceLedger(tmp_path / "ledger.json"))
    missing = _readback(record)
    missing.pop("KP[3]")
    extra = _readback(record, IQ=0.0)

    assert pa.adjudicate_read_only(
        record, _context(), missing, True).status == "READBACK_INVALID"
    assert pa.adjudicate_read_only(
        record, _context(), extra, True).status == "READBACK_INVALID"


def test_adjudicate_equal_or_overlapping_targets_is_never_guessed(tmp_path):
    same = {"KP[1]": 0.08, "KI[1]": 780.0}
    baseline = _prepare(
        pa.PersistenceLedger(tmp_path / "ledger.json"), phase="P1")
    raw = baseline.to_dict()
    raw.update({"original": same, "applied": same})
    record = pa.PersistenceRecord.from_dict(raw)

    decision = pa.adjudicate_read_only(
        record, _context(), _readback(record), True)

    assert not decision.resolved
    assert decision.status == "UNRESOLVED_NO_DISTINGUISHING_CHANGE"


def test_prepare_refuses_indistinguishable_profiles_before_any_ledger_write(
        tmp_path):
    path = tmp_path / "ledger.json"
    same = {"KP[1]": 0.08, "KI[1]": 780.0}

    with pytest.raises(ValueError, match="indistinguishable"):
        _prepare(pa.PersistenceLedger(path), phase="P1",
                 original=same, applied=same)

    assert not path.exists()


def test_adjudicate_mixed_or_neither_target_stays_unknown(tmp_path):
    record = _prepare(pa.PersistenceLedger(tmp_path / "ledger.json"))
    mixed = _readback(record)
    mixed["KP[2]"] = record.original["KP[2]"]
    neither = _readback(record)
    neither.update({"KP[2]": 0.5, "KI[2]": 5.0, "KP[3]": 40.0})

    assert pa.adjudicate_read_only(
        record, _context(), mixed, True).status == "CONFIG_DRIFT_UNKNOWN"
    assert pa.adjudicate_read_only(
        record, _context(), neither, True).status == "CONFIG_DRIFT_UNKNOWN"


@pytest.mark.parametrize("field,bad", [
    ("original", {"KP[2]": 0.0001, "KI[2]": 0.0, "KP[3]": 1.0}),
    ("applied", {"KP[2]": 0.0001, "KI[2]": math.nan, "KP[3]": 1.0}),
])
def test_prepare_rejects_invalid_authority_without_creating_ledger(
        tmp_path, field, bad):
    path = tmp_path / "ledger.json"
    kwargs = {field: bad}

    with pytest.raises(ValueError):
        _prepare(pa.PersistenceLedger(path), **kwargs)

    assert not path.exists()


def test_only_resolved_decisions_can_archive_an_unknown(tmp_path):
    ledger = pa.PersistenceLedger(tmp_path / "ledger.json")
    record = _prepare(ledger)
    ledger.mark_unknown(record.record_id, "TimeoutError")
    unresolved = pa.adjudicate_read_only(
        record, _context(connect_epoch=EPOCH_A), _readback(record), True)

    with pytest.raises(ValueError, match="resolved"):
        ledger.resolve_from_audit(record.record_id, unresolved, {})

    assert ledger.active_for_identity(IDENTITY_A).state == "UNKNOWN"


def test_resolved_audit_decision_is_bound_to_its_exact_record(tmp_path):
    ledger = pa.PersistenceLedger(tmp_path / "ledger.json")
    record_a = _prepare(ledger)
    record_b = _prepare(
        ledger, phase="P1", identity=IDENTITY_B,
        epoch="33333333-3333-4333-8333-333333333333")
    decision_a = pa.adjudicate_read_only(
        record_a, _context(), _readback(record_a), True)

    with pytest.raises(ValueError, match="record"):
        ledger.resolve_from_audit(
            record_b.record_id, decision_a,
            _audit_evidence(record_a, decision_a))

    assert set(ledger.load().active) == {IDENTITY_A, IDENTITY_B}


def test_resolved_audit_decision_cannot_reuse_incident_connection_epoch(tmp_path):
    ledger = pa.PersistenceLedger(tmp_path / "ledger.json")
    record = _prepare(ledger)
    forged_stale = pa.AuditDecision(
        status="RESOLVED_APPLIED_PROFILE",
        resolved=True,
        resolution="APPLIED_PROFILE_AFTER_RESET",
        record_id=record.record_id,
        drive_identity=record.drive_identity,
        connect_epoch=record.connect_epoch,
    )

    with pytest.raises(ValueError, match="epoch"):
        ledger.resolve_from_audit(record.record_id, forged_stale, {})

    assert ledger.active_for_identity(IDENTITY_A) == record


def test_resolved_audit_evidence_epoch_must_equal_decision_epoch(tmp_path):
    ledger = pa.PersistenceLedger(tmp_path / "ledger.json")
    record = _prepare(ledger)
    decision = pa.adjudicate_read_only(
        record, _context(connect_epoch=EPOCH_B), _readback(record), True)
    mismatched_context = _context(connect_epoch=EPOCH_C)
    snapshot = _audit_snapshot(record)
    evidence = pa.build_audit_evidence(
        record, mismatched_context, snapshot, snapshot, True,
        decision.resolution)

    with pytest.raises(ValueError, match="evidence epoch"):
        ledger.resolve_from_audit(record.record_id, decision, evidence)

    assert ledger.active_for_identity(IDENTITY_A) == record
