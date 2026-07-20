"""Pure enable/disable state projection for the Single Axis surface.

This module consumes an already-decoded :class:`AxisSafetySnapshot`.  It never
imports Qt, a worker, or a drive transport and it never sends ``MO=1`` or any
other command.  The projection is drive-reported MODEL evidence only; it is
not proof of independent STO/E-stop response, torque isolation, or readiness
to energize.
"""

from __future__ import annotations

from dataclasses import dataclass

import single_axis_status


UNKNOWN = "UNKNOWN"
DISABLED_REPORTED = "DISABLED_REPORTED"
ENABLE_REQUESTED_WAITING = "ENABLE_REQUESTED_WAITING"
ENABLED_REPORTED = "ENABLED_REPORTED"
DISABLING_BRAKE_HOLD_REPORTED = "DISABLING_BRAKE_HOLD_REPORTED"
FAULT_REPORTED = "FAULT_REPORTED"

EVIDENCE_LABEL = (
    "DRIVE-REPORTED MODEL - MO/SO STATE - NOT STO TEST EVIDENCE")
ENABLE_BOUNDARY = (
    "ENABLE REMAINS LOCKED / NEED-DATA - no executable MO=1 surface; "
    "current envelope, independent protection, operator gate, telemetry "
    "abort, and verified closeout are not commissioned")
DISABLE_ROUTE = "ST -> MO=0 -> terminal readback"


@dataclass(frozen=True)
class EnableStateProjection:
    """Immutable, non-authoritative Single Axis enable-state projection."""

    state: str
    label: str
    detail: str
    evidence_label: str
    conditions: tuple[str, ...]
    enable_executable: bool
    enable_operation_id: str
    enable_boundary: str
    disable_operation_id: str
    disable_route: str


def _unknown(detail: str) -> EnableStateProjection:
    return EnableStateProjection(
        state=UNKNOWN,
        label="UNKNOWN - ENABLE LOCKED",
        detail=str(detail or "No current admitted safety snapshot"),
        evidence_label=EVIDENCE_LABEL,
        conditions=(),
        enable_executable=False,
        enable_operation_id="motor.enable",
        enable_boundary=ENABLE_BOUNDARY,
        disable_operation_id="drive.stop",
        disable_route=DISABLE_ROUTE,
    )


def project_enable_state(snapshot: object) -> EnableStateProjection:
    """Project documented MO/SO lifecycle states without granting authority."""
    if not isinstance(snapshot, single_axis_status.AxisSafetySnapshot):
        return _unknown("Safety snapshot type is missing or invalid")
    if snapshot.evidence_label != single_axis_status.EVIDENCE_LABEL:
        return _unknown("Safety snapshot evidence identity is invalid")
    if snapshot.state != single_axis_status.CURRENT:
        return _unknown(
            snapshot.reason or "Safety snapshot authority is not current")

    raw = snapshot.raw
    try:
        mo = int(raw["MO"])
        so = int(raw["SO"])
        mf = int(raw["MF"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return _unknown("Required MO/SO/MF values are unavailable")
    if mo not in (0, 1) or so not in (0, 1) or mf < 0:
        return _unknown("MO/SO/MF values are outside the documented contract")

    conditions = ("MO=%d" % mo, "SO=%d" % so)
    fault_observed = bool(
        mf != 0
        or snapshot.amplifier_code not in (None, 0)
        or snapshot.enabled_fault_reported is True
        or snapshot.sto_diagnostics_error_reported is True
    )
    if fault_observed:
        fault_conditions = list(conditions)
        if mf:
            fault_conditions.append("MF=%d" % mf)
        if snapshot.amplifier_code not in (None, 0):
            fault_conditions.append(
                "SR amplifier code=0x%X" % snapshot.amplifier_code)
        if snapshot.enabled_fault_reported is True:
            fault_conditions.append("SR6 enable-time fault=1")
        if snapshot.sto_diagnostics_error_reported is True:
            fault_conditions.append("SR27 STO diagnostics error=1")
        return EnableStateProjection(
            state=FAULT_REPORTED,
            label="FAULT REPORTED - NO AUTO-RETRY",
            detail=(
                "Use STOP + Disable, then inspect MF/CD/EE evidence; "
                "do not automatically retry enable."),
            evidence_label=EVIDENCE_LABEL,
            conditions=tuple(fault_conditions),
            enable_executable=False,
            enable_operation_id="motor.enable",
            enable_boundary=ENABLE_BOUNDARY,
            disable_operation_id="drive.stop",
            disable_route=DISABLE_ROUTE,
        )

    if (mo, so) == (0, 0):
        state = DISABLED_REPORTED
        label = "DISABLED REPORTED - ENABLE LOCKED"
        detail = (
            "Drive reports MO=0 / SO=0. This is not independent torque-"
            "isolation evidence and does not make Enable executable.")
    elif (mo, so) == (1, 0):
        state = ENABLE_REQUESTED_WAITING
        label = "ENABLE REQUESTED - SO=0 / REFERENCES BLOCKED"
        detail = (
            "MO=1 was reported but servo authority is not ready; wait for "
            "SO=1 before any reference. STOP remains the escape path.")
    elif (mo, so) == (1, 1):
        state = ENABLED_REPORTED
        label = "ENABLED REPORTED - ENERGIZED"
        detail = (
            "Drive reports MO=1 / SO=1. STOP remains available; this is not "
            "proof of independent STO/E-stop protection.")
    else:
        state = DISABLING_BRAKE_HOLD_REPORTED
        label = "DISABLING / BRAKE HOLD - SO=1"
        detail = (
            "Drive reports MO=0 while SO=1; the Gold reference documents "
            "this during brake application. Disabled closeout remains "
            "unverified until terminal readback completes.")

    return EnableStateProjection(
        state=state,
        label=label,
        detail=detail,
        evidence_label=EVIDENCE_LABEL,
        conditions=conditions,
        enable_executable=False,
        enable_operation_id="motor.enable",
        enable_boundary=ENABLE_BOUNDARY,
        disable_operation_id="drive.stop",
        disable_route=DISABLE_ROUTE,
    )
