import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrowserRouter, Link, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { Artifact, Course, Definition, createCourse, createRun, getCourse, getFile, getRelease, getRun, listArtifacts, listCourses, listReleases, listRuns, postAction, postReview, putFile } from "./api";
import { STAGES, stageMeta } from "./stages";
import { artifactsForStage } from "./workbenchArtifacts";
import { canEditArtifact, isEditableArtifact, summarizeTokenUsage } from "./workbenchUsage";
import { ReleaseReader } from "./ReleaseReader";
import "./styles.css";
import "./workbench.css";

export const t = {
  name: "\u8bfe\u7a0b\u751f\u6210\u5668", library: "\u8bfe\u7a0b\u5e93", newCourse: "\u65b0\u5efa\u8bfe\u7a0b", back: "\u8fd4\u56de\u8bfe\u7a0b\u5e93", create: "\u521b\u5efa\u8bfe\u7a0b\u5e76\u8fdb\u5165\u5de5\u4f5c\u53f0", start: "\u542f\u52a8\u751f\u6210\u8fd0\u884c", stages: "\u751f\u4ea7\u9636\u6bb5", artifacts: "\u5de5\u4f5c\u4ea7\u7269", review: "\u4eba\u5de5\u5ba1\u67e5", approve: "\u6279\u51c6\u5e76\u7ee7\u7eed", rework: "\u8981\u6c42\u8fd4\u5de5", pause: "\u5b89\u5168\u6682\u505c", stop: "\u505c\u6b62", edit: "\u7f16\u8f91", save: "\u4fdd\u5b58\u4fee\u8ba2", cancel: "\u53d6\u6d88", reader: "\u8bfe\u7a0b\u9605\u8bfb\u5668", download: "\u4e0b\u8f7d Markdown", previous: "\u4e0a\u4e00\u7ae0", next: "\u4e0b\u4e00\u7ae0"
};
const running = (status?: string) => status === "queued" || status === "running";
const initialFile = (stage: number | null, items: Artifact[]) => ({ 1: "course.json", 2: "workspace/MISSION.md", 3: "workspace/BLUEPRINT.md", 4: "workspace/batches/batch-01.json", 5: items.find((a) => a.path.startsWith("lessons/"))?.path }[stage ?? 0]);
const latestArtifacts = (items: Artifact[]) => Array.from(items.reduce((byPath, item) => { const prior = byPath.get(item.path); if (!prior || item.revision > prior.revision) byPath.set(item.path, item); return byPath; }, new Map<string, Artifact>()).values());
const lessonText = (content?: string) => { if (!content) return ""; try { const parsed = JSON.parse(content) as { markdown?: unknown }; return typeof parsed.markdown === "string" ? parsed.markdown : content; } catch { return content; } };

export function Shell({ children }: { children: ReactNode }) { return <div className="shell"><header className="topbar"><Link className="brand" to="/"><b>✦</b><span>{t.name}<small>COURSE WORKBENCH</small></span></Link><nav><Link to="/">{t.library}</Link><span>{"\u4e03\u9636\u6bb5\u4eba\u5de5\u628a\u5173"}</span></nav></header><RunRecovery/>{children}</div>; }
function Chip({ status }: { status: string }) { const cn = status === "completed" || status === "published" ? "green" : status === "waiting_human" ? "amber" : "gray"; return <span className={`chip ${cn}`}>{status.replace("_", " ")}</span>; }
function ErrorText({ value }: { value: unknown }) { return value instanceof Error ? <p className="error">{value.message}</p> : null; }
function RunRecovery() { const { runId = "" } = useParams(); const client = useQueryClient(); const run = useQuery({ queryKey: ["run", runId], queryFn: () => getRun(runId), enabled: Boolean(runId) }); const [tokenLimit, setTokenLimit] = useState(""); const restore = useMutation({ mutationFn: () => postAction(runId, "resume", tokenLimit ? Number(tokenLimit) : undefined), onSuccess: () => { client.invalidateQueries({ queryKey: ["run", runId] }); client.invalidateQueries({ queryKey: ["artifacts"] }); } }); const data = run.data; if (!runId || data?.status !== "paused") return null; const budgetPaused = data.error_code === "token_budget_pause"; const nextLimit = Number(tokenLimit); const invalidLimit = budgetPaused && (!Number.isFinite(nextLimit) || nextLimit <= data.token_usage); return <section className="recovery-banner"><div><b>{"\u8fd0\u884c\u5df2\u6682\u505c"}</b><p>{budgetPaused ? `Token \u5df2\u4f7f\u7528 ${data.token_usage}\uff0c\u8bf7\u5148\u8bbe\u5b9a\u66f4\u9ad8\u7684\u9884\u7b97\u518d\u6062\u590d\u3002` : "\u53ef\u4ee5\u4ece\u6700\u8fd1\u7684\u5b89\u5168\u8282\u70b9\u6062\u590d\u8fd0\u884c\u3002"}</p></div>{budgetPaused && <label>{"\u65b0 Token \u9884\u7b97"}<input aria-label="新 Token 预算" type="number" min={data.token_usage + 1} placeholder={String(data.token_usage + 1)} value={tokenLimit} onChange={(event) => setTokenLimit(event.target.value)}/></label>}<button className="btn primary" onClick={() => restore.mutate()} disabled={restore.isPending || invalidLimit}>{"\u6062\u590d\u8fd0\u884c"}</button><ErrorText value={restore.error}/></section>; }

function CourseCard({ course, index }: { course: Course; index: number }) { const releases = useQuery({ queryKey: ["releases", course.id], queryFn: () => listReleases(course.id) }); const latest = releases.data?.find((r) => r.status === "published"); return <Link className="course-card" to={`/courses/${course.id}`}><small>#{String(index + 1).padStart(2, "0")}</small><h2>{course.definition.title}</h2><p>{course.definition.audience}</p><div className="card-foot"><Chip status={latest ? "published" : "draft"}/>{latest ? <span>{latest.version}</span> : <span>→</span>}</div></Link>; }
function Library() { const courses = useQuery({ queryKey: ["courses"], queryFn: listCourses, refetchInterval: 10000 }); return <Shell><main className="library"><section className="library-head"><div><p className="eyebrow">{"\u8bfe\u7a0b\u751f\u4ea7\u5de5\u4f5c\u6d41"}</p><h1>{"\u628a\u5b66\u4e60\u60f3\u6cd5\u53d8\u6210\n\u53ef\u53d1\u5e03\u7684\u5b8c\u6574\u8bfe\u7a0b\u3002"}</h1><p>{"\u4ee5\u7ed3\u6784\u5316\u8f93\u5165\u3001\u53ef\u8ffd\u6eaf\u4ea7\u7269\u548c\u4e03\u9636\u6bb5\u4eba\u5de5\u628a\u5173\uff0c\u4ee3\u66ff\u53cd\u590d\u7684\u804a\u5929\u5f0f\u751f\u6210\u3002"}</p></div><Link className="btn primary" to="/new">{t.newCourse}</Link></section><section className="course-grid">{courses.data?.map((course, index) => <CourseCard key={course.id} course={course} index={index}/>)}<Link className="course-card create-card" to="/new"><b>＋</b><h2>{"\u521b\u5efa\u4e00\u95e8\u8bfe\u7a0b"}</h2><p>{"\u8bbe\u5b9a\u5b66\u4e60\u8005\u3001\u8303\u56f4\u3001\u8d44\u6599\u6765\u6e90\u4e0e\u9a8c\u6536\u6807\u51c6\u3002"}</p></Link></section><ErrorText value={courses.error}/></main></Shell>; }

function NewCourse() { const nav = useNavigate(); const client = useQueryClient(); const [policy, setPolicy] = useState("internal_only"); const save = useMutation({ mutationFn: createCourse, onSuccess: (course) => { client.invalidateQueries({ queryKey: ["courses"] }); nav(`/courses/${course.id}`); } }); function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = new FormData(event.currentTarget); const resource = String(form.get("resource") || "").trim(); const definition: Definition = { title: String(form.get("title")), audience: String(form.get("audience")), learning_goals: String(form.get("goals")).split("\n").map((x) => x.trim()).filter(Boolean), content_scope: String(form.get("scope")), expected_chapter_count: Number(form.get("chapters")), min_effective_chars_per_chapter: Number(form.get("minimum")), source_policy: policy, token_limit: form.get("token") ? Number(form.get("token")) : undefined, resources: resource ? [{ name: "\u8865\u5145\u8d44\u6599", text: resource }] : undefined }; save.mutate({ slug: String(form.get("slug")), definition }); } return <Shell><main className="form-page"><Link to="/">← {t.back}</Link><form className="course-form" onSubmit={submit}><div><p className="eyebrow">{"\u9636\u6bb5\u4e00 · \u8bfe\u7a0b\u9700\u6c42"}</p><h1>{"\u5b9a\u4e49\u4e00\u95e8\u53ef\u9a8c\u6536\u7684\u8bfe\u7a0b"}</h1><p>{"\u8fd9\u4e9b\u5185\u5bb9\u5c06\u6210\u4e3a\u540e\u7eed\u89c4\u5212\u3001\u751f\u6210\u3001\u5ba1\u67e5\u548c\u53d1\u5e03\u7684\u7a33\u5b9a\u8f93\u5165\u3002"}</p></div><div className="field-grid"><label>{"\u8bfe\u7a0b\u540d\u79f0"}<input name="title" required placeholder="Python 变量入门"/></label><label>URL slug<input name="slug" required pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="python-variables"/></label><label>{"\u76ee\u6807\u5b66\u4e60\u8005"}<input name="audience" required placeholder="Python 初学者"/></label><label>{"\u9884\u671f\u7ae0\u8282\u6570"}<input name="chapters" type="number" min="1" defaultValue="3" required/></label></div><label>{"\u5b66\u4e60\u76ee\u6807"}<small>{"\u6bcf\u884c\u4e00\u6761"}</small><textarea name="goals" required defaultValue={"\u7406\u89e3\u6838\u5fc3\u6982\u5ff5\n\u5b8c\u6210\u4e00\u4e2a\u5b9e\u8df5\u7ec3\u4e60\n\u8bc6\u522b\u5e38\u89c1\u9519\u8bef"}/></label><label>{"\u5185\u5bb9\u8303\u56f4"}<textarea name="scope" required placeholder="明确必须讲、可以讲和不讲的内容"/></label><div className="field-grid"><label>{"\u5355\u7ae0\u6700\u4f4e\u6709\u6548\u5b57\u7b26\u6570"}<input name="minimum" type="number" min="1" defaultValue="800" required/></label><label>Token {"\u9884\u7b97"}<input name="token" type="number" min="1" placeholder="12000"/></label></div><label>{"\u6765\u6e90\u653f\u7b56"}<select value={policy} onChange={(e) => setPolicy(e.target.value)}><option value="internal_only">{"\u4ec5\u4f7f\u7528\u6211\u63d0\u4f9b\u7684\u8d44\u6599"}</option><option value="user_plus_official">{"\u7528\u6237\u8d44\u6599 + \u5b98\u65b9\u8d44\u6599"}</option><option value="official_only">{"\u4ec5\u516c\u5f00\u5b98\u65b9\u8d44\u6599"}</option><option value="extended_cross_checked">{"\u6269\u5c55\u8d44\u6599\u5e76\u4ea4\u53c9\u6838\u9a8c"}</option></select></label><label>{"\u8865\u5145\u8d44\u6599"}<textarea name="resource" placeholder="粘贴笔记、提纲或已有资料（可选）"/></label><ErrorText value={save.error}/><button className="btn primary" disabled={save.isPending}>{t.create} →</button></form></main></Shell>; }

function CourseDetail() { const { courseId = "" } = useParams(); const nav = useNavigate(); const course = useQuery({ queryKey: ["course", courseId], queryFn: () => getCourse(courseId) }); const releases = useQuery({ queryKey: ["releases", courseId], queryFn: () => listReleases(courseId) }); const runs = useQuery({ queryKey: ["runs", courseId], queryFn: () => listRuns(courseId) }); const run = useMutation({ mutationFn: () => createRun(courseId, course.data?.definition.token_limit), onSuccess: (result) => { queryClient.invalidateQueries({ queryKey: ["runs", courseId] }); nav(`/courses/${courseId}/runs/${result.id}`); } }); const published = releases.data?.find((item) => item.status === "published"); const latestRun = runs.data?.[0]; const resumable = latestRun && ["queued", "running", "waiting_human", "paused"].includes(latestRun.status); const queryClient = useQueryClient(); return <Shell><main className="detail-page"><Link to="/">← {t.back}</Link>{course.data && <section className="detail-card"><p className="eyebrow">{"\u8bfe\u7a0b\u5b9a\u4e49"}</p><h1>{course.data.definition.title}</h1><p>{course.data.definition.audience}</p><div className="definition-grid"><div><small>{"\u5b66\u4e60\u76ee\u6807"}</small><ul>{course.data.definition.learning_goals.map((goal) => <li key={goal}>{goal}</li>)}</ul></div><div><small>{"\u751f\u4ea7\u7ea6\u675f"}</small><p>{course.data.definition.expected_chapter_count} {"\u7ae0 · \u6700\u4f4e"} {course.data.definition.min_effective_chars_per_chapter} {"\u5b57 · "}{course.data.definition.source_policy}</p></div></div><div className="actions">{latestRun && <Link className="btn primary" to={`/courses/${courseId}/runs/${latestRun.id}`}>{resumable ? "继续最近运行" : "查看最近运行"} →</Link>}<button className="btn" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? "正在创建…" : "重新生成"}</button>{published && <Link className="btn" to={`/courses/${courseId}/releases/${published.version}`}>{t.reader}</Link>}</div><ErrorText value={runs.error}/><ErrorText value={run.error}/></section>}</main></Shell>; }

function Workbench() {
  const { courseId = "", runId = "" } = useParams();
  const client = useQueryClient();
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => getRun(runId), refetchInterval: (query) => running(query.state.data?.status) ? 2000 : false });
  const course = useQuery({ queryKey: ["course", courseId], queryFn: () => getCourse(courseId) });
  const artifacts = useQuery({ queryKey: ["artifacts", courseId], queryFn: () => listArtifacts(courseId), refetchInterval: running(run.data?.status) ? 2000 : false });
  const releases = useQuery({ queryKey: ["releases", courseId], queryFn: () => listReleases(courseId) });
  const [selected, setSelected] = useState<string>();
  const [viewStage, setViewStage] = useState<number>();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const data = run.data;
  const files = latestArtifacts(artifacts.data ?? []);
  const completed = data?.status === "completed";
  const focusedStage = viewStage ?? data?.stage ?? (completed ? 7 : null);
  const validFiles = files.filter((item) => item.valid);
  const visibleItems = artifactsForStage(focusedStage, validFiles);
  const archivedItems = validFiles.filter((item) => !visibleItems.some((visible) => visible.path === item.path));
  const current = selected ?? initialFile(focusedStage, visibleItems) ?? visibleItems[0]?.path;
  const viewingArchive = Boolean(selected && !visibleItems.some((item) => item.path === selected));
  const release = releases.data?.find((item) => item.status === "rc") ?? releases.data?.find((item) => item.status === "published");
  const currentIsEditable = Boolean(current && canEditArtifact(current, data?.status));
  const currentHasContent = Boolean(current && isEditableArtifact(current));
  const tokenUsage = summarizeTokenUsage(data?.token_ledger ?? [], data?.token_limit ?? null);

  useEffect(() => {
    setSelected(undefined);
    setEditing(false);
  }, [focusedStage]);

  const file = useQuery({ queryKey: ["file", courseId, current], queryFn: () => getFile(courseId, current!), enabled: currentHasContent });
  const save = useMutation({
    mutationFn: () => putFile(courseId, current!, draft),
    onSuccess: () => {
      setEditing(false);
      client.invalidateQueries({ queryKey: ["file", courseId, current] });
      client.invalidateQueries({ queryKey: ["artifacts", courseId] });
    },
  });
  const refresh = () => {
    client.invalidateQueries({ queryKey: ["run", runId] });
    client.invalidateQueries({ queryKey: ["artifacts", courseId] });
    client.invalidateQueries({ queryKey: ["releases", courseId] });
  };
  const review = useMutation({
    mutationFn: (action: string) => {
      const currentRun = run.data!;
      const candidate = releases.data?.find((item) => item.status === "rc");
      return postReview(runId, {
        scope: currentRun.stage === 7 ? "release" : "stage",
        target: currentRun.stage === 7 ? candidate?.version ?? "r0001" : "stage-" + currentRun.stage,
        action,
        evidence: {},
      });
    },
    onSuccess: refresh,
  });
  const action = useMutation({ mutationFn: (kind: "pause" | "stop") => postAction(runId, kind), onSuccess: refresh });

  if (!data) return <Shell><main>正在读取运行…<ErrorText value={run.error}/></main></Shell>;

  const renderArtifact = (item: Artifact) => <button className={"artifact " + (current === item.path ? "selected" : "")} key={item.id} onClick={() => setSelected(item.path)}>
    <b>{item.path.endsWith(".md") ? "MD" : "JSON"}</b>
    <span><strong>{item.path}</strong><small>r{item.revision} · {item.sha256.slice(0, 8)}{canEditArtifact(item.path, data.status) ? "" : " · 只读"}</small></span>
  </button>;

  return <Shell>
    <div className="workbench-head">
      <div><Link to={"/courses/" + courseId}>←</Link><strong>{course.data?.definition.title ?? "课程工作台"}</strong><Chip status={data.status}/></div>
      <div className="run-summary"><span>Token {data.token_usage} / {data.token_limit ?? "∞"}</span><button className="btn" onClick={() => action.mutate("pause")} disabled={!running(data.status)}>{t.pause}</button><button className="btn danger" onClick={() => action.mutate("stop")} disabled={!running(data.status)}>{t.stop}</button></div>
    </div>
    <div className="workbench-grid">
      <aside className="stage-rail">
        <small>{t.stages}</small>
        {STAGES.map((stage) => <button key={stage.id} onClick={() => setViewStage(stage.id)} className={"stage-btn " + (stage.id === focusedStage ? "active " : "") + (stage.id < (data.stage ?? 0) || (completed && stage.id <= (data.stage ?? 7)) ? "done" : "")}>
          <b>{stage.id}</b><span><strong>{stage.label}</strong><small>{stage.hint}</small></span>{(stage.id < (data.stage ?? 0) || (completed && stage.id <= (data.stage ?? 7))) && <i>✓</i>}
        </button>)}
        <div className="rail-run"><p>{completed ? "已完成，可点击任一阶段回看对应产物。" : "点击任一阶段查看对应产物。"}</p></div>
      </aside>
      <main className="workspace-main">
        <div className="workspace-title"><div><p className="eyebrow">{stageMeta(focusedStage).label}</p><h1>本阶段产出</h1><p>{stageMeta(focusedStage).hint}</p></div></div>
        {focusedStage === 7 && <section className="panel"><div className="panel-head"><h3>发布版本</h3><span>{release?.status === "published" ? "已发布" : release?.status === "rc" ? "待发布" : "尚未生成"}</span></div><div className="panel-body">{release ? <><p className="release-note">已生成正式课程版本，可在阅读器中查看。</p><Link className="btn primary" to={"/courses/" + courseId + "/releases/" + release.version}>打开 {release.version} 课程阅读器</Link></> : <p>本阶段尚未生成发布候选。</p>}</div></section>}
        {focusedStage !== 7 && <section className="panel">
          <div className="panel-head"><h3>审核产物</h3><span>{visibleItems.length} 个</span></div>
          {visibleItems.length ? <div className="artifact-list">{visibleItems.map(renderArtifact)}</div> : focusedStage !== 7 && <div className="panel-body"><p>该阶段尚未生成可审核产物。</p></div>}
        </section>}
        {archivedItems.length > 0 && <details className="panel artifact-archive"><summary>查看其他留档（{archivedItems.length} 个内部工件）</summary><div className="artifact-list">{archivedItems.map(renderArtifact)}</div></details>}
        {current && <section className="panel">
          <div className="panel-head"><h3>{current}{viewingArchive && <small> · 跨阶段归档</small>}</h3>{currentIsEditable ? <div>{editing ? <><button className="btn" onClick={() => setEditing(false)}>{t.cancel}</button><button className="btn primary" onClick={() => save.mutate()}>{t.save}</button></> : <button className="btn" onClick={() => { setDraft(file.data?.content ?? ""); setEditing(true); }}>{t.edit}</button>}</div> : completed && currentHasContent ? <span className="readonly-badge">已归档，只读</span> : null}</div>
          <div className="panel-body">{currentHasContent ? <>{completed && <p className="readonly-note">该课程已完成并发布。这里保留的是当时的生产记录，不能再直接修改；如需调整，请从课程详情创建新的运行。</p>}{editing ? <textarea className="editor" value={draft} onChange={(event) => setDraft(event.target.value)}/> : <pre className="preview">{file.data?.content ?? "正在读取产物…"}</pre>}</> : <p>该工件是 Worker 留档的只读证据，不允许在工作台直接修改。</p>}</div>
        </section>}
      </main>
      <aside className="review-panel">
        <p className="eyebrow">{t.review}</p><h2>{data.status === "waiting_human" ? "等待你的决定" : completed ? "本次运行已完成" : "运行状态"}</h2>
        <p>{data.error_summary || (completed ? "课程已留档并发布，可返回课程详情进入阅读器。" : "查看本阶段产物后推进流程。")}</p>
        <div className="gate"><b>当前阶段</b><span>{stageMeta(data.stage).label}</span></div>
        <div className="decision-box">{data.status === "waiting_human" ? <><button className="btn primary" onClick={() => review.mutate("approve")}>{data.stage === 7 ? "批准正式发布" : t.approve}</button>{data.stage !== 7 && <button className="btn warn" onClick={() => review.mutate("rework")}>{t.rework}</button>}<button className="btn danger" onClick={() => review.mutate("stop")}>{t.stop}</button></> : <p>{completed ? "保留运行记录供追溯。" : "Worker 正在处理；你可以在顶部安全暂停或停止。"}</p>}<ErrorText value={review.error}/></div>
        <details className="usage-details">
          <summary>模型用量说明</summary>
          <p className="usage-intro">Token 是模型读取和生成文本时消耗的计量单位。用量越高，通常代表生成内容或审核轮次更多。</p>
          <div className="usage-total"><b>{data.token_usage.toLocaleString()} Token</b><span>{data.token_limit ? `额度 ${data.token_limit.toLocaleString()} · 已使用 ${tokenUsage.percent}%` : "未设置额度上限"}</span></div>
          <p className="usage-calls">本次课程共进行了 {tokenUsage.calls} 次模型调用。</p>
          <div className="usage-groups">{tokenUsage.groups.map((group) => <div className="usage-group" key={group.label}><b>{group.label}</b><span>{group.calls} 次 · {group.totalTokens.toLocaleString()} Token</span><small>模型读取 {group.inputTokens.toLocaleString()}，生成 {group.outputTokens.toLocaleString()}</small></div>)}</div>
        </details>
      </aside>
    </div>
  </Shell>;
}

function LegacyReader() { const { courseId = "", version = "" } = useParams(); const course = useQuery({ queryKey: ["course", courseId], queryFn: () => getCourse(courseId) }); const artifacts = useQuery({ queryKey: ["artifacts", courseId], queryFn: () => listArtifacts(courseId) }); const release = useQuery({ queryKey: ["release", courseId, version], queryFn: () => getRelease(courseId, version) }); const batch = useQuery({ queryKey: ["file", courseId, "workspace/batches/batch-01.json"], queryFn: () => getFile(courseId, "workspace/batches/batch-01.json"), retry: false }); const lessons = useMemo(() => latestArtifacts(artifacts.data ?? []).filter((item) => item.valid && item.path.startsWith("lessons/")).sort((a, b) => a.path.localeCompare(b.path)), [artifacts.data]); const chapters = useMemo(() => { try { return (JSON.parse(batch.data?.content ?? "{}") as { chapters?: { title?: string; lesson_path?: string }[] }).chapters ?? []; } catch { return []; } }, [batch.data]); const chapterTitle = (path: string) => chapters.find((chapter) => chapter.lesson_path === path)?.title ?? path.replace("lessons/", ""); const [index, setIndex] = useState(0); const lesson = lessons[index]; const file = useQuery({ queryKey: ["file", courseId, lesson?.path], queryFn: () => getFile(courseId, lesson!.path), enabled: Boolean(lesson) }); const content = lessonText(file.data?.content); const download = () => { if (!content || !lesson) return; const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([content], { type: "text/markdown;charset=utf-8" })); link.download = lesson.path.split("/").pop() ?? "lesson.md"; link.click(); URL.revokeObjectURL(link.href); }; return <Shell><main className="reader"><Link to={`/courses/${courseId}`}>← {"\u8fd4\u56de\u8bfe\u7a0b"}</Link><p className="eyebrow">{t.reader} · {version}</p><h1>{course.data?.definition.title}</h1><p>{course.data?.definition.audience}</p><div className="reader-grid"><aside className="toc"><b>{"\u76ee\u5f55"}</b>{lessons.map((item, itemIndex) => <button className={itemIndex === index ? "selected" : ""} key={item.id} onClick={() => setIndex(itemIndex)}>{chapterTitle(item.path)}</button>)}</aside><section className="reader-content"><div className="reader-tools"><span>{index + 1} / {lessons.length || 0}</span><button className="btn" onClick={download} disabled={!content}>{t.download}</button></div><pre className="lesson-content">{content || "\u6b63\u5728\u8bfb\u53d6\u7ae0\u8282\u2026"}</pre><div className="reader-pager"><button className="btn" onClick={() => setIndex(Math.max(0, index - 1))} disabled={index === 0}>{t.previous}</button><button className="btn" onClick={() => setIndex(Math.min(lessons.length - 1, index + 1))} disabled={index >= lessons.length - 1}>{t.next}</button></div></section></div>{release.data && <details className="release-details"><summary>{"\u53d1\u5e03\u6e05\u5355"}</summary><pre>{JSON.stringify(release.data, null, 2)}</pre></details>}</main></Shell>; }

export function App() { return <BrowserRouter><Routes><Route path="/" element={<Library/>}/><Route path="/new" element={<NewCourse/>}/><Route path="/courses/:courseId" element={<CourseDetail/>}/><Route path="/courses/:courseId/runs/:runId" element={<Workbench/>}/><Route path="/courses/:courseId/releases/:version" element={<ReleaseReader/>}/></Routes></BrowserRouter>; }
