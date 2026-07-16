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
const commercialProfile = {
  schema_version: 1, platform: "fanqie", custom_platform: null, monetization: "free_ad",
  target_reader: "悬疑读者", core_fantasy: "破解不可能犯罪", differentiator: "线索反向误导",
  emotional_payoffs: ["识破骗局"], opening_promise: "首章发生命案", first_thirty_chapter_promise: "破解主案",
  update_cadence: "每日两章", title_candidates: ["已有作品"], synopsis: "侦探破解密室命案。", comparable_titles: [], minimum_commercial_score: 75,
  targets: { click_through_rate: null, chapter_one_completion_rate: null, chapter_three_retention_rate: null, follow_rate: null, revenue_per_thousand_opens_yuan: null },
};
const emptyMetrics = { observations: 0, impressions: 0, opens: 0, chapter_one_completions: 0, chapter_three_completions: 0, follows: 0, read_minutes: 0, revenue_cents: 0, click_through_rate: 0, chapter_one_completion_rate: 0, chapter_three_retention_rate: 0, follow_rate: 0, average_read_minutes_per_open: 0, revenue_per_thousand_opens_yuan: 0 };

async function openExistingProject(page: Page, status = "等待审批") {
  await page.goto("/");
  await page.getByRole("button", { name: /已有作品/ }).first().click();
  await expect(page.getByRole("heading", { name: "已有作品", level: 2 })).toBeVisible();
  await expect(page.locator("main").getByRole("region", { name: "任务状态" }).first()).toContainText(status);
}

test.beforeEach(async ({ page }) => {
  let observations: object[] = [];
  let metrics = emptyMetrics;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/health") return route.fulfill({ json: { status: "ok", service: "tame-ink-api", version: "0.1.0" } });
    if (url.pathname === "/api/projects" && request.method() === "GET") return route.fulfill({ json: [project] });
    if (url.pathname === `/api/projects/${project.id}`) return route.fulfill({ json: project });
    if (url.pathname === `/api/projects/${project.id}/workflow-status`) return route.fulfill({ json: { setting_confirmed: true, outline_confirmed: true, volume_one_confirmed: true, commercial_confirmed: true } });
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
    if (url.pathname.endsWith("/commercial/profile")) return route.fulfill({ json: commercialProfile });
    if (url.pathname.endsWith("/commercial/metrics")) return route.fulfill({ json: metrics });
    if (url.pathname.endsWith("/commercial/observations") && request.method() === "GET") return route.fulfill({ json: observations });
    if (url.pathname.endsWith("/commercial/observations") && request.method() === "POST") {
      const body = request.postDataJSON();
      const created = { id: "observation-1", ...body };
      observations = [created];
      metrics = { observations: 1, impressions: 100, opens: 20, chapter_one_completions: 12, chapter_three_completions: 8, follows: 4, read_minutes: 160, revenue_cents: 250, click_through_rate: 0.2, chapter_one_completion_rate: 0.6, chapter_three_retention_rate: 0.4, follow_rate: 0.2, average_read_minutes_per_open: 8, revenue_per_thousand_opens_yuan: 125 };
      return route.fulfill({ status: 201, json: created });
    }
    return route.fulfill({ status: 404, json: { error: { code: "NOT_FOUND", message: "not found" } } });
  });
});

test("records real commercial funnel observations", async ({ page }) => {
  await openExistingProject(page);
  await page.getByRole("button", { name: "商业增长" }).click();
  await expect(page.getByRole("heading", { name: "番茄首测策略" })).toBeVisible();
  await page.getByLabel("曝光").fill("100");
  await page.getByLabel("打开").fill("20");
  await page.getByLabel("首章完读").fill("12");
  await page.getByLabel("三章完读").fill("8");
  await page.getByLabel("追读").fill("4");
  await page.getByLabel("阅读分钟").fill("160");
  await page.getByLabel("收入（分）").fill("250");
  await page.getByRole("button", { name: "记录数据" }).click();
  await expect(page.getByText("20.0%").first()).toBeVisible();
  await expect(page.getByText("100 曝光")).toBeVisible();
  await expect(page.getByText("¥2.50")).toHaveCount(1);
});

test("explains missing chapter prerequisites and navigates to the next action", async ({ page }) => {
  await page.route(`**/api/projects/${project.id}/workflow-status`, (route) => route.fulfill({ json: { setting_confirmed: false, outline_confirmed: false, volume_one_confirmed: false, commercial_confirmed: false } }));

  await openExistingProject(page);
  await page.getByRole("button", { name: "章节工作台" }).click();

  await expect(page.getByRole("region", { name: "章节生成前置条件" })).toContainText("请先确认故事设定");
  await expect(page.getByRole("button", { name: "Agent 生成章节" })).toBeDisabled();
  await page.getByRole("button", { name: "前往完成" }).click();
  await expect(page.getByRole("heading", { name: "核心设定" })).toBeVisible();
});

test("requires a reason before overriding a low commercial score", async ({ page }) => {
  const dimensions = ["opening_urgency", "reader_promise", "emotional_payoff", "conflict_escalation", "information_clarity", "chapter_hook", "differentiation"];
  const audit = {
    commercial_report: {
      id: "report-1",
      chapter_id: "1",
      total_score: 42,
      recommendation: "revise",
      dimensions: dimensions.map((dimension) => ({ dimension, score: 42, reason: "承诺未兑现" })),
      issues: [{ id: "issue-1", severity: "error", dimension: "reader_promise", description: "正文否定了核心代价", citation: { source: "draft", location: "chars:0-4", quote: "生成正文" }, references: [{ path: "canon/commercial.yaml", location: "full document", quote: "fanqie" }] }],
      references: [{ path: "canon/commercial.yaml", location: "full document", quote: "fanqie" }],
    },
    minimum_commercial_score: 75,
    commercial_gate_passed: false,
  };
  let approvalBody: object | null = null;
  await page.route(`**/api/projects/${project.id}/tasks`, (route) => route.fulfill({ json: [task] }));
  await page.route(`**/api/projects/${project.id}/tasks/${task.id}/drafts`, (route) => route.fulfill({ json: ["chapter.md"] }));
  await page.route(`**/api/projects/${project.id}/drafts/${task.id}`, (route) => route.fulfill({ json: { task_id: task.id, path: "chapter.md", content: "生成正文", revision: "rev-1" } }));
  await page.route(`**/api/projects/${project.id}/commercial/reports/${task.id}`, (route) => route.fulfill({ json: audit }));
  await page.route(`**/api/projects/${project.id}/design/chapters/1/${task.id}/approve`, (route) => {
    approvalBody = route.request().postDataJSON();
    return route.fulfill({ json: { ...task, status: "completed" } });
  });

  await openExistingProject(page);
  await expect(page.getByRole("region", { name: "商业质量审查" })).toContainText("42 / 100");
  const approve = page.getByRole("button", { name: "覆盖门禁并确认" });
  await expect(approve).toBeDisabled();
  await page.getByPlaceholder("说明为什么该章可以低于门槛进入正式稿").fill("编辑确认该章用于节奏对照实验");
  await expect(approve).toBeEnabled();
  await approve.click();
  await expect.poll(() => approvalBody).toEqual({ commercial_override_reason: "编辑确认该章用于节奏对照实验" });
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
