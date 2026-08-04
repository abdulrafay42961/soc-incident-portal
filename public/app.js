const state = {
  incidents: [],
  filter: "all",
};

const elements = {
  form: document.getElementById("incident-form"),
  tableBody: document.getElementById("incident-table-body"),
  stats: {
    total: document.getElementById("stat-total"),
    critical: document.getElementById("stat-critical"),
    open: document.getElementById("stat-open"),
    resolved: document.getElementById("stat-resolved"),
  },
  filterButtons: Array.from(document.querySelectorAll("[data-filter]")),
  toast: document.getElementById("toast"),
  refreshButton: document.getElementById("refresh-button"),
};

function getSeverityClasses(severity) {
  const normalized = (severity || "medium").toLowerCase();
  const styles = {
    low: "border-emerald-400/30 bg-emerald-500/15 text-emerald-300",
    medium: "border-amber-400/30 bg-amber-500/15 text-amber-300",
    high: "border-orange-400/30 bg-orange-500/15 text-orange-300",
    critical: "border-rose-400/30 bg-rose-500/15 text-rose-300",
  };
  return styles[normalized] || styles.medium;
}

function getStatusClasses(status) {
  const normalized = (status || "open").toLowerCase();
  const styles = {
    open: "bg-cyan-500/15 text-cyan-300",
    investigating: "bg-violet-500/15 text-violet-300",
    resolved: "bg-emerald-500/15 text-emerald-300",
  };
  return styles[normalized] || styles.open;
}

function formatTimestamp(value) {
  if (!value) {
    return "—";
  }

  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function showToast(message, type = "info") {
  elements.toast.textContent = message;
  elements.toast.className = `fixed bottom-6 right-6 z-50 rounded-xl border px-4 py-3 text-sm font-medium shadow-2xl transition-all ${
    type === "error"
      ? "border-rose-400/40 bg-rose-500/15 text-rose-200"
      : "border-cyan-400/40 bg-slate-950/90 text-cyan-100"
  }`;
  elements.toast.classList.remove("hidden");

  clearTimeout(showToast.timeoutId);
  showToast.timeoutId = window.setTimeout(() => {
    elements.toast.classList.add("hidden");
  }, 3200);
}

function updateFilterButtons() {
  elements.filterButtons.forEach((button) => {
    const active = button.dataset.filter === state.filter;
    button.className = `rounded-full border px-3 py-2 text-sm transition ${
      active
        ? "border-cyan-400/60 bg-cyan-500/20 text-cyan-200"
        : "border-slate-700 bg-slate-900/70 text-slate-300 hover:border-slate-600"
    }`;
  });
}

function renderStats() {
  const total = state.incidents.length;
  const critical = state.incidents.filter((item) => item.severity === "critical").length;
  const open = state.incidents.filter((item) => item.status === "open").length;
  const resolved = state.incidents.filter((item) => item.status === "resolved").length;

  elements.stats.total.textContent = String(total);
  elements.stats.critical.textContent = String(critical);
  elements.stats.open.textContent = String(open);
  elements.stats.resolved.textContent = String(resolved);
}

function renderTable() {
  const visibleIncidents = state.filter === "all"
    ? state.incidents
    : state.incidents.filter((item) => item.severity === state.filter);

  if (!visibleIncidents.length) {
    elements.tableBody.innerHTML = `
      <tr>
        <td colspan="6" class="px-4 py-8 text-center text-sm text-slate-400">
          No incidents match the selected view.
        </td>
      </tr>
    `;
    return;
  }

  elements.tableBody.innerHTML = visibleIncidents
    .map((incident) => {
      const severityClasses = getSeverityClasses(incident.severity);
      const statusClasses = getStatusClasses(incident.status);
      return `
        <tr class="border-b border-slate-800/70 text-sm text-slate-300">
          <td class="px-4 py-3 font-mono text-cyan-300">${incident.id}</td>
          <td class="px-4 py-3">
            <div class="font-semibold text-slate-100">${incident.title}</div>
            <div class="mt-1 text-xs text-slate-400">${incident.description}</div>
          </td>
          <td class="px-4 py-3">
            <span class="rounded-full border px-2.5 py-1 text-xs font-semibold ${severityClasses}">
              ${incident.severity.toUpperCase()}
            </span>
          </td>
          <td class="px-4 py-3">
            <span class="rounded-full px-2.5 py-1 text-xs font-semibold ${statusClasses}">
              ${incident.status.toUpperCase()}
            </span>
          </td>
          <td class="px-4 py-3 text-slate-400">${incident.source}</td>
          <td class="px-4 py-3 text-slate-400">${formatTimestamp(incident.created_at)}</td>
        </tr>
      `;
    })
    .join("");
}

async function loadIncidents() {
  try {
    const response = await fetch("/api/incidents", { headers: { Accept: "application/json" } });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Unable to load incidents");
    }
    state.incidents = Array.isArray(data.incidents) ? data.incidents : [];
    renderStats();
    renderTable();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function handleSubmit(event) {
  event.preventDefault();

  const payload = {
    title: document.getElementById("title").value.trim(),
    description: document.getElementById("description").value.trim(),
    severity: document.getElementById("severity").value,
    source: document.getElementById("source").value.trim() || "portal",
    status: document.getElementById("status").value,
  };

  if (!payload.title || !payload.description) {
    showToast("Please include both the title and the description.", "error");
    return;
  }

  try {
    const response = await fetch("/api/incidents", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Incident submission failed");
    }

    state.incidents.unshift(data.incident);
    renderStats();
    renderTable();
    elements.form.reset();
    showToast(`Incident ${data.incident.id} recorded and alert workflow triggered.`);
  } catch (error) {
    showToast(error.message, "error");
  }
}

function attachEvents() {
  elements.filterButtons.forEach((button) => {
    button.addEventListener("click", () => {
      state.filter = button.dataset.filter;
      updateFilterButtons();
      renderTable();
    });
  });

  elements.form.addEventListener("submit", handleSubmit);
  elements.refreshButton.addEventListener("click", loadIncidents);
}

attachEvents();
updateFilterButtons();
loadIncidents();
