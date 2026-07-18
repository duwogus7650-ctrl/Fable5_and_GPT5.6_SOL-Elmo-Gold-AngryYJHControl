"""Pure contracts for the hidden Expert Verification - Bode evidence map."""

from __future__ import annotations

import builtins
from dataclasses import FrozenInstanceError
import importlib
import socket
import subprocess
import sys

import pytest

import expert_bode_verification_evidence as evidence


EXPECTED_CONFLICTS = (
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


EXPECTED_WARNINGS = (
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


EXPECTED_MISSING = (
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


def test_snapshot_is_canonical_frozen_deterministic_and_has_exact_shape():
    first = evidence.build_evidence_snapshot()
    second = evidence.build_evidence_snapshot()

    assert first is second
    assert first.model_id == "expert_bode_verification_documented_map_v0_1"
    assert first.authority == "DOCUMENTED_HIDDEN_BODE_MAP_ONLY"
    assert first.model_status == "PARTIAL_NEED_DATA"
    assert first.fidelity == "DOCUMENTED_STATIC_REFERENCE"
    assert tuple(section.key for section in first.sections) == (
        "tuner_settings",
        "current_bode",
        "velocity_position_bode",
    )
    assert tuple(len(section.parameters) for section in first.sections) == (
        8,
        8,
        8,
    )
    assert sum(len(section.parameters) for section in first.sections) == 24

    with pytest.raises(FrozenInstanceError):
        first.authority = "CURRENT_EAS_CONFIGURATION"
    with pytest.raises(FrozenInstanceError):
        first.sections[0].parameters[0].control = "LIVE SETTING"


def test_section_and_parameter_order_preserve_documented_hidden_bode_map():
    tuner = evidence.section_evidence("tuner_settings")
    current = evidence.section_evidence("current_bode")
    velocity_position = evidence.section_evidence("velocity_position_bode")

    assert tuple(item.key for item in tuner.parameters) == (
        "velocity_slope_time",
        "minimum_amplitude_reduction_factor",
        "minimum_frequency_resolution",
        "minimum_quality_factor_threshold",
        "auto_save_experiment_recordings",
        "view_verification_bode_pages",
        "initial_chart_limits",
        "reset_factory_defaults",
    )
    assert tuple(item.control for item in tuner.parameters) == (
        "Velocity Slope Time",
        "Minimum Amplitude Reduction Factor",
        "Min Frequency Resolution",
        "Min Quality Factor Threshold",
        "Auto Save Experiment Recordings",
        "View Verification – Bode Pages",
        "Initial Chart Limits",
        "Reset to Factory Defaults",
    )

    assert tuple(item.key for item in current.parameters) == (
        "experiment_phases",
        "current_level",
        "current_level_mode",
        "experiment_frequencies",
        "current_offset",
        "show_design",
        "unbalanced_vertical_axis",
        "verify",
    )
    assert tuple(item.control for item in current.parameters) == (
        "A / B / C Phases",
        "Current Level",
        "Fixed / Automatic by Frequency",
        "Experiment Frequencies",
        "Current Offset",
        "Show Design",
        "Unbalanced / Vertical Axis",
        "Verify",
    )

    assert tuple(item.key for item in velocity_position.parameters) == (
        "loop_mode",
        "velocity_amplitude",
        "current_level_mode",
        "current_limit",
        "experiment_frequencies",
        "velocity_offset",
        "show_design",
        "verify",
    )
    assert tuple(item.control for item in velocity_position.parameters) == (
        "Loop Mode",
        "Velocity Amplitude",
        "Fixed / Automatic by Frequency",
        "Current Limit",
        "Experiment Frequencies",
        "Velocity Offset",
        "Show Design",
        "Verify",
    )

    assert all(
        "document: inspect-only" in item.access
        and "app: inspect-only" in item.access
        for section in evidence.build_evidence_snapshot().sections
        for item in section.parameters
    )


def test_documented_units_defaults_and_high_risk_controls_are_not_normalized():
    tuner = {
        item.key: item
        for item in evidence.section_evidence("tuner_settings").parameters
    }
    current = {
        item.key: item
        for item in evidence.section_evidence("current_bode").parameters
    }
    velocity_position = {
        item.key: item
        for item in evidence.section_evidence(
            "velocity_position_bode"
        ).parameters
    }

    assert tuner["velocity_slope_time"].documented_unit == "sec"
    assert (
        tuner["minimum_amplitude_reduction_factor"].documented_unit
        == "no units"
    )
    assert tuner["minimum_frequency_resolution"].documented_unit == "Hz"
    assert "four" in tuner["initial_chart_limits"].documented_effect.lower()
    assert "EAS-local" in tuner["reset_factory_defaults"].condition

    assert current["current_level"].documented_unit == (
        "% of PL / % of CL (CONFLICT)")
    assert "40%" in current["current_level"].documented_effect
    assert current["current_offset"].evidence_status == "DOCUMENT_CONFLICT"
    assert (
        current["unbalanced_vertical_axis"].evidence_status
        == "SCREENSHOT_ONLY_NEED_DATA"
    )
    assert current["verify"].evidence_status == "DOCUMENTED_HIGH_RISK_ACTION"
    assert "actual" in current["verify"].documented_effect.lower()

    assert (
        velocity_position["velocity_amplitude"].documented_unit
        == "cnt/sec"
    )
    assert velocity_position["current_limit"].documented_unit == "% of CL"
    assert "100%" in (
        velocity_position["current_limit"].documented_effect
    )
    assert "direction" in (
        velocity_position["velocity_offset"].condition.lower()
    )
    assert (
        velocity_position["verify"].evidence_status
        == "DOCUMENTED_HIGH_RISK_ACTION"
    )


def test_boundary_and_capabilities_fail_closed():
    snapshot = evidence.build_evidence_snapshot()
    boundary = snapshot.boundary.upper()

    for phrase in (
        "STATIC DOCUMENT MAP ONLY",
        "PARTIAL / NEED-DATA",
        "NOT EAS VERIFICATION RESULT",
        "NOT CURRENT DRIVE STATE",
        "NOT EAS SETTING STATE",
        "NOT MODEL/MEASUREMENT PARITY",
        "NOT A SAFETY ASSESSMENT",
        "NO DRIVE READ",
        "NO EXPERIMENT",
        "NO ACQUISITION",
        "NO EVALUATION",
        "NO VERIFY",
        "NO EAS SETTINGS CHANGE",
        "NO COMMAND/WRITE/APPLY/REVERT/SV",
        "NO RECORDING",
        "NO ENERGIZATION/MOTION",
        "NO DRIVE I/O",
    ):
        assert phrase in boundary

    assert snapshot.can_inspect is True
    for capability in (
        "can_read_drive",
        "can_observe_current_state",
        "can_validate",
        "can_evaluate",
        "can_acquire",
        "can_generate_commands",
        "can_write",
        "can_apply",
        "can_revert",
        "can_modify_eas_settings",
        "can_run_verification",
        "can_record",
        "can_energize",
        "can_move",
        "can_stop_hardware",
        "can_persist",
        "can_claim_pass",
        "can_claim_safety",
    ):
        assert getattr(snapshot, capability) is False


def test_conflicts_warnings_and_missing_evidence_are_exact():
    snapshot = evidence.build_evidence_snapshot()

    assert snapshot.document_conflicts == EXPECTED_CONFLICTS
    assert snapshot.persistent_warnings == EXPECTED_WARNINGS
    assert snapshot.missing_evidence == EXPECTED_MISSING
    assert len(snapshot.document_conflicts) == 4
    assert len(snapshot.persistent_warnings) == 12
    assert len(snapshot.missing_evidence) == 8

    combined = " ".join((
        snapshot.boundary,
        *snapshot.document_conflicts,
        *snapshot.missing_evidence,
        *snapshot.persistent_warnings,
        *(
            value
            for section in snapshot.sections
            for item in section.parameters
            for value in (
                item.label,
                item.control,
                item.documented_unit,
                item.access,
                item.documented_effect,
                item.condition,
                item.evidence_status,
            )
        ),
    )).upper()
    for forbidden in (
        "VERIFICATION PASSED",
        "VALIDATED SAFE",
        "CURRENT DRIVE IS",
        "CURRENT EAS SETTING IS",
        "MEASURED RESPONSE IS",
        "MODEL MATCHES MEASUREMENT",
        "APP: R/W",
        "READY TO VERIFY",
        "SAFE TO RUN",
    ):
        assert forbidden not in combined


def test_source_identity_is_exact_and_complete():
    sources = {
        source.key: source.sha256
        for source in evidence.build_evidence_snapshot().sources
    }

    assert sources == {
        "drive_setup_html": (
            "BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE"
        ),
        "settings_html": (
            "E5BF9FDEE568B2FB8C58D06F9D0C2F9261A6973A5E081581038F5CFB3843F881"
        ),
        "current_bode_image": (
            "35007B311F9D912975E5B72666E42C5DE20A0F7CC4B942E03DBD16FA69501663"
        ),
        "current_motor_warning_image": (
            "FC85BAE479514E6B5D5048594968DE0CF149351ABBAEBEE318918F1F86947F91"
        ),
        "velocity_position_bode_image": (
            "3208706439F318FDBA319E4F883DEE59693155ECD5C6F82ED740136F360D40C6"
        ),
        "velocity_position_motor_warning_image": (
            "A2DB9446BF57D19A7C1D20473EBB3BF32C0C91C58C16F4D892EB5D24BC5B2E2A"
        ),
        "tuner_verification_settings_image": (
            "40CCACC87EA197A46FB6010F129F2F538250CED5217B4BE4A14125FB60CCA6AE"
        ),
    }
    assert len(sources) == 7
    assert all(len(digest) == 64 for digest in sources.values())


def test_fresh_module_import_performs_no_application_or_drive_io(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Bode evidence import attempted runtime I/O")

    module_name = evidence.__name__
    previous = sys.modules.pop(module_name)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    try:
        fresh = importlib.import_module(module_name)
        snapshot = fresh.build_evidence_snapshot()
        assert snapshot.can_read_drive is False
        assert snapshot.can_run_verification is False
        assert snapshot.can_energize is False
        assert calls == []
    finally:
        sys.modules[module_name] = previous


def test_snapshot_build_and_lookup_perform_no_runtime_io(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("immutable Bode evidence lookup attempted I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    snapshot = evidence.build_evidence_snapshot()
    assert evidence.section_evidence("tuner_settings") is snapshot.sections[0]
    assert evidence.section_evidence("current_bode") is snapshot.sections[1]
    assert (
        evidence.section_evidence("velocity_position_bode")
        is snapshot.sections[2]
    )
    assert calls == []


@pytest.mark.parametrize("key", [None, True, 1, "", "unknown", "CURRENT_BODE"])
def test_section_lookup_rejects_noncanonical_keys(key):
    expected = (
        TypeError
        if not isinstance(key, str) or isinstance(key, bool)
        else KeyError
    )
    with pytest.raises(expected):
        evidence.section_evidence(key)
