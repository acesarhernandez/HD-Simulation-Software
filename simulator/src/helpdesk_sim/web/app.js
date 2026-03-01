const state = {
  selectedSessionId: null,
  selectedTicketId: null,
  currentSessionTickets: [],
  sessions: [],
  profileDefinitions: [],
  pendingRequests: 0,
  llmRuntimeStatus: null,
  catalog: {
    ticket_types: [],
    departments: [],
    scenarios: [],
    personas: [],
  },
};

const THEME_STORAGE_KEY = "helpdesk_sim_theme_mode";
const RAW_DISPLAY_STORAGE_KEY = "helpdesk_sim_show_raw";
const systemColorScheme = window.matchMedia("(prefers-color-scheme: dark)");

const refs = {
  healthBadge: document.getElementById("healthBadge"),
  requestStatusBadge: document.getElementById("requestStatusBadge"),
  themeLauncher: document.getElementById("themeLauncher"),
  themePanel: document.getElementById("themePanel"),
  themeModeButtons: Array.from(document.querySelectorAll(".theme-mode-btn[data-theme-mode]")),
  showRawJson: document.getElementById("showRawJson"),
  profileSelect: document.getElementById("profileSelect"),
  profileQuickInfo: document.getElementById("profileQuickInfo"),
  clockInBtn: document.getElementById("clockInBtn"),
  clockOutAllBtn: document.getElementById("clockOutAllBtn"),
  clockOutAllBtnSessions: document.getElementById("clockOutAllBtnSessions"),
  schedulerBtn: document.getElementById("schedulerBtn"),
  pollerBtn: document.getElementById("pollerBtn"),
  refreshBtn: document.getElementById("refreshBtn"),
  actionResult: document.getElementById("actionResult"),
  profileDefinitionList: document.getElementById("profileDefinitionList"),
  manualSessionSelect: document.getElementById("manualSessionSelect"),
  manualCount: document.getElementById("manualCount"),
  manualTierSelect: document.getElementById("manualTierSelect"),
  manualTypeSelect: document.getElementById("manualTypeSelect"),
  manualDeptSelect: document.getElementById("manualDeptSelect"),
  manualPersonaSelect: document.getElementById("manualPersonaSelect"),
  manualScenarioSelect: document.getElementById("manualScenarioSelect"),
  manualAutofillBtn: document.getElementById("manualAutofillBtn"),
  manualGenerateBtn: document.getElementById("manualGenerateBtn"),
  manualResult: document.getElementById("manualResult"),
  sessionMeta: document.getElementById("sessionMeta"),
  sessionList: document.getElementById("sessionList"),
  selectedSession: document.getElementById("selectedSession"),
  closeAllSessionTicketsBtn: document.getElementById("closeAllSessionTicketsBtn"),
  deleteAllSessionTicketsBtn: document.getElementById("deleteAllSessionTicketsBtn"),
  deleteFallbackClose: document.getElementById("deleteFallbackClose"),
  deleteStatusBanner: document.getElementById("deleteStatusBanner"),
  ticketTableBody: document.getElementById("ticketTableBody"),
  ticketInfoResult: document.getElementById("ticketInfoResult"),
  ticketCoachingResult: document.getElementById("ticketCoachingResult"),
  mentorTicketId: document.getElementById("mentorTicketId"),
  mentorPrompt: document.getElementById("mentorPrompt"),
  mentorBtn: document.getElementById("mentorBtn"),
  mentorResult: document.getElementById("mentorResult"),
  hintTicketId: document.getElementById("hintTicketId"),
  hintLevel: document.getElementById("hintLevel"),
  hintBtn: document.getElementById("hintBtn"),
  hintResult: document.getElementById("hintResult"),
  dailyReportBtn: document.getElementById("dailyReportBtn"),
  weeklyReportBtn: document.getElementById("weeklyReportBtn"),
  reportResult: document.getElementById("reportResult"),
  llmStatusBadge: document.getElementById("llmStatusBadge"),
  llmHostBadge: document.getElementById("llmHostBadge"),
  llmStatusRefreshBtn: document.getElementById("llmStatusRefreshBtn"),
  wakeEngineBtn: document.getElementById("wakeEngineBtn"),
  llmStatusResult: document.getElementById("llmStatusResult"),
};

function updateRequestStatus() {
  if (!refs.requestStatusBadge) return;

  if (state.pendingRequests > 0) {
    refs.requestStatusBadge.textContent =
      state.pendingRequests === 1 ? "Working..." : `Working (${state.pendingRequests})`;
    refs.requestStatusBadge.className = "badge warn";
    return;
  }

  refs.requestStatusBadge.textContent = "Idle";
  refs.requestStatusBadge.className = "badge badge-muted";
}

async function api(path, options = {}) {
  state.pendingRequests += 1;
  updateRequestStatus();

  const init = {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  };

  try {
    const response = await fetch(path, init);
    const raw = await response.text();

    let data = null;
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch {
        data = raw;
      }
    }

    if (!response.ok) {
      const detail =
        (data && typeof data === "object" && (data.detail || data.error_human || data.error)) ||
        `${response.status} ${response.statusText}`;
      throw new Error(String(detail));
    }

    return data;
  } finally {
    state.pendingRequests = Math.max(0, state.pendingRequests - 1);
    updateRequestStatus();
  }
}

function writeLog(element, payload) {
  if (typeof payload === "string") {
    element.textContent = payload;
    return;
  }
  element.textContent = JSON.stringify(payload, null, 2);
}

function writeHumanAndJson(element, summary, payload) {
  if (!payload || typeof payload === "string" || !shouldShowRaw()) {
    element.textContent = summary || String(payload || "");
    return;
  }
  element.textContent = `${summary}\n\nRaw JSON:\n${JSON.stringify(payload, null, 2)}`;
}

function clearDeleteBanner() {
  if (!refs.deleteStatusBanner) return;
  refs.deleteStatusBanner.hidden = true;
  refs.deleteStatusBanner.className = "inline-alert";
  refs.deleteStatusBanner.textContent = "";
}

function showDeleteBanner(message, kind = "success") {
  if (!refs.deleteStatusBanner) return;
  refs.deleteStatusBanner.hidden = false;
  refs.deleteStatusBanner.className = `inline-alert ${kind === "error" ? "error" : "success"}`;
  refs.deleteStatusBanner.textContent = message;
}

function setBusy(button, busy) {
  if (!button) return;
  if (!button.dataset.idleLabel) {
    button.dataset.idleLabel = button.textContent.trim();
  }

  button.disabled = busy;
  button.style.opacity = busy ? "0.72" : "1";
  button.classList.toggle("is-busy", busy);
  button.setAttribute("aria-busy", busy ? "true" : "false");
  button.textContent = busy ? button.dataset.busyLabel || "Working..." : button.dataset.idleLabel;
}

function shouldShowRaw() {
  return refs.showRawJson?.value === "on";
}

function pickRandom(items) {
  if (!items.length) return null;
  return items[Math.floor(Math.random() * items.length)] ?? null;
}

function pickWeighted(items, weightsByKey, getKey) {
  const weighted = items
    .map((item) => {
      const key = getKey(item);
      const raw = Number(weightsByKey?.[key] ?? 0);
      const weight = Number.isFinite(raw) && raw > 0 ? raw : 0;
      return { item, weight };
    })
    .filter((entry) => entry.weight > 0);

  if (!weighted.length) {
    return pickRandom(items);
  }

  const total = weighted.reduce((sum, entry) => sum + entry.weight, 0);
  let roll = Math.random() * total;
  for (const entry of weighted) {
    roll -= entry.weight;
    if (roll <= 0) return entry.item;
  }

  return weighted[weighted.length - 1]?.item ?? null;
}

function toLocalTime(iso) {
  if (!iso) return "-";
  const date = new Date(iso);
  return date.toLocaleString();
}

function renderProfileDefinitions() {
  const definitions = [...state.profileDefinitions];
  if (!definitions.length) {
    refs.profileDefinitionList.className = "definition-list empty";
    refs.profileDefinitionList.textContent = "No profile definitions found.";
    return;
  }

  refs.profileDefinitionList.className = "definition-list";
  refs.profileDefinitionList.innerHTML = "";

  definitions.forEach((profile) => {
    const tierWeights = Object.entries(profile.tier_weights || {})
      .map(([tier, value]) => `${tier}: ${value}%`)
      .join(" | ");

    const item = document.createElement("div");
    item.className = "definition-item";
    item.innerHTML = `
      <div class="definition-title">${profile.name}</div>
      <div class="definition-sub">${profile.description || "No description set."}</div>
      <div class="definition-sub">Cadence: every ${profile.cadence_minutes}m | Window Load: ${profile.tickets_per_window_min}-${profile.tickets_per_window_max}</div>
      <div class="definition-sub">Delivery: ${profile.trickle_mode ? `trickle (${profile.trickle_max_per_tick} per scheduler tick)` : "window burst"}</div>
      <div class="definition-sub">Hours: ${profile.duration_hours}h | Business-hours gate: ${profile.business_hours_only ? "on" : "off"}</div>
      <div class="definition-sub">Tier Mix: ${tierWeights || "not set"}</div>
    `;
    refs.profileDefinitionList.append(item);
  });
}

function renderSelectedProfileSummary() {
  if (!refs.profileQuickInfo) return;

  const selectedName = refs.profileSelect.value;
  const profile = state.profileDefinitions.find((item) => item.name === selectedName);

  if (!profile) {
    refs.profileQuickInfo.textContent = "Select a day profile to review how that shift will behave.";
    return;
  }

  const tierMix = Object.entries(profile.tier_weights || {})
    .map(([tier, value]) => `${tier}: ${value}%`)
    .join(" | ");

  const topTypes = Object.entries(profile.scenario_type_weights || {})
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 3)
    .map(([name, value]) => `${name} (${value}%)`)
    .join(" | ");

  const delivery = profile.trickle_mode
    ? `Trickle mode is on (${profile.trickle_max_per_tick} ticket max per scheduler run).`
    : "Tickets are delivered in window bursts.";

  refs.profileQuickInfo.textContent = [
    `${profile.name}: ${profile.description || "No description set."}`,
    `Runs for ${profile.duration_hours} hours. Scheduler window: every ${profile.cadence_minutes} minutes, with ${profile.tickets_per_window_min}-${profile.tickets_per_window_max} tickets per window.`,
    delivery,
    `Business-hours gate: ${profile.business_hours_only ? "on" : "off"}.`,
    `Tier mix: ${tierMix || "not set"}.`,
    `Most likely ticket types: ${topTypes || "not set"}.`,
  ].join(" ");
}

function renderSessions() {
  const sessions = [...state.sessions].sort(
    (a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
  );

  refs.sessionMeta.textContent = `${sessions.length} active`;

  if (!sessions.length) {
    refs.sessionList.className = "session-list empty";
    refs.sessionList.textContent = "No active sessions yet.";
    return;
  }

  refs.sessionList.className = "session-list";
  refs.sessionList.innerHTML = "";

  sessions.forEach((session) => {
    const item = document.createElement("div");
    item.className = `session-item${state.selectedSessionId === session.id ? " active" : ""}`;

    const title = document.createElement("div");
    title.className = "session-head";
    title.innerHTML = `
      <span class="session-title">${session.profile_name}</span>
      <span class="meta">${session.status}</span>
    `;

    const pendingBatches = Array.isArray(session.config?._runtime_pending_batches)
      ? session.config._runtime_pending_batches
      : [];
    const pendingCount = pendingBatches.reduce((total, batch) => {
      const value = Number.parseInt(String(batch?.remaining ?? ""), 10);
      return Number.isNaN(value) ? total : total + value;
    }, 0);

    const sub = document.createElement("div");
    sub.className = "session-sub";
    sub.textContent = `Tickets: ${session.ticket_count} | Pending queue: ${pendingCount} | Next window: ${toLocalTime(session.next_window_at)}`;

    const actions = document.createElement("div");
    actions.className = "session-head";

    const openBtn = document.createElement("button");
    openBtn.className = "btn";
    openBtn.textContent = "Open";
    openBtn.addEventListener("click", () => loadSessionDetail(session.id));

    const closeBtn = document.createElement("button");
    closeBtn.className = "btn";
    closeBtn.textContent = "Clock Out";
    closeBtn.addEventListener("click", () => clockOutSession(session.id));

    actions.append(openBtn, closeBtn);
    item.append(title, sub, actions);
    refs.sessionList.append(item);
  });
}

function renderTickets(tickets) {
  if (!tickets.length) {
    refs.ticketTableBody.innerHTML =
      '<tr><td colspan="6" class="empty-cell">No tickets for this session yet.</td></tr>';
    refs.ticketInfoResult.textContent = "Select a ticket to view details.";
    refs.ticketCoachingResult.textContent =
      "Select a closed ticket and use Coach to review how you handled it.";
    refs.mentorResult.textContent =
      "Select a ticket and ask about troubleshooting, communication, SLA, escalation, documentation, or best practices.";
    return;
  }

  refs.ticketTableBody.innerHTML = tickets
    .map(
      (ticket) => `
      <tr class="ticket-row ${state.selectedTicketId === ticket.id ? "selected" : ""}" data-ticket-id="${ticket.id}">
        <td>${ticket.zammad_ticket_id ?? "-"}</td>
        <td>${ticket.tier}</td>
        <td>${ticket.priority}</td>
        <td>${ticket.status}</td>
        <td>
          <div>${ticket.subject}</div>
          <div title="${ticket.created_at}" class="row-sub mono">${toLocalTime(ticket.created_at)}</div>
        </td>
        <td>
          <div class="table-actions">
            <button class="btn use-hint" data-ticket-id="${ticket.id}">Hint</button>
            <button class="btn coach-ticket" data-ticket-id="${ticket.id}" data-busy-label="Reviewing...">Coach</button>
            <button class="btn kb-draft" data-ticket-id="${ticket.id}" data-busy-label="Drafting...">KB</button>
            <button class="btn close-ticket" data-ticket-id="${ticket.id}" data-busy-label="Closing...">Close</button>
            <button class="btn btn-danger delete-ticket" data-ticket-id="${ticket.id}" data-busy-label="Deleting...">Delete</button>
          </div>
        </td>
      </tr>
    `
    )
    .join("");

  refs.ticketTableBody.querySelectorAll(".ticket-row").forEach((row) => {
    row.addEventListener("click", async (event) => {
      if (event.target.closest("button")) return;
      const ticketId = row.dataset.ticketId;
      if (!ticketId) return;
      await loadTicketInfo(ticketId);
    });
  });

  refs.ticketTableBody.querySelectorAll(".use-hint").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const ticketId = button.dataset.ticketId;
      refs.hintTicketId.value = ticketId;
      refs.mentorTicketId.value = ticketId;
      refs.hintTicketId.focus();
      writeLog(refs.hintResult, "Hint target set. Pick level and request.");
      await loadTicketInfo(ticketId);
    });
  });

  refs.ticketTableBody.querySelectorAll(".kb-draft").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      await generateKnowledgeDraft(button.dataset.ticketId, button);
    });
  });

  refs.ticketTableBody.querySelectorAll(".coach-ticket").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const ticketId = button.dataset.ticketId;
      if (!ticketId) return;
      await loadTicketInfo(ticketId);
      await generateTicketCoaching(ticketId, button);
    });
  });

  refs.ticketTableBody.querySelectorAll(".close-ticket").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      await closeSingleTicket(button.dataset.ticketId, button);
    });
  });

  refs.ticketTableBody.querySelectorAll(".delete-ticket").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      await deleteSingleTicket(button.dataset.ticketId, button);
    });
  });
}

function populateManualSessionSelect() {
  const currentValue = refs.manualSessionSelect.value;
  const sessions = [...state.sessions].sort(
    (a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
  );

  refs.manualSessionSelect.innerHTML = sessions
    .map(
      (session) =>
        `<option value="${session.id}">${session.profile_name} | ${session.id.slice(0, 8)} | tickets:${session.ticket_count}</option>`
    )
    .join("");

  if (!sessions.length) {
    refs.manualSessionSelect.innerHTML = '<option value="">No active sessions (clock in first)</option>';
    return;
  }

  const hasCurrent = sessions.some((session) => session.id === currentValue);
  if (hasCurrent) {
    refs.manualSessionSelect.value = currentValue;
    return;
  }

  if (state.selectedSessionId && sessions.some((session) => session.id === state.selectedSessionId)) {
    refs.manualSessionSelect.value = state.selectedSessionId;
    return;
  }

  refs.manualSessionSelect.value = sessions[0].id;
}

function renderCatalogOptions() {
  refs.manualTypeSelect.innerHTML =
    '<option value="">Auto (weighted)</option>' +
    state.catalog.ticket_types.map((type) => `<option value="${type}">${type}</option>`).join("");

  refs.manualDeptSelect.innerHTML =
    '<option value="">Auto (match scenario)</option>' +
    state.catalog.departments.map((dept) => `<option value="${dept}">${dept}</option>`).join("");

  renderPersonaOptions();
  renderScenarioOptions();
}

function renderPersonaOptions() {
  const selectedDept = refs.manualDeptSelect.value;
  const personas = state.catalog.personas.filter((persona) =>
    selectedDept ? persona.role === selectedDept : true
  );

  const previous = refs.manualPersonaSelect.value;
  refs.manualPersonaSelect.innerHTML =
    '<option value="">Auto (match filters)</option>' +
    personas
      .map(
        (persona) =>
          `<option value="${persona.id}">${persona.full_name} (${persona.role}, technical: ${persona.technical_level})</option>`
      )
      .join("");

  if (previous && personas.some((persona) => persona.id === previous)) {
    refs.manualPersonaSelect.value = previous;
  }
}

function renderScenarioOptions() {
  const selectedTier = refs.manualTierSelect.value;
  const selectedType = refs.manualTypeSelect.value;
  const selectedDept = refs.manualDeptSelect.value;

  const scenarios = state.catalog.scenarios.filter((scenario) => {
    if (selectedTier && scenario.tier !== selectedTier) return false;
    if (selectedType && scenario.ticket_type !== selectedType) return false;
    if (selectedDept && scenario.persona_roles.length > 0 && !scenario.persona_roles.includes(selectedDept)) {
      return false;
    }
    return true;
  });

  const previous = refs.manualScenarioSelect.value;
  refs.manualScenarioSelect.innerHTML =
    '<option value="">Auto (match filters)</option>' +
    scenarios
      .map(
        (scenario) =>
          `<option value="${scenario.id}">${scenario.title} [${scenario.tier} | ${scenario.ticket_type}]</option>`
      )
      .join("");

  if (previous && scenarios.some((scenario) => scenario.id === previous)) {
    refs.manualScenarioSelect.value = previous;
  }
}

async function loadHealth() {
  try {
    const data = await api("/health", { method: "GET", headers: {} });
    refs.healthBadge.textContent = data.status === "ok" ? "API Online" : "API Unknown";
    refs.healthBadge.className = `badge ${data.status === "ok" ? "ok" : "fail"}`;
  } catch (error) {
    refs.healthBadge.textContent = `API Error: ${error.message}`;
    refs.healthBadge.className = "badge fail";
  }
}

async function loadProfiles() {
  const currentValue = refs.profileSelect.value;
  const data = await api("/v1/profiles", { method: "GET", headers: {} });
  refs.profileSelect.innerHTML = data.profiles
    .map((name) => `<option value="${name}">${name}</option>`)
    .join("");
  if (currentValue && data.profiles.includes(currentValue)) {
    refs.profileSelect.value = currentValue;
  }
  state.profileDefinitions = data.definitions || [];
  renderProfileDefinitions();
  renderSelectedProfileSummary();
}

async function loadCatalog() {
  const data = await api("/v1/catalog", { method: "GET", headers: {} });
  state.catalog = {
    ticket_types: data.ticket_types || [],
    departments: data.departments || [],
    scenarios: data.scenarios || [],
    personas: data.personas || [],
  };
  renderCatalogOptions();
}

async function loadSessions() {
  const data = await api("/v1/sessions", { method: "GET", headers: {} });
  state.sessions = data.sessions || [];
  renderSessions();
  populateManualSessionSelect();

  if (!state.selectedSessionId && state.sessions.length) {
    await loadSessionDetail(state.sessions[0].id);
  }
}

function renderLlmRuntimeStatus(data, leadSummary = "") {
  state.llmRuntimeStatus = data;

  let badgeText = "Rule-Based";
  let badgeKind = "";
  if (data.configured_engine === "ollama") {
    if (data.active_mode === "ollama") {
      badgeText = "Ollama Live";
      badgeKind = "ok";
    } else if (String(data.active_mode || "").includes("fallback")) {
      badgeText = "Ollama Fallback";
      badgeKind = "warn";
    } else if (data.active_mode === "error") {
      badgeText = "Ollama Error";
      badgeKind = "fail";
    } else {
      badgeText = "Ollama Ready";
      badgeKind = "warn";
    }
  }

  refs.llmStatusBadge.textContent = badgeText;
  refs.llmStatusBadge.className = `badge${badgeKind ? ` ${badgeKind}` : ""}`;

  const wakeReady = Boolean(data.wake_on_lan_ready);
  const wakeEnabled = Boolean(data.wake_on_lan_enabled);
  const hostReachable = Boolean(data.llm_host_reachable);
  if (refs.llmHostBadge) {
    if (data.llm_host_endpoint_host) {
      refs.llmHostBadge.textContent = hostReachable ? "PC Online" : "PC Offline";
      refs.llmHostBadge.className = `badge ${hostReachable ? "ok" : "fail"}`;
    } else {
      refs.llmHostBadge.textContent = "PC Unknown";
      refs.llmHostBadge.className = "badge warn";
    }
  }
  refs.wakeEngineBtn.disabled = !wakeReady;
  refs.wakeEngineBtn.style.opacity = wakeReady ? "1" : "0.65";
  refs.wakeEngineBtn.title = wakeReady
    ? `Send a Wake-on-LAN packet to ${data.llm_host_label || "the LLM host"}`
    : "Wake-on-LAN is not ready. Set SIM_LLM_HOST_WOL_ENABLED=true and configure SIM_LLM_HOST_MAC.";

  let wakeLine = "Wake control: off";
  if (wakeReady) {
    wakeLine = `Wake control: ready for ${data.llm_host_label || "LLM host"} (${data.llm_host_mac_masked || "MAC hidden"}) via ${data.llm_host_wol_broadcast_ip}:${data.llm_host_wol_port}`;
  } else if (wakeEnabled) {
    wakeLine = `Wake control: enabled for ${data.llm_host_label || "LLM host"}, but MAC setup is incomplete.`;
  }

  let hostLine = "LLM host: reachability unknown";
  if (data.llm_host_endpoint_host && data.llm_host_endpoint_port) {
    hostLine = `LLM host: ${hostReachable ? "online" : "offline"} at ${data.llm_host_endpoint_host}:${data.llm_host_endpoint_port}`;
  }

  const lines = [];
  if (leadSummary) {
    lines.push(leadSummary);
  }
  lines.push(data.english_summary || "LLM runtime status loaded.");
  lines.push(hostLine);
  lines.push(wakeLine);

  writeHumanAndJson(refs.llmStatusResult, lines.join("\n"), data);
}

async function loadLlmRuntimeStatus({ quiet = false } = {}) {
  if (!quiet) {
    setBusy(refs.llmStatusRefreshBtn, true);
  }
  try {
    const data = await api("/v1/runtime/response-engine", { method: "GET", headers: {} });
    renderLlmRuntimeStatus(data);
  } catch (error) {
    refs.llmStatusBadge.textContent = "LLM Error";
    refs.llmStatusBadge.className = "badge fail";
    if (refs.llmHostBadge) {
      refs.llmHostBadge.textContent = "PC Unknown";
      refs.llmHostBadge.className = "badge warn";
    }
    refs.wakeEngineBtn.disabled = true;
    refs.wakeEngineBtn.style.opacity = "0.65";
    writeLog(refs.llmStatusResult, `LLM runtime status failed: ${error.message}`);
  } finally {
    if (!quiet) {
      setBusy(refs.llmStatusRefreshBtn, false);
    }
  }
}

async function wakeEngineHost() {
  setBusy(refs.wakeEngineBtn, true);
  try {
    const wakeData = await api("/v1/runtime/wake-llm-host", {
      method: "POST",
      headers: {},
    });
    const statusData = await api("/v1/runtime/response-engine", { method: "GET", headers: {} });
    renderLlmRuntimeStatus(statusData, wakeData.english_summary || "Wake signal sent.");
  } catch (error) {
    writeLog(refs.llmStatusResult, `Wake engine failed: ${error.message}`);
  } finally {
    setBusy(refs.wakeEngineBtn, false);
  }
}

async function loadSessionDetail(sessionId) {
  state.selectedSessionId = sessionId;
  renderSessions();
  populateManualSessionSelect();
  clearDeleteBanner();

  const data = await api(`/v1/sessions/${sessionId}`, { method: "GET", headers: {} });
  refs.selectedSession.textContent = `${data.session.profile_name} | ${sessionId}`;
  state.currentSessionTickets = data.tickets || [];
  renderTickets(state.currentSessionTickets);

  if (
    state.selectedTicketId &&
    state.currentSessionTickets.some((ticket) => ticket.id === state.selectedTicketId)
  ) {
    await loadTicketInfo(state.selectedTicketId);
    return;
  }

  if (state.currentSessionTickets.length) {
    await loadTicketInfo(state.currentSessionTickets[0].id);
  }
}

async function loadTicketInfo(ticketId) {
  state.selectedTicketId = ticketId;
  renderTickets(state.currentSessionTickets);

  const [ticketData, knowledgeData] = await Promise.all([
    api(`/v1/tickets/${ticketId}`, { method: "GET", headers: {} }),
    api(`/v1/tickets/${ticketId}/knowledge-articles`, { method: "GET", headers: {} }),
  ]);

  const ticket = ticketData.ticket;
  const interactions = ticketData.interactions || [];
  const hidden = ticket.hidden_truth || {};
  const persona = hidden.persona || {};
  const userName = persona.full_name || "-";
  const userEmail = persona.email || "-";

  const payload = {
    ticket: {
      local_id: ticket.id,
      zammad_ticket_id: ticket.zammad_ticket_id,
      subject: ticket.subject,
      tier: ticket.tier,
      priority: ticket.priority,
      status: ticket.status,
      scenario_id: ticket.scenario_id,
      ticket_type: hidden.ticket_type || "-",
      department: persona.role || "-",
      user_name: userName,
      user_email: userEmail,
      user_technical_level: persona.technical_level || "-",
      hint_penalty_total: hidden.hint_penalty_total || 0,
      created_at: ticket.created_at,
      updated_at: ticket.updated_at,
    },
    recent_interactions: interactions.slice(-8),
    linked_knowledge_articles: knowledgeData.articles || [],
  };

  const lastInteraction = interactions[interactions.length - 1];
  const summaryLines = [
    `User: ${userName}${userEmail !== "-" ? ` <${userEmail}>` : ""}`,
    `Ticket: ${ticket.subject}`,
    `Status: ${ticket.status} | Tier: ${ticket.tier} | Priority: ${ticket.priority}`,
    `Local ID: ${ticket.id}`,
    `Zammad ID: ${ticket.zammad_ticket_id ?? "-"}`,
    `Type: ${hidden.ticket_type || "-"} | Department: ${persona.role || "-"} | User technical level: ${persona.technical_level || "-"}`,
    `Interactions: ${interactions.length} | Linked KB articles: ${(knowledgeData.articles || []).length}`,
  ];
  if (lastInteraction) {
    summaryLines.push(
      `Most recent interaction: ${lastInteraction.actor} at ${toLocalTime(lastInteraction.created_at)}`
    );
  }

  writeHumanAndJson(refs.ticketInfoResult, summaryLines.join("\n"), payload);
  refs.hintTicketId.value = ticket.id;
  refs.mentorTicketId.value = ticket.id;
  refs.mentorResult.textContent =
    "Ask a senior tech what to troubleshoot next, how to phrase a response, whether to escalate, how to handle SLA risk, or what to document.";
  refs.ticketCoachingResult.textContent =
    ticket.status === "closed"
      ? "This ticket is closed. Use Coach to generate a post-ticket review."
      : "Close this ticket first, then use Coach to review how you handled it.";
}

async function clockIn() {
  const profileName = refs.profileSelect.value;
  if (!profileName) return;

  setBusy(refs.clockInBtn, true);
  try {
    const data = await api("/v1/sessions/clock-in", {
      method: "POST",
      body: JSON.stringify({ profile_name: profileName }),
    });
    writeHumanAndJson(
      refs.actionResult,
      `Clocked in to ${data.profile_name}. Session ${data.id.slice(0, 8)} started.`,
      data
    );
    await loadSessions();
    await loadSessionDetail(data.id);
  } catch (error) {
    writeLog(refs.actionResult, `Clock-in failed: ${error.message}`);
  } finally {
    setBusy(refs.clockInBtn, false);
  }
}

async function clockOutSession(sessionId) {
  try {
    const data = await api(`/v1/sessions/${sessionId}/clock-out`, {
      method: "POST",
      headers: {},
    });
    writeHumanAndJson(
      refs.actionResult,
      `Session ${sessionId.slice(0, 8)} clocked out.`,
      data
    );
    if (state.selectedSessionId === sessionId) {
      state.selectedSessionId = null;
      state.selectedTicketId = null;
      state.currentSessionTickets = [];
      refs.selectedSession.textContent = "No session selected";
      renderTickets([]);
    }
    await loadSessions();
  } catch (error) {
    writeLog(refs.actionResult, `Clock-out failed: ${error.message}`);
  }
}

async function clockOutAllSessions() {
  const proceed = window.confirm("Clock out all active sessions?");
  if (!proceed) return;

  setBusy(refs.clockOutAllBtn, true);
  setBusy(refs.clockOutAllBtnSessions, true);
  try {
    const data = await api("/v1/sessions/clock-out-all", {
      method: "POST",
      headers: {},
    });

    const summary =
      data.english_summary ||
      (data.clocked_out > 0
        ? `Clocked out ${data.clocked_out} session(s).`
        : "No active sessions were running.");
    writeHumanAndJson(refs.actionResult, summary, data);

    state.selectedSessionId = null;
    state.selectedTicketId = null;
    state.currentSessionTickets = [];
    refs.selectedSession.textContent = "No session selected";
    renderTickets([]);
    await loadSessions();
  } catch (error) {
    writeLog(refs.actionResult, `Clock-out-all failed: ${error.message}`);
  } finally {
    setBusy(refs.clockOutAllBtn, false);
    setBusy(refs.clockOutAllBtnSessions, false);
  }
}

async function closeSingleTicket(ticketId, triggerButton = null) {
  if (!ticketId) return;
  setBusy(triggerButton, true);
  try {
    const data = await api(`/v1/tickets/${ticketId}/close`, {
      method: "POST",
      headers: {},
    });
    writeHumanAndJson(refs.actionResult, data.english_summary || `Closed ticket ${ticketId}.`, data);
    if (state.selectedSessionId) {
      await loadSessionDetail(state.selectedSessionId);
    }
  } catch (error) {
    writeLog(refs.actionResult, `Close ticket failed: ${error.message}`);
  } finally {
    setBusy(triggerButton, false);
  }
}

async function generateKnowledgeDraft(ticketId, triggerButton = null) {
  if (!ticketId) return;
  setBusy(triggerButton, true);
  try {
    const data = await api(`/v1/tickets/${ticketId}/knowledge-draft`, {
      method: "POST",
      headers: {},
    });
    if (!data.ready) {
      writeHumanAndJson(refs.actionResult, data.english_summary || "KB draft is not ready yet.", data);
      return;
    }

    writeHumanAndJson(refs.actionResult, data.english_summary || "KB draft generated.", data);
    writeHumanAndJson(refs.ticketInfoResult, "KB Draft (copy/edit before publishing):", {
      ticket_id: data.ticket_id,
      markdown: data.markdown,
    });
  } catch (error) {
    writeLog(refs.actionResult, `KB draft failed: ${error.message}`);
  } finally {
    setBusy(triggerButton, false);
  }
}

async function generateTicketCoaching(ticketId, triggerButton = null) {
  if (!ticketId) return;
  setBusy(triggerButton, true);
  try {
    const data = await api(`/v1/tickets/${ticketId}/coach`, {
      method: "POST",
      headers: {},
    });
    if (!data.ready) {
      writeHumanAndJson(refs.ticketCoachingResult, data.english_summary || "Coaching is not ready yet.", data);
      return;
    }

    const summaryLines = [
      data.english_summary || "Coaching generated.",
      "",
      `Coaching Note: ${data.coaching_note || "-"}`,
      "",
      `Professionalism: ${data.professionalism_critique || "-"}`,
      `Documentation: ${data.documentation_critique || "-"}`,
      "",
      `Strengths: ${(data.strengths || []).length ? data.strengths.join(" | ") : "-"}`,
      `Focus Areas: ${(data.focus_areas || []).length ? data.focus_areas.join(" | ") : "-"}`,
    ];

    writeHumanAndJson(refs.ticketCoachingResult, summaryLines.join("\n"), data);
  } catch (error) {
    writeLog(refs.ticketCoachingResult, `Coaching failed: ${error.message}`);
  } finally {
    setBusy(triggerButton, false);
  }
}

async function askMentor() {
  const ticketId = refs.mentorTicketId.value.trim();
  const message = refs.mentorPrompt.value.trim();
  if (!ticketId) {
    writeLog(refs.mentorResult, "Provide a local ticket ID first.");
    return;
  }
  if (!message) {
    writeLog(refs.mentorResult, "Type the internal question you want to ask the mentor.");
    return;
  }

  setBusy(refs.mentorBtn, true);
  try {
    const data = await api(`/v1/tickets/${ticketId}/mentor`, {
      method: "POST",
      headers: {},
      body: JSON.stringify({ message }),
    });
    const summaryLines = [
      data.english_summary || "Mentor guidance generated.",
      "",
      `Mentor Reply: ${data.mentor_reply || "-"}`,
    ];
    writeHumanAndJson(refs.mentorResult, summaryLines.join("\n"), data);
  } catch (error) {
    writeLog(refs.mentorResult, `Mentor request failed: ${error.message}`);
  } finally {
    setBusy(refs.mentorBtn, false);
  }
}

async function deleteSingleTicket(ticketId, triggerButton = null) {
  if (!ticketId) return;
  const proceed = window.confirm(
    "Delete this ticket from simulator data? This is for cleanup and cannot be undone."
  );
  if (!proceed) return;

  clearDeleteBanner();
  setBusy(triggerButton, true);
  try {
    const fallbackClose = Boolean(refs.deleteFallbackClose?.checked);
    const path = fallbackClose
      ? `/v1/tickets/${ticketId}?fallback_close_on_delete_failure=true`
      : `/v1/tickets/${ticketId}`;
    const data = await api(path, {
      method: "DELETE",
      headers: {},
    });
    writeHumanAndJson(refs.actionResult, data.english_summary || `Deleted ticket ${ticketId}.`, data);
    showDeleteBanner(data.english_summary || "Ticket deleted.", "success");
    if (state.selectedTicketId === ticketId) {
      state.selectedTicketId = null;
      refs.ticketInfoResult.textContent = "Select a ticket to view details.";
      refs.ticketCoachingResult.textContent =
        "Select a closed ticket and use Coach to review how you handled it.";
      refs.mentorResult.textContent =
        "Select a ticket and ask about troubleshooting, communication, SLA, escalation, documentation, or best practices.";
    }
    if (state.selectedSessionId) {
      await loadSessionDetail(state.selectedSessionId);
    }
  } catch (error) {
    writeLog(refs.actionResult, `Delete ticket failed: ${error.message}`);
    showDeleteBanner(`Delete failed: ${error.message}`, "error");
  } finally {
    setBusy(triggerButton, false);
  }
}

async function closeAllTicketsInSelectedSession() {
  const sessionId = state.selectedSessionId || refs.manualSessionSelect.value;
  if (!sessionId) {
    writeLog(refs.actionResult, "Select an active session first, then use Close Open Tickets.");
    return;
  }

  const proceed = window.confirm("Close all open tickets in the selected session?");
  if (!proceed) return;

  setBusy(refs.closeAllSessionTicketsBtn, true);
  try {
    const data = await api(`/v1/sessions/${sessionId}/tickets/close-all`, {
      method: "POST",
      headers: {},
    });
    writeHumanAndJson(refs.actionResult, data.english_summary || "Closed open tickets.", data);
    await loadSessionDetail(sessionId);
  } catch (error) {
    writeLog(refs.actionResult, `Close all tickets failed: ${error.message}`);
  } finally {
    setBusy(refs.closeAllSessionTicketsBtn, false);
  }
}

async function deleteAllTicketsInSelectedSession() {
  const sessionId = state.selectedSessionId || refs.manualSessionSelect.value;
  if (!sessionId) {
    writeLog(refs.actionResult, "Select an active session first, then use Delete All Tickets.");
    return;
  }

  const proceed = window.confirm(
    "Delete ALL tickets in this session from simulator data? This cannot be undone."
  );
  if (!proceed) return;

  setBusy(refs.deleteAllSessionTicketsBtn, true);
  clearDeleteBanner();
  try {
    const fallbackClose = Boolean(refs.deleteFallbackClose?.checked);
    const path = fallbackClose
      ? `/v1/sessions/${sessionId}/tickets?fallback_close_on_delete_failure=true`
      : `/v1/sessions/${sessionId}/tickets`;
    const data = await api(path, {
      method: "DELETE",
      headers: {},
    });
    writeHumanAndJson(refs.actionResult, data.english_summary || "Deleted tickets.", data);
    showDeleteBanner(data.english_summary || "Deleted tickets.", "success");
    state.selectedTicketId = null;
    state.currentSessionTickets = [];
    refs.ticketInfoResult.textContent = "Select a ticket to view details.";
    refs.ticketCoachingResult.textContent =
      "Select a closed ticket and use Coach to review how you handled it.";
    refs.mentorResult.textContent =
      "Select a ticket and ask about troubleshooting, communication, SLA, escalation, documentation, or best practices.";
    await loadSessionDetail(sessionId);
  } catch (error) {
    writeLog(refs.actionResult, `Delete all tickets failed: ${error.message}`);
    showDeleteBanner(`Bulk delete failed: ${error.message}`, "error");
  } finally {
    setBusy(refs.deleteAllSessionTicketsBtn, false);
  }
}

async function runScheduler() {
  setBusy(refs.schedulerBtn, true);
  try {
    const data = await api("/v1/scheduler/run-once", {
      method: "POST",
      headers: {},
    });
    const summary = `Scheduler checked ${data.sessions_checked} session(s), generated ${data.tickets_generated} ticket(s).`;
    writeHumanAndJson(refs.actionResult, summary, data);
    await loadSessions();
    if (state.selectedSessionId) {
      await loadSessionDetail(state.selectedSessionId);
    }
  } catch (error) {
    writeLog(refs.actionResult, `Scheduler failed: ${error.message}`);
  } finally {
    setBusy(refs.schedulerBtn, false);
  }
}

async function runPoller() {
  setBusy(refs.pollerBtn, true);
  try {
    const data = await api("/v1/poller/run-once", {
      method: "POST",
      headers: {},
    });
    const summary = `Poller checked ${data.tickets_checked ?? 0} ticket(s), posted ${data.replies_sent ?? 0} response(s), closed ${data.tickets_closed ?? 0}.`;
    writeHumanAndJson(refs.actionResult, summary, data);
    await loadLlmRuntimeStatus({ quiet: true });
    if (state.selectedSessionId) {
      await loadSessionDetail(state.selectedSessionId);
    }
  } catch (error) {
    writeLog(refs.actionResult, `Poller failed: ${error.message}`);
  } finally {
    setBusy(refs.pollerBtn, false);
  }
}

async function generateManualTickets() {
  const sessionId = refs.manualSessionSelect.value;
  const count = Number.parseInt(refs.manualCount.value, 10) || 1;

  if (!sessionId) {
    writeLog(
      refs.manualResult,
      "No active session selected. Clock in first, then generate manual tickets into that active shift."
    );
    return;
  }

  const payload = {
    session_id: sessionId || null,
    count,
    tier: refs.manualTierSelect.value || null,
    ticket_type: refs.manualTypeSelect.value || null,
    department: refs.manualDeptSelect.value || null,
    persona_id: refs.manualPersonaSelect.value || null,
    scenario_id: refs.manualScenarioSelect.value || null,
  };

  setBusy(refs.manualGenerateBtn, true);
  try {
    const data = await api("/v1/tickets/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const summary = `Created ${data.created_count} manual ticket(s) in shift ${String(data.session_id).slice(0, 8)}.`;
    writeHumanAndJson(refs.manualResult, summary, data);
    await loadSessions();
    if (data.session_id) {
      await loadSessionDetail(data.session_id);
    }
  } catch (error) {
    writeLog(refs.manualResult, `Manual generate failed: ${error.message}`);
  } finally {
    setBusy(refs.manualGenerateBtn, false);
  }
}

function getCurrentManualSession() {
  const sessionId = refs.manualSessionSelect.value;
  if (!sessionId) return null;
  return state.sessions.find((session) => session.id === sessionId) ?? null;
}

function autoFillManualFilters() {
  const session = getCurrentManualSession();
  if (!session) {
    writeLog(
      refs.manualResult,
      "No active session selected. Clock in first, then use Auto Fill Random."
    );
    return;
  }

  const tierCandidates = ["tier1", "tier2", "sysadmin"];
  const pickedTier = pickWeighted(
    tierCandidates,
    session.config?.tier_weights || {},
    (value) => value
  );
  refs.manualTierSelect.value = pickedTier || "";

  const scenariosForTier = state.catalog.scenarios.filter(
    (scenario) => !pickedTier || scenario.tier === pickedTier
  );
  const ticketTypesForTier = Array.from(
    new Set(scenariosForTier.map((scenario) => scenario.ticket_type))
  );

  const pickedTicketType = pickWeighted(
    ticketTypesForTier,
    session.config?.scenario_type_weights || {},
    (value) => value
  );
  refs.manualTypeSelect.value = pickedTicketType || "";

  const scopedScenarios = state.catalog.scenarios.filter((scenario) => {
    if (pickedTier && scenario.tier !== pickedTier) return false;
    if (pickedTicketType && scenario.ticket_type !== pickedTicketType) return false;
    return true;
  });

  const departmentCandidates = Array.from(
    new Set(
      scopedScenarios.flatMap((scenario) =>
        Array.isArray(scenario.persona_roles) ? scenario.persona_roles : []
      )
    )
  );
  const pickedDepartment = pickRandom(
    departmentCandidates.length ? departmentCandidates : state.catalog.departments
  );
  refs.manualDeptSelect.value = pickedDepartment || "";

  renderPersonaOptions();
  renderScenarioOptions();

  const scenarioOptions = Array.from(refs.manualScenarioSelect.options)
    .map((option) => option.value)
    .filter((value) => Boolean(value));
  const pickedScenarioId = pickRandom(scenarioOptions);
  refs.manualScenarioSelect.value = pickedScenarioId || "";

  const personaOptions = Array.from(refs.manualPersonaSelect.options)
    .map((option) => option.value)
    .filter((value) => Boolean(value));
  const pickedPersonaId = pickRandom(personaOptions);
  refs.manualPersonaSelect.value = pickedPersonaId || "";

  const humanSummary = [
    "Auto-fill complete.",
    `Shift: ${session.profile_name} (${session.id.slice(0, 8)})`,
    `Tier: ${pickedTier || "auto"}`,
    `Ticket type: ${pickedTicketType || "auto"}`,
    `Department: ${pickedDepartment || "auto"}`,
    `Persona: ${pickedPersonaId || "auto"}`,
    `Scenario: ${pickedScenarioId || "auto"}`,
  ].join("\n");
  writeHumanAndJson(refs.manualResult, humanSummary, {
    shift_id: session.id,
    shift_profile: session.profile_name,
    tier: pickedTier || null,
    ticket_type: pickedTicketType || null,
    department: pickedDepartment || null,
    persona_id: pickedPersonaId || null,
    scenario_id: pickedScenarioId || null,
  });
}

async function requestHint() {
  const ticketId = refs.hintTicketId.value.trim();
  const level = refs.hintLevel.value;
  if (!ticketId) {
    writeLog(refs.hintResult, "Provide a local ticket ID first.");
    return;
  }

  setBusy(refs.hintBtn, true);
  try {
    const data = await api("/v1/hints", {
      method: "POST",
      body: JSON.stringify({ ticket_id: ticketId, level }),
    });
    const summary = data.english_summary || `Hint: ${data.hint} (Penalty +${data.penalty_applied})`;
    writeHumanAndJson(refs.hintResult, summary, data);
    await loadTicketInfo(ticketId);
  } catch (error) {
    writeLog(refs.hintResult, `Hint request failed: ${error.message}`);
  } finally {
    setBusy(refs.hintBtn, false);
  }
}

async function loadReport(kind) {
  const button = kind === "weekly" ? refs.weeklyReportBtn : refs.dailyReportBtn;
  setBusy(button, true);
  const path = kind === "weekly" ? "/v1/reports/weekly" : "/v1/reports/daily";
  try {
    const data = await api(path, { method: "GET", headers: {} });
    const summary =
      data.english_summary ||
      `${kind === "weekly" ? "Weekly" : "Daily"} report: ${data.tickets_closed ?? 0} closed, avg score ${data.average_score ?? 0}.`;
    writeHumanAndJson(refs.reportResult, summary, data);
  } catch (error) {
    writeLog(refs.reportResult, `Report request failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

function readStoredThemeMode() {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "auto") {
      return stored;
    }
  } catch {
    return "auto";
  }
  return "auto";
}

function readRawDisplayMode() {
  try {
    const stored = window.localStorage.getItem(RAW_DISPLAY_STORAGE_KEY);
    if (stored === "on" || stored === "off") {
      return stored;
    }
  } catch {
    return "off";
  }
  return "off";
}

function applyTheme(mode, persist = false) {
  const normalized = mode === "light" || mode === "dark" ? mode : "auto";
  const resolved = normalized === "auto" ? (systemColorScheme.matches ? "dark" : "light") : normalized;
  document.documentElement.setAttribute("data-theme", resolved);
  refs.themeModeButtons.forEach((button) => {
    const isActive = button.dataset.themeMode === normalized;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });

  if (persist) {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, normalized);
    } catch {
      // Ignore localStorage write errors in locked-down browsers.
    }
  }
}

function applyRawDisplayMode(mode, persist = false) {
  const normalized = mode === "on" ? "on" : "off";
  refs.showRawJson.value = normalized;
  if (persist) {
    try {
      window.localStorage.setItem(RAW_DISPLAY_STORAGE_KEY, normalized);
    } catch {
      // Ignore localStorage write errors in locked-down browsers.
    }
  }
}

function closeThemePanel() {
  if (!refs.themePanel || !refs.themeLauncher) return;
  refs.themePanel.hidden = true;
  refs.themeLauncher.setAttribute("aria-expanded", "false");
}

function toggleThemePanel() {
  if (!refs.themePanel || !refs.themeLauncher) return;
  const shouldOpen = refs.themePanel.hidden;
  refs.themePanel.hidden = !shouldOpen;
  refs.themeLauncher.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

async function refreshAll() {
  setBusy(refs.refreshBtn, true);
  try {
    await Promise.all([loadHealth(), loadProfiles(), loadCatalog(), loadSessions(), loadLlmRuntimeStatus()]);
    if (state.selectedSessionId) {
      await loadSessionDetail(state.selectedSessionId);
    }
  } finally {
    setBusy(refs.refreshBtn, false);
  }
}

refs.clockInBtn.addEventListener("click", clockIn);
refs.clockOutAllBtn.addEventListener("click", clockOutAllSessions);
refs.clockOutAllBtnSessions.addEventListener("click", clockOutAllSessions);
refs.closeAllSessionTicketsBtn.addEventListener("click", closeAllTicketsInSelectedSession);
refs.deleteAllSessionTicketsBtn.addEventListener("click", deleteAllTicketsInSelectedSession);
refs.schedulerBtn.addEventListener("click", runScheduler);
refs.pollerBtn.addEventListener("click", runPoller);
refs.refreshBtn.addEventListener("click", refreshAll);
refs.manualAutofillBtn.addEventListener("click", autoFillManualFilters);
refs.manualGenerateBtn.addEventListener("click", generateManualTickets);
refs.hintBtn.addEventListener("click", requestHint);
refs.dailyReportBtn.addEventListener("click", () => loadReport("daily"));
refs.weeklyReportBtn.addEventListener("click", () => loadReport("weekly"));
refs.llmStatusRefreshBtn.addEventListener("click", () => loadLlmRuntimeStatus());
refs.wakeEngineBtn.addEventListener("click", wakeEngineHost);
refs.mentorBtn.addEventListener("click", askMentor);
refs.showRawJson.addEventListener("change", () => applyRawDisplayMode(refs.showRawJson.value, true));
refs.profileSelect.addEventListener("change", renderSelectedProfileSummary);
refs.manualTierSelect.addEventListener("change", renderScenarioOptions);
refs.manualTypeSelect.addEventListener("change", renderScenarioOptions);
refs.manualDeptSelect.addEventListener("change", () => {
  renderPersonaOptions();
  renderScenarioOptions();
});
refs.themeModeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    applyTheme(button.dataset.themeMode || "auto", true);
    closeThemePanel();
  });
});
if (refs.themeLauncher) {
  refs.themeLauncher.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleThemePanel();
  });
}
if (refs.themePanel) {
  refs.themePanel.addEventListener("click", (event) => {
    event.stopPropagation();
  });
}
document.addEventListener("click", () => {
  closeThemePanel();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeThemePanel();
  }
});

systemColorScheme.addEventListener("change", () => {
  if (readStoredThemeMode() === "auto") {
    applyTheme("auto", false);
  }
});

applyTheme("auto", true);
applyRawDisplayMode(readRawDisplayMode(), false);

refreshAll().catch((error) => {
  writeLog(refs.actionResult, `Initialization failed: ${error.message}`);
});

setInterval(() => {
  Promise.all([loadSessions(), loadLlmRuntimeStatus({ quiet: true })]).catch((error) => {
    writeLog(refs.actionResult, `Auto-refresh failed: ${error.message}`);
  });
}, 15000);
