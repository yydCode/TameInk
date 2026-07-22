import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, CirclePlus, Loader2, Trash2, X } from "lucide-react";
import { useNavigate } from "react-router";

import { deleteProject, listProjects, type Project } from "../api/client";
import { queryKeys } from "../app/queryKeys";

export function HomePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const projects = useQuery({
    queryKey: queryKeys.projects,
    queryFn: listProjects,
  });
  const [pendingDelete, setPendingDelete] = useState<Project | null>(null);
  const remove = useMutation({
    mutationFn: (project: Project) => deleteProject(project.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
      setPendingDelete(null);
    },
  });
  return (
    <section className="home-view">
      <header className="page-header">
        <div>
          <span className="eyebrow">作品架</span>
          <h1>Tame Ink</h1>
          <p>从正式设定、卷章结构和当前任务继续写作。</p>
        </div>
        <button
          className="button button-primary"
          type="button"
          onClick={() => window.dispatchEvent(new Event("tame-ink:create"))}
        >
          <CirclePlus size={16} />
          新建作品
        </button>
      </header>
      {projects.data?.length ? (
        <div className="project-list">
          {projects.data.map((project) => (
            <div className="project-row" key={project.id}>
              <button
                type="button"
                className="project-open"
                onClick={() => navigate(`/projects/${project.id}/workspace`)}
              >
                <span>
                  <strong>{project.title}</strong>
                  <small>
                    {project.genre ?? "未设置题材"} ·{" "}
                    {project.constraints ?? "未设置约束"}
                  </small>
                </span>
                <ArrowRight size={17} />
              </button>
              <button
                type="button"
                className="icon-button project-delete"
                aria-label={`删除作品 ${project.title}`}
                title="删除作品"
                onClick={() => setPendingDelete(project)}
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <span className="manuscript-rule" />
          <h1>项目概览需要一个作品</h1>
          <p>建立第一部作品后，正式设定和任务进度会出现在这里。</p>
          <button
            className="button button-primary"
            type="button"
            onClick={() => window.dispatchEvent(new Event("tame-ink:create"))}
          >
            <CirclePlus size={16} />
            创建第一部作品
          </button>
        </div>
      )}
      {pendingDelete && (
        <div className="dialog-backdrop">
          <div className="dialog" role="alertdialog" aria-modal="true">
            <div className="dialog-heading">
              <div>
                <span className="eyebrow">删除作品</span>
                <h2>确认删除《{pendingDelete.title}》？</h2>
              </div>
              <button
                className="icon-button"
                type="button"
                onClick={() => {
                  if (!remove.isPending) setPendingDelete(null);
                }}
                aria-label="关闭"
              >
                <X size={18} />
              </button>
            </div>
            <p className="dialog-warning">
              <AlertTriangle size={16} />
              这会永久删除该作品的全部设定、卷章、草稿和任务记录，且无法恢复。
            </p>
            {remove.error ? (
              <p className="inline-error">{remove.error.message}</p>
            ) : null}
            <div className="dialog-actions">
              <button
                className="button button-secondary"
                type="button"
                onClick={() => setPendingDelete(null)}
                disabled={remove.isPending}
              >
                取消
              </button>
              <button
                className="button button-danger"
                type="button"
                onClick={() => remove.mutate(pendingDelete)}
                disabled={remove.isPending}
              >
                {remove.isPending ? <Loader2 size={15} className="spin" /> : <Trash2 size={15} />}
                {remove.isPending ? "删除中…" : "永久删除"}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
