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
from PyQt6 import QtGui, QtWidgets

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
        worker.start_verify_vp({})

    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)
    worker.run()

    assert algorithm_calls == [workflow]
    _assert_stop_disable_was_verified(link)
    assert link.disconnect_called


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
