import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  ChartNoAxesCombined,
  CirclePlus,
  FileText,
  GitBranch,
  Library,
  Settings,
  Sparkles,
  Upload,
} from "lucide-react";
import { NavLink, Outlet, useNavigate, useParams } from "react-router";

import { createProject, listProjects } from "../../api/client";
import { queryKeys } from "../../app/queryKeys";
import { useHealth } from "../../hooks/useHealth";
import {
  CreateProjectDialog,
  type CreateProjectInput,
} from "../common/CreateProjectDialog";

const navigation = [
  ["overview", "项目概览", BookOpen],
  ["story", "故事设计", Sparkles],
  ["chapters", "章节工作台", FileText],
  ["commercial", "商业增长", ChartNoAxesCombined],
  ["memory", "记忆中心", Library],
  ["imports", "作品导入", Upload],
  ["runs", "运行记录", GitBranch],
] as const;

export function AppShell() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const health = useHealth();
  const projects = useQuery({
    queryKey: queryKeys.projects,
    queryFn: listProjects,
  });
  const [showCreate, setShowCreate] = useState(false);
  useEffect(() => {
    const open = () => setShowCreate(true);
    window.addEventListener("tame-ink:create", open);
    return () => window.removeEventListener("tame-ink:create", open);
  }, []);
  const create = useMutation({
    mutationFn: (input: CreateProjectInput) => createProject(input),
    onSuccess: ({ project }) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
      setShowCreate(false);
      navigate(`/projects/${project.id}/story`);
    },
  });
  const backendLabel = health.isPending
    ? "检查连接"
    : health.isSuccess
      ? "后端在线"
      : "后端离线";

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand" type="button" onClick={() => navigate("/")}>
          <span className="brand-mark">T</span>
          <span>
            <strong>Tame Ink</strong>
            <small>长篇创作工作台</small>
          </span>
        </button>
        <div
          className={`backend-state backend-state--${health.isSuccess ? "online" : health.isPending ? "checking" : "offline"}`}
        >
          <span />
          {backendLabel}
        </div>
        <NavLink
          className="icon-button"
          to="/settings"
          aria-label="模型设置"
          title="模型设置"
        >
          <Settings size={18} />
        </NavLink>
      </header>
      <div className="app-body">
        <aside className="sidebar">
          <button
            className="button new-project-button"
            type="button"
            onClick={() => setShowCreate(true)}
          >
            <CirclePlus size={16} />
            新建作品
          </button>
          <label className="project-picker">
            当前作品
            <select
              value={projectId ?? ""}
              onChange={(event) =>
                event.target.value &&
                navigate(`/projects/${event.target.value}/overview`)
              }
            >
              <option value="">未选择</option>
              {projects.data?.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.title}
                </option>
              ))}
            </select>
          </label>
          <nav aria-label="项目导航">
            {navigation.map(([path, label, Icon]) =>
              projectId ? (
                <NavLink
                  key={path}
                  to={`/projects/${projectId}/${path}`}
                  className={({ isActive }) =>
                    `nav-item${isActive ? " is-active" : ""}`
                  }
                >
                  <Icon size={16} />
                  <span>{label}</span>
                </NavLink>
              ) : (
                <button
                  key={path}
                  className="nav-item"
                  type="button"
                  onClick={() => navigate(`/${path}`)}
                >
                  <Icon size={16} />
                  <span>{label}</span>
                </button>
              ),
            )}
          </nav>
          <NavLink
            className={({ isActive }) =>
              `nav-item global-settings${isActive ? " is-active" : ""}`
            }
            to="/settings"
          >
            <Settings size={16} />
            <span>模型设置</span>
          </NavLink>
        </aside>
        <main className="main-content">
          <Outlet context={{ backendOnline: health.isSuccess }} />
        </main>
      </div>
      {create.error && (
        <div className="global-error" role="alert">
          {create.error.message}
        </div>
      )}
      {showCreate && (
        <CreateProjectDialog
          busy={create.isPending}
          onClose={() => setShowCreate(false)}
          onCreate={(input) => create.mutate(input)}
        />
      )}
    </div>
  );
}
