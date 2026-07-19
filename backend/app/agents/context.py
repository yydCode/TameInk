from collections.abc import Callable
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.backend import NovelWorkspaceBackend
from app.domain.errors import WorkspacePathViolationError
from app.domain.paths import validate_formal_path


class StrictContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RetrievedSnippet(StrictContextModel):
    path: str
    location: str
    quote: str
    query: str = ""

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        try:
            validate_formal_path(value)
        except WorkspacePathViolationError as error:
            raise ValueError("CONTEXT_SOURCE_INVALID") from error
        return value

    @field_validator("location", "quote")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CONTEXT_TEXT_EMPTY")
        return value


class ContextIntent(StrictContextModel):
    characters: list[str] = Field(default_factory=list, max_length=12)
    locations: list[str] = Field(default_factory=list, max_length=8)
    abilities: list[str] = Field(default_factory=list, max_length=8)
    foreshadowing: list[str] = Field(default_factory=list, max_length=8)
    keywords: list[str] = Field(min_length=1, max_length=12)

    @field_validator("characters", "locations", "abilities", "foreshadowing", "keywords")
    @classmethod
    def validate_terms(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            term = value.strip()
            if len(term) < 2 or len(term) > 64:
                raise ValueError("CONTEXT_INTENT_TERM_INVALID")
            if term not in normalized:
                normalized.append(term)
        return normalized

    def queries(self) -> list[str]:
        ordered = [
            *self.characters,
            *self.locations,
            *self.abilities,
            *self.foreshadowing,
            *self.keywords,
        ]
        return list(dict.fromkeys(ordered))


class ContextBudget(StrictContextModel):
    max_source_characters: int = Field(default=1200, ge=200, le=10_000)
    max_total_characters: int = Field(default=16_000, ge=1000, le=100_000)
    max_retrieved_snippets: int = Field(default=12, ge=1, le=50)


class ContextRequest(StrictContextModel):
    stage: str
    fixed_rules: list[str]
    volume: list[str]
    summaries: list[str]
    entities: list[str]
    fts_queries: list[str]
    budget: ContextBudget = Field(default_factory=ContextBudget)

    @field_validator("stage")
    @classmethod
    def validate_stage(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CONTEXT_STAGE_EMPTY")
        return value

    @field_validator("fts_queries")
    @classmethod
    def validate_queries(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            query = value.strip()
            if len(query) < 2:
                raise ValueError("CONTEXT_QUERY_INVALID")
            if query not in normalized:
                normalized.append(query)
        return normalized


class ManifestSource(StrictContextModel):
    path: str
    sha256: str
    excerpt: str
    location: str
    quote: str
    category: str = "fixed"
    reason: str = "required by stage policy"

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        try:
            validate_formal_path(value)
        except WorkspacePathViolationError as error:
            raise ValueError("CONTEXT_SOURCE_INVALID") from error
        return value

    @field_validator("sha256")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("CONTEXT_HASH_INVALID")
        return value

    @field_validator("excerpt", "location", "quote")
    @classmethod
    def validate_evidence_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("CONTEXT_EVIDENCE_EMPTY")
        return value


class ContextManifest(StrictContextModel):
    stage: str = "unspecified"
    sources: list[ManifestSource]
    retrieved: list[RetrievedSnippet]
    queries: list[str] = Field(default_factory=list)
    total_characters: int = 0

    @model_validator(mode="after")
    def validate_total(self) -> "ContextManifest":
        observed = sum(len(source.excerpt) for source in self.sources) + sum(
            len(snippet.quote) for snippet in self.retrieved
        )
        if self.total_characters == 0:
            object.__setattr__(self, "total_characters", observed)
        elif self.total_characters != observed:
            raise ValueError("CONTEXT_TOTAL_INVALID")
        return self

    def allowed_paths(self) -> frozenset[str]:
        return frozenset(
            [*(source.path for source in self.sources), *(item.path for item in self.retrieved)]
        )


class TrustedAgentContext(StrictContextModel):
    manifest: ContextManifest


class ContextBuilder:
    def __init__(
        self, backend: NovelWorkspaceBackend, search: Callable[[str], list[RetrievedSnippet]]
    ) -> None:
        self.backend = backend
        self.search = search

    def build(self, request: ContextRequest) -> ContextManifest:
        categorized = [
            ("fixed", request.fixed_rules),
            ("volume", request.volume),
            ("summary", request.summaries),
            ("entity", request.entities),
        ]
        sources: list[ManifestSource] = []
        observed_paths: set[str] = set()
        total_characters = 0
        for category, paths in categorized:
            for path in paths:
                if path in observed_paths:
                    continue
                observed_paths.add(path)
                total_characters = self._append_source(
                    sources, path, category, request.budget, total_characters
                )
        retrieved: list[RetrievedSnippet] = []
        observed_snippets: set[tuple[str, str, str]] = set()
        for query in request.fts_queries:
            for snippet in self.search(query):
                key = (snippet.path, snippet.location, snippet.quote)
                if key in observed_snippets:
                    continue
                if len(retrieved) >= request.budget.max_retrieved_snippets:
                    break
                remaining = request.budget.max_total_characters - total_characters
                if remaining <= 0:
                    raise RuntimeError("CONTEXT_BUDGET_EXCEEDED")
                quote = snippet.quote[:remaining]
                if not quote.strip():
                    raise RuntimeError("CONTEXT_BUDGET_EXCEEDED")
                observed_snippets.add(key)
                retrieved.append(snippet.model_copy(update={"quote": quote, "query": query}))
                total_characters += len(quote)
        return ContextManifest(
            stage=request.stage,
            sources=sources,
            retrieved=retrieved,
            queries=request.fts_queries,
            total_characters=total_characters,
        )

    def _append_source(
        self,
        sources: list[ManifestSource],
        path: str,
        category: str,
        budget: ContextBudget,
        total_characters: int,
    ) -> int:
        try:
            validate_formal_path(path)
        except WorkspacePathViolationError as error:
            raise RuntimeError("CONTEXT_SOURCE_INVALID") from error
        result = self.backend.read(f"/{path}", 0, 1_000_000)
        if result.error is not None or result.file_data is None:
            raise RuntimeError("CONTEXT_SOURCE_MISSING")
        content = result.file_data["content"]
        remaining = budget.max_total_characters - total_characters
        excerpt_length = min(len(content), budget.max_source_characters, remaining)
        if excerpt_length <= 0:
            raise RuntimeError("CONTEXT_BUDGET_EXCEEDED")
        excerpt = content[:excerpt_length]
        sources.append(
            ManifestSource(
                path=path,
                sha256=sha256(content.encode()).hexdigest(),
                excerpt=excerpt,
                location=f"chars:0-{len(excerpt)}",
                quote=excerpt,
                category=category,
                reason=f"selected as {category} context for the current stage",
            )
        )
        return total_characters + len(excerpt)
