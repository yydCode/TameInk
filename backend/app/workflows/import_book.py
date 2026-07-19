import json
import os
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from charset_normalizer import from_bytes

from app.domain.errors import (
    ImportAlreadyExistsError,
    ImportChapterBoundaryError,
    ImportEncodingAmbiguousError,
    ImportEncodingUnsupportedError,
)
from app.domain.task import Task, TaskKind, TaskPurpose
from app.repositories.database import DatabaseRepository
from app.repositories.drafts import DraftRepository
from app.repositories.tasks import TasksRepository
from app.repositories.workspace import WorkspaceRepository
from app.workflows.task_service import TaskService

SUPPORTED_ENCODINGS = frozenset({"utf-8", "utf-8-sig", "gb18030"})
_ENCODING_ALIASES = {"utf_8": "utf-8", "utf_8_sig": "utf-8-sig", "gb18030": "gb18030"}
_MARKDOWN_TITLE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
_WEB_TITLE = re.compile(r"^第([0-9]+|[一二三四五六七八九十百千零〇两]+)章(?:[：: \t]+(.*))?$")
_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "两": 2,
}


@dataclass(frozen=True)
class SourceLocation:
    byte: int
    character: int
    line: int
    column: int


@dataclass(frozen=True)
class DecodedImport:
    text: str
    encoding: str


@dataclass(frozen=True)
class ChapterBoundary:
    number: int
    title: str
    start: SourceLocation
    body_start: SourceLocation
    end: SourceLocation


def _source_location(value: object) -> SourceLocation:
    if not isinstance(value, dict):
        raise TypeError("source location must be an object")
    keys = ("byte", "character", "line", "column")
    if set(value) != set(keys) or not all(isinstance(value[key], int) for key in keys):
        raise TypeError("source location fields are invalid")
    return SourceLocation(
        byte=value["byte"],
        character=value["character"],
        line=value["line"],
        column=value["column"],
    )


def decode_import(payload: bytes, encoding: str | None) -> DecodedImport:
    """Decode only a confirmed supported encoding; never replace undecodable bytes."""
    selected = _normalise_encoding(encoding) if encoding is not None else _detect_encoding(payload)
    try:
        return DecodedImport(text=payload.decode(selected, errors="strict"), encoding=selected)
    except UnicodeDecodeError as error:
        raise ImportEncodingAmbiguousError([selected]) from error


def _normalise_encoding(encoding: str) -> str:
    normalized = encoding.lower().replace("-", "_")
    selected = _ENCODING_ALIASES.get(normalized)
    if selected is None or selected not in SUPPORTED_ENCODINGS:
        raise ImportEncodingUnsupportedError(encoding)
    return selected


def _detect_encoding(payload: bytes) -> str:
    if payload.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        pass
    else:
        return "utf-8"
    # A short non-UTF-8 byte sequence has too little evidence to identify GB18030.
    if len(payload) < 32:
        raise ImportEncodingAmbiguousError([])
    matches = list(from_bytes(payload))
    candidates: list[tuple[str, float]] = []
    for match in matches:
        try:
            candidate = _normalise_encoding(str(match.encoding))
        except ImportEncodingUnsupportedError:
            continue
        score = float(match.chaos)
        if (candidate, score) not in candidates:
            candidates.append((candidate, score))
    candidates.sort(key=lambda item: (item[1], item[0]))
    if not candidates:
        raise ImportEncodingAmbiguousError([])
    winner, score = candidates[0]
    close = [name for name, other_score in candidates if other_score - score <= 0.01]
    # For non-UTF-8 input we accept only the unambiguous, low-chaos GB18030 best match.
    if winner != "gb18030" or score > 0.05 or len(close) != 1:
        raise ImportEncodingAmbiguousError([name for name, _ in candidates])
    return winner


def parse_chapters(text: str, encoding: str = "utf-8") -> list[ChapterBoundary]:
    lines = text.splitlines(keepends=True)
    boundaries: list[ChapterBoundary] = []
    byte_offset = 0
    char_offset = 0
    previous_number = 0
    for index, line in enumerate(lines, start=1):
        bare = line.rstrip("\r\n")
        markdown = _MARKDOWN_TITLE.match(bare)
        web = _WEB_TITLE.match(bare)
        if markdown is None and web is None:
            byte_offset += len(line.encode(encoding, errors="strict"))
            char_offset += len(line)
            continue
        location = SourceLocation(byte_offset, char_offset, index, 1)
        if web is not None:
            number = _chapter_number(web.group(1))
            title = (web.group(2) or "").strip()
        else:
            title = markdown.group(2).strip() if markdown is not None else ""
            embedded = _WEB_TITLE.match(title)
            if embedded is None:
                byte_offset += len(line.encode(encoding, errors="strict"))
                char_offset += len(line)
                continue
            number = _chapter_number(embedded.group(1))
            title = (embedded.group(2) or "").strip()
        if number <= previous_number:
            raise ImportChapterBoundaryError("chapter number is duplicated or decreasing", location)
        body_start = SourceLocation(
            byte_offset + len(line.encode(encoding, errors="strict")),
            char_offset + len(line),
            index + 1,
            1,
        )
        boundaries.append(ChapterBoundary(number, title, location, body_start, body_start))
        previous_number = number
        byte_offset += len(line.encode(encoding, errors="strict"))
        char_offset += len(line)
    if not boundaries:
        raise ImportChapterBoundaryError(
            "no deterministic chapter title found", SourceLocation(0, 0, 1, 1)
        )
    resolved: list[ChapterBoundary] = []
    encoded = text.encode(encoding, errors="strict")
    for position, chapter in enumerate(boundaries):
        next_byte = (
            boundaries[position + 1].start.byte if position + 1 < len(boundaries) else len(encoded)
        )
        body = encoded[chapter.body_start.byte : next_byte].decode(encoding, errors="strict")
        if not body.strip():
            raise ImportChapterBoundaryError("chapter has no body", chapter.start)
        end_char = len(encoded[:next_byte].decode(encoding, errors="strict"))
        before_end = encoded[:next_byte].decode(encoding, errors="strict")
        end = SourceLocation(
            next_byte,
            end_char,
            before_end.count("\n") + 1,
            len(before_end.rsplit("\n", 1)[-1]) + 1,
        )
        resolved.append(
            ChapterBoundary(chapter.number, chapter.title, chapter.start, chapter.body_start, end)
        )
    return resolved


def _chapter_number(value: str) -> int:
    if value.isdecimal():
        return int(value)
    result = 0
    current = 0
    for character in value:
        if character in _CHINESE_DIGITS:
            current = _CHINESE_DIGITS[character]
        elif character == "十":
            result += (current or 1) * 10
            current = 0
        elif character == "百":
            result += (current or 1) * 100
            current = 0
        elif character == "千":
            result += (current or 1) * 1000
            current = 0
    return result + current


class ImportBookService:
    def __init__(self, workspace: WorkspaceRepository) -> None:
        self.workspace = workspace

    def upload(
        self, project_id: str, import_id: str, payload: bytes, encoding: str | None
    ) -> tuple[DecodedImport, list[ChapterBoundary]]:
        original = self._original_path(project_id, import_id)
        metadata = self.workspace.resolve_project_path(
            project_id, f".tame-ink/imports/{import_id}.json"
        )
        if metadata.exists():
            raise ImportAlreadyExistsError(import_id)
        if original.exists():
            if original.read_bytes() != payload:
                raise ImportAlreadyExistsError(import_id)
        else:
            self._atomic_write(original, payload)
        decoded = decode_import(payload, encoding)
        self._atomic_write(
            metadata,
            json.dumps(
                {
                    "encoding": decoded.encoding,
                    "sha256": sha256(payload).hexdigest(),
                    "size": len(payload),
                },
                ensure_ascii=False,
            ).encode(),
        )
        return decoded, parse_chapters(decoded.text, decoded.encoding)

    def confirm_boundaries(
        self,
        project_id: str,
        import_id: str,
        source_sha256: str,
        source_size: int,
        boundaries: list[dict[str, object]],
    ) -> tuple[Task, list[ChapterBoundary]]:
        metadata = self.workspace.resolve_project_path(
            project_id, f".tame-ink/imports/{import_id}.json"
        )
        try:
            record = json.loads(metadata.read_text())
            original = self._original_path(project_id, import_id).read_bytes()
            if record["sha256"] != source_sha256 or record["size"] != source_size:
                raise ValueError("import identity does not match")
            if sha256(original).hexdigest() != source_sha256 or len(original) != source_size:
                raise ValueError("stored import bytes do not match")
            encoding = str(record["encoding"])
            decoded = decode_import(original, encoding)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise ImportChapterBoundaryError(
                "import must be uploaded with a confirmed encoding", SourceLocation(0, 0, 1, 1)
            ) from error
        candidates = parse_chapters(decoded.text, decoded.encoding)
        candidate_by_start = {item.start.character: item for item in candidates}
        confirmed: list[ChapterBoundary] = []
        try:
            starts = [_source_location(item["start"]) for item in boundaries]
            ends = [_source_location(item["end"]) for item in boundaries]
            if not boundaries or [item.character for item in starts] != sorted(
                {item.character for item in starts}
            ):
                raise ValueError("chapter starts must be unique and ordered")
            for index, item in enumerate(boundaries):
                candidate = candidate_by_start[starts[index].character]
                expected_end = starts[index + 1] if index + 1 < len(starts) else candidates[-1].end
                if starts[index] != candidate.start or ends[index] != expected_end:
                    raise ValueError("chapter positions are not deterministic boundaries")
                number = item["number"]
                title = item["title"]
                if not isinstance(number, int) or number <= 0:
                    raise ValueError("chapter number must be positive")
                if not isinstance(title, str):
                    raise ValueError("chapter title must be text")
                confirmed.append(
                    ChapterBoundary(
                        number=number,
                        title=title.strip(),
                        start=candidate.start,
                        body_start=candidate.body_start,
                        end=expected_end,
                    )
                )
        except (KeyError, TypeError, ValueError) as error:
            raise ImportChapterBoundaryError(
                "confirmed boundaries are invalid or outside deterministic source positions",
                SourceLocation(0, 0, 1, 1),
            ) from error
        confirmation = self.workspace.resolve_project_path(
            project_id, f".tame-ink/imports/{import_id}-boundaries.json"
        )
        if confirmation.exists():
            raise ImportAlreadyExistsError(import_id)
        self._atomic_write(
            confirmation,
            json.dumps(
                {"sha256": source_sha256, "size": source_size, "boundaries": boundaries}
            ).encode(),
        )
        service = TaskService(TasksRepository(DatabaseRepository(self.workspace), project_id))
        task = service.create(TaskKind.READ, TaskPurpose.IMPORT, subject_id=import_id)
        service.start(task.id)
        analysis = "\n".join(f"{item.number}: {item.title}" for item in confirmed)
        DraftRepository(self.workspace).write(project_id, task.id, "import-analysis.md", analysis)
        return service.await_approval(task.id), confirmed

    def _original_path(self, project_id: str, import_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", import_id):
            raise ImportChapterBoundaryError("import id is invalid", SourceLocation(0, 0, 1, 1))
        return self.workspace.resolve_project_path(project_id, f"imports/originals/{import_id}.bin")

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
