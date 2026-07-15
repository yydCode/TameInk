import { FormEvent, useEffect, useState } from "react";
import { BookOpen, Check, ChevronRight, FilePlus2, FolderOpen, GitCompareArrows, Library, LoaderCircle, Plus, Search, Settings, Sparkles, X } from "lucide-react";
import { approveChapter, approveOutline, approveSetting, createOutline, createProject, getDraft, getHealth, getProject, getTask, Project, saveDraft, startChapter, Task } from "./api/client";
import { NovelEditor } from "./components/editor/NovelEditor";
import { RunStatus } from "./features/runs/RunStatus";
import { subscribeTaskEvents } from "./api/events";

type View = "overview" | "story" | "chapters" | "memory" | "runs" | "settings";

const emptyDraft = "# 故事设定\n\n从核心冲突、主角目标和世界规则开始。";
const SESSION_KEY = "tame-ink.active-session";

function App() {
  const [backendStatus, setBackendStatus] = useState<"checking" | "online" | "offline">("checking");
  const [project, setProject] = useState<Project | null>(null);
  const [view, setView] = useState<View>("overview");
  const [draft, setDraft] = useState(emptyDraft);
  const [originalDraft, setOriginalDraft] = useState(emptyDraft);
  const [activeTask, setActiveTask] = useState<Task | null>(null);
  const [draftPath, setDraftPath] = useState("setting.md");
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getHealth({ signal: controller.signal }).then(() => setBackendStatus("online"), () => setBackendStatus("offline"));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return;
    let session: { projectId: string; taskId: string; path: string; confirmedDraft: string };
    try {
      session = JSON.parse(raw) as typeof session;
    } catch {
      localStorage.removeItem(SESSION_KEY);
      return;
    }
    Promise.all([
      getProject(session.projectId),
      getTask(session.projectId, session.taskId),
      getDraft(session.projectId, session.taskId, session.path),
    ]).then(([restoredProject, restoredTask, restoredDraft]) => {
      setProject(restoredProject);
      setActiveTask(restoredTask);
      setDraft(restoredDraft.content);
      setOriginalDraft(session.confirmedDraft);
      setDraftPath(session.path);
      setView("story");
    }).catch(() => localStorage.removeItem(SESSION_KEY));
  }, []);

  const activeProjectId = project?.id;
  const activeTaskId = activeTask?.id;

  useEffect(() => {
    if (!activeProjectId || !activeTaskId) return;
    localStorage.setItem(SESSION_KEY, JSON.stringify({ projectId: activeProjectId, taskId: activeTaskId, path: draftPath, confirmedDraft: originalDraft }));
  }, [activeProjectId, activeTaskId, draftPath, originalDraft]);

  useEffect(() => {
    if (!activeProjectId || !activeTaskId || draft === originalDraft) return;
    const timeout = window.setTimeout(() => {
      saveDraft(activeProjectId, activeTaskId, draftPath, draft).catch((cause) => {
        setError(cause instanceof Error ? cause.message : "草稿自动保存失败");
      });
    }, 600);
    return () => window.clearTimeout(timeout);
  }, [activeProjectId, activeTaskId, draft, draftPath, originalDraft]);

  useEffect(() => {
    if (!activeProjectId || !activeTaskId) return;
    const terminalStatuses: Task["status"][] = ["completed", "failed", "cancelled", "interrupted"];
    const subscription = subscribeTaskEvents(activeProjectId, activeTaskId, {
      onEvent: ({ data }) => {
        const statusByEvent: Record<string, Task["status"]> = {
          "task.created": "pending", "task.started": "running", "task.awaiting_approval": "awaiting_approval",
          "task.approved": "running", "task.completed": "completed", "task.failed": "failed",
          "task.cancelled": "cancelled", "task.recovered": "interrupted",
        };
        const status = statusByEvent[data.type];
        if (status) {
          setActiveTask((current) => current ? { ...current, status, updated_at: data.timestamp } : current);
          if (terminalStatuses.includes(status)) queueMicrotask(() => subscription.cancel());
        }
      },
      onError: () => undefined,
      onConnectionChange: () => undefined,
    });
    return () => subscription.cancel();
  }, [activeProjectId, activeTaskId]);

  const isDirty = draft !== originalDraft;
  const navItems: Array<{ id: View; label: string; icon: typeof BookOpen }> = [
    { id: "overview", label: "项目概览", icon: BookOpen },
    { id: "story", label: "故事设计", icon: Sparkles },
    { id: "chapters", label: "章节工作台", icon: FilePlus2 },
    { id: "memory", label: "记忆中心", icon: Library },
    { id: "runs", label: "运行记录", icon: GitCompareArrows },
    { id: "settings", label: "模型设置", icon: Settings },
  ];

  async function handleCreate(input: { project_id: string; title: string; genre: string; target_words: number; constraints: string; setting_draft: string }) {
    setError(null);
    try {
      const result = await createProject(input);
      setProject(result.project);
      setActiveTask(result.task);
      setDraftPath("setting.md");
      setDraft(input.setting_draft);
      setOriginalDraft(input.setting_draft);
      setShowCreate(false);
      setView("story");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建项目失败");
    }
  }

  async function confirmCurrent() {
    if (!project || !activeTask) return;
    setError(null);
    try {
      const task = draftPath === "outline-book.md"
        ? await approveOutline(project.id, activeTask.id)
        : await approveSetting(project.id, activeTask.id);
      setActiveTask(task);
      setOriginalDraft(draft);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "确认版本失败");
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark">TI</span><div><h1>Tame Ink</h1><span>本地长篇创作工作台</span></div></div>
        <div className={`status status--${backendStatus}`} role="status"><span className="status__indicator" />{backendStatus === "checking" ? "正在连接" : backendStatus === "online" ? "后端在线" : "后端离线"}</div>
      </header>
      <div className="app-body">
        <aside className="sidebar">
          <button className="new-project-button" type="button" onClick={() => setShowCreate(true)}><Plus size={16} />新建作品</button>
          <div className="sidebar-section-label">工作区</div>
          <nav aria-label="项目导航">
            {navItems.map(({ id, label, icon: Icon }) => <button key={id} className={`nav-item ${view === id ? "is-active" : ""}`} type="button" onClick={() => setView(id)}><Icon size={16} /><span>{label}</span>{view === id && <ChevronRight size={14} />}</button>)}
          </nav>
          <div className="sidebar-project">{project ? <><span className="project-dot" /><div><strong>{project.title}</strong><small>{project.genre ?? "未设置题材"}</small></div></> : <><FolderOpen size={16} /><span>尚未打开项目</span></>}</div>
        </aside>
        <main className="main-content">
          {error && <div className="alert alert-error" role="alert"><X size={16} />{error}<button type="button" onClick={() => setError(null)} aria-label="关闭错误"><X size={14} /></button></div>}
          {!project ? <EmptyState onCreate={() => setShowCreate(true)} /> : <>
            <div className="content-header"><div><div className="eyebrow">{navItems.find((item) => item.id === view)?.label}</div><h2>{project.title}</h2></div><div className="header-actions"><span className={`save-state ${isDirty ? "is-dirty" : ""}`}>{isDirty ? "草稿未确认" : "已保存"}</span>{isDirty && view === "story" && <button className="button button-primary" type="button" onClick={confirmCurrent}><Check size={15} />确认版本</button>}</div></div>
            <div className="workspace-grid"><section className="editor-panel">{view === "overview" && <Overview project={project} onOpen={() => setView("chapters")} />}{view === "story" && <StoryView project={project} draft={draft} setDraft={setDraft} task={activeTask} onApprove={confirmCurrent} onTask={(task) => { setActiveTask(task); setDraftPath("outline-book.md"); }} onError={setError} />}{view === "chapters" && <ChapterView project={project} draft={draft} setDraft={setDraft} task={activeTask} onTask={(task) => { setActiveTask(task); setDraftPath("chapter.md"); }} onError={setError} />}{view === "memory" && <MemoryView project={project} />}{view === "runs" && <RunsView task={activeTask} project={project} />}{view === "settings" && <SettingsView />}</section><aside className="context-panel"><ContextPanel project={project} task={activeTask} dirty={isDirty} /></aside></div>
          </>}
        </main>
      </div>
      {showCreate && <CreateProjectDialog onClose={() => setShowCreate(false)} onCreate={handleCreate} />}
    </div>
  );
}

function EmptyState({ onCreate }: { onCreate: () => void }) { return <div className="empty-state"><div className="empty-icon"><BookOpen size={26} /></div><h2>从一个新故事开始</h2><p>创建本地作品后，设定、大纲、章节和记忆都会保存在你的工作区。</p><button className="button button-primary" type="button" onClick={onCreate}><Plus size={16} />创建第一部作品</button></div>; }

function Overview({ project, onOpen }: { project: Project; onOpen: () => void }) { return <div className="overview-view"><div className="welcome-band"><div><span className="eyebrow">作品概览</span><h3>{project.title}</h3><p>{project.constraints ?? "尚未填写创作约束"}</p></div><button className="button button-secondary" type="button" onClick={onOpen}>打开章节工作台<ChevronRight size={15} /></button></div><div className="metric-grid"><Metric label="目标字数" value={project.target_words ? `${Math.round(project.target_words / 10000)} 万字` : "未设置"} /><Metric label="当前章节" value="尚未开始" /><Metric label="待处理伏笔" value="0" /></div><div className="next-step"><Sparkles size={18} /><div><strong>下一步：确认故事设定</strong><span>先完善核心冲突和世界规则，再开始生成全书大纲。</span></div><button className="icon-button" type="button" onClick={() => onOpen()} aria-label="继续"><ChevronRight size={17} /></button></div></div>; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="metric"><span>{label}</span><strong>{value}</strong></div>; }

function StoryView({ project, draft, setDraft, task, onApprove, onTask, onError }: { project: Project; draft: string; setDraft: (value: string) => void; task: Task | null; onApprove: () => void; onTask: (task: Task) => void; onError: (message: string) => void }) { const [busy, setBusy] = useState(false); async function outline() { setBusy(true); try { onTask(await createOutline(project.id, draft)); } catch (cause) { onError(cause instanceof Error ? cause.message : "大纲任务启动失败"); } finally { setBusy(false); } } return <div className="editor-view"><div className="section-heading"><div><span className="eyebrow">故事设计</span><h3>核心设定</h3></div><div className="header-actions">{task?.status === "awaiting_approval" && <button className="button button-secondary" type="button" onClick={onApprove}><Check size={15} />确认当前草稿</button>}{task?.status === "completed" && <button className="button button-primary" type="button" onClick={outline} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <Sparkles size={15} />}生成全书大纲</button>}</div></div><NovelEditor markdown={draft} onChange={setDraft} /><div className="editor-footer"><span>Markdown · 自动保存到草稿区</span>{task && <RunStatus status={task.status} connection="connected" />}</div></div>; }

function ChapterView({ project, draft, setDraft, task, onTask, onError }: { project: Project; draft: string; setDraft: (value: string) => void; task: Task | null; onTask: (task: Task) => void; onError: (message: string) => void }) { const [plan, setPlan] = useState("开场建立主角处境，并让核心冲突在本章结尾露出一角。"); const [chapterId, setChapterId] = useState("1"); const [busy, setBusy] = useState(false); async function start() { setBusy(true); try { onTask(await startChapter(project.id, chapterId, { plan, draft, issues: [] })); } catch (cause) { onError(cause instanceof Error ? cause.message : "章节任务启动失败"); } finally { setBusy(false); } } async function approve() { if (!task) return; setBusy(true); try { onTask(await approveChapter(project.id, chapterId, task.id)); } catch (cause) { onError(cause instanceof Error ? cause.message : "章节确认失败"); } finally { setBusy(false); } } return <div className="editor-view"><div className="section-heading"><div><span className="eyebrow">逐章创作</span><label className="chapter-number-label" htmlFor="chapter-id">第</label><input id="chapter-id" className="chapter-number" value={chapterId} onChange={(event) => setChapterId(event.target.value.replace(/\D/g, ""))} inputMode="numeric" aria-label="章节编号" /><span className="chapter-number-label">章</span></div><div className="header-actions">{task?.status === "awaiting_approval" && <button className="button button-secondary" type="button" onClick={approve} disabled={busy}><Check size={15} />确认章节</button>}<button className="button button-primary" type="button" onClick={start} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <Sparkles size={15} />}生成章节草稿</button></div></div><label className="field-label" htmlFor="chapter-plan">章节计划</label><textarea id="chapter-plan" className="plan-input" value={plan} onChange={(event) => setPlan(event.target.value)} /><NovelEditor markdown={draft} onChange={setDraft} /><div className="editor-footer"><span>当前任务：{task ? task.status : "尚未启动"}</span><span>项目：{project.id}</span></div></div>; }

function MemoryView({ project }: { project: Project }) { return <div className="placeholder-view"><Library size={24} /><h3>记忆中心</h3><p>确认章节后，人物事实、事件、关系和伏笔会在这里按来源归档。</p><div className="memory-empty">项目 {project.id} 当前还没有已确认的记忆记录。</div></div>; }
function RunsView({ task, project }: { task: Task | null; project: Project }) { return <div className="runs-view"><div className="section-heading"><div><span className="eyebrow">运行记录</span><h3>任务活动</h3></div></div>{task ? <div className="run-card"><div><strong>{task.kind === "write" ? "创作任务" : "读取任务"}</strong><span>{task.id}</span></div><RunStatus status={task.status} connection="connected" /></div> : <div className="memory-empty">{project.title} 还没有运行记录。</div>}</div>; }
function SettingsView() { return <div className="placeholder-view"><Settings size={24} /><h3>模型设置</h3><p>模型配置由本地后端管理，API Key 使用系统密钥环保存。</p><div className="setting-row"><span>提供方</span><strong>OpenAI-compatible</strong></div><div className="setting-row"><span>连接状态</span><strong>未验证</strong></div></div>; }
function ContextPanel({ project, task, dirty }: { project: Project; task: Task | null; dirty: boolean }) { return <><div className="panel-heading"><div><span className="eyebrow">Agent 面板</span><h3>上下文</h3></div><Search size={16} /></div><div className="context-block"><span className="context-label">当前项目</span><strong>{project.title}</strong><span className="muted">{project.genre ?? "未设置题材"}</span></div><div className="context-block"><span className="context-label">任务状态</span>{task ? <RunStatus status={task.status} connection="connected" /> : <span className="muted">暂无活动任务</span>}</div><div className="context-block"><span className="context-label">版本门禁</span><div className="gate-row"><span className={`gate-dot ${dirty ? "gate-dot--warn" : ""}`} />{dirty ? "等待用户确认" : "正式内容未修改"}</div></div><div className="source-list"><span className="context-label">已加载来源</span><span>project.yaml</span><span>canon/world/setting.md</span><span>memory/（确认后生成）</span></div></>; }

function CreateProjectDialog({ onClose, onCreate }: { onClose: () => void; onCreate: (input: { project_id: string; title: string; genre: string; target_words: number; constraints: string; setting_draft: string }) => void }) { const [form, setForm] = useState({ project_id: "my-novel", title: "", genre: "", target_words: 2000000, constraints: "", setting_draft: emptyDraft }); function submit(event: FormEvent) { event.preventDefault(); onCreate(form); } return <div className="dialog-backdrop"><form className="dialog" onSubmit={submit}><div className="dialog-heading"><div><span className="eyebrow">新建作品</span><h2>建立你的故事</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button></div><label className="field-label" htmlFor="project-id">项目 ID</label><input id="project-id" value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value })} required pattern="[a-z0-9]+(?:-[a-z0-9]+)*" /><div className="form-grid"><div><label className="field-label" htmlFor="project-title">书名</label><input id="project-title" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required /></div><div><label className="field-label" htmlFor="project-genre">题材</label><input id="project-genre" value={form.genre} onChange={(event) => setForm({ ...form, genre: event.target.value })} placeholder="例如：东方幻想" required /></div></div><label className="field-label" htmlFor="target-words">目标字数</label><input id="target-words" type="number" min="1" value={form.target_words} onChange={(event) => setForm({ ...form, target_words: Number(event.target.value) })} required /><label className="field-label" htmlFor="constraints">创作约束</label><textarea id="constraints" value={form.constraints} onChange={(event) => setForm({ ...form, constraints: event.target.value })} placeholder="叙事视角、风格、禁用内容等" required /><div className="dialog-actions"><button className="button button-secondary" type="button" onClick={onClose}>取消</button><button className="button button-primary" type="submit"><Plus size={15} />创建并进入工作台</button></div></form></div>; }

export default App;
