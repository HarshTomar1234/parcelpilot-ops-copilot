"use strict";

const state = {
  demoUsers: [],
  currentUserId: "ops_admin",
  lastAction: null, // most recently prepared/confirmed action record
};

function el(id) { return document.getElementById(id); }

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-Demo-User": state.currentUserId,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* no body */ }
  if (!res.ok) {
    const detail = (data && data.detail) ? data.detail : `request failed (${res.status})`;
    const err = new Error(detail);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

function fmtTime(iso) {
  if (!iso) return "-";
  return iso.replace("T", " ").replace(/\.\d+(?=[+Z-])/, "");
}

function badge(text, cls) {
  const span = document.createElement("span");
  span.className = `badge ${cls}`;
  span.textContent = text;
  return span;
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Live models write **bold** in prose; render it instead of showing the
// literal asterisks (found by testing a real answer against the live UI).
function renderAnswerHtml(str) {
  return escapeHtml(str).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

// ---------- top bar / identity ----------

async function loadIdentities() {
  const users = await api("/api/demo-users");
  state.demoUsers = users;
  const sel = el("identity-select");
  sel.innerHTML = "";
  for (const u of users) {
    const opt = document.createElement("option");
    opt.value = u.id;
    opt.textContent = u.display_name;
    sel.appendChild(opt);
  }
  sel.value = state.currentUserId;
  sel.addEventListener("change", () => {
    state.currentUserId = sel.value;
    renderCurrentIdentity();
  });
  renderCurrentIdentity();
}

function renderCurrentIdentity() {
  const user = state.demoUsers.find((u) => u.id === state.currentUserId);
  el("identity-role").textContent = user ? user.role : "";
  el("identity-scope").textContent = user
    ? (user.account_scope ? `scope: ${user.account_scope.join(", ")}` : "scope: all accounts")
    : "";
}

async function loadReadiness() {
  try {
    const res = await fetch("/ready");
    const data = await res.json();
    const banner = el("snapshot-banner");
    if (data.dataset_snapshot) {
      banner.innerHTML =
        `Assessment snapshot: <strong>${fmtTime(data.dataset_snapshot)}</strong> - ` +
        "all answers reason from this fixed point in time, not the current clock.";
    } else {
      banner.innerHTML =
        '<strong>Not ready:</strong> the database has not been ingested yet - see README Quickstart.';
    }
  } catch {
    el("snapshot-banner").innerHTML = '<strong>Backend unreachable.</strong>';
  }
}

// ---------- tabs ----------

function initTabs() {
  const buttons = document.querySelectorAll("nav.tabs button");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      el(btn.dataset.panel).classList.add("active");
    });
  });
}

function switchToTab(panelId) {
  document.querySelectorAll("nav.tabs button").forEach((b) => {
    b.classList.toggle("active", b.dataset.panel === panelId);
  });
  document.querySelectorAll(".panel").forEach((p) => {
    p.classList.toggle("active", p.id === panelId);
  });
}

// ---------- Support Copilot ----------

function renderEvidenceRef(ref) {
  const locator = ref.locator ? `:${ref.locator}` : "";
  return `[${ref.source_id}${locator}]${ref.note ? " " + ref.note : ""}`;
}

async function submitQuestion() {
  const question = el("question").value.trim();
  const out = el("chat-result");
  if (!question) { return; }
  out.innerHTML = '<div class="empty-state">Asking the agent...</div>';
  el("ask-button").disabled = true;
  try {
    const data = await api("/api/chat", { method: "POST", body: { question } });
    renderChatResult(data);
  } catch (err) {
    out.innerHTML = `<div class="error-box">${err.message}</div>`;
  } finally {
    el("ask-button").disabled = false;
  }
}

function renderChatResult(data) {
  const r = data.result;
  const out = el("chat-result");
  out.innerHTML = "";

  const card = document.createElement("div");
  card.className = "card";

  const head = document.createElement("div");
  head.className = "row";
  head.appendChild(badge(r.status, r.status === "completed" ? "status-ok" : "status-bad"));
  if (r.trust_state) head.appendChild(badge(r.trust_state, `trust-${r.trust_state}`));
  if (r.needs_human_review) head.appendChild(badge("Human follow-up recommended", "review"));
  card.appendChild(head);

  if (r.answer) {
    const p = document.createElement("p");
    p.innerHTML = renderAnswerHtml(r.answer);
    card.appendChild(p);
  }
  if (r.reason) {
    const p = document.createElement("p");
    p.className = "muted small";
    p.textContent = r.reason;
    card.appendChild(p);
  }

  if (r.citations && r.citations.length) {
    const h = document.createElement("h3"); h.textContent = "Citations"; card.appendChild(h);
    const ul = document.createElement("ul"); ul.className = "plain";
    r.citations.forEach((c) => { const li = document.createElement("li"); li.textContent = renderEvidenceRef(c); ul.appendChild(li); });
    card.appendChild(ul);
  }

  if (r.assumptions && r.assumptions.length) {
    const h = document.createElement("h3"); h.textContent = "Assumptions"; card.appendChild(h);
    const ul = document.createElement("ul"); ul.className = "plain";
    r.assumptions.forEach((a) => { const li = document.createElement("li"); li.textContent = a; ul.appendChild(li); });
    card.appendChild(ul);
  }

  if (r.conflicts && r.conflicts.length) {
    const h = document.createElement("h3"); h.textContent = "Source conflicts"; card.appendChild(h);
    const ul = document.createElement("ul"); ul.className = "plain";
    r.conflicts.forEach((c) => {
      const li = document.createElement("li");
      li.textContent = `${c.winner_source_id} overrides ${c.loser_source_id}: ${c.reason}`;
      ul.appendChild(li);
    });
    card.appendChild(ul);
  }

  if (r.tool_trace && r.tool_trace.length) {
    const h = document.createElement("h3"); h.textContent = "Tool execution"; card.appendChild(h);
    const wrap = document.createElement("div"); wrap.className = "overflow-x";
    const table = document.createElement("table");
    table.innerHTML = "<thead><tr><th>Tool</th><th>Purpose</th><th>OK</th><th>Latency (ms)</th></tr></thead>";
    const tbody = document.createElement("tbody");
    r.tool_trace.forEach((t) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${t.tool}</td><td>${t.purpose || ""}</td><td>${t.success ? "yes" : "no"}</td><td>${t.latency_ms}</td>`;
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    card.appendChild(wrap);
  }

  const foot = document.createElement("footer");
  foot.className = "result-meta";
  const metaLine = document.createElement("div");
  metaLine.className = "row";
  metaLine.innerHTML =
    `<span><strong>Intent:</strong> ${r.intent || "-"}</span>` +
    `<span><strong>Latency:</strong> ${r.total_latency_ms.toFixed(1)} ms</span>` +
    `<span><strong>Cost:</strong> $${r.total_cost_usd.toFixed(6)}</span>` +
    `<span><strong>Request ID:</strong> ${r.request_id}</span>`;
  const traceLine = document.createElement("div");
  traceLine.className = "state-trace";
  traceLine.innerHTML = `<strong>State trace:</strong> ${r.state_trace.join(" &rarr; ")}`;
  foot.appendChild(metaLine);
  foot.appendChild(traceLine);
  card.appendChild(foot);

  out.appendChild(card);
}

// ---------- Operations Radar ----------

function alertTypeCheckboxes() {
  return Array.from(document.querySelectorAll(".radar-type:checked")).map((c) => c.value);
}

async function runRadar() {
  const out = el("radar-result");
  out.innerHTML = '<div class="empty-state">Running Operations Radar...</div>';
  el("radar-run-button").disabled = true;
  try {
    const types = alertTypeCheckboxes();
    const body = {
      alert_types: types.length ? types : null,
      window_days: Number(el("radar-window").value) || 30,
      group_by_account: false,
    };
    const data = await api("/api/radar/run", { method: "POST", body });
    renderRadarResult(data);
  } catch (err) {
    if (err.status === 403) {
      out.innerHTML = `<div class="error-box">Unauthorized: ${err.message}</div>`;
    } else {
      out.innerHTML = `<div class="error-box">${err.message}</div>`;
    }
  } finally {
    el("radar-run-button").disabled = false;
  }
}

function renderRadarResult(data) {
  const out = el("radar-result");
  out.innerHTML = "";

  const summary = document.createElement("div");
  summary.className = "row small muted";
  summary.style.marginBottom = "10px";
  summary.innerHTML =
    `<span>${data.total_alerts} alert${data.total_alerts === 1 ? "" : "s"}</span>` +
    `<span>latency: ${data.latency_ms.toFixed(2)} ms</span>` +
    `<span>snapshot: ${fmtTime(data.dataset_snapshot)}</span>`;
  out.appendChild(summary);

  if (!data.alerts.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No alerts for this scope, window, and filter.";
    out.appendChild(empty);
    return;
  }

  const severityFilter = el("radar-severity-filter").value;
  const alerts = severityFilter === "all"
    ? data.alerts
    : data.alerts.filter((a) => a.severity === severityFilter);

  if (!alerts.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No alerts match the severity filter.";
    out.appendChild(empty);
    return;
  }

  alerts.forEach((a) => out.appendChild(renderAlertCard(a)));
}

function renderAlertCard(a) {
  const card = document.createElement("div");
  card.className = "card";

  const head = document.createElement("div");
  head.className = "row";
  head.appendChild(badge(a.severity, `severity-${a.severity}`));
  head.appendChild(badge(a.alert_type, "neutral"));
  head.appendChild(badge(a.trust_state, `trust-${a.trust_state}`));
  card.appendChild(head);

  const title = document.createElement("strong");
  title.textContent = a.title;
  title.style.display = "block";
  title.style.margin = "8px 0 4px";
  card.appendChild(title);

  const reason = document.createElement("p");
  reason.className = "small";
  reason.textContent = a.reason;
  card.appendChild(reason);

  const meta = document.createElement("p");
  meta.className = "muted small";
  meta.textContent =
    `observed ${a.observed_count} / threshold ${a.threshold}  -  window: ${a.time_window}  -  ` +
    `accounts: ${a.affected_accounts.join(", ") || "-"}`;
  card.appendChild(meta);

  if (a.evidence && a.evidence.length) {
    const pre = document.createElement("pre");
    pre.className = "evidence";
    pre.textContent = a.evidence.map(renderEvidenceRef).join("\n");
    card.appendChild(pre);
  }

  const next = document.createElement("p");
  next.className = "small";
  next.innerHTML = `<strong>Recommended:</strong> ${a.recommended_next_step}`;
  card.appendChild(next);

  const ticketId = a.representative_records.find((r) => r.startsWith("TKT"));
  if (ticketId) {
    const btn = document.createElement("button");
    btn.className = "secondary";
    btn.textContent = `Prepare escalation for ${ticketId}`;
    btn.addEventListener("click", () => {
      el("prepare-ticket-id").value = ticketId;
      el("prepare-reason").value = `Operations Radar alert ${a.alert_id}: ${a.title}`;
      switchToTab("panel-actions");
    });
    card.appendChild(btn);
  }

  return card;
}

// ---------- Action Panel ----------

function renderProposedChange(change) {
  return Object.entries(change).map(([k, v]) => `${k}: ${v}`).join("\n");
}

function actionOutcomeError(out, outcome) {
  out.innerHTML =
    `<div class="error-box"><strong>${outcome.error_code}</strong> - ${outcome.error_message}</div>`;
}

async function prepareAction() {
  const out = el("action-result");
  const ticketId = el("prepare-ticket-id").value.trim();
  const reason = el("prepare-reason").value.trim();
  if (!ticketId || !reason) { return; }
  out.innerHTML = '<div class="empty-state">Preparing...</div>';
  try {
    const data = await api("/api/actions/prepare", {
      method: "POST", body: { ticket_id: ticketId, reason },
    });
    if (!data.outcome.success) { actionOutcomeError(out, data.outcome); return; }
    state.lastAction = data.outcome.record;
    renderActionRecord(out, data.outcome.record, "prepared");
  } catch (err) {
    out.innerHTML = `<div class="error-box">${err.message}</div>`;
  }
}

async function confirmAction() {
  const out = el("action-result");
  if (!state.lastAction) return;
  out.innerHTML = '<div class="empty-state">Confirming...</div>';
  try {
    const data = await api("/api/actions/confirm", {
      method: "POST",
      body: { action_id: state.lastAction.action_id, payload_hash: state.lastAction.payload_hash },
    });
    if (!data.outcome.success) { actionOutcomeError(out, data.outcome); return; }
    state.lastAction = data.outcome.record;
    renderActionRecord(out, data.outcome.record, "confirmed");
  } catch (err) {
    out.innerHTML = `<div class="error-box">${err.message}</div>`;
  }
}

async function executeAction() {
  const out = el("action-result");
  if (!state.lastAction) return;
  out.innerHTML = '<div class="empty-state">Executing...</div>';
  try {
    const data = await api("/api/actions/execute", {
      method: "POST", body: { action_id: state.lastAction.action_id },
    });
    if (!data.outcome.success) { actionOutcomeError(out, data.outcome); return; }
    state.lastAction = data.outcome.record;
    renderActionRecord(out, data.outcome.record, "executed");
  } catch (err) {
    out.innerHTML = `<div class="error-box">${err.message}</div>`;
  }
}

function renderActionRecord(out, record, stage) {
  out.innerHTML = "";
  const card = document.createElement("div");
  card.className = "card";

  const head = document.createElement("div");
  head.className = "row";
  head.appendChild(badge(record.status, record.status === "EXECUTED" ? "status-ok" : "neutral"));
  head.appendChild(badge(record.risk, record.risk === "high" ? "severity-high" : "severity-medium"));
  card.appendChild(head);

  const lines = [
    ["Target", record.target],
    ["Reason", record.reason],
    ["Proposed change", renderProposedChange(record.proposed_change)],
    ["Evidence", record.evidence.map(renderEvidenceRef).join("\n")],
    ["Action ID", record.action_id],
    ["Prepared at", fmtTime(record.prepared_at)],
    ["Expires at", fmtTime(record.expires_at)],
    ["Confirmed at", fmtTime(record.confirmed_at)],
    ["Executed at", fmtTime(record.executed_at)],
  ];
  const pre = document.createElement("pre");
  pre.className = "evidence";
  pre.textContent = lines.map(([k, v]) => `${k}:\n  ${String(v).split("\n").join("\n  ")}`).join("\n\n");
  card.appendChild(pre);

  const actions = document.createElement("div");
  actions.className = "row";
  actions.style.marginTop = "10px";

  if (record.status === "PENDING_CONFIRMATION") {
    const confirmBtn = document.createElement("button");
    confirmBtn.className = "primary";
    confirmBtn.textContent = "Confirm";
    confirmBtn.addEventListener("click", confirmAction);
    actions.appendChild(confirmBtn);
  } else if (record.status === "CONFIRMED") {
    const execBtn = document.createElement("button");
    execBtn.className = "danger";
    execBtn.textContent = "Execute";
    execBtn.addEventListener("click", executeAction);
    actions.appendChild(execBtn);
  } else if (record.status === "EXECUTED") {
    const done = document.createElement("span");
    done.className = "badge status-ok";
    done.textContent = "EXECUTED";
    actions.appendChild(done);
  }
  card.appendChild(actions);
  out.appendChild(card);
}

// ---------- init ----------

document.addEventListener("DOMContentLoaded", async () => {
  initTabs();
  await loadIdentities();
  await loadReadiness();
  el("ask-button").addEventListener("click", submitQuestion);
  el("question").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submitQuestion();
  });
  el("radar-run-button").addEventListener("click", runRadar);
  el("prepare-button").addEventListener("click", prepareAction);
});
