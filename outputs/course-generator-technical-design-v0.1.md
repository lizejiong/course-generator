# 课程生成器 V1 技术设计

> 版本：v0.1  
> 日期：2026-09-07  
> 状态：已确认，可进入实现  
> 面向后续开发 Agent：以本文件确定技术边界，以 PRD 确定产品和质量规则；不要从历史对话重新推导方案。

## 1. 目标与原则

构建一个本地单实例的课程生成系统。FastAPI 提供 API，独立 Worker 执行 LangGraph，React 提供课程库与生成工作台，PostgreSQL 保存运行、调度、审计和 Checkpoint，课程内容与发布包落盘。

核心原则：

- 系统代码控制流程顺序、权限、预算、质量门、失效和人工中断。
- 模型只在理解、规划、写作、Humanizer 和语义审校节点工作。
- Markdown 是课程正文唯一事实源，HTML 仅为派生发布视图。
- 人工拥有批准、要求返工和停止三种权力，最终发布必须人工确认。
- V1 顺序执行，不实现章节并发、Redis、向量数据库、登录和多人协作。
- Skill 专职提供通用写作方法，不包含业务 Schema、ID、阶段、路径、评分门槛或路由。

## 2. 仓库结构

```text
course-generator/
├── backend/
├── frontend/
├── skills/
│   ├── instructional-writer/
│   └── natural-language-editor/
├── courses/
├── releases/
├── docs/
└── compose.yaml
```

开发时只用 Compose 启动 PostgreSQL。FastAPI、Worker 和 React 分别直接运行；完整容器化不属于 V1 前置工作。

## 3. 运行架构

```text
React
  │ HTTP + 状态轮询
  ▼
FastAPI ──写入──▶ PostgreSQL
                       │
                       │ 领取 job
                       ▼
                    Worker
                       │
                       ▼
                 LangGraph 主图
                       │
           ┌───────────┴───────────┐
           ▼                       ▼
       课程工作区              模型/网页来源
```

FastAPI 不执行长时间模型任务。创建或恢复运行时，它在同一数据库事务中写入 `run` 和 `job`，立即返回 `202 Accepted`。Worker 领取 job 后驱动 LangGraph；到达人工中断点时 job 正常结束，run 进入 `waiting_human`，不占用 Worker。人工决定写入后创建新的恢复 job。

## 4. 事实源边界

| 信息 | 唯一事实源 | 说明 |
|---|---|---|
| 课程定义、章节索引 | `course.json` | 课程是什么 |
| 课程正文 | `lessons/*.md` 对应的不可变 artifact revision | HTML 不可反向修改正文 |
| 当前执行位置 | LangGraph Checkpoint | `runs` 不参与流程路由 |
| 前端运行状态 | `runs` | Checkpoint 的查询投影，可在恢复时修正 |
| Worker 调度 | `jobs` | 不保存业务节点游标 |
| 文件版本与有效性 | `artifacts` | 只保存元数据、路径和哈希 |
| 人工决定 | `review_events` | 只追加，不原地改写 |
| 发布版本 | `releases/<slug>/<version>` | 不可变，发布只提升标记 |

`course.json` 保存课程名称、受众、学习目标、内容范围、章节计划、字符门槛、Token 配置、来源政策和补充资源。运行状态不得写入 `course.json`。所有用户修改统一经过 FastAPI。

## 5. PostgreSQL 数据模型

### 5.1 `courses`

保存稳定身份与定位：`id`、`slug`、`workspace_path`、`archived_at`、创建和更新时间。课程名称等定义字段从 `course.json` 读取，不在数据库维护可独立修改的副本。

### 5.2 `runs`

保存一次完整生成或修复流程的投影：课程、状态、当前用户阶段、当前节点摘要、预算与用量、轻量 Token 账本、暂停/停止请求、LangGraph `thread_id`、错误摘要和时间字段。Token 账本按模型调用追加 `call_id`、operation、节点、模型、输入输出哈希、Token 和结果，不保存 Prompt 或正文。

运行状态：`queued`、`running`、`waiting_human`、`paused`、`failed`、`completed`、`stopped`。

### 5.3 `jobs`

保存 Worker 命令：`run_id`、`job_type`、状态、`input_event_id`、`available_at`、尝试次数、租约、错误码与时间字段。

job 状态：`queued`、`running`、`succeeded`、`failed`、`cancelled`。同一 run 同时最多一个 queued/running job。Worker 使用 `FOR UPDATE SKIP LOCKED` 领取，并在执行期间续租。

### 5.4 `artifacts`

保存 `operation_id`、课程与 run、逻辑路径、不可变存储路径、revision、SHA-256、输入哈希、生产节点、有效性和时间字段。`operation_id` 唯一。

### 5.5 `review_events`

只追加人工审核与知悉事件：作用域、目标、`approve/rework/stop`、意见、证据、关联 revision 和时间。真实 blocker 只能因修复验证通过或人工证据证明不成立而关闭，不能在批准动作中直接豁免。

LangGraph Checkpoint 表由官方 PostgreSQL Checkpointer 管理，不自行复制表结构。

## 6. LangGraph 设计

七阶段是前端观察与审批模型，不强制对应七个子图。V1 使用一个相对平坦的主图，普通节点通过 `stage=1..7` 元数据归组。只有阶段五和阶段六共同使用的单章循环做成 `chapter_cycle` 子图。

```text
主图
├── 需求整理与确认
├── 任务定义与确认
├── 来源、蓝图与确认
├── 批次规划与确认
├── 遍历批次/章节 ──▶ chapter_cycle
├── 整课质量与修复 ──▶ chapter_cycle
└── RC、发布审核与发布
```

`chapter_cycle`：

```text
Context Pack
→ 正文生成或定向修复
→ 确定性预检
→ Humanizer
→ 确定性回归
→ 语义审校
→ 三门汇总
→ 通过 / 有界返工 / 转人工
```

最小 Graph State：

```python
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
```

State 不保存 Markdown、完整来源、模型对话、job 锁或重复的 run 状态。

## 7. Job、恢复与重试

三种重试相互独立：

- job 基础设施错误：额外重试 2 次，每次从 Checkpoint 恢复。
- 节点网络、限流和获取错误：额外重试 2 次；结构化输出错误额外修复 1 次。
- 课程质量失败：不算 job 失败，进入单章最多 3 轮的内容返工。

到达人工审核、暂停、停止或质量升级人工时，当前 job 均正常结束。暂停和停止只在当前模型调用完成并落盘后的安全边界生效。

## 8. 文件写入与幂等

每个产物节点生成稳定 `operation_id`：

```text
run_id + node_name + batch/chapter + round_no + input_hash
```

执行协议：

1. 将字节写入同目录临时文件。
2. 原子替换为 `courses/<slug>/.artifacts/<operation-id>.<ext>`。
3. 用唯一 `operation_id` 登记 `artifacts`。
4. 原子刷新 `workspace/*` 或 `lessons/*` 的人类可读工作视图。
5. 返回 artifact 引用，由 LangGraph 保存 Checkpoint。

节点重入时优先查找相同 operation：文件存在但数据库缺失则补登记；记录存在但工作视图缺失则重建工作视图；artifact 已完整登记则直接复用，不重复调用模型。

输入哈希必须覆盖节点实际读取的所有可见事实源。人工保存也创建新 revision。旧 revision 不覆盖，新证据造成的失效从最早受影响阶段恢复。

## 9. API 契约

```text
POST  /api/courses
GET   /api/courses
GET   /api/courses/{course_id}
PATCH /api/courses/{course_id}
POST  /api/courses/{course_id}/archive
POST  /api/courses/{course_id}/restore

POST  /api/courses/{course_id}/runs
GET   /api/runs/{run_id}
POST  /api/runs/{run_id}/actions

GET   /api/runs/{run_id}/review
POST  /api/runs/{run_id}/review

GET   /api/courses/{course_id}/artifacts
GET   /api/courses/{course_id}/files?path=...
PUT   /api/courses/{course_id}/files?path=...

GET   /api/courses/{course_id}/releases
GET   /api/courses/{course_id}/releases/{version}
```

文件接口只能访问课程根目录内的白名单 Markdown/JSON。阶段七提交批准后自动创建发布 job，不单独设计第二套发布工作流。

## 10. 前端状态与页面

FastAPI 根据节点 `stage` 元数据与 Checkpoint 生成阶段投影。前端不解析 Checkpoint，也不根据节点名推断阶段。

阶段状态只有：`not_started`、`running`、`waiting_human`、`approved`、`needs_rework`、`failed`。进度展示事实，例如“第 5/9 章”或“批次 2/3”，不生成虚假百分比。

V1 用户入口：

- React 课程库：列表、创建、继续、归档和打开发布课程。
- React 生成工作台：七阶段、产物查看/编辑、质量证据和人工决定。
- 发布包静态站点：课程阅读，不在 React 中重写课程渲染器。

运行中的工作台每 2–3 秒轮询 `GET /api/runs/{run_id}`，课程库约每 10 秒轮询；只有发现 revision 或 `updated_at` 变化时才刷新产物详情。后台页和非运行状态降低或停止轮询。前端使用 TanStack Query 管理服务端状态，URL 管理当前课程和阶段，组件本地 state 管理编辑草稿与面板；不引入 Redux 或 Zustand。

## 11. 后端代码结构

```text
backend/app/
├── main.py
├── config.py
├── api/
├── schemas/
├── db/
├── workflows/
│   ├── graph.py
│   ├── state.py
│   ├── routes.py
│   ├── nodes/
│   └── chapter_cycle.py
├── services/
│   ├── courses.py
│   ├── artifacts.py
│   ├── sources.py
│   ├── models.py
│   ├── quality.py
│   ├── releases.py
│   └── reviews.py
├── prompts/
└── worker.py
```

- API 只校验请求和调用 service。
- Workflow 只编排顺序和路由。
- Node 只组装输入、调用 service、返回状态更新。
- Service 保存业务规则和确定性实现，可脱离 LangGraph 测试。
- 模型 SDK 只能由 `services/models.py` 调用。
- 不建立通用 Repository 基类、Event Bus、节点插件系统、工作流 DSL 或多层 interface/implementation。

## 12. 技术栈与配置

后端采用 Python 3.12 同步实现：

```text
fastapi
uvicorn[standard]
pydantic-settings
sqlalchemy
alembic
psycopg[binary,pool]
langgraph
langgraph-checkpoint-postgres
openai
httpx
trafilatura
markdown-it-py
jinja2
pygments
```

开发依赖：`pytest`、`pytest-cov`、`ruff`。依赖由 `pyproject.toml` 和 `uv.lock` 管理。

前端采用 React、TypeScript、Vite、React Router、TanStack Query 和普通 CSS/CSS Modules，不引入大型 UI 组件库。

环境变量：

```text
DATABASE_URL
COURSES_ROOT
RELEASES_ROOT
OPENAI_API_KEY
OPENAI_BASE_URL
OPENAI_MODEL
TAVILY_API_KEY
LOG_LEVEL
```

`TAVILY_API_KEY` 可选；未配置时关闭自动搜索，用户 URL 与粘贴文本仍可使用。V1 不需要 Redis、JWT、S3、向量数据库或 LangSmith Key。

## 13. 实施顺序

只保留三个正式阶段：

1. **完整后端**：数据库、文件存储、Worker、主图、单章子图、七阶段、人工恢复、质量闭环和发布包全部通过 API 可运行。
2. **React 前端**：后端接口稳定后实现课程库和生成工作台，直接连接真实 API，不维护 mock 后端。
3. **联调验收**：验证状态映射、崩溃恢复、人工返工、失效传播、完整课程生成、RC 和发布包。

后端完成标准：仅使用 FastAPI OpenAPI 页面或 HTTP 客户端，即可从创建课程运行到人工发布，并获得符合约定的不可变发布包。

## 14. 实现检查清单

- [ ] 初始化单仓库、Python 3.12、`pyproject.toml`、`uv.lock` 和 PostgreSQL Compose。
- [ ] 建立五张业务表、迁移和 LangGraph PostgreSQL Checkpointer。
- [ ] 实现课程工作区、artifact 幂等写入、哈希和 revision。
- [ ] 实现 jobs 领取、租约、恢复、暂停、停止和三类重试。
- [ ] 实现模型网关、Token 用量账本、Prompt/Skill 哈希与来源抓取。
- [ ] 实现主图、七阶段普通节点和 `chapter_cycle` 子图。
- [ ] 实现三门质量规则、整课修复、RC 与发布包。
- [ ] 使用 API 完成整条后端验收路径和崩溃恢复测试。
- [ ] 实现 React 课程库和生成工作台。
- [ ] 完成前后端联调和 V1 PRD 验收。

## 15. 相关基线

- 产品需求：`outputs/course-agent-prd-v0.2.md`
- 决策摘要：`outputs/course-agent-decision-brief.md`
- 交互原型：`outputs/course-agent-prd-prototype.html`
