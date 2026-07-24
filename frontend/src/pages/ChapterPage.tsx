import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  BookOpenCheck,
  Check,
  ChevronRight,
  CirclePlus,
  LoaderCircle,
  RefreshCw,
  Sparkles,
  Wand2,
  XCircle,
} from "lucide-react";
import { useNavigate, useParams } from "react-router";

import {
  approveChapter,
  approveChapterPlan,
  auditChapterCommercially,
  generateChapter,
  generateChapterPlan,
  getChapterStage,
  getCommercialAudit,
  getDocument,
  getDraft,
  getTaskRun,
  listMemoryCandidates,
  localReviseChapter,
  reviseChapter,
  saveDraft,
  transitionTask,
  type MemoryCandidate,
} from "../api/client";
import { queryKeys } from "../app/queryKeys";
import { NovelEditor } from "../components/editor/NovelEditor";
import { pushDecision } from "../features/decisions/decisionQueue";
import { RunStatus } from "../features/runs/RunStatus";
import { useProjectWorkspace } from "../features/workspace/useProjectWorkspace";
import { useTaskStream } from "../hooks/useTaskStream";

type AuditReports = {
  continuity: Array<{
    id: string;
    severity: string;
    description: string;
    citation: { quote: string };
  }>;
  style: Array<{
    id: string;
    severity: string;
    description: string;
    citation: { quote: string };
  }>;
};
// 右侧信息面板的标签类型，按规划/审查/伏笔/来源四类组织
type EvidenceTab = "plan" | "audit" | "foreshadow" | "context";

export function ChapterPage() {
  const { projectId = "", chapterId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { project, snapshot, workflow, tasks } = useProjectWorkspace(projectId);
  const chapters = useMemo(
    () => [
      ...(snapshot.data?.volumes.flatMap((volume) => volume.chapters) ?? []),
      ...(snapshot.data?.unassigned_chapters ?? []),
    ],
    [snapshot.data],
  );
  const maxChapter = Math.max(
    0,
    ...chapters.map((chapter) => Number(chapter.id)).filter(Number.isFinite),
    ...(tasks.data
      ?.filter((task) => task.chapter_id)
      .map((task) => Number(task.chapter_id))
      .filter(Number.isFinite) ?? []),
  );
  const selectedId =
    chapterId ?? chapters.at(-1)?.id ?? String(maxChapter + 1 || 1);
  const activeTask =
    tasks.data?.find(
      (task) =>
        task.purpose === "chapter" &&
        task.chapter_id === selectedId &&
        !["completed", "cancelled"].includes(task.status),
    ) ??
    tasks.data?.find(
      (task) => task.purpose === "chapter" && task.chapter_id === selectedId,
    );
  const selectedChapter = chapters.find((chapter) => chapter.id === selectedId);
  const [instruction, setInstruction] = useState(
    "完成本章核心兑现，冲突逐级升级，并以新的未决问题收尾。目标 2500-3500 字。",
  );
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [evidenceTab, setEvidenceTab] = useState<EvidenceTab>("plan");
  const [acceptedMemory, setAcceptedMemory] = useState<Set<string>>(new Set());
  const [overrideReason, setOverrideReason] = useState("");
  // P3 局部重写：作者贴入要重写的段落 + 指令
  const [localSelection, setLocalSelection] = useState("");
  const [localInstruction, setLocalInstruction] = useState("");
  const [error, setError] = useState<string | null>(null);
  const parentRef = useRef<HTMLDivElement>(null);
  const allTreeItems = useMemo(
    () =>
      snapshot.data?.volumes.flatMap((volume) => [
        { type: "volume" as const, id: volume.id, label: volume.title },
        ...volume.chapters.map((chapter) => ({
          type: "chapter" as const,
          id: chapter.id,
          label: chapter.title,
        })),
      ]) ?? [],
    [snapshot.data],
  );
  const virtualizer = useVirtualizer({
    count: allTreeItems.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 36,
    overscan: 8,
  });

  const formal = useQuery({
    queryKey: queryKeys.document(projectId, selectedChapter?.path ?? ""),
    queryFn: () => getDocument(projectId, selectedChapter!.path),
    enabled:
      Boolean(selectedChapter) && activeTask?.status !== "awaiting_approval",
  });
  const draft = useQuery({
    queryKey: ["chapter-draft", projectId, activeTask?.id],
    queryFn: () => getDraft(projectId, activeTask!.id, "chapter.md"),
    enabled: activeTask?.status === "awaiting_approval",
  });
  const plan = useQuery({
    queryKey: ["chapter-plan", projectId, activeTask?.id],
    queryFn: () => getDraft(projectId, activeTask!.id, "plan.md"),
    enabled: activeTask?.status === "awaiting_approval",
  });
  const reports = useQuery({
    queryKey: ["chapter-reports", projectId, activeTask?.id],
    queryFn: async () =>
      JSON.parse(
        (await getDraft(projectId, activeTask!.id, "audit-reports.json"))
          .content,
      ) as AuditReports,
    enabled: activeTask?.status === "awaiting_approval",
  });
  const audit = useQuery({
    queryKey: ["chapter-audit", projectId, activeTask?.id],
    queryFn: () => getCommercialAudit(projectId, activeTask!.id),
    enabled: activeTask?.status === "awaiting_approval",
  });
  const memory = useQuery({
    queryKey: ["memory-candidates", projectId, activeTask?.id],
    queryFn: () => listMemoryCandidates(projectId, activeTask!.id),
    enabled: activeTask?.status === "awaiting_approval",
  });
  const run = useQuery({
    queryKey: ["task-run", projectId, activeTask?.id],
    queryFn: () => getTaskRun(projectId, activeTask!.id),
    enabled: Boolean(activeTask),
  });
  // P0 章纲人审：查询当前阶段（plan_awaiting_approval / draft_awaiting_approval / 等）
  const stage = useQuery({
    queryKey: ["chapter-stage", projectId, activeTask?.id],
    queryFn: () => getChapterStage(projectId, selectedId, activeTask!.id),
    enabled: activeTask?.status === "awaiting_approval",
    refetchInterval: 5_000,
  });
  const stageValue = stage.data?.stage ?? "";
  const stream = useTaskStream(
    projectId,
    activeTask && ["pending", "running"].includes(activeTask.status)
      ? activeTask.id
      : undefined,
  );

  useEffect(() => {
    const next = draft.data?.content ?? formal.data?.content ?? "";
    setContent(next);
    setSavedContent(next);
  }, [draft.data?.content, formal.data?.content, selectedId]);
  useEffect(() => {
    setAcceptedMemory(new Set());
  }, [activeTask?.id]);
  useEffect(() => {
    if (
      !activeTask ||
      activeTask.status !== "awaiting_approval" ||
      !draft.data ||
      content === savedContent
    )
      return;
    const timer = window.setTimeout(
      () =>
        saveDraft(
          projectId,
          activeTask.id,
          "chapter.md",
          content,
          draft.data.revision,
        )
          .then(() => setSavedContent(content))
          .catch((cause) =>
            setError(cause instanceof Error ? cause.message : "章节保存失败"),
          ),
      700,
    );
    return () => window.clearTimeout(timer);
  }, [activeTask, content, draft.data, projectId, savedContent]);

  const generate = useMutation({
    mutationFn: () =>
      generateChapter(
        projectId,
        selectedId,
        instruction,
        selectedChapter?.volume_id ?? snapshot.data?.volumes[0]?.id ?? "1",
      ),
    onSuccess: (task) => {
      setError(null);
      navigate(`/projects/${projectId}/chapters/${task.chapter_id}`);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tasks(projectId),
      });
    },
    onError: (cause) => setError(cause.message),
  });
  const approve = useMutation({
    mutationFn: () =>
      approveChapter(
        projectId,
        selectedId,
        activeTask!.id,
        overrideReason || undefined,
        [...acceptedMemory],
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tasks(projectId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.snapshot(projectId),
      });
      setOverrideReason("");
    },
    onError: (cause) => setError(cause.message),
  });
  const reaudit = useMutation({
    mutationFn: () =>
      auditChapterCommercially(projectId, selectedId, activeTask!.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tasks(projectId),
      });
      void queryClient.invalidateQueries({
        queryKey: ["chapter-audit", projectId, activeTask?.id],
      });
    },
    onError: (cause) => setError(cause.message),
  });
  // P0 章纲人审：只生成章纲，等人审批
  const generatePlan = useMutation({
    mutationFn: () =>
      generateChapterPlan(
        projectId,
        selectedId,
        instruction,
        selectedChapter?.volume_id ?? snapshot.data?.volumes[0]?.id ?? "1",
      ),
    onSuccess: (task) => {
      setError(null);
      navigate(`/projects/${projectId}/chapters/${task.chapter_id}`);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tasks(projectId),
      });
    },
    onError: (cause) => setError(cause.message),
  });
  // P0 批准章纲后，跑后续正文流水线
  const approvePlan = useMutation({
    mutationFn: () =>
      approveChapterPlan(projectId, selectedId, activeTask!.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tasks(projectId),
      });
      void queryClient.invalidateQueries({
        queryKey: ["chapter-stage", projectId, activeTask?.id],
      });
    },
    onError: (cause) => setError(cause.message),
  });
  // P1 整章修订：基于人编辑后的草稿重新审计+局部修订
  const revise = useMutation({
    mutationFn: () => reviseChapter(projectId, selectedId, activeTask!.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tasks(projectId),
      });
    },
    onError: (cause) => setError(cause.message),
  });
  // P3 局部重写：用 markdown.indexOf(selection) 算字符偏移
  const localRevise = useMutation({
    mutationFn: () => {
      const start = content.indexOf(localSelection);
      if (start < 0) {
        throw new Error("选中的段落未在当前正文中找到，请检查是否已保存。");
      }
      return localReviseChapter(projectId, selectedId, activeTask!.id, {
        start,
        end: start + localSelection.length,
        instruction: localInstruction,
      });
    },
    onSuccess: () => {
      setLocalSelection("");
      setLocalInstruction("");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tasks(projectId),
      });
    },
    onError: (cause) => setError(cause.message),
  });
  // 把审查问题 push 到决策队列
  function pushAuditDecision(
    item: { id: string; severity: string; description: string; citation: { quote: string } },
    kind: "continuity" | "style",
  ) {
    pushDecision(projectId, {
      id: `audit-${kind}-${item.id}`,
      type: "audit",
      title: `[${kind === "continuity" ? "连续性" : "文风"}] ${item.severity}`,
      content: item.description,
      reason: item.citation.quote,
    });
  }
  async function cancel() {
    if (!activeTask) return;
    await transitionTask(projectId, activeTask.id, "cancel");
    void queryClient.invalidateQueries({
      queryKey: queryKeys.tasks(projectId),
    });
  }
  function selectMemory(candidate: MemoryCandidate) {
    setAcceptedMemory((current) => {
      const next = new Set(current);
      if (next.has(candidate.stable_id)) next.delete(candidate.stable_id);
      else next.add(candidate.stable_id);
      return next;
    });
  }
  const prerequisitesReady = Boolean(
    workflow.data?.outline_confirmed &&
      workflow.data?.commercial_confirmed &&
      snapshot.data?.volumes.length,
  );
  // 审查标签的问题计数（连续性 + 文风），用于在标签按钮上显示徽章
  const auditIssueCount =
    (reports.data?.continuity?.length ?? 0) +
    (reports.data?.style?.length ?? 0);

  if (!project.data)
    return <div className="loading-state">读取章节工作台...</div>;
  return (
    <div className="chapter-page">
      <header className="project-heading compact">
        <div>
          <span className="eyebrow">章节工作台</span>
          <h1>{selectedChapter?.title ?? `第 ${selectedId} 章候选`}</h1>
          <p>
            {project.data.title} ·{" "}
            {content
              ? `${content.replace(/\s/g, "").length.toLocaleString("zh-CN")} 字`
              : "尚无正文"}
          </p>
        </div>
        {activeTask && (
          <RunStatus
            status={activeTask.status}
            connection={stream.connection}
          />
        )}
      </header>
      {!prerequisitesReady && (
        <section className="prerequisite-strip" aria-label="章节生成前置条件">
          <BookOpenCheck size={18} />
          <div>
            <strong>章节生成前置内容未完成</strong>
            <span>需要正式商业定位、全书大纲和至少一个分卷。</span>
          </div>
          <ChevronRight size={17} />
        </section>
      )}
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      <div className="chapter-workbench">
        <aside className="manuscript-rail">
          <div className="rail-heading">
            <span>卷章稿件</span>
            <button
              className="icon-button"
              type="button"
              onClick={() =>
                navigate(`/projects/${projectId}/chapters/${maxChapter + 1}`)
              }
              aria-label="新建章节"
              title="新建章节"
            >
              <CirclePlus size={16} />
            </button>
          </div>
          <div className="chapter-tree" ref={parentRef}>
            <div
              style={{
                height: virtualizer.getTotalSize(),
                position: "relative",
              }}
            >
              {virtualizer.getVirtualItems().map((row) => {
                const item = allTreeItems[row.index];
                return (
                  <div
                    key={`${item.type}-${item.id}`}
                    style={{
                      position: "absolute",
                      transform: `translateY(${row.start}px)`,
                      height: row.size,
                      width: "100%",
                    }}
                    className={
                      item.type === "volume"
                        ? "tree-volume"
                        : `tree-chapter${item.id === selectedId ? " is-active" : ""}`
                    }
                  >
                    {item.type === "volume" ? (
                      <strong>{item.label}</strong>
                    ) : (
                      <button
                        type="button"
                        onClick={() =>
                          navigate(`/projects/${projectId}/chapters/${item.id}`)
                        }
                      >
                        <span>{item.id}</span>
                        {item.label}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
          <button
            className="new-chapter-row"
            type="button"
            onClick={() =>
              navigate(`/projects/${projectId}/chapters/${maxChapter + 1}`)
            }
          >
            <CirclePlus size={14} />第 {maxChapter + 1} 章
          </button>
        </aside>
        <section className="chapter-editor">
          <div className="document-toolbar">
            <label>
              Agent 指令
              <textarea
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
              />
            </label>
            <div className="chapter-actions">
              {activeTask &&
                ["pending", "running"].includes(activeTask.status) && (
                  <button
                    className="icon-button"
                    type="button"
                    onClick={() => void cancel()}
                    aria-label="取消任务"
                    title="取消任务"
                  >
                    <XCircle size={16} />
                  </button>
                )}
              <button
                className="button button-secondary"
                type="button"
                disabled={
                  !prerequisitesReady ||
                  generate.isPending ||
                  activeTask?.status === "pending" ||
                  activeTask?.status === "running" ||
                  activeTask?.status === "awaiting_approval"
                }
                onClick={() => generate.mutate()}
              >
                {generate.isPending || activeTask?.status === "running" ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Sparkles size={15} />
                )}
                Agent 生成章节
              </button>
              {/* P0: 先生成章纲（人审），批准后再跑正文 */}
              <button
                className="button button-secondary"
                type="button"
                disabled={
                  !prerequisitesReady ||
                  generatePlan.isPending ||
                  activeTask?.status === "pending" ||
                  activeTask?.status === "running" ||
                  activeTask?.status === "awaiting_approval"
                }
                onClick={() => generatePlan.mutate()}
                title="只生成章纲，人审批后再跑正文"
              >
                {generatePlan.isPending ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <BookOpenCheck size={15} />
                )}
                先生成章纲
              </button>
              {/* P0 阶段：人审章纲后，批准继续生成正文 */}
              {activeTask?.status === "awaiting_approval" &&
                stageValue === "plan_awaiting_approval" && (
                  <button
                    className="button button-primary"
                    type="button"
                    disabled={approvePlan.isPending}
                    onClick={() => approvePlan.mutate()}
                  >
                    <Sparkles size={15} />
                    批准章纲，继续生成正文
                  </button>
                )}
              {/* P1 整章修订：基于人编辑后的草稿重新审计+局部修订 */}
              {activeTask?.status === "awaiting_approval" &&
                stageValue !== "plan_awaiting_approval" && (
                  <button
                    className="button button-secondary"
                    type="button"
                    disabled={revise.isPending || content !== savedContent}
                    onClick={() => revise.mutate()}
                    title="基于你编辑后的正文重新审计+局部修订"
                  >
                    {revise.isPending ? (
                      <LoaderCircle className="spin" size={15} />
                    ) : (
                      <Wand2 size={15} />
                    )}
                    重写整章
                  </button>
                )}
              {activeTask?.status === "awaiting_approval" && (
                <button
                  className="button button-primary"
                  type="button"
                  disabled={
                    approve.isPending ||
                    content !== savedContent ||
                    (!audit.data?.commercial_gate_passed &&
                      !overrideReason.trim())
                  }
                  onClick={() => approve.mutate()}
                >
                  <Check size={15} />
                  确认章节
                </button>
              )}
            </div>
          </div>
          {/* P3 局部重写区块：作者贴入要重写的段落 + 指令 */}
          {activeTask?.status === "awaiting_approval" &&
            stageValue !== "plan_awaiting_approval" && (
              <details className="local-revise-block">
                <summary>局部重写选中段落</summary>
                <label>
                  要重写的段落（从上方正文复制粘贴）
                  <textarea
                    value={localSelection}
                    onChange={(event) => setLocalSelection(event.target.value)}
                    rows={3}
                    placeholder="从正文复制要重写的段落贴入这里"
                  />
                </label>
                <label>
                  修改指令
                  <textarea
                    value={localInstruction}
                    onChange={(event) => setLocalInstruction(event.target.value)}
                    rows={2}
                    placeholder="例如：把这一段改为更紧张的氛围，加入主角的心理活动"
                  />
                </label>
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={
                    localRevise.isPending ||
                    !localSelection.trim() ||
                    !localInstruction.trim()
                  }
                  onClick={() => localRevise.mutate()}
                >
                  {localRevise.isPending ? (
                    <LoaderCircle className="spin" size={15} />
                  ) : (
                    <Wand2 size={15} />
                  )}
                  局部重写该段
                </button>
              </details>
            )}
          {content ? (
            <NovelEditor
              markdown={content}
              onChange={setContent}
              readOnly={activeTask?.status !== "awaiting_approval"}
            />
          ) : (
            <div className="editor-empty">
              选择正式章节阅读，或创建下一章候选。
            </div>
          )}
        </section>
        <aside className="evidence-rail">
          <div className="evidence-tabs">
            {(
              ["plan", "audit", "foreshadow", "context"] as EvidenceTab[]
            ).map((value) => (
              <button
                key={value}
                type="button"
                className={evidenceTab === value ? "is-active" : ""}
                onClick={() => setEvidenceTab(value)}
              >
                {
                  {
                    plan: "规划",
                    audit: "审查",
                    foreshadow: "伏笔",
                    context: "来源",
                  }[value]
                }
                {value === "audit" && auditIssueCount > 0 && (
                  <span className="evidence-badge">{auditIssueCount}</span>
                )}
              </button>
            ))}
          </div>
          <EvidenceContent
            tab={evidenceTab}
            plan={plan.data?.content}
            reports={reports.data}
            audit={audit.data}
            memory={memory.data ?? []}
            accepted={acceptedMemory}
            onMemory={selectMemory}
            run={run.data}
            overrideReason={overrideReason}
            setOverrideReason={setOverrideReason}
            onReaudit={() => reaudit.mutate()}
            reauditPending={reaudit.isPending}
            onPushAudit={pushAuditDecision}
          />
        </aside>
      </div>
    </div>
  );
}

// 审查报告中的单条问题项（连续性 / 文风共用同一结构）
interface AuditIssue {
  id: string;
  severity: string;
  description: string;
  citation: { quote: string };
}

// 审查区块：标题 + 问题列表（或空态文案），用于连续性与文风两类问题
function AuditSection({
  title,
  items,
  emptyText,
  onPush,
}: {
  title: string;
  items: AuditIssue[];
  emptyText: string;
  onPush?: (item: AuditIssue) => void;
}) {
  return (
    <section className="audit-section">
      <div className="audit-section-title">
        <h4>{title}</h4>
        {items.length > 0 && (
          <span className="audit-count">{items.length}</span>
        )}
      </div>
      {items.length ? (
        items.map((item) => (
          <article className="issue-row" key={item.id}>
            <strong>{item.severity}</strong>
            <p>{item.description}</p>
            <q>{item.citation.quote}</q>
            {onPush && (
              <button
                className="button button-secondary"
                type="button"
                onClick={() => onPush(item)}
              >
                加入待办
              </button>
            )}
          </article>
        ))
      ) : (
        <p className="muted">{emptyText}</p>
      )}
    </section>
  );
}

function EvidenceContent({
  tab,
  plan,
  reports,
  audit,
  memory,
  accepted,
  onMemory,
  run,
  overrideReason,
  setOverrideReason,
  onReaudit,
  reauditPending,
  onPushAudit,
}: {
  tab: EvidenceTab;
  plan?: string;
  reports?: AuditReports;
  audit?: Awaited<ReturnType<typeof getCommercialAudit>>;
  memory: MemoryCandidate[];
  accepted: Set<string>;
  onMemory: (candidate: MemoryCandidate) => void;
  run?: Awaited<ReturnType<typeof getTaskRun>>;
  overrideReason: string;
  setOverrideReason: (value: string) => void;
  onReaudit: () => void;
  reauditPending: boolean;
  onPushAudit?: (item: AuditIssue, kind: "continuity" | "style") => void;
}) {
  if (tab === "plan")
    return (
      <div className="evidence-content">
        <h3>章节计划</h3>
        <pre>{plan ?? "任务完成后显示计划。"}</pre>
      </div>
    );
  if (tab === "audit")
    return (
      <div className="evidence-content" role="region" aria-label="统一审查">
        <h3>审查</h3>
        <AuditSection
          title="连续性问题"
          items={reports?.continuity ?? []}
          emptyText="没有报告问题。"
          onPush={onPushAudit ? (item) => onPushAudit(item, "continuity") : undefined}
        />
        <AuditSection
          title="文风问题"
          items={reports?.style ?? []}
          emptyText="没有报告问题。"
          onPush={onPushAudit ? (item) => onPushAudit(item, "style") : undefined}
        />
        <section className="audit-section">
          <div className="audit-section-title">
            <h4>商业评分</h4>
          </div>
          {audit ? (
            <>
              <div className="score-line">
                <strong>{audit.commercial_report.total_score}</strong>
                <span>
                  / 100 ·{" "}
                  {audit.commercial_gate_passed
                    ? "达到确认门槛"
                    : `低于 ${audit.minimum_commercial_score} 分`}
                </span>
              </div>
              {audit.commercial_report.dimensions.map((item) => (
                <div className="dimension-row" key={item.dimension}>
                  <span>{item.dimension}</span>
                  <progress max="100" value={item.score} />
                  <strong>{item.score}</strong>
                </div>
              ))}
              <button
                className="button button-secondary"
                type="button"
                disabled={reauditPending}
                onClick={onReaudit}
              >
                <RefreshCw size={14} />
                重新审查当前正文
              </button>
              {!audit.commercial_gate_passed && (
                <label>
                  人工覆盖理由
                  <textarea
                    value={overrideReason}
                    onChange={(event) => setOverrideReason(event.target.value)}
                  />
                </label>
              )}
            </>
          ) : (
            <p className="muted">审查完成后显示评分。</p>
          )}
        </section>
      </div>
    );
  if (tab === "foreshadow")
    return (
      <div className="evidence-content">
        <h3>记忆候选</h3>
        {memory.length ? (
          memory.map((candidate) => (
            <label className="memory-candidate" key={candidate.stable_id}>
              <input
                type="checkbox"
                checked={accepted.has(candidate.stable_id)}
                onChange={() => onMemory(candidate)}
              />
              <span>
                <strong>{candidate.content}</strong>
                <small>
                  {candidate.kind} · {candidate.operation}
                </small>
                <q>{candidate.citation.quote}</q>
              </span>
            </label>
          ))
        ) : (
          <p className="muted">没有需要写入的持久记忆。</p>
        )}
      </div>
    );
  return (
    <div className="evidence-content">
      <h3>Agent 与来源</h3>
      {run?.agent_runs.map((item) => (
        <article className="agent-trace" key={`${item.agent}-${item.stage}`}>
          <strong>{item.agent}</strong>
          <span>
            {item.skill} · {item.duration_ms} ms
          </span>
          {item.source_paths.map((path) => (
            <code key={path}>{path}</code>
          ))}
        </article>
      )) ?? <p className="muted">尚无运行上下文。</p>}
      <button
        className="button button-secondary"
        type="button"
        onClick={() => window.location.reload()}
      >
        <RefreshCw size={14} />
        刷新状态
      </button>
    </div>
  );
}
