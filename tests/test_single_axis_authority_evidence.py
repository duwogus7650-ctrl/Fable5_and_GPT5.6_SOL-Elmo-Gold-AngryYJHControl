"""Pure contracts for the Single Axis documented authority map."""

from __future__ import annotations

import builtins
from dataclasses import FrozenInstanceError
import importlib
import socket
import subprocess
import sys

import pytest

import single_axis_authority_evidence as evidence


EXPECTED_SECTION_KEYS = (
    "status_and_io",
    "mode_and_reference",
    "activation_and_tools",
)

EXPECTED_ROW_KEYS = {
    "status_and_io": (
        "motion_status",
        "digital_inputs",
        "digital_outputs",
        "safety_status",
    ),
    "mode_and_reference": (
        "drive_mode",
        "position_velocity",
        "current_reference",
        "sine_homing_stepper",
    ),
    "activation_and_tools": (
        "enable_disable",
        "stop_controls",
        "terminal_command_reference",
        "recorder",
    ),
}


def test_snapshot_is_canonical_frozen_deterministic_and_has_exact_shape():
    first = evidence.build_evidence_snapshot()
    second = evidence.build_evidence_snapshot()

    assert first is second
    assert first.model_id == "single_axis_documented_authority_map_v0_1"
    assert first.authority == "DOCUMENTED_SINGLE_AXIS_AUTHORITY_MAP_ONLY"
    assert first.model_status == "PARTIAL_NEED_DATA"
    assert first.fidelity == "DOCUMENTED_STATIC_REFERENCE"
    assert tuple(section.key for section in first.sections) == (
        EXPECTED_SECTION_KEYS
    )
    assert tuple(len(section.items) for section in first.sections) == (4, 4, 4)

    with pytest.raises(FrozenInstanceError):
        first.authority = "CURRENT_EAS_SINGLE_AXIS"
    with pytest.raises(FrozenInstanceError):
        first.sections[0].items[0].documented_effect = "Live value"


def test_section_and_row_order_is_exact_and_inspect_only():
    snapshot = evidence.build_evidence_snapshot()

    for section_key, expected_keys in EXPECTED_ROW_KEYS.items():
        section = evidence.section_evidence(section_key)
        assert section is next(
            item for item in snapshot.sections if item.key == section_key
        )
        assert tuple(item.key for item in section.items) == expected_keys
        assert all(
            "document: inspect-only" in item.access
            and "app: inspect-only" in item.access
            for item in section.items
        )


def test_documented_controls_preserve_mode_and_mutation_boundaries():
    status = {
        item.key: item
        for item in evidence.section_evidence("status_and_io").items
    }
    modes = {
        item.key: item
        for item in evidence.section_evidence("mode_and_reference").items
    }
    tools = {
        item.key: item
        for item in evidence.section_evidence("activation_and_tools").items
    }

    assert status["motion_status"].label == "Motion Status"
    assert status["digital_inputs"].risk_class == "DRIVE_READ"
    assert status["digital_outputs"].risk_class == "DRIVE_WRITE"
    assert status["safety_status"].risk_class == (
        "DRIVE_READ / SAFETY-RELATED DISPLAY"
    )
    assert modes["drive_mode"].control == (
        "Drive Mode: Position / Velocity / Current / Stepper"
    )
    assert modes["position_velocity"].risk_class == "MOTION"
    assert modes["position_velocity"].evidence_status == (
        "READBACK PARTIAL IMPLEMENTED - COMMAND EXECUTION NEED_DATA")
    assert modes["current_reference"].risk_class == "ENERGIZING"
    assert modes["current_reference"].evidence_status == (
        "READBACK PARTIAL IMPLEMENTED - COMMAND EXECUTION NEED_DATA")
    assert modes["sine_homing_stepper"].risk_class == "MOTION / ENERGIZING"
    assert tools["enable_disable"].risk_class == "ENERGIZING"
    assert tools["stop_controls"].risk_class == "SOFTWARE STOP"
    assert tools["terminal_command_reference"].risk_class == (
        "UNBOUNDED COMMAND SURFACE"
    )
    assert tools["recorder"].risk_class == "DRIVE STATE / ACQUISITION"


def test_boundary_and_capabilities_fail_closed():
    snapshot = evidence.build_evidence_snapshot()
    boundary = snapshot.boundary.upper()

    for phrase in (
        "STATIC DOCUMENT MAP ONLY",
        "DOCUMENTED SINGLE AXIS AUTHORITY MAP",
        "PARTIAL / NEED-DATA",
        "NOT CURRENT EAS SINGLE AXIS STATE",
        "NOT CURRENT DRIVE STATE",
        "NOT STO TEST EVIDENCE",
        "NO DRIVE READ",
        "NO DIGITAL OUTPUT WRITE",
        "NO MODE CHANGE",
        "NO ENABLE/DISABLE",
        "NO PTP/JOG/CURRENT/SINE/HOMING/STEPPER",
        "NO TERMINAL/COMMAND SEND",
        "NO RECORDER CONFIG/ACQUISITION",
        "NO COMMAND GENERATION",
        "NO WRITE/APPLY/SV",
        "NO ENERGIZATION/MOTION",
        "NO DRIVE I/O",
    ):
        assert phrase in boundary

    assert snapshot.can_inspect is True
    for capability in (
        "can_read_drive",
        "can_observe_live_status",
        "can_toggle_outputs",
        "can_change_mode",
        "can_enable",
        "can_command_position_velocity",
        "can_command_current",
        "can_command_sine_homing_stepper",
        "can_send_terminal_commands",
        "can_configure_recorder",
        "can_record",
        "can_generate_commands",
        "can_write",
        "can_apply",
        "can_persist",
        "can_energize",
        "can_move",
        "can_claim_live_state",
        "can_claim_safety",
        "can_claim_eas_parity",
    ):
        assert getattr(snapshot, capability) is False


def test_warnings_and_missing_evidence_cover_runtime_failure_modes():
    snapshot = evidence.build_evidence_snapshot()
    warnings = "\n".join(snapshot.persistent_warnings).upper()
    missing = "\n".join(snapshot.missing_evidence).upper()

    for category in (
        "DOCUMENTED_MAP_ONLY",
        "NO_RUNTIME_IO",
        "STATUS_NOT_LIVE",
        "OUTPUT_IS_MUTATION",
        "SOFTWARE_STOP_NOT_STO",
        "MODE_DEPENDENT",
        "TERMINAL_BYPASS",
        "RECORDER_COUPLING",
    ):
        assert category in warnings
    for category in (
        "TARGET IDENTITY",
        "TELEMETRY FRESHNESS",
        "DIGITAL I/O",
        "MOTION ENVELOPE",
        "INDEPENDENT STOP",
        "COMMAND MAPPING",
        "RECORDER",
        "ROLLBACK / CLOSEOUT",
    ):
        assert category in missing


def test_catalog_contains_no_runtime_or_parity_success_claims():
    snapshot = evidence.build_evidence_snapshot()
    combined = " ".join((
        snapshot.boundary,
        *snapshot.missing_evidence,
        *snapshot.persistent_warnings,
        *(
            value
            for section in snapshot.sections
            for item in section.items
            for value in (
                item.label,
                item.control,
                item.documented_effect,
                item.condition,
                item.access,
                item.risk_class,
                item.evidence_status,
            )
        ),
    )).upper()

    for forbidden in (
        "CURRENT DRIVE SAFE",
        "CURRENT STO TEST PASSED",
        "READY TO ENABLE",
        "READY TO MOVE",
        "EAS PARITY COMPLETE",
        "APP: R/W",
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
        "single_axis_overview_image": (
            "E05313740D16DBF954ED666EA6F56E6359ED4A1AF2D8813BEBF50CF5BEA21F77"
        ),
        "single_axis_areas_image": (
            "C6DEF3392BBC943CE8337CFEB6D353A160AAB23D123C4D2519B4A8972912BAAA"
        ),
    }
    assert all(len(digest) == 64 for digest in sources.values())


def test_fresh_import_build_and_lookup_perform_no_runtime_io(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Single Axis evidence attempted runtime I/O")

    module_name = evidence.__name__
    previous = sys.modules.pop(module_name)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    try:
        fresh = importlib.import_module(module_name)
        snapshot = fresh.build_evidence_snapshot()
        assert snapshot.can_read_drive is False
        assert snapshot.can_enable is False
        assert snapshot.can_move is False
        assert fresh.section_evidence("status_and_io") is snapshot.sections[0]
        assert calls == []
    finally:
        sys.modules[module_name] = previous


@pytest.mark.parametrize(
    "key",
    [None, True, 1, "", "unknown", "STATUS_AND_IO"],
)
def test_section_lookup_rejects_noncanonical_keys(key):
    expected = (
        TypeError
        if not isinstance(key, str) or isinstance(key, bool)
        else KeyError
    )
    with pytest.raises(expected):
        evidence.section_evidence(key)
