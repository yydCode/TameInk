import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Save, Sparkles } from "lucide-react";
import { Link, useParams } from "react-router";

import {
  type BestsellerAnalysis,
  type ChapterAnalysis,
  analyzeBestseller,
  buildPatternTemplate,
} from "../api/client";
import { useLocalStorage } from "../hooks/useLocalStorage";

// 已保存的套路模板列表（与 PatternTemplatePage 共享 localStorage key）
interface StoredPatternTemplate {
  template: import("../api/client").PatternTemplate;
  savedAt: string;
}

// 题材下拉选项
const GENRE_OPTIONS = [
  "系统流",
  "重生流",
  "签到流",
  "脑洞流",
  "都市爽文",
  "其他",
] as const;

// 章节分隔正则：匹配 "第X章" 或 "第X回" 等
const CHAPTER_SPLIT_REGEX = /\n\s*第[零一二三四五六七八九十百千0-9]+[章回卷]\s*[^\n]*\n/;

/**
 * 将粘贴的爆款全文按章节标题切分
 * 支持多章粘贴，章节标题形如 "第一章 标题"、"第1章 标题"、"第123回 标题"
 */
function splitChapters(rawText: string): string[] {
  const text = rawText.trim();
  if (!text) return [];
  // 用正则切分，保留分隔符
  const parts = text.split(CHAPTER_SPLIT_REGEX).map((part) => part.trim()).filter(Boolean);
  // 如果切分后只有一段且没有匹配到章节标题，则整体作为单章返回
  if (parts.length === 1) return parts;
  return parts;
}

/**
 * 爆款拆解页面
 * 作者粘贴爆款全文，AI 拆解为可复用的套路模板
 */
export function BestsellerAnalyzePage() {
  const { projectId = "" } = useParams();

  // 输入区表单状态
  const [sourceTitle, setSourceTitle] = useState("");
  const [sourceGenre, setSourceGenre] = useState<string>(GENRE_OPTIONS[0]);
  const [rawText, setRawText] = useState("");

  // 拆解结果（不存 localStorage，刷新即清空，避免污染多个作品）
  const [analysis, setAnalysis] = useState<BestsellerAnalysis | null>(null);
  const [errorMsg, setErrorMsg] = useState<string>("");

  // 保存模板对话框状态
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [saveTip, setSaveTip] = useState("");

  // 已保存的模板列表（与 PatternTemplatePage 共享 key）
  const [storedTemplates, setStoredTemplates] = useLocalStorage<StoredPatternTemplate[]>(
    `tame-ink:pattern-templates:${projectId}`,
    [],
  );

  // 调用拆解 API
  const analyzeMutation = useMutation({
    mutationFn: () => {
      const chapters = splitChapters(rawText);
      if (chapters.length === 0) {
        throw new Error("请粘贴爆款全文，至少包含一个章节");
      }
      if (!sourceTitle.trim()) {
        throw new Error("请填写书名");
      }
      return analyzeBestseller(projectId, sourceTitle.trim(), sourceGenre, chapters);
    },
    onSuccess: (data) => {
      setAnalysis(data);
      setErrorMsg("");
    },
    onError: (error: unknown) => {
      setAnalysis(null);
      setErrorMsg(error instanceof Error ? error.message : "拆解失败，请重试");
    },
  });

  // 调用保存模板 API
  const saveTemplateMutation = useMutation({
    mutationFn: (name: string) => {
      if (!analysis) throw new Error("请先完成拆解");
      if (!name.trim()) throw new Error("请填写模板名称");
      return buildPatternTemplate(projectId, analysis, name.trim());
    },
    onSuccess: (template) => {
      // 存入 localStorage，与套路模板页面共享
      setStoredTemplates([
        ...storedTemplates,
        { template, savedAt: new Date().toISOString() },
      ]);
      setSaveTip("模板已保存，可在套路模板页面查看");
      setShowSaveDialog(false);
      setTemplateName("");
    },
    onError: (error: unknown) => {
      setSaveTip(error instanceof Error ? error.message : "保存失败，请重试");
    },
  });

  // 预览章节切分结果
  const chapterPreview = useMemo(() => splitChapters(rawText), [rawText]);

  // 拆解按钮处理
  function handleAnalyze() {
    setSaveTip("");
    analyzeMutation.mutate();
  }

  // 保存模板按钮处理
  function handleSaveTemplate() {
    setSaveTip("");
    saveTemplateMutation.mutate(templateName);
  }

  return (
    <section className="bestseller-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">爆款拆解</span>
          <h1>爆款拆解</h1>
          <p>粘贴一本爆款小说的全文，AI 拆解出可复用的套路模板。</p>
        </div>
        <div className="header-actions">
          <Link className="button button-secondary" to={`/projects/${projectId}/patterns`}>
            <Sparkles size={15} />
            套路模板
          </Link>
        </div>
      </header>

      {/* 1. 导入爆款文本区 */}
      <section className="bestseller-input-card">
        <div className="section-title">
          <h2>导入爆款文本</h2>
          <span>支持多章粘贴</span>
        </div>
        <div className="bestseller-form">
          <label className="bestseller-field">
            <span>书名</span>
            <input
              type="text"
              value={sourceTitle}
              onChange={(event) => setSourceTitle(event.target.value)}
              placeholder="例如：斗破苍穹"
            />
          </label>
          <label className="bestseller-field">
            <span>题材</span>
            <select
              value={sourceGenre}
              onChange={(event) => setSourceGenre(event.target.value)}
            >
              {GENRE_OPTIONS.map((genre) => (
                <option key={genre} value={genre}>{genre}</option>
              ))}
            </select>
          </label>
          <label className="bestseller-field bestseller-field--full">
            <span>爆款全文</span>
            <textarea
              value={rawText}
              onChange={(event) => setRawText(event.target.value)}
              placeholder="粘贴爆款全文。每章以『第X章 标题』开头，AI 会自动切分。"
              rows={10}
            />
            <small className="muted">
              已识别 {chapterPreview.length} 章 · 共 {rawText.length.toLocaleString("zh-CN")} 字符
            </small>
          </label>
        </div>
        <div className="bestseller-actions">
          <button
            className="button button-primary"
            type="button"
            onClick={handleAnalyze}
            disabled={analyzeMutation.isPending}
          >
            {analyzeMutation.isPending ? "拆解中..." : "拆解"}
          </button>
          {errorMsg && <span className="inline-error">{errorMsg}</span>}
        </div>
      </section>

      {/* 2. 拆解结果展示区 */}
      {analysis && (
        <AnalysisResult
          analysis={analysis}
          onSaveAsTemplate={() => {
            setSaveTip("");
            setShowSaveDialog(true);
          }}
        />
      )}

      {/* 3. 保存为模板对话框 */}
      {showSaveDialog && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal-card">
            <div className="modal-header">
              <h3>保存为套路模板</h3>
              <button
                className="icon-button"
                type="button"
                onClick={() => setShowSaveDialog(false)}
                aria-label="关闭"
              >
                ✕
              </button>
            </div>
            <div className="modal-body">
              <label className="bestseller-field">
                <span>模板名称</span>
                <input
                  type="text"
                  value={templateName}
                  onChange={(event) => setTemplateName(event.target.value)}
                  placeholder="例如：系统流爽文模板"
                  autoFocus
                />
              </label>
              {saveTip && <p className="modal-tip">{saveTip}</p>}
            </div>
            <div className="modal-footer">
              <button
                className="button button-secondary"
                type="button"
                onClick={() => setShowSaveDialog(false)}
              >
                取消
              </button>
              <button
                className="button button-primary"
                type="button"
                onClick={handleSaveTemplate}
                disabled={saveTemplateMutation.isPending}
              >
                {saveTemplateMutation.isPending ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

/**
 * 拆解结果展示区
 * - 整体统计卡片
 * - 钩子类型分布柱状图（纯 CSS）
 * - 逐章拆解表格（可展开）
 */
function AnalysisResult({
  analysis,
  onSaveAsTemplate,
}: {
  analysis: BestsellerAnalysis;
  onSaveAsTemplate: () => void;
}) {
  return (
    <>
      {/* 整体统计卡片 */}
      <section className="bestseller-stats-card">
        <div className="section-title">
          <h2>整体统计</h2>
          <span>{analysis.source_title} · {analysis.source_genre}</span>
        </div>
        <div className="bestseller-stats-grid">
          <StatItem label="总字数" value={`${analysis.total_words.toLocaleString("zh-CN")} 字`} />
          <StatItem label="总章节数" value={`${analysis.total_chapters} 章`} />
          <StatItem label="平均每章字数" value={`${analysis.avg_chapter_words.toLocaleString("zh-CN")} 字`} />
          <StatItem label="平均对话占比" value={`${(analysis.avg_dialogue_ratio * 100).toFixed(1)}%`} />
          <StatItem label="平均段落长度" value={`${analysis.avg_paragraph_length.toFixed(1)} 字`} />
          <StatItem label="爽点密度" value={`${analysis.climax_density.toFixed(2)} /章`} />
        </div>
        {analysis.overall_pattern && (
          <div className="bestseller-pattern-summary">
            <small className="muted">整体套路总结</small>
            <p>{analysis.overall_pattern}</p>
          </div>
        )}
        <div className="bestseller-actions">
          <button className="button button-primary" type="button" onClick={onSaveAsTemplate}>
            <Save size={14} />
            保存为模板
          </button>
        </div>
      </section>

      {/* 钩子类型分布柱状图 */}
      <section className="bestseller-stats-card">
        <div className="section-title">
          <h2>钩子类型分布</h2>
        </div>
        <HookDistributionChart distribution={analysis.hook_type_distribution} />
      </section>

      {/* 逐章拆解表格 */}
      <section className="bestseller-stats-card">
        <div className="section-title">
          <h2>逐章拆解</h2>
          <span>{analysis.chapter_analyses.length} 章</span>
        </div>
        <ChapterAnalysisTable chapters={analysis.chapter_analyses} />
      </section>
    </>
  );
}

// 统计小卡片
function StatItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="bestseller-stat-item">
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}

/**
 * 钩子类型分布柱状图（纯 CSS）
 * 不依赖任何图表库
 */
function HookDistributionChart({ distribution }: { distribution: Record<string, number> }) {
  const entries = Object.entries(distribution);
  if (entries.length === 0) {
    return <p className="muted">暂无钩子分布数据</p>;
  }
  const maxValue = Math.max(...entries.map(([, count]) => count), 1);
  return (
    <div className="hook-chart">
      {entries.map(([type, count]) => {
        const percent = (count / maxValue) * 100;
        return (
          <div key={type} className="hook-chart-row">
            <span className="hook-chart-label">{type}</span>
            <div className="hook-chart-bar">
              <div className="hook-chart-fill" style={{ width: `${percent}%` }} />
            </div>
            <span className="hook-chart-value">{count}</span>
          </div>
        );
      })}
    </div>
  );
}

/**
 * 逐章拆解表格
 * 列：章节号/字数/对话占比/钩子类型/爽点数/爽点位置/关键事件/摘要
 * 支持展开查看详情
 */
function ChapterAnalysisTable({ chapters }: { chapters: ChapterAnalysis[] }) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  function toggle(index: number) {
    setExpandedIndex(expandedIndex === index ? null : index);
  }

  return (
    <div className="chapter-table">
      <div className="chapter-table-head">
        <span>章号</span>
        <span>字数</span>
        <span>对话占比</span>
        <span>钩子类型</span>
        <span>爽点数</span>
        <span>摘要</span>
        <span />
      </div>
      {chapters.map((chapter, index) => {
        const isExpanded = expandedIndex === index;
        return (
          <div key={chapter.chapter_index} className="chapter-table-row-wrapper">
            <button
              type="button"
              className={`chapter-table-row${isExpanded ? " is-expanded" : ""}`}
              onClick={() => toggle(index)}
            >
              <span className="chapter-cell chapter-cell-id">第 {chapter.chapter_index} 章</span>
              <span className="chapter-cell">{chapter.word_count.toLocaleString("zh-CN")}</span>
              <span className="chapter-cell">{(chapter.dialogue_ratio * 100).toFixed(1)}%</span>
              <span className="chapter-cell chapter-cell-hook">{chapter.hook_type || "—"}</span>
              <span className="chapter-cell">{chapter.climax_count}</span>
              <span className="chapter-cell chapter-cell-summary">{chapter.summary || "—"}</span>
              <span className="chapter-cell chapter-cell-toggle">
                {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </span>
            </button>
            {isExpanded && (
              <div className="chapter-detail">
                <div className="chapter-detail-row">
                  <small>爽点位置</small>
                  <span>{chapter.climax_positions.length ? chapter.climax_positions.join("、") : "—"}</span>
                </div>
                <div className="chapter-detail-row">
                  <small>关键事件</small>
                  <ul>
                    {chapter.key_events.length ? (
                      chapter.key_events.map((event, i) => <li key={i}>{event}</li>)
                    ) : (
                      <li>—</li>
                    )}
                  </ul>
                </div>
                <div className="chapter-detail-row">
                  <small>平均段落长度</small>
                  <span>{chapter.avg_paragraph_length.toFixed(1)} 字</span>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
