import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock, Target, TrendingUp } from "lucide-react";
import { useParams } from "react-router";

import { listMemory } from "../api/client";
import { queryKeys } from "../app/queryKeys";
import { useLocalStorage } from "../hooks/useLocalStorage";

/**
 * 伏笔回收项
 * 跟踪一条伏笔的回收计划与状态
 */
interface ForeshadowResolution {
  memoryId: string;
  content: string;
  plantedChapter: string; // 铺设章节
  priority: "high" | "medium" | "low";
  status: "pending" | "resolved";
  planToResolve?: string; // 计划如何回收
}

/**
 * 完本规划信息
 * 作者自定义目标与结局设计
 */
interface CompletionPlan {
  targetTotalWords: number; // 目标总字数
  currentWords: number; // 当前字数
  dailyUpdateWords: number; // 日更字数
  endingDesign: string; // 结局设计
  remainingPlots: string; // 剩余剧情
}

// 默认完本规划
const DEFAULT_PLAN: CompletionPlan = {
  targetTotalWords: 1_000_000,
  currentWords: 0,
  dailyUpdateWords: 6000,
  endingDesign: "",
  remainingPlots: "",
};

// 优先级排序权重
const PRIORITY_WEIGHT: Record<ForeshadowResolution["priority"], number> = {
  high: 0,
  medium: 1,
  low: 2,
};

/**
 * 完本规划页面
 * 三个区块：伏笔回收清单 + 完本倒计时 + 结局设计
 */
export function CompletionPage() {
  const { projectId = "" } = useParams();

  // 完本规划信息
  const [plan, setPlan] = useLocalStorage<CompletionPlan>(
    `tame-ink:completion:${projectId}`,
    DEFAULT_PLAN,
  );
  // 伏笔回收状态映射
  const [resolutions, setResolutions] = useLocalStorage<ForeshadowResolution[]>(
    `tame-ink:foreshadow-resolution:${projectId}`,
    [],
  );

  // 拉取伏笔数据
  const memory = useQuery({
    queryKey: queryKeys.memory(projectId),
    queryFn: () => listMemory(projectId),
  });

  // 待回收伏笔（AI 整理）
  const activeForeshadowings = useMemo(
    () =>
      (memory.data ?? []).filter(
        (item) => item.kind === "foreshadowing" && item.status === "active",
      ),
    [memory.data],
  );

  // 合并 AI 数据与本地存储的回收状态
  // 对于新出现的伏笔，自动创建默认项（priority=medium, status=pending）
  const mergedResolutions = useMemo<ForeshadowResolution[]>(() => {
    const byId = new Map(resolutions.map((item) => [item.memoryId, item]));
    return activeForeshadowings.map((memory) => {
      const existing = byId.get(memory.id);
      if (existing) {
        // 同步最新内容（content 可能被 AI 修订过）
        return {
          ...existing,
          content: memory.content ?? memory.quote,
          plantedChapter: existing.plantedChapter || memory.location,
        };
      }
      return {
        memoryId: memory.id,
        content: memory.content ?? memory.quote,
        plantedChapter: memory.location,
        priority: "medium",
        status: "pending",
      };
    });
  }, [activeForeshadowings, resolutions]);

  // 按 priority 排序，pending 优先
  const sortedResolutions = useMemo(
    () =>
      [...mergedResolutions].sort((a, b) => {
        if (a.status !== b.status) {
          return a.status === "pending" ? -1 : 1;
        }
        return PRIORITY_WEIGHT[a.priority] - PRIORITY_WEIGHT[b.priority];
      }),
    [mergedResolutions],
  );

  // 统计数据
  const pendingCount = mergedResolutions.filter(
    (item) => item.status === "pending",
  ).length;
  const resolvedCount = mergedResolutions.length - pendingCount;

  // 预计完本天数（按日更字数）
  const remainingWords = Math.max(0, plan.targetTotalWords - plan.currentWords);
  const estimatedDays =
    plan.dailyUpdateWords > 0
      ? Math.ceil(remainingWords / plan.dailyUpdateWords)
      : 0;

  // 完本进度百分比
  const progressPercent =
    plan.targetTotalWords > 0
      ? Math.min(100, (plan.currentWords / plan.targetTotalWords) * 100)
      : 0;

  // 更新某条伏笔的回收状态
  function updateResolution(memoryId: string, patch: Partial<ForeshadowResolution>) {
    const existing = mergedResolutions.find((item) => item.memoryId === memoryId);
    if (!existing) return;
    const next = resolutions.filter((item) => item.memoryId !== memoryId);
    next.push({ ...existing, ...patch });
    setResolutions(next);
  }

  if (memory.isPending) {
    return <div className="loading-state">读取伏笔数据...</div>;
  }
  if (memory.isError) {
    return (
      <div className="error-state" role="alert">
        伏笔数据读取失败：{memory.error?.message ?? "未知错误"}
      </div>
    );
  }

  return (
    <div className="completion-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">长篇维护</span>
          <h1>完本规划</h1>
          <p>跟踪伏笔回收进度、完本倒计时与结局设计</p>
        </div>
      </header>

      {/* 完本倒计时 */}
      <section className="completion-countdown">
        <div className="section-title">
          <h2><Clock size={15} /> 完本倒计时</h2>
          <span>{progressPercent.toFixed(1)}%</span>
        </div>
        <div className="countdown-stats">
          <div className="stat-card">
            <Target size={16} />
            <div>
              <strong>{plan.targetTotalWords.toLocaleString("zh-CN")}</strong>
              <small>目标总字数</small>
            </div>
          </div>
          <div className="stat-card">
            <TrendingUp size={16} />
            <div>
              <strong>{plan.currentWords.toLocaleString("zh-CN")}</strong>
              <small>当前字数</small>
            </div>
          </div>
          <div className="stat-card">
            <Clock size={16} />
            <div>
              <strong>{plan.dailyUpdateWords.toLocaleString("zh-CN")}</strong>
              <small>日更字数</small>
            </div>
          </div>
          <div className="stat-card stat-card-highlight">
            <CheckCircle2 size={16} />
            <div>
              <strong>{estimatedDays.toLocaleString("zh-CN")}</strong>
              <small>预计还需天数</small>
            </div>
          </div>
        </div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progressPercent}%` }} />
        </div>
        <div className="countdown-inputs">
          <label>
            目标总字数
            <input
              type="number"
              min="0"
              step="10000"
              value={plan.targetTotalWords}
              onChange={(event) =>
                setPlan({ ...plan, targetTotalWords: Math.max(0, Number(event.target.value)) })
              }
            />
          </label>
          <label>
            当前字数
            <input
              type="number"
              min="0"
              step="1000"
              value={plan.currentWords}
              onChange={(event) =>
                setPlan({ ...plan, currentWords: Math.max(0, Number(event.target.value)) })
              }
            />
          </label>
          <label>
            日更字数
            <input
              type="number"
              min="1"
              step="500"
              value={plan.dailyUpdateWords}
              onChange={(event) =>
                setPlan({ ...plan, dailyUpdateWords: Math.max(1, Number(event.target.value)) })
              }
            />
          </label>
        </div>
      </section>

      <div className="workspace-row completion-row">
        {/* 伏笔回收清单 */}
        <section className="list-card foreshadow-resolution-card">
          <div className="section-title">
            <h2>伏笔回收清单</h2>
            <span>待回收 {pendingCount} · 已回收 {resolvedCount}</span>
          </div>
          {sortedResolutions.length === 0 ? (
            <p className="muted">没有待回收的伏笔。</p>
          ) : (
            <ul className="foreshadow-resolution-list">
              {sortedResolutions.map((item) => (
                <li
                  key={item.memoryId}
                  className={`foreshadow-resolution-item is-${item.status} priority-${item.priority}`}
                >
                  <header>
                    <select
                      value={item.priority}
                      onChange={(event) =>
                        updateResolution(item.memoryId, {
                          priority: event.target.value as ForeshadowResolution["priority"],
                        })
                      }
                      aria-label="优先级"
                    >
                      <option value="high">高</option>
                      <option value="medium">中</option>
                      <option value="low">低</option>
                    </select>
                    <small className="muted">铺设：{item.plantedChapter}</small>
                    <button
                      type="button"
                      className="button button-secondary foreshadow-toggle"
                      onClick={() =>
                        updateResolution(item.memoryId, {
                          status: item.status === "pending" ? "resolved" : "pending",
                        })
                      }
                    >
                      {item.status === "pending" ? "标记已回收" : "撤销回收"}
                    </button>
                  </header>
                  <p>{item.content}</p>
                  <textarea
                    value={item.planToResolve ?? ""}
                    onChange={(event) =>
                      updateResolution(item.memoryId, {
                        planToResolve: event.target.value,
                      })
                    }
                    placeholder="计划如何回收这条伏笔？"
                    rows={2}
                  />
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* 结局设计 */}
        <section className="list-card ending-design-card">
          <div className="section-title">
            <h2>结局设计</h2>
            <span>作者自定义</span>
          </div>
          <label>
            剩余剧情
            <textarea
              value={plan.remainingPlots}
              onChange={(event) =>
                setPlan({ ...plan, remainingPlots: event.target.value })
              }
              placeholder="还有哪些主线/支线剧情尚未推进？"
              rows={8}
            />
          </label>
          <label>
            结局设计
            <textarea
              value={plan.endingDesign}
              onChange={(event) =>
                setPlan({ ...plan, endingDesign: event.target.value })
              }
              placeholder="如何收束全书？高潮、反转、留白？"
              rows={8}
            />
          </label>
        </section>
      </div>
    </div>
  );
}
