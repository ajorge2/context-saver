import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const viewerRoot = fileURLToPath(new URL("../../plugins/thread-tree/assets/viewer/", import.meta.url));
const html = readFileSync(`${viewerRoot}/index.html`, "utf8");
const app = readFileSync(`${viewerRoot}/app.js`, "utf8");

test("public viewer is a blank redesign canvas without the retired graph UI", () => {
  for (const id of ["search-form", "search-input", "zoom-out", "fit-graph", "zoom-in", "stats", "legend"]) {
    assert.doesNotMatch(html, new RegExp(`id=["']${id}["']`));
    assert.doesNotMatch(app, new RegExp(`#${id}\\b`));
  }
  for (const id of ["graph", "viewport", "layer-guides", "primary-edges", "related-edges", "nodes", "empty-state", "node-card"]) {
    assert.doesNotMatch(html, new RegExp(`id=["']${id}["']`));
  }
  assert.doesNotMatch(app, /\/api\/tree/);
  assert.doesNotMatch(app, /renderGraph/);
  assert.match(html, /data-chrome-arcs/);
  assert.match(html, /context-explorer-model\.js/);
  assert.match(html, /data-node-detail-overlay/);
});
