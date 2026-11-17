const state = { config: null, activeSection: 0 };
const editorPreview = new URLSearchParams(window.location.search).has("editorPreview");
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const orbPositions = [
  { x: 76, y: 51, scale: 1.36, opacity: 0.9 },
  { x: 50, y: 24, scale: 0.92, opacity: 0.66 },
  { x: 88, y: 20, scale: 1.62, opacity: 0.76 },
  { x: 50, y: 50, scale: 1.82, opacity: 0.34 },
];

async function api(path) {
  const response = await fetch(path);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `Request failed: ${response.status}`);
  return value;
}

function applyViewerConfig(config) {
  state.config = { ...(state.config || {}), ...config };
  const root = document.documentElement;
  root.style.setProperty("--accent", state.config.accentColor || "#17765a");
  root.style.setProperty("--paper", state.config.canvasColor || "#f6f5f0");
  root.style.setProperty("--surface", state.config.surfaceColor || "#fffefa");
  root.style.setProperty("--line", state.config.lineColor || "#d8dbd6");
  document.title = state.config.title || "Context Saver";
}

function setActiveSection(index) {
  if (index === state.activeSection && $(".section-nav__dot.is-active")) return;
  state.activeSection = index;
  $$(".section-nav__dot").forEach((dot, dotIndex) => dot.classList.toggle("is-active", dotIndex === index));
  const orb = $(".memory-orb");
  const position = orbPositions[index] || orbPositions[0];
  orb?.style.setProperty("--orb-x", `${position.x}vw`);
  orb?.style.setProperty("--orb-y", `${position.y}vh`);
  orb?.style.setProperty("--orb-scale", position.scale);
  orb?.style.setProperty("--orb-opacity", position.opacity);
}

function updateScrollState() {
  const maxScroll = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
  const progress = Math.min(1, Math.max(0, window.scrollY / maxScroll));
  $(".scroll-progress__value")?.style.setProperty("transform", `scaleX(${progress})`);

  const viewportCenter = window.innerHeight / 2;
  let closestIndex = 0;
  let closestDistance = Number.POSITIVE_INFINITY;
  $$("[data-section]").forEach((section, index) => {
    const rect = section.getBoundingClientRect();
    const distance = Math.abs(rect.top + rect.height / 2 - viewportCenter);
    if (distance < closestDistance) {
      closestDistance = distance;
      closestIndex = index;
    }
  });
  setActiveSection(closestIndex);
}

function scrollToSection(index) {
  $$('[data-section]')[index]?.scrollIntoView({
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    block: "center",
  });
}

window.addEventListener("message", (event) => {
  const fromEditorFrame = event.source === window.parent || event.source === window.top;
  if (!fromEditorFrame || event.data?.type !== "thread-tree-config-preview") return;
  applyViewerConfig(event.data.config || {});
});

(async () => {
  window.ThreadTreeShaderBackground?.mount($("#shader-background"));
  try {
    applyViewerConfig(await api("/api/viewer-config"));
  } catch {
    applyViewerConfig({ title: "Context Saver" });
  }

  $$("[data-section-index]").forEach((button) => {
    button.addEventListener("click", () => scrollToSection(Number(button.dataset.sectionIndex)));
  });
  $$("[data-scroll-to]").forEach((button) => {
    button.addEventListener("click", () => scrollToSection(Number(button.dataset.scrollTo)));
  });

  let ticking = false;
  window.addEventListener("scroll", () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => {
      updateScrollState();
      ticking = false;
    });
  }, { passive: true });
  window.addEventListener("resize", updateScrollState, { passive: true });
  setActiveSection(0);
  updateScrollState();

  if (editorPreview) window.parent.postMessage({ type: "thread-tree-preview-ready" }, "*");
})();
