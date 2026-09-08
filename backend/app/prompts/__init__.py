"""Versioned, repository-local prompt and Skill loader."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class RenderedPrompt:
    name: str
    content: str
    content_hash: str
    skill_name: str | None
    skill_hash: str | None


_PROMPTS = {
    "chapter_writer": "chapter_writer.md",
    "natural_language_editor": "natural_language_editor.md",
    "semantic_reviewer": "semantic_reviewer.md",
    "schema_repair": "schema_repair.md",
}
_PROMPT_ROOT = Path(__file__).parent
_REPOSITORY_ROOT = _PROMPT_ROOT.parents[2]


def render_prompt(name: str, /, *, skill: str | None = None, **values: object) -> RenderedPrompt:
    """Render a checked-in prompt; only generic Skill text may be injected."""
    try:
        template = (_PROMPT_ROOT / _PROMPTS[name]).read_text(encoding="utf-8")
    except KeyError as error:
        raise ValueError(f"unknown prompt: {name}") from error
    skill_text = ""
    skill_hash = None
    if skill:
        skill_text = (_REPOSITORY_ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        skill_hash = sha256(skill_text.encode()).hexdigest()
    content = template.format(skill_instruction=skill_text, **values)
    return RenderedPrompt(
        name=name,
        content=content,
        content_hash=sha256(template.encode()).hexdigest(),
        skill_name=skill,
        skill_hash=skill_hash,
    )
