
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
// const topMenuRenameChatBtn = document.getElementById("renameChat");
// const topMenuSuggestTitleBtn = document.getElementById("suggestChat");
const topMenuManageFilesBtn = document.getElementById("manageFilesTop");
const topMenuOpenMemoryBtn = document.getElementById("openMemory");
const topMenuAdvancedABToggle = document.getElementById("advancedCheckbox");
const topMenuSearchChatHistoryToggle = document.getElementById("searchChatHistoryToggle");
// #endregion

// Conversation and Project List
const sideBarProjListEl = document.getElementById("projectList");
const sideBarConvListEl = document.getElementById("convList");

// CENTER PAGE

// #region Top of Page/Chat Bar and Menu
const topBarChatTitleEl = document.getElementById("chatTitle");
// Model Selectors
const topBarModelSelectA = document.getElementById("modelSelectA");
const topBarModelSelectB = document.getElementById("modelSelectB");
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
const convMenuExportTranscriptBtn = document.getElementById("menuExportTranscript");
const convMenuSummarizeBtn = document.getElementById("menuSummarize");
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
const projMenuFileUploadBtn = document.getElementById("projUpload");
const projMenuManageFilesBtn = document.getElementById("projFiles");
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
const aboutYouSectionEl = aboutYouNicknameEl ? aboutYouNicknameEl.closest(".memSection") : null;
// Memories
const memoryListEl = document.getElementById("memoryList");
const memoryTextEl = document.getElementById("memoryText");
const memoryTagsEl = document.getElementById("memoryTags");
const memoryImportanceEl = document.getElementById("memoryImportance");
const memorySaveBtn = document.getElementById("saveMemory");
const memoryCancelEditBtn = document.getElementById("cancelMemoryEdit");
// Query settings (per-project)
const querySettingsTitleEl = document.getElementById("querySettingsTitle");
const saveQuerySettingsBtn = document.getElementById("saveQuerySettings");

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
const filesListEl = document.getElementById("filesList");
const filesCloseBtn = document.getElementById("filesClose");
const filesSaveBtn = document.getElementById("filesSave");
const filesCloseBottomBtn = document.getElementById("filesCloseBottom");
const filesBackdrop = filesModal ? filesModal.querySelector(".modalBackdrop") : null;
// #endregion
// #region Artifact debug modal and launch buttons
const artifactsDebugTopBtn = document.getElementById("artifactsDebugTop");
const artifactsDebugModal = document.getElementById("artifactsDebugModal");
const artifactsDebugCloseBtn = document.getElementById("artifactsDebugClose");
const artifactsDebugPre = document.getElementById("artifactsDebugPre");
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
// Upload modal state:
let uploadProjectIdForced = null;
// Files modal state:
let filesModalMode = null; // "conversation" | "project" | "global" | "all"
let filesModalConversationId = null;
let filesModalProjectId = null;
let hasAnyFiles = false;
// Context preview and trigger state:
let contextRefreshTimer = null;
let contextRefreshing = false;
let lastContextDraftSent = "";
// chat transcript re-generation/append state:
let transcriptRefreshTimer = null;
// Personalization modal state:
let personalizationMode = "global"; // "global" | "project"
let personalizationProjectId = null;
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
//const ZEIT_PREFIX_RE = /^\s*(?:⟂ts=\d+|⟂t=\d{8}T\d{6}Z(?:\s+⟂age=\d+)?)\s*\n/;
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

// These are usually called by event handlers or after API calls to update the screen based on the current app state.

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

// #region Context Refresh Helpers

function setContextRefreshing(isRefreshing) {
  contextRefreshing = !!isRefreshing;
  if (!contextPreviewEl) return;

  if (contextRefreshing) {
    contextPreviewEl.dataset.loading = "1";
  } else {
    delete contextPreviewEl.dataset.loading;
  }
}

function cancelScheduledContextRefresh() {
  if (contextRefreshTimer) {
    clearTimeout(contextRefreshTimer);
    contextRefreshTimer = null;
  }
}

function scheduleContextRefresh() {
  if (!conversationId) return;

  cancelScheduledContextRefresh();

  contextRefreshTimer = setTimeout(async () => {
    contextRefreshTimer = null;

    const draft = (chatWindowInputTextbox?.value || "").trim();
    if (draft.length < UI_CONFIG.min_rag_query_text_len) return;
    // Don't re-query if the draft hasn't changed since the last preview refresh.
    if (draft === lastContextDraftSent) return;

    try {
      await refreshContext();
      lastContextDraftSent = draft;
    } catch (e) {
      console.warn("debounced refreshContext failed", e);
    }
  }, UI_CONFIG.context_idle_ms);
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

// #region Artifacts Debug Modal Helpers

async function openArtifactsDebug() {
  if (!conversationId) {
    alert("Pick a conversation first.");
    return;
  }
  hideAllTransientUI({ except: [projMenuEl] });
  artifactsDebugPre.textContent = "Loading…";
  artifactsDebugModal.classList.remove("hidden");

  try {
    const data = await fetchJsonDebug(`/api/conversation/${conversationId}/artifacts/debug`);
    artifactsDebugPre.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    artifactsDebugPre.textContent = `Failed to load artifact debug:\n${e?.message || e}`;
  }
}

function closeArtifactsDebug() {
  artifactsDebugModal.classList.add("hidden");
}

async function loadMessages(cid) {
  return await fetchJsonDebug(`/api/conversation/${cid}/messages`);
}

// #endregion

async function newChat() {
  const res = await fetch("/api/new", { method: "POST" });
  const data = await res.json();
  conversationId = data.conversation_id;
  localStorage.setItem("callie_mvp_conversation_id", conversationId);

  //const conversations = await fetchConversations();
  //renderConversations(conversations);
  await refreshConversationLists();

  clearChat();
  addMsg("assistant", "New chat started.");
  await refreshContext();
}

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
/*
function toggleTopMenu(forceState) {
  if (!topMenu) return;
  const shouldShow = forceState !== undefined
    ? forceState
    : topMenu.classList.contains("hidden");
  if (shouldShow) {
    topMenu.classList.remove("hidden");
  } else {
    topMenu.classList.add("hidden");
  }
}
*/

// #region General Menu / Modal Helpers

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

// #region Chat Meta-Info Helpers

function ensureMetaInfoModal() {
  if (metaInfoModal) return;

  const modal = document.createElement("div");
  modal.id = "metaInfoModal";
  modal.className = "modal hidden";

  modal.innerHTML = `
    <div class="modalBackdrop"></div>
    <div class="modalPanel" style="max-width: 760px;">
      <div class="modalHeader">
        <div class="modalTitle" id="metaInfoTitle">Details</div>
        <button class="btn" id="metaInfoClose">Close</button>
      </div>
      <div class="modalBody">
        <pre id="metaInfoPre" style="white-space: pre-wrap; word-break: break-word; margin: 0;"></pre>
      </div>
      <div class="modalActions">
        <button class="btn" id="metaInfoCopy">Copy JSON</button>
      </div>
    </div>
  `;

  document.body.appendChild(modal);

  metaInfoModal = modal;
  metaInfoTitleEl = modal.querySelector("#metaInfoTitle");
  metaInfoPreEl = modal.querySelector("#metaInfoPre");

  const closeBtn = modal.querySelector("#metaInfoClose");
  const copyBtn = modal.querySelector("#metaInfoCopy");
  const backdrop = modal.querySelector(".modalBackdrop");

  function close() {
    metaInfoModal.classList.add("hidden");
  }

  closeBtn.addEventListener("click", close);
  backdrop.addEventListener("click", close);

  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(metaInfoPreEl.textContent || "");
    } catch (e) {
      console.warn("copy failed", e);
    }
  });
}

function openMetaInfo(title, obj) {
  ensureMetaInfoModal();
  metaInfoTitleEl.textContent = title || "Details";
  metaInfoPreEl.textContent = JSON.stringify(obj || {}, null, 2);
  hideAllTransientUI({ except: [projMenuEl] });
  metaInfoModal.classList.remove("hidden");
}

// #endregion

// #region Debug Helpers

function bootLog(...args) {
  if (UI_CONFIG.debug_boot) console.log(...args);
}

async function fetchJsonDebug(url, opts) {
  bootLog(`[boot] fetch -> ${url}`);
  const res = await fetch(url, opts);

  // Always read text first so we can log it even if it isn't JSON
  const text = await res.text();

  if (!res.ok) {
    console.error(`[api] ${url} -> HTTP ${res.status}`, text.slice(0, 800));
    throw new Error(`HTTP ${res.status} from ${url}: ${text.slice(0, 200)}`);
  }

  if (!text) return null;

  try {
    const data = JSON.parse(text);
    bootLog(`[boot] ok <- ${url}`);
    return data;
  } catch (e) {
    console.error(`[api] ${url} -> non-JSON`, text.slice(0, 800));
    throw new Error(`Non-JSON response from ${url}: ${text.slice(0, 200)}`);
  }
}

// #endregion

// #region Error handling helpers

function isErrorBubble(msg) {
  return (
    (msg && msg.meta && msg.meta.kind === "error") ||
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

// #region Message rendering helpers

// A consistent look/feel for headers above chat messages, with optional timestamps and buttons.
function buildMetaBar({ labelText = null, timeIso = null, includeButton = false, metaObj = null }) {
  const metaBar = document.createElement("div");
  metaBar.className = "abMeta singleMeta";

  const left = document.createElement("div");
  left.className = "abMetaLeft";

  if (labelText) {
    const labelSpan = document.createElement("span");
    labelSpan.className = "abLabel";
    labelSpan.textContent = labelText;
    left.appendChild(labelSpan);
  }

  const timeSpan = document.createElement("span");
  timeSpan.className = "msgTime";
  timeSpan.textContent = timeIso ? formatReadableDateTime(timeIso) : "";
  left.appendChild(timeSpan);

  let useBtn = null;
  if (includeButton) {
    useBtn = document.createElement("button");
    useBtn.className = "abChoose";
    useBtn.textContent = "Use";
    metaBar.appendChild(useBtn);
  }

  let infoBtn = null;
  if (metaObj) {
    infoBtn = document.createElement("button");
    infoBtn.className = "abInfo";
    infoBtn.textContent = "i";
    infoBtn.title = "Details";
    infoBtn.addEventListener("click", () => {
      openMetaInfo(labelText || "Details", metaObj);
    });
    metaBar.appendChild(infoBtn);
  }

  // now stuff in the right bar
  const right = document.createElement("div");
  right.className = "abMetaRight";
  if (useBtn)
    right.appendChild(useBtn);
  if (infoBtn)
    right.appendChild(infoBtn);

  metaBar.appendChild(left);
  metaBar.appendChild(right);

  return { metaBar, timeSpan, useBtn, infoBtn };
}

function addMsgTextOnly(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  chatWindow.appendChild(div);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return div;
}

function escapeHtml(s) {
  if (!s) return "";
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function addAssistantMsgWithModel(modelId, initialText, createdAtIso, metaObj = null) {
  let labelText = "Unknown model";
  if (modelId) {
    const m = findModelById(modelId);
    labelText = m ? m.display_name : modelId;
  }

  // Outer wrapper just groups label + bubble
  const wrapper = document.createElement("div");
  wrapper.className = "msgWithModel assistantWrap";
  // Label bar above the bubble
  const { metaBar } = buildMetaBar({ labelText, timeIso: createdAtIso || null, includeButton: false, metaObj });
  // This is now handled in buildMetaBar
  // const metaBar = document.createElement("div");
  //metaBar.className = "abMeta singleMeta";
  //const labelSpan = document.createElement("span");
  //labelSpan.className = "abLabel";
  //labelSpan.textContent = labelText;
  //metaBar.appendChild(labelSpan);
  wrapper.appendChild(metaBar);

  // Actual chat bubble
  const bubble = document.createElement("div");
  bubble.className = "msg assistant";
  // preserve error color coding
  if (metaObj && metaObj.kind === "error") bubble.classList.add("error");

  const body = document.createElement("div");
  body.className = "msgBody";
  body.innerHTML = renderMarkdown(stripZeit(initialText) || "");

  bubble.appendChild(body);
  wrapper.appendChild(bubble);

  chatWindow.appendChild(wrapper);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  // Streaming code updates the body only
  return body;
}

function addUserMsgWithTime(text, createdAtIso) {
  const wrapper = document.createElement("div");
  wrapper.className = "msgWithModel userWrap";

  const { metaBar } = buildMetaBar({ labelText: null, timeIso: createdAtIso || null, includeButton: false });
  wrapper.appendChild(metaBar);

  const bubble = document.createElement("div");
  bubble.className = "msg user";
  bubble.innerHTML = renderMarkdown(stripZeit(text));

  wrapper.appendChild(bubble);
  chatWindow.appendChild(wrapper);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return bubble;
}

function addMsg(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.innerHTML = renderMarkdown(stripZeit(text));

  chatWindow.appendChild(div);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return div;
}

function clearChat() {
  chatWindow.innerHTML = "";
}

function renderMessagesWithAB(rows) {
  let i = 0;
  while (i < rows.length) {
    const msg = rows[i];
    const meta = msg.meta || {};

    // First try: explicit A/B grouping via meta.ab_group
    const abGroup = meta.ab_group || null;
    if (msg.role === "assistant" && abGroup) {
      const next = rows[i + 1];
      if (
        next &&
        next.role === "assistant" &&
        next.meta &&
        next.meta.ab_group === abGroup
      ) {
        renderABRow(msg, next, meta.canonical, next.meta.canonical);
        i += 2;
        continue;
      }
    }

    // Second try: heuristic repair for legacy rows
    if (msg.role === "assistant") {
      const next = rows[i + 1];
      const prev = rows[i - 1];
      const msgHasNoMeta = !meta || Object.keys(meta).length === 0;

      if (
        msgHasNoMeta &&
        next &&
        next.role === "assistant" &&
        (!next.meta || Object.keys(next.meta).length === 0) &&
        prev &&
        prev.role === "user"
      ) {
        // Treat msg as A, next as B
        renderABRow(
          { ...msg, meta: { ab_group: `rehab-${msg.id}`, canonical: true } },
          { ...next, meta: { ab_group: `rehab-${msg.id}`, canonical: false } },
          true,
          false
        );
        i += 2;
        continue;
      }
    }

    // Fallback: single message (non A/B)
    if (msg.role === "assistant") {
      const meta = msg.meta || {};
      const modelId = meta.model || null;
      addAssistantMsgWithModel(modelId, msg.content || "", msg.created_at || null, msg.meta || null);
    } else if (msg.role === "user") {
      addUserMsgWithTime(msg.content || "", msg.created_at || null);
    } else {
      addMsg(msg.role, msg.content || "");
    }
    i += 1;
  }
}

function renderABRow(msgA, msgB, canonicalA, canonicalB) {
  const modelA = (msgA.meta && msgA.meta.model) || "model A";
  const modelB = (msgB.meta && msgB.meta.model) || "model B";

  const { rowEl, msgAEl, msgBEl, labelAEl, labelBEl, infoAEl, infoBEl } = addABRow(
    modelA, modelB,
    msgA.created_at || null, msgB.created_at || null
  );

  msgAEl.innerHTML = renderMarkdown(stripZeit(msgA.content));
  msgBEl.innerHTML = renderMarkdown(stripZeit(msgB.content));

  if (msgA.meta && msgA.meta.kind === "error") msgAEl.classList.add("error");
  if (msgB.meta && msgB.meta.kind === "error") msgBEl.classList.add("error");

  // Wire info buttons for reload/history
  infoAEl.onclick = () => openMetaInfo(labelAEl.textContent || "A", msgA.meta || {});
  infoBEl.onclick = () => openMetaInfo(labelBEl.textContent || "B", msgB.meta || {});

  if (canonicalA) markCanonical(rowEl, "A");
  else if (canonicalB) markCanonical(rowEl, "B");
}

/*
function renderABRow(msgA, msgB, canonicalA, canonicalB) {
  // Try to get model labels if you’re storing them in meta; otherwise fall back.
  const modelA = (msgA.meta && msgA.meta.model) || "model A";
  const modelB = (msgB.meta && msgB.meta.model) || "model B";
  // Reuse the same builder used for live A/B sends
  const { rowEl, msgAEl, msgBEl } = addABRow(
    modelA, modelB,
    msgA.created_at || null, msgB.created_at || null
  );
  // Fill in the content
  msgAEl.innerHTML = renderMarkdown(stripZeit(msgA.content));
  msgBEl.innerHTML = renderMarkdown(stripZeit(msgB.content));
  // Paint stored error rows red (persist across reload)
  if (msgA.meta && msgA.meta.kind === "error") msgAEl.classList.add("error");
  if (msgB.meta && msgB.meta.kind === "error") msgBEl.classList.add("error");
  // Restore canonical choice if we know it
  if (canonicalA) {
    markCanonical(rowEl, "A");
  } else if (canonicalB) {
    markCanonical(rowEl, "B");
  }
}
*/

function addABRow(modelA, modelB, createdAtIsoA = null, createdAtIsoB = null) {
  const row = document.createElement("div");
  row.className = "abRow";

  const makeCol = (labelText, timeIso) => {
    const meta = document.createElement("div");
    meta.className = "abMeta";

    const left = document.createElement("div");
    left.className = "abMetaLeft";

    const right = document.createElement("div");
    right.className = "abMetaRight";

    const col = document.createElement("div");
    col.className = "abCol";

    const label = document.createElement("span");
    label.className = "abLabel";
    label.textContent = labelText;

    const timeEl = document.createElement("span");
    timeEl.className = "msgTime";
    timeEl.textContent = timeIso ? formatReadableDateTime(timeIso) : "";

    const btn = document.createElement("button");
    btn.className = "abChoose";
    btn.textContent = "Use";

    const info = document.createElement("button");
    info.className = "abInfo";
    info.textContent = "i";
    info.title = "Details";

    left.appendChild(label);
    left.appendChild(timeEl);

    // ✅ cluster buttons together on the right
    right.appendChild(btn);
    right.appendChild(info);

    meta.appendChild(left);
    meta.appendChild(right);

    const msg = document.createElement("div");
    msg.className = "msg assistant abMsg";
    msg.textContent = "Thinking…";

    col.appendChild(meta);
    col.appendChild(msg);

    return { col, meta, label, btn, info, msg, timeEl };
  };

  let safeLabelA = modelA && modelA.trim() ? modelA : "Unknown Model A";
  if (safeLabelA == "model A") safeLabelA = "Unknown Model A";

  let safeLabelB = modelB && modelB.trim() ? modelB : "Unknown Model B";
  if (safeLabelB == "model B") safeLabelB = "Unknown Model B";

  const A = makeCol(safeLabelA, createdAtIsoA);
  const B = makeCol(safeLabelB, createdAtIsoB);

  row.appendChild(A.col);
  row.appendChild(B.col);

  chatWindow.appendChild(row);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  return {
    rowEl: row,
    msgAEl: A.msg,
    msgBEl: B.msg,
    labelAEl: A.label,
    labelBEl: B.label,
    timeAEl: A.timeEl,
    timeBEl: B.timeEl,
    btnAEl: A.btn,
    btnBEl: B.btn,
    infoAEl: A.info,
    infoBEl: B.info,
  };
}

/*
function addABRow(modelA, modelB, createdAtIsoA = null, createdAtIsoB = null) {
  const row = document.createElement("div");
  row.className = "abRow";

  const makeCol = (labelText, timeIso) => {
    const meta = document.createElement("div");
    meta.className = "abMeta";
  
    const left = document.createElement("div");
    left.className = "abMetaLeft";

    const col = document.createElement("div");
    col.className = "abCol";

    const label = document.createElement("span");
    label.className = "abLabel";
    label.textContent = labelText;

    const timeEl = document.createElement("span");
    timeEl.className = "msgTime";
    timeEl.textContent = timeIso ? formatReadableDateTime(timeIso) : "";

    const btn = document.createElement("button");
    btn.className = "abChoose";
    btn.textContent = "Use";

    const info = document.createElement("button");
    info.className = "abInfo";
    info.textContent = "i";
    info.title = "Details";

    left.appendChild(label);
    left.appendChild(timeEl);

    meta.appendChild(left); // left now contains both label and time
    //meta.appendChild(label);
    meta.appendChild(info);
    meta.appendChild(btn);

    const msg = document.createElement("div");
    msg.className = "msg assistant abMsg";
    msg.textContent = "Thinking…";

    col.appendChild(meta);
    col.appendChild(msg);

    return { col, meta, label, btn, info, msg, timeEl };
  };

  let safeLabelA = modelA && modelA.trim() ? modelA : "Unknown Model A";
  if (safeLabelA == "model A") safeLabelA = "Unknown Model A";
  const { col: colA, label: labelA, btn: btnA, info: infoA, msg: msgA, timeEl: timeElA } =
    makeCol(`A · ${safeLabelA}`, createdAtIsoA);
  let safeLabelB = modelB && modelB.trim() ? modelB : "Unknown Model B";
  if (safeLabelB == "model B") safeLabelB = "Unknown Model B";
  const { col: colB, label: labelB, btn: btnB, info: infoB, msg: msgB, timeEl: timeElB } =
    makeCol(`B · ${safeLabelB}`, createdAtIsoB);

  row.appendChild(colA);
  row.appendChild(colB);
  chatEl.appendChild(row);
  chatEl.scrollTop = chatEl.scrollHeight;

  btnA.addEventListener("click", () => chooseCanonical(row, "A"));
  btnB.addEventListener("click", () => chooseCanonical(row, "B"));

  return { rowEl: row, msgAEl: msgA, msgBEl: msgB, labelAEl: labelA, labelBEl: labelB, timeAEl: timeElA, timeBEl: timeElB, infoAEl: infoA, infoBEl: infoB };
}
*/

// #endregion

// #region Markdown rendering helpers

// helper: process blockquotes with > and nested >>, >>> etc.
function applyBlockquotes(t) {
  const lines = t.split("\n");
  let result = [];
  let openLevel = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // after escapeHtml, '>' is now '&gt;'
    const m = line.match(/^((?:&gt;)+)\s?(.*)$/);
    if (m) {
      const markers = m[1];
      const content = m[2] || "";
      const level = (markers.match(/&gt;/g) || []).length;

      // open new levels
      while (openLevel < level) {
        result.push("<blockquote>");
        openLevel++;
      }
      // close levels if we decreased
      while (openLevel > level) {
        result.push("</blockquote>");
        openLevel--;
      }

      result.push(content || "");
    } else {
      // if we hit a normal line and we had open quotes, close them
      if (openLevel > 0 && line.trim() === "") {
        while (openLevel > 0) {
          result.push("</blockquote>");
          openLevel--;
        }
        // keep the blank separator
        result.push("");
      } else {
        result.push(line);
      }
    }
  }

  // close any still-open blockquotes
  while (openLevel > 0) {
    result.push("</blockquote>");
    openLevel--;
  }

  return result.join("\n");
}

// helper: process simple tables with | col | col |
function applyTables(t) {
  const lines = t.split("\n");
  let out = [];
  let i = 0;

  const isTableLine = (line) =>
    /^\s*\|.*\|\s*$/.test(line);

  const isDividerLine = (line) =>
    /^\s*\|?\s*[:\- ]+\|\s*[:\-\| ]*\s*$/.test(line);

  while (i < lines.length) {
    if (!isTableLine(lines[i])) {
      out.push(lines[i]);
      i++;
      continue;
    }

    // collect contiguous table lines
    const tableLines = [];
    while (i < lines.length && isTableLine(lines[i])) {
      tableLines.push(lines[i].trim());
      i++;
    }

    if (!tableLines.length) continue;

    let headerCells = null;
    let dataLines = tableLines;

    // support optional alignment divider: header, divider, rows...
    if (tableLines.length >= 2 && isDividerLine(tableLines[1])) {
      const headerLine = tableLines[0];
      headerCells = headerLine
        .replace(/^\s*\|/, "")
        .replace(/\|\s*$/, "")
        .split("|")
        .map((c) => c.trim());
      dataLines = tableLines.slice(2);
    }

    const rows = dataLines.map((line) =>
      line
        .replace(/^\s*\|/, "")
        .replace(/\|\s*$/, "")
        .split("|")
        .map((c) => c.trim())
    );

    let html = '<table class="mdTable">';

    if (headerCells) {
      html += "<thead><tr>";
      for (const cell of headerCells) {
        html += `<th>${cell}</th>`;
      }
      html += "</tr></thead>";
    }

    if (rows.length) {
      html += "<tbody>";
      for (const row of rows) {
        html += "<tr>";
        for (const cell of row) {
          html += `<td>${cell}</td>`;
        }
        html += "</tr>";
      }
      html += "</tbody>";
    }

    html += "</table>";

    out.push(html);
  }

  return out.join("\n");
}

// very simple markdown-ish renderer: headers, bold, italics, lists, code fences, newlines
function renderMarkdown(text) {
  if (!text) return "";

  let s = String(text);

  // Handle fenced code blocks first: ```...```
  const segments = s.split("```");
  let html = "";

  for (let i = 0; i < segments.length; i++) {
    const part = segments[i];
    if (i % 2 === 1) {
      // inside ```
      const code = escapeHtml(part.trim());
      html += `<pre><code>${code}</code></pre>`;
    } else {
      // outside code fences – basic markdown
      let t = escapeHtml(part);

      // Horizontal rule: line that's just ---
      t = t.replace(/^---\s*$/gm, "<hr>");

      // headers (very basic)
      t = t.replace(/^###### (.*)$/gm, "<h6>$1</h6>");
      t = t.replace(/^##### (.*)$/gm, "<h5>$1</h5>");
      t = t.replace(/^#### (.*)$/gm, "<h4>$1</h4>");
      t = t.replace(/^### (.*)$/gm, "<h3>$1</h3>");
      t = t.replace(/^## (.*)$/gm, "<h2>$1</h2>");
      t = t.replace(/^# (.*)$/gm, "<h1>$1</h1>");

      // bold and italics (naive but good enough for chat)
      t = t.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      t = t.replace(/__(.+?)__/g, "<strong>$1</strong>");
      t = t.replace(/\*(.+?)\*/g, "<em>$1</em>");
      t = t.replace(/_(.+?)_/g, "<em>$1</em>");

      // Strikethrough: ~~text~~
      t = t.replace(/~~(.+?)~~/g, "<del>$1</del>");

      // Links: [text](https://example.com)
      // Only allow http/https, keep it simple and safe-ish.
      t = t.replace(
        /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        (match, label, url) => {
          const safeUrl = url
            .replace(/"/g, "&quot;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
          return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${label}</a>`;
        }
      );

      // unordered lists
      t = t.replace(/^(?:[-*] )(.+)$/gm, "<li>$1</li>");
      t = t.replace(/(<li>[\s\S]+?<\/li>)/gm, "<ul>$1</ul>");

      // Blockquotes: handle > and nested >>, >>>…
      t = applyBlockquotes(t);

      // Tables: | A | B | style
      t = applyTables(t);

      // line breaks / paragraphs
      t = t
        .replace(/\r\n/g, "\n")
        .split("\n\n")
        .map(p => p.split("\n").join("<br>"))
        .join("<br><br>");

      html += t;
    }
  }

  return html;
}

// #endregion

// #region Conversation list helpers

function nowIso() { return new Date().toISOString(); }

// Create a conversation list item element to be used in the sidebar, with click and context menu handlers.
function makeConversationItem(c) {
  const item = document.createElement("div");
  item.className = "convItem" + (c.id === conversationId ? " active" : "");
  item.dataset.id = c.id;

  const t = document.createElement("div");
  t.className = "convTitle";
  t.textContent = c.title || "New chat";
  item.appendChild(t);

  const m = document.createElement("div");
  m.className = "convMeta";
  m.textContent = formatReadableDateTime(c.created_at); //convMetaText(c);
  // You can swap created_at for updated_at later if you add it to the API.
  item.appendChild(m);

  if (c.summary_excerpt) {
    const s = document.createElement("div");
    s.className = "convSummary";
    s.textContent = c.summary_excerpt;
    item.appendChild(s);
  }

  item.addEventListener("click", () => selectConversation(c.id));
  item.addEventListener("contextmenu", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    showConvMenu(ev, c.id);
  });

  return item;
}

async function fetchConversations() {
  const list = await fetchJsonDebug("/api/conversations");
  conversationMap = new Map(list.map(x => [x.id, x]));
  return list;
}

function renderConversations(conversations) {
  sideBarConvListEl.innerHTML = "";

  const unassigned = (conversations || []).filter(c => c.project_id == null);

  unassigned.forEach(c => {
    sideBarConvListEl.appendChild(makeConversationItem(c));
  });

  updateChatTitle();
}

function updateChatTitle() {
  const meta = conversationMap.get(conversationId);
  topBarChatTitleEl.textContent = meta?.title || "…";
}

async function selectConversation(cid) {
  const previousCid = conversationId;

  cancelScheduledContextRefresh();
  cancelScheduledTranscriptRefresh();

  if (previousCid && previousCid !== cid) {
    // best-effort flush of old conversation transcript before switching away
    void flushConversationTranscriptArtifact(previousCid, "switch");
  }

  conversationId = cid;
  localStorage.setItem("callie_mvp_conversation_id", conversationId);

  await refreshConversationLists();

  clearChat();

  const msgs = await loadMessages(cid);
  if (!msgs.length) {
    addMsg("assistant", "Empty chat. Say something mean to the void.");
  } else {
    renderMessagesWithAB(msgs);
  }

  await refreshContext();

  // start a new transcript idle timer for the newly selected conversation
  scheduleTranscriptRefresh(cid);
}

// Updated version includes transcript regen logic
/*
async function selectConversation(cid) {
  conversationId = cid;
  localStorage.setItem("callie_mvp_conversation_id", conversationId);

  //const conversations = await fetchConversations();
  //renderConversations(conversations);
  await refreshConversationLists();
  
  clearChat();

  const msgs = await loadMessages(cid); // now returns raw with meta
  if (!msgs.length) {
    addMsg("assistant", "Empty chat. Say something mean to the void.");
  } else {
    renderMessagesWithAB(msgs);
  }

  await refreshContext();
}
*/

// #endregion

// #region Advanced mode (AB) helpers

function bindModelSelect() {
  const selA = document.getElementById("modelSelectA");
  const selB = document.getElementById("modelSelectB");

  if (selA) {
    selA.addEventListener("change", () => {
      localStorage.setItem("chatoss.modelA", selA.value);
      updateModelInfo("A");
      applyAdvancedVisibility();
    });
  }

  if (selB) {
    selB.addEventListener("change", () => {
      localStorage.setItem("chatoss.modelB", selB.value);
      updateModelInfo("B");
      applyAdvancedVisibility();
    });
  }
}

function markCanonical(rowEl, slot) {
  const cols = rowEl.querySelectorAll(".abCol");
  cols.forEach(c => c.classList.remove("abCanonical"));
  const idx = slot === "B" ? 1 : 0;
  if (cols[idx]) cols[idx].classList.add("abCanonical");
}

async function chooseCanonical(rowEl, slot) {
  const abGroup = rowEl.dataset.abGroup;
  if (!conversationId || !abGroup) {
    // No backend metadata? Just visually toggle.
    markCanonical(rowEl, slot);
    return;
  }

  try {
    await fetch("/api/ab/canonical", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: conversationId,
        ab_group: abGroup,
        slot
      })
    });
  } catch (e) {
    console.error("Failed to set canonical A/B", e);
  }

  markCanonical(rowEl, slot);
  await refreshContext();
}

// Show/hide model B dropdown
function applyAdvancedVisibility() {
  const show = !!advancedMode;
  const advancedBlock = document.getElementById("advancedModelB");
  if (advancedBlock) {
    advancedBlock.style.display = show ? "" : "none";
  }
  // Anything with the advancedOnly class
  const advancedBits = document.querySelectorAll(".advancedOnly");
  advancedBits.forEach(el => {
    el.style.display = show ? "" : "none";
  });
}

// #endregion

// #region Context helpers

function allContextSectionsExpanded() {
  return Object.values(contextSectionState).every(Boolean);
}

function updateContextToggleButton() {
  if (!contextPreviewToggleBtn) return;
  contextPreviewToggleBtn.textContent = allContextSectionsExpanded() ? "Collapse all" : "Expand all";
}

function persistContextSectionState() {
  try {
    localStorage.setItem(CONTEXT_SECTION_STATE_KEY, JSON.stringify(contextSectionState));
  } catch {
    // TODO should we log it?
  }
}

function createCtxPre(text) {
  const pre = document.createElement("pre");
  pre.className = "ctxPre";
  pre.textContent = text || "(none)";
  return pre;
}

function createCtxEmpty(text = "(none)") {
  const div = document.createElement("div");
  div.className = "ctxEmpty";
  div.textContent = text;
  return div;
}

function createCtxList(items, emptyText = "(none)") {
  if (!items || !items.length) return createCtxEmpty(emptyText);

  const ul = document.createElement("ul");
  ul.className = "ctxList";
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    ul.appendChild(li);
  }
  return ul;
}

function createCtxSubBlock(title, node) {
  const wrap = document.createElement("div");
  wrap.className = "ctxSubBlock";

  const hdr = document.createElement("div");
  hdr.className = "ctxSubTitle";
  hdr.textContent = title;

  wrap.appendChild(hdr);
  wrap.appendChild(node);
  return wrap;
}

function createCtxSection(key, title, bodyNode, summary = "") {
  const section = document.createElement("section");
  section.className = "ctxSection";
  if (!contextSectionState[key]) section.classList.add("collapsed");

  const header = document.createElement("button");
  header.type = "button";
  header.className = "ctxSectionHeader";

  const left = document.createElement("div");
  left.className = "ctxSectionHeaderLeft";

  const caret = document.createElement("span");
  caret.className = "ctxSectionCaret";
  caret.textContent = contextSectionState[key] ? "▾" : "▸";

  const titleEl = document.createElement("span");
  titleEl.className = "ctxSectionTitle";
  titleEl.textContent = title;

  left.appendChild(caret);
  left.appendChild(titleEl);

  header.appendChild(left);

  if (summary) {
    const summaryEl = document.createElement("span");
    summaryEl.className = "ctxSectionSummary";
    summaryEl.innerHTML = summary.replace("\n", "<br />");
    header.appendChild(summaryEl);
  }

  const body = document.createElement("div");
  body.className = "ctxSectionBody";
  body.appendChild(bodyNode);

  header.addEventListener("click", () => {
    contextSectionState[key] = !contextSectionState[key];
    persistContextSectionState();
    if (lastRenderedContext) renderContext(lastRenderedContext);
  });
  /*
  header.addEventListener("click", () => {
    contextSectionState[key] = !contextSectionState[key];
    if (lastRenderedContext) renderContext(lastRenderedContext);
  });
  */

  section.appendChild(header);
  section.appendChild(body);
  return section;
}

function formatLlmMessageContent(content) {
  if (typeof content === "string") {
    return content;
  }
  try {
    return JSON.stringify(content, null, 2);
  } catch {
    return String(content);
  }
}

function summarizeLlmMessage(content) {
  const raw = typeof content === "string"
    ? content
    : (() => {
        try {
          return JSON.stringify(content);
        } catch {
          return String(content);
        }
      })();

  const oneLine = String(raw || "").replace(/\s+/g, " ").trim();
  if (!oneLine) return "(empty)";
  return oneLine.length > 120 ? `${oneLine.slice(0, 117)}...` : oneLine;
}

function createCtxMessageSection(idx, msg) {
  const key = String(idx);
  const isOpen = !!contextPayloadMessageState[key];

  const section = document.createElement("div");
  section.className = "ctxMsgSection";
  if (!isOpen) section.classList.add("collapsed");

  const header = document.createElement("button");
  header.type = "button";
  header.className = "ctxMsgHeader";

  const left = document.createElement("div");
  left.className = "ctxMsgHeaderLeft";

  const caret = document.createElement("span");
  caret.className = "ctxMsgCaret";
  caret.textContent = isOpen ? "▾" : "▸";

  const title = document.createElement("span");
  title.className = "ctxMsgTitle";
  title.textContent = `#${idx + 1} ${String(msg?.role || "unknown").toUpperCase()}`;

  left.appendChild(caret);
  left.appendChild(title);
  header.appendChild(left);

  const summary = document.createElement("span");
  summary.className = "ctxMsgSummary";
  summary.textContent = summarizeLlmMessage(msg?.content);
  header.appendChild(summary);

  const body = document.createElement("div");
  body.className = "ctxMsgBody";
  body.appendChild(createCtxPre(formatLlmMessageContent(msg?.content)));

  header.addEventListener("click", () => {
    contextPayloadMessageState[key] = !contextPayloadMessageState[key];
    if (lastRenderedContext) renderContext(lastRenderedContext);
  });

  section.appendChild(header);
  section.appendChild(body);
  return section;
}

async function fetchContext(cid, previewLimit = 20, userText = "") {
  const qs = new URLSearchParams();
  qs.set("preview_limit", String(previewLimit));
  if (userText && userText.trim()) {
    qs.set("user_text", userText);
  }
  return await fetchJsonDebug(`/api/conversation/${cid}/context?${qs.toString()}`);
}

function renderContext(ctx) {
  lastRenderedContext = ctx;

  if (!contextPreviewEl) return;
  contextPreviewEl.innerHTML = "";

  const total = ctx.assembled_input_count || 0;
  const previewLimit = ctx.assembled_input_preview_limit ?? 20;
  const truncated = !!ctx.assembled_input_preview_truncated;

  const stats = ctx.token_stats || {};
  const approxTokens = stats.approx_text_tokens ?? 0;
  const numImages = stats.num_images ?? 0;
  const totalChars = stats.total_chars ?? 0;

  const projectName = ctx.project_name || "";
  const projectId = ctx.project_id ?? null;

  const hasDraft = !!ctx.has_user_text;
  const fileIncludeActive = !!ctx.file_include;
  const memoryIncludeActive = !!ctx.memory_include;
  const chatIncludeActive = !!ctx.chat_include;
  const ftsActive = !!ctx.fts_rag_active;
  const vectorActive = !!ctx.vector_rag_active;

  const queryInclude = ctx.query_include || "";
  const queryExpand = ctx.query_expand_results || "";

  const scopedFiles = ctx.scoped_files || [];
  const includedFiles = ctx.included_file_labels || [];
  const includedMemories = ctx.included_memory_labels || [];
  const includedChatSummaries = ctx.included_chat_summary_labels || [];
  const includedChats = ctx.included_chat_labels || [];
  const expansionCandidates = ctx.expansion_candidates || [];

  const rawRows = ctx.retrieved_chunks_raw || [];
  const finalRows = ctx.retrieved_chunks_final || ctx.retrieved_chunk_meta || [];
  const suppressedIncluded = (ctx.retrieval_debug?.suppressed_included_artifact_rows || []).length;
  const suppressedExpanded = (ctx.retrieval_debug?.suppressed_expanded_artifact_rows || []).length;
  const expandedCount = (ctx.expanded_artifact_ids || []).length;
  const llmInputMessages = ctx.llm_input_messages || [];
  const nextPayloadState = {};
  for (let i = 0; i < llmInputMessages.length; i++) {
    nextPayloadState[String(i)] = !!contextPayloadMessageState[String(i)];
  }
  contextPayloadMessageState = nextPayloadState;

  const accordion = document.createElement("div");
  accordion.className = "ctxAccordion";

  // Scope & Query
  {
    const lines = [];
    if (contextRefreshing) {
      lines.push("[updating context preview...]");
      lines.push("");
    }

    lines.push(`Conversation: ${ctx.conversation_id}`);
    if (projectId !== null || projectName) {
      lines.push(`Project: ${projectName || "(unnamed project)"}${projectId !== null ? ` [${projectId}]` : ""}`);
    } else {
      lines.push("Project: (none)");
    }

    lines.push("");
    lines.push(`Include: ${queryInclude || "(none)"}`);
    lines.push(`Expand results: ${queryExpand || "(none)"}`);
    lines.push(
      `Caps: files=${ctx.query_max_full_files ?? "?"}, memories=${ctx.query_max_full_memories ?? "?"}, chats=${ctx.query_max_full_chats ?? "?"}`
    );
    lines.push(`Expand threshold: min artifact hits=${ctx.query_expand_min_artifact_hits ?? "?"}`);

    if (!hasDraft) {
      lines.push("Status: idle (no draft text, so retrieval/inclusion is not running)");
    } else {
      const activeParts = [];
      if (fileIncludeActive) activeParts.push("full-file inclusion");
      if (memoryIncludeActive) activeParts.push("full-memory inclusion");
      if (chatIncludeActive) activeParts.push("full-chat inclusion");
      if (ftsActive) activeParts.push("FTS");
      if (vectorActive) activeParts.push("vector");
      if (!activeParts.length) activeParts.push("no active retrieval path");
      lines.push(`Active: ${activeParts.join("; ")}`);
    }

    lines.push("");
    // lines.push(`Included chat summaries: ${includedChatSummaries.length}`);
    lines.push(`Assembled messages: ${total}`);
    lines.push(`Recent history preview limit: ${previewLimit}${truncated ? " (truncated)" : ""}`);
    lines.push(`Context load: ~${approxTokens} text tokens*; ${totalChars} characters; ${numImages} images`);
    lines.push("*Token and character counts are approximate.");
    
    accordion.appendChild(
      createCtxSection(
        "scopeQuery",
        "Scope & Query",
        createCtxPre(lines.join("\n")),
        `msgs=${total} · raw=${rawRows.length} · final=${finalRows.length}`
      )
    );
  }

  // Prompt Layers
  {
    const wrap = document.createElement("div");
    wrap.appendChild(
      createCtxSubBlock(
        "System Text",
        createCtxPre(ctx.system_text || ctx.effective_system_prompt || "(none)")
      )
    );
    wrap.appendChild(
      createCtxSubBlock(
        "Conversation Summary",
        createCtxPre((ctx.summary || "").trim() || "(none)")
      )
    );

    accordion.appendChild(
      createCtxSection(
        "promptLayers",
        "Prompt Layers",
        wrap,
        `${(ctx.personalization_blocks || []).length} personalization block(s)`
      )
    );
  }

  // Whole Assets Included
  {
    const wrap = document.createElement("div");

    const scopedFileItems = scopedFiles.map((f) => {
      const name = f.name || "(unnamed file)";
      const scope =
        f.scope_type === "conversation"
          ? `conversation:${f.scope_uuid || "?"}`
          : f.scope_type === "project"
          ? `project:${f.scope_id ?? "?"}`
          : (f.scope_type || "global");
      return `${name} [${scope}]`;
    });

    wrap.appendChild(createCtxSubBlock("Scoped Files", createCtxList(scopedFileItems)));
    wrap.appendChild(createCtxSubBlock("Included Files", createCtxList(includedFiles)));
    wrap.appendChild(createCtxSubBlock("Included Memories", createCtxList(includedMemories)));
    wrap.appendChild(createCtxSubBlock("Included Chat Summaries", createCtxList(includedChatSummaries)));
    wrap.appendChild(createCtxSubBlock("Included Chats", createCtxList(includedChats)));

    accordion.appendChild(
      createCtxSection(
        "wholeAssets",
        "Whole Assets Included",
        wrap,
        `files=${includedFiles.length} · memories=${includedMemories.length} \n summaries=${includedChatSummaries.length} · chats=${includedChats.length}`
      )
    );
  }

  // RAG Raw Hits
  {
    const lines = [];
    if (rawRows.length) {
      for (const r of rawRows.slice(0, 50)) {
        const src = r.filename || r.scope_key || r.source_kind || "source";
        lines.push(
          `- ${src}#${r.chunk_index} chunk_id=${r.chunk_id} artifact_id=${r.artifact_id} file_id=${r.file_id || ""} score=${r.score}`
        );
        if (r.conversation_title || r.conversation_summary_excerpt || r.conversation_started_at || r.conversation_ended_at) {
          const range =
            (r.conversation_started_at || r.conversation_ended_at)
              ? `${r.conversation_started_at || "?"} → ${r.conversation_ended_at || "?"}`
              : "";
          if (r.conversation_title) lines.push(`  chat: ${r.conversation_title}`);
          if (range) lines.push(`  range: ${range}`);
          if (r.conversation_summary_excerpt) lines.push(`  summary: ${r.conversation_summary_excerpt}`);
        }
      }
    } else {
      lines.push(!hasDraft && !lastContextQueryText
        ? "Enter a draft message to run retrieval and inclusion diagnostics."
        : "(none)");
      //lines.push("(none)");
    }

    accordion.appendChild(
      createCtxSection(
        "ragRaw",
        "RAG Raw Hits",
        createCtxPre(lines.join("\n")),
        //`${rawRows.length} raw hit(s)`
        `${rawRows.length} raw hit(s) across retrieval`
      )
    );
  }

  // RAG Final Hits
  {
    const lines = [];
    if (finalRows.length) {
      for (const r of finalRows) {
        const src = r.filename || r.scope_key || r.source_kind || "source";
        const ts = r.artifact_updated_at || r.file_updated_at || r.file_created_at || "";
        const snippetRaw = r.preview_text || r.text || "";
        const snippet = snippetRaw.length > 900
          ? `${snippetRaw.slice(0, 900)}\n[...truncated for preview...]`
          : snippetRaw;

        lines.push(`- ${src}#${r.chunk_index} chunk_id=${r.chunk_id} score=${r.score} ts=${ts}`);
        if (r.conversation_title || r.conversation_summary_excerpt || r.conversation_started_at || r.conversation_ended_at) {
          const range =
            (r.conversation_started_at || r.conversation_ended_at)
              ? `${r.conversation_started_at || "?"} → ${r.conversation_ended_at || "?"}`
              : "";
          if (r.conversation_title) lines.push(`  chat: ${r.conversation_title}`);
          if (range) lines.push(`  range: ${range}`);
          if (r.conversation_summary_excerpt) lines.push(`  summary: ${r.conversation_summary_excerpt}`);
        }
        if (snippet) lines.push(snippet);
        lines.push("");
      }
    } else {
      lines.push(!hasDraft && !lastContextQueryText
        ? "Enter a draft message to run retrieval and inclusion diagnostics."
        : "(none)");
      //lines.push("(none)");
    }

    accordion.appendChild(
      createCtxSection(
        "ragFinal",
        "RAG Final Hits",
        createCtxPre(lines.join("\n")),
        //`${finalRows.length} hit(s)`
        `${finalRows.length} final · ${suppressedIncluded} suppressed(included) \n ${suppressedExpanded} suppressed(expanded)`
      )
    );
  }

  // RAG Expansion Results
  {
    const items = expansionCandidates.map((item) => {
      const label =
        item.kind === "FILE"
          ? (item.filename || item.artifact_title || item.artifact_id)
          : item.kind === "MEMORY"
          ? (item.artifact_title || item.artifact_id)
          : (() => {
              const base = item.conversation_title || item.artifact_title || item.artifact_id;
              const range =
                (item.conversation_started_at || item.conversation_ended_at)
                  ? ` [${item.conversation_started_at || "?"} → ${item.conversation_ended_at || "?"}]`
                  : "";
              return `${base}${range}`;
            })();
      /*
      const label =
        item.kind === "FILE"
          ? (item.filename || item.artifact_title || item.artifact_id)
          : item.kind === "MEMORY"
          ? (item.artifact_title || item.artifact_id)
          : (item.conversation_title || item.artifact_title || item.artifact_id);
      */
      return `${item.kind}: ${label} (raw hits=${item.raw_hit_count}, score=${item.score})`;
    });

    accordion.appendChild(
      createCtxSection(
        "expansion",
        "RAG Expansion Candidates",
        createCtxList(items),
        //`${expansionCandidates.length} candidate(s)`
        `${expansionCandidates.length} candidate(s) · ${expandedCount} expanded`
      )
    );
  }

  // Recent Conversation Context
  {
    const lines = [];
    const preview = ctx.recent_history_preview || [];
    if (preview.length) {
      for (const m of preview) {
        lines.push(`${(m.role || "??").toUpperCase()}: ${m.content || ""}`);
        lines.push("");
      }
    } else {
      lines.push("(none)");
    }

    accordion.appendChild(
      createCtxSection(
        "recentContext",
        "Recent Conversation Context",
        createCtxPre(lines.join("\n")),
        `${(ctx.recent_history_preview || []).length} message(s)`
      )
    );
  }

  // Exact LLM payload
  {
    const wrap = document.createElement("div");
    const nested = document.createElement("div");
    nested.className = "ctxNestedAccordion";

    if (llmInputMessages.length) {
      llmInputMessages.forEach((msg, idx) => {
        nested.appendChild(createCtxMessageSection(idx, msg));
      });
    } else {
      nested.appendChild(createCtxEmpty("(none)"));
    }

    wrap.appendChild(nested);

    accordion.appendChild(
      createCtxSection(
        "llmPayload",
        "Exact LLM Payload",
        wrap,
        `${llmInputMessages.length} message(s)`
      )
    );
  }  

  contextPreviewEl.appendChild(accordion);
  updateContextToggleButton();
}

async function refreshContext(draftOverride = null) {
  if (!conversationId) return;
  const limit = contextExpanded ? UI_CONFIG.context_preview_limit_max : UI_CONFIG.context_preview_limit_min;

  const liveDraft = (chatWindowInputTextbox?.value || "").trim();
  const effectiveDraft =
    draftOverride !== null
      ? String(draftOverride || "").trim()
      : (liveDraft || lastContextQueryText || "");

  setContextRefreshing(true);
  try {
    const ctx = await fetchContext(conversationId, limit, effectiveDraft);
    setContextRefreshing(false);
    renderContext(ctx);
    updateContextToggleButton();
  } catch (e) {
    console.error("refreshContext failed", e);
    setContextRefreshing(false);
    if (contextPreviewEl) {
      contextPreviewEl.textContent = `Context refresh failed: ${e?.message || e}`;
    }
  } finally {
    setContextRefreshing(false);
  }
}
/*
async function refreshContext() {
  if (!conversationId) return;
  const limit = contextExpanded ? UI_CONFIG.context_preview_limit_max : UI_CONFIG.context_preview_limit_min;
  const draft = (chatWindowInputTextbox?.value || "").trim();

  setContextRefreshing(true);
  try {
    const ctx = await fetchContext(conversationId, limit, draft);
    setContextRefreshing(false);
    renderContext(ctx);
    updateContextToggleButton();
    //contextPreviewToggleBtn.textContent = contextExpanded ? "Show less" : "Show more";
  } catch (e) {
    console.error("refreshContext failed", e);
    setContextRefreshing(false);
    if (contextPreviewEl) {
      contextPreviewEl.textContent = `Context refresh failed: ${e?.message || e}`;
    }
  } finally {
    setContextRefreshing(false);
  }
}
*/

// #endregion

// #region Sending messages

async function send() {
  const text = chatWindowInputTextbox.value.trim();
  if (!text) return;
  chatWindowInputTextbox.value = "";
  // Reset the RAG timer
  cancelScheduledContextRefresh();
  lastContextDraftSent = "";

  // Base model from A
  const modelA = topBarModelSelectA?.value || null;
  let modelB = modelA;
  // If B is visible and has a value, use it
  if (topBarModelSelectB && topBarModelSelectB.style.display !== "none") {
    const v = (topBarModelSelectB.value || "").trim();
    if (v) modelB = v;
  }

  const mA = findModelById(topBarModelSelectA.value);
  const metaA = {
    ab_group: "A",
    canonical: true,
    model: mA ? mA.display_name : topBarModelSelectA.value
  };
  const mB = findModelById(topBarModelSelectB.value);
  const metaB = {
    ab_group: "B",
    canonical: false,
    model: mB ? mB.display_name : topBarModelSelectB.value
  };

  const useAB =
    typeof advancedMode !== "undefined" &&
    advancedMode &&
    topBarModelSelectB &&
    topBarModelSelectB.style.display !== "none" &&
    modelA && modelB &&
    modelA !== modelB;

  if (useAB) {
    await sendAB(text, modelA, modelB);
  } else {
    await sendSingle(text, modelA);
  }
}

async function sendSingle(text, model) {
  const now = nowIso();
  addUserMsgWithTime(text, now); //addMsg("user", text);
  // build an assistant message shell with model label
  const assistantBody = addAssistantMsgWithModel(model, "Thinking…", now);

  const request_body = JSON.stringify({
    conversation_id: conversationId,
    model: model,
    message: text
  });

  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: request_body
  });

  const headerCid = res.headers.get("X-Conversation-Id");
  if (headerCid) {
    conversationId = headerCid;
    localStorage.setItem("callie_mvp_conversation_id", conversationId);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");

  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    assistantBody.innerHTML = renderMarkdown(stripZeit(buffer));
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  //const conversations = await fetchConversations();
  //renderConversations(conversations);
  await refreshConversationLists();
  lastContextQueryText = text;
  await refreshContext();
  scheduleTranscriptRefresh();
}

async function sendAB(text, modelA, modelB) {
  const now = nowIso();
  addUserMsgWithTime(text, now);

  const { rowEl, msgAEl, msgBEl, labelAEl, labelBEl, infoAEl, infoBEl } = addABRow(
    modelA, modelB, now, now
  );

  // These will be updated after the server returns.
  let detailsA = { pending: true, slot: "A", model: modelA };
  let detailsB = { pending: true, slot: "B", model: modelB };

  infoAEl.onclick = () => openMetaInfo(labelAEl.textContent || "A", detailsA);
  infoBEl.onclick = () => openMetaInfo(labelBEl.textContent || "B", detailsB);

  function renderSlot(msgEl, slotLabelEl, slotName, slotModel, slotData) {
    msgEl.classList.remove("error");

    if (!slotData) {
      msgEl.textContent = "(empty)";
      return;
    }

    if (slotData.ok) {
      const t = stripZeit(slotData.text || "") || "(empty)";
      msgEl.innerHTML = renderMarkdown(t);
      if (slotModel) slotLabelEl.textContent = `${slotName} · ${slotModel}`;
      return;
    }

    msgEl.classList.add("error");

    const err = slotData.error || {};
    const status = err.status_code || "";
    const reqId = err.request_id || "";
    const body = err.body || {};
    const msg =
      (body.error && body.error.message) ||
      body.message ||
      "OpenAI API error";

    const lines = [];
    lines.push(`**${slotName} error** (HTTP ${status || "?"})`);
    if (reqId) lines.push(`request_id: \`${reqId}\``);
    lines.push(msg);

    msgEl.innerHTML = renderMarkdown(lines.join("\n\n"));
    if (slotModel) slotLabelEl.textContent = `${slotName} · ${slotModel}`;
  }

  const payload = {
    conversation_id: conversationId,
    model_a: modelA,
    model_b: modelB,
    message: text
  };

  try {
    const res = await fetch("/api/chat_ab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (data.conversation_id) {
      conversationId = data.conversation_id;
      localStorage.setItem("callie_mvp_conversation_id", conversationId);
    }

    rowEl.dataset.abGroup = data.ab_group || "";

    renderSlot(msgAEl, labelAEl, "A", data.model_a || modelA, data.a);
    renderSlot(msgBEl, labelBEl, "B", data.model_b || modelB, data.b);

    // Update the info payloads AFTER we have data
    detailsA = { slot: "A", model: data.model_a || modelA, ab_group: data.ab_group || null, result: data.a };
    detailsB = { slot: "B", model: data.model_b || modelB, ab_group: data.ab_group || null, result: data.b };

    markCanonical(rowEl, data.canonical_slot || "A");

    await refreshConversationLists();
    lastContextQueryText = text;
    await refreshContext();
    scheduleTranscriptRefresh();
  } catch (e) {
    console.error("Failed A/B send", e);
    msgAEl.classList.add("error");
    msgBEl.classList.add("error");
    msgAEl.textContent = "[A] error during A/B call";
    msgBEl.textContent = "[B] error during A/B call";
  }
}

/*
async function sendAB(text, modelA, modelB) {
  const now = nowIso();
  addUserMsgWithTime(text, now);

  const { rowEl, msgAEl, msgBEl, labelAEl, labelBEl, timeAEl, timeBEl, infoAEl, infoBEl } = addABRow(
    modelA,
    modelB,
    now,
    now
  );

  infoAEl.onclick = () => openMetaInfo(`A · ${data.model_a || modelA}`, data.a);
  infoBEl.onclick = () => openMetaInfo(`B · ${data.model_b || modelB}`, data.b);

  // helper to render one slot (A or B)
  function renderSlot(msgEl, slotLabelEl, slotName, slotModel, slotData) {
    // Reset styles
    msgEl.classList.remove("error");

    if (!slotData) {
      msgEl.textContent = "(empty)";
      return;
    }

    // slotData shape: {ok:true,text:"..."} OR {ok:false,error:{status_code, request_id, body}}
    if (slotData.ok) {
      const t = stripZeit(slotData.text || "") || "(empty)";
      msgEl.innerHTML = renderMarkdown(t);
      if (slotModel) slotLabelEl.textContent = `${slotName} · ${slotModel}`;
      return;
    }

    // Error case
    msgEl.classList.add("error");

    const err = slotData.error || {};
    const status = err.status_code || "";
    const reqId = err.request_id || "";
    const body = err.body || {};
    const msg =
      (body.error && body.error.message) ||
      body.message ||
      "OpenAI API error";

    // Render error text as markdown-safe plaintext
    const lines = [];
    lines.push(`**${slotName} error** (HTTP ${status || "?"})`);
    if (reqId) lines.push(`request_id: \`${reqId}\``);
    lines.push(msg);

    msgEl.innerHTML = renderMarkdown(lines.join("\n\n"));
    if (slotModel) slotLabelEl.textContent = `${slotName} · ${slotModel}`;
  }

  const payload = {
    conversation_id: conversationId,
    model_a: modelA,
    model_b: modelB,
    message: text
  };

  try {
    const res = await fetch("/api/chat_ab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (data.conversation_id) {
      conversationId = data.conversation_id;
      localStorage.setItem("callie_mvp_conversation_id", conversationId);
    }

    rowEl.dataset.abGroup = data.ab_group || "";

    // Data now returns structured a/b objects
    renderSlot(msgAEl, labelAEl, "A", data.model_a || modelA, data.a);
    renderSlot(msgBEl, labelBEl, "B", data.model_b || modelB, data.b);

    // canonical_slot might not exist anymore; keep old behavior defaulting to A
    markCanonical(rowEl, data.canonical_slot || "A");

    await refreshConversationLists();
    await refreshContext();
  } catch (e) {
    console.error("Failed A/B send", e);
    msgAEl.classList.add("error");
    msgBEl.classList.add("error");
    msgAEl.textContent = "[A] error during A/B call";
    msgBEl.textContent = "[B] error during A/B call";
  }
}
*/

/*
async function sendAB(text, modelA, modelB) {
  const now = nowIso();
  addUserMsgWithTime(text, now); //addMsg("user", text);

  const { rowEl, msgAEl, msgBEl, labelAEl, labelBEl, timeAEl, timeBEl } = addABRow(modelA, modelB, now, now);

  const payload = {
    conversation_id: conversationId,
    model_a: modelA,
    model_b: modelB,
    message: text
  };

  try {
    const res = await fetch("/api/chat_ab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (data.conversation_id) {
      conversationId = data.conversation_id;
      localStorage.setItem("callie_mvp_conversation_id", conversationId);
    }

    rowEl.dataset.abGroup = data.ab_group || "";

    // Support rendering as Markdown, but fallback to plain text if it fails for some reason (e.g. malicious content that causes our markdown renderer to throw)
    //msgAEl.textContent = data.a || "(empty)";
    msgAEl.innerHTML = renderMarkdown(stripZeit(data.a) || "(empty)");
    //msgBEl.textContent = data.b || "(empty)";
    msgBEl.innerHTML = renderMarkdown(stripZeit(data.b) || "(empty)");

    if (data.model_a) labelAEl.textContent = `A · ${data.model_a}`;
    if (data.model_b) labelBEl.textContent = `B · ${data.model_b}`;

    markCanonical(rowEl, data.canonical_slot || "A");

    //const conversations = await fetchConversations();
    //renderConversations(conversations);
    await refreshConversationLists();
    await refreshContext();
  } catch (e) {
    console.error("Failed A/B send", e);
    msgAEl.textContent = "[A] error during A/B call";
    msgBEl.textContent = "[B] error during A/B call";
  }
}
*/

// #endregion

// #region Model select helpers

let models = [];

function findModelById(id) {
  return models.find((m) => m.id === id) || null;
}

function updateModelInfo(which) {
  const sel =
    which === "A"
      ? document.getElementById("modelSelectA")
      : document.getElementById("modelSelectB");
  const infoEl =
    which === "A"
      ? document.getElementById("modelInfoA")
      : document.getElementById("modelInfoB");

  if (!sel || !infoEl) return;

  const id = sel.value;
  const m = findModelById(id);
  if (!m) {
    infoEl.textContent = "";
    return;
  }

  const parts = [];

  parts.push(`<strong>${m.display_name}</strong>`);
  if (m.vendor) parts.push(`<span class="modelVendor">${m.vendor}</span>`);

  const priceBits = [];
  if (m.input_cost_per_million != null)
    priceBits.push(`in: $${m.input_cost_per_million}/M`);
  if (m.output_cost_per_million != null)
    priceBits.push(`out: $${m.output_cost_per_million}/M`);
  if (priceBits.length) {
    parts.push(`<span class="modelPrice">${priceBits.join(" · ")}</span>`);
  }

  if (m.context_window) {
    parts.push(
      `<span class="modelContext">ctx: ${m.context_window.toLocaleString()} tokens</span>`
    );
  }

  if (m.description) {
    parts.push(
      `<div class="modelDesc">${escapeHtml(m.description)}</div>`
    );
  }

  infoEl.innerHTML = parts.join(" · ");
}

async function refreshModels() {
  const data = await fetchJsonDebug("/api/models");
  models = data.models || [];

  renderModelDropdowns();
  updateModelInfo("A");
  updateModelInfo("B");
}

function renderModelDropdowns() {
  const selA = document.getElementById("modelSelectA");
  const selB = document.getElementById("modelSelectB");
  if (!selA || !selB) return;

  // What we saved last time (global, not per-conversation yet)
  const savedA = localStorage.getItem("chatoss.modelA") || "";
  const savedB = localStorage.getItem("chatoss.modelB") || "";

  selA.innerHTML = "";
  selB.innerHTML = "";

  for (const m of models) {
    const labelParts = [m.display_name];
    if (m.vendor) labelParts.push(m.vendor);
    if (m.input_cost_per_million != null && m.output_cost_per_million != null) {
      labelParts.push(
        `~$${m.input_cost_per_million}/${m.output_cost_per_million} per M tok`
      );
    }
    const label = labelParts.join(" · ");

    const optA = document.createElement("option");
    optA.value = m.id;
    optA.textContent = label;

    const optB = document.createElement("option");
    optB.value = m.id;
    optB.textContent = label;

    selA.appendChild(optA);
    selB.appendChild(optB);
  }

  // Restore saved selections if they’re still valid
  if (savedA && models.some((m) => m.id === savedA)) {
    selA.value = savedA;
  }
  if (savedB && models.some((m) => m.id === savedB)) {
    selB.value = savedB;
  }

  // If we didn't have anything saved, leave the defaults (first options)
}

function initABUI() {
  renderModelDropdowns();
  
  const footer = document.querySelector("footer");
  if (footer) {
  }
}

// #endregion

// #region Personalization Modal Helpers

function setPersonalizationModeGlobal() {
  personalizationMode = "global";
  personalizationProjectId = null;

  if (projectSettingsSectionEl) projectSettingsSectionEl.classList.add("hidden");
  if (aboutYouSectionEl) aboutYouSectionEl.classList.remove("hidden");

  const title = persModal?.querySelector(".modalTitle");
  if (title) title.textContent = "Personalization";

  if (projectSettingsTitle) {
    projectSettingsTitle.textContent = "Project Settings";
  }
  if (querySettingsTitleEl) {
    querySettingsTitleEl.textContent = "Global Query / Retrieval Settings";
  }
}

function setPersonalizationModeProject(projectObj) {
  personalizationMode = "project";
  personalizationProjectId = projectObj?.id ?? null;

  if (projectSettingsSectionEl) projectSettingsSectionEl.classList.remove("hidden");
  if (aboutYouSectionEl) aboutYouSectionEl.classList.add("hidden");

  if (projectSystemPromptEl) projectSystemPromptEl.value = projectObj?.system_prompt || "";
  if (projectVisibilityEl) projectVisibilityEl.value = projectObj?.visibility || "private";
  if (projectOverrideCorePromptEl) projectOverrideCorePromptEl.checked = !!projectObj?.override_core_prompt;

  const projectName = projectObj?.name || "Project";

  const title = persModal?.querySelector(".modalTitle");
  if (title) title.textContent = `Project Settings — ${projectName}`;

  if (projectSettingsTitle) {
    projectSettingsTitle.textContent = `Project Settings — ${projectName}`;
  }
  if (querySettingsTitleEl) {
    querySettingsTitleEl.textContent = `Project Query / Retrieval Settings — ${projectObj?.name || "Project"}`;
  }
}

function openMemoryModal() {
  if (!persModal) return;
  hideAllTransientUI({ except: [persModal] });
  persModal.classList.remove("hidden");
}
/*
function openMemoryModal() {
  if (!persModal) return;
  persModal.classList.remove("hidden");
}
*/

function closeMemoryModal() {
  if (!persModal) return;
  persModal.classList.add("hidden");
}

async function loadPersonalization() {
  const [pins, aboutYou] = await Promise.all([
    fetchPins(),
    fetchAboutYou(),
    loadMemories(),
    loadQuerySettingsForCurrentMode()
  ]);
  let filteredPins = pins || [];
  if (personalizationMode === "project" && personalizationProjectId != null) {
    filteredPins = filteredPins.filter(p =>
      p.scope_type === "project" && Number(p.scope_id) === Number(personalizationProjectId)
    );
  } else {
    filteredPins = filteredPins.filter(p =>
      (p.scope_type || "global") === "global" && (p.scope_id == null)
    );
  }

  renderPins(filteredPins);
  if (personalizationMode === "global") {
    populateAboutYouForm(aboutYou);
  }
  // clear the editors and refresh the UI
  resetPinEditor();
  resetMemoryEditor();      
  await refreshContext();
}
/*
async function loadPersonalization() {
  const [pins, aboutYou] = await Promise.all([
    fetchPins(),
    fetchAboutYou(),
  ]);
  renderPins(pins);
  populateAboutYouForm(aboutYou);
}
*/

function csvSetFromChecks(map) {
  return Object.entries(map)
    .filter(([_, el]) => !!el?.checked)
    .map(([key]) => key)
    .join(",");
}

function applyChecksFromCsv(value, map) {
  const have = new Set(String(value || "").split(",").map(x => x.trim().toUpperCase()).filter(Boolean));
  Object.entries(map).forEach(([key, el]) => {
    if (el) el.checked = have.has(key);
  });
}

async function fetchQuerySettings(scopeType, scopeId = "") {
  const qs = new URLSearchParams({
    scope_type: scopeType || "global",
    scope_id: String(scopeId || ""),
  });
  return await fetchJsonDebug(`/api/query_settings?${qs.toString()}`);
}

function populateQuerySettingsForm(data) {
  applyChecksFromCsv(data?.effective_query_include || "", {
    FILE: qiFILE,
    MEMORY: qiMEMORY,
    CHAT: qiCHAT,
    CHAT_SUMMARY: qiCHAT_SUMMARY,
    FTS: qiFTS,
    EMBEDDING: qiEMBEDDING,
  });

  applyChecksFromCsv(data?.effective_query_expand_results || "", {
    FILE: qeFILE,
    MEMORY: qeMEMORY,
    CHAT: qeCHAT,
  });

  if (queryMaxFullFilesEl) queryMaxFullFilesEl.value = String(data?.effective_query_max_full_files ?? 0);
  if (queryMaxFullMemoriesEl) queryMaxFullMemoriesEl.value = String(data?.effective_query_max_full_memories ?? 0);
  if (queryMaxFullChatsEl) queryMaxFullChatsEl.value = String(data?.effective_query_max_full_chats ?? 0);
  if (queryExpandMinArtifactHitsEl) queryExpandMinArtifactHitsEl.value = String(data?.effective_query_expand_min_artifact_hits ?? 2);
  if (queryExpandChatWindowBeforeEl) queryExpandChatWindowBeforeEl.value = String(data?.effective_query_expand_chat_window_before ?? 1);
  if (queryExpandChatWindowAfterEl) queryExpandChatWindowAfterEl.value = String(data?.effective_query_expand_chat_window_after ?? 1);  
}

async function loadQuerySettingsForCurrentMode() {
  const scopeType = personalizationMode === "project" ? "project" : "global";
  const scopeId = personalizationMode === "project" ? String(personalizationProjectId || "") : "";
  const data = await fetchQuerySettings(scopeType, scopeId);
  populateQuerySettingsForm(data);
  return data;
}

async function saveQuerySettingsForCurrentMode() {
  const payload = {
    scope_type: personalizationMode === "project" ? "project" : "global",
    scope_id: personalizationMode === "project" ? String(personalizationProjectId || "") : "",
    query_include: csvSetFromChecks({
      FILE: qiFILE,
      MEMORY: qiMEMORY,
      CHAT: qiCHAT,
      CHAT_SUMMARY: qiCHAT_SUMMARY,
      FTS: qiFTS,
      EMBEDDING: qiEMBEDDING,
    }),
    query_expand_results: csvSetFromChecks({
      FILE: qeFILE,
      MEMORY: qeMEMORY,
      CHAT: qeCHAT,
    }),
    query_max_full_files: parseInt(queryMaxFullFilesEl?.value || "0", 10) || 0,
    query_max_full_memories: parseInt(queryMaxFullMemoriesEl?.value || "0", 10) || 0,
    query_max_full_chats: parseInt(queryMaxFullChatsEl?.value || "0", 10) || 0,
    query_expand_min_artifact_hits: Math.max(1, parseInt(queryExpandMinArtifactHitsEl?.value || "2", 10) || 2),
    query_expand_chat_window_before: Math.max(0,parseInt(queryExpandChatWindowBeforeEl?.value || "1", 10) || 0),
    query_expand_chat_window_after: Math.max(0,parseInt(queryExpandChatWindowAfterEl?.value || "1", 10) || 0),
  };

  const data = await fetchJsonDebug("/api/query_settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  populateQuerySettingsForm(data);
  await refreshContext();
  return data;
}

// #endregion
// #region Personalization->Instructions (Pins) helpers

// #region About You

async function fetchAboutYou() {
  return await fetchJsonDebug("/api/memory/pins/about_you");
}

function populateAboutYouForm(data) {
  if (aboutYouNicknameEl) aboutYouNicknameEl.value = data?.nickname || "";
  if (aboutYouAgeEl) aboutYouAgeEl.value = data?.age || "";
  if (aboutYouOccupationEl) aboutYouOccupationEl.value = data?.occupation || "";
  if (aboutYouMoreEl) aboutYouMoreEl.value = data?.more_about_you || "";
}

async function saveAboutYou() {
  const payload = {
    nickname: (aboutYouNicknameEl?.value || "").trim(),
    age: (aboutYouAgeEl?.value || "").trim(),
    occupation: (aboutYouOccupationEl?.value || "").trim(),
    more_about_you: (aboutYouMoreEl?.value || "").trim(),
  };

  const res = await fetch("/api/memory/pins/about_you", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("Failed to save About You: " + (err.detail || err.error || res.status));
    return;
  }

  await loadPersonalization();
  await refreshContext();
}
// #endregion
// #region Regular Pins
async function fetchPins() {
  return await fetchJsonDebug("/api/memory/pins");
}

function resetPinEditor() {
  editingPinId = null;
  if (pinTextEl) pinTextEl.value = "";
  if (pinAddOrSaveBtn) pinAddOrSaveBtn.textContent = "Save";
  if (pinCancelEditBtn) pinCancelEditBtn.classList.add("hidden");
}

function startEditingPin(pin) {
  if (!pin) return;
  editingPinId = pin.id;
  if (pinTextEl) pinTextEl.value = pin.text || "";
  if (pinAddOrSaveBtn) pinAddOrSaveBtn.textContent = "Update";
  if (pinCancelEditBtn) pinCancelEditBtn.classList.remove("hidden");
  openMemoryModal();
}

function renderPins(pins) {
  pinListEl.innerHTML = "";
  pinsCache = (pins || []).filter(p => !(p.pin_kind === "profile" && p.title === "about_you"));

  if (!pinsCache.length) {
    const empty = document.createElement("div");
    empty.className = "memPlaceholder";
    empty.textContent = "No saved instructions yet.";
    pinListEl.appendChild(empty);
    return;
  }

  pinsCache.forEach(p => {
    const item = document.createElement("div");
    item.className = "pinItem";

    const text = document.createElement("div");
    text.className = "pinText";
    text.textContent = p.text;

    const actions = document.createElement("div");
    actions.className = "pinActions";

    const editBtn = document.createElement("button");
    editBtn.textContent = "Edit";
    editBtn.addEventListener("click", () => startEditingPin(p));

    const del = document.createElement("button");
    del.textContent = "Delete";
    del.addEventListener("click", async () => {
      const ok = confirm(`Delete this instruction?\n\n${(p.text || "").slice(0, 180)}`);
      if (!ok) return;

      await fetch(`/api/memory/pins/${p.id}`, { method: "DELETE" });

      if (editingPinId === p.id) {
        resetPinEditor();
      }

      await loadPersonalization();
      await refreshContext();
    });

    actions.appendChild(editBtn);
    actions.appendChild(del);

    item.appendChild(text);
    item.appendChild(actions);
    pinListEl.appendChild(item);
  });
}

async function savePinFromUi() {
  const text = (pinTextEl?.value || "").trim();
  if (!text) return;

  const existing = editingPinId
    ? pinsCache.find((p) => p.id === editingPinId)
    : null;

  const payload = {
    text,
    pin_kind: existing?.pin_kind || "instruction",
    title: existing?.title || null,
    scope_type: personalizationMode === "project" ? "project" : "global",
    scope_id: personalizationMode === "project" ? personalizationProjectId : null,
  };

  const isEdit = !!editingPinId;
  const url = isEdit
    ? `/api/memory/pins/${encodeURIComponent(editingPinId)}`
    : "/api/memory/pins";
  const method = isEdit ? "PUT" : "POST";

  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(`Failed to ${isEdit ? "update" : "save"} instruction: ` + (err.detail || err.error || res.status));
    return;
  }

  resetPinEditor();
  await loadPersonalization();
  await refreshContext();
}

// #endregion

// #endregion
// #region Memory helpers

async function fetchMemories() {
  return await fetchJsonDebug("/api/memories");
}

async function createMemoryFromUi() {
  if (!memoryTextEl) return;

  const content = (memoryTextEl.value || "").trim();
  if (!content) {
    alert("Memory content cannot be empty.");
    return;
  }

  const tagsRaw = (memoryTagsEl?.value || "").trim();
  const tags = tagsRaw || null;

  let importance = 0;
  if (memoryImportanceEl && memoryImportanceEl.value !== "") {
    const parsed = parseInt(memoryImportanceEl.value, 10);
    importance = Number.isNaN(parsed) ? 0 : parsed;
  }

  const existing = editingMemoryId
    ? memoriesCache.find((m) => m.id === editingMemoryId)
    : null;

  const payload = {
    content,
    importance,
    tags,
    created_by: existing?.created_by || "user",
    origin_kind: existing?.origin_kind || "user_asserted",
    scope_type: existing?.scope_type || (personalizationMode === "project" ? "project" : "global"),
    scope_id: existing ? (existing.scope_id ?? null) : (personalizationMode === "project" ? personalizationProjectId : null),
  };
  const forcedProjectId =
  personalizationMode === "project" && personalizationProjectId != null
    ? personalizationProjectId
    : null;

  try {
    const isEdit = !!editingMemoryId;
    const url = isEdit
      ? `/api/memories/${encodeURIComponent(editingMemoryId)}`
      : "/api/memories";
    const method = isEdit ? "PUT" : "POST";

    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(`Failed to ${isEdit ? "update" : "create"} memory: ` + (err.detail || res.status));
      return;
    }

    const data = await res.json();
    const memoryId = data.id;

    // Only link on first create, not on edit.
    if (!isEdit && memoryId) {
      if (conversationId) {
        const resLinkConv = await fetch(
          `/api/memories/${encodeURIComponent(memoryId)}/link_conversation/${encodeURIComponent(conversationId)}`,
          { method: "POST" }
        );
        if (!resLinkConv.ok) {
          console.warn("Failed to link memory to conversation", await resLinkConv.text());
        }
      }

      const meta = conversationMap.get(conversationId);
      const pid = forcedProjectId ?? meta?.project_id ?? null;
      if (pid != null) {
        const resLinkProj = await fetch(
          `/api/memories/${encodeURIComponent(memoryId)}/link_project/${pid}`,
          { method: "POST" }
        );
        if (!resLinkProj.ok) {
          console.warn("Failed to link memory to project", await resLinkProj.text());
        }
      }
    }

    resetMemoryEditor();
    await loadMemories();
    await refreshContext();
  } catch (e) {
    console.error("createMemoryFromUi failed", e);
    alert("Error saving memory – see console for details.");
  }
}

function memoryTagsToInput(tags) {
  if (!tags) return "";
  try {
    const parsed = JSON.parse(tags);
    if (Array.isArray(parsed)) return parsed.join(", ");
  } catch (_) {
    // leave as-is
  }
  return String(tags);
}

function memoryTagsToDisplay(tags) {
  const s = memoryTagsToInput(tags);
  return s ? s.split(",").map(x => x.trim()).filter(Boolean) : [];
}

function resetMemoryEditor() {
  editingMemoryId = null;
  if (memoryTextEl) memoryTextEl.value = "";
  if (memoryTagsEl) memoryTagsEl.value = "";
  if (memoryImportanceEl) memoryImportanceEl.value = "0";
  if (memorySaveBtn) memorySaveBtn.textContent = "Save memory";
  if (memoryCancelEditBtn) memoryCancelEditBtn.classList.add("hidden");
}

function startEditingMemory(mem) {
  if (!mem) return;
  editingMemoryId = mem.id;
  if (memoryTextEl) memoryTextEl.value = mem.content || "";
  if (memoryTagsEl) memoryTagsEl.value = memoryTagsToInput(mem.tags);
  if (memoryImportanceEl) memoryImportanceEl.value = String(mem.importance ?? 0);
  if (memorySaveBtn) memorySaveBtn.textContent = "Update memory";
  if (memoryCancelEditBtn) memoryCancelEditBtn.classList.remove("hidden");
  openMemoryModal();
}

async function saveMemoryScope(mem, scopeType, scopeId) {
  const payload = {
    content: mem.content || "",
    importance: mem.importance ?? 0,
    tags: memoryTagsToInput(mem.tags) || null,
    created_by: mem.created_by || "user",
    origin_kind: mem.origin_kind || "user_asserted",
    scope_type: scopeType,
    scope_id: scopeId,
  };

  const res = await fetch(`/api/memories/${encodeURIComponent(mem.id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("Failed to update memory scope: " + (err.detail || res.status));
    return;
  }

  await loadMemories();
  await refreshContext();
}

function renderMemories(memories) {
  if (!memoryListEl) return;

  memoriesCache = Array.isArray(memories) ? memories : [];
  memoryListEl.innerHTML = "";

  if (!memoriesCache.length) {
    const empty = document.createElement("div");
    empty.className = "memPlaceholder";
    empty.textContent = "No saved memories yet.";
    memoryListEl.appendChild(empty);
    return;
  }

  memoriesCache.forEach((m) => {
    const item = document.createElement("div");
    item.className = "pinItem";

    const preview = document.createElement("div");
    preview.className = "pinText memoryPreview";
    preview.textContent = m.content || "";

    const meta = document.createElement("div");
    meta.className = "memoryMeta";

    const bits = [];
    bits.push(`importance ${m.importance ?? 0}`);
    bits.push(m.origin_kind || "user_asserted");
    bits.push(m.created_by || "user");
    bits.push(`scope: ${(m.scope_type || "global")}${m.scope_id != null ? `:${m.scope_id}` : ""}`);

    if (m.updated_at || m.created_at) {
      bits.push(formatReadableDateTime(m.updated_at || m.created_at));
    }
    
    const tagBits = memoryTagsToDisplay(m.tags);
    if (tagBits.length) {
      bits.push(`tags: ${tagBits.join(", ")}`);
    }

    if (Array.isArray(m.project_ids) && m.project_ids.length) {
      bits.push(`projects: ${m.project_ids.join(", ")}`);
    }

    if (Array.isArray(m.conversation_ids) && m.conversation_ids.length) {
      bits.push(`chats: ${m.conversation_ids.length}`);
    }

    meta.textContent = bits.join(" · ");

    const actions = document.createElement("div");
    actions.className = "pinActions";

    const editBtn = document.createElement("button");
    editBtn.textContent = "Edit";
    editBtn.addEventListener("click", () => startEditingMemory(m));
    actions.appendChild(editBtn);

    const deleteBtn = document.createElement("button");
    deleteBtn.textContent = "Delete";
    deleteBtn.addEventListener("click", async () => {
      const ok = confirm(`Delete this memory?\n\n${(m.content || "").slice(0, 180)}`);
      if (!ok) return;

      await fetch(`/api/memories/${encodeURIComponent(m.id)}`, {
        method: "DELETE",
      });

      if (editingMemoryId === m.id) {
        resetMemoryEditor();
      }

      await loadMemories();
      await refreshContext();
    });
    actions.appendChild(deleteBtn);

    const originalProjectId =
      Array.isArray(m.project_ids) && m.project_ids.length
        ? Number(m.project_ids[0])
        : null;

    if (personalizationMode === "project" && m.scope_type === "project") {
      const globalBtn = document.createElement("button");
      globalBtn.textContent = "Make Global";
      globalBtn.addEventListener("click", async () => {
        const ok = confirm("Promote this memory to global scope?");
        if (!ok) return;
        await saveMemoryScope(m, "global", null);
      });
      actions.appendChild(globalBtn);
    } else if (
      personalizationMode === "global" &&
      (m.scope_type || "global") === "global" &&
      originalProjectId != null
    ) {
      const proj = projectsCache.find(p => Number(p.id) === originalProjectId);
      const returnBtn = document.createElement("button");
      returnBtn.textContent = proj ? `Return to ${proj.name}` : "Return to Project";
      returnBtn.addEventListener("click", async () => {
        const ok = confirm(`Return this memory to ${proj?.name || "its original project"} scope?`);
        if (!ok) return;
        await saveMemoryScope(m, "project", originalProjectId);
      });
      actions.appendChild(returnBtn);
    }

    item.appendChild(preview);
    item.appendChild(meta);
    item.appendChild(actions);

    memoryListEl.appendChild(item);
  });
}

async function loadMemories() {
  const memories = await fetchMemories();
  let filtered = memories || [];

  if (personalizationMode === "project" && personalizationProjectId != null) {
    filtered = filtered.filter(m =>
      (m.scope_type === "project") &&
      Number(m.scope_id) === Number(personalizationProjectId)
    );
  } else {
    filtered = filtered.filter(m =>
      (m.scope_type || "global") === "global"
    );
  }

  renderMemories(filtered);
  return filtered;
}
/*
async function loadMemories() {
  const memories = await fetchMemories();
  let filtered = memories || [];

  if (personalizationMode === "project" && personalizationProjectId != null) {
    filtered = filtered.filter(m =>
      Array.isArray(m.project_ids) &&
      m.project_ids.some(pid => Number(pid) === Number(personalizationProjectId))
    );
  } else {
    filtered = filtered.filter(m =>
      !Array.isArray(m.project_ids) || m.project_ids.length === 0
    );
  }

  renderMemories(filtered);
  return filtered;
}
*/
/*
async function loadMemories() {
  const memories = await fetchMemories();
  renderMemories(memories);
  return memories;
}
*/

// #endregion

// #region Conversation management (context menu/modal) helpers

function getMenuCid() {
  return menuTargetConversationId;
}
function getMenuTitle(cid) {
  return conversationMap.get(cid)?.title || "New chat";
}

async function deleteConversationWithConfirmation(cid, title) {
  const safeTitle = (title && String(title).trim()) ? String(title).trim() : "this chat";
  const ok = confirm(`Delete “${safeTitle}”? This cannot be undone.`);
  if (!ok) return;

  try {
    const res = await fetch(`/api/conversations/${encodeURIComponent(cid)}`, { method: "DELETE" });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      console.error("[delete] failed", res.status, txt);
      alert(`Delete failed (HTTP ${res.status}). ${txt.slice(0, 200)}`);
      return;
    }

    if (cid === conversationId) {
      conversationId = null;
      try { localStorage.removeItem("callie_mvp_conversation_id"); } catch {}
      chatWindow.innerHTML = "";
      contextPreviewEl.textContent = "Loading…";
      topBarChatTitleEl.textContent = "New chat";
    }

    const [projects, conversations] = await Promise.all([fetchProjects(), fetchConversations()]);
    renderProjects(projects, conversations);
    renderConversations(conversations);

    if (!conversationId) {
      if (conversations.length) await selectConversation(conversations[0].id);
      else await newChat();
    }
  } catch (e) {
    console.error("[delete] exception", e);
    alert("Delete failed: " + (e?.message || e));
  }
}

async function moveConversationToProject(conversationId) {
  const projects = await fetchProjects();

  moveToDatalist.innerHTML = "";
  projects.forEach(p => {
    const opt = document.createElement("option");
    opt.value = p.name;
    moveToDatalist.appendChild(opt);
  });

  const current = conversationMap.get(conversationId);
  moveToInput.value = current?.project_name || "";

  function close() { moveToModal.classList.add("hidden"); }
  function open() { moveToModal.classList.remove("hidden"); setTimeout(() => moveToInput.focus(), 0); }

  open();

  const apply = async (value) => {
    const trimmed = (value || "").trim();
    const payload = {};

    if (!trimmed) {
      payload.project_id = null;
      payload.project_name = null;
    } else {
      const hit = projects.find(p => (p.name || "").toLowerCase() === trimmed.toLowerCase());
      if (hit) payload.project_id = hit.id;
      else payload.project_name = trimmed;
    }

    const res = await fetch(`/api/conversations/${conversationId}/project`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert("Failed to move conversation: " + (err.detail || res.status));
      return;
    }

    const [p2, c2] = await Promise.all([fetchProjects(), fetchConversations()]);
    renderProjects(p2, c2);
    renderConversations(c2);
    if (conversationId === window.conversationId) await refreshContext();
  };

  // one-shot handlers
  moveToApply.onclick = async () => { const v = moveToInput.value; close(); await apply(v); };
  moveToClear.onclick = async () => { close(); await apply(""); };
  moveToCancel.onclick = () => close();
  moveToClose.onclick = () => close();
  if (moveToBackdrop) moveToBackdrop.onclick = () => close();
}

async function archiveConversation(conversationId, archived) {
  try {
    const res = await fetch(
      `/api/conversations/${conversationId}/archive`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ archived })
      }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert("Failed to archive: " + (err.detail || res.status));
      return;
    }
    //const conversations = await fetchConversations();
    //renderConversations(conversations);
    await refreshConversationLists();
  } catch (e) {
    console.error("archiveConversation failed", e);
    alert("Error archiving conversation.");
  }
}

function showConvMenu(e, targetId) {
  hideAllTransientUI({ except: [convMenuEl] });
  menuTargetConversationId = targetId;
  positionMenu(convMenuEl, e.clientX, e.clientY);
  if (convMenuManageFilesBtn) {
    // pessimistically disable, then re-enable if we find files
    setFilesButtonEnabled(convMenuManageFilesBtn, false);
    refreshConversationFilesState(targetId);
  }
}

function hideConvMenu() {
  menuTargetConversationId = null;
  convMenuEl.classList.add("hidden");
}

// This one is project aware
async function refreshConversationLists() {
  // projectsCache is already kept fresh in boot and after project edits;
  // if it’s empty (first run), fetch projects once.
  if (!projectsCache || !projectsCache.length) {
    projectsCache = await fetchProjects();
  }
  const conversations = await fetchConversations();
  renderProjects(projectsCache, conversations);
  renderConversations(conversations);
  return conversations;
}

async function renameChat() {
  if (!conversationId) return;
  const current = conversationMap.get(conversationId)?.title || "New chat";
  const next = prompt("Rename chat:", current);
  if (next === null) return;

  const title = next.trim();
  await fetch(`/api/conversation/${conversationId}/title`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title })
  });

  //const conversations = await fetchConversations();
  //renderConversations(conversations);
  await refreshConversationLists();
  await refreshContext();
}

async function suggestChatTitle() {
  if (!conversationId) return;

  topMenuSuggestTitleBtn.disabled = true;
  topMenuSuggestTitleBtn.textContent = "Thinking…";
  try {
    const res = await fetch(`/api/conversation/${conversationId}/suggest_title`, { method: "POST" });
    const data = await res.json();
    if (data?.title) {
      //const conversations = await fetchConversations();
      //renderConversations(conversations);
      await refreshConversationLists();
      await refreshContext();
    }
  } finally {
    topMenuSuggestTitleBtn.disabled = false;
    topMenuSuggestTitleBtn.textContent = "Suggest";
  }
}

async function summarizeConversation(conversationId) {
  try {
    const res = await fetch(`/api/conversations/${conversationId}/summarize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" }
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert("Failed to summarize: " + (err.detail || res.status));
      return;
    }
    const data = await res.json();
    // Re-open current conversation so the new assistant summary message appears
    await selectConversation(conversationId);
    // Downstream calls refreshConversationLists() and refreshContext
  } catch (e) {
    console.error("summarizeConversation failed", e);
    alert("Error summarizing conversation.");
  }
}

// #endregion

// #region Project management (menu/modal) helpers

async function fetchProjects() {
  const res = await fetch("/api/projects");
  if (!res.ok) return [];
  const data = await res.json();
  return data.projects || [];
}

function projectExpandedKey(pid) {
  return `chatoss.projectExpanded.${pid}`;
}

function getProjectExpanded(pid, defaultValue) {
  const v = localStorage.getItem(projectExpandedKey(pid));
  if (v === "1") return true;
  if (v === "0") return false;
  return !!defaultValue;
}

function setProjectExpanded(pid, expanded) {
  localStorage.setItem(projectExpandedKey(pid), expanded ? "1" : "0");
}

function renderProjects(projects, conversations) {
  if (!sideBarProjListEl) return;

  projectsCache = projects || [];
  sideBarProjListEl.innerHTML = "";

  // Group conversations by project_id, preserving whatever order /api/conversations returned
  const byPid = new Map();
  (conversations || []).forEach(c => {
    if (c.project_id == null) return;
    const pid = c.project_id;
    if (!byPid.has(pid)) byPid.set(pid, []);
    byPid.get(pid).push(c);
  });

  projectsCache.forEach(p => {
    const convs = byPid.get(p.id) || [];
    const containsActive = convs.some(x => x.id === conversationId);

    // Default: collapsed unless it contains the active conversation
    const expanded = getProjectExpanded(p.id, containsActive);

    const block = document.createElement("div");
    block.className = "projBlock";

    const header = document.createElement("div");
    header.className = "projItem projHeader";

    const toggle = document.createElement("span");
    toggle.className = "projToggle";
    toggle.textContent = expanded ? "▾" : "▸";

    const name = document.createElement("div");
    name.className = "projName";
    name.textContent = p.name;
    if (p.description) name.title = p.description;

    const count = document.createElement("div");
    count.className = "projCount";
    count.textContent = String(convs.length);

    header.appendChild(toggle);
    header.appendChild(name);
    header.appendChild(count);

    // Left-click toggles expand/collapse
    header.addEventListener("click", (ev) => {
      // Don’t toggle if this was a right-click opening the project menu
      const next = !getProjectExpanded(p.id, containsActive);
      setProjectExpanded(p.id, next);
      renderProjects(projectsCache, conversations); // re-render just the project list
    });

    // Right-click opens the project context menu (rename/description)
    header.addEventListener("contextmenu", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      menuTargetProjectId = p.id;

      if (projMenuToggleVisibility) {
        projMenuToggleVisibility.textContent =
          p.visibility === "global" ? "Make Private" : "Make Global";
      }

      hideAllTransientUI({ except: [projMenuEl] });
      positionMenu(projMenuEl, ev.clientX, ev.clientY);

      if (projMenuManageFilesBtn) {
        setFilesButtonEnabled(projMenuManageFilesBtn, false);
        refreshProjectFilesState(p.id);
      }
    });
    /*
    header.addEventListener("contextmenu", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      menuTargetProjectId = p.id;
      positionMenu(projMenuEl, ev.clientX, ev.clientY);
      //projMenuEl.style.left = `${ev.clientX}px`;
      //projMenuEl.style.top = `${ev.clientY}px`;
      //projMenuEl.classList.remove("hidden");
      if (projMenuManageFilesBtn) {
        setFilesButtonEnabled(projMenuManageFilesBtn, false);
        refreshProjectFilesState(p.id);
      }
    });
    */

    const children = document.createElement("div");
    children.className = "projConvs";
    if (!expanded) children.classList.add("hidden");

    convs.forEach(c => {
      children.appendChild(makeConversationItem(c));
    });

    block.appendChild(header);
    block.appendChild(children);
    sideBarProjListEl.appendChild(block);
  });
}

async function updateProject(projectId, fields) {
  const res = await fetch(`/api/projects/${projectId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fields || {})
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("Project update failed: " + (err.detail || res.status));
    return false;
  }
  return true;
}

// #endregion

// #region File upload helpers

async function sha256OfFile(file) {
  const buf = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buf);
  const bytes = Array.from(new Uint8Array(digest));
  return bytes.map(b => b.toString(16).padStart(2, "0")).join("");
}

function openUploadModal(forceScope, explicitProjectId) {
  if (!uploadModal) return;
  hideAllTransientUI({ except: [projMenuEl] });
  uploadProjectIdForced = explicitProjectId ?? null;

  // Reset state
  if (uploadFilesEl) uploadFilesEl.value = "";
  if (uploadStatusEl) uploadStatusEl.textContent = "";

  if (!uploadScopeEl) {
    uploadModal.classList.remove("hidden");
    return;
  }

  const meta = conversationId ? conversationMap.get(conversationId) : null;
  const hasProject = !!(meta && meta.project_id != null);

  // Enable/disable the Project option based on whether there is a project
  const projectOption = Array.from(uploadScopeEl.options || []).find(
    o => o.value === "project"
  );
  if (projectOption) {
    const allowProject = hasProject || explicitProjectId != null;
    projectOption.disabled = !allowProject;
    if (!allowProject && uploadScopeEl.value === "project") {
      uploadScopeEl.value = "conversation";
    }
  }

  // Lock scope when invoked from project menu
  if (forceScope === "project") {
    uploadScopeEl.value = "project";
    uploadScopeEl.disabled = true;
  } else {
    uploadScopeEl.disabled = false;
    if (!uploadScopeEl.value) {
      uploadScopeEl.value = "conversation";
    }
  }

  uploadModal.classList.remove("hidden");
}

function closeUploadModal() {
  if (!uploadModal) return;
  uploadModal.classList.add("hidden");
  uploadProjectIdForced = null;
}

async function startUpload() {
  if (!uploadFilesEl || !uploadScopeEl) return;
  const files = Array.from(uploadFilesEl.files || []);
  if (!files.length) {
    alert("Choose at least one file.");
    return;
  }

  // scope checks
  const scope = uploadScopeEl.value || "conversation";
  let payloadConversationId = null;
  let payloadProjectId = null;
  if (scope === "conversation") {
    if (!conversationId) {
      alert("You need an active conversation for conversation scope.");
      return;
    }
    payloadConversationId = conversationId;
  } else if (scope === "project") {
    if (uploadProjectIdForced != null) {
      payloadProjectId = uploadProjectIdForced;
    } else {
      const meta = conversationId ? conversationMap.get(conversationId) : null;
      payloadProjectId = meta?.project_id ?? null;
    }
    if (payloadProjectId == null) {
      alert("No project is associated with this chat.");
      return;
    }
  } else if (scope === "global") {
    // No extra ids needed
  } else {
    alert("Invalid scope: " + scope);
    return;
  }

  // Preflight duplicate warning
  const preflightFiles = [];
  for (const f of files) {
    const sha256 = await sha256OfFile(f);
    preflightFiles.push({
      name: f.name,
      sha256,
      scope_type: scope,
      conversation_id: payloadConversationId || null,
      project_id: payloadProjectId ?? null,
    });
  }

  const preflightRes = await fetch("/api/files/preflight_upload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files: preflightFiles }),
  });

  if (!preflightRes.ok) {
    const txt = await preflightRes.text().catch(() => "");
    alert("Upload preflight failed: " + (txt.slice(0, 200) || preflightRes.status));
    return;
  }

  const preflight = await preflightRes.json();
  const pfFiles = preflight.files || [];
  const dupes = pfFiles.filter(x => (x.duplicate_count || 0) > 0);
  const sameNameConflicts = pfFiles.filter(x => (x.same_name_count || 0) > 0);
  let warnings = [];
  if (dupes.length) {
    warnings.push("Possible duplicate upload(s) detected:");
    for (const d of dupes) {
      warnings.push(`• ${d.name} -> ${d.duplicate_count} existing file(s) with same hash`);
      for (const f of (d.duplicates || []).slice(0, 8)) {
        const scope =
          f.scope_type === "conversation"
            ? `conversation:${f.scope_uuid || "?"}`
            : f.scope_type === "project"
            ? `project:${f.scope_id ?? "?"}`
            : (f.scope_type || "global");
        warnings.push(`    - ${scope} :: ${f.name} [${f.id}]`);
      }
    }
  }
  if (sameNameConflicts.length) {
    warnings.push("");
    warnings.push("Same-name conflicts detected:");
    for (const d of sameNameConflicts) {
      const conflicts = (d.same_name_conflicts || []).filter(f => f.id);
      if (!conflicts.length) continue;

      warnings.push(`• ${d.name} -> ${conflicts.length} existing file(s) with same name`);
      for (const f of conflicts.slice(0, 8)) {
        const scope =
          f.scope_type === "conversation"
            ? `conversation:${f.scope_uuid || "?"}`
            : f.scope_type === "project"
            ? `project:${f.scope_id ?? "?"}`
            : (f.scope_type || "global");
        const hashNote = f.same_hash ? "same hash" : "different hash";
        warnings.push(`    - ${scope} :: ${hashNote} [${f.id}]`);
      }
    }
  }
  if (warnings.length) {
    warnings.push("");
    warnings.push("Continue anyway?");
    const ok = confirm(warnings.join("\n"));
    if (!ok) return;
  }

  // actually submittal
  const form = new FormData();
  files.forEach(f => form.append("files", f));

  const params = new URLSearchParams();
  params.set("scope_type", scope);
  if (payloadConversationId) params.set("conversation_id", payloadConversationId);
  if (payloadProjectId != null) params.set("project_id", String(payloadProjectId));

  const prevSendDisabled = chatWindowInputSendBtn.disabled;
  const prevInputDisabled = chatWindowInputTextbox.disabled;
  const prevAttachDisabled = chatWindowInputAddFilesBtn ? chatWindowInputAddFilesBtn.disabled : false;

  chatWindowInputSendBtn.disabled = true;
  chatWindowInputTextbox.disabled = true;
  if (chatWindowInputAddFilesBtn) chatWindowInputAddFilesBtn.disabled = true;
  if (uploadStartBtn) uploadStartBtn.disabled = true;
  if (uploadStatusEl) uploadStatusEl.textContent = "Uploading…";

  try {
    const res = await fetch(`/api/upload_file?${params.toString()}`, {
      method: "POST",
      body: form
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      console.error("Upload failed", res.status, txt);
      if (uploadStatusEl) uploadStatusEl.textContent = "Upload failed.";
      alert("Upload failed: " + (txt.slice(0, 200) || res.status));
      return;
    }

    const data = await res.json().catch(() => ({}));
    console.log("Upload OK", data);
    if (uploadStatusEl) uploadStatusEl.textContent = "Uploaded.";
    closeUploadModal();

    try {
      await refreshGlobalFilesState();
    } catch (e) {
      console.error("refreshGlobalFilesState after upload failed", e);
    }

    // New files can change context; refresh if we can
    try {
      await refreshContext();
    } catch (e) {
      console.warn("refreshContext after upload failed", e);
    }
  } finally {
    chatWindowInputSendBtn.disabled = prevSendDisabled;
    chatWindowInputTextbox.disabled = prevInputDisabled;
    if (chatWindowInputAddFilesBtn) chatWindowInputAddFilesBtn.disabled = prevAttachDisabled;
    if (uploadStartBtn) uploadStartBtn.disabled = false;
  }
}

// #endregion

// #region File management (menu/modal) helpers

function openFilesModalForConversation(convId) {
  filesModalMode = "conversation";
  filesModalConversationId = convId;
  filesModalProjectId = null;
  loadFilesModal();
}

function openFilesModalForProject(pid) {
  filesModalMode = "project";
  filesModalProjectId = pid;
  filesModalConversationId = null;
  loadFilesModal();
}

function openFilesModalGlobal() {
  filesModalMode = "global";
  filesModalConversationId = null;
  filesModalProjectId = null;
  loadFilesModal();
}

function openFilesModalAll() {
  filesModalMode = "all";
  filesModalConversationId = null;
  filesModalProjectId = null;
  loadFilesModal();
}

async function loadFilesModal() {
  if (!filesModal || !filesListEl) return;
  hideAllTransientUI({ except: [projMenuEl] });

  let url = null;

  if (filesModalMode === "conversation") {
    if (!filesModalConversationId) return;
    url = `/api/conversations/${encodeURIComponent(filesModalConversationId)}/files`;
  } else if (filesModalMode === "project") {
    if (filesModalProjectId == null) return;
    url = `/api/projects/${encodeURIComponent(filesModalProjectId)}/files`;
  } else if (filesModalMode === "global") {
    url = "/api/files/global";
  } else if (filesModalMode === "all") {
    url = "/api/files";
  } else {
    return;
  }

  filesListEl.textContent = "Loading…";
  filesModal.classList.remove("hidden");

  try {
    const res = await fetch(url);
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      console.error("files list error", res.status, txt);
      filesListEl.textContent = "Failed to load files.";
      return;
    }

    const data = await res.json().catch(() => ({}));
    const files = Array.isArray(data.files) ? data.files : [];

    if (!files.length) {
      filesListEl.textContent = "No files yet.";
      return;
    }

    const container = document.createElement("div");
    container.className = "filesListTable";

    files.forEach((file) => {
      const row = document.createElement("div");
      row.className = "filesRow";

      const nameSpan = document.createElement("span");
      nameSpan.className = "filesName";
      nameSpan.textContent = file.name || file.path || file.id;

      const descInput = document.createElement("input");
      descInput.className = "filesDescInput";
      descInput.type = "text";
      descInput.placeholder = "Description / what this file is for…";
      descInput.value = file.description || "";
      descInput.dataset.fileId = file.id;
      descInput.addEventListener("change", () => {
        saveFileDescription(file.id, descInput.value);
      });

      let moveBtn = null;
      const canMoveToGlobal = (file.scope_type || "") === "project";
      if (canMoveToGlobal) {
        moveBtn = document.createElement("button");
        moveBtn.className = "filesMoveBtn";
        moveBtn.textContent = "Move to Global";
        moveBtn.addEventListener("click", async () => {
          try {
            await moveFileToGlobal(file);
          } catch (err) {
            console.error("move file failed", err);
            alert("Move failed: " + (err?.message || err));
          }
        });
      }

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "filesDeleteBtn";
      deleteBtn.textContent = "Delete";
      deleteBtn.addEventListener("click", async () => {
        const ok = confirm(`Delete file "${file.name || file.id}" and its artifacts/chunks?`);
        if (!ok) return;

        try {
          const res = await fetch(`/api/files/${encodeURIComponent(file.id)}`, {
            method: "DELETE",
          });

          if (!res.ok) {
            const txt = await res.text().catch(() => "");
            alert(`Delete failed (HTTP ${res.status}). ${txt.slice(0, 200)}`);
            return;
          }

          row.remove();

          if (!container.children.length) {
            filesListEl.textContent = "No files yet.";
          }

          try {
            await refreshContext();
          } catch (e) {
            console.warn("refreshContext after file delete failed", e);
          }

          try {
            await refreshTopLeftManageFilesState();
          } catch (e) {
            console.warn("refreshTopLeftManageFilesState failed", e);
          }

          if (filesModalProjectId != null) {
            try {
              await refreshProjectFilesState(filesModalProjectId);
            } catch (e) {
              console.warn("refreshProjectFilesState failed", e);
            }
          }

          if (filesModalConversationId) {
            try {
              await refreshConversationFilesState(filesModalConversationId);
            } catch (e) {
              console.warn("refreshConversationFilesState failed", e);
            }
          }
        } catch (err) {
          console.error("delete file failed", err);
          alert("Delete failed: " + (err?.message || err));
        }
      });

      row.appendChild(nameSpan);
      row.appendChild(descInput);
      if (moveBtn) row.appendChild(moveBtn);
      row.appendChild(deleteBtn);

      container.appendChild(row);
    });

    filesListEl.innerHTML = "";
    filesListEl.appendChild(container);
  } catch (err) {
    console.error("files list error", err);
    filesListEl.textContent = "Failed to load files.";
  }
}

function closeFilesModal(save = true) {
  if (!filesModal) return;
  if (save) {
    // explicitly save all descriptions on close, in case user edited but didn’t blur the input (which triggers change event)
    for (const input of filesListEl.querySelectorAll("input.filesDescInput")) {
      const fileId = input.dataset.fileId;
      saveFileDescription(fileId, input.value);
    }
  }
  filesModal.classList.add("hidden");
  filesModalMode = null;
  filesModalConversationId = null;
  filesModalProjectId = null;
}

async function moveFileToGlobal(file) {
  const ok = confirm(`Move file "${file.name || file.id}" to Global files?`);
  if (!ok) return false;

  const res = await fetch(`/api/files/${encodeURIComponent(file.id)}/move_scope`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scope_type: "global" }),
  });

  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    alert(`Move failed (HTTP ${res.status}). ${txt.slice(0, 200)}`);
    return false;
  }

  await loadFilesModal();

  try {
    await refreshContext();
  } catch (e) {
    console.warn("refreshContext after file move failed", e);
  }

  try {
    await refreshTopLeftManageFilesState();
  } catch (e) {
    console.warn("refreshTopLeftManageFilesState failed", e);
  }

  if (filesModalProjectId != null) {
    try {
      await refreshProjectFilesState(filesModalProjectId);
    } catch (e) {
      console.warn("refreshProjectFilesState failed", e);
    }
  }

  if (filesModalConversationId) {
    try {
      await refreshConversationFilesState(filesModalConversationId);
    } catch (e) {
      console.warn("refreshConversationFilesState failed", e);
    }
  }

  return true;
}

async function saveFileDescription(fileId, description) {
  try {
    const res = await fetch(`/api/files/${encodeURIComponent(fileId)}/description`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description }),
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      console.error("save description failed", res.status, txt);
    }
  } catch (err) {
    console.error("save description error", err);
  }
}

function setFilesButtonEnabled(btn, enabled) {
  if (!btn) return;
  if (enabled) {
    btn.classList.remove("files-disabled");
    btn.disabled = false;
  } else {
    btn.classList.add("files-disabled");
    btn.disabled = true;
  }
}

async function refreshGlobalFilesState() {
  // Uses the new /api/files/summary endpoint (we'll add it below)
  if (!topMenuManageFilesBtn) return;
  try {
    const data = await fetchJsonDebug("/api/files/summary");
    const total = data?.total ?? 0;
    hasAnyFiles = total > 0;
    setFilesButtonEnabled(topMenuManageFilesBtn, hasAnyFiles);
  } catch (err) {
    console.error("files summary error", err);
    // On error, don't hard-disable the button
    setFilesButtonEnabled(topMenuManageFilesBtn, true);
  }
}

async function refreshConversationFilesState(convId) {
  if (!convMenuManageFilesBtn || !convId) return;
  try {
    const res = await fetch(`/api/conversations/${encodeURIComponent(convId)}/files`);
    if (!res.ok) throw new Error("status " + res.status);
    const data = await res.json();
    const hasFiles = (data.files || []).length > 0;
    setFilesButtonEnabled(convMenuManageFilesBtn, hasFiles);
  } catch (err) {
    console.error("conv files state error", err);
    setFilesButtonEnabled(convMenuManageFilesBtn, false);
  }
}

async function refreshProjectFilesState(projectId) {
  if (!projMenuManageFilesBtn || projectId == null) return;
  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/files`);
    if (!res.ok) throw new Error("status " + res.status);
    const data = await res.json();
    const hasFiles = (data.files || []).length > 0;
    setFilesButtonEnabled(projMenuManageFilesBtn, hasFiles);
  } catch (err) {
    console.error("project files state error", err);
    setFilesButtonEnabled(projMenuManageFilesBtn, false);
  }
}

// #endregion

// ----------------------------------
// Event bindings and UI initialization
// ----------------------------------

// #region Event bindings

chatWindowInputSendBtn.addEventListener("click", send);

topLeftNewChatBtn.addEventListener("click", newChat);

// #region File upload event bindings

if (chatWindowInputAddFilesBtn && uploadModal) {
  chatWindowInputAddFilesBtn.addEventListener("click", () => {
    if (!conversationId) {
      alert("Start a chat first, then attach files.");
      return;
    }
    openUploadModal(null, null);
  });
}

if (uploadCancelBtn) {
  uploadCancelBtn.addEventListener("click", () => {
    closeUploadModal();
  });
}
if (uploadCloseBtn) {
  uploadCloseBtn.addEventListener("click", () => {
    closeUploadModal();
  });
}
if (uploadBackdrop) {
  uploadBackdrop.addEventListener("click", () => {
    closeUploadModal();
  });
}
if (uploadStartBtn) {
  uploadStartBtn.addEventListener("click", (e) => {
    e.preventDefault();
    startUpload().catch(err => {
      console.error("startUpload error", err);
    });
  });
}

// Project right-click: always project scoped
if (projMenuFileUploadBtn) {
  projMenuFileUploadBtn.addEventListener("click", () => {
    const pid = menuTargetProjectId;
    projMenuEl.classList.add("hidden");
    if (!pid) return;
    openUploadModal("project", pid);
  });
}

// #endregion

// #region File management event bindings

if (convMenuManageFilesBtn) {
  convMenuManageFilesBtn.addEventListener("click", () => {
    convMenuEl.classList.add("hidden");
    const cid = menuTargetConversationId || conversationId;
    if (!cid) {
      alert("No conversation selected.");
      return;
    }
    openFilesModalForConversation(cid);
  });
}

if (projMenuManageFilesBtn) {
  projMenuManageFilesBtn.addEventListener("click", () => {
    projMenuEl.classList.add("hidden");
    const pid = menuTargetProjectId;
    if (!pid) {
      alert("No project selected.");
      return;
    }
    openFilesModalForProject(pid);
  });
}

if (topMenuManageFilesBtn) {
  topMenuManageFilesBtn.addEventListener("click", () => {
    if (topMenuManageFilesBtn.classList.contains("files-disabled")) {
      return;
    }
    openFilesModalAll();
  });
}

// All of these do the same thing (close the modal, saving descriptions)
// TODO filesCloseBtn and maybe filesCloseBottomBtn should maybe send False since the button says "Cancel"?
if (filesCloseBtn) {
  filesCloseBtn.addEventListener("click", () => closeFilesModal(false));
}
if (filesCloseBottomBtn) {
  filesCloseBottomBtn.addEventListener("click", () => closeFilesModal(false));
}
if (filesSaveBtn) {
  filesSaveBtn.addEventListener("click", closeFilesModal);
}
if (filesBackdrop) {
  filesBackdrop.addEventListener("click", closeFilesModal);
}

// #endregion

// #region Memory and Pin event bindings

if (memorySaveBtn) {
  memorySaveBtn.addEventListener("click", () => {
    createMemoryFromUi().catch(e => console.error("createMemoryFromUi error", e));
  });
}
if (saveProjectSettingsBtn) {
  saveProjectSettingsBtn.addEventListener("click", async () => {
    if (personalizationMode !== "project" || personalizationProjectId == null) return;
    const payload = {
      system_prompt: (projectSystemPromptEl?.value || "").trim(),
      visibility: projectVisibilityEl?.value || "private",
      override_core_prompt: !!projectOverrideCorePromptEl?.checked,
    };
    const res = await fetch(`/api/projects/${encodeURIComponent(personalizationProjectId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert("Failed to save project settings: " + (err.detail || res.status));
      return;
    }

    const updated = await res.json();
    projectsCache = projectsCache.map(p => Number(p.id) === Number(updated.id) ? updated : p);
    await refreshContext();
  });
}

if (topMenuOpenMemoryBtn) {
  topMenuOpenMemoryBtn.addEventListener("click", async () => {
    setPersonalizationModeGlobal();
    openMemoryModal();
    toggleTopMenu(false);
    try {
      loadPersonalization();
    } catch (e) {
      console.error("load global personalization failed", e);
    }    
  });
}
if (persCloseBtn) {
  persCloseBtn.addEventListener("click", closeMemoryModal);
}
if (persBackdrop) {
  persBackdrop.addEventListener("click", closeMemoryModal);
}
if (memoryCancelEditBtn) {
  memoryCancelEditBtn.addEventListener("click", resetMemoryEditor);
}
if (aboutYouSaveBtn) {
  aboutYouSaveBtn.addEventListener("click", async () => {
    try {
      await saveAboutYou();
    } catch (e) {
      console.error("saveAboutYou failed", e);
      alert("Error saving About You – see console for details.");
    }
  });
}
if (pinAddOrSaveBtn) {
  pinAddOrSaveBtn.addEventListener("click", () => {
    savePinFromUi().catch(e => console.error("savePinFromUi error", e));    
  });
}
if (pinCancelEditBtn) {
  pinCancelEditBtn.addEventListener("click", resetPinEditor);
}

if (saveQuerySettingsBtn) {
  saveQuerySettingsBtn.addEventListener("click", () => {
    saveQuerySettingsForCurrentMode().catch(e => {
      console.error("saveQuerySettingsForCurrentMode failed", e);
      alert("Failed to save query settings.");
    });
  });
}

// #endregion

// #region Conversation Menu event bindings

if (convMenuRenameBtn) {
  convMenuRenameBtn.addEventListener("click", async () => {
    const cid = menuTargetConversationId;
    if (!cid) return;

    const current = conversationMap.get(cid)?.title || "New chat";
    const next = prompt("Rename chat:", current);
    if (next === null) return;

    await fetch(`/api/conversation/${cid}/title`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: next.trim() })
    });

    hideConvMenu();

    const conversations = await fetchConversations();
    renderConversations(conversations);

    // only refresh top title/context if we're renaming the active chat
    if (cid === conversationId) {
      await refreshContext();
    }
  });
}

if (convMenuSuggestTitleBtn) {
  convMenuSuggestTitleBtn.addEventListener("click", async () => {
    const cid = menuTargetConversationId;
    if (!cid) return;

    convMenuSuggestTitleBtn.disabled = true;
    convMenuSuggestTitleBtn.textContent = "Thinking…";
    try {
      await fetch(`/api/conversation/${cid}/suggest_title`, { method: "POST" });
    } finally {
      convMenuSuggestTitleBtn.disabled = false;
      convMenuSuggestTitleBtn.textContent = "Suggest";
    }

    hideConvMenu();

    const conversations = await fetchConversations();
    renderConversations(conversations);

    if (cid === conversationId) {
      await refreshContext();
    }
  });
}

if (convMenuSummarizeBtn) {
  convMenuSummarizeBtn.addEventListener("click", async () => {
    const cid = getMenuCid();
    if (!cid) return;
    hideConvMenu();
    await summarizeConversation(cid);
  });
}

if (convMenuMoveToBtn) {
  convMenuMoveToBtn.addEventListener("click", async () => {
    const cid = getMenuCid();
    if (!cid) return;
    hideConvMenu();
    await moveConversationToProject(cid);
    // after move, refresh projects list too (counts / visibility)
    const [projects, conversations] = await Promise.all([fetchProjects(), fetchConversations()]);
    renderProjects(projects, conversations);
    renderConversations(conversations);
  });
}

if (convMenuArchiveBtn) {
  convMenuArchiveBtn.addEventListener("click", async () => {
    const cid = getMenuCid();
    if (!cid) return;
    hideConvMenu();
    await archiveConversation(cid, true);
  });
}

if (convMenuDeleteBtn) {
  convMenuDeleteBtn.addEventListener("click", async () => {
    const cid = getMenuCid();
    if (!cid) return;
    hideConvMenu();
    await deleteConversationWithConfirmation(cid, getMenuTitle(cid));
  });
}

if (convMenuExportTranscriptBtn) {
  convMenuExportTranscriptBtn.addEventListener("click", async () => {
    const cid = getMenuCid();
    if (!cid) return;
    hideConvMenu();
    window.location = `/api/conversation/${encodeURIComponent(cid)}/export_transcript`;
  });
}

if (projMenuNewChatBtn) {
  projMenuNewChatBtn.addEventListener("click", async () => {
    const pid = menuTargetProjectId;
    projMenuEl.classList.add("hidden");
    if (!pid) return;

    try {
      const res = await fetch("/api/new", { method: "POST" });
      if (!res.ok) {
        throw new Error(`new chat failed: HTTP ${res.status}`);
      }

      const data = await res.json();
      const cid = data.conversation_id;

      const moveRes = await fetch(`/api/conversations/${encodeURIComponent(cid)}/project`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: pid }),
      });

      if (!moveRes.ok) {
        const err = await moveRes.json().catch(() => ({}));
        throw new Error(err.detail || `assign failed: HTTP ${moveRes.status}`);
      }

      conversationId = cid;
      localStorage.setItem("callie_mvp_conversation_id", conversationId);

      const [projects, conversations] = await Promise.all([
        fetchProjects(),
        fetchConversations(),
      ]);
      renderProjects(projects, conversations);
      renderConversations(conversations);

      await selectConversation(cid);
    } catch (e) {
      console.error("New Chat in Project failed", e);
      alert("Failed to create new chat in project.");
    }
  });
}

// #endregion

// #region Context Preview Pane Bindings

if (contextPreviewToggleBtn) {
  contextPreviewToggleBtn.addEventListener("click", () => {
    const next = !allContextSectionsExpanded();
    Object.keys(contextSectionState).forEach((key) => {
      contextSectionState[key] = next;
    });

    if (lastRenderedContext?.llm_input_messages?.length) {
      const newMsgState = {};
      for (let i = 0; i < lastRenderedContext.llm_input_messages.length; i++) {
        newMsgState[String(i)] = next;
      }
      contextPayloadMessageState = newMsgState;
    }

    persistContextSectionState();
    if (lastRenderedContext) renderContext(lastRenderedContext);
  });
}
/*
if (contextPreviewToggleBtn) {
  contextPreviewToggleBtn.addEventListener("click", () => {
    const next = !allContextSectionsExpanded();
    Object.keys(contextSectionState).forEach((key) => {
      contextSectionState[key] = next;
    });
    persistContextSectionState();
    if (lastRenderedContext) renderContext(lastRenderedContext);
  });
}
*/
/*
if (contextPreviewToggleBtn) {
  contextPreviewToggleBtn.addEventListener("click", () => {
    const next = !allContextSectionsExpanded();
    Object.keys(contextSectionState).forEach((key) => {
      contextSectionState[key] = next;
    });
    if (lastRenderedContext) renderContext(lastRenderedContext);
  });
}
*/
/*
if (contextPreviewToggleBtn) {
  contextPreviewToggleBtn.addEventListener("click", async () => {
    contextExpanded = !contextExpanded;
    await refreshContext();
  });
}
*/

// #endregion

// #region Top Bar event bindings

if (topMenuBtn) {
  topMenuBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleTopMenu();
  });
}
if (topMenu) {
  topMenu.addEventListener("click", (e) => {
    // don't let clicks inside menu bubble up and close it
    e.stopPropagation();
  });
}

// #endregion
// #region Top Menu Bindings

if (topMenuAdvancedABToggle) {
  // restore saved setting
  advancedMode = localStorage.getItem("chatoss.advanced") === "1";
  topMenuAdvancedABToggle.checked = advancedMode;

  topMenuAdvancedABToggle.addEventListener("change", () => {
    advancedMode = topMenuAdvancedABToggle.checked;
    localStorage.setItem("chatoss.advanced", advancedMode ? "1" : "0");
    applyAdvancedVisibility();
  });
}

if (topMenuSearchChatHistoryToggle) {
  topMenuSearchChatHistoryToggle.addEventListener("change", async () => {
    try {
      await saveAppConfig({
        search_chat_history: !!topMenuSearchChatHistoryToggle.checked,
      });
      await refreshContext();
    } catch (e) {
      console.error("save app config failed", e);
      alert("Failed to save Search Chat History setting.");
    }
  });
}

// #endregion
// #region Top Menu Model select event bindings

if (topBarModelSelectA) {
  topBarModelSelectA.addEventListener("change", () =>
    updateModelInfo("A")
  );
}
if (topBarModelSelectB) {
  topBarModelSelectB.addEventListener("change", () =>
    updateModelInfo("B")
  );
}

// #endregion

// #region Project management menu event bindings

if (projMenuToggleVisibility) {
  projMenuToggleVisibility.addEventListener("click", async () => {
    const pid = menuTargetProjectId;
    projMenuEl.classList.add("hidden");
    if (!pid) return;

    const proj = projectsCache.find(p => p.id === pid);
    if (!proj) return;

    const nextVisibility = proj.visibility === "global" ? "private" : "global";

    if (await updateProject(pid, { visibility: nextVisibility })) {
      const [p2, c2] = await Promise.all([fetchProjects(), fetchConversations()]);
      renderProjects(p2, c2);
      renderConversations(c2);

      try {
        await refreshContext();
      } catch (e) {
        console.warn("refreshContext after project visibility change failed", e);
      }
    }
  });
}

if (topLeftNewProjBtn) {
  topLeftNewProjBtn.addEventListener("click", async () => {
    const name = prompt("New project name:", "");
    if (!name || !name.trim()) return;
    try {
      const res = await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim() })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert("Failed to create project: " + (err.detail || res.status));
        return;
      }
      // after success
      // refresh conversations and project lists so grouping updates
      const [projects, conversations] = await Promise.all([fetchProjects(), fetchConversations()]);
      renderProjects(projects, conversations);
      renderConversations(conversations);
    } catch (e) {
      console.error("create project failed", e);
      alert("Error creating project.");
    }
  });
}

if (projMenuSettingsBtn) {
  projMenuSettingsBtn.addEventListener("click", async () => {
    const projectObj = projectsCache.find(p => Number(p.id) === Number(menuTargetProjectId));
    if (!projectObj) {
      alert("Project not found.");
      return;
    }

    setPersonalizationModeProject(projectObj);
    openMemoryModal();
    toggleTopMenu(false);

    resetPinEditor();
    resetMemoryEditor();

    try {
      await loadPersonalization();
      await loadMemories();
    } catch (e) {
      console.error("load project personalization failed", e);
    }
  });
}

if (projMenuRenameBtn) {
  projMenuRenameBtn.addEventListener("click", async () => {
    const pid = menuTargetProjectId;
    projMenuEl.classList.add("hidden");
    if (!pid) return;

    const proj = projectsCache.find(p => p.id === pid);
    const next = prompt("Rename project:", proj?.name || "");
    if (next === null) return;

    if (await updateProject(pid, { name: next.trim() })) {
      const [p2, c2] = await Promise.all([fetchProjects(), fetchConversations()]);
      renderProjects(p2, c2);
      renderConversations(c2);
    }
  });
}

if (projMenuDescriptionBtn) {
  projMenuDescriptionBtn.addEventListener("click", async () => {
    const pid = menuTargetProjectId;
    projMenuEl.classList.add("hidden");
    if (!pid) return;

    const proj = projectsCache.find(p => p.id === pid);
    const next = prompt("Project description:", proj?.description || "");
    if (next === null) return;

    if (await updateProject(pid, { description: next })) {
      const [p2, c2] = await Promise.all([fetchProjects(), fetchConversations()]);
      renderProjects(p2, c2);
      renderConversations(c2);
    }
  });
}

// #endregion

// #region Artifact debug/info model bindings

if (artifactsDebugTopBtn) {
  artifactsDebugTopBtn.addEventListener("click", openArtifactsDebug);
}
if (artifactsDebugCloseBtn) {
  artifactsDebugCloseBtn.addEventListener("click", closeArtifactsDebug);
}

// #endregion

// #region Unfocus/Close on Click Outside bindings

document.addEventListener("click", (e) => {
  if (!convMenuEl.classList.contains("hidden") && !convMenuEl.contains(e.target))
    hideConvMenu();
  // if click is outside menu, hide it
  if (projMenuEl && !projMenuEl.classList.contains("hidden") && !projMenuEl.contains(e.target))
    projMenuEl.classList.add("hidden");
  // clicking anywhere else closes the menu
  toggleTopMenu(false);
});

// #endregion

// #region Key Bindings for Esc and Enter

// bind send to enter when chat input is focused, but allow shift+enter for newlines
chatWindowInputTextbox.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") hideConvMenu();
  // optional: Esc closes modal
  if (e.key === "Escape" && persModal && !persModal.classList.contains("hidden")) {
    closeMemoryModal();
  }
});

// #endregion

// #region Context Menu Refresh Binding based on text input

// tell the RAG timer not to fire while typing actively.
chatWindowInputTextbox.addEventListener("input", () => {
  scheduleContextRefresh();
});

// #endregion

// #region Transcript Regen Bindings

window.addEventListener("beforeunload", () => {
  cancelScheduledTranscriptRefresh();
  if (conversationId) {
    flushConversationTranscriptArtifact(conversationId, "unload", true);
  }
});

// #endregion

// #endregion

(async function boot() {
  bootLog("[boot] start");
  try {
    bootLog("[boot] fetchUiConfig");
    await fetchUiConfig();
    bootLog("[boot] fetchAppConfig");
    await fetchAppConfig();

    bootLog("[boot] initABUI");
    initABUI();

    bootLog("[boot] bindModelSelect");
    bindModelSelect();
    // Now does both model selects if present

    bootLog("[boot] refreshModels");
    await refreshModels();
    // advancedMode restored already; just apply once

    bootLog("[boot] applyAdvancedVisibility");
    applyAdvancedVisibility();

    bootLog("[boot] fetchConversations");
    const conversations = await fetchConversations();

    bootLog("[boot] fetchProjects");
    const projects = await fetchProjects();

    bootLog("[boot] renderProjects");
    renderProjects(projects, conversations);
    bootLog("[boot] renderConversations");
    renderConversations(conversations);

    const saved = localStorage.getItem("callie_mvp_conversation_id");
    bootLog("[boot] pick conversation", { saved, count: conversations.length });

    if (saved && conversationMap.has(saved)) {
      bootLog("[boot] select saved");
      await selectConversation(saved);
    } else if (conversations.length) {
      bootLog("[boot] select first");
      await selectConversation(conversations[0].id);
    } else {
      bootLog("[boot] newChat");
      await newChat();
    }

    bootLog("[boot] loadPersonalization");
    await loadPersonalization();
    bootLog("[boot] loadMemories");
    await loadMemories();
    await refreshContext();

    bootLog("[boot] refreshContext");
    await refreshContext();

    bootLog("[boot] refreshGlobalFilesState");
    await refreshGlobalFilesState();

    bootLog("[boot] done");
  } catch (e) {
    console.error("[boot] FAILED", e);
    try {
      addMsgTextOnly("assistant", `UI boot failed: ${e?.message || e}`);
    } catch {}
  }
})();