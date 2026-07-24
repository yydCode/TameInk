// 决策队列共享 helper：供审查/伏笔/建议等模块推送决策项到 DecisionQueuePage。
// 数据存储于 localStorage，key 为 `tame-ink:decisions:{projectId}`，与 DecisionQueuePage 一致。
// 支持多候选 + 利弊分析；自动迁移旧版单候选结构。

import {
  type CandidateOption,
  type DecisionItem,
  type DecisionStatus,
  type DecisionType,
  type LegacyDecisionItem,
  isLegacyDecisionItem,
} from "./types";

// 重新导出类型与类型守卫，便于调用方一次性导入
export {
  type CandidateOption,
  type DecisionItem,
  type DecisionStatus,
  type DecisionType,
  isLegacyDecisionItem,
};

const STORAGE_KEY_PREFIX = "tame-ink:decisions:";
// 旧版 TodayWorkspacePage 使用的 localStorage key（迁移后删除）
const LEGACY_AI_DECISIONS_PREFIX = "tame-ink:ai-decisions:";

function storageKey(projectId: string): string {
  return `${STORAGE_KEY_PREFIX}${projectId}`;
}

/**
 * 将旧版单候选结构迁移为新版多候选结构
 * - 把 content + reason 包装为单个 CandidateOption
 * - 补齐 source 字段（旧数据无来源标记，默认为 ai）
 */
function migrateLegacyItem(item: LegacyDecisionItem): DecisionItem {
  return {
    id: item.id,
    type: item.type,
    title: item.title,
    candidates: [
      {
        id: `${item.id}-legacy`,
        content: item.content,
        pros: [],
        cons: [],
        source: item.reason,
      },
    ],
    selectedCandidateId:
      item.status === "accepted" ? `${item.id}-legacy` : undefined,
    status: item.status,
    createdAt: item.createdAt,
    source: "ai",
  };
}

/**
 * 读取决策项列表（自动迁移旧版数据）
 */
function readItems(projectId: string): DecisionItem[] {
  try {
    const raw = window.localStorage.getItem(storageKey(projectId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // 逐项迁移：检测旧版结构并升级
    return parsed.map((item: DecisionItem | LegacyDecisionItem) =>
      isLegacyDecisionItem(item) ? migrateLegacyItem(item) : item,
    );
  } catch {
    return [];
  }
}

/**
 * 写入决策项列表（同时触发跨标签页同步事件）
 */
function writeItems(projectId: string, items: DecisionItem[]): void {
  try {
    window.localStorage.setItem(storageKey(projectId), JSON.stringify(items));
    // 触发跨标签页同步：DecisionQueuePage 的 useLocalStorage 已监听 storage 事件
    window.dispatchEvent(new StorageEvent("storage", { key: storageKey(projectId) }));
  } catch {
    // 隐私模式或配额超限：静默失败
  }
}

/**
 * 推送决策项输入参数
 * 不含 status/createdAt/source（由 pushDecision 自动填充）
 */
export type PushDecisionInput = Omit<
  DecisionItem,
  "status" | "createdAt" | "source"
> & {
  /** 来源，默认 ai */
  source?: "ai" | "manual";
};

/**
 * 推送一条决策项到队列。已存在相同 id 的项会被跳过（幂等）。
 */
export function pushDecision(projectId: string, item: PushDecisionInput): void {
  const items = readItems(projectId);
  if (items.some((existing) => existing.id === item.id)) return;
  const { source = "ai", ...rest } = item;
  const next: DecisionItem = {
    ...rest,
    status: "pending",
    createdAt: new Date().toISOString(),
    source,
  };
  writeItems(projectId, [next, ...items]);
}

/**
 * 更新决策项状态（作者采纳/忽略/撤销）
 * - accepted/modified 需要提供 selectedCandidateId
 * - 撤销（恢复 pending）会清空 selectedCandidateId 和 decidedAt
 */
export function updateDecisionStatus(
  projectId: string,
  id: string,
  status: DecisionStatus,
  selectedCandidateId?: string,
): void {
  const items = readItems(projectId);
  const next = items.map((item) =>
    item.id === id
      ? {
          ...item,
          status,
          selectedCandidateId:
            status === "pending" ? undefined : selectedCandidateId,
          decidedAt: status === "pending" ? undefined : new Date().toISOString(),
        }
      : item,
  );
  writeItems(projectId, next);
}

/**
 * 更新决策项内容（作者修改后采纳）
 * - 替换选中候选的 content 为新内容
 * - 状态变为 modified
 */
export function modifyDecision(
  projectId: string,
  id: string,
  candidateId: string,
  newContent: string,
): void {
  const items = readItems(projectId);
  const next = items.map((item) =>
    item.id === id
      ? {
          ...item,
          status: "modified" as const,
          selectedCandidateId: candidateId,
          decidedAt: new Date().toISOString(),
          candidates: item.candidates.map((c) =>
            c.id === candidateId ? { ...c, content: newContent } : c,
          ),
        }
      : item,
  );
  writeItems(projectId, next);
}

/**
 * 批量将 pending 标记为 ignored
 */
export function markAllPendingIgnored(projectId: string): void {
  const items = readItems(projectId);
  const now = new Date().toISOString();
  const next = items.map((item) =>
    item.status === "pending"
      ? { ...item, status: "ignored" as const, decidedAt: now }
      : item,
  );
  writeItems(projectId, next);
}

/**
 * 作者自定义决策内容（不采纳任何 AI 候选，自己写一个）
 * - 把自定义内容作为新候选追加到 candidates 列表
 * - 标记为 modified 并选中此自定义候选
 */
export function customAcceptDecision(
  projectId: string,
  id: string,
  customContent: string,
): void {
  const items = readItems(projectId);
  const customCandidateId = `${id}-custom`;
  const next = items.map((item) =>
    item.id === id
      ? {
          ...item,
          status: "modified" as const,
          selectedCandidateId: customCandidateId,
          decidedAt: new Date().toISOString(),
          candidates: [
            ...item.candidates,
            {
              id: customCandidateId,
              content: customContent,
              pros: ["作者自定义方案"],
              cons: [],
            },
          ],
        }
      : item,
  );
  writeItems(projectId, next);
}

/**
 * 删除单条决策项（用于清理历史已决策项）
 */
export function removeDecision(projectId: string, id: string): void {
  const items = readItems(projectId);
  writeItems(projectId, items.filter((item) => item.id !== id));
}

/**
 * 迁移旧版 TodayWorkspacePage 的 ai-decisions 数据到决策队列
 * - 读取旧 key（tame-ink:ai-decisions:{projectId}）
 * - 把每条 Record<key, "adopted" | "ignored"> 转换为决策项
 * - 迁移成功后删除旧 key（避免重复迁移）
 * 注意：此函数应由 TodayWorkspacePage 在首次加载时调用一次
 *
 * @param projectId 项目 ID
 * @param legacyCandidates 旧版候选列表（key + 类型 + 内容）
 */
export function migrateLegacyAiDecisions(
  projectId: string,
  legacyCandidates: Array<{
    key: string;
    type: DecisionType;
    title: string;
    content: string;
    reason?: string;
  }>,
): void {
  try {
    const legacyKey = `${LEGACY_AI_DECISIONS_PREFIX}${projectId}`;
    const raw = window.localStorage.getItem(legacyKey);
    if (!raw) return;
    const legacyMap = JSON.parse(raw) as Record<string, "adopted" | "ignored">;
    if (!legacyMap || typeof legacyMap !== "object") return;

    // 把已决策的旧候选项迁移为决策项
    const existingItems = readItems(projectId);
    const existingIds = new Set(existingItems.map((item) => item.id));
    const newItems: DecisionItem[] = [];

    for (const candidate of legacyCandidates) {
      const state = legacyMap[candidate.key];
      if (!state) continue;
      // 避免重复迁移
      if (existingIds.has(candidate.key)) continue;

      newItems.push({
        id: candidate.key,
        type: candidate.type,
        title: candidate.title,
        candidates: [
          {
            id: `${candidate.key}-legacy`,
            content: candidate.content,
            pros: [],
            cons: [],
            source: candidate.reason,
          },
        ],
        selectedCandidateId:
          state === "adopted" ? `${candidate.key}-legacy` : undefined,
        status: state === "adopted" ? "accepted" : "ignored",
        createdAt: new Date().toISOString(),
        decidedAt: new Date().toISOString(),
        source: "ai",
      });
    }

    if (newItems.length > 0) {
      writeItems(projectId, [...newItems, ...existingItems]);
    }
    // 删除旧 key 完成迁移
    window.localStorage.removeItem(legacyKey);
  } catch {
    // 旧数据解析失败：静默跳过，不影响主流程
  }
}
