import { expect, test } from "@playwright/test";

const project = {
  id: "existing-book",
  title: "已有作品",
  language: "zh-CN",
  genre: "悬疑",
  target_words: 800000,
  constraints: "第三人称",
};
const baseTask = {
  project_id: project.id,
  kind: "write",
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
const chapterTask = {
  ...baseTask,
  id: "71b1b146-d37f-4e45-8848-35fde3af15a4",
  purpose: "chapter",
  status: "awaiting_approval",
  subject_id: "2",
  volume_id: "1",
  chapter_id: "2",
};
const failedTask = {
  ...baseTask,
  id: "71b1b146-d37f-4e45-8848-35fde3af15a5",
  purpose: "book_outline",
  status: "failed",
  subject_id: "book",
  volume_id: null,
  chapter_id: null,
  finished_at: "2026-07-15T10:00:01Z",
  duration_ms: 1000,
  error_code: "AGENT_RUN_FAILED",
  error_message: "agent job failed",
};
const snapshot = {
  project,
  documents: [
    {
      path: "canon/world/setting.md",
      kind: "setting",
      title: "城市设定",
      word_count: 100,
      updated_at: "2026-07-15T10:00:00Z",
    },
    {
      path: "canon/outline.md",
      kind: "outline",
      title: "全书大纲",
      word_count: 200,
      updated_at: "2026-07-15T10:00:00Z",
    },
    {
      path: "canon/volumes/1.md",
      kind: "volume",
      title: "第一卷",
      word_count: 100,
      updated_at: "2026-07-15T10:00:00Z",
    },
    {
      path: "canon/chapters/1.md",
      kind: "chapter",
      title: "第一章 雨夜",
      word_count: 1200,
      updated_at: "2026-07-15T10:00:00Z",
    },
  ],
  volumes: [
    {
      id: "1",
      path: "canon/volumes/1.md",
      kind: "volume",
      title: "第一卷",
      word_count: 100,
      updated_at: "2026-07-15T10:00:00Z",
      chapters: [
        {
          id: "1",
          volume_id: "1",
          path: "canon/chapters/1.md",
          kind: "chapter",
          title: "第一章 雨夜",
          word_count: 1200,
          updated_at: "2026-07-15T10:00:00Z",
        },
      ],
    },
  ],
  unassigned_chapters: [],
  stats: {
    total_words: 1200,
    chapter_count: 1,
    volume_count: 1,
    active_foreshadow_count: 2,
  },
};
const commercialProfile = {
  schema_version: 1,
  platform: "fanqie",
  custom_platform: null,
  monetization: "free_ad",
  target_reader: "悬疑读者",
  core_fantasy: "破解不可能犯罪",
  differentiator: "线索反向误导",
  emotional_payoffs: ["识破骗局"],
  opening_promise: "首章发生命案",
  first_thirty_chapter_promise: "破解主案",
  update_cadence: "每日两章",
  title_candidates: ["已有作品"],
  synopsis: "侦探破解密室命案。",
  comparable_titles: [],
  minimum_commercial_score: 75,
  targets: {
    click_through_rate: null,
    chapter_one_completion_rate: null,
    chapter_three_retention_rate: null,
    follow_rate: null,
    revenue_per_thousand_opens_yuan: null,
  },
};
const metrics = {
  observations: 1,
  impressions: 100,
  opens: 20,
  chapter_one_completions: 12,
  chapter_three_completions: 8,
  follows: 4,
  read_minutes: 160,
  revenue_cents: 250,
  click_through_rate: 0.2,
  chapter_one_completion_rate: 0.6,
  chapter_three_retention_rate: 0.4,
  follow_rate: 0.2,
  average_read_minutes_per_open: 8,
  revenue_per_thousand_opens_yuan: 125,
};
const dimensions = [
  "opening_urgency",
  "reader_promise",
  "emotional_payoff",
  "conflict_escalation",
  "information_clarity",
  "chapter_hook",
  "differentiation",
].map((dimension) => ({ dimension, score: 60, reason: "证据不足" }));

test.beforeEach(async ({ page }) => {
  let tasks = [chapterTask, failedTask];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/health")
      return route.fulfill({
        json: { status: "ok", service: "tame-ink-api", version: "0.1.0" },
      });
    if (path === "/api/projects") return route.fulfill({ json: [project] });
    if (path === `/api/projects/${project.id}`)
      return route.fulfill({ json: project });
    if (path.endsWith("/snapshot")) return route.fulfill({ json: snapshot });
    if (path.endsWith("/workflow-status"))
      return route.fulfill({
        json: {
          setting_confirmed: true,
          outline_confirmed: true,
          volume_one_confirmed: true,
          commercial_confirmed: true,
        },
      });
    if (path.endsWith("/tasks")) return route.fulfill({ json: tasks });
    if (path.endsWith("/usage"))
      return route.fulfill({
        json: {
          project_id: project.id,
          model: "model-1",
          request_count: 8,
          input_tokens: 1000,
          output_tokens: 500,
          total_tokens: 1500,
          total_cost_cny: 0.12,
          pricing_configured: true,
        },
      });
    if (path.endsWith("/revisions"))
      return route.fulfill({
        json: [{ id: "a".repeat(40), message: "确认：第一章" }],
      });
    if (path.endsWith("/documents"))
      return route.fulfill({
        json: {
          path: url.searchParams.get("path"),
          content: "# 第一章 雨夜\n\n正式正文。",
          revision: "a".repeat(40),
        },
      });
    if (path.endsWith(`/drafts/${chapterTask.id}`)) {
      const draftPath = url.searchParams.get("path");
      const content =
        draftPath === "plan.md"
          ? "场景一：雨夜命案"
          : draftPath === "audit-reports.json"
            ? JSON.stringify({ continuity: [], style: [] })
            : "# 第二章\n\n候选正文。";
      return route.fulfill({
        json: {
          task_id: chapterTask.id,
          path: draftPath,
          content,
          revision: "a".repeat(40),
        },
      });
    }
    if (path.endsWith(`/commercial/reports/${chapterTask.id}`))
      return route.fulfill({
        json: {
          commercial_report: {
            id: "report-1",
            chapter_id: "2",
            total_score: 60,
            recommendation: "revise",
            dimensions,
            issues: [],
          },
          minimum_commercial_score: 75,
          commercial_gate_passed: false,
        },
      });
    if (path.endsWith(`/tasks/${chapterTask.id}/memory-candidates`))
      return route.fulfill({
        json: [
          {
            stable_id: "rain-clue",
            kind: "foreshadowing",
            operation: "create",
            content: "雨夜线索待回收",
            citation: {
              source: "draft",
              location: "chars:7-11",
              quote: "候选正文",
            },
          },
        ],
      });
    if (path.endsWith(`/tasks/${chapterTask.id}/run`))
      return route.fulfill({
        json: {
          agent_runs: [
            {
              agent: "RetentionAuditor",
              skill: "webnovel-retention",
              skill_sha256: "a".repeat(64),
              stage: "retention-audit",
              source_paths: ["canon/outline.md"],
              queries: [],
              total_characters: 1000,
              duration_ms: 100,
              status: "success",
              error_code: null,
            },
          ],
        },
      });
    if (path.endsWith(`/tasks/${failedTask.id}/run`))
      return route.fulfill({ json: { agent_runs: [] } });
    if (path.endsWith(`/tasks/${failedTask.id}/history`))
      return route.fulfill({
        json: [
          {
            task_id: failedTask.id,
            project_id: project.id,
            sequence: 1,
            type: "task.error",
            timestamp: failedTask.updated_at,
            data: { error_code: "AGENT_RUN_FAILED" },
          },
        ],
      });
    if (path.endsWith(`/tasks/${failedTask.id}/retry`)) {
      const retry = {
        ...failedTask,
        id: "71b1b146-d37f-4e45-8848-35fde3af15a6",
        status: "pending",
        retry_of_task_id: failedTask.id,
        error_code: null,
        error_message: null,
        finished_at: null,
        duration_ms: null,
      };
      tasks = [retry, ...tasks];
      return route.fulfill({ status: 202, json: retry });
    }
    if (path.endsWith(`/design/chapters/2/${chapterTask.id}/approve`))
      return route.fulfill({ json: { ...chapterTask, status: "completed" } });
    if (path.endsWith("/commercial/profile"))
      return route.fulfill({ json: commercialProfile });
    if (path.endsWith("/commercial/metrics"))
      return route.fulfill({ json: metrics });
    if (path.endsWith("/commercial/observations") && request.method() === "GET")
      return route.fulfill({
        json: [
          {
            id: "o1",
            observed_at: "2026-07-15T10:00:00Z",
            impressions: 100,
            opens: 20,
            chapter_one_completions: 12,
            chapter_three_completions: 8,
            follows: 4,
            read_minutes: 160,
            revenue_cents: 250,
          },
        ],
      });
    if (
      path.endsWith("/commercial/observations") &&
      request.method() === "POST"
    )
      return route.fulfill({
        status: 201,
        json: { id: "o2", ...request.postDataJSON() },
      });
    if (path.endsWith("/imports/book"))
      return route.fulfill({
        status: 201,
        json: {
          encoding: "utf-8",
          sha256: "abc",
          size: 100,
          chapters: [
            {
              number: 1,
              title: "旧标题",
              start: { byte: 0, character: 0, line: 1, column: 1 },
              end: { byte: 20, character: 20, line: 3, column: 1 },
            },
          ],
        },
      });
    if (path.endsWith("/imports/book/boundaries"))
      return route.fulfill({
        status: 201,
        json: {
          task: {
            ...chapterTask,
            id: "71b1b146-d37f-4e45-8848-35fde3af15a7",
            purpose: "import",
            subject_id: "book",
          },
          chapters: [],
        },
      });
    if (path.includes("/imports/book/") && path.endsWith("/approve"))
      return route.fulfill({
        json: { ...chapterTask, status: "completed", purpose: "import" },
      });
    if (path.endsWith("/events"))
      return route.fulfill({ contentType: "text/event-stream", body: "" });
    return route.fulfill({
      status: 404,
      json: { error: { code: "NOT_FOUND", message: "not found" } },
    });
  });
});

test("uses real snapshot metrics and deep links", async ({ page }) => {
  await page.goto(`/projects/${project.id}/overview`);
  await expect(page.getByRole("heading", { name: "已有作品" })).toBeVisible();
  await expect(page.getByText("1,200", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "继续写下一章" }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/chapters`));
});

test("shows chapter evidence and requires a truthful low-score override", async ({
  page,
}) => {
  await page.goto(`/projects/${project.id}/chapters/2`);
  await expect(
    page.getByRole("heading", { name: "第 2 章候选" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "商业" }).click();
  await expect(
    page.getByRole("region", { name: "商业质量审查" }),
  ).toContainText("60");
  const confirm = page.getByRole("button", { name: "确认章节" });
  await expect(confirm).toBeDisabled();
  await page.getByLabel("人工覆盖理由").fill("编辑确认用于小流量对照实验");
  await expect(confirm).toBeEnabled();
  await page.getByRole("button", { name: "记忆" }).click();
  await page.getByText("雨夜线索待回收").click();
  const approvalRequest = page.waitForRequest((request) =>
    request.url().endsWith(`/design/chapters/2/${chapterTask.id}/approve`),
  );
  await confirm.click();
  expect((await approvalRequest).postDataJSON()).toEqual({
    commercial_override_reason: "编辑确认用于小流量对照实验",
    accepted_memory_ids: ["rain-clue"],
  });
});

test("records commercial observations from real fields", async ({ page }) => {
  await page.goto(`/projects/${project.id}/commercial`);
  await expect(
    page.getByRole("heading", { name: "番茄首测策略" }),
  ).toBeVisible();
  await expect(page.getByText("20.0%").first()).toBeVisible();
  await page.getByLabel("曝光").fill("200");
  await page.getByRole("button", { name: "记录数据" }).click();
});

test("shows errors and creates linked retries", async ({ page }) => {
  await page.goto(`/projects/${project.id}/runs`);
  await page
    .locator(".run-table article")
    .filter({ hasText: "全书大纲" })
    .getByRole("button")
    .first()
    .click();
  await expect(page.getByText("AGENT_RUN_FAILED").last()).toBeVisible();
  await page.getByRole("button", { name: "重试任务" }).click();
  await expect(page.getByText("等待开始").first()).toBeVisible();
});

test("keeps import preview separate from formal approval", async ({ page }) => {
  await page.goto(`/projects/${project.id}/imports`);
  await page
    .locator('input[type="file"]')
    .setInputFiles({
      name: "book.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("第一章\n正文"),
    });
  await page.getByRole("button", { name: "解析章节" }).click();
  await page.getByLabel("第 1 条标题").fill("新标题");
  await page.getByRole("button", { name: "确认章节边界" }).click();
  await expect(
    page.getByRole("button", { name: "批准并写入正式章节" }),
  ).toBeVisible();
});
