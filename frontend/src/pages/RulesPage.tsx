import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, LoaderCircle, RotateCcw } from "lucide-react";
import { useParams } from "react-router";

import {
  createCommercialDraft,
  getCommercialProfile,
  updateCommercialDraft,
  type CommercialProfile,
  type PlatformPacing,
} from "../api/client";
import { queryKeys } from "../app/queryKeys";
import { useLocalStorage } from "../hooks/useLocalStorage";
import { useProjectWorkspace } from "../features/workspace/useProjectWorkspace";

// 旧版 localStorage 规则结构（仅用于首次迁移）
interface LegacyProjectRules {
  commercialScoreThreshold: number;
  continuityWeight: number;
  styleWeight: number;
  commercialWeight: number;
  climaxDensity: number;
  chapterEndHookRequired: boolean;
  maxWordsPerChapter: number;
  minWordsPerChapter: number;
}

// 默认节奏（与后端 PlatformPacing 默认值保持一致）
const DEFAULT_PACING: PlatformPacing = {
  chapter_word_count: 2500,
  min_chapter_word_count: 2000,
  opening_hook_lines: 7,
  scenes_per_chapter: 1,
  small_climax_every: 3,
  big_climax_every: 10,
  opening_hook_style: "conflict",
  chapter_end_cliffhanger: true,
  weight_continuity: 30,
  weight_style: 30,
  weight_commercial: 40,
};

/**
 * 规则设置页面
 * 作者设定规则，AI 按规则执行审查和评估。
 *
 * 数据源：后端 CommercialProfile.platform_pacing
 * - 若有 commercial task 处于 awaiting_approval，通过 updateCommercialDraft 保存
 * - 否则通过 createCommercialDraft 创建候选
 * - 旧 localStorage 数据首次进入时迁移一次（合并到后端字段后清理）
 */
export function RulesPage() {
  const { projectId = "" } = useParams();
  const queryClient = useQueryClient();
  const { tasks } = useProjectWorkspace(projectId);

  const profile = useQuery({
    queryKey: queryKeys.commercial(projectId),
    queryFn: () => getCommercialProfile(projectId),
  });

  // 查找 commercial 任务：优先 awaiting_approval，否则取最近的 pending/running
  const commercialTask =
    tasks.data?.find(
      (item) =>
        item.purpose === "commercial" && item.status === "awaiting_approval",
    ) ??
    tasks.data?.find(
      (item) =>
        item.purpose === "commercial" &&
        ["pending", "running"].includes(item.status),
    );

  // 旧 localStorage（仅用于首次迁移）
  const [legacyRules, setLegacyRules] = useLocalStorage<LegacyProjectRules | null>(
    `tame-ink:rules:${projectId}`,
    null,
  );

  // 本地编辑态：pacing + 门槛（独立于 profile 的其他字段）
  const [pacing, setPacing] = useState<PlatformPacing>(DEFAULT_PACING);
  const [minimumScore, setMinimumScore] = useState<number>(75);
  const [baseline, setBaseline] = useState<{
    pacing: PlatformPacing;
    minimumScore: number;
  }>({ pacing: DEFAULT_PACING, minimumScore: 75 });
  const [error, setError] = useState<string | null>(null);
  const [migrated, setMigrated] = useState(false);

  // 从 profile 加载到本地编辑态
  useEffect(() => {
    if (!profile.data) return;
    const next = profile.data.platform_pacing ?? DEFAULT_PACING;
    setPacing(next);
    setMinimumScore(profile.data.minimum_commercial_score);
    setBaseline({ pacing: next, minimumScore: profile.data.minimum_commercial_score });
  }, [profile.data]);

  // 旧 localStorage 迁移：首次加载时若后端 platform_pacing 为空且本地有旧规则，合并一次
  useEffect(() => {
    if (migrated || !profile.data) return;
    if (profile.data.platform_pacing || !legacyRules) return;

    const merged: PlatformPacing = {
      ...DEFAULT_PACING,
      chapter_word_count: legacyRules.maxWordsPerChapter,
      min_chapter_word_count: legacyRules.minWordsPerChapter,
      small_climax_every: legacyRules.climaxDensity,
      big_climax_every: Math.max(5, legacyRules.climaxDensity),
      chapter_end_cliffhanger: legacyRules.chapterEndHookRequired,
      weight_continuity: legacyRules.continuityWeight,
      weight_style: legacyRules.styleWeight,
      weight_commercial: legacyRules.commercialWeight,
    };
    setPacing(merged);
    setMinimumScore(legacyRules.commercialScoreThreshold);
    setBaseline({ pacing: merged, minimumScore: legacyRules.commercialScoreThreshold });
    // 清理旧 localStorage，避免重复迁移
    setLegacyRules(null);
    setMigrated(true);
  }, [profile.data, legacyRules, migrated, setLegacyRules]);

  const dirty = useMemo(
    () =>
      JSON.stringify(pacing) !== JSON.stringify(baseline.pacing) ||
      minimumScore !== baseline.minimumScore,
    [pacing, baseline, minimumScore],
  );

  // 保存：构造完整 profile，按 task 状态选择 API
  // createCommercialDraft 返回 Task；updateCommercialDraft 返回 CommercialProfile
  // 这里统一返回 CommercialProfile | null，让 onSuccess 判断
  const save = useMutation<CommercialProfile | null, Error, void>({
    mutationFn: async () => {
      if (!profile.data) throw new Error("商业定位尚未建立，请先在商业工作台生成定位");
      const next: CommercialProfile = {
        ...profile.data,
        platform_pacing: pacing,
        minimum_commercial_score: minimumScore,
      };
      if (commercialTask?.status === "awaiting_approval") {
        return updateCommercialDraft(projectId, commercialTask.id, next);
      }
      // 无候选任务时创建新 draft，返回 Task；让 query invalidation 拉最新 profile
      await createCommercialDraft(projectId, next);
      return null;
    },
    onSuccess: (value) => {
      setError(null);
      if (value) {
        const nextPacing = value.platform_pacing ?? DEFAULT_PACING;
        setPacing(nextPacing);
        setMinimumScore(value.minimum_commercial_score);
        setBaseline({ pacing: nextPacing, minimumScore: value.minimum_commercial_score });
      } else {
        // createCommercialDraft 返回 Task（无返回 profile），直接用本地值更新 baseline
        setBaseline({ pacing, minimumScore });
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.commercial(projectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks(projectId) });
    },
    onError: (cause) => setError(cause.message),
  });

  // 权重三项总和（建议为 100）
  const weightTotal =
    pacing.weight_continuity + pacing.weight_style + pacing.weight_commercial;
  const weightHint =
    weightTotal === 100 ? "总和为 100" : `建议总和为 100，当前为 ${weightTotal}`;

  // 更新单个 pacing 字段
  function updatePacing<K extends keyof PlatformPacing>(
    key: K,
    value: PlatformPacing[K],
  ) {
    setPacing((current) => ({ ...current, [key]: value }));
  }

  // 重置为默认值
  function reset() {
    setPacing(DEFAULT_PACING);
    setMinimumScore(75);
  }

  if (profile.isPending) {
    return <div className="loading-state">读取规则...</div>;
  }

  const canSave = dirty && !save.isPending;

  return (
    <section className="rules-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">规则设置</span>
          <h1>创作规则</h1>
          <p>
            这些规则由作者设定，AI 按规则执行审查和评估。
            {profile.data
              ? commercialTask?.status === "awaiting_approval"
                ? " 修改后保存到当前候选定位。"
                : " 修改后保存将创建新的商业定位候选。"
              : " 请先在「商业增长」中建立商业定位。"}
          </p>
        </div>
        <div className="header-actions">
          <button
            className="button button-secondary"
            type="button"
            onClick={reset}
            disabled={save.isPending}
          >
            <RotateCcw size={15} />
            重置为默认
          </button>
          <button
            className="button button-primary"
            type="button"
            onClick={() => save.mutate()}
            disabled={!canSave}
            title={profile.data ? "" : "请先在商业工作台建立商业定位"}
          >
            {save.isPending ? (
              <LoaderCircle className="spin" size={15} />
            ) : (
              <Check size={15} />
            )}
            保存规则
          </button>
        </div>
      </header>

      {error && <div className="inline-error" role="alert">{error}</div>}

      {/* 评分与节奏 */}
      <section className="rules-card">
        <div className="section-title">
          <h2>评分与节奏</h2>
        </div>
        <div className="form-grid">
          <label>
            商业评分门槛
            <input
              type="number"
              min={0}
              max={100}
              value={minimumScore}
              onChange={(event) =>
                setMinimumScore(
                  Math.max(0, Math.min(100, Number(event.target.value))),
                )
              }
            />
            <small className="muted">低于此分数的章节将标记为需改进</small>
          </label>

          <label>
            爽点密度（每多少章一个小高潮）
            <input
              type="number"
              min={1}
              max={10}
              value={pacing.small_climax_every}
              onChange={(event) =>
                updatePacing(
                  "small_climax_every",
                  Math.max(1, Math.min(10, Number(event.target.value))),
                )
              }
            />
            <small className="muted">控制节奏，避免平铺直叙</small>
          </label>

          <label>
            大高潮间隔（每多少章一个大高潮）
            <input
              type="number"
              min={5}
              max={30}
              value={pacing.big_climax_every}
              onChange={(event) =>
                updatePacing(
                  "big_climax_every",
                  Math.max(5, Math.min(30, Number(event.target.value))),
                )
              }
            />
            <small className="muted">关键转折或情绪爆点</small>
          </label>

          <label>
            每章最小字数
            <input
              type="number"
              min={500}
              max={5000}
              value={pacing.min_chapter_word_count}
              onChange={(event) =>
                updatePacing(
                  "min_chapter_word_count",
                  Math.max(500, Math.min(5000, Number(event.target.value))),
                )
              }
            />
            <small className="muted">低于此字数审查将告警</small>
          </label>

          <label>
            每章最大字数
            <input
              type="number"
              min={1000}
              max={5000}
              value={pacing.chapter_word_count}
              onChange={(event) =>
                updatePacing(
                  "chapter_word_count",
                  Math.max(1000, Math.min(5000, Number(event.target.value))),
                )
              }
            />
            <small className="muted">目标字数上限</small>
          </label>

          <label>
            开篇钩子行数
            <input
              type="number"
              min={3}
              max={20}
              value={pacing.opening_hook_lines}
              onChange={(event) =>
                updatePacing(
                  "opening_hook_lines",
                  Math.max(3, Math.min(20, Number(event.target.value))),
                )
              }
            />
            <small className="muted">前 N 行必须抓住读者</small>
          </label>

          <label>
            每章场景数
            <input
              type="number"
              min={1}
              max={3}
              value={pacing.scenes_per_chapter}
              onChange={(event) =>
                updatePacing(
                  "scenes_per_chapter",
                  Math.max(1, Math.min(3, Number(event.target.value))),
                )
              }
            />
            <small className="muted">单章场景切换次数</small>
          </label>

          <label>
            开篇钩子风格
            <select
              value={pacing.opening_hook_style}
              onChange={(event) =>
                updatePacing(
                  "opening_hook_style",
                  event.target.value as PlatformPacing["opening_hook_style"],
                )
              }
            >
              <option value="conflict">冲突切入</option>
              <option value="scene">场景切入</option>
              <option value="dialogue">对话切入</option>
            </select>
          </label>

          <label className="toggle-field">
            <input
              type="checkbox"
              checked={pacing.chapter_end_cliffhanger}
              onChange={(event) =>
                updatePacing("chapter_end_cliffhanger", event.target.checked)
              }
            />
            <span>章末钩子必须</span>
          </label>
        </div>
      </section>

      {/* 权重分配 */}
      <section className="rules-card">
        <div className="section-title">
          <h2>权重分配</h2>
          <span>{weightHint}</span>
        </div>
        <div className="form-grid">
          <label>
            连续性权重
            <input
              type="range"
              min={0}
              max={100}
              value={pacing.weight_continuity}
              onChange={(event) =>
                updatePacing("weight_continuity", Number(event.target.value))
              }
            />
            <small className="muted">当前 {pacing.weight_continuity}</small>
          </label>

          <label>
            文风权重
            <input
              type="range"
              min={0}
              max={100}
              value={pacing.weight_style}
              onChange={(event) =>
                updatePacing("weight_style", Number(event.target.value))
              }
            />
            <small className="muted">当前 {pacing.weight_style}</small>
          </label>

          <label>
            商业权重
            <input
              type="range"
              min={0}
              max={100}
              value={pacing.weight_commercial}
              onChange={(event) =>
                updatePacing("weight_commercial", Number(event.target.value))
              }
            />
            <small className="muted">当前 {pacing.weight_commercial}</small>
          </label>
        </div>
        {/* 权重可视化条 */}
        <div className="rules-weight-bar" title={`总和 ${weightTotal}`}>
          <div
            style={{ width: `${pacing.weight_continuity}%`, background: "var(--green)" }}
          />
          <div
            style={{ width: `${pacing.weight_style}%`, background: "var(--blue)" }}
          />
          <div
            style={{ width: `${pacing.weight_commercial}%`, background: "var(--rust)" }}
          />
        </div>
      </section>
    </section>
  );
}
