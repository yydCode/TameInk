import { useMemo } from "react";
import { ListChecks } from "lucide-react";
import { useParams } from "react-router";

import { AiDecisionCard } from "../features/decisions/AiDecisionCard";
import {
  type DecisionItem,
  type DecisionType,
  customAcceptDecision,
  markAllPendingIgnored,
  modifyDecision,
  updateDecisionStatus,
} from "../features/decisions/decisionQueue";
import { DECISION_TYPE_LABELS } from "../features/decisions/constants";
import { useLocalStorage } from "../hooks/useLocalStorage";

// 按类型分组展示顺序（与 DecisionType 一致）
const TYPE_ORDER: DecisionType[] = [
  "audit",
  "foreshadow",
  "suggestion",
  "recommendation",
  "commercial_profile",
  "memory_candidate",
  "character",
  "book_title",
  "opening_beat",
  "batch_plan",
];

/**
 * 决策队列页面
 *
 * 接收来自审查、伏笔、建议、商业定位等模块的待处理项
 * 作者在此进行集中决策（采纳某候选 / 修改后采纳 / 自定义 / 忽略）
 *
 * 数据来源：localStorage `tame-ink:decisions:{projectId}`
 * 与各页面就地决策共用同一份数据，跨标签页实时同步
 */
export function DecisionQueuePage() {
  const { projectId = "" } = useParams();
  const [decisions, setDecisions] = useLocalStorage<DecisionItem[]>(
    `tame-ink:decisions:${projectId}`,
    [],
  );

  // 顶部统计：待处理 / 已采纳 / 已忽略 / 已修改
  const stats = useMemo(() => {
    const result = { pending: 0, accepted: 0, ignored: 0, modified: 0 };
    for (const item of decisions) {
      result[item.status]++;
    }
    return result;
  }, [decisions]);

  // 按类型分组
  const groups = useMemo(() => {
    const map = new Map<DecisionType, DecisionItem[]>();
    for (const type of TYPE_ORDER) map.set(type, []);
    for (const item of decisions) {
      map.get(item.type)?.push(item);
    }
    return map;
  }, [decisions]);

  // 采纳某个候选
  function handleAccept(id: string, candidateId: string) {
    updateDecisionStatus(projectId, id, "accepted", candidateId);
    // 同步本地 state（useLocalStorage 不会感知外部写入，需要重新读取）
    refreshFromStorage();
  }

  // 忽略整条
  function handleIgnore(id: string) {
    updateDecisionStatus(projectId, id, "ignored");
    refreshFromStorage();
  }

  // 修改后采纳
  function handleModify(id: string, candidateId: string, newContent: string) {
    // 复用 decisionQueue.ts 中的 modifyDecision：替换候选内容并标记 modified
    modifyDecision(projectId, id, candidateId, newContent);
    refreshFromStorage();
  }

  // 自定义不采纳任何候选，把自定义内容作为新候选加入并标记 modified
  function handleCustomize(id: string, customContent: string) {
    customAcceptDecision(projectId, id, customContent);
    refreshFromStorage();
  }

  // 撤销决策（恢复 pending）
  function handleReopen(id: string) {
    updateDecisionStatus(projectId, id, "pending");
    refreshFromStorage();
  }

  // 批量将 pending 标记为 ignored
  function markAllIgnored() {
    markAllPendingIgnored(projectId);
    refreshFromStorage();
  }

  // 从 localStorage 重新读取（因为 decisionQueue 直接写入了 localStorage）
  function refreshFromStorage() {
    try {
      const raw = window.localStorage.getItem(`tame-ink:decisions:${projectId}`);
      setDecisions(raw ? (JSON.parse(raw) as DecisionItem[]) : []);
    } catch {
      // 静默失败
    }
  }

  return (
    <section className="decisions-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">决策队列</span>
          <h1>待决策项</h1>
          <p>
            来自审查、伏笔、建议、商业定位等模块的 AI 候选项。
            每项提供多个候选方案与利弊分析，作者决定是否采纳。
          </p>
        </div>
        <button
          className="button button-secondary"
          type="button"
          onClick={markAllIgnored}
          disabled={stats.pending === 0}
        >
          <ListChecks size={15} />
          批量标记已处理
        </button>
      </header>

      {/* 顶部统计 */}
      <div className="decisions-stats">
        <span>
          待处理 <strong>{stats.pending}</strong> 项
        </span>
        <span>
          已采纳 <strong>{stats.accepted}</strong> 项
        </span>
        <span>
          已修改 <strong>{stats.modified}</strong> 项
        </span>
        <span>
          已忽略 <strong>{stats.ignored}</strong> 项
        </span>
      </div>

      {/* 列表或空态 */}
      {decisions.length === 0 ? (
        <div className="empty-state">
          <h1>暂无待处理项</h1>
          <p>审查和伏笔模块推送的决策项会显示在这里。</p>
        </div>
      ) : (
        TYPE_ORDER.map((type) => {
          const items = groups.get(type) ?? [];
          if (items.length === 0) return null;
          return (
            <section key={type} className="decisions-group">
              <div className="section-title">
                <h2>{DECISION_TYPE_LABELS[type]}</h2>
                <span>{items.length} 项</span>
              </div>
              <div className="decision-list">
                {items.map((item) => (
                  <AiDecisionCard
                    key={item.id}
                    item={item}
                    onAccept={(candidateId) => handleAccept(item.id, candidateId)}
                    onIgnore={() => handleIgnore(item.id)}
                    onModify={(candidateId, newContent) =>
                      handleModify(item.id, candidateId, newContent)
                    }
                    onCustomize={(customContent) =>
                      handleCustomize(item.id, customContent)
                    }
                    onReopen={() => handleReopen(item.id)}
                  />
                ))}
              </div>
            </section>
          );
        })
      )}
    </section>
  );
}
