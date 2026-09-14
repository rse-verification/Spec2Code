(function () {
  "use strict";

  const storageKey = "spec2code-theme";

  function current() {
    try {
      return window.localStorage.getItem(storageKey) === "light" ? "light" : "dark";
    } catch (_error) {
      return "dark";
    }
  }

  function apply(theme) {
    const normalized = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = normalized;
    try {
      window.localStorage.setItem(storageKey, normalized);
    } catch (_error) {
      // The selected theme still applies when browser storage is unavailable.
    }
    window.dispatchEvent(new CustomEvent("spec2code-theme-change", { detail: normalized }));
  }

  document.documentElement.dataset.theme = current();
  window.Spec2CodeTheme = { apply, current };
})();
