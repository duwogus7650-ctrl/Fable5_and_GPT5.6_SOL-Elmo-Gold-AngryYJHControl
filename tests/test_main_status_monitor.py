"""Offline fail-closed UI contracts for HOST-OBSERVED Status Monitor v0.1."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

import main as app_main
import status_monitor


HASHED_ID = "elmo-sn4-sha256:" + ("a" * 64)


class _PoisonWorker:
    """Allow liveness checks, but record every drive-facing method call."""

    def __init__(self):
        self.calls = []

    def isRunning(self):
        return True

    def __getattr__(self, name):
        def forbidden(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            raise AssertionError("Status Monitor touched worker.%s" % name)
        return forbidden


def _telemetry(sequence=1, **overrides):
    finished = time.monotonic()
    sample = {
        "pos": 123,
        "vel": -4.5,
        "pos_err": 2,
        "iq": 0.125,
        "mo": 0,
        "telemetry_valid": True,
        "telemetry_error": None,
        "telemetry_sequence": sequence,
        "telemetry_received_monotonic": finished,
        "_sample_started_monotonic": finished - 0.01,
        "_sample_finished_monotonic": finished,
        "_sample_duration_s": 0.01,
        "session_coordinate_known": True,
        "encoder_maintenance_reconnect_required": False,
    }
    sample.update(overrides)
    return sample


def _connection_info(*, sequence=1, identity=HASHED_ID):
    return {
        "fw": "Twitter 01.01.16.00",
        "pal": "90",
        "boot": "DSP Boot",
        "target_type": "Gold Drive",
        "drive_identity": identity,
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
    win.resize(1366, 820)
    win.show()
    qapp.processEvents()
    yield win
    win.worker = None
    win.close()
    qapp.processEvents()


def _open_dialog(window, qapp):
    window.app_menu_actions["ui.status_monitor"].trigger()
    qapp.processEvents()
    dialog = window.status_monitor_dialog
    assert dialog is not None and dialog.isVisible()
    return dialog


def _values_by_signal(dialog):
    return {
        dialog.table.item(row, 1).text(): dialog.table.item(row, 2).text()
        for row in range(dialog.table.rowCount())
    }


def _select_signal_row(dialog, signal):
    for row in range(dialog.table.rowCount()):
        if dialog.table.item(row, 1).text() == signal:
            dialog.table.selectRow(row)
            return
    raise AssertionError("signal row not found: %s" % signal)


def test_floating_action_opens_one_modeless_zero_timer_zero_io_dialog(
        window, qapp):
    poison = _PoisonWorker()
    window.worker = poison

    dialog = _open_dialog(window, qapp)
    first = dialog
    window.app_menu_actions["ui.status_monitor"].trigger()
    qapp.processEvents()

    assert window.status_monitor_dialog is first
    assert not dialog.isModal()
    assert dialog.windowModality() == QtCore.Qt.WindowModality.NonModal
    assert dialog.findChildren(QtCore.QTimer) == []
    assert poison.calls == []
    assert "NO NEW DRIVE POLLING" in dialog.lbl_contract.text()
    assert not window.app_menu_actions[
        "eas.status_monitor.live_polling"].isEnabled()
    assert not window.app_menu_actions[
        "eas.status_monitor.native_config"].isEnabled()


def test_default_rows_are_exact_allowlist_blank_and_read_only(window, qapp):
    dialog = _open_dialog(window, qapp)

    assert tuple(_values_by_signal(dialog)) == ("PX", "VX", "PE", "IQ", "MO")
    assert set(_values_by_signal(dialog).values()) == {"—"}
    assert dialog.table.columnCount() == 5
    assert (dialog.table.editTriggers()
            == QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    assert dialog.lbl_state.text() == "NO CURRENT SAMPLE"


def test_accepted_current_generation_telemetry_updates_without_new_worker_call(
        window, qapp):
    poison = _PoisonWorker()
    window.worker = poison
    dialog = _open_dialog(window, qapp)

    window._on_connected(_connection_info())
    qapp.processEvents()

    snapshot = window.status_monitor_model.snapshot()
    assert snapshot.current is True
    assert snapshot.generation == window.session_log.current_generation == 1
    assert snapshot.sequence == 1
    assert _values_by_signal(dialog) == {
        "PX": "123", "VX": "-4.5", "PE": "2",
        "IQ": "0.125", "MO": "0",
    }
    assert "CURRENT" in dialog.lbl_state.text()
    assert "GEN 1" in dialog.lbl_state.text()
    assert "SEQ 1" in dialog.lbl_state.text()
    assert poison.calls == []


def test_core_revocation_blanks_monitor_without_losing_session_line_order(
        window, qapp):
    poison = _PoisonWorker()
    window.worker = poison
    dialog = _open_dialog(window, qapp)
    window._on_connected(_connection_info())
    before_lines = window.status_monitor_model.config.lines

    window._revoke_telemetry_authority("watchdog expired")
    qapp.processEvents()

    assert window.status_monitor_model.config.lines == before_lines
    assert window.status_monitor_model.snapshot().current is False
    assert set(_values_by_signal(dialog).values()) == {"—"}
    assert dialog.lbl_state.text() == "NO CURRENT SAMPLE"
    assert poison.calls == []


def test_monitor_observer_failure_is_local_and_cannot_revoke_core_authority(
        window, qapp, monkeypatch):
    poison = _PoisonWorker()
    window.worker = poison
    dialog = _open_dialog(window, qapp)
    window._on_connected(_connection_info())

    def explode(*args, **kwargs):
        raise RuntimeError("injected monitor observer failure")

    monkeypatch.setattr(
        type(window.status_monitor_model), "observe", explode)
    window._on_telemetry(_telemetry(2, pos=777, iq=0.25))
    qapp.processEvents()

    assert window._telemetry_authoritative is True
    assert window._last_mo == 0
    assert window._last_telemetry_sequence == 2
    assert window.m_pos.text() == "777"
    assert set(_values_by_signal(dialog).values()) == {"—"}
    assert "OBSERVER ERROR" in dialog.lbl_state.text()
    assert poison.calls == []


def test_session_line_remove_add_reorder_reset_is_zero_io_and_reused(
        window, qapp):
    poison = _PoisonWorker()
    window.worker = poison
    dialog = _open_dialog(window, qapp)

    _select_signal_row(dialog, "IQ")
    dialog.btn_remove.click()
    assert window.status_monitor_model.config.lines == (
        "PX", "VX", "PE", "MO")
    assert "IQ" not in _values_by_signal(dialog)

    index = dialog.cmb_available.findText("IQ")
    assert index >= 0
    dialog.cmb_available.setCurrentIndex(index)
    dialog.btn_add.click()
    assert window.status_monitor_model.config.lines[-1] == "IQ"

    _select_signal_row(dialog, "IQ")
    dialog.btn_up.click()
    assert window.status_monitor_model.config.lines[-2:] == ("IQ", "MO")

    dialog.close()
    qapp.processEvents()
    reopened = _open_dialog(window, qapp)
    assert reopened is dialog
    assert reopened.model.config.lines[-2:] == ("IQ", "MO")

    dialog.btn_reset.click()
    assert window.status_monitor_model.config is status_monitor.DEFAULT_CONFIG
    assert poison.calls == []
    assert len(window.findChildren(app_main.StatusMonitorDialog)) == 1


def test_dialog_default_position_does_not_cover_connection_or_safety_shell(
        window, qapp):
    dialog = _open_dialog(window, qapp)
    dialog_rect = dialog.frameGeometry()
    protected = (
        window.cmb_conn, window.cmb_port, window.btn_port_refresh,
        window.btn_conn, window.btn_global_stop,
        window.lbl_persistence_badge, window.lbl_state,
        *window.app_menu_buttons.values(),
    )
    for widget in protected:
        origin = widget.mapToGlobal(QtCore.QPoint(0, 0))
        assert not dialog_rect.intersects(QtCore.QRect(origin, widget.size()))
    assert window.width() == 1366
    assert window.height() == 820
