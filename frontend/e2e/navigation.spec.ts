import { expect, test } from "@playwright/test";

test("keeps the empty workspace usable at compact widths", async ({ page }) => {
  await page.route("**/api/health", (route) =>
    route.fulfill({
      json: { status: "ok", service: "tame-ink-api", version: "0.1.0" },
    }),
  );
  await page.route("**/api/projects", (route) => route.fulfill({ json: [] }));
  await page.goto("/");

  await expect(
    page.getByRole("heading", { name: "项目概览需要一个作品" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "新建作品" }).first()).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "项目导航" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "章节工作台" }).click();
  await expect(
    page.getByRole("heading", { name: "章节工作台需要一个作品" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "模型设置" }).last().click();
  await expect(
    page.getByRole("heading", { name: "模型设置", level: 2 }),
  ).toBeVisible();
  await expect(page.getByLabel("Base URL")).toBeVisible();
});
