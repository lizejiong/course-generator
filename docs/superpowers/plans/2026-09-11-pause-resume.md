# 暂停恢复与预算调整实施计划

> **给 agentic workers：** 必须使用 `superpowers:executing-plans` 按任务逐项执行，并在每项完成后提交。
**目标：** 让已暂停的课程运行可以通过现有工作台安全恢复；若是 Token 预算暂停，用户可在恢复时仅提高该运行的预算。

**架构：** 在 `POST /api/runs/{run_id}/actions` 上增加稳定的 `resume` 动作；服务端只允许恢复 `paused` 运行，并在预算不足时要求新预算严格大于当前使用量。恢复会清除暂停与预算错误、将运行重新排队，并交给现有 Worker/LangGraph checkpoint 从当前阶段继续。前端把暂停请求状态、错误和恢复表单呈现在运行面板。

**技术栈：** FastAPI、SQLAlchemy、PostgreSQL jobs、React、TanStack Query、pytest、Vitest。

---

### 任务 1：为恢复动作定义后端契约和测试

**文件：**
- 修改：`backend/app/schemas/api.py`
- 修改：`backend/app/api/router.py`
- 测试：`backend/tests/test_api.py`

- [ ] **步骤 1：添加失败测试**

```python
def test_resume_paused_run_requeues_job_and_can_raise_budget(client, db_session, run):
    run.status = "paused"
    run.pause_requested = True
    run.token_usage = 100
    db_session.commit()
    response = client.post(
        f"/api/runs/{run.id}/actions",
        json={"scope": "run", "target": "current", "action": "resume", "token_limit": 200},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["token_limit"] == 200
```

- [ ] **步骤 2：运行失败测试**

Run: `uv run pytest backend/tests/test_api.py -q --basetemp=work/pytest-pause-resume`

Expected: `422`，因为当前路由只接受 `pause` 和 `stop`。

- [ ] **步骤 3：实现最小契约**

```python
class RunAction(BaseModel):
    scope: str
    target: str
    action: str
    token_limit: int | None = Field(default=None, ge=1)
```

将路由参数改为 `RunAction`；`resume` 分支校验 `run.status == "paused"`、`token_limit is None or token_limit > run.token_usage`，清除 `pause_requested`、`error_code`、`error_summary`，更新可选预算，设 `run.status = "queued"` 并通过 `JobService(db).enqueue(run, "resume")` 入队。

- [ ] **步骤 4：运行测试并提交**

Run: `uv run pytest backend/tests/test_api.py -q --basetemp=work/pytest-pause-resume`

Expected: all passed.

Commit: `git commit -am "feat: resume paused course runs"`

### 任务 2：将恢复能力接入工作台

**文件：**
- 修改：`frontend/src/api.ts`
- 修改：`frontend/src/App.tsx`
- 测试：`frontend/src/api.test.ts`

- [ ] **步骤 1：添加客户端测试**

```ts
it("posts a resume action with an optional higher token limit", async () => {
  await postAction("run-1", "resume", 200);
  expect(fetch).toHaveBeenCalledWith(
    "/api/runs/run-1/actions",
    expect.objectContaining({ body: JSON.stringify({ action: "resume", scope: "run", target: "current", token_limit: 200 }) }),
  );
});
```

- [ ] **步骤 2：实现 UI**

将 `postAction` 的动作联合类型扩展为 `pause | stop | resume`，并添加 `tokenLimit?: number`。当 `run.status === "paused"` 时在审查面板显示“恢复运行”；若 `error_code === "token_budget_pause"`，显示大于当前 Token 使用量的数字输入与说明。恢复成功后使 `run`、`artifacts` 与 `releases` 查询失效。暂停和停止请求失败时也显示同一错误组件。

- [ ] **步骤 3：运行前端验证并提交**

Run: `pnpm.cmd --dir frontend test -- --run; pnpm.cmd --dir frontend build`

Expected: tests pass and Vite build succeeds.

Commit: `git commit -am "feat: resume paused runs from workbench"`

### 任务 3：补齐阶段一默认产物并做端到端复验

**文件：**
- 修改：`frontend/src/App.tsx`
- 测试：`frontend/src/stages.test.ts`

- [ ] **步骤 1：修复默认路径**

将 `initialFile` 的第 1 阶段映射从 `workspace/INPUT.json` 改为 `course.json`，使阶段一打开时展示实际归档产物；其他阶段保持原有映射。

- [ ] **步骤 2：运行定向验证**

Run: `pnpm.cmd --dir frontend test -- --run; pnpm.cmd --dir frontend build`

Expected: tests pass and no TypeScript errors.

- [ ] **步骤 3：浏览器验收**

在当前暂停运行的工作台输入 `50000` 恢复预算并点击“恢复运行”；核对状态变为 `queued/running`，Worker 继续到阶段五或后续人工审核。然后完成审批、发布和阅读器检查。

- [ ] **步骤 4：合并、推送和保留验收页面**

Run: `git merge --no-ff fix/pause-resume`; `git push origin main`

Expected: main 包含恢复能力，浏览器保留课程阅读器或最终工作台页面。
