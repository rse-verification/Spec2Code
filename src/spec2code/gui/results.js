const reportFrame = document.getElementById("reportFrame");
const reportLinkResults = document.getElementById("reportLinkResults");
const criticBars = document.getElementById("criticBars");
const outcomePie = document.getElementById("outcomePie");
const outcomeLegend = document.getElementById("outcomeLegend");
const criticTimes = document.getElementById("criticTimes");
const severityBars = document.getElementById("severityBars");
const artifactLinksResults = document.getElementById("artifactLinksResults");
const resultsSummaryText = document.getElementById("resultsSummaryText");
const refreshResultsBtn = document.getElementById("refreshResultsBtn");

function applyReportFrameEmbedPatch() {
  try {
    const doc = reportFrame.contentDocument;
    if (!doc || !doc.body) return;
    doc.body.classList.add("embedded-view");

    if (doc.getElementById("spec2codeEmbedPatch")) return;
    const style = doc.createElement("style");
    style.id = "spec2codeEmbedPatch";
    style.textContent = `
      body.embedded-view .hotbar,
      body.embedded-view .workspace-header,
      body.embedded-view .actions,
      body.embedded-view .footer { display: none !important; }
      body.embedded-view .app-shell { grid-template-columns: 1fr !important; min-height: auto !important; }
      body.embedded-view .workspace { padding: 0 !important; }
      .tabs { align-items: flex-start !important; }
      .tab { min-height: 34px !important; height: auto !important; display: inline-flex !important; align-items: center !important; flex: 0 0 auto !important; }
      .code-block .line { line-height: 1.15 !important; padding-top: 0 !important; padding-bottom: 0 !important; }
      .code-block .line-code { white-space: pre !important; }
    `;
    doc.head.appendChild(style);

  } catch (_e) {
    // ignore cross-frame/transient load issues
  }
}

reportFrame.addEventListener("load", applyReportFrameEmbedPatch);

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderBars(critics) {
  criticBars.innerHTML = "";
  if (!Array.isArray(critics) || !critics.length) {
    criticBars.textContent = "No critics data available.";
    return;
  }
  critics.forEach((c) => {
    const score = Number(c.score || 0);
    const pct = Math.max(0, Math.min(100, score * 100));
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `
      <div>${escapeHtml(c.tool || "unknown")}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      <div>${pct.toFixed(0)}%</div>
    `;
    criticBars.appendChild(row);
  });
}

function renderOutcome(critics) {
  let ok = 0;
  let warn = 0;
  let fail = 0;
  (critics || []).forEach((c) => {
    if (c.score === 1 || c.success === true) ok += 1;
    else if (Number(c.score || 0) > 0) warn += 1;
    else fail += 1;
  });
  const total = ok + warn + fail || 1;
  const okDeg = (ok / total) * 360;
  const warnDeg = (warn / total) * 360;
  outcomePie.style.background = `conic-gradient(#43aa8b 0deg ${okDeg}deg, #ffd166 ${okDeg}deg ${okDeg + warnDeg}deg, #ef476f ${okDeg + warnDeg}deg 360deg)`;
  outcomeLegend.innerHTML = `
    <div class="legend-item"><span class="legend-swatch" style="background:#43aa8b"></span><span>ok: ${ok} (${((ok / total) * 100).toFixed(0)}%)</span></div>
    <div class="legend-item"><span class="legend-swatch" style="background:#ffd166"></span><span>warn: ${warn} (${((warn / total) * 100).toFixed(0)}%)</span></div>
    <div class="legend-item"><span class="legend-swatch" style="background:#ef476f"></span><span>fail: ${fail} (${((fail / total) * 100).toFixed(0)}%)</span></div>
  `;
}

function renderTimes(critics) {
  if (!Array.isArray(critics) || !critics.length) {
    criticTimes.textContent = "No critic timing data available.";
    return;
  }
  const durations = critics.map((critic) => Number(critic.elapsed_time_s ?? (critic.metrics || {}).elapsed_time_s ?? 0));
  const maximum = Math.max(...durations, 0.001);
  criticTimes.innerHTML = critics.map((critic, index) => {
    const seconds = durations[index];
    const percent = Math.max(1, Math.min(100, (seconds / maximum) * 100));
    return `<div class="bar-row"><div>${escapeHtml(critic.tool || "unknown")}</div><div class="bar-track"><div class="bar-fill time-fill" style="width:${percent}%"></div></div><div>${formatSeconds(seconds)}</div></div>`;
  }).join("");
}

function renderSeverity(critics) {
  const counts = { error: 0, warning: 0, info: 0 };
  (critics || []).forEach((critic) => (critic.findings || []).forEach((finding) => {
    const severity = String(finding.severity || "info").toLowerCase();
    counts[severity] = (counts[severity] || 0) + 1;
  }));
  const maximum = Math.max(...Object.values(counts), 1);
  severityBars.innerHTML = Object.entries(counts).map(([severity, count]) => {
    const percent = (count / maximum) * 100;
    return `<div class="bar-row severity-${severity}"><div>${escapeHtml(severity)}</div><div class="bar-track"><div class="bar-fill" style="width:${percent}%"></div></div><div>${count}</div></div>`;
  }).join("");
}

function formatSeconds(value) {
  const total = Math.max(0, Math.round(Number(value) || 0));
  const minutes = Math.floor(total / 60);
  return minutes ? `${minutes}m${String(total % 60).padStart(2, "0")}s` : `${total}s`;
}

function renderArtifacts(data) {
  const artifacts = [
    ["C file", data.generated_file_path],
    ["Header", data.generated_header_path],
    ["ACSL", data.generated_acsl_path],
  ].filter(([, path]) => path);
  artifactLinksResults.innerHTML = artifacts.length
    ? artifacts.map(([label, path]) => `<a href="/api/artifact?path=${encodeURIComponent(path)}" target="_blank" rel="noopener">${escapeHtml(label)}</a>`).join("")
    : "<span class=\"muted-note\">No generated artifacts available.</span>";
}

async function refreshResults() {
  try {
    const [runRes, verifyRes] = await Promise.all([
      fetch("/api/latest-result").then(async (r) => {
        const p = await r.json().catch(() => ({ ok: false, error: `HTTP ${r.status}` }));
        return { status: r.status, payload: p };
      }),
      fetch("/api/latest-verify").then(async (r) => {
        const p = await r.json().catch(() => ({ ok: false, error: `HTTP ${r.status}` }));
        return { status: r.status, payload: p };
      }),
    ]);

    const runOk = !!(runRes.payload && runRes.payload.ok);
    const verifyOk = !!(verifyRes.payload && verifyRes.payload.ok);

    if (!runOk && !verifyOk) {
      criticBars.textContent = (verifyRes.payload && verifyRes.payload.error) || (runRes.payload && runRes.payload.error) || "No results.";
      outcomeLegend.textContent = "";
      outcomePie.style.background = "transparent";
      criticTimes.textContent = "";
      severityBars.textContent = "";
      artifactLinksResults.textContent = "";
      resultsSummaryText.textContent = "No report or verify result is available yet.";
      reportFrame.srcdoc = "<html><body style='font-family:Segoe UI,sans-serif;padding:16px;color:#8a8f99;background:#23262d'>No report or verify result available yet.</body></html>";
      return;
    }

    const runMtime = Number(runRes.payload && runRes.payload.mtime) || 0;
    const verifyMtime = Number(verifyRes.payload && verifyRes.payload.mtime) || 0;
    const useVerify = verifyOk && (!runOk || verifyMtime >= runMtime);

    let critics = [];
    let activeData = {};
    if (useVerify) {
      const data = (verifyRes.payload && verifyRes.payload.data) || {};
      activeData = data.result || data;
      critics = ((data.result || {}).critics_results) || [];
      const cFile = (((data.inputs || {}).c_file_path) || "").toString();
      reportFrame.srcdoc = `<html><body style="font-family:Segoe UI,sans-serif;padding:16px;color:#dbe2ee;background:#23262d"><h3 style="margin:0 0 8px">Latest Verify Result</h3><div style="opacity:.85">Source file: ${escapeHtml(cFile || "(unknown)")}</div><div style="margin-top:8px;opacity:.8">Open full JSON for details.</div></body></html>`;
      if (reportLinkResults) {
        reportLinkResults.href = "/reports/latest-verify.json";
        reportLinkResults.textContent = "Open verify JSON in new tab";
      }
    } else {
      const data = (runRes.payload && runRes.payload.data) || {};
      activeData = data;
      critics = data.critics_results || [];
      reportFrame.src = "/reports/last-run.html?embed=1";
      if (reportLinkResults) {
        reportLinkResults.href = "/reports/last-run.html";
        reportLinkResults.textContent = "Open latest report in new tab";
      }
    }

    renderBars(critics);
    renderOutcome(critics);
    renderTimes(critics);
    renderSeverity(critics);
    renderArtifacts(activeData);
    const failed = critics.filter((critic) => !(critic.score === 1 || critic.success === true)).length;
    resultsSummaryText.textContent = `${critics.length} critic${critics.length === 1 ? "" : "s"} ran; ${failed} need${failed === 1 ? "s" : ""} attention. Open a highlighted line marker in the detailed report for the diagnostic message.`;
  } catch (e) {
    criticBars.textContent = `Failed to load results: ${e}`;
  }
}

refreshResultsBtn.addEventListener("click", refreshResults);
refreshResults();
