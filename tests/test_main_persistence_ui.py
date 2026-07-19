"""Offline UI/worker contract for durable ambiguous-SV recovery.

These tests deliberately never construct ``ElmoLink`` and never start the
worker thread.  They pin the fail-closed dispatch/UI boundary while the link
lifecycle tests own the flash/identity adjudication itself.
"""

from __future__ import annotations

import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

import main as app_main


def _audit_payload(
        *, locked: bool = True, status: str | None = None,
        phase: str = "P2") -> dict:
    if status is None:
        status = ("RESET_NOT_ATTESTED" if locked
                  else "RESOLVED_APPLIED_PROFILE")
    return {
        "status": status,
        "resolved": not locked,
        "detail": ("cold reset evidence still required" if locked
                   else "post-reset applied profile matched"),
        "lock_active": locked,
        "record_id": "audit-record-001",
        "phase": phase,
        "other_active_count": 0,
        "ledger_error": None,
    }


def _authoritative_telemetry(win, **overrides) -> dict:
    """Build one fresh, ordered UI telemetry authority envelope."""
    finished = time.monotonic()
    sequence = int(getattr(win, "_last_telemetry_sequence", 0)) + 1
    sample = {
        "pos": 42,
        "vel": 0.0,
        "pos_err": 0.0,
        "iq": 0.0,
        "mo": 0,
        "_sample_started_monotonic": finished - 0.001,
        "_sample_finished_monotonic": finished,
        "_sample_duration_s": 0.001,
        "telemetry_sequence": sequence,
        "telemetry_received_monotonic": finished,
        "telemetry_valid": True,
        "telemetry_error": None,
        "session_coordinate_known": True,
        "encoder_maintenance_reconnect_required": False,
    }
    sample.update(overrides)
    return sample


def _freeze_connection_access_mode(
        win, mode=app_main.SUPERVISED_ACCESS_MODE) -> None:
    """Freeze the same one-shot access mode on the UI and active worker."""
    worker = getattr(win, "worker", None)
    if worker is None:
        raise AssertionError("connection admission fixture requires a worker")
    win._requested_connection_access_mode = mode
    worker.access_mode = mode


def _connected_info(win, *, fw="CURRENT_FW", target_type="Gold Drive") -> dict:
    """Build the complete identity/admission payload emitted by DriveWorker."""
    _freeze_connection_access_mode(win)
    return {
        "fw": fw,
        "pal": "90",
        "boot": "DSP Boot 1.0.1.6",
        "target_type": target_type,
        "drive_identity": "elmo-sn4-sha256:" + "a" * 64,
        "access_mode": app_main.SUPERVISED_ACCESS_MODE,
        "persistence_status": _audit_payload(locked=False),
        "initial_telemetry": _authoritative_telemetry(win),
    }


def _seed_authoritative_connection(win) -> None:
    """Place a UI test at an already-admitted, fresh MO=0 connection."""
    _freeze_connection_access_mode(win)
    win._connection_admitted = True
    win._connection_access_mode = app_main.SUPERVISED_ACCESS_MODE
    win._energizing_state = False
    win._on_telemetry(_authoritative_telemetry(win))
    win._set_connected_ui(True)


def _seed_phase2_run_authority(win) -> None:
    """Satisfy the independent P1-model and commutation gates for P2."""
    generation = getattr(win, "_tuning_authority_generation", 0)
    win._at_result = SimpleNamespace(
        status=app_main.autotune_current.GREEN,
        r_pp_ohm=0.139,
        l_pp_h=41.6e-6,
    )
    win._at_result_generation = generation
    win._motion_signature_green = True
    win._motion_signature_token = "offline-ui-signature"
    win._motion_signature_generation = generation
    _seed_authoritative_connection(win)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


class _WorkerSpy:
    """GUI-thread spy: there is intentionally no drive/link command API."""

    def __init__(self):
        self.audit_calls = 0
        self.axis_calls = 0
        self.stop_calls = 0
        self.motor_writes = []
        self.verify_calls = []
        self.p1_begin_calls = []
        self.p2_begin_calls = []
        self.p1_commit_calls = []
        self.signature_token = "offline-ui-signature"

    @staticmethod
    def isRunning():
        return True

    def audit_persistence_after_reset(self):
        self.audit_calls += 1

    def refresh_axis_summary(self):
        self.axis_calls += 1

    def request_motion_stop(self):
        self.stop_calls += 1

    def request_recorder_stop(self):
        self.stop_calls += 1

    def stop(self):
        self.stop_calls += 1

    def write_motor(self, writes, *, ca18_basis=None):
        self.motor_writes.append((dict(writes), ca18_basis))

    def current_commutation_signature_token(self):
        return self.signature_token

    def start_verify_vp(self, kw, trial=None, signature_token=None):
        self.verify_calls.append((dict(kw), trial, signature_token))

    def begin_current_gain_trial(self, trial):
        self.p1_begin_calls.append(trial)

    def begin_velpos_gain_trial(self, trial):
        self.p2_begin_calls.append(trial)

    def commit_current_gain_trial(self, trial):
        self.p1_commit_calls.append(trial)


class _WorkerEmitter(QtCore.QObject):
    """Minimal old-worker signal source for queued-generation regressions."""

    connected = QtCore.pyqtSignal(dict)
    failed = QtCore.pyqtSignal(str)
    stopped = QtCore.pyqtSignal()
    motor_params = QtCore.pyqtSignal(dict)
    feedback = QtCore.pyqtSignal(dict)
    telemetry = QtCore.pyqtSignal(dict)
    autotune_result = QtCore.pyqtSignal(object)
    velpos_result = QtCore.pyqtSignal(object)
    current_gain_action = QtCore.pyqtSignal(str, bool, str, object)
    velpos_gain_action = QtCore.pyqtSignal(str, bool, str, object)

    @staticmethod
    def isRunning():
        return True


@pytest.fixture
def window(qapp, monkeypatch):
    # Do not enumerate host serial devices in an offline widget test.
    monkeypatch.setattr(app_main, "list_serial_ports", lambda: ["COM_TEST"])
    win = app_main.MainWindow()
    spy = _WorkerSpy()
    win.worker = spy
    win.cmb_port.setCurrentText("COM_TEST")
    yield win, spy
    win.worker = None
    win.close()
    qapp.processEvents()


def test_worker_durable_unknown_has_exact_four_job_allowlist():
    worker = app_main.DriveWorker("COM_TEST")
    worker._persistence_recovery_unknown = True

    # Mutation tooth: unrelated latches must not hide the durable lock or trap
    # its four recovery/escape jobs behind some earlier guard.
    worker._session_coordinate_known = False
    worker._encoder_maintenance_reconnect_required = True
    worker._motion_config_unknown = True
    worker._recorder_active = True
    worker._p1_gain_trial = object()
    worker._vp_gain_trial = object()

    allowed = {
        "axis_read": None,
        "persistence_audit": None,
        "motion_stop": None,
        "recorder_stop": None,
    }
    for kind, payload in allowed.items():
        assert worker._trial_job_guard(kind, payload) == (True, ""), kind

    blocked = {
        "motor_write": {},
        "feedback_write": [],
        "soft_zero": None,
        "encoder_maint": [{"id": "reset_errors", "socket": 1}],
        "autotune": {},
        "autotune_apply": (object(), False),
        "velpos": {},
        "velpos_apply": (object(), False),
        "verify_vp": ({}, object()),
        "p1_trial_begin": object(),
        "p1_trial_commit": object(),
        "p1_trial_restore": object(),
        "vp_trial_begin": object(),
        "vp_trial_commit": object(),
        "vp_trial_restore": object(),
        "motion_move": (1, object()),
        "recorder_discover": None,
        "recorder_start": (1, object()),
        "recorder_upload": 1,
        "unknown_future_write_job": object(),
    }
    for kind, payload in blocked.items():
        admitted, detail = worker._trial_job_guard(kind, payload)
        assert not admitted, kind
        assert "UNKNOWN" in detail
        assert "persist" in detail.lower() or "영구" in detail


def test_worker_audit_api_queues_one_typed_job_without_other_side_effects(qapp):
    worker = app_main.DriveWorker("COM_TEST")
    received = []

    assert isinstance(worker.persistence_audit_status, QtCore.pyqtBoundSignal)
    worker.persistence_audit_status.connect(received.append)
    payload = _audit_payload()
    worker.persistence_audit_status.emit(payload)
    qapp.processEvents()
    assert received == [payload]

    worker.audit_persistence_after_reset()
    assert list(worker._jobs) == [("persistence_audit", None)]
    assert list(worker._urgent_jobs) == []
    assert list(worker._pending) == []


def test_header_unknown_badge_and_lock_survive_every_page_transition(window, qapp):
    win, _spy = window
    _seed_authoritative_connection(win)
    win._on_persistence_audit_status(_audit_payload())
    win.show()
    qapp.processEvents()

    assert "UNKNOWN" in win.lbl_persistence_badge.text().upper()
    assert win.lbl_persistence_badge.isVisible()
    assert win.btn_persistence_audit.isEnabled()

    expected = win.lbl_persistence_badge.text()
    for index in range(win.stack.count()):
        win._nav_to(index)
        qapp.processEvents()
        assert win.lbl_persistence_badge.isVisible(), index
        assert win.lbl_persistence_badge.text() == expected, index
        assert "UNKNOWN" in win.lbl_persistence_badge.text().upper(), index


def test_audit_button_is_enabled_only_for_connected_durable_unknown(window):
    win, _spy = window

    win._on_persistence_audit_status(_audit_payload(locked=False))
    win._set_connected_ui(False)
    assert not win.btn_persistence_audit.isEnabled()
    _seed_authoritative_connection(win)
    assert not win.btn_persistence_audit.isEnabled()

    win._on_persistence_audit_status(_audit_payload(locked=True))
    win._set_connected_ui(False)
    assert not win.btn_persistence_audit.isEnabled()
    assert "UNKNOWN" in win.lbl_persistence_badge.text().upper()

    _seed_authoritative_connection(win)
    assert win.btn_persistence_audit.isEnabled()


def test_motor_unknown_payload_keeps_record_and_query_only_audit_available(window):
    win, _spy = window
    _seed_authoritative_connection(win)
    payload = _audit_payload(locked=True, phase="MOTOR")

    win._on_persistence_audit_status(payload)

    assert win._persistence_audit_summary == payload
    assert win._persistence_audit_summary["record_id"] == "audit-record-001"
    assert win._persistence_audit_summary["ledger_error"] is None
    assert win.btn_persistence_audit.isEnabled()
    assert "MOTOR" in win.lbl_persistence_badge.text()


@pytest.mark.parametrize(
    ("phase", "cleared_attr", "retained_attr"),
    (
        ("P1", "_p1_gain_trial", "_vp_gain_trial"),
        ("P2", "_vp_gain_trial", "_p1_gain_trial"),
    ),
)
def test_resolved_audit_clears_only_its_corresponding_gui_gain_trial(
        window, phase, cleared_attr, retained_attr):
    win, _spy = window
    p1_trial = object()
    p2_trial = object()
    win._p1_gain_trial = p1_trial
    win._vp_gain_trial = p2_trial

    win._on_persistence_audit_status(
        _audit_payload(locked=False, phase=phase))

    assert getattr(win, cleared_attr) is None
    expected_retained = p2_trial if retained_attr == "_vp_gain_trial" else p1_trial
    assert getattr(win, retained_attr) is expected_retained


@pytest.mark.parametrize(
    ("phase", "status", "profile"),
    (("P1", "RESOLVED_APPLIED_PROFILE", "APPLIED PROFILE"),
     ("P2", "RESOLVED_ORIGINAL_PROFILE", "ORIGINAL PROFILE")),
)
def test_resolved_audit_keeps_profile_and_no_motion_claim_visible(
        window, phase, status, profile):
    win, _spy = window

    win._on_persistence_audit_status(
        _audit_payload(locked=False, phase=phase, status=status))

    message = win.tune_status.text().upper()
    assert "RESOLVED" in message
    assert phase in message
    assert profile in message
    assert "MOTION AUTHORITY NOT GRANTED" in message


@pytest.mark.parametrize("signal_name", ("connected", "failed", "stopped"))
def test_superseded_worker_lifecycle_signal_cannot_mutate_current_ui(
        window, qapp, signal_name):
    win, current_worker = window
    stale_worker = _WorkerEmitter()
    signal = getattr(stale_worker, signal_name)
    slot = getattr(win, "_on_%s" % signal_name)
    signal.connect(slot, QtCore.Qt.ConnectionType.QueuedConnection)

    win._connected_identity = {"fw": "CURRENT_FW", "generation": "current"}
    win.lbl_fw.setText("CURRENT_FW")
    win.worker = stale_worker
    if signal_name == "connected":
        win._set_connected_ui(False)
        signal.emit({"fw": "STALE_FW", "target_type": "stale"})
        expected_connected = False
    elif signal_name == "failed":
        win._set_connected_ui(True)
        signal.emit("stale connection failure")
        expected_connected = True
    else:
        win._set_connected_ui(True)
        signal.emit()
        expected_connected = True

    # The signal was queued while this was the active worker, but it is stale
    # by delivery time.  sender() must identify the superseded QObject.
    win.worker = current_worker
    qapp.processEvents()

    assert win.worker is current_worker
    assert win._ui_connected is expected_connected
    assert win._connected_identity == {
        "fw": "CURRENT_FW", "generation": "current"}
    assert win.lbl_fw.text() == "CURRENT_FW"


@pytest.mark.parametrize("signal_name", ("connected", "failed", "stopped"))
def test_current_worker_lifecycle_signal_is_still_accepted(
        window, qapp, signal_name):
    """Negative control: the generation guard must not drop the live sender."""
    win, _spy = window
    current_worker = _WorkerEmitter()
    win.worker = current_worker
    signal = getattr(current_worker, signal_name)
    slot = getattr(win, "_on_%s" % signal_name)
    signal.connect(slot, QtCore.Qt.ConnectionType.QueuedConnection)

    if signal_name == "connected":
        win._set_connected_ui(False)
        signal.emit(_connected_info(win, fw="CURRENT_FW"))
    elif signal_name == "failed":
        win._set_connected_ui(True)
        win._connected_identity = {"fw": "BEFORE_FAILURE"}
        signal.emit("current connection failure")
    else:
        win._set_connected_ui(True)
        win._connected_identity = {"fw": "BEFORE_STOP"}
        signal.emit()
    qapp.processEvents()

    if signal_name == "connected":
        assert win._ui_connected is True
        assert win._connected_identity["fw"] == "CURRENT_FW"
    else:
        assert win._ui_connected is False
        assert win._connected_identity == {}


def test_superseded_worker_motor_params_cannot_overwrite_current_target(
        window, qapp):
    win, current_worker = window
    stale_worker = _WorkerEmitter()
    stale_worker.motor_params.connect(
        win._on_motor_params, QtCore.Qt.ConnectionType.QueuedConnection)

    win._ca18 = 123456
    win.motor_fields["peak"].setText("CURRENT_PEAK")
    win.motor_fields["cont"].setText("CURRENT_CONT")
    win.motor_fields["maxspeed"].setText("CURRENT_SPEED")
    win.motor_fields["poles"].setText("CURRENT_POLES")
    current_type = win.motor_type_combo.currentData()

    win.worker = stale_worker
    stale_worker.motor_params.emit({
        "ca18": 999,
        "mtype": 3,
        "peak_arms": 9.9,
        "cont_arms": 8.8,
        "rpm": 7777,
        "poles": 66,
    })
    win.worker = current_worker
    qapp.processEvents()

    assert win.worker is current_worker
    assert win._ca18 == 123456
    assert win.motor_fields["peak"].text() == "CURRENT_PEAK"
    assert win.motor_fields["cont"].text() == "CURRENT_CONT"
    assert win.motor_fields["maxspeed"].text() == "CURRENT_SPEED"
    assert win.motor_fields["poles"].text() == "CURRENT_POLES"
    assert win.motor_type_combo.currentData() == current_type


def test_current_worker_motor_params_are_still_accepted(window, qapp):
    win, _spy = window
    current_worker = _WorkerEmitter()
    current_worker.motor_params.connect(
        win._on_motor_params, QtCore.Qt.ConnectionType.QueuedConnection)
    win.worker = current_worker

    current_worker.motor_params.emit({
        "ca18": 8192,
        "mtype": 3,
        "peak_arms": 2.5,
        "cont_arms": 1.5,
        "rpm": 3000,
        "poles": 4,
    })
    qapp.processEvents()

    assert win._ca18 == 8192
    assert win.motor_fields["peak"].text() == "2.50"
    assert win.motor_fields["cont"].text() == "1.50"
    assert win.motor_fields["maxspeed"].text() == "3000"
    assert win.motor_fields["poles"].text() == "4"
    assert win.motor_type_combo.currentData() == 3


@pytest.mark.parametrize("signal_name", ("feedback", "telemetry"))
def test_superseded_worker_target_data_signal_is_ignored(
        window, qapp, signal_name):
    win, current_worker = window
    stale_worker = _WorkerEmitter()
    signal = getattr(stale_worker, signal_name)
    signal.connect(
        getattr(win, "_on_%s" % signal_name),
        QtCore.Qt.ConnectionType.QueuedConnection)

    if signal_name == "feedback":
        win._fb_connected = False
        win._fb_raws = {"CURRENT": 1}
        win.fb_fields["counts"].setText("CURRENT_COUNTS")
        payload = {
            "params": {"STALE": 2}, "sensor_id": 1,
            "commut_method": 2, "counts_rev": 999,
            "pos_socket": 1, "vel_socket": 1, "commut_socket": 1,
        }
    else:
        win.m_pos.setText("CURRENT_POS")
        win._last_mo = 0
        payload = {"pos": 999, "pos_err": 9, "vel": 88, "iq": 7, "mo": 1}

    win.worker = stale_worker
    signal.emit(payload)
    win.worker = current_worker
    qapp.processEvents()

    if signal_name == "feedback":
        assert win._fb_connected is False
        assert win._fb_raws == {"CURRENT": 1}
        assert win.fb_fields["counts"].text() == "CURRENT_COUNTS"
    else:
        assert win.m_pos.text() == "CURRENT_POS"
        assert win._last_mo == 0


def _seed_applicable_tuning_results(win):
    # Include the candidate gains the Apply confirmation dialog formats, so the
    # reachable (unlocked) Apply path can render its prompt.
    win._at_result = SimpleNamespace(
        status=app_main.autotune_current.GREEN,
        kp_v_per_a=1.0, ki_hz=200.0)
    win._vp_result = SimpleNamespace(
        status=app_main.autotune_velpos.GREEN,
        kp_vel=1.0e-4, ki_vel_hz=10.0, kp_pos=80.0)
    generation = getattr(win, "_tuning_authority_generation", 0)
    win._at_result_generation = generation
    win._vp_result_generation = generation
    _seed_authoritative_connection(win)
    # EAS-parity RAM Apply → Drive is unlocked: an applicable GREEN result at an
    # admitted SUPERVISED / MO=0 connection offers Apply (reversible, no SV).
    assert win.btn_tune_apply.isEnabled()
    assert win.btn_tune_vp_apply.isEnabled()
    assert "Drive RAM" in win.btn_tune_apply.text()
    assert "Drive RAM" in win.btn_tune_vp_apply.text()


def test_gain_apply_ui_requires_confirmation_and_no_trial_on_decline(
        window, monkeypatch):
    win, _spy = window
    _seed_applicable_tuning_results(win)
    seen = {"asked": 0}

    def _decline(*_args, **_kwargs):
        seen["asked"] += 1
        return QtWidgets.QMessageBox.StandardButton.No

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", _decline)

    win._apply_autotune_clicked()
    win._apply_velpos_clicked()

    # Apply is reachable now, but a declined confirmation creates no RAM trial.
    assert seen["asked"] == 2
    assert win._tune_dispatch_inflight is None
    assert win._p1_gain_trial is None
    assert win._vp_gain_trial is None


def test_apply_controls_do_not_claim_locked_while_save_does(window):
    win, _spy = window
    # Apply → Drive RAM is a real, reachable write now: its tooltip must not
    # tell the operator it is locked (an energizing-tool safety-message defect).
    for name in ("btn_tune_apply", "btn_tune_vp_apply"):
        tip = getattr(win, name).toolTip().lower()
        assert "locked" not in tip, (name, tip)
        assert "ram" in tip, (name, tip)
    # The durable SV write is still locked and must still say so.
    for name in ("btn_tune_p1_save", "btn_tune_vp_save"):
        assert "locked" in getattr(win, name).toolTip().lower(), name


def test_expert_mode_banner_reflects_ram_apply_unlocked(window):
    win, _spy = window
    win._show_tuning_mode("expert")
    assert "LOCKED" not in win.lbl_tuning_mode_risk.text().upper()
    note = win.tuning_mode_note.text()
    assert "RAM" in note
    assert "Save" in note and "lock" in note.lower()  # SV still called out as locked


@pytest.mark.parametrize(
    ("click", "begin_attr", "result_attr"),
    (
        ("_apply_autotune_clicked", "p1_begin_calls", "_at_result"),
        ("_apply_velpos_clicked", "p2_begin_calls", "_vp_result"),
    ),
)
def test_confirmed_ram_apply_dispatches_reversible_trial(
        window, monkeypatch, click, begin_attr, result_attr):
    win, spy = window
    _seed_applicable_tuning_results(win)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        lambda *_args, **_kwargs: QtWidgets.QMessageBox.StandardButton.Yes)

    getattr(win, click)()

    # The confirmed RAM Apply dispatches exactly the applicable result as a
    # reversible RAM trial, and never touches the durable SV commit path.
    calls = getattr(spy, begin_attr)
    assert len(calls) == 1
    assert calls[0] is getattr(win, result_attr)
    assert win._tune_dispatch_inflight is not None
    assert spy.p1_commit_calls == []


def _assert_tuning_result_authority_invalidated(win):
    assert win._at_result is None
    assert win._vp_result is None
    assert not win.btn_tune_apply.isEnabled()
    assert not win.btn_tune_vp_apply.isEnabled()


def test_motor_profile_request_invalidates_cached_p1_p2_apply_authority(
        window, monkeypatch):
    win, spy = window
    _seed_applicable_tuning_results(win)
    generation_before = win._tuning_authority_generation
    win._ca18 = 65536
    win.motor_fields["peak"].setText("2.0")
    win.motor_fields["cont"].setText("1.0")
    win.motor_fields["maxspeed"].setText("3000")
    win.motor_fields["poles"].setText("4")
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        lambda *_args, **_kwargs: QtWidgets.QMessageBox.StandardButton.Yes)

    win._write_motor()

    assert len(spy.motor_writes) == 1
    assert win._tuning_authority_generation > generation_before
    _assert_tuning_result_authority_invalidated(win)


def test_motor_profile_result_independently_invalidates_cached_apply_authority(
        window):
    win, _spy = window
    _seed_applicable_tuning_results(win)
    generation_before = win._tuning_authority_generation

    win._on_write_result(True, "saved")
    _seed_authoritative_connection(win)

    assert win._tuning_authority_generation > generation_before
    _assert_tuning_result_authority_invalidated(win)


def test_disconnect_reconnect_generation_cannot_reactivate_cached_results(
        window):
    win, _spy = window
    _seed_applicable_tuning_results(win)
    initial_generation = win._tuning_authority_generation

    win._on_stopped()
    stopped_generation = win._tuning_authority_generation
    win._on_connected(_connected_info(win, fw="NEXT_FW"))

    assert win._ui_connected is True
    assert initial_generation < stopped_generation < win._tuning_authority_generation
    _assert_tuning_result_authority_invalidated(win)


@pytest.mark.parametrize(
    ("signal_name", "slot_name", "dispatch_kind", "result_attr", "button_name", "result"),
    (
        ("autotune_result", "_on_autotune_result", "p1", "_at_result",
         "btn_tune_apply",
         app_main.autotune_current.AutotuneResult(
             status=app_main.autotune_current.GREEN)),
        ("velpos_result", "_on_velpos_result", "p2", "_vp_result",
         "btn_tune_vp_apply",
         app_main.autotune_velpos.AutotuneVPResult(
             status=app_main.autotune_velpos.GREEN)),
    ),
)
def test_old_worker_delayed_tuning_result_after_reconnect_is_ignored(
        window, qapp, signal_name, slot_name, dispatch_kind, result_attr,
        button_name, result):
    win, _spy = window
    stale_worker = _WorkerEmitter()
    current_worker = _WorkerEmitter()
    signal = getattr(stale_worker, signal_name)
    signal.connect(
        getattr(win, slot_name), QtCore.Qt.ConnectionType.QueuedConnection)

    win.worker = stale_worker
    assert win._claim_tune_dispatch(dispatch_kind)
    signal.emit(result)
    win.worker = current_worker
    win._on_connected(_connected_info(
        win, fw="CURRENT_FW", target_type="current"))
    qapp.processEvents()

    assert getattr(win, result_attr) is None
    assert not getattr(win, button_name).isEnabled()
    assert win._tune_dispatch_inflight is None


@pytest.mark.parametrize(
    ("signal_name", "slot_name", "dispatch_kind", "result_attr", "button_name", "result"),
    (
        ("autotune_result", "_on_autotune_result", "p1", "_at_result",
         "btn_tune_apply",
         app_main.autotune_current.AutotuneResult(
             status=app_main.autotune_current.GREEN)),
        ("velpos_result", "_on_velpos_result", "p2", "_vp_result",
         "btn_tune_vp_apply",
         app_main.autotune_velpos.AutotuneVPResult(
             status=app_main.autotune_velpos.GREEN)),
    ),
)
def test_current_worker_matching_dispatch_generation_result_is_accepted(
        window, qapp, monkeypatch, signal_name, slot_name, dispatch_kind,
        result_attr, button_name, result):
    win, _spy = window
    current_worker = _WorkerEmitter()
    signal = getattr(current_worker, signal_name)
    signal.connect(
        getattr(win, slot_name), QtCore.Qt.ConnectionType.QueuedConnection)
    monkeypatch.setattr(win, "_dump_autotune_result", lambda _res: None)
    monkeypatch.setattr(win, "_dump_velpos_result", lambda _res: None)
    win.worker = current_worker
    _seed_authoritative_connection(win)
    generation = win._tuning_authority_generation

    assert win._claim_tune_dispatch(dispatch_kind)
    signal.emit(result)
    qapp.processEvents()

    assert getattr(win, result_attr) is result
    assert getattr(win, "%s_generation" % result_attr) == generation
    button = getattr(win, button_name)
    assert button.isEnabled()
    assert "Drive RAM" in button.text()
    assert "drive RAM" in button.toolTip()
    assert win._tune_dispatch_inflight is None


@pytest.mark.parametrize(
    ("signal_name", "slot_name", "trial_attr"),
    (
        ("current_gain_action", "_on_current_gain_action", "_p1_gain_trial"),
        ("velpos_gain_action", "_on_velpos_gain_action", "_vp_gain_trial"),
    ),
)
def test_old_worker_delayed_gain_begin_after_reconnect_cannot_refill_trial(
        window, qapp, signal_name, slot_name, trial_attr):
    win, _spy = window
    stale_worker = _WorkerEmitter()
    current_worker = _WorkerEmitter()
    signal = getattr(stale_worker, signal_name)
    signal.connect(
        getattr(win, slot_name), QtCore.Qt.ConnectionType.QueuedConnection)
    trial = SimpleNamespace(persistence_state="RAM_TRIAL", restore_only=False)

    win.worker = stale_worker
    signal.emit("begin", True, "stale begin", trial)
    win.worker = current_worker
    win._on_connected(_connected_info(
        win, fw="CURRENT_FW", target_type="current"))
    qapp.processEvents()

    assert getattr(win, trial_attr) is None
    assert not win.btn_tune_p1_save.isEnabled()
    assert not win.btn_tune_vp_save.isEnabled()


def test_p1_save_stays_disabled_and_direct_handler_rejects_before_dialog(
        window, monkeypatch):
    win, spy = window
    _seed_authoritative_connection(win)
    trial = SimpleNamespace(
        persistence_state="RAM_TRIAL", restore_only=False)
    win._p1_gain_trial = trial
    win._p1_trial_generation = win._tuning_authority_generation
    win._set_connected_ui(True)

    def dialog_must_not_open(*_args, **_kwargs):
        raise AssertionError("unverified P1 Save opened a confirmation dialog")

    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question", dialog_must_not_open)

    assert not win.btn_tune_p1_save.isEnabled()
    win._save_current_clicked()

    assert spy.p1_commit_calls == []
    assert win._tune_dispatch_inflight is None


def test_autotune_smoke_matches_production_gain_lock_without_writing_media(
        window, qapp, monkeypatch):
    win, _spy = window
    monkeypatch.setattr(win, "_dump_autotune_result", lambda _result: None)
    saved_paths = []
    monkeypatch.setattr(
        win, "grab",
        lambda: SimpleNamespace(save=lambda path: saved_paths.append(path) or True))

    assert app_main._smoke_autotune(qapp, win) == 0
    assert saved_paths


def test_current_worker_late_tuning_results_during_motor_write_are_ignored(
        window, qapp):
    win, _spy = window
    current_worker = _WorkerEmitter()
    current_worker.autotune_result.connect(
        win._on_autotune_result, QtCore.Qt.ConnectionType.QueuedConnection)
    current_worker.velpos_result.connect(
        win._on_velpos_result, QtCore.Qt.ConnectionType.QueuedConnection)
    win.worker = current_worker
    win._motor_write_inflight = True
    _seed_authoritative_connection(win)

    current_worker.autotune_result.emit(
        app_main.autotune_current.AutotuneResult(
            status=app_main.autotune_current.GREEN))
    current_worker.velpos_result.emit(
        app_main.autotune_velpos.AutotuneVPResult(
            status=app_main.autotune_velpos.GREEN))
    qapp.processEvents()

    _assert_tuning_result_authority_invalidated(win)


@pytest.mark.parametrize(
    ("signal_name", "slot_name", "trial_attr"),
    (
        ("current_gain_action", "_on_current_gain_action", "_p1_gain_trial"),
        ("velpos_gain_action", "_on_velpos_gain_action", "_vp_gain_trial"),
    ),
)
def test_current_worker_late_gain_begin_during_motor_write_is_ignored(
        window, qapp, signal_name, slot_name, trial_attr):
    win, _spy = window
    current_worker = _WorkerEmitter()
    signal = getattr(current_worker, signal_name)
    signal.connect(
        getattr(win, slot_name), QtCore.Qt.ConnectionType.QueuedConnection)
    win.worker = current_worker
    win._motor_write_inflight = True
    _seed_authoritative_connection(win)

    signal.emit(
        "begin", True, "late begin",
        SimpleNamespace(persistence_state="RAM_TRIAL", restore_only=False))
    qapp.processEvents()

    assert getattr(win, trial_attr) is None


def test_tuning_dispatch_disables_and_blocks_motor_save(
        window, monkeypatch):
    win, spy = window
    _seed_authoritative_connection(win)
    assert win.btn_motor_write.isEnabled()
    assert win._claim_tune_dispatch("p1")

    assert not win.btn_motor_write.isEnabled()
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "question",
        lambda *_args, **_kwargs: pytest.fail(
            "Motor confirmation must not open during tuning dispatch"))
    win._write_motor()

    assert spy.motor_writes == []


def test_motor_write_inflight_disables_and_blocks_all_tuning_starts(window):
    win, _spy = window
    _seed_applicable_tuning_results(win)
    win._motor_write_inflight = True
    _seed_authoritative_connection(win)

    for name in (
            "btn_tune", "btn_tune_signature", "btn_tune_vp",
            "btn_tune_verify", "btn_tune_apply", "btn_tune_vp_apply"):
        assert not getattr(win, name).isEnabled(), name
    assert not win._claim_tune_dispatch("p1")
    assert win._tune_dispatch_inflight is None


def test_p2_verify_button_requires_current_connection_commutation_signature(
        window):
    win, _spy = window
    _seed_authoritative_connection(win)

    assert not win._motion_signature_green
    assert not win.btn_tune_verify.isEnabled()


def test_p2_verify_direct_ui_path_rejects_before_confirmation_or_dispatch(
        window, monkeypatch):
    win, spy = window
    _seed_authoritative_connection(win)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "warning",
        lambda *_args, **_kwargs: pytest.fail(
            "verification confirmation must not open without signature GREEN"))

    win._run_verify_clicked()

    assert spy.verify_calls == []
    assert win._tune_dispatch_inflight is None


def test_p2_verify_dispatch_carries_current_signature_token(
        window, monkeypatch):
    win, spy = window
    _seed_phase2_run_authority(win)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "warning",
        lambda *_args, **_kwargs:
        QtWidgets.QMessageBox.StandardButton.Yes)

    win._run_verify_clicked()

    assert len(spy.verify_calls) == 1
    _kw, _trial, token = spy.verify_calls[0]
    assert token == win._motion_signature_token


def test_p2_verify_revoked_during_confirmation_never_dispatches(
        window, monkeypatch):
    win, spy = window
    _seed_phase2_run_authority(win)

    def revoke_while_modal(*_args, **_kwargs):
        win._on_motion_authority(False, "signature revoked in modal")
        return QtWidgets.QMessageBox.StandardButton.Yes

    monkeypatch.setattr(
        QtWidgets.QMessageBox, "warning", revoke_while_modal)

    win._run_verify_clicked()

    assert spy.verify_calls == []
    assert win._tune_dispatch_inflight is None


def test_p2_verify_stale_candidate_generation_rejects_before_confirmation(
        window, monkeypatch):
    win, spy = window
    _seed_phase2_run_authority(win)
    win._advance_tuning_authority_generation()
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "warning",
        lambda *_args, **_kwargs: pytest.fail(
            "stale signature generation must reject before confirmation"))

    win._run_verify_clicked()

    assert spy.verify_calls == []
    assert win._tune_dispatch_inflight is None


def test_reconnected_retained_p2_trial_is_restore_only_in_ui(window):
    win, _spy = window
    _seed_authoritative_connection(win)
    trial = SimpleNamespace(persistence_state="RAM_TRIAL", restore_only=False)
    win._on_velpos_gain_action("begin", True, "RAM trial", trial)
    trial_generation = win._vp_trial_generation
    win._vp_trial_verified_green = True
    win._vp_verified_trial = trial
    win._vp_verified_generation = trial_generation
    _seed_authoritative_connection(win)
    assert not win.btn_tune_vp_save.isEnabled()

    win._on_stopped()
    win._on_connected(_connected_info(win, fw="NEXT_FW"))

    assert win._vp_gain_trial is trial
    assert trial_generation < win._tuning_authority_generation
    assert win.btn_tune_vp_restore.isEnabled()
    assert not win.btn_tune_verify.isEnabled()
    assert not win.btn_tune_vp_save.isEnabled()


def test_unknown_locks_hardware_write_controls_but_preserves_escape_and_audit(
        window, qapp):
    win, _spy = window
    _seed_phase2_run_authority(win)

    # Give Recorder Stop a real pre-lock reason to be enabled.  Persistence
    # recovery must not suppress an already-needed recorder escape.
    win._recorder_ui_state = "RECORDING"
    win._update_recorder_controls()
    assert win.btn_rec_stop.isEnabled()

    # Negative control: these are ordinary connected controls before the lock.
    for name in (
            "btn_motor_write", "btn_zero", "btn_tune",
            "btn_tune_signature", "btn_tune_vp"):
        assert getattr(win, name).isEnabled(), name
    # Feedback direct persistence has its own stronger fail-closed contract
    # and therefore remains disabled even while the drive is otherwise clear.
    assert not win.btn_fb_write.isEnabled()

    win._on_persistence_audit_status(_audit_payload())
    # Reapplying ONLINE state and switching pages must not accidentally undo
    # the durable lock through an older per-page control updater.
    _seed_authoritative_connection(win)
    for index in range(win.stack.count()):
        win._nav_to(index)
    qapp.processEvents()

    blocked_controls = (
        "btn_motor_write", "btn_fb_write", "btn_zero", "btn_motion_run",
        "btn_tune", "btn_tune_signature", "btn_tune_vp",
        "btn_tune_apply", "btn_tune_p1_restore", "btn_tune_p1_save",
        "btn_tune_vp_apply", "btn_tune_verify", "btn_tune_vp_restore",
        "btn_tune_vp_save", "btn_rec_signals", "btn_rec_immediate",
        "btn_rec_upload",
    )
    for name in blocked_controls:
        assert not getattr(win, name).isEnabled(), name

    for name in (
            "btn_conn", "btn_axis_refresh", "btn_motion_stop",
            "btn_global_stop", "btn_rec_stop", "btn_persistence_audit"):
        assert getattr(win, name).isEnabled(), name

    assert "Disconnect" in win.btn_conn.text()
    assert "UNKNOWN" in win.lbl_persistence_badge.text().upper()


def _patch_attestation_dialog(monkeypatch, answer, seen):
    def static_dialog(*args, **_kwargs):
        seen.append(" ".join(str(arg) for arg in args[1:]))
        return answer

    def instance_dialog(box):
        seen.append("%s %s" % (box.windowTitle(), box.text()))
        return answer

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", static_dialog)
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", static_dialog)
    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", instance_dialog)


def test_explicit_reset_attestation_queues_exactly_one_read_only_audit(
        window, qapp, monkeypatch):
    win, spy = window
    _seed_authoritative_connection(win)
    win._on_persistence_audit_status(_audit_payload())
    dialogs = []
    _patch_attestation_dialog(
        monkeypatch, QtWidgets.QMessageBox.StandardButton.Yes, dialogs)

    win.btn_persistence_audit.click()
    qapp.processEvents()

    assert spy.audit_calls == 1
    assert dialogs, "audit must require an explicit reset/power-cycle attestation"
    wording = " ".join(dialogs).lower()
    assert "전원" in wording or "power" in wording
    assert "off" in wording and "on" in wording
    assert "읽기" in wording or "read-only" in wording or "read only" in wording


def test_cancelled_reset_attestation_never_queues_audit(
        window, qapp, monkeypatch):
    win, spy = window
    _seed_authoritative_connection(win)
    win._on_persistence_audit_status(_audit_payload())
    dialogs = []
    _patch_attestation_dialog(
        monkeypatch, QtWidgets.QMessageBox.StandardButton.Cancel, dialogs)

    win.btn_persistence_audit.click()
    qapp.processEvents()

    assert dialogs
    assert spy.audit_calls == 0
