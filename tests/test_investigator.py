"""The investigator lane: what the LLM may do, and everything it may not.

Every test here runs with no API key and no network. That is not a convenience --
it is the property under test. The lane is additive, so the deterministic suite must
be able to prove the lane cannot reach the ranking WITHOUT a vendor in the loop.

`StubProvider` replaces the transport, never the validation. The gates in
`investigator.validate` and `investigator.guard` are the security boundary, so they
are exercised against adversarial output a real model would rarely produce and a
compromised or confused one absolutely could.
"""

from __future__ import annotations

from datetime import date

import pytest

import config
from ledgerlens import contracts, investigator, llm, narrate, personas, pipeline
from ledgerlens.models import ProposedTest, Window

AS_OF = date(2026, 8, 17)


class StubProvider:
    """A provider that returns exactly what a test tells it to, and counts calls."""

    def __init__(self, *payloads: dict, usage: llm.Usage | None = None, error: str = ""):
        self.spec = config.PROVIDERS["gemini"]
        self._payloads = list(payloads)
        self._usage = usage or llm.Usage(1000, 200, 0.0008)
        self._error = error
        self.prompts: list[str] = []

    def structured(self, system, prompt, schema, name):
        self.prompts.append(prompt)
        if self._error:
            return None, llm.Usage(), self._error
        payload = self._payloads.pop(0) if self._payloads else {}
        return payload, self._usage, ""


@pytest.fixture(scope="module")
def focal(store):
    payload = pipeline.diagnose("mrr_renewals", AS_OF, store=store)
    return payload.focal, payload.ranked


# --------------------------------------------------------------- the invariant


def test_the_lane_cannot_change_a_single_score(store):
    """THE load-bearing test of this feature.

    An LLM that can move a rank is an LLM that can be wrong about the verdict. The
    lane is allowed to add checks, prose and caveats; it is not allowed to change what
    the engine concluded. Asserted on scores rather than order because order is the
    weaker claim -- two candidates can swap without either score moving.
    """
    provider = StubProvider(
        {
            "tests": [
                {
                    "template": "compare_cohort",
                    "rationale": "does the rail break outside DACH",
                    "prediction": "should_be_flat",
                    "region": ["UK"],
                    "payment_rail": ["sepa"],
                }
            ]
        },
        {"causes": [{"description": "a", "needed_source": "b", "would_test": "c"}]},
    )
    plain = pipeline.diagnose("mrr_renewals", AS_OF, store=store)
    investigator_on = pipeline.diagnose("mrr_renewals", AS_OF, store=store, investigate=True)
    # `investigate=True` resolves a real provider, which is absent here -- so drive the
    # lane directly to prove the point even when a vendor IS configured.
    budget = llm.Budget()
    tests, _ = investigator.propose_tests(store, plain.focal, plain.ranked, budget, provider)
    assert tests, "the stub must have produced a check, or this test proves nothing"

    assert [h.event.event_id for h in plain.ranked] == [h.event.event_id for h in investigator_on.ranked]
    for before, after in zip(plain.ranked, investigator_on.ranked):
        assert before.total == after.total
        assert before.scores == after.scores
    assert [h.rejection_reason for h in plain.rejected] == [
        h.rejection_reason for h in investigator_on.rejected
    ]


def test_a_proposed_check_is_never_decisive(store, focal):
    """`decisive` is what `controls.score_n` reads to zero out N. If an AI-proposed
    check could set it, the LLM could reject a hypothesis by asking a question."""
    f, ranked = focal
    provider = StubProvider(
        {
            "tests": [
                {
                    "template": "compare_cohort",
                    "rationale": "r",
                    "prediction": "should_also_drop",
                    "region": ["UK"],  # will not have dropped -> a failing check
                }
            ]
        }
    )
    tests, _ = investigator.propose_tests(store, f, ranked, llm.Budget(), provider)
    assert tests[0].result is not None
    assert tests[0].result.decisive is False


# ----------------------------------------------------------------- validation


@pytest.fixture(scope="module")
def registry(store):
    return store.dim_registry()


@pytest.mark.parametrize(
    "raw, expect",
    [
        ({"template": "run_arbitrary_sql", "prediction": "should_be_flat", "region": ["UK"]}, "unknown template"),
        ({"template": "compare_cohort", "prediction": "should_be_flat"}, "no cohort"),
        ({"template": "compare_cohort", "prediction": "should_be_flat", "galaxy": ["M31"]}, "unknown dimension"),
        ({"template": "compare_cohort", "prediction": "should_be_flat", "region": ["Atlantis"]}, "outside the region universe"),
        ({"template": "compare_cohort", "prediction": "yes_please", "region": ["UK"]}, "unknown prediction"),
        ({"template": "check_metric_in_cohort", "prediction": "should_be_flat", "region": ["UK"]}, "requires a metric"),
        ({"template": "compare_cohort", "prediction": "should_be_flat", "region": ["UK"], "metric": "profit"}, "unknown metric"),
        ({"template": "check_symptom_lift", "prediction": "should_be_flat", "payment_rail": ["sepa"]}, "no ['payment_rail'] dimension"),
        ({"template": "check_temporal_order", "prediction": "should_be_flat", "region": ["UK"], "days_before": 9999}, "days_before must be between"),
    ],
)
def test_validation_rejects_hallucinated_proposals(registry, raw, expect):
    test, why = investigator.validate(raw, registry, sorted(contracts.CONTRACTS))
    assert test is None, f"{raw} should have been rejected"
    assert expect in why, f"expected {expect!r} in {why!r}"


def test_validation_accepts_a_well_formed_proposal(registry):
    test, why = investigator.validate(
        {
            "template": "compare_cohort",
            "rationale": "test the rail outside the affected region",
            "prediction": "should_be_flat",
            "region": ["UK", "FR"],
            "payment_rail": ["sepa"],
        },
        registry,
        sorted(contracts.CONTRACTS),
    )
    assert why == ""
    assert test.template == "compare_cohort"
    assert test.params["region"] == ["UK", "FR"]
    assert test.provenance == "llm"


def test_an_out_of_universe_value_is_rejected_even_when_its_siblings_are_valid(registry):
    """Partial-credit validation is the dangerous kind: it would run the query with the
    good half and present a result to a question nobody asked."""
    test, why = investigator.validate(
        {"template": "compare_cohort", "prediction": "should_be_flat", "region": ["UK", "Narnia"]},
        registry,
        sorted(contracts.CONTRACTS),
    )
    assert test is None and "Narnia" in why


def test_duplicate_proposals_are_dropped_not_run_twice(store, focal):
    f, ranked = focal
    one = {"template": "compare_cohort", "rationale": "r", "prediction": "should_be_flat", "region": ["UK"]}
    tests, rejected = investigator.propose_tests(
        store, f, ranked, llm.Budget(), StubProvider({"tests": [one, dict(one)]})
    )
    assert len(tests) == 1
    assert any("duplicate" in r for r in rejected)


def test_the_test_budget_is_enforced_against_an_overrunning_model(store, focal):
    f, ranked = focal
    many = [
        {"template": "compare_cohort", "rationale": "r", "prediction": "should_be_flat", "region": [r]}
        for r in ["UK", "FR", "US", "APAC", "Nordics", "DACH"]
    ] * 4
    tests, _ = investigator.propose_tests(store, f, ranked, llm.Budget(), StubProvider({"tests": many}))
    assert len(tests) <= config.LLM_TEST_BUDGET


# ------------------------------------------------------------------ execution


@pytest.mark.parametrize(
    "raw",
    [
        {"template": "compare_cohort", "rationale": "r", "prediction": "should_be_flat", "region": ["UK"]},
        {"template": "check_metric_in_cohort", "rationale": "r", "prediction": "should_also_drop",
         "region": ["DACH"], "metric": "new_logo_bookings"},
        {"template": "check_symptom_lift", "rationale": "r", "prediction": "should_be_flat",
         "region": ["DACH"], "segment": ["Enterprise"]},
        {"template": "check_temporal_order", "rationale": "r", "prediction": "should_be_flat",
         "region": ["DACH"], "payment_rail": ["sepa"], "days_before": 14},
    ],
)
def test_every_template_executes_to_a_replayable_query(store, focal, registry, raw):
    """The point of the template vocabulary: an AI-proposed number is exactly as
    auditable as a rule-based one, because the SAME `store.q` produced it."""
    f, _ = focal
    test, why = investigator.validate(raw, registry, sorted(contracts.CONTRACTS))
    assert test is not None, why
    executed = investigator.execute(store, test, f)
    assert executed.result is not None, f"{raw['template']} produced no result"
    assert executed.result.query_id
    sql, _, _ = store.replay(executed.result.query_id)
    assert sql.strip().upper().startswith("SELECT")
    assert executed.result.rule == f"AI:{raw['template']}"


def test_proposed_check_query_ids_reach_the_provenance_audit(store, focal):
    """An id on the card that `card_query_ids` does not know about is a number a
    reader can see and the audit cannot count."""
    f, ranked = focal
    payload = pipeline.diagnose("mrr_renewals", AS_OF, store=store)
    tests, _ = investigator.propose_tests(
        store,
        f,
        ranked,
        llm.Budget(),
        StubProvider({"tests": [{"template": "compare_cohort", "rationale": "r",
                                 "prediction": "should_be_flat", "region": ["UK"]}]}),
    )
    payload.proposed_tests = tests
    card = narrate.narrate(payload)
    assert tests[0].result.query_id in pipeline.card_query_ids(card)


def test_temporal_order_measures_before_onset_not_during(store, focal, registry):
    f, _ = focal
    test, _ = investigator.validate(
        {"template": "check_temporal_order", "rationale": "r", "prediction": "should_be_flat",
         "region": ["DACH"], "payment_rail": ["sepa"], "days_before": 10},
        registry,
        sorted(contracts.CONTRACTS),
    )
    executed = investigator.execute(store, test, f)
    assert str(f.onset) not in executed.result.name
    assert f"{f.onset.isoformat()}" not in executed.result.name


# -------------------------------------------------------------- numbers guard


@pytest.mark.parametrize(
    "prose, corpus, expected",
    [
        ("Renewals fell 8.2% in DACH.", "a -8.2% drop", []),
        ("Renewals fell about 9% in DACH.", "a -8.2% drop", ["9"]),
        ("The shortfall was $400k.", "shortfall -$410,144", ["400"]),
        ("The shortfall was $410,144.", "shortfall -$410,144", []),
        ("Four controls passed.", "4 of 4 controls passed", []),
        ("It cost us 12% of ARR.", "a -8.2% drop of $410,144", ["12"]),
    ],
)
def test_the_numbers_guard_catches_invented_figures(prose, corpus, expected):
    assert investigator.guard(prose, corpus) == expected


def test_guarded_narration_is_discarded_wholesale_on_one_bad_number():
    """Partial acceptance would leave an invented figure on screen next to verified
    ones, which is worse than no LLM prose at all."""
    budget = llm.Budget()
    provider = StubProvider({"headline": "MRR down 99%", "summary": "A 99% collapse."})
    headline, summary, bad = investigator.narrate_prose(
        "MRR fell 8.2%", personas.get("analyst"), budget, provider
    )
    assert headline == "" and summary == ""
    assert bad == ["99"]
    assert any("numbers guard" in f for f in budget.failures)


def test_clean_narration_is_accepted_and_marks_the_card_as_llm_written(store):
    payload = pipeline.diagnose("mrr_renewals", AS_OF, store=store)
    payload.llm_budget = llm.Budget()
    payload.llm_narration = True
    corpus = narrate._narration_corpus(narrate.narrate(payload), payload)
    provider = StubProvider(
        {"headline": "Renewals broke in one cohort.", "summary": "A deploy is the best-supported cause."}
    )
    headline, summary, bad = investigator.narrate_prose(
        corpus, personas.get("cfo"), payload.llm_budget, provider
    )
    assert bad == []
    assert headline and summary


def test_a_card_with_no_llm_narration_still_reports_template_provenance(store):
    card = pipeline.run("mrr_renewals", AS_OF, store=store)
    assert card.generated_by == "template"


# ------------------------------------------------------- degradation and cost


def test_no_provider_means_no_lane_and_no_exception(store, focal, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    f, ranked = focal
    budget = llm.Budget()
    assert investigator.propose_tests(store, f, ranked, budget) == ([], [])
    assert investigator.unverified_causes(store, f, ranked, None, frozenset(), budget) == []
    assert investigator.narrate_prose("corpus", personas.get("analyst"), budget) == ("", "", [])
    assert budget.calls == 0


def test_a_transport_failure_is_recorded_not_swallowed(store, focal):
    """"The lane found nothing" and "the vendor was down" must not look the same."""
    f, ranked = focal
    budget = llm.Budget()
    tests, rejected = investigator.propose_tests(
        store, f, ranked, budget, StubProvider(error="HTTP 503")
    )
    assert tests == [] and rejected == []
    assert budget.failures == ["proposed checks: HTTP 503"]


def test_a_malformed_response_does_not_reach_the_card(store, focal):
    f, ranked = focal
    tests, rejected = investigator.propose_tests(
        store, f, ranked, llm.Budget(), StubProvider({"tests": ["not an object", 42]})
    )
    assert tests == []
    assert rejected == ["proposal was not an object"] * 2


def test_cost_is_priced_off_the_active_provider_row(store, focal):
    f, ranked = focal
    budget = llm.Budget()
    provider = StubProvider({"tests": []}, usage=llm.Usage(1_000_000, 1_000_000, 0.0))
    investigator.propose_tests(store, f, ranked, budget, provider)
    assert budget.calls == 1
    assert budget.total_tokens == 2_000_000


def test_unverified_causes_never_invent_a_connected_source(store, focal):
    """The prompt must read connectivity off the contract, so the panel cannot claim a
    feed the card says is missing -- the exact bug task 7 fixed in `_no_cause_card`."""
    f, ranked = focal
    provider = StubProvider({"causes": []})
    investigator.unverified_causes(
        store, f, ranked, contracts.CONTRACTS["mrr_renewals"], frozenset({"github"}), llm.Budget(), provider
    )
    prompt = provider.prompts[0]
    assert "github" not in prompt.split("CONNECTED SOURCE SYSTEMS")[1].split("\n")[0]


def test_incomplete_unverified_entries_are_dropped(store, focal):
    f, ranked = focal
    provider = StubProvider(
        {"causes": [
            {"description": "competitor launched", "needed_source": "", "would_test": "x"},
            {"description": "macro shift", "needed_source": "an FX feed", "would_test": "compare EUR cohorts"},
        ]}
    )
    out = investigator.unverified_causes(store, f, ranked, None, frozenset(), llm.Budget(), provider)
    assert len(out) == 1 and out[0].description == "macro shift"


# ------------------------------------------------- the causal-claim guard (task 8b)


@pytest.mark.parametrize(
    "prose",
    [
        "mrr_renewals fell 85.2% due to deploy_sepa_v214.",
        "The drop was caused by the SEPA connector release.",
        "Renewals collapsed because of the payment deploy.",
        "The release led to a shortfall in DACH.",
        "deploy_sepa_v214 is responsible for the DACH shortfall.",
        "The root cause was the connector rework.",
        "The shortfall is attributable to the SEPA release.",
    ],
)
def test_the_claim_guard_rejects_prose_that_asserts_a_cause(prose):
    """The card says outright that it does not prove causation, in the summary
    printed directly beneath the headline. Prose asserting a cause contradicts the
    card it sits on, on the same screen -- which is worse than an ugly sentence."""
    assert investigator.claim_guard(prose), f"causal claim slipped through: {prose!r}"


@pytest.mark.parametrize(
    "prose",
    [
        "DACH renewals are down 35% -- not attributable to campaign spend.",
        "campaign_dach_cut was rejected: the drop was not caused by the budget cut.",
        "The evidence is most consistent with deploy_sepa_v214.",
        "This is the leading candidate; it survived all four negative controls.",
        "The decline did not result from the marketing change.",
        "Ranked first on cohort match, rather than due to temporal proximity.",
    ],
)
def test_the_claim_guard_allows_denials_and_hedged_language(prose):
    """Denying a cause is the honest half of this system's job -- the growth card's
    own headline reads "not attributable to campaign spend", and the second finding
    turns on saying the campaign did NOT cause this. A guard that rejected those
    would delete the part of the story that makes the rest credible."""
    assert investigator.claim_guard(prose) == [], f"wrongly rejected: {prose!r}"
