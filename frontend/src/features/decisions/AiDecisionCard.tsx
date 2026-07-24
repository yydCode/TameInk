// 通用 AI 决策卡片组件
// 支持：多候选 + 利弊分析 + 单选 + 修改后采纳 + 自定义输入
// 用于 DecisionQueuePage 和各页面就地决策

import { useState } from "react";
import { Check, Clock, Edit2, X } from "lucide-react";
import { Link } from "react-router";

import { DECISION_TYPE_LABELS } from "./constants";
import type { DecisionItem } from "./types";

// 决策状态对应的中文标签
const STATUS_LABELS: Record<DecisionItem["status"], string> = {
  pending: "待处理",
  accepted: "已采纳",
  ignored: "已忽略",
  modified: "已修改",
};

/**
 * 通用 AI 决策卡片
 *
 * 使用方式：
 * 1. 在 DecisionQueuePage 中作为统一渲染入口
 * 2. 在各页面就地决策时也可复用
 *
 * 交互流程：
 * - 默认显示所有候选，作者点击 radio 选中某个候选
 * - 点击"采纳选中"按钮 → 调用 onAccept(selectedCandidateId)
 * - 点击"修改后采纳"按钮 → 展开 textarea 编辑候选内容 → 调用 onModify
 * - 点击"自定义"按钮 → 展开 textarea 输入自定义内容 → 调用 onCustomize
 * - 点击"忽略"按钮 → 调用 onIgnore
 * - 已决策状态显示"撤销"按钮 → 调用 onReopen 恢复 pending
 */
export function AiDecisionCard({
  item,
  onAccept,
  onIgnore,
  onModify,
  onCustomize,
  onReopen,
}: {
  item: DecisionItem;
  onAccept: (candidateId: string) => void;
  onIgnore: () => void;
  onModify: (candidateId: string, newContent: string) => void;
  onCustomize: (customContent: string) => void;
  onReopen: () => void;
}) {
  // 当前选中的候选 ID
  const [selectedId, setSelectedId] = useState<string | undefined>(
    item.selectedCandidateId ?? item.candidates[0]?.id,
  );
  // 是否展开"修改后采纳"编辑器
  const [modifyMode, setModifyMode] = useState(false);
  // 是否展开"自定义输入"编辑器
  const [customMode, setCustomMode] = useState(false);
  // 编辑器内容
  const [editContent, setEditContent] = useState("");
  // 自定义内容
  const [customContent, setCustomContent] = useState("");

  const isDecided = item.status !== "pending";

  // 处理采纳：必须有选中的候选
  function handleAccept() {
    if (!selectedId) return;
    onAccept(selectedId);
  }

  // 处理修改后采纳：基于选中的候选内容预填，作者编辑后提交
  function handleModify() {
    const selected = item.candidates.find((c) => c.id === selectedId);
    if (!selectedId || !selected) return;
    if (modifyMode) {
      // 已展开编辑器：提交修改
      onModify(selectedId, editContent.trim() || selected.content);
      setModifyMode(false);
      setEditContent("");
    } else {
      // 展开编辑器：预填当前候选内容
      setEditContent(selected.content);
      setModifyMode(true);
      setCustomMode(false);
    }
  }

  // 处理自定义输入
  function handleCustomize() {
    if (customMode) {
      // 已展开：提交自定义内容
      const trimmed = customContent.trim();
      if (!trimmed) return;
      onCustomize(trimmed);
      setCustomMode(false);
      setCustomContent("");
    } else {
      // 展开
      setCustomMode(true);
      setModifyMode(false);
    }
  }

  return (
    <article className={`ai-decision-card is-${item.status}`}>
      {/* 卡片头部：标题 + 类型标签 + 状态 + 来源页链接 */}
      <div className="ai-decision-header">
        <div className="ai-decision-title-row">
          <strong>{item.title}</strong>
          <span className={`ai-decision-status is-${item.status}`}>
            {STATUS_LABELS[item.status]}
          </span>
        </div>
        <div className="ai-decision-meta">
          <span className="ai-decision-type">
            {DECISION_TYPE_LABELS[item.type]}
          </span>
          {item.pagePath && (
            <Link to={item.pagePath} className="ai-decision-source">
              在源页处理
            </Link>
          )}
          <span className="ai-decision-time muted">
            {new Date(item.createdAt).toLocaleString("zh-CN")}
          </span>
        </div>
      </div>

      {/* 决策背景说明 */}
      {item.context && (
        <p className="ai-decision-context muted">{item.context}</p>
      )}

      {/* 候选列表 */}
      <div className="ai-candidates">
        {item.candidates.map((candidate) => {
          const isSelected = selectedId === candidate.id;
          const isAccepted =
            isDecided && item.selectedCandidateId === candidate.id;
          return (
            <label
              key={candidate.id}
              className={`ai-candidate ${isSelected ? "is-selected" : ""} ${
                isAccepted ? "is-accepted" : ""
              }`}
            >
              <div className="ai-candidate-radio-row">
                <input
                  type="radio"
                  name={`decision-${item.id}`}
                  checked={isSelected}
                  disabled={isDecided}
                  onChange={() => setSelectedId(candidate.id)}
                />
                <div className="ai-candidate-main">
                  <div className="ai-candidate-content-row">
                    <span className="ai-candidate-content">
                      {candidate.content}
                    </span>
                    {candidate.recommended && (
                      <span className="ai-candidate-badge">推荐</span>
                    )}
                  </div>
                  {(candidate.pros.length > 0 || candidate.cons.length > 0) && (
                    <div className="ai-candidate-pros-cons">
                      {candidate.pros.length > 0 && (
                        <div className="ai-pros">
                          <small>优势：</small>
                          <ul>
                            {candidate.pros.map((pro, i) => (
                              <li key={i}>{pro}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {candidate.cons.length > 0 && (
                        <div className="ai-cons">
                          <small>劣势：</small>
                          <ul>
                            {candidate.cons.map((con, i) => (
                              <li key={i}>{con}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                  {candidate.source && (
                    <p className="ai-candidate-source muted">
                      来源：{candidate.source}
                    </p>
                  )}
                </div>
              </div>
            </label>
          );
        })}
      </div>

      {/* 修改后采纳编辑器 */}
      {modifyMode && (
        <div className="ai-decision-edit">
          <textarea
            className="ai-decision-textarea"
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            rows={4}
            placeholder="编辑候选内容..."
          />
          <div className="ai-decision-edit-actions">
            <button
              className="button button-primary"
              type="button"
              onClick={handleModify}
            >
              确认修改
            </button>
            <button
              className="button button-secondary"
              type="button"
              onClick={() => setModifyMode(false)}
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* 自定义输入编辑器 */}
      {customMode && (
        <div className="ai-decision-edit">
          <textarea
            className="ai-decision-textarea"
            value={customContent}
            onChange={(e) => setCustomContent(e.target.value)}
            rows={4}
            placeholder="输入自定义决策内容..."
          />
          <div className="ai-decision-edit-actions">
            <button
              className="button button-primary"
              type="button"
              onClick={handleCustomize}
              disabled={!customContent.trim()}
            >
              提交自定义
            </button>
            <button
              className="button button-secondary"
              type="button"
              onClick={() => setCustomMode(false)}
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* 操作按钮区 */}
      <div className="ai-decision-actions">
        {!isDecided ? (
          <>
            <button
              className="button button-primary"
              type="button"
              onClick={handleAccept}
              disabled={!selectedId}
            >
              <Check size={13} />
              采纳选中
            </button>
            <button
              className="button button-secondary"
              type="button"
              onClick={handleModify}
              disabled={!selectedId}
            >
              <Edit2 size={13} />
              修改后采纳
            </button>
            <button
              className="button button-secondary"
              type="button"
              onClick={handleCustomize}
            >
              自定义
            </button>
            <button
              className="button button-secondary"
              type="button"
              onClick={onIgnore}
            >
              <X size={13} />
              忽略
            </button>
          </>
        ) : (
          <button
            className="button button-secondary"
            type="button"
            onClick={onReopen}
          >
            <Clock size={13} />
            撤销决策
          </button>
        )}
      </div>
    </article>
  );
}
