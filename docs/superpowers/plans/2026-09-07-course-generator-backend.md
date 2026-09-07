# 课程生成器后端实施计划

> **给执行者：** 本计划由当前任务直接执行；用户已经授权在任务工作目录中连续实现并提交。  
> **目标：** 用 Python 3.12、FastAPI、PostgreSQL、LangGraph 和独立同步 Worker 实现不依赖前端的 V1 后端。  
> **架构：** SQLAlchemy 管理五张业务表，服务层负责文件、质量、审核和发布规则；工作流只做阶段编排，Worker 从 `jobs` 表用租约领取命令。课程正文只存在于 Markdown artifact/工作视图，发布包从这些事实源构建。  
> **技术栈：** FastAPI、SQLAlchemy、Alembic、psycopg、LangGraph、langgraph-checkpoint-postgres、pytest、ruff。

---

## 文件结构

| 路径 | 责任 |
| --- | --- |
| `backend/app/config.py` | 环境配置与路径约束 |
| `backend/app/db/*` | SQLAlchemy engine、会话、五张业务表和迁移 |
| `backend/app/services/courses.py` | 课程工作区与 `course.json` |
| `backend/app/services/artifacts.py` | SHA-256、不可变 artifact、原子工作视图和 revision |
| `backend/app/services/jobs.py` | PostgreSQL 领取、续租和完成/失败重试 |
| `backend/app/services/quality.py` | Markdown AST 有效字符与三门质量汇总 |
| `backend/app/services/reviews.py` | 只追加人工决定与恢复任务 |
| `backend/app/services/releases.py` | RC、静态站点、哈希清单和发布提升 |
| `backend/app/workflows/*` | 平坦主图、`chapter_cycle` 子图和 checkpoint 接入 |
| `backend/app/api/*` | API 请求校验与服务调用 |
| `backend/app/worker.py` | 同步轮询执行器 |
| `backend/tests/*` | 持久化、领取、人工恢复、幂等、质量及 API 测试 |

## 任务 1：工程骨架和 PostgreSQL 持久化

- [ ] 写出 `backend/tests/test_models.py`：创建课程、运行、job、artifact 和审核事件，断言外键、状态枚举、JSON 字段与唯一 `operation_id`。
- [ ] 创建 `pyproject.toml`、`backend/app/config.py`、`backend/app/db/base.py`、`backend/app/db/models.py`、Alembic 初始化文件和 `compose.yaml`；只配置 PostgreSQL，不容器化 API/Worker。
- [ ] 实现 migration，创建 `courses`、`runs`、`jobs`、`artifacts`、`review_events` 以及确保同一 run 单个活跃 job 的 PostgreSQL 部分唯一索引。
- [ ] 运行 `pytest backend/tests/test_models.py -v`，再运行 `ruff check backend`。
- [ ] 提交：`feat: add backend persistence foundation`。

## 任务 2：课程工作区与不可变 artifact

- [ ] 写出 `backend/tests/test_artifacts.py`：同一 operation 重入复用 artifact；文件已落盘但未登记时补登记；已登记但工作视图缺失时重建；不同 revision 不覆盖旧 artifact。
- [ ] 实现课程创建、slug 校验、`course.json` 原子写入与白名单路径读取。
- [ ] 实现 `ArtifactService.write()`：由 `run_id/node/scope/round/input_hash` 生成 operation id，在 `.artifacts` 临时写入后原子替换，计算 SHA-256，登记后原子更新指定工作视图。
- [ ] 运行 `pytest backend/tests/test_artifacts.py -v`。
- [ ] 提交：`feat: add idempotent course artifacts`。

## 任务 3：job 领取、租约和 Worker

- [ ] 写出 `backend/tests/test_jobs.py`：两个会话不能领取同一 job；过期租约可回收；基础设施失败最多再创建两次 job；一个 run 不会有两个活跃 job。
- [ ] 用 `SELECT ... FOR UPDATE SKIP LOCKED` 实现原子领取；实现续租、成功、取消、失败和指数退避重试。
- [ ] 实现同步 `Worker.run_once()`，在人工暂停、停止和审核等待时正常结束 job；异常从 checkpoint 再创建重试命令。
- [ ] 运行 `pytest backend/tests/test_jobs.py -v`。
- [ ] 提交：`feat: add leased PostgreSQL worker jobs`。

## 任务 4：质量门、工作流和审核恢复

- [ ] 写出 `backend/tests/test_quality.py`：Markdown AST 仅统计可见中英文和数字、排除代码/URL/章末来源表；语言门阈值；语义 blocker、重复 blocker 指纹和三轮返工转人工。
- [ ] 实现 deterministic、language、semantic 的结构化 GateResult；质量记录始终携带 gate/hash/revision，哈希不符即无效。
- [ ] 实现 workflow state、平坦主图与复用的 `chapter_cycle`：预检失败跳过语言/语义门，三门失败按上限返工或进入 `waiting_human`。
- [ ] 写出 `backend/tests/test_reviews.py`：审核事件只追加；approve/rework/stop 都创建相应恢复/发布 job；approve 不能关闭真实 blocker。
- [ ] 实现人工审核服务、审核事件、run 查询投影、Checkpoint PostgreSQL checkpointer 接入。
- [ ] 运行 `pytest backend/tests/test_quality.py backend/tests/test_reviews.py -v`。
- [ ] 提交：`feat: add workflow quality gates and human recovery`。

## 任务 5：API、发布包与全链路验收

- [ ] 写出 API 测试：课程 CRUD/归档，创建 run 立即返回 202，文件路径越界被拒绝，审核恢复，RC 构建与不变发布。
- [ ] 实现设计文档列出的全部 FastAPI 路由；API 不执行模型或工作流长任务。
- [ ] 实现来源 URL 校验（仅公共 HTTP(S)）、Context Pack、RC/HTML/Markdown/quality 打包和 `release.json` 全量 SHA-256 清单；发布仅提升有效 RC 状态。
- [ ] 运行 `pytest -v`、`ruff check backend`，并用 PostgreSQL Compose 运行迁移与 OpenAPI 健康检查。
- [ ] 提交：`feat: complete course generator backend v1`。

## 自审

- 设计规定的五张业务表、官方 checkpointer、平坦主图与 `chapter_cycle` 均有明确任务。
- 需求的 Markdown 事实源、原子 artifact、人工暂停恢复、租约、三类重试、三门质量规则、RC 不可变性和 API 均覆盖。
- 未加入 SQLite、Redis、向量库、登录、多人或前端；任务范围保持后端。
