"""Fail-closed, zero-I/O projection for System Configuration Inspector v0.1.

This module owns no serial port and imports neither Qt nor the drive link.  It
accepts only connection/telemetry evidence that the UI admission boundary has
already received, then freezes a single-target host projection.  EAS workspace
mutation (add/remove/group/I/O/virtual-axis) is intentionally out of scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re
import unicodedata
from types import MappingProxyType
from typing import Callable


SCHEMA_VERSION = "angryyjh.system-configuration-inspector/0.1"
EVIDENCE_CLASS = "HOST_OBSERVED_ALREADY_ADMITTED"
CURRENT = "CURRENT"
NO_CURRENT_TARGET = "NO_CURRENT_TARGET"
SINGLE_DIRECT_DRIVE = "WORKSPACE_TO_SINGLE_DIRECT_DRIVE_ONE_LEVEL"
HOST_RECEIVE_ONLY = "HOST_RECEIVE_ONLY_NO_DRIVE_SOURCE_TIMESTAMP"
DEFAULT_WORKSPACE_NAME = "Current Session"
DEFAULT_TARGET_ALIAS = "Drive01"
MAX_SAMPLE_DURATION_S = 1.0


FIELD_PROVENANCE = MappingProxyType({
    "workspace_name": "HOST PROJECTION",
    "topology": "EAS PUBLIC CONTRACT + HOST PROJECTION",
    "target_alias": "HOST PROJECTION",
    "identity_alias": "DRIVE SN[4] HASH ALIAS",
    "target_type": "APPLICATION CLASSIFICATION (NOT BOARD READBACK)",
    "firmware": "SANITIZED/REDACTED HOST DISPLAY OF DRIVE READBACK · VR",
    "pal": "SANITIZED/REDACTED HOST DISPLAY OF DRIVE READBACK · VP",
    "boot": "SANITIZED/REDACTED HOST DISPLAY OF DRIVE READBACK · VB",
    "connection_type": "HOST CONFIGURATION",
    "generation": "HOST CONNECTION GENERATION",
    "telemetry_sequence": "HOST RECEIVE SEQUENCE",
    "motor_enabled": "ADMITTED DRIVE READBACK · MO",
    "observed_at_utc": "HOST RECEIVE CLOCK",
    "clock_quality": "HOST PROVENANCE",
})


_HASHED_DRIVE_ID_RE = re.compile(r"elmo-sn4-sha256:[0-9a-f]{64}")
_HASHED_ID_IN_TEXT_RE = re.compile(
    r"elmo-sn4-sha256:[0-9a-f]{64}", re.IGNORECASE)
_COM_PORT_IN_TEXT_RE = re.compile(r"\bCOM[0-9]{1,5}\b", re.IGNORECASE)
_LABELED_SERIAL_IN_TEXT_RE = re.compile(
    r"\b(?:serial(?:\s+number)?|s/n|sn\s*\[\s*4\s*\]|sn)"
    r"(?=\s*[:=#]|\s+)\s*[:=#]?\s*[^;,\r\n]*",
    re.IGNORECASE)
_WINDOWS_PATH_IN_TEXT_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\)[^;\r\n]*", re.IGNORECASE)
_POSIX_USER_PATH_IN_TEXT_RE = re.compile(
    r"(?:/home/|/Users/)[^;\r\n]*", re.IGNORECASE)
_REQUIRED_TELEMETRY = ("pos", "vel", "pos_err", "iq", "mo")
_ALLOWED_CONNECTION_TYPES = frozenset(("Direct Access USB",))
_ALLOWED_TARGET_TYPES = frozenset(("Gold Drive",))
_UNSUPPORTED_DISPLAY_CATEGORIES = frozenset(("Cc", "Cf", "Cs", "Zl", "Zp"))


class ProjectionRejected(ValueError):
    """Raised when supplied evidence cannot own the current projection."""


@dataclass(frozen=True)
class SystemConfigurationSnapshot:
    schema_version: str
    evidence_class: str
    state: str
    generation: int | None
    workspace_name: str
    topology: str | None
    target_alias: str | None
    identity_alias: str | None
    target_type: str | None
    firmware: str | None
    pal: str | None
    boot: str | None
    connection_type: str | None
    telemetry_sequence: int | None
    telemetry_received_monotonic: float | None
    sample_finished_monotonic: float | None
    observed_at_utc: str | None
    clock_quality: str
    motor_enabled: bool | None
    reason: str


@dataclass(frozen=True)
class _ActiveContext:
    generation: int
    drive_identity: str
    identity_alias: str
    target_type: str
    firmware: str
    pal: str
    boot: str
    connection_type: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z")


def _clean_text(value, label: str) -> str:
    if not isinstance(value, str):
        raise ProjectionRejected("%s must be a string" % label)
    # NFC preserves the drive's visible metadata while making equivalent
    # combining sequences deterministic.  Controls, bidi-format marks, line
    # separators and surrogates are rejected so readback cannot visually spoof
    # a neighbouring ONLINE/state/value cell in the Inspector.
    cleaned = unicodedata.normalize("NFC", value).strip()
    if not cleaned:
        raise ProjectionRejected("%s is missing" % label)
    if len(cleaned) > 256 or any(
            unicodedata.category(char) in _UNSUPPORTED_DISPLAY_CATEGORIES
            for char in cleaned):
        raise ProjectionRejected("%s contains unsupported text" % label)
    return cleaned


def _safe_display_text(value, label: str) -> str:
    text = _clean_text(value, label)
    return _redact_text(text)


def _redact_text(text: str) -> str:
    text = _HASHED_ID_IN_TEXT_RE.sub("[TARGET_ID_REDACTED]", text)
    text = _COM_PORT_IN_TEXT_RE.sub("[PORT_REDACTED]", text)
    text = _LABELED_SERIAL_IN_TEXT_RE.sub("[SERIAL_REDACTED]", text)
    text = _WINDOWS_PATH_IN_TEXT_RE.sub("[PATH_REDACTED]", text)
    return _POSIX_USER_PATH_IN_TEXT_RE.sub("[PATH_REDACTED]", text)


def _neutralized_display_text(value, label: str) -> str:
    """Return bounded display-only text with visual controls neutralized.

    This boundary is intentionally different from ``_clean_text``: the core
    connection may remain admitted when a vendor metadata string contains an
    unsafe formatting mark, while every host display/export receives only the
    neutralized and privacy-redacted projection.
    """
    if not isinstance(value, str):
        raise ProjectionRejected("%s must be a string" % label)
    try:
        normalized = unicodedata.normalize("NFC", value)
    except (TypeError, ValueError) as exc:
        raise ProjectionRejected("%s contains unsupported text" % label) from exc
    if len(normalized) > 4096:
        raise ProjectionRejected("%s contains unsupported text" % label)
    neutralized = "".join(
        " " if unicodedata.category(char) in _UNSUPPORTED_DISPLAY_CATEGORIES
        else char
        for char in normalized
    )
    cleaned = " ".join(neutralized.split())
    if not cleaned:
        raise ProjectionRejected("%s is missing" % label)
    if len(cleaned) > 256:
        raise ProjectionRejected("%s contains unsupported text" % label)
    return _redact_text(cleaned)


def sanitize_connection_display_metadata(metadata) -> dict[str, str]:
    """Build the only display/export projection of connection metadata."""
    if not isinstance(metadata, dict):
        raise ProjectionRejected("connection metadata must be a mapping")
    target_type = _clean_text(
        metadata.get("target_type"), "target type classification")
    if target_type not in _ALLOWED_TARGET_TYPES:
        raise ProjectionRejected("target type classification is not allowlisted")
    return {
        "fw": _neutralized_display_text(metadata.get("fw"), "firmware"),
        "pal": _neutralized_display_text(metadata.get("pal"), "PAL"),
        "boot": _neutralized_display_text(
            metadata.get("boot"), "boot version"),
        "target_type": target_type,
    }


def _safe_reason(value) -> str:
    """Non-throwing cleanup sanitizer; fail-close paths must always complete."""
    fallback = "Current target authority unavailable"
    try:
        text = str(value) if value not in (None, "") else fallback
        text = unicodedata.normalize("NFC", text)
    except Exception:
        text = fallback
    # A cleanup path must not raise.  Neutralize the same display controls that
    # strict metadata rejects, then collapse whitespace and bound input before
    # redaction.  This prevents bidi/line-control spoofing in the offline row.
    text = "".join(
        " " if unicodedata.category(char) in _UNSUPPORTED_DISPLAY_CATEGORIES
        else char
        for char in text
    )
    text = " ".join(text[:4096].split()) or fallback
    return _redact_text(text)[:500] or fallback


def _generation(value) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProjectionRejected("connection generation must be a positive integer")
    return value


def _finite(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProjectionRejected("%s must be finite" % label)
    number = float(value)
    if not math.isfinite(number):
        raise ProjectionRejected("%s must be finite" % label)
    return number


def _observed_utc(value: str | None, utc_now: Callable[[], str]) -> str:
    text = utc_now() if value is None else _clean_text(value, "observed_at_utc")
    try:
        observed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProjectionRejected("observed_at_utc must be ISO-8601") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ProjectionRejected("observed_at_utc must be timezone-aware")
    return observed.astimezone(timezone.utc).isoformat(
        timespec="microseconds").replace("+00:00", "Z")


def _identity_alias(identity: str) -> str:
    digest = identity.split(":", 1)[1]
    return "TARGET-" + digest[:12].upper()


def _validate_telemetry(telemetry, *, sequence_floor: int,
                        previous_received: float | None,
                        previous_finished: float | None):
    if not isinstance(telemetry, dict):
        raise ProjectionRejected("telemetry must be a mapping")
    if telemetry.get("telemetry_valid") is not True:
        raise ProjectionRejected("telemetry_valid must be exactly true")
    if telemetry.get("session_coordinate_known") is not True:
        raise ProjectionRejected("session coordinate flag must be exactly true")
    if telemetry.get("encoder_maintenance_reconnect_required") is not False:
        raise ProjectionRejected("encoder reconnect flag must be exactly false")

    for key in _REQUIRED_TELEMETRY:
        _finite(telemetry.get(key), key)
    mo = _finite(telemetry.get("mo"), "mo")
    if mo not in (0.0, 1.0):
        raise ProjectionRejected("mo must be exactly 0 or 1")

    sequence = telemetry.get("telemetry_sequence")
    if (not isinstance(sequence, int) or isinstance(sequence, bool)
            or sequence <= sequence_floor):
        raise ProjectionRejected("telemetry sequence must advance")

    received = _finite(
        telemetry.get("telemetry_received_monotonic"),
        "telemetry received timestamp")
    started = _finite(
        telemetry.get("_sample_started_monotonic"),
        "sample started timestamp")
    finished = _finite(
        telemetry.get("_sample_finished_monotonic"),
        "sample finished timestamp")
    duration = _finite(
        telemetry.get("_sample_duration_s"), "sample duration")
    if (finished < started or duration < 0.0
            or duration > MAX_SAMPLE_DURATION_S
            or abs((finished - started) - duration) > 0.05):
        raise ProjectionRejected("sample timestamp envelope is inconsistent")
    if previous_received is not None and received < previous_received:
        raise ProjectionRejected("telemetry received timestamp regressed")
    if previous_finished is not None and finished < previous_finished:
        raise ProjectionRejected("sample finished timestamp regressed")
    return sequence, received, finished, bool(mo)


class SystemConfigurationProjection:
    """One current, generation-bound host projection with fail-closed redaction."""

    def __init__(self, *, utc_now: Callable[[], str] = _utc_now):
        self._utc_now = utc_now
        self._highest_generation = 0
        self._active: _ActiveContext | None = None
        self._last_sequence = 0
        self._last_received: float | None = None
        self._last_finished: float | None = None
        self._snapshot = self._offline_snapshot("No admitted target")

    @property
    def active_generation(self) -> int | None:
        return self._active.generation if self._active is not None else None

    def snapshot(self) -> SystemConfigurationSnapshot:
        return self._snapshot

    @staticmethod
    def _offline_snapshot(reason: str) -> SystemConfigurationSnapshot:
        return SystemConfigurationSnapshot(
            schema_version=SCHEMA_VERSION,
            evidence_class=EVIDENCE_CLASS,
            state=NO_CURRENT_TARGET,
            generation=None,
            workspace_name=DEFAULT_WORKSPACE_NAME,
            topology=None,
            target_alias=None,
            identity_alias=None,
            target_type=None,
            firmware=None,
            pal=None,
            boot=None,
            connection_type=None,
            telemetry_sequence=None,
            telemetry_received_monotonic=None,
            sample_finished_monotonic=None,
            observed_at_utc=None,
            clock_quality=HOST_RECEIVE_ONLY,
            motor_enabled=None,
            reason=_safe_reason(reason),
        )

    def _current_snapshot(self, telemetry, *, observed_at_utc=None):
        if self._active is None:
            raise ProjectionRejected("no active connection owns the projection")
        sequence, received, finished, motor_enabled = _validate_telemetry(
            telemetry,
            sequence_floor=self._last_sequence,
            previous_received=self._last_received,
            previous_finished=self._last_finished,
        )
        observed = _observed_utc(observed_at_utc, self._utc_now)
        active = self._active
        snapshot = SystemConfigurationSnapshot(
            schema_version=SCHEMA_VERSION,
            evidence_class=EVIDENCE_CLASS,
            state=CURRENT,
            generation=active.generation,
            workspace_name=DEFAULT_WORKSPACE_NAME,
            topology=SINGLE_DIRECT_DRIVE,
            target_alias=DEFAULT_TARGET_ALIAS,
            identity_alias=active.identity_alias,
            target_type=active.target_type,
            firmware=active.firmware,
            pal=active.pal,
            boot=active.boot,
            connection_type=active.connection_type,
            telemetry_sequence=sequence,
            telemetry_received_monotonic=received,
            sample_finished_monotonic=finished,
            observed_at_utc=observed,
            clock_quality=HOST_RECEIVE_ONLY,
            motor_enabled=motor_enabled,
            reason="Accepted current-generation callback projection",
        )
        self._last_sequence = sequence
        self._last_received = received
        self._last_finished = finished
        self._snapshot = snapshot
        return snapshot

    def admit_connection(self, metadata, telemetry, *, generation,
                         connection_type, observed_at_utc=None):
        if not isinstance(metadata, dict):
            raise ProjectionRejected("connection metadata must be a mapping")
        generation_value = _generation(generation)
        if generation_value <= self._highest_generation:
            raise ProjectionRejected("connection generation must be newer")
        identity = _clean_text(metadata.get("drive_identity"), "drive identity")
        if _HASHED_DRIVE_ID_RE.fullmatch(identity) is None:
            raise ProjectionRejected("drive identity is not a strict SN[4] hash")
        connection = _clean_text(connection_type, "connection type")
        if connection not in _ALLOWED_CONNECTION_TYPES:
            raise ProjectionRejected("connection type is not allowlisted")
        target_type = _clean_text(
            metadata.get("target_type"), "target type classification")
        if target_type not in _ALLOWED_TARGET_TYPES:
            raise ProjectionRejected("target type classification is not allowlisted")
        context = _ActiveContext(
            generation=generation_value,
            drive_identity=identity,
            identity_alias=_identity_alias(identity),
            target_type=target_type,
            firmware=_safe_display_text(metadata.get("fw"), "firmware"),
            pal=_safe_display_text(metadata.get("pal"), "PAL"),
            boot=_safe_display_text(metadata.get("boot"), "boot version"),
            connection_type=connection,
        )

        # Validate before replacing the previous context. Rejected admissions
        # cannot erase or partially mutate the last accepted projection.
        sequence, received, finished, motor_enabled = _validate_telemetry(
            telemetry, sequence_floor=0,
            previous_received=None, previous_finished=None)
        observed = _observed_utc(observed_at_utc, self._utc_now)
        snapshot = SystemConfigurationSnapshot(
            schema_version=SCHEMA_VERSION,
            evidence_class=EVIDENCE_CLASS,
            state=CURRENT,
            generation=context.generation,
            workspace_name=DEFAULT_WORKSPACE_NAME,
            topology=SINGLE_DIRECT_DRIVE,
            target_alias=DEFAULT_TARGET_ALIAS,
            identity_alias=context.identity_alias,
            target_type=context.target_type,
            firmware=context.firmware,
            pal=context.pal,
            boot=context.boot,
            connection_type=context.connection_type,
            telemetry_sequence=sequence,
            telemetry_received_monotonic=received,
            sample_finished_monotonic=finished,
            observed_at_utc=observed,
            clock_quality=HOST_RECEIVE_ONLY,
            motor_enabled=motor_enabled,
            reason="Accepted current-generation callback projection",
        )
        self._highest_generation = generation_value
        self._active = context
        self._last_sequence = sequence
        self._last_received = received
        self._last_finished = finished
        self._snapshot = snapshot
        return snapshot

    def update_telemetry(self, telemetry, *, generation, drive_identity,
                         observed_at_utc=None):
        generation_value = _generation(generation)
        if self._active is None:
            raise ProjectionRejected("no active connection owns the projection")
        if generation_value != self._active.generation:
            raise ProjectionRejected("telemetry generation does not own projection")
        identity = _clean_text(drive_identity, "drive identity")
        if (_HASHED_DRIVE_ID_RE.fullmatch(identity) is None
                or identity != self._active.drive_identity):
            raise ProjectionRejected("telemetry identity does not own projection")
        return self._current_snapshot(
            telemetry, observed_at_utc=observed_at_utc)

    def revoke_live(self, reason, *, generation=None):
        if self._active is None:
            self._snapshot = self._offline_snapshot(reason)
            return self._snapshot
        if generation is not None and _generation(generation) != self._active.generation:
            raise ProjectionRejected("revocation generation does not own projection")
        self._snapshot = self._offline_snapshot(reason)
        return self._snapshot

    def end_connection(self, reason, *, generation=None):
        if (self._active is not None and generation is not None
                and _generation(generation) != self._active.generation):
            raise ProjectionRejected("end generation does not own projection")
        self._active = None
        self._last_sequence = 0
        self._last_received = None
        self._last_finished = None
        self._snapshot = self._offline_snapshot(reason)
        return self._snapshot
