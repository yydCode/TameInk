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
  status: TaskStatus;
  created_at: string;
  updated_at: string;
}

export interface MemoryRecord {
  id: string;
  kind: "fact" | "event" | "relationship" | "foreshadowing";
  status: "active" | "resolved" | "superseded";
  source: string;
  location: string;
  quote: string;
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

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...init.headers },
  });
  const payload: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    const body = payload as { error?: { message?: string; code?: string }; detail?: { message?: string; code?: string } } | undefined;
    throw new ApiError(
      body?.error?.message ?? body?.detail?.message ?? `Request failed with status ${response.status}`,
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

export function getTask(projectId: string, taskId: string): Promise<Task> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/tasks/${taskId}`);
}

export function getDraft(projectId: string, taskId: string, path: string): Promise<{ task_id: string; path: string; content: string }> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/drafts/${taskId}?path=${encodeURIComponent(path)}`);
}

export function saveDraft(projectId: string, taskId: string, path: string, content: string): Promise<{ task_id: string; path: string; content: string }> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/drafts/${taskId}`, {
    method: "PUT",
    body: JSON.stringify({ path, content }),
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

export function approveChapter(projectId: string, chapterId: string, taskId: string): Promise<Task> {
  return requestJson(
    `/api/projects/${encodeURIComponent(projectId)}/design/chapters/${encodeURIComponent(chapterId)}/${taskId}/approve`,
    { method: "POST" },
  );
}

export function getMemory(projectId: string, kind: MemoryRecord["kind"], id: string): Promise<MemoryRecord> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/memory/${kind}/${encodeURIComponent(id)}`);
}

export function searchMemory(projectId: string, query: string): Promise<Array<{ path: string; location: string; snippet: string }>> {
  return requestJson(`/api/projects/${encodeURIComponent(projectId)}/search?q=${encodeURIComponent(query)}`);
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

export interface ModelSettings {
  base_url: string;
  model: string;
  timeout: number;
  has_api_key?: boolean;
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
