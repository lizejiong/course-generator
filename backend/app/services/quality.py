import hashlib
from dataclasses import asdict, dataclass, field
from typing import Literal

from markdown_it import MarkdownIt

Outcome = Literal["pass", "warning", "blocker"]


@dataclass(frozen=True)
class Finding:
    rule: str
    location: str
    message: str
    excerpt: str = ""
    fix: str = ""

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.rule}\0{self.location}\0{self.excerpt}".encode()).hexdigest()


@dataclass(frozen=True)
class GateResult:
    gate: str
    content_hash: str
    revision: int
    passed: bool
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, int | float | str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {**asdict(self), "findings": [asdict(finding) for finding in self.findings]}


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode()).hexdigest()


def effective_characters(markdown: str) -> int:
    tokens = MarkdownIt("commonmark").parse(markdown)
    body: list[str] = []
    in_sources = False
    for token in tokens:
        if token.type == "heading_open" and token.tag == "h2":
            in_sources = False
        if (
            token.type == "inline"
            and token.content.strip() == "\u672c\u7ae0\u6765\u6e90"
            and token.map
        ):
            in_sources = True
            continue
        elif token.type == "inline" and token.content.strip() == "本章来源" and token.map:
            in_sources = True
            continue
        if not in_sources and token.type == "inline" and token.map:
            body.extend(child.content for child in token.children or [] if child.type == "text")
    return sum(character.isalnum() for character in "".join(body))


def deterministic_gate(markdown: str, revision: int, minimum: int) -> GateResult:
    findings: list[Finding] = []
    count = effective_characters(markdown)
    if count < minimum:
        findings.append(Finding("minimum_effective_characters", "document", f"{count} < {minimum}"))
    if "# " not in markdown:
        findings.append(Finding("chapter_title", "document", "missing level-one title"))
    return GateResult(
        "deterministic",
        content_hash(markdown),
        revision,
        not findings,
        findings,
        {"effective_chars": count},
    )


def language_gate(
    markdown: str, revision: int, scores: dict[str, int], findings: list[Finding]
) -> GateResult:
    required = ("naturalness", "clarity", "conciseness", "teaching")
    missing = [key for key in required if key not in scores]
    average = sum(scores.values()) / len(required) if not missing else 0
    passed = (
        not missing
        and all(scores[key] >= 85 for key in required)
        and average >= 90
        and not findings
    )
    return GateResult(
        "language",
        content_hash(markdown),
        revision,
        passed,
        findings,
        {**scores, "average": average},
    )


def semantic_gate(
    markdown: str, revision: int, outcomes: dict[str, Outcome], findings: list[Finding]
) -> GateResult:
    required = {"facts_sources", "goals_scope", "teaching", "logic_continuity"}
    passed = required == outcomes.keys() and "blocker" not in outcomes.values()
    return GateResult("semantic", content_hash(markdown), revision, passed, findings, outcomes)


def route_quality(results: list[GateResult], round_no: int, prior_fingerprints: list[str]) -> str:
    blockers = [finding.fingerprint for result in results for finding in result.findings]
    if all(result.passed for result in results):
        return "pass"
    if any(fingerprint in prior_fingerprints for fingerprint in blockers) or round_no >= 3:
        return "waiting_human"
    return "rework"
