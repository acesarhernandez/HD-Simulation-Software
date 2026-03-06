const GOD_KEY_STORAGE_KEY = "helpdesk_sim_god_key";

const state = {
  pendingRequests: 0,
  sessions: [],
  tickets: [],
  selectedSessionId: "",
  selectedTicketId: "",
  walkthrough: null,
  config: null,
  key: "",
};

const refs = {
  godVersionBadge: document.getElementById("godVersionBadge"),
  godStatusBadge: document.getElementById("godStatusBadge"),
  godAccessKey: document.getElementById("godAccessKey"),
  saveGodKeyBtn: document.getElementById("saveGodKeyBtn"),
  refreshGodBtn: document.getElementById("refreshGodBtn"),
  godSessionSelect: document.getElementById("godSessionSelect"),
  godTicketSelect: document.getElementById("godTicketSelect"),
  godAttemptFirst: document.getElementById("godAttemptFirst"),
  godStartBtn: document.getElementById("godStartBtn"),
  godContextResult: document.getElementById("godContextResult"),
  godPhaseList: document.getElementById("godPhaseList"),
  godCurrentPhase: document.getElementById("godCurrentPhase"),
  godGuidanceResult: document.getElementById("godGuidanceResult"),
  godAttemptText: document.getElementById("godAttemptText"),
  godSubmitAttemptBtn: document.getElementById("godSubmitAttemptBtn"),
  godAdvanceBtn: document.getElementById("godAdvanceBtn"),
  godRevealBtn: document.getElementById("godRevealBtn"),
  godAttemptResult: document.getElementById("godAttemptResult"),
  godDraftInstruction: document.getElementById("godDraftInstruction"),
  godDraftPublicBtn: document.getElementById("godDraftPublicBtn"),
  godDraftInternalBtn: document.getElementById("godDraftInternalBtn"),
  godDraftEscalationBtn: document.getElementById("godDraftEscalationBtn"),
  godDraftResult: document.getElementById("godDraftResult"),
  godReplayBtn: document.getElementById("godReplayBtn"),
  godReplayResult: document.getElementById("godReplayResult"),
  godDailyBtn: document.getElementById("godDailyBtn"),
  godWeeklyBtn: document.getElementById("godWeeklyBtn"),
  godReportResult: document.getElementById("godReportResult"),
};

function setBusy(button, busy) {
  if (!button) return;
  if (!button.dataset.idleLabel) {
    button.dataset.idleLabel = button.textContent.trim();
  }
  button.disabled = busy;
  button.style.opacity = busy ? "0.72" : "1";
  button.textContent = busy ? button.dataset.busyLabel || "Working..." : button.dataset.idleLabel;
}

function updateStatusBadge() {
  if (!refs.godStatusBadge) return;
  if (state.pendingRequests > 0) {
    refs.godStatusBadge.className = "badge warn";
    refs.godStatusBadge.textContent =
      state.pendingRequests === 1 ? "Working..." : `Working (${state.pendingRequests})`;
    return;
  }
  refs.godStatusBadge.className = "badge ok";
  refs.godStatusBadge.textContent = "Ready";
}

function writeLog(element, payload) {
  if (!element) return;
  if (typeof payload === "string") {
    element.textContent = payload;
    return;
  }
  element.textContent = JSON.stringify(payload, null, 2);
}

function currentGodKey() {
  return String(state.key || "").trim();
}

function readSavedKey() {
  try {
    return window.localStorage.getItem(GOD_KEY_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function saveKey(value) {
  try {
    if (value) {
      window.localStorage.setItem(GOD_KEY_STORAGE_KEY, value);
    } else {
      window.localStorage.removeItem(GOD_KEY_STORAGE_KEY);
    }
  } catch {
    // Ignore storage failures.
  }
}

function bootstrapKeyFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const queryKey = String(params.get("k") || "").trim();
  if (!queryKey) return;
  state.key = queryKey;
  saveKey(queryKey);
  if (refs.godAccessKey) {
    refs.godAccessKey.value = queryKey;
  }
}

async function api(path, options = {}) {
  state.pendingRequests += 1;
  updateStatusBadge();

  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  const key = currentGodKey();
  if (key) {
    headers["X-God-Key"] = key;
  }

  try {
    const response = await fetch(path, {
      ...options,
      headers,
    });
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
    updateStatusBadge();
  }
}

function renderSessions() {
  if (!refs.godSessionSelect) return;
  const previous = refs.godSessionSelect.value;
  refs.godSessionSelect.innerHTML = "";
  if (!state.sessions.length) {
    refs.godSessionSelect.innerHTML = '<option value="">No active sessions</option>';
    return;
  }

  state.sessions.forEach((session) => {
    const option = document.createElement("option");
    option.value = session.id;
    option.textContent = `${session.profile_name} | ${session.id.slice(0, 8)} | tickets:${session.ticket_count}`;
    refs.godSessionSelect.append(option);
  });

  const preferred =
    state.sessions.find((session) => session.id === previous)?.id ||
    state.sessions.find((session) => session.id === state.selectedSessionId)?.id ||
    state.sessions[0].id;

  refs.godSessionSelect.value = preferred;
  state.selectedSessionId = preferred;
}

function renderTickets() {
  if (!refs.godTicketSelect) return;
  const previous = refs.godTicketSelect.value;
  refs.godTicketSelect.innerHTML = "";
  if (!state.tickets.length) {
    refs.godTicketSelect.innerHTML = '<option value="">No tickets in this session</option>';
    state.selectedTicketId = "";
    return;
  }

  state.tickets.forEach((ticket) => {
    const option = document.createElement("option");
    option.value = ticket.id;
    const zammad = ticket.zammad_ticket_id ? `#${ticket.zammad_ticket_id}` : "local";
    option.textContent = `${zammad} | ${ticket.subject} (${ticket.status})`;
    refs.godTicketSelect.append(option);
  });

  const preferred =
    state.tickets.find((ticket) => ticket.id === previous)?.id ||
    state.tickets.find((ticket) => ticket.id === state.selectedTicketId)?.id ||
    state.tickets[0].id;

  refs.godTicketSelect.value = preferred;
  state.selectedTicketId = preferred;
}

function renderWalkthrough() {
  const walkthrough = state.walkthrough;
  if (!walkthrough) {
    refs.godPhaseList.className = "definition-list empty";
    refs.godPhaseList.textContent = "No walkthrough loaded.";
    refs.godCurrentPhase.textContent = "-";
    writeLog(refs.godGuidanceResult, "Guidance will appear here.");
    return;
  }

  const phases = Array.isArray(walkthrough.phases) ? walkthrough.phases : [];
  if (!phases.length) {
    refs.godPhaseList.className = "definition-list empty";
    refs.godPhaseList.textContent = "No phase data returned.";
  } else {
    refs.godPhaseList.className = "definition-list";
    refs.godPhaseList.innerHTML = phases
      .map((phase) => {
        const gate = phase.gate || {};
        const gateRequired = gate.required ? "required" : "optional";
        const gateState = gate.passed ? "passed" : "not passed";
        return `
          <div class="definition-item">
            <div class="god-phase-top">
              <span class="god-phase-title">${phase.title}</span>
              <span class="badge ${phase.status === "completed" ? "ok" : "badge-muted"}">${phase.status}</span>
            </div>
            <div class="god-phase-focus">${phase.focus || "-"}</div>
            <div class="god-gate">Gate: ${gateRequired} | ${gateState} | ${gate.reason || "-"}</div>
            <div class="god-gate">Attempts: ${phase.attempt_count || 0}</div>
          </div>
        `;
      })
      .join("");
  }

  const currentPhase = walkthrough.current_phase || "-";
  refs.godCurrentPhase.textContent = currentPhase;
  writeLog(refs.godGuidanceResult, walkthrough.phase_guidance || walkthrough.english_summary || "No guidance yet.");
}

function selectedTicketId() {
  return String(refs.godTicketSelect?.value || state.selectedTicketId || "").trim();
}

function selectedPhaseKey() {
  return String(state.walkthrough?.current_phase || "").trim();
}

async function loadHealth() {
  const data = await api("/health", { method: "GET", headers: {} });
  if (refs.godVersionBadge && data?.version) {
    const versionText = String(data.version).startsWith("v") ? String(data.version) : `v${data.version}`;
    refs.godVersionBadge.textContent = versionText;
    refs.godVersionBadge.title = `Simulator version ${versionText}`;
  }
}

async function loadConfig() {
  const config = await api("/v1/god/config", { method: "GET" });
  state.config = config;
  const defaultAttemptFirst = Boolean(config.default_attempt_first);
  if (refs.godAttemptFirst) {
    refs.godAttemptFirst.checked = defaultAttemptFirst;
  }
  writeLog(refs.godContextResult, config.english_summary || "God mode configuration loaded.");
}

async function loadSessions() {
  const data = await api("/v1/sessions", { method: "GET", headers: {} });
  state.sessions = Array.isArray(data.sessions) ? data.sessions : [];
  renderSessions();
}

async function loadSessionTickets(sessionId) {
  if (!sessionId) {
    state.tickets = [];
    renderTickets();
    return;
  }
  const detail = await api(`/v1/sessions/${sessionId}`, { method: "GET", headers: {} });
  state.tickets = Array.isArray(detail.tickets) ? detail.tickets : [];
  renderTickets();
}

async function loadWalkthrough(ticketId) {
  if (!ticketId) {
    state.walkthrough = null;
    renderWalkthrough();
    return;
  }
  const data = await api(`/v1/god/tickets/${ticketId}/walkthrough`, { method: "GET" });
  state.walkthrough = data;
  renderWalkthrough();
}

async function refreshAll() {
  setBusy(refs.refreshGodBtn, true);
  try {
    await loadHealth();
    await loadConfig();
    await loadSessions();
    await loadSessionTickets(state.selectedSessionId);
    if (selectedTicketId()) {
      await loadWalkthrough(selectedTicketId());
    } else {
      state.walkthrough = null;
      renderWalkthrough();
    }
  } catch (error) {
    writeLog(refs.godContextResult, `Refresh failed: ${error.message}`);
  } finally {
    setBusy(refs.refreshGodBtn, false);
  }
}

async function startWalkthrough() {
  const ticketId = selectedTicketId();
  if (!ticketId) {
    writeLog(refs.godContextResult, "Select a ticket first.");
    return;
  }
  setBusy(refs.godStartBtn, true);
  try {
    const payload = {
      attempt_first: Boolean(refs.godAttemptFirst?.checked),
    };
    const data = await api(`/v1/god/tickets/${ticketId}/start`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.walkthrough = data;
    renderWalkthrough();
    writeLog(refs.godContextResult, data.english_summary || "Walkthrough started.");
  } catch (error) {
    writeLog(refs.godContextResult, `Start failed: ${error.message}`);
  } finally {
    setBusy(refs.godStartBtn, false);
  }
}

async function submitAttempt() {
  const ticketId = selectedTicketId();
  const phaseKey = selectedPhaseKey();
  const text = String(refs.godAttemptText?.value || "").trim();
  if (!ticketId) {
    writeLog(refs.godAttemptResult, "Select a ticket first.");
    return;
  }
  if (!phaseKey) {
    writeLog(refs.godAttemptResult, "No active phase. Start walkthrough first.");
    return;
  }
  if (!text) {
    writeLog(refs.godAttemptResult, "Enter your attempt text before submitting.");
    return;
  }
  setBusy(refs.godSubmitAttemptBtn, true);
  try {
    const data = await api(`/v1/god/tickets/${ticketId}/phase/${phaseKey}/attempt`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    writeLog(refs.godAttemptResult, data);
    await loadWalkthrough(ticketId);
  } catch (error) {
    writeLog(refs.godAttemptResult, `Attempt failed: ${error.message}`);
  } finally {
    setBusy(refs.godSubmitAttemptBtn, false);
  }
}

async function advancePhase() {
  const ticketId = selectedTicketId();
  const phaseKey = selectedPhaseKey();
  if (!ticketId || !phaseKey) {
    writeLog(refs.godAttemptResult, "Select a ticket and load an active phase first.");
    return;
  }
  setBusy(refs.godAdvanceBtn, true);
  try {
    const note = String(refs.godAttemptText?.value || "").trim();
    const data = await api(`/v1/god/tickets/${ticketId}/phase/${phaseKey}/advance`, {
      method: "POST",
      body: JSON.stringify({ note, force: false }),
    });
    writeLog(refs.godAttemptResult, data);
    await loadWalkthrough(ticketId);
  } catch (error) {
    writeLog(refs.godAttemptResult, `Advance failed: ${error.message}`);
  } finally {
    setBusy(refs.godAdvanceBtn, false);
  }
}

async function revealTruth() {
  const ticketId = selectedTicketId();
  if (!ticketId) {
    writeLog(refs.godAttemptResult, "Select a ticket first.");
    return;
  }
  setBusy(refs.godRevealBtn, true);
  try {
    const data = await api(`/v1/god/tickets/${ticketId}/reveal-truth`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    writeLog(refs.godAttemptResult, data);
    await loadWalkthrough(ticketId);
  } catch (error) {
    writeLog(refs.godAttemptResult, `Reveal failed: ${error.message}`);
  } finally {
    setBusy(refs.godRevealBtn, false);
  }
}

async function requestDraft(kind, button) {
  const ticketId = selectedTicketId();
  if (!ticketId) {
    writeLog(refs.godDraftResult, "Select a ticket first.");
    return;
  }
  setBusy(button, true);
  try {
    const instruction = String(refs.godDraftInstruction?.value || "").trim();
    const pathMap = {
      public_reply: "public-reply",
      internal_note: "internal-note",
      escalation_handoff: "escalation-handoff",
    };
    const path = pathMap[kind];
    if (!path) {
      throw new Error(`Unsupported draft type: ${kind}`);
    }
    const data = await api(`/v1/god/tickets/${ticketId}/draft/${path}`, {
      method: "POST",
      body: JSON.stringify({ instruction }),
    });
    writeLog(refs.godDraftResult, data);
  } catch (error) {
    writeLog(refs.godDraftResult, `Draft failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

async function loadReplay() {
  const ticketId = selectedTicketId();
  if (!ticketId) {
    writeLog(refs.godReplayResult, "Select a ticket first.");
    return;
  }
  setBusy(refs.godReplayBtn, true);
  try {
    const data = await api(`/v1/god/tickets/${ticketId}/replay`, { method: "GET" });
    writeLog(refs.godReplayResult, data);
  } catch (error) {
    writeLog(refs.godReplayResult, `Replay failed: ${error.message}`);
  } finally {
    setBusy(refs.godReplayBtn, false);
  }
}

async function loadGodReport(kind, button) {
  setBusy(button, true);
  try {
    const path = kind === "weekly" ? "/v1/god/reports/weekly" : "/v1/god/reports/daily";
    const data = await api(path, { method: "GET" });
    writeLog(refs.godReportResult, data);
  } catch (error) {
    writeLog(refs.godReportResult, `Report request failed: ${error.message}`);
  } finally {
    setBusy(button, false);
  }
}

function persistTypedKey() {
  const value = String(refs.godAccessKey?.value || "").trim();
  state.key = value;
  saveKey(value);
  writeLog(refs.godContextResult, value ? "God key saved in this browser." : "God key cleared.");
}

function bindEvents() {
  refs.saveGodKeyBtn?.addEventListener("click", persistTypedKey);
  refs.refreshGodBtn?.addEventListener("click", refreshAll);
  refs.godStartBtn?.addEventListener("click", startWalkthrough);
  refs.godSubmitAttemptBtn?.addEventListener("click", submitAttempt);
  refs.godAdvanceBtn?.addEventListener("click", advancePhase);
  refs.godRevealBtn?.addEventListener("click", revealTruth);
  refs.godDraftPublicBtn?.addEventListener("click", () =>
    requestDraft("public_reply", refs.godDraftPublicBtn)
  );
  refs.godDraftInternalBtn?.addEventListener("click", () =>
    requestDraft("internal_note", refs.godDraftInternalBtn)
  );
  refs.godDraftEscalationBtn?.addEventListener("click", () =>
    requestDraft("escalation_handoff", refs.godDraftEscalationBtn)
  );
  refs.godReplayBtn?.addEventListener("click", loadReplay);
  refs.godDailyBtn?.addEventListener("click", () => loadGodReport("daily", refs.godDailyBtn));
  refs.godWeeklyBtn?.addEventListener("click", () => loadGodReport("weekly", refs.godWeeklyBtn));

  refs.godSessionSelect?.addEventListener("change", async () => {
    state.selectedSessionId = String(refs.godSessionSelect.value || "").trim();
    await loadSessionTickets(state.selectedSessionId);
    const ticketId = selectedTicketId();
    if (ticketId) {
      await loadWalkthrough(ticketId);
    } else {
      state.walkthrough = null;
      renderWalkthrough();
    }
  });

  refs.godTicketSelect?.addEventListener("change", async () => {
    state.selectedTicketId = String(refs.godTicketSelect.value || "").trim();
    await loadWalkthrough(state.selectedTicketId);
  });
}

async function init() {
  const saved = readSavedKey();
  state.key = saved;
  if (refs.godAccessKey) {
    refs.godAccessKey.value = saved;
  }
  bootstrapKeyFromQuery();
  bindEvents();
  await refreshAll();
}

init().catch((error) => {
  writeLog(refs.godContextResult, `Initialization failed: ${error.message}`);
  refs.godStatusBadge.className = "badge fail";
  refs.godStatusBadge.textContent = "Error";
});
