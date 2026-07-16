"""Offline integration tests for the durable persistence-UNKNOWN boundary.

Every test redirects the module-level ledger path before constructing an
``ElmoLink``.  No test may inspect or mutate the workspace's real safety
ledger, and the fake transport is the only vendor-I/O surface exercised here.
"""

from __future__ import annotations

from types import SimpleNamespace
import math
import time
import uuid
from pathlib import Path

import pytest

import autotune_current as current
import elmo_link
import persistence_audit
from elmo_link import ElmoLink


DEFAULT_PERSISTENCE_LEDGER_PATH = Path(
    elmo_link._PERSISTENCE_UNKNOWN_PATH).resolve()


FW = "Twitter 01.01.16.00 08Mar2020B01G"
PAL = "90"
BOOT = "DSP Boot 1.0.1.6 12Feb2014G"
ORIGINAL_P1 = {"KP[1]": 0.06, "KI[1]": 700.0}
APPLIED_P1 = {"KP[1]": 0.0712, "KI[1]": 812.9}


class FakeComm:
    """Minimal .NET communication stand-in with an auditable command log."""

    IsConnected = True

    def __init__(self, *, serial="TEST-DRIVE-A", firmware=FW, pal=PAL,
                 boot=BOOT, values=None, on_sv=None):
        self.values = {
            "SN[4]": serial,
            "VR": firmware,
            "VP": pal,
            "VB": boot,
            "MO": 0,
            "SO": 0,
            "VX": 0,
            "PS": -2,
            "MF": 0,
            **APPLIED_P1,
        }
        if values:
            self.values.update(values)
        self.commands = []
        self.on_sv = on_sv

    def SendCommandAnalyzeError(self, command, _response, _error, _timeout):
        self.commands.append(command)
        core = "".join(str(command).split()).rstrip(";")
        if core == "SV" and self.on_sv is not None:
            self.on_sv()
        if "=" in core:
            name, literal = core.split("=", 1)
            try:
                self.values[name] = float(literal)
            except ValueError:
                self.values[name] = literal
            return True, "", None
        value = self.values.get(core, "")
        return True, value if value is None else str(value), None


@pytest.fixture(autouse=True)
def isolated_state_paths(tmp_path, monkeypatch):
    """Force all durable markers into this test's temporary directory."""
    ledger = tmp_path / "persistence_unknown.json"
    recorder = tmp_path / "recorder_unknown.json"
    monkeypatch.setattr(elmo_link, "_PERSISTENCE_UNKNOWN_PATH", str(ledger))
    monkeypatch.setattr(elmo_link, "_RECORDER_UNKNOWN_PATH", str(recorder))
    return ledger


def _new_link(*, port="COM_TEST", serial="TEST-DRIVE-A", firmware=FW,
              pal=PAL, boot=BOOT, values=None, epoch=None, on_sv=None):
    link = ElmoLink(port)
    comm = FakeComm(
        serial=serial, firmware=firmware, pal=pal, boot=boot,
        values=values, on_sv=on_sv)
    link._comm = comm
    link._connection_epoch = epoch or str(uuid.uuid4())
    # Reproduce the explicit read-only connection handshake used by the worker.
    identity = link.transaction_identity()
    assert identity and identity.startswith("elmo-sn4-sha256:")
    for query in ("VR", "VP", "VB"):
        link.command(query)
    return link, comm


def _prepare_unknown(link, *, original=None, applied=None):
    record_id = link.prepare_persistence_attempt(
        phase="P1",
        registers=current.P1_GAIN_NAMES,
        original=original or ORIGINAL_P1,
        applied=applied or APPLIED_P1,
    )
    link.mark_persistence_attempt_unknown(record_id, "SVTimeout")
    return record_id


def _bound_p1_trial(link):
    trial = current.GainTrialP1(
        original=ORIGINAL_P1, applied=APPLIED_P1)
    trial.persistence_state = current.P1_TRIAL_RAM
    trial.owner_link = link
    trial.stable_identity = link.transaction_identity()
    trial.session_token = link.transaction_session_identity()
    return trial


def _assert_record_active(ledger_path, record_id):
    snapshot = persistence_audit.PersistenceLedger(ledger_path).load()
    assert any(record.record_id == record_id
               for record in snapshot.active.values())
    return snapshot


def test_default_safety_ledger_is_user_local_not_checkout_relative():
    checkout = Path(elmo_link._HERE).resolve()

    assert not DEFAULT_PERSISTENCE_LEDGER_PATH.is_relative_to(checkout)
    assert DEFAULT_PERSISTENCE_LEDGER_PATH.parts[-3:] == (
        "AngryYJHControl", "safety", "persistence_unknown.json")


def test_p1_commit_durably_journals_before_sv(isolated_state_paths):
    observed = {}

    def observe_pre_sv():
        snapshot = persistence_audit.PersistenceLedger(
            isolated_state_paths).load()
        assert len(snapshot.active) == 1
        record = next(iter(snapshot.active.values()))
        assert record.state == "PERSISTING"
        observed["record_id"] = record.record_id

    link, comm = _new_link(values=APPLIED_P1, on_sv=observe_pre_sv)
    trial = _bound_p1_trial(link)

    ok, message = current.commit_gain_trial_p1(link, trial)

    assert ok, message
    assert observed["record_id"]
    assert comm.commands.count("SV") == 1
    snapshot = persistence_audit.PersistenceLedger(
        isolated_state_paths).load()
    assert not snapshot.active
    assert snapshot.resolved[observed["record_id"]].resolution == \
        "SV_ACKNOWLEDGED"


def test_prepared_sv_is_blocked_before_vendor_io_if_ledger_disappears(
        isolated_state_paths):
    link, comm = _new_link(values=APPLIED_P1)
    record_id = link.prepare_persistence_attempt(
        phase="P1", registers=current.P1_GAIN_NAMES,
        original=ORIGINAL_P1, applied=APPLIED_P1)
    assert record_id
    isolated_state_paths.unlink()
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command("SV")

    assert comm.commands == []


def test_deleted_initialized_ledger_blocks_restart_mutation_before_vendor_io(
        isolated_state_paths):
    source, _ = _new_link(values=APPLIED_P1)
    source.prepare_persistence_attempt(
        phase="P1", registers=current.P1_GAIN_NAMES,
        original=ORIGINAL_P1, applied=APPLIED_P1)
    isolated_state_paths.unlink()

    restarted, comm = _new_link(values=APPLIED_P1)
    comm.commands.clear()
    status = restarted.persistence_status()

    assert status["ledger_error"]
    assert status["lock_active"] is True
    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        restarted.command("KP[1]=0.1")
    assert comm.commands == []


def test_stale_record_id_cannot_close_sv_success_after_reconnect(
        isolated_state_paths):
    source, _ = _new_link(values=APPLIED_P1)
    record_id = source.prepare_persistence_attempt(
        phase="P1", registers=current.P1_GAIN_NAMES,
        original=ORIGINAL_P1, applied=APPLIED_P1)
    reconnected, _ = _new_link(values=APPLIED_P1)

    with pytest.raises(RuntimeError, match="acknowledged same-session"):
        reconnected.complete_persistence_attempt(record_id)

    _assert_record_active(isolated_state_paths, record_id)


def test_new_link_same_identity_reloads_active_latch():
    source, _ = _new_link(port="COM3")
    record_id = _prepare_unknown(source)

    reconnected, _ = _new_link(port="COM3")

    status = reconnected.persistence_status()
    assert reconnected.persistence_unknown_latched()
    assert status["lock_active"] is True
    assert status["record_id"] == record_id
    assert status["phase"] == "P1"


def test_different_identity_on_same_com_cannot_resolve_or_clear_incident(
        isolated_state_paths):
    source, _ = _new_link(port="COM3", serial="DRIVE-A")
    record_id = _prepare_unknown(source)
    other, _ = _new_link(port="COM3", serial="DRIVE-B")

    before = persistence_audit.PersistenceLedger(
        isolated_state_paths).load()
    result = other.audit_persistence_after_reset(
        operator_reset_attested=True)
    after = persistence_audit.PersistenceLedger(
        isolated_state_paths).load()

    assert result["resolved"] is False
    assert result["record_id"] is None
    assert result["other_active_count"] == 1
    assert before == after
    _assert_record_active(isolated_state_paths, record_id)


def test_same_identity_on_different_com_is_locked_by_identity():
    source, _ = _new_link(port="COM3", serial="DRIVE-A")
    record_id = _prepare_unknown(source)

    moved, _ = _new_link(port="COM9", serial="DRIVE-A")

    assert moved.persistence_unknown_latched()
    assert moved.persistence_status()["record_id"] == record_id


def test_corrupt_ledger_is_global_fail_closed_before_vendor_write(
        isolated_state_paths):
    isolated_state_paths.write_bytes(b"{not-valid-ledger")
    link, comm = _new_link(serial="UNRELATED-DRIVE")
    comm.commands.clear()

    status = link.persistence_status()
    assert status["lock_active"] is True
    assert status["ledger_error"]
    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command("KP[1]=0.1")
    assert comm.commands == []


def test_audit_rejects_same_connection_epoch_and_retains_lock():
    link, _ = _new_link(values=APPLIED_P1)
    record_id = _prepare_unknown(link)

    result = link.audit_persistence_after_reset(
        operator_reset_attested=True)

    assert result["status"] == "SESSION_NOT_CHANGED"
    assert result["resolved"] is False
    assert result["lock_active"] is True
    assert result["record_id"] == record_id


def test_audit_requires_explicit_operator_reset_attestation():
    source, _ = _new_link(values=APPLIED_P1)
    record_id = _prepare_unknown(source)
    reconnected, _ = _new_link(values=APPLIED_P1)

    result = reconnected.audit_persistence_after_reset(
        operator_reset_attested=False)

    assert result["status"] == "RESET_NOT_ATTESTED"
    assert result["resolved"] is False
    assert result["lock_active"] is True
    assert result["record_id"] == record_id


@pytest.mark.parametrize("field,bad,status", [
    ("firmware", FW + "-different", "FIRMWARE_MISMATCH"),
    ("pal", "91", "PAL_MISMATCH"),
    ("boot", BOOT + "-different", "BOOT_MISMATCH"),
])
def test_audit_requires_exact_firmware_pal_and_boot(field, bad, status):
    source, _ = _new_link(values=APPLIED_P1)
    record_id = _prepare_unknown(source)
    kwargs = {"firmware": FW, "pal": PAL, "boot": BOOT,
              "values": APPLIED_P1}
    kwargs[field] = bad
    reconnected, _ = _new_link(**kwargs)

    result = reconnected.audit_persistence_after_reset(
        operator_reset_attested=True)

    assert result["status"] == status
    assert result["resolved"] is False
    assert result["lock_active"] is True
    _assert_record_active(elmo_link._PERSISTENCE_UNKNOWN_PATH, record_id)


def test_audit_transport_path_is_strictly_query_only():
    source, _ = _new_link(values=APPLIED_P1)
    _prepare_unknown(source)
    reconnected, comm = _new_link(values=APPLIED_P1)
    comm.commands.clear()

    reconnected.audit_persistence_after_reset(
        operator_reset_attested=True)

    cores = ["".join(command.split()).rstrip(";").upper()
             for command in comm.commands]
    assert cores
    assert not any("=" in core for core in cores)
    assert not ({"SV", "LD", "RS"} & set(cores))
    assert set(cores) <= {
        "SN[4]", "VR", "VP", "VB", "MO", "SO", "VX", "PS", "MF",
        "KP[1]", "KI[1]",
    }


@pytest.mark.parametrize("profile,status,resolution,disclaimer", [
    (APPLIED_P1, "RESOLVED_APPLIED_PROFILE",
     "APPLIED_PROFILE_AFTER_RESET", "causality is not claimed"),
    (ORIGINAL_P1, "RESOLVED_ORIGINAL_PROFILE",
     "ORIGINAL_PROFILE_AFTER_RESET", "does not prove"),
])
def test_audit_resolves_complete_profile_with_causal_disclaimer(
        isolated_state_paths, profile, status, resolution, disclaimer):
    source, _ = _new_link(values=APPLIED_P1)
    record_id = _prepare_unknown(source)
    reconnected, _ = _new_link(values=profile)

    result = reconnected.audit_persistence_after_reset(
        operator_reset_attested=True)

    assert result["status"] == status
    assert result["resolved"] is True
    assert disclaimer in result["detail"]
    assert result["lock_active"] is False
    snapshot = persistence_audit.PersistenceLedger(
        isolated_state_paths).load()
    assert not snapshot.active
    assert snapshot.resolved[record_id].resolution == resolution


@pytest.mark.parametrize("values,status", [
    ({"KP[1]": APPLIED_P1["KP[1]"],
      "KI[1]": ORIGINAL_P1["KI[1]"]}, "CONFIG_DRIFT_UNKNOWN"),
    ({"KP[1]": math.nan, "KI[1]": APPLIED_P1["KI[1]"]},
     "READBACK_INVALID"),
    ({"KP[1]": 0.0, "KI[1]": APPLIED_P1["KI[1]"]},
     "READBACK_INVALID"),
])
def test_mixed_nonfinite_or_zero_readback_remains_unknown(
        isolated_state_paths, values, status):
    source, _ = _new_link(values=APPLIED_P1)
    record_id = _prepare_unknown(source)
    reconnected, _ = _new_link(values=values)

    result = reconnected.audit_persistence_after_reset(
        operator_reset_attested=True)

    assert result["status"] == status
    assert result["resolved"] is False
    assert result["lock_active"] is True
    _assert_record_active(isolated_state_paths, record_id)


def test_closeout_failure_after_successful_sv_remains_unknown(
        isolated_state_paths, monkeypatch):
    link, comm = _new_link(values=APPLIED_P1)
    trial = _bound_p1_trial(link)

    def fail_closeout(_record_id):
        raise persistence_audit.LedgerWriteError(
            "negative-control close-out failure")

    monkeypatch.setattr(
        link._persistence_ledger, "resolve_sv_success", fail_closeout)

    ok, message = current.commit_gain_trial_p1(link, trial)

    assert not ok
    assert "close-out" in message
    assert trial.persistence_state == current.P1_TRIAL_UNKNOWN
    assert comm.commands.count("SV") == 1
    assert link.persistence_unknown_latched()
    snapshot = persistence_audit.PersistenceLedger(
        isolated_state_paths).load()
    assert len(snapshot.active) == 1
    assert next(iter(snapshot.active.values())).state == "PERSISTING"


def test_unknown_blocks_mutation_before_vendor_io_but_allows_shutdown():
    source, _ = _new_link(serial="DRIVE-A")
    _prepare_unknown(source)
    link, comm = _new_link(serial="DRIVE-A")
    comm.commands.clear()

    for command in ("KP[1]=0.1", "SV", "LD", "RS"):
        with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
            link.command(command)
    assert comm.commands == []

    link.command("ST")
    link.command("TC=0", allow_motion=True)
    link.command("MO=0")
    assert comm.commands == ["ST", "TC=0", "MO=0"]


@pytest.mark.parametrize("writer,args", [
    ("motor", {"PL[1]": 10.0}),
    ("feedback", [("CA[41]", 30)]),
])
@pytest.mark.parametrize("mo_readback", [0.5, math.nan, None])
def test_direct_settings_reject_unprepared_contract_before_vendor_io(
        writer, args, mo_readback):
    link, comm = _new_link(values={"MO": mo_readback})
    comm.commands.clear()

    if writer == "motor":
        ok, message = link.write_motor_params(args, persist=True)
    else:
        ok, message = link.write_feedback_params(args, persist=True)

    assert not ok
    if writer == "motor":
        assert "profile" in message.lower()
    else:
        assert "durable" in message.lower()
    assert comm.commands == []


def test_worker_authority_invalid_p1_is_restore_only():
    from main import DriveWorker

    worker = DriveWorker("COM_TEST")
    worker._connection_identity_verified = True
    finished = time.monotonic()
    worker._record_fresh_telemetry(
        {
            "mo": 0, "vel": 0.0, "pos_err": 0.0, "iq": 0.0,
            "pos": 0,
            "_sample_started_monotonic": finished - 0.001,
            "_sample_finished_monotonic": finished,
            "_sample_duration_s": 0.001,
        })
    trial = SimpleNamespace(
        persistence_state=current.P1_TRIAL_AUTHORITY_INVALID,
        restore_only=False)
    worker._p1_gain_trial = trial

    assert worker._trial_job_guard("p1_trial_restore", trial) == (True, "")
    for kind in ("p1_trial_commit", "verify_vp", "motion_move",
                 "motor_write", "encoder_maint"):
        allowed, message = worker._trial_job_guard(kind, trial)
        assert not allowed
        assert message
