export type TokenLedgerEntry = {
  node: string;
  operation: string;
  model: string;
  input_tokens: number | null;
  output_tokens: number | null;
};

export type TokenUsageGroup = {
  label: string;
  calls: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
};

const operationLabels: Record<string, string> = {
  draft_chapter: "生成章节初稿",
  humanize_chapter: "润色章节内容",
  review_chapter_semantics: "检查章节语义与一致性",
};

export const isEditableArtifact = (path: string) =>
  path === "course.json" ||
  path === "workspace/MISSION.md" ||
  path === "workspace/SPEC.md" ||
  path === "workspace/BLUEPRINT.md" ||
  path === "workspace/RESOURCES.md" ||
  path.startsWith("workspace/batches/") ||
  path.startsWith("lessons/");

export const canEditArtifact = (path: string, runStatus?: string) =>
  isEditableArtifact(path) && runStatus !== "completed";

export function summarizeTokenUsage(entries: TokenLedgerEntry[], limit: number | null) {
  const grouped = new Map<string, Omit<TokenUsageGroup, "totalTokens">>();

  for (const entry of entries) {
    const label = operationLabels[entry.operation] ?? entry.operation;
    const current = grouped.get(label) ?? { label, calls: 0, inputTokens: 0, outputTokens: 0 };
    current.calls += 1;
    current.inputTokens += entry.input_tokens ?? 0;
    current.outputTokens += entry.output_tokens ?? 0;
    grouped.set(label, current);
  }

  const groups = [...grouped.values()]
    .map((group) => ({ ...group, totalTokens: group.inputTokens + group.outputTokens }))
    .sort((a, b) => b.totalTokens - a.totalTokens);
  const usage = groups.reduce((total, group) => total + group.totalTokens, 0);

  return {
    usage,
    calls: entries.length,
    limit,
    percent: limit ? Math.round((usage / limit) * 100) : null,
    groups,
  };
}
