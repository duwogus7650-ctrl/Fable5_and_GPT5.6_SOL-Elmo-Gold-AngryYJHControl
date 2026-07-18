"""Pure Expert Page Status / Errors projection.

This module classifies existing in-memory LOCAL MODEL and documented-evidence
objects.  It owns no Qt, worker, transport, command, file, or drive I/O.  The
result is not EAS Enter/Apply state, installed-drive evidence, or a tuning
completion verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import autotune_current
import expert_filter_scheduling_evidence
import expert_tuning_offline


SOURCE = (
    "EAS III SimplIQ/Gold NetHelp · Drive Setup and Motion Activities §8.2.1")
SOURCE_SHA256 = (
    "BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE")


@dataclass(frozen=True)
class ExpertPageStatus:
    key: str
    label: str
    state: str
    detail: str
    navigation_target: str


@dataclass(frozen=True)
class ExpertPageStatusSnapshot:
    authority: str
    overall: str
    pages: tuple[ExpertPageStatus, ...]
    source: str
    source_sha256: str
    can_navigate: bool
    can_calculate: bool
    can_apply: bool
    can_write: bool
    can_query_drive: bool


def _strict_bool(value, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError("%s must be bool" % name)
    return value


def _error_text(value, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("%s must be str or None" % name)
    text = " ".join(value.split())
    if not text:
        raise ValueError("%s must not be blank" % name)
    return text[:240]


def _current_pair_coherent(plant, candidate) -> bool:
    if (not isinstance(plant, expert_tuning_offline.CurrentPlant)
            or not isinstance(
                candidate, expert_tuning_offline.CurrentCandidate)):
        return False
    if (candidate.model_status != expert_tuning_offline.MODEL_STATUS
            or candidate.design_passed is not True
            or candidate.basis != plant.basis):
        return False
    try:
        crossover_rad_s, phase_margin_deg = autotune_current.loop_margins(
            float(candidate.kp_v_per_a),
            float(candidate.ki_hz),
            float(plant.resistance_ohm),
            float(plant.inductance_h),
            float(plant.sampling_time_s),
        )
        crossover_hz = float(crossover_rad_s) / (2.0 * math.pi)
    except (TypeError, ValueError, OverflowError):
        return False
    if not all(math.isfinite(value) for value in (
            crossover_hz, phase_margin_deg)):
        return False
    return (
        math.isclose(
            crossover_hz, float(candidate.crossover_hz),
            rel_tol=1e-9, abs_tol=1e-9)
        and math.isclose(
            float(phase_margin_deg), float(candidate.phase_margin_deg),
            rel_tol=1e-9, abs_tol=1e-9)
    )


def _current_status(plant, candidate, stale: bool,
                    error: str | None) -> ExpertPageStatus:
    has_plant = plant is not None
    has_candidate = candidate is not None
    if error is not None:
        state = "INVALID"
        detail = (
            "Current P1 input/error state: %s · retained objects are "
            "historical only · NOT INSTALLED" % error)
    elif not has_plant and not has_candidate:
        state = "MISSING"
        detail = "No complete local Current P1 plant/candidate pair."
    elif not _current_pair_coherent(plant, candidate):
        state = "INVALID"
        detail = (
            "Current P1 local pair is incomplete or incoherent · "
            "NOT INSTALLED")
    elif stale:
        state = "STALE"
        detail = (
            "Inputs changed after the retained Current P1 MODEL · "
            "historical only · NOT INSTALLED")
    else:
        state = "CURRENT_LOCAL_MODEL"
        detail = (
            "Coherent Current P1 MODEL for the current explicit inputs · "
            "NOT INSTALLED")
    return ExpertPageStatus(
        key="current",
        label="Current P1",
        state=state,
        detail=detail,
        navigation_target="current",
    )


def _vp_status(current: ExpertPageStatus, current_plant, current_candidate,
               vp_plant, vp_candidate, stale: bool,
               error: str | None) -> ExpertPageStatus:
    has_plant = vp_plant is not None
    has_candidate = vp_candidate is not None
    if error is not None:
        state = "INVALID"
        detail = (
            "Velocity/Position P2 input/error state: %s · retained objects "
            "are historical only · NOT INSTALLED" % error)
    elif current.state != "CURRENT_LOCAL_MODEL":
        if has_plant or has_candidate:
            state = "INVALID"
            detail = (
                "P2 exists without a current coherent P1 authority binding · "
                "NOT INSTALLED")
        else:
            state = "BLOCKED"
            detail = (
                "A current coherent P1 LOCAL MODEL is required before P2.")
    elif not has_plant and not has_candidate:
        state = "MISSING"
        detail = "No complete local Velocity/Position P2 plant/candidate pair."
    elif (not isinstance(
            vp_plant, expert_tuning_offline.VelocityPositionPlant)
            or not isinstance(
                vp_candidate,
                expert_tuning_offline.VelocityPositionCandidate)):
        state = "INVALID"
        detail = "Velocity/Position P2 local pair is incomplete · NOT INSTALLED"
    elif (vp_plant.current_plant is not current_plant
          or vp_plant.current_candidate is not current_candidate):
        state = "INVALID"
        detail = (
            "Velocity/Position P2 binding does not match the current P1 pair · "
            "NOT INSTALLED")
    else:
        try:
            expected = (
                expert_tuning_offline.design_velocity_position_candidate(
                    vp_plant))
        except (TypeError, ValueError, OverflowError):
            expected = None
        if expected != vp_candidate:
            state = "INVALID"
            detail = (
                "Velocity/Position P2 candidate is incoherent with its exact "
                "plant binding · NOT INSTALLED")
        elif stale:
            state = "STALE"
            detail = (
                "K_a/B inputs changed after the retained P2 MODEL · "
                "historical only · NOT INSTALLED")
        else:
            state = "CURRENT_LOCAL_MODEL"
            detail = (
                "Coherent P2 MODEL bound to the exact current P1 pair · "
                "NOT INSTALLED")
    return ExpertPageStatus(
        key="vp",
        label="Velocity / Position P2",
        state=state,
        detail=detail,
        navigation_target="vp",
    )


def _evidence_status(filter_evidence) -> ExpertPageStatus:
    canonical = (
        expert_filter_scheduling_evidence.build_evidence_snapshot())
    valid = (
        isinstance(
            filter_evidence,
            expert_filter_scheduling_evidence.ExpertEvidenceSnapshot)
        and filter_evidence == canonical
    )
    if valid:
        state = "DOCUMENTED_PARTIAL"
        detail = (
            "%d unresolved document conflicts · exact evaluator, emulation "
            "and write remain NEED-DATA"
            % len(filter_evidence.conflicts))
    else:
        state = "INVALID"
        detail = (
            "Filter/Scheduling evidence authority is incomplete or "
            "unexpected · NEED-DATA")
    return ExpertPageStatus(
        key="evidence",
        label="Filter / Scheduling Evidence",
        state=state,
        detail=detail,
        navigation_target="evidence",
    )


def build_page_status_snapshot(
        *, current_plant, current_candidate, current_stale,
        current_error, vp_plant, vp_candidate, vp_stale, vp_error,
        filter_evidence) -> ExpertPageStatusSnapshot:
    """Classify only the supplied immutable/local objects, without I/O."""
    current_stale = _strict_bool(current_stale, "current_stale")
    vp_stale = _strict_bool(vp_stale, "vp_stale")
    current_error = _error_text(current_error, "current_error")
    vp_error = _error_text(vp_error, "vp_error")
    current = _current_status(
        current_plant, current_candidate, current_stale, current_error)
    vp = _vp_status(
        current,
        current_plant,
        current_candidate,
        vp_plant,
        vp_candidate,
        vp_stale,
        vp_error,
    )
    evidence = _evidence_status(filter_evidence)
    return ExpertPageStatusSnapshot(
        authority="LOCAL_STATUS_ONLY",
        overall="PARTIAL",
        pages=(current, vp, evidence),
        source=SOURCE,
        source_sha256=SOURCE_SHA256,
        can_navigate=True,
        can_calculate=False,
        can_apply=False,
        can_write=False,
        can_query_drive=False,
    )
