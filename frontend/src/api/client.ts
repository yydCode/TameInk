export interface HealthResponse {
  status: "ok";
  service: "tame-ink-api";
  version: string;
}

export interface Project {
  id: string;
  title: string;
  language: string;
  genre: string | null;
  target_words: number | null;
  constraints: string | null;
}

export interface WorkflowStatus {
  setting_confirmed: boolean;
  outline_confirmed: boolean;
  volume_one_confirmed: boolean;
  commercial_confirmed: boolean;
}

export type TaskStatus =
  | "pending"
  | "running"
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface Task {
  id: string;
  project_id: string;
  kind: "read" | "write";
  purpose: "manual" | "setting" | "commercial" | "book_outline" | "volume_outline" | "chapter" | "import" | "commercial_audit" | "memory_curation" | "export";
  status: TaskStatus;
  subject_id: string | null;
  volume_id: string | null;
  chapter_id: string | null;
  parent_task_id: string | null;
  retry_of_task_id: string | null;
  cancel_requested_at: string | null;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectDocument {
  path: string;
  kind: "setting" | "outline" | "commercial" | "volume" | "chapter";
  title: string;
  word_count: number;
  updated_at: string;
}

export interface ChapterNode extends ProjectDocument {
  kind: "chapter";
  id: string;
  volume_id: string | null;
}

export interface VolumeNode extends ProjectDocument {
  kind: "volume";
  id: string;
  chapters: ChapterNode[];
}

export interface ProjectSnapshot {
  project: Project;
  documents: ProjectDocument[];
  volumes: VolumeNode[];
  unassigned_chapters: ChapterNode[];
  stats: {
    total_words: number;
    chapter_count: number;
    volume_count: number;
    active_foreshadow_count: number;
  };
}

export interface AgentRunTrace {
  agent: string;
  skill: string;
  skill_sha256: string;
  stage: string;
  source_paths: string[];
  queries: string[];
  total_characters: number;
  duration_ms: number;
  status: "success" | "failed";
  error_code: string | null;
}

export interface TaskRunManifest {
  agent_runs: AgentRunTrace[];
}

export interface MemoryRecord {
  id: string;
  kind: "fact" | "event" | "relationship" | "foreshadowing";
  status: "active" | "resolved" | "superseded";
  source: string;
  location: string;
  quote: string;
  content?: string | null;
}

export interface MemoryCandidate {
  stable_id: string;
  kind: MemoryRecord["kind"];
  operation: "create" | "update" | "close";
  content: string;
  citation: { source: "draft"; location: string; quote: string };
}

export interface CommercialTargets {
  click_through_rate: number | null;
  chapter_one_completion_rate: number | null;
  chapter_three_retention_rate: number | null;
  follow_rate: number | null;
  revenue_per_thousand_opens_yuan: number | null;
}

export interface CommercialProfile {
  schema_version: 1;
  platform: "fanqie" | "qidian" | "jinjiang" | "custom";
  custom_platform: string | null;
  monetization: "free_ad" | "paid_subscription" | "custom";
  target_reader: string;
  core_fantasy: string;
  differentiator: string;
  emotional_payoffs: string[];
  opening_promise: string;
  first_thirty_chapter_promise: string;
  update_cadence: string;
  title_candidates: string[];
  synopsis: string;
  comparable_titles: string[];
  minimum_commercial_score: number;
  targets: CommercialTargets;
}

export type CommercialDimension =
  | "opening_urgency"
  | "reader_promise"
  | "emotional_payoff"
  | "conflict_escalation"
  | "information_clarity"
  | "chapter_hook"
  | "differentiation";

export interface CommercialReport {
  id: string;
  chapter_id: string;
  total_score: number;
  recommendation: "pass" | "revise";
  dimensions: Array<{ dimension: CommercialDimension; score: number; reason: string }>;
  issues: Array<{
    id: string;
    severity: "warning" | "error";
    dimension: CommercialDimension;
    description: string;
    citation: { source: "draft"; location: string; quote: string };
    references?: Array<{ path: string; location: string; quote: string }>;
  }>;
}

export interface CommercialAudit {
  commercial_report: CommercialReport;
  minimum_commercial_score: number;
  commercial_gate_passed: boolean;
}

export interface CommercialObservationInput {
  observed_at: string;
  impressions: number;
  opens: number;
  chapter_one_completions: number;
  chapter_three_completions: number;
  follows: number;
  read_minutes: number;
  revenue_cents: number;
}

export interface CommercialObservation extends CommercialObservationInput {
  id: string;
}

export interface CommercialMetrics {
  observations: number;
  impressions: number;
  opens: number;
  chapter_one_completions: number;
  chapter_three_completions: number;
  follows: number;
  read_minutes: number;
  revenue_cents: number;
  click_through_rate: number;
  chapter_one_completion_rate: number;
  chapter_three_retention_rate: number;
  follow_rate: number;
  average_read_minutes_per_open: number;
  revenue_per_thousand_opens_yuan: number;
}

export class ApiError extends Error {
  readonly code?: string;
  readonly status: number;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const apiErrorMessages: Record<string, string> = {
  WORKFLOW_GATE_BLOCKED: "当前操作尚未满足创作流程前置条件，请先完成并确认引导中的内容。",
  COMMERCIAL_GATE_BLOCKED: "商业质量未达到确认门槛，请修改章节或填写人工覆盖理由。",
  ACTIVE_TASK_CONFLICT: "已有写入任务正在进行或等待确认，请先完成、取消或处理该任务。",
  MODEL_API_KEY_MISSING: "尚未配置模型 API Key，请前往“模型设置”保存后再试。",
  MODEL_SETTINGS_NOT_FOUND: "尚未保存模型设置，请前往“模型设置”完成配置。",
  MODEL_SETTINGS_INVALID: "模型设置无效，请检查 Base URL、模型名称和 API Key。",
  MODEL_SETTINGS_READ_FAILED: "模型设置无法读取，请检查本地配置后重试。",
};

function friendlyApiErrorMessage(code: string | undefined, fallback: string): string {
  return code ? apiErrorMessages[code] ?? fallback : fallback;
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...init.headers },
  });
  const payload: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    const body = payload as { error?: { message?: string; code?: string }; detail?: { message?: string; code?: string } } | undefined;
    throw new ApiError(
      friendlyApiErrorMessage(
        body?.error?.code ?? body?.detail?.code,
        body?.error?.message ?? body?.detail?.message ?? `请求失败（${response.status}）`,
      ),
      response.status,
      body?.error?.code ?? body?.detail?.code,
    );
  }
  return payload as T;
}

export function createProject(input: {
  project_id: string;
  title: string;
  genre: string;
  target_words: number;
  constraints: string;
  setting_draft: string;
}): Promise<{ project: Project; task: Task }> {
  return requestJson("/api/projects", { method: "POST", body: JSON.stringify(input) });
}

export function getProject(projectId: string): Promise<Project> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}`);
}

export function getProjectSnapshot(projectId: string): Promise<ProjectSnapshot> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/snapshot`);
}

export function getDocument(projectId: string, path: string): Promise<{ path: string; content: string; revision: string | null }> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/documents?path=${encodeURIComponent(path)}`);
}

export function getWorkflowStatus(projectId: string): Promise<WorkflowStatus> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/workflow-status`);
}

export function listProjects(): Promise<Project[]> { return requestJson("/api/projects"); }

export function listTasks(projectId: string): Promise<Task[]> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/tasks`);
}

export function listTaskDrafts(projectId: string, taskId: string): Promise<string[]> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/tasks/${taskId}/drafts`);
}

export function transitionTask(projectId: string, taskId: string, action: "start" | "cancel" | "fail"): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/tasks/${taskId}/${action}`, { method: "POST" });
}

export function retryTask(projectId: string, taskId: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/tasks/${taskId}/retry`, { method: "POST" });
}

export function getTask(projectId: string, taskId: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/tasks/${taskId}`);
}

export function getTaskRun(projectId: string, taskId: string): Promise<TaskRunManifest> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/tasks/${taskId}/run`);
}

export function getDraft(projectId: string, taskId: string, path: string): Promise<{ task_id: string; path: string; content: string; revision: string | null }> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/drafts/${taskId}?path=${encodeURIComponent(path)}`);
}

export function saveDraft(projectId: string, taskId: string, path: string, content: string, baseRevision: string | null): Promise<{ task_id: string; path: string; content: string; revision: string | null }> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/drafts/${taskId}`, {
    method: "PUT",
    body: JSON.stringify({ path, content, base_revision: baseRevision }),
  });
}

export function approveSetting(projectId: string, taskId: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/setting/${taskId}/approve`, {
    method: "POST",
  });
}

export function createOutline(projectId: string, content: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/design/outline`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function approveOutline(projectId: string, taskId: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/design/outline/${taskId}/approve`, {
    method: "POST",
  });
}

export function createVolume(projectId: string, volumeId: string, content: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/design/volumes/${encodeURIComponent(volumeId)}`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function approveVolume(projectId: string, volumeId: string, taskId: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/design/volumes/${encodeURIComponent(volumeId)}/${taskId}/approve`, { method: "POST" });
}

export function generateSetting(projectId: string, taskId: string, instruction: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/design/agent/setting/${taskId}`, {
    method: "POST",
    body: JSON.stringify({ instruction }),
  });
}

export function generateOutline(projectId: string, instruction: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/design/agent/outline`, {
    method: "POST",
    body: JSON.stringify({ instruction }),
  });
}

export function generateVolume(projectId: string, volumeId: string, instruction: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/design/agent/volumes/${encodeURIComponent(volumeId)}`, {
    method: "POST",
    body: JSON.stringify({ instruction }),
  });
}

export function generateChapter(projectId: string, chapterId: string, instruction: string, volumeId = "1"): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/design/agent/chapters/${encodeURIComponent(chapterId)}`, {
    method: "POST",
    body: JSON.stringify({ instruction, volume_id: volumeId }),
  });
}

export function startChapter(
  projectId: string,
  chapterId: string,
  input: { plan: string; draft: string; issues: Array<Record<string, string>>; volume_id?: string },
): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/design/chapters/${encodeURIComponent(chapterId)}`, {
    method: "POST",
    body: JSON.stringify({ ...input, volume_id: input.volume_id ?? "1" }),
  });
}

export function approveChapter(projectId: string, chapterId: string, taskId: string, commercialOverrideReason?: string, acceptedMemoryIds: string[] = []): Promise<Task> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/design/chapters/${encodeURIComponent(chapterId)}/${taskId}/approve`,
    { method: "POST", body: JSON.stringify({ commercial_override_reason: commercialOverrideReason ?? null, accepted_memory_ids: acceptedMemoryIds }) },
  );
}

export function auditChapterCommercially(projectId: string, chapterId: string, taskId: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/design/agent/chapters/${encodeURIComponent(chapterId)}/${taskId}/commercial-audit`, { method: "POST" });
}

export function getCommercialProfile(projectId: string): Promise<CommercialProfile | null> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/commercial/profile`);
}

export function getCommercialAudit(projectId: string, taskId: string): Promise<CommercialAudit | null> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/commercial/reports/${taskId}`);
}

export function createCommercialDraft(projectId: string, profile: CommercialProfile): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/commercial/draft`, { method: "POST", body: JSON.stringify(profile) });
}

export function updateCommercialDraft(projectId: string, taskId: string, profile: CommercialProfile): Promise<CommercialProfile> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/commercial/draft/${taskId}`, { method: "PUT", body: JSON.stringify(profile) });
}

export function getCommercialDraft(projectId: string, taskId: string): Promise<CommercialProfile> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/commercial/draft/${taskId}`);
}

export function approveCommercialDraft(projectId: string, taskId: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/commercial/draft/${taskId}/approve`, { method: "POST" });
}

export function generateCommercialProfile(projectId: string, input: {
  platform: CommercialProfile["platform"];
  monetization: CommercialProfile["monetization"];
  target_reader: string;
  core_fantasy: string;
  differentiator: string;
  comparable_titles: string[];
  instruction: string;
}): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/commercial/agent`, { method: "POST", body: JSON.stringify(input) });
}

export function listCommercialObservations(projectId: string): Promise<CommercialObservation[]> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/commercial/observations`);
}

export function createCommercialObservation(projectId: string, input: CommercialObservationInput): Promise<CommercialObservation> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/commercial/observations`, { method: "POST", body: JSON.stringify(input) });
}

export function getCommercialMetrics(projectId: string): Promise<CommercialMetrics> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/commercial/metrics`);
}

export function getMemory(projectId: string, kind: MemoryRecord["kind"], id: string): Promise<MemoryRecord> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/memory/${kind}/${encodeURIComponent(id)}`);
}

export function searchMemory(projectId: string, query: string): Promise<Array<{ path: string; location: string; quote: string; sha256: string }>> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/search?q=${encodeURIComponent(query)}`);
}

export function listMemory(projectId: string): Promise<MemoryRecord[]> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/memory`);
}

export function listMemoryCandidates(projectId: string, taskId: string): Promise<MemoryCandidate[]> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/tasks/${taskId}/memory-candidates`);
}

export function correctMemory(projectId: string, record: MemoryRecord): Promise<MemoryRecord> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/memory/${record.kind}/${encodeURIComponent(record.id)}`, {
    method: "PUT",
    body: JSON.stringify({ source: record.source, location: record.location, quote: record.quote }),
  });
}

export function revokeMemory(projectId: string, record: MemoryRecord): Promise<MemoryRecord> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/memory/${record.kind}/${encodeURIComponent(record.id)}/revoke`, { method: "POST" });
}

export interface TaskEventRecord {
  task_id: string;
  project_id: string;
  sequence: number;
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export function getTaskHistory(projectId: string, taskId: string): Promise<TaskEventRecord[]> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/tasks/${taskId}/history`);
}

export interface ChapterBoundary {
  number: number;
  title: string;
  start: Record<string, number>;
  end: Record<string, number>;
}

export interface ImportPreview {
  encoding: string;
  sha256: string;
  size: number;
  chapters: ChapterBoundary[];
}

export async function uploadImport(projectId: string, importId: string, file: File): Promise<ImportPreview> {
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/imports/${encodeURIComponent(importId)}`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/octet-stream" },
    body: await file.arrayBuffer(),
  });
  const payload: unknown = await response.json().catch(() => undefined);
  if (!response.ok) throw new ApiError(`Import failed with status ${response.status}`, response.status);
  return payload as ImportPreview;
}

export function confirmImport(projectId: string, importId: string, preview: ImportPreview): Promise<{ task: Task; chapters: ChapterBoundary[] }> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/imports/${encodeURIComponent(importId)}/boundaries`, {
    method: "POST",
    body: JSON.stringify({ source_sha256: preview.sha256, source_size: preview.size, boundaries: preview.chapters }),
  });
}

export function approveImport(projectId: string, importId: string, taskId: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/imports/${encodeURIComponent(importId)}/${taskId}/approve`, { method: "POST" });
}

export interface Revision { id: string; message: string }
export interface RevisionDiff { path: string; status: "added" | "modified" | "deleted"; patch: string }
export function listRevisions(projectId: string): Promise<Revision[]> { return requestJson(`/api/projects/${encodeURIComponent(projectId)}/revisions`); }
export function compareRevisions(projectId: string, base: string, target: string): Promise<RevisionDiff[]> { return requestJson(`/api/projects/${encodeURIComponent(projectId)}/revisions/diff?base=${encodeURIComponent(base)}&target=${encodeURIComponent(target)}`); }
export function restoreRevision(projectId: string, revisionId: string, expectedRevision: string): Promise<Revision> { return requestJson(`/api/projects/${encodeURIComponent(projectId)}/revisions/${revisionId}/restore`, { method: "POST", body: JSON.stringify({ expected_revision: expectedRevision }) }); }

export interface UsageSummary { project_id: string; model: string | null; request_count: number; input_tokens: number; output_tokens: number; total_tokens: number; total_cost_cny: number; pricing_configured: boolean }
export function getProjectUsage(projectId: string): Promise<UsageSummary> { return requestJson(`/api/projects/${encodeURIComponent(projectId)}/usage`); }

export interface ModelSettings {
  base_url: string;
  model: string;
  timeout: number;
  disable_thinking: boolean;
  has_api_key: boolean;
}

export function getModelSettings(): Promise<ModelSettings> { return requestJson("/api/settings"); }
export function saveModelSettings(settings: Omit<ModelSettings, "has_api_key">): Promise<ModelSettings> { return requestJson("/api/settings", { method: "PUT", body: JSON.stringify(settings) }); }
export function saveApiKey(apiKey: string): Promise<{ has_api_key: boolean }> { return requestJson("/api/settings/secret", { method: "PUT", body: JSON.stringify({ api_key: apiKey }) }); }
export function testModelConnection(): Promise<{ status: "ok" }> { return requestJson("/api/settings/connection", { method: "POST" }); }

interface HealthRequestOptions {
  signal?: AbortSignal;
}

const HEALTH_REQUEST_TIMEOUT_MS = 5_000;

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    candidate.status === "ok" &&
    candidate.service === "tame-ink-api" &&
    typeof candidate.version === "string"
  );
}

export async function getHealth(options: HealthRequestOptions = {}): Promise<HealthResponse> {
  const controller = new AbortController();
  const abortFromCaller = () => controller.abort(options.signal?.reason);
  const timeoutId = setTimeout(() => {
    controller.abort(new DOMException("Health request timed out", "TimeoutError"));
  }, HEALTH_REQUEST_TIMEOUT_MS);

  if (options.signal?.aborted) {
    abortFromCaller();
  } else {
    options.signal?.addEventListener("abort", abortFromCaller, { once: true });
  }

  try {
    const response = await fetch("/api/health", {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Health request failed with status ${response.status}`);
    }

    const payload: unknown = await response.json();
    if (!isHealthResponse(payload)) {
      throw new Error("Health response did not match the expected schema");
    }

    return payload;
  } finally {
    clearTimeout(timeoutId);
    options.signal?.removeEventListener("abort", abortFromCaller);
  }
}
