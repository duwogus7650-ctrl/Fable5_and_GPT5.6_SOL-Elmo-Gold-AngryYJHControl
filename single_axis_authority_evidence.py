"""Immutable documentation evidence for EAS Motion - Single Axis.

This is a frozen local authority map, not a live Single Axis implementation.
Import, build, and lookup perform no file, process, network, worker, dialog,
recorder, terminal, or drive I/O.
"""

from __future__ import annotations

from dataclasses import dataclass


MODEL_ID = "single_axis_documented_authority_map_v0_1"
BOUNDARY = (
    "STATIC DOCUMENT MAP ONLY - DOCUMENTED SINGLE AXIS AUTHORITY MAP - "
    "PARTIAL / NEED-DATA - NOT CURRENT EAS SINGLE AXIS STATE - "
    "NOT CURRENT DRIVE STATE - NOT STO TEST EVIDENCE - NO DRIVE READ - "
    "NO DIGITAL OUTPUT WRITE - NO MODE CHANGE - NO ENABLE/DISABLE - "
    "NO PTP/JOG/CURRENT/SINE/HOMING/STEPPER - "
    "NO TERMINAL/COMMAND SEND - NO RECORDER CONFIG/ACQUISITION - "
    "NO COMMAND GENERATION - NO WRITE/APPLY/SV - "
    "NO ENERGIZATION/MOTION - NO DRIVE I/O"
)


@dataclass(frozen=True, slots=True)
class DocumentSource:
    key: str
    location: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DocumentedSingleAxisItem:
    key: str
    label: str
    control: str
    documented_effect: str
    condition: str
    access: str
    risk_class: str
    evidence_status: str


@dataclass(frozen=True, slots=True)
class DocumentedSingleAxisSection:
    key: str
    label: str
    reference: str
    items: tuple[DocumentedSingleAxisItem, ...]


@dataclass(frozen=True, slots=True)
class SingleAxisAuthoritySnapshot:
    model_id: str
    authority: str
    model_status: str
    fidelity: str
    boundary: str
    sections: tuple[DocumentedSingleAxisSection, ...]
    persistent_warnings: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    sources: tuple[DocumentSource, ...]
    can_inspect: bool
    can_read_drive: bool
    can_observe_live_status: bool
    can_toggle_outputs: bool
    can_change_mode: bool
    can_enable: bool
    can_command_position_velocity: bool
    can_command_current: bool
    can_command_sine_homing_stepper: bool
    can_send_terminal_commands: bool
    can_configure_recorder: bool
    can_record: bool
    can_generate_commands: bool
    can_write: bool
    can_apply: bool
    can_persist: bool
    can_energize: bool
    can_move: bool
    can_claim_live_state: bool
    can_claim_safety: bool
    can_claim_eas_parity: bool


_EAS_ROOT = (
    r"C:\Program Files\Elmo Motion Control\Elmo Application Studio III"
    r"\NetHelp\Content"
)
_EAS_UM_ROOT = _EAS_ROOT + r"\EAS_II_SimplIQ_Gold_UM"
_EAS_IMAGE_ROOT = (
    _EAS_ROOT + r"\Resources\Images\EAS_II_SimplIQ_Gold_UM"
)

SOURCES = (
    DocumentSource(
        "drive_setup_html",
        _EAS_UM_ROOT + r"\Drive Setup and Motion Activities.htm",
        "BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE",
    ),
    DocumentSource(
        "single_axis_overview_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_276.png",
        "E05313740D16DBF954ED666EA6F56E6359ED4A1AF2D8813BEBF50CF5BEA21F77",
    ),
    DocumentSource(
        "single_axis_areas_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_277.png",
        "C6DEF3392BBC943CE8337CFEB6D353A160AAB23D123C4D2519B4A8972912BAAA",
    ),
)

_ACCESS = "document: inspect-only - app: inspect-only"


def _item(
        key: str,
        label: str,
        control: str,
        effect: str,
        condition: str,
        risk_class: str,
        evidence_status: str,
) -> DocumentedSingleAxisItem:
    return DocumentedSingleAxisItem(
        key=key,
        label=label,
        control=control,
        documented_effect=effect,
        condition=condition,
        access=_ACCESS,
        risk_class=risk_class,
        evidence_status=evidence_status,
    )


SECTIONS = (
    DocumentedSingleAxisSection(
        key="status_and_io",
        label="Status & I/O",
        reference="Gold UM 8.9.1, 8.9.4, 8.9.5",
        items=(
            _item(
                "motion_status",
                "Motion Status",
                "Position, position error, velocity, active current, fault, "
                "motor/program status",
                "The documented area displays motion-related drive values "
                "and state.",
                "Requires identity-bound fresh telemetry and per-field "
                "validity; this map reads none.",
                "DRIVE_READ",
                "DOCUMENTED DISPLAY - LIVE STATE NEED_DATA",
            ),
            _item(
                "digital_inputs",
                "Digital Inputs",
                "Input bit, assigned function, active/inactive status",
                "The documented monitor displays input numbers, functions "
                "and states.",
                "Requires exact device I/O count, mapping, polarity, filter "
                "and freshness.",
                "DRIVE_READ",
                "DOCUMENTED DISPLAY - LIVE STATE NEED_DATA",
            ),
            _item(
                "digital_outputs",
                "Digital Outputs",
                "General-purpose output status checkboxes",
                "The manual says eligible General Purpose outputs can be "
                "activated or deactivated from this area.",
                "A checkbox is a drive write, not passive status; mapping, "
                "readback, rollback and safe-load behavior are missing.",
                "DRIVE_WRITE",
                "DOCUMENTED CONTROL - EXECUTION NEED_DATA",
            ),
            _item(
                "safety_status",
                "Safety / STO Status",
                "STO1, STO2 and ERR indicators",
                "The documented area displays drive-reported safety-related "
                "input indicators.",
                "Displayed bits are not proof of an independent STO test, "
                "wiring integrity or safe torque removal.",
                "DRIVE_READ / SAFETY-RELATED DISPLAY",
                "DOCUMENTED DISPLAY - NOT STO TEST EVIDENCE",
            ),
        ),
    ),
    DocumentedSingleAxisSection(
        key="mode_and_reference",
        label="Mode & Reference",
        reference="Gold UM 8.9.2-8.9.3.5",
        items=(
            _item(
                "drive_mode",
                "Drive Mode (UM)",
                "Drive Mode: Position / Velocity / Current / Stepper",
                "The selected drive mode determines which cascaded loops and "
                "motion tabs are available.",
                "The manual requires the drive to be disabled before changing "
                "UM; exact commands and rollback are not implemented here.",
                "RAM_WRITE / CONTROL MODE",
                "DOCUMENTED CONTROL - EXECUTION NEED_DATA",
            ),
            _item(
                "position_velocity",
                "Position / Velocity",
                "PTP absolute/relative, repetitive motion and jog",
                "The documented tabs command position profiles or velocity "
                "jogging using mode-dependent profile parameters.",
                "Requires a site motion envelope, limits, stopping distance, "
                "watchdogs, fresh telemetry and independent stop evidence.",
                "MOTION",
                "READBACK PARTIAL IMPLEMENTED - COMMAND EXECUTION NEED_DATA",
            ),
            _item(
                "current_reference",
                "Current Reference",
                "Current command values and Set/Stop controls",
                "The documented Current tab applies requested current "
                "references in the selected loop mode.",
                "Requires verified phase/current conventions, current and "
                "time bounds, thermal limits, watchdog and closeout.",
                "ENERGIZING",
                "READBACK PARTIAL IMPLEMENTED - COMMAND EXECUTION NEED_DATA",
            ),
            _item(
                "sine_homing_stepper",
                "Sine / Homing / Stepper",
                "Sine/step injection, DS-402 homing and Stepper profiles",
                "The documented mode-specific tabs can inject references, "
                "home an axis or execute Stepper motion.",
                "Each path needs exact mode semantics, bounded travel/current, "
                "abort, readback, rollback and field validation.",
                "MOTION / ENERGIZING",
                "DOCUMENTED CONTROL - EXECUTION NEED_DATA",
            ),
        ),
    ),
    DocumentedSingleAxisSection(
        key="activation_and_tools",
        label="Activation & Tools",
        reference="Gold UM 8.9 plus installed overview image",
        items=(
            _item(
                "enable_disable",
                "Enable / Disable",
                "Enable button changes to Disable while active",
                "The manual describes enabling the drive before motion.",
                "Enable energizes the power stage; target identity, disabled "
                "preflight, limits and verified closeout are mandatory.",
                "ENERGIZING",
                "DOCUMENTED CONTROL - EXECUTION NEED_DATA",
            ),
            _item(
                "stop_controls",
                "Stop Controls",
                "Stop and Stop Repetitive Motion",
                "The documented Stop uses configured stop deceleration; "
                "repetitive stop can wait for the current interval.",
                "Software Stop is not independent STO/E-stop and cannot prove "
                "safe torque removal.",
                "SOFTWARE STOP",
                "DOCUMENTED CONTROL - NOT INDEPENDENT STO",
            ),
            _item(
                "terminal_command_reference",
                "Terminal / Command Reference",
                "Terminal prompt and command-reference lookup",
                "The overview places Terminal and Command Reference beside "
                "the Single Axis activity.",
                "An unrestricted terminal can bypass the operation catalog, "
                "allowlist, gates, readback and recovery contracts.",
                "UNBOUNDED COMMAND SURFACE",
                "DOCUMENTED TOOL - COMMAND SEND NEED_DATA",
            ),
            _item(
                "recorder",
                "Recorder",
                "Recorder ribbon, two charts and motion-linked recording",
                "The manual uses Recorder to configure and capture motion "
                "results, including sine-reference recording.",
                "Requires exact signal identity, timing, trigger, ownership, "
                "upload, stop, provenance and motion coupling contracts.",
                "DRIVE STATE / ACQUISITION",
                "DOCUMENTED TOOL - CONFIG/ACQUISITION NEED_DATA",
            ),
        ),
    ),
)

PERSISTENT_WARNINGS = (
    "DOCUMENTED_MAP_ONLY: This inspector normalizes installed Gold UM text "
    "and screenshots; it does not inspect or operate EAS.",
    "NO_RUNTIME_IO: Import, build, lookup, rendering and section changes "
    "perform no file, worker, network, recorder, terminal or drive I/O.",
    "STATUS_NOT_LIVE: Documented displays are names only; no current target "
    "value, timestamp, freshness or validity is supplied.",
    "OUTPUT_IS_MUTATION: A Digital Output checkbox can actuate a physical "
    "output and must never be treated as read-only status.",
    "SOFTWARE_STOP_NOT_STO: A drive Stop or Disable command is not an "
    "independent STO/E-stop and is not safety evidence.",
    "MODE_DEPENDENT: Tabs, commands, loops and units change with UM and "
    "device personality; labels alone do not establish command semantics.",
    "TERMINAL_BYPASS: An unrestricted terminal would bypass catalog gates "
    "and must remain unavailable until a bounded command contract exists.",
    "RECORDER_COUPLING: Recorder configuration/acquisition may be coupled "
    "to energizing or motion and needs separate ownership and closeout.",
)

MISSING_EVIDENCE = (
    "TARGET IDENTITY: Exact drive family/model, axis, serial identity, "
    "firmware, personality and active UM binding.",
    "TELEMETRY FRESHNESS: Signal mapping, sample generation, timestamps, "
    "stale/replay rejection and per-field validity.",
    "DIGITAL I/O CONTRACT: Count, function, polarity, filtering, electrical "
    "load, output readback, rollback and safe-state behavior.",
    "MOTION ENVELOPE: Direction, travel, speed, acceleration, stop "
    "deceleration/distance, limits, load and mechanical restraints.",
    "INDEPENDENT STOP / STO: Tested external stop path, STO wiring, fault "
    "behavior and safe-torque closeout independent of software.",
    "COMMAND MAPPING: Exact UM/tab command sequence, units, validation, "
    "write order, acknowledgement and device-family differences.",
    "RECORDER CONTRACT: Signal identity, timing, buffer, trigger, ownership, "
    "upload integrity, abort and synchronized motion provenance.",
    "ROLLBACK / CLOSEOUT: Tested recovery for timeout, disconnect, fault, "
    "partial command, stale telemetry and unknown final state.",
)

_SNAPSHOT = SingleAxisAuthoritySnapshot(
    model_id=MODEL_ID,
    authority="DOCUMENTED_SINGLE_AXIS_AUTHORITY_MAP_ONLY",
    model_status="PARTIAL_NEED_DATA",
    fidelity="DOCUMENTED_STATIC_REFERENCE",
    boundary=BOUNDARY,
    sections=SECTIONS,
    persistent_warnings=PERSISTENT_WARNINGS,
    missing_evidence=MISSING_EVIDENCE,
    sources=SOURCES,
    can_inspect=True,
    can_read_drive=False,
    can_observe_live_status=False,
    can_toggle_outputs=False,
    can_change_mode=False,
    can_enable=False,
    can_command_position_velocity=False,
    can_command_current=False,
    can_command_sine_homing_stepper=False,
    can_send_terminal_commands=False,
    can_configure_recorder=False,
    can_record=False,
    can_generate_commands=False,
    can_write=False,
    can_apply=False,
    can_persist=False,
    can_energize=False,
    can_move=False,
    can_claim_live_state=False,
    can_claim_safety=False,
    can_claim_eas_parity=False,
)

_SECTION_BY_KEY = {section.key: section for section in SECTIONS}


def build_evidence_snapshot() -> SingleAxisAuthoritySnapshot:
    """Return the canonical immutable no-I/O Single Axis evidence snapshot."""
    return _SNAPSHOT


def section_evidence(key: str) -> DocumentedSingleAxisSection:
    """Return one canonical Single Axis section without runtime I/O."""
    if isinstance(key, bool) or not isinstance(key, str):
        raise TypeError("section key must be a string")
    try:
        return _SECTION_BY_KEY[key]
    except KeyError as exc:
        raise KeyError("unknown Single Axis section %r" % key) from exc
