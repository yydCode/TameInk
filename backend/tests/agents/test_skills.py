"""Regression tests for the YAML-driven skill registry.

These tests verify that:
1. All P0 skills load from disk without errors.
2. The on-disk skill set matches the P0Skill Literal exactly (drift guard).
3. Each loaded definition has the same name/agent/candidate_kinds as the
   original hardcoded values – so refactoring doesn't silently lose data.
4. Extra constraints (Baojian rules) round-trip correctly.
5. is_candidate_kind_allowed and skill_definition keep their original behaviour.
"""

from __future__ import annotations

import typing

import pytest

from app.agents.skills import (
    P0_SKILLS,
    P0Skill,
    P0SkillDefinition,
    is_candidate_kind_allowed,
    render_generation_directives,
    skill_definition,
)
from app.domain.creation import ArtifactKind

# ---------------------------------------------------------------------------
# Expected values mirroring the original hardcoded P0_SKILLS tuple.
# This acts as the regression guard: if a skill.yaml changes name/agent/kinds
# in a way that breaks downstream consumers, this test fails first.
# ---------------------------------------------------------------------------
_EXPECTED: list[dict] = [
    {
        "name": "webnovel-studio",
        "agent": None,
        "candidate_kinds": frozenset(),
    },
    {
        "name": "webnovel-research-genre",
        "agent": "Researcher",
        "candidate_kinds": frozenset({"evidence_finding"}),
    },
    {
        "name": "webnovel-design-reader-contract",
        "agent": "StoryEditor",
        "candidate_kinds": frozenset({"reader_contract"}),
    },
    {
        "name": "webnovel-design-story-engine",
        "agent": "StoryEditor",
        "candidate_kinds": frozenset({"story_engine", "character_state"}),
    },
    {
        "name": "webnovel-plan-rolling-story",
        "agent": "StoryEditor",
        "candidate_kinds": frozenset({"story_card", "expectation"}),
    },
    {
        "name": "webnovel-plan-chapter",
        "agent": "ChapterPlanner",
        "candidate_kinds": frozenset({"chapter_plan"}),
    },
    {
        "name": "webnovel-draft",
        "agent": "DraftWriter",
        "candidate_kinds": frozenset({"chapter_draft"}),
    },
    {
        "name": "webnovel-audit",
        "agent": "ContinuityAuditor",
        "candidate_kinds": frozenset({"evidence_finding"}),
    },
    {
        "name": "webnovel-opening-audit",
        "agent": "OpeningAuditor",
        "candidate_kinds": frozenset({"evidence_finding"}),
    },
    {
        "name": "webnovel-poison-check",
        "agent": "PoisonCheckAuditor",
        "candidate_kinds": frozenset({"evidence_finding"}),
    },
    {
        "name": "webnovel-curate-memory",
        "agent": "MemoryCurator",
        "candidate_kinds": frozenset(
            {"memory_proposal", "actual_event", "character_state", "expectation"}
        ),
    },
    {
        "name": "webnovel-plan-ending",
        "agent": "StoryEditor",
        "candidate_kinds": frozenset({"ending_plan"}),
    },
]


class TestSkillRegistryLoads:
    def test_loads_all_p0_skills(self) -> None:
        """All 12 P0 skills must be present after YAML load."""
        assert len(P0_SKILLS) == 12

    def test_all_definitions_are_p0_skill_definition(self) -> None:
        for defn in P0_SKILLS:
            assert isinstance(defn, P0SkillDefinition)

    def test_on_disk_names_match_literal_exactly(self) -> None:
        """Drift guard: loaded names must equal P0Skill Literal args exactly."""
        loaded_names = {d.name for d in P0_SKILLS}
        literal_names = set(typing.get_args(P0Skill))
        assert loaded_names == literal_names, (
            f"On-disk skill names diverge from P0Skill Literal.\n"
            f"  Extra on disk : {loaded_names - literal_names}\n"
            f"  Missing on disk: {literal_names - loaded_names}"
        )

    def test_declaration_order_preserved(self) -> None:
        """Skills must appear in the same order as declared in P0Skill."""
        expected_order = list(typing.get_args(P0Skill))
        loaded_order = [d.name for d in P0_SKILLS]
        assert loaded_order == expected_order


class TestSkillDefinitionValues:
    """Each skill's name/agent/candidate_kinds must match the original hardcoded values."""

    @pytest.mark.parametrize("expected", _EXPECTED, ids=[e["name"] for e in _EXPECTED])
    def test_matches_original_hardcoded_values(self, expected: dict) -> None:
        defn = skill_definition(expected["name"])  # type: ignore[arg-type]
        assert defn.name == expected["name"]
        assert defn.agent == expected["agent"]
        assert defn.candidate_kinds == expected["candidate_kinds"]

    def test_all_have_non_empty_purpose(self) -> None:
        for defn in P0_SKILLS:
            assert defn.purpose, f"skill '{defn.name}' has empty purpose"

    def test_studio_has_no_agent_and_empty_kinds(self) -> None:
        studio = skill_definition("webnovel-studio")
        assert studio.agent is None
        assert studio.candidate_kinds == frozenset()


class TestBaojianConstraintsLoaded:
    """Skills with Baojian rules must expose them in .constraints."""

    def test_draft_has_generation_constraints(self) -> None:
        defn = skill_definition("webnovel-draft")
        assert "generation_constraints" in defn.constraints
        gc = defn.constraints["generation_constraints"]
        assert gc["max_paragraph_words"] == 100
        assert gc["telescope_exposures"] == 3
        assert gc["word_range"] == [2000, 3500]

    def test_draft_has_protagonist_rules(self) -> None:
        defn = skill_definition("webnovel-draft")
        pr = defn.constraints["protagonist_rules"]
        assert pr["must_act_in_setback"] is True
        assert pr["setback_cause"] == "external_only"
        assert "protagonist_causes_team_failure" in pr["forbidden"]

    def test_draft_has_hook_rules(self) -> None:
        defn = skill_definition("webnovel-draft")
        hr = defn.constraints["hook_rules"]
        assert hr["near_expectation_max_chapters"] == 5
        assert hr["remote_expectation_resurface"] is True

    def test_audit_has_diagnostic_checks(self) -> None:
        defn = skill_definition("webnovel-audit")
        checks = defn.constraints["diagnostic_checks"]
        check_ids = {c["id"] for c in checks}
        assert "passive_protagonist_in_setback" in check_ids
        assert "stale_near_expectation" in check_ids
        assert "paragraph_too_long" in check_ids
        assert "character_inconsistency" in check_ids

    def test_plan_rolling_story_has_seven_step_template(self) -> None:
        defn = skill_definition("webnovel-plan-rolling-story")
        template = defn.constraints["story_card_template"]
        step_ids = [s["id"] for s in template["steps"]]
        assert len(step_ids) == 7
        assert step_ids[0] == "opening_anchor"
        assert step_ids[-1] == "next_cycle_seed"

    def test_skills_without_constraints_have_empty_dict(self) -> None:
        for name in ("webnovel-research-genre", "webnovel-design-reader-contract",
                     "webnovel-plan-ending", "webnovel-curate-memory"):
            defn = skill_definition(name)  # type: ignore[arg-type]
            assert defn.constraints == {}, (
                f"'{name}' should have no constraints but got: {defn.constraints}"
            )


class TestPublicHelpers:
    """skill_definition and is_candidate_kind_allowed must behave as before."""

    def test_skill_definition_returns_correct_definition(self) -> None:
        defn = skill_definition("webnovel-draft")
        assert defn.name == "webnovel-draft"
        assert defn.agent == "DraftWriter"

    def test_is_candidate_kind_allowed_true(self) -> None:
        assert is_candidate_kind_allowed("webnovel-draft", "chapter_draft") is True

    def test_is_candidate_kind_allowed_false(self) -> None:
        assert is_candidate_kind_allowed("webnovel-draft", "story_card") is False

    def test_studio_allows_no_candidate_kinds(self) -> None:
        for kind in typing.get_args(ArtifactKind):
            assert is_candidate_kind_allowed("webnovel-studio", kind) is False  # type: ignore[arg-type]

    def test_curate_memory_allows_multiple_kinds(self) -> None:
        for kind in ("memory_proposal", "actual_event", "character_state", "expectation"):
            assert is_candidate_kind_allowed("webnovel-curate-memory", kind) is True  # type: ignore[arg-type]


class TestNewConstraintRenderers:
    """Verify the three new constraint blocks added in Phase 2."""

    def test_audit_renders_error_and_warning_diagnostic_checks(self) -> None:
        result = render_generation_directives("webnovel-audit")
        assert "错误级" in result
        assert "警告级" in result
        assert "主角被动下行" in result   # error check label
        assert "段落过长" in result       # warning check label

    def test_audit_result_contains_all_six_check_severities(self) -> None:
        defn = skill_definition("webnovel-audit")
        checks = defn.constraints["diagnostic_checks"]
        errors = [c for c in checks if c["severity"] == "error"]
        warnings = [c for c in checks if c["severity"] == "warning"]
        assert len(errors) >= 2, "expect at least 2 error-level checks"
        assert len(warnings) >= 2, "expect at least 2 warning-level checks"

    def test_plan_rolling_story_renders_seven_step_template(self) -> None:
        result = render_generation_directives("webnovel-plan-rolling-story")
        assert "七步构思" in result
        assert "开局定位" in result
        assert "反派出场" in result
        assert "接续下一循环" in result

    def test_plan_chapter_renders_scene_constraints(self) -> None:
        result = render_generation_directives("webnovel-plan-chapter")
        assert "场景" in result          # scene_word_range or require_hook_or_payoff
        assert result != ""

    def test_skills_without_new_blocks_return_empty(self) -> None:
        # webnovel-studio has no constraints at all
        assert render_generation_directives("webnovel-studio") == ""

    def test_webnovel_research_genre_has_no_directives(self) -> None:
        assert render_generation_directives("webnovel-research-genre") == ""

    def test_opening_audit_has_18_element_checklist(self) -> None:
        defn = skill_definition("webnovel-opening-audit")
        checklist = defn.constraints["opening_audit_checklist"]
        assert len(checklist) == 18, "opening audit must have exactly 18 elements"
        # Every element needs id, category, label, severity
        for item in checklist:
            assert {"id", "category", "label", "severity"} <= item.keys()
        # At least the known error-level premises are present
        ids = {item["id"] for item in checklist}
        assert "hero_starts_adventure" in ids
        assert "unfair_harm" in ids
        assert "turn_by_golden_finger" in ids
