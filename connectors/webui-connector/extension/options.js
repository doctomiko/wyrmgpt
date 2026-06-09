const api = typeof browser !== "undefined" ? browser : chrome;

function storageGet() {
  return api.runtime.sendMessage({ type: "GET_CONFIG" });
}
function storageSet(data) {
  return api.runtime.sendMessage({ type: "SET_CONFIG", payload: data });
}

async function load() {
  const cfg = await storageGet();
  if (!cfg) return;

  renderFromConfig(cfg);

  const ec = cfg.exportConfig;

  document.getElementById("autoBackupEnabled").checked = ec.autoBackup.enabled;
  document.getElementById("autoBackupEvery").value = ec.autoBackup.everyNMessages;
  document.getElementById("backupOnLoadEnabled").checked = ec.backupOnLoad.enabled;
  document.getElementById("toastOnExport").checked = ec.toastOnExport;

  for (const el of document.querySelectorAll(".autoFormat")) {
    el.checked = ec.autoBackup.formats.includes(el.value);
  }
  for (const el of document.querySelectorAll(".loadFormat")) {
    el.checked = ec.backupOnLoad.formats.includes(el.value);
  }

  renderHotkeys(cfg);  
}

async function save() {
  let cfg = await storageGet();
  if (!cfg) return;
  const ec = cfg.exportConfig;

  ec.autoBackup.enabled =
    document.getElementById("autoBackupEnabled").checked;
  ec.autoBackup.everyNMessages =
    Number(document.getElementById("autoBackupEvery").value) || 1;
  ec.autoBackup.formats =
    Array.from(document.querySelectorAll(".autoFormat:checked"))
      .map(e => e.value);
  ec.backupOnLoad.enabled =
    document.getElementById("backupOnLoadEnabled").checked;
  ec.backupOnLoad.formats =
    Array.from(document.querySelectorAll(".loadFormat:checked"))
      .map(e => e.value);
  ec.toastOnExport =
    document.getElementById("toastOnExport").checked;

  cfg.keyBindings = cfg.keyBindings || {};
  for (const input of document.querySelectorAll("#hotkeys input[data-action]")) {
    cfg.keyBindings[input.dataset.action] = input.value.trim();
  }

  // 🔍 Ask background about conflicts
  const conflicts = await checkConflicts(cfg.keyBindings);

  if (conflicts.length > 0) {
    showConflictWarnings(conflicts);
    return;
  }

  clearConflictWarnings();

  await storageSet(cfg);

  const status = document.getElementById("status");
  status.textContent = "Saved (open ChatGPT tabs update automatically)";
  setTimeout(() => status.textContent = "", 2000);
}

/*
async function save() {
  let cfg = await storageGet();
  if (!cfg) return;
  //if (!cfg) cfg = structuredClone(DEFAULT_CONFIG);

  const ec = cfg.exportConfig;
  ec.autoBackup.enabled =
    document.getElementById("autoBackupEnabled").checked;
  ec.autoBackup.everyNMessages =
    Number(document.getElementById("autoBackupEvery").value) || 1;
  ec.autoBackup.formats =
    Array.from(document.querySelectorAll(".autoFormat:checked"))
      .map(e => e.value);
  ec.backupOnLoad.enabled =
    document.getElementById("backupOnLoadEnabled").checked;
  ec.backupOnLoad.formats =
    Array.from(document.querySelectorAll(".loadFormat:checked"))
      .map(e => e.value);
  ec.toastOnExport =
    document.getElementById("toastOnExport").checked;
  cfg.keyBindings = cfg.keyBindings || {};
  for (const input of document.querySelectorAll("#hotkeys input[data-action]")) {
    cfg.keyBindings[input.dataset.action] = input.value.trim();
  }
  await storageSet(cfg);

  const status = document.getElementById("status");
  status.textContent = "Saved (open ChatGPT tabs update automatically)";
  setTimeout(() => status.textContent = "", 2000);
}
*/

function renderHotkeys(cfg) {
  const root = document.getElementById("hotkeys");
  root.innerHTML = "";

  const bindings = cfg.keyBindings || {};
  for (const [action, combo] of Object.entries(bindings)) {
    const row = document.createElement("div");
    row.style.margin = "6px 0";

    const input = document.createElement("input");
    input.value = combo;
    input.dataset.action = action;
    input.style.marginLeft = "8px";
    input.style.width = "200px";

    const warn = document.createElement("div");
    warn.dataset.warnFor = action;
    warn.style.fontSize = "12px";
    warn.style.marginLeft = "90px";

    row.innerHTML = `<code>${action}</code>`;
    row.appendChild(input);
    row.appendChild(warn);
    root.appendChild(row);
  }

  // After rendering, show warnings once
  checkConflicts(cfg.keyBindings).then(conflicts => {
    if (conflicts.length > 0) showConflictWarnings(conflicts);
    else clearConflictWarnings();
  });  
}

async function checkConflicts(keyBindings) {
  const response = await api.runtime.sendMessage({
    type: "CHECK_CONFLICTS",
    payload: keyBindings
  });
  return response?.conflicts || [];
}

function showConflictWarnings(conflicts) {
  const container = document.getElementById("conflict-warnings");
  if (!container) return;

  container.innerHTML = "";

  conflicts.forEach(c => {
    const div = document.createElement("div");
    div.className = "warning";
    const header = "⚠Warning: ";
    if (c.type === "browser") {
      div.textContent = header + `${c.combo} is reserved by the browser.`;
    } else if (c.type === "duplicate") {
      div.textContent = header + `${c.combo} is assigned more than once.`;
    } else {
      div.textContent = header + ` ${c.combo} conflict detected.`;
    }
    container.appendChild(div);
  });
}

function clearConflictWarnings() {
  const container = document.getElementById("conflict-warnings");
  if (container) container.innerHTML = "";
}

/*
function showConflictWarnings() {
  const inputs = Array.from(document.querySelectorAll("#hotkeys input[data-action]"));
  const used = new Map(); // combo -> first action
  for (const input of inputs) {
    const action = input.dataset.action;
    const combo = input.value.trim();
    const warn = document.querySelector(`[data-warn-for="${action}"]`);
    warn.textContent = "";

    if (!combo) continue;
    
    if (knownBrowserShortcuts.has(combo)) {
      warn.textContent = `⚠ Often reserved by the browser: ${combo}`;
      continue;
    }

    if (used.has(combo)) {
      warn.textContent = `⚠ Duplicate: also used by "${used.get(combo)}"`;
      continue;
    }

    used.set(combo, action);
  }
}
*/

async function resetToDefaults() {
  const cfg = await api.runtime.sendMessage({ type: "RESET_CONFIG" });
  await load();  // re-render UI
}

document.getElementById("save").addEventListener("click", save);
document.getElementById("reset").addEventListener("click", resetToDefaults);
document.addEventListener("input", async (e) => {
  if (e.target && e.target.matches("#hotkeys input[data-action]")) {
    const cfg = await storageGet();
    if (!cfg) return;

    cfg.keyBindings = cfg.keyBindings || {};
    for (const input of document.querySelectorAll("#hotkeys input[data-action]")) {
      cfg.keyBindings[input.dataset.action] = input.value.trim();
    }

    const conflicts = await checkConflicts(cfg.keyBindings);

    if (conflicts.length > 0) {
      showConflictWarnings(conflicts);
    } else {
      clearConflictWarnings();
    }
  }
});
/*
document.addEventListener("input", (e) => {
  if (e.target && e.target.matches("#hotkeys input[data-action]")) {
    showConflictWarnings();
  }
});
saveButton.addEventListener("click", async () => {
  const cfg = await browser.runtime.sendMessage({ type: "GET_CONFIG" });
  if (!cfg) return;
  // update config from UI
  cfg.keyBindings = collectKeyBindingsFromUI();
  cfg.exportConfig = collectExportConfigFromUI();
  // 🔍 Ask background about conflicts
  const conflicts = await checkConflicts(cfg.keyBindings);

  if (conflicts.length > 0) {
    showConflictWarnings(conflicts);
    return; // stop here
  }
  clearConflictWarnings();
  await browser.runtime.sendMessage({
    type: "SET_CONFIG",
    payload: cfg
  });
  showSavedMessage();
});
*/
load();
