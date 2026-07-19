import { useMemo, useState, type FormEvent } from "react";
import { Download, Pencil, Plus, Trash2, X } from "lucide-react";
import { useParams } from "react-router";

import { useLocalStorage } from "../hooks/useLocalStorage";

// 榜单条目（新书榜 / 飙升榜 / 读完榜）
interface RankingEntry {
  id: string;
  rank: number;
  title: string;
  author: string;
  genre: string;
  wordCount: string;
  category: "new" | "rising" | "completed";
  notes?: string;
}

// 竞品分析条目
interface CompetitorAnalysis {
  id: string;
  title: string;
  strengths: string;
  openingStructure: string;
  readerKeywords: string;
}

// 榜单分类标签映射
const CATEGORY_LABELS: Record<RankingEntry["category"], string> = {
  new: "新书榜",
  rising: "飙升榜",
  completed: "读完榜",
};

/**
 * 市场调研页面（手动数据版）
 * 作者手动录入番茄后台数据，AI 不自动爬取；数据按项目隔离存于 localStorage
 */
export function MarketPage() {
  const { projectId = "" } = useParams();
  const [rankings, setRankings] = useLocalStorage<RankingEntry[]>(
    `tame-ink:market-ranking:${projectId}`,
    [],
  );
  const [competitors, setCompetitors] = useLocalStorage<CompetitorAnalysis[]>(
    `tame-ink:market-competitors:${projectId}`,
    [],
  );
  const [activeTab, setActiveTab] = useState<"ranking" | "competitor">("ranking");

  // 导出榜单与竞品数据为 JSON 文件
  function handleExport() {
    const payload = { projectId, exportedAt: new Date().toISOString(), rankings, competitors };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `market-${projectId}-${Date.now()}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="market-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">市场调研</span>
          <h1>市场榜单与竞品分析</h1>
          <p>手动录入番茄后台数据，AI 不自动爬取</p>
        </div>
        <div className="header-actions">
          <button className="button button-secondary" type="button" onClick={handleExport}>
            <Download size={14} /> 导出 JSON
          </button>
        </div>
      </header>

      <div className="segmented market-tabs">
        <button type="button" className={activeTab === "ranking" ? "is-active" : ""} onClick={() => setActiveTab("ranking")}>
          榜单数据
        </button>
        <button type="button" className={activeTab === "competitor" ? "is-active" : ""} onClick={() => setActiveTab("competitor")}>
          竞品分析
        </button>
      </div>

      {activeTab === "ranking" ? (
        <RankingTab rankings={rankings} setRankings={setRankings} />
      ) : (
        <CompetitorTab competitors={competitors} setCompetitors={setCompetitors} />
      )}
    </div>
  );
}

/**
 * 榜单数据标签页：表格展示 + 按分类/题材筛选 + 增删改
 */
function RankingTab({ rankings, setRankings }: {
  rankings: RankingEntry[];
  setRankings: (next: RankingEntry[]) => void;
}) {
  const [categoryFilter, setCategoryFilter] = useState<"all" | RankingEntry["category"]>("all");
  const [genreFilter, setGenreFilter] = useState<string>("all");
  // 当前编辑条目：undefined=关闭，null=新增，对象=编辑
  const [editing, setEditing] = useState<RankingEntry | null | undefined>(undefined);

  // 收集所有出现过的题材，作为筛选下拉选项
  const genres = useMemo(() => {
    const set = new Set<string>();
    rankings.forEach((entry) => entry.genre && set.add(entry.genre));
    return Array.from(set).sort();
  }, [rankings]);

  // 应用筛选并按排名升序
  const filtered = useMemo(() => {
    return rankings
      .filter((entry) => categoryFilter === "all" || entry.category === categoryFilter)
      .filter((entry) => genreFilter === "all" || entry.genre === genreFilter)
      .sort((a, b) => a.rank - b.rank);
  }, [rankings, categoryFilter, genreFilter]);

  function handleDelete(id: string) {
    if (!window.confirm("确认删除该榜单条目？")) return;
    setRankings(rankings.filter((entry) => entry.id !== id));
  }

  function handleSave(entry: RankingEntry) {
    const exists = rankings.some((item) => item.id === entry.id);
    setRankings(exists
      ? rankings.map((item) => (item.id === entry.id ? entry : item))
      : [...rankings, entry]);
    setEditing(undefined);
  }

  return (
    <section className="market-section">
      <div className="market-filters">
        <label>分类
          <select value={categoryFilter}
            onChange={(event) => setCategoryFilter(event.target.value as "all" | RankingEntry["category"])}>
            <option value="all">全部</option>
            <option value="new">新书榜</option>
            <option value="rising">飙升榜</option>
            <option value="completed">读完榜</option>
          </select>
        </label>
        <label>题材
          <select value={genreFilter} onChange={(event) => setGenreFilter(event.target.value)}>
            <option value="all">全部</option>
            {genres.map((genre) => <option key={genre} value={genre}>{genre}</option>)}
          </select>
        </label>
        <button className="button button-primary" type="button" onClick={() => setEditing(null)}>
          <Plus size={14} /> 新增条目
        </button>
      </div>

      {filtered.length ? (
        <div className="ranking-table">
          <div className="ranking-row ranking-row--head">
            <span>排名</span><span>书名</span><span>作者</span><span>题材</span>
            <span>字数</span><span>分类</span><span>备注</span><span>操作</span>
          </div>
          {filtered.map((entry) => (
            <div className="ranking-row" key={entry.id}>
              <span className="ranking-rank">#{entry.rank}</span>
              <strong>{entry.title}</strong>
              <span>{entry.author}</span>
              <span>{entry.genre}</span>
              <span>{entry.wordCount}</span>
              <span className="ranking-category">{CATEGORY_LABELS[entry.category]}</span>
              <span className="muted">{entry.notes || "—"}</span>
              <div className="row-actions">
                <button type="button" className="icon-button" aria-label="编辑" onClick={() => setEditing(entry)}>
                  <Pencil size={13} />
                </button>
                <button type="button" className="icon-button" aria-label="删除" onClick={() => handleDelete(entry.id)}>
                  <Trash2 size={13} />
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">尚无榜单数据，点击"新增条目"开始录入。</p>
      )}

      {editing !== undefined && (
        <RankingDialog initial={editing} onClose={() => setEditing(undefined)} onSave={handleSave} />
      )}
    </section>
  );
}

/**
 * 榜单条目新增/编辑弹窗
 */
function RankingDialog({ initial, onClose, onSave }: {
  initial: RankingEntry | null;
  onClose: () => void;
  onSave: (entry: RankingEntry) => void;
}) {
  const [draft, setDraft] = useState<RankingEntry>(initial ?? {
    id: crypto.randomUUID(),
    rank: 1, title: "", author: "", genre: "", wordCount: "", category: "new", notes: "",
  });

  function update(patch: Partial<RankingEntry>) {
    setDraft((prev) => ({ ...prev, ...patch }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.title.trim()) {
      window.alert("请填写书名");
      return;
    }
    onSave({ ...draft, rank: Math.max(1, Number(draft.rank) || 1) });
  }

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <form className="dialog" onClick={(e) => e.stopPropagation()} onSubmit={handleSubmit}>
        <div className="dialog-heading">
          <h2>{initial ? "编辑榜单条目" : "新增榜单条目"}</h2>
          <button type="button" className="icon-button" aria-label="关闭" onClick={onClose}>
            <X size={14} />
          </button>
        </div>
        <div className="form-grid">
          <label>排名
            <input type="number" min={1} value={draft.rank}
              onChange={(event) => update({ rank: Number(event.target.value) })} />
          </label>
          <label>分类
            <select value={draft.category}
              onChange={(event) => update({ category: event.target.value as RankingEntry["category"] })}>
              <option value="new">新书榜</option>
              <option value="rising">飙升榜</option>
              <option value="completed">读完榜</option>
            </select>
          </label>
          <label>书名
            <input value={draft.title} onChange={(event) => update({ title: event.target.value })} />
          </label>
          <label>作者
            <input value={draft.author} onChange={(event) => update({ author: event.target.value })} />
          </label>
          <label>题材
            <input value={draft.genre} onChange={(event) => update({ genre: event.target.value })} />
          </label>
          <label>字数
            <input value={draft.wordCount} placeholder="如 120万字"
              onChange={(event) => update({ wordCount: event.target.value })} />
          </label>
          <label className="form-grid-full">备注
            <textarea value={draft.notes} onChange={(event) => update({ notes: event.target.value })} />
          </label>
        </div>
        <div className="dialog-actions">
          <button type="button" className="button button-secondary" onClick={onClose}>取消</button>
          <button type="submit" className="button button-primary">保存</button>
        </div>
      </form>
    </div>
  );
}

/**
 * 竞品分析标签页：卡片列表 + 增删改
 */
function CompetitorTab({ competitors, setCompetitors }: {
  competitors: CompetitorAnalysis[];
  setCompetitors: (next: CompetitorAnalysis[]) => void;
}) {
  const [editing, setEditing] = useState<CompetitorAnalysis | null | undefined>(undefined);

  function handleDelete(id: string) {
    if (!window.confirm("确认删除该竞品分析？")) return;
    setCompetitors(competitors.filter((item) => item.id !== id));
  }

  function handleSave(item: CompetitorAnalysis) {
    const exists = competitors.some((c) => c.id === item.id);
    setCompetitors(exists
      ? competitors.map((c) => (c.id === item.id ? item : c))
      : [...competitors, item]);
    setEditing(undefined);
  }

  return (
    <section className="market-section">
      <div className="market-section-head">
        <span className="muted">共 {competitors.length} 条竞品记录</span>
        <button className="button button-primary" type="button" onClick={() => setEditing(null)}>
          <Plus size={14} /> 新增竞品
        </button>
      </div>

      {competitors.length ? (
        <div className="competitor-grid">
          {competitors.map((item) => (
            <article className="competitor-card" key={item.id}>
              <header>
                <strong>{item.title}</strong>
                <div className="row-actions">
                  <button type="button" className="icon-button" aria-label="编辑" onClick={() => setEditing(item)}>
                    <Pencil size={13} />
                  </button>
                  <button type="button" className="icon-button" aria-label="删除" onClick={() => handleDelete(item.id)}>
                    <Trash2 size={13} />
                  </button>
                </div>
              </header>
              <dl>
                <div><dt>核心卖点</dt><dd>{item.strengths || "—"}</dd></div>
                <div><dt>开篇结构</dt><dd>{item.openingStructure || "—"}</dd></div>
                <div><dt>读者关键词</dt><dd>{item.readerKeywords || "—"}</dd></div>
              </dl>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted">尚无竞品数据，点击"新增竞品"开始录入。</p>
      )}

      {editing !== undefined && (
        <CompetitorDialog initial={editing} onClose={() => setEditing(undefined)} onSave={handleSave} />
      )}
    </section>
  );
}

/**
 * 竞品分析新增/编辑弹窗
 */
function CompetitorDialog({ initial, onClose, onSave }: {
  initial: CompetitorAnalysis | null;
  onClose: () => void;
  onSave: (item: CompetitorAnalysis) => void;
}) {
  const [draft, setDraft] = useState<CompetitorAnalysis>(initial ?? {
    id: crypto.randomUUID(),
    title: "", strengths: "", openingStructure: "", readerKeywords: "",
  });

  function update(patch: Partial<CompetitorAnalysis>) {
    setDraft((prev) => ({ ...prev, ...patch }));
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.title.trim()) {
      window.alert("请填写书名");
      return;
    }
    onSave(draft);
  }

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" onClick={onClose}>
      <form className="dialog" onClick={(e) => e.stopPropagation()} onSubmit={handleSubmit}>
        <div className="dialog-heading">
          <h2>{initial ? "编辑竞品分析" : "新增竞品分析"}</h2>
          <button type="button" className="icon-button" aria-label="关闭" onClick={onClose}>
            <X size={14} />
          </button>
        </div>
        <div className="form-grid">
          <label className="form-grid-full">书名
            <input value={draft.title} onChange={(event) => update({ title: event.target.value })} />
          </label>
          <label className="form-grid-full">核心卖点
            <textarea value={draft.strengths} placeholder="这本书最吸引读者的卖点"
              onChange={(event) => update({ strengths: event.target.value })} />
          </label>
          <label className="form-grid-full">开篇结构
            <textarea value={draft.openingStructure} placeholder="开篇如何展开（钩子 / 危机 / 金手指 等）"
              onChange={(event) => update({ openingStructure: event.target.value })} />
          </label>
          <label className="form-grid-full">读者关键词
            <textarea value={draft.readerKeywords} placeholder="读者评论中高频出现的关键词"
              onChange={(event) => update({ readerKeywords: event.target.value })} />
          </label>
        </div>
        <div className="dialog-actions">
          <button type="button" className="button button-secondary" onClick={onClose}>取消</button>
          <button type="submit" className="button button-primary">保存</button>
        </div>
      </form>
    </div>
  );
}
