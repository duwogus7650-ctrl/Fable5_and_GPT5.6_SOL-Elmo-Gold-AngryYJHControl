"""Offline UI contracts for the always-visible EAS-style application menus."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtWidgets

import main as app_main


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


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


def test_application_menus_are_visible_outside_recorder_context(window, qapp):
    assert tuple(window.app_menu_buttons) == (
        "File", "Parameters", "Tools", "Views", "Floating Tools")
    assert window.eas_application_menu_row.isVisibleTo(window)
    assert not window.btn_rec_context.isVisibleTo(window)
    assert not window.lbl_recorder_ribbon_state.isVisibleTo(window)

    window.app_menu_actions["nav.recorder"].trigger()
    qapp.processEvents()

    assert window.stack.currentIndex() == 5
    assert window.btn_rec_context.isVisibleTo(window)
    assert window.lbl_recorder_ribbon_state.isVisibleTo(window)


def test_quick_and_expert_menu_routes_are_local_and_visually_separate(
        window, qapp):
    assert window.worker is None

    window.app_menu_actions["nav.tuning.quick"].trigger()
    qapp.processEvents()
    assert window.stack.currentIndex() == 3
    assert window._tuning_mode == "quick"
    assert not window.tuning_expert_frame.isVisibleTo(window)

    window.app_menu_actions["nav.tuning.expert"].trigger()
    qapp.processEvents()
    assert window.stack.currentIndex() == 3
    assert window._tuning_mode == "expert"
    assert window.tuning_expert_frame.isVisibleTo(window)
    assert window.worker is None


def test_quick_mode_exposes_guided_runs_but_hides_expert_transactions(
        window, qapp):
    window._show_tuning_mode("quick")
    qapp.processEvents()

    assert window.tuning_guided_run_frame.isVisibleTo(window)
    assert "SUPERVISED" in window.guided_run_title.text()
    assert "MOTION" in window.guided_run_title.text()
    for button in (
            window.btn_tune,
            window.btn_tune_signature,
            window.btn_tune_vp,
            window.btn_tune_abort,
            window.btn_tune_verify):
        assert button.isVisibleTo(window)

    assert not window.expert_lab_frame.isVisibleTo(window)
    for button in (
            window.btn_tune_apply,
            window.btn_tune_p1_restore,
            window.btn_tune_p1_save,
            window.btn_tune_vp_apply,
            window.btn_tune_vp_restore,
            window.btn_tune_vp_save):
        assert not button.isVisibleTo(window)

    window._show_tuning_mode("expert")
    qapp.processEvents()

    assert window.tuning_guided_run_frame.isVisibleTo(window)
    assert window.expert_lab_frame.isVisibleTo(window)
    for button in (
            window.btn_tune_apply,
            window.btn_tune_p1_restore,
            window.btn_tune_p1_save,
            window.btn_tune_vp_apply,
            window.btn_tune_vp_restore,
            window.btn_tune_vp_save):
        assert button.isVisibleTo(window)


def test_need_data_menu_entries_are_visible_but_not_executable(window):
    for operation_id in (
            "eas.native_files", "eas.multiaxis", "eas.floating_terminal",
            "eas.tool_organizer.native_persistence",
            "eas.status_monitor.live_polling",
            "eas.status_monitor.native_config"):
        action = window.app_menu_actions[operation_id]
        assert not action.isEnabled()
        assert "NEED-DATA" in action.text()


def test_safety_critical_controls_expose_shared_operation_classification(window):
    expected = {
        window.btn_global_stop: ("drive.stop", "safety_stop"),
        window.btn_axis_refresh: ("axis.refresh", "drive_read"),
        window.btn_zero: ("session.zero", "ram_write"),
        window.btn_tune: ("tuning.p1.run", "energizing"),
        window.btn_tune_vp: ("tuning.p2.run", "motion"),
        window.btn_tune_verify: ("tuning.p2.verify", "motion"),
        window.btn_tune_apply: ("tuning.p1.apply", "ram_write"),
        window.btn_tune_vp_save: ("tuning.p2.save", "persistent_write"),
        window.btn_motion_run: ("motion.ptp.run", "motion"),
        window.btn_rec_immediate: ("recorder.immediate", "drive_state"),
    }
    for widget, (operation_id, risk) in expected.items():
        assert widget.property("operationId") == operation_id
        assert widget.property("operationRisk") == risk
