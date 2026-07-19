import { expect, test } from "@playwright/test";

const task = {
  id: "71b1b146-d37f-4e45-8848-35fde3af15a4",
  project_id: "night-river",
  kind: "write",
  purpose: "setting",
  status: "awaiting_approval",
  subject_id: "setting",
  volume_id: null,
  chapter_id: null,
  parent_task_id: null,
  retry_of_task_id: null,
  cancel_requested_at: null,
  error_code: null,
  error_message: null,
  started_at: "2026-07-15T10:00:00Z",
  finished_at: null,
  duration_ms: null,
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
  let created = false;
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/health")
      return route.fulfill({
        json: { status: "ok", service: "tame-ink-api", version: "0.1.0" },
      });
    if (url.pathname === "/api/projects" && route.request().method() === "GET")
      return route.fulfill({ json: created ? [project] : [] });
    if (
      url.pathname === "/api/projects" &&
      route.request().method() === "POST"
    ) {
      created = true;
      return route.fulfill({ status: 201, json: { project, task } });
    }
    if (url.pathname === "/api/projects/night-river")
      return route.fulfill({ json: project });
    if (url.pathname.endsWith("/snapshot"))
      return route.fulfill({
        json: {
          project,
          documents: [],
          volumes: [],
          unassigned_chapters: [],
          stats: {
            total_words: 0,
            chapter_count: 0,
            volume_count: 0,
            active_foreshadow_count: 0,
          },
        },
      });
    if (url.pathname.endsWith("/workflow-status"))
      return route.fulfill({
        json: {
          setting_confirmed: false,
          outline_confirmed: false,
          volume_one_confirmed: false,
          commercial_confirmed: false,
        },
      });
    if (url.pathname.endsWith("/tasks")) return route.fulfill({ json: [task] });
    if (url.pathname.endsWith(`/tasks/${task.id}`))
      return route.fulfill({ json: task });
    if (url.pathname.includes("/drafts/")) {
      if (route.request().method() === "GET")
        return route.fulfill({
          json: {
            task_id: task.id,
            path: "setting.md",
            content: "# 故事设定\n\n雨夜渡口。",
            revision: null,
          },
        });
      return route.fulfill({
        json: {
          task_id: task.id,
          path: "setting.md",
          content: "# 故事设定\n\n雨夜渡口。",
          revision: null,
        },
      });
    }
    if (url.pathname.endsWith("/events"))
      return route.fulfill({ contentType: "text/event-stream", body: "" });
    return route.fulfill({
      status: 404,
      json: { error: { code: "NOT_FOUND", message: "not found" } },
    });
  });
});

test("creates a local project and restores its workbench", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "项目概览需要一个作品" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "创建第一部作品" }).click();
  await page.getByLabel("项目 ID").fill("night-river");
  await page.getByLabel("书名").fill("夜渡长河");
  await page.getByLabel("题材").fill("东方悬疑");
  await page.getByLabel("目标字数").fill("800000");
  await page.getByLabel("创作约束").fill("第三人称限知");
  await page
    .getByRole("button", { name: "创建并进入工作台" })
    .click({ force: true });

  await expect(
    page.getByRole("heading", { name: "夜渡长河", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("等待审批").first()).toBeVisible();

  await page.reload();
  await expect(
    page.getByRole("heading", { name: "夜渡长河", level: 1 }),
  ).toBeVisible();
  await expect(page.getByText("雨夜渡口。")).toBeVisible();
});
