import { useMemo, useState } from "react";
import { Check, Plus, Trash2 } from "lucide-react";

import type { CommercialMetrics } from "../../api/client";
import { useLocalStorage } from "../../hooks/useLocalStorage";

// 首测目标设定
interface FirstTestGoals {
  targetWords: number; // 目标首测字数
  targetClickRate: number; // 目标点击率（百分比，0-100）
  targetCompletionRate: number; // 目标首章完读率（百分比，0-100）
  targetFollowRate: number; // 目标追读率（百分比，0-100）
}

// 首测每日任务
interface FirstTestTask {
  id: string;
  text: string;
  done: boolean;
  date: string; // YYYY-MM-DD
}

// 持久化状态结构
interface FirstTestState {
  goals: FirstTestGoals;
  tasks: FirstTestTask[];
}

// 默认目标（番茄首测常见基线）
const DEFAULT_GOALS: FirstTestGoals = {
  targetWords: 100000,
  targetClickRate: 8,
  targetCompletionRate: 45,
  targetFollowRate: 5,
};

// 简单 ID 生成器
function makeId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

// 获取今日日期字符串
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

// 计算单项目标达成百分比，返回 0-100 之间的数字
function progress(current: number, target: number): number {
  if (target <= 0) return 0;
  const value = (current / target) * 100;
  return Math.max(0, Math.min(100, value));
}

/**
 * 首测管理（Task B8）
 * - 首测目标设定
 * - 达成百分比追踪（基于 getCommercialMetrics 返回的实际数据）
 * - 每日任务清单
 * - 首测决策辅助（基于目标达成情况自动判定状态）
 */
export function FirstTestManager({
  projectId,
  metrics,
  totalWords,
}: {
  projectId: string;
  metrics: CommercialMetrics | undefined;
  totalWords: number;
}) {
  const storageKey = `tame-ink:first-test:${projectId}`;
  const [state, setState] = useLocalStorage<FirstTestState>(storageKey, {
    goals: DEFAULT_GOALS,
    tasks: [],
  });

  // 新任务输入框
  const [newTaskText, setNewTaskText] = useState("");

  // 实际指标：点击率/首章完读率/追读率（百分比），字数来自外部传入
  const actual = useMemo(() => {
    return {
      words: totalWords,
      clickRate: metrics ? metrics.click_through_rate * 100 : 0,
      completionRate: metrics ? metrics.chapter_one_completion_rate * 100 : 0,
      followRate: metrics ? metrics.follow_rate * 100 : 0,
    };
  }, [metrics, totalWords]);

  // 各维度达成进度（0-100）
  const progressMap = useMemo(
    () => ({
      words: progress(actual.words, state.goals.targetWords),
      clickRate: progress(actual.clickRate, state.goals.targetClickRate),
      completionRate: progress(
        actual.completionRate,
        state.goals.targetCompletionRate,
      ),
      followRate: progress(actual.followRate, state.goals.targetFollowRate),
    }),
    [actual, state.goals],
  );

  // 整体进度取各项平均
  const overallProgress = useMemo(
    () =>
      Math.round(
        (progressMap.words +
          progressMap.clickRate +
          progressMap.completionRate +
          progressMap.followRate) /
          4,
      ),
    [progressMap],
  );

  // 首测决策辅助：基于目标达成情况判定状态
  const decision = useMemo(() => {
    const values = Object.values(progressMap);
    const allPassed = values.every((v) => v >= 100);
    const anySevere = values.some((v) => v < 60);
    if (allPassed) {
      return {
        status: "passed",
        label: "已通过",
        advice: "首测各项指标均已达标，可推进正式更新节奏与推广资源。",
      };
    }
    if (anySevere) {
      return {
        status: "adjust",
        label: "需调整",
        advice: "存在指标明显低于预期（<60%），建议复盘首章钩子与推荐位素材后再加大投放。",
      };
    }
    return {
      status: "running",
      label: "进行中",
      advice: "首测进行中，部分指标接近目标。继续观察 3-5 天数据再做下一步决策。",
    };
  }, [progressMap]);

  // 修改目标值
  function updateGoal<K extends keyof FirstTestGoals>(
    key: K,
    value: number,
  ) {
    setState((prev) => ({
      ...prev,
      goals: { ...prev.goals, [key]: Number.isFinite(value) ? value : 0 },
    }));
  }

  // 添加每日任务（自动按今日日期记录）
  function addTask() {
    const text = newTaskText.trim();
    if (!text) return;
    const task: FirstTestTask = {
      id: makeId(),
      text,
      done: false,
      date: today(),
    };
    setState((prev) => ({ ...prev, tasks: [task, ...prev.tasks] }));
    setNewTaskText("");
  }

  // 勾选/取消勾选任务
  function toggleTask(id: string) {
    setState((prev) => ({
      ...prev,
      tasks: prev.tasks.map((t) =>
        t.id === id ? { ...t, done: !t.done } : t,
      ),
    }));
  }

  // 删除任务
  function removeTask(id: string) {
    setState((prev) => ({
      ...prev,
      tasks: prev.tasks.filter((t) => t.id !== id),
    }));
  }

  return (
    <section className="first-test-section">
      <div className="section-title">
        <h2>首测管理</h2>
        <span>目标追踪 · 每日任务 · 决策辅助</span>
      </div>

      {/* 首测决策辅助横幅 */}
      <div className={`first-test-banner is-${decision.status}`}>
        <div>
          <strong>首测状态：{decision.label}</strong>
          <p>{decision.advice}</p>
        </div>
        <div className="first-test-overall">
          <span>整体达成</span>
          <strong>{overallProgress}%</strong>
        </div>
      </div>

      {/* 首测目标设定 + 进度追踪 */}
      <div className="first-test-goals">
        <GoalField
          label="目标首测字数"
          value={state.goals.targetWords}
          actualLabel={`${actual.words.toLocaleString()} 字`}
          progress={progressMap.words}
          onChange={(v) => updateGoal("targetWords", v)}
        />
        <GoalField
          label="目标点击率（%）"
          value={state.goals.targetClickRate}
          actualLabel={`${actual.clickRate.toFixed(2)}%`}
          progress={progressMap.clickRate}
          onChange={(v) => updateGoal("targetClickRate", v)}
        />
        <GoalField
          label="目标首章完读率（%）"
          value={state.goals.targetCompletionRate}
          actualLabel={`${actual.completionRate.toFixed(2)}%`}
          progress={progressMap.completionRate}
          onChange={(v) => updateGoal("targetCompletionRate", v)}
        />
        <GoalField
          label="目标追读率（%）"
          value={state.goals.targetFollowRate}
          actualLabel={`${actual.followRate.toFixed(2)}%`}
          progress={progressMap.followRate}
          onChange={(v) => updateGoal("targetFollowRate", v)}
        />
      </div>

      {/* 每日任务清单 */}
      <div className="first-test-tasks">
        <h3>每日任务清单</h3>
        <div className="title-input-row">
          <input
            value={newTaskText}
            onChange={(event) => setNewTaskText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") addTask();
            }}
            placeholder="输入今日待办，例如：检查首章钩子、回复读者评论"
          />
          <button
            type="button"
            className="button button-primary"
            onClick={addTask}
            disabled={!newTaskText.trim()}
          >
            <Plus size={14} />
            添加任务
          </button>
        </div>
        {state.tasks.length === 0 ? (
          <p className="muted empty-hint">暂无任务，添加今日待办以追踪首测执行进度。</p>
        ) : (
          <ul className="task-list">
            {state.tasks.map((t) => (
              <li
                key={t.id}
                className={`task-item${t.done ? " is-done" : ""}`}
              >
                <button
                  type="button"
                  className="task-check"
                  onClick={() => toggleTask(t.id)}
                  aria-label={t.done ? "标记为未完成" : "标记为已完成"}
                >
                  {t.done && <Check size={12} />}
                </button>
                <div className="task-main">
                  <span className="task-text">{t.text}</span>
                  <time className="task-date">{t.date}</time>
                </div>
                <button
                  type="button"
                  className="icon-button"
                  onClick={() => removeTask(t.id)}
                  aria-label="删除任务"
                  title="删除任务"
                >
                  <Trash2 size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

/**
 * 单项目标输入 + 进度条组件
 * 复用避免在主组件中重复书写四遍相同结构
 */
function GoalField({
  label,
  value,
  actualLabel,
  progress,
  onChange,
}: {
  label: string;
  value: number;
  actualLabel: string;
  progress: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="goal-field">
      <label>
        {label}
        <input
          type="number"
          min="0"
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
        />
      </label>
      <div className="goal-actual">
        <span>当前实际</span>
        <strong>{actualLabel}</strong>
      </div>
      <div
        className="goal-progress"
        role="progressbar"
        aria-valuenow={Math.round(progress)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="goal-progress-bar"
          style={{ width: `${progress}%` }}
        />
        <span className="goal-progress-text">{Math.round(progress)}%</span>
      </div>
    </div>
  );
}
