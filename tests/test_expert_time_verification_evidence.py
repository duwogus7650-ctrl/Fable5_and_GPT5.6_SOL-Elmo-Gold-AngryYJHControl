"""Pure contracts for the Expert Verification - Time evidence map."""

from __future__ import annotations

import builtins
from dataclasses import FrozenInstanceError
import importlib
import socket
import subprocess
import sys

import pytest

import expert_time_verification_evidence as evidence


EXPECTED_SECTION_KEYS = (
    "current_time",
    "velocity_position_recording",
    "velocity_position_time",
)

EXPECTED_ROW_KEYS = {
    "current_time": (
        "controller_fine_tuning",
        "experiment_type",
        "excitation_type",
        "test_phases",
        "unbalanced_vertical_axis",
        "verify",
        "advanced_current_frequency",
        "advanced_limits_voltage",
    ),
    "velocity_position_recording": (
        "signals",
        "chart_assignment",
        "trigger",
        "slope",
        "source",
        "delay",
        "start_recording",
        "start_ignore_trigger",
    ),
    "velocity_position_time": (
        "indicators_current",
        "enable_status",
        "ptp_absolute_relative",
        "jogging_run_held",
        "motion_profile",
        "sine_step_injection",
        "injection_run_held_start_stop",
        "control_parameters",
    ),
}


def test_snapshot_is_canonical_frozen_deterministic_and_has_exact_shape():
    first = evidence.build_evidence_snapshot()
    second = evidence.build_evidence_snapshot()

    assert first is second
    assert (
        first.model_id
        == "expert_time_verification_documented_map_v0_1"
    )
    assert first.authority == "DOCUMENTED_TIME_VERIFICATION_MAP_ONLY"
    assert first.model_status == "PARTIAL_NEED_DATA"
    assert first.fidelity == "DOCUMENTED_STATIC_REFERENCE"
    assert tuple(section.key for section in first.sections) == (
        EXPECTED_SECTION_KEYS
    )
    assert tuple(len(section.parameters) for section in first.sections) == (
        8,
        8,
        8,
    )
    assert sum(len(section.parameters) for section in first.sections) == 24

    with pytest.raises(FrozenInstanceError):
        first.authority = "CURRENT_EAS_VERIFICATION"
    with pytest.raises(FrozenInstanceError):
        first.sections[0].parameters[0].control = "LIVE CONTROL"


def test_section_and_grouped_row_order_is_exact():
    snapshot = evidence.build_evidence_snapshot()

    for section_key, expected_keys in EXPECTED_ROW_KEYS.items():
        section = evidence.section_evidence(section_key)
        assert section is next(
            item for item in snapshot.sections
            if item.key == section_key
        )
        assert tuple(item.key for item in section.parameters) == expected_keys
        assert len(set(expected_keys)) == len(expected_keys)

    assert all(
        "document: inspect-only" in item.access
        and "app: inspect-only" in item.access
        for section in snapshot.sections
        for item in section.parameters
    )


def test_grouped_controls_preserve_the_documented_time_workflow():
    current = {
        item.key: item
        for item in evidence.section_evidence("current_time").parameters
    }
    recording = {
        item.key: item
        for item in evidence.section_evidence(
            "velocity_position_recording"
        ).parameters
    }
    velocity_position = {
        item.key: item
        for item in evidence.section_evidence(
            "velocity_position_time"
        ).parameters
    }

    assert "KP[1]" in current["controller_fine_tuning"].control
    assert "KI[1]" in current["controller_fine_tuning"].control
    assert "AUTO" in current["experiment_type"].control.upper()
    assert "SINGLE" in current["experiment_type"].control.upper()
    assert "SINE" in current["excitation_type"].control.upper()
    assert "STEP" in current["excitation_type"].control.upper()
    for phase in ("A", "B", "C"):
        assert phase in current["test_phases"].control
    assert current["verify"].control == "Verify"
    assert "HIGH_RISK" in current["verify"].evidence_status
    for token in ("XP[6]", "XP[5]", "US[1]", "US[2]"):
        assert token in current["advanced_limits_voltage"].control

    assert recording["signals"].control == "Signals"
    assert "CHART" in recording["chart_assignment"].control.upper()
    assert recording["trigger"].control == "Trigger"
    assert "START RECORDING" in recording["start_recording"].control.upper()
    assert "IGNORE TRIGGER" in (
        recording["start_ignore_trigger"].control.upper()
    )

    assert "ENABLE" in velocity_position["enable_status"].control.upper()
    indicators = velocity_position["indicators_current"]
    indicator_text = " ".join((
        indicators.label,
        indicators.documented_effect,
        indicators.condition,
        indicators.evidence_status,
    )).upper()
    for token in ("CURRENT", "INPUT", "ON-THE-FLY", "HIGH_RISK"):
        assert token in indicator_text
    assert "PTP" in (
        velocity_position["ptp_absolute_relative"].control.upper()
    )
    assert "JOG" in velocity_position["jogging_run_held"].control.upper()
    assert "SINE" in (
        velocity_position["sine_step_injection"].control.upper()
    )
    assert "STEP" in (
        velocity_position["sine_step_injection"].control.upper()
    )
    for key in (
        "enable_status",
        "ptp_absolute_relative",
        "jogging_run_held",
        "sine_step_injection",
        "injection_run_held_start_stop",
    ):
        assert "HIGH_RISK" in velocity_position[key].evidence_status
    assert "OVERLAP" in (
        velocity_position["control_parameters"].evidence_status
    )
    control_parameter_text = " ".join((
        velocity_position["control_parameters"].documented_effect,
        velocity_position["control_parameters"].condition,
        velocity_position["control_parameters"].evidence_status,
    )).upper()
    for token in (
            "FIELD WEAKENING", "FRICTION", "CURRENT", "TORQUE",
            "WRITE", "HIGH_RISK"):
        assert token in control_parameter_text

    current_verify_text = " ".join((
        current["verify"].documented_effect,
        current["verify"].condition,
    )).upper()
    for token in ("MOTOR", "MOVE", "WARNING"):
        assert token in current_verify_text


def test_boundary_and_capabilities_fail_closed():
    snapshot = evidence.build_evidence_snapshot()
    boundary = snapshot.boundary.upper()

    for phrase in (
        "STATIC DOCUMENT MAP ONLY",
        "DOCUMENTED TIME VERIFICATION MAP",
        "PARTIAL / NEED-DATA",
        "NOT EAS VERIFICATION RESULT",
        "NOT CURRENT DRIVE STATE",
        "NOT RECORDER STATE",
        "NOT MODEL/MEASUREMENT PARITY",
        "NOT A SAFETY ASSESSMENT",
        "NO DRIVE READ",
        "NO RECORDER CONFIGURATION",
        "NO ACQUISITION",
        "NO EVALUATION",
        "NO VERIFY",
        "NO ENABLE/PTP/JOG/SINE/STEP",
        "NO COMMAND/WRITE/APPLY/SV",
        "NO RECORDING",
        "NO ENERGIZATION/MOTION",
        "UI STOP IS NOT STO/E-STOP",
        "NO DRIVE I/O",
    ):
        assert phrase in boundary

    assert snapshot.can_inspect is True
    for capability in (
        "can_read_drive",
        "can_observe_current_state",
        "can_observe_recorder_state",
        "can_validate",
        "can_evaluate",
        "can_acquire",
        "can_configure_recording",
        "can_generate_commands",
        "can_write",
        "can_apply",
        "can_revert",
        "can_run_verification",
        "can_enable_disable",
        "can_energize",
        "can_inject",
        "can_move",
        "can_record",
        "can_stop_hardware",
        "can_persist",
        "can_claim_pass",
        "can_claim_safety",
    ):
        assert getattr(snapshot, capability) is False


def test_conflicts_warnings_and_missing_evidence_keep_required_categories():
    snapshot = evidence.build_evidence_snapshot()
    conflicts = "\n".join(snapshot.document_conflicts).upper()
    warnings = "\n".join(snapshot.persistent_warnings).upper()
    missing = "\n".join(snapshot.missing_evidence).upper()

    assert len(snapshot.document_conflicts) >= 3
    for category in (
        "CONTROLLER_ZERO_INTEGRAL",
        "PWM_PMW",
        "XP5_UNIT",
    ):
        assert category in conflicts

    assert len(snapshot.persistent_warnings) >= 8
    for category in (
        "DOCUMENTED_MAP_ONLY",
        "NO_RUNTIME_IO",
        "CURRENT_TIME_ENERGIZATION_RISK",
        "VELOCITY_POSITION_MOTION_RISK",
        "RECORDER_NOT_MOTION_STOP",
        "UI_STOP_NOT_STO",
        "RUN_HELD_RISK",
        "NO_QUANTITATIVE_PASS_FAIL",
        "OVERLAP_NOT_PARITY",
    ):
        assert category in warnings

    assert len(snapshot.missing_evidence) >= 6
    for category in (
        "TARGET",
        "WAVEFORM",
        "SAFE",
        "RECORDER",
        "ABORT",
        "ACCEPTANCE",
    ):
        assert category in missing


def test_catalog_contains_no_unsafe_or_pass_claims():
    snapshot = evidence.build_evidence_snapshot()
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
        "CURRENT RECORDER IS",
        "MEASURED RESPONSE IS",
        "MODEL MATCHES MEASUREMENT",
        "APP: R/W",
        "READY TO VERIFY",
        "SAFE TO RUN",
        "STOP IS STO",
    ):
        assert forbidden not in combined


def test_source_identity_is_exact_and_complete():
    snapshot_sources = evidence.build_evidence_snapshot().sources
    sources = {source.key: source.sha256 for source in snapshot_sources}

    assert sources == {
        "drive_setup_html": (
            "BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE"
        ),
        "current_time_image": (
            "B2A92460D2499285B63DCD55DF0550DFB74278E0EDD935ECAA670AAA6047A5A6"
        ),
        "current_motor_warning_image": (
            "FC85BAE479514E6B5D5048594968DE0CF149351ABBAEBEE318918F1F86947F91"
        ),
        "current_completion_image": (
            "D7E261C835B0E9D9EFF3BAC80D8AB358392774C396C06E77999675311CDF1F9D"
        ),
        "velocity_position_time_image": (
            "C49250DEB7F13EC586B1238D8702D92DB7598B1BEF084055C7636F1DB6167B7D"
        ),
        "signal_editor_image": (
            "9F696A8B9C62B40421AA9DFC61C3535BD87FA177B7771079DB0855621CE4B810"
        ),
        "trigger_editor_image": (
            "9242467B7925CD65E451A56F5542ED270E1A6B68B89A7FE83AA868EE8C87D289"
        ),
        "sine_step_image": (
            "F17DD9E5D7B38135895AA1468F1D8072BD731846BB7C7479AABF38C04ED46126"
        ),
    }
    assert len(sources) == 8
    assert all(len(digest) == 64 for digest in sources.values())
    suffixes = {
        "drive_setup_html": r"Drive Setup and Motion Activities.htm",
        "current_time_image": r"Drive Setup and Motion Activities_85.png",
        "current_motor_warning_image":
            r"Drive Setup and Motion Activities_77.jpg",
        "current_completion_image":
            r"Drive Setup and Motion Activities_79.jpg",
        "velocity_position_time_image":
            r"Drive Setup and Motion Activities_144.png",
        "signal_editor_image":
            r"Drive Setup and Motion Activities_175.jpg",
        "trigger_editor_image":
            r"Drive Setup and Motion Activities_177.jpg",
        "sine_step_image":
            r"Drive Setup and Motion Activities_182.jpg",
    }
    assert all(
        source.location.endswith(suffixes[source.key])
        for source in snapshot_sources
    )


def test_fresh_module_import_performs_no_file_socket_or_subprocess_io(
        monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("time evidence import attempted runtime I/O")

    module_name = evidence.__name__
    previous = sys.modules.pop(module_name)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    try:
        fresh = importlib.import_module(module_name)
        snapshot = fresh.build_evidence_snapshot()
        assert snapshot.can_read_drive is False
        assert snapshot.can_observe_recorder_state is False
        assert snapshot.can_run_verification is False
        assert snapshot.can_energize is False
        assert snapshot.can_revert is False
        assert snapshot.can_move is False
        assert calls == []
    finally:
        sys.modules[module_name] = previous


def test_snapshot_build_and_lookup_perform_no_runtime_io(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("immutable time evidence lookup attempted I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    snapshot = evidence.build_evidence_snapshot()
    assert evidence.section_evidence("current_time") is snapshot.sections[0]
    assert (
        evidence.section_evidence("velocity_position_recording")
        is snapshot.sections[1]
    )
    assert (
        evidence.section_evidence("velocity_position_time")
        is snapshot.sections[2]
    )
    assert calls == []


@pytest.mark.parametrize(
    "key",
    [None, True, 1, "", "unknown", "CURRENT_TIME"],
)
def test_section_lookup_rejects_noncanonical_keys(key):
    expected = (
        TypeError
        if not isinstance(key, str) or isinstance(key, bool)
        else KeyError
    )
    with pytest.raises(expected):
        evidence.section_evidence(key)
