
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
  
  wrapper.appendChild(metaBar);

  // Actual chat bubble
  const bubble = document.createElement("div");
  bubble.className = "msg assistant";
  // preserve error color coding
  if (isErrorBubble({ role: "assistant", content: initialText, meta: metaObj })) bubble.classList.add("error");

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

let liveScaffoldCards = new Map();

function clearChat() {
  chatWindow.innerHTML = "";
  liveScaffoldCards = new Map();
}

function scaffoldEventId(evRow) {
  const raw = evRow?.id ?? evRow?.event_id ?? evRow?.live_event_id ?? null;
  return raw == null ? "" : String(raw);
}

function normalizeScaffoldJson(value) {
  if (value == null || value === "") return null;
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function scaffoldStatusLabel(status) {
  const s = String(status || "").toLowerCase();
  if (s === "ok" || s === "ready") return "complete";
  if (s === "running") return "running";
  if (s === "error") return "error";
  return s || "event";
}

function ensureLiveScaffoldHost(anchorEl) {
  if (!anchorEl || !anchorEl.parentNode) return chatWindow;
  let host = anchorEl.previousElementSibling;
  if (!host || !host.classList || !host.classList.contains("liveScaffoldHost")) {
    host = document.createElement("div");
    host.className = "liveScaffoldHost";
    anchorEl.parentNode.insertBefore(host, anchorEl);
  }
  return host;
}

function scaffoldPrettyJsonText(value) {
  if (value == null || value === "") return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function scaffoldToolName(evRow) {
  const inputJson = normalizeScaffoldJson(evRow?.input_json);
  if (inputJson && typeof inputJson === "object" && !Array.isArray(inputJson)) {
    return String(inputJson.tool || inputJson.name || "").trim();
  }
  return "";
}

function scaffoldToolResultPayload(evRow) {
  const outputJson = normalizeScaffoldJson(evRow?.output_json);
  if (outputJson && typeof outputJson === "object" && !Array.isArray(outputJson)) {
    const inner = outputJson.result;
    if (inner && typeof inner === "object" && !Array.isArray(inner)) return inner;
    return outputJson;
  }
  return null;
}

function scaffoldResultDate(item) {
  return String(item?.age || item?.page_age || item?.date || "").trim();
}

function scaffoldSnippetParts(text, limit = 280) {
  const raw = String(text || "").replace(/\s+/g, " ").trim();
  if (!raw) return { preview: "", rest: "" };
  if (raw.length <= limit) return { preview: raw, rest: "" };
  const cut = raw.slice(0, limit);
  const breakAt = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("! "), cut.lastIndexOf("? "), cut.lastIndexOf("; "));
  const idx = breakAt >= Math.floor(limit * 0.55) ? breakAt + 1 : limit;
  return {
    preview: raw.slice(0, idx).trim(),
    rest: raw.slice(idx).trim(),
  };
}

function splitThinkingSectionTextClient(text) {
  const raw = String(text || "").trim();
  if (!raw) return { title: "", body: "", text: "" };
  const cleaned = raw.replace(/^\*\*(.+?)\*\*$/m, "$1").trim();
  const parts = cleaned.split(/\n\s*\n/, 2);
  const first = (parts[0] || "").trim();
  const remainder = (parts[1] || "").trim();
  if (first && first.length <= 140) {
    return { title: first, body: remainder, text: cleaned };
  }
  const lines = cleaned.split(/\n/);
  const firstLine = String(lines[0] || "").trim();
  if (firstLine && firstLine.length <= 140) {
    return { title: firstLine, body: cleaned.slice(firstLine.length).replace(/^\n+/, "").trim(), text: cleaned };
  }
  return { title: "", body: cleaned, text: cleaned };
}

function renderThinkingScaffoldHtml(evRow) {
  const payload = normalizeScaffoldJson(evRow?.output_json);
  const sections = Array.isArray(payload?.sections) ? payload.sections : [];
  if (!sections.length) {
    const bodyText = String(evRow?.body_text || "").trim();
    return bodyText ? renderMarkdown(stripZeit(bodyText)) : "";
  }
  const itemsHtml = sections.map((section, idx) => {
    const parsed = splitThinkingSectionTextClient(section?.text || section?.body || "");
    const title = escapeHtml(String(section?.title || parsed.title || `Thought ${idx + 1}`));
    const bodySource = String(section?.body || parsed.body || section?.text || "").trim();
    const bodyHtml = bodySource ? renderMarkdown(stripZeit(bodySource)) : "";
    const history = Array.isArray(section?.history) ? section.history.filter(Boolean) : [];
    const historyHtml = history.length ? `
      <details class="thinkingHistory">
        <summary>Earlier drafts (${history.length})</summary>
        <div class="thinkingHistoryList">${history.map((entry, hIdx) => {
          const prev = splitThinkingSectionTextClient(entry);
          const prevTitle = escapeHtml(String(prev.title || section?.title || `Draft ${history.length - hIdx}`));
          const prevBody = String(prev.body || prev.text || "").trim();
          const prevBodyHtml = prevBody ? renderMarkdown(stripZeit(prevBody)) : "";
          return `<article class="thinkingHistoryItem"><div class="thinkingHistoryLabel">${prevTitle}</div><div class="thinkingHistoryBody">${prevBodyHtml}</div></article>`;
        }).join("")}</div>
      </details>` : "";
    return `
      <article class="thinkingSection">
        <div class="thinkingSectionTitle">${title}</div>
        ${bodyHtml ? `<div class="thinkingSectionBody">${bodyHtml}</div>` : ""}
        ${historyHtml}
      </article>
    `.trim();
  }).join("");
  return `<div class="thinkingSections">${itemsHtml}</div>`;
}

function renderWebSearchScaffoldHtml(evRow) {
  const payload = scaffoldToolResultPayload(evRow);
  const results = Array.isArray(payload?.results) ? payload.results : [];
  if (!results.length) return "";

  const itemsHtml = results.map((item) => {
    const title = escapeHtml(String(item?.title || item?.url || item?.canonical_url || "result"));
    const urlRaw = String(item?.url || item?.canonical_url || "").trim();
    const safeUrl = isLikelyLinkableUrl(urlRaw) ? sanitizeHref(urlRaw) : "";
    const domain = escapeHtml(String(item?.domain || "").trim());
    const dateText = escapeHtml(scaffoldResultDate(item));
    const snippetText = [
      String(item?.snippet || "").trim(),
      ...((Array.isArray(item?.extra_snippets) ? item.extra_snippets : []).map(x => String(x || "").trim()).filter(Boolean)),
    ].filter(Boolean).join(" ");
    const snippet = scaffoldSnippetParts(snippetText, 300);
    const metaBits = [];
    if (domain) metaBits.push(`<span class="scaffoldSearchDomain">${domain}</span>`);
    if (dateText) metaBits.push(`<span class="scaffoldSearchDate">${dateText}</span>`);
    const metaHtml = metaBits.length ? `<div class="scaffoldSearchMetaLine">${metaBits.join('<span class="scaffoldSearchDot">•</span>')}</div>` : "";
    const previewHtml = snippet.preview ? `<div class="scaffoldSearchSnippet">${escapeHtml(snippet.preview)}</div>` : "";
    const moreHtml = snippet.rest
      ? `<details class="scaffoldSearchMore"><summary>[more]</summary><div class="scaffoldSearchSnippet scaffoldSearchSnippetMore">${escapeHtml(snippet.rest)}</div></details>`
      : "";
    const titleHtml = safeUrl
      ? `<a class="scaffoldSearchTitleLink" href="${safeUrl}" target="_blank" rel="noopener noreferrer">${title}</a>`
      : title;
    const urlHtml = safeUrl
      ? `<a class="scaffoldSearchUrl" href="${safeUrl}" target="_blank" rel="noopener noreferrer">${escapeHtml(urlRaw)}</a>`
      : `<div class="scaffoldSearchUrl">${escapeHtml(urlRaw)}</div>`;
    return `
      <article class="scaffoldSearchResult">
        <div class="scaffoldSearchTitle">${titleHtml}</div>
        ${urlRaw ? urlHtml : ""}
        ${metaHtml}
        ${previewHtml}
        ${moreHtml}
      </article>
    `.trim();
  }).join("");

  return `<div class="scaffoldSearchResults">${itemsHtml}</div>`;
}

function renderScaffoldBodyHtml(evRow) {
  const eventKind = String(evRow?.event_kind || "").toLowerCase();
  if (eventKind === "thinking") {
    const customThinking = renderThinkingScaffoldHtml(evRow);
    if (customThinking) return customThinking;
  }
  const toolName = scaffoldToolName(evRow);
  if (toolName === "web.search") {
    const custom = renderWebSearchScaffoldHtml(evRow);
    if (custom) return custom;
  }
  const bodyText = String(evRow?.body_text || "").trim();
  return bodyText ? renderMarkdown(stripZeit(bodyText)) : "";
}

function buildScaffoldCardShell() {
  const wrap = document.createElement("div");
  wrap.className = "scaffoldCard";

  const header = document.createElement("div");
  header.className = "scaffoldHeader";

  const badge = document.createElement("span");
  badge.className = "scaffoldBadge";

  const title = document.createElement("div");
  title.className = "scaffoldTitle";

  header.appendChild(badge);
  header.appendChild(title);

  const meta = document.createElement("div");
  meta.className = "scaffoldMeta";

  const body = document.createElement("div");
  body.className = "scaffoldBody";

  const detailsWrap = document.createElement("div");
  detailsWrap.className = "scaffoldDetailsStack";

  const inputDetails = document.createElement("details");
  inputDetails.className = "scaffoldDetails";
  const inputSummary = document.createElement("summary");
  inputSummary.className = "scaffoldDetailsSummary";
  const inputPre = document.createElement("pre");
  inputPre.className = "ctxPre";
  inputDetails.appendChild(inputSummary);
  inputDetails.appendChild(inputPre);

  const outputDetails = document.createElement("details");
  outputDetails.className = "scaffoldDetails";
  const outputSummary = document.createElement("summary");
  outputSummary.className = "scaffoldDetailsSummary";
  const outputPre = document.createElement("pre");
  outputPre.className = "ctxPre";
  outputDetails.appendChild(outputSummary);
  outputDetails.appendChild(outputPre);

  detailsWrap.appendChild(inputDetails);
  detailsWrap.appendChild(outputDetails);

  wrap.appendChild(header);
  wrap.appendChild(meta);
  wrap.appendChild(body);
  wrap.appendChild(detailsWrap);

  wrap._scaffoldEls = { badge, title, meta, body, detailsWrap, inputDetails, inputSummary, inputPre, outputDetails, outputSummary, outputPre };
  return wrap;
}

function populateScaffoldCard(wrap, evRow) {
  const els = wrap._scaffoldEls || {};
  const status = String(evRow.status || "").toLowerCase() || "running";
  wrap.dataset.status = status;
  wrap.dataset.kind = String(evRow.event_kind || "").toLowerCase();
  wrap.dataset.eventId = scaffoldEventId(evRow);

  if (els.badge) {
    els.badge.textContent = scaffoldStatusLabel(status);
  }
  if (els.title) {
    els.title.textContent = evRow.title || `Scaffold · ${evRow.event_kind || "event"}`;
  }
  if (els.meta) {
    const parts = [];
    if (evRow.event_kind) parts.push(String(evRow.event_kind));
    if (evRow.updated_at || evRow.created_at) parts.push(formatReadableDateTime(evRow.updated_at || evRow.created_at));
    els.meta.textContent = parts.join(" · ");
    els.meta.style.display = els.meta.textContent ? "" : "none";
  }
  if (els.body) {
    const bodyHtml = renderScaffoldBodyHtml(evRow);
    els.body.innerHTML = bodyHtml;
    els.body.style.display = bodyHtml ? "" : "none";
  }

  const inputJson = normalizeScaffoldJson(evRow.input_json);
  const outputJson = normalizeScaffoldJson(evRow.output_json);
  const toolName = scaffoldToolName(evRow);
  const eventKind = String(evRow.event_kind || "").toLowerCase();
  const isTool = !!toolName || eventKind.startsWith("tool");
  const isThinking = eventKind === "thinking";

  if (els.inputDetails && els.inputSummary && els.inputPre) {
    const inputText = scaffoldPrettyJsonText(inputJson);
    if (inputText) {
      els.inputSummary.textContent = isThinking ? "Thinking settings" : (isTool ? "Tool parameters" : "Scaffold input");
      els.inputPre.textContent = inputText;
      els.inputDetails.style.display = "";
    } else {
      els.inputDetails.style.display = "none";
    }
  }

  if (els.outputDetails && els.outputSummary && els.outputPre) {
    const outputText = scaffoldPrettyJsonText(outputJson);
    if (outputText) {
      els.outputSummary.textContent = isThinking ? "Thinking data" : (isTool ? "Tool results" : "Scaffold output");
      els.outputPre.textContent = outputText;
      els.outputDetails.style.display = "";
    } else {
      els.outputDetails.style.display = "none";
    }
  }

  if (els.detailsWrap) {
    const hasVisible = [els.inputDetails, els.outputDetails].some((node) => node && node.style.display !== "none");
    els.detailsWrap.style.display = hasVisible ? "" : "none";
  }
}

function addScaffoldEventCard(evRow, options = {}) {
  const eventId = scaffoldEventId(evRow);
  const anchorEl = options.anchorEl || null;
  const reuseLive = !!options.reuseLive && !!eventId && liveScaffoldCards.has(eventId);

  let wrap = reuseLive ? liveScaffoldCards.get(eventId) : null;
  if (!wrap) {
    wrap = buildScaffoldCardShell();
    if (eventId) liveScaffoldCards.set(eventId, wrap);

    if (anchorEl) {
      const host = ensureLiveScaffoldHost(anchorEl);
      host.appendChild(wrap);
    } else {
      chatWindow.appendChild(wrap);
    }
  }

  populateScaffoldCard(wrap, evRow);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return wrap;
}

function upsertLiveScaffoldEvent(evRow, anchorEl) {
  const wrap = addScaffoldEventCard(evRow, { anchorEl, reuseLive: true });
  try {
    console.debug("[scaffold]", scaffoldEventId(evRow), evRow?.event_kind || "event", evRow);
  } catch {}
  return wrap;
}

function renderMessagesWithAB(rows) {
  let i = 0;
  while (i < rows.length) {
    const msg = rows[i];
    if (msg.row_type === "scaffold_event") {
      addScaffoldEventCard(msg);
      i += 1;
      continue;
    }
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

  if (isErrorBubble(msgA)) msgAEl.classList.add("error");
  if (isErrorBubble(msgB)) msgBEl.classList.add("error");

  // Wire info buttons for reload/history
  infoAEl.onclick = () => openMetaInfo(labelAEl.textContent || "A", msgA.meta || {});
  infoBEl.onclick = () => openMetaInfo(labelBEl.textContent || "B", msgB.meta || {});

  if (canonicalA) markCanonical(rowEl, "A");
  else if (canonicalB) markCanonical(rowEl, "B");
}

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
  if (safeLabelA === "model A") safeLabelA = "Unknown Model A";

  let safeLabelB = modelB && modelB.trim() ? modelB : "Unknown Model B";
  if (safeLabelB === "model B") safeLabelB = "Unknown Model B";

  const A = makeCol(safeLabelA, createdAtIsoA);
  const B = makeCol(safeLabelB, createdAtIsoB);

  row.appendChild(A.col);
  row.appendChild(B.col);

  chatWindow.appendChild(row);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  // This was missing in the live function.
  A.btn.addEventListener("click", () => chooseCanonical(row, "A"));
  B.btn.addEventListener("click", () => chooseCanonical(row, "B"));

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
    const discordBlock = line.match(/^(&gt;&gt;&gt;)\s?(.*)$/);
    const m = discordBlock || line.match(/^((?:&gt;)+)\s?(.*)$/);
    if (m) {
      const markers = m[1];
      const content = m[2] || "";
      const level = discordBlock ? 1 : (markers.match(/&gt;/g) || []).length;

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
function stripAssistantToolBlocks(text) {
  return String(text || "").replace(/```tool[\s\S]*?```/g, "").trim();
}

function sanitizeHref(url) {
  return String(url || "")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function trimTrailingUrlPunctuation(url) {
  return String(url || "").replace(/[.,;:!?)}\]>'"]+$/g, "");
}

function isLikelyLinkableUrl(url) {
  const raw = trimTrailingUrlPunctuation(url);
  if (!/^https?:\/\//i.test(raw)) return false;
  try {
    const parsed = new URL(raw);
    const host = String(parsed.hostname || "").toLowerCase();
    if (!host) return false;
    if (host === "localhost") return true;
    if (/^\d{1,3}(?:\.\d{1,3}){3}$/.test(host)) return true;
    if (host.includes(".")) return true;
    return false;
  } catch {
    return false;
  }
}

function linkifyExplicitUrlsInEscapedHtml(text) {
  if (!text) return "";
  const urlParts = String(text).split(/(<[^>]+>)/g);
  const explicitUrlRe = /(^|[\s(])((https?:\/\/[^\s<>()]+))/gi;

  for (let i = 0; i < urlParts.length; i++) {
    const part = urlParts[i];
    if (!part || part.startsWith("<")) continue;
    urlParts[i] = part.replace(explicitUrlRe, (match, prefix, url) => {
      const trimmed = trimTrailingUrlPunctuation(url);
      const trailing = url.slice(trimmed.length);
      if (!isLikelyLinkableUrl(trimmed)) {
        return match;
      }
      const safeUrl = sanitizeHref(trimmed);
      return `${prefix}<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeUrl}</a>${trailing}`;
    });
  }

  return urlParts.join("");
}

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

      // Links: [text](https://example.com)
      // Only allow http/https, keep it simple and safe-ish.
      t = t.replace(
        /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        (match, label, url) => {
          const trimmed = trimTrailingUrlPunctuation(url);
          if (!isLikelyLinkableUrl(trimmed)) return match;
          const safeUrl = sanitizeHref(trimmed);
          return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${label}</a>`;
        }
      );

      // Markdown autolinks: <https://example.com>
      t = t.replace(
        /&lt;+\s*(https?:\/\/[^\s<>()]+)\s*&gt;+/gi,
        (match, url) => {
          const trimmed = trimTrailingUrlPunctuation(url);
          if (!isLikelyLinkableUrl(trimmed)) return match;
          const safeUrl = sanitizeHref(trimmed);
          return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeUrl}</a>`;
        }
      );

      // Bare explicit URLs that are not already part of markdown links/autolinks.
      // Deliberately conservative: only explicit http/https URLs get linkified.
      t = linkifyExplicitUrlsInEscapedHtml(t);

      // Strikethrough: ~~text~~
      t = t.replace(/~~(.+?)~~/g, "<del>$1</del>");

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

// #region Sending messages

function parseEventStreamFrame(rawFrame) {
  const lines = String(rawFrame || "").split(/\r?\n/);
  let eventName = "message";
  const dataLines = [];
  for (const line of lines) {
    if (!line) continue;
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim() || "message";
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (!dataLines.length) return null;
  const rawData = dataLines.join("\n");
  let data = rawData;
  try {
    data = JSON.parse(rawData);
  } catch {
    // leave as string
  }
  return { event: eventName, data };
}

async function consumeEventStream(res, onEvent) {
  if (!res.body) {
    throw new Error("Empty streamed response body.");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const frame = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      if (frame) {
        const parsed = parseEventStreamFrame(frame);
        if (parsed) onEvent(parsed);
      }
      boundary = buffer.indexOf("\n\n");
    }

    if (done) {
      const tail = buffer.trim();
      if (tail) {
        const parsed = parseEventStreamFrame(tail);
        if (parsed) onEvent(parsed);
      }
      break;
    }
  }
}

function renderSingleAssistantState(assistantBody, assistantBubble, text) {
  const visibleBuffer = stripAssistantToolBlocks(stripZeit(text || ""));
  const looksLikeError = visibleBuffer.startsWith("**Model error**") || visibleBuffer.startsWith("**Server exception**") || visibleBuffer.startsWith("**Client error**");
  assistantBubble?.classList.toggle("error", looksLikeError);
  assistantBody.innerHTML = renderMarkdown(visibleBuffer || "Thinking…");
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function renderABSlotState(msgEl, slotLabelEl, slotName, slotModel, slotData) {
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
    slotData.text ||
    "API error";

  const lines = [];
  lines.push(`**${slotName} error** (HTTP ${status || "?"})`);
  if (reqId) lines.push(`request_id: \`${reqId}\``);
  lines.push(msg);

  msgEl.innerHTML = renderMarkdown(lines.join("\n\n"));
  if (slotModel) slotLabelEl.textContent = `${slotName} · ${slotModel}`;
}

async function send() {
  const text = chatWindowInputTextbox.value.trim();
  if (!text) return;
  chatWindowInputTextbox.value = "";
  cancelScheduledContextRefresh();
  lastContextDraftSent = "";

  const modelA = topBarModelSelectA?.value || null;
  let modelB = modelA;
  if (topBarModelSelectB && topBarModelSelectB.style.display !== "none") {
    const v = (topBarModelSelectB.value || "").trim();
    if (v) modelB = v;
  }

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

  await refreshConversationLists();
  lastContextQueryText = text;
  await refreshContext();

  const msgs = await loadMessages(conversationId);
  clearChat();
  if (!msgs.length) {
    addMsg("assistant", "Empty chat. Say something mean to the void.");
  } else {
    renderMessagesWithAB(msgs);
  }

  scheduleTranscriptRefresh();
}

async function sendSingle(text, model) {
  const now = nowIso();
  addUserMsgWithTime(text, now);
  const choice = describeSelection(model || "");
  const assistantBody = addAssistantMsgWithModel(choice.display_name || model, "Thinking…", now);
  const assistantBubble = assistantBody.closest(".msg.assistant");
  const assistantWrap = assistantBody.closest(".msgWithModel");

  const requestBody = JSON.stringify({
    conversation_id: conversationId,
    model: model,
    message: text,
  });

  let accumulatedText = "";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: requestBody,
    });

    const headerCid = res.headers.get("X-Conversation-Id");
    if (headerCid) {
      conversationId = headerCid;
      localStorage.setItem("callie_mvp_conversation_id", conversationId);
    }

    await consumeEventStream(res, ({ event, data }) => {
      if (event === "assistant.delta") {
        accumulatedText += data?.text || "";
        renderSingleAssistantState(assistantBody, assistantBubble, accumulatedText);
        return;
      }
      if (event === "assistant.final") {
        if (data && data.ok === false && (data.append_error || (accumulatedText && accumulatedText.trim()))) {
          const errModel = data?.model || choice.model || model;
          addAssistantMsgWithModel(errModel, data?.text || "**Model error**", nowIso(), data || null);
          return;
        }
        accumulatedText = data?.text || accumulatedText;
        renderSingleAssistantState(assistantBody, assistantBubble, accumulatedText);
        if (data && data.ok === false) assistantBubble?.classList.add("error");
        return;
      }
      if (event === "scaffold") {
        upsertLiveScaffoldEvent(data || {}, assistantWrap);
      }
    });
  } catch (e) {
    console.error("Failed single send", e);
    assistantBubble?.classList.add("error");
    assistantBody.innerHTML = renderMarkdown(`**Client error**\n\n${e?.message || String(e) || "Unknown client-side failure"}`);
  }
}

async function sendAB(text, modelA, modelB) {
  const now = nowIso();
  addUserMsgWithTime(text, now);

  const choiceA = describeSelection(modelA || "");
  const choiceB = describeSelection(modelB || "");
  const { rowEl, msgAEl, msgBEl, labelAEl, labelBEl, infoAEl, infoBEl } = addABRow(
    choiceA.display_name || modelA,
    choiceB.display_name || modelB,
    now,
    now,
  );

  let detailsA = {
    pending: true,
    slot: "A",
    model: choiceA.model,
    deployment_id: choiceA.kind === "deployment" ? choiceA.id : null,
    provider: choiceA.provider_id || null,
    selected_label: choiceA.display_name || modelA,
  };
  let detailsB = {
    pending: true,
    slot: "B",
    model: choiceB.model,
    deployment_id: choiceB.kind === "deployment" ? choiceB.id : null,
    provider: choiceB.provider_id || null,
    selected_label: choiceB.display_name || modelB,
  };

  infoAEl.onclick = () => openMetaInfo(labelAEl.textContent || "A", detailsA);
  infoBEl.onclick = () => openMetaInfo(labelBEl.textContent || "B", detailsB);

  const payload = {
    conversation_id: conversationId,
    model_a: modelA,
    model_b: modelB,
    message: text,
  };

  try {
    const res = await fetch("/api/chat_ab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const headerCid = res.headers.get("X-Conversation-Id");
    if (headerCid) {
      conversationId = headerCid;
      localStorage.setItem("callie_mvp_conversation_id", conversationId);
    }

    await consumeEventStream(res, ({ event, data }) => {
      if (event === "ab.init") {
        rowEl.dataset.abGroup = data?.ab_group || "";
        detailsA = { ...detailsA, ...data, slot: "A" };
        detailsB = { ...detailsB, ...data, slot: "B" };
        return;
      }
      if (event === "assistant.final") {
        const slot = data?.slot || "A";
        const slotLabel = data?.deployment_id
          ? `${data.deployment_id} · ${data.model || (slot === "A" ? choiceA.model : choiceB.model)}`
          : (data?.model || (slot === "A" ? choiceA.display_name || modelA : choiceB.display_name || modelB));
        if (slot === "A") {
          renderABSlotState(msgAEl, labelAEl, "A", slotLabel, data);
          detailsA = { slot: "A", ab_group: rowEl.dataset.abGroup || null, result: data, model: data?.model || modelA };
        } else {
          renderABSlotState(msgBEl, labelBEl, "B", slotLabel, data);
          detailsB = { slot: "B", ab_group: rowEl.dataset.abGroup || null, result: data, model: data?.model || modelB };
        }
        return;
      }
      if (event === "scaffold") {
        upsertLiveScaffoldEvent(data || {}, rowEl);
        return;
      }
      if (event === "ab.done") {
        markCanonical(rowEl, "A");
      }
    });
  } catch (e) {
    console.error("Failed A/B send", e);
    msgAEl.classList.add("error");
    msgBEl.classList.add("error");
    msgAEl.innerHTML = renderMarkdown("**Client error**\n\nA/B call failed.");
    msgBEl.innerHTML = renderMarkdown("**Client error**\n\nA/B call failed.");
  }
}

// #endregion

async function newChat() {
  const res = await fetch("/api/new", { method: "POST" });
  const data = await res.json();
  conversationId = data.conversation_id;
  localStorage.setItem("callie_mvp_conversation_id", conversationId);

  await refreshConversationLists();

  clearChat();
  addMsg("assistant", "New chat started.");
  await refreshContext();
}

async function loadMessages(cid) {
  return await fetchJsonDebug(`/api/conversation/${cid}/messages?mode=thread`);
  //return await fetchJsonDebug(`/api/conversation/${cid}/messages`);
}
