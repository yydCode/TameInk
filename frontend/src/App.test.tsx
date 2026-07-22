import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const project = {
  id: "book-1",
  title: "长夜",
  language: "zh-CN",
  genre: "悬疑",
  target_words: null,
  constraints: "第三人称，克制叙述",
};
const task = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  project_id: "book-1",
  kind: "write",
  purpose: "setting",
  status: "awaiting_approval",
  subject_id: "webnovel-design-reader-contract",
  volume_id: null,
  chapter_id: null,
  parent_task_id: null,
  retry_of_task_id: null,
  cancel_requested_at: null,
  error_code: null,
  error_message: null,
  started_at: null,
  finished_at: null,
  duration_ms: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:01Z",
};

function renderApp(path = "/") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}><App /></MemoryRouter>
    </QueryClientProvider>,
  );
}

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("App", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("keeps navigation usable when the backend is offline", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    renderApp();
    expect(screen.getByRole("heading", { name: "Tame Ink" })).toBeInTheDocument();
    expect(await screen.findByText("后端离线")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "项目导航" })).toBeInTheDocument();
  });

  it("starts a P0 project with the first research task", async () => {
    // 项目 ID 现在由前端基于书名自动生成（含随机后缀），测试需动态匹配。
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/health") return response({ status: "ok", service: "tame-ink-api", version: "0.1.0" });
      if (path === "/api/projects") return response([]);
      const startMatch = path.match(/^\/api\/projects\/([^/]+)\/creative\/start$/);
      if (startMatch) return response({ project: { ...project, id: startMatch[1] }, task }, 201);
      const projectMatch = path.match(/^\/api\/projects\/([^/]+)$/);
      if (projectMatch) return response({ ...project, id: projectMatch[1] });
      if (path.endsWith("/creative/next")) return response({ kind: "wait", skill: null, artifact_id: null, task_id: task.id, reason: "等待执行" });
      if (path.endsWith("/creative/artifacts")) return response([]);
      if (path.endsWith("/tasks")) return response([task]);
      return response({}, 404);
    });
    vi.stubGlobal("fetch", fetcher);
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "创建第一部作品" }));
    // 新建对话框是两步式：先跳过 AI 起草，再手动填写审阅表单。
    fireEvent.click(screen.getByRole("button", { name: "跳过，手动填写" }));
    fireEvent.change(screen.getByLabelText("书名"), { target: { value: "新书" } });
    fireEvent.change(screen.getByLabelText("题材视图"), { target: { value: "都市悬疑" } });
    fireEvent.change(screen.getByLabelText("首个故事目标"), { target: { value: "先破解第一桩命案。" } });
    fireEvent.change(screen.getByLabelText("创作意图（可选）"), { target: { value: "让读者持续追问真相。" } });
    fireEvent.click(screen.getByRole("button", { name: "创建并进入工作台" }));
    await waitFor(() => {
      const startCall = fetcher.mock.calls.find(([url]) =>
        /^\/api\/projects\/[^/]+\/creative\/start$/.test(new URL(String(url), "http://localhost").pathname),
      ) as [RequestInfo | URL, RequestInit?] | undefined;
      expect(startCall).toBeDefined();
      expect(JSON.parse(String(startCall![1]?.body))).toEqual({
        title: "新书",
        platform: "番茄小说",
        genre_scope: "都市悬疑",
        initial_intent: "让读者持续追问真相。",
        first_story_goal: "先破解第一桩命案。",
        constraints: ["第三人称限知"],
        material_boundaries: ["仅使用已获授权素材；不模仿具体作者文风"],
      });
    });
    expect(await screen.findByText("等待执行")).toBeInTheDocument();
  });

  it("only offers formal confirmation for a candidate and writes the mapped formal path", async () => {
    const artifact = {
      id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      project_id: "book-1",
      task_id: task.id,
      kind: "reader_contract",
      source_layer: "candidate",
      status: "awaiting_approval",
      payload_path: "artifacts/reader-contract.json",
      accepted_layer: null,
      formal_path: null,
      accepted_decision_id: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:01Z",
    };
    const result = {
      id: "contract-1",
      skill: "webnovel-design-reader-contract",
      status: "ready",
      references: [],
      evidence: [],
      candidate: { artifact_kind: "reader_contract", summary: "主角以真相换取生存。", payload: { id: "reader-contract" } },
      decision_requests: [],
      effects: [],
    };
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/health") return response({ status: "ok", service: "tame-ink-api", version: "0.1.0" });
      if (path === "/api/projects") return response([project]);
      if (path === "/api/projects/book-1") return response(project);
      if (path.endsWith("/creative/next")) return response({ kind: "decision", skill: null, artifact_id: artifact.id, task_id: task.id, reason: "作者确认候选。" });
      if (path.endsWith("/creative/artifacts")) return response([artifact]);
      if (path.endsWith(`/drafts/${task.id}`)) return response({ task_id: task.id, path: artifact.payload_path, content: JSON.stringify(result), revision: null });
      if (path.endsWith("/tasks")) return response([task]);
      if (path.endsWith(`/artifacts/${artifact.id}/decisions`) && init?.method === "POST") return response({ ...task, status: "completed" });
      return response({}, 404);
    });
    vi.stubGlobal("fetch", fetcher);
    renderApp("/projects/book-1/workspace");
    expect(await screen.findByText("主角以真相换取生存。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认进入正式故事" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(
      `/api/projects/book-1/creative/artifacts/${artifact.id}/decisions`,
      expect.objectContaining({ method: "POST", body: expect.stringContaining("commitments/reader-contract.yaml") }),
    ));
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

  it("deletes a project after explicit confirmation", async () => {
    let deleted = false;
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://localhost").pathname;
      if (path === "/api/health") return response({ status: "ok", service: "tame-ink-api", version: "0.1.0" });
      if (path === "/api/projects") return response(deleted ? [] : [project]);
      if (path === "/api/projects/book-1" && init?.method === "DELETE") {
        deleted = true;
        return new Response(null, { status: 204 });
      }
      return response({}, 404);
    });
    vi.stubGlobal("fetch", fetcher);
    renderApp();

    fireEvent.click(await screen.findByRole("button", { name: "删除作品 长夜" }));
    expect(await screen.findByRole("heading", { name: "确认删除《长夜》？" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "永久删除" }));

    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(
      "/api/projects/book-1",
      expect.objectContaining({ method: "DELETE" }),
    ));
    expect(await screen.findByText("项目概览需要一个作品")).toBeInTheDocument();
  });
});
