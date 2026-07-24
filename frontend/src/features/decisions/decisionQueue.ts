// 决策队列共享 helper：供审查/伏笔/建议等模块推送决策项到 DecisionQueuePage。
// 数据存储于 localStorage，key 为 `tame-ink:decisions:{projectId}`，与 DecisionQueuePage 一致。

export type DecisionType = "audit" | "foreshadow" | "suggestion" | "recommendation";
export type DecisionStatus = "pending" | "accepted" | "ignored";

export interface DecisionItem {
  id: string;
  type: DecisionType;
  title: string;
  content: string;
  reason?: string;
  status: DecisionStatus;
  createdAt: string;
}

const STORAGE_KEY_PREFIX = "tame-ink:decisions:";

function storageKey(projectId: string): string {
  return `${STORAGE_KEY_PREFIX}${projectId}`;
}

function readItems(projectId: string): DecisionItem[] {
  try {
    const raw = window.localStorage.getItem(storageKey(projectId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as DecisionItem[]) : [];
  } catch {
    return [];
  }
}

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
 * 推送一条决策项到队列。已存在相同 id 的项会被跳过（幂等）。
 */
export function pushDecision(
  projectId: string,
  item: Omit<DecisionItem, "status" | "createdAt">,
): void {
  const items = readItems(projectId);
  if (items.some((existing) => existing.id === item.id)) return;
  const next: DecisionItem = {
    ...item,
    status: "pending",
    createdAt: new Date().toISOString(),
  };
  writeItems(projectId, [next, ...items]);
}
