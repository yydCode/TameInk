import { useState } from "react";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";

import { useLocalStorage } from "../hooks/useLocalStorage";

/**
 * 人物档案
 * 涵盖主角、反派分层、功能性配角三类角色，统一存 localStorage
 */
export interface CharacterProfile {
  id: string;
  name: string;
  role:
    | "protagonist"
    | "minor-antagonist"
    | "mid-antagonist"
    | "major-antagonist"
    | "mastermind"
    | "support-equipment"
    | "support-info"
    | "support-contrast"
    | "support-conflict"
    | "love-interest"
    | "brother";
  // 主角档案字段
  openingDisadvantage?: string; // 开局劣势
  goldenFinger?: string; // 金手指
  personality?: string; // 性格标签
  growthArc?: string; // 成长弧光
  faceSlappingRhythm?: string; // 打脸节奏规划
  // 反派字段
  appearanceStage?: string; // 出场阶段
  threatLevel?: string; // 威胁等级
  // 配角字段
  function?: string; // 功能定位
  // 通用字段
  notes?: string; // 备注
}

type Role = CharacterProfile["role"];

// 反派四层（由弱到强）
const ANTAGONIST_LAYERS: { role: Role; title: string; description: string }[] = [
  { role: "minor-antagonist", title: "小反派", description: "短期冲突，推动节奏" },
  { role: "mid-antagonist", title: "中反派", description: "卷度对手，阶段主线" },
  { role: "major-antagonist", title: "大反派", description: "全书主要对手" },
  { role: "mastermind", title: "幕后黑手", description: "最终真相" },
];

// 功能性配角四类
const SUPPORT_TYPES: { role: Role; title: string; description: string }[] = [
  { role: "support-equipment", title: "送装备型", description: "提供资源/能力/道具" },
  { role: "support-info", title: "递信息型", description: "提供关键情报" },
  { role: "support-contrast", title: "衬托主角型", description: "衬托主角特质" },
  { role: "support-conflict", title: "制造冲突型", description: "推动剧情冲突" },
];

// 卡片字段分组：决定展示哪些字段
type FieldGroup = "protagonist" | "antagonist" | "support";

// 各分组对应的字段定义（顺序即展示顺序）
const FIELD_DEFS: Record<
  FieldGroup,
  { key: keyof CharacterProfile; label: string; placeholder?: string; multiline?: boolean }[]
> = {
  protagonist: [
    { key: "openingDisadvantage", label: "开局劣势", placeholder: "如：家道中落、被退婚" },
    { key: "goldenFinger", label: "金手指", placeholder: "如：神级功法、系统" },
    { key: "personality", label: "性格标签", placeholder: "如：腹黑、隐忍" },
    { key: "growthArc", label: "成长弧光", placeholder: "如：从废物到无敌", multiline: true },
    { key: "faceSlappingRhythm", label: "打脸节奏规划", placeholder: "如：每 5 章一次小打脸", multiline: true },
  ],
  antagonist: [
    { key: "appearanceStage", label: "出场阶段", placeholder: "如：第 1 卷第 5 章" },
    { key: "threatLevel", label: "威胁等级", placeholder: "如：★★★" },
    { key: "notes", label: "备注", multiline: true },
  ],
  support: [
    { key: "function", label: "功能定位", placeholder: "如：送神兵利器" },
    { key: "notes", label: "备注", multiline: true },
  ],
};

/**
 * 人物体系面板
 * 故事设计页的子模块，由作者自定义人物档案，AI 不干预
 * 数据存 localStorage（key: tame-ink:characters:${projectId}）
 */
export function CharacterSystemPanel({ projectId }: { projectId: string }) {
  const [characters, setCharacters] = useLocalStorage<CharacterProfile[]>(
    `tame-ink:characters:${projectId}`,
    [],
  );

  // 新增空档案（默认进入编辑模式）
  function add(role: Role) {
    setCharacters((prev) => [
      ...prev,
      { id: crypto.randomUUID(), name: "", role },
    ]);
  }
  // 删除档案
  function remove(id: string) {
    setCharacters((prev) => prev.filter((c) => c.id !== id));
  }
  // 增量更新档案字段
  function update(id: string, patch: Partial<CharacterProfile>) {
    setCharacters((prev) =>
      prev.map((c) => (c.id === id ? { ...c, ...patch } : c)),
    );
  }

  const protagonist = characters.filter((c) => c.role === "protagonist");
  const listByRole = (role: Role) => characters.filter((c) => c.role === role);

  return (
    <div className="character-system">
      {/* 主角档案 */}
      <section className="character-section">
        <div className="section-title">
          <h2>主角档案</h2>
          <span>核心人物设定</span>
        </div>
        <div className="character-list">
          {protagonist.map((c) => (
            <CharacterCard
              key={c.id}
              character={c}
              fieldGroup="protagonist"
              onUpdate={(patch) => update(c.id, patch)}
              onRemove={() => remove(c.id)}
            />
          ))}
          {protagonist.length === 0 && (
            <button
              className="button button-secondary character-add"
              type="button"
              onClick={() => add("protagonist")}
            >
              <Plus size={15} /> 添加主角
            </button>
          )}
        </div>
      </section>

      {/* 反派分层体系 */}
      <section className="character-section">
        <div className="section-title">
          <h2>反派分层体系</h2>
          <span>四层反派递进</span>
        </div>
        <div className="character-tiers">
          {ANTAGONIST_LAYERS.map((layer) => (
            <div key={layer.role} className="character-tier">
              <div className="character-tier-header">
                <strong>{layer.title}</strong>
                <span className="muted">{layer.description}</span>
              </div>
              <div className="character-list">
                {listByRole(layer.role).map((c) => (
                  <CharacterCard
                    key={c.id}
                    character={c}
                    fieldGroup="antagonist"
                    onUpdate={(patch) => update(c.id, patch)}
                    onRemove={() => remove(c.id)}
                  />
                ))}
                <button
                  className="button button-secondary character-add"
                  type="button"
                  onClick={() => add(layer.role)}
                >
                  <Plus size={15} /> 添加{layer.title}
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 功能性配角 */}
      <section className="character-section">
        <div className="section-title">
          <h2>功能性配角</h2>
          <span>四类功能定位</span>
        </div>
        <div className="character-tiers">
          {SUPPORT_TYPES.map((type) => (
            <div key={type.role} className="character-tier">
              <div className="character-tier-header">
                <strong>{type.title}</strong>
                <span className="muted">{type.description}</span>
              </div>
              <div className="character-list">
                {listByRole(type.role).map((c) => (
                  <CharacterCard
                    key={c.id}
                    character={c}
                    fieldGroup="support"
                    onUpdate={(patch) => update(c.id, patch)}
                    onRemove={() => remove(c.id)}
                  />
                ))}
                <button
                  className="button button-secondary character-add"
                  type="button"
                  onClick={() => add(type.role)}
                >
                  <Plus size={15} /> 添加{type.title}
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

interface CharacterCardProps {
  character: CharacterProfile;
  fieldGroup: FieldGroup;
  onUpdate: (patch: Partial<CharacterProfile>) => void;
  onRemove: () => void;
}

/**
 * 单个人物卡片
 * 支持查看/编辑两种模式：
 * - 新建档案（姓名为空）默认进入编辑模式
 * - 取消时若姓名为空则删除该档案
 */
function CharacterCard({
  character,
  fieldGroup,
  onUpdate,
  onRemove,
}: CharacterCardProps) {
  // 新建档案（无姓名）默认编辑
  const [editing, setEditing] = useState(!character.name);
  const fieldDefs = FIELD_DEFS[fieldGroup];

  // 取消编辑：姓名为空则删除，否则退出编辑
  function cancel() {
    if (!character.name) {
      onRemove();
      return;
    }
    setEditing(false);
  }

  if (!editing) {
    return (
      <article className="character-card">
        <div className="character-card-header">
          <strong>{character.name || "未命名"}</strong>
          <div className="character-card-actions">
            <button
              type="button"
              className="icon-button"
              aria-label="编辑"
              title="编辑"
              onClick={() => setEditing(true)}
            >
              <Pencil size={13} />
            </button>
            <button
              type="button"
              className="icon-button"
              aria-label="删除"
              title="删除"
              onClick={onRemove}
            >
              <Trash2 size={13} />
            </button>
          </div>
        </div>
        <dl>
          {fieldDefs.map((f) => (
            <div key={f.key}>
              <dt>{f.label}</dt>
              <dd>{(character[f.key] as string | undefined) || "—"}</dd>
            </div>
          ))}
        </dl>
      </article>
    );
  }

  return (
    <form
      className="character-card is-editing"
      onSubmit={(event) => {
        event.preventDefault();
        setEditing(false);
      }}
    >
      <label className="character-name-field">
        <span>姓名</span>
        <input
          value={character.name}
          onChange={(event) => onUpdate({ name: event.target.value })}
          placeholder="人物姓名"
          autoFocus
        />
      </label>
      {fieldDefs.map((f) => (
        <label key={f.key}>
          <span>{f.label}</span>
          {f.multiline ? (
            <textarea
              value={(character[f.key] as string | undefined) ?? ""}
              onChange={(event) =>
                onUpdate({ [f.key]: event.target.value } as Partial<CharacterProfile>)
              }
              placeholder={f.placeholder}
              rows={f.multiline ? 3 : undefined}
            />
          ) : (
            <input
              value={(character[f.key] as string | undefined) ?? ""}
              onChange={(event) =>
                onUpdate({ [f.key]: event.target.value } as Partial<CharacterProfile>)
              }
              placeholder={f.placeholder}
            />
          )}
        </label>
      ))}
      <div className="character-card-actions">
        <button type="submit" className="button button-primary">
          <Check size={15} /> 保存
        </button>
        <button
          type="button"
          className="button button-secondary"
          onClick={cancel}
        >
          <X size={15} /> 取消
        </button>
      </div>
    </form>
  );
}
