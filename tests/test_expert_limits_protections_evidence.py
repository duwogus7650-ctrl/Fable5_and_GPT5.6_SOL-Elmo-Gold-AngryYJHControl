"""Pure contracts for the Expert Limits / Protections evidence inspector."""

from __future__ import annotations

import builtins
from dataclasses import FrozenInstanceError
import hashlib
import importlib
import socket
import subprocess
import sys

import pytest

import expert_limits_protections_evidence as evidence


def test_snapshot_is_canonical_frozen_and_deterministic():
    first = evidence.build_evidence_snapshot()
    second = evidence.build_evidence_snapshot()

    assert first is second
    assert first.authority == "DOCUMENTED_PARAMETER_MAP_ONLY"
    assert first.model_status == "PARTIAL_NEED_DATA"
    assert tuple(section.key for section in first.sections) == (
        "current_limits",
        "motion_limits",
        "protections",
    )
    with pytest.raises(FrozenInstanceError):
        first.authority = "CURRENT_DRIVE_CONFIG"
    with pytest.raises(FrozenInstanceError):
        first.sections[0].parameters[0].command = "PL[999]"


def test_section_parameter_order_and_asymmetric_semantics_are_preserved():
    current = evidence.section_evidence("current_limits")
    motion = evidence.section_evidence("motion_limits")
    protections = evidence.section_evidence("protections")

    assert tuple(item.command for item in current.parameters) == (
        "MC",
        "BV",
        "PL[1]",
        "CL[1]",
        "PL[2]",
        "US[1]",
        "US[2]",
    )
    assert tuple(item.command for item in motion.parameters) == (
        "SD",
        "VH[2]",
        "VL[3]",
        "VH[3]",
        "XM[1]",
        "XM[2]",
        "MODULO MODE",
        "XA[4]:1",
        "XA[4]:2",
    )
    assert tuple(item.command for item in protections.parameters) == (
        "ER[3]",
        "ER[2]",
        "ER[5]",
        "CL[2]",
        "CL[3]",
        "CL[4]",
        "XP[1]",
        "XP[13]",
        "LL[3]",
        "HL[3]",
        "HL[2]",
    )

    by_command = {item.command: item for item in protections.parameters}
    assert "current" in by_command["CL[2]"].documented_effect.lower()
    assert "velocity" in by_command["CL[3]"].documented_effect.lower()
    assert "duration" in by_command["CL[4]"].documented_effect.lower()
    assert "minimum" in by_command["LL[3]"].label.lower()
    assert "maximum" in by_command["HL[3]"].label.lower()


def test_boundary_capabilities_fail_closed():
    snapshot = evidence.build_evidence_snapshot()
    boundary = snapshot.boundary.upper()

    for phrase in (
            "STATIC DOCUMENT MAP ONLY",
            "NOT CURRENT DRIVE CONFIG",
            "NOT ACTIVE PROTECTION STATE",
            "NOT A SAFETY ASSESSMENT",
            "NO DRIVE READ",
            "NO VALIDATION",
            "NO COMMAND",
            "NO WRITE",
            "NO APPLY/SV",
            "NO UNIT PROPAGATION"):
        assert phrase in boundary

    assert snapshot.can_inspect is True
    assert snapshot.can_read_drive is False
    assert snapshot.can_validate is False
    assert snapshot.can_evaluate is False
    assert snapshot.can_generate_commands is False
    assert snapshot.can_write is False
    assert snapshot.can_apply is False
    assert snapshot.can_persist is False
    assert snapshot.can_propagate_units is False


def test_document_conflicts_and_danger_warnings_are_not_normalized_away():
    snapshot = evidence.build_evidence_snapshot()
    conflicts = "\n".join(snapshot.document_conflicts)
    warnings = "\n".join(snapshot.persistent_warnings)

    for token in (
            "US[2]",
            "Reserved",
            "ER[5]",
            "CL[2]",
            "CL[3]",
            "CL[4]",
            "XA[4]",
            "CL[1]",
            "PL[1]",
            "HL[3]",
            "LL[3]"):
        assert token in conflicts
    assert "CL[2] < 2" in warnings
    assert "XA[4]" in warnings
    assert "disable" in warnings.lower()
    assert hashlib.sha256(conflicts.encode()).hexdigest() == (
        "a3117408b61a8f3f5c52ebef62947f6d0f899964156c0d8c86e5b79a526e0979"
    )
    assert hashlib.sha256(warnings.encode()).hexdigest() == (
        "54be34e34ab8444a9d9b9718b9b20a5d8f4d31fcb8adb495084ef5fd60d2d435"
    )

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
                item.command,
                item.documented_unit,
                item.access,
                item.documented_effect,
                item.condition,
                item.evidence_status,
            )
        ),
    )).upper()
    for forbidden in (
            "IS SAFE",
            "VALIDATED SAFE",
            "PROTECTIONS ARE VALID",
            "CURRENT DRIVE IS",
            "CURRENT DRIVE CONFIG IS",
            "INSTALLED VALUE",
            "EAS EQUIVALENT",
            "RECOMMENDED VALUE",
            "APP: R/W"):
        assert forbidden not in combined


def test_source_identity_is_exact():
    snapshot = evidence.build_evidence_snapshot()
    sources = {
        source.key: source.sha256 for source in snapshot.sources
    }
    assert {
        "nethelp_html": (
            "BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE"
        ),
        "nethelp_current_limits_image": (
            "248D74A6F9CCAF06847481061586AC730D280CA531E427FC03EF289DE4F3D156"
        ),
        "nethelp_motion_limits_image": (
            "C7D1FDB9B1D6C8CA898E7C9B6972B6C9E840EC354F2652FC116940EE94A5BEAE"
        ),
        "nethelp_protections_image": (
            "0840FB3554AD30DB8DE1DC429031C70CA03B2A1C3C772007367D515C445CE223"
        ),
        "command_reference": (
            "89280DB57DBBE6877945CC8C4720C959B8295E68806DECBFB9F43892994C2A80"
        ),
        "firmware_release_notes": (
            "3E70090E7E9E43290A972EE96ED057AF7E4E6D74FDA92780F6AD7D47BD201719"
        ),
        "gold_command_cl": (
            "A881FE3E645E42D417E6E598EE3A8016AA04910277B935DD92AC02999598F48C"
        ),
        "gold_command_xa": (
            "8A56F93F0D4F9F1FF9F4280619B5E9DAA2A4FF227D94219A76DC6EAC136A65CB"
        ),
        "gold_command_hl_ll": (
            "75BC54ACF8D84C6946FFB546CEAE22D70E81266A5FEDE6726669227A606461E5"
        ),
        "simpliq_alphabetical_listing": (
            "6387D916255910290468D103E42A796977D3BD44482EC4A04135B8E5780AFBEB"
        ),
    }.items() <= sources.items()


def test_fresh_module_import_performs_no_application_io(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("evidence module import attempted application I/O")

    module_name = evidence.__name__
    previous = sys.modules.pop(module_name)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    try:
        fresh = importlib.import_module(module_name)
        assert fresh.build_evidence_snapshot().can_read_drive is False
    finally:
        sys.modules[module_name] = previous


def test_snapshot_build_and_lookup_perform_no_runtime_io(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("immutable evidence lookup attempted runtime I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    snapshot = evidence.build_evidence_snapshot()
    assert evidence.section_evidence("current_limits") is snapshot.sections[0]


@pytest.mark.parametrize("key", [None, True, 1, "", "unknown"])
def test_section_lookup_rejects_noncanonical_keys(key):
    expected = TypeError if not isinstance(key, str) or isinstance(key, bool) \
        else KeyError
    with pytest.raises(expected):
        evidence.section_evidence(key)
