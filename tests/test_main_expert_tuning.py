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


def test_expert_page_status_step_is_local_and_authority_preserving(
        window, qapp, monkeypatch):
    created = []

    def forbidden_constructor(*args, **kwargs):
        created.append((args, kwargs))
        raise AssertionError("page-status inspector must not construct transport")

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
        "apply_enabled": window.btn_tune_vp_apply.isEnabled(),
        "save_enabled": window.btn_tune_vp_save.isEnabled(),
    }

    window._show_tuning_mode("expert")
    window._set_expert_lab_step("status")
    qapp.processEvents()

    assert window.worker is None
    assert created == []
    assert window.expert_lab_stack.currentWidget() is (
        window.expert_page_status_page)
    assert "LOCAL STATUS ONLY" in window.expert_lab_title.text()
    assert "NO DRIVE I/O" in window.expert_lab_title.text()
    assert "NOT EAS ENTER/APPLY STATE" in (
        window.expert_page_status_banner.text())
    assert "NOT INSTALLED" in window.expert_page_status_banner.text()
    assert "OVERALL PARTIAL" in window.expert_page_status_overall.text()
    assert "MISSING" in window.expert_page_status_rows["current"].text()
    assert "BLOCKED" in window.expert_page_status_rows["vp"].text()
    assert "DOCUMENTED PARTIAL" in (
        window.expert_page_status_rows["evidence"].text())
    rendered = " ".join(
        label.text() for label in window.expert_page_status_rows.values())
    assert "READY" not in rendered
    assert "APPLIED" not in rendered
    assert window._expert_candidate is authority_before["p1"]
    assert window._expert_vp_candidate is authority_before["p2"]
    assert window._vp_result is authority_before["vp_result"]
    assert window._tune_dispatch_inflight is authority_before["dispatch"]
    assert window.btn_tune_verify.isEnabled() == (
        authority_before["verify_enabled"])
    assert window.btn_tune_vp_apply.isEnabled() == (
        authority_before["apply_enabled"])
    assert window.btn_tune_vp_save.isEnabled() == (
        authority_before["save_enabled"])
    assert {
        key: field.text()
        for key, field in window.tune_installed_gain_fields.items()
    } == authority_before["installed"]


def test_expert_page_status_tracks_current_and_stale_models(
        window, qapp):
    _calculate_current_model(window, qapp)
    window._set_expert_lab_step("vp")
    window.expert_vp_ka.setText("5.794e6")
    window.expert_vp_b_visc.setText("1e-7")
    window.btn_expert_vp_calculate.click()
    qapp.processEvents()
    p1_before = window._expert_candidate
    p2_before = window._expert_vp_candidate

    window._set_expert_lab_step("status")
    qapp.processEvents()
    assert "CURRENT LOCAL MODEL" in (
        window.expert_page_status_rows["current"].text())
    assert "CURRENT LOCAL MODEL" in (
        window.expert_page_status_rows["vp"].text())
    assert "NOT INSTALLED" in (
        window.expert_page_status_rows["current"].text())
    assert "NOT INSTALLED" in (
        window.expert_page_status_rows["vp"].text())

    window._set_expert_lab_step("vp")
    window.expert_vp_ka.setText("5.8e6")
    window.expert_vp_ka.textEdited.emit("5.8e6")
    window._set_expert_lab_step("status")
    qapp.processEvents()

    assert window._expert_candidate is p1_before
    assert window._expert_vp_candidate is p2_before
    assert "CURRENT LOCAL MODEL" in (
        window.expert_page_status_rows["current"].text())
    assert "STALE" in window.expert_page_status_rows["vp"].text()


def test_expert_page_status_defers_hidden_reclassification_until_opened(
        window, qapp, monkeypatch):
    _calculate_current_model(window, qapp)
    window._set_expert_lab_step("vp")
    window.expert_vp_ka.setText("5.794e6")
    window.expert_vp_b_visc.setText("1e-7")
    window.btn_expert_vp_calculate.click()
    qapp.processEvents()

    original = (
        app_main.expert_tuning_offline.design_velocity_position_candidate)
    calls = []

    def counted(plant):
        calls.append(plant)
        return original(plant)

    monkeypatch.setattr(
        app_main.expert_tuning_offline,
        "design_velocity_position_candidate",
        counted,
    )
    window.expert_vp_ka.setText("5.8e6")
    window.expert_vp_ka.textEdited.emit("5.8e6")
    qapp.processEvents()

    assert window.expert_lab_stack.currentIndex() == 1
    assert window._expert_page_status_dirty is True
    assert calls == []

    window._set_expert_lab_step("status")
    qapp.processEvents()

    assert len(calls) == 1
    assert window._expert_page_status_dirty is False
    assert "STALE" in window.expert_page_status_rows["vp"].text()


def test_expert_user_units_documented_formula_preview_is_blank_and_zero_io(
        window, qapp, monkeypatch):
    created = []

    def forbidden_constructor(*args, **kwargs):
        created.append((args, kwargs))
        raise AssertionError(
            "documented User Units preview must not construct transport")

    monkeypatch.setattr(app_main, "DriveWorker", forbidden_constructor)
    monkeypatch.setattr(app_main, "ElmoLink", forbidden_constructor)
    monkeypatch.setattr(
        window, "_claim_tune_dispatch", forbidden_constructor)
    window._axis_summary_data = {
        "raw": {
            "CA[18]": 98765,
            "FC[1]": 123,
            "FC[2]": 456,
            "FC[5]": 7,
            "FC[6]": 8,
            "FC[7]": 9,
            "FC[8]": 10,
        },
    }
    window._ca18 = 98765
    authority_before = {
        "p1": window._expert_candidate,
        "p2": window._expert_vp_candidate,
        "evidence": window._expert_evidence,
        "page_status": window._expert_page_status_snapshot,
        "installed": {
            key: field.text()
            for key, field in window.tune_installed_gain_fields.items()
        },
        "vp_result": window._vp_result,
        "dispatch": window._tune_dispatch_inflight,
        "verify_enabled": window.btn_tune_verify.isEnabled(),
        "apply_enabled": window.btn_tune_vp_apply.isEnabled(),
        "save_enabled": window.btn_tune_vp_save.isEnabled(),
    }

    window._show_tuning_mode("expert")
    window._set_expert_lab_step("user_units")
    qapp.processEvents()

    assert window.expert_lab_stack.currentWidget() is (
        window.expert_user_units_page)
    assert all(
        field.text() == ""
        for field in window.expert_user_units_fc_fields.values())
    assert window.expert_user_units_unit_label.text() == ""
    assert window.expert_user_units_sample_counts.text() == ""
    assert window.worker is None
    assert created == []
    rendered = " ".join((
        window.expert_lab_title.text(),
        window.expert_lab_note.text(),
        window.expert_user_units_banner.text(),
        window.expert_user_units_status.text(),
    )).upper()
    for boundary in (
            "EXPLICIT MANUAL INPUT",
            "DOCUMENTED FORMULA",
            "PARTIAL",
            "NOT CURRENT DRIVE CONFIG",
            "NO FC/OF WRITE",
            "NO DRIVE I/O"):
        assert boundary in rendered
    assert "DOCUMENTED GROUPING MISMATCH" in rendered
    assert "PURPOSE NEED-DATA" in rendered
    assert window._expert_candidate is authority_before["p1"]
    assert window._expert_vp_candidate is authority_before["p2"]
    assert window._expert_evidence is authority_before["evidence"]
    assert window._expert_page_status_snapshot is (
        authority_before["page_status"])
    assert window._vp_result is authority_before["vp_result"]
    assert window._tune_dispatch_inflight is authority_before["dispatch"]
    assert window.btn_tune_verify.isEnabled() == (
        authority_before["verify_enabled"])
    assert window.btn_tune_vp_apply.isEnabled() == (
        authority_before["apply_enabled"])
    assert window.btn_tune_vp_save.isEnabled() == (
        authority_before["save_enabled"])
    assert {
        key: field.text()
        for key, field in window.tune_installed_gain_fields.items()
    } == authority_before["installed"]


def _fill_expert_user_units_golden(window, *, sample_counts="100"):
    for key, value in {
            "fc1": "10000",
            "fc2": "1",
            "fc5": "1",
            "fc6": "1",
            "fc7": "1000",
            "fc8": "10",
    }.items():
        window.expert_user_units_fc_fields[key].setText(value)
    window.expert_user_units_unit_label.setText("µm")
    window.expert_user_units_sample_counts.setText(sample_counts)


def test_expert_user_units_preview_click_is_authority_and_io_isolated(
        window, qapp, monkeypatch):
    _calculate_current_model(window, qapp)
    window._set_expert_lab_step("vp")
    window.expert_vp_ka.setText("5.794e6")
    window.expert_vp_b_visc.setText("1e-7")
    window.btn_expert_vp_calculate.click()
    window._set_expert_lab_step("status")
    qapp.processEvents()
    window._set_expert_lab_step("user_units")
    _fill_expert_user_units_golden(window)

    for index, field in enumerate(
            window.tune_installed_gain_fields.values(), start=1):
        field.setText("INSTALLED-SENTINEL-%d" % index)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError(
            "User Units Preview click must not enter an I/O/dispatch path")

    class PoisonWorker:
        def __getattr__(self, name):
            def forbidden_worker_call(*args, **kwargs):
                calls.append((name, args, kwargs))
                raise AssertionError(
                    "User Units Preview click touched connected worker.%s"
                    % name)

            return forbidden_worker_call

    poison_worker = PoisonWorker()
    window.worker = poison_worker
    tuning_buttons = (
        window.btn_tune,
        window.btn_tune_signature,
        window.btn_tune_vp,
        window.btn_tune_abort,
        window.btn_tune_verify,
        window.btn_tune_apply,
        window.btn_tune_p1_restore,
        window.btn_tune_p1_save,
        window.btn_tune_vp_apply,
        window.btn_tune_vp_restore,
        window.btn_tune_vp_save,
    )
    authority_before = {
        "p1_plant": window._expert_plant,
        "p1": window._expert_candidate,
        "p2_plant": window._expert_vp_plant,
        "p2": window._expert_vp_candidate,
        "evidence": window._expert_evidence,
        "page_status": window._expert_page_status_snapshot,
        "at_result": window._at_result,
        "at_result_generation": window._at_result_generation,
        "vp_result": window._vp_result,
        "vp_result_generation": window._vp_result_generation,
        "p1_trial": window._p1_gain_trial,
        "p1_trial_generation": window._p1_trial_generation,
        "vp_trial": window._vp_gain_trial,
        "vp_trial_generation": window._vp_trial_generation,
        "vp_signature_run": window._vp_signature_run,
        "vp_trial_verified_green": window._vp_trial_verified_green,
        "vp_verified_trial": window._vp_verified_trial,
        "vp_verified_generation": window._vp_verified_generation,
        "verify_trial_inflight": window._verify_trial_inflight,
        "authority_generation": window._tuning_authority_generation,
        "dispatch": window._tune_dispatch_inflight,
        "dispatch_generation": window._tune_dispatch_generation,
        "button_enabled": tuple(
            button.isEnabled() for button in tuning_buttons),
        "installed": {
            key: field.text()
            for key, field in window.tune_installed_gain_fields.items()
        },
    }
    monkeypatch.setattr(app_main, "DriveWorker", forbidden)
    monkeypatch.setattr(app_main, "ElmoLink", forbidden)
    monkeypatch.setattr(window, "_claim_tune_dispatch", forbidden)

    window.btn_expert_user_units_preview.click()
    qapp.processEvents()

    assert window._expert_user_units_preview is not None
    assert calls == []
    assert window.worker is poison_worker
    assert window._expert_plant is authority_before["p1_plant"]
    assert window._expert_candidate is authority_before["p1"]
    assert window._expert_vp_plant is authority_before["p2_plant"]
    assert window._expert_vp_candidate is authority_before["p2"]
    assert window._expert_evidence is authority_before["evidence"]
    assert window._expert_page_status_snapshot is (
        authority_before["page_status"])
    assert window._at_result is authority_before["at_result"]
    assert window._at_result_generation is (
        authority_before["at_result_generation"])
    assert window._vp_result is authority_before["vp_result"]
    assert window._vp_result_generation is (
        authority_before["vp_result_generation"])
    assert window._p1_gain_trial is authority_before["p1_trial"]
    assert window._p1_trial_generation is (
        authority_before["p1_trial_generation"])
    assert window._vp_gain_trial is authority_before["vp_trial"]
    assert window._vp_trial_generation is (
        authority_before["vp_trial_generation"])
    assert window._vp_signature_run is authority_before["vp_signature_run"]
    assert window._vp_trial_verified_green is (
        authority_before["vp_trial_verified_green"])
    assert window._vp_verified_trial is authority_before["vp_verified_trial"]
    assert window._vp_verified_generation is (
        authority_before["vp_verified_generation"])
    assert window._verify_trial_inflight is (
        authority_before["verify_trial_inflight"])
    assert window._tuning_authority_generation == (
        authority_before["authority_generation"])
    assert window._tune_dispatch_inflight is authority_before["dispatch"]
    assert window._tune_dispatch_generation is (
        authority_before["dispatch_generation"])
    assert tuple(
        button.isEnabled() for button in tuning_buttons
    ) == authority_before["button_enabled"]
    assert {
        key: field.text()
        for key, field in window.tune_installed_gain_fields.items()
    } == authority_before["installed"]


def test_expert_user_units_late_axis_summary_never_autofills_inputs(
        window, qapp):
    window._set_expert_lab_step("user_units")
    assert all(
        field.text() == ""
        for field in window.expert_user_units_fc_fields.values())

    window._on_axis_summary({
        "scope": "LAST OBSERVED",
        "mode": "UM=5",
        "feedback_routing": "main",
        "raw": {
            "CA[18]": 98765,
            "FC[1]": 123,
            "FC[2]": 456,
            "FC[5]": 7,
            "FC[6]": 8,
            "FC[7]": 9,
            "FC[8]": 10,
        },
    })
    qapp.processEvents()

    assert all(
        field.text() == ""
        for field in window.expert_user_units_fc_fields.values())
    assert window.expert_user_units_unit_label.text() == ""
    assert window.expert_user_units_sample_counts.text() == ""

    _fill_expert_user_units_golden(window)
    window.btn_expert_user_units_preview.click()
    qapp.processEvents()
    preview_before = window._expert_user_units_preview
    inputs_before = {
        key: field.text()
        for key, field in window.expert_user_units_fc_fields.items()
    }
    results_before = {
        key: field.text()
        for key, field in window.expert_user_units_result_fields.items()
    }
    status_before = window.expert_user_units_status.text()

    window._on_axis_summary({
        "scope": "LATER OBSERVED",
        "mode": "UM=1",
        "feedback_routing": "auxiliary",
        "raw": {
            "CA[18]": 55555,
            "FC[1]": 901,
            "FC[2]": 902,
            "FC[5]": 905,
            "FC[6]": 906,
            "FC[7]": 907,
            "FC[8]": 908,
        },
    })
    qapp.processEvents()

    assert window._expert_user_units_preview is preview_before
    assert {
        key: field.text()
        for key, field in window.expert_user_units_fc_fields.items()
    } == inputs_before
    assert {
        key: field.text()
        for key, field in window.expert_user_units_result_fields.items()
    } == results_before
    assert window.expert_user_units_status.text() == status_before


def test_expert_user_units_required_blank_never_uses_an_implicit_value(
        window, qapp):
    window._set_expert_lab_step("user_units")

    window.btn_expert_user_units_preview.click()
    qapp.processEvents()
    assert window._expert_user_units_preview is None
    assert "INVALID" in window.expert_user_units_status.text()
    assert all(
        field.text() == "—"
        for field in window.expert_user_units_result_fields.values())

    _fill_expert_user_units_golden(window)
    window.expert_user_units_fc_fields["fc8"].clear()
    window.btn_expert_user_units_preview.click()
    qapp.processEvents()
    assert window._expert_user_units_preview is None
    assert "FC[8] is required" in window.expert_user_units_status.text()
    assert all(
        field.text() == "—"
        for field in window.expert_user_units_result_fields.values())


@pytest.mark.parametrize(
    "missing_key",
    ("fc1", "fc2", "fc5", "fc6", "fc7", "fc8"),
)
def test_expert_user_units_each_required_fc_rejects_partial_blank(
        window, qapp, missing_key):
    window._set_expert_lab_step("user_units")
    _fill_expert_user_units_golden(window)
    window.expert_user_units_fc_fields[missing_key].clear()

    window.btn_expert_user_units_preview.click()
    qapp.processEvents()

    assert window._expert_user_units_preview is None
    expected_label = "FC[%s]" % missing_key[2:]
    assert "%s is required" % expected_label in (
        window.expert_user_units_status.text())
    assert all(
        field.text() == "—"
        for field in window.expert_user_units_result_fields.values())


def test_expert_user_units_ui_preserves_asymmetric_fc_wiring(
        window, qapp):
    window._set_expert_lab_step("user_units")
    for key, value in {
            "fc1": "2",
            "fc2": "3",
            "fc5": "5",
            "fc6": "7",
            "fc7": "11",
            "fc8": "13",
    }.items():
        window.expert_user_units_fc_fields[key].setText(value)

    window.btn_expert_user_units_preview.click()
    qapp.processEvents()

    assert window._expert_user_units_preview.units_per_count.numerator == 231
    assert window._expert_user_units_preview.units_per_count.denominator == 130
    assert "231 / 130" in (
        window.expert_user_units_result_fields["units_per_count"].text())


def test_expert_user_units_golden_preview_and_edit_stale_contract(
        window, qapp):
    window._show_tuning_mode("expert")
    window._set_expert_lab_step("user_units")
    _fill_expert_user_units_golden(window)
    window.btn_expert_user_units_preview.click()
    qapp.processEvents()

    preview_before = window._expert_user_units_preview
    results_before = {
        key: field.text()
        for key, field in window.expert_user_units_result_fields.items()
    }
    assert preview_before is not None
    assert "DOCUMENTED LOCAL PREVIEW" in (
        window.expert_user_units_status.text())
    assert "PARTIAL" in window.expert_user_units_status.text()
    assert "GROUPING MISMATCH" in window.expert_user_units_status.text()
    assert "1 / 100" in results_before["units_per_count"]
    assert "0.01" in results_before["units_per_count"]
    assert "100" in results_before["counts_per_unit"]
    assert "1" in results_before["sample_units"]
    assert "µm" in results_before["units_per_count"]

    field = window.expert_user_units_fc_fields["fc7"]
    field.setText("2000")
    field.textEdited.emit("2000")
    qapp.processEvents()

    assert window._expert_user_units_preview is preview_before
    assert window._expert_user_units_inputs_stale is True
    assert "STALE" in window.expert_user_units_status.text()
    assert "NOT CURRENT DRIVE CONFIG" in (
        window.expert_user_units_status.text())
    assert {
        key: item.text()
        for key, item in window.expert_user_units_result_fields.items()
    } == results_before


@pytest.mark.parametrize(
    ("field_name", "new_text"),
    (
        ("unit_label", "mm"),
        ("sample_counts", "-200"),
    ),
)
def test_expert_user_units_label_and_sample_edits_mark_preview_stale(
        window, qapp, field_name, new_text):
    window._set_expert_lab_step("user_units")
    _fill_expert_user_units_golden(window)
    window.btn_expert_user_units_preview.click()
    qapp.processEvents()
    preview_before = window._expert_user_units_preview
    results_before = {
        key: field.text()
        for key, field in window.expert_user_units_result_fields.items()
    }
    field = {
        "unit_label": window.expert_user_units_unit_label,
        "sample_counts": window.expert_user_units_sample_counts,
    }[field_name]

    field.setText(new_text)
    field.textEdited.emit(new_text)
    qapp.processEvents()

    assert window._expert_user_units_preview is preview_before
    assert window._expert_user_units_inputs_stale is True
    assert "STALE" in window.expert_user_units_status.text()
    assert {
        key: item.text()
        for key, item in window.expert_user_units_result_fields.items()
    } == results_before


def test_expert_user_units_ui_preserves_signed_sample_direction(
        window, qapp):
    window._set_expert_lab_step("user_units")
    _fill_expert_user_units_golden(window, sample_counts="-100")
    window.btn_expert_user_units_preview.click()
    qapp.processEvents()

    assert window._expert_user_units_preview.sample_units.numerator == -1
    assert "-100 count = -1 = -1 µm" in (
        window.expert_user_units_result_fields["sample_units"].text())

    window.expert_user_units_sample_counts.setText("+100")
    window.btn_expert_user_units_preview.click()
    qapp.processEvents()

    assert window._expert_user_units_preview.sample_units.numerator == 1
    assert "100 count = 1 = 1 µm" in (
        window.expert_user_units_result_fields["sample_units"].text())


def test_expert_user_units_invalid_recalculation_retains_historical_preview(
        window, qapp):
    window._set_expert_lab_step("user_units")
    for key, value in {
            "fc1": "10000",
            "fc2": "1",
            "fc5": "1",
            "fc6": "1",
            "fc7": "1000",
            "fc8": "10",
    }.items():
        window.expert_user_units_fc_fields[key].setText(value)
    window.expert_user_units_unit_label.setText("µm")
    window.expert_user_units_sample_counts.setText("100")
    window.btn_expert_user_units_preview.click()
    qapp.processEvents()
    preview_before = window._expert_user_units_preview
    results_before = {
        key: field.text()
        for key, field in window.expert_user_units_result_fields.items()
    }

    window.expert_user_units_fc_fields["fc1"].setText("0")
    window.btn_expert_user_units_preview.click()
    qapp.processEvents()

    assert window._expert_user_units_preview is preview_before
    assert "INVALID" in window.expert_user_units_status.text()
    assert "historical" in window.expert_user_units_status.text().lower()
    assert {
        key: item.text()
        for key, item in window.expert_user_units_result_fields.items()
    } == results_before

    window.expert_user_units_fc_fields["fc1"].setText("10000")
    window.expert_user_units_unit_label.setText("µ" * 49)
    window.btn_expert_user_units_preview.click()
    qapp.processEvents()

    assert window._expert_user_units_preview is preview_before
    assert "INVALID" in window.expert_user_units_status.text()
    assert "48 characters" in window.expert_user_units_status.text()
    assert {
        key: item.text()
        for key, item in window.expert_user_units_result_fields.items()
    } == results_before


def test_expert_user_units_recovers_from_invalid_with_new_coherent_preview(
        window, qapp):
    window._set_expert_lab_step("user_units")
    _fill_expert_user_units_golden(window)
    window.btn_expert_user_units_preview.click()
    qapp.processEvents()
    preview_before = window._expert_user_units_preview

    window.expert_user_units_fc_fields["fc1"].setText("0")
    window.btn_expert_user_units_preview.click()
    qapp.processEvents()
    assert window._expert_user_units_preview is preview_before
    assert window._expert_user_units_error is not None
    assert "INVALID" in window.expert_user_units_status.text()

    window.expert_user_units_fc_fields["fc1"].setText("10000")
    window.expert_user_units_fc_fields["fc7"].setText("2000")
    window.btn_expert_user_units_preview.click()
    qapp.processEvents()

    assert window._expert_user_units_preview is not preview_before
    assert window._expert_user_units_preview.units_per_count.numerator == 1
    assert window._expert_user_units_preview.units_per_count.denominator == 50
    assert window._expert_user_units_inputs_stale is False
    assert window._expert_user_units_error is None
    assert "DOCUMENTED LOCAL PREVIEW" in (
        window.expert_user_units_status.text())
    assert "INVALID" not in window.expert_user_units_status.text()


def _limits_authority_snapshot(window):
    tuning_buttons = (
        window.btn_tune,
        window.btn_tune_signature,
        window.btn_tune_vp,
        window.btn_tune_abort,
        window.btn_tune_verify,
        window.btn_tune_apply,
        window.btn_tune_p1_restore,
        window.btn_tune_p1_save,
        window.btn_tune_vp_apply,
        window.btn_tune_vp_restore,
        window.btn_tune_vp_save,
    )
    return {
        "p1_plant": window._expert_plant,
        "p1_candidate": window._expert_candidate,
        "p1_response": window._expert_response,
        "p2_plant": window._expert_vp_plant,
        "p2_candidate": window._expert_vp_candidate,
        "p1_inputs_stale": window._expert_current_inputs_stale,
        "p2_inputs_stale": window._expert_vp_inputs_stale,
        "p1_error": window._expert_current_error,
        "p2_error": window._expert_vp_error,
        "evidence": window._expert_evidence,
        "page_status": window._expert_page_status_snapshot,
        "page_status_dirty": window._expert_page_status_dirty,
        "user_units_preview": window._expert_user_units_preview,
        "user_units_stale": window._expert_user_units_inputs_stale,
        "user_units_error": window._expert_user_units_error,
        "at_result": window._at_result,
        "at_generation": window._at_result_generation,
        "vp_result": window._vp_result,
        "vp_generation": window._vp_result_generation,
        "p1_trial": window._p1_gain_trial,
        "p1_trial_generation": window._p1_trial_generation,
        "vp_trial": window._vp_gain_trial,
        "vp_trial_generation": window._vp_trial_generation,
        "vp_signature_run": window._vp_signature_run,
        "vp_trial_verified_green": window._vp_trial_verified_green,
        "vp_verified_trial": window._vp_verified_trial,
        "vp_verified_generation": window._vp_verified_generation,
        "verify_inflight": window._verify_trial_inflight,
        "authority_generation": window._tuning_authority_generation,
        "dispatch": window._tune_dispatch_inflight,
        "dispatch_generation": window._tune_dispatch_generation,
        "axis_summary": dict(window._axis_summary_data),
        "axis_safety_snapshot": window._axis_safety_snapshot,
        "connection": (
            window._ui_connected,
            window._connection_admitted,
            window._connection_access_mode,
            window._requested_connection_access_mode,
            window._connection_shutdown_pending,
            window._telemetry_authoritative,
            window._telemetry_authority_loss_latched,
            window._energizing_state,
            window._last_mo,
            window._motor_write_inflight,
        ),
        "connection_controls": (
            window.cmb_access_mode.currentData(),
            window.cmb_access_mode.isEnabled(),
            window.btn_conn.isEnabled(),
            window.btn_global_stop.isEnabled(),
            window.btn_motion_stop.isEnabled(),
            window.btn_zero.isEnabled(),
        ),
        "safety_render": (
            window.lbl_axis_safety_state.text(),
            window.lbl_axis_safety_detail.text(),
            tuple(
                (key, field.text())
                for key, field in window.axis_safety_fields.items()),
        ),
        "installed": tuple(
            (key, field.text())
            for key, field in window.tune_installed_gain_fields.items()),
        "button_enabled": tuple(
            button.isEnabled() for button in tuning_buttons),
        "user_units_inputs": tuple(
            (key, field.text())
            for key, field in window.expert_user_units_fc_fields.items()),
        "user_units_results": tuple(
            (key, field.text())
            for key, field in window.expert_user_units_result_fields.items()),
        "user_units_label": window.expert_user_units_unit_label.text(),
        "user_units_sample": window.expert_user_units_sample_counts.text(),
    }


def test_expert_limits_protections_page_is_static_zero_io_and_authority_isolated(
        window, qapp, monkeypatch):
    _fill_expert_user_units_golden(window)
    window.btn_expert_user_units_preview.click()
    window._set_expert_lab_step("status")
    qapp.processEvents()
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError(
            "Limits / Protections inspector entered an I/O/dispatch path")

    class PoisonWorker:
        def __getattr__(self, name):
            def forbidden_worker_call(*args, **kwargs):
                calls.append((name, args, kwargs))
                raise AssertionError(
                    "Limits / Protections inspector touched worker.%s" % name)

            return forbidden_worker_call

    poison_worker = PoisonWorker()
    window.worker = poison_worker
    before = _limits_authority_snapshot(window)
    monkeypatch.setattr(app_main, "DriveWorker", forbidden)
    monkeypatch.setattr(app_main, "ElmoLink", forbidden)
    monkeypatch.setattr(window, "_claim_tune_dispatch", forbidden)

    window._set_expert_lab_step("limits_protections")
    for index in range(window.expert_limits_section.count()):
        window.expert_limits_section.setCurrentIndex(index)
        qapp.processEvents()

    assert window.expert_lab_stack.currentWidget() is (
        window.expert_limits_protections_page)
    assert window.worker is poison_worker
    assert calls == []
    assert _limits_authority_snapshot(window) == before
    assert window.expert_limits_section.isEditable() is False
    assert window.expert_limits_protections_page.findChildren(
        QtWidgets.QLineEdit) == []
    assert window.expert_limits_protections_page.findChildren(
        QtWidgets.QPushButton) == []
    assert tuple(
        window.expert_limits_table.item(row, 0).text()
        for row in range(window.expert_limits_table.rowCount())
    ) == (
        "ER[3]", "ER[2]", "ER[5]", "CL[2]", "CL[3]", "CL[4]",
        "XP[1]", "XP[13]", "LL[3]", "HL[3]", "HL[2]",
    )
    assert window.expert_limits_table.horizontalHeaderItem(2).text() == (
        "UNIT / DOCUMENTED REF ACCESS")
    assert all(
        "app: inspect-only" in
        window.expert_limits_table.item(row, 2).text()
        for row in range(window.expert_limits_table.rowCount()))
    rendered = " ".join((
        window.expert_lab_title.text(),
        window.expert_lab_note.text(),
        window.expert_limits_banner.text(),
        window.expert_limits_status.text(),
        window.expert_limits_conflicts.text(),
        window.expert_limits_warnings.text(),
        window.expert_limits_missing.text(),
        *(
            window.expert_limits_table.item(row, column).text()
            for row in range(window.expert_limits_table.rowCount())
            for column in range(window.expert_limits_table.columnCount())
        ),
    )).upper()
    for phrase in (
            "DOCUMENTED PARAMETER MAP",
            "NOT CURRENT DRIVE CONFIG",
            "NOT ACTIVE PROTECTION",
            "NOT A SAFETY ASSESSMENT",
            "NO DRIVE READ",
            "NO VALIDATION",
            "NO WRITE",
            "NO APPLY/SV"):
        assert phrase in rendered
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
        assert forbidden not in rendered


def test_expert_limits_protections_never_absorbs_late_axis_summary(
        window, qapp):
    window._set_expert_lab_step("limits_protections")
    before = tuple(
        window.expert_limits_table.item(row, column).text()
        for row in range(window.expert_limits_table.rowCount())
        for column in range(window.expert_limits_table.columnCount())
    )

    window._on_axis_summary({
        "scope": "LAST OBSERVED",
        "mode": "UM=5",
        "raw": {
            "PL[1]": 12.3456789,
            "CL[1]": 9.87654321,
            "VH[2]": 123456789,
            "ER[3]": 777777777,
            "CL[2]": 88.888888,
            "XP[1]": 55.555555,
            "LL[3]": -444444444,
            "HL[3]": 333333333,
        },
    })
    qapp.processEvents()

    after = tuple(
        window.expert_limits_table.item(row, column).text()
        for row in range(window.expert_limits_table.rowCount())
        for column in range(window.expert_limits_table.columnCount())
    )
    assert after == before
    rendered = " ".join(after)
    for actual_value in (
            "12.3456789", "9.87654321", "123456789", "777777777",
            "88.888888", "55.555555", "-444444444", "333333333"):
        assert actual_value not in rendered


def test_expert_v2_steps_fit_1366x820_in_all_skins(
        window, qapp):
    def contrast_ratio(first, second):
        def relative_luminance(color):
            channels = []
            for value in (color.redF(), color.greenF(), color.blueF()):
                channels.append(
                    value / 12.92
                    if value <= 0.04045
                    else ((value + 0.055) / 1.055) ** 2.4)
            return (
                0.2126 * channels[0]
                + 0.7152 * channels[1]
                + 0.0722 * channels[2]
            )

        high, low = sorted((
            relative_luminance(first),
            relative_luminance(second),
        ), reverse=True)
        return (high + 0.05) / (low + 0.05)

    previous_style_sheet = qapp.styleSheet()
    previous_palette = QtGui.QPalette(qapp.palette())
    window.resize(1366, 820)
    window.show()
    window._show_tuning_mode("expert")
    try:
        for themed in (theme_qdd, amber_theme, theme_angrybirds):
            qapp.setStyleSheet(themed.STYLE)
            for step in (
                    "current", "vp", "evidence", "status", "user_units",
                    "limits_protections"):
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
                if step == "limits_protections":
                    table_palette = (
                        window.expert_limits_table.viewport().palette())
                    assert contrast_ratio(
                        table_palette.color(
                            QtGui.QPalette.ColorRole.Text),
                        table_palette.color(
                            QtGui.QPalette.ColorRole.Base),
                    ) >= 4.5
                buttons = (
                        window.btn_expert_step_current,
                        window.btn_expert_step_vp,
                        window.btn_expert_step_evidence,
                        window.btn_expert_step_status,
                        window.btn_expert_step_user_units,
                        window.btn_expert_step_limits)
                for button in buttons:
                    assert button.isVisible()
                    required = (
                        button.fontMetrics().horizontalAdvance(button.text())
                        + 24)
                    assert required <= button.contentsRect().width()
                for index, first in enumerate(buttons):
                    for second in buttons[index + 1:]:
                        assert not first.geometry().intersects(
                            second.geometry())
    finally:
        qapp.setPalette(previous_palette)
        qapp.setStyleSheet(previous_style_sheet)
