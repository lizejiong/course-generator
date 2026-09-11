export const STAGES = [
  { id: 1, label: "\u8bfe\u7a0b\u9700\u6c42", hint: "\u8f93\u5165\u4e0e\u9a8c\u6536\u8fb9\u754c" },
  { id: 2, label: "\u4efb\u52a1\u5b9a\u4e49", hint: "MISSION \u4e0e SPEC" },
  { id: 3, label: "\u6765\u6e90\u4e0e\u84dd\u56fe", hint: "\u8d44\u6599\u4e0e\u6559\u5b66\u7ed3\u6784" },
  { id: 4, label: "\u6279\u6b21\u89c4\u5212", hint: "\u987a\u5e8f\u3001\u9884\u7b97\u4e0e\u8303\u56f4" },
  { id: 5, label: "\u6279\u6b21\u751f\u4ea7", hint: "\u7ae0\u8282\u4e0e\u8d28\u91cf\u8bc1\u636e" },
  { id: 6, label: "\u6574\u8bfe\u8d28\u91cf\u95ed\u73af", hint: "\u4e00\u81f4\u6027\u4e0e\u4fee\u590d\u8ba1\u5212" },
  { id: 7, label: "\u786e\u8ba4\u4e0e\u53d1\u5e03", hint: "RC \u4e0e\u6b63\u5f0f\u53d1\u5e03" },
] as const;

export function stageMeta(stage: number | null) {
  return STAGES.find((item) => item.id === stage) ?? { id: 0, label: "\u5c1a\u672a\u5f00\u59cb", hint: "" };
}
