import { expect, test, type Page, type Response } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

test.describe.configure({ mode: "serial", timeout: 600_000 });

const projectId = `live-smoke-${Date.now()}`;

type LiveTask = {
  id: string;
  purpose: string;
  subject_id: string | null;
  chapter_id: string | null;
  status: string;
  error_code: string | null;
  error_message: string | null;
  updated_at: string;
};

function apiPath(path: string) {
  return `/api/projects/${projectId}${path}`;
}

async function expectSuccessful(response: Response, status: number) {
  if (response.status() !== status) {
    throw new Error(`expected HTTP ${status}, received ${response.status()}: ${await response.text()}`);
  }
}

async function waitForAgentTask(page: Page, initial: LiveTask, timeout = 180_000) {
  let current = initial;
  await expect
    .poll(
      async () => {
        const response = await page.request.get(apiPath(`/tasks/${initial.id}`));
        expect(response.ok()).toBeTruthy();
        current = (await response.json()) as LiveTask;
        if (["failed", "cancelled", "interrupted"].includes(current.status)) {
          return `${current.status}:${current.error_code ?? "unknown"}:${current.error_message ?? ""}`;
        }
        const workerStarted =
          initial.status !== "awaiting_approval" || current.updated_at !== initial.updated_at;
        return workerStarted ? current.status : "worker-not-started";
      },
      { timeout, intervals: [500, 1_000, 2_000] },
    )
    .toBe("awaiting_approval");
  return current;
}

async function runAgent(
  page: Page,
  buttonName: string,
  endpoint: (pathname: string) => boolean,
  timeout = 180_000,
) {
  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" && endpoint(new URL(response.url()).pathname),
  );
  await page.getByRole("button", { name: buttonName }).click();
  const response = await responsePromise;
  await expectSuccessful(response, 202);
  return waitForAgentTask(page, (await response.json()) as LiveTask, timeout);
}

async function approveCurrentDraft(page: Page) {
  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname.endsWith("/approve"),
  );
  await page.getByRole("button", { name: "确认当前草稿" }).click();
  const response = await responsePromise;
  await expectSuccessful(response, 200);
  expect(((await response.json()) as LiveTask).status).toBe("completed");
  await expect(page.getByText("正式稿").first()).toBeVisible({ timeout: 30_000 });
}

function redactBaseUrl(value: string) {
  const url = new URL(value);
  return `${url.protocol}//${url.host}${url.pathname}`;
}

test("runs the real setting-to-chapter workflow without API mocks", async ({ page }) => {
  const apiRequests: string[] = [];
  const browserErrors: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/")) apiRequests.push(request.url());
  });
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));

  const healthResponse = await page.request.get("/api/health");
  expect(healthResponse.ok()).toBeTruthy();
  expect(await healthResponse.json()).toMatchObject({ status: "ok", service: "tame-ink-api" });

  await page.goto("/settings");
  const connectionResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/settings/connection",
  );
  await page.getByRole("button", { name: "测试连接" }).click();
  await expectSuccessful(await connectionResponse, 200);
  await expect(page.getByText(/连接正常/)).toBeVisible({ timeout: 60_000 });

  await page.goto("/");
  await page.getByRole("button", { name: "新建作品" }).first().click();
  await page.getByLabel("项目 ID").fill(projectId);
  await page.getByLabel("书名").fill("真实联调样本");
  await page.getByLabel("题材").fill("都市悬疑");
  await page.getByLabel("目标字数").fill("1000000");
  await page.getByLabel("创作约束").fill("第三人称，快节奏，能力有明确代价");
  await page
    .getByLabel("初始设定")
    .fill("主角能识别谎言，但每次使用能力都会永久暴露自己的一段秘密。");
  await page.getByRole("button", { name: "创建并进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "真实联调样本", level: 1 })).toBeVisible();

  const initialSetting = await page.locator(".ProseMirror").innerText();
  await runAgent(
    page,
    "AI 生成候选",
    (pathname) => pathname.startsWith(apiPath("/design/agent/setting/")),
  );
  await expect
    .poll(() => page.locator(".ProseMirror").innerText(), { timeout: 30_000 })
    .not.toBe(initialSetting);
  await approveCurrentDraft(page);

  await page.getByRole("link", { name: "商业增长" }).click();
  await page.getByLabel("核心欲望").fill("破解城市中的隐秘案件并逐步接近真相");
  await page.getByLabel("差异化机制").fill("识别谎言会同步暴露主角自己的秘密");
  const commercialTask = await runAgent(
    page,
    "AI 生成定位",
    (pathname) => pathname === apiPath("/commercial/agent"),
  );
  await expect(page.getByRole("button", { name: "确认商业定位" })).toBeEnabled({
    timeout: 30_000,
  });
  const commercialApproval = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === apiPath(`/commercial/draft/${commercialTask.id}/approve`),
  );
  await page.getByRole("button", { name: "确认商业定位" }).click();
  await expectSuccessful(await commercialApproval, 200);
  await expect(page.getByText("正式定位已确认")).toBeVisible({ timeout: 30_000 });

  await page.getByRole("link", { name: "故事设计" }).click();
  await page.getByRole("tab", { name: "全书大纲" }).click();
  await runAgent(
    page,
    "AI 生成候选",
    (pathname) => pathname === apiPath("/design/agent/outline"),
  );
  await approveCurrentDraft(page);

  await page.getByLabel("新分卷 ID").fill("1");
  await page.getByRole("button", { name: "添加分卷" }).click();
  await expect(page.getByRole("tab", { name: "分卷 1" })).toHaveAttribute("aria-selected", "true");
  await runAgent(
    page,
    "AI 生成候选",
    (pathname) => pathname === apiPath("/design/agent/volumes/1"),
  );
  await approveCurrentDraft(page);

  await page.getByRole("link", { name: "章节工作台" }).click();
  const chapterTask = await runAgent(
    page,
    "Agent 生成章节",
    (pathname) => pathname === apiPath("/design/agent/chapters/1"),
    300_000,
  );
  await page.getByRole("button", { name: "商业" }).click();
  await expect(page.getByRole("region", { name: "商业质量审查" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("达到确认门槛")).toBeVisible({ timeout: 30_000 });

  const reportResponse = await page.request.get(apiPath(`/commercial/reports/${chapterTask.id}`));
  expect(reportResponse.ok()).toBeTruthy();
  const report = await reportResponse.json();
  expect(report.commercial_report.references.length).toBeGreaterThan(0);
  const runResponse = await page.request.get(apiPath(`/tasks/${chapterTask.id}/run`));
  expect(runResponse.ok()).toBeTruthy();
  const run = (await runResponse.json()) as {
    agent_runs: Array<{
      agent: string;
      skill: string;
      skill_sha256: string;
      source_paths: string[];
      status: string;
    }>;
  };
  expect(run.agent_runs.length).toBeGreaterThanOrEqual(7);
  expect(run.agent_runs.some((item) => item.agent === "MemoryCurator")).toBeTruthy();
  expect(run.agent_runs.every((item) => item.status === "success")).toBeTruthy();
  expect(run.agent_runs.every((item) => /^[0-9a-f]{64}$/.test(item.skill_sha256))).toBeTruthy();
  expect(run.agent_runs.every((item) => item.source_paths.length > 0)).toBeTruthy();
  await page.getByRole("button", { name: "来源" }).click();
  await expect(page.getByText("RetentionAuditor").first()).toBeVisible();
  await expect(page.getByText(/webnovel-retention/).first()).toBeVisible();

  const chapterApproval = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname === apiPath(`/design/chapters/1/${chapterTask.id}/approve`),
  );
  await page.getByRole("button", { name: "确认章节" }).click();
  await expectSuccessful(await chapterApproval, 200);
  await expect
    .poll(async () => {
      const response = await page.request.get(apiPath(`/tasks/${chapterTask.id}`));
      return ((await response.json()) as LiveTask).status;
    })
    .toBe("completed");

  expect(apiRequests.length).toBeGreaterThan(10);
  expect(browserErrors).toEqual([]);

  const root = resolve(process.cwd(), "..");
  const workspacePath = (
    await readFile(resolve(root, "output/live/e2e-workspace-path.txt"), "utf8")
  ).trim();
  const projectPath = resolve(workspacePath, "projects", projectId);
  const chapter = await readFile(resolve(projectPath, "canon/chapters/1.md"), "utf8");
  expect(chapter.trim()).not.toBe("");
  expect((await readFile(resolve(projectPath, ".git/refs/heads/main"), "utf8")).trim()).toMatch(
    /^[0-9a-f]{40}$/,
  );
  const usagePath = (
    await readFile(resolve(root, "output/live/e2e-usage-path.txt"), "utf8")
  ).trim();
  const usage = await readFile(usagePath, "utf8");
  const events = usage
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as { total_cost_cny: number | null });
  expect(events.length).toBeGreaterThanOrEqual(11);
  expect(events.every((event) => event.total_cost_cny !== null)).toBeTruthy();
  const totalCost = events.reduce((sum, event) => sum + (event.total_cost_cny ?? 0), 0);
  const maxCost = Number(process.env.TAME_INK_MAX_COST_CNY ?? "20");
  expect(totalCost).toBeLessThanOrEqual(maxCost);
  const settingsResponse = await page.request.get("/api/settings");
  expect(settingsResponse.ok()).toBeTruthy();
  const settings = (await settingsResponse.json()) as { model: string; base_url: string };
  await writeFile(
    resolve(root, "output/live/e2e-report.json"),
    `${JSON.stringify(
      {
        status: "passed",
        run_id: process.env.TAME_INK_RUN_ID ?? null,
        model: settings.model,
        base_url: redactBaseUrl(settings.base_url),
        project_id: projectId,
        request_count: events.length,
        agent_run_count: run.agent_runs.length,
        skills: [...new Set(run.agent_runs.map((item) => item.skill))],
        total_cost_cny: totalCost,
        max_cost_cny: maxCost,
        usage_log: usagePath,
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
});
