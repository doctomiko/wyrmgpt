// ----------------------------------
// Identity management: tenants, users, personas
// ----------------------------------

(function () {
  const STORE_KEY = "wyrmgpt.identity.selection";
  const state = { tenants: [], users: [], allUsers: [], personas: [], selection: {} };
  const $ = (id) => document.getElementById(id);

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

  function renderList(id, rows, labelFn) {
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
      item.textContent = labelFn(row);
      target.appendChild(item);
    });
  }

  function renderManager() {
    renderList("identityTenantList", state.tenants, (t) => `${t.name || `Tenant ${t.id}`} · ${t.kind || "local"}${t.is_enabled === 0 ? " · disabled" : ""}`);
    renderList("identityUserList", state.allUsers.length ? state.allUsers : state.users, (u) => `${u.display_name || `User ${u.id}`}${u.handle ? ` · @${u.handle}` : ""}${u.tenant_role ? ` · ${u.tenant_role}` : ""}${u.is_enabled === 0 ? " · disabled" : ""}`);
    renderList("identityPersonaList", state.personas, (p) => `${p.name || `Persona ${p.id}`} · ${p.slug || "persona"}${p.tenant_name ? ` · ${p.tenant_name}` : " · global"}${p.is_enabled === 0 ? " · disabled" : ""}`);
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
    ["identityNewPersonaName", "identityNewPersonaSlug", "identityNewPersonaDescription", "identityNewPersonaPrompt"].forEach((id) => { if ($(id)) $(id).value = ""; });
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
        if (method === "POST" && (path === "/api/chat" || path === "/api/chat_ab") && init && typeof init.body === "string") {
          const body = JSON.parse(init.body || "{}");
          if (body && typeof body === "object" && !Array.isArray(body)) {
            init = { ...init, body: JSON.stringify({ ...activeIdentityPayload(), ...body }) };
          }
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
  bind();
  installFetchPatch();
  loadIdentity().catch((e) => console.error("identity boot failed", e));
})();
