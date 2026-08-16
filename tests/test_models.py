from __future__ import annotations

import pytest

import config
from ledgerlens.models import (
    canonical_cohort_key,
    cohort_complement,
    cohort_intersect,
    cohort_is_empty,
    cohort_predicate,
    validate_cohort,
)


def test_predicate_unconstrained_is_true():
    assert cohort_predicate({}) == "TRUE"


def test_predicate_renders_sorted_conjunction():
    pred = cohort_predicate({"segment": ["Enterprise"], "region": ["DACH"]})
    assert pred == "region IN ('DACH') AND segment IN ('Enterprise')"


def test_predicate_disjunction_within_key():
    assert cohort_predicate({"segment": ["Mid", "SMB"]}) == "segment IN ('Mid', 'SMB')"


def test_predicate_empty_key_selects_nothing():
    assert cohort_predicate({"region": []}) == "FALSE"
    assert cohort_is_empty({"region": []})


def test_intersect_disjoint_shared_key_is_none():
    # This is the filter that eliminates the US pricing decoy before it can score.
    assert cohort_intersect({"region": ["DACH"]}, {"region": ["US"]}) is None


def test_intersect_unconstrained_key_carries_through():
    got = cohort_intersect({"region": ["DACH"]}, {"segment": ["Enterprise"]})
    assert got == {"region": ["DACH"], "segment": ["Enterprise"]}


def test_intersect_overlapping_values():
    got = cohort_intersect({"region": ["DACH", "UK"]}, {"region": ["UK", "US"]})
    assert got == {"region": ["UK"]}


def test_complement_flips_one_dimension():
    base = {"region": ["DACH"], "segment": ["Enterprise"]}
    got = cohort_complement(base, "region", config.DIMENSIONS["region"])
    assert got["segment"] == ["Enterprise"]
    assert set(got["region"]) == {"UK", "FR", "US", "APAC", "Nordics"}
    assert len(got["region"]) == 5


def test_complement_of_unconstrained_dimension_raises():
    with pytest.raises(ValueError):
        cohort_complement({"segment": ["Enterprise"]}, "region", config.DIMENSIONS["region"])


def test_canonical_key_is_order_invariant():
    a = {"region": ["DACH"], "segment": ["Mid", "Enterprise"]}
    b = {"segment": ["Enterprise", "Mid"], "region": ["DACH"]}
    assert canonical_cohort_key(a) == canonical_cohort_key(b)


def test_validate_rejects_unknown_value():
    with pytest.raises(ValueError):
        validate_cohort({"region": ["DACHH"]}, config.DIMENSIONS)


def test_validate_rejects_unknown_dimension():
    with pytest.raises(ValueError):
        validate_cohort({"continent": ["EU"]}, config.DIMENSIONS)


def test_validate_accepts_known_cohort():
    validate_cohort(config.TARGET_COHORT, config.DIMENSIONS)
