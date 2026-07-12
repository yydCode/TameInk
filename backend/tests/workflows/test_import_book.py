import pytest

from app.domain.errors import ImportChapterBoundaryError, ImportEncodingAmbiguousError
from app.workflows.import_book import decode_import, parse_chapters


def test_explicit_supported_encoding_decodes_without_replacement() -> None:
    decoded = decode_import("第一章\n正文".encode("gb18030"), "gb18030")

    assert decoded.encoding == "gb18030"
    assert decoded.text == "第一章\n正文"


def test_unknown_or_ambiguous_encoding_requires_user_choice() -> None:
    with pytest.raises(ImportEncodingAmbiguousError) as raised:
        decode_import("第一章 正文 content enough words perhaps this includes text".encode(), None)

    assert raised.value.candidates


def test_parser_accepts_only_markdown_or_chinese_webnovel_titles() -> None:
    chapters = parse_chapters("# 第一章 雨夜\n\n正文甲\n\n第2章\n正文乙\n")

    assert [(chapter.number, chapter.title) for chapter in chapters] == [(1, "雨夜"), (2, "")]
    assert chapters[0].start.byte == 0
    assert chapters[1].start.line == 5


def test_parser_records_original_encoding_byte_offsets() -> None:
    text = "第一章\n正文\n第二章\n正文"

    chapters = parse_chapters(text, encoding="gb18030")

    assert chapters[1].start.byte == len("第一章\n正文\n".encode("gb18030"))


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
