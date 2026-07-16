"""Offline UI contracts for System Configuration Inspector v0.1."""

from __future__ import annotations

import os
import time
import unicodedata

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

import main as app_main
import operation_catalog
import system_configuration as sc
import theme as amber_theme
import theme_angrybirds
import theme_qdd


HASH_A = "elmo-sn4-sha256:" + ("c" * 64)


class _PoisonWorker:
    def __init__(self):
        self.calls = []

    @staticmethod
    def isRunning():
        return True

    def __getattr__(self, name):
        def forbidden(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            raise AssertionError("System Configuration page issued drive I/O: %s" % name)
        return forbidden


class _ConnectionWorker:
    def __init__(self):
        self.stop_calls = 0

    @staticmethod
    def isRunning():
        return True

    def stop(self):
        self.stop_calls += 1


class _OldWorker(QtCore.QObject):
    telemetry = QtCore.pyqtSignal(dict)


def _telemetry(sequence=1, *, mo=0, base=None):
    finished = time.monotonic() if base is None else float(base)
    return {
        "pos": 0,
        "vel": 0,
        "pos_err": 0,
        "iq": 0.0,
        "mo": mo,
        "telemetry_valid": True,
        "telemetry_sequence": sequence,
        "telemetry_received_monotonic": finished,
        "_sample_started_monotonic": finished - 0.01,
        "_sample_finished_monotonic": finished,
        "_sample_duration_s": 0.01,
        "session_coordinate_known": True,
        "encoder_maintenance_reconnect_required": False,
    }


def _connection_info(sequence=1, identity=HASH_A):
    return {
        "fw": "Twitter 01.01.16.00",
        "pal": "90",
        "boot": "DSP Boot",
        "target_type": "Gold Drive",
        "drive_identity": identity,
        "initial_telemetry": _telemetry(sequence),
        "persistence_status": {
            "status": "CLEAR", "lock_active": False,
            "detail": "No active persistence incident", "record_id": None,
            "phase": None, "other_active_count": 0, "ledger_error": None,
            "resolved": False,
        },
    }


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    previous_style = app.styleSheet()
    app.setStyleSheet(app_main.theme.STYLE)
    yield app
    app.setStyleSheet(previous_style)


@pytest.fixture
def window(qapp, monkeypatch):
    monkeypatch.setattr(app_main, "list_serial_ports", lambda: ["COM_TEST"])
    win = app_main.MainWindow()
    win.show()
    qapp.processEvents()
    yield win
    win.worker = None
    win.close()
    qapp.processEvents()


def test_catalog_separates_local_inspector_from_full_management():
    nav = operation_catalog.operation_spec("nav.system_config")
    assert nav.risk is operation_catalog.OperationRisk.LOCAL_UI
    assert nav.status is operation_catalog.OperationStatus.PARTIAL
    assert nav.menu_enabled

    full = operation_catalog.operation_spec("eas.system_config.manage")
    assert full.risk is operation_catalog.OperationRisk.NEED_DATA
    assert full.status is operation_catalog.OperationStatus.NEED_DATA
    assert not full.menu_enabled


def test_every_selectable_theme_has_ordered_status_pill_semantics():
    for themed in (theme_qdd, amber_theme, theme_angrybirds):
        on_index = themed.STYLE.index('QLabel#pill[on="true"]')
        for status in ("active", "ready", "success", "error", "neutral"):
            selector = 'QLabel#pill[status="%s"]' % status
            assert selector in themed.STYLE
            assert themed.STYLE.index(selector) > on_index


def test_open_and_render_are_zero_io_and_do_not_change_authority(window, qapp):
    poison = _PoisonWorker()
    window.worker = poison
    window._connection_admitted = True
    window._telemetry_authoritative = True

    window.app_menu_actions["nav.system_config"].trigger()
    window._render_system_configuration()
    qapp.processEvents()

    assert window.stack.currentIndex() == 7
    assert window._connection_admitted is True
    assert window._telemetry_authoritative is True
    assert poison.calls == []
    assert not window.app_menu_actions["eas.system_config.manage"].isEnabled()


def test_page_is_read_only_and_full_eas_mutations_are_visibly_locked(window):
    assert window.system_config_tree.editTriggers() == (
        QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    assert window.system_config_table.editTriggers() == (
        QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    assert "HOST-OBSERVED" in window.lbl_system_config_contract.text()
    assert "not full EAS System Configuration" in (
        window.lbl_system_config_contract.text())
    assert window.system_config_locked_controls
    for control in window.system_config_locked_controls:
        assert not control.isEnabled()
        assert control.property("operationId") == "eas.system_config.manage"


def test_admitted_connection_populates_one_level_direct_drive_projection(window):
    worker = _ConnectionWorker()
    window.worker = worker

    window._on_connected(_connection_info())

    snapshot = window.system_configuration.snapshot()
    assert snapshot.state == sc.CURRENT
    assert snapshot.generation == window.session_log.current_generation == 1
    assert snapshot.target_type == "Gold Drive"
    assert snapshot.firmware == "Twitter 01.01.16.00"
    assert window.lbl_system_config_state.text() == "CURRENT · HOST OBSERVED"
    root = window.system_config_tree.topLevelItem(0)
    assert root.text(0) == "Workspace · Current Session"
    assert root.childCount() == 1
    assert root.child(0).text(0).startswith("Drive01 · Gold Drive")
    assert worker.stop_calls == 0

    table = {
        window.system_config_table.item(row, 0).text(): (
            window.system_config_table.item(row, 1).text(),
            window.system_config_table.item(row, 2).text())
        for row in range(window.system_config_table.rowCount())
    }
    assert table["Target class"] == (
        "Gold Drive · application classification",
        "APPLICATION CLASSIFICATION (NOT BOARD READBACK)")
    assert table["Hardware board type"] == (
        "NEED-DATA", "NO VERIFIED PUBLIC READ MAPPING")


def test_connection_metadata_is_safe_in_every_global_display_projection(window):
    worker = _ConnectionWorker()
    window.worker = worker
    info = _connection_info()
    info.update({
        "fw": "Twitter <b>ONLINE</b> \u202eENILNO COM3 " + (
            "elmo-sn4-sha256:" + ("d" * 64)),
        "pal": "90 SN[4]=12345678",
        "boot": r"DSP Boot C:\Users\alice\secret.bin",
    })

    window._on_connected(info)

    assert window._connection_admitted is True
    rendered = " | ".join((
        window.lbl_fw.text(), window.lbl_pal.text(), window.lbl_boot.text(),
        window.cmb_ribbon_target.itemText(0),
        window._connected_identity["fw"],
        window.system_configuration.snapshot().firmware,
    ))
    assert all(
        unicodedata.category(char) not in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        for char in rendered)
    for secret in ("COM3", "alice", "12345678", "elmo-sn4-sha256:"):
        assert secret not in rendered
    assert "NOT HARDWARE BOARD READBACK" in window.lbl_type.toolTip()
    assert any(
        label.text() == "Target Class (app)"
        for label in window.findChildren(QtWidgets.QLabel))
    assert all(
        label.textFormat() == QtCore.Qt.TextFormat.PlainText
        for label in (
            window.lbl_fw, window.lbl_pal, window.lbl_boot, window.lbl_type))
    assert "<b>ONLINE</b>" in window.lbl_fw.text()
    firmware_row = next(
        row for row in range(window.system_config_table.rowCount())
        if window.system_config_table.item(row, 0).text() == (
            "Firmware / Target Version"))
    firmware_item = window.system_config_table.item(firmware_row, 1)
    assert "<b>ONLINE</b>" in firmware_item.text()
    assert "<b>" not in firmware_item.toolTip()
    assert "&lt;b&gt;ONLINE&lt;/b&gt;" in firmware_item.toolTip()
    opened = next(
        row for row in window.session_log.snapshot()
        if row["name"] == "connection.opened")
    assert "target_type" not in opened["payload"]
    assert opened["payload"]["application_target_class"] == (
        "Gold Drive")
    assert opened["payload"][
        "application_target_class_provenance"] == (
            "APPLICATION CLASSIFICATION · NOT BOARD READBACK")

    window._on_recorder_manifest({
        "worker_generation": 1,
        "target_type": "ambiguous worker field",
    })
    manifest = window._recorder_manifest_data
    assert "target_type" not in manifest
    assert manifest["application_target_class"] == "Gold Drive"
    assert manifest["application_target_class_provenance"] == (
        "APPLICATION CLASSIFICATION · NOT BOARD READBACK")


def test_replayed_telemetry_revokes_projection_and_fresh_sequence_restores(window):
    worker = _ConnectionWorker()
    window.worker = worker
    window._on_connected(_connection_info(sequence=1))

    window._on_telemetry(_telemetry(sequence=1))

    assert window.system_configuration.snapshot().state == sc.NO_CURRENT_TARGET
    assert window.lbl_system_config_state.text() == "NO CURRENT TARGET"
    assert window.system_config_tree.topLevelItem(0).childCount() == 0

    window._on_telemetry(_telemetry(sequence=2))

    assert window.system_configuration.snapshot().state == sc.CURRENT
    assert window.system_configuration.snapshot().telemetry_sequence == 2


def test_old_worker_signal_cannot_change_current_projection(window, qapp):
    old = _OldWorker()
    old.telemetry.connect(window._on_telemetry)
    current = _ConnectionWorker()
    window.worker = current
    window._on_connected(_connection_info(sequence=1))
    before = window.system_configuration.snapshot()

    old.telemetry.emit(_telemetry(sequence=99, mo=1))
    qapp.processEvents()

    assert window.system_configuration.snapshot() is before
    assert window.system_configuration.snapshot().motor_enabled is False


def test_failure_and_late_telemetry_cannot_restore_current_target(window):
    worker = _ConnectionWorker()
    window.worker = worker
    window._on_connected(_connection_info(sequence=1))

    window._on_failed("transport lost")
    window._on_telemetry(_telemetry(sequence=2))

    snapshot = window.system_configuration.snapshot()
    assert snapshot.state == sc.NO_CURRENT_TARGET
    assert snapshot.identity_alias is None
    assert snapshot.target_type is None


@pytest.mark.parametrize("failure_site", ("update", "render"))
def test_inspector_failure_cannot_abort_core_motor_safety_update(
        window, monkeypatch, failure_site):
    worker = _ConnectionWorker()
    window.worker = worker
    window._on_connected(_connection_info(sequence=1))

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected Inspector observer failure")

    if failure_site == "update":
        original_observer = window.system_configuration.update_telemetry
        monkeypatch.setattr(
            window.system_configuration, "update_telemetry", fail)
    else:
        original_observer = window._render_system_configuration
        monkeypatch.setattr(window, "_render_system_configuration", fail)

    window._on_telemetry(_telemetry(sequence=2, mo=1))

    assert window._last_telemetry_sequence == 2
    assert window._telemetry_authoritative is True
    assert window._last_mo == 1
    assert window.lbl_motor.text() == "MOTOR ENABLED"
    assert not window.btn_zero.isEnabled()
    assert window.btn_global_stop.isEnabled()
    assert window.system_configuration.snapshot().state == sc.NO_CURRENT_TARGET
    assert "OBSERVER ERROR" in window.lbl_system_config_state.text()
    assert window.lbl_system_config_state.property("on") == "false"
    assert window.lbl_system_config_state.property("status") == "error"

    if failure_site == "update":
        monkeypatch.setattr(
            window.system_configuration, "update_telemetry", original_observer)
    else:
        monkeypatch.setattr(
            window, "_render_system_configuration", original_observer)
    window._on_telemetry(_telemetry(sequence=3, mo=0))

    assert window.system_configuration.snapshot().state == sc.CURRENT
    assert window.lbl_system_config_state.text() == "CURRENT · HOST OBSERVED"
    assert window.lbl_system_config_state.property("status") is None
    assert window.lbl_system_config_state.property("on") == "true"


def test_uppercase_identity_is_rejected_at_connection_admission(window):
    worker = _ConnectionWorker()
    window.worker = worker

    window._on_connected(_connection_info(
        identity="elmo-sn4-sha256:" + ("C" * 64)))

    assert window._connection_admitted is False
    assert window._telemetry_authoritative is False
    assert worker.stop_calls == 1
    assert window.system_configuration.snapshot().state == sc.NO_CURRENT_TARGET
    assert window.session_log.connection_active is False
    assert window.session_log.current_generation is None
    assert not any(
        row["name"] == "connection.opened"
        for row in window.session_log.snapshot())


def test_new_connect_attempt_clears_old_projection_before_worker_admission(
        window, monkeypatch):
    window.worker = _ConnectionWorker()
    window._on_connected(_connection_info(sequence=1))
    assert window.system_configuration.snapshot().state == sc.CURRENT

    window.worker = None
    monkeypatch.setattr(app_main.DriveWorker, "start", lambda _worker: None)
    window.cmb_port.setCurrentText("COM_TEST")
    window.connect_drive()

    assert window.system_configuration.snapshot().state == sc.NO_CURRENT_TARGET
    assert window.lbl_system_config_state.text() == "NO CURRENT TARGET"
    assert window.system_config_tree.topLevelItem(0).childCount() == 0


def test_contract_label_is_not_clipped(window, qapp):
    window.resize(1500, 940)
    window._nav_to(7)
    qapp.processEvents()

    assert window.lbl_system_config_contract.height() >= (
        window.lbl_system_config_contract.sizeHint().height())
    assert window.workspace_scroll.horizontalScrollBar().maximum() == 0


def test_eight_page_navigation_and_system_page_fit_declared_1366_width(
        window, qapp):
    def assert_1366_contract():
        qapp.processEvents()
        assert window.minimumSizeHint().width() <= 1366
        assert window.width() <= 1366
        assert window.workspace_scroll.horizontalScrollBar().maximum() == 0

    selectable_themes = (theme_qdd, amber_theme, theme_angrybirds)
    window.resize(1366, 820)
    window._nav_to(7)
    assert_1366_contract()
    assert window.lbl_system_config_contract.height() >= (
        window.lbl_system_config_contract.sizeHint().height())
    vertical = window.workspace_scroll.verticalScrollBar()
    assert vertical.maximum() > 0
    vertical.setValue(vertical.maximum())
    qapp.processEvents()
    viewport = window.workspace_scroll.viewport()
    viewport_rect = QtCore.QRect(
        viewport.mapToGlobal(QtCore.QPoint(0, 0)), viewport.size())
    for control in window.system_config_locked_controls:
        control_rect = QtCore.QRect(
            control.mapToGlobal(QtCore.QPoint(0, 0)), control.size())
        assert viewport_rect.contains(control_rect)
        assert not control.isEnabled()
    vertical.setValue(0)
    assert [button.text() for button in window._nav_btns][-2:] == [
        "Status", "System"]
    assert "Session Log" in window._nav_btns[-2].toolTip()
    assert "System Configuration" in window._nav_btns[-1].toolTip()

    window.worker = _ConnectionWorker()
    window._on_connected(_connection_info())
    window._persistence_audit_summary = {
        "ledger_error": "injected", "lock_active": True,
        "other_active_count": 0,
    }
    window._update_persistence_badge()
    # CURRENT has the longer page-state pill and ERROR has the longest safety
    # badge. This single worst-case combination gates all advertised skins.
    for themed in selectable_themes:
        qapp.setStyleSheet(themed.STYLE)
        window.resize(1366, 820)
        assert_1366_contract()
    qapp.setStyleSheet(app_main.theme.STYLE)

    for summary in (
        {"ledger_error": "injected", "lock_active": True,
         "other_active_count": 0},
        {"ledger_error": None, "lock_active": True, "phase": "P2",
         "other_active_count": 0},
        {"ledger_error": None, "lock_active": False,
         "other_active_count": 2},
        {"ledger_error": None, "lock_active": False,
         "other_active_count": 0},
    ):
        window._persistence_audit_summary = summary
        window._update_persistence_badge()
        window.resize(1366, 820)
        assert_1366_contract()
