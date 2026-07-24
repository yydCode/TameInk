// 决策类型相关常量
// 独立文件避免 AiDecisionCard.tsx 因导出常量触发 react-refresh 警告

import type { DecisionType } from "./types";

// 决策类型对应的中文标签
export const DECISION_TYPE_LABELS: Record<DecisionType, string> = {
  audit: "审查问题",
  foreshadow: "伏笔候选",
  suggestion: "建议",
  recommendation: "推荐",
  character: "人物档案",
  book_title: "书名候选",
  opening_beat: "开篇节拍",
  batch_plan: "批量规划",
  commercial_profile: "商业定位",
  memory_candidate: "记忆候选",
};
