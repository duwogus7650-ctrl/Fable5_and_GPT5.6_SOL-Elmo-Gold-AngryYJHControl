"""Offline fail-closed UI contracts for Tool Organizer v0.1."""

from __future__ import annotations

import os
import json
import subprocess
import sys
import textwrap

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

import main as app_main
import tool_organizer


@pytest.mark.parametrize("skin", ("qdd", "amber", "angrybirds"))
def test_production_skin_apply_keeps_1366x820_and_protected_geometry(skin):
    probe = textwrap.dedent(r"""
        import json
        import os
        from PyQt6 import QtCore, QtGui, QtWidgets
        import main

        main.list_serial_ports = lambda: ["COM_TEST"]
        app = QtWidgets.QApplication([])
        font_path = os.path.join(os.environ["WINDIR"], "Fonts", "malgun.ttf")
        font_id = QtGui.QFontDatabase.addApplicationFont(font_path)
        family = QtGui.QFontDatabase.applicationFontFamilies(font_id)[0]
        app.setFont(QtGui.QFont(family, 10))
        app.setStyleSheet(
            main.theme.STYLE + '\n* { font-family: "%s"; }' % family)
        window = main.MainWindow()
        window.resize(1366, 820)
        window.show()
        for _ in range(5):
            app.processEvents()
        window._nav_to(4)
        window._show_tool_organizer()
        for _ in range(5):
            app.processEvents()
        dialog = window.tool_organizer_dialog

        def select(list_widget, tool_id):
            for row in range(list_widget.count()):
                item = list_widget.item(row)
                if item.data(QtCore.Qt.ItemDataRole.UserRole) == tool_id:
                    list_widget.setCurrentRow(row)
                    return
            raise AssertionError(tool_id)

        for tool_id in ("feedback", "axis"):
            select(dialog.active_list, tool_id)
            dialog.btn_remove.click()
        select(dialog.active_list, "system")
        for _ in range(5):
            dialog.btn_up.click()
        dialog.btn_apply.click()
        for _ in range(5):
            app.processEvents()

        dialog_rect = dialog.frameGeometry()
        protected = (
            window.btn_conn, window.btn_global_stop,
            window.lbl_persistence_badge, window.lbl_state,
            *window.app_menu_buttons.values(),
        )
        overlaps = []
        for widget in protected:
            origin = widget.mapToGlobal(QtCore.QPoint(0, 0))
            if dialog_rect.intersects(QtCore.QRect(origin, widget.size())):
                overlaps.append(widget.objectName() or widget.text())
        print(json.dumps({
            "size": [window.width(), window.height()],
            "minimum": [window.minimumSizeHint().width(),
                        window.minimumSizeHint().height()],
            "current_index": window.stack.currentIndex(),
            "overlaps": overlaps,
            "status_bar_count": len(window.findChildren(QtWidgets.QStatusBar)),
            "toast_visible": window._toast_label.isVisibleTo(window),
        }))
        window.worker = None
        window.close()
    """)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["AYJH_THEME"] = skin
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=os.path.dirname(app_main.__file__), env=env,
        text=True, capture_output=True, timeout=60, check=True)
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["size"] == [1366, 820]
    assert result["minimum"][1] <= 820
    assert result["current_index"] == 7
    assert result["overlaps"] == []
    assert result["status_bar_count"] == 0
    assert result["toast_visible"] is True


class _PoisonWorker:
    """Any drive/worker touch from a local layout operation is a test failure."""

    def __getattr__(self, name):
        raise AssertionError("Tool Organizer touched worker.%s" % name)


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
    win.resize(1366, 820)
    win.show()
    qapp.processEvents()
    yield win
    win.worker = None
    win.close()
    qapp.processEvents()


def _select_tool(list_widget, tool_id):
    for row in range(list_widget.count()):
        item = list_widget.item(row)
        if item.data(QtCore.Qt.ItemDataRole.UserRole) == tool_id:
            list_widget.setCurrentRow(row)
            return
    raise AssertionError("tool %r not found" % tool_id)


def _open_dialog(window, qapp):
    window.app_menu_actions["ui.tool_organizer"].trigger()
    qapp.processEvents()
    dialog = window.tool_organizer_dialog
    assert dialog is not None
    assert dialog.isVisible()
    return dialog


def _unchecked_layout(active, available):
    """Build a corrupt candidate without weakening ToolLayout construction."""
    candidate = object.__new__(tool_organizer.ToolLayout)
    object.__setattr__(candidate, "active", active)
    object.__setattr__(candidate, "available", available)
    return candidate


def test_organizer_is_modeless_local_ui_and_cannot_hide_safety_shell(
        window, qapp):
    window.worker = _PoisonWorker()
    protected = (
        window.btn_global_stop,
        window.btn_conn,
        window.lbl_state,
        window.lbl_persistence_badge,
        *window.app_menu_buttons.values(),
    )

    dialog = _open_dialog(window, qapp)

    assert not dialog.isModal()
    assert dialog.windowModality() == QtCore.Qt.WindowModality.NonModal
    assert dialog.lbl_contract.text().startswith("LOCAL SESSION v0.1")
    assert all(widget.isVisibleTo(window) for widget in protected)
    for widget in protected:
        top_left = widget.mapTo(window, QtCore.QPoint(0, 0))
        assert top_left.x() >= 0
        assert top_left.y() >= 0
        assert top_left.x() + widget.width() <= window.width()
        assert top_left.y() + widget.height() <= window.height()
    assert window.worker.__class__ is _PoisonWorker


def test_apply_hides_active_tool_falls_back_and_preserves_all_pages(
        window, qapp):
    page_objects = tuple(window.stack.widget(i) for i in range(window.stack.count()))
    # EAS-flow default lands on the first/top tool = motor (canonical index 1)
    assert window.stack.currentIndex() == 1
    dialog = _open_dialog(window, qapp)

    _select_tool(dialog.active_list, "motion")
    dialog.btn_remove.click()
    dialog.btn_apply.click()
    qapp.processEvents()

    # EAS default order (motor,feedback,axis,tuning,motion,recorder,system,status)
    # minus the removed motion
    assert window.tool_layout.active == (
        "motor", "feedback", "axis", "tuning",
        "recorder", "system", "status")
    assert window.stack.currentIndex() == 1
    assert not window._nav_button_by_tool_id["motion"].isVisible()
    assert all(
        not action.isVisible()
        for action in window.app_menu_actions_by_operation["nav.motion"])
    assert window.stack.count() == 8
    assert tuple(window.stack.widget(i) for i in range(8)) == page_objects
    assert window.btn_global_stop.isVisibleTo(window)
    assert window.btn_conn.isVisibleTo(window)


def test_default_startup_nav_order_is_eas_flow(window, qapp):
    """The fresh window renders the vertical tool nav in EAS-flow VISUAL order
    (setup -> tuning -> run -> diagnostics), and lands on the top tool.  Page
    indices stay canonical, so this is a presentation-only ordering."""
    visible_buttons = sorted(
        (button.mapTo(window, QtCore.QPoint(0, 0)).y(), tool_id)
        for tool_id, button in window._nav_button_by_tool_id.items()
        if button.isVisibleTo(window))
    assert tuple(tool_id for _, tool_id in visible_buttons) \
        == tool_organizer.DEFAULT_NAV_ORDER
    assert tool_organizer.DEFAULT_NAV_ORDER[0] == "motor"
    # landed on the top tool (motor = canonical page index 1)
    assert window.stack.currentIndex() \
        == window._TOOL_ID_TO_PAGE_INDEX["motor"]
    # every page object still present (ordering did not drop pages)
    assert window.stack.count() == len(tool_organizer.CANONICAL_TOOL_IDS)


def test_reorder_and_reset_are_atomic_and_keep_menu_duplicates_consistent(
        window, qapp):
    dialog = _open_dialog(window, qapp)
    _select_tool(dialog.active_list, "system")
    for _ in range(7):
        dialog.btn_up.click()
    dialog.btn_apply.click()
    qapp.processEvents()

    assert window.tool_layout.active[0] == "system"
    # EAS-structure: the tool nav is a vertical column, so visual order is by
    # y (was x when the nav was a horizontal row).
    visible_buttons = sorted(
        (button.mapTo(window, QtCore.QPoint(0, 0)).y(), tool_id)
        for tool_id, button in window._nav_button_by_tool_id.items()
        if button.isVisibleTo(window))
    assert tuple(tool_id for _, tool_id in visible_buttons) == window.tool_layout.active
    assert len(window.app_menu_actions_by_operation["nav.system_config"]) >= 2
    assert all(
        action.isVisible()
        for action in window.app_menu_actions_by_operation["nav.system_config"])

    dialog = _open_dialog(window, qapp)
    dialog.btn_reset.click()
    dialog.btn_apply.click()
    qapp.processEvents()

    assert window.tool_layout == tool_organizer.DEFAULT_LAYOUT
    assert all(button.isVisibleTo(window)
               for button in window._nav_button_by_tool_id.values())
    for operation_id in window._tool_nav_operation_ids:
        assert all(action.isVisible() for action in
                   window.app_menu_actions_by_operation[operation_id])


def test_rejected_forged_or_all_hidden_layout_is_noop_for_ui_and_authority(
        window, qapp):
    before_layout = window.tool_layout
    before_pages = tuple(window.stack.widget(i) for i in range(8))
    before_visibility = {
        key: button.isVisible() for key, button in
        window._nav_button_by_tool_id.items()
    }
    window._telemetry_authoritative = False
    window._last_mo = None
    sentinel_worker = object()
    window.worker = sentinel_worker

    for candidate in (
        _unchecked_layout(
            ("drive.stop",), tool_organizer.CANONICAL_TOOL_IDS),
        _unchecked_layout(
            (), tool_organizer.CANONICAL_TOOL_IDS),
    ):
        with pytest.raises(tool_organizer.ToolOrganizerError):
            window._apply_tool_layout(candidate)

    assert window.tool_layout == before_layout
    assert {key: button.isVisible() for key, button in
            window._nav_button_by_tool_id.items()} == before_visibility
    assert tuple(window.stack.widget(i) for i in range(8)) == before_pages
    assert window._telemetry_authoritative is False
    assert window._last_mo is None
    assert window.worker is sentinel_worker


def test_dialog_rejects_removing_last_visible_tool_without_partial_apply(
        window, qapp):
    only_system = tool_organizer.ToolLayout(
        active=("system",),
        available=tuple(
            tool_id for tool_id in tool_organizer.CANONICAL_TOOL_IDS
            if tool_id != "system"))
    window._apply_tool_layout(only_system)
    dialog = _open_dialog(window, qapp)
    _select_tool(dialog.active_list, "system")

    dialog.btn_remove.click()
    qapp.processEvents()

    assert dialog.candidate == only_system
    assert "at least one" in dialog.lbl_error.text().lower()
    assert window.tool_layout == only_system
    assert window.btn_global_stop.isVisibleTo(window)


def test_recovery_controls_cannot_be_hidden_during_active_trial_or_recorder(
        window):
    before = window.tool_layout
    hide_tuning = tool_organizer.remove_tool(before, "tuning")
    window._p1_gain_trial = object()

    with pytest.raises(tool_organizer.ToolOrganizerError, match="Tuning"):
        window._apply_tool_layout(hide_tuning)

    assert window.tool_layout == before
    assert window._nav_button_by_tool_id["tuning"].isVisible()

    window._p1_gain_trial = None
    hide_recorder = tool_organizer.remove_tool(before, "recorder")
    recorder_pending_states = (
        "DISCOVERING_SIGNALS", "CONFIGURING", "WAITING_FOR_TRIGGER",
        "RECORDING", "READY_TO_UPLOAD", "UPLOADING",
        "STALE_CONNECTION_UNKNOWN", "CANCEL_FAILED_UNKNOWN",
        "START_OWNERSHIP_UNKNOWN", "RECOVERY_REQUIRED_UNKNOWN",
        "UNKNOWN: injected state",
    )
    for state in recorder_pending_states:
        window._recorder_ui_state = state
        assert window._recorder_state_pending()
        with pytest.raises(tool_organizer.ToolOrganizerError,
                           match="Recorder"):
            window._apply_tool_layout(hide_recorder)
        assert window.tool_layout == before
        assert window._nav_button_by_tool_id["recorder"].isVisible()

    window._recorder_ui_state = "IDLE"
    hide_motion = tool_organizer.remove_tool(before, "motion")
    window._motion_inflight = True

    with pytest.raises(tool_organizer.ToolOrganizerError, match="Motion"):
        window._apply_tool_layout(hide_motion)

    assert window.tool_layout == before
    assert window._nav_button_by_tool_id["motion"].isVisible()


def test_hidden_navigation_action_cannot_be_programmatically_triggered(
        window, qapp):
    window._apply_tool_layout(
        tool_organizer.remove_tool(window.tool_layout, "motion"))
    assert window.stack.currentIndex() == 1

    for action in window.app_menu_actions_by_operation["nav.motion"]:
        action.trigger()
    qapp.processEvents()

    assert window.stack.currentIndex() == 1
    assert not window._nav_button_by_tool_id["motion"].isVisible()


def test_hidden_recorder_blocks_file_open_before_dialog_or_drive_discovery(
        window, qapp, monkeypatch):
    window._apply_tool_layout(
        tool_organizer.remove_tool(window.tool_layout, "recorder"))
    before_index = window.stack.currentIndex()
    file_dialog_calls = []

    def forbidden_file_dialog(*args, **kwargs):
        file_dialog_calls.append((args, kwargs))
        return "should-not-open.json", ""

    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getOpenFileName", forbidden_file_dialog)
    window.app_menu_actions["recorder.workspace.open"].trigger()
    qapp.processEvents()

    assert file_dialog_calls == []
    assert window.stack.currentIndex() == before_index
    assert not window._nav_button_by_tool_id["recorder"].isVisible()


def test_cancel_discards_staged_changes(window, qapp):
    before = window.tool_layout
    dialog = _open_dialog(window, qapp)
    _select_tool(dialog.active_list, "feedback")
    dialog.btn_remove.click()
    assert dialog.candidate != before

    dialog.btn_cancel.click()
    qapp.processEvents()

    assert window.tool_layout == before
    assert window._nav_button_by_tool_id["feedback"].isVisible()


def test_open_while_visible_reuses_one_modeless_dialog(window, qapp):
    first = _open_dialog(window, qapp)
    window.app_menu_actions["ui.tool_organizer"].trigger()
    qapp.processEvents()

    assert window.tool_organizer_dialog is first
    assert first.isVisible()
    assert not first.isModal()


def test_repeated_cancel_reuses_dialog_and_resets_detached_draft(window, qapp):
    for _ in range(5):
        dialog = _open_dialog(window, qapp)
        _select_tool(dialog.active_list, "feedback")
        dialog.btn_remove.click()
        assert "feedback" not in dialog.candidate.active
        dialog.btn_cancel.click()
        qapp.processEvents()

    dialogs = window.findChildren(app_main.ToolOrganizerDialog)
    assert len(dialogs) == 1
    reopened = _open_dialog(window, qapp)
    assert reopened is dialogs[0]
    assert reopened.candidate == window.tool_layout
    assert "feedback" in reopened.candidate.active


def test_repeated_apply_reuses_one_dialog_instance(window, qapp):
    for _ in range(3):
        dialog = _open_dialog(window, qapp)
        _select_tool(dialog.active_list, "feedback")
        dialog.btn_remove.click()
        dialog.btn_apply.click()
        qapp.processEvents()

        dialog = _open_dialog(window, qapp)
        _select_tool(dialog.hidden_list, "feedback")
        dialog.btn_add.click()
        dialog.btn_apply.click()
        qapp.processEvents()

    assert len(window.findChildren(app_main.ToolOrganizerDialog)) == 1
    assert "feedback" in window.tool_layout.active


def test_default_dialog_position_does_not_cover_connection_or_safety_escape(
        window, qapp):
    dialog = _open_dialog(window, qapp)
    dialog_rect = dialog.frameGeometry()
    # EAS-structure: the connection SETTINGS (access mode / type / port) moved
    # to the System page; only the header Connect button stays always visible.
    protected = (
        window.btn_conn,
        window.btn_global_stop,
        window.lbl_persistence_badge,
        window.lbl_state,
        *window.app_menu_buttons.values(),
    )

    for widget in protected:
        origin = widget.mapToGlobal(QtCore.QPoint(0, 0))
        widget_rect = QtCore.QRect(origin, widget.size())
        assert not dialog_rect.intersects(widget_rect), (
            widget.objectName() or widget.text(), dialog_rect, widget_rect)


def test_render_exception_rolls_back_visuals_index_and_model(
        window, monkeypatch):
    before_layout = window.tool_layout
    before_index = window.stack.currentIndex()
    before_authority = (
        window._telemetry_authoritative,
        window._connection_admitted,
        window._last_mo,
    )
    before_order = tuple(sorted(
        tool_organizer.CANONICAL_TOOL_IDS,
        key=lambda tool_id: window._workspace_nav_layout.indexOf(
            window._nav_button_by_tool_id[tool_id])))
    original_render = window._render_tool_layout
    calls = {"count": 0}

    def flaky_render(layout, **kwargs):
        calls["count"] += 1
        for tool_id in tool_organizer.CANONICAL_TOOL_IDS:
            window._workspace_nav_layout.removeWidget(
                window._nav_button_by_tool_id[tool_id])
        for position, tool_id in enumerate(reversed(
                tool_organizer.CANONICAL_TOOL_IDS)):
            window._workspace_nav_layout.insertWidget(
                position, window._nav_button_by_tool_id[tool_id])
        window.stack.setCurrentIndex(7)
        window._nav_button_by_tool_id["feedback"].setVisible(False)
        for action in window.app_menu_actions_by_operation["nav.feedback"]:
            action.setVisible(False)
        raise RuntimeError("injected render mutation")

    monkeypatch.setattr(window, "_render_tool_layout", flaky_render)
    candidate = tool_organizer.remove_tool(before_layout, "feedback")

    with pytest.raises(tool_organizer.ToolOrganizerError,
                       match="not applied"):
        window._apply_tool_layout(candidate)

    assert calls["count"] == 1
    assert window.tool_layout == before_layout
    assert window.stack.currentIndex() == before_index
    assert tuple(sorted(
        tool_organizer.CANONICAL_TOOL_IDS,
        key=lambda tool_id: window._workspace_nav_layout.indexOf(
            window._nav_button_by_tool_id[tool_id]))) == before_order
    assert window._nav_button_by_tool_id["feedback"].isVisible()
    assert all(action.isVisible() for action in
               window.app_menu_actions_by_operation["nav.feedback"])
    assert (
        window._telemetry_authoritative,
        window._connection_admitted,
        window._last_mo,
    ) == before_authority
