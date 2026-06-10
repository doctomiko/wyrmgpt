// ----------------------------------
// Identity management: tenants, users, personas
// ----------------------------------

(function () {
  const STORE_KEY = "wyrmgpt.identity.selection";
  const state = { tenants: [], users: [], allUsers: [], personas: [], selection: {} };
  const $ = (id) => document.getElementById(id);

  function installIdentityRuntimeStyle() {
    if (document.getElementById("identityRuntimeStyle")) return;
    const style = document.createElement("style");
    style.id = "identityRuntimeStyle";
    style.textContent = `
      #rightSidePanel {
        display: flex;
        flex-direction: column;
        gap: 10px;
        overflow: hidden;
      }
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
      #rightSidePanel > .rightSideSection:not(#identitySidePanel) {
        flex: 1 1 auto;
        min-height: 0;
      }
      #identitySidePanel select {
        width: 100%;
        min-width: 0;
      }
      .identityListItem {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 8px;
        align-items: start;
      }
      .identityListLabel {
        min-width: 0;
        overflow-wrap: anywhere;
      }
      .identityListActions {
        display: flex;
        flex-wrap: wrap;
        justify-content: flex-end;
        gap: 4px;
      }
      .identityMiniButton {
        padding: 2px 6px;
        font-size: 0.75rem;
        line-height: 1.4;
      }
    `;
    document.head.appendChild(style);
  }

  function asInt(value) {
    if (value === null || value === undefined || value === "") return null;
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

  function fillSelect(el, rows, labelFn, { blank = false, blankLabel = "—" } = {}) {
    if (!el) return;
    const prev = el.value;
    el.innerHTML = "";
    if (blank) el.appendChild(option(blankLabel, ""));
    rows.forEach((row) => el.appendChild(option(labelFn(row), row.id)));
    if ([...el.options].some((opt) => opt.value === prev)) el.value = prev;
  }

  function selectedTenantId() { return asInt($("identityTenantSelect")?.value ?? state.selection.tenant_id); }
  function selectedUserId() { return asInt($("identityUserSelect")?.value ?? state.selection.user_id); }
  function selectedPersonaId() { return asInt($("identityPersonaSelect")?.value ?? state.selection.persona_id); }

  function usersForTenant(tenantId) {
    const scoped = tenantId == null ? [] : state.users.filter((u) => Number(u.tenant_id || tenantId) === Number(tenantId));
    return scoped.length ? scoped : (state.allUsers.length ? state.allUsers : state.users);
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
    const userPool = state.allUsers.length ? state.allUsers : state.users;
    const user = userPool.find((u) => Number(u.id) === Number(selectedUserId()));
    const persona = state.personas.find((p) => Number(p.id) === Number(selectedPersonaId()));
    badge.textContent = [
      tenant?.name ? `Tenant: ${tenant.name}` : null,
      user?.display_name ? `User: ${user.display_name}` : null,
      persona?.name ? `Persona: ${persona.name}` : null,
    ].filter(Boolean).join(" · ");
  }

  function syncSelectionFromControls() {
    state.selection = activeIdentityPayload();
    saveSelection();
    updateBadge();
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
    fillSelect(userSelect, users, (u) => u.display_name || u.handle || `User ${u.id}`);
    if (userSelect && state.selection.user_id != null) userSelect.value = String(state.selection.user_id);
    if (userSelect && !userSelect.value && users[0]) userSelect.value = String(users[0].id);

    const personas = personasForTenant(tenantId);
    fillSelect(personaSelect, personas, (p) => p.tenant_name ? `${p.name} · ${p.tenant_name}` : p.name);
    if (personaSelect && state.selection.persona_id != null) personaSelect.value = String(state.selection.persona_id);
    if (personaSelect && !personaSelect.value && personas[0]) personaSelect.value = String(personas[0].id);
    syncSelectionFromControls();
  }

  async function putJson(url, payload) {
    return await fetchJsonDebug(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
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
      item.appendChild(actionWrap);
      target.appendChild(item);
    });
  }

  function renderManager() {
    renderList(
      "identityTenantList",
      state.tenants,
      (t) => `${t.name || `Tenant ${t.id}`} · ${t.kind || "local"}${t.is_enabled === 0 ? " · disabled" : ""}`,
      { edit: editTenant, toggle: toggleTenant }
    );
    renderList(
      "identityUserList",
      state.allUsers.length ? state.allUsers : state.users,
      (u) => `${u.display_name || `User ${u.id}`}${u.handle ? ` · @${u.handle}` : ""}${u.tenant_role ? ` · ${u.tenant_role}` : ""}${u.is_enabled === 0 ? " · disabled" : ""}`,
      { edit: editUser, toggle: toggleUser }
    );
    renderList(
      "identityPersonaList",
      state.personas,
      (p) => `${p.name || `Persona ${p.id}`} · ${p.slug || "persona"}${p.tenant_name ? ` · ${p.tenant_name}` : " · global"}${p.is_enabled === 0 ? " · disabled" : ""}`,
      { edit: editPersona, toggle: togglePersona }
    );
    fillSelect($("identityNewUserTenant"), state.tenants.filter((t) => t.is_enabled !== 0), (t) => t.name || `Tenant ${t.id}`);
    fillSelect($("identityNewPersonaTenant"), state.tenants.filter((t) => t.is_enabled !== 0), (t) => t.name || `Tenant ${t.id}`, { blank: true, blankLabel: "Global persona" });
    if ($("identityNewUserTenant") && selectedTenantId() != null) $("identityNewUserTenant").value = String(selectedTenantId());
    if ($("identityNewPersonaTenant") && selectedTenantId() != null) $("identityNewPersonaTenant").value = String(selectedTenantId());
  }

  async function loadIdentity() {
    const stored = loadStoredSelection();
    const data = await fetchJsonDebug("/api/identity/bootstrap");
    state.tenants = data.tenants || [];
    state.users = data.users || [];
    state.allUsers = data.all_users || data.users || [];
    state.personas = data.personas || [];
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

  async function createTenant() {
    const name = ($("identityNewTenantName")?.value || "").trim();
    const kind = ($("identityNewTenantKind")?.value || "local").trim();
    if (!name) return alert("Tenant name required.");
    await fetchJsonDebug("/api/tenants", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, kind }) });
    $("identityNewTenantName").value = "";
    await loadIdentity();
  }

  async function createUser() {
    const display_name = ($("identityNewUserName")?.value || "").trim();
    const handle = ($("identityNewUserHandle")?.value || "").trim();
    const tenant_id = asInt($("identityNewUserTenant")?.value);
    if (!display_name) return alert("User display name required.");
    await fetchJsonDebug("/api/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ display_name, handle, tenant_id }) });
    $("identityNewUserName").value = "";
    $("identityNewUserHandle").value = "";
    await loadIdentity();
  }

  async function createPersona() {
    const name = ($("identityNewPersonaName")?.value || "").trim();
    const slug = ($("identityNewPersonaSlug")?.value || "").trim();
    const tenant_id = asInt($("identityNewPersonaTenant")?.value);
    const description = ($("identityNewPersonaDescription")?.value || "").trim();
    const system_prompt = ($("identityNewPersonaPrompt")?.value || "").trim();
    if (!name) return alert("Persona name required.");
    await fetchJsonDebug("/api/personas", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, slug, tenant_id, description, system_prompt }) });
    ["identityNewPersonaName", "identityNewPersonaSlug", "identityNewPersonaDescription", "identityNewPersonaPrompt"].forEach((fieldId) => { if ($(fieldId)) $(fieldId).value = ""; });
    await loadIdentity();
  }

  async function editTenant(row) {
    const name = prompt("Tenant name:", row.name || "");
    if (name === null) return;
    const kind = prompt("Tenant kind:", row.kind || "local");
    if (kind === null) return;
    await putJson(`/api/tenants/${encodeURIComponent(row.id)}`, { name: name.trim(), kind: kind.trim() || "local" });
    await loadIdentity();
  }

  async function toggleTenant(row) {
    const next = row.is_enabled === 0;
    if (!next && !confirm(`Disable tenant “${row.name || row.id}”? Existing messages will keep their identity history.`)) return;
    await putJson(`/api/tenants/${encodeURIComponent(row.id)}`, { is_enabled: next });
    await loadIdentity();
  }

  async function editUser(row) {
    const display_name = prompt("User display name:", row.display_name || "");
    if (display_name === null) return;
    const handle = prompt("User handle:", row.handle || "");
    if (handle === null) return;
    await putJson(`/api/users/${encodeURIComponent(row.id)}`, { display_name: display_name.trim(), handle: handle.trim() });
    await loadIdentity();
  }

  async function toggleUser(row) {
    const next = row.is_enabled === 0;
    if (!next && !confirm(`Disable user “${row.display_name || row.id}”? Existing messages will keep their identity history.`)) return;
    await putJson(`/api/users/${encodeURIComponent(row.id)}`, { is_enabled: next });
    await loadIdentity();
  }

  async function editPersona(row) {
    const name = prompt("Persona name:", row.name || "");
    if (name === null) return;
    const slug = prompt("Persona slug:", row.slug || "");
    if (slug === null) return;
    const description = prompt("Persona description:", row.description || "");
    if (description === null) return;
    const system_prompt = prompt("Persona system prompt:", row.system_prompt || "");
    if (system_prompt === null) return;
    await putJson(`/api/personas/${encodeURIComponent(row.id)}`, {
      name: name.trim(),
      slug: slug.trim(),
      description: description.trim(),
      system_prompt: system_prompt.trim(),
    });
    await loadIdentity();
  }

  async function togglePersona(row) {
    const next = row.is_enabled === 0;
    if (!next && !confirm(`Disable persona “${row.name || row.id}”? Existing messages will keep their persona history.`)) return;
    await putJson(`/api/personas/${encodeURIComponent(row.id)}`, { is_enabled: next });
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
    $("identityTenantSelect")?.addEventListener("change", () => { state.selection.tenant_id = selectedTenantId(); state.selection.user_id = null; state.selection.persona_id = null; renderSelectors(); refreshContext?.().catch?.(() => {}); });
    $("identityUserSelect")?.addEventListener("change", () => { syncSelectionFromControls(); refreshContext?.().catch?.(() => {}); });
    $("identityPersonaSelect")?.addEventListener("change", () => { syncSelectionFromControls(); refreshContext?.().catch?.(() => {}); });
    $("manageIdentityTop")?.addEventListener("click", () => { openIdentityModal(); toggleTopMenu?.(false); });
    $("identityClose")?.addEventListener("click", closeIdentityModal);
    $("identityCloseBottom")?.addEventListener("click", closeIdentityModal);
    $("identityModal")?.querySelector(".modalBackdrop")?.addEventListener("click", closeIdentityModal);
    $("identityCreateTenant")?.addEventListener("click", () => createTenant().catch((e) => alert(`Failed to create tenant: ${e?.message || e}`)));
    $("identityCreateUser")?.addEventListener("click", () => createUser().catch((e) => alert(`Failed to create user: ${e?.message || e}`)));
    $("identityCreatePersona")?.addEventListener("click", () => createPersona().catch((e) => alert(`Failed to create persona: ${e?.message || e}`)));
  }

  window.wyrmgptIdentity = { state, loadIdentity, activeIdentityPayload, openIdentityModal };
  installIdentityRuntimeStyle();
  bind();
  installFetchPatch();
  loadIdentity().catch((e) => console.error("identity boot failed", e));
})();
