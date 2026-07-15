import { expect, test } from "@playwright/test";

const task = {
  id: "71b1b146-d37f-4e45-8848-35fde3af15a4",
  project_id: "night-river",
  kind: "write",
  status: "awaiting_approval",
  created_at: "2026-07-15T10:00:00Z",
  updated_at: "2026-07-15T10:00:00Z",
};
const project = {
  id: "night-river",
  title: "夜渡长河",
  language: "zh-CN",
  genre: "东方悬疑",
  target_words: 800000,
  constraints: "第三人称限知",
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/health") return route.fulfill({ json: { status: "ok", service: "tame-ink-api", version: "0.1.0" } });
    if (url.pathname === "/api/projects" && route.request().method() === "POST") return route.fulfill({ status: 201, json: { project, task } });
    if (url.pathname === "/api/projects/night-river") return route.fulfill({ json: project });
    if (url.pathname.endsWith(`/tasks/${task.id}`)) return route.fulfill({ json: task });
    if (url.pathname.includes("/drafts/")) {
      if (route.request().method() === "GET") return route.fulfill({ json: { task_id: task.id, path: "setting.md", content: "# 故事设定\n\n雨夜渡口。" } });
      return route.fulfill({ json: { task_id: task.id, path: "setting.md", content: "# 故事设定\n\n雨夜渡口。" } });
    }
    if (url.pathname.endsWith("/events")) return route.fulfill({ contentType: "text/event-stream", body: "" });
    return route.fulfill({ status: 404, json: { error: { code: "NOT_FOUND", message: "not found" } } });
  });
});

test("creates a local project and restores its workbench", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "从一个新故事开始" })).toBeVisible();
  await page.getByRole("button", { name: "创建第一部作品" }).click();
  await page.getByLabel("项目 ID").fill("night-river");
  await page.getByLabel("书名").fill("夜渡长河");
  await page.getByLabel("题材").fill("东方悬疑");
  await page.getByLabel("目标字数").fill("800000");
  await page.getByLabel("创作约束").fill("第三人称限知");
  await page.getByRole("button", { name: "创建并进入工作台" }).click({ force: true });

  await expect(page.getByRole("heading", { name: "夜渡长河", level: 2 })).toBeVisible();
  await expect(page.getByText("等待审批").first()).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: "夜渡长河", level: 2 })).toBeVisible();
  await expect(page.getByText("雨夜渡口。")).toBeVisible();
});
