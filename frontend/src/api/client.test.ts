import { afterEach, describe, expect, it, vi } from "vitest";

import { createProject } from "./client";

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
});
