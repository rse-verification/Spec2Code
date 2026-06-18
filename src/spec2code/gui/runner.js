const templatePath = document.getElementById("templatePath");
const templateSuggestions = document.getElementById("templateSuggestions");
const modelsSelect = document.getElementById("modelsSelect");
const nPrograms = document.getElementById("nPrograms");
const temperature = document.getElementById("temperature");

const customName = document.getElementById("customName");
const customCaseStudy = document.getElementById("customCaseStudy");
const customPromptTemplate = document.getElementById("customPromptTemplate");
const customModels = document.getElementById("customModels");
const customPrograms = document.getElementById("customPrograms");
const customTemperature = document.getElementById("customTemperature");
const customOutputFolder = document.getElementById("customOutputFolder");
const customNaturalSpecPath = document.getElementById("customNaturalSpecPath");
const customInterfacePath = document.getElementById("customInterfacePath");
const customVerificationHeaderPath = document.getElementById("customVerificationHeaderPath");
const rowCustomVerificationHeader = document.getElementById("rowCustomVerificationHeader");
const customTestHarnessPath = document.getElementById("customTestHarnessPath");
const customTestHarnessSourceName = document.getElementById("customTestHarnessSourceName");
const customIncludeDirs = document.getElementById("customIncludeDirs");
const customHeadersDir = document.getElementById("customHeadersDir");
const customHeadersManifest = document.getElementById("customHeadersManifest");
const customConfig = document.getElementById("customConfig");
const customCriticsCatalog = document.getElementById("customCriticsCatalog");

const templateModeBox = document.getElementById("templateModeBox");
const customModeBox = document.getElementById("customModeBox");
const modeTemplate = document.getElementById("modeTemplate");
const modeCustom = document.getElementById("modeCustom");
const modelsLoading = document.getElementById("modelsLoading");
const refreshModelsBtn = document.getElementById("refreshModelsBtn");
const anthropicApiKey = document.getElementById("anthropicApiKey");
const openaiApiKey = document.getElementById("openaiApiKey");
const awsProfile = document.getElementById("awsProfile");
const awsRegion = document.getElementById("awsRegion");
const caseStudiesRoot = document.getElementById("caseStudiesRoot");
const inputRoot = document.getElementById("inputRoot");
const applyRuntimeEnvBtn = document.getElementById("applyRuntimeEnvBtn");
const runtimeEnvStatus = document.getElementById("runtimeEnvStatus");
const runBtn = document.getElementById("runBtn");
const statusBox = document.getElementById("status");
const reportLink = document.getElementById("reportLink");
const logBox = document.getElementById("logBox");

const filePickerModal = document.getElementById("filePickerModal");
const pickerSearch = document.getElementById("pickerSearch");
const pickerList = document.getElementById("pickerList");
const pickerClose = document.getElementById("pickerClose");

let mode = "template";
let _modelsPayload = { models: [], all_models: [], note: "" };
let pickerState = { targetId: "", kind: "file", ext: "", append: false };

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch (_e) {
    throw new Error(`Non-JSON response from ${url}: ${String(text).slice(0, 120)}`);
  }
  if (!res.ok) {
    throw new Error((data && data.error) || `${url} failed (${res.status})`);
  }
  return data;
}

const criticsUi = window.Spec2CodeCriticsUI.create({
  container: customCriticsCatalog,
  idPrefix: "runner-opt",
  onChange: (payload) => {
    refreshCriticDependentFields(payload.critics || []);
    if (mode === "custom") syncCustomPreview();
  },
});

function refreshCriticDependentFields(critics) {
  const enabled = new Set(Array.isArray(critics) ? critics : []);
  const usesFrama = enabled.has("framac-wp");

  if (rowCustomVerificationHeader) {
    rowCustomVerificationHeader.classList.toggle("disabled", !usesFrama);
    rowCustomVerificationHeader.querySelectorAll("input,button,select").forEach((el) => {
      el.disabled = !usesFrama;
    });
  }
}

function splitCsv(s) {
  return String(s || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
}

function selectedModels() {
  return Array.from(modelsSelect.selectedOptions).map((o) => o.value);
}

function setStatus(text, ok) {
  statusBox.textContent = text;
  statusBox.classList.remove("ok", "err");
  statusBox.classList.add(ok ? "ok" : "err");
}

function setMode(nextMode) {
  mode = nextMode;
  const isTemplate = mode === "template";
  templateModeBox.classList.toggle("hidden", !isTemplate);
  customModeBox.classList.toggle("hidden", isTemplate);
  modeTemplate.classList.toggle("active", isTemplate);
  modeCustom.classList.toggle("active", !isTemplate);
  if (!isTemplate) syncCustomPreview();
}

async function loadTemplates() {
  const data = await fetchJson("/api/templates");
  const templates = Array.isArray(data.templates) ? data.templates : [];
  if (templateSuggestions) templateSuggestions.innerHTML = "";
  templates.forEach((tpl) => {
    if (!templateSuggestions) return;
    const opt = document.createElement("option");
    opt.value = tpl;
    templateSuggestions.appendChild(opt);
  });
  const shutdown = templates.find((x) => x.includes("shutdown-algorithm"));
  if (templatePath && shutdown && !String(templatePath.value || "").trim()) {
    templatePath.value = shutdown;
  }
}

function formatModelLabel(name) {
  const s = String(name || "");
  if (!s.startsWith("bedrock-profile/")) return s;
  const raw = s.slice("bedrock-profile/".length);
  const marker = ":inference-profile/";
  const idx = raw.indexOf(marker);
  if (idx === -1) return s;
  const regionPart = raw.slice(0, idx);
  const profileId = raw.slice(idx + marker.length);
  const region = regionPart.split(":").pop() || "aws";
  return `bedrock-profile/${region}/${profileId}`;
}

function renderModels() {
  modelsSelect.innerHTML = "";
  const names = (_modelsPayload.all_models || _modelsPayload.models || []);
  names.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = formatModelLabel(name);
    opt.title = name;
    if (name === "test-llm-shutdown") opt.selected = true;
    modelsSelect.appendChild(opt);
  });
}

async function loadModels(force = false) {
  if (modelsLoading) modelsLoading.classList.remove("hidden");
  try {
    const q = force ? "?force=1" : "";
    const data = await fetchJson(`/api/models${q}`);
    _modelsPayload = data || _modelsPayload;
    renderModels();
  } finally {
    if (modelsLoading) modelsLoading.classList.add("hidden");
  }
}

function collectEnvOverrides() {
  const env = {};
  const put = (k, v) => {
    const s = String(v || "").trim();
    if (s) env[k] = s;
  };
  put("ANTHROPIC_API_KEY", anthropicApiKey && anthropicApiKey.value);
  put("OPENAI_API_KEY", openaiApiKey && openaiApiKey.value);
  put("AWS_PROFILE", awsProfile && awsProfile.value);
  put("AWS_REGION", awsRegion && awsRegion.value);
  put("SPEC2CODE_CASE_STUDIES_ROOT", caseStudiesRoot && caseStudiesRoot.value);
  put("SPEC2CODE_INPUT_ROOT", inputRoot && inputRoot.value);
  return env;
}

async function applyRuntimeEnvAndRefreshModels() {
  if (!applyRuntimeEnvBtn) return;
  applyRuntimeEnvBtn.disabled = true;
  if (runtimeEnvStatus) runtimeEnvStatus.textContent = "Applying credentials...";
  try {
    const data = await fetchJson("/api/session-env", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ env: collectEnvOverrides() }),
    });
    if (runtimeEnvStatus) {
      const keys = Array.isArray(data.saved_keys) ? data.saved_keys : [];
      runtimeEnvStatus.textContent = `Credentials applied. Active keys: ${keys.join(", ") || "none"}. Click 'Refresh models' to update list.`;
    }
  } catch (e) {
    if (runtimeEnvStatus) runtimeEnvStatus.textContent = `Credential setup failed: ${e}`;
  } finally {
    applyRuntimeEnvBtn.disabled = false;
  }
}

function setFieldValue(targetId, value, append) {
  const el = document.getElementById(targetId);
  if (!el) return;
  if (!append) {
    el.value = value;
    if (mode === "custom") syncCustomPreview();
    return;
  }
  const parts = splitCsv(el.value);
  if (!parts.includes(value)) parts.push(value);
  el.value = parts.join(", ");
  if (mode === "custom") syncCustomPreview();
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

async function tryNativePicker({ targetId, kind, ext, append }) {
  const res = await fetch("/api/native-pick", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind: kind || "file", ext: ext || "" }),
  });
  let data = null;
  try {
    data = await res.json();
  } catch (_e) {
    return "error";
  }
  if (!res.ok || !data || !data.ok) return "error";
  if (data.cancelled) return "cancelled";
  if (!data.path) return "error";
  setFieldValue(targetId, data.path, !!append);
  return "picked";
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const res = String(reader.result || "");
        const comma = res.indexOf(",");
        resolve(comma >= 0 ? res.slice(comma + 1) : res);
      } catch (e) {
        reject(e);
      }
    };
    reader.onerror = () => reject(reader.error || new Error("Failed to read file"));
    reader.readAsDataURL(file);
  });
}

async function tryBrowserPicker({ targetId, kind, ext, append }) {
  if ((kind || "file") !== "file") return "unsupported";

  const input = document.createElement("input");
  input.type = "file";
  const accept = String(ext || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
    .join(",");
  if (accept) input.accept = accept;

  const file = await new Promise((resolve) => {
    input.addEventListener("change", () => {
      resolve((input.files && input.files[0]) || null);
    }, { once: true });
    input.click();
  });

  if (!file) return "cancelled";
  const content_b64 = await fileToBase64(file);
  const data = await fetchJson("/api/upload-picker-file", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name || "picked_file", content_b64 }),
  });
  if (!data || !data.ok || !data.path) return "error";
  setFieldValue(targetId, data.path, !!append);
  return "picked";
}

function buildCustomConfigObject() {
  const criticPayload = criticsUi.collect();
  const selectedCritics = new Set(criticPayload.critics || []);
  let headersManifestObj = {};
  try {
    headersManifestObj = JSON.parse(customHeadersManifest.value || "{}");
  } catch (e) {
    throw new Error(`Invalid headers manifest JSON: ${e}`);
  }
  if (typeof headersManifestObj !== "object" || Array.isArray(headersManifestObj) || !headersManifestObj) {
    throw new Error("Headers manifest must be a JSON object.");
  }

  const interfacePath = (customInterfacePath.value || "").trim();
  if (!interfacePath) {
    throw new Error("Interface path is required.");
  }

  const cfg = {
    name: (customName.value || "config_custom_zero-shot").trim(),
    case_study: (customCaseStudy.value || "").trim(),
    selected_prompt_template: (customPromptTemplate.value || "zero-shot").trim(),
    llms_used: splitCsv(customModels.value),
    n_programs_generated: Number(customPrograms.value || 1),
    output_folder: (customOutputFolder.value || "").trim(),
    natural_spec_path: (customNaturalSpecPath.value || "").trim(),
    interface_path: interfacePath,
    include_dirs: splitCsv(customIncludeDirs.value),
    headers_dir: (customHeadersDir.value || "").trim(),
    headers_manifest: headersManifestObj,
    temperature: Number(customTemperature.value || 0.7),
    critics: criticPayload.critics,
    critic_options: criticPayload.critic_options,
  };

  const verificationHeaderPath = (customVerificationHeaderPath.value || "").trim();
  if (selectedCritics.has("framac-wp") && verificationHeaderPath) {
    cfg.verification_header_path = verificationHeaderPath;
  }

  const testHarnessPath = (customTestHarnessPath.value || "").trim();
  if (testHarnessPath) {
    cfg.test_harness_path = testHarnessPath;
  }

  const testHarnessSourceName = (customTestHarnessSourceName.value || "").trim();
  if (testHarnessSourceName) {
    cfg.test_harness_source_name = testHarnessSourceName;
  }

  return cfg;
}

function syncCustomPreview() {
  try {
    const cfg = [buildCustomConfigObject()];
    customConfig.value = JSON.stringify(cfg, null, 2);
    customConfig.classList.remove("err");
  } catch (e) {
    customConfig.value = `Invalid custom config: ${e}`;
    customConfig.classList.add("err");
  }
}

modeTemplate.addEventListener("click", () => setMode("template"));
modeCustom.addEventListener("click", () => setMode("custom"));

document.addEventListener("click", (ev) => {
  const btn = ev.target.closest(".picker-btn");
  if (!btn || ev.shiftKey) return;
  const req = {
    targetId: btn.dataset.pickerTarget,
    kind: btn.dataset.pickerKind || "file",
    ext: btn.dataset.pickerExt || "",
    append: btn.dataset.pickerAppend === "1",
  };
  tryNativePicker(req)
    .then((state) => {
      if (state === "picked" || state === "cancelled") return state;
      return tryBrowserPicker(req);
    })
    .then((state) => {
      if (state === "picked" || state === "cancelled") return;
      return openPicker(req);
    })
    .catch((e) => setStatus(`Picker failed: ${e}`, false));
});

document.addEventListener("click", (ev) => {
  const btn = ev.target.closest(".picker-btn");
  if (!btn || !ev.shiftKey) return;
  const req = {
    targetId: btn.dataset.pickerTarget,
    kind: btn.dataset.pickerKind || "file",
    ext: btn.dataset.pickerExt || "",
    append: btn.dataset.pickerAppend === "1",
  };
  openPicker(req).catch((e) => setStatus(`Failed to open fallback picker: ${e}`, false));
});

pickerClose.addEventListener("click", closePicker);
filePickerModal.addEventListener("click", (e) => {
  if (e.target === filePickerModal) closePicker();
});
pickerSearch.addEventListener("input", () => {
  renderPickerEntries().catch((e) => setStatus(`Picker search failed: ${e}`, false));
});

[
  customName,
  customCaseStudy,
  customPromptTemplate,
  customModels,
  customPrograms,
  customTemperature,
  customOutputFolder,
  customNaturalSpecPath,
  customInterfacePath,
  customVerificationHeaderPath,
  customTestHarnessPath,
  customTestHarnessSourceName,
  customIncludeDirs,
  customHeadersDir,
  customHeadersManifest,
].forEach((el) => {
  if (!el) return;
  el.addEventListener("input", () => {
    if (mode === "custom") syncCustomPreview();
  });
});

runBtn.addEventListener("click", async () => {
  reportLink.classList.add("hidden");
  logBox.textContent = "Running pipeline...\n";
  setStatus("Running...", true);
  runBtn.disabled = true;

  let payload;
  try {
    payload = mode === "template"
      ? {
          template: String(templatePath && templatePath.value ? templatePath.value : "").trim(),
          models: selectedModels(),
          manual_models: "",
          env_overrides: collectEnvOverrides(),
          n_programs_generated: Number(nPrograms.value || 1),
          temperature: Number(temperature.value || 0.7),
        }
      : {
          config_json: JSON.stringify([buildCustomConfigObject()]),
          env_overrides: collectEnvOverrides(),
        };
  } catch (e) {
    setStatus(`Invalid custom config: ${e}`, false);
    runBtn.disabled = false;
    return;
  }

  try {
    const startEndpoint = mode === "template" ? "/api/run-start" : "/api/run-custom-start";
    const startData = await fetchJson(startEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!startData.ok || !startData.run_id) {
      throw new Error((startData && startData.error) || "Failed to start run");
    }

    let done = false;
    while (!done) {
      const data = await fetchJson(`/api/run-status?run_id=${encodeURIComponent(startData.run_id)}`);
      if (!data.ok) throw new Error((data && data.error) || "Failed to read run status");

      const out = [];
      if (data.stdout) out.push(String(data.stdout).trim());
      if (data.stderr) out.push(String(data.stderr).trim());
      logBox.textContent = out.filter(Boolean).join("\n\n") || "(running...)";

      done = !!data.done;
      if (!done) {
        await new Promise((resolve) => setTimeout(resolve, 800));
      } else if (data.ok && Number(data.returncode ?? 1) === 0) {
        setStatus("Run completed. Open Results page when ready.", true);
        if (Array.isArray(data.warnings) && data.warnings.length) {
          statusBox.textContent += ` (${data.warnings.join(" ")})`;
        }
        reportLink.href = "/results";
        reportLink.classList.remove("hidden");
      } else {
        setStatus(data.error || `Run failed (exit=${data.returncode ?? "?"})`, false);
        if (Array.isArray(data.warnings) && data.warnings.length) {
          statusBox.textContent += ` (${data.warnings.join(" ")})`;
        }
      }
    }
  } catch (e) {
    setStatus(`Request failed: ${e}`, false);
    logBox.textContent += `\n\n${e}`;
  } finally {
    runBtn.disabled = false;
  }
});

loadTemplates().catch((e) => setStatus(`Template load failed: ${e}`, false));
loadModels().catch((e) => setStatus(`Model load failed: ${e}`, false));
criticsUi
  .load()
  .then(() => syncCustomPreview())
  .catch((e) => setStatus(`Critics load failed: ${e}`, false));

if (applyRuntimeEnvBtn) {
  applyRuntimeEnvBtn.addEventListener("click", () => {
    applyRuntimeEnvAndRefreshModels().catch((e) => setStatus(`Model refresh failed: ${e}`, false));
  });
}
if (refreshModelsBtn) {
  refreshModelsBtn.addEventListener("click", () => {
    loadModels(true).catch((e) => setStatus(`Model load failed: ${e}`, false));
  });
}
