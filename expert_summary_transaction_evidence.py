"""Immutable documentation evidence for the EAS Expert Summary page.

This is a frozen local transaction map, not an executable Summary workflow.
Import, build, and lookup perform no file, process, network, worker, dialog,
database, or drive I/O.
"""

from __future__ import annotations

from dataclasses import dataclass


MODEL_ID = "expert_summary_documented_transaction_map_v0_1"
BOUNDARY = (
    "STATIC DOCUMENT MAP ONLY · DOCUMENTED SUMMARY TRANSACTION MAP · "
    "PARTIAL / NEED-DATA · NOT CURRENT EAS SUMMARY STATE · "
    "NOT CURRENT DRIVE STATE · NOT CURRENT FILE STATE · "
    "NOT CURRENT MOTOR DATABASE STATE · NOT PROOF OF SAVED DATA · "
    "NO DRIVE READ/UPLOAD · NO SV/DRIVE SAVE · NO FILE DIALOG · "
    "NO FILE/DESIGN EXPORT · NO DATABASE IMPORT/MUTATION · "
    "NO SAVE/APPLY · NO COMMAND GENERATION · NO ENERGIZATION/MOTION · "
    "NO DRIVE I/O"
)


@dataclass(frozen=True, slots=True)
class DocumentSource:
    key: str
    location: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DocumentedSummaryItem:
    key: str
    label: str
    control: str
    display_group: str
    documented_effect: str
    condition: str
    access: str
    risk_class: str
    evidence_status: str


@dataclass(frozen=True, slots=True)
class DocumentedSummarySection:
    key: str
    label: str
    reference: str
    items: tuple[DocumentedSummaryItem, ...]


@dataclass(frozen=True, slots=True)
class SummaryTransactionSnapshot:
    model_id: str
    authority: str
    model_status: str
    fidelity: str
    boundary: str
    sections: tuple[DocumentedSummarySection, ...]
    document_ambiguities: tuple[str, ...]
    persistent_warnings: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    sources: tuple[DocumentSource, ...]
    can_inspect: bool
    can_read_drive: bool
    can_observe_summary_state: bool
    can_observe_file_state: bool
    can_observe_database_state: bool
    can_select_actions: bool
    can_choose_paths: bool
    can_open_file_dialog: bool
    can_upload_from_drive: bool
    can_save_drive: bool
    can_save_files: bool
    can_save_design: bool
    can_import_database: bool
    can_mutate_database: bool
    can_generate_commands: bool
    can_write: bool
    can_apply: bool
    can_persist: bool
    can_energize: bool
    can_move: bool
    can_claim_saved: bool
    can_claim_complete: bool
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
        "summary_before_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_46.png",
        "2C39359565D75F5886CB44C4D772762BD30129D912212A94A5A15E53E7D48B21",
    ),
    DocumentSource(
        "summary_after_image",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_47.png",
        "5D26C4670ECF1ABD94E9F031B873459081D1E790629B0D96F4441043CF8E14A4",
    ),
)

_ACCESS = "document: inspect-only · app: inspect-only"


def _item(
        key: str,
        display_group: str,
        control: str,
        effect: str,
        condition: str,
        risk_class: str,
        evidence_status: str,
) -> DocumentedSummaryItem:
    return DocumentedSummaryItem(
        key=key,
        label=display_group,
        control=control,
        display_group=display_group,
        documented_effect=effect,
        condition=condition,
        access=_ACCESS,
        risk_class=risk_class,
        evidence_status=evidence_status,
    )


SECTIONS = (
    DocumentedSummarySection(
        key="recommended_actions",
        label="Recommended Actions",
        reference="Gold UM §8.2.2 steps 81–85 · Summary before-save image",
        items=(
            _item(
                "save_parameters_in_drive",
                "Save Parameters in Drive (SV)",
                "Save Parameters in Drive (SV)",
                "The manual describes selecting this checkbox to save "
                "configured parameters in the drive.",
                "Executed only by the real EAS Summary Save transaction; "
                "this inspector never selects it.",
                "PERSISTENT_WRITE",
                "DOCUMENTED CONTROL · EXECUTION NEED_DATA",
            ),
            _item(
                "upload_parameters_from_drive",
                "Upload Parameters from Drive",
                "Upload Parameters from Drive",
                "The manual describes uploading drive parameters to a "
                "user-selected local parameter file.",
                "Requires a connected target, exact path and format, complete "
                "read, verified file result, and recovery contract.",
                "DRIVE_READ + LOCAL_FILE",
                "DOCUMENTED CONTROL · EXECUTION NEED_DATA",
            ),
            _item(
                "save_design_plants",
                "Save Design Plants",
                "Save Design Plants",
                "The manual describes saving all identified plants and "
                "controllers to a selected design folder.",
                "Requires exact artifact schema, inventory, path, overwrite, "
                "integrity, and rollback contracts.",
                "LOCAL_FILE",
                "DOCUMENTED CONTROL · EXECUTION NEED_DATA",
            ),
            _item(
                "import_to_motor_database",
                "Import to DB…",
                "Import to DB…",
                "The manual describes optional import of the session motor "
                "data into the motor database selected in Edit Motor DB.",
                "Requires an explicit database identity, schema, duplicate "
                "policy, transaction/rollback, and post-write verification.",
                "LOCAL_DATABASE_MUTATION",
                "DOCUMENTED OPTIONAL CONTROL · EXECUTION NEED_DATA",
            ),
        ),
    ),
    DocumentedSummarySection(
        key="save_transaction",
        label="Save Transaction",
        reference="Gold UM §8.2.2 steps 81–85 · before/after images",
        items=(
            _item(
                "parameter_file_path",
                "Parameter File Path",
                "Parameter file path + browse (…) control",
                "The before-save image shows a local destination field for "
                "the parameter upload.",
                "The screenshot path is an example, not the current path and "
                "not authority to open a file dialog.",
                "DRIVE_READ + LOCAL_FILE",
                "DOCUMENTED EXAMPLE · CURRENT PATH UNKNOWN",
            ),
            _item(
                "design_folder_path",
                "Design Folder Path",
                "Design folder path + browse (…) control",
                "The before-save image shows a local destination folder for "
                "identified plant/controller artifacts.",
                "The screenshot path is an example, not the current folder "
                "and not authority to create or overwrite files.",
                "LOCAL_FILE",
                "DOCUMENTED EXAMPLE · CURRENT PATH UNKNOWN",
            ),
            _item(
                "save_commit",
                "Save (combined commit)",
                "Save",
                "The main procedure describes one Save action after choosing "
                "any Summary actions and destinations.",
                "This is a multi-authority transaction boundary; each selected "
                "effect needs independent preconditions and closeout evidence.",
                "COMPOSITE MUTATION",
                "DOCUMENTED CONTROL · ATOMICITY NEED_DATA",
            ),
            _item(
                "completion_log",
                "Completion Log",
                "Documented post-Save progress/result area",
                "The after-save example shows 3810 of 3810 parameters "
                "uploaded, VelocityPlants and CurrentPlants artifacts saved, "
                "and 'Completed Successfully'.",
                "Example screenshot only; it is not a current run, target, "
                "file inventory, hash, readback, or success claim.",
                "DOCUMENTATION ONLY",
                "DOCUMENTED EXAMPLE · NOT CURRENT RESULT",
            ),
        ),
    ),
    DocumentedSummarySection(
        key="authority_split",
        label="Authority Split",
        reference="Derived risk split from Gold UM §8.2.2 steps 81–85",
        items=(
            _item(
                "drive_flash_persistence",
                "Drive Flash Persistence",
                "Save Parameters in Drive (SV) execution",
                "Would persist selected tuning parameters in drive flash.",
                "Needs target identity, exact parameter set, pre-save snapshot, "
                "SV result/readback, power-cycle evidence, and rollback.",
                "PERSISTENT_WRITE",
                "DERIVED AUTHORITY · NEED_DATA / UNIMPLEMENTED",
            ),
            _item(
                "drive_parameter_export",
                "Drive Parameter Export",
                "Upload Parameters from Drive execution",
                "Would read parameters from the drive and write a local file.",
                "Needs bounded drive-read consistency plus path, format, "
                "overwrite, atomic write, hash, and recovery contracts.",
                "DRIVE_READ + LOCAL_FILE",
                "DERIVED AUTHORITY · NEED_DATA / UNIMPLEMENTED",
            ),
            _item(
                "design_artifact_export",
                "Design Artifact Export",
                "Save Design Plants execution",
                "Would write identified plants/controllers to local artifacts.",
                "Needs exact in-memory source identity, schema, artifact list, "
                "versioning, integrity, overwrite, and rollback contracts.",
                "LOCAL_FILE",
                "DERIVED AUTHORITY · NEED_DATA / UNIMPLEMENTED",
            ),
            _item(
                "motor_database_mutation",
                "Motor Database Mutation",
                "Import to DB… execution",
                "Would mutate the selected EAS motor database.",
                "Needs database identity and backup, schema compatibility, "
                "duplicate policy, transaction, verification, and rollback.",
                "LOCAL_DATABASE_MUTATION",
                "DERIVED AUTHORITY · NEED_DATA / UNIMPLEMENTED",
            ),
        ),
    ),
)

DOCUMENT_AMBIGUITIES = (
    "UPLOAD_DIRECTION: The control says Upload Parameters from Drive while "
    "the prose says it saves parameters to a file; the exact protocol, "
    "snapshot boundary, and file schema are not documented here.",
    "SAVE_COMMIT_LABEL: The main Expert procedure says click Save, while "
    "specialized gantry walkthroughs describe Apply after the same Summary "
    "checkboxes; target-specific transaction semantics require validation.",
    "DESIGN_ARTIFACT_SCHEMA: The prose says all identified plants and "
    "controllers; the example log names VelocityPlants and CurrentPlants, "
    "but complete artifact inventory, extensions, schema and versioning are "
    "not established.",
)

PERSISTENT_WARNINGS = (
    "DOCUMENTED_MAP_ONLY: This page normalizes installed manual text and "
    "screenshots; it does not inspect or operate EAS.",
    "NO_RUNTIME_IO: Import, build, lookup, rendering and section changes "
    "perform no file, database, dialog, worker, network or drive I/O.",
    "MULTI_AUTHORITY_TRANSACTION: One documented Save control may combine "
    "drive flash persistence, drive read, local file export, design export "
    "and database-related choices; these authorities must remain separate.",
    "SV_POWER_CYCLE: A reported SV response alone is not proof that exact "
    "parameters survived a power cycle or can be restored.",
    "PARTIAL_FAILURE: Ordering, atomicity, cancel, timeout, disk-full, "
    "disconnect and rollback behavior across selected actions are unknown.",
    "SCREENSHOT_NOT_CURRENT_STATE: Example paths, counts and Completed "
    "Successfully text are historical documentation, not live state.",
)

MISSING_EVIDENCE = (
    "TARGET IDENTITY: Exact connected drive, axis, serial/identity, firmware, "
    "personality and Summary-session binding.",
    "PRE_SAVE SNAPSHOT: Exact changed parameter set, previous flash/RAM "
    "values, design inventory and database record before any mutation.",
    "PATH CONTRACT: Canonical destinations, permissions, overwrite/collision "
    "policy, free space, temporary-file and recovery semantics.",
    "FILE FORMAT: Parameter and design schemas, versions, extensions, "
    "encoding, completeness rules, compatibility and independent parser.",
    "DATABASE CONTRACT: Selected database identity, schema/version, backup, "
    "duplicate/update policy and transaction boundary.",
    "ATOMICITY / PARTIAL FAILURE: Operation order, cancel/timeout/disconnect/"
    "disk-full behavior and durable per-action closeout.",
    "READBACK / INTEGRITY: Exact post-SV parameter readback, power-cycle "
    "check, exported file hashes/content and database verification.",
    "ROLLBACK / RECOVERY: Tested recovery for every partial completion state "
    "without overwriting the only known-good data.",
)

_SNAPSHOT = SummaryTransactionSnapshot(
    model_id=MODEL_ID,
    authority="DOCUMENTED_SUMMARY_TRANSACTION_MAP_ONLY",
    model_status="PARTIAL_NEED_DATA",
    fidelity="DOCUMENTED_STATIC_REFERENCE",
    boundary=BOUNDARY,
    sections=SECTIONS,
    document_ambiguities=DOCUMENT_AMBIGUITIES,
    persistent_warnings=PERSISTENT_WARNINGS,
    missing_evidence=MISSING_EVIDENCE,
    sources=SOURCES,
    can_inspect=True,
    can_read_drive=False,
    can_observe_summary_state=False,
    can_observe_file_state=False,
    can_observe_database_state=False,
    can_select_actions=False,
    can_choose_paths=False,
    can_open_file_dialog=False,
    can_upload_from_drive=False,
    can_save_drive=False,
    can_save_files=False,
    can_save_design=False,
    can_import_database=False,
    can_mutate_database=False,
    can_generate_commands=False,
    can_write=False,
    can_apply=False,
    can_persist=False,
    can_energize=False,
    can_move=False,
    can_claim_saved=False,
    can_claim_complete=False,
    can_claim_safety=False,
)

_SECTION_BY_KEY = {section.key: section for section in SECTIONS}


def build_evidence_snapshot() -> SummaryTransactionSnapshot:
    """Return the canonical immutable no-I/O Summary evidence snapshot."""
    return _SNAPSHOT


def section_evidence(key: str) -> DocumentedSummarySection:
    """Return one canonical Summary section without runtime I/O."""
    if isinstance(key, bool) or not isinstance(key, str):
        raise TypeError("section key must be a string")
    try:
        return _SECTION_BY_KEY[key]
    except KeyError as exc:
        raise KeyError("unknown Summary section %r" % key) from exc
