"""Offline RED regressions for drive-energy ownership and shutdown cleanup.

No test in this module opens a COM port or shows a real window.  Worker/link
dependencies are deterministic process-local fakes; the one Qt close-event
test constructs an offscreen widget without starting a ``DriveWorker``.
"""

from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

import elmo_link
import main as app_main


class _SafetyLink:
    """Query-capable fake whose command log proves final torque removal."""

    def __init__(self, *, mo: int = 0):
        self.mo = int(mo)
        self.command_log: list[tuple[str, int]] = []
        self.disconnect_called = False

    def connect(self):
        return True

    def command(self, command, **_kwargs):
        text = str(command)
        self.command_log.append((text, self.mo))
        if text == "VR":
            return "FakeFW"
        if text == "VP":
            return "90"
        if text == "VB":
            return "FakeBoot"
        if text == "ST":
            return ""
        if text == "MO=0":
            self.mo = 0
            return ""
        if text == "MO":
            return str(self.mo)
        if text == "SO":
            return str(self.mo)
        if text == "MS":
            return "3"
        if text in {"ID", "IQ", "VX"}:
            return "0"
        return "0"

    @staticmethod
    def transaction_identity():
        return "elmo-sn4-sha256:" + ("e" * 64)

    @staticmethod
    def persistence_status():
        return {
            "status": "CLEAR",
            "resolved": True,
            "detail": "fake",
            "lock_active": False,
            "record_id": None,
            "phase": None,
            "other_active_count": 0,
            "ledger_error": None,
        }

    @staticmethod
    def recorder_recovery_unknown_latched():
        return False

    @staticmethod
    def read_motor_params():
        return {}

    @staticmethod
    def read_feedback():
        return {}

    @staticmethod
    def read_tuning_gains():
        return {}

    def read_telemetry(self):
        now = time.monotonic()
        return {
            "pos": 0,
            "vel": 0.0,
            "pos_err": 0,
            "iq": 0.0,
            "mo": self.mo,
            "_sample_started_monotonic": now,
            "_sample_finished_monotonic": now,
            "_sample_duration_s": 0.0,
        }

    def disconnect(self):
        self.disconnect_called = True


def _assert_stop_disable_was_verified(link: _SafetyLink):
    commands = [command for command, _mo_before in link.command_log]
    assert "ST" in commands, "shutdown did not issue software Stop"
    assert "MO=0" in commands, "shutdown did not remove torque"
    assert commands.index("ST") < commands.index("MO=0")
    disable_index = commands.index("MO=0")
    post_disable = link.command_log[disable_index + 1 :]
    assert any(
        command == "MO" and mo_before == 0
        for command, mo_before in post_disable
    ), "shutdown did not read MO back after the disable command"
    assert any(
        command == "SO" and mo_before == 0
        for command, mo_before in post_disable
    ), "shutdown did not read SO back after the disable command"
    assert link.mo == 0


@pytest.mark.parametrize("workflow", ("autotune", "velpos", "verify"))
def test_energized_workflow_exception_uses_common_verified_safe_stop(
        monkeypatch, workflow):
    """An unexpected wrapper exception must not strand an energized drive."""
    link = _SafetyLink(mo=0)
    worker = app_main.DriveWorker("COM_FAKE")
    algorithm_calls: list[str] = []

    def explode_after_enable(fake_link, _params):
        algorithm_calls.append(workflow)
        fake_link.mo = 1
        # Reproduce an operator shutdown racing the unexpected algorithm error.
        worker.stop()
        raise RuntimeError("negative-control energized workflow crash")

    if workflow == "autotune":
        monkeypatch.setattr(
            app_main.autotune_current, "run_current_autotune",
            explode_after_enable)
        worker.start_autotune({})
    elif workflow == "velpos":
        monkeypatch.setattr(
            app_main.autotune_velpos, "run_velpos_autotune",
            explode_after_enable)
        worker._commutation_signature_green = True
        worker.start_velpos_autotune({
            "r_pp_ohm": 0.139,
            "l_pp_h": 41.6e-6,
        })
    else:
        monkeypatch.setattr(
            app_main.autotune_velpos, "verify_run_vp",
            explode_after_enable)
        worker._commutation_signature_green = True
        worker._commutation_signature_token = "offline-signature"
        worker.start_verify_vp(
            {}, signature_token="offline-signature")

    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)
    worker.run()

    assert algorithm_calls == [workflow]
    _assert_stop_disable_was_verified(link)
    assert link.disconnect_called


@pytest.mark.parametrize("workflow", ("autotune", "velpos", "verify"))
def test_tuning_cancel_during_fresh_telemetry_never_enters_algorithm(
        monkeypatch, workflow):
    """Cancellation racing the admission read must remain authoritative."""
    telemetry_entered = threading.Event()
    telemetry_release = threading.Event()
    result_emitted = threading.Event()
    algorithm_calls: list[str] = []
    results = []

    class _BlockingFreshTelemetryLink(_SafetyLink):
        def __init__(self):
            super().__init__(mo=0)
            self.telemetry_calls = 0

        def read_telemetry(self):
            self.telemetry_calls += 1
            if self.telemetry_calls == 2:
                telemetry_entered.set()
                assert telemetry_release.wait(2.0), (
                    "test did not release the pre-mutation telemetry read")
            return super().read_telemetry()

    link = _BlockingFreshTelemetryLink()
    worker = app_main.DriveWorker("COM_FAKE")

    def unexpected_algorithm_entry(_link, _params):
        algorithm_calls.append(workflow)
        if workflow == "autotune":
            return app_main.autotune_current.AutotuneResult(
                status=app_main.autotune_current.RED,
                reason="algorithm must not run")
        return app_main.autotune_velpos.AutotuneVPResult(
            status=app_main.autotune_velpos.RED,
            reason="algorithm must not run")

    if workflow == "autotune":
        monkeypatch.setattr(
            app_main.autotune_current, "run_current_autotune",
            unexpected_algorithm_entry)
        worker.autotune_result.connect(
            lambda result: (results.append(result), result_emitted.set()),
            QtCore.Qt.ConnectionType.DirectConnection)
        worker.start_autotune({})
        cancel = worker.cancel_autotune
    elif workflow == "velpos":
        monkeypatch.setattr(
            app_main.autotune_velpos, "run_velpos_autotune",
            unexpected_algorithm_entry)
        worker.velpos_result.connect(
            lambda result: (results.append(result), result_emitted.set()),
            QtCore.Qt.ConnectionType.DirectConnection)
        worker._commutation_signature_green = True
        worker.start_velpos_autotune({
            "r_pp_ohm": 0.139,
            "l_pp_h": 41.6e-6,
        })
        cancel = worker.cancel_velpos
    else:
        monkeypatch.setattr(
            app_main.autotune_velpos, "verify_run_vp",
            unexpected_algorithm_entry)
        worker.verify_result.connect(
            lambda result: (results.append(result), result_emitted.set()),
            QtCore.Qt.ConnectionType.DirectConnection)
        worker._commutation_signature_green = True
        worker._commutation_signature_token = "offline-signature"
        worker.start_verify_vp(
            {}, signature_token="offline-signature")
        cancel = worker.cancel_velpos

    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)
    runner = threading.Thread(target=worker.run, name="tune-cancel-barrier")
    runner.start()
    try:
        assert telemetry_entered.wait(2.0), (
            "worker never entered the pre-mutation telemetry read")

        cancel()
        telemetry_release.set()
        assert result_emitted.wait(2.0), (
            "worker did not publish a typed RED result")
    finally:
        telemetry_release.set()
        worker.stop()
        runner.join(3.0)

    assert not runner.is_alive()
    assert algorithm_calls == []
    assert len(results) == 1
    assert results[0].status == "RED"
    assert "superseded" in results[0].reason
    assert not any(
        command == "ST" or command == "SV" or "=" in command
        for command, _mo_before in link.command_log
    )
    assert link.disconnect_called


@pytest.mark.parametrize("workflow", ("autotune", "velpos", "verify"))
def test_cancelled_queued_tune_does_not_poison_fresh_generation(
        monkeypatch, workflow):
    """Abort covers existing generations, while a later explicit Start is fresh."""
    link = _SafetyLink(mo=0)
    worker = app_main.DriveWorker("COM_FAKE")
    algorithm_calls: list[str] = []
    results = []
    two_results = threading.Event()

    def completed(result):
        results.append(result)
        if len(results) == 2:
            two_results.set()

    def fresh_generation_algorithm(_link, _params):
        algorithm_calls.append(workflow)
        if workflow == "autotune":
            return app_main.autotune_current.AutotuneResult(
                status=app_main.autotune_current.RED,
                reason="fresh generation ran")
        return app_main.autotune_velpos.AutotuneVPResult(
            status=app_main.autotune_velpos.RED,
            reason="fresh generation ran")

    if workflow == "autotune":
        monkeypatch.setattr(
            app_main.autotune_current, "run_current_autotune",
            fresh_generation_algorithm)
        worker.autotune_result.connect(
            completed, QtCore.Qt.ConnectionType.DirectConnection)
        worker.start_autotune({})
        worker.cancel_autotune()
        worker.start_autotune({})
    elif workflow == "velpos":
        monkeypatch.setattr(
            app_main.autotune_velpos, "run_velpos_autotune",
            fresh_generation_algorithm)
        worker.velpos_result.connect(
            completed, QtCore.Qt.ConnectionType.DirectConnection)
        worker._commutation_signature_green = True
        params = {"r_pp_ohm": 0.139, "l_pp_h": 41.6e-6}
        worker.start_velpos_autotune(params)
        worker.cancel_velpos()
        worker.start_velpos_autotune(params)
    else:
        monkeypatch.setattr(
            app_main.autotune_velpos, "verify_run_vp",
            fresh_generation_algorithm)
        worker.verify_result.connect(
            completed, QtCore.Qt.ConnectionType.DirectConnection)
        worker._commutation_signature_green = True
        worker._commutation_signature_token = "offline-signature"
        worker.start_verify_vp(
            {}, signature_token="offline-signature")
        worker.cancel_velpos()
        worker.start_verify_vp(
            {}, signature_token="offline-signature")

    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)
    runner = threading.Thread(target=worker.run, name="fresh-tune-generation")
    runner.start()
    try:
        assert two_results.wait(2.0), (
            "worker did not resolve both the cancelled and fresh generations")
    finally:
        worker.stop()
        runner.join(3.0)

    assert not runner.is_alive()
    assert len(results) == 2
    assert "superseded" in results[0].reason
    assert results[1].reason.startswith("fresh generation ran")
    assert algorithm_calls == [workflow]
    assert link.disconnect_called


@pytest.mark.parametrize("phase", ("P1", "P2"))
def test_worker_direct_gain_trial_dispatch_is_production_locked_without_mutation(
        monkeypatch, phase):
    """Bypassing the UI cannot bypass the production RAM-trial lock."""
    link = _SafetyLink(mo=0)
    worker = app_main.DriveWorker("COM_FAKE")
    result_emitted = threading.Event()
    actions = []

    def record_action(action, ok, message, trial):
        actions.append((action, ok, message, trial))
        result_emitted.set()

    if phase == "P1":
        worker.current_gain_action.connect(
            record_action, QtCore.Qt.ConnectionType.DirectConnection)
        worker.begin_current_gain_trial(
            app_main.autotune_current.AutotuneResult(
                status=app_main.autotune_current.GREEN,
                kp_v_per_a=0.0712,
                ki_hz=812.9))
    else:
        worker.velpos_gain_action.connect(
            record_action, QtCore.Qt.ConnectionType.DirectConnection)
        worker.begin_velpos_gain_trial(
            app_main.autotune_velpos.AutotuneVPResult(
                status=app_main.autotune_velpos.GREEN,
                kp_vel=8.0e-5,
                ki_vel_hz=10.7,
                kp_pos=85.2114))

    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)
    runner = threading.Thread(target=worker.run, name="gain-trial-lock")
    runner.start()
    try:
        assert result_emitted.wait(2.0), (
            "worker did not publish the production gain-trial rejection")
    finally:
        worker.stop()
        runner.join(3.0)

    assert not runner.is_alive()
    assert len(actions) == 1
    action, ok, message, trial = actions[0]
    assert action == "begin" and ok is False and trial is None
    assert "durable" in message.lower() and "locked" in message.lower()
    assert worker._p1_gain_trial is None
    assert worker._vp_gain_trial is None
    assert not any(
        command == "BG" or command == "SV" or "=" in command
        for command, _mo_before in link.command_log
    )
    assert link.disconnect_called


def test_p1_configuration_restore_unknown_latches_worker_mutation_lock(
        monkeypatch):
    link = _SafetyLink(mo=0)
    worker = app_main.DriveWorker("COM_FAKE")
    worker._connection_identity_verified = True
    monkeypatch.setattr(
        app_main.autotune_current, "run_current_autotune",
        lambda _link, _params: app_main.autotune_current.AutotuneResult(
            status=app_main.autotune_current.RED,
            reason="configuration restore UNKNOWN",
            evidence={"configuration_state": "UNKNOWN"}))

    worker._run_autotune(link, {})

    assert worker._motion_config_unknown
    allowed, detail = worker._trial_job_guard("autotune", {})
    assert not allowed
    assert "UNKNOWN" in detail


@pytest.mark.parametrize("workflow", ("velpos", "verify"))
def test_p2_critical_limit_restore_unknown_latches_worker_mutation_lock(
        monkeypatch, workflow):
    link = _SafetyLink(mo=0)
    worker = app_main.DriveWorker("COM_FAKE")
    worker._connection_identity_verified = True
    worker._commutation_signature_green = True
    result = app_main.autotune_velpos.AutotuneVPResult(
        status=app_main.autotune_velpos.GREEN,
        reason="",
        evidence={"configuration_state": "UNKNOWN"})
    emitted = []

    if workflow == "velpos":
        monkeypatch.setattr(
            app_main.autotune_velpos, "run_velpos_autotune",
            lambda _link, _params: result)
        worker.velpos_result.connect(emitted.append)
        worker._run_velpos_autotune(link, {})
    else:
        monkeypatch.setattr(
            app_main.autotune_velpos, "verify_run_vp",
            lambda _link, _params: result)
        worker.verify_result.connect(emitted.append)
        worker._run_verify_vp(link, {})

    assert worker._motion_config_unknown
    assert not worker._commutation_signature_green
    assert emitted and emitted[0].status == app_main.autotune_velpos.RED
    assert "UNKNOWN" in emitted[0].reason
    allowed, detail = worker._trial_job_guard("autotune", {})
    assert not allowed
    assert "UNKNOWN" in detail


def test_p2_configuration_unknown_immediately_publishes_durable_lock_status():
    link = _SafetyLink(mo=0)
    link.persistence_status = lambda: {
        "status": "PERSISTENCE_UNKNOWN",
        "resolved": False,
        "detail": "P2_LIMITS restore closeout is unresolved",
        "lock_active": True,
        "record_id": "p2-limits-record",
        "phase": "P2_LIMITS",
        "other_active_count": 0,
        "ledger_error": None,
    }
    worker = app_main.DriveWorker("COM_FAKE")
    result = app_main.autotune_velpos.AutotuneVPResult(
        status=app_main.autotune_velpos.RED,
        reason="limit restore UNKNOWN",
        evidence={"configuration_state": "UNKNOWN"})
    published = []
    worker.persistence_audit_status.connect(published.append)

    assert worker._latch_configuration_unknown(link, result, "P2") is True

    assert worker._persistence_recovery_unknown is True
    assert published
    assert published[-1]["lock_active"] is True
    assert published[-1]["phase"] == "P2_LIMITS"


def test_new_worker_startup_reloads_p2_limits_durable_lock(monkeypatch):
    link = _SafetyLink(mo=0)
    link.persistence_status = lambda: {
        "status": "PERSISTENCE_UNKNOWN",
        "resolved": False,
        "detail": "reloaded active P2_LIMITS incident",
        "lock_active": True,
        "record_id": "p2-limits-record",
        "phase": "P2_LIMITS",
        "other_active_count": 0,
        "ledger_error": None,
    }
    worker = app_main.DriveWorker("COM_FAKE")
    statuses = []
    worker.persistence_audit_status.connect(statuses.append)
    worker.connected.connect(lambda _info: worker.stop())
    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)

    worker.run()

    assert worker._persistence_recovery_unknown is True
    assert statuses and statuses[0]["phase"] == "P2_LIMITS"
    allowed, detail = worker._trial_job_guard("velpos", {})
    assert not allowed
    assert "UNKNOWN" in detail


def test_disconnect_race_does_not_drop_queued_urgent_motion_stop(monkeypatch):
    """STOP followed immediately by Disconnect still owns one verified stop."""
    link = _SafetyLink(mo=1)
    worker = app_main.DriveWorker("COM_FAKE")
    worker.request_motion_stop()
    worker.stop()
    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)

    worker.run()

    _assert_stop_disable_was_verified(link)
    assert list(worker._urgent_jobs) == []
    assert link.disconnect_called


def test_stop_requested_while_connect_blocks_still_owns_verified_stop(monkeypatch):
    """The post-connect decision must not use a pre-connect STOP snapshot."""
    entered = threading.Event()
    release = threading.Event()

    class _BlockingConnectLink(_SafetyLink):
        def connect(self):
            entered.set()
            assert release.wait(2.0), "test did not release fake connect"
            return True

    link = _BlockingConnectLink(mo=1)
    worker = app_main.DriveWorker("COM_FAKE")
    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)

    runner = threading.Thread(target=worker.run, name="blocking-fake-connect")
    runner.start()
    assert entered.wait(2.0), "worker never entered fake connect"
    worker.request_motion_stop()
    worker.stop()
    release.set()
    runner.join(3.0)

    assert not runner.is_alive()
    _assert_stop_disable_was_verified(link)
    assert link.disconnect_called


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


class _WorkerThatCannotStopYet:
    def __init__(self):
        self.stop_calls = 0
        self.wait_calls: list[int] = []

    @staticmethod
    def isRunning():
        return True

    def stop(self):
        self.stop_calls += 1

    def wait(self, timeout_ms):
        self.wait_calls.append(int(timeout_ms))
        return False


def test_close_event_is_ignored_when_worker_shutdown_times_out(
        monkeypatch, qapp):
    """A failed QThread wait must keep the application alive and controllable."""
    monkeypatch.setattr(app_main, "list_serial_ports", lambda: ["COM_FAKE"])
    window = app_main.MainWindow()
    worker = _WorkerThatCannotStopYet()
    window.worker = worker
    event = QtGui.QCloseEvent()
    try:
        window.closeEvent(event)
        assert worker.stop_calls == 1
        assert len(worker.wait_calls) == 1
        assert not event.isAccepted(), (
            "closeEvent accepted shutdown although the worker was still running")
    finally:
        window.worker = None
        window.close()
        window.deleteLater()
        qapp.processEvents()


class _DisconnectSpy:
    def __init__(self):
        self.disconnect_called = False

    def Disconnect(self):
        self.disconnect_called = True


def test_recorder_latch_write_failure_cannot_skip_vendor_disconnect(monkeypatch):
    """Durable-latch failure and transport cleanup are independent obligations."""
    link = elmo_link.ElmoLink("COM_FAKE")
    comm = _DisconnectSpy()
    link._comm = comm
    link._connected_drive_identity = "fake-drive-identity"
    link._rec_pending = {"drive_identity": "fake-drive-identity"}

    def stop_lost():
        raise RuntimeError("negative-control Recorder Stop loss")

    def latch_unwritable(*_args, **_kwargs):
        raise OSError("negative-control durable latch write failure")

    monkeypatch.setattr(link, "record_stop", stop_lost)
    monkeypatch.setattr(elmo_link, "_latch_recorder_unknown", latch_unwritable)

    try:
        link.disconnect()
    except Exception:
        # The public error policy may propagate or aggregate this failure; the
        # invariant under test is that transport cleanup was attempted anyway.
        pass

    assert comm.disconnect_called, (
        "durable Recorder-latch failure skipped the vendor Disconnect call")


def test_stop_before_run_never_publishes_connected(monkeypatch):
    """A cancelled connection may emit stopped, but never transient ONLINE."""
    link = _SafetyLink(mo=0)
    worker = app_main.DriveWorker("COM_FAKE")
    connected: list[dict] = []
    stopped: list[bool] = []
    worker.connected.connect(connected.append)
    worker.stopped.connect(lambda: stopped.append(True))
    worker.stop()
    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)

    worker.run()

    assert connected == []
    assert stopped == [True]


@pytest.mark.parametrize("failure_mode", ("unverified-result", "helper-exception"))
def test_unverified_energy_closeout_keeps_guard_locked_and_disconnects(
        monkeypatch, failure_mode):
    """UNKNOWN torque removal must survive through terminal cleanup as a lock."""
    link = _SafetyLink(mo=1)
    worker = app_main.DriveWorker("COM_FAKE")
    terminal: list[bool] = []
    motion_results: list[tuple[str, object]] = []
    worker.stopped.connect(lambda: terminal.append(True))
    worker.motion_result.connect(
        lambda action, result: motion_results.append((action, result)))

    def unsafe_closeout(*_args, **_kwargs):
        if failure_mode == "helper-exception":
            raise RuntimeError("negative-control safe-stop helper crash")
        return app_main.single_axis_motion.MotionResult(
            app_main.single_axis_motion.UNKNOWN,
            "negative-control disable readback mismatch",
            final_state={"disabled_verified": False},
            evidence={"negative_control": failure_mode},
        )

    monkeypatch.setattr(
        app_main.single_axis_motion, "safe_stop_disable", unsafe_closeout)
    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)
    worker.request_motion_stop()
    worker.stop()

    worker.run()

    assert terminal == [True]
    assert link.disconnect_called
    assert worker._energy_closeout_unknown
    assert not worker._session_coordinate_known
    allowed, detail = worker._trial_job_guard("motor_write", {})
    assert not allowed
    assert "Energy closeout UNKNOWN" in detail
    assert motion_results
    assert motion_results[-1][1].final_state["disabled_verified"] is False
