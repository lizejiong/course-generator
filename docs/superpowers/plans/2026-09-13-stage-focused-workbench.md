# 阶段聚焦工作台实施计划

> **给执行 agent：** 使用 `superpowers:executing-plans` 按任务逐项执行。
**目标：** 工作台仅展示当前阶段的核心审核产物，并保留完整归档入口。

**架构：** `frontend/src/workbenchArtifacts.ts` 定义阶段到稳定工件路径的映射；`App.tsx` 使用该映射过滤最新有效工件。后端工件、审核 API 和发布语义完全不变。

**技术栈：** React、TypeScript、Vitest、Vite。

---

### 任务 1：阶段工件映射与测试

**文件：**
- 新建：`frontend/src/workbenchArtifacts.ts`
- 新建：`frontend/src/workbenchArtifacts.test.ts`

- [ ] 编写 Vitest：验证阶段 5 仅返回 `lessons/`，阶段 6 仅返回 `quality.json` 与修复计划；第 7 阶段发布版本由发布 API 单独呈现，不从工件列表推断。
- [ ] 运行 `pnpm test -- workbenchArtifacts.test.ts`，确认失败。
- [ ] 实现阶段 1–7 的稳定路径匹配器。
- [ ] 重跑同一测试并提交 `feat: map workbench artifacts to stages`。

### 任务 2：阶段聚焦的工作台

**文件：**
- 修改：`frontend/src/App.tsx`

- [ ] 从最新有效工件导出 `visibleItems`，仅在主列表渲染这些工件。
- [ ] 将列表标题改为“本阶段产出”，空列表显示“该阶段尚未生成可审核产物”。
- [ ] 增加默认折叠的“查看全部归档”区域；选择归档工件后保持详情可读并标明“跨阶段归档”。第 7 阶段渲染发布 API 返回的 RC/正式版本卡片及阅读器链接。
- [ ] 运行 `pnpm test && pnpm build`，提交 `feat: focus workbench artifacts by stage`。

### 任务 3：真实页面验收

**文件：**
- 无。

- [ ] 打开已发布课程的工作台，确认第 7 阶段只显示发布候选核心工件。
- [ ] 展开完整归档并选择一个历史工件，确认主列表仍保持阶段聚焦。
- [ ] 汇报测试、构建和页面验收结果。
