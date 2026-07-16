"""Offline UI regressions for telemetry-bound hardware authority.

The tests in this module never construct ``ElmoLink`` and never start a
``DriveWorker``.  A process-local QObject emits the same signals as the worker
so sender/generation checks are exercised without opening a COM port.
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

import feedback_spec
import main as app_main


_IDENTITY = "elmo-sn4-sha256:" + ("a" * 64)


class _SignalWorker(QtCore.QObject):
    """Synchronous, no-I/O worker double with QThread-like stop semantics."""

    connected = QtCore.pyqtSignal(dict)
    telemetry = QtCore.pyqtSignal(dict)
    persistence_audit_status = QtCore.pyqtSignal(object)
    autotune_started = QtCore.pyqtSignal()
    velpos_started = QtCore.pyqtSignal()
    verify_started = QtCore.pyqtSignal()
    axis_summary = QtCore.pyqtSignal(dict)
    motion_authority = QtCore.pyqtSignal(bool, str)
    motion_result = QtCore.pyqtSignal(str, object)

    def __init__(self, *, running=True, stop_keeps_running=False):
        super().__init__()
        self.running = bool(running)
        self.stop_keeps_running = bool(stop_keeps_running)
        self.stop_calls = 0

    def isRunning(self):
        return self.running

    def stop(self):
        self.stop_calls += 1
        # QThread.isRunning() remains true while run() performs terminal
        # cleanup, even after DriveWorker.stop() has revoked ordinary work.
        if not self.stop_keeps_running:
            self.running = False


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


@pytest.fixture
def ui(qapp, monkeypatch):
    monkeypatch.setattr(app_main, "list_serial_ports", lambda: ["COM_TEST"])
    win = app_main.MainWindow()
    worker = _SignalWorker()
    win.worker = worker
    win.cmb_port.setCurrentText("COM_TEST")

    worker.connected.connect(win._on_connected)
    worker.telemetry.connect(win._on_telemetry)
    worker.persistence_audit_status.connect(win._on_persistence_audit_status)
    worker.autotune_started.connect(win._on_autotune_started)
    worker.velpos_started.connect(win._on_velpos_started)
    worker.verify_started.connect(win._on_verify_started)
    worker.axis_summary.connect(win._on_axis_summary)
    worker.motion_authority.connect(win._on_motion_authority)
    worker.motion_result.connect(win._on_motion_result)

    yield SimpleNamespace(win=win, worker=worker)

    win.worker = None
    win.close()
    qapp.processEvents()


def _telemetry(*, sequence=1, received=None, mo=0, valid=True):
    if received is None:
        received = time.monotonic()
    return {
        "pos": 42,
        "vel": 0.0,
        "pos_err": 0.0,
        "iq": 0.0,
        "mo": mo,
        "_sample_started_monotonic": received - 0.01,
        "_sample_finished_monotonic": received,
        "_sample_duration_s": 0.01,
        "telemetry_valid": bool(valid),
        "telemetry_sequence": sequence,
        "telemetry_received_monotonic": received,
        "session_coordinate_known": bool(valid),
        "encoder_maintenance_reconnect_required": False,
    }


def _connection_info(initial=None):
    return {
        "fw": "Twitter 01.01.16.00",
        "pal": "90",
        "boot": "DSP Boot 1.0.1.6",
        "target_type": "Gold Drive",
        "drive_identity": _IDENTITY,
        "initial_telemetry": initial or _telemetry(),
        "persistence_status": {
            "status": "CLEAR",
            "resolved": True,
            "detail": "offline deterministic fixture",
            "lock_active": False,
            "record_id": None,
            "phase": None,
            "other_active_count": 0,
            "ledger_error": None,
        },
    }


def _admit_disabled(ui, *, sequence=1):
    ui.worker.connected.emit(
        _connection_info(_telemetry(sequence=sequence, mo=0)))
    assert ui.win._ui_connected is True
    assert ui.win.lbl_motor.text() == "MOTOR DISABLED"


def test_disconnect_clears_run_attestations_and_session_zero(ui):
    _admit_disabled(ui)
    for check in (
            ui.win.chk_motion_operator,
            ui.win.chk_motion_estop,
            ui.win.chk_motion_limits):
        check.setChecked(True)
    ui.win._motion_session_zero_confirmed = True

    ui.win._set_connected_ui(False)

    assert not ui.win._motion_session_zero_confirmed
    assert not ui.win.chk_motion_operator.isChecked()
    assert not ui.win.chk_motion_estop.isChecked()
    assert not ui.win.chk_motion_limits.isChecked()


def test_phase2_button_tracks_current_connection_signature_authority(ui):
    _admit_disabled(ui)

    assert ui.win.btn_tune_signature.isEnabled()
    assert not ui.win.btn_tune_vp.isEnabled()

    ui.worker.motion_authority.emit(True, "offline signature fixture")

    assert not ui.win.btn_tune_vp.isEnabled()
    ui.win._at_result = app_main.autotune_current.AutotuneResult(
        status=app_main.autotune_current.GREEN,
        r_pp_ohm=0.139,
        l_pp_h=41.6e-6,
    )
    ui.win._at_result_generation = ui.win._tuning_authority_generation
    ui.win._set_connected_ui(True)

    assert ui.win.btn_tune_vp.isEnabled()


def test_phase2_confirmation_never_invents_amp_value_from_one_drive(
        ui, monkeypatch):
    _admit_disabled(ui)
    ui.worker.motion_authority.emit(True, "offline signature fixture")
    ui.win._at_result = app_main.autotune_current.AutotuneResult(
        status=app_main.autotune_current.GREEN,
        r_pp_ohm=0.139,
        l_pp_h=41.6e-6,
    )
    ui.win._at_result_generation = ui.win._tuning_authority_generation
    shown = []

    def capture(_parent, _title, text, *_args, **_kwargs):
        shown.append(text)
        return QtWidgets.QMessageBox.StandardButton.No

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", capture)

    ui.win._run_velpos_clicked()

    assert shown
    assert "21.2132" not in shown[0]
    assert "live CL[1]" in shown[0]


_ORDINARY_MUTATION_CONTROLS = (
    "btn_zero",
    "btn_motor_write",
    "btn_tune",
    "btn_tune_signature",
    "btn_tune_vp",
    "btn_tune_verify",
    "btn_tune_apply",
    "btn_tune_p1_restore",
    "btn_tune_p1_save",
    "btn_tune_vp_apply",
    "btn_tune_vp_restore",
    "btn_tune_vp_save",
    "btn_motion_run",
    "btn_rec_immediate",
    "btn_rec_upload",
    "btn_fb_write",
)


def _encoder_maintenance_buttons(win):
    # EnDat 2.2 owns the datum/multiturn maintenance entrypoint.  Rebuilding
    # this local panel performs no drive I/O.
    win._rebuild_fb_dynamic(30, values={})
    return tuple(
        widget
        for _label, (field, widget) in win._fb_dyn_fields.items()
        if (field.get("kind") == feedback_spec.BTN
            and "maintenance" in str(field.get("label") or "").lower())
    )


def _assert_telemetry_unknown_and_mutations_locked(win):
    assert win.lbl_motor.text() == "MOTOR STATE UNKNOWN"
    assert win._last_mo is None
    for name in _ORDINARY_MUTATION_CONTROLS:
        assert not getattr(win, name).isEnabled(), name
    assert not win.motor_type_combo.isEnabled()
    for name in ("peak", "cont", "maxspeed", "poles"):
        assert not win.motor_fields[name].isEnabled(), name
    maintenance = _encoder_maintenance_buttons(win)
    assert maintenance, "EnDat maintenance control was not constructed"
    assert all(not button.isEnabled() for button in maintenance)

    # Loss of telemetry authority must not remove the independent software
    # escape path while the current worker/link thread is still alive.
    assert win.btn_motion_stop.isEnabled()
    assert win.btn_global_stop.isEnabled()


def test_missing_authority_metadata_never_renders_disabled_or_keeps_writes(ui):
    _admit_disabled(ui)
    _encoder_maintenance_buttons(ui.win)

    ui.worker.telemetry.emit({
        "pos": 42,
        "vel": 0.0,
        "pos_err": 0.0,
        "iq": 0.0,
        "mo": 0,
    })

    _assert_telemetry_unknown_and_mutations_locked(ui.win)


def test_aged_authority_envelope_never_renders_disabled_or_keeps_writes(ui):
    _admit_disabled(ui)
    _encoder_maintenance_buttons(ui.win)

    ui.worker.telemetry.emit(_telemetry(
        sequence=2,
        received=time.monotonic() - 3600.0,
        mo=0,
    ))

    _assert_telemetry_unknown_and_mutations_locked(ui.win)


def test_replayed_sequence_never_renders_disabled_or_keeps_writes(ui):
    _admit_disabled(ui, sequence=7)
    _encoder_maintenance_buttons(ui.win)

    ui.worker.telemetry.emit(_telemetry(
        sequence=7,
        received=time.monotonic(),
        mo=0,
    ))

    _assert_telemetry_unknown_and_mutations_locked(ui.win)


def test_mo_one_gate_survives_connected_ui_recalculation(ui):
    _admit_disabled(ui, sequence=1)
    ui.win._on_telemetry(_telemetry(sequence=2, mo=1))
    assert ui.win.lbl_motor.text() == "MOTOR ENABLED"
    assert not ui.win.btn_zero.isEnabled()

    ui.win._set_connected_ui(True)

    assert ui.win.lbl_motor.text() == "MOTOR ENABLED"
    assert not ui.win.btn_zero.isEnabled()


def test_telemetry_before_connection_admission_never_creates_authority(ui):
    ui.win._on_telemetry(_telemetry(sequence=1, mo=0))

    assert ui.win.lbl_motor.text() == "MOTOR STATE UNKNOWN"
    assert ui.win._last_mo is None
    assert all(not getattr(ui.win, name).isEnabled()
               for name in _ORDINARY_MUTATION_CONTROLS)
    assert not ui.win.btn_motion_stop.isEnabled()
    assert not ui.win.btn_global_stop.isEnabled()


@pytest.mark.parametrize("reason", ("worker-stopped", "initial-aged"))
def test_connected_admission_rejects_dead_worker_or_aged_initial(ui, reason):
    if reason == "worker-stopped":
        ui.worker.running = False
        initial = _telemetry(sequence=1, mo=0)
    else:
        initial = _telemetry(
            sequence=1,
            received=time.monotonic() - 3600.0,
            mo=0,
        )

    ui.worker.connected.emit(_connection_info(initial))

    assert ui.win._ui_connected is False
    assert ui.win.lbl_state.text() == "OFFLINE"
    assert ui.win._connected_identity == {}


@pytest.mark.parametrize(
    "flag",
    ("MISSING", None, 0, 1, "false"),
    ids=("missing", "none", "zero-int", "one-int", "string"),
)
def test_connection_admission_requires_explicit_false_reconnect_flag(ui, flag):
    initial = _telemetry(sequence=1, mo=0)
    if flag == "MISSING":
        initial.pop("encoder_maintenance_reconnect_required")
    else:
        initial["encoder_maintenance_reconnect_required"] = flag

    ui.worker.connected.emit(_connection_info(initial))

    assert ui.worker.stop_calls == 1
    assert ui.win._connection_admitted is False
    assert ui.win._telemetry_authoritative is False


@pytest.mark.parametrize(
    "flag",
    ("MISSING", None, 0, 1, "false"),
    ids=("missing", "none", "zero-int", "one-int", "string"),
)
def test_live_telemetry_requires_explicit_false_reconnect_flag(ui, flag):
    _admit_disabled(ui, sequence=1)
    sample = _telemetry(sequence=2, mo=0)
    if flag == "MISSING":
        sample.pop("encoder_maintenance_reconnect_required")
    else:
        sample["encoder_maintenance_reconnect_required"] = flag

    ui.worker.telemetry.emit(sample)

    _assert_telemetry_unknown_and_mutations_locked(ui.win)


def test_rejected_admission_cannot_be_resurrected_by_queued_status(ui):
    ui.worker.stop_keeps_running = True
    incomplete = _connection_info()
    incomplete.pop("boot")

    ui.worker.connected.emit(incomplete)
    assert ui.worker.stop_calls == 1
    assert ui.worker.isRunning(), "stub must model QThread terminal cleanup"
    assert ui.win._ui_connected is False

    ui.worker.persistence_audit_status.emit(
        _connection_info()["persistence_status"])

    assert ui.win._ui_connected is False
    assert ui.win.lbl_state.text() == "OFFLINE"


@pytest.mark.parametrize(
    "bad_status",
    (
        None,
        {},
        {"status": "CLEAR", "lock_active": False},
        {
            "status": "CLEAR", "resolved": True, "detail": "bad type",
            "lock_active": "false", "record_id": None, "phase": None,
            "other_active_count": 0, "ledger_error": None,
        },
    ),
    ids=("none", "empty", "partial", "malformed-lock"),
)
def test_connection_admission_rejects_malformed_persistence_schema(
        ui, bad_status):
    info = _connection_info(_telemetry(sequence=1, mo=0))
    info["persistence_status"] = bad_status

    ui.worker.connected.emit(info)

    assert ui.worker.stop_calls == 1
    assert ui.win._ui_connected is False
    assert ui.win._connection_admitted is False
    assert ui.win.lbl_state.text() == "OFFLINE"
    assert not ui.win.btn_motion_stop.isEnabled()
    assert not ui.win.btn_global_stop.isEnabled()


def test_superseded_worker_axis_and_motion_signals_cannot_mutate_new_session(ui):
    old_worker = ui.worker
    new_worker = _SignalWorker()
    ui.win.worker = new_worker
    ui.win._axis_summary_data = {"session": "new"}
    ui.win._motion_signature_green = False
    ui.win._motion_config_unknown = False
    ui.win._motion_stop_pending = False
    ui.win._motion_inflight = True
    before_gate = ui.win.motion_gate.text()

    old_worker.axis_summary.emit({
        "scope": "stale-worker",
        "motion_config_unknown": True,
        "raw": {"MO": 1},
    })
    old_worker.motion_authority.emit(True, "stale GREEN authority")
    old_worker.motion_result.emit(
        "move",
        app_main.single_axis_motion.MotionResult(
            app_main.single_axis_motion.UNKNOWN,
            "stale motion result",
            final_state={"disabled_verified": False},
        ),
    )

    assert ui.win._axis_summary_data == {"session": "new"}
    assert ui.win._motion_signature_green is False
    assert ui.win._motion_config_unknown is False
    assert ui.win._motion_stop_pending is False
    assert ui.win._motion_inflight is True
    assert ui.win.motion_gate.text() == before_gate


@pytest.mark.parametrize(
    ("dispatch_kind", "signal_name"),
    (
        ("p1", "autotune_started"),
        ("p2", "velpos_started"),
        ("verify", "verify_started"),
    ),
)
def test_energizing_start_forbids_disabled_until_new_envelope(
        ui, dispatch_kind, signal_name):
    _admit_disabled(ui, sequence=11)
    assert ui.win._claim_tune_dispatch(dispatch_kind)

    getattr(ui.worker, signal_name).emit()

    assert ui.win.lbl_motor.text() != "MOTOR DISABLED"
    assert ui.win._last_mo is None

    # Replaying the pre-start sequence cannot prove the terminal MO state.
    ui.worker.telemetry.emit(_telemetry(sequence=11, mo=0))
    assert ui.win.lbl_motor.text() != "MOTOR DISABLED"

    # Only a new, complete and timely sample can restore a DISABLED claim.
    ui.worker.telemetry.emit(_telemetry(sequence=12, mo=0))
    assert ui.win.lbl_motor.text() == "MOTOR DISABLED"


def _malformed_raw_timing(case, *, sequence):
    sample = _telemetry(sequence=sequence, mo=0)
    if case.startswith("missing-"):
        sample.pop({
            "missing-start": "_sample_started_monotonic",
            "missing-finish": "_sample_finished_monotonic",
            "missing-duration": "_sample_duration_s",
        }[case])
    elif case == "finish-before-start":
        sample["_sample_started_monotonic"] = (
            sample["_sample_finished_monotonic"] + 0.01)
    elif case == "duration-mismatch":
        sample["_sample_started_monotonic"] = (
            sample["_sample_finished_monotonic"] - 0.20)
        sample["_sample_duration_s"] = 0.01
    else:  # pragma: no cover - test-table programming error
        raise AssertionError(case)
    return sample


_RAW_TIMING_FAILURES = (
    "missing-start",
    "missing-finish",
    "missing-duration",
    "finish-before-start",
    "duration-mismatch",
)


@pytest.mark.parametrize("timing_case", _RAW_TIMING_FAILURES)
def test_connection_admission_rejects_missing_or_malformed_raw_timing(
        ui, timing_case):
    initial = _malformed_raw_timing(timing_case, sequence=1)

    ui.worker.connected.emit(_connection_info(initial))

    assert ui.worker.stop_calls == 1
    assert ui.win._ui_connected is False
    assert ui.win._connection_admitted is False
    assert ui.win.lbl_state.text() == "OFFLINE"
    assert not ui.win.btn_motion_stop.isEnabled()
    assert not ui.win.btn_global_stop.isEnabled()
    assert all(
        not getattr(ui.win, name).isEnabled()
        for name in _ORDINARY_MUTATION_CONTROLS)


@pytest.mark.parametrize("timing_case", _RAW_TIMING_FAILURES)
def test_live_telemetry_rejects_missing_or_malformed_raw_timing(
        ui, timing_case):
    _admit_disabled(ui, sequence=1)

    ui.worker.telemetry.emit(
        _malformed_raw_timing(timing_case, sequence=2))

    _assert_telemetry_unknown_and_mutations_locked(ui.win)


def test_watchdog_keeps_just_inside_age_and_revokes_just_outside_age(
        ui, monkeypatch):
    _admit_disabled(ui, sequence=1)
    fixed_now = time.monotonic()
    monkeypatch.setattr(app_main.time, "monotonic", lambda: fixed_now)

    ui.win._last_telemetry_received_monotonic = (
        fixed_now - app_main.TELEMETRY_UI_MAX_AGE_S + 0.01)
    ui.win._check_telemetry_watchdog()

    assert ui.win._telemetry_authoritative
    assert ui.win.lbl_motor.text() == "MOTOR DISABLED"
    assert ui.win.btn_motor_write.isEnabled()
    assert ui.win.btn_motion_stop.isEnabled()
    assert ui.win.btn_global_stop.isEnabled()

    ui.win._last_telemetry_received_monotonic = (
        fixed_now - app_main.TELEMETRY_UI_MAX_AGE_S - 0.01)
    ui.win._check_telemetry_watchdog()

    _assert_telemetry_unknown_and_mutations_locked(ui.win)


def test_failed_soft_zero_cannot_restore_mutation_controls(ui):
    _admit_disabled(ui, sequence=1)

    ui.win._on_soft_zero_result(
        False, "negative-control PX=0 postcondition failure", None)

    _assert_telemetry_unknown_and_mutations_locked(ui.win)


def test_failed_encoder_maintenance_revokes_stale_position_authority(
        ui, monkeypatch):
    _admit_disabled(ui, sequence=1)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "exec", lambda _dialog: 0)

    ui.win._on_encoder_maint_result(
        False,
        "negative-control postcondition mismatch; encoder/PX state UNKNOWN")

    _assert_telemetry_unknown_and_mutations_locked(ui.win)


def test_red_verify_result_cannot_restore_controls_without_fresh_envelope(ui):
    _admit_disabled(ui, sequence=11)
    assert ui.win._claim_tune_dispatch("verify")
    ui.worker.verify_started.emit()
    result = app_main.autotune_velpos.AutotuneVPResult(
        status=app_main.autotune_velpos.RED,
        reason="negative-control verification failure",
        evidence={},
    )

    ui.win._on_verify_result(result)

    assert ui.win.lbl_motor.text() != "MOTOR DISABLED"
    assert ui.win._last_mo is None
    for name in _ORDINARY_MUTATION_CONTROLS:
        assert not getattr(ui.win, name).isEnabled(), name
    assert ui.win.btn_motion_stop.isEnabled()
    assert ui.win.btn_global_stop.isEnabled()


def test_red_signature_result_cannot_restore_controls_without_fresh_envelope(ui):
    _admit_disabled(ui, sequence=21)
    assert ui.win._claim_tune_dispatch("signature")
    ui.win._vp_signature_run = True
    ui.worker.velpos_started.emit()
    result = app_main.autotune_velpos.AutotuneVPResult(
        status=app_main.autotune_velpos.RED,
        reason="negative-control unverified signature closeout",
        evidence={
            "signature_gate": {"mode": "standalone_commutation_signature"},
            "final_state": {"MO": None, "TC": None, "pass": False},
        },
    )

    ui.win._on_velpos_result(result)

    assert ui.win.lbl_motor.text() != "MOTOR DISABLED"
    assert ui.win._last_mo is None
    for name in _ORDINARY_MUTATION_CONTROLS:
        assert not getattr(ui.win, name).isEnabled(), name
    assert ui.win.btn_motion_stop.isEnabled()
    assert ui.win.btn_global_stop.isEnabled()
