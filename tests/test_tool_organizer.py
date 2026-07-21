"""Pure offline contracts for Tool Organizer / Visibility v0.1."""

from __future__ import annotations

import ast
import builtins
from dataclasses import FrozenInstanceError
from pathlib import Path
import socket
import subprocess

import pytest

import tool_organizer as organizer


CANONICAL = (
    "motion",
    "motor",
    "feedback",
    "tuning",
    "axis",
    "recorder",
    "status",
    "system",
)

# The default layout is now the EAS-flow VISUAL order (a permutation of the
# canonical id set); page/stack indices still follow CANONICAL_TOOL_IDS.
DEFAULT = organizer.DEFAULT_NAV_ORDER  # (motor,feedback,axis,tuning,motion,recorder,system,status)


def _layout(active, available):
    return organizer.ToolLayout(active=active, available=available)


def test_default_layout_is_frozen_active_and_exactly_canonical():
    layout = organizer.DEFAULT_LAYOUT

    assert organizer.CANONICAL_TOOL_IDS == CANONICAL
    assert layout.active == DEFAULT           # EAS-flow visual order (a permutation)
    assert set(layout.active) == set(CANONICAL)
    assert layout.available == ()
    assert organizer.validate_layout(layout) is layout
    assert set(layout.active).isdisjoint(layout.available)
    assert set(layout.active) | set(layout.available) == set(CANONICAL)
    with pytest.raises(FrozenInstanceError):
        layout.active = ()


@pytest.mark.parametrize(
    "active,available,error",
    (
        ((), CANONICAL, "at least one active"),
        (CANONICAL[:-1], (), "exact partition"),
        (CANONICAL + ("motion",), (), "duplicate"),
        (("motion",), CANONICAL[1:] + ("motion",), "duplicate"),
        (("Motion",) + CANONICAL[1:], (), "unknown tool id"),
        ((1,) + CANONICAL[1:], (), "tool ids must be strings"),
    ),
)
def test_layout_rejects_all_hidden_missing_duplicate_or_ambiguous_ids(
        active, available, error):
    with pytest.raises(organizer.LayoutRejected, match=error):
        _layout(active, available)


@pytest.mark.parametrize(
    "forged",
    (
        "drive.stop",
        "btn_global_stop",
        "btn_conn",
        "lbl_persistence_badge",
        "disconnect",
        "online",
    ),
)
def test_safety_shell_ids_cannot_be_forged_into_the_visibility_partition(forged):
    with pytest.raises(organizer.LayoutRejected, match="unknown tool id"):
        _layout((forged,) + CANONICAL[1:], ())


def test_validate_layout_rechecks_an_adversarially_forged_frozen_instance():
    forged = object.__new__(organizer.ToolLayout)
    object.__setattr__(forged, "active", ("drive.stop",) + CANONICAL[1:])
    object.__setattr__(forged, "available", ())

    with pytest.raises(organizer.LayoutRejected, match="unknown tool id"):
        organizer.validate_layout(forged)


def test_remove_and_add_return_new_exact_partitions_without_mutating_input():
    original = organizer.DEFAULT_LAYOUT

    removed = organizer.remove_tool(original, "status")
    assert original is organizer.DEFAULT_LAYOUT
    assert original.active == DEFAULT
    assert removed.active == DEFAULT[:-1]          # status is last in DEFAULT
    assert removed.available == ("status",)

    restored = organizer.add_tool(removed, "status")
    assert restored.active == DEFAULT[:-1] + ("status",)
    assert restored.available == ()
    assert organizer.validate_layout(restored) is restored


def test_remove_last_active_tool_is_rejected_without_mutating_the_layout():
    layout = _layout(("motion",), CANONICAL[1:])
    before = (layout.active, layout.available)

    with pytest.raises(organizer.LayoutRejected, match="at least one active"):
        organizer.remove_tool(layout, "motion")

    assert (layout.active, layout.available) == before


@pytest.mark.parametrize(
    "operation,tool_id,error",
    (
        (organizer.remove_tool, "status", "not active"),
        (organizer.add_tool, "motion", "not available"),
        (organizer.remove_tool, "drive.stop", "unknown tool id"),
        (organizer.add_tool, "btn_global_stop", "unknown tool id"),
    ),
)
def test_add_remove_reject_wrong_partition_and_forged_ids_atomically(
        operation, tool_id, error):
    layout = organizer.DEFAULT_LAYOUT
    if operation is organizer.remove_tool and tool_id == "status":
        layout = organizer.remove_tool(layout, "status")
    before = (layout.active, layout.available)

    with pytest.raises(organizer.LayoutRejected, match=error):
        operation(layout, tool_id)

    assert (layout.active, layout.available) == before


def test_move_reorders_only_the_partition_that_owns_the_tool_by_delta():
    original = organizer.DEFAULT_LAYOUT

    # system sits at index 6 in DEFAULT; move it to the front (delta -6)
    moved_active = organizer.move_tool(original, "system", -6)
    assert moved_active.active == ("system",) + DEFAULT[:6] + DEFAULT[7:]
    assert moved_active.available == ()

    hidden = organizer.remove_tool(
        organizer.remove_tool(original, "status"), "system")
    moved_available = organizer.move_tool(hidden, "status", 1)
    assert moved_available.available == ("system", "status")
    assert moved_available.active == DEFAULT[:6]      # motor..recorder


@pytest.mark.parametrize(
    "tool_id,delta,error",
    (
        ("motor", -1, "outside its partition"),   # motor is first in DEFAULT
        ("status", 1, "outside its partition"),    # status is last in DEFAULT
        ("motion", True, "delta"),
        ("motion", 1.5, "delta"),
        ("motion", "1", "delta"),
        ("drive.stop", 1, "unknown tool id"),
    ),
)
def test_move_rejects_invalid_delta_boundary_and_forged_id_atomically(
        tool_id, delta, error):
    layout = organizer.DEFAULT_LAYOUT
    before = (layout.active, layout.available)

    with pytest.raises(organizer.LayoutRejected, match=error):
        organizer.move_tool(layout, tool_id, delta)

    assert (layout.active, layout.available) == before


def test_zero_delta_is_an_explicit_valid_noop():
    layout = organizer.remove_tool(organizer.DEFAULT_LAYOUT, "status")

    assert organizer.move_tool(layout, "status", 0) is layout


def test_reset_defaults_returns_the_single_frozen_canonical_layout():
    # after removing feedback, system sits at index 5; move it to the front
    changed = organizer.move_tool(
        organizer.remove_tool(organizer.DEFAULT_LAYOUT, "feedback"),
        "system", -5)

    reset = organizer.reset_defaults()

    assert reset is organizer.DEFAULT_LAYOUT
    assert reset.active == DEFAULT
    assert reset.available == ()
    assert changed != reset


def test_pure_operations_perform_no_file_network_process_or_serial_io(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Tool Organizer attempted external I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    layout = organizer.remove_tool(organizer.DEFAULT_LAYOUT, "status")
    layout = organizer.move_tool(layout, "status", 0)
    layout = organizer.add_tool(layout, "status")
    layout = organizer.reset_defaults()
    assert organizer.validate_layout(layout) is layout
    assert calls == []


def test_module_is_qt_drive_and_persistence_free_by_construction():
    tree = ast.parse(Path(organizer.__file__).read_text(encoding="utf-8"))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0]
                                  for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint({
        "PyQt6", "serial", "elmo_link", "main", "os", "pathlib", "socket",
        "subprocess",
    })
    for persistence_api in ("save", "load", "export", "import_file"):
        assert not hasattr(organizer, persistence_api)
