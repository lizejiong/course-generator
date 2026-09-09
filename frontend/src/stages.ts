export const STAGES = [
  { id: 1, label: "课程需求" }, { id: 2, label: "任务定义" }, { id: 3, label: "来源与蓝图" },
  { id: 4, label: "批次规划" }, { id: 5, label: "批次生产" }, { id: 6, label: "整课质量闭环" },
  { id: 7, label: "确认与发布" },
] as const;

export function stageMeta(stage: number | null) {
  return STAGES.find((item) => item.id === stage) ?? { id: 0, label: "尚未开始" };
}
