const isReload = performance.getEntriesByType("navigation")[0]?.type === "reload";
if (isReload) history.scrollRestoration = "manual";

const sections = [...document.querySelectorAll("[data-section]")];
const dots = [...document.querySelectorAll("[data-section-index]")];
const progressBar = document.querySelector(".scroll-progress__value");
const sectionsTrack = document.querySelector("[data-sections-track]");
const scrollSpacer = document.querySelector("[data-scroll-spacer]");

let projects = [];
let selectedProjectValue = "";
let projectLoadState = "loading";
let projectRequestVersion = 0;
let messageSearchOnly = false;

function selectedProject() {
  return projects.find((project) => project.value === selectedProjectValue);
}

function projectSearchPlaceholder(onlyMessages = messageSearchOnly) {
  const project = selectedProject();
  if (onlyMessages) {
    return project
      ? `Search specific messages only from ${project.label}`
      : "Search specific messages only";
  }
  return project ? `Search Context in ${project.label}` : "Search Context";
}

const searchIcon = `
  <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
`;
const chevronsIcon = `
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 15 5 5 5-5M7 9l5-5 5 5" /></svg>
`;
const checkIcon = `
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m20 6-11 11-5-5" /></svg>
`;

function comboboxMarkup({
  mode = "project",
  placeholder = "Select project...",
  searchPlaceholder = "Search projects...",
  emptyText = "Loading connected projects...",
} = {}) {
  return `
    <div class="framework-combobox" data-combobox data-combobox-mode="${mode}" data-default-label="${escapeHtml(placeholder)}">
      <button class="combobox-trigger" type="button" role="combobox" aria-expanded="false" aria-label="${escapeHtml(placeholder.replace(/\.\.\.$/, ""))}">
        <span data-combobox-value>${escapeHtml(placeholder)}</span>${mode === "layer" ? chevronsIcon : ""}
      </button>
      <button class="combobox-clear" type="button" aria-label="Clear selection" title="Clear selection" hidden>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
      <div class="combobox-popover" data-combobox-popover hidden>
        <label class="combobox-search">${searchIcon}<input type="search" placeholder="${escapeHtml(searchPlaceholder)}" aria-label="${escapeHtml(searchPlaceholder.replace(/\.\.\.$/, ""))}" disabled /></label>
        <div class="combobox-list" role="listbox">
          <p class="combobox-empty" data-project-status>${escapeHtml(emptyText)}</p>
          <div class="combobox-group"></div>
        </div>
      </div>
    </div>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderProjectOptions(statusMessage = "") {
  document.querySelectorAll('[data-combobox][data-combobox-mode="project"]').forEach((combobox) => {
    const group = combobox.querySelector(".combobox-group");
    const status = combobox.querySelector("[data-project-status]");
    const search = combobox.querySelector("input[type='search']");
    group.innerHTML = projects.map((project) => `
      <button class="combobox-option" type="button" role="option" aria-selected="false" data-value="${escapeHtml(project.value)}">
        <span>${escapeHtml(project.label)}</span><span class="combobox-check">${checkIcon}</span>
      </button>
    `).join("");
    search.disabled = projects.length === 0;
    status.textContent = statusMessage || (projects.length ? "No project found." : "No connected projects yet.");
    status.hidden = projects.length > 0;
  });
  setSelectedProject(selectedProjectValue, { refresh: true });
}

async function loadConnectedProjects() {
  const requestVersion = ++projectRequestVersion;
  try {
    const threadsResponse = await fetch("/api/threads?include_all=1", { cache: "no-store" });
    if (!threadsResponse.ok) throw new Error("Project data is unavailable");
    const threads = await threadsResponse.json();
    if (!Array.isArray(threads)) throw new Error("Project data is unavailable");
    if (requestVersion !== projectRequestVersion) return;
    projects = threads
      .filter((project) => project && typeof project.id === "string" && project.id.trim())
      .map((project) => ({
        value: project.id,
        label: project.title || project.cwd?.split(/[\\/]/).filter(Boolean).at(-1) || "Project",
      }));
    projectLoadState = "ready";
    renderProjectOptions();
  } catch (_error) {
    if (requestVersion !== projectRequestVersion) return;
    projects = [];
    projectLoadState = "error";
    renderProjectOptions("Could not load connected projects.");
  }
}

function setSelectedProject(nextValue, { refresh = false } = {}) {
  // The server ranks available projects by actual plugin use. Browsing and
  // manual selection do not change that durable order.
  const nextProject = projects.find((project) => project.value === nextValue) || projects[0];
  const previousValue = selectedProjectValue;
  selectedProjectValue = nextProject?.value || "";
  const selected = selectedProject();

  document.querySelectorAll('[data-combobox][data-combobox-mode="project"]').forEach((combobox) => {
    const valueLabel = combobox.querySelector("[data-combobox-value]");
    const clear = combobox.querySelector(".combobox-clear");
    valueLabel.textContent = selected?.label || (projectLoadState === "ready"
      ? "No connected projects" : projectLoadState === "error" ? "Projects unavailable" : "Loading projects…");
    clear.hidden = true;
    combobox.classList.toggle("has-value", Boolean(selected));
    combobox.querySelectorAll(".combobox-option").forEach((option) => {
      const isSelected = option.dataset.value === selectedProjectValue;
      option.setAttribute("aria-selected", String(isSelected));
      option.classList.toggle("is-selected", isSelected);
    });
  });

  if (refresh || previousValue !== selectedProjectValue) {
    document.dispatchEvent(new CustomEvent("projectchange", {
      detail: { label: selected?.label || "", value: selectedProjectValue },
    }));
  }
}

function initializeCombobox(host) {
  const combobox = host.matches("[data-combobox]") ? host : host.querySelector("[data-combobox]");
  const mode = combobox?.dataset.comboboxMode;
  const trigger = host.querySelector(".combobox-trigger");
  const clear = host.querySelector(".combobox-clear");
  const popover = host.querySelector("[data-combobox-popover]");
  const input = host.querySelector("input[type='search']");
  const empty = host.querySelector(".combobox-empty");
  const group = host.querySelector(".combobox-group");

  const setOpen = (open) => {
    popover.hidden = !open;
    trigger.setAttribute("aria-expanded", String(open));
    host.classList.toggle("is-open", open);
    if (open) requestAnimationFrame(() => input.focus());
    else {
      input.value = "";
      host.querySelectorAll(".combobox-option").forEach((option) => { option.hidden = false; });
      empty.hidden = mode === "project" && projects.length > 0;
    }
  };

  trigger.addEventListener("click", () => setOpen(popover.hidden));
  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    let matches = 0;
    host.querySelectorAll(".combobox-option").forEach((option) => {
      const visible = option.textContent.toLowerCase().includes(query);
      option.hidden = !visible;
      if (visible) matches += 1;
    });
    empty.textContent = mode === "project" ? "No project found." : "No matching item found.";
    empty.hidden = matches !== 0;
  });

  clear.addEventListener("click", (event) => {
    event.stopPropagation();
    if (mode === "project") return;
    else {
      host.querySelector("[data-combobox-value]").textContent = combobox.dataset.defaultLabel;
      clear.hidden = true;
      host.dispatchEvent(new CustomEvent("layerselectionchange", {
        bubbles: true,
        detail: { layer: host.dataset.layerKey, id: "" },
      }));
    }
    setOpen(false);
    trigger.focus();
  });

  group.addEventListener("click", (event) => {
    const option = event.target.closest(".combobox-option");
    if (!option) return;
    if (mode === "project") {
      setSelectedProject(option.dataset.value);
    } else {
      host.querySelector("[data-combobox-value]").textContent = option.textContent.trim();
      clear.hidden = false;
      host.dispatchEvent(new CustomEvent("layerselectionchange", {
        bubbles: true,
        detail: { layer: host.dataset.layerKey, id: option.dataset.value || "" },
      }));
    }
    setOpen(false);
    trigger.focus();
  });

  host.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !popover.hidden) {
      event.preventDefault();
      setOpen(false);
      trigger.focus();
    }
  });
  document.addEventListener("pointerdown", (event) => {
    if (!host.contains(event.target)) setOpen(false);
  });
  if (mode === "project") setSelectedProject(selectedProjectValue);
}

const layerSelectors = [
  { key: "subject", name: "subject", plural: "subjects" },
  { key: "broad_topic", name: "broad topic", plural: "broad topics" },
  { key: "specific_topic", name: "specific topic", plural: "specific topics" },
  { key: "specific_message", name: "specific message", plural: "specific messages" },
];

sections.slice(1).forEach((section, index) => {
  const layer = layerSelectors[index];
  section.classList.add("demo-section--split");
  const host = document.createElement("aside");
  host.className = "combobox-demo";
  host.dataset.layerKey = layer.key;
  host.setAttribute("aria-label", `${layer.name} selector`);
  host.innerHTML = comboboxMarkup({
    mode: "layer",
    placeholder: `Select ${layer.name}...`,
    searchPlaceholder: `Search ${layer.plural}...`,
    emptyText: "Select a project first.",
  });
  section.append(host);
  initializeCombobox(host);

  const upButton = document.createElement("button");
  upButton.className = "slide-up-button";
  upButton.type = "button";
  upButton.dataset.scrollTo = String(index);
  upButton.setAttribute("aria-label", "Go to previous slide");
  upButton.innerHTML = `
    <span>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="m6.5 11.5 5.5-5.5 5.5 5.5M12 6v12" />
      </svg>
    </span>
  `;
  section.append(upButton);
});

sections.slice(0, -1).forEach((section, index) => {
  const downButton = document.createElement("button");
  const isHero = index === 0;
  downButton.className = `slide-up-button slide-down-button${isHero ? " slide-down-button--hero" : ""}`;
  downButton.type = "button";
  downButton.dataset.scrollTo = String(index + 1);
  downButton.setAttribute("aria-label", isHero ? "See what you've been chatting about" : "Go to next slide");
  downButton.innerHTML = `
    <span>
      ${isHero ? "<strong data-hero-down-label>See what you've been chatting about</strong>" : ""}
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="m6.5 12.5 5.5 5.5 5.5-5.5M12 18V6" />
      </svg>
      ${isHero ? '<i class="button-loader-pulse" aria-hidden="true"></i>' : ""}
    </span>
  `;
  section.append(downButton);
});

const resultQueryHeadings = sections.slice(1).map((section) => {
  const layerTitle = section.querySelector(".section-title");
  const queryHeading = document.createElement("div");
  queryHeading.className = "result-query-heading";
  queryHeading.hidden = true;
  queryHeading.setAttribute("aria-label", "Submitted search");
  layerTitle?.before(queryHeading);
  return queryHeading;
});

const heroCombobox = document.querySelector("[data-hero-combobox]");
if (heroCombobox) {
  heroCombobox.innerHTML = comboboxMarkup();
  initializeCombobox(heroCombobox);
}
loadConnectedProjects();

const explorerLayerLabels = {
  subject: "Subject",
  broad_topic: "Broad topic",
  specific_topic: "Specific topic",
  specific_message: "Specific message",
};

function initializeNodeDetailModal() {
  const overlay = document.querySelector("[data-node-detail-overlay]");
  if (!overlay) return { open: () => {} };
  const dialog = overlay.querySelector(".node-detail-dialog");
  const title = overlay.querySelector("[data-node-detail-title]");
  const layer = overlay.querySelector("[data-node-detail-layer]");
  const content = overlay.querySelector("[data-node-detail-content]");
  const closeButtons = overlay.querySelectorAll("[data-node-detail-close], [data-node-detail-done]");
  let returnFocus = null;
  let activeRequest = null;
  let originSection = null;
  let originEpoch = null;

  const close = () => {
    activeRequest?.abort();
    activeRequest = null;
    overlay.hidden = true;
    content.replaceChildren();
    title.textContent = "";
    layer.textContent = "Context node";
    document.body.classList.remove("node-detail-open");
    const trigger = returnFocus;
    returnFocus = null;
    trigger?.focus({ preventScroll: true });
    if (originSection !== null && originEpoch === navigationEpoch) {
      settleSlide(originSection);
    }
    originSection = null;
    originEpoch = null;
  };

  const readableDate = (value) => {
    if (!value) return "Not available";
    const date = new Date(value);
    return Number.isNaN(date.valueOf()) ? String(value) : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
  };

  const row = (label, value) => `
    <div class="node-detail-stat">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `;

  const readableCount = (value) => Number.isSafeInteger(value) && value > 0
    ? value.toLocaleString()
    : "Unavailable";

  const render = (detail, fallback) => {
    title.textContent = detail.display_title || fallback.title || "Context details";
    const parents = Array.isArray(detail.parents) ? detail.parents : [];
    const children = Array.isArray(detail.children) ? detail.children : [];
    const sources = Array.isArray(detail.sources) ? detail.sources : [];
    const excerptCount = detail.source_excerpt_count;
    const overview = Array.isArray(detail.overview)
      ? detail.overview.filter((passage) => typeof passage?.text === "string" && passage.text.trim())
      : [];
    const updatedAt = detail.updated_at || detail.created_at || fallback.updatedAt;
    content.innerHTML = `
      <section class="node-detail-section">
        <h3>Conversation preview</h3>
        ${overview.length ? `<div class="node-detail-overview">
          ${overview.map((passage) => `
            <div>
              <h4>${escapeHtml(passage.label || "Excerpt")}</h4>
              <blockquote>${escapeHtml(passage.text)}</blockquote>
            </div>
          `).join("")}
        </div>` : `<p class="node-detail-status">${sources.length
          ? "Open a source excerpt below to read the conversation."
          : "There’s no conversation preview available for this item."}</p>`}
      </section>
      <section class="node-detail-section">
        <h3>Details</h3>
        <div class="node-detail-stats">
          ${row("Messages included", readableCount(detail.message_count))}
          ${row("Source chats", readableCount(detail.source_chat_count))}
          ${updatedAt ? row("Last updated", readableDate(updatedAt)) : ""}
        </div>
      </section>
      ${(parents.length || children.length) ? `
        <section class="node-detail-section">
          <h3>Place in your context</h3>
          <div class="node-detail-relations">
            ${parents.map((item) => `<div><span>Contained by</span><strong>${escapeHtml(item.display_title || item.title)}</strong></div>`).join("")}
            ${children.map((item) => `<div><span>Contains</span><strong>${escapeHtml(item.display_title || item.title)}</strong></div>`).join("")}
          </div>
        </section>
      ` : ""}
      ${sources.length ? `
        <section class="node-detail-section">
          <h3>Source excerpts</h3>
          ${Number.isSafeInteger(excerptCount) && excerptCount > sources.length ? `
            <p class="node-detail-source-count">Showing ${sources.length.toLocaleString()} of ${excerptCount.toLocaleString()} excerpts.</p>
          ` : ""}
          <div class="node-detail-sources">
            ${sources.map((source, index) => `
              <details>
                <summary>
                  <span>${escapeHtml(source.chat_title || `Excerpt ${index + 1}`)}</span>
                  <small class="${source.verified ? "is-verified" : ""}">${source.verified ? "Verified" : "Unverified"}</small>
                </summary>
                <p>${escapeHtml(source.text || "No excerpt is available.")}</p>
              </details>
            `).join("")}
          </div>
        </section>
      ` : ""}
    `;
  };

  closeButtons.forEach((button) => button.addEventListener("click", close));
  overlay.addEventListener("pointerdown", (event) => {
    if (event.target === overlay) close();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key !== "Tab" || overlay.inert) return;
    const controls = dialog.querySelectorAll("button:not(:disabled), summary, [tabindex='0']");
    const first = controls[0];
    const last = controls[controls.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === dialog)) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first?.focus();
    }
  });
  document.addEventListener("focusin", (event) => {
    if (!overlay.hidden && !overlay.inert && !dialog.contains(event.target)) {
      dialog.focus({ preventScroll: true });
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !overlay.hidden && !overlay.inert) close();
  });
  document.addEventListener("projectchange", () => {
    if (!overlay.hidden) close();
  });

  return {
    async open(node, trigger) {
      activeRequest?.abort();
      const request = new AbortController();
      activeRequest = request;
      returnFocus = trigger || document.activeElement;
      const section = returnFocus?.closest?.('[data-section]');
      originSection = section ? Number(section.dataset.section) : null;
      originEpoch = originSection !== null ? settleSlide(originSection) : null;
      title.textContent = node.title;
      layer.textContent = explorerLayerLabels[node.layer] || "Context node";
      content.innerHTML = '<div class="node-detail-loading"><i aria-hidden="true"></i><span>Loading conversation details…</span></div>';
      content.scrollTop = 0;
      overlay.hidden = false;
      document.body.classList.add("node-detail-open");
      requestAnimationFrame(() => {
        if (!overlay.hidden && !overlay.inert && !request.signal.aborted) dialog.focus({ preventScroll: true });
      });
      try {
        const response = await fetch(`/api/node/${encodeURIComponent(node.id)}?view=explorer`, {
          cache: "no-store",
          signal: request.signal,
        });
        if (request.signal.aborted) return;
        if (response.status === 404) {
          title.textContent = "Context no longer available";
          content.innerHTML = '<p class="node-detail-status">The source messages for this item are no longer in this project’s context.</p>';
          return;
        }
        if (!response.ok) throw new Error("Details are unavailable");
        const detail = await response.json();
        if (!detail || detail.error) throw new Error("Details are unavailable");
        if (!request.signal.aborted) render(detail, node);
      } catch (_error) {
        if (request.signal.aborted) return;
        content.innerHTML = '<p class="node-detail-status">Couldn’t load the conversation details. Close this window and try again.</p>';
      }
    },
  };
}

const nodeDetailModal = initializeNodeDetailModal();

const contextExplorer = (() => {
  const layerSections = new Map(layerSelectors.map((layer, index) => [layer.key, sections[index + 1]]));
  const layerHosts = new Map([...document.querySelectorAll('[data-layer-key]')].map((host) => [host.dataset.layerKey, host]));
  const pageSize = 9;
  const messageBufferSize = 36;
  const pages = {};
  const lists = new Map();
  const pagers = new Map();
  let payload = null;
  let selected = {};
  let browsing = false;
  let messageStatus = '';
  let browseStatus = '';
  let activeMessageRequest = null;
  let activeRequest = null;
  let index = window.ContextExplorerModel.indexPayload(null);
  let byId = index.byId;

  layerSelectors.forEach((layer) => {
    const list = layerSections.get(layer.key)?.querySelector('.feature-list');
    if (!list) return;
    list.tabIndex = 0;
    list.setAttribute('aria-label', `${layer.plural} cards`);
    lists.set(layer.key, list);

    const pager = document.createElement('nav');
    pager.className = 'feature-pagination';
    pager.setAttribute('aria-label', `${layer.plural} pages`);
    pager.innerHTML = `
      <button type="button" data-card-page="previous">Previous</button>
      <span class="feature-pagination__status" aria-live="polite"></span>
      <button type="button" data-card-page="next">Next</button>
    `;
    pager.hidden = true;
    pager.addEventListener('click', async (event) => {
      const button = event.target.closest('[data-card-page]');
      if (!button || button.disabled) return;
      const page = (pages[layer.key] || 0) + (button.dataset.cardPage === 'next' ? 1 : -1);
      pages[layer.key] = page;
      list.scrollTop = 0;
      const messagePage = browseMessagePage();
      if (layer.key === 'specific_message' && messagePage
          && (page * pageSize < messagePage.offset
            || page * pageSize >= messagePage.offset + payload.layers.specific_message.length)) {
        list.focus({ preventScroll: true });
        const loaded = await refreshBrowseMessages(page);
        if (!loaded || document.activeElement !== list) return;
      } else {
        renderLayer(layer.key);
      }
      (button.disabled || pager.hidden ? list : button).focus({ preventScroll: true });
    });
    list.after(pager);
    pagers.set(layer.key, pager);
  });

  // Search and older viewer fixtures keep their existing, local pagination.
  // Browse metadata describes the full message set while the array is one buffer.
  const browseMessagePage = () => {
    const page = payload?.messagePage;
    return browsing && !selected.specific_message && page
      && Number.isInteger(page.offset) && Number.isInteger(page.total) ? page : null;
  };

  const candidates = (layerKey, excludeOwnSelection = false) => {
    return window.ContextExplorerModel.filterLayerNodes(payload, index, selected, layerKey, excludeOwnSelection);
  };

  const renderCombobox = (layerKey) => {
    const host = layerHosts.get(layerKey);
    if (!host) return;
    const layer = layerSelectors.find((item) => item.key === layerKey);
    const waitingForMessages = layerKey === 'specific_message' && Boolean(messageStatus);
    const options = waitingForMessages ? [] : candidates(layerKey, true);
    const selectedNode = byId.get(selected[layerKey]);
    const group = host.querySelector(".combobox-group");
    const empty = host.querySelector(".combobox-empty");
    const search = host.querySelector("input[type='search']");
    const clear = host.querySelector(".combobox-clear");
    const value = host.querySelector("[data-combobox-value]");
    group.innerHTML = options.map((node) => `
      <button class="combobox-option" type="button" role="option" aria-selected="${node.id === selected[layerKey]}" data-value="${escapeHtml(node.id)}">
        <span>${escapeHtml(node.title)}</span><span class="combobox-check">${checkIcon}</span>
      </button>
    `).join("");
    search.disabled = !payload || waitingForMessages;
    if (waitingForMessages) {
      empty.textContent = messageStatus === 'loading' ? 'Loading messages…' : 'Messages are unavailable.';
    } else if (layerKey === 'specific_message' && browsing) {
      empty.textContent = 'No messages to show.';
    } else {
      empty.textContent = payload ? `No ${layer.plural} match the active filters.` : selectedProjectValue ? 'Loading saved context…' : projectLoadState === 'error' ? 'Projects are unavailable.' : 'No connected projects.';
    }
    empty.hidden = options.length > 0;
    value.textContent = selectedNode?.title || host.querySelector("[data-combobox]")?.dataset.defaultLabel || `Select ${layer.name}...`;
    clear.hidden = !selectedNode;
    host.classList.toggle("has-value", Boolean(selectedNode));
  };

  const renderLayer = (layerKey) => {
    const list = lists.get(layerKey);
    const pager = pagers.get(layerKey);
    if (!list || !pager) return;
    pager.hidden = true;
    if (!payload) {
      const title = projectLoadState === 'error' ? 'Couldn’t load connected projects'
        : projectLoadState === 'loading' ? 'Loading connected projects…'
        : !projects.length ? 'No connected projects'
        : browseStatus === 'error' ? 'Couldn’t load saved context' : 'Loading saved context…';
      const description = projectLoadState === 'ready' && !projects.length
        ? 'Use Context Saver in a project chat to connect it.' : '';
      list.innerHTML = `<div class="feature-empty"><strong>${title}</strong>${description ? `<span>${description}</span>` : ''}${browseStatus === 'error' ? '<button type="button" class="feature-retry" data-retry-project>Try again</button>' : ''}</div>`;
      list.querySelector('[data-retry-project]')?.addEventListener('click', browseProject);
      return;
    }
    if (layerKey === 'specific_message' && messageStatus) {
      if (messageStatus === 'loading') {
        list.innerHTML = '<div class="feature-empty" role="status"><strong>Loading messages…</strong></div>';
      } else {
        list.innerHTML = '<div class="feature-empty"><strong>Couldn’t load messages</strong><button type="button" class="feature-retry" data-retry-messages>Try again</button></div>';
        list.querySelector('[data-retry-messages]').addEventListener('click', () => refreshBrowseMessages(pages.specific_message || 0));
      }
      return;
    }
    const nodes = candidates(layerKey);
    if (!nodes.length) {
      if (layerKey === 'specific_message' && browsing) {
        const hasTopicFilter = layerSelectors.slice(0, -1).some(({ key }) => selected[key]);
        list.innerHTML = hasTopicFilter
          ? '<div class="feature-empty"><strong>No messages in this branch</strong><span>Remove a topic filter to see more messages.</span></div>'
          : '<div class="feature-empty"><strong>No saved messages yet</strong><span>Messages appear here as connected chats are indexed.</span></div>';
      } else {
        list.innerHTML = '<div class="feature-empty"><strong>No nodes match</strong><span>Try removing a filter or searching for something else.</span></div>';
      }
      return;
    }
    const messagePage = layerKey === 'specific_message' ? browseMessagePage() : null;
    const total = messagePage ? messagePage.total : nodes.length;
    const totalPages = Math.ceil(total / pageSize);
    const page = Math.max(0, Math.min(pages[layerKey] || 0, totalPages - 1));
    pages[layerKey] = page;
    const first = page * pageSize;
    const last = Math.min(first + pageSize, total);
    const bufferFirst = first - (messagePage?.offset || 0);
    if (totalPages > 1) {
      pager.hidden = false;
      pager.querySelector('[data-card-page="previous"]').disabled = page === 0;
      pager.querySelector('[data-card-page="next"]').disabled = page === totalPages - 1;
      pager.querySelector('.feature-pagination__status').textContent = `${first + 1}–${last} of ${total}`;
    }
    list.innerHTML = nodes.slice(bufferFirst, bufferFirst + last - first).map((node) => {
      const isSelected = selected[layerKey] === node.id;
      return `
        <article class="feature-card${isSelected ? " is-selected" : ""}" data-node-id="${escapeHtml(node.id)}">
          <i></i>
          <button class="feature-card__body" type="button" aria-label="View metadata for ${escapeHtml(node.title)}">
            <span class="feature-eyebrow">${escapeHtml(explorerLayerLabels[layerKey])}</span>
            <h3>${escapeHtml(node.title)}</h3>
            <p>${escapeHtml(node.summary || "")}</p>
          </button>
          <button class="feature-card__toggle" type="button" aria-label="${isSelected ? "Remove" : "Add"} ${escapeHtml(node.title)} filter" title="${isSelected ? "Remove filter" : "Filter by this node"}">${isSelected ? "×" : "+"}</button>
        </article>
      `;
    }).join("");
    list.querySelectorAll(".feature-card").forEach((card) => {
      const node = byId.get(card.dataset.nodeId);
      card.querySelector(".feature-card__body")?.addEventListener("click", (event) => nodeDetailModal.open(node, event.currentTarget));
      card.querySelector(".feature-card__toggle")?.addEventListener("click", () => select(layerKey, selected[layerKey] === node.id ? "" : node.id));
    });
  };

  const render = () => {
    layerSelectors.forEach((layer) => {
      renderCombobox(layer.key);
      renderLayer(layer.key);
    });
  };

  const renderMessages = () => {
    renderCombobox('specific_message');
    renderLayer('specific_message');
  };

  const cancelMessageRequest = () => {
    activeMessageRequest?.abort();
    activeMessageRequest = null;
  };

  async function refreshBrowseMessages(requestedPage = 0) {
    cancelMessageRequest();
    pages.specific_message = requestedPage;
    const request = new AbortController();
    activeMessageRequest = request;
    const params = new URLSearchParams({
      q: '', thread_id: selectedProjectValue,
      message_offset: String(Math.floor(requestedPage * pageSize / messageBufferSize) * messageBufferSize),
      message_limit: String(messageBufferSize),
    });
    for (const layer of layerSelectors.slice(0, -1)) {
      if (selected[layer.key]) params.append('browse_node', selected[layer.key]);
    }
    if (selected.specific_message) params.set('browse_message', selected.specific_message);
    messageStatus = 'loading';
    const list = lists.get('specific_message');
    if (list.contains(document.activeElement)) list.focus({ preventScroll: true });
    renderMessages();
    try {
      const response = await fetch(`/api/explore?${params}`, { cache: 'no-store', signal: request.signal });
      if (!response.ok) throw new Error('Messages are unavailable.');
      const nextPayload = await response.json();
      if (request.signal.aborted) return false;
      load(nextPayload, true, true);
      return true;
    } catch (_error) {
      if (request.signal.aborted) return false;
      messageStatus = 'error';
      renderMessages();
      return false;
    } finally {
      if (activeMessageRequest === request) activeMessageRequest = null;
    }
  }

  const resetPages = () => {
    for (const [key, list] of lists) {
      pages[key] = 0;
      list.scrollTop = 0;
    }
  };

  const select = (layerKey, nodeId) => {
    if (nodeId && !byId.has(nodeId)) return;
    const value = nodeId || '';
    if (value === (selected[layerKey] || '')) return;
    cancelMessageRequest();
    messageStatus = '';
    selected = { ...selected, [layerKey]: value };
    resetPages();
    if (browsing && !activeRequest && (layerKey !== 'specific_message' || !value)) void refreshBrowseMessages();
    render();
  };

  const load = (nextPayload, browse = false, preserveSelection = false) => {
    payload = nextPayload;
    browseStatus = '';
    browsing = browse;
    messageStatus = '';
    index = window.ContextExplorerModel.indexPayload(payload);
    byId = index.byId;
    if (preserveSelection) {
      selected = Object.fromEntries(Object.entries(selected).filter(([, id]) => byId.has(id)));
    } else {
      selected = {};
      resetPages();
    }
    render();
  };

  document.addEventListener("layerselectionchange", (event) => select(event.detail.layer, event.detail.id));
  const cancelRequest = () => {
    activeRequest?.abort();
    activeRequest = null;
  };
  const fetchPayload = async (query) => {
    cancelRequest();
    if (activeMessageRequest) {
      cancelMessageRequest();
      messageStatus = '';
      const messagePage = browseMessagePage();
      if (messagePage) pages.specific_message = Math.ceil(messagePage.offset / pageSize);
      renderMessages();
    }
    const request = new AbortController();
    activeRequest = request;
    const params = new URLSearchParams({ q: query, thread_id: selectedProjectValue });
    try {
      const response = await fetch(`/api/explore?${params}`, {
        cache: "no-store",
        signal: request.signal,
      });
      if (!response.ok) throw new Error("Context search is unavailable.");
      const nextPayload = await response.json();
      if (request.signal.aborted) return false;
      cancelMessageRequest();
      load(nextPayload, !query.trim());
      return true;
    } catch (error) {
      if (request.signal.aborted) return false;
      throw error;
    } finally {
      if (activeRequest === request) activeRequest = null;
    }
  };
  const browseProject = () => {
    cancelRequest();
    cancelMessageRequest();
    load(null);
    const requestedProject = selectedProjectValue;
    if (requestedProject) void fetchPayload("").catch(() => {
      if (selectedProjectValue !== requestedProject) return;
      browseStatus = 'error';
      render();
    });
  };
  document.addEventListener("projectchange", browseProject);
  render();

  return {
    async search(query) {
      if (!selectedProjectValue) throw new Error("Select a project before searching.");
      return fetchPayload(query);
    },
    clear: browseProject,
    clearTopicFilters() {
      if (!layerSelectors.slice(0, -1).some(({ key }) => selected[key])) return;
      cancelMessageRequest();
      messageStatus = '';
      selected = selected.specific_message ? { specific_message: selected.specific_message } : {};
      resetPages();
      if (browsing && !activeRequest) void refreshBrowseMessages();
      render();
    },
  };
})();

function initializeConnections() {
  const launcher = document.querySelector("[data-connections-launcher]");
  const overlay = document.querySelector("[data-connections-overlay]");
  const confirmOverlay = document.querySelector("[data-connections-confirm-overlay]");
  const refreshOverlay = document.querySelector("[data-connection-refresh-overlay]");
  if (!launcher || !overlay || !confirmOverlay || !refreshOverlay) return;

  const list = overlay.querySelector("[data-connections-list]");
  const status = overlay.querySelector("[data-connections-status]");
  const refreshNotice = overlay.querySelector("[data-connections-refresh-notice]");
  const refreshNoticeMessage = overlay.querySelector("[data-connections-refresh-notice-message]");
  const refreshRetry = overlay.querySelector("[data-connections-refresh-retry]");
  const confirmTitle = confirmOverlay.querySelector("[data-connections-confirm-title]");
  const confirmIcon = confirmOverlay.querySelector("[data-connections-confirm-icon]");
  const confirmCopy = confirmOverlay.querySelector("[data-connections-confirm-copy]");
  const confirmNote = confirmOverlay.querySelector("[data-connections-confirm-note]");
  const confirmError = confirmOverlay.querySelector("[data-connections-confirm-error]");
  const confirmButton = confirmOverlay.querySelector("[data-connections-confirm]");
  const confirmCancel = confirmOverlay.querySelector("[data-connections-confirm-cancel]");
  const tabs = [...overlay.querySelectorAll("[data-connections-tab]")];
  let connections = [];
  let activeTab = "connected";
  let pendingDisconnect = null;
  let disconnectTrigger = null;
  let disconnectInFlight = false;
  let returnFocus = null;
  let activeRefreshJobId = null;
  let pendingRefreshJobId = null;
  let retryRefreshJobId = null;
  let refreshPollTimer = null;
  let refreshFailures = 0;
  let lockedChildren = [];

  const folderIcon = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h6l2 2h10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"></path></svg>`;
  const chatIcon = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h9a4 4 0 0 1 4 4Z"></path></svg>`;
  const warningIcon = `<svg viewBox="0 0 24 24"><path d="M12 8v5M12 17h.01"></path><path d="M10.2 4.3 2.8 17a2 2 0 0 0 1.7 3h15a2 2 0 0 0 1.7-3L13.8 4.3a2 2 0 0 0-3.6 0Z"></path></svg>`;
  const successIcon = `<svg viewBox="0 0 24 24"><path d="m6.5 12.5 3.5 3.5 7.5-8"></path><circle cx="12" cy="12" r="9"></circle></svg>`;

  const itemCount = (targetStatus) => connections.reduce((count, project) => (
    count
      + (project.status === targetStatus ? 1 : 0)
      + project.chats.filter((chat) => chat.status === targetStatus).length
  ), 0);

  const syncCounts = () => {
    ["connected", "paused"].forEach((name) => {
      const count = overlay.querySelector(`[data-connections-count="${name}"]`);
      if (count) count.textContent = String(itemCount(name));
    });
  };

  const formatActivity = (value) => {
    if (!value) return "Connected chat";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Connected chat";
    return `Active ${new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date)}`;
  };

  const resetConfirmation = (name, itemKind) => {
    confirmOverlay.classList.remove("is-success");
    confirmIcon.innerHTML = warningIcon;
    confirmTitle.textContent = "Disconnect this connection?";
    confirmCopy.textContent = `Disconnect “${name}”?`;
    confirmNote.textContent = `Context Saver will stop using this ${itemKind}. Its retained context will be permanently removed. This can’t be undone.`;
    confirmNote.hidden = false;
    confirmError.hidden = true;
    confirmCancel.hidden = false;
    confirmButton.dataset.mode = "confirm";
    confirmButton.textContent = "Disconnect";
  };

  const showDisconnectSuccess = (name, itemKind) => {
    confirmOverlay.classList.add("is-success");
    confirmIcon.innerHTML = successIcon;
    confirmTitle.textContent = `${name} successfully disconnected`;
    confirmCopy.textContent = `Context Saver no longer uses this ${itemKind}.`;
    confirmNote.textContent = `Data from this ${itemKind} will be removed after you close Connections and the memory update finishes.`;
    confirmNote.hidden = false;
    confirmCancel.hidden = true;
    confirmButton.dataset.mode = "success";
    confirmButton.textContent = "Done";
    confirmButton.disabled = false;
    confirmButton.focus();
  };

  const setRefreshLock = (locked) => {
    window.clearTimeout(refreshPollTimer);
    refreshPollTimer = null;
    refreshOverlay.hidden = !locked;
    document.body.classList.toggle("connection-refresh-active", locked);
    document.body.setAttribute("aria-busy", String(locked));
    if (locked) {
      lockedChildren = [...document.body.children].filter((child) => {
        if (child === refreshOverlay || child.inert) return false;
        child.inert = true;
        return true;
      });
      refreshOverlay.focus({ preventScroll: true });
      return;
    }
    lockedChildren.forEach((child) => { child.inert = false; });
    lockedChildren = [];
  };

  const showRefreshRetry = (jobId, message = "The memory update could not be completed.") => {
    retryRefreshJobId = jobId;
    refreshNoticeMessage.textContent = message;
    refreshNotice.hidden = !jobId;
  };

  const finishRefresh = async (failedJobId = null) => {
    activeRefreshJobId = null;
    setRefreshLock(false);
    if (failedJobId) {
      showRefreshRetry(failedJobId);
      if (overlay.hidden) open(refreshRetry);
      else refreshRetry.focus({ preventScroll: true });
      return;
    }
    showRefreshRetry(null);
    await Promise.all([loadConnections(), loadConnectedProjects()]);
    await resumeActiveRefresh();
  };

  const pollRefresh = async () => {
    const jobId = activeRefreshJobId;
    if (!jobId) return;
    try {
      const response = await fetch(`/api/connections/refresh-status?job=${encodeURIComponent(jobId)}`, { cache: "no-store" });
      const payload = await response.json();
      if (activeRefreshJobId !== jobId) return;
      if (!response.ok) throw new Error(payload.error || "Refresh status is unavailable");
      refreshFailures = 0;
      if (payload.state === "complete") {
        await finishRefresh();
        return;
      }
      if (["failed", "pending", "idle"].includes(payload.state)) {
        await finishRefresh(jobId);
        return;
      }
    } catch (_error) {
      if (activeRefreshJobId !== jobId) return;
      refreshFailures += 1;
      if (refreshFailures >= 8) {
        await finishRefresh(jobId);
        return;
      }
    }
    refreshPollTimer = window.setTimeout(pollRefresh, 350);
  };

  const startRefreshLock = (jobId) => {
    if (!jobId || activeRefreshJobId === jobId) return;
    activeRefreshJobId = jobId;
    refreshFailures = 0;
    setRefreshLock(true);
    pollRefresh();
  };

  const resumeActiveRefresh = async () => {
    try {
      const response = await fetch("/api/connections/refresh-status", { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok || !payload.id || activeRefreshJobId || pendingRefreshJobId) return;
      if (["queued", "running"].includes(payload.state)) {
        startRefreshLock(payload.id);
      } else if (payload.retryable) {
        showRefreshRetry(payload.id, payload.state === "pending" ? "A memory update is pending." : undefined);
      }
    } catch (_error) {
      // A missing prior refresh must not block the viewer from opening.
    }
  };

  const actionMarkup = ({ kind, status: itemStatus, projectPath, threadId = "", name, disconnectPending }) => {
    const primaryAction = itemStatus === "paused" ? "resume" : "pause";
    const primaryLabel = itemStatus === "paused" ? "Resume" : "Pause";
    return `
      <div class="connection-actions">
        ${disconnectPending ? "" : `<button class="connections-action" type="button" data-connection-action="${primaryAction}" data-kind="${kind}" data-project-path="${escapeHtml(projectPath)}" data-thread-id="${escapeHtml(threadId)}" data-name="${escapeHtml(name)}">${primaryLabel}</button>`}
        <button class="connections-action connections-action--danger" type="button" data-connection-action="disconnect" data-kind="${kind}" data-project-path="${escapeHtml(projectPath)}" data-thread-id="${escapeHtml(threadId)}" data-name="${escapeHtml(name)}">${disconnectPending ? "Retry disconnect" : "Disconnect"}</button>
      </div>
    `;
  };

  const render = () => {
    syncCounts();
    const visibleGroups = connections.map((project) => {
      const visibleChats = project.chats.filter((chat) => chat.status === activeTab);
      const projectMatches = project.status === activeTab;
      if (!projectMatches && !visibleChats.length) return "";
      const projectAction = projectMatches
        ? actionMarkup({ kind: "project", status: project.status, projectPath: project.path, name: project.name, disconnectPending: project.disconnectPending })
        : "";
      const chatRows = visibleChats.map((chat) => `
        <div class="connection-row connection-row--chat">
          <span class="connection-kind-icon">${chatIcon}</span>
          <div class="connection-copy">
            <p class="connection-name" title="${escapeHtml(chat.title)}">${escapeHtml(chat.title)}</p>
            <div class="connection-meta"><i class="connection-status-dot${chat.status === "paused" ? " is-paused" : ""}" aria-hidden="true"></i><span>${chat.disconnectPending ? "Disconnection pending" : chat.status === "paused" ? "Paused chat" : escapeHtml(formatActivity(chat.lastActivityAt))}</span></div>
          </div>
          ${project.disconnectPending ? "" : actionMarkup({ kind: "chat", status: chat.status, projectPath: project.path, threadId: chat.id, name: chat.title, disconnectPending: chat.disconnectPending })}
        </div>
      `).join("");
      return `
        <section class="connection-group" aria-label="${escapeHtml(project.name)}">
          <div class="connection-row connection-row--project">
            <span class="connection-kind-icon">${folderIcon}</span>
            <div class="connection-copy">
              <p class="connection-name" title="${escapeHtml(project.name)}">${escapeHtml(project.name)}</p>
              <div class="connection-meta"><i class="connection-status-dot${project.status === "paused" ? " is-paused" : ""}" aria-hidden="true"></i><span class="connection-meta__path" title="${escapeHtml(project.path)}">${project.disconnectPending ? "Disconnection pending" : projectMatches ? (project.status === "paused" ? "Paused folder" : `${project.chatCount} connected ${project.chatCount === 1 ? "chat" : "chats"}`) : escapeHtml(project.path)}</span></div>
            </div>
            ${projectAction}
          </div>
          ${chatRows}
        </section>
      `;
    }).join("");

    status.hidden = true;
    if (visibleGroups) {
      list.innerHTML = visibleGroups;
      return;
    }
    const emptyLabel = activeTab === "paused" ? "Nothing is paused" : "No active connections";
    const emptyCopy = activeTab === "paused"
      ? "Project folders and chats you pause will wait here until you resume them."
      : "Connect Context Saver to a project folder or chat to see it here.";
    list.innerHTML = `
      <div class="connections-empty">
        <div>${folderIcon}<strong>${emptyLabel}</strong><p>${emptyCopy}</p></div>
      </div>
    `;
  };

  const selectTab = (name) => {
    activeTab = name;
    tabs.forEach((item) => {
      const selected = item.dataset.connectionsTab === name;
      item.classList.toggle("is-active", selected);
      item.setAttribute("aria-selected", String(selected));
    });
    render();
  };

  const loadConnections = async ({ showPending = false } = {}) => {
    status.hidden = false;
    status.textContent = "Loading connections…";
    list.replaceChildren();
    try {
      const response = await fetch("/api/connections", { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Connections could not be loaded");
      connections = Array.isArray(payload.connections) ? payload.connections : [];
      if (showPending && connections.some((project) => project.disconnectPending || project.chats.some((chat) => chat.disconnectPending))) {
        selectTab("paused");
      } else {
        render();
      }
    } catch (error) {
      status.hidden = false;
      status.textContent = error.message || "Connections could not be loaded.";
    }
  };

  const open = (focusTarget = overlay.querySelector("[data-connections-close]")) => {
    returnFocus = document.activeElement;
    overlay.hidden = false;
    document.body.classList.add("connections-open");
    loadConnections({ showPending: true });
    requestAnimationFrame(() => focusTarget?.focus({ preventScroll: true }));
  };

  const close = () => {
    if (!confirmOverlay.hidden) return;
    overlay.hidden = true;
    document.body.classList.remove("connections-open");
    returnFocus?.focus?.();
    if (pendingRefreshJobId) {
      const jobId = pendingRefreshJobId;
      pendingRefreshJobId = null;
      startRefreshLock(jobId);
    }
  };

  refreshRetry.addEventListener("click", async () => {
    const jobId = retryRefreshJobId;
    if (!jobId) return;
    refreshRetry.disabled = true;
    try {
      const response = await fetch("/api/connections/refresh-retry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jobId }),
      });
      const payload = await response.json();
      if (!response.ok || payload.id !== jobId) throw new Error("Memory update could not be retried");
      if (payload.state === "complete") {
        await finishRefresh();
      } else if (["queued", "running"].includes(payload.state)) {
        showRefreshRetry(null);
        if (!overlay.hidden) close();
        startRefreshLock(jobId);
      } else {
        showRefreshRetry(jobId);
      }
    } catch (_error) {
      showRefreshRetry(jobId, "The memory update could not be started. Try again.");
    } finally {
      refreshRetry.disabled = false;
    }
  });

  const closeConfirm = () => {
    if (disconnectInFlight) return;
    confirmOverlay.hidden = true;
    overlay.inert = false;
    pendingDisconnect = null;
    const focusTarget = disconnectTrigger?.isConnected
      ? disconnectTrigger
      : overlay.querySelector("[data-connections-close]");
    focusTarget?.focus();
    disconnectTrigger = null;
  };

  const runAction = async (action) => {
    const buttons = [...overlay.querySelectorAll("[data-connection-action]")];
    buttons.forEach((button) => { button.disabled = true; });
    try {
      const response = await fetch("/api/connections/action", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(action),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "The connection could not be updated");
      connections = Array.isArray(payload.connections) ? payload.connections : [];
      render();
      await loadConnectedProjects();
      return payload;
    } catch (error) {
      status.hidden = false;
      status.textContent = error.message || "The connection could not be updated.";
      return null;
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
    }
  };

  launcher.addEventListener("click", () => open());
  overlay.querySelectorAll("[data-connections-close]").forEach((button) => button.addEventListener("click", close));
  overlay.addEventListener("pointerdown", (event) => {
    if (event.target === overlay) close();
  });
  tabs.forEach((tab) => tab.addEventListener("click", () => selectTab(tab.dataset.connectionsTab)));
  list.addEventListener("click", (event) => {
    const button = event.target.closest("[data-connection-action]");
    if (!button) return;
    const action = {
      action: button.dataset.connectionAction,
      kind: button.dataset.kind,
      projectPath: button.dataset.projectPath,
      threadId: button.dataset.threadId || undefined,
    };
    if (action.action !== "disconnect") {
      runAction(action);
      return;
    }
    pendingDisconnect = action;
    disconnectTrigger = button;
    const itemKind = action.kind === "project" ? "project folder" : "chat";
    pendingDisconnect.name = button.dataset.name;
    pendingDisconnect.itemKind = itemKind;
    resetConfirmation(pendingDisconnect.name, itemKind);
    confirmOverlay.hidden = false;
    overlay.inert = true;
    confirmCancel.focus();
  });
  confirmOverlay.querySelector("[data-connections-confirm-cancel]").addEventListener("click", closeConfirm);
  confirmOverlay.addEventListener("pointerdown", (event) => {
    if (event.target === confirmOverlay) closeConfirm();
  });
  confirmButton.addEventListener("click", async () => {
    if (confirmButton.dataset.mode === "success") {
      closeConfirm();
      return;
    }
    if (!pendingDisconnect) return;
    const action = pendingDisconnect;
    disconnectInFlight = true;
    confirmError.hidden = true;
    confirmCancel.disabled = true;
    confirmButton.disabled = true;
    confirmButton.textContent = "Disconnecting…";
    const result = await runAction(action);
    disconnectInFlight = false;
    confirmCancel.disabled = false;
    if (!result) {
      confirmButton.disabled = false;
      confirmButton.textContent = "Disconnect";
      confirmError.hidden = false;
      confirmError.textContent = "The disconnection could not be completed. Try disconnecting again.";
      confirmButton.focus();
      return;
    }
    showDisconnectSuccess(action.name, action.itemKind);
    if (result.refreshJobId) pendingRefreshJobId = result.refreshJobId;
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || activeRefreshJobId) return;
    if (!confirmOverlay.hidden) closeConfirm();
    else if (!overlay.hidden) close();
  });
  resumeActiveRefresh();
}

initializeConnections();

function initializeSpotlight(host) {
  const input = host.querySelector("[data-spotlight-input]");
  const placeholder = host.querySelector("[data-spotlight-placeholder]");
  const results = host.querySelector("[data-spotlight-results]");
  const errorStatus = host.querySelector("[data-spotlight-error]");
  const messageToggle = host.querySelector("[data-message-search-toggle]");
  const heroDownButton = document.querySelector(".slide-down-button--hero");
  const heroDownLabel = heroDownButton?.querySelector("[data-hero-down-label]");
  let placeholderTimer;
  let committedQuery = "";
  let submission = null;

  const setSearchError = (message = "") => {
    errorStatus.textContent = message;
  };

  const setSearchLoading = (loading) => {
    input.readOnly = loading;
    if (heroDownButton) {
      heroDownButton.classList.toggle("is-loading", loading);
      heroDownButton.disabled = loading;
      if (loading) heroDownButton.setAttribute("aria-busy", "true");
      else heroDownButton.removeAttribute("aria-busy");
    }
    dots.forEach((dot) => { dot.disabled = loading; });
  };

  const syncHeroDownButton = () => {
    const hasSubmittedQuery = Boolean(committedQuery);
    const label = hasSubmittedQuery ? "View results" : "See what you've been chatting about";
    if (!heroDownButton || !heroDownLabel) return;
    heroDownButton.dataset.hasSearchQuery = String(hasSubmittedQuery);
    heroDownButton.setAttribute("aria-label", label);
    heroDownLabel.textContent = label;
    resultQueryHeadings.forEach((heading, index) => {
      heading.textContent = committedQuery;
      heading.title = committedQuery;
      heading.hidden = !hasSubmittedQuery;
      sections[index + 1]?.classList.toggle("has-search-query", hasSubmittedQuery);
    });
  };

  const clearCommittedSearch = ({ reloadBrowse = true } = {}) => {
    submission = null;
    committedQuery = "";
    input.value = "";
    if (reloadBrowse) contextExplorer.clear();
    setSearchLoading(false);
    setSearchError();
    host.classList.remove("has-results");
    results.hidden = true;
    results.replaceChildren();
    placeholder.classList.remove("is-hidden");
    syncHeroDownButton();
  };

  const submitDraft = async () => {
    const submittedQuery = input.value.trim();
    if (!submittedQuery) {
      clearCommittedSearch();
      return;
    }
    if (submittedQuery === committedQuery) {
      input.value = committedQuery;
      placeholder.classList.add("is-hidden");
      return;
    }
    if (submission) return;
    const current = {};
    submission = current;
    setSearchError();
    setSearchLoading(true);
    try {
      const displayed = await contextExplorer.search(submittedQuery);
      if (submission !== current || !displayed) return;
      committedQuery = submittedQuery;
      input.value = committedQuery;
      syncHeroDownButton();
    } catch (error) {
      if (submission === current) setSearchError(error instanceof Error ? error.message : "Search failed.");
    } finally {
      if (submission === current) {
        submission = null;
        setSearchLoading(false);
      }
    }
  };

  const setPlaceholder = (text, overlay = false) => {
    window.clearTimeout(placeholderTimer);
    placeholder.classList.add("is-changing");
    placeholderTimer = window.setTimeout(() => {
      placeholder.textContent = text;
      placeholder.classList.toggle("is-overlay", overlay);
      placeholder.classList.remove("is-changing");
    }, 100);
  };

  input.addEventListener("input", () => {
    syncHeroDownButton();
    const hasQuery = Boolean(input.value.trim());
    if (!hasQuery) {
      clearCommittedSearch();
      return;
    }
    host.classList.remove("has-results");
    results.hidden = true;
    results.replaceChildren();
    placeholder.classList.add("is-hidden");
  });
  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    void submitDraft();
  });
  input.addEventListener("blur", (event) => {
    if (event.relatedTarget === messageToggle) {
      return;
    }
    if (heroDownButton?.classList.contains("is-loading")) return;
    if (input.value.trim() !== committedQuery) {
      void submitDraft();
      return;
    }
    input.value = committedQuery;
    placeholder.classList.toggle("is-hidden", Boolean(committedQuery));
  });
  input.addEventListener("search", () => {
    if (!input.value) clearCommittedSearch();
  });
  messageToggle?.addEventListener("mouseenter", () => {
    if (!input.value) setPlaceholder(projectSearchPlaceholder(!messageSearchOnly));
  });
  messageToggle?.addEventListener("mouseleave", () => {
    if (!input.value) setPlaceholder(projectSearchPlaceholder());
  });
  messageToggle?.addEventListener("mousedown", (event) => {
    // WebKit blurs the field without reporting the clicked button as its next
    // focus target. Keep mouse activation from submitting the draft.
    if (document.activeElement === input) event.preventDefault();
  });
  messageToggle?.addEventListener("click", () => {
    messageSearchOnly = !messageSearchOnly;
    messageToggle.setAttribute("aria-pressed", String(messageSearchOnly));
    host.classList.toggle("is-message-only", messageSearchOnly);
    if (messageSearchOnly) contextExplorer.clearTopicFilters();
    syncSlideMode();
    const label = projectSearchPlaceholder();
    input.setAttribute("aria-label", label);
    if (!input.value) setPlaceholder(label);
    if (input.value !== committedQuery) {
      requestAnimationFrame(() => input.focus());
    }
  });
  document.addEventListener("projectchange", () => {
    const label = projectSearchPlaceholder();
    if (submission || committedQuery) clearCommittedSearch({ reloadBrowse: false });
    setSearchError();
    input.setAttribute("aria-label", label);
    if (!input.value) setPlaceholder(label);
  });
  syncHeroDownButton();
}

const spotlight = document.querySelector("[data-spotlight]");
if (spotlight) initializeSpotlight(spotlight);

function initializeAmbientBackground() {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const borderTargets = [...document.querySelectorAll(".feature-card, .combobox-trigger")];
  const chromeArcs = window.createChromeArcsBackground?.(document.querySelector("[data-chrome-arcs]"));
  if (!chromeArcs) return;
  borderTargets.forEach((target, index) => {
    target.style.setProperty("--card-border-angle", `${index * 23}deg`);
  });

  let lastScrollY = window.scrollY;
  let currentRate = 0;
  let targetRate = 0;
  let rateFrame = 0;
  let settleTimer = 0;
  let borderAngle = 0;
  let lastFrameTime = performance.now();

  if (reducedMotion) {
    chromeArcs.setPlaybackRate(0);
    return;
  }

  const updateRate = (frameTime = performance.now()) => {
    const elapsed = Math.min(48, Math.max(0, frameTime - lastFrameTime));
    lastFrameTime = frameTime;
    const easing = targetRate > currentRate ? 0.36 : 0.55;
    currentRate += (targetRate - currentRate) * easing;
    chromeArcs.setPlaybackRate(currentRate);
    borderAngle = (borderAngle + currentRate * elapsed * 0.045) % 360;
    borderTargets.forEach((target, index) => {
      target.style.setProperty("--card-border-angle", `${borderAngle + index * 23}deg`);
    });
    if (Math.abs(targetRate - currentRate) > 0.01 || targetRate !== 0) {
      rateFrame = requestAnimationFrame(updateRate);
    } else {
      currentRate = 0;
      chromeArcs.setPlaybackRate(0);
      rateFrame = 0;
    }
  };

  const startRateTransition = () => {
    if (!rateFrame) rateFrame = requestAnimationFrame(updateRate);
  };

  window.addEventListener("scroll", () => {
    const nextScrollY = window.scrollY;
    const impulse = Math.abs(nextScrollY - lastScrollY);
    lastScrollY = nextScrollY;
    targetRate = Math.max(targetRate, Math.min(5, 0.6 + impulse * 0.08));
    startRateTransition();
    window.clearTimeout(settleTimer);
    settleTimer = window.setTimeout(() => {
      targetRate = 0;
      startRateTransition();
    }, 60);
  }, { passive: true });
}

initializeAmbientBackground();

let activeSection = -1;
let navigationEpoch = 0;
let navigationTarget = null;
let navigationStartTimer = 0;
let navigationSettleTimer = 0;
let ticking = false;
let scrollVisualSettleTimer = 0;
let lastVisualScrollY = window.scrollY;
let headingScrollDirection = 1;

function setActiveSection(index) {
  if (index === activeSection) return;
  activeSection = index;
  sections[index]?.querySelectorAll(".slide-up-button").forEach((button) => {
    button.classList.remove("is-leaving");
  });
  dots.forEach((dot, dotIndex) => {
    dot.classList.toggle("is-active", dotIndex === index);
  });
}

function syncVisualTracks() {
  sectionsTrack.style.transform = `translate3d(0, ${-window.scrollY}px, 0)`;
}

function cancelSlideNavigation() {
  window.clearTimeout(navigationStartTimer);
  window.clearTimeout(navigationSettleTimer);
  navigationTarget = null;
  return ++navigationEpoch;
}

function sectionScrollTop(section) {
  // Preserve fractional layout pixels, including desktop browser zoom.
  return section.getBoundingClientRect().top + window.scrollY;
}

function alignSlide(index, epoch) {
  const section = sections[index];
  if (epoch !== navigationEpoch || !section || section.hidden) return;
  syncVisualTracks();
  window.scrollTo({ top: sectionScrollTop(section), behavior: 'instant' });
  updateScrollPosition();
  // A cancelled scroll may never have changed the active index.
  section.querySelectorAll('.slide-up-button').forEach((button) => button.classList.remove('is-leaving'));
}

function settleSlide(index) {
  if (!sections[index] || sections[index].hidden) return null;
  const epoch = cancelSlideNavigation();
  alignSlide(index, epoch);
  requestAnimationFrame(() => alignSlide(index, epoch));
  return epoch;
}

function scheduleNavigationSettle() {
  if (navigationTarget === null) return;
  const epoch = navigationEpoch;
  window.clearTimeout(navigationSettleTimer);
  navigationSettleTimer = window.setTimeout(() => {
    if (epoch === navigationEpoch && navigationTarget !== null) settleSlide(navigationTarget);
  }, 180);
}

function updateScrollPosition() {
  syncVisualTracks();
  const documentHeight = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
  const progress = Math.min(Math.max(window.scrollY / documentHeight, 0), 1);
  progressBar.style.transform = `scaleX(${progress})`;

  const viewportCenter = window.innerHeight / 2;
  let nearestIndex = 0;
  let nearestDistance = Number.POSITIVE_INFINITY;
  sections.forEach((section, index) => {
    if (section.hidden) return;
    const sectionCenter = section.offsetTop - window.scrollY + section.offsetHeight / 2;
    const distance = Math.abs(sectionCenter - viewportCenter);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = index;
    }
  });
  setActiveSection(nearestIndex);
}

function scrollToSection(index, { fade = false } = {}) {
  const section = sections[index];
  if (!section || section.hidden) return;
  const epoch = cancelSlideNavigation();
  if (index === activeSection && Math.abs(section.getBoundingClientRect().top) < 1) {
    alignSlide(index, epoch);
    return;
  }
  navigationTarget = index;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (fade) sections[activeSection]?.querySelectorAll('.slide-up-button').forEach((button) => button.classList.add('is-leaving'));
  const beginScroll = () => {
    if (epoch !== navigationEpoch) return;
    syncVisualTracks();
    window.scrollTo({ top: sectionScrollTop(section), behavior: reducedMotion ? 'instant' : 'smooth' });
    scheduleNavigationSettle();
  };
  if (fade && !reducedMotion) navigationStartTimer = window.setTimeout(beginScroll, 60);
  else beginScroll();
}

function syncScrollSpace() {
  scrollSpacer.style.height = `${sectionsTrack.scrollHeight}px`;
}

function syncSlideMode() {
  const epoch = cancelSlideNavigation();
  const visibleIndices = sections.map((_, index) => index).filter((index) => (
    !messageSearchOnly || index === 0 || index === sections.length - 1
  ));
  const destination = visibleIndices.includes(activeSection) ? activeSection : 0;
  sections.forEach((section, index) => {
    const position = visibleIndices.indexOf(index);
    section.hidden = position < 0;
    section.inert = position < 0;
    const up = section.querySelector('.slide-up-button:not(.slide-down-button)');
    const down = section.querySelector('.slide-down-button');
    if (up) {
      up.hidden = position <= 0;
      if (position > 0) up.dataset.scrollTo = String(visibleIndices[position - 1]);
    }
    if (down) {
      down.hidden = position < 0 || position === visibleIndices.length - 1;
      if (!down.hidden) down.dataset.scrollTo = String(visibleIndices[position + 1]);
    }
    section.querySelectorAll('.slide-up-button').forEach((button) => button.classList.remove('is-leaving'));
  });
  dots.forEach((dot) => {
    dot.hidden = !visibleIndices.includes(Number(dot.dataset.sectionIndex));
  });
  syncScrollSpace();
  activeSection = -1;
  const alignDestination = () => {
    if (epoch !== navigationEpoch) return;
    alignSlide(destination, epoch);
  };
  // Native smooth scrolling can deliver one compositor frame after the mode's
  // layout change. Reconcile after that frame too; a newer navigation wins.
  alignDestination();
  requestAnimationFrame(alignDestination);
}

dots.forEach((dot) => dot.addEventListener("click", () => scrollToSection(Number(dot.dataset.sectionIndex))));
document.querySelectorAll("[data-scroll-to]").forEach((button) => {
  button.addEventListener("click", () => {
    scrollToSection(Number(button.dataset.scrollTo), { fade: true });
  });
});

const blockedPageScrollKeys = new Set([
  "ArrowUp",
  "ArrowDown",
  "PageUp",
  "PageDown",
  "Home",
  "End",
  " ",
  "Spacebar",
]);

function isInsideScrollableControl(target) {
  return target instanceof Element && Boolean(target.closest(".combobox-list, .node-detail-content, .feature-list"));
}

window.addEventListener("wheel", (event) => {
  if (!isInsideScrollableControl(event.target)) event.preventDefault();
}, { passive: false, capture: true });

window.addEventListener("touchmove", (event) => {
  if (!isInsideScrollableControl(event.target)) event.preventDefault();
}, { passive: false, capture: true });

window.addEventListener("keydown", (event) => {
  if (!blockedPageScrollKeys.has(event.key)) return;
  const target = event.target instanceof Element ? event.target : null;
  if (target?.closest(".node-detail-content, .feature-list")) return;
  if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
  if (target?.closest("button") && (event.key === " " || event.key === "Spacebar")) return;
  event.preventDefault();
}, { capture: true });

window.addEventListener("scroll", () => {
  syncVisualTracks();
  scheduleNavigationSettle();
  const scrollY = window.scrollY;
  const direction = Math.sign(scrollY - lastVisualScrollY);
  lastVisualScrollY = scrollY;
  if (direction && direction !== headingScrollDirection) {
    headingScrollDirection = direction;
    sectionsTrack.style.setProperty("--heading-scroll-direction", String(direction));
  }
  document.body.classList.add("is-scrolling");
  window.clearTimeout(scrollVisualSettleTimer);
  scrollVisualSettleTimer = window.setTimeout(() => {
    document.body.classList.remove("is-scrolling");
  }, 90);
  if (ticking) return;
  ticking = true;
  requestAnimationFrame(() => {
    updateScrollPosition();
    ticking = false;
  });
}, { passive: true });
window.addEventListener("resize", () => {
  const destination = navigationTarget ?? (activeSection >= 0 ? activeSection : 0);
  syncScrollSpace();
  settleSlide(destination);
}, { passive: true });

syncScrollSpace();
if (isReload) window.scrollTo({ top: 0, behavior: "instant" });
updateScrollPosition();
