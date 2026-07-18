"""Immutable documentation evidence for hidden EAS Bode verification pages.

This module is a frozen local catalog.  It does not inspect a drive, sample
telemetry, read or change EAS settings, acquire a response, run Verify, record,
generate commands, energize a motor, or move hardware.  Source identities and
normalized documentation facts are constants so import, build, and lookup
perform no file, process, network, worker, or drive I/O.
"""

from __future__ import annotations

from dataclasses import dataclass


MODEL_ID = "expert_bode_verification_documented_map_v0_1"
BOUNDARY = (
    "STATIC DOCUMENT MAP ONLY · DOCUMENTED BODE VERIFICATION MAP · "
    "PARTIAL / NEED-DATA · NOT EAS VERIFICATION RESULT · "
    "NOT CURRENT DRIVE STATE · NOT EAS SETTING STATE · "
    "NOT MODEL/MEASUREMENT PARITY · NOT A SAFETY ASSESSMENT · "
    "NO DRIVE READ · NO EXPERIMENT · NO ACQUISITION · NO EVALUATION · "
    "NO VERIFY · NO EAS SETTINGS CHANGE · "
    "NO COMMAND/WRITE/APPLY/REVERT/SV · NO RECORDING · "
    "NO ENERGIZATION/MOTION · NO DRIVE I/O"
)


@dataclass(frozen=True, slots=True)
class DocumentSource:
    key: str
    location: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DocumentedBodeControl:
    key: str
    label: str
    control: str
    documented_unit: str
    access: str
    documented_effect: str
    condition: str
    evidence_status: str = "DOCUMENTED"


@dataclass(frozen=True, slots=True)
class DocumentedBodeSection:
    key: str
    label: str
    reference: str
    parameters: tuple[DocumentedBodeControl, ...]


@dataclass(frozen=True, slots=True)
class BodeVerificationSnapshot:
    model_id: str
    authority: str
    model_status: str
    fidelity: str
    boundary: str
    sections: tuple[DocumentedBodeSection, ...]
    document_conflicts: tuple[str, ...]
    persistent_warnings: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    sources: tuple[DocumentSource, ...]
    can_inspect: bool
    can_read_drive: bool
    can_observe_current_state: bool
    can_validate: bool
    can_evaluate: bool
    can_acquire: bool
    can_generate_commands: bool
    can_write: bool
    can_apply: bool
    can_revert: bool
    can_modify_eas_settings: bool
    can_run_verification: bool
    can_record: bool
    can_energize: bool
    can_move: bool
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
        "current_bode_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_87.png",
        "35007B311F9D912975E5B72666E42C5DE20A0F7CC4B942E03DBD16FA69501663",
    ),
    DocumentSource(
        "current_motor_warning_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_77.jpg",
        "FC85BAE479514E6B5D5048594968DE0CF149351ABBAEBEE318918F1F86947F91",
    ),
    DocumentSource(
        "velocity_position_bode_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_145.png",
        "3208706439F318FDBA319E4F883DEE59693155ECD5C6F82ED740136F360D40C6",
    ),
    DocumentSource(
        "velocity_position_motor_warning_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_125.jpg",
        "A2DB9446BF57D19A7C1D20473EBB3BF32C0C91C58C16F4D892EB5D24BC5B2E2A",
    ),
    DocumentSource(
        "settings_html",
        _EAS_UM_ROOT + r"\Settings and Configuration.htm",
        "E5BF9FDEE568B2FB8C58D06F9D0C2F9261A6973A5E081581038F5CFB3843F881",
    ),
    DocumentSource(
        "tuner_verification_settings_image",
        _EAS_IMAGE_ROOT + r"\Settings and Configuration_11.jpg",
        "40CCACC87EA197A46FB6010F129F2F538250CED5217B4BE4A14125FB60CCA6AE",
    ),
)


def _control(
        key: str,
        label: str,
        control: str,
        unit: str,
        effect: str,
        condition: str,
        status: str = "DOCUMENTED",
) -> DocumentedBodeControl:
    return DocumentedBodeControl(
        key=key,
        label=label,
        control=control,
        documented_unit=unit,
        access="document: inspect-only · app: inspect-only",
        documented_effect=effect,
        condition=condition,
        evidence_status=status,
    )


TUNER_SETTINGS = DocumentedBodeSection(
    key="tuner_settings",
    label="Tuner Verification Settings",
    reference="EAS III §13.1.5.6",
    parameters=(
        _control(
            "velocity_slope_time",
            "Velocity Slope Time",
            "Velocity Slope Time",
            "sec",
            "Documented Tuner verification setting; current value, range, "
            "and default are intentionally not sampled.",
            "EAS-local setting; exact minimum, maximum, default, and runtime "
            "use remain NEED-DATA.",
            "NEED_DATA",
        ),
        _control(
            "minimum_amplitude_reduction_factor",
            "Minimum Amplitude Reduction Factor",
            "Minimum Amplitude Reduction Factor",
            "no units",
            "Documented lower amplitude-reduction ratio used by automatic "
            "frequency-dependent experiments; not a current value.",
            "Exact equation, clamping, rounding, and firmware behavior remain "
            "NEED-DATA.",
            "NEED_DATA",
        ),
        _control(
            "minimum_frequency_resolution",
            "Minimum Frequency Resolution",
            "Min Frequency Resolution",
            "Hz",
            "Documented minimum frequency-resolution setting; current value, "
            "range, and default are intentionally not sampled.",
            "Sampling and frequency-grid interaction remain NEED-DATA.",
            "NEED_DATA",
        ),
        _control(
            "minimum_quality_factor_threshold",
            "Minimum Quality Factor Threshold",
            "Min Quality Factor Threshold",
            "no units",
            "Documented quality-factor threshold setting; no acceptance "
            "meaning is inferred.",
            "Exact calculation, range, default, and pass/fail role remain "
            "NEED-DATA.",
            "NEED_DATA",
        ),
        _control(
            "auto_save_experiment_recordings",
            "Automatic Recording Save",
            "Auto Save Experiment Recordings",
            "Boolean",
            "Documents automatic saving of experiment recordings for "
            "frequency points; no file is created by this inspector.",
            "File schema, signals, sampling, completion marker, and source "
            "identity remain NEED-DATA.",
            "DOCUMENTED_NOT_EXECUTABLE",
        ),
        _control(
            "view_verification_bode_pages",
            "Hidden Bode Page Visibility",
            "View Verification – Bode Pages",
            "Boolean",
            "Documents display of both Current and Velocity/Position "
            "Verification – Bode pages, which are hidden by default.",
            "Visibility is not authority, readiness, validation, or a safe "
            "operating condition; this inspector never changes the setting.",
            "DOCUMENTED_NOT_EXECUTABLE",
        ),
        _control(
            "initial_chart_limits",
            "Initial Chart Limits",
            "Initial Chart Limits",
            "dB / deg",
            "Documents four initial chart bounds: magnitude minimum/maximum "
            "and phase minimum/maximum.",
            "Exact ranges, defaults, validation, and current values remain "
            "NEED-DATA.",
            "NEED_DATA",
        ),
        _control(
            "reset_factory_defaults",
            "Reset Tuner Verification Settings",
            "Reset to Factory Defaults",
            "action",
            "Documents an EAS reset action; unavailable and not executable "
            "in this inspector.",
            "EAS-local destructive setting action; factory values, scope, "
            "confirmation, rollback, and persistence remain NEED-DATA.",
            "DOCUMENTED_UNAVAILABLE_ACTION",
        ),
    ),
)


CURRENT_BODE = DocumentedBodeSection(
    key="current_bode",
    label="Current Verification – Bode",
    reference="EAS III §8.2.8.4",
    parameters=(
        _control(
            "experiment_phases",
            "Current Experiment Phase Selection",
            "A / B / C Phases",
            "phase selection",
            "Documents selection of motor phases A, B, and C for the "
            "frequency-domain current experiment.",
            "Selected phases, topology, balance, and current path are not "
            "sampled or validated.",
            "DOCUMENTED_HIGH_RISK_INPUT",
        ),
        _control(
            "current_level",
            "Current Experiment Level",
            "Current Level",
            "% of PL / % of CL (CONFLICT)",
            "The field table documents % of PL with default 40%; the test "
            "procedure and screenshot instead label the control % of CL.",
            "Reference basis is unresolved; no value is read or recommended.",
            "DOCUMENT_CONFLICT",
        ),
        _control(
            "current_level_mode",
            "Current Level Mode",
            "Fixed / Automatic by Frequency",
            "mode",
            "Documents fixed current level or an automatic frequency-"
            "dependent reduction.",
            "Automatic amplitude law, bounds, clamping, and target-firmware "
            "behavior remain NEED-DATA.",
            "NEED_DATA",
        ),
        _control(
            "experiment_frequencies",
            "Current Experiment Frequency Sweep",
            "Experiment Frequencies",
            "Hz / point count",
            "Documents start frequency, end frequency, and Number of Points "
            "for the Bode experiment.",
            "Number of Points is described as position points; exact sampling "
            "grid, ordering, and timing remain NEED-DATA.",
            "DOCUMENT_CONFLICT",
        ),
        _control(
            "current_offset",
            "Current Experiment Offset",
            "Current Offset",
            "prose unspecified / screenshot % of CL",
            "Documents a current offset field, but only the screenshot shows "
            "a % of CL unit.",
            "Unit, allowed range, interaction with phase selection, and safe "
            "bias remain unresolved.",
            "DOCUMENT_CONFLICT",
        ),
        _control(
            "show_design",
            "Current Design Overlay",
            "Show Design",
            "Boolean",
            "Documents display of the designed response over the measured "
            "chart during an actual EAS experiment.",
            "A visual overlay is not a numeric acceptance criterion or "
            "verification result.",
            "DOCUMENTED_NOT_EXECUTABLE",
        ),
        _control(
            "unbalanced_vertical_axis",
            "Current Axis Options",
            "Unbalanced / Vertical Axis",
            "Boolean options",
            "The Current Bode screenshot shows Unbalanced and Vertical Axis "
            "options; the section field table does not define them.",
            "Behavior, interaction, prerequisites, and safety meaning remain "
            "NEED-DATA.",
            "SCREENSHOT_ONLY_NEED_DATA",
        ),
        _control(
            "verify",
            "Run Current Bode Verification",
            "Verify",
            "action",
            "Documents an actual closed-loop frequency-domain current test "
            "that energizes the motor and can make it move, hum, or click.",
            "Unavailable and not executable; no current envelope, acquisition "
            "contract, stop path, closeout, or acceptance oracle is present.",
            "DOCUMENTED_HIGH_RISK_ACTION",
        ),
    ),
)


VELOCITY_POSITION_BODE = DocumentedBodeSection(
    key="velocity_position_bode",
    label="Velocity / Position Verification – Bode",
    reference="EAS III §8.2.13.5",
    parameters=(
        _control(
            "loop_mode",
            "Closed Loop Verification Mode",
            "Loop Mode",
            "mode",
            "Documents Position Closed Loop Bode and Velocity Closed Loop "
            "Bode selections.",
            "Current mode, installed gains, active feedback, and field "
            "readiness are intentionally not sampled.",
            "DOCUMENTED_HIGH_RISK_INPUT",
        ),
        _control(
            "velocity_amplitude",
            "Velocity Experiment Amplitude",
            "Velocity Amplitude",
            "cnt/sec",
            "Documents velocity amplitude and an overview minimum of 1; the "
            "position-mode amplitude meaning is not fully stated.",
            "Allowed range, position-mode interpretation, travel demand, and "
            "safe value remain NEED-DATA.",
            "PARTIAL_NEED_DATA",
        ),
        _control(
            "current_level_mode",
            "Verification Current Mode",
            "Fixed / Automatic by Frequency",
            "mode",
            "Documents fixed current limit or an automatic frequency-"
            "dependent level.",
            "Automatic amplitude law, bounds, clamping, and target-firmware "
            "behavior remain NEED-DATA.",
            "NEED_DATA",
        ),
        _control(
            "current_limit",
            "Verification Current Limit",
            "Current Limit",
            "% of CL",
            "The detailed page documents a Current Limit with default 100%; "
            "that text is reference only, not a current or safe value.",
            "Approved current envelope, thermal limit, and field clamp remain "
            "NEED-DATA.",
            "DOCUMENTED_REFERENCE_NOT_CURRENT",
        ),
        _control(
            "experiment_frequencies",
            "Velocity / Position Experiment Frequency Sweep",
            "Experiment Frequencies",
            "Hz / point count",
            "Documents start frequency, end frequency, and Number of Points "
            "for the selected closed-loop experiment.",
            "Number of Points is described as position points; exact sampling "
            "grid, ordering, and timing remain NEED-DATA.",
            "DOCUMENT_CONFLICT",
        ),
        _control(
            "velocity_offset",
            "Velocity Experiment Offset",
            "Velocity Offset",
            "cnt/sec",
            "Documents a velocity-only offset that forces one direction and "
            "therefore some axis movement.",
            "Direction, available travel, limit behavior, stopping distance, "
            "and safe offset remain NEED-DATA.",
            "DOCUMENTED_HIGH_RISK_INPUT",
        ),
        _control(
            "show_design",
            "Velocity / Position Design Overlay",
            "Show Design",
            "Boolean",
            "Documents display of the designed response over the measured "
            "chart during an actual EAS experiment.",
            "A visual overlay is not a numeric acceptance criterion or "
            "verification result.",
            "DOCUMENTED_NOT_EXECUTABLE",
        ),
        _control(
            "verify",
            "Run Velocity / Position Bode Verification",
            "Verify",
            "action",
            "Documents an actual closed-loop frequency-domain test that can "
            "move the motor and update charts continuously.",
            "Unavailable and not executable; no motion envelope, acquisition "
            "contract, stop path, closeout, or acceptance oracle is present.",
            "DOCUMENTED_HIGH_RISK_ACTION",
        ),
    ),
)


SECTIONS = (TUNER_SETTINGS, CURRENT_BODE, VELOCITY_POSITION_BODE)


DOCUMENT_CONFLICTS = (
    "CURRENT_LEVEL_BASIS_CONFLICT: EAS section 8.2.8.4 defines Current Level "
    "as [% of PL] with a documented default of 40%, while section 8.2.8.4.1 "
    "and the Current Bode screenshot label that same control [% of CL]; the "
    "reference basis is unresolved.",
    "CURRENT_OFFSET_UNIT_CONFLICT: EAS section 8.2.8.4 describes Current "
    "Offset without a unit, while the Current Bode screenshot labels it "
    "[% of CL]; the prose does not establish that screenshot unit.",
    "CURRENT_AXIS_OPTIONS_SCOPE_CONFLICT: The Current Bode screenshot shows "
    "Unbalanced and Vertical Axis options, while the section 8.2.8.4 field "
    "table does not describe either control or its behavior.",
    "POINT_LABEL_CONFLICT: Both Current and Velocity/Position Bode frequency "
    "sweep tables describe Number of Points as the required number of "
    "position points; no mapping from position points to swept-frequency "
    "samples is stated.",
)


PERSISTENT_WARNINGS = (
    "DOCUMENTED_MAP_ONLY: This is a frozen map of installed local EAS "
    "documentation, not a verification result, current EAS configuration, "
    "current drive state, measured plant, model/measurement comparison, or "
    "safety assessment.",
    "HIDDEN_PAGE_VISIBILITY_ONLY: View Verification - Bode Pages only changes "
    "whether two advanced EAS pages are displayed; visibility is not "
    "authorization, readiness, validation, or a safe operating condition.",
    "NO_RUNTIME_IO: Import, snapshot construction, section lookup, and page "
    "navigation must not connect, query, dispatch, read, write, apply, save, "
    "change EAS settings, run Verify, energize, or move hardware.",
    "CURRENT_BODE_ENERGIZATION_RISK: Actual EAS Current Verification - Bode "
    "injects closed-loop current across selected phases and frequencies; the "
    "motor can move, hum, or click and the test requires a separately "
    "authorized guarded procedure.",
    "VELOCITY_POSITION_MOTION_RISK: Actual EAS Velocity/Position Verification "
    "- Bode commands a closed-loop response and can move the axis; amplitude, "
    "offset, travel, load, limits, and stopping controls require independent "
    "bench gates.",
    "MODEL_VS_FIELD_BOUNDARY: The application's offline Bode model preview is "
    "not the EAS measured response, and agreement with a design overlay must "
    "not be represented as field verification.",
    "SHOW_DESIGN_NOT_ACCEPTANCE: Show Design is a visual overlay control; the "
    "documentation supplies no numeric model-to-measurement tolerance, phase "
    "margin gate, stability gate, or pass/fail rule.",
    "NO_QUANTITATIVE_PASS_FAIL: A completed EAS workflow or continuously "
    "updated chart does not by itself prove acceptable tuning, stability, "
    "accuracy, robustness, or safe operation.",
    "AUTOMATIC_AMPLITUDE_UNRESOLVED: Automatic by Frequency is documented as "
    "a logarithmic reduction and the Tuner setting supplies an end/start "
    "ratio, but the exact law, limits, clamping, and firmware behavior are "
    "not established.",
    "OFFSET_DIRECTION_RISK: Current Offset and Velocity Offset can bias the "
    "experiment; velocity offset intentionally forces one direction and can "
    "consume travel even when the plotted excitation appears bounded.",
    "RECORDING_NOT_PROVENANCE: Auto Save Experiment Recordings can save "
    "per-frequency chart recordings, but file identity, signals, sampling, "
    "units, exclusions, completion status, and linkage to a drive revision "
    "remain unverified.",
    "EAS_SETTINGS_MUTATION_EXCLUDED: Tuner Verification values and Reset to "
    "Factory Defaults are EAS-local configuration actions; this inspector "
    "must display documentation only and must never modify or reset them.",
)


MISSING_EVIDENCE = (
    "Exact Gold Twitter orderable part number, hardware revision, firmware "
    "personality, and evidence that the installed EAS documentation matches "
    "the reported 01.01.16.00 08Mar2020B01G target.",
    "Current EAS Tuner Verification values, Bode-page visibility state, "
    "workspace state, selected loop/phase, and current drive values; "
    "intentionally not read.",
    "Exact minimum, maximum, and factory-default values for Velocity Slope "
    "Time, Minimum Amplitude Reduction Factor, Min Frequency Resolution, Min "
    "Quality Factor Threshold, and Initial Chart Limits.",
    "Exact Automatic by Frequency amplitude law, interpolation, rounding, "
    "frequency ordering, current clamping, and interaction with Current "
    "Level/Limit for the target firmware.",
    "Approved experiment current and motion envelope, motor/load inertia, "
    "travel, hard stops, brake state, vertical-axis behavior, thermal margin, "
    "personnel clearance, STO, E-stop, and independent stop path.",
    "Raw EAS verification recordings and metadata including signals, sample "
    "rate, frequency points, units, phase/loop selection, offsets, timestamps, "
    "drive identity, completion state, and file hashes.",
    "Quantitative acceptance criteria and an independent comparison method "
    "for measured versus designed magnitude, phase, margins, resonances, "
    "uncertainty, repeatability, and pass/fail disposition.",
    "Documented and bench-verified abort, timeout, disconnect, fault, "
    "over-travel, stale-telemetry, partial-recording, recovery, and restore "
    "behavior for both Bode experiments.",
)


_SNAPSHOT = BodeVerificationSnapshot(
    model_id=MODEL_ID,
    authority="DOCUMENTED_HIDDEN_BODE_MAP_ONLY",
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
    can_validate=False,
    can_evaluate=False,
    can_acquire=False,
    can_generate_commands=False,
    can_write=False,
    can_apply=False,
    can_revert=False,
    can_modify_eas_settings=False,
    can_run_verification=False,
    can_record=False,
    can_energize=False,
    can_move=False,
    can_stop_hardware=False,
    can_persist=False,
    can_claim_pass=False,
    can_claim_safety=False,
)

_SECTION_BY_KEY = {
    section.key: section
    for section in SECTIONS
}


def build_evidence_snapshot() -> BodeVerificationSnapshot:
    """Return the canonical immutable no-I/O evidence snapshot."""
    return _SNAPSHOT


def section_evidence(key: str) -> DocumentedBodeSection:
    """Return one canonical section without reading any runtime source."""
    if isinstance(key, bool) or not isinstance(key, str):
        raise TypeError("section key must be a string")
    try:
        return _SECTION_BY_KEY[key]
    except KeyError as exc:
        raise KeyError("unknown Bode verification section %r" % key) from exc
