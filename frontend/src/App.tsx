import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, ReactNode } from "react";
import { BrowserRouter, Link, Route, Routes, useNavigate, useParams } from "react-router-dom";

import { createCourse, createRun, getCourse, getRelease, getRun, listCourses, listReleases, postAction, postReview } from "./api";
import { STAGES, stageMeta } from "./stages";
import "./styles.css";

const active = (status?: string) => status === "queued" || status === "running";

function Layout({ children }: { children: ReactNode }) {
  return <><header><Link to="/">课程生成器</Link><span>V1 · API 驱动的课程工作台</span></header><main>{children}</main></>;
}

function CourseLibrary() {
  const query = useQuery({ queryKey: ["courses"], queryFn: listCourses, refetchInterval: 10_000 });
  const navigate = useNavigate(); const client = useQueryClient();
  const mutation = useMutation({ mutationFn: createCourse, onSuccess: (course) => { client.invalidateQueries({ queryKey: ["courses"] }); navigate(`/courses/${course.id}`); } });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    mutation.mutate({ slug: String(form.get("slug")), definition: { title: form.get("title"), audience: form.get("audience"), learning_goals: String(form.get("goals")).split("\n").filter(Boolean), content_scope: form.get("scope"), expected_chapter_count: Number(form.get("chapters")), min_effective_chars_per_chapter: Number(form.get("minimum")), source_policy: "internal_only" } });
  }
  return <Layout><section className="hero"><h1>课程库</h1><p>创建课程后，由 Worker 驱动七阶段生产与人工审核。</p></section><section className="grid"><div className="card"><h2>已有课程</h2>{query.isPending ? <p>正在读取…</p> : query.data?.map(course => <Link className="course" key={course.id} to={`/courses/${course.id}`}><strong>{String(course.definition.title)}</strong><small>{course.slug}</small></Link>) || <p>尚无课程。</p>}</div><form className="card form" onSubmit={submit}><h2>新建最小课程</h2><input name="title" placeholder="课程名称" required /><input name="slug" placeholder="course-slug" pattern="[a-z0-9]+(-[a-z0-9]+)*" required /><input name="audience" placeholder="目标学员" required /><textarea name="goals" placeholder="学习目标，每行一条（3–7 条）" defaultValue={"理解核心概念\n完成一个练习\n识别常见错误"} required /><textarea name="scope" placeholder="内容范围" required /><input name="chapters" type="number" min="1" defaultValue="1" required /><input name="minimum" type="number" min="1" defaultValue="100" required /><button disabled={mutation.isPending}>创建课程</button>{mutation.error && <p className="error">{mutation.error.message}</p>}</form></section></Layout>;
}

function CoursePage() {
  const { courseId = "" } = useParams(); const navigate = useNavigate(); const client = useQueryClient();
  const course = useQuery({ queryKey: ["course", courseId], queryFn: () => getCourse(courseId) });
  const start = useMutation({ mutationFn: () => createRun(courseId), onSuccess: run => { client.invalidateQueries({ queryKey: ["course", courseId] }); navigate(`/courses/${courseId}/runs/${run.id}`); } });
  return <Layout><Link to="/">← 返回课程库</Link>{course.data && <section className="card detail"><h1>{String(course.data.definition.title)}</h1><p>{String(course.data.definition.audience)}</p><button onClick={() => start.mutate()} disabled={start.isPending}>启动生成运行</button>{start.error && <p className="error">{start.error.message}</p>}</section>}</Layout>;
}

function Workbench() {
  const { courseId = "", runId = "" } = useParams(); const client = useQueryClient();
  const run = useQuery({ queryKey: ["run", runId], queryFn: () => getRun(runId), refetchInterval: (q) => active(q.state.data?.status) ? 2_000 : false });
  const releases = useQuery({ queryKey: ["releases", courseId], queryFn: () => listReleases(courseId) });
  const refresh = () => client.invalidateQueries({ queryKey: ["run", runId] });
  const review = useMutation({ mutationFn: (action: string) => { const current = run.data!; const release = releases.data?.find(item => item.status === "rc"); return postReview(runId, { scope: current.stage === 7 ? "release" : "stage", target: current.stage === 7 ? release?.version ?? "r0001" : `stage-${current.stage}`, action, evidence: {} }); }, onSuccess: refresh });
  const action = useMutation({ mutationFn: (kind: "pause" | "stop") => postAction(runId, kind), onSuccess: refresh });
  const data = run.data;
  return <Layout><Link to={`/courses/${courseId}`}>← 返回课程</Link>{data && <><section className="run-header"><div><p className="eyebrow">{stageMeta(data.stage).label}</p><h1>{data.status}</h1><p>{data.node_summary || "等待 Worker 更新"}</p></div><div><button onClick={() => action.mutate("pause")} disabled={!active(data.status)}>安全暂停</button><button className="danger" onClick={() => action.mutate("stop")} disabled={!active(data.status)}>停止</button></div></section><section className="workspace"><ol className="stages">{STAGES.map(stage => <li key={stage.id} className={stage.id === data.stage ? "current" : stage.id < (data.stage ?? 0) ? "done" : ""}><span>{stage.id}</span>{stage.label}</li>)}</ol><article className="card"><h2>人工操作</h2>{data.status === "waiting_human" ? <div className="actions"><button onClick={() => review.mutate("approve")}>批准并继续</button>{data.stage !== 7 && <button onClick={() => review.mutate("rework")}>要求返工</button>}<button className="danger" onClick={() => review.mutate("stop")}>停止运行</button></div> : <p>仅在后端状态为 <code>waiting_human</code> 时可审批或返工。</p>}<h2>运行信息</h2><dl><dt>阶段</dt><dd>{data.stage ?? "—"}</dd><dt>Token</dt><dd>{data.token_usage} / {data.token_limit ?? "未限制"}</dd><dt>错误</dt><dd>{data.error_summary || "无"}</dd></dl>{review.error && <p className="error">{review.error.message}</p>}</article></section>{releases.data?.length ? <section className="card"><h2>发布版本</h2>{releases.data.map(item => <Link key={item.version} to={`/courses/${courseId}/releases/${item.version}`}>{item.version} · {item.status}</Link>)}</section> : null}</>}</Layout>;
}

function ReleasePage() { const { courseId = "", version = "" } = useParams(); const query = useQuery({ queryKey: ["release", courseId, version], queryFn: () => getRelease(courseId, version) }); return <Layout><Link to={`/courses/${courseId}`}>← 返回课程</Link><section className="card"><h1>发布 {version}</h1><pre>{JSON.stringify(query.data, null, 2)}</pre></section></Layout>; }

export function App() { return <BrowserRouter><Routes><Route path="/" element={<CourseLibrary />} /><Route path="/courses/:courseId" element={<CoursePage />} /><Route path="/courses/:courseId/runs/:runId" element={<Workbench />} /><Route path="/courses/:courseId/releases/:version" element={<ReleasePage />} /></Routes></BrowserRouter>; }
