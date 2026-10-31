const templatePath = document.getElementById("templatePath");
const templateSuggestions = document.getElementById("templateSuggestions");
const modelsSelect = document.getElementById("modelsSelect");
const nPrograms = document.getElementById("nPrograms");
const temperature = document.getElementById("temperature");
const templateMaxIterations = document.getElementById("templateMaxIterations");
const projectSelect = document.getElementById("projectSelect");
const projectSummary = document.getElementById("projectSummary");
const refreshProjectsBtn = document.getElementById("refreshProjectsBtn");
const importProjectZipBtn = document.getElementById("importProjectZipBtn");
const importProjectFolderBtn = document.getElementById("importProjectFolderBtn");
const projectZipInput = document.getElementById("projectZipInput");
const projectFolderInput = document.getElementById("projectFolderInput");
const projectFilesInput = document.getElementById("projectFilesInput");
const projectImportReview = document.getElementById("projectImportReview");
let pendingProjectFiles = [];
const projectRunName = document.getElementById("projectRunName");
const projectPrograms = document.getElementById("projectPrograms");
const projectTemperature = document.getElementById("projectTemperature");
const projectMaxIterations = document.getElementById("projectMaxIterations");
const projectOutputFolder = document.getElementById("projectOutputFolder");
const projectNaturalSpecPath = document.getElementById("projectNaturalSpecPath");
const projectInterfacePath = document.getElementById("projectInterfacePath");
const projectVerificationHeaderPath = document.getElementById("projectVerificationHeaderPath");
const projectIncludeDirs = document.getElementById("projectIncludeDirs");
const projectHeadersDir = document.getElementById("projectHeadersDir");
const projectHeadersManifest = document.getElementById("projectHeadersManifest");
const projectCriticsCatalog = document.getElementById("projectCriticsCatalog");

const customName = document.getElementById("customName");
const customCaseStudy = document.getElementById("customCaseStudy");
const customPromptTemplate = document.getElementById("customPromptTemplate");
const customPrograms = document.getElementById("customPrograms");
const customTemperature = document.getElementById("customTemperature");
const customMaxIterations = document.getElementById("customMaxIterations");
const customOutputFolder = document.getElementById("customOutputFolder");
const customNaturalSpecPath = document.getElementById("customNaturalSpecPath");
const customInterfacePath = document.getElementById("customInterfacePath");
const customVerificationHeaderPath = document.getElementById("customVerificationHeaderPath");
const rowCustomVerificationHeader = document.getElementById("rowCustomVerificationHeader");
const customIncludeDirs = document.getElementById("customIncludeDirs");
const customHeadersDir = document.getElementById("customHeadersDir");
const customHeadersManifest = document.getElementById("customHeadersManifest");
const customConfig = document.getElementById("customConfig");
const customCriticsCatalog = document.getElementById("customCriticsCatalog");

const templateModeBox = document.getElementById("templateModeBox");
const customModeBox = document.getElementById("customModeBox");
const projectModeBox = document.getElementById("projectModeBox");
const modeProject = document.getElementById("modeProject");
const modeTemplate = document.getElementById("modeTemplate");
const modeCustom = document.getElementById("modeCustom");
const modelsLoading = document.getElementById("modelsLoading");
const refreshModelsBtn = document.getElementById("refreshModelsBtn");
const modelsNote = document.getElementById("modelsNote");
const modelsDiagnostics = document.getElementById("modelsDiagnostics");
const runBtn = document.getElementById("runBtn");
const statusBox = document.getElementById("status");
const reportLink = document.getElementById("reportLink");
const logBox = document.getElementById("logBox");

const filePickerModal = document.getElementById("filePickerModal");
const pickerSearch = document.getElementById("pickerSearch");
const pickerList = document.getElementById("pickerList");
const pickerClose = document.getElementById("pickerClose");

let mode = "project";
let _modelsPayload = { models: [], all_models: [], note: "" };
let _projects = [];
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

const projectCriticsUi = window.Spec2CodeCriticsUI.create({
  container: projectCriticsCatalog,
  idPrefix: "project-opt",
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
  return Array.from(modelsSelect.querySelectorAll("input:checked:not(:disabled)")).map((o) => o.value);
}

function setStatus(text, ok) {
  statusBox.textContent = text;
  statusBox.classList.remove("ok", "err");
  statusBox.classList.add(ok ? "ok" : "err");
}

function setMode(nextMode) {
  mode = nextMode;
  const isTemplate = mode === "template";
  const isProject = mode === "project";
  templateModeBox.classList.toggle("hidden", !isTemplate);
  projectModeBox.classList.toggle("hidden", !isProject);
  customModeBox.classList.toggle("hidden", mode !== "custom");
  modeProject.classList.toggle("active", isProject);
  modeTemplate.classList.toggle("active", isTemplate);
  modeCustom.classList.toggle("active", mode === "custom");
  if (mode === "custom") syncCustomPreview();
}

function renderProjectSummary() {
  const project = _projects.find((item) => item.id === projectSelect.value);
  if (!project) {
    projectSummary.textContent = "No managed projects yet. Import a project ZIP to begin.";
    return;
  }
  if (!project.ready) {
    projectSummary.textContent = project.error || `Incomplete project: missing ${(project.missing || []).join(", ")}.`;
    return;
  }
  const headerCount = Object.keys(project.prompt_headers || {}).length;
  projectSummary.replaceChildren();
  [["Requirements", project.spec], ["Interface", project.interface], ["Headers", `${project.headers} (${headerCount} prompt headers)`], ["Verification", project.verification_header || "Not selected"]].forEach(([role, path]) => {
    const row = document.createElement("div");
    row.textContent = `${role}: ${path}`;
    projectSummary.appendChild(row);
  });
}

async function loadProjects(selectId = "") {
  const data = await fetchJson("/api/projects", { cache: "no-store" });
  _projects = Array.isArray(data.projects) ? data.projects : [];
  const previous = selectId || projectSelect.value;
  projectSelect.innerHTML = "";
  _projects.forEach((project) => {
    const option = document.createElement("option");
    option.value = project.id;
    option.textContent = `${project.id}${project.ready ? "" : " (incomplete)"}`;
    option.disabled = !project.ready;
    option.selected = project.id === previous;
    projectSelect.appendChild(option);
  });
  if (!projectSelect.value) {
    const firstReady = _projects.find((project) => project.ready);
    if (firstReady) projectSelect.value = firstReady.id;
  }
  renderProjectSummary();
}

function buildProjectConfigObject() {
  const project = projectSelect.value;
  if (!project) throw new Error("Import or select a ready project first.");
  const criticPayload = projectCriticsUi.collect();
  const programs = Number(projectPrograms.value || 1);
  const repairIterations = Number(projectMaxIterations.value || 0);
  if (!Number.isInteger(programs) || programs < 1) throw new Error("Programs per model must be an integer of at least 1.");
  if (!Number.isInteger(repairIterations) || repairIterations < 0) throw new Error("Repair iterations must be a non-negative integer.");
  const cfg = {
    project,
    name: (projectRunName.value || `${project}-run`).trim(),
    selected_prompt_template: "zero-shot",
    llms_used: selectedModels(),
    n_programs_generated: programs,
    max_generation_iterations: repairIterations + 1,
    temperature: Number(projectTemperature.value || 0.7),
    critics: criticPayload.critics,
    critic_options: criticPayload.critic_options,
  };
  const overrides = [
    ["output_folder", projectOutputFolder.value],
    ["natural_spec_path", projectNaturalSpecPath.value],
    ["interface_path", projectInterfacePath.value],
    ["verification_header_path", projectVerificationHeaderPath.value],
    ["headers_dir", projectHeadersDir.value],
  ];
  overrides.forEach(([key, value]) => {
    if (String(value || "").trim()) cfg[key] = String(value).trim();
  });
  if (projectIncludeDirs.value.trim()) cfg.include_dirs = splitCsv(projectIncludeDirs.value);
  if (projectHeadersManifest.value.trim()) {
    const manifest = JSON.parse(projectHeadersManifest.value);
    if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
      throw new Error("Prompt headers manifest must be a JSON object.");
    }
    cfg.headers_manifest = manifest;
  }
  return cfg;
}

async function importProject(payload) {
  setStatus("Importing project...", true);
  const data = await fetchJson("/api/projects/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await loadProjects(data.project.id);
  setStatus(`Imported project '${data.project.id}'.`, true);
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
  const region = regionPart.split(":")[3] || "aws";
  return `bedrock-profile/${region}/${profileId}`;
}

function renderModels() {
  const selected = new Set(selectedModels());
  modelsSelect.innerHTML = "";
  const groups = Array.isArray(_modelsPayload.providers) ? _modelsPayload.providers : [];
  const appendModel = (parent, model) => {
    const name = typeof model === "string" ? model : model.name;
    if (!name) return;
    const row = document.createElement("label");
    row.className = "model-choice";
    const opt = document.createElement("input");
    opt.type = "checkbox";
    opt.value = name;
    opt.disabled = typeof model === "object" && model.ready === false;
    const description = document.createElement("span");
    description.textContent = formatModelLabel(name);
    if (model.reason) {
      const reason = document.createElement("small");
      reason.textContent = model.reason;
      description.appendChild(reason);
    }
    row.title = name;
    row.dataset.model = name.toLowerCase();
    opt.checked = !opt.disabled && selected.has(name);
    opt.addEventListener("change", updateModelSelection);
    row.append(opt, description);
    parent.appendChild(row);
  };

  if (groups.length) {
    groups.forEach((group) => {
      const optgroup = document.createElement("fieldset");
      const legend = document.createElement("legend");
      legend.textContent = group.label || group.id || "Models";
      optgroup.appendChild(legend);
      (group.models || []).forEach((model) => appendModel(optgroup, model));
      modelsSelect.appendChild(optgroup);
    });
  } else {
    (_modelsPayload.all_models || _modelsPayload.models || []).forEach((name) => appendModel(modelsSelect, name));
  }

  if (modelsNote) {
    const note = String(_modelsPayload.note || "").trim();
    modelsNote.textContent = note;
    if (modelsDiagnostics) modelsDiagnostics.classList.toggle("hidden", !note);
  }
  updateModelSelection();
  filterModels();
}

function updateModelSelection() {
  const selected = selectedModels();
  const available = modelsSelect.querySelectorAll("input:not(:disabled)").length;
  document.getElementById("modelSelectionSummary").textContent = selected.length
    ? `${selected.length} selected: ${selected.map(formatModelLabel).join(", ")}`
    : available ? `${available} selectable models. Select at least one; selections are kept while filtering.` : "No text-generation models available. Check Provider settings and discovery details, then refresh.";
  if (mode === "custom") syncCustomPreview();
}

function filterModels() {
  const query = document.getElementById("modelSearch").value.trim().toLowerCase();
  modelsSelect.querySelectorAll(".model-choice").forEach((row) => { row.hidden = !row.dataset.model.includes(query); });
  modelsSelect.querySelectorAll("fieldset").forEach((group) => { group.hidden = !group.querySelector(".model-choice:not([hidden])"); });
}
document.getElementById("modelSearch").addEventListener("input", filterModels);

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
  document.getElementById("pickerUpload").hidden = pickerState.kind !== "file";
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
    input.addEventListener("cancel", () => resolve(null), { once: true });
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
    llms_used: selectedModels(),
    n_programs_generated: Number(customPrograms.value || 1),
    max_generation_iterations: Number(customMaxIterations.value || 0) + 1,
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

modeProject.addEventListener("click", () => setMode("project"));
modeTemplate.addEventListener("click", () => setMode("template"));
modeCustom.addEventListener("click", () => setMode("custom"));
projectSelect.addEventListener("change", renderProjectSummary);
refreshProjectsBtn.addEventListener("click", () => {
  loadProjects().catch((e) => setStatus(`Project refresh failed: ${e}`, false));
});
importProjectZipBtn.addEventListener("click", () => projectZipInput.click());
projectZipInput.addEventListener("change", async () => {
  const file = projectZipInput.files && projectZipInput.files[0];
  if (!file) return;
  try {
    await importProject({ filename: file.name, content_b64: await fileToBase64(file) });
  } catch (e) {
    setStatus(`Project import failed: ${e}`, false);
  } finally {
    projectZipInput.value = "";
  }
});
importProjectFolderBtn.addEventListener("click", () => projectFolderInput.click());
document.getElementById("importProjectFilesBtn").addEventListener("click", () => projectFilesInput.click());

async function reviewProjectFiles(input) {
  const files = Array.from(input.files || []);
  if (!files.length) return;
  if (files.length > 5000 || files.reduce((sum, file) => sum + file.size, 0) > 50 * 1024 * 1024) {
    throw new Error("Choose at most 5000 files with a combined size below 50 MB.");
  }
  pendingProjectFiles = files.map((file) => ({ file, path: file.webkitRelativePath ? file.webkitRelativePath.split("/").slice(1).join("/") : file.name }));
  const paths = pendingProjectFiles.map((item) => item.path).sort();
  const manifestFile = pendingProjectFiles.find((item) => item.path === "spec2code.project.json");
  const manifest = manifestFile ? JSON.parse(await manifestFile.file.text()) : {};
  const setOptions = (id, choices, selected, placeholder) => {
    const select = document.getElementById(id);
    select.replaceChildren(new Option(placeholder, ""), ...choices.map((path) => new Option(path === "." ? "Project root" : path, path)));
    select.value = choices.includes(selected) ? selected : "";
  };
  const specs = paths.filter((path) => /\.(txt|md|rst)$/i.test(path));
  const interfaces = paths.filter((path) => /\.is$/i.test(path));
  const headers = paths.filter((path) => /\.h$/i.test(path));
  const directories = new Set(["."]);
  paths.forEach((path) => { const parts = path.split("/"); parts.pop(); while (parts.length) { directories.add(parts.join("/")); parts.pop(); } });
  const spec = manifest.spec || specs.find((path) => /(^|\/)(nlspec|spec|requirements)[^/]*\.(txt|md|rst)$/i.test(path)) || (specs.length === 1 ? specs[0] : "");
  setOptions("importSpec", paths.filter((path) => path !== "spec2code.project.json"), spec, "Choose the requirements file");
  setOptions("importInterface", interfaces, manifest.interface || (interfaces.length === 1 ? interfaces[0] : ""), "Choose the interface");
  setOptions("importHeaders", [...directories].sort(), manifest.headers || (directories.has("headers") ? "headers" : "."), "Choose the headers directory");
  const verification = headers.filter((path) => /_ver\.h$/i.test(path));
  setOptions("importVerification", headers, manifest.verification_header || (verification.length === 1 ? verification[0] : ""), "None");
  const folderName = files[0].webkitRelativePath?.split("/")[0] || (interfaces[0] || "project").split("/").pop().replace(/\.is$/i, "");
  document.getElementById("importProjectName").value = folderName.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^[^A-Za-z0-9]+/, "") || "project";
  document.getElementById("projectImportSummary").textContent = `${files.length} files · ${(files.reduce((sum, file) => sum + file.size, 0) / 1024).toFixed(1)} KiB. Original filenames and folder structure will be preserved.`;
  projectImportReview.classList.remove("hidden");
  input.value = "";
}

[projectFolderInput, projectFilesInput].forEach((input) => input.addEventListener("change", () => reviewProjectFiles(input).catch((error) => setStatus(error.message, false))));
document.getElementById("cancelProjectImport").addEventListener("click", () => { pendingProjectFiles = []; projectImportReview.classList.add("hidden"); });
document.getElementById("confirmProjectImport").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const selections = { spec: document.getElementById("importSpec").value, interface: document.getElementById("importInterface").value, headers: document.getElementById("importHeaders").value, verification_header: document.getElementById("importVerification").value };
    if (!selections.spec || !selections.interface || !selections.headers) throw new Error("Choose requirements, an interface and a headers directory before importing.");
    const files = [];
    for (const item of pendingProjectFiles) files.push({ path: item.path, content_b64: await fileToBase64(item.file) });
    await importProject({ project_name: document.getElementById("importProjectName").value.trim(), files, selections });
    pendingProjectFiles = [];
    projectImportReview.classList.add("hidden");
  } catch (e) {
    setStatus(`Project import failed: ${e.message}`, false);
  } finally {
    button.disabled = false;
  }
});

document.addEventListener("click", (ev) => {
  const btn = ev.target.closest(".picker-btn");
  if (!btn) return;
  const req = {
    targetId: btn.dataset.pickerTarget,
    kind: btn.dataset.pickerKind || "file",
    ext: btn.dataset.pickerExt || "",
    append: btn.dataset.pickerAppend === "1",
  };
  openPicker(req).catch((e) => setStatus(`Picker failed: ${e}`, false));
});

[["pickerUpload", tryBrowserPicker], ["pickerNative", tryNativePicker]].forEach(([id, pick]) => document.getElementById(id).addEventListener("click", () => {
  pick(pickerState).then((state) => {
    if (state === "picked") closePicker();
    if (state === "error") setStatus("Picker unavailable. Choose a server path or upload a file.", false);
  }).catch((error) => setStatus(error.message, false));
}));
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closePicker(); });

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
  customPrograms,
  customTemperature,
  customMaxIterations,
  customOutputFolder,
  customNaturalSpecPath,
  customInterfacePath,
  customVerificationHeaderPath,
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
    if (!selectedModels().length) throw new Error("Select at least one available model.");
    payload = mode === "template"
      ? {
          template: String(templatePath && templatePath.value ? templatePath.value : "").trim(),
          models: selectedModels(),
          manual_models: "",
          n_programs_generated: Number(nPrograms.value || 1),
          temperature: Number(temperature.value || 0.7),
          repair_iterations: Number(templateMaxIterations.value || 0),
        }
      : { config_json: JSON.stringify([mode === "project" ? buildProjectConfigObject() : buildCustomConfigObject()]) };
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
      const data = await fetchJson(`/api/run-status?run_id=${encodeURIComponent(startData.run_id)}`, { cache: "no-store" });
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
loadProjects().catch((e) => setStatus(`Project load failed: ${e}`, false));
loadModels().catch((e) => setStatus(`Model load failed: ${e}`, false));
criticsUi
  .load()
  .then(() => syncCustomPreview())
  .catch((e) => setStatus(`Critics load failed: ${e}`, false));
projectCriticsUi.load().catch((e) => setStatus(`Project critics load failed: ${e}`, false));

if (refreshModelsBtn) {
  refreshModelsBtn.addEventListener("click", () => {
    loadModels(true).catch((e) => setStatus(`Model load failed: ${e}`, false));
  });
}
