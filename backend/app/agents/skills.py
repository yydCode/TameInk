"""Skill registry: loads P0 skill definitions from on-disk skill.yaml files.

Each P0 skill lives at  <repo-root>/skills/<skill-name>/skill.yaml  and carries:

  name            – must match one of the P0Skill Literal values
  agent           – the subagent responsible (null for meta-skills like webnovel-studio)
  candidate_kinds – list of ArtifactKind strings the skill may produce
  purpose         – one-line description used in agent routing
  <extra keys>    – arbitrary generation/diagnostic constraints (stored in .constraints)

The P0Skill Literal is kept as a static regression guard: a startup assertion
verifies that the on-disk names exactly match the Literal set, so the two can
never silently drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, get_args

import yaml

from app.domain.creation import ArtifactKind

# ---------------------------------------------------------------------------
# Public type alias – kept as Literal for Pydantic validation at API/schema
# boundaries. The YAML loader verifies on-disk names match this set at import.
# ---------------------------------------------------------------------------
P0Skill = Literal[
    "webnovel-studio",
    "webnovel-research-genre",
    "webnovel-design-reader-contract",
    "webnovel-design-story-engine",
    "webnovel-plan-rolling-story",
    "webnovel-plan-chapter",
    "webnovel-draft",
    "webnovel-audit",
    "webnovel-opening-audit",
    "webnovel-poison-check",
    "webnovel-curate-memory",
    "webnovel-plan-ending",
]

# Ordered tuple of valid P0Skill names (preserves original declaration order)
_P0_SKILL_NAMES: tuple[str, ...] = get_args(P0Skill)
_P0_SKILL_SET: frozenset[str] = frozenset(_P0_SKILL_NAMES)

# Valid ArtifactKind values for candidate_kinds validation
_VALID_ARTIFACT_KINDS: frozenset[str] = frozenset(get_args(ArtifactKind))

# On-disk skills root: <repo-root>/skills/
_SKILLS_ROOT = Path(__file__).resolve().parents[3] / "skills"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class P0SkillDefinition:
    name: P0Skill
    agent: str | None
    candidate_kinds: frozenset[ArtifactKind]
    purpose: str
    # Arbitrary generation / diagnostic constraints loaded from skill.yaml.
    # Consumers may read these to inject platform rules into agent context.
    constraints: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

_RESERVED_KEYS = frozenset({"name", "agent", "candidate_kinds", "purpose"})


def _load_p0_skills() -> tuple[P0SkillDefinition, ...]:
    """Read skill.yaml for every P0 skill and return an ordered tuple.

    Validation rules
    ----------------
    - Every P0Skill name must have a corresponding skill.yaml on disk.
    - skill.yaml names must be a subset of P0Skill (extra on-disk skills are
      ignored; they belong to the legacy agent namespace).
    - candidate_kinds must only contain valid ArtifactKind values.
    - Raises RuntimeError at import time if any constraint is violated so the
      server refuses to start with a broken skill configuration.
    """
    by_name: dict[str, P0SkillDefinition] = {}

    for skill_dir in _SKILLS_ROOT.iterdir():
        yaml_path = skill_dir / "skill.yaml"
        if not yaml_path.exists():
            continue

        try:
            data: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise RuntimeError(f"Invalid YAML in {yaml_path}: {exc}") from exc

        name: str = str(data.get("name", ""))
        if name not in _P0_SKILL_SET:
            # Legacy or unknown skill – skip silently
            continue

        raw_kinds: list[str] = data.get("candidate_kinds") or []
        invalid_kinds = frozenset(raw_kinds) - _VALID_ARTIFACT_KINDS
        if invalid_kinds:
            raise RuntimeError(
                f"skill.yaml for '{name}' has unrecognised candidate_kinds: {invalid_kinds}"
            )

        constraints = {k: v for k, v in data.items() if k not in _RESERVED_KEYS}

        by_name[name] = P0SkillDefinition(
            name=name,  # type: ignore[arg-type]  # validated against Literal set above
            agent=data.get("agent") or None,
            candidate_kinds=frozenset(raw_kinds),  # type: ignore[arg-type]
            purpose=str(data.get("purpose", "")),
            constraints=constraints,
        )

    # All P0 skills must be present on disk
    missing = _P0_SKILL_SET - by_name.keys()
    if missing:
        raise RuntimeError(
            f"Missing skill.yaml for P0 skills: {sorted(missing)}\n"
            f"Expected files under: {_SKILLS_ROOT}"
        )

    # Return in the canonical declaration order (preserves original P0_SKILLS order)
    return tuple(by_name[name] for name in _P0_SKILL_NAMES)


# ---------------------------------------------------------------------------
# Module-level registry – loaded once at import time
# ---------------------------------------------------------------------------

P0_SKILLS: tuple[P0SkillDefinition, ...] = _load_p0_skills()

_BY_NAME: dict[str, P0SkillDefinition] = {d.name: d for d in P0_SKILLS}


# ---------------------------------------------------------------------------
# Public helpers (interface unchanged from original)
# ---------------------------------------------------------------------------


def skill_definition(name: P0Skill) -> P0SkillDefinition:
    return _BY_NAME[name]


def is_candidate_kind_allowed(skill: P0Skill, kind: ArtifactKind) -> bool:
    return kind in skill_definition(skill).candidate_kinds


# ---------------------------------------------------------------------------
# Generation-constraint renderer
#
# Converts the structured constraints loaded from skill.yaml into a compact
# block of Chinese directives suitable for injection into an agent system
# prompt. Returns "" when the skill declares no generation constraints, so
# callers can concatenate unconditionally.
# ---------------------------------------------------------------------------

_FORBIDDEN_LABELS: dict[str, str] = {
    "protagonist_causes_team_failure": "主角失误导致队伍陷入危机",
    "protagonist_passive_throughout": "主角茫然无措、全程无有效反应",
    "gain_less_than_cost": "主角主动行为得不偿失（收益低于代价）",
    "protagonist_only_flees_no_counterattack": "被打压后只逃跑、不反击",
}


def render_generation_directives(skill: str) -> str:
    """Render skill.yaml constraints into Chinese prompt directives.

    Handles all constraint blocks defined in skill.yaml:
    - generation_constraints, protagonist_rules, hook_rules, scene_validity
      (DraftWriter / ChapterPlanner)
    - scene_constraints (ChapterPlanner)
    - story_card_template (StoryEditor planning)
    - diagnostic_checks (ContinuityAuditor / audit agents)

    Accepts any skill name; returns "" for legacy or unknown skills.
    """
    if skill not in _P0_SKILL_SET:
        return ""
    constraints = _BY_NAME[skill].constraints  # validated against _P0_SKILL_SET above
    lines: list[str] = []

    gc = constraints.get("generation_constraints")
    if isinstance(gc, dict):
        if isinstance(gc.get("word_range"), list) and len(gc["word_range"]) == 2:
            lo, hi = gc["word_range"]
            lines.append(f"全章字数控制在 {lo}-{hi} 字。")
        if isinstance(gc.get("scene_word_range"), list) and len(gc["scene_word_range"]) == 2:
            lo, hi = gc["scene_word_range"]
            lines.append(f"单个场景 {lo}-{hi} 字。")
        if gc.get("max_paragraph_words"):
            lines.append(f"单段描写不超过 {gc['max_paragraph_words']} 字，超过读者会跳读。")
        if gc.get("emotion_beats_per_1000"):
            lines.append(f"每千字至少 {gc['emotion_beats_per_1000']} 个情绪起伏点。")
        if gc.get("telescope_exposures"):
            lines.append(
                f"每个爽点在兑现前至少分 {gc['telescope_exposures']} 次向读者暴露终点信息"
                "（递望远镜），不要藏着不让读者猜。"
            )

    pr = constraints.get("protagonist_rules")
    if isinstance(pr, dict):
        if pr.get("must_act_in_setback"):
            lines.append("情绪下行时主角必须有主动行为，哪怕是有计划的主动撤退。")
        if pr.get("setback_cause") == "external_only":
            lines.append("情绪下行的起因只能是外部敌人或客观困难，绝不能是主角失误。")
        forbidden = pr.get("forbidden")
        if isinstance(forbidden, list) and forbidden:
            labels = [_FORBIDDEN_LABELS.get(item) or item for item in forbidden]
            lines.append("绝对禁止：" + "；".join(labels) + "。")

    hr = constraints.get("hook_rules")
    if isinstance(hr, dict):
        if hr.get("near_expectation_max_chapters"):
            lines.append(
                f"近期待开启后 {hr['near_expectation_max_chapters']} 章内必须有进展或回收。"
            )
        if hr.get("same_type_hook_consecutive_limit"):
            lines.append(
                f"同类型钩子连续使用不超过 {hr['same_type_hook_consecutive_limit']} 次，"
                "否则读者审美疲劳。"
            )

    sv = constraints.get("scene_validity")
    if isinstance(sv, dict):
        if sv.get("require_hook_or_payoff"):
            lines.append("每个场景必须是抛钩或收钩，两者都不是的场景删掉。")
        if sv.get("emotion_must_bind_expectation"):
            lines.append("情绪描写必须绑定期待：下行用于开钩，上行用于收钩。")

    # ── scene_constraints (ChapterPlanner) ──────────────────────────────
    sc = constraints.get("scene_constraints")
    if isinstance(sc, dict):
        if isinstance(sc.get("scene_word_range"), list) and len(sc["scene_word_range"]) == 2:
            lo, hi = sc["scene_word_range"]
            lines.append(f"单个场景 {lo}-{hi} 字。")
        if sc.get("require_hook_or_payoff"):
            lines.append("每个场景必须有抛钩或收钩，两者都不是则删除该场景。")

    # ── story_card_template (StoryEditor planning) ───────────────────────
    sct = constraints.get("story_card_template")
    if isinstance(sct, dict):
        steps = sct.get("steps") or []
        if steps:
            step_labels: list[str] = []
            for step in steps:
                label = str(step.get("label") or step.get("id") or "")
                constraint = step.get("constraint")
                required: list[str] = step.get("required") or []
                note = ""
                if constraint:
                    note += f"【{constraint}】"
                if required:
                    note += f"【必含：{'/'.join(str(r) for r in required)}】"
                step_labels.append(f"{label}{note}")
            lines.append("故事卡必须按以下七步构思：" + " → ".join(step_labels) + "。")

    # ── diagnostic_checks (ContinuityAuditor / audit agents) ─────────────
    dc = constraints.get("diagnostic_checks")
    if isinstance(dc, list) and dc:
        error_checks = [c for c in dc if isinstance(c, dict) and c.get("severity") == "error"]
        warning_checks = [c for c in dc if isinstance(c, dict) and c.get("severity") == "warning"]
        info_checks = [c for c in dc if isinstance(c, dict) and c.get("severity") == "info"]
        if error_checks:
            labels = [str(c.get("label") or c.get("id") or "") for c in error_checks]
            lines.append("以下问题为【错误级】，发现即必须报告：" + "；".join(labels) + "。")
        if warning_checks:
            labels = [str(c.get("label") or c.get("id") or "") for c in warning_checks]
            lines.append("以下问题为【警告级】，有证据时报告：" + "；".join(labels) + "。")
        if info_checks:
            labels = [str(c.get("label") or c.get("id") or "") for c in info_checks]
            lines.append("以下问题为【信息级】，可酌情提示：" + "；".join(labels) + "。")

    # ── poison_checklist (PoisonCheckAuditor) ────────────────────────────
    pc = constraints.get("poison_checklist")
    if isinstance(pc, list) and pc:
        error_poisons = [c for c in pc if isinstance(c, dict) and c.get("severity") == "error"]
        warning_poisons = [c for c in pc if isinstance(c, dict) and c.get("severity") == "warning"]
        if error_poisons:
            labels = [str(c.get("label") or c.get("id") or "") for c in error_poisons]
            lines.append("以下为【致命毒点】，有证据必须报告：" + "；".join(labels) + "。")
        if warning_poisons:
            labels = [str(c.get("label") or c.get("id") or "") for c in warning_poisons]
            lines.append("以下为【警告毒点】，有明确证据时报告：" + "；".join(labels) + "。")

    if not lines:
        return ""
    numbered = "".join(f"（{i}）{line}" for i, line in enumerate(lines, start=1))
    return "必须遵守以下番茄平台创作规则：" + numbered
