"use strict";

const form = document.getElementById("settingsForm");
const loading = document.getElementById("settingsLoading");
const content = document.getElementById("settingsContent");
const appearanceSection = document.getElementById("appearanceSection");
const modelsSection = document.getElementById("modelsSection");
const availableModels = document.getElementById("availableModels");
const refreshAvailableModelsBtn = document.getElementById("refreshAvailableModelsBtn");
const settingsStatus = document.getElementById("settingsStatus");
const saveTimers = new Map();
const saveQueues = new Map();

const providers = {
  openai: {
    statusId: "openaiApiKeyStatus",
    fields: {},
    secrets: { api_key: ["openaiApiKey", "openaiClearApiKey"] },
  },
  anthropic: {
    statusId: "anthropicApiKeyStatus",
    fields: {},
    secrets: { api_key: ["anthropicApiKey", "anthropicClearApiKey"] },
  },
  aws_bedrock: {
    statusId: "awsBedrockSecretAccessKeyStatus",
    fields: { profile: "awsBedrockProfile", region: "awsBedrockRegion" },
    secrets: {
      access_key_id: ["awsBedrockAccessKeyId", "awsBedrockClearAccessKeyId"],
      secret_access_key: ["awsBedrockSecretAccessKey", "awsBedrockClearSecretAccessKey"],
      session_token: ["awsBedrockSessionToken", "awsBedrockClearSessionToken"],
    },
  },
  ollama: {
    statusId: "ollamaApiKeyStatus",
    fields: { base_url: "ollamaBaseUrl" },
    secrets: { api_key: ["ollamaApiKey", "ollamaClearApiKey"] },
  },
  vllm: {
    statusId: "vllmApiKeyStatus",
    fields: { base_url: "vllmBaseUrl" },
    secrets: { api_key: ["vllmApiKey", "vllmClearApiKey"] },
  },
};

function element(id) {
  return document.getElementById(id);
}

function setStatus(message, kind = "") {
  settingsStatus.textContent = message;
  settingsStatus.className = `status autosave-status ${kind}`.trim();
}

async function responseJson(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || data.message || `Request failed (${response.status})`);
  }
  return data;
}

function providerSettings(source, providerId) {
  const collection = source.providers || {};
  return collection[providerId] || {};
}

function isSecretConfigured(config, secretName) {
  const statuses = config.configured_secrets || {};
  return statuses[secretName] === true;
}

function updateProviderStatus(providerId, config) {
  const definition = providers[providerId];
  const primarySecret = Object.keys(definition.secrets)[0];
  const configured = typeof config.configured === "boolean" ? config.configured : isSecretConfigured(config, primarySecret);
  const badge = element(definition.statusId);
  badge.textContent = configured ? "Configured" : "Not configured";
  badge.classList.toggle("configured", configured);
}

function resetClearButton(button) {
  const target = button.dataset.clearTarget;
  let label = "Clear key";
  if (target.includes("Token")) label = "Clear token";
  if (target.includes("Secret")) label = "Clear secret";
  if (target.includes("AccessKeyId")) label = "Clear ID";
  button.textContent = label;
  button.setAttribute("aria-pressed", "false");
  element(button.dataset.clearField).checked = false;
  element(target).disabled = false;
}

function populateSettings(payload) {
  const settings = payload.settings || payload.data || payload;
  Object.entries(providers).forEach(([providerId, definition]) => {
    const config = providerSettings(settings, providerId);
    Object.entries(definition.fields).forEach(([key, id]) => {
      element(id).value = config[key] ?? "";
    });
    Object.values(definition.secrets).forEach(([secretId]) => {
      element(secretId).value = "";
    });
    updateProviderStatus(providerId, config);
  });
  document.querySelectorAll(".secret-clear").forEach(resetClearButton);
}

function renderAvailableModels(payload) {
  const groups = Array.isArray(payload.providers) ? payload.providers : [];
  availableModels.innerHTML = "";
  if (!groups.length) {
    availableModels.textContent = "No models are currently configured.";
    return;
  }

  groups.forEach((group) => {
    const details = document.createElement("details");
    details.className = "models-group";
    details.open = true;
    const summary = document.createElement("summary");
    summary.textContent = group.label || group.id || "Models";
    details.appendChild(summary);
    const list = document.createElement("ul");
    list.className = "models-list";
    (group.models || []).forEach((model) => {
      const item = document.createElement("li");
      const ready = model.ready !== false;
      item.className = `model-entry${ready ? "" : " unavailable"}`;
      const name = document.createElement("span");
      name.className = "model-name";
      name.textContent = model.name || "Unknown model";
      const state = document.createElement("span");
      state.className = "model-state";
      state.textContent = ready ? "Ready" : (model.reason || "Configure provider");
      item.append(name, state);
      list.appendChild(item);
    });
    details.appendChild(list);
    availableModels.appendChild(details);
  });
}

async function loadAvailableModels(force = false) {
  refreshAvailableModelsBtn.disabled = true;
  availableModels.textContent = "Loading models...";
  try {
    const suffix = force ? "?force=1" : "";
    const data = await responseJson(await fetch(`/api/models${suffix}`, { headers: { Accept: "application/json" } }));
    renderAvailableModels(data);
  } catch (error) {
    availableModels.textContent = `Unable to load models: ${error.message}`;
  } finally {
    refreshAvailableModelsBtn.disabled = false;
  }
}

function buildProviderPayload(providerId) {
  const definition = providers[providerId];
  const payload = {};
  Object.entries(definition.fields).forEach(([key, id]) => {
    payload[key] = element(id).value.trim();
  });
  Object.entries(definition.secrets).forEach(([key, [secretId, clearId]]) => {
    const value = element(secretId).value;
    if (value) payload[key] = value;
    if (element(clearId).checked) payload[`clear_${key}`] = true;
  });
  return payload;
}

function saveProvider(providerId) {
  const timer = saveTimers.get(providerId);
  if (timer) window.clearTimeout(timer);
  saveTimers.delete(providerId);
  const submitted = buildProviderPayload(providerId);
  const previous = saveQueues.get(providerId) || Promise.resolve(true);
  const next = previous.then(
    () => performProviderSave(providerId, submitted),
    () => performProviderSave(providerId, submitted),
  );
  saveQueues.set(providerId, next);
  return next;
}

async function performProviderSave(providerId, submitted) {
  setStatus("Saving...");
  try {
    const data = await responseJson(await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ providers: { [providerId]: submitted } }),
    }));
    const config = providerSettings(data.settings || {}, providerId);
    updateProviderStatus(providerId, config);
    Object.entries(providers[providerId].secrets).forEach(([key, [secretId, clearId]]) => {
      if (submitted[key] || submitted[`clear_${key}`]) element(secretId).value = "";
      if (submitted[`clear_${key}`]) resetClearButton(document.querySelector(`[data-clear-field="${clearId}"]`));
    });
    setStatus("Saved", "ok");
    loadAvailableModels(true);
    return true;
  } catch (error) {
    Object.entries(providers[providerId].secrets).forEach(([key, [, clearId]]) => {
      if (submitted[`clear_${key}`]) resetClearButton(document.querySelector(`[data-clear-field="${clearId}"]`));
    });
    setStatus(error.message, "err");
    return false;
  }
}

function scheduleSave(providerId) {
  const current = saveTimers.get(providerId);
  if (current) window.clearTimeout(current);
  setStatus("Pending changes...");
  saveTimers.set(providerId, window.setTimeout(() => saveProvider(providerId), 600));
}

async function loadSettings() {
  try {
    const data = await responseJson(await fetch("/api/settings", { headers: { Accept: "application/json" } }));
    populateSettings(data);
    loading.classList.add("hidden");
    content.classList.remove("hidden");
    appearanceSection.classList.remove("hidden");
    modelsSection.classList.remove("hidden");
    await loadAvailableModels();
  } catch (error) {
    loading.textContent = `Unable to load settings: ${error.message}`;
    loading.classList.add("status", "err");
  }
}

Object.entries(providers).forEach(([providerId, definition]) => {
  Object.values(definition.fields).forEach((id) => {
    element(id).addEventListener("input", () => scheduleSave(providerId));
  });
  Object.values(definition.secrets).forEach(([secretId]) => {
    element(secretId).addEventListener("change", () => saveProvider(providerId));
  });
});

document.querySelectorAll(".secret-clear").forEach((button) => {
  button.addEventListener("click", () => {
    const checkbox = element(button.dataset.clearField);
    checkbox.checked = true;
    button.setAttribute("aria-pressed", "true");
    button.textContent = "Clearing...";
    const secretInput = element(button.dataset.clearTarget);
    secretInput.value = "";
    secretInput.disabled = true;
    saveProvider(button.closest("[data-provider]").dataset.provider);
  });
});

document.querySelectorAll("[data-test-provider]").forEach((button) => {
  button.addEventListener("click", async () => {
    const providerId = button.dataset.testProvider;
    const statusPrefix = providerId === "aws_bedrock" ? "awsBedrock" : providerId;
    const result = element(`${statusPrefix}TestStatus`);
    if (!(await saveProvider(providerId))) return;
    button.disabled = true;
    result.textContent = "Testing...";
    result.className = "test-result";
    try {
      const data = await responseJson(await fetch("/api/settings/test", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ provider: providerId }),
      }));
      result.textContent = data.message || "Connection successful";
      result.className = "test-result ok";
    } catch (error) {
      result.textContent = error.message;
      result.className = "test-result err";
    } finally {
      button.disabled = false;
    }
  });
});

document.querySelectorAll("[data-theme-value]").forEach((button) => {
  const refresh = () => button.classList.toggle("active", button.dataset.themeValue === window.Spec2CodeTheme.current());
  refresh();
  button.addEventListener("click", () => {
    window.Spec2CodeTheme.apply(button.dataset.themeValue);
    document.querySelectorAll("[data-theme-value]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
  });
});

form.addEventListener("submit", (event) => event.preventDefault());
refreshAvailableModelsBtn.addEventListener("click", () => loadAvailableModels(true));
loadSettings();
