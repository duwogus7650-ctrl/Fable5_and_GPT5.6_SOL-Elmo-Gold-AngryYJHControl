"""Offline UI and zero-drive-I/O contracts for Session Log v0.1."""

from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

import main as app_main
import operation_catalog


HASHED_ID = "elmo-sn4-sha256:" + ("c" * 64)
HASHED_ID_B = "elmo-sn4-sha256:" + ("d" * 64)


class _PoisonWorker:
    """Allow UI liveness checks; fail every drive-facing method call."""

    def __init__(self):
        self.calls = []

    def isRunning(self):
        return True

    def __getattr__(self, name):
        def forbidden(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            raise AssertionError("drive I/O forbidden from session log: %s" % name)
        return forbidden


class _SignalWorker(QtCore.QObject):
    axis_summary = QtCore.pyqtSignal(dict)
    telemetry = QtCore.pyqtSignal(dict)
    failed = QtCore.pyqtSignal(str)
    stopped = QtCore.pyqtSignal()
    recorder_status_changed = QtCore.pyqtSignal(str, str)
    persistence_audit_status = QtCore.pyqtSignal(object)
    motion_result = QtCore.pyqtSignal(str, object)


class _ConnectionWorker:
    def __init__(self):
        self.stop_calls = 0

    def isRunning(self):
        return True

    def stop(self):
        self.stop_calls += 1


class _RecorderWorker(_ConnectionWorker):
    def __init__(self):
        super().__init__()
        self.discover_calls = 0
        self.start_calls = []

    def discover_recorder_signals(self):
        self.discover_calls += 1

    def start_recorder(self, request):
        self.start_calls.append(request)
        return len(self.start_calls)


def _telemetry(sequence=1, *, mo=0, received=None):
    finished = time.monotonic() if received is None else float(received)
    started = finished - 0.01
    return {
        "pos": 10,
        "vel": 0,
        "pos_err": 0,
        "iq": 0.0,
        "mo": mo,
        "telemetry_valid": True,
        "telemetry_error": None,
        "telemetry_sequence": sequence,
        "telemetry_received_monotonic": finished,
        "_sample_started_monotonic": started,
        "_sample_finished_monotonic": finished,
        "_sample_duration_s": finished - started,
        "session_coordinate_known": True,
        "encoder_maintenance_reconnect_required": False,
    }


def _freeze_connection_access_mode(
        win, mode=app_main.SUPERVISED_ACCESS_MODE) -> None:
    """Freeze the same one-shot access mode on the UI and active worker."""
    worker = getattr(win, "worker", None)
    if worker is None:
        raise AssertionError("connection admission fixture requires a worker")
    win._requested_connection_access_mode = mode
    worker.access_mode = mode


def _connection_info(win, *, sequence=1, identity=HASHED_ID):
    _freeze_connection_access_mode(win)
    return {
        "fw": "Twitter 01.01.16.00",
        "pal": "90",
        "boot": "DSP Boot",
        "target_type": "Gold Drive",
        "drive_identity": identity,
        "access_mode": app_main.SUPERVISED_ACCESS_MODE,
        "initial_telemetry": _telemetry(sequence),
        "persistence_status": {
            "status": "CLEAR",
            "lock_active": False,
            "detail": "No active persistence incident",
            "record_id": None,
            "phase": None,
            "other_active_count": 0,
            "ledger_error": None,
            "resolved": False,
        },
    }


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch):
    monkeypatch.setattr(app_main, "list_serial_ports", lambda: ["COM_TEST"])
    win = app_main.MainWindow()
    win.show()
    qapp.processEvents()
    yield win
    win.worker = None
    win.close()
    qapp.processEvents()


def test_session_log_operations_are_local_while_full_fault_manager_stays_locked():
    assert operation_catalog.operation_spec(
        "nav.session_log").risk is operation_catalog.OperationRisk.LOCAL_UI
    assert operation_catalog.operation_spec("nav.session_log").menu_enabled
    assert operation_catalog.operation_spec(
        "session_log.export_json").risk is operation_catalog.OperationRisk.LOCAL_FILE
    assert operation_catalog.operation_spec(
        "session_log.export_csv").risk is operation_catalog.OperationRisk.LOCAL_FILE
    full = operation_catalog.operation_spec("eas.fault_log")
    assert full.status is operation_catalog.OperationStatus.NEED_DATA
    assert not full.menu_enabled


def test_opening_session_log_page_is_local_and_does_not_change_authority(
        window, qapp):
    poison = _PoisonWorker()
    window.worker = poison
    window._telemetry_authoritative = True
    window._last_mo = 0

    window.app_menu_actions["nav.session_log"].trigger()
    qapp.processEvents()

    assert window.stack.currentIndex() == 6
    assert window._telemetry_authoritative is True
    assert window._last_mo == 0
    assert poison.calls == []
    assert not window.app_menu_actions["eas.fault_log"].isEnabled()
    assert window.btn_session_export_json.property(
        "operationId") == "session_log.export_json"
    assert window.btn_session_export_csv.property(
        "operationId") == "session_log.export_csv"


def test_connection_and_same_state_telemetry_are_logged_without_event_flood(
        window):
    poison = _PoisonWorker()
    window.worker = poison
    window._on_connected(_connection_info(window))
    baseline = len(window.session_log.snapshot())

    for sequence in range(2, 102):
        window._on_telemetry(_telemetry(sequence, mo=0))

    rows = window.session_log.snapshot()
    assert len(rows) == baseline
    assert any(row["name"] == "connection.opened" for row in rows)
    assert any(row["name"] == "telemetry.state" for row in rows)
    assert poison.calls == []


def test_axis_summary_preserves_nonzero_raw_fault_without_decoding(window):
    poison = _PoisonWorker()
    window.worker = poison
    window._on_connected(_connection_info(window))
    window._on_axis_summary({
        "raw": {"MO": 0, "SO": 0, "MF": 8, "SR": 49152, "MS": 3},
        "errors": {},
        "scope": "single-axis read-only",
    })

    row = window.session_log.snapshot()[-1]
    assert row["name"] == "axis.raw_status"
    assert row["severity"] == "ERROR"
    assert row["payload"]["raw"]["MF"] == 8
    assert row["payload"]["raw"]["SR"] == 49152
    assert poison.calls == []


def test_json_and_csv_buttons_export_frozen_local_history_with_zero_worker_io(
        window, qapp, monkeypatch, tmp_path):
    poison = _PoisonWorker()
    window.worker = poison
    window.session_log.append(
        category="ui", name="local.test", payload={"detail": "offline"})
    json_path = tmp_path / "session.json"
    csv_path = tmp_path / "session.csv"
    paths = iter(((str(json_path), "JSON"), (str(csv_path), "CSV")))
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName",
        lambda *args, **kwargs: next(paths))

    window.btn_session_export_json.click()
    window.btn_session_export_csv.click()
    qapp.processEvents()

    assert json_path.is_file() and csv_path.is_file()
    assert json.loads(json_path.read_text(encoding="utf-8"))["event_count"] == 1
    assert "HOST_OBSERVED_NOT_DRIVE_HISTORY" in json_path.read_text(encoding="utf-8")
    assert poison.calls == []

    with pytest.raises(AssertionError, match="drive I/O forbidden"):
        poison.send_once("MF")
    assert poison.calls[0][0] == "send_once"


def test_session_log_table_is_read_only_and_render_does_not_call_worker(
        window, qapp):
    poison = _PoisonWorker()
    window.worker = poison
    window.session_log.append(
        category="recorder", name="READY_TO_UPLOAD",
        payload={"detail": "finite capture"})

    window._render_session_log()
    qapp.processEvents()

    assert window.session_log_table.rowCount() == 1
    assert (window.session_log_table.editTriggers()
            == QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    assert "HOST-OBSERVED" in window.lbl_session_log_contract.text()
    assert poison.calls == []


def test_session_log_contract_and_export_actions_are_visible_above_table(
        window, qapp):
    window.resize(1600, 900)
    window._nav_to(6)
    qapp.processEvents()

    table_y = window.session_log_table.mapTo(window, QtCore.QPoint(0, 0)).y()
    json_y = window.btn_session_export_json.mapTo(
        window, QtCore.QPoint(0, 0)).y()
    csv_y = window.btn_session_export_csv.mapTo(
        window, QtCore.QPoint(0, 0)).y()

    assert json_y < table_y
    assert csv_y < table_y
    assert (window.lbl_session_log_contract.height()
            >= window.lbl_session_log_contract.sizeHint().height())


def test_repeated_authority_revocation_is_logged_once(window):
    poison = _PoisonWorker()
    window.worker = poison
    window._on_connected(_connection_info(window))

    window._revoke_telemetry_authority("watchdog expired")
    window._revoke_telemetry_authority("watchdog expired again")

    lost = [row for row in window.session_log.snapshot()
            if row["name"] == "telemetry.authority_lost"]
    assert len(lost) == 1
    assert lost[0]["affects_current"] is True
    assert lost[0]["scope"] == "CURRENT"

    window._on_telemetry(_telemetry(2, mo=0))
    restored_index = len(window.session_log.snapshot()) - 1
    assert window.session_log.snapshot()[restored_index]["name"] == (
        "telemetry.authority_restored")
    window._revoke_telemetry_authority("second real authority loss")

    lost = [row for row in window.session_log.snapshot()
            if row["name"] == "telemetry.authority_lost"]
    assert len(lost) == 2
    rows = window.session_log.snapshot()
    first_loss = next(index for index, row in enumerate(rows)
                      if row["name"] == "telemetry.authority_lost")
    second_loss = max(index for index, row in enumerate(rows)
                      if row["name"] == "telemetry.authority_lost")
    assert any(row["name"] == "telemetry.authority_restored"
               for row in rows[first_loss + 1:second_loss])
    assert poison.calls == []


def test_previous_worker_signal_cannot_change_current_session_log(window, qapp):
    old_worker = _SignalWorker()
    current_worker = _PoisonWorker()
    old_worker.axis_summary.connect(window._on_axis_summary)
    old_worker.telemetry.connect(window._on_telemetry)
    old_worker.failed.connect(window._on_failed)
    old_worker.stopped.connect(window._on_stopped)
    old_worker.recorder_status_changed.connect(window._on_recorder_status)
    old_worker.persistence_audit_status.connect(
        window._on_persistence_audit_status)
    old_worker.motion_result.connect(window._on_motion_result)
    window.worker = current_worker
    window._on_connected(_connection_info(window))
    baseline = window.session_log.snapshot()

    old_worker.axis_summary.emit({
        "raw": {"MO": 1, "SO": 1, "MF": 99, "SR": 99, "MS": 99},
        "errors": {},
    })
    old_worker.telemetry.emit(_telemetry(2, mo=1))
    old_worker.failed.emit("late failure")
    old_worker.stopped.emit()
    old_worker.recorder_status_changed.emit("ERROR", "late recorder")
    old_worker.persistence_audit_status.emit({"status": "UNKNOWN"})
    old_worker.motion_result.emit(
        "move", SimpleNamespace(status="UNKNOWN", reason="late",
                                final_state={"MO": 1}))
    qapp.processEvents()

    assert window.session_log.snapshot() == baseline
    assert current_worker.calls == []


def test_new_connection_accepts_sequence_reset_without_old_stopped_signal(window):
    first = _ConnectionWorker()
    window.worker = first
    window._on_connected(_connection_info(
        window, sequence=50, identity=HASHED_ID))
    assert window._connection_admitted is True
    assert window._last_telemetry_sequence == 50

    second = _ConnectionWorker()
    window.worker = second
    window._on_connected(_connection_info(
        window, sequence=1, identity=HASHED_ID_B))

    assert window._connection_admitted is True
    assert window._last_telemetry_sequence == 1
    assert window.session_log.current_generation == 2
    assert second.stop_calls == 0
    rows = window.session_log.snapshot()
    assert all(row["scope"] == "HISTORICAL"
               for row in rows if row["generation"] == 1)
    assert all(row["scope"] == "CURRENT"
               for row in rows if row["generation"] == 2)
    assert any(row["generation"] == 2 and row["name"] == "connection.opened"
               for row in rows)


def test_new_connect_attempt_closes_orphaned_generation_before_failure(
        window, monkeypatch):
    first = _ConnectionWorker()
    window.worker = first
    window._on_connected(_connection_info(
        window, sequence=1, identity=HASHED_ID))
    assert window.session_log.connection_active is True

    window.worker = None
    monkeypatch.setattr(app_main.DriveWorker, "start", lambda _worker: None)
    window.cmb_port.setCurrentText("COM_TEST")
    window.connect_drive()

    assert window._ui_connected is False
    assert window._connection_admitted is False
    assert window._telemetry_authoritative is False
    assert window.lbl_state.text() == "CONNECTING"
    assert not window.btn_conn.isEnabled()
    for control in (
            window.btn_zero,
            window.btn_axis_refresh,
            window.btn_motor_write,
            window.btn_tune,
            window.btn_tune_signature,
            window.btn_tune_vp,
            window.btn_tune_verify,
            window.btn_tune_apply,
            window.btn_tune_vp_apply,
            window.btn_motion_run,
            window.btn_rec_signals,
    ):
        assert not control.isEnabled(), control.text()

    window._on_failed("new attempt failed before identity admission")

    assert window.session_log.connection_active is False
    rows = window.session_log.snapshot()
    assert all(row["scope"] == "HISTORICAL"
               for row in rows if row["generation"] == 1)
    assert rows[-1]["name"] == "connection.failed"
    assert rows[-1]["generation"] == 0
    assert rows[-1]["target_identity"] == "REDACTED_UNVERIFIED"


def test_soft_zero_handler_rejects_running_worker_without_ui_authority(window):
    class RunningMutationProbe:
        def __init__(self):
            self.calls = []

        @staticmethod
        def isRunning():
            return True

        def soft_zero(self):
            self.calls.append("soft_zero")

    probe = RunningMutationProbe()
    window.worker = probe
    window._ui_connected = True
    window._connection_admitted = False
    window._telemetry_authoritative = False
    window._last_mo = 0

    window.zero_position()

    assert probe.calls == []
    assert not window.btn_zero.isEnabled()


def test_malformed_hashed_identity_is_not_admitted(window):
    worker = _ConnectionWorker()
    window.worker = worker

    window._on_connected(_connection_info(
        window, identity="elmo-sn4-sha256:" + ("g" * 64)))

    assert window._connection_admitted is False
    assert worker.stop_calls == 1
    assert not any(row["name"] == "connection.opened"
                   for row in window.session_log.snapshot())
    failed = window.session_log.snapshot()[-1]
    assert failed["name"] == "connection.failed"
    assert failed["target_identity"] == "REDACTED_UNVERIFIED"


def test_regressed_source_timestamp_is_rejected_without_consuming_sequence(window):
    worker = _ConnectionWorker()
    window.worker = worker
    window._on_connected(_connection_info(window, sequence=1))
    accepted_time = window._last_telemetry_received_monotonic

    window._on_telemetry(_telemetry(
        2, mo=1, received=accepted_time - 0.05))

    assert window._telemetry_authoritative is False
    rejected = [row for row in window.session_log.snapshot()
                if row["name"] == "telemetry.rejected"][-1]
    assert rejected["freshness"] == "UI_REJECTED"
    assert rejected["telemetry_sequence"] == 2

    window._on_telemetry(_telemetry(2, mo=1))

    assert window._telemetry_authoritative is True
    assert window._last_telemetry_sequence == 2
    assert window.session_log.snapshot()[-1]["name"] == (
        "telemetry.authority_restored")
    assert any(row["name"] == "telemetry.state"
               and row["telemetry_sequence"] == 2
               for row in window.session_log.snapshot())


def test_initial_telemetry_expiry_after_open_requests_worker_stop(
        window, monkeypatch):
    worker = _ConnectionWorker()
    window.worker = worker
    decisions = iter((True, False))
    monkeypatch.setattr(
        window, "_telemetry_envelope_valid",
        lambda *_args, **_kwargs: next(decisions))

    window._on_connected(_connection_info(window))

    assert window._connection_admitted is False
    assert window._telemetry_authoritative is False
    assert worker.stop_calls == 1
    assert window.session_log.connection_active is True
    window._on_stopped()
    assert window.session_log.connection_active is False


def test_late_telemetry_after_connection_failure_cannot_restore_authority(window):
    worker = _ConnectionWorker()
    window.worker = worker
    window._on_connected(_connection_info(window, sequence=1))
    window._on_failed("transport failed")

    window._on_telemetry(_telemetry(2, mo=0))

    assert window._connection_admitted is False
    assert window._telemetry_authoritative is False
    assert window._last_telemetry_sequence == 0
    assert window.session_log.snapshot()[-1]["name"] == "telemetry.rejected"
    assert window.session_log.snapshot()[-1]["freshness"] == "UI_REJECTED"


def test_field_age_burst_reproduces_one_loss_then_fresh_restore(
        window, monkeypatch):
    """Replay the observed 690..695 queue ages without drive or wall-clock I/O."""
    clock = [10_000.0]
    monkeypatch.setattr(app_main.time, "monotonic", lambda: clock[0])
    worker = _ConnectionWorker()
    window.worker = worker
    info = _connection_info(window, sequence=1)
    worker.access_mode = app_main.OBSERVE_ONLY_ACCESS_MODE
    window._requested_connection_access_mode = (
        app_main.OBSERVE_ONLY_ACCESS_MODE)
    info["access_mode"] = app_main.OBSERVE_ONLY_ACCESS_MODE
    info["quiescent_state"] = {
        "MO": 0.0, "SO": 0.0, "VX": 0.0, "PS": -2.0, "MF": 0.0,
    }
    window._on_connected(info)
    window._on_telemetry(_telemetry(689, mo=0, received=clock[0]))
    baseline = len(window.session_log.snapshot())

    clock[0] = 10_002.0
    for sequence, age_s in enumerate(
            (1.514, 1.295, 1.077, 0.860, 0.640, 0.420), start=690):
        window._on_telemetry(_telemetry(
            sequence, mo=0, received=clock[0] - age_s))

    names = [
        row["name"] for row in window.session_log.snapshot()[baseline:]
    ]
    assert names == [
        "telemetry.rejected",
        "telemetry.authority_lost",
        "telemetry.rejected",
        "telemetry.rejected",
        "telemetry.rejected",
        "telemetry.rejected",
        "telemetry.authority_restored",
    ]
    assert window._last_telemetry_sequence == 695
    assert window._telemetry_authoritative is True
    assert window._last_mo == 0
    assert not window.btn_motor_write.isEnabled()


def test_close_timeout_queue_cannot_restore_terminating_connection_authority(
        window, monkeypatch):
    """A timed-out close must reject even a fresh queued worker sample."""

    class ShutdownTimeoutWorker(_ConnectionWorker):
        def __init__(self):
            super().__init__()
            self.wait_calls = []

        def wait(self, timeout_ms):
            self.wait_calls.append(int(timeout_ms))
            return False

    clock = [10_000.0]
    monkeypatch.setattr(app_main.time, "monotonic", lambda: clock[0])
    worker = ShutdownTimeoutWorker()
    window.worker = worker
    window._on_connected(_connection_info(window, sequence=1))
    assert window._connection_admitted is True
    assert window._telemetry_authoritative is True

    close_event = SimpleNamespace(ignored=False)
    close_event.ignore = lambda: setattr(close_event, "ignored", True)
    window.closeEvent(close_event)

    assert close_event.ignored is True
    assert worker.stop_calls == 1
    assert worker.wait_calls == [1500]
    assert window._connection_admitted is False
    assert window._telemetry_authoritative is False
    assert window._ui_connected is False

    # Replay the field trace's queue ages: five samples exceed the 0.5 s
    # source-age gate, while the sixth is fresh enough.  Shutdown admission,
    # not sample freshness, must remain the final authority boundary.
    clock[0] = 10_002.0
    for sequence, age_s in enumerate(
            (1.514, 1.295, 1.077, 0.860, 0.640, 0.420), start=2):
        window._on_telemetry(_telemetry(
            sequence, mo=0, received=clock[0] - age_s))

    rows = window.session_log.snapshot()
    assert not any(
        row["name"] == "telemetry.authority_restored"
        for row in rows
    )
    assert window._last_telemetry_sequence == 1
    assert window._telemetry_authoritative is False
    assert window._connection_admitted is False
    assert getattr(window, "_connection_shutdown_pending", False) is True
    assert window.lbl_state.text() == "DISCONNECTING"
    assert not window.btn_conn.isEnabled()
    assert not window.cmb_port.isEnabled()
    assert not window.cmb_conn.isEnabled()
    assert not window.cmb_access_mode.isEnabled()

    window._on_stopped()

    assert window._connection_shutdown_pending is False
    assert window.lbl_state.text() == "OFFLINE"
    assert window.btn_conn.isEnabled()
    assert window.cmb_port.isEnabled()
    assert window.cmb_conn.isEnabled()
    assert window.cmb_access_mode.isEnabled()


def test_disconnect_request_rejects_fresh_sample_before_stopped_signal(window):
    """Disconnect authority must close synchronously, not on a later signal."""
    worker = _ConnectionWorker()
    window.worker = worker
    window._on_connected(_connection_info(window, sequence=1))
    assert window._telemetry_authoritative is True

    window.disconnect_drive()
    window._on_telemetry(_telemetry(2, mo=0))

    assert worker.stop_calls == 1
    assert window._connection_admitted is False
    assert window._ui_connected is False
    assert window._telemetry_authoritative is False
    assert window._last_telemetry_sequence == 1
    assert not any(
        row["name"] == "telemetry.authority_restored"
        for row in window.session_log.snapshot()
    )
    assert getattr(window, "_connection_shutdown_pending", False) is True
    assert window.lbl_state.text() == "DISCONNECTING"
    assert not window.btn_conn.isEnabled()
    assert not window.cmb_port.isEnabled()
    assert not window.cmb_conn.isEnabled()
    assert not window.cmb_access_mode.isEnabled()


def test_late_connected_signal_cannot_hide_pending_worker_cleanup(window):
    """A pre-stop connected signal cannot turn DISCONNECTING into OFFLINE."""
    worker = _ConnectionWorker()
    window.worker = worker
    window._on_connected(_connection_info(window, sequence=1))
    queued_connected = _connection_info(window, sequence=2)

    window.disconnect_drive()
    window._on_connected(queued_connected)

    assert window._connection_admitted is False
    assert window._telemetry_authoritative is False
    assert getattr(window, "_connection_shutdown_pending", False) is True
    assert window.lbl_state.text() == "DISCONNECTING"
    assert not window.btn_conn.isEnabled()
    assert not window.cmb_port.isEnabled()
    assert not window.cmb_conn.isEnabled()
    assert not window.cmb_access_mode.isEnabled()


def test_recorder_button_status_is_applied_locally_and_blocks_duplicate_queue(
        window, qapp):
    worker = _RecorderWorker()
    window.worker = worker
    window._on_connected(_connection_info(window))
    assert window.btn_rec_signals.isEnabled()

    window.btn_rec_signals.click()
    qapp.processEvents()

    assert worker.discover_calls == 1
    assert window._recorder_ui_state == "DISCOVERING_SIGNALS"
    assert not window.btn_rec_signals.isEnabled()
    assert window.session_log.snapshot()[-1]["payload"]["source"] == "ui"

    window._on_recorder_signals_result(("PX",), None)
    recorder_rows = [row for row in window.session_log.snapshot()
                     if row["name"] == "recorder.state"]
    assert recorder_rows[-1]["payload"]["state"] == "IDLE"
    item = window.rec_signal_list.item(0)
    item.setCheckState(QtCore.Qt.CheckState.Checked)
    window._update_recorder_controls()
    assert window.btn_rec_immediate.isEnabled()

    window.btn_rec_immediate.click()
    window.btn_rec_immediate.click()
    qapp.processEvents()

    assert len(worker.start_calls) == 1
    assert window._recorder_ui_state == "CONFIGURING"
    assert not window.btn_rec_immediate.isEnabled()
