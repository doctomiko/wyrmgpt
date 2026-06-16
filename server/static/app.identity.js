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
    capabilities: {},
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
      #identitySidePanel { flex: 0 0 auto !important; display: block !important; position: relative; z-index: 5; pointer-events: auto; padding: 10px; border: 1px solid var(--border); border-radius: 12px; background: rgba(12,19,32,0.72); margin-bottom: 0; }
      #rightSidePanel > .rightSideSection:not(#identitySidePanel) { flex: 1 1 auto; min-height: 0; }
      #identitySidePanel select { width: 100%; min-width: 0; }
      .identityManagerGrid { display: grid; grid-template-columns: minmax(0, 340px) minmax(0, 1fr); gap: 16px; }
      .identityManagerCol { border: 1px solid rgba(128,128,128,.25); border-radius: 8px; padding: 10px; }
      .identityManagerCol h3 { margin: 0 0 8px 0; font-size: 1rem; }
      .identityFormStack { display: grid; gap: 6px; margin-bottom: 10px; }
      .identityFormStack input, .identityFormStack select, .identityFormStack textarea { width: 100%; box-sizing: border-box; }
      .identityList { display: grid; gap: 5px; margin-top: 8px; max-height: 56vh; overflow: auto; }
      .identityListItem, .identityEmpty { padding: 6px 8px; border-radius: 6px; background: rgba(128,128,128,.10); font-size: .85rem; }
      .identityListItem { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: start; }
      .identityListLabel { min-width: 0; overflow-wrap: anywhere; }
      .identityListActions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px; }
      .identityMiniButton { padding: 2px 6px; font-size: 0.75rem; line-height: 1.4; }
      .identityMiniButton.danger { opacity: 0.9; }
      .identityScopeNote { font-size: 0.72rem; opacity: 0.7; line-height: 1.25; }
      .identityFormStack button.hidden, .identityTopHidden { display: none !important; }
      @media (max-width: 1100px) { .identityManagerGrid { grid-template-columns: 1fr; } }
    `;
    document.head.appendChild(style);
  }

  function ensureScopedIdentityUi() {
    document.getElementById("identityModal")?.remove();
    const old = $("manageIdentityTop");
    old?.classList.add("identityTopHidden");

    const menuParent = old?.parentElement || document.querySelector("#topMenu, .topMenu, #sidebar") || document.body;
    for (const [id, text] of [["manageTenantsTop", "Manage Tenants…"], ["manageUsersTop", "Manage Users…"], ["managePersonasTop", "Manage Personas…"]]) {
      if (!$(id)) {
        const btn = document.createElement("button");
        btn.id = id;
        btn.textContent = text;
        if (old && old.parentElement) old.insertAdjacentElement("afterend", btn);
        else menuParent.appendChild(btn);
      }
    }

    if (!$("identityTenantModal")) document.body.insertAdjacentHTML("beforeend", tenantModalHtml());
    if (!$("identityUserModal")) document.body.insertAdjacentHTML("beforeend", userModalHtml());
    if (!$("identityPersonaModal")) document.body.insertAdjacentHTML("beforeend", personaModalHtml());
  }

  function tenantModalHtml() {
    return `
      <div id="identityTenantModal" class="modal hidden">
        <div class="modalBackdrop"></div>
        <div class="modalPanel" style="max-width: 900px;">
          <div class="modalHeader"><div class="modalTitle">Manage Tenants</div><button id="identityTenantClose" class="iconButton" title="Close">&times;</button></div>
          <div class="modalBody"><div class="identityManagerGrid">
            <section class="identityManagerCol"><h3>Tenant</h3><div class="identityFormStack">
              <input id="identityTenantName" placeholder="Tenant name" />
              <input id="identityTenantKind" placeholder="kind: local, household, discord_guild…" value="local" />
              <button id="identitySaveTenant">Create Tenant</button>
              <button id="identityCancelTenantEdit" class="hidden">Cancel Update</button>
            </div></section>
            <section class="identityManagerCol"><h3>Existing Tenants</h3><div id="identityTenantList" class="identityList"></div></section>
          </div></div>
          <div class="modalActions"><button id="identityTenantCloseBottom">Close</button></div>
        </div>
      </div>`;
  }

  function userModalHtml() {
    return `
      <div id="identityUserModal" class="modal hidden">
        <div class="modalBackdrop"></div>
        <div class="modalPanel" style="max-width: 980px;">
          <div class="modalHeader"><div class="modalTitle">Manage Users</div><button id="identityUserClose" class="iconButton" title="Close">&times;</button></div>
          <div class="modalBody"><div class="identityManagerGrid">
            <section class="identityManagerCol"><h3>User</h3><div class="identityFormStack">
              <select id="identityUserScope"></select>
              <label class="identityCheckboxRow"><input id="identityUserTenantAdmin" type="checkbox" /> Tenant admin</label>
              <label class="identityCheckboxRow"><input id="identityUserGlobalAdmin" type="checkbox" /> Global admin</label>
              <input id="identityUserName" placeholder="Display name" />
              <input id="identityUserSlug" placeholder="slug / short name" />
              <input id="identityUserEmail" type="email" placeholder="email" />
              <input id="identityUserDiscordId" placeholder="Discord user ID / slug" />
              <label class="identityCheckboxRow"><input id="identityUserPkIdentity" type="checkbox" /> Discord profile is a PK identity</label>
              <button id="identitySaveUser">Create User</button>
              <button id="identityCancelUserEdit" class="hidden">Cancel Update</button>
              <div id="identityUserScopeNote" class="identityScopeNote"></div>
            </div></section>
            <section class="identityManagerCol"><h3>Existing Users</h3><div id="identityUserList" class="identityList"></div></section>
          </div></div>
          <div class="modalActions"><button id="identityUserCloseBottom">Close</button></div>
        </div>
      </div>`;
  }

  function personaModalHtml() {
    return `
      <div id="identityPersonaModal" class="modal hidden">
        <div class="modalBackdrop"></div>
        <div class="modalPanel" style="max-width: 980px;">
          <div class="modalHeader"><div class="modalTitle">Manage Personas</div><button id="identityPersonaClose" class="iconButton" title="Close">&times;</button></div>
          <div class="modalBody"><div class="identityManagerGrid">
            <section class="identityManagerCol"><h3>Persona</h3><div class="identityFormStack">
              <select id="identityPersonaScope"></select>
              <select id="identityPersonaTenant"></select>
              <input id="identityPersonaName" placeholder="Persona name" />
              <input id="identityPersonaSlug" placeholder="slug, e.g. callie" />
              <input id="identityPersonaDescription" placeholder="Short description" />
              <select id="identityPersonaPromptFile"></select>
              <textarea id="identityPersonaPrompt" rows="5" placeholder="Optional custom persona system prompt"></textarea>
              <button id="identitySavePersona">Create Persona</button>
              <button id="identityCancelPersonaEdit" class="hidden">Cancel Update</button>
              <div id="identityPersonaScopeNote" class="identityScopeNote"></div>
            </div></section>
            <section class="identityManagerCol"><h3>Existing Personas</h3><div id="identityPersonaList" class="identityList"></div></section>
          </div></div>
          <div class="modalActions"><button id="identityPersonaCloseBottom">Close</button></div>
        </div>
      </div>`;
  }

  function asInt(value) {
    if (value === null || value === undefined || value === "" || value === GLOBAL_USER_VALUE) return null;
    const n = Number(value);
    return Number.isFinite(n) ? Math.trunc(n) : null;
  }

  function option(label, value) {
    const opt = document.createElement("option");
    opt.textContent = label;
    opt.value = value == null ? "" : String(value);
    return opt;
  }

  function selectedTenantId() { return asInt($("identityTenantSelect")?.value ?? state.selection.tenant_id); }
  function selectedUserId() { return asInt($("identityUserSelect")?.value ?? state.selection.user_id); }
  function selectedPersonaId() { return asInt($("identityPersonaSelect")?.value ?? state.selection.persona_id); }
  function userPool() { return state.allUsers.length ? state.allUsers : state.users; }
  function activeUser() { return userPool().find((u) => Number(u.id) === Number(selectedUserId())); }
  function activeUserIsGlobalAdmin() { return !!state.capabilities?.is_global_admin; }
  function activeUserIsTenantAdmin() { return !!state.capabilities?.is_tenant_admin; }

  function loadStoredSelection() {
    try { const raw = localStorage.getItem(STORE_KEY); return raw ? JSON.parse(raw) || {} : {}; } catch { return {}; }
  }

  function saveSelection() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state.selection || {})); } catch {}
  }

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

  let identityToastTimer = null;
  function showIdentityToast(message, tone = "ok") {
    let toast = $("identityToast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "identityToast";
      document.body.appendChild(toast);
      const style = document.createElement("style");
      style.id = "identityToastStyle";
      style.textContent = `
        #identityToast { position: fixed; right: 18px; bottom: 18px; z-index: 9999; padding: 10px 14px; border-radius: 10px; background: rgba(22, 90, 42, .94); color: #fff; box-shadow: 0 4px 18px rgba(0,0,0,.35); opacity: 0; transform: translateY(8px); transition: opacity .16s ease, transform .16s ease; pointer-events: none; max-width: 360px; }
        #identityToast.visible { opacity: 1; transform: translateY(0); }
        #identityToast.warn { background: rgba(122, 73, 16, .96); }
        #identityToast.error { background: rgba(130, 35, 35, .96); }
      `;
      document.head.appendChild(style);
    }
    toast.textContent = message;
    toast.className = tone;
    requestAnimationFrame(() => toast.classList.add("visible"));
    clearTimeout(identityToastTimer);
    identityToastTimer = setTimeout(() => toast.classList.remove("visible"), 2600);
  }

  function emitIdentityEvent(name, detail = {}) {
    document.dispatchEvent(new CustomEvent(name, { detail }));
  }

  function fillSelect(el, rows, labelFn, { blank = false, blankLabel = "—", blankValue = "" } = {}) {
    if (!el) return;
    const prev = el.value;
    el.innerHTML = "";
    if (blank) el.appendChild(option(blankLabel, blankValue));
    rows.forEach((row) => el.appendChild(option(labelFn(row), row.id ?? row.path ?? row.value)));
    if ([...el.options].some((opt) => opt.value === prev)) el.value = prev;
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
      user?.display_name ? `User: ${user.display_name}${Number(user.is_global_admin || 0) === 1 ? " (global admin)" : Number(user.is_tenant_admin || 0) === 1 ? " (tenant admin)" : Number(user.is_global || 0) === 1 ? " (global)" : ""}` : null,
      persona?.name ? `Persona: ${persona.name}` : null,
    ].filter(Boolean).join(" · ");
  }

  function syncSelectionFromControls() {
    state.selection = activeIdentityPayload();
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state.selection)); } catch {}
    updateBadge();
    updateMenuVisibility();
  }

  function renderSelectors() {
    const tenants = state.tenants.filter((t) => t.is_enabled !== 0);
    fillSelect($("identityTenantSelect"), tenants, (t) => t.name || `Tenant ${t.id}`);
    if ($("identityTenantSelect") && state.selection.tenant_id != null) $("identityTenantSelect").value = String(state.selection.tenant_id);
    if ($("identityTenantSelect") && !$("identityTenantSelect").value && tenants[0]) $("identityTenantSelect").value = String(tenants[0].id);

    const tenantId = selectedTenantId();
    const users = usersForTenant(tenantId).filter((u) => u.is_enabled !== 0);
    fillSelect($("identityUserSelect"), users, (u) => `${u.display_name || u.slug || u.handle || `User ${u.id}`}${Number(u.is_global_admin || 0) === 1 ? " · global admin" : Number(u.is_tenant_admin || 0) === 1 ? " · tenant admin" : Number(u.is_global || 0) === 1 ? " · global" : ""}`);
    if ($("identityUserSelect") && state.selection.user_id != null) $("identityUserSelect").value = String(state.selection.user_id);
    if ($("identityUserSelect") && !$("identityUserSelect").value && users[0]) $("identityUserSelect").value = String(users[0].id);

    const personas = personasForTenant(tenantId);
    fillSelect($("identityPersonaSelect"), personas, (p) => `${p.name}${p.persona_scope ? ` · ${p.persona_scope}` : ""}${p.tenant_name ? ` · ${p.tenant_name}` : ""}`);
    if ($("identityPersonaSelect") && state.selection.persona_id != null) $("identityPersonaSelect").value = String(state.selection.persona_id);
    if ($("identityPersonaSelect") && !$("identityPersonaSelect").value && personas[0]) $("identityPersonaSelect").value = String(personas[0].id);
    syncSelectionFromControls();
  }

  async function putJson(url, payload) { return await fetchJsonDebug(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}) }); }
  async function postJson(url, payload) { return await fetchJsonDebug(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}) }); }
  async function deleteJson(url, payload) { return await fetchJsonDebug(url, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload || {}) }); }

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
      if (row.id != null) item.dataset.rowId = String(row.id);
      if (id === "identityUserList" && row.id != null) item.dataset.userId = String(row.id);
      if (id === "identityPersonaList" && row.id != null) item.dataset.personaId = String(row.id);
      if (id === "identityTenantList" && row.id != null) item.dataset.tenantId = String(row.id);
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

  function updateMenuVisibility() {
    const caps = state.capabilities || {};
    $("manageTenantsTop")?.classList.toggle("identityTopHidden", !caps.can_manage_tenants);
    $("manageUsersTop")?.classList.toggle("identityTopHidden", !caps.can_manage_users);
    $("managePersonasTop")?.classList.toggle("identityTopHidden", false);
  }

  async function loadIdentity() {
    const stored = loadStoredSelection();
    const base = await fetchJsonDebug("/api/identity/bootstrap");
    const defaults = base.defaults || {};
    state.selection = {
      tenant_id: state.selection.tenant_id ?? asInt(stored.tenant_id ?? defaults.tenant_id),
      user_id: state.selection.user_id ?? asInt(stored.user_id ?? defaults.user_id),
      persona_id: state.selection.persona_id ?? asInt(stored.persona_id ?? defaults.persona_id),
      persona_slug: state.selection.persona_slug ?? stored.persona_slug ?? null,
    };
    const qs = new URLSearchParams();
    if (state.selection.tenant_id != null) qs.set("tenant_id", String(state.selection.tenant_id));
    if (state.selection.user_id != null) qs.set("user_id", String(state.selection.user_id));
    const scoped = await fetchJsonDebug(`/api/identity/scope/bootstrap?${qs.toString()}`);
    state.tenants = scoped.tenants || [];
    state.users = scoped.users || [];
    state.allUsers = scoped.all_users || scoped.users || [];
    state.personas = scoped.personas || [];
    state.capabilities = scoped.capabilities || {};
    state.promptFiles = base.prompt_files || [];
    renderSelectors();
    renderAllManagers();
  }

  function fillUserScopeSelect(selectedValue = null) {
    const el = $("identityUserScope");
    if (!el) return;
    const prev = selectedValue ?? el.value;
    el.innerHTML = "";
    if (state.capabilities.can_set_user_global) el.appendChild(option("Global User", GLOBAL_USER_VALUE));
    state.tenants.filter((t) => t.is_enabled !== 0).forEach((t) => el.appendChild(option(t.name || `Tenant ${t.id}`, t.id)));
    if ([...el.options].some((opt) => opt.value === String(prev))) el.value = String(prev);
    else if (selectedTenantId() != null) el.value = String(selectedTenantId());
    else if (el.options.length) el.value = el.options[0].value;
    updateUserAdminCheckboxes();
  }

  function userScopeIsGlobal() { return $("identityUserScope")?.value === GLOBAL_USER_VALUE; }

  function updateUserAdminCheckboxes() {
    const tenantAdmin = $("identityUserTenantAdmin");
    const globalAdmin = $("identityUserGlobalAdmin");
    if (tenantAdmin) {
      tenantAdmin.disabled = !state.capabilities.can_set_user_tenant_admin || userScopeIsGlobal();
      if (tenantAdmin.disabled) tenantAdmin.checked = false;
    }
    if (globalAdmin) {
      globalAdmin.disabled = !state.capabilities.can_set_user_global_admin || !userScopeIsGlobal();
      if (globalAdmin.disabled) globalAdmin.checked = false;
    }
  }

  function fillPersonaScopeSelect(selectedValue = "user") {
    const el = $("identityPersonaScope");
    if (!el) return;
    const prev = selectedValue || el.value || "user";
    el.innerHTML = "";
    if (state.capabilities.can_set_persona_user) el.appendChild(option("Private to this user", "user"));
    if (state.capabilities.can_set_persona_tenant) el.appendChild(option("Tenant-wide", "tenant"));
    if (state.capabilities.can_set_persona_global) el.appendChild(option("Global across all tenants", "global"));
    if ([...el.options].some((opt) => opt.value === String(prev))) el.value = String(prev);
    else if (el.options.length) el.value = el.options[0].value;
    updatePersonaScopeControls();
  }

  function updatePersonaScopeControls() {
    const scope = $("identityPersonaScope")?.value || "user";
    const tenant = $("identityPersonaTenant");
    if (tenant) tenant.disabled = scope === "global";
    const note = $("identityPersonaScopeNote");
    if (note) {
      note.textContent = scope === "global"
        ? "Global personas are visible across all tenants and require global admin."
        : scope === "tenant"
          ? "Tenant-wide personas are available to the selected tenant and require tenant/global admin."
          : "Private personas are available only to the selected user.";
    }
  }

  function fillPromptFileSelect(selectedValue = CUSTOM_PROMPT_VALUE) {
    const el = $("identityPersonaPromptFile");
    if (!el) return;
    el.innerHTML = "";
    el.appendChild(option("Provide Custom Prompt", CUSTOM_PROMPT_VALUE));
    (state.promptFiles || []).forEach((p) => el.appendChild(option(p.name || p.path, p.path)));
    el.value = selectedValue || CUSTOM_PROMPT_VALUE;
    updatePromptTextareaState();
  }

  function updatePromptTextareaState() {
    const choice = $("identityPersonaPromptFile")?.value || CUSTOM_PROMPT_VALUE;
    const textarea = $("identityPersonaPrompt");
    if (!textarea) return;
    const custom = choice === CUSTOM_PROMPT_VALUE;
    textarea.disabled = !custom;
    textarea.placeholder = custom ? "Optional custom persona system prompt" : "Using selected prompt file from ./prompts";
    if (!custom) textarea.value = "";
  }

  function renderAllManagers() {
    renderTenants();
    renderUsers();
    renderPersonas();
    updateMenuVisibility();
  }

  function renderTenants() {
    renderList("identityTenantList", state.tenants, (t) => `${t.name || `Tenant ${t.id}`} · ${t.kind || "local"}${t.is_enabled === 0 ? " · disabled" : ""}${t.reference_count ? ` · refs=${t.reference_count}` : ""}`, { edit: editTenant, toggle: toggleTenant, delete: hardDeleteTenant });
    $("identitySaveTenant") && ($("identitySaveTenant").textContent = state.editingTenantId ? "Update Tenant" : "Create Tenant");
    $("identityCancelTenantEdit")?.classList.toggle("hidden", !state.editingTenantId);
  }

  function renderUsers() {
    fillUserScopeSelect($("identityUserScope")?.value || (selectedTenantId() != null ? String(selectedTenantId()) : GLOBAL_USER_VALUE));
    renderList("identityUserList", usersForTenant(selectedTenantId()), (u) => {
      const scope = Number(u.is_global_admin || 0) === 1 ? "global admin" : Number(u.is_tenant_admin || 0) === 1 ? "tenant admin" : Number(u.is_global || 0) === 1 ? "global" : (u.tenant_name || `tenant ${u.tenant_id || "?"}`);
      return `${u.display_name || `User ${u.id}`} · ${u.slug || u.handle || "user"}${u.email ? ` · ${u.email}` : ""}${u.discord_user_id ? ` · Discord: ${u.discord_user_id}` : ""}${Number(u.is_pk_identity || 0) === 1 ? " · PK identity" : ""} · ${scope}${u.is_enabled === 0 ? " · disabled" : ""}${u.reference_count ? ` · refs=${u.reference_count}` : ""}`;
    }, { edit: editUser, toggle: toggleUser, delete: hardDeleteUser });
    $("identitySaveUser") && ($("identitySaveUser").textContent = state.editingUserId ? "Update User" : "Create User");
    $("identityCancelUserEdit")?.classList.toggle("hidden", !state.editingUserId);
  }

  function renderPersonas() {
    fillSelect($("identityPersonaTenant"), state.tenants.filter((t) => t.is_enabled !== 0), (t) => t.name || `Tenant ${t.id}`, { blank: true, blankLabel: "No tenant / global", blankValue: "" });
    if ($("identityPersonaTenant") && selectedTenantId() != null && !$("identityPersonaTenant").value) $("identityPersonaTenant").value = String(selectedTenantId());
    fillPersonaScopeSelect($("identityPersonaScope")?.value || "user");
    fillPromptFileSelect($("identityPersonaPromptFile")?.value || CUSTOM_PROMPT_VALUE);
    renderList("identityPersonaList", state.personas, (p) => `${p.name || `Persona ${p.id}`} · ${p.slug || "persona"} · ${p.persona_scope || "tenant"}${p.tenant_name ? ` · ${p.tenant_name}` : ""}${p.prompt_file ? ` · ${p.prompt_file}` : ""}${p.is_enabled === 0 ? " · disabled" : ""}${p.reference_count ? ` · refs=${p.reference_count}` : ""}`, { edit: editPersona, toggle: togglePersona, delete: hardDeletePersona });
    $("identitySavePersona") && ($("identitySavePersona").textContent = state.editingPersonaId ? "Update Persona" : "Create Persona");
    $("identityCancelPersonaEdit")?.classList.toggle("hidden", !state.editingPersonaId);
  }

  function openModal(id) {
    const modal = $(id);
    if (!modal) return;
    if (typeof hideAllTransientUI === "function") hideAllTransientUI({ except: [modal] });
    modal.classList.remove("hidden");
    safeCloseTopMenu();
  }
  function closeModal(id) { $(id)?.classList.add("hidden"); }

  function buildTenantPayload() { return { name: ($("identityTenantName")?.value || "").trim(), kind: ($("identityTenantKind")?.value || "local").trim() || "local", acting_user_id: selectedUserId() }; }
  async function saveTenant() {
    const p = buildTenantPayload();
    if (!p.name) return alert("Tenant name required.");
    const wasEdit = !!state.editingTenantId;
    const row = wasEdit
      ? await putJson(`/api/identity/scope/tenants/${encodeURIComponent(state.editingTenantId)}`, p)
      : await postJson("/api/identity/scope/tenants", p);
    resetTenantForm();
    await loadIdentity();
    showIdentityToast(`Tenant ${wasEdit ? "updated" : "created"}: ${row?.name || p.name}`);
  }
  function editTenant(row) { state.editingTenantId = row.id; if ($("identityTenantName")) $("identityTenantName").value = row.name || ""; if ($("identityTenantKind")) $("identityTenantKind").value = row.kind || "local"; renderTenants(); }
  function resetTenantForm() { state.editingTenantId = null; if ($("identityTenantName")) $("identityTenantName").value = ""; if ($("identityTenantKind")) $("identityTenantKind").value = "local"; renderTenants(); }
  async function toggleTenant(row) { const next = row.is_enabled === 0; if (!next && !confirm(`Disable tenant “${row.name || row.id}”?`)) return; await putJson(`/api/identity/scope/tenants/${encodeURIComponent(row.id)}`, { is_enabled: next, acting_user_id: selectedUserId() }); await loadIdentity(); }
  async function hardDeleteTenant(row) { if (!confirm(`Permanently delete tenant “${row.name || row.id}”? This cannot be undone.`)) return; await deleteJson(`/api/identity/scope/tenants/${encodeURIComponent(row.id)}`, { acting_user_id: selectedUserId() }); if (Number(state.editingTenantId) === Number(row.id)) resetTenantForm(); await loadIdentity(); }

  function buildUserPayload() {
    const scope = $("identityUserScope")?.value || "";
    const isGlobal = scope === GLOBAL_USER_VALUE;
    return {
      display_name: ($("identityUserName")?.value || "").trim(),
      slug: ($("identityUserSlug")?.value || "").trim(),
      email: ($("identityUserEmail")?.value || "").trim(),
      discord_user_id: ($("identityUserDiscordId")?.value || "").trim() || ($("identityUserSlug")?.value || "").trim(),
      is_pk_identity: !!$("identityUserPkIdentity")?.checked,
      acting_user_id: selectedUserId(),
      is_global: isGlobal,
      is_global_admin: isGlobal && !!$("identityUserGlobalAdmin")?.checked,
      is_tenant_admin: !isGlobal && !!$("identityUserTenantAdmin")?.checked,
      tenant_id: isGlobal ? null : asInt(scope),
      role: isGlobal && !!$("identityUserGlobalAdmin")?.checked ? "global_admin" : !isGlobal && !!$("identityUserTenantAdmin")?.checked ? "tenant_admin" : "member",
    };
  }
  async function saveUser() {
    const p = buildUserPayload();
    if (!p.display_name) return alert("User display name required.");
    const wasEdit = !!state.editingUserId;
    const row = wasEdit
      ? await putJson(`/api/identity/scope/users/${encodeURIComponent(state.editingUserId)}`, p)
      : await postJson("/api/identity/scope/users", p);
    resetUserForm();
    await loadIdentity();
    showIdentityToast(`User ${wasEdit ? "updated" : "created"}: ${row?.display_name || p.display_name}`);
  }
  function editUser(row) {
    state.editingUserId = row.id;
    if ($("identityUserName")) $("identityUserName").value = row.display_name || "";
    if ($("identityUserSlug")) $("identityUserSlug").value = row.slug || row.handle || "";
    if ($("identityUserEmail")) $("identityUserEmail").value = row.email || "";
    if ($("identityUserDiscordId")) $("identityUserDiscordId").value = row.discord_user_id || row.slug || row.handle || "";
    if ($("identityUserPkIdentity")) $("identityUserPkIdentity").checked = Number(row.is_pk_identity || 0) === 1;
    fillUserScopeSelect(Number(row.is_global || 0) === 1 || Number(row.is_global_admin || 0) === 1 ? GLOBAL_USER_VALUE : String(row.tenant_id || selectedTenantId() || ""));
    if ($("identityUserTenantAdmin")) $("identityUserTenantAdmin").checked = Number(row.is_tenant_admin || 0) === 1;
    if ($("identityUserGlobalAdmin")) $("identityUserGlobalAdmin").checked = Number(row.is_global_admin || 0) === 1;
    updateUserAdminCheckboxes();
    renderUsers();
    emitIdentityEvent("wyrmgpt:identity-user-edit", { user: row, userId: row.id });
  }
  function resetUserForm() {
    state.editingUserId = null;
    fillUserScopeSelect(selectedTenantId() != null ? String(selectedTenantId()) : GLOBAL_USER_VALUE);
    if ($("identityUserTenantAdmin")) $("identityUserTenantAdmin").checked = false;
    if ($("identityUserGlobalAdmin")) $("identityUserGlobalAdmin").checked = false;
    if ($("identityUserName")) $("identityUserName").value = "";
    if ($("identityUserSlug")) $("identityUserSlug").value = "";
    if ($("identityUserEmail")) $("identityUserEmail").value = "";
    if ($("identityUserDiscordId")) $("identityUserDiscordId").value = "";
    if ($("identityUserPkIdentity")) $("identityUserPkIdentity").checked = false;
    renderUsers();
    emitIdentityEvent("wyrmgpt:identity-user-reset");
  }
  async function toggleUser(row) { const next = row.is_enabled === 0; if (!next && !confirm(`Disable user “${row.display_name || row.id}”?`)) return; await putJson(`/api/identity/scope/users/${encodeURIComponent(row.id)}`, { is_enabled: next, acting_user_id: selectedUserId(), tenant_id: row.tenant_id }); await loadIdentity(); }
  async function hardDeleteUser(row) { if (!confirm(`Permanently delete user “${row.display_name || row.id}”? This cannot be undone.`)) return; await deleteJson(`/api/identity/scope/users/${encodeURIComponent(row.id)}`, { acting_user_id: selectedUserId(), tenant_id: row.tenant_id }); if (Number(state.editingUserId) === Number(row.id)) resetUserForm(); await loadIdentity(); }

  function buildPersonaPayload() {
    const promptChoice = $("identityPersonaPromptFile")?.value || CUSTOM_PROMPT_VALUE;
    const custom = promptChoice === CUSTOM_PROMPT_VALUE;
    const scope = $("identityPersonaScope")?.value || "user";
    return {
      acting_user_id: selectedUserId(),
      persona_scope: scope,
      tenant_id: scope === "global" ? null : asInt($("identityPersonaTenant")?.value || selectedTenantId()),
      name: ($("identityPersonaName")?.value || "").trim(),
      slug: ($("identityPersonaSlug")?.value || "").trim(),
      description: ($("identityPersonaDescription")?.value || "").trim(),
      prompt_file: custom ? null : promptChoice,
      system_prompt: custom ? ($("identityPersonaPrompt")?.value || "").trim() : "",
    };
  }
  async function savePersona() {
    const p = buildPersonaPayload();
    if (!p.name) return alert("Persona name required.");
    const wasEdit = !!state.editingPersonaId;
    const row = wasEdit
      ? await putJson(`/api/identity/scope/personas/${encodeURIComponent(state.editingPersonaId)}`, p)
      : await postJson("/api/identity/scope/personas", p);
    resetPersonaForm();
    await loadIdentity();
    showIdentityToast(`Persona ${wasEdit ? "updated" : "created"}: ${row?.name || p.name}`);
  }
  function editPersona(row) { state.editingPersonaId = row.id; fillPersonaScopeSelect(row.persona_scope || "tenant"); if ($("identityPersonaTenant")) $("identityPersonaTenant").value = row.tenant_id == null ? "" : String(row.tenant_id); if ($("identityPersonaName")) $("identityPersonaName").value = row.name || ""; if ($("identityPersonaSlug")) $("identityPersonaSlug").value = row.slug || ""; if ($("identityPersonaDescription")) $("identityPersonaDescription").value = row.description || ""; if (row.prompt_file) fillPromptFileSelect(row.prompt_file); else { fillPromptFileSelect(CUSTOM_PROMPT_VALUE); if ($("identityPersonaPrompt")) $("identityPersonaPrompt").value = row.system_prompt || ""; } renderPersonas(); }
  function resetPersonaForm() { state.editingPersonaId = null; fillPersonaScopeSelect("user"); if ($("identityPersonaTenant") && selectedTenantId() != null) $("identityPersonaTenant").value = String(selectedTenantId()); if ($("identityPersonaName")) $("identityPersonaName").value = ""; if ($("identityPersonaSlug")) $("identityPersonaSlug").value = ""; if ($("identityPersonaDescription")) $("identityPersonaDescription").value = ""; if ($("identityPersonaPrompt")) $("identityPersonaPrompt").value = ""; fillPromptFileSelect(CUSTOM_PROMPT_VALUE); renderPersonas(); }
  async function togglePersona(row) { const next = row.is_enabled === 0; if (!next && !confirm(`Disable persona “${row.name || row.id}”?`)) return; await putJson(`/api/identity/scope/personas/${encodeURIComponent(row.id)}`, { is_enabled: next, acting_user_id: selectedUserId(), tenant_id: row.tenant_id, persona_scope: row.persona_scope || "tenant" }); await loadIdentity(); }
  async function hardDeletePersona(row) { if (!confirm(`Permanently delete persona “${row.name || row.id}”? This cannot be undone.`)) return; await deleteJson(`/api/identity/scope/personas/${encodeURIComponent(row.id)}`, { acting_user_id: selectedUserId() }); if (Number(state.editingPersonaId) === Number(row.id)) resetPersonaForm(); await loadIdentity(); }

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
      } catch (e) { console.warn("identity fetch patch skipped", e); }
      return originalFetch(input, init);
    };
    window.__wyrmgptIdentityFetchPatched = true;
  }

  function bind() {
    ensureScopedIdentityUi();
    $("identityTenantSelect")?.addEventListener("change", () => { state.selection.tenant_id = selectedTenantId(); state.selection.user_id = null; state.selection.persona_id = null; loadIdentity().then(safeRefreshContext).catch(console.error); });
    $("identityUserSelect")?.addEventListener("change", () => { state.selection.user_id = selectedUserId(); state.selection.persona_id = null; loadIdentity().then(safeRefreshContext).catch(console.error); });
    $("identityPersonaSelect")?.addEventListener("change", () => { syncSelectionFromControls(); safeRefreshContext(); });
    $("manageTenantsTop")?.addEventListener("click", () => { renderTenants(); openModal("identityTenantModal"); });
    $("manageUsersTop")?.addEventListener("click", () => { renderUsers(); openModal("identityUserModal"); });
    $("managePersonasTop")?.addEventListener("click", () => { renderPersonas(); openModal("identityPersonaModal"); });
    for (const [id, modal] of [["identityTenantClose", "identityTenantModal"], ["identityTenantCloseBottom", "identityTenantModal"], ["identityUserClose", "identityUserModal"], ["identityUserCloseBottom", "identityUserModal"], ["identityPersonaClose", "identityPersonaModal"], ["identityPersonaCloseBottom", "identityPersonaModal"]]) $(id)?.addEventListener("click", () => closeModal(modal));
    for (const id of ["identityTenantModal", "identityUserModal", "identityPersonaModal"]) $(id)?.querySelector(".modalBackdrop")?.addEventListener("click", () => closeModal(id));
    $("identitySaveTenant")?.addEventListener("click", () => saveTenant().catch((e) => showIdentityToast(`Failed to save tenant: ${e?.message || e}`, "error")));
    $("identityCancelTenantEdit")?.addEventListener("click", resetTenantForm);
    $("identitySaveUser")?.addEventListener("click", () => saveUser().catch((e) => showIdentityToast(`Failed to save user: ${e?.message || e}`, "error")));
    $("identityCancelUserEdit")?.addEventListener("click", resetUserForm);
    $("identityUserScope")?.addEventListener("change", updateUserAdminCheckboxes);
    $("identitySavePersona")?.addEventListener("click", () => savePersona().catch((e) => showIdentityToast(`Failed to save persona: ${e?.message || e}`, "error")));
    $("identityCancelPersonaEdit")?.addEventListener("click", resetPersonaForm);
    $("identityPersonaScope")?.addEventListener("change", updatePersonaScopeControls);
    $("identityPersonaPromptFile")?.addEventListener("change", updatePromptTextareaState);
  }

  window.wyrmgptIdentityToast = showIdentityToast;
  window.wyrmgptIdentity = { state, loadIdentity, activeIdentityPayload, openIdentityModal: () => openModal("identityPersonaModal"), showToast: showIdentityToast };
  installIdentityRuntimeStyle();
  bind();
  installFetchPatch();
  loadIdentity().catch((e) => console.error("identity boot failed", e));
})();
