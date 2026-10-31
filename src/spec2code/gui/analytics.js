/* Shared by the live Results page and offline reports; no charting service required. */
(function (root) {
  "use strict";
  const colors = { passed: "#369569", failed: "#d85b53", warning: "#c3942b", unknown: "#8993a4", error: "#d85b53", info: "#4e8ac9" };
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const numeric = (value) => value !== null && value !== undefined && value !== "" && typeof value !== "boolean" && Number.isFinite(Number(value)) ? Number(value) : null;
  const nonnegative = (value) => { const n = numeric(value); return n !== null && n >= 0 ? n : null; };
  const format = (value) => value === null ? "Not reported" : Number(value.toFixed(3)).toLocaleString();
  const duration = (critic) => nonnegative(critic.elapsed_time_s ?? critic.metrics?.elapsed_time_s);
  const severity = (value) => ["error", "warning", "info"].includes(String(value).toLowerCase()) ? String(value).toLowerCase() : "info";

  function status(critic) {
    // The explicit critic verdict is authoritative, including partial proof failures.
    if (critic.success === false) return "failed";
    if (critic.success === true) return "passed";
    if ((critic.findings || []).some((f) => severity(f.severity) === "error")) return "failed";
    const score = numeric(critic.score);
    if (score === 1) return "passed";
    if (score === 0) return "failed";
    return score !== null && score > 0 && score < 1 ? "warning" : "unknown";
  }

  function summarize(data = {}) {
    const critics = Array.isArray(data.critics_results) ? data.critics_results : [];
    const outcomes = { passed: 0, failed: 0, warning: 0, unknown: 0 };
    const severities = { error: 0, warning: 0, info: 0 };
    const findings = [];
    critics.forEach((critic) => {
      outcomes[status(critic)] += 1;
      (critic.findings || []).forEach((finding) => {
        const item = { ...finding, tool: critic.tool || "unknown", severity: severity(finding.severity) };
        findings.push(item);
        severities[item.severity] += 1;
      });
    });
    const durations = critics.map(duration).filter((n) => n !== null).sort((a, b) => a - b);
    const middle = Math.floor(durations.length / 2);
    const median = durations.length ? (durations[middle] + durations[Math.floor((durations.length - 1) / 2)]) / 2 : null;
    const criticSeconds = durations.length ? durations.reduce((a, b) => a + b, 0) : null;
    const located = findings.filter((f) => f.location?.file && Number.isInteger(f.location.line) && f.location.line > 0);
    const lines = new Set(located.map((f) => `${f.location.file}:${f.location.line}`));
    const overall = data.error || data.critics_success === false || outcomes.failed ? "failed"
      : !critics.length || outcomes.unknown ? "unknown" : outcomes.warning ? "warning" : "passed";
    return { critics, outcomes, findings, severities, durations, median, criticSeconds, located, lines: lines.size, overall };
  }

  function bars(rows, maximum) {
    const max = maximum || Math.max(...rows.map((r) => r.value ?? 0), 1);
    const height = Math.max(50, rows.length * 42 + 12);
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 ${height}" role="img" aria-label="Bar chart; exact values in the table below"><rect width="640" height="${height}" fill="#f7f9fc"/>${rows.map((row, i) => {
      const y = i * 42 + 12;
      const label = String(row.label);
      return `<g><title>${escape(label)}: ${escape(row.display ?? format(row.value))}</title><text x="10" y="${y + 19}" fill="#243247" font-size="12">${escape(label.length > 25 ? `${label.slice(0, 24)}…` : label)}</text><rect x="205" y="${y}" width="300" height="28" rx="4" fill="#e2e8f0"/>${row.value !== null ? `<rect x="205" y="${y}" width="${Math.max(0, Math.min(300, row.value / max * 300))}" height="28" rx="4" fill="${row.color || colors.info}"/>` : ""}<text x="515" y="${y + 19}" fill="#243247" font-size="12">${escape(row.display ?? format(row.value))}</text></g>`;
    }).join("")}</svg>`;
  }

  function distribution(outcomes) {
    const total = Object.values(outcomes).reduce((a, b) => a + b, 0);
    let offset = 0;
    const arcs = Object.entries(outcomes).map(([key, count]) => {
      const percent = total ? count / total * 100 : 0;
      const arc = `<circle cx="100" cy="100" r="70" pathLength="100" fill="none" stroke="${colors[key]}" stroke-width="28" stroke-dasharray="${percent} ${100 - percent}" stroke-dashoffset="${-offset}" transform="rotate(-90 100 100)"><title>${key}: ${count}</title></circle>`;
      offset += percent;
      return arc;
    }).join("");
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 200" role="img" aria-label="Critic outcomes"><rect width="420" height="200" fill="#f7f9fc"/><circle cx="100" cy="100" r="70" fill="none" stroke="#e2e8f0" stroke-width="28"/>${arcs}<text x="100" y="106" text-anchor="middle" fill="#243247" font-size="26">${total}</text>${Object.entries(outcomes).map(([key, count], i) => `<circle cx="215" cy="${40 + i * 38}" r="6" fill="${colors[key]}"/><text x="232" y="${45 + i * 38}" fill="#243247" font-size="15">${key}: ${count}</text>`).join("")}</svg>`;
  }

  function counted(items, key) {
    const counts = new Map();
    items.forEach((item) => { const label = key(item); counts.set(label, (counts.get(label) || 0) + 1); });
    return [...counts].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
  }

  function figures(data, stats) {
    const { critics, outcomes, findings, severities } = stats;
    const result = [];
    const add = (title, note, rows, chart) => result.push({ title, note, rows, chart: chart || (rows.length ? bars(rows) : "") });
    add("Critic outcomes", "Verdicts use the critic's success flag. Missing results are not passes.", Object.entries(outcomes).map(([label, value]) => ({ label, value })), distribution(outcomes));
    const scores = critics.map((c) => ({ label: c.tool, value: numeric(c.score), display: numeric(c.score) === null ? "Not reported" : `${format(Number(c.score) * 100)}%`, color: colors[status(c)] }));
    add("Scores by critic", "Scores have tool-specific meanings; they are not averaged into a quality grade.", scores, scores.length ? bars(scores, 1) : "");
    add("Critic runtime", "Measured seconds for the displayed attempt. Missing timings remain unknown.", [...critics].sort((a, b) => (duration(b) ?? -1) - (duration(a) ?? -1)).map((c) => ({ label: c.tool, value: duration(c), display: duration(c) === null ? "Not reported" : `${format(duration(c))} s` })));
    add("Finding severity", "Counts of diagnostic records, including informational findings.", Object.entries(severities).map(([label, value]) => ({ label, value, color: colors[label] })));
    add("Findings by critic", "Zero findings does not necessarily mean a check passed.", critics.map((c) => ({ label: c.tool, value: (c.findings || []).length, color: colors[status(c)] })));
    add("Most frequent rules", "Top 10 rule identifiers, grouped by critic. Diagnostics without a rule are included.", counted(findings, (f) => `${f.tool}: ${f.rule || "No rule"}`).slice(0, 10));
    add("Source hotspots", "Top 10 files by diagnostic count. Full paths are available in the data table.", counted(findings, (f) => f.location?.file || "No source location").slice(0, 10));
    const goals = critics.flatMap((c) => {
      const m = c.metrics || {};
      const total = nonnegative(m.total_goals ?? m.goals_total), proved = nonnegative(m.proved_goals ?? m.goals_proved);
      return total !== null && proved !== null && proved <= total ? [{ label: `${c.tool}: proved`, value: proved, color: colors.passed }, { label: `${c.tool}: unproved`, value: total - proved, color: colors.failed }] : [];
    });
    add("Proof obligations", "Reported proof goals only; zero obligations is not proof of correctness.", goals);
    const resources = critics.flatMap((c) => ["binary_size_bytes", "binary_size_limit_bytes", "peak_heap_bytes", "heap_limit_bytes", "peak_stack_bytes", "stack_limit_bytes", "peak_total_bytes"].flatMap((key) => {
      const value = nonnegative(c.metrics?.[key]);
      if (value === null || (key.includes("limit") && value === 0)) return [];
      return [{ label: `${c.tool}: ${key.replace(/_/g, " ")}`, value, display: `${format(value)} B`, color: key.includes("limit") ? colors.unknown : colors.info }];
    }));
    add("Resource usage and limits", "Bytes reported by size/memory critics. Zero (disabled) memory limits are omitted.", resources);
    const attempts = Array.isArray(data.generation_attempts) ? data.generation_attempts : [];
    if (attempts.length) {
      add("Repair progress", "Passing critics per attempt; every attempt is retained, including unsuccessful repairs.", attempts.map((a, i) => {
        const s = summarize(a);
        return { label: `Attempt ${i + 1}`, value: s.outcomes.passed, display: `${s.outcomes.passed} / ${s.critics.length}`, color: colors[s.overall] };
      }));
      add("Attempt duration", "Generation plus evaluation wall-clock seconds for each attempt.", attempts.map((a, i) => ({ label: `Attempt ${i + 1}`, value: nonnegative(a.total_elapsed_time_attempt) })));
    }
    return result;
  }

  function render(container, data) {
    if (!container) return;
    const s = summarize(data);
    const cards = [
      ["Critic pass rate", s.critics.length ? `${format(s.outcomes.passed / s.critics.length * 100)}%` : "Not reported"],
      ["Failed / unknown", `${s.outcomes.failed} / ${s.outcomes.unknown}`],
      ["Findings", s.findings.length], ["Affected source lines", s.lines],
      ["Unlocated findings", s.findings.length - s.located.length],
      ["Measured critic time", s.criticSeconds === null ? "Not reported" : `${format(s.criticSeconds)} s`],
      ["Median critic time", s.median === null ? "Not reported" : `${format(s.median)} s`],
      ["Timing coverage", `${s.durations.length} / ${s.critics.length}`],
    ];
    const charts = figures(data, s);
    container.innerHTML = `<div class="analytics-stats">${cards.map(([label, value]) => `<div><span>${escape(label)}</span><strong>${escape(value)}</strong></div>`).join("")}</div><p class="analytics-note">Statistics describe this sample's final attempt. Repair charts appear when attempt history is available.</p><div class="analytics-grid">${charts.map((f, i) => `<figure class="analytics-figure"><figcaption>${escape(f.title)}</figcaption><p>${escape(f.note)}</p>${f.chart || '<div class="analytics-empty">No data reported for this figure.</div>'}${f.chart ? `<button type="button" data-chart="${i}">Download SVG</button>` : ""}<details><summary>View data (${f.rows.length})</summary><table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>${f.rows.map((r) => `<tr><td>${escape(r.label)}</td><td>${escape(r.display ?? format(r.value))}</td></tr>`).join("")}</tbody></table></details></figure>`).join("")}</div>`;
    container.querySelectorAll("[data-chart]").forEach((button) => button.addEventListener("click", () => {
      const figure = charts[Number(button.dataset.chart)];
      const url = URL.createObjectURL(new Blob([figure.chart], { type: "image/svg+xml" }));
      const link = document.createElement("a");
      link.href = url; link.download = `${figure.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.svg`;
      document.body.appendChild(link);
      link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }));
  }
  const api = { numeric, duration, status, summarize, figures, render };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Spec2CodeAnalytics = api;
})(typeof window === "undefined" ? globalThis : window);
