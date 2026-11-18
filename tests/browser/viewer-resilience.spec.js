import { test, expect } from "@playwright/test";
import { appOrigin, getViewerFixtureAsset } from "./viewer-fixture-assets.js";

test.use({ reducedMotion: "reduce", serviceWorkers: "block" });

const projects = [{ id: "alpha", title: "Alpha project" }, { id: "beta", title: "Beta project" }];
const layerNames = ["subject", "broad_topic", "specific_topic", "specific_message"];
const browseLabel = "See what you've been chatting about";

function branch(project, label, query = "") {
  const nodes = layerNames.map((layer, index) => ({
    id: `${project}-${index}`,
    layer,
    title: `${label} ${layer.replaceAll("_", " ")}`,
    summary: `Summary for ${label}`,
  }));
  const visible = query ? nodes : nodes.slice(0, 3);
  return {
    query,
    project: { id: project },
    layers: Object.fromEntries(layerNames.map((layer) => [layer, visible.filter((node) => node.layer === layer)])),
    edges: visible.slice(1).map((node, index) => ({ child_id: node.id, parent_id: visible[index].id })),
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((settle) => { resolve = settle; });
  return { promise, resolve };
}

// Hold the response until the test deliberately releases it. A separate
// arrival signal lets the test assert browser state with the request in flight.
function responseGate() {
  const requestArrived = deferred();
  const released = deferred();
  return {
    arrived: requestArrived.promise,
    release: released.resolve,
    async reply(request) {
      requestArrived.resolve(request);
      return released.promise;
    },
  };
}

async function boot(page, { explore, metadata, refreshStatus, refreshRetry, connectionAction, connections = [], projectList = projects } = {}) {
  const requests = [];
  const unexpected = [];
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === appOrigin && url.pathname === "/api/connections/action" && request.method() === "POST" && connectionAction) {
      return route.fulfill(await connectionAction(request));
    }
    if (url.origin === appOrigin && url.pathname === "/api/connections/refresh-retry" && request.method() === "POST" && refreshRetry) {
      return route.fulfill(await refreshRetry(request));
    }
    if (request.method() !== "GET" || url.origin !== appOrigin) {
      unexpected.push([request.method(), url.pathname]);
      return route.abort();
    }
    const asset = getViewerFixtureAsset(url);
    if (asset) return route.fulfill({ path: asset });
    if (url.pathname === "/favicon.ico") return route.fulfill({ status: 204 });
    if (url.pathname === "/api/threads") return route.fulfill({ json: projectList });
    if (url.pathname === "/api/connections/refresh-status") {
      const override = await refreshStatus?.(url.searchParams.get("job"), request);
      return route.fulfill(override || { json: { state: "idle" } });
    }
    if (url.pathname === "/api/connections") return route.fulfill({ json: { connections } });
    if (url.pathname === "/api/explore") {
      const query = url.searchParams.get("q");
      const project = url.searchParams.get("thread_id");
      const entry = { query, project };
      requests.push(entry);
      const override = await explore?.(entry, request);
      if (override === "abort") return route.abort();
      return route.fulfill(override || { json: branch(project, project === "alpha" ? "Alpha" : "Beta", query) });
    }
    if (url.pathname.startsWith("/api/node/")) {
      const id = decodeURIComponent(url.pathname.slice("/api/node/".length));
      const override = await metadata?.({ id, query: Object.fromEntries(url.searchParams) }, request);
      if (override === "abort") return route.abort();
      return route.fulfill(override || { json: { display_title: `Details for ${id}` } });
    }
    unexpected.push([request.method(), url.pathname]);
    return route.abort();
  });
  await page.goto(appOrigin);
  return { requests, unexpected, pageErrors };
}

const search = (page) => page.locator("[data-spotlight-input]");
const heroButton = (page) => page.locator(".slide-down-button--hero");
const subjectCards = (page) => page.locator('[data-section="1"] .feature-card h3');
const resultHeadings = (page) => page.locator(".result-query-heading");
const searchStatus = (page) => page.locator("[data-spotlight]").getByRole("status");
const dialog = (page) => page.getByRole("dialog", { name: /./ });
const details = (page) => page.getByRole("region", { name: "Conversation details" });

async function chooseProject(page, name) {
  await page.getByRole("combobox", { name: "Select project" }).click();
  await page.getByRole("option", { name }).click();
}

async function submit(page, query) {
  await search(page).fill(query);
  await search(page).press("Enter");
}

async function openSlide(page, name) {
  const dot = page.getByRole("button", { name: `Go to ${name}` });
  await dot.click();
  await expect(dot).toHaveClass(/is-active/);
}

async function releaseResponse(page, gate, payload) {
  const request = await gate.arrived;
  gate.release(payload);
  const response = await request.response();
  if (response) await response.finished();
  // Wait for the page to process the body before asserting that a completed
  // stale response had no visible effect.
  await page.evaluate(() => new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  }));
}

test("CN-RECOVER-01: a reloaded view exposes a pending disconnect and confirms before retry", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = await boot(page, {
    connections: [{
      id: "fixture", path: "/fixture/project", name: "Fixture project", status: "connected", chatCount: 1,
      chats: [{ id: "fixture-chat", title: "Fixture chat", status: "paused", disconnectPending: true }],
    }],
  });
  await page.getByRole("button", { name: "Manage connections" }).click();
  const panel = page.getByRole("dialog", { name: "Connections" });
  await expect(panel.getByRole("tab", { name: /^Paused/ })).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByText("Disconnection pending", { exact: true })).toBeVisible();
  await expect(panel.getByText("Lookups share matching excerpts with your coding agent session.", { exact: false })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Resume", exact: true })).toHaveCount(0);
  await panel.getByRole("button", { name: "Retry disconnect" }).click();
  await expect(page.getByRole("alertdialog")).toHaveAccessibleName("Disconnect this connection?");
  expect(state.unexpected).toEqual([]);
  expect(state.pageErrors).toEqual([]);
});

test("CN-RECOVER-02: a failed disconnect stays visible in the confirmation and can be retried", async ({ page }) => {
  const first = responseGate();
  let attempts = 0;
  const state = await boot(page, {
    connections: [{ id: "fixture", path: "/fixture/project", name: "Fixture project", status: "connected", chatCount: 0, chats: [] }],
    connectionAction: (request) => {
      expect(request.postDataJSON()).toMatchObject({ action: "disconnect", kind: "project", projectPath: "/fixture/project" });
      attempts += 1;
      return attempts === 1 ? first.reply(request) : { json: { ok: true, connections: [] } };
    },
  });
  await page.getByRole("button", { name: "Manage connections" }).click();
  await page.getByRole("dialog", { name: "Connections" }).getByRole("button", { name: "Disconnect", exact: true }).click();
  const confirmation = page.getByRole("alertdialog");
  await expect(confirmation.getByRole("button", { name: "Keep connected" })).toBeFocused();
  await confirmation.getByRole("button", { name: "Disconnect", exact: true }).click();
  await first.arrived;
  await page.keyboard.press("Escape");
  await expect(confirmation).toBeVisible();
  await expect(confirmation.getByRole("button", { name: "Keep connected" })).toBeDisabled();
  await releaseResponse(page, first, { status: 500, json: { error: "Synthetic storage failure" } });
  await expect(confirmation.getByRole("alert")).toBeVisible();
  await expect(confirmation.getByRole("alert")).toContainText("Try disconnecting again");
  await confirmation.getByRole("button", { name: "Disconnect", exact: true }).click();
  await expect(confirmation).toHaveAccessibleName("Fixture project successfully disconnected");
  await expect(confirmation.getByRole("alert")).toBeHidden();
  await expect(confirmation.getByRole("button", { name: "Done" })).toBeFocused();
  expect(attempts).toBe(2);
  expect(state.pageErrors).toEqual([]);
});

test("CN-RECOVER-03: a failed memory update discovered after reload can be retried without disconnecting again", async ({ page }) => {
  const completed = responseGate();
  let attempts = 0;
  let finished = false;
  const jobId = "refresh-fixture";
  const state = await boot(page, {
    refreshStatus: (job, request) => {
      if (job === jobId) return completed.reply(request);
      return { json: finished ? { state: "idle" } : { id: jobId, state: "failed", retryable: true } };
    },
    refreshRetry: (request) => {
      expect(request.postDataJSON()).toEqual({ jobId });
      attempts += 1;
      return attempts === 1 ? { status: 503, json: { error: "try later" } } : { json: { id: jobId, state: "queued" } };
    },
  });
  await page.reload();
  await page.getByRole("button", { name: "Manage connections" }).click();
  const panel = page.getByRole("dialog", { name: "Connections" });
  const retry = panel.getByRole("button", { name: "Retry memory update" });
  await expect(panel.getByText("The memory update could not be completed.")).toBeVisible();
  await retry.click();
  await expect(panel.getByText("The memory update could not be started. Try again.")).toBeVisible();
  await retry.click();
  await completed.arrived;
  const busy = page.getByRole("status", { name: "Refreshing Context Saver" });
  await expect(page.locator("body")).toHaveAttribute("aria-busy", "true");
  await expect(busy).toBeFocused();
  await expect(page.locator("main")).toHaveJSProperty("inert", true);
  finished = true;
  await releaseResponse(page, completed, { json: { id: jobId, state: "complete" } });
  await expect(page.locator("body")).toHaveAttribute("aria-busy", "false");
  await page.getByRole("button", { name: "Manage connections" }).click();
  await expect(retry).toBeHidden();
  expect(attempts).toBe(2);
  expect(state.unexpected).toEqual([]);
  expect(state.pageErrors).toEqual([]);
});

test("EX-RACE-01: stale browse success never replaces the selected project", async ({ page }) => {
  const old = responseGate();
  const state = await boot(page, { explore: ({ project }, request) => project === "alpha" ? old.reply(request) : undefined });
  await chooseProject(page, "Alpha project");
  await old.arrived;
  await chooseProject(page, "Beta project");
  await expect(subjectCards(page)).toHaveText(["Beta subject"]);
  await releaseResponse(page, old, { json: branch("alpha", "Stale Alpha") });
  await expect(subjectCards(page)).toHaveText(["Beta subject"]);
  expect(state.unexpected).toEqual([]);
  expect(state.pageErrors).toEqual([]);
});

test("EX-RACE-02: stale browse HTTP failure never clears a newer project", async ({ page }) => {
  const old = responseGate();
  await boot(page, { explore: ({ project }, request) => project === "alpha" ? old.reply(request) : undefined });
  await chooseProject(page, "Alpha project");
  await old.arrived;
  await chooseProject(page, "Beta project");
  await expect(subjectCards(page)).toHaveText(["Beta subject"]);
  await releaseResponse(page, old, { status: 503, json: { error: "old browse failed" } });
  await expect(subjectCards(page)).toHaveText(["Beta subject"], { timeout: 1000 });
});

test("EX-RACE-03: switching projects during search never commits the old query to the new project", async ({ page }) => {
  const old = responseGate();
  await boot(page, { explore: ({ query }, request) => query === "alpha notes" ? old.reply(request) : undefined });
  await chooseProject(page, "Alpha project");
  await expect(subjectCards(page)).toHaveText(["Alpha subject"]);
  await submit(page, "alpha notes");
  await old.arrived;
  await expect(heroButton(page)).toHaveAttribute("aria-busy", "true");
  await chooseProject(page, "Beta project");
  await expect(subjectCards(page)).toHaveText(["Beta subject"]);
  await releaseResponse(page, old, { json: branch("alpha", "Alpha secret", "alpha notes") });
  await expect(subjectCards(page)).toHaveText(["Beta subject"]);
  await expect(heroButton(page)).not.toHaveAttribute("aria-busy", "true");
  await expect(heroButton(page)).toHaveAccessibleName(browseLabel, { timeout: 1000 });
  await expect(search(page)).toHaveValue("");
  for (const heading of await resultHeadings(page).all()) {
    await expect(heading).toBeHidden();
    await expect(heading).not.toContainText("alpha notes");
  }
});

for (const [label, reply] of [
  ["200", { json: branch("alpha", "Browse only") }],
  ["503", { status: 503, json: { error: "old browse failed" } }],
]) {
  test(`EX-RACE-04: delayed browse ${label} cannot change a newer search in the same project`, async ({ page }) => {
    const browse = responseGate();
    await boot(page, { explore: ({ query }, request) => query === "" ? browse.reply(request) : { json: branch("alpha", "Matched", query) } });
    await chooseProject(page, "Alpha project");
    await browse.arrived;
    await submit(page, "bounded");
    await expect(heroButton(page)).toHaveAccessibleName("View results");
    await expect(subjectCards(page)).toHaveText(["Matched subject"]);
    await releaseResponse(page, browse, reply);
    await expect(subjectCards(page)).toHaveText(["Matched subject"]);
    await expect(page.locator('[data-section="4"] .feature-card h3')).toHaveText(["Matched specific message"]);
  });
}

test("EX-RACE-05: clearing the project while browse is pending cannot restore its cards", async ({ page }) => {
  const old = responseGate();
  await boot(page, { explore: (_entry, request) => old.reply(request) });
  await chooseProject(page, "Alpha project");
  await old.arrived;
  await page.locator("[data-hero-combobox]").getByRole("button", { name: "Clear selection" }).click();
  await expect(search(page)).toHaveAccessibleName("Search Context");
  await releaseResponse(page, old, { json: branch("alpha", "Sensitive Alpha") });
  await expect(subjectCards(page)).toHaveCount(0);
  await expect(page.locator('[data-section="1"] .feature-empty')).toContainText("Choose a project to get started");
});

test("EX-RACE-06: an obsolete search cannot unlock the current project's pending search", async ({ page }) => {
  const alpha = responseGate();
  const beta = responseGate();
  const state = await boot(page, {
    explore: ({ query, project }, request) => query ? (project === "alpha" ? alpha : beta).reply(request) : undefined,
  });
  await chooseProject(page, "Alpha project");
  await expect(subjectCards(page)).toHaveText(["Alpha subject"]);
  await submit(page, "private Alpha query");
  await alpha.arrived;
  await chooseProject(page, "Beta project");
  await expect(subjectCards(page)).toHaveText(["Beta subject"]);
  await expect(search(page)).toHaveJSProperty("readOnly", false);
  await submit(page, "current Beta query");
  await beta.arrived;
  await releaseResponse(page, alpha, { status: 503, json: { error: "private obsolete error" } });
  await expect(search(page)).toHaveJSProperty("readOnly", true);
  await expect(heroButton(page)).toHaveAttribute("aria-busy", "true");
  await expect(heroButton(page)).toBeDisabled();
  await expect(searchStatus(page)).not.toContainText(/unavailable|obsolete/i);
  await releaseResponse(page, beta, { json: branch("beta", "Matched Beta", "current Beta query") });
  await expect(subjectCards(page)).toHaveText(["Matched Beta subject"]);
  await expect(resultHeadings(page)).toHaveText(Array(4).fill("current Beta query"));
  expect(state.requests.filter(({ query }) => query)).toEqual([
    { project: "alpha", query: "private Alpha query" },
    { project: "beta", query: "current Beta query" },
  ]);
  expect(state.unexpected).toEqual([]);
});

test("EX-FAIL-01: an active search failure unlocks navigation, retains committed results and permits retry", async ({ page }) => {
  let attempts = 0;
  const failure = responseGate();
  const state = await boot(page, {
    explore: ({ query }, request) => {
      if (query !== "retry this") return { json: branch("alpha", query ? "First search" : "Browse", query) };
      attempts += 1;
      return attempts === 1 ? failure.reply(request) : { json: branch("alpha", "Recovered", query) };
    },
  });
  await chooseProject(page, "Alpha project");
  await submit(page, "first query");
  await expect(subjectCards(page)).toHaveText(["First search subject"]);
  await submit(page, "retry this");
  await failure.arrived;
  await expect(search(page)).toHaveJSProperty("readOnly", true);
  await expect(heroButton(page)).toBeDisabled();
  for (const dot of await page.locator("[data-section-index]").all()) await expect(dot).toBeDisabled();
  await search(page).press("Enter");
  await releaseResponse(page, failure, { status: 503, json: { error: "service unavailable" } });
  await expect(search(page)).toHaveJSProperty("readOnly", false);
  await expect(heroButton(page)).toBeEnabled();
  await expect(heroButton(page)).toHaveAccessibleName("View results");
  await expect(searchStatus(page)).toBeVisible();
  await expect(searchStatus(page)).toContainText(/unavailable|try again/i);
  await expect(searchStatus(page)).not.toContainText("service unavailable");
  await expect(subjectCards(page)).toHaveText(["First search subject"]);
  await expect(resultHeadings(page)).toHaveText(Array(4).fill("first query"));
  expect(state.requests.filter(({ query }) => query === "retry this")).toHaveLength(1);
  await search(page).press("Enter");
  await expect(subjectCards(page)).toHaveText(["Recovered subject"]);
  await expect(resultHeadings(page)).toHaveText(Array(4).fill("retry this"));
  await expect(searchStatus(page)).toHaveText("");
  expect(state.requests.filter(({ query }) => query === "retry this")).toHaveLength(2);
  expect(state.pageErrors).toEqual([]);
});

test("EX-EMPTY-01: no-hit results clear the prior branch completely and clearing restores browse", async ({ page }) => {
  await boot(page, {
    explore: ({ query }) => query === "ไม่มีผลลัพธ์ + < >" ? {
      json: { query, project: { id: "alpha" }, layers: {}, edges: [] },
    } : undefined,
  });
  await chooseProject(page, "Alpha project");
  await submit(page, "first match");
  await expect(page.locator('[data-section="4"] .feature-card h3')).toHaveText(["Alpha specific message"]);
  await submit(page, "ไม่มีผลลัพธ์ + < >");
  await expect(resultHeadings(page)).toHaveText(Array(4).fill("ไม่มีผลลัพธ์ + < >"));
  await expect(page.locator(".feature-card")).toHaveCount(0);
  await expect(page.locator(".feature-empty")).toHaveCount(4);
  await expect(page.locator(".feature-empty strong")).toHaveText(Array(4).fill("No nodes match"));
  await search(page).fill("");
  await expect(heroButton(page)).toHaveAccessibleName(browseLabel);
  await expect(resultHeadings(page)).toHaveText(Array(4).fill(""));
  await expect(subjectCards(page)).toHaveText(["Alpha subject"]);
  await expect(page.locator('[data-section="4"] .feature-card h3')).toHaveCount(0);
});

test("UX-004: switching search modes preserves the unsent draft and does not issue a request", async ({ page }) => {
  const state = await boot(page);
  await chooseProject(page, "Alpha project");
  await expect(subjectCards(page)).toHaveText(["Alpha subject"]);
  await search(page).fill("not submitted yet");
  const mode = page.getByRole("button", { name: "Search specific messages only" });
  await mode.click();
  await expect(mode).toHaveAttribute("aria-pressed", "true");
  await expect(search(page)).toHaveAccessibleName("Search specific messages only from Alpha project");
  await expect(search(page)).toHaveValue("not submitted yet");
  await expect(search(page)).toBeFocused();
  await expect(heroButton(page)).toHaveAccessibleName(browseLabel);
  expect(state.requests).toEqual([{ project: "alpha", query: "" }]);
  await search(page).press("Enter");
  await expect(resultHeadings(page)).toHaveText(Array(4).fill("not submitted yet"));
  expect(state.requests).toEqual([
    { project: "alpha", query: "" },
    { project: "alpha", query: "not submitted yet" },
  ]);
  expect(state.unexpected).toEqual([]);
});

test("EX-FILTER-01: a project change drops the previous filter even when IDs are reused", async ({ page }) => {
  const combined = (project) => {
    const matchingIds = branch("shared-id", project === "alpha" ? "Alpha" : "Beta");
    const other = branch(project, "Other");
    return {
      project: { id: project },
      layers: Object.fromEntries(layerNames.map((layer) => [layer, [...matchingIds.layers[layer], ...other.layers[layer]]])),
      edges: [...matchingIds.edges, ...other.edges],
    };
  };
  await boot(page, { explore: ({ project }) => ({ json: combined(project) }) });
  await chooseProject(page, "Alpha project");
  await openSlide(page, "Subjects");
  await page.getByRole("button", { name: "Add Alpha subject filter" }).click();
  await expect(subjectCards(page)).toHaveText(["Alpha subject"]);
  await expect(page.locator('[data-layer-key="subject"] [data-combobox-value]')).toHaveText("Alpha subject");
  await openSlide(page, "Welcome");
  await chooseProject(page, "Beta project");
  await expect(subjectCards(page)).toHaveText(["Beta subject", "Other subject"]);
  await expect(page.locator('[data-layer-key="subject"] [data-combobox-value]')).toHaveText("Select subject...");
  await expect(page.locator(".feature-card.is-selected")).toHaveCount(0);
});

const metadataFailures = [
  { label: "server 503", response: { status: 503, json: { error: "private fetch diagnostics" } } },
  { label: "malformed JSON", response: { body: "{truncated", contentType: "application/json" } },
  { label: "network failure", response: "abort" },
  { label: "JSON error envelope", response: { json: { error: "private fetch diagnostics" } } },
];

for (const { label, response } of metadataFailures) {
  test(`MD-FAIL-01: ${label} fails safely and a later request recovers`, async ({ page }) => {
    let attempts = 0;
    const state = await boot(page, { metadata: () => {
      attempts += 1;
      if (attempts === 1) return response;
      return { json: { display_title: "Recovered metadata", message_count: 7, source_chat_count: 2 } };
    } });
    await chooseProject(page, "Alpha project");
    await openSlide(page, "Subjects");
    const trigger = page.getByRole("button", { name: "View metadata for Alpha subject" });
    await trigger.click();
    await expect(details(page)).toContainText("Couldn’t load the conversation details");
    await expect(details(page)).not.toContainText("private fetch diagnostics");
    await expect(details(page)).not.toContainText("Summary for Alpha");
    await expect(details(page)).not.toContainText("Messages included");
    await page.keyboard.press("Escape");
    await expect(dialog(page)).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await trigger.press("Enter");
    await expect(dialog(page)).toHaveAccessibleName("Recovered metadata");
    await expect(details(page).locator(".node-detail-stat", { hasText: "Messages included" }).locator("strong")).toHaveText("7");
    expect(attempts).toBe(2);
    expect(state.pageErrors).toEqual([]);
  });
}

test("MD-RACE-01: Escape while loading prevents a late reply from replacing reopened metadata", async ({ page }) => {
  const first = responseGate();
  let attempts = 0;
  const state = await boot(page, {
    metadata: ({ id, query }, request) => {
      expect(id).toBe("alpha-0");
      expect(query).toEqual({ view: "explorer" });
      attempts += 1;
      if (attempts === 1) return first.reply(request);
      return { json: { display_title: "New request", overview: [{ text: "Fresh and safe", label: "Excerpt" }] } };
    },
  });
  await chooseProject(page, "Alpha project");
  await openSlide(page, "Subjects");
  const trigger = page.getByRole("button", { name: "View metadata for Alpha subject" });
  await trigger.click();
  await first.arrived;
  await expect(details(page)).toHaveAttribute("aria-live", "polite");
  await expect(details(page)).toContainText("Loading conversation details");
  await expect(dialog(page)).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog(page)).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await trigger.press("Enter");
  await expect(dialog(page)).toHaveAccessibleName("New request");
  await expect(details(page)).toContainText("Fresh and safe");
  await releaseResponse(page, first, { json: { display_title: "Obsolete response", overview: [{ text: "stale secret" }] } });
  await expect(dialog(page)).toHaveAccessibleName("New request");
  await expect(details(page)).not.toContainText("stale secret");
  await dialog(page).getByRole("button", { name: "Done" }).click();
  await expect(trigger).toBeFocused();
  await expect(page.locator("[data-node-detail-content]")).toBeEmpty();
  await expect(page.locator("[data-node-detail-title]")).toBeEmpty();
  expect(state.pageErrors).toEqual([]);
});

test("MD-SAFE-01: transcript text is displayed literally and internal fields never reach the modal DOM", async ({ page }) => {
  const markup = '<img src="https://disclosure.invalid/pixel" onerror="window.transcriptExecuted = true">';
  const secret = "PRIVATE_UNUSED_FIELD_SENTINEL";
  const nodeId = 'alpha path / ? # & ü';
  const state = await boot(page, {
    explore: () => ({ json: {
      layers: { subject: [{ id: nodeId, layer: "subject", title: markup, summary: markup }] },
      edges: [],
    } }),
    metadata: ({ id, query }) => {
      expect(id).toBe(nodeId);
      expect(query).toEqual({ view: "explorer" });
      return { json: {
        display_title: markup,
        overview: [{ text: markup, label: markup }],
        parents: [{ display_title: markup }],
        children: [{ title: markup }],
        message_count: -1,
        source_chat_count: Number.MAX_SAFE_INTEGER + 1,
        source_excerpt_count: 3,
        sources: [
          { chat_title: markup, text: markup, verified: true, chat_id: secret, raw_excerpt: secret },
          { text: markup, verified: false, metadata: secret },
        ],
        summary: secret,
        embedding: [secret],
      } };
    },
  });
  await chooseProject(page, "Alpha project");
  await openSlide(page, "Subjects");
  await expect(subjectCards(page)).toHaveText([markup]);
  await page.getByRole("button", { name: `View metadata for ${markup}` }).click();
  await expect(dialog(page)).toHaveAccessibleName(markup);
  await expect(details(page).locator("blockquote")).toHaveText(markup);
  await expect(details(page).locator(".node-detail-stat strong")).toHaveText(["Unavailable", "Unavailable"]);
  await expect(details(page)).toContainText("Showing 2 of 3 excerpts.");
  await expect(details(page).locator("summary small")).toHaveText(["Verified", "Unverified"]);
  await details(page).locator("summary").first().click();
  await expect(details(page).locator("details[open] p")).toHaveText(markup);
  await expect(details(page)).not.toContainText(secret);
  await expect(page.locator('[src*="disclosure.invalid"]')).toHaveCount(0);
  expect(await page.evaluate(() => window.transcriptExecuted)).toBeUndefined();
  expect(state.unexpected).toEqual([]);
  expect(state.pageErrors).toEqual([]);
});

test("MD-005: keyboard tabbing while metadata is open cannot focus the underlying explorer", async ({ page }) => {
  await boot(page);
  await chooseProject(page, "Alpha project");
  await openSlide(page, "Subjects");
  const trigger = page.getByRole("button", { name: "View metadata for Alpha subject" });
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(dialog(page)).toBeFocused();
  await expect(dialog(page)).toHaveAttribute("aria-modal", "true");
  const close = dialog(page).getByRole("button", { name: "Close details" });
  const done = dialog(page).getByRole("button", { name: "Done" });

  await close.focus();
  await page.keyboard.press("Shift+Tab");
  expect(await dialog(page).evaluate((element) =>
    document.activeElement === document.body || element.contains(document.activeElement))).toBe(true);

  await done.focus();
  for (let step = 0; step < 8; step += 1) {
    await page.keyboard.press("Tab");
    expect(await dialog(page).evaluate((element) =>
      document.activeElement === document.body || element.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog(page)).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("MD-RACE-02: a late connection refresh takes focus and invalidates old metadata when it completes", async ({ page }) => {
  const start = responseGate();
  const completion = responseGate();
  let finished = false;
  const state = await boot(page, {
    refreshStatus: (job, request) => {
      if (finished) return { json: { state: "idle" } };
      return job === "refresh-1" ? completion.reply(request) : start.reply(request);
    },
    metadata: () => ({
      json: { display_title: "Former project detail", overview: [{ text: "old displayed excerpt" }] },
    }),
  });
  await start.arrived;
  await chooseProject(page, "Alpha project");
  await openSlide(page, "Subjects");
  await page.getByRole("button", { name: "View metadata for Alpha subject" }).click();
  await expect(details(page)).toContainText("old displayed excerpt");
  await releaseResponse(page, start, { json: { id: "refresh-1", state: "running" } });
  await completion.arrived;
  const refresh = page.getByRole("status", { name: "Refreshing Context Saver" });
  await expect(refresh).toBeFocused();
  await expect(page.locator("[data-node-detail-overlay]")).toHaveJSProperty("inert", true);
  await expect(page.locator("body")).toHaveAttribute("aria-busy", "true");
  await page.keyboard.press("Escape");
  await expect(refresh).toBeFocused();

  finished = true;
  await releaseResponse(page, completion, { json: { id: "refresh-1", state: "complete" } });
  await expect(refresh).toHaveCount(0);
  await expect(page.locator("[data-node-detail-overlay]")).toBeHidden();
  await expect(page.locator("[data-node-detail-content]")).toBeEmpty();
  await expect(page.locator("[data-node-detail-title]")).toBeEmpty();
  await expect(subjectCards(page)).toHaveText(["Alpha subject"]);
  expect(state.unexpected).toEqual([]);
  expect(state.pageErrors).toEqual([]);
});
