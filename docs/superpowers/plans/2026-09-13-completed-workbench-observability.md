# 已完成课程工作台可读性实施计划

> **执行 agent：** 必须使用 `superpowers:executing-plans` 按任务逐项执行；每个任务完成后运行对应测试，并在任务结束时提交。
**目标：** 让已完成课程的工作台成为清晰、只读的历史观察界面，并将 Token 技术账本转化为可理解的模型用量说明。

**架构：** 保持既有 API 与七阶段模型不变，在前端新增纯函数模块集中处理“可编辑性”和 Token 聚合、中文操作标签；`Workbench` 只消费该视图模型。已完成运行不改变任何产物或发布数据，只通过 `status === "completed"` 禁用编辑入口。界面仍允许选择任一阶段和打开归档，不扩展后端数据字段。

**技术栈：** React、TypeScript、TanStack Query、Vitest、Vite、现有 FastAPI API。

---

## 文件结构

- 新建 `frontend/src/workbenchUsage.ts`：Token 账本聚合、操作中文标签、额度百分比与编辑权限纯函数。
- 新建 `frontend/src/workbenchUsage.test.ts`：覆盖聚合、未知操作回退、无限额度和完成态只读规则。
- 修改 `frontend/src/App.tsx`：用视图模型渲染模型用量说明；完成态移除编辑操作；精简阶段 7 空审核卡与英文节点摘要。
- 修改 `frontend/src/styles.css`：压缩阶段标题留白、加强信息层次、增加只读提示和用量分组样式。

### 任务 1：建立工作台用量与权限视图模型

**文件：**
- 新建：`frontend/src/workbenchUsage.ts`
- 新建：`frontend/src/workbenchUsage.test.ts`

- [ ] **步骤 1：编写失败测试，锁定账本聚合和完成态只读规则。**

```ts
import { canEditArtifact, summarizeTokenUsage } from "./workbenchUsage";

const ledger = [
  { node: "chapter_write", operation: "draft_chapter", model: "deepseek-v4-flash", input_tokens: 10, output_tokens: 90 },
  { node: "chapter_write", operation: "draft_chapter", model: "deepseek-v4-flash", input_tokens: 20, output_tokens: 80 },
  { node: "semantic_review", operation: "review_chapter_semantics", model: "deepseek-v4-flash", input_tokens: 30, output_tokens: 10 },
];

it("按业务动作汇总输入、输出和调用次数", () => {
  expect(summarizeTokenUsage(ledger, 240).groups).toEqual([
    { label: "生成章节初稿", calls: 2, inputTokens: 30, outputTokens: 170, totalTokens: 200 },
    { label: "检查章节语义与一致性", calls: 1, inputTokens: 30, outputTokens: 10, totalTokens: 40 },
  ]);
});

it("完成态禁止修改原本可编辑的产物，未完成态保持可编辑", () => {
  expect(canEditArtifact("workspace/batches/batch-01.json", "completed")).toBe(false);
  expect(canEditArtifact("workspace/batches/batch-01.json", "waiting_human")).toBe(true);
  expect(canEditArtifact("quality.json", "waiting_human")).toBe(false);
});
```

- [ ] **步骤 2：运行测试并确认失败。**

Run: `pnpm.cmd test -- workbenchUsage.test.ts`

Expected: 测试无法导入 `./workbenchUsage`。

- [ ] **步骤 3：实现最小视图模型。**

```ts
export type TokenLedgerEntry = {
  node: string;
  operation: string;
  model: string;
  input_tokens: number | null;
  output_tokens: number | null;
};

export const isEditableArtifact = (path: string) =>
  path === "course.json" || path === "workspace/MISSION.md" || path === "workspace/SPEC.md" ||
  path === "workspace/BLUEPRINT.md" || path === "workspace/RESOURCES.md" ||
  path.startsWith("workspace/batches/") || path.startsWith("lessons/");

const operationLabel: Record<string, string> = {
  draft_chapter: "生成章节初稿",
  humanize_chapter: "润色章节内容",
  review_chapter_semantics: "检查章节语义与一致性",
};

export const canEditArtifact = (path: string, runStatus?: string) =>
  isEditableArtifact(path) && runStatus !== "completed";

export function summarizeTokenUsage(entries: TokenLedgerEntry[], limit: number | null) {
  const groups = new Map<string, { label: string; calls: number; inputTokens: number; outputTokens: number }>();
  for (const entry of entries) {
    const label = operationLabel[entry.operation] ?? entry.operation;
    const group = groups.get(label) ?? { label, calls: 0, inputTokens: 0, outputTokens: 0 };
    group.calls += 1;
    group.inputTokens += entry.input_tokens ?? 0;
    group.outputTokens += entry.output_tokens ?? 0;
    groups.set(label, group);
  }
  const result = [...groups.values()].map((group) => ({ ...group, totalTokens: group.inputTokens + group.outputTokens }));
  return { groups: result, calls: entries.length, limit, usage: result.reduce((sum, group) => sum + group.totalTokens, 0) };
}
```

- [ ] **步骤 4：补全额度百分比与稳定排序，并让测试通过。**

在 `summarizeTokenUsage` 返回值中加入 `percent: limit ? Math.round(usage / limit * 100) : null`，将 `groups` 以 `totalTokens` 降序排列；在测试中断言 `usage` 为 `240`、`percent` 为 `100`，并新增 `limit === null` 时 `percent === null` 的用例。

Run: `pnpm.cmd test -- workbenchUsage.test.ts`

Expected: 全部通过。

- [ ] **步骤 5：提交视图模型和测试。**

```bash
git add frontend/src/workbenchUsage.ts frontend/src/workbenchUsage.test.ts
git commit -m "feat: add workbench usage view model"
```

### 任务 2：将完成态改为只读历史观察，并精简阶段输出

**文件：**
- 修改：`frontend/src/App.tsx:4-18`
- 修改：`frontend/src/App.tsx:31-128`
- 测试：`frontend/src/workbenchUsage.test.ts`

- [ ] **步骤 1：写出页面使用的派生状态。**

在 `App.tsx` 导入 `canEditArtifact`、`isEditableArtifact` 和 `summarizeTokenUsage`。在 `current` 派生状态之后加入：

```ts
const tokenUsage = summarizeTokenUsage(data?.token_ledger ?? [], data?.token_limit ?? null);
const currentIsEditable = Boolean(current && canEditArtifact(current, data?.status));
const isCompletedHistory = data?.status === "completed";
```

将 `file` query 的 `enabled` 改为 `Boolean(current && isEditableArtifact(current))`。这会让已完成课程继续读取并展示原产物；只有 `currentIsEditable` 控制编辑器与保存按钮。

- [ ] **步骤 2：移除完成态编辑入口，并提供明确的归档说明。**

将产物卡片元信息中的可编辑判断替换为 `canEditArtifact(item.path, data.status)`；将详情面板的编辑按钮条件替换为 `currentIsEditable`。当 `isCompletedHistory && editable(current)` 时，渲染以下只读说明而不是编辑按钮：

```tsx
<span className="readonly-badge">已归档，只读</span>
```

在预览区保留原产物全文，并在其上方显示：`该课程已完成并发布。这里保留的是当时的生产记录，不能再直接修改；如需调整，请从课程详情创建新的运行。`

- [ ] **步骤 3：消除发布阶段的冗余和机器措辞。**

将阶段标题副文案改为 `stageMeta(focusedStage).hint`，不再显示 `data.node_summary`；仅在 `focusedStage !== 7` 时渲染“审核产物”面板。发布卡状态将 `published` 显示为 `已发布`、`rc` 显示为 `待发布`，并补充 `已生成正式课程版本，可在阅读器中查看。`。归档摘要文案改为 `查看其他留档（N 个内部工件）`。

- [ ] **步骤 4：运行单元测试与 TypeScript 检查。**

Run: `pnpm.cmd test -- workbenchUsage.test.ts && pnpm.cmd build`

Expected: 用量聚合、完成态只读测试通过；构建无 TypeScript 错误。

- [ ] **步骤 5：提交完成态行为改动。**

```bash
git add frontend/src/App.tsx frontend/src/workbenchUsage.ts frontend/src/workbenchUsage.test.ts
git commit -m "fix: keep completed workbench artifacts read-only"
```

### 任务 3：把 Token 节点明细改为面向人的模型用量说明

**文件：**
- 修改：`frontend/src/App.tsx:120-126`
- 修改：`frontend/src/styles.css`（`.review-panel details`、`.ledger` 附近）
- 测试：`frontend/src/workbenchUsage.test.ts`

- [ ] **步骤 1：替换技术账本的 JSX。**

将现有 `<details><summary>Token 与节点明细</summary>…</details>` 替换为：

```tsx
<details className="usage-details">
  <summary>模型用量说明</summary>
  <p className="usage-intro">Token 是模型读取和生成文本时消耗的计量单位。用量越高，通常代表生成内容或审核轮次更多。</p>
  <div className="usage-total">
    <b>{data.token_usage.toLocaleString()} Token</b>
    <span>{data.token_limit ? `额度 ${data.token_limit.toLocaleString()} · 已使用 ${tokenUsage.percent}%` : "未设置额度上限"}</span>
  </div>
  <p className="usage-calls">本次课程共进行了 {tokenUsage.calls} 次模型调用。</p>
  <div className="usage-groups">
    {tokenUsage.groups.map((group) => <div className="usage-group" key={group.label}>
      <b>{group.label}</b><span>{group.calls} 次 · {group.totalTokens.toLocaleString()} Token</span>
      <small>模型读取 {group.inputTokens.toLocaleString()}，生成 {group.outputTokens.toLocaleString()}</small>
    </div>)}
  </div>
</details>
```

- [ ] **步骤 2：为说明卡增加紧凑、可扫读的样式。**

在 `styles.css` 中新增以下样式，保持右栏窄宽度内不溢出：

```css
.usage-details{padding-top:16px;font-size:13px;color:#536e89}
.usage-details summary{font-weight:800;cursor:pointer}
.usage-intro,.usage-calls{margin:10px 0;color:#6e849d;line-height:1.6;font-size:12px}
.usage-total{display:grid;gap:3px;padding:11px;border-radius:9px;background:#eef6fe;color:#2967a9}
.usage-total b{font-size:15px}.usage-total span,.usage-group small{font-size:11px}
.usage-groups{display:grid;gap:8px;margin-top:10px}.usage-group{display:grid;gap:3px;padding:9px 0;border-bottom:1px solid #edf2f7}
.usage-group b{font-size:12px;color:#405973}.usage-group span{font-size:11px;color:#597490}
.readonly-badge{font-size:11px;font-weight:800;color:#5c7895;background:#eef3f8;border-radius:999px;padding:5px 8px}
```

- [ ] **步骤 3：压缩阶段展示留白，强化产出层级。**

在 `styles.css` 将工作台主区和标题调整为：

```css
.workspace-main{padding:26px clamp(24px,4vw,64px);background:#f4f8fc}
.workspace-title{margin:0 0 16px}.workspace-title h1{font-size:24px;line-height:1.25}
.workspace-title p:not(.eyebrow){font-size:14px;line-height:1.5}
.artifact-archive summary{padding:13px 15px;font-weight:800;cursor:pointer;color:#49657f}
```

删除或替换原有 `.review-panel details` 和 `.ledger` 的规则，避免旧账本样式与新说明卡冲突。

- [ ] **步骤 4：运行完整前端验证。**

Run: `pnpm.cmd test && pnpm.cmd build`

Expected: 现有 8 个测试及新增用量测试全部通过，Vite 生产构建成功。

- [ ] **步骤 5：在本地完成态课程进行视觉验收。**

Run: `pnpm.cmd dev -- --host 127.0.0.1 --port 5175`

验证 `http://127.0.0.1:5175/courses/96e556cd-bf5e-4089-8915-46589db102cc/runs/22fae4ff-c3d7-4c93-a3a9-4a5ff179852a`：

1. 阶段 7 不显示“审核产物 0 个”，发布状态显示“已发布”。
2. 点击阶段 4 的 `workspace/batches/batch-01.json` 后不出现“编辑”，显示“已归档，只读”。
3. 展开“模型用量说明”后能读到总额度、25 次调用和三类中文动作汇总。
4. 点击阶段 1 至阶段 7 均能回看对应产物，归档保持折叠。

- [ ] **步骤 6：提交界面与样式。**

```bash
git add frontend/src/App.tsx frontend/src/styles.css frontend/src/workbenchUsage.ts frontend/src/workbenchUsage.test.ts
git commit -m "feat: clarify completed workbench observability"
```

### 任务 4：交付前检查

**文件：**
- 修改：`frontend/src/App.tsx`
- 修改：`frontend/src/styles.css`
- 新建：`frontend/src/workbenchUsage.ts`
- 新建：`frontend/src/workbenchUsage.test.ts`

- [ ] **步骤 1：检查工作树只包含本次改动。**

Run: `git status --short`

Expected: 仅列出任务 1 至任务 3 涉及的文件，且无 `main` 分支现有的 `docs/superpowers/plans/2026-09-13-langgraph-orchestration-refactor.md`。

- [ ] **步骤 2：检查最终提交。**

Run: `git log --oneline -3`

Expected: 包含 `feat: clarify completed workbench observability`，且每项提交都可独立通过测试。
