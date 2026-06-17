
// ----------------------------------
// DOM references
// ----------------------------------

// Usually const but some are reassigned later

// LEFT SIDEBAR

// Top Left
const topLeftNewChatBtn = document.getElementById("newChat");
const topLeftNewProjBtn = document.getElementById("newProjectBtn");
// #region the Top Menu Hamburger
// the underlying menu
const topMenuBtn = document.getElementById("topMenuButton");
const topMenu = document.getElementById("topMenu");
const topMenuManageFilesBtn = document.getElementById("manageFilesTop");
const topMenuLibraryBtn = document.getElementById("openLibraryTop");
const topMenuOpenMemoryBtn = document.getElementById("openMemory");
const topMenuAdvancedABToggle = document.getElementById("advancedCheckbox");
const topMenuSearchChatHistoryToggle = document.getElementById("searchChatHistoryToggle");
// #endregion

// Conversation and Project List
const sideBarProjListEl = document.getElementById("projectList");
//const sideBarConvListEl = document.getElementById("convList");

// CENTER PAGE

// #region Top of Page/Chat Bar and Menu
const topBarChatTitleEl = document.getElementById("chatTitle");
// Model Selectors and Info Panels
const topBarModelSelectA = document.getElementById("modelSelectA");
const topBarModelSelectB = document.getElementById("modelSelectB");
const topBarModelInfoA = document.getElementById("modelInfoA");
const topBarModelInfoB = document.getElementById("modelInfoB");
// #endregion
// #region Inside the Chat Window
const chatWindow = document.getElementById("chat");
const chatWindowInputTextbox = document.getElementById("input");
const chatWindowInputSendBtn = document.getElementById("send");
// #endregion

// RIGHT SIDEBAR

// #region Context Diagnostic Panel
const contextPreviewToggleBtn = document.getElementById("toggleContext");
const contextPreviewEl = document.getElementById("contextPreview");
// #endregion

// CONTEXT MENUS

// #region Conversation Context Menu
const convMenuEl = document.getElementById("convMenu");
const convMenuRenameBtn = document.getElementById("menuRename");
const convMenuSuggestTitleBtn = document.getElementById("menuSuggest");
const convMenuMoveToBtn = document.getElementById("menuMoveTo");
const convMenuManageFilesBtn = document.getElementById("menuConvViewFiles");
const convMenuLibraryBtn = document.getElementById("menuConvLibrary");
const convMenuCitationsBtn = document.getElementById("menuConvCitations");
const convMenuSharingBtn = document.getElementById("menuConvSharing");
const convMenuExportTranscriptBtn = document.getElementById("menuExportTranscript");
const convMenuSummarizeBtn = document.getElementById("menuSummarize");
const convMenuSettingsBtn = document.getElementById("menuConvSettings");
const convMenuArchiveBtn = document.getElementById("menuArchive");
const convMenuDeleteBtn = document.getElementById("menuDelete");
// #endregion

// #region Project Context Menu
const projMenuEl = document.getElementById("projMenu");
const projMenuNewChatBtn = document.getElementById("projNewChat");
const projMenuRenameBtn = document.getElementById("projRename");
const projMenuDescriptionBtn = document.getElementById("projDesc");
const projMenuSettingsBtn = document.getElementById("projSettings");
const projMenuToggleVisibility = document.getElementById("projToggleVisibility");
const projMenuArchiveBtn = document.getElementById("projArchive");
const projMenuDeleteBtn = document.getElementById("projDelete");
const projMenuFileUploadBtn = document.getElementById("projUpload");
const projMenuManageFilesBtn = document.getElementById("projFiles");
const projMenuLibraryBtn = document.getElementById("projLibrary");
const projMenuCitationsBtn = document.getElementById("projCitations");
const projMenuSharingBtn = document.getElementById("projSharing");
// #endregion

// MODAL DIALOGS

// #region Move To... modal
const moveToModal = document.getElementById("moveToModal");
const moveToInput = document.getElementById("moveToInput");
const moveToDatalist = document.getElementById("moveToDatalist");
const moveToClose = document.getElementById("moveToClose");
const moveToCancel = document.getElementById("moveToCancel");
const moveToClear = document.getElementById("moveToClear");
const moveToApply = document.getElementById("moveToApply");
const moveToBackdrop = moveToModal ? moveToModal.querySelector(".modalBackdrop") : null;
// #endregion

// #region Personalization Modal (Instructions and Memories)
const persModal = document.getElementById("memoryModal");
const persCloseBtn = document.getElementById("closeMemory");
const persBackdrop = persModal
  ? persModal.querySelector(".modalBackdrop")
  : null;
// Pins (Personalization/Instructions)
const pinListEl = document.getElementById("pinList");
const pinTextEl = document.getElementById("pinText");
const pinAddOrSaveBtn = document.getElementById("addPin");
const pinCancelEditBtn = document.getElementById("cancelPinEdit");
// Project Settings in Memory model
const projectSettingsSectionEl = document.getElementById("projectSettingsSection");
const projectSettingsTitle = document.getElementById("projectSettingsTitle");
const projectSystemPromptEl = document.getElementById("projectSystemPrompt");
const projectVisibilityEl = document.getElementById("projectVisibility");
const projectOverrideCorePromptEl = document.getElementById("projectOverrideCorePrompt");
const saveProjectSettingsBtn = document.getElementById("saveProjectSettings");
// About You - Just a special pin really
const aboutYouNicknameEl = document.getElementById("aboutYouNickname");
const aboutYouAgeEl = document.getElementById("aboutYouAge");
const aboutYouOccupationEl = document.getElementById("aboutYouOccupation");
const aboutYouMoreEl = document.getElementById("aboutYouMore");
const aboutYouSaveBtn = document.getElementById("saveAboutYou");
const aboutYouSharingBtn = document.getElementById("aboutYouSharing");
const aboutYouSectionEl = aboutYouNicknameEl ? aboutYouNicknameEl.closest(".memSection") : null;
// Memories
const memoryListEl = document.getElementById("memoryList");
const memoryTextEl = document.getElementById("memoryText");
const memoryTagsEl = document.getElementById("memoryTags");
const memoryImportanceEl = document.getElementById("memoryImportance");
const memorySaveBtn = document.getElementById("saveMemory");
const memoryCancelEditBtn = document.getElementById("cancelMemoryEdit");
// Query settings (per-project)
const querySettingsSectionEl = document.getElementById("querySettingsSection");
const querySettingsTitleEl = document.getElementById("querySettingsTitle");
const saveQuerySettingsBtn = document.getElementById("saveQuerySettings");
// Model settings
const modelSettingsSectionEl = document.getElementById("modelSettingsSection");
const modelSettingsTitleEl = document.getElementById("modelSettingsTitle");
const modelTemperatureEl = document.getElementById("modelTemperature");
const modelTemperatureValueEl = document.getElementById("modelTemperatureValue");
const modelThinkingLevelEl = document.getElementById("modelThinkingLevel");
const modelThinkingLevelValueEl = document.getElementById("modelThinkingLevelValue");
const modelShowThinkingEl = document.getElementById("modelShowThinking");
const modelVerbosityEl = document.getElementById("modelVerbosity");
const modelVerbosityValueEl = document.getElementById("modelVerbosityValue");
const modelToolAggressivenessEl = document.getElementById("modelToolAggressiveness");
const modelToolAggressivenessValueEl = document.getElementById("modelToolAggressivenessValue");
const modelMaxOutputTokensEl = document.getElementById("modelMaxOutputTokens");
const modelTopPEl = document.getElementById("modelTopP");
const modelTopKEl = document.getElementById("modelTopK");
const saveModelSettingsBtn = document.getElementById("saveModelSettings");
const resetModelSettingsBtn = document.getElementById("resetModelSettings");
const customInstructionsSectionEl = document.getElementById("customInstructionsSection");
const memoriesSectionEl = document.getElementById("memoriesSection");

const qiFILE = document.getElementById("qiFILE");
const qiMEMORY = document.getElementById("qiMEMORY");
const qiCHAT = document.getElementById("qiCHAT");
const qiCHAT_SUMMARY = document.getElementById("qiCHAT_SUMMARY");
const qiFTS = document.getElementById("qiFTS");
const qiEMBEDDING = document.getElementById("qiEMBEDDING");
const qeFILE = document.getElementById("qeFILE");
const qeMEMORY = document.getElementById("qeMEMORY");
const qeCHAT = document.getElementById("qeCHAT");
const queryMaxFullFilesEl = document.getElementById("queryMaxFullFiles");
const queryMaxFullMemoriesEl = document.getElementById("queryMaxFullMemories");
const queryMaxFullChatsEl = document.getElementById("queryMaxFullChats");
const queryExpandMinArtifactHitsEl = document.getElementById("queryExpandMinArtifactHits");
const queryExpandChatWindowBeforeEl = document.getElementById("queryExpandChatWindowBefore");
const queryExpandChatWindowAfterEl = document.getElementById("queryExpandChatWindowAfter");

// #endregion

// #region File Uploads and Management
const chatWindowInputAddFilesBtn = document.getElementById("attachButton");

const uploadModal = document.getElementById("uploadModal");
const uploadScopeEl = document.getElementById("uploadScope");
const uploadFilesEl = document.getElementById("uploadFiles");
const uploadStatusEl = document.getElementById("uploadStatus");
const uploadStartBtn = document.getElementById("uploadStart");
const uploadCancelBtn = document.getElementById("uploadCancel");
const uploadCloseBtn = document.getElementById("uploadClose");
const uploadBackdrop = uploadModal
  ? uploadModal.querySelector(".modalBackdrop")
  : null;

const filesModal = document.getElementById("filesModal");
const filesTitleEl = document.getElementById("filesModalTitle");
const filesScopeNoteEl = document.getElementById("filesScopeNote");
const filesListEl = document.getElementById("filesList");
const filesCloseBtn = document.getElementById("filesClose");
const filesSaveBtn = document.getElementById("filesSave");
const filesCloseBottomBtn = document.getElementById("filesCloseBottom");
const filesBackdrop = filesModal ? filesModal.querySelector(".modalBackdrop") : null;
// #endregion
// #region Library modal
const libraryModal = document.getElementById("libraryModal");
const libraryTitleEl = document.getElementById("libraryModalTitle");
const libraryScopeNoteEl = document.getElementById("libraryScopeNote");
const librarySectionsEl = document.getElementById("librarySections");
const libraryAdminViewToggle = document.getElementById("libraryAdminView");
const libraryCloseBtn = document.getElementById("libraryClose");
const libraryCloseBottomBtn = document.getElementById("libraryCloseBottom");
const libraryBackdrop = libraryModal ? libraryModal.querySelector(".modalBackdrop") : null;
// #endregion
// #region Artifact debug modal and launch buttons
const artifactsDebugTopBtn = document.getElementById("artifactsDebugTop");
const artifactsDebugModal = document.getElementById("artifactsDebugModal");
const artifactsDebugCloseBtn = document.getElementById("artifactsDebugClose");
const artifactsDebugPre = document.getElementById("artifactsDebugPre");
// #endregion
// #region Citations Modal
const citationsModal = document.getElementById("citationsModal");
const citationsModalTitleEl = document.getElementById("citationsModalTitle");
const citationsListEl = document.getElementById("citationsList");
const citationsCloseBtn = document.getElementById("citationsClose");
const citationsCloseBottomBtn = document.getElementById("citationsCloseBottom");
const citationsBackdrop = citationsModal ? citationsModal.querySelector(".modalBackdrop") : null;
// #endregion

// ----------------------------------
// Global variables we'll need later
// ----------------------------------

// Note: Some globals are in the regions where their functions use them.

// #region State Maintenance

// Conversation state:
let conversationMap = new Map(); // id -> {id,title,created_at}
let conversationId = null; // currently active conversation ID
let menuTargetConversationId = null; // which conversation the context menu is currently targeting (for rename/suggest actions)
// Context view state:
let contextExpanded = false; // whether the "show more" context view is expanded, which affects how much context is fetched and shown in the preview
// Toggle advanced AB mode features on/off.
let advancedMode = false; // whether advanced features (model B, A/B button) are enabled
let hideSendInAdvanced = true; // This is likely no longer useful // if true, "Send" button is hidden whenever A/B is visible, forcing users to use A/B for better comparison data
// Project modal state:
let menuTargetProjectId = null; // which project the context menu is currently targeting (for rename/desc/upload actions)
let projectsCache = []; // cache of projects for quick lookup when showing the "move to project" list in conversation menu
// Chat message meta info state:
let metaInfoModal = null;
let metaInfoTitleEl = null;
let metaInfoPreEl = null;
let metaInfoSharingEditorEl = null;
// Upload modal state:
let uploadProjectIdForced = null;
// Library modal state:
let libraryModalMode = null; // "conversation" | "project" | "global"
let libraryModalConversationId = null;
let libraryModalProjectId = null;
const LIBRARY_COLLAPSE_THRESHOLD = 12;
const libraryGroupCollapseState = new Map();
// Files modal state:
let filesModalMode = null; // "conversation" | "project" | "global" | "all"
let filesModalConversationId = null;
let filesModalProjectId = null;
const FILES_COLLAPSE_THRESHOLD = 12;
const filesGroupCollapseState = new Map();
const selectedManageFileIds = new Set();
let hasAnyFiles = false;
let citationsModalMode = null; // "conversation" | "project"
let citationsModalConversationId = null;
let citationsModalProjectId = null;
// Context preview and trigger state:
let contextRefreshTimer = null;
let contextRefreshing = false;
let lastContextDraftSent = "";
// chat transcript re-generation/append state:
let transcriptRefreshTimer = null;
// Personalization modal state:
let personalizationMode = "global"; // "global" | "project" | "conversation"
let personalizationProjectId = null;
let personalizationConversationId = null;
let editingMemoryId = null;
let memoriesCache = [];
let editingPinId = null;
let pinsCache = [];
// context diagnostic state:
let lastContextQueryText = "";
let lastRenderedContext = null;
let contextPayloadMessageState = {};
const CONTEXT_SECTION_STATE_KEY = "wyrmgpt.contextSectionState";
const contextSectionState = (() => {
  const defaults = {
    scopeQuery: true,
    promptLayers: true,
    wholeAssets: true,
    expansion: true,
    ragFinal: true,
    ragRaw: false,
    recentContext: false,
    ragDebug: false,
    llmPayload: false,
  };

  try {
    const raw = localStorage.getItem(CONTEXT_SECTION_STATE_KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw);
    return { ...defaults, ...(parsed || {}) };
  } catch {
    return defaults;
  }
})();

// #endregion

// Zeitgeber hints - used to let ChatGPT know the time of a chat
const ZEIT_PREFIX_RE = /^\s*(?:⟂ts=\d+|⟂t=\d{8}T\d{6}Z(?:\s+⟂age=-?\d+)?)\s*\n/;
const LEGACY_PREFIX_RE = /^\s*\[20\d\d-[^\]]+\]\s*\n/;

// #region Configuration

// TODO pull these from config objects/API

let APP_CONFIG = {
  search_chat_history: true,
};
// TODO implement me per comment below
let UI_CONFIG = {
  local_timezone: null, // TZ for display
  // Context preview settings
  context_preview_limit_min: 20,
  context_preview_limit_max: 200,
  // Real-time Context Preview + RAG query update timer config
  min_rag_query_text_len: 5, // minimum size of text input to matter for previews
  context_idle_ms: 5000, // How long user should idle typing before we refresh context preview
  // Chat transcript re-generation/append config
  transcript_idle_ms: 120000, // 2 minutes
  debug_boot: true,
}

// #endregion

// ----------------------------------
// Helpers for UI state management and updates. 
// ----------------------------------

function pickPositiveInt(value, fallback) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : fallback;
}

// #region Zeitgeber helpers

function formatDate(iso) {
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso || "";
  }
}

function formatReadableDateTime(iso) {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso || "";

    const opts = {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "numeric",
      minute: "2-digit",
    };

    if (UI_CONFIG.local_timezone) {
      return new Intl.DateTimeFormat(undefined, { ...opts, timeZone: UI_CONFIG.local_timezone }).format(d);
    }
    return new Intl.DateTimeFormat(undefined, opts).format(d);
  } catch {
    return iso || "";
  }
}

function stripZeit(text) {
  if (!text) return text;
  return text.replace(ZEIT_PREFIX_RE, "").replace(LEGACY_PREFIX_RE, "");
}

// #endregion

// #region Transcript Generation Helpers

function cancelScheduledTranscriptRefresh() {
  if (transcriptRefreshTimer) {
    clearTimeout(transcriptRefreshTimer);
    transcriptRefreshTimer = null;
  }
}

async function flushConversationTranscriptArtifact(cid, reason = "manual", useBeacon = false) {
  if (!cid) return;

  const url = `/api/conversation/${encodeURIComponent(cid)}/refresh_transcript_artifact?reason=${encodeURIComponent(reason)}`;

  if (useBeacon && navigator.sendBeacon) {
    try {
      const ok = navigator.sendBeacon(url, new Blob([], { type: "text/plain" }));
      if (ok) return;
    } catch (e) {
      // fall through to fetch
    }
  }

  try {
    await fetch(url, {
      method: "POST",
      keepalive: reason === "unload",
    });
  } catch (e) {
    console.warn("flushConversationTranscriptArtifact failed", e);
  }
}

function scheduleTranscriptRefresh(cid = conversationId) {
  if (!cid) return;

  cancelScheduledTranscriptRefresh();

  transcriptRefreshTimer = setTimeout(async () => {
    transcriptRefreshTimer = null;
    try {
      await flushConversationTranscriptArtifact(cid, "idle");
    } catch (e) {
      console.warn("scheduled transcript refresh failed", e);
    }
  }, UI_CONFIG.transcript_idle_ms);
}

// #endregion

// #region app_settings and UI Config Helpers

// TODO make this a class instead of a bunch of global vars
async function fetchUiConfig() {
  try {
    const cfg = await fetchJsonDebug("/api/ui_config");

    UI_CONFIG.local_timezone = (cfg && cfg.local_timezone) ? String(cfg.local_timezone) : null;

    UI_CONFIG.context_preview_limit_min = pickPositiveInt(
      cfg?.context_preview_limit_min,
      UI_CONFIG.context_preview_limit_min
    );
    UI_CONFIG.context_preview_limit_max = pickPositiveInt(
      cfg?.context_preview_limit_max,
      UI_CONFIG.context_preview_limit_max
    );
    UI_CONFIG.min_rag_query_text_len = pickPositiveInt(
      cfg?.min_rag_query_text_len,
      UI_CONFIG.min_rag_query_text_len
    );
    UI_CONFIG.context_idle_ms = pickPositiveInt(
      cfg?.context_idle_ms,
      UI_CONFIG.context_idle_ms
    );
    UI_CONFIG.transcript_idle_ms = pickPositiveInt(
      cfg?.transcript_idle_ms,
      UI_CONFIG.transcript_idle_ms
    );

    if (typeof cfg?.debug_boot === "boolean") {
      UI_CONFIG.debug_boot = cfg.debug_boot;
    }
  } catch {
    UI_CONFIG.local_timezone = null;
  }
}

async function fetchAppConfig() {
  try {
    const cfg = await fetchJsonDebug("/api/app_config");
    APP_CONFIG = {
      search_chat_history: !!cfg?.search_chat_history,
    };

    if (topMenuSearchChatHistoryToggle) {
      topMenuSearchChatHistoryToggle.checked = APP_CONFIG.search_chat_history;
    }
  } catch (e) {
    console.warn("fetchAppConfig failed", e);
  }
}

async function saveAppConfig(patch) {
  const cfg = await fetchJsonDebug("/api/app_config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch || {}),
  });

  APP_CONFIG = {
    search_chat_history: !!cfg?.search_chat_history,
  };

  if (topMenuSearchChatHistoryToggle) {
    topMenuSearchChatHistoryToggle.checked = APP_CONFIG.search_chat_history;
  }

  return APP_CONFIG;
}

// #endregion

// #region General Menu / Modal Helpers

function toggleTopMenu(forceState) {
  if (!topMenu) return;
  const shouldShow = forceState !== undefined
    ? forceState
    : topMenu.classList.contains("hidden");

  if (shouldShow) {
    hideAllTransientUI({ except: [topMenu] });
    topMenu.classList.remove("hidden");
  } else {
    topMenu.classList.add("hidden");
  }
}

// to ensure small modals (like conversation and project mgmt.) don't end up off-screen if the click is near the edge
function positionMenu(menuEl, x, y) {
  if (!menuEl) return;

  // Initial position near the click
  menuEl.style.left = x + "px";
  menuEl.style.top = y + "px";
  menuEl.classList.remove("hidden");

  // Now clamp into viewport
  const rect = menuEl.getBoundingClientRect();
  const padding = 8;

  let left = rect.left;
  let top = rect.top;

  const maxLeft = window.innerWidth - rect.width - padding;
  const maxTop = window.innerHeight - rect.height - padding;

  if (left > maxLeft) left = maxLeft;
  if (top > maxTop) top = maxTop;
  if (left < padding) left = padding;
  if (top < padding) top = padding;

  menuEl.style.left = left + "px";
  menuEl.style.top = top + "px";
}

function hideProjMenu() {
  menuTargetProjectId = null;
  if (projMenuEl) projMenuEl.classList.add("hidden");
}

function hideAllTransientUI({ except = [] } = {}) {
  const keep = new Set((Array.isArray(except) ? except : [except]).filter(Boolean));

  if (topMenu && !keep.has(topMenu)) {
    topMenu.classList.add("hidden");
  }

  if (convMenuEl && !keep.has(convMenuEl)) {
    hideConvMenu();
  }

  if (projMenuEl && !keep.has(projMenuEl)) {
    hideProjMenu();
  }

  document.querySelectorAll(".modal").forEach((modal) => {
    if (!keep.has(modal)) {
      modal.classList.add("hidden");
    }
  });
}

// #endregion

// #region Error handling helpers

function coerceMetaObject(meta) {
  if (!meta) return null;
  if (typeof meta === "string") {
    try {
      const parsed = JSON.parse(meta);
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch {
      return null;
    }
  }
  return (typeof meta === "object") ? meta : null;
}

function isErrorBubble(msg) {
  const meta = coerceMetaObject(msg?.meta);
  return (
    (meta && meta.kind === "error") ||
    msg?.kind === "error" ||
    msg?.is_error === true ||
    (typeof msg?.content === "string" && msg.content.startsWith("[Model ") && msg.content.includes(" error]"))
  );
}

function errorDetailsFromMsg(msg) {
  const meta = (msg && msg.meta) ? msg.meta : {};
  const status = meta.status_code ?? meta.http_status ?? meta.status ?? null;
  const requestId = meta.request_id ?? meta.requestId ?? null;
  const body = meta.body ?? meta.error_body ?? null;
  const message =
    (body && body.error && body.error.message) ||
    meta.message ||
    meta.error_message ||
    null;

  return { status, requestId, message, body };
}

function bubbleClassName(msg) {
  return isErrorBubble(msg) ? "bubble bubble-error" : "bubble";
}

// #endregion

// #region Model / Deployment Settings helpers

let deployments = [];
let models = [];

function findDeploymentById(id) {
  return deployments.find((d) => d.id === id) || null;
}

function findModelById(id) {
  return models.find((m) => m.id === id) || null;
}

function findModelMeta(providerId, modelId) {
  return (
    models.find((m) => m.provider_id === providerId && m.id === modelId) ||
    models.find((m) => m.id === modelId) ||
    null
  );
}

function describeSelection(id) {
  const dep = findDeploymentById(id);
  if (dep) {
    return {
      kind: "deployment",
      id: dep.id,
      display_name: dep.display_name || dep.id,
      provider_id: dep.provider_id || "",
      provider_type: dep.provider_type || "",
      model: dep.model || dep.id,
      tags: dep.tags || [],
      capabilities: dep.capabilities || [],
      vendor: dep.vendor || dep.provider_id || "",
      description: dep.description || "",
      input_cost_per_million: dep.input_cost_per_million,
      output_cost_per_million: dep.output_cost_per_million,
      context_window: dep.context_window,
    };
  }

  const model = findModelById(id);
  if (model) {
    return {
      kind: "model",
      id: model.id,
      display_name: model.display_name || model.id,
      provider_id: model.provider_id || "",
      provider_type: model.provider_type || "",
      model: model.id,
      tags: model.tags || [],
      capabilities: [],
      vendor: model.vendor || model.provider_id || "",
      description: model.description || "",
      input_cost_per_million: model.input_cost_per_million,
      output_cost_per_million: model.output_cost_per_million,
      context_window: model.context_window,
    };
  }

  return {
    kind: "raw",
    id: id,
    display_name: id,
    provider_id: "",
    provider_type: "",
    model: id,
    tags: [],
    capabilities: [],
    vendor: "",
    description: "",
    input_cost_per_million: null,
    output_cost_per_million: null,
    context_window: null,
  };
}

function updateModelInfo(which) {
  const sel = which === "A" ? topBarModelSelectA : topBarModelSelectB;
  const infoEl = which === "A" ? topBarModelInfoA : topBarModelInfoB;
  if (!sel || !infoEl) return;

  const choice = describeSelection(sel.value || "");
  const modelMeta = choice.model
    ? findModelMeta(choice.provider_id, choice.model)
    : null;

  // Prefer live model metadata, but fall back to deployment metadata from /api/deployments.
  const meta = modelMeta || choice;

  const parts = [];

  parts.push(`<span class="modelName">${escapeHtml(choice.display_name || choice.id)}</span>`);

  if (choice.provider_id) {
    parts.push(`<span class="modelVendor">${escapeHtml(choice.provider_id)}</span>`);
  }

  if (choice.kind === "deployment" && choice.model && choice.model !== choice.display_name) {
    parts.push(`<span class="modelId">${escapeHtml(choice.model)}</span>`);
  }

  if (Array.isArray(choice.capabilities) && choice.capabilities.length) {
    parts.push(`<span class="modelCaps">${escapeHtml(choice.capabilities.join(", "))}</span>`);
  }

  if (meta?.input_cost_per_million != null) {
    parts.push(`<span class="modelPrice">in: $${meta.input_cost_per_million}/M</span>`);
  }
  if (meta?.output_cost_per_million != null) {
    parts.push(`<span class="modelPrice">out: $${meta.output_cost_per_million}/M</span>`);
  }
  if (meta?.context_window) {
    parts.push(`<span class="modelContext">ctx: ${Number(meta.context_window).toLocaleString()} tokens</span>`);
  }

  let html = parts.join(" · ");
  if (meta?.description) {
    html += `<div class="modelDesc">${escapeHtml(meta.description)}</div>`;
  }

  infoEl.innerHTML = html;
}

async function refreshDeployments(refreshUi = false) {
  const data = await fetchJsonDebug("/api/deployments");
  deployments = data.deployments || [];

  if (refreshUi) {
    renderModelDropdowns();
    updateModelInfo("A");
    updateModelInfo("B");
  }
}

async function refreshModels() {
  const [modelData, deploymentData] = await Promise.all([
    fetchJsonDebug("/api/models"),
    fetchJsonDebug("/api/deployments"),
  ]);

  models = modelData.models || [];
  deployments = deploymentData.deployments || [];

  renderModelDropdowns();
  updateModelInfo("A");
  updateModelInfo("B");
}

function renderModelDropdowns() {
  const selA = document.getElementById("modelSelectA");
  const selB = document.getElementById("modelSelectB");
  if (!selA || !selB) return;

  const savedA = localStorage.getItem("chatoss.modelA") || "";
  const savedB = localStorage.getItem("chatoss.modelB") || "";

  selA.innerHTML = "";
  selB.innerHTML = "";

  for (const d of deployments) {
    const meta =
      findModelMeta(d.provider_id, d.model) || d;

    const labelParts = [d.display_name || d.id];

    if (d.provider_id) labelParts.push(d.provider_id);
    if (d.model && d.model !== d.display_name) labelParts.push(d.model);

    if (meta.input_cost_per_million != null && meta.output_cost_per_million != null) {
      labelParts.push(`~$${meta.input_cost_per_million}/${meta.output_cost_per_million} per M tok`);
    }

    if (Array.isArray(d.tags) && d.tags.length) {
      labelParts.push(d.tags.join(", "));
    }

    const label = labelParts.join(" · ");

    const optA = document.createElement("option");
    optA.value = d.id;
    optA.textContent = label;

    const optB = document.createElement("option");
    optB.value = d.id;
    optB.textContent = label;

    selA.appendChild(optA);
    selB.appendChild(optB);
  }

  function maybeAppendLegacyOption(sel, value) {
    if (!value) return;
    if ([...sel.options].some((o) => o.value === value)) return;

    const model = findModelById(value);
    const label = model
      ? `${model.display_name || model.id} · legacy model`
      : `${value} · legacy value`;

    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    sel.appendChild(opt);
  }

  maybeAppendLegacyOption(selA, savedA);
  maybeAppendLegacyOption(selB, savedB);

  if (savedA && [...selA.options].some((o) => o.value === savedA)) {
    selA.value = savedA;
  }
  if (savedB && [...selB.options].some((o) => o.value === savedB)) {
    selB.value = savedB;
  }
}
function initABUI() {
  renderModelDropdowns();
  
  const footer = document.querySelector("footer");
  if (footer) {
  }
}

// #endregion

function resolveCardScopeLabel(item, explicitFallback = "") {
  const direct = String(item?.scope_label || "").trim();
  if (direct) return direct;

  if (item?.scope_type === "project" && Array.isArray(item?.meta)) {
    const line = item.meta.find((x) => typeof x === "string" && x.startsWith("Project: "));
    if (line) return line.replace(/^Project:\s*/, "").trim();
  }
  const fallback = String(explicitFallback || "").trim();
  if (fallback) return fallback;

  const scopeType = String(item?.scope_type || "").trim().toLowerCase();
  if (scopeType === "project") {
    const projectId = item?.scope_id ?? filesModalProjectId ?? libraryModalProjectId ?? null;
    if (projectId != null) {
      const project = (projectsCache || []).find((p) => Number(p.id) === Number(projectId));
      return String(project?.name || "").trim();
    }
  }

  if (scopeType === "conversation" && item?.scope_uuid) {
    return String(conversationMap.get(String(item.scope_uuid))?.title || "").trim();
  }

  return "";
}

// Chat message helpers moved to /static/app.chat.js
// Context/artifact helpers moved to /static/app.context.js
// File/Upload helpers moved to /static/app.file.js
// Conv/Project helpers moved to /static/app.manage.js
// Event bindings and boot moved to /static/app.events.js
