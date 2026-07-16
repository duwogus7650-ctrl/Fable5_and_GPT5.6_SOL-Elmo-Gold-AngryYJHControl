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
import hashlib
import json
import math
import re
import threading
import time
import uuid
import zipfile

import persistence_audit

# --- locate / stage the vendored DLLs -------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_LIBDIR = os.path.join(_HERE, "lib_net")
_STATE_DIR = os.path.join(_HERE, ".omc", "state")   # diagnostics dumps (recorder signals)
_USER_STATE_ROOT = (os.environ.get("LOCALAPPDATA")
                    or os.path.join(os.path.expanduser("~"), ".local", "state"))
_SAFETY_STATE_DIR = os.path.join(
    _USER_STATE_ROOT, "AngryYJHControl", "safety")
_MAIN_DLL_NAME = "ElmoMotionControlComponents.Drive.EASComponents.dll"
_ZIP = os.path.join(_HERE, "vendor", "elmo-downloads", "Drive .NET Library 1.0.0.8.zip")
_RECORDER_UNKNOWN_PATH = os.path.join(_STATE_DIR, "recorder_unknown.json")
# Safety authority must survive checkout changes and must not live in a
# OneDrive-synchronised repository.  Every updated app copy for this user
# therefore shares this one LOCALAPPDATA ledger.
_PERSISTENCE_UNKNOWN_PATH = os.path.join(
    _SAFETY_STATE_DIR, "persistence_unknown.json")
_UNKNOWN_DRIVE_IDENTITY = "identity-unavailable"

_MOTOR_TARGET_REGISTERS = (
    "PL[1]", "CL[1]", "VH[2]", "CA[19]", "CA[28]",
)
_MOTOR_PROFILE_REGISTERS = _MOTOR_TARGET_REGISTERS + (
    "CA[18]", "MC", "UM",
)
_MOTOR_INTEGER_REGISTERS = frozenset((
    "VH[2]", "CA[19]", "CA[28]", "CA[18]", "UM",
))
_MOTOR_TYPE_ENUM = frozenset((0, 1, 2, 3, 4, 6))
_MOTOR_SAFETY_REGISTERS = ("MO", "SO", "VX", "PS", "MF")


class TelemetrySnapshotError(IOError):
    """A required telemetry query did not produce one complete finite sample."""

    def __init__(self, field, command, detail):
        super().__init__(
            "telemetry %s (%s) unavailable: %s" %
            (str(field), str(command), str(detail)))
        self.field = str(field)
        self.command = str(command)


class DisconnectCleanupError(RuntimeError):
    """One or more independent disconnect obligations did not complete."""

    def __init__(self, failures):
        normalized = tuple((str(phase), exc) for phase, exc in failures)
        detail = "; ".join(
            "%s: %s: %s" % (phase, type(exc).__name__, exc)
            for phase, exc in normalized)
        super().__init__("disconnect cleanup incomplete: %s" % detail)
        self.failures = normalized


def _load_recorder_unknown_ports():
    try:
        with open(_RECORDER_UNKNOWN_PATH, encoding="utf-8") as handle:
            payload = json.load(handle)
        ports = payload.get("ports", {})
        return dict(ports) if isinstance(ports, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_recorder_unknown_ports(ports):
    os.makedirs(os.path.dirname(_RECORDER_UNKNOWN_PATH), exist_ok=True)
    temp = _RECORDER_UNKNOWN_PATH + ".tmp"
    with open(temp, "w", encoding="utf-8", newline="") as handle:
        json.dump({"schema": "angryyjh-recorder-unknown/v2", "ports": ports},
                  handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp, _RECORDER_UNKNOWN_PATH)


def _recorder_unknown_records(ports, port):
    """Return the identity-keyed records for one port, migrating v1 in memory."""
    port_key = str(port)
    payload = ports.get(port_key)
    if not isinstance(payload, dict):
        return {}
    records = payload.get("records")
    if isinstance(records, dict):
        return dict(records)
    # v1 stored one reason record directly under the COM port.  It did not
    # prove drive identity, so it must remain fail-closed and cannot be cleared
    # automatically by whichever drive happens to appear on that port.
    identity = payload.get("drive_identity") or _UNKNOWN_DRIVE_IDENTITY
    return {str(identity): {"reason": str(payload.get("reason", "unknown"))}}


def _latch_recorder_unknown(port, reason, drive_identity=None):
    ports = _load_recorder_unknown_ports()
    records = _recorder_unknown_records(ports, port)
    identity = str(drive_identity or _UNKNOWN_DRIVE_IDENTITY)
    records[identity] = {"reason": str(reason)}
    ports[str(port)] = {"records": records}
    _write_recorder_unknown_ports(ports)


def _clear_recorder_unknown(port, drive_identity):
    """Clear only the exact proven drive record; never clear by COM port alone."""
    if not drive_identity:
        raise RuntimeError("Recorder recovery identity is unavailable")
    ports = _load_recorder_unknown_ports()
    records = _recorder_unknown_records(ports, port)
    identity = str(drive_identity)
    if identity not in records:
        raise RuntimeError(
            "Recorder recovery identity does not match the latched drive")
    del records[identity]
    if records:
        ports[str(port)] = {"records": records}
    else:
        ports.pop(str(port), None)
    _write_recorder_unknown_ports(ports)


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
_NON_MO_MOTION_PREFIXES = tuple(
    prefix for prefix in _MOTION_PREFIXES if prefix != "MO=1")


def _command_guard_core(cmd: str) -> str:
    """Canonical command used only for safety classification.

    Exactly one normal trailing semicolon is treated as a terminator.  The
    caller still passes the original, unmodified string to the vendor API.
    """
    if not isinstance(cmd, str):
        raise TypeError("drive command must be str")
    canonical = "".join(cmd.split()).upper()
    return canonical[:-1] if canonical.endswith(";") else canonical


def _validate_single_vendor_command(cmd: str) -> None:
    """Reject possible multi-command separators before vendor I/O."""
    if not isinstance(cmd, str):
        raise TypeError("drive command must be str")
    if any(ord(ch) < 32 for ch in cmd) or any(
            ch in cmd for ch in ("\u2028", "\u2029")):
        raise ValueError("control/newline separators are not allowed")
    stripped = cmd.strip()
    semicolons = stripped.count(";")
    if semicolons and (semicolons != 1 or not stripped.endswith(";")):
        raise ValueError(
            "multiple or embedded command separators are not allowed")


def _is_motion_command(core: str) -> bool:
    """Fail-closed classification for power-enable and motion commands."""
    if core.startswith("MO="):
        raw_value = core[3:]
        try:
            value = float(raw_value)
        except (TypeError, ValueError, OverflowError):
            return True
        # Only a finite numeric zero is a proven disable operation.  Every
        # nonzero/nonfinite spelling is power-enable capable and motion-gated.
        return not math.isfinite(value) or value != 0.0
    return any(core.startswith(prefix)
               for prefix in _NON_MO_MOTION_PREFIXES)


def _is_safe_deenergizing_command(core: str) -> bool:
    """Return True only for narrowly proven software shutdown commands."""
    if core == "ST":
        return True
    for prefix in ("MO=", "TC="):
        if core.startswith(prefix):
            try:
                value = float(core[len(prefix):])
            except (TypeError, ValueError, OverflowError):
                return False
            return math.isfinite(value) and value == 0.0
    return False


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


def _drive_numeric_literal(value) -> str:
    """Return a deterministic finite numeric literal for one drive command."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("drive numeric literal must be finite")
    if number.is_integer():
        return str(int(number))
    return repr(number)


def _normalize_motor_writes(writes) -> dict[str, float]:
    """Validate the complete Motor v1 target before any vendor I/O."""
    if not isinstance(writes, dict) or set(writes) != set(_MOTOR_TARGET_REGISTERS):
        raise ValueError(
            "Motor profile must contain exactly %s" %
            (_MOTOR_TARGET_REGISTERS,))
    normalized = {}
    for register in _MOTOR_TARGET_REGISTERS:
        value = writes[register]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("%s must be numeric" % register)
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("%s must be finite" % register)
        if register in {"PL[1]", "CL[1]"} and number <= 0.0:
            raise ValueError("%s must be positive" % register)
        if register in {"VH[2]", "CA[19]"}:
            if not number.is_integer() or number <= 0.0:
                raise ValueError("%s must be a positive integer" % register)
        if register == "VH[2]" and number > 2**31 - 1:
            raise ValueError("VH[2] must not exceed 2^31-1")
        if register == "CA[28]":
            if not number.is_integer() or int(number) not in _MOTOR_TYPE_ENUM:
                raise ValueError(
                    "CA[28] must be one of 0,1,2,3,4,6 (5 is reserved)")
        normalized[register] = number
    if normalized["CL[1]"] > normalized["PL[1]"]:
        raise ValueError("CL[1] must not exceed PL[1]")
    return normalized


class ElmoLink:
    """Read-oriented transport to a single Gold drive over USB (default COM3)."""

    def __init__(self, com_port: str = "COM3"):
        self.com_port = com_port
        self._comm = None
        self._factory = None
        self._transaction_session_token = object()
        self._connection_epoch = None
        # Link-wide safety latch shared by every P1/P2 persistence caller.
        # It deliberately survives disconnect/connect on this object: an SV
        # timeout may mean flash completed even though the reply was lost.
        self._persistence_unknown_latched = False
        self._prepared_persistence_attempt_id = None
        self._acknowledged_persistence_attempt_id = None
        # Serializes capability adjudication, consumption, and vendor I/O.
        # In particular two concurrent callers can never consume one SV
        # capability twice.
        self._persistence_command_lock = threading.RLock()
        self._persistence_ledger = persistence_audit.PersistenceLedger(
            _PERSISTENCE_UNKNOWN_PATH)
        self._persistence_record = None
        self._persistence_ledger_error = None
        self._persistence_other_active_count = 0
        self._connected_firmware_context = {
            "firmware": None, "pal": None, "boot": None}
        self._last_recorder_error = None   # human-readable reason recorder_signals()==None
        self._rec_pending = None
        self._personality_provenance = {}
        self._connected_drive_identity = None
        self._recorder_recovery_record = None
        self._refresh_persistence_state()
        self._refresh_recorder_recovery_state()

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
        # One token per successful transport session.  A disconnect/reconnect on
        # the same ElmoLink object must invalidate every prior GREEN capability.
        self._transaction_session_token = object()
        self._connection_epoch = str(uuid.uuid4())
        self._prepared_persistence_attempt_id = None
        self._acknowledged_persistence_attempt_id = None
        # Do not issue an implicit drive command here.  The worker's explicit
        # read-only identity handshake calls transaction_identity(); until then
        # any recorder marker on this port remains conservatively latched.
        self._connected_drive_identity = None
        self._connected_firmware_context = {
            "firmware": None, "pal": None, "boot": None}
        self._refresh_persistence_state()
        self._refresh_recorder_recovery_state()
        return True

    @property
    def is_connected(self) -> bool:
        return bool(self._comm and self._comm.IsConnected)

    def transaction_session_identity(self):
        """Return an opaque token for this exact live transport session.

        The token intentionally changes on every successful connect and on
        disconnect.  It is process-local and carries no persistence claim.
        """
        return self._transaction_session_token if self.is_connected else None

    def _refresh_persistence_state(self):
        """Refresh the identity-bound durable persistence safety state.

        A corrupt or unreadable ledger is a global fail-closed condition.  An
        unresolved record for another proven identity is retained as evidence
        but does not grant that record authority over the current drive.
        """
        try:
            snapshot = self._persistence_ledger.load()
        except persistence_audit.PersistenceAuditError as exc:
            self._persistence_record = None
            self._persistence_other_active_count = 0
            self._persistence_ledger_error = (
                "%s: %s" % (type(exc).__name__, exc))
            return
        self._persistence_ledger_error = None
        active = dict(snapshot.active)
        identity = self._connected_drive_identity
        if identity is not None:
            record = active.get(str(identity))
            self._persistence_other_active_count = (
                len(active) - (1 if record is not None else 0))
        else:
            # Before the read-only SN[4] handshake, any active record is a
            # conservative lock.  SN[4]/VR/VP/VB queries remain permitted.
            record = next(iter(active.values()), None)
            self._persistence_other_active_count = max(
                0, len(active) - (1 if record is not None else 0))
        self._persistence_record = record

    def persistence_unknown_latched(self) -> bool:
        """Whether an earlier SV response made persistence ambiguous.

        Disconnect/reconnect never clears this latch.  A separate reset and
        durability-audit workflow must create the authority to proceed; this
        transport intentionally exposes no implicit clear operation.
        """
        self._refresh_persistence_state()
        return bool(self._persistence_unknown_latched
                    or self._persistence_ledger_error
                    or self._persistence_record is not None)

    def latch_persistence_unknown(self) -> None:
        """Block later SV and enable/motion I/O on this link instance."""
        self._persistence_unknown_latched = True

    def persistence_status(self) -> dict:
        """Return a JSON-safe summary without exposing raw drive identity."""
        self._refresh_persistence_state()
        record = self._persistence_record
        if self._persistence_ledger_error:
            status = "LEDGER_CORRUPT_OR_UNREADABLE"
            detail = ("Persistence safety ledger is untrusted; all mutating "
                      "commands remain locked")
        elif record is not None:
            status = "PERSISTENCE_UNKNOWN"
            detail = ("%s bounded-profile persistence requires operator-attested "
                      "power-cycle/reset and a read-only audit" % record.phase)
        elif self._persistence_unknown_latched:
            status = "RUNTIME_UNKNOWN_NO_LEDGER"
            detail = ("Runtime persistence ambiguity has no auditable durable "
                      "profile; writes remain locked")
        elif self._persistence_other_active_count:
            status = "OTHER_DRIVE_UNKNOWN"
            detail = ("%d unresolved record(s) belong to other drive identities"
                      % self._persistence_other_active_count)
        else:
            status = "CLEAR"
            detail = "No active persistence incident for this drive"
        return {
            "status": status,
            "lock_active": bool(
                self._persistence_unknown_latched
                or self._persistence_ledger_error
                or record is not None),
            "detail": detail,
            "record_id": record.record_id if record is not None else None,
            "phase": record.phase if record is not None else None,
            "record_state": record.state if record is not None else None,
            "identity_proven": self._connected_drive_identity is not None,
            "other_active_count": int(self._persistence_other_active_count),
            "ledger_error": self._persistence_ledger_error,
        }

    def recorder_recovery_unknown_latched(self) -> bool:
        """Whether a prior disconnect lost Recorder Stop confirmation."""
        return bool(self._recorder_recovery_unknown)

    def _refresh_recorder_recovery_state(self):
        """Bind durable unknown state to the drive identity, not only the port.

        Identity-less legacy records remain fail-closed.  A record for drive A
        is retained but does not block or get cleared by a proven different
        drive B using the same COM port.
        """
        ports = _load_recorder_unknown_ports()
        records = _recorder_unknown_records(ports, self.com_port)
        identity = self._connected_drive_identity
        record = None
        if records:
            if identity and str(identity) in records:
                record = records[str(identity)]
            elif _UNKNOWN_DRIVE_IDENTITY in records:
                record = records[_UNKNOWN_DRIVE_IDENTITY]
            elif not identity:
                record = next(iter(records.values()))
        self._recorder_recovery_record = record
        self._recorder_recovery_unknown = record is not None

    def transaction_identity(self):
        """Return a stable opaque drive identity derived from read-only SN[4].

        The raw serial value is never exposed by this API.  Unavailable,
        malformed, or non-finite identity data returns ``None``; callers may
        still complete a same-session transaction but must refuse reconnect
        adoption because drive identity cannot then be proven.
        """
        try:
            raw = self.command("SN[4]")
        except Exception:
            return None
        if raw is None:
            return None
        token = str(raw).strip().rstrip(";").strip()
        if not token:
            return None
        # SN[4] is an opaque serial token, not a numeric quantity.  Preserve
        # significant leading zeros while normalizing only presentation noise.
        canonical = " ".join(token.split()).casefold()
        if not canonical or canonical in {
                "nan", "+nan", "-nan", "inf", "+inf", "-inf",
                "infinity", "+infinity", "-infinity"}:
            return None
        digest = hashlib.sha256(
            ("Elmo:SN[4]\0" + canonical).encode("utf-8")).hexdigest()
        identity = "elmo-sn4-sha256:" + digest
        self._connected_drive_identity = identity
        self._refresh_persistence_state()
        self._refresh_recorder_recovery_state()
        return identity

    def prepare_persistence_attempt(
            self, *, phase, registers, original, applied,
            initial_state="PERSISTING") -> str:
        """Durably journal one frozen profile transaction.

        This method performs filesystem I/O only.  It never sends a drive
        command.  P1/P2 start in ``PERSISTING`` immediately before ``SV``;
        Motor starts in ``RAM_APPLYING`` before its first assignment.
        """
        if not self.is_connected:
            raise RuntimeError("persistence journal requires a live connection")
        if self.persistence_unknown_latched():
            raise RuntimeError("persistence state UNKNOWN; new SV is blocked")
        expected = persistence_audit.PHASE_REGISTERS.get(str(phase))
        if expected is None or tuple(registers) != tuple(expected):
            raise ValueError("persistence register set does not match phase")
        identity = self._connected_drive_identity
        epoch = self._connection_epoch
        context = dict(self._connected_firmware_context)
        if not identity:
            raise RuntimeError("stable drive identity was not captured")
        if not epoch:
            raise RuntimeError("connection epoch is unavailable")
        if any(not context.get(name) for name in ("firmware", "pal", "boot")):
            raise RuntimeError("VR/VP/VB context was not captured")
        session = self.transaction_session_identity()
        record = self._persistence_ledger.prepare(
            phase=str(phase),
            drive_identity=str(identity),
            com_port=str(self.com_port),
            firmware=str(context["firmware"]),
            pal=str(context["pal"]),
            boot=str(context["boot"]),
            connect_epoch=str(epoch),
            registers=tuple(registers),
            original=original,
            applied=applied,
            initial_state=str(initial_state),
        )
        self._refresh_persistence_state()
        if (not self.is_connected
                or self.transaction_session_identity() is not session
                or self._connection_epoch != epoch):
            try:
                self._persistence_ledger.mark_unknown(
                    record.record_id, "SESSION_CHANGED_AFTER_PREPARE")
            finally:
                self._persistence_unknown_latched = True
                self._refresh_persistence_state()
            raise RuntimeError(
                "connection changed after persistence journal prepare")
        self._prepared_persistence_attempt_id = record.record_id
        self._acknowledged_persistence_attempt_id = None
        return record.record_id

    def mark_persistence_attempt_persisting(self, record_id) -> None:
        """Advance a verified RAM profile to the single-use SV boundary."""
        record = self._require_matching_persistence_record(record_id)
        if (not self.is_connected
                or record.connect_epoch != self._connection_epoch
                or self._prepared_persistence_attempt_id != record.record_id):
            raise RuntimeError(
                "persistence transition lacks a prepared same-session attempt")
        self._persistence_ledger.mark_persisting(str(record_id))
        self._refresh_persistence_state()

    def resolve_persistence_ram_rollback(self, record_id) -> None:
        """Archive a pre-SV Motor attempt after exact RAM restoration."""
        record = self._require_matching_persistence_record(record_id)
        if (not self.is_connected
                or record.connect_epoch != self._connection_epoch
                or self._prepared_persistence_attempt_id != record.record_id):
            raise RuntimeError(
                "RAM rollback close-out lacks a prepared same-session attempt")
        self._persistence_ledger.resolve_ram_rollback(str(record_id))
        self._prepared_persistence_attempt_id = None
        self._acknowledged_persistence_attempt_id = None
        self._refresh_persistence_state()

    def _require_matching_persistence_record(self, record_id):
        self._refresh_persistence_state()
        record = self._persistence_record
        if (record is None or self._connected_drive_identity is None
                or record.drive_identity != self._connected_drive_identity
                or record.record_id != str(record_id)):
            raise RuntimeError(
                "persistence record is not bound to the current drive identity")
        return record

    def complete_persistence_attempt(self, record_id) -> None:
        """Archive a prepared record only after a definite successful reply."""
        record = self._require_matching_persistence_record(record_id)
        if (not self.is_connected
                or record.connect_epoch != self._connection_epoch
                or self._acknowledged_persistence_attempt_id != record.record_id):
            raise RuntimeError(
                "SV success close-out lacks an acknowledged same-session attempt")
        self._persistence_ledger.resolve_sv_success(str(record_id))
        self._prepared_persistence_attempt_id = None
        self._acknowledged_persistence_attempt_id = None
        self._refresh_persistence_state()

    def mark_persistence_attempt_unknown(self, record_id, reason) -> None:
        """Retain the pre-SV record after an ambiguous transport outcome."""
        self._require_matching_persistence_record(record_id)
        try:
            self._persistence_ledger.mark_unknown(
                str(record_id), str(reason) or "UNKNOWN")
        finally:
            self._prepared_persistence_attempt_id = None
            self._acknowledged_persistence_attempt_id = None
            self._persistence_unknown_latched = True
            self._refresh_persistence_state()

    @staticmethod
    def _audit_failure(status, detail, summary=None):
        summary = dict(summary or {})
        return {
            "status": str(status),
            "resolved": False,
            "detail": str(detail),
            "lock_active": bool(summary.get("lock_active", True)),
            "record_id": summary.get("record_id"),
            "phase": summary.get("phase"),
            "other_active_count": int(summary.get("other_active_count", 0)),
            "ledger_error": summary.get("ledger_error"),
        }

    def audit_persistence_after_reset(
            self, operator_reset_attested: bool) -> dict:
        """Run the query-only post-reset P1/P2 gain-profile audit.

        No reset is sent here.  In particular this path never issues SV, LD,
        RS, an assignment, an enable, or a motion command.  A resolved result
        names only the durable gain profile observed after the operator-
        attested reset; it does not prove which ambiguous SV caused it.
        """
        summary = self.persistence_status()
        if summary.get("ledger_error"):
            return self._audit_failure(
                "LEDGER_CORRUPT_OR_UNREADABLE",
                "Persistence ledger is untrusted and was not modified", summary)
        if operator_reset_attested is not True:
            return self._audit_failure(
                "RESET_NOT_ATTESTED",
                "USB reconnect alone does not prove that flash was reloaded",
                summary)
        identity = self._connected_drive_identity
        if not identity:
            return self._audit_failure(
                "IDENTITY_UNAVAILABLE", "SN[4] identity is unavailable", summary)
        try:
            record = self._persistence_ledger.active_for_identity(identity)
        except persistence_audit.PersistenceAuditError as exc:
            self._refresh_persistence_state()
            return self._audit_failure(
                "LEDGER_CORRUPT_OR_UNREADABLE", str(exc),
                self.persistence_status())
        if record is None:
            return self._audit_failure(
                "NO_MATCHING_RECORD",
                "No active persistence incident belongs to this drive identity",
                summary)
        if self._connection_epoch == record.connect_epoch:
            return self._audit_failure(
                "SESSION_NOT_CHANGED",
                "A new connection after the attested reset is required", summary)

        def fresh_context():
            before = self.transaction_session_identity()
            current_identity = self.transaction_identity()
            for command in ("VR", "VP", "VB"):
                self.command(command)
            after = self.transaction_session_identity()
            if before is None or after is not before:
                raise RuntimeError("transport session changed during context reads")
            return {
                "drive_identity": current_identity,
                "firmware": self._connected_firmware_context["firmware"],
                "pal": self._connected_firmware_context["pal"],
                "boot": self._connected_firmware_context["boot"],
                "connect_epoch": self._connection_epoch,
            }

        try:
            context_values = fresh_context()
            audit_context = persistence_audit.AuditContext.from_mapping(
                context_values)
        except Exception as exc:
            return self._audit_failure(
                "CONTEXT_READ_FAILED", str(exc), self.persistence_status())

        # Abort before gain comparison when identity or exact software context
        # is stale.  The pure adjudicator remains the canonical status owner.
        placeholder = {name: 1.0 for name in record.registers}
        placeholder.update({"MO": 0.0, "SO": 0.0, "VX": 0.0})
        preflight = persistence_audit.adjudicate_read_only(
            record, audit_context, placeholder, True)
        if preflight.status in {
                "IDENTITY_MISMATCH", "FIRMWARE_MISMATCH", "PAL_MISMATCH",
                "BOOT_MISMATCH", "SESSION_NOT_CHANGED"}:
            result = preflight.to_dict()
            result.update({
                "lock_active": True, "phase": record.phase,
                "record_id": record.record_id,
                "other_active_count": summary.get("other_active_count", 0),
                "ledger_error": None})
            return result

        commands = ("MO", "SO", "VX", "PS", "MF") + record.registers

        def fresh_snapshot():
            token = self.transaction_session_identity()
            values = {}
            for command in commands:
                values[command] = _to_num(self.command(command))
            if token is None or self.transaction_session_identity() is not token:
                raise RuntimeError("transport session changed during readback")
            return values

        try:
            first = fresh_snapshot()
            second = fresh_snapshot()
            final_context = fresh_context()
        except Exception as exc:
            return self._audit_failure(
                "READBACK_FAILED", str(exc), self.persistence_status())
        if context_values != final_context:
            return self._audit_failure(
                "SESSION_OR_CONTEXT_CHANGED",
                "identity/software context changed during the audit",
                self.persistence_status())
        for observed in (first, second):
            candidate = persistence_audit.adjudicate_read_only(
                record, audit_context,
                {name: observed[name]
                 for name in ("MO", "SO", "VX") + record.registers},
                True)
            if candidate.status in {
                    "READBACK_INVALID", "DRIVE_NOT_DISABLED_STATIONARY"}:
                result = candidate.to_dict()
                result.update({
                    "record_id": record.record_id,
                    "lock_active": True,
                    "phase": record.phase,
                    "other_active_count": summary.get(
                        "other_active_count", 0),
                    "ledger_error": None,
                })
                return result
        if first != second:
            return self._audit_failure(
                "READBACK_UNSTABLE",
                "two query-only snapshots were not identical",
                self.persistence_status())
        ps, mf = second.get("PS"), second.get("MF")
        if (isinstance(ps, bool) or not isinstance(ps, (int, float))
                or float(ps) not in (-2.0, -1.0)):
            return self._audit_failure(
                "DRIVE_STATE_INVALID", "PS must be -2 or -1", summary)
        if (isinstance(mf, bool) or not isinstance(mf, (int, float))
                or not math.isfinite(float(mf))):
            return self._audit_failure(
                "DRIVE_STATE_INVALID", "MF must be a finite readback", summary)
        audit_readback = {
            name: second[name]
            for name in ("MO", "SO", "VX") + record.registers}
        decision = persistence_audit.adjudicate_read_only(
            record, audit_context, audit_readback, True)
        result = decision.to_dict()
        if decision.resolved:
            try:
                audit_evidence = persistence_audit.build_audit_evidence(
                    record, audit_context, first, second, True,
                    decision.resolution)
                self._persistence_ledger.resolve_from_audit(
                    record.record_id, decision, audit_evidence)
            except Exception as exc:
                self._persistence_unknown_latched = True
                self._refresh_persistence_state()
                return self._audit_failure(
                    "LEDGER_CLOSEOUT_FAILED",
                    "Readback resolved, but durable archive failed: %s" % exc,
                    self.persistence_status())
            self._persistence_unknown_latched = False
            self._refresh_persistence_state()
        current = self.persistence_status()
        result.update({
            "record_id": record.record_id,
            "lock_active": current["lock_active"],
            "phase": record.phase,
            "other_active_count": current["other_active_count"],
            "ledger_error": current["ledger_error"],
        })
        return result

    def command(self, cmd: str, timeout_ms: int = 1000,
                allow_motion: bool = False,
                _persistence_attempt_id=None) -> str:
        """Send a 2-letter Elmo command, return the drive's textual response.

        Motion/power-enabling commands are refused unless allow_motion=True.
        ``_persistence_attempt_id`` is an internal, record-bound capability
        used by the P1/P2/Motor persistence engines for authorized RAM
        assignments and the one-shot ``SV``; normal callers must omit it.
        """
        with self._persistence_command_lock:
            return self._command_locked(
                cmd, timeout_ms=timeout_ms, allow_motion=allow_motion,
                persistence_attempt_id=_persistence_attempt_id)

    def _command_locked(self, cmd: str, *, timeout_ms: int,
                        allow_motion: bool,
                        persistence_attempt_id=None) -> str:
        """Adjudicate and execute one command while the link mutex is held."""
        core = _command_guard_core(cmd)
        _validate_single_vendor_command(cmd)
        is_sv = core == "SV"
        is_motion = _is_motion_command(core)
        safe_deenergizing = _is_safe_deenergizing_command(core)
        persistence_unknown = self.persistence_unknown_latched()
        prepared = self._persistence_record
        authorized_sv = bool(
            is_sv and prepared is not None
            and self._persistence_ledger_error is None
            and str(persistence_attempt_id) == prepared.record_id
            and self._prepared_persistence_attempt_id == prepared.record_id
            and prepared.drive_identity == self._connected_drive_identity
            and prepared.connect_epoch == self._connection_epoch
            and prepared.state == "PERSISTING")

        assignment_register = None
        assignment_value = None
        if "=" in core and core.count("=") == 1:
            assignment_register, literal = core.split("=", 1)
            try:
                assignment_value = float(literal)
            except (TypeError, ValueError, OverflowError):
                assignment_value = None
        authorized_motor_assignment = bool(
            prepared is not None
            and prepared.phase == "MOTOR"
            and prepared.state == "RAM_APPLYING"
            and self._persistence_ledger_error is None
            and str(persistence_attempt_id) == prepared.record_id
            and self._prepared_persistence_attempt_id == prepared.record_id
            and prepared.drive_identity == self._connected_drive_identity
            and prepared.connect_epoch == self._connection_epoch
            and assignment_register in _MOTOR_TARGET_REGISTERS
            and assignment_value is not None
            and math.isfinite(assignment_value)
            and any(assignment_value == float(profile[assignment_register])
                    for profile in (prepared.original, prepared.applied)))

        if is_sv and not authorized_sv:
            if persistence_unknown:
                raise RuntimeError(
                    "command blocked: persistence state UNKNOWN on this link")
            raise RuntimeError(
                "SV requires a prepared persistence transaction")
        persistence_mutation = (
            is_sv or is_motion or "=" in core or core in {"LD", "RS", "XQ"})
        if (persistence_unknown and persistence_mutation
                and not safe_deenergizing
                and not authorized_sv
                and not authorized_motor_assignment):
            raise RuntimeError(
                "command blocked: persistence state UNKNOWN on this link")
        if not self._comm:
            raise RuntimeError("not connected")
        if not allow_motion and is_motion:
            raise PermissionError(f"refused motion/power command without allow_motion=True: {cmd!r}")
        if authorized_sv:
            # Consume before vendor I/O so no exception path can repeat SV.
            self._prepared_persistence_attempt_id = None
            self._acknowledged_persistence_attempt_id = None
        # SendCommandAnalyzeError(command, OUT response, OUT errorObj, timeout).
        # pythonnet needs placeholders passed for the OUT params ("", None);
        # returns (retval, response, errorObj).
        try:
            ok, response, err = self._comm.SendCommandAnalyzeError(
                cmd, "", None, timeout_ms)
        except Exception:
            if is_sv:
                self.latch_persistence_unknown()
            raise
        if not ok:
            if is_sv:
                self.latch_persistence_unknown()
            raise IOError(f"drive/library error on {cmd!r}: {err}")
        if authorized_sv:
            self._acknowledged_persistence_attempt_id = prepared.record_id
        if core in {"VR", "VP", "VB"}:
            value = str(response).strip().rstrip(";").strip()
            if core == "VP":
                try:
                    number = float(value)
                    if math.isfinite(number) and number.is_integer():
                        value = str(int(number))
                except (TypeError, ValueError, OverflowError):
                    pass
            key = {"VR": "firmware", "VP": "pal", "VB": "boot"}[core]
            self._connected_firmware_context[key] = value or None
        return response

    # --- read-only telemetry (grounded from Gold Line Command Reference) --------------
    # PX Main Position [cnt], VX Main Feedback Velocity [cnt/s], PE Position Error [cnt],
    # IQ Active Current [A], MO Motor On state (0/1). All are read-only when queried
    # without '=' (a bare mnemonic returns the current value).
    _TELEMETRY = (("pos", "PX"), ("vel", "VX"), ("pos_err", "PE"),
                  ("iq", "IQ"), ("mo", "MO"))

    def read_telemetry(self) -> dict:
        """Return one complete finite snapshot or raise ``TelemetrySnapshotError``.

        Treating a failed ``MO`` query as false is unsafe: it makes an unknown
        drive state look torque-disabled.  A snapshot therefore has authority
        only when every required bare query succeeds in the same polling cycle.
        Monotonic timing metadata lets the worker reject an excessively slow,
        mixed-age sample without relying on the wall clock.
        """
        started = time.monotonic()
        out = {}
        for key, cmd in self._TELEMETRY:
            try:
                value = _to_num(self.command(cmd))
            except Exception as exc:
                raise TelemetrySnapshotError(
                    key, cmd, "%s: %s" % (type(exc).__name__, exc)) from exc
            if (isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))):
                raise TelemetrySnapshotError(
                    key, cmd, "non-finite or non-numeric response %r" % (value,))
            out[key] = value
        if float(out["mo"]) not in (0.0, 1.0):
            raise TelemetrySnapshotError(
                "mo", "MO", "unexpected state %r (expected 0 or 1)" % out["mo"])
        out["mo"] = int(float(out["mo"]))
        finished = time.monotonic()
        out["_sample_started_monotonic"] = started
        out["_sample_finished_monotonic"] = finished
        out["_sample_duration_s"] = finished - started
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

    def read_platform_clock(self) -> dict:
        """Read-only platform grounding for the duty-count full scale (autotune
        G0).  CR grounding: XP[2] sets TS*f_pwm = XP[2]/2 (default 2, p.325
        table); WS[54]/WS[56]/WS[57] = max/min/range PWM command in 150 MHz
        clock counts (p.291); WS[53] converts internal units to bus voltage
        (float).  FS_counts = 150e6*TS_s/XP[2] (fable-physics run #8 — live
        mid=3750 at TS=100us, XP[2]=2).  Missing values come back as None."""
        g = lambda c: _to_num(self.command(c))
        out = {}
        for key, cmd in (("ts_us", "TS"), ("xp2", "XP[2]"), ("ws53", "WS[53]"),
                         ("ws54", "WS[54]"), ("ws56", "WS[56]"), ("ws57", "WS[57]")):
            try:
                out[key] = g(cmd)
            except Exception:
                out[key] = None
        try:
            out["fs_counts"] = 150e6 * (out["ts_us"] * 1e-6) / out["xp2"]
        except Exception:
            out["fs_counts"] = None
        return out

    def write_motor_params(self, writes: dict, persist: bool = True,
                           expected_ca18=None):
        """Serialize one complete Motor transaction on this communication link."""
        with self._persistence_command_lock:
            return self._write_motor_params_locked(
                writes, persist=persist, expected_ca18=expected_ca18)

    def _write_motor_params_locked(self, writes: dict, persist: bool = True,
                                   expected_ca18=None):
        """Apply and persist the fixed Motor v1 profile transactionally.

        A durable ``RAM_APPLYING`` record precedes the first RAM mutation.
        Every assignment is read back.  A pre-SV failure restores touched
        registers in reverse order and proves the complete original profile;
        only a verified applied profile may advance to one single-use ``SV``.
        This is a bounded Motor-profile claim, not a whole-drive flash claim.
        """
        try:
            desired = _normalize_motor_writes(writes)
        except (TypeError, ValueError) as exc:
            return (False, "Motor profile rejected before I/O: %s" % exc)
        if expected_ca18 is not None:
            if (isinstance(expected_ca18, bool)
                    or not isinstance(expected_ca18, (int, float))
                    or not math.isfinite(float(expected_ca18))
                    or not float(expected_ca18).is_integer()
                    or float(expected_ca18) <= 0.0):
                return (False,
                        "Motor CA[18] conversion basis is invalid before I/O")
            expected_ca18 = float(expected_ca18)
        if persist is not True:
            return (False,
                    "Motor RAM-only write is not exposed; durable transaction required")
        if self.persistence_unknown_latched():
            return (False,
                    "Persistence UNKNOWN - Motor write blocked before RAM mutation")
        if (not self._connected_drive_identity or not self._connection_epoch
                or any(not self._connected_firmware_context.get(name)
                       for name in ("firmware", "pal", "boot"))):
            return (False,
                    "Motor transaction requires the identity and VR/VP/VB handshake")

        session = self.transaction_session_identity()

        def finite_snapshot():
            values = {}
            for register in _MOTOR_SAFETY_REGISTERS + _MOTOR_PROFILE_REGISTERS:
                value = _to_num(self.command(register))
                if (isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))):
                    raise ValueError("%s must be finite numeric" % register)
                values[register] = float(value)
            if (session is None
                    or self.transaction_session_identity() is not session):
                raise RuntimeError("transport session changed during Motor snapshot")
            return values

        def operational_state_valid(snapshot):
            return (snapshot["MO"] == 0.0
                    and snapshot["SO"] == 0.0
                    and snapshot["VX"] == 0.0
                    and snapshot["PS"] in (-2.0, -1.0)
                    and snapshot["MF"] == 0.0)

        def profile_of(snapshot):
            return {name: snapshot[name]
                    for name in _MOTOR_PROFILE_REGISTERS}

        try:
            first = finite_snapshot()
            second = finite_snapshot()
        except Exception as exc:
            return (False, "Motor preflight read failed: %s" % exc)
        if first != second:
            return (False, "Motor preflight rejected: two snapshots were unstable")
        if not operational_state_valid(second):
            return (False,
                    "MO=SO=VX=MF=0 and PS=-2/-1 are required")
        ca18 = second["CA[18]"]
        mc = second["MC"]
        um = second["UM"]
        if not ca18.is_integer() or ca18 <= 0.0:
            return (False, "CA[18] must be a fresh positive integer")
        if expected_ca18 is not None and ca18 != expected_ca18:
            return (False,
                    "CA[18] changed since the RPM preview; refresh and confirm again")
        if not math.isfinite(mc) or mc <= 0.0:
            return (False, "MC must be finite and positive")
        if not um.is_integer() or int(um) not in {2, 3, 5}:
            return (False, "UM must be a supported exact mode (2, 3, or 5)")
        if desired["PL[1]"] > mc or desired["CL[1]"] >= mc:
            return (False, "PL[1] must be <= MC and CL[1] must be < MC")
        if int(desired["CA[28]"]) in {1, 3} and int(um) == 3:
            return (False, "CA[28] 1/3 is incompatible with UM=3")

        original = profile_of(second)
        applied = dict(original)
        applied.update(desired)
        if all(applied[name] == original[name]
               for name in _MOTOR_TARGET_REGISTERS):
            return (True, "NO_CHANGE - no RAM assignment or SV was issued")

        try:
            record_id = self.prepare_persistence_attempt(
                phase="MOTOR",
                registers=_MOTOR_PROFILE_REGISTERS,
                original=original,
                applied=applied,
                initial_state="RAM_APPLYING")
        except Exception as exc:
            return (False, "Motor WAL prepare failed before RAM mutation: %s" % exc)

        decreasing = [
            name for name in ("CL[1]", "PL[1]", "VH[2]")
            if applied[name] < original[name]]
        static = [
            name for name in ("CA[19]", "CA[28]")
            if applied[name] != original[name]]
        increasing = [
            name for name in ("VH[2]", "PL[1]", "CL[1]")
            if applied[name] > original[name]]
        write_plan = decreasing + static + increasing
        touched = []

        def read_exact(register, expected):
            observed = _to_num(self.command(register))
            return (not isinstance(observed, bool)
                    and isinstance(observed, (int, float))
                    and math.isfinite(float(observed))
                    and float(observed) == float(expected))

        def assert_safe_mutation_boundary(context):
            """Query the exact no-motion/no-fault gate at a RAM-write boundary.

            This is the closest software-only guard available to a serial
            command.  It does not replace exclusive ownership of every other
            EAS/CAN/EtherCAT controller that can enable the same drive.
            """
            state = {}
            for register in _MOTOR_SAFETY_REGISTERS:
                value = _to_num(self.command(register))
                if (isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(float(value))):
                    raise RuntimeError(
                        "%s: %s safety readback is invalid" %
                        (context, register))
                state[register] = float(value)
            if (session is None
                    or self.transaction_session_identity() is not session):
                raise RuntimeError(
                    "%s: transport session changed" % context)
            if not operational_state_valid(state):
                raise RuntimeError(
                    "%s: MO=SO=VX=MF=0 and PS=-2/-1 are required" %
                    context)
            return state

        def mark_unknown(reason):
            try:
                self.mark_persistence_attempt_unknown(record_id, reason)
            except Exception:
                self.latch_persistence_unknown()
                self._refresh_persistence_state()

        def rollback_after(pre_sv_error):
            rollback_errors = []
            for register in reversed(touched):
                literal = _drive_numeric_literal(original[register])
                try:
                    assert_safe_mutation_boundary(
                        "before rollback %s" % register)
                except Exception as exc:
                    rollback_errors.append(
                        "%s safety gate: %s" %
                        (register, type(exc).__name__))
                    # Never continue issuing rollback assignments after the
                    # drive becomes enabled, moving, faulted, or session-stale.
                    break
                try:
                    self.command(
                        "%s=%s" % (register, literal),
                        _persistence_attempt_id=record_id)
                except Exception as exc:
                    rollback_errors.append(
                        "%s write: %s" % (register, type(exc).__name__))
                try:
                    if not read_exact(register, original[register]):
                        rollback_errors.append("%s readback mismatch" % register)
                except Exception as exc:
                    rollback_errors.append(
                        "%s readback: %s" % (register, type(exc).__name__))
            try:
                restored_first = finite_snapshot()
                restored_second = finite_snapshot()
                restored = (restored_first == restored_second
                            and operational_state_valid(restored_second)
                            and profile_of(restored_second) == original)
            except Exception as exc:
                restored = False
                rollback_errors.append(
                    "full readback: %s" % type(exc).__name__)
            if restored and not rollback_errors:
                try:
                    self.resolve_persistence_ram_rollback(record_id)
                    return (False,
                            "Motor apply failed; RAM rollback verified; no SV: %s"
                            % pre_sv_error)
                except Exception as exc:
                    rollback_errors.append(
                        "rollback archive: %s" % type(exc).__name__)
            reason = "RAM_ROLLBACK_UNKNOWN: %s; %s" % (
                pre_sv_error, "; ".join(rollback_errors) or "unverified")
            mark_unknown(reason)
            return (False,
                    "Motor RAM state UNKNOWN after rollback; no SV was issued: %s"
                    % reason)

        try:
            # WAL file I/O can take long enough for another controller to alter
            # state.  Re-prove the frozen preflight profile after the journal is
            # durable and before the first local mutation.
            post_wal = finite_snapshot()
            if post_wal != second:
                reason = (
                    "POST_WAL_STATE_CHANGED: full Motor/safety snapshot no "
                    "longer matches frozen preflight")
                mark_unknown(reason)
                return (False,
                        "Motor RAM authority UNKNOWN before first assignment; "
                        "no rollback or SV was issued: %s" % reason)
            for register in write_plan:
                assert_safe_mutation_boundary(
                    "before forward assignment %s" % register)
                touched.append(register)
                self.command(
                    "%s=%s" % (
                        register, _drive_numeric_literal(applied[register])),
                    _persistence_attempt_id=record_id)
                if not read_exact(register, applied[register]):
                    raise RuntimeError("%s applied readback mismatch" % register)
                # Detect an enable/fault transition that happened after the
                # closest pre-send query.  Rollback will itself remain gated.
                assert_safe_mutation_boundary(
                    "after forward assignment %s" % register)
            applied_first = finite_snapshot()
            applied_second = finite_snapshot()
            if (applied_first != applied_second
                    or not operational_state_valid(applied_second)
                    or profile_of(applied_second) != applied):
                raise RuntimeError("complete applied Motor profile was not stable")
            self.mark_persistence_attempt_persisting(record_id)
        except Exception as exc:
            return rollback_after("%s: %s" % (type(exc).__name__, exc))

        # The durable state transition itself performs filesystem I/O.  Recheck
        # both the complete applied profile and the exact no-motion/no-fault
        # gate after that boundary, then place one final safety-only query as
        # close as the serial protocol permits to SV.  Once PERSISTING is
        # durable, a failed gate cannot safely regain RAM rollback authority;
        # retain UNKNOWN and require reset/readback instead.
        try:
            pre_sv = finite_snapshot()
            if (not operational_state_valid(pre_sv)
                    or profile_of(pre_sv) != applied):
                raise RuntimeError(
                    "post-PERSISTING Motor/safety snapshot changed")
            assert_safe_mutation_boundary("immediately before SV")
        except Exception as exc:
            reason = "PRE_SV_GATE_FAILED: %s: %s" % (
                type(exc).__name__, exc)
            mark_unknown(reason)
            return (False,
                    "Motor persistence UNKNOWN before SV; SV was not issued: %s"
                    % reason)

        try:
            self.command("SV", _persistence_attempt_id=record_id)
        except Exception as exc:
            mark_unknown("SV_OUTCOME_UNKNOWN: %s: %s" %
                         (type(exc).__name__, exc))
            return (False,
                    "Motor persistence UNKNOWN after single SV; do not retry: %s"
                    % exc)
        try:
            self.complete_persistence_attempt(record_id)
        except Exception as exc:
            self.latch_persistence_unknown()
            self._refresh_persistence_state()
            return (False,
                    "Motor SV acknowledged but durable close-out is UNKNOWN: %s"
                    % exc)
        return (True,
                "Motor profile applied, read back, and persisted by one SV")

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
        """Fail closed until the sensor-specific persistence contract exists."""
        return (False,
                "Feedback durable transaction is locked until the versioned "
                "sensor write-contract registry is implemented")

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
    # Official code example: SamplingTime is TS in µs; dt=TimeResolution*TS.
    # Target-specific post-Configure mutation remains live-unknown and is checked.
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

    @staticmethod
    def _sha256_path(path):
        try:
            with open(path, "rb") as handle:
                return hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            return None

    @staticmethod
    def _personality_version_text(path):
        try:
            with open(path, "rb") as handle:
                prefix = handle.read(8192).decode("ascii", errors="ignore")
        except OSError:
            return None
        match = re.search(r"<version>\s*(.*?)\s*</version>", prefix, re.I | re.S)
        return " ".join(match.group(1).split()) if match else None

    def _personality_cache_matches_drive(self, path):
        version = self._personality_version_text(path)
        if not version:
            return False, None
        try:
            firmware = " ".join(
                str(self.command("VR")).strip().rstrip(";").split())
            pal = int(float(str(self.command("VP")).strip().rstrip(";")))
        except Exception:
            return False, version
        if not firmware:
            return False, version
        pal_match = re.search(r"\bPal\s*:\s*(\d+)\b", version, re.I)
        personality_firmware = (
            version[:pal_match.start()].strip() if pal_match is not None else "")
        matches = (personality_firmware.casefold() == firmware.casefold()
                   and pal_match is not None
                   and int(pal_match.group(1)) == pal)
        return matches, version

    def _signal_catalog_sha256(self, model):
        try:
            rows = []
            for kv in self._signals_meta_of(model):
                signal = kv.Value
                rows.append((int(kv.Key), str(signal.Name),
                             str(getattr(signal, "CategoryName", "") or ""),
                             str(getattr(signal, "Classification", "") or "")))
            payload = "\n".join("\t".join(map(str, row)) for row in sorted(rows))
            return hashlib.sha256(payload.encode("utf-8")).hexdigest()
        except Exception:
            return None

    def _set_personality_provenance(self, model, *, source, path=None,
                                    version=None, identity_verified=False):
        drive_identity = self.transaction_identity()
        self._personality_provenance = {
            "source": source,
            "firmware_personality_match": bool(identity_verified),
            "stable_drive_identity_present": bool(drive_identity),
            "version": version,
            "xml_path": os.path.abspath(path) if path else None,
            "xml_sha256": self._sha256_path(path) if path else None,
            "signal_catalog_sha256": self._signal_catalog_sha256(model),
            "drive_identity": drive_identity,
        }

    def recorder_personality_provenance(self):
        """Return source/hash/identity evidence for the active signal catalog."""
        if not self._personality_provenance:
            self._personality()
        return dict(self._personality_provenance)

    @staticmethod
    def recorder_library_provenance():
        path = os.path.join(_LIBDIR, _MAIN_DLL_NAME)
        return {
            "artifact": _MAIN_DLL_NAME,
            "path": os.path.abspath(path),
            "sha256": ElmoLink._sha256_path(path),
        }

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
            if not self._personality_provenance:
                self._set_personality_provenance(
                    model, source="connected_communication_model",
                    identity_verified=False)
            return model
        path = self._personality_xml_path
        cache_matches, version = self._personality_cache_matches_drive(path)
        if os.path.isfile(path) and cache_matches:
            model = self._try_create_personality(path)
            if model is not None:
                self._set_personality_provenance(
                    model, source="cache_identity_matched", path=path,
                    version=version, identity_verified=True)
                self._dump_recorder_signals(model)
                return model
        if not self._upload_personality(path):
            return None
        model = self._try_create_personality(path)
        if model is not None:
            upload_matches, upload_version = (
                self._personality_cache_matches_drive(path))
            self._set_personality_provenance(
                model, source="drive_upload_current_session", path=path,
                version=upload_version, identity_verified=upload_matches)
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

    def record_start(
            self, signals, length, time_resolution: int = 1,
            *, sampling_time_us=None):
        """ARM the .NET recorder and return immediately (Phase-2 split: the
        recorder free-runs while the caller keeps sending TC/JV/VX commands).

        Flow (docs/recording-api.md): GetRecordingObject -> RecordingSetup(
        TimeResolution/RecordingLength/SignalData/TriggerSetup.SetupType=
        Immediate) -> ConfigureRecording -> StartRecording.  State is kept on
        the link for the matching record_fetch().  Raises on failure."""
        if not self._comm:
            raise RuntimeError("not connected")
        if self._recorder_recovery_unknown:
            raise RuntimeError(
                "prior Recorder cleanup is UNKNOWN; execute Recorder Stop recovery first")
        if getattr(self, "_rec_pending", None):
            raise RuntimeError("recorder already has an active/pending capture")
        names = [str(name) for name in signals]
        if not names or any(not name for name in names):
            raise ValueError("at least one exact recorder signal is required")
        resolution = int(time_resolution)
        sample_count = int(length)
        if resolution <= 0 or sample_count <= 0:
            raise ValueError("time_resolution and length must be positive integers")
        if sampling_time_us is None:
            sampling_time_us = _to_num(self.command("TS"))
        try:
            ts_us = float(sampling_time_us)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("TS sampling time must be finite and positive") from exc
        if not math.isfinite(ts_us) or ts_us <= 0:
            raise ValueError("TS sampling time must be finite and positive")
        REC, PERS = self._rec_ns()
        setups = self._signal_setups(names)
        rec = self._comm.GetRecordingObject()
        setup = REC.RecordingSetup()
        # Official DriveDotNetRecording example semantics: SamplingTime is TS
        # in microseconds; the interval is TimeResolution × SamplingTime.
        setup.SamplingTime = ts_us
        setup.TimeResolution = resolution
        setup.RecordingLength = sample_count
        from System.Collections.Generic import List
        sig_list = List[PERS.RecordingSignalSetup]()
        for s in setups:
            sig_list.Add(s)
        setup.SignalData = sig_list
        trig = REC.TriggerSetup()
        trig.SetupType = REC.TriggerSetupType.Immediate
        setup.TriggerSetup = trig
        # Establish ownership *before* either vendor call.  Configure/Start can
        # time out after a side effect; only Recorder Stop or a proven terminal
        # status may release this handle.
        pending = {"obj": rec, "setup": setup, "REC": REC,
                   "signals": names,
                   "length": sample_count,
                   "sampling_time_us": ts_us,
                   "time_resolution": resolution,
                   "drive_identity": (
                       self._connected_drive_identity
                       or self.transaction_identity()),
                   "phase": "CONFIGURING_UNKNOWN"}
        self._rec_pending = pending
        try:
            configured = rec.ConfigureRecording(setup)
        except Exception:
            pending["phase"] = "CONFIGURE_RESULT_UNKNOWN"
            raise
        if not configured:
            # StartRecording was never called; an explicit Configure false is
            # the only pre-start result treated as proven not armed.
            self._rec_pending = None
            raise IOError("ConfigureRecording returned false; recorder not started")
        pending["phase"] = "START_RESULT_UNKNOWN"
        try:
            started = rec.StartRecording()
        except Exception:
            raise
        if not started:
            raise IOError(
                "StartRecording returned false; outcome retained UNKNOWN until Recorder Stop")
        pending["phase"] = "RECORDING"

    def record_status(self) -> str:
        """Return a normalized non-blocking recorder state.

        ``OFF`` is intentionally not called success or cancel: the vendor enum
        does not preserve the cause, so the caller must keep its own reason.
        """
        pend = getattr(self, "_rec_pending", None)
        if not pend:
            return "IDLE"
        status = pend["obj"].GetRecordingStatus()
        enum = pend["REC"].RecordingStatus
        if status == enum.REnd:
            return "READY_TO_UPLOAD"
        if status == enum.RProgress:
            return "RECORDING"
        if status == enum.RWait:
            return "WAITING_FOR_TRIGGER"
        if status == enum.ROff:
            return "OFF"
        return "UNKNOWN:%s" % status

    def record_upload(self) -> dict:
        """Upload one completed capture without waiting and clear it on success."""
        import numpy as np
        pend = getattr(self, "_rec_pending", None)
        if not pend:
            raise RuntimeError("record_upload without record_start")
        status = self.record_status()
        if status != "READY_TO_UPLOAD":
            raise RuntimeError("recording is not ready to upload (status=%s)" % status)
        rec, setup = pend["obj"], pend["setup"]
        try:
            configured_ts_us = float(pend["sampling_time_us"])
            reported_ts_us = float(setup.SamplingTime)
            resolution = int(pend["time_resolution"])
            reported_resolution = int(setup.TimeResolution)
            expected_length = int(pend["length"])
            reported_length = int(setup.RecordingLength)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise IOError("Recorder timing provenance is unavailable") from exc
        if (not math.isfinite(configured_ts_us) or configured_ts_us <= 0
                or not math.isfinite(reported_ts_us) or reported_ts_us <= 0
                or resolution <= 0 or reported_resolution <= 0
                or expected_length <= 0 or reported_length <= 0):
            raise IOError("Recorder timing contains a non-finite/non-positive value")
        if not math.isclose(
                reported_ts_us, configured_ts_us,
                rel_tol=1e-9, abs_tol=1e-9):
            raise IOError(
                "Recorder SamplingTime readback %.12g us disagrees with configured TS %.12g us"
                % (reported_ts_us, configured_ts_us))
        if reported_resolution != resolution:
            raise IOError(
                "Recorder TimeResolution readback %d disagrees with configured %d"
                % (reported_resolution, resolution))
        if reported_length != expected_length:
            raise IOError(
                "Recorder RecordingLength readback %d disagrees with configured %d"
                % (reported_length, expected_length))
        dt = resolution * configured_ts_us * 1e-6
        if not math.isfinite(dt) or dt <= 0:
            raise IOError("Recorder sample interval is invalid")
        data = rec.UploadRecordingData()
        by_key = {}
        for kv in data.Data:
            by_key[int(kv.Key)] = np.array(list(kv.Value), dtype=float)
        out = _map_upload_data(pend["signals"], by_key)
        expected = expected_length
        invalid = []
        for name in pend["signals"]:
            values = out[name]
            if len(values) != expected:
                invalid.append("%s length=%d expected=%d" %
                               (name, len(values), expected))
            elif not np.isfinite(values).all():
                invalid.append("%s contains non-finite samples" % name)
        if invalid:
            pend["last_invalid_upload"] = out
            raise IOError("invalid Recorder upload: %s" % "; ".join(invalid))
        out["dt"] = dt
        self._rec_pending = None
        return out

    @staticmethod
    def _verify_recorder_terminal_after_stop(rec, enum):
        """Require an observed inactive Recorder state after StopRecorder()."""
        import time as _time
        last = None
        for attempt in range(6):
            last = rec.GetRecordingStatus()
            if last in (enum.ROff, enum.REnd):
                return last
            if attempt < 5:
                _time.sleep(0.02)
        raise IOError(
            "StopRecorder returned without terminal status confirmation "
            "(status=%s)" % last)

    def record_stop(self) -> bool:
        """Cancel only the drive Recorder; this is not a motor stop.

        A no-exception vendor return is not sufficient evidence.  Ownership is
        released only after ROff/REnd is read back from the same recorder.
        """
        pend = getattr(self, "_rec_pending", None)
        if not pend:
            if not self._recorder_recovery_unknown:
                return False
            if not self._comm:
                raise RuntimeError(
                    "Recorder recovery requires a live communication session")
            current_identity = (
                self._connected_drive_identity or self.transaction_identity())
            records = _recorder_unknown_records(
                _load_recorder_unknown_ports(), self.com_port)
            if (not current_identity
                    or str(current_identity) not in records):
                raise RuntimeError(
                    "Recorder recovery refused: current drive identity does not "
                    "match the durable unknown record")
            rec = self._comm.GetRecordingObject()
            rec.StopRecorder()
            REC, _PERS = self._rec_ns()
            self._verify_recorder_terminal_after_stop(
                rec, REC.RecordingStatus)
            _clear_recorder_unknown(self.com_port, current_identity)
            self._refresh_recorder_recovery_state()
            return True
        pend["obj"].StopRecorder()
        self._verify_recorder_terminal_after_stop(
            pend["obj"], pend["REC"].RecordingStatus)
        self._rec_pending = None
        return True

    def recorder_has_pending(self) -> bool:
        """Whether this link still owns a recorder handle or unknown start."""
        return bool(self._rec_pending)

    def record_fetch(self, timeout_s: float = 10.0, poll_s: float = 0.02) -> dict:
        """WAIT for the armed recording to finish and upload it.

        Returns {name: np.ndarray (physical doubles), 'dt': float seconds}.
        Poll GetRecordingStatus()==REnd (ROff=error; timeout -> StopRecorder)
        -> UploadRecordingData().Data (Dict<int, Double[]>, already physical).
        Data keys are POSITIONAL 0..N-1 in SignalData request order — NOT the
        personality SignalIndex (LIVE-CONFIRMED on run #4).
        dt: TimeResolution × configured/read-back SamplingTime(=TS µs) × 1e-6,
        per the official DriveDotNetRecording example."""
        import time as _time
        import numpy as np
        if not getattr(self, "_rec_pending", None):
            raise RuntimeError("record_fetch without record_start")
        t0 = _time.time()
        while True:
            st = self.record_status()
            if st == "READY_TO_UPLOAD":
                break
            if st == "OFF":
                raise IOError("recorder status ROff (error/cancelled)")
            if _time.time() - t0 > timeout_s:
                try:
                    self.record_stop()
                except Exception:
                    pass
                raise TimeoutError("recording not finished in %.1fs (status=%s)"
                                   % (timeout_s, st))
            _time.sleep(poll_s)
        return self.record_upload()

    def record(self, signals, length, time_resolution: int = 1,
               timeout_s: float = 10.0, poll_s: float = 0.02) -> dict:
        """Blocking record = record_start + record_fetch (Phase-1 compatible
        wrapper — existing callers/tests unchanged)."""
        self.record_start(signals, length, time_resolution)
        return self.record_fetch(timeout_s=timeout_s, poll_s=poll_s)

    def disconnect(self):
        failures = []
        comm = self._comm
        try:
            if comm is not None:
                try:
                    if getattr(self, "_rec_pending", None):
                        pending_identity = self._connected_drive_identity
                        identity_failure = None
                        try:
                            pending_identity = (
                                self._rec_pending.get("drive_identity")
                                or pending_identity
                                or self.transaction_identity())
                        except Exception as exc:
                            # Identity evidence is useful for a drive-specific
                            # durable latch, but it must never prevent Recorder
                            # Stop or the independent transport Disconnect.
                            identity_failure = exc
                        try:
                            self.record_stop()
                        except Exception as stop_exc:
                            self._last_recorder_error = (
                                "Recorder cleanup before disconnect remained "
                                "UNKNOWN: %s" % stop_exc)
                            if identity_failure is not None:
                                self._last_recorder_error += (
                                    "; drive identity lookup also failed: %s"
                                    % identity_failure)
                            self._recorder_recovery_unknown = True
                            try:
                                _latch_recorder_unknown(
                                    self.com_port, type(stop_exc).__name__,
                                    pending_identity)
                            except Exception as latch_exc:
                                # A Stop failure is normally handled by the
                                # durable UNKNOWN latch.  If the latch itself
                                # also fails, retain every contributing error.
                                if identity_failure is not None:
                                    failures.append((
                                        "Recorder drive-identity lookup",
                                        identity_failure))
                                failures.extend((
                                    ("Recorder Stop", stop_exc),
                                    ("Recorder UNKNOWN latch", latch_exc),
                                ))
                                self._last_recorder_error += (
                                    "; durable UNKNOWN latch failed: %s"
                                    % latch_exc)
                except Exception as exc:
                    # Last-resort containment: no unexpected recorder cleanup
                    # bug may bypass the independent transport teardown.
                    failures.append(("Recorder disconnect cleanup", exc))
                finally:
                    try:
                        comm.Disconnect()
                    except Exception as exc:
                        failures.append(("vendor Disconnect", exc))
        finally:
            # Clear every transport/session authority before surfacing any
            # cleanup error.  A failed vendor Disconnect is therefore never
            # represented as a usable local session.
            self._comm = None
            self._factory = None
            # The communication session is gone; this object can no longer
            # operate or retry the vendor recorder handle.
            self._rec_pending = None
            self._personality_provenance = {}
            self._connected_drive_identity = None
            self._prepared_persistence_attempt_id = None
            self._acknowledged_persistence_attempt_id = None
            self._transaction_session_token = object()
            self._connection_epoch = None
            self._connected_firmware_context = {
                "firmware": None, "pal": None, "boot": None}
            try:
                self._refresh_persistence_state()
            except Exception as exc:
                failures.append(("local persistence-state refresh", exc))

        if failures:
            error = DisconnectCleanupError(failures)
            raise error from failures[0][1]


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
