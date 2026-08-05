/**
 * SOC Incident Reporting & Alerting Portal
 * Frontend logic — vanilla JS, no build step required.
 */

const API_BASE = "/api";

const state = {
  incidents: [],
  severityFilter: "All",
  search: "",
};

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const form = document.getElementById("incident-form");
const submitBtn = document.getElementById("submit-btn");
const submitSpinner = document.getElementById("submit-spinner");
const submitLabel = document.getElementById("submit-label");
const tableBody = document.getElementById("incident-table-body");
const emptyState = document.getElementById("empty-state");
const loadingState = document.getElementById("loading-state");
const searchInput = document.getElementById("search-input");
const toastContainer = document.getElementById("toast-container");
const connStatus = document.getElementById("conn-status");
const liveClock = document.getElementById("live-clock");

const statTotal = document.getElementById("stat-total");
const statCritical = document.getElementById("stat-critical");
const statOpen = document.getElementById("stat-open");
const statResolved = document.getElementById("stat-resolved");

const detailModal = document.getElementById("detail-modal");
const modalBody = document.getElementById("modal-body");
const modalClose = document.getElementById("modal-close");

const severityFilterButtons = Array.from(document.querySelectorAll(".severity-filter"));

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

function formatTimestamp(isoString) {
  try {
    const date = new Date(isoString);
    return date.toLocaleString(undefined, {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch (err) {
    return isoString;
  }
}

function severityBadgeClass(severity) {
  const map = {
    Low: "badge-low",
    Medium: "badge-medium",
    High: "badge-high",
    Critical: "badge-critical",
  };
  return map[severity] || "badge-low";
}

function showToast(message, type = "info") {
  const colors = {
    success: { border: "border-emerald-500/40", text: "text-emerald-300", icon: "✓" },
    error: { border: "border-critical/50", text: "text-red-300", icon: "✕" },
    info: { border: "border-cyan-500/40", text: "text-cyan-300", icon: "ℹ" },
    warning: { border: "border-amber-500/40", text: "text-amber-300", icon: "!" },
  };
  const style = colors[type] || colors.info;

  const toast = document.createElement("div");
  toast.className = `toast-enter bg-panel2 border ${style.border} rounded-lg px-4 py-3 shadow-lg flex items-start gap-3`;
  toast.innerHTML = `
    <span class="${style.text} font-bold text-sm mt-0.5">${style.icon}</span>
    <p class="text-sm text-slate-200 flex-1">${escapeHtml(message)}</p>
  `;
  toastContainer.appendChild(toast);

  setTimeout(() => {
    toast.style.transition = "opacity 0.3s ease, transform 0.3s ease";
    toast.style.opacity = "0";
    toast.style.transform = "translateX(20px)";
    setTimeout(() => toast.remove(), 300);
  }, 4200);
}

function setConnectionStatus(connected) {
  if (connected) {
    connStatus.textContent = "LINK ESTABLISHED";
    connStatus.className = "text-[11px] font-mono px-2.5 py-1 rounded border border-emerald-500/40 text-emerald-400";
  } else {
    connStatus.textContent = "LINK DOWN";
    connStatus.className = "text-[11px] font-mono px-2.5 py-1 rounded border border-critical/50 text-red-400";
  }
}

function tickClock() {
  const now = new Date();
  liveClock.textContent = now.toLocaleTimeString(undefined, { hour12: false });
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let data = null;
  try {
    data = await response.json();
  } catch (err) {
    data = null;
  }
  if (!response.ok) {
    const message = data && data.error ? data.error : `Request failed (${response.status})`;
    const error = new Error(message);
    error.details = data;
    throw error;
  }
  return data;
}

async function fetchIncidents() {
  loadingState.classList.remove("hidden");
  try {
    const params = new URLSearchParams();
    if (state.severityFilter !== "All") params.set("severity", state.severityFilter);
    if (state.search) params.set("search", state.search);

    const data = await apiRequest(`/incidents?${params.toString()}`);
    state.incidents = data.incidents || [];
    setConnectionStatus(true);
    renderTable();
    renderStats();
  } catch (err) {
    setConnectionStatus(false);
    showToast(`Unable to reach incident log: ${err.message}`, "error");
  } finally {
    loadingState.classList.add("hidden");
  }
}

async function createIncident(payload) {
  return apiRequest("/incidents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

async function updateIncidentStatus(id, status) {
  return apiRequest(`/incidents/${id}`, {
    method: "PUT",
    body: JSON.stringify({ status }),
  });
}

async function deleteIncident(id) {
  return apiRequest(`/incidents/${id}`, { method: "DELETE" });
}

async function resendAlert(id) {
  return apiRequest(`/incidents/${id}/alert`, { method: "POST" });
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderStats() {
  const total = state.incidents.length;
  const critical = state.incidents.filter((i) => i.severity === "Critical").length;
  const open = state.incidents.filter((i) => i.status === "Open" || i.status === "Investigating").length;
  const resolved = state.incidents.filter((i) => i.status === "Resolved").length;

  statTotal.textContent = total;
  statCritical.textContent = critical;
  statOpen.textContent = open;
  statResolved.textContent = resolved;
}

function renderTable() {
  tableBody.innerHTML = "";

  if (state.incidents.length === 0) {
    emptyState.classList.remove("hidden");
    return;
  }
  emptyState.classList.add("hidden");

  state.incidents.forEach((incident, idx) => {
    const row = document.createElement("tr");
    row.className = "hover:bg-panel2/60 transition-colors" + (idx === 0 ? " row-enter" : "");
    row.innerHTML = `
      <td class="px-5 sm:px-6 py-3.5 max-w-[280px]">
        <p class="text-slate-100 font-medium truncate">${escapeHtml(incident.title)}</p>
        <p class="text-xs text-slate-500 truncate mt-0.5">${escapeHtml(incident.description)}</p>
      </td>
      <td class="px-4 py-3.5">
        <span class="badge ${severityBadgeClass(incident.severity)}">
          <span class="badge-dot"></span>${escapeHtml(incident.severity)}
        </span>
      </td>
      <td class="px-4 py-3.5">
        <span class="status-pill">${escapeHtml(incident.status)}</span>
      </td>
      <td class="px-4 py-3.5 hidden md:table-cell text-slate-400 font-mono text-xs">${escapeHtml(incident.asset)}</td>
      <td class="px-4 py-3.5 hidden lg:table-cell text-slate-400 text-xs">${escapeHtml(incident.reporter)}</td>
      <td class="px-4 py-3.5 text-slate-500 text-xs font-mono whitespace-nowrap">${formatTimestamp(incident.created_at)}</td>
      <td class="px-4 sm:px-6 py-3.5 text-right whitespace-nowrap">
        <button data-action="view" data-id="${incident.id}" class="text-cyan-400 hover:text-cyan-300 text-xs font-mono mr-3">VIEW</button>
        <button data-action="delete" data-id="${incident.id}" class="text-red-400 hover:text-red-300 text-xs font-mono">DEL</button>
      </td>
    `;
    tableBody.appendChild(row);
  });
}

function openDetailModal(incident) {
  modalBody.innerHTML = `
    <div class="flex items-center gap-2 mb-1">
      <span class="badge ${severityBadgeClass(incident.severity)}"><span class="badge-dot"></span>${escapeHtml(incident.severity)}</span>
      <span class="status-pill">${escapeHtml(incident.status)}</span>
    </div>
    <h3 class="font-display text-lg font-700 text-slate-50 mt-2 mb-2">${escapeHtml(incident.title)}</h3>
    <p class="text-sm text-slate-300 leading-relaxed mb-4">${escapeHtml(incident.description)}</p>
    <div class="grid grid-cols-2 gap-3 text-xs mb-5">
      <div class="bg-panel2 border border-border rounded-md p-3">
        <p class="text-slate-500 font-mono uppercase tracking-widest mb-1">Asset</p>
        <p class="text-slate-200">${escapeHtml(incident.asset)}</p>
      </div>
      <div class="bg-panel2 border border-border rounded-md p-3">
        <p class="text-slate-500 font-mono uppercase tracking-widest mb-1">Reported By</p>
        <p class="text-slate-200">${escapeHtml(incident.reporter)}</p>
      </div>
      <div class="bg-panel2 border border-border rounded-md p-3 col-span-2">
        <p class="text-slate-500 font-mono uppercase tracking-widest mb-1">Incident ID</p>
        <p class="text-slate-400 font-mono text-[11px] break-all">${escapeHtml(incident.id)}</p>
      </div>
    </div>
    <div class="flex flex-col gap-2">
      <label class="text-xs font-mono text-slate-400">Update Status</label>
      <select id="modal-status-select" class="w-full bg-panel2 border border-border rounded-md px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-cyan-400/30">
        <option value="Open">Open</option>
        <option value="Investigating">Investigating</option>
        <option value="Contained">Contained</option>
        <option value="Resolved">Resolved</option>
      </select>
      <div class="flex gap-2 mt-2">
        <button id="modal-save-status" class="flex-1 bg-cyan-600/90 hover:bg-cyan-500 text-slate-950 text-sm font-display font-700 rounded-md py-2 transition">SAVE STATUS</button>
        <button id="modal-resend-alert" class="flex-1 bg-panel2 border border-border hover:border-amber-400/50 text-amber-300 text-sm font-display font-700 rounded-md py-2 transition">RESEND ALERT</button>
      </div>
    </div>
  `;

  const statusSelect = document.getElementById("modal-status-select");
  statusSelect.value = incident.status;

  document.getElementById("modal-save-status").addEventListener("click", async () => {
    try {
      await updateIncidentStatus(incident.id, statusSelect.value);
      showToast("Incident status updated.", "success");
      closeModal();
      fetchIncidents();
    } catch (err) {
      showToast(`Failed to update status: ${err.message}`, "error");
    }
  });

  document.getElementById("modal-resend-alert").addEventListener("click", async () => {
    try {
      const result = await resendAlert(incident.id);
      if (result.alert && result.alert.sent) {
        showToast("Alert email re-dispatched successfully.", "success");
      } else {
        const reason = result.alert ? result.alert.reason : "Unknown error";
        showToast(`Alert not sent: ${reason}`, "warning");
      }
    } catch (err) {
      showToast(`Failed to resend alert: ${err.message}`, "error");
    }
  });

  detailModal.classList.remove("hidden");
}

function closeModal() {
  detailModal.classList.add("hidden");
  modalBody.innerHTML = "";
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const formData = new FormData(form);
  const payload = {
    title: formData.get("title").trim(),
    description: formData.get("description").trim(),
    severity: formData.get("severity"),
    status: formData.get("status"),
    asset: formData.get("asset").trim(),
    reporter: formData.get("reporter").trim(),
  };

  submitBtn.disabled = true;
  submitSpinner.classList.remove("hidden");
  submitLabel.textContent = "DISPATCHING…";

  try {
    const result = await createIncident(payload);
    showToast(`Incident "${result.incident.title}" logged successfully.`, "success");

    if (result.alert && result.alert.sent) {
      showToast(`Email alert dispatched via ${result.alert.provider}.`, "success");
    } else if (result.alert) {
      showToast(`Incident saved, but alert email was not sent: ${result.alert.reason}`, "warning");
    }

    form.reset();
    document.getElementById("field-severity").value = "Medium";
    document.getElementById("field-status").value = "Open";

    await fetchIncidents();
  } catch (err) {
    const detailMsg =
      err.details && err.details.details ? err.details.details.join(", ") : err.message;
    showToast(`Failed to log incident: ${detailMsg}`, "error");
  } finally {
    submitBtn.disabled = false;
    submitSpinner.classList.add("hidden");
    submitLabel.textContent = "DISPATCH INCIDENT REPORT";
  }
});

tableBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;

  const { action, id } = button.dataset;
  const incident = state.incidents.find((i) => i.id === id);
  if (!incident) return;

  if (action === "view") {
    openDetailModal(incident);
  } else if (action === "delete") {
    if (!confirm(`Delete incident "${incident.title}"? This cannot be undone.`)) return;
    try {
      await deleteIncident(id);
      showToast("Incident deleted.", "success");
      fetchIncidents();
    } catch (err) {
      showToast(`Failed to delete incident: ${err.message}`, "error");
    }
  }
});

severityFilterButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    severityFilterButtons.forEach((b) => b.removeAttribute("data-active"));
    btn.setAttribute("data-active", "true");
    state.severityFilter = btn.dataset.severity;
    fetchIncidents();
  });
});

let searchDebounce;
searchInput.addEventListener("input", (event) => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => {
    state.search = event.target.value.trim();
    fetchIncidents();
  }, 300);
});

modalClose.addEventListener("click", closeModal);
detailModal.addEventListener("click", (event) => {
  if (event.target === detailModal) closeModal();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeModal();
});

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

tickClock();
setInterval(tickClock, 1000);
fetchIncidents();
setInterval(fetchIncidents, 15000);
