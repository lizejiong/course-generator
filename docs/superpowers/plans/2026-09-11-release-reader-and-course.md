# 发布版课程阅读器与多章验收课程实施计划

> **给执行者：** 必须使用 `superpowers:executing-plans` 逐项执行，并在每个任务的测试通过后提交。
>
> **目标：** 让阅读器只读取不可变发布包中的 HTML/Markdown，提供可阅读的排版与可靠目录；随后生成并发布一门四章真实模型课程验证该路径。
>
> **架构：** 发布阶段在 `release.json` 写入章节标题、Markdown 路径与 HTML 路径；后端只允许读取清单中登记的发布文件。React 阅读器改为以发布清单为唯一输入，在隔离 iframe 中展示生成的 HTML，并用发布 Markdown 下载，不再读取工作区产物。
>
> **技术栈：** Python 3.12、FastAPI、Jinja2、React 18、TanStack Query、Vitest、pytest。

---

### 任务 1：在发布包中记录章节索引并提升 HTML 排版

**文件：**
- 修改：`backend/app/services/releases.py`
- 测试：`backend/tests/test_releases.py`

- [ ] **步骤 1：编写失败测试，要求发布清单保存章节标题及对应 HTML/Markdown。**

```python
manifest = json.loads((release / "release.json").read_text(encoding="utf-8"))
assert manifest["chapters"] == [
    {
        "title": "第一章标题",
        "markdown_path": "markdown/01-example.md",
        "html_path": "site/01-example.html",
    }
]
assert "article" in (release / "site" / "01-example.html").read_text(encoding="utf-8")
```

- [ ] **步骤 2：运行测试并确认失败。**

Run: `uv run pytest backend/tests/test_releases.py -q`

Expected: 失败，`chapters` 不存在。

- [ ] **步骤 3：实现最小发布索引和课程页面样式。**

在 `build_rc()` 中为每个 `lessons/*.md` 生成：

```python
chapters.append({
    "title": self._lesson_title(markdown) or lesson.stem,
    "markdown_path": f"markdown/{lesson.name}",
    "html_path": f"site/{lesson.stem}.html",
})
```

将页面模板改为包含 `<article class="lesson">{{ body }}</article>`，并让 `site/assets/site.css` 覆盖正文宽度、标题层级、段落、列表、引用、代码块和表格的阅读样式。`release.json` 增加 `"chapters": chapters`，不改变已存在发布包。

- [ ] **步骤 4：运行测试并确认通过。**

Run: `uv run pytest backend/tests/test_releases.py -q`

Expected: `passed`。

- [ ] **步骤 5：提交。**

```bash
git add backend/app/services/releases.py backend/tests/test_releases.py
git commit -m "feat: index lessons in release packages"
```

### 任务 2：提供受清单约束的发布文件读取 API

**文件：**
- 修改：`backend/app/api/router.py`
- 测试：`backend/tests/test_api.py`

- [ ] **步骤 1：编写失败测试，读取发布 HTML，拒绝未登记和路径穿越。**

```python
response = client.get(f"/api/courses/{course.id}/releases/r0001/files/site/01-example.html")
assert response.status_code == 200
assert "<article" in response.json()["content"]
assert client.get(f"/api/courses/{course.id}/releases/r0001/files/../release.json").status_code == 404
assert client.get(f"/api/courses/{course.id}/releases/r0001/files/quality/unknown.json").status_code == 404
```

- [ ] **步骤 2：运行测试并确认失败。**

Run: `uv run pytest backend/tests/test_api.py -q`

Expected: 404，路由尚不存在。

- [ ] **步骤 3：实现只读发布文件端点。**

在 `get_release()` 后新增 `GET /courses/{course_id}/releases/{version}/files/{path:path}`：读取 `release.json` 的 `files` 键，使用 `Path(path)` 拒绝绝对路径和 `..`，仅当规范化后的相对路径在清单中才以 UTF-8 返回 `{ "path": path, "content": ... }`。文件不存在、非 UTF-8 或未登记均返回 404。

- [ ] **步骤 4：运行测试并确认通过。**

Run: `uv run pytest backend/tests/test_api.py -q`

Expected: `passed`。

- [ ] **步骤 5：提交。**

```bash
git add backend/app/api/router.py backend/tests/test_api.py
git commit -m "feat: expose immutable release files"
```

### 任务 3：让 React 阅读器使用发布 HTML 和发布 Markdown

**文件：**
- 修改：`frontend/src/api.ts`
- 修改：`frontend/src/App.tsx`
- 修改：`frontend/src/styles.css`
- 测试：`frontend/src/App.test.tsx`（若不存在则新建）

- [ ] **步骤 1：编写失败测试，断言阅读器请求发布清单和发布 HTML，不请求工作区 artifacts/files。**

```tsx
renderReaderAt("/courses/course-1/releases/r0001");
expect(await screen.findByRole("heading", { name: "Python 数据处理入门" })).toBeInTheDocument();
expect(await screen.findByTitle("第一章：数据容器" )).toHaveAttribute("srcDoc", expect.stringContaining("<article"));
expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/releases/r0001/files/site/01-data.html"));
```

- [ ] **步骤 2：运行测试并确认失败。**

Run: `pnpm.cmd test -- --run`

Expected: 失败，现有 `Reader` 请求 `artifacts` 与工作区 `files`。

- [ ] **步骤 3：实现发布版 Reader。**

在 `api.ts` 新增 `getReleaseFile(id, version, path)`；在 `App.tsx` 定义 `ReleaseManifest` 和章节类型。`Reader` 只从 `release.chapters`（旧包回退为 `release.files` 的 `site/*.html`）建立目录，选中章节时请求其 `html_path` 并以：

```tsx
<iframe className="lesson-frame" sandbox="" title={chapter.title} srcDoc={html.data?.content ?? ""} />
```

展示。下载按钮请求同一章节的 `markdown_path`，而非调用工作区 `getFile`。删除 `Reader` 对 `listArtifacts`、批次文件和工作区章节的依赖。

在 `styles.css` 为 iframe 定义自适应宽度、高度、边框和移动端行为；目录保持当前章节高亮和上一章/下一章切换。

- [ ] **步骤 4：运行前端测试与构建。**

Run: `pnpm.cmd test -- --run; pnpm.cmd build`

Expected: 全部通过，TypeScript 无错误。

- [ ] **步骤 5：提交。**

```bash
git add frontend/src/api.ts frontend/src/App.tsx frontend/src/styles.css frontend/src/App.test.tsx
git commit -m "feat: render immutable release lessons"
```

### 任务 4：端到端发布四章课程并人工验收

**文件：**
- 修改：无（仅产生运行时课程和发布包）
- 验证：浏览器、`backend/tests`、前端测试与构建

- [ ] **步骤 1：创建课程。**

创建「Python 数据容器实战：列表、字典与集合」，设定 4 章、每章至少 500 有效字符、Token 预算 160000、`internal_only`。学习目标依次为：选择合适容器、使用列表处理有序数据、使用字典按键查找、使用集合去重和成员判断。

- [ ] **步骤 2：逐阶段人工批准并核验。**

在第 1–4 阶段检查课程定义、MISSION/SPEC、蓝图和批次文件；第 5 阶段确认四个 `lessons/*.md` 与质量证据；第 6 阶段确认 `quality.json` 无 blocker；第 7 阶段批准发布。

- [ ] **步骤 3：验收阅读器。**

打开 `r0001`，确认目录有 4 个中文标题、章节切换可用、iframe 中有标题/段落/代码块而不是 Markdown 原文、下载得到冻结的 Markdown。确认课程详情显示该发布版本。

- [ ] **步骤 4：运行完整回归。**

Run: `uv run pytest backend/tests -q; pnpm.cmd test -- --run; pnpm.cmd build`

Expected: 全部通过。
