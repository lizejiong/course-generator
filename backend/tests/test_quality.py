from app.services.quality import (
    Finding,
    deterministic_gate,
    effective_characters,
    language_gate,
    route_quality,
    semantic_gate,
)


def test_effective_characters_uses_markdown_ast_and_excludes_sources_urls_and_code() -> None:
    markdown = """# \u6807\u9898

> \u5f15\u7528\u6587\u5b57 123

\u53ef\u89c1 [\u94fe\u63a5\u6807\u7b7e](https://example.test/ignored)

```python
ignored_code = 4
```

## \u672c\u7ae0\u6765\u6e90

- [\u4e0d\u8ba1\u5165](https://example.test/source)
"""
    visible = "\u6807\u9898\u5f15\u7528\u6587\u5b57123\u53ef\u89c1\u94fe\u63a5\u6807\u7b7e"
    assert effective_characters(markdown) == len(visible)


def test_deterministic_gate_requires_title_and_minimum_visible_content() -> None:
    result = deterministic_gate("\u6b63\u6587", revision=1, minimum=3)
    assert not result.passed
    assert {finding.rule for finding in result.findings} == {
        "chapter_title",
        "minimum_effective_characters",
    }


def test_language_gate_requires_each_dimension_average_and_no_blockers() -> None:
    scores = {"naturalness": 90, "clarity": 90, "conciseness": 90, "teaching": 84}
    assert not language_gate("# \u7ae0", 1, scores, []).passed
    blocker = Finding("prompt_residue", "line:1", "contains prompt", "prompt")
    assert not language_gate("# \u7ae0", 1, {key: 90 for key in scores}, [blocker]).passed


def test_semantic_blocker_and_repeated_or_third_quality_failure_route_to_human() -> None:
    finding = Finding("unsupported_fact", "line:3", "missing source", "claim")
    semantic = semantic_gate(
        "# \u7ae0",
        2,
        {
            "facts_sources": "blocker",
            "goals_scope": "pass",
            "teaching": "pass",
            "logic_continuity": "pass",
        },
        [finding],
    )
    deterministic = deterministic_gate("# \u7ae0\n\u6b63\u6587", 2, 1)
    assert route_quality([deterministic, semantic], 1, []) == "rework"
    assert route_quality([deterministic, semantic], 2, [finding.fingerprint]) == "waiting_human"
    assert route_quality([deterministic, semantic], 3, []) == "waiting_human"
