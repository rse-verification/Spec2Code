const elements = {
  title: document.getElementById("runTitle"),
  identity: document.getElementById("runIdentity"),
  summary: document.getElementById("resultsSummaryText"),
  metrics: document.getElementById("metricCards"),
  critics: document.getElementById("criticOverview"),
  outcome: document.getElementById("outcomeDistribution"),
  runtime: document.getElementById("runtimeProfile"),
  findings: document.getElementById("findingsTable"),
  findingsCount: document.getElementById("findingsCount"),
  search: document.getElementById("findingSearch"),
  criticFilter: document.getElementById("findingCriticFilter"),
  severityFilter: document.getElementById("findingSeverityFilter"),
  source: document.getElementById("sourceViewer"),
  diagnostic: document.getElementById("diagnosticViewer"),
  evidence: document.getElementById("evidenceSummary"),
  artifacts: document.getElementById("artifactLinksResults"),
  download: document.getElementById("evidenceDownload"),
  refresh: document.getElementById("refreshResultsBtn"),
};

let activeData = null;
let activeCritics = [];
let activeFindings = [];
let selectedFinding = null;
let sourceTab = "c";

function escapeHtml(value) {
  return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function formatSeconds(value) {
  const total = Math.max(0, Math.round(Number(value) || 0));
  const minutes = Math.floor(total / 60);
  return minutes ? `${minutes}m ${String(total % 60).padStart(2, "0")}s` : `${total}s`;
}

function criticDuration(critic) {
  return Number(critic.elapsed_time_s ?? (critic.metrics || {}).elapsed_time_s ?? 0);
}

function severity(value) {
  const normalized = String(value || "info").toLowerCase();
  return ["error", "warning", "info"].includes(normalized) ? normalized : "info";
}

function criticStatus(critic) {
  const findings = critic.findings || [];
  if (findings.some((finding) => severity(finding.severity) === "error") || critic.score === 0) return "failed";
  if (critic.score === 1 || critic.success === true) return findings.length ? "warning" : "passed";
  return "warning";
}

function locationText(location = {}) {
  return location.file ? `${location.file}${location.line != null ? `:${location.line}` : ""}` : "No source location";
}

function allFindings(critics) {
  return critics.flatMap((critic) => (critic.findings || []).map((finding, index) => ({
    ...finding,
    id: `${critic.tool || "critic"}-${index}`,
    tool: critic.tool || "unknown",
    severity: severity(finding.severity),
  }))).sort((a, b) => (severityRank(b.severity) - severityRank(a.severity)) || a.tool.localeCompare(b.tool));
}

function severityRank(value) {
  return { error: 3, warning: 2, info: 1 }[severity(value)];
}

function renderHeader() {
  const passed = activeCritics.filter((critic) => criticStatus(critic) === "passed").length;
  const errors = activeFindings.filter((finding) => finding.severity === "error").length;
  const warnings = activeFindings.filter((finding) => finding.severity === "warning").length;
  const duration = Number(activeData.total_elapsed_time_program || activeCritics.reduce((sum, critic) => sum + criticDuration(critic), 0));
  const status = errors ? "Needs attention" : warnings ? "Warnings" : "Passed";
  const statusClass = errors ? "failed" : warnings ? "warning" : "passed";
  elements.title.innerHTML = `<span class="status-pill ${statusClass}">${status}</span> ${passed}/${activeCritics.length} critics passed`;
  elements.identity.textContent = [activeData.exact_model_used, activeData.sample_name, activeData.attempt_name].filter(Boolean).join(" / ") || "Latest run";
  elements.summary.textContent = `${errors} error${errors === 1 ? "" : "s"} · ${warnings} warning${warnings === 1 ? "" : "s"} · ${formatSeconds(duration)} total`;
  const verification = activeData.verify_success === true ? "Passed" : activeData.verify_success === false ? "Failed" : "Not run";
  const cards = [["Overall status", status, statusClass], ["Critics passed", `${passed} / ${activeCritics.length}`, statusClass], ["Errors", errors, errors ? "failed" : "passed"], ["Warnings", warnings, warnings ? "warning" : "passed"], ["Total duration", formatSeconds(duration), "info"], ["Verification", verification, verification === "Passed" ? "passed" : "info"]];
  elements.metrics.innerHTML = cards.map(([label, value, kind]) => `<div class="metric-card ${kind}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
}

function renderCritics() {
  elements.critics.innerHTML = activeCritics.map((critic) => {
    const status = criticStatus(critic);
    const findings = critic.findings || [];
    const mainIssue = findings[0]?.message || critic.summary || (status === "passed" ? "No findings" : "No diagnostic details");
    return `<tr class="critic-row ${elements.criticFilter.value === critic.tool ? "selected" : ""}" data-critic="${escapeHtml(critic.tool || "unknown")}" tabindex="0"><td><span class="status-strip ${status}"></span>${escapeHtml(critic.tool || "unknown")}</td><td><span class="status-label ${status}">${status}</span></td><td>${Math.round(Number(critic.score || 0) * 100)}%</td><td>${findings.length}</td><td>${formatSeconds(criticDuration(critic))}</td><td class="main-issue">${escapeHtml(mainIssue)}</td></tr>`;
  }).join("") || '<tr><td colspan="6" class="empty-cell">No critic results available.</td></tr>';
  elements.critics.querySelectorAll(".critic-row").forEach((row) => row.addEventListener("click", () => {
    elements.criticFilter.value = row.dataset.critic;
    renderCritics();
    renderFindings();
  }));
}

function renderOutcome() {
  const counts = { passed: 0, warning: 0, failed: 0 };
  activeCritics.forEach((critic) => { counts[criticStatus(critic)] += 1; });
  const total = activeCritics.length || 1;
  elements.outcome.innerHTML = Object.entries(counts).map(([kind, count]) => `<div class="distribution-row"><span>${kind}</span><div><i class="${kind}" style="width:${(count / total) * 100}%"></i></div><b>${count}</b></div>`).join("");
}

function renderRuntime() {
  const total = activeCritics.reduce((sum, critic) => sum + criticDuration(critic), 0) || 1;
  const max = Math.max(...activeCritics.map(criticDuration), 0.001);
  elements.runtime.innerHTML = [...activeCritics].sort((a, b) => criticDuration(b) - criticDuration(a)).map((critic) => {
    const duration = criticDuration(critic);
    return `<div class="runtime-row"><span>${escapeHtml(critic.tool || "unknown")}</span><div><i style="width:${(duration / max) * 100}%"></i></div><b>${formatSeconds(duration)} <small>${Math.round((duration / total) * 100)}%</small></b></div>`;
  }).join("") || '<p class="muted-note">No timing information available.</p>';
}

function filteredFindings() {
  const search = elements.search.value.trim().toLowerCase();
  return activeFindings.filter((finding) => (!elements.criticFilter.value || finding.tool === elements.criticFilter.value) && (!elements.severityFilter.value || finding.severity === elements.severityFilter.value) && (!search || [finding.tool, finding.message, finding.rule, locationText(finding.location)].some((value) => String(value || "").toLowerCase().includes(search))));
}

function renderFindings() {
  const findings = filteredFindings();
  elements.findingsCount.textContent = `${findings.length} of ${activeFindings.length} finding${activeFindings.length === 1 ? "" : "s"}`;
  elements.findings.innerHTML = findings.map((finding) => `<tr data-finding="${escapeHtml(finding.id)}"><td><span class="severity-label ${finding.severity}">${finding.severity}</span></td><td>${escapeHtml(finding.tool)}</td><td>${escapeHtml(locationText(finding.location))}</td><td>${escapeHtml(finding.rule || "-")}</td><td class="finding-message">${escapeHtml(finding.message || "No message")}</td><td><button class="link-button" type="button">View</button></td></tr>`).join("") || '<tr><td colspan="6" class="empty-cell">No findings match these filters.</td></tr>';
  elements.findings.querySelectorAll("tr[data-finding]").forEach((row) => row.addEventListener("click", () => selectFinding(activeFindings.find((finding) => finding.id === row.dataset.finding))));
}

function renderSource() {
  const code = sourceTab === "header" ? activeData.generated_header : activeData.code;
  const path = sourceTab === "header" ? activeData.generated_header_path : activeData.generated_file_path;
  const highlights = new Map();
  activeFindings.forEach((finding) => {
    const file = String(finding.location?.file || "");
    if (finding.location?.line && (path ? (file.endsWith(path) || path.endsWith(file)) : file.endsWith(sourceTab === "header" ? ".h" : ".c"))) highlights.set(Number(finding.location.line), finding);
  });
  elements.source.innerHTML = String(code || "No generated source available.").replace(/\r\n?/g, "\n").split("\n").map((line, index) => {
    const number = index + 1;
    const finding = highlights.get(number);
    return `<div class="source-line ${finding ? finding.severity : ""}" data-line="${number}"><span>${number}</span><code>${escapeHtml(line || " ")}</code>${finding ? '<i aria-label="Finding on this line">!</i>' : ""}</div>`;
  }).join("");
}

function selectFinding(finding) {
  if (!finding) return;
  selectedFinding = finding;
  sourceTab = String(finding.location?.file || "").endsWith(".h") ? "header" : "c";
  document.querySelectorAll(".source-tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.source === sourceTab));
  renderSource();
  elements.diagnostic.classList.remove("hidden");
  elements.source.classList.add("hidden");
  elements.diagnostic.innerHTML = `<p class="eyebrow">${escapeHtml(finding.tool)}</p><h3>${escapeHtml(finding.rule || "Diagnostic")}</h3><p><span class="severity-label ${finding.severity}">${finding.severity}</span> ${escapeHtml(locationText(finding.location))}</p><p class="diagnostic-message">${escapeHtml(finding.message || "No message")}</p><button id="showSourceBtn" class="secondary-action" type="button">Open location in code</button>`;
  document.getElementById("showSourceBtn").addEventListener("click", () => {
    elements.diagnostic.classList.add("hidden"); elements.source.classList.remove("hidden");
    const line = elements.source.querySelector(`[data-line="${Number(finding.location?.line || 1)}"]`);
    line?.scrollIntoView({ block: "center", behavior: "smooth" });
  });
}

function renderEvidence() {
  const totalGoals = activeCritics.reduce((sum, critic) => sum + Number(critic.metrics?.goals_total || 0), 0);
  const proved = activeCritics.reduce((sum, critic) => sum + Number(critic.metrics?.goals_proved || 0), 0);
  elements.evidence.innerHTML = `<div><span>Model</span><strong>${escapeHtml(activeData.exact_model_used || "Unknown")}</strong></div><div><span>Generation attempts</span><strong>${activeData.generation_attempt_count || 1}</strong></div><div><span>Proof obligations</span><strong>${totalGoals ? `${proved} / ${totalGoals} proved` : "Not reported"}</strong></div>`;
  const artifacts = [["C source", activeData.generated_file_path], ["Header", activeData.generated_header_path], ["ACSL", activeData.generated_acsl_path]].filter(([, path]) => path);
  elements.artifacts.innerHTML = artifacts.map(([label, path]) => `<a href="/api/artifact?path=${encodeURIComponent(path)}">${label}</a>`).join("") || '<span class="muted-note">No generated artifacts available.</span>';
}

function populateCriticFilter() {
  const selected = elements.criticFilter.value;
  elements.criticFilter.innerHTML = '<option value="">All critics</option>' + activeCritics.map((critic) => `<option value="${escapeHtml(critic.tool || "unknown")}">${escapeHtml(critic.tool || "unknown")}</option>`).join("");
  elements.criticFilter.value = selected;
}

async function refreshResults() {
  try {
    const [run, verify] = await Promise.all([fetch("/api/latest-result", { cache: "no-store" }).then((response) => response.json()), fetch("/api/latest-verify", { cache: "no-store" }).then((response) => response.json())]);
    const useVerify = verify.ok && (!run.ok || Number(verify.mtime || 0) >= Number(run.mtime || 0));
    activeData = useVerify ? (verify.data.result || verify.data) : run.data;
    if (!activeData) throw new Error((run.error || verify.error || "No result is available"));
    activeCritics = activeData.critics_results || [];
    activeFindings = allFindings(activeCritics);
    selectedFinding = null;
    populateCriticFilter(); renderHeader(); renderCritics(); renderOutcome(); renderRuntime(); renderFindings(); renderSource(); renderEvidence();
    elements.download.href = useVerify ? "/reports/latest-verify.json" : "/api/latest-result";
  } catch (error) {
    elements.title.textContent = "No result available";
    elements.summary.textContent = String(error.message || error);
  }
}

elements.refresh.addEventListener("click", refreshResults);
[elements.search, elements.criticFilter, elements.severityFilter].forEach((control) => control.addEventListener("input", () => { renderCritics(); renderFindings(); }));
document.querySelectorAll(".source-tab").forEach((tab) => tab.addEventListener("click", () => {
  sourceTab = tab.dataset.source;
  document.querySelectorAll(".source-tab").forEach((button) => button.classList.toggle("active", button === tab));
  if (sourceTab === "diagnostic") { if (selectedFinding) selectFinding(selectedFinding); return; }
  elements.diagnostic.classList.add("hidden"); elements.source.classList.remove("hidden"); renderSource();
}));
refreshResults();
