const api = typeof browser !== "undefined" ? browser : chrome;
//const isFirefox = typeof browser !== "undefined";

const STORAGE_KEY = "chatgptdom.config";
const SCHEMA_VERSION = 2;

const DEFAULT_CONFIG = {
  schema_version: SCHEMA_VERSION,
  exportConfig: {
    autoBackup: {
      enabled: false,
      formats: ["json"],
      everyNMessages: 10,
    },
    backupOnLoad: {
      enabled: false,
      formats: ["json"],
    },
    toastOnExport: true
  },
  keyBindings: {
    exportJSON: "Ctrl+Shift+S",
    exportMD: "Ctrl+Shift+M",
    exportHTML: "Ctrl+Shift+H",
    toggleAutoBackup: "Ctrl+Shift+B",
    toggleBackupOnLoad: "Ctrl+Shift+L",
    manualFullBackup: "Ctrl+Shift+F",
    showKeyBindings: "Ctrl+Shift+Alt+K"
  }};
  const knownBrowserShortcuts = new Set([
    "Ctrl+T",
    "Ctrl+W",
    "Ctrl+Shift+T",
    "Ctrl+Shift+K",
    "Ctrl+L",
    "Ctrl+Tab",
    "Ctrl+Shift+Tab",
    "Ctrl+R",
    "Ctrl+Shift+R",
    "Ctrl+N",
    "Ctrl+Shift+N",
    "Ctrl+J",
    "Ctrl+K",
    "Ctrl+F",
    "Ctrl+H"
  ]);

async function ensureDefaults(force = false) {
  const result = await api.storage.local.get(STORAGE_KEY);
  if (!result[STORAGE_KEY] || force) {
    await api.storage.local.set({ [STORAGE_KEY]: DEFAULT_CONFIG });
  }
}

async function getConfig() {
  const result = await api.storage.local.get(STORAGE_KEY);
  const stored = result[STORAGE_KEY];

  if (!stored || stored.schema_version !== SCHEMA_VERSION) {
    await api.storage.local.set({ [STORAGE_KEY]: DEFAULT_CONFIG });
    return structuredClone(DEFAULT_CONFIG);
  }
  return stored;
}
async function setConfig(newConfig) {
  await api.storage.local.set({ [STORAGE_KEY]: newConfig });
  return { ok: true };
}

function detectConflicts(keyBindings) {
  //const combos = Object.values(keyBindings || {}).map(k => k.combo);
  const combos = Object.values(keyBindings || {});
  const seen = new Set();
  const conflicts = [];

  for (const combo of combos) {
    if (!combo) continue;
    if (knownBrowserShortcuts.has(combo)) {
      conflicts.push({
        combo,
        type: "browser"
      });
    }
    if (seen.has(combo)) {
      conflicts.push({
        combo,
        type: "duplicate"
      });
    }
    seen.add(combo);
  }
  return conflicts;
}

async function broadcastConfigUpdate() {
  const cfg = await getConfig();
  const tabs = await api.tabs.query({});
  for (const tab of tabs) {
    api.tabs.sendMessage(tab.id, { type: "CONFIG_UPDATED", payload: cfg })
      .catch(() => {});
  }
}

api.runtime.onInstalled.addListener(async () => {
  await ensureDefaults();
  console.log("[ChatGPTDOM] Installed / initialized");
});

api.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message?.type) return;

  (async () => {
    switch (message.type) {
      case "GET_CONFIG": {
        const cfg = await getConfig();
        sendResponse(cfg);
        break;
      }
      case "SET_CONFIG": {
        await setConfig(message.payload);
        await broadcastConfigUpdate();
        sendResponse({ ok: true });
        break;
      }
      case "RESET_CONFIG": {
        await ensureDefaults(true);
        await broadcastConfigUpdate();
        sendResponse(structuredClone(DEFAULT_CONFIG));
        break;
      }
      case "CHECK_CONFLICTS": {
        sendResponse({
          conflicts: detectConflicts(message.payload)
        });
        break;
      }
    }
  })();
  return true; // Required for async in Chrome MV3
});

ensureDefaults();