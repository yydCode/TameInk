import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ClipboardPenLine,
  PanelRightClose,
  PanelRightOpen,
  RefreshCw,
  RotateCcw,
  X,
} from "lucide-react";
import { Link, useParams } from "react-router";

import {
  decideCreativeArtifact,
  getCreativeArtifactResult,
  getNextCreativeAction,
  getProject,
  listCreativeArtifacts,
  listExpectations,
  listTasks,
  runCreativeSkill,
  type CreativeArtifact,
} from "../api/client";
import { queryKeys } from "../app/queryKeys";
import { ArtifactCard } from "../components/creative/ArtifactCard";
import { ChapterDraftReview } from "../components/creative/ChapterDraftReview";
import { ExpectationHeatmap } from "../components/creative/ExpectationHeatmap";
import { StoryCardPicker } from "../components/creative/StoryCardPicker";
import {
  artifactLabels,
  artifactStatusLabel,
  artifactSummary,
  canConfirmArtifact,
  defaultFormalPath,
  skillLabels,
} from "./creativeUi";

export function CreativeWorkspacePage() {
  const { projectId = "" } = useParams();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [instruction, setInstruction] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const project = useQuery({
    queryKey: queryKeys.project(projectId),
    queryFn: () => getProject(projectId),
  });
  const next = useQuery({
    queryKey: queryKeys.creativeNext(projectId),
    queryFn: () => getNextCreativeAction(projectId),
    refetchInterval: 3_000,
  });
  const artifacts = useQuery({
    queryKey: queryKeys.creativeArtifacts(projectId),
    queryFn: () => listCreativeArtifacts(projectId),
    refetchInterval: 3_000,
  });
  const tasks = useQuery({
    queryKey: queryKeys.tasks(projectId),
    queryFn: () => listTasks(projectId),
    refetchInterval: 3_000,
  });
  const expectations = useQuery({
    queryKey: queryKeys.expectations(projectId),
    queryFn: () => listExpectations(projectId),
    refetchInterval: 10_000,
  });

  const selected = useMemo(() => {
    const id = selectedId ?? next.data?.artifact_id;
    return (
      artifacts.data?.find((a) => a.id === id) ??
      artifacts.data?.find((a) =>
        ["needs_decision", "conflict", "awaiting_approval"].includes(a.status),
      ) ??
      null
    );
  }, [artifacts.data, next.data?.artifact_id, selectedId]);

  const result = useQuery({
    queryKey: ["creative-artifact-result", projectId, selected?.id],
    queryFn: () => getCreativeArtifactResult(projectId, selected!),
    enabled: Boolean(selected),
  });

  const invalidate = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.creativeNext(projectId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.creativeArtifacts(projectId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks(projectId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.snapshot(projectId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.expectations(projectId) }),
    ]);

  const execute = useMutation({
    mutationFn: () => {
      if (!next.data?.skill) throw new Error("当前没有可执行的创作任务。");
      return runCreativeSkill(projectId, next.data.skill, {
        instruction: instruction.trim() || "按已确认内容继续执行。",
      });
    },
    onSuccess: () => {
      setInstruction("");
      void invalidate();
    },
  });

  const decide = useMutation({
    mutationFn: ({
      artifact,
      action,
      rationale,
      contentOverride,
    }: {
      artifact: CreativeArtifact;
      action: "accept" | "reject" | "mix" | "replan";
      rationale?: string;
      contentOverride?: string;
    }) => {
      const formalPath =
        action === "accept" || action === "mix"
          ? defaultFormalPath(artifact, result.data)
          : null;
      return decideCreativeArtifact(projectId, artifact.id, {
        expected_status: artifact.status,
        action,
        rationale:
          rationale ??
          (action === "accept"
            ? "作者确认该候选进入正式故事。"
            : "作者未采用该候选，需重新判断下一步。"),
        target_layer: formalPath?.startsWith("commitments/")
          ? "commitment"
          : formalPath
            ? "canon"
            : null,
        formal_path: formalPath,
        content_override: contentOverride ?? null,
      });
    },
    onSuccess: () => void invalidate(),
  });

  // Callback for ChapterDraftReview paragraph-level decisions
  const handleChapterDraftDecide = useCallback(
    (action: "accept" | "reject" | "mix", rationale: string, contentOverride?: string) => {
      if (!selected) return;
      decide.mutate({ artifact: selected, action, rationale, contentOverride });
    },
    [selected, decide],
  );

  useEffect(() => {
    if (next.data?.artifact_id && next.data.artifact_id !== selectedId) {
      setSelectedId(next.data.artifact_id);
    }
  }, [next.data?.artifact_id, selectedId]);

  const activeTask = tasks.data?.find((task) => task.id === next.data?.task_id);
  const actionTitle =
    next.data?.kind === "decision"
      ? "作者决策"
      : next.data?.kind === "wait"
        ? "正在生成"
        : next.data?.kind === "recover"
          ? "需要明确恢复"
          : next.data?.kind === "complete"
            ? "本轮已完成"
            : "下一步";

  // Determine whether selected artifact is a chapter_draft awaiting review
  const isChapterDraftReview =
    selected?.kind === "chapter_draft" &&
    selected.status === "awaiting_approval" &&
    result.data?.candidate != null;

  // 候选队列不再常驻左栏：只有当有多于一个待处理候选时，才在主轴上方显示切换条。
  const pendingArtifacts = useMemo(
    () =>
      (artifacts.data ?? []).filter((a) =>
        ["needs_decision", "conflict", "awaiting_approval", "ready"].includes(a.status),
      ),
    [artifacts.data],
  );
  const otherPending = pendingArtifacts.filter((a) => a.id !== selected?.id);

  // 期待热力：折叠态侧栏用的状态摘要（悬挂 = 已开启但未强化）。
  const expectationList = expectations.data ?? [];
  const urgentCount = expectationList.filter(
    (e) => e.status === "opened" && e.strengthening_event_ids.length === 0,
  ).length;
  const openCount = expectationList.filter((e) => e.status === "opened").length;

  return (
    <section className="creative-workspace">
      <header className="project-heading">
        <div>
          <span className="eyebrow">工作台 / 作者主导</span>
          <h1>{project.data?.title ?? "加载作品"}</h1>
          <p>作者决定故事走向；AI 仅生成可审阅的执行候选。</p>
        </div>
        <div className="project-heading-actions">
          <button
            className="icon-button"
            type="button"
            onClick={() =>
              void Promise.all([
                next.refetch(),
                artifacts.refetch(),
                tasks.refetch(),
                expectations.refetch(),
              ])
            }
            aria-label="刷新工作台"
            title="刷新工作台"
          >
            <RefreshCw size={16} />
          </button>
          <button
            className={`icon-button ${sidebarOpen ? "is-active" : ""}`}
            type="button"
            onClick={() => setSidebarOpen((open) => !open)}
            aria-label={sidebarOpen ? "收起期待账本" : "展开期待账本"}
            aria-pressed={sidebarOpen}
            title={sidebarOpen ? "收起期待账本" : "展开期待账本"}
          >
            {sidebarOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
            {urgentCount > 0 && !sidebarOpen ? (
              <span className="icon-badge">{urgentCount}</span>
            ) : null}
          </button>
        </div>
      </header>

      {/* ── Next action banner ──────────────────────────────────── */}
      <section
        className={`next-action next-action--${next.data?.kind ?? "loading"}`}
        aria-live="polite"
      >
        <span className="eyebrow">{actionTitle}</span>
        <strong>{next.data?.reason ?? "正在读取当前创作状态。"}</strong>
        {next.data?.kind === "execute" && next.data.skill ? (
          <div className="next-action-form">
            <label>
              给 {skillLabels[next.data.skill]} 的补充指令
              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                placeholder="说明这一步希望验证、保留或改变的方向。"
              />
            </label>
            <button
              className="button button-primary"
              type="button"
              onClick={() => execute.mutate()}
              disabled={execute.isPending}
            >
              <ClipboardPenLine size={15} />
              执行 {skillLabels[next.data.skill]}
            </button>
          </div>
        ) : null}
        {next.data?.kind === "input" ? (
          <StoryCardPicker projectId={projectId} onActivated={() => void invalidate()} />
        ) : null}
        {next.data?.kind === "recover" ? (
          <Link className="button button-primary" to={`/projects/${projectId}/create`}>
            <RotateCcw size={15} />
            明确重启任务
          </Link>
        ) : null}
        {next.data?.kind === "wait" ? (
          <small>
            {activeTask
              ? `任务状态：${activeTask.status}`
              : "等待任务状态同步。"}
          </small>
        ) : null}
      </section>

      {/* ── Main axis (single column) + collapsible sidebar ─────── */}
      <div className={`creative-workspace-grid ${sidebarOpen ? "is-sidebar-open" : ""}`}>
        {/* Main axis: focus on the one candidate awaiting review */}
        <div className="workspace-main" aria-label="当前候选">
          {/* 多个待处理候选时，主轴上方显示切换条，而非常驻左栏 */}
          {otherPending.length > 0 ? (
            <div className="artifact-switch-bar" role="tablist" aria-label="其他待处理候选">
              <span className="artifact-switch-hint">
                还有 {otherPending.length} 项待处理
              </span>
              {otherPending.map((artifact) => (
                <button
                  key={artifact.id}
                  type="button"
                  className={`artifact-chip artifact-chip--${artifact.source_layer}`}
                  onClick={() => setSelectedId(artifact.id)}
                >
                  {artifactLabels[artifact.kind]}
                  <small>{artifactStatusLabel(artifact.status)}</small>
                </button>
              ))}
            </div>
          ) : null}

        {/* Candidate detail / chapter draft review */}
        <section className="artifact-detail" aria-label="候选详情">
          {selected ? (
            <>
              <div className="section-title">
                <h2>{artifactLabels[selected.kind]}</h2>
                <span
                  className={`artifact-state artifact-state--${selected.source_layer}`}
                >
                  {selected.source_layer === "hypothesis"
                    ? "假设"
                    : artifactStatusLabel(selected.status)}
                </span>
              </div>

              {result.isLoading ? (
                <p className="muted">正在读取候选内容。</p>
              ) : null}
              {result.error ? (
                <p className="inline-error">
                  候选内容读取失败：{result.error.message}
                </p>
              ) : null}

              {/* Chapter draft gets paragraph-level review */}
              {isChapterDraftReview && result.data ? (
                <ChapterDraftReview
                  artifact={selected}
                  result={result.data}
                  isPending={decide.isPending}
                  onDecide={handleChapterDraftDecide}
                />
              ) : (
                <>
                  <p className="artifact-summary">
                    {artifactSummary(selected, result.data)}
                  </p>
                  {result.data?.decision_requests.length ? (
                    <div className="decision-questions">
                      {result.data.decision_requests.map((req) => (
                        <p key={req.id}>
                          <strong>{req.question}</strong>
                          <span>{req.options.join(" / ")}</span>
                        </p>
                      ))}
                    </div>
                  ) : null}
                  {result.data?.candidate?.payload ? (
                    <ArtifactCard
                      kind={result.data.candidate.artifact_kind}
                      payload={result.data.candidate.payload}
                    />
                  ) : null}
                  {["needs_decision", "conflict", "awaiting_approval", "ready"].includes(
                    selected.status,
                  ) ? (
                    <div className="artifact-actions">
                      {canConfirmArtifact(selected, result.data) ? (
                        <button
                          className="button button-primary"
                          type="button"
                          onClick={() =>
                            decide.mutate({ artifact: selected, action: "accept" })
                          }
                          disabled={decide.isPending}
                        >
                          <Check size={15} />
                          确认进入正式故事
                        </button>
                      ) : null}
                      <button
                        className="button button-secondary"
                        type="button"
                        onClick={() =>
                          decide.mutate({
                            artifact: selected,
                            action:
                              selected.source_layer === "hypothesis"
                                ? "replan"
                                : "reject",
                          })
                        }
                        disabled={decide.isPending}
                      >
                        <X size={15} />
                        {selected.source_layer === "hypothesis"
                          ? "不采用，重新规划"
                          : "不采用"}
                      </button>
                    </div>
                  ) : null}
                </>
              )}
            </>
          ) : (
            <div className="artifact-placeholder">
              <ClipboardPenLine size={22} />
              <p>先执行一个明确任务，再审阅 AI 提交的候选。</p>
            </div>
          )}
        </section>
        </div>

        {/* Right: expectation ledger — collapsed to a rail by default */}
        {sidebarOpen ? (
          <aside className="expectation-sidebar" aria-label="期待账本">
            <div className="section-title">
              <h2>期待账本</h2>
              <span>{expectationList.length} 条</span>
            </div>
            <ExpectationHeatmap expectations={expectationList} />
          </aside>
        ) : (
          <button
            type="button"
            className="expectation-rail"
            onClick={() => setSidebarOpen(true)}
            aria-label="展开期待账本"
            title="展开期待账本"
          >
            <PanelRightOpen size={16} />
            <span className="expectation-rail-metric">
              <strong>{urgentCount}</strong>悬挂
            </span>
            <span className="expectation-rail-metric">
              <strong>{openCount}</strong>开启
            </span>
          </button>
        )}
      </div>

      {execute.error || decide.error ? (
        <p className="inline-error">
          {execute.error?.message ?? decide.error?.message}
        </p>
      ) : null}
    </section>
  );
}
