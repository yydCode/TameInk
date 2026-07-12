from pathlib import Path

import pytest

from app.agents.context import ContextBuilder, ContextRequest, RetrievedSnippet
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
            fixed_rules=["canon/premise.md"],
            volume=["canon/volumes/volume-1.md"],
            summaries=["memory/summaries/book.md"],
            entities=["canon/characters/hero.md"],
            fts_queries=["hero clue"],
        )
    )

    assert [source.path for source in manifest.sources] == list(sources)
    assert all(len(source.sha256) == 64 and source.excerpt for source in manifest.sources)
    assert queried == ["hero clue"]
    assert manifest.retrieved[0].path == "canon/premise.md"


def test_context_missing_explicit_source_fails_without_glob_fallback(tmp_path: Path) -> None:
    backend, _, _, _ = make_backend(tmp_path)
    builder = ContextBuilder(backend, lambda _: [])
    request = ContextRequest(
        fixed_rules=["canon/premise.md"],
        volume=[],
        summaries=[],
        entities=[],
        fts_queries=[],
    )
    with pytest.raises(RuntimeError, match="CONTEXT_SOURCE_MISSING"):
        builder.build(request)
