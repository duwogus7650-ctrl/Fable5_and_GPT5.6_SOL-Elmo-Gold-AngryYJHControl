"""Crash-safe persistence UNKNOWN ledger and read-only adjudication.

This module deliberately performs no drive I/O.  A caller must durably prepare
an incident *before* issuing ``SV`` and may then either archive the acknowledged
result or retain an UNKNOWN incident.  Reconnect audit is a pure comparison of
already-read values; it never claims which particular ``SV`` caused a durable
profile to exist.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
import re
import tempfile
import uuid


_LOCK_TIMEOUT_S = 5.0
_PROCESS_MUTEXES: dict[str, threading.RLock] = {}
_PROCESS_MUTEXES_GUARD = threading.Lock()


LEDGER_SCHEMA = "angryyjh-persistence-ledger/v2"
AUDIT_EVIDENCE_SCHEMA = "angryyjh-persistence-audit-evidence/v1"
DEFAULT_RTOL = 1e-3
PHASE_REGISTERS = MappingProxyType({
    "P1": ("KP[1]", "KI[1]"),
    "P2": ("KP[2]", "KI[2]", "KP[3]"),
    "MOTOR": (
        "PL[1]", "CL[1]", "VH[2]", "CA[19]", "CA[28]",
        "CA[18]", "MC", "UM",
    ),
})

_ACTIVE_STATES = frozenset(("RAM_APPLYING", "PERSISTING", "UNKNOWN"))
_RESOLUTIONS = frozenset((
    "SV_ACKNOWLEDGED",
    "RAM_ROLLBACK_VERIFIED",
    "APPLIED_PROFILE_AFTER_RESET",
    "ORIGINAL_PROFILE_AFTER_RESET",
))
_MOTOR_INTEGER_REGISTERS = frozenset((
    "VH[2]", "CA[19]", "CA[28]", "CA[18]", "UM",
))
_MOTOR_POSITIVE_REGISTERS = frozenset((
    "PL[1]", "CL[1]", "VH[2]", "CA[19]", "CA[18]", "MC",
))
_MOTOR_TYPE_ENUM = frozenset((0, 1, 2, 3, 4, 6))
_MOTOR_VH2_MAX = (1 << 31) - 1
_IDENTITY_RE = re.compile(r"^elmo-sn4-sha256:[0-9a-f]{64}$")
_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RECORD_KEYS = frozenset((
    "record_id", "phase", "state", "drive_identity", "com_port",
    "firmware", "pal", "boot", "connect_epoch", "registers",
    "original", "applied", "rtol", "created_utc", "updated_utc",
    "resolved_utc", "resolution", "reason", "audit_evidence",
))


class PersistenceAuditError(RuntimeError):
    """Base error for the durable persistence safety boundary."""


class LedgerIntegrityError(PersistenceAuditError):
    """The on-disk ledger cannot be trusted and must be treated as active."""


class LedgerUnreadableError(PersistenceAuditError):
    """The ledger exists but could not be read."""


class LedgerWriteError(PersistenceAuditError):
    """An atomic ledger state change was not durably verified."""


class ActiveIncidentError(PersistenceAuditError):
    """A drive identity already owns an unresolved persistence incident."""


class RecordNotFoundError(PersistenceAuditError):
    """No active incident has the requested record id."""


def _require_nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("%s must be a non-empty exact string" % name)
    return value


def _require_identity(value: Any) -> str:
    value = _require_nonempty_string(value, "drive_identity")
    if _IDENTITY_RE.fullmatch(value) is None:
        raise ValueError("drive_identity must be an opaque SN[4] SHA-256 identity")
    return value


def _require_uuid(value: Any, name: str, *, version: int | None = None) -> str:
    value = _require_nonempty_string(value, name)
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("%s must be a canonical UUID string" % name) from exc
    if str(parsed) != value.lower() or (version is not None and parsed.version != version):
        raise ValueError("%s must be a canonical UUID%s string" % (
            name, ("v%d" % version) if version is not None else ""))
    return value.lower()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="microseconds").replace("+00:00", "Z")


def _require_utc(value: Any, name: str) -> str:
    value = _require_nonempty_string(value, name)
    if not value.endswith("Z"):
        raise ValueError("%s must be an explicit UTC timestamp" % name)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("%s must be an ISO-8601 UTC timestamp" % name) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("%s must be UTC" % name)
    return value


def _require_profile(
        values: Any, registers: tuple[str, ...], name: str,
        phase: str) -> dict:
    if not isinstance(values, Mapping) or set(values) != set(registers):
        raise ValueError("%s must contain exactly %s" % (name, registers))
    result = {}
    for register in registers:
        value = values[register]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("%s[%s] must be numeric" % (name, register))
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("%s[%s] must be finite" % (name, register))
        if phase in {"P1", "P2"} and number <= 0.0:
            raise ValueError("%s[%s] must be finite and positive" %
                             (name, register))
        if phase == "MOTOR":
            if register in _MOTOR_INTEGER_REGISTERS and not number.is_integer():
                raise ValueError("%s[%s] must be an integer" %
                                 (name, register))
            if register in _MOTOR_POSITIVE_REGISTERS and number <= 0.0:
                raise ValueError("%s[%s] must be finite and positive" %
                                 (name, register))
            if register == "CA[28]" and int(number) not in _MOTOR_TYPE_ENUM:
                raise ValueError(
                    "%s[CA[28]] must be one of %s" %
                    (name, tuple(sorted(_MOTOR_TYPE_ENUM))))
            if register == "VH[2]" and number > _MOTOR_VH2_MAX:
                raise ValueError(
                    "%s[VH[2]] must not exceed %d" %
                    (name, _MOTOR_VH2_MAX))
        result[register] = number
    if phase == "MOTOR":
        if result["CL[1]"] > result["PL[1]"]:
            raise ValueError("%s CL[1] must not exceed PL[1]" % name)
        if result["PL[1]"] > result["MC"]:
            raise ValueError("%s PL[1] must not exceed MC" % name)
        if result["CL[1]"] >= result["MC"]:
            raise ValueError("%s CL[1] must be strictly less than MC" % name)
        if int(result["UM"]) not in {2, 3, 5}:
            raise ValueError("%s UM must be one of 2, 3 or 5" % name)
        if int(result["CA[28]"]) in {1, 3} and int(result["UM"]) == 3:
            raise ValueError("%s CA[28] 1/3 is incompatible with UM=3" % name)
    return result


@dataclass(frozen=True)
class PersistenceRecord:
    """One immutable active or archived persistence incident."""

    record_id: str
    phase: str
    state: str
    drive_identity: str
    com_port: str
    firmware: str
    pal: str
    boot: str
    connect_epoch: str
    registers: tuple[str, ...]
    original: Mapping[str, float]
    applied: Mapping[str, float]
    rtol: float
    created_utc: str
    updated_utc: str
    resolved_utc: str | None = None
    resolution: str | None = None
    reason: str | None = None
    audit_evidence: Mapping[str, Any] | None = None

    def __post_init__(self):
        record_id = _require_uuid(self.record_id, "record_id", version=4)
        if self.phase not in PHASE_REGISTERS:
            raise ValueError("phase must be P1, P2 or MOTOR")
        registers = tuple(self.registers)
        if registers != PHASE_REGISTERS[self.phase]:
            raise ValueError("registers do not match phase %s" % self.phase)
        if self.state not in _ACTIVE_STATES and self.state != "RESOLVED":
            raise ValueError("unsupported incident state %r" % self.state)
        identity = _require_identity(self.drive_identity)
        com_port = _require_nonempty_string(self.com_port, "com_port")
        firmware = _require_nonempty_string(self.firmware, "firmware")
        pal = _require_nonempty_string(self.pal, "pal")
        boot = _require_nonempty_string(self.boot, "boot")
        connect_epoch = _require_uuid(self.connect_epoch, "connect_epoch")
        if (isinstance(self.rtol, bool)
                or not isinstance(self.rtol, (int, float))
                or not math.isfinite(float(self.rtol))
                or float(self.rtol) != DEFAULT_RTOL):
            raise ValueError("rtol must be exactly %.9g" % DEFAULT_RTOL)
        original = _require_profile(
            self.original, registers, "original", self.phase)
        applied = _require_profile(
            self.applied, registers, "applied", self.phase)
        created_utc = _require_utc(self.created_utc, "created_utc")
        updated_utc = _require_utc(self.updated_utc, "updated_utc")
        if self.reason is not None and not isinstance(self.reason, str):
            raise ValueError("reason must be a string or null")

        if self.state == "RESOLVED":
            if self.resolution not in _RESOLUTIONS:
                raise ValueError("resolved record has invalid resolution")
            if self.resolved_utc is None:
                raise ValueError("resolved record lacks resolved_utc")
            resolved_utc = _require_utc(self.resolved_utc, "resolved_utc")
        else:
            if self.resolution is not None or self.resolved_utc is not None:
                raise ValueError("active record cannot carry resolution fields")
            resolved_utc = None

        if self.resolution in {
                "APPLIED_PROFILE_AFTER_RESET",
                "ORIGINAL_PROFILE_AFTER_RESET"}:
            audit_evidence = _validate_audit_evidence(
                self.audit_evidence, record=self,
                expected_resolution=self.resolution)
        else:
            if self.audit_evidence is not None:
                raise ValueError(
                    "audit_evidence is allowed only for a post-reset resolution")
            audit_evidence = None

        object.__setattr__(self, "record_id", record_id)
        object.__setattr__(self, "drive_identity", identity)
        object.__setattr__(self, "com_port", com_port)
        object.__setattr__(self, "firmware", firmware)
        object.__setattr__(self, "pal", pal)
        object.__setattr__(self, "boot", boot)
        object.__setattr__(self, "connect_epoch", connect_epoch)
        object.__setattr__(self, "registers", registers)
        object.__setattr__(self, "original", MappingProxyType(original))
        object.__setattr__(self, "applied", MappingProxyType(applied))
        object.__setattr__(self, "rtol", float(self.rtol))
        object.__setattr__(self, "created_utc", created_utc)
        object.__setattr__(self, "updated_utc", updated_utc)
        object.__setattr__(self, "resolved_utc", resolved_utc)
        object.__setattr__(self, "audit_evidence", audit_evidence)

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "phase": self.phase,
            "state": self.state,
            "drive_identity": self.drive_identity,
            "com_port": self.com_port,
            "firmware": self.firmware,
            "pal": self.pal,
            "boot": self.boot,
            "connect_epoch": self.connect_epoch,
            "registers": list(self.registers),
            "original": dict(self.original),
            "applied": dict(self.applied),
            "rtol": self.rtol,
            "created_utc": self.created_utc,
            "updated_utc": self.updated_utc,
            "resolved_utc": self.resolved_utc,
            "resolution": self.resolution,
            "reason": self.reason,
            "audit_evidence": (
                _deep_thaw(self.audit_evidence)
                if self.audit_evidence is not None else None),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "PersistenceRecord":
        if not isinstance(value, Mapping) or set(value) != _RECORD_KEYS:
            raise ValueError("record fields are missing or unexpected")
        return cls(**dict(value))


@dataclass(frozen=True)
class LedgerSnapshot:
    """Validated immutable view of active and resolved ledger records."""

    active: Mapping[str, PersistenceRecord]
    resolved: Mapping[str, PersistenceRecord]

    def __post_init__(self):
        active = dict(self.active)
        resolved = dict(self.resolved)
        seen_ids = set()
        for identity, record in active.items():
            if identity != record.drive_identity or record.state not in _ACTIVE_STATES:
                raise ValueError("active record key/state mismatch")
            if record.record_id in seen_ids:
                raise ValueError("duplicate record_id")
            seen_ids.add(record.record_id)
        for record_id, record in resolved.items():
            if record_id != record.record_id or record.state != "RESOLVED":
                raise ValueError("resolved record key/state mismatch")
            if record_id in seen_ids:
                raise ValueError("duplicate record_id")
            seen_ids.add(record_id)
        object.__setattr__(self, "active", MappingProxyType(active))
        object.__setattr__(self, "resolved", MappingProxyType(resolved))

    def to_payload(self) -> dict:
        return {
            "active": {
                identity: record.to_dict()
                for identity, record in self.active.items()
            },
            "resolved": {
                record_id: record.to_dict()
                for record_id, record in self.resolved.items()
            },
        }


@dataclass(frozen=True)
class AuditContext:
    """Fresh read-only target/session identity captured after reconnect."""

    drive_identity: str
    firmware: str
    pal: str
    boot: str
    connect_epoch: str

    def __post_init__(self):
        object.__setattr__(self, "drive_identity",
                           _require_identity(self.drive_identity))
        for name in ("firmware", "pal", "boot"):
            object.__setattr__(self, name,
                               _require_nonempty_string(getattr(self, name), name))
        object.__setattr__(self, "connect_epoch",
                           _require_uuid(self.connect_epoch, "connect_epoch"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AuditContext":
        return cls(**{name: value[name] for name in (
            "drive_identity", "firmware", "pal", "boot", "connect_epoch")})


@dataclass(frozen=True)
class AuditDecision:
    """Pure adjudication result; ``resolved`` never means motion-safe."""

    status: str
    resolved: bool
    resolution: str | None = None
    detail: str = ""
    record_id: str | None = None
    drive_identity: str | None = None
    connect_epoch: str | None = None

    def __post_init__(self):
        _require_nonempty_string(self.status, "status")
        if not isinstance(self.resolved, bool):
            raise ValueError("resolved must be bool")
        if self.resolved:
            if self.resolution not in {
                    "APPLIED_PROFILE_AFTER_RESET",
                    "ORIGINAL_PROFILE_AFTER_RESET"}:
                raise ValueError("resolved audit decision has invalid resolution")
            _require_uuid(self.record_id, "record_id", version=4)
            _require_identity(self.drive_identity)
            _require_uuid(self.connect_epoch, "connect_epoch")
        elif self.resolution is not None:
            raise ValueError("unresolved audit decision cannot have resolution")
        if not isinstance(self.detail, str):
            raise ValueError("detail must be a string")

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "resolved": self.resolved,
            "resolution": self.resolution,
            "detail": self.detail,
            "record_id": self.record_id,
            "drive_identity": self.drive_identity,
            "connect_epoch": self.connect_epoch,
        }


def _empty_snapshot() -> LedgerSnapshot:
    return LedgerSnapshot(active={}, resolved={})


def _canonical_hash(schema: str, payload: Mapping[str, Any]) -> str:
    body = json.dumps(
        {"schema": schema, "payload": payload},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _deep_freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item)
                                 for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value):
    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


def _validate_audit_evidence(
        value: Any, *, record: PersistenceRecord,
        expected_resolution: str) -> Mapping[str, Any]:
    """Validate the bounded evidence that justified a post-reset unlock."""
    if not isinstance(value, Mapping) or set(value) != {
            "schema", "operator_reset_attested", "context",
            "first_snapshot", "second_snapshot", "sha256"}:
        raise ValueError("post-reset audit_evidence fields are invalid")
    if value["schema"] != AUDIT_EVIDENCE_SCHEMA:
        raise ValueError("post-reset audit_evidence schema is invalid")
    if value["operator_reset_attested"] is not True:
        raise ValueError("post-reset audit evidence lacks reset attestation")
    context = value["context"]
    if not isinstance(context, Mapping) or set(context) != {
            "drive_identity", "firmware", "pal", "boot", "connect_epoch"}:
        raise ValueError("post-reset audit context fields are invalid")
    normalized_context = {
        "drive_identity": _require_identity(context["drive_identity"]),
        "firmware": _require_nonempty_string(context["firmware"], "firmware"),
        "pal": _require_nonempty_string(context["pal"], "pal"),
        "boot": _require_nonempty_string(context["boot"], "boot"),
        "connect_epoch": _require_uuid(context["connect_epoch"], "connect_epoch"),
    }
    if (normalized_context["drive_identity"] != record.drive_identity
            or normalized_context["firmware"] != record.firmware
            or normalized_context["pal"] != record.pal
            or normalized_context["boot"] != record.boot):
        raise ValueError("post-reset audit context differs from incident authority")
    if normalized_context["connect_epoch"] == record.connect_epoch:
        raise ValueError("post-reset audit context reused the incident epoch")

    required = set(record.registers) | {"MO", "SO", "VX", "PS", "MF"}
    snapshots = []
    for field in ("first_snapshot", "second_snapshot"):
        raw = value[field]
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise ValueError("%s keys do not match the bounded audit set" % field)
        normalized = {}
        for name in sorted(required):
            observed = raw[name]
            if (isinstance(observed, bool)
                    or not isinstance(observed, (int, float))
                    or not math.isfinite(float(observed))):
                raise ValueError("%s[%s] must be finite numeric" % (field, name))
            normalized[name] = float(observed)
        snapshots.append(normalized)
    first, second = snapshots
    if first != second:
        raise ValueError("post-reset audit snapshots are not identical")
    if any(second[name] != 0.0 for name in ("MO", "SO", "VX")):
        raise ValueError("post-reset evidence is not disabled and stationary")
    if second["PS"] not in (-2.0, -1.0):
        raise ValueError("post-reset evidence has an invalid PS state")
    actual = {name: second[name] for name in record.registers}
    expected = (record.applied if expected_resolution ==
                "APPLIED_PROFILE_AFTER_RESET" else record.original)
    if not _profile_matches(
            actual, expected, record.registers, record.rtol, record.phase):
        raise ValueError("post-reset evidence does not match its resolution")

    body = {
        "operator_reset_attested": True,
        "context": normalized_context,
        "first_snapshot": first,
        "second_snapshot": second,
    }
    checksum = value["sha256"]
    if (not isinstance(checksum, str)
            or _HEX_SHA256_RE.fullmatch(checksum) is None
            or not hmac.compare_digest(
                checksum, _canonical_hash(AUDIT_EVIDENCE_SCHEMA, body))):
        raise ValueError("post-reset audit evidence sha256 mismatch")
    normalized = {"schema": AUDIT_EVIDENCE_SCHEMA, **body,
                  "sha256": checksum}
    return _deep_freeze(normalized)


def build_audit_evidence(
        record: PersistenceRecord, context: AuditContext | Mapping[str, Any],
        first_snapshot: Mapping[str, Any], second_snapshot: Mapping[str, Any],
        operator_reset_attested: bool, resolution: str) -> Mapping[str, Any]:
    """Build and self-validate the exact evidence archived on audit closeout."""
    if not isinstance(record, PersistenceRecord):
        raise TypeError("record must be PersistenceRecord")
    if not isinstance(context, AuditContext):
        context = AuditContext.from_mapping(context)
    required = set(record.registers) | {"MO", "SO", "VX", "PS", "MF"}

    def normalized_snapshot(raw):
        if not isinstance(raw, Mapping) or set(raw) != required:
            raise ValueError("audit snapshot keys do not match the bounded set")
        return {name: float(raw[name]) for name in sorted(required)}

    body = {
        "operator_reset_attested": operator_reset_attested,
        "context": {
            "drive_identity": context.drive_identity,
            "firmware": context.firmware,
            "pal": context.pal,
            "boot": context.boot,
            "connect_epoch": context.connect_epoch,
        },
        "first_snapshot": normalized_snapshot(first_snapshot),
        "second_snapshot": normalized_snapshot(second_snapshot),
    }
    evidence = {
        "schema": AUDIT_EVIDENCE_SCHEMA,
        **body,
        "sha256": _canonical_hash(AUDIT_EVIDENCE_SCHEMA, body),
    }
    return _validate_audit_evidence(
        evidence, record=record, expected_resolution=resolution)


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LedgerIntegrityError("duplicate JSON key %r" % key)
        result[key] = value
    return result


def _reject_json_constant(value):
    raise LedgerIntegrityError("non-finite JSON constant %s" % value)


def _decode_envelope(text: str) -> LedgerSnapshot:
    try:
        envelope = json.loads(
            text, object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant)
    except LedgerIntegrityError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise LedgerIntegrityError("invalid persistence ledger JSON") from exc
    if not isinstance(envelope, Mapping) or set(envelope) != {
            "schema", "payload", "sha256"}:
        raise LedgerIntegrityError("ledger envelope fields are invalid")
    schema = envelope["schema"]
    if schema != LEDGER_SCHEMA:
        raise LedgerIntegrityError("unsupported persistence ledger schema %r" % schema)
    payload = envelope["payload"]
    checksum = envelope["sha256"]
    if not isinstance(checksum, str) or _HEX_SHA256_RE.fullmatch(checksum) is None:
        raise LedgerIntegrityError("ledger sha256 field is invalid")
    try:
        expected = _canonical_hash(schema, payload)
    except (TypeError, ValueError) as exc:
        raise LedgerIntegrityError("ledger payload is not canonical JSON") from exc
    if not hmac.compare_digest(checksum, expected):
        raise LedgerIntegrityError("ledger sha256 mismatch")
    if not isinstance(payload, Mapping) or set(payload) != {"active", "resolved"}:
        raise LedgerIntegrityError("ledger payload fields are invalid")
    if not isinstance(payload["active"], Mapping) \
            or not isinstance(payload["resolved"], Mapping):
        raise LedgerIntegrityError("ledger record collections must be objects")
    try:
        active = {
            identity: PersistenceRecord.from_dict(raw)
            for identity, raw in payload["active"].items()
        }
        resolved = {
            record_id: PersistenceRecord.from_dict(raw)
            for record_id, raw in payload["resolved"].items()
        }
        return LedgerSnapshot(active=active, resolved=resolved)
    except (TypeError, ValueError) as exc:
        raise LedgerIntegrityError("ledger record validation failed: %s" % exc) from exc


def _encode_snapshot(snapshot: LedgerSnapshot) -> bytes:
    payload = snapshot.to_payload()
    envelope = {
        "schema": LEDGER_SCHEMA,
        "payload": payload,
        "sha256": _canonical_hash(LEDGER_SCHEMA, payload),
    }
    return (json.dumps(
        envelope, ensure_ascii=False, indent=2, sort_keys=True,
        allow_nan=False) + "\n").encode("utf-8")


class PersistenceLedger:
    """Identity-primary crash-safe ledger stored in one atomic JSON file."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)

    @property
    def _lock_path(self) -> Path:
        return self.path.with_name(self.path.name + ".lock")

    def _process_mutex(self) -> threading.RLock:
        """Return one in-process mutex shared by every instance for this path."""
        key = os.path.normcase(os.path.abspath(str(self.path)))
        with _PROCESS_MUTEXES_GUARD:
            return _PROCESS_MUTEXES.setdefault(key, threading.RLock())

    @contextmanager
    def _mutation_lock(self):
        """Serialize the complete load/modify/replace transaction.

        Atomic replacement prevents torn JSON, but it does not prevent two app
        processes from both reading the same old snapshot and overwriting each
        other's incident.  A stable sibling lock file closes that lost-update
        window.  Timeout is fail-closed: a caller must not proceed to ``SV``
        when the write-ahead record could not be serialized.
        """
        mutex = self._process_mutex()
        if not mutex.acquire(timeout=_LOCK_TIMEOUT_S):
            raise LedgerWriteError("persistence ledger mutex acquisition timed out")
        handle = None
        locked = False
        created_sentinel = False
        try:
            parent = self.path.parent
            try:
                parent.mkdir(parents=True, exist_ok=True)
                try:
                    fd = os.open(
                        self._lock_path,
                        os.O_CREAT | os.O_EXCL | os.O_RDWR)
                    created_sentinel = True
                except FileExistsError:
                    fd = os.open(self._lock_path, os.O_RDWR)
                handle = os.fdopen(fd, "a+b")
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise LedgerWriteError(
                    "persistence ledger lock cannot be opened: %s" %
                    type(exc).__name__) from exc

            deadline = time.monotonic() + _LOCK_TIMEOUT_S
            if os.name == "nt":
                import msvcrt
                while True:
                    try:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        locked = True
                        break
                    except OSError as exc:
                        if time.monotonic() >= deadline:
                            raise LedgerWriteError(
                                "persistence ledger file-lock acquisition timed out") from exc
                        time.sleep(0.025)
            else:
                import fcntl
                while True:
                    try:
                        fcntl.flock(
                            handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                        break
                    except OSError as exc:
                        if time.monotonic() >= deadline:
                            raise LedgerWriteError(
                                "persistence ledger file-lock acquisition timed out") from exc
                        time.sleep(0.025)
            yield created_sentinel
        finally:
            if handle is not None:
                if locked:
                    try:
                        if os.name == "nt":
                            import msvcrt
                            handle.seek(0)
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
                handle.close()
            mutex.release()

    def _load(self, *, allow_missing_for_new_sentinel: bool = False
              ) -> LedgerSnapshot:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            if self._lock_path.exists() and not allow_missing_for_new_sentinel:
                raise LedgerIntegrityError(
                    "persistence ledger is missing after initialization")
            return _empty_snapshot()
        except OSError as exc:
            raise LedgerUnreadableError(
                "persistence ledger cannot be read: %s" % type(exc).__name__) from exc
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LedgerIntegrityError("persistence ledger is not UTF-8") from exc
        return _decode_envelope(text)

    def load(self) -> LedgerSnapshot:
        return self._load()

    def _commit(self, snapshot: LedgerSnapshot) -> LedgerSnapshot:
        try:
            encoded = _encode_snapshot(snapshot)
        except (TypeError, ValueError) as exc:
            raise LedgerWriteError("ledger serialization failed") from exc
        parent = self.path.parent
        temp_path = None
        try:
            parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=self.path.name + ".", suffix=".tmp", dir=str(parent))
            temp_path = Path(temp_name)
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            temp_path = None
        except OSError as exc:
            raise LedgerWriteError(
                "atomic persistence ledger write failed: %s" %
                type(exc).__name__) from exc
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        try:
            observed = self.load()
        except PersistenceAuditError as exc:
            raise LedgerWriteError("ledger readback validation failed") from exc
        if observed != snapshot:
            raise LedgerWriteError("ledger readback differs from requested state")
        return observed

    def prepare(
            self, *, phase: str, drive_identity: str, com_port: str,
            firmware: str, pal: str, boot: str, connect_epoch: str,
            original: Mapping[str, float], applied: Mapping[str, float],
            registers: tuple[str, ...] | None = None,
            initial_state: str = "PERSISTING",
            ) -> PersistenceRecord:
        """Durably create the write-ahead incident for one frozen profile.

        Existing P1/P2 callers omit ``registers`` and ``initial_state`` and
        retain the original PERSISTING-before-SV behavior.  Configuration
        writers may start in RAM_APPLYING before their first assignment, then
        explicitly advance to PERSISTING only after complete RAM readback.
        """
        if phase not in PHASE_REGISTERS:
            raise ValueError("phase must be P1, P2 or MOTOR")
        expected_registers = PHASE_REGISTERS[phase]
        if registers is None:
            registers = expected_registers
        else:
            registers = tuple(registers)
            if registers != expected_registers:
                raise ValueError("registers do not match phase %s" % phase)
        if (not isinstance(initial_state, str)
                or initial_state not in {"PERSISTING", "RAM_APPLYING"}):
            raise ValueError(
                "initial_state must be PERSISTING or RAM_APPLYING")
        if phase == "MOTOR" and initial_state != "RAM_APPLYING":
            raise ValueError("MOTOR must start in RAM_APPLYING")
        if phase in {"P1", "P2"} and initial_state != "PERSISTING":
            raise ValueError("P1/P2 must start in PERSISTING")
        now = _utc_now()
        record = PersistenceRecord(
            record_id=str(uuid.uuid4()),
            phase=phase,
            state=initial_state,
            drive_identity=drive_identity,
            com_port=com_port,
            firmware=firmware,
            pal=pal,
            boot=boot,
            connect_epoch=connect_epoch,
            registers=registers,
            original=original,
            applied=applied,
            rtol=DEFAULT_RTOL,
            created_utc=now,
            updated_utc=now,
        )
        if _profile_matches(
                record.original, record.applied, record.registers,
                record.rtol, record.phase):
            raise ValueError(
                "original and applied profiles are indistinguishable; SV is not authorized")
        with self._mutation_lock() as new_sentinel:
            snapshot = self._load(
                allow_missing_for_new_sentinel=new_sentinel)
            if record.drive_identity in snapshot.active:
                raise ActiveIncidentError(
                    "drive identity already has an active persistence incident")
            if record.record_id in snapshot.resolved or any(
                    active.record_id == record.record_id
                    for active in snapshot.active.values()):
                raise LedgerWriteError("generated duplicate record_id")
            active = dict(snapshot.active)
            active[record.drive_identity] = record
            committed = self._commit(LedgerSnapshot(
                active=active, resolved=snapshot.resolved))
            return committed.active[record.drive_identity]

    @staticmethod
    def _find_active(snapshot: LedgerSnapshot, record_id: str
                     ) -> tuple[str, PersistenceRecord]:
        for identity, record in snapshot.active.items():
            if record.record_id == record_id:
                return identity, record
        raise RecordNotFoundError("active persistence record not found")

    def mark_unknown(self, record_id: str, reason: str) -> PersistenceRecord:
        """Retain an incident after an ambiguous SV transport outcome."""
        _require_uuid(record_id, "record_id", version=4)
        reason = _require_nonempty_string(reason, "reason")
        with self._mutation_lock() as new_sentinel:
            snapshot = self._load(
                allow_missing_for_new_sentinel=new_sentinel)
            identity, record = self._find_active(snapshot, record_id)
            unknown = replace(
                record, state="UNKNOWN", updated_utc=_utc_now(), reason=reason)
            active = dict(snapshot.active)
            active[identity] = unknown
            committed = self._commit(LedgerSnapshot(
                active=active, resolved=snapshot.resolved))
            return committed.active[identity]

    def mark_persisting(self, record_id: str) -> PersistenceRecord:
        """Advance a fully verified RAM profile to the sole SV-ready state."""
        _require_uuid(record_id, "record_id", version=4)
        with self._mutation_lock() as new_sentinel:
            snapshot = self._load(
                allow_missing_for_new_sentinel=new_sentinel)
            identity, record = self._find_active(snapshot, record_id)
            if record.phase != "MOTOR" or record.state != "RAM_APPLYING":
                raise ValueError(
                    "only a MOTOR RAM_APPLYING record can advance to PERSISTING")
            persisting = replace(
                record, state="PERSISTING", updated_utc=_utc_now(),
                reason=None)
            active = dict(snapshot.active)
            active[identity] = persisting
            committed = self._commit(LedgerSnapshot(
                active=active, resolved=snapshot.resolved))
            return committed.active[identity]

    def _resolve_locked(self, snapshot: LedgerSnapshot, record_id: str,
                        resolution: str, *, require_persisting: bool = False,
                        audit_evidence: Mapping[str, Any] | None = None,
                        ) -> PersistenceRecord:
        identity, record = self._find_active(snapshot, record_id)
        if require_persisting and record.state != "PERSISTING":
            raise ValueError("SV success can resolve only a PERSISTING record")
        now = _utc_now()
        archived = replace(
            record, state="RESOLVED", resolution=resolution,
            resolved_utc=now, updated_utc=now,
            audit_evidence=audit_evidence)
        active = dict(snapshot.active)
        del active[identity]
        resolved = dict(snapshot.resolved)
        if record_id in resolved:
            raise LedgerIntegrityError("record_id already exists in resolved archive")
        resolved[record_id] = archived
        committed = self._commit(LedgerSnapshot(
            active=active, resolved=resolved))
        return committed.resolved[record_id]

    def resolve_sv_success(self, record_id: str) -> PersistenceRecord:
        """Archive a prepared incident after a definite successful SV reply."""
        _require_uuid(record_id, "record_id", version=4)
        with self._mutation_lock() as new_sentinel:
            return self._resolve_locked(
                self._load(allow_missing_for_new_sentinel=new_sentinel),
                record_id, "SV_ACKNOWLEDGED",
                require_persisting=True)

    def resolve_ram_rollback(self, record_id: str) -> PersistenceRecord:
        """Archive a pre-SV incident after exact RAM rollback readback."""
        _require_uuid(record_id, "record_id", version=4)
        with self._mutation_lock() as new_sentinel:
            snapshot = self._load(
                allow_missing_for_new_sentinel=new_sentinel)
            _identity, record = self._find_active(snapshot, record_id)
            if record.phase != "MOTOR" or record.state != "RAM_APPLYING":
                raise ValueError(
                    "RAM rollback can resolve only a MOTOR RAM_APPLYING record")
            return self._resolve_locked(
                snapshot, record_id, "RAM_ROLLBACK_VERIFIED")

    def resolve_from_audit(
            self, record_id: str, decision: AuditDecision,
            audit_evidence: Mapping[str, Any]) -> PersistenceRecord:
        """Archive only a fully resolved read-only post-reset profile match."""
        _require_uuid(record_id, "record_id", version=4)
        if not isinstance(decision, AuditDecision) or not decision.resolved:
            raise ValueError("a resolved AuditDecision is required")
        if decision.resolution not in {
                "APPLIED_PROFILE_AFTER_RESET",
                "ORIGINAL_PROFILE_AFTER_RESET"}:
            raise ValueError("unsupported audit resolution")
        with self._mutation_lock() as new_sentinel:
            snapshot = self._load(
                allow_missing_for_new_sentinel=new_sentinel)
            _identity, record = self._find_active(snapshot, record_id)
            if (decision.record_id != record.record_id
                    or decision.drive_identity != record.drive_identity):
                raise ValueError("audit decision is bound to a different record")
            if decision.connect_epoch == record.connect_epoch:
                raise ValueError("audit decision must use a different connection epoch")
            validated_evidence = _validate_audit_evidence(
                audit_evidence, record=record,
                expected_resolution=decision.resolution)
            if (validated_evidence["context"]["connect_epoch"]
                    != decision.connect_epoch):
                raise ValueError(
                    "audit evidence epoch differs from the adjudication epoch")
            return self._resolve_locked(
                snapshot, record_id, decision.resolution,
                audit_evidence=validated_evidence)

    def active_for_identity(
            self, drive_identity: str) -> PersistenceRecord | None:
        identity = _require_identity(drive_identity)
        return self.load().active.get(identity)


def _unresolved(status: str, detail: str) -> AuditDecision:
    return AuditDecision(status=status, resolved=False, detail=detail)


def _profile_matches(actual: Mapping[str, float], expected: Mapping[str, float],
                     registers: tuple[str, ...], rtol: float,
                     phase: str) -> bool:
    if phase == "MOTOR":
        return all(float(actual[name]) == float(expected[name])
                   for name in registers)
    return all(abs(float(actual[name]) - float(expected[name]))
               <= rtol * abs(float(expected[name]))
               for name in registers)


def adjudicate_read_only(
        record: PersistenceRecord | Mapping[str, Any],
        context: AuditContext | Mapping[str, Any],
        readback: Mapping[str, Any],
        operator_reset_attested: bool,
        ) -> AuditDecision:
    """Purely classify fresh post-reset readback against one incident.

    A matching profile describes the durable values observed after the operator-
    attested reset.  It does *not* establish that the ambiguous ``SV`` succeeded
    or failed, because the pre-trial ``original`` values were a RAM snapshot,
    not an independently proven flash baseline.
    """
    try:
        if not isinstance(record, PersistenceRecord):
            record = PersistenceRecord.from_dict(record)
    except (TypeError, ValueError, KeyError) as exc:
        return _unresolved("INVALID_RECORD", str(exc))
    try:
        if not isinstance(context, AuditContext):
            context = AuditContext.from_mapping(context)
    except (TypeError, ValueError, KeyError) as exc:
        return _unresolved("INVALID_CONTEXT", str(exc))

    if context.drive_identity != record.drive_identity:
        return _unresolved(
            "IDENTITY_MISMATCH", "current drive identity differs from the incident")
    if context.firmware != record.firmware:
        return _unresolved(
            "FIRMWARE_MISMATCH", "firmware string differs from the incident")
    if context.pal != record.pal:
        return _unresolved("PAL_MISMATCH", "PAL string differs from the incident")
    if context.boot != record.boot:
        return _unresolved("BOOT_MISMATCH", "boot string differs from the incident")
    if context.connect_epoch == record.connect_epoch:
        return _unresolved(
            "SESSION_NOT_CHANGED", "a different connection epoch is required")
    if operator_reset_attested is not True:
        return _unresolved(
            "RESET_NOT_ATTESTED",
            "reconnect alone does not prove that flash was reloaded")

    if not isinstance(readback, Mapping):
        return _unresolved("READBACK_INVALID", "readback must be a mapping")
    required_keys = set(record.registers) | {"MO", "SO", "VX"}
    if set(readback) != required_keys:
        return _unresolved(
            "READBACK_INVALID", "readback keys must exactly match the audit set")
    for name in ("MO", "SO", "VX"):
        value = readback[name]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(float(value)) or float(value) != 0.0):
            return _unresolved(
                "DRIVE_NOT_DISABLED_STATIONARY",
                "MO, SO and VX must each be a finite exact zero")

    try:
        actual = _require_profile(
            {name: readback[name] for name in record.registers},
            record.registers, "readback", record.phase)
    except (TypeError, ValueError, KeyError) as exc:
        return _unresolved("READBACK_INVALID", str(exc))

    targets_overlap = _profile_matches(
        record.applied, record.original, record.registers, record.rtol,
        record.phase)
    applied_match = _profile_matches(
        actual, record.applied, record.registers, record.rtol, record.phase)
    original_match = _profile_matches(
        actual, record.original, record.registers, record.rtol, record.phase)
    if targets_overlap or (applied_match and original_match):
        return _unresolved(
            "UNRESOLVED_NO_DISTINGUISHING_CHANGE",
            "original and applied profiles are not distinguishable at audit tolerance")
    if applied_match:
        return AuditDecision(
            status="RESOLVED_APPLIED_PROFILE", resolved=True,
            resolution="APPLIED_PROFILE_AFTER_RESET",
            detail=("post-reset durable values equal the applied profile; "
                    "specific SV causality is not claimed"),
            record_id=record.record_id,
            drive_identity=record.drive_identity,
            connect_epoch=context.connect_epoch)
    if original_match:
        return AuditDecision(
            status="RESOLVED_ORIGINAL_PROFILE", resolved=True,
            resolution="ORIGINAL_PROFILE_AFTER_RESET",
            detail=("post-reset durable values equal the original RAM profile; "
                    "this does not prove that the ambiguous SV failed"),
            record_id=record.record_id,
            drive_identity=record.drive_identity,
            connect_epoch=context.connect_epoch)
    return _unresolved(
        "CONFIG_DRIFT_UNKNOWN",
        "complete readback matches neither frozen profile")


__all__ = [
    "LEDGER_SCHEMA", "AUDIT_EVIDENCE_SCHEMA", "DEFAULT_RTOL",
    "PHASE_REGISTERS",
    "PersistenceAuditError", "LedgerIntegrityError", "LedgerUnreadableError",
    "LedgerWriteError", "ActiveIncidentError", "RecordNotFoundError",
    "PersistenceRecord", "LedgerSnapshot", "AuditContext", "AuditDecision",
    "PersistenceLedger", "adjudicate_read_only", "build_audit_evidence",
]
