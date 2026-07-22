import type { CreativeArtifactKind } from "../../api/client";

/**
 * 结构化候选视图：把 AI 生成的 artifact payload 渲染成作者可读的卡片，
 * 替代裸 JSON。每种 artifact_kind 有专属布局；未知字段回退为忽略。
 *
 * 设计原则：作者永远看到"写小说的语言"（读者契约/人物/期待），
 * 而不是数据结构。字段缺失时静默跳过，不显示 undefined。
 */

type Payload = Record<string, unknown>;

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.trim() !== "");
}

/** 单个字段行：标签 + 值 */
function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className="artifact-field">
      <span className="artifact-field-label">{label}</span>
      <span className="artifact-field-value">{value}</span>
    </div>
  );
}

/** 列表字段：标签 + 条目列表 */
function ListField({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="artifact-field artifact-field--list">
      <span className="artifact-field-label">{label}</span>
      <ul className="artifact-field-list">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function ReaderContractCard({ p }: { p: Payload }) {
  return (
    <div className="artifact-card">
      <Field label="平台" value={asString(p.platform)} />
      <Field label="频道" value={asString(p.channel)} />
      <Field label="题材范围" value={asString(p.genre_scope)} />
      <ListField label="目标读者" items={asStringList(p.target_readers)} />
      <Field label="核心体验" value={asString(p.core_experience)} />
      <Field label="主角承诺" value={asString(p.protagonist_promise)} />
      <ListField label="必须兑现" items={asStringList(p.must_payoffs)} />
      <ListField label="禁止方向" items={asStringList(p.forbidden_directions)} />
    </div>
  );
}

function StoryEngineCard({ p }: { p: Payload }) {
  return (
    <div className="artifact-card">
      <Field label="主角定位" value={asString(p.protagonist_role)} />
      <Field label="欲望" value={asString(p.desire)} />
      <Field label="恐惧" value={asString(p.fear)} />
      <Field label="价值优先级" value={asString(p.value_priority)} />
      <Field label="行动机制" value={asString(p.action_mechanism)} />
      <Field label="世界压力" value={asString(p.world_pressure)} />
      <ListField label="转化链" items={asStringList(p.conversion_chain)} />
      <ListField label="状态维度" items={asStringList(p.state_dimensions)} />
      <ListField label="变奏轴" items={asStringList(p.variation_axes)} />
      <ListField label="长线" items={asStringList(p.long_lines)} />
      <Field label="结局方向" value={asString(p.ending_direction)} />
    </div>
  );
}

function CharacterStateCard({ p }: { p: Payload }) {
  return (
    <div className="artifact-card">
      <Field label="姓名" value={asString(p.name)} />
      <Field label="欲望" value={asString(p.desire)} />
      <Field label="恐惧" value={asString(p.fear)} />
      <Field label="当前信念" value={asString(p.current_belief)} />
      <Field label="价值优先级" value={asString(p.value_priority)} />
      <Field label="决策模式" value={asString(p.decision_pattern)} />
      <ListField label="社会角色" items={asStringList(p.social_roles)} />
      <ListField label="可用资源" items={asStringList(p.available_resources)} />
    </div>
  );
}

const EXPECTATION_STATUS: Record<string, string> = {
  opened: "已开启",
  strengthened: "已强化",
  partially_paid: "部分兑现",
  paid: "已兑现",
  invalidated: "已作废",
};
const EXPECTATION_SCOPE: Record<string, string> = { local: "局部", long_term: "长线" };

function ExpectationCard({ p }: { p: Payload }) {
  const question = asString(p.reader_question);
  const status = asString(p.status);
  const scope = asString(p.scope);
  return (
    <div className="artifact-card">
      {question ? <p className="artifact-question">读者会问：{question}</p> : null}
      <Field label="兑现方式" value={asString(p.payoff_semantics)} />
      <Field label="范围" value={scope ? (EXPECTATION_SCOPE[scope] ?? scope) : null} />
      <Field label="当前状态" value={status ? (EXPECTATION_STATUS[status] ?? status) : null} />
    </div>
  );
}

const CARD_STATUS: Record<string, string> = {
  planned: "已规划",
  current: "进行中",
  completed: "已完成",
  superseded: "已替换",
};

function StoryCardCard({ p }: { p: Payload }) {
  const sceneUnits = Array.isArray(p.scene_units) ? p.scene_units : [];
  const status = asString(p.status);
  return (
    <div className="artifact-card">
      <Field label="状态" value={status ? (CARD_STATUS[status] ?? status) : null} />
      <Field label="目标" value={asString(p.goal)} />
      <Field label="动机" value={asString(p.motivation)} />
      <Field label="入口状态" value={asString(p.cycle_input)} />
      <Field label="状态变化" value={asString(p.cycle_delta)} />
      <Field label="下一步引子" value={asString(p.next_affordance)} />
      {sceneUnits.length > 0 ? (
        <div className="artifact-field artifact-field--list">
          <span className="artifact-field-label">场景单元（{sceneUnits.length}）</span>
          <ol className="artifact-scene-list">
            {sceneUnits.map((unit, index) => {
              const u = unit as Payload;
              return (
                <li key={index}>
                  {asString(u.foreground_purpose) ?? asString(u.local_intention) ?? `场景 ${index + 1}`}
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}
    </div>
  );
}

const FINDING_TYPE: Record<string, string> = {
  continuity: "连续性",
  promise: "承诺兑现",
  character: "人物",
  scene: "场景",
  dialogue: "对话",
  cognitive_load: "认知负担",
  style: "文风",
};

function EvidenceFindingCard({ p }: { p: Payload }) {
  const findingType = asString(p.finding_type);
  const certainty = asString(p.certainty);
  const evidence = Array.isArray(p.evidence) ? p.evidence : [];
  return (
    <div className="artifact-card artifact-card--finding">
      <div className="artifact-field-inline">
        {findingType ? (
          <span className="artifact-tag">{FINDING_TYPE[findingType] ?? findingType}</span>
        ) : null}
        {certainty ? (
          <span className={`artifact-tag artifact-tag--${certainty}`}>
            {certainty === "deterministic" ? "确定性冲突" : "假设"}
          </span>
        ) : null}
      </div>
      <Field label="问题描述" value={asString(p.description)} />
      <Field label="可能反证" value={asString(p.counter_hypothesis)} />
      {evidence.length > 0 ? (
        <div className="artifact-field artifact-field--list">
          <span className="artifact-field-label">正文证据</span>
          <ul className="artifact-field-list">
            {evidence.map((item, index) => {
              const e = item as Payload;
              return <li key={index}>{asString(e.quote) ?? asString(e.location) ?? "—"}</li>;
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function ActualEventCard({ p }: { p: Payload }) {
  return (
    <div className="artifact-card">
      <Field label="事件" value={asString(p.summary)} />
      <ListField label="状态变化" items={asStringList(p.state_changes)} />
    </div>
  );
}

function EndingPlanCard({ p }: { p: Payload }) {
  return (
    <div className="artifact-card">
      <ListField label="最终状态目标" items={asStringList(p.final_state_targets)} />
      <ListField label="共同高潮线" items={asStringList(p.shared_climax_links)} />
      <ListField label="高潮后奖励" items={asStringList(p.post_climax_rewards)} />
    </div>
  );
}

function GenericCard({ p }: { p: Payload }) {
  // 兜底：把 payload 的字符串/列表字段平铺展示，仍不显示裸 JSON 花括号
  const entries = Object.entries(p).filter(
    ([key]) => !["id", "schema_version", "decision_id", "confirmed_by"].includes(key),
  );
  return (
    <div className="artifact-card">
      {entries.map(([key, value]) => {
        const str = asString(value);
        if (str) return <Field key={key} label={key} value={str} />;
        const list = asStringList(value);
        if (list.length > 0) return <ListField key={key} label={key} items={list} />;
        return null;
      })}
    </div>
  );
}

export function ArtifactCard({
  kind,
  payload,
}: {
  kind: CreativeArtifactKind;
  payload: Record<string, unknown>;
}) {
  const p = payload;
  switch (kind) {
    case "reader_contract":
      return <ReaderContractCard p={p} />;
    case "story_engine":
      return <StoryEngineCard p={p} />;
    case "character_state":
      return <CharacterStateCard p={p} />;
    case "expectation":
      return <ExpectationCard p={p} />;
    case "story_card":
    case "chapter_plan":
      return <StoryCardCard p={p} />;
    case "evidence_finding":
      return <EvidenceFindingCard p={p} />;
    case "actual_event":
      return <ActualEventCard p={p} />;
    case "ending_plan":
      return <EndingPlanCard p={p} />;
    default:
      return <GenericCard p={p} />;
  }
}
