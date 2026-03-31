const cFilePath = document.getElementById("cFilePath");
const generatedHeaderPath = document.getElementById("generatedHeaderPath");
const includeDirs = document.getElementById("includeDirs");
const defines = document.getElementById("defines");
const generatedFiles = document.getElementById("generatedFiles");
const cleanupAfterVerify = document.getElementById("cleanupAfterVerify");
const verifyBtn = document.getElementById("verifyBtn");
const verifyStatus = document.getElementById("verifyStatus");
const verifyLog = document.getElementById("verifyLog");
const verifyBars = document.getElementById("verifyBars");
const verifyPie = document.getElementById("verifyPie");
const verifyLegend = document.getElementById("verifyLegend");
const criticsCatalog = document.getElementById("criticsCatalog");
const filePickerModal = document.getElementById("filePickerModal");
const pickerSearch = document.getElementById("pickerSearch");
const pickerList = document.getElementById("pickerList");
const pickerClose = document.getElementById("pickerClose");

let pickerState = { targetId: "", kind: "file", ext: "", append: false };
const criticsUi = window.Spec2CodeCriticsUI.create({
  container: criticsCatalog,
  idPrefix: "verify-opt",
});

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function setStatus(text, ok) {
  verifyStatus.textContent = text;
  verifyStatus.classList.remove("ok", "err");
  verifyStatus.classList.add(ok ? "ok" : "err");
}

function renderBars(critics) {
  verifyBars.innerHTML = "";
  if (!Array.isArray(critics) || !critics.length) {
    verifyBars.textContent = "No critics data available.";
    return;
  }
  critics.forEach((c) => {
    const score = Number(c && c.score ? c.score : 0);
    const pct = Math.max(0, Math.min(100, score * 100));
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `
      <div>${escapeHtml((c && c.tool) || "unknown")}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      <div>${pct.toFixed(0)}%</div>
    `;
    verifyBars.appendChild(row);
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
  verifyPie.style.background = `conic-gradient(#43aa8b 0deg ${okDeg}deg, #ffd166 ${okDeg}deg ${okDeg + warnDeg}deg, #ef476f ${okDeg + warnDeg}deg 360deg)`;
  verifyLegend.innerHTML = `
    <div class="legend-item"><span class="legend-swatch" style="background:#43aa8b"></span><span>ok: ${ok} (${((ok / total) * 100).toFixed(0)}%)</span></div>
    <div class="legend-item"><span class="legend-swatch" style="background:#ffd166"></span><span>warn: ${warn} (${((warn / total) * 100).toFixed(0)}%)</span></div>
    <div class="legend-item"><span class="legend-swatch" style="background:#ef476f"></span><span>fail: ${fail} (${((fail / total) * 100).toFixed(0)}%)</span></div>
  `;
}

function splitCsv(s) {
  return String(s || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}


function setFieldValue(targetId, value, append) {
  const el = document.getElementById(targetId);
  if (!el) return;
  if (!append) {
    el.value = value;
    return;
  }
  const parts = splitCsv(el.value);
  if (!parts.includes(value)) parts.push(value);
  el.value = parts.join(", ");
}

function closePicker() {
  filePickerModal.classList.add("hidden");
  filePickerModal.setAttribute("aria-hidden", "true");
}

async function renderPickerEntries() {
  const q = (pickerSearch.value || "").trim();
  const params = new URLSearchParams();
  params.set("kind", pickerState.kind || "file");
  if (q) params.set("q", q);
  if (pickerState.ext) params.set("ext", pickerState.ext);
  params.set("limit", "300");

  const res = await fetch(`/api/files?${params.toString()}`);
  const data = await res.json();
  const entries = Array.isArray(data.entries) ? data.entries : [];

  pickerList.innerHTML = "";
  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "hint";
    empty.textContent = "No matches.";
    pickerList.appendChild(empty);
    return;
  }

  entries.forEach((entry) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "picker-item";
    btn.textContent = entry;
    btn.addEventListener("click", () => {
      setFieldValue(pickerState.targetId, entry, pickerState.append);
      closePicker();
    });
    pickerList.appendChild(btn);
  });
}

async function openPicker({ targetId, kind, ext, append }) {
  pickerState = { targetId, kind: kind || "file", ext: ext || "", append: !!append };
  pickerSearch.value = "";
  filePickerModal.classList.remove("hidden");
  filePickerModal.setAttribute("aria-hidden", "false");
  await renderPickerEntries();
  pickerSearch.focus();
}

document.addEventListener("click", (ev) => {
  const btn = ev.target.closest(".picker-btn");
  if (!btn) return;
  openPicker({
    targetId: btn.dataset.pickerTarget,
    kind: btn.dataset.pickerKind || "file",
    ext: btn.dataset.pickerExt || "",
    append: btn.dataset.pickerAppend === "1",
  }).catch((e) => setStatus(`Failed to open picker: ${e}`, false));
});

pickerClose.addEventListener("click", closePicker);
filePickerModal.addEventListener("click", (e) => {
  if (e.target === filePickerModal) closePicker();
});
pickerSearch.addEventListener("input", () => {
  renderPickerEntries().catch((e) => setStatus(`Picker search failed: ${e}`, false));
});

verifyBtn.addEventListener("click", async () => {
  verifyBtn.disabled = true;
  setStatus("Running verification...", true);
  verifyLog.textContent = "Running...\n";

  const criticPayload = criticsUi.collect();
  const payload = {
    c_file_path: cFilePath.value,
    generated_header_path: generatedHeaderPath.value,
    critics: criticPayload.critics,
    critic_options: criticPayload.critic_options,
    include_dirs: splitCsv(includeDirs.value),
    defines: splitCsv(defines.value),
    generated_files: splitCsv(generatedFiles.value),
    cleanup_after_verify: !!(cleanupAfterVerify && cleanupAfterVerify.checked),
  };

  try {
    const res = await fetch("/api/verify-files", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    // Console output (summary + full payload)
    const ts = new Date().toISOString();
    if (data && data.ok && data.result) {
      const results = Array.isArray(data.result.critics_results) ? data.result.critics_results : [];
      console.groupCollapsed(`[verify ${ts}] success=${!!data.result.critics_success} score=${data.result.critics_score}`);
      results.forEach((r) => {
        const tool = r && r.tool ? r.tool : "unknown";
        const ok = !!(r && r.success);
        const score = typeof r?.score === "number" ? r.score.toFixed(3) : "n/a";
        const summary = r && r.summary ? r.summary : "";
        console.log(`[${tool}] success=${ok} score=${score} ${summary}`);
        if (r && r.raw_output) {
          console.log(`[${tool}] raw_output:\n${r.raw_output}`);
        }
      });
      console.log("Full verify response:", data);
      console.groupEnd();
    } else {
      console.groupCollapsed(`[verify ${ts}] failed`);
      console.log("Payload:", payload);
      console.log("Response:", data);
      console.groupEnd();
    }

    verifyLog.textContent = JSON.stringify(data, null, 2);

    if (data.ok) {
      const success = !!(data.result && data.result.critics_success);
      const score = data.result && typeof data.result.critics_score === "number" ? data.result.critics_score.toFixed(3) : "n/a";
      setStatus(`Verification completed. success=${success} score=${score}`, success);
      const critics = (data.result && data.result.critics_results) || [];
      renderBars(critics);
      renderOutcome(critics);
    } else {
      setStatus(data.error || "Verification failed.", false);
      renderBars([]);
      verifyLegend.textContent = "";
      verifyPie.style.background = "transparent";
    }
  } catch (e) {
    setStatus(`Request failed: ${e}`, false);
    verifyLog.textContent += `\n\n${e}`;
    renderBars([]);
    verifyLegend.textContent = "";
    verifyPie.style.background = "transparent";
  } finally {
    verifyBtn.disabled = false;
  }
});

criticsUi.load().catch((e) => setStatus(`Failed to load critics catalog: ${e}`, false));
