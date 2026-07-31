// Theme system: brand colour swatches + light/dark mode.
// Default is always light + classic (#ccffcc), regardless of OS preference.
// Once the user picks something, it is persisted.
(function () {
  const APP_KEY = "henrusian";

  const COLOR_THEMES = [
    { id: "classic", label: "Classic", hex: "#ccffcc" },
    { id: "not-green-1", label: "Not green 1", hex: "#ffcccc" },
    { id: "not-green-2", label: "Not green 2", hex: "#ccccff" },
    { id: "not-green-3", label: "Not green 3", hex: "#ffffcc" },
    { id: "not-green-4", label: "Not green 4", hex: "#ffccff" },
    { id: "not-green-5", label: "Not green 5", hex: "#ccffff" },
    { id: "really-light-green", label: "Really really light green", hex: "#ffffff" },
    { id: "hello", label: "HelloTheme", hex: "#fedc00" },
  ];

  const STORAGE_KEY_COLOR = `${APP_KEY}.colorTheme`;
  const STORAGE_KEY_MODE = `${APP_KEY}.mode`;

  // Old single-axis keys, from before the mode axis existed.
  const LEGACY_KEY = "hd_theme";
  const LEGACY_MAP = {
    classic: "classic",
    pink: "not-green-1",
    blue: "not-green-2",
    yellow: "not-green-3",
    magenta: "not-green-4",
    cyan: "not-green-5",
    white: "really-light-green",
    hello: "hello",
  };

  function hexToRgb(hex) {
    const n = parseInt(hex.replace("#", ""), 16);
    return `${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}`;
  }

  // Runs once, before the first read. Unmapped values fall back to default.
  function migrateLegacyTheme() {
    const legacy = localStorage.getItem(LEGACY_KEY);
    if (!legacy) return;
    if (!localStorage.getItem(STORAGE_KEY_COLOR) && LEGACY_MAP[legacy]) {
      localStorage.setItem(STORAGE_KEY_COLOR, LEGACY_MAP[legacy]);
    }
    localStorage.removeItem(LEGACY_KEY);
  }

  function getStoredColorTheme() {
    return localStorage.getItem(STORAGE_KEY_COLOR) || "classic";
  }

  function getStoredMode() {
    return localStorage.getItem(STORAGE_KEY_MODE) || "light";
  }

  function applyColorTheme(id) {
    const theme = COLOR_THEMES.find((t) => t.id === id) || COLOR_THEMES[0];
    document.documentElement.setAttribute("data-color-theme", theme.id);
    document.documentElement.style.setProperty("--brand", theme.hex);
    document.documentElement.style.setProperty("--brand-rgb", hexToRgb(theme.hex));
    localStorage.setItem(STORAGE_KEY_COLOR, theme.id);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme.hex);
    return theme;
  }

  function applyMode(mode) {
    const resolved = mode === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-mode", resolved);
    localStorage.setItem(STORAGE_KEY_MODE, resolved);
    return resolved;
  }

  function initTheme() {
    migrateLegacyTheme();
    applyColorTheme(getStoredColorTheme());
    applyMode(getStoredMode());
  }

  // ---- modal wiring ----

  function buildThemeModal() {
    const grid = document.getElementById("swatchGrid");
    grid.innerHTML = COLOR_THEMES.map(
      (t) => `
      <button class="swatch" data-theme-id="${t.id}" style="--swatch-color:${t.hex}" type="button" aria-label="${t.label}">
        <span class="swatch-dot"></span>
        <span class="swatch-label">${t.label}</span>
      </button>`
    ).join("");

    syncThemeModalState();

    grid.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-theme-id]");
      if (!btn) return;
      applyColorTheme(btn.dataset.themeId);
      syncThemeModalState();
    });

    document.getElementById("modeToggle").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-mode]");
      if (!btn) return;
      applyMode(btn.dataset.mode);
      syncThemeModalState();
    });
  }

  function syncThemeModalState() {
    const activeTheme = getStoredColorTheme();
    const activeMode = getStoredMode();
    document.querySelectorAll("#swatchGrid .swatch").forEach((el) => {
      const on = el.dataset.themeId === activeTheme;
      el.classList.toggle("active", on);
      el.setAttribute("aria-pressed", on);
    });
    document.querySelectorAll("#modeToggle .mode-btn").forEach((el) => {
      const on = el.dataset.mode === activeMode;
      el.classList.toggle("active", on);
      el.setAttribute("aria-pressed", on);
    });
    updateThemeButtonIcon();
  }

  function updateThemeButtonIcon() {
    const span = document.querySelector("#themeBtn [data-icon]");
    if (!span) return;
    span.setAttribute("data-icon", getStoredMode() === "dark" ? "moon" : "sun");
    window.hydrateIcons(document.getElementById("themeBtn"));
  }

  function wireModals() {
    document.querySelectorAll("[data-close-modal]").forEach((btn) => {
      btn.addEventListener("click", () => window.closeModal(btn.dataset.closeModal));
    });
    document.querySelectorAll(".modal-backdrop").forEach((backdrop) => {
      backdrop.addEventListener("click", (e) => {
        if (e.target === backdrop) window.closeModal(backdrop.id);
      });
    });
    document.getElementById("themeBtn").addEventListener("click", () => window.openModal("themeModal"));
  }

  function bootTheme() {
    initTheme();
    window.hydrateIcons();
    updateThemeButtonIcon();
    buildThemeModal();
    wireModals();
  }

  window.bootTheme = bootTheme;
})();
