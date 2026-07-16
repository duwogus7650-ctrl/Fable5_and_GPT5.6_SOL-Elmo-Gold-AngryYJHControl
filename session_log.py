"""Bounded host-observed session evidence with zero drive dependencies.

This module deliberately does not import PyQt, ``elmo_link`` or ``main``.  It
accepts already-emitted, detached application events and produces local JSON or
CSV evidence.  Host timestamps are observation times, never drive history.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import secrets
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_CAPACITY = 512
MAX_PAYLOAD_JSON_BYTES = 64 * 1024
_HASHED_ID = re.compile(r"^elmo-sn4-sha256:[0-9a-fA-F]{64}$")
_HASHED_ID_IN_TEXT = re.compile(
    r"elmo-sn4-sha256:[0-9a-fA-F]{64}", re.IGNORECASE)
_COM_PORT_IN_TEXT = re.compile(r"\bCOM[0-9]{1,5}\b", re.IGNORECASE)
_LABELED_SERIAL_IN_TEXT = re.compile(
    r"\b(?:serial(?:\s+number)?|s/n|sn\s*\[\s*4\s*\]|sn)"
    r"(?=\s*[:=#]|\s+)\s*[:=#]?\s*[^;,\r\n]*",
    re.IGNORECASE)
_WINDOWS_PATH_IN_TEXT = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\)[^;\r\n]*", re.IGNORECASE)
_POSIX_USER_PATH_IN_TEXT = re.compile(
    r"(?:/home/|/Users/)[^;\r\n]*", re.IGNORECASE)
_SENSITIVE_KEYS = frozenset((
    "port", "com_port", "path", "file_path", "workspace_path",
    "serial", "serial_number", "raw_serial", "sn", "sn[4]",
))
_RAW_STATUS_FIELDS = ("MO", "SO", "MF", "SR", "MS")
_TELEMETRY_NUMERIC_FIELDS = ("pos", "vel", "pos_err", "iq", "mo")
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _format_utc(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("utc_now must return a timezone-aware datetime")
    utc = value.astimezone(timezone.utc)
    timespec = "microseconds" if utc.microsecond else "seconds"
    return utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def _finite_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _sanitize_identity(value: Any) -> str:
    text = str(value or "").strip()
    if _HASHED_ID.fullmatch(text):
        prefix, _, digest = text.partition(":")
        return prefix.lower() + ":" + digest.lower()
    return "REDACTED_UNVERIFIED"


def _sensitive_key(key: str) -> bool:
    normalized = str(key).strip().lower()
    return (normalized in _SENSITIVE_KEYS or normalized.endswith("_path")
            or normalized.endswith("_port")
            or normalized.startswith("serial_"))


def _redact_free_text(value: str) -> str:
    """Remove common local identifiers from otherwise useful status text."""

    text = _HASHED_ID_IN_TEXT.sub("[TARGET_ID_REDACTED]", str(value))
    text = _COM_PORT_IN_TEXT.sub("[PORT_REDACTED]", text)
    text = _LABELED_SERIAL_IN_TEXT.sub("[SERIAL_REDACTED]", text)
    text = _WINDOWS_PATH_IN_TEXT.sub("[PATH_REDACTED]", text)
    return _POSIX_USER_PATH_IN_TEXT.sub("[PATH_REDACTED]", text)


def _sanitize(value: Any, *, key: str | None = None) -> Any:
    """Return detached, deterministic JSON data without object ``repr`` leaks."""

    if key is not None:
        normalized = str(key).strip().lower()
        if normalized == "drive_identity":
            return _sanitize_identity(value)
        if _sensitive_key(normalized):
            return "REDACTED"
    if isinstance(value, str):
        return _redact_free_text(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return "NON_FINITE_%s" % (
            "NAN" if math.isnan(value) else "POS_INF" if value > 0 else "NEG_INF")
    if isinstance(value, datetime):
        return _format_utc(value)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for index, raw_key in enumerate(
                sorted(value, key=lambda item: str(item))):
            text_key = str(raw_key)
            safe_key = _redact_free_text(text_key) or "[EMPTY_KEY]"
            if safe_key in out:
                safe_key = "%s#%d" % (safe_key, index + 1)
            out[safe_key] = _sanitize(value[raw_key], key=text_key)
        return out
    if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray, memoryview)):
        return [_sanitize(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "BINARY_REDACTED_%d_BYTES" % len(value)
    return "UNSUPPORTED_%s" % type(value).__name__


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _sanitize(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False)


def _csv_safe(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + text
    return text


@dataclass(frozen=True)
class SessionEvent:
    event_id: int
    generation: int
    host_utc: str
    host_monotonic_s: float
    clock_quality: str
    category: str
    name: str
    severity: str
    freshness: str
    affects_current: bool
    target_identity: str
    source_monotonic_s: float | None
    telemetry_sequence: int | None
    payload_json: str

    @property
    def payload(self) -> dict[str, Any]:
        """Return a new detached mapping on every access."""

        value = json.loads(self.payload_json)
        return value if isinstance(value, dict) else {"value": value}


class SessionLog:
    """In-memory bounded event log for already-observed application signals."""

    def __init__(
            self, *, capacity: int = DEFAULT_CAPACITY,
            utc_now: Callable[[], datetime] | None = None,
            monotonic_now: Callable[[], float] | None = None):
        if (not isinstance(capacity, int) or isinstance(capacity, bool)
                or not 1 <= capacity <= 100_000):
            raise ValueError("capacity must be an integer in 1..100000")
        self.capacity = capacity
        self._utc_now = utc_now or (lambda: datetime.now(timezone.utc))
        self._monotonic_now = monotonic_now or time.monotonic
        self._events: deque[SessionEvent] = deque(maxlen=capacity)
        self._next_event_id = 1
        self._generation_counter = 0
        self._current_generation: int | None = None
        self._connection_active = False
        self._identity_by_generation: dict[int, str] = {}
        self._last_telemetry_sequence: dict[int, int] = {}
        self._last_telemetry_projection: dict[int, tuple[Any, ...]] = {}
        self._last_axis_projection: dict[int, str] = {}
        self._last_host_monotonic: float | None = None
        self.dropped_count = 0

    @property
    def current_generation(self) -> int | None:
        return self._current_generation

    @property
    def connection_active(self) -> bool:
        return self._connection_active

    def _observe_clock(self) -> tuple[str, float, str]:
        host_utc = _format_utc(self._utc_now())
        monotonic = self._monotonic_now()
        if not _finite_number(monotonic):
            raise ValueError("monotonic_now must return a finite number")
        monotonic_f = float(monotonic)
        quality = "MONOTONIC"
        if (self._last_host_monotonic is not None
                and monotonic_f < self._last_host_monotonic):
            quality = "REGRESSED"
        self._last_host_monotonic = monotonic_f
        return host_utc, monotonic_f, quality

    def _store(self, event: SessionEvent) -> SessionEvent:
        if len(self._events) == self.capacity:
            self.dropped_count += 1
        self._events.append(event)
        retained_generations = {
            item.generation for item in self._events if item.generation > 0}
        if self._connection_active and self._current_generation is not None:
            retained_generations.add(self._current_generation)
        for mapping in (
                self._identity_by_generation,
                self._last_telemetry_sequence,
                self._last_telemetry_projection,
                self._last_axis_projection):
            for generation in tuple(mapping):
                if generation not in retained_generations:
                    del mapping[generation]
        return event

    def append(
            self, *, category: str, name: str, severity: str = "INFO",
            payload: Mapping[str, Any] | None = None,
            generation: int | None = None, freshness: str = "OBSERVED",
            affects_current: bool | None = None,
            source_monotonic_s: float | None = None,
            telemetry_sequence: int | None = None) -> SessionEvent:
        category_text = _redact_free_text(str(category or "").strip())[:256]
        name_text = _redact_free_text(str(name or "").strip())[:256]
        severity_text = _redact_free_text(
            str(severity or "UNKNOWN").strip().upper())[:128]
        freshness_text = _redact_free_text(
            str(freshness or "UNKNOWN").strip().upper())[:128]
        if not category_text or not name_text:
            raise ValueError("category and name are required")
        if generation is None:
            generation = (
                self._current_generation
                if self._connection_active and self._current_generation is not None
                else 0)
        if (not isinstance(generation, int) or isinstance(generation, bool)
                or generation < 0 or generation > self._generation_counter):
            raise ValueError("generation is outside the observed session range")
        if source_monotonic_s is not None and not _finite_number(source_monotonic_s):
            source_monotonic_s = None
            freshness_text = "INVALID_SOURCE_TIME"
            affects_current = False
        if telemetry_sequence is not None and (
                not isinstance(telemetry_sequence, int)
                or isinstance(telemetry_sequence, bool)
                or telemetry_sequence <= 0):
            telemetry_sequence = None
            freshness_text = "INVALID_SEQUENCE"
            affects_current = False
        if affects_current is None:
            affects_current = bool(
                self._connection_active
                and generation == self._current_generation)
        target_identity = self._identity_by_generation.get(
            generation, "REDACTED_UNVERIFIED")
        payload_json = _canonical_json(dict(payload or {}))
        if len(payload_json.encode("utf-8")) > MAX_PAYLOAD_JSON_BYTES:
            raise ValueError(
                "event payload exceeds %d UTF-8 bytes" %
                MAX_PAYLOAD_JSON_BYTES)
        host_utc, host_monotonic_s, clock_quality = self._observe_clock()
        event = SessionEvent(
            event_id=self._next_event_id,
            generation=generation,
            host_utc=host_utc,
            host_monotonic_s=host_monotonic_s,
            clock_quality=clock_quality,
            category=category_text,
            name=name_text,
            severity=severity_text,
            freshness=freshness_text,
            affects_current=bool(affects_current),
            target_identity=target_identity,
            source_monotonic_s=(None if source_monotonic_s is None
                                else float(source_monotonic_s)),
            telemetry_sequence=telemetry_sequence,
            payload_json=payload_json,
        )
        self._next_event_id += 1
        return self._store(event)

    def begin_connection(
            self, *, target_identity: str,
            metadata: Mapping[str, Any] | None = None) -> SessionEvent:
        self._generation_counter += 1
        generation = self._generation_counter
        self._current_generation = generation
        self._connection_active = True
        identity = _sanitize_identity(target_identity)
        self._identity_by_generation[generation] = identity
        self._last_telemetry_sequence.pop(generation, None)
        self._last_telemetry_projection.pop(generation, None)
        self._last_axis_projection.pop(generation, None)
        return self.append(
            category="connection", name="connection.opened", severity="INFO",
            payload=dict(metadata or {}), generation=generation,
            freshness="OBSERVED", affects_current=True)

    def end_connection(self, reason: str) -> SessionEvent:
        generation = (
            self._current_generation
            if self._connection_active and self._current_generation is not None
            else 0)
        event = self.append(
            category="connection", name="connection.closed", severity="INFO",
            payload={"reason": str(reason or "unspecified")},
            generation=generation, freshness="OBSERVED",
            affects_current=False)
        self._connection_active = False
        return event

    def record_telemetry(
            self, sample: Mapping[str, Any], *,
            accepted_by_ui: bool | None = None) -> SessionEvent | None:
        copied = dict(sample or {})
        if accepted_by_ui is not None and not isinstance(accepted_by_ui, bool):
            raise TypeError("accepted_by_ui must be bool or None")
        generation = (
            self._current_generation
            if self._connection_active and self._current_generation is not None
            else 0)
        sequence = copied.get("telemetry_sequence")
        source_time = copied.get("telemetry_received_monotonic")
        sequence_ok = (isinstance(sequence, int) and not isinstance(sequence, bool)
                       and sequence > 0)
        numeric_ok = all(_finite_number(copied.get(name))
                         for name in _TELEMETRY_NUMERIC_FIELDS)
        mo_ok = numeric_ok and float(copied.get("mo")) in (0.0, 1.0)
        payload_valid = bool(
            copied.get("telemetry_valid") is True
            and copied.get("session_coordinate_known") is True
            and copied.get("encoder_maintenance_reconnect_required") is False
            and _finite_number(source_time)
            and sequence_ok and numeric_ok and mo_ok)
        if not self._connection_active:
            return self.append(
                category="telemetry", name="telemetry.rejected",
                severity="UNKNOWN", payload=copied, generation=generation,
                freshness="NO_ACTIVE_CONNECTION", affects_current=False,
                source_monotonic_s=source_time,
                telemetry_sequence=(sequence if sequence_ok else None))
        if accepted_by_ui is False or not payload_valid:
            return self.append(
                category="telemetry", name="telemetry.rejected",
                severity="UNKNOWN", payload=copied, generation=generation,
                freshness=("UI_REJECTED" if accepted_by_ui is False
                           else "INVALID"),
                affects_current=False,
                source_monotonic_s=source_time,
                telemetry_sequence=(sequence if sequence_ok else None))
        last = self._last_telemetry_sequence.get(generation, 0)
        if sequence <= last:
            return self.append(
                category="telemetry", name="telemetry.rejected",
                severity="WARNING", payload=copied, generation=generation,
                freshness="STALE_OR_REPLAYED", affects_current=False,
                source_monotonic_s=source_time,
                telemetry_sequence=sequence)
        self._last_telemetry_sequence[generation] = sequence
        projection = (
            int(float(copied["mo"])),
            copied.get("telemetry_valid") is True,
            copied.get("telemetry_error"),
            copied.get("session_coordinate_known") is True,
            copied.get("encoder_maintenance_reconnect_required") is True,
        )
        if self._last_telemetry_projection.get(generation) == projection:
            return None
        self._last_telemetry_projection[generation] = projection
        return self.append(
            category="telemetry", name="telemetry.state", severity="INFO",
            payload=copied, generation=generation, freshness="FRESH",
            affects_current=True, source_monotonic_s=source_time,
            telemetry_sequence=sequence)

    def record_axis_summary(
            self, summary: Mapping[str, Any]) -> SessionEvent | None:
        source = dict(summary or {})
        raw_source = source.get("raw")
        errors_source = source.get("errors")
        raw_map = raw_source if isinstance(raw_source, Mapping) else {}
        errors_valid = isinstance(errors_source, Mapping)
        errors_map = errors_source if errors_valid else {}
        raw = {name: _sanitize(raw_map[name]) for name in _RAW_STATUS_FIELDS
               if name in raw_map}
        errors = _sanitize(dict(errors_map))
        if not isinstance(errors, dict):  # defensive; _sanitize(mapping) is dict
            errors = {}
        payload = {"raw": raw, "errors": errors}
        if not errors_valid:
            payload["errors_schema"] = "INVALID_NON_MAPPING"
        generation = (
            self._current_generation
            if self._connection_active and self._current_generation is not None
            else 0)
        fingerprint = _canonical_json(payload)
        if self._last_axis_projection.get(generation) == fingerprint:
            return None
        self._last_axis_projection[generation] = fingerprint
        complete = all(name in raw for name in _RAW_STATUS_FIELDS)
        raw_known = complete and all(
            _finite_number(raw[name]) for name in _RAW_STATUS_FIELDS)
        mf_read_failed = any(
            str(key).strip().upper() == "MF" for key in errors_map)
        mf_known_nonzero = (
            _finite_number(raw.get("MF"))
            and float(raw["MF"]) != 0.0
            and not mf_read_failed)
        if mf_known_nonzero:
            severity = "ERROR"
        elif errors or not raw_known or not errors_valid:
            severity = "UNKNOWN"
        else:
            severity = "INFO"
        return self.append(
            category="status", name="axis.raw_status", severity=severity,
            payload=payload, generation=generation,
            freshness=("OBSERVED" if self._connection_active
                       else "NO_ACTIVE_CONNECTION"),
            affects_current=self._connection_active)

    def _scope(self, event: SessionEvent) -> str:
        if (not self._connection_active
                or event.generation != self._current_generation):
            return "HISTORICAL"
        if not event.affects_current:
            return "REJECTED"
        return "CURRENT"

    def snapshot(self) -> tuple[dict[str, Any], ...]:
        return tuple({
            "event_id": event.event_id,
            "host_utc": event.host_utc,
            "host_monotonic_s": event.host_monotonic_s,
            "clock_quality": event.clock_quality,
            "generation": event.generation,
            "scope": self._scope(event),
            "target_identity": event.target_identity,
            "telemetry_sequence": event.telemetry_sequence,
            "category": event.category,
            "name": event.name,
            "severity": event.severity,
            "freshness": event.freshness,
            "affects_current": event.affects_current,
            "source_monotonic_s": event.source_monotonic_s,
            "payload": event.payload,
        } for event in self._events)

    @staticmethod
    def _export_rows(rows: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
        aliases: dict[str, str] = {}

        def alias_identity(identity: str) -> str:
            if identity not in aliases:
                aliases[identity] = "target-%03d" % (len(aliases) + 1)
            return aliases[identity]

        def replace_aliases(value: Any) -> Any:
            if isinstance(value, str) and value in aliases:
                return aliases[value]
            if isinstance(value, Mapping):
                return {str(key): replace_aliases(item)
                        for key, item in value.items()}
            if isinstance(value, list):
                return [replace_aliases(item) for item in value]
            return value

        def collect_identities(value: Any) -> None:
            if isinstance(value, str) and _HASHED_ID.fullmatch(value):
                alias_identity(value.lower())
            elif isinstance(value, Mapping):
                for item in value.values():
                    collect_identities(item)
            elif isinstance(value, list):
                for item in value:
                    collect_identities(item)

        # Build the complete alias table before traversing payloads so a row
        # cannot leak the hash of a target first observed in a later row.
        for row in rows:
            alias_identity(str(
                row.get("target_identity") or "REDACTED_UNVERIFIED"))
            collect_identities(row.get("payload", {}))

        exported = []
        for row in rows:
            identity = str(row.get("target_identity") or "REDACTED_UNVERIFIED")
            detached = dict(row)
            detached["target_identity"] = aliases[identity]
            detached["payload"] = replace_aliases(row.get("payload", {}))
            exported.append(detached)
        return tuple(exported)

    def _frozen_export_snapshot(self) -> tuple[dict[str, Any], ...]:
        # ``snapshot`` returns detached payloads; later appends cannot mutate it.
        return self._export_rows(self.snapshot())

    def export_json_text(self) -> str:
        rows = self._frozen_export_snapshot()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "evidence_class": "HOST_OBSERVED_NOT_DRIVE_HISTORY",
            "exported_at_utc": _format_utc(self._utc_now()),
            "capacity": self.capacity,
            "event_count": len(rows),
            "dropped_count": self.dropped_count,
            "events": rows,
        }
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, indent=2,
            allow_nan=False) + "\n"

    def export_csv_text(self) -> str:
        rows = self._frozen_export_snapshot()
        columns = (
            "row_type", "schema_version", "evidence_class",
            "exported_at_utc", "capacity", "event_count", "dropped_count",
            "event_id", "host_utc", "host_monotonic_s", "clock_quality",
            "generation", "scope", "target_identity", "telemetry_sequence",
            "category", "name", "severity", "freshness", "affects_current",
            "source_monotonic_s", "payload_json",
        )
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "evidence_class": "HOST_OBSERVED_NOT_DRIVE_HISTORY",
            "exported_at_utc": _format_utc(self._utc_now()),
            "capacity": self.capacity,
            "event_count": len(rows),
            "dropped_count": self.dropped_count,
        }
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        if not rows:
            record = {key: "" for key in columns}
            record.update(metadata)
            record["row_type"] = "META"
            writer.writerow({key: _csv_safe(record.get(key)) for key in columns})
        for row in rows:
            record = {key: row.get(key) for key in columns}
            record.update(metadata)
            record["row_type"] = "EVENT"
            record["payload_json"] = _canonical_json(row.get("payload", {}))
            record["affects_current"] = (
                "true" if row.get("affects_current") else "false")
            for key in columns:
                record[key] = _csv_safe(record.get(key))
            writer.writerow(record)
        return stream.getvalue()

    @staticmethod
    def _atomic_write(path: Path | str, text: str) -> dict[str, Any]:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        temporary = destination.with_name(
            ".%s.%s.tmp" % (destination.name, secrets.token_hex(8)))
        try:
            with temporary.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            readback = destination.read_bytes()
            readback_digest = hashlib.sha256(readback).hexdigest()
            if readback_digest != digest:
                raise IOError("export readback SHA-256 mismatch")
            return {
                "path": str(destination),
                "bytes": len(data),
                "sha256": digest,
                "readback_sha256": readback_digest,
            }
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def write_json(self, path: Path | str) -> dict[str, Any]:
        return self._atomic_write(path, self.export_json_text())

    def write_csv(self, path: Path | str) -> dict[str, Any]:
        return self._atomic_write(path, self.export_csv_text())
