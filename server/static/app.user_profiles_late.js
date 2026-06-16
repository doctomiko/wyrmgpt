// Late hook so legacy event handlers use active-user About You functions.
(function () {
  function installLateAboutYouHandler() {
    const saveBtn = document.getElementById("saveAboutYou");
    if (saveBtn && window.saveAboutYou) {
      saveBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        window.saveAboutYou().catch((e) => alert(`Failed to save About You: ${e?.message || e}`));
      }, true);
    }

    const openMemory = document.getElementById("openMemory");
    if (openMemory && window.wyrmgptIdentity?.state) {
      openMemory.addEventListener("click", () => {
        setTimeout(() => {
          if (window.fetchAboutYou && window.populateAboutYouForm) {
            window.fetchAboutYou()
              .then((data) => window.populateAboutYouForm(data))
              .catch((e) => console.warn("active-user About You refresh failed", e));
          }
        }, 0);
      }, true);
    }
  }
  installLateAboutYouHandler();
})();
