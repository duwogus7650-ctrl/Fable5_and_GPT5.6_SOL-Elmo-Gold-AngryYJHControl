"""Offline contract for crash-safe Motor Settings persistence.

No test loads the vendor DLL or touches a serial port.  The fake transport is
the only command surface and every durable path is redirected to ``tmp_path``.
"""

from __future__ import annotations

import math
import threading
import uuid

import pytest

import elmo_link
import persistence_audit as pa
from elmo_link import ElmoLink


FW = "Twitter 01.01.16.00 08Mar2020B01G"
PAL = "90"
BOOT = "DSP Boot 1.0.1.6 12Feb2014G"
ORIGINAL = {
    "PL[1]": 10.0,
    "CL[1]": 5.0,
    "VH[2]": 10000.0,
    "CA[19]": 8.0,
    "CA[28]": 0.0,
    "CA[18]": 65536.0,
    "MC": 20.0,
    "UM": 3.0,
}
DESIRED_WRITES = {
    "PL[1]": 12.0,
    "CL[1]": 6.0,
    "VH[2]": 9000,
    "CA[19]": 10,
    "CA[28]": 2,
}


class FakeComm:
    IsConnected = True

    def __init__(self, *, values=None, serial="MOTOR-DRIVE-A",
                 before_assignment=None, before_sv=None,
                 fail_once=None, fail_applies=True, corrupt_readback=None):
        self.values = {
            "SN[4]": serial, "VR": FW, "VP": PAL, "VB": BOOT,
            "MO": 0, "SO": 0, "VX": 0, "PS": -2, "MF": 0,
            **ORIGINAL,
        }
        if values:
            self.values.update(values)
        self.commands = []
        self.before_assignment = before_assignment
        self.before_sv = before_sv
        self.fail_once = fail_once
        self.fail_applies = fail_applies
        self.corrupt_readback = dict(corrupt_readback or {})

    def SendCommandAnalyzeError(self, command, _response, _error, _timeout):
        core = "".join(str(command).split()).rstrip(";")
        self.commands.append(core)
        if core == "SV":
            if self.before_sv:
                self.before_sv()
            if self.fail_once == core:
                self.fail_once = None
                return False, "", "simulated SV reply loss"
            return True, "", None
        if "=" in core:
            if self.before_assignment:
                self.before_assignment(core)
            name, raw = core.split("=", 1)
            value = float(raw)
            if value.is_integer():
                value = int(value)
            failing = self.fail_once == core
            if not failing or self.fail_applies:
                self.values[name] = value
            if failing:
                self.fail_once = None
                return False, "", "simulated assignment reply loss"
            return True, "", None
        if core in self.corrupt_readback:
            return True, str(self.corrupt_readback[core]), None
        value = self.values.get(core, "")
        return True, str(value), None


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    path = tmp_path / "persistence_unknown.json"
    monkeypatch.setattr(elmo_link, "_PERSISTENCE_UNKNOWN_PATH", str(path))
    return path


def _new_link(*, comm=None, epoch=None):
    link = ElmoLink("COM_TEST")
    comm = comm or FakeComm()
    link._comm = comm
    link._connection_epoch = epoch or str(uuid.uuid4())
    assert link.transaction_identity().startswith("elmo-sn4-sha256:")
    for query in ("VR", "VP", "VB"):
        link.command(query)
    comm.commands.clear()
    return link, comm


def test_clear_link_rejects_unprepared_sv_before_vendor_io():
    link, comm = _new_link()

    with pytest.raises(RuntimeError, match="prepared persistence"):
        link.command(" SV ; ")

    assert comm.commands == []


def test_one_prepared_capability_cannot_send_two_concurrent_sv_calls():
    link, comm = _new_link()
    record_id = link.prepare_persistence_attempt(
        phase="P1", registers=("KP[1]", "KI[1]"),
        original={"KP[1]": 0.05, "KI[1]": 700.0},
        applied={"KP[1]": 0.06, "KI[1]": 800.0})
    gate = threading.Barrier(3)
    outcomes = []

    def send_sv():
        gate.wait()
        try:
            link.command("SV", _persistence_attempt_id=record_id)
            outcomes.append("ACK")
        except RuntimeError:
            outcomes.append("BLOCKED")

    threads = [threading.Thread(target=send_sv) for _ in range(2)]
    for thread in threads:
        thread.start()
    gate.wait()
    for thread in threads:
        thread.join(timeout=2.0)

    assert outcomes.count("ACK") == 1
    assert outcomes.count("BLOCKED") == 1
    assert comm.commands.count("SV") == 1
    link.complete_persistence_attempt(record_id)


def test_foreign_attempt_id_cannot_consume_prepared_sv_capability():
    link, comm = _new_link()
    record_id = link.prepare_persistence_attempt(
        phase="P1", registers=("KP[1]", "KI[1]"),
        original={"KP[1]": 0.05, "KI[1]": 700.0},
        applied={"KP[1]": 0.06, "KI[1]": 800.0})
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command("SV", _persistence_attempt_id=str(uuid.uuid4()))

    assert comm.commands == []
    link.command("SV", _persistence_attempt_id=record_id)
    link.complete_persistence_attempt(record_id)
    assert comm.commands == ["SV"]


def test_motor_cannot_prepare_directly_in_sv_ready_state(isolated_ledger):
    link, _comm = _new_link()

    with pytest.raises(ValueError, match="RAM_APPLYING"):
        link.prepare_persistence_attempt(
            phase="MOTOR", registers=tuple(ORIGINAL),
            original={**ORIGINAL, "PL[1]": 9.0}, applied=ORIGINAL,
            initial_state="PERSISTING")

    assert not isolated_ledger.exists()


def test_motor_wal_exists_before_first_assignment_and_sv_is_single_use(
        isolated_ledger):
    observed = {}

    def before_assignment(_core):
        if "first_state" not in observed:
            record = next(iter(pa.PersistenceLedger(isolated_ledger).load().active.values()))
            observed["first_state"] = record.state
            observed["phase"] = record.phase

    def before_sv():
        record = next(iter(pa.PersistenceLedger(isolated_ledger).load().active.values()))
        observed["sv_state"] = record.state

    link, comm = _new_link(comm=FakeComm(
        before_assignment=before_assignment, before_sv=before_sv))

    ok, message = link.write_motor_params(DESIRED_WRITES, persist=True)

    assert ok, message
    assert observed == {
        "first_state": "RAM_APPLYING", "phase": "MOTOR",
        "sv_state": "PERSISTING"}
    assert comm.commands.count("SV") == 1
    snapshot = pa.PersistenceLedger(isolated_ledger).load()
    assert not snapshot.active
    archived = next(iter(snapshot.resolved.values()))
    assert archived.phase == "MOTOR"
    assert archived.resolution == "SV_ACKNOWLEDGED"
    assert archived.original == ORIGINAL
    assert archived.applied == {**ORIGINAL, **{
        name: float(value) for name, value in DESIRED_WRITES.items()}}


def test_motor_apply_uses_bounded_order_and_verifies_every_target():
    link, comm = _new_link()

    ok, message = link.write_motor_params(DESIRED_WRITES, persist=True)

    assert ok, message
    assignments = [command for command in comm.commands if "=" in command]
    assert assignments == [
        "VH[2]=9000", "CA[19]=10", "CA[28]=2",
        "PL[1]=12", "CL[1]=6"]
    for register in DESIRED_WRITES:
        last_write = max(i for i, command in enumerate(comm.commands)
                         if command.startswith(register + "="))
        assert register in comm.commands[last_write + 1:]
    assert comm.commands[-1] == "SV"


def test_motor_partial_apply_failure_rolls_back_and_never_sends_sv(
        isolated_ledger):
    comm = FakeComm(fail_once="CA[19]=10", fail_applies=True)
    link, comm = _new_link(comm=comm)

    ok, message = link.write_motor_params(DESIRED_WRITES, persist=True)

    assert not ok
    assert "rollback" in message.lower() or "복원" in message
    assert "SV" not in comm.commands
    assert {name: float(comm.values[name]) for name in ORIGINAL} == ORIGINAL
    snapshot = pa.PersistenceLedger(isolated_ledger).load()
    assert not snapshot.active
    assert next(iter(snapshot.resolved.values())).resolution == \
        "RAM_ROLLBACK_VERIFIED"


def test_motor_rollback_failure_is_durable_unknown_and_restart_blocks_mutation(
        isolated_ledger):
    class RollbackLoss(FakeComm):
        def SendCommandAnalyzeError(self, command, response, error, timeout):
            core = "".join(str(command).split()).rstrip(";")
            if core == "CA[19]=8":
                self.commands.append(core)
                return False, "", "rollback lost"
            return super().SendCommandAnalyzeError(command, response, error, timeout)

    link, comm = _new_link(comm=RollbackLoss(
        fail_once="CA[19]=10", fail_applies=True))

    ok, message = link.write_motor_params(DESIRED_WRITES, persist=True)

    assert not ok and "UNKNOWN" in message
    assert "SV" not in comm.commands
    active = next(iter(pa.PersistenceLedger(isolated_ledger).load().active.values()))
    assert active.state == "UNKNOWN"

    restarted, restarted_comm = _new_link(comm=FakeComm(values=comm.values))
    restarted_comm.commands.clear()
    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        restarted.command("PL[1]=11")
    assert restarted_comm.commands == []


def test_motor_sv_reply_loss_leaves_durable_unknown_and_exactly_one_sv(
        isolated_ledger):
    link, comm = _new_link(comm=FakeComm(fail_once="SV"))

    ok, message = link.write_motor_params(DESIRED_WRITES, persist=True)

    assert not ok and "UNKNOWN" in message
    assert comm.commands.count("SV") == 1
    active = next(iter(pa.PersistenceLedger(isolated_ledger).load().active.values()))
    assert active.state == "UNKNOWN"
    with pytest.raises(RuntimeError):
        link.command("SV")
    assert comm.commands.count("SV") == 1


def test_motor_no_change_skips_assignments_journal_and_sv(isolated_ledger):
    writes = {name: ORIGINAL[name] for name in DESIRED_WRITES}
    link, comm = _new_link()

    ok, message = link.write_motor_params(writes, persist=True)

    assert ok and "NO_CHANGE" in message
    assert not any("=" in command or command == "SV" for command in comm.commands)
    assert not isolated_ledger.exists()


def test_stale_ui_ca18_conversion_basis_blocks_before_assignment_and_sv():
    link, comm = _new_link()

    ok, message = link.write_motor_params(
        DESIRED_WRITES, persist=True, expected_ca18=12345)

    assert not ok
    assert "CA[18]" in message and "changed" in message.lower()
    assert not any("=" in command or command == "SV"
                   for command in comm.commands)


@pytest.mark.parametrize("writes", [
    {"PL[1]": 10.0},
    {**DESIRED_WRITES, "KP[1]": 1.0},
    {**DESIRED_WRITES, "CA[28]": 5},
    {**DESIRED_WRITES, "CA[19]": 1.5},
    {**DESIRED_WRITES, "CA[19]": 0},
    {**DESIRED_WRITES, "VH[2]": 0},
    {**DESIRED_WRITES, "VH[2]": 2**31},
    {**DESIRED_WRITES, "PL[1]": math.nan},
    {**DESIRED_WRITES, "CL[1]": True},
    {**DESIRED_WRITES, "CL[1]": 13.0},
])
def test_invalid_motor_profile_is_rejected_with_zero_vendor_io(writes):
    link, comm = _new_link()

    ok, _message = link.write_motor_params(writes, persist=True)

    assert not ok
    assert comm.commands == []


@pytest.mark.parametrize("dependency,value", [
    ("MC", 11.0),
    ("CA[18]", 0),
    ("UM", math.nan),
    ("MO", 0.5),
    ("MO", math.nan),
    ("SO", 1),
    ("VX", 0.5),
    ("PS", 0),
    ("MF", math.nan),
    ("MF", 1),
])
def test_invalid_live_motor_dependency_blocks_before_assignment_and_sv(
        dependency, value):
    link, comm = _new_link(comm=FakeComm(values={dependency: value}))

    ok, _message = link.write_motor_params(DESIRED_WRITES, persist=True)

    assert not ok
    assert not any("=" in command or command == "SV" for command in comm.commands)


def test_motor_official_vh_upper_boundary_is_accepted_by_offline_fake():
    writes = {**DESIRED_WRITES, "VH[2]": 2**31 - 1}
    link, comm = _new_link()

    ok, message = link.write_motor_params(writes, persist=True)

    assert ok, message
    assert "VH[2]=2147483647" in comm.commands
    assert comm.commands.count("SV") == 1


def test_motor_cl_equal_mc_is_rejected_before_assignment_and_sv():
    writes = {**DESIRED_WRITES, "PL[1]": 20.0, "CL[1]": 20.0}
    link, comm = _new_link()

    ok, message = link.write_motor_params(writes, persist=True)

    assert not ok
    assert "CL[1]" in message and "< MC" in message
    assert not any("=" in command or command == "SV" for command in comm.commands)


def test_post_wal_profile_change_blocks_first_assignment_and_sv(
        isolated_ledger):
    link, comm = _new_link()
    original_prepare = link.prepare_persistence_attempt

    def prepare_then_external_change(*args, **kwargs):
        record_id = original_prepare(*args, **kwargs)
        comm.values["PL[1]"] = 11.0
        return record_id

    link.prepare_persistence_attempt = prepare_then_external_change

    ok, message = link.write_motor_params(DESIRED_WRITES, persist=True)

    assert not ok and "UNKNOWN" in message
    assert not any("=" in command or command == "SV" for command in comm.commands)
    active = next(iter(pa.PersistenceLedger(isolated_ledger).load().active.values()))
    assert active.state == "UNKNOWN"


def test_first_assignment_boundary_rechecks_operational_state(
        isolated_ledger):
    class EnableAtFirstAssignmentBoundary(FakeComm):
        def __init__(self):
            super().__init__()
            self.mo_reads = 0

        def SendCommandAnalyzeError(self, command, response, error, timeout):
            core = "".join(str(command).split()).rstrip(";")
            if core == "MO":
                self.mo_reads += 1
                # Two preflight snapshots + one post-WAL snapshot precede the
                # first per-assignment software boundary.
                if self.mo_reads == 4:
                    self.values["MO"] = 1
            return super().SendCommandAnalyzeError(
                command, response, error, timeout)

    link, comm = _new_link(comm=EnableAtFirstAssignmentBoundary())

    ok, message = link.write_motor_params(DESIRED_WRITES, persist=True)

    assert not ok and "UNKNOWN" in message
    assert not any("=" in command or command == "SV" for command in comm.commands)
    active = next(iter(pa.PersistenceLedger(isolated_ledger).load().active.values()))
    assert active.state == "UNKNOWN"


def test_unsafe_state_after_forward_write_prevents_rollback_and_sv(
        isolated_ledger):
    class EnableAfterFirstForwardWrite(FakeComm):
        def SendCommandAnalyzeError(self, command, response, error, timeout):
            result = super().SendCommandAnalyzeError(
                command, response, error, timeout)
            core = "".join(str(command).split()).rstrip(";")
            if core == "VH[2]=9000":
                self.values["MO"] = 1
            return result

    link, comm = _new_link(comm=EnableAfterFirstForwardWrite())

    ok, message = link.write_motor_params(DESIRED_WRITES, persist=True)

    assert not ok and "UNKNOWN" in message
    assignments = [command for command in comm.commands if "=" in command]
    assert assignments == ["VH[2]=9000"]
    assert "SV" not in comm.commands
    active = next(iter(pa.PersistenceLedger(isolated_ledger).load().active.values()))
    assert active.state == "UNKNOWN"


def test_each_rollback_write_rechecks_operational_state(
        isolated_ledger):
    class EnableAfterFirstRollbackWrite(FakeComm):
        def SendCommandAnalyzeError(self, command, response, error, timeout):
            result = super().SendCommandAnalyzeError(
                command, response, error, timeout)
            core = "".join(str(command).split()).rstrip(";")
            if core == "CA[28]=0":
                self.values["MO"] = 1
            return result

    comm = EnableAfterFirstRollbackWrite(
        fail_once="CA[28]=2", fail_applies=True)
    link, comm = _new_link(comm=comm)

    ok, message = link.write_motor_params(DESIRED_WRITES, persist=True)

    assert not ok and "UNKNOWN" in message
    assignments = [command for command in comm.commands if "=" in command]
    assert assignments[:4] == [
        "VH[2]=9000", "CA[19]=10", "CA[28]=2", "CA[28]=0"]
    assert "CA[19]=8" not in assignments
    assert "VH[2]=10000" not in assignments
    assert "SV" not in comm.commands
    active = next(iter(pa.PersistenceLedger(isolated_ledger).load().active.values()))
    assert active.state == "UNKNOWN"


def test_post_persisting_safety_change_blocks_sv_and_stays_unknown(
        isolated_ledger):
    link, comm = _new_link()
    original_mark = link.mark_persistence_attempt_persisting

    def mark_then_external_enable(record_id):
        original_mark(record_id)
        comm.values["MO"] = 1

    link.mark_persistence_attempt_persisting = mark_then_external_enable

    ok, message = link.write_motor_params(DESIRED_WRITES, persist=True)

    assert not ok and "UNKNOWN" in message
    assert "before SV" in message
    assert "SV" not in comm.commands
    active = next(iter(pa.PersistenceLedger(isolated_ledger).load().active.values()))
    assert active.state == "UNKNOWN"


def test_post_persisting_profile_change_blocks_sv_and_stays_unknown(
        isolated_ledger):
    link, comm = _new_link()
    original_mark = link.mark_persistence_attempt_persisting

    def mark_then_external_profile_change(record_id):
        original_mark(record_id)
        comm.values["PL[1]"] = 13.0

    link.mark_persistence_attempt_persisting = mark_then_external_profile_change

    ok, message = link.write_motor_params(DESIRED_WRITES, persist=True)

    assert not ok and "UNKNOWN" in message
    assert "SV" not in comm.commands
    active = next(iter(pa.PersistenceLedger(isolated_ledger).load().active.values()))
    assert active.state == "UNKNOWN"


def test_final_safety_query_catches_enable_after_full_pre_sv_snapshot(
        isolated_ledger):
    class EnableAtFinalSafetyQuery(FakeComm):
        def __init__(self):
            super().__init__()
            self.um_reads = 0
            self.arm_final_mo = False

        def SendCommandAnalyzeError(self, command, response, error, timeout):
            core = "".join(str(command).split()).rstrip(";")
            if core == "MO" and self.arm_final_mo:
                self.arm_final_mo = False
                self.values["MO"] = 1
            result = super().SendCommandAnalyzeError(
                command, response, error, timeout)
            if core == "UM":
                self.um_reads += 1
                # preflight x2, post-WAL, applied x2, then post-PERSISTING
                # full snapshot.  The following MO is the final safety-only
                # boundary immediately before the one-shot SV.
                if self.um_reads == 6:
                    self.arm_final_mo = True
            return result

    link, comm = _new_link(comm=EnableAtFinalSafetyQuery())

    ok, message = link.write_motor_params(DESIRED_WRITES, persist=True)

    assert not ok and "UNKNOWN" in message
    assert comm.um_reads >= 6
    assert "SV" not in comm.commands
    active = next(iter(pa.PersistenceLedger(isolated_ledger).load().active.values()))
    assert active.state == "UNKNOWN"


def test_motor_post_reset_audit_accepts_zero_enum_and_queries_only(
        isolated_ledger):
    source, _ = _new_link()
    record_id = source.prepare_persistence_attempt(
        phase="MOTOR",
        registers=tuple(ORIGINAL),
        original={**ORIGINAL, "PL[1]": 9.0},
        applied=ORIGINAL,
        initial_state="RAM_APPLYING")
    source.mark_persistence_attempt_unknown(record_id, "crash-before-sv")
    reconnected, comm = _new_link(comm=FakeComm(values=ORIGINAL))
    comm.commands.clear()

    result = reconnected.audit_persistence_after_reset(True)

    assert result["status"] == "RESOLVED_APPLIED_PROFILE"
    assert result["phase"] == "MOTOR"
    assert not any("=" in command or command in {"SV", "LD", "RS"}
                   for command in comm.commands)


def test_feedback_direct_persistence_is_blocked_before_any_vendor_io():
    link, comm = _new_link()

    ok, message = link.write_feedback_params(
        [("CA[41]", 30), ("CA[17]", 5), ("CA[18]", 65536)],
        persist=True)

    assert not ok
    assert "durable" in message.lower() or "transaction" in message.lower()
    assert comm.commands == []
