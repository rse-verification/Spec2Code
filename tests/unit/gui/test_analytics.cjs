const { test } = require("node:test");
const assert = require("node:assert/strict");
const analytics = require("../../../src/spec2code/gui/analytics.js");

test("explicit failures, absent results and unknown scores never become passes", () => {
  assert.equal(analytics.status({ success: false, score: 1, findings: [] }), "failed");
  assert.equal(analytics.status({ success: false, score: 0.8 }), "failed");
  assert.equal(analytics.status({ success: true, findings: [{ severity: "info" }] }), "passed");
  assert.equal(analytics.summarize({}).overall, "unknown");
  assert.equal(analytics.status({}), "unknown");
  assert.equal(analytics.summarize({ error: "parse failed" }).overall, "failed");
});

test("timing statistics distinguish zero from missing, and source counts deduplicate lines", () => {
  const data = { critics_results: [
    { tool: "compile", success: true, elapsed_time_s: 0, findings: [{ location: { file: "x.c", line: 1 } }] },
    { tool: "wp", success: false, metrics: { elapsed_time_s: 0.4 }, findings: [{ severity: "error", location: { file: "x.c", line: 1 } }, { severity: "warning" }] },
    { tool: "unmeasured" },
  ] };
  const stats = analytics.summarize(data);
  assert.equal(stats.criticSeconds, 0.4);
  assert.equal(stats.median, 0.2);
  assert.equal(stats.durations.length, 2);
  assert.equal(stats.lines, 1);
  assert.equal(stats.findings.length - stats.located.length, 1);
  assert.equal(stats.overall, "failed");
  assert.equal(analytics.summarize({}).criticSeconds, null);
});

test("figures use actual proof metrics, preserve unknowns, escape labels and include repair history", () => {
  const data = { critics_results: [{ tool: '<script>"&', metrics: { total_goals: 8, proved_goals: 6 }, findings: [{ rule: "<img>" }] }], generation_attempts: [{ critics_results: [{ success: false }], total_elapsed_time_attempt: 1.5 }, { critics_results: [{ success: true }], total_elapsed_time_attempt: 2 }] };
  const figures = analytics.figures(data, analytics.summarize(data));
  assert.deepEqual(figures.find((f) => f.title === "Proof obligations").rows.map((r) => r.value), [6, 2]);
  assert.deepEqual(figures.find((f) => f.title === "Repair progress").rows.map((r) => r.value), [0, 1]);
  assert.equal(figures.find((f) => f.title === "Scores by critic").rows[0].value, null);
  for (const figure of figures) {
    assert.ok(!figure.chart.includes("<script>"));
    assert.ok(!figure.chart.includes("<img>"));
    assert.ok(!figure.chart.includes("NaN"));
  }
});
