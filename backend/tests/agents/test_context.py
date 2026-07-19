from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents.context import (
    ContextBudget,
    ContextBuilder,
    ContextIntent,
    ContextRequest,
    ManifestSource,
    RetrievedSnippet,
)
from app.domain.project import ConfirmedContent
from tests.agents.test_backend import make_backend


def test_context_reads_exact_manifest_and_records_hashes(tmp_path: Path) -> None:
    backend, canon, _, _ = make_backend(tmp_path)
    sources = {
        "canon/premise.md": "rules",
        "canon/volumes/volume-1.md": "volume",
        "memory/summaries/book.md": "summary",
        "canon/characters/hero.md": "hero",
    }
    for path, content in sources.items():
        canon.write_markdown("story-01", path, ConfirmedContent(markdown=content))
    queried: list[str] = []

    def search(query: str) -> list[RetrievedSnippet]:
        queried.append(query)
        return [RetrievedSnippet(path="canon/premise.md", location="paragraph 1", quote="rules")]

    manifest = ContextBuilder(backend, search).build(
        ContextRequest(
            stage="DraftWriter",
            fixed_rules=["canon/premise.md"],
            volume=["canon/volumes/volume-1.md"],
            summaries=["memory/summaries/book.md"],
            entities=["canon/characters/hero.md"],
            fts_queries=["hero clue"],
        )
    )

    assert [source.path for source in manifest.sources] == list(sources)
    assert all(len(source.sha256) == 64 and source.excerpt for source in manifest.sources)
    assert all(source.location.startswith("chars:0-") for source in manifest.sources)
    assert [source.quote for source in manifest.sources] == list(sources.values())
    assert queried == ["hero clue"]
    assert manifest.retrieved[0].path == "canon/premise.md"


def test_context_missing_explicit_source_fails_without_glob_fallback(tmp_path: Path) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    builder = ContextBuilder(backend, lambda _: [])
    request = ContextRequest(
        stage="ChapterPlanner",
        fixed_rules=["canon/premise.md"],
        volume=[],
        summaries=[],
        entities=[],
        fts_queries=[],
    )
    with pytest.raises(RuntimeError, match="CONTEXT_SOURCE_MISSING"):
        builder.build(request)


def test_context_intent_deduplicates_terms_and_rejects_short_queries() -> None:
    intent = ContextIntent(
        characters=["林默", "林默"],
        locations=[],
        abilities=[],
        foreshadowing=[],
        keywords=["雨夜线索"],
    )

    assert intent.characters == ["林默"]
    assert intent.queries() == ["林默", "雨夜线索"]
    with pytest.raises(ValidationError):
        ContextIntent(keywords=["雨"])


def test_context_budget_limits_each_source_and_total(tmp_path: Path) -> None:
    backend, canon, _, _ = make_backend(tmp_path)
    canon.write_markdown("story-01", "canon/premise.md", ConfirmedContent(markdown="甲" * 500))
    canon.write_markdown("story-01", "canon/outline.md", ConfirmedContent(markdown="乙" * 500))
    request = ContextRequest(
        stage="DraftWriter",
        fixed_rules=["canon/premise.md", "canon/outline.md"],
        volume=[],
        summaries=[],
        entities=[],
        fts_queries=[],
        budget=ContextBudget(max_source_characters=200, max_total_characters=1000),
    )

    manifest = ContextBuilder(backend, lambda _: []).build(request)

    assert [len(source.excerpt) for source in manifest.sources] == [200, 200]
    assert manifest.total_characters == 400


@pytest.mark.parametrize(
    "overrides",
    [
        {"path": "../canon/premise.md"},
        {"sha256": "0" * 63},
        {"sha256": "g" * 64},
        {"excerpt": " "},
        {"location": ""},
        {"quote": ""},
    ],
)
def test_manifest_source_rejects_invalid_evidence(overrides: dict[str, str]) -> None:
    payload = {
        "path": "canon/premise.md",
        "sha256": "a" * 64,
        "excerpt": "confirmed",
        "location": "full document",
        "quote": "confirmed",
        **overrides,
    }
    with pytest.raises(ValidationError):
        ManifestSource.model_validate(payload)
