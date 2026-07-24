// 决策队列类型定义
// 抽离为独立文件避免与 decisionQueue.ts 产生循环依赖

/**
 * 决策类型枚举
 * - audit: 审查问题（连续性/文风）
 * - foreshadow: 伏笔候选
 * - suggestion: 建议
 * - recommendation: 推荐
 * - character: 人物档案候选（P2 预留）
 * - book_title: 书名候选（P1 预留）
 * - opening_beat: 开篇节拍候选（P2 预留）
 * - batch_plan: 批量章节规划候选（P1 预留）
 * - commercial_profile: 商业定位候选
 * - memory_candidate: 记忆候选
 */
export type DecisionType =
  | "audit"
  | "foreshadow"
  | "suggestion"
  | "recommendation"
  | "character"
  | "book_title"
  | "opening_beat"
  | "batch_plan"
  | "commercial_profile"
  | "memory_candidate";

/**
 * 决策状态
 * - pending: 待处理
 * - accepted: 已采纳某个候选
 * - ignored: 已忽略整条
 * - modified: 作者修改后采纳
 */
export type DecisionStatus = "pending" | "accepted" | "ignored" | "modified";

/**
 * 候选方案（多候选结构）
 * AI 给出的每个可选方案，含内容、利弊分析、是否推荐
 */
export interface CandidateOption {
  /** 候选 ID（稳定，便于撤销后恢复） */
  id: string;
  /** 候选内容 */
  content: string;
  /** 优势列表 */
  pros: string[];
  /** 劣势列表 */
  cons: string[];
  /** AI 是否推荐此候选 */
  recommended?: boolean;
  /** 来源说明（如"基于XX爆款拆解"） */
  source?: string;
}

/**
 * 决策项数据结构（支持多候选 + 利弊分析）
 * 兼容旧版单候选结构（无 candidates 字段时自动包装）
 */
export interface DecisionItem {
  /** 决策项 ID（幂等去重） */
  id: string;
  /** 决策类型 */
  type: DecisionType;
  /** 标题 */
  title: string;
  /** 决策背景说明（灰色小字） */
  context?: string;
  /** 候选方案列表（1-N 个） */
  candidates: CandidateOption[];
  /** 作者选中的候选 ID */
  selectedCandidateId?: string;
  /** 决策状态 */
  status: DecisionStatus;
  /** 创建时间 */
  createdAt: string;
  /** 决策时间 */
  decidedAt?: string;
  /** 来源：AI 推送或作者手动 */
  source: "ai" | "manual";
  /** 来源页面路径（可跳回就地处理） */
  pagePath?: string;
  /**
   * 兼容旧版字段（仅用于读取旧数据）
   * @deprecated 使用 candidates 代替
   */
  content?: string;
  /**
   * 兼容旧版字段（仅用于读取旧数据）
   * @deprecated 使用 candidates[].pros/cons 代替
   */
  reason?: string;
}

/**
 * 旧版决策项结构（v1，单候选）
 * 用于类型守卫和向后兼容迁移
 */
export interface LegacyDecisionItem {
  id: string;
  type: DecisionType;
  title: string;
  content: string;
  reason?: string;
  status: "pending" | "accepted" | "ignored";
  createdAt: string;
}

/**
 * 类型守卫：判断是否为旧版决策项（无 candidates 字段）
 */
export function isLegacyDecisionItem(
  item: DecisionItem | LegacyDecisionItem,
): item is LegacyDecisionItem {
  return !Array.isArray((item as DecisionItem).candidates);
}
