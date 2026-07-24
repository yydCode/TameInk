import { useCallback, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";
import {
  ArrowRight,
  CalendarRange,
  LoaderCircle,
  Sparkles,
  XCircle,
} from "lucide-react";

import {
  generateChapterPlan,
  getDraft,
  getTask,
  type Task,
} from "../api/client";
import { useLocalStorage } from "../hooks/useLocalStorage";

/**
 * 批量章节规划项
 * 每章包含钩子、目标、爽点、结尾四要素
 * status 跟踪每章进度：planned -> writing -> done
 * aiPlan：AI 通过 generateChapterPlan 生成的 plan.md 文本（作者参考，可忽略）
 */
export interface BatchChapter {
  id: string;
  chapterId: string; // 章节号
  hook: string; // 钩子：开头抓住读者
  goal: string; // 目标：本章要推进什么
  climax: string; // 爽点：高潮或转折
  ending: string; // 结尾：留悬念或收束
  status: "planned" | "writing" | "done";
  // AI 规划产物（来自 plan.md），作者可参考填写四字段
  aiPlan?: string;
  // AI 任务状态：标记当前章节的 AI 规划进度
  aiStatus?: "idle" | "running" | "done" | "failed";
  aiError?: string;
}

const STATUS_LABELS: Record<BatchChapter["status"], string> = {
  planned: "已规划",
  writing: "写作中",
  done: "已完成",
};

const AI_STATUS_LABELS: Record<NonNullable<BatchChapter["aiStatus"]>, string> = {
  idle: "未生成",
  running: "生成中",
  done: "已生成",
  failed: "失败",
};

// 串行轮询任务的间隔（毫秒）
const POLL_INTERVAL_MS = 3000;
// 单任务最长等待时间（毫秒），超过视为失败
const TASK_TIMEOUT_MS = 5 * 60 * 1000;

/**
 * 批量章节规划页面
 * 作者输入起止章节号，可选「AI 规划」串行生成每章 plan.md
 * 规划存 localStorage，作者可逐章修改后开始写作
 */
export function BatchPlanningPage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();

  // 起止章节号输入
  const [startId, setStartId] = useState(1);
  const [endId, setEndId] = useState(10);
  // 错误提示
  const [error, setError] = useState<string | null>(null);
  // AI 串行规划的全局进度（正在处理的章节号，null 表示空闲）
  const [aiRunningChapter, setAiRunningChapter] = useState<string | null>(null);

  // 规划数据存 localStorage
  const [chapters, setChapters] = useLocalStorage<BatchChapter[]>(
    `tame-ink:batch-plan:${projectId}`,
    [],
  );

  // 章节号 -> 是否已规划
  const plannedIds = useMemo(
    () => new Set(chapters.map((chapter) => chapter.chapterId)),
    [chapters],
  );

  /**
   * 生成空模板：根据起止章节号生成 BatchChapter 空壳
   * 不引入 Mock 数据，作者完全自主决策
   */
  function generateEmptyPlan() {
    setError(null);
    if (!Number.isFinite(startId) || !Number.isFinite(endId)) {
      setError("章节号必须为数字");
      return;
    }
    if (startId <= 0 || endId <= 0) {
      setError("章节号必须大于 0");
      return;
    }
    if (startId > endId) {
      setError("起始章节号不能大于结束章节号");
      return;
    }
    // 上限保护：避免一次性生成过多空模板
    const total = endId - startId + 1;
    if (total > 100) {
      setError("一次最多规划 100 章");
      return;
    }

    const next: BatchChapter[] = [...chapters];
    for (let chapterId = startId; chapterId <= endId; chapterId++) {
      const id = String(chapterId);
      if (plannedIds.has(id)) continue;
      next.push({
        id: crypto.randomUUID(),
        chapterId: id,
        hook: "",
        goal: "",
        climax: "",
        ending: "",
        status: "planned",
        aiStatus: "idle",
      });
    }
    setChapters(next);
  }

  // 更新某一章的字段
  function updateField(id: string, field: keyof BatchChapter, value: string) {
    setChapters(
      chapters.map((chapter) =>
        chapter.id === id ? { ...chapter, [field]: value } : chapter,
      ),
    );
  }

  // 循环切换状态：planned -> writing -> done -> planned
  function cycleStatus(id: string) {
    setChapters(
      chapters.map((chapter) => {
        if (chapter.id !== id) return chapter;
        const nextStatus: BatchChapter["status"] =
          chapter.status === "planned"
            ? "writing"
            : chapter.status === "writing"
              ? "done"
              : "planned";
        return { ...chapter, status: nextStatus };
      }),
    );
  }

  // 删除单章规划
  function removeChapter(id: string) {
    setChapters(chapters.filter((chapter) => chapter.id !== id));
  }

  // 清空全部规划
  function clearAll() {
    if (chapters.length === 0) return;
    if (window.confirm("确定清空全部规划吗？此操作不可撤销。")) {
      setChapters([]);
    }
  }

  /**
   * AI 规划单章：调用 generateChapterPlan，轮询任务状态，完成后回填 plan.md
   * 失败抛出错误，由调用方决定是否继续下一章
   */
  const planOneChapter = useCallback(
    async (projectId: string, chapterId: string, instruction: string) => {
      // 启动任务
      const task: Task = await generateChapterPlan(
        projectId,
        chapterId,
        instruction,
      );

      // 轮询任务状态
      const startTime = Date.now();
      while (true) {
        if (Date.now() - startTime > TASK_TIMEOUT_MS) {
          throw new Error(`AI 规划第 ${chapterId} 章超时（5 分钟）`);
        }
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        const current = await getTask(projectId, task.id);
        if (current.status === "awaiting_approval") {
          // 任务完成，读取 plan.md
          const draft = await getDraft(projectId, task.id, "plan.md");
          return draft.content;
        }
        if (current.status === "failed" || current.status === "cancelled") {
          const detail = current.error_message
            ? `：${current.error_message}`
            : "";
          throw new Error(
            `AI 规划第 ${chapterId} 章${current.status === "cancelled" ? "被取消" : "失败"}${detail}`,
          );
        }
        // pending / running 继续轮询
      }
    },
    [],
  );

  /**
   * 批量 AI 规划：对未生成 AI plan 的章节串行执行
   * 一章失败不阻塞下一章，仅标记当前章失败
   */
  async function runAiBatch() {
    if (aiRunningChapter) return;
    setError(null);

    // 找出所有 aiStatus 为 idle 或 failed 的章节，按章节号升序
    const pending = chapters
      .filter((c) => c.aiStatus === "idle" || c.aiStatus === "failed")
      .sort((a, b) => Number(a.chapterId) - Number(b.chapterId));

    if (pending.length === 0) {
      setError("没有待 AI 规划的章节");
      return;
    }

    for (const chapter of pending) {
      setAiRunningChapter(chapter.chapterId);
      // 标记为 running
      setChapters((prev) =>
        prev.map((c) =>
          c.id === chapter.id
            ? { ...c, aiStatus: "running", aiError: undefined }
            : c,
        ),
      );

      try {
        const instruction = `为第 ${chapter.chapterId} 章生成章纲。${
          chapter.goal ? `作者目标：${chapter.goal}。` : ""
        }${
          chapter.hook ? `开头钩子：${chapter.hook}。` : ""
        }请给出本章的开头钩子、核心目标、爽点设计、结尾悬念。`;
        const planContent = await planOneChapter(
          projectId,
          chapter.chapterId,
          instruction,
        );
        // 回填 plan.md
        setChapters((prev) =>
          prev.map((c) =>
            c.id === chapter.id
              ? { ...c, aiStatus: "done", aiPlan: planContent, aiError: undefined }
              : c,
          ),
        );
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        setChapters((prev) =>
          prev.map((c) =>
            c.id === chapter.id
              ? { ...c, aiStatus: "failed", aiError: message }
              : c,
          ),
        );
        // 失败不阻塞，继续下一章
      }
    }
    setAiRunningChapter(null);
  }

  // 组件卸载时 async 循环无法被 abort，但 React 18 之后 setState on unmounted 会被忽略，无需额外处理

  // 按章节号排序展示
  const sorted = useMemo(
    () =>
      [...chapters].sort(
        (a, b) => Number(a.chapterId) - Number(b.chapterId),
      ),
    [chapters],
  );

  // 是否有未生成 AI plan 的章节
  const hasPendingAi = sorted.some(
    (c) => c.aiStatus === "idle" || c.aiStatus === "failed",
  );

  return (
    <div className="batch-planning-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">长篇维护</span>
          <h1>批量章节规划</h1>
          <p>
            生成空模板后，可点击「AI 规划」串行生成每章章纲（plan.md），
            作者参考 AI 章纲手动填写四要素，最终决定权在作者。
          </p>
        </div>
        {chapters.length > 0 && (
          <div className="header-actions">
            <button
              type="button"
              className="button button-primary"
              onClick={runAiBatch}
              disabled={Boolean(aiRunningChapter) || !hasPendingAi}
              title={!hasPendingAi ? "所有章节已生成 AI 规划" : ""}
            >
              {aiRunningChapter ? (
                <LoaderCircle className="spin" size={15} />
              ) : (
                <Sparkles size={15} />
              )}
              {aiRunningChapter
                ? `AI 规划中：第 ${aiRunningChapter} 章`
                : "AI 规划"}
            </button>
            <button
              type="button"
              className="button button-secondary"
              onClick={clearAll}
              disabled={Boolean(aiRunningChapter)}
            >
              清空全部
            </button>
          </div>
        )}
      </header>

      {/* 起止章节号输入区 */}
      <section className="batch-input-card">
        <div className="batch-input-row">
          <label>
            起始章节号
            <input
              type="number"
              min="1"
              value={startId}
              onChange={(event) =>
                setStartId(Math.max(1, Number(event.target.value)))
              }
            />
          </label>
          <label>
            结束章节号
            <input
              type="number"
              min="1"
              value={endId}
              onChange={(event) =>
                setEndId(Math.max(1, Number(event.target.value)))
              }
            />
          </label>
          <button
            type="button"
            className="button button-primary"
            onClick={generateEmptyPlan}
          >
            <Sparkles size={15} />
            生成空模板
          </button>
        </div>
        {error && <div className="inline-error">{error}</div>}
        <p className="muted batch-hint">
          说明：点击「生成空模板」生成章节卡片。
          再点「AI 规划」串行调用后端 generateChapterPlan，
          每章任务完成后把 plan.md 回填到卡片，作者参考后填写四要素。
          失败的章节可再次点击「AI 规划」重试。
        </p>
      </section>

      {/* 规划结果列表 */}
      {sorted.length === 0 ? (
        <div className="loading-state">
          <CalendarRange size={28} />
          <p>暂无规划，请输入起止章节号后点击「生成空模板」</p>
        </div>
      ) : (
        <div className="batch-chapter-list">
          {sorted.map((chapter) => (
            <BatchChapterCard
              key={chapter.id}
              chapter={chapter}
              aiRunning={aiRunningChapter === chapter.chapterId}
              onFieldChange={updateField}
              onCycleStatus={cycleStatus}
              onRemove={removeChapter}
              onStartWriting={() =>
                navigate(`/projects/${projectId}/chapters/${chapter.chapterId}`)
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * 单章规划卡片
 * 展示并编辑钩子/目标/爽点/结尾，AI 规划产物作为只读参考展示
 */
interface BatchChapterCardProps {
  chapter: BatchChapter;
  aiRunning: boolean;
  onFieldChange: (id: string, field: keyof BatchChapter, value: string) => void;
  onCycleStatus: (id: string) => void;
  onRemove: (id: string) => void;
  onStartWriting: () => void;
}

function BatchChapterCard({
  chapter,
  aiRunning,
  onFieldChange,
  onCycleStatus,
  onRemove,
  onStartWriting,
}: BatchChapterCardProps) {
  const [showAiPlan, setShowAiPlan] = useState(false);

  return (
    <article className="batch-chapter-card">
      <header className="batch-chapter-header">
        <button
          type="button"
          className="batch-chapter-title"
          onClick={() => onCycleStatus(chapter.id)}
          title="点击切换状态"
        >
          <span className="chapter-id">第 {chapter.chapterId} 章</span>
          <span className={`batch-status batch-status-${chapter.status}`}>
            {STATUS_LABELS[chapter.status]}
          </span>
          {chapter.aiStatus && chapter.aiStatus !== "idle" && (
            <span
              className={`batch-status batch-status-${chapter.aiStatus}`}
              title={chapter.aiError}
            >
              {aiRunning
                ? "AI 生成中..."
                : AI_STATUS_LABELS[chapter.aiStatus]}
            </span>
          )}
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={() => onRemove(chapter.id)}
          aria-label="删除此章规划"
          disabled={aiRunning}
        >
          ×
        </button>
      </header>

      {/* AI 规划产物（参考展示） */}
      {chapter.aiPlan && (
        <div className="batch-ai-plan">
          <button
            type="button"
            className="button button-secondary batch-ai-toggle"
            onClick={() => setShowAiPlan(!showAiPlan)}
          >
            {showAiPlan ? "收起 AI 章纲" : "查看 AI 章纲"}
          </button>
          {showAiPlan && (
            <pre className="batch-ai-plan-content">{chapter.aiPlan}</pre>
          )}
        </div>
      )}

      {/* AI 失败提示 */}
      {chapter.aiStatus === "failed" && chapter.aiError && (
        <div className="inline-error">
          <XCircle size={13} />
          {chapter.aiError}
        </div>
      )}

      <div className="batch-chapter-fields">
        <label>
          钩子
          <textarea
            value={chapter.hook}
            onChange={(event) =>
              onFieldChange(chapter.id, "hook", event.target.value)
            }
            placeholder="开头如何抓住读者？"
            disabled={aiRunning}
          />
        </label>
        <label>
          目标
          <textarea
            value={chapter.goal}
            onChange={(event) =>
              onFieldChange(chapter.id, "goal", event.target.value)
            }
            placeholder="本章要推进什么剧情？"
            disabled={aiRunning}
          />
        </label>
        <label>
          爽点
          <textarea
            value={chapter.climax}
            onChange={(event) =>
              onFieldChange(chapter.id, "climax", event.target.value)
            }
            placeholder="高潮或转折是什么？"
            disabled={aiRunning}
          />
        </label>
        <label>
          结尾
          <textarea
            value={chapter.ending}
            onChange={(event) =>
              onFieldChange(chapter.id, "ending", event.target.value)
            }
            placeholder="结尾如何收束或留悬念？"
            disabled={aiRunning}
          />
        </label>
      </div>
      <footer className="batch-chapter-footer">
        <button
          type="button"
          className="button button-primary"
          onClick={onStartWriting}
          disabled={aiRunning}
        >
          开始写作 <ArrowRight size={15} />
        </button>
      </footer>
    </article>
  );
}
