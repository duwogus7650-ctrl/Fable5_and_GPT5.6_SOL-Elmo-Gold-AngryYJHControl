"""Pure contracts for the Expert DS-402 position-scale preview."""

from dataclasses import FrozenInstanceError
from fractions import Fraction

import pytest

import expert_user_units as user_units


def _preview(**overrides):
    values = {
        "fc1": 10_000,
        "fc2": 1,
        "fc5": 1,
        "fc6": 1,
        "fc7": 1_000,
        "fc8": 10,
        "unit_label": "  micrometre   (um) ",
        "sample_counts": 100,
    }
    values.update(overrides)
    return user_units.build_position_scale_preview(**values)


def test_nethelp_golden_example_is_exact_and_explicitly_local_only():
    preview = _preview()

    assert preview.authority == "DOCUMENTED_FORMULA_PREVIEW"
    assert preview.model_status == "PARTIAL_SCREENING"
    assert preview.units_per_count == Fraction(1, 100)
    assert preview.counts_per_unit == Fraction(100, 1)
    assert preview.sample_counts == 100
    assert preview.sample_units == Fraction(1, 1)
    assert preview.units_per_count_decimal == "0.01"
    assert preview.counts_per_unit_decimal == "100"
    assert preview.sample_units_decimal == "1"
    assert preview.unit_label == "micrometre (um)"
    assert preview.can_read_drive is False
    assert preview.can_write is False
    assert preview.can_apply is False
    assert preview.can_persist is False
    assert "NOT CURRENT DRIVE CONFIG" in preview.boundary
    assert "NO FC/OF WRITE" in preview.boundary
    assert "NO DRIVE I/O" in preview.boundary


def test_formula_index_grouping_and_literal_limit_groupings_are_independent():
    preview = user_units.build_position_scale_preview(
        fc1=2,
        fc2=3,
        fc5=5,
        fc6=7,
        fc7=11,
        fc8=13,
    )

    # NetHelp equation: (FC2 * FC6 * FC7) / (FC1 * FC5 * FC8).
    assert preview.units_per_count == Fraction(3 * 7 * 11, 2 * 5 * 13)
    swapped_fc1_fc2 = Fraction(2 * 7 * 11, 3 * 5 * 13)
    swapped_fc5_fc6 = Fraction(3 * 5 * 11, 2 * 7 * 13)
    assert preview.units_per_count != swapped_fc1_fc2
    assert preview.units_per_count != swapped_fc5_fc6
    assert preview.formula_grouping == (
        "(FC2*FC6*FC7)/(FC1*FC5*FC8)"
    )

    # MAN-G-CR restrictions are retained literally and are deliberately not
    # misrepresented as the equation numerator/denominator.
    assert preview.documented_limit_groupings == (
        "FC1*FC6*FC8 < 2^63",
        "FC2*FC5*FC7 < 2^63",
    )
    assert preview.documented_limit_products == (
        2 * 7 * 13,
        3 * 5 * 11,
    )
    assert preview.document_conflict
    assert "grouping mismatch" in preview.document_conflict.lower()
    assert "need-data" in preview.document_conflict.lower()
    assert preview.document_conflict in preview.limitations


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("fc1", True),
        ("fc2", False),
        ("fc5", 1.0),
        ("fc6", "1"),
        ("fc7", None),
        ("fc8", Fraction(1, 1)),
        ("fc1", 0),
        ("fc2", -1),
        ("fc5", 2**31),
        ("fc8", 2**31 + 1),
    ),
)
def test_fc_inputs_are_strict_bounded_integers(field, value):
    with pytest.raises((TypeError, ValueError), match=field.upper()):
        _preview(**{field: value})


def test_first_literal_man_g_cr_product_guard_rejects_at_2_to_63():
    with pytest.raises(
            ValueError, match=r"FC1\*FC6\*FC8.*< 2\^63"):
        user_units.build_position_scale_preview(
            fc1=2**31 - 1,
            fc2=1,
            fc5=1,
            fc6=2**31 - 1,
            fc7=1,
            fc8=3,
        )


def test_second_literal_man_g_cr_product_guard_rejects_at_2_to_63():
    with pytest.raises(
            ValueError, match=r"FC2\*FC5\*FC7.*< 2\^63"):
        user_units.build_position_scale_preview(
            fc1=1,
            fc2=2**31 - 1,
            fc5=2**31 - 1,
            fc6=1,
            fc7=3,
            fc8=1,
        )


@pytest.mark.parametrize(
    "values",
    (
        {
            "fc1": 2**21,
            "fc2": 1,
            "fc5": 1,
            "fc6": 2**21,
            "fc7": 1,
            "fc8": 2**21,
        },
        {
            "fc1": 1,
            "fc2": 2**21,
            "fc5": 2**21,
            "fc6": 1,
            "fc7": 2**21,
            "fc8": 1,
        },
    ),
)
def test_literal_man_g_cr_product_guards_reject_exactly_at_2_to_63(
        values):
    with pytest.raises(ValueError, match=r"< 2\^63"):
        user_units.build_position_scale_preview(**values)


@pytest.mark.parametrize(
    "sample_counts",
    (
        True,
        1.0,
        "100",
        Fraction(100, 1),
        user_units.MAX_LOCAL_SAMPLE_COUNTS + 1,
        -(user_units.MAX_LOCAL_SAMPLE_COUNTS + 1),
    ),
)
def test_optional_sample_count_is_a_conservatively_bounded_signed_integer(
        sample_counts):
    with pytest.raises((TypeError, ValueError), match="sample_counts"):
        _preview(sample_counts=sample_counts)


def test_optional_sample_and_unit_label_have_deterministic_defaults():
    preview = _preview(sample_counts=None, unit_label=" \t ")

    assert preview.sample_counts is None
    assert preview.sample_units is None
    assert preview.sample_units_decimal is None
    assert preview.unit_label == "unit"


@pytest.mark.parametrize(
    ("sample_counts", "expected"),
    (
        (-100, Fraction(-1, 1)),
        (0, Fraction(0, 1)),
        (
            user_units.MAX_LOCAL_SAMPLE_COUNTS,
            Fraction(user_units.MAX_LOCAL_SAMPLE_COUNTS, 100),
        ),
        (
            -user_units.MAX_LOCAL_SAMPLE_COUNTS,
            Fraction(-user_units.MAX_LOCAL_SAMPLE_COUNTS, 100),
        ),
    ),
)
def test_signed_sample_conversion_preserves_direction_and_boundaries(
        sample_counts, expected):
    preview = _preview(sample_counts=sample_counts)

    assert preview.sample_counts == sample_counts
    assert preview.sample_units == expected


def test_repeating_decimal_uses_fixed_half_even_display_contract():
    preview = user_units.build_position_scale_preview(
        fc1=3,
        fc2=2,
        fc5=1,
        fc6=1,
        fc7=1,
        fc8=1,
    )

    assert preview.units_per_count == Fraction(2, 3)
    assert preview.units_per_count_decimal == "0.666666666666667"


def test_unicode_unit_label_accepts_48_codepoints_and_rejects_49():
    accepted = _preview(unit_label="µ" * 48)

    assert accepted.unit_label == "µ" * 48
    with pytest.raises(ValueError, match="48"):
        _preview(unit_label="µ" * 49)


def test_result_is_frozen_and_repeated_builds_are_deterministic():
    first = _preview()
    second = _preview()

    assert first == second
    assert hash(first) == hash(second)
    with pytest.raises(FrozenInstanceError):
        first.authority = "VALID_DRIVE_CONFIG"


def test_document_sources_are_fixed_hashes_without_runtime_reads():
    preview = _preview()
    by_key = {source.key: source for source in preview.sources}

    assert by_key["nethelp_html"].sha256 == (
        "BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE"
    )
    assert by_key["nethelp_formula_image"].sha256 == (
        "772B95FB672E43F54573AE498F137450810E601EB76636790275BC2B2E935CD9"
    )
    assert by_key["command_reference"].sha256 == (
        "89280DB57DBBE6877945CC8C4720C959B8295E68806DECBFB9F43892994C2A80"
    )
    assert all(len(source.sha256) == 64 for source in preview.sources)


def test_preview_build_has_no_file_process_or_network_io(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("documented formula preview must remain pure")

    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("socket.socket", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)

    preview = _preview()

    assert preview.units_per_count == Fraction(1, 100)
    assert calls == []
