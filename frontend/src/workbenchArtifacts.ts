import type { Artifact } from "./api";

const STAGE_MATCHERS: Record<number, (path: string) => boolean> = {
  1: (path) => path === "course.json" || path === "workspace/INPUT.json",
  2: (path) => path === "workspace/MISSION.md" || path === "workspace/SPEC.md",
  3: (path) => ["workspace/RESOURCES.md", "workspace/BLUEPRINT.md", "workspace/source-index.json"].includes(path),
  4: (path) => path.startsWith("workspace/batches/"),
  5: (path) => path.startsWith("lessons/"),
  6: (path) => path === "quality.json" || path === "workspace/course-repair-plan.json",
  7: () => false,
};

export function artifactsForStage(stage: number | null, items: Artifact[]): Artifact[] {
  const matches = STAGE_MATCHERS[stage ?? 0] ?? (() => false);
  return items.filter((item) => matches(item.path));
}
