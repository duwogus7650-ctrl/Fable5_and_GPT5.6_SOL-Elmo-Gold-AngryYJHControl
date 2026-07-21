# -*- coding: utf-8 -*-
"""Pure orchestration state machine for one-button Quick Tuning (EAS parity).

No Qt, no hardware, no I/O.  It owns two things and nothing else: the ORDER of
the guided steps and the accept/stop POLICY per result.  The Qt glue in main.py
owns dispatch, the confirmation dialog, and the result signals; it asks this
module what to do next.  Keeping the decision logic here makes the whole chain
testable offline — the part that was impossible to trust by eye on hardware.

WHY ONE BUTTON: EAS runs its whole Quick Tuning from a single press; our app
made the operator press five buttons (Commutation ID -> Phase 1 -> Signature ->
Phase 2 -> Apply) and hunt for Apply on a different tab.  North stars: "our app
becomes EAS" and "make the UI simple like EAS".

ORDER IS A FIELD LESSON (2026-07-22): Phase 1 clears the motion signature — its
P1_CONFIG persistence transaction trips the audit-status path that invalidates
the signature — so the SIGNATURE MUST RUN AFTER PHASE 1, never before.  With the
order below, by the time Phase 2 runs, both of its gate preconditions (a live
Phase-1 R/L model AND a current motion signature) hold by construction, so the
chain needs no stateful precondition probing.

    commutation -> phase1 -> signature -> phase2 -> apply

Commutation ID is always run first and is nearly free when commutation is already
healthy: the kernel self-selects path A (no CA[7] flip) after a clean
enable-watch.  So "skip re-commutation when healthy" is handled INSIDE the step,
not by branching here.

POLICY (conservative by default; every step but Apply is a supervised, reversible,
RAM/low-current measurement — no SV anywhere):

  * RED at any step            -> STOP(failed).  That kernel already ran its own
                                  S6 / limit-restore closeout; the chain only
                                  halts and reports which step and why.
  * YELLOW at commutation /
    phase1 / signature          -> ADVANCE.  These are benign setup/measurement
                                  yellows: a no-baseline flip-only commutation, a
                                  coast-down settle wait, a provisional first-run
                                  signature.
  * phase2 GREEN                -> ADVANCE to apply.
  * phase2 YELLOW               -> STOP(operator).  The gains ARE computed and
                                  shown, but the chain never auto-applies gains
                                  from a run that flagged something (an early-stop,
                                  a censored measurement): the operator decides.
  * apply GREEN                 -> FINISH.
  * apply YELLOW / RED          -> STOP(failed): the RAM write did not verify.

Every knob above is a constructor parameter so both branches are unit-tested.
"""
from __future__ import annotations

import dataclasses
from typing import FrozenSet, List, Optional, Tuple

# Status strings mirror autotune_velpos / autotune_current / commutation_id.
GREEN = "GREEN"
YELLOW = "YELLOW"
RED = "RED"

# Canonical step ids.  These match the labels the glue dispatches on.
COMMUTATION = "commutation"
PHASE1 = "phase1"
SIGNATURE = "signature"
PHASE2 = "phase2"
APPLY = "apply"

FULL_ORDER: Tuple[str, ...] = (COMMUTATION, PHASE1, SIGNATURE, PHASE2, APPLY)

# Action kinds returned to the glue.
DISPATCH = "DISPATCH"
FINISH = "FINISH"
STOP = "STOP"


@dataclasses.dataclass(frozen=True)
class ChainAction:
    """What the glue should do next.

    kind == DISPATCH -> run ``step``.
    kind == FINISH   -> the chain reached its goal (``ok`` is True).
    kind == STOP     -> the chain halted early.  ``ok`` distinguishes a clean
                        hand-off to the operator (e.g. a YELLOW Phase 2 whose
                        gains are ready to apply manually) from a failure abort.
    """
    kind: str
    step: Optional[str] = None
    ok: bool = False
    reason: str = ""
    failed_step: Optional[str] = None
    status: Optional[str] = None

    @property
    def needs_operator(self) -> bool:
        """A clean early stop that hands control back rather than a failure."""
        return self.kind == STOP and self.ok


class QuickTuneChain:
    """A single-run orchestration state machine.  Not reusable: build one per
    chain run, call :meth:`start`, then feed each step's status to
    :meth:`on_result` until it returns FINISH or STOP."""

    def __init__(
        self,
        *,
        include_apply: bool = True,
        phase2_yellow_stops: bool = True,
        advance_yellow_steps: FrozenSet[str] = frozenset(
            {COMMUTATION, PHASE1, SIGNATURE}),
    ) -> None:
        order = list(FULL_ORDER) if include_apply else list(FULL_ORDER[:-1])
        self._order: List[str] = order
        self._include_apply = include_apply
        self._phase2_yellow_stops = bool(phase2_yellow_stops)
        self._advance_yellow: FrozenSet[str] = frozenset(advance_yellow_steps)
        self._idx: int = -1
        self._done: bool = False
        self.history: List[Tuple[str, str]] = []

    # ------------------------------------------------------------------ state
    @property
    def steps(self) -> Tuple[str, ...]:
        return tuple(self._order)

    @property
    def current_step(self) -> Optional[str]:
        if 0 <= self._idx < len(self._order):
            return self._order[self._idx]
        return None

    @property
    def done(self) -> bool:
        return self._done

    # ---------------------------------------------------------------- driving
    def start(self) -> ChainAction:
        if self._idx != -1 or self._done:
            raise RuntimeError("QuickTuneChain.start() called more than once")
        self._idx = 0
        return ChainAction(DISPATCH, step=self._order[0])

    def on_result(self, step: str, status: str) -> ChainAction:
        """Report the finished step's status and get the next action."""
        if self._done:
            raise RuntimeError("QuickTuneChain already finished")
        if self._idx < 0:
            raise RuntimeError("QuickTuneChain.on_result() before start()")
        expected = self.current_step
        if step != expected:
            raise ValueError(
                "result for %r but the chain is at %r" % (step, expected))
        status = str(status)
        if status not in (GREEN, YELLOW, RED):
            # Unknown status is never silently treated as success.
            return self._stop(
                ok=False, failed_step=step, status=status,
                reason="%s 알 수 없는 상태 %r — 체인 중단" % (step, status))
        self.history.append((step, status))

        if status == RED:
            return self._stop(
                ok=False, failed_step=step, status=status,
                reason="%s RED — 체인 중단 (해당 단계가 자체 클로즈아웃 수행)"
                       % step)

        if status == YELLOW and not self._yellow_advances(step):
            # A non-advancing YELLOW is either a clean hand-off to the operator
            # (Phase 2: gains computed, operator decides whether to Apply) or a
            # failure (Apply: the RAM write did not verify — not a success).
            clean_handoff = (step == PHASE2)
            return self._stop(
                ok=clean_handoff, failed_step=step, status=status,
                reason=self._yellow_stop_reason(step))

        # GREEN, or a YELLOW this step is allowed to advance through.
        return self._advance()

    # --------------------------------------------------------------- internal
    def _yellow_advances(self, step: str) -> bool:
        if step in self._advance_yellow:
            return True
        if step == PHASE2:
            return not self._phase2_yellow_stops
        # apply and any unlisted step: YELLOW does not advance
        return False

    def _yellow_stop_reason(self, step: str) -> str:
        if step == PHASE2:
            return ("Phase 2 YELLOW — 게인은 산출됐으나 자동 적용하지 않습니다."
                    " 값을 확인하고 필요하면 Apply를 직접 실행하세요.")
        if step == APPLY:
            return "Apply YELLOW — RAM 쓰기 검증 미완, 체인 중단"
        return "%s YELLOW — 정책상 이 단계에서 중단" % step

    def _advance(self) -> ChainAction:
        self._idx += 1
        if self._idx >= len(self._order):
            self._done = True
            return ChainAction(FINISH, ok=True)
        return ChainAction(DISPATCH, step=self._order[self._idx])

    def _stop(self, *, ok: bool, reason: str,
              failed_step: Optional[str], status: Optional[str]) -> ChainAction:
        self._done = True
        return ChainAction(
            STOP, ok=ok, reason=reason,
            failed_step=failed_step, status=status)
