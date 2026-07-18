"""Immutable documentation evidence for EAS Expert Verification - Time.

This module is a frozen local catalog.  It does not inspect a drive or
recorder, configure a recording, acquire a response, run Verify, enable a
motor, start PTP/Jog/Sine/Step activity, generate commands, or move hardware.
All source identities and normalized documentation facts are constants, so
import, build, and lookup perform no file, process, network, worker, recorder,
or drive I/O.
"""

from __future__ import annotations

from dataclasses import dataclass


MODEL_ID = "expert_time_verification_documented_map_v0_1"
BOUNDARY = (
    "STATIC DOCUMENT MAP ONLY · DOCUMENTED TIME VERIFICATION MAP · "
    "PARTIAL / NEED-DATA · NOT EAS VERIFICATION RESULT · "
    "NOT CURRENT DRIVE STATE · NOT RECORDER STATE · "
    "NOT MODEL/MEASUREMENT PARITY · NOT A SAFETY ASSESSMENT · "
    "NO DRIVE READ · NO RECORDER CONFIGURATION · NO ACQUISITION · "
    "NO EVALUATION · NO VERIFY · NO ENABLE/PTP/JOG/SINE/STEP · "
    "NO COMMAND/WRITE/APPLY/SV · NO RECORDING · "
    "NO ENERGIZATION/MOTION · UI STOP IS NOT STO/E-STOP · NO DRIVE I/O"
)


@dataclass(frozen=True, slots=True)
class DocumentSource:
    key: str
    location: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DocumentedTimeControl:
    key: str
    label: str
    control: str
    display_group: str
    documented_unit: str
    access: str
    documented_effect: str
    condition: str
    evidence_status: str = "DOCUMENTED"


@dataclass(frozen=True, slots=True)
class DocumentedTimeSection:
    key: str
    label: str
    reference: str
    parameters: tuple[DocumentedTimeControl, ...]


@dataclass(frozen=True, slots=True)
class TimeVerificationSnapshot:
    model_id: str
    authority: str
    model_status: str
    fidelity: str
    boundary: str
    sections: tuple[DocumentedTimeSection, ...]
    document_conflicts: tuple[str, ...]
    persistent_warnings: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    sources: tuple[DocumentSource, ...]
    can_inspect: bool
    can_read_drive: bool
    can_observe_current_state: bool
    can_observe_recorder_state: bool
    can_validate: bool
    can_evaluate: bool
    can_acquire: bool
    can_configure_recording: bool
    can_generate_commands: bool
    can_write: bool
    can_apply: bool
    can_revert: bool
    can_run_verification: bool
    can_enable_disable: bool
    can_energize: bool
    can_inject: bool
    can_move: bool
    can_record: bool
    can_stop_hardware: bool
    can_persist: bool
    can_claim_pass: bool
    can_claim_safety: bool


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
        "current_time_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_85.png",
        "B2A92460D2499285B63DCD55DF0550DFB74278E0EDD935ECAA670AAA6047A5A6",
    ),
    DocumentSource(
        "current_motor_warning_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_77.jpg",
        "FC85BAE479514E6B5D5048594968DE0CF149351ABBAEBEE318918F1F86947F91",
    ),
    DocumentSource(
        "current_completion_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_79.jpg",
        "D7E261C835B0E9D9EFF3BAC80D8AB358392774C396C06E77999675311CDF1F9D",
    ),
    DocumentSource(
        "velocity_position_time_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_144.png",
        "C49250DEB7F13EC586B1238D8702D92DB7598B1BEF084055C7636F1DB6167B7D",
    ),
    DocumentSource(
        "signal_editor_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_175.jpg",
        "9F696A8B9C62B40421AA9DFC61C3535BD87FA177B7771079DB0855621CE4B810",
    ),
    DocumentSource(
        "trigger_editor_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_177.jpg",
        "9242467B7925CD65E451A56F5542ED270E1A6B68B89A7FE83AA868EE8C87D289",
    ),
    DocumentSource(
        "sine_step_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_182.jpg",
        "F17DD9E5D7B38135895AA1468F1D8072BD731846BB7C7479AABF38C04ED46126",
    ),
)

_DISPLAY_GROUP_BY_KEY = {
    "controller_fine_tuning": "Controller KP[1] / KI[1]",
    "experiment_type": "Experiment Type · Auto / Single",
    "excitation_type": "Excitation Type · Step / Sine",
    "test_phases": "Test in Phases · A / B / C",
    "unbalanced_vertical_axis": "Unbalanced / Vertical Axis",
    "verify": "Verify",
    "advanced_current_frequency": "Advanced Current Range / Frequency",
    "advanced_limits_voltage":
        "XP[6] / XP[5] / US[1] / US[2] / Show Phase Voltage",
    "signals": "Recorder Signals",
    "chart_assignment": "Chart Assignment",
    "trigger": "Trigger Editor",
    "slope": "Trigger Slope",
    "source": "Trigger Source",
    "delay": "Trigger Delay",
    "start_recording": "Start Recording",
    "start_ignore_trigger": "Start Ignore Trigger",
    "indicators_current": "Position / Velocity / Current",
    "enable_status": "Enable / Disable + Status",
    "ptp_absolute_relative": "PTP Absolute / Relative",
    "jogging_run_held": "Jogging + Run Held",
    "motion_profile": "Acc / Dec / Stop Dec / Smooth / Speed / Dwell",
    "sine_step_injection": "Sine / Step Injection",
    "injection_run_held_start_stop":
        "Injection Run Held + Start / Stop",
    "control_parameters": "Control Parameters",
}


def _control(
        key: str,
        label: str,
        control: str,
        unit: str,
        effect: str,
        condition: str,
        status: str = "DOCUMENTED",
) -> DocumentedTimeControl:
    return DocumentedTimeControl(
        key=key,
        label=label,
        control=control,
        display_group=_DISPLAY_GROUP_BY_KEY[key],
        documented_unit=unit,
        access="document: inspect-only · app: inspect-only",
        documented_effect=effect,
        condition=condition,
        evidence_status=status,
    )


CURRENT_TIME = DocumentedTimeSection(
    key="current_time",
    label="Current Verification - Time",
    reference="EAS III §8.2.8.3",
    parameters=(
        _control(
            "controller_fine_tuning",
            "Current Controller Fine Tuning",
            "Controller Gain KP[1] / Controller Integral KI[1]",
            "V/A / Hz",
            "Documents the KP[1] gain and KI[1] frequency controls shown on "
            "the Current Verification - Time page.",
            "The prose calls KI[1] Controller Zero while the screenshot calls "
            "it Controller Integral; no value is sampled or recommended.",
            "DOCUMENT_CONFLICT",
        ),
        _control(
            "experiment_type",
            "Current Response Experiment Type",
            "Auto / Single",
            "mode",
            "Documents automatic and single current-response experiment "
            "choices.",
            "Exact repetition, phase ordering, timing, and termination "
            "semantics remain NEED-DATA.",
            "NEED_DATA",
        ),
        _control(
            "excitation_type",
            "Current Response Excitation Type",
            "Sine / Step",
            "waveform mode",
            "Documents sine and step excitation choices for the current "
            "response test.",
            "Exact waveform, amplitude, offset, rise time, duration, and "
            "spectral content remain NEED-DATA.",
            "DOCUMENTED_HIGH_RISK_INPUT",
        ),
        _control(
            "test_phases",
            "Current Experiment Phase Selection",
            "A / B / C Phases",
            "phase selection",
            "Documents selection of motor phases A, B, and C for the "
            "current-response experiment.",
            "Selected phases, topology, current path, and test order are not "
            "sampled or validated.",
            "DOCUMENTED_HIGH_RISK_INPUT",
        ),
        _control(
            "unbalanced_vertical_axis",
            "Unbalanced or Vertical Axis Option",
            "Unbalanced / Vertical Axis",
            "Boolean",
            "Documents an option for brake-equipped or vertically hanging "
            "axes where commutation considers free-fall.",
            "Brake state, load holding, gravity direction, travel, and safe "
            "behavior remain NEED-DATA.",
            "DOCUMENTED_HIGH_RISK_INPUT",
        ),
        _control(
            "verify",
            "Run Current Verification - Time",
            "Verify",
            "action",
            "Documents an actual current-response experiment that requires "
            "the motor to be on, can move or twitch the motor, and records "
            "phase response data.",
            "Unavailable and not executable; EAS displays a motor-movement "
            "warning, while the excitation envelope, recorder contract, "
            "abort path, closeout, and acceptance oracle are absent.",
            "DOCUMENTED_HIGH_RISK_ACTION",
        ),
        _control(
            "advanced_current_frequency",
            "Advanced Current and Frequency Controls",
            "Minimum / Maximum Current + Frequency",
            "A / Hz",
            "Documents minimum current, maximum current, and frequency fields "
            "in the Advanced area.",
            "Exact ranges, defaults, waveform interaction, clamps, and target-"
            "firmware behavior remain NEED-DATA.",
            "NEED_DATA",
        ),
        _control(
            "advanced_limits_voltage",
            "Advanced Limits and Phase Voltage",
            "XP[6] / XP[5] / US[1] / US[2] / Show Phase Voltage",
            "Hz / % of MC/TS / % PWM",
            "Documents pre-filter cutoff, slope limit, PWM output limit, "
            "integral limit, and phase-voltage display controls.",
            "XP[5] unit punctuation and PMW/PWM naming conflict in the prose; "
            "current values and drive effects are intentionally not read.",
            "DOCUMENT_CONFLICT",
        ),
    ),
)


VELOCITY_POSITION_RECORDING = DocumentedTimeSection(
    key="velocity_position_recording",
    label="Velocity / Position Recording Setup",
    reference="EAS III §8.2.13.4 Recorder procedure",
    parameters=(
        _control(
            "signals",
            "Open Recorder Signal Editor",
            "Signals",
            "action",
            "Documents opening the EAS Signal Editor from the Recording "
            "ribbon.",
            "Unavailable and not executable; this catalog does not open or "
            "configure the existing application Recorder.",
            "DOCUMENTED_UNAVAILABLE_ACTION",
        ),
        _control(
            "chart_assignment",
            "Assign Signals to Charts",
            "Chart Signal Assignment",
            "signal-to-chart mapping",
            "Documents assigning one or more signals to each verification "
            "chart.",
            "Signal identity, units, sampling, ordering, and chart persistence "
            "remain NEED-DATA.",
            "DOCUMENTED_OVERLAP_NOT_EXECUTABLE",
        ),
        _control(
            "trigger",
            "Open Recorder Trigger Editor",
            "Trigger",
            "action",
            "Documents opening the EAS Trigger Editor from the Recording "
            "ribbon.",
            "Unavailable and not executable; no trigger configuration is "
            "created by this catalog.",
            "DOCUMENTED_UNAVAILABLE_ACTION",
        ),
        _control(
            "slope",
            "Recorder Trigger Slope",
            "Slope",
            "Rising / Falling / Out of Window",
            "Documents the trigger slope choices shown by EAS.",
            "Edge polarity, thresholds, hysteresis, and target behavior "
            "remain NEED-DATA.",
            "NEED_DATA",
        ),
        _control(
            "source",
            "Recorder Trigger Source",
            "Source",
            "signal selection",
            "Documents selecting a trigger source such as Begin Motion.",
            "Exact source availability and firmware signal mapping remain "
            "NEED-DATA.",
            "NEED_DATA",
        ),
        _control(
            "delay",
            "Recorder Trigger Delay",
            "Delay",
            "percent",
            "Documents selection of a trigger delay percentage.",
            "Buffer reference, quantization, valid range, and timing accuracy "
            "remain NEED-DATA.",
            "NEED_DATA",
        ),
        _control(
            "start_recording",
            "Start Triggered Recorder Capture",
            "Start Recording",
            "action",
            "Documents starting EAS recording with the configured trigger.",
            "Unavailable and not executable; recording does not authorize "
            "motion and does not provide a hardware stop.",
            "DOCUMENTED_HIGH_RISK_ACTION",
        ),
        _control(
            "start_ignore_trigger",
            "Start Recorder Capture Without Trigger",
            "Start Ignore Trigger",
            "action",
            "Documents starting EAS recording while ignoring the configured "
            "trigger.",
            "Unavailable and not executable; pre-trigger meaning, timing, "
            "ownership, and closeout remain NEED-DATA.",
            "DOCUMENTED_HIGH_RISK_ACTION",
        ),
    ),
)


VELOCITY_POSITION_TIME = DocumentedTimeSection(
    key="velocity_position_time",
    label="Velocity / Position Verification - Time",
    reference="EAS III §8.2.13.4.1–8.2.13.4.3",
    parameters=(
        _control(
            "indicators_current",
            "Motion Indicators and Editable Current Input",
            "Position / Velocity / Current",
            "cnt or user units / cnt/sec / A",
            "Documents actual-position and velocity indicators plus a Current "
            "input that EAS says may be changed on-the-fly during PTP or Jog.",
            "Unavailable and not executable; this catalog neither observes "
            "telemetry nor writes the motion-current input. CL limits are not "
            "treated as a verified safe envelope.",
            "DOCUMENTED_HIGH_RISK_INPUT_NOT_CURRENT",
        ),
        _control(
            "enable_status",
            "Motor Activation and Motion Status",
            "Enable / Disable + Status",
            "drive state",
            "Documents the motor activation control and displayed motion/error "
            "status.",
            "Unavailable and not executable; displayed status is not an "
            "independent safe-state or torque-isolation proof.",
            "DOCUMENTED_HIGH_RISK_ACTION",
        ),
        _control(
            "ptp_absolute_relative",
            "Profiler Point-to-Point Motion",
            "PTP Absolute / Relative",
            "cnt or user units",
            "Documents absolute and relative profiler targets, repetitive "
            "selection, and motion buttons.",
            "Cross-reference only; no target, travel, limit, direction, "
            "watchdog, or motion command is produced.",
            "DOCUMENTED_HIGH_RISK_OVERLAP",
        ),
        _control(
            "jogging_run_held",
            "Profiler Jogging",
            "Jogging + Run Held",
            "direction / hold behavior",
            "Documents Jog-/Jog+ and Run Held behavior.",
            "Cross-reference only; button release, application focus loss, "
            "disconnect, and stop behavior require independent gates.",
            "DOCUMENTED_HIGH_RISK_OVERLAP",
        ),
        _control(
            "motion_profile",
            "Profiler Motion Parameters",
            "Acc / Dec / Stop Dec / Smooth / Speed / Dwell",
            "cnt/sec² / msec / cnt/sec / percent",
            "Documents grouped profiler acceleration, deceleration, stop "
            "deceleration, smoothing, speed, and dwell controls.",
            "Cross-reference only; units, limits, on-the-fly updates, and "
            "drive mappings are not validated.",
            "DOCUMENTED_OVERLAP_NOT_EXECUTABLE",
        ),
        _control(
            "sine_step_injection",
            "Velocity / Position Wave Injection",
            "Sine / Step Injection",
            "injection point / Hz / cnt / waveform",
            "Documents injection point, frequency, amplitude, and Sine/Step "
            "waveform controls.",
            "Unavailable and not executable; exact waveform, target loop, "
            "travel demand, current demand, and bounds remain NEED-DATA.",
            "DOCUMENTED_HIGH_RISK_ACTION",
        ),
        _control(
            "injection_run_held_start_stop",
            "Wave Injection Lifecycle",
            "Injection Run Held + Start / Stop",
            "hold / action",
            "Documents Run Held and Start/Stop controls for Sine/Step "
            "injection.",
            "Unavailable and not executable; the UI Stop control is not STO, "
            "an E-stop, or an independent hardware stop.",
            "DOCUMENTED_HIGH_RISK_ACTION",
        ),
        _control(
            "control_parameters",
            "Displayed Controller and Compensation Parameters",
            "Control Parameters (Scheduling / Gains / Filters / Compensation)",
            "mixed documented units",
            "Documents controller tuning, scheduling, gains, feedforward, "
            "advanced filters, phase advance, field weakening, and friction "
            "compensation groups, including settings that can alter current "
            "and torque behavior.",
            "High-risk write boundary: field weakening and friction "
            "compensation can affect current, torque, and motion. This is a "
            "cross-reference only, not parity with the local P2 MODEL or "
            "filter/scheduling evidence, and exposes no edits.",
            "DOCUMENTED_HIGH_RISK_OVERLAP_NOT_EXECUTABLE",
        ),
    ),
)


SECTIONS = (
    CURRENT_TIME,
    VELOCITY_POSITION_RECORDING,
    VELOCITY_POSITION_TIME,
)


DOCUMENT_CONFLICTS = (
    "CONTROLLER_ZERO_INTEGRAL_LABEL_CONFLICT: EAS section 8.2.8.3 calls "
    "KI[1] Controller Zero while the page screenshot calls it Controller "
    "Integral; this catalog preserves both labels without choosing one.",
    "PWM_PMW_LABEL_CONFLICT: The Current Verification - Time prose labels "
    "US[1] as PMW Output Limit while describing PWM duty-cycle limiting; "
    "PMW is treated as an unresolved documentation typo.",
    "XP5_UNIT_SYNTAX_CONFLICT: The documented Slope Limit XP[5] unit is "
    "rendered [% of MC/TS]] with an extra closing bracket; its exact "
    "normalization is not inferred.",
)


PERSISTENT_WARNINGS = (
    "DOCUMENTED_MAP_ONLY: This frozen catalog is not an EAS verification "
    "result, current drive or recorder state, measured response, controller "
    "recommendation, model/measurement comparison, or safety assessment.",
    "NO_RUNTIME_IO: Import, snapshot construction, lookup, and page "
    "navigation must not connect, read, query, dispatch, configure a "
    "recorder, acquire, Verify, enable, inject, move, write, Apply, or save.",
    "CURRENT_TIME_ENERGIZATION_RISK: Actual EAS Current Verification - Time "
    "requires the motor to be on and applies Sine/Step current-response "
    "experiments; EAS displays a motor-movement warning and the motor can "
    "move or twitch. It requires a separately authorized guarded procedure.",
    "VELOCITY_POSITION_MOTION_RISK: Actual EAS Velocity/Position "
    "Verification - Time exposes Enable, PTP, Jog, and Sine/Step injection "
    "controls that can move the axis.",
    "RECORDER_NOT_MOTION_STOP: Starting, stopping, or completing a recording "
    "controls data capture; it must not be interpreted as stopping motor "
    "torque or motion.",
    "UI_STOP_NOT_STO: The Verification-Time UI Stop control is not STO, an "
    "E-stop, contactor isolation, or evidence of torque removal.",
    "RUN_HELD_RISK: Run Held depends on user-interface input and documented "
    "Stop behavior; release, focus loss, disconnect, timeout, and stale "
    "command handling require independent validation.",
    "NO_QUANTITATIVE_PASS_FAIL: A completed progress dialog or continuously "
    "updated chart does not establish tuning quality, stability, robustness, "
    "accuracy, repeatability, or safe operation.",
    "OVERLAP_NOT_PARITY: Recorder, profiler, P2, and filter/scheduling rows "
    "are documentation cross-references only; they do not reproduce, invoke, "
    "or validate the existing application tools.",
)


MISSING_EVIDENCE = (
    "TARGET PARITY: Exact Gold Twitter orderable part number, hardware "
    "revision, firmware personality, and evidence that installed EAS "
    "documentation matches the reported B01G target.",
    "EXCITATION WAVEFORM: Exact Sine/Step amplitude, offset, frequency, rise "
    "time, duration, repetition, phase order, saturation, and drive mapping.",
    "SAFE ENVELOPE: Approved current, thermal, travel, velocity, acceleration, "
    "load, brake, vertical-axis, limit, stopping-distance, STO, and E-stop "
    "conditions.",
    "RECORDER PROVENANCE: Exact signals, units, sampling rate, resolution, "
    "buffer mode, trigger semantics, timestamps, target identity, completion "
    "state, raw data, and file hashes.",
    "ABORT AND RECOVERY: Verified timeout, cancel, disconnect, fault, "
    "over-travel, focus-loss, partial-recording, closeout, and restore "
    "behavior for both experiment families.",
    "ACCEPTANCE CRITERIA: Quantitative response metrics, tolerances, "
    "uncertainty, repeatability, model comparison, stability gate, and an "
    "independent pass/fail oracle.",
)


_SNAPSHOT = TimeVerificationSnapshot(
    model_id=MODEL_ID,
    authority="DOCUMENTED_TIME_VERIFICATION_MAP_ONLY",
    model_status="PARTIAL_NEED_DATA",
    fidelity="DOCUMENTED_STATIC_REFERENCE",
    boundary=BOUNDARY,
    sections=SECTIONS,
    document_conflicts=DOCUMENT_CONFLICTS,
    persistent_warnings=PERSISTENT_WARNINGS,
    missing_evidence=MISSING_EVIDENCE,
    sources=SOURCES,
    can_inspect=True,
    can_read_drive=False,
    can_observe_current_state=False,
    can_observe_recorder_state=False,
    can_validate=False,
    can_evaluate=False,
    can_acquire=False,
    can_configure_recording=False,
    can_generate_commands=False,
    can_write=False,
    can_apply=False,
    can_revert=False,
    can_run_verification=False,
    can_enable_disable=False,
    can_energize=False,
    can_inject=False,
    can_move=False,
    can_record=False,
    can_stop_hardware=False,
    can_persist=False,
    can_claim_pass=False,
    can_claim_safety=False,
)

_SECTION_BY_KEY = {
    section.key: section
    for section in SECTIONS
}


def build_evidence_snapshot() -> TimeVerificationSnapshot:
    """Return the canonical immutable no-I/O evidence snapshot."""
    return _SNAPSHOT


def section_evidence(key: str) -> DocumentedTimeSection:
    """Return one canonical section without reading any runtime source."""
    if isinstance(key, bool) or not isinstance(key, str):
        raise TypeError("section key must be a string")
    try:
        return _SECTION_BY_KEY[key]
    except KeyError as exc:
        raise KeyError(
            "unknown time verification section %r" % key
        ) from exc
