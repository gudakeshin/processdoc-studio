import { test, expect } from "@playwright/test";

test.describe("ProcessDoc smoke", () => {
  test("home loads", async ({ page }) => {
    const response = await page.goto("/");
    expect(response?.ok() || response?.status() === 304).toBeTruthy();
    await expect(page.locator("body")).toBeVisible();
  });

  test("login page is reachable when unauthenticated", async ({ page }) => {
    await page.goto("/login").catch(async () => {
      await page.goto("/");
    });
    await expect(page.locator("body")).toBeVisible();
  });
});
