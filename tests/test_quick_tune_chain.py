# -*- coding: utf-8 -*-
"""Exhaustive offline tests for the Quick Tuning orchestration state machine.

The chain owns ORDER and POLICY; both are fully decidable without Qt or
hardware, so every branch is pinned here.  These tests are the reason the
one-button flow can be trusted before it ever touches a drive.
"""
import dataclasses
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quick_tune_chain as qtc
from quick_tune_chain import (
    QuickTuneChain, ChainAction, GREEN, YELLOW, RED,
    DISPATCH, FINISH, STOP,
    COMMUTATION, PHASE1, SIGNATURE, PHASE2, APPLY, FULL_ORDER)


# --------------------------------------------------------------------- helpers
def _drive(chain, statuses):
    """Feed a status per step; return the list of actions (start + each result)."""
    actions = [chain.start()]
    for step, status in zip(chain.steps, statuses):
        if actions[-1].kind != DISPATCH:
            break
        assert actions[-1].step == step
        actions.append(chain.on_result(step, status))
    return actions


# ------------------------------------------------------------------- the order
def test_order_puts_signature_after_phase1():
    """The field lesson: Phase 1 clears the signature, so signature must follow
    it.  If this order ever regresses, the whole chain is unsafe."""
    order = QuickTuneChain().steps
    assert order == FULL_ORDER
    assert order.index(SIGNATURE) > order.index(PHASE1)
    assert order.index(PHASE2) > order.index(SIGNATURE)
    assert order.index(APPLY) == len(order) - 1


def test_commutation_runs_first():
    assert QuickTuneChain().start().step == COMMUTATION


# --------------------------------------------------------------- happy path
def test_all_green_runs_every_step_then_finishes():
    chain = QuickTuneChain()
    actions = _drive(chain, [GREEN] * 5)
    dispatched = [a.step for a in actions if a.kind == DISPATCH]
    assert dispatched == list(FULL_ORDER)
    assert actions[-1].kind == FINISH
    assert actions[-1].ok is True
    assert chain.done is True


def test_dispatch_sequence_is_strictly_in_order():
    chain = QuickTuneChain()
    a = chain.start()
    seen = []
    for step in FULL_ORDER:
        assert a.kind == DISPATCH and a.step == step
        seen.append(a.step)
        a = chain.on_result(step, GREEN)
    assert seen == list(FULL_ORDER)
    assert a.kind == FINISH


# ------------------------------------------------------------- benign yellows
@pytest.mark.parametrize("yellow_step", [COMMUTATION, PHASE1, SIGNATURE])
def test_setup_step_yellow_advances(yellow_step):
    """No-baseline flip, coast-down wait, provisional first-run signature — all
    benign; the chain proceeds."""
    chain = QuickTuneChain()
    statuses = [YELLOW if s == yellow_step else GREEN for s in FULL_ORDER]
    actions = _drive(chain, statuses)
    assert actions[-1].kind == FINISH
    assert actions[-1].ok is True
    dispatched = [a.step for a in actions if a.kind == DISPATCH]
    assert dispatched == list(FULL_ORDER)


# -------------------------------------------------------------- RED stops
@pytest.mark.parametrize("red_step", list(FULL_ORDER))
def test_red_stops_the_chain_at_that_step(red_step):
    chain = QuickTuneChain()
    statuses = [RED if s == red_step else GREEN for s in FULL_ORDER]
    actions = _drive(chain, statuses)
    stop = actions[-1]
    assert stop.kind == STOP
    assert stop.ok is False
    assert stop.failed_step == red_step
    assert stop.status == RED
    assert stop.needs_operator is False
    # nothing past the failed step is dispatched
    dispatched = [a.step for a in actions if a.kind == DISPATCH]
    assert dispatched == list(FULL_ORDER[:FULL_ORDER.index(red_step) + 1])


def test_red_at_commutation_dispatches_nothing_else():
    chain = QuickTuneChain()
    a0 = chain.start()
    assert a0.step == COMMUTATION
    a1 = chain.on_result(COMMUTATION, RED)
    assert a1.kind == STOP and a1.failed_step == COMMUTATION
    assert chain.done is True


# ------------------------------------------------- phase2 yellow -> operator
def test_phase2_yellow_stops_before_apply_by_default():
    """The safety-critical rule: never auto-apply gains from a flagged Phase 2."""
    chain = QuickTuneChain()
    actions = _drive(chain, [GREEN, GREEN, GREEN, YELLOW, GREEN])
    stop = actions[-1]
    assert stop.kind == STOP
    assert stop.ok is True                 # clean hand-off, not a failure
    assert stop.needs_operator is True
    assert stop.failed_step == PHASE2
    assert stop.status == YELLOW
    # apply was never dispatched
    dispatched = [a.step for a in actions if a.kind == DISPATCH]
    assert APPLY not in dispatched
    assert dispatched == [COMMUTATION, PHASE1, SIGNATURE, PHASE2]


def test_phase2_yellow_can_be_configured_to_advance():
    chain = QuickTuneChain(phase2_yellow_stops=False)
    actions = _drive(chain, [GREEN, GREEN, GREEN, YELLOW, GREEN])
    assert actions[-1].kind == FINISH
    dispatched = [a.step for a in actions if a.kind == DISPATCH]
    assert APPLY in dispatched


# --------------------------------------------------------------- apply step
def test_apply_yellow_stops_as_failure():
    """A RAM write that did not verify is not a success."""
    chain = QuickTuneChain()
    actions = _drive(chain, [GREEN, GREEN, GREEN, GREEN, YELLOW])
    stop = actions[-1]
    assert stop.kind == STOP
    assert stop.ok is False
    assert stop.failed_step == APPLY


def test_include_apply_false_finishes_after_phase2():
    chain = QuickTuneChain(include_apply=False)
    assert APPLY not in chain.steps
    actions = _drive(chain, [GREEN, GREEN, GREEN, GREEN])
    assert actions[-1].kind == FINISH
    dispatched = [a.step for a in actions if a.kind == DISPATCH]
    assert dispatched == [COMMUTATION, PHASE1, SIGNATURE, PHASE2]


# ------------------------------------------------------------- history + misc
def test_history_records_each_step_status():
    chain = QuickTuneChain()
    _drive(chain, [GREEN, YELLOW, GREEN, RED, GREEN])
    assert chain.history == [
        (COMMUTATION, GREEN), (PHASE1, YELLOW), (SIGNATURE, GREEN),
        (PHASE2, RED)]


def test_unknown_status_stops_and_is_never_treated_as_success():
    chain = QuickTuneChain()
    chain.start()
    a = chain.on_result(COMMUTATION, "PURPLE")
    assert a.kind == STOP and a.ok is False
    assert a.status == "PURPLE"


# ----------------------------------------------------------- guard-rails
def test_start_twice_raises():
    chain = QuickTuneChain()
    chain.start()
    with pytest.raises(RuntimeError):
        chain.start()


def test_result_before_start_raises():
    with pytest.raises(RuntimeError):
        QuickTuneChain().on_result(COMMUTATION, GREEN)


def test_result_after_finish_raises():
    chain = QuickTuneChain()
    _drive(chain, [GREEN] * 5)
    with pytest.raises(RuntimeError):
        chain.on_result(APPLY, GREEN)


def test_result_for_wrong_step_raises():
    chain = QuickTuneChain()
    chain.start()                      # at commutation
    with pytest.raises(ValueError):
        chain.on_result(PHASE1, GREEN)


def test_current_step_tracks_progress():
    chain = QuickTuneChain()
    assert chain.current_step is None
    chain.start()
    assert chain.current_step == COMMUTATION
    chain.on_result(COMMUTATION, GREEN)
    assert chain.current_step == PHASE1


def test_action_is_frozen():
    a = ChainAction(DISPATCH, step=COMMUTATION)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.step = PHASE1
