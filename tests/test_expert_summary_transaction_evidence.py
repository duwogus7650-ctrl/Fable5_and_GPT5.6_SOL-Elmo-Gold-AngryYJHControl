"""Pure contracts for the Expert Summary documented transaction map."""

from __future__ import annotations

import builtins
from dataclasses import FrozenInstanceError
import importlib
import socket
import subprocess
import sys

import pytest

import expert_summary_transaction_evidence as evidence


EXPECTED_SECTION_KEYS = (
    "recommended_actions",
    "save_transaction",
    "authority_split",
)

EXPECTED_ROW_KEYS = {
    "recommended_actions": (
        "save_parameters_in_drive",
        "upload_parameters_from_drive",
        "save_design_plants",
        "import_to_motor_database",
    ),
    "save_transaction": (
        "parameter_file_path",
        "design_folder_path",
        "save_commit",
        "completion_log",
    ),
    "authority_split": (
        "drive_flash_persistence",
        "drive_parameter_export",
        "design_artifact_export",
        "motor_database_mutation",
    ),
}


def test_snapshot_is_canonical_frozen_deterministic_and_has_exact_shape():
    first = evidence.build_evidence_snapshot()
    second = evidence.build_evidence_snapshot()

    assert first is second
    assert first.model_id == "expert_summary_documented_transaction_map_v0_1"
    assert first.authority == "DOCUMENTED_SUMMARY_TRANSACTION_MAP_ONLY"
    assert first.model_status == "PARTIAL_NEED_DATA"
    assert first.fidelity == "DOCUMENTED_STATIC_REFERENCE"
    assert tuple(section.key for section in first.sections) == (
        EXPECTED_SECTION_KEYS
    )
    assert tuple(len(section.items) for section in first.sections) == (4, 4, 4)
    assert sum(len(section.items) for section in first.sections) == 12

    with pytest.raises(FrozenInstanceError):
        first.authority = "CURRENT_EAS_SUMMARY"
    with pytest.raises(FrozenInstanceError):
        first.sections[0].items[0].control = "Save now"


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


def test_documented_summary_controls_and_outputs_are_preserved():
    actions = {
        item.key: item
        for item in evidence.section_evidence("recommended_actions").items
    }
    transaction = {
        item.key: item
        for item in evidence.section_evidence("save_transaction").items
    }
    authorities = {
        item.key: item
        for item in evidence.section_evidence("authority_split").items
    }

    assert actions["save_parameters_in_drive"].control == (
        "Save Parameters in Drive (SV)"
    )
    assert actions["upload_parameters_from_drive"].control == (
        "Upload Parameters from Drive"
    )
    assert actions["save_design_plants"].control == "Save Design Plants"
    assert actions["import_to_motor_database"].control == "Import to DB…"
    assert transaction["save_commit"].control == "Save"

    completion_text = " ".join((
        transaction["completion_log"].documented_effect,
        transaction["completion_log"].condition,
    )).upper()
    for token in (
        "3810",
        "VELOCITYPLANTS",
        "CURRENTPLANTS",
        "COMPLETED SUCCESSFULLY",
    ):
        assert token in completion_text

    expected_risks = {
        "drive_flash_persistence": "PERSISTENT_WRITE",
        "drive_parameter_export": "DRIVE_READ + LOCAL_FILE",
        "design_artifact_export": "LOCAL_FILE",
        "motor_database_mutation": "LOCAL_DATABASE_MUTATION",
    }
    assert {
        key: authorities[key].risk_class
        for key in expected_risks
    } == expected_risks
    assert all(
        "NEED_DATA" in authorities[key].evidence_status
        for key in expected_risks
    )


def test_boundary_and_capabilities_fail_closed():
    snapshot = evidence.build_evidence_snapshot()
    boundary = snapshot.boundary.upper()

    for phrase in (
        "STATIC DOCUMENT MAP ONLY",
        "DOCUMENTED SUMMARY TRANSACTION MAP",
        "PARTIAL / NEED-DATA",
        "NOT CURRENT EAS SUMMARY STATE",
        "NOT CURRENT DRIVE STATE",
        "NOT CURRENT FILE STATE",
        "NOT CURRENT MOTOR DATABASE STATE",
        "NOT PROOF OF SAVED DATA",
        "NO DRIVE READ/UPLOAD",
        "NO SV/DRIVE SAVE",
        "NO FILE DIALOG",
        "NO FILE/DESIGN EXPORT",
        "NO DATABASE IMPORT/MUTATION",
        "NO SAVE/APPLY",
        "NO COMMAND GENERATION",
        "NO ENERGIZATION/MOTION",
        "NO DRIVE I/O",
    ):
        assert phrase in boundary

    assert snapshot.can_inspect is True
    for capability in (
        "can_read_drive",
        "can_observe_summary_state",
        "can_observe_file_state",
        "can_observe_database_state",
        "can_select_actions",
        "can_choose_paths",
        "can_open_file_dialog",
        "can_upload_from_drive",
        "can_save_drive",
        "can_save_files",
        "can_save_design",
        "can_import_database",
        "can_mutate_database",
        "can_generate_commands",
        "can_write",
        "can_apply",
        "can_persist",
        "can_energize",
        "can_move",
        "can_claim_saved",
        "can_claim_complete",
        "can_claim_safety",
    ):
        assert getattr(snapshot, capability) is False


def test_warnings_and_missing_evidence_cover_transaction_failure_modes():
    snapshot = evidence.build_evidence_snapshot()
    ambiguities = "\n".join(snapshot.document_ambiguities).upper()
    warnings = "\n".join(snapshot.persistent_warnings).upper()
    missing = "\n".join(snapshot.missing_evidence).upper()

    for category in (
        "UPLOAD_DIRECTION",
        "SAVE_COMMIT_LABEL",
        "DESIGN_ARTIFACT_SCHEMA",
    ):
        assert category in ambiguities
    for category in (
        "DOCUMENTED_MAP_ONLY",
        "NO_RUNTIME_IO",
        "MULTI_AUTHORITY_TRANSACTION",
        "SV_POWER_CYCLE",
        "PARTIAL_FAILURE",
        "SCREENSHOT_NOT_CURRENT_STATE",
    ):
        assert category in warnings
    for category in (
        "TARGET IDENTITY",
        "PRE_SAVE SNAPSHOT",
        "PATH",
        "FILE FORMAT",
        "DATABASE",
        "ATOMICITY",
        "READBACK",
        "ROLLBACK",
    ):
        assert category in missing


def test_catalog_contains_no_execution_or_success_claims():
    snapshot = evidence.build_evidence_snapshot()
    combined = " ".join((
        snapshot.boundary,
        *snapshot.document_ambiguities,
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
        "CURRENT DRIVE SAVED",
        "CURRENT FILE EXISTS",
        "CURRENT DATABASE UPDATED",
        "SAVE COMPLETED NOW",
        "READY TO SAVE",
        "VALIDATED SAFE",
        "APP: R/W",
    ):
        assert forbidden not in combined


def test_source_identity_is_exact_and_complete():
    snapshot_sources = evidence.build_evidence_snapshot().sources
    sources = {source.key: source.sha256 for source in snapshot_sources}

    assert sources == {
        "drive_setup_html": (
            "BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE"
        ),
        "summary_before_image": (
            "2C39359565D75F5886CB44C4D772762BD30129D912212A94A5A15E53E7D48B21"
        ),
        "summary_after_image": (
            "5D26C4670ECF1ABD94E9F031B873459081D1E790629B0D96F4441043CF8E14A4"
        ),
    }
    assert all(len(digest) == 64 for digest in sources.values())


def test_fresh_import_build_and_lookup_perform_no_runtime_io(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Summary evidence attempted runtime I/O")

    module_name = evidence.__name__
    previous = sys.modules.pop(module_name)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    try:
        fresh = importlib.import_module(module_name)
        snapshot = fresh.build_evidence_snapshot()
        assert snapshot.can_read_drive is False
        assert snapshot.can_save_drive is False
        assert snapshot.can_save_files is False
        assert snapshot.can_import_database is False
        assert fresh.section_evidence("recommended_actions") is (
            snapshot.sections[0]
        )
        assert calls == []
    finally:
        sys.modules[module_name] = previous


@pytest.mark.parametrize(
    "key",
    [None, True, 1, "", "unknown", "RECOMMENDED_ACTIONS"],
)
def test_section_lookup_rejects_noncanonical_keys(key):
    expected = (
        TypeError
        if not isinstance(key, str) or isinstance(key, bool)
        else KeyError
    )
    with pytest.raises(expected):
        evidence.section_evidence(key)
