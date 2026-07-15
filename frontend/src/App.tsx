import { FormEvent, useEffect, useState } from "react";
import { BookOpen, Check, ChevronRight, FilePlus2, FolderOpen, GitCompareArrows, Library, LoaderCircle, Plus, Search, Settings, Sparkles, Trash2, Upload, X } from "lucide-react";
import { ApiError, approveChapter, approveOutline, approveSetting, approveVolume, confirmImport, correctMemory, createProject, generateChapter, generateOutline, generateSetting, generateVolume, getDraft, getHealth, getModelSettings, getProject, getTask, getTaskHistory, ImportPreview, listMemory, listProjects, listTaskDrafts, listTasks, MemoryRecord, Project, revokeMemory, saveApiKey, saveDraft, saveModelSettings, searchMemory, Task, TaskEventRecord, testModelConnection, transitionTask, uploadImport } from "./api/client";
import { NovelEditor } from "./components/editor/NovelEditor";
import { applyReview, reviewChanges } from "./components/editor/changeset";
import { RunStatus } from "./features/runs/RunStatus";
import { subscribeTaskEvents } from "./api/events";

type View = "overview" | "imports" | "story" | "chapters" | "memory" | "runs" | "settings";

const emptyDraft = "# 故事设定\n\n从核心冲突、主角目标和世界规则开始。";
const SESSION_KEY = "tame-ink.active-session";

function App() {
  const [backendStatus, setBackendStatus] = useState<"checking" | "online" | "offline">("checking");
  const [project, setProject] = useState<Project | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [view, setView] = useState<View>("overview");
  const [draft, setDraft] = useState(emptyDraft);
  const [originalDraft, setOriginalDraft] = useState(emptyDraft);
  const [activeTask, setActiveTask] = useState<Task | null>(null);
  const [draftPath, setDraftPath] = useState("setting.md");
  const [baseRevision, setBaseRevision] = useState<string | null | undefined>(undefined);
  const [versionConflict, setVersionConflict] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showDiff, setShowDiff] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getHealth({ signal: controller.signal }).then(() => setBackendStatus("online"), () => setBackendStatus("offline"));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    listProjects().then(setProjects).catch(() => undefined);
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
      setBaseRevision(restoredDraft.revision);
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
    if (!activeProjectId || !activeTaskId || baseRevision === undefined || draft === originalDraft || versionConflict) return;
    const timeout = window.setTimeout(() => {
      saveDraft(activeProjectId, activeTaskId, draftPath, draft, baseRevision).then(
        (saved) => setBaseRevision(saved.revision),
        (cause) => {
          if (cause instanceof ApiError && cause.code === "CANON_VERSION_CONFLICT") {
            setVersionConflict(true);
            setError("正式版本已在外部发生变化，自动保存已停止。请重新加载或查看本地差异。");
          } else {
            setError(cause instanceof Error ? cause.message : "草稿自动保存失败");
          }
        },
      );
    }, 600);
    return () => window.clearTimeout(timeout);
  }, [activeProjectId, activeTaskId, baseRevision, draft, draftPath, originalDraft, versionConflict]);

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
    { id: "imports", label: "作品导入", icon: Upload },
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
      setProjects((current) => [...current.filter((item) => item.id !== result.project.id), result.project]);
      setActiveTask(result.task);
      setDraftPath("setting.md");
      setDraft(input.setting_draft);
      setOriginalDraft(input.setting_draft);
      const opened = await getDraft(result.project.id, result.task.id, "setting.md");
      setBaseRevision(opened.revision);
      setVersionConflict(false);
      setShowCreate(false);
      setView("story");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建项目失败");
    }
  }

  async function openProject(selected: Project) {
    setError(null);
    setProject(selected);
    try {
      const tasks = await listTasks(selected.id);
      const latest = tasks[0];
      if (!latest) {
        setActiveTask(null);
        setView("overview");
        return;
      }
      const paths = await listTaskDrafts(selected.id, latest.id);
      const path = ["chapter.md", "volume-1.md", "book-outline.md", "setting.md"].find((candidate) => paths.includes(candidate));
      setActiveTask(latest);
      if (!path) {
        setView("runs");
        return;
      }
      const restored = await getDraft(selected.id, latest.id, path);
      setDraftPath(path);
      setDraft(restored.content);
      setOriginalDraft(restored.content);
      setBaseRevision(restored.revision);
      setVersionConflict(false);
      setView(path === "chapter.md" ? "chapters" : "story");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "项目打开失败");
    }
  }

  async function confirmCurrent() {
    if (!project || !activeTask) return;
    setError(null);
    try {
      const task = draftPath === "book-outline.md"
        ? await approveOutline(project.id, activeTask.id)
        : draftPath === "volume-1.md"
          ? await approveVolume(project.id, "1", activeTask.id)
        : await approveSetting(project.id, activeTask.id);
      setActiveTask(task);
      setOriginalDraft(draft);
      const reopened = await getDraft(project.id, task.id, draftPath);
      setBaseRevision(reopened.revision);
      setVersionConflict(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "确认版本失败");
    }
  }

  async function reloadDraft() {
    if (!project || !activeTask) return;
    try {
      const restored = await getDraft(project.id, activeTask.id, draftPath);
      setDraft(restored.content);
      setOriginalDraft(restored.content);
      setBaseRevision(restored.revision);
      setVersionConflict(false);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "草稿重新加载失败");
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
          {projects.length > 0 && <div className="project-switcher"><span className="sidebar-section-label">作品</span>{projects.map((item) => <button type="button" key={item.id} className={project?.id === item.id ? "is-active" : ""} onClick={() => openProject(item)}><span className="project-dot" /><span>{item.title}</span></button>)}</div>}
          <div className="sidebar-project">{project ? <><span className="project-dot" /><div><strong>{project.title}</strong><small>{project.genre ?? "未设置题材"}</small></div></> : <><FolderOpen size={16} /><span>尚未打开项目</span></>}</div>
        </aside>
        <main className="main-content">
          {error && <div className="alert alert-error" role="alert"><X size={16} />{error}<button type="button" onClick={() => setError(null)} aria-label="关闭错误"><X size={14} /></button></div>}
          {versionConflict && <div className="conflict-actions"><button className="button button-secondary" type="button" onClick={() => setShowDiff(true)}><GitCompareArrows size={14} />查看本地差异</button><button className="button button-primary" type="button" onClick={reloadDraft}>重新加载正式版本</button></div>}
          {!project ? <EmptyState projects={projects} onCreate={() => setShowCreate(true)} onOpen={openProject} /> : <>
            <div className="content-header"><div><div className="eyebrow">{navItems.find((item) => item.id === view)?.label}</div><h2>{project.title}</h2></div><div className="header-actions"><span className={`save-state ${isDirty ? "is-dirty" : ""}`}>{isDirty ? "草稿未确认" : "已保存"}</span>{isDirty && view === "story" && <button className="button button-primary" type="button" onClick={confirmCurrent}><Check size={15} />确认版本</button>}</div></div>
            <div className="workspace-grid"><section className="editor-panel">{view === "overview" && <Overview project={project} onOpen={() => setView("chapters")} />}{view === "imports" && <ImportView project={project} onTask={setActiveTask} onError={setError} />}{view === "story" && <StoryView project={project} draft={draft} documentPath={draftPath} setDraft={setDraft} task={activeTask} onApprove={confirmCurrent} onGenerated={(task, path, content, baseline) => { setActiveTask(task); setDraftPath(path); setOriginalDraft(baseline); setDraft(content); }} onOpenChapters={() => setView("chapters")} onError={setError} />}{view === "chapters" && <ChapterView project={project} draft={draft} setDraft={setDraft} task={activeTask} onGenerated={(task, content) => { setActiveTask(task); setDraftPath("chapter.md"); setOriginalDraft(""); setDraft(content); }} onError={setError} />}{view === "memory" && <MemoryView project={project} />}{view === "runs" && <RunsView task={activeTask} project={project} onTask={setActiveTask} onError={setError} />}{view === "settings" && <SettingsView onError={setError} />}</section><aside className="context-panel"><ContextPanel project={project} task={activeTask} dirty={isDirty} onReview={() => setShowDiff(true)} /></aside></div>
          </>}
        </main>
      </div>
      {showCreate && <CreateProjectDialog onClose={() => setShowCreate(false)} onCreate={handleCreate} />}
      {showDiff && <DiffDialog before={originalDraft} after={draft} onClose={() => setShowDiff(false)} onApply={(content) => { setDraft(content); setShowDiff(false); }} />}
    </div>
  );
}

function EmptyState({ projects, onCreate, onOpen }: { projects: Project[]; onCreate: () => void; onOpen: (project: Project) => void }) { return <div className="empty-state"><div className="empty-icon"><BookOpen size={26} /></div><h2>{projects.length ? "打开已有作品" : "从一个新故事开始"}</h2><p>作品的设定、大纲、章节和记忆都保存在本地工作区。</p>{projects.length > 0 && <div className="recent-projects">{projects.map((project) => <button type="button" key={project.id} onClick={() => onOpen(project)}><strong>{project.title}</strong><span>{project.genre}</span></button>)}</div>}<button className="button button-primary" type="button" onClick={onCreate}><Plus size={16} />{projects.length ? "创建新作品" : "创建第一部作品"}</button></div>; }

function Overview({ project, onOpen }: { project: Project; onOpen: () => void }) { return <div className="overview-view"><div className="welcome-band"><div><span className="eyebrow">作品概览</span><h3>{project.title}</h3><p>{project.constraints ?? "尚未填写创作约束"}</p></div><button className="button button-secondary" type="button" onClick={onOpen}>打开章节工作台<ChevronRight size={15} /></button></div><div className="metric-grid"><Metric label="目标字数" value={project.target_words ? `${Math.round(project.target_words / 10000)} 万字` : "未设置"} /><Metric label="当前章节" value="尚未开始" /><Metric label="待处理伏笔" value="0" /></div><div className="next-step"><Sparkles size={18} /><div><strong>下一步：确认故事设定</strong><span>先完善核心冲突和世界规则，再开始生成全书大纲。</span></div><button className="icon-button" type="button" onClick={() => onOpen()} aria-label="继续"><ChevronRight size={17} /></button></div></div>; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="metric"><span>{label}</span><strong>{value}</strong></div>; }

function StoryView({ project, draft, documentPath, setDraft, task, onApprove, onGenerated, onOpenChapters, onError }: { project: Project; draft: string; documentPath: string; setDraft: (value: string) => void; task: Task | null; onApprove: () => void; onGenerated: (task: Task, path: string, content: string, baseline: string) => void; onOpenChapters: () => void; onError: (message: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [instruction, setInstruction] = useState("围绕核心冲突生成可长期连载、事实边界明确的候选内容。");
  const title = documentPath === "setting.md" ? "核心设定" : documentPath === "book-outline.md" ? "全书大纲" : "第一卷规划";

  async function generateCurrent() {
    if (!task) return;
    setBusy(true);
    try {
      if (documentPath === "setting.md" && task.status === "awaiting_approval") {
        const result = await generateSetting(project.id, task.id, instruction);
        onGenerated(result.task, "setting.md", result.content, draft);
      } else if (documentPath === "setting.md") {
        const result = await generateOutline(project.id, instruction);
        onGenerated(result.task, "book-outline.md", result.content, "");
      } else if (documentPath === "book-outline.md") {
        const result = await generateVolume(project.id, "1", instruction);
        onGenerated(result.task, "volume-1.md", result.content, "");
      } else {
        onOpenChapters();
      }
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "Agent 生成失败");
    } finally {
      setBusy(false);
    }
  }

  const nextLabel = task?.status === "awaiting_approval"
    ? "AI 重新生成"
    : documentPath === "setting.md"
      ? "AI 生成全书大纲"
      : documentPath === "book-outline.md"
        ? "AI 规划第一卷"
        : "进入章节工作台";
  return <div className="editor-view"><div className="section-heading"><div><span className="eyebrow">故事设计</span><h3>{title}</h3></div><div className="header-actions">{task?.status === "awaiting_approval" && <button className="button button-secondary" type="button" onClick={onApprove}><Check size={15} />确认当前草稿</button>}<button className="button button-primary" type="button" onClick={generateCurrent} disabled={busy || !task}>{busy ? <LoaderCircle className="spin" size={15} /> : <Sparkles size={15} />}{nextLabel}</button></div></div><label className="field-label" htmlFor="story-instruction">Agent 指令</label><textarea id="story-instruction" className="plan-input" value={instruction} onChange={(event) => setInstruction(event.target.value)} /><NovelEditor markdown={draft} onChange={setDraft} /><div className="editor-footer"><span>Markdown · 自动保存到草稿区</span>{task && <RunStatus status={task.status} connection="connected" />}</div></div>;
}

function ChapterView({ project, draft, setDraft, task, onGenerated, onError }: { project: Project; draft: string; setDraft: (value: string) => void; task: Task | null; onGenerated: (task: Task, content: string) => void; onError: (message: string) => void }) {
  const [instruction, setInstruction] = useState("承接上一章状态推进主线，并在结尾留下明确钩子。");
  const [chapterId, setChapterId] = useState("1");
  const [busy, setBusy] = useState(false);
  async function start() {
    setBusy(true);
    try {
      const result = await generateChapter(project.id, chapterId, instruction);
      onGenerated(result.task, result.content);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "章节 Agent 生成失败");
    } finally {
      setBusy(false);
    }
  }
  async function approve() {
    if (!task) return;
    setBusy(true);
    try {
      onGenerated(await approveChapter(project.id, chapterId, task.id), draft);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "章节确认失败");
    } finally {
      setBusy(false);
    }
  }
  return <div className="editor-view"><div className="section-heading"><div><span className="eyebrow">逐章创作</span><label className="chapter-number-label" htmlFor="chapter-id">第</label><input id="chapter-id" className="chapter-number" value={chapterId} onChange={(event) => setChapterId(event.target.value.replace(/\D/g, ""))} inputMode="numeric" aria-label="章节编号" /><span className="chapter-number-label">章</span></div><div className="header-actions">{task?.status === "awaiting_approval" && <button className="button button-secondary" type="button" onClick={approve} disabled={busy}><Check size={15} />确认章节</button>}<button className="button button-primary" type="button" onClick={start} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <Sparkles size={15} />}Agent 生成章节</button></div></div><label className="field-label" htmlFor="chapter-plan">Agent 指令</label><textarea id="chapter-plan" className="plan-input" value={instruction} onChange={(event) => setInstruction(event.target.value)} /><NovelEditor markdown={draft} onChange={setDraft} /><div className="editor-footer"><span>当前任务：{task ? task.status : "尚未启动"}</span><span>项目：{project.id}</span></div></div>;
}

function ImportView({ project, onTask, onError }: { project: Project; onTask: (task: Task) => void; onError: (message: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [sourceEnd, setSourceEnd] = useState<Record<string, number> | null>(null);
  const [busy, setBusy] = useState(false);
  const importId = file ? file.name.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "book-import" : "book-import";
  async function upload() {
    if (!file) return;
    setBusy(true);
    try {
      const result = await uploadImport(project.id, importId, file);
      setPreview(result);
      setSourceEnd(result.chapters.at(-1)?.end ?? null);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "作品导入失败");
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    if (!preview || !sourceEnd) return;
    setBusy(true);
    try {
      const chapters = preview.chapters.map((chapter, index) => ({
        ...chapter,
        end: preview.chapters[index + 1]?.start ?? sourceEnd,
      }));
      const result = await confirmImport(project.id, importId, { ...preview, chapters });
      onTask(result.task);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "章节边界确认失败");
    } finally {
      setBusy(false);
    }
  }
  function edit(index: number, field: "number" | "title", value: string) {
    if (!preview) return;
    setPreview({ ...preview, chapters: preview.chapters.map((chapter, current) => current === index ? { ...chapter, [field]: field === "number" ? Number(value) : value } : chapter) });
  }
  return <div className="placeholder-view"><Upload size={24} /><h3>作品导入</h3><p>选择 TXT 或 Markdown，校正章号和标题，移除误识别边界，再确认进入分析流程。</p><label className="file-drop"><input type="file" accept=".txt,.md,text/plain,text/markdown" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setPreview(null); }} /><Upload size={18} /><span>{file ? file.name : "选择 TXT 或 Markdown 文件"}</span></label><button className="button button-primary" type="button" disabled={!file || busy} onClick={upload}>{busy ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />}解析章节</button>{preview && <div className="import-preview"><div><strong>{preview.chapters.length} 章</strong><span>{preview.encoding} · {Math.ceil(preview.size / 1024)} KB</span></div><div className="boundary-list">{preview.chapters.map((chapter, index) => <div className="boundary-row" key={`${chapter.start.character}-${index}`}><input aria-label={`第 ${index + 1} 条章号`} type="number" min="1" value={chapter.number} onChange={(event) => edit(index, "number", event.target.value)} /><input aria-label={`第 ${index + 1} 条标题`} value={chapter.title} onChange={(event) => edit(index, "title", event.target.value)} /><span>第 {chapter.start.line} 行</span><button className="icon-button" type="button" aria-label={`移除 ${chapter.title}`} onClick={() => setPreview({ ...preview, chapters: preview.chapters.filter((_, current) => current !== index) })}><Trash2 size={15} /></button></div>)}</div><button className="button button-secondary" type="button" onClick={confirm} disabled={busy || preview.chapters.length === 0}><Check size={15} />确认章节边界</button></div>}</div>;
}

function MemoryView({ project }: { project: Project }) {
  const [records, setRecords] = useState<MemoryRecord[]>([]);
  const [kind, setKind] = useState<MemoryRecord["kind"]>("fact");
  const [editing, setEditing] = useState<MemoryRecord | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Array<{ path: string; location: string; quote: string; sha256: string }>>([]);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => { listMemory(project.id).then(setRecords).catch((cause) => setMessage(cause instanceof Error ? cause.message : "记忆读取失败")); }, [project.id]);
  async function search() {
    if (!query.trim()) return;
    try { setHits(await searchMemory(project.id, query)); setMessage(null); }
    catch (cause) { setMessage(cause instanceof Error ? cause.message : "记忆搜索失败"); }
  }
  async function save() {
    if (!editing) return;
    try {
      const updated = await correctMemory(project.id, editing);
      setRecords((current) => current.map((item) => item.id === updated.id ? updated : item));
      setEditing(null);
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : "记忆修正失败"); }
  }
  async function revoke(record: MemoryRecord) {
    try {
      const updated = await revokeMemory(project.id, record);
      setRecords((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : "记忆撤销失败"); }
  }
  const labels: Record<MemoryRecord["kind"], string> = { fact: "事实", event: "事件", relationship: "关系", foreshadowing: "伏笔" };
  return <div className="placeholder-view"><Library size={24} /><h3>记忆中心</h3><p>分类浏览、修正或撤销派生记忆；每条记录保留正式章节来源。</p><div className="memory-tabs">{Object.entries(labels).map(([value, label]) => <button type="button" className={kind === value ? "is-active" : ""} key={value} onClick={() => setKind(value as MemoryRecord["kind"])}>{label}<span>{records.filter((record) => record.kind === value).length}</span></button>)}</div>{message && <div className="memory-empty">{message}</div>}<div className="memory-records">{records.filter((record) => record.kind === kind).map((record) => <article className="memory-record" key={record.id}><div><strong>{record.id}</strong><span>{record.status}</span></div><p>{record.quote}</p><small>{record.source} · {record.location}</small><div><button className="button button-secondary" type="button" onClick={() => setEditing(record)}>修正</button>{record.status === "active" && <button className="button button-secondary" type="button" onClick={() => revoke(record)}>撤销</button>}</div></article>)}</div>{records.filter((record) => record.kind === kind).length === 0 && <div className="memory-empty">当前分类暂无记录。</div>}<div className="memory-search"><div className="search-row"><input aria-label="搜索记忆" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void search(); }} placeholder="搜索正文和记忆来源" /><button className="button button-primary" type="button" onClick={search}><Search size={15} />搜索</button></div>{hits.map((hit) => <article className="memory-hit" key={`${hit.path}:${hit.location}`}><strong>{hit.path}</strong><span>{hit.location}</span><p>{hit.quote}</p></article>)}</div>{editing && <div className="memory-edit"><h4>修正 {editing.id}</h4><label>来源<input value={editing.source} onChange={(event) => setEditing({ ...editing, source: event.target.value })} /></label><label>位置<input value={editing.location} onChange={(event) => setEditing({ ...editing, location: event.target.value })} /></label><label>原文引用<textarea value={editing.quote} onChange={(event) => setEditing({ ...editing, quote: event.target.value })} /></label><div><button className="button button-secondary" type="button" onClick={() => setEditing(null)}>取消</button><button className="button button-primary" type="button" onClick={save}>保存修正</button></div></div>}</div>;
}
function RunsView({ task, project, onTask, onError }: { task: Task | null; project: Project; onTask: (task: Task) => void; onError: (message: string) => void }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [history, setHistory] = useState<TaskEventRecord[]>([]);
  useEffect(() => { listTasks(project.id).then(setTasks).catch((cause) => onError(cause instanceof Error ? cause.message : "任务记录读取失败")); }, [project.id, task, onError]);
  async function act(item: Task, action: "start" | "cancel") {
    try {
      const updated = await transitionTask(project.id, item.id, action);
      setTasks((current) => current.map((candidate) => candidate.id === updated.id ? updated : candidate));
      onTask(updated);
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "任务操作失败");
    }
  }
  async function inspect(item: Task) {
    try {
      setHistory(await getTaskHistory(project.id, item.id));
      setSelectedTask(item.id);
    } catch (cause) { onError(cause instanceof Error ? cause.message : "任务事件读取失败"); }
  }
  return <div className="runs-view"><div className="section-heading"><div><span className="eyebrow">运行记录</span><h3>任务活动</h3></div></div>{tasks.length ? <div className="run-list">{tasks.map((item) => <div className="run-entry" key={item.id}><div className="run-card"><div><strong>{item.kind === "write" ? "创作任务" : "读取任务"}</strong><span>{item.id}</span><small>{new Date(item.updated_at).toLocaleString("zh-CN")}</small></div><div className="run-actions"><RunStatus status={item.status} connection="connected" /><button className="button button-secondary" type="button" onClick={() => inspect(item)}>事件</button>{item.status === "interrupted" && <button className="button button-secondary" type="button" onClick={() => act(item, "start")}>恢复</button>}{["pending", "running", "awaiting_approval", "interrupted"].includes(item.status) && <button className="button button-secondary" type="button" onClick={() => act(item, "cancel")}>取消</button>}</div></div>{selectedTask === item.id && <ol className="event-history">{history.map((event) => <li key={event.sequence}><span>{event.sequence}</span><strong>{event.type}</strong><time>{new Date(event.timestamp).toLocaleTimeString("zh-CN")}</time></li>)}</ol>}</div>)}</div> : <div className="memory-empty">{project.title} 还没有运行记录。</div>}</div>;
}
function SettingsView({ onError }: { onError: (message: string) => void }) { const [settings, setSettings] = useState({ base_url: "", model: "", timeout: 30 }); const [apiKey, setApiKey] = useState(""); const [status, setStatus] = useState("未验证"); useEffect(() => { getModelSettings().then((value) => setSettings({ base_url: value.base_url, model: value.model, timeout: value.timeout })).catch(() => undefined); }, []); async function save() { try { await saveModelSettings(settings); if (apiKey) { await saveApiKey(apiKey); setApiKey(""); } setStatus("已保存"); } catch (cause) { onError(cause instanceof Error ? cause.message : "模型设置保存失败"); } } async function connect() { setStatus("正在验证"); try { await testModelConnection(); setStatus("连接正常"); } catch (cause) { setStatus("连接失败"); onError(cause instanceof Error ? cause.message : "模型连接失败"); } } return <div className="placeholder-view settings-form"><Settings size={24} /><h3>模型设置</h3><p>只配置一个 OpenAI-compatible 接口，API Key 由系统密钥环保存且不会回显。</p><label>Base URL<input value={settings.base_url} onChange={(event) => setSettings({ ...settings, base_url: event.target.value })} placeholder="https://api.example.com/v1" /></label><label>模型名<input value={settings.model} onChange={(event) => setSettings({ ...settings, model: event.target.value })} /></label><label>超时（秒）<input type="number" min="1" value={settings.timeout} onChange={(event) => setSettings({ ...settings, timeout: Number(event.target.value) })} /></label><label>API Key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="new-password" placeholder="未填写则保留现有密钥" /></label><div className="settings-actions"><button className="button button-secondary" type="button" onClick={save}>保存设置</button><button className="button button-primary" type="button" onClick={connect}>测试连接</button><span>{status}</span></div></div>; }
function ContextPanel({ project, task, dirty, onReview }: { project: Project; task: Task | null; dirty: boolean; onReview: () => void }) { return <><div className="panel-heading"><div><span className="eyebrow">Agent 面板</span><h3>上下文</h3></div><Search size={16} /></div><div className="context-block"><span className="context-label">当前项目</span><strong>{project.title}</strong><span className="muted">{project.genre ?? "未设置题材"}</span></div><div className="context-block"><span className="context-label">任务状态</span>{task ? <RunStatus status={task.status} connection="connected" /> : <span className="muted">暂无活动任务</span>}</div><div className="context-block"><span className="context-label">版本门禁</span><div className="gate-row"><span className={`gate-dot ${dirty ? "gate-dot--warn" : ""}`} />{dirty ? "等待用户确认" : "正式内容未修改"}</div>{dirty && <button className="button button-secondary" type="button" onClick={onReview}><GitCompareArrows size={14} />查看差异</button>}</div><div className="source-list"><span className="context-label">已加载来源</span><span>project.yaml</span><span>canon/world/setting.md</span><span>memory/（确认后生成）</span></div></>; }

function DiffDialog({ before, after, onClose, onApply }: { before: string; after: string; onClose: () => void; onApply: (content: string) => void }) {
  const changes = reviewChanges(before, after);
  const [accepted, setAccepted] = useState(() => new Set(changes.map((change) => change.id)));
  function toggle(id: string) {
    setAccepted((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }
  return <div className="dialog-backdrop"><div className="dialog diff-dialog" role="dialog" aria-modal="true" aria-label="修改差异"><div className="dialog-heading"><div><span className="eyebrow">AI 修改审核</span><h2>逐项审核 {changes.length} 处修改</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button></div><div className="diff-review-list">{changes.map((change) => <label className="diff-review-item" key={change.id}><input type="checkbox" checked={accepted.has(change.id)} onChange={() => toggle(change.id)} /><div><span>{accepted.has(change.id) ? "接受" : "拒绝"}</span><pre className="diff-removed">{change.before || "（新增）"}</pre><pre className="diff-added">{change.after || "（删除）"}</pre></div></label>)}</div><div className="dialog-actions"><button className="button button-secondary" type="button" onClick={() => setAccepted(new Set())}>拒绝全部</button><button className="button button-primary" type="button" onClick={() => onApply(applyReview(before, after, accepted))}><Check size={15} />应用审核结果</button></div></div></div>;
}

function CreateProjectDialog({ onClose, onCreate }: { onClose: () => void; onCreate: (input: { project_id: string; title: string; genre: string; target_words: number; constraints: string; setting_draft: string }) => void }) { const [form, setForm] = useState({ project_id: "my-novel", title: "", genre: "", target_words: 2000000, constraints: "", setting_draft: emptyDraft }); function submit(event: FormEvent) { event.preventDefault(); onCreate(form); } return <div className="dialog-backdrop"><form className="dialog" onSubmit={submit}><div className="dialog-heading"><div><span className="eyebrow">新建作品</span><h2>建立你的故事</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button></div><label className="field-label" htmlFor="project-id">项目 ID</label><input id="project-id" value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value })} required pattern="[a-z0-9]+(?:-[a-z0-9]+)*" /><div className="form-grid"><div><label className="field-label" htmlFor="project-title">书名</label><input id="project-title" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required /></div><div><label className="field-label" htmlFor="project-genre">题材</label><input id="project-genre" value={form.genre} onChange={(event) => setForm({ ...form, genre: event.target.value })} placeholder="例如：东方幻想" required /></div></div><label className="field-label" htmlFor="target-words">目标字数</label><input id="target-words" type="number" min="1" value={form.target_words} onChange={(event) => setForm({ ...form, target_words: Number(event.target.value) })} required /><label className="field-label" htmlFor="constraints">创作约束</label><textarea id="constraints" value={form.constraints} onChange={(event) => setForm({ ...form, constraints: event.target.value })} placeholder="叙事视角、风格、禁用内容等" required /><div className="dialog-actions"><button className="button button-secondary" type="button" onClick={onClose}>取消</button><button className="button button-primary" type="submit"><Plus size={15} />创建并进入工作台</button></div></form></div>; }

export default App;
