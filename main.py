"""Elmo Gold Control — mini-EAS desktop GUI (Made after EAS III).

First screens: connection + Single Axis Motion dashboard, built on the official
Drive .NET Library transport (elmo_link) and the SDD PyQt6 shell.

Run:   python main.py
Smoke: python main.py --smoke     (offscreen render, no hardware)

Safety: telemetry is read continuously, while every drive write is routed through
an explicit UI action. Production hardware gain trials and finite PTP remain
locked; retained recovery trials are Restore-only.
"""
from __future__ import annotations

import sys
import os
import json
import html
import math
import time
from datetime import datetime, timezone
import hashlib
import tempfile
import uuid
import re

import collections

from PyQt6 import QtCore, QtGui, QtWidgets

# swappable skin: AYJH_THEME = qdd (default) | angrybirds | amber
_THEME = os.environ.get("AYJH_THEME", "qdd").lower()
if _THEME == "amber":
    import theme
elif _THEME == "angrybirds":
    import theme_angrybirds as theme
else:
    import theme_qdd as theme
from elmo_link import ElmoLink
import feedback_spec
import autotune_current
import autotune_velpos
import expert_tuning_offline
import expert_filter_scheduling_evidence
import expert_limits_protections_evidence
import expert_application_settings_evidence
import expert_bode_verification_evidence
import expert_time_verification_evidence
import expert_summary_transaction_evidence
import expert_page_status
import expert_user_units
import single_axis_motion
import single_axis_status
import single_axis_enable_contract
import single_axis_authority_evidence
import single_axis_current_reference
import single_axis_drive_mode
import single_axis_digital_inputs
import single_axis_digital_outputs
import recorder_control
import recorder_view
import operation_catalog
import session_log
import status_monitor
import system_configuration
import tool_organizer

APP_TITLE = "AngryYJH Control"
POLL_HZ = 5
TELEMETRY_REQUIRED_FIELDS = ("pos", "vel", "pos_err", "iq", "mo")
TELEMETRY_MAX_SAMPLE_DURATION_S = 1.0
TELEMETRY_SOURCE_MAX_AGE_S = 0.5
TELEMETRY_UI_MAX_AGE_S = 1.5
_HASHED_DRIVE_ID_RE = re.compile(
    r"^elmo-sn4-sha256:[0-9a-f]{64}$")
_RECORDER_OFFLINE_TEST_CAPABILITY = object()
# The finite-PTP kernel is implemented and tested with command-level doubles,
# but live motion remains fail-closed until a site-specific envelope (mechanical
# travel, direction, validated SD/stopping distance, limit inputs and independent
# E-stop/STO evidence) is entered and verified.  Do not turn this into an
# environment-variable bypass: activation must be a reviewed code/config change.
FINITE_PTP_LIVE_ENABLED = False
# Hardware RAM gain trials stay disabled until their write-ahead record can
# coexist safely with the P2_LIMITS transaction used during verification.
# Synthetic kernels opt in inside their domain modules; the desktop UI never
# exposes that test-only capability.
PRODUCTION_GAIN_TRIALS_ENABLED = False
OBSERVE_ONLY_ACCESS_MODE = "OBSERVE_ONLY_WITH_SAFE_SHUTDOWN"
SUPERVISED_ACCESS_MODE = "SUPERVISED_CONTROL"
_ACCESS_MODE_LABELS = {
    OBSERVE_ONLY_ACCESS_MODE: "Read Only",
    SUPERVISED_ACCESS_MODE: "Supervised Control",
}


class SessionCoordinateError(RuntimeError):
    """A coordinate write failed and the current PX state may be unknown."""

    def __init__(self, message, *, coordinate_unknown=False, telemetry=None):
        super().__init__(message)
        self.coordinate_unknown = bool(coordinate_unknown)
        self.telemetry = telemetry


class _EnergyAwareLink:
    """Transparent link proxy that latches worker ownership before energization.

    The tuning kernels receive this proxy only for the duration of an explicitly
    approved energizing workflow.  Read/preflight behavior is unchanged.  Once
    a power/motion command is attempted, shutdown owns a verified ST/MO=0
    closeout even if the algorithm raises or its reply is lost.
    """

    _LOCAL_NAMES = frozenset(("_base", "_on_energy", "_can_energize"))

    def __init__(self, base, on_energy, can_energize):
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_on_energy", on_energy)
        object.__setattr__(self, "_can_energize", can_energize)

    @staticmethod
    def _energizes(command, allow_motion):
        if not allow_motion:
            return False
        core = str(command).strip().rstrip(";").strip().upper().replace(" ", "")
        if core in {"BG", "SE", "MI"} or core.startswith(("BG[", "SE[", "MI[")):
            return True
        for prefix in ("MO=", "TC=", "JV="):
            if core.startswith(prefix):
                try:
                    return float(core[len(prefix):]) != 0.0
                except (TypeError, ValueError, OverflowError):
                    return True
        return False

    def command(self, command, *args, **kwargs):
        if self._energizes(command, bool(kwargs.get("allow_motion", False))):
            if not bool(self._can_energize()):
                raise PermissionError(
                    "energizing command rejected after cancel/disconnect")
            self._on_energy(str(command))
        return self._base.command(command, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._base, name)

    @property
    def transaction_session_link(self):
        """Canonical identity for gain-trial session capability checks."""
        return self._base

    def __setattr__(self, name, value):
        if name in self._LOCAL_NAMES:
            object.__setattr__(self, name, value)
            return
        # Deterministic offline fakes often model the accepted MO=1 command by
        # assigning their ``mo`` state directly inside the algorithm stub.
        if name == "mo" and value == 1:
            if not bool(self._can_energize()):
                raise PermissionError(
                    "energizing state transition rejected after cancel/disconnect")
            self._on_energy("MO=1 (simulated state transition)")
        setattr(self._base, name, value)


def list_serial_ports():
    """Return available COM port names (auto-detect). Falls back gracefully."""
    ports = []
    try:
        from serial.tools import list_ports
        ports = [p.device for p in list_ports.comports()]
    except Exception:
        pass
    # de-dup, natural-ish sort
    return sorted(set(ports), key=lambda s: (len(s), s))


class ExpertBodeWidget(QtWidgets.QWidget):
    """Compact read-only view of an offline Expert current-loop response.

    The widget accepts only immutable response data.  It deliberately owns no
    worker, link, command callback, or editable control.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.response = None
        self.setMinimumHeight(180)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed)

    def set_response(self, response):
        self.response = response
        self.update()

    @staticmethod
    def _path(x_values, y_values, rect, *, y_min=None, y_max=None):
        path = QtGui.QPainterPath()
        if not x_values or not y_values:
            return path
        x_min = math.log10(float(x_values[0]))
        x_max = math.log10(float(x_values[-1]))
        if y_min is None:
            y_min = min(float(value) for value in y_values)
        if y_max is None:
            y_max = max(float(value) for value in y_values)
        y_span = max(1e-12, y_max - y_min)
        x_span = max(1e-12, x_max - x_min)
        for index, (x_value, y_value) in enumerate(zip(x_values, y_values)):
            x_norm = (math.log10(float(x_value)) - x_min) / x_span
            y_norm = (float(y_value) - y_min) / y_span
            point = QtCore.QPointF(
                rect.left() + x_norm * rect.width(),
                rect.bottom() - y_norm * rect.height())
            if index:
                path.lineTo(point)
            else:
                path.moveTo(point)
        return path

    def paintEvent(self, event):
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QtGui.QColor(theme.INSET))
        if self.response is None:
            painter.setPen(QtGui.QColor(theme.MUTED))
            painter.drawText(
                self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter,
                "OFFLINE BODE PREVIEW · calculate a MODEL candidate")
            return

        outer = QtCore.QRectF(self.rect()).adjusted(52, 20, -16, -26)
        magnitude = QtCore.QRectF(
            outer.left(), outer.top(), outer.width(), outer.height() * 0.55)
        phase = QtCore.QRectF(
            outer.left(), magnitude.bottom() + 18,
            outer.width(), outer.height() * 0.30)
        grid_pen = QtGui.QPen(QtGui.QColor(theme.MUTED))
        grid_pen.setWidthF(0.7)
        painter.setPen(grid_pen)
        painter.drawRect(magnitude)
        painter.drawRect(phase)
        painter.drawText(
            QtCore.QRectF(4, magnitude.top(), 46, 18),
            QtCore.Qt.AlignmentFlag.AlignRight, "MAG dB")
        painter.drawText(
            QtCore.QRectF(4, phase.top(), 46, 18),
            QtCore.Qt.AlignmentFlag.AlignRight, "PH deg")
        painter.drawText(
            QtCore.QRectF(
                outer.left(), phase.bottom() + 3, outer.width(), 20),
            QtCore.Qt.AlignmentFlag.AlignCenter, "frequency [Hz] · log")

        frequencies = self.response.frequency_hz
        magnitude_values = (
            self.response.open_loop_magnitude_db
            + self.response.closed_loop_magnitude_db)
        magnitude_min = min(magnitude_values)
        magnitude_max = max(magnitude_values)
        for values, color in (
                (self.response.open_loop_magnitude_db, theme.C_BLUE),
                (self.response.closed_loop_magnitude_db, theme.C_AMBER)):
            pen = QtGui.QPen(QtGui.QColor(color))
            pen.setWidthF(1.6)
            painter.setPen(pen)
            painter.drawPath(self._path(
                frequencies, values, magnitude,
                y_min=magnitude_min, y_max=magnitude_max))
        painter.setPen(QtGui.QColor(theme.C_BLUE))
        painter.drawText(
            QtCore.QRectF(magnitude.left() + 6, magnitude.top() + 3, 60, 16),
            QtCore.Qt.AlignmentFlag.AlignLeft, "OPEN")
        painter.setPen(QtGui.QColor(theme.C_AMBER))
        painter.drawText(
            QtCore.QRectF(magnitude.left() + 68, magnitude.top() + 3, 70, 16),
            QtCore.Qt.AlignmentFlag.AlignLeft, "CLOSED")
        phase_pen = QtGui.QPen(QtGui.QColor(theme.C_CYAN))
        phase_pen.setWidthF(1.4)
        painter.setPen(phase_pen)
        painter.drawPath(self._path(
            frequencies, self.response.open_loop_phase_deg, phase))


class RecorderPlotWidget(QtWidgets.QWidget):
    """Dependency-free, read-only two-lane plot for a validated capture view.

    The widget owns no worker/link reference and cannot issue drive commands.
    Any point reduction is performed on an immutable display copy; the raw
    capture retained for CSV export is never modified.
    """

    _COLORS = (theme.C_BLUE, theme.C_AMBER, theme.C_CYAN, theme.C_VIOLET)
    _MARGIN_LEFT = 76
    _MARGIN_RIGHT = 18
    _MARGIN_TOP = 22
    _MARGIN_BOTTOM = 28
    _LANE_GAP = 46
    _MARKER_HIT_RADIUS_PX = 8.0

    sampleRangePreview = QtCore.pyqtSignal(object, int, int)
    sampleRangeCommitted = QtCore.pyqtSignal(object, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view_model = None
        self.spectrum_model = None
        self.layout_model = None
        self.sample_range_selection = None
        self._drag_marker = None
        self._drag_source_view = None
        self._drag_lane_index = None
        self._drag_pair = None
        self._drag_changed = False
        self.setMinimumHeight(300)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding)

    def clear(self):
        self._cancel_range_drag()
        self.view_model = None
        self.spectrum_model = None
        self.layout_model = None
        self.sample_range_selection = None
        self.update()

    def set_view_model(self, model, layout=None):
        if model is None:
            self.clear()
            return
        replacing_evidence = self.view_model is not model
        names = tuple(model.signals)
        if layout is None:
            layout = recorder_view.ViewLayout((
                recorder_view.LaneLayout(names[:1]),
                recorder_view.LaneLayout(names[1:2]),
            ))
        # Store the canonical, capture-bound layout rather than the caller's
        # possibly stringly-typed or out-of-domain object.
        layout = recorder_view.validate_layout_for_view(layout, model)
        spectrum = (
            recorder_view.build_spectrum_view(model)
            if layout.plot_mode == recorder_view.PLOT_MODE_FFT
            else None
        )
        self._cancel_range_drag()
        self.view_model = model
        self.spectrum_model = spectrum
        self.layout_model = layout
        if replacing_evidence:
            self.sample_range_selection = None
        self.update()

    def set_sample_range(self, selection):
        """Display a capture-bound local A/B range; never touch drive state."""
        if selection is not None:
            if (self.view_model is None
                    or not isinstance(
                        selection, recorder_view.SampleRangeSelection)
                    or selection.binding != self.view_model.binding):
                raise recorder_view.RecorderViewError(
                    "sample range must match the displayed capture")
        self.sample_range_selection = selection
        self.update()

    def set_lanes(self, first, second):
        if self.view_model is None:
            return
        current = self.layout_model or recorder_view.ViewLayout((
            recorder_view.LaneLayout(), recorder_view.LaneLayout()))
        requested = (
            (first,) if first else (),
            (second,) if second else (),
        )
        lanes = []
        for old, channels in zip(current.lanes, requested):
            # A signal change keeps the shared time viewport and the other
            # lane state, but drops a unit-unknown manual Y range for the
            # changed lane so stale scaling is not misapplied.
            lanes.append(recorder_view.LaneLayout(
                channels=channels,
                visible=old.visible,
                y_range=(old.y_range if old.channels == channels else None),
            ))
        layout = recorder_view.ViewLayout(
            (lanes[0], lanes[1]),
            x_range_s=current.x_range_s,
            plot_mode=current.plot_mode,
        )
        self.set_view_model(self.view_model, layout)

    def sizeHint(self):
        return QtCore.QSize(720, 390)

    def _cancel_range_drag(self):
        self._drag_marker = None
        self._drag_source_view = None
        self._drag_lane_index = None
        self._drag_pair = None
        self._drag_changed = False
        self.unsetCursor()

    def _plot_geometry(self):
        """Return the exact X viewport and lane rects shared by paint/hit-test."""
        if self.view_model is None or self.layout_model is None:
            return None
        fft_mode = (
            self.layout_model.plot_mode == recorder_view.PLOT_MODE_FFT)
        display = self.spectrum_model if fft_mode else self.view_model
        if display is None:
            return None
        if fft_mode:
            x_min, x_max = display.x_hz[0], display.x_hz[-1]
        elif self.layout_model.x_range_s is None:
            x_min, x_max = self.view_model.x_s[0], self.view_model.x_s[-1]
        else:
            x_min, x_max = self.layout_model.x_range_s
        available_h = max(
            80,
            self.height() - self._MARGIN_TOP - self._MARGIN_BOTTOM
            - self._LANE_GAP,
        )
        lane_h = max(36, available_h // 2)
        lane_width = max(
            10, self.width() - self._MARGIN_LEFT - self._MARGIN_RIGHT)
        rects = tuple(
            QtCore.QRectF(
                self._MARGIN_LEFT,
                self._MARGIN_TOP
                + lane_index * (lane_h + self._LANE_GAP),
                lane_width,
                lane_h,
            )
            for lane_index in range(2)
        )
        return x_min, x_max, rects

    @staticmethod
    def _marker_x(time_s, rect, x_min, x_max):
        x_norm = ((time_s - x_min) / (x_max - x_min)
                  if x_max > x_min else 0.0)
        return rect.left() + x_norm * rect.width()

    def _interactive_lane_index(self, position, rects):
        for lane_index, (lane, rect) in enumerate(
                zip(self.layout_model.lanes, rects)):
            if (lane.visible and lane.channels
                    and rect.contains(position)):
                return lane_index
        return None

    def _update_range_drag(self, position):
        source = self._drag_source_view
        pair = self._drag_pair
        geometry = self._plot_geometry()
        if (source is None or source is not self.view_model
                or pair is None or geometry is None
                or self.layout_model.plot_mode != recorder_view.PLOT_MODE_TIME):
            self._cancel_range_drag()
            return
        x_min, x_max, rects = geometry
        lane_index = self._drag_lane_index
        if lane_index is None or not 0 <= lane_index < len(rects):
            self._cancel_range_drag()
            return
        rect = rects[lane_index]
        x_pixel = min(max(position.x(), rect.left()), rect.right())
        time_s = (
            x_min + ((x_pixel - rect.left()) / rect.width())
            * (x_max - x_min)
            if rect.width() > 0.0 else x_min)
        try:
            snapped = recorder_view.nearest_visible_sample_index(
                source,
                time_s=time_s,
                visible_range_s=(x_min, x_max),
            )
        except recorder_view.RecorderViewError:
            self._cancel_range_drag()
            return
        start_index, end_index = pair
        if self._drag_marker == "A":
            start_index = min(snapped, end_index - 1)
        else:
            end_index = max(snapped, start_index + 1)
        updated = (start_index, end_index)
        if updated == pair:
            return
        try:
            selection = recorder_view.build_sample_range_selection(
                source,
                start_index=start_index,
                end_index=end_index,
            )
        except recorder_view.RecorderViewError:
            return
        self._drag_pair = updated
        self._drag_changed = True
        self.set_sample_range(selection)
        self.sampleRangePreview.emit(source, start_index, end_index)

    def mousePressEvent(self, event):
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        geometry = self._plot_geometry()
        selection = self.sample_range_selection
        if (geometry is None or self.view_model is None
                or self.layout_model.plot_mode != recorder_view.PLOT_MODE_TIME
                or not isinstance(
                    selection, recorder_view.SampleRangeSelection)
                or selection.binding != self.view_model.binding):
            super().mousePressEvent(event)
            return
        x_min, x_max, rects = geometry
        lane_index = self._interactive_lane_index(event.position(), rects)
        if lane_index is None:
            super().mousePressEvent(event)
            return
        rect = rects[lane_index]
        visible_markers = tuple(
            (marker_index, self._marker_x(
                time_s, rect, x_min, x_max))
            for marker_index, time_s in (
                (0, selection.start_time_s),
                (1, selection.end_time_s))
            if x_min <= time_s <= x_max)
        if not visible_markers:
            super().mousePressEvent(event)
            return
        closest, _marker_position = min(
            visible_markers,
            key=lambda item: (
                abs(event.position().x() - item[1]), item[0]))
        if (abs(event.position().x() - _marker_position)
                > self._MARKER_HIT_RADIUS_PX):
            super().mousePressEvent(event)
            return
        self._drag_marker = "A" if closest == 0 else "B"
        self._drag_source_view = self.view_model
        self._drag_lane_index = lane_index
        self._drag_pair = (
            selection.start_index, selection.end_index)
        self._drag_changed = False
        self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_source_view is None:
            super().mouseMoveEvent(event)
            return
        if not (event.buttons() & QtCore.Qt.MouseButton.LeftButton):
            self._cancel_range_drag()
            super().mouseMoveEvent(event)
            return
        self._update_range_drag(event.position())
        event.accept()

    def mouseReleaseEvent(self, event):
        if (event.button() != QtCore.Qt.MouseButton.LeftButton
                or self._drag_source_view is None):
            super().mouseReleaseEvent(event)
            return
        self._update_range_drag(event.position())
        source = self._drag_source_view
        pair = self._drag_pair
        changed = self._drag_changed
        self._cancel_range_drag()
        if (changed and source is self.view_model and pair is not None):
            self.sampleRangeCommitted.emit(source, pair[0], pair[1])
        event.accept()

    @staticmethod
    def _fmt_axis(value, axis_span):
        return recorder_view.format_axis_value(value, axis_span=axis_span)

    @staticmethod
    def _build_series_path(item, rect, *, x_min, x_max, y_min, y_max):
        """Build one exact visible path and report its measured point count."""
        path = QtGui.QPainterPath()
        plotted_count = 0
        y_span = max(1e-30, y_max - y_min)
        for x_value, y_value in zip(item.x, item.y):
            if x_value < x_min or x_value > x_max:
                continue
            x_norm = ((x_value - x_min) / (x_max - x_min)
                      if x_max > x_min else 0.0)
            y_norm = (y_value - y_min) / y_span
            point = QtCore.QPointF(
                rect.left() + x_norm * rect.width(),
                rect.bottom() - y_norm * rect.height())
            if plotted_count == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
            plotted_count += 1
        return path, plotted_count

    def paintEvent(self, event):
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QtGui.QColor(theme.INSET))
        if self.view_model is None or self.layout_model is None:
            painter.setPen(QtGui.QColor(theme.MUTED))
            painter.drawText(
                self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter,
                "No validated capture\nRecording → Immediate → Upload Buffer → PC")
            return

        model = self.view_model
        fft_mode = self.layout_model.plot_mode == recorder_view.PLOT_MODE_FFT
        # The drive has a hard 16K total-sample buffer and View v1 allows one
        # channel per lane.  Render the full immutable capture so a transient
        # cannot disappear through display decimation.
        display = self.spectrum_model if fft_mode else model
        if display is None:
            painter.setPen(QtGui.QColor(theme.MUTED))
            painter.drawText(
                self.rect(), QtCore.Qt.AlignmentFlag.AlignCenter,
                "FFT display is unavailable for this capture")
            return
        series_by_name = {item.name: item for item in display.series}
        full_series_by_name = {item.name: item for item in display.series}
        geometry = self._plot_geometry()
        if geometry is None:
            return
        x_min, x_max, lane_rects = geometry
        x_unit = "Hz" if fft_mode else "s"
        margin_left = self._MARGIN_LEFT
        font = painter.font(); font.setFamily("Cascadia Mono"); font.setPointSize(8)
        painter.setFont(font)

        for lane_index, (lane, rect) in enumerate(
                zip(self.layout_model.lanes, lane_rects)):
            painter.setPen(QtGui.QPen(QtGui.QColor(theme.BORDER), 1))
            painter.setBrush(QtGui.QColor(theme.CARD_SOFT))
            painter.drawRoundedRect(rect, 4, 4)
            channels = tuple(lane.channels) if lane.visible else ()
            selected = [series_by_name[name] for name in channels if name in series_by_name]
            if not selected:
                painter.setPen(QtGui.QColor(theme.FAINT))
                painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter,
                                 "Chart %d · no signal assigned" % (lane_index + 1))
                continue

            # Auto range comes from the full immutable evidence, not just the
            # display-reduced copy.  A short transient must still affect axes.
            full_selected = [
                full_series_by_name[name] for name in channels
                if name in full_series_by_name]
            all_y = [value for item in full_selected for value in item.y]
            if fft_mode:
                y_min, y_max = recorder_view.spectrum_zero_scale_bounds(
                    full_selected)
            elif lane.y_range is None:
                y_min, y_max = min(all_y), max(all_y)
                if y_min == y_max:
                    pad = max(1.0, abs(y_min) * 0.05)
                    y_min, y_max = y_min - pad, y_max + pad
                else:
                    pad = (y_max - y_min) * 0.05
                    y_min, y_max = y_min - pad, y_max + pad
            else:
                y_min, y_max = lane.y_range

            painter.setPen(QtGui.QPen(QtGui.QColor(theme.BORDER), 1))
            for grid_index in range(1, 4):
                y = rect.top() + rect.height() * grid_index / 4.0
                painter.drawLine(QtCore.QPointF(rect.left(), y),
                                 QtCore.QPointF(rect.right(), y))
            for grid_index in range(1, 5):
                x = rect.left() + rect.width() * grid_index / 5.0
                painter.drawLine(QtCore.QPointF(x, rect.top()),
                                 QtCore.QPointF(x, rect.bottom()))

            painter.save()
            painter.setClipRect(rect)
            for color_index, item in enumerate(selected):
                path, _plotted_count = self._build_series_path(
                    item, rect,
                    x_min=x_min, x_max=x_max,
                    y_min=y_min, y_max=y_max)
                painter.setPen(QtGui.QPen(
                    QtGui.QColor(self._COLORS[color_index % len(self._COLORS)]), 1.5))
                painter.drawPath(path)
            if not fft_mode and self.sample_range_selection is not None:
                markers = (
                    ("A", self.sample_range_selection.start_time_s,
                     theme.C_AMBER),
                    ("B", self.sample_range_selection.end_time_s,
                     theme.C_CYAN),
                )
                for label, time_s, color in markers:
                    if x_min <= time_s <= x_max:
                        x = self._marker_x(
                            time_s, rect, x_min, x_max)
                        painter.setPen(QtGui.QPen(QtGui.QColor(color), 1.5))
                        painter.drawLine(
                            QtCore.QPointF(x, rect.top()),
                            QtCore.QPointF(x, rect.bottom()))
                        painter.drawText(
                            QtCore.QPointF(x + 3, rect.top() + 13), label)
            painter.restore()

            painter.setPen(QtGui.QColor(theme.TEXT))
            painter.drawText(
                QtCore.QRectF(rect.left(), rect.top() - 20, rect.width(), 18),
                QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter,
                "Chart %d · %s · %s" % (
                    lane_index + 1,
                    "FFT" if fft_mode else "TIME",
                    " · ".join(channels)))
            painter.setPen(QtGui.QColor(theme.MUTED))
            y_span = y_max - y_min
            x_span = x_max - x_min
            painter.drawText(
                QtCore.QRectF(4, rect.top() - 2, margin_left - 10, 16),
                QtCore.Qt.AlignmentFlag.AlignRight,
                self._fmt_axis(y_max, y_span))
            painter.drawText(
                QtCore.QRectF(4, rect.bottom() - 14, margin_left - 10, 16),
                QtCore.Qt.AlignmentFlag.AlignRight,
                self._fmt_axis(y_min, y_span))
            painter.drawText(
                QtCore.QRectF(rect.left(), rect.bottom() + 3, rect.width(), 18),
                QtCore.Qt.AlignmentFlag.AlignLeft,
                "%s %s" % (self._fmt_axis(x_min, x_span), x_unit))
            painter.drawText(
                QtCore.QRectF(rect.left(), rect.bottom() + 3, rect.width(), 18),
                QtCore.Qt.AlignmentFlag.AlignRight,
                "%s %s" % (self._fmt_axis(x_max, x_span), x_unit))


# ---------------------------------------------------------------------------------------
# Drive worker — owns ALL drive I/O in one thread (pythonnet COM object is single-thread)
# ---------------------------------------------------------------------------------------
class DriveWorker(QtCore.QThread):
    OBSERVE_ONLY_ACCESS_MODE = OBSERVE_ONLY_ACCESS_MODE
    SUPERVISED_ACCESS_MODE = SUPERVISED_ACCESS_MODE
    _QUIESCENT_ADMISSION_REGISTERS = ("MO", "SO", "VX", "PS", "MF")
    _OBSERVE_ONLY_JOB_ALLOWLIST = frozenset((
        "axis_read", "axis_drive_mode_read", "axis_current_reference_read",
        "axis_digital_inputs_read", "axis_digital_outputs_read",
        "persistence_audit",
        "motion_stop", "recorder_stop",
    ))
    _READ_ONLY_QUERY_ALLOWLIST = frozenset((
        "VR", "VP", "VB", "SN[4]", "PX", "VX", "PE", "IQ",
        "MO", "SO", "MS", "MF", "SR", "ID", "UM", "RM",
        "TC", "CL[1]", "PL[1]", "LC", "MC",
    ))
    _TRIAL_JOB_ALLOWLIST = {
        "P1": frozenset(("p1_trial_restore", "p1_trial_commit")),
        "P2": frozenset(("verify_vp", "vp_trial_restore", "vp_trial_commit")),
    }
    _ENCODER_OPERATION_IDS = frozenset(
        ("set_datum_shift", "reset_multiturn", "reset_errors"))
    _PRE_MUTATION_FRESH_REQUIRED = frozenset((
        "motor_write", "feedback_write", "motion_move", "recorder_start",
        "autotune", "velpos", "verify_vp", "p1_trial_begin",
        "p1_trial_restore", "p1_trial_commit", "vp_trial_begin",
        "vp_trial_restore", "vp_trial_commit", "soft_zero", "encoder_maint",
    ))

    connected = QtCore.pyqtSignal(dict)      # {fw, pal, boot, target_type}
    failed = QtCore.pyqtSignal(str)
    telemetry = QtCore.pyqtSignal(dict)      # {pos, vel, pos_err, iq, mo}
    command_done = QtCore.pyqtSignal(str, str)   # (cmd, response)
    motor_params = QtCore.pyqtSignal(dict)       # Motor Settings snapshot
    feedback = QtCore.pyqtSignal(dict)           # Feedback/encoder config
    tuning_gains = QtCore.pyqtSignal(dict)       # control-loop gains (read-only)
    write_result = QtCore.pyqtSignal(bool, str)  # (ok, message) for config writes
    autotune_started = QtCore.pyqtSignal()
    autotune_progress = QtCore.pyqtSignal(str, str)   # (phase_code, human detail)
    autotune_result = QtCore.pyqtSignal(object)       # autotune_current.AutotuneResult
    autotune_applied = QtCore.pyqtSignal(bool, str)   # (ok, message) for gain apply
    current_gain_action = QtCore.pyqtSignal(str, bool, str, object)
    # action, ok, message, GainTrialP1 (begin/restore/commit)
    velpos_started = QtCore.pyqtSignal()                  # Phase 2 (vel/pos) mirror set
    velpos_progress = QtCore.pyqtSignal(str, str)         # (phase_code, human detail)
    velpos_result = QtCore.pyqtSignal(object)             # autotune_velpos.AutotuneVPResult
    velpos_applied = QtCore.pyqtSignal(bool, str)         # (ok, message) for KP[2..3] apply
    velpos_gain_action = QtCore.pyqtSignal(str, bool, str, object)
    # action, ok, message, GainTrialVP (begin/restore/commit)
    verify_started = QtCore.pyqtSignal()                  # F2/G5 verification run
    verify_result = QtCore.pyqtSignal(object)             # AutotuneVPResult (verify)
    encoder_maint_result = QtCore.pyqtSignal(bool, str)   # (ok, drive-response text)
    soft_zero_result = QtCore.pyqtSignal(bool, str, object)  # ok, message, telemetry
    axis_summary = QtCore.pyqtSignal(dict)                 # read-only Quick Axis snapshot
    axis_current_reference = QtCore.pyqtSignal(object)    # bounded current-reference snapshot
    axis_drive_mode = QtCore.pyqtSignal(object)            # bounded UM snapshot
    axis_digital_inputs = QtCore.pyqtSignal(object)        # bounded IP/IL/IF snapshot
    axis_digital_outputs = QtCore.pyqtSignal(object)       # bounded OP/OL/GO snapshot
    motion_result = QtCore.pyqtSignal(str, object)         # action, MotionResult
    motion_authority = QtCore.pyqtSignal(bool, str)        # session signature authority
    recorder_signals_result = QtCore.pyqtSignal(object, str)  # names, error
    recorder_status_changed = QtCore.pyqtSignal(str, str)     # state, detail
    recorder_manifest = QtCore.pyqtSignal(object)             # immutable capture evidence
    recorder_data = QtCore.pyqtSignal(object, object, object)  # data, resolved, token
    persistence_audit_status = QtCore.pyqtSignal(object)      # durable UNKNOWN/audit dict
    stopped = QtCore.pyqtSignal()

    def __init__(self, port: str, parent=None, *, query_only: bool = False):
        super().__init__(parent)
        self.port = port
        self.query_only = bool(query_only)
        self.access_mode = (
            self.OBSERVE_ONLY_ACCESS_MODE
            if self.query_only else self.SUPERVISED_ACCESS_MODE)
        self._run = True
        self._pending = collections.deque()   # one-shot commands from the GUI thread
        self._jobs = collections.deque()      # structured jobs (writes) from the GUI thread
        self._cancel_at = False               # operator-abort flag polled by the autotune
        self._tune_job_generation = 0         # STOP cannot be undone by a later start call
        self._tune_cancelled_through = 0
        self._motion_cancel = False           # polled inside finite PTP transaction
        self._motion_generation = 0           # STOP cannot be reordered behind a queued move
        self._motion_cancelled_through = 0
        self._motion_stop_requested = False
        self._urgent_jobs = collections.deque()  # STOP escape path, ahead of normal jobs
        self._motion_config_unknown = False
        self._energy_closeout_unknown = False
        self._motion_ownership_requested = False
        self._commutation_signature_green = False
        self._commutation_signature_token = None
        self._recorder_active = False
        self._recorder_ready = False
        self._recorder_resolved = None
        self._recorder_last_status = None
        self._recorder_manifest_current = None
        self._recorder_recovery_unknown = False
        self._recorder_generation = 0         # invalidates Start queued before Recorder Stop
        self._recorder_cancelled_through = 0
        self._recorder_stop_requested = False
        self._recorder_upload_consumed_after_cancel = False
        self._p1_gain_trial = None             # worker-side P1 SV/race interlock
        self._vp_gain_trial = None             # worker-side SV/race interlock
        self._persistence_recovery_unknown = False
        self._connection_identity_verified = False
        self._telemetry_sequence = 0
        # No write-capable job may run until this worker has observed one fresh,
        # finite PX from the newly-opened link.
        self._session_coordinate_known = False
        # Finite motion additionally requires one explicit, verified PX=0 in
        # this worker/connection. A merely readable PX is not a session origin.
        self._session_zero_confirmed = False
        # An ambiguous Encoder Maintenance command can change persistent datum
        # state without a response. Ordinary PX polling cannot adjudicate that;
        # only constructing a new worker after reconnect clears this latch.
        self._encoder_maintenance_reconnect_required = False

    def send_once(self, cmd: str):
        """Queue one read-only bare query in the worker thread.

        The old generic entrypoint admitted ordinary ``=`` assignments after a
        fresh PX sample.  There are no production callers that need that power;
        typed jobs own every mutation and its dedicated safety transaction.
        """
        text = str(cmd).strip()
        normalized = text.upper().replace(" ", "")
        if normalized not in self._READ_ONLY_QUERY_ALLOWLIST:
            raise ValueError(
                "send_once accepts only an explicitly allowlisted read-only query")
        self._pending.append(normalized)

    def audit_persistence_after_reset(self):
        """Queue the query-only audit after explicit GUI attestation."""
        self._jobs.append(("persistence_audit", None))

    def start_autotune(self, kw: dict):
        """Queue our own current-loop auto-tune (ENERGIZES the motor — caller gates)."""
        return self._queue_tuning_job("autotune", dict(kw))

    def cancel_autotune(self):
        """Request a safe abort mid-tune (polled in autotune's _sleep -> SPEC §6 chain)."""
        self._tune_cancelled_through = self._tune_job_generation
        self._cancel_at = True

    def apply_autotune_gains(self, result, persist: bool):
        """Deprecated compatibility entrypoint; worker guard rejects without I/O."""
        self._jobs.append(("autotune_apply", (result, bool(persist))))

    def begin_current_gain_trial(self, result):
        """Queue an unsaved, rollback-capable KP[1]/KI[1] RAM trial."""
        self._jobs.append(("p1_trial_begin", result))

    def restore_current_gain_trial(self, trial):
        """Queue restoration of the pre-trial P1 gains (never SV)."""
        self._jobs.append(("p1_trial_restore", trial))

    def commit_current_gain_trial(self, trial):
        """Queue P1 SV only after the complete RAM set still matches."""
        self._jobs.append(("p1_trial_commit", trial))

    def start_velpos_autotune(self, kw: dict):
        """Queue the Phase-2 vel/pos auto-tune (ROTATES the motor ~1 rev/run +
        low-speed jogs — the caller shows the rotation warning gate first)."""
        return self._queue_tuning_job("velpos", dict(kw))

    def cancel_velpos(self):
        """Request a safe Phase-2 abort (same operator flag; the module runs the
        segment-appropriate chain: TC=0->MO=0 or JV=0;ST->MO=0)."""
        self._tune_cancelled_through = self._tune_job_generation
        self._cancel_at = True

    def apply_velpos_gains(self, result, persist: bool):
        """Deprecated compatibility entrypoint; worker guard rejects without I/O."""
        self._jobs.append(("velpos_apply", (result, bool(persist))))

    def begin_velpos_gain_trial(self, result):
        """Queue an unsaved, rollback-capable KP[2]/KI[2]/KP[3] RAM trial."""
        self._jobs.append(("vp_trial_begin", result))

    def restore_velpos_gain_trial(self, trial):
        """Queue restoration of the pre-trial gain snapshot (never SV)."""
        self._jobs.append(("vp_trial_restore", trial))

    def commit_velpos_gain_trial(self, trial):
        """Queue SV only after the full trial readback still matches."""
        self._jobs.append(("vp_trial_commit", trial))

    def start_verify_vp(self, kw: dict, trial=None, signature_token=None):
        """Queue the F2/G5 gain-acceptance run (ROTATES the motor: JV steps
        300->900 rpm — the caller shows the rotation warning gate first)."""
        return self._queue_tuning_job(
            "verify_vp", (dict(kw), trial, signature_token))

    def _queue_tuning_job(self, kind, payload):
        """Bind one energizing job to a monotonic STOP/cancel generation."""
        self._tune_job_generation += 1
        token = self._tune_job_generation
        if self._motion_stop_requested:
            self._tune_cancelled_through = token
        self._jobs.append((str(kind), (token, payload)))
        return token

    def _tune_cancel_requested(self, tune_token=None):
        """Return the monotonic cancellation state for one tuning job.

        ``_cancel_at`` is a convenience flag that a later job may clear.  A
        generation already covered by STOP/cancel remains cancelled for its
        entire lifetime, including the telemetry-to-handler race window.
        """
        token_bound = isinstance(tune_token, int)
        generation_cancelled = (
            token_bound and tune_token <= self._tune_cancelled_through)
        return bool(
            not self._run
            or self._motion_stop_requested
            or (not token_bound and self._cancel_at)
            or generation_cancelled)

    def soft_zero(self):
        """Queue a session-only PX=0 with MO/standstill and readback gates."""
        self._jobs.append(("soft_zero", None))

    def encoder_maintenance(self, operations):
        """Queue structured encoder-maintenance operations for worker validation.

        Raw drive command strings deliberately do not cross this boundary.  The
        worker converts whitelisted operation IDs to TW[18]/TW[19]/TW[20].
        """
        if isinstance(operations, (list, tuple)):
            copied = [dict(op) if isinstance(op, dict) else op for op in operations]
        else:
            copied = operations
        self._jobs.append(("encoder_maint", copied))

    def refresh_axis_summary(self):
        """Queue a read-only Quick Axis summary."""
        self._jobs.append(("axis_read", None))

    def refresh_axis_drive_mode(self):
        """Queue one bounded UM read-only snapshot."""
        self._jobs.append(("axis_drive_mode_read", None))

    def refresh_axis_current_reference(self):
        """Queue one bounded current-reference read-only snapshot."""
        self._jobs.append(("axis_current_reference_read", None))

    def refresh_axis_digital_inputs(self):
        """Queue one bounded IP/IL[1..6]/IF[1..6] read-only snapshot."""
        self._jobs.append(("axis_digital_inputs_read", None))

    def refresh_axis_digital_outputs(self):
        """Queue one bounded OP/OL[1..4]/GO[1..4] read-only snapshot."""
        self._jobs.append(("axis_digital_outputs_read", None))

    def run_position_move(self, request):
        """Queue one finite PTP move; the kernel always auto-disables."""
        self._motion_generation += 1
        token = self._motion_generation
        if self._motion_stop_requested:
            self._motion_cancelled_through = token
        self._jobs.append(("motion_move", (token, request)))
        return token

    def request_motion_stop(self):
        """Request the guard-bypassing STOP escape path.

        The flag is visible to a running finite move immediately; the urgent job
        also executes ST/MO=0 when the worker is between jobs.
        """
        self._motion_cancel = True
        self._motion_stop_requested = True
        self._motion_cancelled_through = self._motion_generation
        self._tune_cancelled_through = self._tune_job_generation
        self._cancel_at = True
        self._urgent_jobs.append(("motion_stop", None))

    def discover_recorder_signals(self):
        self._jobs.append(("recorder_discover", None))

    def start_recorder(self, request):
        self._recorder_generation += 1
        token = self._recorder_generation
        if self._recorder_stop_requested:
            self._recorder_cancelled_through = token
        self._jobs.append(("recorder_start", (token, request)))
        return token

    def upload_recorder(self):
        # Bind Upload to the capture generation that produced READY_TO_UPLOAD.
        # Recorder Stop advances ``_recorder_cancelled_through`` for that same
        # generation, allowing a queued Upload to be discarded without
        # overwriting the later CANCELLED/UNKNOWN result.
        token = self._recorder_generation
        self._jobs.append(("recorder_upload", token))
        return token

    def request_recorder_stop(self):
        """Cancel only the Recorder.  This never substitutes for motion STOP."""
        self._recorder_cancelled_through = self._recorder_generation
        self._recorder_stop_requested = True
        self._urgent_jobs.append(("recorder_stop", None))

    def _invalidate_commutation_signature(self, reason):
        """Conservatively revoke session motion authority before config writes."""
        was_green = self._commutation_signature_green
        self._commutation_signature_green = False
        self._commutation_signature_token = None
        if was_green:
            self.motion_authority.emit(False, str(reason))

    def current_commutation_signature_token(self):
        """Return the opaque token for the exact current GREEN proof."""
        if not self._commutation_signature_green:
            return None
        token = self._commutation_signature_token
        return token if isinstance(token, str) and token else None

    def write_motor(self, writes: dict, ca18_basis=None):
        """Queue a Motor write with the exact RPM-conversion basis shown."""
        self._jobs.append(("motor_write", {
            "writes": dict(writes), "ca18_basis": ca18_basis}))

    def write_feedback(self, pairs):
        """Queue a Feedback/encoder write — ORDERED [(cmd, value)] (validated by caller)."""
        self._jobs.append(("feedback_write", pairs))

    def stop(self):
        self._cancel_at = True
        self._motion_cancel = True
        self._run = False
        # Once Disconnect is requested, queued ordinary work loses authority.
        # Active motion/trial cleanup is handled explicitly in ``finally``.
        self._pending.clear()
        self._jobs.clear()
        self._session_coordinate_known = False
        self._session_zero_confirmed = False

    @staticmethod
    def _is_finite_number(value):
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(float(value)))

    def _latch_coordinate_unknown(self, *, reconnect_required=False):
        """Close the coordinate gate; optionally require a new link/worker."""
        self._session_coordinate_known = False
        self._session_zero_confirmed = False
        if reconnect_required:
            self._encoder_maintenance_reconnect_required = True

    def _record_fresh_telemetry(self, telemetry):
        """Admit only one complete, timely, identity-bound telemetry sample."""
        fresh = dict(telemetry or {})
        received_now = time.monotonic()
        missing = [name for name in TELEMETRY_REQUIRED_FIELDS
                   if not self._is_finite_number(fresh.get(name))]
        mo = fresh.get("mo")
        if self._is_finite_number(mo) and float(mo) not in (0.0, 1.0):
            missing.append("mo-state")
        started = fresh.get("_sample_started_monotonic")
        finished = fresh.get("_sample_finished_monotonic")
        duration = fresh.get("_sample_duration_s")
        timing_values = (started, finished, duration)
        if not all(self._is_finite_number(value) for value in timing_values):
            missing.append("sample-timing")
        else:
            started_f = float(started)
            finished_f = float(finished)
            duration_f = float(duration)
            measured_f = finished_f - started_f
            source_age_f = received_now - finished_f
            if (finished_f < started_f
                    or duration_f < 0.0
                    or duration_f > TELEMETRY_MAX_SAMPLE_DURATION_S
                    or abs(measured_f - duration_f) > 0.05
                    or source_age_f < -0.25
                    or source_age_f > TELEMETRY_SOURCE_MAX_AGE_S):
                missing.append("sample-timing")
        valid = bool(
            self._connection_identity_verified
            and not missing
            and not self._encoder_maintenance_reconnect_required
            and not self._energy_closeout_unknown)
        if valid:
            self._session_coordinate_known = True
            self._telemetry_sequence += 1
            fresh["telemetry_sequence"] = self._telemetry_sequence
            fresh["telemetry_received_monotonic"] = received_now
        else:
            self._session_coordinate_known = False
        fresh["telemetry_valid"] = valid
        fresh["telemetry_error"] = (None if valid else
            ("identity-unverified" if not self._connection_identity_verified else
             "energy-closeout-unverified" if self._energy_closeout_unknown else
             "invalid fields: %s" % ", ".join(missing or ["unknown"])))
        fresh["session_coordinate_known"] = self._session_coordinate_known
        fresh["encoder_maintenance_reconnect_required"] = \
            self._encoder_maintenance_reconnect_required
        return fresh

    @staticmethod
    def _validated_persistence_status(raw):
        """Return a schema-checked status or raise without weakening locks."""
        if not isinstance(raw, dict):
            raise TypeError("persistence status must be a dict")
        required = (
            "status", "lock_active", "detail", "record_id", "phase",
            "other_active_count", "ledger_error",
        )
        missing = [key for key in required if key not in raw]
        if missing:
            raise ValueError(
                "persistence status missing: %s" % ", ".join(missing))
        status = dict(raw)
        if not isinstance(status["status"], str) or not status["status"].strip():
            raise ValueError("persistence status name is invalid")
        if not isinstance(status["detail"], str):
            raise ValueError("persistence detail is invalid")
        if not isinstance(status["lock_active"], bool):
            raise ValueError("persistence lock_active must be bool")
        if (not isinstance(status["other_active_count"], int)
                or isinstance(status["other_active_count"], bool)
                or status["other_active_count"] < 0):
            raise ValueError("persistence other_active_count is invalid")
        if status["record_id"] is not None and not isinstance(
                status["record_id"], str):
            raise ValueError("persistence record_id is invalid")
        if status["phase"] not in (
                None, "P1", "P2", "P1_CONFIG", "P2_LIMITS", "MOTOR"):
            raise ValueError("persistence phase is invalid")
        if status["ledger_error"] is not None and not isinstance(
                status["ledger_error"], str):
            raise ValueError("persistence ledger_error is invalid")
        if "resolved" in status and not isinstance(status["resolved"], bool):
            raise ValueError("persistence resolved must be bool")
        return status

    @staticmethod
    def _locked_persistence_status(exc):
        return {
            "status": "LEDGER_STATUS_FAILED",
            "resolved": False,
            "detail": str(exc),
            "lock_active": True,
            "record_id": None,
            "phase": None,
            "other_active_count": 0,
            "ledger_error": type(exc).__name__,
        }

    def _active_trial_phase(self):
        if self._p1_gain_trial is not None and self._vp_gain_trial is not None:
            return "CONFLICT"
        if self._p1_gain_trial is not None:
            return "P1"
        if self._vp_gain_trial is not None:
            return "P2"
        return None

    @staticmethod
    def _verify_payload_trial(payload):
        if isinstance(payload, tuple) and len(payload) >= 2:
            return payload[1]
        return None

    @staticmethod
    def _verify_payload_signature_token(payload):
        if isinstance(payload, tuple) and len(payload) >= 3:
            return payload[2]
        return None

    def _verify_signature_is_current(self, payload):
        supplied = self._verify_payload_signature_token(payload)
        current = self.current_commutation_signature_token()
        return bool(current is not None and supplied == current)

    def _trial_job_guard(self, kind, payload):
        """Worker-owned phase/state allowlist and exact trial identity gate."""
        if self.query_only:
            if kind in self._OBSERVE_ONLY_JOB_ALLOWLIST:
                return True, ""
            return False, (
                "observe-only connection permits Axis/persistence reads and "
                "software shutdown only")
        persistence_allowlist = frozenset((
            "axis_read", "axis_drive_mode_read", "axis_current_reference_read",
            "axis_digital_inputs_read",
            "axis_digital_outputs_read", "persistence_audit",
            "motion_stop", "recorder_stop"))
        if self._persistence_recovery_unknown:
            if kind in persistence_allowlist:
                return True, ""
            return False, (
                "Persistence UNKNOWN durable lock — only read-only audit/Axis "
                "read and software STOP/Recorder Stop are allowed")
        if self._energy_closeout_unknown:
            if kind in (
                    "axis_read", "axis_drive_mode_read",
                    "axis_current_reference_read",
                    "axis_digital_inputs_read",
                    "axis_digital_outputs_read", "motion_stop",
                    "recorder_stop"):
                return True, ""
            return False, (
                "Energy closeout UNKNOWN — only read-only Axis Summary and "
                "software STOP/Recorder Stop are allowed")
        # Read-only discovery and the STOP escape path must not be trapped
        # behind coordinate, encoder, gain-trial, or persistence uncertainty.
        if kind in (
                "axis_read", "axis_drive_mode_read",
                "axis_current_reference_read",
                "axis_digital_inputs_read",
                "axis_digital_outputs_read", "motion_stop", "recorder_stop",
                "recorder_upload"):
            return True, ""
        if self._recorder_active:
            return False, (
                "Recorder capture/upload is pending; finish or Cancel Recorder first")
        if kind in ("autotune_apply", "velpos_apply"):
            return False, ("Legacy direct gain apply 지원 종료 — "
                           "begin→verify/restore→commit transaction을 사용하세요.")
        if (self._motion_config_unknown
                and kind not in ("p1_trial_restore", "vp_trial_restore")):
            return False, ("Motion 임시 설정 복원 상태 UNKNOWN — Axis Summary로 실제 "
                           "SP/AC/DC/SF/PL/CL을 audit하기 전까지 작업을 차단합니다.")
        if self._encoder_maintenance_reconnect_required:
            return False, ("Encoder Maintenance 결과 UNKNOWN — reconnect 후 fresh PX와 "
                           "encoder 상태를 audit하기 전까지 모든 작업을 차단합니다.")
        if not self._session_coordinate_known:
            return False, ("세션 좌표 UNKNOWN — fresh PX readback이 성공하기 전까지 "
                           "새 작업을 실행하지 않습니다.")
        if (kind == "velpos"
                and not (isinstance(payload, dict)
                         and payload.get("signature_only") is True)
                and not self._commutation_signature_green):
            return False, (
                "Phase 2 locked: Commutation Signature GREEN is required "
                "for this connection")
        if (kind == "velpos"
                and not (isinstance(payload, dict)
                         and payload.get("signature_only") is True)):
            p1_model_valid = bool(
                isinstance(payload, dict)
                and all(
                    self._is_finite_number(payload.get(name))
                    and float(payload[name]) > 0.0
                    for name in ("r_pp_ohm", "l_pp_h")))
            if not p1_model_valid:
                return False, (
                    "Phase 2 locked: current-generation Phase 1 R/L model "
                    "is required")
        if kind == "motion_move" and not self._session_zero_confirmed:
            return False, (
                "Finite Motion locked: verified Session Zero (PX=0) is required "
                "for this connection")
        phase = self._active_trial_phase()
        if phase == "CONFLICT":
            return False, ("워커 RAM 시험 상태 충돌(P1/P2 동시 활성) — 어떤 쓰기나 "
                           "검증도 실행하지 않습니다.")

        if phase is not None:
            active_trial = (self._p1_gain_trial if phase == "P1"
                            else self._vp_gain_trial)
            persistence_state = getattr(
                active_trial, "persistence_state", "RAM_TRIAL")
            restore_kind = ("p1_trial_restore" if phase == "P1"
                            else "vp_trial_restore")
            if (persistence_state == "RESTORE_FAILED"
                    or (phase == "P1" and
                        persistence_state == "AUTHORITY_INVALID")):
                allowed_kinds = frozenset((restore_kind,))
            elif persistence_state == "RAM_TRIAL":
                allowed_kinds = self._TRIAL_JOB_ALLOWLIST[phase]
                if getattr(active_trial, "restore_only", False):
                    allowed_kinds = frozenset((restore_kind,))
            else:
                return False, ("%s 시험 상태가 활성 RAM_TRIAL이 아닙니다(%s)." %
                               (phase, persistence_state))
            if kind not in allowed_kinds:
                return False, ("미저장 %s RAM 게인 시험 보호: 이 단계에서는 %s 작업을 "
                               "실행할 수 없습니다." % (phase, kind))
            if phase == "P1" and payload is not self._p1_gain_trial:
                return False, "P1 RAM 시험 객체 불일치 — 현재 시험만 복원/저장할 수 있습니다."
            if (phase == "P1" and kind == "p1_trial_commit"
                    and not autotune_current.p1_gain_trial_has_save_authority(
                        active_trial)):
                return False, (
                    "P1 Save locked: session-bound on-motor verification "
                    "capability is unavailable while E4 remains RED")
            if phase == "P2":
                supplied = (self._verify_payload_trial(payload)
                            if kind == "verify_vp" else payload)
                if supplied is not self._vp_gain_trial:
                    return False, ("P2 RAM 시험 객체 불일치 — 현재 적용된 정확한 시험만 "
                                   "검증/복원/저장할 수 있습니다.")
                if (kind == "verify_vp"
                        and not self._verify_signature_is_current(payload)):
                    return False, (
                        "Phase 2 verification locked: Commutation Signature "
                        "GREEN is required for this connection")
            return True, ""

        if kind in ("p1_trial_commit", "vp_trial_commit"):
            return False, "활성 RAM 게인 시험이 없어 복원/저장을 거부했습니다."
        if kind in ("p1_trial_restore", "vp_trial_restore"):
            # A new worker may adopt a retained trial for restore only.  The
            # adoption API owns same-device identity and full readback gates.
            return True, ""
        if kind == "verify_vp" and self._verify_payload_trial(payload) is not None:
            return False, "종료된 P2 RAM 시험 객체의 검증 요청을 거부했습니다."
        if kind == "verify_vp" and not self._verify_signature_is_current(payload):
            return False, (
                "Phase 2 verification locked: Commutation Signature GREEN "
                "is required for this connection")
        return True, ""

    def _emit_guard_rejection(self, kind, payload, message):
        """Return a typed failure signal so the GUI can release its in-flight lock."""
        if kind in ("motor_write", "feedback_write"):
            self.write_result.emit(False, message)
        elif kind == "autotune_apply":
            self.autotune_applied.emit(False, message)
        elif kind == "velpos_apply":
            self.velpos_applied.emit(False, message)
        elif kind == "encoder_maint":
            self.encoder_maint_result.emit(False, message)
        elif kind == "soft_zero":
            self.soft_zero_result.emit(False, message, None)
        elif kind == "motion_move":
            self.motion_result.emit(
                "move", single_axis_motion.MotionResult(
                    single_axis_motion.RED, message))
        elif kind == "axis_read":
            self.axis_summary.emit({"errors": {"worker": message}})
        elif kind == "recorder_discover":
            self.recorder_signals_result.emit(None, message)
        elif kind.startswith("recorder_"):
            self.recorder_status_changed.emit("ERROR", message)
        elif kind == "autotune":
            self.autotune_result.emit(autotune_current.AutotuneResult(
                status=autotune_current.RED, reason=message))
        elif kind == "velpos":
            self.velpos_result.emit(autotune_velpos.AutotuneVPResult(
                status=autotune_velpos.RED, reason=message))
        elif kind == "verify_vp":
            self.verify_result.emit(autotune_velpos.AutotuneVPResult(
                status=autotune_velpos.RED, reason=message))
        elif kind.startswith("p1_trial_"):
            action = kind.removeprefix("p1_trial_")
            current = self._p1_gain_trial if action != "begin" else None
            self.current_gain_action.emit(action, False, message, current)
        elif kind.startswith("vp_trial_"):
            action = kind.removeprefix("vp_trial_")
            current = self._vp_gain_trial if action != "begin" else None
            self.velpos_gain_action.emit(action, False, message, current)
        else:
            self.command_done.emit(str(kind), "ERR: %s" % message)

    @classmethod
    def _normalise_encoder_operations(cls, operations):
        """Validate operation IDs/arguments and return ``[(id, command, value)]``.

        Validation completes before the first command is issued.  This rejects
        raw strings, separators, ``SV``, unknown IDs, duplicate NVM actions, and
        sockets other than the configured feedback socket 1.
        """
        if not isinstance(operations, (list, tuple)) or not operations:
            raise ValueError("엔코더 정비 작업이 비어 있습니다.")
        if len(operations) > len(cls._ENCODER_OPERATION_IDS):
            raise ValueError("엔코더 정비 작업 수가 허용 범위를 초과했습니다.")
        normalised, seen = [], set()
        for op in operations:
            if not isinstance(op, dict):
                raise ValueError("원시 명령 문자열은 허용되지 않습니다(구조화 operation ID 필요).")
            op_id = op.get("id")
            if op_id not in cls._ENCODER_OPERATION_IDS:
                raise ValueError("허용되지 않은 엔코더 정비 operation ID: %r" % op_id)
            if op_id in seen:
                raise ValueError("중복 엔코더 정비 operation ID: %s" % op_id)
            seen.add(op_id)
            if op_id == "set_datum_shift":
                if set(op) != {"id", "value"}:
                    raise ValueError("set_datum_shift에는 id/value만 허용됩니다.")
                value = op["value"]
                if isinstance(value, bool):
                    raise ValueError("Datum 값은 정수여야 합니다.")
                if isinstance(value, str):
                    token = value.strip()
                    digits = token[1:] if token[:1] in ("+", "-") else token
                    if not digits.isdecimal():
                        raise ValueError("Datum 값은 구분자 없는 정수여야 합니다.")
                    value = int(token, 10)
                elif isinstance(value, int):
                    value = int(value)
                else:
                    raise ValueError("Datum 값은 정수여야 합니다.")
                if not -(2 ** 31) <= value <= (2 ** 31 - 1):
                    raise ValueError("Datum 값이 32-bit 범위를 벗어났습니다.")
                normalised.append((op_id, "TW[18]=%d" % value, value))
            else:
                if set(op) != {"id", "socket"}:
                    raise ValueError("%s에는 id/socket만 허용됩니다." % op_id)
                socket = op["socket"]
                if isinstance(socket, bool) or not isinstance(socket, int) or socket != 1:
                    raise ValueError("엔코더 정비는 피드백 소켓 1만 허용됩니다.")
                tw_index = 19 if op_id == "reset_multiturn" else 20
                normalised.append((op_id, "TW[%d]=1" % tw_index, socket))
        return normalised

    @classmethod
    def encoder_operation_commands(cls, operations):
        """Return the exact whitelisted commands for a confirmation preview."""
        return [command for _op_id, command, _value
                in cls._normalise_encoder_operations(operations)]

    @staticmethod
    def _require_non_motion_write_ready(link):
        """Return fresh telemetry only when a non-motion coordinate/config write is safe."""
        t = link.read_telemetry()
        mo, vel, iq = t.get("mo"), t.get("vel"), t.get("iq")
        if mo != 0:
            raise RuntimeError("모터 OFF 필요(MO=%r)" % mo)
        if not DriveWorker._is_finite_number(vel) or abs(float(vel)) > 1.0:
            raise RuntimeError("정지 확인 실패(VX=%r cnt/s)" % vel)
        if not DriveWorker._is_finite_number(iq) or abs(float(iq)) > 0.10:
            raise RuntimeError("무전류 확인 실패(IQ=%r A)" % iq)
        return t

    @classmethod
    def _perform_soft_zero(cls, link):
        """Execute guarded PX=0; restore or explicitly mark ambiguous state UNKNOWN."""
        before = cls._require_non_motion_write_ready(link)
        before_pos = before.get("pos")
        if not cls._is_finite_number(before_pos):
            raise RuntimeError("PX 쓰기 전 위치 되읽기 실패(PX=%r)" % before_pos)
        before_pos = float(before_pos)
        if abs(before_pos - round(before_pos)) > 1e-6:
            raise RuntimeError("PX 쓰기 전 위치가 정수 count가 아닙니다(PX=%r)" % before_pos)

        write_error = None
        try:
            link.command("PX=0")
        except Exception as exc:
            # A transport error does not prove the drive rejected the command.
            write_error = exc
        try:
            after = cls._require_non_motion_write_ready(link)
        except Exception as exc:
            raise SessionCoordinateError(
                "PX=0 쓰기 시도 후 fresh readback 실패(%s) — 세션 좌표 UNKNOWN; "
                "추가 좌표 쓰기를 금지하고 새 PX 읽기를 기다립니다." % exc,
                coordinate_unknown=True) from exc
        pos = after.get("pos")
        if not cls._is_finite_number(pos):
            raise SessionCoordinateError(
                "PX=0 쓰기 후 PX 되읽기 무효(PX=%r) — 세션 좌표 UNKNOWN" % pos,
                coordinate_unknown=True, telemetry=after)
        if abs(float(pos)) <= 1.0:
            suffix = ("; 명령 응답 오류가 있었으나 fresh PX=0으로 적용 확인"
                      if write_error is not None else "")
            msg = "세션 원점 적용·되읽기 완료: PX %s → %s (SV 미실행%s)" % (
                before.get("pos"), pos, suffix)
            return msg, after

        # Fresh telemetry proves it is safe to restore the captured coordinate.
        # If the write clearly left PX unchanged, avoid an unnecessary second write.
        if abs(float(pos) - before_pos) <= 1.0:
            detail = "명령 응답 오류: %s; " % write_error if write_error else ""
            raise RuntimeError("PX=0 적용 실패(%sPX=%r), 원래 좌표 유지 확인" %
                               (detail, pos))
        try:
            cls._require_non_motion_write_ready(link)
        except Exception as exc:
            raise SessionCoordinateError(
                "PX=0 되읽기 불일치(PX=%r), 원래 PX=%d 복원 전 안전 확인 실패(%s) — "
                "세션 좌표 UNKNOWN" % (pos, int(round(before_pos)), exc),
                coordinate_unknown=True) from exc

        restore_write_error = None
        try:
            link.command("PX=%d" % int(round(before_pos)))
        except Exception as exc:
            # The drive may have accepted the restore before its reply was lost.
            # Always adjudicate that outcome with an independent fresh readback.
            restore_write_error = exc
        try:
            restored = cls._require_non_motion_write_ready(link)
        except Exception as exc:
            detail = ("; 복원 명령 응답 오류=%s" % restore_write_error
                      if restore_write_error is not None else "")
            raise SessionCoordinateError(
                "PX=0 되읽기 불일치(PX=%r), 원래 PX=%d 복원 되읽기 실패(%s%s) — "
                "세션 좌표 UNKNOWN" %
                (pos, int(round(before_pos)), exc, detail),
                coordinate_unknown=True) from exc
        restored_pos = restored.get("pos")
        if (not cls._is_finite_number(restored_pos)
                or abs(float(restored_pos) - before_pos) > 1.0):
            detail = ("; 복원 명령 응답 오류=%s" % restore_write_error
                      if restore_write_error is not None else "")
            raise SessionCoordinateError(
                "PX=0 되읽기 불일치(PX=%r), 원래 PX=%d 복원 되읽기 불일치"
                "(PX=%r%s) — 세션 좌표 UNKNOWN" %
                (pos, int(round(before_pos)), restored_pos, detail),
                coordinate_unknown=True, telemetry=restored)
        suffix = ("; 복원 명령 응답은 유실됐으나 fresh PX로 복원 확인"
                  if restore_write_error is not None else "")
        raise RuntimeError(
            "PX=0 되읽기 불일치(PX=%r); 원래 PX=%d 복원·되읽기 완료%s" %
            (pos, int(round(before_pos)), suffix))

    @classmethod
    def _perform_encoder_maintenance(cls, link, operations):
        """Execute a prevalidated, fail-fast encoder operation transaction."""
        normalised = cls._normalise_encoder_operations(operations)
        before = cls._require_non_motion_write_ready(link)
        parts = []
        for op_id, command, _value in normalised:
            try:
                response = link.command(command)
            except Exception as exc:
                raise SessionCoordinateError(
                    "%s 실패(%s) — 이후 작업은 실행하지 않음; encoder/PX 상태 UNKNOWN" %
                    (command, exc), coordinate_unknown=True) from exc
            parts.append("%s  →  %s" % (
                command, response if str(response).strip() else "OK"))

        try:
            after = cls._require_non_motion_write_ready(link)
        except Exception as exc:
            raise SessionCoordinateError(
                "엔코더 정비 후 final PX readback 실패(%s) — encoder/PX 상태 UNKNOWN" % exc,
                coordinate_unknown=True) from exc
        pos = after.get("pos")
        if not cls._is_finite_number(pos):
            raise SessionCoordinateError(
                "엔코더 정비 후 final PX가 유효하지 않습니다(PX=%r) — 상태 UNKNOWN" % pos,
                coordinate_unknown=True, telemetry=after)

        op_ids = [item[0] for item in normalised]
        if "reset_errors" in op_ids and len(op_ids) == 1:
            before_pos = before.get("pos")
            if (cls._is_finite_number(before_pos)
                    and abs(float(pos) - float(before_pos)) > 1.0):
                raise SessionCoordinateError(
                    "Reset Errors 후 PX 변경 감지: %r → %r — "
                    "encoder/PX 상태 UNKNOWN" % (before_pos, pos),
                    coordinate_unknown=True, telemetry=after)
        if "set_datum_shift" in op_ids and "reset_multiturn" in op_ids:
            datum = next(item[2] for item in normalised
                         if item[0] == "set_datum_shift")
            if abs(float(pos) - float(datum)) > 1.0:
                raise SessionCoordinateError(
                    "영구 원점 작업 후 final PX 불일치: expected %d, read %r — "
                    "encoder/PX 상태 UNKNOWN" % (datum, pos),
                    coordinate_unknown=True, telemetry=after)
        parts.append("Final PX  →  %s (fresh readback)" % pos)
        parts.append("SV  →  미실행(Encoder Maintenance 자체 영구 동작)")
        return "\n".join(parts), after

    def _prepare_retained_trial_restore(self, link, phase, trial):
        """Adopt a retained same-device trial for one restore path only.

        Commit and verify never call this helper.  The domain adoption API
        requires stable transaction identity plus MO=0/full-gain readback and
        clears all previous verification authority.
        """
        attr = "_p1_gain_trial" if phase == "P1" else "_vp_gain_trial"
        current = getattr(self, attr)
        if current is not None:
            if current is not trial:
                return False, "%s RAM 시험 객체 불일치" % phase, False
            return True, "", False
        adopt = (autotune_current.adopt_gain_trial_p1_for_restore
                 if phase == "P1"
                 else autotune_velpos.adopt_gain_trial_vp_for_restore)
        try:
            ok, message = adopt(link, trial)
        except Exception as exc:
            return False, "%s restore-only adoption 예외: %r" % (phase, exc), False
        if not ok:
            return False, message, False
        state = getattr(trial, "persistence_state", None)
        if state == "RESTORED":
            return True, message, True
        if (state not in ("RAM_TRIAL", "RESTORE_FAILED")
                or not getattr(trial, "restore_only", False)):
            return False, ("%s adoption 사후조건 불일치(state=%r, restore_only=%r)" %
                           (phase, state, getattr(trial, "restore_only", None))), False
        setattr(self, attr, trial)
        return True, message, False

    def _emit_axis_summary(self, link):
        try:
            summary = single_axis_motion.read_axis_summary(link)
        except Exception as exc:
            summary = {"errors": {"worker": str(exc)}, "write_supported": False}
        summary["motion_config_unknown"] = bool(self._motion_config_unknown)
        summary["energy_closeout_unknown"] = bool(
            self._energy_closeout_unknown)
        summary["commutation_signature_green"] = bool(
            self._commutation_signature_green)
        self.axis_summary.emit(summary)

    def _emit_axis_digital_inputs(self, link):
        snapshot = single_axis_digital_inputs.read_digital_input_snapshot(link)
        self.axis_digital_inputs.emit(snapshot)

    def _emit_axis_drive_mode(self, link):
        snapshot = single_axis_drive_mode.read_drive_mode_snapshot(link)
        self.axis_drive_mode.emit(snapshot)

    def _emit_axis_current_reference(self, link):
        snapshot = (
            single_axis_current_reference.read_current_reference_snapshot(link))
        self.axis_current_reference.emit(snapshot)

    def _emit_axis_digital_outputs(self, link):
        snapshot = single_axis_digital_outputs.read_digital_output_snapshot(link)
        self.axis_digital_outputs.emit(snapshot)

    def _run_motion_stop(self, link, action="stop"):
        try:
            result = single_axis_motion.safe_stop_disable(
                link,
                sleep_fn=lambda seconds: self.msleep(
                    int(max(float(seconds), 0.0) * 1000)),
            )
        except Exception as exc:
            # Cleanup must remain terminal even if the safety helper itself
            # fails unexpectedly; never skip trial restore/vendor Disconnect.
            result = single_axis_motion.MotionResult(
                single_axis_motion.UNKNOWN,
                "STOP/disable helper raised; final energy state is UNKNOWN",
                final_state={"disabled_verified": False},
                evidence={"worker_exception": repr(exc)},
            )
        if result.final_state.get("disabled_verified") is True:
            self._motion_ownership_requested = False
            self._motion_cancel = False
            self._motion_stop_requested = False
            self._energy_closeout_unknown = False
        else:
            self._energy_closeout_unknown = True
            self._session_coordinate_known = False
        self.motion_result.emit(action, result)
        return result

    def _claim_drive_energy(self, command):
        """Latch cleanup ownership before an energizing command is attempted."""
        self._motion_ownership_requested = True
        self._session_coordinate_known = False

    @staticmethod
    def _mark_workflow_red(result, detail):
        if result is None:
            return result
        result.status = "RED"
        prior = str(getattr(result, "reason", "") or "").strip()
        result.reason = "%s; %s" % (prior, detail) if prior else str(detail)
        return result

    def _latch_configuration_unknown(self, link, result, workflow):
        evidence = getattr(result, "evidence", None) or {}
        if evidence.get("configuration_state") != "UNKNOWN":
            return False
        self._motion_config_unknown = True
        self._invalidate_commutation_signature(
            "Commutation Signature revoked: %s configuration restore UNKNOWN"
            % workflow)
        self._mark_workflow_red(
            result, "%s temporary configuration restore is UNKNOWN" % workflow)
        self._publish_persistence_status(link)
        self._emit_axis_summary(link)
        return True

    def _finish_energizing_workflow(self, link, result, workflow):
        """Own verified torque removal and publish a new post-run sample.

        Tuning modules have their own abort chains, but an unexpected wrapper
        exception must not bypass a common worker-owned ST/MO=0 readback gate.
        """
        closeout = None
        closeout_error = None
        if self._motion_ownership_requested:
            try:
                closeout = self._run_motion_stop(
                    link, action="%s_closeout" % workflow)
                if closeout.final_state.get("disabled_verified") is not True:
                    closeout_error = (
                        "%s closeout could not verify MO=0/SO=0" % workflow)
            except Exception as exc:
                closeout_error = "%s closeout exception: %s" % (workflow, exc)
        if closeout_error:
            self._mark_workflow_red(result, closeout_error)

        telemetry_error = None
        try:
            fresh = self._record_fresh_telemetry(link.read_telemetry())
            if not fresh.get("telemetry_valid"):
                raise RuntimeError(fresh.get("telemetry_error") or "invalid sample")
            self.telemetry.emit(fresh)
        except Exception as exc:
            self._session_coordinate_known = False
            telemetry_error = "%s post-run telemetry unavailable: %s" % (
                workflow, exc)
            invalid = {name: None for name in TELEMETRY_REQUIRED_FIELDS}
            invalid.update({
                "telemetry_valid": False,
                "telemetry_error": telemetry_error,
                "session_coordinate_known": False,
                "encoder_maintenance_reconnect_required":
                    self._encoder_maintenance_reconnect_required,
            })
            self.telemetry.emit(invalid)
            self._mark_workflow_red(result, telemetry_error)

        if result is not None:
            evidence = dict(getattr(result, "evidence", None) or {})
            evidence["worker_safe_closeout"] = {
                "workflow": workflow,
                "energy_was_claimed": closeout is not None,
                "disabled_verified": (
                    closeout.final_state.get("disabled_verified")
                    if closeout is not None else None),
                "closeout_error": closeout_error,
                "post_telemetry_error": telemetry_error,
            }
            result.evidence = evidence
        return result

    def _run_recorder_stop(self, link, detail="operator requested Recorder cancel"):
        try:
            stopped = bool(link.record_stop())
            consumed = bool(self._recorder_upload_consumed_after_cancel)
            state = "CANCELLED" if (stopped or consumed) else "IDLE"
            if consumed:
                message = (
                    "Recorder Stop arrived while UploadRecordingData was in progress; "
                    "the consumed host data was discarded")
            else:
                message = detail if stopped else "Recorder had no pending capture"
        except Exception as exc:
            # StopRecorder failure does not prove that the recorder stopped.
            # Keep the interlock and recovery button alive until a later retry
            # succeeds or a new link/session is constructed.
            self._recorder_active = True
            self._recorder_last_status = "CANCEL_FAILED_UNKNOWN"
            self.recorder_status_changed.emit(
                "CANCEL_FAILED_UNKNOWN",
                "Recorder cancel failed; ownership remains locked: %s" % exc)
            return
        self._recorder_active = False
        self._recorder_ready = False
        self._recorder_recovery_unknown = False
        self._recorder_stop_requested = False
        self._recorder_upload_consumed_after_cancel = False
        self._recorder_resolved = None
        self._recorder_manifest_current = None
        self._recorder_last_status = state
        self.recorder_status_changed.emit(state, message)

    @staticmethod
    def _require_disabled_stationary_recorder_io(link):
        """Gate potentially long vendor discovery/upload calls.

        These calls share the single communication worker with software STOP.
        They are therefore admitted only after fresh MO=0, SO=0 and VX=0
        readbacks.  This is not an independent STO claim.
        """
        values = {}
        for command in ("MO", "SO", "VX"):
            try:
                raw = link.command(command, timeout_ms=300)
            except TypeError:  # deterministic test doubles / older adapters
                raw = link.command(command)
            try:
                number = float(str(raw).strip().rstrip(";"))
            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeError(
                    "Recorder blocking-I/O gate: unreadable %s" % command) from exc
            if not math.isfinite(number):
                raise RuntimeError(
                    "Recorder blocking-I/O gate: non-finite %s" % command)
            values[command] = number
        if values["MO"] != 0.0 or values["SO"] != 0.0 or values["VX"] != 0.0:
            raise RuntimeError(
                "Recorder discovery/upload requires fresh MO=0, SO=0, VX=0; "
                "observed MO=%s SO=%s VX=%s" %
                (values["MO"], values["SO"], values["VX"]))
        return values

    @staticmethod
    def _source_sha256(filename):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        try:
            with open(path, "rb") as handle:
                return hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            return None

    def _build_recorder_manifest(self, link, resolved):
        personality = {}
        library = {}
        try:
            personality = dict(link.recorder_personality_provenance() or {})
        except Exception:
            pass
        try:
            library = dict(link.recorder_library_provenance() or {})
        except Exception:
            pass
        return {
            "capture_id": str(uuid.uuid4()),
            "capture_start_attempt_utc": datetime.now(timezone.utc).isoformat(),
            "target": self.port,
            "requested_resolution_us": resolved.requested_resolution_us,
            "actual_resolution_us": resolved.actual_resolution_us,
            "requested_record_time_s": resolved.requested_record_time_s,
            "actual_record_time_s": resolved.actual_record_time_s,
            "length_per_signal": resolved.length_per_signal,
            "total_buffer_samples": resolved.total_buffer_samples,
            "signals": list(resolved.signals),
            "trigger": resolved.trigger,
            "dt_source": "TimeResolution × configured/read-back TS (vendor example semantics)",
            "personality": personality,
            "drive_dotnet_library": library,
            "app_source_sha256": {
                "main.py": self._source_sha256("main.py"),
                "elmo_link.py": self._source_sha256("elmo_link.py"),
                "recorder_control.py": self._source_sha256("recorder_control.py"),
                "recorder_view.py": self._source_sha256("recorder_view.py"),
            },
        }

    def _run_recorder_discover(self, link):
        try:
            self._require_disabled_stationary_recorder_io(link)
            names = link.recorder_signals()
            if not names:
                reason = getattr(link, "_last_recorder_error", None) or \
                    "personality returned no recorder signals"
                raise RuntimeError(reason)
            self.recorder_signals_result.emit(list(names), "")
        except Exception as exc:
            self.recorder_signals_result.emit(None, str(exc))

    def _run_recorder_start(self, link, payload):
        if (isinstance(payload, tuple) and len(payload) == 2
                and isinstance(payload[0], int)):
            token, request = payload
        else:  # compatibility for direct offline probes
            token, request = self._recorder_generation + 1, payload
            self._recorder_generation = token
        if token <= self._recorder_cancelled_through:
            self.recorder_status_changed.emit(
                "CANCELLED", "Recorder Start was superseded before drive I/O")
            return
        if self._recorder_active:
            self.recorder_status_changed.emit(
                "ERROR", "Recorder already has a pending capture")
            return
        try:
            ts_us = float(str(link.command("TS")).strip().rstrip(";"))
            resolved = recorder_control.resolve_request(request, ts_us=ts_us)
        except Exception as exc:
            self.recorder_status_changed.emit("ERROR", str(exc))
            return
        if token <= self._recorder_cancelled_through:
            self.recorder_status_changed.emit(
                "CANCELLED", "Recorder Start was superseded before StartRecording")
            return
        manifest = self._build_recorder_manifest(link, resolved)
        manifest["worker_generation"] = token
        self._recorder_manifest_current = manifest
        try:
            link.record_start(
                resolved.signals,
                resolved.length_per_signal,
                resolved.time_resolution,
                sampling_time_us=ts_us)
        except Exception as exc:
            # Once the vendor Start call is crossed, a timeout/exception can
            # have occurred after its side effect.  Keep ownership fail-closed
            # even if a test double cannot expose its provisional handle.
            self._recorder_active = True
            self._recorder_ready = False
            self._recorder_resolved = resolved
            self._recorder_last_status = "START_OWNERSHIP_UNKNOWN"
            manifest["start_outcome"] = "UNKNOWN"
            self.recorder_manifest.emit(dict(manifest))
            self.recorder_status_changed.emit(
                "START_OWNERSHIP_UNKNOWN",
                "StartRecording outcome is UNKNOWN; only Recorder Stop/recovery is allowed: %s"
                % exc)
            return
        self._recorder_active = True
        self._recorder_ready = False
        self._recorder_resolved = resolved
        self._recorder_last_status = "RECORDING"
        manifest["start_outcome"] = "STARTED"
        self.recorder_manifest.emit(dict(manifest))
        if token <= self._recorder_cancelled_through:
            self._run_recorder_stop(
                link, "Recorder Stop raced with StartRecording; capture cancelled")
            return
        self.recorder_status_changed.emit(
            "RECORDING",
            "Immediate capture armed: %d signals × %d samples, actual %.6g µs"
            % (len(resolved.signals), resolved.length_per_signal,
               resolved.actual_resolution_us))

    def _poll_recorder(self, link):
        if not self._recorder_active:
            return
        if self._recorder_recovery_unknown:
            return
        try:
            status = str(link.record_status())
        except Exception as exc:
            # One failed query cannot release ownership while ElmoLink retains
            # its pending recorder handle.
            self._recorder_ready = False
            self._recorder_last_status = "STALE_CONNECTION_UNKNOWN"
            self.recorder_status_changed.emit(
                "STALE_CONNECTION_UNKNOWN",
                "Status read failed; Recorder ownership remains locked: %s" % exc)
            return
        if status == "OFF":
            try:
                link.record_stop()
            except Exception as exc:
                self._recorder_ready = False
                self._recorder_last_status = "CANCEL_FAILED_UNKNOWN"
                self.recorder_status_changed.emit(
                    "CANCEL_FAILED_UNKNOWN",
                    "Recorder reported ROff and cleanup failed: %s" % exc)
                return
            self._recorder_active = False
            self._recorder_ready = False
            self._recorder_stop_requested = False
            self._recorder_resolved = None
            self._recorder_manifest_current = None
            self._recorder_last_status = "OFF_CAUSE_UNKNOWN"
            self.recorder_status_changed.emit(
                "OFF_CAUSE_UNKNOWN",
                "Recorder reached ROff; error versus cancel cause is not distinguishable")
            return
        self._recorder_ready = status == "READY_TO_UPLOAD"
        if status != self._recorder_last_status:
            self._recorder_last_status = status
            detail = (
                "Capture complete; Upload is now available"
                if self._recorder_ready else status.replace("_", " ").title())
            self.recorder_status_changed.emit(status, detail)

    def _run_recorder_upload(self, link, payload=None):
        token = (payload if isinstance(payload, int)
                 and not isinstance(payload, bool) else None)
        if (token is not None and token > 0
                and token <= self._recorder_cancelled_through):
            return  # Recorder Stop owns the terminal status for this generation.
        if not self._recorder_active or not self._recorder_ready:
            self.recorder_status_changed.emit(
                "ERROR", "Recorder data is not READY_TO_UPLOAD")
            return
        try:
            self._require_disabled_stationary_recorder_io(link)
        except Exception as exc:
            self._recorder_last_status = "READY_TO_UPLOAD"
            self.recorder_status_changed.emit(
                "READY_TO_UPLOAD",
                "Upload deferred; issue DRIVE STOP/disable, then retry: %s" % exc)
            return
        if (token is not None and token > 0
                and token <= self._recorder_cancelled_through):
            return  # Stop arrived during the pre-upload stationary readbacks.
        self.recorder_status_changed.emit("UPLOADING", "Uploading physical-double arrays…")
        try:
            data = link.record_upload()
        except Exception as exc:
            if (token is not None and token > 0
                    and token <= self._recorder_cancelled_through):
                return  # Stop owns the pending handle and terminal status.
            self._recorder_last_status = "READY_TO_UPLOAD"
            self.recorder_status_changed.emit(
                "READY_TO_UPLOAD",
                "Upload/validation failed; Retry Upload or Recorder Stop: %s" % exc)
            return
        if (token is not None and token > 0
                and token <= self._recorder_cancelled_through):
            # The vendor upload consumed the recorder buffer before the urgent
            # Stop could execute.  Do not publish a late COMPLETED/data bundle;
            # the urgent Stop will report CANCELLED with this exact condition.
            self._recorder_upload_consumed_after_cancel = True
            self._recorder_ready = False
            return
        resolved = self._recorder_resolved
        if self._recorder_manifest_current is not None:
            self._recorder_manifest_current["capture_completed_utc"] = \
                datetime.now(timezone.utc).isoformat()
            self._recorder_manifest_current["completion"] = "VALIDATED"
            self.recorder_manifest.emit(dict(self._recorder_manifest_current))
        self._recorder_active = False
        self._recorder_ready = False
        self._recorder_upload_consumed_after_cancel = False
        self._recorder_resolved = None
        self._recorder_last_status = "COMPLETED"
        completion_token = {
            "capture_id": (
                self._recorder_manifest_current or {}).get("capture_id"),
            "worker_generation": (
                self._recorder_manifest_current or {}).get("worker_generation"),
        }
        self.recorder_data.emit(data, resolved, completion_token)
        self.recorder_status_changed.emit("COMPLETED", "Recorder upload complete")

    def _run_position_move(self, link, payload):
        if (isinstance(payload, tuple) and len(payload) == 2
                and isinstance(payload[0], int)):
            token, request = payload
        else:  # compatibility for direct offline probes
            token, request = self._motion_generation + 1, payload
            self._motion_generation = token
        if not FINITE_PTP_LIVE_ENABLED:
            self.motion_result.emit(
                "move", single_axis_motion.MotionResult(
                    single_axis_motion.RED,
                    "LIVE PTP is NEED-DATA locked: mechanical envelope, direction, "
                    "validated SD/stopping distance, limit inputs and independent "
                    "E-stop/STO evidence are not yet commissioned"))
            return
        if token <= self._motion_cancelled_through:
            self.motion_result.emit(
                "move", single_axis_motion.MotionResult(
                    single_axis_motion.RED,
                    "STOP/cancel request superseded this motion before I/O"))
            return
        self._motion_ownership_requested = True
        result = single_axis_motion.run_position_move(
            link,
            request,
            signature_green=self._commutation_signature_green,
            sleep_fn=lambda seconds: self.msleep(
                int(max(float(seconds), 0.0) * 1000)),
            cancel_fn=lambda: (
                token <= self._motion_cancelled_through or not self._run),
        )
        if result.status == single_axis_motion.UNKNOWN:
            self._motion_config_unknown = True
        if result.final_state.get("disabled_verified") is True:
            self._motion_ownership_requested = False
        self.motion_result.emit("move", result)
        self._emit_axis_summary(link)

    def _drain_urgent_motion_jobs(self, link):
        while self._urgent_jobs:
            kind, _payload = self._urgent_jobs.popleft()
            if kind == "motion_stop":
                self._run_motion_stop(link)
            elif kind == "recorder_stop":
                self._run_recorder_stop(link)

    def _publish_persistence_status(self, link):
        try:
            status = self._validated_persistence_status(
                link.persistence_status())
        except Exception as exc:
            status = self._locked_persistence_status(exc)
        self._persistence_recovery_unknown = bool(status.get("lock_active"))
        self.persistence_audit_status.emit(status)
        return status

    @classmethod
    def _read_quiescent_admission(cls, link):
        """Require two identical, finite disabled/stationary safety sweeps."""
        sweeps = []
        for _sweep_index in range(2):
            observed = {}
            for register in cls._QUIESCENT_ADMISSION_REGISTERS:
                raw = link.command(register)
                try:
                    number = float(str(raw).strip().rstrip(";"))
                except (TypeError, ValueError, OverflowError) as exc:
                    raise RuntimeError(
                        "observe-only quiescent admission has unreadable %s"
                        % register) from exc
                if not math.isfinite(number):
                    raise RuntimeError(
                        "observe-only quiescent admission has non-finite %s"
                        % register)
                if register != "VX" and not number.is_integer():
                    raise RuntimeError(
                        "observe-only quiescent admission requires integer %s"
                        % register)
                observed[register] = float(number)
            sweeps.append(observed)
        if sweeps[0] != sweeps[1]:
            raise RuntimeError(
                "observe-only drive state changed between safety sweeps")
        state = sweeps[1]
        if not (
                state["MO"] == 0.0
                and state["SO"] == 0.0
                and state["VX"] == 0.0
                and state["PS"] in (-2.0, -1.0)
                and state["MF"] == 0.0):
            raise RuntimeError(
                "observe-only quiescent admission requires "
                "MO=SO=VX=MF=0 and PS=-2/-1; observed %s" % state)
        return dict(state)

    @classmethod
    def _required_transport_access_mode(cls, link):
        """Read explicit transport authority evidence without a fallback."""
        try:
            mode = link.access_mode
        except Exception as exc:
            raise RuntimeError(
                "transport access mode evidence is unavailable") from exc
        if mode not in {
                cls.OBSERVE_ONLY_ACCESS_MODE, cls.SUPERVISED_ACCESS_MODE}:
            raise RuntimeError(
                "transport access mode evidence is invalid: %r" % (mode,))
        return mode

    def run(self):
        shutdown_stop_pending = bool(
            self._motion_stop_requested
            or self._motion_ownership_requested
            or any(kind == "motion_stop" for kind, _payload in self._urgent_jobs))
        if not self._run and not shutdown_stop_pending:
            self.stopped.emit()
            return
        link = ElmoLink(self.port)
        try:
            if self.query_only:
                mode = link.enter_observe_only_session()
                if mode != self.OBSERVE_ONLY_ACCESS_MODE:
                    raise RuntimeError(
                        "observe-only transport latch returned an invalid mode")
            actual_access_mode = self._required_transport_access_mode(link)
            if actual_access_mode != self.access_mode:
                raise RuntimeError(
                    "transport access mode mismatch: requested %s, actual %s"
                    % (self.access_mode, actual_access_mode))
            link.connect()
        except Exception as e:
            self.failed.emit(str(e))
            self.stopped.emit()
            return
        # A STOP+Disconnect race may cancel the thread before ``run`` starts.
        # In that case connect only long enough to execute the already-owned
        # software STOP/disable transaction; never publish transient ONLINE.
        if not self._run:
            shutdown_stop_pending = bool(
                self._motion_stop_requested
                or self._motion_ownership_requested
                or any(kind == "motion_stop"
                       for kind, _payload in self._urgent_jobs))
            try:
                if shutdown_stop_pending:
                    self._run_motion_stop(link, action="shutdown_stop")
                self._urgent_jobs.clear()
            finally:
                try:
                    link.disconnect()
                except Exception as exc:
                    self.failed.emit(
                        "Disconnect outcome UNKNOWN; UI forced OFFLINE: %s" % exc)
                self.stopped.emit()
            return
        # Identity and the first complete telemetry snapshot form one
        # fail-closed admission boundary.  Never publish ONLINE from partial
        # metadata or an unknown MO state.
        info = {}
        try:
            actual_access_mode = self._required_transport_access_mode(link)
            if actual_access_mode != self.access_mode:
                raise RuntimeError(
                    "transport access mode mismatch: requested %s, actual %s"
                    % (self.access_mode, actual_access_mode))
            info["access_mode"] = actual_access_mode
            if self.query_only:
                info["quiescent_state"] = self._read_quiescent_admission(link)
            for key, cmd in (("fw", "VR"), ("pal", "VP"), ("boot", "VB")):
                info[key] = link.command(cmd)
            info["drive_identity"] = link.transaction_identity()
            missing_identity = [
                key for key in ("fw", "pal", "boot")
                if not str(info.get(key) or "").strip()]
            identity = info.get("drive_identity")
            if (not isinstance(identity, str)
                    or _HASHED_DRIVE_ID_RE.fullmatch(identity) is None):
                missing_identity.append("drive_identity")
            if missing_identity:
                raise RuntimeError(
                    "initial identity incomplete: %s" %
                    ", ".join(missing_identity))
            self._connection_identity_verified = True
            initial_telemetry = self._record_fresh_telemetry(
                link.read_telemetry())
            if not initial_telemetry.get("telemetry_valid"):
                raise RuntimeError(
                    "initial telemetry rejected: %s" %
                    initial_telemetry.get("telemetry_error"))
            info["initial_telemetry"] = initial_telemetry
        except Exception as exc:
            self._connection_identity_verified = False
            self._session_coordinate_known = False
            mode_prefix = (
                "Read-only"
                if self.access_mode == self.OBSERVE_ONLY_ACCESS_MODE
                else "Supervised"
                if self.access_mode == self.SUPERVISED_ACCESS_MODE
                else "Unknown"
            )
            self.failed.emit(
                "%s connection admission failed: %s"
                % (mode_prefix, exc))
            try:
                link.disconnect()
            except Exception:
                pass
            finally:
                self.stopped.emit()
            return
        info["target_type"] = "Gold Drive"
        try:
            persistence_status = self._validated_persistence_status(
                link.persistence_status())
        except Exception as exc:
            persistence_status = self._locked_persistence_status(exc)
        self._persistence_recovery_unknown = bool(
            persistence_status.get("lock_active"))
        info["persistence_status"] = dict(persistence_status)
        recorder_recovery_detail = None
        try:
            self._recorder_recovery_unknown = bool(
                link.recorder_recovery_unknown_latched())
        except Exception as exc:
            # A failed durable-state read cannot prove that no prior Recorder
            # capture is pending.  Keep every mutation locked until recovery.
            self._recorder_recovery_unknown = True
            recorder_recovery_detail = (
                "Recorder recovery ledger could not be read: %s" % exc)
        if self._recorder_recovery_unknown:
            self._recorder_active = True
            self._recorder_ready = False
            self._recorder_last_status = "RECOVERY_REQUIRED_UNKNOWN"
        if not self._run:
            try:
                if (self._motion_stop_requested
                        or self._motion_ownership_requested
                        or any(kind == "motion_stop"
                               for kind, _payload in self._urgent_jobs)):
                    self._run_motion_stop(link, action="shutdown_stop")
                self._urgent_jobs.clear()
            finally:
                try:
                    link.disconnect()
                except Exception as exc:
                    self.failed.emit(
                        "Disconnect outcome UNKNOWN; UI forced OFFLINE: %s" % exc)
                self.stopped.emit()
            return
        try:
            final_access_mode = self._required_transport_access_mode(link)
        except Exception as exc:
            self._connection_identity_verified = False
            self._session_coordinate_known = False
            self.failed.emit(
                "Connection access mode evidence was lost before admission: %s"
                % exc)
            try:
                link.disconnect()
            except Exception:
                pass
            self.stopped.emit()
            return
        if (final_access_mode != self.access_mode
                or final_access_mode != info.get("access_mode")):
            self._connection_identity_verified = False
            self._session_coordinate_known = False
            self.failed.emit(
                "Connection access mode changed before admission; ONLINE refused")
            try:
                link.disconnect()
            except Exception:
                pass
            self.stopped.emit()
            return
        self.connected.emit(info)
        self.persistence_audit_status.emit(dict(persistence_status))
        if self._recorder_recovery_unknown:
            self.recorder_status_changed.emit(
                "RECOVERY_REQUIRED_UNKNOWN",
                recorder_recovery_detail or
                "A prior disconnect lost Recorder Stop confirmation; click Recorder Stop "
                "to recover before any write/tuning/motion")
        try:
            self.motor_params.emit(link.read_motor_params())
        except Exception:
            pass
        try:
            self.feedback.emit(link.read_feedback())
        except Exception:
            pass
        try:
            self.tuning_gains.emit(link.read_tuning_gains())
        except Exception:
            pass
        self._emit_axis_summary(link)
        self.motion_authority.emit(False, "Commutation Signature required this connection")

        interval = 1.0 / POLL_HZ
        try:
            while self._run:
                self._drain_urgent_motion_jobs(link)
                while self._pending and self._run:
                    self._drain_urgent_motion_jobs(link)
                    if not self._run:
                        break
                    c = self._pending.popleft()
                    if self._encoder_maintenance_reconnect_required:
                        self.command_done.emit(
                            c, "ERR: Encoder Maintenance UNKNOWN — reconnect/audit 필요")
                        continue
                    if not self._session_coordinate_known:
                        self.command_done.emit(
                            c, "ERR: 세션 좌표 UNKNOWN — fresh PX readback 대기")
                        continue
                    phase = self._active_trial_phase()
                    if phase is not None:
                        self.command_done.emit(
                            c, "ERR: %s RAM 시험 중 원시 명령 실행 금지" % phase)
                        continue
                    try:
                        self.command_done.emit(c, str(link.command(c)))
                    except Exception as e:
                        self.command_done.emit(c, "ERR: %s" % e)
                while self._jobs and self._run:
                    self._drain_urgent_motion_jobs(link)
                    if not self._run:
                        break
                    kind, payload = self._jobs.popleft()
                    tune_token = None
                    if kind in {"autotune", "velpos", "verify_vp"}:
                        if (isinstance(payload, tuple) and len(payload) == 2
                                and isinstance(payload[0], int)):
                            tune_token, payload = payload
                        else:  # compatibility for pre-generation offline probes
                            tune_token = self._tune_job_generation + 1
                        if self._tune_cancel_requested(tune_token):
                            self._emit_guard_rejection(
                                kind, payload,
                                "STOP/cancel superseded this tuning request "
                                "before drive I/O")
                            continue
                    allowed, guard_message = self._trial_job_guard(kind, payload)
                    if not allowed:
                        self._emit_guard_rejection(kind, payload, guard_message)
                        continue
                    if kind in self._PRE_MUTATION_FRESH_REQUIRED:
                        pre_mutation = self._record_fresh_telemetry(
                            link.read_telemetry())
                        if not pre_mutation.get("telemetry_valid"):
                            raise RuntimeError(
                                "pre-mutation telemetry rejected for %s: %s" % (
                                    kind, pre_mutation.get("telemetry_error")))
                        self.telemetry.emit(pre_mutation)
                    # stop() may arrive while the fresh pre-mutation query is
                    # blocked.  Re-check after that round trip, before any
                    # popped job can cross into a write-capable handler.
                    if not self._run:
                        break
                    if (kind in {"autotune", "velpos", "verify_vp"}
                            and self._tune_cancel_requested(tune_token)):
                        self._emit_guard_rejection(
                            kind, payload,
                            "STOP/cancel superseded this tuning request "
                            "during the fresh telemetry admission read")
                        continue
                    if kind == "motor_write":
                        self._invalidate_commutation_signature(
                            "Commutation Signature revoked before Motor Settings write")
                        try:
                            if (isinstance(payload, dict)
                                    and "writes" in payload):
                                writes = payload.get("writes")
                                ca18_basis = payload.get("ca18_basis")
                            else:  # compatibility for already-queued old jobs
                                writes = payload
                                ca18_basis = None
                            ok, msg = link.write_motor_params(
                                writes, expected_ca18=ca18_basis)
                            self.write_result.emit(ok, msg)
                            if ok:
                                self.motor_params.emit(link.read_motor_params())
                        except Exception as e:
                            self.write_result.emit(False, "ERR: %s" % e)
                        self._publish_persistence_status(link)
                    elif kind == "feedback_write":
                        self._invalidate_commutation_signature(
                            "Commutation Signature revoked before Feedback/commutation write")
                        try:
                            # ordered pairs: MO=0 gate + CA[35]/[36] -> CA[41] re-issue + SV
                            ok, msg = link.write_feedback_params(payload)
                            self.write_result.emit(ok, msg)
                            if ok:
                                self.feedback.emit(link.read_feedback())
                        except Exception as e:
                            self.write_result.emit(False, "ERR: %s" % e)
                        self._publish_persistence_status(link)
                    elif kind == "axis_read":
                        self._emit_axis_summary(link)
                    elif kind == "axis_drive_mode_read":
                        self._emit_axis_drive_mode(link)
                    elif kind == "axis_current_reference_read":
                        self._emit_axis_current_reference(link)
                    elif kind == "axis_digital_inputs_read":
                        self._emit_axis_digital_inputs(link)
                    elif kind == "axis_digital_outputs_read":
                        self._emit_axis_digital_outputs(link)
                    elif kind == "motion_stop":
                        self._run_motion_stop(link)
                    elif kind == "motion_move":
                        self._run_position_move(link, payload)
                    elif kind == "recorder_discover":
                        self._run_recorder_discover(link)
                    elif kind == "recorder_start":
                        self._run_recorder_start(link, payload)
                    elif kind == "recorder_upload":
                        self._run_recorder_upload(link, payload)
                    elif kind == "recorder_stop":
                        self._run_recorder_stop(link)
                    elif kind == "persistence_audit":
                        self._invalidate_commutation_signature(
                            "Post-reset persistence audit revoked Commutation Signature")
                        self.motion_authority.emit(
                            False,
                            "Post-reset persistence audit never grants motion authority")
                        try:
                            audit = self._validated_persistence_status(
                                link.audit_persistence_after_reset(
                                    operator_reset_attested=True))
                        except Exception as exc:
                            audit = self._locked_persistence_status(exc)
                            audit["status"] = "AUDIT_EXCEPTION"
                        self._persistence_recovery_unknown = bool(
                            audit.get("lock_active", True))
                        if (audit.get("resolved") is True
                                and not self._persistence_recovery_unknown):
                            if audit.get("phase") == "P1":
                                self._p1_gain_trial = None
                            elif audit.get("phase") == "P2":
                                self._vp_gain_trial = None
                        self.persistence_audit_status.emit(dict(audit))
                        try:
                            self.tuning_gains.emit(link.read_tuning_gains())
                        except Exception:
                            pass
                    elif kind == "autotune":
                        self._invalidate_commutation_signature(
                            "Commutation Signature revoked before Phase 1 tuning")
                        if not self._motion_stop_requested:
                            self._cancel_at = False
                        try:
                            self._run_autotune(link, payload, tune_token)
                        finally:
                            if not self._motion_stop_requested:
                                self._cancel_at = False
                    elif kind == "autotune_apply":
                        # Defense in depth: the guard rejects this legacy API.
                        # Keep the typed signal for compatibility, but never I/O.
                        self.autotune_applied.emit(
                            False, "Legacy direct apply 지원 종료 — P1 transaction을 사용하세요.")
                    elif kind == "velpos":
                        if not self._motion_stop_requested:
                            self._cancel_at = False
                        try:
                            self._run_velpos_autotune(link, payload, tune_token)
                        finally:
                            if not self._motion_stop_requested:
                                self._cancel_at = False
                    elif kind == "verify_vp":
                        if not self._motion_stop_requested:
                            self._cancel_at = False
                        try:
                            self._run_verify_vp(link, payload, tune_token)
                        finally:
                            if not self._motion_stop_requested:
                                self._cancel_at = False
                    elif kind == "vp_trial_begin":
                        if self._p1_gain_trial is not None or self._vp_gain_trial is not None:
                            phase = "P1" if self._p1_gain_trial is not None else "P2"
                            self.velpos_gain_action.emit(
                                "begin", False,
                                "%s RAM 시험을 먼저 복원하거나 저장해야 합니다." % phase,
                                None)
                            continue
                        try:
                            ok, msg, trial = autotune_velpos.begin_gain_trial_vp(
                                link, payload)
                        except Exception as e:
                            ok, msg, trial = False, "RAM 임시 적용 예외: %r" % e, None
                        self._vp_gain_trial = trial
                        self.velpos_gain_action.emit("begin", ok, msg, trial)
                        try:
                            self.tuning_gains.emit(link.read_tuning_gains())
                        except Exception:
                            pass
                    elif kind == "p1_trial_begin":
                        if self._p1_gain_trial is not None or self._vp_gain_trial is not None:
                            phase = "P1" if self._p1_gain_trial is not None else "P2"
                            self.current_gain_action.emit(
                                "begin", False,
                                "%s RAM 시험을 먼저 복원하거나 저장해야 합니다." % phase,
                                None)
                            continue
                        try:
                            ok, msg, trial = autotune_current.begin_gain_trial_p1(link, payload)
                        except Exception as e:
                            ok, msg, trial = False, "P1 RAM 임시 적용 예외: %r" % e, None
                        self._p1_gain_trial = trial
                        self.current_gain_action.emit("begin", ok, msg, trial)
                        try:
                            self.tuning_gains.emit(link.read_tuning_gains())
                        except Exception:
                            pass
                    elif kind == "p1_trial_restore":
                        prepared, adoption_msg, already_restored = \
                            self._prepare_retained_trial_restore(
                                link, "P1", payload)
                        if not prepared:
                            self.current_gain_action.emit(
                                "restore", False, adoption_msg, payload)
                            continue
                        if already_restored:
                            self.current_gain_action.emit(
                                "restore", True, adoption_msg, payload)
                            continue
                        try:
                            ok, msg = autotune_current.restore_gain_trial_p1(link, payload)
                        except Exception as e:
                            ok, msg = False, "P1 원래 게인 복원 예외: %r" % e
                        if adoption_msg:
                            msg = "%s; %s" % (adoption_msg, msg)
                        if ok:
                            self._p1_gain_trial = None
                        self.current_gain_action.emit("restore", ok, msg, payload)
                        try:
                            self.tuning_gains.emit(link.read_tuning_gains())
                        except Exception:
                            pass
                    elif kind == "p1_trial_commit":
                        try:
                            ok, msg = autotune_current.commit_gain_trial_p1(link, payload)
                        except Exception as e:
                            ok, msg = False, "P1 SV 저장 예외: %r" % e
                        if ok:
                            self._p1_gain_trial = None
                        self.current_gain_action.emit("commit", ok, msg, payload)
                        self._publish_persistence_status(link)
                    elif kind == "vp_trial_restore":
                        prepared, adoption_msg, already_restored = \
                            self._prepare_retained_trial_restore(
                                link, "P2", payload)
                        if not prepared:
                            self.velpos_gain_action.emit(
                                "restore", False, adoption_msg, payload)
                            continue
                        if already_restored:
                            self._vp_gain_trial = None
                            self.velpos_gain_action.emit(
                                "restore", True, adoption_msg, payload)
                            continue
                        try:
                            ok, msg = autotune_velpos.restore_gain_trial_vp(link, payload)
                        except Exception as e:
                            ok, msg = False, "원래 게인 복원 예외: %r" % e
                        if adoption_msg:
                            msg = "%s; %s" % (adoption_msg, msg)
                        if ok:
                            self._vp_gain_trial = None
                        self.velpos_gain_action.emit("restore", ok, msg, payload)
                        try:
                            self.tuning_gains.emit(link.read_tuning_gains())
                        except Exception:
                            pass
                    elif kind == "vp_trial_commit":
                        try:
                            ok, msg = autotune_velpos.commit_gain_trial_vp(link, payload)
                        except Exception as e:
                            ok, msg = False, "SV 저장 예외: %r" % e
                        if ok:
                            self._vp_gain_trial = None
                        self.velpos_gain_action.emit("commit", ok, msg, payload)
                        self._publish_persistence_status(link)
                    elif kind == "velpos_apply":
                        # Defense in depth: the guard rejects this legacy API.
                        # Keep the typed signal for compatibility, but never I/O.
                        self.velpos_applied.emit(
                            False, "Legacy direct apply 지원 종료 — P2 transaction을 사용하세요.")
                    elif kind == "soft_zero":
                        self._session_zero_confirmed = False
                        try:
                            msg, after = self._perform_soft_zero(link)
                            self._session_coordinate_known = True
                            after = self._record_fresh_telemetry(after)
                            self._session_zero_confirmed = bool(
                                after.get("telemetry_valid")
                                and self._is_finite_number(after.get("pos"))
                                and abs(float(after["pos"])) <= 0.5)
                            if not self._session_zero_confirmed:
                                raise SessionCoordinateError(
                                    "PX=0 identity-bound readback did not prove zero",
                                    telemetry=after,
                                    coordinate_unknown=True)
                            self.soft_zero_result.emit(True, msg, after)
                            self.telemetry.emit(after)
                        except SessionCoordinateError as e:
                            if e.coordinate_unknown:
                                self._latch_coordinate_unknown()
                            self.soft_zero_result.emit(
                                False, "세션 원점 적용 거부/실패: %s" % e, e.telemetry)
                        except Exception as e:
                            self.soft_zero_result.emit(False, "세션 원점 적용 거부/실패: %s" % e, None)
                    elif kind == "encoder_maint":
                        self._session_zero_confirmed = False
                        self._invalidate_commutation_signature(
                            "Commutation Signature revoked before Encoder Maintenance")
                        try:
                            msg, after = self._perform_encoder_maintenance(link, payload)
                            self._session_coordinate_known = True
                            after = self._record_fresh_telemetry(after)
                            self.encoder_maint_result.emit(True, msg)
                            self.telemetry.emit(after)
                        except SessionCoordinateError as e:
                            if e.coordinate_unknown:
                                self._latch_coordinate_unknown(reconnect_required=True)
                                invalid = {
                                    name: None for name in TELEMETRY_REQUIRED_FIELDS}
                                invalid.update({
                                    "telemetry_valid": False,
                                    "telemetry_error": str(e),
                                    "session_coordinate_known": False,
                                    "encoder_maintenance_reconnect_required": True,
                                })
                                self.telemetry.emit(invalid)
                            self.encoder_maint_result.emit(False, "엔코더 정비 실패: %s" % e)
                        except Exception as e:
                            self.encoder_maint_result.emit(False, "엔코더 정비 실패: %s" % e)
                if not self._run:
                    break
                self._poll_recorder(link)
                fresh = self._record_fresh_telemetry(link.read_telemetry())
                if not fresh.get("telemetry_valid"):
                    raise RuntimeError(
                        "telemetry authority lost: %s" %
                        fresh.get("telemetry_error"))
                self.telemetry.emit(fresh)
                self.msleep(int(interval * 1000))
        except Exception as exc:
            self._run = False
            self._connection_identity_verified = False
            self._session_coordinate_known = False
            invalid = {name: None for name in TELEMETRY_REQUIRED_FIELDS}
            invalid.update({
                "telemetry_valid": False,
                "telemetry_error": "%s: %s" % (type(exc).__name__, exc),
                "session_coordinate_known": False,
                "encoder_maintenance_reconnect_required":
                    self._encoder_maintenance_reconnect_required,
            })
            self.telemetry.emit(invalid)
            self.failed.emit("Connection/telemetry lost; writes locked: %s" % exc)
        finally:
            if self._recorder_active:
                self._run_recorder_stop(link, "connection closing")
            if (self._motion_ownership_requested
                    or self._motion_stop_requested
                    or any(kind == "motion_stop"
                           for kind, _payload in self._urgent_jobs)):
                self._run_motion_stop(link, action="shutdown_stop")
                self._urgent_jobs = collections.deque(
                    item for item in self._urgent_jobs
                    if item[0] != "motion_stop")
            if self._p1_gain_trial is not None:
                try:
                    ok, msg = autotune_current.restore_gain_trial_p1(
                        link, self._p1_gain_trial)
                except Exception as e:
                    ok, msg = False, "연결 종료 전 P1 게인 복원 예외: %r" % e
                trial = self._p1_gain_trial
                if ok:
                    self._p1_gain_trial = None
                self.current_gain_action.emit("restore", ok, msg, trial)
            if self._vp_gain_trial is not None:
                try:
                    ok, msg = autotune_velpos.restore_gain_trial_vp(
                        link, self._vp_gain_trial)
                except Exception as e:
                    ok, msg = False, "연결 종료 전 P2 게인 복원 예외: %r" % e
                trial = self._vp_gain_trial
                if ok:
                    self._vp_gain_trial = None
                self.velpos_gain_action.emit("restore", ok, msg, trial)
            self._connection_identity_verified = False
            self._session_coordinate_known = False
            try:
                link.disconnect()
            except Exception as exc:
                self.failed.emit(
                    "Disconnect outcome UNKNOWN; UI forced OFFLINE: %s" % exc)
            finally:
                self.stopped.emit()

    def _run_autotune(self, link, kw: dict, tune_token=None):
        """Run the current-loop auto-tune in this thread, streaming progress to the GUI.

        sleep_fn -> QThread.msleep so timeouts advance in real time; progress_fn and
        cancel_fn bridge to Qt signals / the operator-abort flag. The module itself
        never raises (returns a RED result) and runs the SPEC §6 abort chain on cancel.
        """
        self.autotune_started.emit()
        params = autotune_current.AutotuneParams(
            sleep_fn=lambda s: self.msleep(int(max(s, 0.0) * 1000)),
            progress_fn=lambda code, detail: self.autotune_progress.emit(str(code), str(detail)),
            cancel_fn=lambda: self._tune_cancel_requested(tune_token),
            **kw)
        guarded_link = _EnergyAwareLink(
            link, self._claim_drive_energy,
            lambda: not self._tune_cancel_requested(tune_token))
        try:
            res = autotune_current.run_current_autotune(guarded_link, params)
        except Exception as e:                       # module shouldn't raise; be safe
            res = autotune_current.AutotuneResult(
                status=autotune_current.RED, reason="worker 예외: %r" % e)
        res = self._finish_energizing_workflow(link, res, "autotune")
        self._latch_configuration_unknown(link, res, "P1")
        self.autotune_result.emit(res)
        try:                                         # gains view reflects reality post-run
            self.tuning_gains.emit(link.read_tuning_gains())
        except Exception:
            pass

    def _run_velpos_autotune(self, link, kw: dict, tune_token=None):
        """Run the Phase-2 vel/pos auto-tune in this thread (mirror of
        _run_autotune): sleep_fn -> msleep, progress_fn/cancel_fn -> Qt signals
        / the shared operator-abort flag.  The module never raises (RED result)
        and runs the segment-appropriate abort chain on cancel."""
        self.velpos_started.emit()
        params = autotune_velpos.AutotuneVPParams(
            sleep_fn=lambda s: self.msleep(int(max(s, 0.0) * 1000)),
            progress_fn=lambda code, detail: self.velpos_progress.emit(str(code), str(detail)),
            cancel_fn=lambda: self._tune_cancel_requested(tune_token),
            **kw)
        guarded_link = _EnergyAwareLink(
            link, self._claim_drive_energy,
            lambda: not self._tune_cancel_requested(tune_token))
        try:
            res = autotune_velpos.run_velpos_autotune(guarded_link, params)
        except Exception as e:                       # module shouldn't raise; be safe
            res = autotune_velpos.AutotuneVPResult(
                status=autotune_velpos.RED, reason="worker 예외: %r" % e)
        res = self._finish_energizing_workflow(link, res, "velpos")
        evidence = res.evidence or {}
        self._latch_configuration_unknown(link, res, "P2")
        signature = evidence.get("signature_gate", {})
        final = evidence.get("final_state", {})
        signature_mode = (bool(kw.get("signature_only")) or
                          signature.get("mode") ==
                          "standalone_commutation_signature")
        if signature_mode:
            self._commutation_signature_green = bool(
                res.status == autotune_velpos.GREEN
                and signature.get("pass") is True
                and final.get("MO") == 0
                and final.get("TC") == 0)
            self._commutation_signature_token = (
                str(uuid.uuid4()) if self._commutation_signature_green else None)
            detail = ("Session Commutation Signature GREEN"
                      if self._commutation_signature_green
                      else "Commutation Signature not GREEN")
            self.motion_authority.emit(
                self._commutation_signature_green, detail)
            self._emit_axis_summary(link)
        self.velpos_result.emit(res)
        try:                                         # gains view reflects reality post-run
            self.tuning_gains.emit(link.read_tuning_gains())
        except Exception:
            pass

    def _run_verify_vp(self, link, payload, tune_token=None):
        """Run the F2/G5 verification in this thread (mirror of
        _run_velpos_autotune): sleep_fn -> msleep, progress -> the shared
        velpos_progress stream, cancel -> the operator-abort flag.  The
        module never raises (RED result) and runs the JV abort chain
        (JV=0 -> BG -> ST -> MO=0) on cancel."""
        if isinstance(payload, tuple):
            kw, trial = payload[:2]
        else:                           # compatibility with existing smoke/tests
            kw, trial = payload, None
        self.verify_started.emit()
        params = autotune_velpos.AutotuneVPParams(
            sleep_fn=lambda s: self.msleep(int(max(s, 0.0) * 1000)),
            progress_fn=lambda code, detail: self.velpos_progress.emit(str(code), str(detail)),
            cancel_fn=lambda: self._tune_cancel_requested(tune_token),
            **kw)
        guarded_link = _EnergyAwareLink(
            link, self._claim_drive_energy,
            lambda: not self._tune_cancel_requested(tune_token))
        try:
            if trial is None:
                res = autotune_velpos.verify_run_vp(guarded_link, params)
            else:
                res = autotune_velpos.verify_gain_trial_vp(
                    guarded_link, trial, params)
        except Exception as e:                       # module shouldn't raise; be safe
            res = autotune_velpos.AutotuneVPResult(
                status=autotune_velpos.RED, reason="verify worker 예외: %r" % e)
        res = self._finish_energizing_workflow(link, res, "verify_vp")
        self._latch_configuration_unknown(link, res, "P2 Verify")
        if trial is not None:
            restore = (res.evidence or {}).get("gain_trial_restore", {})
            if res.status != autotune_velpos.GREEN and restore.get("pass") is True:
                self._vp_gain_trial = None
            else:
                self._vp_gain_trial = trial
        self.verify_result.emit(res)
        try:
            self.tuning_gains.emit(link.read_tuning_gains())
        except Exception:
            pass


# ---------------------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------------------
def metric(title: str):
    """Monospace metric readout (title, big value, small sub-line). Returns (frame, value, sub)."""
    box = QtWidgets.QFrame(); box.setObjectName("cell")
    lay = QtWidgets.QVBoxLayout(box); lay.setContentsMargins(12, 9, 12, 9); lay.setSpacing(2)
    t = QtWidgets.QLabel(title); t.setProperty("role", "metric_t")
    v = QtWidgets.QLabel("—"); v.setProperty("role", "metric_v")
    v.setStyleSheet("color:%s;" % theme.TEXT)
    sub = QtWidgets.QLabel(""); sub.setProperty("role", "hint")
    lay.addWidget(t); lay.addWidget(v); lay.addWidget(sub)
    return box, v, sub


class PortCombo(QtWidgets.QComboBox):
    """COM-port dropdown that re-scans available ports each time it is opened."""
    def __init__(self, refresh_cb, parent=None):
        super().__init__(parent)
        self._refresh_cb = refresh_cb

    def showPopup(self):
        if self._refresh_cb:
            self._refresh_cb()
        super().showPopup()


class MacTitleBar(QtWidgets.QWidget):
    """macOS-style title bar: traffic lights (left) + centered title, drag to move."""
    def __init__(self, win, title=""):
        super().__init__(win)
        self._win = win
        self._drag = None
        self.setFixedHeight(38)
        self.setObjectName("titlebar")
        self.setStyleSheet(
            f"#titlebar{{background:{theme.BG_BOT};}}"
            f"#titletext{{color:{theme.MUTED};font-weight:700;font-size:12px;letter-spacing:1px;}}"
        )
        lay = QtWidgets.QHBoxLayout(self); lay.setContentsMargins(14, 0, 14, 0); lay.setSpacing(9)
        lights = (("#ff5f57", self._close), ("#febc2e", self._min), ("#28c840", self._max))
        for color, slot in lights:
            b = QtWidgets.QPushButton(); b.setFixedSize(14, 14); b.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(f"QPushButton{{background:{color};border-radius:7px;border:none;}}")
            b.clicked.connect(slot)
            lay.addWidget(b)
        lay.addStretch(1)
        self._title = QtWidgets.QLabel(title); self._title.setObjectName("titletext")
        lay.addWidget(self._title)
        lay.addStretch(1)
        spacer = QtWidgets.QWidget(); spacer.setFixedWidth(3 * 14 + 2 * 9)  # balance the lights
        lay.addWidget(spacer)

    def _close(self): self._win.close()
    def _min(self): self._win.showMinimized()
    def _max(self): self._win.showNormal() if self._win.isMaximized() else self._win.showMaximized()

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None and (e.buttons() & QtCore.Qt.MouseButton.LeftButton):
            self._win.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def mouseDoubleClickEvent(self, e):
        self._max()


class CurrentPageStack(QtWidgets.QStackedWidget):
    """Size a stacked workspace from its current page, not every hidden page."""

    def sizeHint(self):
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):
        current = self.currentWidget()
        return (current.minimumSizeHint()
                if current is not None else super().minimumSizeHint())


class ToolOrganizerDialog(QtWidgets.QDialog):
    """Modeless, session-only adapter around the zero-I/O layout model."""

    _LABELS = {
        "motion": "Single Axis Motion",
        "motor": "Motor Settings",
        "feedback": "Feedback Settings",
        "tuning": "Quick / Expert Tuning",
        "axis": "Axis Summary",
        "recorder": "Recorder",
        "status": "Status / Session Log",
        "system": "System Configuration",
    }

    def __init__(self, parent, layout, apply_callback):
        super().__init__(parent)
        self.setWindowTitle("Tool Organizer · LOCAL SESSION")
        self.setModal(False)
        self.setWindowModality(QtCore.Qt.WindowModality.NonModal)
        self.setMinimumSize(560, 430)
        self._apply_callback = apply_callback
        self.candidate = tool_organizer.validate_layout(layout)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)
        title = QtWidgets.QLabel("TOOL ORGANIZER")
        title.setProperty("role", "celltitle")
        outer.addWidget(title)
        self.lbl_contract = QtWidgets.QLabel(
            "LOCAL SESSION v0.1 · NOT EAS PERSISTENCE — only the eight "
            "workspace selectors can be shown or reordered. DRIVE STOP, "
            "connection state and persistence warnings are immutable.")
        self.lbl_contract.setWordWrap(True)
        self.lbl_contract.setProperty("role", "hint")
        outer.addWidget(self.lbl_contract)

        panes = QtWidgets.QHBoxLayout()
        panes.setSpacing(10)
        active_group = QtWidgets.QGroupBox("Activities · visible")
        active_layout = QtWidgets.QVBoxLayout(active_group)
        self.active_list = QtWidgets.QListWidget()
        self.active_list.setObjectName("toolOrganizerActive")
        active_layout.addWidget(self.active_list)
        panes.addWidget(active_group, 1)

        controls = QtWidgets.QVBoxLayout()
        controls.addStretch(1)
        self.btn_up = QtWidgets.QPushButton("Move Up")
        self.btn_down = QtWidgets.QPushButton("Move Down")
        self.btn_remove = QtWidgets.QPushButton("Remove →")
        self.btn_add = QtWidgets.QPushButton("← Add")
        for button in (self.btn_up, self.btn_down,
                       self.btn_remove, self.btn_add):
            controls.addWidget(button)
        controls.addStretch(1)
        panes.addLayout(controls)

        available_group = QtWidgets.QGroupBox("Tools · hidden / available")
        available_layout = QtWidgets.QVBoxLayout(available_group)
        self.hidden_list = QtWidgets.QListWidget()
        self.hidden_list.setObjectName("toolOrganizerAvailable")
        available_layout.addWidget(self.hidden_list)
        panes.addWidget(available_group, 1)
        outer.addLayout(panes, 1)

        self.lbl_error = QtWidgets.QLabel("")
        self.lbl_error.setProperty("role", "hint")
        self.lbl_error.setWordWrap(True)
        outer.addWidget(self.lbl_error)

        actions = QtWidgets.QHBoxLayout()
        self.btn_reset = QtWidgets.QPushButton("Reset Defaults")
        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        self.btn_apply = QtWidgets.QPushButton("Apply Session Layout")
        self.btn_apply.setObjectName("primary")
        actions.addWidget(self.btn_reset)
        actions.addStretch(1)
        actions.addWidget(self.btn_cancel)
        actions.addWidget(self.btn_apply)
        outer.addLayout(actions)

        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_add.clicked.connect(self._add_selected)
        self.btn_up.clicked.connect(lambda: self._move_selected(-1))
        self.btn_down.clicked.connect(lambda: self._move_selected(1))
        self.btn_reset.clicked.connect(self._reset)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self._apply)
        self._refresh_lists()

    def reset_candidate(self, layout):
        """Discard a closed dialog's draft before the next modeless open."""
        self.candidate = tool_organizer.validate_layout(layout)
        self.lbl_error.clear()
        self._refresh_lists()

    @staticmethod
    def _selected_tool(list_widget):
        item = list_widget.currentItem()
        return (item.data(QtCore.Qt.ItemDataRole.UserRole)
                if item is not None else None)

    def _fill_list(self, list_widget, tool_ids, selected=None):
        list_widget.clear()
        selected_row = -1
        for row, tool_id in enumerate(tool_ids):
            item = QtWidgets.QListWidgetItem(
                "%s  [%s]" % (self._LABELS[tool_id], tool_id))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, tool_id)
            list_widget.addItem(item)
            if tool_id == selected:
                selected_row = row
        if selected_row >= 0:
            list_widget.setCurrentRow(selected_row)

    def _refresh_lists(self, selected_active=None, selected_available=None):
        self._fill_list(self.active_list, self.candidate.active, selected_active)
        self._fill_list(
            self.hidden_list, self.candidate.available, selected_available)

    def _replace_candidate(self, operation, *, selected_active=None,
                           selected_available=None):
        previous = self.candidate
        try:
            candidate = tool_organizer.validate_layout(operation(previous))
        except tool_organizer.ToolOrganizerError as exc:
            self.lbl_error.setText(str(exc))
            return False
        self.candidate = candidate
        self.lbl_error.clear()
        self._refresh_lists(selected_active, selected_available)
        return True

    def _remove_selected(self):
        tool_id = self._selected_tool(self.active_list)
        if tool_id is None:
            self.lbl_error.setText("Select one visible tool to remove.")
            return
        self._replace_candidate(
            lambda layout: tool_organizer.remove_tool(layout, tool_id),
            selected_available=tool_id)

    def _add_selected(self):
        tool_id = self._selected_tool(self.hidden_list)
        if tool_id is None:
            self.lbl_error.setText("Select one available tool to add.")
            return
        self._replace_candidate(
            lambda layout: tool_organizer.add_tool(layout, tool_id),
            selected_active=tool_id)

    def _move_selected(self, delta):
        tool_id = self._selected_tool(self.active_list)
        if tool_id is None:
            self.lbl_error.setText("Select one visible tool to move.")
            return
        self._replace_candidate(
            lambda layout: tool_organizer.move_tool(layout, tool_id, delta),
            selected_active=tool_id)

    def _reset(self):
        self.candidate = tool_organizer.reset_defaults()
        self.lbl_error.clear()
        self._refresh_lists()

    def _apply(self):
        try:
            self._apply_callback(self.candidate)
        except tool_organizer.ToolOrganizerError as exc:
            self.lbl_error.setText(str(exc))
            return
        self.accept()


class StatusMonitorDialog(QtWidgets.QDialog):
    """Modeless view of telemetry already admitted by the application core."""

    _BLANK = "—"

    def __init__(self, parent, model, replace_config_callback):
        super().__init__(parent)
        self.setWindowTitle("Status Monitor · HOST OBSERVED v0.1")
        self.setModal(False)
        self.setWindowModality(QtCore.Qt.WindowModality.NonModal)
        self.setMinimumSize(640, 360)
        self.model = model
        self._replace_config_callback = replace_config_callback

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(9)

        title_row = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("STATUS MONITOR")
        title.setProperty("role", "celltitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.lbl_state = QtWidgets.QLabel("NO CURRENT SAMPLE")
        self.lbl_state.setObjectName("pill")
        title_row.addWidget(self.lbl_state)
        outer.addLayout(title_row)

        self.lbl_contract = QtWidgets.QLabel(
            "HOST OBSERVED v0.1 · NO NEW DRIVE POLLING — displays only the "
            "core-admitted PX/VX/PE/IQ/MO sample. Line layout is session-only; "
            "EAS arbitrary signals, Quick Watch and .smc/.sac remain locked.")
        self.lbl_contract.setWordWrap(True)
        self.lbl_contract.setProperty("role", "hint")
        outer.addWidget(self.lbl_contract)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setObjectName("statusMonitorTable")
        self.table.setHorizontalHeaderLabels((
            "Target", "Signal", "Value", "Units", "Description"))
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            4, QtWidgets.QHeaderView.ResizeMode.Stretch)
        outer.addWidget(self.table, 1)

        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(QtWidgets.QLabel("Available signal"))
        self.cmb_available = QtWidgets.QComboBox()
        self.cmb_available.setMinimumWidth(90)
        controls.addWidget(self.cmb_available)
        self.btn_add = QtWidgets.QPushButton("Add")
        self.btn_remove = QtWidgets.QPushButton("Remove")
        self.btn_up = QtWidgets.QPushButton("Move Up")
        self.btn_down = QtWidgets.QPushButton("Move Down")
        self.btn_reset = QtWidgets.QPushButton("Reset Defaults")
        for button in (self.btn_add, self.btn_remove, self.btn_up,
                       self.btn_down, self.btn_reset):
            controls.addWidget(button)
        controls.addStretch(1)
        outer.addLayout(controls)

        self.lbl_error = QtWidgets.QLabel("")
        self.lbl_error.setProperty("role", "hint")
        self.lbl_error.setWordWrap(True)
        outer.addWidget(self.lbl_error)

        self.btn_add.clicked.connect(self._add_line)
        self.btn_remove.clicked.connect(self._remove_line)
        self.btn_up.clicked.connect(lambda: self._move_line(-1))
        self.btn_down.clicked.connect(lambda: self._move_line(1))
        self.btn_reset.clicked.connect(
            lambda: self._replace_config(status_monitor.DEFAULT_CONFIG))
        self.table.itemSelectionChanged.connect(self._update_controls)
        self.render(model.snapshot())

    @staticmethod
    def _format_value(value):
        if value is None:
            return StatusMonitorDialog._BLANK
        if type(value) is float:
            return format(value, ".15g")
        return str(value)

    def _selected_signal(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 1)
        return item.text() if item is not None else None

    def _replace_config(self, candidate):
        try:
            self._replace_config_callback(candidate)
        except status_monitor.StatusMonitorError as exc:
            self.lbl_error.setText(str(exc))
            return
        self.lbl_error.clear()

    def _add_line(self):
        signal = self.cmb_available.currentText().strip()
        if not signal:
            self.lbl_error.setText("No allowlisted signal is available to add.")
            return
        self._replace_config(status_monitor.insert_line(
            self.model.config, signal, len(self.model.config.lines)))

    def _remove_line(self):
        signal = self._selected_signal()
        if signal is None:
            self.lbl_error.setText("Select one displayed signal to remove.")
            return
        self._replace_config(
            status_monitor.delete_line(self.model.config, signal))

    def _move_line(self, delta):
        signal = self._selected_signal()
        if signal is None:
            self.lbl_error.setText("Select one displayed signal to move.")
            return
        self._replace_config(
            status_monitor.move_line(self.model.config, signal, delta))

    def _update_controls(self):
        signal = self._selected_signal()
        lines = self.model.config.lines
        self.btn_add.setEnabled(self.cmb_available.count() > 0)
        self.btn_remove.setEnabled(signal is not None)
        if signal is None or signal not in lines:
            self.btn_up.setEnabled(False)
            self.btn_down.setEnabled(False)
            return
        row = lines.index(signal)
        self.btn_up.setEnabled(row > 0)
        self.btn_down.setEnabled(row + 1 < len(lines))

    def render(self, snapshot=None, *, observer_error=False):
        snapshot = self.model.snapshot() if snapshot is None else snapshot
        selected = self._selected_signal()
        self.table.setRowCount(len(snapshot.lines))
        selected_row = -1
        for row, line in enumerate(snapshot.lines):
            display_value = None if observer_error else line.value
            values = (
                "Drive01", line.signal, self._format_value(display_value),
                line.unit, line.description)
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                if column == 2:
                    item.setTextAlignment(
                        int(QtCore.Qt.AlignmentFlag.AlignRight
                            | QtCore.Qt.AlignmentFlag.AlignVCenter))
                self.table.setItem(row, column, item)
            if line.signal == selected:
                selected_row = row
        if selected_row >= 0:
            self.table.selectRow(selected_row)

        if observer_error:
            self.lbl_state.setText("OBSERVER ERROR · DISPLAY BLANK")
        elif snapshot.current:
            self.lbl_state.setText(
                "CURRENT · GEN %d · SEQ %d" %
                (snapshot.generation, snapshot.sequence))
        else:
            self.lbl_state.setText("NO CURRENT SAMPLE")

        missing = tuple(
            signal for signal in status_monitor.SIGNAL_SPECS
            if signal not in self.model.config.lines)
        current_available = self.cmb_available.currentText()
        self.cmb_available.blockSignals(True)
        self.cmb_available.clear()
        self.cmb_available.addItems(missing)
        if current_available in missing:
            self.cmb_available.setCurrentText(current_available)
        self.cmb_available.blockSignals(False)
        self._update_controls()


class MainWindow(QtWidgets.QMainWindow):
    _TOOL_ID_TO_PAGE_INDEX = {
        tool_id: index for index, tool_id in
        enumerate(tool_organizer.CANONICAL_TOOL_IDS)
    }
    _TOOL_NAV_OPERATIONS = {
        "motion": ("nav.motion",),
        "motor": ("nav.motor",),
        "feedback": ("nav.feedback",),
        "tuning": ("nav.tuning.quick", "nav.tuning.expert"),
        "axis": ("nav.axis",),
        "recorder": ("nav.recorder",),
        "status": ("nav.session_log",),
        "system": ("nav.system_config",),
    }

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        # The compact eight-page engineering workspace is contract-tested at
        # 1366 px.  Declaring a smaller initial size caused Qt to silently grow
        # the window to the header/card minimum and made the visible contract
        # misleading.
        self.resize(1366, 820)
        self.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint)
        _icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spg_icon.ico")
        if os.path.isfile(_icon):
            self.setWindowIcon(QtGui.QIcon(_icon))
        self.worker: DriveWorker | None = None
        self._ui_connected = False
        self._connection_admitted = False
        self._connection_access_mode = None
        self._requested_connection_access_mode = None
        self._connection_shutdown_pending = False
        self._telemetry_authoritative = False
        self._telemetry_authority_loss_latched = False
        self._last_telemetry_sequence = 0
        self._last_telemetry_received_monotonic = None
        self._last_telemetry_sample_finished_monotonic = None
        self._energizing_state = False
        self._last_mo = None
        self._motor_write_inflight = False
        self._recorder_view_generation = 1
        self._recorder_manifest_ui_generation = None
        self._recorder_expected_worker_generation = None
        self._recorder_capture_evidence = None
        self._recorder_view_model = None
        self._recorder_view_is_current = False
        self._recorder_statistics_model = None
        self._recorder_statistics_source_view = None
        self._recorder_range_selection = None
        self._recorder_range_source_view = None
        self._persistence_recovery_unknown = False
        self._persistence_audit_summary = {
            "status": "CLEAR", "resolved": False,
            "detail": "No active persistence incident",
            "lock_active": False, "record_id": None, "phase": None,
            "other_active_count": 0, "ledger_error": None,
        }
        self.session_log = session_log.SessionLog(
            capacity=session_log.DEFAULT_CAPACITY)
        self._session_log_last_recorder_state = None
        self.status_monitor_model = status_monitor.StatusMonitorModel()
        self.status_monitor_dialog = None
        self._status_monitor_observer_error = False
        self.system_configuration = (
            system_configuration.SystemConfigurationProjection())
        self.tool_layout = tool_organizer.DEFAULT_LAYOUT
        self.tool_organizer_dialog = None

        central = QtWidgets.QWidget(); central.setObjectName("central")
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(MacTitleBar(self, APP_TITLE))

        content = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(content); root.setContentsMargins(16, 14, 16, 16); root.setSpacing(14)
        self.eas_ribbon = self._build_eas_ribbon()
        root.addWidget(self.eas_ribbon)
        root.addWidget(self._build_header())
        body = QtWidgets.QHBoxLayout(); body.setSpacing(14)
        body.addWidget(self._build_connection_card(), 0)
        body.addWidget(self._build_workspace(), 1)
        root.addLayout(body, 1)
        outer.addWidget(content, 1)

        self._set_connected_ui(False)
        self._telemetry_watchdog = QtCore.QTimer(self)
        self._telemetry_watchdog.setInterval(250)
        self._telemetry_watchdog.timeout.connect(self._check_telemetry_watchdog)
        self._telemetry_watchdog.start()

    # ---- header ----------------------------------------------------------------------
    def _build_header(self):
        f = QtWidgets.QFrame(); f.setObjectName("card")
        h = QtWidgets.QHBoxLayout(f); h.setContentsMargins(22, 14, 22, 14); h.setSpacing(18)
        logo = self._img_label("spg_logo.png", 82)
        if logo is not None:
            h.addWidget(logo)
        brand = QtWidgets.QLabel("AngryYJH Control"); brand.setObjectName("brand")
        brand.setStyleSheet("font-size:34px;font-weight:900;letter-spacing:1px;")
        made = QtWidgets.QLabel("Made By 여재현"); made.setObjectName("madeby")
        made.setStyleSheet("font-size:23px;font-weight:900;color:%s;" % theme.INDIGO)
        col = QtWidgets.QVBoxLayout(); col.setSpacing(4)
        col.addWidget(brand); col.addWidget(made)
        h.addLayout(col)
        bird = self._img_label("angry_bird.png", 112)
        if bird is not None:
            h.addWidget(bird)
        h.addStretch(1)
        self.lbl_persistence_badge = QtWidgets.QLabel(
            "PERSISTENCE LEDGER · CLEAR")
        self.lbl_persistence_badge.setObjectName("pill")
        self.lbl_persistence_badge.setProperty("status", "neutral")
        # Keep the safety badge readable without allowing long ERROR/UNKNOWN
        # text to force the production-styled window beyond 1366 px.  Details
        # remain available in its tooltip and the Status/Log page.
        self.lbl_persistence_badge.setFixedWidth(300)
        self.lbl_persistence_badge.setWordWrap(True)
        self.lbl_persistence_badge.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignCenter)
        self.lbl_persistence_badge.setToolTip(
            "Active P1_CONFIG/P2_LIMITS/Motor persistence ledger plus legacy P2 "
            "record audit. A resolved profile does not certify commutation or motion safety.")
        self.lbl_state = QtWidgets.QLabel("OFFLINE"); self.lbl_state.setObjectName("pill")
        # Stack the two status pills.  Side-by-side long safety text made the
        # header dictate a width larger than common 1366 px bench displays.
        status_col = QtWidgets.QVBoxLayout(); status_col.setSpacing(6)
        status_col.addWidget(self.lbl_persistence_badge)
        status_col.addWidget(
            self.lbl_state, 0, QtCore.Qt.AlignmentFlag.AlignRight)
        h.addLayout(status_col)
        return f

    def _img_label(self, filename, height):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        if not os.path.isfile(path):
            return None
        pix = QtGui.QPixmap(path)
        if pix.isNull():
            return None
        lbl = QtWidgets.QLabel()
        lbl.setPixmap(pix.scaledToHeight(height, QtCore.Qt.TransformationMode.SmoothTransformation))
        return lbl

    # ---- EAS-style contextual ribbon -------------------------------------------------
    def _ribbon_group(self, title):
        frame = QtWidgets.QFrame(); frame.setObjectName("chip")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(9, 7, 9, 7); layout.setSpacing(5)
        label = QtWidgets.QLabel(title); label.setProperty("role", "field")
        layout.addWidget(label)
        return frame, layout

    def _decorate_operation_control(self, widget, operation_id):
        """Bind one visible control to the shared operation/risk contract."""
        spec = operation_catalog.operation_spec(operation_id)
        widget.setProperty("operationId", spec.operation_id)
        widget.setProperty("operationRisk", spec.risk.value)
        existing = widget.toolTip().strip()
        classified = operation_catalog.operation_tooltip(operation_id)
        widget.setToolTip(classified + (("\n\n" + existing) if existing else ""))
        return widget

    def _build_application_menus(self):
        """Build always-visible, local-only top menus.

        Menu activation itself is restricted to navigation or local JSON file
        operations.  Hardware-bound controls remain inside their pages and are
        separately classified/gated.
        """
        widget = QtWidgets.QWidget()
        widget.setObjectName("easApplicationMenus")
        widget.setAutoFillBackground(False)
        widget.setStyleSheet("#easApplicationMenus{background:transparent;}")
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(4)
        self.app_menu_buttons = {}
        self.app_menu_actions = {}
        self.app_menu_actions_by_operation = {}

        handlers = {
            "recorder.workspace.open": self._recorder_open_workspace,
            "recorder.workspace.save": self._recorder_save_workspace,
            "recorder.workspace.save_as": (
                lambda: self._recorder_save_workspace(force_dialog=True)),
            "nav.motion": lambda: self._navigate_tool("motion"),
            "nav.motor": lambda: self._navigate_tool("motor"),
            "nav.feedback": lambda: self._navigate_tool("feedback"),
            "nav.tuning.quick": lambda: self._navigate_tool(
                "tuning", tuning_mode="quick"),
            "nav.tuning.expert": lambda: self._navigate_tool(
                "tuning", tuning_mode="expert"),
            "nav.axis": lambda: self._navigate_tool("axis"),
            "nav.recorder": lambda: self._navigate_tool("recorder"),
            "nav.session_log": lambda: self._navigate_tool("status"),
            "nav.system_config": lambda: self._navigate_tool("system"),
            "session_log.export_json": self._session_log_export_json,
            "session_log.export_csv": self._session_log_export_csv,
            "ui.status_monitor": self._show_status_monitor,
            "ui.tool_organizer": self._show_tool_organizer,
            "ui.capability_guide": self._show_capability_guide,
        }
        for menu_name, operation_ids in operation_catalog.TOP_MENU_OPERATIONS.items():
            button = QtWidgets.QToolButton()
            button.setText(menu_name)
            button.setObjectName("easMenu")
            button.setPopupMode(
                QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
            popup = QtWidgets.QMenu(button)
            need_data_separator_added = False
            for operation_id in operation_ids:
                spec = operation_catalog.operation_spec(operation_id)
                if (spec.status is operation_catalog.OperationStatus.NEED_DATA
                        and not need_data_separator_added
                        and popup.actions()):
                    popup.addSeparator()
                    need_data_separator_added = True
                action = popup.addAction(spec.label)
                action.setData(operation_id)
                action.setToolTip(operation_catalog.operation_tooltip(operation_id))
                action.setStatusTip(spec.summary)
                handler = handlers.get(operation_id)
                action.setEnabled(bool(spec.menu_enabled and handler is not None))
                if action.isEnabled():
                    action.triggered.connect(handler)
                self.app_menu_actions[operation_id] = action
                self.app_menu_actions_by_operation.setdefault(
                    operation_id, []).append(action)
            button.setMenu(popup)
            button.setToolTip(
                "%s · implemented local actions plus explicit NEED-DATA gaps" %
                menu_name)
            layout.addWidget(button)
            self.app_menu_buttons[menu_name] = button
        layout.addStretch(1)
        self.eas_application_menu_row = widget
        # Backward-compatible handle used by Recorder pending-state gating.
        self.btn_rec_menu_workspace = self.app_menu_actions[
            "recorder.workspace.open"]
        return widget

    def _show_capability_guide(self):
        QtWidgets.QMessageBox.information(
            self, "Capability & risk guide",
            "LOCAL UI / LOCAL FILE: no drive command\n"
            "DRIVE READ: identity-bound query only\n"
            "DRIVE STATE: recorder or other drive state changes\n"
            "RAM WRITE: volatile parameter/coordinate mutation\n"
            "ENERGIZES: motor power/current can be applied\n"
            "MOTION: commanded movement is possible\n"
            "PERSIST / SV: non-volatile change\n\n"
            "Opening a page is LOCAL UI. Each action inside the page keeps its "
            "own telemetry, identity, approval, readback and closeout gate.")

    def _navigate_tool(self, tool_id, *, tuning_mode=None):
        """Navigate through the current visibility contract, without I/O."""
        if tool_id not in self.tool_layout.active:
            self._flash(
                "Tool Organizer: %s is hidden in this local session" % tool_id)
            return False
        if tuning_mode is not None:
            self._show_tuning_mode(tuning_mode)
        else:
            self._nav_to(self._TOOL_ID_TO_PAGE_INDEX[tool_id])
        return True

    def _show_tool_organizer(self):
        """Open a modeless, zero-I/O editor for the current session layout."""
        dialog = getattr(self, "tool_organizer_dialog", None)
        if dialog is None:
            dialog = ToolOrganizerDialog(
                self, self.tool_layout, self._apply_tool_layout)
            self.tool_organizer_dialog = dialog
        elif dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()
            return
        else:
            dialog.reset_candidate(self.tool_layout)
        self._position_tool_organizer(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _position_tool_organizer(self, dialog):
        """Place the modeless editor over workspace, not safety/connection UI."""
        dialog.adjustSize()
        workspace_origin = self.workspace_scroll.mapTo(
            self, QtCore.QPoint(0, 0))
        connection_right = self.btn_conn.mapTo(
            self, QtCore.QPoint(0, 0)).x() + self.btn_conn.width()
        left = max(workspace_origin.x(), connection_right + 16)
        available_width = max(
            dialog.minimumWidth(), self.width() - left - 16)
        width = min(720, available_width)
        available_height = max(
            dialog.minimumHeight(), self.height() - 96 - 16)
        height = min(470, available_height)
        top = max(96, self.height() - height - 16)
        dialog.resize(width, height)
        dialog.move(self.mapToGlobal(QtCore.QPoint(left, top)))

    def _show_status_monitor(self):
        """Open one modeless, zero-polling view of accepted telemetry."""
        dialog = getattr(self, "status_monitor_dialog", None)
        if dialog is None:
            dialog = StatusMonitorDialog(
                self, self.status_monitor_model,
                self._status_monitor_replace_config)
            self.status_monitor_dialog = dialog
        elif dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog.model = self.status_monitor_model
        dialog.render(
            self.status_monitor_model.snapshot(),
            observer_error=self._status_monitor_observer_error)
        self._position_status_monitor(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _position_status_monitor(self, dialog):
        """Keep the floating monitor inside workspace and off safety controls."""
        dialog.adjustSize()
        workspace_origin = self.workspace_scroll.mapTo(
            self, QtCore.QPoint(0, 0))
        connection_right = self.btn_conn.mapTo(
            self, QtCore.QPoint(0, 0)).x() + self.btn_conn.width()
        left = max(workspace_origin.x(), connection_right + 16)
        available_width = max(
            dialog.minimumWidth(), self.width() - left - 16)
        width = min(720, available_width)
        available_height = max(
            dialog.minimumHeight(), self.height() - 96 - 16)
        height = min(410, available_height)
        top = max(96, self.height() - height - 16)
        dialog.resize(width, height)
        dialog.move(self.mapToGlobal(QtCore.QPoint(left, top)))

    def _render_status_monitor(self, snapshot=None, *, observer_error=None):
        """Render only if the optional floating adapter already exists."""
        dialog = getattr(self, "status_monitor_dialog", None)
        if dialog is None:
            return
        if observer_error is None:
            observer_error = self._status_monitor_observer_error
        try:
            dialog.model = self.status_monitor_model
            dialog.render(
                self.status_monitor_model.snapshot()
                if snapshot is None else snapshot,
                observer_error=bool(observer_error))
        except Exception:
            # A display-only renderer must never affect core telemetry or MO.
            self._status_monitor_observer_error = True
            try:
                self.status_monitor_model.revoke(
                    "local Status Monitor renderer failure")
            except Exception:
                pass
            try:
                for row in range(dialog.table.rowCount()):
                    item = dialog.table.item(row, 2)
                    if item is not None:
                        item.setText(StatusMonitorDialog._BLANK)
                dialog.lbl_state.setText("OBSERVER ERROR · DISPLAY BLANK")
            except Exception:
                pass

    def _status_monitor_replace_config(self, candidate):
        snapshot = self.status_monitor_model.replace_config(candidate)
        self._status_monitor_observer_error = False
        self._render_status_monitor(snapshot, observer_error=False)
        return snapshot

    def _status_monitor_observer_failed(self):
        """Blank this passive projection without touching core authority."""
        self._status_monitor_observer_error = True
        try:
            snapshot = self.status_monitor_model.revoke(
                "local Status Monitor observer failure")
        except Exception:
            snapshot = None
        self._render_status_monitor(snapshot, observer_error=True)
        return snapshot

    def _status_monitor_activate(self, generation, drive_identity):
        try:
            snapshot = self.status_monitor_model.activate_generation(
                generation, drive_identity)
        except Exception:
            return self._status_monitor_observer_failed()
        self._status_monitor_observer_error = False
        self._render_status_monitor(snapshot, observer_error=False)
        return snapshot

    def _status_monitor_revoke(self, reason):
        try:
            snapshot = self.status_monitor_model.revoke(reason)
        except Exception:
            return self._status_monitor_observer_failed()
        self._status_monitor_observer_error = False
        self._render_status_monitor(snapshot, observer_error=False)
        return snapshot

    def _status_monitor_end(self, reason):
        try:
            snapshot = self.status_monitor_model.end_generation(reason)
        except Exception:
            return self._status_monitor_observer_failed()
        self._status_monitor_observer_error = False
        self._render_status_monitor(snapshot, observer_error=False)
        return snapshot

    def _status_monitor_accept_telemetry(self, telemetry):
        """Observe only after the core has admitted and applied the sample."""
        generation = self.session_log.current_generation
        identity = (getattr(self, "_connected_identity", {}) or {}).get(
            "drive_identity")
        try:
            snapshot = self.status_monitor_model.observe(
                telemetry,
                generation=generation,
                sequence=int(telemetry["telemetry_sequence"]),
                drive_identity=identity,
                fresh=True)
        except Exception:
            return self._status_monitor_observer_failed()
        # The core admitted this sample.  A non-current projection therefore
        # indicates a local monitor contract/integration failure, not ordinary
        # telemetry absence, and must remain diagnostically visible.
        self._status_monitor_observer_error = not snapshot.current
        self._render_status_monitor(
            snapshot,
            observer_error=self._status_monitor_observer_error)
        return snapshot

    def _build_eas_ribbon(self):
        frame = QtWidgets.QFrame(); frame.setObjectName("card")
        outer = QtWidgets.QVBoxLayout(frame)
        outer.setContentsMargins(10, 7, 10, 8); outer.setSpacing(6)

        menu_widget = self._build_application_menus()
        menu_scroll = QtWidgets.QScrollArea()
        menu_scroll.setWidgetResizable(False)
        menu_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        menu_scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        menu_scroll.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        menu_scroll.setFixedHeight(54)
        menu_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea QWidget{background:transparent;}")
        menu_scroll.viewport().setAutoFillBackground(False)
        menu_scroll.viewport().setStyleSheet("background:transparent;")
        menu_scroll.setWidget(menu_widget)

        # Keep the implemented context and lifecycle state visible even when
        # the literal local/EAS menu strip needs horizontal scrolling.
        menu_row_widget = QtWidgets.QWidget()
        menu_row = QtWidgets.QHBoxLayout(menu_row_widget)
        menu_row.setContentsMargins(0, 0, 0, 0); menu_row.setSpacing(7)
        menu_row.addWidget(menu_scroll, 1)
        self.btn_rec_context = QtWidgets.QPushButton("Recording · Immediate v1")
        self.btn_rec_context.setCheckable(True); self.btn_rec_context.setChecked(True)
        self.btn_rec_context.clicked.connect(lambda: self._nav_to(5))
        self.btn_rec_context.setToolTip("Implemented v1: Immediate finite capture only")
        menu_row.addWidget(self.btn_rec_context, 0)
        self.lbl_recorder_ribbon_state = QtWidgets.QLabel("IDLE")
        self.lbl_recorder_ribbon_state.setObjectName("pill")
        self.lbl_recorder_ribbon_state.setMinimumWidth(118)
        self.lbl_recorder_ribbon_state.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        menu_row.addWidget(self.lbl_recorder_ribbon_state, 0)
        outer.addWidget(menu_row_widget)

        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(108)
        body = QtWidgets.QWidget(); groups = QtWidgets.QHBoxLayout(body)
        groups.setContentsMargins(0, 0, 0, 0); groups.setSpacing(7)

        target, layout = self._ribbon_group("TARGET DEVICE")
        self.cmb_ribbon_target = QtWidgets.QComboBox()
        self.cmb_ribbon_target.addItem("Drive01 · current connection")
        self.cmb_ribbon_target.setEnabled(False)
        self.chk_ribbon_lock = QtWidgets.QCheckBox("Lock Target · single-drive")
        self.chk_ribbon_lock.setChecked(True); self.chk_ribbon_lock.setEnabled(False)
        self.chk_ribbon_lock.setToolTip(
            "Implemented by architecture: this app owns one connected target per worker")
        layout.addWidget(self.cmb_ribbon_target); layout.addWidget(self.chk_ribbon_lock)
        groups.addWidget(target)

        files, layout = self._ribbon_group("RECORDER WORKSPACE · LOCAL JSON")
        row = QtWidgets.QHBoxLayout()
        self.btn_rec_open = QtWidgets.QPushButton("Open Local Setup")
        self.btn_rec_save = QtWidgets.QPushButton("Save Local Setup")
        self.btn_rec_save_as = QtWidgets.QPushButton("Save Setup Copy…")
        self.btn_rec_open.clicked.connect(self._recorder_open_workspace)
        self.btn_rec_save.clicked.connect(self._recorder_save_workspace)
        self.btn_rec_save_as.clicked.connect(
            lambda: self._recorder_save_workspace(force_dialog=True))
        for button in (self.btn_rec_open, self.btn_rec_save, self.btn_rec_save_as):
            row.addWidget(button)
        layout.addLayout(row)
        local_note = QtWidgets.QLabel("Not EAS-file compatible")
        local_note.setProperty("role", "hint"); layout.addWidget(local_note)
        groups.addWidget(files)

        timing, layout = self._ribbon_group("RECORDING TIME")
        time_row = QtWidgets.QHBoxLayout()
        self.spn_rec_resolution = QtWidgets.QDoubleSpinBox()
        self.spn_rec_resolution.setRange(1.0, 1_000_000.0)
        self.spn_rec_resolution.setDecimals(1); self.spn_rec_resolution.setValue(200.0)
        self.spn_rec_resolution.setSuffix(" µs requested")
        self.spn_rec_time = QtWidgets.QDoubleSpinBox()
        self.spn_rec_time.setRange(0.001, 60.0)
        self.spn_rec_time.setDecimals(3); self.spn_rec_time.setValue(1.0)
        self.spn_rec_time.setSuffix(" s")
        time_row.addWidget(self.spn_rec_resolution); time_row.addWidget(self.spn_rec_time)
        layout.addLayout(time_row)
        self.lbl_rec_buffer = QtWidgets.QLabel("16K shared buffer · actual timing shown after TS read")
        self.lbl_rec_buffer.setProperty("role", "hint"); layout.addWidget(self.lbl_rec_buffer)
        groups.addWidget(timing)

        selection, layout = self._ribbon_group("SIGNALS / TRIGGER")
        row = QtWidgets.QHBoxLayout()
        self.btn_rec_signals = QtWidgets.QPushButton("Select Personality Signals…")
        self.btn_rec_signals.clicked.connect(self._recorder_signals_clicked)
        self.btn_rec_trigger = QtWidgets.QPushButton("Trigger… · NEED-DATA")
        self.btn_rec_trigger.setEnabled(False)
        self.btn_rec_trigger.setToolTip(
            "Normal/Auto/Interval/analog/digital triggers are intentionally locked; Immediate only")
        row.addWidget(self.btn_rec_signals); row.addWidget(self.btn_rec_trigger)
        layout.addLayout(row)
        mode = QtWidgets.QLabel("Single finite · Immediate · no Rollover")
        mode.setProperty("role", "hint"); layout.addWidget(mode)
        groups.addWidget(selection)

        activation, layout = self._ribbon_group("RECORDER ACTIVATION")
        row = QtWidgets.QHBoxLayout()
        self.btn_rec_start = QtWidgets.QPushButton("Trigger Start · LOCKED")
        self.btn_rec_start.setEnabled(False)
        self.btn_rec_start.setToolTip("PLANNED · configured trigger Start is not implemented")
        self.btn_rec_immediate = QtWidgets.QPushButton("Immediate")
        self.btn_rec_immediate.setObjectName("primary")
        self.btn_rec_immediate.clicked.connect(self._recorder_immediate_clicked)
        self.btn_rec_upload = QtWidgets.QPushButton("Upload Buffer → PC")
        self.btn_rec_upload.clicked.connect(self._recorder_upload_clicked)
        self.btn_rec_stop = QtWidgets.QPushButton("Recorder Stop")
        self.btn_rec_stop.clicked.connect(self._recorder_stop_clicked)
        self.btn_rec_stop.setToolTip("Stops recording only · does NOT stop the motor")
        self._decorate_operation_control(
            self.btn_rec_immediate, "recorder.immediate")
        self._decorate_operation_control(
            self.btn_rec_upload, "recorder.upload")
        self._decorate_operation_control(
            self.btn_rec_stop, "recorder.stop")
        for button in (
                self.btn_rec_start, self.btn_rec_immediate,
                self.btn_rec_upload, self.btn_rec_stop):
            row.addWidget(button)
        layout.addLayout(row)
        # Activation is added outside the horizontal scroll below, alongside
        # DRIVE STOP, so Immediate/Upload/Recorder Stop cannot be clipped.
        activation.setFixedSize(570, 108)

        future, layout = self._ribbon_group("PRESET / MULTI DRIVE")
        self.btn_rec_preset = QtWidgets.QPushButton("Save Setup Copy…")
        self.btn_rec_preset.clicked.connect(
            lambda: self._recorder_save_workspace(force_dialog=True))
        self.chk_rec_multi = QtWidgets.QCheckBox("Multi Drive Recording · NEED-DATA")
        self.chk_rec_multi.setEnabled(False)
        self.chk_rec_multi.setToolTip(
            "Requires drive-clock sync, partial-failure and aligned-upload contracts")
        layout.addWidget(self.btn_rec_preset); layout.addWidget(self.chk_rec_multi)
        groups.addWidget(future)

        stop_group, layout = self._ribbon_group("MOTION SAFETY ESCAPE")
        self.btn_global_stop = QtWidgets.QPushButton("DRIVE STOP")
        self.btn_global_stop.setObjectName("stop")
        self.btn_global_stop.clicked.connect(self._motion_stop_clicked)
        self.btn_global_stop.setToolTip(
            "Queued software ST → MO=0 with readback; not STO/E-stop. "
            "May wait behind an in-process vendor call; Recorder long calls require MO=0/SO=0/VX=0.")
        self._decorate_operation_control(self.btn_global_stop, "drive.stop")
        layout.addWidget(self.btn_global_stop)
        stop_group.setFixedWidth(232)
        stop_group.setFixedHeight(108)
        groups.addStretch(1)

        scroll.setWidget(body)
        ribbon_row = QtWidgets.QHBoxLayout(); ribbon_row.setSpacing(7)
        ribbon_row.addStretch(0)
        ribbon_row.addWidget(scroll, 1)
        ribbon_row.addWidget(activation, 0)
        ribbon_row.addWidget(stop_group, 0)
        outer.addLayout(ribbon_row)
        self.recorder_ribbon_menu = menu_row_widget
        self.recorder_menu_scroll = menu_scroll
        self.recorder_menu_content = menu_widget
        self.recorder_ribbon_scroll = scroll
        self.recorder_activation_group = activation
        self._recorder_workspace_path = None
        self._recorder_last_data = None
        self._recorder_last_resolved = None
        self._recorder_manifest_data = None
        self._recorder_signals_target = None
        self._connected_identity = {}
        self._recorder_ui_state = "IDLE"
        self._recorder_pending_selection = set()
        return frame

    # ---- connection ------------------------------------------------------------------
    def _build_connection_card(self):
        f = theme.HudCard(); f.setFixedWidth(340)
        v = QtWidgets.QVBoxLayout(f)
        v.setContentsMargins(16, 14, 16, 16); v.setSpacing(8)

        # Access authority is always visible, but it shares the card heading
        # instead of consuming another full form row.  The previous standalone
        # row raised the production minimum height beyond 1366×820.
        title_row = QtWidgets.QHBoxLayout(); title_row.setSpacing(8)
        title = QtWidgets.QLabel("CONNECTION")
        title.setProperty("role", "celltitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.cmb_access_mode = QtWidgets.QComboBox()
        self.cmb_access_mode.addItem(
            "READ ONLY",
            OBSERVE_ONLY_ACCESS_MODE)
        self.cmb_access_mode.addItem(
            "SUPERVISED",
            SUPERVISED_ACCESS_MODE)
        self.cmb_access_mode.setFixedWidth(156)
        self.cmb_access_mode.setAccessibleName("Connection Access Mode")
        self.cmb_access_mode.setItemData(
            0,
            "Default. Drive writes are blocked; queries and safe shutdown remain available.",
            QtCore.Qt.ItemDataRole.ToolTipRole)
        self.cmb_access_mode.setItemData(
            1,
            "Explicit supervised authority. Later controls can energize or move the motor.",
            QtCore.Qt.ItemDataRole.ToolTipRole)
        self.cmb_access_mode.currentIndexChanged.connect(
            self._connection_access_mode_selection_changed)
        title_row.addWidget(self.cmb_access_mode)
        v.addLayout(title_row)

        self.cmb_conn = QtWidgets.QComboBox()
        self.cmb_conn.addItems(["Direct Access USB", "Direct Access RS232",
                                "Direct Access UDP", "CAN (Kvaser)", "CAN Gateway (G-MAS)"])
        v.addLayout(self._row("Connection Type", self.cmb_conn))

        self.cmb_port = PortCombo(self.refresh_ports)
        self.btn_port_refresh = QtWidgets.QPushButton("⟳")
        self.btn_port_refresh.setFixedWidth(38)
        self.btn_port_refresh.clicked.connect(self.refresh_ports)
        portrow = QtWidgets.QHBoxLayout(); portrow.setSpacing(6)
        portrow.addWidget(self.cmb_port, 1)
        portrow.addWidget(self.btn_port_refresh)
        v.addLayout(self._row("Serial Port", portrow))

        self.btn_conn = QtWidgets.QPushButton(
            "Connect · Read Only"); self.btn_conn.setObjectName("primary")
        self.btn_conn.clicked.connect(self.toggle_connect)
        v.addWidget(self.btn_conn)

        v.addWidget(self._hline())
        self.lbl_fw = self._kv(v, "Firmware")
        self.lbl_pal = self._kv(v, "PAL")
        self.lbl_boot = self._kv(v, "Boot")
        self.lbl_type = self._kv(v, "Target Class (app)")
        self.lbl_type.setToolTip(
            "APPLICATION CLASSIFICATION · NOT HARDWARE BOARD READBACK")
        self.btn_persistence_audit = QtWidgets.QPushButton(
            "전원 재인가 후 읽기 전용 Audit…")
        self.btn_persistence_audit.setEnabled(False)
        self.btn_persistence_audit.setToolTip(
            "SN[4]/VR/VP/VB/MO/SO/VX/PS/MF와 해당 게인만 조회합니다. "
            "SV·LD·RS·설정 쓰기는 실행하지 않습니다.")
        self.btn_persistence_audit.clicked.connect(
            self._persistence_audit_clicked)
        v.addWidget(self.btn_persistence_audit)
        v.addStretch(1)
        self.refresh_ports()
        return f

    def _row(self, label, inner):
        lay = QtWidgets.QVBoxLayout(); lay.setSpacing(3)
        l = QtWidgets.QLabel(label); l.setProperty("role", "field")
        lay.addWidget(l)
        if isinstance(inner, QtWidgets.QLayout):
            lay.addLayout(inner)
        else:
            lay.addWidget(inner)
        return lay

    def _kv(self, parent_layout, key):
        row = QtWidgets.QHBoxLayout()
        k = QtWidgets.QLabel(key); k.setObjectName("fwkey"); k.setFixedWidth(96)
        val = QtWidgets.QLabel("—"); val.setObjectName("fwval")
        # Vendor/readback text is data, never rich UI markup.  Qt AutoText
        # would otherwise interpret strings such as <b>ONLINE</b> as HTML.
        val.setTextFormat(QtCore.Qt.TextFormat.PlainText)
        row.addWidget(k); row.addWidget(val, 1)
        parent_layout.addLayout(row)
        return val

    def _hline(self):
        line = QtWidgets.QFrame(); line.setFixedHeight(1)
        line.setStyleSheet("background:%s;" % theme.BORDER)
        return line

    # ---- motion dashboard ------------------------------------------------------------
    def _build_motion_card(self):
        f = theme.HudCard()
        v = QtWidgets.QVBoxLayout(f); v.setContentsMargins(16, 14, 16, 16); v.setSpacing(12)

        top = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("SINGLE AXIS MOTION"); title.setProperty("role", "celltitle")
        top.addWidget(title); top.addStretch(1)
        self.lbl_motor = QtWidgets.QLabel("MOTOR STATE UNKNOWN"); self.lbl_motor.setObjectName("pill")
        top.addWidget(self.lbl_motor)
        v.addLayout(top)

        grid = QtWidgets.QGridLayout(); grid.setSpacing(10)
        (b1, self.m_pos, self.m_pos_sub) = metric("POSITION  [cnt]")
        (b2, self.m_perr, _) = metric("POS. ERROR  [cnt]")
        (b3, self.m_vel, self.m_vel_sub) = metric("VELOCITY  [cnt/sec]")
        (b4, self.m_iq, _) = metric("ACTIVE CURRENT  [A]")
        grid.addWidget(b1, 0, 0); grid.addWidget(b2, 0, 1)
        grid.addWidget(b3, 1, 0); grid.addWidget(b4, 1, 1)
        v.addLayout(grid)

        v.addWidget(self._hline())
        actionrow = QtWidgets.QHBoxLayout(); actionrow.setSpacing(8)
        self.btn_motion_stop = QtWidgets.QPushButton("STOP + Disable  ·  ST → MO=0")
        self.btn_motion_stop.setEnabled(False)
        self.btn_motion_stop.setStyleSheet(
            "QPushButton{background:#8f2635;color:white;font-weight:900;}"
            "QPushButton:disabled{background:#26384b;color:#71849a;}")
        self.btn_motion_stop.clicked.connect(self._motion_stop_clicked)
        self._decorate_operation_control(self.btn_motion_stop, "drive.stop")
        actionrow.addWidget(self.btn_motion_stop)
        self.btn_zero = QtWidgets.QPushButton("Set Session Zero  ·  PX=0")
        self.btn_zero.clicked.connect(self.zero_position)
        self._decorate_operation_control(self.btn_zero, "session.zero")
        actionrow.addWidget(self.btn_zero); actionrow.addStretch(1)
        v.addLayout(actionrow)
        note = QtWidgets.QLabel(
            "Session Zero: 현재 위치를 이번 연결의 임시 좌표 0으로 설정합니다. 모터 OFF·정지·무전류를 "
            "다시 확인하고 PX=0 되읽기까지 수행하며, 모터는 움직이지 않고 SV도 실행하지 않습니다. "
            "EnDat 2.2의 영구 기계 원점은 Feedback → Encoder Maintenance에서만 변경합니다.")
        note.setProperty("role", "hint"); note.setWordWrap(True)
        v.addWidget(note)

        v.addWidget(self._hline())
        motion_title = QtWidgets.QLabel(
            "FINITE POSITION MOVE v1  ·  PTP / RAM LIMITS / AUTO-DISABLE")
        motion_title.setProperty("role", "field"); v.addWidget(motion_title)
        self.motion_gate = QtWidgets.QLabel(
            "LIVE LOCKED — connect, Session Zero, Commutation Signature GREEN, "
            "and this-run safety checks are required.")
        self.motion_gate.setProperty("role", "hint")
        self.motion_gate.setWordWrap(True); v.addWidget(self.motion_gate)

        form = QtWidgets.QGridLayout(); form.setHorizontalSpacing(10); form.setVerticalSpacing(6)
        self.cmb_motion_mode = QtWidgets.QComboBox()
        self.cmb_motion_mode.addItem("Relative from fresh PX", "relative")
        self.cmb_motion_mode.addItem("Absolute from Session Zero", "session_absolute")
        self.spn_motion_target = QtWidgets.QDoubleSpinBox()
        self.spn_motion_target.setRange(-0.25, 0.25); self.spn_motion_target.setDecimals(4)
        self.spn_motion_target.setSingleStep(0.005); self.spn_motion_target.setValue(0.01)
        self.spn_motion_speed = QtWidgets.QDoubleSpinBox()
        self.spn_motion_speed.setRange(0.5, single_axis_motion.MAX_SPEED_RPM)
        self.spn_motion_speed.setDecimals(1); self.spn_motion_speed.setValue(5.0)
        self.spn_motion_accel = QtWidgets.QDoubleSpinBox()
        self.spn_motion_accel.setRange(1.0, single_axis_motion.MAX_ACCEL_RPM_S)
        self.spn_motion_accel.setDecimals(1); self.spn_motion_accel.setValue(30.0)
        self.spn_motion_envelope = QtWidgets.QDoubleSpinBox()
        self.spn_motion_envelope.setRange(0.01, single_axis_motion.MAX_TRAVEL_LIMIT_REV)
        self.spn_motion_envelope.setDecimals(3); self.spn_motion_envelope.setValue(0.25)
        self.spn_motion_current = QtWidgets.QDoubleSpinBox()
        self.spn_motion_current.setRange(
            single_axis_motion.MIN_CURRENT_CAP_A,
            single_axis_motion.MAX_CURRENT_CAP_A)
        self.spn_motion_current.setDecimals(2); self.spn_motion_current.setValue(1.30)
        fields = (
            ("Target [rev]", self.spn_motion_target),
            ("Speed cap [rpm]", self.spn_motion_speed),
            ("Acceleration cap [rpm/s]", self.spn_motion_accel),
            ("Session travel envelope [±rev]", self.spn_motion_envelope),
            ("Temporary current cap [A peak]", self.spn_motion_current),
        )
        form.addWidget(QtWidgets.QLabel("Target mode"), 0, 0)
        form.addWidget(self.cmb_motion_mode, 0, 1)
        for row, (label, widget) in enumerate(fields, start=1):
            form.addWidget(QtWidgets.QLabel(label), row, 0)
            form.addWidget(widget, row, 1)
        v.addLayout(form)

        self.chk_motion_operator = QtWidgets.QCheckBox("Operator present · area clear · load restrained")
        self.chk_motion_estop = QtWidgets.QCheckBox("Independent E-stop/STO tested for this run")
        self.chk_motion_limits = QtWidgets.QCheckBox("Direction and allowed travel envelope physically verified")
        for check in (self.chk_motion_operator, self.chk_motion_estop, self.chk_motion_limits):
            check.stateChanged.connect(self._update_motion_controls)
            v.addWidget(check)
        self.btn_motion_run = QtWidgets.QPushButton(
            "Run finite PTP move  ·  always STOP/MO=0 after exit")
        self.btn_motion_run.setEnabled(False)
        self.btn_motion_run.clicked.connect(self._motion_run_clicked)
        self._decorate_operation_control(self.btn_motion_run, "motion.ptp.run")
        v.addWidget(self.btn_motion_run)
        locked = QtWidgets.QLabel(
            "LOCKED IN v1: endless JV Jog · Run Held · Homing · Current · Sine Reference. "
            "These need drive-level limit/watchdog and field evidence; software STOP is not STO.")
        locked.setProperty("role", "hint"); locked.setWordWrap(True); v.addWidget(locked)

        v.addWidget(self._build_single_axis_authority_frame())
        v.addWidget(self._build_axis_enable_contract_frame())
        v.addWidget(self._build_axis_drive_mode_frame())
        v.addWidget(self._build_axis_current_reference_frame())
        v.addWidget(self._build_axis_digital_inputs_frame())
        v.addWidget(self._build_axis_digital_outputs_frame())

        self._motion_signature_green = False
        self._motion_signature_token = None
        self._motion_signature_generation = None
        self._motion_session_zero_confirmed = False
        self._motion_inflight = False
        self._motion_stop_pending = False
        self._motion_config_unknown = False
        self._axis_summary_data = {}
        v.addStretch(1)
        return f

    def _build_axis_enable_contract_frame(self):
        """Build a zero-I/O, fail-closed Enable/Disable contract panel."""
        frame = QtWidgets.QFrame()
        frame.setObjectName("chip")
        self.axis_enable_contract_frame = frame
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel(
            "SINGLE AXIS ENABLE / DISABLE - DRIVE-REPORTED MODEL v0.1")
        title.setProperty("role", "field")
        title.setMinimumWidth(0)
        title.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred)
        head.addWidget(title)
        head.addStretch(1)
        self.lbl_axis_enable_state = QtWidgets.QLabel(
            "UNKNOWN - ENABLE LOCKED")
        self.lbl_axis_enable_state.setObjectName("pill")
        self.lbl_axis_enable_state.setProperty("on", "false")
        self.lbl_axis_enable_state.setProperty("status", "neutral")
        self.lbl_axis_enable_state.setMinimumWidth(0)
        self.lbl_axis_enable_state.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred)
        head.addWidget(self.lbl_axis_enable_state)
        layout.addLayout(head)

        self.lbl_axis_enable_contract = QtWidgets.QLabel(
            single_axis_enable_contract.EVIDENCE_LABEL + " - "
            + single_axis_enable_contract.ENABLE_BOUNDARY)
        self.lbl_axis_enable_contract.setProperty("role", "hint")
        self.lbl_axis_enable_contract.setWordWrap(True)
        self.lbl_axis_enable_contract.setMinimumWidth(0)
        self.lbl_axis_enable_contract.setMinimumHeight(96)
        layout.addWidget(self.lbl_axis_enable_contract)

        controls = QtWidgets.QHBoxLayout()
        self.btn_axis_enable_locked = QtWidgets.QPushButton(
            "Enable - LOCKED / NEED-DATA (MO=1)")
        self.btn_axis_enable_locked.setEnabled(False)
        self.btn_axis_enable_locked.setMinimumWidth(0)
        self.btn_axis_enable_locked.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Fixed)
        self.btn_axis_enable_locked.setToolTip(
            "No executable MO=1 handler exists. Enable requires a separately "
            "commissioned energization contract and exact user authority.")
        self._decorate_operation_control(
            self.btn_axis_enable_locked, "motor.enable")
        controls.addWidget(self.btn_axis_enable_locked)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.lbl_axis_disable_route = QtWidgets.QLabel(
            "STOP + DISABLE uses the existing safety escape: "
            "ST -> MO=0 -> terminal readback. "
            "Use DRIVE STOP or Motion STOP; software STOP is not independent "
            "STO/E-stop.")
        self.lbl_axis_disable_route.setProperty("role", "hint")
        self.lbl_axis_disable_route.setWordWrap(True)
        self.lbl_axis_disable_route.setMinimumWidth(0)
        layout.addWidget(self.lbl_axis_disable_route)

        self.lbl_axis_enable_detail = QtWidgets.QLabel(
            "No current admitted safety snapshot")
        self.lbl_axis_enable_detail.setProperty("role", "hint")
        self.lbl_axis_enable_detail.setWordWrap(True)
        self.lbl_axis_enable_detail.setMinimumWidth(0)
        self.lbl_axis_enable_detail.setMinimumHeight(68)
        layout.addWidget(self.lbl_axis_enable_detail)
        return frame

    def _build_single_axis_authority_frame(self):
        """Build a local-only map of documented EAS Single Axis controls."""
        frame = QtWidgets.QFrame()
        frame.setObjectName("chip")
        self.single_axis_authority_frame = frame
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        self._single_axis_authority = (
            single_axis_authority_evidence.build_evidence_snapshot())
        title = QtWidgets.QLabel(
            "SINGLE AXIS CONTROLS - DOCUMENTED AUTHORITY MAP")
        title.setProperty("role", "field")
        layout.addWidget(title)

        self.single_axis_authority_banner = QtWidgets.QLabel(
            self._single_axis_authority.boundary)
        self.single_axis_authority_banner.setProperty("role", "hint")
        self.single_axis_authority_banner.setWordWrap(True)
        self.single_axis_authority_banner.setMinimumWidth(0)
        self.single_axis_authority_banner.setMinimumHeight(82)
        self.single_axis_authority_banner.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred)
        layout.addWidget(self.single_axis_authority_banner)
        self.single_axis_authority_status = QtWidgets.QLabel()
        self.single_axis_authority_status.setProperty("role", "field")
        self.single_axis_authority_status.setWordWrap(True)
        self.single_axis_authority_status.setMinimumWidth(0)
        self.single_axis_authority_status.setMinimumHeight(100)
        self.single_axis_authority_status.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred)
        layout.addWidget(self.single_axis_authority_status)

        selector_layout = QtWidgets.QHBoxLayout()
        selector_label = QtWidgets.QLabel("Documented Single Axis section")
        selector_label.setProperty("role", "field")
        self.single_axis_authority_section = QtWidgets.QComboBox()
        self.single_axis_authority_section.setEditable(False)
        self.single_axis_authority_section.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy
            .AdjustToMinimumContentsLengthWithIcon)
        self.single_axis_authority_section.setMinimumContentsLength(20)
        self.single_axis_authority_section.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Fixed)
        for section in self._single_axis_authority.sections:
            self.single_axis_authority_section.addItem(
                "%s - %s" % (section.label, section.reference),
                section.key)
        selector_layout.addWidget(selector_label)
        selector_layout.addWidget(self.single_axis_authority_section, 1)
        layout.addLayout(selector_layout)

        self.single_axis_authority_table = QtWidgets.QTableWidget(0, 4)
        self.single_axis_authority_table.setObjectName(
            "expertEvidenceTable")
        self.single_axis_authority_table.setStyleSheet(
            "QTableWidget#expertEvidenceTable { font-size: 12px; } "
            "QTableWidget#expertEvidenceTable QHeaderView::section "
            "{ font-size: 12px; }")
        self.single_axis_authority_table.setHorizontalHeaderLabels((
            "EAS AREA / CONTROL",
            "DOCUMENTED ROLE",
            "RISK / ACCESS",
            "STATUS / BOUNDARY",
        ))
        for column, tooltip in enumerate((
                "Documented EAS area/control; not an executable control.",
                "Installed-manual role only; not current state or a result.",
                "Physical/software risk plus inspect-only application access.",
                "Evidence status plus missing execution preconditions.",
        )):
            self.single_axis_authority_table.horizontalHeaderItem(
                column).setToolTip(tooltip)
        self.single_axis_authority_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.single_axis_authority_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.single_axis_authority_table.setFocusPolicy(
            QtCore.Qt.FocusPolicy.NoFocus)
        self.single_axis_authority_table.setWordWrap(True)
        self.single_axis_authority_table.setAlternatingRowColors(True)
        self.single_axis_authority_table.setMinimumWidth(0)
        self.single_axis_authority_table.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Expanding)
        self.single_axis_authority_table.verticalHeader().setVisible(False)
        header = self.single_axis_authority_table.horizontalHeader()
        for column in (0, 1, 2):
            header.setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.single_axis_authority_table.setColumnWidth(0, 190)
        self.single_axis_authority_table.setColumnWidth(1, 300)
        self.single_axis_authority_table.setColumnWidth(2, 220)
        self.single_axis_authority_table.setMinimumHeight(230)
        layout.addWidget(self.single_axis_authority_table, 1)

        self.single_axis_authority_warnings = QtWidgets.QLabel(
            "PERSISTENT WARNINGS - " + " | ".join(
                self._single_axis_authority.persistent_warnings))
        self.single_axis_authority_missing = QtWidgets.QLabel(
            "MISSING EVIDENCE / NEED-DATA - " + " | ".join(
                self._single_axis_authority.missing_evidence))
        for detail in (
                self.single_axis_authority_warnings,
                self.single_axis_authority_missing):
            detail.setProperty("role", "hint")
            detail.setWordWrap(True)
            detail.setMinimumWidth(0)
            detail.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Preferred)
            layout.addWidget(detail)

        sources = {
            source.key: source.sha256
            for source in self._single_axis_authority.sources
        }
        self.single_axis_authority_sources = QtWidgets.QLabel(
            "SOURCES - %d frozen identities\n"
            "EAS Drive Setup SHA-256 %s\n"
            "Single Axis overview SHA-256 %s\n"
            "Single Axis areas SHA-256 %s" % (
                len(sources),
                sources["drive_setup_html"],
                sources["single_axis_overview_image"],
                sources["single_axis_areas_image"]))
        self.single_axis_authority_sources.setProperty("role", "hint")
        self.single_axis_authority_sources.setWordWrap(True)
        self.single_axis_authority_sources.setMinimumWidth(0)
        self.single_axis_authority_sources.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred)
        layout.addWidget(self.single_axis_authority_sources)

        self.single_axis_authority_section.currentIndexChanged.connect(
            self._refresh_single_axis_authority_panel)
        self._refresh_single_axis_authority_panel()
        return frame

    def _refresh_single_axis_authority_panel(self, *_args):
        """Render one immutable Single Axis documentation section."""
        if not hasattr(self, "_single_axis_authority"):
            return
        section = single_axis_authority_evidence.section_evidence(
            self.single_axis_authority_section.currentData())
        self.single_axis_authority_status.setText(
            "AUTHORITY %s - EVIDENCE STATUS %s - %s - "
            "%d documented groups - NOT CURRENT / NOT EXECUTED - "
            "controls unavailable / not executable" % (
                self._single_axis_authority.authority,
                self._single_axis_authority.model_status,
                section.reference,
                len(section.items)))
        self.single_axis_authority_table.setRowCount(len(section.items))
        for row, item in enumerate(section.items):
            values = (
                item.label,
                "%s - %s" % (item.control, item.documented_effect),
                "%s - %s" % (item.risk_class, item.access),
                "%s - %s" % (item.evidence_status, item.condition),
            )
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(value)
                cell.setToolTip(value)
                self.single_axis_authority_table.setItem(row, column, cell)
        self.single_axis_authority_table.resizeRowsToContents()

    def _build_axis_drive_mode_frame(self):
        """Build the explicit one-query UM read-only panel."""
        frame = QtWidgets.QFrame()
        frame.setObjectName("chip")
        self.axis_drive_mode_frame = frame
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel(
            "DRIVE MODE (UM) · READ-ONLY SNAPSHOT v0.1")
        title.setProperty("role", "field")
        head.addWidget(title)
        head.addStretch(1)
        self.lbl_axis_drive_mode_state = QtWidgets.QLabel("UNKNOWN")
        self.lbl_axis_drive_mode_state.setObjectName("pill")
        self.lbl_axis_drive_mode_state.setProperty("on", "false")
        self.lbl_axis_drive_mode_state.setProperty("status", "neutral")
        head.addWidget(self.lbl_axis_drive_mode_state)
        layout.addLayout(head)

        self.lbl_axis_drive_mode_contract = QtWidgets.QLabel(
            single_axis_drive_mode.EVIDENCE_LABEL
            + " · EXPLICIT REFRESH ONLY · CHANGE LOCKED / NEED-DATA · "
              "UM IS NON-VOLATILE · MOTOR MUST BE OFF FOR ASSIGNMENT · "
              "NO CHANGE WITHOUT EXACT READBACK + ROLLBACK AUTHORITY")
        self.lbl_axis_drive_mode_contract.setProperty("role", "hint")
        self.lbl_axis_drive_mode_contract.setWordWrap(True)
        self.lbl_axis_drive_mode_contract.setMinimumWidth(0)
        self.lbl_axis_drive_mode_contract.setMinimumHeight(96)
        layout.addWidget(self.lbl_axis_drive_mode_contract)

        current = QtWidgets.QHBoxLayout()
        current_label = QtWidgets.QLabel("Current drive report")
        current_label.setProperty("role", "field")
        current.addWidget(current_label)
        self.lbl_axis_drive_mode_value = QtWidgets.QLabel("—")
        self.lbl_axis_drive_mode_value.setProperty("role", "value")
        current.addWidget(self.lbl_axis_drive_mode_value)
        current.addSpacing(12)
        self.lbl_axis_drive_mode_reference = QtWidgets.QLabel("—")
        self.lbl_axis_drive_mode_reference.setProperty("role", "hint")
        self.lbl_axis_drive_mode_reference.setWordWrap(True)
        current.addWidget(self.lbl_axis_drive_mode_reference, 1)
        layout.addLayout(current)

        self.axis_drive_mode_table = QtWidgets.QTableWidget(5, 4)
        self.axis_drive_mode_table.setObjectName("expertEvidenceTable")
        self.axis_drive_mode_table.setStyleSheet(
            "QTableWidget { font-family: 'Segoe UI'; font-size: 11px; }")
        self.axis_drive_mode_table.setHorizontalHeaderLabels((
            "UM",
            "DOCUMENTED MODE",
            "HIGHEST CONTROL LOOP",
            "REFERENCE / CONSEQUENCE",
        ))
        self.axis_drive_mode_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.axis_drive_mode_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.axis_drive_mode_table.setFocusPolicy(
            QtCore.Qt.FocusPolicy.NoFocus)
        self.axis_drive_mode_table.setAlternatingRowColors(True)
        self.axis_drive_mode_table.verticalHeader().setVisible(False)
        header = self.axis_drive_mode_table.horizontalHeader()
        header.setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.axis_drive_mode_table.setMinimumWidth(0)
        self.axis_drive_mode_table.setMinimumHeight(225)
        for row, spec in enumerate(
                single_axis_drive_mode.MODE_SPECS.values()):
            values = (
                "UM=%d" % spec.value,
                spec.name,
                spec.highest_control_loop,
                "%s · %s" % (
                    spec.reference_contract, spec.consequence),
            )
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip(value)
                self.axis_drive_mode_table.setItem(row, column, item)
        self.axis_drive_mode_table.resizeRowsToContents()
        layout.addWidget(self.axis_drive_mode_table)

        action = QtWidgets.QHBoxLayout()
        self.btn_axis_drive_mode_refresh = QtWidgets.QPushButton(
            "Refresh Drive Mode · READ ONLY")
        self.btn_axis_drive_mode_refresh.setEnabled(False)
        self.btn_axis_drive_mode_refresh.clicked.connect(
            self._refresh_axis_drive_mode_clicked)
        self._decorate_operation_control(
            self.btn_axis_drive_mode_refresh,
            "axis.drive_mode.refresh")
        action.addWidget(self.btn_axis_drive_mode_refresh)
        action.addStretch(1)
        layout.addLayout(action)

        self.lbl_axis_drive_mode_detail = QtWidgets.QLabel(
            "OFFLINE · no current identity-bound UM snapshot")
        self.lbl_axis_drive_mode_detail.setProperty("role", "hint")
        self.lbl_axis_drive_mode_detail.setWordWrap(True)
        self.lbl_axis_drive_mode_detail.setMinimumWidth(0)
        layout.addWidget(self.lbl_axis_drive_mode_detail)
        self._reset_axis_drive_mode(
            "OFFLINE · no current identity-bound UM snapshot")
        return frame

    def _reset_axis_drive_mode(self, reason):
        """Blank the current UM observation without changing authority."""
        self._axis_drive_mode_snapshot = None
        if not hasattr(self, "lbl_axis_drive_mode_state"):
            return
        self.lbl_axis_drive_mode_state.setText("UNKNOWN")
        self.lbl_axis_drive_mode_state.setProperty("on", "false")
        self.lbl_axis_drive_mode_state.setProperty("status", "neutral")
        self._restyle(self.lbl_axis_drive_mode_state)
        self.lbl_axis_drive_mode_value.setText("—")
        self.lbl_axis_drive_mode_reference.setText("—")
        for row in range(self.axis_drive_mode_table.rowCount()):
            item = self.axis_drive_mode_table.item(row, 0)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, None)
            font = item.font()
            font.setBold(False)
            item.setFont(font)
        self.lbl_axis_drive_mode_detail.setText(
            str(reason or "Drive-mode snapshot unavailable"))

    def _refresh_axis_drive_mode_clicked(self):
        """Request the bounded UM reader; never synthesize a mode."""
        current = bool(
            self.worker
            and self.worker.isRunning()
            and getattr(self, "_connection_admitted", False)
            and getattr(self, "_ui_connected", False)
            and getattr(self, "_telemetry_authoritative", False)
            and not getattr(self, "_energizing_state", False)
            and not getattr(self, "_connection_shutdown_pending", False))
        if not current:
            self._reset_axis_drive_mode(
                "Current identity/telemetry authority is unavailable")
            return
        self._reset_axis_drive_mode(
            "Reading one UM query in the worker")
        self.lbl_axis_drive_mode_state.setText("READING")
        self.worker.refresh_axis_drive_mode()

    def _on_axis_drive_mode(self, snapshot):
        """Render only a canonical current-session UM observation."""
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        canonical = None
        if isinstance(
                snapshot,
                single_axis_drive_mode.DriveModeSnapshot):
            canonical = (
                single_axis_drive_mode.decode_drive_mode_snapshot(
                    snapshot.raw,
                    sample_duration_s=snapshot.sample_duration_s,
                ))
        current_source = bool(
            not getattr(self, "_connection_shutdown_pending", False)
            and getattr(self, "_connection_admitted", False)
            and getattr(self, "_ui_connected", False)
            and getattr(self, "_telemetry_authoritative", False)
            and not getattr(self, "_energizing_state", False)
            and self.worker
            and self.worker.isRunning())
        if (not current_source
                or not isinstance(
                    snapshot,
                    single_axis_drive_mode.DriveModeSnapshot)
                or snapshot.state != single_axis_drive_mode.CURRENT
                or canonical is None
                or canonical.state != single_axis_drive_mode.CURRENT
                or snapshot != canonical):
            reason = (
                getattr(snapshot, "reason", "")
                or "Noncanonical or non-current drive-mode snapshot")
            self._reset_axis_drive_mode(reason)
            return

        snapshot = canonical
        self._axis_drive_mode_snapshot = snapshot
        self.lbl_axis_drive_mode_value.setText(
            "UM=%d · %s" % (snapshot.mode.value, snapshot.mode.name))
        self.lbl_axis_drive_mode_reference.setText(
            "%s · %s" % (
                snapshot.mode.reference_contract,
                snapshot.mode.consequence,
            ))
        for row in range(self.axis_drive_mode_table.rowCount()):
            item = self.axis_drive_mode_table.item(row, 0)
            is_current = (
                item.text() == "UM=%d" % snapshot.mode.value)
            item.setData(
                QtCore.Qt.ItemDataRole.UserRole,
                "CURRENT" if is_current else None)
            font = item.font()
            font.setBold(is_current)
            item.setFont(font)
        self.lbl_axis_drive_mode_state.setText(
            "CURRENT · DRIVE READ ONLY")
        self.lbl_axis_drive_mode_state.setProperty("on", "false")
        self.lbl_axis_drive_mode_state.setProperty("status", "neutral")
        self._restyle(self.lbl_axis_drive_mode_state)
        self.lbl_axis_drive_mode_detail.setText(
            "Identity-bound explicit UM snapshot · acquisition %.1f ms · "
            "documented map only · NO MODE CHANGE / ENABLE / REFERENCE / "
            "MOTION" % (1000.0 * snapshot.sample_duration_s))

    def _build_axis_current_reference_frame(self):
        """Build the bounded current-reference read-only panel."""
        frame = QtWidgets.QFrame()
        frame.setObjectName("chip")
        self.axis_current_reference_frame = frame
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel(
            "CURRENT REFERENCE · READ-ONLY SNAPSHOT v0.1")
        title.setProperty("role", "field")
        head.addWidget(title)
        head.addStretch(1)
        self.lbl_axis_current_reference_state = QtWidgets.QLabel("UNKNOWN")
        self.lbl_axis_current_reference_state.setObjectName("pill")
        self.lbl_axis_current_reference_state.setProperty("on", "false")
        self.lbl_axis_current_reference_state.setProperty("status", "neutral")
        head.addWidget(self.lbl_axis_current_reference_state)
        layout.addLayout(head)

        self.lbl_axis_current_reference_contract = QtWidgets.QLabel(
            single_axis_current_reference.EVIDENCE_LABEL
            + " · EXPLICIT REFRESH ONLY · COMMAND LOCKED / NEED-DATA · "
              "TC REQUIRES MO=1 + SO=1 AND FORCES CURRENT LOOP · "
              "NO COMMAND WITHOUT FIELD ENVELOPE + WATCHDOG + ST → MO=0 "
              "CLOSEOUT")
        self.lbl_axis_current_reference_contract.setProperty("role", "hint")
        self.lbl_axis_current_reference_contract.setWordWrap(True)
        self.lbl_axis_current_reference_contract.setMinimumWidth(0)
        self.lbl_axis_current_reference_contract.setMinimumHeight(112)
        layout.addWidget(self.lbl_axis_current_reference_contract)

        self.lbl_axis_current_reference_motor = QtWidgets.QLabel("—")
        self.lbl_axis_current_reference_motor.setProperty("role", "value")
        self.lbl_axis_current_reference_motor.setWordWrap(True)
        layout.addWidget(self.lbl_axis_current_reference_motor)

        rows = (
            ("TC", "Torque/current command · amperes · query only"),
            ("IQ", "Active current component · torque producing"),
            ("ID", "Reactive current component · normally regulated to zero"),
            ("CL[1]", "Continuous motor phase-current limit"),
            ("PL[1]", "Peak current limit"),
            ("LC", "Current-limit flag · SR bit 13 cross-check"),
            ("MC", "Factory drive maximum phase-current rating"),
        )
        self.axis_current_reference_table = QtWidgets.QTableWidget(
            len(rows), 3)
        self.axis_current_reference_table.setObjectName("expertEvidenceTable")
        self.axis_current_reference_table.setStyleSheet(
            "QTableWidget { font-family: 'Segoe UI'; font-size: 11px; }")
        self.axis_current_reference_table.setHorizontalHeaderLabels((
            "DRIVE ITEM",
            "CURRENT READBACK",
            "DOCUMENTED MEANING",
        ))
        self.axis_current_reference_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.axis_current_reference_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.axis_current_reference_table.setFocusPolicy(
            QtCore.Qt.FocusPolicy.NoFocus)
        self.axis_current_reference_table.setAlternatingRowColors(True)
        self.axis_current_reference_table.verticalHeader().setVisible(False)
        header = self.axis_current_reference_table.horizontalHeader()
        header.setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.axis_current_reference_table.setMinimumWidth(0)
        self.axis_current_reference_table.setMinimumHeight(300)
        for row, (item_name, meaning) in enumerate(rows):
            for column, value in enumerate((item_name, "—", meaning)):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip(value)
                self.axis_current_reference_table.setItem(row, column, item)
        self.axis_current_reference_table.resizeRowsToContents()
        layout.addWidget(self.axis_current_reference_table)

        actions = QtWidgets.QHBoxLayout()
        self.btn_axis_current_reference_refresh = QtWidgets.QPushButton(
            "Refresh Current Reference · READ ONLY")
        self.btn_axis_current_reference_refresh.setEnabled(False)
        self.btn_axis_current_reference_refresh.clicked.connect(
            self._refresh_axis_current_reference_clicked)
        self._decorate_operation_control(
            self.btn_axis_current_reference_refresh,
            "axis.current_reference.refresh")
        actions.addWidget(self.btn_axis_current_reference_refresh)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.lbl_axis_current_reference_detail = QtWidgets.QLabel(
            "OFFLINE · no current identity-bound current-reference snapshot")
        self.lbl_axis_current_reference_detail.setProperty("role", "hint")
        self.lbl_axis_current_reference_detail.setWordWrap(True)
        self.lbl_axis_current_reference_detail.setMinimumWidth(0)
        layout.addWidget(self.lbl_axis_current_reference_detail)
        self._reset_axis_current_reference(
            "OFFLINE · no current identity-bound current-reference snapshot")
        return frame

    def _reset_axis_current_reference(self, reason):
        """Blank the current-reference observation without granting authority."""
        self._axis_current_reference_snapshot = None
        if not hasattr(self, "lbl_axis_current_reference_state"):
            return
        self.lbl_axis_current_reference_state.setText("UNKNOWN")
        self.lbl_axis_current_reference_state.setProperty("on", "false")
        self.lbl_axis_current_reference_state.setProperty(
            "status", "neutral")
        self._restyle(self.lbl_axis_current_reference_state)
        self.lbl_axis_current_reference_motor.setText("—")
        for row in range(self.axis_current_reference_table.rowCount()):
            self.axis_current_reference_table.item(row, 1).setText("—")
        self.lbl_axis_current_reference_detail.setText(
            str(reason or "Current-reference snapshot unavailable"))

    def _refresh_axis_current_reference_clicked(self):
        """Request only the typed, bounded current-reference read job."""
        current = bool(
            self.worker
            and self.worker.isRunning()
            and getattr(self, "_connection_admitted", False)
            and getattr(self, "_ui_connected", False)
            and getattr(self, "_telemetry_authoritative", False)
            and not getattr(self, "_energizing_state", False)
            and not getattr(self, "_connection_shutdown_pending", False))
        if not current:
            self._reset_axis_current_reference(
                "Current identity/telemetry authority is unavailable")
            return
        self._reset_axis_current_reference(
            "Reading bounded current-reference query set in the worker")
        self.lbl_axis_current_reference_state.setText("READING")
        self.worker.refresh_axis_current_reference()

    def _on_axis_current_reference(self, snapshot):
        """Render only a canonical current-session read-only snapshot."""
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        canonical = None
        if isinstance(
                snapshot,
                single_axis_current_reference.CurrentReferenceSnapshot):
            canonical = (
                single_axis_current_reference
                .decode_current_reference_snapshot(
                    snapshot.raw,
                    sample_duration_s=snapshot.sample_duration_s,
                ))
        current_source = bool(
            not getattr(self, "_connection_shutdown_pending", False)
            and getattr(self, "_connection_admitted", False)
            and getattr(self, "_ui_connected", False)
            and getattr(self, "_telemetry_authoritative", False)
            and not getattr(self, "_energizing_state", False)
            and self.worker
            and self.worker.isRunning())
        if (not current_source
                or not isinstance(
                    snapshot,
                    single_axis_current_reference.CurrentReferenceSnapshot)
                or snapshot.state != single_axis_current_reference.CURRENT
                or canonical is None
                or canonical.state != single_axis_current_reference.CURRENT
                or snapshot != canonical):
            reason = (
                getattr(snapshot, "reason", "")
                or "Noncanonical or non-current current-reference snapshot")
            self._reset_axis_current_reference(reason)
            return

        snapshot = canonical
        self._axis_current_reference_snapshot = snapshot
        self.lbl_axis_current_reference_state.setText(
            "CURRENT · DRIVE READ ONLY")
        self.lbl_axis_current_reference_state.setProperty("on", "false")
        self.lbl_axis_current_reference_state.setProperty(
            "status", "neutral")
        self._restyle(self.lbl_axis_current_reference_state)
        self.lbl_axis_current_reference_motor.setText(
            "%s · UM=%d %s" % (
                snapshot.motor_state,
                snapshot.mode_value,
                snapshot.mode_name,
            ))
        values = (
            "%.4f A" % snapshot.tc_a,
            "%.4f A" % snapshot.iq_a,
            "%.4f A" % snapshot.id_a,
            "%.4f A" % snapshot.continuous_limit_a,
            "%.4f A" % snapshot.peak_limit_a,
            "%d · %s" % (
                1 if snapshot.current_limit_active else 0,
                "ON" if snapshot.current_limit_active else "OFF",
            ),
            "%.4f A" % snapshot.maximum_drive_current_a,
        )
        for row, value in enumerate(values):
            item = self.axis_current_reference_table.item(row, 1)
            item.setText(value)
            item.setToolTip(value)
        self.lbl_axis_current_reference_detail.setText(
            "Identity-bound query-only snapshot · acquisition %.1f ms · %s · "
            "COMMAND LOCKED / NEED-DATA · NO TC ASSIGNMENT / LOOP CHANGE / "
            "ENABLE / MOTION" % (
                1000.0 * snapshot.sample_duration_s,
                snapshot.limit_relation,
            ))

    def _build_axis_digital_inputs_frame(self):
        """Build the explicit, bounded IP/IL/IF read-only input panel."""
        frame = QtWidgets.QFrame()
        frame.setObjectName("chip")
        self.axis_digital_inputs_frame = frame
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel(
            "DIGITAL INPUTS · READ-ONLY SNAPSHOT v0.1")
        title.setProperty("role", "field")
        head.addWidget(title)
        head.addStretch(1)
        self.lbl_axis_digital_inputs_state = QtWidgets.QLabel("UNKNOWN")
        self.lbl_axis_digital_inputs_state.setObjectName("pill")
        self.lbl_axis_digital_inputs_state.setProperty("on", "false")
        self.lbl_axis_digital_inputs_state.setProperty("status", "neutral")
        head.addWidget(self.lbl_axis_digital_inputs_state)
        layout.addLayout(head)

        self.lbl_axis_digital_inputs_contract = QtWidgets.QLabel(
            single_axis_digital_inputs.EVIDENCE_LABEL
            + " · EXPLICIT REFRESH ONLY · IP READ ONLY · NO IB STICKY CLEAR · "
              "NO MAPPING/FILTER CHANGE · NO OUTPUT READ · NO OUTPUT WRITE · "
              "NO ENABLE/MOTION")
        self.lbl_axis_digital_inputs_contract.setProperty("role", "hint")
        self.lbl_axis_digital_inputs_contract.setWordWrap(True)
        self.lbl_axis_digital_inputs_contract.setMinimumWidth(0)
        layout.addWidget(self.lbl_axis_digital_inputs_contract)

        self.axis_digital_inputs_table = QtWidgets.QTableWidget(6, 5)
        self.axis_digital_inputs_table.setObjectName("expertEvidenceTable")
        self.axis_digital_inputs_table.setStyleSheet(
            "QTableWidget { font-family: 'Segoe UI'; font-size: 11px; }")
        self.axis_digital_inputs_table.setHorizontalHeaderLabels((
            "INPUT",
            "DRIVE LOGICAL STATE",
            "IL FUNCTION",
            "POLARITY / STICKY",
            "IF FILTER",
        ))
        self.axis_digital_inputs_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.axis_digital_inputs_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.axis_digital_inputs_table.setFocusPolicy(
            QtCore.Qt.FocusPolicy.NoFocus)
        self.axis_digital_inputs_table.setAlternatingRowColors(True)
        self.axis_digital_inputs_table.verticalHeader().setVisible(False)
        header = self.axis_digital_inputs_table.horizontalHeader()
        header.setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            4, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.axis_digital_inputs_table.setMinimumWidth(0)
        self.axis_digital_inputs_table.setMinimumHeight(245)
        for row in range(6):
            input_cell = QtWidgets.QTableWidgetItem("Input %d" % (row + 1))
            self.axis_digital_inputs_table.setItem(row, 0, input_cell)
            for column in range(1, 5):
                self.axis_digital_inputs_table.setItem(
                    row, column, QtWidgets.QTableWidgetItem("—"))
        layout.addWidget(self.axis_digital_inputs_table)

        action = QtWidgets.QHBoxLayout()
        self.btn_axis_digital_inputs_refresh = QtWidgets.QPushButton(
            "Refresh Digital Inputs · READ ONLY")
        self.btn_axis_digital_inputs_refresh.setEnabled(False)
        self.btn_axis_digital_inputs_refresh.clicked.connect(
            self._refresh_axis_digital_inputs_clicked)
        self._decorate_operation_control(
            self.btn_axis_digital_inputs_refresh,
            "axis.digital_inputs.refresh")
        action.addWidget(self.btn_axis_digital_inputs_refresh)
        action.addStretch(1)
        layout.addLayout(action)

        self.lbl_axis_digital_inputs_detail = QtWidgets.QLabel(
            "OFFLINE · no current identity-bound input snapshot")
        self.lbl_axis_digital_inputs_detail.setProperty("role", "hint")
        self.lbl_axis_digital_inputs_detail.setWordWrap(True)
        self.lbl_axis_digital_inputs_detail.setMinimumWidth(0)
        layout.addWidget(self.lbl_axis_digital_inputs_detail)
        self._reset_axis_digital_inputs(
            "OFFLINE · no current identity-bound input snapshot")
        return frame

    def _reset_axis_digital_inputs(self, reason):
        """Blank all input values without changing any drive authority."""
        self._axis_digital_inputs_snapshot = None
        if not hasattr(self, "lbl_axis_digital_inputs_state"):
            return
        self.lbl_axis_digital_inputs_state.setText("UNKNOWN")
        self.lbl_axis_digital_inputs_state.setProperty("on", "false")
        self.lbl_axis_digital_inputs_state.setProperty("status", "neutral")
        self._restyle(self.lbl_axis_digital_inputs_state)
        for row in range(6):
            for column in range(1, 5):
                self.axis_digital_inputs_table.item(row, column).setText("—")
        self.lbl_axis_digital_inputs_detail.setText(
            str(reason or "Digital-input snapshot unavailable"))

    def _refresh_axis_digital_inputs_clicked(self):
        """Request the bounded reader; never synthesize or retain old values."""
        current = bool(
            self.worker
            and self.worker.isRunning()
            and getattr(self, "_connection_admitted", False)
            and getattr(self, "_ui_connected", False)
            and getattr(self, "_telemetry_authoritative", False)
            and not getattr(self, "_energizing_state", False)
            and not getattr(self, "_connection_shutdown_pending", False))
        if not current:
            self._reset_axis_digital_inputs(
                "Current identity/telemetry authority is unavailable")
            return
        self._reset_axis_digital_inputs(
            "Reading IP + IL[1..6] + IF[1..6] in the worker")
        self.lbl_axis_digital_inputs_state.setText("READING")
        self.worker.refresh_axis_digital_inputs()

    def _on_axis_digital_inputs(self, snapshot):
        """Render only a current-worker, identity-bound read-only snapshot."""
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        canonical = None
        if isinstance(
                snapshot,
                single_axis_digital_inputs.DigitalInputSnapshot):
            canonical = single_axis_digital_inputs.decode_digital_input_snapshot(
                snapshot.raw,
                sample_duration_s=snapshot.sample_duration_s,
            )
        current_source = bool(
            not getattr(self, "_connection_shutdown_pending", False)
            and getattr(self, "_connection_admitted", False)
            and getattr(self, "_ui_connected", False)
            and getattr(self, "_telemetry_authoritative", False)
            and not getattr(self, "_energizing_state", False)
            and self.worker
            and self.worker.isRunning())
        if (not current_source
                or not isinstance(
                    snapshot,
                    single_axis_digital_inputs.DigitalInputSnapshot)
                or snapshot.state != single_axis_digital_inputs.CURRENT
                or canonical is None
                or canonical.state != single_axis_digital_inputs.CURRENT
                or snapshot != canonical):
            reason = (
                getattr(snapshot, "reason", "")
                or "Noncanonical or non-current digital-input snapshot")
            self._reset_axis_digital_inputs(reason)
            return

        snapshot = canonical
        self._axis_digital_inputs_snapshot = snapshot
        for row, input_state in enumerate(snapshot.inputs):
            values = (
                input_state.state_label,
                input_state.function_label,
                "%s · %s" % (
                    input_state.polarity,
                    "sticky" if input_state.sticky else "non-sticky"),
                "%.3f ms" % input_state.filter_ms,
            )
            for column, value in enumerate(values, start=1):
                cell = self.axis_digital_inputs_table.item(row, column)
                cell.setText(value)
                cell.setToolTip(value)
        self.lbl_axis_digital_inputs_state.setText(
            "CURRENT · DRIVE READ ONLY")
        self.lbl_axis_digital_inputs_state.setProperty("on", "false")
        self.lbl_axis_digital_inputs_state.setProperty("status", "neutral")
        self._restyle(self.lbl_axis_digital_inputs_state)
        self.lbl_axis_digital_inputs_detail.setText(
            "Identity-bound explicit snapshot · acquisition %.1f ms · "
            "IP read last · logical state only · no output/write/motion" %
            (1000.0 * snapshot.sample_duration_s))

    def _build_axis_digital_outputs_frame(self):
        """Build the explicit, bounded OP/OL/GO read-only output panel."""
        frame = QtWidgets.QFrame()
        frame.setObjectName("chip")
        self.axis_digital_outputs_frame = frame
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel(
            "DIGITAL OUTPUTS · READ-ONLY SNAPSHOT v0.1")
        title.setProperty("role", "field")
        head.addWidget(title)
        head.addStretch(1)
        self.lbl_axis_digital_outputs_state = QtWidgets.QLabel("UNKNOWN")
        self.lbl_axis_digital_outputs_state.setObjectName("pill")
        self.lbl_axis_digital_outputs_state.setProperty("on", "false")
        self.lbl_axis_digital_outputs_state.setProperty("status", "neutral")
        head.addWidget(self.lbl_axis_digital_outputs_state)
        layout.addLayout(head)

        self.lbl_axis_digital_outputs_contract = QtWidgets.QLabel(
            single_axis_digital_outputs.EVIDENCE_LABEL
            + " · EXPLICIT REFRESH ONLY · OP READ ONLY · "
              "NO OL/GO ASSIGNMENT · NO OUTPUT WRITE · NO OUTPUT ACTUATION · "
              "NO ENABLE/MOTION")
        self.lbl_axis_digital_outputs_contract.setProperty("role", "hint")
        self.lbl_axis_digital_outputs_contract.setWordWrap(True)
        self.lbl_axis_digital_outputs_contract.setMinimumWidth(0)
        layout.addWidget(self.lbl_axis_digital_outputs_contract)

        self.axis_digital_outputs_table = QtWidgets.QTableWidget(4, 5)
        self.axis_digital_outputs_table.setObjectName("expertEvidenceTable")
        self.axis_digital_outputs_table.setStyleSheet(
            "QTableWidget { font-family: 'Segoe UI'; font-size: 11px; }")
        self.axis_digital_outputs_table.setHorizontalHeaderLabels((
            "OUTPUT / LOGIC",
            "DRIVE LOGICAL ACTIVATION",
            "OL FUNCTION",
            "POLARITY",
            "GO ROUTE",
        ))
        self.axis_digital_outputs_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.axis_digital_outputs_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.axis_digital_outputs_table.setFocusPolicy(
            QtCore.Qt.FocusPolicy.NoFocus)
        self.axis_digital_outputs_table.setAlternatingRowColors(True)
        self.axis_digital_outputs_table.verticalHeader().setVisible(False)
        header = self.axis_digital_outputs_table.horizontalHeader()
        header.setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            4, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.axis_digital_outputs_table.setMinimumWidth(0)
        self.axis_digital_outputs_table.setMinimumHeight(205)
        for row in range(4):
            number = row + 1
            voltage = "5 V logic" if number <= 2 else "3.3 V logic"
            self.axis_digital_outputs_table.setItem(
                row, 0, QtWidgets.QTableWidgetItem(
                    "Output %d · %s" % (number, voltage)))
            for column in range(1, 5):
                self.axis_digital_outputs_table.setItem(
                    row, column, QtWidgets.QTableWidgetItem("—"))
        layout.addWidget(self.axis_digital_outputs_table)

        action = QtWidgets.QHBoxLayout()
        self.btn_axis_digital_outputs_refresh = QtWidgets.QPushButton(
            "Refresh Digital Outputs · READ ONLY")
        self.btn_axis_digital_outputs_refresh.setEnabled(False)
        self.btn_axis_digital_outputs_refresh.clicked.connect(
            self._refresh_axis_digital_outputs_clicked)
        self._decorate_operation_control(
            self.btn_axis_digital_outputs_refresh,
            "axis.digital_outputs.refresh")
        action.addWidget(self.btn_axis_digital_outputs_refresh)
        action.addStretch(1)
        layout.addLayout(action)

        self.lbl_axis_digital_outputs_detail = QtWidgets.QLabel(
            "OFFLINE · no current identity-bound output snapshot")
        self.lbl_axis_digital_outputs_detail.setProperty("role", "hint")
        self.lbl_axis_digital_outputs_detail.setWordWrap(True)
        self.lbl_axis_digital_outputs_detail.setMinimumWidth(0)
        layout.addWidget(self.lbl_axis_digital_outputs_detail)
        self._reset_axis_digital_outputs(
            "OFFLINE · no current identity-bound output snapshot")
        return frame

    def _reset_axis_digital_outputs(self, reason):
        """Blank all output values without changing any drive authority."""
        self._axis_digital_outputs_snapshot = None
        if not hasattr(self, "lbl_axis_digital_outputs_state"):
            return
        self.lbl_axis_digital_outputs_state.setText("UNKNOWN")
        self.lbl_axis_digital_outputs_state.setProperty("on", "false")
        self.lbl_axis_digital_outputs_state.setProperty("status", "neutral")
        self._restyle(self.lbl_axis_digital_outputs_state)
        for row in range(4):
            for column in range(1, 5):
                self.axis_digital_outputs_table.item(row, column).setText("—")
        self.lbl_axis_digital_outputs_detail.setText(
            str(reason or "Digital-output snapshot unavailable"))

    def _refresh_axis_digital_outputs_clicked(self):
        """Request the bounded reader; never synthesize or retain old values."""
        current = bool(
            self.worker
            and self.worker.isRunning()
            and getattr(self, "_connection_admitted", False)
            and getattr(self, "_ui_connected", False)
            and getattr(self, "_telemetry_authoritative", False)
            and not getattr(self, "_energizing_state", False)
            and not getattr(self, "_connection_shutdown_pending", False))
        if not current:
            self._reset_axis_digital_outputs(
                "Current identity/telemetry authority is unavailable")
            return
        self._reset_axis_digital_outputs(
            "Reading OL[1..4] + GO[1..4] + OP in the worker")
        self.lbl_axis_digital_outputs_state.setText("READING")
        self.worker.refresh_axis_digital_outputs()

    def _on_axis_digital_outputs(self, snapshot):
        """Render only a current-worker, identity-bound read-only snapshot."""
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        canonical = None
        if isinstance(
                snapshot,
                single_axis_digital_outputs.DigitalOutputSnapshot):
            canonical = (
                single_axis_digital_outputs.decode_digital_output_snapshot(
                    snapshot.raw,
                    sample_duration_s=snapshot.sample_duration_s,
                ))
        current_source = bool(
            not getattr(self, "_connection_shutdown_pending", False)
            and getattr(self, "_connection_admitted", False)
            and getattr(self, "_ui_connected", False)
            and getattr(self, "_telemetry_authoritative", False)
            and not getattr(self, "_energizing_state", False)
            and self.worker
            and self.worker.isRunning())
        if (not current_source
                or not isinstance(
                    snapshot,
                    single_axis_digital_outputs.DigitalOutputSnapshot)
                or snapshot.state != single_axis_digital_outputs.CURRENT
                or canonical is None
                or canonical.state != single_axis_digital_outputs.CURRENT
                or snapshot != canonical):
            reason = (
                getattr(snapshot, "reason", "")
                or "Noncanonical or non-current digital-output snapshot")
            self._reset_axis_digital_outputs(reason)
            return

        snapshot = canonical
        self._axis_digital_outputs_snapshot = snapshot
        for row, output_state in enumerate(snapshot.outputs):
            values = (
                output_state.state_label,
                output_state.function_label,
                output_state.polarity,
                output_state.route_label,
            )
            for column, value in enumerate(values, start=1):
                cell = self.axis_digital_outputs_table.item(row, column)
                cell.setText(value)
                cell.setToolTip(value)
        self.lbl_axis_digital_outputs_state.setText(
            "CURRENT · DRIVE READ ONLY")
        self.lbl_axis_digital_outputs_state.setProperty("on", "false")
        self.lbl_axis_digital_outputs_state.setProperty("status", "neutral")
        self._restyle(self.lbl_axis_digital_outputs_state)
        self.lbl_axis_digital_outputs_detail.setText(
            "Identity-bound explicit snapshot · acquisition %.1f ms · "
            "OP read last · physical level UNVERIFIED · "
            "no output write/actuation/motion" %
            (1000.0 * snapshot.sample_duration_s))

    def _motion_stop_clicked(self):
        """Always-available software STOP/disable escape path.

        This is not represented as STO.  It merely asks the worker to issue ST
        and MO=0 with readback, ahead of ordinary jobs.
        """
        if not (self.worker and self.worker.isRunning()):
            self._flash("드라이브가 연결되어 있지 않습니다.")
            return
        self._motion_stop_pending = True
        self.worker.request_motion_stop()
        self.motion_gate.setText(
            "STOP 요청 전송: ST → MO=0 최종 readback을 기다리는 중입니다. "
            "이 소프트웨어 STOP은 독립 STO/E-stop이 아닙니다.")
        self._update_motion_controls()

    def _update_motion_controls(self):
        connected = bool(
            getattr(self, "_connection_admitted", False)
            and getattr(self, "_ui_connected", False)
            and self.worker and self.worker.isRunning())
        telemetry_trusted = bool(
            connected
            and getattr(self, "_telemetry_authoritative", False)
            and not getattr(self, "_energizing_state", False))
        mutation_trusted = bool(
            telemetry_trusted
            and getattr(self, "_connection_access_mode", None)
            == SUPERVISED_ACCESS_MODE
            and getattr(self, "_last_mo", None) == 0)
        checks = all(check.isChecked() for check in (
            self.chk_motion_operator,
            self.chk_motion_estop,
            self.chk_motion_limits,
        ))
        ready = (
            FINITE_PTP_LIVE_ENABLED
            and mutation_trusted
            and not getattr(self, "_persistence_recovery_unknown", False)
            and self._motion_signature_is_current()
            and self._motion_session_zero_confirmed
            and not self._motion_inflight
            and not self._motion_stop_pending
            and not self._motion_config_unknown
            and checks
        )
        self.btn_motion_run.setEnabled(ready)
        # STOP never depends on the motion gate, coordinate state or gain trial.
        self.btn_motion_stop.setEnabled(connected)
        if not FINITE_PTP_LIVE_ENABLED:
            text = (
                "NEED-DATA 잠금: PTP 백엔드는 구현됐지만 기계 이동범위·정방향·"
                "limit 입력·검증된 SD/정지거리·독립 E-stop/STO 시험값이 없어 "
                "실기 실행은 열지 않았습니다.")
        elif getattr(self, "_persistence_recovery_unknown", False):
            text = ("PERSISTENCE UNKNOWN 잠금: 전원 재인가 후 읽기 전용 Audit 전에는 "
                    "새 Motion을 실행할 수 없습니다.")
        elif self._motion_config_unknown:
            text = "UNKNOWN 잠금: 임시 Motion 설정과 실제 드라이브 readback을 audit해야 합니다."
        elif not connected:
            text = "OFFLINE: 먼저 드라이브에 연결하세요."
        elif not self._motion_signature_is_current():
            text = "잠금: 이 연결 세션의 Commutation Signature GREEN이 필요합니다."
        elif not self._motion_session_zero_confirmed:
            text = "잠금: 이 연결에서 현재 위치에 Session Zero(PX=0)를 먼저 실행하세요."
        elif not checks:
            text = "잠금: 이번 실행의 현장 안전 확인 3개를 모두 확인하세요."
        elif self._motion_stop_pending:
            text = "STOP 확인 대기: MO=0/SO=0 readback 전에는 새 Motion을 실행할 수 없습니다."
        elif self._motion_inflight:
            text = "FINITE PTP 실행 중: STOP은 언제든 요청할 수 있습니다."
        else:
            text = "READY: 유한 PTP 1회 실행 후 자동 ST/MO=0 및 RAM 설정 복원."
        self.motion_gate.setText(text)

    def _motion_run_clicked(self):
        if not FINITE_PTP_LIVE_ENABLED:
            self._flash("FINITE PTP는 NEED-DATA 잠금 상태입니다. Axis Summary는 읽을 수 있습니다.")
            self._update_motion_controls()
            return
        if not self.btn_motion_run.isEnabled():
            self._flash("Motion 실행 게이트가 충족되지 않았습니다.")
            return
        request = single_axis_motion.PositionMoveRequest(
            mode=str(self.cmb_motion_mode.currentData()),
            target_rev=float(self.spn_motion_target.value()),
            speed_rpm=float(self.spn_motion_speed.value()),
            accel_rpm_s=float(self.spn_motion_accel.value()),
            travel_limit_rev=float(self.spn_motion_envelope.value()),
            current_cap_a=float(self.spn_motion_current.value()),
        )
        preview = (
            "Mode: %s\nTarget: %.4f rev\nSpeed cap: %.1f rpm\n"
            "AC/DC/SD cap: %.1f rpm/s\nTravel envelope: ±%.3f rev\n"
            "Current cap: %.2f A peak\n\n"
            "RAM-only profile → MO=1 → PA/BG → ST → MO=0 → restore"
            % (request.mode, request.target_rev, request.speed_rpm,
               request.accel_rpm_s, request.travel_limit_rev,
               request.current_cap_a))
        answer = QtWidgets.QMessageBox.warning(
            self, "유한 PTP 실행 확인",
            preview + "\n\n실행하시겠습니까?",
            QtWidgets.QMessageBox.StandardButton.Yes |
            QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._motion_inflight = True
        self._update_motion_controls()
        self.worker.run_position_move(request)

    def _refresh_axis_clicked(self):
        if self.worker and self.worker.isRunning():
            self.axis_status.setText("READING · drive raw parameters…")
            self.worker.refresh_axis_summary()
        else:
            self.axis_status.setText("OFFLINE")

    @staticmethod
    def _axis_join(raw, names):
        return " / ".join("%s=%s" % (name, raw.get(name, "—")) for name in names)

    def _reset_axis_enable_contract(self, reason):
        """Blank the enable projection and keep its command surface locked."""
        projection = single_axis_enable_contract.project_enable_state(None)
        self._axis_enable_projection = projection
        if not hasattr(self, "lbl_axis_enable_state"):
            return
        self.lbl_axis_enable_state.setText(projection.label)
        self.lbl_axis_enable_state.setProperty("on", "false")
        self.lbl_axis_enable_state.setProperty("status", "neutral")
        self._restyle(self.lbl_axis_enable_state)
        self.lbl_axis_enable_detail.setText(
            str(reason or projection.detail))
        self.btn_axis_enable_locked.setEnabled(False)

    def _render_axis_enable_contract(self, snapshot):
        """Render drive-reported state; never add or grant MO=1 authority."""
        projection = single_axis_enable_contract.project_enable_state(snapshot)
        self._axis_enable_projection = projection
        if not hasattr(self, "lbl_axis_enable_state"):
            return
        self.lbl_axis_enable_state.setText(projection.label)
        state_style = (
            "error"
            if projection.state in (
                single_axis_enable_contract.UNKNOWN,
                single_axis_enable_contract.FAULT_REPORTED,
            )
            else "neutral")
        self.lbl_axis_enable_state.setProperty(
            "on", "true"
            if projection.state == single_axis_enable_contract.ENABLED_REPORTED
            else "false")
        self.lbl_axis_enable_state.setProperty("status", state_style)
        self._restyle(self.lbl_axis_enable_state)
        self.lbl_axis_enable_detail.setText(projection.detail)
        self.btn_axis_enable_locked.setEnabled(False)

    def _reset_axis_safety_snapshot(self, reason):
        """Blank the safety projection without changing any drive authority."""
        self._axis_safety_snapshot = (
            single_axis_status.decode_axis_safety_snapshot(None))
        self._reset_axis_enable_contract(reason)
        if not hasattr(self, "lbl_axis_safety_state"):
            return
        self.lbl_axis_safety_state.setText("UNKNOWN")
        self.lbl_axis_safety_state.setProperty("on", "false")
        self.lbl_axis_safety_state.setProperty("status", "neutral")
        self._restyle(self.lbl_axis_safety_state)
        for widget in self.axis_safety_fields.values():
            widget.setText("—")
        self.lbl_axis_safety_detail.setText(
            str(reason or "No current admitted connection snapshot"))
        if hasattr(self, "axis_fields") and "safety" in self.axis_fields:
            self.axis_fields["safety"].setText("—")

    def _render_axis_safety_snapshot(self, snapshot):
        """Render a pure MODEL projection; never grant motion/STO authority."""
        self._axis_safety_snapshot = snapshot
        if not hasattr(self, "lbl_axis_safety_state"):
            return
        if snapshot.state == single_axis_status.UNKNOWN:
            self._reset_axis_safety_snapshot(snapshot.reason)
            return

        raw = snapshot.raw
        values = {
            "mo_so": "MO=%d · SO=%d" % (raw["MO"], raw["SO"]),
            "fault_amp": "MF=%d · SR[3:0]=0x%X" % (
                raw["MF"], snapshot.amplifier_code),
            "servo": "SR4=%d" % int(snapshot.servo_enabled_reported),
            "sto": "SR14=%d · SR15=%d" % (
                int(snapshot.sto1_permission_reported),
                int(snapshot.sto2_permission_reported)),
            "program_limit": "PS=%d · SR12=%d · SR13=%d" % (
                raw["PS"], int(snapshot.user_program_reported),
                int(snapshot.current_limit_reported)),
            "profiler": "MS=%d · SR[11:8]=%d" % (
                raw["MS"], snapshot.profiler_code),
        }
        for key, widget in self.axis_safety_fields.items():
            widget.setText(values[key])

        if snapshot.state == single_axis_status.INCONSISTENT:
            state_text = "INCONSISTENT · AUTHORITY UNKNOWN"
            state_style = "error"
            detail = snapshot.reason
        else:
            state_text = "CURRENT · MODEL"
            state_style = "neutral"
            detail = " · ".join(snapshot.conditions)
        self.lbl_axis_safety_state.setText(state_text)
        self.lbl_axis_safety_state.setProperty("on", "false")
        self.lbl_axis_safety_state.setProperty("status", state_style)
        self._restyle(self.lbl_axis_safety_state)
        self.lbl_axis_safety_detail.setText(detail)

    def _on_axis_summary(self, summary):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        current_source = bool(
            not getattr(self, "_connection_shutdown_pending", False)
            and getattr(self, "_connection_admitted", False)
            and getattr(self, "_ui_connected", False)
            and self.worker
            and self.worker.isRunning())
        if not current_source:
            self._reset_axis_safety_snapshot(
                "No current admitted connection snapshot")
            return
        self._session_log_event_changed(
            self.session_log.record_axis_summary(summary or {}))
        self._axis_summary_data = dict(summary or {})
        raw = self._axis_summary_data.get("raw", {}) or {}
        if (getattr(self, "_telemetry_authoritative", False)
                and not getattr(self, "_energizing_state", False)):
            safety_snapshot = (
                single_axis_status.decode_axis_safety_snapshot(raw))
            self._render_axis_safety_snapshot(safety_snapshot)
            self._render_axis_enable_contract(safety_snapshot)
        else:
            self._reset_axis_safety_snapshot(
                "Telemetry authority unavailable for safety projection")
        values = {
            "scope": self._axis_summary_data.get("scope", "—"),
            "mode": self._axis_summary_data.get("mode", "—"),
            "motor": "CA[28]=%s" % raw.get("CA[28]", "—"),
            "counts": "CA[18]=%s cnt/rev" % raw.get("CA[18]", "—"),
            "routing": self._axis_summary_data.get("feedback_routing", "—"),
            "directions": self._axis_join(raw, ("CA[54]", "CA[55]", "CA[56]", "CA[57]")),
            "gear": self._axis_join(raw, ("FC[5]", "FC[6]")),
            "scaling": self._axis_join(raw, tuple("FC[%d]" % i for i in range(1, 13))),
            "brake": self._axis_join(raw, ("BP[1]", "BP[2]")),
            "unbalanced": "SC[13]=%s (raw; gravity compensation 아님)" % raw.get("SC[13]", "—"),
            "external": "RM=%s" % raw.get("RM", "—"),
            "limits": self._axis_join(raw, ("VL[3]", "VH[3]")),
            "modulo": self._axis_join(raw, ("XM[1]", "XM[2]")),
            "profile": self._axis_join(raw, ("SP", "AC", "DC", "SD", "FS", "SF[1]", "SF[2]")),
            "current": self._axis_join(raw, ("PL[1]", "CL[1]")),
            "safety": self._axis_join(raw, ("MO", "SO", "MF", "SR", "MS")),
        }
        for key, widget in self.axis_fields.items():
            widget.setText(str(values.get(key, "—")))
        errors = self._axis_summary_data.get("errors", {}) or {}
        self._motion_config_unknown = bool(
            self._axis_summary_data.get("motion_config_unknown")
            or self._axis_summary_data.get("energy_closeout_unknown"))
        self.axis_status.setText(
            ("READ-ONLY · %d field read errors · writes remain locked" % len(errors))
            if errors else
            "READ-ONLY · drive raw values refreshed · Axis writes remain locked")
        self._update_motion_controls()

    def _on_motion_authority(self, allowed, detail):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        token = None
        if allowed:
            getter = getattr(
                self.worker, "current_commutation_signature_token", None)
            if callable(getter):
                token = getter()
            elif source is None or source is self.worker:
                # Offline/fake workers have no drive authority; retain a local
                # marker only so deterministic UI tests can exercise controls.
                token = "offline-ui-signature:%s" % id(self.worker)
        effective = bool(allowed and isinstance(token, str) and token)
        self._motion_signature_green = effective
        self._motion_signature_token = token if effective else None
        self._motion_signature_generation = (
            getattr(self, "_tuning_authority_generation", 0)
            if effective else None)
        self._flash(str(detail))
        self._set_connected_ui(bool(
            getattr(self, "_ui_connected", False)
            and self.worker and self.worker.isRunning()))
        self._update_motion_controls()

    def _on_motion_result(self, action, result):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        final_state = getattr(result, "final_state", {}) or {}
        detached_final = {
            key: final_state.get(key)
            for key in ("MO", "SO", "MS", "disabled_verified")
            if key in final_state
        }
        motion_status = str(getattr(result, "status", "UNKNOWN") or "UNKNOWN")
        self._session_log_event_changed(self.session_log.append(
            category="motion", name="motion.%s" % str(action or "unknown"),
            severity=("INFO" if motion_status in ("OK", "PASS", "STOPPED")
                      else "UNKNOWN" if motion_status == "UNKNOWN"
                      else "WARNING"),
            payload={
                "status": motion_status,
                "reason": str(getattr(result, "reason", "") or "")[:500],
                "final_state": detached_final,
            }))
        if action == "move":
            self._motion_inflight = False
        if (action in ("stop", "shutdown_stop")
                or str(action).endswith("_closeout")):
            disabled = (getattr(result, "final_state", {}) or {}).get(
                "disabled_verified") is True
            if disabled:
                self._motion_stop_pending = False
                self._motion_inflight = False
            else:
                self._motion_stop_pending = True
                self._motion_config_unknown = True
        if getattr(result, "status", None) == single_axis_motion.UNKNOWN:
            self._motion_config_unknown = True
        status = getattr(result, "status", "UNKNOWN")
        reason = getattr(result, "reason", "") or ""
        self._flash("Motion %s · %s%s" % (
            action, status, (" · " + reason) if reason else ""))
        self.motion_gate.setText(
            "%s · %s%s" % (action.upper(), status,
                            (" · " + reason) if reason else ""))
        self._update_motion_controls()

    # ---- workspace: nav + stacked pages ----------------------------------------------
    def _build_workspace(self):
        wrap = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(wrap); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)
        nav = QtWidgets.QHBoxLayout(); nav.setSpacing(8)
        self._workspace_nav_layout = nav
        self.stack = CurrentPageStack()
        self._nav_btns = []
        self._nav_button_by_tool_id = {}
        self._page_index_to_tool_id = {}
        self._tool_nav_operation_ids = tuple(dict.fromkeys(
            operation_id
            for tool_id in tool_organizer.CANONICAL_TOOL_IDS
            for operation_id in self._TOOL_NAV_OPERATIONS[tool_id]
        ))
        pages = [("Motion", self._build_motion_card()),
                 ("Motor", self._build_motor_page()),
                 ("Feedback", self._build_feedback_page()),
                 ("Tuning", self._build_tuning_page()),
                 ("Axis", self._build_axis_page()),
                 ("Recorder", self._build_recorder_page()),
                 ("Status", self._build_session_log_page()),
                 ("System", self._build_system_configuration_page())]
        nav_tooltips = {
            "Status": "Fault / Status / Session Log · host observed",
            "System": "System Configuration · Inspector v0.1",
        }
        for i, (name, page) in enumerate(pages):
            tool_id = tool_organizer.CANONICAL_TOOL_IDS[i]
            b = QtWidgets.QPushButton(name); b.setCheckable(True)
            b.setStyleSheet("QPushButton{padding:7px 8px;} "
                            "QPushButton:checked{background:%s;color:#042435;border:none;font-weight:800;}"
                            % theme.INDIGO)
            if name in nav_tooltips:
                b.setToolTip(nav_tooltips[name])
            b.clicked.connect(
                lambda _=False, current_tool_id=tool_id:
                self._navigate_tool(current_tool_id))
            nav.addWidget(b); self._nav_btns.append(b)
            self._nav_button_by_tool_id[tool_id] = b
            self._page_index_to_tool_id[i] = tool_id
            self.stack.addWidget(page)
        nav.addStretch(1)
        self.workspace_scroll = QtWidgets.QScrollArea()
        self.workspace_scroll.setWidgetResizable(True)
        self.workspace_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.workspace_scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.workspace_scroll.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.workspace_scroll.setWidget(self.stack)
        v.addLayout(nav); v.addWidget(self.workspace_scroll, 1)
        self._nav_to(0)
        return wrap

    def _render_tool_layout(self, layout, *, preferred_index=None):
        """Render one already-validated layout without changing page objects."""
        layout = tool_organizer.validate_layout(layout)
        active = frozenset(layout.active)

        # Keep every page/button object alive.  Only the presentation order and
        # visibility of the eight workspace selectors may change.
        for tool_id in tool_organizer.CANONICAL_TOOL_IDS:
            self._workspace_nav_layout.removeWidget(
                self._nav_button_by_tool_id[tool_id])
        for position, tool_id in enumerate(layout.active + layout.available):
            button = self._nav_button_by_tool_id[tool_id]
            self._workspace_nav_layout.insertWidget(position, button)
            button.setVisible(tool_id in active)

        for tool_id, operation_ids in self._TOOL_NAV_OPERATIONS.items():
            visible = tool_id in active
            for operation_id in operation_ids:
                for action in self.app_menu_actions_by_operation.get(
                        operation_id, ()):
                    action.setVisible(visible)

        current_index = self.stack.currentIndex()
        if preferred_index is not None:
            preferred_tool = self._page_index_to_tool_id.get(preferred_index)
            if preferred_tool in active:
                current_index = preferred_index
        current_tool = self._page_index_to_tool_id.get(current_index)
        if current_tool not in active:
            current_index = self._TOOL_ID_TO_PAGE_INDEX[layout.active[0]]
        self._nav_to(current_index)

    def _capture_tool_visual_state(self):
        """Freeze the exact selector/action presentation for direct rollback."""
        ordered_ids = tuple(sorted(
            tool_organizer.CANONICAL_TOOL_IDS,
            key=lambda tool_id: self._workspace_nav_layout.indexOf(
                self._nav_button_by_tool_id[tool_id])))
        return {
            "order": ordered_ids,
            "button_visible": {
                tool_id: not self._nav_button_by_tool_id[tool_id].isHidden()
                for tool_id in tool_organizer.CANONICAL_TOOL_IDS
            },
            "action_visible": tuple(
                (action, action.isVisible())
                for operation_id in self._tool_nav_operation_ids
                for action in self.app_menu_actions_by_operation.get(
                    operation_id, ())),
            "current_index": self.stack.currentIndex(),
        }

    def _restore_tool_visual_state(self, snapshot):
        """Restore a frozen presentation without re-entering the renderer."""
        for tool_id in tool_organizer.CANONICAL_TOOL_IDS:
            self._workspace_nav_layout.removeWidget(
                self._nav_button_by_tool_id[tool_id])
        for position, tool_id in enumerate(snapshot["order"]):
            button = self._nav_button_by_tool_id[tool_id]
            self._workspace_nav_layout.insertWidget(position, button)
            button.setVisible(snapshot["button_visible"][tool_id])
        for action, visible in snapshot["action_visible"]:
            action.setVisible(visible)
        self._nav_to(snapshot["current_index"])

    def _apply_tool_layout(self, candidate):
        """Atomically replace the session layout; never touch drive authority."""
        candidate = tool_organizer.validate_layout(candidate)
        active = frozenset(candidate.active)
        tuning_recovery_active = bool(
            getattr(self, "_p1_gain_trial", None) is not None
            or getattr(self, "_vp_gain_trial", None) is not None
            or getattr(self, "_tune_dispatch_inflight", None) is not None
            or getattr(self, "_motor_write_inflight", False))
        if "tuning" not in active and tuning_recovery_active:
            raise tool_organizer.ToolOrganizerError(
                "Tuning must stay visible while a trial or tuning transaction "
                "requires recovery controls")

        recorder_recovery_active = self._recorder_state_pending()
        if "recorder" not in active and recorder_recovery_active:
            raise tool_organizer.ToolOrganizerError(
                "Recorder must stay visible while its stop or recovery "
                "controls may be required")

        motion_recovery_active = bool(
            getattr(self, "_motion_inflight", False)
            or getattr(self, "_motion_stop_pending", False)
            or getattr(self, "_motion_config_unknown", False))
        if "motion" not in active and motion_recovery_active:
            raise tool_organizer.ToolOrganizerError(
                "Motion must stay visible while its stop or recovery controls "
                "may be required")

        visual_snapshot = self._capture_tool_visual_state()
        try:
            self._render_tool_layout(candidate)
        except Exception as exc:
            try:
                self._restore_tool_visual_state(visual_snapshot)
            except Exception as rollback_exc:
                raise tool_organizer.ToolOrganizerError(
                    "session tool layout was not applied; visual rollback "
                    "also failed closed") from rollback_exc
            raise tool_organizer.ToolOrganizerError(
                "session tool layout was not applied") from exc
        self.tool_layout = candidate
        self._flash(
            "Tool Organizer · LOCAL SESSION layout applied (not persisted)")
        return candidate

    def _nav_to(self, ix):
        page_changed = self.stack.currentIndex() != ix
        self.stack.setCurrentIndex(ix)
        self.stack.updateGeometry()
        if hasattr(self, "workspace_scroll"):
            self.workspace_scroll.widget().adjustSize()
            if page_changed:
                for scroll_bar in (
                        self.workspace_scroll.horizontalScrollBar(),
                        self.workspace_scroll.verticalScrollBar()):
                    scroll_bar.setValue(scroll_bar.minimum())
        for i, b in enumerate(self._nav_btns):
            b.setChecked(i == ix)
        recorder_visible = ix == 5
        if hasattr(self, "recorder_ribbon_menu"):
            # Application menus are global; only the Recorder context/lifecycle
            # controls are contextual.
            self.recorder_ribbon_menu.setVisible(True)
            self.recorder_ribbon_scroll.setVisible(recorder_visible)
            self.recorder_activation_group.setVisible(recorder_visible)
            self.btn_rec_context.setChecked(recorder_visible)
            self.btn_rec_context.setVisible(recorder_visible)
            self.lbl_recorder_ribbon_state.setVisible(recorder_visible)

    def _build_motor_page(self):
        f = theme.HudCard()
        v = QtWidgets.QVBoxLayout(f); v.setContentsMargins(16, 14, 16, 16); v.setSpacing(10)
        title = QtWidgets.QLabel("MOTOR SETTINGS"); title.setProperty("role", "celltitle")
        v.addWidget(title)
        self.motor_fields = {}
        form = QtWidgets.QGridLayout(); form.setHorizontalSpacing(14); form.setVerticalSpacing(8)
        r = 0
        lt = QtWidgets.QLabel("Motor Type  (CA[28])"); lt.setProperty("role", "field")
        self.motor_type_combo = QtWidgets.QComboBox()
        for k in sorted(self._MOTOR_TYPES):
            self.motor_type_combo.addItem(self._MOTOR_TYPES[k], k)
        self.motor_type_combo.setEnabled(False)
        form.addWidget(lt, r, 0); form.addWidget(self.motor_type_combo, r, 1); r += 1
        for key, label in [("peak", "Peak Current [Arms]  (PL[1])"),
                           ("cont", "Continuous Stall Current [Arms]  (CL[1])"),
                           ("maxspeed", "Maximal Motor Speed [RPM]  (VH[2])"),
                           ("poles", "Pole Pairs per Revolution  (CA[19])")]:
            l = QtWidgets.QLabel(label); l.setProperty("role", "field")
            e = QtWidgets.QLineEdit(); e.setText("—"); e.setEnabled(False)
            form.addWidget(l, r, 0); form.addWidget(e, r, 1); self.motor_fields[key] = e; r += 1
        for key, label in [("R", "R phase-to-phase [ohm]"), ("L", "L phase-to-phase [mH]"),
                           ("Ke", "Ke back-emf [Vrms/Krpm]")]:
            l = QtWidgets.QLabel(label); l.setProperty("role", "field")
            e = QtWidgets.QLineEdit(); e.setReadOnly(True); e.setText("—")
            form.addWidget(l, r, 0); form.addWidget(e, r, 1); self.motor_fields[key] = e; r += 1
        v.addLayout(form)
        v.addWidget(self._hline())
        row = QtWidgets.QHBoxLayout()
        self.btn_motor_write = QtWidgets.QPushButton("Save Motor Profile  (Durable SV)")
        self.btn_motor_write.setObjectName("primary"); self.btn_motor_write.setEnabled(False)
        self.btn_motor_write.setToolTip(
            "Preflight → durable write-ahead record → RAM write/readback → "
            "verified rollback on failure → one authorized SV. Duplicate clicks are blocked.")
        self.btn_motor_write.clicked.connect(self._write_motor)
        self._decorate_operation_control(self.btn_motor_write, "motor.save")
        row.addWidget(self.btn_motor_write); row.addStretch(1)
        v.addLayout(row)
        note = QtWidgets.QLabel(
            "저장 순서: 안전 사전검증 → durable WAL → RAM 적용·전체 되읽기 → "
            "실패 시 원값 rollback·되읽기 → 승인된 SV 1회. 응답 유실은 UNKNOWN으로 잠기며 "
            "자동 재시도하지 않습니다. R/L/Ke는 Current ID(Quick Tuning)가 산출합니다.")
        note.setProperty("role", "hint"); note.setWordWrap(True)
        v.addWidget(note); v.addStretch(1)
        return f

    def _build_axis_page(self):
        f = theme.HudCard()
        outer = QtWidgets.QVBoxLayout(f)
        outer.setContentsMargins(16, 14, 16, 16); outer.setSpacing(10)
        title = QtWidgets.QLabel("QUICK AXIS SUMMARY  ·  READ ONLY v1")
        title.setProperty("role", "celltitle"); outer.addWidget(title)
        note = QtWidgets.QLabel(
            "EAS의 Axis Configuration 이름을 명령 근거 없이 쓰기로 열지 않습니다. "
            "현재 드라이브의 raw UM/feedback routing/FC/BP/SC/limit/profile을 읽어 보여주며, "
            "Axis 설정 쓰기는 Preview → RAM → exact readback → rollback → 별도 SV 계약 이후 추가합니다.")
        note.setProperty("role", "hint"); note.setWordWrap(True); outer.addWidget(note)

        safety_frame = QtWidgets.QFrame()
        safety_frame.setObjectName("chip")
        safety_outer = QtWidgets.QVBoxLayout(safety_frame)
        safety_outer.setContentsMargins(10, 8, 10, 8)
        safety_outer.setSpacing(6)
        safety_head = QtWidgets.QHBoxLayout()
        safety_title = QtWidgets.QLabel(
            "SINGLE AXIS SAFETY SNAPSHOT v1  ·  ZERO-NEW-I/O")
        safety_title.setProperty("role", "field")
        safety_head.addWidget(safety_title)
        safety_head.addStretch(1)
        self.lbl_axis_safety_state = QtWidgets.QLabel("UNKNOWN")
        self.lbl_axis_safety_state.setObjectName("pill")
        self.lbl_axis_safety_state.setProperty("on", "false")
        self.lbl_axis_safety_state.setProperty("status", "neutral")
        safety_head.addWidget(self.lbl_axis_safety_state)
        safety_outer.addLayout(safety_head)

        self.lbl_axis_safety_contract = QtWidgets.QLabel(
            single_axis_status.EVIDENCE_LABEL
            + " · existing MO/SO/MF/PS/SR/MS snapshot only · "
              "independent E-stop/STO response and torque isolation remain NEED-DATA")
        self.lbl_axis_safety_contract.setProperty("role", "hint")
        self.lbl_axis_safety_contract.setWordWrap(True)
        self.lbl_axis_safety_contract.setMinimumHeight(max(
            58, self.lbl_axis_safety_contract.sizeHint().height()))
        safety_outer.addWidget(self.lbl_axis_safety_contract)

        safety_grid = QtWidgets.QGridLayout()
        safety_grid.setContentsMargins(0, 0, 0, 0)
        safety_grid.setHorizontalSpacing(10)
        safety_grid.setVerticalSpacing(5)
        self.axis_safety_fields = {}
        safety_rows = (
            ("mo_so", "Motor command / feedback"),
            ("fault_amp", "Fault / amplifier code"),
            ("servo", "Servo feedback"),
            ("sto", "STO channels · drive report"),
            ("program_limit", "User program / current limit"),
            ("profiler", "Profiler"),
        )
        for index, (key, label) in enumerate(safety_rows):
            cell = QtWidgets.QWidget()
            cell_layout = QtWidgets.QVBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(2)
            field_label = QtWidgets.QLabel(label)
            field_label.setProperty("role", "field")
            value = QtWidgets.QLineEdit("—")
            value.setReadOnly(True)
            cell_layout.addWidget(field_label)
            cell_layout.addWidget(value)
            safety_grid.addWidget(cell, index // 3, index % 3)
            self.axis_safety_fields[key] = value
        safety_outer.addLayout(safety_grid)

        self.lbl_axis_safety_detail = QtWidgets.QLabel(
            "OFFLINE · no current drive snapshot")
        self.lbl_axis_safety_detail.setProperty("role", "hint")
        self.lbl_axis_safety_detail.setWordWrap(True)
        self.lbl_axis_safety_detail.setMinimumHeight(max(
            58, self.lbl_axis_safety_detail.sizeHint().height()))
        safety_outer.addWidget(self.lbl_axis_safety_detail)
        outer.addWidget(safety_frame)

        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        self.axis_summary_scroll = scroll
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        body = QtWidgets.QWidget()
        self.axis_summary_body = body
        for surface in (scroll.viewport(), body):
            palette = surface.palette()
            palette.setColor(
                QtGui.QPalette.ColorRole.Window, QtGui.QColor(theme.CARD))
            palette.setColor(
                QtGui.QPalette.ColorRole.Base, QtGui.QColor(theme.CARD))
            surface.setPalette(palette)
            surface.setAutoFillBackground(True)
        grid = QtWidgets.QGridLayout(body)
        grid.setContentsMargins(0, 0, 6, 0); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(7)
        self.axis_fields = {}
        rows = (
            ("scope", "Axis / control scope"),
            ("mode", "Mode of operation"),
            ("motor", "Motor type raw  CA[28]"),
            ("counts", "Main feedback counts/rev  CA[18]"),
            ("routing", "Feedback routing  CA[45]/[46]/[47]"),
            ("directions", "Feedback directions  CA[54..57]"),
            ("gear", "Gear ratio raw  FC[5]/FC[6]"),
            ("scaling", "FC scaling  FC[1..12]"),
            ("brake", "Brake delays raw  BP[1]/BP[2]"),
            ("unbalanced", "Unbalanced-axis raw  SC[13]"),
            ("external", "External reference  RM"),
            ("limits", "Position limits  VL[3]/VH[3]"),
            ("modulo", "Position range  XM[1]/XM[2]"),
            ("profile", "Profile  SP/AC/DC/SD/SF"),
            ("current", "Current limits  PL[1]/CL[1]"),
            ("safety", "Live status  MO/SO/MF/SR/MS"),
        )
        for row, (key, label) in enumerate(rows):
            lab = QtWidgets.QLabel(label); lab.setProperty("role", "field")
            value = QtWidgets.QLineEdit("—"); value.setReadOnly(True)
            grid.addWidget(lab, row, 0); grid.addWidget(value, row, 1)
            self.axis_fields[key] = value
        scroll.setWidget(body); outer.addWidget(scroll, 1)
        row = QtWidgets.QHBoxLayout()
        self.btn_axis_refresh = QtWidgets.QPushButton("Refresh read-only Axis Summary")
        self.btn_axis_refresh.setEnabled(False)
        self.btn_axis_refresh.clicked.connect(self._refresh_axis_clicked)
        self._decorate_operation_control(self.btn_axis_refresh, "axis.refresh")
        row.addWidget(self.btn_axis_refresh); row.addStretch(1); outer.addLayout(row)
        self.axis_status = QtWidgets.QLabel("OFFLINE")
        self.axis_status.setProperty("role", "hint"); self.axis_status.setWordWrap(True)
        outer.addWidget(self.axis_status)
        self._reset_axis_safety_snapshot("OFFLINE · no current drive snapshot")
        return f

    def _build_system_configuration_page(self):
        """Build a zero-query projection of already-admitted target evidence."""
        frame = theme.HudCard()
        self.system_config_frame = frame
        outer = QtWidgets.QVBoxLayout(frame)
        outer.setContentsMargins(16, 14, 16, 16); outer.setSpacing(10)

        title_row = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel(
            "SYSTEM CONFIGURATION  ·  READ ONLY v0.1")
        title.setProperty("role", "celltitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.lbl_system_config_state = QtWidgets.QLabel("NO CURRENT TARGET")
        self.lbl_system_config_state.setObjectName("pill")
        self.lbl_system_config_state.setProperty("on", "false")
        title_row.addWidget(self.lbl_system_config_state)
        outer.addLayout(title_row)

        self.lbl_system_config_contract = QtWidgets.QLabel(
            "HOST-OBSERVED / ZERO-NEW-I/O · this is not full EAS System Configuration. "
            "It projects only the current generation already admitted by the connection "
            "callback. Add, Remove, Edit, Group, I/O and Virtual Axis remain NEED-DATA.")
        self.lbl_system_config_contract.setProperty("role", "hint")
        self.lbl_system_config_contract.setWordWrap(True)
        self.lbl_system_config_contract.setMinimumHeight(max(
            48, self.lbl_system_config_contract.sizeHint().height()))
        outer.addWidget(self.lbl_system_config_contract)

        content = QtWidgets.QHBoxLayout(); content.setSpacing(12)
        tree_panel, tree_layout = self._ribbon_group(
            "HOST WORKSPACE PROJECTION")
        tree_panel.setMinimumWidth(245)
        tree_panel.setMaximumWidth(330)
        self.system_config_tree = QtWidgets.QTreeWidget()
        self.system_config_tree.setHeaderHidden(True)
        self.system_config_tree.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.system_config_tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        tree_layout.addWidget(self.system_config_tree, 1)
        tree_note = QtWidgets.QLabel(
            "EAS public topology rule: a directly connected drive is one level "
            "below Workspace. Multi-target hierarchy is not inferred here.")
        tree_note.setProperty("role", "hint")
        tree_note.setWordWrap(True)
        tree_layout.addWidget(tree_note)
        content.addWidget(tree_panel, 0)

        property_panel, property_layout = self._ribbon_group(
            "ITEM CONFIGURATION · VALUE / PROVENANCE")
        self.system_config_table = QtWidgets.QTableWidget(0, 3)
        self.system_config_table.setHorizontalHeaderLabels((
            "PROPERTY", "VALUE", "SOURCE / AUTHORITY"))
        self.system_config_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.system_config_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.system_config_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.system_config_table.setAlternatingRowColors(True)
        self.system_config_table.setWordWrap(False)
        self.system_config_table.verticalHeader().setVisible(False)
        table_header = self.system_config_table.horizontalHeader()
        table_header.setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        property_layout.addWidget(self.system_config_table, 1)
        content.addWidget(property_panel, 1)
        outer.addLayout(content, 1)

        locked_panel, locked_layout = self._ribbon_group(
            "FULL EAS MANAGEMENT · LOCKED / NEED-DATA")
        locked_grid = QtWidgets.QGridLayout(); locked_grid.setSpacing(7)
        self.system_config_locked_controls = []
        for index, label in enumerate((
                "Add / Remove Target", "Add Group", "Add I/O Device",
                "Add Virtual Axis", "Edit / Apply Configuration")):
            button = QtWidgets.QPushButton(label + "  ·  LOCKED")
            self._decorate_operation_control(
                button, "eas.system_config.manage")
            button.setEnabled(False)
            # Two columns keep long, explicit lock labels from forcing a
            # horizontal workspace scrollbar on ordinary desktop widths.
            if index == 4:
                # The longest action owns a full row.  Keeping it in column 0
                # made that column dictate a 1 px horizontal overflow in the
                # supported Angry Birds skin at the 1366 px contract width.
                locked_grid.addWidget(button, 2, 0, 1, 2)
            else:
                locked_grid.addWidget(button, index // 2, index % 2)
            self.system_config_locked_controls.append(button)
        locked_layout.addLayout(locked_grid)
        outer.addWidget(locked_panel)

        self._render_system_configuration()
        return frame

    @staticmethod
    def _system_config_value(value):
        if value is None:
            return "—"
        if isinstance(value, bool):
            return "ENABLED" if value else "DISABLED"
        return str(value)

    def _render_system_configuration(self):
        """Render the frozen projection without consulting the worker or drive."""
        if not hasattr(self, "system_config_table"):
            return
        snapshot = self.system_configuration.snapshot()
        current = snapshot.state == system_configuration.CURRENT
        self.lbl_system_config_state.setText(
            "CURRENT · HOST OBSERVED" if current else "NO CURRENT TARGET")
        self.lbl_system_config_state.setProperty(
            "on", "true" if current else "false")
        self.lbl_system_config_state.setProperty("status", None)
        self._restyle(self.lbl_system_config_state)

        self.system_config_tree.clear()
        root = QtWidgets.QTreeWidgetItem((
            "Workspace · %s" % snapshot.workspace_name,))
        root.setFlags(root.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
        self.system_config_tree.addTopLevelItem(root)
        if current:
            target = QtWidgets.QTreeWidgetItem((
                "%s · %s" % (snapshot.target_alias, snapshot.target_type),))
            target.setFlags(target.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            root.addChild(target)
            target.setToolTip(
                0, "%s · raw SN[4] is not retained by this view" %
                snapshot.identity_alias)
        root.setExpanded(True)

        topology_text = (
            "Workspace → one directly connected drive"
            if snapshot.topology == system_configuration.SINGLE_DIRECT_DRIVE
            else None)
        target_class = (
            "%s · application classification" % snapshot.target_type
            if snapshot.target_type is not None else None)
        rows = (
            ("Projection state", snapshot.state, "HOST AUTHORITY"),
            ("Workspace", snapshot.workspace_name,
             system_configuration.FIELD_PROVENANCE["workspace_name"]),
            ("Topology", topology_text,
             system_configuration.FIELD_PROVENANCE["topology"]),
            ("Target alias", snapshot.target_alias,
             system_configuration.FIELD_PROVENANCE["target_alias"]),
            ("Identity alias", snapshot.identity_alias,
             system_configuration.FIELD_PROVENANCE["identity_alias"]),
            ("Target class", target_class,
             system_configuration.FIELD_PROVENANCE["target_type"]),
            ("Hardware board type", "NEED-DATA",
             "NO VERIFIED PUBLIC READ MAPPING"),
            ("Firmware / Target Version", snapshot.firmware,
             system_configuration.FIELD_PROVENANCE["firmware"]),
            ("PAL · host extension", snapshot.pal,
             system_configuration.FIELD_PROVENANCE["pal"]),
            ("Boot · host extension", snapshot.boot,
             system_configuration.FIELD_PROVENANCE["boot"]),
            ("Connection type", snapshot.connection_type,
             system_configuration.FIELD_PROVENANCE["connection_type"]),
            ("Host generation · extension", snapshot.generation,
             system_configuration.FIELD_PROVENANCE["generation"]),
            ("Telemetry sequence · extension", snapshot.telemetry_sequence,
             system_configuration.FIELD_PROVENANCE["telemetry_sequence"]),
            ("Motor state · extension", snapshot.motor_enabled,
             system_configuration.FIELD_PROVENANCE["motor_enabled"]),
            ("Observed at UTC · extension", snapshot.observed_at_utc,
             system_configuration.FIELD_PROVENANCE["observed_at_utc"]),
            ("Clock quality · extension", snapshot.clock_quality,
             system_configuration.FIELD_PROVENANCE["clock_quality"]),
            ("Reason", snapshot.reason, "FAIL-CLOSED PROJECTION STATE"),
        )
        self.system_config_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, raw_value in enumerate(row):
                item = QtWidgets.QTableWidgetItem(
                    self._system_config_value(raw_value))
                item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                # QToolTip auto-detects rich text even though table delegates
                # render plain text. Escape the already-sanitized display value
                # so vendor metadata cannot inject markup into hover content.
                item.setToolTip(html.escape(
                    self._system_config_value(raw_value), quote=True))
                self.system_config_table.setItem(row_index, column, item)

    def _system_configuration_changed(self, snapshot=None):
        self._render_system_configuration()
        return snapshot

    def _system_configuration_end(self, reason):
        return self._system_configuration_changed(
            self.system_configuration.end_connection(reason))

    def _system_configuration_revoke(self, reason):
        generation = self.system_configuration.active_generation
        try:
            snapshot = self.system_configuration.revoke_live(
                reason, generation=generation)
        except system_configuration.ProjectionRejected:
            snapshot = self.system_configuration.end_connection(reason)
        return self._system_configuration_changed(snapshot)

    def _system_configuration_accept_telemetry(self, telemetry):
        """Project one UI-admitted envelope without issuing a new drive read."""
        generation = self.session_log.current_generation
        identity = self._connected_identity.get("drive_identity")
        try:
            if self.system_configuration.active_generation == generation:
                snapshot = self.system_configuration.update_telemetry(
                    telemetry, generation=generation,
                    drive_identity=identity)
            else:
                snapshot = self.system_configuration.admit_connection(
                    self._connected_identity, telemetry,
                    generation=generation,
                    connection_type=self.cmb_conn.currentText())
        except system_configuration.ProjectionRejected as exc:
            self._system_configuration_revoke(
                "Projection rejected admitted telemetry: %s" % exc)
            return False
        self._system_configuration_changed(snapshot)
        return True

    def _system_configuration_observer_failed(self):
        """Blank only the Inspector; this observer must never own drive safety."""
        reason = "Inspector observer error; core telemetry remains independent"
        try:
            generation = self.system_configuration.active_generation
            self.system_configuration.revoke_live(
                reason, generation=generation)
        except Exception:
            # If the projection object itself is the failed component, replace
            # it with a clean offline model.  Do not call the normal renderer:
            # the renderer may be the injected/actual failing observer.
            try:
                self.system_configuration = (
                    system_configuration.SystemConfigurationProjection())
            except Exception:
                pass
        try:
            self.lbl_system_config_state.setText(
                "NO CURRENT TARGET · OBSERVER ERROR")
            self.lbl_system_config_state.setProperty("on", "false")
            self.lbl_system_config_state.setProperty("status", "error")
            self._restyle(self.lbl_system_config_state)
            self.system_config_tree.clear()
            root = QtWidgets.QTreeWidgetItem((
                "Workspace · %s" % system_configuration.DEFAULT_WORKSPACE_NAME,))
            root.setFlags(
                root.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.system_config_tree.addTopLevelItem(root)
            self.system_config_table.setRowCount(1)
            for column, value in enumerate((
                    "Projection state", "NO CURRENT TARGET",
                    "INSPECTOR OBSERVER ERROR · CORE AUTHORITY INDEPENDENT")):
                item = QtWidgets.QTableWidgetItem(value)
                item.setFlags(
                    item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
                self.system_config_table.setItem(0, column, item)
        except Exception:
            # The safety callback remains non-throwing even if Qt rendering is
            # the failed observer component.
            pass

    def _build_session_log_page(self):
        """Build a passive viewer over events the UI already received."""
        frame = theme.HudCard()
        outer = QtWidgets.QVBoxLayout(frame)
        outer.setContentsMargins(16, 14, 16, 16); outer.setSpacing(10)

        title_row = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("FAULT / STATUS / SESSION LOG  ·  READ ONLY v0.1")
        title.setProperty("role", "celltitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.lbl_session_log_count = QtWidgets.QLabel("0 events · 0 dropped")
        self.lbl_session_log_count.setObjectName("pill")
        title_row.addWidget(self.lbl_session_log_count)
        title_row.addSpacing(8)
        self.btn_session_export_json = QtWidgets.QPushButton("Export JSON…")
        self.btn_session_export_json.clicked.connect(self._session_log_export_json)
        self._decorate_operation_control(
            self.btn_session_export_json, "session_log.export_json")
        title_row.addWidget(self.btn_session_export_json)
        self.btn_session_export_csv = QtWidgets.QPushButton("Export CSV…")
        self.btn_session_export_csv.clicked.connect(self._session_log_export_csv)
        self._decorate_operation_control(
            self.btn_session_export_csv, "session_log.export_csv")
        title_row.addWidget(self.btn_session_export_csv)
        outer.addLayout(title_row)

        self.lbl_session_log_contract = QtWidgets.QLabel(
            "HOST-OBSERVED / LOCAL MODEL · opening, filtering and export issue no drive command. "
            "This is not drive fault history; Ack, Clear, Reset and fault taxonomy remain NEED-DATA.")
        self.lbl_session_log_contract.setProperty("role", "hint")
        self.lbl_session_log_contract.setWordWrap(True)
        self.lbl_session_log_contract.setMinimumHeight(max(
            48, self.lbl_session_log_contract.sizeHint().height()))
        outer.addWidget(self.lbl_session_log_contract)

        self.session_log_table = QtWidgets.QTableWidget(0, 7)
        self.session_log_table.setHorizontalHeaderLabels((
            "HOST UTC", "EVENT ID", "GEN / SCOPE", "SEVERITY",
            "CATEGORY", "EVENT", "DETACHED EVIDENCE"))
        self.session_log_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.session_log_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.session_log_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.session_log_table.setAlternatingRowColors(True)
        self.session_log_table.setWordWrap(False)
        self.session_log_table.verticalHeader().setVisible(False)
        header = self.session_log_table.horizontalHeader()
        header.setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            4, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            5, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(
            6, QtWidgets.QHeaderView.ResizeMode.Stretch)
        outer.addWidget(self.session_log_table, 1)

        self._render_session_log()
        return frame

    @staticmethod
    def _session_log_detail(row):
        payload = row.get("payload", {}) or {}
        if isinstance(payload, dict):
            for key in ("detail", "reason", "error"):
                if payload.get(key) not in (None, ""):
                    return str(payload[key])[:500]
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"))[:500]

    def _render_session_log(self):
        if not hasattr(self, "session_log_table"):
            return
        rows = tuple(reversed(self.session_log.snapshot()))
        self.session_log_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row.get("host_utc", "—"),
                row.get("event_id", "—"),
                "%s / %s" % (row.get("generation", "—"),
                              row.get("scope", "—")),
                row.get("severity", "UNKNOWN"),
                row.get("category", "—"),
                row.get("name", "—"),
                self._session_log_detail(row),
            )
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(str(value))
                item.setToolTip(
                    "freshness=%s · clock=%s · target=%s" % (
                        row.get("freshness", "UNKNOWN"),
                        row.get("clock_quality", "UNKNOWN"),
                        row.get("target_identity", "REDACTED")))
                if column in (1, 2, 3):
                    item.setTextAlignment(
                        QtCore.Qt.AlignmentFlag.AlignCenter)
                self.session_log_table.setItem(row_index, column, item)
        self.lbl_session_log_count.setText(
            "%d events · %d dropped" %
            (len(rows), self.session_log.dropped_count))

    def _session_log_event_changed(self, event):
        if event is not None:
            self._render_session_log()
        return event

    def _session_log_export_json(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Host-Observed Session Log",
            "angryyjh-session.aysession.json",
            "AngryYJH Session Log (*.aysession.json);;JSON (*.json)")
        if not path:
            return
        try:
            meta = self.session_log.write_json(path)
            self._flash(
                "Session Log JSON saved · %d events · SHA-256 %s…" %
                (len(self.session_log.snapshot()), meta["sha256"][:12]))
        except Exception as exc:
            self._flash("Session Log JSON export failed: %s" % exc)

    def _session_log_export_csv(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Host-Observed Session Log",
            "angryyjh-session.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            meta = self.session_log.write_csv(path)
            self._flash(
                "Session Log CSV saved · %d events · SHA-256 %s…" %
                (len(self.session_log.snapshot()), meta["sha256"][:12]))
        except Exception as exc:
            self._flash("Session Log CSV export failed: %s" % exc)

    def _build_recorder_page(self):
        frame = theme.HudCard()
        outer = QtWidgets.QVBoxLayout(frame)
        outer.setContentsMargins(16, 14, 16, 16); outer.setSpacing(10)
        title_row = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("RECORDER · RECORDING + VIEW DESIGN")
        title.setProperty("role", "celltitle"); title_row.addWidget(title)
        title_row.addStretch(1)
        self.lbl_recorder_page_state = QtWidgets.QLabel("IDLE")
        self.lbl_recorder_page_state.setObjectName("pill")
        title_row.addWidget(self.lbl_recorder_page_state); outer.addLayout(title_row)

        tabs = QtWidgets.QHBoxLayout(); tabs.setSpacing(6)
        self.btn_rec_recording_tab = QtWidgets.QPushButton("Recording · Immediate v1")
        self.btn_rec_view_tab = QtWidgets.QPushButton(
            "View Design · Time + FFT + A:B Statistics")
        for button in (self.btn_rec_recording_tab, self.btn_rec_view_tab):
            button.setCheckable(True); tabs.addWidget(button)
        self.btn_rec_recording_tab.setChecked(True)
        self.btn_rec_view_tab.setEnabled(False)
        self.btn_rec_recording_tab.clicked.connect(self._show_recorder_recording)
        self.btn_rec_view_tab.clicked.connect(self._show_recorder_view)
        tabs.addStretch(1); outer.addLayout(tabs)

        self.recorder_page_stack = QtWidgets.QStackedWidget()
        recording_page = QtWidgets.QWidget()
        recording_layout = QtWidgets.QVBoxLayout(recording_page)
        recording_layout.setContentsMargins(0, 0, 0, 0); recording_layout.setSpacing(8)
        note = QtWidgets.QLabel(
            "Personality의 정확한 신호 이름을 선택해 드라이브의 16K 공유 버퍼에 한 번 기록합니다. "
            "실제 sample interval은 TS readback으로 계산하며, 단위는 추정하지 않습니다. "
            "Rollover·Normal/Auto/Interval·Multi-drive는 의미와 실패 정책이 확인될 때까지 잠겨 있습니다.")
        note.setWordWrap(True); note.setProperty("role", "hint"); recording_layout.addWidget(note)

        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        left = QtWidgets.QWidget(); lv = QtWidgets.QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 6, 0)
        lv.addWidget(QtWidgets.QLabel("PERSONALITY SIGNALS · check channels to record"))
        self.rec_signal_list = QtWidgets.QListWidget()
        self.rec_signal_list.itemChanged.connect(self._update_recorder_controls)
        lv.addWidget(self.rec_signal_list, 1)
        self.lbl_rec_signal_count = QtWidgets.QLabel("0 selected · 0 discovered")
        self.lbl_rec_signal_count.setProperty("role", "hint")
        lv.addWidget(self.lbl_rec_signal_count)
        split.addWidget(left)

        right = QtWidgets.QWidget(); rv = QtWidgets.QVBoxLayout(right)
        rv.setContentsMargins(6, 0, 0, 0)
        rv.addWidget(QtWidgets.QLabel("CAPTURE EVIDENCE / DATA SUMMARY"))
        self.recorder_log = QtWidgets.QPlainTextEdit()
        self.recorder_log.setReadOnly(True)
        self.recorder_log.setPlainText(
            "IDLE\n\nUse Select Personality Signals… to read the connected drive personality.\n"
            "Recorder Stop affects recording only; DRIVE STOP affects motion only.")
        rv.addWidget(self.recorder_log, 1)
        actions = QtWidgets.QHBoxLayout()
        self.btn_rec_export = QtWidgets.QPushButton("Export raw CSV…")
        self.btn_rec_export.setEnabled(False)
        self.btn_rec_export.clicked.connect(self._recorder_export_csv)
        open_map = QtWidgets.QPushButton("Open feature map")
        open_map.clicked.connect(self._open_recorder_feature_map)
        actions.addWidget(self.btn_rec_export); actions.addWidget(open_map); actions.addStretch(1)
        rv.addLayout(actions); split.addWidget(right)
        split.setStretchFactor(0, 1); split.setStretchFactor(1, 2)
        recording_layout.addWidget(split, 1)
        self.recorder_page_stack.addWidget(recording_page)

        view_page = QtWidgets.QWidget()
        view_page.setObjectName("recorderViewPage")
        view_page.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        view_page.setStyleSheet(
            "QWidget#recorderViewPage { background: %s; }" % theme.CARD)
        view_layout = QtWidgets.QVBoxLayout(view_page)
        view_layout.setContentsMargins(0, 0, 0, 0); view_layout.setSpacing(8)
        self.lbl_rec_view_status = QtWidgets.QLabel(
            "No validated capture · View Design remains read-only and locked")
        self.lbl_rec_view_status.setProperty("role", "hint")
        self.lbl_rec_view_status.setWordWrap(True)
        view_layout.addWidget(self.lbl_rec_view_status)

        controls = QtWidgets.QHBoxLayout(); controls.setSpacing(7)
        controls.addWidget(QtWidgets.QLabel("Chart 1"))
        self.chk_rec_view_lane_a = QtWidgets.QCheckBox("Show")
        self.chk_rec_view_lane_a.setEnabled(False)
        controls.addWidget(self.chk_rec_view_lane_a)
        self.rec_view_lane_a = QtWidgets.QComboBox(); self.rec_view_lane_a.setEnabled(False)
        controls.addWidget(self.rec_view_lane_a, 1)
        controls.addWidget(QtWidgets.QLabel("Chart 2"))
        self.chk_rec_view_lane_b = QtWidgets.QCheckBox("Show")
        self.chk_rec_view_lane_b.setEnabled(False)
        controls.addWidget(self.chk_rec_view_lane_b)
        self.rec_view_lane_b = QtWidgets.QComboBox(); self.rec_view_lane_b.setEnabled(False)
        controls.addWidget(self.rec_view_lane_b, 1)
        self.btn_rec_view_open = QtWidgets.QPushButton("Open Local View…")
        self.btn_rec_view_save = QtWidgets.QPushButton("Save Local View…")
        self.btn_rec_view_open.setEnabled(False); self.btn_rec_view_save.setEnabled(False)
        controls.addWidget(self.btn_rec_view_open); controls.addWidget(self.btn_rec_view_save)
        view_layout.addLayout(controls)
        self.rec_view_lane_a.currentIndexChanged.connect(self._recorder_view_lane_changed)
        self.rec_view_lane_b.currentIndexChanged.connect(self._recorder_view_lane_changed)
        self.chk_rec_view_lane_a.stateChanged.connect(
            self._recorder_view_visibility_changed)
        self.chk_rec_view_lane_b.stateChanged.connect(
            self._recorder_view_visibility_changed)
        self.btn_rec_view_open.clicked.connect(self._recorder_open_view_layout)
        self.btn_rec_view_save.clicked.connect(self._recorder_save_view_layout)

        display = QtWidgets.QHBoxLayout(); display.setSpacing(7)
        display.addWidget(QtWidgets.QLabel("DISPLAY"))
        self.btn_rec_view_time = QtWidgets.QPushButton("Time Waveform")
        self.btn_rec_view_fft = QtWidgets.QPushButton(
            "FFT Magnitude · Full Capture")
        self._recorder_plot_mode_group = QtWidgets.QButtonGroup(self)
        self._recorder_plot_mode_group.setExclusive(True)
        for button in (self.btn_rec_view_time, self.btn_rec_view_fft):
            button.setCheckable(True)
            button.setEnabled(False)
            self._recorder_plot_mode_group.addButton(button)
            display.addWidget(button)
        self.btn_rec_view_time.setChecked(True)
        self.lbl_rec_plot_contract = QtWidgets.QLabel("NO CAPTURE")
        self.lbl_rec_plot_contract.setProperty("role", "hint")
        self.lbl_rec_plot_contract.setWordWrap(True)
        display.addWidget(self.lbl_rec_plot_contract, 1)
        view_layout.addLayout(display)
        self.btn_rec_view_time.clicked.connect(
            lambda _checked=False: self._recorder_set_plot_mode(
                recorder_view.PLOT_MODE_TIME))
        self.btn_rec_view_fft.clicked.connect(
            lambda _checked=False: self._recorder_set_plot_mode(
                recorder_view.PLOT_MODE_FFT))

        zoom = QtWidgets.QHBoxLayout(); zoom.setSpacing(7)
        zoom.addWidget(QtWidgets.QLabel("MANUAL TIME WINDOW [s]"))
        self.edit_rec_time_start = QtWidgets.QLineEdit()
        self.edit_rec_time_start.setPlaceholderText("start")
        self.edit_rec_time_start.setMaximumWidth(115)
        self.edit_rec_time_end = QtWidgets.QLineEdit()
        self.edit_rec_time_end.setPlaceholderText("end")
        self.edit_rec_time_end.setMaximumWidth(115)
        self.btn_rec_time_apply_all = QtWidgets.QPushButton(
            "Apply Time Window → Both Charts")
        self.btn_rec_time_full = QtWidgets.QPushButton("Reset Full Time")
        self.lbl_rec_time_mode = QtWidgets.QLabel("NO CAPTURE")
        self.lbl_rec_time_mode.setProperty("role", "hint")
        for widget in (
                self.edit_rec_time_start, self.edit_rec_time_end,
                self.btn_rec_time_apply_all, self.btn_rec_time_full):
            widget.setEnabled(False)
        self.btn_rec_time_apply_all.setToolTip(
            "Display-only shared X(time) viewport. No drive command; Y ranges are not copied.")
        self.btn_rec_time_full.setToolTip(
            "Return both charts to the full captured time range.")
        zoom.addWidget(self.edit_rec_time_start)
        zoom.addWidget(QtWidgets.QLabel("to"))
        zoom.addWidget(self.edit_rec_time_end)
        zoom.addWidget(self.btn_rec_time_apply_all)
        zoom.addWidget(self.btn_rec_time_full)
        zoom.addWidget(self.lbl_rec_time_mode)
        zoom.addStretch(1)
        view_layout.addLayout(zoom)
        self.btn_rec_time_apply_all.clicked.connect(
            self._recorder_apply_time_zoom)
        self.btn_rec_time_full.clicked.connect(
            self._recorder_reset_time_zoom)

        sample_range = QtWidgets.QHBoxLayout()
        sample_range.setSpacing(7)
        self.lbl_rec_range_title = QtWidgets.QLabel(
            "LOCAL SAMPLE RANGE A:B · MOUSE DRAG / INDEX · INCLUSIVE")
        self.lbl_rec_range_title.setToolTip(
            "Drag an A or B line in either Time chart. It snaps to the nearest "
            "visible original sample; exact ties use the lower index. Index "
            "spinboxes remain authoritative. EAS glyphs, shortcuts, and "
            "persistence are not claimed.")
        sample_range.addWidget(self.lbl_rec_range_title)
        sample_range.addWidget(QtWidgets.QLabel("A"))
        self.spin_rec_range_start = QtWidgets.QSpinBox()
        self.spin_rec_range_start.setRange(0, 0)
        self.spin_rec_range_start.setEnabled(False)
        self.spin_rec_range_start.setMaximumWidth(100)
        sample_range.addWidget(self.spin_rec_range_start)
        sample_range.addWidget(QtWidgets.QLabel("B"))
        self.spin_rec_range_end = QtWidgets.QSpinBox()
        self.spin_rec_range_end.setRange(0, 0)
        self.spin_rec_range_end.setEnabled(False)
        self.spin_rec_range_end.setMaximumWidth(100)
        sample_range.addWidget(self.spin_rec_range_end)
        self.btn_rec_range_calculate = QtWidgets.QPushButton(
            "Calculate A:B Range")
        self.btn_rec_range_calculate.setEnabled(False)
        self.btn_rec_range_calculate.setToolTip(
            "Read-only inclusive statistics over exact integer sample indexes. "
            "N = B - A + 1; display zoom and FFT bins are not inputs.")
        sample_range.addWidget(self.btn_rec_range_calculate)
        self.btn_rec_range_full = QtWidgets.QPushButton(
            "A=First · B=Last")
        self.btn_rec_range_full.setEnabled(False)
        sample_range.addWidget(self.btn_rec_range_full)
        self.lbl_rec_range_scope = QtWidgets.QLabel("NO CAPTURE")
        self.lbl_rec_range_scope.setProperty("role", "hint")
        self.lbl_rec_range_scope.setWordWrap(True)
        sample_range.addWidget(self.lbl_rec_range_scope, 1)
        view_layout.addLayout(sample_range)
        self.spin_rec_range_start.valueChanged.connect(
            self._recorder_range_changed)
        self.spin_rec_range_end.valueChanged.connect(
            self._recorder_range_changed)
        self.btn_rec_range_calculate.clicked.connect(
            self._recorder_calculate_range_statistics)
        self.btn_rec_range_full.clicked.connect(
            self._recorder_reset_sample_range)

        statistics_header = QtWidgets.QHBoxLayout()
        statistics_header.setSpacing(7)
        self.lbl_rec_stats_title = QtWidgets.QLabel(
            "SIGNAL STATISTICS · FULL/A:B · EAS FIELD/FORMULA STATIC-IL")
        self.lbl_rec_stats_title.setToolTip(
            "Verified against installed EAS 3.0.0.26 runtime IL: nearest-sample "
            "endpoint/delta and RMS/Tolerance % formulas. This is not full EAS UI/file parity.")
        statistics_header.addWidget(self.lbl_rec_stats_title)
        self.btn_rec_stats_calculate = QtWidgets.QPushButton(
            "Calculate Full Capture Statistics")
        self.btn_rec_stats_calculate.setEnabled(False)
        self.btn_rec_stats_calculate.setToolTip(
            "Read-only calculation over every exact captured sample. "
            "It does not use the visible Time window or FFT bins. "
            "Installed EAS runtime IL verifies divide-by-N before square root.")
        statistics_header.addWidget(self.btn_rec_stats_calculate)
        self.btn_rec_stats_export = QtWidgets.QPushButton(
            "Export Statistics CSV…")
        self.btn_rec_stats_export.setEnabled(False)
        self.btn_rec_stats_export.setToolTip(
            "Export this exact DERIVED result with capture identity, source "
            "SHA-256, range, and current/historical authority. Local CSV only; "
            "not EAS Save As compatible.")
        self.btn_rec_stats_export.clicked.connect(
            self._recorder_export_statistics_csv)
        statistics_header.addWidget(self.btn_rec_stats_export)
        self.lbl_rec_stats_scope = QtWidgets.QLabel("NO CAPTURE")
        self.lbl_rec_stats_scope.setProperty("role", "hint")
        self.lbl_rec_stats_scope.setWordWrap(True)
        statistics_header.addWidget(self.lbl_rec_stats_scope, 1)
        view_layout.addLayout(statistics_header)

        self.rec_stats_table = QtWidgets.QTableWidget(0, 9)
        self.rec_stats_table.setHorizontalHeaderLabels((
            "Signal", "N (local samples)", "Min", "Max", "Average",
            "RMS AC", "RMS DC", "Tolerance", "Tolerance %",
        ))
        self.rec_stats_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rec_stats_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.rec_stats_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.rec_stats_table.setAlternatingRowColors(True)
        self.rec_stats_table.verticalHeader().setVisible(False)
        stats_header = self.rec_stats_table.horizontalHeader()
        stats_header.setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column in range(1, 9):
            stats_header.setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.btn_rec_stats_calculate.clicked.connect(
            self._recorder_calculate_statistics)

        self.rec_range_values_table = QtWidgets.QTableWidget(0, 9)
        self.rec_range_values_table.setHorizontalHeaderLabels((
            "Signal", "A sample", "A time [s]", "A value",
            "B sample", "B time [s]", "B value", "Δ time [s]", "Δ value",
        ))
        self.rec_range_values_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rec_range_values_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.rec_range_values_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.rec_range_values_table.setAlternatingRowColors(True)
        self.rec_range_values_table.verticalHeader().setVisible(False)
        endpoint_header = self.rec_range_values_table.horizontalHeader()
        endpoint_header.setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for column in range(1, 9):
            endpoint_header.setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.rec_range_values_table.setMaximumHeight(150)
        self.lbl_rec_range_values_scope = QtWidgets.QLabel(
            "SIGNAL VALUES · calculate a valid A:B range")
        self.lbl_rec_range_values_scope.setProperty("role", "hint")
        self.lbl_rec_range_values_scope.setWordWrap(True)

        statistics_page = QtWidgets.QWidget()
        statistics_layout = QtWidgets.QVBoxLayout(statistics_page)
        statistics_layout.setContentsMargins(0, 0, 0, 0)
        statistics_layout.setSpacing(5)
        statistics_layout.addWidget(self.lbl_rec_range_values_scope)
        statistics_layout.addWidget(self.rec_range_values_table)
        statistics_layout.addWidget(self.rec_stats_table, 1)

        self.recorder_plot = RecorderPlotWidget()
        self.recorder_plot.sampleRangePreview.connect(
            self._recorder_plot_range_preview)
        self.recorder_plot.sampleRangeCommitted.connect(
            self._recorder_plot_range_committed)
        self.rec_view_analysis_tabs = QtWidgets.QTabWidget()
        self.rec_view_analysis_tabs.addTab(
            self.recorder_plot, "Charts · Time / FFT")
        self.rec_view_analysis_tabs.addTab(
            statistics_page, "Signal Values + Statistics · Full / A:B")
        self.rec_view_analysis_tabs.setCurrentIndex(0)
        analysis_surface = getattr(theme, "INSET", theme.CARD_SOFT)
        analysis_selected = getattr(theme, "INDIGO_DK", theme.INDIGO)
        self.rec_view_analysis_tabs.setStyleSheet("""
            QTabWidget::pane {{
                background: {surface}; border: 1px solid {border};
                border-radius: 7px; top: -1px;
            }}
            QTabBar::tab {{
                background: {soft}; color: {muted};
                border: 1px solid {border}; padding: 7px 15px;
                margin-right: 3px;
            }}
            QTabBar::tab:selected {{
                background: {selected}; color: {text};
                border-color: {accent};
            }}
            QTableWidget {{
                background: {surface}; alternate-background-color: {soft};
                color: {text}; gridline-color: {border}; border: none;
                selection-background-color: {selected};
                selection-color: {text};
            }}
            QHeaderView::section {{
                background: {card}; color: {muted};
                border: none; border-right: 1px solid {border};
                border-bottom: 1px solid {border}; padding: 7px 6px;
                font-weight: 700;
            }}
            QTableCornerButton::section {{
                background: {card}; border: none;
                border-right: 1px solid {border};
                border-bottom: 1px solid {border};
            }}
        """.format(
            surface=analysis_surface,
            soft=theme.CARD_SOFT,
            card=theme.CARD,
            border=theme.BORDER,
            muted=theme.MUTED,
            text=theme.TEXT,
            selected=analysis_selected,
            accent=theme.INDIGO,
        ))
        view_layout.addWidget(self.rec_view_analysis_tabs, 1)
        compatibility = QtWidgets.QLabel(
            "LOCAL STAND-IN · not EAS-file compatible · exact Personality names · "
            "FULL 16K-bounded Time/FFT render · raw CSV remains analysis evidence · "
            "Manual Zoom copies X(time) only · FFT uses full capture and preserves "
            "that saved time window · EAS generic Zero Scale means Y starts at 0; "
            "FFT numeric convention remains NEED-DATA · Statistics are DERIVED "
            "from full or exact inclusive A:B samples and never replace raw evidence · "
            "A/B line drag snaps to visible original samples (lower-index tie) · "
            "Statistics CSV is atomic, source-hashed, authority-labelled, and LOCAL ONLY · "
            "endpoint/delta/RMS/Tolerance % semantics are STATIC-IL VERIFIED against "
            "installed EAS 3.0.0.26")
        compatibility.setProperty("role", "hint"); compatibility.setWordWrap(True)
        view_layout.addWidget(compatibility)
        self.recorder_page_stack.addWidget(view_page)
        outer.addWidget(self.recorder_page_stack, 1)
        self._recorder_view_layout_path = None
        return frame

    def _show_recorder_recording(self):
        self.recorder_page_stack.setCurrentIndex(0)
        self.btn_rec_recording_tab.setChecked(True)
        self.btn_rec_view_tab.setChecked(False)
        self.btn_rec_context.setText("Recording · Immediate v1")
        self.btn_rec_context.setChecked(True)

    def _show_recorder_view(self):
        if self._recorder_view_model is None:
            self._show_recorder_recording()
            self._flash("View Design은 검증 완료된 Recorder capture 후 사용할 수 있습니다.")
            return
        self.recorder_page_stack.setCurrentIndex(1)
        self.btn_rec_recording_tab.setChecked(False)
        self.btn_rec_view_tab.setChecked(True)
        self.btn_rec_context.setText(
            "View Design · Time + FFT + A:B Statistics")
        self.btn_rec_context.setChecked(True)

    def _recorder_view_lane_changed(self, _index=0):
        if self._recorder_view_model is None:
            return
        first = self.rec_view_lane_a.currentData()
        second = self.rec_view_lane_b.currentData()
        self.recorder_plot.set_lanes(first, second)

    def _recorder_view_visibility_changed(self, _state=0):
        model = self._recorder_view_model
        current = self.recorder_plot.layout_model
        if model is None or current is None:
            return
        visibility = (
            self.chk_rec_view_lane_a.isChecked(),
            self.chk_rec_view_lane_b.isChecked(),
        )
        lanes = tuple(
            recorder_view.LaneLayout(
                channels=lane.channels,
                visible=visible,
                y_range=lane.y_range,
            )
            for lane, visible in zip(current.lanes, visibility)
        )
        self.recorder_plot.set_view_model(
            model,
            recorder_view.ViewLayout(
                lanes,
                x_range_s=current.x_range_s,
                plot_mode=current.plot_mode,
            ),
        )

    def _populate_recorder_view_controls(self, model, layout=None):
        names = tuple(model.signals)
        if layout is None:
            layout = recorder_view.ViewLayout((
                recorder_view.LaneLayout(names[:1]),
                recorder_view.LaneLayout(names[1:2]),
            ))
        combos = (self.rec_view_lane_a, self.rec_view_lane_b)
        visibility_controls = (
            self.chk_rec_view_lane_a, self.chk_rec_view_lane_b)
        for combo, visibility, lane in zip(
                combos, visibility_controls, layout.lanes):
            combo.blockSignals(True)
            visibility.blockSignals(True)
            combo.clear(); combo.addItem("— no signal —", None)
            for name in names:
                combo.addItem(name, name)
            selected = lane.channels[0] if lane.channels else None
            combo.setCurrentIndex(max(0, combo.findData(selected)))
            combo.setEnabled(True)
            visibility.setChecked(lane.visible)
            visibility.setEnabled(True)
            combo.blockSignals(False)
            visibility.blockSignals(False)
        self.recorder_plot.set_view_model(model, layout)
        self._configure_recorder_sample_range(model)
        self._sync_recorder_plot_mode_controls(
            self.recorder_plot.layout_model)
        self._sync_recorder_time_zoom_controls(
            self.recorder_plot.layout_model)
        self._sync_recorder_sample_range_controls()
        statistics = self._recorder_statistics_model
        if (statistics is None
                or statistics.binding != model.binding
                or self._recorder_statistics_source_view is not model):
            self._reset_recorder_statistics(has_capture=True)
        else:
            self.btn_rec_stats_calculate.setEnabled(True)
        self.btn_rec_view_open.setEnabled(True)
        self.btn_rec_view_save.setEnabled(True)

    def _recorder_set_plot_mode(self, plot_mode):
        model = self._recorder_view_model
        current = self.recorder_plot.layout_model
        if model is None or current is None:
            self._sync_recorder_plot_mode_controls(None)
            self._flash(
                "Time/FFT display requires a validated completed capture.")
            return
        try:
            layout = recorder_view.set_plot_mode(
                current, model, plot_mode)
            self.recorder_plot.set_view_model(model, layout)
        except Exception as exc:
            self._sync_recorder_plot_mode_controls(current)
            self._sync_recorder_time_zoom_controls(current)
            self._sync_recorder_sample_range_controls()
            self._flash("Recorder display mode rejected: %s" % exc)
            return
        applied = self.recorder_plot.layout_model
        self.rec_view_analysis_tabs.setCurrentIndex(0)
        self._sync_recorder_plot_mode_controls(applied)
        self._sync_recorder_time_zoom_controls(applied)
        self._sync_recorder_sample_range_controls()
        if plot_mode == recorder_view.PLOT_MODE_FFT:
            self._flash(
                "Local FFT STAND-IN · full capture · DC included · Y lower bound 0")
        else:
            self._flash("Time waveform restored · saved time window preserved")

    def _sync_recorder_plot_mode_controls(self, layout=None):
        model = self._recorder_view_model
        has_capture = model is not None
        fft_capable = bool(
            has_capture and model.display_sample_count >= 2)
        self.btn_rec_view_time.setEnabled(has_capture)
        self.btn_rec_view_fft.setEnabled(fft_capable)

        layout = layout or self.recorder_plot.layout_model
        plot_mode = (
            layout.plot_mode if layout is not None
            else recorder_view.PLOT_MODE_TIME)
        if plot_mode == recorder_view.PLOT_MODE_FFT and not fft_capable:
            plot_mode = recorder_view.PLOT_MODE_TIME
        for button in (self.btn_rec_view_time, self.btn_rec_view_fft):
            button.blockSignals(True)
        self.btn_rec_view_time.setChecked(
            plot_mode == recorder_view.PLOT_MODE_TIME)
        self.btn_rec_view_fft.setChecked(
            plot_mode == recorder_view.PLOT_MODE_FFT)
        for button in (self.btn_rec_view_time, self.btn_rec_view_fft):
            button.blockSignals(False)

        if not has_capture:
            self.lbl_rec_plot_contract.setText("NO CAPTURE")
        elif plot_mode == recorder_view.PLOT_MODE_FFT:
            self.lbl_rec_plot_contract.setText(
                "FFT · ONE-SIDED PEAK · RECTANGULAR · DC INCLUDED · "
                "FULL CAPTURE · Y STARTS AT 0 · LOCAL STAND-IN")
        else:
            self.lbl_rec_plot_contract.setText(
                "TIME · exact samples · exponent axes when span < 0.001")

    def _sync_recorder_time_zoom_controls(self, layout=None):
        model = self._recorder_view_model
        layout = layout or self.recorder_plot.layout_model
        time_mode = bool(
            layout is None
            or layout.plot_mode == recorder_view.PLOT_MODE_TIME)
        capable = bool(
            model is not None and model.display_sample_count >= 2
            and time_mode)
        for widget in (
                self.edit_rec_time_start, self.edit_rec_time_end,
                self.btn_rec_time_apply_all, self.btn_rec_time_full):
            widget.setEnabled(capable)
        if model is None:
            self.edit_rec_time_start.clear(); self.edit_rec_time_end.clear()
            self.lbl_rec_time_mode.setText("NO CAPTURE")
            return
        if layout is None or layout.x_range_s is None:
            low, high = model.x_s[0], model.x_s[-1]
            mode = "FULL TIME · raw capture domain"
        else:
            low, high = layout.x_range_s
            mode = "MANUAL TIME · shared by both charts"
        self.edit_rec_time_start.setText("%.12g" % low)
        self.edit_rec_time_end.setText("%.12g" % high)
        if not time_mode:
            self.lbl_rec_time_mode.setText(
                "FFT · FULL CAPTURE · saved time window preserved")
        elif model.display_sample_count < 2:
            self.lbl_rec_time_mode.setText(
                "TIME · SINGLE SAMPLE · manual zoom unavailable")
        else:
            self.lbl_rec_time_mode.setText(mode)

    def _clear_recorder_statistics_result(self, *, select_charts):
        """Clear derived rows without changing capture, range, or CSV authority."""
        self._recorder_statistics_model = None
        self._recorder_statistics_source_view = None
        if hasattr(self, "btn_rec_stats_export"):
            self.btn_rec_stats_export.setEnabled(False)
        self.rec_stats_table.clearContents()
        self.rec_stats_table.setRowCount(0)
        self.rec_range_values_table.clearContents()
        self.rec_range_values_table.setRowCount(0)
        self.lbl_rec_range_values_scope.setText(
            "SIGNAL VALUES · calculate a valid A:B range")
        if select_charts:
            self.rec_view_analysis_tabs.setCurrentIndex(0)

    def _sync_recorder_statistics_export(self):
        model = self._recorder_view_model
        result = self._recorder_statistics_model
        evidence = self._recorder_capture_evidence
        enabled = bool(
            model is not None
            and result is not None
            and self._recorder_statistics_source_view is model
            and result.binding == model.binding
            and isinstance(evidence, recorder_view.CaptureEvidence)
            and evidence.view is model
        )
        self.btn_rec_stats_export.setEnabled(enabled)

    def _configure_recorder_sample_range(self, model):
        """Bind A/B controls to one exact view object, never just its IDs."""
        if model is None:
            self._recorder_range_selection = None
            self._recorder_range_source_view = None
            for spin in (
                    self.spin_rec_range_start, self.spin_rec_range_end):
                spin.blockSignals(True)
                spin.setRange(0, 0); spin.setValue(0); spin.setEnabled(False)
                spin.blockSignals(False)
            self.btn_rec_range_calculate.setEnabled(False)
            self.btn_rec_range_full.setEnabled(False)
            self.lbl_rec_range_scope.setText("NO CAPTURE")
            self.recorder_plot.set_sample_range(None)
            return
        if self._recorder_range_source_view is model:
            self.recorder_plot.set_sample_range(
                self._recorder_range_selection)
            return

        count = model.display_sample_count
        maximum = max(0, count - 1)
        for spin in (self.spin_rec_range_start, self.spin_rec_range_end):
            spin.blockSignals(True); spin.setRange(0, maximum)
        self.spin_rec_range_start.setValue(0)
        self.spin_rec_range_end.setValue(maximum)
        for spin in (self.spin_rec_range_start, self.spin_rec_range_end):
            spin.blockSignals(False)
        self._recorder_range_source_view = model
        if count >= 2:
            self._recorder_range_selection = (
                recorder_view.build_sample_range_selection(
                    model, start_index=0, end_index=maximum))
        else:
            self._recorder_range_selection = None
        self.recorder_plot.set_sample_range(
            self._recorder_range_selection)

    def _sync_recorder_sample_range_controls(self):
        model = self._recorder_view_model
        layout = self.recorder_plot.layout_model
        capable = bool(
            model is not None and model.display_sample_count >= 2)
        time_mode = bool(
            layout is None
            or layout.plot_mode == recorder_view.PLOT_MODE_TIME)
        editable = capable and time_mode
        self.spin_rec_range_start.setEnabled(editable)
        self.spin_rec_range_end.setEnabled(editable)
        self.btn_rec_range_full.setEnabled(editable)
        selection = self._recorder_range_selection
        valid = bool(
            selection is not None
            and self._recorder_range_source_view is model
            and selection.start_index == self.spin_rec_range_start.value()
            and selection.end_index == self.spin_rec_range_end.value())
        self.btn_rec_range_calculate.setEnabled(editable and valid)
        if model is None:
            self.lbl_rec_range_scope.setText("NO CAPTURE")
        elif not capable:
            self.lbl_rec_range_scope.setText(
                "UNAVAILABLE · EAS range requires A < B · at least two samples")
        elif not time_mode:
            self.lbl_rec_range_scope.setText(
                "FFT · A/B selection preserved · switch to Time Waveform to edit")
        elif not valid:
            self.lbl_rec_range_scope.setText(
                "INVALID · A must be less than B · no stale range result shown")
        else:
            authority = (
                "CURRENT" if self._recorder_view_is_current
                else "HISTORICAL / OFFLINE")
            self.lbl_rec_range_scope.setText(
                "READY · A #%d @ %.12g s · B #%d @ %.12g s · N=%d · "
                "INCLUSIVE · %s" % (
                    selection.start_index, selection.start_time_s,
                    selection.end_index, selection.end_time_s,
                    selection.sample_count, authority))

    def _recorder_range_changed(self, _value=0):
        model = self._recorder_view_model
        if model is None or self._recorder_range_source_view is not model:
            self._sync_recorder_sample_range_controls()
            return
        if self._recorder_statistics_model is not None:
            self._clear_recorder_statistics_result(select_charts=False)
            self.lbl_rec_stats_scope.setText(
                "READY · range changed · previous derived rows cleared")
        try:
            selection = recorder_view.build_sample_range_selection(
                model,
                start_index=self.spin_rec_range_start.value(),
                end_index=self.spin_rec_range_end.value())
        except Exception:
            selection = None
        self._recorder_range_selection = selection
        self.recorder_plot.set_sample_range(selection)
        self._sync_recorder_sample_range_controls()

    def _recorder_plot_range_preview(
            self, source_view, start_index, end_index):
        """Accept one capture-object-bound mouse preview without drive I/O."""
        model = self._recorder_view_model
        layout = self.recorder_plot.layout_model
        if (source_view is not model
                or source_view is not self.recorder_plot.view_model
                or self._recorder_range_source_view is not model
                or layout is None
                or layout.plot_mode != recorder_view.PLOT_MODE_TIME):
            return
        try:
            selection = recorder_view.build_sample_range_selection(
                model,
                start_index=start_index,
                end_index=end_index,
            )
        except recorder_view.RecorderViewError:
            return
        for spin in (self.spin_rec_range_start, self.spin_rec_range_end):
            spin.blockSignals(True)
        self.spin_rec_range_start.setValue(start_index)
        self.spin_rec_range_end.setValue(end_index)
        for spin in (self.spin_rec_range_start, self.spin_rec_range_end):
            spin.blockSignals(False)
        if self._recorder_statistics_model is not None:
            self._clear_recorder_statistics_result(select_charts=False)
            self.lbl_rec_stats_scope.setText(
                "READY · mouse range changed · previous derived rows cleared")
        self._recorder_range_selection = selection
        self._recorder_range_source_view = model
        self.recorder_plot.set_sample_range(selection)
        self._sync_recorder_sample_range_controls()

    def _recorder_plot_range_committed(
            self, source_view, start_index, end_index):
        """Calculate the snapped inclusive result once when a drag is released."""
        selection = self._recorder_range_selection
        if (source_view is not self._recorder_view_model
                or source_view is not self.recorder_plot.view_model
                or self._recorder_range_source_view is not source_view
                or not isinstance(
                    selection, recorder_view.SampleRangeSelection)
                or selection.start_index != start_index
                or selection.end_index != end_index):
            return
        self._recorder_calculate_range_statistics()

    def _recorder_reset_sample_range(self):
        model = self._recorder_view_model
        if model is None or model.display_sample_count < 2:
            self._sync_recorder_sample_range_controls()
            return
        for spin in (self.spin_rec_range_start, self.spin_rec_range_end):
            spin.blockSignals(True)
        self.spin_rec_range_start.setValue(0)
        self.spin_rec_range_end.setValue(model.display_sample_count - 1)
        for spin in (self.spin_rec_range_start, self.spin_rec_range_end):
            spin.blockSignals(False)
        self._recorder_range_changed()

    def _reset_recorder_statistics(self, *, has_capture):
        """Clear derived rows without changing capture or CSV authority."""
        self._clear_recorder_statistics_result(select_charts=True)
        if not has_capture:
            self._configure_recorder_sample_range(None)
        capable = bool(
            has_capture
            and self._recorder_view_model is not None
            and self._recorder_view_model.display_sample_count >= 2)
        self.btn_rec_stats_calculate.setEnabled(capable)
        if capable:
            self.lbl_rec_stats_scope.setText(
                "READY · FULL OR A:B · RMS + Tolerance % STATIC-IL VERIFIED")
        elif has_capture:
            self.lbl_rec_stats_scope.setText(
                "UNAVAILABLE · EAS statistics requires AT LEAST TWO SAMPLES")
        else:
            self.lbl_rec_stats_scope.setText("NO CAPTURE")
        self._sync_recorder_sample_range_controls()

    @staticmethod
    def _format_recorder_statistic(value):
        if value is None:
            return "N/A"
        return "%.12g" % float(value)

    def _render_recorder_statistics(self, result):
        model = self._recorder_view_model
        self.rec_stats_table.setRowCount(len(result.rows))
        for row_index, row in enumerate(result.rows):
            values = (
                row.name,
                str(row.sample_count),
                self._format_recorder_statistic(row.minimum),
                self._format_recorder_statistic(row.maximum),
                self._format_recorder_statistic(row.average),
                self._format_recorder_statistic(row.rms_ac),
                self._format_recorder_statistic(row.rms_dc),
                self._format_recorder_statistic(row.tolerance),
                self._format_recorder_statistic(row.tolerance_percent),
            )
            for column, text in enumerate(values):
                item = QtWidgets.QTableWidgetItem(text)
                if column > 0:
                    item.setTextAlignment(
                        int(QtCore.Qt.AlignmentFlag.AlignRight
                            | QtCore.Qt.AlignmentFlag.AlignVCenter))
                self.rec_stats_table.setItem(row_index, column, item)

        selection = result.selection
        self.rec_range_values_table.clearContents()
        self.rec_range_values_table.setRowCount(len(result.endpoints))
        if selection is None:
            self.lbl_rec_range_values_scope.setText(
                "SIGNAL VALUES · FULL CAPTURE result · choose A:B for endpoints")
        else:
            for row_index, endpoint in enumerate(result.endpoints):
                values = (
                    endpoint.name,
                    str(selection.start_index),
                    self._format_recorder_statistic(selection.start_time_s),
                    self._format_recorder_statistic(endpoint.start_value),
                    str(selection.end_index),
                    self._format_recorder_statistic(selection.end_time_s),
                    self._format_recorder_statistic(endpoint.end_value),
                    self._format_recorder_statistic(selection.delta_time_s),
                    self._format_recorder_statistic(endpoint.delta_value),
                )
                for column, text in enumerate(values):
                    item = QtWidgets.QTableWidgetItem(text)
                    if column > 0:
                        item.setTextAlignment(
                            int(QtCore.Qt.AlignmentFlag.AlignRight
                                | QtCore.Qt.AlignmentFlag.AlignVCenter))
                    self.rec_range_values_table.setItem(
                        row_index, column, item)
            self.lbl_rec_range_values_scope.setText(
                "SIGNAL VALUES · exact endpoints · A #%d / B #%d · "
                "personality-owned units" % (
                    selection.start_index, selection.end_index))

        self._recorder_statistics_model = result
        self._recorder_statistics_source_view = model
        self._sync_recorder_statistics_export()
        self.rec_view_analysis_tabs.setCurrentIndex(1)
        authority = (
            "CURRENT" if self._recorder_view_is_current
            else "HISTORICAL / OFFLINE")
        if selection is None:
            scope = "FULL CAPTURE"
        else:
            scope = "SAMPLE RANGE A:B · INCLUSIVE · N=%d" % (
                selection.sample_count)
        self.lbl_rec_stats_scope.setText(
            "DERIVED · %s · %s · RMS STATIC-IL VERIFIED · "
            "Tolerance %% STATIC-IL VERIFIED · units not inferred" % (
                scope, authority))

    def _recorder_calculate_statistics(self):
        """Populate documented fields with local math; never touch the worker."""
        model = self._recorder_view_model
        if model is None:
            self._reset_recorder_statistics(has_capture=False)
            self._flash(
                "Signal Statistics requires a validated completed capture.")
            return
        try:
            result = recorder_view.build_full_capture_statistics(model)
        except Exception as exc:
            self._clear_recorder_statistics_result(select_charts=False)
            self.btn_rec_stats_calculate.setEnabled(True)
            self.lbl_rec_stats_scope.setText(
                "UNAVAILABLE · statistics rejected · capture/CSV retained")
            self.rec_view_analysis_tabs.setCurrentIndex(1)
            self._flash("Signal Statistics rejected: %s" % exc)
            return
        self._render_recorder_statistics(result)
        self._flash(
            "Full-capture Signal Statistics calculated · read-only · raw CSV unchanged")

    def _recorder_calculate_range_statistics(self):
        """Calculate exact inclusive A:B statistics; never touch the worker."""
        model = self._recorder_view_model
        if model is None:
            self._reset_recorder_statistics(has_capture=False)
            self._flash("A:B statistics requires a validated completed capture.")
            return
        try:
            result = recorder_view.build_sample_range_statistics(
                model,
                start_index=self.spin_rec_range_start.value(),
                end_index=self.spin_rec_range_end.value())
        except Exception as exc:
            self._clear_recorder_statistics_result(select_charts=False)
            self.lbl_rec_stats_scope.setText(
                "UNAVAILABLE · A:B statistics rejected · capture/CSV retained")
            self.rec_view_analysis_tabs.setCurrentIndex(1)
            self._sync_recorder_sample_range_controls()
            self._flash("A:B Signal Statistics rejected: %s" % exc)
            return
        self._recorder_range_selection = result.selection
        self._recorder_range_source_view = model
        self.recorder_plot.set_sample_range(result.selection)
        self._render_recorder_statistics(result)
        self._sync_recorder_sample_range_controls()
        self._flash(
            "A:B endpoint values and inclusive statistics calculated · "
            "read-only · raw CSV unchanged")

    def _recorder_apply_time_zoom(self):
        model = self._recorder_view_model
        current = self.recorder_plot.layout_model
        if model is None or current is None:
            self._flash("Time Zoom은 검증 완료된 capture 후 사용할 수 있습니다.")
            return
        if current.plot_mode != recorder_view.PLOT_MODE_TIME:
            self._sync_recorder_time_zoom_controls(current)
            self._flash("Manual Time Zoom is available only in Time Waveform mode.")
            return
        try:
            start_s = float(self.edit_rec_time_start.text().strip())
            end_s = float(self.edit_rec_time_end.text().strip())
            layout = recorder_view.set_time_window(
                current, model, (start_s, end_s))
            self.recorder_plot.set_view_model(model, layout)
        except Exception as exc:
            # Keep the visible fields consistent with the unchanged atomic
            # layout; a rejected text value must not look applied or savable.
            self._sync_recorder_time_zoom_controls(current)
            self._flash("Time Zoom 적용 실패: %s" % exc)
            return
        self._sync_recorder_time_zoom_controls(self.recorder_plot.layout_model)
        self._flash(
            "Manual Time Zoom applied to both charts · display only · Y range unchanged")

    def _recorder_reset_time_zoom(self):
        model = self._recorder_view_model
        current = self.recorder_plot.layout_model
        if model is None or current is None:
            self._flash("Time Zoom은 검증 완료된 capture 후 사용할 수 있습니다.")
            return
        if current.plot_mode != recorder_view.PLOT_MODE_TIME:
            self._sync_recorder_time_zoom_controls(current)
            self._flash("Full Time reset is available only in Time Waveform mode.")
            return
        try:
            layout = recorder_view.set_time_window(current, model, None)
            self.recorder_plot.set_view_model(model, layout)
        except Exception as exc:
            self._flash("Full Time 복원 실패: %s" % exc)
            return
        self._sync_recorder_time_zoom_controls(self.recorder_plot.layout_model)
        self._flash("Both charts restored to the full captured time range")

    def _invalidate_recorder_view(self, detail, *, clear, advance=True):
        if advance:
            self._recorder_view_generation += 1
        self._recorder_manifest_ui_generation = None
        self._recorder_expected_worker_generation = None
        self._recorder_view_is_current = False
        if clear:
            self._recorder_capture_evidence = None
            self._recorder_view_model = None
            self.recorder_plot.clear()
            for combo in (self.rec_view_lane_a, self.rec_view_lane_b):
                combo.blockSignals(True); combo.clear(); combo.setEnabled(False)
                combo.blockSignals(False)
            for visibility in (
                    self.chk_rec_view_lane_a, self.chk_rec_view_lane_b):
                visibility.blockSignals(True)
                visibility.setChecked(False); visibility.setEnabled(False)
                visibility.blockSignals(False)
            self.btn_rec_view_tab.setEnabled(False)
            self.btn_rec_view_open.setEnabled(False)
            self.btn_rec_view_save.setEnabled(False)
            self._reset_recorder_statistics(has_capture=False)
            self._sync_recorder_plot_mode_controls(None)
            self._sync_recorder_time_zoom_controls(None)
            self.lbl_rec_view_status.setText("No validated capture · %s" % detail)
            self.lbl_rec_view_status.setToolTip(str(detail))
            self._show_recorder_recording()
        elif self._recorder_view_model is not None:
            self.btn_rec_view_tab.setEnabled(True)
            self.lbl_rec_view_status.setText(
                "HISTORICAL / OFFLINE · retained read-only capture · not current target evidence")
            self.lbl_rec_view_status.setToolTip(str(detail))
            self._sync_recorder_sample_range_controls()
            if (self._recorder_statistics_model is not None
                    and self._recorder_statistics_source_view
                    is self._recorder_view_model):
                self.lbl_rec_stats_scope.setText(
                    self.lbl_rec_stats_scope.text().replace(
                        "CURRENT", "HISTORICAL / OFFLINE"))

    def _recorder_save_view_layout(self):
        model = self._recorder_view_model
        layout = self.recorder_plot.layout_model
        if model is None or layout is None:
            self._flash("저장할 Recorder View가 없습니다."); return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save Local Recorder View", "recorder.ayview.json",
            "AngryYJH Recorder View (*.ayview.json);;JSON (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".ayview.json"
        try:
            recorder_view.save_layout(
                path, layout, available_channels=model.signals)
        except Exception as exc:
            self._flash("Recorder View 저장 실패: %s" % exc); return
        self._recorder_view_layout_path = path
        self._flash("Local Recorder View 저장 완료 · EAS 파일 호환 아님 · %s" % path)

    def _recorder_open_view_layout(self):
        model = self._recorder_view_model
        if model is None:
            self._flash("먼저 검증 완료된 capture가 필요합니다."); return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open Local Recorder View", "",
            "AngryYJH Recorder View (*.ayview.json *.json);;JSON (*.json)")
        if not path:
            return
        try:
            layout = recorder_view.load_layout(
                path, available_channels=model.signals)
            layout = recorder_view.validate_layout_for_view(layout, model)
        except Exception as exc:
            self._flash("Recorder View 열기 실패: %s" % exc); return
        self._recorder_view_layout_path = path
        self._populate_recorder_view_controls(model, layout)
        self._flash("Local Recorder View loaded · not EAS-file compatible · %s" % path)

    def _open_recorder_feature_map(self):
        path = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "docs", "eas-recorder-ribbon.md"))
        if not os.path.isfile(path):
            self._flash("Recorder feature map 파일을 찾을 수 없습니다: %s" % path)
            return
        if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path)):
            self._flash("Recorder feature map 열기 실패: %s" % path)

    def _recorder_checked_signals(self):
        if not hasattr(self, "rec_signal_list"):
            return tuple()
        return tuple(
            self.rec_signal_list.item(index).text()
            for index in range(self.rec_signal_list.count())
            if self.rec_signal_list.item(index).checkState()
            == QtCore.Qt.CheckState.Checked)

    def _recorder_current_request(self):
        return recorder_control.validate_request(recorder_control.RecorderRequest(
            signals=self._recorder_checked_signals(),
            resolution_us=float(self.spn_rec_resolution.value()),
            record_time_s=float(self.spn_rec_time.value()),
            trigger="immediate"))

    def _recorder_signals_clicked(self):
        self._nav_to(5)
        if not (self.worker and self.worker.isRunning()):
            self._flash("Recorder Signals는 드라이브 연결 후 Personality에서 읽습니다.")
            return
        self._apply_recorder_status(
            "DISCOVERING_SIGNALS",
            "Personality model/cache/upload path를 확인하는 중입니다…",
            source_label="ui")
        self.worker.discover_recorder_signals()

    def _on_recorder_signals_result(self, names, error):
        source = self.sender()
        if source is not None and source is not self.worker:
            return  # late result from a superseded connection generation
        if error or not names:
            self._recorder_signals_target = None
            self._recorder_ui_state = "ERROR"
            self.recorder_log.setPlainText(
                "SIGNAL DISCOVERY ERROR\n\n%s" % (error or "no signals returned"))
            self._on_recorder_status("ERROR", error or "no signals returned")
            return
        pending_workspace = set(self._recorder_pending_selection)
        available = {str(name) for name in names}
        missing = sorted(pending_workspace - available)
        previous = (set() if missing else
                    set(self._recorder_checked_signals()) | pending_workspace)
        self.rec_signal_list.blockSignals(True)
        self.rec_signal_list.clear()
        for name in names:
            item = QtWidgets.QListWidgetItem(str(name))
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked if str(name) in previous
                else QtCore.Qt.CheckState.Unchecked)
            self.rec_signal_list.addItem(item)
        self.rec_signal_list.blockSignals(False)
        self._recorder_pending_selection.clear()
        self._recorder_signals_target = self.worker
        if missing:
            self._apply_recorder_status(
                "WORKSPACE_MISMATCH",
                "%d workspace channel(s) are absent on the current target" %
                len(missing),
                source_label="worker" if source is not None else "ui")
            self.recorder_log.setPlainText(
                "WORKSPACE_MISMATCH\n\nWorkspace channels absent on this target:\n- %s\n\n"
                "No partial setup was applied. Select channels manually to acknowledge "
                "the current Personality."
                % "\n- ".join(missing))
        else:
            self._apply_recorder_status(
                "IDLE", "%d exact Personality signal name(s) discovered" %
                len(names),
                source_label="worker" if source is not None else "ui")
            self.recorder_log.setPlainText(
                "SIGNALS READY\n\n%d exact personality names discovered.\n"
                "Select 1–%d channels; units remain personality-owned."
                % (len(names), recorder_control.MAX_SIGNALS))

    def _recorder_immediate_clicked(self):
        if not (self.worker and self.worker.isRunning()):
            self._flash("드라이브를 먼저 연결하세요.")
            return
        try:
            request = self._recorder_current_request()
        except Exception as exc:
            self._apply_recorder_status(
                "ERROR", str(exc), source_label="ui"); return
        self._nav_to(5)
        # Revoke the old plot synchronously before a new vendor job can be
        # queued.  A late result must not remain visually authoritative.
        self._invalidate_recorder_view(
            "New capture started; previous plot authority was revoked",
            clear=True, advance=True)
        self._recorder_manifest_data = None
        self._recorder_last_data = None
        self._recorder_last_resolved = None
        self.btn_rec_export.setEnabled(False)
        self._apply_recorder_status(
            "CONFIGURING",
            "TS readback과 16K buffer capacity를 검증하는 중입니다…",
            source_label="ui")
        token = self.worker.start_recorder(request)
        self._recorder_expected_worker_generation = token

    def _recorder_upload_clicked(self):
        if not (self.worker and self.worker.isRunning()):
            self._flash("드라이브 연결이 없습니다.")
            return
        if self._recorder_ui_state != "READY_TO_UPLOAD":
            self._flash("Recorder data is not READY_TO_UPLOAD.")
            return
        # Lock synchronously before enqueue so rapid clicks cannot queue two
        # uploads for one finite capture.  Worker failures restore READY state.
        self._apply_recorder_status(
            "UPLOADING", "Recorder Upload request queued", source_label="ui")
        try:
            self.worker.upload_recorder()
        except Exception as exc:
            self._apply_recorder_status(
                "READY_TO_UPLOAD",
                "Upload enqueue failed; retry is available: %s" % exc,
                source_label="ui")

    def _recorder_stop_clicked(self):
        if self.worker and self.worker.isRunning():
            self.worker.request_recorder_stop()
            self._flash("Recorder cancel 요청 · 모터 STOP 명령은 보내지 않습니다.")
        else:
            self._flash("Recorder가 연결되어 있지 않습니다.")

    def _on_recorder_manifest(self, manifest):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        incoming = dict(manifest or {})
        expected = self._recorder_expected_worker_generation
        incoming_generation = incoming.get("worker_generation")
        try:
            valid_generation = (
                isinstance(incoming_generation, int)
                and not isinstance(incoming_generation, bool)
                and incoming_generation > 0)
            if expected is not None:
                valid_generation = valid_generation and incoming_generation == expected
            elif source is not None:
                valid_generation = False
            if not valid_generation and (expected is not None or source is not None):
                raise recorder_view.RecorderViewError(
                    "manifest worker-generation token is missing or stale")
        except Exception as exc:
            self._recorder_manifest_data = None
            self._invalidate_recorder_view(
                "Rejected manifest: %s" % exc, clear=True, advance=False)
            self.recorder_log.setPlainText(
                "MANIFEST REJECTED\n\n%s\n\nNo plot or CSV authority was granted." % exc)
            return
        # A worker must not smuggle an ambiguous bare target_type into evidence.
        incoming.pop("target_type", None)
        self._recorder_manifest_data = incoming
        self._recorder_manifest_data.update({
            "firmware": self._connected_identity.get("fw"),
            "pal": self._connected_identity.get("pal"),
            "boot": self._connected_identity.get("boot"),
            "application_target_class": self._connected_identity.get(
                "target_type"),
            "application_target_class_provenance": (
                "APPLICATION CLASSIFICATION · NOT BOARD READBACK"),
            "drive_identity": self._connected_identity.get("drive_identity"),
        })
        self._recorder_manifest_ui_generation = self._recorder_view_generation
        m = self._recorder_manifest_data
        self.lbl_rec_buffer.setText(
            "actual %.6g µs · %.6g s · %s samples/signal · %s/%s buffer" %
            (m.get("actual_resolution_us", float("nan")),
             m.get("actual_record_time_s", float("nan")),
             m.get("length_per_signal", "—"),
             m.get("total_buffer_samples", "—"),
             recorder_control.RECORDER_BUFFER_SAMPLES))

    def _on_recorder_status(self, state, detail):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        self._apply_recorder_status(
            state, detail,
            source_label="worker" if source is not None else "ui")

    def _apply_recorder_status(self, state, detail, *, source_label):
        """Apply a validated worker status or explicit local UI transition."""
        state = str(state)
        detail = str(detail or "")
        recorder_projection = (state, detail)
        if recorder_projection != self._session_log_last_recorder_state:
            self._session_log_last_recorder_state = recorder_projection
            severity = (
                "ERROR" if ("ERROR" in state or "UNKNOWN" in state
                            or state.startswith("STALE")) else "INFO")
            self._session_log_event_changed(self.session_log.append(
                category="recorder", name="recorder.state",
                severity=severity,
                payload={
                    "state": state,
                    "detail": detail[:500],
                    "source": str(source_label or "unknown"),
                }))
        self._recorder_ui_state = state
        for label in (
                getattr(self, "lbl_recorder_ribbon_state", None),
                getattr(self, "lbl_recorder_page_state", None)):
            if label is not None:
                label.setText(state)
                if state == "READY_TO_UPLOAD":
                    status_class = "ready"
                elif state == "COMPLETED":
                    status_class = "success"
                elif state in ("DISCOVERING_SIGNALS", "RECORDING", "CONFIGURING", "UPLOADING",
                               "WAITING_FOR_TRIGGER"):
                    status_class = "active"
                elif ("ERROR" in state or "UNKNOWN" in state
                      or state.startswith("STALE")):
                    status_class = "error"
                else:
                    status_class = "neutral"
                label.setProperty("status", status_class)
                label.setProperty(
                    "on", "true" if state in (
                        "RECORDING", "READY_TO_UPLOAD", "COMPLETED") else "false")
                self._restyle(label)
        if hasattr(self, "recorder_log"):
            existing = self.recorder_log.toPlainText()
            self.recorder_log.setPlainText(
                "%s\n\n%s%s" % (
                    state, detail,
                    ("\n\n" + existing) if existing and state != "CONFIGURING" else ""))
        self._update_recorder_controls()

    def _inject_recorder_data_for_offline_test(
            self, data, resolved, completion_token=None):
        """Test/smoke-only bundle injection; never a production signal slot."""
        allowed = (
            "PYTEST_CURRENT_TEST" in os.environ
            or "--smoke-recorder" in sys.argv
        )
        if not allowed:
            raise RuntimeError(
                "offline Recorder injection is available only to pytest/smoke")
        self._recorder_offline_test_capability = (
            _RECORDER_OFFLINE_TEST_CAPABILITY)
        try:
            return self._on_recorder_data(data, resolved, completion_token)
        finally:
            self._recorder_offline_test_capability = None

    def _on_recorder_data(self, data, resolved, completion_token=None):
        source = self.sender()
        offline_test = (
            getattr(self, "_recorder_offline_test_capability", None)
            is _RECORDER_OFFLINE_TEST_CAPABILITY)
        # Production acceptance is signal-bound to the current worker.  A
        # direct call must never regain capture authority after invalidation.
        if source is None and not offline_test:
            return
        if source is not None and source is not self.worker:
            return
        manifest = dict(self._recorder_manifest_data or {})
        names = tuple(getattr(resolved, "signals", ()))
        manifest_generation = self._recorder_manifest_ui_generation
        try:
            if manifest_generation is None:
                if not offline_test:
                    raise recorder_view.RecorderViewError(
                        "capture generation is stale after target invalidation")
                # Direct offline acceptance probes may inject a complete
                # immutable manifest without a worker signal.
                manifest_generation = self._recorder_view_generation
            if source is not None and self._recorder_expected_worker_generation is None:
                raise recorder_view.RecorderViewError(
                    "worker completion arrived without current capture authority")
            if manifest.get("completion") != "VALIDATED":
                raise recorder_view.RecorderViewError(
                    "capture manifest is not VALIDATED")
            if tuple(manifest.get("signals") or ()) != names:
                raise recorder_view.RecorderViewError(
                    "capture manifest signals disagree with resolved request")
            if int(manifest.get("length_per_signal")) != int(
                    getattr(resolved, "length_per_signal", -1)):
                raise recorder_view.RecorderViewError(
                    "capture manifest length disagrees with resolved request")
            if manifest_generation != self._recorder_view_generation:
                raise recorder_view.RecorderViewError(
                    "capture generation is stale for the current UI authority")
            if completion_token is None:
                if (source is not None
                        or self._recorder_expected_worker_generation is not None):
                    raise recorder_view.RecorderViewError(
                        "completion token is missing from worker data")
            else:
                if not isinstance(completion_token, dict):
                    raise recorder_view.RecorderViewError(
                        "completion token must be a mapping")
                manifest_worker_generation = manifest.get("worker_generation")
                token_worker_generation = completion_token.get("worker_generation")
                if (completion_token.get("capture_id") != manifest.get("capture_id")
                        or token_worker_generation != manifest_worker_generation
                        or (self._recorder_expected_worker_generation is not None
                            and token_worker_generation
                            != self._recorder_expected_worker_generation)):
                    raise recorder_view.RecorderViewError(
                        "completion token disagrees with capture manifest")
            binding = recorder_view.CaptureBinding(
                capture_id=str(manifest.get("capture_id") or ""),
                generation=int(manifest_generation),
                drive_identity=str(manifest.get("drive_identity") or ""))
            evidence = recorder_view.build_capture_evidence(
                state="COMPLETED", data=data, resolved=resolved,
                binding=binding, manifest=manifest)
            model = evidence.view
        except Exception as exc:
            self._recorder_capture_evidence = None
            self._recorder_last_data = None
            self._recorder_last_resolved = None
            self.btn_rec_export.setEnabled(False)
            self._invalidate_recorder_view(
                "Rejected capture: %s" % exc, clear=True, advance=False)
            self.recorder_log.setPlainText(
                "VIEW REJECTED\n\n%s\n\nNo plot or CSV authority was granted." % exc)
            self._update_recorder_controls()
            return

        self._recorder_capture_evidence = evidence
        self._recorder_last_data = evidence.data
        self._recorder_last_resolved = evidence.resolved
        self._recorder_manifest_data = evidence.manifest
        self._recorder_view_model = model
        self._recorder_view_is_current = True
        self._populate_recorder_view_controls(model)
        self.btn_rec_view_tab.setEnabled(True)
        self.lbl_rec_view_status.setText(
            "Validated · FULL waveform · %d samples × %d signals · capture %s" %
            (model.source_sample_count, len(model.signals), model.capture_id))
        self.lbl_rec_view_status.setToolTip(
            "Current generation %d · drive identity %s" %
            (model.generation, model.drive_identity))
        accepted_data = evidence.data
        dt = accepted_data.get("dt")
        lines = ["COMPLETED", "", "dt = %s s" % dt]
        for name in names:
            values = accepted_data.get(name, [])
            try:
                count = len(values)
                minimum = min(values) if count else None
                maximum = max(values) if count else None
                lines.append("%s · n=%d · min=%s · max=%s" %
                             (name, count, minimum, maximum))
            except Exception:
                lines.append("%s · summary unavailable" % name)
        lines.extend(("", "Units are not inferred; headers are exact personality names."))
        self.recorder_log.setPlainText("\n".join(lines))
        self.btn_rec_export.setEnabled(bool(names and data))
        self._update_recorder_controls()

    def _recorder_state_pending(self):
        state = str(getattr(self, "_recorder_ui_state", "IDLE"))
        return (state in (
            "DISCOVERING_SIGNALS", "CONFIGURING", "WAITING_FOR_TRIGGER", "RECORDING",
            "READY_TO_UPLOAD", "UPLOADING", "STALE_CONNECTION_UNKNOWN",
            "CANCEL_FAILED_UNKNOWN", "START_OWNERSHIP_UNKNOWN",
            "RECOVERY_REQUIRED_UNKNOWN") or state.startswith("UNKNOWN:"))

    def _recorder_state_cancellable(self):
        state = str(getattr(self, "_recorder_ui_state", "IDLE"))
        return (state in (
            "CONFIGURING", "WAITING_FOR_TRIGGER", "RECORDING",
            "READY_TO_UPLOAD", "UPLOADING", "STALE_CONNECTION_UNKNOWN",
            "CANCEL_FAILED_UNKNOWN", "START_OWNERSHIP_UNKNOWN",
            "RECOVERY_REQUIRED_UNKNOWN") or state.startswith("UNKNOWN:"))

    def _update_recorder_controls(self):
        connected = bool(
            getattr(self, "_connection_admitted", False)
            and getattr(self, "_ui_connected", False)
            and self.worker and self.worker.isRunning())
        telemetry_trusted = bool(
            connected
            and getattr(self, "_telemetry_authoritative", False)
            and not getattr(self, "_energizing_state", False))
        mutation_trusted = bool(
            telemetry_trusted
            and getattr(self, "_connection_access_mode", None)
            == SUPERVISED_ACCESS_MODE
            and getattr(self, "_last_mo", None) == 0)
        persistence_locked = bool(
            getattr(self, "_persistence_recovery_unknown", False))
        selected = len(self._recorder_checked_signals())
        state = getattr(self, "_recorder_ui_state", "IDLE")
        pending = self._recorder_state_pending()
        target_bound = connected and self._recorder_signals_target is self.worker
        if hasattr(self, "btn_rec_signals"):
            self.btn_rec_signals.setEnabled(
                mutation_trusted and not pending and not persistence_locked)
            self.btn_rec_immediate.setEnabled(
                mutation_trusted and target_bound and selected > 0 and not pending
                and not persistence_locked)
            self.btn_rec_upload.setEnabled(
                mutation_trusted and state == "READY_TO_UPLOAD"
                and not persistence_locked)
            self.btn_rec_stop.setEnabled(
                connected and self._recorder_state_cancellable())
            self.btn_global_stop.setEnabled(connected)
            self.btn_rec_open.setEnabled(not pending)
            self.btn_rec_menu_workspace.setEnabled(not pending)
            self.rec_signal_list.setEnabled(
                not pending and not persistence_locked)
            self.spn_rec_resolution.setEnabled(
                not pending and not persistence_locked)
            self.spn_rec_time.setEnabled(
                not pending and not persistence_locked)
            self.btn_rec_save.setEnabled(selected > 0 and not pending)
            self.btn_rec_save_as.setEnabled(selected > 0 and not pending)
            self.btn_rec_preset.setEnabled(selected > 0 and not pending)
            if hasattr(self, "btn_rec_export"):
                self.btn_rec_export.setEnabled(
                    bool(self._recorder_last_data is not None
                         and self._recorder_last_resolved is not None)
                    and not pending)
        if hasattr(self, "lbl_rec_signal_count"):
            self.lbl_rec_signal_count.setText(
                "%d selected · %d discovered · max %d" %
                (selected, self.rec_signal_list.count(), recorder_control.MAX_SIGNALS))

    def _recorder_save_workspace(self, _checked=False, force_dialog=False):
        if self._recorder_state_pending():
            self._flash("Recorder lifecycle가 끝날 때까지 workspace 설정은 잠깁니다.")
            return
        try:
            request = self._recorder_current_request()
        except Exception as exc:
            self._flash("Recorder workspace 저장 불가: %s" % exc); return
        path = self._recorder_workspace_path
        if force_dialog or not path:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Save Recorder Workspace", "recorder.ayrec.json",
                "AngryYJH Recorder Workspace (*.ayrec.json);;JSON (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".ayrec.json"
        try:
            recorder_control.save_workspace(path, request)
        except Exception as exc:
            self._flash("Recorder workspace 저장 실패: %s" % exc); return
        self._recorder_workspace_path = path
        self._flash("Recorder workspace 저장 완료 · EAS 파일 호환을 주장하지 않음 · %s" % path)

    def _recorder_open_workspace(self, _checked=False):
        if self._recorder_state_pending():
            self._flash("Recorder lifecycle가 끝날 때까지 다른 workspace를 열 수 없습니다.")
            return
        if "recorder" not in self.tool_layout.active:
            self._navigate_tool("recorder")
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open Recorder Workspace", "",
            "AngryYJH Recorder Workspace (*.ayrec.json *.json);;JSON (*.json)")
        if not path:
            return
        try:
            request = recorder_control.load_workspace(path)
        except Exception as exc:
            self._flash("Recorder workspace 열기 실패: %s" % exc); return
        self._recorder_workspace_path = path
        self.spn_rec_resolution.setValue(request.resolution_us)
        self.spn_rec_time.setValue(request.record_time_s)
        self._recorder_pending_selection = set(request.signals)
        for index in range(self.rec_signal_list.count()):
            item = self.rec_signal_list.item(index)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked
                if item.text() in self._recorder_pending_selection
                else QtCore.Qt.CheckState.Unchecked)
        self._navigate_tool("recorder")
        if self.worker and self.worker.isRunning():
            self._apply_recorder_status(
                "DISCOVERING_SIGNALS",
                "Loaded workspace is being checked against the current Personality…",
                source_label="ui")
            self.worker.discover_recorder_signals()
        self._flash("Recorder workspace loaded · local schema v1 · %s" % path)
        self._update_recorder_controls()

    def _recorder_export_statistics_csv(self):
        model = self._recorder_view_model
        result = self._recorder_statistics_model
        evidence = self._recorder_capture_evidence
        view_generation = self._recorder_view_generation
        was_current = bool(self._recorder_view_is_current)
        valid = bool(
            model is not None
            and result is not None
            and self._recorder_statistics_source_view is model
            and result.binding == model.binding
            and isinstance(evidence, recorder_view.CaptureEvidence)
            and evidence.view is model
        )
        if not valid:
            self._sync_recorder_statistics_export()
            self._flash(
                "Statistics CSV requires one exact displayed result and source capture.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Derived Recorder Statistics CSV",
            "recorder_statistics.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        unchanged = bool(
            self._recorder_view_generation == view_generation
            and bool(self._recorder_view_is_current) is was_current
            and self._recorder_view_model is model
            and self._recorder_statistics_model is result
            and self._recorder_statistics_source_view is model
            and self._recorder_capture_evidence is evidence
            and result.binding == model.binding
            and evidence.view is model
        )
        if not unchanged:
            self._sync_recorder_statistics_export()
            self._flash(
                "Statistics CSV not exported · capture/result authority changed "
                "while the save dialog was open.")
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        authority = (
            recorder_view.STATISTICS_AUTHORITY_CURRENT
            if was_current
            else recorder_view.STATISTICS_AUTHORITY_HISTORICAL_OFFLINE)
        try:
            metadata = recorder_view.export_statistics_csv(
                path,
                model,
                result,
                authority=authority,
            )
        except Exception as exc:
            self._flash("Statistics CSV export failed: %s" % exc)
            return
        self._flash(
            "Derived Statistics CSV exported · %s · %d signals · source %s" % (
                metadata.authority.upper(),
                metadata.row_count,
                metadata.source_view_sha256[:12],
            ))

    def _recorder_export_csv(self):
        data = self._recorder_last_data
        resolved = self._recorder_last_resolved
        if not data or resolved is None:
            self._flash("내보낼 Recorder 데이터가 없습니다."); return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export Recorder CSV", "recorder_capture.csv",
            "CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            meta = recorder_control.export_csv(
                path, data, resolved.signals,
                metadata=self._recorder_manifest_data)
        except Exception as exc:
            self._flash("CSV export 실패: %s" % exc); return
        self._flash("CSV + metadata export 완료 · %d samples/signal · %s" %
                    (meta["samples_per_signal"], meta["metadata_path"]))

    def _build_feedback_page(self):
        f = theme.HudCard()
        outer = QtWidgets.QVBoxLayout(f); outer.setContentsMargins(16, 14, 16, 10); outer.setSpacing(8)
        title = QtWidgets.QLabel("FEEDBACK ON MOTOR"); title.setProperty("role", "celltitle")
        outer.addWidget(title)
        # scrollable body — EAS panels have up to ~20 rows in 3-4 groups
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        inner = QtWidgets.QWidget(); inner.setStyleSheet("background:transparent;")
        v = QtWidgets.QVBoxLayout(inner); v.setContentsMargins(0, 0, 6, 0); v.setSpacing(10)
        scroll.setWidget(inner)

        lbl = QtWidgets.QLabel("Feedback Sensor Type  (CA[41])  ·  READBACK")
        lbl.setProperty("role", "field")
        self.cmb_sensor = QtWidgets.QComboBox()
        # EAS III verbatim 23-sensor list (Port notation). data = CA[41] id, or the
        # EAS name string when the id is unconfirmed (write blocked for those).
        for name, sid in feedback_spec.EAS_SENSORS:
            if sid is None:
                self.cmb_sensor.addItem("%s   · ID 미확정" % name, name)
            else:
                self.cmb_sensor.addItem(name, sid)
        self.cmb_sensor.setEnabled(False)
        self.cmb_sensor.currentIndexChanged.connect(self._on_sensor_changed)
        v.addWidget(lbl); v.addWidget(self.cmb_sensor)
        lc = QtWidgets.QLabel("Commutation Method  (CA[17])  ·  READBACK")
        lc.setProperty("role", "field")
        self.cmb_commut = QtWidgets.QComboBox()
        for cid in sorted(feedback_spec.COMMUT_NAMES):
            self.cmb_commut.addItem("%s  ·  %d" % (feedback_spec.COMMUT_NAMES[cid], cid), cid)
        self.cmb_commut.setEnabled(False)
        v.addWidget(lc); v.addWidget(self.cmb_commut)
        # common (always-shown) fields
        self.fb_fields = {}
        common = [("counts", "Counts / Rev  (CA[18])  ·  READBACK", True),
                  ("sockets", "Sockets  pos / vel / commut  (CA[45/46/47])", False)]
        cform = QtWidgets.QGridLayout(); cform.setHorizontalSpacing(14); cform.setVerticalSpacing(7)
        for i, (k, label, editable) in enumerate(common):
            l = QtWidgets.QLabel(label); l.setProperty("role", "field")
            e = QtWidgets.QLineEdit(); e.setText("—")
            e.setReadOnly(not editable)
            if editable:
                e.setEnabled(False)     # enabled on connect
            cform.addWidget(l, i, 0); cform.addWidget(e, i, 1); self.fb_fields[k] = e
        v.addLayout(cform)
        # dynamic per-sensor groups (General / Sensor Parameters / Serial Encoder Frame /
        # Resolution) — rebuilt to mirror the exact EAS panel of the selected sensor
        self.fb_dyn_title = QtWidgets.QLabel(""); self.fb_dyn_title.setProperty("role", "field")
        v.addWidget(self.fb_dyn_title)
        self._fb_dyn_box = QtWidgets.QVBoxLayout(); self._fb_dyn_box.setSpacing(8)
        self._fb_dyn_fields = {}
        self._fb_group_titles = []
        v.addLayout(self._fb_dyn_box)
        v.addStretch(1)
        outer.addWidget(scroll, 1)
        outer.addWidget(self._hline())
        row = QtWidgets.QHBoxLayout()
        self.btn_fb_write = QtWidgets.QPushButton(
            "Preview only  ·  Direct Save LOCKED  (Registry Required)")
        self.btn_fb_write.setObjectName("primary"); self.btn_fb_write.setEnabled(False)
        self.btn_fb_write.setToolTip(
            "Feedback direct save is fail-closed. A versioned per-register write contract, "
            "full readback, rollback, and persistence audit are required before this opens.")
        self.btn_fb_write.clicked.connect(self._write_feedback)
        row.addWidget(self.btn_fb_write); row.addStretch(1)
        outer.addLayout(row)
        self.fb_note = QtWidgets.QLabel(
            "🔒 Preview only · 화면 값은 drive에 전송되지 않습니다. 센서/펌웨어별 명령, "
            "타입·범위, 부작용과 복원 순서를 고정한 versioned write registry가 마련되기 "
            "전에는 Feedback assignment와 SV를 보내지 않습니다. Encoder Maintenance는 "
            "별도 영구 datum 작업입니다.")
        self.fb_note.setProperty("role", "hint"); self.fb_note.setWordWrap(True)
        self.fb_note.setStyleSheet("color:%s;" % theme.C_AMBER)
        outer.addWidget(self.fb_note)
        # offline preview: render the current selection's EAS structure right away
        self._rebuild_fb_dynamic(self.cmb_sensor.currentData(), values=None)
        return f

    @staticmethod
    def _clear_layout(lay):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)   # detach NOW (deleteLater alone leaves ghosts in grabs)
                w.deleteLater()
            elif it.layout():
                MainWindow._clear_layout(it.layout())

    def _clear_fb_dynamic(self):
        self._clear_layout(self._fb_dyn_box)
        self._fb_dyn_fields = {}
        self._fb_group_titles = []

    def _fb_make_widget(self, fld, raws, connected, sensor_label):
        """Build the widget for one field spec; returns the widget."""
        kind = fld["kind"]
        if kind == feedback_spec.DD:
            cb = QtWidgets.QComboBox()
            for text, raw in (fld["options"] or []):
                cb.addItem(text, raw)
            val = raws.get(fld["cmd"]) if fld["cmd"] else None
            if isinstance(val, (int, float)):
                ix = cb.findData(int(val))
                if ix < 0:                       # off-list raw value: show it honestly
                    cb.addItem("(raw %s)" % val, val); ix = cb.count() - 1
                cb.setCurrentIndex(ix)
            # The panel mapping is not a write authority.  Keep mapped dropdowns
            # visibly read-only until a sensor/firmware-specific registry exists.
            cb.setEnabled(False)
            return cb
        if kind == feedback_spec.BTN:
            b = QtWidgets.QPushButton(fld["label"])
            if "maintenance" in (fld["label"] or "").lower():
                b.clicked.connect(lambda _=False: self._open_encoder_maintenance())
            else:
                note = fld["note"] or "미구현"
                b.clicked.connect(lambda _=False, n=note: self._flash("%s" % n))
            b.setEnabled(connected)
            return b
        # VALUE / RO -> line edit
        e = QtWidgets.QLineEdit()
        if fld.get("static") is not None:
            dec = sensor_label if fld["label"] == "Sensor Name" else fld["static"]
        else:
            dec = feedback_spec.decode_field(fld, raws)
        e.setText("—" if dec is None else str(dec))
        editable = fld["editable"] and kind == feedback_spec.VALUE
        e.setReadOnly(True)
        e.setEnabled(False if editable else True)
        return e

    def _rebuild_fb_dynamic(self, sensor_key, values=None):
        """Rebuild the per-sensor EAS group structure. values: raw {cmd: value} or None."""
        self._clear_fb_dynamic()
        groups, verified = feedback_spec.spec_for(sensor_key)
        connected = getattr(self, "_fb_connected", False)
        raws = values or {}
        sensor_label = self.cmb_sensor.currentText().split("   ·")[0]
        for gtitle, fields in groups:
            frame = QtWidgets.QFrame()
            if gtitle == "Serial Encoder Frame":   # EAS sub-group ([∞] popup) -> boxed
                frame.setObjectName("cell")
            gv = QtWidgets.QVBoxLayout(frame); gv.setContentsMargins(
                12 if gtitle == "Serial Encoder Frame" else 0, 6, 0, 4); gv.setSpacing(5)
            t = QtWidgets.QLabel(gtitle.upper()); t.setProperty("role", "celltitle")
            t.setStyleSheet("font-size:11px;letter-spacing:1px;color:%s;" % theme.INDIGO)
            gv.addWidget(t)
            form = QtWidgets.QFormLayout()
            form.setHorizontalSpacing(14); form.setVerticalSpacing(6)
            for fld in fields:
                w = self._fb_make_widget(fld, raws, connected, sensor_label)
                tag = "   · 미확정" if (fld["note"] or "").startswith(("미확정", "쓰기 미확정",
                                                                       "스케일 미확정")) else ""
                cap = fld["label"] + (("  (%s)" % fld["cmd"]) if fld["cmd"] else "") + tag
                lab = QtWidgets.QLabel(cap)
                if fld["note"]:
                    lab.setToolTip(fld["note"]); w.setToolTip(fld["note"])
                if fld["kind"] == feedback_spec.BTN:
                    form.addRow(lab, w)
                else:
                    form.addRow(lab, w)
                self._fb_dyn_fields[fld["label"]] = (fld, w)
            gv.addLayout(form)
            self._fb_dyn_box.addWidget(frame)
            self._fb_group_titles.append(gtitle)
        if not groups:
            self._fb_dyn_box.addWidget(QtWidgets.QLabel("(EAS 미등재 센서 ID — 공통 필드만)"))
        self.fb_dyn_title.setText("EAS 패널 미러" if verified
                                  else "레퍼런스 기반(실화면 미검증)")

    def _on_sensor_changed(self, _ix):
        if not getattr(self, "_fb_connected", False):
            return
        key = self.cmb_sensor.currentData()
        self._rebuild_fb_dynamic(key, values=None)
        # coordinate commutation to this sensor's default so the preview is coherent (EAS-style)
        dc = feedback_spec.DEFAULT_COMMUT.get(key) if isinstance(key, int) else None
        if dc is not None:
            ix = self.cmb_commut.findData(dc)
            if ix >= 0:
                self.cmb_commut.setCurrentIndex(ix)
        extra = " · 이 센서는 CA[41] ID 미확정 — 쓰기 차단됨." if not isinstance(key, int) else ""
        self.fb_note.setText(
            "Preview only · 선택한 패널은 drive에 전송되지 않습니다. 커뮤테이션 표시는 "
            "해당 센서의 문서상 기본값이며 실제 장착 엔코더 설정을 변경하지 않습니다."
            + extra)

    # EAS 6-stage wizard; Phase-1 current-loop tune drives stages 0..2,
    # Phase-2 vel/pos tune drives stages 3..5.
    _AT_STAGES = ["Initialization (Starting Phase)", "Current Identification", "Current Design",
                  "Commutation", "Velocity & Position Identification", "Velocity & Position Design"]
    _AT_PHASE1_LAST = 2
    _AT_PHASE2_LAST = 5
    _AT_CODE_STAGE = {"P0": 0, "VALIDATE": 0, "SNAPSHOT": 0, "ENABLE": 1,
                      "ALIGN": 1,       # B4 pre-align/ratchet (2026-07-13 fix)
                      "MEASURE_R": 1, "MEASURE_L": 1, "DESIGN": 2, "DONE": 2}
    _VP_CODE_STAGE = {"P0": 3, "VALIDATE": 3, "SNAPSHOT": 3,
                      "ENABLE": 4, "BREAKAWAY": 4,     # B1.4 adaptive ramp
                      "UNIT_DIAG": 4, "PROBE": 4, "SIZING": 4,
                      "IDENT_KA": 4, "IDENT_FRICTION": 4,
                      "DESIGN": 5, "DONE": 5}

    def _build_tuning_page(self):
        f = theme.HudCard()
        v = QtWidgets.QVBoxLayout(f); v.setContentsMargins(16, 14, 16, 16); v.setSpacing(10)
        mode_row = QtWidgets.QGridLayout()
        mode_row.setHorizontalSpacing(7)
        mode_row.setVerticalSpacing(6)
        self.btn_tuning_quick_mode = QtWidgets.QPushButton("Quick Tuning · Guided")
        self.btn_tuning_expert_mode = QtWidgets.QPushButton(
            "Expert Tuning · Candidates / Drive Verify")
        for column, button in enumerate((
                self.btn_tuning_quick_mode, self.btn_tuning_expert_mode)):
            button.setCheckable(True)
            button.setStyleSheet(
                "QPushButton:checked{background:%s;color:#052438;"
                "border:1px solid #79d8ff;font-weight:900;}" % theme.INDIGO)
            mode_row.addWidget(button, 0, column)
        self.btn_tuning_quick_mode.clicked.connect(
            lambda: self._show_tuning_mode("quick"))
        self.btn_tuning_expert_mode.clicked.connect(
            lambda: self._show_tuning_mode("expert"))
        self.lbl_tuning_mode_risk = QtWidgets.QLabel("ENERGIZES / MOTION")
        self.lbl_tuning_mode_risk.setObjectName("pill")
        mode_row.addWidget(
            self.lbl_tuning_mode_risk, 1, 0, 1, 2,
            QtCore.Qt.AlignmentFlag.AlignRight)
        v.addLayout(mode_row)

        self.tune_title = QtWidgets.QLabel(
            "QUICK TUNING  ·  Guided identification + design")
        self.tune_title.setProperty("role", "celltitle"); v.addWidget(self.tune_title)
        self.tuning_mode_note = QtWidgets.QLabel("")
        self.tuning_mode_note.setProperty("role", "hint")
        self.tuning_mode_note.setWordWrap(True); v.addWidget(self.tuning_mode_note)
        self.tune_stage_lbls = []
        for i, s in enumerate(self._AT_STAGES):
            row = QtWidgets.QLabel("○  " + s); row.setProperty("role", "fwval")
            v.addWidget(row); self.tune_stage_lbls.append(row)
        # live status line (current phase detail / result reason)
        self.tune_status = QtWidgets.QLabel("연결 후 Run — 드라이브에서 R·L 실측 → PI 게인 산출")
        self.tune_status.setProperty("role", "hint"); self.tune_status.setWordWrap(True)
        v.addWidget(self.tune_status)
        v.addWidget(self._hline())
        # Candidate results and installed drive readback are deliberately
        # separate authority classes.  A tuning result is a model candidate;
        # a later KP/KI query is evidence of what the drive currently reports.
        self.tune_candidate_title = QtWidgets.QLabel(
            "CANDIDATE MODEL · MEASURED PLANT + COMPUTED GAINS "
            "(NOT DRIVE READBACK)")
        self.tune_candidate_title.setProperty("role", "field")
        v.addWidget(self.tune_candidate_title)
        self.tune_gain_fields = {}
        self.tune_candidate_labels = {}
        self.tune_candidate_gain_labels = {}
        gform = QtWidgets.QGridLayout(); gform.setHorizontalSpacing(14); gform.setVerticalSpacing(7)
        rows = [
            ("r_pp", "Resistance R · CANDIDATE MEASUREMENT "
                     "[Ω phase-to-phase]"),
            ("l_pp", "Inductance L · CANDIDATE MEASUREMENT "
                     "[µH phase-to-phase]"),
            ("kp_cur", "Current Loop KP · CANDIDATE (KP[1]) [V/A]"),
            ("ki_cur", "Current Loop KI · CANDIDATE (KI[1]) [Hz]"),
            ("pm", "Current Phase Margin · CANDIDATE DESIGN [deg]"),
            ("k_a", "Accel Constant K_a · CANDIDATE IDENTIFICATION "
                    "[cnt/s²/A]"),
            ("b_visc", "Viscous Friction B · CANDIDATE IDENTIFICATION "
                       "[A/(cnt/s)]"),
            ("i_c", "Coulomb Friction I_c · CANDIDATE IDENTIFICATION [A]"),
            ("kp_vel", "Velocity Loop KP · CANDIDATE (KP[2]) [A/(cnt/s)]"),
            ("ki_vel", "Velocity Loop KI · CANDIDATE (KI[2]) [Hz]"),
            ("kp_pos", "Position Loop KP · CANDIDATE (KP[3]) [1/s]"),
            ("pm_vel", "Velocity Phase Margin · CANDIDATE DESIGN "
                       "[deg; GM dB]"),
            ("pm_pos", "Position Phase Margin · CANDIDATE DESIGN [deg]"),
        ]
        for i, (k, label) in enumerate(rows):
            l = QtWidgets.QLabel(label); l.setProperty("role", "field")
            e = QtWidgets.QLineEdit(); e.setReadOnly(True); e.setText("—")
            gform.addWidget(l, i, 0); gform.addWidget(e, i, 1)
            self.tune_gain_fields[k] = e
            self.tune_candidate_labels[k] = l
            if k in ("kp_cur", "ki_cur", "kp_vel", "ki_vel", "kp_pos"):
                self.tune_candidate_gain_labels[k] = l
        v.addLayout(gform)

        self.tune_installed_title = QtWidgets.QLabel(
            "INSTALLED GAINS · DRIVE READBACK (NOT CANDIDATES)")
        self.tune_installed_title.setProperty("role", "field")
        v.addWidget(self.tune_installed_title)
        self.tune_installed_gain_fields = {}
        self.tune_installed_gain_labels = {}
        installed_form = QtWidgets.QGridLayout()
        installed_form.setHorizontalSpacing(14)
        installed_form.setVerticalSpacing(7)
        installed_rows = [
            ("kp_cur", "Current Loop KP · INSTALLED / DRIVE READBACK "
                       "(KP[1]) [V/A]"),
            ("ki_cur", "Current Loop KI · INSTALLED / DRIVE READBACK "
                       "(KI[1]) [Hz]"),
            ("kp_vel", "Velocity Loop KP · INSTALLED / DRIVE READBACK "
                       "(KP[2]) [A/(cnt/s)]"),
            ("ki_vel", "Velocity Loop KI · INSTALLED / DRIVE READBACK "
                       "(KI[2]) [Hz]"),
            ("kp_pos", "Position Loop KP · INSTALLED / DRIVE READBACK "
                       "(KP[3]) [1/s]"),
        ]
        for i, (key, label) in enumerate(installed_rows):
            field_label = QtWidgets.QLabel(label)
            field_label.setProperty("role", "field")
            value = QtWidgets.QLineEdit()
            value.setReadOnly(True)
            value.setText("—")
            installed_form.addWidget(field_label, i, 0)
            installed_form.addWidget(value, i, 1)
            self.tune_installed_gain_labels[key] = field_label
            self.tune_installed_gain_fields[key] = value
        v.addLayout(installed_form)
        v.addWidget(self._hline())
        # breakaway cap selector (multi-unit: stiff gearboxes need 0.4*CL —
        # fable-physics: this unit shows NO breakaway at the default 0.2*CL;
        # the kernel's RAMP_FRAC_ABS_MAX(0.4) pre-gate stays the hard ceiling)
        self.tuning_expert_frame = QtWidgets.QFrame()
        self.tuning_expert_frame.setObjectName("chip")
        expert_layout = QtWidgets.QVBoxLayout(self.tuning_expert_frame)
        expert_layout.setContentsMargins(12, 10, 12, 10); expert_layout.setSpacing(8)
        expert_title = QtWidgets.QLabel(
            "EXPERT CONTROLS  ·  CANDIDATES + INSTALLED-GAIN VERIFY")
        expert_title.setProperty("role", "field"); expert_layout.addWidget(expert_title)

        self.expert_lab_frame = QtWidgets.QFrame()
        self.expert_lab_frame.setObjectName("inset")
        lab_layout = QtWidgets.QVBoxLayout(self.expert_lab_frame)
        lab_layout.setContentsMargins(10, 10, 10, 10)
        lab_layout.setSpacing(7)
        self.expert_lab_title = QtWidgets.QLabel(
            "EXPERT CANDIDATE LAB v2 · OFFLINE MODEL · NO DRIVE I/O")
        self.expert_lab_title.setProperty("role", "celltitle")
        self.expert_lab_title.setWordWrap(True)
        self.expert_lab_title.setMinimumWidth(0)
        self.expert_lab_title.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred)
        self._expert_model_title = self.expert_lab_title.text()
        lab_layout.addWidget(self.expert_lab_title)
        self.expert_lab_note = QtWidgets.QLabel(
            "Two-step local model: first design Current P1 from explicit "
            "phase-to-phase inputs, then project Velocity / Position P2 from "
            "explicit K_a and B. Calculate never connects, enqueues, applies, "
            "verifies, saves, or changes installed-drive authority.")
        self.expert_lab_note.setProperty("role", "hint")
        self.expert_lab_note.setWordWrap(True)
        self.expert_lab_note.setMinimumWidth(0)
        self.expert_lab_note.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred)
        self.expert_lab_note.setMinimumHeight(max(
            48, self.expert_lab_note.sizeHint().height()))
        self._expert_model_note = self.expert_lab_note.text()
        lab_layout.addWidget(self.expert_lab_note)

        expert_step_grid = QtWidgets.QGridLayout()
        expert_step_grid.setHorizontalSpacing(8)
        expert_step_grid.setVerticalSpacing(6)
        self.btn_expert_step_current = QtWidgets.QPushButton(
            "1 · CURRENT P1")
        self.btn_expert_step_vp = QtWidgets.QPushButton(
            "2 · VEL / POS P2")
        self.btn_expert_step_evidence = QtWidgets.QPushButton(
            "3 · FILTER / SCHED")
        self.btn_expert_step_status = QtWidgets.QPushButton(
            "4 · STATUS / ERRORS")
        self.btn_expert_step_user_units = QtWidgets.QPushButton(
            "5 · USER UNITS")
        self.btn_expert_step_limits = QtWidgets.QPushButton(
            "6 · LIMITS / PROTECT")
        self.btn_expert_step_application = QtWidgets.QPushButton(
            "7 · APP SETTINGS")
        self.btn_expert_step_bode_verification = QtWidgets.QPushButton(
            "8 · BODE DOC MAP")
        self.btn_expert_step_time_verification = QtWidgets.QPushButton(
            "9 · TIME DOC MAP")
        self.btn_expert_step_summary = QtWidgets.QPushButton(
            "10 · SUMMARY DOC MAP")
        self.btn_expert_step_current.setCheckable(True)
        self.btn_expert_step_vp.setCheckable(True)
        self.btn_expert_step_evidence.setCheckable(True)
        self.btn_expert_step_status.setCheckable(True)
        self.btn_expert_step_user_units.setCheckable(True)
        self.btn_expert_step_limits.setCheckable(True)
        self.btn_expert_step_application.setCheckable(True)
        self.btn_expert_step_bode_verification.setCheckable(True)
        self.btn_expert_step_time_verification.setCheckable(True)
        self.btn_expert_step_summary.setCheckable(True)
        for button in (
                self.btn_expert_step_current,
                self.btn_expert_step_vp,
                self.btn_expert_step_evidence,
                self.btn_expert_step_status,
                self.btn_expert_step_user_units,
                self.btn_expert_step_limits,
                self.btn_expert_step_application,
                self.btn_expert_step_bode_verification,
                self.btn_expert_step_time_verification,
                self.btn_expert_step_summary):
            button.setMinimumWidth(0)
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Fixed)
        self.expert_lab_step_group = QtWidgets.QButtonGroup(self)
        self.expert_lab_step_group.setExclusive(True)
        self.expert_lab_step_group.addButton(self.btn_expert_step_current)
        self.expert_lab_step_group.addButton(self.btn_expert_step_vp)
        self.expert_lab_step_group.addButton(self.btn_expert_step_evidence)
        self.expert_lab_step_group.addButton(self.btn_expert_step_status)
        self.expert_lab_step_group.addButton(
            self.btn_expert_step_user_units)
        self.expert_lab_step_group.addButton(self.btn_expert_step_limits)
        self.expert_lab_step_group.addButton(
            self.btn_expert_step_application)
        self.expert_lab_step_group.addButton(
            self.btn_expert_step_bode_verification)
        self.expert_lab_step_group.addButton(
            self.btn_expert_step_time_verification)
        self.expert_lab_step_group.addButton(
            self.btn_expert_step_summary)
        self.btn_expert_step_current.clicked.connect(
            lambda: self._set_expert_lab_step("current"))
        self.btn_expert_step_vp.clicked.connect(
            lambda: self._set_expert_lab_step("vp"))
        self.btn_expert_step_evidence.clicked.connect(
            lambda: self._set_expert_lab_step("evidence"))
        self.btn_expert_step_status.clicked.connect(
            lambda: self._set_expert_lab_step("status"))
        self.btn_expert_step_user_units.clicked.connect(
            lambda: self._set_expert_lab_step("user_units"))
        self.btn_expert_step_limits.clicked.connect(
            lambda: self._set_expert_lab_step("limits_protections"))
        self.btn_expert_step_application.clicked.connect(
            lambda: self._set_expert_lab_step("application_settings"))
        self.btn_expert_step_bode_verification.clicked.connect(
            lambda: self._set_expert_lab_step("bode_verification"))
        self.btn_expert_step_time_verification.clicked.connect(
            lambda: self._set_expert_lab_step("time_verification"))
        self.btn_expert_step_summary.clicked.connect(
            lambda: self._set_expert_lab_step("summary"))
        expert_step_grid.addWidget(
            self.btn_expert_step_current, 0, 0)
        expert_step_grid.addWidget(
            self.btn_expert_step_vp, 0, 1)
        expert_step_grid.addWidget(
            self.btn_expert_step_evidence, 0, 2)
        expert_step_grid.addWidget(
            self.btn_expert_step_status, 1, 0)
        expert_step_grid.addWidget(
            self.btn_expert_step_user_units, 1, 1)
        expert_step_grid.addWidget(
            self.btn_expert_step_limits, 1, 2)
        expert_step_grid.addWidget(
            self.btn_expert_step_application, 2, 0)
        expert_step_grid.addWidget(
            self.btn_expert_step_bode_verification, 2, 1)
        expert_step_grid.addWidget(
            self.btn_expert_step_time_verification, 2, 2)
        expert_step_grid.addWidget(
            self.btn_expert_step_summary, 3, 0, 1, 3)
        for column in range(3):
            expert_step_grid.setColumnStretch(column, 1)
        lab_layout.addLayout(expert_step_grid)

        self.expert_lab_stack = QtWidgets.QStackedWidget()
        self.expert_lab_stack.setMinimumWidth(0)
        self.expert_lab_stack.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred)
        current_page = QtWidgets.QWidget()
        current_page_layout = QtWidgets.QVBoxLayout(current_page)
        current_page_layout.setContentsMargins(0, 0, 0, 0)
        current_page_layout.setSpacing(7)

        lab_form = QtWidgets.QGridLayout()
        lab_form.setHorizontalSpacing(10)
        lab_form.setVerticalSpacing(6)
        self.expert_lab_r_ohm = QtWidgets.QLineEdit()
        self.expert_lab_l_uh = QtWidgets.QLineEdit()
        self.expert_lab_ts_us = QtWidgets.QLineEdit()
        self.expert_lab_bandwidth_hz = QtWidgets.QLineEdit()
        self.expert_lab_bandwidth_hz.setPlaceholderText(
            "blank = calibrated model law")
        for row, (label, field) in enumerate((
                ("R phase-to-phase [ohm]", self.expert_lab_r_ohm),
                ("L phase-to-phase [uH]", self.expert_lab_l_uh),
                ("TS [us]", self.expert_lab_ts_us),
                ("Target bandwidth [Hz] (optional)",
                 self.expert_lab_bandwidth_hz))):
            name = QtWidgets.QLabel(label)
            name.setProperty("role", "field")
            lab_form.addWidget(name, row, 0)
            lab_form.addWidget(field, row, 1)
        rule_label = QtWidgets.QLabel("KI rule")
        rule_label.setProperty("role", "field")
        self.expert_lab_ki_rule = QtWidgets.QComboBox()
        self.expert_lab_ki_rule.addItem("EAS ratio", "eas_ratio")
        self.expert_lab_ki_rule.addItem("Pole-zero", "pole_zero")
        lab_form.addWidget(rule_label, 4, 0)
        lab_form.addWidget(self.expert_lab_ki_rule, 4, 1)
        self.btn_expert_calculate = QtWidgets.QPushButton(
            "Calculate Candidate · OFFLINE")
        self.btn_expert_calculate.clicked.connect(
            self._calculate_expert_candidate)
        lab_form.addWidget(self.btn_expert_calculate, 5, 0, 1, 2)
        current_page_layout.addLayout(lab_form)

        self.expert_lab_status = QtWidgets.QLabel(
            "MODEL · waiting for explicit plant inputs · no candidate")
        self.expert_lab_status.setProperty("role", "hint")
        self.expert_lab_status.setWordWrap(True)
        current_page_layout.addWidget(self.expert_lab_status)
        self.expert_lab_response_summary = QtWidgets.QLabel(
            "Bode-ready response · not calculated")
        self.expert_lab_response_summary.setProperty("role", "hint")
        self.expert_lab_response_summary.setWordWrap(True)
        current_page_layout.addWidget(self.expert_lab_response_summary)
        self.expert_bode_widget = ExpertBodeWidget()
        current_page_layout.addWidget(self.expert_bode_widget)
        self.expert_lab_stack.addWidget(current_page)

        vp_page = QtWidgets.QWidget()
        vp_page_layout = QtWidgets.QVBoxLayout(vp_page)
        vp_page_layout.setContentsMargins(0, 0, 0, 0)
        vp_page_layout.setSpacing(7)
        self.expert_vp_basis = QtWidgets.QLabel(
            "MODEL basis · velocity = encoder counts/s · current = peak A · "
            "K_a = cnt/s²/A_peak · B = A_peak/(cnt/s). Requires the complete "
            "passing Current P1 MODEL above. Single-point calibrated for the "
            "current Gold Twitter / motor / TS combination; not generalized "
            "to other motors, feedbacks, firmware, or Gold products.")
        self.expert_vp_basis.setProperty("role", "hint")
        self.expert_vp_basis.setWordWrap(True)
        self.expert_vp_basis.setMinimumWidth(0)
        self.expert_vp_basis.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Preferred)
        self.expert_vp_basis.setMinimumHeight(max(
            58, self.expert_vp_basis.sizeHint().height()))
        vp_page_layout.addWidget(self.expert_vp_basis)

        vp_form = QtWidgets.QGridLayout()
        vp_form.setHorizontalSpacing(10)
        vp_form.setVerticalSpacing(6)
        self.expert_vp_ka = QtWidgets.QLineEdit()
        self.expert_vp_b_visc = QtWidgets.QLineEdit()
        for row, (label, field) in enumerate((
                ("Acceleration constant K_a [cnt/s²/A_peak]",
                 self.expert_vp_ka),
                ("Viscous friction B [A_peak/(cnt/s)]",
                 self.expert_vp_b_visc))):
            name = QtWidgets.QLabel(label)
            name.setProperty("role", "field")
            vp_form.addWidget(name, row, 0)
            vp_form.addWidget(field, row, 1)
        self.btn_expert_vp_calculate = QtWidgets.QPushButton(
            "Calculate P2 Candidate · OFFLINE")
        self.btn_expert_vp_calculate.clicked.connect(
            self._calculate_expert_vp_candidate)
        vp_form.addWidget(self.btn_expert_vp_calculate, 2, 0, 1, 2)
        vp_page_layout.addLayout(vp_form)

        self.expert_vp_status = QtWidgets.QLabel(
            "MODEL · calculate after Current candidate · no P2 candidate")
        self.expert_vp_status.setProperty("role", "hint")
        self.expert_vp_status.setWordWrap(True)
        vp_page_layout.addWidget(self.expert_vp_status)
        vp_results = QtWidgets.QGridLayout()
        vp_results.setHorizontalSpacing(10)
        vp_results.setVerticalSpacing(6)
        self.expert_vp_result_fields = {}
        for row, (key, label) in enumerate((
                ("kp_vel", "Velocity KP[2] [A_peak/(cnt/s)]"),
                ("ki_vel", "Velocity KI[2] [Hz]"),
                ("kp_pos",
                 "Position KP[3] [rad/s command ref; count MODEL 1/s]"),
                ("pm_vel", "Velocity margin [deg; GM dB]"),
                ("pm_pos", "Position margin [deg]"))):
            name = QtWidgets.QLabel(label)
            name.setProperty("role", "field")
            value = QtWidgets.QLineEdit("—")
            value.setReadOnly(True)
            vp_results.addWidget(name, row, 0)
            vp_results.addWidget(value, row, 1)
            self.expert_vp_result_fields[key] = value
        vp_page_layout.addLayout(vp_results)
        expert_vp_boundary = QtWidgets.QLabel(
            "FILTER NEED-DATA · GAIN SCHEDULING GS[2]≠0 NEED-DATA · "
            "no KV / GS / KG emulation or writes")
        expert_vp_boundary.setProperty("role", "hint")
        expert_vp_boundary.setWordWrap(True)
        vp_page_layout.addWidget(expert_vp_boundary)
        vp_page_layout.addStretch(1)
        self.expert_lab_stack.addWidget(vp_page)

        self.expert_evidence_page = QtWidgets.QWidget()
        evidence_layout = QtWidgets.QVBoxLayout(self.expert_evidence_page)
        evidence_layout.setContentsMargins(0, 0, 0, 0)
        evidence_layout.setSpacing(7)
        self._expert_evidence = (
            expert_filter_scheduling_evidence.build_evidence_snapshot())
        self.expert_evidence_status = QtWidgets.QLabel(
            "DOCUMENTED TOPOLOGY ONLY · LOCAL INSPECTOR · "
            "NO MODEL · NO EMULATION · NO WRITE · NO DRIVE I/O")
        self.expert_evidence_status.setProperty("role", "hint")
        self.expert_evidence_status.setWordWrap(True)
        evidence_layout.addWidget(self.expert_evidence_status)

        evidence_form = QtWidgets.QGridLayout()
        evidence_form.setHorizontalSpacing(10)
        evidence_form.setVerticalSpacing(6)
        filter_type_label = QtWidgets.QLabel("Documented filter type")
        filter_type_label.setProperty("role", "field")
        self.expert_filter_type = QtWidgets.QComboBox()
        for item in self._expert_evidence.filter_types:
            self.expert_filter_type.addItem(
                "%d · %s" % (item.code, item.name), item.code)
        filter_location_label = QtWidgets.QLabel(
            "Controller filter location")
        filter_location_label.setProperty("role", "field")
        self.expert_filter_location = QtWidgets.QComboBox()
        for item in self._expert_evidence.filter_locations:
            self.expert_filter_location.addItem(item.label, item.key)
        schedule_mode_label = QtWidgets.QLabel("GS[2] mode inspector")
        schedule_mode_label.setProperty("role", "field")
        self.expert_schedule_mode = QtWidgets.QSpinBox()
        self.expert_schedule_mode.setRange(0, 66)
        self.expert_schedule_mode.setPrefix("GS[2] = ")
        evidence_form.addWidget(filter_type_label, 0, 0)
        evidence_form.addWidget(self.expert_filter_type, 0, 1)
        evidence_form.addWidget(filter_location_label, 1, 0)
        evidence_form.addWidget(self.expert_filter_location, 1, 1)
        evidence_form.addWidget(schedule_mode_label, 2, 0)
        evidence_form.addWidget(self.expert_schedule_mode, 2, 1)
        evidence_layout.addLayout(evidence_form)

        self.expert_filter_type_detail = QtWidgets.QLabel()
        self.expert_filter_location_detail = QtWidgets.QLabel()
        self.expert_schedule_mode_detail = QtWidgets.QLabel()
        self.expert_evidence_documented_facts = QtWidgets.QLabel()
        self.expert_evidence_conflicts = QtWidgets.QLabel()
        self.expert_evidence_missing = QtWidgets.QLabel()
        for detail in (
                self.expert_filter_type_detail,
                self.expert_filter_location_detail,
                self.expert_schedule_mode_detail,
                self.expert_evidence_documented_facts,
                self.expert_evidence_conflicts,
                self.expert_evidence_missing):
            detail.setProperty("role", "hint")
            detail.setWordWrap(True)
            detail.setMinimumWidth(0)
            detail.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Preferred)
            evidence_layout.addWidget(detail)
        evidence_source = QtWidgets.QLabel(
            "SOURCE · %s · SHA-256 %s" % (
                self._expert_evidence.source,
                self._expert_evidence.source_sha256))
        evidence_source.setProperty("role", "hint")
        evidence_source.setWordWrap(True)
        evidence_layout.addWidget(evidence_source)
        evidence_layout.addStretch(1)
        self.expert_lab_stack.addWidget(self.expert_evidence_page)

        self.expert_page_status_page = QtWidgets.QWidget()
        page_status_layout = QtWidgets.QVBoxLayout(
            self.expert_page_status_page)
        page_status_layout.setContentsMargins(0, 0, 0, 0)
        page_status_layout.setSpacing(7)
        self.expert_page_status_banner = QtWidgets.QLabel(
            "LOCAL STATUS ONLY · NOT EAS ENTER/APPLY STATE · NOT INSTALLED · "
            "NO CALCULATION · NO WRITE · NO DRIVE I/O")
        self.expert_page_status_banner.setProperty("role", "hint")
        self.expert_page_status_banner.setWordWrap(True)
        page_status_layout.addWidget(self.expert_page_status_banner)
        self.expert_page_status_overall = QtWidgets.QLabel(
            "OVERALL PARTIAL · local state not yet classified")
        self.expert_page_status_overall.setProperty("role", "field")
        self.expert_page_status_overall.setWordWrap(True)
        page_status_layout.addWidget(self.expert_page_status_overall)

        page_status_grid = QtWidgets.QGridLayout()
        page_status_grid.setHorizontalSpacing(10)
        page_status_grid.setVerticalSpacing(7)
        self.expert_page_status_rows = {}
        self.expert_page_status_open_buttons = {}
        for row, (key, label, target) in enumerate((
                ("current", "Current P1", "current"),
                ("vp", "Velocity / Position P2", "vp"),
                ("evidence", "Filter / Scheduling Evidence", "evidence"))):
            name = QtWidgets.QLabel(label)
            name.setProperty("role", "field")
            detail = QtWidgets.QLabel()
            detail.setProperty("role", "hint")
            detail.setWordWrap(True)
            detail.setMinimumWidth(0)
            detail.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Preferred)
            open_button = QtWidgets.QPushButton("Open")
            open_button.clicked.connect(
                lambda _checked=False, page=target:
                self._set_expert_lab_step(page))
            self._decorate_operation_control(
                open_button, "tuning.expert.page_status.inspect")
            page_status_grid.addWidget(name, row, 0)
            page_status_grid.addWidget(detail, row, 1)
            page_status_grid.addWidget(open_button, row, 2)
            self.expert_page_status_rows[key] = detail
            self.expert_page_status_open_buttons[key] = open_button
        page_status_grid.setColumnStretch(1, 1)
        page_status_layout.addLayout(page_status_grid)
        self.expert_page_status_source = QtWidgets.QLabel(
            "SOURCE · %s · SHA-256 %s" % (
                expert_page_status.SOURCE,
                expert_page_status.SOURCE_SHA256))
        self.expert_page_status_source.setProperty("role", "hint")
        self.expert_page_status_source.setWordWrap(True)
        page_status_layout.addWidget(self.expert_page_status_source)
        page_status_boundary = QtWidgets.QLabel(
            "EAS Idle/Changed/Warning icon parity, Enter, Apply, Apply All, "
            "Revert, saved-last-page behavior and completion recommendations "
            "remain unimplemented / NEED-DATA.")
        page_status_boundary.setProperty("role", "hint")
        page_status_boundary.setWordWrap(True)
        page_status_layout.addWidget(page_status_boundary)
        page_status_layout.addStretch(1)
        self.expert_lab_stack.addWidget(self.expert_page_status_page)

        self.expert_user_units_page = QtWidgets.QWidget()
        user_units_layout = QtWidgets.QVBoxLayout(
            self.expert_user_units_page)
        user_units_layout.setContentsMargins(0, 0, 0, 0)
        user_units_layout.setSpacing(7)
        self.expert_user_units_banner = QtWidgets.QLabel(
            expert_user_units.BOUNDARY)
        self.expert_user_units_banner.setProperty("role", "hint")
        self.expert_user_units_banner.setWordWrap(True)
        user_units_layout.addWidget(self.expert_user_units_banner)
        self.expert_user_units_grouping_notice = QtWidgets.QLabel(
            "DOCUMENTED GROUPING MISMATCH · PURPOSE NEED-DATA · "
            "NetHelp formula and MAN-G-CR limit guards are shown separately; "
            "neither is silently rewritten.")
        self.expert_user_units_grouping_notice.setProperty("role", "hint")
        self.expert_user_units_grouping_notice.setWordWrap(True)
        user_units_layout.addWidget(
            self.expert_user_units_grouping_notice)
        self.expert_user_units_formula = QtWidgets.QLabel(
            "NetHelp position formula · user unit/count = "
            "(FC[2] × FC[6] × FC[7]) / "
            "(FC[1] × FC[5] × FC[8])")
        self.expert_user_units_formula.setProperty("role", "field")
        self.expert_user_units_formula.setWordWrap(True)
        user_units_layout.addWidget(self.expert_user_units_formula)

        user_units_form = QtWidgets.QGridLayout()
        user_units_form.setHorizontalSpacing(10)
        user_units_form.setVerticalSpacing(6)
        self.expert_user_units_fc_fields = {}
        fc_rows = (
            ("fc1", "FC[1] · encoder counts"),
            ("fc2", "FC[2] · motor-shaft revs"),
            ("fc5", "FC[5] · motor-shaft revs"),
            ("fc6", "FC[6] · driving-shaft revs"),
            ("fc7", "FC[7] · feed [user units]"),
            ("fc8", "FC[8] · driving-shaft revs"),
        )
        for index, (key, label) in enumerate(fc_rows):
            row = index // 2
            column = (index % 2) * 2
            name = QtWidgets.QLabel(label)
            name.setProperty("role", "field")
            field = QtWidgets.QLineEdit()
            field.setPlaceholderText("explicit integer · 1..2³¹−1")
            user_units_form.addWidget(name, row, column)
            user_units_form.addWidget(field, row, column + 1)
            self.expert_user_units_fc_fields[key] = field
        unit_label_name = QtWidgets.QLabel("Unit label · display only")
        unit_label_name.setProperty("role", "field")
        self.expert_user_units_unit_label = QtWidgets.QLineEdit()
        self.expert_user_units_unit_label.setPlaceholderText(
            "optional · e.g. µm")
        sample_name = QtWidgets.QLabel("Sample encoder counts")
        sample_name.setProperty("role", "field")
        self.expert_user_units_sample_counts = QtWidgets.QLineEdit()
        self.expert_user_units_sample_counts.setPlaceholderText(
            "optional signed integer")
        user_units_form.addWidget(unit_label_name, 3, 0)
        user_units_form.addWidget(
            self.expert_user_units_unit_label, 3, 1)
        user_units_form.addWidget(sample_name, 3, 2)
        user_units_form.addWidget(
            self.expert_user_units_sample_counts, 3, 3)
        self.btn_expert_user_units_preview = QtWidgets.QPushButton(
            "Preview Documented Position Formula · LOCAL ONLY")
        self.btn_expert_user_units_preview.clicked.connect(
            self._calculate_expert_user_units_preview)
        self._decorate_operation_control(
            self.btn_expert_user_units_preview,
            "tuning.expert.user_units.preview")
        user_units_form.addWidget(
            self.btn_expert_user_units_preview, 4, 0, 1, 4)
        user_units_form.setColumnStretch(1, 1)
        user_units_form.setColumnStretch(3, 1)
        user_units_layout.addLayout(user_units_form)

        self.expert_user_units_status = QtWidgets.QLabel(
            "PARTIAL / SCREENING · waiting for explicit manual inputs · "
            "DOCUMENTED GROUPING MISMATCH · PURPOSE NEED-DATA")
        self.expert_user_units_status.setProperty("role", "hint")
        self.expert_user_units_status.setWordWrap(True)
        user_units_layout.addWidget(self.expert_user_units_status)
        user_units_results = QtWidgets.QGridLayout()
        user_units_results.setHorizontalSpacing(10)
        user_units_results.setVerticalSpacing(6)
        self.expert_user_units_result_fields = {}
        for row, (key, label) in enumerate((
                ("units_per_count", "Position user units / encoder count"),
                ("counts_per_unit", "Encoder counts / position user unit"),
                ("sample_units", "Optional sample conversion"))):
            name = QtWidgets.QLabel(label)
            name.setProperty("role", "field")
            value = QtWidgets.QLineEdit("—")
            value.setReadOnly(True)
            user_units_results.addWidget(name, row, 0)
            user_units_results.addWidget(value, row, 1)
            self.expert_user_units_result_fields[key] = value
        user_units_results.setColumnStretch(1, 1)
        user_units_layout.addLayout(user_units_results)
        self.expert_user_units_limits = QtWidgets.QLabel(
            "MAN-G-CR literal guards · FC[1]×FC[6]×FC[8] < 2⁶³ · "
            "FC[2]×FC[5]×FC[7] < 2⁶³ · these are not relabeled as the "
            "NetHelp formula numerator/denominator.")
        self.expert_user_units_limits.setProperty("role", "hint")
        self.expert_user_units_limits.setWordWrap(True)
        user_units_layout.addWidget(self.expert_user_units_limits)
        self.expert_user_units_source = QtWidgets.QLabel(
            "SOURCES · NetHelp HTML SHA-256 %s · formula image SHA-256 %s · "
            "MAN-G-CR SHA-256 %s" % tuple(
                source.sha256 for source in expert_user_units.SOURCES))
        self.expert_user_units_source.setProperty("role", "hint")
        self.expert_user_units_source.setWordWrap(True)
        user_units_layout.addWidget(self.expert_user_units_source)
        user_units_layout.addStretch(1)
        self.expert_lab_stack.addWidget(self.expert_user_units_page)

        self.expert_limits_protections_page = QtWidgets.QWidget()
        limits_layout = QtWidgets.QVBoxLayout(
            self.expert_limits_protections_page)
        limits_layout.setContentsMargins(0, 0, 0, 0)
        limits_layout.setSpacing(7)
        self._expert_limits_protections = (
            expert_limits_protections_evidence.build_evidence_snapshot())
        self.expert_limits_banner = QtWidgets.QLabel(
            self._expert_limits_protections.boundary)
        self.expert_limits_banner.setProperty("role", "hint")
        self.expert_limits_banner.setWordWrap(True)
        limits_layout.addWidget(self.expert_limits_banner)
        self.expert_limits_status = QtWidgets.QLabel()
        self.expert_limits_status.setProperty("role", "field")
        self.expert_limits_status.setWordWrap(True)
        limits_layout.addWidget(self.expert_limits_status)

        limits_selector_layout = QtWidgets.QHBoxLayout()
        limits_selector_label = QtWidgets.QLabel(
            "Documented EAS section")
        limits_selector_label.setProperty("role", "field")
        self.expert_limits_section = QtWidgets.QComboBox()
        self.expert_limits_section.setEditable(False)
        for section in self._expert_limits_protections.sections:
            self.expert_limits_section.addItem(
                "%s · %s" % (section.label, section.reference),
                section.key)
        limits_selector_layout.addWidget(limits_selector_label)
        limits_selector_layout.addWidget(self.expert_limits_section, 1)
        limits_layout.addLayout(limits_selector_layout)

        self.expert_limits_table = QtWidgets.QTableWidget(0, 4)
        self.expert_limits_table.setObjectName("expertEvidenceTable")
        self.expert_limits_table.setHorizontalHeaderLabels((
            "COMMAND",
            "DOCUMENTED ROLE",
            "UNIT / DOCUMENTED REF ACCESS",
            "CONDITION / CONFLICT",
        ))
        self.expert_limits_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.expert_limits_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.expert_limits_table.setFocusPolicy(
            QtCore.Qt.FocusPolicy.NoFocus)
        self.expert_limits_table.setWordWrap(True)
        self.expert_limits_table.setAlternatingRowColors(True)
        self.expert_limits_table.setMinimumWidth(0)
        self.expert_limits_table.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Expanding)
        self.expert_limits_table.verticalHeader().setVisible(False)
        limits_header = self.expert_limits_table.horizontalHeader()
        for column in range(4):
            limits_header.setSectionResizeMode(
                column,
                QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.expert_limits_table.setMinimumHeight(250)
        limits_layout.addWidget(self.expert_limits_table, 1)

        self.expert_limits_conflicts = QtWidgets.QLabel(
            "DOCUMENT CONFLICTS · " + " | ".join(
                self._expert_limits_protections.document_conflicts))
        self.expert_limits_warnings = QtWidgets.QLabel(
            "PERSISTENT WARNINGS · " + " | ".join(
                self._expert_limits_protections.persistent_warnings))
        self.expert_limits_missing = QtWidgets.QLabel(
            "MISSING EVIDENCE / NEED-DATA · " + " | ".join(
                self._expert_limits_protections.missing_evidence))
        for detail in (
                self.expert_limits_conflicts,
                self.expert_limits_warnings,
                self.expert_limits_missing):
            detail.setProperty("role", "hint")
            detail.setWordWrap(True)
            detail.setMinimumWidth(0)
            detail.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Preferred)
            limits_layout.addWidget(detail)
        self.expert_limits_sources = QtWidgets.QLabel(
            "SOURCES · %d frozen identities · NetHelp HTML SHA-256 %s · "
            "MAN-G-CR SHA-256 %s" % (
                len(self._expert_limits_protections.sources),
                self._expert_limits_protections.sources[0].sha256,
                next(
                    source.sha256
                    for source in self._expert_limits_protections.sources
                    if source.key == "command_reference")))
        self.expert_limits_sources.setProperty("role", "hint")
        self.expert_limits_sources.setWordWrap(True)
        limits_layout.addWidget(self.expert_limits_sources)
        self.expert_lab_stack.addWidget(
            self.expert_limits_protections_page)

        self.expert_application_settings_page = QtWidgets.QWidget()
        application_layout = QtWidgets.QVBoxLayout(
            self.expert_application_settings_page)
        application_layout.setContentsMargins(0, 0, 0, 0)
        application_layout.setSpacing(7)
        self._expert_application_settings = (
            expert_application_settings_evidence.build_evidence_snapshot())
        self.expert_application_banner = QtWidgets.QLabel(
            self._expert_application_settings.boundary)
        self.expert_application_banner.setProperty("role", "hint")
        self.expert_application_banner.setWordWrap(True)
        application_layout.addWidget(self.expert_application_banner)
        self.expert_application_status = QtWidgets.QLabel()
        self.expert_application_status.setProperty("role", "field")
        self.expert_application_status.setWordWrap(True)
        application_layout.addWidget(self.expert_application_status)

        application_selector_layout = QtWidgets.QHBoxLayout()
        application_selector_label = QtWidgets.QLabel(
            "Documented EAS section")
        application_selector_label.setProperty("role", "field")
        self.expert_application_section = QtWidgets.QComboBox()
        self.expert_application_section.setEditable(False)
        for section in self._expert_application_settings.sections:
            self.expert_application_section.addItem(
                "%s · %s" % (section.label, section.reference),
                section.key)
        application_selector_layout.addWidget(application_selector_label)
        application_selector_layout.addWidget(
            self.expert_application_section, 1)
        application_layout.addLayout(application_selector_layout)

        self.expert_application_table = QtWidgets.QTableWidget(0, 4)
        self.expert_application_table.setObjectName("expertEvidenceTable")
        self.expert_application_table.setHorizontalHeaderLabels((
            "COMMAND",
            "ROLE / REF",
            "UNIT / ACCESS",
            "STATUS / NOTE",
        ))
        for column, tooltip in enumerate((
                "Documented command or combined semantics reference.",
                "Documented role, range, and reference only; not current.",
                "Documented unit/access; app remains inspect-only.",
                "Evidence status plus condition, conflict, or missing scope.",
        )):
            self.expert_application_table.horizontalHeaderItem(
                column).setToolTip(tooltip)
        self.expert_application_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.expert_application_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.expert_application_table.setFocusPolicy(
            QtCore.Qt.FocusPolicy.NoFocus)
        self.expert_application_table.setWordWrap(True)
        self.expert_application_table.setAlternatingRowColors(True)
        self.expert_application_table.setMinimumWidth(0)
        self.expert_application_table.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Expanding)
        self.expert_application_table.verticalHeader().setVisible(False)
        application_header = self.expert_application_table.horizontalHeader()
        for column in range(4):
            application_header.setSectionResizeMode(
                column,
                QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.expert_application_table.setMinimumHeight(250)
        application_layout.addWidget(self.expert_application_table, 1)

        self.expert_application_conflicts = QtWidgets.QLabel(
            "DOCUMENT CONFLICTS · " + " | ".join(
                self._expert_application_settings.document_conflicts))
        self.expert_application_warnings = QtWidgets.QLabel(
            "PERSISTENT WARNINGS · " + " | ".join(
                self._expert_application_settings.persistent_warnings))
        self.expert_application_missing = QtWidgets.QLabel(
            "MISSING EVIDENCE / NEED-DATA · " + " | ".join(
                self._expert_application_settings.missing_evidence))
        for detail in (
                self.expert_application_conflicts,
                self.expert_application_warnings,
                self.expert_application_missing):
            detail.setProperty("role", "hint")
            detail.setWordWrap(True)
            detail.setMinimumWidth(0)
            detail.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Preferred)
            application_layout.addWidget(detail)
        self.expert_application_sources = QtWidgets.QLabel(
            "SOURCES · %d frozen identities · EAS III HTML SHA-256 %s · "
            "MAN-G-CR v2.001 root SHA-256 %s" % (
                len(self._expert_application_settings.sources),
                next(
                    source.sha256
                    for source in self._expert_application_settings.sources
                    if source.key == "app_settings_html"),
                next(
                    source.sha256
                    for source in self._expert_application_settings.sources
                    if source.key == "man_g_cr_root")))
        self.expert_application_sources.setProperty("role", "hint")
        self.expert_application_sources.setWordWrap(True)
        application_layout.addWidget(self.expert_application_sources)
        self.expert_lab_stack.addWidget(
            self.expert_application_settings_page)

        self.expert_bode_verification_page = QtWidgets.QWidget()
        bode_verification_layout = QtWidgets.QVBoxLayout(
            self.expert_bode_verification_page)
        bode_verification_layout.setContentsMargins(0, 0, 0, 0)
        bode_verification_layout.setSpacing(7)
        self._expert_bode_verification = (
            expert_bode_verification_evidence.build_evidence_snapshot())
        self.expert_bode_verification_banner = QtWidgets.QLabel(
            self._expert_bode_verification.boundary)
        self.expert_bode_verification_banner.setProperty("role", "hint")
        self.expert_bode_verification_banner.setWordWrap(True)
        bode_verification_layout.addWidget(
            self.expert_bode_verification_banner)
        self.expert_bode_verification_status = QtWidgets.QLabel()
        self.expert_bode_verification_status.setProperty("role", "field")
        self.expert_bode_verification_status.setWordWrap(True)
        bode_verification_layout.addWidget(
            self.expert_bode_verification_status)

        bode_verification_selector_layout = QtWidgets.QHBoxLayout()
        bode_verification_selector_label = QtWidgets.QLabel(
            "Documented EAS verification section")
        bode_verification_selector_label.setProperty("role", "field")
        self.expert_bode_verification_section = QtWidgets.QComboBox()
        self.expert_bode_verification_section.setEditable(False)
        for section in self._expert_bode_verification.sections:
            self.expert_bode_verification_section.addItem(
                "%s · %s" % (section.label, section.reference),
                section.key)
        bode_verification_selector_layout.addWidget(
            bode_verification_selector_label)
        bode_verification_selector_layout.addWidget(
            self.expert_bode_verification_section, 1)
        bode_verification_layout.addLayout(
            bode_verification_selector_layout)

        self.expert_bode_verification_table = QtWidgets.QTableWidget(0, 4)
        self.expert_bode_verification_table.setObjectName(
            "expertEvidenceTable")
        self.expert_bode_verification_table.setHorizontalHeaderLabels((
            "CONTROL",
            "ROLE / REF",
            "UNIT / ACCESS",
            "STATUS / NOTE",
        ))
        for column, tooltip in enumerate((
                "Documented EAS control name; not an executable control.",
                "Documented role and reference only; not a result.",
                "Documented unit/access; app remains inspect-only.",
                "Evidence status plus conflict, risk, or missing scope.",
        )):
            self.expert_bode_verification_table.horizontalHeaderItem(
                column).setToolTip(tooltip)
        self.expert_bode_verification_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.expert_bode_verification_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.expert_bode_verification_table.setFocusPolicy(
            QtCore.Qt.FocusPolicy.NoFocus)
        self.expert_bode_verification_table.setWordWrap(True)
        self.expert_bode_verification_table.setAlternatingRowColors(True)
        self.expert_bode_verification_table.setMinimumWidth(0)
        self.expert_bode_verification_table.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Expanding)
        self.expert_bode_verification_table.verticalHeader().setVisible(False)
        bode_verification_header = (
            self.expert_bode_verification_table.horizontalHeader())
        for column in range(4):
            bode_verification_header.setSectionResizeMode(
                column,
                QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.expert_bode_verification_table.setMinimumHeight(250)
        bode_verification_layout.addWidget(
            self.expert_bode_verification_table, 1)

        self.expert_bode_verification_conflicts = QtWidgets.QLabel(
            "DOCUMENT CONFLICTS · " + " | ".join(
                self._expert_bode_verification.document_conflicts))
        self.expert_bode_verification_warnings = QtWidgets.QLabel(
            "PERSISTENT WARNINGS · " + " | ".join(
                self._expert_bode_verification.persistent_warnings))
        self.expert_bode_verification_missing = QtWidgets.QLabel(
            "MISSING EVIDENCE / NEED-DATA · " + " | ".join(
                self._expert_bode_verification.missing_evidence))
        for detail in (
                self.expert_bode_verification_conflicts,
                self.expert_bode_verification_warnings,
                self.expert_bode_verification_missing):
            detail.setProperty("role", "hint")
            detail.setWordWrap(True)
            detail.setMinimumWidth(0)
            detail.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Preferred)
            bode_verification_layout.addWidget(detail)
        self.expert_bode_verification_sources = QtWidgets.QLabel(
            "SOURCES · %d frozen identities · EAS Drive Setup SHA-256 %s · "
            "EAS Tuner Settings SHA-256 %s" % (
                len(self._expert_bode_verification.sources),
                self._expert_bode_verification.sources[0].sha256,
                self._expert_bode_verification.sources[-2].sha256))
        self.expert_bode_verification_sources.setProperty("role", "hint")
        self.expert_bode_verification_sources.setWordWrap(True)
        bode_verification_layout.addWidget(
            self.expert_bode_verification_sources)
        self.expert_lab_stack.addWidget(
            self.expert_bode_verification_page)

        self.expert_time_verification_page = QtWidgets.QWidget()
        time_verification_layout = QtWidgets.QVBoxLayout(
            self.expert_time_verification_page)
        time_verification_layout.setContentsMargins(0, 0, 0, 0)
        time_verification_layout.setSpacing(7)
        self._expert_time_verification = (
            expert_time_verification_evidence.build_evidence_snapshot())
        self.expert_time_verification_banner = QtWidgets.QLabel(
            self._expert_time_verification.boundary)
        self.expert_time_verification_banner.setProperty("role", "hint")
        self.expert_time_verification_banner.setWordWrap(True)
        time_verification_layout.addWidget(
            self.expert_time_verification_banner)
        self.expert_time_verification_status = QtWidgets.QLabel()
        self.expert_time_verification_status.setProperty("role", "field")
        self.expert_time_verification_status.setWordWrap(True)
        time_verification_layout.addWidget(
            self.expert_time_verification_status)

        time_verification_selector_layout = QtWidgets.QHBoxLayout()
        time_verification_selector_label = QtWidgets.QLabel(
            "Documented EAS Verification–Time section")
        time_verification_selector_label.setProperty("role", "field")
        self.expert_time_verification_section = QtWidgets.QComboBox()
        self.expert_time_verification_section.setEditable(False)
        for section in self._expert_time_verification.sections:
            self.expert_time_verification_section.addItem(
                "%s · %s" % (section.label, section.reference),
                section.key)
        time_verification_selector_layout.addWidget(
            time_verification_selector_label)
        time_verification_selector_layout.addWidget(
            self.expert_time_verification_section, 1)
        time_verification_layout.addLayout(
            time_verification_selector_layout)

        self.expert_time_verification_table = QtWidgets.QTableWidget(0, 4)
        self.expert_time_verification_table.setObjectName(
            "expertEvidenceTable")
        self.expert_time_verification_table.setStyleSheet(
            "QTableWidget#expertEvidenceTable { font-size: 12px; } "
            "QTableWidget#expertEvidenceTable QHeaderView::section "
            "{ font-size: 12px; }")
        self.expert_time_verification_table.setHorizontalHeaderLabels((
            "CONTROL GROUP",
            "DOCUMENTED ROLE / REF",
            "UNIT / ACCESS",
            "STATUS / BOUNDARY",
        ))
        for column, tooltip in enumerate((
                "Documented EAS control group; not an executable control.",
                "Documented role and reference only; not a result.",
                "Documented unit/access; app remains inspect-only.",
                "Evidence status plus conflict, risk, or missing scope.",
        )):
            self.expert_time_verification_table.horizontalHeaderItem(
                column).setToolTip(tooltip)
        self.expert_time_verification_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.expert_time_verification_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.expert_time_verification_table.setFocusPolicy(
            QtCore.Qt.FocusPolicy.NoFocus)
        self.expert_time_verification_table.setWordWrap(True)
        self.expert_time_verification_table.setAlternatingRowColors(True)
        self.expert_time_verification_table.setMinimumWidth(0)
        self.expert_time_verification_table.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Expanding)
        self.expert_time_verification_table.verticalHeader().setVisible(False)
        time_verification_header = (
            self.expert_time_verification_table.horizontalHeader())
        for column in (0, 1, 2):
            time_verification_header.setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeMode.Fixed)
        time_verification_header.setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.expert_time_verification_table.setColumnWidth(0, 180)
        self.expert_time_verification_table.setColumnWidth(1, 280)
        self.expert_time_verification_table.setColumnWidth(2, 180)
        self.expert_time_verification_table.setMinimumHeight(250)
        time_verification_layout.addWidget(
            self.expert_time_verification_table, 1)

        self.expert_time_verification_conflicts = QtWidgets.QLabel(
            "DOCUMENT CONFLICTS · " + " | ".join(
                self._expert_time_verification.document_conflicts))
        self.expert_time_verification_warnings = QtWidgets.QLabel(
            "PERSISTENT WARNINGS · " + " | ".join(
                self._expert_time_verification.persistent_warnings))
        self.expert_time_verification_missing = QtWidgets.QLabel(
            "MISSING EVIDENCE / NEED-DATA · " + " | ".join(
                self._expert_time_verification.missing_evidence))
        for detail in (
                self.expert_time_verification_conflicts,
                self.expert_time_verification_warnings,
                self.expert_time_verification_missing):
            detail.setProperty("role", "hint")
            detail.setWordWrap(True)
            detail.setMinimumWidth(0)
            detail.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Preferred)
            time_verification_layout.addWidget(detail)
        self.expert_time_verification_sources = QtWidgets.QLabel(
            "SOURCES · %d frozen identities · EAS Drive Setup SHA-256 %s · "
            "Sine/Step image SHA-256 %s" % (
                len(self._expert_time_verification.sources),
                next(
                    source.sha256
                    for source in self._expert_time_verification.sources
                    if source.key == "drive_setup_html"),
                next(
                    source.sha256
                    for source in self._expert_time_verification.sources
                    if source.key == "sine_step_image")))
        self.expert_time_verification_sources.setProperty("role", "hint")
        self.expert_time_verification_sources.setWordWrap(True)
        time_verification_layout.addWidget(
            self.expert_time_verification_sources)
        self.expert_lab_stack.addWidget(
            self.expert_time_verification_page)

        self.expert_summary_page = QtWidgets.QWidget()
        summary_layout = QtWidgets.QVBoxLayout(self.expert_summary_page)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(7)
        self._expert_summary = (
            expert_summary_transaction_evidence.build_evidence_snapshot())
        self.expert_summary_banner = QtWidgets.QLabel(
            self._expert_summary.boundary)
        self.expert_summary_banner.setProperty("role", "hint")
        self.expert_summary_banner.setWordWrap(True)
        summary_layout.addWidget(self.expert_summary_banner)
        self.expert_summary_status = QtWidgets.QLabel()
        self.expert_summary_status.setProperty("role", "field")
        self.expert_summary_status.setWordWrap(True)
        summary_layout.addWidget(self.expert_summary_status)

        summary_selector_layout = QtWidgets.QHBoxLayout()
        summary_selector_label = QtWidgets.QLabel(
            "Documented EAS Summary section")
        summary_selector_label.setProperty("role", "field")
        self.expert_summary_section = QtWidgets.QComboBox()
        self.expert_summary_section.setEditable(False)
        for section in self._expert_summary.sections:
            self.expert_summary_section.addItem(
                "%s · %s" % (section.label, section.reference),
                section.key)
        summary_selector_layout.addWidget(summary_selector_label)
        summary_selector_layout.addWidget(self.expert_summary_section, 1)
        summary_layout.addLayout(summary_selector_layout)

        self.expert_summary_table = QtWidgets.QTableWidget(0, 4)
        self.expert_summary_table.setObjectName("expertEvidenceTable")
        self.expert_summary_table.setStyleSheet(
            "QTableWidget#expertEvidenceTable { font-size: 12px; } "
            "QTableWidget#expertEvidenceTable QHeaderView::section "
            "{ font-size: 12px; }")
        self.expert_summary_table.setHorizontalHeaderLabels((
            "CONTROL / GROUP",
            "ROLE / REF",
            "AUTHORITY / ACCESS",
            "STATUS / BOUNDARY",
        ))
        for column, tooltip in enumerate((
                "Documented Summary control or grouped authority; "
                "not executable.",
                "Installed-manual role/reference only; not a current result.",
                "Risk authority and inspect-only access; no authority is "
                "combined by this page.",
                "Evidence status plus condition or missing transaction scope.",
        )):
            self.expert_summary_table.horizontalHeaderItem(
                column).setToolTip(tooltip)
        self.expert_summary_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.expert_summary_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.expert_summary_table.setFocusPolicy(
            QtCore.Qt.FocusPolicy.NoFocus)
        self.expert_summary_table.setWordWrap(True)
        self.expert_summary_table.setAlternatingRowColors(True)
        self.expert_summary_table.setMinimumWidth(0)
        self.expert_summary_table.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Ignored,
            QtWidgets.QSizePolicy.Policy.Expanding)
        self.expert_summary_table.verticalHeader().setVisible(False)
        summary_header = self.expert_summary_table.horizontalHeader()
        for column in (0, 1, 2):
            summary_header.setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeMode.Fixed)
        summary_header.setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.expert_summary_table.setColumnWidth(0, 210)
        self.expert_summary_table.setColumnWidth(1, 180)
        self.expert_summary_table.setColumnWidth(2, 250)
        self.expert_summary_table.setMinimumHeight(220)
        summary_layout.addWidget(self.expert_summary_table, 1)

        self.expert_summary_ambiguities = QtWidgets.QLabel(
            "DOCUMENT AMBIGUITIES · " + " | ".join(
                self._expert_summary.document_ambiguities))
        self.expert_summary_warnings = QtWidgets.QLabel(
            "PERSISTENT WARNINGS · " + " | ".join(
                self._expert_summary.persistent_warnings))
        self.expert_summary_missing = QtWidgets.QLabel(
            "MISSING EVIDENCE / NEED-DATA · " + " | ".join(
                self._expert_summary.missing_evidence))
        for detail in (
                self.expert_summary_ambiguities,
                self.expert_summary_warnings,
                self.expert_summary_missing):
            detail.setProperty("role", "hint")
            detail.setWordWrap(True)
            detail.setMinimumWidth(0)
            detail.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Preferred)
            summary_layout.addWidget(detail)
        self.expert_summary_sources = QtWidgets.QLabel(
            "SOURCES · %d frozen identities · EAS Drive Setup SHA-256 %s · "
            "Summary before/after SHA-256 %s / %s" % (
                len(self._expert_summary.sources),
                next(
                    source.sha256
                    for source in self._expert_summary.sources
                    if source.key == "drive_setup_html"),
                next(
                    source.sha256
                    for source in self._expert_summary.sources
                    if source.key == "summary_before_image"),
                next(
                    source.sha256
                    for source in self._expert_summary.sources
                    if source.key == "summary_after_image")))
        self.expert_summary_sources.setProperty("role", "hint")
        self.expert_summary_sources.setWordWrap(True)
        summary_layout.addWidget(self.expert_summary_sources)
        self.expert_lab_stack.addWidget(self.expert_summary_page)

        self.expert_filter_type.currentIndexChanged.connect(
            self._refresh_expert_evidence_panel)
        self.expert_filter_location.currentIndexChanged.connect(
            self._refresh_expert_evidence_panel)
        self.expert_schedule_mode.valueChanged.connect(
            self._refresh_expert_evidence_panel)
        self.expert_limits_section.currentIndexChanged.connect(
            self._refresh_expert_limits_protections_panel)
        self.expert_application_section.currentIndexChanged.connect(
            self._refresh_expert_application_settings_panel)
        self.expert_bode_verification_section.currentIndexChanged.connect(
            self._refresh_expert_bode_verification_panel)
        self.expert_time_verification_section.currentIndexChanged.connect(
            self._refresh_expert_time_verification_panel)
        self.expert_summary_section.currentIndexChanged.connect(
            self._refresh_expert_summary_panel)
        self._refresh_expert_evidence_panel()
        self._refresh_expert_limits_protections_panel()
        self._refresh_expert_application_settings_panel()
        self._refresh_expert_bode_verification_panel()
        self._refresh_expert_time_verification_panel()
        self._refresh_expert_summary_panel()
        lab_layout.addWidget(self.expert_lab_stack)
        expert_layout.addWidget(self.expert_lab_frame)
        self._expert_plant = None
        self._expert_candidate = None
        self._expert_response = None
        self._expert_vp_plant = None
        self._expert_vp_candidate = None
        self._expert_current_inputs_stale = True
        self._expert_vp_inputs_stale = True
        self._expert_current_error = None
        self._expert_vp_error = None
        self._expert_page_status_snapshot = None
        self._expert_page_status_dirty = True
        self._expert_user_units_preview = None
        self._expert_user_units_inputs_stale = True
        self._expert_user_units_error = None
        for field in (
                self.expert_lab_r_ohm,
                self.expert_lab_l_uh,
                self.expert_lab_ts_us,
                self.expert_lab_bandwidth_hz):
            field.textEdited.connect(
                self._mark_expert_current_input_stale)
        self.expert_lab_ki_rule.currentIndexChanged.connect(
            self._mark_expert_current_input_stale)
        for field in (self.expert_vp_ka, self.expert_vp_b_visc):
            field.textEdited.connect(self._mark_expert_vp_input_stale)
        for field in tuple(self.expert_user_units_fc_fields.values()) + (
                self.expert_user_units_unit_label,
                self.expert_user_units_sample_counts):
            field.textEdited.connect(
                self._mark_expert_user_units_input_stale)
        self._refresh_expert_page_status()
        self._set_expert_lab_step("current")

        self.tuning_guided_run_frame = QtWidgets.QFrame()
        self.tuning_guided_run_frame.setObjectName("chip")
        guided_run_layout = QtWidgets.QVBoxLayout(
            self.tuning_guided_run_frame)
        guided_run_layout.setContentsMargins(12, 10, 12, 10)
        guided_run_layout.setSpacing(8)
        self.guided_run_title = QtWidgets.QLabel(
            "GUIDED HARDWARE TUNING CONTROLS · SUPERVISED · "
            "ENERGIZES / MOTION")
        # Preserve the existing handle while making the Quick/Expert shared
        # role explicit for callers and UI contracts.
        self.expert_hardware_title = self.guided_run_title
        self.guided_run_title.setProperty("role", "field")
        guided_run_layout.addWidget(self.guided_run_title)
        hardware_note = QtWidgets.QLabel(
            "This section is separate from the offline Candidate Lab. "
            "Its Run/Verify controls can energize or move hardware and remain "
            "subject to connection, authority, and field-safety gates.")
        hardware_note.setProperty("role", "hint")
        hardware_note.setWordWrap(True)
        guided_run_layout.addWidget(hardware_note)

        caprow = QtWidgets.QHBoxLayout(); caprow.setSpacing(8)
        cap_l = QtWidgets.QLabel("Phase 2 브레이크어웨이 전류 상한"); cap_l.setProperty("role", "field")
        self.cmb_ba_cap = QtWidgets.QComboBox()
        self.cmb_ba_cap.addItem("Standard · 0.20 × CL[1]", 0.2)
        self.cmb_ba_cap.addItem("Extended · 0.40 × CL[1] (별도 실기 승인 필요)", 0.4)
        self.cmb_ba_cap.setCurrentIndex(0)
        caprow.addWidget(cap_l); caprow.addWidget(self.cmb_ba_cap, 1)
        guided_run_layout.addLayout(caprow)
        cap_hint = QtWidgets.QLabel(
            "ⓘ 이 값은 지령값이 아니라 탐색을 중단할 최대 상한입니다. 선택만으로 모터가 통전되지 않습니다. "
            "Extended는 Standard보다 최대 전류가 2배이며, 실행할 때 별도의 현장 확인과 승인이 필요합니다.")
        cap_hint.setProperty("role", "hint"); cap_hint.setWordWrap(True)
        guided_run_layout.addWidget(cap_hint)
        # Keep measurement/motion actions separate from production-locked gain
        # mutation controls so the available authority remains visually explicit.
        btnrow = QtWidgets.QGridLayout()
        btnrow.setHorizontalSpacing(8)
        btnrow.setVerticalSpacing(8)
        self.btn_tune = QtWidgets.QPushButton("Run Phase 1 (Current)"); self.btn_tune.setEnabled(False)
        self.btn_tune.clicked.connect(self._run_autotune_clicked)
        self.btn_tune_signature = QtWidgets.QPushButton("Run Commutation Signature (≤1.30 A)")
        self.btn_tune_signature.setEnabled(False)
        self.btn_tune_signature.clicked.connect(self._run_signature_clicked)
        self.btn_tune_vp = QtWidgets.QPushButton("Run Phase 2 (Vel/Pos)"); self.btn_tune_vp.setEnabled(False)
        self.btn_tune_vp.clicked.connect(self._run_velpos_clicked)
        self.btn_tune_abort = QtWidgets.QPushButton("Abort"); self.btn_tune_abort.setEnabled(False)
        self.btn_tune_abort.clicked.connect(self._abort_autotune_clicked)
        self.btn_tune_verify = QtWidgets.QPushButton("Verify Installed P2 on Motor")
        self.btn_tune_verify.setEnabled(False)
        self.btn_tune_verify.clicked.connect(self._run_verify_clicked)
        for index, b in enumerate((
                self.btn_tune, self.btn_tune_signature, self.btn_tune_vp,
                self.btn_tune_verify, self.btn_tune_abort)):
            btnrow.addWidget(b, index // 2, index % 2)
        guided_run_layout.addLayout(btnrow)

        p1row = QtWidgets.QGridLayout()
        p1row.setHorizontalSpacing(8)
        p1row.setVerticalSpacing(6)
        p1label = QtWidgets.QLabel("P1 CURRENT GAINS"); p1label.setProperty("role", "field")
        self.btn_tune_apply = QtWidgets.QPushButton("Apply P1 → RAM (LOCKED)"); self.btn_tune_apply.setEnabled(False)
        self.btn_tune_apply.clicked.connect(self._apply_autotune_clicked)
        self.btn_tune_p1_restore = QtWidgets.QPushButton("Restore P1 → Original")
        self.btn_tune_p1_restore.setEnabled(False)
        self.btn_tune_p1_restore.clicked.connect(self._restore_current_clicked)
        self.btn_tune_p1_save = QtWidgets.QPushButton("Save P1 → SV (LOCKED)")
        self.btn_tune_p1_save.setEnabled(False)
        self.btn_tune_p1_save.clicked.connect(self._save_current_clicked)
        p1row.addWidget(p1label, 0, 0, 1, 2)
        for index, b in enumerate((
                self.btn_tune_apply, self.btn_tune_p1_restore,
                self.btn_tune_p1_save)):
            p1row.addWidget(b, 1 + index // 2, index % 2)
        expert_layout.addLayout(p1row)

        p2row = QtWidgets.QGridLayout()
        p2row.setHorizontalSpacing(8)
        p2row.setVerticalSpacing(6)
        p2label = QtWidgets.QLabel("P2 VELOCITY / POSITION GAINS"); p2label.setProperty("role", "field")
        self.btn_tune_vp_apply = QtWidgets.QPushButton("Apply P2 → RAM (LOCKED)"); self.btn_tune_vp_apply.setEnabled(False)
        self.btn_tune_vp_apply.clicked.connect(self._apply_velpos_clicked)
        self.btn_tune_vp_restore = QtWidgets.QPushButton("Restore P2 → Original")
        self.btn_tune_vp_restore.setEnabled(False)
        self.btn_tune_vp_restore.clicked.connect(self._restore_velpos_clicked)
        self.btn_tune_vp_save = QtWidgets.QPushButton("Save P2 → SV (LOCKED)")
        self.btn_tune_vp_save.setEnabled(False)
        self.btn_tune_vp_save.clicked.connect(self._save_velpos_clicked)
        p2row.addWidget(p2label, 0, 0, 1, 2)
        for index, b in enumerate((
                self.btn_tune_vp_apply, self.btn_tune_vp_restore,
                self.btn_tune_vp_save)):
            p2row.addWidget(b, 1 + index // 2, index % 2)
        gain_lock_reason = (
            "Hardware gain Apply/Save is locked until a durable "
            "pre-assignment RAM-trial WAL is implemented.")
        for b in (self.btn_tune_apply, self.btn_tune_p1_save,
                  self.btn_tune_vp_apply, self.btn_tune_vp_save):
            b.setToolTip(gain_lock_reason)
        expert_layout.addLayout(p2row)
        v.addWidget(self.tuning_expert_frame)
        v.addWidget(self.tuning_guided_run_frame)
        note = QtWidgets.QLabel("ⓘ 우리 자체 오토튠 — EAS 내부 알고리즘 재현이 아니라, 드라이브 명령으로 "
                                "R·L을 실측해 표준 PI 설계식으로 게인을 계산합니다. 시뮬 검증 완료(오라클 대비 KP/KI ≤1%), "
                                "실기 최초 실행은 통전·미세회전이 있으므로 감독 하에서만.")
        note.setProperty("role", "hint"); note.setWordWrap(True)
        v.addWidget(note); v.addStretch(1)
        # keep handles to the running results so Apply can reference them
        self._at_result = None
        self._at_result_generation = None
        self._p1_gain_trial = None
        self._p1_trial_generation = None
        self._vp_result = None
        self._vp_result_generation = None
        self._vp_signature_run = False
        self._vp_gain_trial = None
        self._vp_trial_generation = None
        self._vp_trial_verified_green = False
        self._vp_verified_trial = None
        self._vp_verified_generation = None
        self._tuning_authority_generation = 0
        self._tune_dispatch_inflight = None
        self._tune_dispatch_generation = None
        self._verify_trial_inflight = None
        for widget, operation_id in (
                (self.btn_tune, "tuning.p1.run"),
                (self.btn_tune_signature, "tuning.signature.run"),
                (self.btn_tune_vp, "tuning.p2.run"),
                (self.btn_tune_verify, "tuning.p2.verify"),
                (self.btn_tune_apply, "tuning.p1.apply"),
                (self.btn_tune_p1_restore, "tuning.p1.restore"),
                (self.btn_tune_p1_save, "tuning.p1.save"),
                (self.btn_tune_vp_apply, "tuning.p2.apply"),
                (self.btn_tune_vp_restore, "tuning.p2.restore"),
                (self.btn_tune_vp_save, "tuning.p2.save")):
            self._decorate_operation_control(widget, operation_id)
        self._decorate_operation_control(
            self.btn_expert_calculate, "tuning.expert.offline.calculate")
        self._decorate_operation_control(
            self.btn_expert_vp_calculate,
            "tuning.expert.offline.calculate_p2")
        for widget in (
                self.expert_filter_type,
                self.expert_filter_location):
            self._decorate_operation_control(
                widget, "tuning.expert.filter.evidence.inspect")
        self._decorate_operation_control(
            self.expert_schedule_mode,
            "tuning.expert.scheduling.evidence.inspect")
        self._decorate_operation_control(
            self.expert_limits_section,
            "tuning.expert.limits_protections.evidence.inspect")
        self._decorate_operation_control(
            self.expert_application_section,
            "tuning.expert.application_settings.evidence.inspect")
        self._decorate_operation_control(
            self.expert_bode_verification_section,
            "tuning.expert.bode_verification.evidence.inspect")
        self._decorate_operation_control(
            self.expert_time_verification_section,
            "tuning.expert.time_verification.evidence.inspect")
        self._decorate_operation_control(
            self.expert_summary_section,
            "tuning.expert.summary.evidence.inspect")
        self._set_tuning_mode("quick")
        return f

    def _set_tuning_mode(self, mode):
        if mode not in ("quick", "expert"):
            raise ValueError("unknown tuning UI mode %r" % mode)
        self._tuning_mode = mode
        expert = mode == "expert"
        self.btn_tuning_quick_mode.setChecked(not expert)
        self.btn_tuning_expert_mode.setChecked(expert)
        self.tuning_expert_frame.setVisible(expert)
        self.expert_lab_frame.setVisible(expert)
        if expert:
            self.tune_title.setText(
                "EXPERT TUNING  ·  Candidate review (gain Apply/Save locked)")
            self.tuning_mode_note.setText(
                "Expert mode does not bypass any gate. Hardware P1/P2 gain Apply and "
                "Save are locked until a durable pre-assignment RAM-trial WAL exists. "
                "Verify can still move the motor for the currently installed gains; "
                "retained recovery trials, if any, remain Restore-only.")
            self.lbl_tuning_mode_risk.setText("MOTION / GAIN APPLY LOCKED")
        else:
            self.tune_title.setText(
                "QUICK TUNING  ·  Guided identification + design")
            self.tuning_mode_note.setText(
                "Guided view measures and computes candidates only. Phase 1 energizes the "
                "motor; commutation and Phase 2 can rotate it. Hardware gain Apply/Save "
                "remain locked in every mode pending a durable pre-assignment trial WAL.")
            self.lbl_tuning_mode_risk.setText("ENERGIZES / MOTION")

    def _set_expert_lab_step(self, step):
        """Select one zero-I/O Expert model page without changing authority."""
        if step not in (
                "current", "vp", "evidence", "status", "user_units",
                "limits_protections", "application_settings",
                "bode_verification", "time_verification", "summary"):
            raise ValueError("unknown Expert Lab step %r" % step)
        if step == "evidence":
            self.expert_lab_title.setText(
                "EXPERT EVIDENCE LAB v0.1 · DOCUMENTED TOPOLOGY · "
                "NO MODEL · NO DRIVE I/O")
            self.expert_lab_note.setText(
                "Public-document topology inspector only: no model, transfer "
                "evaluation, controller selection, emulation, KV/KG/GS write, "
                "worker, command, or drive I/O. Unresolved document conflicts "
                "remain fail-closed as NEED-DATA.")
        elif step == "status":
            self.expert_lab_title.setText(
                "EXPERT PAGE STATUS v0.1 · LOCAL STATUS ONLY · NO DRIVE I/O")
            self.expert_lab_note.setText(
                "Classifies existing in-memory P1/P2/evidence state only: "
                "no calculation, installed-drive claim, EAS Enter/Apply "
                "state, worker, command, file, or drive I/O.")
        elif step == "user_units":
            self.expert_lab_title.setText(
                "EXPERT USER UNITS v0.1 · DOCUMENTED FORMULA · "
                "PARTIAL / SCREENING · NO DRIVE I/O")
            self.expert_lab_note.setText(
                "Uses explicit manual FC inputs only. The NetHelp formula "
                "and MAN-G-CR literal guards are displayed separately "
                "because their index groupings differ and the purpose "
                "remains NEED-DATA. No current-drive readback, automatic "
                "fill, FC/OF command, Apply, SV, or unit propagation.")
        elif step == "limits_protections":
            self.expert_lab_title.setText(
                "EXPERT LIMITS / PROTECTIONS v0.1 · "
                "DOCUMENTED PARAMETER MAP · PARTIAL / NEED-DATA")
            self.expert_lab_note.setText(
                "Immutable documentation catalog only: not current drive "
                "config, not active protection state, and not a safety "
                "assessment. No drive read, validation, recommendation, "
                "command generation, write, Apply/SV, motion, or unit "
                "propagation.")
        elif step == "application_settings":
            self.expert_lab_title.setText(
                "EXPERT APPLICATION SETTINGS v0.1 · "
                "DOCUMENTED APPLICATION SETTINGS MAP · PARTIAL / NEED-DATA")
            self.expert_lab_note.setText(
                "Immutable documentation catalog only: not current drive "
                "config, not current I/O state, and not brake or safety "
                "evidence. No drive read, validation/evaluation, command, "
                "write, Apply/Revert/SV, output actuation, motion, or drive "
                "I/O.")
        elif step == "bode_verification":
            self.expert_lab_title.setText(
                "EXPERT HIDDEN BODE VERIFICATION v0.1 · "
                "DOCUMENTED BODE VERIFICATION MAP · PARTIAL / NEED-DATA")
            self.expert_lab_note.setText(
                "Immutable static documentation map only. It is not an EAS "
                "verification result, current drive or EAS setting state, "
                "and not parity with the offline Bode MODEL. No drive read, "
                "acquisition, evaluation, Verify, EAS setting change, "
                "recording, command/write/Apply/Revert/SV, energization, "
                "motion, or drive I/O.")
        elif step == "time_verification":
            self.expert_lab_title.setText(
                "EXPERT VERIFICATION–TIME v0.1 · "
                "DOCUMENTED VERIFICATION-TIME MAP · PARTIAL / NEED-DATA")
            self.expert_lab_note.setText(
                "Static document map only; not EAS verification result, not "
                "current drive/EAS/recorder state, not measured response, "
                "not model/measurement parity, and not tuning pass. No "
                "drive read, no recorder configuration/acquisition, no "
                "Apply/Verify, no Enable/Disable, no current injection, no "
                "PTP/Jog/Sine/Step, no command/write/SV, no energization/"
                "motion, and no drive I/O. Documented UI Stop is not "
                "STO/E-stop.")
        elif step == "summary":
            self.expert_lab_title.setText(
                "EXPERT SUMMARY v0.1 · "
                "DOCUMENTED SUMMARY TRANSACTION MAP · PARTIAL / NEED-DATA")
            self.expert_lab_note.setText(
                "Static document map only; not current EAS Summary state, "
                "not current drive/file/motor database state, and not proof "
                "of saved data. No drive read/upload, no SV/Drive Save, no "
                "file dialog, no file/design export, no database import/"
                "mutation, no Save/Apply, no command generation, no "
                "energization/motion, and no drive I/O. The documented "
                "combined Save is split here into independent authorities.")
        else:
            self.expert_lab_title.setText(self._expert_model_title)
            self.expert_lab_note.setText(self._expert_model_note)
        current = step == "current"
        vp = step == "vp"
        self.btn_expert_step_current.setChecked(current)
        self.btn_expert_step_vp.setChecked(vp)
        self.btn_expert_step_evidence.setChecked(step == "evidence")
        self.btn_expert_step_status.setChecked(step == "status")
        self.btn_expert_step_user_units.setChecked(step == "user_units")
        self.btn_expert_step_limits.setChecked(
            step == "limits_protections")
        self.btn_expert_step_application.setChecked(
            step == "application_settings")
        self.btn_expert_step_bode_verification.setChecked(
            step == "bode_verification")
        self.btn_expert_step_time_verification.setChecked(
            step == "time_verification")
        self.btn_expert_step_summary.setChecked(step == "summary")
        self.expert_lab_stack.setCurrentIndex(
            {
                "current": 0,
                "vp": 1,
                "evidence": 2,
                "status": 3,
                "user_units": 4,
                "limits_protections": 5,
                "application_settings": 6,
                "bode_verification": 7,
                "time_verification": 8,
                "summary": 9,
            }[step])
        if step == "status":
            self._refresh_expert_page_status()

    def _refresh_expert_limits_protections_panel(self, *_args):
        """Render one immutable documented section without authority changes."""
        if not hasattr(self, "_expert_limits_protections"):
            return
        section = expert_limits_protections_evidence.section_evidence(
            self.expert_limits_section.currentData())
        self.expert_limits_status.setText(
            "AUTHORITY %s · MODEL STATUS %s · %s · %d documented rows · "
            "values intentionally absent" % (
                self._expert_limits_protections.authority,
                self._expert_limits_protections.model_status,
                section.reference,
                len(section.parameters)))
        self.expert_limits_table.setRowCount(len(section.parameters))
        for row, item in enumerate(section.parameters):
            values = (
                item.command,
                "%s · %s" % (item.label, item.documented_effect),
                "%s · document: %s · app: inspect-only" % (
                    item.documented_unit, item.access),
                "%s · %s" % (item.evidence_status, item.condition),
            )
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(value)
                cell.setToolTip(value)
                self.expert_limits_table.setItem(row, column, cell)
        self.expert_limits_table.resizeRowsToContents()

    def _refresh_expert_application_settings_panel(self, *_args):
        """Render one immutable application-settings documentation section."""
        if not hasattr(self, "_expert_application_settings"):
            return
        section = expert_application_settings_evidence.section_evidence(
            self.expert_application_section.currentData())
        self.expert_application_status.setText(
            "AUTHORITY %s · MODEL STATUS %s · %s · %d documented rows · "
            "NOT CURRENT / NOT READ BACK · live I/O unavailable / not sampled"
            % (
                self._expert_application_settings.authority,
                self._expert_application_settings.model_status,
                section.reference,
                len(section.parameters)))
        self.expert_application_table.setRowCount(len(section.parameters))
        for row, item in enumerate(section.parameters):
            values = (
                item.command,
                "%s · %s" % (item.label, item.documented_effect),
                "%s · %s" % (item.documented_unit, item.access),
                "%s · %s" % (item.evidence_status, item.condition),
            )
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(value)
                cell.setToolTip(value)
                self.expert_application_table.setItem(row, column, cell)
        self.expert_application_table.resizeRowsToContents()

    def _refresh_expert_bode_verification_panel(self, *_args):
        """Render one immutable hidden-Bode documentation section."""
        if not hasattr(self, "_expert_bode_verification"):
            return
        section = expert_bode_verification_evidence.section_evidence(
            self.expert_bode_verification_section.currentData())
        self.expert_bode_verification_status.setText(
            "AUTHORITY %s · EVIDENCE STATUS %s · %s · %d documented rows · "
            "NOT CURRENT / NOT SAMPLED · controls unavailable / not "
            "executable" % (
                self._expert_bode_verification.authority,
                self._expert_bode_verification.model_status,
                section.reference,
                len(section.parameters)))
        self.expert_bode_verification_table.setRowCount(
            len(section.parameters))
        for row, item in enumerate(section.parameters):
            values = (
                item.control,
                "%s · %s" % (item.label, item.documented_effect),
                "%s · %s" % (item.documented_unit, item.access),
                "%s · %s" % (item.evidence_status, item.condition),
            )
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(value)
                cell.setToolTip(value)
                self.expert_bode_verification_table.setItem(
                    row, column, cell)
        self.expert_bode_verification_table.resizeRowsToContents()

    def _refresh_expert_time_verification_panel(self, *_args):
        """Render one immutable Verification-Time documentation section."""
        if not hasattr(self, "_expert_time_verification"):
            return
        section = expert_time_verification_evidence.section_evidence(
            self.expert_time_verification_section.currentData())
        self.expert_time_verification_status.setText(
            "AUTHORITY %s · EVIDENCE STATUS %s · %s · "
            "%d documented control groups · NOT CURRENT / NOT SAMPLED · "
            "controls unavailable / not executable" % (
                self._expert_time_verification.authority,
                self._expert_time_verification.model_status,
                section.reference,
                len(section.parameters)))
        self.expert_time_verification_table.setRowCount(
            len(section.parameters))
        for row, item in enumerate(section.parameters):
            values = (
                item.display_group,
                "%s · %s" % (item.label, item.documented_effect),
                "%s · %s" % (item.documented_unit, item.access),
                "%s · %s" % (item.evidence_status, item.condition),
            )
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(value)
                cell.setToolTip(value)
                self.expert_time_verification_table.setItem(
                    row, column, cell)
        self.expert_time_verification_table.resizeRowsToContents()

    def _refresh_expert_summary_panel(self, *_args):
        """Render one immutable Summary transaction documentation section."""
        if not hasattr(self, "_expert_summary"):
            return
        section = expert_summary_transaction_evidence.section_evidence(
            self.expert_summary_section.currentData())
        self.expert_summary_status.setText(
            "AUTHORITY %s · EVIDENCE STATUS %s · %s · "
            "%d documented groups · NOT CURRENT / NOT EXECUTED · "
            "controls unavailable / not executable" % (
                self._expert_summary.authority,
                self._expert_summary.model_status,
                section.reference,
                len(section.items)))
        self.expert_summary_table.setRowCount(len(section.items))
        for row, item in enumerate(section.items):
            values = (
                item.display_group,
                "%s · %s" % (item.control, item.documented_effect),
                "%s · %s" % (item.risk_class, item.access),
                "%s · %s" % (item.evidence_status, item.condition),
            )
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(value)
                cell.setToolTip(value)
                self.expert_summary_table.setItem(row, column, cell)
        self.expert_summary_table.resizeRowsToContents()

    def _refresh_expert_evidence_panel(self, *_args):
        """Render only immutable public-document topology and blockers."""
        if not hasattr(self, "_expert_evidence"):
            return
        filter_code = self.expert_filter_type.currentData()
        location_key = self.expert_filter_location.currentData()
        gs2_value = self.expert_schedule_mode.value()
        filter_type = (
            expert_filter_scheduling_evidence.filter_type_evidence(
                filter_code))
        location = (
            expert_filter_scheduling_evidence.filter_location_evidence(
                location_key))
        schedule = (
            expert_filter_scheduling_evidence.classify_gs2_mode(gs2_value))

        parameters = (
            "none" if not filter_type.parameters
            else " · ".join(filter_type.parameters))
        self.expert_filter_type_detail.setText(
            "FILTER TYPE %d · %s · parameters: %s · "
            "EXACT TRANSFER %s" % (
                filter_type.code,
                filter_type.name,
                parameters,
                filter_type.exact_transfer_status))

        kv_text = (
            "none selected" if not location.kv_indices
            else ",".join("KV[%d]" % index
                         for index in location.kv_indices))
        type_text = " / ".join(
            "KV[%d]" % index
            for index in location.type_index_candidates)
        kg_text = (
            "none" if not location.kg_index_ranges
            else " · ".join(
                "KG[%d..%d]" % bounds
                for bounds in location.kg_index_ranges))
        gs_text = (
            "none" if location.gs_index is None
            else "GS[%d]" % location.gs_index)
        self.expert_filter_location_detail.setText(
            "%s · %s · KV slots: %s · type index candidate(s): %s · "
            "schedule: %s · table: %s%s" % (
                location.status.replace("_", " "),
                location.label,
                kv_text,
                type_text,
                gs_text,
                kg_text,
                (" · " + location.detail) if location.detail else ""))

        dependencies = (
            "none" if not schedule.dependencies
            else " · ".join(schedule.dependencies))
        self.expert_schedule_mode_detail.setText(
            "GS[2]=%d · %s · %s · dependencies: %s · "
            "SELECTION / INTERPOLATION %s" % (
                gs2_value,
                schedule.category,
                schedule.description,
                dependencies,
                schedule.selection_algorithm_status))
        self.expert_evidence_documented_facts.setText(
            "DOCUMENTED FACTS · DC GAIN = one at zero frequency · "
            "the fifth parameter selects/enables a non-scheduled filter · "
            "MOTOR OFF required to change KV filter type · inspector never "
            "issues that change")
        self.expert_evidence_conflicts.setText(
            "DOCUMENT CONFLICTS · " + " · ".join(
                self._expert_evidence.conflicts))
        self.expert_evidence_missing.setText(
            "MISSING / NEED-DATA · " + " · ".join(
                self._expert_evidence.missing_evidence))

    def _refresh_expert_page_status(self, *_args):
        """Project existing local Expert state without creating authority."""
        if not hasattr(self, "expert_page_status_rows"):
            return
        if (self.expert_lab_stack.currentWidget()
                is not self.expert_page_status_page):
            self._expert_page_status_dirty = True
            return
        try:
            snapshot = expert_page_status.build_page_status_snapshot(
                current_plant=getattr(self, "_expert_plant", None),
                current_candidate=getattr(self, "_expert_candidate", None),
                current_stale=getattr(
                    self, "_expert_current_inputs_stale", True),
                current_error=getattr(self, "_expert_current_error", None),
                vp_plant=getattr(self, "_expert_vp_plant", None),
                vp_candidate=getattr(self, "_expert_vp_candidate", None),
                vp_stale=getattr(self, "_expert_vp_inputs_stale", True),
                vp_error=getattr(self, "_expert_vp_error", None),
                filter_evidence=getattr(self, "_expert_evidence", None),
            )
        except (TypeError, ValueError, OverflowError) as exc:
            self._expert_page_status_snapshot = None
            self._expert_page_status_dirty = False
            self.expert_page_status_overall.setText(
                "OVERALL INVALID · local state classification failed · "
                "NOT EAS COMPLETE")
            detail = (
                "INVALID · local state classification failed · %s · "
                "no authority granted" % exc)
            for label in self.expert_page_status_rows.values():
                label.setText(detail)
            return

        self._expert_page_status_snapshot = snapshot
        self._expert_page_status_dirty = False
        self.expert_page_status_overall.setText(
            "OVERALL PARTIAL · LOCAL STATUS ONLY · filter/scheduling "
            "NEED-DATA · NOT EAS COMPLETE")
        for page in snapshot.pages:
            self.expert_page_status_rows[page.key].setText(
                "%s · %s" % (
                    page.state.replace("_", " "),
                    page.detail,
                ))

    @staticmethod
    def _format_expert_user_units_fraction(value):
        if value.denominator == 1:
            return str(value.numerator)
        return "%d / %d" % (value.numerator, value.denominator)

    def _calculate_expert_user_units_preview(self):
        """Evaluate one documented formula without reading or writing a drive."""
        def parse_integer(field, label, *, optional=False):
            text = field.text().strip()
            if not text:
                if optional:
                    return None
                raise ValueError("%s is required" % label)
            if re.fullmatch(r"[+-]?\d+", text) is None:
                raise ValueError("%s must be an explicit integer" % label)
            return int(text, 10)

        try:
            preview = expert_user_units.build_position_scale_preview(
                fc1=parse_integer(
                    self.expert_user_units_fc_fields["fc1"], "FC[1]"),
                fc2=parse_integer(
                    self.expert_user_units_fc_fields["fc2"], "FC[2]"),
                fc5=parse_integer(
                    self.expert_user_units_fc_fields["fc5"], "FC[5]"),
                fc6=parse_integer(
                    self.expert_user_units_fc_fields["fc6"], "FC[6]"),
                fc7=parse_integer(
                    self.expert_user_units_fc_fields["fc7"], "FC[7]"),
                fc8=parse_integer(
                    self.expert_user_units_fc_fields["fc8"], "FC[8]"),
                unit_label=self.expert_user_units_unit_label.text(),
                sample_counts=parse_integer(
                    self.expert_user_units_sample_counts,
                    "sample counts",
                    optional=True),
            )
        except (TypeError, ValueError, OverflowError) as exc:
            self._expert_user_units_inputs_stale = True
            self._expert_user_units_error = str(exc)
            retained = (
                " · previous preview retained as historical only"
                if self._expert_user_units_preview is not None
                else " · no preview created")
            self.expert_user_units_status.setText(
                "INVALID · %s%s · PARTIAL / SCREENING · "
                "NOT CURRENT DRIVE CONFIG" % (exc, retained))
            return

        exact_units_per_count = (
            self._format_expert_user_units_fraction(
                preview.units_per_count))
        exact_counts_per_unit = (
            self._format_expert_user_units_fraction(
                preview.counts_per_unit))
        self.expert_user_units_result_fields[
            "units_per_count"].setText(
                "%s = %s %s/count" % (
                    exact_units_per_count,
                    preview.units_per_count_decimal,
                    preview.unit_label))
        self.expert_user_units_result_fields[
            "counts_per_unit"].setText(
                "%s = %s count/%s" % (
                    exact_counts_per_unit,
                    preview.counts_per_unit_decimal,
                    preview.unit_label))
        if preview.sample_units is None:
            sample_text = "— · sample counts not supplied"
        else:
            sample_text = "%d count = %s = %s %s" % (
                preview.sample_counts,
                self._format_expert_user_units_fraction(
                    preview.sample_units),
                preview.sample_units_decimal,
                preview.unit_label)
        self.expert_user_units_result_fields["sample_units"].setText(
            sample_text)
        self._expert_user_units_preview = preview
        self._expert_user_units_inputs_stale = False
        self._expert_user_units_error = None
        self.expert_user_units_status.setText(
            "DOCUMENTED LOCAL PREVIEW · PARTIAL / SCREENING · "
            "DOCUMENTED GROUPING MISMATCH · PURPOSE NEED-DATA · "
            "NOT CURRENT DRIVE CONFIG · NO FC/OF WRITE · NO DRIVE I/O")

    def _mark_expert_user_units_input_stale(self, *_args):
        """Retain historical output while revoking current-input coherence."""
        self._expert_user_units_inputs_stale = True
        self._expert_user_units_error = None
        if self._expert_user_units_preview is None:
            self.expert_user_units_status.setText(
                "PARTIAL / SCREENING · waiting for complete explicit manual "
                "inputs · DOCUMENTED GROUPING MISMATCH · "
                "PURPOSE NEED-DATA")
            return
        self.expert_user_units_status.setText(
            "STALE · explicit manual inputs changed · previous documented "
            "preview retained as historical only · PARTIAL / SCREENING · "
            "NOT CURRENT DRIVE CONFIG")

    def _mark_expert_current_input_stale(self, *_args):
        """Prevent a prior P1 PASS from appearing bound to edited inputs."""
        self._expert_current_error = None
        if getattr(self, "_expert_candidate", None) is None:
            self._refresh_expert_page_status()
            return
        self._expert_current_inputs_stale = True
        self.expert_lab_status.setText(
            "STALE · Current inputs changed · previous P1 MODEL retained "
            "as historical evidence · recalculate before P2")
        self._reset_expert_vp_candidate(
            "STALE · Current inputs changed · calculate Current, then P2")

    def _mark_expert_vp_input_stale(self, *_args):
        """Keep prior immutable evidence but revoke its visible PASS status."""
        self._expert_vp_error = None
        if getattr(self, "_expert_vp_candidate", None) is None:
            self._refresh_expert_page_status()
            return
        self._expert_vp_inputs_stale = True
        self.expert_vp_status.setText(
            "STALE · K_a/B inputs changed · previous P2 MODEL retained "
            "as historical evidence · recalculation required")
        self._refresh_expert_page_status()

    def _reset_expert_vp_candidate(self, reason):
        """Invalidate only the dependent offline P2 projection."""
        self._expert_vp_plant = None
        self._expert_vp_candidate = None
        self._expert_vp_inputs_stale = True
        self._expert_vp_error = None
        for field in self.expert_vp_result_fields.values():
            field.setText("—")
        for key in (
                "k_a", "b_visc", "i_c", "kp_vel", "ki_vel", "kp_pos",
                "pm_vel", "pm_pos"):
            self.tune_gain_fields[key].setText("—")
        self.expert_vp_status.setText(str(reason))
        self._refresh_expert_page_status()

    def _show_tuning_mode(self, mode):
        self._nav_to(3)
        if (mode == "quick" and (
                getattr(self, "_p1_gain_trial", None) is not None
                or getattr(self, "_vp_gain_trial", None) is not None
                or getattr(self, "_motor_write_inflight", False))):
            self._set_tuning_mode("expert")
            self._flash(
                "활성 RAM trial/저장 작업이 있어 Expert 복원·검증 제어를 숨기지 않습니다.")
            return
        self._set_tuning_mode(mode)

    def _calculate_expert_candidate(self):
        """Compute and display a pure offline P1 candidate atomically.

        Every parse, design, and response step completes before any candidate
        field is changed.  Therefore invalid input cannot partially overwrite
        the last complete MODEL result.
        """
        try:
            resistance_ohm = float(self.expert_lab_r_ohm.text().strip())
            inductance_h = (
                float(self.expert_lab_l_uh.text().strip()) * 1e-6)
            sampling_time_s = (
                float(self.expert_lab_ts_us.text().strip()) * 1e-6)
            bandwidth_text = self.expert_lab_bandwidth_hz.text().strip()
            target_bandwidth_hz = (
                float(bandwidth_text) if bandwidth_text else None)
            ki_rule = self.expert_lab_ki_rule.currentData()
            plant = expert_tuning_offline.CurrentPlant(
                resistance_ohm=resistance_ohm,
                inductance_h=inductance_h,
                sampling_time_s=sampling_time_s,
            )
            candidate = expert_tuning_offline.design_current_candidate(
                plant,
                target_bandwidth_hz=target_bandwidth_hz,
                ki_rule=ki_rule,
            )
            response = expert_tuning_offline.current_frequency_response(
                plant, candidate)
        except (TypeError, ValueError, OverflowError) as exc:
            self._expert_current_error = "INVALID_INPUT · %s" % exc
            self.expert_lab_status.setText(
                "INVALID · previous candidate preserved · %s" % exc)
            self._refresh_expert_page_status()
            return

        self._expert_plant = plant
        self._expert_candidate = candidate
        self._expert_response = response
        self._expert_current_inputs_stale = False
        self._expert_current_error = None
        self._reset_expert_vp_candidate(
            "MODEL · calculate after Current candidate · no P2 candidate")
        candidate_fields = self.tune_gain_fields
        candidate_fields["r_pp"].setText(
            "%.6g ohm" % resistance_ohm)
        candidate_fields["l_pp"].setText(
            "%.6g uH" % (inductance_h * 1e6))
        candidate_fields["kp_cur"].setText(
            "%.6g V/A" % candidate.kp_v_per_a)
        candidate_fields["ki_cur"].setText(
            "%.6g Hz" % candidate.ki_hz)
        candidate_fields["pm"].setText(
            "%.1f deg" % candidate.phase_margin_deg)
        design_gate = "PASS" if candidate.design_passed else "FAIL"
        self.expert_lab_status.setText(
            "%s · crossover %.6g Hz · PM %.2f deg · basis %s · "
            "design gate %s · %s"
            % (
                candidate.model_status,
                candidate.crossover_hz,
                candidate.phase_margin_deg,
                candidate.basis,
                design_gate,
                candidate.source,
            ))
        self.expert_lab_response_summary.setText(
            "Bode-ready response · %d points · %.6g..%.6g Hz · "
            "open/closed magnitude + open-loop phase"
            % (
                len(response.frequency_hz),
                response.frequency_hz[0],
                response.frequency_hz[-1],
            ))
        self.expert_bode_widget.set_response(response)
        self._refresh_expert_page_status()

    def _calculate_expert_vp_candidate(self):
        """Project a pure offline P2 candidate from the complete P1 MODEL.

        Parsing and design finish before any P2 field is changed.  Invalid
        inputs therefore preserve the previous complete projection and cannot
        create a worker, command, installed-gain claim, or motion authority.
        """
        try:
            if (not isinstance(self._expert_plant,
                               expert_tuning_offline.CurrentPlant)
                    or not isinstance(
                        self._expert_candidate,
                        expert_tuning_offline.CurrentCandidate)):
                raise ValueError(
                    "complete passing Current MODEL candidate required")
            if self._expert_current_inputs_stale:
                raise ValueError(
                    "Current inputs changed; recalculate Current MODEL first")
            k_a = float(self.expert_vp_ka.text().strip())
            b_visc = float(self.expert_vp_b_visc.text().strip())
            plant = expert_tuning_offline.VelocityPositionPlant(
                current_plant=self._expert_plant,
                current_candidate=self._expert_candidate,
                accel_constant_cnt_per_s2_per_a_peak=k_a,
                viscous_friction_a_peak_per_cnt_s=b_visc,
            )
            candidate = (
                expert_tuning_offline.design_velocity_position_candidate(
                    plant))
        except (TypeError, ValueError, OverflowError) as exc:
            self._expert_vp_error = "INVALID_INPUT · %s" % exc
            self.expert_vp_status.setText(
                "INVALID · previous P2 candidate preserved · %s" % exc)
            self._refresh_expert_page_status()
            return

        gain_margin = (
            "%.2f dB" % candidate.velocity_gain_margin_db
            if candidate.velocity_gain_margin_db is not None
            else "not crossed on bounded grid")
        gate = "PASS" if candidate.loop_model_passed else "FAIL"
        self._expert_vp_plant = plant
        self._expert_vp_candidate = candidate
        self._expert_vp_inputs_stale = False
        self._expert_vp_error = None
        results = self.expert_vp_result_fields
        results["kp_vel"].setText(
            "%.7g A_peak/(cnt/s)" % candidate.kp_vel_a_per_cnt_s)
        results["ki_vel"].setText(
            "%.7g Hz" % candidate.ki_vel_hz)
        results["kp_pos"].setText(
            "%.7g rad/s · count-domain MODEL %.7g 1/s"
            % (candidate.kp_pos_per_s, candidate.kp_pos_per_s))
        results["pm_vel"].setText(
            "%.2f deg · GM %s · fc %.3f Hz"
            % (
                candidate.velocity_phase_margin_deg,
                gain_margin,
                candidate.velocity_crossover_hz,
            ))
        results["pm_pos"].setText(
            "%.2f deg · fc %.3f Hz"
            % (
                candidate.position_phase_margin_deg,
                candidate.position_crossover_hz,
            ))

        fields = self.tune_gain_fields
        fields["k_a"].setText(
            "%.7g cnt/s²/A_peak"
            % plant.accel_constant_cnt_per_s2_per_a_peak)
        fields["b_visc"].setText(
            "%.7g A_peak/(cnt/s)"
            % plant.viscous_friction_a_peak_per_cnt_s)
        fields["i_c"].setText(
            "— · excluded from linear P2 MODEL")
        fields["kp_vel"].setText(results["kp_vel"].text())
        fields["ki_vel"].setText(results["ki_vel"].text())
        fields["kp_pos"].setText(results["kp_pos"].text())
        fields["pm_vel"].setText(results["pm_vel"].text())
        fields["pm_pos"].setText(results["pm_pos"].text())
        self.expert_vp_status.setText(
            "MODEL GATE %s · SINGLE-POINT CALIBRATION · "
            "GS[2]=0 ONLY · FILTER NEED-DATA · D=%.7g 1/s · "
            "design bandwidth %.3f rad/s · reductions %d · "
            "no drive / worker / command I/O"
            % (
                gate,
                candidate.d_visc_per_s,
                candidate.design_bandwidth_rad_s,
                candidate.reductions,
            ))
        self._refresh_expert_page_status()

    # ---- auto-tune GUI glue ----------------------------------------------------------
    def _claim_tune_dispatch(self, kind, trial=None):
        """Synchronously lock run buttons before a worker start signal can race."""
        if getattr(self, "_motor_write_inflight", False):
            self._flash("Motor profile durable transaction 중에는 튜닝을 시작할 수 없습니다.")
            return False
        active = getattr(self, "_tune_dispatch_inflight", None)
        if active is not None:
            self._flash("이미 %s 작업을 전송해 시작/결과를 기다리는 중입니다." % active)
            return False
        self._tune_dispatch_inflight = str(kind)
        self._tune_dispatch_generation = getattr(
            self, "_tuning_authority_generation", 0)
        self._verify_trial_inflight = trial if kind == "verify" else None
        for name in ("btn_tune", "btn_tune_signature", "btn_tune_vp",
                     "btn_tune_verify"):
            if hasattr(self, name):
                getattr(self, name).setEnabled(False)
        if hasattr(self, "btn_motor_write"):
            self.btn_motor_write.setEnabled(False)
        return True

    def _release_tune_dispatch(self, *expected):
        active = getattr(self, "_tune_dispatch_inflight", None)
        if not expected or active in expected:
            self._tune_dispatch_inflight = None
            self._tune_dispatch_generation = None
            self._verify_trial_inflight = None

    def _tune_signal_is_current(self, *expected_kinds):
        """Accept a tuning signal only for this worker/profile generation.

        Direct calls (``sender() is None``) remain available to deterministic
        offline smoke tests.  Real Qt worker signals require exact sender,
        in-flight operation kind, and monotonically bound generation.
        """
        sender = getattr(self, "sender", None)
        source = sender() if callable(sender) else None
        if source is not None and source is not self.worker:
            return False
        if getattr(self, "_motor_write_inflight", False):
            return False
        if source is None:
            return True
        active = getattr(self, "_tune_dispatch_inflight", None)
        return bool(
            active in expected_kinds
            and getattr(self, "_tune_dispatch_generation", None) ==
            getattr(self, "_tuning_authority_generation", 0))

    def _gain_action_signal_is_current(self, phase, action, trial):
        """Generation gate for RAM-trial begin/restore/commit results."""
        sender = getattr(self, "sender", None)
        source = sender() if callable(sender) else None
        if source is not None and source is not self.worker:
            return False
        if getattr(self, "_motor_write_inflight", False):
            return False
        if source is None:
            return True
        expected = "%s_%s" % (phase.lower(), action)
        if MainWindow._tune_signal_is_current(self, expected):
            return True
        # Worker shutdown may automatically restore the exact active trial
        # without a GUI dispatch.  It is accepted only before a generation
        # boundary and can never grant Save/Apply authority.
        if action == "restore":
            attr = "_p1_gain_trial" if phase == "P1" else "_vp_gain_trial"
            gen_attr = ("_p1_trial_generation" if phase == "P1"
                        else "_vp_trial_generation")
            return bool(
                trial is not None and trial is getattr(self, attr, None)
                and getattr(self, gen_attr, None) ==
                getattr(self, "_tuning_authority_generation", 0))
        return False

    def _set_tune_stage(self, active_idx, done_upto=-1):
        """Repaint the stage list: ● done, ◆ active, ○ pending.
        Stages 0..2 = Phase 1 (current), 3..5 = Phase 2 (vel/pos)."""
        for i, lbl in enumerate(self.tune_stage_lbls):
            base = self._AT_STAGES[i]
            if i <= done_upto:
                mark, col = "●", theme.OK if hasattr(theme, "OK") else "#28c840"
            elif i == active_idx:
                mark, col = "◆", theme.C_AMBER
            else:
                mark, col = "○", theme.TEXT
            lbl.setText("%s  %s" % (mark, base))
            lbl.setStyleSheet("color:%s;" % col)

    def _run_autotune_clicked(self):
        if getattr(self, "_motor_write_inflight", False):
            self._flash("Motor profile 저장 중에는 Phase 1을 시작할 수 없습니다.")
            return
        if getattr(self, "_tune_dispatch_inflight", None) is not None:
            self._flash("이전 튜닝/검증 전송의 시작 또는 결과를 기다리는 중입니다.")
            return
        if self._guard_unsaved_vp_trial("Phase 1을 실행"):
            return
        if not (self.worker and self.worker.isRunning()):
            self._flash("연결 후 사용하세요."); return
        btn = QtWidgets.QMessageBox.warning(
            self, "자동튜닝 실행 확인 (통전 주의)",
            "지금부터 드라이브가 모터를 통전(MO=1)하고 전류를 주입해 R·L을 실측합니다.\n\n"
            "• 커뮤테이션 정렬로 축이 최대 ±11.25° 순간 회전할 수 있습니다.\n"
            "• 모터가 기계적으로 자유롭거나 안전하게 고정돼 있어야 합니다.\n"
            "• 전류는 CL[1] 이내로 제한되며, 언제든 Abort로 안전 중단(MO=0)됩니다.\n"
            "• 이상 시 자동으로 원래 상태(게인·설정)로 복원합니다.\n\n"
            "실행할까요?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if not self._claim_tune_dispatch("p1"):
            return
        # reset display
        self._at_result = None
        for k in self.tune_gain_fields:
            self.tune_gain_fields[k].setText("—")
        self.btn_tune_apply.setEnabled(False)
        self.worker.start_autotune({})            # defaults; drive already has KP[1]>0 (no bootstrap)

    def _abort_autotune_clicked(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel_autotune()
            self._flash("Abort 요청 — 안전 중단 중(MO=0)…")
            self.tune_status.setText("⏹ Abort 요청됨 — 드라이브를 안전 상태로 되돌리는 중…")

    def _apply_autotune_clicked(self):
        if not PRODUCTION_GAIN_TRIALS_ENABLED:
            self._flash(
                "P1 Apply locked: durable pre-assignment RAM-trial WAL is not "
                "available for hardware links.")
            return
        if getattr(self, "_motor_write_inflight", False):
            self._flash("Motor profile 저장 중에는 P1 게인을 적용할 수 없습니다.")
            return
        if getattr(self, "_p1_gain_trial", None) is not None:
            self._flash("이미 P1 RAM 임시 게인이 적용되어 있습니다.")
            return
        if self._guard_unsaved_vp_trial("P1 게인을 RAM에 적용"):
            return
        r = self._at_result
        if (r is None
                or getattr(self, "_at_result_generation", None) !=
                getattr(self, "_tuning_authority_generation", 0)
                or r.status not in (autotune_current.GREEN, autotune_current.YELLOW)):
            self._flash("적용할 유효한 결과가 없습니다."); return
        btn = QtWidgets.QMessageBox.question(
            self, "P1 synthetic/retained RAM trial 확인",
            "개발 회귀/retained recovery 전용 경로입니다. Production hardware entry는 잠겨 있습니다.\n"
            "산출된 전류루프 게인을 RAM에만 적용합니다 (모터 OFF에서만).\n"
            "적용 전에 원래 KP[1]/KI[1]을 저장하고, 이 단계에서는 SV를 실행하지 않습니다.\n\n"
            "• KP[1] = %.6g V/A\n• KI[1] = %.6g Hz\n"
            "• 적용 후 Restore P1만 가능 (Save P1 → SV는 검증 capability 미구현으로 잠김)"
            "\n\nRAM 임시 적용을 진행할까요?"
            % (r.kp_v_per_a, r.ki_hz),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if self.worker and self.worker.isRunning():
            if not self._claim_tune_dispatch("p1_begin"):
                return
            self.btn_tune_apply.setEnabled(False)
            self.worker.begin_current_gain_trial(r)
            self._flash("P1 게인 RAM 임시 적용 중… (SV 없음)")

    def _restore_current_clicked(self):
        trial = getattr(self, "_p1_gain_trial", None)
        if trial is None:
            self._flash("복원할 P1 RAM 게인 시험이 없습니다.")
            return
        if getattr(trial, "persistence_state", "RAM_TRIAL") not in (
                "RAM_TRIAL", "RESTORE_FAILED", "AUTHORITY_INVALID"):
            self._flash("현재 P1 상태에서는 Restore를 실행할 수 없습니다.")
            return
        if not (self.worker and self.worker.isRunning()):
            self._flash("복원하려면 드라이브를 다시 연결하세요.")
            return
        if not self._claim_tune_dispatch("p1_restore"):
            return
        self.btn_tune_p1_restore.setEnabled(False)
        self.btn_tune_p1_save.setEnabled(False)
        self.worker.restore_current_gain_trial(trial)
        self._flash("원래 P1 게인 복원 및 되읽기 확인 중…")

    def _save_current_clicked(self):
        trial = getattr(self, "_p1_gain_trial", None)
        if (trial is not None
                and not autotune_current.p1_gain_trial_has_save_authority(
                    trial)):
            self._flash(
                "P1 Save locked: session-bound on-motor verification "
                "capability is unavailable while E4 remains RED")
            return
        if trial is None:
            self._flash("저장할 P1 RAM 게인 시험이 없습니다.")
            return
        if (getattr(trial, "persistence_state", "RAM_TRIAL") != "RAM_TRIAL"
                or getattr(trial, "restore_only", False)):
            self._flash("현재 P1 시험은 Save 권한이 없습니다(restore-only/terminal 상태).")
            return
        if not (self.worker and self.worker.isRunning()):
            self._flash("드라이브를 다시 연결하고 RAM 상태를 확인하세요.")
            return
        if (getattr(self, "_p1_trial_generation", None) !=
                getattr(self, "_tuning_authority_generation", 0)):
            self._flash("이 P1 시험은 이전 연결 세대입니다 — Restore만 허용됩니다.")
            return
        btn = QtWidgets.QMessageBox.question(
            self, "P1 legacy/offline 저장 경로 확인",
            "Production에서는 도달할 수 없는 legacy/offline 경로입니다. RAM의 KP[1]/KI[1]을 "
            "최종 되읽기하고 임시 적용값과 모두 일치할 때만 SV를 검사합니다.\n\n계속할까요?",
            QtWidgets.QMessageBox.StandardButton.Yes |
            QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if not self._claim_tune_dispatch("p1_commit"):
            return
        self.btn_tune_p1_save.setEnabled(False)
        self.worker.commit_current_gain_trial(trial)
        self._flash("P1 게인 최종 되읽기 후 SV 저장 중…")

    def _on_autotune_started(self):
        if not self._tune_signal_is_current("p1"):
            return
        self._mark_energizing_ui("Phase 1 tuning is running")
        self.btn_tune.setEnabled(False); self.btn_tune_signature.setEnabled(False)
        self.btn_tune_abort.setEnabled(True)
        self.btn_tune_apply.setEnabled(False)
        self._set_tune_stage(0)
        self.tune_status.setText("▶ 튜닝 시작 — 초기화/검증 중…")

    def _on_autotune_progress(self, code, detail):
        if not self._tune_signal_is_current("p1"):
            return
        stage = self._AT_CODE_STAGE.get(code, 0)
        done = stage - 1 if code != "DONE" else self._AT_PHASE1_LAST
        self._set_tune_stage(stage if code != "DONE" else -1, done_upto=done)
        self.tune_status.setText("◆ [%s] %s" % (code, detail))

    def _dump_autotune_result(self, res):
        """Persist the full result (fields + evidence) to .omc/state so the exact
        measured numbers can be read off disk for oracle comparison (no transcription)."""
        try:
            import json as _json, dataclasses as _dc, time as _time
            d = os.path.join(".omc", "state")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, "autotune_result_%d.json" % int(_time.time() * 1000))
            with open(path, "w", encoding="utf-8") as fh:
                _json.dump(_dc.asdict(res), fh, ensure_ascii=False, indent=1, default=str)
            return path
        except Exception:
            return None

    def _on_autotune_result(self, res):
        if not self._tune_signal_is_current("p1"):
            return
        self._release_tune_dispatch("p1")
        self.btn_tune_abort.setEnabled(False)
        on = bool(getattr(self, "_ui_connected", False) and
                  (self.worker is None or self.worker.isRunning()))
        trial_active = (getattr(self, "_p1_gain_trial", None) is not None or
                        getattr(self, "_vp_gain_trial", None) is not None)
        self.btn_tune.setEnabled(on and not trial_active)
        self.btn_tune_signature.setEnabled(on and not trial_active)
        self._at_result = res
        self._at_result_generation = getattr(
            self, "_tuning_authority_generation", 0)
        self._at_result_path = self._dump_autotune_result(res)
        # Apply is offered only for an applicable (GREEN/YELLOW) result — a RED/aborted
        # run must never leave the previous run's Apply enabled.
        self.btn_tune_apply.setEnabled(False)
        g = self.tune_gain_fields
        if res.r_pp_ohm is not None:
            g["r_pp"].setText("%.6g Ω" % res.r_pp_ohm)
        if res.l_pp_h is not None:
            g["l_pp"].setText("%.6g µH" % (res.l_pp_h * 1e6))
        # btw-006: surface the Phase-1-measured R/L on the Motor Settings page too.
        # The drive itself stores no R/L (Current ID computes them), so those fields
        # would otherwise stay "—"; mirror the measured values here for convenience.
        mf = getattr(self, "motor_fields", None)
        if mf:
            if res.r_pp_ohm is not None and "R" in mf:
                mf["R"].setText("%.6g Ω  · Phase 1 측정" % res.r_pp_ohm)
            if res.l_pp_h is not None and "L" in mf:
                mf["L"].setText("%.6g mH  · Phase 1 측정" % (res.l_pp_h * 1e3))
        if res.kp_v_per_a is not None:
            g["kp_cur"].setText("%.6g V/A" % res.kp_v_per_a)
        if res.ki_hz is not None:
            g["ki_cur"].setText("%.6g Hz" % res.ki_hz)
        if res.pm_deg is not None:
            g["pm"].setText("%.1f °" % res.pm_deg)
        if res.status == autotune_current.GREEN:
            self._set_tune_stage(-1, done_upto=self._AT_PHASE1_LAST)
            saved = ("  ·  저장: %s" % self._at_result_path) if self._at_result_path else ""
            self.tune_status.setText(
                "✅ GREEN — 후보 산출 완료. Hardware P1 Apply는 durable "
                "RAM-trial WAL 대기 중 잠김.%s" % saved)
            self.btn_tune_apply.setEnabled(False)
        elif res.status == autotune_current.YELLOW:
            self.tune_status.setText(
                "⚠ YELLOW — %s (후보 검토만 가능; Hardware Apply 잠김)"
                % (res.reason or ""))
            self.btn_tune_apply.setEnabled(False)
        else:
            self.tune_status.setText("⛔ RED — %s" % (res.reason or "실패"))
        self._set_connected_ui(bool(getattr(self, "_ui_connected", False)))
        self._flash("Auto-Tune %s" % res.status)

    def _on_autotune_applied(self, ok, msg):
        source = self.sender()
        if (source is not None and source is not self.worker) or getattr(
                self, "_motor_write_inflight", False):
            return
        self._flash(("게인 적용됨: " + msg) if ok else ("적용 실패: " + msg))

    @staticmethod
    def _retain_failed_gain_trial(trial):
        """Terminal stale signal payloads must not recreate an active trial."""
        if trial is None:
            return False
        return getattr(trial, "persistence_state", None) not in (
            "RESTORED", "PERSISTED")

    def _on_current_gain_action(self, action, ok, msg, trial):
        """Own the P1 RAM -> restore/save transaction state."""
        expected = {"begin": "p1_begin", "restore": "p1_restore",
                    "commit": "p1_commit"}.get(action)
        if expected is None or not MainWindow._gain_action_signal_is_current(
                self,
                "P1", action, trial):
            return
        MainWindow._release_tune_dispatch(self, expected)
        on = bool(getattr(self, "_ui_connected", False) and
                  (self.worker is None or self.worker.isRunning()))
        if action == "begin":
            if ok:
                self._p1_gain_trial = trial
                self._p1_trial_generation = getattr(
                    self, "_tuning_authority_generation", 0)
                self.tune_status.setText(
                    "P1 게인 RAM 임시 적용 완료 — SV 미실행. "
                    "Save P1은 잠김; Restore P1로 원본을 복원하세요.")
            else:
                if MainWindow._retain_failed_gain_trial(trial):
                    self._p1_gain_trial = trial
                    self._p1_trial_generation = getattr(
                        self, "_tuning_authority_generation", 0)
                else:
                    self._p1_trial_generation = None
                self.tune_status.setText("⛔ P1 RAM 임시 적용 실패 — %s" % msg)
        elif action == "restore":
            if ok:
                self._p1_gain_trial = None
                self._p1_trial_generation = None
                self.tune_status.setText("P1 원래 게인 복원·되읽기 완료 — SV 미실행.")
            else:
                if MainWindow._retain_failed_gain_trial(trial):
                    self._p1_gain_trial = trial
                if getattr(trial, "persistence_state", None) == "UNKNOWN":
                    self.tune_status.setText(
                        "⛔ P1 영구저장 상태 UNKNOWN — 복원/저장 재시도 금지. "
                        "reset/reconnect identity evidence와 게인 readback 필요. %s" % msg)
                else:
                    self.tune_status.setText("⛔ P1 원래 게인 복원 실패 — %s" % msg)
        elif action == "commit":
            if ok:
                self._p1_gain_trial = None
                self._p1_trial_generation = None
                self.tune_status.setText("✅ P1 legacy/offline SV 경로 완료.")
            else:
                if MainWindow._retain_failed_gain_trial(trial):
                    self._p1_gain_trial = trial
                if getattr(trial, "persistence_state", None) == "UNKNOWN":
                    self.tune_status.setText(
                        "⛔ P1 영구저장 상태 UNKNOWN — Save/Restore 재시도 금지. "
                        "reset/reconnect identity evidence와 게인 readback 필요. %s" % msg)
                else:
                    self.tune_status.setText("⛔ P1 SV 저장 거부/실패 — %s" % msg)
        self._set_connected_ui(on)
        self._flash(("P1 게인 작업 완료: " if ok else "P1 게인 작업 실패: ") + msg)

    # ---- Phase 2 (vel/pos) GUI glue — mirror of the Phase-1 set -----------------------
    def _p1_model_overrides_for_p2(self) -> dict:
        """Return only a current-generation, finite Phase-1 R/L model."""
        result = getattr(self, "_at_result", None)
        if (result is None
                or getattr(self, "_at_result_generation", None) !=
                getattr(self, "_tuning_authority_generation", 0)
                or getattr(result, "status", None) not in
                (autotune_current.GREEN, autotune_current.YELLOW)):
            return {}
        values = {
            "r_pp_ohm": getattr(result, "r_pp_ohm", None),
            "l_pp_h": getattr(result, "l_pp_h", None),
        }
        if not all(
                DriveWorker._is_finite_number(value) and float(value) > 0.0
                for value in values.values()):
            return {}
        return {name: float(value) for name, value in values.items()}

    def _velpos_overrides(self) -> dict:
        """Phase-2 param overrides from the Tuning-page controls (everything
        else = kernel defaults).  ramp_frac = user-selected breakaway cap;
        the kernel's RAMP_FRAC_ABS_MAX(0.4) preflight gate stays the ceiling."""
        try:
            frac = float(self.cmb_ba_cap.currentData())
        except (TypeError, ValueError):
            frac = 0.2
        overrides = {"ramp_frac": frac}
        overrides.update(self._p1_model_overrides_for_p2())
        return overrides

    def _guard_unsaved_vp_trial(self, action: str) -> bool:
        """Block actions that could overwrite or accidentally persist any RAM trial."""
        p1 = getattr(self, "_p1_gain_trial", None) is not None
        p2 = getattr(self, "_vp_gain_trial", None) is not None
        if not (p1 or p2):
            return False
        phase = "P1" if p1 else "P2"
        if p1:
            msg = ("P1 RAM 임시 게인이 남아 있습니다. Save P1은 검증 "
                   "capability 미구현으로 잠겨 있으므로, Restore로 복원한 "
                   "뒤 %s하세요." % action)
        else:
            msg = ("P2 RAM 임시 게인이 남아 있습니다. Production Save는 "
                   "durable pre-assignment trial WAL 부재로 잠겨 있으므로, "
                   "Restore로 복원한 뒤 %s하세요." % action)
        self._flash(msg)
        self.tune_status.setText("⚠ 미저장 %s 게인 보호 — %s" % (phase, msg))
        return True

    def _run_signature_clicked(self):
        if getattr(self, "_motor_write_inflight", False):
            self._flash("Motor profile 저장 중에는 커뮤테이션 서명을 시작할 수 없습니다.")
            return
        if getattr(self, "_tune_dispatch_inflight", None) is not None:
            self._flash("이전 튜닝/검증 전송의 시작 또는 결과를 기다리는 중입니다.")
            return
        if self._guard_unsaved_vp_trial("커뮤테이션 서명을 실행"):
            return
        if not (self.worker and self.worker.isRunning()):
            self._flash("드라이브를 먼저 연결하세요.")
            return
        btn = QtWidgets.QMessageBox.warning(
            self, "커뮤테이션 서명 실행 확인 (실제 저전류 동작)",
            "커뮤테이션 서명 전용 시험을 실행합니다.\n\n"
            "• +TC를 0 → 최대 1.30 A로 최대 2.0초 동안만 램프\n"
            "• 합격창: i_ba 0.50..1.30 A, 피드백 방향 +\n"
            "• UNIT-DIAG, UM=3, 식별 펄스, JV 속도 운전은 실행하지 않음\n"
            "• 모든 종료 경로에서 TC=0, MO=0 및 임시 제한 복귀 확인\n"
            "• 게인 적용과 SV 저장 없음\n\n"
            "축 주변이 비어 있고 E-stop/STO가 즉시 사용 가능한 상태입니까?",
            QtWidgets.QMessageBox.StandardButton.Yes |
            QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if not self._claim_tune_dispatch("signature"):
            return
        self._vp_signature_run = True
        self._vp_result = None
        self.btn_tune_vp_apply.setEnabled(False)
        self.worker.start_velpos_autotune({
            "signature_only": True,
            "signature_cap_a": 1.30,
            "signature_i_min_a": 0.50,
            "signature_i_max_a": 1.30,
        })

    def _run_velpos_clicked(self):
        if getattr(self, "_motor_write_inflight", False):
            self._flash("Motor profile 저장 중에는 Phase 2를 시작할 수 없습니다.")
            return
        if getattr(self, "_tune_dispatch_inflight", None) is not None:
            self._flash("이전 튜닝/검증 전송의 시작 또는 결과를 기다리는 중입니다.")
            return
        if self._guard_unsaved_vp_trial("Phase 2를 다시 실행"):
            return
        if not (self.worker and self.worker.isRunning()):
            self._flash("연결 후 사용하세요."); return
        ov = self._velpos_overrides()
        if not all(name in ov for name in ("r_pp_ohm", "l_pp_h")):
            self._flash(
                "Phase 2 잠금: 이 연결·Motor generation에서 측정한 Phase 1 R/L이 필요합니다.")
            return
        btn = QtWidgets.QMessageBox.warning(
            self, "Phase 2 실행 확인 (⚠ 실제 회전)",
            "⚠ Phase 2는 모터를 실제로 회전시킵니다.\n\n"
            "• 브레이크어웨이 캡: %.2f × live CL[1] "
            "(통전 직전 worker가 재판독·검증; 캐시된 A 값은 표시하지 않음)\n"
            % ov["ramp_frac"] +
            "• ±토크 펄스로 약 1바퀴/측정 회전 + 저속 조그(±300/±900rpm)가 수행됩니다.\n"
            "• 축이 자유롭게, 안전하게 돌 수 있어야 합니다 — 부하·치구·손·케이블을 확인하세요.\n"
            "• 과속 시 자동 정지(1200rpm SW 가드), 언제든 Abort로 안전 중단됩니다.\n"
            "• 속도/가속 리밋을 임시 설정 후 종료 시 원복합니다.\n\n"
            "축이 자유회전 가능함을 확인했고, 실행할까요?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if not self._claim_tune_dispatch("p2"):
            return
        self._vp_signature_run = False
        self._vp_result = None
        for k in ("k_a", "b_visc", "i_c", "kp_vel", "ki_vel", "kp_pos",
                  "pm_vel", "pm_pos"):
            self.tune_gain_fields[k].setText("—")
        self.btn_tune_vp_apply.setEnabled(False)
        self.worker.start_velpos_autotune(ov)     # cap override + module defaults

    def _apply_velpos_clicked(self):
        if not PRODUCTION_GAIN_TRIALS_ENABLED:
            self._flash(
                "P2 Apply locked: durable pre-assignment RAM-trial WAL is not "
                "available for hardware links.")
            return
        if getattr(self, "_motor_write_inflight", False):
            self._flash("Motor profile 저장 중에는 P2 게인을 적용할 수 없습니다.")
            return
        if getattr(self, "_vp_gain_trial", None) is not None:
            self._flash("이미 P2 RAM 임시 게인이 적용되어 있습니다.")
            return
        r = getattr(self, "_vp_result", None)
        if (r is None
                or getattr(self, "_vp_result_generation", None) !=
                getattr(self, "_tuning_authority_generation", 0)
                or r.status not in (autotune_velpos.GREEN, autotune_velpos.YELLOW)):
            self._flash("적용할 유효한 Phase 2 결과가 없습니다."); return
        btn = QtWidgets.QMessageBox.question(
            self, "Phase 2 synthetic/retained RAM trial 확인",
            "개발 회귀/retained recovery 전용 경로입니다. Production hardware entry는 잠겨 있습니다.\n"
            "산출된 속도/위치 게인을 RAM에만 임시 적용합니다 (모터 OFF에서만).\n"
            "원래 게인을 먼저 저장하며, 이 단계에서는 SV를 실행하지 않습니다.\n\n"
            "• KP[2] = %.6g A/(cnt/s)\n• KI[2] = %.6g Hz\n• KP[3] = %.6g 1/s\n"
            "• 이 retained/synthetic 경로도 Production Save 권한은 만들지 않습니다.\n"
            "• 검증 뒤 Restore로 원래 게인을 복원합니다.\n"
            "(FF[1]은 변경하지 않습니다)\n\nRAM 임시 적용을 진행할까요?"
            % (r.kp_vel, r.ki_vel_hz, r.kp_pos),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if self.worker and self.worker.isRunning():
            if not self._claim_tune_dispatch("p2_begin"):
                return
            self.btn_tune_vp_apply.setEnabled(False)
            self.worker.begin_velpos_gain_trial(r)
            self._flash("Phase 2 게인 RAM 임시 적용 중… (SV 없음)")

    def _restore_velpos_clicked(self):
        trial = getattr(self, "_vp_gain_trial", None)
        if trial is None:
            self._flash("복원할 P2 RAM 게인 시험이 없습니다.")
            return
        if getattr(trial, "persistence_state", "RAM_TRIAL") not in (
                "RAM_TRIAL", "RESTORE_FAILED"):
            self._flash("현재 P2 상태에서는 Restore를 실행할 수 없습니다.")
            return
        if not (self.worker and self.worker.isRunning()):
            self._flash("복원하려면 드라이브를 다시 연결하세요.")
            return
        if not self._claim_tune_dispatch("p2_restore"):
            return
        self.btn_tune_vp_restore.setEnabled(False)
        self.btn_tune_vp_save.setEnabled(False)
        self.worker.restore_velpos_gain_trial(trial)
        self._flash("원래 P2 게인 복원 및 되읽기 확인 중…")

    def _save_velpos_clicked(self):
        if not PRODUCTION_GAIN_TRIALS_ENABLED:
            self._flash(
                "P2 Save locked: no production RAM trial can be created "
                "without durable pre-assignment WAL authority.")
            return
        trial = getattr(self, "_vp_gain_trial", None)
        if (trial is None or not getattr(self, "_vp_trial_verified_green", False)
                or getattr(self, "_vp_verified_trial", None) is not trial):
            self._flash("SV 저장은 이 RAM 게인의 검증런 GREEN 후에만 가능합니다.")
            return
        if (getattr(trial, "persistence_state", "RAM_TRIAL") != "RAM_TRIAL"
                or getattr(trial, "restore_only", False)):
            self._flash("현재 P2 시험은 Save 권한이 없습니다(restore-only/terminal 상태).")
            return
        if not (self.worker and self.worker.isRunning()):
            self._flash("드라이브를 다시 연결하고 재검증하세요.")
            return
        if (getattr(self, "_vp_trial_generation", None) !=
                getattr(self, "_tuning_authority_generation", 0)):
            self._flash("이 P2 시험은 이전 연결 세대입니다 — Restore만 허용됩니다.")
            return
        btn = QtWidgets.QMessageBox.question(
            self, "P2 legacy/offline 저장 경로 확인",
            "Production에서는 도달할 수 없는 legacy/offline 경로입니다. 검증런 GREEN을 받은 "
            "RAM 게인의 persistence state machine만 검사합니다.\n\n"
            "저장 직전에 KP[2]/KI[2]/KP[3] 전체를 다시 읽어 임시 적용값과 "
            "일치할 때만 SV를 보냅니다.\n\n영구저장할까요?",
            QtWidgets.QMessageBox.StandardButton.Yes |
            QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if not self._claim_tune_dispatch("p2_commit"):
            return
        self.btn_tune_vp_save.setEnabled(False)
        self.worker.commit_velpos_gain_trial(trial)
        self._flash("검증된 P2 게인 최종 되읽기 후 SV 저장 중…")

    def _run_verify_clicked(self):
        if getattr(self, "_motor_write_inflight", False):
            self._flash("Motor profile 저장 중에는 검증런을 시작할 수 없습니다.")
            return
        if getattr(self, "_tune_dispatch_inflight", None) is not None:
            self._flash("이전 튜닝/검증 전송의 시작 또는 결과를 기다리는 중입니다.")
            return
        if not (self.worker and self.worker.isRunning()):
            self._flash("연결 후 사용하세요."); return
        if not self._motion_signature_is_current():
            self._flash(
                "P2 Verify locked: this connection requires Commutation "
                "Signature GREEN first.")
            return
        signature_generation = self._motion_signature_generation
        signature_token = self._motion_signature_token
        btn = QtWidgets.QMessageBox.warning(
            self, "게인 검증런 실행 확인 (⚠ 실제 회전)",
            "⚠ F2 검증런은 모터를 실제로 회전시킵니다 (JV 스텝 300 → 900 rpm).\n\n"
            "• 적용된 KP[2]/KI[2]/KP[3] 게인의 스텝응답을 드라이브 레코더로 캡처해\n"
            "  오버슈트(<25%)·지속발진·정상상태 전류/속도를 자동 판정합니다.\n"
            "• 축이 자유롭게, 안전하게 돌 수 있어야 합니다 — 부하·치구·손·케이블 확인.\n"
            "• 과속 시 자동 정지(1200rpm SW 가드), 언제든 Abort로 안전 중단됩니다.\n"
            "• 무인 실행 금지 — 감독 하에서만 실행하세요.\n\n"
            "축이 자유회전 가능함을 확인했고, 실행할까요?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if (not self._motion_signature_is_current()
                or self._motion_signature_generation != signature_generation
                or self._motion_signature_token != signature_token):
            self._flash(
                "P2 Verify locked: Commutation Signature changed while "
                "confirmation was open.")
            return
        trial = getattr(self, "_vp_gain_trial", None)
        if (trial is not None and
                getattr(self, "_vp_trial_generation", None) !=
                getattr(self, "_tuning_authority_generation", 0)):
            self._flash("이 P2 시험은 이전 연결 세대입니다 — Verify 대신 Restore하세요.")
            return
        if not self._claim_tune_dispatch("verify", trial):
            return
        self.worker.start_verify_vp(
            {}, trial, signature_token=signature_token)  # defaults (300, 900)

    def _on_verify_started(self):
        if not self._tune_signal_is_current("verify"):
            return
        self._mark_energizing_ui("Velocity/position verification is running")
        for b in (self.btn_tune, self.btn_tune_signature, self.btn_tune_vp,
                  self.btn_tune_verify,
                  self.btn_tune_apply, self.btn_tune_vp_apply,
                  self.btn_tune_vp_restore, self.btn_tune_vp_save):
            b.setEnabled(False)
        self.btn_tune_abort.setEnabled(True)
        self.tune_status.setText("▶ 검증런(F2) 시작 — JV 스텝 사다리…")

    def _on_verify_result(self, res):
        if not self._tune_signal_is_current("verify"):
            return
        verified_trial = getattr(self, "_verify_trial_inflight", None)
        self._release_tune_dispatch("verify")
        self.btn_tune_abort.setEnabled(False)
        on = bool(self.worker and self.worker.isRunning())
        trial = getattr(self, "_vp_gain_trial", None)
        same_trial = trial is not None and verified_trial is trial
        verification = getattr(res, "gain_trial_verification", None)
        verification_matches = (
            same_trial and verification is not None
            and getattr(verification, "trial", None) is trial
            and getattr(trial, "verification", None) is verification)
        restore = (res.evidence or {}).get("gain_trial_restore", {})
        if trial is not None and same_trial:
            if res.status == autotune_velpos.GREEN and verification_matches:
                self._vp_trial_verified_green = True
                self._vp_verified_trial = trial
                self._vp_verified_generation = getattr(
                    self, "_tuning_authority_generation", 0)
            elif res.status == autotune_velpos.GREEN:
                self._vp_trial_verified_green = False
                self._vp_verified_trial = None
                self._vp_verified_generation = None
            elif restore.get("pass") is True:
                self._vp_gain_trial = None
                self._vp_trial_generation = None
                self._vp_trial_verified_green = False
                self._vp_verified_trial = None
                self._vp_verified_generation = None
                trial = None
            else:
                self._vp_trial_verified_green = False
                self._vp_verified_trial = None
                self._vp_verified_generation = None
        elif trial is not None:
            # A late/foreign result must never authorize the current RAM trial.
            self._vp_trial_verified_green = False
            self._vp_verified_trial = None
            self._vp_verified_generation = None
        no_trial = (trial is None and
                    getattr(self, "_p1_gain_trial", None) is None)
        self.btn_tune.setEnabled(on and no_trial)
        self.btn_tune_vp.setEnabled(
            on and no_trial and self._motion_signature_is_current()
            and bool(self._p1_model_overrides_for_p2()))
        self.btn_tune_signature.setEnabled(on and no_trial)
        trial_state = (getattr(trial, "persistence_state", "RAM_TRIAL")
                       if trial is not None else None)
        restore_allowed = (trial is not None and
                           trial_state in ("RAM_TRIAL", "RESTORE_FAILED"))
        normal_allowed = (trial is not None and trial_state == "RAM_TRIAL"
                          and not getattr(trial, "restore_only", False))
        self.btn_tune_verify.setEnabled(
            on and getattr(self, "_p1_gain_trial", None) is None
            and (trial is None or normal_allowed)
            and self._motion_signature_is_current())
        self.btn_tune_apply.setEnabled(False)
        self.btn_tune_vp_apply.setEnabled(False)
        self.btn_tune_vp_restore.setEnabled(
            on and restore_allowed)
        self.btn_tune_vp_save.setEnabled(False)
        steps = (res.evidence or {}).get("verify", {}).get("steps", [])
        parts = ["%.0frpm: OS %.1f%% 정착 %s I_ss %.3fA %s"
                 % (s["rpm"], 100 * s["overshoot_frac"],
                    ("%.0fms" % (1e3 * s["t_settle_s"])
                     if s.get("t_settle_s") is not None else "—"),
                    s["i_ss"], "✓" if s["pass"] else "✗") for s in steps]
        path = (res.evidence or {}).get("result_path")
        restore_text = ""
        if restore.get("required"):
            restore_text = (" — 원래 게인 자동 복원 완료" if restore.get("pass")
                            else " — 원래 게인 자동 복원 실패")
        elif (trial is not None and res.status == autotune_velpos.GREEN
              and verification_matches):
            restore_text = " — RAM 게인 유지, Production Save 잠금·Restore만 가능"
        elif trial is not None and res.status == autotune_velpos.GREEN:
            restore_text = " — 검증 토큰 불일치, Save 차단·재검증 필요"
        self.tune_status.setText(
            "검증런(F2) %s%s%s%s%s"
            % (res.status,
               (" — " + " | ".join(parts)) if parts else "",
               (" — %s" % res.reason) if res.reason else "",
               restore_text,
               ("  ·  저장: %s" % path) if path else ""))
        self._flash("검증런 %s" % res.status)

        # Result delivery never grants authority by itself.  Recalculate from
        # the latest accepted telemetry envelope (which may still be revoked).
        self._set_connected_ui(bool(
            self._ui_connected and self._connection_admitted and on))

    def _on_velpos_started(self):
        if not self._tune_signal_is_current("p2", "signature"):
            return
        self._mark_energizing_ui("Phase 2 tuning/signature is running")
        self.btn_tune.setEnabled(False); self.btn_tune_signature.setEnabled(False)
        self.btn_tune_vp.setEnabled(False)
        self.btn_tune_verify.setEnabled(False)
        self.btn_tune_abort.setEnabled(True)
        self.btn_tune_vp_apply.setEnabled(False)
        self.btn_tune_vp_restore.setEnabled(False)
        self.btn_tune_vp_save.setEnabled(False)
        self._set_tune_stage(3, done_upto=-1)
        self.tune_status.setText("▶ Phase 2 시작 — 커뮤테이션/구성 검증 중…")

        if self._vp_signature_run:
            self.tune_status.setText(
                "커뮤테이션 서명 시작 — +TC 0→1.30 A, Phase 2 미진입")

    def _on_velpos_progress(self, code, detail):
        if not self._tune_signal_is_current("p2", "signature"):
            return
        if self._vp_signature_run:
            self.tune_status.setText("커뮤테이션 서명 [%s] %s" % (code, detail))
            return
        stage = self._VP_CODE_STAGE.get(code, 3)
        done = stage - 1 if code != "DONE" else self._AT_PHASE2_LAST
        self._set_tune_stage(stage if code != "DONE" else -1, done_upto=done)
        self.tune_status.setText("◆ [%s] %s" % (code, detail))

    def _dump_velpos_result(self, res):
        """Persist the full Phase-2 result to .omc/state (oracle comparison off disk)."""
        try:
            import json as _json, dataclasses as _dc, time as _time
            d = os.path.join(".omc", "state")
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, "autotune_vp_result_%d.json" % int(_time.time() * 1000))
            with open(path, "w", encoding="utf-8") as fh:
                _json.dump(_dc.asdict(res), fh, ensure_ascii=False, indent=1, default=str)
            return path
        except Exception:
            return None

    def _on_velpos_result(self, res):
        if not self._tune_signal_is_current("p2", "signature"):
            return
        self._release_tune_dispatch("p2", "signature")
        self.btn_tune_abort.setEnabled(False)
        on = bool(getattr(self, "_ui_connected", False) and
                  (self.worker is None or self.worker.isRunning()))
        trial_active = (getattr(self, "_p1_gain_trial", None) is not None or
                        getattr(self, "_vp_gain_trial", None) is not None)
        self.btn_tune.setEnabled(on and not trial_active)
        self.btn_tune_vp.setEnabled(
            on and not trial_active and self._motion_signature_is_current()
            and bool(self._p1_model_overrides_for_p2()))
        self.btn_tune_signature.setEnabled(on and not trial_active)
        self.btn_tune_verify.setEnabled(
            on and getattr(self, "_p1_gain_trial", None) is None
            and self._motion_signature_is_current())
        self._vp_result_path = self._dump_velpos_result(res)
        evidence = res.evidence or {}
        signature = (self._vp_signature_run or
                     evidence.get("signature_gate", {}).get("mode") ==
                     "standalone_commutation_signature")
        if signature:
            self._vp_signature_run = False
            self._vp_result = None
            self._vp_result_generation = None
            self.btn_tune_vp_apply.setEnabled(False)
            sig = evidence.get("signature_gate", {})
            final = evidence.get("final_state", {})
            i_ba = sig.get("i_ba_a")
            i_text = "%.3f A" % i_ba if isinstance(i_ba, (int, float)) else "미검출"
            saved = ("  ·  저장: %s" % self._vp_result_path
                     if self._vp_result_path else "")
            self.tune_status.setText(
                "커뮤테이션 서명 %s — i_ba=%s, 방향=%s, 종료 MO=%s TC=%s%s%s"
                % (res.status, i_text, sig.get("direction", "-"),
                   final.get("MO", "-"), final.get("TC", "-"),
                   (" · " + res.reason) if res.reason else "", saved))
            self._flash("Commutation Signature %s" % res.status)
            self._set_connected_ui(bool(
                self._ui_connected and self._connection_admitted and on))
            return
        self._vp_signature_run = False
        self._vp_result = res
        self._vp_result_generation = getattr(
            self, "_tuning_authority_generation", 0)
        # RED/aborted must never leave a previous run's Apply enabled (Phase-1 fix)
        self.btn_tune_vp_apply.setEnabled(False)
        g = self.tune_gain_fields
        if res.k_a is not None:
            g["k_a"].setText("%.5g cnt/s²/A" % res.k_a)
        if res.b_visc is not None:
            g["b_visc"].setText("%.4g A/(cnt/s)" % res.b_visc)
        if res.i_c is not None:
            g["i_c"].setText("%.4g A" % res.i_c)
        if res.kp_vel is not None:
            g["kp_vel"].setText("%.6g A/(cnt/s)" % res.kp_vel)
        if res.ki_vel_hz is not None:
            g["ki_vel"].setText("%.6g Hz" % res.ki_vel_hz)
        if res.kp_pos is not None:
            g["kp_pos"].setText("%.6g 1/s" % res.kp_pos)
        if res.pm_vel_deg is not None:
            gm = (" · GM %.1f dB" % res.gm_db) if res.gm_db is not None else ""
            g["pm_vel"].setText("%.1f °%s" % (res.pm_vel_deg, gm))
        if res.pm_pos_deg is not None:
            g["pm_pos"].setText("%.1f °" % res.pm_pos_deg)
        if res.status == autotune_velpos.GREEN:
            self._set_tune_stage(-1, done_upto=self._AT_PHASE2_LAST)
            saved = ("  ·  저장: %s" % self._vp_result_path) if self._vp_result_path else ""
            self.tune_status.setText(
                "✅ Phase 2 GREEN — 후보 산출 완료. Hardware P2 Apply/Save는 "
                "durable RAM-trial WAL 대기 중 잠김.%s" % saved)
        elif res.status == autotune_velpos.YELLOW:
            self.tune_status.setText("⚠ Phase 2 YELLOW — %s (후보 검토만 가능; Hardware Apply 잠김)"
                                     % (res.reason or ""))
        else:
            self.tune_status.setText("⛔ Phase 2 RED — %s" % (res.reason or "실패"))
        self._set_connected_ui(bool(
            self._ui_connected and self._connection_admitted and on))
        self._flash("Phase 2 Auto-Tune %s" % res.status)

    def _on_velpos_applied(self, ok, msg):
        source = self.sender()
        if (source is not None and source is not self.worker) or getattr(
                self, "_motor_write_inflight", False):
            return
        self._flash(("P2 게인 적용됨: " + msg) if ok else ("P2 적용 실패: " + msg))

    def _on_velpos_gain_action(self, action, ok, msg, trial):
        """Own the GUI state for the explicit RAM -> verify -> SV workflow."""
        expected = {"begin": "p2_begin", "restore": "p2_restore",
                    "commit": "p2_commit"}.get(action)
        if expected is None or not MainWindow._gain_action_signal_is_current(
                self,
                "P2", action, trial):
            return
        MainWindow._release_tune_dispatch(self, expected)
        on = bool(self.worker and self.worker.isRunning())
        if action == "begin":
            if ok:
                self._vp_gain_trial = trial
                self._vp_trial_generation = getattr(
                    self, "_tuning_authority_generation", 0)
                self._vp_trial_verified_green = False
                self._vp_verified_trial = None
                self._vp_verified_generation = None
                self.tune_status.setText(
                    "P2 synthetic/retained RAM trial 완료 — Production Save 잠금; Verify 후 Restore하세요.")
            else:
                # begin returns a trial only when automatic rollback could not
                # be proven; retain it so the operator can retry Restore.
                if MainWindow._retain_failed_gain_trial(trial):
                    self._vp_gain_trial = trial
                    self._vp_trial_generation = getattr(
                        self, "_tuning_authority_generation", 0)
                else:
                    self._vp_trial_generation = None
                self._vp_trial_verified_green = False
                self._vp_verified_trial = None
                self._vp_verified_generation = None
                self.tune_status.setText("⛔ P2 RAM 임시 적용 실패 — %s" % msg)
        elif action == "restore":
            if ok:
                self._vp_gain_trial = None
                self._vp_trial_generation = None
                self._vp_trial_verified_green = False
                self._vp_verified_trial = None
                self._vp_verified_generation = None
                self.tune_status.setText("P2 원래 게인 복원·되읽기 완료 — SV 미실행.")
            else:
                if MainWindow._retain_failed_gain_trial(trial):
                    self._vp_gain_trial = trial
                self._vp_trial_verified_green = False
                self._vp_verified_trial = None
                self._vp_verified_generation = None
                if getattr(trial, "persistence_state", None) == "UNKNOWN":
                    self.tune_status.setText(
                        "⛔ P2 영구저장 상태 UNKNOWN — 복원 재시도 금지. "
                        "재연결·리셋 후 게인 readback 필요. %s" % msg)
                else:
                    self.tune_status.setText("⛔ P2 원래 게인 복원 실패 — %s" % msg)
        elif action == "commit":
            if ok:
                self._vp_gain_trial = None
                self._vp_trial_generation = None
                self._vp_trial_verified_green = False
                self._vp_verified_trial = None
                self._vp_verified_generation = None
                self.tune_status.setText("✅ P2 legacy/offline SV 경로 완료.")
            else:
                if MainWindow._retain_failed_gain_trial(trial):
                    self._vp_gain_trial = trial
                self._vp_trial_verified_green = False
                self._vp_verified_trial = None
                self._vp_verified_generation = None
                if getattr(trial, "persistence_state", None) == "UNKNOWN":
                    self.tune_status.setText(
                        "⛔ P2 영구저장 상태 UNKNOWN — Save/Restore/Verify 재시도 금지. "
                        "드라이브 재연결·리셋 후 게인 readback으로 확인하세요. %s" % msg)
                else:
                    self.tune_status.setText(
                        "⛔ P2 SV 저장 거부/실패 — 재검증 필요. %s" % msg)

        update_ui = getattr(self, "_set_connected_ui", None)
        if callable(update_ui):
            update_ui(on)
        self._flash(("P2 게인 작업 완료: " if ok else "P2 게인 작업 실패: ") + msg)

    def _on_encoder_maint_result(self, ok, msg):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        self._motion_session_zero_confirmed = False
        if not ok:
            self._revoke_telemetry_authority(
                "Encoder Maintenance failed; encoder/PX authority is UNKNOWN")
        # Persistent (non-transient) so the drive's exact response can't be missed.
        self._flash("엔코더 정비 " + ("완료" if ok else "실패/거부"))
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Information if ok else QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle("엔코더 정비 결과" + ("" if ok else " (거부/실패)"))
        box.setText(("드라이브 응답:\n\n%s" % msg) + ("\n\nMotion 탭에서 POSITION을 확인하세요." if ok else ""))
        box.exec()

    # ---- port refresh ----------------------------------------------------------------
    def refresh_ports(self):
        cur = self.cmb_port.currentText()
        self.cmb_port.clear()
        ports = list_serial_ports()
        self.cmb_port.addItems(ports if ports else [])
        if cur and cur in ports:
            self.cmb_port.setCurrentText(cur)

    def _update_persistence_badge(self):
        summary = dict(getattr(self, "_persistence_audit_summary", {}) or {})
        locked = bool(summary.get("lock_active"))
        other = int(summary.get("other_active_count") or 0)
        if summary.get("ledger_error"):
            text, style = (
                "⛔ PERSISTENCE LEDGER ERROR · READ-ONLY LOCK", "error")
        elif locked:
            phase = summary.get("phase") or "SV"
            text, style = (
                "⛔ PERSISTENCE UNKNOWN · %s · READ-ONLY LOCK" % phase,
                "error")
        elif other:
            text, style = (
                "⚠ OTHER DRIVE UNKNOWN · %d" % other, "ready")
        else:
            text, style = ("PERSISTENCE LEDGER · CLEAR", "neutral")
        self.lbl_persistence_badge.setText(text)
        self.lbl_persistence_badge.setProperty("status", style)
        self._restyle(self.lbl_persistence_badge)
        connected = bool(getattr(self, "_ui_connected", False))
        self.btn_persistence_audit.setEnabled(
            connected and locked
            and bool(summary.get("record_id"))
            and not bool(summary.get("ledger_error")))

    def _on_persistence_audit_status(self, payload):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        try:
            summary = DriveWorker._validated_persistence_status(payload)
        except Exception as exc:
            summary = DriveWorker._locked_persistence_status(exc)
        summary.setdefault("status", "UNKNOWN")
        summary.setdefault("resolved", False)
        summary.setdefault("detail", "")
        summary.setdefault("lock_active", True)
        summary.setdefault("record_id", None)
        summary.setdefault("phase", None)
        summary.setdefault("other_active_count", 0)
        summary.setdefault("ledger_error", None)
        self._session_log_event_changed(self.session_log.append(
            category="persistence", name="persistence.status",
            severity=("ERROR" if (summary.get("lock_active")
                                  or summary.get("ledger_error")) else "INFO"),
            payload={
                "status": summary.get("status"),
                "resolved": summary.get("resolved") is True,
                "lock_active": summary.get("lock_active") is True,
                "phase": summary.get("phase"),
                "other_active_count": summary.get("other_active_count"),
                "ledger_error_present": bool(summary.get("ledger_error")),
            }))
        self._persistence_audit_summary = summary
        self._persistence_recovery_unknown = bool(summary["lock_active"])
        if summary.get("resolved") is True and not self._persistence_recovery_unknown:
            if summary.get("phase") == "P1":
                self._p1_gain_trial = None
                self._p1_trial_generation = None
            elif summary.get("phase") == "P2":
                self._vp_gain_trial = None
                self._vp_trial_generation = None
        self._vp_trial_verified_green = False
        self._vp_verified_trial = None
        self._vp_verified_generation = None
        self._motion_signature_green = False
        self._motion_signature_token = None
        self._motion_signature_generation = None
        self._update_persistence_badge()
        # A status update may refine an already admitted connection, but it
        # must never create ONLINE authority by itself while a rejected worker
        # is merely finishing terminal cleanup.
        connected = bool(
            getattr(self, "_connection_admitted", False)
            and getattr(self, "_ui_connected", False)
            and self.worker and self.worker.isRunning())
        self._set_connected_ui(connected)
        detail = str(summary.get("detail") or summary.get("status"))
        if hasattr(self, "tune_status"):
            if self._persistence_recovery_unknown:
                self.tune_status.setText(
                    "⛔ PERSISTENCE UNKNOWN · READ-ONLY LOCK — %s" % detail)
            elif summary.get("resolved") is True:
                observed = ("APPLIED PROFILE" if summary.get("status") ==
                            "RESOLVED_APPLIED_PROFILE" else "ORIGINAL PROFILE")
                self.tune_status.setText(
                    "PERSISTENCE AUDIT RESOLVED · %s · %s OBSERVED AFTER RESET · "
                    "MOTION AUTHORITY NOT GRANTED" %
                    (summary.get("phase") or "?", observed))
        self._flash("Persistence audit: %s — %s" %
                    (summary.get("status"), detail))

    def _persistence_audit_clicked(self):
        summary = getattr(self, "_persistence_audit_summary", {}) or {}
        if not (self.worker and self.worker.isRunning()
                and summary.get("lock_active")
                and summary.get("record_id")
                and not summary.get("ledger_error")):
            self._flash("현재 연결에서 실행 가능한 persistence audit 기록이 없습니다.")
            return
        answer = QtWidgets.QMessageBox.warning(
            self, "전원 재인가 후 읽기 전용 Audit 확인",
            "USB 재연결만으로는 저장 여부를 판정할 수 없습니다.\n\n"
            "UNKNOWN 발생 뒤 드라이브가 flash를 다시 로드하도록 전원을 "
            "완전히 OFF → ON 했거나 동등한 현장 reset을 완료했음을 확인합니다.\n\n"
            "이 Audit은 SN[4]/VR/VP/VB와 정지 상태 및 해당 record profile만 읽습니다. "
            "SV·LD·RS·설정 쓰기·모션 명령은 보내지 않습니다.\n\n"
            "현장 전원 재인가 확인을 서명하고 읽기 전용 Audit을 실행할까요?",
            QtWidgets.QMessageBox.StandardButton.Yes |
            QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel)
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.btn_persistence_audit.setEnabled(False)
        self.worker.audit_persistence_after_reset()
        self._flash("전원 재인가 서명 접수 · query-only persistence audit 대기 중…")

    # ---- connect / disconnect --------------------------------------------------------
    def _connection_access_mode_selection_changed(self):
        """Keep the offline Connect label aligned with the explicit selector."""
        if not hasattr(self, "btn_conn"):
            return
        if self.worker and self.worker.isRunning():
            return
        mode = self.cmb_access_mode.currentData()
        label = _ACCESS_MODE_LABELS.get(mode, "INVALID MODE")
        self.btn_conn.setText("Connect · %s" % label)

    def _reset_connection_access_mode(self):
        """Forget one-shot supervised authority and restore the safe default."""
        self._requested_connection_access_mode = None
        if not hasattr(self, "cmb_access_mode"):
            return
        shutdown_pending = bool(
            getattr(self, "_connection_shutdown_pending", False))
        index = self.cmb_access_mode.findData(OBSERVE_ONLY_ACCESS_MODE)
        self.cmb_access_mode.blockSignals(True)
        if index >= 0:
            self.cmb_access_mode.setCurrentIndex(index)
        self.cmb_access_mode.blockSignals(False)
        self.cmb_access_mode.setEnabled(not shutdown_pending)
        if hasattr(self, "btn_conn") and not self._ui_connected:
            self.btn_conn.setEnabled(not shutdown_pending)
            self.btn_conn.setText(
                "Disconnecting" if shutdown_pending
                else "Connect · Read Only")

    def _confirm_supervised_connection(self):
        """Request one non-persistent, connection-only supervised authority."""
        answer = QtWidgets.QMessageBox.warning(
            self,
            "Supervised Control 연결 확인",
            "This opens a write-capable session. Connecting does not enable "
            "the motor and does not run motion, commutation, tuning, PX=0, "
            "parameter writes, or SV.\n\n"
            "After connection, fresh live telemetry, MO=0, and each action's "
            "separate confirmation are still required before controls can "
            "energize or move the motor.\n\n"
            "Software STOP is not independent STO/E-stop. Continue only when "
            "an operator is present at the machine, the axis area is safe, and "
            "independent E-stop/STO is immediately available.\n\n"
            "This approves the connection mode only. It approves no motor action.",
            QtWidgets.QMessageBox.StandardButton.Yes |
            QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel)
        return answer == QtWidgets.QMessageBox.StandardButton.Yes

    def toggle_connect(self):
        if self.worker and self.worker.isRunning():
            self.disconnect_drive()
        else:
            self.connect_drive()

    def connect_drive(self):
        requested_mode = self.cmb_access_mode.currentData()
        if requested_mode not in {
                OBSERVE_ONLY_ACCESS_MODE, SUPERVISED_ACCESS_MODE}:
            self._reset_connection_access_mode()
            self._flash("알 수 없는 Access Mode — Read Only로 복귀했습니다.")
            return
        port = self.cmb_port.currentText().strip()
        if not port:
            self._flash("연결할 COM 포트가 없습니다 (⟳로 새로고침).")
            return
        if self.cmb_conn.currentText() != "Direct Access USB":
            self._flash("이번 빌드는 USB만 활성 — 다른 방식은 곧 추가됩니다.")
            return
        if (requested_mode == SUPERVISED_ACCESS_MODE
                and not self._confirm_supervised_connection()):
            self._reset_connection_access_mode()
            self._flash("Supervised Control 연결이 취소되었습니다.")
            return
        if self.session_log.connection_active:
            self._session_log_event_changed(self.session_log.end_connection(
                "superseded by a new connection attempt"))
        if hasattr(self, "system_configuration"):
            self._system_configuration_end(
                "New connection attempt awaiting admission")
        if hasattr(self, "status_monitor_model"):
            self._status_monitor_end(
                "New connection attempt awaiting admission")
        self._invalidate_tuning_result_authority()
        self._invalidate_recorder_target_ui("New connection requires Personality rediscovery")
        self._connection_shutdown_pending = False
        self._connection_admitted = False
        self._connection_access_mode = None
        self._requested_connection_access_mode = requested_mode
        self._telemetry_authoritative = False
        self._telemetry_authority_loss_latched = False
        self._last_telemetry_sequence = 0
        self._last_telemetry_received_monotonic = None
        self._last_telemetry_sample_finished_monotonic = None
        self._energizing_state = False
        self._last_mo = None
        self._motor_write_inflight = False
        # Close every ordinary read/write gate before a replacement worker is
        # constructed. A missed stopped signal must not leave the previous
        # target's ONLINE controls usable during identity admission.
        self._set_connected_ui(False)
        self.btn_conn.setEnabled(False)
        self.btn_conn.setText(
            "Connecting · %s" % _ACCESS_MODE_LABELS[requested_mode])
        self.lbl_state.setText("CONNECTING")
        self.lbl_state.setProperty("on", "false")
        self._restyle(self.lbl_state)
        self.cmb_port.setEnabled(False)
        self.cmb_conn.setEnabled(False)
        self.cmb_access_mode.setEnabled(False)
        self.worker = DriveWorker(
            port, query_only=(requested_mode == OBSERVE_ONLY_ACCESS_MODE))
        if getattr(self.worker, "access_mode", None) != requested_mode:
            self.worker = None
            self._set_connected_ui(False)
            self._reset_connection_access_mode()
            self._flash(
                "Worker Access Mode 불일치 — 연결을 시작하지 않았습니다.")
            return
        self.worker.connected.connect(self._on_connected)
        self.worker.failed.connect(self._on_failed)
        self.worker.telemetry.connect(self._on_telemetry)
        self.worker.command_done.connect(self._on_command_done)
        self.worker.motor_params.connect(self._on_motor_params)
        self.worker.feedback.connect(self._on_feedback)
        self.worker.tuning_gains.connect(self._on_tuning_gains)
        self.worker.write_result.connect(self._on_write_result)
        self.worker.autotune_started.connect(self._on_autotune_started)
        self.worker.autotune_progress.connect(self._on_autotune_progress)
        self.worker.autotune_result.connect(self._on_autotune_result)
        self.worker.autotune_applied.connect(self._on_autotune_applied)
        self.worker.current_gain_action.connect(self._on_current_gain_action)
        self.worker.velpos_started.connect(self._on_velpos_started)
        self.worker.velpos_progress.connect(self._on_velpos_progress)
        self.worker.velpos_result.connect(self._on_velpos_result)
        self.worker.velpos_applied.connect(self._on_velpos_applied)
        self.worker.velpos_gain_action.connect(self._on_velpos_gain_action)
        self.worker.verify_started.connect(self._on_verify_started)
        self.worker.verify_result.connect(self._on_verify_result)
        self.worker.encoder_maint_result.connect(self._on_encoder_maint_result)
        self.worker.soft_zero_result.connect(self._on_soft_zero_result)
        self.worker.axis_summary.connect(self._on_axis_summary)
        self.worker.axis_current_reference.connect(
            self._on_axis_current_reference)
        self.worker.axis_drive_mode.connect(self._on_axis_drive_mode)
        self.worker.axis_digital_inputs.connect(self._on_axis_digital_inputs)
        self.worker.axis_digital_outputs.connect(self._on_axis_digital_outputs)
        self.worker.motion_result.connect(self._on_motion_result)
        self.worker.motion_authority.connect(self._on_motion_authority)
        self.worker.recorder_signals_result.connect(self._on_recorder_signals_result)
        self.worker.recorder_status_changed.connect(self._on_recorder_status)
        self.worker.recorder_manifest.connect(self._on_recorder_manifest)
        self.worker.recorder_data.connect(self._on_recorder_data)
        self.worker.persistence_audit_status.connect(
            self._on_persistence_audit_status)
        self.worker.stopped.connect(self._on_stopped)
        self.worker.start()

    def disconnect_drive(self):
        p1 = getattr(self, "_p1_gain_trial", None) is not None
        p2 = getattr(self, "_vp_gain_trial", None) is not None
        p1_unknown = (p1 and
            getattr(self._p1_gain_trial, "persistence_state", None) == "UNKNOWN")
        p2_unknown = (p2 and
            getattr(self._vp_gain_trial, "persistence_state", None) == "UNKNOWN")
        if (p1 and not p1_unknown) or (p2 and not p2_unknown):
            self._vp_trial_verified_green = False
            self._vp_verified_trial = None
            phase = "P1" if p1 else "P2"
            self._flash("미저장 %s RAM 게인이 있어 연결 해제를 차단했습니다. 먼저 Restore를 실행하세요." % phase)
            self.tune_status.setText(
                "⚠ 연결 해제 차단 — 미저장 %s RAM 게인을 먼저 복원하거나 저장하세요." % phase)
            return
        if p1_unknown or p2_unknown:
            phase = "P1" if p1_unknown else "P2"
            self.tune_status.setText(
                "%s 영구저장 상태 UNKNOWN — 연결 해제 후 드라이브 리셋·재연결하고 "
                "identity/durability evidence와 실제 게인 readback을 확인하세요." % phase)
        if self.worker:
            self._begin_connection_shutdown(
                "Disconnect requested; telemetry authority revoked")
            self.worker.stop()

    def _begin_connection_shutdown(self, detail):
        """Synchronously close UI authority before worker shutdown can block.

        A QThread may need time to finish a vendor read or its verified energy
        closeout. Signals already queued before ``stop()`` remain deliverable
        during that interval, so terminal authority cannot wait for ``stopped``.
        """
        energizing = bool(getattr(self, "_energizing_state", False))
        self._connection_shutdown_pending = True
        self._connection_admitted = False
        self._connection_access_mode = None
        # Prevent a late ``connected`` signal from admitting a worker after
        # shutdown was requested while connection setup was still in flight.
        self._requested_connection_access_mode = None
        self._revoke_telemetry_authority(
            str(detail or "Connection shutdown requested"),
            energizing=energizing)
        self.btn_conn.setEnabled(False)
        self.btn_conn.setText("Disconnecting")
        self.cmb_port.setEnabled(False)
        self.cmb_conn.setEnabled(False)
        if hasattr(self, "cmb_access_mode"):
            self.cmb_access_mode.setEnabled(False)
        self.lbl_state.setText("DISCONNECTING")
        self.lbl_state.setProperty("on", "false")
        self._restyle(self.lbl_state)

    def _telemetry_envelope_valid(self, telemetry, *, new_generation=False):
        """Validate one live worker authority envelope without mutating UI state."""
        t = dict(telemetry or {})
        finite_values = all(
            DriveWorker._is_finite_number(t.get(key))
            for key in TELEMETRY_REQUIRED_FIELDS)
        mo = t.get("mo")
        sequence = t.get("telemetry_sequence")
        received = t.get("telemetry_received_monotonic")
        started = t.get("_sample_started_monotonic")
        finished = t.get("_sample_finished_monotonic")
        duration = t.get("_sample_duration_s")
        now = time.monotonic()
        sequence_floor = (
            0 if new_generation
            else int(getattr(self, "_last_telemetry_sequence", 0)))
        previous_received = (
            None if new_generation
            else getattr(self, "_last_telemetry_received_monotonic", None))
        previous_finished = (
            None if new_generation
            else getattr(
                self, "_last_telemetry_sample_finished_monotonic", None))
        timing_finite = all(DriveWorker._is_finite_number(value) for value in (
            started, finished, duration))
        timing_ok = False
        if timing_finite:
            started_f = float(started)
            finished_f = float(finished)
            duration_f = float(duration)
            source_age_f = now - finished_f
            timing_ok = bool(
                finished_f >= started_f
                and 0.0 <= duration_f <= TELEMETRY_MAX_SAMPLE_DURATION_S
                and abs((finished_f - started_f) - duration_f) <= 0.05
                and -0.25 <= source_age_f <= TELEMETRY_SOURCE_MAX_AGE_S)
        return bool(
            t.get("telemetry_valid") is True
            and t.get("session_coordinate_known") is True
            and t.get("encoder_maintenance_reconnect_required") is False
            and finite_values
            and float(mo) in (0.0, 1.0)
            and isinstance(sequence, int) and not isinstance(sequence, bool)
            and sequence > sequence_floor
            and DriveWorker._is_finite_number(received)
            and -0.25 <= now - float(received) <= TELEMETRY_UI_MAX_AGE_S
            and timing_ok
            and (not DriveWorker._is_finite_number(previous_received)
                 or float(received) >= float(previous_received))
            and (not DriveWorker._is_finite_number(previous_finished)
                 or float(finished) >= float(previous_finished))
        )

    @staticmethod
    def _quiescent_connection_state_valid(state):
        """Independently validate the worker's observe-only admission summary."""
        if not isinstance(state, dict):
            return False
        required = ("MO", "SO", "VX", "PS", "MF")
        if not all(DriveWorker._is_finite_number(state.get(name))
                   for name in required):
            return False
        return bool(
            float(state["MO"]) == 0.0
            and float(state["SO"]) == 0.0
            and float(state["VX"]) == 0.0
            and float(state["PS"]) in (-2.0, -1.0)
            and float(state["MF"]) == 0.0)

    def _on_connected(self, info: dict):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        info = dict(info or {})
        identity = info.get("drive_identity")
        initial = info.get("initial_telemetry")
        identity_ok = (
            isinstance(identity, str)
            and _HASHED_DRIVE_ID_RE.fullmatch(identity) is not None)
        access_mode = info.get("access_mode")
        requested_mode = getattr(
            self, "_requested_connection_access_mode", None)
        worker_mode = getattr(self.worker, "access_mode", None)
        valid_modes = {
            OBSERVE_ONLY_ACCESS_MODE, SUPERVISED_ACCESS_MODE}
        if requested_mode not in valid_modes:
            requested_mode = None
        if worker_mode not in valid_modes:
            worker_mode = None
        access_mode_ok = bool(
            requested_mode in valid_modes
            and worker_mode == requested_mode
            and access_mode == requested_mode)
        quiescent_ok = bool(
            access_mode != OBSERVE_ONLY_ACCESS_MODE
            or self._quiescent_connection_state_valid(
                info.get("quiescent_state")))
        try:
            display_metadata = (
                system_configuration.sanitize_connection_display_metadata(
                    info))
            metadata_ok = True
        except system_configuration.ProjectionRejected:
            display_metadata = {}
            metadata_ok = False
        telemetry_ok = self._telemetry_envelope_valid(
            initial, new_generation=True)
        try:
            DriveWorker._validated_persistence_status(
                info.get("persistence_status"))
            persistence_ok = True
        except Exception:
            persistence_ok = False
        worker_running = bool(self.worker and self.worker.isRunning())
        if not (worker_running and identity_ok and access_mode_ok
                and quiescent_ok and metadata_ok and telemetry_ok
                and persistence_ok):
            stop = getattr(self.worker, "stop", None)
            if callable(stop):
                stop()
            self._connection_admitted = False
            self._telemetry_authoritative = False
            self._on_failed(
                "Connection admission evidence incomplete; ONLINE was refused")
            return
        # A newly accepted connection is a new target generation even if a
        # prior worker never delivered its stopped signal.
        self._release_tune_dispatch()
        self._advance_tuning_authority_generation()
        self._connection_shutdown_pending = False
        self._connection_admitted = True
        self._connection_access_mode = access_mode
        # From this point onward every label, passive observer and export sees
        # the same control-neutralized/privacy-redacted metadata projection.
        # The raw vendor strings are not retained by MainWindow.
        info.update(display_metadata)
        self._connected_identity = dict(info)
        self._telemetry_authority_loss_latched = False
        self._last_telemetry_sequence = 0
        self._last_telemetry_received_monotonic = None
        self._last_telemetry_sample_finished_monotonic = None
        self._session_log_last_recorder_state = None
        self._session_log_event_changed(self.session_log.begin_connection(
            target_identity=identity,
            metadata={
                "firmware": info.get("fw"),
                "pal": info.get("pal"),
                "boot": info.get("boot"),
                "application_target_class": info.get("target_type"),
                "application_target_class_provenance": (
                    "APPLICATION CLASSIFICATION · NOT BOARD READBACK"),
            }))
        self._status_monitor_activate(
            self.session_log.current_generation, identity)
        persistence_status = info.get("persistence_status")
        if isinstance(persistence_status, dict):
            self._persistence_audit_summary = dict(persistence_status)
            self._persistence_recovery_unknown = bool(
                persistence_status.get("lock_active"))
            self._update_persistence_badge()
        self.lbl_fw.setText(info.get("fw") or "—")
        self.lbl_pal.setText(str(info.get("pal") or "—"))
        self.lbl_boot.setText(info.get("boot") or "—")
        self.lbl_type.setText(info.get("target_type") or "—")
        if hasattr(self, "cmb_ribbon_target"):
            self.cmb_ribbon_target.setItemText(
                0, "Drive01 · %s · %s" %
                (self.cmb_port.currentText(), info.get("fw") or "firmware unknown"))
        self._on_telemetry(initial)
        if not self._telemetry_authoritative:
            stop = getattr(self.worker, "stop", None)
            if callable(stop):
                stop()
            self._connection_admitted = False
            self._on_failed(
                "Initial telemetry expired before UI admission completed")
            return
        self._set_connected_ui(True)

    def _invalidate_recorder_target_ui(self, detail):
        """Drop target-bound signal authority without deleting captured evidence."""
        self._recorder_signals_target = None
        self._recorder_pending_selection.clear()
        if hasattr(self, "rec_signal_list"):
            self.rec_signal_list.blockSignals(True)
            self.rec_signal_list.clear()
            self.rec_signal_list.blockSignals(False)
        if hasattr(self, "lbl_rec_buffer"):
            self.lbl_rec_buffer.setText(
                "16K shared buffer · rediscover Signals for the current target")
        if hasattr(self, "recorder_log"):
            self.recorder_log.setPlainText(
                "TARGET SIGNALS STALE\n\n%s\n"
                "Immediate remains locked until Personality Signals are rediscovered."
                % detail)
        if hasattr(self, "cmb_ribbon_target"):
            self.cmb_ribbon_target.setItemText(0, "Drive01 · OFFLINE / unverified")
        if hasattr(self, "recorder_plot"):
            self._invalidate_recorder_view(detail, clear=False, advance=True)
        self._update_recorder_controls()

    def _revoke_telemetry_authority(self, detail, *, energizing=False):
        """Fail closed without hiding that a live worker may still own energy."""
        was_authoritative = bool(self._telemetry_authoritative)
        self._telemetry_authoritative = False
        reset_snapshot = getattr(
            self, "_reset_axis_safety_snapshot", None)
        if callable(reset_snapshot):
            reset_snapshot(
                str(detail or "Telemetry authority unavailable"))
        reset_inputs = getattr(
            self, "_reset_axis_digital_inputs", None)
        if callable(reset_inputs):
            reset_inputs(
                str(detail or "Telemetry authority unavailable"))
        reset_mode = getattr(
            self, "_reset_axis_drive_mode", None)
        if callable(reset_mode):
            reset_mode(
                str(detail or "Telemetry authority unavailable"))
        reset_current_reference = getattr(
            self, "_reset_axis_current_reference", None)
        if callable(reset_current_reference):
            reset_current_reference(
                str(detail or "Telemetry authority unavailable"))
        reset_outputs = getattr(
            self, "_reset_axis_digital_outputs", None)
        if callable(reset_outputs):
            reset_outputs(
                str(detail or "Telemetry authority unavailable"))
        if hasattr(self, "status_monitor_model"):
            self._status_monitor_revoke(
                str(detail or "Telemetry authority unavailable"))
        if hasattr(self, "system_configuration"):
            self._system_configuration_revoke(
                str(detail or "Telemetry authority unavailable"))
        self._last_mo = None
        self._energizing_state = bool(energizing)
        for metric in (self.m_pos, self.m_perr, self.m_vel, self.m_iq):
            metric.setText("—")
        self.m_pos_sub.setText("")
        self.m_vel_sub.setText("")
        self.lbl_motor.setText(
            "ENERGIZING / LIVE TELEMETRY PAUSED"
            if energizing else "MOTOR STATE UNKNOWN")
        self.lbl_motor.setToolTip(str(detail or "Telemetry authority unavailable"))
        self.lbl_motor.setProperty("on", "false")
        self._restyle(self.lbl_motor)
        connected = bool(
            getattr(self, "_connection_admitted", False)
            and getattr(self, "_ui_connected", False)
            and self.worker and self.worker.isRunning())
        self._set_connected_ui(connected)
        if was_authoritative:
            self._telemetry_authority_loss_latched = True
            self._session_log_event_changed(self.session_log.append(
                category="telemetry", name="telemetry.authority_lost",
                severity="WARNING",
                payload={
                    "detail": str(detail or "Telemetry authority unavailable")[:500],
                    "energizing": bool(energizing),
                }))

    def _check_telemetry_watchdog(self):
        """Expire an otherwise valid envelope when polling stops advancing."""
        if not (getattr(self, "_ui_connected", False)
                and getattr(self, "_telemetry_authoritative", False)
                and not getattr(self, "_energizing_state", False)):
            return
        received = getattr(self, "_last_telemetry_received_monotonic", None)
        if not DriveWorker._is_finite_number(received):
            self._revoke_telemetry_authority("Live telemetry timestamp is missing")
            return
        age = time.monotonic() - float(received)
        if age < -0.25 or age > TELEMETRY_UI_MAX_AGE_S:
            self._revoke_telemetry_authority(
                "Live telemetry expired (age %.3f s)" % age)

    def _mark_energizing_ui(self, detail):
        """Revoke the previous MO claim before an energy-capable job begins."""
        self._revoke_telemetry_authority(detail, energizing=True)

    def _on_failed(self, msg: str):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        shutdown_pending = bool(
            getattr(self, "_connection_shutdown_pending", False))
        shutdown_was_energizing = bool(
            shutdown_pending and getattr(self, "_energizing_state", False))
        self._session_log_event_changed(self.session_log.append(
            category="connection", name="connection.failed", severity="ERROR",
            payload={"detail": str(msg or "unspecified failure")[:500]}))
        recorder_was_pending = self._recorder_state_pending()
        self._motor_write_inflight = False
        self._release_tune_dispatch()
        self._advance_tuning_authority_generation()
        self._vp_trial_verified_green = False
        self._vp_verified_trial = None
        self._vp_verified_generation = None
        self._connection_admitted = False
        self._connection_access_mode = None
        self._telemetry_authoritative = False
        self._telemetry_authority_loss_latched = False
        self._last_telemetry_sequence = 0
        self._last_telemetry_received_monotonic = None
        self._last_telemetry_sample_finished_monotonic = None
        self._energizing_state = shutdown_was_energizing
        self._last_mo = None
        if hasattr(self, "system_configuration"):
            self._system_configuration_end("Connection failed")
        if hasattr(self, "status_monitor_model"):
            self._status_monitor_end("Connection failed")
        self._set_connected_ui(False)
        self._reset_connection_access_mode()
        self._connected_identity = {}
        self._invalidate_recorder_target_ui("Connection failed")
        if recorder_was_pending:
            self._on_recorder_status(
                "STALE_CONNECTION_UNKNOWN",
                "Connection ended before Recorder lifecycle was closed")
        self._flash("연결 실패: %s" % msg)

    def _on_telemetry(self, t: dict):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        t = dict(t or {})
        telemetry_ok = bool(
            getattr(self, "_connection_admitted", False)
            and self._telemetry_envelope_valid(t))
        self._session_log_event_changed(self.session_log.record_telemetry(
            t, accepted_by_ui=telemetry_ok))
        if not telemetry_ok:
            self._revoke_telemetry_authority(
                "Incomplete, stale, or replayed live telemetry",
                energizing=getattr(self, "_energizing_state", False))
            return
        self._last_telemetry_sequence = int(t["telemetry_sequence"])
        self._last_telemetry_received_monotonic = float(
            t["telemetry_received_monotonic"])
        self._last_telemetry_sample_finished_monotonic = float(
            t["_sample_finished_monotonic"])
        self._telemetry_authoritative = True
        self._energizing_state = False
        self.m_pos.setText(self._fmt(t.get("pos")))
        self.m_perr.setText(self._fmt(t.get("pos_err")))
        self.m_vel.setText(self._fmt(t.get("vel")))
        self.m_iq.setText(self._fmt(t.get("iq"), 3))
        # human-readable units (auto-adapt to any encoder via CA[18] counts/rev)
        pos, vel = t.get("pos"), t.get("vel")
        ca18 = getattr(self, "_ca18", None)
        if isinstance(pos, (int, float)) and ca18:
            rev = pos / ca18
            self.m_pos_sub.setText("= %.3f rev · %.1f°" % (rev, (rev * 360.0) % 360.0))
        else:
            self.m_pos_sub.setText("")
        if isinstance(vel, (int, float)) and ca18:
            self.m_vel_sub.setText("= %.1f RPM" % (vel * 60.0 / ca18))
        else:
            self.m_vel_sub.setText("")
        mo = t.get("mo")
        self._last_mo = mo
        enabled = (float(mo) == 1.0)
        self.lbl_motor.setText("MOTOR ENABLED" if enabled else "MOTOR DISABLED")
        self.lbl_motor.setToolTip(
            "Authoritative live telemetry sequence %d" %
            self._last_telemetry_sequence)
        self.lbl_motor.setProperty("on", "true" if enabled else "false")
        self._restyle(self.lbl_motor)
        if getattr(self, "_telemetry_authority_loss_latched", False):
            self._session_log_event_changed(self.session_log.append(
                category="telemetry", name="telemetry.authority_restored",
                severity="INFO",
                payload={
                    "telemetry_sequence": self._last_telemetry_sequence,
                    "motor_enabled": bool(enabled),
                }))
            self._telemetry_authority_loss_latched = False
        if getattr(self, "_ui_connected", False):
            self._set_connected_ui(True)
        if hasattr(self, "status_monitor_model"):
            # This observer runs only after the core sequence, timestamps, MO,
            # metrics and connected controls have advanced successfully.
            self._status_monitor_accept_telemetry(t)
        if hasattr(self, "system_configuration"):
            # Run the passive Inspector only after the complete core motor/UI
            # safety state has advanced.  Any model or renderer failure is
            # contained to that page and cannot leave a half-applied MO state.
            try:
                self._system_configuration_accept_telemetry(t)
            except Exception:
                self._system_configuration_observer_failed()

    def _on_stopped(self):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        if self.session_log.connection_active:
            self._session_log_event_changed(
                self.session_log.end_connection("worker stopped"))
        else:
            self._session_log_event_changed(self.session_log.append(
                category="connection", name="worker.stopped", severity="INFO",
                payload={"reason": "worker stopped"}, affects_current=False))
        recorder_was_pending = self._recorder_state_pending()
        self._motor_write_inflight = False
        self._release_tune_dispatch()
        self._advance_tuning_authority_generation()
        self._vp_trial_verified_green = False
        self._vp_verified_trial = None
        self._vp_verified_generation = None
        self._connection_shutdown_pending = False
        self._connection_admitted = False
        self._connection_access_mode = None
        self._telemetry_authoritative = False
        self._telemetry_authority_loss_latched = False
        self._last_telemetry_sequence = 0
        self._last_telemetry_received_monotonic = None
        self._last_telemetry_sample_finished_monotonic = None
        self._energizing_state = False
        self._last_mo = None
        if hasattr(self, "system_configuration"):
            self._system_configuration_end("Worker stopped")
        if hasattr(self, "status_monitor_model"):
            self._status_monitor_end("Worker stopped")
        if getattr(self, "_p1_gain_trial", None) is not None:
            if getattr(self._p1_gain_trial, "persistence_state", None) == "UNKNOWN":
                self.tune_status.setText(
                    "⛔ 연결 끊김 — P1 영구저장 상태 UNKNOWN. reset/reconnect identity "
                    "evidence와 게인 readback 전까지 쓰기 금지.")
            else:
                self.tune_status.setText(
                    "⚠ 연결 끊김 — P1 RAM 상태 미확인. 재연결 후 Restore P1을 실행하세요.")
        if getattr(self, "_vp_gain_trial", None) is not None:
            # A cable/worker drop does not prove that drive power was removed;
            # keep the rollback snapshot and require restore after reconnect.
            if getattr(self._vp_gain_trial, "persistence_state", None) == "UNKNOWN":
                self.tune_status.setText(
                    "⛔ 연결 끊김 — P2 영구저장 상태 UNKNOWN. 드라이브 리셋·재연결 후 "
                    "자동 게인 readback 판정을 기다리세요.")
            else:
                self.tune_status.setText(
                    "⚠ 연결 끊김 — P2 RAM 상태 미확인. 재연결 후 Restore P2를 실행하세요.")
        self._set_connected_ui(False)
        self._reset_connection_access_mode()
        self._connected_identity = {}
        self._invalidate_recorder_target_ui("Drive disconnected")
        if recorder_was_pending:
            self._on_recorder_status(
                "STALE_CONNECTION_UNKNOWN",
                "Connection ended before Recorder lifecycle was closed")

    def _mutation_authority_ready(self, *, require_motor_disabled=False):
        """Return whether an ordinary drive mutation may cross the UI boundary.

        STOP/abort escape paths deliberately do not use this gate. They must
        remain available after an admitted connection loses telemetry.
        """
        ready = bool(
            getattr(self, "_ui_connected", False)
            and getattr(self, "_connection_admitted", False)
            and getattr(self, "_telemetry_authoritative", False)
            and not getattr(self, "_energizing_state", False)
            and getattr(self, "_connection_access_mode", None)
            == SUPERVISED_ACCESS_MODE
            and getattr(self, "_last_mo", None) == 0
            and self.worker and self.worker.isRunning())
        if require_motor_disabled:
            ready = ready and getattr(self, "_last_mo", None) == 0
        return ready

    def zero_position(self):
        if self._guard_unsaved_vp_trial("세션 원점을 변경"):
            return
        if self._mutation_authority_ready(require_motor_disabled=True):
            self._motion_session_zero_confirmed = False
            self.btn_zero.setEnabled(False)
            self.worker.soft_zero()
            self._flash("세션 원점 안전 확인 및 PX=0 되읽기 중…")
        else:
            self.btn_zero.setEnabled(False)
            self._flash(
                "Session Zero 잠금: 승인된 live telemetry와 MO=0이 필요합니다.")

    def _on_soft_zero_result(self, ok, msg, telemetry):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        self._motion_session_zero_confirmed = False
        self._flash(msg)
        if ok and isinstance(telemetry, dict):
            self._on_telemetry(telemetry)
            self._motion_session_zero_confirmed = bool(
                getattr(self, "_telemetry_authoritative", False)
                and DriveWorker._is_finite_number(telemetry.get("pos"))
                and abs(float(telemetry["pos"])) <= 0.5)
        elif not ok:
            self._revoke_telemetry_authority(
                "Soft Zero failed or its readback was not authoritative")
        on = bool(self.worker and self.worker.isRunning())
        self._set_connected_ui(bool(
            self._ui_connected and self._connection_admitted and on))

    def _on_command_done(self, cmd, resp):
        self._flash("%s → %s" % (cmd, resp if resp else "OK"))

    _MOTOR_TYPES = {0: "Rotary brushless", 1: "Rotary DC brush", 2: "Linear brushless",
                    3: "Linear voice coil", 4: "Rotary two-phase", 6: "Linear two-phase"}

    def _on_motor_params(self, mp):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        f = self.motor_fields
        self._ca18 = mp.get("ca18")
        mt = mp.get("mtype")
        if isinstance(mt, (int, float)):
            ix = self.motor_type_combo.findData(int(mt))
            if ix >= 0:
                self.motor_type_combo.setCurrentIndex(ix)
        f["peak"].setText(self._fmt(mp.get("peak_arms"), 2))
        f["cont"].setText(self._fmt(mp.get("cont_arms"), 2))
        f["maxspeed"].setText(self._fmt(mp.get("rpm"), 0))
        f["poles"].setText(self._fmt(mp.get("poles")))
        for k in ("R", "L", "Ke"):
            f[k].setText("— (Current ID가 산출)")

    def _on_feedback(self, fb):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        # ``_fb_connected`` controls mutation-capable dynamic widgets, not
        # merely whether feedback readback is available.  A feedback refresh
        # must not undo the observe-only or MO=1 locks applied by
        # ``_set_connected_ui``.
        self._fb_connected = self._mutation_authority_ready(
            require_motor_disabled=True)
        self._fb_raws = fb.get("params") or {}
        sid = fb.get("sensor_id")
        if isinstance(sid, (int, float)):
            self.cmb_sensor.blockSignals(True)
            ix = self.cmb_sensor.findData(int(sid))
            if ix < 0:      # drive reports a non-EAS id (e.g. stepper/sensorless) — show honestly
                nm = feedback_spec.SENSOR_NAMES.get(int(sid), "ID %d" % int(sid))
                self.cmb_sensor.addItem("%s   · EAS 목록 외 (ID %d)" % (nm, int(sid)), int(sid))
                ix = self.cmb_sensor.count() - 1
            self.cmb_sensor.setCurrentIndex(ix)
            self.cmb_sensor.blockSignals(False)
        m = fb.get("commut_method")
        if isinstance(m, (int, float)):
            ix = self.cmb_commut.findData(int(m))
            if ix >= 0:
                self.cmb_commut.setCurrentIndex(ix)
        ff = self.fb_fields
        ff["counts"].setText(self._fmt(fb.get("counts_rev")))
        ff["sockets"].setText("%s / %s / %s" % (fb.get("pos_socket"), fb.get("vel_socket"), fb.get("commut_socket")))
        self._rebuild_fb_dynamic(sid if not isinstance(sid, float) else int(sid),
                                 values=self._fb_raws)

    def _write_feedback(self):
        # Deliberately fail closed even if this disabled slot is invoked directly.
        # UI-screen mapping is not a write authority: sensor/firmware-specific
        # ranges, CA[41] side effects, rollback order, and post-reset audit must
        # first be frozen in a versioned registry.
        self._flash(
            "Feedback direct save locked — versioned write registry와 "
            "RAM readback/rollback/persistence audit가 필요합니다.")

    def _write_motor(self):
        if getattr(self, "_motor_write_inflight", False):
            self._flash("Motor profile 저장 요청이 이미 진행 중입니다 — 결과를 기다리세요.")
            return
        if getattr(self, "_tune_dispatch_inflight", None) is not None:
            self._flash("튜닝/검증 작업이 진행 중입니다 — 완료 후 Motor profile을 저장하세요.")
            return
        if self._guard_unsaved_vp_trial("모터 설정을 저장"):
            return
        import math
        f = self.motor_fields
        try:
            peak = float(f["peak"].text()); cont = float(f["cont"].text())
            rpm = float(f["maxspeed"].text())
            poles_raw = float(f["poles"].text())
            poles = int(poles_raw)
            mtype = int(self.motor_type_combo.currentData())
        except (ValueError, TypeError):
            self._flash("숫자 형식 오류 — 값을 확인하세요."); return
        if not all(math.isfinite(value)
                   for value in (peak, cont, rpm, poles_raw)):
            self._flash("Motor 값은 모두 유한한 숫자여야 합니다."); return
        if peak <= 0 or cont <= 0 or rpm <= 0:
            self._flash("전류와 최대 속도는 0보다 커야 합니다."); return
        if not poles_raw.is_integer() or poles <= 0:
            self._flash("Pole Pairs는 양의 정수여야 합니다."); return
        if cont > peak:
            self._flash("연속전류(Cont)는 피크(Peak) 이하여야 합니다."); return
        if not getattr(self, "_ca18", None):
            self._flash("CA[18](counts/rev) 미확보 — 재연결 후 재시도."); return
        rt2 = math.sqrt(2)
        writes = {"PL[1]": round(peak * rt2, 4), "CL[1]": round(cont * rt2, 4),
                  "VH[2]": int(round(rpm * self._ca18 / 60.0)),
                  "CA[19]": poles, "CA[28]": mtype}
        rows = [("Peak Current", "%.2f Arms" % peak, "PL[1] = %s" % writes["PL[1]"]),
                ("Continuous Stall", "%.2f Arms" % cont, "CL[1] = %s" % writes["CL[1]"]),
                ("Max Speed", "%g RPM" % rpm, "VH[2] = %s" % writes["VH[2]"]),
                ("Pole Pairs", "%d" % poles, "CA[19] = %d" % poles),
                ("Motor Type", self._MOTOR_TYPES.get(mtype, str(mtype)), "CA[28] = %d" % mtype)]
        preview = "\n".join("• %s :  %s\n      (%s)" % (n, val, raw) for n, val, raw in rows)
        btn = QtWidgets.QMessageBox.question(
            self, "Motor Profile durable 저장 확인",
            "아래 값을 안전 사전검증한 뒤 durable WAL을 먼저 기록하고 RAM에 적용합니다.\n"
            "전체 되읽기가 일치해야 SV를 정확히 한 번 실행하며, RAM 단계 실패는 원값 복원·되읽기를 시도합니다.\n"
            "SV 응답 유실은 UNKNOWN으로 잠기고 자동 재시도하지 않습니다.\n\n%s\n\n진행할까요?" % preview,
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if self.worker and self.worker.isRunning():
            # Motor constants are inputs to both tuning phases.  Revoke any
            # previously computed result before the write request crosses the
            # worker boundary; a later UI refresh must not re-enable Apply.
            self._advance_tuning_authority_generation()
            self._motor_write_inflight = True
            self.btn_motor_write.setEnabled(False)
            self.worker.write_motor(writes, ca18_basis=self._ca18)
            self._flash("Motor profile durable transaction 진행 중…")

    def _on_write_result(self, ok, msg):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        # Defensive repeat: results can arrive for jobs queued by another UI
        # path, and both success and partial/failed Motor transactions make a
        # cached tuning result insufficient evidence for the current profile.
        self._advance_tuning_authority_generation()
        self._motor_write_inflight = False
        connected = bool(
            getattr(self, "_ui_connected", False)
            and self.worker and self.worker.isRunning())
        self._set_connected_ui(connected)
        self._flash(
            "Motor profile durable transaction 완료" if ok
            else "Motor profile 저장 거부/실패: %s" % msg)

    # ---- Encoder Maintenance (EAS parity: TW[18] datum / TW[19] multi-turn / TW[20] errors) ----
    def _encoder_maint_dialog(self):
        """Build the Encoder Maintenance dialog mirroring EAS. Returns (dialog, widgets).

        Grounded (firmware notes): TW[18]=<val> resets single-turn absolute position
        (EnDat 2.2: any value, 0 to zero; other sensors 0 only else EC=99); TW[20]=<socket>
        resets that socket's errors (=1 for socket 1). TW[19] resets multi-turn; its
        argument is the feedback socket (=1 for socket 1). On a multi-turn encoder
        PX = multiturn*counts + single-turn, so a full
        zero needs BOTH TW[18] and TW[19] (matches the observed EAS procedure).
        These commands update the encoder datum directly; ``SV`` is not part of
        the maintenance transaction."""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Encoder Maintenance")
        dlg.setMinimumWidth(380)
        lay = QtWidgets.QVBoxLayout(dlg); lay.setContentsMargins(16, 14, 16, 16); lay.setSpacing(9)
        title = QtWidgets.QLabel("ENCODER MAINTENANCE"); title.setProperty("role", "celltitle")
        lay.addWidget(title)
        lay.addWidget(QtWidgets.QLabel("Set Datum Shift  ·  TW[18]  (단일회전 절대위치 → 값)"))
        edit = QtWidgets.QLineEdit("0")
        lay.addWidget(edit)
        btn_datum = QtWidgets.QPushButton("Set Datum Shift  (TW[18])")
        btn_mt = QtWidgets.QPushButton("Reset Multi-turn  (TW[19]=1)")
        btn_err = QtWidgets.QPushButton("Reset Errors  (TW[20]=1)")
        for b in (btn_datum, btn_mt, btn_err):
            lay.addWidget(b)
        lay.addWidget(self._hline())
        btn_zero = QtWidgets.QPushButton("Set Permanent Encoder Zero  ·  TW[18] + TW[19]")
        lay.addWidget(btn_zero)
        note = QtWidgets.QLabel("ⓘ EnDat 2.2는 Datum 임의값 허용(0=영점) · 타 센서는 0만(그 외 EC=99). "
                                "다회전 엔코더는 PX=다회전×counts+단일회전 → 완전 영점엔 TW[18]+TW[19] 둘 다 필요. "
                                "에러리셋은 소켓 1(TW[20]=1). 이 명령은 엔코더 기준을 직접 변경하므로 SV를 사용하지 않습니다.")
        note.setWordWrap(True); note.setProperty("role", "hint")
        lay.addWidget(note)

        def datum_op():
            return {"id": "set_datum_shift", "value": edit.text().strip() or "0"}
        # TW[19]/TW[20] take a SOCKET argument (=1 for socket 1), NOT a value — live-confirmed:
        # TW[19]=0 was rejected by the drive ("Drive error 21"); socket 1 is our feedback socket.
        mt_ops = [{"id": "reset_multiturn", "socket": 1}]
        err_ops = [{"id": "reset_errors", "socket": 1}]
        btn_datum.clicked.connect(lambda: self._enc_maint_send([datum_op()], "Set Datum Shift"))
        btn_mt.clicked.connect(lambda: self._enc_maint_send(list(mt_ops), "Reset Multi-turn"))
        btn_err.clicked.connect(lambda: self._enc_maint_send(list(err_ops), "Reset Errors"))
        btn_zero.clicked.connect(lambda: self._enc_maint_send([datum_op()] + list(mt_ops),
                                                              "Permanent Encoder Zero"))
        widgets = {"edit": edit, "btn_datum": btn_datum, "btn_mt": btn_mt, "btn_err": btn_err,
                   "btn_zero": btn_zero, "datum_op": datum_op,
                   "mt_ops": mt_ops, "err_ops": err_ops}
        return dlg, widgets

    def _open_encoder_maintenance(self):
        if self._guard_unsaved_vp_trial("엔코더 정비를 실행"):
            return
        if not (self.worker and self.worker.isRunning()):
            self._flash("연결 후 사용하세요."); return
        dlg, _w = self._encoder_maint_dialog()
        dlg.exec()

    def _enc_maint_send(self, operations, label):
        if self._guard_unsaved_vp_trial("엔코더 정비를 실행"):
            return
        if not (self.worker and self.worker.isRunning()):
            self._flash("연결 후 사용하세요."); return
        active_trial = getattr(self, "_vp_gain_trial", None)
        if active_trial is not None and (
                getattr(active_trial, "persistence_state", "RAM_TRIAL") != "RAM_TRIAL"
                or getattr(active_trial, "restore_only", False)):
            self._flash("현재 P2 시험은 검증 권한이 없습니다. Restore만 허용됩니다.")
            return
        try:
            commands = DriveWorker.encoder_operation_commands(operations)
        except (TypeError, ValueError) as exc:
            self._flash("엔코더 정비 입력 거부: %s" % exc)
            return
        preview = "\n".join("• %s" % c for c in commands) + "\n• SV: 실행하지 않음"
        btn = QtWidgets.QMessageBox.warning(
            self, "엔코더 정비 확인 (주의)",
            "%s 를 실행합니다 — 엔코더의 위치 기준(원점)을 변경합니다.\n"
            "모터 OFF에서만 실행 · 실제 장착 상태와 일치해야 합니다.\n\n%s\n\n진행할까요?" % (label, preview),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.worker.encoder_maintenance(operations)
        self._flash("%s 전송 중… (드라이브 응답 대기)" % label)

    def _on_tuning_gains(self, g):
        source = self.sender()
        if source is not None and source is not self.worker:
            return
        units = {
            "kp_cur": "V/A",
            "ki_cur": "Hz",
            "kp_vel": "A/(cnt/s)",
            "ki_vel": "Hz",
            "kp_pos": "1/s",
        }
        for key, unit in units.items():
            value = self._fmt(g.get(key), 4)
            self.tune_installed_gain_fields[key].setText(
                value if value == "—" else "%s %s" % (value, unit))

    # ---- ui state --------------------------------------------------------------------
    def _invalidate_tuning_result_authority(self):
        """Revoke target/profile-bound P1/P2 result authority.

        Saved JSON result paths remain as historical evidence, but their
        in-memory result objects cannot authorize Apply after a Motor profile
        mutation or connection-generation boundary.
        """
        self._at_result = None
        self._at_result_generation = None
        self._vp_result = None
        self._vp_result_generation = None
        self._vp_trial_verified_green = False
        self._vp_verified_trial = None
        self._vp_verified_generation = None
        for name in ("btn_tune_apply", "btn_tune_vp_apply"):
            if hasattr(self, name):
                getattr(self, name).setEnabled(False)

    def _advance_tuning_authority_generation(self):
        """Advance the connection/Motor-profile generation monotonically."""
        self._tuning_authority_generation = (
            getattr(self, "_tuning_authority_generation", 0) + 1)
        self._invalidate_tuning_result_authority()
        return self._tuning_authority_generation

    def _motion_signature_is_current(self):
        return bool(
            getattr(self, "_motion_signature_green", False)
            and isinstance(getattr(self, "_motion_signature_token", None), str)
            and self._motion_signature_token
            and getattr(self, "_motion_signature_generation", None) ==
            getattr(self, "_tuning_authority_generation", 0))

    def _set_connected_ui(self, on: bool):
        shutdown_pending = bool(
            getattr(self, "_connection_shutdown_pending", False))
        if not on:
            self._connection_access_mode = None
            self._invalidate_tuning_result_authority()
            self._motion_session_zero_confirmed = False
            self._reset_axis_safety_snapshot(
                "No current admitted connection snapshot")
            self._reset_axis_drive_mode(
                "No current admitted connection snapshot")
            self._reset_axis_current_reference(
                "No current admitted connection snapshot")
            self._reset_axis_digital_inputs(
                "No current admitted connection snapshot")
            self._reset_axis_digital_outputs(
                "No current admitted connection snapshot")
            for name in (
                    "chk_motion_operator", "chk_motion_estop",
                    "chk_motion_limits"):
                check = getattr(self, name, None)
                if check is not None:
                    check.setChecked(False)
        self._ui_connected = bool(on)
        persistence_locked = bool(
            getattr(self, "_persistence_recovery_unknown", False))
        p1_active = getattr(self, "_p1_gain_trial", None) is not None
        vp_active = getattr(self, "_vp_gain_trial", None) is not None
        trial_active = p1_active or vp_active
        generation = getattr(self, "_tuning_authority_generation", 0)
        motor_write_inflight = bool(
            getattr(self, "_motor_write_inflight", False))
        p1_trial_current = (
            not p1_active or getattr(self, "_p1_trial_generation", None) == generation)
        vp_trial_current = (
            not vp_active or getattr(self, "_vp_trial_generation", None) == generation)
        p1_state = (getattr(self._p1_gain_trial, "persistence_state", "RAM_TRIAL")
                    if p1_active else None)
        vp_state = (getattr(self._vp_gain_trial, "persistence_state", "RAM_TRIAL")
                    if vp_active else None)
        p1_restore_allowed = p1_active and p1_state in (
            "RAM_TRIAL", "RESTORE_FAILED", "AUTHORITY_INVALID")
        p1_save_allowed = (p1_active and p1_trial_current
                           and p1_state == "RAM_TRIAL"
                           and not getattr(self._p1_gain_trial, "restore_only", False)
                           and autotune_current.p1_gain_trial_has_save_authority(
                               self._p1_gain_trial))
        vp_restore_allowed = vp_active and vp_state in ("RAM_TRIAL", "RESTORE_FAILED")
        vp_normal_allowed = (vp_active and vp_trial_current
                             and vp_state == "RAM_TRIAL"
                             and not getattr(self._vp_gain_trial, "restore_only", False))
        dispatch_inflight = getattr(self, "_tune_dispatch_inflight", None) is not None
        telemetry_trusted = bool(
            on
            and getattr(self, "_connection_admitted", False)
            and getattr(self, "_telemetry_authoritative", False)
            and not getattr(self, "_energizing_state", False)
            and self.worker and self.worker.isRunning())
        mutation_trusted = bool(
            telemetry_trusted
            and getattr(self, "_connection_access_mode", None)
            == SUPERVISED_ACCESS_MODE
            and self._last_mo == 0)
        p1_model_ready = bool(self._p1_model_overrides_for_p2())
        self.btn_conn.setEnabled(not shutdown_pending)
        observe_only = bool(
            on and getattr(self, "_connection_access_mode", None)
            == OBSERVE_ONLY_ACCESS_MODE)
        if shutdown_pending:
            self.btn_conn.setText("Disconnecting")
            self.lbl_state.setText("DISCONNECTING")
        else:
            self.btn_conn.setText(
                "Disconnect · Read Only" if observe_only else
                ("Disconnect · Supervised Control" if on else
                 "Connect · %s" % _ACCESS_MODE_LABELS.get(
                     self.cmb_access_mode.currentData(), "Read Only")))
            self.lbl_state.setText(
                "ONLINE · READ ONLY" if observe_only else
                ("ONLINE · SUPERVISED" if on else "OFFLINE"))
        self.lbl_state.setProperty("on", "true" if on else "false")
        self._restyle(self.lbl_state)
        if hasattr(self, "btn_zero"):
            self.btn_zero.setEnabled(
                mutation_trusted and not trial_active and not persistence_locked)
        if hasattr(self, "btn_axis_refresh"):
            self.btn_axis_refresh.setEnabled(on)
        if hasattr(self, "btn_axis_digital_inputs_refresh"):
            self.btn_axis_digital_inputs_refresh.setEnabled(
                telemetry_trusted)
        if hasattr(self, "btn_axis_drive_mode_refresh"):
            self.btn_axis_drive_mode_refresh.setEnabled(
                telemetry_trusted)
        if hasattr(self, "btn_axis_current_reference_refresh"):
            self.btn_axis_current_reference_refresh.setEnabled(
                telemetry_trusted)
        if hasattr(self, "btn_axis_digital_outputs_refresh"):
            self.btn_axis_digital_outputs_refresh.setEnabled(
                telemetry_trusted)
        if hasattr(self, "btn_motion_stop"):
            self.btn_motion_stop.setEnabled(on)
        if hasattr(self, "btn_global_stop"):
            self.btn_global_stop.setEnabled(on)
        if hasattr(self, "btn_motor_write"):
            self.btn_motor_write.setEnabled(
                mutation_trusted and not trial_active and not persistence_locked
                and not motor_write_inflight and not dispatch_inflight)
        if hasattr(self, "btn_tune"):
            self.btn_tune.setEnabled(
                mutation_trusted and not trial_active and not dispatch_inflight
                and not motor_write_inflight and not persistence_locked)
        if hasattr(self, "btn_tune_signature"):
            self.btn_tune_signature.setEnabled(
                mutation_trusted and not trial_active and not dispatch_inflight
                and not motor_write_inflight and not persistence_locked)
        if hasattr(self, "btn_tune_vp"):
            self.btn_tune_vp.setEnabled(
                mutation_trusted and not trial_active and not dispatch_inflight
                and not motor_write_inflight and not persistence_locked
                and self._motion_signature_is_current() and p1_model_ready)
        if hasattr(self, "btn_tune_verify"):
            self.btn_tune_verify.setEnabled(
                mutation_trusted and not p1_active
                and (not vp_active or vp_normal_allowed)
                and self._motion_signature_is_current()
                and not dispatch_inflight and not motor_write_inflight
                and not persistence_locked)
        if hasattr(self, "btn_tune_apply"):
            applicable = (getattr(self, "_at_result", None) is not None and
                          getattr(self, "_at_result_generation", None) == generation and
                          self._at_result.status in
                          (autotune_current.GREEN, autotune_current.YELLOW))
            self.btn_tune_apply.setEnabled(False)
        if hasattr(self, "btn_tune_p1_restore"):
            self.btn_tune_p1_restore.setEnabled(
                mutation_trusted and p1_restore_allowed and not dispatch_inflight
                and not motor_write_inflight and not persistence_locked)
        if hasattr(self, "btn_tune_p1_save"):
            self.btn_tune_p1_save.setEnabled(
                mutation_trusted and p1_save_allowed and not dispatch_inflight
                and not motor_write_inflight and not persistence_locked)
        if hasattr(self, "btn_tune_vp_restore"):
            self.btn_tune_vp_restore.setEnabled(
                mutation_trusted and vp_restore_allowed and not dispatch_inflight
                and not motor_write_inflight and not persistence_locked)
        if hasattr(self, "btn_tune_vp_save"):
            self.btn_tune_vp_save.setEnabled(False)
        if hasattr(self, "btn_tune_vp_apply"):
            applicable = (getattr(self, "_vp_result", None) is not None and
                          getattr(self, "_vp_result_generation", None) == generation and
                          self._vp_result.status in
                          (autotune_velpos.GREEN, autotune_velpos.YELLOW))
            self.btn_tune_vp_apply.setEnabled(False)
        if persistence_locked and hasattr(self, "btn_tune_abort"):
            self.btn_tune_abort.setEnabled(False)
        if not on:
            self._motion_signature_green = False
            self._motion_signature_token = None
            self._motion_signature_generation = None
            self._motion_inflight = False
            self._motion_stop_pending = False
            for b in ("btn_tune_abort", "btn_tune_apply", "btn_tune_p1_restore",
                      "btn_tune_p1_save", "btn_tune_vp_apply",
                      "btn_tune_vp_restore", "btn_tune_vp_save"):
                if hasattr(self, b):
                    getattr(self, b).setEnabled(False)
        if hasattr(self, "motor_type_combo"):
            self.motor_type_combo.setEnabled(
                mutation_trusted and not persistence_locked)
        if hasattr(self, "motor_fields"):
            for k in ("peak", "cont", "maxspeed", "poles"):
                if k in self.motor_fields:
                    self.motor_fields[k].setEnabled(
                        mutation_trusted and not persistence_locked)
        for w in ("cmb_sensor", "cmb_commut"):
            if hasattr(self, w):
                # Readback selectors must not look write-capable before the
                # versioned Feedback registry/transaction exists.
                getattr(self, w).setEnabled(False)
        if hasattr(self, "btn_fb_write"):
            # A disabled button is not the safety boundary; _write_feedback is
            # independently fail-closed as well.  Never re-enable on connect.
            self.btn_fb_write.setEnabled(False)
        # Dynamic feedback widgets may include Encoder Maintenance actions.
        # Keep their rebuild authority aligned with the same supervised/MO=0
        # boundary as every other ordinary mutation control.
        self._fb_connected = mutation_trusted
        if hasattr(self, "fb_fields"):
            if "counts" in self.fb_fields:
                self.fb_fields["counts"].setEnabled(False)
        if hasattr(self, "_fb_dyn_fields"):
            for _label, (fld, w) in self._fb_dyn_fields.items():
                if fld["kind"] == feedback_spec.BTN:
                    w.setEnabled(mutation_trusted and not persistence_locked)
                elif fld["editable"]:
                    w.setEnabled(False)
        if not on:
            for m in (getattr(self, "m_pos", None), getattr(self, "m_perr", None),
                      getattr(self, "m_vel", None), getattr(self, "m_iq", None)):
                if m:
                    m.setText("—")
            for s in (getattr(self, "m_pos_sub", None), getattr(self, "m_vel_sub", None)):
                if s:
                    s.setText("")
            self._last_mo = None
            self.lbl_motor.setText(
                "SHUTDOWN IN PROGRESS · ENERGY STATE UNKNOWN"
                if shutdown_pending else "MOTOR STATE UNKNOWN")
            if shutdown_pending:
                self.lbl_motor.setToolTip(
                    "Worker cleanup is still pending; software state is not "
                    "proof of physical energy isolation")
            self.lbl_motor.setProperty("on", "false"); self._restyle(self.lbl_motor)
            self.cmb_port.setEnabled(not shutdown_pending)
            self.cmb_conn.setEnabled(not shutdown_pending)
            if hasattr(self, "cmb_access_mode"):
                self.cmb_access_mode.setEnabled(not shutdown_pending)
        else:
            self.cmb_port.setEnabled(False); self.cmb_conn.setEnabled(False)
            if hasattr(self, "cmb_access_mode"):
                self.cmb_access_mode.setEnabled(False)
        if hasattr(self, "btn_motion_run"):
            self._update_motion_controls()
        if hasattr(self, "btn_rec_immediate"):
            self._update_recorder_controls()
        if hasattr(self, "lbl_persistence_badge"):
            self._update_persistence_badge()

    @staticmethod
    def _fmt(val, ndigits=0):
        if val is None:
            return "—"
        if isinstance(val, float):
            return f"{val:.{ndigits}f}" if ndigits else f"{val:.0f}"
        return str(val)

    @staticmethod
    def _restyle(w):
        w.style().unpolish(w); w.style().polish(w)

    def _flash(self, msg: str):
        """Show a non-modal toast without adding a QMainWindow status-bar row."""
        # QMainWindow.statusBar() creates a layout-owned row lazily.  With the
        # production Malgun/theme metrics that row pushed the Angry Birds skin
        # from the declared 1366x820 bench contract to 1366x840.  This overlay
        # is mouse-transparent, bounded and outside the safety ribbon instead.
        parent = self.centralWidget() or self
        toast = getattr(self, "_toast_label", None)
        if toast is None:
            toast = QtWidgets.QLabel(parent)
            toast.setObjectName("statusToast")
            toast.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            toast.setWordWrap(True)
            toast.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            toast.setAttribute(
                QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            toast.setStyleSheet(
                "QLabel#statusToast{background:rgba(6,20,34,238);"
                "color:#e6f3ff;border:1px solid #3aaed8;border-radius:5px;"
                "padding:7px 11px;font-weight:700;}")
            toast.hide()
            self._toast_label = toast
            timer = QtCore.QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(toast.hide)
            self._toast_timer = timer

        text = str(msg)
        toast.setText(text)
        toast.setToolTip(text)
        available_width = max(260, min(760, parent.width() - 40))
        text_rect = toast.fontMetrics().boundingRect(
            QtCore.QRect(0, 0, max(120, available_width - 28), 120),
            int(QtCore.Qt.AlignmentFlag.AlignCenter
                | QtCore.Qt.TextFlag.TextWordWrap),
            text)
        width = max(260, min(available_width, text_rect.width() + 28))
        height = max(38, min(120, text_rect.height() + 18))
        toast.resize(width, height)
        toast.move(
            max(16, (parent.width() - width) // 2),
            max(16, parent.height() - height - 18))
        toast.raise_()
        toast.show()
        self._toast_timer.start(6000)

    def _confirm_unknown_persistence_exit(self, phases):
        """Warn before exit while preserving UNKNOWN in the durable ledger."""
        phase_text = "/".join(phases)
        status = (
            "⛔ %s 영구저장 상태 UNKNOWN — 종료해도 durable ledger와 READ-ONLY "
            "잠금은 유지됩니다. 다음 실행에서 UNKNOWN 이후 전원 OFF→ON(reset)을 현장에서 "
            "확인한 뒤 identity-bound query-only audit가 필요합니다." % phase_text)
        self.tune_status.setText(status)
        answer = QtWidgets.QMessageBox.warning(
            self, "영구저장 상태 UNKNOWN — 종료 주의",
            status + "\n\nUNKNOWN 상태를 해결하지 않고 정말 종료할까요?",
            QtWidgets.QMessageBox.StandardButton.Yes |
            QtWidgets.QMessageBox.StandardButton.Cancel,
            QtWidgets.QMessageBox.StandardButton.Cancel)
        return answer == QtWidgets.QMessageBox.StandardButton.Yes

    def closeEvent(self, ev):
        p1 = getattr(self, "_p1_gain_trial", None) is not None
        p2 = getattr(self, "_vp_gain_trial", None) is not None
        p1_unknown = (p1 and
            getattr(self._p1_gain_trial, "persistence_state", None) == "UNKNOWN")
        p2_unknown = (p2 and
            getattr(self._vp_gain_trial, "persistence_state", None) == "UNKNOWN")
        if (p1 and not p1_unknown) or (p2 and not p2_unknown):
            self._vp_trial_verified_green = False
            self._vp_verified_trial = None
            phase = "P1" if p1 else "P2"
            self._flash("미저장 %s RAM 게인이 있어 종료를 차단했습니다. Restore 후 종료하세요." % phase)
            self.tune_status.setText(
                "⚠ 종료 차단 — 미저장 %s RAM 게인을 먼저 복원하세요." % phase)
            ev.ignore()
            return
        unknown_phases = tuple(
            phase for phase, active in (("P1", p1_unknown), ("P2", p2_unknown))
            if active)
        if (unknown_phases
                and not self._confirm_unknown_persistence_exit(unknown_phases)):
            ev.ignore()
            return
        if self.worker and self.worker.isRunning():
            self._begin_connection_shutdown(
                "Window close requested; telemetry authority revoked")
            self.worker.stop()
            if not self.worker.wait(1500):
                self._flash(
                    "Shutdown is still in progress; window kept open until the "
                    "drive worker confirms cleanup")
                if hasattr(self, "tune_status"):
                    self.tune_status.setText(
                        "SHUTDOWN UNKNOWN — worker cleanup has not completed")
                ev.ignore()
                return
        super().closeEvent(ev)


def _smoke_feedback(app, win):
    """Headless acceptance: per-sensor EAS panel mirroring (no hardware, offscreen).

    Selects 5 representative sensors and asserts their EAS field labels/groups exist,
    then feeds the live-measured EnDat 2.2 snapshot through _on_feedback and checks
    the decoded UI values. Saves media/smoke_feedback_full.png. Returns 0/1.
    """
    sys.stdout.reconfigure(encoding="utf-8")
    win._fb_connected = True          # panel behaves as if connected (no drive I/O)
    win._nav_to(2)                    # Feedback page
    cases = [
        (30, "EnDat 2.2", ["Direction", "Read EnDat External Temperature",
                           "SW Sensor Resolution (Bits)", "High Bits Mask",
                           "Absolute Position Offset", "Encoder Maintenance"],
         ["General", "Sensor Parameters", "Serial Encoder Frame", "Resolution"]),
        (4, "Halls Only", ["Velocity FIR Filter Window", "Counts / Revolution"],
         ["General", "Sensor Parameters", "Resolution"]),
        (24, "BiSS General", ["Resolution Type", "BiSS Mode", "Warning Report",
                              "Protocol Total Bits", "Position LSB Number"],
         ["General", "Sensor Parameters", "Serial Encoder Frame", "Resolution"]),
        (18, "SSI", ["Sensor Data Presentation", "First Clock Delay (us)",
                     "Error Bit Number", "Protocol Total Bits"],
         ["General", "Sensor Parameters", "Serial Encoder Frame", "Resolution"]),
        (22, "Resolver", ["Resolver Pole Pairs", "Resolver Frequency [kHz]",
                          "Multiplication Factor", "Cycles / Revolution"],
         ["General", "Sensor Parameters", "Resolution"]),
    ]
    fails = []
    for sid, name, labels, groups in cases:
        ix = win.cmb_sensor.findData(sid)
        if ix < 0:
            fails.append("%s: combo missing id %d" % (name, sid)); continue
        win.cmb_sensor.setCurrentIndex(ix)
        app.processEvents()
        for lb in labels:
            ok = lb in win._fb_dyn_fields
            print("  [%s] %-38s %s" % (name, lb, "PASS" if ok else "FAIL"))
            if not ok:
                fails.append("%s: label missing %r" % (name, lb))
        if win._fb_group_titles != groups:
            fails.append("%s: groups %r != %r" % (name, win._fb_group_titles, groups))
        else:
            print("  [%s] groups %s PASS" % (name, "/".join(groups)))
    # unconfirmed-ID sensors present, write-blocked (data is the name string)
    for nm in ("Serial Absolute - IAI, Port A", "Serial Absolute - Mitsubishi, Port A",
               "Serial Exclusive #3"):
        ok = win.cmb_sensor.findData(nm) >= 0
        print("  [combo] %-38s %s" % (nm + " (ID 미확정)", "PASS" if ok else "FAIL"))
        if not ok:
            fails.append("combo missing unconfirmed sensor %r" % nm)
    assert win.cmb_sensor.count() >= 23, win.cmb_sensor.count()
    # live-measured EnDat 2.2 oracle snapshot -> decoded UI values
    snap = {"CA[54]": 0, "CA[36]": 50000000, "CA[35]": 8, "CA[8]": 0, "CA[60]": 8,
            "CA[91]": 0, "CA[71]": 0, "CA[59]": 19, "CA[61]": 3, "CA[58]": 0,
            "CA[62]": 16, "CA[18]": 65536}
    win._on_feedback({"sensor_id": 30, "commut_method": 5, "counts_rev": 65536,
                      "direction": 0, "pos_socket": 1, "vel_socket": 1,
                      "commut_socket": 1, "params": snap, "verified": True})
    app.processEvents()
    checks = [
        ("SW Sensor Resolution (Bits)", lambda w: w.text() == "16"),
        ("Input Glitch Filter (nanosecond)", lambda w: w.currentText() == "120"),
        ("Counts / Revolution", lambda w: w.text() == "65536"),
        ("Velocity FIR Filter Window", lambda w: w.text() == "Disabled"),
        ("Error Bitwise Mask", lambda w: w.text() == "0x0"),
        ("Read EnDat External Temperature", lambda w: w.text() == "No"),
        ("Rotary Multi-turn Resolution", lambda w: w.text() == "16"),
        ("High Bits Mask", lambda w: w.currentText() == "0"),
    ]
    for lb, pred in checks:
        fld_w = win._fb_dyn_fields.get(lb)
        ok = bool(fld_w) and pred(fld_w[1])
        print("  [EnDat decode] %-34s %s" % (lb, "PASS" if ok else "FAIL"))
        if not ok:
            fails.append("EnDat decode failed: %r" % lb)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "media", "smoke_feedback_full.png")
    win.grab().save(out)
    print("screenshot ->", out)
    print("SMOKE-FEEDBACK:", "GREEN (all assertions pass)" if not fails
          else "RED — %d failure(s): %s" % (len(fails), fails))
    return 0 if not fails else 1


class _OfflineSmokeWorker:
    """QThread-shaped, process-local smoke double; it owns no transport."""

    access_mode = SUPERVISED_ACCESS_MODE

    @staticmethod
    def isRunning():
        return True

    @staticmethod
    def stop():
        return None


def _smoke_authority_sample(sequence, *, mo=0):
    now = time.monotonic()
    return {
        "pos": 0, "vel": 0.0, "pos_err": 0.0, "iq": 0.0, "mo": mo,
        "_sample_started_monotonic": now,
        "_sample_finished_monotonic": now,
        "_sample_duration_s": 0.0,
        "telemetry_sequence": int(sequence),
        "telemetry_received_monotonic": now,
        "telemetry_valid": True,
        "session_coordinate_known": True,
        "encoder_maintenance_reconnect_required": False,
    }


def _smoke_admit_ui(win, worker=None):
    """Admit a complete synthetic UI envelope without opening a COM port."""
    win.worker = worker or _OfflineSmokeWorker()
    win._requested_connection_access_mode = SUPERVISED_ACCESS_MODE
    initial = _smoke_authority_sample(1, mo=0)
    win._on_connected({
        "fw": "SmokeFW", "pal": "90", "boot": "SmokeBoot",
        "target_type": "Gold Drive",
        "drive_identity": "elmo-sn4-sha256:" + ("0" * 64),
        "access_mode": SUPERVISED_ACCESS_MODE,
        "initial_telemetry": initial,
        "persistence_status": {
            "status": "CLEAR", "resolved": True,
            "detail": "offline smoke", "lock_active": False,
            "record_id": None, "phase": None, "other_active_count": 0,
            "ledger_error": None,
        },
    })
    return win._ui_connected and win._telemetry_authoritative


def _smoke_refresh_ui(win, sequence, *, mo=0):
    win._on_telemetry(_smoke_authority_sample(sequence, mo=mo))
    return win._telemetry_authoritative


def _smoke_autotune(app, win):
    """Headless acceptance for the auto-tune UI glue (no hardware, offscreen).

    Drives the DriveWorker->GUI signal handlers with synthetic progress + a GREEN
    result and asserts the stage wizard, measured/gain fields, and production
    Apply lock. Then feeds a RED result and asserts the lock remains. Saves a screenshot.
    """
    sys.stdout.reconfigure(encoding="utf-8")
    ac = autotune_current
    win._nav_to(3)                                    # Tuning page
    _smoke_admit_ui(win)
    app.processEvents()
    fails = []

    def chk(name, cond):
        print("  [autotune-ui] %-40s %s" % (name, "PASS" if cond else "FAIL"))
        if not cond:
            fails.append(name)

    chk("Run enabled on connect", win.btn_tune.isEnabled())
    chk("Apply disabled initially", not win.btn_tune_apply.isEnabled())

    # --- progress stream ---
    win._on_autotune_started()
    chk("Abort enabled while running", win.btn_tune_abort.isEnabled())
    for code, detail in [("P0", "연결·MO게이트 통과"), ("VALIDATE", "TS=100us CL[1]=70.7A"),
                         ("SNAPSHOT", "스냅숏 저장"), ("ENABLE", "서보온 확인"),
                         ("MEASURE_R", "R_pp=119.0 mΩ"), ("MEASURE_L", "L_pp=35.7 µH"),
                         ("DESIGN", "KP=0.0712 KI=812.9 PM=57.5°")]:
        win._on_autotune_progress(code, detail)
        app.processEvents()
    chk("status shows DESIGN detail", "DESIGN" in win.tune_status.text())

    # --- GREEN result ---
    res = ac.AutotuneResult(status=ac.GREEN, kp_v_per_a=0.071195, ki_hz=812.8695,
                            r_pp_ohm=0.118987, l_pp_h=35.42e-6, pm_deg=57.55)
    _smoke_refresh_ui(win, 2, mo=0)
    win._on_autotune_result(res)
    app.processEvents()
    g = win.tune_gain_fields
    chk("R_pp populated", g["r_pp"].text() != "—" and "Ω" in g["r_pp"].text())
    chk("L_pp populated (µH)", g["l_pp"].text() != "—" and "µH" in g["l_pp"].text())
    chk("KP[1] populated", g["kp_cur"].text().startswith("0.0711") and "V/A" in g["kp_cur"].text())
    chk("KI[1] populated", g["ki_cur"].text().startswith("812") and "Hz" in g["ki_cur"].text())
    chk("PM populated", "°" in g["pm"].text())
    chk("Apply remains production-locked after GREEN",
        not win.btn_tune_apply.isEnabled()
        and "LOCKED" in win.btn_tune_apply.text())
    chk("Abort disabled after result", not win.btn_tune_abort.isEnabled())
    chk("stages 0..2 all done (●)", all("●" in win.tune_stage_lbls[i].text() for i in range(3)))
    chk("status shows GREEN", "GREEN" in win.tune_status.text())
    chk("result cached for candidate review", win._at_result is res)

    # --- RED result keeps Apply disabled ---
    win._on_autotune_result(ac.AutotuneResult(status=ac.RED, reason="SE 미주입 (U1)"))
    app.processEvents()
    chk("Apply disabled after RED", not win.btn_tune_apply.isEnabled())
    chk("status shows RED reason", "RED" in win.tune_status.text() and "U1" in win.tune_status.text())

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media", "smoke_autotune.png")
    # re-run GREEN so the screenshot shows the useful state
    win._on_autotune_result(res); app.processEvents()
    win.grab().save(out)
    print("screenshot ->", out)
    print("SMOKE-AUTOTUNE:", "GREEN (all assertions pass)" if not fails
          else "RED — %d failure(s): %s" % (len(fails), fails))
    return 0 if not fails else 1


def _smoke_velpos(app, win):
    """Headless acceptance for the Phase-2 (vel/pos) auto-tune GUI glue.

    Part A — WORKER GLUE: runs the real DriveWorker._run_velpos_autotune
    (exact production param construction: sleep_fn->msleep override,
    progress_fn/cancel_fn->signals) against the T3 VPSim plant and checks the
    P0..DONE progress stream + gain oracles.
    Part B — HANDLERS: drives the GUI slots with synthetic progress + GREEN
    result and asserts wizard stages 3..5, result fields, the production Apply
    lock, and that a RED result keeps Apply disabled. Saves a screenshot. No hardware.
    """
    sys.stdout.reconfigure(encoding="utf-8")
    fails = []

    def chk(name, cond):
        print("  [velpos-ui] %-46s %s" % (name, "PASS" if cond else "FAIL"))
        if not cond:
            fails.append(name)

    # ---- Part A: worker glue against the T3 sim ---------------------------------------
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests"))
    from test_autotune_velpos import VPSim

    class GlueWorker(DriveWorker):
        """DriveWorker with msleep mapped onto the sim clock (headless)."""
        def __init__(self, drive):
            super().__init__("SIM")
            self._drive = drive
            self._connection_identity_verified = True
            if not hasattr(drive, "read_telemetry"):
                def read_sim_telemetry():
                    now = time.monotonic()
                    return {
                        "pos": float(drive.p),
                        "vel": float(drive.v),
                        "pos_err": float(
                            drive.regs.get("PA", drive.p) - drive.p),
                        "iq": float(drive.i_act),
                        "mo": int(drive.regs.get("MO", 0)),
                        "_sample_started_monotonic": now,
                        "_sample_finished_monotonic": now,
                        "_sample_duration_s": 0.0,
                    }
                drive.read_telemetry = read_sim_telemetry
            original_command = drive.command

            def smoke_command(command, *args, **kwargs):
                name = str(command).strip().rstrip(";").strip().upper()
                if name == "ST" and not kwargs.get("allow_motion", False):
                    kwargs["allow_motion"] = True
                if name == "MS":
                    return "3" if int(drive.regs.get("MO", 0)) == 0 else "2"
                if name == "ID":
                    return "0"
                return original_command(command, *args, **kwargs)

            drive.command = smoke_command

        def msleep(self, ms):
            self._drive.advance(ms / 1000.0)

    sim = VPSim()
    w = GlueWorker(sim)
    codes, results, started = [], [], []
    w.velpos_started.connect(lambda: started.append(1))
    w.velpos_progress.connect(lambda c, d: codes.append(c))
    w.velpos_result.connect(results.append)
    # LIVE-BASELINE TRIPWIRE (2026-07-14 x3 incident): this smoke previously
    # overwrote .omc/state/autotune_ka_baseline.json with its synthetic K_a
    # (5.77e6) — the kernel now quarantines VPSim (is_synthetic) persistence
    # into .omc/state/synthetic; assert the LIVE file is untouched.
    _bl_path = os.path.join(".omc", "state", "autotune_ka_baseline.json")
    _bl_before = open(_bl_path, "rb").read() if os.path.exists(_bl_path) else None
    w._run_velpos_autotune(sim, {"ramp_frac": 0.4})   # UI override path
    _bl_after = open(_bl_path, "rb").read() if os.path.exists(_bl_path) else None
    chk("synthetic run leaves LIVE baseline untouched", _bl_before == _bl_after)
    chk("glue: started emitted", len(started) == 1)
    need = ["P0", "VALIDATE", "SNAPSHOT", "ENABLE", "BREAKAWAY", "UNIT_DIAG",
            "PROBE", "SIZING", "IDENT_KA", "IDENT_FRICTION", "DESIGN", "DONE"]
    chk("glue: progress P0..DONE stream", all(c in codes for c in need))
    res_glue = results[0] if results else None
    chk("glue: result GREEN", res_glue is not None
        and res_glue.status == autotune_velpos.GREEN)
    chk("glue: KP[2] oracle <=3%", res_glue is not None
        and abs(res_glue.kp_vel / 7.896e-5 - 1.0) <= 0.03)
    chk("glue: KI[2]/KP[3] deterministic", res_glue is not None
        and abs(res_glue.ki_vel_hz / 10.70 - 1.0) <= 0.005
        and abs(res_glue.kp_pos / 85.2 - 1.0) <= 0.005)
    chk("glue: sim motor left OFF", sim.regs["MO"] == 0)
    chk("glue: ramp_frac=0.4 flowed to kernel (i_cap evidence)",
        res_glue is not None
        and abs(res_glue.evidence["breakaway"]["i_cap_a"] - 0.4 * 21.2132) < 0.05)
    chk("glue: persistence quarantined (synthetic evidence)",
        res_glue is not None
        and str(res_glue.evidence.get("synthetic_quarantine", ""))
        .endswith(autotune_velpos.SYNTHETIC_SUBDIR))

    # ---- Part A1b: standalone commutation-signature worker glue -----------------------
    sim_sig = VPSim(i_c=0.6, vel_noise=0.0)
    w_sig = GlueWorker(sim_sig)
    sig_results = []
    w_sig.velpos_result.connect(sig_results.append)
    w_sig._run_velpos_autotune(sim_sig, {
        "signature_only": True, "signature_cap_a": 1.30,
        "signature_i_min_a": 0.50, "signature_i_max_a": 1.30})
    sig_res = sig_results[0] if sig_results else None
    sig_cmds = [c.replace(" ", "").upper() for c, _a in sim_sig.log]
    sig_tc = [abs(float(c.split("=", 1)[1])) for c in sig_cmds
              if c.startswith("TC=")]
    chk("signature glue: GREEN", sig_res is not None
        and sig_res.status == autotune_velpos.GREEN)
    chk("signature glue: absolute cap <=1.30 A",
        bool(sig_tc) and max(sig_tc) <= 1.30 + 1e-9)
    chk("signature glue: no JV/BG/UM3 continuation",
        "BG" not in sig_cmds and "UM=3" not in sig_cmds
        and not any(c.startswith("JV") for c in sig_cmds))
    chk("signature glue: final TC=0/MO=0", sig_res is not None
        and sig_res.evidence["final_state"]["pass"]
        and sim_sig.regs["MO"] == 0)
    sim_sig_red = VPSim(i_c=2.0, vel_noise=0.0)
    w_sig_red = GlueWorker(sim_sig_red)
    sig_red_results = []
    w_sig_red.velpos_result.connect(sig_red_results.append)
    w_sig_red._run_velpos_autotune(sim_sig_red, {
        "signature_only": True, "signature_cap_a": 1.30,
        "signature_i_min_a": 0.50, "signature_i_max_a": 1.30})
    sig_red = sig_red_results[0] if sig_red_results else None
    chk("signature glue: RED still records final TC=0/MO=0",
        sig_red is not None and sig_red.status == autotune_velpos.RED
        and sig_red.evidence["final_state"]["pass"]
        and sim_sig_red.regs["MO"] == 0)

    # ---- Part A2: F2/G5 verify-run worker glue ------------------------------------------
    sim2 = VPSim()
    w2 = GlueWorker(sim2)
    v_started, v_results = [], []
    w2.verify_started.connect(lambda: v_started.append(1))
    w2.verify_result.connect(v_results.append)
    trial_result = autotune_velpos.AutotuneVPResult(
        status=autotune_velpos.GREEN, kp_vel=7.896e-5,
        ki_vel_hz=10.70, kp_pos=85.2)
    trial_ok, trial_msg, gain_trial = autotune_velpos.begin_gain_trial_vp(
        sim2, trial_result)
    chk("trial glue: RAM apply succeeds without SV", trial_ok and gain_trial is not None
        and not any(c == "SV" for c, _ in sim2.log))
    w2._run_verify_vp(sim2, ({}, gain_trial))
    _bl_after2 = (open(_bl_path, "rb").read()
                  if os.path.exists(_bl_path) else None)
    chk("verify glue: started emitted", len(v_started) == 1)
    res_v = v_results[0] if v_results else None
    chk("verify glue: GREEN on nominal plant", res_v is not None
        and res_v.status == autotune_velpos.GREEN)
    chk("verify glue: ladder 300+900 both ran", res_v is not None
        and [s["rpm"] for s in res_v.evidence["verify"]["steps"]]
        == [300.0, 900.0])
    chk("verify glue: overshoot in design band (<15%)", res_v is not None
        and all(s["overshoot_frac"] < 0.15
                for s in res_v.evidence["verify"]["steps"]))
    chk("verify glue: motor left OFF", sim2.regs["MO"] == 0)
    chk("verify glue: GREEN trial remains unsaved",
        res_v is not None
        and res_v.evidence["gain_trial_restore"]["required"] is False
        and not any(c == "SV" for c, _ in sim2.log))
    chk("verify glue: result json quarantined", res_v is not None
        and autotune_velpos.SYNTHETIC_SUBDIR in res_v.evidence["result_path"])
    chk("verify glue: LIVE baseline still untouched", _bl_before == _bl_after2)

    # ---- Part B: GUI handlers -----------------------------------------------------------
    ac = autotune_velpos
    # smoke-only: synthetic Part-B results must not pollute the LIVE result
    # snapshots (.omc/state/autotune_vp_result_*.json) — stub the dump on this
    # window instance (GUI logic itself unchanged)
    win._dump_velpos_result = lambda res: None
    win._nav_to(3)                                    # Tuning page
    _smoke_admit_ui(win)
    smoke_sequence = 1

    def refresh_smoke_authority():
        nonlocal smoke_sequence
        smoke_sequence += 1
        return _smoke_refresh_ui(win, smoke_sequence, mo=0)
    app.processEvents()
    chk("Run Signature enabled on connect", win.btn_tune_signature.isEnabled())
    chk("Phase 2 locked until current signature + P1 model",
        not win.btn_tune_vp.isEnabled())
    chk("Verify locked until current commutation signature",
        not win.btn_tune_verify.isEnabled())
    chk("Apply P2 disabled initially", not win.btn_tune_vp_apply.isEnabled())
    chk("P1/P2 production Apply/Save vocabulary is visibly locked",
        win.btn_tune_apply.text() == "Apply P1 → RAM (LOCKED)"
        and win.btn_tune_p1_restore.text() == "Restore P1 → Original"
        and win.btn_tune_p1_save.text() == "Save P1 → SV (LOCKED)"
        and win.btn_tune_vp_apply.text() == "Apply P2 → RAM (LOCKED)"
        and win.btn_tune_vp_save.text() == "Save P2 → SV (LOCKED)")
    p1_gui_trial = autotune_current.GainTrialP1(
        original={"KP[1]": 0.06, "KI[1]": 700.0},
        applied={"KP[1]": 0.0712, "KI[1]": 812.9})
    p1_gui_trial.persistence_state = "RAM_TRIAL"
    win._on_current_gain_action("begin", True, "P1 RAM trial", p1_gui_trial)
    win._set_connected_ui(True)
    chk("P1 trial is Restore-only and locks motion/config",
        win.btn_tune_p1_restore.isEnabled() and not win.btn_tune_p1_save.isEnabled()
        and not win.btn_tune_vp.isEnabled() and not win.btn_zero.isEnabled())
    p1_gui_trial.persistence_state = "UNKNOWN"
    win._on_current_gain_action(
        "commit", False, "simulated SV response loss", p1_gui_trial)
    win._set_connected_ui(True)
    chk("P1 UNKNOWN disables retry/restore and all normal writes",
        not win.btn_tune_p1_restore.isEnabled()
        and not win.btn_tune_p1_save.isEnabled()
        and not win.btn_tune.isEnabled() and not win.btn_zero.isEnabled()
        and "UNKNOWN" in win.tune_status.text())
    p1_gui_trial.persistence_state = "RAM_TRIAL"
    win._on_current_gain_action("restore", True, "P1 rollback verified", p1_gui_trial)
    win._set_connected_ui(True)
    chk("P1 restore clears transaction controls",
        win._p1_gain_trial is None and not win.btn_tune_p1_restore.isEnabled()
        and not win.btn_tune_p1_save.isEnabled())
    chk("BA cap default = 0.2", abs(win._velpos_overrides()["ramp_frac"] - 0.2) < 1e-9)
    win.cmb_ba_cap.setCurrentIndex(1)
    chk("BA cap select -> 0.4", abs(win._velpos_overrides()["ramp_frac"] - 0.4) < 1e-9)
    win.cmb_ba_cap.setCurrentIndex(0)
    win._vp_signature_run = True
    win._on_velpos_started()
    chk("signature UI: Abort enabled", win.btn_tune_abort.isEnabled())
    chk("signature UI: dedicated status", "커뮤테이션 서명" in win.tune_status.text())
    refresh_smoke_authority()
    win._on_velpos_result(sig_res)
    app.processEvents()
    chk("signature UI: result never enables Apply P2",
        not win.btn_tune_vp_apply.isEnabled() and win._vp_result is None)
    chk("signature UI: verdict and i_ba shown",
        "GREEN" in win.tune_status.text() and "i_ba=" in win.tune_status.text())
    win._vp_signature_run = True
    win._on_velpos_result(sig_red)
    app.processEvents()
    chk("signature UI: RED shows verified final TC=0/MO=0",
        "RED" in win.tune_status.text()
        and "MO=0" in win.tune_status.text()
        and "TC=0" in win.tune_status.text())
    win._set_connected_ui(True)
    win._on_velpos_started()
    chk("Abort enabled while running", win.btn_tune_abort.isEnabled())
    chk("stage 3 active on start", "◆" in win.tune_stage_lbls[3].text())
    for code, detail in [("P0", "연결·MO게이트"), ("VALIDATE", "G0 통과"),
                         ("SNAPSHOT", "스냅숏"), ("ENABLE", "통전"),
                         ("PROBE", "K_a 프로브"), ("SIZING", "Tp"),
                         ("IDENT_KA", "K_a=5.80e6"),
                         ("IDENT_FRICTION", "B, I_c")]:
        win._on_velpos_progress(code, detail)
        app.processEvents()
    chk("stage 3 done after ENABLE+", "●" in win.tune_stage_lbls[3].text())
    chk("stage 4 active during ident", "◆" in win.tune_stage_lbls[4].text())
    win._on_velpos_progress("DESIGN", "KP[2]=7.888e-5 PM=67.7°")
    app.processEvents()
    chk("stage 5 active at DESIGN", "◆" in win.tune_stage_lbls[5].text())
    res = ac.AutotuneVPResult(status=ac.GREEN, kp_vel=7.888e-5, ki_vel_hz=10.700,
                              kp_pos=85.211, k_a=5.7998e6, b_visc=9.986e-8,
                              i_c=0.2003, pm_vel_deg=67.66, gm_db=15.04,
                              pm_pos_deg=81.66)
    refresh_smoke_authority()
    win._on_velpos_result(res)
    app.processEvents()
    g = win.tune_gain_fields
    chk("K_a populated", g["k_a"].text().startswith("5.7998e+06")
        or "5.79" in g["k_a"].text())
    chk("B populated", "A/(cnt/s)" in g["b_visc"].text())
    chk("I_c populated", g["i_c"].text().startswith("0.2003"))
    chk("KP[2] populated", g["kp_vel"].text().startswith("7.888e-05"))
    chk("KI[2] populated", g["ki_vel"].text().startswith("10.7"))
    chk("KP[3] populated", g["kp_pos"].text().startswith("85.211"))
    chk("PM vel populated (GM 병기)", "°" in g["pm_vel"].text()
        and "GM" in g["pm_vel"].text())
    chk("PM pos populated", "°" in g["pm_pos"].text())
    chk("Apply P2 remains production-locked after GREEN",
        not win.btn_tune_vp_apply.isEnabled())
    chk("Abort disabled after result", not win.btn_tune_abort.isEnabled())
    chk("stages 3..5 all done (●)",
        all("●" in win.tune_stage_lbls[i].text() for i in (3, 4, 5)))
    chk("status shows GREEN", "GREEN" in win.tune_status.text())
    chk("result cached as a review-only candidate", win._vp_result is res)
    # RED result must re-disable Apply (Phase-1 bug-fix carried over)
    win._on_velpos_result(ac.AutotuneVPResult(status=ac.RED, reason="G4 실패 (모의)"))
    app.processEvents()
    chk("Apply P2 disabled after RED", not win.btn_tune_vp_apply.isEnabled())
    chk("status shows RED reason", "RED" in win.tune_status.text()
        and "G4" in win.tune_status.text())

    # ---- Part B2: verify-run handlers ----------------------------------------------------
    win._set_connected_ui(True)                   # re-ground: connected state
    win._on_motion_authority(False, "smoke: signature revoked")
    chk("Run Verify remains locked without current signature",
        not win.btn_tune_verify.isEnabled())
    win._on_motion_authority(True, "smoke: current signature GREEN")
    chk("Run Verify enabled only with current signature",
        win.btn_tune_verify.isEnabled())
    first_claim = win._claim_tune_dispatch("p2")
    second_claim = win._claim_tune_dispatch("verify")
    chk("GUI dispatch lock rejects rapid duplicate tune/verify",
        first_claim and not second_claim
        and win._tune_dispatch_inflight == "p2")
    win._release_tune_dispatch("p2")
    win._set_connected_ui(True)
    win._on_verify_started()
    chk("verify: run buttons locked while running",
        not win.btn_tune_verify.isEnabled() and not win.btn_tune_vp.isEnabled()
        and not win.btn_tune.isEnabled())
    chk("verify: Abort enabled while running", win.btn_tune_abort.isEnabled())
    refresh_smoke_authority()
    win._on_verify_result(res_v)
    app.processEvents()
    chk("verify: status shows verdict+metrics",
        "GREEN" in win.tune_status.text() and "OS" in win.tune_status.text()
        and "I_ss" in win.tune_status.text())
    chk("verify: Abort disabled after result",
        not win.btn_tune_abort.isEnabled())
    # (button re-enable follows worker liveness — same convention as Phase 2;
    # headless smoke has no live worker, so no assertion on the enabled state)

    # ---- Part B3: explicit RAM -> GREEN -> SV/restore button gating --------------------
    gui_trial = autotune_velpos.GainTrialVP(
        original={"KP[2]": 0.000153, "KI[2]": 20.0, "KP[3]": 180.0},
        applied={"KP[2]": 0.000166, "KI[2]": 10.7, "KP[3]": 85.2114})
    win._on_velpos_gain_action("begin", True, "RAM trial", gui_trial)
    win._set_connected_ui(True)
    chk("trial UI: Restore enabled, Save disabled",
        win.btn_tune_vp_restore.isEnabled() and not win.btn_tune_vp_save.isEnabled())
    chk("trial UI: tune/SV-capable P1 actions locked",
        not win.btn_tune_vp.isEnabled() and not win.btn_tune_apply.isEnabled())
    trial_green = autotune_velpos.AutotuneVPResult(
        status=autotune_velpos.GREEN,
        evidence={"gain_trial_restore": {"required": False, "pass": None},
                  "verify": (res_v.evidence or {}).get("verify", {})})
    foreign_trial = autotune_velpos.GainTrialVP(
        original=dict(gui_trial.original), applied=dict(gui_trial.applied))
    foreign_token = autotune_velpos.GainVerificationVP(
        trial=foreign_trial,
        applied=tuple((name, float(foreign_trial.applied[name]))
                      for name in autotune_velpos.VP_GAIN_NAMES))
    foreign_trial.verification = foreign_token
    trial_green.gain_trial_verification = foreign_token
    win._claim_tune_dispatch("verify", foreign_trial)
    win._on_verify_result(trial_green)
    win._set_connected_ui(True)
    chk("trial UI: foreign GREEN cannot authorize current Save",
        not win.btn_tune_vp_save.isEnabled()
        and win._vp_verified_trial is None)
    current_token = autotune_velpos.GainVerificationVP(
        trial=gui_trial,
        applied=tuple((name, float(gui_trial.applied[name]))
                      for name in autotune_velpos.VP_GAIN_NAMES))
    gui_trial.verification = current_token
    trial_green.gain_trial_verification = current_token
    win._claim_tune_dispatch("verify", gui_trial)
    win._on_verify_result(trial_green)
    win._set_connected_ui(True)
    chk("trial UI: production Save remains locked after GREEN",
        not win.btn_tune_vp_save.isEnabled() and win.btn_tune_vp_restore.isEnabled()
        and win._vp_verified_trial is gui_trial)
    gui_trial.persistence_state = "UNKNOWN"
    win._on_velpos_gain_action(
        "commit", False, "simulated SV response loss", gui_trial)
    win._set_connected_ui(True)
    chk("trial UI: P2 UNKNOWN blocks verify/restore/save",
        not win.btn_tune_verify.isEnabled()
        and not win.btn_tune_vp_restore.isEnabled()
        and not win.btn_tune_vp_save.isEnabled()
        and "UNKNOWN" in win.tune_status.text())
    gui_trial.persistence_state = "RAM_TRIAL"
    win._on_velpos_gain_action("restore", True, "rollback verified", gui_trial)
    win._set_connected_ui(True)
    chk("trial UI: successful restore clears trial controls",
        win._vp_gain_trial is None and not win.btn_tune_vp_restore.isEnabled()
        and not win.btn_tune_vp_save.isEnabled())

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "media", "smoke_velpos.png")
    win._on_velpos_result(res); app.processEvents()   # screenshot in useful state
    win.grab().save(out)
    print("screenshot ->", out)
    print("SMOKE-VELPOS:", "GREEN (all assertions pass)" if not fails
          else "RED — %d failure(s): %s" % (len(fails), fails))
    return 0 if not fails else 1


def _smoke_encoder(app, win):
    """Headless acceptance for Encoder Maintenance wiring (no hardware, offscreen).

    Builds the dialog (no exec), asserts the EAS-parity controls and the exact
    grounded command strings, and checks the worker queues the right job payload.
    """
    sys.stdout.reconfigure(encoding="utf-8")
    fails = []

    def chk(name, cond):
        print("  [encoder-ui] %-44s %s" % (name, "PASS" if cond else "FAIL"))
        if not cond:
            fails.append(name)

    dlg, w = win._encoder_maint_dialog()
    app.processEvents()
    chk("dialog builds", dlg is not None)
    chk("has datum input default 0", w["edit"].text() == "0")
    chk("Set Datum / Multi / Errors / Zero buttons", all(w[k] is not None
        for k in ("btn_datum", "btn_mt", "btn_err", "btn_zero")))
    chk("TW[18] datum op (default 0)",
        DriveWorker.encoder_operation_commands([w["datum_op"]()]) == ["TW[18]=0"])
    w["edit"].setText("123")
    chk("TW[18] datum op (value)",
        DriveWorker.encoder_operation_commands([w["datum_op"]()]) == ["TW[18]=123"])
    # TW[19]/TW[20] use a socket arg =1 (TW[19]=0 was rejected live with Drive error 21)
    chk("Reset Multi-turn = TW[19]=1 (socket)",
        DriveWorker.encoder_operation_commands(w["mt_ops"]) == ["TW[19]=1"])
    chk("Reset Errors = TW[20]=1 (socket)",
        DriveWorker.encoder_operation_commands(w["err_ops"]) == ["TW[20]=1"])

    # worker queues the right payloads (thread not started)
    wk = DriveWorker("COM_TEST")
    zero_ops = [{"id": "set_datum_shift", "value": 0},
                {"id": "reset_multiturn", "socket": 1}]
    wk.encoder_maintenance(zero_ops)
    job = wk._jobs[-1]
    chk("worker queues structured encoder_maint job",
        job == ("encoder_maint", zero_ops))
    err_ops = [{"id": "reset_errors", "socket": 1}]
    wk.encoder_maintenance(err_ops)
    chk("encoder maintenance never queues SV option",
        wk._jobs[-1] == ("encoder_maint", err_ops) and "chk_sv" not in w)
    wk.soft_zero()
    chk("session zero uses structured guarded job", wk._jobs[-1] == ("soft_zero", None))

    class CommandLogLink:
        def __init__(self, pos=12345, fail_command=None):
            self.t = {"mo": 0, "vel": 0.0, "iq": 0.0, "pos": pos,
                      "pos_err": 0}
            self.log = []
            self.fail_command = fail_command

        def read_telemetry(self):
            return dict(self.t)

        def command(self, cmd):
            self.log.append(cmd)
            if cmd == self.fail_command:
                raise RuntimeError("negative control")
            if cmd == "TW[19]=1":
                self.t["pos"] = 0
            return ""

    enc = CommandLogLink()
    enc_msg, enc_after = DriveWorker._perform_encoder_maintenance(enc, zero_ops)
    chk("encoder ops execute whitelist and verify final PX",
        enc.log == ["TW[18]=0", "TW[19]=1"] and enc_after["pos"] == 0
        and "Final PX" in enc_msg)

    malicious = [{"id": "set_datum_shift", "value": "0;SV"}]
    evil = CommandLogLink()
    try:
        DriveWorker._perform_encoder_maintenance(evil, malicious)
        malicious_refused = False
    except ValueError:
        malicious_refused = True
    chk("malicious separator/SV rejected before drive I/O",
        malicious_refused and evil.log == [])

    fail_fast = CommandLogLink(fail_command="TW[19]=1")
    try:
        DriveWorker._perform_encoder_maintenance(
            fail_fast, zero_ops + [{"id": "reset_errors", "socket": 1}])
        stopped_on_first_failure = False
    except SessionCoordinateError:
        stopped_on_first_failure = True
    chk("encoder sequence fail-fast (no later command)",
        stopped_on_first_failure
        and fail_fast.log == ["TW[18]=0", "TW[19]=1"])

    class ZeroLink:
        def __init__(self, mo=0, vel=0.0, iq=0.0, pos=12345):
            self.t = {"mo": mo, "vel": vel, "iq": iq, "pos": pos,
                      "pos_err": 0}
            self.log = []

        def read_telemetry(self):
            return dict(self.t)

        def command(self, cmd):
            self.log.append(cmd)
            if cmd == "PX=0":
                self.t["pos"] = 0
            return ""

    zl = ZeroLink()
    zmsg, zafter = DriveWorker._perform_soft_zero(zl)
    chk("session zero gates then verifies PX=0 without SV",
        zafter["pos"] == 0 and zl.log == ["PX=0"] and "SV 미실행" in zmsg)
    try:
        DriveWorker._perform_soft_zero(ZeroLink(mo=1))
        zero_on_refused = False
    except RuntimeError:
        zero_on_refused = True
    chk("session zero refuses MO=1 before PX write", zero_on_refused)

    class ReadbackFailureLink(ZeroLink):
        def __init__(self):
            super().__init__(pos=9876)
            self.read_count = 0

        def read_telemetry(self):
            self.read_count += 1
            if self.read_count >= 2:
                raise RuntimeError("readback lost")
            return dict(self.t)

    rb = ReadbackFailureLink()
    try:
        DriveWorker._perform_soft_zero(rb)
        readback_unknown = False
    except SessionCoordinateError as exc:
        readback_unknown = exc.coordinate_unknown and "UNKNOWN" in str(exc)
    chk("PX write then readback failure reports UNKNOWN without blind restore",
        readback_unknown and rb.log == ["PX=0"])

    print("SMOKE-ENCODER:", "GREEN (all assertions pass)" if not fails
          else "RED — %d failure(s): %s" % (len(fails), fails))
    return 0 if not fails else 1


def _smoke_recorder(app, win):
    """Offscreen Recorder ribbon/page acceptance; never creates a DriveWorker."""
    fails = []

    def check(label, condition):
        if not condition:
            fails.append(label)

    app.processEvents()
    smoke_font_family = str(
        app.property("smokeEvidenceFontFamily") or "")
    check("offscreen evidence uses an installed readable font",
          bool(smoke_font_family)
          and QtGui.QFontInfo(win.rec_stats_table.font()).family()
          == smoke_font_family)

    class ConnectedStub:
        def __init__(self):
            self.started = None

        @staticmethod
        def isRunning():
            return True

        def start_recorder(self, request):
            self.started = request
            return 7

    _smoke_admit_ui(win, ConnectedStub())
    win._nav_to(5)
    names = ["Position", "Velocity", "Active Current [A]"]
    win._on_recorder_signals_result(names, "")
    for index in range(2):
        win.rec_signal_list.item(index).setCheckState(QtCore.Qt.CheckState.Checked)
    resolved = recorder_control.ResolvedRecorderRequest(
        signals=tuple(names[:2]),
        requested_resolution_us=200.0,
        actual_resolution_us=200.0,
        time_resolution=4,
        requested_record_time_s=0.0006,
        actual_record_time_s=0.0006,
        length_per_signal=3,
        total_buffer_samples=6,
        trigger="immediate")
    win._on_recorder_status("RECORDING", "synthetic offline lifecycle state")
    check("capture freezes exact signal selection", not win.rec_signal_list.isEnabled())
    check("capture freezes requested timing",
          not win.spn_rec_resolution.isEnabled() and not win.spn_rec_time.isEnabled())
    check("capture freezes workspace Open/Save",
          not win.btn_rec_open.isEnabled() and not win.btn_rec_save.isEnabled())
    check("Recorder Stop remains available while pending", win.btn_rec_stop.isEnabled())
    win._on_recorder_status("READY_TO_UPLOAD", "synthetic retryable ready state")
    check("ready state permits both Upload and Recorder Stop",
          win.btn_rec_upload.isEnabled() and win.btn_rec_stop.isEnabled())
    win._recorder_manifest_data = {
        "capture_id": "offline-smoke-capture-1", "completion": "VALIDATED",
        "signals": list(resolved.signals), "length_per_signal": 3,
        "actual_resolution_us": 200.0,
        "drive_identity": "sha256:offline-smoke-drive"}
    win._recorder_manifest_ui_generation = win._recorder_view_generation
    win._inject_recorder_data_for_offline_test(
        {"dt": 0.0002, "Position": [0.0, 1.0, 2.0],
         "Velocity": [3.0, 4.0, 5.0]}, resolved)
    win._on_recorder_status("COMPLETED", "synthetic terminal state")
    check("Recorder page selected", win.stack.currentIndex() == 5)
    check("exact personality names listed", win.rec_signal_list.count() == 3)
    check("advanced trigger locked", not win.btn_rec_trigger.isEnabled())
    check("multi-drive locked", not win.chk_rec_multi.isEnabled())
    check("Recorder stop and motion stop are visibly distinct",
          "Recorder" in win.btn_rec_stop.text()
          and "DRIVE" in win.btn_global_stop.text())
    app.processEvents()
    global_top_left = win.btn_global_stop.mapTo(win, QtCore.QPoint(0, 0))
    check("DRIVE STOP is outside horizontal Recorder scroll",
          not win.recorder_ribbon_scroll.isAncestorOf(win.btn_global_stop))
    check("DRIVE STOP is inside the default visible window",
          win.btn_global_stop.isVisibleTo(win)
          and global_top_left.x() >= 0
          and global_top_left.x() + win.btn_global_stop.width() <= win.width())
    activation_top_left = win.btn_rec_immediate.mapTo(win, QtCore.QPoint(0, 0))
    check("Recorder Activation is fixed outside horizontal scroll",
          not win.recorder_ribbon_scroll.isAncestorOf(win.btn_rec_immediate))
    check("Recorder Activation is visible without scrolling",
          win.btn_rec_immediate.isVisibleTo(win)
          and activation_top_left.x() >= 0
          and activation_top_left.x() + win.btn_rec_immediate.width() <= win.width())
    context_top_left = win.btn_rec_context.mapTo(win, QtCore.QPoint(0, 0))
    state_top_left = win.lbl_recorder_ribbon_state.mapTo(win, QtCore.QPoint(0, 0))
    check("Recorder context is fixed outside the scrollable menu strip",
          not win.recorder_menu_scroll.isAncestorOf(win.btn_rec_context))
    check("Recorder context and state are visible without menu scrolling",
          win.btn_rec_context.isVisibleTo(win)
          and win.lbl_recorder_ribbon_state.isVisibleTo(win)
          and context_top_left.x() >= 0
          and state_top_left.x() + win.lbl_recorder_ribbon_state.width() <= win.width())
    win._nav_to(0); app.processEvents()
    check("Application menus remain visible while Recorder context hides",
          not win.recorder_ribbon_scroll.isVisible()
          and win.recorder_ribbon_menu.isVisible()
          and win.eas_application_menu_row.isVisibleTo(win)
          and not win.btn_rec_context.isVisible()
          and not win.lbl_recorder_ribbon_state.isVisible()
          and not win.recorder_activation_group.isVisible())
    check("global DRIVE STOP remains visible outside Recorder page",
          win.btn_global_stop.isVisibleTo(win))
    win._nav_to(5)
    check("raw export becomes available after uploaded data",
          win.btn_rec_export.isEnabled())
    check("validated capture enables View Design",
          win.btn_rec_view_tab.isEnabled()
          and win._recorder_view_model is not None
          and win._recorder_view_model.x_s == (0.0, 0.0002, 0.0004))
    win._recorder_immediate_clicked()
    check("new capture clears old data, timing and provenance bundle",
          win._recorder_last_data is None
          and win._recorder_last_resolved is None
          and win._recorder_manifest_data is None)
    check("new capture disables export until its own upload completes",
          not win.btn_rec_export.isEnabled())
    check("new capture revokes old View Design authority",
          win._recorder_view_model is None and not win.btn_rec_view_tab.isEnabled())
    check("new capture clears derived Signal Statistics",
          win._recorder_statistics_model is None
          and win.rec_stats_table.rowCount() == 0
          and win.rec_range_values_table.rowCount() == 0
          and win._recorder_range_selection is None
          and not win.btn_rec_stats_calculate.isEnabled())
    check("new capture request was handed to the current worker",
          win.worker.started is not None)
    win._recorder_manifest_data = {
        "capture_id": "offline-smoke-capture-2", "completion": "VALIDATED",
        "worker_generation": 7,
        "signals": list(resolved.signals), "length_per_signal": 3,
        "actual_resolution_us": 200.0,
        "drive_identity": "sha256:offline-smoke-drive"}
    win._recorder_manifest_ui_generation = win._recorder_view_generation
    win._inject_recorder_data_for_offline_test(
        {"dt": 0.0002, "Position": [0.0, 1.0, 2.0],
         "Velocity": [3.0, 4.0, 5.0]}, resolved,
        {"capture_id": "offline-smoke-capture-2", "worker_generation": 7})
    win._on_recorder_status("COMPLETED", "synthetic terminal state")
    win.btn_rec_view_tab.click()
    check("dual local plot renders exact selected signals",
          win.recorder_page_stack.currentIndex() == 1
          and win.rec_view_lane_a.currentText() == "Position"
          and win.rec_view_lane_b.currentText() == "Velocity"
          and win.recorder_plot.view_model is win._recorder_view_model)
    check("local acquisition workspace schema explicit",
          recorder_control.WORKSPACE_SCHEMA.endswith("/v1"))
    check("local View layout schema migrated to v3",
          recorder_view.VIEW_LAYOUT_SCHEMA.endswith("/v3"))
    win.btn_rec_stats_calculate.click()
    check("full-capture Statistics label documented fields and local RMS",
          win._recorder_statistics_model is not None
          and win._recorder_statistics_model.binding
          == win._recorder_view_model.binding
          and win.rec_stats_table.rowCount() == 2
          and win.rec_stats_table.item(0, 0).text() == "Position"
          and win.rec_stats_table.item(0, 4).text() == "1"
          and win.rec_stats_table.item(0, 8).text() == "100"
          and win.rec_stats_table.horizontalHeaderItem(1).text()
          == "N (local samples)"
          and "Tolerance % STATIC-IL VERIFIED"
          in win.lbl_rec_stats_scope.text())
    win.edit_rec_time_start.setText("0")
    win.edit_rec_time_end.setText("0.0002")
    win.btn_rec_time_apply_all.click()
    check("Manual Time Zoom applies one shared X window to both charts",
          win.recorder_plot.layout_model.x_range_s == (0.0, 0.0002)
          and "MANUAL TIME" in win.lbl_rec_time_mode.text())
    current_before_fft = win._recorder_view_is_current
    win.btn_rec_view_fft.click()
    check("FFT uses the full immutable capture with a zero-based local scale",
          win.recorder_plot.layout_model.plot_mode == recorder_view.PLOT_MODE_FFT
          and win.recorder_plot.spectrum_model is not None
          and win.recorder_plot.spectrum_model.input_sample_count == 3
          and len(win.recorder_plot.spectrum_model.x_hz) == 2
          and "Y STARTS AT 0" in win.lbl_rec_plot_contract.text())
    check("FFT preserves Time viewport state and capture authority",
          win.recorder_plot.layout_model.x_range_s == (0.0, 0.0002)
          and win._recorder_view_is_current is current_before_fft
          and not win.btn_rec_time_apply_all.isEnabled())
    win.btn_rec_view_time.click()
    check("Time mode restores the saved manual viewport",
          win.recorder_plot.layout_model.plot_mode == recorder_view.PLOT_MODE_TIME
          and win.recorder_plot.layout_model.x_range_s == (0.0, 0.0002)
          and win.btn_rec_time_apply_all.isEnabled())
    win.btn_rec_time_full.click()
    check("Reset Full Time restores the immutable capture domain",
          win.recorder_plot.layout_model.x_range_s is None
          and "FULL TIME" in win.lbl_rec_time_mode.text())
    win.btn_rec_view_fft.click()
    win.btn_rec_stats_calculate.click()
    check("Statistics opens a dedicated read-only analysis view",
          win.rec_view_analysis_tabs.currentIndex() == 1
          and win.rec_stats_table.rowCount() == 2)
    win.btn_rec_view_time.click()
    win.spin_rec_range_start.setValue(0)
    win.spin_rec_range_end.setValue(1)
    win.btn_rec_range_calculate.click()
    check("A:B range binds exact endpoints and inclusive statistics",
          win._recorder_statistics_model is not None
          and win._recorder_statistics_model.scope == "sample_range"
          and win._recorder_statistics_model.selection.sample_count == 2
          and win.rec_range_values_table.rowCount() == 2
          and win.rec_range_values_table.item(0, 3).text() == "0"
          and win.rec_range_values_table.item(0, 6).text() == "1"
          and win.recorder_plot.sample_range_selection
          == win._recorder_statistics_model.selection
          and "INCLUSIVE" in win.lbl_rec_stats_scope.text())
    check("A/B selector advertises local mouse snap without EAS parity claim",
          "MOUSE DRAG" in win.lbl_rec_range_title.text()
          and "nearest visible original sample"
          in win.lbl_rec_range_title.toolTip().lower())
    geometry = win.recorder_plot._plot_geometry()
    if geometry is not None:
        x_min, x_max, lane_rects = geometry
        lane_rect = lane_rects[0]
        selection = win.recorder_plot.sample_range_selection
        b_x = win.recorder_plot._marker_x(
            selection.end_time_s, lane_rect, x_min, x_max)
        end_x = win.recorder_plot._marker_x(
            win._recorder_view_model.x_s[-1], lane_rect, x_min, x_max)
        lane_y = lane_rect.center().y()

        def marker_event(event_type, x_position, *, button, buttons):
            point = QtCore.QPointF(x_position, lane_y)
            return QtGui.QMouseEvent(
                event_type, point, point, button, buttons,
                QtCore.Qt.KeyboardModifier.NoModifier)

        win.recorder_plot.mousePressEvent(marker_event(
            QtCore.QEvent.Type.MouseButtonPress, b_x,
            button=QtCore.Qt.MouseButton.LeftButton,
            buttons=QtCore.Qt.MouseButton.LeftButton))
        win.recorder_plot.mouseMoveEvent(marker_event(
            QtCore.QEvent.Type.MouseMove, end_x,
            button=QtCore.Qt.MouseButton.NoButton,
            buttons=QtCore.Qt.MouseButton.LeftButton))
        win.recorder_plot.mouseReleaseEvent(marker_event(
            QtCore.QEvent.Type.MouseButtonRelease, end_x,
            button=QtCore.Qt.MouseButton.LeftButton,
            buttons=QtCore.Qt.MouseButton.NoButton))
    check("mouse B drag snaps and commits one valid inclusive result",
          win._recorder_statistics_model is not None
          and win._recorder_statistics_model.scope == "sample_range"
          and win._recorder_statistics_model.selection.start_index == 0
          and win._recorder_statistics_model.selection.end_index == 2
          and win.spin_rec_range_end.value() == 2
          and win.btn_rec_stats_export.isEnabled())
    with tempfile.TemporaryDirectory(prefix="angryyjh-recorder-smoke-") as folder:
        receipt = recorder_view.export_statistics_csv(
            os.path.join(folder, "statistics.csv"),
            win._recorder_view_model,
            win._recorder_statistics_model,
            authority=recorder_view.STATISTICS_AUTHORITY_CURRENT)
        check("statistics CSV is local, source-hashed and atomically published",
              receipt.row_count == 2
              and receipt.source_view_sha256
              == recorder_view.capture_view_sha256(win._recorder_view_model)
              and os.path.isfile(receipt.path))
    win.lbl_rec_view_status.setText(
        "DEMO · OFFLINE SMOKE · SYNTHETIC CAPTURE · NO HARDWARE I/O")
    win.lbl_rec_view_status.setStyleSheet(
        "color: #ffb454; font-weight: 800; background: #2a1d0b; "
        "border: 1px solid #a86f18; padding: 5px 8px;")
    win.lbl_rec_range_scope.setText(
        win.lbl_rec_range_scope.text().replace(
            "CURRENT", "DEMO / OFFLINE SMOKE"))
    win.lbl_rec_stats_scope.setText(
        win.lbl_rec_stats_scope.text().replace(
            "CURRENT", "DEMO / OFFLINE SMOKE"))
    win.resize(1600, 1050)
    win.repaint()
    win.recorder_page_stack.currentWidget().repaint()
    app.processEvents()
    app.processEvents()
    out = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "media", "smoke_recorder.png")
    win.grab().save(out)
    statistics_out = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "media",
        "smoke_recorder_statistics.png")
    win.recorder_page_stack.currentWidget().grab().save(statistics_out)
    win.rec_view_analysis_tabs.setCurrentIndex(0)
    win.repaint()
    win.recorder_page_stack.currentWidget().repaint()
    app.processEvents()
    app.processEvents()
    markers_out = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "media",
        "smoke_recorder_markers.png")
    # Use the full window for marker evidence so the global OFFLINE badge and
    # the synthetic-smoke banner remain attached to the chart image.
    marker_evidence = QtGui.QPixmap(win.size())
    marker_evidence.fill(win.palette().color(QtGui.QPalette.ColorRole.Window))
    win.render(marker_evidence)
    marker_evidence.save(markers_out)
    print("SMOKE-RECORDER:", "GREEN (all assertions pass)" if not fails
          else "RED - %d failure(s): %s" % (len(fails), fails))
    print("SMOKE-RECORDER image ->", out)
    print("SMOKE-RECORDER markers image ->", markers_out)
    print("SMOKE-RECORDER statistics image ->", statistics_out)
    return 0 if not fails else 1


def main():
    smoke = "--smoke" in sys.argv
    smoke_fb = "--smoke-feedback" in sys.argv
    smoke_at = "--smoke-autotune" in sys.argv
    smoke_enc = "--smoke-encoder" in sys.argv
    smoke_vp = "--smoke-velpos" in sys.argv
    smoke_rec = "--smoke-recorder" in sys.argv
    smoke_mode = bool(
        smoke or smoke_fb or smoke_at or smoke_enc or smoke_vp or smoke_rec)
    if smoke_mode:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication(sys.argv)
    if smoke_mode:
        # Make screenshot evidence deterministic and readable on the Windows
        # offscreen plugin instead of relying on QSS fallback-font selection.
        smoke_font_path = os.path.join(
            os.environ.get("WINDIR", r"C:\Windows"),
            "Fonts", "malgun.ttf")
        smoke_font_id = (
            QtGui.QFontDatabase.addApplicationFont(smoke_font_path)
            if os.path.isfile(smoke_font_path) else -1)
        smoke_families = (
            QtGui.QFontDatabase.applicationFontFamilies(smoke_font_id)
            if smoke_font_id >= 0 else [])
        smoke_font_family = smoke_families[0] if smoke_families else ""
        app.setProperty("smokeEvidenceFontFamily", smoke_font_family)
        if smoke_font_family:
            app.setFont(QtGui.QFont(smoke_font_family, 10))
        app.setStyleSheet(
            theme.STYLE + (
                '\n* { font-family: "%s"; }' % smoke_font_family
                if smoke_font_family else ""))
    else:
        app.setStyleSheet(theme.STYLE)
    win = MainWindow()
    win.show()
    if smoke_fb:
        return _smoke_feedback(app, win)
    if smoke_at:
        return _smoke_autotune(app, win)
    if smoke_enc:
        return _smoke_encoder(app, win)
    if smoke_vp:
        return _smoke_velpos(app, win)
    if smoke_rec:
        return _smoke_recorder(app, win)
    if smoke:
        # Exercise the same fail-closed admission envelope as a live worker,
        # using a process-local stub only.  This smoke path performs no I/O.
        class SmokeWorker:
            access_mode = OBSERVE_ONLY_ACCESS_MODE

            @staticmethod
            def isRunning():
                return True

            @staticmethod
            def stop():
                return None

        win.worker = SmokeWorker()
        win._requested_connection_access_mode = OBSERVE_ONLY_ACCESS_MODE
        now = time.monotonic()
        initial = {
            "pos": 0, "vel": 0.0, "pos_err": 0, "iq": 0.0, "mo": 0,
            "_sample_started_monotonic": now,
            "_sample_finished_monotonic": now,
            "_sample_duration_s": 0.0,
            "telemetry_sequence": 1,
            "telemetry_received_monotonic": now,
            "telemetry_valid": True,
            "session_coordinate_known": True,
            "encoder_maintenance_reconnect_required": False,
        }
        win._on_connected({
            "fw": "Twitter 01.01.16.00 08Mar2020B01G",
            "pal": "90",
            "boot": "DSP Boot 1.0.1.6",
            "target_type": "Gold Drive",
            "drive_identity": "elmo-sn4-sha256:" + ("0" * 64),
            "access_mode": OBSERVE_ONLY_ACCESS_MODE,
            "quiescent_state": {
                "MO": 0.0, "SO": 0.0, "VX": 0.0,
                "PS": -2.0, "MF": 0.0,
            },
            "persistence_status": {
                "status": "CLEAR", "resolved": True, "detail": "smoke",
                "lock_active": False, "record_id": None, "phase": None,
                "other_active_count": 0, "ledger_error": None,
            },
            "initial_telemetry": initial,
        })
        update = dict(initial)
        update.update({
            "pos": 12124061, "vel": 3932674.0, "iq": 0.124, "mo": 1,
            "telemetry_sequence": 2,
            "telemetry_received_monotonic": time.monotonic(),
        })
        win._on_telemetry(update)
        app.processEvents()
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media", "smoke_main.png")
        win.grab().save(out)
        accepted = bool(
            win._ui_connected and win._connection_admitted
            and win._telemetry_authoritative
            and win._last_telemetry_sequence == 2
            and win.lbl_state.text() == "ONLINE · READ ONLY"
            and win.lbl_motor.text() == "MOTOR ENABLED")
        print("SMOKE %s -> %s" % ("GREEN" if accepted else "RED", out))
        return 0 if accepted else 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
