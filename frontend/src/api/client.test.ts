import { afterEach, describe, expect, it, vi } from "vitest";

import { approveChapter, createCommercialObservation, createProject, generateCommercialProfile } from "./client";

describe("API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("creates a project with the exact backend payload", async () => {
    const payload = {
      project_id: "river-night",
      title: "夜渡",
      genre: "悬疑",
      target_words: 800000,
      constraints: "第三人称限知",
      setting_draft: "# 设定",
    };
    const response = {
      project: { id: "river-night", title: "夜渡", language: "zh-CN", genre: "悬疑", target_words: 800000, constraints: "第三人称限知" },
      task: { id: "71b1b146-d37f-4e45-8848-35fde3af15a4", project_id: "river-night", kind: "write", status: "awaiting_approval", created_at: "2026-07-15T10:00:00Z", updated_at: "2026-07-15T10:00:00Z" },
    };
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(response), { status: 201 }));
    vi.stubGlobal("fetch", fetcher);

    await expect(createProject(payload)).resolves.toEqual(response);
    expect(fetcher).toHaveBeenCalledWith("/api/projects", expect.objectContaining({ method: "POST", body: JSON.stringify(payload) }));
  });

  it("returns stable backend error information", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "WORKSPACE_PATH_VIOLATION", message: "request could not be processed" } }), { status: 400 })));

    await expect(createProject({ project_id: "../bad", title: "x", genre: "x", target_words: 1, constraints: "x", setting_draft: "x" })).rejects.toMatchObject({ code: "WORKSPACE_PATH_VIOLATION", status: 400 });
  });

  it("sends commercial generation, observation, and override payloads exactly", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const brief = {
      platform: "fanqie" as const,
      monetization: "free_ad" as const,
      target_reader: "升级读者",
      core_fantasy: "以失忆换升级",
      differentiator: "每次升级永久失去记忆",
      comparable_titles: [],
      instruction: "生成可验证定位",
    };
    const observation = {
      observed_at: "2026-07-15",
      impressions: 100,
      opens: 20,
      chapter_one_completions: 12,
      chapter_three_completions: 8,
      follows: 4,
      read_minutes: 160,
      revenue_cents: 250,
    };

    await generateCommercialProfile("book-1", brief);
    await createCommercialObservation("book-1", observation);
    await approveChapter("book-1", "1", "task-1", "编辑确认用于对照实验");

    expect(fetcher).toHaveBeenNthCalledWith(1, "/api/projects/book-1/commercial/agent", expect.objectContaining({ method: "POST", body: JSON.stringify(brief) }));
    expect(fetcher).toHaveBeenNthCalledWith(2, "/api/projects/book-1/commercial/observations", expect.objectContaining({ method: "POST", body: JSON.stringify(observation) }));
    expect(fetcher).toHaveBeenNthCalledWith(3, "/api/projects/book-1/design/chapters/1/task-1/approve", expect.objectContaining({ method: "POST", body: JSON.stringify({ commercial_override_reason: "编辑确认用于对照实验" }) }));
  });
});
