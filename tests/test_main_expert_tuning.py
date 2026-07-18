"""Offline authority regressions for the Expert Tuning presentation.

These tests never construct ``DriveWorker`` or an ``ElmoLink``.  They exercise
only the Qt presentation boundary so a computed candidate cannot be mistaken
for a gain read back from the drive.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtGui, QtWidgets

import main as app_main
import theme as amber_theme
import theme_angrybirds
import theme_qdd


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch):
    monkeypatch.setattr(app_main, "list_serial_ports", lambda: ["COM_OFFLINE"])
    win = app_main.MainWindow()
    win._dump_autotune_result = lambda _result: None
    win._dump_velpos_result = lambda _result: None
    yield win
    win.worker = None
    win.close()
    qapp.processEvents()


def test_candidate_and_installed_gain_readback_remain_distinct(window):
    """A later drive readback must not erase the just-computed candidates."""
    p1 = app_main.autotune_current.AutotuneResult(
        status=app_main.autotune_current.GREEN,
        r_pp_ohm=0.139,
        l_pp_h=41.6e-6,
        kp_v_per_a=0.0857,
        ki_hz=782.5188,
        pm_deg=63.2,
    )
    p2 = app_main.autotune_velpos.AutotuneVPResult(
        status=app_main.autotune_velpos.GREEN,
        k_a=1234.5,
        b_visc=2.5e-6,
        i_c=0.42,
        kp_vel=0.0002,
        ki_vel_hz=10.7,
        kp_pos=85.2114,
        pm_vel_deg=64.0,
        pm_pos_deg=58.0,
    )

    window._on_autotune_result(p1)
    window._on_velpos_result(p2)
    candidate_before = {
        key: window.tune_gain_fields[key].text()
        for key in ("kp_cur", "ki_cur", "kp_vel", "ki_vel", "kp_pos")
    }

    window._on_tuning_gains({
        "kp_cur": 1.1111,
        "ki_cur": 2.2222,
        "kp_vel": 3.3333,
        "ki_vel": 4.4444,
        "kp_pos": 5.5555,
    })

    assert {
        key: window.tune_gain_fields[key].text()
        for key in candidate_before
    } == candidate_before
    assert "0.0857" in candidate_before["kp_cur"]
    assert "0.0002" in candidate_before["kp_vel"]
    assert window.tune_installed_gain_fields["kp_cur"].text() == "1.1111 V/A"
    assert window.tune_installed_gain_fields["ki_cur"].text() == "2.2222 Hz"
    assert (
        window.tune_installed_gain_fields["kp_vel"].text()
        == "3.3333 A/(cnt/s)"
    )
    assert window.tune_installed_gain_fields["ki_vel"].text() == "4.4444 Hz"
    assert window.tune_installed_gain_fields["kp_pos"].text() == "5.5555 1/s"

    assert "CANDIDATE" in window.tune_candidate_title.text()
    assert "INSTALLED" in window.tune_installed_title.text()
    assert "DRIVE READBACK" in window.tune_installed_title.text()
    assert all(
        "CANDIDATE" in label.text()
        for label in window.tune_candidate_gain_labels.values()
    )
    assert all(
        "INSTALLED / DRIVE READBACK" in label.text()
        for label in window.tune_installed_gain_labels.values()
    )


def test_offline_expert_mode_switch_and_edit_create_no_worker(
        window, monkeypatch):
    created = []

    def forbidden_worker(*args, **kwargs):
        created.append((args, kwargs))
        raise AssertionError("offline Expert UI must not construct DriveWorker")

    monkeypatch.setattr(app_main, "DriveWorker", forbidden_worker)

    window._set_tuning_mode("quick")
    assert window.expert_lab_frame.isHidden()
    window._show_tuning_mode("expert")
    window.cmb_ba_cap.setCurrentIndex(1)
    window.cmb_ba_cap.setCurrentIndex(0)

    assert window._tuning_mode == "expert"
    assert not window.expert_lab_frame.isHidden()
    assert (
        window.expert_lab_title.text()
        == "EXPERT CANDIDATE LAB v2 · OFFLINE MODEL · NO DRIVE I/O"
    )
    assert "HARDWARE TUNING CONTROLS" in window.expert_hardware_title.text()
    assert window.worker is None
    assert created == []


def test_offline_expert_candidate_populates_model_only(
        window, qapp, monkeypatch):
    """Explicit SI-derived inputs update candidates and chart, never readback."""
    created = []

    def forbidden_constructor(*args, **kwargs):
        created.append((args, kwargs))
        raise AssertionError("offline candidate calculation must not create I/O")

    monkeypatch.setattr(app_main, "DriveWorker", forbidden_constructor)
    monkeypatch.setattr(app_main, "ElmoLink", forbidden_constructor)
    installed_before = {}
    for index, (key, field) in enumerate(
            window.tune_installed_gain_fields.items(), start=1):
        field.setText("INSTALLED-SENTINEL-%d" % index)
        installed_before[key] = field.text()

    window._show_tuning_mode("expert")
    window.expert_lab_r_ohm.setText("0.139")
    window.expert_lab_l_uh.setText("41.6")
    window.expert_lab_ts_us.setText("100")
    window.expert_lab_bandwidth_hz.setText("1200")
    window.expert_lab_ki_rule.setCurrentIndex(
        window.expert_lab_ki_rule.findData("eas_ratio"))
    window.btn_expert_calculate.click()
    qapp.processEvents()

    assert window._tuning_mode == "expert"
    assert not window.expert_lab_frame.isHidden()
    assert window.worker is None
    assert created == []
    assert window._expert_candidate.model_status == "MODEL"
    assert window._expert_candidate.basis == "phase-to-phase"
    assert len(window._expert_response.frequency_hz) == 401
    assert window.expert_bode_widget.response is window._expert_response
    assert window.tune_gain_fields["r_pp"].text() == "0.139 ohm"
    assert window.tune_gain_fields["l_pp"].text() == "41.6 uH"
    assert "V/A" in window.tune_gain_fields["kp_cur"].text()
    assert "Hz" in window.tune_gain_fields["ki_cur"].text()
    assert "deg" in window.tune_gain_fields["pm"].text()
    assert {
        key: field.text()
        for key, field in window.tune_installed_gain_fields.items()
    } == installed_before
    summary = window.expert_lab_status.text()
    assert "MODEL" in summary
    assert "phase-to-phase" in summary
    assert "crossover" in summary
    assert "PM" in summary
    assert "design gate" in summary
    assert "401" in window.expert_lab_response_summary.text()
    preview = QtGui.QPixmap(800, 180)
    window.expert_bode_widget.resize(800, 180)
    window.expert_bode_widget.render(preview)
    assert not preview.isNull()


@pytest.mark.parametrize("invalid_value", ["nan", "inf", "-1", "0"])
def test_offline_expert_invalid_input_preserves_prior_candidate(
        window, qapp, invalid_value):
    """Invalid/non-finite plant input fails closed without erasing evidence."""
    window._show_tuning_mode("expert")
    window.expert_lab_r_ohm.setText("0.139")
    window.expert_lab_l_uh.setText("41.6")
    window.expert_lab_ts_us.setText("100")
    window.expert_lab_bandwidth_hz.clear()
    window.btn_expert_calculate.click()
    qapp.processEvents()
    candidate_before = window._expert_candidate
    response_before = window._expert_response
    fields_before = {
        key: window.tune_gain_fields[key].text()
        for key in ("r_pp", "l_pp", "kp_cur", "ki_cur", "pm")
    }

    window.expert_lab_l_uh.setText(invalid_value)
    window.btn_expert_calculate.click()
    qapp.processEvents()

    assert window._expert_candidate is candidate_before
    assert window._expert_response is response_before
    assert window.expert_bode_widget.response is response_before
    assert {
        key: window.tune_gain_fields[key].text()
        for key in fields_before
    } == fields_before
    assert "INVALID" in window.expert_lab_status.text()


def test_offline_expert_mode_switch_and_calculate_enqueue_no_job(
        window, qapp, monkeypatch):
    """Mode selection and pure MODEL calculation have no worker/job side effect."""
    created = []

    def forbidden_constructor(*args, **kwargs):
        created.append((args, kwargs))
        raise AssertionError("offline Expert UI must not construct transport")

    monkeypatch.setattr(app_main, "DriveWorker", forbidden_constructor)
    monkeypatch.setattr(app_main, "ElmoLink", forbidden_constructor)
    window._show_tuning_mode("expert")
    window.expert_lab_r_ohm.setText("0.2")
    window.expert_lab_l_uh.setText("80")
    window.expert_lab_ts_us.setText("100")
    window.expert_lab_bandwidth_hz.clear()
    window.expert_lab_ki_rule.setCurrentIndex(
        window.expert_lab_ki_rule.findData("pole_zero"))
    window.btn_expert_calculate.click()
    qapp.processEvents()

    assert window.worker is None
    assert created == []
    assert window._expert_candidate.source == "AUTO_CALIBRATED_MODEL"


def _calculate_current_model(window, qapp):
    window._show_tuning_mode("expert")
    window._set_expert_lab_step("current")
    window.expert_lab_r_ohm.setText("0.139")
    window.expert_lab_l_uh.setText("41.6")
    window.expert_lab_ts_us.setText("100")
    window.expert_lab_bandwidth_hz.clear()
    window.expert_lab_ki_rule.setCurrentIndex(
        window.expert_lab_ki_rule.findData("eas_ratio"))
    window.btn_expert_calculate.click()
    qapp.processEvents()
    assert window._expert_candidate is not None


def test_offline_expert_p2_requires_a_complete_current_model(
        window, qapp):
    window._show_tuning_mode("expert")
    window._set_expert_lab_step("vp")
    window.expert_vp_ka.setText("5.794e6")
    window.expert_vp_b_visc.setText("1e-7")

    window.btn_expert_vp_calculate.click()
    qapp.processEvents()

    assert window._expert_vp_plant is None
    assert window._expert_vp_candidate is None
    assert "INVALID" in window.expert_vp_status.text()
    assert "Current" in window.expert_vp_status.text()
    assert all(
        field.text() == "—"
        for field in window.expert_vp_result_fields.values())


def test_offline_expert_p2_populates_model_only_and_preserves_all_authority(
        window, qapp, monkeypatch):
    created = []

    def forbidden_constructor(*args, **kwargs):
        created.append((args, kwargs))
        raise AssertionError("offline P2 must not construct transport")

    monkeypatch.setattr(app_main, "DriveWorker", forbidden_constructor)
    monkeypatch.setattr(app_main, "ElmoLink", forbidden_constructor)
    _calculate_current_model(window, qapp)
    installed_before = {}
    for index, (key, field) in enumerate(
            window.tune_installed_gain_fields.items(), start=1):
        field.setText("INSTALLED-P2-SENTINEL-%d" % index)
        installed_before[key] = field.text()
    verify_enabled_before = window.btn_tune_verify.isEnabled()

    window._set_expert_lab_step("vp")
    window.expert_vp_ka.setText("5.794e6")
    window.expert_vp_b_visc.setText("1e-7")
    window.btn_expert_vp_calculate.click()
    qapp.processEvents()

    candidate = window._expert_vp_candidate
    assert window.worker is None
    assert created == []
    assert candidate.model_status == "MODEL"
    assert candidate.kp_vel_a_per_cnt_s == pytest.approx(7.896e-5, rel=1e-3)
    assert candidate.ki_vel_hz == pytest.approx(10.7, rel=1e-3)
    assert candidate.kp_pos_per_s == pytest.approx(85.211, rel=1e-3)
    assert candidate.loop_model_passed
    assert "MODEL GATE PASS" in window.expert_vp_status.text()
    assert "SINGLE-POINT" in window.expert_vp_status.text()
    assert "FILTER NEED-DATA" in window.expert_vp_status.text()
    assert "GS[2]=0 ONLY" in window.expert_vp_status.text()
    assert "A_peak/(cnt/s)" in window.expert_vp_result_fields["kp_vel"].text()
    assert "Hz" in window.expert_vp_result_fields["ki_vel"].text()
    assert "1/s" in window.expert_vp_result_fields["kp_pos"].text()
    assert "dB" in window.expert_vp_result_fields["pm_vel"].text()
    assert "deg" in window.expert_vp_result_fields["pm_pos"].text()
    assert "excluded" in window.tune_gain_fields["i_c"].text()
    assert window._vp_result is None
    assert not window.btn_tune_vp_apply.isEnabled()
    assert not window.btn_tune_vp_save.isEnabled()
    assert window.btn_tune_verify.isEnabled() == verify_enabled_before
    assert {
        key: field.text()
        for key, field in window.tune_installed_gain_fields.items()
    } == installed_before


@pytest.mark.parametrize("invalid", ("nan", "inf", "-1", "0"))
def test_offline_expert_p2_invalid_input_preserves_previous_complete_model(
        window, qapp, invalid):
    _calculate_current_model(window, qapp)
    window._set_expert_lab_step("vp")
    window.expert_vp_ka.setText("5.794e6")
    window.expert_vp_b_visc.setText("1e-7")
    window.btn_expert_vp_calculate.click()
    qapp.processEvents()
    candidate_before = window._expert_vp_candidate
    fields_before = {
        key: field.text()
        for key, field in window.expert_vp_result_fields.items()
    }

    window.expert_vp_ka.setText(invalid)
    window.btn_expert_vp_calculate.click()
    qapp.processEvents()

    assert window._expert_vp_candidate is candidate_before
    assert {
        key: field.text()
        for key, field in window.expert_vp_result_fields.items()
    } == fields_before
    assert "INVALID" in window.expert_vp_status.text()


def test_new_current_model_invalidates_dependent_offline_p2(
        window, qapp):
    _calculate_current_model(window, qapp)
    window._set_expert_lab_step("vp")
    window.expert_vp_ka.setText("5.794e6")
    window.expert_vp_b_visc.setText("1e-7")
    window.btn_expert_vp_calculate.click()
    qapp.processEvents()
    assert window._expert_vp_candidate is not None

    window._set_expert_lab_step("current")
    window.expert_lab_r_ohm.setText("0.15")
    window.btn_expert_calculate.click()
    qapp.processEvents()

    assert window._expert_vp_plant is None
    assert window._expert_vp_candidate is None
    assert all(
        field.text() == "—"
        for field in window.expert_vp_result_fields.values())
    assert "calculate after Current" in window.expert_vp_status.text()


def test_editing_current_inputs_marks_p1_stale_and_invalidates_p2(
        window, qapp):
    _calculate_current_model(window, qapp)
    current_before = window._expert_candidate
    window._set_expert_lab_step("vp")
    window.expert_vp_ka.setText("5.794e6")
    window.expert_vp_b_visc.setText("1e-7")
    window.btn_expert_vp_calculate.click()
    qapp.processEvents()
    assert window._expert_vp_candidate is not None

    window._set_expert_lab_step("current")
    window.expert_lab_r_ohm.setText("0.15")
    window.expert_lab_r_ohm.textEdited.emit("0.15")
    qapp.processEvents()

    assert window._expert_candidate is current_before
    assert window._expert_current_inputs_stale is True
    assert "STALE" in window.expert_lab_status.text()
    assert window._expert_vp_candidate is None
    assert "STALE" in window.expert_vp_status.text()
    assert all(
        field.text() == "—"
        for field in window.expert_vp_result_fields.values())


def test_editing_p2_inputs_marks_previous_model_stale_without_erasing_it(
        window, qapp):
    _calculate_current_model(window, qapp)
    window._set_expert_lab_step("vp")
    window.expert_vp_ka.setText("5.794e6")
    window.expert_vp_b_visc.setText("1e-7")
    window.btn_expert_vp_calculate.click()
    qapp.processEvents()
    candidate_before = window._expert_vp_candidate
    fields_before = {
        key: field.text()
        for key, field in window.expert_vp_result_fields.items()
    }

    window.expert_vp_ka.setText("6.0e6")
    window.expert_vp_ka.textEdited.emit("6.0e6")
    qapp.processEvents()

    assert window._expert_vp_candidate is candidate_before
    assert window._expert_vp_inputs_stale is True
    assert "STALE" in window.expert_vp_status.text()
    assert "MODEL GATE PASS" not in window.expert_vp_status.text()
    assert {
        key: field.text()
        for key, field in window.expert_vp_result_fields.items()
    } == fields_before


def test_expert_offline_lab_precedes_hardware_controls(window):
    layout = window.tuning_expert_frame.parentWidget().layout()

    assert layout.indexOf(window.tuning_expert_frame) < (
        layout.indexOf(window.tuning_guided_run_frame))


def test_filter_scheduling_evidence_step_is_local_and_fail_closed(
        window, qapp, monkeypatch):
    created = []

    def forbidden_constructor(*args, **kwargs):
        created.append((args, kwargs))
        raise AssertionError("evidence inspector must not construct transport")

    monkeypatch.setattr(app_main, "DriveWorker", forbidden_constructor)
    monkeypatch.setattr(app_main, "ElmoLink", forbidden_constructor)
    authority_before = {
        "p1": window._expert_candidate,
        "p2": window._expert_vp_candidate,
        "installed": {
            key: field.text()
            for key, field in window.tune_installed_gain_fields.items()
        },
        "vp_result": window._vp_result,
        "dispatch": window._tune_dispatch_inflight,
        "verify_enabled": window.btn_tune_verify.isEnabled(),
    }
    window._show_tuning_mode("expert")
    window._set_expert_lab_step("evidence")
    qapp.processEvents()

    assert window.worker is None
    assert created == []
    assert window.expert_lab_stack.currentWidget() is (
        window.expert_evidence_page)
    assert "DOCUMENTED TOPOLOGY" in window.expert_lab_title.text()
    assert "NO MODEL" in window.expert_lab_title.text()
    assert "OFFLINE MODEL" not in window.expert_lab_title.text()
    assert "no model" in window.expert_lab_note.text().lower()
    assert "P1" not in window.expert_lab_note.text()
    assert "P2" not in window.expert_lab_note.text()
    assert "DOCUMENTED TOPOLOGY" in window.expert_evidence_status.text()
    assert "NO MODEL" in window.expert_evidence_status.text()
    assert "NO EMULATION" in window.expert_evidence_status.text()
    assert "NO WRITE" in window.expert_evidence_status.text()

    window.expert_filter_type.setCurrentIndex(
        window.expert_filter_type.findData(4))
    window.expert_filter_location.setCurrentIndex(
        window.expert_filter_location.findData("scheduled_position"))
    window.expert_schedule_mode.setValue(64)
    qapp.processEvents()

    assert "Notch" in window.expert_filter_type_detail.text()
    assert "Attenuation [dB]" in window.expert_filter_type_detail.text()
    assert "DOCUMENT CONFLICT" in window.expert_filter_location_detail.text()
    assert "KV[45]" in window.expert_filter_location_detail.text()
    assert "KV[50]" in window.expert_filter_location_detail.text()
    assert "SPEED" in window.expert_schedule_mode_detail.text()
    assert "NEED-DATA" in window.expert_schedule_mode_detail.text()
    assert "1..504" in window.expert_evidence_conflicts.text()
    assert "1..945" in window.expert_evidence_conflicts.text()
    assert "DC GAIN" in window.expert_evidence_documented_facts.text()
    assert "MOTOR OFF" in window.expert_evidence_documented_facts.text()
    assert not window.btn_tune_vp_apply.isEnabled()
    assert not window.btn_tune_vp_save.isEnabled()
    assert window._expert_candidate is authority_before["p1"]
    assert window._expert_vp_candidate is authority_before["p2"]
    assert window._vp_result is authority_before["vp_result"]
    assert window._tune_dispatch_inflight is authority_before["dispatch"]
    assert window.btn_tune_verify.isEnabled() == (
        authority_before["verify_enabled"])
    assert {
        key: field.text()
        for key, field in window.tune_installed_gain_fields.items()
    } == authority_before["installed"]
    assert window.worker is None
    assert created == []


def test_expert_v2_steps_fit_1366x820_in_all_skins(
        window, qapp):
    previous_style_sheet = qapp.styleSheet()
    previous_palette = QtGui.QPalette(qapp.palette())
    window.resize(1366, 820)
    window.show()
    window._show_tuning_mode("expert")
    try:
        for themed in (theme_qdd, amber_theme, theme_angrybirds):
            qapp.setStyleSheet(themed.STYLE)
            for step in ("current", "vp", "evidence"):
                window._set_expert_lab_step(step)
                window.resize(1366, 820)
                for _ in range(3):
                    qapp.processEvents()
                assert window.minimumSizeHint().width() <= 1366
                assert (
                    window.workspace_scroll.horizontalScrollBar().maximum()
                    == 0)
                assert window.expert_lab_note.height() >= (
                    window.expert_lab_note.sizeHint().height())
                if step == "vp":
                    assert window.expert_vp_basis.height() >= (
                        window.expert_vp_basis.sizeHint().height())
    finally:
        qapp.setPalette(previous_palette)
        qapp.setStyleSheet(previous_style_sheet)
