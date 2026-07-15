import { expect, test } from "@playwright/test";

test("keeps the empty workspace usable at compact widths", async ({ page }) => {
  await page.route("**/api/health", (route) => route.fulfill({ json: { status: "ok", service: "tame-ink-api", version: "0.1.0" } }));
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "从一个新故事开始" })).toBeVisible();
  await expect(page.getByRole("button", { name: "新建作品" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "项目导航" })).toBeVisible();
});

