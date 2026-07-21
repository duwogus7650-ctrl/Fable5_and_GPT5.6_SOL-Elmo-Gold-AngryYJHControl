# -*- coding: utf-8 -*-
"""One-button Quick Tuning glue: dispatch mapping, chaining, and the stops.

quick_tune_chain owns the order/policy and is proven in its own file.  What is
proven HERE is the wiring: that each step dispatches the RIGHT worker call with
the right arguments, that a finished step advances the chain, and — the part
that matters most — that RED, Abort, DRIVE STOP and a dropped connection all
stop it before the next energize.

Nothing here touches hardware; the worker is a recorder.
"""
import dataclasses
import os
import sys
import types

import pytest
from PyQt6 import QtWidgets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as app_main
import quick_tune_chain as qtc


@dataclasses.dataclass
class _FakeDataclassResult:
    """_result_payload() runs dataclasses.asdict, so the stub must be one."""
    status: str = "GREEN"
    reason: str = ""


class _ChainWorker:
    """Records what the chain dispatches instead of driving a motor."""

    def __init__(self):
        self.calls = []

    def isRunning(self):
        return True

    def start_commutation_id(self, kw):
        self.calls.append(("commutation", dict(kw)))

    def start_autotune(self, kw):
        self.calls.append(("phase1", dict(kw)))

    def start_velpos_autotune(self, kw):
        step = "signature" if kw.get("signature_only") else "phase2"
        self.calls.append((step, dict(kw)))

    def begin_velpos_gain_trial(self, r):
        self.calls.append(("apply", r))

    # unused by the chain but touched by shared UI paths
    def cancel_autotune(self):
        self.calls.append(("cancel", None))

    def request_motion_stop(self):
        self.calls.append(("motion_stop", None))


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def win(qapp, monkeypatch):
    monkeypatch.setattr(app_main, "list_serial_ports", lambda: ["COM_TEST"])
    w = app_main.MainWindow()
    yield w
    w.worker = None
    w.close()


def _arm(win, worker):
    """Put the window in the state a live, signature-authorised session has."""
    win.worker = worker
    win._ui_connected = True
    win._connection_admitted = True
    gen = getattr(win, "_tuning_authority_generation", 0)
    # motion authority (what a GREEN/provisional signature grants)
    win._motion_signature_green = True
    win._motion_signature_token = "tok"
    win._motion_signature_generation = gen
    # Phase-1 R/L model (what Phase 2 needs)
    win._at_result = types.SimpleNamespace(
        status="GREEN", r_pp_ohm=0.1385, l_pp_h=43.4e-6)
    win._at_result_generation = gen
    # Phase-2 candidate (what Apply needs)
    win._vp_result = types.SimpleNamespace(
        status="GREEN", kp_vel=2.5e-4, ki_vel_hz=10.7, kp_pos=85.2)
    win._vp_result_generation = gen
    win._vp_gain_trial = None
    return gen


def _step_names(worker):
    return [c[0] for c in worker.calls]


def _advance(win, step, status):
    """Mimic the real result handler.

    Order matters and mirrors main.py: the handler releases the dispatch token
    and STORES its result (``_at_result`` / ``_vp_result`` / motion authority)
    BEFORE the chain hook at its tail runs — the next step's preconditions are
    exactly those stored values.  A harness that skipped the store would make
    every chained dispatch look refused.
    """
    win._release_tune_dispatch(
        {"commutation": "commutation", "phase1": "p1", "signature": "signature",
         "phase2": "p2", "apply": "p2_begin"}[step])
    gen = getattr(win, "_tuning_authority_generation", 0)
    usable = status in ("GREEN", "YELLOW")
    if step == "phase1" and usable:
        win._at_result = types.SimpleNamespace(
            status=status, r_pp_ohm=0.1385, l_pp_h=43.4e-6)
        win._at_result_generation = gen
    elif step == "signature" and usable:
        win._motion_signature_green = True
        win._motion_signature_token = "tok"
        win._motion_signature_generation = gen
    elif step == "phase2" and usable:
        win._vp_result = types.SimpleNamespace(
            status=status, kp_vel=2.5e-4, ki_vel_hz=10.7, kp_pos=85.2)
        win._vp_result_generation = gen
    win._quick_chain_on_result(step, status)


# ------------------------------------------------------------------ dispatch
@pytest.mark.parametrize("step,expect", [
    (qtc.COMMUTATION, "commutation"),
    (qtc.PHASE1, "phase1"),
    (qtc.SIGNATURE, "signature"),
    (qtc.PHASE2, "phase2"),
    (qtc.APPLY, "apply"),
])
def test_each_step_dispatches_its_own_worker_call(win, step, expect):
    worker = _ChainWorker()
    _arm(win, worker)
    assert win._quick_chain_dispatch(step) is True
    assert _step_names(worker) == [expect]


def test_signature_dispatch_is_flagged_signature_only(win):
    worker = _ChainWorker()
    _arm(win, worker)
    win._quick_chain_dispatch(qtc.SIGNATURE)
    assert worker.calls[0][1].get("signature_only") is True


def test_phase2_dispatch_carries_the_measured_rl_model(win):
    worker = _ChainWorker()
    _arm(win, worker)
    win._quick_chain_dispatch(qtc.PHASE2)
    kw = worker.calls[0][1]
    assert kw["r_pp_ohm"] == pytest.approx(0.1385)
    assert kw["l_pp_h"] == pytest.approx(43.4e-6)
    assert not kw.get("signature_only")


# --------------------------------------------------- refusals (never hang)
def test_phase2_is_refused_without_motion_authority(win):
    """The load-bearing ordering guard: no signature authority -> no rotation."""
    worker = _ChainWorker()
    _arm(win, worker)
    win._motion_signature_green = False
    assert win._quick_chain_dispatch(qtc.PHASE2) is False
    assert worker.calls == []


def test_phase2_is_refused_without_a_phase1_model(win):
    worker = _ChainWorker()
    _arm(win, worker)
    win._at_result = None
    assert win._quick_chain_dispatch(qtc.PHASE2) is False
    assert worker.calls == []


def test_apply_is_refused_without_a_usable_phase2_result(win):
    worker = _ChainWorker()
    _arm(win, worker)
    win._vp_result = None
    assert win._quick_chain_dispatch(qtc.APPLY) is False
    assert worker.calls == []


def test_apply_is_refused_when_a_trial_is_already_applied(win):
    worker = _ChainWorker()
    _arm(win, worker)
    win._vp_gain_trial = object()
    assert win._quick_chain_dispatch(qtc.APPLY) is False
    assert worker.calls == []


def test_dispatch_is_refused_without_a_running_worker(win):
    _arm(win, _ChainWorker())
    win.worker = None
    assert win._quick_chain_dispatch(qtc.COMMUTATION) is False


# ------------------------------------------------------------------ chaining
def test_all_green_chain_dispatches_all_five_in_order(win):
    worker = _ChainWorker()
    _arm(win, worker)
    win._quick_chain = qtc.QuickTuneChain()
    win._quick_chain_apply_action(win._quick_chain.start())
    for step in ("commutation", "phase1", "signature", "phase2", "apply"):
        assert _step_names(worker)[-1] == step, _step_names(worker)
        _advance(win, step, "GREEN")
    assert _step_names(worker) == [
        "commutation", "phase1", "signature", "phase2", "apply"]
    assert win._quick_chain is None                 # finished and cleared
    assert "완료" in win.tune_status.text()


def test_signature_runs_after_phase1_not_before(win):
    """Field lesson: Phase 1 clears the signature, so the chain must re-take it
    AFTER Phase 1.  Locked here at the wiring level too."""
    worker = _ChainWorker()
    _arm(win, worker)
    win._quick_chain = qtc.QuickTuneChain()
    win._quick_chain_apply_action(win._quick_chain.start())
    _advance(win, "commutation", "GREEN")
    _advance(win, "phase1", "GREEN")
    assert _step_names(worker) == ["commutation", "phase1", "signature"]


def test_red_stops_the_chain_before_the_next_energize(win):
    worker = _ChainWorker()
    _arm(win, worker)
    win._quick_chain = qtc.QuickTuneChain()
    win._quick_chain_apply_action(win._quick_chain.start())
    _advance(win, "commutation", "RED")
    assert _step_names(worker) == ["commutation"]   # phase1 never dispatched
    assert win._quick_chain is None
    assert "⛔" in win.tune_status.text()


def test_phase2_yellow_never_auto_applies(win):
    """Gains from a flagged Phase 2 are shown, not installed."""
    worker = _ChainWorker()
    _arm(win, worker)
    win._quick_chain = qtc.QuickTuneChain()
    win._quick_chain_apply_action(win._quick_chain.start())
    for step in ("commutation", "phase1", "signature"):
        _advance(win, step, "GREEN")
    _advance(win, "phase2", "YELLOW")
    assert "apply" not in _step_names(worker)
    assert win._quick_chain is None
    assert "Apply" in win.tune_status.text()


# --------------------------------------------------------------- the stops
def test_abort_cancels_the_chain(win):
    worker = _ChainWorker()
    _arm(win, worker)
    win._quick_chain = qtc.QuickTuneChain()
    win._quick_chain_apply_action(win._quick_chain.start())
    win._abort_autotune_clicked()
    assert win._quick_chain is None
    # a late result from the aborted step must not restart the chain
    _advance(win, "commutation", "GREEN")
    assert _step_names(worker).count("phase1") == 0


def test_drive_stop_cancels_the_chain(win):
    worker = _ChainWorker()
    _arm(win, worker)
    win._quick_chain = qtc.QuickTuneChain()
    win._quick_chain_apply_action(win._quick_chain.start())
    win._motion_stop_clicked()
    assert win._quick_chain is None
    _advance(win, "commutation", "GREEN")
    assert "phase1" not in _step_names(worker)


def test_disconnect_cancels_the_chain(win):
    worker = _ChainWorker()
    _arm(win, worker)
    win._quick_chain = qtc.QuickTuneChain()
    win._quick_chain_apply_action(win._quick_chain.start())
    win._set_connected_ui(False)
    assert win._quick_chain is None


def test_result_for_another_step_does_not_advance(win):
    """A manual run interleaving with a chain must not push it forward."""
    worker = _ChainWorker()
    _arm(win, worker)
    win._quick_chain = qtc.QuickTuneChain()
    win._quick_chain_apply_action(win._quick_chain.start())   # at commutation
    win._release_tune_dispatch("commutation")
    win._quick_chain_on_result(qtc.PHASE2, "GREEN")           # not our step
    assert win._quick_chain is not None
    assert win._quick_chain.current_step == qtc.COMMUTATION
    assert _step_names(worker) == ["commutation"]


# ------------------------------------------------------------------- the UI
def test_quick_button_exists_and_is_gated_offline(win):
    assert hasattr(win, "btn_tune_quick")
    assert win.btn_tune_quick.isEnabled() is False


def test_quick_button_label_carries_no_stale_current(win):
    """The signature cap is per-motor now; a hardcoded number on the button
    would contradict the dialog (which asks the kernel)."""
    assert "1.30" not in win.btn_tune_signature.text()


def test_claiming_a_dispatch_disables_the_quick_button(win):
    _arm(win, _ChainWorker())
    win.btn_tune_quick.setEnabled(True)
    assert win._claim_tune_dispatch("commutation") is True
    assert win.btn_tune_quick.isEnabled() is False


def test_result_handlers_store_their_result_before_advancing_the_chain():
    """Guards the assumption the harness above encodes.

    Each step's precondition IS the previous step's stored result, so every
    result handler must assign it BEFORE the chain hook at its tail runs.  If
    the hook were moved above the assignment, the chained dispatch would be
    refused on live hardware while these tests still passed — so the ordering is
    asserted against the real source, not re-implemented here.
    """
    import inspect
    for func, store in (
            (app_main.MainWindow._on_autotune_result, "self._at_result = res"),
            (app_main.MainWindow._on_velpos_result, "self._vp_result = res")):
        src = inspect.getsource(func)
        assert store in src, store
        assert "_quick_chain_on_result" in src
        assert src.index(store) < src.rindex("_quick_chain_on_result"), (
            "%s must be stored before the chain hook in %s"
            % (store, func.__name__))


# --------------------------------------------- guided lamps fill cumulatively
def _lamp_marks(win):
    return [lbl.text().strip()[0] for lbl in win.tune_stage_lbls]


def test_phase1_completion_keeps_its_lamps_lit_through_later_steps(win):
    """The EAS wizard fills up; ours used to blank the Phase-1 lamps the moment
    a signature/Phase-2 run started (observed 2026-07-22)."""
    win._tune_stage_floor = win._AT_PHASE1_LAST          # Phase 1 completed
    win._set_tune_stage(3, done_upto=-1)                 # a Vel/Pos run starts
    marks = _lamp_marks(win)
    assert marks[:3] == ["●", "●", "●"], marks           # stay done
    assert marks[3] == "◆", marks                        # current step active
    assert marks[4:] == ["○", "○"], marks


def test_lamp_floor_never_claims_a_stage_from_a_previous_connection(win):
    win._tune_stage_floor = win._AT_PHASE2_LAST
    win._invalidate_tuning_result_authority()
    assert win._tune_stage_floor == -1
    win._set_tune_stage(-1, done_upto=-1)
    assert _lamp_marks(win) == ["○"] * len(win.tune_stage_lbls)


def test_a_fresh_phase1_run_clears_the_floor(win):
    win._tune_stage_floor = win._AT_PHASE1_LAST
    win._tune_dispatch_inflight = "p1"
    win._on_autotune_started()
    assert win._tune_stage_floor == -1
    assert _lamp_marks(win)[0] == "◆"


# ------------------------------------------------------- build provenance
def test_window_title_names_the_loaded_build(win):
    """btw-028: every screenshot carries the title bar, so the 'is this app
    running my fix?' question is answerable from a screenshot alone."""
    title = win.windowTitle()
    assert "build" in title
    assert (app_main.BUILD_REV or "unknown") in title


def test_result_payload_is_stamped_with_the_build():
    payload = app_main.MainWindow._result_payload(
        _FakeDataclassResult(status="GREEN"))
    assert payload["_build_rev"] == app_main.BUILD_REV
    assert payload["_build_loaded_at"] == app_main.BUILD_LOADED_AT
    assert payload["status"] == "GREEN"


def test_starting_a_chain_while_one_runs_is_refused(win, monkeypatch):
    worker = _ChainWorker()
    _arm(win, worker)
    win._quick_chain = qtc.QuickTuneChain()
    win._quick_chain_apply_action(win._quick_chain.start())
    before = list(worker.calls)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "warning",
        staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes))
    win._run_quick_tuning_clicked()
    assert worker.calls == before
