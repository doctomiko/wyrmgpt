
// ----------------------------------
// DOM references
// ----------------------------------

// Usually const but some are reassigned later

const modelSelectA = document.getElementById("modelSelectA");
const modelSelectB = document.getElementById("modelSelectB");

const chatEl = document.getElementById("chat");
const inputEl = document.getElementById("input");
const newBtn = document.getElementById("newChat");
const manageFilesTopBtn = document.getElementById("manageFilesTop");
const sendBtn = document.getElementById("send");
const chatMenuButton = document.getElementById("chatMenuButton");
const chatMenu = document.getElementById("chatMenu");
const advancedCheckbox = document.getElementById("advancedCheckbox");
const convListEl = document.getElementById("convList");
const chatTitleEl = document.getElementById("chatTitle");
const renameBtn = document.getElementById("renameChat");
const suggestBtn = document.getElementById("suggestChat");
const pinTextEl = document.getElementById("pinText");
const addPinBtn = document.getElementById("addPin");
const pinListEl = document.getElementById("pinList");
const memoryTextEl = document.getElementById("memoryText");
const memoryTagsEl = document.getElementById("memoryTags");
const memoryImportanceEl = document.getElementById("memoryImportance");
const saveMemoryBtn = document.getElementById("saveMemory");

const convMenuEl = document.getElementById("convMenu");
const menuRenameBtn = document.getElementById("menuRename");
const menuSuggestBtn = document.getElementById("menuSuggest");

const menuMoveToBtn = document.getElementById("menuMoveTo");
const moveToModal = document.getElementById("moveToModal");
const moveToInput = document.getElementById("moveToInput");
const moveToDatalist = document.getElementById("moveToDatalist");
const moveToClose = document.getElementById("moveToClose");
const moveToCancel = document.getElementById("moveToCancel");
const moveToClear = document.getElementById("moveToClear");
const moveToApply = document.getElementById("moveToApply");
const moveToBackdrop = moveToModal ? moveToModal.querySelector(".modalBackdrop") : null;

const menuSummarizeBtn = document.getElementById("menuSummarize");
const menuArchiveBtn = document.getElementById("menuArchive");
const menuDeleteBtn = document.getElementById("menuDelete");

const projectListEl = document.getElementById("projectList");
const conversationListEl = convListEl; // document.getElementById("conversationList");
const newProjectBtn = document.getElementById("newProjectBtn");
const toggleContextBtn = document.getElementById("toggleContext");
const contextPreviewEl = document.getElementById("contextPreview");

const openMemoryBtn = document.getElementById("openMemory");
const memoryModal = document.getElementById("memoryModal");
const closeMemoryBtn = document.getElementById("closeMemory");
const memoryBackdrop = memoryModal
  ? memoryModal.querySelector(".modalBackdrop")
  : null;

const projMenuEl = document.getElementById("projMenu");
const projRenameBtn = document.getElementById("projRename");
const projDescBtn = document.getElementById("projDesc");
const projUploadBtn = document.getElementById("projUpload");

const attachBtn = document.getElementById("attachButton");
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

const convViewFilesBtn = document.getElementById("menuConvViewFiles");
const projFilesBtn = document.getElementById("projFiles");

const filesModal = document.getElementById("filesModal");
const filesListEl = document.getElementById("filesList");
const filesCloseBtn = document.getElementById("filesClose");
const filesSaveBtn = document.getElementById("filesSave");
const filesCloseBottomBtn = document.getElementById("filesCloseBottom");
const filesBackdrop = filesModal ? filesModal.querySelector(".modalBackdrop") : null;

// ----------------------------------
// Global variables we'll need later
// ----------------------------------

// Note: Some globals are in the regions where their functions use them.

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
// Upload modal state:
let uploadProjectIdForced = null;
// Files modal state:
let filesModalMode = null; // "conversation" | "project" | "global" | "all"
let filesModalConversationId = null;
let filesModalProjectId = null;
let hasAnyFiles = false;
let UI_TIMEZONE = null; // TZ for display
const ZEIT_PREFIX_RE = /^\s*(?:⟂ts=\d+|⟂t=\d{8}T\d{6}Z(?:\s+⟂age=\d+)?)\s*\n/;
const LEGACY_PREFIX_RE = /^\s*\[20\d\d-[^\]]+\]\s*\n/;

// ----------------------------------
// Helpers for UI state management and updates. 
// ----------------------------------

async function fetchUiConfig() {
  try {
    const cfg = await fetchJsonDebug("/api/ui_config");
    UI_TIMEZONE = (cfg && cfg.timezone) ? String(cfg.timezone) : null;
  } catch {
    UI_TIMEZONE = null;
  }
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

    if (UI_TIMEZONE) {
      return new Intl.DateTimeFormat(undefined, { ...opts, timeZone: UI_TIMEZONE }).format(d);
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

// A consistent look/feel for headers above chat messages, with optional timestamps and buttons.
function buildMetaBar({ labelText = null, timeIso = null, includeButton = false }) {
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

  metaBar.appendChild(left);

  let btn = null;
  if (includeButton) {
    btn = document.createElement("button");
    btn.className = "abChoose";
    btn.textContent = "Use";
    metaBar.appendChild(btn);
  }

  return { metaBar, timeSpan, btn };
}

async function loadMessages(cid) {
  return await fetchJsonDebug(`/api/conversation/${cid}/messages`);
}

async function fetchContext(cid, previewLimit = 20) {
  return await fetchJsonDebug(`/api/conversation/${cid}/context?preview_limit=${previewLimit}`);
}

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

function toggleChatMenu(forceState) {
  if (!chatMenu) return;
  const shouldShow = forceState !== undefined
    ? forceState
    : chatMenu.classList.contains("hidden");
  if (shouldShow) {
    chatMenu.classList.remove("hidden");
  } else {
    chatMenu.classList.add("hidden");
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

// #region Debug Helpers

const DEBUG_BOOT = true;

function bootLog(...args) {
  if (DEBUG_BOOT) console.log(...args);
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

// #region Memory modal helpers

function openMemoryModal() {
  if (!memoryModal) return;
  memoryModal.classList.remove("hidden");
}

function closeMemoryModal() {
  if (!memoryModal) return;
  memoryModal.classList.add("hidden");
}

// #endregion

// #region Message rendering helpers

function addMsgTextOnly(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return div;
}

function escapeHtml(s) {
  if (!s) return "";
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function addAssistantMsgWithModel(modelId, initialText, createdAtIso) {
  let labelText = "Unknown model";
  if (modelId) {
    const m = findModelById(modelId);
    labelText = m ? m.display_name : modelId;
  }

  // Outer wrapper just groups label + bubble
  const wrapper = document.createElement("div");
  wrapper.className = "msgWithModel assistantWrap";
  // Label bar above the bubble
  const { metaBar } = buildMetaBar({ labelText, timeIso: createdAtIso || null, includeButton: false });
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

  const body = document.createElement("div");
  body.className = "msgBody";
  body.innerHTML = renderMarkdown(stripZeit(initialText) || "");

  bubble.appendChild(body);
  wrapper.appendChild(bubble);

  chatEl.appendChild(wrapper);
  chatEl.scrollTop = chatEl.scrollHeight;

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
  chatEl.appendChild(wrapper);
  chatEl.scrollTop = chatEl.scrollHeight;
  return bubble;
}

function addMsg(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.innerHTML = renderMarkdown(stripZeit(text));

  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return div;
}

function clearChat() {
  chatEl.innerHTML = "";
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
      addAssistantMsgWithModel(modelId, msg.content || "", msg.created_at || null);
    } else if (msg.role === "user") {
      addUserMsgWithTime(msg.content || "", msg.created_at || null);
    } else {
      addMsg(msg.role, msg.content || "");
    }
    i += 1;
  }
}

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
  // Restore canonical choice if we know it
  if (canonicalA) {
    markCanonical(rowEl, "A");
  } else if (canonicalB) {
    markCanonical(rowEl, "B");
  }
}

function addABRow(modelA, modelB,  createdAtIsoA = null, createdAtIsoB = null) {
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

    left.appendChild(label);
    left.appendChild(timeEl);

    meta.appendChild(left); // left now contains both label and time
    //meta.appendChild(label);
    meta.appendChild(btn);

    const msg = document.createElement("div");
    msg.className = "msg assistant abMsg";
    msg.textContent = "Thinking…";

    col.appendChild(meta);
    col.appendChild(msg);

    return { col, meta, label, btn, msg, timeEl };
  };

  let safeLabelA = modelA && modelA.trim() ? modelA : "Unknown Model A";
  if (safeLabelA == "model A") safeLabelA = "Unknown Model A";
  const { col: colA, label: labelA, btn: btnA, msg: msgA, timeEl: timeElA } =
    makeCol(`A · ${safeLabelA}`, createdAtIsoA);
  let safeLabelB = modelB && modelB.trim() ? modelB : "Unknown Model B";
  if (safeLabelB == "model B") safeLabelB = "Unknown Model B";
  const { col: colB, label: labelB, btn: btnB, msg: msgB, timeEl: timeElB } =
    makeCol(`B · ${safeLabelB}`, createdAtIsoB);

  row.appendChild(colA);
  row.appendChild(colB);
  chatEl.appendChild(row);
  chatEl.scrollTop = chatEl.scrollHeight;

  btnA.addEventListener("click", () => chooseCanonical(row, "A"));
  btnB.addEventListener("click", () => chooseCanonical(row, "B"));

  return { rowEl: row, msgAEl: msgA, msgBEl: msgB, labelAEl: labelA, labelBEl: labelB, timeAEl: timeElA, timeBEl: timeElB };
}

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

  const m = document.createElement("div");
  m.className = "convMeta";
  m.textContent = formatReadableDateTime(c.created_at); //convMetaText(c);
  // You can swap created_at for updated_at later if you add it to the API.

  item.appendChild(t);
  item.appendChild(m);

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
  convListEl.innerHTML = "";

  const unassigned = (conversations || []).filter(c => c.project_id == null);

  unassigned.forEach(c => {
    convListEl.appendChild(makeConversationItem(c));
  });

  updateChatTitle();
}

function updateChatTitle() {
  const meta = conversationMap.get(conversationId);
  chatTitleEl.textContent = meta?.title || "…";
}

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

function renderContext(ctx) {
  const lines = [];
  const total = ctx.assembled_input_count || 0;
  const previewLimit = ctx.assembled_input_preview_limit ?? 20;
  const truncated = !!ctx.assembled_input_preview_truncated;

  const stats = ctx.token_stats || {};
  const approxTokens = stats.approx_text_tokens;
  const numImages = stats.num_images;
  const totalChars = stats.total_chars;

  let previewNote;
  if (truncated) {
    previewNote = `showing last ${previewLimit} in preview`;
  } else {
    previewNote = `showing all ${total} in preview`;
  }

  lines.push(`Conversation: ${ctx.conversation_id}`);
  lines.push("");
  lines.push("CONTEXT STATS:");
  lines.push(`Token and character counts are approximate and may not reflect the exact input to the model, but can be used for rough estimation and debugging.`);
  lines.push(`  Assembled messages: ${total} (${previewNote})`);
  lines.push(`  Context load: ~${approxTokens} text tokens; ${totalChars} characters; ${numImages} images;`);
  lines.push("");

  lines.push("SYSTEM:");
  lines.push(ctx.system_prompt || "");
  lines.push("");

  lines.push(`PINNED (${(ctx.pinned_memories || []).length}):`);
  if ((ctx.pinned_memories || []).length) {
    for (const t of ctx.pinned_memories) lines.push(`- ${t}`);
  } else {
    lines.push("(none)");
  }
  lines.push("");

  lines.push(`SUMMARY:`);
  lines.push((ctx.summary || "").trim() || "(none)");
  lines.push("");

  lines.push(`RETRIEVED (${(ctx.retrieved_memories || []).length}):`);
  if ((ctx.retrieved_memories || []).length) {
    for (const t of ctx.retrieved_memories) lines.push(`- ${t}`);
  } else {
    lines.push("(none)");
  }
  lines.push("");

  lines.push("INPUT PREVIEW (tail):");
  for (const m of (ctx.assembled_input_preview || [])) {
    lines.push(`${(m.role || "??").toUpperCase()}: ${m.content || ""}`);
    lines.push("");
  }

  contextPreviewEl.textContent = lines.join("\n");
}

async function refreshContext() {
  if (!conversationId) return;
  const limit = contextExpanded ? 200 : 20;
  const ctx = await fetchContext(conversationId, limit);
  renderContext(ctx);
  toggleContextBtn.textContent = contextExpanded ? "Show less" : "Show more";
}

// #endregion

// #region Sending messages

async function send() {
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = "";

  // Base model from A
  const modelA = modelSelectA?.value || null;
  let modelB = modelA;
  // If B is visible and has a value, use it
  if (modelSelectB && modelSelectB.style.display !== "none") {
    const v = (modelSelectB.value || "").trim();
    if (v) modelB = v;
  }

  const mA = findModelById(modelSelectA.value);
  const metaA = {
    ab_group: "A",
    canonical: true,
    model: mA ? mA.display_name : modelSelectA.value
  };
  const mB = findModelById(modelSelectB.value);
  const metaB = {
    ab_group: "B",
    canonical: false,
    model: mB ? mB.display_name : modelSelectB.value
  };

  const useAB =
    typeof advancedMode !== "undefined" &&
    advancedMode &&
    modelSelectB &&
    modelSelectB.style.display !== "none" &&
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
    chatEl.scrollTop = chatEl.scrollHeight;
  }

  //const conversations = await fetchConversations();
  //renderConversations(conversations);
  await refreshConversationLists();
  await refreshContext();
}

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

// #region Memory Pin helpers

async function fetchPins() {
  return await fetchJsonDebug("/api/memory/pins");
}

function renderPins(pins) {
  pinListEl.innerHTML = "";
  if (!pins.length) {
    const empty = document.createElement("div");
    empty.className = "memPlaceholder";
    empty.textContent = "No pinned memories yet. Add one, and we’ll treat it as canon later.";
    pinListEl.appendChild(empty);
    return;
  }

  pins.forEach(p => {
    const item = document.createElement("div");
    item.className = "pinItem";

    const text = document.createElement("div");
    text.className = "pinText";
    text.textContent = p.text;

    const actions = document.createElement("div");
    actions.className = "pinActions";

    const del = document.createElement("button");
    del.textContent = "Delete";
    del.addEventListener("click", async () => {
      await fetch(`/api/memory/pins/${p.id}`, { method: "DELETE" });
      const pins2 = await fetchPins();
      renderPins(pins2);
      await refreshContext(); // pins affect context pack
    });

    actions.appendChild(del);
    item.appendChild(text);
    item.appendChild(actions);
    pinListEl.appendChild(item);
  });
}

async function addPin() {
  const text = (pinTextEl.value || "").trim();
  if (!text) return;
  pinTextEl.value = "";

  await fetch("/api/memory/pins", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text })
  });

  const pins = await fetchPins();
  renderPins(pins);
  await refreshContext();
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

  try {
    // 1) Create the memory
    const res = await fetch("/api/memories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content,
        importance,
        tags
      })
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert("Failed to create memory: " + (err.detail || res.status));
      return;
    }

    const data = await res.json();
    const memoryId = data.id;
    if (!memoryId) {
      console.warn("createMemory: no id in response", data);
      return;
    }

    // 2) Link to current conversation, if any
    if (conversationId) {
      const resLinkConv = await fetch(
        `/api/memories/${encodeURIComponent(memoryId)}/link_conversation/${encodeURIComponent(conversationId)}`,
        { method: "POST" }
      );
      if (!resLinkConv.ok) {
        console.warn("Failed to link memory to conversation", await resLinkConv.text());
      }
    }

    // 3) Link to current project, if the conversation has one
    const meta = conversationMap.get(conversationId);
    const pid = meta?.project_id ?? null;
    if (pid != null) {
      const resLinkProj = await fetch(
        `/api/memories/${encodeURIComponent(memoryId)}/link_project/${pid}`,
        { method: "POST" }
      );
      if (!resLinkProj.ok) {
        console.warn("Failed to link memory to project", await resLinkProj.text());
      }
    }

    // 4) Clean up UI & refresh context
    memoryTextEl.value = "";
    if (memoryTagsEl) memoryTagsEl.value = "";
    if (memoryImportanceEl) memoryImportanceEl.value = "0";

    await refreshContext();
  } catch (e) {
    console.error("createMemoryFromUi failed", e);
    alert("Error creating memory – see console for details.");
  }
}

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
      chatEl.innerHTML = "";
      contextPreviewEl.textContent = "Loading…";
      chatTitleEl.textContent = "New chat";
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
  menuTargetConversationId = targetId;
  positionMenu(convMenuEl, e.clientX, e.clientY);
  if (convViewFilesBtn) {
    // pessimistically disable, then re-enable if we find files
    setFilesButtonEnabled(convViewFilesBtn, false);
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

  suggestBtn.disabled = true;
  suggestBtn.textContent = "Thinking…";
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
    suggestBtn.disabled = false;
    suggestBtn.textContent = "Suggest";
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
    // reload that conversation so the new summary message appears
    await loadConversation(conversationId);
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
  if (!projectListEl) return;

  projectsCache = projects || [];
  projectListEl.innerHTML = "";

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
      positionMenu(projMenuEl, ev.clientX, ev.clientY);
      //projMenuEl.style.left = `${ev.clientX}px`;
      //projMenuEl.style.top = `${ev.clientY}px`;
      //projMenuEl.classList.remove("hidden");
      if (projFilesBtn) {
        setFilesButtonEnabled(projFilesBtn, false);
        refreshProjectFilesState(p.id);
      }
    });

    const children = document.createElement("div");
    children.className = "projConvs";
    if (!expanded) children.classList.add("hidden");

    convs.forEach(c => {
      children.appendChild(makeConversationItem(c));
    });

    block.appendChild(header);
    block.appendChild(children);
    projectListEl.appendChild(block);
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

function openUploadModal(forceScope, explicitProjectId) {
  if (!uploadModal) return;

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

  const form = new FormData();
  files.forEach(f => form.append("files", f));

  const params = new URLSearchParams();
  params.set("scope_type", scope);
  if (payloadConversationId) params.set("conversation_id", payloadConversationId);
  if (payloadProjectId != null) params.set("project_id", String(payloadProjectId));

  const prevSendDisabled = sendBtn.disabled;
  const prevInputDisabled = inputEl.disabled;
  const prevAttachDisabled = attachBtn ? attachBtn.disabled : false;

  sendBtn.disabled = true;
  inputEl.disabled = true;
  if (attachBtn) attachBtn.disabled = true;
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
    sendBtn.disabled = prevSendDisabled;
    inputEl.disabled = prevInputDisabled;
    if (attachBtn) attachBtn.disabled = prevAttachDisabled;
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

  let url;
  if (filesModalMode === "conversation") {
    if (!filesModalConversationId) return;
    url = `/api/conversations/${encodeURIComponent(filesModalConversationId)}/files`;
  } else if (filesModalMode === "project") {
    if (filesModalProjectId == null) return;
    url = `/api/projects/${encodeURIComponent(filesModalProjectId)}/files`;
  } else if (filesModalMode === "all") {
    url = "/api/files";
  } else {
    return;
  }
  // TODO change above branches to also support "global" and sandbox+id

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
    const data = await res.json();
    const files = data.files || [];

    if (!files.length) {
      filesListEl.textContent = "No files yet.";
      return;
    }

    const container = document.createElement("div");
    container.className = "filesListTable";

    files.forEach(file => {
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
      descInput.addEventListener("change", () => {
        saveFileDescription(file.id, descInput.value);
      });

      row.appendChild(nameSpan);
      row.appendChild(descInput);
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
  if (!manageFilesTopBtn) return;
  try {
    const data = await fetchJsonDebug("/api/files/summary");
    const total = data?.total ?? 0;
    hasAnyFiles = total > 0;
    setFilesButtonEnabled(manageFilesTopBtn, hasAnyFiles);
  } catch (err) {
    console.error("files summary error", err);
    // On error, don't hard-disable the button
    setFilesButtonEnabled(manageFilesTopBtn, true);
  }
}

async function refreshConversationFilesState(convId) {
  if (!convViewFilesBtn || !convId) return;
  try {
    const res = await fetch(`/api/conversations/${encodeURIComponent(convId)}/files`);
    if (!res.ok) throw new Error("status " + res.status);
    const data = await res.json();
    const hasFiles = (data.files || []).length > 0;
    setFilesButtonEnabled(convViewFilesBtn, hasFiles);
  } catch (err) {
    console.error("conv files state error", err);
    setFilesButtonEnabled(convViewFilesBtn, false);
  }
}

async function refreshProjectFilesState(projectId) {
  if (!projFilesBtn || projectId == null) return;
  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/files`);
    if (!res.ok) throw new Error("status " + res.status);
    const data = await res.json();
    const hasFiles = (data.files || []).length > 0;
    setFilesButtonEnabled(projFilesBtn, hasFiles);
  } catch (err) {
    console.error("project files state error", err);
    setFilesButtonEnabled(projFilesBtn, false);
  }
}

// #endregion

// ----------------------------------
// Event bindings and UI initialization
// ----------------------------------

// #region Event bindings

// #region File upload event bindings

if (attachBtn && uploadModal) {
  attachBtn.addEventListener("click", () => {
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
if (projUploadBtn) {
  projUploadBtn.addEventListener("click", () => {
    const pid = menuTargetProjectId;
    projMenuEl.classList.add("hidden");
    if (!pid) return;
    openUploadModal("project", pid);
  });
}

// #endregion

// #region File management event bindings

if (convViewFilesBtn) {
  convViewFilesBtn.addEventListener("click", () => {
    convMenuEl.classList.add("hidden");
    const cid = menuTargetConversationId || conversationId;
    if (!cid) {
      alert("No conversation selected.");
      return;
    }
    openFilesModalForConversation(cid);
  });
}

if (projFilesBtn) {
  projFilesBtn.addEventListener("click", () => {
    projMenuEl.classList.add("hidden");
    const pid = menuTargetProjectId;
    if (!pid) {
      alert("No project selected.");
      return;
    }
    openFilesModalForProject(pid);
  });
}

if (manageFilesTopBtn) {
  manageFilesTopBtn.addEventListener("click", () => {
    if (manageFilesTopBtn.classList.contains("files-disabled")) {
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

// #region Conversation & chat menu event bindings

if (chatMenuButton) {
  chatMenuButton.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleChatMenu();
  });
}
if (chatMenu) {
  chatMenu.addEventListener("click", (e) => {
    // don't let clicks inside menu bubble up and close it
    e.stopPropagation();
  });
}

sendBtn.addEventListener("click", send);
newBtn.addEventListener("click", newChat);

// #endregion

// #region Memory and Pin event bindings

if (addPinBtn) {
  addPinBtn.addEventListener("click", addPin);
}
if (saveMemoryBtn) {
  saveMemoryBtn.addEventListener("click", () => {
    createMemoryFromUi().catch(e => console.error("createMemoryFromUi error", e));
  });
}

if (openMemoryBtn) {
  openMemoryBtn.addEventListener("click", () => {
    openMemoryModal();
    // hide the chat menu when opening modal, so it doesn't float over
    toggleChatMenu(false);
  });
}
if (closeMemoryBtn) {
  closeMemoryBtn.addEventListener("click", closeMemoryModal);
}
if (memoryBackdrop) {
  memoryBackdrop.addEventListener("click", closeMemoryModal);
}

// #endregion

// #region Chat buttons in the top panel (now hidden)
if (renameBtn) {
  renameBtn.addEventListener("click", renameChat);
}
if (suggestBtn) {
  suggestBtn.addEventListener("click", suggestChatTitle);
}
// #endregion

// #region Conversation context menu event bindings

if (menuRenameBtn) {
  menuRenameBtn.addEventListener("click", async () => {
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

if (menuSuggestBtn) {
  menuSuggestBtn.addEventListener("click", async () => {
    const cid = menuTargetConversationId;
    if (!cid) return;

    menuSuggestBtn.disabled = true;
    menuSuggestBtn.textContent = "Thinking…";
    try {
      await fetch(`/api/conversation/${cid}/suggest_title`, { method: "POST" });
    } finally {
      menuSuggestBtn.disabled = false;
      menuSuggestBtn.textContent = "Suggest";
    }

    hideConvMenu();

    const conversations = await fetchConversations();
    renderConversations(conversations);

    if (cid === conversationId) {
      await refreshContext();
    }
  });
}

if (menuSummarizeBtn) {
  menuSummarizeBtn.addEventListener("click", async () => {
    const cid = getMenuCid();
    if (!cid) return;
    hideConvMenu();
    await summarizeConversation(cid);
  });
}

if (menuMoveToBtn) {
  menuMoveToBtn.addEventListener("click", async () => {
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

if (menuArchiveBtn) {
  menuArchiveBtn.addEventListener("click", async () => {
    const cid = getMenuCid();
    if (!cid) return;
    hideConvMenu();
    await archiveConversation(cid, true);
  });
}

if (menuDeleteBtn) {
  menuDeleteBtn.addEventListener("click", async () => {
    const cid = getMenuCid();
    if (!cid) return;
    hideConvMenu();
    await deleteConversationWithConfirmation(cid, getMenuTitle(cid));
  });
}

if (toggleContextBtn) {
  toggleContextBtn.addEventListener("click", async () => {
    contextExpanded = !contextExpanded;
    await refreshContext();
  });
}

// #endregion

// #region Model select event bindings

if (advancedCheckbox) {
  // restore saved setting
  advancedMode = localStorage.getItem("chatoss.advanced") === "1";
  advancedCheckbox.checked = advancedMode;

  advancedCheckbox.addEventListener("change", () => {
    advancedMode = advancedCheckbox.checked;
    localStorage.setItem("chatoss.advanced", advancedMode ? "1" : "0");
    applyAdvancedVisibility();
  });
}

if (modelSelectA) {
  modelSelectA.addEventListener("change", () =>
    updateModelInfo("A")
  );
}
if (modelSelectB) {
  modelSelectB.addEventListener("change", () =>
    updateModelInfo("B")
  );
}

// #endregion

// #region Project management menu event bindings

if (newProjectBtn) {
  newProjectBtn.addEventListener("click", async () => {
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

if (projRenameBtn) {
  projRenameBtn.addEventListener("click", async () => {
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

if (projDescBtn) {
  projDescBtn.addEventListener("click", async () => {
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

// bind send to enter when chat input is focused, but allow shift+enter for newlines
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

document.addEventListener("click", (e) => {
  if (!convMenuEl.classList.contains("hidden") && !convMenuEl.contains(e.target))
    hideConvMenu();
  // if click is outside menu, hide it
  if (projMenuEl && !projMenuEl.classList.contains("hidden") && !projMenuEl.contains(e.target))
    projMenuEl.classList.add("hidden");
  // clicking anywhere else closes the menu
  toggleChatMenu(false);
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") hideConvMenu();
  // optional: Esc closes modal
  if (e.key === "Escape" && memoryModal && !memoryModal.classList.contains("hidden")) {
    closeMemoryModal();
  }
});

// #endregion

(async function boot() {
  bootLog("[boot] start");
  try {
    bootLog("[boot] fetchUiConfig");
    await fetchUiConfig();

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

    bootLog("[boot] fetchPins");
    const pins = await fetchPins();

    bootLog("[boot] renderPins");
    renderPins(pins);

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