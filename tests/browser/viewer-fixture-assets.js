import { fileURLToPath } from "node:url";

export const appOrigin = "http://viewer.fixture.test";

const assets = new Map([
  ["/", "index.html"],
  ["/exact-demo.css", "exact-demo.css"],
  ["/exact-demo.js", "exact-demo.js"],
  ["/chrome-arcs-background.js", "chrome-arcs-background.js"],
  ["/context-explorer-model.js", "context-explorer-model.js"],
].map(([pathname, asset]) => [
  pathname,
  fileURLToPath(new URL(`../../plugins/thread-tree/assets/viewer/${asset}`, import.meta.url)),
]));

export function getViewerFixtureAsset(url) {
  return url.origin === appOrigin ? assets.get(url.pathname) : undefined;
}
