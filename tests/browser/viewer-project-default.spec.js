import { test, expect } from "@playwright/test";
import { appOrigin, getViewerFixtureAsset } from "./viewer-fixture-assets.js";

test.use({ reducedMotion: "reduce", serviceWorkers: "block" });

const recent = { id: "recent", title: "Most recent" };
const second = { id: "second", title: "Second most recent" };
const oldest = { id: "oldest", title: "Oldest" };
const projectBox = (page) => page.getByRole("combobox", { name: "Select project", exact: true });
const search = (page) => page.locator("[data-spotlight-input]");

function connection(project) {
  return { id: project.id, path: `/fixture/${project.id}`, name: project.title,
    status: "connected", chatCount: 0, chats: [] };
}

function payload(project, query = "") {
  return { query, project: { id: project }, layers: {
    subject: [{ id: `${project}-subject`, layer: "subject", title: `${project} theme` }],
    broad_topic: [], specific_topic: [], specific_message: [],
  }, edges: [] };
}

async function boot(page, { initial = [recent, second, oldest], firstListGate, listStatus = 200, failFirstBrowse = false } = {}) {
  const state = { projects: [...initial], listRequests: 0, exploreRequests: [], errors: [] };
  page.on("pageerror", (error) => state.errors.push(error.message));
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const asset = getViewerFixtureAsset(url);
    if (asset) return route.fulfill({ path: asset });
    if (url.pathname === "/favicon.ico") return route.fulfill({ status: 204 });
    if (url.pathname === "/api/threads") {
      const requestNumber = ++state.listRequests;
      if (requestNumber === 1 && firstListGate) await firstListGate;
      return route.fulfill({ status: listStatus, json: requestNumber === 1 && firstListGate ? initial : state.projects });
    }
    if (url.pathname === "/api/connections/refresh-status") return route.fulfill({ json: { state: "idle" } });
    if (url.pathname === "/api/connections") return route.fulfill({ json: { connections: state.projects.map(connection) } });
    if (url.pathname === "/api/connections/action") {
      const action = request.postDataJSON();
      if (action.action === "disconnect") state.projects = state.projects.filter((item) => `/fixture/${item.id}` !== action.projectPath);
      return route.fulfill({ json: { ok: true, connections: state.projects.map(connection) } });
    }
    if (url.pathname === "/api/explore") {
      const project = url.searchParams.get("thread_id");
      const query = url.searchParams.get("q");
      state.exploreRequests.push({ project, query });
      if (failFirstBrowse && state.exploreRequests.length === 1) return route.fulfill({ status: 503, json: { error: "Synthetic read failure" } });
      return route.fulfill({ json: payload(project, query) });
    }
    return route.abort();
  });
  await page.goto(appOrigin);
  return state;
}

async function chooseProject(page, name) {
  await projectBox(page).click();
  await page.getByRole("option", { name, exact: true }).click();
}

async function disconnectProject(page, name) {
  const panel = page.getByRole("dialog", { name: "Connections", exact: true });
  if (!await panel.isVisible()) await page.getByRole("button", { name: "Manage connections" }).click();
  await panel.getByRole("region", { name, exact: true }).getByRole("button", { name: "Disconnect", exact: true }).click();
  const confirm = page.getByRole("alertdialog");
  await confirm.getByRole("button", { name: "Disconnect", exact: true }).click();
  await expect(confirm).toHaveAccessibleName(`${name} successfully disconnected`);
  await confirm.getByRole("button", { name: "Done", exact: true }).click();
}

test("project defaults to the ranked first available item and cannot be cleared by reselection", async ({ page }) => {
  const state = await boot(page);
  await expect(projectBox(page)).toHaveText("Most recent");
  await expect(search(page)).toHaveAccessibleName("Search Context in Most recent");
  await expect(page.locator('[data-section="1"] .feature-card h3')).toHaveText(["recent theme"]);
  await expect(page.locator("[data-hero-combobox] .combobox-clear")).toBeHidden();
  await search(page).fill("keep this submitted query");
  await search(page).press("Enter");
  await expect(page.locator(".slide-down-button--hero")).toHaveAccessibleName("View results");
  const before = [...state.exploreRequests];
  await chooseProject(page, "Most recent");
  await expect(projectBox(page)).toHaveText("Most recent");
  await expect(search(page)).toHaveValue("keep this submitted query");
  await expect(page.locator(".slide-down-button--hero")).toHaveAccessibleName("View results");
  expect(state.exploreRequests).toEqual(before);
  expect(state.errors).toEqual([]);
});

test("manual choice survives list reorder and reload returns to the plugin's ranked default", async ({ page }) => {
  const state = await boot(page);
  await expect(projectBox(page)).toHaveText("Most recent");
  await chooseProject(page, "Oldest");
  state.projects = [second, recent, oldest];
  await page.getByRole("button", { name: "Manage connections" }).click();
  await page.getByRole("dialog", { name: "Connections" }).getByRole("region", { name: "Most recent", exact: true }).getByRole("button", { name: "Pause", exact: true }).click();
  await expect.poll(() => state.listRequests).toBe(2);
  await expect(projectBox(page)).toHaveText("Oldest");
  await page.reload();
  await expect(projectBox(page)).toHaveText("Second most recent");
  expect(state.errors).toEqual([]);
});

test("a failed default-project browse retains the project and can be retried", async ({ page }) => {
  const state = await boot(page, { failFirstBrowse: true });
  const subjects = page.locator('[data-section="1"] .feature-list');
  await expect(projectBox(page)).toHaveText("Most recent");
  await expect(subjects.locator(".feature-empty strong")).toHaveText("Couldn’t load saved context");
  await page.getByRole("button", { name: "Go to Subjects", exact: true }).click();
  await expect.poll(() => page.locator('[data-section="1"]').evaluate((section) => Math.abs(section.getBoundingClientRect().top))).toBeLessThan(1);
  await subjects.getByRole("button", { name: "Try again", exact: true }).click();
  await expect(subjects.locator(".feature-card h3")).toHaveText(["recent theme"]);
  await expect(projectBox(page)).toHaveText("Most recent");
  expect(state.exploreRequests).toEqual([{ project: "recent", query: "" }, { project: "recent", query: "" }]);
  expect(state.errors).toEqual([]);
});

test("disconnecting selected projects falls back through ranked choices and finally shows no projects", async ({ page }) => {
  const state = await boot(page);
  await expect(projectBox(page)).toHaveText("Most recent");
  await disconnectProject(page, "Most recent");
  await expect(projectBox(page)).toHaveText("Second most recent");
  await disconnectProject(page, "Second most recent");
  await expect(projectBox(page)).toHaveText("Oldest");
  await disconnectProject(page, "Oldest");
  await expect(projectBox(page)).toHaveText("No connected projects");
  await expect(search(page)).toHaveAccessibleName("Search Context");
  await expect(page.locator('[data-section="1"] .feature-empty strong')).toHaveText("No connected projects");
  expect(state.exploreRequests.map(({ project }) => project)).toEqual(["recent", "second", "oldest"]);
  expect(state.errors).toEqual([]);
});

test("an obsolete initial project list cannot restore a project removed by a newer connection refresh", async ({ page }) => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const state = await boot(page, { initial: [recent, second], firstListGate: gate });
  await expect(projectBox(page)).toHaveText("Loading projects…");
  await disconnectProject(page, "Most recent");
  await expect(projectBox(page)).toHaveText("Second most recent");
  const oldResponse = page.waitForResponse((response) => response.url().includes("/api/threads"));
  release();
  await (await oldResponse).finished();
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(projectBox(page)).toHaveText("Second most recent");
  expect(state.exploreRequests).toEqual([{ project: "second", query: "" }]);
  expect(state.errors).toEqual([]);
});

for (const scenario of [{ name: "empty", initial: [], status: 200, title: "No connected projects" },
  { name: "unavailable", initial: [recent], status: 503, title: "Couldn’t load connected projects" }]) {
  test(`${scenario.name} project data produces an honest empty state without a browse request`, async ({ page }) => {
    const state = await boot(page, { initial: scenario.initial, listStatus: scenario.status });
    await expect(page.locator('[data-section="1"] .feature-empty strong')).toHaveText(scenario.title);
    expect(state.exploreRequests).toEqual([]);
    expect(state.errors).toEqual([]);
  });
}
