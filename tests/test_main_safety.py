"""Offline safety tests for main.py worker-owned transaction boundaries."""

from types import SimpleNamespace
import time

import pytest

import main as app_main
from main import DriveWorker, SessionCoordinateError


class FakeLink:
    def __init__(self, *, pos=12345, fail_command=None):
        self.telemetry = {"mo": 0, "vel": 0.0, "iq": 0.0,
                          "pos": pos, "pos_err": 0}
        self.commands = []
        self.fail_command = fail_command

    def read_telemetry(self):
        return _with_sample_timing(dict(self.telemetry))

    def command(self, command):
        self.commands.append(command)
        if command == self.fail_command:
            raise RuntimeError("negative-control failure")
        if command == "TW[19]=1":
            self.telemetry["pos"] = 0
        elif command.startswith("PX="):
            self.telemetry["pos"] = int(command.split("=", 1)[1])
        return ""


def _with_sample_timing(sample, *, duration_s=0.001):
    """Attach one internally consistent raw-query timing envelope."""
    finished = time.monotonic()
    sample.update({
        "_sample_started_monotonic": finished - duration_s,
        "_sample_finished_monotonic": finished,
        "_sample_duration_s": duration_s,
    })
    return sample


def _full_disabled_telemetry(**overrides):
    sample = _with_sample_timing(
        {"pos": 42, "vel": 0.0, "pos_err": 0.0, "iq": 0.0, "mo": 0})
    sample.update(overrides)
    return sample


def _worker_with_fresh_px():
    worker = DriveWorker("COM_TEST")
    worker._connection_identity_verified = True
    worker._record_fresh_telemetry(_full_disabled_telemetry(pos=0))
    assert worker._session_coordinate_known
    return worker


class _HandshakeLink:
    """Offline link double for the worker's initial identity handshake."""

    def __init__(self, *, fw="firmware", pal="90", boot="boot",
                 identity="elmo-sn4-sha256:" + "a" * 64):
        self.values = {"VR": fw, "VP": pal, "VB": boot}
        self.identity = identity
        self.commands = []
        self.disconnected = False

    def connect(self):
        return True

    def command(self, command, **_kwargs):
        self.commands.append(command)
        assert "=" not in command and command != "SV"
        return self.values.get(command, "0")

    def transaction_identity(self):
        return self.identity

    @staticmethod
    def persistence_status():
        return {
            "status": "CLEAR",
            "resolved": True,
            "detail": "offline fixture",
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

    def disconnect(self):
        self.disconnected = True


@pytest.mark.parametrize("missing", ["fw", "pal", "boot", "drive_identity"])
def test_initial_handshake_missing_identity_field_fails_closed(monkeypatch, missing):
    values = {
        "fw": "Twitter 01.01.16.00",
        "pal": "90",
        "boot": "DSP Boot 1.0.1.6",
        "drive_identity": "elmo-sn4-sha256:" + "a" * 64,
    }
    values[missing] = None
    link = _HandshakeLink(
        fw=values["fw"], pal=values["pal"], boot=values["boot"],
        identity=values["drive_identity"])
    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)

    worker = DriveWorker("COM_TEST")
    connected, failed = [], []
    worker.connected.connect(connected.append)
    worker.failed.connect(failed.append)
    worker.run()

    assert connected == [], "an incomplete initial identity must never publish ONLINE"
    assert failed, "the rejected initial identity must publish an explicit failure"


def test_initial_handshake_non_hex_identity_fails_closed(monkeypatch):
    link = _HandshakeLink(
        identity="elmo-sn4-sha256:" + ("g" * 64))
    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)

    worker = DriveWorker("COM_TEST")
    connected, failed = [], []
    worker.connected.connect(connected.append)
    worker.failed.connect(failed.append)
    worker.run()

    assert connected == []
    assert failed
    assert link.disconnected is True


@pytest.mark.parametrize(
    "raw_status",
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
def test_worker_malformed_persistence_status_stays_read_only_locked_and_cleans_up(
        monkeypatch, raw_status):
    worker = DriveWorker("COM_TEST")

    class BadPersistenceLink(_HandshakeLink):
        def read_telemetry(self):
            return _full_disabled_telemetry()

        def persistence_status(self):
            return raw_status

    link = BadPersistenceLink()
    connected = []
    terminal = []

    def stop_after_read_only_admission(info):
        connected.append(info)
        worker.stop()

    worker.connected.connect(stop_after_read_only_admission)
    worker.stopped.connect(lambda: terminal.append(True))
    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)

    worker.run()

    assert len(connected) == 1
    locked = connected[0]["persistence_status"]
    assert locked["status"] == "LEDGER_STATUS_FAILED"
    assert locked["lock_active"] is True
    assert locked["resolved"] is False
    assert worker._persistence_recovery_unknown
    assert worker._trial_job_guard("axis_read", None) == (True, "")
    allowed, detail = worker._trial_job_guard("motor_write", {})
    assert not allowed and "Persistence UNKNOWN" in detail
    assert terminal == [True]
    assert link.disconnected


def test_worker_trial_allowlist_and_exact_p2_identity():
    worker = _worker_with_fresh_px()
    current = object()
    foreign = object()
    worker._vp_gain_trial = current

    assert worker._trial_job_guard("verify_vp", ({}, current))[0]
    assert worker._trial_job_guard("vp_trial_restore", current)[0]
    assert worker._trial_job_guard("vp_trial_commit", current)[0]

    for kind, payload in (
            ("verify_vp", ({}, foreign)),
            ("vp_trial_restore", foreign),
            ("vp_trial_commit", foreign),
            ("velpos", {}),
            ("encoder_maint", []),
            ("p1_trial_restore", foreign)):
        allowed, message = worker._trial_job_guard(kind, payload)
        assert not allowed
        assert message


def test_stop_escape_is_allowed_through_all_worker_uncertainty_latches():
    worker = DriveWorker("COM_TEST")
    worker._motion_config_unknown = True
    worker._encoder_maintenance_reconnect_required = True
    worker._session_coordinate_known = False
    worker._p1_gain_trial = SimpleNamespace(persistence_state="UNKNOWN")

    assert worker._trial_job_guard("motion_stop", None) == (True, "")
    worker.request_motion_stop()
    assert worker._motion_cancel and worker._cancel_at
    assert worker._urgent_jobs.popleft()[0] == "motion_stop"


def test_live_ptp_worker_gate_is_fail_closed_before_link_io(monkeypatch):
    assert app_main.FINITE_PTP_LIVE_ENABLED is False

    class NoIoLink:
        def command(self, *_args, **_kwargs):
            raise AssertionError("live gate must reject before drive I/O")

    worker = DriveWorker("COM_TEST")
    emitted = []
    worker.motion_result.connect(lambda action, result: emitted.append((action, result)))
    worker._run_position_move(NoIoLink(), object())

    assert not worker._motion_ownership_requested
    assert emitted and emitted[0][0] == "move"
    assert emitted[0][1].status == app_main.single_axis_motion.RED
    assert "NEED-DATA" in emitted[0][1].reason


def test_pending_recorder_blocks_conflicting_jobs_but_not_stop_or_upload():
    worker = _worker_with_fresh_px()
    worker._recorder_active = True

    for kind, payload in (
            ("motion_move", object()), ("autotune", {}),
            ("velpos", {}), ("motor_write", {}), ("recorder_start", object()),
            ("recorder_discover", None)):
        allowed, message = worker._trial_job_guard(kind, payload)
        assert not allowed and "Recorder" in message
    for kind in ("motion_stop", "recorder_stop", "recorder_upload", "axis_read"):
        assert worker._trial_job_guard(kind, None)[0]


def test_recorder_cancel_is_not_confused_with_motion_stop():
    class RecorderLink:
        def __init__(self):
            self.calls = []

        def record_stop(self):
            self.calls.append("record_stop")
            return True

        def command(self, *_args, **_kwargs):
            raise AssertionError("Recorder cancel must not issue ST/MO")

    worker = DriveWorker("COM_TEST")
    worker._recorder_active = True
    link = RecorderLink()
    worker._run_recorder_stop(link)

    assert link.calls == ["record_stop"]
    assert not worker._recorder_active


def test_recorder_stop_invalidates_queued_and_stop_pending_starts():
    class RecorderLink:
        def __init__(self):
            self.calls = []

        def record_stop(self):
            self.calls.append("STOP")
            return False

        def command(self, command, **_kwargs):
            self.calls.append(command)
            return "50"

        def record_start(self, *_args, **_kwargs):
            self.calls.append("START")

    request = app_main.recorder_control.RecorderRequest(
        ("Position",), resolution_us=200.0, record_time_s=0.1)
    worker = DriveWorker("COM_TEST")
    worker.start_recorder(request)
    first_payload = worker._jobs.popleft()[1]
    worker.request_recorder_stop()
    # A second request made while STOP is pending must also be invalidated.
    worker.start_recorder(request)
    second_payload = worker._jobs.popleft()[1]
    link = RecorderLink()
    worker._run_recorder_stop(link)
    worker._run_recorder_start(link, first_payload)
    worker._run_recorder_start(link, second_payload)

    assert link.calls == ["STOP"]
    assert worker._recorder_last_status == "IDLE"


def test_recorder_status_failure_keeps_fail_closed_ownership():
    class BrokenStatus:
        def record_status(self):
            raise OSError("negative-control status failure")

    worker = DriveWorker("COM_TEST")
    worker._recorder_active = True
    worker._recorder_ready = True
    worker._recorder_resolved = object()
    states = []
    worker.recorder_status_changed.connect(
        lambda state, detail: states.append((state, detail)))
    worker._poll_recorder(BrokenStatus())

    assert worker._recorder_active
    assert not worker._recorder_ready
    assert worker._recorder_resolved is not None
    assert states[-1][0] == "STALE_CONNECTION_UNKNOWN"


def test_upload_failure_remains_retryable_and_cancellable():
    class BrokenUpload:
        def command(self, command, **_kwargs):
            return {"MO": "0", "SO": "0", "VX": "0"}[command]

        def record_upload(self):
            raise OSError("negative-control upload failure")

    worker = DriveWorker("COM_TEST")
    worker._recorder_active = True
    worker._recorder_ready = True
    worker._recorder_resolved = object()
    states = []
    worker.recorder_status_changed.connect(
        lambda state, detail: states.append((state, detail)))
    worker._run_recorder_upload(BrokenUpload())

    assert worker._recorder_active and worker._recorder_ready
    assert states[-1][0] == "READY_TO_UPLOAD"
    assert "Retry" in states[-1][1]


def test_recorder_completion_emits_capture_id_and_worker_generation_token():
    worker = DriveWorker("COM_TEST")
    resolved = app_main.recorder_control.ResolvedRecorderRequest(
        signals=("Position",),
        requested_resolution_us=200.0,
        actual_resolution_us=200.0,
        time_resolution=4,
        requested_record_time_s=0.0002,
        actual_record_time_s=0.0002,
        length_per_signal=1,
        total_buffer_samples=1,
        trigger="immediate",
    )
    worker._recorder_generation = 7
    worker._recorder_active = True
    worker._recorder_ready = True
    worker._recorder_resolved = resolved
    worker._recorder_manifest_current = {
        "capture_id": "capture-token-001",
        "worker_generation": 7,
    }
    events = []
    worker.recorder_data.connect(
        lambda data, request, token: events.append((data, request, token)))

    class Link:
        @staticmethod
        def command(command, **_kwargs):
            return {"MO": "0", "SO": "0", "VX": "0"}[command]

        @staticmethod
        def record_upload():
            return {"dt": 0.0002, "Position": [1.0]}

    worker._run_recorder_upload(Link(), 7)

    assert len(events) == 1
    assert events[0][1] is resolved
    assert events[0][2] == {
        "capture_id": "capture-token-001", "worker_generation": 7}


def test_recorder_upload_click_locks_synchronously_before_enqueue():
    class WorkerStub:
        def __init__(self):
            self.upload_calls = 0

        @staticmethod
        def isRunning():
            return True

        def upload_recorder(self):
            self.upload_calls += 1

    class WindowStub:
        def __init__(self):
            self.worker = WorkerStub()
            self._recorder_ui_state = "READY_TO_UPLOAD"
            self.states = []
            self.flashes = []

        def _apply_recorder_status(self, state, detail, *, source_label):
            self._recorder_ui_state = state
            self.states.append((state, detail, source_label))

        def _flash(self, message):
            self.flashes.append(message)

    window = WindowStub()
    app_main.MainWindow._recorder_upload_clicked(window)
    app_main.MainWindow._recorder_upload_clicked(window)

    assert window.worker.upload_calls == 1
    assert window._recorder_ui_state == "UPLOADING"
    assert window.states[0][0] == "UPLOADING"


@pytest.mark.parametrize(
    "stop_error,expected_state",
    [(False, "CANCELLED"), (True, "CANCEL_FAILED_UNKNOWN")],
)
def test_recorder_stop_silently_supersedes_queued_upload(
        stop_error, expected_state):
    class Link:
        def __init__(self):
            self.calls = []

        def record_stop(self):
            self.calls.append("record_stop")
            if stop_error:
                raise OSError("negative-control stop failure")
            return True

        def command(self, *_args, **_kwargs):
            raise AssertionError("superseded upload must not reach drive I/O")

        def record_upload(self):
            raise AssertionError("superseded upload must not consume capture")

    worker = DriveWorker("COM_TEST")
    worker._recorder_generation = 7
    worker._recorder_active = True
    worker._recorder_ready = True
    worker._recorder_resolved = object()
    token = worker.upload_recorder()
    kind, upload_payload = worker._jobs.popleft()
    assert kind == "recorder_upload"
    assert token == upload_payload == 7

    worker.request_recorder_stop()
    states = []
    worker.recorder_status_changed.connect(
        lambda state, detail: states.append((state, detail)))
    link = Link()
    worker._drain_urgent_motion_jobs(link)
    worker._run_recorder_upload(link, upload_payload)

    assert link.calls == ["record_stop"]
    assert states[-1][0] == expected_state
    assert all(state not in ("ERROR", "UPLOADING") for state, _ in states)


def test_recorder_stop_during_stationary_gate_prevents_vendor_upload():
    worker = DriveWorker("COM_TEST")
    worker._recorder_generation = 3
    worker._recorder_active = True
    worker._recorder_ready = True
    worker._recorder_resolved = object()

    class Link:
        def __init__(self):
            self.uploaded = False

        def command(self, command, **_kwargs):
            if command == "VX":
                worker.request_recorder_stop()
            return "0"

        def record_upload(self):
            self.uploaded = True
            raise AssertionError("cancelled capture must not reach vendor upload")

    link = Link()
    worker._run_recorder_upload(link, 3)
    assert not link.uploaded
    assert worker._recorder_cancelled_through == 3


def test_recorder_stop_during_vendor_upload_discards_late_completed_bundle():
    worker = DriveWorker("COM_TEST")
    worker._recorder_generation = 4
    worker._recorder_active = True
    worker._recorder_ready = True
    worker._recorder_resolved = object()
    states, data_events = [], []
    worker.recorder_status_changed.connect(
        lambda state, detail: states.append((state, detail)))
    worker.recorder_data.connect(
        lambda data, resolved, token: data_events.append((data, resolved, token)))

    class Link:
        @staticmethod
        def command(_command, **_kwargs):
            return "0"

        @staticmethod
        def record_upload():
            worker.request_recorder_stop()
            return {"dt": 0.001, "Position": [1.0]}

        @staticmethod
        def record_stop():
            return False  # Upload already consumed the pending vendor handle.

    link = Link()
    worker._run_recorder_upload(link, 4)
    assert not data_events
    assert all(state != "COMPLETED" for state, _ in states)
    assert worker._recorder_upload_consumed_after_cancel

    worker._drain_urgent_motion_jobs(link)
    assert states[-1][0] == "CANCELLED"
    assert "discarded" in states[-1][1]
    assert not worker._recorder_upload_consumed_after_cancel


def test_start_reply_loss_keeps_recorder_ownership_fail_closed():
    class AmbiguousStart:
        def command(self, command, **_kwargs):
            assert command == "TS"
            return "50"

        @staticmethod
        def recorder_personality_provenance():
            return {}

        @staticmethod
        def recorder_library_provenance():
            return {}

        def record_start(self, *_args, **_kwargs):
            raise TimeoutError("side effect may have occurred")

    request = app_main.recorder_control.RecorderRequest(
        ("Position",), resolution_us=200.0, record_time_s=0.1)
    worker = DriveWorker("COM_TEST")
    states = []
    worker.recorder_status_changed.connect(
        lambda state, detail: states.append((state, detail)))
    worker._run_recorder_start(AmbiguousStart(), (1, request))

    assert worker._recorder_active
    assert worker._recorder_resolved is not None
    assert states[-1][0] == "START_OWNERSHIP_UNKNOWN"
    allowed, message = worker._trial_job_guard("motor_write", {})
    assert not allowed and "Recorder" in message


def test_blocking_recorder_io_requires_disabled_stationary_readback():
    class MovingLink:
        def command(self, command, **_kwargs):
            return {"MO": "0", "SO": "0", "VX": "1"}[command]

    with pytest.raises(RuntimeError, match="MO=0, SO=0, VX=0"):
        DriveWorker._require_disabled_stationary_recorder_io(MovingLink())


@pytest.mark.parametrize("bad_command,bad_value", [("MO", "0.5"), ("SO", "-0.5")])
def test_blocking_recorder_io_rejects_fractional_boolean_states(
        bad_command, bad_value):
    class FractionalLink:
        def command(self, command, **_kwargs):
            values = {"MO": "0", "SO": "0", "VX": "0"}
            values[bad_command] = bad_value
            return values[command]

    with pytest.raises(RuntimeError, match="MO=0, SO=0, VX=0"):
        DriveWorker._require_disabled_stationary_recorder_io(FractionalLink())


def test_motion_stop_latch_invalidates_moves_queued_until_stop_finishes():
    worker = DriveWorker("COM_TEST")
    first = worker.run_position_move(object())
    worker.request_motion_stop()
    second = worker.run_position_move(object())

    assert first == 1 and second == 2
    assert worker._motion_stop_requested
    assert worker._motion_cancelled_through == 2
    assert worker._jobs[0][1][0] <= worker._motion_cancelled_through
    assert worker._jobs[1][1][0] <= worker._motion_cancelled_through


def test_config_write_revokes_green_commutation_authority():
    worker = DriveWorker("COM_TEST")
    worker._commutation_signature_green = True
    events = []
    worker.motion_authority.connect(
        lambda allowed, detail: events.append((allowed, detail)))
    worker._invalidate_commutation_signature("Feedback write requested")

    assert not worker._commutation_signature_green
    assert events == [(False, "Feedback write requested")]


def test_worker_p1_phase_allows_only_exact_restore_or_commit():
    worker = _worker_with_fresh_px()
    current = object()
    worker._p1_gain_trial = current

    assert worker._trial_job_guard("p1_trial_restore", current)[0]
    assert worker._trial_job_guard("p1_trial_commit", current)[0]
    assert not worker._trial_job_guard("p1_trial_restore", object())[0]
    assert not worker._trial_job_guard("verify_vp", ({}, None))[0]
    assert not worker._trial_job_guard("soft_zero", None)[0]


@pytest.mark.parametrize("phase", ["P1", "P2"])
def test_worker_unknown_persistence_state_blocks_every_trial_action(phase):
    class UnknownTrial:
        persistence_state = "UNKNOWN"

    worker = _worker_with_fresh_px()
    trial = UnknownTrial()
    if phase == "P1":
        worker._p1_gain_trial = trial
        requests = (("p1_trial_restore", trial),
                    ("p1_trial_commit", trial))
    else:
        worker._vp_gain_trial = trial
        requests = (("verify_vp", ({}, trial)),
                    ("vp_trial_restore", trial),
                    ("vp_trial_commit", trial))
    for kind, payload in requests:
        allowed, message = worker._trial_job_guard(kind, payload)
        assert not allowed
        assert "UNKNOWN" in message


def test_new_worker_allows_only_restore_adoption_not_commit_or_verify():
    worker = _worker_with_fresh_px()
    retained = object()
    assert worker._trial_job_guard("p1_trial_restore", retained)[0]
    assert worker._trial_job_guard("vp_trial_restore", retained)[0]
    assert not worker._trial_job_guard("p1_trial_commit", retained)[0]
    assert not worker._trial_job_guard("vp_trial_commit", retained)[0]
    assert not worker._trial_job_guard("verify_vp", ({}, retained))[0]


def test_coordinate_unknown_latch_blocks_follow_on_jobs_until_fresh_read():
    worker = _worker_with_fresh_px()
    worker._session_coordinate_known = False
    for kind, payload in (
            ("soft_zero", None),
            ("encoder_maint", [{"id": "reset_errors", "socket": 1}]),
            ("autotune", {}),
            ("velpos", {}),
            ("p1_trial_begin", object()),
            ("vp_trial_begin", object())):
        allowed, message = worker._trial_job_guard(kind, payload)
        assert not allowed
        assert "UNKNOWN" in message
    worker._session_coordinate_known = True
    assert worker._trial_job_guard("soft_zero", None)[0]


def test_motion_requires_explicit_session_zero_not_only_fresh_px():
    worker = _worker_with_fresh_px()
    request = app_main.single_axis_motion.PositionMoveRequest(
        mode="relative", target_rev=0.01)

    allowed, message = worker._trial_job_guard("motion_move", (1, request))

    assert not allowed
    assert "Session Zero" in message
    worker._session_zero_confirmed = True
    assert worker._trial_job_guard("motion_move", (1, request)) == (True, "")


def test_phase2_requires_current_connection_commutation_signature():
    worker = _worker_with_fresh_px()

    allowed, message = worker._trial_job_guard("velpos", {"ramp_frac": 0.2})

    assert not allowed
    assert "Commutation Signature" in message
    # The signature acquisition job itself must remain reachable.
    assert worker._trial_job_guard(
        "velpos", {"signature_only": True}) == (True, "")
    worker._commutation_signature_green = True
    allowed, message = worker._trial_job_guard(
        "velpos", {"ramp_frac": 0.2})
    assert not allowed
    assert "Phase 1" in message
    assert worker._trial_job_guard(
        "velpos", {
            "ramp_frac": 0.2,
            "r_pp_ohm": 0.139,
            "l_pp_h": 41.6e-6,
        }) == (True, "")


@pytest.mark.parametrize("phase", ["P1", "P2"])
def test_restore_failed_and_restore_only_states_allow_exact_restore_only(phase):
    class Trial:
        persistence_state = "RESTORE_FAILED"
        restore_only = False

    worker = _worker_with_fresh_px()
    trial = Trial()
    if phase == "P1":
        worker._p1_gain_trial = trial
        restore_kind, commit_kind = "p1_trial_restore", "p1_trial_commit"
        verify_payload = ({}, None)
    else:
        worker._vp_gain_trial = trial
        restore_kind, commit_kind = "vp_trial_restore", "vp_trial_commit"
        verify_payload = ({}, trial)
    assert worker._trial_job_guard(restore_kind, trial)[0]
    assert not worker._trial_job_guard(commit_kind, trial)[0]
    assert not worker._trial_job_guard("verify_vp", verify_payload)[0]

    trial.persistence_state = "RAM_TRIAL"
    trial.restore_only = True
    assert worker._trial_job_guard(restore_kind, trial)[0]
    assert not worker._trial_job_guard(commit_kind, trial)[0]
    assert not worker._trial_job_guard("verify_vp", verify_payload)[0]


@pytest.mark.parametrize("phase", ["P1", "P2"])
def test_new_worker_adopts_retained_trial_for_restore_only(monkeypatch, phase):
    class RetainedTrial:
        transaction_id = "SN4:ABC"
        persistence_state = "RAM_TRIAL"
        restore_only = False

    class IdentityLink:
        def transaction_identity(self):
            return "SN4:ABC"

    trial = RetainedTrial()

    def adopt(link, candidate):
        if link.transaction_identity() != candidate.transaction_id:
            return False, "identity mismatch"
        candidate.restore_only = True
        return True, "same-device full readback matched applied gains"

    if phase == "P1":
        monkeypatch.setattr(
            app_main.autotune_current, "adopt_gain_trial_p1_for_restore", adopt,
            raising=False)
        attr = "_p1_gain_trial"
    else:
        monkeypatch.setattr(
            app_main.autotune_velpos, "adopt_gain_trial_vp_for_restore", adopt,
            raising=False)
        attr = "_vp_gain_trial"
    worker = DriveWorker("COM_TEST")
    ok, message, already_restored = worker._prepare_retained_trial_restore(
        IdentityLink(), phase, trial)
    assert ok and not already_restored
    assert "same-device" in message
    assert getattr(worker, attr) is trial
    assert trial.restore_only


def test_new_worker_rejects_retained_trial_from_different_identity(monkeypatch):
    class RetainedTrial:
        persistence_state = "RAM_TRIAL"
        restore_only = False

    def reject(_link, _trial):
        return False, "transaction identity mismatch"

    monkeypatch.setattr(
        app_main.autotune_velpos, "adopt_gain_trial_vp_for_restore", reject,
        raising=False)
    worker = DriveWorker("COM_TEST")
    trial = RetainedTrial()
    ok, message, already_restored = worker._prepare_retained_trial_restore(
        FakeLink(), "P2", trial)
    assert not ok and not already_restored
    assert "identity" in message
    assert worker._vp_gain_trial is None


def test_new_worker_accepts_already_restored_readback_without_active_adoption(monkeypatch):
    class RetainedTrial:
        persistence_state = "RAM_TRIAL"
        restore_only = False

    def already_restored(_link, trial):
        trial.persistence_state = "RESTORED"
        trial.restore_only = True
        return True, "original gains already present"

    monkeypatch.setattr(
        app_main.autotune_current, "adopt_gain_trial_p1_for_restore",
        already_restored, raising=False)
    worker = DriveWorker("COM_TEST")
    trial = RetainedTrial()
    ok, message, done = worker._prepare_retained_trial_restore(
        FakeLink(), "P1", trial)
    assert ok and done
    assert "already" in message
    assert worker._p1_gain_trial is None


@pytest.mark.parametrize("operations", [
    ["SV"],
    [{"id": "SV"}],
    [{"id": "set_datum_shift", "value": "0;SV"}],
    [{"id": "set_datum_shift", "value": "0\nTW[19]=1"}],
    [{"id": "reset_multiturn", "socket": "1"}],
])
def test_encoder_maintenance_rejects_raw_sv_and_separators_before_io(operations):
    link = FakeLink()
    with pytest.raises(ValueError):
        DriveWorker._perform_encoder_maintenance(link, operations)
    assert link.commands == []


def test_encoder_maintenance_is_fail_fast_and_skips_later_operations():
    link = FakeLink(fail_command="TW[19]=1")
    operations = [
        {"id": "set_datum_shift", "value": 0},
        {"id": "reset_multiturn", "socket": 1},
        {"id": "reset_errors", "socket": 1},
    ]
    with pytest.raises(SessionCoordinateError, match="UNKNOWN"):
        DriveWorker._perform_encoder_maintenance(link, operations)
    assert link.commands == ["TW[18]=0", "TW[19]=1"]


def test_encoder_permanent_zero_verifies_final_px_without_sv():
    link = FakeLink(pos=912345)
    operations = [
        {"id": "set_datum_shift", "value": 0},
        {"id": "reset_multiturn", "socket": 1},
    ]
    message, telemetry = DriveWorker._perform_encoder_maintenance(link, operations)
    assert link.commands == ["TW[18]=0", "TW[19]=1"]
    assert telemetry["pos"] == 0
    assert "Final PX" in message
    assert "SV  →  미실행" in message


def test_encoder_maintenance_postcondition_mismatch_is_coordinate_unknown():
    link = FakeLink(pos=912345)
    operations = [
        {"id": "set_datum_shift", "value": 123},
        {"id": "reset_multiturn", "socket": 1},
    ]

    with pytest.raises(SessionCoordinateError) as caught:
        DriveWorker._perform_encoder_maintenance(link, operations)

    assert caught.value.coordinate_unknown
    assert caught.value.telemetry is not None
    assert caught.value.telemetry["pos"] == 0
    assert link.commands == ["TW[18]=123", "TW[19]=1"]


def test_encoder_maintenance_postcondition_mismatch_latches_worker_reconnect(
        monkeypatch):
    operations = [
        {"id": "set_datum_shift", "value": 123},
        {"id": "reset_multiturn", "socket": 1},
    ]
    worker = DriveWorker("COM_TEST")

    class MismatchLink(_HandshakeLink):
        def __init__(self):
            super().__init__()
            self.telemetry = {
                "pos": 912345, "vel": 0.0, "pos_err": 0.0,
                "iq": 0.0, "mo": 0,
            }
            self.telemetry_reads = 0

        def command(self, command, **kwargs):
            if command in self.values:
                return super().command(command, **kwargs)
            self.commands.append(command)
            if command == "TW[19]=1":
                # Deliberately violate the combined datum + multi-turn
                # transaction's required final PX=123 postcondition.
                self.telemetry["pos"] = 0
            return ""

        def read_telemetry(self):
            self.telemetry_reads += 1
            sample = _with_sample_timing(dict(self.telemetry))
            if self.telemetry_reads == 4:
                # initial admission, pre-mutation gate, transaction pre-state,
                # transaction post-state. End the worker after the mismatch.
                worker.stop()
            return sample

    link = MismatchLink()
    results = []
    terminal = []
    worker.encoder_maint_result.connect(
        lambda ok, message: results.append((ok, message)))
    worker.stopped.connect(lambda: terminal.append(True))
    worker.encoder_maintenance(operations)
    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)

    worker.run()

    assert results and results[-1][0] is False
    assert worker._encoder_maintenance_reconnect_required
    assert not worker._session_coordinate_known
    assert terminal == [True]
    assert link.disconnected


def test_soft_zero_write_then_readback_loss_reports_unknown_without_blind_restore():
    class ReadbackLoss(FakeLink):
        def __init__(self):
            super().__init__(pos=9876)
            self.read_count = 0

        def read_telemetry(self):
            self.read_count += 1
            if self.read_count >= 2:
                raise RuntimeError("telemetry lost after write")
            return dict(self.telemetry)

    link = ReadbackLoss()
    with pytest.raises(SessionCoordinateError, match="UNKNOWN") as caught:
        DriveWorker._perform_soft_zero(link)
    assert caught.value.coordinate_unknown
    assert link.commands == ["PX=0"]


def test_soft_zero_mismatch_restores_captured_px_and_verifies():
    class MismatchThenRestore(FakeLink):
        def command(self, command):
            self.commands.append(command)
            if command == "PX=0":
                self.telemetry["pos"] = 7
            elif command.startswith("PX="):
                self.telemetry["pos"] = int(command.split("=", 1)[1])
            return ""

    link = MismatchThenRestore(pos=123)
    with pytest.raises(RuntimeError, match="복원·되읽기 완료"):
        DriveWorker._perform_soft_zero(link)
    assert link.commands == ["PX=0", "PX=123"]
    assert link.telemetry["pos"] == 123


def test_new_worker_requires_verified_full_telemetry_and_encoder_unknown_requires_reconnect():
    worker = DriveWorker("COM_TEST")
    assert not worker._session_coordinate_known

    invalid = worker._record_fresh_telemetry(
        _full_disabled_telemetry(pos=None))
    assert not worker._session_coordinate_known
    assert invalid["session_coordinate_known"] is False

    worker._connection_identity_verified = True
    fresh = worker._record_fresh_telemetry(_full_disabled_telemetry(pos=42))
    assert worker._session_coordinate_known
    assert fresh["session_coordinate_known"] is True

    worker._latch_coordinate_unknown(reconnect_required=True)
    fresh = worker._record_fresh_telemetry(_full_disabled_telemetry(pos=43))
    assert not worker._session_coordinate_known
    assert worker._encoder_maintenance_reconnect_required
    assert fresh["session_coordinate_known"] is False
    assert fresh["encoder_maintenance_reconnect_required"] is True
    allowed, message = worker._trial_job_guard("soft_zero", None)
    assert not allowed
    assert "reconnect" in message.lower()

    reconnected = DriveWorker("COM_TEST")
    reconnected._connection_identity_verified = True
    reconnected._record_fresh_telemetry(_full_disabled_telemetry(pos=43))
    assert reconnected._session_coordinate_known
    assert not reconnected._encoder_maintenance_reconnect_required

    transient_unknown = DriveWorker("COM_TEST")
    transient_unknown._connection_identity_verified = True
    transient_unknown._latch_coordinate_unknown()
    transient_unknown._record_fresh_telemetry(_full_disabled_telemetry(pos=44))
    assert transient_unknown._session_coordinate_known


@pytest.mark.parametrize("sample", [
    _full_disabled_telemetry(mo=None),
    {"pos": 42, "vel": 0.0, "pos_err": 0.0, "mo": 0},
    _full_disabled_telemetry(vel=float("inf")),
    _full_disabled_telemetry(iq=float("nan")),
    _full_disabled_telemetry(mo=float("nan")),
], ids=["mo-none", "partial", "infinite-velocity", "nan-current", "nan-mo"])
def test_invalid_or_partial_telemetry_closes_session_coordinate_gate(sample):
    worker = DriveWorker("COM_TEST")
    worker._connection_identity_verified = True
    worker._record_fresh_telemetry(_full_disabled_telemetry())
    assert worker._session_coordinate_known

    observed = worker._record_fresh_telemetry(sample)

    assert worker._session_coordinate_known is False
    assert observed["session_coordinate_known"] is False


def test_full_finite_mo_zero_telemetry_is_valid_for_session_coordinate_gate():
    worker = DriveWorker("COM_TEST")
    worker._connection_identity_verified = True
    observed = worker._record_fresh_telemetry(_full_disabled_telemetry())

    assert worker._session_coordinate_known is True
    assert observed["session_coordinate_known"] is True


@pytest.mark.parametrize(
    "timing_case",
    ("past-source", "future-source", "duration-mismatch"),
    ids=("past-source", "future-source", "duration-mismatch"),
)
def test_raw_telemetry_rejects_untrusted_source_timing(timing_case):
    worker = DriveWorker("COM_TEST")
    worker._connection_identity_verified = True
    # Derive source times at execution, not pytest collection.  A preceding
    # suite taking >10 s must not turn the future-source negative control into
    # a valid present-time sample.
    now = time.monotonic()
    if timing_case == "past-source":
        timing_overrides = {
            "_sample_started_monotonic": now - 10.01,
            "_sample_finished_monotonic": now - 10.0,
            "_sample_duration_s": 0.01,
        }
    elif timing_case == "future-source":
        timing_overrides = {
            "_sample_started_monotonic": now + 9.99,
            "_sample_finished_monotonic": now + 10.0,
            "_sample_duration_s": 0.01,
        }
    else:
        timing_overrides = {
            "_sample_started_monotonic": now - 0.20,
            "_sample_finished_monotonic": now,
            "_sample_duration_s": 0.01,
        }
    sample = _full_disabled_telemetry(**timing_overrides)

    observed = worker._record_fresh_telemetry(sample)

    assert observed["telemetry_valid"] is False
    assert observed["session_coordinate_known"] is False
    assert "sample-timing" in observed["telemetry_error"]
    assert "telemetry_sequence" not in observed


@pytest.mark.parametrize("kind,persist", [
    ("autotune_apply", True),
    ("velpos_apply", False),
])
def test_legacy_gain_apply_worker_jobs_are_rejected_even_after_fresh_px(kind, persist):
    worker = DriveWorker("COM_TEST")
    worker._session_coordinate_known = True
    result = object()
    if kind == "autotune_apply":
        worker.apply_autotune_gains(result, persist)
    else:
        worker.apply_velpos_gains(result, persist)
    queued_kind, payload = worker._jobs.popleft()
    assert queued_kind == kind
    allowed, message = worker._trial_job_guard(queued_kind, payload)
    assert not allowed
    assert "begin" in message.lower()


def test_soft_zero_restore_reply_loss_is_resolved_by_independent_readback():
    class AcceptedRestoreWithLostReply(FakeLink):
        def command(self, command):
            self.commands.append(command)
            if command == "PX=0":
                self.telemetry["pos"] = 7
                return ""
            if command == "PX=123":
                self.telemetry["pos"] = 123
                raise TimeoutError("reply lost after accepted restore")
            raise AssertionError(command)

    link = AcceptedRestoreWithLostReply(pos=123)
    with pytest.raises(RuntimeError, match="복원·되읽기 완료") as caught:
        DriveWorker._perform_soft_zero(link)
    assert not isinstance(caught.value, SessionCoordinateError)
    assert link.commands == ["PX=0", "PX=123"]
    assert link.telemetry["pos"] == 123


def test_soft_zero_restore_reply_loss_stays_unknown_when_readback_mismatches():
    class LostReplyAndWrongRestore(FakeLink):
        def command(self, command):
            self.commands.append(command)
            if command == "PX=0":
                self.telemetry["pos"] = 7
                return ""
            if command == "PX=123":
                self.telemetry["pos"] = 99
                raise TimeoutError("reply lost and restore did not match")
            raise AssertionError(command)

    link = LostReplyAndWrongRestore(pos=123)
    with pytest.raises(SessionCoordinateError, match="UNKNOWN") as caught:
        DriveWorker._perform_soft_zero(link)
    assert caught.value.coordinate_unknown
    assert link.telemetry["pos"] == 99


class _TextSink:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


class _ButtonSink:
    def __init__(self):
        self.enabled = None

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


class _RunningWorker:
    @staticmethod
    def isRunning():
        return True


class _PropertyTextSink(_TextSink):
    def __init__(self):
        super().__init__()
        self.properties = {}

    def setProperty(self, name, value):
        self.properties[name] = value

    def setToolTip(self, text):
        self.properties["tooltip"] = text


def _authoritative_ui_telemetry(**overrides):
    sample = _full_disabled_telemetry()
    sample.update({
        "telemetry_sequence": 1,
        "telemetry_received_monotonic": time.monotonic(),
        "telemetry_valid": True,
        "telemetry_error": None,
        "session_coordinate_known": True,
        "encoder_maintenance_reconnect_required": False,
    })
    sample.update(overrides)
    return sample


def _telemetry_ui_stub():
    ui = SimpleNamespace(
        sender=lambda: None,
        worker=_RunningWorker(),
        m_pos=_TextSink(), m_perr=_TextSink(), m_vel=_TextSink(), m_iq=_TextSink(),
        m_pos_sub=_TextSink(), m_vel_sub=_TextSink(),
        lbl_motor=_PropertyTextSink(),
        _fmt=lambda value, *_args: "--" if value is None else str(value),
        _ca18=65536,
        _restyle=lambda _widget: None,
        _ui_connected=False,
        _connection_admitted=True,
        _telemetry_authoritative=False,
        _energizing_state=False,
        _last_telemetry_sequence=0,
        _last_telemetry_received_monotonic=None,
        _last_telemetry_sample_finished_monotonic=None,
        _set_connected_ui=lambda _on: None,
        session_log=SimpleNamespace(
            record_telemetry=lambda *_args, **_kwargs: None),
        _session_log_event_changed=lambda event: event,
    )
    ui._telemetry_envelope_valid = lambda sample: (
        app_main.MainWindow._telemetry_envelope_valid(ui, sample))
    ui._revoke_telemetry_authority = lambda detail, energizing=False: (
        app_main.MainWindow._revoke_telemetry_authority(
            ui, detail, energizing=energizing))
    return ui


@pytest.mark.parametrize("sample", [
    _full_disabled_telemetry(mo=None),
    {"pos": 42, "mo": 0},
    _full_disabled_telemetry(mo=float("nan")),
], ids=["mo-none", "partial", "nan-mo"])
def test_invalid_or_partial_mo_never_renders_as_motor_disabled(sample):
    ui = _telemetry_ui_stub()

    app_main.MainWindow._on_telemetry(ui, sample)

    assert ui.lbl_motor.text != "MOTOR DISABLED"
    assert "UNKNOWN" in ui.lbl_motor.text


def test_full_finite_mo_zero_renders_as_motor_disabled():
    ui = _telemetry_ui_stub()

    app_main.MainWindow._on_telemetry(ui, _authoritative_ui_telemetry())

    assert ui.lbl_motor.text == "MOTOR DISABLED"
    assert ui._last_mo == 0


def test_terminal_restored_failure_payload_does_not_resurrect_p1_or_p2_trial():
    restored = SimpleNamespace(persistence_state="RESTORED")

    p1 = SimpleNamespace(
        worker=_RunningWorker(), _p1_gain_trial=None, tune_status=_TextSink(),
        _set_connected_ui=lambda _on: None, _flash=lambda _msg: None,
    )
    app_main.MainWindow._on_current_gain_action(
        p1, "restore", False, "late duplicate failure", restored)
    assert p1._p1_gain_trial is None
    unknown = SimpleNamespace(persistence_state="UNKNOWN")
    app_main.MainWindow._on_current_gain_action(
        p1, "commit", False, "ambiguous SV", unknown)
    assert p1._p1_gain_trial is unknown

    buttons = {name: _ButtonSink() for name in (
        "btn_tune", "btn_tune_signature", "btn_tune_vp", "btn_tune_apply",
        "btn_tune_vp_apply", "btn_tune_verify", "btn_tune_vp_restore",
        "btn_tune_vp_save")}
    p2 = SimpleNamespace(
        worker=_RunningWorker(), _p1_gain_trial=None, _vp_gain_trial=None,
        _vp_trial_verified_green=False, _vp_verified_trial=None,
        _vp_result=None, _at_result=None, tune_status=_TextSink(),
        _flash=lambda _msg: None, **buttons,
    )
    app_main.MainWindow._on_velpos_gain_action(
        p2, "restore", False, "late duplicate failure", restored)
    assert p2._vp_gain_trial is None


def test_unknown_persistence_close_requires_explicit_critical_confirmation(monkeypatch):
    calls = []

    def cancel_warning(*args, **kwargs):
        calls.append((args, kwargs))
        return app_main.QtWidgets.QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(app_main.QtWidgets.QMessageBox, "warning", cancel_warning)
    fake = SimpleNamespace(tune_status=_TextSink())
    assert not app_main.MainWindow._confirm_unknown_persistence_exit(fake, ("P1",))
    assert calls
    assert "UNKNOWN" in fake.tune_status.text
    assert "reset" in fake.tune_status.text.lower()

    monkeypatch.setattr(
        app_main.QtWidgets.QMessageBox, "warning",
        lambda *args, **kwargs:
        app_main.QtWidgets.QMessageBox.StandardButton.Yes)
    assert app_main.MainWindow._confirm_unknown_persistence_exit(fake, ("P2",))

    event = SimpleNamespace(ignored=False)
    event.ignore = lambda: setattr(event, "ignored", True)
    fake = SimpleNamespace(
        _p1_gain_trial=SimpleNamespace(persistence_state="UNKNOWN"),
        _vp_gain_trial=None,
        _confirm_unknown_persistence_exit=lambda _phases: False,
        _vp_trial_verified_green=True,
        _vp_verified_trial=object(),
        _flash=lambda _msg: None,
        tune_status=_TextSink(),
        worker=None,
    )
    app_main.MainWindow.closeEvent(fake, event)
    assert event.ignored
