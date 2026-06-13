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
  if (conversationId) params.set("conversation_id", conversationId);
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
  selectedManageFileIds.clear();
  loadFilesModal();
}

function openFilesModalForProject(pid) {
  filesModalMode = "project";
  filesModalProjectId = pid;
  filesModalConversationId = null;
  selectedManageFileIds.clear();
  loadFilesModal();
}

function openFilesModalGlobal() {
  filesModalMode = "global";
  filesModalConversationId = null;
  filesModalProjectId = null;
  selectedManageFileIds.clear();
  loadFilesModal();
}

function openFilesModalAll() {
  filesModalMode = "all";
  filesModalConversationId = null;
  filesModalProjectId = null;
  selectedManageFileIds.clear();
  loadFilesModal();
}

function normalizeManageFilesScopeType(scopeType) {
  const st = (scopeType || "").trim().toLowerCase();
  if (st === "conversation") return "conversation";
  if (st === "project") return "project";
  return "global";
}

function looksLikeImageFile(file) {
  const mime = String(file?.mime_type || "").trim().toLowerCase();
  const name = String(file?.name || file?.title || "").trim().toLowerCase();
  return mime.startsWith("image/") || /\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(name);
}

function buildManageFilesScopeNote(data) {
  if (filesModalMode === "conversation") {
    return "Conversation files plus inherited project/global files.";
  }
  if (filesModalMode === "project") {
    return "Project files, conversation-scoped files in this project, and inherited global files.";
  }
  if (filesModalMode === "global") {
    return "Globally scoped files.";
  }
  return "All files grouped by scope.";
}

function getMovableProjectsForFiles() {
  return (projectsCache || []).filter((p) => {
    const visibilityOk = !p?.is_hidden;
    return visibilityOk && String(p?.visibility || "").toLowerCase() !== "global";
  });
}

function lookupManageFileScopeLabel(file, scopeType) {
  const direct = String(file?.scope_label || "").trim();
  if (direct) return direct;

  if (scopeType === "project" && file?.scope_id != null) {
    const project = (projectsCache || []).find((p) => Number(p.id) === Number(file.scope_id));
    return project?.name || null;
  }
  if (scopeType === "conversation" && file?.scope_uuid) {
    return conversationMap.get(String(file.scope_uuid))?.title || null;
  }
  return null;
}

function makeManageFilesItemFromRawFile(file) {
  const scopeType = normalizeManageFilesScopeType(file?.scope_type);
  const isImage = looksLikeImageFile(file);
  const promoteTargets = [];
  const fileMeta = parseManageFileMeta(file?.meta_json);
  const scopeLabel = lookupManageFileScopeLabel(file, scopeType);
  const imageCaption = String(fileMeta?.image_caption || "").trim();
  const imageOcrText = String(fileMeta?.image_ocr_text || "").trim();
  const importNote = String(fileMeta?.import_note || "").trim();
  const artifactTitle = String(file?.artifact_title || "").trim();
  const artifactId = String(file?.artifact_id || "").trim();
  const artifactSourceKind = String(file?.artifact_source_kind || "").trim();

  const meta = [
    `MIME: ${file.mime_type || "unknown"}`,
    `Scope: ${scopeType}`,
  ];
  if (scopeType === "project" && scopeLabel) meta.push(`Project: ${scopeLabel}`);
  if (scopeType === "conversation" && scopeLabel) meta.push(`Conversation: ${scopeLabel}`);
  if (artifactTitle) meta.push(`Artifact: ${artifactTitle}`);
  else if (artifactId) meta.push(`Artifact ID: ${artifactId}`);
  if (artifactSourceKind) meta.push(`Artifact source: ${artifactSourceKind}`);
  if (imageCaption) meta.push(`Image summary: ${imageCaption}`);
  if (imageOcrText) meta.push(`OCR text: ${imageOcrText}`);
  if (file?.artifact_summary_present || file?.artifact_index_present) {
    const helpers = [
      file?.artifact_summary_present ? "summary" : "",
      file?.artifact_index_present ? "index" : "",
    ].filter(Boolean).join(", ");
    if (helpers) meta.push(`Artifact helpers: ${helpers}`);
  }
  if (importNote) meta.push(`Import note: ${importNote}`);
  if (file.provenance) meta.push(`Provenance: ${file.provenance}`);

  const badges = [];
  if (isImage) badges.push("image");
  if (imageCaption) badges.push("captioned");
  if (imageOcrText) badges.push("ocr");

  if (scopeType === "conversation" && filesModalProjectId != null) {
    promoteTargets.push({
      label: "Move to Project",
      scope_type: "project",
      scope_id: filesModalProjectId,
      scope_uuid: null,
    });
  }

  if (scopeType === "conversation" || scopeType === "project") {
    promoteTargets.push({
      label: "Move to Global",
      scope_type: "global",
      scope_id: null,
      scope_uuid: null,
    });
  }

  return {
    item_kind: "file",
    id: file.id,
    title: file.name || file.path || file.id,
    description: file.description || "",
    scope_type: scopeType,
    scope_id: file.scope_id ?? null,
    scope_uuid: file.scope_uuid ?? null,
    scope_label: scopeLabel || "",
    updated_at: file.updated_at || file.created_at || null,
    badges,
    thumbnail_url: isImage ? `/api/files/${encodeURIComponent(file.id)}/thumbnail` : null,
    meta,
    meta_json: fileMeta,
    provenance: file.provenance || "",
    artifact_id: artifactId || "",
    artifact_title: artifactTitle || "",
    artifact_source_kind: artifactSourceKind || "",
    promote_targets: promoteTargets,
  };
}

function buildManageFilesDataFromLibrary(data) {
  const filesSection = (Array.isArray(data?.sections) ? data.sections : []).find((section) => section?.key === "files");
  return {
    title: `Files — ${data?.scope_label || "Files"}`,
    note: buildManageFilesScopeNote(data),
    groups: Array.isArray(filesSection?.groups) ? filesSection.groups : [],
  };
}

function buildManageFilesDataFromAll(files) {
  const items = (Array.isArray(files) ? files : []).map(makeManageFilesItemFromRawFile);
  const groups = [
    {
      key: "global",
      title: "Global scope",
      items: items.filter((item) => item.scope_type === "global"),
    },
    {
      key: "project",
      title: "Project scope",
      items: items.filter((item) => item.scope_type === "project"),
    },
    {
      key: "conversation",
      title: "Conversation scope",
      items: items.filter((item) => item.scope_type === "conversation"),
    },
  ].filter((group) => group.items.length);

  return {
    title: "Files — All",
    note: buildManageFilesScopeNote(null),
    groups,
  };
}

function pruneManageFilesSelection(groups) {
  const visibleIds = new Set();
  (groups || []).forEach((group) => {
    (group.items || []).forEach((item) => {
      if (item?.id) visibleIds.add(String(item.id));
    });
  });
  for (const fid of Array.from(selectedManageFileIds)) {
    if (!visibleIds.has(String(fid))) selectedManageFileIds.delete(String(fid));
  }
}

async function refreshManageFilesAndRelatedState() {
  await loadFilesModal();

  try {
    await refreshContext();
  } catch (e) {
    console.warn("refreshContext after file action failed", e);
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
}

async function moveFileToScope(item, target) {
  const label = target?.label || "Move file";
  const ok = confirm(`${label} “${item.title || item.id}”?`);
  if (!ok) return false;

  const res = await fetch(`/api/files/${encodeURIComponent(item.id)}/move_scope`, {
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
    alert(`Move failed (HTTP ${res.status}). ${txt.slice(0, 200)}`);
    return false;
  }

  selectedManageFileIds.delete(String(item.id));
  await refreshManageFilesAndRelatedState();
  return true;
}

async function renameManagedFile(item) {
  const current = item.title || item.id || "";
  const next = prompt("Rename file:", current);
  if (next === null) return false;
  const name = String(next || "").trim();
  if (!name || name === current) return false;

  const res = await fetch(`/api/files/${encodeURIComponent(item.id)}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    alert(`Rename failed (HTTP ${res.status}). ${txt.slice(0, 200)}`);
    return false;
  }

  await refreshManageFilesAndRelatedState();
}

async function describeManagedImage(item, buttonEl = null) {
  if (buttonEl) {
    buttonEl.disabled = true;
    buttonEl.dataset.originalText = buttonEl.textContent;
    buttonEl.textContent = "Thinking…";
  }
  try {
    const res = await fetch(`/api/files/${encodeURIComponent(item.id)}/describe_image`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ overwrite: true }),
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      alert(`Image description failed (HTTP ${res.status}). ${txt.slice(0, 300)}`);
      return false;
    }
    await refreshManageFilesAndRelatedState();
    return true;
  } catch (err) {
    console.error("describe image failed", err);
    alert("Image description failed: " + (err?.message || err));
    return false;
  } finally {
    if (buttonEl) {
      buttonEl.disabled = false;
      buttonEl.textContent = buttonEl.dataset.originalText || "Describe Image";
      delete buttonEl.dataset.originalText;
    }
  }
}

async function ocrManagedImage(item, buttonEl = null) {
  if (buttonEl) {
    buttonEl.disabled = true;
    buttonEl.dataset.originalText = buttonEl.textContent;
    buttonEl.textContent = "Reading…";
  }
  try {
    const res = await fetch(`/api/files/${encodeURIComponent(item.id)}/ocr_image`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ overwrite: true }),
    });
    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      alert(`Image OCR failed (HTTP ${res.status}). ${txt.slice(0, 300)}`);
      return false;
    }
    await refreshManageFilesAndRelatedState();
    return true;
  } catch (err) {
    console.error("image OCR failed", err);
    alert("Image OCR failed: " + (err?.message || err));
    return false;
  } finally {
    if (buttonEl) {
      buttonEl.disabled = false;
      buttonEl.textContent = buttonEl.dataset.originalText || "Read Text";
      delete buttonEl.dataset.originalText;
    }
  }
}

async function deleteManagedFile(item) {
  const ok = confirm(`Delete file "${item.title || item.id}" and its artifacts/chunks?`);
  if (!ok) return false;

  try {
    const res = await fetch(`/api/files/${encodeURIComponent(item.id)}`, {
      method: "DELETE",
    });

    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      alert(`Delete failed (HTTP ${res.status}). ${txt.slice(0, 200)}`);
      return false;
    }

    selectedManageFileIds.delete(String(item.id));
    await refreshManageFilesAndRelatedState();
    return true;
  } catch (err) {
    console.error("delete file failed", err);
    alert("Delete failed: " + (err?.message || err));
    return false;
  }
}

async function bulkMoveManagedFiles(target) {
  const fileIds = Array.from(selectedManageFileIds);
  if (!fileIds.length) {
    alert("Select one or more files first.");
    return false;
  }

  const ok = confirm(`${target.label || "Move files"} for ${fileIds.length} selected file${fileIds.length === 1 ? "" : "s"}?`);
  if (!ok) return false;

  const res = await fetch("/api/files/bulk_move_scope", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file_ids: fileIds,
      scope_type: target.scope_type,
      scope_id: target.scope_id ?? null,
      scope_uuid: target.scope_uuid ?? null,
    }),
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    alert(`Bulk move failed (HTTP ${res.status}). ${txt.slice(0, 200)}`);
    return false;
  }

  const data = await res.json().catch(() => ({}));
  const failed = Number(data?.failed || 0);
  if (failed > 0) {
    alert(`Bulk move finished with ${failed} failure${failed === 1 ? "" : "s"}.`);
  }
  selectedManageFileIds.clear();
  await refreshManageFilesAndRelatedState();
  return true;
}

async function bulkDeleteManagedFiles() {
  const fileIds = Array.from(selectedManageFileIds);
  if (!fileIds.length) {
    alert("Select one or more files first.");
    return false;
  }

  const ok = confirm(`Delete ${fileIds.length} selected file${fileIds.length === 1 ? "" : "s"} and their artifacts/chunks?`);
  if (!ok) return false;

  const res = await fetch("/api/files/bulk_delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_ids: fileIds }),
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    alert(`Bulk delete failed (HTTP ${res.status}). ${txt.slice(0, 200)}`);
    return false;
  }

  const data = await res.json().catch(() => ({}));
  const failed = Number(data?.failed || 0);
  if (failed > 0) {
    alert(`Bulk delete finished with ${failed} failure${failed === 1 ? "" : "s"}.`);
  }
  selectedManageFileIds.clear();
  await refreshManageFilesAndRelatedState();
  return true;
}

function renderFileProjectPicker(defaultProjectId = "") {
  const wrap = document.createElement("span");
  wrap.className = "filesProjectPicker";

  const select = document.createElement("select");
  select.className = "filesProjectSelect";

  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Project…";
  select.appendChild(placeholder);

  getMovableProjectsForFiles().forEach((project) => {
    const opt = document.createElement("option");
    opt.value = String(project.id);
    opt.textContent = project.name;
    if (String(defaultProjectId || "") === String(project.id)) opt.selected = true;
    select.appendChild(opt);
  });

  wrap.appendChild(select);
  return { wrap, select };
}

function renderManageFilesBulkBar(groups) {
  const allItems = [];
  (groups || []).forEach((group) => {
    (group.items || []).forEach((item) => allItems.push(item));
  });

  const bar = document.createElement("div");
  bar.className = "filesBulkBar";

  const summary = document.createElement("div");
  summary.className = "filesBulkSummary";
  bar.appendChild(summary);

  const actions = document.createElement("div");
  actions.className = "filesBulkActions";
  bar.appendChild(actions);

  const selectVisibleBtn = document.createElement("button");
  selectVisibleBtn.textContent = "Select Visible";
  selectVisibleBtn.addEventListener("click", async () => {
    allItems.forEach((item) => selectedManageFileIds.add(String(item.id)));
    renderManageFilesModal({
      title: filesTitleEl?.textContent || "Files",
      note: filesScopeNoteEl?.textContent || "",
      groups,
    });
  });
  actions.appendChild(selectVisibleBtn);

  const clearBtn = document.createElement("button");
  clearBtn.textContent = "Clear";
  clearBtn.addEventListener("click", () => {
    selectedManageFileIds.clear();
    renderManageFilesModal({
      title: filesTitleEl?.textContent || "Files",
      note: filesScopeNoteEl?.textContent || "",
      groups,
    });
  });
  actions.appendChild(clearBtn);

  const picker = renderFileProjectPicker();
  actions.appendChild(picker.wrap);

  const moveProjectBtn = document.createElement("button");
  moveProjectBtn.textContent = "Move to Project";
  moveProjectBtn.addEventListener("click", async () => {
    const projectId = String(picker.select.value || "").trim();
    if (!projectId) {
      alert("Choose a target project first.");
      return;
    }
    await bulkMoveManagedFiles({
      label: "Move to Project",
      scope_type: "project",
      scope_id: Number(projectId),
      scope_uuid: null,
    });
  });
  actions.appendChild(moveProjectBtn);

  const makeGlobalBtn = document.createElement("button");
  makeGlobalBtn.textContent = "Make Global";
  makeGlobalBtn.addEventListener("click", async () => {
    await bulkMoveManagedFiles({
      label: "Make Global",
      scope_type: "global",
      scope_id: null,
      scope_uuid: null,
    });
  });
  actions.appendChild(makeGlobalBtn);

  const deleteBtn = document.createElement("button");
  deleteBtn.className = "filesDeleteBtn";
  deleteBtn.textContent = "Delete Selected";
  deleteBtn.addEventListener("click", async () => {
    await bulkDeleteManagedFiles();
  });
  actions.appendChild(deleteBtn);

  const selectedCount = Array.from(selectedManageFileIds).length;
  summary.textContent = `${selectedCount} selected • ${allItems.length} visible`;
  return bar;
}

function renderManageFilesItemCard(item, fallbackScopeLabel = "") {
  const card = document.createElement("div");
  card.className = "libraryCard";

  const body = document.createElement("div");
  body.className = "libraryCardBody";
  card.appendChild(body);

  const checkboxWrap = document.createElement("label");
  checkboxWrap.className = "filesCheckboxWrap";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.className = "filesSelectCheckbox";
  checkbox.checked = selectedManageFileIds.has(String(item.id));
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) selectedManageFileIds.add(String(item.id));
    else selectedManageFileIds.delete(String(item.id));
    const bar = filesListEl?.querySelector('.filesBulkBar');
    if (bar) {
      const summary = bar.querySelector('.filesBulkSummary');
      if (summary) {
        const visible = filesListEl.querySelectorAll('.filesSelectCheckbox').length;
        summary.textContent = `${selectedManageFileIds.size} selected • ${visible} visible`;
      }
    }
  });
  checkboxWrap.appendChild(checkbox);
  body.appendChild(checkboxWrap);

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
  const resolvedScopeLabel = resolveCardScopeLabel(item, fallbackScopeLabel);

  if (item.scope_type && item.scope_type !== "global" && resolvedScopeLabel) {
    const scopeSubtitle = document.createElement("div");
    scopeSubtitle.className = "libraryCardSubtitle";
    scopeSubtitle.textContent = `${item.scope_type === "project" ? "Project" : "Conversation"}: ${resolvedScopeLabel}`;
    left.appendChild(scopeSubtitle);
  }

  const right = document.createElement("div");
  right.className = "libraryBadges";
  (item.badges || []).forEach((badge) => {
    const el = document.createElement("span");
    el.className = "libraryBadge";
    el.textContent = badge;
    right.appendChild(el);
  });
  appendAccessBadges(right, item);
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

  const controls = document.createElement("div");
  controls.className = "filesCardControls";

  const descInput = document.createElement("input");
  descInput.className = "filesDescInput";
  descInput.type = "text";
  descInput.placeholder = "Description / what this file is for…";
  descInput.value = item.description || item.subtitle || "";
  descInput.dataset.fileId = item.id;
  descInput.addEventListener("change", () => {
    saveFileDescription(item.id, descInput.value);
  });
  controls.appendChild(descInput);

  const actions = document.createElement("div");
  actions.className = "filesCardActions";

  const renameBtn = document.createElement("button");
  renameBtn.textContent = "Rename";
  renameBtn.addEventListener("click", async () => {
    await renameManagedFile(item);
  });
  actions.appendChild(renameBtn);

  if ((item.badges || []).includes("image")) {
    const describeBtn = document.createElement("button");
    describeBtn.textContent = (item.meta_json && item.meta_json.image_caption) ? "Refresh Summary" : "Describe Image";
    describeBtn.addEventListener("click", async () => {
      await describeManagedImage(item, describeBtn);
    });
    actions.appendChild(describeBtn);

    const ocrBtn = document.createElement("button");
    ocrBtn.textContent = (item.meta_json && item.meta_json.image_ocr_text) ? "Refresh OCR" : "Read Text";
    ocrBtn.addEventListener("click", async () => {
      await ocrManagedImage(item, ocrBtn);
    });
    actions.appendChild(ocrBtn);
  }

  (item.promote_targets || []).filter((target) => String(target?.scope_type || "") !== "project").forEach((target) => {
    const btn = document.createElement("button");
    btn.textContent = target.label || "Move";
    btn.addEventListener("click", async () => {
      await moveFileToScope(item, target);
    });
    actions.appendChild(btn);
  });

  const picker = renderFileProjectPicker(item.scope_type === "project" ? item.scope_id : "");
  actions.appendChild(picker.wrap);

  const moveProjectBtn = document.createElement("button");
  moveProjectBtn.textContent = "Move to Project";
  moveProjectBtn.addEventListener("click", async () => {
    const projectId = String(picker.select.value || "").trim();
    if (!projectId) {
      alert("Choose a target project first.");
      return;
    }
    await moveFileToScope(item, {
      label: "Move to Project",
      scope_type: "project",
      scope_id: Number(projectId),
      scope_uuid: null,
    });
  });
  actions.appendChild(moveProjectBtn);

  const deleteBtn = document.createElement("button");
  deleteBtn.className = "filesDeleteBtn";
  deleteBtn.textContent = "Delete";
  deleteBtn.addEventListener("click", async () => {
    await deleteManagedFile(item);
  });
  actions.appendChild(deleteBtn);

  controls.appendChild(actions);
  content.appendChild(controls);

  return card;
}

function renderManageFilesGroup(group, scopeKey) {
  const wrap = document.createElement("div");
  wrap.className = "libraryGroup";

  const items = Array.isArray(group?.items) ? group.items : [];
  const itemCount = items.length;
  const groupKey = `${scopeKey}:${group?.key || "group"}`;
  const canCollapse = itemCount > FILES_COLLAPSE_THRESHOLD;
  const collapsed = canCollapse ? (filesGroupCollapseState.get(groupKey) ?? true) : false;
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

  const title = document.createElement("div");
  title.className = "libraryGroupTitle";
  title.textContent = group.title || group.key || "Group";
  titleRow.appendChild(title);

  const count = document.createElement("div");
  count.className = "libraryGroupCount";
  count.textContent = `${itemCount} item${itemCount === 1 ? "" : "s"}`;

  header.appendChild(titleRow);
  header.appendChild(count);
  wrap.appendChild(header);

  const cards = document.createElement("div");
  cards.className = "libraryCards";
  const fallbackScopeLabel = String(
    (projectsCache || []).find((p) => Number(p.id) === Number(filesModalProjectId))?.name || ""
  ).trim();
  items.forEach((item) => cards.appendChild(renderManageFilesItemCard(item, fallbackScopeLabel)));
  wrap.appendChild(cards);

  if (canCollapse) {
    header.addEventListener("click", () => {
      const next = !wrap.classList.contains("is-collapsed");
      wrap.classList.toggle("is-collapsed", next);
      filesGroupCollapseState.set(groupKey, next);
      header.setAttribute("aria-expanded", next ? "false" : "true");
      const caret = header.querySelector(".libraryCaret");
      if (caret) caret.textContent = next ? "▸" : "▾";
    });
  }

  return wrap;
}

function renderManageFilesModal(data) {
  if (!filesListEl) return;
  filesListEl.innerHTML = "";
  if (filesTitleEl) filesTitleEl.textContent = data?.title || "Files";
  if (filesScopeNoteEl) filesScopeNoteEl.textContent = data?.note || "";

  const groups = Array.isArray(data?.groups) ? data.groups : [];
  pruneManageFilesSelection(groups);
  if (!groups.length) {
    filesListEl.textContent = "No files yet.";
    return;
  }

  const container = document.createElement("div");
  container.className = "librarySection";
  container.appendChild(renderManageFilesBulkBar(groups));
  const scopeKey = `files:${filesModalMode || "unknown"}:${filesModalConversationId || filesModalProjectId || "root"}`;
  groups.forEach((group) => {
    container.appendChild(renderManageFilesGroup(group, scopeKey));
  });
  filesListEl.appendChild(container);
}

async function loadFilesModal() {
  if (!filesModal || !filesListEl) return;
  hideAllTransientUI({ except: [projMenuEl] });
  await ensureProjectsCacheLoaded();

  let url = null;
  let kind = "flat";

  if (filesModalMode === "conversation") {
    if (!filesModalConversationId) return;
    url = `/api/conversation/${encodeURIComponent(filesModalConversationId)}/library`;
    kind = "library";
  } else if (filesModalMode === "project") {
    if (filesModalProjectId == null) return;
    url = `/api/projects/${encodeURIComponent(filesModalProjectId)}/library`;
    kind = "library";
  } else if (filesModalMode === "global") {
    url = "/api/library/global";
    kind = "library";
  } else if (filesModalMode === "all") {
    url = "/api/files";
    kind = "flat";
  } else {
    return;
  }

  filesListEl.textContent = "Loading…";
  if (filesTitleEl) filesTitleEl.textContent = "Files";
  if (filesScopeNoteEl) filesScopeNoteEl.textContent = "";
  filesModal.classList.remove("hidden");

  try {
    const data = await fetchJsonDebug(url);
    const viewData = kind === "library"
      ? buildManageFilesDataFromLibrary(data || {})
      : buildManageFilesDataFromAll(Array.isArray(data?.files) ? data.files : []);
    renderManageFilesModal(viewData);
  } catch (err) {
    console.error("files list error", err);
    filesListEl.textContent = "Failed to load files.";
  }
}

function closeFilesModal(save = true) {
  if (!filesModal) return;
  if (save) {
    for (const input of filesListEl.querySelectorAll("input.filesDescInput")) {
      const fileId = input.dataset.fileId;
      saveFileDescription(fileId, input.value);
    }
  }
  filesModal.classList.add("hidden");
  filesModalMode = null;
  filesModalConversationId = null;
  filesModalProjectId = null;
  selectedManageFileIds.clear();
}

async function moveFileToGlobal(file) {
  return moveFileToScope(
    {
      id: file.id,
      title: file.name || file.path || file.id,
    },
    {
      label: "Move to Global",
      scope_type: "global",
      scope_id: null,
      scope_uuid: null,
    }
  );
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

function parseManageFileMeta(raw) {
  if (!raw) return {};
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }
  return (typeof raw === "object") ? raw : {};
}
