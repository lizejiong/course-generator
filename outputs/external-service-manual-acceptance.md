# 真实外部服务人工验收手册

> 状态：待操作者配置外部服务密钥后执行
>
> 本手册验证已交付后端与真实 OpenAI 兼容服务的集成。它不以单元测试中的替身模型代替真实模型验收，也不会要求或记录任何密钥。

## 1. 前置条件与密钥边界

在仓库根目录复制环境变量模板，密钥仅保存在本机 `.env`，不要提交、粘贴到 API 请求、日志、课程文件、数据库或截图中：

```powershell
Copy-Item .env.example .env
```

必需变量：

```dotenv
DATABASE_URL=postgresql+psycopg://course_generator:course_generator@localhost:5433/course_generator
COURSES_ROOT=./courses
RELEASES_ROOT=./releases
OPENAI_API_KEY=<仅保存在本机的密钥>
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=<服务商实际可用的模型标识>
LOG_LEVEL=INFO
```

`OPENAI_BASE_URL` 使用 OpenAI 原生服务时保持 `https://api.openai.com/v1`；使用任何兼容 Chat Completions API 的服务时，改为该服务商文档规定的 API 根地址，并将 `OPENAI_MODEL` 改为其实际模型标识。程序通过 OpenAI 兼容 SDK 调用 `base_url` 与 `model`，不需要修改后端代码。先用服务商给出的最小调用示例确认地址、认证方式和模型名，再启动本项目。

Tavily 是可选项：仅在课程的 `source_policy` 不是 `internal_only` 时用于发现候选 URL。未设置 `TAVILY_API_KEY` 时自动发现关闭；仍可使用用户提供的 `resources`。建议第一次真实验收使用 `internal_only`，以隔离模型验收与网络检索的不确定性。

## 2. 启动服务

```powershell
docker compose up -d postgres
uv sync --group dev
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir backend --reload
```

另开终端启动 Worker：

```powershell
uv run python -m app.worker_main
```

确认 API 存活：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

预期返回 `status = ok`。Windows 若本机 `5432` 已被占用，模板和 Compose 默认使用 `5433`。

## 3. 创建最小课程并启动运行

以下示例使用一章、低但有效的字数下限以控制成本。保存创建响应中的 `id` 为 `$courseId`，再保存启动响应中的 `id` 为 `$runId`。

```powershell
$course = Invoke-RestMethod http://127.0.0.1:8000/api/courses -Method Post -ContentType 'application/json; charset=utf-8' -Body (@{
  slug = 'python-variables-mini'
  definition = @{
    title = 'Python 变量入门'
    audience = '有基础编程经验的自学者'
    learning_goals = @('解释变量的作用', '使用赋值创建变量', '识别常见命名错误')
    content_scope = '仅覆盖 Python 变量、赋值和命名规则'
    expected_chapter_count = 1
    min_effective_chars_per_chapter = 100
    source_policy = 'internal_only'
  }
} | ConvertTo-Json -Depth 6)
$courseId = $course.id
$run = Invoke-RestMethod "http://127.0.0.1:8000/api/courses/$courseId/runs" -Method Post -ContentType 'application/json' -Body '{"token_limit":12000}'
$runId = $run.id
```

轮询运行投影。等待人工操作时，响应的 `status` 为 `waiting_human`，并以 `stage` 指示当前阶段；运行中为 `queued` 或 `running`，暂停为 `paused`，最终发布完成为 `completed`。

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/runs/$runId"
Invoke-RestMethod "http://127.0.0.1:8000/api/runs/$runId/review"
```

## 4. 审批、返工、暂停恢复与发布

每次在 `waiting_human` 后先读取运行的 `stage`。阶段 1 至 6 的正常批准请求使用 `scope = stage` 和 `target = stage-N`；阶段 7 的发布使用 `scope = release` 和当前 RC 版本（通常为 `r0001`）。批准会创建只追加的审核事件并排入恢复或发布 job。

```powershell
# 示例：批准当前第 1 阶段；将 N 替换为实际的 $state.stage。
$state = Invoke-RestMethod "http://127.0.0.1:8000/api/runs/$runId"
Invoke-RestMethod "http://127.0.0.1:8000/api/runs/$runId/review" -Method Post -ContentType 'application/json; charset=utf-8' -Body (@{
  scope = 'stage'; target = "stage-$($state.stage)"; action = 'approve'; comment = '人工验收通过'; evidence = @{}
} | ConvertTo-Json -Depth 4)
```

在阶段 2 或 3 首次等待时，验证返工：提交 `action = rework`，目标为当前 `stage-N`，附上可审核说明；Worker 恢复后应仍在该阶段并重建相应产物。随后再次批准。

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/runs/$runId/review" -Method Post -ContentType 'application/json; charset=utf-8' -Body (@{
  scope = 'stage'; target = "stage-$($state.stage)"; action = 'rework'; comment = '请补充一个可操作的示例'; evidence = @{ manual_check = 'rework-path' }
} | ConvertTo-Json -Depth 4)
```

在 Worker 正在处理阶段 5 时，验证安全暂停：

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/runs/$runId/actions" -Method Post -ContentType 'application/json' -Body '{"action":"pause","scope":"run","target":"current"}'
```

等待当前模型调用安全落盘后，预期运行变为 `paused`。恢复不使用单独的 action：对暂停前所在阶段提交一条 `approve` 审核事件，Worker 会排入 `resume` job。若暂停发生在尚未进入人工审核的模型调用前，则先用相同课程新建一次 run 再执行此步骤；不要手工修改数据库状态。

继续逐阶段批准至阶段 6。若 `quality.json` 包含未解决 warning，必须先用 `acknowledge` 事件确认所有 `warning_fingerprints`；存在 blocker 时不能批准，应提交 `rework`。阶段 7 生成 RC 后，查询候选版本并执行最终发布：

```powershell
$releases = Invoke-RestMethod "http://127.0.0.1:8000/api/courses/$courseId/releases"
$version = ($releases | Where-Object status -eq 'rc' | Select-Object -Last 1).version
Invoke-RestMethod "http://127.0.0.1:8000/api/runs/$runId/review" -Method Post -ContentType 'application/json; charset=utf-8' -Body (@{
  scope = 'release'; target = $version; action = 'approve'; comment = '人工批准正式发布'; evidence = @{}
} | ConvertTo-Json -Depth 4)
```

最终检查：`GET /api/runs/{runId}` 为 `completed`，`GET /api/courses/{courseId}/releases` 中版本为 `published`，并可读取 `GET /api/courses/{courseId}/releases/{version}`。发布目录应包含不可变的 `release.json`、`site/`、`markdown/` 和 `quality/`。

## 5. 验收记录

执行者应在独立的验收记录中保存日期、代码提交、模型供应商和模型标识、课程 ID、运行 ID、每个阶段的状态转移、返工/暂停/恢复/发布结果，以及脱敏错误摘要。不要保存 API key、Authorization 头、完整 prompt 或模型原始回复。

在 `OPENAI_API_KEY` 未配置时，本验收项状态必须记录为“待用户配置真实模型密钥”；该状态不等同于真实模型已验证。
