import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Download, History, RotateCcw, X } from "lucide-react";
import { Link, useParams } from "react-router";

import {
  compareRevisions,
  getProjectUsage,
  listRevisions,
  restoreRevision,
  type RevisionDiff,
} from "../api/client";
import { queryKeys } from "../app/queryKeys";
import { useProjectWorkspace } from "../features/workspace/useProjectWorkspace";

export function OverviewPage() {
  const { projectId = "" } = useParams();
  const queryClient = useQueryClient();
  const { project, snapshot, workflow } = useProjectWorkspace(projectId);
  const usage = useQuery({
    queryKey: queryKeys.usage(projectId),
    queryFn: () => getProjectUsage(projectId),
  });
  const revisions = useQuery({
    queryKey: queryKeys.revisions(projectId),
    queryFn: () => listRevisions(projectId),
  });
  const [diff, setDiff] = useState<{
    revisionId: string;
    changes: RevisionDiff[];
  } | null>(null);
  const compare = useMutation({
    mutationFn: async (revisionId: string) => ({
      revisionId,
      changes: await compareRevisions(
        projectId,
        revisionId,
        revisions.data![0].id,
      ),
    }),
    onSuccess: setDiff,
  });
  const restore = useMutation({
    mutationFn: (revisionId: string) =>
      restoreRevision(projectId, revisionId, revisions.data![0].id),
    onSuccess: () => {
      setDiff(null);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.snapshot(projectId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.revisions(projectId),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.workflow(projectId),
      });
    },
  });
  if (project.isPending || snapshot.isPending)
    return <div className="loading-state">读取作品...</div>;
  if (!project.data || !snapshot.data)
    return (
      <div className="error-state" role="alert">
        作品数据读取失败
      </div>
    );
  const next = !workflow.data?.setting_confirmed
    ? ["确认故事设定", "story"]
    : !workflow.data?.commercial_confirmed
      ? ["确认商业定位", "commercial"]
      : !workflow.data?.outline_confirmed
        ? ["确认全书大纲", "story"]
        : !workflow.data?.volume_one_confirmed
          ? ["规划一个分卷", "story"]
          : [
              snapshot.data.stats.chapter_count ? "继续写下一章" : "开始第一章",
              "chapters",
            ];
  return (
    <div className="overview-page">
      <header className="project-heading">
        <div>
          <span className="eyebrow">作品概览</span>
          <h1>{project.data.title}</h1>
          <p>
            {project.data.genre ?? "未设置题材"} ·{" "}
            {project.data.constraints ?? "未设置创作约束"}
          </p>
        </div>
        <a
          className="button button-secondary"
          href={`/api/projects/${projectId}/exports/project.zip`}
        >
          <Download size={15} />
          导出作品
        </a>
      </header>
      <section className="overview-ledger" aria-label="作品统计">
        <div>
          <span>正式字数</span>
          <strong>
            {snapshot.data.stats.total_words.toLocaleString("zh-CN")}
          </strong>
        </div>
        <div>
          <span>正式章节</span>
          <strong>{snapshot.data.stats.chapter_count}</strong>
        </div>
        <div>
          <span>分卷</span>
          <strong>{snapshot.data.stats.volume_count}</strong>
        </div>
        <div>
          <span>待回收伏笔</span>
          <strong>{snapshot.data.stats.active_foreshadow_count}</strong>
        </div>
      </section>
      <Link className="continue-strip" to={`/projects/${projectId}/${next[1]}`}>
        <span>
          <small>下一步</small>
          <strong>{next[0]}</strong>
        </span>
        <ArrowRight size={18} />
      </Link>
      <div className="overview-columns">
        <section>
          <div className="section-title">
            <h2>正式文档</h2>
            <span>{snapshot.data.documents.length} 项</span>
          </div>
          <div className="document-ledger">
            {snapshot.data.documents.map((document) => (
              <div key={document.path}>
                <span>{document.kind}</span>
                <strong>{document.title}</strong>
                <small>
                  {document.word_count.toLocaleString("zh-CN")} 字 ·{" "}
                  {new Date(document.updated_at).toLocaleDateString("zh-CN")}
                </small>
              </div>
            ))}
          </div>
        </section>
        <aside>
          <div className="section-title">
            <h2>
              <History size={16} />
              版本
            </h2>
            <span>{revisions.data?.length ?? 0}</span>
          </div>
          <ol className="revision-list">
            {revisions.data?.slice(0, 8).map((revision, index) => (
              <li key={revision.id}>
                <button
                  type="button"
                  disabled={index === 0}
                  onClick={() => compare.mutate(revision.id)}
                >
                  <strong>{revision.message}</strong>
                  <code>{revision.id.slice(0, 10)}</code>
                </button>
              </li>
            ))}
          </ol>
          <div className="usage-line">
            <span>模型用量</span>
            <strong>
              {usage.data?.total_tokens.toLocaleString("zh-CN") ?? 0} tokens
            </strong>
            <small>¥{usage.data?.total_cost_cny.toFixed(4) ?? "0.0000"}</small>
          </div>
        </aside>
      </div>
      {diff && (
        <div className="dialog-backdrop">
          <div
            className="dialog version-dialog"
            role="dialog"
            aria-modal="true"
            aria-label="版本差异"
          >
            <div className="dialog-heading">
              <div>
                <span className="eyebrow">版本恢复</span>
                <h2>{diff.changes.length} 个文件发生变化</h2>
              </div>
              <button
                className="icon-button"
                type="button"
                onClick={() => setDiff(null)}
                aria-label="关闭"
              >
                <X size={17} />
              </button>
            </div>
            <div className="version-diff-list">
              {diff.changes.map((change) => (
                <article key={change.path}>
                  <div>
                    <strong>{change.path}</strong>
                    <span>{change.status}</span>
                  </div>
                  <pre>{change.patch}</pre>
                </article>
              ))}
            </div>
            <div className="dialog-actions">
              <button
                className="button button-secondary"
                type="button"
                onClick={() => setDiff(null)}
              >
                取消
              </button>
              <button
                className="button button-primary"
                type="button"
                disabled={restore.isPending}
                onClick={() => restore.mutate(diff.revisionId)}
              >
                <RotateCcw size={15} />
                恢复到此版本
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
