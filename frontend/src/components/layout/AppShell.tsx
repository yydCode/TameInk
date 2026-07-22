import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CirclePlus,
  History,
  LayoutDashboard,
  LibraryBig,
  PenLine,
  Settings,
} from "lucide-react";
import { NavLink, Outlet, useNavigate, useParams } from "react-router";
import type { LucideIcon } from "lucide-react";

import { listProjects, startCreativeProject } from "../../api/client";
import { queryKeys } from "../../app/queryKeys";
import { useHealth } from "../../hooks/useHealth";
import {
  CreateProjectDialog,
  type CreateProjectInput,
} from "../common/CreateProjectDialog";

// 导航项类型
interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
}
const navItems: NavItem[] = [
  { path: "workspace", label: "工作台", icon: LayoutDashboard },
  { path: "create", label: "创作", icon: PenLine },
  { path: "library", label: "故事库", icon: LibraryBig },
  { path: "review", label: "复盘", icon: History },
];

// 把多行文本拆成非空条目；作者留空时用默认值兜底，满足后端非空约束
function toLines(text: string, fallback: string): string[] {
  const lines = text.split("\n").map((item) => item.trim()).filter(Boolean);
  return lines.length > 0 ? lines : [fallback];
}

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
    mutationFn: (input: CreateProjectInput) =>
      startCreativeProject(input.project_id, {
        title: input.title,
        platform: input.platform,
        // 可选字段留空时补默认值，满足后端非空约束、减少作者输入
        genre_scope: input.genre_scope.trim() || "未定题材，待题材调研后确认",
        initial_intent:
          input.initial_intent.trim() || "写一个让读者持续追问后续的长篇故事。",
        first_story_goal: input.first_story_goal,
        constraints: toLines(input.constraints, "第三人称限知"),
        material_boundaries: toLines(
          input.material_boundaries,
          "仅使用已获授权素材；不模仿具体作者文风",
        ),
      }),
    onSuccess: ({ project }) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects });
      setShowCreate(false);
      navigate(`/projects/${project.id}/workspace`);
    },
  });

  const backendLabel = health.isPending
    ? "检查连接"
    : health.isSuccess
      ? "后端在线"
      : "后端离线";

  return (
    <div className="app-shell">
      <div className="app-body">
        <aside className="sidebar">
          <button className="brand" type="button" onClick={() => navigate("/")}>
          <span className="brand-mark">T</span>
          <span>
            <strong>Tame Ink</strong>
            <small>人机协作写作系统</small>
          </span>
        </button>
          <div
            className={`backend-state backend-state--${health.isSuccess ? "online" : health.isPending ? "checking" : "offline"}`}
          >
            <span />
            {backendLabel}
          </div>
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
                navigate(`/projects/${event.target.value}/workspace`)
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
            {navItems.map((item) =>
              projectId ? (
                <NavLink
                  key={item.path}
                  to={`/projects/${projectId}/${item.path}`}
                  className={({ isActive }) =>
                    `nav-item${isActive ? " is-active" : ""}`
                  }
                >
                  <item.icon size={16} />
                  <span>{item.label}</span>
                </NavLink>
              ) : (
                <button
                  key={item.path}
                  className="nav-item"
                  type="button"
                  onClick={() => navigate("/")}
                >
                  <item.icon size={16} />
                  <span>{item.label}</span>
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
            <span>模型与设置</span>
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
