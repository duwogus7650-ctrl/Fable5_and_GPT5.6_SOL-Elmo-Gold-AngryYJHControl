"""Offline UI contract for Recorder View Design v1.

These tests never construct ``ElmoLink`` and never start ``DriveWorker``.  The
view is allowed to consume only a validated, completed recorder bundle and may
not create any drive command path.
"""

from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

import main as app_main


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


class _RecorderWorkerSpy:
    def __init__(self):
        self.starts = []

    @staticmethod
    def isRunning():
        return True

    def start_recorder(self, request):
        self.starts.append(request)
        return 7


@pytest.fixture
def window(qapp, monkeypatch):
    monkeypatch.setattr(app_main, "list_serial_ports", lambda: ["COM_TEST"])
    win = app_main.MainWindow()
    yield win
    win.worker = None
    win.close()
    qapp.processEvents()


def _resolved(*signals, count=3):
    return app_main.recorder_control.ResolvedRecorderRequest(
        signals=tuple(signals),
        requested_resolution_us=200.0,
        actual_resolution_us=200.0,
        time_resolution=2,
        requested_record_time_s=0.0002 * count,
        actual_record_time_s=0.0002 * count,
        length_per_signal=count,
        total_buffer_samples=count * len(signals),
        trigger="immediate",
    )


def _validated_bundle(win):
    resolved = _resolved("Position Feedback", "Actual Velocity")
    win._recorder_manifest_data = {
        "capture_id": "capture-test-001",
        "completion": "VALIDATED",
        "signals": list(resolved.signals),
        "length_per_signal": resolved.length_per_signal,
        "actual_resolution_us": resolved.actual_resolution_us,
        "drive_identity": "sha256:test-drive",
    }
    data = {
        "dt": 0.0002,
        "Position Feedback": [10.0, 11.0, 12.0],
        "Actual Velocity": [-1.0, 0.0, 1.0],
    }
    win._inject_recorder_data_for_offline_test(data, resolved)
    return data, resolved


def test_view_design_is_locked_without_validated_completed_capture(window):
    assert hasattr(window, "btn_rec_recording_tab")
    assert hasattr(window, "btn_rec_view_tab")
    assert hasattr(window, "recorder_page_stack")
    assert not window.btn_rec_view_tab.isEnabled()
    assert window.recorder_page_stack.currentIndex() == 0
    assert "No validated capture" in window.lbl_rec_view_status.text()
    assert not window.edit_rec_time_start.isEnabled()
    assert not window.edit_rec_time_end.isEnabled()
    assert not window.btn_rec_time_apply_all.isEnabled()
    assert not window.btn_rec_time_full.isEnabled()
    assert not window.btn_rec_view_time.isEnabled()
    assert not window.btn_rec_view_fft.isEnabled()
    assert not window.btn_rec_stats_calculate.isEnabled()
    assert "LOCAL SAMPLE RANGE" in window.lbl_rec_range_title.text()
    assert "MOUSE DRAG" in window.lbl_rec_range_title.text()
    assert "nearest visible original sample" in (
        window.lbl_rec_range_title.toolTip().lower())
    assert "FIELD/FORMULA" in window.lbl_rec_stats_title.text()
    assert "STATIC-IL" in window.lbl_rec_stats_title.text()
    assert not window.spin_rec_range_start.isEnabled()
    assert not window.spin_rec_range_end.isEnabled()
    assert not window.btn_rec_range_calculate.isEnabled()
    assert not window.btn_rec_stats_export.isEnabled()
    assert window.rec_stats_table.rowCount() == 0
    assert window.rec_range_values_table.rowCount() == 0
    assert window.lbl_rec_stats_scope.text() == "NO CAPTURE"
    assert window.lbl_rec_range_scope.text() == "NO CAPTURE"
    assert window.rec_view_analysis_tabs.currentIndex() == 0

    # A data-shaped object without its VALIDATED manifest must not update the view.
    resolved = _resolved("Position Feedback")
    window._inject_recorder_data_for_offline_test(
        {"dt": 0.0002, "Position Feedback": [1.0, 2.0, 3.0]}, resolved)
    assert not window.btn_rec_view_tab.isEnabled()
    assert window._recorder_view_model is None


def test_validated_capture_enables_read_only_dual_view(window):
    data, resolved = _validated_bundle(window)

    assert window.btn_rec_view_tab.isEnabled()
    assert window._recorder_view_is_current
    assert window._recorder_view_model.capture_id == "capture-test-001"
    assert window._recorder_view_model.signals == resolved.signals
    assert window._recorder_view_model.x_s == pytest.approx((0.0, 0.0002, 0.0004))
    assert window._recorder_view_model.series[0].y == tuple(data[resolved.signals[0]])
    assert window._recorder_view_model.units == "personality-owned; not inferred"
    assert window.rec_view_lane_a.currentText() == "Position Feedback"
    assert window.rec_view_lane_b.currentText() == "Actual Velocity"
    assert "Validated" in window.lbl_rec_view_status.text()
    assert "FULL" in window.lbl_rec_view_status.text()
    assert window.edit_rec_time_start.isEnabled()
    assert window.edit_rec_time_end.isEnabled()
    assert window.btn_rec_time_apply_all.isEnabled()
    assert window.btn_rec_time_full.isEnabled()
    assert window.btn_rec_view_time.isEnabled()
    assert window.btn_rec_view_time.isChecked()
    assert window.btn_rec_view_fft.isEnabled()
    assert "exact samples" in window.lbl_rec_plot_contract.text()
    assert window.btn_rec_stats_calculate.isEnabled()
    assert window.spin_rec_range_start.isEnabled()
    assert window.spin_rec_range_end.isEnabled()
    assert window.spin_rec_range_start.minimum() == 0
    assert window.spin_rec_range_start.maximum() == 2
    assert window.spin_rec_range_start.value() == 0
    assert window.spin_rec_range_end.value() == 2
    assert window.btn_rec_range_calculate.isEnabled()
    assert "A #0" in window.lbl_rec_range_scope.text()
    assert "B #2" in window.lbl_rec_range_scope.text()
    assert "N=3" in window.lbl_rec_range_scope.text()
    assert window.recorder_plot.sample_range_selection.start_index == 0
    assert window.recorder_plot.sample_range_selection.end_index == 2
    assert window.rec_stats_table.rowCount() == 0
    assert window.rec_range_values_table.rowCount() == 0
    assert "READY" in window.lbl_rec_stats_scope.text()
    assert not window.btn_rec_stats_export.isEnabled()

    window.btn_rec_view_tab.click()
    assert window.recorder_page_stack.currentIndex() == 1
    assert window.recorder_plot.view_model is window._recorder_view_model


def test_full_capture_statistics_table_labels_local_contract_and_signal_order(window):
    _validated_bundle(window)

    window.btn_rec_stats_calculate.click()

    result = window._recorder_statistics_model
    assert result is not None
    assert result.binding == window._recorder_view_model.binding
    assert result.scope == "full_capture"
    assert window.rec_stats_table.rowCount() == 2
    assert window.rec_stats_table.columnCount() == 9
    assert tuple(
        window.rec_stats_table.horizontalHeaderItem(column).text()
        for column in range(window.rec_stats_table.columnCount())
    ) == (
        "Signal", "N (local samples)", "Min", "Max", "Average",
        "RMS AC", "RMS DC", "Tolerance", "Tolerance %",
    )
    assert window.rec_stats_table.item(0, 0).text() == "Position Feedback"
    assert window.rec_stats_table.item(1, 0).text() == "Actual Velocity"
    assert window.rec_stats_table.item(0, 1).text() == "3"
    assert float(window.rec_stats_table.item(0, 2).text()) == 10.0
    assert float(window.rec_stats_table.item(0, 3).text()) == 12.0
    assert float(window.rec_stats_table.item(0, 4).text()) == 11.0
    assert float(window.rec_stats_table.item(0, 5).text()) == pytest.approx(
        (2.0 / 3.0) ** 0.5)
    assert float(window.rec_stats_table.item(0, 6).text()) == pytest.approx(
        (365.0 / 3.0) ** 0.5)
    assert float(window.rec_stats_table.item(0, 7).text()) == 2.0
    assert float(window.rec_stats_table.item(0, 8).text()) == pytest.approx(
        abs(2.0 / 11.0 / 2.0) * 100.0)
    assert "DERIVED" in window.lbl_rec_stats_scope.text()
    assert "FULL CAPTURE" in window.lbl_rec_stats_scope.text()
    assert "RMS STATIC-IL VERIFIED" in window.lbl_rec_stats_scope.text()
    assert "Tolerance % STATIC-IL VERIFIED" in window.lbl_rec_stats_scope.text()
    assert window.btn_rec_stats_export.isEnabled()
    assert window.rec_view_analysis_tabs.currentIndex() == 1


def test_exact_sample_range_populates_endpoint_values_and_inclusive_statistics(window):
    _validated_bundle(window)
    window.spin_rec_range_start.setValue(1)
    window.spin_rec_range_end.setValue(2)

    window.btn_rec_range_calculate.click()

    result = window._recorder_statistics_model
    assert result is not None
    assert result.scope == "sample_range"
    assert result.binding == window._recorder_view_model.binding
    assert result.selection.start_index == 1
    assert result.selection.end_index == 2
    assert result.selection.sample_count == 2
    assert result.selection.start_time_s == pytest.approx(0.0002)
    assert result.selection.end_time_s == pytest.approx(0.0004)
    assert window.rec_stats_table.rowCount() == 2
    assert window.rec_stats_table.item(0, 1).text() == "2"
    assert float(window.rec_stats_table.item(0, 2).text()) == 11.0
    assert float(window.rec_stats_table.item(0, 3).text()) == 12.0
    assert float(window.rec_stats_table.item(0, 4).text()) == 11.5
    assert float(window.rec_stats_table.item(0, 7).text()) == 1.0
    assert float(window.rec_stats_table.item(0, 8).text()) == pytest.approx(
        abs(1.0 / 11.5 / 2.0) * 100.0)
    assert window.rec_range_values_table.rowCount() == 2
    assert tuple(
        window.rec_range_values_table.horizontalHeaderItem(column).text()
        for column in range(window.rec_range_values_table.columnCount())
    ) == (
        "Signal", "A sample", "A time [s]", "A value",
        "B sample", "B time [s]", "B value", "Δ time [s]", "Δ value",
    )
    assert window.rec_range_values_table.item(0, 0).text() == "Position Feedback"
    assert window.rec_range_values_table.item(0, 1).text() == "1"
    assert float(window.rec_range_values_table.item(0, 2).text()) == 0.0002
    assert float(window.rec_range_values_table.item(0, 3).text()) == 11.0
    assert window.rec_range_values_table.item(0, 4).text() == "2"
    assert float(window.rec_range_values_table.item(0, 5).text()) == 0.0004
    assert float(window.rec_range_values_table.item(0, 6).text()) == 12.0
    assert float(window.rec_range_values_table.item(0, 7).text()) == 0.0002
    assert float(window.rec_range_values_table.item(0, 8).text()) == 1.0
    assert "SAMPLE RANGE A:B · INCLUSIVE" in window.lbl_rec_stats_scope.text()
    assert "N=2" in window.lbl_rec_stats_scope.text()
    assert "Tolerance % STATIC-IL VERIFIED" in window.lbl_rec_stats_scope.text()
    assert window.recorder_plot.sample_range_selection == result.selection
    assert window.rec_view_analysis_tabs.currentIndex() == 1


def test_range_zero_mean_percent_and_invalid_edit_clear_stale_result(window):
    _validated_bundle(window)
    window.btn_rec_range_calculate.click()
    accepted = window._recorder_statistics_model

    assert accepted.rows[1].average == 0.0
    assert accepted.rows[1].tolerance_percent == 0.0
    assert float(window.rec_stats_table.item(1, 8).text()) == 0.0

    window.spin_rec_range_start.setValue(1)
    window.spin_rec_range_end.setValue(1)
    assert not window.btn_rec_range_calculate.isEnabled()
    assert "INVALID" in window.lbl_rec_range_scope.text()
    assert accepted is not None
    assert window._recorder_statistics_model is None
    assert window.rec_stats_table.rowCount() == 0
    assert window.rec_range_values_table.rowCount() == 0
    assert not window.btn_rec_stats_export.isEnabled()
    assert window.btn_rec_export.isEnabled()


def test_range_is_zoom_independent_fft_preserved_and_historical_local_only(window):
    class _PoisonWorker:
        def __getattr__(self, name):
            raise AssertionError("range statistics touched worker.%s" % name)

    _validated_bundle(window)
    window.spin_rec_range_start.setValue(0)
    window.spin_rec_range_end.setValue(1)
    window.btn_rec_range_calculate.click()
    accepted = window._recorder_statistics_model
    accepted_cells = tuple(
        window.rec_stats_table.item(0, column).text()
        for column in range(window.rec_stats_table.columnCount()))

    window.edit_rec_time_start.setText("0.0002")
    window.edit_rec_time_end.setText("0.0004")
    window.btn_rec_time_apply_all.click()
    assert window._recorder_statistics_model is accepted
    assert tuple(
        window.rec_stats_table.item(0, column).text()
        for column in range(window.rec_stats_table.columnCount())) == accepted_cells

    window.btn_rec_view_fft.click()
    assert not window.spin_rec_range_start.isEnabled()
    assert not window.spin_rec_range_end.isEnabled()
    assert not window.btn_rec_range_calculate.isEnabled()
    assert window.recorder_plot.sample_range_selection == accepted.selection
    window.btn_rec_view_time.click()
    assert window.spin_rec_range_start.isEnabled()
    assert window.btn_rec_range_calculate.isEnabled()

    window._invalidate_recorder_target_ui("Drive disconnected")
    assert "HISTORICAL / OFFLINE" in window.lbl_rec_range_scope.text()
    assert "HISTORICAL / OFFLINE" in window.lbl_rec_stats_scope.text()
    window.worker = _PoisonWorker()
    window.btn_rec_range_calculate.click()

    assert window._recorder_statistics_model.scope == "sample_range"
    assert not window._recorder_view_is_current
    assert "HISTORICAL / OFFLINE" in window.lbl_rec_view_status.text()


def test_same_binding_new_view_resets_range_and_clears_endpoint_rows(window):
    _validated_bundle(window)
    window.spin_rec_range_start.setValue(1)
    window.spin_rec_range_end.setValue(2)
    window.btn_rec_range_calculate.click()
    first_view = window._recorder_view_model
    assert window.rec_range_values_table.rowCount() == 2

    _validated_bundle(window)

    assert window._recorder_view_model is not first_view
    assert window._recorder_range_source_view is window._recorder_view_model
    assert window.spin_rec_range_start.value() == 0
    assert window.spin_rec_range_end.value() == 2
    assert window._recorder_range_selection.start_index == 0
    assert window._recorder_range_selection.end_index == 2
    assert window._recorder_statistics_model is None
    assert window.rec_stats_table.rowCount() == 0
    assert window.rec_range_values_table.rowCount() == 0


def test_single_sample_statistics_are_locked_to_match_eas_range_gate(window):
    resolved = _resolved("Single", count=1)
    window._recorder_manifest_data = {
        "capture_id": "capture-single-001",
        "completion": "VALIDATED",
        "signals": ["Single"],
        "length_per_signal": 1,
        "actual_resolution_us": resolved.actual_resolution_us,
        "drive_identity": "sha256:test-drive",
    }

    window._inject_recorder_data_for_offline_test(
        {"dt": 0.0002, "Single": [7.0]}, resolved)

    assert window._recorder_view_model is not None
    assert not window.btn_rec_stats_calculate.isEnabled()
    assert window.rec_stats_table.rowCount() == 0
    assert "AT LEAST TWO SAMPLES" in window.lbl_rec_stats_scope.text()


def test_statistics_ignore_zoom_and_fft_and_remain_historical_local_only(window):
    class _PoisonWorker:
        def __getattr__(self, name):
            raise AssertionError("statistics touched worker.%s" % name)

    _validated_bundle(window)
    window.btn_rec_stats_calculate.click()
    original = window._recorder_statistics_model
    original_cells = tuple(
        window.rec_stats_table.item(0, column).text()
        for column in range(window.rec_stats_table.columnCount()))

    window.edit_rec_time_start.setText("0")
    window.edit_rec_time_end.setText("0.0002")
    window.btn_rec_time_apply_all.click()
    window.btn_rec_view_fft.click()

    assert window._recorder_statistics_model is original
    assert window.rec_view_analysis_tabs.currentIndex() == 0
    assert tuple(
        window.rec_stats_table.item(0, column).text()
        for column in range(window.rec_stats_table.columnCount())) == original_cells

    window._invalidate_recorder_target_ui("Drive disconnected")
    window.worker = _PoisonWorker()
    window.btn_rec_stats_calculate.click()

    assert window._recorder_statistics_model is not None
    assert window.rec_view_analysis_tabs.currentIndex() == 1
    assert window._recorder_statistics_model.binding == original.binding
    assert not window._recorder_view_is_current
    assert "HISTORICAL / OFFLINE" in window.lbl_rec_view_status.text()


def test_statistics_clear_with_capture_and_failure_does_not_revoke_capture_or_csv(window):
    _validated_bundle(window)
    window.btn_rec_stats_calculate.click()
    assert window.rec_stats_table.rowCount() == 2
    first_source = window._recorder_statistics_source_view

    # Even a duplicate test bundle with the same logical binding creates a
    # new immutable view object.  Never carry derived rows across that
    # evidence replacement merely because its ID fields compare equal.
    _validated_bundle(window)
    assert window._recorder_view_model is not first_source
    assert window._recorder_statistics_model is None
    assert window._recorder_statistics_source_view is None
    assert window.rec_stats_table.rowCount() == 0
    window.btn_rec_stats_calculate.click()
    assert window.rec_stats_table.rowCount() == 2

    window._invalidate_recorder_view("New capture", clear=True)

    assert window._recorder_statistics_model is None
    assert window._recorder_statistics_source_view is None
    assert window.rec_stats_table.rowCount() == 0
    assert not window.btn_rec_stats_calculate.isEnabled()
    assert window.lbl_rec_stats_scope.text() == "NO CAPTURE"

    resolved = _resolved("Extreme", count=2)
    window._recorder_manifest_data = {
        "capture_id": "capture-extreme-001",
        "completion": "VALIDATED",
        "signals": ["Extreme"],
        "length_per_signal": 2,
        "actual_resolution_us": resolved.actual_resolution_us,
        "drive_identity": "sha256:test-drive",
    }
    window._inject_recorder_data_for_offline_test(
        {"dt": 0.0002, "Extreme": [-1e308, 1e308]}, resolved)
    accepted_model = window._recorder_view_model

    window.btn_rec_stats_calculate.click()

    assert window._recorder_view_model is accepted_model
    assert window._recorder_view_is_current
    assert window.btn_rec_export.isEnabled()
    assert window.rec_stats_table.rowCount() == 0
    assert window._recorder_statistics_model is None
    assert "UNAVAILABLE" in window.lbl_rec_stats_scope.text()
    assert window.rec_view_analysis_tabs.currentIndex() == 1


def test_tolerance_percent_nonfinite_is_field_level_na_not_capture_failure(window):
    resolved = _resolved("Tiny Mean", count=3)
    window._recorder_manifest_data = {
        "capture_id": "capture-tiny-mean-001",
        "completion": "VALIDATED",
        "signals": ["Tiny Mean"],
        "length_per_signal": 3,
        "actual_resolution_us": resolved.actual_resolution_us,
        "drive_identity": "sha256:test-drive",
    }
    window._inject_recorder_data_for_offline_test(
        {"dt": 0.0002, "Tiny Mean": [-1.0, 1.0, 1e-308]}, resolved)
    accepted_model = window._recorder_view_model

    window.btn_rec_stats_calculate.click()

    assert window._recorder_view_model is accepted_model
    assert window._recorder_statistics_model is not None
    assert window._recorder_statistics_model.rows[0].tolerance_percent is None
    assert window.rec_stats_table.item(0, 8).text() == "N/A"
    assert window.btn_rec_export.isEnabled()
    assert "DERIVED" in window.lbl_rec_stats_scope.text()


def test_manual_time_zoom_applies_to_both_charts_and_survives_lane_change(window):
    _validated_bundle(window)
    window.edit_rec_time_start.setText("0")
    window.edit_rec_time_end.setText("0.0002")

    window.btn_rec_time_apply_all.click()

    assert window.recorder_plot.layout_model.x_range_s == pytest.approx(
        (0.0, 0.0002))
    assert "MANUAL TIME" in window.lbl_rec_time_mode.text()
    window.rec_view_lane_a.setCurrentIndex(2)
    assert window.recorder_plot.layout_model.x_range_s == pytest.approx(
        (0.0, 0.0002))

    window.btn_rec_time_full.click()

    assert window.recorder_plot.layout_model.x_range_s is None
    assert "FULL TIME" in window.lbl_rec_time_mode.text()


def test_fft_mode_uses_full_capture_zero_scale_and_preserves_manual_time_window(window):
    _validated_bundle(window)
    window.edit_rec_time_start.setText("0")
    window.edit_rec_time_end.setText("0.0002")
    window.btn_rec_time_apply_all.click()
    manual_range = window.recorder_plot.layout_model.x_range_s

    window.btn_rec_view_fft.click()

    layout = window.recorder_plot.layout_model
    spectrum = window.recorder_plot.spectrum_model
    assert layout.plot_mode == app_main.recorder_view.PLOT_MODE_FFT
    assert layout.x_range_s == manual_range
    assert spectrum is not None
    assert spectrum.input_sample_count == 3
    assert len(spectrum.x_hz) == 2
    assert not window.edit_rec_time_start.isEnabled()
    assert not window.edit_rec_time_end.isEnabled()
    assert not window.btn_rec_time_apply_all.isEnabled()
    assert not window.btn_rec_time_full.isEnabled()
    assert "FULL CAPTURE" in window.lbl_rec_time_mode.text()
    assert "Y STARTS AT 0" in window.lbl_rec_plot_contract.text()

    window.btn_rec_view_time.click()

    assert window.recorder_plot.layout_model.plot_mode == (
        app_main.recorder_view.PLOT_MODE_TIME)
    assert window.recorder_plot.layout_model.x_range_s == manual_range
    assert window.edit_rec_time_start.isEnabled()
    assert "MANUAL TIME" in window.lbl_rec_time_mode.text()


def test_historical_fft_is_local_only_and_cannot_repromote_capture_authority(window):
    class _PoisonWorker:
        def __getattr__(self, name):
            raise AssertionError("FFT display touched worker.%s" % name)

    _validated_bundle(window)
    window._invalidate_recorder_target_ui("Drive disconnected")
    window.worker = _PoisonWorker()

    window.btn_rec_view_fft.click()

    assert window.recorder_plot.layout_model.plot_mode == (
        app_main.recorder_view.PLOT_MODE_FFT)
    assert window.recorder_plot.spectrum_model is not None
    assert not window._recorder_view_is_current
    assert "HISTORICAL / OFFLINE" in window.lbl_rec_view_status.text()


def test_fft_is_cached_outside_repaint_and_ignores_time_domain_y_range(
        qapp, monkeypatch):
    resolved = _resolved("Position", count=8)
    view = app_main.recorder_view.build_capture_view(
        state="COMPLETED",
        data={
            "dt": 0.0002,
            "Position": [0.0, 1.0, 0.0, -1.0, 0.0, 1.0, 0.0, -1.0],
        },
        resolved=resolved,
        binding=app_main.recorder_view.CaptureBinding(
            "capture-fft-cache", 1, "sha256:test-drive"),
    )
    layout = app_main.recorder_view.ViewLayout(
        lanes=(
            app_main.recorder_view.LaneLayout(
                ("Position",), True, (-100.0, -50.0)),
            app_main.recorder_view.LaneLayout(),
        ),
        x_range_s=(0.0, 0.0002),
        plot_mode=app_main.recorder_view.PLOT_MODE_FFT,
    )
    real_builder = app_main.recorder_view.build_spectrum_view
    build_calls = []

    def counted_builder(model):
        build_calls.append(model)
        return real_builder(model)

    observed_bounds = []
    real_path_builder = app_main.RecorderPlotWidget._build_series_path

    def observed_path(item, rect, **kwargs):
        observed_bounds.append((kwargs["y_min"], kwargs["y_max"]))
        return real_path_builder(item, rect, **kwargs)

    monkeypatch.setattr(
        app_main.recorder_view, "build_spectrum_view", counted_builder)
    monkeypatch.setattr(
        app_main.RecorderPlotWidget, "_build_series_path",
        staticmethod(observed_path))
    plot = app_main.RecorderPlotWidget()
    plot.resize(720, 390)
    plot.set_view_model(view, layout)
    target = QtGui.QPixmap(plot.size())

    plot.render(target)
    plot.render(target)

    assert build_calls == [view]
    assert len(observed_bounds) == 2
    assert all(low == 0.0 and high >= 0.0 for low, high in observed_bounds)
    assert all((low, high) != (-100.0, -50.0)
               for low, high in observed_bounds)
    assert plot.layout_model.x_range_s == (0.0, 0.0002)
    plot.close()
    qapp.processEvents()


def test_single_sample_capture_keeps_fft_disabled(window):
    resolved = _resolved("Position", count=1)
    window._recorder_manifest_data = {
        "capture_id": "capture-single-sample",
        "completion": "VALIDATED",
        "signals": ["Position"],
        "length_per_signal": 1,
        "actual_resolution_us": 200.0,
        "drive_identity": "sha256:test-drive",
    }
    window._inject_recorder_data_for_offline_test(
        {"dt": 0.0002, "Position": [1.0]}, resolved)

    assert window.btn_rec_view_time.isEnabled()
    assert window.btn_rec_view_time.isChecked()
    assert not window.btn_rec_view_fft.isEnabled()
    assert not window.btn_rec_time_apply_all.isEnabled()


def test_invalid_manual_time_zoom_is_rejected_without_changing_layout(
        window, monkeypatch):
    _validated_bundle(window)
    before = window.recorder_plot.layout_model
    flashes = []
    monkeypatch.setattr(window, "_flash", flashes.append)
    window.edit_rec_time_start.setText("0.0001")
    window.edit_rec_time_end.setText("0.0002")

    window.btn_rec_time_apply_all.click()

    assert window.recorder_plot.layout_model is before
    assert float(window.edit_rec_time_start.text()) == pytest.approx(0.0)
    assert float(window.edit_rec_time_end.text()) == pytest.approx(0.0004)
    assert "FULL TIME" in window.lbl_rec_time_mode.text()
    assert flashes and "Time Zoom" in flashes[-1]


def test_saved_manual_time_window_repopulates_controls(window):
    _validated_bundle(window)
    layout = app_main.recorder_view.set_time_window(
        window.recorder_plot.layout_model,
        window._recorder_view_model,
        (0.0002, 0.0004),
    )

    window._populate_recorder_view_controls(window._recorder_view_model, layout)

    assert window.recorder_plot.layout_model.x_range_s == pytest.approx(
        (0.0002, 0.0004))
    assert float(window.edit_rec_time_start.text()) == pytest.approx(0.0002)
    assert float(window.edit_rec_time_end.text()) == pytest.approx(0.0004)
    assert "MANUAL TIME" in window.lbl_rec_time_mode.text()


def test_plot_stores_canonical_layout_and_signal_change_preserves_time_only(window):
    _validated_bundle(window)
    layout = app_main.recorder_view.ViewLayout((
        app_main.recorder_view.LaneLayout(
            ("Position Feedback",), True, ("0", "20")),
        app_main.recorder_view.LaneLayout(
            ("Actual Velocity",), True, ("-2", "2")),
    ), x_range_s=("0", "0.0002"))

    window.recorder_plot.set_view_model(window._recorder_view_model, layout)

    canonical = window.recorder_plot.layout_model
    assert canonical.x_range_s == pytest.approx((0.0, 0.0002))
    assert canonical.lanes[0].y_range == pytest.approx((0.0, 20.0))
    assert canonical.lanes[1].y_range == pytest.approx((-2.0, 2.0))
    window.recorder_plot.set_lanes("Actual Velocity", "Actual Velocity")
    changed = window.recorder_plot.layout_model
    assert changed.x_range_s == canonical.x_range_s
    assert changed.lanes[0].y_range is None
    assert changed.lanes[1].y_range == canonical.lanes[1].y_range


def test_hidden_lane_loaded_from_layout_is_visible_and_recoverable_in_ui(window):
    _validated_bundle(window)
    layout = app_main.recorder_view.ViewLayout((
        app_main.recorder_view.LaneLayout(
            ("Position Feedback",), False, None),
        app_main.recorder_view.LaneLayout(
            ("Actual Velocity",), True, None),
    ))

    window._populate_recorder_view_controls(window._recorder_view_model, layout)

    assert not window.chk_rec_view_lane_a.isChecked()
    assert window.chk_rec_view_lane_a.isEnabled()
    assert not window.recorder_plot.layout_model.lanes[0].visible
    window.chk_rec_view_lane_a.click()
    assert window.recorder_plot.layout_model.lanes[0].visible


def test_historical_capture_can_be_zoomed_without_regaining_current_authority(window):
    _validated_bundle(window)
    window._invalidate_recorder_target_ui("Drive disconnected")
    window.edit_rec_time_start.setText("0")
    window.edit_rec_time_end.setText("0.0002")

    window.btn_rec_time_apply_all.click()

    assert not window._recorder_view_is_current
    assert "HISTORICAL / OFFLINE" in window.lbl_rec_view_status.text()
    assert window.recorder_plot.layout_model.x_range_s == pytest.approx(
        (0.0, 0.0002))


def test_plot_renders_full_16k_capture_without_decimator(qapp, monkeypatch):
    count = app_main.recorder_control.RECORDER_BUFFER_SAMPLES
    resolved = app_main.recorder_control.ResolvedRecorderRequest(
        signals=("Position",),
        requested_resolution_us=200.0,
        actual_resolution_us=200.0,
        time_resolution=2,
        requested_record_time_s=count * 0.0002,
        actual_record_time_s=count * 0.0002,
        length_per_signal=count,
        total_buffer_samples=count,
        trigger="immediate",
    )
    view = app_main.recorder_view.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Position": list(range(count))},
        resolved=resolved,
        binding=app_main.recorder_view.CaptureBinding(
            "capture-16k", 1, "sha256:test-drive"),
    )
    monkeypatch.setattr(
        app_main.recorder_view, "decimate_view",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("full renderer must not decimate")))
    plot = app_main.RecorderPlotWidget()
    plot.resize(720, 390)
    plot.set_view_model(view)
    target = QtGui.QPixmap(plot.size())

    plot.render(target)
    path, plotted_count = plot._build_series_path(
        view.series[0], QtCore.QRectF(0.0, 0.0, 720.0, 300.0),
        x_min=view.x_s[0], x_max=view.x_s[-1],
        y_min=0.0, y_max=float(count - 1))

    assert plot.view_model is view
    assert plot.view_model.display_sample_count == count
    assert plotted_count == count
    assert path.elementCount() == count
    plot.close()
    qapp.processEvents()


def test_manual_y_range_path_is_clipped_before_the_inter_lane_gap(qapp):
    resolved = app_main.recorder_control.ResolvedRecorderRequest(
        signals=("Position",),
        requested_resolution_us=200.0,
        actual_resolution_us=200.0,
        time_resolution=2,
        requested_record_time_s=0.0004,
        actual_record_time_s=0.0004,
        length_per_signal=2,
        total_buffer_samples=2,
        trigger="immediate",
    )
    view = app_main.recorder_view.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Position": [0.5, -2.0]},
        resolved=resolved,
        binding=app_main.recorder_view.CaptureBinding(
            "capture-clip", 1, "sha256:test-drive"),
    )
    layout = app_main.recorder_view.ViewLayout((
        app_main.recorder_view.LaneLayout(
            ("Position",), True, (0.0, 1.0)),
        app_main.recorder_view.LaneLayout(),
    ))
    plot = app_main.RecorderPlotWidget()
    plot.resize(720, 390)
    plot.set_view_model(view, layout)
    target = QtGui.QPixmap(plot.size())

    plot.render(target)

    image = target.toImage()
    signal = QtGui.QColor(app_main.theme.C_BLUE)
    # With the widget's fixed 390 px test geometry, y=184..200 is the gap
    # immediately below Chart 1.  A below-range segment must not enter it.
    bleed = any(
        abs(image.pixelColor(x, y).red() - signal.red())
        + abs(image.pixelColor(x, y).green() - signal.green())
        + abs(image.pixelColor(x, y).blue() - signal.blue()) < 20
        for y in range(184, 201)
        for x in range(76, 703)
    )
    assert not bleed
    plot.close()
    qapp.processEvents()


def test_validated_capture_uses_one_immutable_evidence_snapshot(window):
    data, resolved = _validated_bundle(window)
    data["dt"] = 9.0
    data["Position Feedback"][0] = 999.0
    data["Actual Velocity"].append(2.0)

    assert window._recorder_capture_evidence.view is window._recorder_view_model
    assert window._recorder_last_resolved is resolved
    assert window._recorder_last_data["dt"] == pytest.approx(0.0002)
    assert window._recorder_last_data["Position Feedback"] == (10.0, 11.0, 12.0)
    assert window._recorder_last_data["Actual Velocity"] == (-1.0, 0.0, 1.0)
    with pytest.raises(TypeError):
        window._recorder_last_data["dt"] = 1.0


def test_new_capture_invalidates_old_plot_before_worker_enqueue(window):
    _validated_bundle(window)
    spy = _RecorderWorkerSpy()
    window.worker = spy
    window._recorder_signals_target = spy
    window.rec_signal_list.clear()
    item = QtWidgets.QListWidgetItem("Position Feedback")
    item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
    item.setCheckState(QtCore.Qt.CheckState.Checked)
    window.rec_signal_list.addItem(item)

    window._recorder_immediate_clicked()

    assert len(spy.starts) == 1
    assert window._recorder_view_model is None
    assert window.recorder_plot.view_model is None
    assert not window.btn_rec_view_tab.isEnabled()
    assert window.recorder_page_stack.currentIndex() == 0


def test_disconnect_retains_capture_only_as_historical_offline_evidence(window):
    _validated_bundle(window)
    model = window._recorder_view_model

    window._invalidate_recorder_target_ui("Drive disconnected")

    assert window._recorder_view_model is model
    assert not window._recorder_view_is_current
    assert window.btn_rec_view_tab.isEnabled()
    assert "HISTORICAL" in window.lbl_rec_view_status.text()
    assert "Drive disconnected" in window.lbl_rec_view_status.toolTip()


def test_direct_stale_bundle_replay_cannot_repromote_historical_capture(window):
    data, resolved = _validated_bundle(window)
    model = window._recorder_view_model
    window._invalidate_recorder_target_ui("Drive disconnected")

    window._on_recorder_data(data, resolved)

    assert window._recorder_view_model is model
    assert not window._recorder_view_is_current
    assert "HISTORICAL / OFFLINE" in window.lbl_rec_view_status.text()


def test_offline_bundle_injection_helper_is_unavailable_in_normal_runtime(
        window, monkeypatch):
    resolved = _resolved("Position Feedback")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(app_main.sys, "argv", ["main.py"])

    with pytest.raises(RuntimeError, match="pytest/smoke"):
        window._inject_recorder_data_for_offline_test(
            {"dt": 0.0002, "Position Feedback": [1.0, 2.0, 3.0]},
            resolved,
        )

    assert window._recorder_view_model is None


def test_delayed_same_worker_data_cannot_repromote_historical_capture(window):
    class _Emitter(QtCore.QObject):
        recorder_data = QtCore.pyqtSignal(object, object, object)

        @staticmethod
        def isRunning():
            return True

    emitter = _Emitter()
    window.worker = emitter
    emitter.recorder_data.connect(window._on_recorder_data)
    resolved = _resolved("Position Feedback")
    data = {"dt": 0.0002, "Position Feedback": [1.0, 2.0, 3.0]}
    token = {"capture_id": "capture-delay-001", "worker_generation": 7}
    window._recorder_manifest_data = {
        "capture_id": token["capture_id"],
        "completion": "VALIDATED",
        "worker_generation": token["worker_generation"],
        "signals": list(resolved.signals),
        "length_per_signal": resolved.length_per_signal,
        "actual_resolution_us": resolved.actual_resolution_us,
        "drive_identity": "sha256:test-drive",
    }
    window._recorder_manifest_ui_generation = window._recorder_view_generation
    window._recorder_expected_worker_generation = token["worker_generation"]
    emitter.recorder_data.emit(data, resolved, token)
    assert window._recorder_view_is_current

    window._invalidate_recorder_target_ui("Drive disconnected")
    assert not window._recorder_view_is_current
    assert "HISTORICAL" in window.lbl_rec_view_status.text()

    emitter.recorder_data.emit(data, resolved, token)

    assert not window._recorder_view_is_current
    assert window._recorder_view_model is None
    assert not window.btn_rec_view_tab.isEnabled()
    assert "stale" in window.recorder_log.toPlainText().lower()


def test_stale_manifest_generation_cannot_authorize_new_capture_data(window):
    resolved = _resolved("Position Feedback")
    window._recorder_manifest_data = {
        "capture_id": "capture-stale-001",
        "completion": "VALIDATED",
        "signals": list(resolved.signals),
        "length_per_signal": resolved.length_per_signal,
        "actual_resolution_us": resolved.actual_resolution_us,
        "drive_identity": "sha256:test-drive",
    }
    window._recorder_manifest_ui_generation = window._recorder_view_generation

    # A new target/capture generation supersedes the accepted manifest before
    # its data callback arrives.  The old bundle must fail closed.
    window._recorder_view_generation += 1
    window._inject_recorder_data_for_offline_test(
        {"dt": 0.0002, "Position Feedback": [1.0, 2.0, 3.0]}, resolved)

    assert window._recorder_view_model is None
    assert not window.btn_rec_view_tab.isEnabled()
    assert not window.btn_rec_export.isEnabled()
    assert "stale" in window.recorder_log.toPlainText().lower()


def test_completion_token_must_match_the_manifest_bundle(window):
    resolved = _resolved("Position Feedback")
    window._recorder_manifest_data = {
        "capture_id": "capture-current-001",
        "completion": "VALIDATED",
        "worker_generation": 7,
        "signals": list(resolved.signals),
        "length_per_signal": resolved.length_per_signal,
        "actual_resolution_us": resolved.actual_resolution_us,
        "drive_identity": "sha256:test-drive",
    }
    window._recorder_manifest_ui_generation = window._recorder_view_generation
    window._recorder_expected_worker_generation = 7

    window._inject_recorder_data_for_offline_test(
        {"dt": 0.0002, "Position Feedback": [1.0, 2.0, 3.0]},
        resolved,
        {"capture_id": "capture-stale-999", "worker_generation": 6},
    )

    assert window._recorder_view_model is None
    assert not window.btn_rec_view_tab.isEnabled()
    assert "token" in window.recorder_log.toPlainText().lower()


def test_recorder_manifest_hashes_the_view_implementation():
    class _Link:
        @staticmethod
        def recorder_personality_provenance():
            return {}

        @staticmethod
        def recorder_library_provenance():
            return {}

    resolved = _resolved("Position Feedback")
    manifest = app_main.DriveWorker("COM_TEST")._build_recorder_manifest(
        _Link(), resolved)
    view_path = Path(app_main.__file__).with_name("recorder_view.py")

    assert manifest["app_source_sha256"]["recorder_view.py"] == hashlib.sha256(
        view_path.read_bytes()).hexdigest()


def _plot_mouse_event(event_type, x, y, *, button, buttons):
    point = QtCore.QPointF(float(x), float(y))
    return QtGui.QMouseEvent(
        event_type,
        point,
        point,
        button,
        buttons,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


def test_time_plot_drag_snaps_a_to_original_sample_and_commits_statistics_once(
        window, monkeypatch):
    class _PoisonWorker:
        def __getattr__(self, name):
            raise AssertionError("marker drag touched worker.%s" % name)

    _validated_bundle(window)
    plot = window.recorder_plot
    plot.resize(720, 390)
    window.worker = _PoisonWorker()
    window.btn_rec_stats_calculate.click()
    assert window._recorder_statistics_model is not None
    assert window.btn_rec_stats_export.isEnabled()
    real_builder = app_main.recorder_view.build_sample_range_statistics
    build_calls = []

    def counted_builder(*args, **kwargs):
        build_calls.append((args, kwargs))
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(
        app_main.recorder_view,
        "build_sample_range_statistics",
        counted_builder,
    )
    lane_y = 70.0
    left_x = 76.0
    middle_x = 76.0 + (720.0 - 76.0 - 18.0) / 2.0

    plot.mousePressEvent(_plot_mouse_event(
        QtCore.QEvent.Type.MouseButtonPress,
        left_x + 1.0,
        lane_y,
        button=QtCore.Qt.MouseButton.LeftButton,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    ))
    plot.mouseMoveEvent(_plot_mouse_event(
        QtCore.QEvent.Type.MouseMove,
        middle_x,
        lane_y,
        button=QtCore.Qt.MouseButton.NoButton,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    ))

    assert window.spin_rec_range_start.value() == 1
    assert window.spin_rec_range_end.value() == 2
    assert window._recorder_range_selection.start_index == 1
    assert window._recorder_statistics_model is None
    assert not window.btn_rec_stats_export.isEnabled()
    assert build_calls == []

    plot.mouseReleaseEvent(_plot_mouse_event(
        QtCore.QEvent.Type.MouseButtonRelease,
        middle_x,
        lane_y,
        button=QtCore.Qt.MouseButton.LeftButton,
        buttons=QtCore.Qt.MouseButton.NoButton,
    ))

    assert len(build_calls) == 1
    assert window._recorder_statistics_model is not None
    assert window._recorder_statistics_model.scope == "sample_range"
    assert window._recorder_statistics_model.selection.start_index == 1
    assert window._recorder_statistics_model.selection.end_index == 2
    assert window.btn_rec_stats_export.isEnabled()


def test_time_plot_drag_is_disabled_in_fft_mode(window, monkeypatch):
    _validated_bundle(window)
    plot = window.recorder_plot
    plot.resize(720, 390)
    before = window._recorder_range_selection
    build_calls = []
    monkeypatch.setattr(
        app_main.recorder_view,
        "build_sample_range_statistics",
        lambda *args, **kwargs: build_calls.append((args, kwargs)),
    )
    window.btn_rec_view_fft.click()

    plot.mousePressEvent(_plot_mouse_event(
        QtCore.QEvent.Type.MouseButtonPress,
        77.0,
        70.0,
        button=QtCore.Qt.MouseButton.LeftButton,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    ))
    plot.mouseMoveEvent(_plot_mouse_event(
        QtCore.QEvent.Type.MouseMove,
        389.0,
        70.0,
        button=QtCore.Qt.MouseButton.NoButton,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    ))
    plot.mouseReleaseEvent(_plot_mouse_event(
        QtCore.QEvent.Type.MouseButtonRelease,
        389.0,
        70.0,
        button=QtCore.Qt.MouseButton.LeftButton,
        buttons=QtCore.Qt.MouseButton.NoButton,
    ))

    assert window._recorder_range_selection == before
    assert build_calls == []


def test_time_plot_does_not_hit_an_unpainted_marker_just_outside_viewport(window):
    _validated_bundle(window)
    plot = window.recorder_plot
    plot.resize(720, 390)
    before = window._recorder_range_selection
    window.edit_rec_time_start.setText("0.000001")
    window.edit_rec_time_end.setText("0.0004")
    window.btn_rec_time_apply_all.click()
    assert plot.layout_model.x_range_s == pytest.approx((0.000001, 0.0004))
    assert before.start_time_s < plot.layout_model.x_range_s[0]

    plot.mousePressEvent(_plot_mouse_event(
        QtCore.QEvent.Type.MouseButtonPress,
        76.0,
        70.0,
        button=QtCore.Qt.MouseButton.LeftButton,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    ))
    plot.mouseMoveEvent(_plot_mouse_event(
        QtCore.QEvent.Type.MouseMove,
        200.0,
        70.0,
        button=QtCore.Qt.MouseButton.NoButton,
        buttons=QtCore.Qt.MouseButton.LeftButton,
    ))
    plot.mouseReleaseEvent(_plot_mouse_event(
        QtCore.QEvent.Type.MouseButtonRelease,
        200.0,
        70.0,
        button=QtCore.Qt.MouseButton.LeftButton,
        buttons=QtCore.Qt.MouseButton.NoButton,
    ))

    assert window._recorder_range_selection == before
    assert window.spin_rec_range_start.value() == 0
    assert window.spin_rec_range_end.value() == 2
    assert window._recorder_statistics_model is None


def test_statistics_csv_button_tracks_exact_result_and_exports_current_or_historical(
        window, monkeypatch, tmp_path):
    class _PoisonWorker:
        def __getattr__(self, name):
            raise AssertionError("statistics export touched worker.%s" % name)

    _validated_bundle(window)
    assert not window.btn_rec_stats_export.isEnabled()
    window.spin_rec_range_start.setValue(1)
    window.btn_rec_range_calculate.click()
    assert window.btn_rec_stats_export.isEnabled()

    current_path = tmp_path / "current-statistics.csv"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(current_path), "CSV (*.csv)"),
    )
    window.btn_rec_stats_export.click()

    with current_path.open("r", encoding="utf-8", newline="") as handle:
        current_rows = list(csv.DictReader(handle))
    assert current_rows
    assert all(row["authority"] == "current" for row in current_rows)
    assert all(row["capture_id"] == "capture-test-001" for row in current_rows)

    window._invalidate_recorder_target_ui("Drive disconnected")
    assert window.btn_rec_stats_export.isEnabled()
    window.worker = _PoisonWorker()
    historical_path = tmp_path / "historical-statistics.csv"
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(historical_path), "CSV (*.csv)"),
    )
    window.btn_rec_stats_export.click()

    with historical_path.open("r", encoding="utf-8", newline="") as handle:
        historical_rows = list(csv.DictReader(handle))
    assert historical_rows
    assert all(row["authority"] == "historical_offline"
               for row in historical_rows)

    window.spin_rec_range_start.setValue(0)
    assert window._recorder_statistics_model is None
    assert not window.btn_rec_stats_export.isEnabled()


def test_statistics_csv_aborts_if_modal_dialog_replaces_exact_source_view(
        window, monkeypatch, tmp_path):
    _validated_bundle(window)
    window.btn_rec_stats_calculate.click()
    old_view = window._recorder_view_model
    old_result = window._recorder_statistics_model
    path = tmp_path / "must-not-exist.csv"
    new_view = app_main.recorder_view.build_capture_view(
        state="COMPLETED",
        data={
            "dt": 0.0002,
            "Position Feedback": [20.0, 21.0, 22.0],
            "Actual Velocity": [2.0, 3.0, 4.0],
        },
        resolved=_resolved("Position Feedback", "Actual Velocity"),
        binding=app_main.recorder_view.CaptureBinding(
            "capture-new", 99, "sha256:test-drive"),
    )
    flashes = []
    monkeypatch.setattr(window, "_flash", flashes.append)

    def replace_capture_during_dialog(*_args, **_kwargs):
        window._recorder_view_generation += 1
        window._recorder_view_model = new_view
        window._recorder_capture_evidence = None
        window._recorder_statistics_model = None
        window._recorder_statistics_source_view = None
        window._recorder_view_is_current = True
        window.btn_rec_stats_export.setEnabled(False)
        return str(path), "CSV (*.csv)"

    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        replace_capture_during_dialog,
    )

    window._recorder_export_statistics_csv()

    assert old_result is not None
    assert not path.exists()
    assert window._recorder_view_model is new_view
    assert window._recorder_statistics_model is None
    assert not window.btn_rec_stats_export.isEnabled()
    assert flashes and "changed" in flashes[-1].lower()


def test_feedback_controls_are_preview_only_until_registry_exists(window):
    window._set_connected_ui(True)

    assert not window.cmb_sensor.isEnabled()
    assert not window.cmb_commut.isEnabled()
    assert not window.fb_fields["counts"].isEnabled()
    assert not window.btn_fb_write.isEnabled()
    assert all(
        not widget.isEnabled()
        for field, widget in window._fb_dyn_fields.values()
        if field["editable"]
    )
    note = window.fb_note.text()
    assert "Preview only" in note
    assert "전송되지" in note
