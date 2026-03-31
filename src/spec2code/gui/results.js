const reportFrame = document.getElementById("reportFrame");
const reportLinkResults = document.getElementById("reportLinkResults");
const criticBars = document.getElementById("criticBars");
const outcomePie = document.getElementById("outcomePie");
const outcomeLegend = document.getElementById("outcomeLegend");
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

    // Extra safeguard for already-rendered reports/assets: compact visually
    // noisy blank rows when they dominate the code blocks.
    const codeBlocks = Array.from(doc.querySelectorAll(".code-block"));
    codeBlocks.forEach((block) => {
      const rows = Array.from(block.querySelectorAll(".line"));
      if (!rows.length) return;
      const blankRows = rows.filter((r) => {
        const t = (r.querySelector(".line-code")?.textContent || "").trim();
        return t === "";
      });
      if (blankRows.length / rows.length > 0.2) {
        blankRows.forEach((r) => r.remove());
      }
    });
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
      reportFrame.srcdoc = "<html><body style='font-family:Segoe UI,sans-serif;padding:16px;color:#8a8f99;background:#23262d'>No report or verify result available yet.</body></html>";
      return;
    }

    const runMtime = Number(runRes.payload && runRes.payload.mtime) || 0;
    const verifyMtime = Number(verifyRes.payload && verifyRes.payload.mtime) || 0;
    const useVerify = verifyOk && (!runOk || verifyMtime >= runMtime);

    let critics = [];
    if (useVerify) {
      const data = (verifyRes.payload && verifyRes.payload.data) || {};
      critics = ((data.result || {}).critics_results) || [];
      const cFile = (((data.inputs || {}).c_file_path) || "").toString();
      reportFrame.srcdoc = `<html><body style="font-family:Segoe UI,sans-serif;padding:16px;color:#dbe2ee;background:#23262d"><h3 style="margin:0 0 8px">Latest Verify Result</h3><div style="opacity:.85">Source file: ${escapeHtml(cFile || "(unknown)")}</div><div style="margin-top:8px;opacity:.8">Open full JSON for details.</div></body></html>`;
      if (reportLinkResults) {
        reportLinkResults.href = "/reports/latest-verify.json";
        reportLinkResults.textContent = "Open verify JSON in new tab";
      }
    } else {
      const data = (runRes.payload && runRes.payload.data) || {};
      critics = data.critics_results || [];
      reportFrame.src = "/reports/last-run.html?embed=1";
      if (reportLinkResults) {
        reportLinkResults.href = "/reports/last-run.html";
        reportLinkResults.textContent = "Open latest report in new tab";
      }
    }

    renderBars(critics);
    renderOutcome(critics);
  } catch (e) {
    criticBars.textContent = `Failed to load results: ${e}`;
  }
}

refreshResultsBtn.addEventListener("click", refreshResults);
refreshResults();
