import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, History, Plus, X } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router";

import { getCommercialMetrics, getProjectUsage, listMemory } from "../api/client";
import { queryKeys } from "../app/queryKeys";
import { useLocalStorage } from "../hooks/useLocalStorage";
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

  // 如果日期变了，重置今日已写
  if (dailyGoal.date !== today) {
    setDailyGoal({ ...dailyGoal, date: today, writtenWords: 0 });
  }

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
