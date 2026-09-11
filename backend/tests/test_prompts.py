from app.prompts import render_prompt


def test_prompt_content_and_generic_skill_are_versioned_from_repository_files() -> None:
    prompt = render_prompt(
        "chapter_writer",
        skill="instructional-writer",
        title="Testing",
        context_content='{"chapter_id":"chapter-1"}',
        repair_evidence="none",
    )
    assert "Testing" in prompt.content
    assert "course_id" not in prompt.content.lower()
    assert prompt.skill_name == "instructional-writer"
    assert prompt.skill_hash is not None
    assert len(prompt.skill_hash) == 64
