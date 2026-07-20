"""Pure local Recorder View Design model (no GUI and no hardware I/O)."""
from __future__ import annotations

import bisect
import csv
from dataclasses import dataclass, replace
from fractions import Fraction
import hashlib
import io
import json
import math
import os
import struct
import tempfile
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import numpy as np

import recorder_control


VIEW_LAYOUT_SCHEMA = "angryyjh-recorder-view-layout/v3"
PREVIOUS_VIEW_LAYOUT_SCHEMA = "angryyjh-recorder-view-layout/v2"
LEGACY_VIEW_LAYOUT_SCHEMA = "angryyjh-recorder-view-layout/v1"
UNITS_NOTICE = "personality-owned; not inferred"
SPECTRUM_UNITS_NOTICE = "personality-owned amplitude; not inferred"
SPECTRUM_PROCESSING = (
    "one-sided amplitude; rectangular; DC included; full capture")
LOCAL_COMPATIBILITY = "local-only; not EAS-compatible"
PLOT_MODE_TIME = "time"
PLOT_MODE_FFT = "fft"
STATISTICS_SCOPE_FULL_CAPTURE = "full_capture"
STATISTICS_SCOPE_SAMPLE_RANGE = "sample_range"
STATISTICS_CSV_SCHEMA = "angryyjh-recorder-statistics-csv/v1"
STATISTICS_AUTHORITY_CURRENT = "current"
STATISTICS_AUTHORITY_HISTORICAL_OFFLINE = "historical_offline"
STATISTICS_CSV_FIELDS = (
    "schema", "evidence_class", "authority",
    "capture_id", "generation", "drive_identity",
    "source_view_sha256", "scope", "source_sample_count",
    "range_start_index", "range_end_index",
    "range_start_time_s", "range_end_time_s", "delta_time_s",
    "signal_order", "signal", "sample_count",
    "endpoint_start_value", "endpoint_end_value", "endpoint_delta_value",
    "minimum", "maximum", "average", "rms_ac", "rms_dc",
    "tolerance", "tolerance_percent", "tolerance_percent_status",
    "units", "semantics", "numeric_contract", "compatibility",
)


class RecorderViewError(ValueError):
    pass


@dataclass(frozen=True)
class CaptureBinding:
    capture_id: str
    generation: int
    drive_identity: str


@dataclass(frozen=True)
class SignalSeries:
    name: str
    x: tuple[float, ...]
    y: tuple[float, ...]


@dataclass(frozen=True)
class CaptureView:
    binding: CaptureBinding
    series: tuple[SignalSeries, ...]
    source_sample_count: int
    units: str = UNITS_NOTICE

    @property
    def capture_id(self) -> str:
        return self.binding.capture_id

    @property
    def generation(self) -> int:
        return self.binding.generation

    @property
    def drive_identity(self) -> str:
        return self.binding.drive_identity

    @property
    def signals(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.series)

    @property
    def x_s(self) -> tuple[float, ...]:
        return self.series[0].x if self.series else ()

    @property
    def signal_names(self) -> tuple[str, ...]:
        return self.signals

    @property
    def display_sample_count(self) -> int:
        return len(self.series[0].x) if self.series else 0


@dataclass(frozen=True)
class SpectrumView:
    """Immutable local FFT stand-in derived from one full CaptureView."""

    binding: CaptureBinding
    series: tuple[SignalSeries, ...]
    input_sample_count: int
    dt_s: float
    frequency_resolution_hz: float
    nyquist_hz: float
    units: str = SPECTRUM_UNITS_NOTICE
    processing: str = SPECTRUM_PROCESSING

    @property
    def signals(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.series)

    @property
    def x_hz(self) -> tuple[float, ...]:
        return self.series[0].x if self.series else ()


@dataclass(frozen=True)
class SignalStatistics:
    """EAS-defined descriptive fields derived from one immutable signal."""

    name: str
    sample_count: int
    minimum: float
    maximum: float
    average: float
    rms_ac: float
    rms_dc: float
    tolerance: float
    tolerance_percent: float | None


@dataclass(frozen=True)
class SampleRangeSelection:
    """Exact inclusive sample range bound to one immutable capture."""

    binding: CaptureBinding
    start_index: int
    end_index: int
    start_time_s: float
    end_time_s: float

    @property
    def sample_count(self) -> int:
        return self.end_index - self.start_index + 1

    @property
    def delta_time_s(self) -> float:
        return self.end_time_s - self.start_time_s


@dataclass(frozen=True)
class SignalEndpointValues:
    """Exact signal values at the two selected sample endpoints."""

    name: str
    start_value: float
    end_value: float
    delta_value: float


@dataclass(frozen=True)
class CaptureStatistics:
    """Read-only statistics bound to the exact capture used as evidence."""

    binding: CaptureBinding
    rows: tuple[SignalStatistics, ...]
    scope: str = STATISTICS_SCOPE_FULL_CAPTURE
    units: str = UNITS_NOTICE
    selection: SampleRangeSelection | None = None
    endpoints: tuple[SignalEndpointValues, ...] = ()


@dataclass(frozen=True)
class StatisticsExportMetadata:
    """Receipt for one atomically published local statistics CSV."""

    path: str
    schema: str
    authority: str
    row_count: int
    source_view_sha256: str
    csv_sha256: str


@dataclass(frozen=True)
class CaptureEvidence:
    """One detached, immutable-at-rest capture used by plot, summary and CSV."""

    view: CaptureView
    resolved: recorder_control.ResolvedRecorderRequest
    dt_s: float
    _data_items: tuple[tuple[str, tuple[float, ...]], ...]
    _manifest_json: str

    @property
    def data(self) -> Mapping[str, Any]:
        # Return a fresh read-only mapping so callers cannot mutate the stored
        # evidence or retain an alias into its channel tuples.
        return MappingProxyType({
            "dt": self.dt_s,
            **{name: values for name, values in self._data_items},
        })

    @property
    def manifest(self) -> Mapping[str, Any]:
        # JSON is the immutable-at-rest representation.  Each access gets a
        # detached object behind a read-only top-level mapping.
        return MappingProxyType(json.loads(self._manifest_json))


@dataclass(frozen=True)
class LaneLayout:
    channels: tuple[str, ...] = ()
    visible: bool = True
    y_range: tuple[float, float] | None = None


@dataclass(frozen=True)
class ViewLayout:
    lanes: tuple[LaneLayout, LaneLayout]
    x_range_s: tuple[float, float] | None = None
    plot_mode: str = PLOT_MODE_TIME


def build_capture_view(*, state: str, data: Mapping[str, Any], resolved: Any,
                       binding: CaptureBinding) -> CaptureView:
    """Build an immutable local view only from one validated completed capture."""
    if state != "COMPLETED":
        raise RecorderViewError(
            "Recorder View requires the exact COMPLETED lifecycle state")
    if not isinstance(resolved, recorder_control.ResolvedRecorderRequest):
        raise RecorderViewError(
            "Recorder View requires ResolvedRecorderRequest")
    _validate_binding(binding)
    _exact_names(resolved.signals, "resolved signals")

    # Snapshot the caller-owned arrays before validation so a mutable list (or
    # one-shot iterable) cannot change between the gate and view construction.
    if isinstance(data, Mapping):
        captured: Any = {"dt": data.get("dt")}
        for name in resolved.signals:
            if name in data:
                try:
                    captured[name] = tuple(data[name])
                except TypeError:
                    captured[name] = data[name]
    else:
        captured = data
    try:
        checked = recorder_control.validate_capture(captured, resolved)
    except (recorder_control.RecorderConfigError, TypeError) as exc:
        raise RecorderViewError(str(exc)) from exc

    count = int(checked["samples_per_signal"])
    dt = float(checked["dt_s"])
    x_values = tuple(index * dt for index in range(count))
    series = tuple(
        SignalSeries(
            name=name,
            x=x_values,
            y=tuple(float(value) for value in captured[name]),
        )
        for name in resolved.signals
    )
    return CaptureView(
        binding=binding,
        series=series,
        source_sample_count=count,
        units=UNITS_NOTICE,
    )


def build_spectrum_view(view: CaptureView) -> SpectrumView:
    """Derive a deterministic one-sided peak-amplitude spectrum.

    This is a local display contract, not a claim about EAS FFT semantics.
    The transform always consumes the complete, uniformly sampled immutable
    capture; a time-windowed or display-decimated view is never accepted.
    """
    _validate_capture_view(view)
    count = view.display_sample_count
    if count < 2:
        raise RecorderViewError("FFT requires at least two captured samples")
    if count != view.source_sample_count:
        raise RecorderViewError("FFT requires the full, undecimated capture")

    x_values = view.x_s
    dt_s = x_values[1] - x_values[0]
    if not math.isfinite(dt_s) or dt_s <= 0.0:
        raise RecorderViewError("FFT requires a finite positive uniform sample interval")
    if x_values[0] != 0.0:
        raise RecorderViewError("FFT requires a uniform time axis starting at zero")
    interval_tolerance = max(
        math.ulp(dt_s) * 8.0,
        abs(dt_s) * 1e-9,
    )
    if any(
            not math.isclose(
                right - left, dt_s,
                rel_tol=0.0, abs_tol=interval_tolerance)
            for left, right in zip(x_values, x_values[1:])):
        raise RecorderViewError("FFT requires one exact uniform sample interval")

    try:
        with np.errstate(
                over="ignore", under="ignore",
                divide="ignore", invalid="ignore"):
            frequency_values = tuple(
                float(value) for value in np.fft.rfftfreq(count, d=dt_s))
            frequency_resolution_hz = 1.0 / (count * dt_s)
            nyquist_hz = 1.0 / (2.0 * dt_s)
    except (ArithmeticError, FloatingPointError, ValueError) as exc:
        raise RecorderViewError(
            "FFT derived frequency axis is not representable") from exc
    if (not math.isfinite(frequency_resolution_hz)
            or frequency_resolution_hz <= 0.0
            or not math.isfinite(nyquist_hz)
            or nyquist_hz <= 0.0
            or not frequency_values
            or frequency_values[0] != 0.0
            or any(not math.isfinite(value) for value in frequency_values)
            or any(left >= right for left, right in zip(
                frequency_values, frequency_values[1:]))):
        raise RecorderViewError(
            "FFT derived frequency axis must be finite and strictly increasing")
    transformed = []
    for item in view.series:
        with np.errstate(over="ignore", invalid="ignore"):
            amplitudes = np.abs(
                np.fft.rfft(np.asarray(item.y, dtype=np.float64))) / count
            if count % 2 == 0:
                amplitudes[1:-1] *= 2.0
            else:
                amplitudes[1:] *= 2.0
        amplitude_values = tuple(float(value) for value in amplitudes)
        if any(not math.isfinite(value) for value in amplitude_values):
            raise RecorderViewError("FFT result is non-finite")
        transformed.append(SignalSeries(
            name=item.name,
            x=frequency_values,
            y=amplitude_values,
        ))

    return SpectrumView(
        binding=view.binding,
        series=tuple(transformed),
        input_sample_count=count,
        dt_s=dt_s,
        frequency_resolution_hz=frequency_resolution_hz,
        nyquist_hz=nyquist_hz,
    )


def _finite_mean(values: tuple[float, ...]) -> float:
    """Return a finite mean without overflowing a representable result."""
    try:
        result = math.fsum(values) / len(values)
    except OverflowError:
        # A finite mean can exist when the exact sum exceeds binary64 or when
        # very large positive/negative partials cancel.  Fraction.from_float
        # is an exact, rare fallback and preserves any representable residual.
        exact_total = sum(
            (Fraction.from_float(value) for value in values), Fraction())
        result = float(exact_total / len(values))
    if not math.isfinite(result):
        raise RecorderViewError("signal statistics are not representable")
    return result


def _scaled_rms(values: tuple[float, ...]) -> float:
    """Return standard sqrt(mean(x**2)) without square/sum overflow."""
    scale = max(abs(value) for value in values)
    if scale == 0.0:
        return 0.0
    result = math.sqrt(
        math.fsum((value / scale) ** 2 for value in values) / len(values)
    ) * scale
    if not math.isfinite(result):
        raise RecorderViewError("signal statistics are not representable")
    return result


def _build_signal_statistics(
        name: str, values: tuple[float, ...]) -> SignalStatistics:
    """Calculate one EAS-compatible statistics row with stable arithmetic."""
    if len(values) < 2:
        raise RecorderViewError(
            "signal statistics require at least two samples")
    minimum = min(values)
    maximum = max(values)
    try:
        tolerance = maximum - minimum
        if not math.isfinite(tolerance):
            raise RecorderViewError(
                "signal statistics are not representable")
        average = _finite_mean(values)
        rms_dc = _scaled_rms(values)

        # Translate before centering.  Subtracting a rounded global mean
        # from a large DC offset can destroy a small but real AC spread.
        # With finite Tolerance these offsets stay finite and retain that
        # spread; RMS is then evaluated in the translated domain.
        offsets = tuple(value - minimum for value in values)
        if any(not math.isfinite(value) for value in offsets):
            raise RecorderViewError(
                "signal statistics are not representable")
        offset_average = _finite_mean(offsets)
        deviations = tuple(value - offset_average for value in offsets)
        rms_ac = _scaled_rms(deviations)

        # Installed EAS 3.0.0.26 SignalStatistics.get_TolerancePercent()
        # uses exact zero as its guard and otherwise evaluates this expression
        # in this order.  Reject non-finite display evidence rather than
        # presenting infinity as an engineering value.
        tolerance_percent = (
            0.0 if average == 0.0
            else abs(tolerance / average / 2.0) * 100.0
        )
        if not math.isfinite(tolerance_percent):
            tolerance_percent = None
    except (ArithmeticError, OverflowError, ValueError) as exc:
        raise RecorderViewError(
            "signal statistics are not representable") from exc
    derived = (minimum, maximum, average, rms_ac, rms_dc, tolerance)
    if any(not math.isfinite(value) for value in derived):
        raise RecorderViewError(
            "signal statistics are not representable")
    return SignalStatistics(
        name=name,
        sample_count=len(values),
        minimum=minimum,
        maximum=maximum,
        average=average,
        rms_ac=rms_ac,
        rms_dc=rms_dc,
        tolerance=tolerance,
        tolerance_percent=tolerance_percent,
    )


def _require_full_capture(view: CaptureView) -> None:
    _validate_capture_view(view)
    if view.display_sample_count != view.source_sample_count:
        raise RecorderViewError(
            "signal statistics require the full capture")


def build_full_capture_statistics(view: CaptureView) -> CaptureStatistics:
    """Derive the documented EAS statistics over every captured sample.

    The calculation is independent of Time/FFT display mode, lanes and zoom.
    Stable arithmetic keeps finite high-magnitude signals representable while
    an unrepresentable derived result fails closed instead of displaying an
    infinity as engineering evidence.
    """
    _require_full_capture(view)
    if view.display_sample_count < 2:
        raise RecorderViewError(
            "signal statistics require at least two samples")
    rows = tuple(
        _build_signal_statistics(item.name, item.y)
        for item in view.series)
    return CaptureStatistics(binding=view.binding, rows=rows)


def build_sample_range_selection(
        view: CaptureView, *, start_index: int,
        end_index: int) -> SampleRangeSelection:
    """Validate and bind one exact inclusive A:B selection to a capture."""
    _require_full_capture(view)
    if type(start_index) is not int or type(end_index) is not int:
        raise RecorderViewError(
            "range requires integer sample indexes")
    if start_index >= end_index:
        raise RecorderViewError(
            "range requires start before end")
    count = view.display_sample_count
    if start_index < 0 or end_index >= count:
        raise RecorderViewError(
            "range indexes must stay within the full capture")

    return SampleRangeSelection(
        binding=view.binding,
        start_index=start_index,
        end_index=end_index,
        start_time_s=view.x_s[start_index],
        end_time_s=view.x_s[end_index],
    )


def build_sample_range_statistics(
        view: CaptureView, *, start_index: int,
        end_index: int) -> CaptureStatistics:
    """Derive endpoint values and statistics for exact inclusive samples.

    Integer sample indexes are the authority.  Times are read from the exact
    immutable capture rather than rounded back into indexes.  The strict
    ``start_index < end_index`` gate mirrors installed EAS 3.0.0.26.
    """
    selection = build_sample_range_selection(
        view, start_index=start_index, end_index=end_index)
    rows = tuple(
        _build_signal_statistics(
            item.name, item.y[start_index:end_index + 1])
        for item in view.series)
    endpoints = tuple(
        SignalEndpointValues(
            name=item.name,
            start_value=item.y[start_index],
            end_value=item.y[end_index],
            delta_value=item.y[end_index] - item.y[start_index],
        )
        for item in view.series)
    return CaptureStatistics(
        binding=view.binding,
        rows=rows,
        scope=STATISTICS_SCOPE_SAMPLE_RANGE,
        selection=selection,
        endpoints=endpoints,
    )


def nearest_visible_sample_index(
        view: CaptureView, *, time_s: Any,
        visible_range_s: tuple[float, float] | None = None) -> int:
    """Return the closest original sample index in the visible Time viewport.

    This local cursor contract never interpolates.  Exact distance ties select
    the lower original index, matching the installed EAS Analyze-range path.
    """
    _require_full_capture(view)
    if isinstance(time_s, bool):
        raise RecorderViewError("cursor time must be a finite number")
    try:
        cursor_time = float(time_s)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RecorderViewError("cursor time must be a finite number") from exc
    if not math.isfinite(cursor_time):
        raise RecorderViewError("cursor time must be a finite number")

    x_values = view.x_s
    if visible_range_s is None:
        low, high = x_values[0], x_values[-1]
    else:
        if (not isinstance(visible_range_s, (tuple, list))
                or len(visible_range_s) != 2
                or any(isinstance(value, bool) for value in visible_range_s)):
            raise RecorderViewError(
                "visible range must contain two finite times")
        try:
            low, high = map(float, visible_range_s)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RecorderViewError(
                "visible range must contain two finite times") from exc
        if (not math.isfinite(low) or not math.isfinite(high)
                or low > high):
            raise RecorderViewError(
                "visible range must contain ordered finite times")

    first = bisect.bisect_left(x_values, low)
    last_exclusive = bisect.bisect_right(x_values, high)
    if first >= last_exclusive:
        raise RecorderViewError(
            "visible range does not contain an original sample")
    last = last_exclusive - 1
    if cursor_time <= x_values[first]:
        return first
    if cursor_time >= x_values[last]:
        return last

    right = bisect.bisect_left(
        x_values, cursor_time, first, last_exclusive)
    if right <= first:
        return first
    if right >= last_exclusive:
        return last
    if x_values[right] == cursor_time:
        return right
    left = right - 1
    return (left if cursor_time - x_values[left]
            <= x_values[right] - cursor_time else right)


def _hash_length_prefixed(hasher: Any, value: str) -> None:
    encoded = value.encode("utf-8")
    hasher.update(struct.pack(">Q", len(encoded)))
    hasher.update(encoded)


def capture_view_sha256(view: CaptureView) -> str:
    """Hash one exact immutable view using length-prefixed IEEE-754 bytes."""
    _require_full_capture(view)
    hasher = hashlib.sha256()
    _hash_length_prefixed(hasher, "angryyjh-recorder-capture-view/v1")
    _hash_length_prefixed(hasher, view.capture_id)
    hasher.update(struct.pack(">Q", view.generation))
    _hash_length_prefixed(hasher, view.drive_identity)
    _hash_length_prefixed(hasher, view.units)
    hasher.update(struct.pack(">Q", view.source_sample_count))
    hasher.update(struct.pack(">Q", len(view.series)))
    for item in view.series:
        _hash_length_prefixed(hasher, item.name)
        hasher.update(struct.pack(">Q", len(item.x)))
        for x_value, y_value in zip(item.x, item.y):
            hasher.update(struct.pack(">d", float(x_value)))
            hasher.update(struct.pack(">d", float(y_value)))
    return hasher.hexdigest()


def _statistics_for_exact_view(
        view: CaptureView,
        statistics: CaptureStatistics) -> CaptureStatistics:
    _require_full_capture(view)
    if not isinstance(statistics, CaptureStatistics):
        raise RecorderViewError(
            "structured capture statistics are required")
    if statistics.binding != view.binding:
        raise RecorderViewError(
            "statistics binding does not match the source capture")
    if statistics.scope == STATISTICS_SCOPE_FULL_CAPTURE:
        expected = build_full_capture_statistics(view)
    elif statistics.scope == STATISTICS_SCOPE_SAMPLE_RANGE:
        selection = statistics.selection
        if not isinstance(selection, SampleRangeSelection):
            raise RecorderViewError(
                "sample-range statistics require a bound selection")
        expected = build_sample_range_statistics(
            view,
            start_index=selection.start_index,
            end_index=selection.end_index,
        )
    else:
        raise RecorderViewError("statistics scope is not supported")
    if statistics != expected:
        raise RecorderViewError(
            "statistics do not exactly match the source capture")
    return expected


def _statistics_csv_number(value: float | None) -> str:
    return "" if value is None else format(float(value), ".17g")


def export_statistics_csv(
        path: os.PathLike[str] | str,
        view: CaptureView,
        statistics: CaptureStatistics, *,
        authority: str) -> StatisticsExportMetadata:
    """Atomically export one deterministic, provenance-bound local CSV.

    The file contains derived statistics, not raw capture samples, and is not
    an EAS-compatible Save/Save As format.  Validation and serialization finish
    before the target path is opened.
    """
    if authority not in (
            STATISTICS_AUTHORITY_CURRENT,
            STATISTICS_AUTHORITY_HISTORICAL_OFFLINE):
        raise RecorderViewError(
            "statistics authority must be current or historical_offline")
    checked = _statistics_for_exact_view(view, statistics)
    source_digest = capture_view_sha256(view)
    selection = checked.selection
    endpoints = {item.name: item for item in checked.endpoints}

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=STATISTICS_CSV_FIELDS,
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    for signal_order, row in enumerate(checked.rows):
        endpoint = endpoints.get(row.name)
        writer.writerow({
            "schema": STATISTICS_CSV_SCHEMA,
            "evidence_class": "DERIVED",
            "authority": authority,
            "capture_id": view.capture_id,
            "generation": str(view.generation),
            "drive_identity": view.drive_identity,
            "source_view_sha256": source_digest,
            "scope": checked.scope,
            "source_sample_count": str(view.source_sample_count),
            "range_start_index": (
                "" if selection is None else str(selection.start_index)),
            "range_end_index": (
                "" if selection is None else str(selection.end_index)),
            "range_start_time_s": (
                "" if selection is None
                else _statistics_csv_number(selection.start_time_s)),
            "range_end_time_s": (
                "" if selection is None
                else _statistics_csv_number(selection.end_time_s)),
            "delta_time_s": (
                "" if selection is None
                else _statistics_csv_number(selection.delta_time_s)),
            "signal_order": str(signal_order),
            "signal": row.name,
            "sample_count": str(row.sample_count),
            "endpoint_start_value": (
                "" if endpoint is None
                else _statistics_csv_number(endpoint.start_value)),
            "endpoint_end_value": (
                "" if endpoint is None
                else _statistics_csv_number(endpoint.end_value)),
            "endpoint_delta_value": (
                "" if endpoint is None
                else _statistics_csv_number(endpoint.delta_value)),
            "minimum": _statistics_csv_number(row.minimum),
            "maximum": _statistics_csv_number(row.maximum),
            "average": _statistics_csv_number(row.average),
            "rms_ac": _statistics_csv_number(row.rms_ac),
            "rms_dc": _statistics_csv_number(row.rms_dc),
            "tolerance": _statistics_csv_number(row.tolerance),
            "tolerance_percent": _statistics_csv_number(
                row.tolerance_percent),
            "tolerance_percent_status": (
                "FINITE" if row.tolerance_percent is not None
                else "NOT_REPRESENTABLE"),
            "units": checked.units,
            "semantics": "EAS_3.0.0.26_STATIC_IL",
            "numeric_contract": "LOCAL_STABLE_BINARY64_NOT_BIT_IDENTICAL",
            "compatibility": "LOCAL_ONLY_NOT_EAS_FILE_COMPATIBLE",
        })
    payload = buffer.getvalue().encode("utf-8")
    csv_digest = hashlib.sha256(payload).hexdigest()

    try:
        raw_path = os.fspath(path)
    except TypeError as exc:
        raise RecorderViewError(
            "statistics CSV path must be path-like") from exc
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise RecorderViewError(
            "statistics CSV path must be a non-empty text path")
    target = os.path.abspath(raw_path)
    if not os.path.basename(target) or os.path.isdir(target):
        raise RecorderViewError("statistics CSV path must name a file")
    parent = os.path.dirname(target) or os.curdir
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=os.path.basename(target) + ".",
        suffix=".tmp",
        dir=parent,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        with open(temporary, "rb") as handle:
            staged = handle.read()
        if staged != payload or hashlib.sha256(staged).hexdigest() != csv_digest:
            raise RecorderViewError(
                "staged statistics CSV failed byte verification")
        os.replace(temporary, target)
        with open(target, "rb") as handle:
            published = handle.read()
        if (published != payload
                or hashlib.sha256(published).hexdigest() != csv_digest):
            raise RecorderViewError(
                "published statistics CSV failed byte verification")
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise

    return StatisticsExportMetadata(
        path=target,
        schema=STATISTICS_CSV_SCHEMA,
        authority=authority,
        row_count=len(checked.rows),
        source_view_sha256=source_digest,
        csv_sha256=csv_digest,
    )


def spectrum_zero_scale_bounds(
        series: Sequence[SignalSeries]) -> tuple[float, float]:
    """Return local FFT display bounds whose numeric lower edge is zero."""
    if isinstance(series, (str, bytes)):
        raise RecorderViewError("spectrum series must be a sequence")
    try:
        items = tuple(series)
    except TypeError as exc:
        raise RecorderViewError("spectrum series must be a sequence") from exc
    if not items:
        raise RecorderViewError("spectrum series cannot be empty")
    maximum = 0.0
    for item in items:
        if not isinstance(item, SignalSeries) or not item.y:
            raise RecorderViewError("spectrum series must contain amplitude data")
        for value in item.y:
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(float(value)) or float(value) < 0.0):
                raise RecorderViewError(
                    "spectrum amplitudes must be finite and non-negative")
            maximum = max(maximum, float(value))
    return 0.0, maximum


def format_axis_value(value: Any, *, axis_span: Any) -> str:
    """Format a local axis label, using exponent form below a 0.001 span."""
    if isinstance(value, bool) or isinstance(axis_span, bool):
        raise RecorderViewError("axis value and span must be finite numbers")
    try:
        numeric = float(value)
        span = float(axis_span)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RecorderViewError(
            "axis value and span must be finite numbers") from exc
    if not math.isfinite(numeric) or not math.isfinite(span) or span < 0.0:
        raise RecorderViewError("axis value and span must be finite numbers")
    if span == 0.0:
        return "0" if numeric == 0.0 else ("%.6g" % numeric)
    return ("%.3e" % numeric) if span < 0.001 else ("%.6g" % numeric)


def build_capture_evidence(*, state: str, data: Mapping[str, Any], resolved: Any,
                           binding: CaptureBinding,
                           manifest: Mapping[str, Any]) -> CaptureEvidence:
    """Detach one validated capture so every downstream consumer agrees."""
    if not isinstance(manifest, Mapping):
        raise RecorderViewError("capture manifest must be a mapping")
    view = build_capture_view(
        state=state, data=data, resolved=resolved, binding=binding)
    try:
        manifest_json = json.dumps(
            dict(manifest), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RecorderViewError(
            "capture manifest must be finite JSON evidence") from exc
    detached_manifest = json.loads(manifest_json)
    if str(detached_manifest.get("capture_id") or "") != binding.capture_id:
        raise RecorderViewError("capture manifest ID disagrees with binding")
    if str(detached_manifest.get("drive_identity") or "") != binding.drive_identity:
        raise RecorderViewError("capture manifest drive identity disagrees with binding")
    # ``build_capture_view`` already validated the captured ``data.get('dt')``
    # against this immutable resolved value.  Do not touch caller-owned data a
    # second time: a hostile/flipping Mapping could otherwise split plot/CSV.
    dt_s = float(resolved.actual_resolution_us) * 1e-6
    return CaptureEvidence(
        view=view,
        resolved=resolved,
        dt_s=dt_s,
        _data_items=tuple((item.name, item.y) for item in view.series),
        _manifest_json=manifest_json,
    )


def layout_payload(layout: ViewLayout, *, available_channels: Sequence[str]) -> dict[str, Any]:
    """Return the explicit local-only JSON representation of a two-lane layout."""
    checked = _validate_layout(layout, available_channels)
    lanes = []
    for lane in checked.lanes:
        lanes.append({
            "channels": list(lane.channels),
            "visible": lane.visible,
            "y_range": (
                "auto" if lane.y_range is None
                else [lane.y_range[0], lane.y_range[1]]),
        })
    return {
        "schema": VIEW_LAYOUT_SCHEMA,
        "compatibility": LOCAL_COMPATIBILITY,
        "plot_mode": checked.plot_mode,
        "x_range_s": (
            "full" if checked.x_range_s is None
            else [checked.x_range_s[0], checked.x_range_s[1]]),
        "lanes": lanes,
    }


def parse_layout(payload: Mapping[str, Any], *,
                 available_channels: Sequence[str]) -> ViewLayout:
    if not isinstance(payload, Mapping):
        raise RecorderViewError("layout payload must be a mapping")
    schema = payload.get("schema")
    if schema not in (
            VIEW_LAYOUT_SCHEMA, PREVIOUS_VIEW_LAYOUT_SCHEMA,
            LEGACY_VIEW_LAYOUT_SCHEMA):
        raise RecorderViewError("unsupported Recorder View layout schema")
    if payload.get("compatibility") != LOCAL_COMPATIBILITY:
        raise RecorderViewError(
            "Recorder View layout must declare local-only compatibility")
    if schema == LEGACY_VIEW_LAYOUT_SCHEMA:
        if "x_range_s" in payload:
            raise RecorderViewError(
                "legacy Recorder View layout cannot declare a time window")
        if "plot_mode" in payload:
            raise RecorderViewError(
                "legacy Recorder View layout cannot declare plot_mode")
        x_range_s = None
        plot_mode = PLOT_MODE_TIME
    else:
        if "x_range_s" not in payload:
            raise RecorderViewError(
                "%s Recorder View layout requires x_range_s" % (
                    "v3" if schema == VIEW_LAYOUT_SCHEMA else "v2"))
        raw_x_range = payload["x_range_s"]
        if raw_x_range == "full":
            x_range_s = None
        elif isinstance(raw_x_range, (list, tuple)) and len(raw_x_range) == 2:
            x_range_s = (raw_x_range[0], raw_x_range[1])
        else:
            raise RecorderViewError(
                "x_range_s must be full or finite [min, max]")
        if schema == PREVIOUS_VIEW_LAYOUT_SCHEMA:
            if "plot_mode" in payload:
                raise RecorderViewError(
                    "v2 Recorder View layout cannot declare plot_mode")
            plot_mode = PLOT_MODE_TIME
        else:
            if "plot_mode" not in payload:
                raise RecorderViewError(
                    "v3 Recorder View layout requires plot_mode")
            plot_mode = _validate_plot_mode(payload["plot_mode"])
    raw_lanes = payload.get("lanes")
    if not isinstance(raw_lanes, (list, tuple)) or len(raw_lanes) != 2:
        raise RecorderViewError("Recorder View layout requires exactly two lanes")

    lanes = []
    for index, raw in enumerate(raw_lanes, start=1):
        if not isinstance(raw, Mapping):
            raise RecorderViewError("lane %d must be a mapping" % index)
        channels = raw.get("channels")
        if not isinstance(channels, (list, tuple)):
            raise RecorderViewError("lane %d channels must be a list" % index)
        visible = raw.get("visible")
        raw_range = raw.get("y_range")
        if raw_range == "auto":
            y_range = None
        elif isinstance(raw_range, (list, tuple)) and len(raw_range) == 2:
            y_range = (raw_range[0], raw_range[1])
        else:
            raise RecorderViewError(
                "lane %d y_range must be auto or [min, max]" % index)
        lanes.append(LaneLayout(tuple(channels), visible, y_range))
    return _validate_layout(
        ViewLayout(
            tuple(lanes), x_range_s=x_range_s, plot_mode=plot_mode),
        available_channels)


def validate_layout_for_view(layout: ViewLayout, view: CaptureView) -> ViewLayout:
    """Canonicalize a layout and bind its time window to one capture domain."""
    _validate_capture_view(view)
    checked = _validate_layout(layout, view.signals)
    if checked.plot_mode == PLOT_MODE_FFT:
        if view.display_sample_count < 2:
            raise RecorderViewError("FFT plot mode requires at least two samples")
        if view.display_sample_count != view.source_sample_count:
            raise RecorderViewError("FFT plot mode requires the full capture")
    if checked.x_range_s is None:
        return checked
    low, high = checked.x_range_s
    x_values = view.x_s
    spacing = min(
        right - left for left, right in zip(x_values, x_values[1:])
        if right > left
    ) if len(x_values) >= 2 else 1.0
    tolerance = min(1e-12, spacing * 1e-6)

    # Text/JSON round-trips can land a sub-picosecond away from an actual
    # sample.  Canonicalize those boundaries once so validation, rendering,
    # labels and persistence all use the same exact values.
    def snap_to_sample(value: float) -> float:
        nearest = min(x_values, key=lambda sample: abs(sample - value))
        return nearest if abs(nearest - value) <= tolerance else value

    low = snap_to_sample(low)
    high = snap_to_sample(high)
    if low < x_values[0] or high > x_values[-1]:
        raise RecorderViewError(
            "manual time window is outside the current capture")
    visible_count = sum(
        1 for value in x_values
        if low <= value <= high)
    if visible_count < 2:
        raise RecorderViewError(
            "manual time window must contain at least two captured samples")
    return replace(checked, x_range_s=(low, high))


def set_time_window(layout: ViewLayout, view: CaptureView,
                    time_window: tuple[float, float] | None) -> ViewLayout:
    """Return a new shared-X layout; capture data and lane Y ranges are untouched."""
    if not isinstance(layout, ViewLayout):
        raise RecorderViewError("structured ViewLayout is required")
    candidate = replace(layout, x_range_s=time_window)
    return validate_layout_for_view(candidate, view)


def set_plot_mode(layout: ViewLayout, view: CaptureView,
                  plot_mode: str) -> ViewLayout:
    """Switch local display mode without changing capture or saved time state."""
    if not isinstance(layout, ViewLayout):
        raise RecorderViewError("structured ViewLayout is required")
    checked = _validate_layout(layout, view.signals)
    candidate = replace(checked, plot_mode=_validate_plot_mode(plot_mode))
    # Run the capture-bound gate for rejection, but keep the already validated
    # time-window values byte-for-byte.  Switching display domain must not
    # silently rewrite the user's saved Time viewport through float snapping.
    validate_layout_for_view(candidate, view)
    return candidate


def save_layout(path: os.PathLike[str] | str, layout: ViewLayout, *,
                available_channels: Sequence[str]) -> None:
    """Atomically save app-local JSON; this is not an EAS-compatible format."""
    payload = layout_payload(layout, available_channels=available_channels)
    target = os.path.abspath(os.fspath(path))
    parent = os.path.dirname(target) or os.curdir
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=os.path.basename(target) + ".", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_layout(path: os.PathLike[str] | str, *,
                available_channels: Sequence[str]) -> ViewLayout:
    try:
        with open(os.fspath(path), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise RecorderViewError("invalid Recorder View layout JSON") from exc
    return parse_layout(payload, available_channels=available_channels)


def decimate_view(view: CaptureView, *, max_points: int) -> CaptureView:
    """Return a reduced immutable copy while retaining salient extrema/spikes."""
    _validate_capture_view(view)
    if (not isinstance(max_points, int) or isinstance(max_points, bool)
            or max_points < 2):
        raise RecorderViewError("max_points must be an integer of at least 2")
    count = view.display_sample_count
    if count <= max_points:
        indices = tuple(range(count))
    else:
        selected = {0, count - 1}

        # Global extrema are safety-relevant in recorder traces.  Seed them
        # before uniform points so a one-sample peak is not silently erased.
        extrema = set()
        for item in view.series:
            extrema.add(min(range(count), key=lambda index: item.y[index]))
            extrema.add(max(range(count), key=lambda index: item.y[index]))
        series_ranges = tuple(
            max(max(item.y) - min(item.y), 1e-30)
            for item in view.series)

        def local_prominence(index: int) -> float:
            score = 0.0
            for item, scale in zip(view.series, series_ranges):
                if 0 < index < count - 1:
                    left, center, right = (
                        item.y[index - 1], item.y[index], item.y[index + 1])
                    if center > left and center > right:
                        prominence = center - max(left, right)
                    elif center < left and center < right:
                        prominence = min(left, right) - center
                    else:
                        prominence = 0.0
                    score = max(score, prominence / scale)
            return score

        for index in sorted(
                (index for index in extrema if index not in selected),
                key=lambda index: (-local_prominence(index), index)):
            if len(selected) >= max_points:
                break
            selected.add(index)

        # Consume the remaining display budget with the strongest strict
        # local extrema before uniform samples.  This catches a narrow local
        # spike even when a larger global peak exists elsewhere.
        local_extrema = sorted(
            (index for index in range(1, count - 1)
             if index not in selected and local_prominence(index) > 0.0),
            key=lambda index: (-local_prominence(index), index))
        for index in local_extrema:
            if len(selected) >= max_points:
                break
            selected.add(index)

        uniform = (
            int(round(index * (count - 1) / (max_points - 1)))
            for index in range(max_points)
        )
        for index in uniform:
            if len(selected) >= max_points:
                break
            selected.add(index)

        if len(selected) < max_points:
            candidates = [
                index for index in range(1, count - 1)
                if index not in selected]
            selected.update(candidates[:max_points - len(selected)])
        indices = tuple(sorted(selected))
    reduced = tuple(
        SignalSeries(
            name=item.name,
            x=tuple(item.x[index] for index in indices),
            y=tuple(item.y[index] for index in indices),
        )
        for item in view.series
    )
    return CaptureView(
        binding=view.binding,
        series=reduced,
        source_sample_count=view.source_sample_count,
        units=UNITS_NOTICE,
    )


def _validate_binding(binding: CaptureBinding) -> None:
    valid = (
        isinstance(binding, CaptureBinding)
        and isinstance(binding.capture_id, str)
        and bool(binding.capture_id.strip())
        and isinstance(binding.generation, int)
        and not isinstance(binding.generation, bool)
        and binding.generation > 0
        and isinstance(binding.drive_identity, str)
        and bool(binding.drive_identity.strip())
    )
    if not valid:
        raise RecorderViewError(
            "capture binding requires capture_id, positive generation, and drive_identity")


def _exact_names(names: Sequence[str], label: str) -> tuple[str, ...]:
    if isinstance(names, (str, bytes)):
        raise RecorderViewError("%s must be a sequence of exact names" % label)
    try:
        result = tuple(names)
    except TypeError as exc:
        raise RecorderViewError("%s must be a sequence" % label) from exc
    if any(not isinstance(name, str) or not name for name in result):
        raise RecorderViewError("%s contain an invalid channel name" % label)
    if len(set(result)) != len(result):
        raise RecorderViewError("%s contain a duplicate channel" % label)
    return result


def _validate_y_range(value: Any, lane_index: int) -> tuple[float, float] | None:
    if value is None:
        return None
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise RecorderViewError(
            "lane %d y_range must be auto or finite [min, max]" % lane_index)
    if any(isinstance(item, bool) for item in value):
        raise RecorderViewError("lane %d y_range must be finite" % lane_index)
    try:
        low, high = float(value[0]), float(value[1])
    except (TypeError, ValueError, OverflowError) as exc:
        raise RecorderViewError("lane %d y_range must be finite" % lane_index) from exc
    if not math.isfinite(low) or not math.isfinite(high):
        raise RecorderViewError("lane %d y_range must be finite" % lane_index)
    if not low < high:
        raise RecorderViewError("lane %d y_range requires min < max" % lane_index)
    return low, high


def _validate_x_range(value: Any) -> tuple[float, float] | None:
    if value is None:
        return None
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise RecorderViewError(
            "x_range_s must be full or finite [min, max]")
    if any(isinstance(item, bool) for item in value):
        raise RecorderViewError("x_range_s must be finite")
    try:
        low, high = float(value[0]), float(value[1])
    except (TypeError, ValueError, OverflowError) as exc:
        raise RecorderViewError("x_range_s must be finite") from exc
    if not math.isfinite(low) or not math.isfinite(high):
        raise RecorderViewError("x_range_s must be finite")
    if low < 0.0:
        raise RecorderViewError("x_range_s cannot start before zero")
    if not low < high:
        raise RecorderViewError("x_range_s requires min < max")
    return low, high


def _validate_plot_mode(value: Any) -> str:
    if type(value) is not str or value not in (PLOT_MODE_TIME, PLOT_MODE_FFT):
        raise RecorderViewError("plot_mode must be 'time' or 'fft'")
    return value


def _validate_layout(layout: ViewLayout,
                     available_channels: Sequence[str]) -> ViewLayout:
    available = _exact_names(available_channels, "available channels")
    if not isinstance(layout, ViewLayout):
        raise RecorderViewError("structured ViewLayout is required")
    if not isinstance(layout.lanes, (tuple, list)) or len(layout.lanes) != 2:
        raise RecorderViewError("Recorder View layout requires exactly two lanes")
    known = set(available)
    checked_lanes = []
    for index, lane in enumerate(layout.lanes, start=1):
        if not isinstance(lane, LaneLayout):
            raise RecorderViewError("lane %d must be a LaneLayout" % index)
        channels = _exact_names(lane.channels, "lane %d channels" % index)
        if len(channels) > 1:
            raise RecorderViewError(
                "lane %d supports at most one channel in View v1" % index)
        unknown = [name for name in channels if name not in known]
        if unknown:
            raise RecorderViewError(
                "lane %d contains unknown channel %r" % (index, unknown[0]))
        if type(lane.visible) is not bool:
            raise RecorderViewError("lane %d visible must be boolean" % index)
        checked_lanes.append(LaneLayout(
            channels=channels,
            visible=lane.visible,
            y_range=_validate_y_range(lane.y_range, index),
        ))
    return ViewLayout(
        tuple(checked_lanes),
        x_range_s=_validate_x_range(layout.x_range_s),
        plot_mode=_validate_plot_mode(layout.plot_mode))


def _validate_capture_view(view: CaptureView) -> None:
    if not isinstance(view, CaptureView):
        raise RecorderViewError("structured CaptureView is required")
    _validate_binding(view.binding)
    if view.units != UNITS_NOTICE:
        raise RecorderViewError("Recorder View units notice was altered")
    if (not isinstance(view.source_sample_count, int)
            or isinstance(view.source_sample_count, bool)
            or view.source_sample_count <= 0):
        raise RecorderViewError("source_sample_count must be positive")
    if not isinstance(view.series, tuple) or not view.series:
        raise RecorderViewError("CaptureView requires immutable signal series")
    _exact_names(tuple(item.name for item in view.series), "view signals")
    display_count = None
    reference_x = None
    for item in view.series:
        if (not isinstance(item, SignalSeries)
                or not isinstance(item.x, tuple)
                or not isinstance(item.y, tuple)
                or not item.x
                or len(item.x) != len(item.y)):
            raise RecorderViewError("signal series must contain immutable paired x/y data")
        if any(not math.isfinite(value) for value in item.x + item.y):
            raise RecorderViewError("signal series must contain finite x/y data")
        if any(item.x[i] >= item.x[i + 1] for i in range(len(item.x) - 1)):
            raise RecorderViewError("signal x values must be strictly increasing")
        if display_count is None:
            display_count = len(item.x)
            reference_x = item.x
        elif len(item.x) != display_count or item.x != reference_x:
            raise RecorderViewError("all signal series must share one exact x axis")
    if view.source_sample_count < int(display_count or 0):
        raise RecorderViewError("view cannot exceed its source sample count")
