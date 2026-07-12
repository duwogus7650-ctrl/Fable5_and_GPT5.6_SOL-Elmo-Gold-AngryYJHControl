"""Elmo Gold Control — mini-EAS desktop GUI (Made after EAS III).

First screens: connection + Single Axis Motion dashboard (read-only live telemetry),
built on the official Drive .NET Library transport (elmo_link) and the SDD PyQt6 shell.

Run:   python main.py
Smoke: python main.py --smoke     (offscreen render, no hardware)

Safety: this build is read-only telemetry. No motion/enable commands are issued.
"""
from __future__ import annotations

import sys
import os

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

APP_TITLE = "AngryYJH Control"
POLL_HZ = 5


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


# ---------------------------------------------------------------------------------------
# Drive worker — owns ALL drive I/O in one thread (pythonnet COM object is single-thread)
# ---------------------------------------------------------------------------------------
class DriveWorker(QtCore.QThread):
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
    encoder_maint_result = QtCore.pyqtSignal(bool, str)   # (ok, drive-response text)
    stopped = QtCore.pyqtSignal()

    def __init__(self, port: str, parent=None):
        super().__init__(parent)
        self.port = port
        self._run = True
        self._pending = collections.deque()   # one-shot commands from the GUI thread
        self._jobs = collections.deque()      # structured jobs (writes) from the GUI thread
        self._cancel_at = False               # operator-abort flag polled by the autotune

    def send_once(self, cmd: str):
        """Queue a single command to run in the worker thread (thread-safe)."""
        self._pending.append(cmd)

    def start_autotune(self, kw: dict):
        """Queue our own current-loop auto-tune (ENERGIZES the motor — caller gates)."""
        self._cancel_at = False
        self._jobs.append(("autotune", dict(kw)))

    def cancel_autotune(self):
        """Request a safe abort mid-tune (polled in autotune's _sleep -> SPEC §6 chain)."""
        self._cancel_at = True

    def apply_autotune_gains(self, result, persist: bool):
        """Queue writing a GREEN/YELLOW result's KP[1]/KI[1] to the drive (MO=0 gated)."""
        self._jobs.append(("autotune_apply", (result, bool(persist))))

    def encoder_maintenance(self, cmds, persist: bool):
        """Queue encoder-maintenance command(s) (TW[18]/TW[19]/TW[20]) in order.
        MO=0 gated in run(); the exact command + drive response is reported back."""
        self._jobs.append(("encoder_maint", (list(cmds), bool(persist))))

    def write_motor(self, writes: dict):
        """Queue a Motor Settings write (validated/converted by the caller)."""
        self._jobs.append(("motor_write", writes))

    def write_feedback(self, pairs):
        """Queue a Feedback/encoder write — ORDERED [(cmd, value)] (validated by caller)."""
        self._jobs.append(("feedback_write", pairs))

    def stop(self):
        self._run = False

    def run(self):
        link = ElmoLink(self.port)
        try:
            link.connect()
        except Exception as e:
            self.failed.emit(str(e))
            return
        # identity handshake (read-only)
        info = {}
        for key, cmd in (("fw", "VR"), ("pal", "VP"), ("boot", "VB")):
            try:
                info[key] = link.command(cmd)
            except Exception:
                info[key] = None
        info["target_type"] = "Gold Drive"
        self.connected.emit(info)
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

        interval = 1.0 / POLL_HZ
        try:
            while self._run:
                while self._pending:
                    c = self._pending.popleft()
                    try:
                        self.command_done.emit(c, str(link.command(c)))
                    except Exception as e:
                        self.command_done.emit(c, "ERR: %s" % e)
                while self._jobs:
                    kind, payload = self._jobs.popleft()
                    if kind == "motor_write":
                        try:
                            ok, msg = link.write_motor_params(payload)
                            self.write_result.emit(ok, msg)
                            if ok:
                                self.motor_params.emit(link.read_motor_params())
                        except Exception as e:
                            self.write_result.emit(False, "ERR: %s" % e)
                    elif kind == "feedback_write":
                        try:
                            # ordered pairs: MO=0 gate + CA[35]/[36] -> CA[41] re-issue + SV
                            ok, msg = link.write_feedback_params(payload)
                            self.write_result.emit(ok, msg)
                            if ok:
                                self.feedback.emit(link.read_feedback())
                        except Exception as e:
                            self.write_result.emit(False, "ERR: %s" % e)
                    elif kind == "autotune":
                        self._run_autotune(link, payload)
                    elif kind == "autotune_apply":
                        result, persist = payload
                        try:
                            ok, msg = autotune_current.apply_gains(link, result, persist=persist)
                        except Exception as e:
                            ok, msg = False, "적용 예외: %r" % e
                        self.autotune_applied.emit(ok, msg)
                        try:
                            self.tuning_gains.emit(link.read_tuning_gains())
                        except Exception:
                            pass
                    elif kind == "encoder_maint":
                        cmds, persist = payload
                        try:
                            mo = str(link.command("MO")).strip().rstrip(";").strip()
                            if mo == "1":
                                self.encoder_maint_result.emit(False, "모터 ON(MO=1) — STOP 후 실행하세요.")
                            else:
                                parts, ok_all = [], True
                                for c in cmds:                       # TW[..] are non-motion config
                                    try:
                                        resp = link.command(c)
                                        parts.append("%s  →  %s" % (c, resp if str(resp).strip() else "OK"))
                                    except Exception as e:           # per-command: keep going, show it
                                        ok_all = False
                                        parts.append("%s  →  실패: %s" % (c, e))
                                if persist:
                                    try:
                                        parts.append("SV  →  %s" % (link.command("SV") or "OK"))
                                    except Exception as e:
                                        ok_all = False
                                        parts.append("SV  →  실패: %s" % e)
                                self.encoder_maint_result.emit(ok_all, "\n".join(parts))
                                self.telemetry.emit(link.read_telemetry())   # refresh PX readout
                        except Exception as e:
                            self.encoder_maint_result.emit(False, "엔코더 정비 실패: %s" % e)
                self.telemetry.emit(link.read_telemetry())
                self.msleep(int(interval * 1000))
        finally:
            link.disconnect()
            self.stopped.emit()

    def _run_autotune(self, link, kw: dict):
        """Run the current-loop auto-tune in this thread, streaming progress to the GUI.

        sleep_fn -> QThread.msleep so timeouts advance in real time; progress_fn and
        cancel_fn bridge to Qt signals / the operator-abort flag. The module itself
        never raises (returns a RED result) and runs the SPEC §6 abort chain on cancel.
        """
        self.autotune_started.emit()
        params = autotune_current.AutotuneParams(
            sleep_fn=lambda s: self.msleep(int(max(s, 0.0) * 1000)),
            progress_fn=lambda code, detail: self.autotune_progress.emit(str(code), str(detail)),
            cancel_fn=lambda: self._cancel_at,
            **kw)
        try:
            res = autotune_current.run_current_autotune(link, params)
        except Exception as e:                       # module shouldn't raise; be safe
            res = autotune_current.AutotuneResult(
                status=autotune_current.RED, reason="worker 예외: %r" % e)
        self.autotune_result.emit(res)
        try:                                         # gains view reflects reality post-run
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


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1180, 740)
        self.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint)
        _icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spg_icon.ico")
        if os.path.isfile(_icon):
            self.setWindowIcon(QtGui.QIcon(_icon))
        self.worker: DriveWorker | None = None

        central = QtWidgets.QWidget(); central.setObjectName("central")
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(MacTitleBar(self, APP_TITLE))

        content = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(content); root.setContentsMargins(16, 14, 16, 16); root.setSpacing(14)
        root.addWidget(self._build_header())
        body = QtWidgets.QHBoxLayout(); body.setSpacing(14)
        body.addWidget(self._build_connection_card(), 0)
        body.addWidget(self._build_workspace(), 1)
        root.addLayout(body, 1)
        outer.addWidget(content, 1)

        self._set_connected_ui(False)

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
        bird = self._img_label("angry_bird.png", 78)
        if bird is not None:
            h.addWidget(bird)
        h.addStretch(1)
        self.lbl_state = QtWidgets.QLabel("OFFLINE"); self.lbl_state.setObjectName("pill")
        h.addWidget(self.lbl_state)
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

    # ---- connection ------------------------------------------------------------------
    def _build_connection_card(self):
        f = theme.HudCard(); f.setFixedWidth(340)
        v = QtWidgets.QVBoxLayout(f); v.setContentsMargins(16, 14, 16, 16); v.setSpacing(10)
        title = QtWidgets.QLabel("CONNECTION"); title.setProperty("role", "celltitle")
        v.addWidget(title)

        self.cmb_conn = QtWidgets.QComboBox()
        self.cmb_conn.addItems(["Direct Access USB", "Direct Access RS232",
                                "Direct Access UDP", "CAN (Kvaser)", "CAN Gateway (G-MAS)"])
        v.addLayout(self._row("Connection Type", self.cmb_conn))

        self.cmb_port = PortCombo(self.refresh_ports)
        btn_refresh = QtWidgets.QPushButton("⟳"); btn_refresh.setFixedWidth(38)
        btn_refresh.clicked.connect(self.refresh_ports)
        portrow = QtWidgets.QHBoxLayout(); portrow.setSpacing(6)
        portrow.addWidget(self.cmb_port, 1); portrow.addWidget(btn_refresh)
        v.addLayout(self._row("Serial Port", portrow))

        self.btn_conn = QtWidgets.QPushButton("Connect"); self.btn_conn.setObjectName("primary")
        self.btn_conn.clicked.connect(self.toggle_connect)
        v.addWidget(self.btn_conn)

        v.addWidget(self._hline())
        self.lbl_fw = self._kv(v, "Firmware")
        self.lbl_pal = self._kv(v, "PAL")
        self.lbl_boot = self._kv(v, "Boot")
        self.lbl_type = self._kv(v, "Target Type")
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
        self.lbl_motor = QtWidgets.QLabel("MOTOR DISABLED"); self.lbl_motor.setObjectName("pill")
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
        self.btn_zero = QtWidgets.QPushButton("Soft Zero  (세션 · PX=0)")
        self.btn_zero.clicked.connect(self.zero_position)
        actionrow.addWidget(self.btn_zero); actionrow.addStretch(1)
        v.addLayout(actionrow)
        note = QtWidgets.QLabel("Soft Zero (PX=0): 제어기 위치 카운터만 임시로 0 — 증분 엔코더용·세션 한정 "
                                "(모터 안 움직임). 절대 엔코더의 영구 원점은 Feedback 탭 → Encoder Maintenance "
                                "(Set Datum Shift + Reset Multi-turn).")
        note.setProperty("role", "hint"); note.setWordWrap(True)
        v.addWidget(note)
        v.addStretch(1)
        return f

    # ---- workspace: nav + stacked pages ----------------------------------------------
    def _build_workspace(self):
        wrap = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(wrap); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(10)
        nav = QtWidgets.QHBoxLayout(); nav.setSpacing(8)
        self.stack = QtWidgets.QStackedWidget()
        self._nav_btns = []
        pages = [("Motion", self._build_motion_card()),
                 ("Motor Settings", self._build_motor_page()),
                 ("Feedback", self._build_feedback_page()),
                 ("Tuning", self._build_tuning_page())]
        for i, (name, page) in enumerate(pages):
            b = QtWidgets.QPushButton(name); b.setCheckable(True)
            b.setStyleSheet("QPushButton{padding:7px 16px;} "
                            "QPushButton:checked{background:%s;color:#042435;border:none;font-weight:800;}"
                            % theme.INDIGO)
            b.clicked.connect(lambda _=False, ix=i: self._nav_to(ix))
            nav.addWidget(b); self._nav_btns.append(b)
            self.stack.addWidget(page)
        nav.addStretch(1)
        v.addLayout(nav); v.addWidget(self.stack, 1)
        self._nav_to(0)
        return wrap

    def _nav_to(self, ix):
        self.stack.setCurrentIndex(ix)
        for i, b in enumerate(self._nav_btns):
            b.setChecked(i == ix)

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
        self.btn_motor_write = QtWidgets.QPushButton("Write to Drive  (SV)")
        self.btn_motor_write.setObjectName("primary"); self.btn_motor_write.setEnabled(False)
        self.btn_motor_write.clicked.connect(self._write_motor)
        row.addWidget(self.btn_motor_write); row.addStretch(1)
        v.addLayout(row)
        note = QtWidgets.QLabel("쓰기는 모터 OFF(MO=0)에서만 · SV로 영구저장 · 모터 안 움직임 · "
                               "R/L/Ke는 드라이브에 없고 Current ID(Quick Tuning)가 산출하는 값")
        note.setProperty("role", "hint"); note.setWordWrap(True)
        v.addWidget(note); v.addStretch(1)
        return f

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

        lbl = QtWidgets.QLabel("Feedback Sensor Type  (CA[41])"); lbl.setProperty("role", "field")
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
        lc = QtWidgets.QLabel("Commutation Method  (CA[17])"); lc.setProperty("role", "field")
        self.cmb_commut = QtWidgets.QComboBox()
        for cid in sorted(feedback_spec.COMMUT_NAMES):
            self.cmb_commut.addItem("%s  ·  %d" % (feedback_spec.COMMUT_NAMES[cid], cid), cid)
        self.cmb_commut.setEnabled(False)
        v.addWidget(lc); v.addWidget(self.cmb_commut)
        # common (always-shown) fields
        self.fb_fields = {}
        common = [("counts", "Counts / Rev  (CA[18])", True),
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
        self.btn_fb_write = QtWidgets.QPushButton("Write to Drive  (SV)")
        self.btn_fb_write.setObjectName("primary"); self.btn_fb_write.setEnabled(False)
        self.btn_fb_write.clicked.connect(self._write_feedback)
        row.addWidget(self.btn_fb_write); row.addStretch(1)
        outer.addLayout(row)
        self.fb_note = QtWidgets.QLabel("⚠ 센서 타입·커뮤테이션 변경은 실제 장착 엔코더와 일치해야 함. "
                                        "쓰기는 MO=0 + 커뮤테이션 리셋 + SV. 필드는 센서 타입에 맞춰 재구성됩니다.")
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
            cb.setEnabled(fld["editable"] and connected)
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
        e.setReadOnly(not editable)
        e.setEnabled(editable and connected)
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
        self.fb_note.setText("⚠ 센서 변경됨 — 커뮤테이션은 이 센서 기본값으로 맞췄습니다. "
                             "Counts/Rev·세부 파라미터를 확인 후 Write 하세요 (실제 장착 엔코더와 일치 필수)."
                             + extra)

    # EAS 6-stage wizard; our Phase-1 current-loop tune drives stages 0..2. 3..5 = Phase 2.
    _AT_STAGES = ["Initialization (Starting Phase)", "Current Identification", "Current Design",
                  "Commutation", "Velocity & Position Identification", "Velocity & Position Design"]
    _AT_PHASE1_LAST = 2
    _AT_CODE_STAGE = {"P0": 0, "VALIDATE": 0, "SNAPSHOT": 0, "ENABLE": 1,
                      "MEASURE_R": 1, "MEASURE_L": 1, "DESIGN": 2, "DONE": 2}

    def _build_tuning_page(self):
        f = theme.HudCard()
        v = QtWidgets.QVBoxLayout(f); v.setContentsMargins(16, 14, 16, 16); v.setSpacing(10)
        title = QtWidgets.QLabel("AUTOMATIC TUNING  ·  Current Loop (Phase 1)")
        title.setProperty("role", "celltitle"); v.addWidget(title)
        self.tune_stage_lbls = []
        for i, s in enumerate(self._AT_STAGES):
            suffix = "" if i <= self._AT_PHASE1_LAST else "   · Phase 2 (미구현)"
            row = QtWidgets.QLabel("○  " + s + suffix); row.setProperty("role", "fwval")
            if i > self._AT_PHASE1_LAST:
                row.setStyleSheet("color:%s;" % theme.MUTED)
            v.addWidget(row); self.tune_stage_lbls.append(row)
        # live status line (current phase detail / result reason)
        self.tune_status = QtWidgets.QLabel("연결 후 Run — 드라이브에서 R·L 실측 → PI 게인 산출")
        self.tune_status.setProperty("role", "hint"); self.tune_status.setWordWrap(True)
        v.addWidget(self.tune_status)
        v.addWidget(self._hline())
        # measured plant + computed gains
        gt = QtWidgets.QLabel("MEASURED PLANT · COMPUTED GAINS"); gt.setProperty("role", "field")
        v.addWidget(gt)
        self.tune_gain_fields = {}
        gform = QtWidgets.QGridLayout(); gform.setHorizontalSpacing(14); gform.setVerticalSpacing(7)
        rows = [("r_pp", "Resistance  R  (phase-to-phase)"), ("l_pp", "Inductance  L  (phase-to-phase)"),
                ("kp_cur", "Current Loop  KP  (KP[1])"), ("ki_cur", "Current Loop  KI  (KI[1])"),
                ("pm", "Phase Margin  (설계 안정도)"),
                ("kp_vel", "Velocity Loop  KP  (KP[2])"), ("ki_vel", "Velocity Loop  KI  (KI[2])"),
                ("kp_pos", "Position Loop  KP  (KP[3])")]
        for i, (k, label) in enumerate(rows):
            l = QtWidgets.QLabel(label); l.setProperty("role", "field")
            e = QtWidgets.QLineEdit(); e.setReadOnly(True); e.setText("—")
            gform.addWidget(l, i, 0); gform.addWidget(e, i, 1); self.tune_gain_fields[k] = e
        v.addLayout(gform)
        v.addWidget(self._hline())
        # controls
        btnrow = QtWidgets.QHBoxLayout(); btnrow.setSpacing(8)
        self.btn_tune = QtWidgets.QPushButton("Run Auto-Tune"); self.btn_tune.setEnabled(False)
        self.btn_tune.clicked.connect(self._run_autotune_clicked)
        self.btn_tune_abort = QtWidgets.QPushButton("Abort"); self.btn_tune_abort.setEnabled(False)
        self.btn_tune_abort.clicked.connect(self._abort_autotune_clicked)
        self.btn_tune_apply = QtWidgets.QPushButton("Apply Gains → Drive"); self.btn_tune_apply.setEnabled(False)
        self.btn_tune_apply.clicked.connect(self._apply_autotune_clicked)
        for b in (self.btn_tune, self.btn_tune_abort, self.btn_tune_apply):
            btnrow.addWidget(b)
        v.addLayout(btnrow)
        note = QtWidgets.QLabel("ⓘ 우리 자체 오토튠 — EAS 내부 알고리즘 재현이 아니라, 드라이브 명령으로 "
                                "R·L을 실측해 표준 PI 설계식으로 게인을 계산합니다. 시뮬 검증 완료(오라클 대비 KP/KI ≤1%), "
                                "실기 최초 실행은 통전·미세회전이 있으므로 감독 하에서만.")
        note.setProperty("role", "hint"); note.setWordWrap(True)
        v.addWidget(note); v.addStretch(1)
        # keep a handle to the running result so Apply can reference it
        self._at_result = None
        return f

    # ---- auto-tune GUI glue ----------------------------------------------------------
    def _set_tune_stage(self, active_idx, done_upto=-1):
        """Repaint the stage list: ● done, ◆ active, ○ pending (Phase-2 stays muted)."""
        for i, lbl in enumerate(self.tune_stage_lbls):
            base = self._AT_STAGES[i]
            suffix = "" if i <= self._AT_PHASE1_LAST else "   · Phase 2 (미구현)"
            if i <= done_upto:
                mark, col = "●", theme.OK if hasattr(theme, "OK") else "#28c840"
            elif i == active_idx:
                mark, col = "◆", theme.C_AMBER
            else:
                mark, col = "○", (theme.MUTED if i > self._AT_PHASE1_LAST else theme.TEXT)
            lbl.setText("%s  %s%s" % (mark, base, suffix))
            lbl.setStyleSheet("color:%s;" % col)

    def _run_autotune_clicked(self):
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
        r = self._at_result
        if r is None or r.status not in (autotune_current.GREEN, autotune_current.YELLOW):
            self._flash("적용할 유효한 결과가 없습니다."); return
        btn = QtWidgets.QMessageBox.question(
            self, "게인 적용 확인",
            "산출된 전류루프 게인을 드라이브에 쓰고 SV로 영구저장합니다 (모터 OFF에서만).\n\n"
            "• KP[1] = %.6g V/A\n• KI[1] = %.6g Hz\n\n진행할까요?" % (r.kp_v_per_a, r.ki_hz),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if self.worker and self.worker.isRunning():
            self.worker.apply_autotune_gains(r, persist=True)
            self._flash("게인 적용 전송 중…")

    def _on_autotune_started(self):
        self.btn_tune.setEnabled(False); self.btn_tune_abort.setEnabled(True)
        self.btn_tune_apply.setEnabled(False)
        self._set_tune_stage(0)
        self.tune_status.setText("▶ 튜닝 시작 — 초기화/검증 중…")

    def _on_autotune_progress(self, code, detail):
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
        self.btn_tune_abort.setEnabled(False)
        self.btn_tune.setEnabled(bool(self.worker and self.worker.isRunning()))
        self._at_result = res
        self._at_result_path = self._dump_autotune_result(res)
        # Apply is offered only for an applicable (GREEN/YELLOW) result — a RED/aborted
        # run must never leave the previous run's Apply enabled.
        self.btn_tune_apply.setEnabled(res.status in (autotune_current.GREEN, autotune_current.YELLOW))
        g = self.tune_gain_fields
        if res.r_pp_ohm is not None:
            g["r_pp"].setText("%.6g Ω" % res.r_pp_ohm)
        if res.l_pp_h is not None:
            g["l_pp"].setText("%.6g µH" % (res.l_pp_h * 1e6))
        if res.kp_v_per_a is not None:
            g["kp_cur"].setText("%.6g V/A" % res.kp_v_per_a)
        if res.ki_hz is not None:
            g["ki_cur"].setText("%.6g Hz" % res.ki_hz)
        if res.pm_deg is not None:
            g["pm"].setText("%.1f °" % res.pm_deg)
        if res.status == autotune_current.GREEN:
            self._set_tune_stage(-1, done_upto=self._AT_PHASE1_LAST)
            saved = ("  ·  저장: %s" % self._at_result_path) if self._at_result_path else ""
            self.tune_status.setText("✅ GREEN — 산출 완료. Apply로 드라이브에 적용할 수 있습니다.%s" % saved)
            self.btn_tune_apply.setEnabled(True)
        elif res.status == autotune_current.YELLOW:
            self.tune_status.setText("⚠ YELLOW — %s (검토 후 Apply 가능)" % (res.reason or ""))
            self.btn_tune_apply.setEnabled(True)
        else:
            self.tune_status.setText("⛔ RED — %s" % (res.reason or "실패"))
        self._flash("Auto-Tune %s" % res.status)

    def _on_autotune_applied(self, ok, msg):
        self._flash(("게인 적용됨: " + msg) if ok else ("적용 실패: " + msg))

    def _on_encoder_maint_result(self, ok, msg):
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

    # ---- connect / disconnect --------------------------------------------------------
    def toggle_connect(self):
        if self.worker and self.worker.isRunning():
            self.disconnect_drive()
        else:
            self.connect_drive()

    def connect_drive(self):
        port = self.cmb_port.currentText().strip()
        if not port:
            self._flash("연결할 COM 포트가 없습니다 (⟳로 새로고침).")
            return
        if self.cmb_conn.currentText() != "Direct Access USB":
            self._flash("이번 빌드는 USB만 활성 — 다른 방식은 곧 추가됩니다.")
            return
        self.btn_conn.setEnabled(False); self.btn_conn.setText("Connecting…")
        self.worker = DriveWorker(port)
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
        self.worker.encoder_maint_result.connect(self._on_encoder_maint_result)
        self.worker.stopped.connect(self._on_stopped)
        self.worker.start()

    def disconnect_drive(self):
        if self.worker:
            self.worker.stop()

    def _on_connected(self, info: dict):
        self.lbl_fw.setText(info.get("fw") or "—")
        self.lbl_pal.setText(str(info.get("pal") or "—"))
        self.lbl_boot.setText(info.get("boot") or "—")
        self.lbl_type.setText(info.get("target_type") or "—")
        self._set_connected_ui(True)

    def _on_failed(self, msg: str):
        self._set_connected_ui(False)
        self._flash("연결 실패: %s" % msg)

    def _on_telemetry(self, t: dict):
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
        enabled = (mo == 1)
        self.lbl_motor.setText("MOTOR ENABLED" if enabled else "MOTOR DISABLED")
        self.lbl_motor.setProperty("on", "true" if enabled else "false")
        self._restyle(self.lbl_motor)

    def _on_stopped(self):
        self._set_connected_ui(False)

    def zero_position(self):
        if self.worker and self.worker.isRunning():
            self.worker.send_once("PX=0")
            self._flash("Zero Position 전송 (PX=0)…")
        else:
            self._flash("연결 후 사용하세요.")

    def _on_command_done(self, cmd, resp):
        self._flash("%s → %s" % (cmd, resp if resp else "OK"))

    _MOTOR_TYPES = {0: "Rotary brushless", 1: "Rotary DC brush", 2: "Linear brushless",
                    3: "Linear voice coil", 4: "Rotary two-phase", 6: "Linear two-phase"}

    def _on_motor_params(self, mp):
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
        self._fb_connected = True
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
        key = self.cmb_sensor.currentData()
        if not isinstance(key, int):
            self._flash("이 센서는 CA[41] ID 미확정(IAI/Mitsubishi/Serial Exclusive #3) — 쓰기 차단."); return
        ff = self.fb_fields
        try:
            sid = int(key)
            cid = int(self.cmb_commut.currentData())
            counts = int(float(ff["counts"].text()))
        except (ValueError, TypeError):
            self._flash("숫자/선택 형식 오류 — 값을 확인하세요."); return
        # ORDERED writes: sensor id first (resets commutation), then commut/counts,
        # then mapped editable panel fields; elmo_link re-issues CA[41] after CA[35]/[36].
        pairs = [("CA[41]", sid), ("CA[17]", cid), ("CA[18]", counts)]
        rows = [("센서 타입", feedback_spec.SENSOR_NAMES.get(sid, "ID %d" % sid), "CA[41] = %d" % sid),
                ("커뮤테이션 방법", feedback_spec.COMMUT_NAMES.get(cid, str(cid)), "CA[17] = %d" % cid),
                ("Counts / Rev", "%d" % counts, "CA[18] = %d" % counts)]
        raws = getattr(self, "_fb_raws", {}) or {}
        pending = {"CA[41]": sid, "CA[17]": cid, "CA[18]": counts}
        deferred = []   # sw_res needs CA[59]/CA[58] resolved from pending first
        for label, (fld, w) in self._fb_dyn_fields.items():
            if not fld["editable"]:
                continue
            if fld["kind"] == feedback_spec.DD:
                raw = w.currentData()
                if raw is None:
                    continue
                pairs.append((fld["cmd"], raw)); pending[fld["cmd"]] = raw
                rows.append((label, w.currentText(), "%s = %s" % (fld["cmd"], raw)))
            elif fld["kind"] == feedback_spec.VALUE:
                txt = w.text().strip()
                if not txt or txt == "—":
                    continue
                if fld["xform"] == "sw_res":
                    deferred.append((label, fld, txt)); continue
                try:
                    cmd, val = feedback_spec.encode_value(fld, txt, raws, pending)
                except ValueError:
                    self._flash("숫자 오류: %s" % label); return
                pairs.append((cmd, val)); pending[cmd] = val
                rows.append((label, txt, "%s = %s" % (cmd, val)))
        for label, fld, txt in deferred:
            try:
                cmd, val = feedback_spec.encode_value(fld, txt, raws, pending)
            except ValueError as e:
                self._flash("%s: %s" % (label, e)); return
            pairs.append((cmd, val))
            rows.append((label, txt, "%s = %s  (CA[61]=CA[59]−SW−CA[58])" % (cmd, val)))
        preview = "\n".join("• %s :  %s\n      (%s)" % (n, val, raw) for n, val, raw in rows)
        btn = QtWidgets.QMessageBox.warning(
            self, "피드백/엔코더 쓰기 확인 (주의)",
            "센서/커뮤테이션 설정을 드라이브에 쓰고 SV 저장합니다.\n"
            "⚠ 실제 장착된 엔코더와 일치해야 합니다 — 불일치 시 모터 미동작/폴트.\n"
            "(모터 OFF에서만 실행 · CA[35]/CA[36] 변경 시 CA[41] 자동 재기입)\n\n%s\n\n진행할까요?" % preview,
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if self.worker and self.worker.isRunning():
            self.worker.write_feedback(pairs)
            self._flash("피드백 쓰기 전송 중…")

    def _write_motor(self):
        import math
        f = self.motor_fields
        try:
            peak = float(f["peak"].text()); cont = float(f["cont"].text())
            rpm = float(f["maxspeed"].text()); poles = int(float(f["poles"].text()))
            mtype = int(self.motor_type_combo.currentData())
        except (ValueError, TypeError):
            self._flash("숫자 형식 오류 — 값을 확인하세요."); return
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
            self, "드라이브 쓰기 확인",
            "아래 값을 드라이브에 쓰고 SV로 영구저장합니다 (모터 OFF에서만 실행).\n\n%s\n\n진행할까요?" % preview,
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        if self.worker and self.worker.isRunning():
            self.worker.write_motor(writes)
            self._flash("쓰기 전송 중…")

    def _on_write_result(self, ok, msg):
        self._flash("쓰기 완료 (드라이브 재읽기로 확인)" if ok else "쓰기 거부/실패: %s" % msg)

    # ---- Encoder Maintenance (EAS parity: TW[18] datum / TW[19] multi-turn / TW[20] errors) ----
    def _encoder_maint_dialog(self):
        """Build the Encoder Maintenance dialog mirroring EAS. Returns (dialog, widgets).

        Grounded (firmware notes): TW[18]=<val> resets single-turn absolute position
        (EnDat 2.2: any value, 0 to zero; other sensors 0 only else EC=99); TW[20]=<socket>
        resets that socket's errors (=1 for socket 1). TW[19] resets multi-turn; sent as
        TW[19]=0. On a multi-turn encoder PX = multiturn*counts + single-turn, so a full
        zero needs BOTH TW[18] and TW[19] (matches the observed EAS procedure)."""
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
        btn_zero = QtWidgets.QPushButton("▶  Zero Position  (TW[18] + TW[19])")
        lay.addWidget(btn_zero)
        chk_sv = QtWidgets.QCheckBox("SV 로 영구저장 (선택)")
        lay.addWidget(chk_sv)
        note = QtWidgets.QLabel("ⓘ EnDat 2.2는 Datum 임의값 허용(0=영점) · 타 센서는 0만(그 외 EC=99). "
                                "다회전 엔코더는 PX=다회전×counts+단일회전 → 완전 영점엔 TW[18]+TW[19] 둘 다 필요. "
                                "에러리셋은 소켓 1(TW[20]=1). 각 명령의 드라이브 응답을 상태줄에 그대로 표시합니다.")
        note.setWordWrap(True); note.setProperty("role", "hint")
        lay.addWidget(note)

        def datum_cmd():
            return "TW[18]=%s" % (edit.text().strip() or "0")
        # TW[19]/TW[20] take a SOCKET argument (=1 for socket 1), NOT a value — live-confirmed:
        # TW[19]=0 was rejected by the drive ("Drive error 21"); socket 1 is our feedback socket.
        mt_cmds = ["TW[19]=1"]      # reset multi-turn of socket 1
        err_cmds = ["TW[20]=1"]     # reset errors of socket 1
        btn_datum.clicked.connect(lambda: self._enc_maint_send([datum_cmd()], chk_sv.isChecked(), "Set Datum Shift"))
        btn_mt.clicked.connect(lambda: self._enc_maint_send(list(mt_cmds), chk_sv.isChecked(), "Reset Multi-turn"))
        btn_err.clicked.connect(lambda: self._enc_maint_send(list(err_cmds), chk_sv.isChecked(), "Reset Errors"))
        btn_zero.clicked.connect(lambda: self._enc_maint_send([datum_cmd()] + list(mt_cmds), chk_sv.isChecked(),
                                                              "Zero Position (Datum+Multi-turn)"))
        widgets = {"edit": edit, "btn_datum": btn_datum, "btn_mt": btn_mt, "btn_err": btn_err,
                   "btn_zero": btn_zero, "chk_sv": chk_sv, "datum_cmd": datum_cmd,
                   "mt_cmds": mt_cmds, "err_cmds": err_cmds}
        return dlg, widgets

    def _open_encoder_maintenance(self):
        if not (self.worker and self.worker.isRunning()):
            self._flash("연결 후 사용하세요."); return
        dlg, _w = self._encoder_maint_dialog()
        dlg.exec()

    def _enc_maint_send(self, cmds, persist, label):
        if not (self.worker and self.worker.isRunning()):
            self._flash("연결 후 사용하세요."); return
        preview = "\n".join("• %s" % c for c in cmds) + ("\n• SV (영구저장)" if persist else "")
        btn = QtWidgets.QMessageBox.warning(
            self, "엔코더 정비 확인 (주의)",
            "%s 를 실행합니다 — 엔코더의 위치 기준(원점)을 변경합니다.\n"
            "모터 OFF에서만 실행 · 실제 장착 상태와 일치해야 합니다.\n\n%s\n\n진행할까요?" % (label, preview),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No)
        if btn != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self.worker.encoder_maintenance(cmds, persist)
        self._flash("%s 전송 중… (드라이브 응답 대기)" % label)

    def _on_tuning_gains(self, g):
        for k in ("kp_cur", "ki_cur", "kp_vel", "ki_vel", "kp_pos"):
            self.tune_gain_fields[k].setText(self._fmt(g.get(k), 4))

    # ---- ui state --------------------------------------------------------------------
    def _set_connected_ui(self, on: bool):
        self.btn_conn.setEnabled(True)
        self.btn_conn.setText("Disconnect" if on else "Connect")
        self.lbl_state.setText("ONLINE" if on else "OFFLINE")
        self.lbl_state.setProperty("on", "true" if on else "false")
        self._restyle(self.lbl_state)
        if hasattr(self, "btn_zero"):
            self.btn_zero.setEnabled(on)
        if hasattr(self, "btn_motor_write"):
            self.btn_motor_write.setEnabled(on)
        if hasattr(self, "btn_tune"):
            self.btn_tune.setEnabled(on)
        if not on:
            for b in ("btn_tune_abort", "btn_tune_apply"):
                if hasattr(self, b):
                    getattr(self, b).setEnabled(False)
        if hasattr(self, "motor_type_combo"):
            self.motor_type_combo.setEnabled(on)
        if hasattr(self, "motor_fields"):
            for k in ("peak", "cont", "maxspeed", "poles"):
                if k in self.motor_fields:
                    self.motor_fields[k].setEnabled(on)
        for w in ("cmb_sensor", "cmb_commut", "btn_fb_write"):
            if hasattr(self, w):
                getattr(self, w).setEnabled(on)
        self._fb_connected = on
        if hasattr(self, "fb_fields"):
            if "counts" in self.fb_fields:
                self.fb_fields["counts"].setEnabled(on)
        if hasattr(self, "_fb_dyn_fields"):
            for _label, (fld, w) in self._fb_dyn_fields.items():
                if fld["editable"] or fld["kind"] == feedback_spec.BTN:
                    w.setEnabled(on)
        if not on:
            for m in (getattr(self, "m_pos", None), getattr(self, "m_perr", None),
                      getattr(self, "m_vel", None), getattr(self, "m_iq", None)):
                if m:
                    m.setText("—")
            for s in (getattr(self, "m_pos_sub", None), getattr(self, "m_vel_sub", None)):
                if s:
                    s.setText("")
            self.lbl_motor.setText("MOTOR DISABLED")
            self.lbl_motor.setProperty("on", "false"); self._restyle(self.lbl_motor)
            self.cmb_port.setEnabled(True); self.cmb_conn.setEnabled(True)
        else:
            self.cmb_port.setEnabled(False); self.cmb_conn.setEnabled(False)

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
        # non-modal status (never a blocking QDialog — headless-safe)
        self.statusBar().showMessage(msg, 6000)

    def closeEvent(self, ev):
        if self.worker and self.worker.isRunning():
            self.worker.stop(); self.worker.wait(1500)
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


def _smoke_autotune(app, win):
    """Headless acceptance for the auto-tune UI glue (no hardware, offscreen).

    Drives the DriveWorker->GUI signal handlers with synthetic progress + a GREEN
    result and asserts the stage wizard, measured/gain fields, and Apply gating.
    Then feeds a RED result and asserts Apply is re-disabled. Saves a screenshot.
    """
    sys.stdout.reconfigure(encoding="utf-8")
    ac = autotune_current
    win._nav_to(3)                                    # Tuning page
    win._set_connected_ui(True)
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
    win._on_autotune_result(res)
    app.processEvents()
    g = win.tune_gain_fields
    chk("R_pp populated", g["r_pp"].text() != "—" and "Ω" in g["r_pp"].text())
    chk("L_pp populated (µH)", g["l_pp"].text() != "—" and "µH" in g["l_pp"].text())
    chk("KP[1] populated", g["kp_cur"].text().startswith("0.0711") and "V/A" in g["kp_cur"].text())
    chk("KI[1] populated", g["ki_cur"].text().startswith("812") and "Hz" in g["ki_cur"].text())
    chk("PM populated", "°" in g["pm"].text())
    chk("Apply ENABLED after GREEN", win.btn_tune_apply.isEnabled())
    chk("Abort disabled after result", not win.btn_tune_abort.isEnabled())
    chk("stages 0..2 all done (●)", all("●" in win.tune_stage_lbls[i].text() for i in range(3)))
    chk("status shows GREEN", "GREEN" in win.tune_status.text())
    chk("result cached for Apply", win._at_result is res)

    # --- RED result re-disables Apply ---
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
    chk("TW[18] datum cmd (default 0)", w["datum_cmd"]() == "TW[18]=0")
    w["edit"].setText("123")
    chk("TW[18] datum cmd (value)", w["datum_cmd"]() == "TW[18]=123")
    # TW[19]/TW[20] use a socket arg =1 (TW[19]=0 was rejected live with Drive error 21)
    chk("Reset Multi-turn = TW[19]=1 (socket)", w["mt_cmds"] == ["TW[19]=1"])
    chk("Reset Errors = TW[20]=1 (socket)", w["err_cmds"] == ["TW[20]=1"])

    # worker queues the right payloads (thread not started)
    wk = DriveWorker("COM_TEST")
    wk.encoder_maintenance(["TW[18]=0", "TW[19]=1"], False)
    job = wk._jobs[-1]
    chk("worker queues encoder_maint job", job == ("encoder_maint", (["TW[18]=0", "TW[19]=1"], False)))
    wk.encoder_maintenance(["TW[20]=1"], True)
    chk("worker queues errors+SV job", wk._jobs[-1] == ("encoder_maint", (["TW[20]=1"], True)))

    print("SMOKE-ENCODER:", "GREEN (all assertions pass)" if not fails
          else "RED — %d failure(s): %s" % (len(fails), fails))
    return 0 if not fails else 1


def main():
    smoke = "--smoke" in sys.argv
    smoke_fb = "--smoke-feedback" in sys.argv
    smoke_at = "--smoke-autotune" in sys.argv
    smoke_enc = "--smoke-encoder" in sys.argv
    if smoke or smoke_fb or smoke_at or smoke_enc:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(theme.STYLE)
    win = MainWindow()
    win.show()
    if smoke_fb:
        return _smoke_feedback(app, win)
    if smoke_at:
        return _smoke_autotune(app, win)
    if smoke_enc:
        return _smoke_encoder(app, win)
    if smoke:
        # exercise the telemetry slot with a synthetic sample, screenshot, exit
        win._on_connected({"fw": "Twitter 01.01.16.00 08Mar2020B01G", "pal": "90",
                           "boot": "DSP Boot 1.0.1.6", "target_type": "Gold Drive"})
        win._on_telemetry({"pos": 12124061, "vel": 3932674.0, "pos_err": 0, "iq": 0.124, "mo": 1})
        app.processEvents()
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media", "smoke_main.png")
        win.grab().save(out)
        print("SMOKE OK ->", out)
        return 0
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
