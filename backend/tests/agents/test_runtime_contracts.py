import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from app.agents.context import (
    ContextManifest,
    ManifestSource,
    RetrievedSnippet,
)
from app.agents.contracts import (
    OutputContractError,
    validate_agent_output,
)
from app.agents.runtime import AgentRunner
from app.agents.schemas import StorySetting
from app.agents.subagents import build_subagent_definitions
from app.domain.project import ConfirmedContent
from tests.agents.fake_model import ScriptedTameInkModel
from tests.agents.test_backend import make_backend


def manifest(path: str = "canon/premise.md") -> ContextManifest:
    return ContextManifest(
        sources=[
            ManifestSource(
                path=path,
                sha256="a" * 64,
                excerpt="confirmed",
                location="paragraph 1",
                quote="confirmed quote",
            )
        ],
        retrieved=[RetrievedSnippet(path=path, location="paragraph 1", quote="confirmed quote")],
    )


def output(
    path: str,
    *,
    location: str = "paragraph 1",
    quote: str = "confirmed quote",
) -> StorySetting:
    return StorySetting.model_validate(
        {
            "id": "setting-1",
            "title": "setting",
            "content": "content",
            "references": [{"path": path, "location": location, "quote": quote}],
        }
    )


def test_output_parses_without_context_then_validates_known_sources() -> None:
    parsed = output("canon/premise.md")
    assert validate_agent_output(parsed, manifest()) is parsed
    excerpted = output("canon/premise.md", quote="confirmed")
    assert validate_agent_output(excerpted, manifest()) is excerpted
    with pytest.raises(OutputContractError, match="REFERENCE_SOURCE_UNKNOWN"):
        validate_agent_output(parsed, manifest("canon/outline.md"))
    with pytest.raises(OutputContractError, match="REFERENCE_EVIDENCE_UNKNOWN"):
        validate_agent_output(output("canon/premise.md", quote="FABRICATED"), manifest())
    with pytest.raises(OutputContractError, match="REFERENCE_EVIDENCE_UNKNOWN"):
        validate_agent_output(output("canon/premise.md", location="wrong location"), manifest())


def test_model_schema_omits_system_assigned_references() -> None:
    definition = next(
        item for item in build_subagent_definitions() if item.name == "RetentionAuditor"
    )

    schema = AgentRunner._model_output_schema(definition)

    assert '"references"' not in json.dumps(schema)
    assert "context_reference_paths" in schema["properties"]
    assert "total_score" not in schema["properties"]


def test_direct_runner_attaches_exact_context_references_to_output_tree() -> None:
    runner = object.__new__(AgentRunner)
    runner.manifest = manifest()
    raw = {
        "id": "report-1",
        "issues": [{"id": "issue-1"}],
        "context_reference_paths": ["canon/premise.md"],
    }

    enriched = runner._attach_context_references(raw)

    expected = [
        {
            "path": "canon/premise.md",
            "location": "paragraph 1",
            "quote": "confirmed quote",
        }
    ]
    assert enriched["references"] == expected
    assert enriched["issues"][0]["references"] == expected


def test_direct_runner_computes_commercial_score_from_dimensions() -> None:
    raw = {"dimensions": [{"score": score} for score in (80, 75, 70, 85, 65, 90, 72)]}

    enriched = AgentRunner._attach_commercial_score(raw)

    assert enriched["total_score"] == 77


def test_stage_runner_returns_scoped_structured_output(tmp_path: Path) -> None:
    backend, canon, _, _ = make_backend(tmp_path)
    canon.write_markdown("story-01", "canon/premise.md", ConfirmedContent(markdown="confirmed"))
    skill_root = tmp_path / "skills"
    skill_file = skill_root / "webnovel-architecture" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text(
        "---\nname: webnovel-architecture\ndescription: architecture\n---\nFollow facts.",
        encoding="utf-8",
    )
    runner = object.__new__(AgentRunner)
    runner.skill_root = skill_root
    runner._run_traces = []
    runner.model = ScriptedTameInkModel(
        api_key="test",
        model="scripted",
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "StorySetting",
                        "args": {
                            "id": "setting-1",
                            "title": "设定",
                            "content": "内容",
                            "context_reference_paths": ["canon/premise.md"],
                        },
                        "id": "structured-response",
                    }
                ],
            ),
        ],
    )
    runner.usage_recorder = None
    runner.manifest = manifest()
    definition = next(
        item for item in build_subagent_definitions() if item.name == "StoryArchitect"
    )

    result = runner._invoke_stage(definition, {"instruction": "design"})

    assert isinstance(result, StorySetting)
    assert result.references[0].path == "canon/premise.md"
    assert runner.run_traces()[0]["skill"] == "webnovel-architecture"
    assert runner.run_traces()[0]["source_paths"] == ["canon/premise.md"]
