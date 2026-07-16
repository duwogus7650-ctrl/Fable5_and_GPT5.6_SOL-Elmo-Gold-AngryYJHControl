"""Offline lifecycle contracts for HOST-OBSERVED Status Monitor v0.1.

These tests exercise only MainWindow's accepted-telemetry projection.  They
replace the live worker with inert doubles and never open a serial transport.
"""

from __future__ import annotations

import os
import json
import subprocess
import sys
import textwrap
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

import main as app_main


HASH_A = "elmo-sn4-sha256:" + ("a" * 64)
HASH_B = "elmo-sn4-sha256:" + ("b" * 64)


@pytest.mark.parametrize("skin", ("qdd", "amber", "angrybirds"))
def test_production_skin_monitor_is_bounded_private_and_zero_io(skin):
    probe = textwrap.dedent(r"""
        import json
        import os
        from PyQt6 import QtCore, QtGui, QtWidgets
        import main

        identity = "elmo-sn4-sha256:" + ("a" * 64)
        main.list_serial_ports = lambda: ["COM_TEST"]
        app = QtWidgets.QApplication([])
        font_path = os.path.join(os.environ["WINDIR"], "Fonts", "malgun.ttf")
        font_id = QtGui.QFontDatabase.addApplicationFont(font_path)
        family = QtGui.QFontDatabase.applicationFontFamilies(font_id)[0]
        app.setFont(QtGui.QFont(family, 10))
        app.setStyleSheet(
            main.theme.STYLE + '\n* { font-family: "%s"; }' % family)

        class PoisonWorker:
            def __init__(self):
                self.calls = []
            def isRunning(self):
                return True
            def __getattr__(self, name):
                def forbidden(*args, **kwargs):
                    self.calls.append(name)
                    raise AssertionError(name)
                return forbidden

        window = main.MainWindow()
        window.resize(1366, 820)
        window.show()
        for _ in range(5):
            app.processEvents()
        poison = PoisonWorker()
        window.worker = poison
        window.app_menu_actions["ui.status_monitor"].trigger()
        for _ in range(5):
            app.processEvents()
        dialog = window.status_monitor_dialog

        snapshot = window.status_monitor_model.activate_generation(1, identity)
        snapshot = window.status_monitor_model.observe(
            {"pos": 123, "vel": -4.5, "pos_err": 2,
             "iq": 0.125, "mo": 0},
            generation=1, sequence=1, drive_identity=identity, fresh=True)
        window._render_status_monitor(snapshot, observer_error=False)
        for _ in range(5):
            app.processEvents()

        dialog_rect = dialog.frameGeometry()
        protected = (
            window.cmb_conn, window.cmb_port, window.btn_port_refresh,
            window.btn_conn, window.btn_global_stop,
            window.lbl_persistence_badge, window.lbl_state,
            *window.app_menu_buttons.values(),
        )
        overlaps = []
        for widget in protected:
            origin = widget.mapToGlobal(QtCore.QPoint(0, 0))
            if dialog_rect.intersects(QtCore.QRect(origin, widget.size())):
                overlaps.append(widget.objectName() or widget.text())

        visible = []
        for widget in (dialog, *dialog.findChildren(QtWidgets.QWidget)):
            for accessor in ("windowTitle", "toolTip", "statusTip",
                             "whatsThis", "accessibleName",
                             "accessibleDescription"):
                value = getattr(widget, accessor)()
                if value:
                    visible.append(str(value))
            if isinstance(widget, (QtWidgets.QLabel,
                                   QtWidgets.QAbstractButton)):
                visible.append(widget.text())
        for row in range(dialog.table.rowCount()):
            for column in range(dialog.table.columnCount()):
                item = dialog.table.item(row, column)
                if item is not None:
                    visible.append(item.text())

        print(json.dumps({
            "size": [window.width(), window.height()],
            "minimum": [window.minimumSizeHint().width(),
                        window.minimumSizeHint().height()],
            "dialog": [dialog_rect.x(), dialog_rect.y(),
                       dialog_rect.width(), dialog_rect.height()],
            "overlaps": overlaps,
            "timer_count": len(dialog.findChildren(QtCore.QTimer)),
            "worker_calls": poison.calls,
            "stack_count": window.stack.count(),
            "state": dialog.lbl_state.text(),
            "values": [dialog.table.item(row, 2).text()
                       for row in range(dialog.table.rowCount())],
            "identity_visible": (identity in "\n".join(visible)
                                 or identity.split(":", 1)[1]
                                 in "\n".join(visible)),
            "status_bar_count": len(
                window.findChildren(QtWidgets.QStatusBar)),
        }))
        window.worker = None
        window.close()
    """)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["AYJH_THEME"] = skin
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=os.path.dirname(app_main.__file__), env=env,
        text=True, capture_output=True, timeout=60, check=True)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["size"] == [1366, 820]
    assert result["minimum"][1] <= 820
    # QDialog frameGeometry includes the 2 px platform frame on each side.
    assert result["dialog"][2:] == [724, 414]
    assert result["overlaps"] == []
    assert result["timer_count"] == 0
    assert result["worker_calls"] == []
    assert result["stack_count"] == 8
    assert result["state"] == "CURRENT · GEN 1 · SEQ 1"
    assert result["values"] == ["123", "-4.5", "2", "0.125", "0"]
    assert result["identity_visible"] is False
    assert result["status_bar_count"] == 0


class _ConnectionWorker:
    """An admitted, non-I/O worker double."""

    def __init__(self):
        self.stop_calls = 0

    @staticmethod
    def isRunning():
        return True

    def stop(self):
        self.stop_calls += 1


class _OldWorker(QtCore.QObject):
    """Signal source used to prove sender-identity rejection."""

    telemetry = QtCore.pyqtSignal(dict)


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


def _connection_info(*, sequence=1, identity=HASH_A):
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
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch):
    monkeypatch.setattr(app_main, "list_serial_ports", lambda: ["COM_TEST"])
    win = app_main.MainWindow()
    win.resize(1366, 820)
    win.show()
    # Keep this lifecycle suite deterministic: it supplies every sample
    # directly and does not test the independent watchdog clock.
    win._telemetry_watchdog.stop()
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


def _display_values(dialog):
    return tuple(
        dialog.table.item(row, 2).text()
        for row in range(dialog.table.rowCount()))


def _connect(window, *, identity=HASH_A, sequence=1):
    worker = _ConnectionWorker()
    window.worker = worker
    window._on_connected(_connection_info(
        sequence=sequence, identity=identity))
    assert window._connection_admitted is True
    return worker


def test_opening_floating_monitor_preserves_exact_eight_page_stack(
        window, qapp):
    window._nav_to(6)
    pages_before = tuple(
        window.stack.widget(index) for index in range(window.stack.count()))

    _open_dialog(window, qapp)

    assert window.stack.count() == 8
    assert window.stack.currentIndex() == 6
    assert window._TOOL_ID_TO_PAGE_INDEX["status"] == 6
    assert window._TOOL_ID_TO_PAGE_INDEX["system"] == 7
    assert window.stack.widget(6) is pages_before[6]
    assert window.stack.widget(7) is pages_before[7]
    assert tuple(
        window.stack.widget(index)
        for index in range(window.stack.count())) == pages_before


@pytest.mark.parametrize(
    "rejected",
    (
        {"sequence": 1},
        {"sequence": 2, "telemetry_valid": False},
    ),
    ids=("replayed-sequence", "ui-rejected-envelope"),
)
def test_replayed_or_rejected_sample_blanks_complete_monitor(
        window, qapp, rejected):
    dialog = _open_dialog(window, qapp)
    _connect(window, sequence=1)
    assert window.status_monitor_model.snapshot().current is True

    sequence = rejected["sequence"]
    overrides = {
        key: value for key, value in rejected.items() if key != "sequence"}
    window._on_telemetry(_telemetry(sequence, **overrides))
    qapp.processEvents()

    snapshot = window.status_monitor_model.snapshot()
    assert window._telemetry_authoritative is False
    assert snapshot.current is False
    assert snapshot.sequence is None
    assert all(line.value is None for line in snapshot.lines)
    assert set(_display_values(dialog)) == {
        app_main.StatusMonitorDialog._BLANK}
    assert dialog.lbl_state.text() == "NO CURRENT SAMPLE"


@pytest.mark.parametrize(
    "lifecycle",
    ("failed", "stopped", "new-connection-attempt"),
)
def test_terminal_or_replacement_lifecycle_ends_monitor_generation(
        window, qapp, monkeypatch, lifecycle):
    dialog = _open_dialog(window, qapp)
    _connect(window)
    assert window.status_monitor_model.active_generation == 1

    if lifecycle == "failed":
        window._on_failed("injected transport failure")
    elif lifecycle == "stopped":
        window._on_stopped()
    else:
        # DriveWorker construction is local; suppress QThread.start so no
        # serial transport can be opened by this replacement attempt.
        window.worker = None
        monkeypatch.setattr(app_main.DriveWorker, "start", lambda _self: None)
        window.cmb_port.setCurrentText("COM_TEST")
        window.connect_drive()
    qapp.processEvents()

    snapshot = window.status_monitor_model.snapshot()
    assert window.status_monitor_model.active_generation is None
    assert window.status_monitor_model.active_drive_identity is None
    assert snapshot.current is False
    assert snapshot.generation is None
    assert snapshot.drive_alias is None
    assert snapshot.sequence is None
    assert all(line.value is None for line in snapshot.lines)
    assert set(_display_values(dialog)) == {
        app_main.StatusMonitorDialog._BLANK}


def test_reconnect_generation_two_accepts_sequence_one(window, qapp):
    dialog = _open_dialog(window, qapp)
    _connect(window, identity=HASH_A, sequence=1)
    assert window.session_log.current_generation == 1

    window._on_stopped()
    _connect(window, identity=HASH_B, sequence=1)
    qapp.processEvents()

    snapshot = window.status_monitor_model.snapshot()
    assert window.session_log.current_generation == 2
    assert snapshot.current is True
    assert snapshot.generation == 2
    assert snapshot.sequence == 1
    assert snapshot.drive_alias != HASH_B
    assert _display_values(dialog) == ("123", "-4.5", "2", "0.125", "0")
    assert "GEN 2" in dialog.lbl_state.text()
    assert "SEQ 1" in dialog.lbl_state.text()


def test_late_old_worker_signal_cannot_change_current_monitor(
        window, qapp):
    old_worker = _OldWorker()
    old_worker.telemetry.connect(window._on_telemetry)
    _connect(window, identity=HASH_A, sequence=1)
    before = window.status_monitor_model.snapshot()

    old_worker.telemetry.emit(_telemetry(99, pos=999, iq=9.9, mo=1))
    qapp.processEvents()

    assert window.status_monitor_model.snapshot() is before
    assert window.status_monitor_model.snapshot().sequence == 1
    assert window.status_monitor_model.snapshot().lines[0].value == 123
    assert window._last_telemetry_sequence == 1
    assert window._last_mo == 0


def test_observer_error_blanks_then_next_valid_sample_recovers(
        window, qapp, monkeypatch):
    dialog = _open_dialog(window, qapp)
    _connect(window, sequence=1)
    original_observe = window.status_monitor_model.observe
    fail_once = {"pending": True}

    def flaky_observe(*args, **kwargs):
        if fail_once["pending"]:
            fail_once["pending"] = False
            raise RuntimeError("injected Status Monitor observer failure")
        return original_observe(*args, **kwargs)

    monkeypatch.setattr(window.status_monitor_model, "observe", flaky_observe)

    window._on_telemetry(_telemetry(2, pos=222, iq=0.2))
    qapp.processEvents()
    failed = window.status_monitor_model.snapshot()
    assert window._telemetry_authoritative is True
    assert window._last_telemetry_sequence == 2
    assert failed.current is False
    assert all(line.value is None for line in failed.lines)
    assert "OBSERVER ERROR" in dialog.lbl_state.text()

    window._on_telemetry(_telemetry(3, pos=333, iq=0.3))
    qapp.processEvents()
    recovered = window.status_monitor_model.snapshot()
    assert window._telemetry_authoritative is True
    assert window._last_telemetry_sequence == 3
    assert recovered.current is True
    assert recovered.sequence == 3
    assert recovered.lines[0].value == 333
    assert window._status_monitor_observer_error is False
    assert "CURRENT" in dialog.lbl_state.text()
    assert "SEQ 3" in dialog.lbl_state.text()


def test_activation_failure_stays_visible_after_core_accepts_initial_sample(
        window, qapp, monkeypatch):
    dialog = _open_dialog(window, qapp)

    def fail_activation(*_args, **_kwargs):
        raise RuntimeError("injected Status Monitor activation failure")

    monkeypatch.setattr(
        window.status_monitor_model, "activate_generation", fail_activation)
    _connect(window, sequence=1)
    qapp.processEvents()

    snapshot = window.status_monitor_model.snapshot()
    assert window._connection_admitted is True
    assert window._telemetry_authoritative is True
    assert window._last_telemetry_sequence == 1
    assert snapshot.current is False
    assert all(line.value is None for line in snapshot.lines)
    assert window._status_monitor_observer_error is True
    assert "OBSERVER ERROR" in dialog.lbl_state.text()
    assert set(_display_values(dialog)) == {
        app_main.StatusMonitorDialog._BLANK}


def test_render_failure_cannot_revoke_core_telemetry_or_motor_state(
        window, qapp, monkeypatch):
    dialog = _open_dialog(window, qapp)
    _connect(window, sequence=1)

    def fail_render(*_args, **_kwargs):
        raise RuntimeError("injected Status Monitor render failure")

    monkeypatch.setattr(dialog, "render", fail_render)
    window._on_telemetry(_telemetry(2, pos=888, iq=0.75, mo=1))
    qapp.processEvents()

    snapshot = window.status_monitor_model.snapshot()
    assert window._connection_admitted is True
    assert window._telemetry_authoritative is True
    assert window._last_telemetry_sequence == 2
    assert window._last_mo == 1
    assert window.m_pos.text() == "888"
    assert window.lbl_motor.text() == "MOTOR ENABLED"
    # The passive projection may blank itself on a renderer failure, but that
    # local fail-closed response must not roll back the already-applied core.
    assert snapshot.current is False
    assert all(line.value is None for line in snapshot.lines)
    assert window._status_monitor_observer_error is True
    assert "OBSERVER ERROR" in dialog.lbl_state.text()
    assert set(_display_values(dialog)) == {
        app_main.StatusMonitorDialog._BLANK}


def test_config_edit_render_failure_is_contained_inside_qt_slot(
        window, qapp, monkeypatch):
    dialog = _open_dialog(window, qapp)
    _connect(window, sequence=1)
    uncaught = []

    def fail_render(*_args, **_kwargs):
        raise RuntimeError("injected config-render failure")

    monkeypatch.setattr(dialog, "render", fail_render)
    monkeypatch.setattr(
        sys, "excepthook",
        lambda exc_type, value, traceback: uncaught.append(
            (exc_type, value, traceback)))

    dialog.btn_reset.click()
    qapp.processEvents()

    assert uncaught == []
    assert window._connection_admitted is True
    assert window._telemetry_authoritative is True
    assert window._last_telemetry_sequence == 1
    assert window._last_mo == 0
    assert window.status_monitor_model.snapshot().current is False
    assert set(_display_values(dialog)) == {
        app_main.StatusMonitorDialog._BLANK}
    assert "OBSERVER ERROR" in dialog.lbl_state.text()


def _dialog_visible_strings(dialog):
    """Collect user-visible text and tooltip-like metadata from the dialog."""
    strings = []
    widgets = (dialog, *dialog.findChildren(QtWidgets.QWidget))
    for widget in widgets:
        for accessor in (
                "windowTitle", "toolTip", "statusTip", "whatsThis",
                "accessibleName", "accessibleDescription"):
            value = getattr(widget, accessor)()
            if value:
                strings.append(value)
        if isinstance(widget, (QtWidgets.QLabel,
                               QtWidgets.QAbstractButton)):
            strings.append(widget.text())
        if isinstance(widget, QtWidgets.QComboBox):
            strings.extend(
                widget.itemText(index) for index in range(widget.count()))
        if isinstance(widget, QtWidgets.QTableWidget):
            items = []
            for row in range(widget.rowCount()):
                for column in range(widget.columnCount()):
                    items.append(widget.item(row, column))
            items.extend(
                widget.horizontalHeaderItem(column)
                for column in range(widget.columnCount()))
            items.extend(
                widget.verticalHeaderItem(row)
                for row in range(widget.rowCount()))
            for item in (item for item in items if item is not None):
                strings.extend((
                    item.text(), item.toolTip(), item.statusTip(),
                    item.whatsThis(),
                    item.data(QtCore.Qt.ItemDataRole.AccessibleTextRole),
                    item.data(
                        QtCore.Qt.ItemDataRole.AccessibleDescriptionRole)))
    return tuple(value for value in strings if value)


def test_exact_hashed_identity_is_absent_from_dialog_text_and_tooltips(
        window, qapp):
    _connect(window, identity=HASH_A, sequence=1)
    dialog = _open_dialog(window, qapp)

    visible = _dialog_visible_strings(dialog)
    joined = "\n".join(visible)
    assert HASH_A not in joined
    assert HASH_A.split(":", 1)[1] not in joined
    assert all(
        dialog.table.item(row, 0).text() == "Drive01"
        for row in range(dialog.table.rowCount()))
