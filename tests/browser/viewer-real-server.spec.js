import { execFile, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { once } from "node:events";
import { readFile } from "node:fs/promises";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { test, expect } from "@playwright/test";

const python = process.env.CONTEXT_SAVER_TEST_PYTHON || "python";
const fixture = fileURLToPath(new URL("../viewer_browser_fixture.py", import.meta.url));
const run = promisify(execFile);

test.use({ reducedMotion: "reduce" });

async function usingViewer(callback, options = []) {
  const server = spawn(python, [fixture, ...options], {
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
  });
  const exited = once(server, "exit");
  let stderr = "";
  server.stderr.setEncoding("utf8");
  server.stderr.on("data", (data) => { stderr += data; });
  const lines = createInterface({ input: server.stdout });
  try {
    const info = await Promise.race([
      once(lines, "line").then(([line]) => JSON.parse(line)),
      exited.then(([code]) => { throw new Error(`Fixture exited with ${code}: ${stderr}`); }),
    ]);
    await callback(info);
  } finally {
    lines.close();
    if (server.exitCode === null && server.signalCode === null) server.kill("SIGTERM");
    await exited.catch(() => {});
  }
}

test("EX-E2E-01: real viewer browses scoped SQLite, opens evidence, and leaves durable rows unchanged", async ({ page }) => {
  await usingViewer(async (info) => {
    await page.goto(info.origin);
    await page.getByRole("combobox", { name: "Select project" }).click();
    await expect(page.getByRole("option", { name: "Selected fixture" })).toBeVisible();
    await expect(page.getByRole("option", { name: "Unselected fixture" })).toHaveCount(0);
    await page.getByRole("option", { name: "Selected fixture" }).click();
    const search = page.getByRole("searchbox", { name: "Search Context in Selected fixture" });
    await search.fill("durabilityproof901");
    await search.press("Enter");
    await expect(page.getByRole("button", { name: "View results" })).toBeEnabled();
    await page.getByRole("button", { name: "Go to Specific Messages" }).click();
    await page.getByRole("button", { name: /View metadata for .*Nimbus Blue/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.locator("blockquote")).toContainText("Nimbus Blue");
    await expect(dialog).not.toContainText("Violet Quartz");
    await expect(dialog.locator(".node-detail-stat", { hasText: "Messages included" }).locator("strong")).toHaveText("1");
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);

    const excluded = await page.request.get(`${info.origin}/api/explore`, {
      params: { q: "durabilityproof901", thread_id: info.excludedProject },
    });
    expect(await excluded.text()).not.toContain("Violet Quartz");
    const result = await run(python, [fixture, "--snapshot", info.db]);
    expect(result.stdout.trim()).toBe(info.digest);
  });
});

test("CN-E2E-01: a real disconnect survives a failed worker launch, reload, and successful memory retry", async ({ page }) => {
  await usingViewer(async (info) => {
    await page.goto(info.origin);
    const manager = page.getByRole("button", { name: "Manage connections" });
    await manager.click();
    const panel = page.getByRole("dialog", { name: "Connections" });
    const disconnected = panel.locator(".connection-row--chat").filter({ hasText: "Nimbus lookup" });
    await disconnected.getByRole("button", { name: "Disconnect", exact: true }).click();
    const confirmation = page.getByRole("alertdialog");
    await confirmation.getByRole("button", { name: "Disconnect", exact: true }).click();
    await expect(confirmation).toHaveAccessibleName(/successfully disconnected/);
    await confirmation.getByRole("button", { name: "Done" }).click();
    await page.reload();
    await manager.click();
    const retry = panel.getByRole("button", { name: "Retry memory update" });
    await expect(retry).toBeVisible();
    const outcome = page.waitForResponse((response) =>
      response.url().includes("/api/connections/refresh-status?job=") && response.ok()
      && response.json().then((data) => data.state === "complete"),
    );
    await retry.click();
    await outcome;
    await expect(page.locator("body")).toHaveAttribute("aria-busy", "false");
    await manager.click();
    await expect(retry).toBeHidden();
    await expect(panel).not.toContainText("Nimbus lookup");
    await expect(panel).toContainText("Amber follow-up");
    const check = async (q) => {
      const response = await page.request.get(`${info.origin}/api/explore`, { params: { q, thread_id: info.selectedProject } });
      expect(response.ok()).toBe(true);
      return response.text();
    };
    expect(await check("durabilityproof901")).not.toContain("Nimbus Blue");
    expect(await check("Amber Glass")).toContain("Amber Glass");
    for (const [path, hash] of info.sources) {
      expect(createHash("sha256").update(await readFile(path)).digest("hex")).toBe(hash);
    }
  }, ["--fail-first-refresh"]);
});

test("EX-E2E-02: blank browse reaches every SQLite message beyond search's 80-result cap", async ({ page }) => {
  await usingViewer(async (info) => {
    const expected = info.browseMessageIds;
    expect(expected.length).toBeGreaterThan(100);
    const initial = await page.request.get(`${info.origin}/api/explore`, { params: { q: "", thread_id: info.selectedProject } });
    const initialData = await initial.json();
    expect(initialData.layers.specific_message).toHaveLength(36);
    expect(initialData.messagePage.total).toBe(expected.length);
    await page.goto(info.origin);
    await page.getByRole("combobox", { name: "Select project" }).click();
    await page.getByRole("option", { name: "Selected fixture" }).click();
    await page.getByRole("button", { name: "Go to Specific Messages" }).click();
    const messages = page.locator('[data-section="4"]');
    const pager = messages.getByRole("navigation", { name: "specific messages pages" });
    const status = pager.locator(".feature-pagination__status");
    await expect(status).toHaveText(`1–9 of ${expected.length}`);
    const seen = [];
    for (let offset = 0; offset < expected.length; offset += 9) {
      await expect(status).toHaveText(`${offset + 1}–${Math.min(offset + 9, expected.length)} of ${expected.length}`);
      const ids = await messages.locator(".feature-card").evaluateAll((cards) => cards.map((card) => card.dataset.nodeId));
      expect(ids).toEqual(expected.slice(offset, offset + 9));
      seen.push(...ids);
      if (offset + 9 < expected.length) await pager.getByRole("button", { name: "Next", exact: true }).click();
    }
    expect(new Set(seen).size).toBe(expected.length);
    expect(seen.at(-1)).toBe(expected.at(-1));
    await expect(pager.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
    await pager.getByRole("button", { name: "Previous", exact: true }).click();
    const previousOffset = Math.floor((expected.length - 1) / 9) * 9 - 9;
    await expect(status).toHaveText(`${previousOffset + 1}–${previousOffset + 9} of ${expected.length}`);
    await expect(messages.locator(".feature-card").first()).toHaveAttribute("data-node-id", expected[previousOffset]);

    await page.getByRole("button", { name: "Go to Welcome" }).click();
    const search = page.getByRole("searchbox", { name: "Search Context in Selected fixture" });
    await search.fill("optimization");
    await search.press("Enter");
    await expect(page.getByRole("button", { name: "View results" })).toBeEnabled();
    await expect(status).toHaveText("1–9 of 80");
    const searchResponse = await page.request.get(`${info.origin}/api/explore`, { params: { q: "optimization", thread_id: info.selectedProject } });
    const searchData = await searchResponse.json();
    expect(searchData.layers.specific_message).toHaveLength(80);
    expect(searchData.layers.specific_message.every((message) => seen.includes(message.id))).toBe(true);
    await search.fill("");
    await expect(status).toHaveText(`1–9 of ${expected.length}`);
    await expect(messages.locator(".feature-card").first()).toHaveAttribute("data-node-id", expected[0]);
    expect((await run(python, [fixture, "--snapshot", info.db])).stdout.trim()).toBe(info.digest);
  }, ["--large-browse"]);
});
