"""Pure fail-closed contracts for the Expert local page-status inspector."""

from dataclasses import FrozenInstanceError, replace

import pytest

import expert_filter_scheduling_evidence as filter_evidence
import expert_page_status as page_status
import expert_tuning_offline as expert


def _complete_models():
    current_plant = expert.CurrentPlant(
        resistance_ohm=0.139,
        inductance_h=41.6e-6,
        sampling_time_s=100e-6,
    )
    current_candidate = expert.design_current_candidate(current_plant)
    vp_plant = expert.VelocityPositionPlant(
        current_plant=current_plant,
        current_candidate=current_candidate,
        accel_constant_cnt_per_s2_per_a_peak=5.794e6,
        viscous_friction_a_peak_per_cnt_s=1e-7,
    )
    vp_candidate = expert.design_velocity_position_candidate(vp_plant)
    return current_plant, current_candidate, vp_plant, vp_candidate


def _snapshot(**overrides):
    values = {
        "current_plant": None,
        "current_candidate": None,
        "current_stale": True,
        "current_error": None,
        "vp_plant": None,
        "vp_candidate": None,
        "vp_stale": True,
        "vp_error": None,
        "filter_evidence": filter_evidence.build_evidence_snapshot(),
    }
    values.update(overrides)
    return page_status.build_page_status_snapshot(**values)


def test_empty_status_is_partial_missing_blocked_and_never_ready():
    snapshot = _snapshot()
    pages = {item.key: item for item in snapshot.pages}

    assert snapshot.authority == "LOCAL_STATUS_ONLY"
    assert snapshot.overall == "PARTIAL"
    assert snapshot.can_navigate is True
    assert snapshot.can_calculate is False
    assert snapshot.can_apply is False
    assert snapshot.can_write is False
    assert snapshot.can_query_drive is False
    assert pages["current"].state == "MISSING"
    assert pages["vp"].state == "BLOCKED"
    assert pages["evidence"].state == "DOCUMENTED_PARTIAL"
    rendered = " ".join(
        (snapshot.overall,)
        + tuple(item.state + " " + item.detail for item in snapshot.pages)
    ).upper()
    for forbidden in ("READY", "APPLIED", "EAS COMPLETE", "INSTALLED"):
        assert forbidden not in rendered
    with pytest.raises(FrozenInstanceError):
        snapshot.overall = "READY"


def test_complete_models_are_current_local_only_and_not_installed():
    current_plant, current_candidate, vp_plant, vp_candidate = (
        _complete_models())
    snapshot = _snapshot(
        current_plant=current_plant,
        current_candidate=current_candidate,
        current_stale=False,
        vp_plant=vp_plant,
        vp_candidate=vp_candidate,
        vp_stale=False,
    )
    pages = {item.key: item for item in snapshot.pages}

    assert pages["current"].state == "CURRENT_LOCAL_MODEL"
    assert pages["vp"].state == "CURRENT_LOCAL_MODEL"
    assert "NOT INSTALLED" in pages["current"].detail
    assert "NOT INSTALLED" in pages["vp"].detail
    assert snapshot.overall == "PARTIAL"


def test_complete_current_with_no_p2_is_explicitly_missing():
    current_plant, current_candidate, _, _ = _complete_models()

    snapshot = _snapshot(
        current_plant=current_plant,
        current_candidate=current_candidate,
        current_stale=False,
    )
    pages = {item.key: item for item in snapshot.pages}

    assert pages["current"].state == "CURRENT_LOCAL_MODEL"
    assert pages["vp"].state == "MISSING"


def test_stale_and_invalid_errors_override_retained_historical_objects():
    current_plant, current_candidate, vp_plant, vp_candidate = (
        _complete_models())

    stale = _snapshot(
        current_plant=current_plant,
        current_candidate=current_candidate,
        current_stale=True,
        vp_plant=vp_plant,
        vp_candidate=vp_candidate,
        vp_stale=True,
    )
    stale_pages = {item.key: item for item in stale.pages}
    assert stale_pages["current"].state == "STALE"
    assert stale_pages["vp"].state == "INVALID"

    invalid = _snapshot(
        current_plant=current_plant,
        current_candidate=current_candidate,
        current_stale=True,
        current_error="INVALID_INPUT",
        vp_plant=vp_plant,
        vp_candidate=vp_candidate,
        vp_stale=True,
        vp_error="INVALID_INPUT",
    )
    invalid_pages = {item.key: item for item in invalid.pages}
    assert invalid_pages["current"].state == "INVALID"
    assert invalid_pages["vp"].state == "INVALID"


def test_stale_never_hides_a_mutated_p2_candidate():
    current_plant, current_candidate, vp_plant, vp_candidate = (
        _complete_models())
    mutated_candidate = replace(
        vp_candidate,
        kp_pos_per_s=vp_candidate.kp_pos_per_s * 1.5,
    )

    snapshot = _snapshot(
        current_plant=current_plant,
        current_candidate=current_candidate,
        current_stale=False,
        vp_plant=vp_plant,
        vp_candidate=mutated_candidate,
        vp_stale=True,
    )
    pages = {item.key: item for item in snapshot.pages}

    assert pages["vp"].state == "INVALID"
    assert "incoherent" in pages["vp"].detail.lower()


def test_mismatched_p2_binding_is_never_reported_current():
    current_plant, current_candidate, _, _ = _complete_models()
    other_plant = expert.CurrentPlant(
        resistance_ohm=0.2,
        inductance_h=80e-6,
        sampling_time_s=100e-6,
    )
    other_candidate = expert.design_current_candidate(other_plant)
    mismatched_vp_plant = expert.VelocityPositionPlant(
        current_plant=other_plant,
        current_candidate=other_candidate,
        accel_constant_cnt_per_s2_per_a_peak=5.794e6,
        viscous_friction_a_peak_per_cnt_s=1e-7,
    )
    mismatched_vp_candidate = (
        expert.design_velocity_position_candidate(mismatched_vp_plant))

    snapshot = _snapshot(
        current_plant=current_plant,
        current_candidate=current_candidate,
        current_stale=False,
        vp_plant=mismatched_vp_plant,
        vp_candidate=mismatched_vp_candidate,
        vp_stale=False,
    )
    pages = {item.key: item for item in snapshot.pages}

    assert pages["current"].state == "CURRENT_LOCAL_MODEL"
    assert pages["vp"].state == "INVALID"
    assert "binding" in pages["vp"].detail.lower()


@pytest.mark.parametrize(
    "mutation",
    (
        {"source_sha256": "0" * 64},
        {"conflicts": ()},
        {"model_status": "MODEL"},
    ),
)
def test_mutated_filter_evidence_is_invalid_not_documented_partial(mutation):
    forged = replace(filter_evidence.build_evidence_snapshot(), **mutation)

    snapshot = _snapshot(filter_evidence=forged)
    pages = {item.key: item for item in snapshot.pages}

    assert pages["evidence"].state == "INVALID"
    assert "unexpected" in pages["evidence"].detail.lower()


def test_page_status_build_has_no_file_process_or_network_io(monkeypatch):
    current_plant, current_candidate, vp_plant, vp_candidate = (
        _complete_models())
    evidence = filter_evidence.build_evidence_snapshot()
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("page-status projection must remain pure")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)

    snapshot = page_status.build_page_status_snapshot(
        current_plant=current_plant,
        current_candidate=current_candidate,
        current_stale=False,
        current_error=None,
        vp_plant=vp_plant,
        vp_candidate=vp_candidate,
        vp_stale=False,
        vp_error=None,
        filter_evidence=evidence,
    )
    assert snapshot.overall == "PARTIAL"
    assert calls == []
