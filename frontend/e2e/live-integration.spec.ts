import { expect, test, type Page } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

test.describe.configure({ mode: "serial", timeout: 300_000 });

const projectId = `live-smoke-${Date.now()}`;

async function approveCurrentDraft(page: Page) {
  await page.getByRole("button", { name: "确认当前草稿" }).click();
  await expect(page.getByText("已确认").first()).toBeVisible({ timeout: 30_000 });
}

test("runs the real setting-to-chapter workflow without API mocks", async ({ page }) => {
  const apiRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) apiRequests.push(request.url());
  });

  await page.goto("/");
  await page.getByRole("button", { name: "模型设置" }).click();
  await page.getByRole("button", { name: "测试连接" }).click();
  await expect(page.getByText("连接正常")).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: "项目概览" }).click();
  await page.getByRole("button", { name: "新建作品" }).click();
  await page.getByLabel("项目 ID").fill(projectId);
  await page.getByLabel("书名").fill("真实联调样本");
  await page.getByLabel("题材").fill("都市悬疑");
  await page.getByLabel("目标字数").fill("1000000");
  await page.getByLabel("创作约束").fill("第三人称，快节奏，能力有明确代价");
  await page.getByRole("button", { name: "创建并进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "真实联调样本", level: 2 })).toBeVisible();

  await page.getByRole("button", { name: "AI 重新生成" }).click();
  await expect(page.locator(".ProseMirror")).not.toContainText("从核心冲突");
  await approveCurrentDraft(page);

  await page.getByRole("button", { name: "AI 生成全书大纲" }).click();
  await expect(page.getByRole("heading", { name: "全书大纲" })).toBeVisible();
  await approveCurrentDraft(page);

  await page.getByRole("button", { name: "AI 规划第一卷" }).click();
  await expect(page.getByRole("heading", { name: "第一卷规划" })).toBeVisible();
  await approveCurrentDraft(page);

  await page.getByRole("button", { name: "商业增长" }).click();
  await page.getByLabel("核心欲望").fill("破解城市中的隐秘案件并逐步接近真相");
  await page.getByLabel("差异化机制").fill("主角能识别谎言，但每次使用都会暴露自己的秘密");
  await page.getByRole("button", { name: "AI 生成定位" }).click();
  await expect(page.getByRole("button", { name: "确认商业定位" })).toBeEnabled({ timeout: 60_000 });
  await page.getByRole("button", { name: "确认商业定位" }).click();
  await expect(page.getByText("正式定位已确认")).toBeVisible({ timeout: 30_000 });

  await page.getByRole("button", { name: "章节工作台" }).click();
  await page.getByRole("button", { name: "Agent 生成章节" }).click();
  await expect(page.getByRole("region", { name: "商业质量审查" })).toBeVisible({ timeout: 180_000 });
  await expect(page.getByText("达到确认门槛")).toBeVisible({ timeout: 30_000 });

  const tasksResponse = await page.request.get(`/api/projects/${projectId}/tasks`);
  expect(tasksResponse.ok()).toBeTruthy();
  const tasks = (await tasksResponse.json()) as Array<{ id: string; status: string }>;
  const chapterTask = tasks[0];
  expect(chapterTask.status).toBe("awaiting_approval");
  const reportResponse = await page.request.get(
    `/api/projects/${projectId}/commercial/reports/${chapterTask.id}`,
  );
  expect(reportResponse.ok()).toBeTruthy();
  const report = await reportResponse.json();
  expect(report.commercial_report.references.length).toBeGreaterThan(0);

  await page.getByRole("button", { name: "确认章节" }).click();
  await expect.poll(async () => {
    const response = await page.request.get(`/api/projects/${projectId}/tasks/${chapterTask.id}`);
    return ((await response.json()) as { status: string }).status;
  }, { timeout: 30_000 }).toBe("completed");

  expect(apiRequests.length).toBeGreaterThan(10);
  expect(apiRequests.every((url) => new URL(url).pathname.startsWith("/api/"))).toBeTruthy();

  const root = resolve(process.cwd(), "..");
  const workspacePath = (await readFile(resolve(root, "output/live/e2e-workspace-path.txt"), "utf8")).trim();
  const chapter = await readFile(resolve(workspacePath, "projects", projectId, "canon/chapters/1.md"), "utf8");
  expect(chapter.trim()).not.toBe("");
  const usagePath = (await readFile(resolve(root, "output/live/e2e-usage-path.txt"), "utf8")).trim();
  const usage = await readFile(usagePath, "utf8");
  const events = usage.trim().split("\n").map((line) => JSON.parse(line) as { total_cost_cny: number | null });
  expect(events.length).toBeGreaterThanOrEqual(10);
  expect(events.every((event) => event.total_cost_cny !== null)).toBeTruthy();
  const totalCost = events.reduce((sum, event) => sum + (event.total_cost_cny ?? 0), 0);
  const maxCost = Number(process.env.TAME_INK_MAX_COST_CNY ?? "20");
  expect(totalCost).toBeLessThanOrEqual(maxCost);
  const settingsResponse = await page.request.get("/api/settings");
  expect(settingsResponse.ok()).toBeTruthy();
  const settings = (await settingsResponse.json()) as { model: string; base_url: string };
  await writeFile(resolve(root, "output/live/e2e-report.json"), `${JSON.stringify({
    status: "passed",
    run_id: process.env.TAME_INK_RUN_ID ?? null,
    model: settings.model,
    base_url: settings.base_url,
    project_id: projectId,
    request_count: events.length,
    total_cost_cny: totalCost,
    max_cost_cny: maxCost,
    usage_log: usagePath,
  }, null, 2)}\n`, "utf8");
});
