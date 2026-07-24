from app.agents.subagents import build_subagent_definitions

EXPECTED_NAMES = {
    "MarketStrategist",
    "StoryArchitect",
    "OutlineArchitect",
    "ChapterPlanner",
    "DraftWriter",
    "ContinuityAuditor",
    "StyleCritic",
    "RetentionAuditor",
    "MemoryCurator",
    "ImportAnalyst",
}


def test_ten_subagents_have_independent_contracts() -> None:
    definitions = build_subagent_definitions()

    assert {definition.name for definition in definitions} == EXPECTED_NAMES
    assert len({definition.system_prompt for definition in definitions}) == 10
    assert all(definition.output_schema is not None for definition in definitions)
