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

if (convMenuCitationsBtn) {
  convMenuCitationsBtn.addEventListener("click", () => {
    convMenuEl.classList.add("hidden");
    const cid = menuTargetConversationId || conversationId;
    if (!cid) {
      alert("No conversation selected.");
      return;
    }
    openCitationsModalForConversation(cid).catch(e => {
      console.error("openCitationsModalForConversation failed", e);
      alert("Failed to load conversation citations.");
    });
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

if (projMenuCitationsBtn) {
  projMenuCitationsBtn.addEventListener("click", () => {
    projMenuEl.classList.add("hidden");
    const pid = menuTargetProjectId;
    if (!pid) {
      alert("No project selected.");
      return;
    }
    openCitationsModalForProject(pid).catch(e => {
      console.error("openCitationsModalForProject failed", e);
      alert("Failed to load project citations.");
    });
  });
}

if (projMenuSharingBtn) {
  projMenuSharingBtn.addEventListener("click", () => {
    projMenuEl.classList.add("hidden");
    const pid = menuTargetProjectId;
    if (!pid) {
      alert("No project selected.");
      return;
    }
    openSharingDiagnostics("project", pid).catch(e => {
      console.error("openSharingDiagnostics project failed", e);
      alert("Failed to load sharing diagnostics.");
    });
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


if (topMenuLibraryBtn) {
  topMenuLibraryBtn.addEventListener("click", () => {
    openLibraryModalGlobal();
  });
}

if (convMenuLibraryBtn) {
  convMenuLibraryBtn.addEventListener("click", () => {
    convMenuEl.classList.add("hidden");
    const cid = menuTargetConversationId || conversationId;
    if (!cid) {
      alert("No conversation selected.");
      return;
    }
    openLibraryModalForConversation(cid);
  });
}

if (convMenuSharingBtn) {
  convMenuSharingBtn.addEventListener("click", () => {
    convMenuEl.classList.add("hidden");
    const cid = menuTargetConversationId || conversationId;
    if (!cid) {
      alert("No conversation selected.");
      return;
    }
    openSharingDiagnostics("conversation", cid).catch(e => {
      console.error("openSharingDiagnostics conversation failed", e);
      alert("Failed to load sharing diagnostics.");
    });
  });
}

if (projMenuLibraryBtn) {
  projMenuLibraryBtn.addEventListener("click", () => {
    projMenuEl.classList.add("hidden");
    const pid = menuTargetProjectId;
    if (!pid) {
      alert("No project selected.");
      return;
    }
    openLibraryModalForProject(pid);
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
if (citationsCloseBtn) {
  citationsCloseBtn.addEventListener("click", closeCitationsModal);
}
if (citationsCloseBottomBtn) {
  citationsCloseBottomBtn.addEventListener("click", closeCitationsModal);
}
if (citationsBackdrop) {
  citationsBackdrop.addEventListener("click", closeCitationsModal);
}
if (libraryCloseBtn) {
  libraryCloseBtn.addEventListener("click", closeLibraryModal);
}
if (libraryCloseBottomBtn) {
  libraryCloseBottomBtn.addEventListener("click", closeLibraryModal);
}
if (libraryBackdrop) {
  libraryBackdrop.addEventListener("click", closeLibraryModal);
}
if (libraryAdminViewToggle) {
  libraryAdminViewToggle.addEventListener("change", () => {
    if (libraryModal && !libraryModal.classList.contains("hidden")) {
      loadLibraryModal();
    }
  });
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
if (convMenuSettingsBtn) {
  convMenuSettingsBtn.addEventListener("click", async () => {
    convMenuEl.classList.add("hidden");
    const cid = menuTargetConversationId || conversationId;
    if (!cid) {
      alert("No conversation selected.");
      return;
    }
    const conv = conversationMap.get(cid) || { id: cid, title: topBarChatTitleEl?.textContent || "Conversation" };
    setPersonalizationModeConversation(conv);
    openMemoryModal();
    try {
      await loadPersonalization();
    } catch (e) {
      console.error("load conversation personalization failed", e);
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
if (aboutYouSharingBtn) {
  aboutYouSharingBtn.addEventListener("click", () => {
    openSharingDiagnostics("user_profile", "local").catch(e => {
      console.error("openSharingDiagnostics about you failed", e);
      alert("Failed to load sharing diagnostics.");
    });
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

if (saveModelSettingsBtn) {
  saveModelSettingsBtn.addEventListener("click", async () => {
    try {
      await saveModelSettingsForCurrentMode();
      await refreshContext();
    } catch (e) {
      console.error("saveModelSettingsForCurrentMode failed", e);
      alert("Failed to save model settings.");
    }
  });
}
if (resetModelSettingsBtn) {
  resetModelSettingsBtn.addEventListener("click", async () => {
    try {
      await resetModelSettingsForCurrentMode();
      await refreshContext();
    } catch (e) {
      console.error("resetModelSettingsForCurrentMode failed", e);
      alert("Failed to reset scoped model settings.");
    }
  });
}
[modelTemperatureEl, modelThinkingLevelEl, modelVerbosityEl, modelToolAggressivenessEl].forEach((el) => {
  if (el) el.addEventListener("input", syncModelSettingsLabels);
});

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

    hideConvMenu();

    const res = await fetch(`/api/conversation/${cid}/title`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: next.trim() })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert("Failed to rename chat: " + (err.detail || res.status));
      return;
    }

    await refreshConversationLists();

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

    /*
    const conversations = await fetchConversations();
    renderConversations(conversations);
    */
    // do the project aware version - not optimized for a single conversation
    refreshConversationLists();

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
    //renderConversations(conversations);
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
      //renderConversations(conversations);

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

async function archiveProject(projectId, archived = true) {
  const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/archive`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ archived: !!archived }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return await res.json();
}

async function fetchProjectDeletePreview(projectId) {
  const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/delete_preview`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return await res.json();
}

function buildProjectDeleteConfirmationMessage(projectName, preview) {
  const title = (projectName || preview?.name || "this project").trim();
  const convCount = Number(preview?.conversation_count || 0);
  const fileCount = Number(preview?.file_count || 0);
  const artifactCount = Number(preview?.artifact_count || 0);
  const sessionCount = Number(preview?.reading_session_count || 0);

  const lines = [
    `Delete project “${title}”?`,
    "",
    "This will:",
    `- move ${convCount} conversation${convCount === 1 ? "" : "s"} to Unassigned Chats`,
    `- promote ${fileCount} file${fileCount === 1 ? "" : "s"} to global scope`,
    `- update ${artifactCount} artifact${artifactCount === 1 ? "" : "s"} that belong to this project`,
  ];

  if (sessionCount > 0) {
    lines.push(`- keep ${sessionCount} reading session${sessionCount === 1 ? "" : "s"} attached to their conversations`);
  }

  lines.push("", "This cannot be undone.");
  return lines.join("\n");
}

async function deleteProjectWithConfirmation(projectId, projectName) {
  let preview = null;
  try {
    preview = await fetchProjectDeletePreview(projectId);
  } catch (e) {
    console.error("fetchProjectDeletePreview failed", e);
  }

  const message = preview
    ? buildProjectDeleteConfirmationMessage(projectName, preview)
    : `Delete project “${(projectName || "this project").trim()}”? This cannot be undone.`;

  const ok = confirm(message);
  if (!ok) return false;

  const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert("Failed to delete project: " + (err.detail || res.status));
    return false;
  }
  return true;
}

if (projMenuToggleVisibility) {
  projMenuToggleVisibility.addEventListener("click", async () => {
    const pid = menuTargetProjectId;
    hideProjMenu();
    if (!pid) return;

    const proj = projectsCache.find(p => Number(p.id) === Number(pid));
    if (!proj) return;

    const nextVisibility = proj.visibility === "global" ? "private" : "global";

    if (await updateProject(pid, { visibility: nextVisibility })) {
      const [p2, c2] = await Promise.all([fetchProjects(), fetchConversations()]);
      renderProjects(p2, c2);

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
      const [projects, conversations] = await Promise.all([fetchProjects(), fetchConversations()]);
      renderProjects(projects, conversations);
    } catch (e) {
      console.error("create project failed", e);
      alert("Error creating project.");
    }
  });
}

if (projMenuArchiveBtn) {
  projMenuArchiveBtn.addEventListener("click", async () => {
    const pid = menuTargetProjectId;
    const proj = projectsCache.find(p => Number(p.id) === Number(pid));
    hideProjMenu();
    if (!pid || !proj) return;

    const ok = confirm(`Archive project “${proj.name}”? It will be hidden from the sidebar.`);
    if (!ok) return;

    try {
      await archiveProject(pid, true);
      await refreshConversationLists();
      await refreshContext();
    } catch (e) {
      console.error("archiveProject failed", e);
      alert("Failed to archive project.");
    }
  });
}

if (projMenuDeleteBtn) {
  projMenuDeleteBtn.addEventListener("click", async () => {
    const pid = menuTargetProjectId;
    const proj = projectsCache.find(p => Number(p.id) === Number(pid));
    hideProjMenu();
    if (!pid || !proj) return;

    const didDelete = await deleteProjectWithConfirmation(pid, proj.name);
    if (!didDelete) return;
    const [p2, c2] = await Promise.all([fetchProjects(), fetchConversations()]);
    renderProjects(p2, c2);
    //await refreshConversationLists();
    await refreshContext();
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
      //renderConversations(c2);
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
      //renderConversations(c2);
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
  if (e.key === "Escape" && libraryModal && !libraryModal.classList.contains("hidden")) {
    closeLibraryModal();
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
    // We no longer need this call to get the model list
    // deployments handles all of this now.
    //await refreshModels(true);
    await refreshDeployments(true);
    // advancedMode restored already; just apply once

    bootLog("[boot] applyAdvancedVisibility");
    applyAdvancedVisibility();

    const saved = localStorage.getItem("callie_mvp_conversation_id");

    bootLog("[boot] fetchRecentConversations");
    const recentConversations = await fetchConversations(10);
    bootLog("[boot] pick conversation", { saved, count: recentConversations.length });

    if (saved) {
      bootLog("[boot] select saved without sidebar refresh");
      await selectConversation(saved, { refreshLists: false });
    } else if (recentConversations.length) {
      bootLog("[boot] select first recent without sidebar refresh");
      await selectConversation(recentConversations[0].id, { refreshLists: false });
    } else {
      bootLog("[boot] newChat");
      await newChat();
    }

    bootLog("[boot] fetchProjects");
    const projects = await fetchProjects();
    projectsCache = projects;

    bootLog("[boot] renderProjects");
    renderProjects(projects, recentConversations);
    //bootLog("[boot] renderConversations");
    //renderConversations(recentConversations);

    void (async () => {
      try {
        bootLog("[boot-bg] fetchAllConversations");
        const allConversations = await fetchConversations(1000000);
        bootLog("[boot-bg] renderProjects/all");
        renderProjects(projectsCache, allConversations);
        //bootLog("[boot-bg] renderConversations/all");
        //renderConversations(allConversations);
        updateChatTitle();
      } catch (e) {
        console.error("[boot-bg] FAILED", e);
      }
    })();

    bootLog("[boot] loadPersonalization");
    await loadPersonalization();
    bootLog("[boot] loadMemories");
    await loadMemories();
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
