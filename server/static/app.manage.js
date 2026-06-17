
// #region Personalization Modal Helpers

function syncModelSettingsLabels() {
  if (modelTemperatureValueEl && modelTemperatureEl) modelTemperatureValueEl.textContent = `Current: ${Number(modelTemperatureEl.value || 0).toFixed(1)}`;
  if (modelThinkingLevelValueEl && modelThinkingLevelEl) modelThinkingLevelValueEl.textContent = `Current: ${modelThinkingLevelEl.value || "0"}`;
  if (modelVerbosityValueEl && modelVerbosityEl) modelVerbosityValueEl.textContent = `Current: ${modelVerbosityEl.value || "0"}`;
  if (modelToolAggressivenessValueEl && modelToolAggressivenessEl) modelToolAggressivenessValueEl.textContent = `Current: ${modelToolAggressivenessEl.value || "0"}`;
}

function applyPersonalizationSectionVisibility() {
  const isGlobal = personalizationMode === "global";
  const isProject = personalizationMode === "project";
  const isConversation = personalizationMode === "conversation";
  if (projectSettingsSectionEl) projectSettingsSectionEl.classList.toggle("hidden", !isProject);
  if (aboutYouSectionEl) aboutYouSectionEl.classList.toggle("hidden", !isGlobal);
  if (querySettingsSectionEl) querySettingsSectionEl.classList.toggle("hidden", isConversation);
  if (customInstructionsSectionEl) customInstructionsSectionEl.classList.toggle("hidden", isConversation);
  if (memoriesSectionEl) memoriesSectionEl.classList.toggle("hidden", isConversation);
  if (modelSettingsSectionEl) modelSettingsSectionEl.classList.remove("hidden");
}

function setPersonalizationModeGlobal() {
  personalizationMode = "global";
  personalizationProjectId = null;
  personalizationConversationId = null;
  applyPersonalizationSectionVisibility();
  const title = persModal?.querySelector(".modalTitle");
  if (title) title.textContent = "Personalization";
  if (projectSettingsTitle) projectSettingsTitle.textContent = "Project Settings";
  if (querySettingsTitleEl) querySettingsTitleEl.textContent = "Global Query / Retrieval Settings";
  if (modelSettingsTitleEl) modelSettingsTitleEl.textContent = "Global Model Behavior Settings";
}

function setPersonalizationModeProject(projectObj) {
  personalizationMode = "project";
  personalizationProjectId = projectObj?.id ?? null;
  personalizationConversationId = null;
  applyPersonalizationSectionVisibility();

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
  if (modelSettingsTitleEl) {
    modelSettingsTitleEl.textContent = `Project Model Behavior Settings — ${projectObj?.name || "Project"}`;
  }
}

function setPersonalizationModeConversation(conversationObj) {
  personalizationMode = "conversation";
  personalizationConversationId = conversationObj?.id ?? conversationId ?? null;
  personalizationProjectId = conversationObj?.project_id ?? null;
  applyPersonalizationSectionVisibility();
  const label = conversationObj?.title || "Conversation";
  const title = persModal?.querySelector(".modalTitle");
  if (title) title.textContent = `Conversation Settings — ${label}`;
  if (modelSettingsTitleEl) modelSettingsTitleEl.textContent = `Conversation Model Behavior Settings — ${label}`;
}

function openMemoryModal() {
  if (!persModal) return;
  hideAllTransientUI({ except: [persModal] });
  persModal.classList.remove("hidden");
}

function closeMemoryModal() {
  if (!persModal) return;
  persModal.classList.add("hidden");
}

async function loadPersonalization() {
  const [pins, aboutYou] = await Promise.all([
    fetchPins(),
    fetchAboutYou(),
    loadMemories(),
    loadQuerySettingsForCurrentMode(),
    loadModelSettingsForCurrentMode()
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

async function fetchModelSettings(scopeType, scopeId = "") {
  const qs = new URLSearchParams({ scope_type: scopeType || "global", scope_id: String(scopeId || "") });
  return await fetchJsonDebug(`/api/model_settings?${qs.toString()}`);
}

function _modelSettingsScopeParts() {
  if (personalizationMode === "project") return { scopeType: "project", scopeId: String(personalizationProjectId || "") };
  if (personalizationMode === "conversation") return { scopeType: "conversation", scopeId: String(personalizationConversationId || conversationId || "") };
  return { scopeType: "global", scopeId: "" };
}

function populateModelSettingsForm(data) {
  const eff = data?.effective || {};
  if (modelTemperatureEl) modelTemperatureEl.value = String(eff.temperature ?? 0.7);
  if (modelThinkingLevelEl) modelThinkingLevelEl.value = String(eff.thinking_level ?? 0);
  if (modelShowThinkingEl) modelShowThinkingEl.checked = !!eff.show_thinking;
  if (modelVerbosityEl) modelVerbosityEl.value = String(eff.verbosity ?? 5);
  if (modelToolAggressivenessEl) modelToolAggressivenessEl.value = String(eff.tool_aggressiveness ?? 5);
  if (modelMaxOutputTokensEl) modelMaxOutputTokensEl.value = eff.max_output_tokens == null ? "" : String(eff.max_output_tokens);
  if (modelTopPEl) modelTopPEl.value = eff.top_p == null ? "" : String(eff.top_p);
  if (modelTopKEl) modelTopKEl.value = eff.top_k == null ? "" : String(eff.top_k);
  syncModelSettingsLabels();
}

async function loadModelSettingsForCurrentMode() {
  const { scopeType, scopeId } = _modelSettingsScopeParts();
  const data = await fetchModelSettings(scopeType, scopeId);
  populateModelSettingsForm(data);
  if (resetModelSettingsBtn) resetModelSettingsBtn.disabled = scopeType === "global";
  return data;
}

async function saveModelSettingsForCurrentMode() {
  const { scopeType, scopeId } = _modelSettingsScopeParts();
  const payload = {
    scope_type: scopeType,
    scope_id: scopeId,
    temperature: parseFloat(modelTemperatureEl?.value || "0.7"),
    thinking_level: parseInt(modelThinkingLevelEl?.value || "0", 10) || 0,
    show_thinking: !!modelShowThinkingEl?.checked,
    verbosity: parseInt(modelVerbosityEl?.value || "5", 10) || 0,
    tool_aggressiveness: parseInt(modelToolAggressivenessEl?.value || "5", 10) || 0,
    max_output_tokens: modelMaxOutputTokensEl?.value ? parseInt(modelMaxOutputTokensEl.value, 10) : null,
    top_p: modelTopPEl?.value ? parseFloat(modelTopPEl.value) : null,
    top_k: modelTopKEl?.value ? parseInt(modelTopKEl.value, 10) : null,
  };
  const data = await fetchJsonDebug('/api/model_settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  populateModelSettingsForm(data);
  return data;
}

async function resetModelSettingsForCurrentMode() {
  const { scopeType, scopeId } = _modelSettingsScopeParts();
  if (scopeType === 'global') return;
  const qs = new URLSearchParams({ scope_type: scopeType, scope_id: scopeId });
  const data = await fetchJsonDebug(`/api/model_settings?${qs.toString()}`, { method: 'DELETE' });
  populateModelSettingsForm(data);
  return data;
}

// #endregion

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

// #endregion

// #region Conversation management (context menu/modal) helpers

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

async function fetchConversations(limit = null) {
  const params = new URLSearchParams();
  if (limit != null) {
    params.set("limit", String(limit));
  }
  const url = `/api/conversations${params.toString() ? `?${params.toString()}` : ""}`;
  const list = await fetchJsonDebug(url);
  const nextMap = new Map(conversationMap);
  list.forEach(x => nextMap.set(x.id, x));
  conversationMap = nextMap;
  return list;
}

function updateChatTitle() {
  const meta = conversationMap.get(conversationId);
  topBarChatTitleEl.textContent = meta?.title || "…";
}

async function selectConversation(cid, opts = {}) {
  const refreshLists = opts.refreshLists !== false;
  const previousCid = conversationId;

  cancelScheduledContextRefresh();
  cancelScheduledTranscriptRefresh();

  if (previousCid && previousCid !== cid) {
    // best-effort flush of old conversation transcript before switching away
    void flushConversationTranscriptArtifact(previousCid, "switch");
  }

  conversationId = cid;
  localStorage.setItem("callie_mvp_conversation_id", conversationId);

  if (refreshLists) {
    await refreshConversationLists();
  } else {
    updateChatTitle();
  }

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
    //renderConversations(conversations);

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
    //renderConversations(c2);
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
  const conversations = await fetchConversations(1000000);
  renderProjects(projectsCache, conversations);
  //renderConversations(conversations);
  return conversations;
}

async function renameChat() {
  if (!conversationId) return;
  const current = conversationMap.get(conversationId)?.title || "New chat";
  const next = prompt("Rename chat:", current);
  if (next === null) return;

  const title = next.trim();
  const res = await fetch(`/api/conversation/${conversationId}/title`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title })
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("Failed to rename chat: " + (err.detail || res.status));
    return;
  }

  await refreshConversationLists();
  await refreshContext();
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

async function ensureProjectsCacheLoaded() {
  if (Array.isArray(projectsCache) && projectsCache.length) return projectsCache;
  projectsCache = await fetchProjects();
  return projectsCache;
}

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
    const pid = c.project_id;
    if (pid == null) return;
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
      const next = !getProjectExpanded(p.id, containsActive);
      setProjectExpanded(p.id, next);
      renderProjects(projectsCache, conversations); // re-render just the project list
    });

    // Right-click opens the project context menu (rename/description)
    header.addEventListener("contextmenu", (ev) => {
      if (p.is_pseudo_global) {
        return;
      }
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

  updateChatTitle();
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
        <div id="metaInfoSharingEditor" class="sharingEditor hidden"></div>
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
  metaInfoSharingEditorEl = modal.querySelector("#metaInfoSharingEditor");

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
  if (metaInfoSharingEditorEl) {
    metaInfoSharingEditorEl.classList.add("hidden");
    metaInfoSharingEditorEl.innerHTML = "";
  }
  hideAllTransientUI({ except: [projMenuEl] });
  metaInfoModal.classList.remove("hidden");
}

function sharingRequestIdentity() {
  const identity = (typeof getCurrentIdentity === "function" ? getCurrentIdentity() : null) || {};
  return {
    requester_type: "user",
    requester_id: identity.user_id != null ? String(identity.user_id) : "local",
    requester_tenant_id: identity.tenant_id != null ? String(identity.tenant_id) : null,
    admin_view: libraryAdminViewToggle && libraryAdminViewToggle.checked ? "true" : "false",
  };
}

function sharingJsonFetch(url, body, method = "POST") {
  return fetchJsonDebug(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

function renderSharingDiagnosticsEditor(data) {
  if (!metaInfoSharingEditorEl || !data || !data.resource) return;
  const resource = data.resource;
  const resourceType = resource.resource_type;
  const resourceId = resource.resource_id;
  const provenance = resource.provenance_json || {};
  const directEntries = data.direct_access_control_entries || [];

  metaInfoSharingEditorEl.classList.remove("hidden");
  metaInfoSharingEditorEl.innerHTML = `
    <div class="sharingEditorGrid">
      <label>Visibility
        <select id="sharingEditorVisibility">
          <option value="">Leave unchanged</option>
          <option value="private">Private</option>
          <option value="tenant">Tenant</option>
          <option value="public">Public</option>
          <option value="inherit">Inherit</option>
        </select>
      </label>
      <label>Sharing
        <select id="sharingEditorMode">
          <option value="">Leave unchanged</option>
          <option value="owner">Owner</option>
          <option value="tenant">Tenant</option>
          <option value="public">Public</option>
          <option value="custom">Custom</option>
          <option value="inherit">Inherit</option>
        </select>
      </label>
    </div>
    <label class="sharingEditorWide">Provenance JSON
      <textarea id="sharingEditorProvenance" rows="4"></textarea>
    </label>
    <div class="modalActions sharingEditorActions">
      <button class="btn primary" id="sharingEditorSave">Save Sharing</button>
      <button class="btn" id="sharingEditorReload">Reload</button>
    </div>
    <div class="sharingEditorSection">
      <div class="sharingEditorTitle">Direct access entries</div>
      <div id="sharingEditorAceList" class="sharingAceList"></div>
    </div>
    <div class="sharingEditorGrid">
      <label>Effect
        <select id="sharingAceEffect">
          <option value="allow">Allow</option>
          <option value="deny">Deny</option>
        </select>
      </label>
      <label>Action
        <select id="sharingAceAction">
          <option value="read">Read</option>
          <option value="write">Write</option>
          <option value="share">Share</option>
          <option value="audit">Audit</option>
          <option value="use_in_context">Use in context</option>
          <option value="manage">Manage</option>
        </select>
      </label>
      <label>Principal type
        <select id="sharingAcePrincipalType">
          <option value="user">User</option>
          <option value="group">Group</option>
          <option value="role">Role</option>
          <option value="persona">Persona</option>
          <option value="tenant_users">Tenant users</option>
          <option value="tenant_personas">Tenant personas</option>
          <option value="public">Public</option>
          <option value="service">Service</option>
        </select>
      </label>
      <label>Principal ID
        <input id="sharingAcePrincipalId" placeholder="local">
      </label>
    </div>
    <label class="sharingEditorWide">Reason
      <input id="sharingAceReason" placeholder="Admin sharing edit">
    </label>
    <div class="modalActions sharingEditorActions">
      <button class="btn" id="sharingAceAdd">Add Entry</button>
    </div>
  `;

  const visibilityEl = metaInfoSharingEditorEl.querySelector("#sharingEditorVisibility");
  const modeEl = metaInfoSharingEditorEl.querySelector("#sharingEditorMode");
  const provenanceEl = metaInfoSharingEditorEl.querySelector("#sharingEditorProvenance");
  if (resource.visibility && visibilityEl) visibilityEl.value = resource.visibility;
  if (resource.sharing_mode && modeEl) modeEl.value = resource.sharing_mode;
  if (provenanceEl) provenanceEl.value = JSON.stringify(provenance, null, 2);

  const aceList = metaInfoSharingEditorEl.querySelector("#sharingEditorAceList");
  if (aceList) {
    if (!directEntries.length) {
      aceList.textContent = "No direct entries.";
    } else {
      directEntries.forEach((entry) => {
        const row = document.createElement("div");
        row.className = "sharingAceRow";
        const label = document.createElement("span");
        label.textContent = `${entry.effect} ${entry.action} for ${entry.principal_type}:${entry.principal_id}`;
        const removeBtn = document.createElement("button");
        removeBtn.className = "btn danger";
        removeBtn.textContent = "Remove";
        removeBtn.addEventListener("click", async () => {
          await sharingJsonFetch(`/api/sharing/access-control/${encodeURIComponent(entry.id)}`, sharingRequestIdentity(), "DELETE");
          await openSharingDiagnostics(resourceType, resourceId);
        });
        row.append(label, removeBtn);
        aceList.appendChild(row);
      });
    }
  }

  metaInfoSharingEditorEl.querySelector("#sharingEditorReload")?.addEventListener("click", () => {
    openSharingDiagnostics(resourceType, resourceId).catch(console.error);
  });
  metaInfoSharingEditorEl.querySelector("#sharingEditorSave")?.addEventListener("click", async () => {
    let parsedProvenance = {};
    try {
      parsedProvenance = JSON.parse(provenanceEl?.value || "{}");
    } catch (e) {
      alert("Provenance must be valid JSON.");
      return;
    }
    await sharingJsonFetch("/api/sharing/resource", {
      ...sharingRequestIdentity(),
      resource_type: resourceType,
      resource_id: resourceId,
      visibility: visibilityEl?.value || null,
      sharing_mode: modeEl?.value || null,
      provenance_json: JSON.stringify(parsedProvenance),
    }, "PUT");
    await openSharingDiagnostics(resourceType, resourceId);
  });
  metaInfoSharingEditorEl.querySelector("#sharingAceAdd")?.addEventListener("click", async () => {
    const principalType = metaInfoSharingEditorEl.querySelector("#sharingAcePrincipalType")?.value || "user";
    const principalId = metaInfoSharingEditorEl.querySelector("#sharingAcePrincipalId")?.value.trim() || "";
    if (!principalId) {
      alert("Principal ID is required.");
      return;
    }
    await sharingJsonFetch("/api/sharing/access-control", {
      ...sharingRequestIdentity(),
      resource_type: resourceType,
      resource_id: resourceId,
      effect: metaInfoSharingEditorEl.querySelector("#sharingAceEffect")?.value || "allow",
      action: metaInfoSharingEditorEl.querySelector("#sharingAceAction")?.value || "read",
      principal_type: principalType,
      principal_id: principalId,
      reason: metaInfoSharingEditorEl.querySelector("#sharingAceReason")?.value || "Admin sharing edit",
    });
    await openSharingDiagnostics(resourceType, resourceId);
  });
}

async function openSharingDiagnostics(resourceType, resourceId) {
  if (!resourceType || !resourceId) return;
  const params = new URLSearchParams({
    resource_type: resourceType,
    resource_id: String(resourceId),
    action: "read",
    principal_type: "user",
    principal_id: "local",
  });
  const data = await fetchJsonDebug(`/api/sharing/diagnostics?${params.toString()}`);
  openMetaInfo(`Sharing: ${resourceType} ${resourceId}`, data);
  renderSharingDiagnosticsEditor(data);
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
