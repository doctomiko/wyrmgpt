
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

function clearChat() {
  chatWindow.innerHTML = "";
}

function addScaffoldEventCard(evRow) {
  const wrap = document.createElement("div");
  wrap.className = "scaffoldCard";

  const title = document.createElement("div");
  title.className = "scaffoldTitle";
  title.textContent = evRow.title || `Scaffold: ${evRow.event_kind || "event"}`;

  const meta = document.createElement("div");
  meta.className = "scaffoldMeta";
  const parts = [];
  if (evRow.status) parts.push(`status=${evRow.status}`);
  if (evRow.created_at) parts.push(formatReadableDateTime(evRow.created_at));
  meta.textContent = parts.join(" · ");

  const body = document.createElement("div");
  body.className = "scaffoldBody";
  body.innerHTML = renderMarkdown(stripZeit(evRow.body_text || ""));

  wrap.appendChild(title);
  if (meta.textContent) wrap.appendChild(meta);
  if ((evRow.body_text || "").trim()) wrap.appendChild(body);

  const detailsBits = [];
  if (evRow.input_json) detailsBits.push(`Input:\n${typeof evRow.input_json === "string" ? evRow.input_json : JSON.stringify(evRow.input_json, null, 2)}`);
  if (evRow.output_json) detailsBits.push(`Output:\n${typeof evRow.output_json === "string" ? evRow.output_json : JSON.stringify(evRow.output_json, null, 2)}`);
  if (detailsBits.length) {
    const details = document.createElement("details");
    details.className = "scaffoldDetails";
    const summary = document.createElement("summary");
    const kind = String(evRow.event_kind || "").toLowerCase();
    summary.textContent = kind.startsWith("tool") ? "Tool details" : "Scaffold details";
    const pre = document.createElement("pre");
    pre.className = "ctxPre";
    pre.textContent = detailsBits.join("\n\n");
    details.appendChild(summary);
    details.appendChild(pre);
    wrap.appendChild(details);
  }

  chatWindow.appendChild(wrap);
  chatWindow.scrollTop = chatWindow.scrollHeight;
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
function stripAssistantToolBlocks(text) {
  return String(text || "").replace(/```tool[\s\S]*?```/g, "").trim();
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

      // Markdown autolinks: <https://example.com>
      t = t.replace(
        /&lt;+\s*(https?:\/\/(?:(?!&gt;|&lt;|\s).)+)\s*&gt;+/g,
        (match, url) => {
          const safeUrl = url
            .replace(/"/g, "&quot;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
          return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeUrl}</a>`;
        }
      );

      // Bare explicit URLs that are not already part of markdown links/autolinks.
      // Only run this on text nodes, not inside HTML tags we already emitted.
      {
        const urlParts = t.split(/(<[^>]+>)/g);
        for (let i = 0; i < urlParts.length; i++) {
          const part = urlParts[i];
          if (!part || part.startsWith("<")) continue;
          urlParts[i] = part.replace(
            /(^|[\s(])((https?:\/\/(?:(?!&lt;|&gt;|\s).)+))/g,
            (match, prefix, url) => {
              const safeUrl = url
                .replace(/"/g, "&quot;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;");
              return `${prefix}<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${safeUrl}</a>`;
            }
          );
        }
        t = urlParts.join("");
      }

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

  const choiceA = describeSelection(modelA || "");
  const choiceB = describeSelection(modelB || "");

  const metaA = {
    ab_group: "A",
    canonical: true,
    model: choiceA.display_name || choiceA.id,
    deployment_id: choiceA.kind === "deployment" ? choiceA.id : null,
    provider: choiceA.provider_id || null,
  };

  const metaB = {
    ab_group: "B",
    canonical: false,
    model: choiceB.display_name || choiceB.id,
    deployment_id: choiceB.kind === "deployment" ? choiceB.id : null,
    provider: choiceB.provider_id || null,
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
  addUserMsgWithTime(text, now); //addMsg("user", text);
  // build an assistant message shell with model label
  const choice = describeSelection(model || "");
  //const assistantBody = addAssistantMsgWithModel(model, "Thinking…", now);
  const assistantBody = addAssistantMsgWithModel(choice.display_name || model, "Thinking…", now);
  const assistantBubble = assistantBody.closest(".msg.assistant");

  const request_body = JSON.stringify({
    conversation_id: conversationId,
    model: model,
    message: text
  });

  try {
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

    if (!res.body) {
      throw new Error("Empty response body from /api/chat");
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");

    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const visibleBuffer = stripAssistantToolBlocks(stripZeit(buffer));
      const looksLikeError = visibleBuffer.startsWith("**Model error**") || visibleBuffer.startsWith("**Server exception**");
      assistantBubble?.classList.toggle("error", looksLikeError);
      assistantBody.innerHTML = renderMarkdown(visibleBuffer || "Thinking…");
      chatWindow.scrollTop = chatWindow.scrollHeight;
    }
  } catch (e) {
    console.error("Failed single send", e);
    assistantBubble?.classList.add("error");
    assistantBody.innerHTML = renderMarkdown("**Client error**" + (e?.message || String(e) || "Unknown client-side failure"));
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
    now
  );

  // These will be updated after the server returns.
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
      "API error";

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

    const labelA = data.deployment_a
      ? `${data.deployment_a} · ${data.model_a || choiceA.model || modelA}`
      : (data.model_a || choiceA.display_name || modelA);

    const labelB = data.deployment_b
      ? `${data.deployment_b} · ${data.model_b || choiceB.model || modelB}`
      : (data.model_b || choiceB.display_name || modelB);


    const msgs = await loadMessages(conversationId);
    clearChat();
    if (!msgs.length) {
      addMsg("assistant", "Empty chat. Say something mean to the void.");
    } else {
      renderMessagesWithAB(msgs);
    }

    renderSlot(msgAEl, labelAEl, "A", labelA, data.a);
    renderSlot(msgBEl, labelBEl, "B", labelB, data.b);

    // Update the info payloads AFTER we have data
    detailsA = { slot: "A", model: data.model_a || modelA, ab_group: data.ab_group || null, result: data.a };
    detailsB = { slot: "B", model: data.model_b || modelB, ab_group: data.ab_group || null, result: data.b };

    markCanonical(rowEl, data.canonical_slot || "A");
  } catch (e) {
    console.error("Failed A/B send", e);
    msgAEl.classList.add("error");
    msgBEl.classList.add("error");
    msgAEl.textContent = "[A] error during A/B call";
    msgBEl.textContent = "[B] error during A/B call";
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
