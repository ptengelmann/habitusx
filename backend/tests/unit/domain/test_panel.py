from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from habitusx.domain.panel import (
    SAMPLE_SPACE,
    Cohort,
    Panel,
    PanelMember,
    build_panel,
    in_sample,
    sample_key,
)

DAY = date(2026, 9, 5)


class TestSampleKey:
    def test_deterministic_and_case_insensitive(self) -> None:
        assert sample_key("Octo/Repo") == sample_key("octo/repo") == sample_key("  octo/repo ")

    def test_different_repos_differ(self) -> None:
        assert sample_key("octo/repo") != sample_key("octo/repo2")

    @given(st.text(min_size=1))
    def test_always_in_range(self, repo: str) -> None:
        assert 0 <= sample_key(repo) < SAMPLE_SPACE

    def test_known_value_is_stable_across_releases(self) -> None:
        # Pinned so a change to the hashing scheme is a deliberate, visible decision.
        assert sample_key("octo/repo") == 9427


class TestInSample:
    def test_rate_zero_and_one(self) -> None:
        assert in_sample("octo/repo", 0.0) is False
        assert in_sample("octo/repo", 1.0) is True

    def test_rate_selects_roughly_the_expected_share(self) -> None:
        repos = [f"owner{i}/repo{i}" for i in range(20_000)]
        share = sum(in_sample(r, 0.1) for r in repos) / len(repos)
        assert 0.09 < share < 0.11

    @pytest.mark.parametrize("rate", [-0.1, 1.1])
    def test_rejects_bad_rates(self, rate: float) -> None:
        with pytest.raises(ValueError, match="between 0 and 1"):
            in_sample("octo/repo", rate)


class TestBuildPanel:
    def test_cohorts_do_not_overlap_and_output_is_sorted(self) -> None:
        treated_all = [f"t{i}/r" for i in range(400)]
        control_all = [f"c{i}/r" for i in range(4000)] + treated_all  # overlap on purpose
        panel = build_panel(
            version=1,
            created_on=DAY,
            treated_candidates=treated_all,
            control_candidates=control_all,
            treated_rate=0.5,
            control_rate=0.05,
            control_source="archive_active:2026-08-25",
        )
        treated = panel.by_cohort(Cohort.TREATED)
        control = panel.by_cohort(Cohort.CONTROL)
        assert treated
        assert control
        assert {m.repo for m in treated}.isdisjoint({m.repo for m in control})
        assert all(m.repo.startswith("t") for m in treated)
        assert [m.repo for m in treated] == sorted((m.repo for m in treated), key=str.lower)
        assert all(m.source == "source_a" for m in treated)
        assert all(m.source == "archive_active:2026-08-25" for m in control)
        assert all(m.sample_key == sample_key(m.repo) for m in panel.members)

    def test_deterministic_regardless_of_input_order(self) -> None:
        a = build_panel(
            version=1,
            created_on=DAY,
            treated_candidates=["b/x", "a/y", "c/z"],
            control_candidates=["z/1", "y/2"],
            treated_rate=1.0,
            control_rate=1.0,
            control_source="s",
        )
        b = build_panel(
            version=1,
            created_on=DAY,
            treated_candidates=["c/z", "a/y", "b/x"],
            control_candidates=["y/2", "z/1"],
            treated_rate=1.0,
            control_rate=1.0,
            control_source="s",
        )
        assert a == b

    def test_case_variants_collapse_to_one_spelling(self) -> None:
        panel = build_panel(
            version=1,
            created_on=DAY,
            treated_candidates=["Owner/Repo", "owner/repo", "OWNER/REPO"],
            control_candidates=["owner/repo"],  # also excluded: it is treated
            treated_rate=1.0,
            control_rate=1.0,
            control_source="s",
        )
        assert panel.repos == ("OWNER/REPO",)

    def test_duplicate_candidates_collapse(self) -> None:
        panel = build_panel(
            version=1,
            created_on=DAY,
            treated_candidates=["a/b", "a/b"],
            control_candidates=[],
            treated_rate=1.0,
            control_rate=1.0,
            control_source="s",
        )
        assert panel.repos == ("a/b",)


class TestPanelModel:
    def _member(self, repo: str, cohort: Cohort = Cohort.TREATED) -> PanelMember:
        return PanelMember(
            repo=repo, cohort=cohort, added_on=DAY, source="s", sample_key=sample_key(repo)
        )

    def test_rejects_duplicate_repos_case_insensitively(self) -> None:
        with pytest.raises(ValidationError, match="more than once"):
            Panel(
                version=1,
                created_on=DAY,
                treated_rate=1.0,
                control_rate=0.0,
                members=(self._member("a/b"), self._member("A/B", Cohort.CONTROL)),
            )

    def test_roundtrips_through_json(self) -> None:
        panel = Panel(
            version=2,
            created_on=DAY,
            treated_rate=0.3,
            control_rate=0.01,
            members=(self._member("a/b"), self._member("c/d", Cohort.CONTROL)),
        )
        assert Panel.model_validate_json(panel.model_dump_json()) == panel
