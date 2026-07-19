import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";

describe("App", () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("shows the application title and an explicit offline status", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<App />);

    expect(screen.getByRole("heading", { name: "Tame Ink" })).toBeInTheDocument();
    expect(await screen.findByText("后端离线")).toBeInTheDocument();
  });

  it("shows the backend as offline when the health request times out", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted", "AbortError"));
          });
        });
      }),
    );

    render(<App />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(screen.getByText("后端离线")).toBeInTheDocument();
  });

  it("cancels the health request when the application unmounts", () => {
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        if (String(input).endsWith("/api/health")) requestSignal = init?.signal ?? undefined;
        return new Promise<Response>(() => undefined);
      }),
    );

    const { unmount } = render(<App />);
    unmount();

    expect(requestSignal?.aborted).toBe(true);
  });

  it("opens the project creation workflow", () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "创建第一部作品" }));

    expect(screen.getByRole("heading", { name: "建立你的故事" })).toBeInTheDocument();
    expect(screen.getByLabelText("项目 ID")).toHaveValue("my-novel");
    expect(screen.getByRole("button", { name: "创建并进入工作台" })).toBeInTheDocument();
  });

  it("shows project-scoped menu states and keeps model settings globally available", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "章节工作台" }));
    expect(screen.getByRole("heading", { name: "章节工作台需要一个作品" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "模型设置" }));
    expect(screen.getByRole("heading", { name: "模型设置", level: 2 })).toBeInTheDocument();
    expect(screen.getByLabelText("Base URL")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存设置" })).toBeInTheDocument();
  });

  it("renders the commercial workbench and requires a custom platform name", async () => {
    const project = { id: "book-1", title: "失忆签到", language: "zh-CN", genre: "玄幻升级", target_words: 800000, constraints: "第三人称" };
    const profile = {
      schema_version: 1,
      platform: "fanqie",
      custom_platform: null,
      monetization: "free_ad",
      target_reader: "升级读者",
      core_fantasy: "以失忆换升级",
      differentiator: "每次升级永久失去重要记忆",
      emotional_payoffs: ["绝境反杀"],
      opening_promise: "首章展示能力和代价",
      first_thirty_chapter_promise: "三次升级改变关键关系",
      update_cadence: "每日两章",
      title_candidates: ["失忆签到"],
      synopsis: "周玄必须在力量和身份之间选择。",
      comparable_titles: [],
      minimum_commercial_score: 75,
      targets: { click_through_rate: null, chapter_one_completion_rate: null, chapter_three_retention_rate: null, follow_rate: null, revenue_per_thousand_opens_yuan: null },
    };
    const metrics = { observations: 1, impressions: 100, opens: 20, chapter_one_completions: 12, chapter_three_completions: 8, follows: 4, read_minutes: 160, revenue_cents: 250, click_through_rate: 0.2, chapter_one_completion_rate: 0.6, chapter_three_retention_rate: 0.4, follow_rate: 0.2, average_read_minutes_per_open: 8, revenue_per_thousand_opens_yuan: 125 };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const body = path === "/api/health" ? { status: "ok", service: "tame-ink-api", version: "0.1.0" }
        : path === "/api/projects" ? [project]
          : path === `/api/projects/${project.id}` ? project
            : path === `/api/projects/${project.id}/tasks` ? []
              : path.endsWith("/commercial/profile") ? profile
                : path.endsWith("/commercial/metrics") ? metrics
                  : path.endsWith("/commercial/observations") ? []
                    : {};
      return new Response(JSON.stringify(body), { status: 200 });
    }));

    render(<App />);
    fireEvent.click((await screen.findAllByRole("button", { name: /失忆签到/ }))[0]);
    fireEvent.click(await screen.findByRole("button", { name: "商业增长" }));

    expect(await screen.findByRole("heading", { name: "番茄首测策略" })).toBeInTheDocument();
    expect(screen.getAllByText("20.0%")).toHaveLength(2);
    const confirm = screen.getByRole("button", { name: "确认商业定位" });
    expect(confirm).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "自定义" }));
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("平台名称"), { target: { value: "测试平台" } });
    expect(confirm).toBeEnabled();
  });

  it("shows the actual Skill and compiled sources for the active task", async () => {
    const project = { id: "book-run", title: "上下文样本", language: "zh-CN", genre: "悬疑", target_words: 800000, constraints: "第三人称" };
    const task = { id: "task-run", project_id: project.id, kind: "write", status: "completed", created_at: "2026-07-19T10:00:00Z", updated_at: "2026-07-19T10:01:00Z" };
    const run = {
      agent_runs: [{
        agent: "RetentionAuditor",
        skill: "webnovel-retention",
        skill_sha256: "a".repeat(64),
        stage: "retention-audit",
        source_paths: ["canon/outline.md", "memory/summaries/book.md"],
        queries: ["主角 能力"],
        total_characters: 2048,
        duration_ms: 321,
        status: "success",
        error_code: null,
      }],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const body = path === "/api/health" ? { status: "ok", service: "tame-ink-api", version: "0.1.0" }
        : path === "/api/projects" ? [project]
          : path === `/api/projects/${project.id}` ? project
            : path === `/api/projects/${project.id}/tasks` ? [task]
              : path.endsWith(`/tasks/${task.id}/drafts`) ? ["chapter.md"]
                : path.endsWith(`/tasks/${task.id}/run`) ? run
                  : path.endsWith(`/drafts/${task.id}`) ? { task_id: task.id, path: "chapter.md", content: "# 第一章\n\n正文", revision: "r1" }
                    : path.endsWith("/workflow-status") ? { setting_confirmed: true, outline_confirmed: true, volume_one_confirmed: true, commercial_confirmed: true }
                      : path.endsWith(`/commercial/reports/${task.id}`) ? null
                        : {};
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }));

    render(<App />);
    fireEvent.click((await screen.findAllByRole("button", { name: /上下文样本/ }))[0]);

    expect(await screen.findByText("retention-audit")).toBeInTheDocument();
    expect(screen.getByText("RetentionAuditor · webnovel-retention")).toBeInTheDocument();
    expect(screen.getByText("1 条检索")).toBeInTheDocument();
    expect(screen.getByText("2,048 字符")).toBeInTheDocument();
    expect(screen.getByText("canon/outline.md")).toBeInTheDocument();
    expect(screen.queryByText("canon/world/setting.md")).not.toBeInTheDocument();
  });
});
