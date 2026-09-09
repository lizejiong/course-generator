export type Course = { id: string; slug: string; archived_at: string | null; definition: Record<string, unknown> };
export type Run = { id: string; status: string; stage: number | null; node_summary: string | null; token_limit: number | null; token_usage: number; error_code: string | null; error_summary: string | null; updated_at: string };
export type ReviewDecision = { scope: string; target: string; action: string; comment?: string; evidence?: Record<string, unknown> };
export type Release = { version: string; status: "rc" | "published" };
export type Artifact = { id: string; operation_id: string; path: string; revision: number; sha256: string; valid: boolean };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) throw new Error((await response.text()) || `请求失败：${response.status}`);
  return response.json() as Promise<T>;
}
export const listCourses = () => request<Course[]>("/api/courses");
export const getCourse = (id: string) => request<Course>(`/api/courses/${id}`);
export const createCourse = (body: { slug: string; definition: Record<string, unknown> }) => request<Course>("/api/courses", { method: "POST", body: JSON.stringify(body) });
export const createRun = (courseId: string) => request<Run>(`/api/courses/${courseId}/runs`, { method: "POST", body: "{}" });
export const getRun = (id: string) => request<Run>(`/api/runs/${id}`);
export const postReview = (id: string, body: ReviewDecision) => request(`/api/runs/${id}/review`, { method: "POST", body: JSON.stringify(body) });
export const postAction = (id: string, action: "pause" | "stop") => request<Run>(`/api/runs/${id}/actions`, { method: "POST", body: JSON.stringify({ action, scope: "run", target: "current" }) });
export const listReleases = (id: string) => request<Release[]>(`/api/courses/${id}/releases`);
export const getRelease = (id: string, version: string) => request<Record<string, unknown>>(`/api/courses/${id}/releases/${version}`);
export const listArtifacts = (id: string) => request<Artifact[]>(`/api/courses/${id}/artifacts`);
