import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("explore filters, scale selection and evidence export", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Compare planetary terrain with Earth" })).toBeVisible();
  await page.getByRole("combobox", { name: "Filter Earth region" }).selectOption("namib");
  const names = await page.locator("tbody th button").allTextContents();
  expect(names.length).toBeGreaterThan(0);
  expect(names.every((name) => name.trim().startsWith("NAMIB-"))).toBe(true);
  await page.getByRole("button", { name: "1 km", exact: true }).click();
  await expect(page.getByRole("button", { name: "1 km", exact: true })).toHaveAttribute("aria-pressed", "true");
  const pending = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export evidence", exact: true }).click();
  expect((await pending).suggestedFilename()).toContain("mimesis-jezero-");
});

test("evidence, replication and the paper remain accessible", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Evidence", exact: true }).click();
  await expect(page.getByRole("heading", { name: "The lunar source check fails" })).toBeVisible();
  await page.getByLabel("Lunar site").selectOption("marius");
  await expect(page.getByText("97.37%", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Replication", exact: true }).click();
  await page.getByRole("combobox", { name: "Target", exact: true }).selectOption("nili");
  await expect(page.getByText("0 / 10", { exact: true })).toBeVisible();
  expect((await page.request.get("/research/mimesis-paper.pdf")).ok()).toBe(true);
  expect((await page.request.head("/research/discovery.json.gz")).ok()).toBe(true);
  expect((await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze()).violations).toEqual([]);
});

test("four-page navigation stays usable on the current viewport", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  await expect(navigation.getByRole("button")).toHaveText(["Explore", "Evidence", "Methods", "Data"]);
  for (const name of ["Methods", "Data", "Evidence", "Explore"]) {
    await navigation.getByRole("button", { name, exact: true }).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  expect(errors).toEqual([]);
});
