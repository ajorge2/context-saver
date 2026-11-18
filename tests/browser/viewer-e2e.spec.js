import { test, expect } from "@playwright/test";
import { appOrigin, getViewerFixtureAsset } from "./viewer-fixture-assets.js";

const payload = {
  query: "release plan",
  project: { id: "project-one", title: "Project One" },
  layers: {
    subject: [
      { id: "s1", layer: "subject", title: "Launch", summary: "Launch work", memberCount: 2, sourceChatCount: 1, confidence: .9 },
      { id: "s2", layer: "subject", title: "Personal", summary: "Unrelated branch", memberCount: 1, sourceChatCount: 1, confidence: .8 },
    ],
    broad_topic: [
      { id: "b1", layer: "broad_topic", title: "Release planning", summary: "Release details", memberCount: 2, sourceChatCount: 1, confidence: .88 },
      { id: "b2", layer: "broad_topic", title: "Errands", summary: "Unrelated details", memberCount: 1, sourceChatCount: 1, confidence: .7 },
    ],
    specific_topic: [
      { id: "t1", layer: "specific_topic", title: "Staged rollout", summary: "Rollout sequence", memberCount: 1, sourceChatCount: 1, confidence: .82 },
      { id: "t2", layer: "specific_topic", title: "Rollback", summary: "Rollback sequence", memberCount: 1, sourceChatCount: 1, confidence: .8 },
      { id: "t3", layer: "specific_topic", title: "Groceries", summary: "Unrelated", memberCount: 1, sourceChatCount: 1, confidence: .7 },
    ],
    specific_message: [
      { id: "message:m1", layer: "specific_message", title: "Ship ten percent first", summary: "USER: Ship ten percent first", memberCount: 1, sourceChatCount: 1, confidence: .96 },
      { id: "message:m2", layer: "specific_message", title: "Rollback on elevated errors", summary: "ASSISTANT: Roll back on errors", memberCount: 1, sourceChatCount: 1, confidence: .94 },
      { id: "message:m3", layer: "specific_message", title: "Buy tea", summary: "USER: Buy tea", memberCount: 1, sourceChatCount: 1, confidence: .75 },
    ],
  },
  edges: [
    { child_id: "b1", parent_id: "s1" }, { child_id: "b2", parent_id: "s2" },
    { child_id: "t1", parent_id: "b1" }, { child_id: "t2", parent_id: "b1" }, { child_id: "t3", parent_id: "b2" },
    { child_id: "message:m1", parent_id: "t1" }, { child_id: "message:m2", parent_id: "t2" }, { child_id: "message:m3", parent_id: "t3" },
  ],
};

async function boot(page, browsePayload = () => ({ ...payload, query: "" })) {
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    const asset = getViewerFixtureAsset(url);
    if (asset) return route.fulfill({ path: asset });
    if (url.origin === appOrigin && url.pathname === "/favicon.ico") return route.fulfill({ status: 204 });
    return route.abort();
  });
  await page.route("**/api/threads?include_all=1", (route) => route.fulfill({ json: [{ id: "project-one", title: "Project One" }] }));
  await page.route("**/api/connections/refresh-status**", (route) => route.fulfill({ json: { state: "idle" } }));
  await page.route("**/api/explore?**", async (route) => {
    const url = new URL(route.request().url());
    const response = url.searchParams.get("q")
      ? payload
      : browsePayload(url.searchParams);
    await route.fulfill({ json: response });
  });
  await page.route("**/api/node/**", (route) => route.fulfill({ json: {
    id: "s1",
    title: "Launch",
    summary: "USER: Old fragment; ASSISTANT: Another fragment",
    overview: [{ label: "Example question", text: "Should we ship ten percent first?" }],
    member_count: 1,
    message_count: 2,
    source_chat_count: 1,
    parents: [],
    children: [{ id: "b1", title: "Release planning" }],
    sources: [{ text: "USER: Ship ten percent first", chat_title: "Launch planning", verified: true }],
  } }));
  await page.goto(appOrigin);
  await page.locator("[data-hero-combobox] .combobox-trigger").click();
  await page.locator("[data-hero-combobox] .combobox-option").click();
}

async function search(page) {
  let releaseResponse;
  const loadingChecked = new Promise((resolve) => { releaseResponse = resolve; });
  await page.route(
    (url) => url.pathname === "/api/explore" && url.searchParams.get("q") === payload.query,
    async (route) => {
      await loadingChecked;
      await route.fallback();
    },
    { times: 1 },
  );
  try {
    await page.locator("[data-spotlight-input]").fill(payload.query);
    await page.locator("[data-spotlight-input]").press("Enter");
    await expect(page.locator(".slide-down-button--hero")).toHaveClass(/is-loading/);
  } finally {
    releaseResponse();
  }
  await expect(page.locator("[data-hero-down-label]")).toHaveText("View results");
}

test("UX-002/EX-001: committed search populates all four hierarchy layers", async ({ page }) => {
  await boot(page);
  await search(page);
  await expect(page.locator('[data-section="1"] .feature-card')).toHaveCount(2);
  await expect(page.locator('[data-section="4"] .feature-card')).toHaveCount(3);
});

test("FL-006/FL-007: card and dropdown selections share one intersecting filter model", async ({ page }) => {
  await boot(page);
  await search(page);
  await page.locator('[data-section="1"] .feature-card', { hasText: "Launch" }).locator(".feature-card__toggle").click();
  await expect(page.locator('[data-section="1"] .feature-card')).toHaveCount(1);
  await expect(page.locator('[data-section="4"] .feature-card')).toHaveCount(2);
  await expect(page.locator('[data-layer-key="subject"] [data-combobox-value]')).toHaveText("Launch");
  await page.locator('[data-layer-key="specific_message"] .combobox-trigger').click();
  await page.locator('[data-layer-key="specific_message"] .combobox-option', { hasText: "Rollback" }).click();
  await expect(page.locator('[data-section="3"] .feature-card h3')).toHaveText("Rollback");
  await expect(page.locator('[data-section="4"] .feature-card h3')).toHaveText("Rollback on elevated errors");
});

test("MD-001/MD-006: card body opens readable metadata and Escape restores focus", async ({ page }) => {
  await boot(page);
  await search(page);
  await page.getByRole("button", { name: "Go to Subjects" }).click();
  const body = page.locator('[data-section="1"] .feature-card', { hasText: "Launch" }).locator(".feature-card__body");
  await body.click();
  await expect(page.locator("[data-node-detail-overlay]")).toBeVisible();
  await expect(page.locator("[data-node-detail-title]")).toHaveText("Launch");
  const content = page.locator("[data-node-detail-content]");
  await expect(content.locator("blockquote")).toHaveText("Should we ship ten percent first?");
  await expect(content.locator(".node-detail-stat", { hasText: "Messages included" }).locator("strong")).toHaveText("2");
  await expect(content).not.toContainText("Old fragment");
  await page.keyboard.press("Escape");
  await expect(page.locator("[data-node-detail-overlay]")).toBeHidden();
  await expect(body).toBeFocused();
});

test("MD-004: a disconnected topic never falls back to its cached summary", async ({ page }) => {
  await boot(page);
  await page.route("**/api/node/**", (route) => route.fulfill({ status: 404, json: { error: "not found" } }));
  await page.getByRole("button", { name: "Go to Subjects" }).click();
  await page.getByRole("button", { name: "View metadata for Launch" }).click();
  const content = page.locator("[data-node-detail-content]");
  await expect(page.locator("[data-node-detail-title]")).toHaveText("Context no longer available");
  await expect(content).toContainText(/source messages .* are no longer/i);
  await expect(content).not.toContainText("Messages included");
});

test("UX-005/EX-003: clearing the query restores project browse mode", async ({ page }) => {
  await boot(page);
  await search(page);
  await page.locator('[data-section="1"] .feature-card__toggle').first().click();
  await page.locator("[data-spotlight-input]").fill("");
  await expect(page.locator("[data-hero-down-label]")).toHaveText("See what you've been chatting about");
  await expect(page.locator('[data-section="1"] .feature-card')).toHaveCount(2);
  await expect(page.locator('[data-section="4"] .feature-card')).toHaveCount(3);
  await expect(page.locator('[data-layer-key="subject"] [data-combobox-value]')).toHaveText("Select subject...");
});


test("project browsing pages through topics and loads older messages within the selected branch", async ({ page }) => {
  const extraTopics = Array.from({ length: 8 }, (_, index) => ({
    id: `extra-${index}`, layer: "specific_topic", title: `Older topic ${index + 1}`,
  }));
  await boot(page, (params) => {
    const inRollback = params.getAll("browse_node").includes("t2");
    return {
      ...payload,
      query: "",
      layers: {
        ...payload.layers,
        specific_topic: [...extraTopics, ...payload.layers.specific_topic],
        specific_message: [payload.layers.specific_message[inRollback ? 1 : 0]],
      },
      edges: [...payload.edges, ...extraTopics.map((topic) => ({ child_id: topic.id, parent_id: "b1" }))],
    };
  });
  const messages = page.locator('[data-section="4"]');
  await expect(messages.locator(".feature-card h3")).toHaveText("Ship ten percent first");
  await page.getByRole("button", { name: "Go to Specific Topics" }).click();
  const topics = page.locator('[data-section="3"]');
  const pager = topics.getByRole("navigation", { name: "specific topics pages" });
  await expect(topics.locator(".feature-card")).toHaveCount(9);
  await expect(pager.locator(".feature-pagination__status")).toHaveText("1–9 of 11");
  await pager.getByRole("button", { name: "Next", exact: true }).click();
  await expect(topics.locator(".feature-card h3")).toHaveText(["Rollback", "Groceries"]);
  await expect(pager.getByRole("button", { name: "Next", exact: true })).toBeDisabled();
  const branchRequest = page.waitForResponse((response) => new URL(response.url()).searchParams.get("browse_node") === "t2");
  await topics.getByRole("button", { name: "Add Rollback filter" }).click();
  await branchRequest;
  await expect(topics.locator(".feature-card h3")).toHaveText("Rollback");
  await expect(messages.locator(".feature-card h3")).toHaveText("Rollback on elevated errors");
});


test("reloading a lower slide returns to Welcome", async ({ page }) => {
  await boot(page);
  const lowerSlide = page.getByRole("button", { name: "Go to Specific Topics" });
  await lowerSlide.click();
  await expect(lowerSlide).toHaveClass(/is-active/);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Go to Welcome" })).toHaveClass(/is-active/);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await expect(page.locator(".scroll-progress__value")).toHaveCSS("transform", "matrix(0, 0, 0, 1, 0, 0)");
});
