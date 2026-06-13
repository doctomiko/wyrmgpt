

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

function closeCitationsModal() {
  citationsModalMode = null;
  citationsModalConversationId = null;
  citationsModalProjectId = null;
  if (citationsModal) citationsModal.classList.add("hidden");
}

function renderCitationScopeItems(data) {
  if (!citationsListEl) return;
  const items = Array.isArray(data?.items) ? data.items : [];
  citationsListEl.innerHTML = "";

  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "citationEmpty";
    empty.textContent = "No citations found in this scope yet.";
    citationsListEl.appendChild(empty);
    return;
  }

  for (const item of items) {
    const card = document.createElement("div");
    card.className = "citationCard";

    const title = document.createElement("div");
    title.className = "citationCardTitle";
    title.textContent = item.title || "Untitled source";

    const meta = document.createElement("div");
    meta.className = "citationCardMeta";
    const metaBits = [];
    if (item.citation_count != null) metaBits.push(`${item.citation_count} citation${Number(item.citation_count) === 1 ? "" : "s"}`);
    if (Array.isArray(item.retrieval_channels) && item.retrieval_channels.length) {
      metaBits.push(item.retrieval_channels.join(", "));
    }
    if (item.latest_created_at) metaBits.push(formatReadableDateTime(item.latest_created_at));
    meta.textContent = metaBits.join(" · ");

    const excerpt = document.createElement("div");
    excerpt.className = "citationExcerpt";
    excerpt.textContent = item.summary_excerpt || item.excerpt || "";

    const path = document.createElement("div");
    path.className = "citationPath";

    if (item.origin_url) {
      const a = document.createElement("a");
      a.href = item.origin_url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = item.origin_label || item.origin_url;
      path.appendChild(a);
    } else if (item.origin_conversation_id) {
      const btn = document.createElement("button");
      btn.className = "citationJumpBtn";
      btn.textContent = item.origin_conversation_title || item.origin_conversation_id;
      btn.addEventListener("click", async () => {
        closeCitationsModal();
        await selectConversation(item.origin_conversation_id);
      });
      path.appendChild(btn);
    } else if (item.origin_path) {
      const code = document.createElement("code");
      code.textContent = item.origin_path;
      path.appendChild(code);
    } else {
      path.textContent = item.origin_label || item.source_kind || "Artifact";
    }

    card.appendChild(title);
    if (meta.textContent) card.appendChild(meta);
    if (excerpt.textContent) card.appendChild(excerpt);
    card.appendChild(path);
    citationsListEl.appendChild(card);
  }
}

async function openCitationsModalForConversation(cid) {
  citationsModalMode = "conversation";
  citationsModalConversationId = cid;
  citationsModalProjectId = null;
  citationsModalTitleEl.textContent = "Conversation Citations";
  citationsListEl.innerHTML = "Loading…";
  hideAllTransientUI({ except: [citationsModal] });
  citationsModal.classList.remove("hidden");

  const data = await fetchJsonDebug(`/api/conversation/${encodeURIComponent(cid)}/citations`);
  citationsModalTitleEl.textContent = `Conversation Citations — ${data?.scope_label || cid}`;
  renderCitationScopeItems(data);
}

async function openCitationsModalForProject(pid) {
  citationsModalMode = "project";
  citationsModalProjectId = pid;
  citationsModalConversationId = null;
  citationsModalTitleEl.textContent = "Project Citations";
  citationsListEl.innerHTML = "Loading…";
  hideAllTransientUI({ except: [citationsModal] });
  citationsModal.classList.remove("hidden");

  const data = await fetchJsonDebug(`/api/projects/${encodeURIComponent(pid)}/citations`);
  citationsModalTitleEl.textContent = `Project Citations — ${data?.scope_label || pid}`;
  renderCitationScopeItems(data);
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

function fmtScore(v, digits = 4) {
  if (v === null || v === undefined || v === "") return "-";
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(digits) : String(v);
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

function accessMetaParts(item) {
  const parts = [];
  if (!item || typeof item !== "object") return parts;
  if (item.admin_visible) parts.push("admin-visible");
  const access = item.effective_access || {};
  const reason = String(access.reason || "").trim();
  if (reason) parts.push(reason);
  const resource = item.access_resource || {};
  if (resource.resource_type && resource.resource_id) {
    parts.push(`${resource.resource_type}:${resource.resource_id}`);
  }
  return parts;
}

function accessMetaSuffix(item) {
  const parts = accessMetaParts(item);
  return parts.length ? ` [access: ${parts.join("; ")}]` : "";
}

function appendAccessBadges(container, item) {
  if (!container) return;
  const access = item?.effective_access || {};
  if (item?.admin_visible) {
    const badge = document.createElement("span");
    badge.className = "libraryBadge libraryBadgeAccess libraryBadgeAdminVisible";
    badge.textContent = "admin";
    container.appendChild(badge);
  }
  const reason = String(access.reason || "").trim();
  if (reason) {
    const badge = document.createElement("span");
    badge.className = "libraryBadge libraryBadgeAccess";
    badge.textContent = reason;
    container.appendChild(badge);
  }
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
  const chatSummaryIncludeActive = !!ctx.chat_summary_include;
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
  const retrievalDebug = ctx.retrieval_debug || {};
  const retrievalMode =
    retrievalDebug.retrieval_mode ||
    (ftsActive && vectorActive ? "hybrid" : vectorActive ? "vector" : ftsActive ? "fts" : "none");
  const embeddingProvider = retrievalDebug.embedding_provider || "(unknown)";
  const embeddingModel = retrievalDebug.embedding_model || "(unknown)";
  const vectorBackend = retrievalDebug.vector_backend || "(unknown)";
  const vectorCollection = retrievalDebug.vector_collection || "(unknown)";

  const rawCount = retrievalDebug.raw_result_count ?? rawRows.length;
  const ftsCount = retrievalDebug.fts_result_count ?? 0;
  const vectorCount = retrievalDebug.vector_result_count ?? 0;
  const beforeDiversify = retrievalDebug.result_count_before_diversify ?? "?";
  const afterDiversify = retrievalDebug.result_count_after_diversify ?? finalRows.length;
  const cacheHit = !!retrievalDebug.cache_hit;
  
  const suppressedIncluded = (retrievalDebug.suppressed_included_artifact_rows || []).length;
  const suppressedExpanded = (retrievalDebug.suppressed_expanded_artifact_rows || []).length;
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
    lines.push(`Retrieval mode: ${retrievalMode}`);
    lines.push(`Embedding provider: ${embeddingProvider}`);
    lines.push(`Embedding model: ${embeddingModel}`);
    lines.push(`Vector backend: ${vectorBackend}`);
    lines.push(`Vector collection: ${vectorCollection}`);

    const activeParts = [];
    if (fileIncludeActive) activeParts.push("full-file inclusion");
    if (memoryIncludeActive) activeParts.push("full-memory inclusion");
    if (chatIncludeActive) activeParts.push("full-chat inclusion");
    if (chatSummaryIncludeActive) activeParts.push("chat-summary inclusion");
    if (!hasDraft) {
      lines.push("Status: idle (no draft text, so retrieval/inclusion is not running)");
    } else {
      if (ftsActive) activeParts.push("FTS");
      if (vectorActive) activeParts.push("vector");
    }
    if (!activeParts.length) activeParts.push("no active retrieval path");
    lines.push(`Active: ${activeParts.join("; ")}`);

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
    const llmSystemMessages = (ctx.llm_system_messages || []).filter((msg) => msg && msg.role === "system");
    const primarySystem = llmSystemMessages.length
      ? (llmSystemMessages[0]?.content || ctx.system_text || ctx.effective_system_prompt || "(none)")
      : (ctx.system_text || ctx.effective_system_prompt || "(none)");
    const extraSystemMessages = llmSystemMessages.slice(1);

    wrap.appendChild(
      createCtxSubBlock(
        "System Text",
        createCtxPre(primarySystem)
      )
    );

    if (extraSystemMessages.length) {
      extraSystemMessages.forEach((msg, idx) => {
        const text = typeof msg.content === "string" ? msg.content : JSON.stringify(msg.content, null, 2);
        const firstLine = (text || "").split("")[0]?.trim() || `Supplemental System ${idx + 1}`;
        wrap.appendChild(
          createCtxSubBlock(
            `Supplemental System ${idx + 1}`,
            createCtxPre(text),
            firstLine
          )
        );
      });
    } else {
      wrap.appendChild(createCtxSubBlock("Supplemental System Prompts", createCtxPre("(none)")));
    }

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
      return `${name} [${scope}]${accessMetaSuffix(f)}`;
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

  // Retrieval Diagnostics
  {
    const lines = [];
    lines.push(`Mode: ${retrievalMode}`);
    lines.push(`Cache hit: ${cacheHit ? "yes" : "no"}`);
    lines.push(`Raw hits: ${rawCount}`);
    lines.push(`FTS hits: ${ftsCount}`);
    lines.push(`Vector hits: ${vectorCount}`);
    lines.push(`Before diversify: ${beforeDiversify}`);
    lines.push(`After diversify: ${afterDiversify}`);
    lines.push(`Embedding provider: ${embeddingProvider}`);
    lines.push(`Embedding model: ${embeddingModel}`);
    lines.push(`Vector backend: ${vectorBackend}`);
    lines.push(`Vector collection: ${vectorCollection}`);

    const dominance = retrievalDebug.dominance || {};
    const topFiles = dominance.top_files_by_raw_hits || [];
    const topArtifacts = dominance.top_artifacts_by_raw_hits || [];
    const topChunks = dominance.top_chunks_by_raw_hits || [];

    if (topFiles.length) {
      lines.push("");
      lines.push("Top files by raw hits:");
      for (const [k, v] of topFiles) lines.push(`  ${k}: ${v}`);
    }

    if (topArtifacts.length) {
      lines.push("");
      lines.push("Top artifacts by raw hits:");
      for (const [k, v] of topArtifacts) lines.push(`  ${k}: ${v}`);
    }

    if (topChunks.length) {
      lines.push("");
      lines.push("Top chunks by raw hits:");
      for (const [k, v] of topChunks) lines.push(`  ${k}: ${v}`);
    }

    accordion.appendChild(
      createCtxSection(
        "retrievalDiag",
        "Retrieval Diagnostics",
        createCtxPre(lines.join("\n")),
        `${retrievalMode} · raw=${rawCount} · fts=${ftsCount} \n vector=${vectorCount} · final=${afterDiversify}`
      )
    );
  }

  // RAG Raw Hits
  {
    const lines = [];
    if (rawRows.length) {
      for (const r of rawRows.slice(0, 50)) {
        const src = r.filename || r.scope_key || r.source_kind || "source";
        const channels = (r.retrieval_channels || []).join("+") || "?";
        lines.push(
          `- ${src}#${r.chunk_index} chunk_id=${r.chunk_id} artifact_id=${r.artifact_id} file_id=${r.file_id || ""} channels=${channels} score=${fmtScore(r.score)} fts=${fmtScore(r.fts_score)} vec=${fmtScore(r.vector_score)}${accessMetaSuffix(r)}`
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

        const channels = (r.retrieval_channels || []).join("+") || "?";
        lines.push(
          `- ${src}#${r.chunk_index} chunk_id=${r.chunk_id} channels=${channels} final=${fmtScore(r.final_score ?? r.score)} fts=${fmtScore(r.fts_score)} vec=${fmtScore(r.vector_score)} rrf=${fmtScore(r.rrf_score)} ts=${ts}${accessMetaSuffix(r)}`
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
      return `${item.kind}: ${label} (raw hits=${item.raw_hit_count}, score=${item.score})${accessMetaSuffix(item)}`;
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

// #endregion

// #region Library model helpers



function openLibraryModalForConversation(convId) {
  libraryModalMode = "conversation";
  libraryModalConversationId = convId;
  libraryModalProjectId = null;
  loadLibraryModal();
}

function openLibraryModalForProject(pid) {
  libraryModalMode = "project";
  libraryModalProjectId = pid;
  libraryModalConversationId = null;
  loadLibraryModal();
}

function openLibraryModalGlobal() {
  libraryModalMode = "global";
  libraryModalConversationId = null;
  libraryModalProjectId = null;
  loadLibraryModal();
}

function closeLibraryModal() {
  if (!libraryModal) return;
  libraryModal.classList.add("hidden");
  libraryModalMode = null;
  libraryModalConversationId = null;
  libraryModalProjectId = null;
}

function renderLibraryItemCard(item, fallbackScopeLabel = "") {
  const card = document.createElement("div");
  card.className = "libraryCard";

  const body = document.createElement("div");
  body.className = "libraryCardBody";
  card.appendChild(body);

  if (item.thumbnail_url) {
    const thumbWrap = document.createElement("div");
    thumbWrap.className = "libraryThumbWrap";
    const thumb = document.createElement("img");
    thumb.className = "libraryThumb";
    thumb.src = item.thumbnail_url;
    thumb.alt = item.title || item.id || "Image preview";
    thumb.loading = "lazy";
    thumb.addEventListener("error", () => thumbWrap.remove());
    thumbWrap.appendChild(thumb);
    body.appendChild(thumbWrap);
  }

  const content = document.createElement("div");
  content.className = "libraryCardContent";
  body.appendChild(content);

  const header = document.createElement("div");
  header.className = "libraryCardHeader";

  const left = document.createElement("div");
  const title = document.createElement("div");
  title.className = "libraryCardTitle";
  title.textContent = item.title || item.id || "Untitled";
  left.appendChild(title);
  if (item.subtitle) {
    const subtitle = document.createElement("div");
    subtitle.className = "libraryCardSubtitle";
    subtitle.textContent = item.subtitle;
    left.appendChild(subtitle);
  }
  const resolvedScopeLabel = resolveCardScopeLabel(item, fallbackScopeLabel);
  if (item.scope_type && item.scope_type !== "global" && resolvedScopeLabel) {
    const scopeSubtitle = document.createElement("div");
    scopeSubtitle.className = "libraryCardSubtitle";
    scopeSubtitle.textContent = `${item.scope_type === "project" ? "Project" : "Conversation"}: ${resolvedScopeLabel}`;
    left.appendChild(scopeSubtitle);
  }

  const right = document.createElement("div");
  right.className = "libraryBadges";
  const identity = item.identity || {};
  if (identity.visibility) {
    const visibilityBadge = document.createElement("span");
    visibilityBadge.className = `libraryBadge libraryBadgeVisibility libraryBadgeVisibility-${String(identity.visibility).toLowerCase()}`;
    visibilityBadge.textContent = identity.visibility;
    right.appendChild(visibilityBadge);
  }
  if (identity.tenant_id && identity.tenant_id !== "default") {
    const tenantBadge = document.createElement("span");
    tenantBadge.className = "libraryBadge libraryBadgeTenant";
    tenantBadge.textContent = identity.tenant_id;
    right.appendChild(tenantBadge);
  }
  appendAccessBadges(right, item);
  (item.badges || []).forEach((badge) => {
    const el = document.createElement("span");
    el.className = "libraryBadge";
    el.textContent = badge;
    right.appendChild(el);
  });

  if (item.updated_at) {
    const ts = document.createElement("span");
    ts.className = "libraryBadge";
    ts.textContent = formatReadableDateTime(item.updated_at);
    right.appendChild(ts);
  }

  header.appendChild(left);
  header.appendChild(right);
  content.appendChild(header);

  const meta = document.createElement("div");
  meta.className = "libraryMeta";
  (item.meta || []).forEach((line) => {
    const row = document.createElement("div");
    row.textContent = line;
    meta.appendChild(row);
  });
  content.appendChild(meta);

  const actions = document.createElement("div");
  actions.className = "libraryActions";
  if (item.sharing_resource_type && item.sharing_resource_id && typeof openSharingDiagnostics === "function") {
    const sharingBtn = document.createElement("button");
    sharingBtn.textContent = "Sharing...";
    sharingBtn.addEventListener("click", async () => {
      try {
        await openSharingDiagnostics(item.sharing_resource_type, item.sharing_resource_id);
      } catch (e) {
        console.error("openSharingDiagnostics from library failed", e);
        alert("Failed to load sharing diagnostics.");
      }
    });
    actions.appendChild(sharingBtn);
  }
  (item.promote_targets || []).forEach((target) => {
    const btn = document.createElement("button");
    btn.textContent = target.label || "Promote";
    btn.addEventListener("click", async () => {
      const what = item.item_kind === "file" ? "file" : "artifact";
      const ok = confirm(`${target.label} “${item.title || item.id}”?`);
      if (!ok) return;

      const url = item.item_kind === "file"
        ? `/api/files/${encodeURIComponent(item.id)}/move_scope`
        : `/api/artifacts/${encodeURIComponent(item.id)}/move_scope`;
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scope_type: target.scope_type,
          scope_id: target.scope_id ?? null,
          scope_uuid: target.scope_uuid ?? null,
        }),
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        alert(`Failed to promote ${what} (HTTP ${res.status}). ${txt.slice(0, 200)}`);
        return;
      }
      try { await refreshContext(); } catch (e) { console.warn("refreshContext failed after librarian promote", e); }
      try { await refreshConversationLists(); } catch (e) { console.warn("refreshConversationLists failed after librarian promote", e); }
      try { await refreshGlobalFilesState(); } catch (e) { console.warn("refreshGlobalFilesState failed after librarian promote", e); }
      await loadLibraryModal();
    });
    actions.appendChild(btn);
  });

  if (!actions.children.length && item.promote_disabled_reason) {
    const hint = document.createElement("div");
    hint.className = "libraryEmpty";
    hint.textContent = item.promote_disabled_reason;
    actions.appendChild(hint);
  }

  if (actions.children.length) {
    content.appendChild(actions);
   }
 
   return card;
}

function renderLibraryGroup(section, group, scopeKey, fallbackScopeLabel = "") {
  const wrap = document.createElement("div");
  wrap.className = "libraryGroup";
  const items = Array.isArray(group?.items) ? group.items : [];
  const itemCount = items.length;
  const groupKey = `${scopeKey}:${section?.key || "section"}:${group?.key || "group"}`;
  const canCollapse = itemCount > LIBRARY_COLLAPSE_THRESHOLD;
  const collapsed = canCollapse ? (libraryGroupCollapseState.get(groupKey) ?? true) : false;
  if (collapsed) wrap.classList.add("is-collapsed");

  const header = document.createElement(canCollapse ? "button" : "div");
  header.className = "libraryGroupHeader";
  if (canCollapse) {
    header.type = "button";
    header.setAttribute("aria-expanded", collapsed ? "false" : "true");
  }

  const titleRow = document.createElement("div");
  titleRow.className = "libraryGroupTitleRow";
  if (canCollapse) {
    const caret = document.createElement("span");
    caret.className = "libraryCaret";
    caret.textContent = collapsed ? "▸" : "▾";
    titleRow.appendChild(caret);
  }

  const gt = document.createElement("div");
  gt.className = "libraryGroupTitle";
  gt.textContent = group.title || group.key || "Group";
  titleRow.appendChild(gt);

  const count = document.createElement("div");
  count.className = "libraryGroupCount";
  count.textContent = `${itemCount} item${itemCount === 1 ? "" : "s"}`;
  header.appendChild(titleRow);
  header.appendChild(count);
  wrap.appendChild(header);

  const cards = document.createElement("div");
  cards.className = "libraryCards";
  items.forEach((item) => cards.appendChild(renderLibraryItemCard(item, fallbackScopeLabel)));
  wrap.appendChild(cards);
  if (canCollapse) {
    header.addEventListener("click", () => {
      const next = !wrap.classList.contains("is-collapsed");
      wrap.classList.toggle("is-collapsed", next);
      libraryGroupCollapseState.set(groupKey, next);
      header.setAttribute("aria-expanded", next ? "false" : "true");
      const caret = header.querySelector(".libraryCaret");
      if (caret) caret.textContent = next ? "▸" : "▾";
    });
  }
  return wrap;
}

function renderLibraryModal(data) {
  if (!librarySectionsEl) return;
  librarySectionsEl.innerHTML = "";
  libraryTitleEl.textContent = `${data?.scope_label || "Library"}`;
  libraryScopeNoteEl.textContent = data?.scope_note || "";

  const sections = Array.isArray(data?.sections) ? data.sections : [];
  if (!sections.length) {
    librarySectionsEl.textContent = "Nothing here yet.";
    return;
  }

  let renderedAny = false;
  const scopeKey = `${data?.scope_type || "library"}:${data?.scope_id || "root"}`;
  const projectFallbackLabel =
    data?.scope_type === "project" ? String(data?.scope_label || "").trim() : "";

  sections.forEach((section) => {
    const groups = Array.isArray(section?.groups) ? section.groups : [];
    if (!groups.length) return;
    renderedAny = true;

    const sec = document.createElement("div");
    sec.className = "librarySection";

    const title = document.createElement("div");
    title.className = "librarySectionTitle";
    title.textContent = section.title || section.key || "Section";
    sec.appendChild(title);

    groups.forEach((group) => {
      sec.appendChild(renderLibraryGroup(section, group, scopeKey, projectFallbackLabel));
    });

    librarySectionsEl.appendChild(sec);
  });

  if (!renderedAny) {
    const empty = document.createElement("div");
    empty.className = "libraryEmpty";
    empty.textContent = "Nothing here yet.";
    librarySectionsEl.appendChild(empty);
  }
}

async function loadLibraryModal() {
  if (!libraryModal || !librarySectionsEl) return;
  hideAllTransientUI({ except: [libraryModal] });
  await ensureProjectsCacheLoaded();

  let url = "/api/library/global";
  if (libraryModalMode === "conversation" && libraryModalConversationId) {
    url = `/api/conversation/${encodeURIComponent(libraryModalConversationId)}/library`;
  } else if (libraryModalMode === "project" && libraryModalProjectId != null) {
    url = `/api/projects/${encodeURIComponent(libraryModalProjectId)}/library`;
  }
  const params = new URLSearchParams({
    principal_type: "user",
    principal_id: "local",
    tenant_id: "default",
    admin_view: libraryAdminViewToggle && libraryAdminViewToggle.checked ? "true" : "false",
  });
  url += `${url.includes("?") ? "&" : "?"}${params.toString()}`;

  librarySectionsEl.textContent = "Loading…";
  libraryModal.classList.remove("hidden");

  try {
    const data = await fetchJsonDebug(url);
    renderLibraryModal(data || {});
  } catch (err) {
    console.error("library load failed", err);
    librarySectionsEl.textContent = "Failed to load library.";
  }
}

// #endregion
