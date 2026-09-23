// Service worker registration and the update prompt bar. The one place the
// worker is registered, for every page: the prompt needs the registration
// object, and an inline register() in the markup has nowhere to hand it to.
//
// A new worker never activates on its own. It installs and waits, and only a
// press of Reload in the bar promotes it. See sw.js for the other half.
(function () {
  var SW_URL = "/sw.js";

  var STRINGS = {
    label: "Update",
    ready: "A new version of Henrusian Dictionary is ready.",
    reload: "Reload",
    later: "Not now",
  };

  var registration = null;
  var waitingWorker = null;
  var reloading = false;
  // For this page view only, and never stored. "Not now" means not now.
  var dismissed = false;

  function render() {
    var existing = document.querySelector(".update-notice");

    if (!waitingWorker || dismissed) {
      if (existing) hideBar(existing);
      return;
    }
    if (existing) return;

    var bar = document.createElement("div");
    bar.className = "update-notice";
    // status, not alert: nothing is wrong, and an alert would interrupt a
    // screen reader mid-sentence to say the site is slightly newer.
    bar.setAttribute("role", "status");
    bar.setAttribute("aria-label", STRINGS.label);

    var inner = document.createElement("div");
    inner.className = "update-notice-inner";

    var text = document.createElement("p");
    text.textContent = STRINGS.ready;

    var reload = document.createElement("button");
    reload.type = "button";
    reload.className = "update-notice-btn primary";
    reload.setAttribute("data-sw-update", "");
    reload.textContent = STRINGS.reload;
    reload.addEventListener("click", function () {
      // The only place anything asks for skipWaiting. The reload itself
      // happens on controllerchange, not here.
      if (waitingWorker) waitingWorker.postMessage("skip-waiting");
    });

    var later = document.createElement("button");
    later.type = "button";
    later.className = "update-notice-btn";
    later.setAttribute("data-sw-later", "");
    later.textContent = STRINGS.later;
    later.addEventListener("click", function () {
      dismissed = true;
      render();
    });

    inner.append(text, reload, later);
    bar.append(inner);
    document.body.prepend(bar);
  }

  // Animated out, then removed. With reduced motion the animation is near
  // instant and animationend still fires.
  function hideBar(bar) {
    if (bar.classList.contains("leaving")) return;
    bar.classList.add("leaving");
    bar.addEventListener("animationend", function () { bar.remove(); }, { once: true });
  }

  function watchForUpdate() {
    if (!registration) return;

    // A worker already waiting when the page opened. The ordinary case on the
    // second page view after a deploy; without it the prompt would only reach
    // somebody who had the page open while the new worker installed.
    if (registration.waiting && navigator.serviceWorker.controller) {
      waitingWorker = registration.waiting;
      render();
    }

    registration.addEventListener("updatefound", function () {
      var installing = registration.installing;
      if (!installing) return;

      installing.addEventListener("statechange", function () {
        // installed with a controller present is an update. installed with no
        // controller is a first install, with no previous version on screen.
        if (installing.state === "installed" && navigator.serviceWorker.controller) {
          waitingWorker = registration.waiting || installing;
          render();
        }
      });
    });
  }

  function registerWorker() {
    if (!("serviceWorker" in navigator)) return;

    navigator.serviceWorker
      .register(SW_URL)
      .then(function (reg) {
        registration = reg;
        watchForUpdate();
      })
      .catch(function (cause) {
        // Private browsing in some browsers, and any http origin that is not
        // localhost, land here. Not a reason to break the page.
        console.warn("service worker registration failed:", cause);
      });

    // The swap, once somebody has accepted it. Reloading here rather than in
    // the click handler is what brings the page back on the new version: the
    // controller has already changed, so the new worker serves the reload.
    // The flag guards against controllerchange firing more than once.
    navigator.serviceWorker.addEventListener("controllerchange", function () {
      if (reloading) return;
      reloading = true;
      window.location.reload();
    });
  }

  // On load, not immediately: installing fetches everything the worker
  // precaches, and competing with the page's own assets slows a first visit.
  if (document.readyState === "complete") registerWorker();
  else window.addEventListener("load", registerWorker, { once: true });
})();
