from collections.abc import Callable
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, field_validator

from app.agents.backend import NovelWorkspaceBackend
from app.domain.errors import WorkspacePathViolationError
from app.domain.paths import validate_formal_path


class StrictContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RetrievedSnippet(StrictContextModel):
    path: str
    location: str
    quote: str

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


class ContextRequest(StrictContextModel):
    fixed_rules: list[str]
    volume: list[str]
    summaries: list[str]
    entities: list[str]
    fts_queries: list[str]


class ManifestSource(StrictContextModel):
    path: str
    sha256: str
    excerpt: str
    location: str
    quote: str

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
    sources: list[ManifestSource]
    retrieved: list[RetrievedSnippet]


class TrustedAgentContext(StrictContextModel):
    manifest: ContextManifest


class ContextBuilder:
    def __init__(
        self, backend: NovelWorkspaceBackend, search: Callable[[str], list[RetrievedSnippet]]
    ) -> None:
        self.backend = backend
        self.search = search

    def build(self, request: ContextRequest) -> ContextManifest:
        ordered = request.fixed_rules + request.volume + request.summaries + request.entities
        sources: list[ManifestSource] = []
        for path in ordered:
            try:
                validate_formal_path(path)
            except WorkspacePathViolationError as error:
                raise RuntimeError("CONTEXT_SOURCE_INVALID") from error
            result = self.backend.read(f"/{path}", 0, 1_000_000)
            if result.error is not None or result.file_data is None:
                raise RuntimeError("CONTEXT_SOURCE_MISSING")
            content = result.file_data["content"]
            excerpt = content[:1000]
            sources.append(
                ManifestSource(
                    path=path,
                    sha256=sha256(content.encode()).hexdigest(),
                    excerpt=excerpt,
                    location="full document",
                    quote=excerpt,
                )
            )
        retrieved: list[RetrievedSnippet] = []
        for query in request.fts_queries:
            if not query.strip():
                raise RuntimeError("CONTEXT_QUERY_EMPTY")
            retrieved.extend(self.search(query))
        return ContextManifest(sources=sources, retrieved=retrieved)
