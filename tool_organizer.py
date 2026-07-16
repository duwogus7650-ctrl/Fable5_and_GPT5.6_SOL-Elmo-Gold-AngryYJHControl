"""Qt-free, zero-I/O layout model for Tool Organizer v0.1.

Only the eight workspace-page identifiers belong to this model.  Connection,
Disconnect, DRIVE STOP, ONLINE state and persistence warnings are deliberately
outside its namespace, so a visibility layout cannot hide the safety shell.
The v0.1 model has no persistence and performs no drive query or command.
"""

from __future__ import annotations

from dataclasses import dataclass


CANONICAL_TOOL_IDS = (
    "motion",
    "motor",
    "feedback",
    "tuning",
    "axis",
    "recorder",
    "status",
    "system",
)
_CANONICAL_TOOL_SET = frozenset(CANONICAL_TOOL_IDS)


class LayoutRejected(ValueError):
    """Raised before an invalid visibility layout can replace the current one."""


# Public feature-level name used by the Qt adapter.  Keep the narrower legacy
# name as an alias so pure-model callers and existing tests remain compatible.
ToolOrganizerError = LayoutRejected


def _validate_partitions(active, available) -> None:
    if not isinstance(active, tuple) or not isinstance(available, tuple):
        raise LayoutRejected("tool partitions must be tuples")

    combined = active + available
    if any(not isinstance(tool_id, str) for tool_id in combined):
        raise LayoutRejected("tool ids must be strings")

    unknown = tuple(
        tool_id for tool_id in combined
        if tool_id not in _CANONICAL_TOOL_SET)
    if unknown:
        raise LayoutRejected("unknown tool id: %s" % unknown[0])

    if len(set(combined)) != len(combined):
        raise LayoutRejected("duplicate tool id in layout")

    if not active:
        raise LayoutRejected("layout requires at least one active tool")

    if len(combined) != len(CANONICAL_TOOL_IDS) or set(combined) != _CANONICAL_TOOL_SET:
        raise LayoutRejected(
            "active and available must form the exact partition of canonical tools")


@dataclass(frozen=True, slots=True)
class ToolLayout:
    """One complete, immutable partition of visible and hidden workspace tools."""

    active: tuple[str, ...]
    available: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_partitions(self.active, self.available)


# Descriptive alias for callers that prefer the feature name over the compact
# integration type.  Both names denote the same frozen class.
ToolOrganizerLayout = ToolLayout

DEFAULT_LAYOUT = ToolLayout(active=CANONICAL_TOOL_IDS, available=())


def validate_layout(layout: ToolLayout) -> ToolLayout:
    """Revalidate a candidate and return that exact frozen instance."""
    if type(layout) is not ToolLayout:
        raise LayoutRejected("layout must be a ToolLayout")
    _validate_partitions(layout.active, layout.available)
    return layout


def _validated_tool_id(tool_id) -> str:
    if not isinstance(tool_id, str) or tool_id not in _CANONICAL_TOOL_SET:
        raise LayoutRejected("unknown tool id: %s" % str(tool_id))
    return tool_id


def remove_tool(layout: ToolLayout, tool_id: str) -> ToolLayout:
    """Return a layout with one active tool moved to the available partition."""
    validate_layout(layout)
    tool_id = _validated_tool_id(tool_id)
    if tool_id not in layout.active:
        raise LayoutRejected("tool is not active: %s" % tool_id)
    if len(layout.active) == 1:
        raise LayoutRejected("layout requires at least one active tool")

    candidate = ToolLayout(
        active=tuple(item for item in layout.active if item != tool_id),
        available=layout.available + (tool_id,),
    )
    return validate_layout(candidate)


def add_tool(layout: ToolLayout, tool_id: str) -> ToolLayout:
    """Return a layout with one available tool appended to the active partition."""
    validate_layout(layout)
    tool_id = _validated_tool_id(tool_id)
    if tool_id not in layout.available:
        raise LayoutRejected("tool is not available: %s" % tool_id)

    candidate = ToolLayout(
        active=layout.active + (tool_id,),
        available=tuple(
            item for item in layout.available if item != tool_id),
    )
    return validate_layout(candidate)


def move_tool(layout: ToolLayout, tool_id: str, delta: int) -> ToolLayout:
    """Return a layout with a tool moved by ``delta`` inside its own partition."""
    validate_layout(layout)
    tool_id = _validated_tool_id(tool_id)
    if not isinstance(delta, int) or isinstance(delta, bool):
        raise LayoutRejected("move delta must be an integer")
    if delta == 0:
        return layout

    source = layout.active if tool_id in layout.active else layout.available
    current_index = source.index(tool_id)
    destination_index = current_index + delta
    if destination_index < 0 or destination_index >= len(source):
        raise LayoutRejected("move would place tool outside its partition")

    reordered = list(source)
    reordered.pop(current_index)
    reordered.insert(destination_index, tool_id)
    if source is layout.active:
        candidate = ToolLayout(
            active=tuple(reordered), available=layout.available)
    else:
        candidate = ToolLayout(
            active=layout.active, available=tuple(reordered))
    return validate_layout(candidate)


def reset_defaults() -> ToolLayout:
    """Return the immutable canonical layout; no file or process state is read."""
    return DEFAULT_LAYOUT
