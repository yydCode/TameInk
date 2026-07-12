from pathlib import Path

import pytest

from app.domain.errors import (
    ImportAlreadyExistsError,
    ImportChapterBoundaryError,
    ImportEncodingAmbiguousError,
)
from app.repositories.workspace import WorkspaceRepository
from app.workflows.import_book import ImportBookService, decode_import, parse_chapters


def test_explicit_supported_encoding_decodes_without_replacement() -> None:
    decoded = decode_import("第一章\n正文".encode("gb18030"), "gb18030")

    assert decoded.encoding == "gb18030"
    assert decoded.text == "第一章\n正文"


@pytest.mark.parametrize("encoding", ["utf-8", "gb18030"])
def test_detects_real_long_chinese_utf8_and_gb18030_payloads(encoding: str) -> None:
    payload = ("第一章 风雨如晦，主角在长街寻找失踪的人。" * 30).encode(encoding)

    decoded = decode_import(payload, None)

    assert decoded.encoding == encoding


def test_detects_utf8_bom_before_charset_normalizer() -> None:
    decoded = decode_import("第一章\n正文".encode("utf-8-sig"), None)

    assert decoded.encoding == "utf-8-sig"


def test_unknown_or_ambiguous_encoding_requires_user_choice() -> None:
    with pytest.raises(ImportEncodingAmbiguousError) as raised:
        decode_import(b"\x81", None)

    assert raised.value.code == "IMPORT_ENCODING_AMBIGUOUS"


def test_parser_accepts_only_markdown_or_chinese_webnovel_titles() -> None:
    chapters = parse_chapters("# 第一章 雨夜\n\n正文甲\n\n第2章\n正文乙\n")

    assert [(chapter.number, chapter.title) for chapter in chapters] == [(1, "雨夜"), (2, "")]
    assert chapters[0].start.byte == 0
    assert chapters[1].start.line == 5


def test_parser_records_original_encoding_byte_offsets() -> None:
    text = "第一章\n正文\n第二章\n正文"

    chapters = parse_chapters(text, encoding="gb18030")

    assert chapters[1].start.byte == len("第一章\n正文\n".encode("gb18030"))


def test_unnumbered_markdown_is_not_guessed_as_a_chapter() -> None:
    with pytest.raises(ImportChapterBoundaryError):
        parse_chapters("# 前言\n\n背景说明")


def test_import_original_cannot_be_overwritten(tmp_path: Path) -> None:
    workspace = WorkspaceRepository(tmp_path)
    workspace.create_project("story-01")
    service = ImportBookService(workspace)
    original = "第一章\n正文".encode()
    service.upload("story-01", "source-01", original, "utf-8")

    with pytest.raises(ImportAlreadyExistsError):
        service.upload("story-01", "source-01", b"changed", "utf-8")

    assert (
        workspace.project_path("story-01") / "imports/originals/source-01.bin"
    ).read_bytes() == original


@pytest.mark.parametrize(
    "text",
    [
        "没有标题的正文",
        "第一章\n\n第二章\n正文",
        "第二章\n正文\n第一章\n正文",
        "第一章\n",
    ],
)
def test_parser_rejects_missing_or_invalid_boundaries_with_location(text: str) -> None:
    with pytest.raises(ImportChapterBoundaryError) as raised:
        parse_chapters(text)

    assert raised.value.location.line >= 1
