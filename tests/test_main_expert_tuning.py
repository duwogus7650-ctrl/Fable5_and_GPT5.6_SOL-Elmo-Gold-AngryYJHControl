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
        == "EXPERT CANDIDATE LAB v1 · OFFLINE MODEL · NO DRIVE I/O"
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
