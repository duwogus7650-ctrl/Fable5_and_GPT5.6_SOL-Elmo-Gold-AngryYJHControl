"""Elmo Gold drive transport — thin Python wrapper over the official
Drive .NET Library (ElmoMotionControlComponents.Drive.EASComponents.dll) via pythonnet.

Confirmed working 2026-07-12: pythonnet 3.1.0 (Python 3.14, 64-bit) loads the 2015
.NET Framework DLL under CLR 4.0.30319 (netfx runtime). This is the sanctioned,
safe transport to a closed Gold drive over USB — no protocol reverse-engineering.

SAFETY: this module never enables the motor. `command()` will refuse motion-enabling
commands unless allow_motion=True is passed explicitly by a supervised caller.
"""
from __future__ import annotations

import os
import sys
import glob
import math
import zipfile

# --- locate / stage the vendored DLLs -------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_LIBDIR = os.path.join(_HERE, "lib_net")
_STATE_DIR = os.path.join(_HERE, ".omc", "state")   # diagnostics dumps (recorder signals)
_MAIN_DLL_NAME = "ElmoMotionControlComponents.Drive.EASComponents.dll"
_ZIP = os.path.join(_HERE, "vendor", "elmo-downloads", "Drive .NET Library 1.0.0.8.zip")


def _ensure_dlls() -> str:
    """Extract the DLLs from the vendored zip on first use; return main DLL path."""
    main_dll = os.path.join(_LIBDIR, _MAIN_DLL_NAME)
    if os.path.isfile(main_dll):
        return main_dll
    os.makedirs(_LIBDIR, exist_ok=True)
    with zipfile.ZipFile(_ZIP) as z:
        for n in z.namelist():
            if n.lower().endswith(".dll"):
                with open(os.path.join(_LIBDIR, os.path.basename(n)), "wb") as f:
                    f.write(z.read(n))
    if not os.path.isfile(main_dll):
        raise FileNotFoundError(f"main DLL not found after extract: {main_dll}")
    return main_dll


_ASM = None


def _load_assembly():
    global _ASM
    if _ASM is not None:
        return _ASM
    main_dll = _ensure_dlls()
    try:
        from pythonnet import load
        load("netfx")  # DLL is a .NET Framework assembly — force Framework runtime
    except Exception:
        pass  # already loaded, or default runtime acceptable
    import clr  # noqa: F401
    from System.Reflection import Assembly
    _ASM = Assembly.LoadFrom(main_dll)
    return _ASM


# commands that enable power / cause motion — blocked unless explicitly allowed
_MOTION_PREFIXES = ("MO=1", "BG", "JV", "PA", "PR", "PT", "PVT", "TC", "MI")


def _to_num(s: str):
    """Parse an Elmo textual response to int/float; return the stripped string if not numeric."""
    if s is None:
        return None
    t = s.strip().rstrip(";").strip()
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return t


class ElmoLink:
    """Read-oriented transport to a single Gold drive over USB (default COM3)."""

    def __init__(self, com_port: str = "COM3"):
        self.com_port = com_port
        self._comm = None
        self._factory = None
        self._last_recorder_error = None   # human-readable reason recorder_signals()==None

    def _ns(self):
        _load_assembly()
        import ElmoMotionControlComponents.Drive.EASComponents as EAS
        return EAS

    def connect(self):
        EAS = self._ns()
        self._factory = EAS.DriveCommunicationFactory()
        info = self._factory.CreateUSBCommunicationInfo(self.com_port)
        self._comm = self._factory.CreateCommunication(info)
        # Connect has one OUT param (errorObj) -> omit from call, returned in tuple
        ok, err = self._comm.Connect()
        if not ok:
            raise ConnectionError(f"Connect failed on {self.com_port}: {err}")
        return True

    @property
    def is_connected(self) -> bool:
        return bool(self._comm and self._comm.IsConnected)

    def command(self, cmd: str, timeout_ms: int = 1000, allow_motion: bool = False) -> str:
        """Send a 2-letter Elmo command, return the drive's textual response.

        Motion/power-enabling commands are refused unless allow_motion=True.
        """
        if not self._comm:
            raise RuntimeError("not connected")
        u = cmd.replace(" ", "").upper()
        if not allow_motion and any(u.startswith(p) for p in _MOTION_PREFIXES):
            raise PermissionError(f"refused motion/power command without allow_motion=True: {cmd!r}")
        # SendCommandAnalyzeError(command, OUT response, OUT errorObj, timeout).
        # pythonnet needs placeholders passed for the OUT params ("", None);
        # returns (retval, response, errorObj).
        ok, response, err = self._comm.SendCommandAnalyzeError(cmd, "", None, timeout_ms)
        if not ok:
            raise IOError(f"drive/library error on {cmd!r}: {err}")
        return response

    # --- read-only telemetry (grounded from Gold Line Command Reference) --------------
    # PX Main Position [cnt], VX Main Feedback Velocity [cnt/s], PE Position Error [cnt],
    # IQ Active Current [A], MO Motor On state (0/1). All are read-only when queried
    # without '=' (a bare mnemonic returns the current value).
    _TELEMETRY = (("pos", "PX"), ("vel", "VX"), ("pos_err", "PE"),
                  ("iq", "IQ"), ("mo", "MO"))

    def read_telemetry(self) -> dict:
        """Return a snapshot dict {pos, vel, pos_err, iq, mo}. Missing values are None."""
        out = {}
        for key, cmd in self._TELEMETRY:
            try:
                out[key] = _to_num(self.command(cmd))
            except Exception:
                out[key] = None
        return out

    def read_motor_params(self) -> dict:
        """Read Motor Settings params (grounded + live-verified against EAS 2026-07-12).

        Drive stores current in AMPLITUDE amperes; EAS displays rms = amplitude/sqrt(2)
        (verified: PL[1]=70.71 -> 50 Arms). Max speed RPM = VH[2](counts/s)*60/CA[18].
        R/L/Ke are NOT drive parameters (EAS motor-DB only) -> not returned.
        """
        g = lambda c: _to_num(self.command(c))
        pl, cl = g("PL[1]"), g("CL[1]")
        vh, ca18 = g("VH[2]"), g("CA[18]")
        poles, mtype = g("CA[19]"), g("CA[28]")
        rms = lambda x: (x / math.sqrt(2)) if isinstance(x, (int, float)) else None
        rpm = (vh * 60.0 / ca18) if (isinstance(vh, (int, float))
                                     and isinstance(ca18, (int, float)) and ca18) else None
        return {"peak_arms": rms(pl), "cont_arms": rms(cl), "rpm": rpm,
                "poles": poles, "mtype": mtype,
                "pl_amp": pl, "cl_amp": cl, "vh": vh, "ca18": ca18}

    def read_tuning_gains(self) -> dict:
        """Read the control-loop gains the drive holds (read-only).

        These are the OUTPUT of EAS's Automatic Tuning (whose gain-design algorithm is
        EAS-internal and not reproducible from the command set). We can display them.
        KP[1]/KI[1] = current loop, KP[2]/KI[2] = velocity loop, KP[3] = position loop.
        Verified live: KI[1]=812.9, KP[1]=0.0718.
        """
        g = lambda c: _to_num(self.command(c))
        out = {}
        for key, cmd in (("kp_cur", "KP[1]"), ("ki_cur", "KI[1]"),
                         ("kp_vel", "KP[2]"), ("ki_vel", "KI[2]"), ("kp_pos", "KP[3]")):
            try:
                out[key] = g(cmd)
            except Exception:
                out[key] = None
        return out

    def write_motor_params(self, writes: dict, persist: bool = True):
        """Write Motor Settings params, then persist with SV.

        `writes` maps raw drive command -> value, e.g. {'PL[1]': 70.71, 'CA[19]': 16}.
        SAFETY: all config writes + SV require the motor OFF (MO=0); if the motor is on
        this refuses rather than disabling it (turning a servo off is the operator's call).
        Returns (ok: bool, message: str).
        """
        if _to_num(self.command("MO")) == 1:
            return (False, "모터 ON(MO=1) 상태 — 설정 변경/저장은 모터 OFF에서만. STOP 후 재시도.")
        for cmd, val in writes.items():
            self.command("%s=%s" % (cmd, val))          # non-motion config writes
        if persist:
            self.command("SV")                          # persist to flash (needs MO=0)
        return (True, "OK")

    # feedback sensor type IDs (CA[41..44]) and commutation methods (CA[17])
    SENSOR_IDS = {1: "Incremental Quad (Port B)", 2: "Incremental Quad (Port A)",
                  3: "Analog Sin/Cos", 4: "Digital Hall", 5: "Serial Absolute BiSS",
                  6: "Panasonic", 7: "Mitutoyo", 8: "Virtual 2-Sine (SE)",
                  9: "Serial Absolute EnDat", 10: "Tamagawa", 11: "Pulse&Dir (Port B)",
                  12: "Pulse&Dir (Port A)", 13: "Emulation (Port B)", 14: "Emulation (Port A)",
                  16: "Analog Input #1", 17: "Gurley", 18: "Absolute SSI", 19: "Yaskawa",
                  22: "Resolver", 23: "Kawasaki", 24: "General BiSS", 25: "Sanyo",
                  28: "Serial Hiperface",
                  # live-corrected 2026-07-12: 2013 CR enum is incomplete for 2020 firmware.
                  # This drive reports ID 30 for its EnDat 2.2 (19-bit + 16-bit multiturn), not the CR's 9.
                  30: "Serial Absolute EnDat 2.2"}
    COMMUT_METHODS = {1: "Digital Hall", 2: "Stepper", 3: "Binary Search", 4: "Analog Hall",
                      5: "Serial Absolute Encoder", 6: "Virtual Gurley", 7: "PAL Slave"}

    def read_feedback(self) -> dict:
        """Read feedback config + the CURRENT sensor's specific parameters (read-only).

        Common (always): CA[41] sensor ID, CA[17] commutation, CA[18] counts/rev,
        CA[54] direction, CA[45/46/47] sockets. Sensor-specific params = every raw
        command feedback_spec.commands_for(sensor_id) needs (incl. conversion deps
        like CA[59]/CA[61]/CA[58] for SW-resolution), so the panel can decode and
        reconfigure per sensor exactly like EAS.
        """
        import feedback_spec
        g = lambda c: _to_num(self.command(c))
        sid, meth = g("CA[41]"), g("CA[17]")
        _groups, verified = feedback_spec.spec_for(sid)
        params = {}
        for cmd in feedback_spec.commands_for(sid):
            try:
                params[cmd] = _to_num(self.command(cmd))
            except Exception:
                params[cmd] = None
        return {
            "sensor_id": sid,
            "sensor_name": (feedback_spec.SENSOR_NAMES.get(int(sid)) or ("ID %d (미확정)" % int(sid)))
                           if isinstance(sid, (int, float)) else None,
            "commut_method": meth,
            "commut_name": feedback_spec.COMMUT_NAMES.get(int(meth)) if isinstance(meth, (int, float)) else None,
            "counts_rev": g("CA[18]"), "direction": g("CA[54]"),
            "pos_socket": g("CA[45]"), "vel_socket": g("CA[46]"), "commut_socket": g("CA[47]"),
            "params": params, "verified": verified,
        }

    def write_feedback_params(self, pairs, persist: bool = True):
        """Write feedback/encoder config as an ORDERED list of (command, value) pairs.

        Encoding discipline (docs/eas-feedback-command-map.md):
        - all feedback CA[] writes require motor OFF (MO=0); refused otherwise
        - after changing CA[35]/CA[36], the sensor ID CA[41] must be re-written
          (re-issued automatically here when both appear in `pairs`)
        - persist with SV (also MO=0 only)
        Returns (ok: bool, message: str).
        """
        if _to_num(self.command("MO")) == 1:
            return (False, "모터 ON(MO=1) 상태 — 설정 변경/저장은 모터 OFF에서만. STOP 후 재시도.")
        pairs = list(pairs)
        for cmd, val in pairs:
            self.command("%s=%s" % (cmd, val))          # non-motion config writes
        touched = {c for c, _v in pairs}
        if touched & {"CA[35]", "CA[36]"}:
            for cmd, val in pairs:                      # re-issue sensor ID after CA[35]/[36]
                if cmd == "CA[41]":
                    self.command("%s=%s" % (cmd, val))
                    break
        if persist:
            self.command("SV")                          # persist to flash (needs MO=0)
        return (True, "OK")

    # --- drive recorder (.NET Drive Recording API — docs/recording-api.md) -----------
    # The legacy 2-letter path (RC/RG/RR + BH hex upload) is NOT used: BH takes a
    # bitfield and returns hex-binary with a live-unknown framing.  The .NET recorder
    # returns physical doubles directly.
    # LIVE-CONFIRMED (2026-07-13, supervised read-only diagnosis):
    #   * CreatePersonalityModel(path) only PARSES an existing XML (LibEC=8 when the
    #     file is missing) — it does NOT upload from the drive.
    #   * Upload flow: comm.UploadPersonality(path) -> IUploadDownloadModel; ALL FIVE
    #     events (OnStart/OnProgress/OnFinish/OnFailed/OnCancel) must be registered
    #     BEFORE model.Start() (else LibEC=9 "No Callbacks Registered"); then poll
    #     OperationStatus until FINISHED; the XML lands at the given path (~95 KB,
    #     254 signals on this drive).
    # STILL LIVE-UNKNOWN: recording dt semantics (SamplingTime vs TimeResolution*TS)
    # and WHICH of the A/B/C/D Voltage signals is the applied-voltage channel (U3
    # refined — needs live SE-excitation characterization).

    @staticmethod
    def _rec_ns():
        """Recording/Personality sub-namespaces (grounded by live reflection:
        RecordingSetup etc. live under .Recording, RecordingSignalSetup under
        .Personality — NOT in the root EASComponents namespace)."""
        _load_assembly()
        import ElmoMotionControlComponents.Drive.EASComponents.Recording as REC
        import ElmoMotionControlComponents.Drive.EASComponents.Personality as PERS
        return REC, PERS

    @property
    def _personality_xml_path(self) -> str:
        return os.path.join(_LIBDIR, "personality_model.xml")

    @staticmethod
    def _signals_meta_of(model):
        """SignalsMetaData (Dictionary<int, RecordingSignalSetup>) or None."""
        try:
            meta = model.SignalsMetaData if model is not None else None
            return meta if (meta is not None and int(meta.Count) > 0) else None
        except Exception:
            return None

    @staticmethod
    def _err_text(err):
        """IDriveErrorObject -> readable string (ErrorCode/LibraryErrorCode/
        ErrorDescription/LibraryErrorDescription — live-confirmed members)."""
        if err is None:
            return None
        try:
            parts = []
            for attr in ("ErrorCode", "LibraryErrorCode",
                         "ErrorDescription", "LibraryErrorDescription"):
                v = getattr(err, attr, None)
                if v not in (None, "", 0):
                    parts.append("%s=%s" % (attr, v))
            return "; ".join(parts) or str(err)
        except Exception:
            return str(err)

    def _try_create_personality(self, path):
        """CreatePersonalityModel(path): PARSES an existing XML (live-confirmed;
        LibEC=8 if missing).  Returns the populated model or None (+ error)."""
        try:
            ok, err = self._comm.CreatePersonalityModel(path)
            if not ok:
                self._last_recorder_error = self._err_text(err) \
                    or "CreatePersonalityModel returned false"
                return None
            model = self._comm.PersonalityModel
            if self._signals_meta_of(model) is None:
                self._last_recorder_error = \
                    "personality parsed but SignalsMetaData empty"
                return None
            return model
        except Exception as e:
            self._last_recorder_error = "CreatePersonalityModel: %r" % (e,)
            return None

    def _upload_personality(self, path, timeout_s: float = 60.0,
                            poll_s: float = 0.1) -> bool:
        """Upload the personality XML FROM the drive to `path` (live-confirmed
        flow): UploadPersonality -> register ALL FIVE events -> Start ->
        poll OperationStatus until FINISHED (FAILED/CANCELED/timeout -> False)."""
        import time as _time
        try:
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            model, err = self._comm.UploadPersonality(path)
            if model is None:
                self._last_recorder_error = self._err_text(err) \
                    or "UploadPersonality returned no model"
                return False
            events = []

            def _h(_sender, _args):              # progress-capturing no-op
                try:
                    events.append(str(_args))
                except Exception:
                    pass

            # all five MUST be registered before Start (else LibEC=9)
            model.OnStart += _h
            model.OnProgress += _h
            model.OnFinish += _h
            model.OnFailed += _h
            model.OnCancel += _h
            ok, err = model.Start()
            if not ok:
                self._last_recorder_error = self._err_text(err) \
                    or "personality upload Start() failed"
                return False
            t0 = _time.time()
            while True:
                st = str(model.OperationStatus)  # OPERATION_STATUS enum name
                if st == "FINISHED":
                    return True
                if st in ("FAILED", "CANCELED"):
                    self._last_recorder_error = "personality upload %s" % st
                    return False
                if _time.time() - t0 > timeout_s:
                    self._last_recorder_error = \
                        "personality upload timeout %.0fs (status=%s)" % (timeout_s, st)
                    return False
                _time.sleep(poll_s)
        except Exception as e:
            self._last_recorder_error = "UploadPersonality: %r" % (e,)
            return False

    def _dump_recorder_signals(self, model):
        """Durability dump of the signal list to .omc/state/recorder_signals.json
        (name/index/category/classification) — diagnostics only, never raises."""
        try:
            import json
            meta = self._signals_meta_of(model)
            if meta is None:
                return
            rows = []
            for kv in meta:
                s = kv.Value
                rows.append({
                    "index": int(kv.Key),
                    "signal_index": int(getattr(s, "SignalIndex", kv.Key) or 0),
                    "name": str(s.Name),
                    "category": str(getattr(s, "CategoryName", "") or ""),
                    "classification": str(getattr(s, "Classification", "") or "")})
            os.makedirs(_STATE_DIR, exist_ok=True)
            out = os.path.join(_STATE_DIR, "recorder_signals.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"count": len(rows), "signals": rows}, f,
                          ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _personality(self):
        """DrivePersonalityModel with populated SignalsMetaData, or None.

        Ladder (live-confirmed 2026-07-13): already-populated model -> cached
        XML parse (CreatePersonalityModel) -> upload from drive
        (_upload_personality) then parse.  Every failure returns None with the
        reason in self._last_recorder_error; the autotune turns None into an
        honest pre-power RED at P4."""
        if not self._comm:
            self._last_recorder_error = "not connected"
            return None
        self._last_recorder_error = None
        try:
            model = self._comm.PersonalityModel
        except Exception:
            model = None
        if self._signals_meta_of(model) is not None:
            return model
        path = self._personality_xml_path
        if os.path.isfile(path):                 # cache-first (95 KB XML persists)
            model = self._try_create_personality(path)
            if model is not None:
                self._dump_recorder_signals(model)
                return model
        if not self._upload_personality(path):
            return None
        model = self._try_create_personality(path)
        if model is not None:
            self._dump_recorder_signals(model)
        return model

    def recorder_signals(self):
        """list[str] of recordable signal names from the personality, or None.
        (None => autotune P4 RED '레코더 신호목록 확보 실패' — honest, pre-power.)"""
        model = self._personality()
        meta = self._signals_meta_of(model)
        if meta is None:
            return None
        try:
            names = []
            for kv in meta:                  # KeyValuePair<int, RecordingSignalSetup>
                nm = kv.Value.Name
                if nm:
                    names.append(str(nm))
            return names or None
        except Exception:
            return None

    def _signal_setups(self, names):
        """RecordingSignalSetup objects for the given signal names (exact match)."""
        model = self._personality()
        meta = self._signals_meta_of(model)
        if meta is None:
            raise IOError("personality model unavailable — recorder signal list unknown")
        lookup = {}
        for kv in meta:
            lookup[str(kv.Value.Name)] = kv.Value
        missing = [n for n in names if n not in lookup]
        if missing:
            raise KeyError("signals not in personality: %s" % missing)
        return [lookup[n] for n in names]

    def record(self, signals, length, time_resolution: int = 1,
               timeout_s: float = 10.0, poll_s: float = 0.02) -> dict:
        """Record `signals` (names) for `length` samples via the .NET recorder.

        Returns {name: np.ndarray (physical doubles), 'dt': float seconds}.
        Flow (docs/recording-api.md): GetRecordingObject -> RecordingSetup(
        TimeResolution/RecordingLength/SignalData/TriggerSetup.SetupType=Immediate)
        -> ConfigureRecording -> StartRecording -> poll GetRecordingStatus()==REnd
        (ROff=error; timeout -> StopRecorder) -> UploadRecordingData().Data
        (Dict<int, Double[]>, already physical — no factor/hex parsing).
        Data keys are POSITIONAL 0..N-1 in SignalData request order — NOT the
        personality SignalIndex (LIVE-CONFIRMED on run #4: a 6-signal request
        returned keys [0..5] while 'A Voltage' has SignalIndex 19).
        dt: RecordingSetup.SamplingTime when populated, else TimeResolution*TS
        (PROVISIONAL — dt semantics live-unknown).  Blocking; raises on failure.
        """
        import time as _time
        import numpy as np
        if not self._comm:
            raise RuntimeError("not connected")
        REC, PERS = self._rec_ns()
        setups = self._signal_setups(list(signals))
        rec = self._comm.GetRecordingObject()
        setup = REC.RecordingSetup()
        setup.TimeResolution = int(time_resolution)
        setup.RecordingLength = int(length)
        from System.Collections.Generic import List
        sig_list = List[PERS.RecordingSignalSetup]()
        for s in setups:
            sig_list.Add(s)
        setup.SignalData = sig_list
        trig = REC.TriggerSetup()
        trig.SetupType = REC.TriggerSetupType.Immediate
        setup.TriggerSetup = trig
        if not rec.ConfigureRecording(setup):
            raise IOError("ConfigureRecording failed")
        if not rec.StartRecording():
            raise IOError("StartRecording failed")
        RS = REC.RecordingStatus
        t0 = _time.time()
        while True:
            st = rec.GetRecordingStatus()
            if st == RS.REnd:
                break
            if st == RS.ROff:
                raise IOError("recorder status ROff (error/cancelled)")
            if _time.time() - t0 > timeout_s:
                try:
                    rec.StopRecorder()
                except Exception:
                    pass
                raise TimeoutError("recording not finished in %.1fs (status=%s)"
                                   % (timeout_s, st))
            _time.sleep(poll_s)
        data = rec.UploadRecordingData()
        by_key = {}
        for kv in data.Data:                     # Dictionary<int, Double[]>
            by_key[int(kv.Key)] = np.array(list(kv.Value), dtype=float)
        out = _map_upload_data(list(signals), by_key)   # positional 0..N-1
        dt = 0.0
        try:
            dt = float(setup.SamplingTime)
        except Exception:
            dt = 0.0
        if not dt or dt <= 0:
            try:                                 # provisional fallback (live-unknown)
                ts_us = _to_num(self.command("TS"))
                dt = int(time_resolution) * float(ts_us) * 1e-6
            except Exception:
                dt = 0.0
        out["dt"] = dt
        return out

    def disconnect(self):
        if self._comm:
            try:
                self._comm.Disconnect()
            finally:
                self._comm = None


def _map_upload_data(signals, by_key):
    """Map UploadRecordingData().Data to signal names.

    LIVE-CONFIRMED (2026-07-13, autotune run #4): the Data dictionary keys are
    POSITIONAL indices 0..N-1 in the order the signals were placed into
    RecordingSetup.SignalData — NOT the personality SignalIndex (a 6-signal
    request returned keys [0..5] while 'A Voltage' has SignalIndex 19).
    Raises IOError when the key set is not exactly {0..N-1} (unexpected
    count/order — never guess a partial mapping)."""
    n = len(signals)
    if set(by_key.keys()) != set(range(n)):
        raise IOError("recording upload keys %s != positional 0..%d for %d signals"
                      % (sorted(by_key.keys()), n - 1, n))
    return {name: by_key[i] for i, name in enumerate(signals)}


def _reflect_recorder():
    """No-hardware STRUCTURAL check of the .NET recording surface we depend on
    (docs/recording-api.md): types constructible, properties settable, enums
    resolvable, interface members present.  Returns {check_name: bool}.
    Actual recording needs a connected drive and is NOT exercised here."""
    asm = _load_assembly()
    import ElmoMotionControlComponents.Drive.EASComponents.Recording as REC
    import ElmoMotionControlComponents.Drive.EASComponents.Personality as PERS
    from System.Collections.Generic import List
    from System import Enum
    types = {t.Name: t for t in asm.GetExportedTypes()}
    checks = {}

    setup = REC.RecordingSetup()
    setup.TimeResolution = 2
    setup.RecordingLength = 4000
    checks["RecordingSetup ctor+props"] = (int(setup.TimeResolution) == 2
                                           and int(setup.RecordingLength) == 4000)
    trig = REC.TriggerSetup()
    trig.SetupType = REC.TriggerSetupType.Immediate
    setup.TriggerSetup = trig
    checks["TriggerSetupType.Immediate set"] = \
        setup.TriggerSetup.SetupType == REC.TriggerSetupType.Immediate
    sig = PERS.RecordingSignalSetup()
    lst = List[PERS.RecordingSignalSetup]()
    lst.Add(sig)
    setup.SignalData = lst
    checks["SignalData List<RecordingSignalSetup>"] = int(setup.SignalData.Count) == 1
    checks["RecordingSignalSetup Name/SignalIndex props"] = all(
        types["RecordingSignalSetup"].GetProperty(p) is not None
        for p in ("Name", "SignalIndex"))

    rec_methods = {m.Name for m in types["IDriveRecording"].GetMethods()}
    checks["IDriveRecording methods"] = {
        "ConfigureRecording", "StartRecording", "GetRecordingStatus",
        "UploadRecordingData", "StopRecorder"} <= rec_methods
    checks["RecordingStatus enum values"] = {
        "ROff", "RWait", "REnd", "RProgress"} <= set(Enum.GetNames(types["RecordingStatus"]))
    checks["RecordingData.Data property"] = \
        types["RecordingData"].GetProperty("Data") is not None
    comm_methods = {m.Name for m in types["IDriveCommunication"].GetMethods()}
    checks["CreatePersonalityModel on IDriveCommunication"] = \
        "CreatePersonalityModel" in comm_methods
    checks["GetRecordingObject on IDriveCommunication"] = \
        "GetRecordingObject" in comm_methods
    checks["PersonalityModel property"] = \
        types["IDriveCommunication"].GetProperty("PersonalityModel") is not None
    checks["SignalsMetaData property"] = \
        types["DrivePersonalityModel"].GetProperty("SignalsMetaData") is not None

    # --- personality upload flow (live-confirmed 2026-07-13) --------------------------
    checks["UploadPersonality on IUploadDownload"] = any(
        m.Name == "UploadPersonality" and m.ReturnType.Name == "IUploadDownloadModel"
        for m in types["IUploadDownload"].GetMethods())
    checks["UploadPersonality on DriveUSBCommunication"] = any(
        m.Name == "UploadPersonality"
        for m in types["DriveUSBCommunication"].GetMethods())
    up = types["IUploadDownloadModel"]
    checks["IUploadDownloadModel 5 events"] = {
        "OnStart", "OnProgress", "OnFinish", "OnFailed", "OnCancel"} <= \
        {e.Name for e in up.GetEvents()}
    checks["IUploadDownloadModel Start(out err)->bool"] = any(
        m.Name == "Start" and m.ReturnType.Name == "Boolean"
        and len(m.GetParameters()) == 1
        and m.GetParameters()[0].ParameterType.Name.startswith("IDriveErrorObject")
        for m in up.GetMethods())
    checks["OperationStatus property"] = up.GetProperty("OperationStatus") is not None
    checks["OPERATION_STATUS enum values"] = {
        "UNDEFINED", "STARTED", "FINISHED", "FAILED", "PROGRESSED", "CANCELED"} <= \
        set(Enum.GetNames(types["OPERATION_STATUS"]))
    checks["IDriveErrorObject 4 members"] = {
        "ErrorCode", "LibraryErrorCode", "ErrorDescription",
        "LibraryErrorDescription"} <= \
        {p.Name for p in types["IDriveErrorObject"].GetProperties()}
    return checks


def _reflect():
    """No-hardware sanity check: load the DLL and confirm the key USB API exists."""
    sys.stdout.reconfigure(encoding="utf-8")
    asm = _load_assembly()
    print("LOADED:", asm.FullName)
    names = {t.FullName.split(".")[-1] for t in asm.GetExportedTypes()}
    need = {"DriveCommunicationFactory", "IDriveCommunication", "DriveUSBCommunication",
            "DriveRecording" if "DriveRecording" in names else "IDriveRecording"}
    print("key types present:", {n: (n in names) for n in
          ["DriveCommunicationFactory", "IDriveCommunication", "DriveUSBCommunication", "IDriveRecording"]})
    return True


if __name__ == "__main__":
    # Default: reflection only (safe, no hardware). Live connect is a separate,
    # supervised step — COM3 must be free (EAS III disconnected).
    _reflect()
