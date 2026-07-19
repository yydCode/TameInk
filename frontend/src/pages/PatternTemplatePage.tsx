import { useMemo, useState } from "react";
import { Check, GitCompare, Trash2 } from "lucide-react";
import { Link, useParams } from "react-router";

import type { PatternTemplate } from "../api/client";
import { useLocalStorage } from "../hooks/useLocalStorage";

// 已保存的套路模板条目（与 BestsellerAnalyzePage 共享 localStorage key）
interface StoredPatternTemplate {
  template: PatternTemplate;
  savedAt: string;
}

/**
 * 套路模板页面
 * 展示爆款拆解保存下来的模板，支持详情查看、激活、对比
 */
export function PatternTemplatePage() {
  const { projectId = "" } = useParams();

  // 模板列表（与 BestsellerAnalyzePage 共享 key）
  const [storedTemplates, setStoredTemplates] = useLocalStorage<StoredPatternTemplate[]>(
    `tame-ink:pattern-templates:${projectId}`,
    [],
  );
  // 当前激活的模板
  const [activeTemplate, setActiveTemplate] = useLocalStorage<StoredPatternTemplate | null>(
    `tame-ink:active-template:${projectId}`,
    null,
  );

  // 当前展开详情的模板索引
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);
  // 对比模式选中的两个模板索引
  const [compareSelection, setCompareSelection] = useState<number[]>([]);
  // 是否处于对比模式
  const [compareMode, setCompareMode] = useState(false);

  // 删除模板
  function handleDelete(index: number) {
    const removed = storedTemplates[index];
    const next = storedTemplates.filter((_, i) => i !== index);
    setStoredTemplates(next);
    // 若删除的是激活模板，清空激活状态
    if (activeTemplate && activeTemplate.savedAt === removed.savedAt) {
      setActiveTemplate(null);
    }
    // 调整展开索引
    if (expandedIndex === index) {
      setExpandedIndex(null);
    } else if (expandedIndex !== null && expandedIndex > index) {
      setExpandedIndex(expandedIndex - 1);
    }
    // 调整对比选择
    setCompareSelection((prev) =>
      prev
        .filter((i) => i !== index)
        .map((i) => (i > index ? i - 1 : i)),
    );
  }

  // 展开/收起详情
  function toggleDetail(index: number) {
    setExpandedIndex(expandedIndex === index ? null : index);
  }

  // 应用为当前项目的激活模板
  function handleActivate(index: number) {
    setActiveTemplate(storedTemplates[index]);
  }

  // 切换对比选择
  function toggleCompareSelection(index: number) {
    setCompareSelection((prev) => {
      if (prev.includes(index)) {
        return prev.filter((i) => i !== index);
      }
      if (prev.length >= 2) {
        // 最多选两个，超过则替换最早的
        return [prev[1], index];
      }
      return [...prev, index];
    });
  }

  // 进入/退出对比模式
  function toggleCompareMode() {
    if (compareMode) {
      setCompareMode(false);
      setCompareSelection([]);
    } else {
      setCompareMode(true);
      setExpandedIndex(null);
    }
  }

  // 待对比的两个模板
  const compareTargets = useMemo(() => {
    if (compareSelection.length !== 2) return null;
    return [storedTemplates[compareSelection[0]], storedTemplates[compareSelection[1]]];
  }, [compareSelection, storedTemplates]);

  // 空态
  if (storedTemplates.length === 0) {
    return (
      <section className="pattern-page">
        <header className="project-heading">
          <div>
            <span className="eyebrow">套路模板</span>
            <h1>套路模板</h1>
            <p>从爆款拆解中提炼的可复用模板，可激活后指导新作品创作。</p>
          </div>
        </header>
        <div className="pattern-empty">
          <p className="muted">还没有模板，去</p>
          <Link className="button button-primary" to={`/projects/${projectId}/bestseller`}>
            爆款拆解页面
          </Link>
          <p className="muted">创建一个</p>
        </div>
      </section>
    );
  }

  return (
    <section className="pattern-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">套路模板</span>
          <h1>套路模板</h1>
          <p>
            共 {storedTemplates.length} 个模板
            {activeTemplate && (
              <span className="pattern-active-tip">
                · 当前激活：<strong>{activeTemplate.template.template_name}</strong>
              </span>
            )}
          </p>
        </div>
        <div className="header-actions">
          <Link className="button button-secondary" to={`/projects/${projectId}/bestseller`}>
            新建拆解
          </Link>
          <button
            className={`button ${compareMode ? "button-primary" : "button-secondary"}`}
            type="button"
            onClick={toggleCompareMode}
          >
            <GitCompare size={15} />
            {compareMode ? "退出对比" : "对比模式"}
          </button>
        </div>
      </header>

      {/* 对比模式提示条 */}
      {compareMode && (
        <div className="pattern-compare-tip">
          {compareSelection.length === 0 && "请选择第一个模板"}
          {compareSelection.length === 1 && "请选择第二个模板"}
          {compareSelection.length === 2 && "已选择两个模板，下方查看对比"}
        </div>
      )}

      {/* 模板卡片列表 */}
      <div className="pattern-grid">
        {storedTemplates.map((stored, index) => {
          const template = stored.template;
          const isExpanded = expandedIndex === index;
          const isSelected = compareSelection.includes(index);
          const isActive = activeTemplate?.savedAt === stored.savedAt;
          return (
            <article
              key={`${stored.savedAt}-${index}`}
              className={`pattern-card${isExpanded ? " is-expanded" : ""}${isSelected ? " is-selected" : ""}${isActive ? " is-active" : ""}`}
            >
              <div className="pattern-card-head">
                <div className="pattern-card-title">
                  <strong>{template.template_name}</strong>
                  {isActive && <span className="pattern-badge pattern-badge--active">已激活</span>}
                </div>
                <small className="muted">{new Date(stored.savedAt).toLocaleDateString("zh-CN")}</small>
              </div>
              <div className="pattern-card-meta">
                <span>来源：<strong>{template.source_title}</strong></span>
                <span>题材：<strong>{template.genre}</strong></span>
                <span>爽点密度：<strong>{template.climax_density.toFixed(2)}/章</strong></span>
              </div>
              <div className="pattern-card-actions">
                {compareMode ? (
                  <button
                    className="button button-secondary"
                    type="button"
                    onClick={() => toggleCompareSelection(index)}
                  >
                    {isSelected ? "取消选择" : "选择对比"}
                  </button>
                ) : (
                  <>
                    <button
                      className="button button-secondary"
                      type="button"
                      onClick={() => toggleDetail(index)}
                    >
                      {isExpanded ? "收起详情" : "查看详情"}
                    </button>
                    <button
                      className="button button-secondary"
                      type="button"
                      onClick={() => handleDelete(index)}
                    >
                      <Trash2 size={14} />
                      删除
                    </button>
                    <button
                      className="button button-primary"
                      type="button"
                      onClick={() => handleActivate(index)}
                      disabled={isActive}
                    >
                      <Check size={14} />
                      {isActive ? "已激活" : "应用此模板"}
                    </button>
                  </>
                )}
              </div>
              {isExpanded && <PatternDetail template={template} />}
            </article>
          );
        })}
      </div>

      {/* 对比结果 */}
      {compareMode && compareTargets && (
        <PatternCompare a={compareTargets[0].template} b={compareTargets[1].template} />
      )}
    </section>
  );
}

/**
 * 模板详情
 * 展示模板的全部字段
 */
function PatternDetail({ template }: { template: PatternTemplate }) {
  return (
    <div className="pattern-detail">
      <div className="pattern-detail-row">
        <small>章节字数范围</small>
        <span>{template.chapter_length_range[0]} ~ {template.chapter_length_range[1]} 字</span>
      </div>
      <div className="pattern-detail-row">
        <small>对话占比范围</small>
        <span>{(template.dialogue_ratio_range[0] * 100).toFixed(0)}% ~ {(template.dialogue_ratio_range[1] * 100).toFixed(0)}%</span>
      </div>
      <div className="pattern-detail-row">
        <small>段落最大长度建议</small>
        <span>{template.paragraph_length_max} 字</span>
      </div>
      <div className="pattern-detail-row">
        <small>爽点密度</small>
        <span>{template.climax_density.toFixed(2)} /章</span>
      </div>
      <div className="pattern-detail-row pattern-detail-row--column">
        <small>钩子类型分布</small>
        <div className="pattern-hook-list">
          {Object.entries(template.hook_distribution).length === 0 ? (
            <span className="muted">—</span>
          ) : (
            Object.entries(template.hook_distribution).map(([type, count]) => (
              <span key={type} className="pattern-hook-pill">
                {type} <strong>{count}</strong>
              </span>
            ))
          )}
        </div>
      </div>
      <div className="pattern-detail-row pattern-detail-row--column">
        <small>建议章节结构</small>
        <ol className="pattern-structure-list">
          {template.chapter_structure.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
      </div>
      {template.notes && (
        <div className="pattern-detail-row pattern-detail-row--column">
          <small>使用备注</small>
          <p>{template.notes}</p>
        </div>
      )}
    </div>
  );
}

/**
 * 模板对比
 * 选择两个模板，按维度展示差异
 */
function PatternCompare({ a, b }: { a: PatternTemplate; b: PatternTemplate }) {
  // 钩子分布合并后的所有类型
  const hookTypes = useMemo(() => {
    const set = new Set<string>([
      ...Object.keys(a.hook_distribution),
      ...Object.keys(b.hook_distribution),
    ]);
    return Array.from(set);
  }, [a.hook_distribution, b.hook_distribution]);

  const rows: Array<{ label: string; a: string; b: string }> = [
    { label: "模板名称", a: a.template_name, b: b.template_name },
    { label: "来源爆款", a: a.source_title, b: b.source_title },
    { label: "适用题材", a: a.genre, b: b.genre },
    {
      label: "章节字数范围",
      a: `${a.chapter_length_range[0]} ~ ${a.chapter_length_range[1]} 字`,
      b: `${b.chapter_length_range[0]} ~ ${b.chapter_length_range[1]} 字`,
    },
    {
      label: "对话占比范围",
      a: `${(a.dialogue_ratio_range[0] * 100).toFixed(0)}% ~ ${(a.dialogue_ratio_range[1] * 100).toFixed(0)}%`,
      b: `${(b.dialogue_ratio_range[0] * 100).toFixed(0)}% ~ ${(b.dialogue_ratio_range[1] * 100).toFixed(0)}%`,
    },
    {
      label: "段落最大长度",
      a: `${a.paragraph_length_max} 字`,
      b: `${b.paragraph_length_max} 字`,
    },
    {
      label: "爽点密度",
      a: `${a.climax_density.toFixed(2)} /章`,
      b: `${b.climax_density.toFixed(2)} /章`,
    },
    {
      label: "建议章节结构",
      a: a.chapter_structure.join(" → "),
      b: b.chapter_structure.join(" → "),
    },
    {
      label: "使用备注",
      a: a.notes || "—",
      b: b.notes || "—",
    },
  ];

  // 钩子分布对比行
  hookTypes.forEach((type) => {
    rows.push({
      label: `钩子：${type}`,
      a: String(a.hook_distribution[type] ?? 0),
      b: String(b.hook_distribution[type] ?? 0),
    });
  });

  return (
    <section className="pattern-compare-card">
      <div className="section-title">
        <h2>模板对比</h2>
        <span>{a.template_name} vs {b.template_name}</span>
      </div>
      <div className="pattern-compare-table">
        <div className="pattern-compare-head">
          <span>维度</span>
          <span>模板 A</span>
          <span>模板 B</span>
        </div>
        {rows.map((row, i) => (
          <div key={i} className="pattern-compare-row">
            <span className="pattern-compare-label">{row.label}</span>
            <span>{row.a}</span>
            <span>{row.b}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
