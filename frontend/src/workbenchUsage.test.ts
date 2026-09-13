import { expect, test } from "vitest";
import { canEditArtifact, summarizeTokenUsage } from "./workbenchUsage";

const ledger = [
  { node: "chapter_write", operation: "draft_chapter", model: "deepseek-v4-flash", input_tokens: 10, output_tokens: 90 },
  { node: "chapter_write", operation: "draft_chapter", model: "deepseek-v4-flash", input_tokens: 20, output_tokens: 80 },
  { node: "semantic_review", operation: "review_chapter_semantics", model: "deepseek-v4-flash", input_tokens: 30, output_tokens: 10 },
];

test("按业务动作汇总输入、输出和调用次数", () => {
  expect(summarizeTokenUsage(ledger, 240)).toMatchObject({
    usage: 240,
    calls: 3,
    percent: 100,
    groups: [
      { label: "生成章节初稿", calls: 2, inputTokens: 30, outputTokens: 170, totalTokens: 200 },
      { label: "检查章节语义与一致性", calls: 1, inputTokens: 30, outputTokens: 10, totalTokens: 40 },
    ],
  });
});

test("没有额度上限时不展示百分比，未知操作保留原始标识", () => {
  const summary = summarizeTokenUsage([
    { node: "custom", operation: "custom_operation", model: "model", input_tokens: null, output_tokens: 12 },
  ], null);

  expect(summary.percent).toBeNull();
  expect(summary.groups).toEqual([
    { label: "custom_operation", calls: 1, inputTokens: 0, outputTokens: 12, totalTokens: 12 },
  ]);
});

test("完成态禁止修改原本可编辑的产物，未完成态保持可编辑", () => {
  expect(canEditArtifact("workspace/batches/batch-01.json", "completed")).toBe(false);
  expect(canEditArtifact("workspace/batches/batch-01.json", "waiting_human")).toBe(true);
  expect(canEditArtifact("quality.json", "waiting_human")).toBe(false);
});
