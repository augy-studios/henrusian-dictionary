// Shared UI helpers. Plain script, published on window since the project
// does not use ES modules.
(function () {
  // Safe to call repeatedly; re-renders when data-icon changes.
  function hydrateIcons(root) {
    (root || document).querySelectorAll("[data-icon]").forEach(function (el) {
      var name = el.dataset.icon;
      if (el.dataset.iconRendered === name) return;
      el.innerHTML = window.icon(name);
      el.dataset.iconRendered = name;
    });
  }

  function openModal(id) {
    document.getElementById(id).classList.remove("hidden");
    document.body.classList.add("modal-open");
  }

  function closeModal(id) {
    document.getElementById(id).classList.add("hidden");
    if (!document.querySelector(".modal-backdrop:not(.hidden)")) {
      document.body.classList.remove("modal-open");
    }
  }

  window.hydrateIcons = hydrateIcons;
  window.openModal = openModal;
  window.closeModal = closeModal;
})();
