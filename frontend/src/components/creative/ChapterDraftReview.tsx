/**
 * ChapterDraftReview — paragraph-level review UI for chapter_draft artifacts.
 *
 * The author reviews each paragraph individually: accept, reject, or inline-edit.
 * When they submit, the component assembles the final markdown from accepted
 * (and possibly edited) paragraphs and triggers the decision callback.
 *
 * Persistence: the stored artifact payload always contains the full
 * AI-generated markdown. When the author edits paragraphs, the merged result
 * is sent as `content_override` on a `mix` decision, so the canon receives the
 * author's edited text rather than the raw candidate. When the author accepts
 * paragraphs without edits, a plain `accept` promotes the original candidate.
 */

import { useCallback, useMemo, useReducer } from "react";
import { Check, Edit3, RotateCcw, X } from "lucide-react";

import type { CreativeArtifact, SkillExecutionResult } from "../../api/client";

// ── Types ─────────────────────────────────────────────────────────────────

type ParagraphStatus = "pending" | "accepted" | "rejected" | "editing";

interface ParagraphState {
  original: string;
  edited: string;
  status: ParagraphStatus;
}

type ReviewAction =
  | { type: "accept"; index: number }
  | { type: "reject"; index: number }
  | { type: "startEdit"; index: number }
  | { type: "updateEdit"; index: number; text: string }
  | { type: "confirmEdit"; index: number }
  | { type: "reset"; index: number }
  | { type: "acceptAll" }
  | { type: "rejectAll" };

interface ReviewState {
  paragraphs: ParagraphState[];
}

// ── Reducer ───────────────────────────────────────────────────────────────

function reviewReducer(state: ReviewState, action: ReviewAction): ReviewState {
  const update = (
    index: number,
    patch: Partial<ParagraphState>,
  ): ReviewState => ({
    paragraphs: state.paragraphs.map((p, i) => (i === index ? { ...p, ...patch } : p)),
  });

  switch (action.type) {
    case "accept":
      return update(action.index, { status: "accepted" });
    case "reject":
      return update(action.index, { status: "rejected" });
    case "startEdit":
      return update(action.index, { status: "editing" });
    case "updateEdit":
      return update(action.index, { edited: action.text });
    case "confirmEdit":
      return update(action.index, {
        status: action.index < state.paragraphs.length ? "accepted" : "pending",
      });
    case "reset":
      return update(action.index, {
        status: "pending",
        edited: state.paragraphs[action.index].original,
      });
    case "acceptAll":
      return {
        paragraphs: state.paragraphs.map((p) =>
          p.status !== "rejected" ? { ...p, status: "accepted" } : p,
        ),
      };
    case "rejectAll":
      return {
        paragraphs: state.paragraphs.map((p) => ({ ...p, status: "rejected" })),
      };
    default:
      return state;
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────

function splitMarkdown(markdown: string): string[] {
  return markdown
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);
}

function buildMergedMarkdown(paragraphs: ParagraphState[]): string {
  return paragraphs
    .filter((p) => p.status === "accepted")
    .map((p) => p.edited || p.original)
    .join("\n\n");
}

function countBy(paragraphs: ParagraphState[], status: ParagraphStatus): number {
  return paragraphs.filter((p) => p.status === status).length;
}

// ── Component ─────────────────────────────────────────────────────────────

interface Props {
  artifact: CreativeArtifact;
  result: SkillExecutionResult;
  isPending: boolean;
  onDecide: (
    action: "accept" | "reject" | "mix",
    rationale: string,
    contentOverride?: string,
  ) => void;
}

export function ChapterDraftReview({ artifact, result, isPending, onDecide }: Props) {
  const rawMarkdown = (result.candidate?.payload as { markdown?: string })?.markdown ?? "";

  const initialState = useMemo<ReviewState>(
    () => ({
      paragraphs: splitMarkdown(rawMarkdown).map((text) => ({
        original: text,
        edited: text,
        status: "pending" as ParagraphStatus,
      })),
    }),
    [rawMarkdown],
  );

  const [state, dispatch] = useReducer(reviewReducer, initialState);
  const { paragraphs } = state;

  const accepted = countBy(paragraphs, "accepted");
  const rejected = countBy(paragraphs, "rejected");
  const pending = countBy(paragraphs, "pending") + countBy(paragraphs, "editing");
  const hasEdits = paragraphs.some((p) => p.status === "accepted" && p.edited !== p.original);
  const canSubmit = accepted > 0;

  const handleSubmit = useCallback(() => {
    const merged = buildMergedMarkdown(paragraphs);
    const stats = `已接受 ${accepted} 段，已拒绝 ${rejected} 段，待处理 ${pending} 段。`;
    const action = hasEdits ? "mix" : "accept";
    const rationale = hasEdits
      ? `作者修改并合并了部分段落后确认。${stats}`
      : `作者逐段审阅后确认所有接受段落。${stats}`;
    // 有修改时走 mix，并把合并后的正文作为 content_override 写入正式故事；
    // 无修改时走 accept，沿用原始候选正文。
    onDecide(action, rationale, hasEdits ? merged : undefined);
  }, [paragraphs, accepted, rejected, pending, hasEdits, onDecide]);

  const handleRejectAll = () => {
    dispatch({ type: "rejectAll" });
    onDecide("reject", "作者拒绝全部段落，需重新生成。");
  };

  if (!rawMarkdown) {
    return (
      <p className="muted">该候选没有章节正文。</p>
    );
  }

  return (
    <div className="chapter-draft-review">
      {/* ── Stats bar ─────────────────────────────────────────── */}
      <div className="review-stats">
        <span className="review-stat review-stat--accepted">
          <Check size={12} /> {accepted} 接受
        </span>
        <span className="review-stat review-stat--rejected">
          <X size={12} /> {rejected} 拒绝
        </span>
        <span className="review-stat review-stat--pending">
          {pending} 待定
        </span>
        <div className="review-stats-actions">
          <button
            type="button"
            className="button-text"
            onClick={() => dispatch({ type: "acceptAll" })}
          >
            全部接受
          </button>
        </div>
      </div>

      {/* ── Paragraph list ────────────────────────────────────── */}
      <ol className="paragraph-list">
        {paragraphs.map((para, index) => (
          <ParagraphItem
            key={index}
            index={index}
            para={para}
            dispatch={dispatch}
          />
        ))}
      </ol>

      {/* ── Submit bar ────────────────────────────────────────── */}
      <div className="review-submit-bar">
        <button
          type="button"
          className="button button-primary"
          onClick={handleSubmit}
          disabled={isPending || !canSubmit}
          title={canSubmit ? undefined : "至少接受一段才能提交"}
        >
          <Check size={15} />
          {hasEdits ? "提交修改版（mix）" : "确认接受段落"}
          {accepted > 0 ? ` · ${accepted} 段` : ""}
        </button>
        <button
          type="button"
          className="button button-secondary"
          onClick={handleRejectAll}
          disabled={isPending}
        >
          <X size={15} />
          全部拒绝，重新生成
        </button>
      </div>

      {artifact.status === "awaiting_approval" && (
        <p className="review-note muted">
          章节草稿共 {paragraphs.length} 段。逐段审阅后点击提交。
          {hasEdits ? " 你已修改了部分段落，将以 mix 动作记录。" : ""}
        </p>
      )}
    </div>
  );
}

// ── ParagraphItem ──────────────────────────────────────────────────────────

interface ParagraphItemProps {
  index: number;
  para: ParagraphState;
  dispatch: React.Dispatch<ReviewAction>;
}

function ParagraphItem({ index, para, dispatch }: ParagraphItemProps) {
  const isTitle = para.original.startsWith("#");

  return (
    <li className={`paragraph-item paragraph-item--${para.status}`}>
      {/* Content */}
      {para.status === "editing" ? (
        <textarea
          className="paragraph-edit-textarea"
          value={para.edited}
          onChange={(e) =>
            dispatch({ type: "updateEdit", index, text: e.target.value })
          }
          rows={Math.max(3, para.edited.split("\n").length + 1)}
          autoFocus
        />
      ) : (
        <p className={`paragraph-text ${isTitle ? "paragraph-text--title" : ""}`}>
          {para.edited || para.original}
          {para.edited !== para.original && para.status === "accepted" && (
            <span className="paragraph-edited-badge">已改</span>
          )}
        </p>
      )}

      {/* Controls */}
      <div className="paragraph-controls">
        {para.status === "editing" ? (
          <>
            <button
              type="button"
              className="para-btn para-btn--accept"
              onClick={() => dispatch({ type: "confirmEdit", index })}
              title="确认修改"
            >
              <Check size={12} /> 确认
            </button>
            <button
              type="button"
              className="para-btn para-btn--neutral"
              onClick={() => dispatch({ type: "reset", index })}
              title="放弃修改"
            >
              <RotateCcw size={12} />
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className={`para-btn ${para.status === "accepted" ? "para-btn--accept para-btn--active" : "para-btn--accept"}`}
              onClick={() => dispatch({ type: "accept", index })}
              title="接受此段"
            >
              <Check size={12} />
            </button>
            <button
              type="button"
              className="para-btn para-btn--edit"
              onClick={() => dispatch({ type: "startEdit", index })}
              title="改写此段"
            >
              <Edit3 size={12} />
            </button>
            <button
              type="button"
              className={`para-btn ${para.status === "rejected" ? "para-btn--reject para-btn--active" : "para-btn--reject"}`}
              onClick={() => dispatch({ type: "reject", index })}
              title="拒绝此段"
            >
              <X size={12} />
            </button>
            {para.status !== "pending" && (
              <button
                type="button"
                className="para-btn para-btn--neutral"
                onClick={() => dispatch({ type: "reset", index })}
                title="重置"
              >
                <RotateCcw size={12} />
              </button>
            )}
          </>
        )}
      </div>
    </li>
  );
}
