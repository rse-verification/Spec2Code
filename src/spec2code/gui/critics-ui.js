(function () {
  function optionInputId(prefix, criticName, key) {
    return `${prefix}-${criticName}-${key}`.replace(/[^a-zA-Z0-9_-]/g, "_");
  }

  function pickerExtForOptionKey(key) {
    const k = String(key || "").toLowerCase();
    if (k.includes("misra") && k.includes("rules")) return ".txt";
    if (k.includes("script")) return ".sh";
    if (k.includes("interface")) return ".is";
    if (k.includes("formal")) return ".h";
    return "";
  }

  function parseByType(def, rawValue, checkedValue) {
    const t = def.type;
    if (t === "bool") return !!checkedValue;
    if (t === "int") {
      const n = Number(rawValue);
      if (!Number.isFinite(n)) return null;
      return Math.trunc(n);
    }
    if (t === "float") {
      const n = Number(rawValue);
      if (!Number.isFinite(n)) return null;
      return n;
    }
    return String(rawValue || "").trim();
  }

  async function fetchCatalog() {
    const res = await fetch("/api/critics");
    const text = await res.text();
    let data = null;
    try {
      data = JSON.parse(text);
    } catch (e) {
      throw new Error(`Invalid critics catalog response (${res.status}): ${text.slice(0, 120)}`);
    }
    if (!res.ok) {
      throw new Error(data && data.error ? data.error : `Failed to load critics catalog (${res.status})`);
    }
    return Array.isArray(data.critics) ? data.critics : [];
  }

  function create(opts) {
    const container = opts.container;
    const idPrefix = opts.idPrefix || "opt";
    let criticDefs = [];
    const onChange = typeof opts.onChange === "function" ? opts.onChange : null;
    let api = null;

    function emitChange() {
      if (!onChange || !api) return;
      try {
        onChange(api.collect());
      } catch (_err) {
        // noop
      }
    }

    function render() {
      container.innerHTML = "";
      criticDefs.forEach((critic) => {
        const item = document.createElement("div");
        item.className = "critic-item";

        const head = document.createElement("label");
        head.className = "critic-head";

        const chk = document.createElement("input");
        chk.type = "checkbox";
        chk.dataset.criticName = critic.name;
        chk.checked = !!critic.default_enabled;

        const title = document.createElement("span");
        title.textContent = critic.label || critic.name;

        head.appendChild(chk);
        head.appendChild(title);
        item.appendChild(head);

        const optsWrap = document.createElement("div");
        optsWrap.className = "critic-options";

        (critic.options || []).forEach((optDef) => {
          const row = document.createElement("div");
          row.className = "critic-options-row";

          const lab = document.createElement("label");
          const inputId = optionInputId(idPrefix, critic.name, optDef.key);
          lab.htmlFor = inputId;
          lab.textContent = optDef.label || optDef.key;

          let inp;
          if (optDef.type === "bool") {
            inp = document.createElement("input");
            inp.type = "checkbox";
            inp.checked = !!optDef.default;
          } else {
            inp = document.createElement("input");
            inp.type = optDef.type === "int" || optDef.type === "float" ? "number" : "text";
            if (optDef.type === "int") inp.step = "1";
            if (optDef.type === "float") inp.step = "any";
            inp.value = optDef.default === undefined || optDef.default === null ? "" : String(optDef.default);
            inp.autocomplete = "off";
            inp.autocorrect = "off";
            inp.autocapitalize = "off";
            inp.spellcheck = false;
          }
          inp.id = inputId;
          inp.dataset.optType = optDef.type || "string";
          inp.dataset.optKey = optDef.key;

          row.appendChild(lab);
          if (optDef.type === "path") {
            const wrap = document.createElement("div");
            wrap.className = "input-picker-row";
            wrap.appendChild(inp);

            const pickBtn = document.createElement("button");
            pickBtn.type = "button";
            pickBtn.className = "picker-btn";
            pickBtn.textContent = "Pick";
            pickBtn.dataset.pickerTarget = inputId;
            pickBtn.dataset.pickerKind = "file";
            pickBtn.dataset.pickerExt = optDef.ext || pickerExtForOptionKey(optDef.key);
            wrap.appendChild(pickBtn);

            row.appendChild(wrap);
          } else {
            row.appendChild(inp);
          }

          optsWrap.appendChild(row);
        });

        item.appendChild(optsWrap);

        const syncState = () => {
          item.classList.toggle("disabled", !chk.checked);
          optsWrap.querySelectorAll("input,select").forEach((el) => {
            el.disabled = !chk.checked;
          });
          emitChange();
        };
        chk.addEventListener("change", syncState);
        syncState();

        container.appendChild(item);
      });
    }

    api = {
      async load() {
        criticDefs = await fetchCatalog();
        render();
        emitChange();
      },
      collect() {
        const critics = [];
        const critic_options = {};

        criticDefs.forEach((critic) => {
          const chk = container.querySelector(`input[data-critic-name="${critic.name}"]`);
          if (!chk || !chk.checked) return;

          critics.push(critic.name);
          const opts = {};
          (critic.options || []).forEach((optDef) => {
            const input = document.getElementById(optionInputId(idPrefix, critic.name, optDef.key));
            if (!input) return;

            let parsed = null;
            if (optDef.type === "bool") {
              parsed = parseByType(optDef, null, input.checked);
            } else {
              const raw = input.value;
              if (!String(raw || "").trim()) return;
              parsed = parseByType(optDef, raw, false);
              if (parsed === null) return;
            }

            opts[optDef.key] = parsed;
          });
          if (Object.keys(opts).length > 0) critic_options[critic.name] = opts;
        });

        return { critics, critic_options };
      },
    };

    return api;
  }

  window.Spec2CodeCriticsUI = { create };
})();
