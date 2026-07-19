import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { queryKeys } from "./app/queryKeys";

function renderApp(path = "/") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { ...render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>), queryClient };
}

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("App", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("shows a persistent offline state without hiding the workspace", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    renderApp();
    expect(screen.getByRole("heading", { name: "Tame Ink" })).toBeInTheDocument();
    expect(await screen.findByText("后端离线")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "项目导航" })).toBeInTheDocument();
  });

  it("opens the project creation workflow from the empty workspace", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "创建第一部作品" }));
    expect(screen.getByRole("heading", { name: "建立你的故事" })).toBeInTheDocument();
    expect(screen.getByLabelText("项目 ID")).toHaveValue("my-novel");
  });

  it("keeps model settings globally addressable", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/health") return response({ status: "ok", service: "tame-ink-api", version: "0.1.0" });
      if (path === "/api/projects") return response([]);
      if (path === "/api/settings") return response({ base_url: "https://api.example.com/v1", model: "model-1", timeout: 30, disable_thinking: false, has_api_key: true });
      return response({}, 404);
    }));
    renderApp("/settings");
    expect(await screen.findByRole("heading", { name: "模型设置", level: 2 })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Base URL")).toHaveValue("https://api.example.com/v1"));
    expect(screen.getByText("密钥已保存")).toBeInTheDocument();
  });

  it("renders overview metrics from the project snapshot", async () => {
    const project = { id: "book-1", title: "长夜", language: "zh-CN", genre: "悬疑", target_words: 800000, constraints: "第三人称" };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/health") return response({ status: "ok", service: "tame-ink-api", version: "0.1.0" });
      if (path === "/api/projects") return response([project]);
      if (path === "/api/projects/book-1") return response(project);
      if (path.endsWith("/snapshot")) return response({ project, documents: [], volumes: [], unassigned_chapters: [], stats: { total_words: 12345, chapter_count: 7, volume_count: 2, active_foreshadow_count: 3 } });
      if (path.endsWith("/workflow-status")) return response({ setting_confirmed: true, outline_confirmed: true, volume_one_confirmed: true, commercial_confirmed: true });
      if (path.endsWith("/tasks")) return response([]);
      if (path.endsWith("/usage")) return response({ project_id: "book-1", model: "model-1", request_count: 2, input_tokens: 100, output_tokens: 50, total_tokens: 150, total_cost_cny: 0.02, pricing_configured: true });
      if (path.endsWith("/revisions")) return response([]);
      return response({}, 404);
    }));
    renderApp("/projects/book-1/overview");
    expect(await screen.findByRole("heading", { name: "长夜" })).toBeInTheDocument();
    expect(screen.getByText("12,345")).toBeInTheDocument();
    expect(screen.getByText("继续写下一章")).toBeInTheDocument();
  });

  it("does not pick an unrelated latest task for the story document", async () => {
    const project = { id: "book-2", title: "任务隔离", language: "zh-CN", genre: "悬疑", target_words: 800000, constraints: "第三人称" };
    const baseTask = { project_id: "book-2", kind: "write", subject_id: null, volume_id: null, chapter_id: null, parent_task_id: null, retry_of_task_id: null, cancel_requested_at: null, error_code: null, error_message: null, started_at: null, finished_at: null, duration_ms: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:01Z" };
    const tasks = [{ ...baseTask, id: "chapter-task", purpose: "chapter", status: "awaiting_approval", subject_id: "1", volume_id: "1", chapter_id: "1" }, { ...baseTask, id: "setting-task", purpose: "setting", status: "completed", subject_id: "setting", duration_ms: 1 }];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === "/api/health") return response({ status: "ok", service: "tame-ink-api", version: "0.1.0" });
      if (url.pathname === "/api/projects") return response([project]);
      if (url.pathname === "/api/projects/book-2") return response(project);
      if (url.pathname.endsWith("/snapshot")) return response({ project, documents: [{ path: "canon/world/setting.md", kind: "setting", title: "正式设定", word_count: 4, updated_at: "2026-01-01T00:00:01Z" }], volumes: [], unassigned_chapters: [], stats: { total_words: 0, chapter_count: 0, volume_count: 0, active_foreshadow_count: 0 } });
      if (url.pathname.endsWith("/workflow-status")) return response({ setting_confirmed: true, outline_confirmed: false, volume_one_confirmed: false, commercial_confirmed: false });
      if (url.pathname.endsWith("/tasks")) return response(tasks);
      if (url.pathname.endsWith("/documents")) return response({ path: "canon/world/setting.md", content: "# 正式设定\n\n城市落雨。", revision: "r1" });
      return response({}, 404);
    }));
    renderApp("/projects/book-2/story");
    expect(await screen.findByRole("heading", { name: "正式设定" })).toBeInTheDocument();
    expect(screen.queryByText("chapter-task")).not.toBeInTheDocument();
  });

  it("reloads a regenerated setting draft when the reused task changes", async () => {
    const project = { id: "book-3", title: "草稿刷新", language: "zh-CN", genre: "悬疑", target_words: 800000, constraints: "第三人称" };
    const task = { id: "setting-task", project_id: "book-3", kind: "write", purpose: "setting", status: "awaiting_approval", subject_id: "setting", volume_id: null, chapter_id: null, parent_task_id: null, retry_of_task_id: null, cancel_requested_at: null, error_code: null, error_message: null, started_at: null, finished_at: null, duration_ms: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:01Z" };
    let draftContent = "# 旧设定\n\n旧版本。";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === "/api/health") return response({ status: "ok", service: "tame-ink-api", version: "0.1.0" });
      if (url.pathname === "/api/projects") return response([project]);
      if (url.pathname === "/api/projects/book-3") return response(project);
      if (url.pathname.endsWith("/snapshot")) return response({ project, documents: [], volumes: [], unassigned_chapters: [], stats: { total_words: 0, chapter_count: 0, volume_count: 0, active_foreshadow_count: 0 } });
      if (url.pathname.endsWith("/workflow-status")) return response({ setting_confirmed: false, outline_confirmed: false, volume_one_confirmed: false, commercial_confirmed: false });
      if (url.pathname.endsWith("/tasks")) return response([task]);
      if (url.pathname.endsWith("/drafts/setting-task")) return response({ task_id: task.id, path: "setting.md", content: draftContent, revision: "r1" });
      return response({}, 404);
    }));
    const { queryClient } = renderApp("/projects/book-3/story");
    expect(await screen.findByRole("heading", { name: "旧设定" })).toBeInTheDocument();

    draftContent = "# 新设定\n\n模型生成的新版本。";
    await act(async () => {
      queryClient.setQueryData(queryKeys.tasks("book-3"), [
        { ...task, updated_at: "2026-01-01T00:00:02Z" },
      ]);
    });

    expect(await screen.findByRole("heading", { name: "新设定" })).toBeInTheDocument();
  });
});
