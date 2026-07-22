import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, History, RefreshCw } from "lucide-react";
import { useParams } from "react-router";

import { exportCreativeProject, listCreativeArtifacts, listTasks } from "../api/client";
import { queryKeys } from "../app/queryKeys";
import { artifactLabels, artifactStatusLabel, skillLabels } from "./creativeUi";

function taskLabel(subjectId: string | null): string {
  return subjectId && subjectId in skillLabels ? skillLabels[subjectId as keyof typeof skillLabels] : subjectId ?? "系统任务";
}

export function ReviewPage() {
  const { projectId = "" } = useParams();
  const queryClient = useQueryClient();
  const tasks = useQuery({ queryKey: queryKeys.tasks(projectId), queryFn: () => listTasks(projectId) });
  const artifacts = useQuery({ queryKey: queryKeys.creativeArtifacts(projectId), queryFn: () => listCreativeArtifacts(projectId) });
  const exportProject = useMutation({
    mutationFn: () => exportCreativeProject(projectId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.tasks(projectId) }),
  });
  const counts = useMemo(() => ({
    accepted: artifacts.data?.filter((artifact) => artifact.status === "accepted").length ?? 0,
    waiting: artifacts.data?.filter((artifact) => ["needs_decision", "conflict", "awaiting_approval"].includes(artifact.status)).length ?? 0,
    hypotheses: artifacts.data?.filter((artifact) => artifact.source_layer === "hypothesis").length ?? 0,
  }), [artifacts.data]);

  return (
    <section className="review-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">复盘 / 可追溯</span>
          <h1>决策与执行记录</h1>
          <p>这里记录任务结果与作者取舍，不以未经验证的商业分数作为创作门禁。</p>
        </div>
        <button className="button button-primary" type="button" onClick={() => exportProject.mutate()} disabled={exportProject.isPending}><Download size={15} />导出已确认章节</button>
      </header>
      {exportProject.data ? <p className="export-result">已导出 {exportProject.data.chapter_count} 章到 {exportProject.data.path}</p> : null}
      {exportProject.error ? <p className="inline-error">{exportProject.error.message}</p> : null}
      <div className="review-summary">
        <span><strong>{counts.waiting}</strong>等待作者决策</span>
        <span><strong>{counts.accepted}</strong>已确认候选</span>
        <span><strong>{counts.hypotheses}</strong>证据与假设</span>
      </div>
      <div className="review-layout">
        <section>
          <div className="section-title"><h2><History size={15} />任务记录</h2><button className="icon-button" type="button" onClick={() => void tasks.refetch()} aria-label="刷新任务" title="刷新任务"><RefreshCw size={15} /></button></div>
          <div className="review-list">
            {tasks.data?.map((task) => <article key={task.id}><span>{taskLabel(task.subject_id)}</span><small>{task.status}</small><time>{new Date(task.updated_at).toLocaleString("zh-CN")}</time>{task.error_message ? <p>{task.error_message}</p> : null}</article>)}
          </div>
        </section>
        <section>
          <div className="section-title"><h2>候选状态</h2><span>{artifacts.data?.length ?? 0} 条</span></div>
          <div className="review-list">
            {artifacts.data?.map((artifact) => <article key={artifact.id}><span>{artifactLabels[artifact.kind]}</span><small className={`artifact-state artifact-state--${artifact.source_layer}`}>{artifact.source_layer === "hypothesis" ? "假设" : artifactStatusLabel(artifact.status)}</small><time>{new Date(artifact.updated_at).toLocaleString("zh-CN")}</time></article>)}
          </div>
        </section>
      </div>
    </section>
  );
}
