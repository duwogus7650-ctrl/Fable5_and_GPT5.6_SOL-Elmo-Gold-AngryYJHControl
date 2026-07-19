"""Immutable ledger for the bounded 2026-07-19 EAS live parity audit.

This module records what was actually observed in EAS 3.0.0.26 and what the
current AngryYJH implementation does.  It is deliberately not an automation
driver and performs no file, serial, worker, drive, recorder, or motion I/O.
No entry grants write, save, energization, motion, or full EAS-parity
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Optional


LIVE_UI_OBSERVED = "LIVE_UI_OBSERVED"
VALUE_PARITY_OBSERVED = "VALUE_PARITY_OBSERVED"
PARTIAL_LIVE_OBSERVED = "PARTIAL_LIVE_OBSERVED"
UI_SEMANTICS_MISMATCH = "UI_SEMANTICS_MISMATCH"
MISMATCH_NEED_DATA = "MISMATCH_NEED_DATA"
DOC_ONLY = "DOC_ONLY"
STAND_IN = "STAND_IN"
NOT_EXECUTED_NEED_DATA = "NOT_EXECUTED_NEED_DATA"

VERDICTS = frozenset({
    LIVE_UI_OBSERVED,
    VALUE_PARITY_OBSERVED,
    PARTIAL_LIVE_OBSERVED,
    UI_SEMANTICS_MISMATCH,
    MISMATCH_NEED_DATA,
    DOC_ONLY,
    STAND_IN,
    NOT_EXECUTED_NEED_DATA,
})

AUDIT_DATE_KST = "2026-07-19"
EAS_VERSION = "3.0.0.26"
TARGET_ALIAS = "Drive01"
FIRMWARE = "Twitter 01.01.16.00 08Mar2020B01G"
AUDIT_EXECUTION_BOUNDARY = "READ_ONLY_UI_AND_QUERY_OBSERVATION"

EAS_TERMINAL_RAW_PX = -2_038_379_934
OUR_RAW_PX = -2_038_379_934
EAS_SINGLE_AXIS_POSITION = -2_004_825_502
OUR_EAS_SINGLE_AXIS_POSITION = -2_004_825_502
POSITION_DISPLAY_DELTA = EAS_SINGLE_AXIS_POSITION - EAS_TERMINAL_RAW_PX


@dataclass(frozen=True, slots=True)
class ParityEntry:
    feature_id: str
    area: str
    eas_behavior: str
    our_behavior: str
    verdict: str
    evidence: str
    eas_value: Optional[int | float | str] = None
    our_value: Optional[int | float | str] = None
    live_observed: bool = False
    field_executed: bool = False
    motion_executed: bool = False
    write_executed: bool = False
    save_executed: bool = False
    can_claim_eas_parity: bool = False


def _entry(
        feature_id: str,
        area: str,
        eas_behavior: str,
        our_behavior: str,
        verdict: str,
        evidence: str,
        *,
        eas_value: Optional[int | float | str] = None,
        our_value: Optional[int | float | str] = None,
        live_observed: bool = False,
) -> ParityEntry:
    return ParityEntry(
        feature_id=feature_id,
        area=area,
        eas_behavior=eas_behavior,
        our_behavior=our_behavior,
        verdict=verdict,
        evidence=evidence,
        eas_value=eas_value,
        our_value=our_value,
        live_observed=live_observed,
    )


ENTRIES = (
    _entry(
        "shell.menus", "Shell",
        "File, Parameters, Tools, Views and Floating Tools ribbons/menus.",
        "A bounded local menu shell and operation catalog.",
        PARTIAL_LIVE_OBSERVED,
        "EAS menus observed; individual command behavior was not executed.",
        live_observed=True,
    ),
    _entry(
        "shell.system_configuration", "System Configuration",
        "Connected target identity, board, firmware, PAL and COM3 projection.",
        "Single admitted Gold target projection and read-only connection.",
        VALUE_PARITY_OBSERVED,
        "Identity fields and connection route matched during exclusive sessions.",
        live_observed=True,
    ),
    _entry(
        "shell.tool_organizer", "Shell",
        "Native activity/Favorites visibility and persistence behavior.",
        "Session-only show/hide/reorder/reset for eight fixed app pages.",
        STAND_IN,
        "The local tool was tested, but native EAS Tool Organizer behavior "
        "and persistence were not exercised in this audit.",
    ),
    _entry(
        "shell.host_status_monitor", "Shell",
        "Native EAS configurable Status Monitor/Quick Watch.",
        "Modeless host-observed PX/VX/PE/IQ/MO projection.",
        STAND_IN,
        "The app reuses admitted telemetry and performs no native EAS polling "
        "or configuration round trip.",
    ),
    _entry(
        "motor.profile", "Motor Settings",
        "Configured motor DB/current/speed/pole/R/L fields.",
        "Bounded motor profile readback and editable local form.",
        PARTIAL_LIVE_OBSERVED,
        "The EAS page and current configured values were observed; a full "
        "field-by-field app readback/write parity transaction was not run.",
        live_observed=True,
    ),
    _entry(
        "motor.persistence_transaction", "Motor Settings",
        "Apply/Revert and Save/SV behavior in EAS.",
        "Durable WAL/readback/rollback transaction with production authority "
        "gates.",
        NOT_EXECUTED_NEED_DATA,
        "The app state machine has offline fault-injection evidence, but no "
        "EAS Apply/Revert/SV transaction was executed in this audit.",
        live_observed=True,
    ),
    _entry(
        "feedback.sensor_panels", "Feedback",
        "Sensor-specific EAS pages and live fields.",
        "Twenty-three sensor read/preview panels.",
        PARTIAL_LIVE_OBSERVED,
        "Only the current EnDat 2.2 target was observed live; the remaining "
        "sensor panels are not field-validated.",
        live_observed=True,
    ),
    _entry(
        "feedback.settings_preview", "Feedback",
        "Editable feedback settings with EAS validation and write semantics.",
        "Read/preview UI with unknown write mappings rejected.",
        STAND_IN,
        "The EnDat page was observed, but Apply/Revert/write side effects and "
        "all other feedback types were not executed.",
        live_observed=True,
    ),
    _entry(
        "axis.summary", "Axis Setup",
        "Axis/feedback/mode configuration distributed across EAS pages.",
        "Read-only UM/feedback-routing/FC/BP/SC/limit summary.",
        PARTIAL_LIVE_OBSERVED,
        "UM=5 and EnDat routing agree with EAS; the full raw summary has no "
        "one-page EAS behavioral oracle.",
        live_observed=True,
    ),
    _entry(
        "quick.axis_configuration", "Quick Tuning",
        "Single Axis, rotary motor/load, single feedback, Position UM=5.",
        "Guided Quick flow with equivalent high-level axis selection.",
        PARTIAL_LIVE_OBSERVED,
        "EAS configuration page observed; no Apply or tuning execution.",
        live_observed=True,
    ),
    _entry(
        "quick.motor_settings", "Quick Tuning",
        "Configured motor database/current/speed/pole/R/L/Ke fields.",
        "Motor profile readback and separately measured P1 R/L candidate.",
        PARTIAL_LIVE_OBSERVED,
        "Stored EAS R/L (0.1316 ohm, 0.0395 mH) differs from the earlier "
        "identified candidate; the two authorities must remain separate.",
        live_observed=True,
    ),
    _entry(
        "quick.feedback_settings", "Quick Tuning",
        "Serial Absolute EnDat 2.2 on Port A and detailed timing/options.",
        "EnDat 2.2 read panels plus separately gated Encoder Maintenance.",
        PARTIAL_LIVE_OBSERVED,
        "Feedback type and principal routing matched; no setting write.",
        live_observed=True,
    ),
    _entry(
        "quick.automatic_tuning", "Quick Tuning",
        "Six ordered phases with start-phase and Full Log controls.",
        "Six-stage guided flow with local/field-gated phase implementations.",
        NOT_EXECUTED_NEED_DATA,
        "EAS stage order observed; Run Automatic Tuning was not clicked.",
        live_observed=True,
    ),
    _entry(
        "tuning.phase1", "Tuning",
        "EAS Current Identification/Design/Verification pages.",
        "Bounded current identification, candidate design and installed gain "
        "readback.",
        PARTIAL_LIVE_OBSERVED,
        "Design and installed gains match current EAS values; EAS "
        "identification/verification was not executed.",
        live_observed=True,
    ),
    _entry(
        "tuning.phase2", "Tuning",
        "EAS Fast 100% CL V/P identification and subsequent design.",
        "Separately bounded low-current Phase 2 identification/design.",
        UI_SEMANTICS_MISMATCH,
        "Installed design gains match, but the identification experiments "
        "and current amplitudes are not equivalent.",
        live_observed=True,
    ),
    _entry(
        "tuning.installed_gain_verify", "Tuning",
        "Current and V/P Time/Bode Verify actions.",
        "Installed-gain verification contracts with hardware execution "
        "gated.",
        NOT_EXECUTED_NEED_DATA,
        "Values were compared; no EAS or app Verify experiment was run.",
        live_observed=True,
    ),
    _entry(
        "expert.user_units", "Expert Tuning",
        "No Conversion, factor 1, calculation on motor.",
        "Explicit-input documented formula inspector only.",
        DOC_ONLY,
        "Live EAS page observed; current drive FC/OF propagation is not read.",
        live_observed=True,
    ),
    _entry(
        "expert.current_limits", "Expert Tuning",
        "MC/BV/PL/CL/PL2/US fields; page currently reports invalid parameters.",
        "Immutable documented parameter map, not current drive state.",
        DOC_ONLY,
        "Live values and EAS validation warning observed; app has no live page.",
        live_observed=True,
    ),
    _entry(
        "expert.motion_limits", "Expert Tuning",
        "SD/VH and No-Modulo mode; position limits ignored by drive.",
        "Immutable documented limits/modulo map.",
        DOC_ONLY,
        "Live EAS values observed; app does not evaluate active protection.",
        live_observed=True,
    ),
    _entry(
        "expert.protections", "Expert Tuning",
        "Position/velocity/yaw error and motor-stuck thresholds.",
        "Immutable documented protections map.",
        DOC_ONLY,
        "Live EAS values observed; protection efficacy was not tested.",
        live_observed=True,
    ),
    _entry(
        "expert.application.settling", "Expert Tuning",
        "Position/velocity windows and 20 ms times.",
        "Immutable documented Application Settings map.",
        DOC_ONLY,
        "Live EAS values observed; app has no current-drive readback.",
        live_observed=True,
    ),
    _entry(
        "expert.application.io", "Expert Tuning",
        "Input/output level, function, filter and status table.",
        "Separate bounded Digital Input/Output read-only snapshots.",
        VALUE_PARITY_OBSERVED,
        "Inputs 1..6 active GP and outputs 1..4 inactive GP matched.",
        live_observed=True,
    ),
    _entry(
        "expert.current.identification", "Expert Tuning",
        "Three-phase experiment, 60% PL and configured R/L plant.",
        "Bounded P1 identification and independent local candidate model.",
        NOT_EXECUTED_NEED_DATA,
        "EAS controls/values observed; Identify was not clicked.",
        live_observed=True,
    ),
    _entry(
        "expert.current.design", "Expert Tuning",
        "5 kHz, 59 degree design; rounded KP/KI display.",
        "P1 model computes KP=0.0857 and KI=782.5188.",
        VALUE_PARITY_OBSERVED,
        "Displayed EAS 0.086/782.52 agrees after rounding.",
        eas_value="KP 0.086; KI 782.52",
        our_value="KP 0.0857; KI 782.5188",
        live_observed=True,
    ),
    _entry(
        "expert.current.verification_time", "Expert Tuning",
        "Installed KP=0.0857 and KI=782.5188 with Verify controls.",
        "Installed-gain read/verification contracts, execution still gated.",
        VALUE_PARITY_OBSERVED,
        "Installed gain values matched exactly; Verify was not clicked.",
        eas_value="KP 0.0857; KI 782.5188",
        our_value="KP 0.0857; KI 782.5188",
        live_observed=True,
    ),
    _entry(
        "expert.commutation", "Expert Tuning",
        "Absolute Serial phasing at 100% CL with 1.4 electrical cycles.",
        "A separate bounded 1.30 A commutation-signature procedure.",
        UI_SEMANTICS_MISMATCH,
        "Both concern commutation, but the procedures and amplitudes are not "
        "functionally identical; EAS Run Commutation was not clicked.",
        live_observed=True,
    ),
    _entry(
        "expert.velocity_position.identification", "Expert Tuning",
        "Fast open-loop identification at 100% CL.",
        "Separately bounded low-current Phase 2 identification.",
        UI_SEMANTICS_MISMATCH,
        "EAS controls observed; identification procedures are not identical.",
        live_observed=True,
    ),
    _entry(
        "expert.velocity_position.design", "Expert Tuning",
        "PI+LPF design with KP2/KI2/KP3/feed-forward/filter fields.",
        "P2 local model and documented filter/scheduling inspector.",
        VALUE_PARITY_OBSERVED,
        "KP2≈0.000196, KI2=10.7 and KP3=85.2114 match current EAS values; "
        "filter evaluation itself remains documented-only.",
        live_observed=True,
    ),
    _entry(
        "expert.velocity_position.scheduling", "Expert Tuning",
        "Scheduling Off with PIP/filter tabs.",
        "Documented topology inspector; no live scheduler evaluator.",
        DOC_ONLY,
        "EAS page observed; no scheduling operation executed.",
        live_observed=True,
    ),
    _entry(
        "expert.velocity_position.verification_time", "Expert Tuning",
        "Motion controls, gains/filters and Recorder charts.",
        "Static documented Time Verification map.",
        DOC_ONLY,
        "Live EAS page observed; Verify/motion/recording was not executed.",
        live_observed=True,
    ),
    _entry(
        "expert.summary", "Expert Tuning",
        "SV, upload, design export and DB import recommended actions.",
        "Static transaction-authority map.",
        DOC_ONLY,
        "Live checked recommendations observed; Save was not clicked.",
        live_observed=True,
    ),
    _entry(
        "single_axis.status", "Single Axis",
        "Position/error/velocity/current and motor/program status.",
        "Live raw-PX telemetry card with separate PU/EAS coordinate evidence.",
        PARTIAL_LIVE_OBSERVED,
        "Disabled/zero-velocity/zero-current state matched; the raw dashboard "
        "is now explicitly labelled PX and the EAS coordinate is PU.",
        live_observed=True,
    ),
    _entry(
        "single_axis.position", "Single Axis",
        "Position tab with PTP/Jog/profile controls.",
        "Separate raw PX and EAS/DS402 PU readback, session zero and locked "
        "finite PTP surface.",
        PARTIAL_LIVE_OBSERVED,
        "Profile values observed; no position motion executed.",
        live_observed=True,
    ),
    _entry(
        "single_axis.session_zero", "Single Axis",
        "Zero Position control.",
        "Generation-bound Set Session Zero using PX=0 with readback.",
        NOT_EXECUTED_NEED_DATA,
        "Both controls exist, but PX=0 was not executed in this audit and "
        "EnDat permanent datum behavior is a separate authority.",
        live_observed=True,
    ),
    _entry(
        "single_axis.finite_ptp", "Single Axis",
        "PTP Absolute/Relative, Jog and Run Held.",
        "Finite PTP backend with live execution locked by motion-envelope "
        "NEED-DATA.",
        NOT_EXECUTED_NEED_DATA,
        "EAS profile controls were observed; no app or EAS motion was run.",
        live_observed=True,
    ),
    _entry(
        "single_axis.position.raw_px", "Single Axis",
        "Terminal query returns raw PX.",
        "Bounded reader returns raw PX.",
        VALUE_PARITY_OBSERVED,
        "Exclusive-session read-only observations agree exactly.",
        eas_value=EAS_TERMINAL_RAW_PX,
        our_value=OUR_RAW_PX,
        live_observed=True,
    ),
    _entry(
        "single_axis.position.eas_display", "Single Axis",
        "Single Axis and Verification-Time display PU/DS402 0x6064 position.",
        "Displays PU separately from raw PX and reports PU-PX without "
        "auto-correction.",
        VALUE_PARITY_OBSERVED,
        "The displayed value now matches PU exactly. PU-PX remains exactly "
        "2^25 counts and the firmware-internal coordinate origin is unresolved.",
        eas_value=EAS_SINGLE_AXIS_POSITION,
        our_value=OUR_EAS_SINGLE_AXIS_POSITION,
        live_observed=True,
    ),
    _entry(
        "single_axis.velocity", "Single Axis",
        "Jog/velocity profile with SP/AC/DC/SD fields.",
        "Bounded raw JV/SP/AC/DC/SD/VX readback.",
        VALUE_PARITY_OBSERVED,
        "SP=4444444 and AC=DC=SD=1000000 matched; Jog was not run.",
        live_observed=True,
    ),
    _entry(
        "single_axis.current", "Single Axis",
        "Five editable Current Command presets with Set controls.",
        "Separate TC/IQ/ID/CL/PL/LC/MC readback plus five local Current "
        "Command drafts; all Set TC outputs remain locked.",
        PARTIAL_LIVE_OBSERVED,
        "The five-preset shape, zero defaults and shared TC target match the "
        "observed EAS UI. Enable/Set behavior was not executed and app output "
        "remains locked.",
        live_observed=True,
    ),
    _entry(
        "single_axis.sine", "Single Axis",
        "Sine/Step injection settings and Start/Stop.",
        "Documented authority row only.",
        NOT_EXECUTED_NEED_DATA,
        "EAS fields observed; Allow Sine Motion and Start were not used.",
        live_observed=True,
    ),
    _entry(
        "single_axis.homing", "Single Axis",
        "Method 1, socket, offset, acceleration and speed controls.",
        "Documented authority row only.",
        NOT_EXECUTED_NEED_DATA,
        "EAS fields observed; Home was disabled/not executed.",
        live_observed=True,
    ),
    _entry(
        "single_axis.digital_inputs", "Single Axis",
        "Six GP input status indicators.",
        "IL/IF/IP bounded read-only snapshot for six inputs.",
        VALUE_PARITY_OBSERVED,
        "All six logical active/GP states matched.",
        live_observed=True,
    ),
    _entry(
        "single_axis.digital_outputs", "Single Axis",
        "Four output status checkboxes.",
        "OL/GO/OP bounded read-only snapshot for four outputs.",
        VALUE_PARITY_OBSERVED,
        "All four logical inactive/GP states matched; no output actuation.",
        live_observed=True,
    ),
    _entry(
        "single_axis.drive_mode", "Single Axis",
        "Position UM=5.",
        "Exact one-query UM read-only snapshot.",
        VALUE_PARITY_OBSERVED,
        "UM=5 Position matched.",
        eas_value=5,
        our_value=5,
        live_observed=True,
    ),
    _entry(
        "single_axis.encoder_maintenance", "Feedback",
        "Encoder Maintenance entry from EnDat feedback settings.",
        "Separately gated TW[18..20] maintenance surface.",
        PARTIAL_LIVE_OBSERVED,
        "Entry and encoder type observed; no maintenance write executed.",
        live_observed=True,
    ),
    _entry(
        "single_axis.terminal", "Single Axis",
        "General terminal and command reference.",
        "Unrestricted terminal intentionally unavailable.",
        NOT_EXECUTED_NEED_DATA,
        "Only the exact read-only PX query was issued in EAS.",
        live_observed=True,
    ),
    _entry(
        "single_axis.enable", "Single Axis",
        "Enable/Disable control.",
        "Enable remains locked; Stop+Disable is a bounded escape path.",
        NOT_EXECUTED_NEED_DATA,
        "Motor remained disabled; Enable was not clicked.",
        live_observed=True,
    ),
    _entry(
        "single_axis.ptp_jog", "Single Axis",
        "Absolute/relative PTP, Jog and Run Held.",
        "Finite PTP backend exists but live execution remains locked.",
        NOT_EXECUTED_NEED_DATA,
        "Controls/profile values observed; no motion executed.",
        live_observed=True,
    ),
    _entry(
        "recorder.ribbon", "Recorder",
        "Resolution, duration, mode, trigger, activation and file controls.",
        "Local Recorder ribbon with implemented Immediate subset and locks.",
        PARTIAL_LIVE_OBSERVED,
        "EAS ribbon/options observed; several app controls are stand-ins or "
        "placeholders rather than native parity.",
        live_observed=True,
    ),
    _entry(
        "recorder.capture", "Recorder",
        "Drive acquisition, trigger, upload and multi-drive workflows.",
        "Single-drive finite Immediate capture backend.",
        NOT_EXECUTED_NEED_DATA,
        "No EAS acquisition was started in this audit.",
        live_observed=True,
    ),
    _entry(
        "recorder.view", "Recorder",
        "Two charts and native View Design/statistics interactions.",
        "Two-lane local renderer, zoom, FFT and A:B statistics.",
        STAND_IN,
        "Local behaviors are separately tested; native EAS file/glyph/"
        "interaction parity was not executed.",
        live_observed=True,
    ),
    _entry(
        "recorder.export", "Recorder",
        "Native recording Save/Save As and preset formats.",
        "Local CSV plus provenance sidecar and local JSON workspace.",
        STAND_IN,
        "Local export integrity is tested, but EAS file-format compatibility "
        "and native open-save-open behavior were not exercised.",
        live_observed=True,
    ),
    _entry(
        "recorder.statistics", "Recorder",
        "Native chart statistics/cursor behavior.",
        "Local time/FFT/full+A:B statistics and statistics CSV.",
        STAND_IN,
        "Formulas have static/offline evidence; exact native interaction, "
        "rounding, glyph and file parity were not executed.",
        live_observed=True,
    ),
    _entry(
        "status.session_log", "Status / Log",
        "Native EAS drive-origin status/fault history and controls.",
        "Bounded redacted host-observed event/session log.",
        STAND_IN,
        "The app log is not drive fault history; native Ack/Clear/Reset "
        "behavior was not exercised.",
    ),
    _entry(
        "status.monitor", "Supporting Tools",
        "Native EAS Status Monitor/Quick Watch behavior.",
        "Host-observed fixed-signal modeless monitor.",
        STAND_IN,
        "No native EAS monitor behavior was executed in this audit.",
    ),
    _entry(
        "persistence", "Persistence",
        "Apply/Revert/SV/upload/export/DB operations across pages.",
        "Separated local/WAL/drive authority contracts with production writes "
        "locked in the audited surfaces.",
        NOT_EXECUTED_NEED_DATA,
        "No Apply, Save, SV, upload, export or DB mutation was executed.",
        live_observed=True,
    ),
    _entry(
        "persistence.audit", "Persistence",
        "EAS native page/apply/save state and transaction result.",
        "Local durable safety ledger, identity binding and recovery latches.",
        STAND_IN,
        "The ledger protects app transactions but is not an EAS transaction "
        "or proof of flash persistence.",
    ),
    _entry(
        "safety.drive_stop", "Safety Escape",
        "EAS global STOP and page Stop controls.",
        "ST then MO=0 software Stop+Disable path.",
        NOT_EXECUTED_NEED_DATA,
        "Controls were observed but not clicked in this audit; neither is "
        "independent STO/E-stop evidence.",
        live_observed=True,
    ),
)

REQUIRED_FEATURE_IDS = frozenset({
    "shell.menus",
    "shell.system_configuration",
    "shell.tool_organizer",
    "shell.host_status_monitor",
    "motor.profile",
    "motor.persistence_transaction",
    "feedback.sensor_panels",
    "feedback.settings_preview",
    "axis.summary",
    "quick.axis_configuration",
    "quick.motor_settings",
    "quick.feedback_settings",
    "quick.automatic_tuning",
    "tuning.phase1",
    "tuning.phase2",
    "tuning.installed_gain_verify",
    "expert.user_units",
    "expert.current_limits",
    "expert.motion_limits",
    "expert.protections",
    "expert.application.settling",
    "expert.application.io",
    "expert.current.identification",
    "expert.current.design",
    "expert.current.verification_time",
    "expert.commutation",
    "expert.velocity_position.identification",
    "expert.velocity_position.design",
    "expert.velocity_position.scheduling",
    "expert.velocity_position.verification_time",
    "expert.summary",
    "single_axis.status",
    "single_axis.position",
    "single_axis.session_zero",
    "single_axis.finite_ptp",
    "single_axis.position.raw_px",
    "single_axis.position.eas_display",
    "single_axis.velocity",
    "single_axis.current",
    "single_axis.sine",
    "single_axis.homing",
    "single_axis.digital_inputs",
    "single_axis.digital_outputs",
    "single_axis.drive_mode",
    "single_axis.encoder_maintenance",
    "single_axis.terminal",
    "single_axis.enable",
    "single_axis.ptp_jog",
    "recorder.ribbon",
    "recorder.capture",
    "recorder.view",
    "recorder.export",
    "recorder.statistics",
    "status.session_log",
    "status.monitor",
    "persistence",
    "persistence.audit",
    "safety.drive_stop",
})


def validate_entries(entries: tuple[ParityEntry, ...]) -> None:
    """Fail closed on a malformed ledger or an unsupported parity claim."""

    identifiers = tuple(item.feature_id for item in entries)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate feature id in EAS parity ledger")
    missing = REQUIRED_FEATURE_IDS - set(identifiers)
    if missing:
        raise ValueError("missing required feature ids: %s" % sorted(missing))
    invalid = [item.feature_id for item in entries
               if item.verdict not in VERDICTS]
    if invalid:
        raise ValueError("invalid verdicts: %s" % invalid)
    if any(item.can_claim_eas_parity for item in entries):
        raise ValueError("full EAS parity claim is not supported")
    if any(
            item.motion_executed or item.write_executed or item.save_executed
            for item in entries):
        raise ValueError("audit execution boundary was exceeded")

    by_id = {item.feature_id: item for item in entries}
    raw = by_id["single_axis.position.raw_px"]
    display = by_id["single_axis.position.eas_display"]
    if (
            raw.verdict != VALUE_PARITY_OBSERVED
            or raw.eas_value != EAS_TERMINAL_RAW_PX
            or raw.our_value != OUR_RAW_PX):
        raise ValueError("raw PX evidence is inconsistent")
    if (
            display.verdict != VALUE_PARITY_OBSERVED
            or not isinstance(display.eas_value, int)
            or not isinstance(display.our_value, int)
            or display.eas_value != EAS_SINGLE_AXIS_POSITION
            or display.our_value != OUR_EAS_SINGLE_AXIS_POSITION
            or display.our_value - OUR_RAW_PX != 1 << 25):
        raise ValueError("position display evidence is inconsistent")
    current = by_id["single_axis.current"]
    if current.verdict != PARTIAL_LIVE_OBSERVED:
        raise ValueError("EAS Current UI must remain partial and output-locked")


validate_entries(ENTRIES)
ENTRY_BY_ID = MappingProxyType({item.feature_id: item for item in ENTRIES})


def entry(feature_id: str) -> ParityEntry:
    """Return one immutable entry or fail on an unknown feature id."""

    try:
        return ENTRY_BY_ID[str(feature_id)]
    except KeyError as exc:
        raise KeyError("unknown EAS parity feature: %s" % feature_id) from exc
