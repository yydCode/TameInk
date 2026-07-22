"""测试反复词汇检测模块。"""

from app.utils.vocabulary import detect_repetitive_vocabulary


def test_detects_ai_cliche_phrases() -> None:
    text = """
    他看到这一幕，心头一震，不由得后退一步。
    "你……"他低声说道，心中一凛。
    这时候，她嘴角微扬，淡淡地说："不必惊讶。"
    他心头一震，再次不由得感叹。
    """
    issues = detect_repetitive_vocabulary(text)
    cliches = [i for i in issues if i.category == "cliche"]
    assert len(cliches) >= 2  # "心头一震"和"不由得"各出现2次，会被检出
    phrases = {i.phrase for i in cliches}
    assert "心头一震" in phrases
    assert "不由得" in phrases


def test_detects_high_frequency_ngrams() -> None:
    text = "主角快速前进，快速攻击，快速躲闪，快速回防。" * 5  # "快速"重复 20 次
    text += "正常描写内容" * 100  # 稀释
    issues = detect_repetitive_vocabulary(text)
    repetitive = [i for i in issues if i.category == "repetitive" and "快速" in i.phrase]
    assert len(repetitive) >= 1


def test_returns_empty_for_clean_text() -> None:
    text = """
    主角走进房间，观察四周。桌上放着一封信，他拿起来仔细阅读。
    信中提到明天的会面地点。他思考片刻，决定按时赴约。
    """
    issues = detect_repetitive_vocabulary(text)
    assert len(issues) == 0


def test_handles_markdown_syntax() -> None:
    text = """
    ## 第一章

    **主角**看到这一幕，*心头一震*。他不由得后退。

    > 引用块内容

    他心头一震，[链接文本](url)。
    """
    issues = detect_repetitive_vocabulary(text)
    cliches = [i for i in issues if i.category == "cliche"]
    # 即使有 markdown 语法，也能检出"心头一震"出现 2 次
    assert any("心头一震" in i.phrase for i in cliches)


def test_ignores_empty_or_non_chinese_text() -> None:
    assert detect_repetitive_vocabulary("") == []
    assert detect_repetitive_vocabulary("   \n\n  ") == []
    assert detect_repetitive_vocabulary("English text only") == []


def test_per_thousand_normalization() -> None:
    # 短文本（100 字）中"不由得"出现 2 次 → 每千字 20 次
    text = "不由得" * 2 + "其他内容" * 23  # 约 100 字
    issues = detect_repetitive_vocabulary(text)
    issue = next((i for i in issues if "不由得" in i.phrase), None)
    assert issue is not None
    assert issue.per_thousand >= 10.0  # 归一化后应该很高
