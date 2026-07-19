import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CirclePlus } from "lucide-react";
import { useNavigate } from "react-router";

import { listProjects } from "../api/client";
import { queryKeys } from "../app/queryKeys";

export function HomePage() {
  const navigate = useNavigate();
  const projects = useQuery({
    queryKey: queryKeys.projects,
    queryFn: listProjects,
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
            <button
              type="button"
              key={project.id}
              onClick={() => navigate(`/projects/${project.id}/today`)}
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
    </section>
  );
}
