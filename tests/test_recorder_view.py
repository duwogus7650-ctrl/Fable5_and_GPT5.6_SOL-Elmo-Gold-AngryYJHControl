from dataclasses import FrozenInstanceError, replace
import csv
import cmath
import hashlib
import json
import math

import pytest

import recorder_control as rc
import recorder_view as rv


def resolved(signals=("Position [cnt]", "Velocity [cnt/s]"), count=5):
    dt_us = 200.0
    return rc.ResolvedRecorderRequest(
        signals=tuple(signals),
        requested_resolution_us=dt_us,
        actual_resolution_us=dt_us,
        time_resolution=4,
        requested_record_time_s=count * dt_us * 1e-6,
        actual_record_time_s=count * dt_us * 1e-6,
        length_per_signal=count,
        total_buffer_samples=count * len(signals),
        trigger="immediate",
    )


def binding():
    return rv.CaptureBinding(
        capture_id="capture-001", generation=7, drive_identity="gold-twitter-A")


def capture_data(signals=("Position [cnt]", "Velocity [cnt/s]"), count=5):
    data = {"dt": 0.0002}
    for channel_index, name in enumerate(signals):
        data[name] = [float(channel_index * 10 + i) for i in range(count)]
    return data


def test_completed_capture_is_validated_bound_and_copied_immutably():
    request = resolved()
    raw = capture_data()

    view = rv.build_capture_view(
        state="COMPLETED", data=raw, resolved=request, binding=binding())

    assert view.binding == binding()
    assert view.capture_id == "capture-001"
    assert view.generation == 7
    assert view.drive_identity == "gold-twitter-A"
    assert view.signals == request.signals
    assert view.x_s == pytest.approx((0.0, 0.0002, 0.0004, 0.0006, 0.0008))
    assert view.signal_names == request.signals
    assert view.source_sample_count == 5
    assert view.display_sample_count == 5
    assert view.units == "personality-owned; not inferred"
    assert view.series[0].name == "Position [cnt]"
    assert view.series[0].x == pytest.approx((0.0, 0.0002, 0.0004, 0.0006, 0.0008))
    assert view.series[0].y == (0.0, 1.0, 2.0, 3.0, 4.0)
    assert isinstance(view.series[0].x, tuple)
    assert isinstance(view.series[0].y, tuple)

    raw["Position [cnt]"][0] = 999.0
    assert view.series[0].y[0] == 0.0
    with pytest.raises(FrozenInstanceError):
        view.source_sample_count = 99


@pytest.mark.parametrize("state", ["IDLE", "RECORDING", "READY_TO_UPLOAD", "completed"])
def test_capture_view_rejects_every_state_except_exact_completed(state):
    with pytest.raises(rv.RecorderViewError, match="COMPLETED"):
        rv.build_capture_view(
            state=state, data=capture_data(), resolved=resolved(), binding=binding())


def test_capture_view_rejects_non_resolved_or_invalid_capture_via_shared_validator():
    with pytest.raises(rv.RecorderViewError, match="ResolvedRecorderRequest"):
        rv.build_capture_view(
            state="COMPLETED", data=capture_data(), resolved=object(), binding=binding())

    bad = capture_data()
    bad["dt"] = 0.001
    with pytest.raises(rv.RecorderViewError, match="disagrees"):
        rv.build_capture_view(
            state="COMPLETED", data=bad, resolved=resolved(), binding=binding())

    bad = capture_data()
    bad["Velocity [cnt/s]"][2] = float("nan")
    with pytest.raises(rv.RecorderViewError, match="non-finite"):
        rv.build_capture_view(
            state="COMPLETED", data=bad, resolved=resolved(), binding=binding())


@pytest.mark.parametrize(
    "bad_binding",
    [
        rv.CaptureBinding("", 7, "drive"),
        rv.CaptureBinding("capture", 0, "drive"),
        rv.CaptureBinding("capture", True, "drive"),
        rv.CaptureBinding("capture", 7, ""),
    ],
)
def test_capture_binding_requires_nonempty_id_positive_generation_and_drive(bad_binding):
    with pytest.raises(rv.RecorderViewError, match="binding"):
        rv.build_capture_view(
            state="COMPLETED", data=capture_data(), resolved=resolved(),
            binding=bad_binding)


def test_full_capture_statistics_match_known_eas_definitions_and_signal_order():
    request = resolved(signals=("Signal A", "Signal B"), count=4)
    raw = {
        "dt": 0.0002,
        "Signal A": [1.0, 2.0, 3.0, 4.0],
        "Signal B": [-2.0, -2.0, -2.0, -2.0],
    }
    view = rv.build_capture_view(
        state="COMPLETED", data=raw, resolved=request, binding=binding())
    original_series = view.series

    result = rv.build_full_capture_statistics(view)

    assert result.binding == view.binding
    assert result.scope == "full_capture"
    assert result.units == "personality-owned; not inferred"
    assert tuple(row.name for row in result.rows) == request.signals
    first, second = result.rows
    assert first.sample_count == 4
    assert first.minimum == 1.0
    assert first.maximum == 4.0
    assert first.average == pytest.approx(2.5)
    assert first.rms_ac == pytest.approx(math.sqrt(1.25))
    assert first.rms_dc == pytest.approx(math.sqrt(7.5))
    assert first.tolerance == 3.0
    assert first.tolerance_percent == pytest.approx(60.0)
    assert second.sample_count == 4
    assert second.minimum == second.maximum == second.average == -2.0
    assert second.rms_ac == 0.0
    assert second.rms_dc == 2.0
    assert second.tolerance == 0.0
    assert second.tolerance_percent == 0.0
    assert view.series is original_series
    assert view.series[0].y == (1.0, 2.0, 3.0, 4.0)


def test_full_capture_statistics_handle_zero_mean_and_full_16k_capture():
    count = rc.RECORDER_BUFFER_SAMPLES
    request = resolved(signals=("Signal",), count=count)
    samples = tuple((-1.0, 0.0, 1.0)[index % 3] for index in range(count))
    view = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Signal": samples},
        resolved=request,
        binding=binding(),
    )

    row = rv.build_full_capture_statistics(view).rows[0]

    expected_mean = math.fsum(samples) / count
    expected_rms_dc = math.sqrt(math.fsum(v * v for v in samples) / count)
    expected_rms_ac = math.sqrt(
        math.fsum((v - expected_mean) ** 2 for v in samples) / count)
    assert row.sample_count == count
    assert row.average == pytest.approx(expected_mean)
    assert row.rms_ac == pytest.approx(expected_rms_ac)
    assert row.rms_dc == pytest.approx(expected_rms_dc)
    assert row.tolerance == 2.0


def test_full_capture_statistics_use_scaled_math_and_fail_closed_on_overflow():
    stable_request = resolved(signals=("Signal",), count=2)
    stable = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Signal": [1e308, 1e308]},
        resolved=stable_request,
        binding=binding(),
    )

    stable_row = rv.build_full_capture_statistics(stable).rows[0]

    assert stable_row.average == pytest.approx(1e308)
    assert stable_row.rms_ac == 0.0
    assert stable_row.rms_dc == pytest.approx(1e308)
    assert stable_row.tolerance == 0.0

    unrepresentable = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Signal": [-1e308, 1e308]},
        resolved=stable_request,
        binding=binding(),
    )
    with pytest.raises(rv.RecorderViewError, match="not representable"):
        rv.build_full_capture_statistics(unrepresentable)


def test_full_capture_statistics_preserve_small_mean_and_high_offset_ac_rms():
    cancellation_samples = (8e307, -8e307, 1e-308)
    cancellation_request = resolved(signals=("Signal",), count=3)
    cancellation_view = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Signal": cancellation_samples},
        resolved=cancellation_request,
        binding=binding(),
    )

    cancellation_row = rv.build_full_capture_statistics(
        cancellation_view).rows[0]

    expected_mean = math.fsum(cancellation_samples) / 3
    assert expected_mean != 0.0
    assert cancellation_row.average == expected_mean
    assert math.isfinite(cancellation_row.rms_ac)
    assert math.isfinite(cancellation_row.rms_dc)
    assert cancellation_row.tolerance == 1.6e308

    high_offset_samples = (1_000_000_000.0, 1_000_000_000.000001)
    high_offset_request = resolved(signals=("Signal",), count=2)
    high_offset_view = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Signal": high_offset_samples},
        resolved=high_offset_request,
        binding=binding(),
    )

    high_offset_row = rv.build_full_capture_statistics(high_offset_view).rows[0]

    exact_float_delta = high_offset_samples[1] - high_offset_samples[0]
    assert high_offset_row.average == math.fsum(high_offset_samples) / 2
    assert high_offset_row.rms_ac == exact_float_delta / 2


def test_full_capture_statistics_reject_decimated_or_unstructured_view():
    request = resolved(signals=("Signal",), count=8)
    full = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Signal": list(range(8))},
        resolved=request,
        binding=binding(),
    )
    decimated = rv.decimate_view(full, max_points=4)

    with pytest.raises(rv.RecorderViewError, match="full capture"):
        rv.build_full_capture_statistics(decimated)
    with pytest.raises(rv.RecorderViewError, match="CaptureView"):
        rv.build_full_capture_statistics(object())

    one_request = resolved(signals=("Signal",), count=1)
    one = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Signal": [7.0]},
        resolved=one_request,
        binding=binding(),
    )
    with pytest.raises(rv.RecorderViewError, match="at least two"):
        rv.build_full_capture_statistics(one)


def test_sample_range_statistics_are_inclusive_and_bind_endpoint_values():
    request = resolved(signals=("Signal A", "Signal B"), count=5)
    view = rv.build_capture_view(
        state="COMPLETED",
        data={
            "dt": 0.0002,
            "Signal A": [100.0, 1.0, 2.0, 3.0, 200.0],
            "Signal B": [99.0, -1.0, 0.0, 1.0, 98.0],
        },
        resolved=request,
        binding=binding(),
    )

    result = rv.build_sample_range_statistics(
        view, start_index=1, end_index=3)

    assert result.binding == view.binding
    assert result.scope == "sample_range"
    assert result.selection.binding == view.binding
    assert result.selection.start_index == 1
    assert result.selection.end_index == 3
    assert result.selection.start_time_s == pytest.approx(0.0002)
    assert result.selection.end_time_s == pytest.approx(0.0006)
    assert result.selection.delta_time_s == pytest.approx(0.0004)
    assert result.selection.sample_count == 3
    assert tuple(row.name for row in result.rows) == request.signals
    first, zero_mean = result.rows
    assert first.sample_count == 3
    assert first.minimum == 1.0
    assert first.maximum == 3.0
    assert first.average == 2.0
    assert first.rms_ac == pytest.approx(math.sqrt(2.0 / 3.0))
    assert first.rms_dc == pytest.approx(math.sqrt(14.0 / 3.0))
    assert first.tolerance == 2.0
    assert first.tolerance_percent == pytest.approx(50.0)
    assert zero_mean.average == 0.0
    assert zero_mean.tolerance == 2.0
    assert zero_mean.tolerance_percent == 0.0
    assert tuple(endpoint.name for endpoint in result.endpoints) == request.signals
    assert result.endpoints[0].start_value == 1.0
    assert result.endpoints[0].end_value == 3.0
    assert result.endpoints[0].delta_value == 2.0
    assert result.endpoints[1].start_value == -1.0
    assert result.endpoints[1].end_value == 1.0
    assert result.endpoints[1].delta_value == 2.0
    assert view.series[0].y == (100.0, 1.0, 2.0, 3.0, 200.0)


@pytest.mark.parametrize(
    "start_index,end_index,error",
    [
        (0, 0, "start before end"),
        (3, 1, "start before end"),
        (-1, 2, "within the full capture"),
        (1, 5, "within the full capture"),
        (True, 2, "integer sample indexes"),
        (1.0, 2, "integer sample indexes"),
        ("1", 2, "integer sample indexes"),
    ],
)
def test_sample_range_statistics_reject_ambiguous_or_out_of_capture_ranges(
        start_index, end_index, error):
    request = resolved(signals=("Signal",), count=5)
    view = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Signal": [0.0, 1.0, 2.0, 3.0, 4.0]},
        resolved=request,
        binding=binding(),
    )

    with pytest.raises(rv.RecorderViewError, match=error):
        rv.build_sample_range_statistics(
            view, start_index=start_index, end_index=end_index)


def test_sample_range_statistics_reject_decimated_view_and_lock_unrepresentable_percent():
    request = resolved(signals=("Signal",), count=4)
    view = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Signal": [0.0, 1.0, 2.0, 3.0]},
        resolved=request,
        binding=binding(),
    )
    decimated = rv.decimate_view(view, max_points=2)

    with pytest.raises(rv.RecorderViewError, match="full capture"):
        rv.build_sample_range_statistics(
            decimated, start_index=0, end_index=1)

    tiny_mean_request = resolved(signals=("Tiny Mean",), count=3)
    tiny_mean_view = rv.build_capture_view(
        state="COMPLETED",
        data={
            "dt": 0.0002,
            "Tiny Mean": [-1.0, 1.0, 1e-308],
        },
        resolved=tiny_mean_request,
        binding=binding(),
    )
    row = rv.build_sample_range_statistics(
        tiny_mean_view, start_index=0, end_index=2).rows[0]

    assert row.average != 0.0
    assert row.tolerance_percent is None


def test_full_range_rows_equal_full_wrapper_and_negative_mean_percent_is_absolute():
    request = resolved(signals=("Negative",), count=4)
    view = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Negative": [-4.0, -3.0, -2.0, -1.0]},
        resolved=request,
        binding=binding(),
    )

    full = rv.build_full_capture_statistics(view)
    selected = rv.build_sample_range_statistics(
        view, start_index=0, end_index=3)

    assert selected.rows == full.rows
    assert selected.rows[0].average == -2.5
    assert selected.rows[0].tolerance_percent == pytest.approx(60.0)
    assert selected.selection.sample_count == 4
    assert selected.endpoints[0].start_value == -4.0
    assert selected.endpoints[0].end_value == -1.0


def test_fft_known_truth_preserves_dc_and_one_sided_sine_amplitude():
    count = 16
    bin_index = 2
    request = resolved(signals=("Signal",), count=count)
    raw = {
        "dt": 0.0002,
        "Signal": [
            3.0 + 2.0 * math.sin(2.0 * math.pi * bin_index * i / count)
            for i in range(count)
        ],
    }
    view = rv.build_capture_view(
        state="COMPLETED", data=raw, resolved=request, binding=binding())

    spectrum = rv.build_spectrum_view(view)

    assert spectrum.binding == view.binding
    assert spectrum.signals == ("Signal",)
    assert spectrum.input_sample_count == count
    assert spectrum.dt_s == pytest.approx(0.0002)
    assert spectrum.frequency_resolution_hz == pytest.approx(312.5)
    assert spectrum.nyquist_hz == pytest.approx(2500.0)
    assert spectrum.processing == (
        "one-sided amplitude; rectangular; DC included; full capture")
    assert spectrum.units == "personality-owned amplitude; not inferred"
    assert spectrum.x_hz == pytest.approx(tuple(312.5 * i for i in range(9)))
    assert spectrum.series[0].y[0] == pytest.approx(3.0, abs=1e-12)
    assert spectrum.series[0].y[bin_index] == pytest.approx(2.0, abs=1e-12)
    assert max(
        value for i, value in enumerate(spectrum.series[0].y)
        if i not in (0, bin_index)
    ) < 1e-12


def test_fft_nyquist_bin_is_not_doubled_and_zero_scale_starts_at_zero():
    count = 16
    amplitude = 1.5
    request = resolved(signals=("Signal",), count=count)
    view = rv.build_capture_view(
        state="COMPLETED",
        data={
            "dt": 0.0002,
            "Signal": [amplitude * ((-1.0) ** i) for i in range(count)],
        },
        resolved=request,
        binding=binding(),
    )

    spectrum = rv.build_spectrum_view(view)

    assert spectrum.x_hz[-1] == pytest.approx(spectrum.nyquist_hz)
    assert spectrum.series[0].y[-1] == pytest.approx(amplitude, abs=1e-12)
    assert rv.spectrum_zero_scale_bounds(spectrum.series) == pytest.approx(
        (0.0, amplitude))


def test_fft_odd_length_matches_independent_direct_dft_oracle():
    samples = (0.2, -1.0, 3.0, 0.5, 2.0)
    count = len(samples)
    request = resolved(signals=("Signal",), count=count)
    view = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Signal": samples},
        resolved=request,
        binding=binding(),
    )

    spectrum = rv.build_spectrum_view(view)
    expected = []
    for k in range(count // 2 + 1):
        raw_bin = sum(
            samples[n] * cmath.exp(-2j * math.pi * k * n / count)
            for n in range(count)
        )
        magnitude = abs(raw_bin) / count
        if k > 0:
            magnitude *= 2.0
        expected.append(magnitude)

    assert spectrum.series[0].y == pytest.approx(expected, abs=1e-12)
    assert spectrum.x_hz[-1] < spectrum.nyquist_hz


def test_fft_zero_signal_is_exact_and_does_not_mutate_capture():
    count = 8
    request = resolved(signals=("Signal",), count=count)
    raw = {"dt": 0.0002, "Signal": [0.0] * count}
    view = rv.build_capture_view(
        state="COMPLETED", data=raw, resolved=request, binding=binding())
    before = view.series[0]

    spectrum = rv.build_spectrum_view(view)

    assert spectrum.series[0].y == (0.0,) * 5
    assert rv.spectrum_zero_scale_bounds(spectrum.series) == (0.0, 0.0)
    assert view.series[0] is before
    assert view.series[0].y == (0.0,) * count


def test_fft_rejects_single_sample_nonuniform_time_and_nonfinite_result():
    one_request = resolved(signals=("Signal",), count=1)
    one = rv.build_capture_view(
        state="COMPLETED", data={"dt": 0.0002, "Signal": [1.0]},
        resolved=one_request, binding=binding())
    with pytest.raises(rv.RecorderViewError, match="at least two"):
        rv.build_spectrum_view(one)

    nonuniform = rv.CaptureView(
        binding=binding(),
        series=(rv.SignalSeries(
            "Signal", (0.0, 0.0002, 0.00041), (1.0, 2.0, 3.0)),),
        source_sample_count=3,
    )
    with pytest.raises(rv.RecorderViewError, match="uniform"):
        rv.build_spectrum_view(nonuniform)

    huge_request = resolved(signals=("Signal",), count=16)
    huge = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Signal": [1e308] * 16},
        resolved=huge_request,
        binding=binding(),
    )
    with pytest.raises(rv.RecorderViewError, match="non-finite"):
        rv.build_spectrum_view(huge)


def test_fft_rejects_last_interval_drift_even_on_a_long_capture():
    count = rc.RECORDER_BUFFER_SAMPLES
    dt_s = 0.0002
    x_values = [index * dt_s for index in range(count)]
    x_values[-1] += 1e-9
    drifted = rv.CaptureView(
        binding=binding(),
        series=(rv.SignalSeries(
            "Signal", tuple(x_values), (0.0,) * count),),
        source_sample_count=count,
    )

    with pytest.raises(rv.RecorderViewError, match="uniform"):
        rv.build_spectrum_view(drifted)


@pytest.mark.parametrize(
    "x_values",
    [
        (0.0, 1e-309, 2e-309, 3e-309),
        (0.0, 1e308),
    ],
)
def test_fft_rejects_nonfinite_or_degenerate_derived_frequency_axis(x_values):
    extreme = rv.CaptureView(
        binding=binding(),
        series=(rv.SignalSeries(
            "Signal", x_values, (0.0,) * len(x_values)),),
        source_sample_count=len(x_values),
    )

    with pytest.raises(rv.RecorderViewError, match="frequency axis"):
        rv.build_spectrum_view(extreme)


def test_fft_full_16k_capture_has_exact_rfft_bin_count():
    count = rc.RECORDER_BUFFER_SAMPLES
    request = resolved(signals=("Signal",), count=count)
    view = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Signal": [0.0] * count},
        resolved=request,
        binding=binding(),
    )

    spectrum = rv.build_spectrum_view(view)

    assert len(spectrum.x_hz) == count // 2 + 1
    assert len(spectrum.series[0].y) == count // 2 + 1
    assert spectrum.series[0].x is spectrum.x_hz


@pytest.mark.parametrize(
    "value, span, expected",
    [
        (0.0005, 0.0009, "5.000e-04"),
        (0.0, 0.0009, "0.000e+00"),
        (-0.0005, 0.0009, "-5.000e-04"),
        (0.0, 0.0, "0"),
        (0.0005, 0.001, "0.0005"),
        (12.3456789, 10.0, "12.3457"),
    ],
)
def test_axis_formatter_uses_exponential_only_for_ranges_below_threshold(
        value, span, expected):
    assert rv.format_axis_value(value, axis_span=span) == expected


def test_axis_formatter_rejects_nonfinite_or_boolean_input():
    for value, span in (
        (float("nan"), 1.0), (1.0, float("inf")), (True, 1.0), (1.0, False),
    ):
        with pytest.raises(rv.RecorderViewError, match="axis"):
            rv.format_axis_value(value, axis_span=span)


def test_two_lane_layout_roundtrips_exact_order_visibility_and_range(tmp_path):
    channels = ("Position [cnt]", "Velocity [cnt/s]", "Active Current [A]")
    layout = rv.ViewLayout(lanes=(
        rv.LaneLayout(
            channels=("Velocity [cnt/s]",),
            visible=True,
            y_range=None,
        ),
        rv.LaneLayout(
            channels=("Active Current [A]",),
            visible=False,
            y_range=(-2.5, 3.5),
        ),
    ))
    path = tmp_path / "scope.ayview.json"

    rv.save_layout(path, layout, available_channels=channels)
    loaded = rv.load_layout(path, available_channels=channels)

    assert loaded == layout
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == rv.VIEW_LAYOUT_SCHEMA
    assert payload["compatibility"] == "local-only; not EAS-compatible"
    assert payload["plot_mode"] == rv.PLOT_MODE_TIME
    assert payload["lanes"][0]["channels"] == ["Velocity [cnt/s]"]
    assert payload["lanes"][0]["y_range"] == "auto"
    assert payload["lanes"][1]["y_range"] == [-2.5, 3.5]


def test_time_window_roundtrips_and_legacy_layout_defaults_to_full_range():
    channels = ("Position", "Velocity")
    layout = rv.ViewLayout(
        lanes=(rv.LaneLayout(("Position",)), rv.LaneLayout(("Velocity",))),
        x_range_s=(0.0002, 0.0006),
    )

    payload = rv.layout_payload(layout, available_channels=channels)
    loaded = rv.parse_layout(payload, available_channels=channels)
    legacy = dict(payload)
    legacy["schema"] = rv.LEGACY_VIEW_LAYOUT_SCHEMA
    legacy.pop("x_range_s")
    legacy.pop("plot_mode")

    assert payload["x_range_s"] == [0.0002, 0.0006]
    assert loaded == layout
    assert rv.parse_layout(legacy, available_channels=channels).x_range_s is None

    legacy["x_range_s"] = [0.0, 0.0002]
    with pytest.raises(rv.RecorderViewError, match="legacy"):
        rv.parse_layout(legacy, available_channels=channels)


def test_fft_plot_mode_roundtrips_and_v1_v2_migrate_only_to_time_mode():
    channels = ("Position", "Velocity")
    layout = rv.ViewLayout(
        lanes=(rv.LaneLayout(("Position",)), rv.LaneLayout(("Velocity",))),
        x_range_s=(0.0002, 0.0006),
        plot_mode=rv.PLOT_MODE_FFT,
    )
    payload = rv.layout_payload(layout, available_channels=channels)

    assert payload["schema"] == rv.VIEW_LAYOUT_SCHEMA
    assert payload["plot_mode"] == rv.PLOT_MODE_FFT
    assert rv.parse_layout(payload, available_channels=channels) == layout

    v2 = dict(payload)
    v2["schema"] = rv.PREVIOUS_VIEW_LAYOUT_SCHEMA
    v2.pop("plot_mode")
    migrated_v2 = rv.parse_layout(v2, available_channels=channels)
    assert migrated_v2.x_range_s == pytest.approx((0.0002, 0.0006))
    assert migrated_v2.plot_mode == rv.PLOT_MODE_TIME

    v1 = dict(v2)
    v1["schema"] = rv.LEGACY_VIEW_LAYOUT_SCHEMA
    v1.pop("x_range_s")
    migrated_v1 = rv.parse_layout(v1, available_channels=channels)
    assert migrated_v1.x_range_s is None
    assert migrated_v1.plot_mode == rv.PLOT_MODE_TIME

    v2["plot_mode"] = rv.PLOT_MODE_FFT
    with pytest.raises(rv.RecorderViewError, match="v2"):
        rv.parse_layout(v2, available_channels=channels)


def test_v3_layout_requires_valid_explicit_plot_mode():
    base = {
        "schema": rv.VIEW_LAYOUT_SCHEMA,
        "compatibility": rv.LOCAL_COMPATIBILITY,
        "x_range_s": "full",
        "lanes": [
            {"channels": ["Position"], "visible": True, "y_range": "auto"},
            {"channels": [], "visible": True, "y_range": "auto"},
        ],
    }
    with pytest.raises(rv.RecorderViewError, match="plot_mode"):
        rv.parse_layout(base, available_channels=("Position",))

    invalid = dict(base, plot_mode="waterfall")
    with pytest.raises(rv.RecorderViewError, match="plot_mode"):
        rv.parse_layout(invalid, available_channels=("Position",))


def test_set_plot_mode_preserves_time_window_and_lanes_and_rejects_one_sample_fft():
    request = resolved(signals=("Position", "Velocity"), count=5)
    view = rv.build_capture_view(
        state="COMPLETED", data=capture_data(request.signals, count=5),
        resolved=request, binding=binding())
    layout = rv.ViewLayout(
        lanes=(
            rv.LaneLayout(("Position",), False, (-1.0, 1.0)),
            rv.LaneLayout(("Velocity",), True, None),
        ),
        x_range_s=(0.0002, 0.0006),
    )

    fft = rv.set_plot_mode(layout, view, rv.PLOT_MODE_FFT)
    time = rv.set_plot_mode(fft, view, rv.PLOT_MODE_TIME)

    assert fft.plot_mode == rv.PLOT_MODE_FFT
    assert fft.lanes == layout.lanes
    assert fft.x_range_s == layout.x_range_s
    assert time == layout

    one_request = resolved(signals=("Position",), count=1)
    one = rv.build_capture_view(
        state="COMPLETED", data=capture_data(one_request.signals, count=1),
        resolved=one_request, binding=binding())
    one_layout = rv.ViewLayout((rv.LaneLayout(("Position",)), rv.LaneLayout()))
    with pytest.raises(rv.RecorderViewError, match="two samples"):
        rv.set_plot_mode(one_layout, one, rv.PLOT_MODE_FFT)


def test_fft_plot_mode_rejects_a_decimated_capture_before_rendering():
    request = resolved(signals=("Position",), count=8)
    full = rv.build_capture_view(
        state="COMPLETED", data=capture_data(request.signals, count=8),
        resolved=request, binding=binding())
    decimated = rv.decimate_view(full, max_points=4)
    layout = rv.ViewLayout(
        (rv.LaneLayout(("Position",)), rv.LaneLayout()),
        plot_mode=rv.PLOT_MODE_FFT,
    )

    with pytest.raises(rv.RecorderViewError, match="full capture"):
        rv.validate_layout_for_view(layout, decimated)


def test_time_window_is_immutable_capture_bounded_and_requires_two_samples():
    request = resolved(signals=("Position",), count=5)
    view = rv.build_capture_view(
        state="COMPLETED", data=capture_data(request.signals, count=5),
        resolved=request, binding=binding())
    layout = rv.ViewLayout((rv.LaneLayout(("Position",)), rv.LaneLayout()))

    zoomed = rv.set_time_window(layout, view, (0.0002, 0.0006))
    restored = rv.set_time_window(zoomed, view, None)

    assert layout.x_range_s is None
    assert zoomed.x_range_s == pytest.approx((0.0002, 0.0006))
    assert restored.x_range_s is None

    for bad in (
        (-0.0001, 0.0002),
        (0.0002, 0.0002),
        (0.0, 0.001),
        (0.0001, 0.0002),
        (False, 0.0002),
        (0.0, float("nan")),
    ):
        with pytest.raises(rv.RecorderViewError):
            rv.set_time_window(layout, view, bad)


def test_time_window_canonicalizes_tolerance_near_real_sample_boundaries():
    request = resolved(signals=("Position",), count=5)
    view = rv.build_capture_view(
        state="COMPLETED", data=capture_data(request.signals, count=5),
        resolved=request, binding=binding())
    layout = rv.ViewLayout((rv.LaneLayout(("Position",)), rv.LaneLayout()))

    zoomed = rv.set_time_window(
        layout, view, (0.0002 + 5e-13, 0.0004 - 5e-13))
    endpoint_clamped = rv.set_time_window(
        layout, view, (0.0, view.x_s[-1] + 5e-13))

    assert zoomed.x_range_s == (view.x_s[1], view.x_s[2])
    assert endpoint_clamped.x_range_s == (view.x_s[0], view.x_s[-1])
    assert sum(
        zoomed.x_range_s[0] <= value <= zoomed.x_range_s[1]
        for value in view.x_s
    ) == 2


def test_manual_window_two_sample_capture_is_valid_and_single_sample_is_rejected():
    two_request = resolved(signals=("Position",), count=2)
    two_view = rv.build_capture_view(
        state="COMPLETED", data=capture_data(two_request.signals, count=2),
        resolved=two_request, binding=binding())
    two_layout = rv.ViewLayout((rv.LaneLayout(("Position",)), rv.LaneLayout()))

    assert rv.set_time_window(
        two_layout, two_view, (two_view.x_s[0], two_view.x_s[-1])
    ).x_range_s == (two_view.x_s[0], two_view.x_s[-1])

    one_request = resolved(signals=("Position",), count=1)
    one_view = rv.build_capture_view(
        state="COMPLETED", data=capture_data(one_request.signals, count=1),
        resolved=one_request, binding=binding())
    with pytest.raises(rv.RecorderViewError):
        rv.set_time_window(two_layout, one_view, (0.0, 0.0002))


def test_time_window_preserves_lane_channels_visibility_and_independent_y_ranges():
    request = resolved(signals=("Position", "Velocity"), count=5)
    view = rv.build_capture_view(
        state="COMPLETED", data=capture_data(request.signals, count=5),
        resolved=request, binding=binding())
    layout = rv.ViewLayout((
        rv.LaneLayout(("Position",), False, (-10.0, 10.0)),
        rv.LaneLayout(("Velocity",), True, (-2.0, 3.0)),
    ))

    zoomed = rv.set_time_window(layout, view, (0.0, 0.0008))

    assert zoomed.lanes == layout.lanes
    assert zoomed.x_range_s == pytest.approx((0.0, 0.0008))


def test_v1_layout_rejects_more_than_one_channel_per_lane():
    layout = rv.ViewLayout(lanes=(
        rv.LaneLayout(("Position", "Velocity")),
        rv.LaneLayout(("Current",)),
    ))

    with pytest.raises(rv.RecorderViewError, match="at most one"):
        rv.layout_payload(
            layout, available_channels=("Position", "Velocity", "Current"))


@pytest.mark.parametrize(
    "payload, match",
    [
        ({"schema": "unknown/v9", "compatibility": "local-only; not EAS-compatible",
          "lanes": []}, "schema"),
        ({"schema": rv.VIEW_LAYOUT_SCHEMA,
          "compatibility": "local-only; not EAS-compatible",
          "plot_mode": rv.PLOT_MODE_TIME,
          "x_range_s": "full",
          "lanes": [
              {"channels": ["Unknown"], "visible": True, "y_range": "auto"},
              {"channels": [], "visible": True, "y_range": "auto"},
          ]}, "unknown channel"),
        ({"schema": rv.VIEW_LAYOUT_SCHEMA,
          "compatibility": "local-only; not EAS-compatible",
          "plot_mode": rv.PLOT_MODE_TIME,
          "x_range_s": "full",
          "lanes": [
              {"channels": [], "visible": True, "y_range": "auto"},
          ]}, "exactly two"),
    ],
)
def test_layout_parser_rejects_unknown_schema_channel_or_lane_count(payload, match):
    with pytest.raises(rv.RecorderViewError, match=match):
        rv.parse_layout(payload, available_channels=("Position [cnt]",))


@pytest.mark.parametrize(
    "x_range_s, match",
    [
        ([-0.1, 0.1], "before zero"),
        ([0.1, 0.1], "min < max"),
        ([0.2, 0.1], "min < max"),
        ([0.0, float("inf")], "finite"),
        ([False, 0.1], "finite"),
        ([0.0], "full or finite"),
    ],
)
def test_v2_layout_parser_rejects_malformed_manual_time_windows(x_range_s, match):
    payload = {
        "schema": rv.VIEW_LAYOUT_SCHEMA,
        "compatibility": rv.LOCAL_COMPATIBILITY,
        "plot_mode": rv.PLOT_MODE_TIME,
        "x_range_s": x_range_s,
        "lanes": [
            {"channels": ["Position"], "visible": True, "y_range": "auto"},
            {"channels": [], "visible": True, "y_range": "auto"},
        ],
    }

    with pytest.raises(rv.RecorderViewError, match=match):
        rv.parse_layout(payload, available_channels=("Position",))


def test_v2_layout_requires_explicit_time_window_field():
    payload = {
        "schema": rv.VIEW_LAYOUT_SCHEMA,
        "compatibility": rv.LOCAL_COMPATIBILITY,
        "lanes": [
            {"channels": ["Position"], "visible": True, "y_range": "auto"},
            {"channels": [], "visible": True, "y_range": "auto"},
        ],
    }

    with pytest.raises(rv.RecorderViewError, match="x_range_s"):
        rv.parse_layout(payload, available_channels=("Position",))


@pytest.mark.parametrize(
    "lane, match",
    [
        (rv.LaneLayout(("A", "A"), True, None), "duplicate"),
        (rv.LaneLayout(("A",), 1, None), "visible"),
        (rv.LaneLayout(("A",), True, (1.0, 1.0)), "min < max"),
        (rv.LaneLayout(("A",), True, (2.0, 1.0)), "min < max"),
        (rv.LaneLayout(("A",), True, (0.0, float("inf"))), "finite"),
    ],
)
def test_layout_validation_is_fail_closed(lane, match):
    layout = rv.ViewLayout(lanes=(lane, rv.LaneLayout()))
    with pytest.raises(rv.RecorderViewError, match=match):
        rv.layout_payload(layout, available_channels=("A",))


def test_layout_save_is_atomic_and_preserves_existing_file_on_replace_failure(
        tmp_path, monkeypatch):
    path = tmp_path / "scope.ayview.json"
    path.write_text("original", encoding="utf-8")
    layout = rv.ViewLayout(lanes=(rv.LaneLayout(("A",)), rv.LaneLayout()))

    def fail_replace(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(rv.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        rv.save_layout(path, layout, available_channels=("A",))

    assert path.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.glob("*.tmp")) == []


def test_decimation_creates_only_an_immutable_view_copy_and_keeps_raw_unchanged():
    request = resolved(signals=("Position [cnt]",), count=9)
    raw = capture_data(signals=request.signals, count=9)
    raw_before = list(raw["Position [cnt]"])
    full = rv.build_capture_view(
        state="COMPLETED", data=raw, resolved=request, binding=binding())

    reduced = rv.decimate_view(full, max_points=4)

    assert reduced is not full
    assert reduced.binding == full.binding
    assert reduced.source_sample_count == 9
    assert reduced.display_sample_count == 4
    assert reduced.series[0].x[0] == 0.0
    assert reduced.series[0].x[-1] == pytest.approx(0.0016)
    assert reduced.series[0].y[0] == 0.0
    assert reduced.series[0].y[-1] == 8.0
    assert raw["Position [cnt]"] == raw_before
    assert full.series[0].y == tuple(raw_before)

    with pytest.raises(rv.RecorderViewError, match="at least 2"):
        rv.decimate_view(full, max_points=1)


def test_capture_evidence_detaches_data_and_nested_manifest_from_caller_aliases():
    request = resolved(signals=("Position [cnt]",), count=3)
    raw = capture_data(signals=request.signals, count=3)
    manifest = {
        "capture_id": "capture-001",
        "drive_identity": "gold-twitter-A",
        "completion": "VALIDATED",
        "nested": {"source": "before"},
    }

    evidence = rv.build_capture_evidence(
        state="COMPLETED", data=raw, resolved=request,
        binding=binding(), manifest=manifest)
    raw["dt"] = 99.0
    raw["Position [cnt]"][1] = 999.0
    manifest["nested"]["source"] = "after"

    assert evidence.data["dt"] == pytest.approx(0.0002)
    assert evidence.data["Position [cnt]"] == (0.0, 1.0, 2.0)
    assert evidence.manifest["nested"]["source"] == "before"
    assert evidence.view.series[0].y == (0.0, 1.0, 2.0)
    detached_manifest = evidence.manifest
    detached_manifest["nested"]["source"] = "local-copy-only"
    assert evidence.manifest["nested"]["source"] == "before"
    with pytest.raises(TypeError):
        evidence.data["dt"] = 1.0
    with pytest.raises(TypeError):
        evidence.manifest["capture_id"] = "changed"


def test_capture_evidence_reads_validated_dt_only_once():
    class SplitDtMapping(dict):
        def get(self, key, default=None):
            if key == "dt":
                return 0.0002
            return super().get(key, default)

        def __getitem__(self, key):
            if key == "dt":
                return 0.123
            return super().__getitem__(key)

    request = resolved(signals=("Position",), count=3)
    raw = SplitDtMapping({"Position": [0.0, 1.0, 2.0]})
    manifest = {
        "capture_id": "capture-001",
        "drive_identity": "gold-twitter-A",
        "completion": "VALIDATED",
    }

    evidence = rv.build_capture_evidence(
        state="COMPLETED", data=raw, resolved=request,
        binding=binding(), manifest=manifest)

    assert evidence.data["dt"] == pytest.approx(0.0002)
    assert evidence.view.x_s == pytest.approx((0.0, 0.0002, 0.0004))


def test_decimation_preserves_single_sample_spike_and_extrema():
    request = resolved(signals=("Current",), count=9)
    raw = capture_data(signals=request.signals, count=9)
    raw["Current"] = [0.0, 0.0, 50.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0]
    full = rv.build_capture_view(
        state="COMPLETED", data=raw, resolved=request, binding=binding())

    reduced = rv.decimate_view(full, max_points=4)

    assert reduced.display_sample_count == 4
    assert 50.0 in reduced.series[0].y
    assert 100.0 in reduced.series[0].y
    assert min(reduced.series[0].y) == 0.0
    assert max(reduced.series[0].y) == 100.0


def test_nearest_visible_sample_index_uses_original_samples_and_lower_tie():
    view = rv.CaptureView(
        binding=binding(),
        series=(rv.SignalSeries(
            name="Position",
            x=(0.0, 2.0, 4.0, 6.0),
            y=(10.0, 11.0, 12.0, 13.0),
        ),),
        source_sample_count=4,
    )

    assert rv.nearest_visible_sample_index(
        view, time_s=3.0, visible_range_s=(2.0, 6.0)) == 1
    assert rv.nearest_visible_sample_index(
        view, time_s=4.0, visible_range_s=(2.0, 6.0)) == 2
    assert rv.nearest_visible_sample_index(
        view, time_s=-100.0, visible_range_s=(2.0, 6.0)) == 1
    assert rv.nearest_visible_sample_index(
        view, time_s=100.0, visible_range_s=(2.0, 6.0)) == 3

    with pytest.raises(rv.RecorderViewError, match="finite"):
        rv.nearest_visible_sample_index(view, time_s=float("nan"))
    with pytest.raises(rv.RecorderViewError, match="visible"):
        rv.nearest_visible_sample_index(
            view, time_s=3.0, visible_range_s=(2.1, 3.9))


def test_capture_view_sha256_is_deterministic_and_float_identity_sensitive():
    request = resolved(signals=("Position",), count=3)
    view = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Position": [1.0, -0.0, 3.0]},
        resolved=request,
        binding=binding(),
    )
    same = replace(view, series=tuple(view.series))
    changed_series = replace(
        view.series[0], y=(1.0, 0.0, 3.0))
    changed = replace(view, series=(changed_series,))

    digest = rv.capture_view_sha256(view)

    assert len(digest) == 64
    assert digest == rv.capture_view_sha256(same)
    assert digest != rv.capture_view_sha256(changed)


def test_statistics_csv_exports_range_provenance_authority_and_exact_rows(tmp_path):
    request = resolved(signals=("Position", "Velocity"), count=4)
    view = rv.build_capture_view(
        state="COMPLETED",
        data={
            "dt": 0.0002,
            "Position": [10.0, 11.0, 12.0, 13.0],
            "Velocity": [-3.0, -1.0, 1.0, 3.0],
        },
        resolved=request,
        binding=binding(),
    )
    statistics = rv.build_sample_range_statistics(
        view, start_index=1, end_index=3)
    path = tmp_path / "range-statistics.csv"

    metadata = rv.export_statistics_csv(
        path, view, statistics, authority="historical_offline")
    duplicate_path = tmp_path / "range-statistics-copy.csv"
    duplicate = rv.export_statistics_csv(
        duplicate_path, view, statistics, authority="historical_offline")

    assert metadata.path == str(path.resolve())
    assert metadata.schema == rv.STATISTICS_CSV_SCHEMA
    assert metadata.authority == "historical_offline"
    assert metadata.row_count == 2
    assert metadata.source_view_sha256 == rv.capture_view_sha256(view)
    assert len(metadata.csv_sha256) == 64
    assert metadata.csv_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert duplicate.csv_sha256 == metadata.csv_sha256
    assert duplicate_path.read_bytes() == path.read_bytes()
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["signal"] for row in rows] == ["Position", "Velocity"]
    assert all(row["schema"] == rv.STATISTICS_CSV_SCHEMA for row in rows)
    assert all(row["evidence_class"] == "DERIVED" for row in rows)
    assert all(row["authority"] == "historical_offline" for row in rows)
    assert all(row["source_view_sha256"] == metadata.source_view_sha256
               for row in rows)
    assert all(row["scope"] == "sample_range" for row in rows)
    assert all(row["range_start_index"] == "1" for row in rows)
    assert all(row["range_end_index"] == "3" for row in rows)
    assert all(row["sample_count"] == "3" for row in rows)
    assert float(rows[0]["endpoint_start_value"]) == 11.0
    assert float(rows[0]["endpoint_end_value"]) == 13.0
    assert float(rows[0]["endpoint_delta_value"]) == 2.0
    assert rows[0]["tolerance_percent_status"] == "FINITE"
    assert rows[0]["units"] == rv.UNITS_NOTICE


def test_statistics_csv_full_scope_leaves_range_and_endpoint_fields_blank(tmp_path):
    view = rv.build_capture_view(
        state="COMPLETED",
        data=capture_data(signals=("Position",), count=3),
        resolved=resolved(signals=("Position",), count=3),
        binding=binding(),
    )
    statistics = rv.build_full_capture_statistics(view)
    path = tmp_path / "full-statistics.csv"

    rv.export_statistics_csv(path, view, statistics, authority="current")

    with path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["scope"] == "full_capture"
    assert row["range_start_index"] == ""
    assert row["range_end_index"] == ""
    assert row["endpoint_start_value"] == ""
    assert row["endpoint_end_value"] == ""
    assert row["endpoint_delta_value"] == ""


def test_statistics_csv_labels_unrepresentable_tolerance_percent_explicitly(tmp_path):
    view = rv.build_capture_view(
        state="COMPLETED",
        data={"dt": 0.0002, "Tiny Mean": [-1.0, 1.0, 1e-308]},
        resolved=resolved(signals=("Tiny Mean",), count=3),
        binding=binding(),
    )
    statistics = rv.build_full_capture_statistics(view)
    assert statistics.rows[0].tolerance_percent is None
    path = tmp_path / "tiny-mean-statistics.csv"

    rv.export_statistics_csv(path, view, statistics, authority="current")

    with path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["tolerance_percent"] == ""
    assert row["tolerance_percent_status"] == "NOT_REPRESENTABLE"


def test_statistics_csv_rejects_tampered_or_wrong_source_statistics(tmp_path):
    view = rv.build_capture_view(
        state="COMPLETED",
        data=capture_data(signals=("Position",), count=3),
        resolved=resolved(signals=("Position",), count=3),
        binding=binding(),
    )
    statistics = rv.build_full_capture_statistics(view)
    tampered = replace(
        statistics,
        rows=(replace(statistics.rows[0], average=999.0),),
    )
    changed_view = replace(
        view,
        series=(replace(view.series[0], y=(100.0, 101.0, 102.0)),),
    )

    with pytest.raises(rv.RecorderViewError, match="statistics"):
        rv.export_statistics_csv(
            tmp_path / "tampered.csv", view, tampered, authority="current")
    with pytest.raises(rv.RecorderViewError, match="statistics"):
        rv.export_statistics_csv(
            tmp_path / "wrong-source.csv", changed_view, statistics,
            authority="current")


def test_statistics_csv_replace_failure_preserves_target_and_cleans_temp(
        tmp_path, monkeypatch):
    view = rv.build_capture_view(
        state="COMPLETED",
        data=capture_data(signals=("Position",), count=3),
        resolved=resolved(signals=("Position",), count=3),
        binding=binding(),
    )
    statistics = rv.build_full_capture_statistics(view)
    path = tmp_path / "statistics.csv"
    path.write_bytes(b"previous-good-file")

    def reject_replace(_source, _target):
        raise OSError("replace blocked")

    monkeypatch.setattr(rv.os, "replace", reject_replace)

    with pytest.raises(OSError, match="replace blocked"):
        rv.export_statistics_csv(
            path, view, statistics, authority="current")

    assert path.read_bytes() == b"previous-good-file"
    assert list(tmp_path.glob("statistics.csv.*.tmp")) == []


def test_statistics_csv_preserves_publication_error_if_temp_cleanup_also_fails(
        tmp_path, monkeypatch):
    view = rv.build_capture_view(
        state="COMPLETED",
        data=capture_data(signals=("Position",), count=3),
        resolved=resolved(signals=("Position",), count=3),
        binding=binding(),
    )
    statistics = rv.build_full_capture_statistics(view)

    monkeypatch.setattr(
        rv.os, "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace blocked")),
    )
    monkeypatch.setattr(
        rv.os, "unlink",
        lambda *_args: (_ for _ in ()).throw(PermissionError("cleanup blocked")),
    )

    with pytest.raises(OSError, match="replace blocked"):
        rv.export_statistics_csv(
            tmp_path / "statistics.csv", view, statistics,
            authority="current")


def test_statistics_csv_rejects_empty_or_directory_target_before_staging(
        tmp_path, monkeypatch):
    view = rv.build_capture_view(
        state="COMPLETED",
        data=capture_data(signals=("Position",), count=3),
        resolved=resolved(signals=("Position",), count=3),
        binding=binding(),
    )
    statistics = rv.build_full_capture_statistics(view)
    staged = []
    real_mkstemp = rv.tempfile.mkstemp

    def observed_mkstemp(*args, **kwargs):
        staged.append((args, kwargs))
        return real_mkstemp(*args, **kwargs)

    monkeypatch.setattr(rv.tempfile, "mkstemp", observed_mkstemp)

    with pytest.raises(rv.RecorderViewError, match="path"):
        rv.export_statistics_csv("", view, statistics, authority="current")
    with pytest.raises(rv.RecorderViewError, match="file"):
        rv.export_statistics_csv(
            tmp_path, view, statistics, authority="current")
    assert staged == []


def test_statistics_csv_requires_final_target_readback_before_success(
        tmp_path, monkeypatch):
    view = rv.build_capture_view(
        state="COMPLETED",
        data=capture_data(signals=("Position",), count=3),
        resolved=resolved(signals=("Position",), count=3),
        binding=binding(),
    )
    statistics = rv.build_full_capture_statistics(view)
    path = tmp_path / "statistics.csv"
    path.write_bytes(b"old-target")
    monkeypatch.setattr(rv.os, "replace", lambda *_args: None)

    with pytest.raises(rv.RecorderViewError, match="published"):
        rv.export_statistics_csv(
            path, view, statistics, authority="current")

    assert path.read_bytes() == b"old-target"
    assert list(tmp_path.glob("statistics.csv.*.tmp")) == []
