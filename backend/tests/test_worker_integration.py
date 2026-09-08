from uuid import uuid4

from sqlalchemy.orm import sessionmaker

from app.db.checkpoints import postgres_checkpointer
from app.db.models import Run
from app.services.courses import CourseService
from app.services.jobs import JobService
from app.services.models import ModelResult
from app.services.reviews import ReviewService
from app.worker import Worker
from app.workflows.runner import WorkflowRunner


def test_worker_persists_stage_artifact_waits_for_human_then_resumes(settings, db_session) -> None:
    course = CourseService(db_session, settings.courses_root).create(
        "worker-course",
        {
            "title": "Worker Course",
            "audience": "learners",
            "learning_goals": ["verify a durable workflow"],
            "expected_chapter_count": 1,
        },
    )
    run = Run(course_id=course.id, thread_id=str(uuid4()))
    db_session.add(run)
    db_session.flush()
    JobService(db_session).enqueue(run, "start")
    db_session.commit()
    factory = sessionmaker(db_session.bind, expire_on_commit=False)
    worker = Worker(factory, "test-worker", WorkflowRunner(settings).execute)

    assert worker.run_once()
    with postgres_checkpointer(settings) as checkpointer:
        checkpoint = checkpointer.get_tuple(
            {"configurable": {"thread_id": run.thread_id, "checkpoint_ns": "course_generator"}}
        )
        assert checkpoint is not None
        assert checkpoint.checkpoint["channel_values"]["workflow_state"]["stage"] == 1
    with factory.begin() as session:
        persisted = session.get(Run, run.id)
        assert persisted and persisted.status == "waiting_human"
        assert persisted.current_stage == 1
        assert (settings.courses_root / "worker-course" / "workspace" / "INPUT.json").is_file()
        ReviewService(session).decide(persisted, scope="stage", target="stage-1", action="approve")

    assert worker.run_once()
    with factory.begin() as session:
        persisted = session.get(Run, run.id)
        assert persisted and persisted.status == "waiting_human"
        assert persisted.current_stage == 2
        root = settings.courses_root / "worker-course" / "workspace"
        assert (root / "MISSION.md").is_file()
        assert (root / "SPEC.md").is_file()


class ScriptedGateway:
    def __init__(self) -> None:
        self.responses = iter(
            [
                "# Chapter\n\nA useful explanation with an example and exercise.",
                '{"markdown":"# Chapter\\n\\nA clear lesson with an example and exercise.",'
                '"scores":{"naturalness":90,"clarity":90,"conciseness":90,"teaching":90},'
                '"findings":[]}',
                '{"outcomes":{"facts_sources":"pass","goals_scope":"pass",'
                '"teaching":"pass","logic_continuity":"pass"},"findings":[]}',
            ]
        )

    def complete(self, *args, **kwargs) -> ModelResult:
        return ModelResult(next(self.responses), 1, 1, "test-model")


class CountingGateway(ScriptedGateway):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def complete(self, *args, **kwargs) -> ModelResult:
        self.calls += 1
        return super().complete(*args, **kwargs)


class SchemaRepairGateway(ScriptedGateway):
    def __init__(self) -> None:
        self.responses = iter(
            [
                "# Chapter\n\nA useful explanation with an example and exercise.",
                "not valid JSON",
                '{"markdown":"# Chapter\\n\\nA clear lesson with an example and exercise.",'
                '"scores":{"naturalness":90,"clarity":90,"conciseness":90,"teaching":90},'
                '"findings":[]}',
                '{"outcomes":{"facts_sources":"pass","goals_scope":"pass",'
                '"teaching":"pass","logic_continuity":"pass"},"findings":[]}',
            ]
        )
        self.calls = 0

    def complete(self, *args, **kwargs) -> ModelResult:
        self.calls += 1
        return ModelResult(next(self.responses), 1, 1, "test-model")


def test_chapter_cycle_persists_all_three_gate_evidence(settings, db_session) -> None:
    course = CourseService(db_session, settings.courses_root).create(
        "quality-course", {"min_effective_chars_per_chapter": 1}
    )
    run = Run(course_id=course.id, thread_id=str(uuid4()), current_stage=5)
    db_session.add(run)
    db_session.flush()
    runner = WorkflowRunner(settings)
    passed = runner._chapter_quality_cycle(
        db_session,
        course,
        run,
        ScriptedGateway(),
        {"id": "chapter-1", "title": "Chapter", "number": 1},
        uuid4(),
        "lessons/01-quality-course.md",
    )
    assert passed
    evidence = settings.courses_root / "quality-course" / "workspace" / "quality"
    assert (evidence / "chapter-1-round-1.json").is_file()


def test_chapter_cycle_reuses_durable_model_outputs_after_a_retry(settings, db_session) -> None:
    course = CourseService(db_session, settings.courses_root).create(
        "cached-quality-course", {"min_effective_chars_per_chapter": 1}
    )
    run = Run(course_id=course.id, thread_id=str(uuid4()), current_stage=5)
    db_session.add(run)
    db_session.flush()
    runner = WorkflowRunner(settings)
    gateway = CountingGateway()
    chapter = {"id": "chapter-1", "title": "Chapter", "number": 1}
    context_id = uuid4()
    assert runner._chapter_quality_cycle(
        db_session,
        course,
        run,
        gateway,
        chapter,
        context_id,
        "lessons/01-cached-quality-course.md",
    )
    assert gateway.calls == 3
    assert runner._chapter_quality_cycle(
        db_session,
        course,
        run,
        gateway,
        chapter,
        context_id,
        "lessons/01-cached-quality-course.md",
    )
    assert gateway.calls == 3


def test_chapter_cycle_repairs_one_invalid_structured_model_output(settings, db_session) -> None:
    course = CourseService(db_session, settings.courses_root).create(
        "schema-repair-course", {"min_effective_chars_per_chapter": 1}
    )
    run = Run(course_id=course.id, thread_id=str(uuid4()), current_stage=5)
    db_session.add(run)
    db_session.flush()
    gateway = SchemaRepairGateway()
    assert WorkflowRunner(settings)._chapter_quality_cycle(
        db_session,
        course,
        run,
        gateway,
        {"id": "chapter-1", "title": "Chapter", "number": 1},
        uuid4(),
        "lessons/01-schema-repair-course.md",
    )
    assert gateway.calls == 4


def test_stage_three_source_fragments_are_injected_into_stage_five_context_pack(
    settings, db_session, monkeypatch
) -> None:
    course = CourseService(db_session, settings.courses_root).create(
        "source-context-course",
        {
            "title": "来源课程",
            "content_scope": "测试来源传递",
            "expected_chapter_count": 1,
            "min_effective_chars_per_chapter": 1,
            "source_policy": "internal_only",
            "resources": [{"name": "内部笔记", "text": "可追溯的来源证据。"}],
        },
    )
    run = Run(course_id=course.id, thread_id=str(uuid4()), current_stage=3)
    db_session.add(run)
    db_session.flush()
    runner = WorkflowRunner(settings)
    runner._write_blueprint(db_session, course, run)
    run.current_stage = 4
    runner._write_batches(db_session, course, run)
    run.current_stage = 5
    monkeypatch.setattr("app.workflows.runner.ModelGateway", lambda settings: ScriptedGateway())
    assert runner._produce_chapters(db_session, course, run)
    context = runner._workspace_json(course, "workspace/context-packs/batch-01/chapter-01.json")
    assert context["source_fragments"][0]["text"] == "可追溯的来源证据。"


def test_batch_plan_has_parseable_context_scope_and_course_quality_detects_missing_lessons(
    settings, db_session
) -> None:
    course = CourseService(db_session, settings.courses_root).create(
        "plan-course", {"expected_chapter_count": 2, "min_effective_chars_per_chapter": 10}
    )
    run = Run(course_id=course.id, thread_id=str(uuid4()), current_stage=4)
    db_session.add(run)
    db_session.flush()
    runner = WorkflowRunner(settings)
    runner._write_batches(db_session, course, run)
    batch = runner._workspace_json(course, "workspace/batches/batch-01.json")
    assert batch["execution"] == "sequential"
    assert batch["context_pack_scope"][0]["blueprint_ref"].startswith("workspace/BLUEPRINT.md#")
    assert not list(
        (settings.courses_root / "plan-course" / "workspace" / "context-packs").rglob("*.json")
    )
    run.current_stage = 6
    assert runner._write_course_quality(db_session, course, run)
    repair_plan = settings.courses_root / "plan-course" / "workspace" / "course-repair-plan.json"
    assert repair_plan.is_file()


def test_worker_builds_then_publishes_final_release_after_human_event(settings, db_session) -> None:
    course = CourseService(db_session, settings.courses_root).create("release-worker", {})
    lessons = settings.courses_root / "release-worker" / "lessons"
    (lessons / "01-intro.md").write_text("# Intro\n\nBody", encoding="utf-8")
    run = Run(course_id=course.id, thread_id=str(uuid4()), current_stage=7)
    db_session.add(run)
    db_session.flush()
    JobService(db_session).enqueue(run, "start")
    db_session.commit()
    factory = sessionmaker(db_session.bind, expire_on_commit=False)
    worker = Worker(factory, "test-worker", WorkflowRunner(settings).execute)

    assert worker.run_once()
    with factory.begin() as session:
        persisted = session.get(Run, run.id)
        assert persisted and persisted.status == "waiting_human"
        ReviewService(session).decide(persisted, scope="release", target="r0001", action="approve")
    assert worker.run_once()
    with factory.begin() as session:
        persisted = session.get(Run, run.id)
        assert persisted and persisted.status == "completed"


def test_worker_completes_all_seven_stages_with_human_approvals(
    settings, db_session, monkeypatch
) -> None:
    course = CourseService(db_session, settings.courses_root).create(
        "full-worker",
        {
            "title": "Full Worker Course",
            "audience": "learners",
            "learning_goals": ["complete a durable course run"],
            "expected_chapter_count": 1,
            "min_effective_chars_per_chapter": 1,
        },
    )
    run = Run(course_id=course.id, thread_id=str(uuid4()))
    db_session.add(run)
    db_session.flush()
    JobService(db_session).enqueue(run, "start")
    db_session.commit()
    settings.openai_api_key = "test-key"
    monkeypatch.setattr("app.workflows.runner.ModelGateway", lambda settings: ScriptedGateway())
    factory = sessionmaker(db_session.bind, expire_on_commit=False)
    worker = Worker(factory, "full-worker-test", WorkflowRunner(settings).execute)

    for expected_stage in range(1, 7):
        assert worker.run_once()
        with factory.begin() as session:
            persisted = session.get(Run, run.id)
            assert persisted and persisted.status == "waiting_human"
            assert persisted.current_stage == expected_stage
            ReviewService(session).decide(
                persisted,
                scope="stage",
                target=f"stage-{expected_stage}",
                action="approve",
            )

    assert worker.run_once()
    with factory.begin() as session:
        persisted = session.get(Run, run.id)
        assert persisted and persisted.status == "waiting_human"
        assert persisted.current_stage == 7
        assert (settings.releases_root / "full-worker" / "r0001" / "release.json").is_file()
        ReviewService(session).decide(persisted, scope="release", target="r0001", action="approve")

    assert worker.run_once()
    with factory.begin() as session:
        persisted = session.get(Run, run.id)
        assert persisted and persisted.status == "completed"
