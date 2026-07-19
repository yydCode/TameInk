import { useMemo, useState } from "react";
import { Check } from "lucide-react";
import { useParams } from "react-router";

import { useLocalStorage } from "../hooks/useLocalStorage";

// 开篇节拍
interface Beat {
  id: string;
  chapter: number; // 第几章（1/2/3）
  range: string; // 字数范围，如"0-300"
  label: string; // 节拍名称，如"钩子"
  content: string; // 作者填写的节拍内容
}

// 爽点检查清单项
interface ChecklistItem {
  id: string;
  text: string; // 检查项
  checked: boolean;
}

// 番茄风格检测报告
interface StyleReport {
  totalChars: number;
  paragraphCount: number;
  avgParagraphLength: number;
  dialogueRatio: number;
  longDescriptionParagraphs: Array<{ index: number; length: number; preview: string }>;
}

// 节拍模板（3 章 × 6 节拍 = 18 格）
const BEAT_TEMPLATE: Array<Omit<Beat, "id" | "content">> = [
  { chapter: 1, range: "0-300", label: "钩子" },
  { chapter: 1, range: "300-800", label: "危机" },
  { chapter: 1, range: "800-1500", label: "金手指亮相" },
  { chapter: 1, range: "1500-2000", label: "第一次反转" },
  { chapter: 1, range: "2000-2500", label: "震惊效果" },
  { chapter: 1, range: "2500-3000", label: "章末强钩子" },
  { chapter: 2, range: "0-300", label: "回顾钩子" },
  { chapter: 2, range: "300-800", label: "新冲突" },
  { chapter: 2, range: "800-1500", label: "金手指升级" },
  { chapter: 2, range: "1500-2000", label: "第二次反转" },
  { chapter: 2, range: "2000-2500", label: "震惊效果" },
  { chapter: 2, range: "2500-3000", label: "章末强钩子" },
  { chapter: 3, range: "0-300", label: "回顾钩子" },
  { chapter: 3, range: "300-800", label: "危机升级" },
  { chapter: 3, range: "800-1500", label: "金手指应用" },
  { chapter: 3, range: "1500-2000", label: "高潮反转" },
  { chapter: 3, range: "2000-2500", label: "爽点爆发" },
  { chapter: 3, range: "2500-3000", label: "章末强钩子" },
];

// 默认节拍：基于模板生成，id 保持稳定（按 章号-范围 拼接）
const DEFAULT_BEATS: Beat[] = BEAT_TEMPLATE.map((t) => ({
  id: `beat-${t.chapter}-${t.range}`,
  chapter: t.chapter,
  range: t.range,
  label: t.label,
  content: "",
}));

// 默认爽点检查清单
const DEFAULT_CHECKLIST: ChecklistItem[] = [
  { id: "hook", text: "300字内出钩子", checked: false },
  { id: "golden-finger", text: "第一章亮出金手指", checked: false },
  { id: "first-reversal", text: "第一章有反转", checked: false },
  { id: "end-hook", text: "每章结尾有强钩子", checked: false },
  { id: "protagonist", text: "主角主动出击不被动", checked: false },
];

/**
 * 番茄风格检测：纯前端计算
 * - 平均段落长度（建议 < 50 字）
 * - 对话占比（建议 > 30%）
 * - 描写冗余（连续描写 > 100 字的段落标记）
 */
function analyzeStyle(text: string): StyleReport | null {
  if (!text.trim()) return null;
  // 按空行或换行分段，过滤空段
  const paragraphs = text.split(/\n+/).map((p) => p.trim()).filter(Boolean);
  if (paragraphs.length === 0) return null;

  const totalChars = paragraphs.reduce((sum, p) => sum + p.length, 0);
  const paragraphCount = paragraphs.length;
  const avgParagraphLength = totalChars / paragraphCount;

  // 对话字符：识别中文引号 "" 包裹的内容（包含引号本身）
  let dialogueChars = 0;
  const dialogueRegex = /["“”]([^"“”]+)["”]/g;
  let match: RegExpExecArray | null;
  while ((match = dialogueRegex.exec(text)) !== null) {
    dialogueChars += match[0].length;
  }
  const dialogueRatio = totalChars > 0 ? dialogueChars / totalChars : 0;

  // 描写冗余：不含对话引号且超过 100 字的段落
  const longDescriptionParagraphs: StyleReport["longDescriptionParagraphs"] = [];
  paragraphs.forEach((para, index) => {
    const hasDialogue = /["“”]/.test(para);
    if (!hasDialogue && para.length > 100) {
      longDescriptionParagraphs.push({
        index,
        length: para.length,
        preview: para.slice(0, 30) + "...",
      });
    }
  });

  return { totalChars, paragraphCount, avgParagraphLength, dialogueRatio, longDescriptionParagraphs };
}

/**
 * 黄金三章页面
 *
 * 三个区块：
 * 1. 开篇节拍设计模板（3 章 × 6 节拍）
 * 2. 爽点密度检查清单
 * 3. 番茄风格检测（粘贴正文，前端纯计算）
 */
export function OpeningPage() {
  const { projectId = "" } = useParams();
  const [beats, setBeats] = useLocalStorage<Beat[]>(
    `tame-ink:opening-beats:${projectId}`,
    DEFAULT_BEATS,
  );
  const [checklist, setChecklist] = useLocalStorage<ChecklistItem[]>(
    `tame-ink:opening-checklist:${projectId}`,
    DEFAULT_CHECKLIST,
  );
  const [draft, setDraft] = useState("");
  const [report, setReport] = useState<StyleReport | null>(null);

  // 更新节拍内容
  function updateBeatContent(id: string, content: string) {
    setBeats(beats.map((beat) => (beat.id === id ? { ...beat, content } : beat)));
  }

  // 切换检查项勾选状态
  function toggleChecklist(id: string) {
    setChecklist(checklist.map((item) => (item.id === id ? { ...item, checked: !item.checked } : item)));
  }

  // 执行番茄风格检测
  function handleAnalyze() {
    setReport(analyzeStyle(draft));
  }

  // 按章号分组节拍，并按字数范围起点排序
  const beatsByChapter = useMemo(() => {
    const groups: Record<number, Beat[]> = { 1: [], 2: [], 3: [] };
    beats.forEach((beat) => {
      if (!groups[beat.chapter]) groups[beat.chapter] = [];
      groups[beat.chapter].push(beat);
    });
    Object.values(groups).forEach((group) =>
      group.sort((a, b) => parseInt(a.range.split("-")[0], 10) - parseInt(b.range.split("-")[0], 10)),
    );
    return groups;
  }, [beats]);

  const checkedCount = checklist.filter((item) => item.checked).length;

  return (
    <div className="opening-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">黄金三章</span>
          <h1>开篇节拍与爽点设计</h1>
          <p>开篇三章决定留存，按节拍模板填写并自检</p>
        </div>
      </header>

      {/* 区块 1：开篇节拍设计模板 */}
      <section className="opening-section">
        <div className="section-title">
          <h2>开篇节拍设计</h2>
          <span>3 章 × 6 节拍</span>
        </div>
        <div className="beats-grid">
          {[1, 2, 3].map((chapter) => (
            <div className="beats-chapter" key={chapter}>
              <h3>第 {chapter} 章</h3>
              <div className="beats-list">
                {beatsByChapter[chapter].map((beat) => (
                  <div className="beat-cell" key={beat.id}>
                    <div className="beat-header">
                      <strong>{beat.label}</strong>
                      <code>{beat.range}字</code>
                    </div>
                    <textarea
                      value={beat.content}
                      onChange={(event) => updateBeatContent(beat.id, event.target.value)}
                      placeholder={`填写${beat.label}内容...`}
                    />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 区块 2：爽点密度检查清单 */}
      <section className="opening-section">
        <div className="section-title">
          <h2>爽点密度检查</h2>
          <span>{checkedCount}/{checklist.length} 已通过</span>
        </div>
        <ul className="opening-checklist">
          {checklist.map((item) => (
            <li key={item.id} className={item.checked ? "is-checked" : ""}>
              <button
                type="button"
                className="opening-check"
                onClick={() => toggleChecklist(item.id)}
                aria-pressed={item.checked}
                aria-label={item.text}
              >
                {item.checked && <Check size={13} />}
              </button>
              <span>{item.text}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* 区块 3：番茄风格检测 */}
      <section className="opening-section">
        <div className="section-title">
          <h2>番茄风格检测</h2>
          <span>前端纯计算，不调后端</span>
        </div>
        <p className="muted style-hint">粘贴正文后点击"检测"，自动评估段落长度、对话占比与描写冗余。</p>
        <textarea
          className="style-textarea"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="粘贴章节正文进行风格检测..."
        />
        <div className="style-actions">
          <button
            type="button"
            className="button button-primary"
            onClick={handleAnalyze}
            disabled={!draft.trim()}
          >
            检测
          </button>
        </div>

        {report && (
          <div className="style-report">
            <div className="style-metrics">
              <div className="style-metric">
                <span>总字数</span>
                <strong>{report.totalChars}</strong>
              </div>
              <div className="style-metric">
                <span>段落数</span>
                <strong>{report.paragraphCount}</strong>
              </div>
              <div className={`style-metric ${report.avgParagraphLength < 50 ? "is-ok" : "is-warn"}`}>
                <span>平均段落长度</span>
                <strong>{report.avgParagraphLength.toFixed(1)}</strong>
                <small>建议 &lt; 50 字</small>
              </div>
              <div className={`style-metric ${report.dialogueRatio > 0.3 ? "is-ok" : "is-warn"}`}>
                <span>对话占比</span>
                <strong>{(report.dialogueRatio * 100).toFixed(1)}%</strong>
                <small>建议 &gt; 30%</small>
              </div>
            </div>
            {report.longDescriptionParagraphs.length > 0 ? (
              <div className="style-warnings">
                <h4>描写冗余段落（连续 &gt; 100 字且无对话）</h4>
                <ul>
                  {report.longDescriptionParagraphs.map((p) => (
                    <li key={p.index}>
                      <span>第 {p.index + 1} 段 · {p.length} 字</span>
                      <code>{p.preview}</code>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="muted style-ok">未发现描写冗余段落。</p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
