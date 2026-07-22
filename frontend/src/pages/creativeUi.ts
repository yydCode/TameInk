import type {
  CreativeArtifact,
  CreativeArtifactKind,
  P0Skill,
  SkillExecutionResult,
} from "../api/client";

export const skillLabels: Record<P0Skill, string> = {
  "webnovel-research-genre": "题材与读者证据",
  "webnovel-design-reader-contract": "读者契约",
  "webnovel-design-story-engine": "故事引擎",
  "webnovel-plan-rolling-story": "滚动故事卡",
  "webnovel-plan-chapter": "章节场景规划",
  "webnovel-draft": "章节草稿",
  "webnovel-audit": "质量审查",
  "webnovel-opening-audit": "开篇18元素审核",
  "webnovel-poison-check": "毒点检测",
  "webnovel-curate-memory": "记忆整理",
  "webnovel-plan-ending": "结局规划",
};

export const artifactLabels: Record<CreativeArtifactKind, string> = {
  reader_contract: "读者契约",
  story_engine: "故事引擎",
  character_state: "人物状态",
  expectation: "读者期待",
  story_card: "故事卡",
  chapter_plan: "章节规划",
  chapter_draft: "章节草稿",
  evidence_finding: "证据与假设",
  actual_event: "实际事件",
  memory_proposal: "记忆提案",
  ending_plan: "结局规划",
};

export function artifactStatusLabel(status: CreativeArtifact["status"]): string {
  return {
    candidate: "保存中",
    needs_decision: "等待选择",
    conflict: "存在冲突",
    ready: "准备确认",
    awaiting_approval: "等待确认",
    accepted: "已确认",
    rejected: "未采用",
  }[status];
}

export function artifactSummary(
  artifact: CreativeArtifact,
  result?: SkillExecutionResult,
): string {
  if (result?.candidate?.summary) return result.candidate.summary;
  return artifact.source_layer === "hypothesis"
    ? "模型整理的证据或假设，不能进入正式故事。"
    : "等待读取候选内容。";
}

function payloadId(result?: SkillExecutionResult): string | null {
  const id = result?.candidate?.payload.id;
  return typeof id === "string" && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(id)
    ? id
    : null;
}

export function defaultFormalPath(
  artifact: CreativeArtifact,
  result?: SkillExecutionResult,
): string | null {
  const id = payloadId(result);
  switch (artifact.kind) {
    case "reader_contract":
      return "commitments/reader-contract.yaml";
    case "story_engine":
      return "commitments/story-engine.yaml";
    case "ending_plan":
      return "commitments/ending-plan.yaml";
    case "character_state":
      return id ? `canon/characters/${id}.yaml` : null;
    case "expectation":
      return id ? `commitments/expectations/${id}.yaml` : null;
    case "story_card":
    case "chapter_plan":
      return id ? `commitments/story-cards/${id}.yaml` : null;
    case "chapter_draft": {
      const chapterId = result?.candidate?.payload.chapter_id;
      const safeId = typeof chapterId === "string" ? chapterId : id;
      return safeId && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(safeId)
        ? `canon/chapters/${safeId}.md`
        : null;
    }
    case "actual_event":
      return id ? `canon/actual-events/${id}.yaml` : null;
    case "memory_proposal": {
      const kind = result?.candidate?.payload.kind;
      const directory =
        kind === "fact"
          ? "facts"
          : kind === "event"
            ? "events"
            : kind === "relationship"
              ? "relationships"
              : kind === "foreshadowing"
                ? "foreshadowing"
                : null;
      return id && directory ? `memory/${directory}/${id}.yaml` : null;
    }
    case "evidence_finding":
      return null;
  }
}

export function canConfirmArtifact(
  artifact: CreativeArtifact,
  result?: SkillExecutionResult,
): boolean {
  return artifact.source_layer === "candidate" && defaultFormalPath(artifact, result) !== null;
}
