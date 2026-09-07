from typing import TypedDict


class WorkflowState(TypedDict):
    course_id: str
    run_id: str
    stage: int
    batch_id: str | None
    chapter_id: str | None
    round_no: int
    artifact_refs: dict[str, str]
    gate_result_refs: list[str]
    pending_review_event_id: str | None
    last_error_code: str | None
