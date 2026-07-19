import { RotateCcw } from "lucide-react";
import { useParams } from "react-router";

import { useLocalStorage } from "../hooks/useLocalStorage";

// 项目规则配置（作者设定，AI 按此执行审查与评估）
interface ProjectRules {
  commercialScoreThreshold: number; // 商业评分门槛（0-100）
  continuityWeight: number; // 连续性权重
  styleWeight: number; // 文风权重
  commercialWeight: number; // 商业权重
  climaxDensity: number; // 爽点密度（每多少章一个高潮）
  chapterEndHookRequired: boolean; // 章末钩子是否必须
  maxWordsPerChapter: number; // 每章最大字数
  minWordsPerChapter: number; // 每章最小字数
}

// 默认规则
const DEFAULT_RULES: ProjectRules = {
  commercialScoreThreshold: 70,
  continuityWeight: 30,
  styleWeight: 30,
  commercialWeight: 40,
  climaxDensity: 10,
  chapterEndHookRequired: true,
  maxWordsPerChapter: 3000,
  minWordsPerChapter: 2000,
};

/**
 * 规则设置页面
 * 作者设定规则，AI 按规则执行审查和评估
 */
export function RulesPage() {
  const { projectId = "" } = useParams();
  const [rules, setRules] = useLocalStorage<ProjectRules>(
    `tame-ink:rules:${projectId}`,
    DEFAULT_RULES,
  );

  // 权重三项总和（建议为 100）
  const weightTotal =
    rules.continuityWeight + rules.styleWeight + rules.commercialWeight;
  const weightHint =
    weightTotal === 100 ? "总和为 100" : `建议总和为 100，当前为 ${weightTotal}`;

  // 更新单个字段
  function update<K extends keyof ProjectRules>(
    key: K,
    value: ProjectRules[K],
  ) {
    setRules({ ...rules, [key]: value });
  }

  // 重置为默认值
  function reset() {
    setRules(DEFAULT_RULES);
  }

  return (
    <section className="rules-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">规则设置</span>
          <h1>创作规则</h1>
          <p>这些规则由作者设定，AI 按规则执行审查和评估。</p>
        </div>
      </header>

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
              value={rules.commercialScoreThreshold}
              onChange={(event) =>
                update(
                  "commercialScoreThreshold",
                  Math.max(0, Math.min(100, Number(event.target.value))),
                )
              }
            />
            <small className="muted">低于此分数的章节将标记为需改进</small>
          </label>

          <label>
            爽点密度（每多少章一个高潮）
            <input
              type="number"
              min={1}
              value={rules.climaxDensity}
              onChange={(event) =>
                update("climaxDensity", Math.max(1, Number(event.target.value)))
              }
            />
            <small className="muted">控制节奏，避免平铺直叙</small>
          </label>

          <label>
            每章最小字数
            <input
              type="number"
              min={0}
              value={rules.minWordsPerChapter}
              onChange={(event) =>
                update(
                  "minWordsPerChapter",
                  Math.max(0, Number(event.target.value)),
                )
              }
            />
          </label>

          <label>
            每章最大字数
            <input
              type="number"
              min={0}
              value={rules.maxWordsPerChapter}
              onChange={(event) =>
                update(
                  "maxWordsPerChapter",
                  Math.max(0, Number(event.target.value)),
                )
              }
            />
          </label>

          <label className="toggle-field">
            <input
              type="checkbox"
              checked={rules.chapterEndHookRequired}
              onChange={(event) =>
                update("chapterEndHookRequired", event.target.checked)
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
              value={rules.continuityWeight}
              onChange={(event) =>
                update("continuityWeight", Number(event.target.value))
              }
            />
            <small className="muted">当前 {rules.continuityWeight}</small>
          </label>

          <label>
            文风权重
            <input
              type="range"
              min={0}
              max={100}
              value={rules.styleWeight}
              onChange={(event) =>
                update("styleWeight", Number(event.target.value))
              }
            />
            <small className="muted">当前 {rules.styleWeight}</small>
          </label>

          <label>
            商业权重
            <input
              type="range"
              min={0}
              max={100}
              value={rules.commercialWeight}
              onChange={(event) =>
                update("commercialWeight", Number(event.target.value))
              }
            />
            <small className="muted">当前 {rules.commercialWeight}</small>
          </label>
        </div>
        {/* 权重可视化条 */}
        <div className="rules-weight-bar" title={`总和 ${weightTotal}`}>
          <div
            style={{ width: `${rules.continuityWeight}%`, background: "var(--green)" }}
          />
          <div
            style={{ width: `${rules.styleWeight}%`, background: "var(--blue)" }}
          />
          <div
            style={{ width: `${rules.commercialWeight}%`, background: "var(--rust)" }}
          />
        </div>
      </section>

      <div className="rules-actions">
        <button className="button button-secondary" type="button" onClick={reset}>
          <RotateCcw size={15} />
          重置为默认
        </button>
      </div>
    </section>
  );
}
