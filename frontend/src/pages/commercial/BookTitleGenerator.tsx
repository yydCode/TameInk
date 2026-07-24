import { useEffect, useMemo, useState } from "react";
import { Check, Plus, Sparkles, Star, Trash2 } from "lucide-react";

import type { CommercialProfile } from "../../api/client";
import { useLocalStorage } from "../../hooks/useLocalStorage";

// 书名候选条目（作者手动添加的本地候选）
interface TitleCandidate {
  id: string;
  title: string;
  template: string; // 使用的题材模板名称
  score?: number; // 作者评分（1-5）
  selected: boolean; // 是否选中
}

// 三段式简介组成
interface SynopsisParts {
  hook: string; // 钩子：一句话抓住读者
  setting: string; // 核心设定：金手指+爽点
  promise: string; // 期待感：后续剧情承诺
}

// 题材模板预设：每种流派对应一个命名结构
const TITLE_TEMPLATES = [
  { value: "系统流", pattern: "《开局+金手指+爽点》" },
  { value: "重生流", pattern: "《重生年代+身份+逆袭》" },
  { value: "签到流", pattern: "《签到XX年+出世即无敌》" },
  { value: "脑洞流", pattern: "《奇葩设定+核心冲突》" },
  { value: "都市爽文", pattern: "《身份反转+打脸》" },
] as const;

// 热门标签静态建议列表（番茄/起点常见引流标签）
const HOT_TAGS = [
  "穿越", "重生", "系统", "签到", "无敌流", "爽文", "种田", "宫斗",
  "玄幻", "都市", "末世", "科幻", "悬疑", "历史", "军事", "游戏",
  "打脸", "逆袭", "扮猪吃虎", "金手指", "群像", "单女主", "快节奏",
];

// 简单 ID 生成器（避免引入额外依赖）
function makeId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

interface BookTitleGeneratorProps {
  projectId: string;
  // 商业定位（含 AI 生成的 title_candidates 和 synopsis）
  profile: CommercialProfile | null;
  // 当前是否有商业定位任务处于 awaiting_approval（决定是否能"选中回写"）
  canAdopt: boolean;
  // 作者选中某 AI 候选书名时触发（由 CommercialPage 写入 profile 并保存）
  onAdoptTitle: (title: string) => void;
  // 作者采纳 AI 简介时触发（拆分为三段式后写入本地）
  onAdoptSynopsis: (synopsis: string) => void;
}

/**
 * 书名简介生成器
 *
 * 数据来源：
 * 1. AI 候选（来自 CommercialProfile.title_candidates / synopsis）—— 由 MarketStrategist 生成
 * 2. 作者手动添加的候选 —— 存 localStorage
 *
 * 人决策、AI 执行：
 * - AI 候选只读展示，作者点「选中」通过 onAdoptTitle 回写到 profile（仅 task awaiting_approval 时可用）
 * - 作者手动添加的候选独立 localStorage，与 AI 候选互不干扰
 */
export function BookTitleGenerator({
  projectId,
  profile,
  canAdopt,
  onAdoptTitle,
  onAdoptSynopsis,
}: BookTitleGeneratorProps) {
  const storageKey = `tame-ink:book-title:${projectId}`;

  // 作者手动添加的候选 + 三段式简介 + 标签
  const [state, setState] = useLocalStorage<{
    template: string;
    candidates: TitleCandidate[];
    parts: SynopsisParts;
    synopsis: string;
    tags: string[];
    tagInput: string;
  }>(storageKey, {
    template: TITLE_TEMPLATES[0].value,
    candidates: [],
    parts: { hook: "", setting: "", promise: "" },
    synopsis: "",
    tags: [],
    tagInput: "",
  });

  // 新书名输入框（非持久化，仅当前会话）
  const [newTitle, setNewTitle] = useState("");
  // 当前已采纳的 AI 候选书名（用于 UI 高亮）
  const [adoptedAiTitle, setAdoptedAiTitle] = useState<string | null>(null);

  // 当 profile 的 title_candidates 首项变化时，同步"已采纳"状态
  // 约定：title_candidates[0] 是作者最终选中的书名
  useEffect(() => {
    if (profile?.title_candidates?.length) {
      setAdoptedAiTitle(profile.title_candidates[0]);
    }
  }, [profile?.title_candidates]);

  // 当前模板的命名结构提示
  const currentPattern = useMemo(
    () => TITLE_TEMPLATES.find((t) => t.value === state.template)?.pattern ?? "",
    [state.template],
  );

  // 修改题材模板
  function changeTemplate(value: string) {
    setState((prev) => ({ ...prev, template: value }));
  }

  // 添加书名候选（作者手动添加）
  function addCandidate() {
    const title = newTitle.trim();
    if (!title) return;
    const candidate: TitleCandidate = {
      id: makeId(),
      title,
      template: state.template,
      selected: false,
    };
    setState((prev) => ({
      ...prev,
      candidates: [...prev.candidates, candidate],
    }));
    setNewTitle("");
  }

  // 删除指定书名候选（仅作者手动添加的）
  function removeCandidate(id: string) {
    setState((prev) => ({
      ...prev,
      candidates: prev.candidates.filter((c) => c.id !== id),
    }));
  }

  // 设置书名评分（1-5 星点击，仅作者手动添加的）
  function scoreCandidate(id: string, score: number) {
    setState((prev) => ({
      ...prev,
      candidates: prev.candidates.map((c) =>
        c.id === id ? { ...c, score } : c,
      ),
    }));
  }

  // 切换书名选中状态（仅作者手动添加的；AI 候选用 onAdoptTitle）
  function toggleCandidate(id: string) {
    setState((prev) => ({
      ...prev,
      candidates: prev.candidates.map((c) =>
        c.id === id ? { ...c, selected: !c.selected } : { ...c, selected: false },
      ),
    }));
  }

  // 修改三段式简介中某一段
  function updatePart(key: keyof SynopsisParts, value: string) {
    setState((prev) => ({
      ...prev,
      parts: { ...prev.parts, [key]: value },
    }));
  }

  // 拼接三段为完整简介
  function generateSynopsis() {
    const { hook, setting, promise } = state.parts;
    const segments = [hook, setting, promise]
      .map((s) => s.trim())
      .filter(Boolean);
    if (segments.length === 0) return;
    setState((prev) => ({
      ...prev,
      synopsis: segments.join("\n\n"),
    }));
  }

  // 采纳 AI 简介：把 profile.synopsis 整体写入本地 synopsis，并尝试拆分为三段
  function adoptAiSynopsis() {
    if (!profile?.synopsis) return;
    // 简单拆分：按双换行分段，前 1 段为 hook，第 2 段为 setting，剩余合并为 promise
    const segments = profile.synopsis.split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean);
    const hook = segments[0] ?? "";
    const setting = segments[1] ?? "";
    const promise = segments.slice(2).join("\n\n");
    setState((prev) => ({
      ...prev,
      parts: { hook, setting, promise },
      synopsis: profile.synopsis,
    }));
    onAdoptSynopsis(profile.synopsis);
  }

  // 添加自定义标签
  function addTag() {
    const tag = state.tagInput.trim();
    if (!tag) return;
    if (state.tags.includes(tag)) {
      setState((prev) => ({ ...prev, tagInput: "" }));
      return;
    }
    setState((prev) => ({
      ...prev,
      tags: [...prev.tags, tag],
      tagInput: "",
    }));
  }

  // 从热门标签中快速添加
  function addHotTag(tag: string) {
    setState((prev) =>
      prev.tags.includes(tag)
        ? prev
        : { ...prev, tags: [...prev.tags, tag] },
    );
  }

  // 删除已选标签
  function removeTag(tag: string) {
    setState((prev) => ({
      ...prev,
      tags: prev.tags.filter((t) => t !== tag),
    }));
  }

  // AI 候选书名（来自 profile.title_candidates）
  const aiCandidates = profile?.title_candidates ?? [];
  const aiSynopsis = profile?.synopsis ?? "";

  return (
    <section className="book-title-section">
      <div className="section-title">
        <h2>书名简介生成器</h2>
        <span>AI 候选 · 题材模板 · 三段式简介</span>
      </div>

      {/* AI 候选书名（来自 MarketStrategist） */}
      {aiCandidates.length > 0 && (
        <div className="ai-title-block">
          <h3 className="ai-block-title">AI 候选书名</h3>
          <p className="muted ai-block-hint">
            来自商业定位 AI 生成。点「选中」可置顶为最终书名（写入商业定位候选）。
            {!canAdopt && " 当前无候选定位任务，仅展示不能选中。"}
          </p>
          <div className="title-candidate-list">
            {aiCandidates.map((title, index) => {
              const isAdopted = adoptedAiTitle === title || index === 0 && adoptedAiTitle === null;
              return (
                <div
                  key={`ai-${index}-${title}`}
                  className={`title-candidate-item${isAdopted ? " is-selected" : ""}`}
                >
                  <button
                    type="button"
                    className={`title-select-button${isAdopted ? " is-active" : ""}`}
                    onClick={() => {
                      if (!canAdopt) return;
                      onAdoptTitle(title);
                      setAdoptedAiTitle(title);
                    }}
                    disabled={!canAdopt}
                    title={
                      canAdopt
                        ? isAdopted
                          ? "已选为最终书名"
                          : "设为最终书名"
                        : "需要候选定位任务处于待审批状态"
                    }
                    aria-label={isAdopted ? "已选中" : "设为最终书名"}
                  >
                    {isAdopted ? <Check size={14} /> : "○"}
                  </button>
                  <div className="title-candidate-main">
                    <strong className="title-text">{title}</strong>
                    <span className="title-template-tag">AI 候选 {index + 1}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 题材模板选择 + 手动添加候选 */}
      <div className="book-title-form">
        <label>
          题材模板
          <select
            value={state.template}
            onChange={(event) => changeTemplate(event.target.value)}
          >
            {TITLE_TEMPLATES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.value} — {t.pattern}
              </option>
            ))}
          </select>
        </label>
        <label>
          当前模板命名结构
          <input value={currentPattern} readOnly />
        </label>
        <label>
          添加书名候选
          <div className="title-input-row">
            <input
              value={newTitle}
              onChange={(event) => setNewTitle(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") addCandidate();
              }}
              placeholder={`按 ${currentPattern} 思路起名`}
            />
            <button
              type="button"
              className="button button-primary"
              onClick={addCandidate}
              disabled={!newTitle.trim()}
            >
              <Plus size={14} />
              添加
            </button>
          </div>
        </label>
      </div>

      {/* 作者手动添加的书名候选列表 */}
      <div className="title-candidate-list">
        {state.candidates.length === 0 ? (
          <p className="muted empty-hint">
            暂无作者添加的候选。可基于题材模板手动起名，或参考上方 AI 候选。
          </p>
        ) : (
          state.candidates.map((c) => (
            <div
              key={c.id}
              className={`title-candidate-item${c.selected ? " is-selected" : ""}`}
            >
              <button
                type="button"
                className={`title-select-button${c.selected ? " is-active" : ""}`}
                onClick={() => toggleCandidate(c.id)}
                title={c.selected ? "取消选中" : "设为最终书名"}
                aria-label={c.selected ? "取消选中" : "设为最终书名"}
              >
                {c.selected ? "✓" : "○"}
              </button>
              <div className="title-candidate-main">
                <strong className="title-text">{c.title}</strong>
                <span className="title-template-tag">{c.template}</span>
              </div>
              <div className="title-score" role="radiogroup" aria-label="评分">
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    type="button"
                    className={`star-button${(c.score ?? 0) >= star ? " is-on" : ""}`}
                    onClick={() => scoreCandidate(c.id, star)}
                    aria-label={`${star} 星`}
                  >
                    <Star size={13} />
                  </button>
                ))}
              </div>
              <button
                type="button"
                className="icon-button"
                onClick={() => removeCandidate(c.id)}
                aria-label="删除候选"
                title="删除候选"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))
        )}
      </div>

      {/* AI 简介（来自 MarketStrategist） */}
      {aiSynopsis && (
        <div className="ai-synopsis-block">
          <div className="ai-synopsis-header">
            <h3 className="ai-block-title">AI 简介</h3>
            <button
              type="button"
              className="button button-secondary"
              onClick={adoptAiSynopsis}
              title="把 AI 简介拆分到三段式并采纳"
            >
              <Check size={14} />
              采纳 AI 简介
            </button>
          </div>
          <pre className="ai-synopsis-preview">{aiSynopsis}</pre>
        </div>
      )}

      {/* 三段式简介（作者编辑区） */}
      <div className="synopsis-grid">
        <label>
          钩子（一句话抓住读者）
          <textarea
            value={state.parts.hook}
            onChange={(event) => updatePart("hook", event.target.value)}
            placeholder="例：被嫡姐毒杀那天，她重生回了十六岁。"
          />
        </label>
        <label>
          核心设定（金手指+爽点）
          <textarea
            value={state.parts.setting}
            onChange={(event) => updatePart("setting", event.target.value)}
            placeholder="例：觉醒传承玉佩，可鉴定万物价值，捡漏逆袭。"
          />
        </label>
        <label>
          期待感（后续剧情承诺）
          <textarea
            value={state.parts.promise}
            onChange={(event) => updatePart("promise", event.target.value)}
            placeholder="例：从废柴到京城第一鉴宝师，每个仇人都要付出代价。"
          />
        </label>
      </div>
      <div className="synopsis-actions">
        <button
          type="button"
          className="button button-primary"
          onClick={generateSynopsis}
          disabled={
            !state.parts.hook.trim() &&
            !state.parts.setting.trim() &&
            !state.parts.promise.trim()
          }
        >
          <Sparkles size={14} />
          生成简介
        </button>
      </div>
      {state.synopsis && (
        <div className="synopsis-preview">
          <h3>完整简介</h3>
          <pre>{state.synopsis}</pre>
        </div>
      )}

      {/* 标签关键词优化建议 */}
      <div className="tag-section">
        <h3>标签关键词</h3>
        <div className="title-input-row">
          <input
            value={state.tagInput}
            onChange={(event) =>
              setState((prev) => ({ ...prev, tagInput: event.target.value }))
            }
            onKeyDown={(event) => {
              if (event.key === "Enter") addTag();
            }}
            placeholder="输入自定义标签后回车"
          />
          <button
            type="button"
            className="button button-secondary"
            onClick={addTag}
            disabled={!state.tagInput.trim()}
          >
            <Plus size={14} />
            添加标签
          </button>
        </div>
        {state.tags.length > 0 && (
          <div className="tag-list">
            {state.tags.map((tag) => (
              <span key={tag} className="tag-chip is-mine">
                {tag}
                <button
                  type="button"
                  onClick={() => removeTag(tag)}
                  aria-label={`移除 ${tag}`}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
        <h4>热门标签建议</h4>
        <div className="tag-list">
          {HOT_TAGS.map((tag) => (
            <button
              key={tag}
              type="button"
              className={`tag-chip${state.tags.includes(tag) ? " is-picked" : ""}`}
              onClick={() => addHotTag(tag)}
              disabled={state.tags.includes(tag)}
            >
              {tag}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
