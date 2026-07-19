import { useMemo } from "react";
import { Check, Clock, ListChecks, X } from "lucide-react";
import { useParams } from "react-router";

import { useLocalStorage } from "../hooks/useLocalStorage";

// 决策项类型
type DecisionType = "audit" | "foreshadow" | "suggestion" | "recommendation";

// 决策项状态
type DecisionStatus = "pending" | "accepted" | "ignored";

// 决策项数据结构（其他页面推送过来，本页面只负责展示与状态管理）
interface DecisionItem {
  id: string;
  type: DecisionType;
  title: string;
  content: string;
  reason?: string;
  status: DecisionStatus;
  createdAt: string;
}

// 类型 -> 中文标题
const TYPE_LABELS: Record<DecisionType, string> = {
  audit: "审查问题",
  foreshadow: "伏笔候选",
  suggestion: "建议",
  recommendation: "推荐",
};

// 状态 -> 中文标签
const STATUS_LABELS: Record<DecisionStatus, string> = {
  pending: "待处理",
  accepted: "已采纳",
  ignored: "已忽略",
};

// 分组展示顺序
const TYPE_ORDER: DecisionType[] = [
  "audit",
  "foreshadow",
  "suggestion",
  "recommendation",
];

/**
 * 决策队列页面
 * 接收来自审查、伏笔、建议等模块的待处理项
 * 作者在此进行采纳/忽略/待处理的状态管理
 */
export function DecisionQueuePage() {
  const { projectId = "" } = useParams();
  const [decisions, setDecisions] = useLocalStorage<DecisionItem[]>(
    `tame-ink:decisions:${projectId}`,
    [],
  );

  // 顶部统计：待处理 / 已采纳 / 已忽略
  const stats = useMemo(() => {
    let pending = 0;
    let accepted = 0;
    let ignored = 0;
    for (const item of decisions) {
      if (item.status === "pending") pending++;
      else if (item.status === "accepted") accepted++;
      else ignored++;
    }
    return { pending, accepted, ignored };
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

  // 更新某项状态
  function setStatus(id: string, status: DecisionStatus) {
    setDecisions(
      decisions.map((item) => (item.id === id ? { ...item, status } : item)),
    );
  }

  // 批量将 pending 标记为 ignored
  function markAllIgnored() {
    setDecisions(
      decisions.map((item) =>
        item.status === "pending" ? { ...item, status: "ignored" } : item,
      ),
    );
  }

  return (
    <section className="decisions-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">决策队列</span>
          <h1>待决策项</h1>
          <p>来自审查、伏笔、建议等模块的待处理项，作者在此进行决策。</p>
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
                <h2>{TYPE_LABELS[type]}</h2>
                <span>{items.length} 项</span>
              </div>
              <div className="decision-list">
                {items.map((item) => (
                  <DecisionCard
                    key={item.id}
                    item={item}
                    onStatusChange={setStatus}
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

/**
 * 单条决策项卡片
 */
function DecisionCard({
  item,
  onStatusChange,
}: {
  item: DecisionItem;
  onStatusChange: (id: string, status: DecisionStatus) => void;
}) {
  return (
    <article className={`decision-item is-${item.status}`}>
      <div className="decision-main">
        <div className="decision-header">
          <strong>{item.title}</strong>
          <span className={`decision-status is-${item.status}`}>
            {STATUS_LABELS[item.status]}
          </span>
        </div>
        <p className="decision-content">{item.content}</p>
        {item.reason && (
          <p className="decision-reason muted">原因：{item.reason}</p>
        )}
        <small className="muted">
          {new Date(item.createdAt).toLocaleString("zh-CN")}
        </small>
      </div>
      <div className="decision-actions">
        <button
          className="button button-primary"
          type="button"
          onClick={() => onStatusChange(item.id, "accepted")}
          disabled={item.status === "accepted"}
        >
          <Check size={13} />
          采纳
        </button>
        <button
          className="button button-secondary"
          type="button"
          onClick={() => onStatusChange(item.id, "ignored")}
          disabled={item.status === "ignored"}
        >
          <X size={13} />
          忽略
        </button>
        <button
          className="button button-secondary"
          type="button"
          onClick={() => onStatusChange(item.id, "pending")}
          disabled={item.status === "pending"}
        >
          <Clock size={13} />
          待处理
        </button>
      </div>
    </article>
  );
}
