"""Offline integration tests for the durable persistence-UNKNOWN boundary.

Every test redirects the module-level ledger path before constructing an
``ElmoLink``.  No test may inspect or mutate the workspace's real safety
ledger, and the fake transport is the only vendor-I/O surface exercised here.
"""

from __future__ import annotations

from types import SimpleNamespace
import math
import threading
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
ORIGINAL_P2 = {"KP[2]": 0.00008, "KI[2]": 9.5, "KP[3]": 80.0}
APPLIED_P2 = {"KP[2]": 0.00009, "KI[2]": 10.7, "KP[3]": 85.2}
P1_CONFIG_ORIGINAL = {
    "KP[1]": 0.0712, "KI[1]": 812.9, "UM": 5, "SC[8]": 0,
    "CA[42]": 0, "CA[43]": 0, "CA[44]": 0, "CA[70]": 0,
    "SE[1]": 0, "SE[2]": 0, "SE[3]": 0, "SE[4]": 0,
    "SE[5]": 0, "SE[6]": 0, "SE[7]": 0,
}
P1_CONFIG_APPLIED = {
    **P1_CONFIG_ORIGINAL,
    "UM": 3, "CA[44]": 8, "CA[70]": 4,
    "SE[1]": 1, "SE[3]": 200, "SE[7]": 50,
}
P1_CONFIG_MUTATION_BOUNDS = {
    "KP[1]": (0.05, 0.2),
    "KI[1]": (600.0, 1000.0),
    "SE[2]": (0.0, 2.0),
    "SE[3]": (100.0, 400.0),
    "TC": (0.0, 5.0),
}
P2_LIMITS_ORIGINAL = {
    "SD": 2_000_000.0,
    "HL[2]": 1_500_000.0,
    "LL[2]": -1_500_000.0,
    "ER[2]": 1_000.0,
}
P2_LIMITS_APPLIED = {
    "SD": 4_000_000.0,
    "HL[2]": 1_970_000.0,
    "LL[2]": -1_970_000.0,
    "ER[2]": 2_000.0,
}
P2_LIMITS_MUTATION_BOUNDS = {
    "TC": (-8.0, 8.0),
    "JV": (-1_310_720.0, 1_310_720.0),
    "PA": (-(1 << 31), (1 << 31) - 1),
    "UM": (3, 5),
}


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


class LifecycleProbeRLock:
    """Real reentrant lock with deterministic lifecycle-boundary evidence."""

    def __init__(self):
        self._lock = threading.RLock()
        self.lifecycle_thread = None
        self.boundary_reached = threading.Event()
        self.entries = []

    def record(self, label):
        self.entries.append(label)
        self.boundary_reached.set()

    def __enter__(self):
        if threading.current_thread() is self.lifecycle_thread:
            self.record("lock_attempt")
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self._lock.release()


class LifecycleFakeComm(FakeComm):
    """Fake transport that records unlocked lifecycle-body entry."""

    def __init__(self, *args, lifecycle_probe=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.lifecycle_probe = lifecycle_probe
        self.IsConnected = True

    def Connect(self):
        self.IsConnected = True
        return True, None

    def Disconnect(self):
        if self.lifecycle_probe is not None:
            self.lifecycle_probe.record("disconnect_body")
        self.IsConnected = False


class EpochBarrierLink(ElmoLink):
    """Pause one command after it reads the authorized connection epoch."""

    @property
    def _connection_epoch(self):
        value = getattr(self, "_connection_epoch_value", None)
        if (getattr(self, "_epoch_gate_armed", False)
                and threading.current_thread()
                is getattr(self, "_epoch_gate_thread", None)):
            self._epoch_gate_armed = False
            self._epoch_checked.set()
            if not self._epoch_release.wait(2.0):
                raise RuntimeError("test epoch gate release timed out")
        return value

    @_connection_epoch.setter
    def _connection_epoch(self, value):
        self._connection_epoch_value = value


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


def _new_epoch_barrier_link(*, values):
    probe = LifecycleProbeRLock()
    link = EpochBarrierLink("COM_TEST")
    link._persistence_command_lock = probe
    link._epoch_checked = threading.Event()
    link._epoch_release = threading.Event()
    link._epoch_gate_armed = False
    comm = LifecycleFakeComm(
        values=values, lifecycle_probe=probe)
    link._comm = comm
    link._connection_epoch = str(uuid.uuid4())
    identity = link.transaction_identity()
    assert identity and identity.startswith("elmo-sn4-sha256:")
    for query in ("VR", "VP", "VB"):
        link.command(query)
    return link, comm, probe


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


def test_p2_journal_durably_prepares_before_authorized_sv(
        isolated_state_paths):
    observed = {}

    def observe_pre_sv():
        snapshot = persistence_audit.PersistenceLedger(
            isolated_state_paths).load()
        assert len(snapshot.active) == 1
        record = next(iter(snapshot.active.values()))
        assert record.state == "PERSISTING"
        observed["record_id"] = record.record_id

    link, comm = _new_link(values=APPLIED_P2, on_sv=observe_pre_sv)
    record_id = link.prepare_persistence_attempt(
        phase="P2", registers=persistence_audit.PHASE_REGISTERS["P2"],
        original=ORIGINAL_P2, applied=APPLIED_P2)
    link.command("SV", _persistence_attempt_id=record_id)
    link.complete_persistence_attempt(record_id)

    assert observed["record_id"]
    assert comm.commands.count("SV") == 1
    snapshot = persistence_audit.PersistenceLedger(
        isolated_state_paths).load()
    assert not snapshot.active
    assert snapshot.resolved[observed["record_id"]].resolution == \
        "SV_ACKNOWLEDGED"


def test_p1_record_id_cannot_authorize_sv_without_on_motor_verification(
        isolated_state_paths):
    link, comm = _new_link(values=APPLIED_P1)
    record_id = link.prepare_persistence_attempt(
        phase="P1", registers=current.P1_GAIN_NAMES,
        original=ORIGINAL_P1, applied=APPLIED_P1)
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="on-motor verification"):
        link.command("SV", _persistence_attempt_id=record_id)

    assert comm.commands == []
    _assert_record_active(isolated_state_paths, record_id)


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


def test_p1_config_record_is_a_scoped_same_session_ram_capability(
        isolated_state_paths):
    link, comm = _new_link(values=P1_CONFIG_ORIGINAL)
    record_id = link.prepare_persistence_attempt(
        phase="P1_CONFIG",
        registers=tuple(P1_CONFIG_ORIGINAL),
        original=P1_CONFIG_ORIGINAL,
        applied=P1_CONFIG_APPLIED,
        initial_state="RAM_APPLYING",
        mutation_bounds=P1_CONFIG_MUTATION_BOUNDS,
    )
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command("UM=3")
    assert comm.commands == []

    link.command("UM=3", _persistence_attempt_id=record_id)
    link.command("KP[1]=0.08", _persistence_attempt_id=record_id)
    link.command("KI[1]=800", _persistence_attempt_id=record_id)
    link.command("SE[2]=1", _persistence_attempt_id=record_id)
    link.command("SE[3]=400", _persistence_attempt_id=record_id)
    link.command(
        "MO=1", allow_motion=True,
        _persistence_attempt_id=record_id)
    link.command(
        "TC=0.25", allow_motion=True,
        _persistence_attempt_id=record_id)
    with pytest.raises(PermissionError, match="allow_motion=True"):
        link.command("TW[80]=1", _persistence_attempt_id=record_id)
    link.command(
        "TW[80]=1", allow_motion=True,
        _persistence_attempt_id=record_id)
    link.command("TW[80]=0", _persistence_attempt_id=record_id)

    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command(
            "JV=10", allow_motion=True,
            _persistence_attempt_id=record_id)

    link.command("TC=0", allow_motion=True)
    link.command("MO=0")
    link.begin_persistence_ram_rollback(record_id)
    for register, value in P1_CONFIG_ORIGINAL.items():
        link.command(
            "%s=%s" % (register, value),
            _persistence_attempt_id=record_id)
    link.resolve_persistence_ram_rollback(record_id)

    assert link.persistence_status()["status"] == "CLEAR"
    snapshot = persistence_audit.PersistenceLedger(
        isolated_state_paths).load()
    assert not snapshot.active
    assert snapshot.resolved[record_id].resolution == \
        "RAM_ROLLBACK_VERIFIED"


def test_p1_config_closeout_cannot_clear_unrestored_original_profile(
        isolated_state_paths):
    link, comm = _new_link(values=P1_CONFIG_ORIGINAL)
    record_id = link.prepare_persistence_attempt(
        phase="P1_CONFIG",
        registers=tuple(P1_CONFIG_ORIGINAL),
        original=P1_CONFIG_ORIGINAL,
        applied=P1_CONFIG_APPLIED,
        initial_state="RAM_APPLYING",
        mutation_bounds=P1_CONFIG_MUTATION_BOUNDS,
    )
    link.command("UM=3", _persistence_attempt_id=record_id)
    comm.commands.clear()
    link.begin_persistence_ram_rollback(record_id)

    with pytest.raises(RuntimeError, match="original-profile readback"):
        link.resolve_persistence_ram_rollback(record_id)

    assert comm.values["UM"] == 3.0
    assert link.persistence_status()["status"] == "PERSISTENCE_UNKNOWN"
    _assert_record_active(isolated_state_paths, record_id)


@pytest.mark.parametrize("command,allow_motion", [
    ("KP[1]=-123", False),
    ("KI[1]=999999", False),
    ("SE[2]=-1", False),
    ("SE[3]=-200", False),
    ("TC=999999", True),
])
def test_p1_config_capability_rejects_values_outside_prepared_bounds(
        isolated_state_paths, command, allow_motion):
    link, comm = _new_link(values=P1_CONFIG_ORIGINAL)
    record_id = link.prepare_persistence_attempt(
        phase="P1_CONFIG",
        registers=tuple(P1_CONFIG_ORIGINAL),
        original=P1_CONFIG_ORIGINAL,
        applied=P1_CONFIG_APPLIED,
        initial_state="RAM_APPLYING",
        mutation_bounds=P1_CONFIG_MUTATION_BOUNDS,
    )
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command(
            command, allow_motion=allow_motion,
            _persistence_attempt_id=record_id)

    assert comm.commands == []


def test_p1_config_original_outside_bounds_requires_rollback_transition(
        isolated_state_paths):
    link, comm = _new_link(values=P1_CONFIG_ORIGINAL)
    record_id = link.prepare_persistence_attempt(
        phase="P1_CONFIG",
        registers=tuple(P1_CONFIG_ORIGINAL),
        original=P1_CONFIG_ORIGINAL,
        applied=P1_CONFIG_APPLIED,
        initial_state="RAM_APPLYING",
        mutation_bounds=P1_CONFIG_MUTATION_BOUNDS,
    )
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command(
            "SE[3]=0",
            _persistence_attempt_id=record_id,
        )
    assert comm.commands == []

    link.begin_persistence_ram_rollback(record_id)
    comm.commands.clear()
    link.command("SE[3]=0", _persistence_attempt_id=record_id)

    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command(
            "SE[3]=200",
            _persistence_attempt_id=record_id,
        )
    assert comm.commands == ["SE[3]=0"]


def test_p1_config_rollback_closeout_rejects_one_ulp_profile_drift(
        isolated_state_paths):
    link, comm = _new_link(values=P1_CONFIG_ORIGINAL)
    record_id = link.prepare_persistence_attempt(
        phase="P1_CONFIG",
        registers=tuple(P1_CONFIG_ORIGINAL),
        original=P1_CONFIG_ORIGINAL,
        applied=P1_CONFIG_APPLIED,
        initial_state="RAM_APPLYING",
        mutation_bounds=P1_CONFIG_MUTATION_BOUNDS,
    )
    link.begin_persistence_ram_rollback(record_id)
    comm.values.update(P1_CONFIG_ORIGINAL)
    comm.values["KI[1]"] = math.nextafter(
        float(P1_CONFIG_ORIGINAL["KI[1]"]), math.inf)

    with pytest.raises(RuntimeError, match="original-profile readback"):
        link.resolve_persistence_ram_rollback(record_id)

    assert link.persistence_status()["status"] == "PERSISTENCE_UNKNOWN"
    _assert_record_active(isolated_state_paths, record_id)


@pytest.mark.parametrize("register,readback", [
    ("KI[1]", "812.9000000000000001"),
    ("UM", "5.0000000000000001"),
])
def test_p1_config_rollback_closeout_rejects_sub_ulp_decimal_drift(
        isolated_state_paths, register, readback):
    link, comm = _new_link(values=P1_CONFIG_ORIGINAL)
    record_id = link.prepare_persistence_attempt(
        phase="P1_CONFIG",
        registers=tuple(P1_CONFIG_ORIGINAL),
        original=P1_CONFIG_ORIGINAL,
        applied=P1_CONFIG_APPLIED,
        initial_state="RAM_APPLYING",
        mutation_bounds=P1_CONFIG_MUTATION_BOUNDS,
    )
    link.begin_persistence_ram_rollback(record_id)
    comm.values[register] = readback

    with pytest.raises(RuntimeError, match="original-profile readback"):
        link.resolve_persistence_ram_rollback(record_id)

    assert link.persistence_status()["status"] == "PERSISTENCE_UNKNOWN"
    _assert_record_active(isolated_state_paths, record_id)


def test_ram_rollback_rejects_sub_ulp_nonzero_stationary_readback(
        isolated_state_paths):
    link, comm = _new_link(values=P1_CONFIG_ORIGINAL)
    record_id = link.prepare_persistence_attempt(
        phase="P1_CONFIG",
        registers=tuple(P1_CONFIG_ORIGINAL),
        original=P1_CONFIG_ORIGINAL,
        applied=P1_CONFIG_APPLIED,
        initial_state="RAM_APPLYING",
        mutation_bounds=P1_CONFIG_MUTATION_BOUNDS,
    )
    comm.values["VX"] = "0.0000000000000001"
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="disabled stationary"):
        link.begin_persistence_ram_rollback(record_id)

    assert comm.commands == ["MO", "SO", "VX"]
    _assert_record_active(isolated_state_paths, record_id)


@pytest.mark.parametrize("command", [
    "UM=3.00000001",
    "UM=3.0000000000000001",
    "CA[44]=8.00000005",
])
def test_p1_config_discrete_profile_values_require_exact_equality(
        isolated_state_paths, command):
    link, comm = _new_link(values=P1_CONFIG_ORIGINAL)
    record_id = link.prepare_persistence_attempt(
        phase="P1_CONFIG",
        registers=tuple(P1_CONFIG_ORIGINAL),
        original=P1_CONFIG_ORIGINAL,
        applied=P1_CONFIG_APPLIED,
        initial_state="RAM_APPLYING",
        mutation_bounds=P1_CONFIG_MUTATION_BOUNDS,
    )
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command(command, _persistence_attempt_id=record_id)

    assert comm.commands == []


def test_p1_config_prepare_requires_explicit_mutation_bounds(
        isolated_state_paths):
    link, comm = _new_link(values=P1_CONFIG_ORIGINAL)
    comm.commands.clear()

    with pytest.raises(ValueError, match="mutation bounds"):
        link.prepare_persistence_attempt(
            phase="P1_CONFIG",
            registers=tuple(P1_CONFIG_ORIGINAL),
            original=P1_CONFIG_ORIGINAL,
            applied=P1_CONFIG_APPLIED,
            initial_state="RAM_APPLYING",
        )

    assert comm.commands == []
    assert link.persistence_status()["status"] == "CLEAR"


def test_p1_config_prepare_rejects_applied_profile_outside_frozen_bounds(
        isolated_state_paths):
    link, comm = _new_link(values=P1_CONFIG_ORIGINAL)
    applied = dict(P1_CONFIG_APPLIED)
    applied["KP[1]"] = 50.0
    bounds = dict(P1_CONFIG_MUTATION_BOUNDS)
    bounds["KP[1]"] = (0.05, 0.2)
    comm.commands.clear()

    with pytest.raises(ValueError, match="applied KP.*outside"):
        link.prepare_persistence_attempt(
            phase="P1_CONFIG",
            registers=tuple(P1_CONFIG_ORIGINAL),
            original=P1_CONFIG_ORIGINAL,
            applied=applied,
            initial_state="RAM_APPLYING",
            mutation_bounds=bounds,
        )

    assert comm.commands == []
    assert link.persistence_status()["status"] == "CLEAR"
    assert not isolated_state_paths.exists()


def _prepare_p2_limits(link):
    return link.prepare_persistence_attempt(
        phase="P2_LIMITS",
        registers=tuple(P2_LIMITS_ORIGINAL),
        original=P2_LIMITS_ORIGINAL,
        applied=P2_LIMITS_APPLIED,
        initial_state="RAM_APPLYING",
        mutation_bounds=P2_LIMITS_MUTATION_BOUNDS,
    )


def _write_p2_limits_profile(link, record_id, profile):
    for register in P2_LIMITS_ORIGINAL:
        link.command(
            "%s=%s" % (register, profile[register]),
            _persistence_attempt_id=record_id)


def test_p2_limits_capability_requires_two_sweep_applied_proof_before_motion(
        isolated_state_paths):
    link, comm = _new_link(values=P2_LIMITS_ORIGINAL)
    record_id = _prepare_p2_limits(link)
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command(
            "MO=1", allow_motion=True,
            _persistence_attempt_id=record_id)
    assert comm.commands == []

    _write_p2_limits_profile(link, record_id, P2_LIMITS_APPLIED)
    comm.commands.clear()
    verified = link.verify_persistence_ram_applied(record_id)

    assert verified["forward"] == P2_LIMITS_APPLIED
    assert verified["reverse"] == P2_LIMITS_APPLIED
    assert comm.commands == (
        list(P2_LIMITS_ORIGINAL)
        + list(reversed(tuple(P2_LIMITS_ORIGINAL))))

    link.command(
        "MO=1", allow_motion=True,
        _persistence_attempt_id=record_id)
    link.command(
        "TC=0.25", allow_motion=True,
        _persistence_attempt_id=record_id)
    link.command(
        "JV=100", allow_motion=True,
        _persistence_attempt_id=record_id)
    link.command(
        "BG", allow_motion=True,
        _persistence_attempt_id=record_id)
    link.command("UM=3", _persistence_attempt_id=record_id)
    link.command(
        "PA=512", allow_motion=True,
        _persistence_attempt_id=record_id)


def test_p2_limits_applied_proof_freezes_limit_writes_until_safe_rollback(
        isolated_state_paths):
    link, comm = _new_link(values=P2_LIMITS_ORIGINAL)
    record_id = link.prepare_persistence_attempt(
        phase="P2_LIMITS",
        registers=tuple(P2_LIMITS_ORIGINAL),
        original=P2_LIMITS_ORIGINAL,
        applied=P2_LIMITS_ORIGINAL,
        initial_state="RAM_APPLYING",
        mutation_bounds=P2_LIMITS_MUTATION_BOUNDS,
    )

    link.verify_persistence_ram_applied(record_id)
    link.command(
        "MO=1", allow_motion=True,
        _persistence_attempt_id=record_id)
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command(
            "SD=%s" % int(P2_LIMITS_ORIGINAL["SD"]),
            _persistence_attempt_id=record_id)
    assert comm.commands == []

    with pytest.raises(RuntimeError, match="disabled|stationary"):
        link.begin_persistence_ram_rollback(record_id)
    assert comm.commands == ["MO"]


@pytest.mark.parametrize("command,allow_motion", [
    ("SD=3999999", False),
    ("SD=4000000.0000000001", False),
    ("TC=8.01", True),
    ("JV=1310721", True),
    ("PA=2147483648", True),
    ("PA=1.5", True),
    ("UM=4", False),
    ("KP[2]=0.1", False),
    ("SV", False),
])
def test_p2_limits_capability_blocks_unprepared_values_before_vendor_io(
        isolated_state_paths, command, allow_motion):
    link, comm = _new_link(values=P2_LIMITS_ORIGINAL)
    record_id = _prepare_p2_limits(link)
    _write_p2_limits_profile(link, record_id, P2_LIMITS_APPLIED)
    link.verify_persistence_ram_applied(record_id)
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command(
            command, allow_motion=allow_motion,
            _persistence_attempt_id=record_id)

    assert comm.commands == []


def test_p2_limits_applied_proof_rejects_sub_ulp_fractional_readback(
        isolated_state_paths):
    link, comm = _new_link(values=P2_LIMITS_ORIGINAL)
    record_id = _prepare_p2_limits(link)
    _write_p2_limits_profile(link, record_id, P2_LIMITS_APPLIED)
    comm.values["SD"] = "4000000.0000000001"
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="applied-profile.*mismatch"):
        link.verify_persistence_ram_applied(record_id)

    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command(
            "MO=1", allow_motion=True,
            _persistence_attempt_id=record_id)
    _assert_record_active(isolated_state_paths, record_id)


def test_p2_limits_forward_rejects_sub_ulp_fractional_profile_literal(
        isolated_state_paths):
    link, comm = _new_link(values=P2_LIMITS_ORIGINAL)
    record_id = _prepare_p2_limits(link)
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command(
            "SD=4000000.0000000001",
            _persistence_attempt_id=record_id,
        )

    assert comm.commands == []


def test_p2_limits_post_reset_audit_rejects_sub_ulp_fractional_profile(
        isolated_state_paths):
    source, _ = _new_link(values=P2_LIMITS_ORIGINAL)
    record_id = _prepare_p2_limits(source)
    source.mark_persistence_attempt_unknown(
        record_id, "LIMIT_RESTORE_OR_CLOSEOUT_UNVERIFIED")
    fractional = dict(P2_LIMITS_ORIGINAL)
    fractional["SD"] = "2000000.0000000001"
    reset, _ = _new_link(values=fractional)

    result = reset.audit_persistence_after_reset(
        operator_reset_attested=True)

    assert result["resolved"] is False
    assert result["status"] == "READBACK_INVALID"
    assert result["lock_active"] is True
    _assert_record_active(isolated_state_paths, record_id)


def test_p2_limits_applied_proof_catches_cross_register_read_side_effect(
        isolated_state_paths):
    link, comm = _new_link(values=P2_LIMITS_ORIGINAL)
    record_id = _prepare_p2_limits(link)
    _write_p2_limits_profile(link, record_id, P2_LIMITS_APPLIED)
    original_send = comm.SendCommandAnalyzeError

    def mutate_earlier_after_later_query(command, response, error, timeout):
        result = original_send(command, response, error, timeout)
        core = "".join(str(command).split()).rstrip(";")
        if core == "HL[2]":
            comm.values["SD"] = P2_LIMITS_APPLIED["SD"] - 1.0
        return result

    comm.SendCommandAnalyzeError = mutate_earlier_after_later_query
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="applied-profile.*mismatch"):
        link.verify_persistence_ram_applied(record_id)

    assert comm.commands == (
        list(P2_LIMITS_ORIGINAL)
        + list(reversed(tuple(P2_LIMITS_ORIGINAL))))
    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        link.command(
            "MO=1", allow_motion=True,
            _persistence_attempt_id=record_id)
    _assert_record_active(isolated_state_paths, record_id)


def test_p2_limits_closeout_requires_forward_and_reverse_exact_original(
        isolated_state_paths):
    link, comm = _new_link(values=P2_LIMITS_ORIGINAL)
    record_id = _prepare_p2_limits(link)
    _write_p2_limits_profile(link, record_id, P2_LIMITS_APPLIED)
    link.verify_persistence_ram_applied(record_id)
    link.begin_persistence_ram_rollback(record_id)
    _write_p2_limits_profile(link, record_id, P2_LIMITS_ORIGINAL)
    comm.commands.clear()

    verified = link.resolve_persistence_ram_rollback(record_id)

    assert verified["forward"] == P2_LIMITS_ORIGINAL
    assert verified["reverse"] == P2_LIMITS_ORIGINAL
    assert comm.commands == (
        list(P2_LIMITS_ORIGINAL)
        + list(reversed(tuple(P2_LIMITS_ORIGINAL))))
    assert link.persistence_status()["status"] == "CLEAR"
    archived = persistence_audit.PersistenceLedger(
        isolated_state_paths).load().resolved[record_id]
    assert archived.resolution == "RAM_ROLLBACK_VERIFIED"


def test_p2_limits_closeout_cross_register_side_effect_stays_durable_unknown(
        isolated_state_paths):
    link, comm = _new_link(values=P2_LIMITS_ORIGINAL)
    record_id = _prepare_p2_limits(link)
    link.begin_persistence_ram_rollback(record_id)
    original_send = comm.SendCommandAnalyzeError

    def mutate_earlier_after_later_query(command, response, error, timeout):
        result = original_send(command, response, error, timeout)
        core = "".join(str(command).split()).rstrip(";")
        if core == "HL[2]":
            comm.values["SD"] = P2_LIMITS_ORIGINAL["SD"] - 1.0
        return result

    comm.SendCommandAnalyzeError = mutate_earlier_after_later_query
    comm.commands.clear()

    with pytest.raises(RuntimeError, match="original-profile.*mismatch"):
        link.resolve_persistence_ram_rollback(record_id)

    assert comm.commands == (
        list(P2_LIMITS_ORIGINAL)
        + list(reversed(tuple(P2_LIMITS_ORIGINAL))))
    _assert_record_active(isolated_state_paths, record_id)


def test_p2_limits_same_record_token_is_stale_after_reconnect(
        isolated_state_paths):
    source, _ = _new_link(values=P2_LIMITS_ORIGINAL)
    record_id = _prepare_p2_limits(source)
    reconnected, comm = _new_link(values=P2_LIMITS_ORIGINAL)
    comm.commands.clear()

    status = reconnected.persistence_status()
    assert status["lock_active"] is True
    assert status["record_id"] == record_id
    assert status["phase"] == "P2_LIMITS"
    with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
        reconnected.command(
            "SD=4000000", _persistence_attempt_id=record_id)
    assert comm.commands == []


@pytest.mark.parametrize("phase,command,allow_motion", [
    ("P1_CONFIG", "KP[1]=0.1", False),
    ("P2_LIMITS", "MO=1", True),
])
@pytest.mark.parametrize("lifecycle", ["connect", "disconnect"])
def test_persistence_capability_command_is_atomic_with_transport_lifecycle(
        isolated_state_paths, phase, command, allow_motion, lifecycle):
    values = (P1_CONFIG_ORIGINAL if phase == "P1_CONFIG"
              else P2_LIMITS_ORIGINAL)
    link, old_comm, probe = _new_epoch_barrier_link(values=values)
    if phase == "P1_CONFIG":
        record_id = link.prepare_persistence_attempt(
            phase="P1_CONFIG",
            registers=tuple(P1_CONFIG_ORIGINAL),
            original=P1_CONFIG_ORIGINAL,
            applied=P1_CONFIG_APPLIED,
            initial_state="RAM_APPLYING",
            mutation_bounds=P1_CONFIG_MUTATION_BOUNDS,
        )
    else:
        record_id = _prepare_p2_limits(link)
        _write_p2_limits_profile(link, record_id, P2_LIMITS_APPLIED)
        link.verify_persistence_ram_applied(record_id)
    old_comm.commands.clear()

    command_result = {}

    def issue_capability_command():
        link._epoch_gate_thread = threading.current_thread()
        try:
            command_result["response"] = link.command(
                command, allow_motion=allow_motion,
                _persistence_attempt_id=record_id)
        except Exception as exc:
            command_result["error"] = exc

    link._epoch_gate_armed = True
    command_thread = threading.Thread(target=issue_capability_command)
    command_thread.start()
    assert link._epoch_checked.wait(2.0), "command did not reach epoch gate"

    new_comm = LifecycleFakeComm(values=values)
    if lifecycle == "connect":
        factory = SimpleNamespace(
            CreateUSBCommunicationInfo=lambda port: port,
            CreateCommunication=lambda _info: new_comm,
        )

        def fake_namespace():
            probe.record("connect_body")
            return SimpleNamespace(
                DriveCommunicationFactory=lambda: factory)

        link._ns = fake_namespace
        lifecycle_fn = link.connect
    else:
        lifecycle_fn = link.disconnect

    lifecycle_result = {}

    def run_lifecycle():
        try:
            lifecycle_result["response"] = lifecycle_fn()
        except Exception as exc:
            lifecycle_result["error"] = exc

    lifecycle_thread = threading.Thread(target=run_lifecycle)
    probe.lifecycle_thread = lifecycle_thread
    lifecycle_thread.start()
    assert probe.boundary_reached.wait(2.0), \
        "lifecycle did not reach either lock or unlocked body"
    link._epoch_release.set()
    command_thread.join(2.0)
    lifecycle_thread.join(2.0)

    assert not command_thread.is_alive()
    assert not lifecycle_thread.is_alive()
    assert probe.entries[0] == "lock_attempt"
    assert command_result.get("error") is None
    assert old_comm.commands == [command]
    assert new_comm.commands == []

    if lifecycle == "connect":
        assert isinstance(lifecycle_result.get("error"), RuntimeError)
        assert "fully disconnected" in str(lifecycle_result["error"])
        assert probe.entries == ["lock_attempt"]
        assert link._comm is old_comm
    else:
        assert lifecycle_result.get("error") is None
        with pytest.raises(RuntimeError, match="persistence state UNKNOWN"):
            link.command(
                command, allow_motion=allow_motion,
                _persistence_attempt_id=record_id)
    assert new_comm.commands == []


@pytest.mark.parametrize("mode", ["false", "raise"])
def test_failed_connect_discards_provisional_transport_and_session_authority(
        isolated_state_paths, mode):
    probe = LifecycleProbeRLock()

    class FailedConnectComm(LifecycleFakeComm):
        def Connect(self):
            self.IsConnected = True
            if mode == "raise":
                raise IOError("synthetic lost Connect reply")
            return False, "synthetic Connect false"

    comm = FailedConnectComm(lifecycle_probe=probe)
    factory = SimpleNamespace(
        CreateUSBCommunicationInfo=lambda port: port,
        CreateCommunication=lambda _info: comm,
    )
    link = ElmoLink("COM_TEST")
    link._ns = lambda: SimpleNamespace(
        DriveCommunicationFactory=lambda: factory)
    old_session = link._transaction_session_token
    link._prepared_persistence_attempt_id = "stale-attempt"
    link._prepared_p1_config_bounds = ("stale-attempt", {})
    link._prepared_p2_limits_bounds = ("stale-attempt", old_session, {})
    link._verified_p2_limits_applied_id = "stale-attempt"
    link._connected_drive_identity = "stale-identity"
    link._connection_epoch = "stale-epoch"

    expected = ConnectionError if mode == "false" else IOError
    with pytest.raises(expected):
        link.connect()

    assert probe.entries == ["disconnect_body"]
    assert comm.IsConnected is False
    assert link._comm is None
    assert link._factory is None
    assert link._prepared_persistence_attempt_id is None
    assert link._prepared_p1_config_bounds is None
    assert link._prepared_p2_limits_bounds is None
    assert link._verified_p2_limits_applied_id is None
    assert link._connected_drive_identity is None
    assert link._connection_epoch is None
    assert link._transaction_session_token is not old_session


def test_p2_limits_post_reset_audit_clears_only_exact_original_profile(
        isolated_state_paths):
    source, _ = _new_link(values=P2_LIMITS_ORIGINAL)
    record_id = _prepare_p2_limits(source)
    source.mark_persistence_attempt_unknown(
        record_id, "LIMIT_RESTORE_OR_CLOSEOUT_UNVERIFIED")

    temporary, _ = _new_link(values=P2_LIMITS_APPLIED)
    temporary_result = temporary.audit_persistence_after_reset(
        operator_reset_attested=True)

    assert temporary_result["resolved"] is False
    assert temporary_result["status"] == \
        "TEMPORARY_CONFIGURATION_AFTER_RESET"
    _assert_record_active(isolated_state_paths, record_id)

    reset, _ = _new_link(values=P2_LIMITS_ORIGINAL)
    original_result = reset.audit_persistence_after_reset(
        operator_reset_attested=True)

    assert original_result["resolved"] is True
    assert original_result["resolution"] == \
        "ORIGINAL_PROFILE_AFTER_RESET"
    assert original_result["lock_active"] is False


def test_p2_limits_no_change_incident_reset_audit_requires_exact_original(
        isolated_state_paths):
    source, _ = _new_link(values=P2_LIMITS_ORIGINAL)
    record_id = source.prepare_persistence_attempt(
        phase="P2_LIMITS",
        registers=tuple(P2_LIMITS_ORIGINAL),
        original=P2_LIMITS_ORIGINAL,
        applied=P2_LIMITS_ORIGINAL,
        initial_state="RAM_APPLYING",
        mutation_bounds=P2_LIMITS_MUTATION_BOUNDS,
    )
    source.mark_persistence_attempt_unknown(
        record_id, "NO_CHANGE_PROOF_INTERRUPTED")

    drifted_profile = dict(P2_LIMITS_ORIGINAL)
    drifted_profile["SD"] += 1.0
    drifted, _ = _new_link(values=drifted_profile)
    drifted_result = drifted.audit_persistence_after_reset(
        operator_reset_attested=True)
    assert drifted_result["resolved"] is False
    assert drifted_result["status"] == "CONFIG_DRIFT_UNKNOWN"
    _assert_record_active(isolated_state_paths, record_id)

    exact, _ = _new_link(values=P2_LIMITS_ORIGINAL)
    exact_result = exact.audit_persistence_after_reset(
        operator_reset_attested=True)
    assert exact_result["resolved"] is True
    assert exact_result["resolution"] == "ORIGINAL_PROFILE_AFTER_RESET"
    assert exact_result["lock_active"] is False


def test_p1_config_post_reset_near_original_drift_keeps_durable_lock(
        isolated_state_paths):
    source, _ = _new_link(values=P1_CONFIG_ORIGINAL)
    record_id = source.prepare_persistence_attempt(
        phase="P1_CONFIG",
        registers=tuple(P1_CONFIG_ORIGINAL),
        original=P1_CONFIG_ORIGINAL,
        applied=P1_CONFIG_APPLIED,
        initial_state="RAM_APPLYING",
        mutation_bounds=P1_CONFIG_MUTATION_BOUNDS,
    )
    source.mark_persistence_attempt_unknown(
        record_id, "CONFIGURATION_RESTORE_UNVERIFIED")
    near_original = dict(P1_CONFIG_ORIGINAL)
    near_original["KI[1]"] = float(P1_CONFIG_ORIGINAL["KI[1]"]) * 1.0005
    reset, _ = _new_link(values=near_original)

    result = reset.audit_persistence_after_reset(
        operator_reset_attested=True)

    assert result["resolved"] is False
    assert result["status"] == "CONFIG_DRIFT_UNKNOWN"
    assert result["lock_active"] is True
    _assert_record_active(isolated_state_paths, record_id)


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


def test_closeout_failure_after_successful_sv_keeps_active_lock(
        isolated_state_paths, monkeypatch):
    link, comm = _new_link(values=APPLIED_P2)
    record_id = link.prepare_persistence_attempt(
        phase="P2", registers=persistence_audit.PHASE_REGISTERS["P2"],
        original=ORIGINAL_P2, applied=APPLIED_P2)

    def fail_closeout(_record_id):
        raise persistence_audit.LedgerWriteError(
            "negative-control close-out failure")

    monkeypatch.setattr(
        link._persistence_ledger, "resolve_sv_success", fail_closeout)

    link.command("SV", _persistence_attempt_id=record_id)
    with pytest.raises(
            persistence_audit.LedgerWriteError,
            match="negative-control close-out failure"):
        link.complete_persistence_attempt(record_id)

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
