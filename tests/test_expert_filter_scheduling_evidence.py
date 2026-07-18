"""Pure contracts for the Expert filter/scheduling evidence inspector."""

from dataclasses import FrozenInstanceError

import pytest

import expert_filter_scheduling_evidence as evidence


def test_snapshot_is_immutable_documented_topology_not_a_filter_model():
    snapshot = evidence.build_evidence_snapshot()

    assert snapshot.authority == "DOCUMENTED_TOPOLOGY_ONLY"
    assert snapshot.model_status == "NEED-DATA"
    assert snapshot.can_inspect is True
    assert snapshot.can_evaluate is False
    assert snapshot.can_emulate is False
    assert snapshot.can_write is False
    assert "MAN-G-CR" in snapshot.source
    assert snapshot.source_sha256 == (
        "55F620EA0E35812BC754FC9B4F7B6C9AF714C1041AECC0EB6DCCAEB63A44F156")
    assert any("SimplIQ" in item and "15.4" in item
               for item in snapshot.missing_evidence)
    assert any("B01G" in item for item in snapshot.missing_evidence)
    assert any("DC gain" in item and "one" in item
               for item in snapshot.documented_facts)
    assert any("motor off" in item.lower()
               for item in snapshot.documented_facts)
    assert any("fifth parameter" in item.lower()
               for item in snapshot.documented_facts)
    with pytest.raises(FrozenInstanceError):
        snapshot.authority = "MODEL"


def test_filter_type_catalog_preserves_only_documented_physical_parameters():
    snapshot = evidence.build_evidence_snapshot()
    by_code = {item.code: item for item in snapshot.filter_types}

    assert tuple(by_code) == tuple(range(7))
    assert by_code[0].name == "Canceled"
    assert by_code[0].parameters == ()
    assert by_code[1].parameters == ("Frequency [Hz]", "Damping")
    assert by_code[2].parameters == ("Frequency [Hz]", "Phase [deg]")
    assert by_code[3].parameters == ("Frequency [Hz]", "Phase [deg]")
    assert by_code[4].parameters == (
        "Frequency [Hz]", "Quality factor", "Attenuation [dB]")
    assert by_code[5].parameters == (
        "Frequency [Hz]", "Quality factor", "Amplification [dB]")
    assert by_code[6].parameters == (
        "Numerator frequency [Hz]",
        "Numerator damping",
        "Denominator frequency [Hz]",
        "Denominator damping",
    )
    assert all(item.exact_transfer_status == "NEED-DATA"
               for item in snapshot.filter_types)


@pytest.mark.parametrize(
    ("value", "category"),
    ((0, "DISABLED"), (1, "FIXED"), (63, "FIXED"),
     (64, "SPEED"), (65, "POSITION"), (66, "PROFILER")),
)
def test_gs2_mode_classifier_is_strict_and_does_not_select_a_controller(
        value, category):
    mode = evidence.classify_gs2_mode(value)

    assert mode.category == category
    assert mode.code_min <= value <= mode.code_max
    assert mode.selection_algorithm_status == "NEED-DATA"


@pytest.mark.parametrize("value", (-1, 67, 1.0, "64", True, None))
def test_gs2_mode_classifier_rejects_out_of_contract_values(value):
    with pytest.raises((TypeError, ValueError)):
        evidence.classify_gs2_mode(value)


@pytest.mark.parametrize("value", (-1, 7, 1.0, "4", True, None))
def test_filter_type_lookup_rejects_out_of_contract_values(value):
    with pytest.raises((TypeError, ValueError)):
        evidence.filter_type_evidence(value)


def test_controller_slots_and_document_conflicts_are_never_normalized_away():
    snapshot = evidence.build_evidence_snapshot()
    locations = {item.key: item for item in snapshot.filter_locations}
    tables = {item.key: item for item in snapshot.kg_tables}

    assert locations["velocity_output_1"].kv_indices == (1, 2, 3, 4, 5)
    assert locations["velocity_output_1"].type_index_candidates == (5,)
    scheduled_position = locations["scheduled_position"]
    assert scheduled_position.type_index_candidates == (45, 50)
    assert scheduled_position.status == "DOCUMENT_CONFLICT"
    assert tables["velocity_ki"].index_range == (1, 63)
    assert tables["velocity_kp"].index_range == (64, 126)
    assert tables["position_kp"].index_range == (127, 189)
    assert tables["scheduled_position_p4"].index_range == (883, 945)
    assert any("1..504" in conflict and "1..945" in conflict
               for conflict in snapshot.conflicts)
    assert any("KV[45]" in conflict and "KV[50]" in conflict
               for conflict in snapshot.conflicts)
    assert any("1..90" in conflict and "KV[91..95]" in conflict
               for conflict in snapshot.conflicts)
    assert any("GS[18,20]" in conflict and "GS[19]" in conflict
               for conflict in snapshot.conflicts)
    assert any(
        "GS[1,6,8,10]" in conflict
        and "GS[8]" in conflict
        and "GS[6]" in conflict
        and "GS[7]" in conflict
        for conflict in snapshot.conflicts
    )
    assert len(snapshot.conflicts) == 5


def test_building_the_snapshot_issues_no_file_process_or_network_io(
        monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("evidence snapshot must be a pure local constant")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)

    snapshot = evidence.build_evidence_snapshot()
    assert snapshot.can_inspect
    assert calls == []
