from app.agents.context import ContextManifest
from app.agents.schemas import (
    CommercialReport,
    ContinuityReport,
    DraftWriterResult,
    ReferencedOutput,
    StyleReport,
)


class OutputContractError(RuntimeError):
    pass


def validate_agent_output(
    output: ReferencedOutput,
    manifest: ContextManifest,
) -> ReferencedOutput:
    known_sources = {source.path for source in manifest.sources}
    known_sources.update(snippet.path for snippet in manifest.retrieved)
    if any(reference.path not in known_sources for reference in output.references):
        raise OutputContractError("REFERENCE_SOURCE_UNKNOWN")
    known_evidence: dict[tuple[str, str], list[str]] = {}
    for source in manifest.sources:
        known_evidence.setdefault((source.path, source.location), []).append(source.quote)
    for snippet in manifest.retrieved:
        known_evidence.setdefault((snippet.path, snippet.location), []).append(snippet.quote)
    if any(
        not any(
            reference.quote in evidence
            for evidence in known_evidence.get(
                (reference.path, reference.location), []
            )
        )
        for reference in output.references
    ):
        raise OutputContractError("REFERENCE_EVIDENCE_UNKNOWN")
    return output


def validate_agent_output_tree(
    output: ReferencedOutput,
    manifest: ContextManifest,
) -> ReferencedOutput:
    validate_agent_output(output, manifest)
    children: list[ReferencedOutput] = []
    if isinstance(output, (CommercialReport, ContinuityReport, StyleReport)):
        children.extend(output.issues)
    if isinstance(output, DraftWriterResult):
        children.extend(output.revisions)
    for child in children:
        validate_agent_output(child, manifest)
    return output
