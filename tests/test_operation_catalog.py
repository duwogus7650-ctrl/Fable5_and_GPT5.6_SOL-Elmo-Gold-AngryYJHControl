"""Pure contracts for the shared EAS operation/risk catalog."""

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
