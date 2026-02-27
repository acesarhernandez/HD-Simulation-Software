(function () {
  const THEME_STORAGE_KEY = "helpdesk_sim_theme_mode";
  const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

  function getMode() {
    try {
      const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (stored === "light" || stored === "dark" || stored === "auto") {
        return stored;
      }
    } catch {
      // Ignore localStorage access errors.
    }
    return "auto";
  }

  function setMode(mode, persist = false) {
    const normalized = mode === "light" || mode === "dark" ? mode : "auto";
    const resolved = normalized === "auto" ? (mediaQuery.matches ? "dark" : "light") : normalized;
    document.documentElement.setAttribute("data-theme", resolved);

    if (persist) {
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, normalized);
      } catch {
        // Ignore localStorage write errors.
      }
    }

    return normalized;
  }

  const api = { getMode, setMode };
  window.HelpdeskThemeSync = api;

  // Apply immediately so page theme stays consistent across routes.
  setMode(getMode(), false);

  const refreshIfAuto = () => {
    if (getMode() === "auto") {
      setMode("auto", false);
    }
  };

  if (typeof mediaQuery.addEventListener === "function") {
    mediaQuery.addEventListener("change", refreshIfAuto);
  } else if (typeof mediaQuery.addListener === "function") {
    mediaQuery.addListener(refreshIfAuto);
  }
})();
