import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  Bookmark,
  CalendarRange,
  ChartNoAxesCombined,
  ChevronDown,
  CirclePlus,
  ClipboardCheck,
  FileText,
  GitBranch,
  Library,
  Settings,
  Sliders,
  Sparkles,
  Target,
  TrendingUp,
  Upload,
  Zap,
} from "lucide-react";
import { NavLink, Outlet, useNavigate, useParams } from "react-router";
import type { LucideIcon } from "lucide-react";

import { createProject, listProjects } from "../../api/client";
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
interface NavGroup {
  id: string;
  label: string;
  icon: LucideIcon;
  items: NavItem[];
}

// 按创作阶段分组的导航结构
const navGroups: NavGroup[] = [
  {
    id: "today",
    label: "今日工作台",
    icon: Zap,
    items: [
      { path: "today", label: "今日工作台", icon: Zap },
    ],
  },
  {
    id: "planning",
    label: "新书策划",
    icon: Sparkles,
    items: [
      { path: "story", label: "故事设计", icon: Sparkles },
      { path: "market", label: "市场调研", icon: TrendingUp },
      { path: "opening", label: "黄金三章", icon: Sparkles },
      { path: "commercial", label: "商业定位", icon: ChartNoAxesCombined },
      { path: "bestseller", label: "爆款拆解", icon: TrendingUp },
      { path: "patterns", label: "套路模板", icon: Sparkles },
    ],
  },
  {
    id: "creation",
    label: "章节创作",
    icon: FileText,
    items: [
      { path: "chapters", label: "章节工作台", icon: FileText },
    ],
  },
  {
    id: "maintenance",
    label: "长篇维护",
    icon: Library,
    items: [
      { path: "memory", label: "记忆中心", icon: Library },
      { path: "batch-plan", label: "批量规划", icon: CalendarRange },
      { path: "materials", label: "素材库", icon: Bookmark },
      { path: "completion", label: "完本规划", icon: Target },
      { path: "imports", label: "作品导入", icon: Upload },
    ],
  },
  {
    id: "system",
    label: "系统",
    icon: GitBranch,
    items: [
      { path: "overview", label: "作品概览", icon: BookOpen },
      { path: "rules", label: "规则设置", icon: Sliders },
      { path: "decisions", label: "决策队列", icon: ClipboardCheck },
      { path: "runs", label: "运行记录", icon: GitBranch },
    ],
  },
];

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
  // 默认展开"今日工作台"组
  const [expandedGroup, setExpandedGroup] = useState<string>("today");

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
      // 新建作品后进入今日工作台
      navigate(`/projects/${project.id}/today`);
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
                navigate(`/projects/${event.target.value}/today`)
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
          <nav aria-label="项目导航" className="nav-groups">
            {navGroups.map((group) => (
              <div key={group.id} className="nav-group">
                <button
                  type="button"
                  className={`nav-group-header${expandedGroup === group.id ? " is-expanded" : ""}`}
                  onClick={() => setExpandedGroup(expandedGroup === group.id ? "" : group.id)}
                  aria-expanded={expandedGroup === group.id}
                >
                  <group.icon size={14} />
                  <span>{group.label}</span>
                  <ChevronDown size={13} className="nav-chevron" />
                </button>
                {expandedGroup === group.id && (
                  <div className="nav-group-items">
                    {group.items.map((item) =>
                      projectId ? (
                        <NavLink
                          key={item.path}
                          to={`/projects/${projectId}/${item.path}`}
                          className={({ isActive }) =>
                            `nav-item${isActive ? " is-active" : ""}`
                          }
                        >
                          <item.icon size={15} />
                          <span>{item.label}</span>
                        </NavLink>
                      ) : (
                        <button
                          key={item.path}
                          className="nav-item"
                          type="button"
                          onClick={() => navigate(`/${item.path}`)}
                        >
                          <item.icon size={15} />
                          <span>{item.label}</span>
                        </button>
                      ),
                    )}
                  </div>
                )}
              </div>
            ))}
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
