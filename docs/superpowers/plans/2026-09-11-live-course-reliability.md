# 真实课程链路可靠性修复实施计划

> **给执行 Agent：** 必须使用 `superpowers:executing-plans` 按任务逐项执行；每完成一个任务均运行对应测试并提交。

**目标：** 让 OpenAI 兼容模型（含 DeepSeek）能够完成第一门课程，同时使数据库初始化、结构化模型输出、Worker 停止/租约恢复和阶段六 warning 确认具备可验证的可靠行为。

**架构：** 保持既有 FastAPI、PostgreSQL、独立同步 Worker 与七阶段 LangGraph 工作流。模型输出兼容在 `WorkflowRunner` 边界规范化；停止与任务租约由 `JobService` 以数据库状态为准；前端只复用现有 review API，不新增后端产品能力。

**技术栈：** Python 3.12、FastAPI、SQLAlchemy、Alembic、PostgreSQL、pytest；React、TypeScript、TanStack Query、Vitest。

---

### 任务 1：修复 Context Pack 注入与 DeepSeek 语义 JSON 兼容

**文件：**
- 修改：`backend/app/workflows/runner.py`
- 修改：`backend/app/prompts/chapter_writer.md`
- 修改：`backend/app/prompts/semantic_reviewer.md`
- 修改：`backend/app/prompts/schema_repair.md`
- 修改：`backend/tests/test_worker_integration.py`
- 修改：`backend/tests/test_prompts.py`

- [ ] **步骤 1：编写失败测试，证明写作提示词包含 Context Pack 正文，且扁平语义结果会被规范化。**

在 `test_worker_integration.py` 新增一个 Gateway，保存每次 `complete(..., prompt=...)` 的 prompt；用 `source_fragments=[{"text": "可追溯的来源证据"}]` 运行 `_produce_chapters`，断言首个 prompt 包含该文本。再以以下真实兼容格式运行 `_semantic_payload`：

```python
payload = runner._semantic_payload(
    '{"facts_sources":"pass","goals_scope":"pass",'
    '"teaching":"pass","logic_continuity":"pass","findings":[]}'
)
assert payload["outcomes"]["teaching"] == "pass"
```

- [ ] **步骤 2：运行测试并确认失败。**

运行：`uv run pytest backend/tests/test_worker_integration.py backend/tests/test_prompts.py -q`

预期：Context Pack 正文不在写作 prompt 中；扁平 JSON 因缺少 `outcomes` 失败。

- [ ] **步骤 3：实现最小的输入和输出规范化。**

在 `WorkflowRunner._produce_chapters` 中，读取刚创建的 Context Pack：

```python
context_content = Path(context.storage_path).read_text(encoding="utf-8")
```

把 `context_content=context_content` 传入 `_chapter_quality_cycle`，并继续传给 `render_prompt("chapter_writer", ...)`。在 `chapter_writer.md` 中将 `{context_id}` 替换为 `{context_content}`，明确“以下 JSON 是唯一可用证据，禁止声称缺少 Context Pack”。

在 `_semantic_payload` 中，将四个顶级键都存在的 payload 规范化为：

```python
if "outcomes" not in payload:
    payload = {
        "outcomes": {name: payload[name] for name in required},
        "findings": payload.get("findings", []),
    }
```

保留对嵌套格式的支持；任一必需键缺失、结果值不在 `pass/warning/blocker` 时抛出 `ValueError`。

将 `semantic_reviewer.md` 改为明确对象示例：

```json
{"outcomes":{"facts_sources":"pass","goals_scope":"pass","teaching":"pass","logic_continuity":"pass"},"findings":[]}
```

将 `schema_repair.md` 改为要求“保留原任务但只返回满足原任务中 JSON 示例的对象”，避免只复述模糊描述。

- [ ] **步骤 4：运行测试并确认通过。**

运行：`uv run pytest backend/tests/test_worker_integration.py backend/tests/test_prompts.py backend/tests/test_quality.py -q`

预期：全部通过，且 Gateway 捕获的写作 prompt 包含来源正文。

- [ ] **步骤 5：提交。**

```bash
git add backend/app/workflows/runner.py backend/app/prompts backend/tests/test_worker_integration.py backend/tests/test_prompts.py
git commit -m "fix: make model chapter generation provider-compatible"
```

### 任务 2：将可预期模型结构错误从基础设施重试中隔离

**文件：**
- 修改：`backend/app/workflows/runner.py`
- 修改：`backend/app/worker.py`
- 修改：`backend/app/services/jobs.py`
- 修改：`backend/tests/test_worker_integration.py`
- 修改：`backend/tests/test_jobs.py`

- [ ] **步骤 1：编写失败测试，证明重复结构化响应无效时运行失败但不会创建重试 Job。**

在测试中令 Gateway 对 schema repair 连续返回 `{"unexpected": true}`；执行一次 Worker，并断言：

```python
assert persisted.status == "failed"
assert persisted.error_code == "model_output_invalid"
assert session.query(Job).filter_by(run_id=run.id).count() == 1
```

- [ ] **步骤 2：运行测试并确认失败。**

运行：`uv run pytest backend/tests/test_worker_integration.py::test_invalid_model_schema_does_not_retry -q`

预期：当前实现把 `KeyError` 归类为 `worker_exception`，并创建 retry Job。

- [ ] **步骤 3：实现业务错误分类。**

在 `runner.py` 定义 `ModelOutputInvalid(ValueError)`；在 `_humanizer_payload`、`_semantic_payload` 和二次 schema repair 无法解析时抛出该异常。让 `Worker.run_once` 单独捕获该异常，调用新增的：

```python
def fail_business(self, job: Job, code: str, summary: str) -> None:
    job.status = "failed"
    job.error_code = code
    job.error_summary = summary
    job.lease_owner = None
    job.lease_expires_at = None
    job.finished_at = datetime.now(UTC)
    run = self.session.get(Run, job.run_id)
    if run:
        run.status = "failed"
        run.error_code = code
        run.error_summary = summary
```

仅网络/Worker 未预期异常继续走 `fail_infrastructure`。

- [ ] **步骤 4：运行测试并确认通过。**

运行：`uv run pytest backend/tests/test_jobs.py backend/tests/test_worker_integration.py -q`

预期：无效模型输出只产生一个 failed Job；现有临时基础设施重试测试仍通过。

- [ ] **步骤 5：提交。**

```bash
git add backend/app/workflows/runner.py backend/app/worker.py backend/app/services/jobs.py backend/tests/test_jobs.py backend/tests/test_worker_integration.py
git commit -m "fix: avoid retrying invalid model output"
```

### 任务 3：保证迁移、停止与 Worker 崩溃恢复可靠

**文件：**
- 修改：`backend/alembic/versions/0001_initial_business_tables.py`
- 新建：`backend/alembic/versions/0002_verify_business_schema.py`
- 修改：`backend/app/services/jobs.py`
- 修改：`backend/app/worker.py`
- 修改：`backend/tests/test_jobs.py`
- 修改：`backend/tests/test_postgres_integration.py`
- 修改：`README.md`

- [ ] **步骤 1：编写失败测试，证明过期租约会被重新领取，停止请求不会被 Worker 的旧 ORM 实例覆盖。**

创建 `status="running"`、`lease_expires_at=datetime.now(UTC)-timedelta(seconds=1)` 的 Job，断言 `claim` 返回该 Job 并将 `attempts` 加一。再用两个独立 Session：Session A 读取 Job/Run；Session B 设置 `stop_requested=True` 并提交；Session A 执行结束前调用 `session.refresh(run)`，断言状态最终为 `stopped`。

- [ ] **步骤 2：运行测试并确认失败。**

运行：`uv run pytest backend/tests/test_jobs.py backend/tests/test_postgres_integration.py -q`

预期：停止竞争测试失败，因为 Worker 使用了开始执行时的旧 `Run` 实例。

- [ ] **步骤 3：实现租约和停止状态的权威读取。**

保留 `JobService.claim` 对过期 `running` Job 的领取条件，并在领取前清除前任 `lease_owner` 的语义通过新 owner 覆盖。`Worker.run_once` 在 `self.execute(job)` 返回后使用：

```python
session.expire(run)
session.refresh(run)
```

再根据刷新后的 `run.stop_requested` / `run.pause_requested` 决定最终状态；不写回标志位为 `False`。

新增迁移 `0002_verify_business_schema.py`：使用 `inspect(op.get_bind()).get_table_names()` 检查 `courses`、`runs`、`jobs`、`artifacts`、`review_events`；缺表时以 `Base.metadata.create_all(bind=bind)` 补齐，保证旧的 `0001` 标记但业务表缺失时执行 `upgrade head` 会恢复。`0001` 保持历史兼容，不修改已发布 revision。

README 的启动步骤改为 `uv run alembic upgrade head` 后执行 `GET /health` 与 `GET /api/courses`，并说明 Worker 使用 `PYTHONPATH=backend` 的跨平台命令。

- [ ] **步骤 4：运行迁移和集成测试。**

运行：`uv run pytest backend/tests/test_jobs.py backend/tests/test_postgres_integration.py backend/tests/test_worker_integration.py -q`

预期：全部通过。随后对本地开发库运行 `uv run alembic upgrade head`，再运行：`Invoke-RestMethod http://127.0.0.1:8000/api/courses`；预期 HTTP 200。

- [ ] **步骤 5：提交。**

```bash
git add backend/alembic backend/app/services/jobs.py backend/app/worker.py backend/tests/test_jobs.py backend/tests/test_postgres_integration.py README.md
git commit -m "fix: harden worker recovery and database bootstrap"
```

### 任务 4：在前端暴露阶段六 warning 确认

**文件：**
- 修改：`frontend/src/api.ts`
- 修改：`frontend/src/App.tsx`
- 修改：`frontend/src/api.test.ts`
- 新建：`frontend/src/review.ts`
- 新建：`frontend/src/review.test.ts`

- [ ] **步骤 1：编写失败测试，证明前端能构造 warning acknowledgement。**

在 `review.test.ts` 编写：

```ts
import { acknowledgementDecision } from "./review";
expect(acknowledgementDecision(["warning-a", "warning-b"])).toEqual({
  scope: "stage", target: "stage-6", action: "acknowledge",
  evidence: { warning_fingerprints: ["warning-a", "warning-b"] },
});
```

- [ ] **步骤 2：运行测试并确认失败。**

运行：`pnpm.cmd --dir frontend test --run`

预期：找不到 `./review`。

- [ ] **步骤 3：实现最小前端确认入口。**

新建 `review.ts` 并导出：

```ts
export const acknowledgementDecision = (warning_fingerprints: string[]) => ({
  scope: "stage", target: "stage-6", action: "acknowledge",
  evidence: { warning_fingerprints },
});
```

在 `api.ts` 新增 `getFile(courseId, path)`，读取 `workspace/quality.json`。在 Workbench 中仅当 `stage === 6 && status === "waiting_human"` 时读取质量报告；为 `unresolved_warnings` 每项显示 fingerprint、message 与复选框。仅将勾选项传给 `postReview(runId, acknowledgementDecision(selected))`，确认成功后刷新 run 与质量报告；在仍存在未确认 warning 时禁用“批准并继续”。保留 blocker 时的“要求返工”入口。

- [ ] **步骤 4：运行前端检查。**

运行：`pnpm.cmd --dir frontend test --run; pnpm.cmd --dir frontend build`

预期：测试、TypeScript 与 Vite 构建均通过。

- [ ] **步骤 5：提交。**

```bash
git add frontend/src
git commit -m "feat: acknowledge stage six quality warnings"
```

### 任务 5：真实外部服务回归验收与交付

**文件：**
- 修改：`outputs/external-service-manual-acceptance.md`
- 修改：`README.md`

- [ ] **步骤 1：启动干净的本地服务。**

运行：`docker compose up -d postgres`、`uv run alembic upgrade head`、`$env:PYTHONPATH='backend'; Start-Process .venv\Scripts\python.exe -ArgumentList '-m','app.worker_main'`，以及 `pnpm.cmd --dir frontend dev --host 127.0.0.1 --port 5173`。

- [ ] **步骤 2：执行自动回归。**

运行：`uv run pytest backend/tests -q` 与 `pnpm.cmd --dir frontend test --run; pnpm.cmd --dir frontend build`。

预期：全部通过。

- [ ] **步骤 3：执行真实模型验收。**

用 UI 创建单章最小课程，逐阶段批准；阶段五核对提示词使用 Context Pack，阶段六如出现 warning 则确认，阶段七发布 `r0001`。记录 run ID、token 使用量、release 状态，不记录任何密钥或模型原文。

- [ ] **步骤 4：更新验收文档。**

在 `outputs/external-service-manual-acceptance.md` 添加本次日期、模型兼容验证结果、已验证七阶段路径与失败时的 `model_output_invalid` 行为；README 只保留稳定的运行说明与链接。

- [ ] **步骤 5：提交并推送。**

```bash
git add README.md outputs/external-service-manual-acceptance.md
git commit -m "docs: record live model acceptance"
git push origin main
```

## 自检

- 覆盖：任务 1 覆盖 Context Pack 与模型结构；任务 2 覆盖费用安全；任务 3 覆盖启动、停止与崩溃恢复；任务 4 覆盖 warning 审核；任务 5 覆盖真实验收与交付。
- 无占位项：每项包含文件、测试、实现或命令。
- 一致性：前端 acknowledgement 使用后端既有 `ReviewDecision` 的 `scope="stage"`、`target="stage-6"` 与 `warning_fingerprints` 字段；未增加 API 枚举。
