"""Pure contracts for the shared EAS operation/risk catalog."""

import pytest

import operation_catalog as catalog


def test_catalog_classifies_the_user_facing_hardware_boundaries():
    expected = {
        "drive.stop": catalog.OperationRisk.SAFETY_STOP,
        "axis.refresh": catalog.OperationRisk.DRIVE_READ,
        "session.zero": catalog.OperationRisk.RAM_WRITE,
        "tuning.p1.run": catalog.OperationRisk.ENERGIZING,
        "tuning.p2.run": catalog.OperationRisk.MOTION,
        "tuning.p2.verify": catalog.OperationRisk.MOTION,
        "tuning.p1.apply": catalog.OperationRisk.RAM_WRITE,
        "tuning.p2.save": catalog.OperationRisk.PERSISTENT_WRITE,
        "motion.ptp.run": catalog.OperationRisk.MOTION,
        "recorder.immediate": catalog.OperationRisk.DRIVE_STATE,
    }

    assert {key: catalog.operation_spec(key).risk for key in expected} == expected


def test_expert_offline_candidate_calculation_is_local_only():
    for operation_id in (
            "tuning.expert.offline.calculate",
            "tuning.expert.offline.calculate_p2"):
        spec = catalog.operation_spec(operation_id)
        assert spec.risk is catalog.OperationRisk.LOCAL_UI
        assert spec.status is catalog.OperationStatus.IMPLEMENTED
        assert spec.gates == frozenset()
        assert spec.risk not in catalog.DRIVE_MUTATING_RISKS
        assert "no drive" in spec.summary.lower()


def test_expert_filter_and_scheduling_are_visible_need_data_boundaries():
    for operation_id in (
            "tuning.expert.filter.offline.evaluate",
            "tuning.expert.scheduling.offline.evaluate"):
        spec = catalog.operation_spec(operation_id)
        assert spec.risk is catalog.OperationRisk.NEED_DATA
        assert spec.status is catalog.OperationStatus.NEED_DATA
        assert spec.gates == frozenset()
        assert not spec.menu_enabled


def test_expert_filter_and_scheduling_evidence_inspection_is_local_only():
    for operation_id in (
            "tuning.expert.filter.evidence.inspect",
            "tuning.expert.scheduling.evidence.inspect"):
        spec = catalog.operation_spec(operation_id)
        assert spec.risk is catalog.OperationRisk.LOCAL_UI
        assert spec.status is catalog.OperationStatus.PARTIAL
        assert spec.gates == frozenset()
        assert not spec.menu_enabled
        assert "no drive" in spec.summary.lower()
        assert "documented" in spec.summary.lower()


def test_expert_page_status_inspection_is_local_partial_and_not_eas_apply():
    spec = catalog.operation_spec("tuning.expert.page_status.inspect")

    assert spec.risk is catalog.OperationRisk.LOCAL_UI
    assert spec.status is catalog.OperationStatus.PARTIAL
    assert spec.gates == frozenset()
    assert not spec.menu_enabled
    assert "no drive" in spec.summary.lower()
    assert "not eas enter/apply" in spec.summary.lower()
    assert "not installed" in spec.summary.lower()


def test_expert_user_units_documented_formula_preview_is_local_partial():
    spec = catalog.operation_spec("tuning.expert.user_units.preview")

    assert spec.risk is catalog.OperationRisk.LOCAL_UI
    assert spec.status is catalog.OperationStatus.PARTIAL
    assert spec.gates == frozenset()
    assert not spec.menu_enabled
    summary = spec.summary.lower()
    assert "documented formula" in summary
    assert "documented grouping mismatch" in summary
    assert "purpose need-data" in summary
    assert "not current drive config" in summary
    assert "no drive" in summary
    assert "no fc/of write" in summary


def test_expert_limits_protections_inspector_is_local_partial_and_fail_closed():
    spec = catalog.operation_spec(
        "tuning.expert.limits_protections.evidence.inspect")

    assert spec.risk is catalog.OperationRisk.LOCAL_UI
    assert spec.status is catalog.OperationStatus.PARTIAL
    assert spec.gates == frozenset()
    assert not spec.menu_enabled
    assert spec.risk not in catalog.DRIVE_MUTATING_RISKS
    summary = spec.summary.lower()
    for phrase in (
            "documented parameter map",
            "not current drive config",
            "not active protection",
            "no drive read",
            "no validation",
            "no command",
            "no write",
            "no apply/sv",
            "no unit propagation"):
        assert phrase in summary


def test_expert_application_settings_inspector_is_local_partial_and_fail_closed():
    spec = catalog.operation_spec(
        "tuning.expert.application_settings.evidence.inspect")

    assert spec.risk is catalog.OperationRisk.LOCAL_UI
    assert spec.status is catalog.OperationStatus.PARTIAL
    assert spec.gates == frozenset()
    assert not spec.menu_enabled
    assert spec.risk not in catalog.DRIVE_MUTATING_RISKS
    summary = spec.summary.lower()
    for phrase in (
            "documented application settings map",
            "not current drive config",
            "not current i/o state",
            "not brake or safety evidence",
            "no drive read",
            "no validation",
            "no command",
            "no write",
            "no apply/revert/sv",
            "no output actuation",
            "no motion",
            "no drive i/o"):
        assert phrase in summary


def test_expert_application_settings_transaction_remains_need_data():
    spec = catalog.operation_spec(
        "tuning.expert.application_settings.transaction")

    assert spec.risk is catalog.OperationRisk.NEED_DATA
    assert spec.status is catalog.OperationStatus.NEED_DATA
    assert spec.gates == frozenset()
    assert not spec.menu_enabled
    summary = spec.summary.lower()
    for phrase in (
            "conditional visibility",
            "validation",
            "readback",
            "revert",
            "sv",
            "output actuation"):
        assert phrase in summary


def test_expert_bode_verification_evidence_is_local_partial_zero_io():
    spec = catalog.operation_spec(
        "tuning.expert.bode_verification.evidence.inspect")

    assert spec.risk is catalog.OperationRisk.LOCAL_UI
    assert spec.status is catalog.OperationStatus.PARTIAL
    assert spec.gates == frozenset()
    assert not spec.menu_enabled
    summary = spec.summary.lower()
    for phrase in (
            "immutable",
            "hidden",
            "document",
            "no drive read",
            "no acquisition",
            "no evaluation",
            "no verify",
            "no eas settings change",
            "no energization",
            "no motion"):
        assert phrase in summary


def test_expert_bode_verification_execute_remains_need_data():
    spec = catalog.operation_spec(
        "tuning.expert.bode_verification.execute")

    assert spec.risk is catalog.OperationRisk.NEED_DATA
    assert spec.status is catalog.OperationStatus.NEED_DATA
    assert spec.gates == frozenset()
    assert not spec.menu_enabled
    summary = spec.summary.lower()
    for phrase in (
            "current verification energizes",
            "velocity/position verification can move",
            "amplitude",
            "frequency",
            "current bounds",
            "sampling",
            "abort",
            "closeout",
            "acceptance"):
        assert phrase in summary


def test_expert_time_verification_evidence_is_local_partial_zero_io():
    spec = catalog.operation_spec(
        "tuning.expert.time_verification.evidence.inspect")

    assert spec.risk is catalog.OperationRisk.LOCAL_UI
    assert spec.status is catalog.OperationStatus.PARTIAL
    assert spec.gates == frozenset()
    assert not spec.menu_enabled
    summary = spec.summary.lower()
    for phrase in (
            "immutable",
            "verification-time",
            "document",
            "no drive read",
            "no recorder configuration",
            "no acquisition",
            "no verify",
            "no enable",
            "no ptp",
            "no jog",
            "no injection",
            "no energization",
            "no motion"):
        assert phrase in summary


def test_expert_summary_evidence_is_local_partial_zero_io():
    spec = catalog.operation_spec(
        "tuning.expert.summary.evidence.inspect")

    assert spec.risk is catalog.OperationRisk.LOCAL_UI
    assert spec.status is catalog.OperationStatus.PARTIAL
    assert spec.gates == frozenset()
    assert not spec.menu_enabled
    summary = spec.summary.lower()
    for phrase in (
            "immutable",
            "summary transaction",
            "document",
            "no drive read",
            "no sv",
            "no file dialog",
            "no file export",
            "no database mutation",
            "no save",
            "no apply",
            "no energization",
            "no motion"):
        assert phrase in summary


@pytest.mark.parametrize(
    ("operation_id", "risk", "phrases"),
    (
        (
            "tuning.expert.summary.drive_persist",
            catalog.OperationRisk.PERSISTENT_WRITE,
            ("sv", "drive flash", "readback", "rollback", "need-data"),
        ),
        (
            "tuning.expert.summary.parameter_export",
            catalog.OperationRisk.LOCAL_FILE,
            ("drive read", "local file", "path", "format", "need-data"),
        ),
        (
            "tuning.expert.summary.design_export",
            catalog.OperationRisk.LOCAL_FILE,
            ("identified plants", "controllers", "schema", "path", "need-data"),
        ),
        (
            "tuning.expert.summary.database_import",
            catalog.OperationRisk.LOCAL_FILE,
            ("motor database", "mutation", "duplicate", "rollback", "need-data"),
        ),
    ),
)
def test_expert_summary_mutations_remain_separate_need_data(
        operation_id, risk, phrases):
    spec = catalog.operation_spec(operation_id)

    assert spec.risk is risk
    assert spec.status is catalog.OperationStatus.NEED_DATA
    assert spec.gates == frozenset()
    assert not spec.menu_enabled
    summary = spec.summary.lower()
    for phrase in phrases:
        assert phrase in summary


def test_expert_current_time_execution_is_energizing_and_need_data():
    spec = catalog.operation_spec(
        "tuning.expert.time_verification.current.execute")

    assert spec.risk is catalog.OperationRisk.ENERGIZING
    assert spec.status is catalog.OperationStatus.NEED_DATA
    assert spec.gates == frozenset()
    assert not spec.menu_enabled
    summary = spec.summary.lower()
    for phrase in (
            "current",
            "energizes",
            "phase",
            "current envelope",
            "recorder provenance",
            "abort",
            "closeout",
            "acceptance"):
        assert phrase in summary


def test_expert_velocity_position_time_execution_is_motion_and_need_data():
    spec = catalog.operation_spec(
        "tuning.expert.time_verification.velocity_position.execute")

    assert spec.risk is catalog.OperationRisk.MOTION
    assert spec.status is catalog.OperationStatus.NEED_DATA
    assert spec.gates == frozenset()
    assert not spec.menu_enabled
    summary = spec.summary.lower()
    for phrase in (
            "enable",
            "ptp",
            "jog",
            "sine/step",
            "current input",
            "control parameter",
            "travel",
            "independent stop",
            "telemetry",
            "restore"):
        assert phrase in summary


def test_single_axis_safety_snapshot_is_zero_io_model_projection():
    spec = catalog.operation_spec("axis.safety_snapshot")

    assert spec.risk is catalog.OperationRisk.LOCAL_UI
    assert spec.status is catalog.OperationStatus.IMPLEMENTED
    assert spec.gates == frozenset()
    assert "MO/SO/MF/PS/SR/MS" in spec.summary
    assert "no new drive" in spec.summary.lower()
    assert "not STO test evidence" in spec.summary


def test_single_axis_authority_map_is_local_partial_and_zero_io():
    spec = catalog.operation_spec(
        "eas.single_axis.authority.evidence.inspect")

    assert spec.risk is catalog.OperationRisk.LOCAL_UI
    assert spec.status is catalog.OperationStatus.PARTIAL
    assert spec.gates == frozenset()
    assert not spec.menu_enabled
    summary = spec.summary.lower()
    for phrase in (
            "document",
            "no drive read",
            "no digital output write",
            "no mode change",
            "no enable",
            "no ptp",
            "jog",
            "current",
            "sine",
            "homing",
            "stepper",
            "no terminal",
            "no recorder",
            "no energization",
            "no motion"):
        assert phrase in summary


def test_unmapped_single_axis_eas_controls_remain_separate_need_data_gaps():
    for operation_id in (
            "eas.single_axis.digital_io",
            "eas.single_axis.manual_references",
            "eas.single_axis.terminal"):
        spec = catalog.operation_spec(operation_id)
        assert spec.risk is catalog.OperationRisk.NEED_DATA
        assert spec.status is catalog.OperationStatus.NEED_DATA
        assert not spec.menu_enabled


def test_live_ptp_catalog_matches_the_production_field_gate():
    spec = catalog.operation_spec("motion.ptp.run")

    assert spec.risk is catalog.OperationRisk.MOTION
    assert spec.status is catalog.OperationStatus.NEED_DATA
    assert "commissioning envelope" in spec.summary
    assert "site_motion_envelope" in spec.gates


def test_gain_mutation_catalog_is_need_data_and_installed_verify_uses_signature_gate():
    for operation_id in (
            "tuning.p1.apply", "tuning.p1.save",
            "tuning.p2.apply", "tuning.p2.save"):
        spec = catalog.operation_spec(operation_id)
        assert spec.status is catalog.OperationStatus.NEED_DATA
        assert "durable pre-assignment gain-trial WAL" in spec.summary

    verify = catalog.operation_spec("tuning.p2.verify")
    assert "commutation_signature" in verify.gates
    assert "trial_capability" not in verify.gates
    assert "currently installed" in verify.summary


def test_every_mutating_operation_declares_fail_closed_gates():
    for spec in catalog.OPERATIONS.values():
        if spec.risk not in catalog.DRIVE_MUTATING_RISKS:
            continue
        if not spec.gates:
            # A disabled NEED-DATA entry may classify the physical risk
            # before any executable gate contract exists.  It remains
            # fail-closed because no menu or dispatch path is exposed.
            assert spec.status is catalog.OperationStatus.NEED_DATA
            assert spec.menu_enabled is False
            continue
        assert "verified_identity" in spec.gates, spec.operation_id
        assert "fresh_telemetry" in spec.gates, spec.operation_id
        if spec.risk in {
                catalog.OperationRisk.ENERGIZING,
                catalog.OperationRisk.MOTION}:
            assert "explicit_scope" in spec.gates, spec.operation_id
            assert "verified_closeout" in spec.gates, spec.operation_id
        if spec.risk is catalog.OperationRisk.PERSISTENT_WRITE:
            assert "durable_authority" in spec.gates, spec.operation_id


def test_top_menu_can_only_execute_local_actions_or_show_disabled_need_data():
    for operation_ids in catalog.TOP_MENU_OPERATIONS.values():
        for operation_id in operation_ids:
            spec = catalog.operation_spec(operation_id)
            if spec.menu_enabled:
                assert spec.risk in {
                    catalog.OperationRisk.LOCAL_UI,
                    catalog.OperationRisk.LOCAL_FILE,
                }, operation_id
            else:
                assert spec.status is catalog.OperationStatus.NEED_DATA


def test_tool_organizer_file_contract_is_local_partial_and_native_gap_stays_locked():
    organizer = catalog.operation_spec("ui.tool_organizer")
    assert organizer.risk is catalog.OperationRisk.LOCAL_UI
    assert organizer.status is catalog.OperationStatus.PARTIAL
    assert organizer.menu_enabled is True
    assert organizer.gates == frozenset()

    native = catalog.operation_spec("eas.tool_organizer.native_persistence")
    assert native.risk is catalog.OperationRisk.NEED_DATA
    assert native.status is catalog.OperationStatus.NEED_DATA
    assert native.menu_enabled is False
    assert native.gates == frozenset()

    file_operations = catalog.TOP_MENU_OPERATIONS["File"]
    assert file_operations[0] == "ui.tool_organizer"
    assert "eas.tool_organizer.native_persistence" in file_operations


def test_status_monitor_host_view_and_full_eas_gaps_are_distinct_contracts():
    host = catalog.operation_spec("ui.status_monitor")
    assert host.risk is catalog.OperationRisk.LOCAL_UI
    assert host.status is catalog.OperationStatus.PARTIAL
    assert host.menu_enabled is True
    assert host.gates == frozenset()
    assert "HOST OBSERVED" in host.label
    assert "already-admitted" in host.summary
    assert "no new drive polling" in host.summary

    polling = catalog.operation_spec("eas.status_monitor.live_polling")
    assert polling.risk is catalog.OperationRisk.DRIVE_READ
    assert polling.status is catalog.OperationStatus.NEED_DATA
    assert polling.menu_enabled is False
    assert polling.gates == frozenset({
        "verified_identity",
        "fresh_telemetry",
        "bounded_read_allowlist",
        "poll_ownership",
        "poll_rate_limit",
    })
    for boundary in (
            "0.5 s", "arbitrary signals", "multi-target", "gauge",
            "Quick Watch"):
        assert boundary in polling.summary

    native = catalog.operation_spec("eas.status_monitor.native_config")
    assert native.risk is catalog.OperationRisk.LOCAL_FILE
    assert native.status is catalog.OperationStatus.NEED_DATA
    assert native.menu_enabled is False
    assert native.gates == frozenset()
    assert ".smc" in native.label
    assert ".smc/.sac" in native.summary

    floating = catalog.TOP_MENU_OPERATIONS["Floating Tools"]
    assert floating[0] == "ui.status_monitor"
    assert "eas.status_monitor.live_polling" in floating

    file_operations = catalog.TOP_MENU_OPERATIONS["File"]
    assert file_operations.index("eas.status_monitor.native_config") > (
        file_operations.index("eas.native_files"))
