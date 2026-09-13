import { expect, test } from "vitest";
import type { Artifact } from "./api";
import { artifactsForStage } from "./workbenchArtifacts";

const artifact = (path: string): Artifact => ({
  id: path,
  operation_id: `operation-${path}`,
  path,
  revision: 1,
  sha256: "a".repeat(64),
  valid: true,
});

const artifacts = [
  "course.json",
  "workspace/INPUT.json",
  "workspace/MISSION.md",
  "workspace/SPEC.md",
  "workspace/BLUEPRINT.md",
  "workspace/batches/batch-01.json",
  "workspace/context-packs/batch-01/chapter-01.json",
  "lessons/01-chapter-1.md",
  "workspace/quality/chapter-1-round-1.json",
  "quality.json",
].map(artifact);

test("阶段五只展示章节，不展示内部 Context Pack 与逐轮质检证据", () => {
  expect(artifactsForStage(5, artifacts).map((item) => item.path)).toEqual([
    "lessons/01-chapter-1.md",
  ]);
});

test("阶段六只展示课程级质量产物", () => {
  expect(artifactsForStage(6, artifacts).map((item) => item.path)).toEqual(["quality.json"]);
});

test("阶段一保留课程定义与输入快照", () => {
  expect(artifactsForStage(1, artifacts).map((item) => item.path)).toEqual([
    "course.json",
    "workspace/INPUT.json",
  ]);
});
