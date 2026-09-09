# 课程生成器

一个采用 FastAPI、React、LangGraph 和 PostgreSQL 的 AI 课程生成项目。

系统通过固定工作流完成需求确认、任务定义、来源与蓝图、批次规划、逐章生产、整课质量闭环以及人工发布。课程正文以 Markdown 为唯一事实源，HTML 是发布视图；关键阶段由人工批准、要求返工或停止。

## 功能概览

- 课程库：创建、归档与恢复课程；课程定义和正文均可版本化保存。
- 七阶段生成工作台：需求、任务定义、来源与蓝图、批次规划、批次生产、整课质量闭环、确认与发布。
- 人工参与：支持审批、返工、安全暂停、停止、warning 知悉与最终发布。
- 可追溯产物：Markdown 正文、质量证据、来源快照、RC 与正式发布包均使用不可变 artifact 与 SHA-256 记录。
- 可观察执行：FastAPI 提供运行投影，独立 Worker 从 PostgreSQL jobs 队列执行 LangGraph 工作流；前端通过轮询展示真实状态。

## 架构

```text
frontend/  React + TypeScript + Vite + TanStack Query
backend/   FastAPI + SQLAlchemy + LangGraph
PostgreSQL 课程、运行、任务、审核事件与 Checkpoint
courses/   课程工作区与 Markdown 产物
releases/  不可变 RC 与正式发布包
```

## 本地启动

后端位于 `backend/`，使用 Python 3.12、FastAPI、PostgreSQL 和独立同步 Worker；API、Worker 与前端在本地分别启动。

```powershell
Copy-Item .env.example .env
docker compose up -d postgres
uv sync --group dev
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir backend --reload
```

另开终端运行 Worker：

```powershell
uv run python -m app.worker_main
```

安装并启动前端：

```powershell
pnpm --dir frontend install
pnpm --dir frontend dev
```

前端开发服务器默认将 `/api` 请求代理到 `http://127.0.0.1:8000`。

Windows 本机若 5432 已被占用，Compose 默认将项目 PostgreSQL 映射到 5433；`.env.example` 已使用相同连接地址。

验证：

```powershell
uv run pytest backend/tests -q --basetemp=work/pytest-verify
uv run ruff check backend
pnpm --dir frontend test
pnpm --dir frontend build
```

真实 OpenAI 兼容模型和可选 Tavily 的人工验收、环境变量与最小课程操作步骤见 [真实外部服务人工验收手册](outputs/external-service-manual-acceptance.md)。密钥仅应保存在本机 `.env`，不得提交。

## 文档

- [产品需求文档](outputs/course-agent-prd-v0.2.md)
- [技术设计](outputs/course-generator-technical-design-v0.1.md)
- [决策摘要](outputs/course-agent-decision-brief.md)
- [真实外部服务人工验收手册](outputs/external-service-manual-acceptance.md)
- [交互原型](outputs/course-agent-prd-prototype.html)

## V1 技术方向

- FastAPI + 独立 Worker
- LangGraph + PostgreSQL Checkpoint
- PostgreSQL jobs 队列，不引入 Redis
- React + TypeScript + Vite
- Markdown 正文与不可变发布包
- 人工参与关键审核与最终发布

