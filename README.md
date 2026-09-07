# 课程生成器

一个采用 FastAPI、React、LangGraph 和 PostgreSQL 的 AI 课程生成项目。

系统通过固定工作流完成需求确认、任务定义、来源与蓝图、批次规划、逐章生产、整课质量闭环以及人工发布。课程正文以 Markdown 为唯一事实源，HTML 是发布视图；关键阶段由人工批准、要求返工或停止。

## 当前状态

项目目前完成 V1 产品需求、交互原型和技术设计，下一步开始实现后端。

## 文档

- [产品需求文档](outputs/course-agent-prd-v0.2.md)
- [技术设计](outputs/course-generator-technical-design-v0.1.md)
- [决策摘要](outputs/course-agent-decision-brief.md)
- [交互原型](outputs/course-agent-prd-prototype.html)

## V1 技术方向

- FastAPI + 独立 Worker
- LangGraph + PostgreSQL Checkpoint
- PostgreSQL jobs 队列，不引入 Redis
- React + TypeScript + Vite
- Markdown 正文与不可变发布包
- 人工参与关键审核与最终发布

