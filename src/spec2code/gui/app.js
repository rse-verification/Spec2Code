const fileInput = document.getElementById("fileInput");
const overview = document.getElementById("overview");
const criticsList = document.getElementById("criticsList");
const codeBlock = document.getElementById("codeBlock");
const headerBlock = document.getElementById("headerBlock");
const acslPath = document.getElementById("acslPath");
const criticsSummary = document.getElementById("criticsSummary");
const findingsTable = document.getElementById("findingsTable");
const promptBlock = document.getElementById("promptBlock");
const rawBlock = document.getElementById("rawBlock");
const findingFilter = document.getElementById("findingFilter");

const params = new URLSearchParams(window.location.search || "");
const isEmbeddedView = params.get("embed") === "1" || window.self !== window.top;
if (isEmbeddedView) {
  document.body.classList.add("embedded-view");
}

let currentData = null;

if (window.__PIPELINE_DATA__) {
  currentData = window.__PIPELINE_DATA__;
  renderAll(currentData);
}

const tabs = document.querySelectorAll(".tab");
tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    tabs.forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    const panel = document.getElementById(`tab-${tab.dataset.tab}`);
    if (panel) panel.classList.add("active");
  });
});

const themeButtons = document.querySelectorAll(".theme-btn");
themeButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const theme = btn.dataset.theme;
    document.body.classList.remove("theme-default", "theme-sun", "theme-slate", "theme-monokai");
    if (theme === "default") document.body.classList.add("theme-default");
    if (theme === "sun") document.body.classList.add("theme-sun");
    if (theme === "slate") document.body.classList.add("theme-slate");
    if (theme === "monokai") document.body.classList.add("theme-monokai");
    themeButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
  });
});

// default theme
const defaultTheme = document.querySelector(".theme-btn[data-theme='slate']");
if (defaultTheme) defaultTheme.classList.add("active");

fileInput.addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const text = await file.text();
  try {
    currentData = JSON.parse(text);
    renderAll(currentData);
  } catch (err) {
    alert("Invalid JSON file.");
  }
});

findingFilter.addEventListener("input", () => {
  if (currentData) {
    renderFindings(currentData, findingFilter.value.trim());
  }
});

function renderAll(data) {
  renderOverview(data);
  renderCriticsList(data);
  renderCode(data);
  renderCriticsSummary(data);
  renderFindings(data, "");
  renderPrompt(data);
  renderRaw(data);
}

function renderOverview(data) {
  const items = [
    ["Model", data.exact_model_used || "n/a"],
    ["Verify", boolLabel(data.verify_success)],
    ["Critics", data.critics_results ? data.critics_results.length : 0],
    ["Critics Score", formatScore(data.critics_score)],
    ["Elapsed", formatSeconds(data.total_elapsed_time_program)],
    ["C File", data.generated_file_path || "n/a"],
    ["Header", data.generated_header_path || "n/a"],
    ["ACSL", data.generated_acsl_path || "n/a"],
  ];

  overview.innerHTML = items
    .map(([key, value]) => {
      return `<div class="kv"><div class="key">${escapeHtml(key)}</div><div class="value">${escapeHtml(String(value))}</div></div>`;
    })
    .join("");
}

function renderCriticsList(data) {
  const list = data.critics_results || [];
  if (!list.length) {
    criticsList.innerHTML = "<div class=\"kv-empty\">No critics results.</div>";
    return;
  }
  criticsList.innerHTML = list
    .map((c) => {
      const badge = criticBadge(c);
      const score = formatScore(c.score);
      return `
        <div class="list-item">
          ${badge}
          <strong>${escapeHtml(c.tool || "unknown")}</strong>
          <div class="muted">score: ${score}</div>
          <div class="muted">${escapeHtml(c.summary || "")}</div>
        </div>
      `;
    })
    .join("");
}

function renderCode(data) {
  const findings = collectFindings(data);
  const cHighlights = buildLineHighlights(findings, data.generated_file_path, ".c");
  const hHighlights = buildLineHighlights(findings, data.generated_header_path, ".h");

  codeBlock.innerHTML = renderHighlightedCode(compactCodeForViewer(data.code || ""), "c", cHighlights);
  headerBlock.innerHTML = renderHighlightedCode(compactCodeForViewer(data.generated_header || ""), "c", hHighlights);
  acslPath.textContent = data.generated_acsl_path || "";
}

function compactCodeForViewer(code) {
  const lines = String(code || "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n");
  const out = [];
  let lastBlank = false;
  lines.forEach((line) => {
    const isBlank = line.trim() === "";
    if (isBlank && lastBlank) return;
    out.push(line);
    lastBlank = isBlank;
  });
  const blankCount = out.filter((l) => l.trim() === "").length;
  if (out.length > 0 && blankCount / out.length > 0.2) {
    return out.filter((l) => l.trim() !== "").join("\n");
  }
  return out.join("\n");
}

function renderCriticsSummary(data) {
  const list = data.critics_results || [];
  if (!list.length) {
    criticsSummary.innerHTML = "<div class=\"kv-empty\">No critics data.</div>";
    return;
  }
  criticsSummary.innerHTML = list
    .map((c) => {
      const metrics = c.metrics || {};
      const native = metrics.native || {};
      return `
        <div class="card">
          <div class="card-title">${escapeHtml(c.tool || "unknown")}</div>
          <div>${criticBadge(c)} score ${formatScore(c.score)}</div>
          <div class="muted">${escapeHtml(c.summary || "")}</div>
          <div class="muted">elapsed: ${formatSeconds(metrics.elapsed_time_s)}</div>
          <div class="muted">timeout: ${metrics.timeout ?? "n/a"}</div>
          ${metrics.warnings != null ? `<div class="muted">warnings: ${metrics.warnings}</div>` : ""}
          ${metrics.compiled_output_path ? `<div class="muted">output: ${escapeHtml(metrics.compiled_output_path)}</div>` : ""}
          ${metrics.goals_ratio ? `<div class="muted">goals: ${escapeHtml(metrics.goals_ratio)}</div>` : ""}
          ${native.preprocessed_acsl_path ? `<div class="muted">pp acsl: ${escapeHtml(native.preprocessed_acsl_path)}</div>` : ""}
        </div>
      `;
    })
    .join("");
}

function renderFindings(data, filterText) {
  const list = data.critics_results || [];
  const rows = [];
  list.forEach((c) => {
    (c.findings || []).forEach((f) => {
      rows.push({
        tool: c.tool || "unknown",
        severity: f.severity || "info",
        message: f.message || "",
        location: formatLocation(f.location || {}),
      });
    });
  });

  const filtered = filterText
    ? rows.filter((r) =>
        [r.tool, r.severity, r.message, r.location].some((v) =>
          String(v).toLowerCase().includes(filterText.toLowerCase())
        )
      )
    : rows;

  if (!filtered.length) {
    findingsTable.innerHTML = "<div class=\"kv-empty\">No findings.</div>";
    return;
  }

  findingsTable.innerHTML = filtered
    .map((r) => {
      return `
        <div class="row">
          <div>${escapeHtml(r.tool)}</div>
          <div class="severity">${escapeHtml(r.severity)}</div>
          <div>${escapeHtml(r.message)}</div>
          <div class="location">${escapeHtml(r.location)}</div>
        </div>
      `;
    })
    .join("");
}

function renderPrompt(data) {
  promptBlock.textContent = data.filled_prompt || "";
}

function renderRaw(data) {
  rawBlock.textContent = data.raw_output || "";
}

function collectFindings(data) {
  const list = data.critics_results || [];
  const out = [];
  list.forEach((c) => {
    (c.findings || []).forEach((f) => out.push(f));
  });
  return out;
}

function buildLineHighlights(findings, filePath, extension) {
  const map = new Map();
  findings.forEach((f) => {
    if (!f || !f.location) return;
    const locFile = f.location.file || "";
    const line = f.location.line;
    if (!line || !locFile) return;
    const matches = filePath
      ? locFile === filePath || locFile.endsWith(String(filePath)) || String(filePath).endsWith(locFile)
      : locFile.endsWith(extension);
    if (!matches) return;
    const sev = f.severity || "info";
    const prev = map.get(line);
    if (!prev || severityRank(sev) > severityRank(prev)) {
      map.set(line, sev);
    }
  });
  return map;
}

function renderHighlightedCode(code, language, highlights) {
  if (!code) return "";
  let highlighted = escapeHtml(code);
  if (window.hljs) {
    try {
      highlighted = hljs.highlight(code, { language }).value;
    } catch (e) {
      highlighted = escapeHtml(code);
    }
  }
  const lines = highlighted.split("\n");
  return lines
    .map((lineHtml, idx) => {
      const lineNumber = idx + 1;
      const sev = highlights.get(lineNumber);
      const sevClass = sev ? ` ${sev}` : "";
      return `
        <div class="line${sevClass}">
          <div class="line-num">${lineNumber}</div>
          <div class="line-code">${lineHtml || " "}</div>
        </div>
      `;
    })
    .join("");
}

function severityRank(sev) {
  const s = String(sev || "").toLowerCase();
  if (s === "error") return 3;
  if (s === "warning") return 2;
  return 1;
}

function boolLabel(value) {
  return value === true ? "true" : value === false ? "false" : "n/a";
}

function formatScore(value) {
  if (value == null || Number.isNaN(value)) return "n/a";
  return Number(value).toFixed(2);
}

function formatSeconds(value) {
  if (value == null || Number.isNaN(value)) return "n/a";
  const total = Math.max(0, Math.round(Number(value)));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h${String(m).padStart(2, "0")}m${String(s).padStart(2, "0")}s`;
  if (m > 0) return `${m}m${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

function formatLocation(loc) {
  const file = loc.file || "";
  const line = loc.line != null ? `:${loc.line}` : "";
  const col = loc.column != null ? `:${loc.column}` : "";
  return file ? `${file}${line}${col}` : "";
}

function criticBadge(c) {
  if (c.score === 1 || c.success === true) {
    return `<span class="badge ok">ok</span>`;
  }
  if (c.score && c.score > 0) {
    return `<span class="badge warn">warn</span>`;
  }
  return `<span class="badge err">fail</span>`;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
