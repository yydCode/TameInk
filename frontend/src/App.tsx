import { FormEvent, useEffect, useState } from "react";
import { BookOpen, Check, ChevronRight, FilePlus2, FolderOpen, GitCompareArrows, Library, LoaderCircle, Plus, Search, Settings, Sparkles, Upload, X } from "lucide-react";
import { approveChapter, approveOutline, approveSetting, approveVolume, confirmImport, createOutline, createProject, createVolume, getDraft, getHealth, getModelSettings, getProject, getTask, ImportPreview, Project, saveApiKey, saveDraft, saveModelSettings, searchMemory, startChapter, Task, testModelConnection, uploadImport } from "./api/client";
import { NovelEditor } from "./components/editor/NovelEditor";
import { markdownDiff } from "./components/editor/changeset";
import { RunStatus } from "./features/runs/RunStatus";
import { subscribeTaskEvents } from "./api/events";

type View = "overview" | "imports" | "story" | "chapters" | "memory" | "runs" | "settings";

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
  const [showDiff, setShowDiff] = useState(false);

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
        : draftPath === "volume-1.md"
          ? await approveVolume(project.id, "1", activeTask.id)
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
            <div className="workspace-grid"><section className="editor-panel">{view === "overview" && <Overview project={project} onOpen={() => setView("chapters")} />}{view === "imports" && <ImportView project={project} onTask={setActiveTask} onError={setError} />}{view === "story" && <StoryView project={project} draft={draft} documentPath={draftPath} setDraft={setDraft} task={activeTask} onApprove={confirmCurrent} onTask={(task, path) => { setActiveTask(task); setDraftPath(path); }} onOpenChapters={() => setView("chapters")} onError={setError} />}{view === "chapters" && <ChapterView project={project} draft={draft} setDraft={setDraft} task={activeTask} onTask={(task) => { setActiveTask(task); setDraftPath("chapter.md"); }} onError={setError} />}{view === "memory" && <MemoryView project={project} />}{view === "runs" && <RunsView task={activeTask} project={project} />}{view === "settings" && <SettingsView onError={setError} />}</section><aside className="context-panel"><ContextPanel project={project} task={activeTask} dirty={isDirty} onReview={() => setShowDiff(true)} /></aside></div>
          </>}
        </main>
      </div>
      {showCreate && <CreateProjectDialog onClose={() => setShowCreate(false)} onCreate={handleCreate} />}
      {showDiff && <DiffDialog before={originalDraft} after={draft} onClose={() => setShowDiff(false)} onReject={() => { setDraft(originalDraft); setShowDiff(false); }} />}
    </div>
  );
}

function EmptyState({ onCreate }: { onCreate: () => void }) { return <div className="empty-state"><div className="empty-icon"><BookOpen size={26} /></div><h2>从一个新故事开始</h2><p>创建本地作品后，设定、大纲、章节和记忆都会保存在你的工作区。</p><button className="button button-primary" type="button" onClick={onCreate}><Plus size={16} />创建第一部作品</button></div>; }

function Overview({ project, onOpen }: { project: Project; onOpen: () => void }) { return <div className="overview-view"><div className="welcome-band"><div><span className="eyebrow">作品概览</span><h3>{project.title}</h3><p>{project.constraints ?? "尚未填写创作约束"}</p></div><button className="button button-secondary" type="button" onClick={onOpen}>打开章节工作台<ChevronRight size={15} /></button></div><div className="metric-grid"><Metric label="目标字数" value={project.target_words ? `${Math.round(project.target_words / 10000)} 万字` : "未设置"} /><Metric label="当前章节" value="尚未开始" /><Metric label="待处理伏笔" value="0" /></div><div className="next-step"><Sparkles size={18} /><div><strong>下一步：确认故事设定</strong><span>先完善核心冲突和世界规则，再开始生成全书大纲。</span></div><button className="icon-button" type="button" onClick={() => onOpen()} aria-label="继续"><ChevronRight size={17} /></button></div></div>; }
function Metric({ label, value }: { label: string; value: string }) { return <div className="metric"><span>{label}</span><strong>{value}</strong></div>; }

function StoryView({ project, draft, documentPath, setDraft, task, onApprove, onTask, onOpenChapters, onError }: { project: Project; draft: string; documentPath: string; setDraft: (value: string) => void; task: Task | null; onApprove: () => void; onTask: (task: Task, path: string) => void; onOpenChapters: () => void; onError: (message: string) => void }) { const [busy, setBusy] = useState(false); const title = documentPath === "setting.md" ? "核心设定" : documentPath === "outline-book.md" ? "全书大纲" : "第一卷规划"; async function next() { setBusy(true); try { if (documentPath === "setting.md") onTask(await createOutline(project.id, draft), "outline-book.md"); else if (documentPath === "outline-book.md") onTask(await createVolume(project.id, "1", draft), "volume-1.md"); else onOpenChapters(); } catch (cause) { onError(cause instanceof Error ? cause.message : "规划任务启动失败"); } finally { setBusy(false); } } const nextLabel = documentPath === "setting.md" ? "生成全书大纲" : documentPath === "outline-book.md" ? "规划第一卷" : "进入章节工作台"; return <div className="editor-view"><div className="section-heading"><div><span className="eyebrow">故事设计</span><h3>{title}</h3></div><div className="header-actions">{task?.status === "awaiting_approval" && <button className="button button-secondary" type="button" onClick={onApprove}><Check size={15} />确认当前草稿</button>}{task?.status === "completed" && <button className="button button-primary" type="button" onClick={next} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <Sparkles size={15} />}{nextLabel}</button>}</div></div><NovelEditor markdown={draft} onChange={setDraft} /><div className="editor-footer"><span>Markdown · 自动保存到草稿区</span>{task && <RunStatus status={task.status} connection="connected" />}</div></div>; }

function ChapterView({ project, draft, setDraft, task, onTask, onError }: { project: Project; draft: string; setDraft: (value: string) => void; task: Task | null; onTask: (task: Task) => void; onError: (message: string) => void }) { const [plan, setPlan] = useState("开场建立主角处境，并让核心冲突在本章结尾露出一角。"); const [chapterId, setChapterId] = useState("1"); const [busy, setBusy] = useState(false); async function start() { setBusy(true); try { onTask(await startChapter(project.id, chapterId, { plan, draft, issues: [] })); } catch (cause) { onError(cause instanceof Error ? cause.message : "章节任务启动失败"); } finally { setBusy(false); } } async function approve() { if (!task) return; setBusy(true); try { onTask(await approveChapter(project.id, chapterId, task.id)); } catch (cause) { onError(cause instanceof Error ? cause.message : "章节确认失败"); } finally { setBusy(false); } } return <div className="editor-view"><div className="section-heading"><div><span className="eyebrow">逐章创作</span><label className="chapter-number-label" htmlFor="chapter-id">第</label><input id="chapter-id" className="chapter-number" value={chapterId} onChange={(event) => setChapterId(event.target.value.replace(/\D/g, ""))} inputMode="numeric" aria-label="章节编号" /><span className="chapter-number-label">章</span></div><div className="header-actions">{task?.status === "awaiting_approval" && <button className="button button-secondary" type="button" onClick={approve} disabled={busy}><Check size={15} />确认章节</button>}<button className="button button-primary" type="button" onClick={start} disabled={busy}>{busy ? <LoaderCircle className="spin" size={15} /> : <Sparkles size={15} />}生成章节草稿</button></div></div><label className="field-label" htmlFor="chapter-plan">章节计划</label><textarea id="chapter-plan" className="plan-input" value={plan} onChange={(event) => setPlan(event.target.value)} /><NovelEditor markdown={draft} onChange={setDraft} /><div className="editor-footer"><span>当前任务：{task ? task.status : "尚未启动"}</span><span>项目：{project.id}</span></div></div>; }

function ImportView({ project, onTask, onError }: { project: Project; onTask: (task: Task) => void; onError: (message: string) => void }) { const [file, setFile] = useState<File | null>(null); const [preview, setPreview] = useState<ImportPreview | null>(null); const [busy, setBusy] = useState(false); const importId = file ? file.name.replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "book-import" : "book-import"; async function upload() { if (!file) return; setBusy(true); try { setPreview(await uploadImport(project.id, importId, file)); } catch (cause) { onError(cause instanceof Error ? cause.message : "作品导入失败"); } finally { setBusy(false); } } async function confirm() { if (!preview) return; setBusy(true); try { const result = await confirmImport(project.id, importId, preview); onTask(result.task); } catch (cause) { onError(cause instanceof Error ? cause.message : "章节边界确认失败"); } finally { setBusy(false); } } return <div className="placeholder-view"><Upload size={24} /><h3>作品导入</h3><p>选择 TXT 或 Markdown，先检查确定性章节边界，再确认进入分析流程。</p><label className="file-drop"><input type="file" accept=".txt,.md,text/plain,text/markdown" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setPreview(null); }} /><Upload size={18} /><span>{file ? file.name : "选择 TXT 或 Markdown 文件"}</span></label><button className="button button-primary" type="button" disabled={!file || busy} onClick={upload}>{busy ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />}解析章节</button>{preview && <div className="import-preview"><div><strong>{preview.chapters.length} 章</strong><span>{preview.encoding} · {Math.ceil(preview.size / 1024)} KB</span></div><ol>{preview.chapters.slice(0, 8).map((chapter) => <li key={chapter.number}><span>第 {chapter.number} 章</span>{chapter.title}</li>)}</ol>{preview.chapters.length > 8 && <p>另有 {preview.chapters.length - 8} 章</p>}<button className="button button-secondary" type="button" onClick={confirm} disabled={busy}><Check size={15} />确认章节边界</button></div>}</div>; }

function MemoryView({ project }: { project: Project }) { const [query, setQuery] = useState(""); const [hits, setHits] = useState<Array<{ path: string; location: string; snippet: string }>>([]); const [searched, setSearched] = useState(false); async function search() { if (!query.trim()) return; setHits(await searchMemory(project.id, query)); setSearched(true); } return <div className="placeholder-view"><Library size={24} /><h3>记忆中心</h3><p>检索已确认正文、人物事实、事件、关系和伏笔，结果始终携带来源。</p><div className="search-row"><input aria-label="搜索记忆" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void search(); }} placeholder="人物、地点、能力或线索" /><button className="button button-primary" type="button" onClick={search}><Search size={15} />搜索</button></div>{hits.map((hit) => <article className="memory-hit" key={`${hit.path}:${hit.location}`}><strong>{hit.path}</strong><span>{hit.location}</span><p>{hit.snippet}</p></article>)}{searched && hits.length === 0 && <div className="memory-empty">没有找到相关的已确认记忆。</div>}</div>; }
function RunsView({ task, project }: { task: Task | null; project: Project }) { return <div className="runs-view"><div className="section-heading"><div><span className="eyebrow">运行记录</span><h3>任务活动</h3></div></div>{task ? <div className="run-card"><div><strong>{task.kind === "write" ? "创作任务" : "读取任务"}</strong><span>{task.id}</span></div><RunStatus status={task.status} connection="connected" /></div> : <div className="memory-empty">{project.title} 还没有运行记录。</div>}</div>; }
function SettingsView({ onError }: { onError: (message: string) => void }) { const [settings, setSettings] = useState({ base_url: "", model: "", timeout: 30 }); const [apiKey, setApiKey] = useState(""); const [status, setStatus] = useState("未验证"); useEffect(() => { getModelSettings().then((value) => setSettings({ base_url: value.base_url, model: value.model, timeout: value.timeout })).catch(() => undefined); }, []); async function save() { try { await saveModelSettings(settings); if (apiKey) { await saveApiKey(apiKey); setApiKey(""); } setStatus("已保存"); } catch (cause) { onError(cause instanceof Error ? cause.message : "模型设置保存失败"); } } async function connect() { setStatus("正在验证"); try { await testModelConnection(); setStatus("连接正常"); } catch (cause) { setStatus("连接失败"); onError(cause instanceof Error ? cause.message : "模型连接失败"); } } return <div className="placeholder-view settings-form"><Settings size={24} /><h3>模型设置</h3><p>只配置一个 OpenAI-compatible 接口，API Key 由系统密钥环保存且不会回显。</p><label>Base URL<input value={settings.base_url} onChange={(event) => setSettings({ ...settings, base_url: event.target.value })} placeholder="https://api.example.com/v1" /></label><label>模型名<input value={settings.model} onChange={(event) => setSettings({ ...settings, model: event.target.value })} /></label><label>超时（秒）<input type="number" min="1" value={settings.timeout} onChange={(event) => setSettings({ ...settings, timeout: Number(event.target.value) })} /></label><label>API Key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="new-password" placeholder="未填写则保留现有密钥" /></label><div className="settings-actions"><button className="button button-secondary" type="button" onClick={save}>保存设置</button><button className="button button-primary" type="button" onClick={connect}>测试连接</button><span>{status}</span></div></div>; }
function ContextPanel({ project, task, dirty, onReview }: { project: Project; task: Task | null; dirty: boolean; onReview: () => void }) { return <><div className="panel-heading"><div><span className="eyebrow">Agent 面板</span><h3>上下文</h3></div><Search size={16} /></div><div className="context-block"><span className="context-label">当前项目</span><strong>{project.title}</strong><span className="muted">{project.genre ?? "未设置题材"}</span></div><div className="context-block"><span className="context-label">任务状态</span>{task ? <RunStatus status={task.status} connection="connected" /> : <span className="muted">暂无活动任务</span>}</div><div className="context-block"><span className="context-label">版本门禁</span><div className="gate-row"><span className={`gate-dot ${dirty ? "gate-dot--warn" : ""}`} />{dirty ? "等待用户确认" : "正式内容未修改"}</div>{dirty && <button className="button button-secondary" type="button" onClick={onReview}><GitCompareArrows size={14} />查看差异</button>}</div><div className="source-list"><span className="context-label">已加载来源</span><span>project.yaml</span><span>canon/world/setting.md</span><span>memory/（确认后生成）</span></div></>; }

function DiffDialog({ before, after, onClose, onReject }: { before: string; after: string; onClose: () => void; onReject: () => void }) { const parts = markdownDiff(before, after); return <div className="dialog-backdrop"><div className="dialog diff-dialog" role="dialog" aria-modal="true" aria-label="修改差异"><div className="dialog-heading"><div><span className="eyebrow">AI 修改审核</span><h2>修改差异</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button></div><div className="diff-content">{parts.map((part, index) => <pre key={`${part.kind}-${index}`} className={`diff-${part.kind}`}>{part.text}</pre>)}</div><div className="dialog-actions"><button className="button button-secondary" type="button" onClick={onReject}>拒绝全部</button><button className="button button-primary" type="button" onClick={onClose}><Check size={15} />保留到工作副本</button></div></div></div>; }

function CreateProjectDialog({ onClose, onCreate }: { onClose: () => void; onCreate: (input: { project_id: string; title: string; genre: string; target_words: number; constraints: string; setting_draft: string }) => void }) { const [form, setForm] = useState({ project_id: "my-novel", title: "", genre: "", target_words: 2000000, constraints: "", setting_draft: emptyDraft }); function submit(event: FormEvent) { event.preventDefault(); onCreate(form); } return <div className="dialog-backdrop"><form className="dialog" onSubmit={submit}><div className="dialog-heading"><div><span className="eyebrow">新建作品</span><h2>建立你的故事</h2></div><button className="icon-button" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button></div><label className="field-label" htmlFor="project-id">项目 ID</label><input id="project-id" value={form.project_id} onChange={(event) => setForm({ ...form, project_id: event.target.value })} required pattern="[a-z0-9]+(?:-[a-z0-9]+)*" /><div className="form-grid"><div><label className="field-label" htmlFor="project-title">书名</label><input id="project-title" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required /></div><div><label className="field-label" htmlFor="project-genre">题材</label><input id="project-genre" value={form.genre} onChange={(event) => setForm({ ...form, genre: event.target.value })} placeholder="例如：东方幻想" required /></div></div><label className="field-label" htmlFor="target-words">目标字数</label><input id="target-words" type="number" min="1" value={form.target_words} onChange={(event) => setForm({ ...form, target_words: Number(event.target.value) })} required /><label className="field-label" htmlFor="constraints">创作约束</label><textarea id="constraints" value={form.constraints} onChange={(event) => setForm({ ...form, constraints: event.target.value })} placeholder="叙事视角、风格、禁用内容等" required /><div className="dialog-actions"><button className="button button-secondary" type="button" onClick={onClose}>取消</button><button className="button button-primary" type="submit"><Plus size={15} />创建并进入工作台</button></div></form></div>; }

export default App;
