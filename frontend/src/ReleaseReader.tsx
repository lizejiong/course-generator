import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ReleaseChapter, getCourse, getRelease, getReleaseFile } from "./api";
import { Shell, t } from "./App";
import "./release-reader.css";

function releaseChapters(chapters: ReleaseChapter[] | undefined, files: Record<string, string>) {
  if (chapters?.length) return chapters;
  return Object.keys(files).filter((path) => path.startsWith("site/") && path.endsWith(".html") && path !== "site/index.html").sort().map((html_path) => ({ title: html_path.replace(/^site\//, "").replace(/\.html$/, ""), html_path, markdown_path: html_path.replace(/^site\//, "markdown/").replace(/\.html$/, ".md") }));
}

function lessonBody(html: string | undefined) {
  const match = html?.match(/<article class="lesson">([\s\S]*)<\/article>/i);
  return match?.[1] ?? "";
}

export function ReleaseReader() {
  const { courseId = "", version = "" } = useParams();
  const course = useQuery({ queryKey: ["course", courseId], queryFn: () => getCourse(courseId) });
  const release = useQuery({ queryKey: ["release", courseId, version], queryFn: () => getRelease(courseId, version) });
  const chapters = useMemo(() => releaseChapters(release.data?.chapters, release.data?.files ?? {}), [release.data]);
  const [index, setIndex] = useState(0);
  useEffect(() => setIndex(0), [version]);
  const activeIndex = Math.min(index, Math.max(chapters.length - 1, 0));
  const chapter = chapters[activeIndex];
  const html = useQuery({ queryKey: ["release-file", courseId, version, chapter?.html_path], queryFn: () => getReleaseFile(courseId, version, chapter!.html_path), enabled: Boolean(chapter) });
  const markdown = useQuery({ queryKey: ["release-file", courseId, version, chapter?.markdown_path], queryFn: () => getReleaseFile(courseId, version, chapter!.markdown_path), enabled: Boolean(chapter) });
  const download = () => { if (!markdown.data?.content || !chapter) return; const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([markdown.data.content], { type: "text/markdown;charset=utf-8" })); link.download = chapter.markdown_path.split("/").pop() ?? "lesson.md"; link.click(); URL.revokeObjectURL(link.href); };
  const content = lessonBody(html.data?.content);
  return <Shell><main className="reader"><Link to={`/courses/${courseId}`}>← {"\u8fd4\u56de\u8bfe\u7a0b"}</Link><p className="eyebrow">{t.reader} · {version}</p><h1>{course.data?.definition.title}</h1><p>{course.data?.definition.audience}</p><div className="reader-grid"><aside className="toc"><b>{"\u76ee\u5f55"}</b>{chapters.map((item, itemIndex) => <button className={itemIndex === activeIndex ? "selected" : ""} key={item.html_path} onClick={() => setIndex(itemIndex)}>{item.title}</button>)}</aside><section className="reader-content"><div className="reader-tools"><span>{chapters.length ? `${activeIndex + 1} / ${chapters.length}` : "0 / 0"}</span><button className="btn" onClick={download} disabled={!markdown.data?.content}>{t.download}</button></div>{chapter ? <article className="published-lesson" aria-label={chapter.title} dangerouslySetInnerHTML={{ __html: content }} /> : <p className="empty-reader">该发布包中没有可阅读的章节。</p>}<div className="reader-pager"><button className="btn" onClick={() => setIndex(Math.max(0, activeIndex - 1))} disabled={activeIndex === 0}>{t.previous}</button><button className="btn" onClick={() => setIndex(Math.min(chapters.length - 1, activeIndex + 1))} disabled={activeIndex >= chapters.length - 1}>{t.next}</button></div>{html.error instanceof Error && <p className="error">{html.error.message}</p>}</section></div></main></Shell>;
}
