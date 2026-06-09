// chatgpt_dom_adapter.js
// Single-file DOM adapter for chatgpt.com
// Paste into DevTools Snippets OR use as a content script later.

(function () {
  console.log("[ChatGPTDOM] loading adapter");

  // #region Config Management

  const _DEBUG_MODE = true;
    
  async function loadConfig() {
    const cfg = await storageGet();
    if (!cfg) return;
    applyConfig(cfg);
  }

  function saveConfig(data) {
    storageSet(data);
  }

  let exportConfig = null;
  let keyBindings = null;

  function applyConfig(cfg) {
    exportConfig = structuredClone(cfg.exportConfig);
    keyBindings = structuredClone(cfg.keyBindings);
    checkConflicts(keyBindings).then(conflicts => {
      if (conflicts.length > 0) {
        console.warn("[ChatGPTDOM] Found conflicts in key bindings:", conflicts);
      }
    });
    //warnOnKnownBrowserConflicts();
  }

  const api = typeof browser !== "undefined" ? browser : chrome;
  function storageGet() {
    return api.runtime.sendMessage({ type: "GET_CONFIG" });
  }
  function storageSet(data) {
    return api.runtime.sendMessage({ type: "SET_CONFIG", payload: data });
  }
  async function checkConflicts(keyBindings) {
    const response = await api.runtime.sendMessage({
      type: "CHECK_CONFLICTS",
      payload: keyBindings
    });
    return response?.conflicts || [];
  }  

  // #endregion

  // #region Conversation Context Change Detection

  let lastConversationId = null;

  function getConversationId() {
    const m = location.pathname.match(/\/c\/([^/]+)/);
    return m ? m[1] : null;
  }

  function observeConversationChanges() {
    const observer = new MutationObserver(() => {
      const currentId = getConversationId();
      // Ignore states where there is no conversation yet
      if (!currentId) return;
  
      // Either first time seeing a conversation or
      // Conversation switch detected
      if (lastConversationId === null || currentId !== lastConversationId) {
        // Record the new conversation ID
        lastConversationId = currentId;
        // Actions to take on conversation switch:        
        if (_DEBUG_MODE) {
          console.debug("Conversation new or changed:", lastConversationId);
        }
        resetStore(true);
        // Only trigger backup on actual conversation navigation,
        // not on every store rebuild.
        backupCurrentConversationOnce();
      }
    });
  
    observer.observe(document.body, {
      childList: true,
      subtree: true
    });

    return observer;
  }

  // #endregion

  // #region DOM Parsing

  function getThreadRoot() {
    return document.querySelector("main #thread");
  }

  function getMessageNodes() {
    const thread = getThreadRoot();
    if (!thread) return [];
    return Array.from(thread.querySelectorAll("article"));
  }

  function getRoleFromArticle(article) {
    const roleDiv = article.querySelector("[data-message-author-role]");
    if (roleDiv) {
      const role = roleDiv.getAttribute("data-message-author-role");
      if (role === "user" || role === "assistant") return role;
    }

    const h5 = article.querySelector("h5");
    const h6 = article.querySelector("h6");
    if (h5 && /you said/i.test(h5.textContent)) return "user";
    if (h6 && /chatgpt said/i.test(h6.textContent)) return "assistant";

    return "unknown";
  }

  function isMeaningfulContentNode(node) {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) return false;
    if (node.classList.contains("whitespace-pre-wrap")) return true;

    return Array.from(node.children).some(child =>
      ["P", "PRE", "UL", "OL", "TABLE"].includes(child.tagName)
    );
  }

  function getContentRoot(article) {
    const roleDiv = article.querySelector("[data-message-author-role]");
    if (!roleDiv) return null;

    let node = roleDiv;

    while (node) {
      if (isMeaningfulContentNode(node)) return node;

      if (node.children.length === 1 && node.children[0].tagName === "DIV") {
        node = node.children[0];
      } else {
        break;
      }
    }

    return roleDiv;
  }

  function getDomId(article) {
    // Preferred: real message GUID (newer UI)
    const msgNode = article.querySelector('[data-message-id]');
    if (msgNode) {
      const id = msgNode.getAttribute('data-message-id');
      if (id) return id;
    }
  
    // Fallback: older conversation-turn IDs (if they reappear)
    const legacy = article.querySelector('[data-test-id^="conversation-turn"]');
    if (legacy) {
      return legacy.getAttribute('data-test-id');
    }
  
    // Last resort: null (hash will be used)
    return null;
  }

  function extractBlocks(contentRoot) {
    if (!contentRoot) return [];

    if (contentRoot.classList.contains("whitespace-pre-wrap")) {
      return [{ type: "paragraph", text: contentRoot.innerText }];
    }

    const blocks = [];

    for (const child of contentRoot.children) {
      if (child.tagName === "P") {
        blocks.push({ type: "paragraph", text: child.innerText });
      }
      else if (child.tagName === "PRE") {
        const code = child.querySelector("code");
        blocks.push({
          type: "code",
          language: code?.className || null,
          text: code?.innerText || child.innerText
        });
      }
      else if (child.classList.contains("whitespace-pre-wrap")) {
        blocks.push({ type: "paragraph", text: child.innerText });
      }
      else {
        blocks.push({
          type: "raw",
          text: child.innerText,
          html: child.innerHTML
        });
      }
    }

    return blocks;
  }

  function isVisible(el) {
    if (!el) return false;
  
    const style = getComputedStyle(el);
    if (style.display === "none") return false;
    if (style.visibility === "hidden") return false;
    if (style.opacity === "0") return false;
    if (el.offsetParent === null) return false;
  
    return true;
  }

  function showToast(message, duration = 2000) {
    const toast = document.createElement("div");
    toast.textContent = message;
  
    Object.assign(toast.style, {
      position: "fixed",
      bottom: "24px",
      right: "24px",
      padding: "10px 14px",
      background: "rgba(0,0,0,0.85)",
      color: "#fff",
      borderRadius: "6px",
      fontSize: "14px",
      zIndex: 99999,
      opacity: "0",
      transition: "opacity 150ms ease"
    });
  
    document.body.appendChild(toast);
    requestAnimationFrame(() => toast.style.opacity = "1");
  
    setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => toast.remove(), 200);
    }, duration);
  }

  function isTypingContext(e) {
    const el = document.activeElement;
    if (!el) return false;
    if (el.tagName === "TEXTAREA") return true;
    if (el.tagName === "INPUT") return true;
    if (el.isContentEditable) return true;
    return false;
  }

  // #endregion
  
  // #region Message Store

  const messageStore = {
    byId: new Map(),
    order: []
  };

  function isEphemeralMessage(message) {
    // No stable identity yet
    if (!message.dom_id) {
      // And no content yet
      if (!message.content.text || message.content.text.trim() === "") {
        return true;
      }
    }
    if (isPlaceholderRequest(message)) {
      return true;
    }
    return false;
  }

  function isPlaceholderRequest(message) {
    return typeof message.dom_id === "string" &&
           message.dom_id.startsWith("placeholder-request");
  }

  function resetStore(rebuild = false) {
    messageStore.byId.clear();
    messageStore.order.length = 0;
  
    if (!rebuild) return;
  
    const articles = getMessageNodes();
    for (const article of articles) {
      const parsed = parseMessage(article);
      // wait for messages with real content / real ID
      if (!isEphemeralMessage(parsed)) {
        upsertMessage(parsed);
      }
    }

    cleanStore();
  }

  function upsertMessage(message) {
    // If message has a real dom_id and we previously stored it provisionally,
    // we need to upgrade the ID.
    if (message.dom_id) {
      for (const [id, existing] of messageStore.byId.entries()) {
        if (existing.provisional && existing.content_hash === message.content_hash) {
          // Upgrade identity
          messageStore.byId.delete(id);
          existing.provisional = false;
          existing.dom_id = message.dom_id;
          existing.message_id = message.message_id;
  
          Object.assign(existing, message);
  
          messageStore.byId.set(message.message_id, existing);
          return existing;
        }
      }
    }

    // Normal upsert
    const id = message.message_id;
  
    if (messageStore.byId.has(id)) {
      Object.assign(messageStore.byId.get(id), message);
      return messageStore.byId.get(id);
    }
  
    messageStore.byId.set(id, message);
    messageStore.order.push(id);

    return message;
  }

  function assertStoreClean() {
    for (const msg of messageStore.byId.values()) {
      if (msg.provisional) {
        console.warn("Provisional message survived cleanup", msg);
      }
      if (msg.dom_id?.startsWith("placeholder-request")) {
        console.warn("placeholder-request in store; should not happen", msg);
      }
      if (!msg.dom_id && (!msg.content?.text || !msg.content.text.trim())) {
        console.warn("Empty/ephemeral message in store; should not happen", msg);
      }      
    }
  }

  function cleanStore() {
    for (let i = messageStore.order.length - 1; i >= 0; i--) {
      const id = messageStore.order[i];
      const msg = messageStore.byId.get(id);
  
      // Orphaned entry
      if (!msg) {
        messageStore.order.splice(i, 1);
        continue;
      }
  
      // 1) Drop placeholder-request nodes unconditionally
      if (
        typeof msg.dom_id === "string" &&
        msg.dom_id.startsWith("placeholder-request")
      ) {
        messageStore.byId.delete(id);
        messageStore.order.splice(i, 1);
        continue;
      }
  
      // 2) Drop empty shells (no dom_id + no text)
      if (
        !msg.dom_id &&
        (!msg.content?.text || msg.content.text.trim() === "")
      ) {
        messageStore.byId.delete(id);
        messageStore.order.splice(i, 1);
        continue;
      }
  
      // 3) Upgrade provisional messages that now have a real dom_id
      if (msg.provisional && msg.dom_id) {
        messageStore.byId.delete(id);
  
        msg.provisional = false;
        msg.message_id = msg.dom_id;
  
        messageStore.byId.set(msg.message_id, msg);
        messageStore.order[i] = msg.message_id;
        continue;
      }
  
      // 4) Drop provisional messages that somehow reached final without an ID
      if (msg.provisional && msg.final && !msg.dom_id) {
        messageStore.byId.delete(id);
        messageStore.order.splice(i, 1);
        continue;
      }
    }
  }

  function parseMessage(article) {
    const role = getRoleFromArticle(article);
    const contentRoot = getContentRoot(article);
  
    const text = contentRoot?.innerText || "";
    const html = contentRoot?.innerHTML || "";
  
    const content_hash = hashText(text);
    const dom_id = getDomId(article);
    // We're going to disambiguate synthetic_id further to prevent collisoons that are already very unlikely
    //const synthetic_id = dom_id ?? content_hash;
    const synthetic_id = dom_id ?? `${role}:${content_hash}`;
    const provisional = !dom_id;

    const isAssistant = role === "assistant";
    const final = isAssistant ? isAssistantFinal(article) : true;
    const streaming = isAssistant ? !final : false;
  
    return {
      message_id: synthetic_id,     // stable primary key
      dom_id,                       // real DOM identity if present
      content_hash,                 // deterministic fallback identity
      provisional,                  // ID not yet stable
  
      role,
      author: role,
  
      content: {
        text,
        blocks: extractBlocks(contentRoot),
        html
      },
  
      streaming,
      final,
  
      meta: {
        source: "chatgpt-dom",
        parsed_at: new Date().toISOString()
      }
    };
  }

  // #endregion
  
  // #region Chat File Transcript Backup and Download

  let lastAutoBackupCount = 0;
  let backupOnLoadDoneForConversation = new Set();

  function downloadText(filename, text, mime = "text/plain") {
    const blob = new Blob([text], { type: `${mime};charset=utf-8` });
    const url = URL.createObjectURL(blob);
  
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
  
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function getTimestamp() {
    const d = new Date();
    const pad = n => String(n).padStart(2, "0");
    return (
      d.getFullYear() +
      "-" + pad(d.getMonth() + 1) +
      "-" + pad(d.getDate()) +
      "_" + pad(d.getHours()) +
      "-" + pad(d.getMinutes()) +
      "-" + pad(d.getSeconds())
    );
  }

  function buildFilename(ext) {
    const convo = getConversationId() || "no-conversation";
    const ts = getTimestamp();
    return `chatgpt_${convo}_${ts}.${ext}`;
  }

  function maybeAutoBackup() {
    if (!exportConfig)
      loadConfig();
    const cfg = exportConfig.autoBackup;
    if (!cfg || cfg.enabled === undefined)
      console.warn("Auto-backup config missing; did you forget to loadConfig?", exportConfig);
    // If it isn't defined yet, do nothing
    if (!cfg?.enabled) return;
  
    const count = messageStore.order.length;
    const delta = count - lastAutoBackupCount;
  
    if (delta < exportConfig.autoBackup.everyNMessages) return;
  
    lastAutoBackupCount = count;
  
    for (const fmt of exportConfig.autoBackup.formats) {
      if (fmt === "json") exportAsJSON(true);
      if (fmt === "md") exportAsMarkdown(true);
      if (fmt === "html") exportAsHTML(true);
    }
  }

  function maybeBackupOnLoad() {
    const convoId = getConversationId();
    if (!convoId) return;
  
    if (!exportConfig)
      loadConfig();
    const cfg = exportConfig.backupOnLoad;
    if (!cfg || cfg.enabled === undefined)
      console.warn("Backup on load config missing; did you forget to loadConfig?", exportConfig);
    // If it isn't defined yet, do nothing
    if (!cfg?.enabled) return;
  
    if (backupOnLoadDoneForConversation.has(convoId)) return;
  
    backupOnLoadDoneForConversation.add(convoId);
  
    // Don't do this, that'd be a circular dependency between this function and backupCurrentConversationOnce
    //backupCurrentConversationOnce();
    for (const fmt of cfg.formats) {
      if (fmt === "json") exportAsJSON(true);
      if (fmt === "md") exportAsMarkdown(true);
      if (fmt === "html") exportAsHTML(true);
    }
    if (exportConfig.toastOnExport) {
      showToast("Backup on load complete");
    }
  }
  
  function exportConversation() {
    return messageStore.order.map(id => messageStore.byId.get(id));
  }
  
  function exportAsJSON(auto = false) {
    const data = exportConversation();
    const json = JSON.stringify(data, null, 2);
    downloadText(buildFilename("json"), json, "application/json");
    if (!auto && exportConfig.toastOnExport) showToast("Exported JSON");
  }

  function exportAsMarkdown(auto = false) {
    const messages = exportConversation();
  
    const md = messages.map(m => {
      const header = m.role === "assistant" ? "### Assistant" : "### User";
      const body = m.content?.text || "";
      return `${header}\n\n${body}\n`;
    }).join("\n");
  
    downloadText(buildFilename("md"), md, "text/markdown");
    if (!auto && exportConfig.toastOnExport) showToast("Exported Markdown");
  }

  function exportAsHTML(auto = false) {
    const messages = exportConversation();
  
    const body = messages.map(m => {
      const cls = m.role;
      const title = m.role === "assistant" ? "Assistant" : "User";
      const content = m.content?.html || "";
      return `
        <div class="message ${cls}">
          <h3>${title}</h3>
          <div class="content">${content}</div>
        </div>
      `;
    }).join("\n");
  
    const html = `<!doctype html>
  <html>
  <head>
  <meta charset="utf-8">
  <title>ChatGPT Conversation</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; }
    .message { margin-bottom: 2rem; }
    .user h3 { color: #444; }
    .assistant h3 { color: #0b5; }
    .content { white-space: pre-wrap; }
  </style>
  </head>
  <body>
  ${body}
  </body>
  </html>`;
  
    downloadText(buildFilename("html"), html, "text/html");
    if (!auto && exportConfig.toastOnExport) showToast("Exported HTML");
  }

  function backupCurrentConversationOnce() {
    const convoId = getConversationId();
    if (!convoId) return;
  
    backupOnLoadDoneForConversation.delete(convoId);
    maybeBackupOnLoad();
  }

  function backupCurrentConversationNow() {
    const convoId = getConversationId();
    if (!convoId) {
      showToast("No active conversation to back up");
      return;
    }
  
    const formats = exportConfig.backupOnLoad.formats;
  
    for (const fmt of formats) {
      if (fmt === "json") exportAsJSON(true);
      if (fmt === "md") exportAsMarkdown(true);
      if (fmt === "html") exportAsHTML(true);
    }
  
    showToast("Full conversation backup complete");
  }

  function toggleAutoBackup() {
    exportConfig.autoBackup.enabled = !exportConfig.autoBackup.enabled;
    saveConfig();
    showToast(
      `Auto-backup ${exportConfig.autoBackup.enabled ? "enabled" : "disabled"}`
    );
  }

  function toggleBackupOnLoad() {
    exportConfig.backupOnLoad.enabled = !exportConfig.backupOnLoad.enabled;
    saveConfig();
    showToast(
      `Backup on load ${exportConfig.backupOnLoad.enabled ? "enabled" : "disabled"}`
    );
  }
  // #endregion

  // #region KeyBindings

  const actions = {
    exportJSON: () => exportAsJSON(),
    exportMD: () => exportAsMarkdown(),
    exportHTML: () => exportAsHTML(),
    toggleAutoBackup: () => toggleAutoBackup(),
    toggleBackupOnLoad: () => toggleBackupOnLoad(),
    manualFullBackup: () => backupCurrentConversationOnce(),
    showKeyBindings: () => showKeyBindingsOverlay()
  };

  /*
  function applyKeyBindingOverrides(overrides) {
    for (const [name, combo] of Object.entries(overrides)) {
      if (keyBindings[name]) {
        keyBindings[name].combo = combo;
      }
    }
  }
  */

  function normalizeCombo(e) {
    const parts = [];
    if (e.ctrlKey) parts.push("Ctrl");
    if (e.shiftKey) parts.push("Shift");
    if (e.altKey) parts.push("Alt");
    if (e.metaKey) parts.push("Meta");
  
    // Normalize the key
    const key = e.key.length === 1
      ? e.key.toUpperCase()
      : e.key;
  
    parts.push(key);
    return parts.join("+");
  }

  function handleKeydown(e) {
    console.log("[ChatGPTDOM] keydown", e);
    const combo = normalizeCombo(e);
    console.log("Combo: ", combo);
    for (const [actionName, binding] of Object.entries(keyBindings)) {
      if (binding === combo && actions[actionName]) {
        console.log("Found matching key binding:", actionName);
        actions[actionName]();
        e.preventDefault();
        return;
      }
    }
  }

  function listKeyBindings() {
    return Object.entries(keyBindings).map(([action, binding]) => ({
      action,
      binding
    }));
  }

  function showKeyBindingsOverlay() {
    const overlay = document.createElement("div");
  
    const rows = listKeyBindings()
      .map(b => `<tr><td>${b.action}</td><td>${b.binding}</td></tr>`)
      .join("");
  
    overlay.innerHTML = `
      <div style="
        position: fixed;
        top: 15%;
        left: 50%;
        transform: translateX(-50%);
        background: #111;
        color: #fff;
        padding: 16px;
        border-radius: 8px;
        z-index: 100000;
        max-width: 80%;
        box-shadow: 0 10px 30px rgba(0,0,0,0.5);
      ">
        <h3 style="margin-top:0">Callie Hotkeys</h3>
        <table style="width:100%; border-collapse: collapse">
          ${rows}
        </table>
        <div style="text-align:right; margin-top:12px">
          <button id="close-hotkeys">Close</button>
        </div>
      </div>
    `;
  
    document.body.appendChild(overlay);
    overlay.querySelector("#close-hotkeys").onclick = () => overlay.remove();
  }

  // #endregion
  
  // #region Text Entry Input

  function injectUserMessage(text, options = {}) {
    const { replace = false } = options;
  
    const composer = document.querySelector('form[data-type="unified-composer"]');
    if (!composer) throw new Error("Composer form not found");
  
    const inputDiv = composer.querySelector('#prompt-textarea[contenteditable="true"]');
    if (!inputDiv) throw new Error("Prompt textarea div not found");

    inputDiv.focus();

    if (replace) {
      inputDiv.innerHTML = "";
    }

    if (true) {
      // Prepend spacing if appending
      const payload = replace
        ? text
        : (inputDiv.innerText.trim() ? "\n\n" + text : text);
  
      document.execCommand("insertText", false, payload);
    } else {
      if (inputDiv.childNodes.length > 0) {
        const last = inputDiv.lastChild;
        if (last.nodeType === Node.ELEMENT_NODE && last.tagName === "P") {
          const spacer = document.createElement("p");
          spacer.textContent = "";
          inputDiv.appendChild(spacer);
        }
      }
    
      const lines = text.split(/\n{2,}/);
      for (const line of lines) {
        const p = document.createElement("p");
        p.textContent = line;
        inputDiv.appendChild(p);
      }
    
      // Caret to end
      const range = document.createRange();
      range.selectNodeContents(inputDiv);
      range.collapse(false);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);

      // Tell React first
      inputDiv.dispatchEvent(new InputEvent("input", { bubbles: true }));
      inputDiv.dispatchEvent(new Event("change", { bubbles: true }));
    }
  
    // Wait one render frame, then send
    requestAnimationFrame(() => {
      const sendButton =
        composer.querySelector('button[type="submit"]') ||
        Array.from(composer.querySelectorAll('button')).find(
          b => !b.disabled &&
               b.getAttribute("aria-label")?.toLowerCase().includes("send")
        );

      // This exception is intentional, yes!
      if (!sendButton) {
        throw new Error("Send button not found after injection");
      }
    
      sendButton.click();
    });
  }

  // #endregion

  // #region Assistant Finality Detection

  function isAssistantFinal(article) {
    // This logic is UI senstitive and intentionally loose/vague.
    // We could look for a more specific button, but so far Open AI does not have any.
    const buttonDiv = Array.from(article.querySelectorAll("div"))
      .find(div => div.querySelector("button"));
  
    return isVisible(buttonDiv);
  }

  function hashText(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) {
      h = ((h << 5) - h) + str.charCodeAt(i);
      h |= 0; // force 32-bit
    }
    return "h" + Math.abs(h);
  }

  let assistantObserver = null;

  function observeAssistant(onDone) {
    const thread = getThreadRoot();
    if (!thread) throw new Error("Thread root not found");
  
    stopObserving();
  
    assistantObserver = new MutationObserver(() => {
      const articles = getMessageNodes();
      if (!articles.length) return;
  
      const last = articles[articles.length - 1];
      if (getRoleFromArticle(last) !== "assistant") return;
  
      const parsed = parseMessage(last);
      if (isEphemeralMessage(parsed)) {
        return; // wait for real content / real ID
      }
      const message = upsertMessage(parsed);
     
      // Finality is UI-truth, already reflected in parseMessage
      if (message.final && !message._emitted_final) {
        message._emitted_final = true;
        onDone(message);
        cleanStore();
        // We could have done this in upsertMessage
        // but we don't want to trigger backups while rebuilding the store
        // We do this here so we don't backup partial messages.
        maybeAutoBackup();
      }
  
      // If UI regresses (freeze resumes), allow re-emit later
      if (!message.final) {
        message._emitted_final = false;
      }
    });
  
    assistantObserver.observe(thread, {
      subtree: true,
      childList: true,
      characterData: true
    });
  }
  
  function stopObserving() {
    if (assistantObserver) {
      assistantObserver.disconnect();
      assistantObserver = null;
    }
  }

  // #endregion

  // NOW we have everything in place, we start invoking stuff!!
  loadConfig();
  //attachConfigChangeListener();
  window.ChatGPTDOM = {
    getMessages() {
      return messageStore.order.map(id => messageStore.byId.get(id));
    },
    exportConversation() {
      cleanStore();
      return exportConversation();
    },
    resetStore(rebuild = false) {
      resetStore(rebuild);
      cleanStore();
    },
    assertStoreClean() {
      assertStoreClean();
    },
    cleanStore() {
      cleanStore();
    },
    injectUserMessage(text, options) {
      return injectUserMessage(text, options);
    },
    _store: messageStore   // intentionally exposed for debugging
  };
  // Ensure we cleanup on page/thread reloads
  // This should clean up the store and rebuild it also
  window.ChatGPTDOM.observeConversationChanges = observeConversationChanges;
  window.ChatGPTDOM.observeConversationChanges(
    //Add this when observeConversationChanges actually returns a result.
    /*{result => {
    console.log("CONVERSATION CONTEXT RELOADED:", result);}*/
  ); 
  // Watch new messages, and emit when assistants finish responding
  window.ChatGPTDOM.observeAssistant = observeAssistant;
  window.ChatGPTDOM.stopObserving = stopObserving;
  // Monitor for mutations of the assistant response
  window.ChatGPTDOM.observeAssistant(result => {
    console.log("ASSISTANT DONE:", result);
  }); 
  document.addEventListener("keydown", handleKeydown);
  // connect to background for config updates
  api.runtime.onMessage.addListener((msg) => {
    if (msg?.type === "CONFIG_UPDATED") {
      applyConfig(msg.payload);
    }
  });
  // notify the brwoser extension that we're ready to receive config and commands
  console.log("[ChatGPTDOM] adapter ready");
})();
