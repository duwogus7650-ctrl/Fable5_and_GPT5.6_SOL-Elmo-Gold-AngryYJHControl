"""Offline UI contracts for Single Axis Safety Snapshot v1."""

from __future__ import annotations

from dataclasses import replace
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

import main as app_main
import single_axis_current_reference
import single_axis_drive_mode
import single_axis_digital_inputs
import single_axis_digital_outputs
import single_axis_position_velocity_reference
import theme as amber_theme
import theme_angrybirds
import theme_qdd


class _AxisWorker(QtCore.QObject):
    axis_summary = QtCore.pyqtSignal(dict)
    axis_current_reference = QtCore.pyqtSignal(object)
    axis_position_velocity_reference = QtCore.pyqtSignal(object)
    axis_drive_mode = QtCore.pyqtSignal(object)
    axis_digital_inputs = QtCore.pyqtSignal(object)
    axis_digital_outputs = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.running = True

    def isRunning(self):
        return self.running

    def refresh_axis_digital_inputs(self):
        self.calls.append(("refresh_axis_digital_inputs", (), {}))

    def refresh_axis_digital_outputs(self):
        self.calls.append(("refresh_axis_digital_outputs", (), {}))

    def refresh_axis_drive_mode(self):
        self.calls.append(("refresh_axis_drive_mode", (), {}))

    def refresh_axis_current_reference(self):
        self.calls.append(("refresh_axis_current_reference", (), {}))

    def refresh_axis_position_velocity_reference(self):
        self.calls.append(
            ("refresh_axis_position_velocity_reference", (), {}))

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
    worker.axis_current_reference.connect(win._on_axis_current_reference)
    worker.axis_position_velocity_reference.connect(
        win._on_axis_position_velocity_reference)
    worker.axis_drive_mode.connect(win._on_axis_drive_mode)
    worker.axis_digital_inputs.connect(win._on_axis_digital_inputs)
    worker.axis_digital_outputs.connect(win._on_axis_digital_outputs)
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


def test_enable_contract_starts_unknown_with_enable_locked(ui):
    assert ui.win.lbl_axis_enable_state.text() == "UNKNOWN - ENABLE LOCKED"
    assert ui.win.btn_axis_enable_locked.text() == (
        "Enable - LOCKED / NEED-DATA (MO=1)")
    assert ui.win.btn_axis_enable_locked.isEnabled() is False
    assert (
        ui.win.btn_axis_enable_locked.property("operationId")
        == "motor.enable"
    )
    rendered = " ".join((
        ui.win.lbl_axis_enable_contract.text(),
        ui.win.lbl_axis_enable_detail.text(),
        ui.win.lbl_axis_disable_route.text(),
    )).upper()
    for phrase in (
            "DRIVE-REPORTED",
            "NOT STO TEST EVIDENCE",
            "ENABLE REMAINS LOCKED",
            "STOP + DISABLE",
            "ST",
            "MO=0",
            "TERMINAL READBACK",
            "NOT INDEPENDENT STO/E-STOP"):
        assert phrase in rendered


@pytest.mark.parametrize(
    ("summary", "expected_state", "detail_phrase"),
    (
        (
            _summary(MO=0, SO=0),
            "DISABLED REPORTED - ENABLE LOCKED",
            "MO=0 / SO=0",
        ),
        (
            _summary(MO=1, SO=0),
            "ENABLE REQUESTED - SO=0 / REFERENCES BLOCKED",
            "wait for SO=1",
        ),
        (
            _summary(
                MO=1,
                SO=1,
                SR=(1 << 4) | (1 << 14) | (1 << 15)),
            "ENABLED REPORTED - ENERGIZED",
            "STOP remains available",
        ),
        (
            _summary(
                MO=0,
                SO=1,
                SR=(1 << 4) | (1 << 14) | (1 << 15)),
            "DISABLING / BRAKE HOLD - SO=1",
            "brake",
        ),
        (
            _summary(MO=0, SO=0, MF=9),
            "FAULT REPORTED - NO AUTO-RETRY",
            "inspect",
        ),
    ),
)
def test_enable_contract_renders_documented_state_without_worker_io(
        ui, qapp, summary, expected_state, detail_phrase):
    authority_before = (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
    )

    ui.worker.axis_summary.emit(summary)
    qapp.processEvents()

    assert ui.win.lbl_axis_enable_state.text() == expected_state
    assert detail_phrase.lower() in (
        ui.win.lbl_axis_enable_detail.text().lower())
    assert ui.win.btn_axis_enable_locked.isEnabled() is False
    assert tuple(ui.worker.calls) == ()
    assert ui.win.btn_motion_stop.isEnabled() is True
    assert (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
    ) == authority_before


def test_clicking_locked_enable_cannot_dispatch_mo1(ui, qapp):
    ui.worker.axis_summary.emit(_summary(MO=0, SO=0))
    qapp.processEvents()

    ui.win.btn_axis_enable_locked.click()
    qapp.processEvents()

    assert ui.win.btn_axis_enable_locked.isEnabled() is False
    assert tuple(ui.worker.calls) == ()


def test_enable_contract_blanks_on_authority_loss_and_rejects_late_summary(
        ui, qapp):
    ui.worker.axis_summary.emit(_summary(MO=0, SO=0))
    qapp.processEvents()
    assert ui.win.lbl_axis_enable_state.text() == (
        "DISABLED REPORTED - ENABLE LOCKED")

    ui.win._revoke_telemetry_authority("offline authority loss")
    assert ui.win.lbl_axis_enable_state.text() == "UNKNOWN - ENABLE LOCKED"

    ui.worker.axis_summary.emit(_summary(MO=1, SO=1, SR=(
        (1 << 4) | (1 << 14) | (1 << 15))))
    qapp.processEvents()
    assert ui.win.lbl_axis_enable_state.text() == "UNKNOWN - ENABLE LOCKED"


def _digital_input_snapshot(**updates):
    raw = {"IP": (1 << 16) | (1 << 20)}
    raw.update({"IL[%d]" % index: 7 for index in range(1, 7)})
    raw.update({"IF[%d]" % index: 0.25 * index for index in range(1, 7)})
    raw.update(updates)
    return single_axis_digital_inputs.decode_digital_input_snapshot(
        raw, sample_duration_s=0.125)


def _digital_output_snapshot(**updates):
    raw = {
        "OP": (1 << 0) | (1 << 3),
        "OL[1]": 1,
        "OL[2]": 4,
        "OL[3]": 7,
        "OL[4]": 11,
        "GO[1]": 0,
        "GO[2]": 1,
        "GO[3]": 2,
        "GO[4]": 7,
    }
    raw.update(updates)
    return single_axis_digital_outputs.decode_digital_output_snapshot(
        raw, sample_duration_s=0.075)


def _drive_mode_snapshot(value=5, *, duration=0.05):
    return single_axis_drive_mode.decode_drive_mode_snapshot(
        {"UM": value}, sample_duration_s=duration)


def _current_reference_snapshot(*, duration=0.08):
    sr = (1 << 14) | (1 << 15)
    return single_axis_current_reference.decode_current_reference_snapshot(
        {
            "MO_PRE": 0,
            "SO_PRE": 0,
            "MF_PRE": 0,
            "SR_PRE": sr,
            "UM": 5,
            "TC": 0.0,
            "IQ": 0.0,
            "ID": 0.0,
            "CL[1]": 2.0,
            "PL[1]": 4.0,
            "LC": 0,
            "MC": 5.0,
            "MO_POST": 0,
            "SO_POST": 0,
            "MF_POST": 0,
            "SR_POST": sr,
        },
        sample_duration_s=duration,
    )


def _position_velocity_snapshot(*, duration=0.09):
    sr = (1 << 14) | (1 << 15)
    return (
        single_axis_position_velocity_reference
        .decode_position_velocity_snapshot(
            {
                "MO_PRE": 0,
                "SO_PRE": 0,
                "MF_PRE": 0,
                "SR_PRE": sr,
                "UM": 5,
                "PA[1]": 12000,
                "PR[1]": -500,
                "JV": 2500,
                "SP[1]": 10000,
                "AC[1]": 20000,
                "DC": 18000,
                "SD": 15000,
                "PX": 11500,
                "VX": 12.5,
                "MO_POST": 0,
                "SO_POST": 0,
                "MF_POST": 0,
                "SR_POST": sr,
            },
            sample_duration_s=duration,
        ))


def test_digital_input_panel_starts_unknown_and_exposes_no_write_surface(ui):
    assert ui.win.lbl_axis_digital_inputs_state.text() == "UNKNOWN"
    assert ui.win.axis_digital_inputs_table.rowCount() == 6
    assert all(
        ui.win.axis_digital_inputs_table.item(row, column).text() == "—"
        for row in range(6)
        for column in range(1, 5))
    contract = ui.win.lbl_axis_digital_inputs_contract.text().upper()
    for phrase in (
            "IP + IL[1..6] + IF[1..6]",
            "INPUTS 1..6 ONLY",
            "NOT PHYSICAL PIN VOLTAGE",
            "NOT STO/E-STOP EVIDENCE",
            "NO OUTPUT WRITE"):
        assert phrase in contract
    assert ui.win.axis_digital_inputs_frame.findChildren(
        QtWidgets.QCheckBox) == []
    assert ui.win.axis_digital_inputs_frame.findChildren(
        QtWidgets.QLineEdit) == []
    assert tuple(
        button.text()
        for button in ui.win.axis_digital_inputs_frame.findChildren(
            QtWidgets.QPushButton)
    ) == ("Refresh Digital Inputs · READ ONLY",)
    assert ui.win.btn_axis_digital_inputs_refresh.property(
        "operationId") == "axis.digital_inputs.refresh"


def test_current_digital_input_snapshot_renders_without_changing_authority(
        ui, qapp):
    before = (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
        tuple(ui.worker.calls),
    )

    ui.worker.axis_digital_inputs.emit(_digital_input_snapshot())
    qapp.processEvents()

    assert ui.win.lbl_axis_digital_inputs_state.text() == (
        "CURRENT · DRIVE READ ONLY")
    assert ui.win.axis_digital_inputs_table.item(0, 0).text() == "Input 1"
    assert ui.win.axis_digital_inputs_table.item(0, 1).text() == (
        "ACTIVE · DRIVE LOGICAL")
    assert ui.win.axis_digital_inputs_table.item(1, 1).text() == (
        "INACTIVE · DRIVE LOGICAL")
    assert ui.win.axis_digital_inputs_table.item(4, 1).text() == (
        "ACTIVE · DRIVE LOGICAL")
    assert ui.win.axis_digital_inputs_table.item(0, 2).text() == (
        "General purpose")
    assert ui.win.axis_digital_inputs_table.item(0, 3).text() == (
        "ACTIVE_HIGH · non-sticky")
    assert ui.win.axis_digital_inputs_table.item(0, 4).text() == "0.250 ms"
    assert "125.0 ms" in ui.win.lbl_axis_digital_inputs_detail.text()
    assert (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
        tuple(ui.worker.calls),
    ) == before


def test_digital_input_refresh_queues_one_typed_read_job(ui, qapp):
    ui.win.btn_axis_digital_inputs_refresh.setEnabled(True)
    ui.win.btn_axis_digital_inputs_refresh.click()
    qapp.processEvents()

    assert ui.worker.calls == [
        ("refresh_axis_digital_inputs", (), {}),
    ]
    assert ui.win.lbl_axis_digital_inputs_state.text() == "READING"
    assert all(
        ui.win.axis_digital_inputs_table.item(row, column).text() == "—"
        for row in range(6)
        for column in range(1, 5))


def test_invalid_late_or_disconnected_digital_input_snapshot_stays_unknown(
        ui, qapp):
    ui.worker.axis_digital_inputs.emit(_digital_input_snapshot())
    qapp.processEvents()
    assert ui.win.lbl_axis_digital_inputs_state.text() == (
        "CURRENT · DRIVE READ ONLY")

    ui.win._telemetry_authoritative = False
    ui.worker.axis_digital_inputs.emit(_digital_input_snapshot())
    qapp.processEvents()
    assert ui.win.lbl_axis_digital_inputs_state.text() == "UNKNOWN"

    ui.win._telemetry_authoritative = True
    ui.worker.axis_digital_inputs.emit(_digital_input_snapshot())
    qapp.processEvents()
    ui.win._set_connected_ui(False)
    assert ui.win.lbl_axis_digital_inputs_state.text() == "UNKNOWN"
    assert all(
        ui.win.axis_digital_inputs_table.item(row, column).text() == "—"
        for row in range(6)
        for column in range(1, 5))


def test_structurally_forged_current_digital_input_snapshot_fails_closed(
        ui, qapp):
    valid = _digital_input_snapshot()
    forged = replace(valid, inputs=valid.inputs[:-1])

    ui.worker.axis_digital_inputs.emit(forged)
    qapp.processEvents()

    assert ui.win.lbl_axis_digital_inputs_state.text() == "UNKNOWN"
    assert all(
        ui.win.axis_digital_inputs_table.item(row, column).text() == "—"
        for row in range(6)
        for column in range(1, 5))


def test_worker_queues_exact_digital_input_read_job():
    worker = app_main.DriveWorker("COM_TEST", query_only=True)

    worker.refresh_axis_digital_inputs()

    assert worker._jobs == app_main.collections.deque((
        ("axis_digital_inputs_read", None),
    ))


def test_worker_emits_only_the_typed_digital_input_snapshot(monkeypatch):
    worker = app_main.DriveWorker("COM_TEST", query_only=True)
    expected = _digital_input_snapshot()
    calls = []
    observed = []
    monkeypatch.setattr(
        app_main.single_axis_digital_inputs,
        "read_digital_input_snapshot",
        lambda link: calls.append(link) or expected)
    worker.axis_digital_inputs.connect(observed.append)
    link = object()

    worker._emit_axis_digital_inputs(link)

    assert calls == [link]
    assert observed == [expected]


def test_digital_output_panel_starts_unknown_and_exposes_no_write_surface(ui):
    assert ui.win.lbl_axis_digital_outputs_state.text() == "UNKNOWN"
    assert ui.win.axis_digital_outputs_table.rowCount() == 4
    assert all(
        ui.win.axis_digital_outputs_table.item(row, column).text() == "—"
        for row in range(4)
        for column in range(1, 5))
    contract = ui.win.lbl_axis_digital_outputs_contract.text().upper()
    for phrase in (
            "OP + OL[1..4] + GO[1..4]",
            "OUTPUTS 1..4 ONLY",
            "NOT PHYSICAL PIN",
            "NOT STO TEST EVIDENCE",
            "NO OUTPUT WRITE",
            "NO OUTPUT ACTUATION"):
        assert phrase in contract
    assert ui.win.axis_digital_outputs_frame.findChildren(
        QtWidgets.QCheckBox) == []
    assert ui.win.axis_digital_outputs_frame.findChildren(
        QtWidgets.QLineEdit) == []
    assert tuple(
        button.text()
        for button in ui.win.axis_digital_outputs_frame.findChildren(
            QtWidgets.QPushButton)
    ) == ("Refresh Digital Outputs · READ ONLY",)
    assert ui.win.btn_axis_digital_outputs_refresh.property(
        "operationId") == "axis.digital_outputs.refresh"


def test_current_digital_output_snapshot_renders_without_changing_authority(
        ui, qapp):
    before = (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
        tuple(ui.worker.calls),
    )

    ui.worker.axis_digital_outputs.emit(_digital_output_snapshot())
    qapp.processEvents()

    assert ui.win.lbl_axis_digital_outputs_state.text() == (
        "CURRENT · DRIVE READ ONLY")
    assert ui.win.axis_digital_outputs_table.item(0, 0).text() == (
        "Output 1 · 5 V logic")
    assert ui.win.axis_digital_outputs_table.item(2, 0).text() == (
        "Output 3 · 3.3 V logic")
    assert ui.win.axis_digital_outputs_table.item(0, 1).text() == (
        "ACTIVE · DRIVE LOGICAL ACTIVATION")
    assert ui.win.axis_digital_outputs_table.item(1, 1).text() == (
        "INACTIVE · DRIVE LOGICAL ACTIVATION")
    assert ui.win.axis_digital_outputs_table.item(0, 2).text() == (
        "General purpose")
    assert ui.win.axis_digital_outputs_table.item(1, 3).text() == "ACTIVE_LOW"
    assert ui.win.axis_digital_outputs_table.item(3, 4).text() == (
        "STO status indication · NOT STO TEST")
    assert "75.0 ms" in ui.win.lbl_axis_digital_outputs_detail.text()
    assert "PHYSICAL LEVEL UNVERIFIED" in (
        ui.win.lbl_axis_digital_outputs_detail.text().upper())
    assert (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
        tuple(ui.worker.calls),
    ) == before


def test_digital_output_refresh_queues_one_typed_read_job(ui, qapp):
    ui.win.btn_axis_digital_outputs_refresh.setEnabled(True)
    ui.win.btn_axis_digital_outputs_refresh.click()
    qapp.processEvents()

    assert ui.worker.calls == [
        ("refresh_axis_digital_outputs", (), {}),
    ]
    assert ui.win.lbl_axis_digital_outputs_state.text() == "READING"
    assert all(
        ui.win.axis_digital_outputs_table.item(row, column).text() == "—"
        for row in range(4)
        for column in range(1, 5))


def test_invalid_late_or_disconnected_digital_output_snapshot_stays_unknown(
        ui, qapp):
    ui.worker.axis_digital_outputs.emit(_digital_output_snapshot())
    qapp.processEvents()
    assert ui.win.lbl_axis_digital_outputs_state.text() == (
        "CURRENT · DRIVE READ ONLY")

    ui.win._telemetry_authoritative = False
    ui.worker.axis_digital_outputs.emit(_digital_output_snapshot())
    qapp.processEvents()
    assert ui.win.lbl_axis_digital_outputs_state.text() == "UNKNOWN"

    ui.win._telemetry_authoritative = True
    ui.worker.axis_digital_outputs.emit(_digital_output_snapshot())
    qapp.processEvents()
    ui.win._set_connected_ui(False)
    assert ui.win.lbl_axis_digital_outputs_state.text() == "UNKNOWN"
    assert all(
        ui.win.axis_digital_outputs_table.item(row, column).text() == "—"
        for row in range(4)
        for column in range(1, 5))


def test_structurally_forged_current_digital_output_snapshot_fails_closed(
        ui, qapp):
    valid = _digital_output_snapshot()
    forged = replace(valid, outputs=valid.outputs[:-1])

    ui.worker.axis_digital_outputs.emit(forged)
    qapp.processEvents()

    assert ui.win.lbl_axis_digital_outputs_state.text() == "UNKNOWN"
    assert all(
        ui.win.axis_digital_outputs_table.item(row, column).text() == "—"
        for row in range(4)
        for column in range(1, 5))


def test_worker_queues_exact_digital_output_read_job():
    worker = app_main.DriveWorker("COM_TEST", query_only=True)

    worker.refresh_axis_digital_outputs()

    assert worker._jobs == app_main.collections.deque((
        ("axis_digital_outputs_read", None),
    ))


def test_worker_emits_only_the_typed_digital_output_snapshot(monkeypatch):
    worker = app_main.DriveWorker("COM_TEST", query_only=True)
    expected = _digital_output_snapshot()
    calls = []
    observed = []
    monkeypatch.setattr(
        app_main.single_axis_digital_outputs,
        "read_digital_output_snapshot",
        lambda link: calls.append(link) or expected)
    worker.axis_digital_outputs.connect(observed.append)
    link = object()

    worker._emit_axis_digital_outputs(link)

    assert calls == [link]
    assert observed == [expected]


def test_drive_mode_panel_starts_unknown_and_exposes_no_change_surface(ui):
    assert ui.win.lbl_axis_drive_mode_state.text() == "UNKNOWN"
    assert ui.win.lbl_axis_drive_mode_value.text() == "—"
    assert ui.win.axis_drive_mode_table.rowCount() == 5
    assert tuple(
        ui.win.axis_drive_mode_table.item(row, 0).text()
        for row in range(5)
    ) == ("UM=1", "UM=2", "UM=3", "UM=5", "UM=6")
    contract = ui.win.lbl_axis_drive_mode_contract.text().upper()
    for phrase in (
            "UM QUERY ONLY",
            "NO UM ASSIGNMENT",
            "NO MODE CHANGE",
            "MOTOR MUST BE OFF",
            "NON-VOLATILE",
            "NEED-DATA"):
        assert phrase in contract
    for widget_type in (
            QtWidgets.QComboBox,
            QtWidgets.QSpinBox,
            QtWidgets.QDoubleSpinBox,
            QtWidgets.QCheckBox,
            QtWidgets.QLineEdit):
        assert ui.win.axis_drive_mode_frame.findChildren(widget_type) == []
    assert tuple(
        button.text()
        for button in ui.win.axis_drive_mode_frame.findChildren(
            QtWidgets.QPushButton)
    ) == ("Refresh Drive Mode · READ ONLY",)
    assert ui.win.btn_axis_drive_mode_refresh.property(
        "operationId") == "axis.drive_mode.refresh"


def test_current_drive_mode_snapshot_renders_without_changing_authority(
        ui, qapp):
    before = (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
        tuple(ui.worker.calls),
    )

    ui.worker.axis_drive_mode.emit(_drive_mode_snapshot())
    qapp.processEvents()

    assert ui.win.lbl_axis_drive_mode_state.text() == (
        "CURRENT · DRIVE READ ONLY")
    assert ui.win.lbl_axis_drive_mode_value.text() == "UM=5 · Position"
    assert "PA / PR" in ui.win.lbl_axis_drive_mode_reference.text()
    assert ui.win.axis_drive_mode_table.item(3, 0).data(
        QtCore.Qt.ItemDataRole.UserRole) == "CURRENT"
    assert "50.0 ms" in ui.win.lbl_axis_drive_mode_detail.text()
    assert "NO MODE CHANGE" in ui.win.lbl_axis_drive_mode_detail.text().upper()
    assert (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
        tuple(ui.worker.calls),
    ) == before


def test_drive_mode_refresh_queues_one_typed_read_job(ui, qapp):
    ui.win.btn_axis_drive_mode_refresh.setEnabled(True)
    ui.win.btn_axis_drive_mode_refresh.click()
    qapp.processEvents()

    assert ui.worker.calls == [
        ("refresh_axis_drive_mode", (), {}),
    ]
    assert ui.win.lbl_axis_drive_mode_state.text() == "READING"
    assert ui.win.lbl_axis_drive_mode_value.text() == "—"


def test_invalid_late_or_disconnected_drive_mode_snapshot_stays_unknown(
        ui, qapp):
    ui.worker.axis_drive_mode.emit(_drive_mode_snapshot())
    qapp.processEvents()
    assert ui.win.lbl_axis_drive_mode_state.text() == (
        "CURRENT · DRIVE READ ONLY")

    ui.win._telemetry_authoritative = False
    ui.worker.axis_drive_mode.emit(_drive_mode_snapshot())
    qapp.processEvents()
    assert ui.win.lbl_axis_drive_mode_state.text() == "UNKNOWN"

    ui.win._telemetry_authoritative = True
    ui.worker.axis_drive_mode.emit(_drive_mode_snapshot())
    qapp.processEvents()
    ui.win._set_connected_ui(False)
    assert ui.win.lbl_axis_drive_mode_state.text() == "UNKNOWN"
    assert ui.win.lbl_axis_drive_mode_value.text() == "—"


def test_structurally_forged_current_drive_mode_snapshot_fails_closed(
        ui, qapp):
    valid = _drive_mode_snapshot()
    forged = replace(valid, evidence_label="FORGED")

    ui.worker.axis_drive_mode.emit(forged)
    qapp.processEvents()

    assert ui.win.lbl_axis_drive_mode_state.text() == "UNKNOWN"
    assert ui.win.lbl_axis_drive_mode_value.text() == "—"


def test_worker_queues_exact_drive_mode_read_job():
    worker = app_main.DriveWorker("COM_TEST", query_only=True)

    worker.refresh_axis_drive_mode()

    assert worker._jobs == app_main.collections.deque((
        ("axis_drive_mode_read", None),
    ))


def test_worker_emits_only_the_typed_drive_mode_snapshot(monkeypatch):
    worker = app_main.DriveWorker("COM_TEST", query_only=True)
    expected = _drive_mode_snapshot()
    calls = []
    observed = []
    monkeypatch.setattr(
        app_main.single_axis_drive_mode,
        "read_drive_mode_snapshot",
        lambda link: calls.append(link) or expected)
    worker.axis_drive_mode.connect(observed.append)
    link = object()

    worker._emit_axis_drive_mode(link)

    assert calls == [link]
    assert observed == [expected]


def test_current_reference_panel_starts_unknown_and_has_no_command_surface(ui):
    assert ui.win.lbl_axis_current_reference_state.text() == "UNKNOWN"
    assert ui.win.lbl_axis_current_reference_title.text() == (
        "DRIVE CURRENT READBACK · NOT EAS CURRENT COMMAND UI")
    assert ui.win.axis_current_reference_table.rowCount() == 7
    assert tuple(
        ui.win.axis_current_reference_table.item(row, 0).text()
        for row in range(7)
    ) == ("TC", "IQ", "ID", "CL[1]", "PL[1]", "LC", "MC")
    contract = ui.win.lbl_axis_current_reference_contract.text().upper()
    for phrase in (
            "QUERY ONLY",
            "NO TC ASSIGNMENT",
            "NO LOOP CHANGE",
            "COMMAND LOCKED",
            "NEED-DATA",
            "NOT EAS CURRENT TAB",
            "FIVE CURRENT COMMAND PRESETS"):
        assert phrase in contract
    for widget_type in (
            QtWidgets.QComboBox,
            QtWidgets.QSpinBox,
            QtWidgets.QDoubleSpinBox,
            QtWidgets.QCheckBox,
            QtWidgets.QLineEdit,
            QtWidgets.QSlider):
        assert (
            ui.win.axis_current_reference_frame.findChildren(widget_type)
            == [])
    assert tuple(
        button.text()
        for button in ui.win.axis_current_reference_frame.findChildren(
            QtWidgets.QPushButton)
    ) == ("Refresh Drive Current Readback · READ ONLY",)
    assert ui.win.btn_axis_current_reference_refresh.property(
        "operationId") == "axis.current_reference.refresh"


def test_current_reference_snapshot_renders_without_granting_authority(
        ui, qapp):
    before = (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
        tuple(ui.worker.calls),
    )

    ui.worker.axis_current_reference.emit(_current_reference_snapshot())
    qapp.processEvents()

    assert ui.win.lbl_axis_current_reference_state.text() == (
        "CURRENT · DRIVE READ ONLY")
    assert ui.win.lbl_axis_current_reference_motor.text() == (
        "DISABLED REPORTED · UM=5 Position")
    assert ui.win.axis_current_reference_table.item(0, 1).text() == "0.0000 A"
    assert ui.win.axis_current_reference_table.item(3, 1).text() == "2.0000 A"
    assert ui.win.axis_current_reference_table.item(4, 1).text() == "4.0000 A"
    assert ui.win.axis_current_reference_table.item(5, 1).text() == "0 · OFF"
    assert ui.win.axis_current_reference_table.item(6, 1).text() == "5.0000 A"
    detail = ui.win.lbl_axis_current_reference_detail.text().upper()
    assert "80.0 MS" in detail
    assert "NO TC ASSIGNMENT" in detail
    assert "COMMAND LOCKED" in detail
    assert (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
        tuple(ui.worker.calls),
    ) == before


def test_current_reference_refresh_queues_one_typed_read_job(ui, qapp):
    ui.win.btn_axis_current_reference_refresh.setEnabled(True)
    ui.win.btn_axis_current_reference_refresh.click()
    qapp.processEvents()

    assert ui.worker.calls == [
        ("refresh_axis_current_reference", (), {}),
    ]
    assert ui.win.lbl_axis_current_reference_state.text() == "READING"


def test_late_or_forged_current_reference_snapshot_fails_closed(ui, qapp):
    valid = _current_reference_snapshot()
    forged = replace(valid, evidence_label="FORGED")

    ui.worker.axis_current_reference.emit(forged)
    qapp.processEvents()
    assert ui.win.lbl_axis_current_reference_state.text() == "UNKNOWN"

    ui.win._telemetry_authoritative = False
    ui.worker.axis_current_reference.emit(valid)
    qapp.processEvents()
    assert ui.win.lbl_axis_current_reference_state.text() == "UNKNOWN"

    ui.win._telemetry_authoritative = True
    ui.worker.axis_current_reference.emit(valid)
    qapp.processEvents()
    ui.win._set_connected_ui(False)
    assert ui.win.lbl_axis_current_reference_state.text() == "UNKNOWN"


def test_worker_queues_exact_current_reference_read_job():
    worker = app_main.DriveWorker("COM_TEST", query_only=True)

    worker.refresh_axis_current_reference()

    assert worker._jobs == app_main.collections.deque((
        ("axis_current_reference_read", None),
    ))
    assert "axis_current_reference_read" in worker._OBSERVE_ONLY_JOB_ALLOWLIST
    assert {
        "TC", "CL[1]", "PL[1]", "LC", "MC",
    } <= worker._READ_ONLY_QUERY_ALLOWLIST


def test_worker_emits_only_the_typed_current_reference_snapshot(monkeypatch):
    worker = app_main.DriveWorker("COM_TEST", query_only=True)
    expected = _current_reference_snapshot()
    calls = []
    observed = []
    monkeypatch.setattr(
        app_main.single_axis_current_reference,
        "read_current_reference_snapshot",
        lambda link: calls.append(link) or expected)
    worker.axis_current_reference.connect(observed.append)
    link = object()

    worker._emit_axis_current_reference(link)

    assert calls == [link]
    assert observed == [expected]


def test_position_velocity_panel_starts_unknown_and_has_no_command_surface(ui):
    assert ui.win.lbl_axis_position_velocity_state.text() == "UNKNOWN"
    assert ui.win.axis_position_velocity_table.rowCount() == 9
    assert ui.win.axis_position_velocity_table.minimumHeight() >= 410
    assert tuple(
        ui.win.axis_position_velocity_table.item(row, 0).text()
        for row in range(9)
    ) == (
        "PA[1]", "PR[1]", "JV", "SP[1]", "AC[1]",
        "DC", "SD", "PX", "VX",
    )
    contract = ui.win.lbl_axis_position_velocity_contract.text().upper()
    for phrase in (
            "QUERY ONLY",
            "CONFIGURED",
            "NOT ACTIVE COMMAND",
            "NO ASSIGNMENT",
            "NO BG",
            "COMMAND LOCKED",
            "NEED-DATA",
            "RAW PX MATCHED EAS TERMINAL",
            "2^25",
            "MISMATCH / NEED-DATA"):
        assert phrase in contract
    for widget_type in (
            QtWidgets.QComboBox,
            QtWidgets.QSpinBox,
            QtWidgets.QDoubleSpinBox,
            QtWidgets.QCheckBox,
            QtWidgets.QLineEdit,
            QtWidgets.QSlider):
        assert (
            ui.win.axis_position_velocity_frame.findChildren(widget_type)
            == [])
    assert tuple(
        button.text()
        for button in ui.win.axis_position_velocity_frame.findChildren(
            QtWidgets.QPushButton)
    ) == ("Refresh Position / Velocity References - READ ONLY",)
    assert ui.win.btn_axis_position_velocity_refresh.property(
        "operationId") == "axis.position_velocity_reference.refresh"


def test_position_velocity_snapshot_renders_without_granting_authority(
        ui, qapp):
    before = (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
        tuple(ui.worker.calls),
    )

    ui.worker.axis_position_velocity_reference.emit(
        _position_velocity_snapshot())
    qapp.processEvents()

    assert ui.win.lbl_axis_position_velocity_state.text() == (
        "CURRENT - DRIVE READ ONLY")
    assert ui.win.lbl_axis_position_velocity_motor.text() == (
        "DISABLED REPORTED - UM=5 Position")
    assert ui.win.axis_position_velocity_table.item(0, 1).text() == (
        "12,000 cnt")
    assert ui.win.axis_position_velocity_table.item(1, 1).text() == (
        "-500 cnt")
    assert ui.win.axis_position_velocity_table.item(2, 1).text() == (
        "2,500 cnt/s")
    assert ui.win.axis_position_velocity_table.item(4, 1).text() == (
        "20,000 cnt/s^2")
    assert ui.win.axis_position_velocity_table.item(8, 1).text() == (
        "12.500 cnt/s")
    detail = ui.win.lbl_axis_position_velocity_detail.text().upper()
    assert "90.0 MS" in detail
    assert "LIMITED BY SD" in detail
    assert "NOT ACTIVE COMMAND" in detail
    assert "COMMAND LOCKED" in detail
    assert (
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
        tuple(ui.worker.calls),
    ) == before


def test_position_velocity_refresh_queues_one_typed_read_job(ui, qapp):
    ui.win.btn_axis_position_velocity_refresh.setEnabled(True)
    ui.win.btn_axis_position_velocity_refresh.click()
    qapp.processEvents()

    assert ui.worker.calls == [
        ("refresh_axis_position_velocity_reference", (), {}),
    ]
    assert ui.win.lbl_axis_position_velocity_state.text() == "READING"


def test_late_or_forged_position_velocity_snapshot_fails_closed(ui, qapp):
    valid = _position_velocity_snapshot()
    forged = replace(valid, reference_semantics="FORGED")

    ui.worker.axis_position_velocity_reference.emit(forged)
    qapp.processEvents()
    assert ui.win.lbl_axis_position_velocity_state.text() == "UNKNOWN"

    ui.win._telemetry_authoritative = False
    ui.worker.axis_position_velocity_reference.emit(valid)
    qapp.processEvents()
    assert ui.win.lbl_axis_position_velocity_state.text() == "UNKNOWN"

    ui.win._telemetry_authoritative = True
    ui.worker.axis_position_velocity_reference.emit(valid)
    qapp.processEvents()
    ui.win._set_connected_ui(False)
    assert ui.win.lbl_axis_position_velocity_state.text() == "UNKNOWN"


def test_worker_queues_exact_position_velocity_read_job():
    worker = app_main.DriveWorker("COM_TEST", query_only=True)

    worker.refresh_axis_position_velocity_reference()

    assert worker._jobs == app_main.collections.deque((
        ("axis_position_velocity_reference_read", None),
    ))
    assert (
        "axis_position_velocity_reference_read"
        in worker._OBSERVE_ONLY_JOB_ALLOWLIST)
    assert {
        "PA[1]", "PR[1]", "JV", "SP[1]", "AC[1]",
        "DC", "SD", "PX", "VX",
    } <= worker._READ_ONLY_QUERY_ALLOWLIST


def test_worker_emits_only_the_typed_position_velocity_snapshot(monkeypatch):
    worker = app_main.DriveWorker("COM_TEST", query_only=True)
    expected = _position_velocity_snapshot()
    calls = []
    observed = []
    monkeypatch.setattr(
        app_main.single_axis_position_velocity_reference,
        "read_position_velocity_snapshot",
        lambda link: calls.append(link) or expected)
    worker.axis_position_velocity_reference.connect(observed.append)
    link = object()

    worker._emit_axis_position_velocity_reference(link)

    assert calls == [link]
    assert observed == [expected]


def test_single_axis_authority_map_is_static_zero_io_and_isolated(
        ui, qapp, monkeypatch):
    calls_before = tuple(ui.worker.calls)
    authority_before = (
        ui.win.worker,
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
        ui.win.btn_motion_stop.isEnabled(),
    )

    expected_labels = {
        "status_and_io": (
            "Motion Status",
            "Digital Inputs",
            "Digital Outputs",
            "Safety / STO Status",
        ),
        "mode_and_reference": (
            "Drive Mode (UM)",
            "Position / Velocity",
            "Current Reference",
            "Sine / Homing / Stepper",
        ),
        "activation_and_tools": (
            "Enable / Disable",
            "Stop Controls",
            "Terminal / Command Reference",
            "Recorder",
        ),
    }
    assert tuple(
        ui.win.single_axis_authority_section.itemData(index)
        for index in range(ui.win.single_axis_authority_section.count())
    ) == tuple(expected_labels)
    for index, section_key in enumerate(expected_labels):
        ui.win.single_axis_authority_section.setCurrentIndex(index)
        qapp.processEvents()
        assert ui.win.single_axis_authority_table.rowCount() == 4
        assert tuple(
            ui.win.single_axis_authority_table.item(row, 0).text()
            for row in range(4)
        ) == expected_labels[section_key]

    assert ui.win.single_axis_authority_section.isEditable() is False
    assert ui.win.single_axis_authority_frame.findChildren(
        QtWidgets.QLineEdit) == []
    assert ui.win.single_axis_authority_frame.findChildren(
        QtWidgets.QPushButton) == []
    assert ui.win.single_axis_authority_frame.findChildren(
        QtWidgets.QCheckBox) == []
    assert ui.win.single_axis_authority_frame.findChildren(
        QtWidgets.QSlider) == []
    assert tuple(
        ui.win.single_axis_authority_table.horizontalHeaderItem(column).text()
        for column in range(4)
    ) == (
        "EAS AREA / CONTROL",
        "DOCUMENTED ROLE",
        "RISK / ACCESS",
        "STATUS / BOUNDARY",
    )
    assert all(
        "app: inspect-only" in
        ui.win.single_axis_authority_table.item(row, 2).text()
        for row in range(ui.win.single_axis_authority_table.rowCount()))
    rendered = " ".join((
        ui.win.single_axis_authority_banner.text(),
        ui.win.single_axis_authority_status.text(),
        ui.win.single_axis_authority_warnings.text(),
        ui.win.single_axis_authority_missing.text(),
        *(
            ui.win.single_axis_authority_table.item(row, column).text()
            for row in range(ui.win.single_axis_authority_table.rowCount())
            for column in range(
                ui.win.single_axis_authority_table.columnCount())
        ),
    )).upper()
    for phrase in (
            "DOCUMENTED SINGLE AXIS AUTHORITY MAP",
            "NOT CURRENT EAS SINGLE AXIS STATE",
            "NOT CURRENT DRIVE STATE",
            "NOT STO TEST EVIDENCE",
            "NO DRIVE READ",
            "NO DIGITAL OUTPUT WRITE",
            "NO MODE CHANGE",
            "NO ENABLE/DISABLE",
            "NO PTP/JOG/CURRENT/SINE/HOMING/STEPPER",
            "NO TERMINAL/COMMAND SEND",
            "NO RECORDER CONFIG/ACQUISITION",
            "NO ENERGIZATION/MOTION",
            "NO DRIVE I/O"):
        assert phrase in rendered
    for forbidden in (
            "CURRENT DRIVE SAFE",
            "CURRENT STO TEST PASSED",
            "READY TO ENABLE",
            "READY TO MOVE",
            "EAS PARITY COMPLETE",
            "APP: R/W"):
        assert forbidden not in rendered

    assert tuple(ui.worker.calls) == calls_before
    assert (
        ui.win.worker,
        ui.win._connection_admitted,
        ui.win._telemetry_authoritative,
        ui.win._motion_signature_green,
        ui.win._motion_session_zero_confirmed,
        ui.win._motion_inflight,
        ui.win.btn_motion_run.isEnabled(),
        ui.win.btn_motion_stop.isEnabled(),
    ) == authority_before


def test_single_axis_authority_map_fits_1366x820_in_all_skins(ui, qapp):
    def contrast_ratio(first, second):
        def relative_luminance(color):
            channels = []
            for value in (color.redF(), color.greenF(), color.blueF()):
                channels.append(
                    value / 12.92
                    if value <= 0.04045
                    else ((value + 0.055) / 1.055) ** 2.4)
            return (
                0.2126 * channels[0]
                + 0.7152 * channels[1]
                + 0.0722 * channels[2]
            )

        high, low = sorted((
            relative_luminance(first),
            relative_luminance(second),
        ), reverse=True)
        return (high + 0.05) / (low + 0.05)

    previous_style_sheet = qapp.styleSheet()
    previous_palette = QtGui.QPalette(qapp.palette())
    ui.win.resize(1366, 820)
    ui.win.show()
    ui.win._nav_to(0)
    try:
        for themed in (theme_qdd, amber_theme, theme_angrybirds):
            qapp.setStyleSheet(themed.STYLE)
            ui.win.resize(1366, 820)
            for _ in range(3):
                qapp.processEvents()

            assert ui.win.minimumSizeHint().width() <= 1366
            assert ui.win.workspace_scroll.horizontalScrollBar().maximum() == 0
            assert ui.win.single_axis_authority_banner.height() >= (
                ui.win.single_axis_authority_banner.sizeHint().height())
            assert ui.win.single_axis_authority_status.height() >= (
                ui.win.single_axis_authority_status.sizeHint().height())
            assert ui.win.single_axis_authority_table.columnWidth(0) >= 190
            assert ui.win.single_axis_authority_table.columnWidth(1) >= 300
            assert ui.win.single_axis_authority_table.columnWidth(2) >= 220
            table_palette = (
                ui.win.single_axis_authority_table.viewport().palette())
            assert contrast_ratio(
                table_palette.color(QtGui.QPalette.ColorRole.Text),
                table_palette.color(QtGui.QPalette.ColorRole.Base),
            ) >= 4.5
            inputs_palette = (
                ui.win.axis_digital_inputs_table.viewport().palette())
            assert contrast_ratio(
                inputs_palette.color(QtGui.QPalette.ColorRole.Text),
                inputs_palette.color(QtGui.QPalette.ColorRole.Base),
            ) >= 4.5
            assert (
                ui.win.axis_digital_inputs_table.horizontalScrollBar().maximum()
                == 0)
            outputs_palette = (
                ui.win.axis_digital_outputs_table.viewport().palette())
            assert contrast_ratio(
                outputs_palette.color(QtGui.QPalette.ColorRole.Text),
                outputs_palette.color(QtGui.QPalette.ColorRole.Base),
            ) >= 4.5
            assert (
                ui.win.axis_digital_outputs_table.horizontalScrollBar().maximum()
                == 0)
            mode_palette = (
                ui.win.axis_drive_mode_table.viewport().palette())
            assert contrast_ratio(
                mode_palette.color(QtGui.QPalette.ColorRole.Text),
                mode_palette.color(QtGui.QPalette.ColorRole.Base),
            ) >= 4.5
            assert (
                ui.win.axis_drive_mode_table.horizontalScrollBar().maximum()
                == 0)
            current_palette = (
                ui.win.axis_current_reference_table.viewport().palette())
            assert contrast_ratio(
                current_palette.color(QtGui.QPalette.ColorRole.Text),
                current_palette.color(QtGui.QPalette.ColorRole.Base),
            ) >= 4.5
            assert (
                ui.win.axis_current_reference_table.horizontalScrollBar().maximum()
                == 0)
            assert (
                ui.win.axis_current_reference_table.verticalScrollBar().maximum()
                == 0)
            assert ui.win.lbl_axis_current_reference_contract.height() >= (
                ui.win.lbl_axis_current_reference_contract.sizeHint().height())
            assert ui.win.lbl_axis_drive_mode_contract.height() >= (
                ui.win.lbl_axis_drive_mode_contract.sizeHint().height())
            assert ui.win.lbl_axis_enable_contract.height() >= (
                ui.win.lbl_axis_enable_contract.sizeHint().height())
            assert ui.win.lbl_axis_enable_detail.height() >= (
                ui.win.lbl_axis_enable_detail.sizeHint().height())
            assert ui.win.btn_axis_enable_locked.isEnabled() is False
    finally:
        qapp.setPalette(previous_palette)
        qapp.setStyleSheet(previous_style_sheet)


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
