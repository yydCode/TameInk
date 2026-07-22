/**
 * StoryCardPicker — inline card selector shown in the workspace when
 * next_action returns kind:"input" asking the author to pick the current
 * production unit (故事卡). Replaces the redirect to /create.
 *
 * The author sees cards in sequence order, with AI-recommended "current"
 * pre-selected. Confirming the selection calls set_current_story_card,
 * which atomically promotes the chosen card and demotes any previous one.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader } from "lucide-react";

import { listStoryCards, setCurrentStoryCard, type StoryCard } from "../../api/client";
import { queryKeys } from "../../app/queryKeys";

const STATUS_LABELS: Record<StoryCard["status"], string> = {
  planned: "已规划",
  current: "进行中",
  completed: "已完成",
  superseded: "已替换",
};

interface Props {
  projectId: string;
  onActivated: () => void; // called after successful set-current so workspace refreshes
}

export function StoryCardPicker({ projectId, onActivated }: Props) {
  const queryClient = useQueryClient();
  const { data: cards, isLoading } = useQuery({
    queryKey: queryKeys.storyCards(projectId),
    queryFn: () => listStoryCards(projectId),
  });

  // Pre-select: first non-completed, non-superseded card (or the existing current one)
  const recommended = cards?.find(
    (c) => c.status === "current" || c.status === "planned",
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const effectiveId = selectedId ?? recommended?.id ?? null;

  const activate = useMutation({
    mutationFn: (cardId: string) => setCurrentStoryCard(projectId, cardId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.storyCards(projectId) });
      onActivated();
    },
  });

  if (isLoading) {
    return (
      <div className="story-picker-loading">
        <Loader size={16} className="spin" />
        <span>正在加载故事卡…</span>
      </div>
    );
  }

  const selectableCards = cards?.filter(
    (c) => c.status !== "completed" && c.status !== "superseded",
  ) ?? [];

  if (selectableCards.length === 0) {
    return (
      <p className="muted">
        当前没有可用的故事卡。请先执行「滚动故事卡」任务，让 AI 规划下一个叙事单元。
      </p>
    );
  }

  return (
    <div className="story-picker">
      <p className="story-picker-hint">
        接下来写哪个单元？选择后，AI 将围绕它规划章节并生成草稿。
      </p>
      <ol className="story-picker-list">
        {selectableCards.map((card) => {
          const isSelected = effectiveId === card.id;
          const isRecommended = recommended?.id === card.id && card.status !== "current";
          return (
            <li key={card.id}>
              <button
                type="button"
                className={`story-picker-card ${isSelected ? "is-selected" : ""}`}
                onClick={() => setSelectedId(card.id)}
              >
                <div className="story-picker-card-header">
                  <span className="story-picker-sequence">单元 {card.sequence}</span>
                  {isRecommended && <span className="story-picker-badge">AI 推荐</span>}
                  {card.status === "current" && (
                    <span className="story-picker-badge story-picker-badge--current">
                      {STATUS_LABELS.current}
                    </span>
                  )}
                </div>
                <p className="story-picker-goal">{card.goal}</p>
                <p className="story-picker-motivation">{card.motivation}</p>
              </button>
            </li>
          );
        })}
      </ol>
      <button
        type="button"
        className="button button-primary"
        disabled={!effectiveId || activate.isPending}
        onClick={() => effectiveId && activate.mutate(effectiveId)}
      >
        <ArrowRight size={15} />
        {activate.isPending ? "正在激活…" : "就写这个单元 →"}
      </button>
      {activate.error ? (
        <p className="inline-error">{(activate.error as Error).message}</p>
      ) : null}
    </div>
  );
}
