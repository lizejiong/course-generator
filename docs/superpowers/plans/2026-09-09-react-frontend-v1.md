# React 前端 V1 实施计划

> **给执行者：** 本计划在当前仓库的功能分支执行；每个任务完成后运行指定验证并提交。
>
> **目标：** 构建直接消费既有 FastAPI API 的 React 课程库和生成工作台，完整呈现七阶段状态、审核、暂停、停止及发布读取能力。
>
> **架构：** `api.ts` 是唯一 HTTP 边界并使用后端稳定的英文机器字段；React Router 管理课程库、工作台与发布详情路径；TanStack Query 负责轮询与失效。界面只解释 `GET /api/runs/{run_id}` 的 `stage` 和 `status`，不读取 Checkpoint、不推断节点。
>
> **技术栈：** React、TypeScript、Vite、React Router、TanStack Query、普通 CSS、Vitest。

---

## 文件结构

| 路径 | 责任 |
| --- | --- |
| `frontend/package.json` | 前端脚本与依赖锁定入口 |
| `frontend/vite.config.ts` | Vite 开发服务器与 `/api` 代理 |
| `frontend/src/api.ts` | 后端 JSON 类型与唯一请求封装 |
| `frontend/src/App.tsx` | 路由、课程库、工作台、发布详情与审核操作 |
| `frontend/src/stages.ts` | 七阶段中文展示和稳定状态映射 |
| `frontend/src/main.tsx` | Query Client 与路由器装配 |
| `frontend/src/styles.css` | 浅蓝白主题与响应式布局 |
| `frontend/src/api.test.ts` | API 客户端请求与错误归一化测试 |
| `frontend/src/stages.test.ts` | 七阶段映射测试 |

### 任务 1：建立 Vite 与 TypeScript 基础

**文件：**
- 新建：`frontend/package.json`
- 新建：`frontend/index.html`
- 新建：`frontend/tsconfig.json`
- 新建：`frontend/vite.config.ts`
- 新建：`frontend/src/main.tsx`

- [ ] **步骤 1：创建可运行的 React 包配置。**

```json
{
  "scripts": { "dev": "vite", "build": "tsc -b && vite build", "test": "vitest run" },
  "dependencies": { "@tanstack/react-query": "^5.0.0", "react": "^18.3.0", "react-dom": "^18.3.0", "react-router-dom": "^6.28.0" },
  "devDependencies": { "@types/react": "^18.3.0", "@types/react-dom": "^18.3.0", "@vitejs/plugin-react": "^4.3.0", "typescript": "^5.6.0", "vite": "^5.4.0", "vitest": "^2.1.0" }
}
```

- [ ] **步骤 2：编写最小入口和 Vite 配置。**

```ts
export default defineConfig({ plugins: [react()], server: { proxy: { '/api': 'http://127.0.0.1:8000' } } })
```

- [ ] **步骤 3：安装依赖并构建。**

Run: `pnpm.cmd --dir frontend install && pnpm.cmd --dir frontend build`

预期：依赖安装完成，Vite 输出 `dist/` 且 TypeScript 无错误。

- [ ] **步骤 4：提交。**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/index.html frontend/tsconfig.json frontend/vite.config.ts frontend/src/main.tsx
git commit -m "feat: scaffold React frontend"
```

### 任务 2：实现 API 客户端与七阶段观察模型

**文件：**
- 新建：`frontend/src/api.ts`
- 新建：`frontend/src/stages.ts`
- 新建：`frontend/src/api.test.ts`
- 新建：`frontend/src/stages.test.ts`

- [ ] **步骤 1：先编写失败测试，固定 API 请求和阶段投影。**

```ts
it('maps the only seven backend stages', () => expect(stageMeta(7).label).toBe('确认与发布'))
it('posts a review decision', async () => { await postReview('run-1', { scope: 'stage', target: 'stage-1', action: 'approve' }); expect(fetch).toHaveBeenCalledWith('/api/runs/run-1/review', expect.any(Object)) })
```

- [ ] **步骤 2：运行测试，确认因模块不存在而失败。**

Run: `pnpm.cmd --dir frontend test`

预期：失败，提示找不到 `api` 或 `stages` 模块。

- [ ] **步骤 3：实现类型安全 API 封装和映射。**

```ts
export const STAGES = [{ id: 1, label: '课程需求' }, { id: 2, label: '任务定义' }, { id: 3, label: '来源与蓝图' }, { id: 4, label: '批次规划' }, { id: 5, label: '批次生产' }, { id: 6, label: '整课质量闭环' }, { id: 7, label: '确认与发布' }] as const
export async function postReview(runId: string, body: ReviewDecision) { return request<ReviewEvent>(`/api/runs/${runId}/review`, { method: 'POST', body: JSON.stringify(body) }) }
```

- [ ] **步骤 4：运行单元测试和构建。**

Run: `pnpm.cmd --dir frontend test && pnpm.cmd --dir frontend build`

预期：测试全部通过，构建成功。

- [ ] **步骤 5：提交。**

```bash
git add frontend/src/api.ts frontend/src/stages.ts frontend/src/api.test.ts frontend/src/stages.test.ts
git commit -m "feat: add frontend API client and stage model"
```

### 任务 3：实现课程库、生成工作台和发布读取

**文件：**
- 新建：`frontend/src/App.tsx`
- 新建：`frontend/src/styles.css`
- 修改：`frontend/src/main.tsx`

- [ ] **步骤 1：实现课程库页面。**

```tsx
const { data: courses = [] } = useQuery({ queryKey: ['courses'], queryFn: listCourses, refetchInterval: 10_000 })
return <Link to={`/courses/${course.id}`}>{course.definition.title}</Link>
```

- [ ] **步骤 2：实现运行工作台和七阶段只读投影。**

```tsx
const { data: run } = useQuery({ queryKey: ['run', runId], queryFn: () => getRun(runId), refetchInterval: run?.status === 'queued' || run?.status === 'running' ? 2_000 : false })
return <ol>{STAGES.map(stage => <li data-current={stage.id === run?.stage}>{stage.label}</li>)}</ol>
```

- [ ] **步骤 3：接入审批、返工、暂停、停止、warning 确认与最终发布按钮。**

```tsx
await postReview(run.id, { scope: run.stage === 7 ? 'release' : 'stage', target, action: 'approve', evidence: {} })
await postAction(run.id, 'pause')
```

- [ ] **步骤 4：实现发布详情读取与浅蓝白响应式样式。**

```tsx
const { data: release } = useQuery({ queryKey: ['release', courseId, version], queryFn: () => getRelease(courseId, version) })
```

- [ ] **步骤 5：构建并做真实 API 冒烟检查。**

Run: `pnpm.cmd --dir frontend build`

预期：构建成功；在后端运行时，`pnpm.cmd --dir frontend dev` 打开课程库，创建/打开课程并查看工作台，页面仅通过已定义 API 工作。

- [ ] **步骤 6：提交。**

```bash
git add frontend/src/App.tsx frontend/src/styles.css frontend/src/main.tsx
git commit -m "feat: add course workspace frontend"
```

## 自审

- 后端 API 只使用既有 `/api/courses`、`/api/runs`、`/review`、`/actions`、`/artifacts`、`/releases` 路由，没有新增接口或枚举。
- 七阶段标签只来自 `stage=1..7`；`status` 只显示后端返回的稳定枚举，前端不访问 Checkpoint。
- 轮询仅在课程库和运行中任务启用；等待人工、失败、暂停、停止、完成均停止高频轮询。
- 不引入 Redux、Zustand、大型组件库、鉴权、多用户、流式输出或后端产品规则。
