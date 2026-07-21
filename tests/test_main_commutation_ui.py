# -*- coding: utf-8 -*-
"""P4 Commutation-ID GUI wiring — offline UI + mock-worker acceptance.

계약(세그먼트 2026-07-21):
  * 버튼 활성 조건 = 서명 버튼과 동일 (연결 + SUPERVISED + MO=0 +
    mutation_trusted; 트라이얼/디스패치 중이면 잠김).
  * 통전 결정은 버튼 클릭 + 확인 다이얼로그에서만 — No면 워커 호출 0회.
    다이얼로그는 1.30 A 천장·UM3 사다리 단계별(8.49 A 자동 경로 없음)·
    Abort·E-stop 확인을 명시한다.
  * 목-워커로 run_commutation_id가 실제로 트리거되고(진짜 커널 실행)
    결과(path_used/delta/ca7 before→after/status/reason)가 표시된다.
  * Abort(operator cancel)는 RED + CA[7] 원복 + MO=0으로 끝난다.
  * 워커 가드: observe-only/RAM-trial 중 commutation_id 거부, 통전 전
    (S0 스냅숏의 MO=1/폴트 게이트)은 커널이 정직 RED로 거부한다.

이 모듈은 실제 COM 포트를 절대 열지 않는다 (하드웨어 무접촉).
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autotune_velpos
import commutation_id
import main as app_main
from commutation_id import CommutationIDResult
from test_commutation_id import CommutGearLashSim, IBA_REF


# ======================================================================================
# harness
# ======================================================================================
@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


@pytest.fixture
def win(qapp):
    w = app_main.MainWindow()
    yield w
    w.worker = None
    w.close()
    qapp.processEvents()


def _admit(win, qapp):
    """SUPERVISED + MO=0 offline admission (production envelope, no COM)."""
    assert app_main._smoke_admit_ui(win)
    qapp.processEvents()


def _refresh(win, seq, mo=0):
    return app_main._smoke_refresh_ui(win, seq, mo=mo)


class _GlueWorker(app_main.DriveWorker):
    """Real DriveWorker with msleep mapped onto the sim clock (headless).

    Mirrors the shim used by --smoke-velpos/--smoke-commutation: adds
    read_telemetry, maps MS/ID, and lets the worker-owned safety closeout
    (ST) through the sim's motion guard.
    """

    def __init__(self, drive):
        super().__init__("SIM")
        self._drive = drive
        self._connection_identity_verified = True
        if not hasattr(drive, "read_telemetry"):
            import time as _time

            def read_sim_telemetry():
                now = _time.monotonic()
                return {
                    "pos": float(drive.p),
                    "vel": float(drive.v),
                    "pos_err": float(drive.regs.get("PA", drive.p) - drive.p),
                    "iq": float(drive.i_act),
                    "mo": int(drive.regs.get("MO", 0)),
                    "_sample_started_monotonic": now,
                    "_sample_finished_monotonic": now,
                    "_sample_duration_s": 0.0,
                }

            drive.read_telemetry = read_sim_telemetry
        original_command = drive.command

        def glue_command(command, *args, **kwargs):
            name = str(command).strip().rstrip(";").strip().upper()
            if name == "ST" and not kwargs.get("allow_motion", False):
                kwargs["allow_motion"] = True
            if name == "MS":
                return "3" if int(drive.regs.get("MO", 0)) == 0 else "2"
            if name == "ID":
                return "0"
            return original_command(command, *args, **kwargs)

        drive.command = glue_command

    def msleep(self, ms):
        self._drive.advance(ms / 1000.0)


def _cmds(drive):
    return [c.replace(" ", "").upper() for c, _a in drive.log]


# ======================================================================================
# 1) 버튼 활성 조건 = 서명 버튼과 동일
# ======================================================================================
def test_button_disabled_offline_and_mirrors_signature_gate(win, qapp):
    # OFFLINE: both run buttons stay locked
    assert not win.btn_tune_commutation.isEnabled()
    assert not win.btn_tune_signature.isEnabled()
    # SUPERVISED + MO=0 admission enables both together
    _admit(win, qapp)
    assert win.btn_tune_signature.isEnabled()
    assert win.btn_tune_commutation.isEnabled()
    # MO=1 telemetry revokes mutation trust for both together
    _refresh(win, 2, mo=1)
    win._set_connected_ui(True)
    assert not win.btn_tune_signature.isEnabled()
    assert not win.btn_tune_commutation.isEnabled()
    # back to MO=0 re-enables both
    _refresh(win, 3, mo=0)
    win._set_connected_ui(True)
    assert win.btn_tune_signature.isEnabled()
    assert win.btn_tune_commutation.isEnabled()


def test_button_locked_during_dispatch_and_ram_trial(win, qapp):
    _admit(win, qapp)
    assert win.btn_tune_commutation.isEnabled()
    # any in-flight tuning dispatch locks the button (claim/release cycle)
    assert win._claim_tune_dispatch("p1")
    assert not win.btn_tune_commutation.isEnabled()
    win._release_tune_dispatch("p1")
    win._set_connected_ui(True)
    assert win.btn_tune_commutation.isEnabled()
    # an active RAM gain trial locks the button (same as the signature gate)
    win._p1_gain_trial = object()
    win._set_connected_ui(True)
    assert not win.btn_tune_commutation.isEnabled()
    assert not win.btn_tune_signature.isEnabled()
    win._p1_gain_trial = None


# ======================================================================================
# 2) 확인 다이얼로그 — 통전 결정은 여기서만
# ======================================================================================
def test_confirm_dialog_no_blocks_worker_dispatch(win, qapp, monkeypatch):
    _admit(win, qapp)
    calls = []
    win.worker.start_commutation_id = lambda kw: calls.append(kw)
    captured = {}

    def warn_no(parent, title, text, *a, **k):
        captured["title"] = str(title)
        captured["text"] = str(text)
        return QtWidgets.QMessageBox.StandardButton.No

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", warn_no)
    win._run_commutation_clicked()
    assert calls == []                      # 워커 호출 0회 — 통전 없음
    assert win._tune_dispatch_inflight is None
    # 안전 문구 계약: 1.30 A 천장 · 사다리 단계별 · 8.49 A 자동 경로 없음 ·
    # CA[7] 원복 · SV 없음 · Abort · E-stop
    text = captured["text"]
    assert "1.30" in text
    assert "2.00 → 4.24 → 6.00" in text
    assert "8.49" in text and "자동 경로 없음" in text
    assert "CA[7]" in text and "원복" in text
    assert "SV" in text
    assert "Abort" in text
    assert "E-stop" in text


def test_confirm_dialog_yes_dispatches_exactly_once(win, qapp, monkeypatch):
    _admit(win, qapp)
    calls = []
    win.worker.start_commutation_id = lambda kw: calls.append(kw)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "warning",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes)
    win._run_commutation_clicked()
    assert len(calls) == 1
    assert win._tune_dispatch_inflight == "commutation"
    assert not win.btn_tune_commutation.isEnabled()
    assert not win.btn_tune.isEnabled()
    # a second click while in flight is refused without another dispatch
    win._run_commutation_clicked()
    assert len(calls) == 1


def test_click_refused_when_worker_not_running(win, qapp, monkeypatch):
    _admit(win, qapp)
    win.worker = None
    dialogs = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "warning",
        lambda *a, **k: dialogs.append(1)
        or QtWidgets.QMessageBox.StandardButton.Yes)
    win._run_commutation_clicked()
    assert dialogs == []                    # 다이얼로그 이전에 거부
    assert win._tune_dispatch_inflight is None


# ======================================================================================
# 3) 목-워커: run_commutation_id 실제 트리거 → 결과 표시
# ======================================================================================
def test_mock_worker_green_run_reaches_result_display(win, qapp):
    sim = CommutGearLashSim(delta0_deg=59.0, s_sim=+1)
    worker = _GlueWorker(sim)
    started, codes, results = [], [], []
    worker.commutation_started.connect(lambda: started.append(1))
    worker.commutation_progress.connect(lambda c, d: codes.append(c))
    worker.commutation_result.connect(results.append)
    worker._run_commutation_id(
        sim, {"i_ba_ref_a": IBA_REF, "clock_fn": (lambda: sim.t)})
    assert started == [1]
    for code in ("S0_SNAPSHOT", "S1_WATCH", "S3_MEASURE", "S4_CORRECT",
                 "S6_CLOSE"):
        assert code in codes
    res = results[0]
    assert res.status == commutation_id.GREEN
    assert res.path_used == "A"
    assert abs(res.delta_est_deg) <= 25.8
    assert res.ca7_sign_resolved == +1
    corr = [i for i in res.evidence["iterations"] if i.get("event") == "correct"]
    assert res.ca7_before == 438
    assert corr and res.ca7_after == corr[-1]["ca7"]   # GREEN keeps correction
    # safety envelope: worker glue must not have widened the kernel caps
    assert sim.regs["MO"] == 0 and sim.regs["MF"] == 0 and sim.regs["UM"] == 5
    assert sim.tc_um5_max <= autotune_velpos.SIGNATURE_ENERGIZE_ABS_MAX_A + 1e-9
    assert not any(c == "SV" or c.startswith("SV=") for c in _cmds(sim))

    # feed the real result into the GUI handlers (deterministic direct call)
    _admit(win, qapp)
    win._dump_commutation_result = lambda r: None   # keep LIVE state clean
    win._on_commutation_started()
    assert win.btn_tune_abort.isEnabled()
    win._on_commutation_progress("S3_MEASURE", "서명 램프(≤1.30A)")
    assert "S3_MEASURE" in win.tune_status.text()
    _refresh(win, 2, mo=0)
    win._on_commutation_result(res)
    text = win.tune_status.text()
    assert "GREEN" in text
    assert res.path_used in text
    assert "%s→%s" % (res.ca7_before, res.ca7_after) in text
    assert not win.btn_tune_abort.isEnabled()
    assert win._tune_dispatch_inflight is None


def test_mock_worker_operator_abort_red_ca7_reverted(win, qapp):
    sim = CommutGearLashSim(delta0_deg=59.0, s_sim=+1)
    worker = _GlueWorker(sim)
    results = []
    worker.commutation_result.connect(results.append)
    worker._cancel_at = True                # operator Abort flag (shared chain)
    worker._run_commutation_id(
        sim, {"i_ba_ref_a": IBA_REF, "clock_fn": (lambda: sim.t)})
    res = results[0]
    assert res.status == commutation_id.RED
    assert sim.regs["MO"] == 0
    assert sim.regs["CA[7]"] == 438         # CA[7] untouched/reverted
    # RED must surface honestly in the GUI and never look converged
    _admit(win, qapp)
    win._dump_commutation_result = lambda r: None
    win._on_commutation_result(res)
    assert "RED" in win.tune_status.text()


def test_mock_worker_red_result_display_reason(win, qapp):
    _admit(win, qapp)
    win._dump_commutation_result = lambda r: None
    red = CommutationIDResult(
        status=commutation_id.RED,
        reason="비-커뮤 원인: 180° 플립 양측에서 MF=0x80",
        path_used="A+flip", ca7_before=438, ca7_after=438)
    win._on_commutation_result(red)
    text = win.tune_status.text()
    assert "RED" in text and "비-커뮤" in text and "438→438" in text


# ======================================================================================
# 4) 통전 전 게이트 — 워커 가드 + 커널 preflight (GUI가 우회하지 않음)
# ======================================================================================
def test_worker_guard_rejects_commutation_in_observe_only():
    worker = app_main.DriveWorker("SIM", query_only=True)
    allowed, msg = worker._trial_job_guard("commutation_id", {})
    assert not allowed
    assert "observe-only" in msg


def test_worker_guard_rejects_commutation_during_ram_trial():
    worker = app_main.DriveWorker("SIM")
    worker._session_coordinate_known = True
    worker._vp_gain_trial = object()
    allowed, msg = worker._trial_job_guard("commutation_id", {})
    assert not allowed
    assert "P2" in msg
    worker._vp_gain_trial = None
    worker._p1_gain_trial = object()
    allowed, msg = worker._trial_job_guard("commutation_id", {})
    assert not allowed
    assert "P1" in msg


def test_worker_guard_allows_commutation_when_clear():
    worker = app_main.DriveWorker("SIM")
    worker._session_coordinate_known = True
    allowed, msg = worker._trial_job_guard("commutation_id", {})
    assert allowed and msg == ""


def test_guard_rejection_emits_red_commutation_result():
    worker = app_main.DriveWorker("SIM", query_only=True)
    results = []
    worker.commutation_result.connect(results.append)
    worker._emit_guard_rejection("commutation_id", {}, "observe-only refusal")
    assert len(results) == 1
    assert results[0].status == commutation_id.RED
    assert "observe-only refusal" in results[0].reason


def test_kernel_refuses_energize_when_motor_already_on():
    """S0 preflight: MO=1 -> honest RED, zero enable, zero writes."""
    sim = CommutGearLashSim(delta0_deg=0.0)
    sim.regs["MO"] = 1
    worker = _GlueWorker(sim)
    results = []
    worker.commutation_result.connect(results.append)
    worker._run_commutation_id(
        sim, {"i_ba_ref_a": IBA_REF, "clock_fn": (lambda: sim.t)})
    res = results[0]
    assert res.status == commutation_id.RED
    assert "MO=1" in res.reason
    assert sim.enable_count == 0
    assert sim.tc_um5_max == 0.0 and sim.tc_um3_max == 0.0


def test_kernel_refuses_cap_above_absolute_ceiling():
    sim = CommutGearLashSim()
    worker = _GlueWorker(sim)
    results = []
    worker.commutation_result.connect(results.append)
    # tracks the constant, not a frozen number (ceiling moved 2026-07-22)
    worker._run_commutation_id(
        sim, {"i_ba_ref_a": IBA_REF,
              "signature_cap_a":
                  autotune_velpos.SIGNATURE_ENERGIZE_ABS_MAX_A + 0.01})
    res = results[0]
    assert res.status == commutation_id.RED
    assert sim.enable_count == 0


# ======================================================================================
# 5) 큐/취소 배선 — start_commutation_id 계약
# ======================================================================================
def test_start_commutation_id_queues_generation_bound_job():
    worker = app_main.DriveWorker("SIM")
    token = worker.start_commutation_id({"x": 1})
    assert worker._jobs
    kind, payload = worker._jobs[-1]
    assert kind == "commutation_id"
    assert payload == (token, {"x": 1})
    assert not worker._tune_cancel_requested(token)
    worker.cancel_commutation_id()
    assert worker._tune_cancel_requested(token)


def test_stale_signal_from_foreign_sender_ignored(win, qapp):
    """Qt-delivered commutation signals from a non-current worker are dropped."""
    _admit(win, qapp)
    from PyQt6 import QtCore

    class _Foreign(QtCore.QObject):
        commutation_result = QtCore.pyqtSignal(object)

    foreign = _Foreign()
    foreign.commutation_result.connect(win._on_commutation_result)
    before = win.tune_status.text()
    foreign.commutation_result.emit(CommutationIDResult(
        status=commutation_id.GREEN, path_used="A"))
    qapp.processEvents()
    assert win.tune_status.text() == before
