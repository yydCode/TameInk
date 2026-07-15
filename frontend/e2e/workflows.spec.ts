import { expect, test, type Page } from "@playwright/test";

const project = {
  id: "existing-book",
  title: "已有作品",
  language: "zh-CN",
  genre: "悬疑",
  target_words: 800000,
  constraints: "第三人称",
};
const task = {
  id: "71b1b146-d37f-4e45-8848-35fde3af15a4",
  project_id: project.id,
  kind: "write",
  status: "awaiting_approval",
  created_at: "2026-07-15T10:00:00Z",
  updated_at: "2026-07-15T10:00:00Z",
};
const location = (line: number, character: number) => ({ byte: character, character, line, column: 1 });

async function openExistingProject(page: Page, status = "等待审批") {
  await page.goto("/");
  await page.getByRole("button", { name: /已有作品/ }).first().click();
  await expect(page.getByRole("heading", { name: "已有作品", level: 2 })).toBeVisible();
  await expect(page.locator("main").getByRole("region", { name: "任务状态" }).first()).toContainText(status);
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/health") return route.fulfill({ json: { status: "ok", service: "tame-ink-api", version: "0.1.0" } });
    if (url.pathname === "/api/projects" && request.method() === "GET") return route.fulfill({ json: [project] });
    if (url.pathname === `/api/projects/${project.id}`) return route.fulfill({ json: project });
    if (url.pathname === `/api/projects/${project.id}/tasks`) return route.fulfill({ json: [task] });
    if (url.pathname.endsWith(`/tasks/${task.id}/drafts`)) return route.fulfill({ json: ["setting.md"] });
    if (url.pathname.endsWith(`/drafts/${task.id}`)) return route.fulfill({ json: { task_id: task.id, path: "setting.md", content: "# 原设定\n\n旧句。中段。旧尾。", revision: "rev-1" } });
    if (url.pathname.endsWith(`/tasks/${task.id}/history`)) return route.fulfill({ json: [{ task_id: task.id, project_id: project.id, sequence: 1, type: "task.created", timestamp: task.created_at, data: {} }] });
    if (url.pathname.endsWith(`/tasks/${task.id}/cancel`)) return route.fulfill({ json: { ...task, status: "cancelled" } });
    if (url.pathname.endsWith("/events")) return route.fulfill({ contentType: "text/event-stream", body: "" });
    if (url.pathname === `/api/projects/${project.id}/imports/book`) return route.fulfill({ status: 201, json: { encoding: "utf-8", sha256: "abc", size: 100, chapters: [
      { number: 1, title: "旧标题", start: location(1, 0), end: location(3, 20) },
      { number: 2, title: "误识别", start: location(3, 20), end: location(5, 40) },
    ] } });
    if (url.pathname.endsWith("/imports/book/boundaries")) return route.fulfill({ status: 201, json: { task, chapters: [] } });
    return route.fulfill({ status: 404, json: { error: { code: "NOT_FOUND", message: "not found" } } });
  });
});

test("opens an existing project and manages import boundaries", async ({ page }) => {
  await openExistingProject(page);

  await page.getByRole("button", { name: "作品导入" }).click();
  await page.locator('input[type="file"]').setInputFiles({ name: "book.txt", mimeType: "text/plain", buffer: Buffer.from("第一章\n正文") });
  await page.getByRole("button", { name: "解析章节" }).click();
  await page.getByLabel("第 1 条标题").fill("修正标题");
  await page.getByRole("button", { name: "移除 误识别" }).click();
  await page.getByRole("button", { name: "确认章节边界" }).click();
  await expect(page.getByText("1 章")).toBeVisible();
});

test("shows task history and cancels an active task", async ({ page }) => {
  await openExistingProject(page);
  await page.getByRole("button", { name: "运行记录" }).click();
  await expect(page.getByText(task.id)).toBeVisible();
  await page.getByRole("button", { name: "事件" }).click();
  await expect(page.getByText("task.created")).toBeVisible();
  await page.getByRole("button", { name: "取消" }).click();
  await expect(page.getByText("任务已取消")).toBeVisible();
});

test("reviews AI changes independently", async ({ page }) => {
  await openExistingProject(page);
  const editor = page.locator(".ProseMirror");
  await editor.locator("p").fill("新句。中段。新尾。");
  await page.getByRole("button", { name: "查看差异" }).click();
  await expect(page.getByRole("dialog", { name: "修改差异" }).getByRole("checkbox")).toHaveCount(2);
  await page.getByRole("dialog", { name: "修改差异" }).getByRole("checkbox").nth(1).uncheck();
  await page.getByRole("button", { name: "应用审核结果" }).click();
  await expect(editor).toContainText("旧尾");
  await expect(editor).toContainText("新句");
});

test("resumes an interrupted task", async ({ page }) => {
  const interrupted = { ...task, status: "interrupted" };
  await page.route(`**/api/projects/${project.id}/tasks`, (route) => route.fulfill({ json: [interrupted] }));
  await page.route(`**/api/projects/${project.id}/tasks/${task.id}/start`, (route) => route.fulfill({ json: { ...task, status: "running" } }));

  await openExistingProject(page, "任务已中断");
  await page.getByRole("button", { name: "运行记录" }).click();
  await page.getByRole("button", { name: "恢复" }).click();
  await expect(page.getByText("正在运行")).toBeVisible();
});

test("stops autosave and exposes recovery actions on a revision conflict", async ({ page }) => {
  await page.route(`**/api/projects/${project.id}/drafts/${task.id}`, async (route) => {
    if (route.request().method() === "PUT") {
      return route.fulfill({
        status: 409,
        json: { error: { code: "CANON_VERSION_CONFLICT", message: "revision conflict" } },
      });
    }
    return route.fallback();
  });

  await openExistingProject(page);
  await page.locator(".ProseMirror p").fill("本地未保存修改。");
  await expect(page.getByRole("alert")).toContainText("自动保存已停止");
  await expect(page.getByRole("button", { name: "查看本地差异" })).toBeVisible();
  await expect(page.getByRole("button", { name: "重新加载正式版本" })).toBeVisible();
});
