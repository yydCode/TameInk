import { useMemo, useState } from "react";
import { useParams } from "react-router";
import { Pencil, Plus, Search, Trash2, X } from "lucide-react";

import { useLocalStorage } from "../hooks/useLocalStorage";

/**
 * 素材分类
 * - climax：爽点素材（高潮/转折）
 * - dialogue：对话素材（人物对话）
 * - scene：场景描写
 * - name：人名地名
 * - inspiration：灵感碎片
 */
type MaterialCategory = "climax" | "dialogue" | "scene" | "name" | "inspiration";

interface MaterialItem {
  id: string;
  category: MaterialCategory;
  title: string;
  content: string;
  tags: string[];
  createdAt: string;
}

// 分类中文标签
const CATEGORY_LABELS: Record<MaterialCategory, string> = {
  climax: "爽点素材",
  dialogue: "对话素材",
  scene: "场景描写",
  name: "人名地名",
  inspiration: "灵感碎片",
};

// 分类顺序（左侧导航用）
const CATEGORY_ORDER: MaterialCategory[] = [
  "climax",
  "dialogue",
  "scene",
  "name",
  "inspiration",
];

const EMPTY_DRAFT: MaterialDraft = {
  title: "",
  content: "",
  tagsText: "",
};

interface MaterialDraft {
  title: string;
  content: string;
  tagsText: string; // 标签输入用逗号分隔
}

/**
 * 素材库页面
 * 作者自定义素材，存 localStorage，AI 不干预
 * 左侧分类导航，右侧卡片列表 + 搜索 + 增删改
 */
export function MaterialLibraryPage() {
  const { projectId = "" } = useParams();

  const [materials, setMaterials] = useLocalStorage<MaterialItem[]>(
    `tame-ink:materials:${projectId}`,
    [],
  );

  // 当前选中的分类，"all" 表示全部
  const [activeCategory, setActiveCategory] = useState<
    MaterialCategory | "all"
  >("all");
  // 搜索关键字（按标题/内容/标签匹配）
  const [query, setQuery] = useState("");
  // 编辑中的素材 id，null 表示新建，undefined 表示未打开
  const [editingId, setEditingId] = useState<string | null | undefined>(
    undefined,
  );
  const [draft, setDraft] = useState<MaterialDraft>(EMPTY_DRAFT);
  const [error, setError] = useState<string | null>(null);

  // 按分类与关键字过滤
  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return materials
      .filter((item) => activeCategory === "all" || item.category === activeCategory)
      .filter((item) => {
        if (!keyword) return true;
        return (
          item.title.toLowerCase().includes(keyword) ||
          item.content.toLowerCase().includes(keyword) ||
          item.tags.some((tag) => tag.toLowerCase().includes(keyword))
        );
      })
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }, [materials, activeCategory, query]);

  // 每个分类的素材数量（用于左侧导航徽章）
  const counts = useMemo(() => {
    const result: Record<MaterialCategory, number> = {
      climax: 0,
      dialogue: 0,
      scene: 0,
      name: 0,
      inspiration: 0,
    };
    for (const item of materials) result[item.category] += 1;
    return result;
  }, [materials]);

  // 打开新增面板
  function openCreate() {
    setEditingId(null);
    // 新增时默认选中当前分类（若为 all，则默认 inspiration）
    const defaultCategory: MaterialCategory =
      activeCategory === "all" ? "inspiration" : activeCategory;
    setDraft({ ...EMPTY_DRAFT, tagsText: defaultCategory });
    setError(null);
  }

  // 打开编辑面板
  function openEdit(item: MaterialItem) {
    setEditingId(item.id);
    setDraft({
      title: item.title,
      content: item.content,
      tagsText: item.tags.join(", "),
    });
    setError(null);
  }

  // 关闭编辑面板
  function closeEditor() {
    setEditingId(undefined);
    setDraft(EMPTY_DRAFT);
    setError(null);
  }

  // 解析分类：从 tagsText 第一项中识别，若不属于合法分类则用当前默认
  function resolveCategory(tagsText: string): MaterialCategory {
    const first = tagsText.split(",")[0]?.trim().toLowerCase();
    return (CATEGORY_ORDER.find((c) => c === first) as MaterialCategory) ?? "inspiration";
  }

  // 保存（新增或更新）
  function save() {
    const title = draft.title.trim();
    const content = draft.content.trim();
    if (!title) {
      setError("请填写标题");
      return;
    }
    if (!content) {
      setError("请填写内容");
      return;
    }
    // 解析标签：第一项作为分类，其余作为标签
    const parts = draft.tagsText
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
    const category = resolveCategory(draft.tagsText);
    const tags = parts.slice(1); // 第一项是分类

    if (editingId === null) {
      // 新增
      const newItem: MaterialItem = {
        id: crypto.randomUUID(),
        category,
        title,
        content,
        tags,
        createdAt: new Date().toISOString(),
      };
      setMaterials([newItem, ...materials]);
    } else if (editingId) {
      // 更新
      setMaterials(
        materials.map((item) =>
          item.id === editingId
            ? { ...item, category, title, content, tags }
            : item,
        ),
      );
    }
    closeEditor();
  }

  // 删除素材
  function remove(id: string) {
    if (window.confirm("确定删除该素材吗？")) {
      setMaterials(materials.filter((item) => item.id !== id));
    }
  }

  const isEditorOpen = editingId !== undefined;

  return (
    <div className="material-library-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">长篇维护</span>
          <h1>素材库</h1>
          <p>作者积累的爽点、对话、场景、命名与灵感碎片</p>
        </div>
        <div className="header-actions">
          <button
            type="button"
            className="button button-primary"
            onClick={openCreate}
          >
            <Plus size={15} />
            新增素材
          </button>
        </div>
      </header>

      {/* 搜索栏 */}
      <section className="material-search-bar">
        <Search size={15} />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="按标题、内容或标签搜索"
        />
      </section>

      <div className="split-layout">
        {/* 左侧分类导航 */}
        <aside className="split-side material-categories">
          <button
            type="button"
            className={activeCategory === "all" ? "is-active" : ""}
            onClick={() => setActiveCategory("all")}
          >
            全部素材
            <span className="count-badge">{materials.length}</span>
          </button>
          {CATEGORY_ORDER.map((category) => (
            <button
              key={category}
              type="button"
              className={activeCategory === category ? "is-active" : ""}
              onClick={() => setActiveCategory(category)}
            >
              {CATEGORY_LABELS[category]}
              <span className="count-badge">{counts[category]}</span>
            </button>
          ))}
        </aside>

        {/* 右侧素材列表 */}
        <section className="material-list">
          {filtered.length === 0 ? (
            <div className="loading-state">
              <p>暂无素材，点击右上角「新增素材」开始积累</p>
            </div>
          ) : (
            <div className="material-grid">
              {filtered.map((item) => (
                <article key={item.id} className="material-card">
                  <header className="material-card-header">
                    <span className={`material-category category-${item.category}`}>
                      {CATEGORY_LABELS[item.category]}
                    </span>
                    <div className="material-card-actions">
                      <button
                        type="button"
                        className="icon-button"
                        onClick={() => openEdit(item)}
                        aria-label="编辑"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        type="button"
                        className="icon-button"
                        onClick={() => remove(item.id)}
                        aria-label="删除"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </header>
                  <h3>{item.title}</h3>
                  <p>{item.content}</p>
                  {item.tags.length > 0 && (
                    <div className="material-tags">
                      {item.tags.map((tag) => (
                        <span key={tag} className="material-tag">#{tag}</span>
                      ))}
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* 编辑/新增弹层 */}
      {isEditorOpen && (
        <MaterialEditor
          draft={draft}
          isEdit={editingId !== null}
          error={error}
          onChange={setDraft}
          onSave={save}
          onClose={closeEditor}
        />
      )}
    </div>
  );
}

/**
 * 素材编辑弹层
 * 复用新增与编辑两种场景
 */
interface MaterialEditorProps {
  draft: MaterialDraft;
  isEdit: boolean;
  error: string | null;
  onChange: (draft: MaterialDraft) => void;
  onSave: () => void;
  onClose: () => void;
}

function MaterialEditor({
  draft,
  isEdit,
  error,
  onChange,
  onSave,
  onClose,
}: MaterialEditorProps) {
  return (
    <div className="material-editor-overlay" role="dialog" aria-modal="true">
      <div className="material-editor">
        <header className="material-editor-header">
          <h2>{isEdit ? "编辑素材" : "新增素材"}</h2>
          <button
            type="button"
            className="icon-button"
            onClick={onClose}
            aria-label="关闭"
          >
            <X size={15} />
          </button>
        </header>
        <div className="material-editor-body">
          <label>
            标题
            <input
              value={draft.title}
              onChange={(event) => onChange({ ...draft, title: event.target.value })}
              placeholder="给素材起个名字"
            />
          </label>
          <label>
            内容
            <textarea
              value={draft.content}
              onChange={(event) =>
                onChange({ ...draft, content: event.target.value })
              }
              placeholder="详细描述素材内容"
              rows={6}
            />
          </label>
          <label>
            分类与标签
            <input
              value={draft.tagsText}
              onChange={(event) =>
                onChange({ ...draft, tagsText: event.target.value })
              }
              placeholder="第一项为分类（climax/dialogue/scene/name/inspiration），其余为标签，逗号分隔"
            />
            <small className="muted">
              示例：climax, 反派, 突围 —— 第一项决定分类，其余作为标签
            </small>
          </label>
          {error && <div className="inline-error">{error}</div>}
        </div>
        <footer className="material-editor-footer">
          <button type="button" className="button button-secondary" onClick={onClose}>
            取消
          </button>
          <button type="button" className="button button-primary" onClick={onSave}>
            保存
          </button>
        </footer>
      </div>
    </div>
  );
}
