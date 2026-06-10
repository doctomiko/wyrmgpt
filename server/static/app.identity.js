// ----------------------------------
// Identity management: tenants, users, personas
// ----------------------------------

(function () {
  const STORE_KEY = "wyrmgpt.identity.selection";
  const CUSTOM_PROMPT_VALUE = "__custom__";
  const GLOBAL_USER_VALUE = "__global__";
  const state = {
    tenants: [],
    users: [],
    allUsers: [],
    personas: [],
    promptFiles: [],
    selection: {},
    editingTenantId: null,
    editingUserId: null,
    editingPersonaId: null,
  };
  const $ = (id) => document.getElementById(id);

  function installIdentityRuntimeStyle() {
    if (document.getElementById("identityRuntimeStyle")) return;
    const style = document.createElement("style");
    style.id = "identityRuntimeStyle";
    style.textContent = `
      #rightSidePanel { display: flex; flex-direction: column; gap: 10px; overflow: hidden; }
      #identitySidePanel {
        flex: 0 0 auto !important;
        display: block !important;
        position: relative;
        z-index: 5;
        pointer-events: auto;
        padding: 10px;
        border: 1px solid var(--border);
        border-radius: 12px;
        background: rgba(12,19,32,0.72);
        margin-bottom: 0;
      }
      #rightSidePanel > .rightSideSection:not(#identitySidePanel) { flex: 1 1 auto; min-height: 0; }
      #identitySidePanel select { width: 100%; min-width: 0; }
      .identityListItem { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: start; }
      .identityListLabel { min-width: 0; overflow-wrap: anywhere; }
      .identityListActions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px; }
      .identityMiniButton { padding: 2px 6px; font-size: 0.75rem; line-height: 1.4; }
      .identityMiniButton.danger { opacity: 0.9; }
      .identityScopeNote { font-size: 0.72rem; opacity: 0.7; line-height: 1.25; }
      .identityFormStack button.hidden { display: none; }
    `;
    document.head.appendChild(style);
  }

  function asInt(value) {
    if (value === null || value === undefined || value === "" || value === GLOBAL_USER_VALUE) return null;
    const n = Number(value);
    return Number.isFinite(n) ? Math.trunc(n) : null;
  }

  function loadStoredSelection() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      return raw ? JSON.parse(raw) || {} : {};
    } catch {
      return {};
    }
  }

  function saveSelection() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state.selection || {})); } catch {}
  }

  function option(label, value) {
    const opt = document.createElement("option");
    opt.textContent = label;
    opt.value = value == null ? "" : String(value);
    return opt;
  }

  function fillSelect(el, rows, labelFn, { blank = false, blankLabel = "—", blankValue = "" } = {}) {
    if (!el) return;
    const prev = el.value;
    el.innerHTML = "";
    if (blank) el.appendChild(option(blankLabel, blankValue));
    rows.forEach((row) => el.appendChild(option(labelFn(row), row.id ?? row.path ?? row.value)));
    if ([...el.options].some((opt) => opt.value === prev)) el.value = prev;
  }

  function selectedTenantId() { return asInt($("identityTenantSelect")?.value ?? state.selection.tenant_id); }
  function selectedUserId() { return asInt($("identityUserSelect")?.value ?? state.selection.user_id); }
  function selectedPersonaId() { return asInt($("identityPersonaSelect")?.value ?? state.selection.persona_id); }
  function userPool() { return state.allUsers.length ? state.allUsers : state.users; }
  function activeUser() { return userPool().find((u) => Number(u.id) === Number(selectedUserId())); }
  function activeUserIsGlobalAdmin() { return Number(activeUser()?.is_global_admin || 0) === 1; }

  function safeRefreshContext() {
    try {
      if (typeof window.refreshContext === "function") window.refreshContext().catch?.(() => {});
      else if (typeof refreshContext === "function") refreshContext().catch?.(() => {});
    } catch {}
  }

  function safeCloseTopMenu() {
    try {
      if (typeof window.toggleTopMenu === "function") window.toggleTopMenu(false);
      else if (typeof toggleTopMenu === "function") toggleTopMenu(false);
    } catch {}
  }

  function usersForTenant(tenantId) {
    return userPool().filter((u) => {
      if (Number(u.is_global || 0) === 1 || Number(u.is_global_admin || 0) === 1) return true;
      if (tenantId == null) return false;
      return Number(u.tenant_id) === Number(tenantId);
    });
  }

  function personasForTenant(tenantId) {
    return state.personas.filter((p) => p.is_enabled !== 0 && (p.tenant_id == null || tenantId == null || Number(p.tenant_id) === Number(tenantId)));
  }

  function activeIdentityPayload() {
    const tenant_id = selectedTenantId();
    const user_id = selectedUserId();
    const persona_id = selectedPersonaId();
    const persona = state.personas.find((p) => Number(p.id) === Number(persona_id));
    return { tenant_id, user_id, persona_id, persona_slug: persona?.slug || null };
  }

  function updateBadge() {
    const badge = $("identityBadge");
    if (!badge) return;
    const tenant = state.tenants.find((t) => Number(t.id) === Number(selectedTenantId()));
    const user = userPool().find((u) => Number(u.id) === Number(selectedUserId()));
    const persona = state.personas.find((p) => Number(p.id) === Number(selectedPersonaId()));
    badge.textContent = [
      tenant?.name ? `Tenant: ${tenant.name}` : null,
      user?.display_name ? `User: ${user.display_name}${Number(user.is_global_admin || 0) === 1 ? " (global admin)" : Number(user.is_global || 0) === 1 ? " (global)" : ""}` : null,
      persona?.name ? `Persona: ${persona.name}` : null,
    ].filter(Boolean).join(" · ");
  }

  function syncSelectionFromControls() {
    state.selection = activeIdentityPayload();
    saveSelection();
    updateBadge();
    renderManagerButtons();
  }

  function renderSelectors() {
    const tenantSelect = $("identityTenantSelect");
    const userSelect = $("identityUserSelect");
    const personaSelect = $("identityPersonaSelect");
    const tenants = state.tenants.filter((t) => t.is_enabled !== 0);
    fillSelect(tenantSelect, tenants, (t) => t.name || `Tenant ${t.id}`);
    if (tenantSelect && state.selection.tenant_id != null) tenantSelect.value = String(state.selection.tenant_id);
    if (tenantSelect && !tenantSelect.value && tenants[0]) tenantSelect.value = String(tenants[0].id);

    const tenantId = selectedTenantId();
    const users = usersForTenant(tenantId).filter((u) => u.is_enabled !== 0);
    fillSelect(userSelect, users, (u) => {
      const scope = Number(u.is_global_admin || 0) === 1 ? " · global admin" : Number(u.is_global || 0) === 1 ? " · global" : "";
      return `${u.display_name || u.slug || u.handle || `User ${u.id}`}${scope}`;
    });
    if (userSelect && state.selection.user_id != null) userSelect.value = String(state.selection.user_id);
    if (userSelect && !userSelect.value && users[0]) userSelect.value = String(users[0].id);

    const personas = personasForTenant(tenantId);
    fillSelect(personaSelect, personas, (p) => p.tenant_name ? `${p.name} · ${p.tenant_name}` : `${p.name} · global`);
    if (personaSelect && state.selection.persona_id != null) personaSelect.value = String(state.selection.persona_id);
    if (personaSelect && !personaSelect.value && personas[0]) personaSelect.value = String(personas[0].id);
    syncSelectionFromControls();
  }

  async function putJson(url, payload) {
    return await fetchJsonDebug(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}) });
  }

  async function postJson(url, payload) {
    return await fetchJsonDebug(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}) });
  }

  async function deleteJson(url, payload) {
    return await fetchJsonDebug(url, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}) });
  }

  function renderList(id, rows, labelFn, actions = {}) {
    const target = $(id);
    if (!target) return;
    target.innerHTML = "";
    if (!rows.length) {
      const empty = document.createElement("div");
      empty.className = "identityEmpty";
      empty.textContent = "Nothing here yet.";
      target.appendChild(empty);
      return;
    }
    rows.forEach((row) => {
      const item = document.createElement("div");
      item.className = "identityListItem";
      const label = document.createElement("div");
      label.className = "identityListLabel";
      label.textContent = labelFn(row);
      item.appendChild(label);
      const actionWrap = document.createElement("div");
      actionWrap.className = "identityListActions";
      if (actions.edit) {
        const edit = document.createElement("button");
        edit.className = "identityMiniButton";
        edit.textContent = "Edit";
        edit.addEventListener("click", () => actions.edit(row));
        actionWrap.appendChild(edit);
      }
      if (actions.toggle) {
        const toggle = document.createElement("button");
        toggle.className = "identityMiniButton";
        toggle.textContent = row.is_enabled === 0 ? "Enable" : "Disable";
        toggle.addEventListener("click", () => actions.toggle(row));
        actionWrap.appendChild(toggle);
      }
      if (actions.delete && row.can_delete) {
        const del = document.createElement("button");
        del.className = "identityMiniButton danger";
        del.textContent = "Hard Delete";
        del.addEventListener("click", () => actions.delete(row));
        actionWrap.appendChild(del);
      }
      item.appendChild(actionWrap);
      target.appendChild(item);
    });
  }

  function fillUserScopeSelect(selectedValue = null) {
    const el = $("identityNewUserTenant");
    if (!el) return;
    const prev = selectedValue ?? el.value;
    el.innerHTML = "";
    el.appendChild(option("Global User", GLOBAL_USER_VALUE));
    state.tenants.filter((t) => t.is_enabled !== 0).forEach((t) => el.appendChild(option(t.name || `Tenant ${t.id}`, t.id)));
    if ([...el.options].some((opt) => opt.value === String(prev))) el.value = String(prev);
    else if (selectedTenantId() != null) el.value = String(selectedTenantId());
    else el.value = GLOBAL_USER_VALUE;
    updateUserGlobalAdminState();
  }

  function userScopeIsGlobal() {
    return $("identityNewUserTenant")?.value === GLOBAL_USER_VALUE;
  }

  function updateUserGlobalAdminState() {
    const adminBox = $("identityNewUserGlobalAdmin");
    if (!adminBox) return;
    const allowed = activeUserIsGlobalAdmin() && userScopeIsGlobal();
    adminBox.disabled = !allowed;
    if (!allowed) adminBox.checked = false;
  }

  function fillPromptFileSelect(selectedValue = CUSTOM_PROMPT_VALUE) {
    const el = $("identityNewPersonaPromptFile");
    if (!el) return;
    el.innerHTML = "";
    el.appendChild(option("Provide Custom Prompt", CUSTOM_PROMPT_VALUE));
    (state.promptFiles || []).forEach((p) => el.appendChild(option(p.name || p.path, p.path)));
    el.value = selectedValue || CUSTOM_PROMPT_VALUE;
    updatePromptTextareaState();
  }

  function updatePromptTextareaState() {
    const choice = $("identityNewPersonaPromptFile")?.value || CUSTOM_PROMPT_VALUE;
    const textarea = $("identityNewPersonaPrompt");
    if (!textarea) return;
    const custom = choice === CUSTOM_PROMPT_VALUE;
    textarea.disabled = !custom;
    textarea.placeholder = custom ? "Optional custom persona system prompt" : "Using selected prompt file from ./prompts";
    if (!custom) textarea.value = "";
  }

  function resetTenantForm() {
    state.editingTenantId = null;
    if ($("identityNewTenantName")) $("identityNewTenantName").value = "";
    if ($("identityNewTenantKind")) $("identityNewTenantKind").value = "local";
    renderManagerButtons();
  }

  function resetUserForm() {
    state.editingUserId = null;
    fillUserScopeSelect(selectedTenantId() != null ? String(selectedTenantId()) : GLOBAL_USER_VALUE);
    if ($("identityNewUserGlobalAdmin")) $("identityNewUserGlobalAdmin").checked = false;
    if ($("identityNewUserName")) $("identityNewUserName").value = "";
    if ($("identityNewUserSlug")) $("identityNewUserSlug").value = "";
    renderManagerButtons();
  }

  function resetPersonaForm() {
    state.editingPersonaId = null;
    if ($("identityNewPersonaTenant") && selectedTenantId() != null) $("identityNewPersonaTenant").value = String(selectedTenantId());
    if ($("identityNewPersonaName")) $("identityNewPersonaName").value = "";
    if ($("identityNewPersonaSlug")) $("identityNewPersonaSlug").value = "";
    if ($("identityNewPersonaDescription")) $("identityNewPersonaDescription").value = "";
    if ($("identityNewPersonaPrompt")) $("identityNewPersonaPrompt").value = "";
    fillPromptFileSelect(CUSTOM_PROMPT_VALUE);
    renderManagerButtons();
  }

  function renderManagerButtons() {
    const isAdmin = activeUserIsGlobalAdmin();
    if ($("identityCreateTenant")) $("identityCreateTenant").textContent = state.editingTenantId ? "Update Tenant" : "Create Tenant";
    if ($("identityCancelTenantEdit")) $("identityCancelTenantEdit").classList.toggle("hidden", !state.editingTenantId);
    if ($("identityCreateUser")) $("identityCreateUser").textContent = state.editingUserId ? "Update User" : "Create User";
    if ($("identityCancelUserEdit")) $("identityCancelUserEdit").classList.toggle("hidden", !state.editingUserId);
    if ($("identityCreatePersona")) $("identityCreatePersona").textContent = state.editingPersonaId ? "Update Persona" : "Create Persona";
    if ($("identityCancelPersonaEdit")) $("identityCancelPersonaEdit").classList.toggle("hidden", !state.editingPersonaId);

    const scopeSelect = $("identityNewUserTenant");
    if (scopeSelect) scopeSelect.disabled = !isAdmin;
    updateUserGlobalAdminState();

    let note = $("identityUserScopeNote");
    if (!note && $("identityNewUserTenant")?.parentElement) {
      note = document.createElement("div");
      note.id = "identityUserScopeNote";
      note.className = "identityScopeNote";
      $("identityNewUserTenant").parentElement.appendChild(note);
    }
    if (note) note.textContent = isAdmin ? "Global admin mode: user tenant/global/admin status may be changed." : "User scope controls are locked unless the selected user is a global admin.";
  }

  function renderManager() {
    const tenantId = selectedTenantId();
    renderList(
      "identityTenantList",
      state.tenants,
      (t) => `${t.name || `Tenant ${t.id}`} · ${t.kind || "local"}${t.is_enabled === 0 ? " · disabled" : ""}${t.reference_count ? ` · refs=${t.reference_count}` : ""}`,
      { edit: editTenant, toggle: toggleTenant, delete: hardDeleteTenant }
    );
    renderList(
      "identityUserList",
      usersForTenant(tenantId),
      (u) => {
        const scope = Number(u.is_global_admin || 0) === 1 ? "global admin" : Number(u.is_global || 0) === 1 ? "global" : (u.tenant_name || `tenant ${u.tenant_id || "?"}`);
        return `${u.display_name || `User ${u.id}`} · ${u.slug || u.handle || "user"} · ${scope}${u.is_enabled === 0 ? " · disabled" : ""}${u.reference_count ? ` · refs=${u.reference_count}` : ""}`;
      },
      { edit: editUser, toggle: toggleUser, delete: hardDeleteUser }
    );
    renderList(
      "identityPersonaList",
      state.personas,
      (p) => `${p.name || `Persona ${p.id}`} · ${p.slug || "persona"}${p.tenant_name ? ` · ${p.tenant_name}` : " · global"}${p.prompt_file ? ` · ${p.prompt_file}` : ""}${p.is_enabled === 0 ? " · disabled" : ""}${p.reference_count ? ` · refs=${p.reference_count}` : ""}`,
      { edit: editPersona, toggle: togglePersona, delete: hardDeletePersona }
    );
    fillUserScopeSelect($("identityNewUserTenant")?.value || (selectedTenantId() != null ? String(selectedTenantId()) : GLOBAL_USER_VALUE));
    fillSelect($("identityNewPersonaTenant"), state.tenants.filter((t) => t.is_enabled !== 0), (t) => t.name || `Tenant ${t.id}`, { blank: true, blankLabel: "Global persona" });
    fillPromptFileSelect($("identityNewPersonaPromptFile")?.value || CUSTOM_PROMPT_VALUE);
    if (!state.editingPersonaId && $("identityNewPersonaTenant") && selectedTenantId() != null) $("identityNewPersonaTenant").value = String(selectedTenantId());
    renderManagerButtons();
  }

  async function loadIdentity() {
    const stored = loadStoredSelection();
    const data = await fetchJsonDebug("/api/identity/bootstrap");
    state.tenants = data.tenants || [];
    state.users = data.users || [];
    state.allUsers = data.all_users || data.users || [];
    state.personas = data.personas || [];
    state.promptFiles = data.prompt_files || [];
    state.selection = {
      tenant_id: asInt(stored.tenant_id ?? data.defaults?.tenant_id),
      user_id: asInt(stored.user_id ?? data.defaults?.user_id),
      persona_id: asInt(stored.persona_id ?? data.defaults?.persona_id),
      persona_slug: stored.persona_slug || null,
    };
    renderSelectors();
    renderManager();
  }

  function openIdentityModal() {
    const modal = $("identityModal");
    if (!modal) return;
    if (typeof hideAllTransientUI === "function") hideAllTransientUI({ except: [modal] });
    modal.classList.remove("hidden");
    renderManager();
  }

  function closeIdentityModal() { $("identityModal")?.classList.add("hidden"); }

  function buildTenantPayload() {
    return {
      name: ($("identityNewTenantName")?.value || "").trim(),
      kind: ($("identityNewTenantKind")?.value || "local").trim() || "local",
    };
  }

  async function saveTenant() {
    const payload = buildTenantPayload();
    if (!payload.name) return alert("Tenant name required.");
    if (state.editingTenantId) await putJson(`/api/tenants/${encodeURIComponent(state.editingTenantId)}`, payload);
    else await postJson("/api/tenants", payload);
    resetTenantForm();
    await loadIdentity();
  }

  function editTenant(row) {
    state.editingTenantId = row.id;
    if ($("identityNewTenantName")) $("identityNewTenantName").value = row.name || "";
    if ($("identityNewTenantKind")) $("identityNewTenantKind").value = row.kind || "local";
    renderManagerButtons();
  }

  async function toggleTenant(row) {
    const next = row.is_enabled === 0;
    if (!next && !confirm(`Disable tenant “${row.name || row.id}”? Existing messages will keep their identity history.`)) return;
    await putJson(`/api/tenants/${encodeURIComponent(row.id)}`, { is_enabled: next });
    await loadIdentity();
  }

  function buildUserPayload() {
    const isAdmin = activeUserIsGlobalAdmin();
    const scopeValue = $("identityNewUserTenant")?.value || "";
    const scopeIsGlobal = scopeValue === GLOBAL_USER_VALUE;
    const payload = {
      display_name: ($("identityNewUserName")?.value || "").trim(),
      slug: ($("identityNewUserSlug")?.value || "").trim(),
      acting_user_id: selectedUserId(),
    };
    if (isAdmin) {
      payload.is_global = scopeIsGlobal;
      payload.is_global_admin = scopeIsGlobal && !!$("identityNewUserGlobalAdmin")?.checked;
      payload.tenant_id = scopeIsGlobal ? null : asInt(scopeValue);
      payload.role = payload.is_global_admin ? "global_admin" : "member";
    } else if (!state.editingUserId) {
      payload.is_global_admin = false;
      payload.is_global = false;
      payload.tenant_id = selectedTenantId();
      payload.role = "member";
    }
    return payload;
  }

  async function saveUser() {
    const payload = buildUserPayload();
    if (!payload.display_name) return alert("User display name required.");
    if (state.editingUserId) await putJson(`/api/users/${encodeURIComponent(state.editingUserId)}`, payload);
    else await postJson("/api/users", payload);
    resetUserForm();
    await loadIdentity();
  }

  function editUser(row) {
    state.editingUserId = row.id;
    if ($("identityNewUserName")) $("identityNewUserName").value = row.display_name || "";
    if ($("identityNewUserSlug")) $("identityNewUserSlug").value = row.slug || row.handle || "";
    fillUserScopeSelect(Number(row.is_global || 0) === 1 || Number(row.is_global_admin || 0) === 1 ? GLOBAL_USER_VALUE : String(row.tenant_id || selectedTenantId() || ""));
    if ($("identityNewUserGlobalAdmin")) $("identityNewUserGlobalAdmin").checked = Number(row.is_global_admin || 0) === 1;
    updateUserGlobalAdminState();
    renderManagerButtons();
  }

  async function toggleUser(row) {
    const next = row.is_enabled === 0;
    if (!next && !confirm(`Disable user “${row.display_name || row.id}”? Existing messages will keep their identity history.`)) return;
    await putJson(`/api/users/${encodeURIComponent(row.id)}`, { is_enabled: next, acting_user_id: selectedUserId() });
    await loadIdentity();
  }

  function buildPersonaPayload() {
    const promptChoice = $("identityNewPersonaPromptFile")?.value || CUSTOM_PROMPT_VALUE;
    const custom = promptChoice === CUSTOM_PROMPT_VALUE;
    return {
      tenant_id: asInt($("identityNewPersonaTenant")?.value),
      name: ($("identityNewPersonaName")?.value || "").trim(),
      slug: ($("identityNewPersonaSlug")?.value || "").trim(),
      description: ($("identityNewPersonaDescription")?.value || "").trim(),
      prompt_file: custom ? null : promptChoice,
      system_prompt: custom ? ($("identityNewPersonaPrompt")?.value || "").trim() : "",
    };
  }

  async function savePersona() {
    const payload = buildPersonaPayload();
    if (!payload.name) return alert("Persona name required.");
    if (state.editingPersonaId) await putJson(`/api/personas/${encodeURIComponent(state.editingPersonaId)}`, payload);
    else await postJson("/api/personas", payload);
    resetPersonaForm();
    await loadIdentity();
  }

  function editPersona(row) {
    state.editingPersonaId = row.id;
    if ($("identityNewPersonaTenant")) $("identityNewPersonaTenant").value = row.tenant_id == null ? "" : String(row.tenant_id);
    if ($("identityNewPersonaName")) $("identityNewPersonaName").value = row.name || "";
    if ($("identityNewPersonaSlug")) $("identityNewPersonaSlug").value = row.slug || "";
    if ($("identityNewPersonaDescription")) $("identityNewPersonaDescription").value = row.description || "";
    if (row.prompt_file) {
      fillPromptFileSelect(row.prompt_file);
    } else {
      fillPromptFileSelect(CUSTOM_PROMPT_VALUE);
      if ($("identityNewPersonaPrompt")) $("identityNewPersonaPrompt").value = row.system_prompt || "";
    }
    renderManagerButtons();
  }

  async function togglePersona(row) {
    const next = row.is_enabled === 0;
    if (!next && !confirm(`Disable persona “${row.name || row.id}”? Existing messages will keep their persona history.`)) return;
    await putJson(`/api/personas/${encodeURIComponent(row.id)}`, { is_enabled: next });
    await loadIdentity();
  }

  async function hardDeleteTenant(row) {
    if (!confirm(`Permanently delete tenant “${row.name || row.id}”? This cannot be undone.`)) return;
    await deleteJson(`/api/tenants/${encodeURIComponent(row.id)}`, { acting_user_id: selectedUserId() });
    if (Number(state.editingTenantId) === Number(row.id)) resetTenantForm();
    await loadIdentity();
  }

  async function hardDeleteUser(row) {
    if (!confirm(`Permanently delete user “${row.display_name || row.id}”? This cannot be undone.`)) return;
    await deleteJson(`/api/users/${encodeURIComponent(row.id)}`, { acting_user_id: selectedUserId() });
    if (Number(state.editingUserId) === Number(row.id)) resetUserForm();
    await loadIdentity();
  }

  async function hardDeletePersona(row) {
    if (!confirm(`Permanently delete persona “${row.name || row.id}”? This cannot be undone.`)) return;
    await deleteJson(`/api/personas/${encodeURIComponent(row.id)}`, { acting_user_id: selectedUserId() });
    if (Number(state.editingPersonaId) === Number(row.id)) resetPersonaForm();
    await loadIdentity();
  }

  function installFetchPatch() {
    if (window.__wyrmgptIdentityFetchPatched) return;
    const originalFetch = window.fetch.bind(window);
    window.fetch = function patchedFetch(input, init) {
      try {
        const url = typeof input === "string" ? input : input?.url || "";
        const path = new URL(url, window.location.origin).pathname;
        const method = String(init?.method || input?.method || "GET").toUpperCase();
        if (method === "POST" && (path === "/api/chat" || path === "/api/chat_ab") && init) {
          const identity = activeIdentityPayload();
          const headers = new Headers(init.headers || {});
          if (identity.tenant_id != null) headers.set("X-WyrmGPT-Tenant-Id", String(identity.tenant_id));
          if (identity.user_id != null) headers.set("X-WyrmGPT-User-Id", String(identity.user_id));
          if (identity.persona_id != null) headers.set("X-WyrmGPT-Persona-Id", String(identity.persona_id));
          if (identity.persona_slug) headers.set("X-WyrmGPT-Persona-Slug", String(identity.persona_slug));
          if (typeof init.body === "string") {
            const body = JSON.parse(init.body || "{}");
            if (body && typeof body === "object" && !Array.isArray(body)) init.body = JSON.stringify({ ...identity, ...body });
          }
          init = { ...init, headers };
        }
      } catch (e) {
        console.warn("identity fetch patch skipped", e);
      }
      return originalFetch(input, init);
    };
    window.__wyrmgptIdentityFetchPatched = true;
  }

  function bind() {
    $("identityTenantSelect")?.addEventListener("change", () => { state.selection.tenant_id = selectedTenantId(); state.selection.user_id = null; state.selection.persona_id = null; renderSelectors(); renderManager(); safeRefreshContext(); });
    $("identityUserSelect")?.addEventListener("change", () => { syncSelectionFromControls(); renderManager(); safeRefreshContext(); });
    $("identityPersonaSelect")?.addEventListener("change", () => { syncSelectionFromControls(); safeRefreshContext(); });
    $("manageIdentityTop")?.addEventListener("click", () => { openIdentityModal(); safeCloseTopMenu(); });
    $("identityClose")?.addEventListener("click", closeIdentityModal);
    $("identityCloseBottom")?.addEventListener("click", closeIdentityModal);
    $("identityModal")?.querySelector(".modalBackdrop")?.addEventListener("click", closeIdentityModal);
    $("identityCreateTenant")?.addEventListener("click", () => saveTenant().catch((e) => alert(`Failed to save tenant: ${e?.message || e}`)));
    $("identityCancelTenantEdit")?.addEventListener("click", resetTenantForm);
    $("identityCreateUser")?.addEventListener("click", () => saveUser().catch((e) => alert(`Failed to save user: ${e?.message || e}`)));
    $("identityCancelUserEdit")?.addEventListener("click", resetUserForm);
    $("identityCreatePersona")?.addEventListener("click", () => savePersona().catch((e) => alert(`Failed to save persona: ${e?.message || e}`)));
    $("identityCancelPersonaEdit")?.addEventListener("click", resetPersonaForm);
    $("identityNewPersonaPromptFile")?.addEventListener("change", updatePromptTextareaState);
    $("identityNewUserTenant")?.addEventListener("change", updateUserGlobalAdminState);
  }

  window.wyrmgptIdentity = { state, loadIdentity, activeIdentityPayload, openIdentityModal };
  installIdentityRuntimeStyle();
  bind();
  installFetchPatch();
  loadIdentity().catch((e) => console.error("identity boot failed", e));
})();
