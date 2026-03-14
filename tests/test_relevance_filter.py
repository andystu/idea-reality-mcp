"""Tests for filter_by_core_concept in scoring engine."""

from idea_reality_mcp.scoring.engine import filter_by_core_concept


def test_filter_keeps_relevant():
    items = [{"name": "sketch-app", "description": "a drawing tool for artists"}]
    result = filter_by_core_concept(items, "drawing")
    assert len(result) == 1
    assert result[0]["name"] == "sketch-app"


def test_filter_removes_irrelevant():
    items = [{"name": "calculator", "description": "math utility"}]
    result = filter_by_core_concept(items, "drawing")
    assert len(result) == 0


def test_filter_empty_core_concept():
    items = [
        {"name": "a", "description": "foo"},
        {"name": "b", "description": "bar"},
    ]
    result = filter_by_core_concept(items, "")
    assert len(result) == 2


def test_filter_case_insensitive():
    items = [{"name": "app", "description": "Drawing canvas"}]
    result = filter_by_core_concept(items, "drawing")
    assert len(result) == 1


def test_filter_hyphenated_concept():
    items = [
        {"name": "tool", "description": "assisted sketching"},
        {"name": "other", "description": "drawing pad"},
    ]
    # "AI-assisted drawing" splits to [ai, assisted, drawing]
    # "ai" is a stop word → effective words: [assisted, drawing]
    result = filter_by_core_concept(items, "AI-assisted drawing")
    assert len(result) == 2


def test_real_scenario():
    items = [
        {"name": "drawbot", "detail": "AI drawing tool", "description": ""},
        {"name": "pixnano", "detail": "pixel editor nano banana", "description": ""},
    ]
    result = filter_by_core_concept(items, "AI-assisted drawing")
    assert len(result) == 1
    assert result[0]["name"] == "drawbot"
