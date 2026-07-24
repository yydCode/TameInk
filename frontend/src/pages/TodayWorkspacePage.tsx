import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, History, Plus, RefreshCw, X } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router";

import {
  type DiagnosticResult,
  type Suggestion,
  getCommercialMetrics,
  getProjectUsage,
  listMemory,
  listSuggestions,
  runDiagnostics,
} from "../api/client";
import { queryKeys } from "../app/queryKeys";
import { useLocalStorage } from "../hooks/useLocalStorage";
import {
  type DecisionItem,
  pushDecision,
  updateDecisionStatus,
} from "../features/decisions/decisionQueue";
import { useProjectWorkspace } from "../features/workspace/useProjectWorkspace";

// 作者自定义数据类型
interface TodoItem {
  id: string;
  text: string;
  done: boolean;
}

interface DailyGoal {
  date: string; // YYYY-MM-DD
  targetWords: number;
  writtenWords: number;
}

interface Stockpile {
  chapters: number;
  dailyUpdateChapters: number; // 每日更新章节数
}

// AI 决策统一进入决策队列（features/decisions/decisionQueue.ts）
// 旧的 tame-ink:ai-decisions:${projectId} localStorage 已废弃，首次加载时自动迁移

// 写作统计：每日字数记录 + 今日写作时长
interface WritingStats {
  dailyWords: Record<string, number>; // key: YYYY-MM-DD，value: 当日字数
  todayMinutes: number; // 今日写作时长（分钟），用于计算平均时速
}

// 生成诊断项的稳定 key（基于类型 + 对象）
function diagnosticKey(item: DiagnosticResult): string {
  return `d:${item.diagnostic_type}:${item.target}`;
}

// 生成建议项的稳定 key（基于类型 + 内容前 40 字）
function suggestionKey(item: Suggestion): string {
  return `s:${item.type}:${item.content.slice(0, 40)}`;
}

// 诊断类型中文标签
function diagnosticTypeLabel(type: DiagnosticResult["diagnostic_type"]): string {
  switch (type) {
    case "data":
      return "数据";
    case "plot":
      return "剧情";
    case "foreshadowing":
      return "伏笔";
  }
}

// 建议类型中文标签
function suggestionTypeLabel(type: Suggestion["type"]): string {
  switch (type) {
    case "planning":
      return "规划";
    case "optimization":
      return "优化";
    case "foreshadow":
      return "伏笔";
    case "material":
      return "素材";
  }
}

// 优先级中文标签
function priorityLabel(priority: Suggestion["priority"]): string {
  switch (priority) {
    case "low":
      return "低";
    case "medium":
      return "中";
    case "high":
      return "高";
  }
}

// 计算最近 N 天的日期列表（YYYY-MM-DD，按时间正序）
function recentDays(count: number): string[] {
  const days: string[] = [];
  const now = new Date();
  for (let i = count - 1; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(now.getDate() - i);
    days.push(d.toISOString().slice(0, 10));
  }
  return days;
}

// 计算连续更新天数（从今日向前数；今天没写不算中断，昨天起没写即中断）
function streakDays(dailyWords: Record<string, number>): number {
  let streak = 0;
  const now = new Date();
  for (let i = 0; i < 365; i++) {
    const d = new Date(now);
    d.setDate(now.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    const words = dailyWords[key] ?? 0;
    if (words > 0) {
      streak++;
    } else if (i > 0) {
      // i=0（今天）没写不中断；i>=1（昨天起）没写即中断
      break;
    }
  }
  return streak;
}

// 计算本周字数（最近 7 天之和）
function weekWords(dailyWords: Record<string, number>): number {
  return recentDays(7).reduce((sum, date) => sum + (dailyWords[date] ?? 0), 0);
}

// 计算本月字数（当月所有日字数之和）
function monthWords(dailyWords: Record<string, number>): number {
  const now = new Date();
  const prefix = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  return Object.entries(dailyWords)
    .filter(([date]) => date.startsWith(prefix))
    .reduce((sum, [, words]) => sum + words, 0);
}

/**
 * 今日工作台
 * 替代原来的项目概览，作为进入项目的默认页面
 *
 * 设计原则：人决策、AI 执行
 * - 作者自定义数据（目标、存稿、待办）由作者输入
 * - AI 只整理和呈现已有数据（伏笔、章节、指标）
 * - 每个 AI 呈现的数据都有"作者决策"入口
 */
export function TodayWorkspacePage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const { project, snapshot, workflow } = useProjectWorkspace(projectId);

  // 作者自定义数据（localStorage）
  const today = new Date().toISOString().slice(0, 10);
  const [dailyGoal, setDailyGoal] = useLocalStorage<DailyGoal>(
    `tame-ink:daily-goal:${projectId}`,
    { date: today, targetWords: 6000, writtenWords: 0 },
  );
  const [stockpile, setStockpile] = useLocalStorage<Stockpile>(
    `tame-ink:stockpile:${projectId}`,
    { chapters: 0, dailyUpdateChapters: 2 },
  );
  const [todos, setTodos] = useLocalStorage<TodoItem[]>(
    `tame-ink:todos:${projectId}`,
    [],
  );
  // 写作统计：每日字数记录 + 今日写作时长（作者自定义，AI 不干预）
  const [writingStats, setWritingStats] = useLocalStorage<WritingStats>(
    `tame-ink:writing-stats:${projectId}`,
    { dailyWords: {}, todayMinutes: 60 },
  );
  // AI 决策统一进入决策队列（与 DecisionQueuePage 共用同一份数据）
  const [decisions, setDecisions] = useLocalStorage<DecisionItem[]>(
    `tame-ink:decisions:${projectId}`,
    [],
  );

  // 如果日期变了，重置今日已写
  if (dailyGoal.date !== today) {
    setDailyGoal({ ...dailyGoal, date: today, writtenWords: 0 });
  }

  // 同步今日已写字数到每日记录（用于本周/本月统计与 7 天打卡）
  useEffect(() => {
    if (dailyGoal.writtenWords <= 0) return;
    setWritingStats((prev) => {
      if (prev.dailyWords[today] === dailyGoal.writtenWords) return prev;
      return {
        ...prev,
        dailyWords: { ...prev.dailyWords, [today]: dailyGoal.writtenWords },
      };
    });
  }, [dailyGoal.writtenWords, today, setWritingStats]);

  // 获取伏笔数据（AI 整理）
  const memory = useQuery({
    queryKey: queryKeys.memory(projectId),
    queryFn: () => listMemory(projectId),
  });
  // 获取商业数据（AI 整理）
  const metrics = useQuery({
    queryKey: ["commercial-metrics", projectId],
    queryFn: () => getCommercialMetrics(projectId),
  });
  const usage = useQuery({
    queryKey: queryKeys.usage(projectId),
    queryFn: () => getProjectUsage(projectId),
  });
  // AI 诊断（候选，作者决策）
  // enabled: false —— 默认不自动运行，由作者点击"运行诊断"按钮触发 refetch
  // retry: false —— 失败不重试，UI 显示"诊断服务暂不可用"
  const diagnostics = useQuery({
    queryKey: queryKeys.diagnostics(projectId),
    queryFn: () => runDiagnostics(projectId),
    enabled: false,
    retry: false,
  });
  // AI 建议列表（候选，作者决策）
  const suggestions = useQuery({
    queryKey: queryKeys.suggestions(projectId),
    queryFn: () => listSuggestions(projectId),
    retry: false,
  });

  // 计算下一章信息
  const chapters = useMemo(
    () => [
      ...(snapshot.data?.volumes.flatMap((volume) => volume.chapters) ?? []),
      ...(snapshot.data?.unassigned_chapters ?? []),
    ],
    [snapshot.data],
  );
  const maxChapter = Math.max(0, ...chapters.map((chapter) => Number(chapter.id)).filter(Number.isFinite));
  const nextChapterId = String(maxChapter + 1);
  const nextChapterTitle = chapters.at(-1)?.title ?? "开始第一章";

  // 计算"下一步"引导（AI 整理，作者决策）
  const nextStep = useMemo(() => {
    if (!workflow.data || !snapshot.data) return null;
    if (!workflow.data.setting_confirmed) return ["确认故事设定", "story"];
    if (!workflow.data.commercial_confirmed) return ["确认商业定位", "commercial"];
    if (!workflow.data.outline_confirmed) return ["确认全书大纲", "story"];
    if (!workflow.data.volume_one_confirmed) return ["规划一个分卷", "story"];
    return [snapshot.data.stats.chapter_count ? "继续写下一章" : "开始第一章", "chapters"];
  }, [workflow.data, snapshot.data]);

  // 活跃伏笔列表（AI 整理）
  const activeForeshadowings = useMemo(
    () => (memory.data ?? []).filter((item) => item.kind === "foreshadowing" && item.status === "active"),
    [memory.data],
  );

  // 最近 5 章
  const recentChapters = useMemo(
    () => [...chapters].reverse().slice(0, 5),
    [chapters],
  );

  // 今日进度百分比
  const progressPercent = dailyGoal.targetWords > 0
    ? Math.min(100, (dailyGoal.writtenWords / dailyGoal.targetWords) * 100)
    : 0;

  // 存稿可撑天数
  const stockpileDays = stockpile.dailyUpdateChapters > 0
    ? Math.floor(stockpile.chapters / stockpile.dailyUpdateChapters)
    : 0;

  // 从 localStorage 重新读取决策队列（pushDecision 直接写入了 localStorage）
  // 用 useCallback 包裹以保证 useEffect 依赖稳定
  const refreshDecisions = useCallback(() => {
    try {
      const raw = window.localStorage.getItem(`tame-ink:decisions:${projectId}`);
      setDecisions(raw ? (JSON.parse(raw) as DecisionItem[]) : []);
    } catch {
      // 静默失败
    }
  }, [projectId, setDecisions]);

  // 把诊断/建议候选项推送到决策队列（幂等：相同 id 不会重复推送）
  // 数据加载后调用，让作者可以在 DecisionQueuePage 或本页就地决策
  useEffect(() => {
    if (!diagnostics.data) return;
    for (const item of diagnostics.data) {
      const id = diagnosticKey(item);
      pushDecision(projectId, {
        id,
        type: "suggestion",
        title: `[诊断] ${diagnosticTypeLabel(item.diagnostic_type)}：${item.target}`,
        context: item.conclusion,
        candidates: [
          {
            id: `${id}-c1`,
            content: item.possible_causes.length > 0
              ? `可能原因：${item.possible_causes.join("、")}`
              : "采纳此诊断结论",
            pros: [],
            cons: [],
            source: `严重度：${item.severity}`,
          },
        ],
        pagePath: `/projects/${projectId}/today`,
      });
    }
    // 触发本地 state 刷新（pushDecision 直接写入了 localStorage）
    refreshDecisions();
  }, [diagnostics.data, projectId, refreshDecisions]);

  useEffect(() => {
    if (!suggestions.data) return;
    for (const item of suggestions.data) {
      const id = suggestionKey(item);
      pushDecision(projectId, {
        id,
        type: "suggestion",
        title: `[建议] ${suggestionTypeLabel(item.type)}：${item.content.slice(0, 30)}`,
        context: item.content,
        candidates: [
          {
            id: `${id}-c1`,
            content: item.content,
            pros: [`优先级：${priorityLabel(item.priority)}`],
            cons: [],
            source: item.reason,
          },
        ],
        pagePath: `/projects/${projectId}/today`,
      });
    }
    refreshDecisions();
  }, [suggestions.data, projectId, refreshDecisions]);

  // 作者对某条 AI 候选做决策：state 为 undefined 时表示撤销决策
  function handleAiDecide(key: string, state: "accepted" | "ignored" | undefined) {
    if (state === undefined) {
      updateDecisionStatus(projectId, key, "pending");
    } else {
      updateDecisionStatus(projectId, key, state, `${key}-c1`);
    }
    refreshDecisions();
  }

  // 查询某条候选项的决策状态
  function getDecisionState(key: string): "pending" | "accepted" | "ignored" | "modified" | undefined {
    const item = decisions.find((d) => d.id === key);
    return item?.status;
  }

  // 平均时速（字/小时）= 今日字数 / 今日写作小时数
  const wordsPerHour = writingStats.todayMinutes > 0
    ? Math.round(dailyGoal.writtenWords / (writingStats.todayMinutes / 60))
    : 0;

  // 最近 7 天日期列表（用于打卡显示）
  const calendarDays = useMemo(() => recentDays(7), []);
  // 连续更新天数
  const streak = useMemo(
    () => streakDays(writingStats.dailyWords),
    [writingStats.dailyWords],
  );

  if (project.isPending || snapshot.isPending)
    return <div className="loading-state">读取今日工作台...</div>;
  if (!project.data || !snapshot.data)
    return <div className="error-state" role="alert">作品数据读取失败</div>;

  return (
    <div className="today-workspace">
      <header className="project-heading">
        <div>
          <span className="eyebrow">今日工作台</span>
          <h1>{project.data.title}</h1>
          <p>
            {project.data.genre ?? "未设置题材"} ·{" "}
            第 {maxChapter} 章 ·{" "}
            已写 {snapshot.data.stats.total_words.toLocaleString("zh-CN")} 字
          </p>
        </div>
        <div className="header-actions">
          <Link className="button button-secondary" to={`/projects/${projectId}/overview`}>
            <History size={15} />
            作品概览
          </Link>
          <a
            className="button button-secondary"
            href={`/api/projects/${projectId}/exports/project.zip`}
          >
            导出作品
          </a>
        </div>
      </header>

      {/* 今日写作进度（作者设定目标，AI 呈现进度） */}
      <section className="progress-card">
        <div className="progress-header">
          <h2>今日写作进度</h2>
          <div className="progress-stats">
            <span>目标 <strong>{dailyGoal.targetWords.toLocaleString("zh-CN")}</strong> 字</span>
            <span>已完成 <strong>{dailyGoal.writtenWords.toLocaleString("zh-CN")}</strong> 字</span>
            <span>{progressPercent.toFixed(0)}%</span>
          </div>
        </div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progressPercent}%` }} />
        </div>
        <div className="progress-actions">
          <label className="progress-input">
            <span>调整目标</span>
            <input
              type="number"
              min="0"
              step="500"
              value={dailyGoal.targetWords}
              onChange={(event) =>
                setDailyGoal({ ...dailyGoal, targetWords: Math.max(0, Number(event.target.value)) })
              }
            />
          </label>
          <label className="progress-input">
            <span>更新已写</span>
            <input
              type="number"
              min="0"
              step="100"
              value={dailyGoal.writtenWords}
              onChange={(event) =>
                setDailyGoal({ ...dailyGoal, writtenWords: Math.max(0, Number(event.target.value)) })
              }
            />
          </label>
        </div>
      </section>

      {/* C2：写作统计（节奏管理）——今日字数 / 本周字数 / 本月字数 / 平均时速 / 7 天打卡 / 连续天数 */}
      <section className="stats-card">
        <div className="section-title">
          <h2>写作统计</h2>
          <span>节奏管理</span>
        </div>
        <div className="stats-grid">
          <div className="stats-item">
            <small>今日字数</small>
            <strong>{dailyGoal.writtenWords.toLocaleString("zh-CN")}</strong>
          </div>
          <div className="stats-item">
            <small>本周字数</small>
            <strong>{weekWords(writingStats.dailyWords).toLocaleString("zh-CN")}</strong>
          </div>
          <div className="stats-item">
            <small>本月字数</small>
            <strong>{monthWords(writingStats.dailyWords).toLocaleString("zh-CN")}</strong>
          </div>
          <div className="stats-item">
            <small>平均时速</small>
            <strong>{wordsPerHour.toLocaleString("zh-CN")} 字/时</strong>
          </div>
        </div>
        <div className="stats-calendar">
          <div className="stats-calendar-row">
            <small>最近 7 天</small>
            <div className="stats-dots">
              {calendarDays.map((date) => {
                const words = writingStats.dailyWords[date] ?? 0;
                const isToday = date === today;
                return (
                  <span
                    key={date}
                    className={`stats-dot${words > 0 ? " is-active" : ""}${isToday ? " is-today" : ""}`}
                    title={`${date}：${words.toLocaleString("zh-CN")} 字`}
                  >
                    {date.slice(5)}
                  </span>
                );
              })}
            </div>
            <small>
              连续更新 <strong>{streak}</strong> 天
            </small>
          </div>
          <label className="stats-minutes">
            <span>今日写作时长（分钟）</span>
            <input
              type="number"
              min="0"
              step="10"
              value={writingStats.todayMinutes}
              onChange={(event) =>
                setWritingStats({
                  ...writingStats,
                  todayMinutes: Math.max(0, Number(event.target.value)),
                })
              }
            />
          </label>
        </div>
      </section>

      {/* 下一章 + 存稿情况（两列） */}
      <div className="workspace-row">
        <section className="action-card">
          <h2>下一章</h2>
          <div className="action-card-body">
            <strong>第 {nextChapterId} 章</strong>
            <span className="muted">{nextChapterTitle}</span>
          </div>
          <button
            className="button button-primary"
            type="button"
            onClick={() => navigate(`/projects/${projectId}/chapters/${nextChapterId}`)}
          >
            开始写作 <ArrowRight size={15} />
          </button>
        </section>

        <section className="action-card">
          <h2>存稿情况</h2>
          <div className="action-card-body">
            <strong>{stockpile.chapters} 章</strong>
            {stockpileDays > 0 && (
              <span className="muted">按日更 {stockpile.dailyUpdateChapters} 章可撑 {stockpileDays} 天</span>
            )}
            {stockpileDays > 0 && stockpileDays <= 3 && (
              <span className="stockpile-warning">⚠️ 存稿不足，建议补充</span>
            )}
          </div>
          {/* 存稿预警线：3 天为预警线，存稿 < 3 天时整条进度条变红 */}
          <div className="stockpile-meter">
            <div
              className={`stockpile-meter-fill${stockpileDays < 3 ? " is-warning" : ""}`}
              style={{ width: `${Math.min(100, (stockpileDays / 10) * 100)}%` }}
            />
            <span
              className="stockpile-meter-warnline"
              style={{ left: `${(3 / 10) * 100}%` }}
              title="预警线：3 天"
            />
            <small className="stockpile-meter-label">
              预警线 3 天 · 当前 {stockpileDays} 天
            </small>
          </div>
          <div className="stockpile-inputs">
            <label>
              存稿数
              <input
                type="number"
                min="0"
                value={stockpile.chapters}
                onChange={(event) =>
                  setStockpile({ ...stockpile, chapters: Math.max(0, Number(event.target.value)) })
                }
              />
            </label>
            <label>
              日更章数
              <input
                type="number"
                min="1"
                value={stockpile.dailyUpdateChapters}
                onChange={(event) =>
                  setStockpile({ ...stockpile, dailyUpdateChapters: Math.max(1, Number(event.target.value)) })
                }
              />
            </label>
          </div>
        </section>
      </div>

      {/* 今日待办（作者自定义） */}
      <section className="todo-card">
        <div className="section-title">
          <h2>今日待办</h2>
          <span>作者自定义</span>
        </div>
        <TodoList todos={todos} setTodos={setTodos} />
      </section>

      {/* 下一步引导（AI 整理，作者决策） */}
      {nextStep && (
        <Link className="continue-strip" to={`/projects/${projectId}/${nextStep[1]}`}>
          <span>
            <small>下一步建议</small>
            <strong>{nextStep[0]}</strong>
          </span>
          <ArrowRight size={18} />
        </Link>
      )}

      {/* 最近章节 + 伏笔状态（两列） */}
      <div className="workspace-row">
        <section className="list-card">
          <div className="section-title">
            <h2>最近章节</h2>
            <span>{chapters.length} 章</span>
          </div>
          {recentChapters.length ? (
            <div className="recent-list">
              {recentChapters.map((chapter) => (
                <button
                  key={chapter.id}
                  type="button"
                  className="recent-item"
                  onClick={() => navigate(`/projects/${projectId}/chapters/${chapter.id}`)}
                >
                  <span className="chapter-id">{chapter.id}</span>
                  <strong>{chapter.title}</strong>
                  <small>{chapter.word_count.toLocaleString("zh-CN")} 字</small>
                </button>
              ))}
            </div>
          ) : (
            <p className="muted">尚无正式章节。</p>
          )}
        </section>

        <section className="list-card">
          <div className="section-title">
            <h2>伏笔状态</h2>
            <span>AI 整理</span>
          </div>
          {activeForeshadowings.length ? (
            <div className="foreshadow-list">
              {activeForeshadowings.slice(0, 5).map((item) => (
                <article key={item.id} className="foreshadow-item">
                  <strong>{item.content ?? item.id}</strong>
                  <small className="muted">来源：{item.source}</small>
                  <code className="muted">{item.location}</code>
                </article>
              ))}
              {activeForeshadowings.length > 5 && (
                <Link className="view-all" to={`/projects/${projectId}/memory`}>
                  查看全部 {activeForeshadowings.length} 个伏笔 <ArrowRight size={14} />
                </Link>
              )}
            </div>
          ) : (
            <p className="muted">没有待回收的伏笔。</p>
          )}
        </section>
      </div>

      {/* 最近数据（AI 整理，作者决策） */}
      {metrics.data && metrics.data.observations > 0 && (
        <section className="metrics-card">
          <div className="section-title">
            <h2>最近数据</h2>
            <span>{metrics.data.observations} 次观测</span>
          </div>
          <div className="metric-strip">
            <span>
              点击率 <strong>{(metrics.data.click_through_rate * 100).toFixed(1)}%</strong>
            </span>
            <span>
              首章完读 <strong>{(metrics.data.chapter_one_completion_rate * 100).toFixed(1)}%</strong>
            </span>
            <span>
              三章留存 <strong>{(metrics.data.chapter_three_retention_rate * 100).toFixed(1)}%</strong>
            </span>
            <span>
              追读率 <strong>{(metrics.data.follow_rate * 100).toFixed(1)}%</strong>
            </span>
            <span>
              千次打开收入 <strong>¥{metrics.data.revenue_per_thousand_opens_yuan.toFixed(2)}</strong>
            </span>
          </div>
          <Link className="view-all" to={`/projects/${projectId}/commercial`}>
            查看详细数据 <ArrowRight size={14} />
          </Link>
        </section>
      )}

      {/* C1：AI 诊断与建议（候选，作者决策） */}
      <section className="ai-card">
        <div className="section-title">
          <h2>AI 诊断与建议</h2>
          <span>候选，作者决策</span>
        </div>
        <p className="ai-intro">
          AI 诊断与建议（候选，作者决策）——以下条目均为候选，由作者决定是否采纳。
        </p>
        <div className="ai-toolbar">
          <button
            className="button button-secondary"
            type="button"
            onClick={() => diagnostics.refetch()}
            disabled={diagnostics.isFetching}
          >
            <RefreshCw size={14} className={diagnostics.isFetching ? "is-spinning" : ""} />
            运行诊断
          </button>
        </div>
        <AiDiagnosticsSection
          data={diagnostics.data}
          isFetching={diagnostics.isFetching}
          isError={diagnostics.isError}
          getState={getDecisionState}
          onDecide={handleAiDecide}
        />
        <AiSuggestionsSection
          data={suggestions.data}
          isFetching={suggestions.isFetching}
          isError={suggestions.isError}
          getState={getDecisionState}
          onDecide={handleAiDecide}
        />
      </section>

      {/* 模型用量（AI 整理） */}
      {usage.data && (
        <section className="usage-card">
          <div className="section-title">
            <h2>模型用量</h2>
            <span>本次会话累计</span>
          </div>
          <div className="usage-strip">
            <span>
              调用 <strong>{usage.data.request_count}</strong> 次
            </span>
            <span>
              Token <strong>{usage.data.total_tokens.toLocaleString("zh-CN")}</strong>
            </span>
            <span>
              费用 <strong>¥{usage.data.total_cost_cny.toFixed(4)}</strong>
            </span>
          </div>
        </section>
      )}
    </div>
  );
}

/**
 * 待办列表组件
 * 作者自定义，AI 不干预
 */
function TodoList({ todos, setTodos }: { todos: TodoItem[]; setTodos: (todos: TodoItem[]) => void }) {
  const [input, setInput] = useState("");

  function add() {
    const text = input.trim();
    if (!text) return;
    setTodos([...todos, { id: crypto.randomUUID(), text, done: false }]);
    setInput("");
  }

  function toggle(id: string) {
    setTodos(todos.map((item) => (item.id === id ? { ...item, done: !item.done } : item)));
  }

  function remove(id: string) {
    setTodos(todos.filter((item) => item.id !== id));
  }

  return (
    <div className="todo-container">
      <div className="todo-input-row">
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && add()}
          placeholder="添加待办事项"
        />
        <button className="icon-button" type="button" onClick={add} aria-label="添加">
          <Plus size={15} />
        </button>
      </div>
      {todos.length ? (
        <ul className="todo-list">
          {todos.map((todo) => (
            <li key={todo.id} className={todo.done ? "is-done" : ""}>
              <button type="button" className="todo-check" onClick={() => toggle(todo.id)}>
                {todo.done && <Check size={13} />}
              </button>
              <span>{todo.text}</span>
              <button type="button" className="icon-button todo-remove" onClick={() => remove(todo.id)} aria-label="删除">
                <X size={13} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">暂无待办。</p>
      )}
    </div>
  );
}

/**
 * AI 诊断候选区
 * 显示 runDiagnostics 返回的诊断列表，每项可采纳/忽略
 * 决策状态从统一决策队列查询（features/decisions/decisionQueue.ts）
 * 失败时显示"诊断服务暂不可用"，不报错
 */
function AiDiagnosticsSection({
  data,
  isFetching,
  isError,
  getState,
  onDecide,
}: {
  data: DiagnosticResult[] | undefined;
  isFetching: boolean;
  isError: boolean;
  getState: (key: string) => "pending" | "accepted" | "ignored" | "modified" | undefined;
  onDecide: (key: string, state: "accepted" | "ignored" | undefined) => void;
}) {
  if (isFetching) {
    return <p className="muted">正在运行诊断...</p>;
  }
  if (isError) {
    return <p className="muted">诊断服务暂不可用</p>;
  }
  if (!data || data.length === 0) {
    return <p className="muted">点击"运行诊断"获取候选诊断。</p>;
  }
  return (
    <div className="ai-subsection">
      <h3 className="ai-subsection-title">诊断候选</h3>
      <ul className="ai-list">
        {data.map((item, index) => {
          const key = diagnosticKey(item);
          const state = getState(key);
          return (
            <li
              key={`${key}-${index}`}
              className={`ai-item ai-item--${item.severity}`}
            >
              <div className="ai-item-header">
                <span className={`ai-tag ai-tag--${item.diagnostic_type}`}>
                  {diagnosticTypeLabel(item.diagnostic_type)}
                </span>
                <strong className="ai-target">{item.target}</strong>
                {state && (
                  <span className={`ai-state ai-state--${state}`}>
                    {state === "accepted" ? "已采纳" : state === "modified" ? "已修改" : "已忽略"}
                  </span>
                )}
              </div>
              <p className="ai-conclusion">{item.conclusion}</p>
              {item.possible_causes.length > 0 && (
                <div className="ai-causes">
                  <small>可能原因：</small>
                  <ul>
                    {item.possible_causes.map((cause, i) => (
                      <li key={i}>{cause}</li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="ai-actions">
                {!state && (
                  <>
                    <button
                      className="button button-primary"
                      type="button"
                      onClick={() => onDecide(key, "accepted")}
                    >
                      采纳
                    </button>
                    <button
                      className="button button-secondary"
                      type="button"
                      onClick={() => onDecide(key, "ignored")}
                    >
                      忽略
                    </button>
                  </>
                )}
                {state && (
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => onDecide(key, undefined)}
                  >
                    撤销
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * AI 建议候选区
 * 显示 listSuggestions 返回的建议列表，每项可采纳/忽略
 * 决策状态从统一决策队列查询
 * 失败时显示"建议服务暂不可用"，不报错
 */
function AiSuggestionsSection({
  data,
  isFetching,
  isError,
  getState,
  onDecide,
}: {
  data: Suggestion[] | undefined;
  isFetching: boolean;
  isError: boolean;
  getState: (key: string) => "pending" | "accepted" | "ignored" | "modified" | undefined;
  onDecide: (key: string, state: "accepted" | "ignored" | undefined) => void;
}) {
  if (isFetching) {
    return <p className="muted">正在加载建议...</p>;
  }
  if (isError) {
    return <p className="muted">建议服务暂不可用</p>;
  }
  if (!data || data.length === 0) {
    return <p className="muted">暂无可执行建议。</p>;
  }
  return (
    <div className="ai-subsection">
      <h3 className="ai-subsection-title">建议候选</h3>
      <ul className="ai-list">
        {data.map((item, index) => {
          const key = suggestionKey(item);
          const state = getState(key);
          return (
            <li
              key={`${key}-${index}`}
              className={`ai-item ai-item--${item.priority}`}
            >
              <div className="ai-item-header">
                <span className={`ai-tag ai-tag--${item.type}`}>
                  {suggestionTypeLabel(item.type)}
                </span>
                <span className={`ai-priority ai-priority--${item.priority}`}>
                  优先级：{priorityLabel(item.priority)}
                </span>
                {state && (
                  <span className={`ai-state ai-state--${state}`}>
                    {state === "accepted" ? "已采纳" : state === "modified" ? "已修改" : "已忽略"}
                  </span>
                )}
              </div>
              <p className="ai-conclusion">{item.content}</p>
              <p className="ai-reason">
                <small>推荐理由：</small>
                <span>{item.reason}</span>
              </p>
              <div className="ai-actions">
                {!state && (
                  <>
                    <button
                      className="button button-primary"
                      type="button"
                      onClick={() => onDecide(key, "accepted")}
                    >
                      采纳
                    </button>
                    <button
                      className="button button-secondary"
                      type="button"
                      onClick={() => onDecide(key, "ignored")}
                    >
                      忽略
                    </button>
                  </>
                )}
                {state && (
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => onDecide(key, undefined)}
                  >
                    撤销
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
