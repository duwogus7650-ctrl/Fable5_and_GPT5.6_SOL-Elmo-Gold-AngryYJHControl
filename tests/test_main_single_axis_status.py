"""Offline UI contracts for Single Axis Safety Snapshot v1."""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

import main as app_main
import theme as amber_theme
import theme_angrybirds
import theme_qdd


class _AxisWorker(QtCore.QObject):
    axis_summary = QtCore.pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.running = True

    def isRunning(self):
        return self.running

    def __getattr__(self, name):
        def forbidden(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            raise AssertionError(
                "Single Axis status projection issued worker I/O: %s" % name)
        return forbidden


def _summary(**updates):
    raw = {
        "MO": 0,
        "SO": 0,
        "MF": 0,
        "PS": -2,
        "SR": (1 << 14) | (1 << 15),
        "MS": 3,
    }
    raw.update(updates)
    return {
        "scope": "Single Axis (application scope)",
        "mode": "Position (UM=5)",
        "feedback_routing": "same socket routing (0)",
        "raw": raw,
        "errors": {},
        "write_supported": False,
    }


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def ui(qapp, monkeypatch):
    monkeypatch.setattr(app_main, "list_serial_ports", lambda: ["COM_TEST"])
    win = app_main.MainWindow()
    worker = _AxisWorker()
    win.worker = worker
    win._connection_admitted = True
    win._ui_connected = True
    win._telemetry_authoritative = True
    win._connection_shutdown_pending = False
    worker.axis_summary.connect(win._on_axis_summary)
    yield SimpleNamespace(win=win, worker=worker)
    win.worker = None
    win.close()
    qapp.processEvents()


def test_snapshot_card_starts_unknown_and_names_its_evidence_boundary(ui):
    assert ui.win.lbl_axis_safety_state.text() == "UNKNOWN"
    contract = ui.win.lbl_axis_safety_contract.text()
    assert "DRIVE-REPORTED" in contract
    assert "MODEL" in contract
    assert "NOT STO TEST EVIDENCE" in contract
    assert all(
        widget.text() == "—"
        for widget in ui.win.axis_safety_fields.values())


def test_axis_summary_scroll_uses_theme_background_instead_of_platform_white(
        ui):
    expected = QtGui.QColor(app_main.theme.CARD)

    assert ui.win.axis_summary_scroll.viewport().autoFillBackground()
    assert ui.win.axis_summary_body.autoFillBackground()
    assert ui.win.axis_summary_scroll.viewport().palette().color(
        QtGui.QPalette.ColorRole.Window) == expected
    assert ui.win.axis_summary_body.palette().color(
        QtGui.QPalette.ColorRole.Window) == expected


def test_safety_evidence_boundary_is_not_clipped_at_1366x820_in_any_skin(
        ui, qapp):
    ui.win.resize(1366, 820)
    ui.win.show()
    ui.win._nav_to(4)
    ui.worker.axis_summary.emit(_summary())
    try:
        for themed in (theme_qdd, amber_theme, theme_angrybirds):
            qapp.setStyleSheet(themed.STYLE)
            ui.win.resize(1366, 820)
            for _ in range(3):
                qapp.processEvents()

            assert ui.win.lbl_axis_safety_contract.height() >= (
                ui.win.lbl_axis_safety_contract.sizeHint().height())
            assert ui.win.lbl_axis_safety_detail.height() >= (
                ui.win.lbl_axis_safety_detail.sizeHint().height())
            assert (
                ui.win.workspace_scroll.horizontalScrollBar().maximum() == 0)
    finally:
        qapp.setStyleSheet(app_main.theme.STYLE)


def test_current_worker_snapshot_updates_read_only_fields_without_new_io(ui):
    authority_before = (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win.btn_motion_run.isEnabled(),
    )

    ui.worker.axis_summary.emit(_summary())

    assert ui.win.lbl_axis_safety_state.text() == "CURRENT · MODEL"
    assert ui.win.axis_safety_fields["mo_so"].text() == "MO=0 · SO=0"
    assert "MF=0" in ui.win.axis_safety_fields["fault_amp"].text()
    assert "SR[3:0]=0x0" in ui.win.axis_safety_fields["fault_amp"].text()
    assert ui.win.axis_safety_fields["servo"].text() == "SR4=0"
    assert ui.win.axis_safety_fields["sto"].text() == "SR14=1 · SR15=1"
    assert ui.win.axis_safety_fields["program_limit"].text() == (
        "PS=-2 · SR12=0 · SR13=0")
    assert ui.win.axis_safety_fields["profiler"].text() == (
        "MS=3 · SR[11:8]=0")
    assert ui.worker.calls == []
    assert (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win.btn_motion_run.isEnabled(),
    ) == authority_before


def test_invalid_snapshot_blanks_every_semantic_field(ui):
    ui.worker.axis_summary.emit(_summary(SR=True))

    assert ui.win.lbl_axis_safety_state.text() == "UNKNOWN"
    assert all(
        widget.text() == "—"
        for widget in ui.win.axis_safety_fields.values())
    assert "SR" in ui.win.lbl_axis_safety_detail.text()


def test_redundant_readback_conflict_is_not_presented_as_current_authority(ui):
    ui.worker.axis_summary.emit(_summary(SO=1))

    assert ui.win.lbl_axis_safety_state.text() == (
        "INCONSISTENT · AUTHORITY UNKNOWN")
    assert "SO=1" in ui.win.lbl_axis_safety_detail.text()
    assert "SR4=0" in ui.win.lbl_axis_safety_detail.text()
    combined = " ".join(
        (ui.win.lbl_axis_safety_state.text(),
         ui.win.lbl_axis_safety_contract.text(),
         ui.win.lbl_axis_safety_detail.text(),
         *(widget.text() for widget in ui.win.axis_safety_fields.values())))
    assert "GREEN" not in combined.upper()
    assert "SAFE" not in combined.upper()


def test_old_worker_and_shutdown_pending_signal_cannot_repopulate_snapshot(
        ui):
    ui.worker.axis_summary.emit(_summary())
    assert ui.win.lbl_axis_safety_state.text() == "CURRENT · MODEL"

    old_worker = _AxisWorker()
    old_worker.axis_summary.connect(ui.win._on_axis_summary)
    old_worker.axis_summary.emit(_summary(MF=9))
    assert "MF=0" in ui.win.axis_safety_fields["fault_amp"].text()

    ui.win._begin_connection_shutdown("offline lifecycle test")
    assert ui.win.lbl_axis_safety_state.text() == "UNKNOWN"
    assert all(
        widget.text() == "—"
        for widget in ui.win.axis_safety_fields.values())

    ui.worker.axis_summary.emit(_summary())
    assert ui.win.lbl_axis_safety_state.text() == "UNKNOWN"
    assert all(
        widget.text() == "—"
        for widget in ui.win.axis_safety_fields.values())


def test_disconnect_reset_does_not_leave_stale_sto_or_servo_projection(ui):
    ui.worker.axis_summary.emit(_summary(SO=1, SR=(
        (1 << 4) | (1 << 14) | (1 << 15))))
    assert ui.win.axis_safety_fields["servo"].text() == "SR4=1"

    ui.win._set_connected_ui(False)

    assert ui.win.lbl_axis_safety_state.text() == "UNKNOWN"
    assert ui.win.axis_safety_fields["servo"].text() == "—"
    assert ui.win.axis_safety_fields["sto"].text() == "—"


def test_energizing_authority_revocation_blanks_and_rejects_late_snapshot(ui):
    ui.worker.axis_summary.emit(_summary())
    assert ui.win.lbl_axis_safety_state.text() == "CURRENT · MODEL"
    ui.win._motion_config_unknown = False

    ui.win._revoke_telemetry_authority(
        "offline energizing lifecycle regression", energizing=True)

    assert ui.win.lbl_axis_safety_state.text() == "UNKNOWN"
    assert all(
        widget.text() == "—"
        for widget in ui.win.axis_safety_fields.values())
    assert ui.win._telemetry_authoritative is False
    assert ui.win._energizing_state is True

    # A queued summary from before authority revocation is not fresh evidence.
    configuration_unknown = _summary()
    configuration_unknown["motion_config_unknown"] = True
    ui.worker.axis_summary.emit(configuration_unknown)
    assert ui.win.lbl_axis_safety_state.text() == "UNKNOWN"
    assert all(
        widget.text() == "—"
        for widget in ui.win.axis_safety_fields.values())
    # The same current-worker message still carries a fail-safe configuration
    # latch which must not be discarded with the stale safety projection.
    assert ui.win._motion_config_unknown is True

    # Recovery requires both renewed telemetry authority and a later snapshot.
    ui.win._telemetry_authoritative = True
    ui.win._energizing_state = False
    ui.worker.axis_summary.emit(_summary())
    assert ui.win.lbl_axis_safety_state.text() == "CURRENT · MODEL"
