import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ArrowRight, CalendarRange, Sparkles } from "lucide-react";

import { useLocalStorage } from "../hooks/useLocalStorage";

/**
 * 批量章节规划项
 * 每章包含钩子、目标、爽点、结尾四要素
 * status 跟踪每章进度：planned -> writing -> done
 */
export interface BatchChapter {
  id: string;
  chapterId: string; // 章节号
  hook: string; // 钩子：开头抓住读者
  goal: string; // 目标：本章要推进什么
  climax: string; // 爽点：高潮或转折
  ending: string; // 结尾：留悬念或收束
  status: "planned" | "writing" | "done";
}

const STATUS_LABELS: Record<BatchChapter["status"], string> = {
  planned: "已规划",
  writing: "写作中",
  done: "已完成",
};

/**
 * 批量章节规划页面
 * 作者输入起止章节号，生成候选规划卡片
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
   * 生成规划：根据起止章节号生成空模板
   * 注意：后端 API 暂不支持批量规划，这里只生成空模板让作者手动填写
   * 不引入 Mock 数据，作者完全自主决策
   */
  function generatePlan() {
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

  // 按章节号排序展示
  const sorted = useMemo(
    () =>
      [...chapters].sort(
        (a, b) => Number(a.chapterId) - Number(b.chapterId),
      ),
    [chapters],
  );

  return (
    <div className="batch-planning-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">长篇维护</span>
          <h1>批量章节规划</h1>
          <p>AI 按作者输入生成候选规划，作者可逐章修改</p>
        </div>
        {chapters.length > 0 && (
          <div className="header-actions">
            <button
              type="button"
              className="button button-secondary"
              onClick={clearAll}
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
            onClick={generatePlan}
          >
            <Sparkles size={15} />
            生成规划
          </button>
        </div>
        {error && <div className="inline-error">{error}</div>}
        <p className="muted batch-hint">
          说明：当前后端暂不支持批量 AI 规划，点击后生成空模板，作者逐章填写即可。
          已存在的章节号不会被覆盖。
        </p>
      </section>

      {/* 规划结果列表 */}
      {sorted.length === 0 ? (
        <div className="loading-state">
          <CalendarRange size={28} />
          <p>暂无规划，请输入起止章节号后点击「生成规划」</p>
        </div>
      ) : (
        <div className="batch-chapter-list">
          {sorted.map((chapter) => (
            <BatchChapterCard
              key={chapter.id}
              chapter={chapter}
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
 * 展示并编辑钩子/目标/爽点/结尾，提供「开始写作」入口
 */
interface BatchChapterCardProps {
  chapter: BatchChapter;
  onFieldChange: (id: string, field: keyof BatchChapter, value: string) => void;
  onCycleStatus: (id: string) => void;
  onRemove: (id: string) => void;
  onStartWriting: () => void;
}

function BatchChapterCard({
  chapter,
  onFieldChange,
  onCycleStatus,
  onRemove,
  onStartWriting,
}: BatchChapterCardProps) {
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
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={() => onRemove(chapter.id)}
          aria-label="删除此章规划"
        >
          ×
        </button>
      </header>
      <div className="batch-chapter-fields">
        <label>
          钩子
          <textarea
            value={chapter.hook}
            onChange={(event) =>
              onFieldChange(chapter.id, "hook", event.target.value)
            }
            placeholder="开头如何抓住读者？"
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
          />
        </label>
      </div>
      <footer className="batch-chapter-footer">
        <button
          type="button"
          className="button button-primary"
          onClick={onStartWriting}
        >
          开始写作 <ArrowRight size={15} />
        </button>
      </footer>
    </article>
  );
}
