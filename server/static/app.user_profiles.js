// ----------------------------------
// User-scoped About You profile helpers
// ----------------------------------

(function () {
  const $ = (id) => document.getElementById(id);
  let managedAboutUserId = null;

  function identityState() {
    return window.wyrmgptIdentity?.state || {};
  }

  function activeIdentity() {
    try {
      return window.wyrmgptIdentity?.activeIdentityPayload?.() || {};
    } catch {
      return {};
    }
  }

  function activeUser() {
    const state = identityState();
    const identity = activeIdentity();
    const pool = state.allUsers?.length ? state.allUsers : state.users || [];
    return pool.find((u) => Number(u.id) === Number(identity.user_id));
  }

  function currentEditingUserId() {
    return identityState().editingUserId || null;
  }

  function userPool() {
    const state = identityState();
    return state.allUsers?.length ? state.allUsers : state.users || [];
  }

  function selectedTenantId() {
    return activeIdentity().tenant_id;
  }

  function usersForCurrentTenant() {
    const tenantId = selectedTenantId();
    return userPool().filter((u) => {
      if (Number(u.is_global || 0) === 1 || Number(u.is_global_admin || 0) === 1) return true;
      if (tenantId == null) return false;
      return Number(u.tenant_id) === Number(tenantId);
    });
  }

  function userScopeLabel(u) {
    if (Number(u.is_global_admin || 0) === 1) return "global admin";
    if (Number(u.is_tenant_admin || 0) === 1) return "tenant admin";
    if (Number(u.is_global || 0) === 1) return "global";
    return u.tenant_name || `tenant ${u.tenant_id || "?"}`;
  }

  function userListLabel(u) {
    return `${u.display_name || `User ${u.id}`} · ${u.slug || u.handle || "user"} · ${userScopeLabel(u)}${u.is_enabled === 0 ? " · disabled" : ""}${u.reference_count ? ` · refs=${u.reference_count}` : ""}`;
  }

  function identifyClickedUserFromEditButton(button) {
    const row = button?.closest?.("#identityUserList .identityListItem");
    if (!row) return null;
    const label = row.querySelector(".identityListLabel")?.textContent || "";
    const byLabel = usersForCurrentTenant().find((u) => userListLabel(u) === label);
    if (byLabel) return byLabel;

    const items = [...document.querySelectorAll("#identityUserList .identityListItem")];
    const idx = items.indexOf(row);
    const rows = usersForCurrentTenant();
    if (idx >= 0 && idx < rows.length) return rows[idx];
    return null;
  }

  function updateAboutYouTitle(user) {
    const section = document.getElementById("aboutYouNickname")?.closest(".memSection");
    if (!section) return;
    const title = section.querySelector(".memTitle");
    if (title) title.textContent = `About You — ${user?.display_name || "selected user"}`;
    let note = document.getElementById("aboutYouAppliesTo");
    if (!note) {
      note = document.createElement("div");
      note.id = "aboutYouAppliesTo";
      note.className = "memHint";
      title?.insertAdjacentElement("afterend", note);
    }
    note.textContent = user
      ? `These profile details apply to active user ${user.display_name || user.slug || user.id}.`
      : "These profile details apply to the currently selected active user.";
  }

  async function fetchUserAboutYou(userId, actingUserId) {
    if (!userId) {
      return { nickname: "", age: "", occupation: "", more_about_you: "", text: "" };
    }
    const qs = new URLSearchParams();
    if (actingUserId) qs.set("acting_user_id", String(actingUserId));
    return await fetchJsonDebug(`/api/user_profiles/${encodeURIComponent(userId)}/about_you?${qs.toString()}`);
  }

  async function saveUserAboutYou(userId, actingUserId, payload) {
    return await fetchJsonDebug(`/api/user_profiles/${encodeURIComponent(userId)}/about_you`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...(payload || {}), acting_user_id: actingUserId || userId }),
    });
  }

  // Override the legacy global About You functions used by app.manage.js.
  window.fetchAboutYou = async function fetchAboutYouForActiveUser() {
    const ident = activeIdentity();
    const user = activeUser();
    updateAboutYouTitle(user);
    return await fetchUserAboutYou(ident.user_id, ident.user_id);
  };

  window.saveAboutYou = async function saveAboutYouForActiveUser() {
    const ident = activeIdentity();
    if (!ident.user_id) {
      alert("Pick an active user before saving About You.");
      return;
    }
    const payload = readPersonalizationAboutFields();
    await saveUserAboutYou(ident.user_id, ident.user_id, payload);
    if (typeof window.loadPersonalization === "function") await window.loadPersonalization();
    if (typeof window.refreshContext === "function") await window.refreshContext();
  };

  function readPersonalizationAboutFields() {
    return {
      nickname: ($("aboutYouNickname")?.value || "").trim(),
      age: ($("aboutYouAge")?.value || "").trim(),
      occupation: ($("aboutYouOccupation")?.value || "").trim(),
      more_about_you: ($("aboutYouMore")?.value || "").trim(),
    };
  }

  function readManagedAboutFields() {
    return {
      nickname: ($("identityAboutNickname")?.value || "").trim(),
      age: ($("identityAboutAge")?.value || "").trim(),
      occupation: ($("identityAboutOccupation")?.value || "").trim(),
      more_about_you: ($("identityAboutMore")?.value || "").trim(),
    };
  }

  function hasAnyAboutFields(payload) {
    return !!(payload?.nickname || payload?.age || payload?.occupation || payload?.more_about_you);
  }

  function clearManagedAboutFields() {
    managedAboutUserId = null;
    if ($("identityAboutNickname")) $("identityAboutNickname").value = "";
    if ($("identityAboutAge")) $("identityAboutAge").value = "";
    if ($("identityAboutOccupation")) $("identityAboutOccupation").value = "";
    if ($("identityAboutMore")) $("identityAboutMore").value = "";
    updateManagedAboutNote(null);
  }

  function updateManagedAboutNote(user) {
    const note = $("identityAboutNote");
    if (!note) return;
    if (user) {
      note.textContent = `Editing About You for ${user.display_name || user.slug || user.id}.`;
    } else {
      note.textContent = "For a new user, these fields will be saved after the user record is created.";
    }
  }

  function ensureManageUserAboutPanel() {
    const modal = $("identityUserModal");
    if (!modal || $("identityManageUserAboutPanel")) return;
    const bodyGrid = modal.querySelector(".identityManagerGrid");
    if (!bodyGrid) return;
    const panel = document.createElement("section");
    panel.id = "identityManageUserAboutPanel";
    panel.className = "identityManagerCol";
    panel.innerHTML = `
      <h3>About This User</h3>
      <div class="identityAboutGrid">
        <label>
          Nickname
          <input id="identityAboutNickname" placeholder="Nickname" />
        </label>
        <label>
          Approximate Age
          <input id="identityAboutAge" placeholder="Approximate age" />
        </label>
        <label class="span2">
          Occupation
          <textarea id="identityAboutOccupation" rows="4" placeholder="Occupation"></textarea>
        </label>
        <label class="span2">
          More About This User
          <textarea id="identityAboutMore" rows="8" placeholder="Anything enduring, useful, or identity-shaping about this user."></textarea>
        </label>
        <div class="span2">
          <button id="identitySaveUserBottom">Create User</button>
          <div id="identityAboutNote" class="identityScopeNote"></div>
        </div>
      </div>
    `;
    bodyGrid.appendChild(panel);

    const styleId = "identityAboutUserStyle";
    if (!document.getElementById(styleId)) {
      const style = document.createElement("style");
      style.id = styleId;
      style.textContent = `
        #identityManageUserAboutPanel { grid-column: 1 / -1; }
        .identityAboutGrid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
        .identityAboutGrid label { display: grid; gap: 4px; }
        .identityAboutGrid .span2 { grid-column: 1 / -1; }
        .identityAboutGrid input, .identityAboutGrid textarea { width: 100%; box-sizing: border-box; }
        @media (max-width: 800px) { .identityAboutGrid { grid-template-columns: 1fr; } .identityAboutGrid .span2 { grid-column: auto; } }
      `;
      document.head.appendChild(style);
    }
    $("identitySaveUserBottom")?.addEventListener("click", interceptUserSave, true);
  }

  async function loadManagedAboutForUser(userId) {
    ensureManageUserAboutPanel();
    const actorUserId = activeIdentity().user_id;
    if (!userId) {
      clearManagedAboutFields();
      return;
    }
    managedAboutUserId = Number(userId);
    const data = await fetchUserAboutYou(userId, actorUserId);
    if ($("identityAboutNickname")) $("identityAboutNickname").value = data.nickname || "";
    if ($("identityAboutAge")) $("identityAboutAge").value = data.age || "";
    if ($("identityAboutOccupation")) $("identityAboutOccupation").value = data.occupation || "";
    if ($("identityAboutMore")) $("identityAboutMore").value = data.more_about_you || "";
    const user = userPool().find((u) => Number(u.id) === Number(userId));
    updateManagedAboutNote(user || { id: userId });
  }

  function buildUserPayloadFromForm() {
    const scopeValue = $("identityUserScope")?.value || "";
    const globalValue = "__global__";
    const isGlobal = scopeValue === globalValue;
    const isGlobalAdmin = isGlobal && !!$("identityUserGlobalAdmin")?.checked;
    const isTenantAdmin = !isGlobal && !!$("identityUserTenantAdmin")?.checked;
    return {
      display_name: ($("identityUserName")?.value || "").trim(),
      slug: ($("identityUserSlug")?.value || "").trim(),
      acting_user_id: activeIdentity().user_id,
      is_global: isGlobal,
      is_global_admin: isGlobalAdmin,
      is_tenant_admin: isTenantAdmin,
      tenant_id: isGlobal ? null : Number(scopeValue || activeIdentity().tenant_id || 0) || null,
      role: isGlobalAdmin ? "global_admin" : isTenantAdmin ? "tenant_admin" : "member",
    };
  }

  function setUserSaveButtonLabels() {
    const isEdit = !!currentEditingUserId();
    if ($("identitySaveUserBottom")) $("identitySaveUserBottom").textContent = isEdit ? "Update User" : "Create User";
  }

  function clearUserFormFieldsAfterCreate() {
    if ($("identityUserName")) $("identityUserName").value = "";
    if ($("identityUserSlug")) $("identityUserSlug").value = "";
    if ($("identityUserTenantAdmin")) $("identityUserTenantAdmin").checked = false;
    if ($("identityUserGlobalAdmin")) $("identityUserGlobalAdmin").checked = false;
  }

  async function interceptUserSave(event) {
    event.preventDefault();
    event.stopImmediatePropagation();
    const editingUserId = currentEditingUserId();
    const payload = buildUserPayloadFromForm();
    if (!payload.display_name) {
      alert("User display name required.");
      return;
    }
    const url = editingUserId
      ? `/api/identity/scope/users/${encodeURIComponent(editingUserId)}`
      : "/api/identity/scope/users";
    const method = editingUserId ? "PUT" : "POST";
    const savedUser = await fetchJsonDebug(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const aboutPayload = readManagedAboutFields();
    if (savedUser?.id && hasAnyAboutFields(aboutPayload)) {
      await saveUserAboutYou(savedUser.id, activeIdentity().user_id, aboutPayload);
    }

    if (window.wyrmgptIdentity?.loadIdentity) await window.wyrmgptIdentity.loadIdentity();
    if (!editingUserId) {
      clearUserFormFieldsAfterCreate();
      clearManagedAboutFields();
    }
    setUserSaveButtonLabels();
    if (typeof window.refreshContext === "function") await window.refreshContext();
  }

  function installProfileUiHooks() {
    ensureManageUserAboutPanel();
    $("identitySaveUser")?.addEventListener("click", interceptUserSave, true);
    $("identitySaveUserBottom")?.addEventListener("click", interceptUserSave, true);

    const manageUsers = $("manageUsersTop");
    manageUsers?.addEventListener("click", () => {
      setTimeout(() => {
        setUserSaveButtonLabels();
        if (currentEditingUserId()) loadManagedAboutForUser(currentEditingUserId()).catch(console.warn);
        else clearManagedAboutFields();
      }, 0);
    });

    $("identityCancelUserEdit")?.addEventListener("click", () => {
      setTimeout(() => {
        clearManagedAboutFields();
        setUserSaveButtonLabels();
      }, 0);
    });

    document.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.textContent !== "Edit" || !target.closest("#identityUserList")) return;
      const clickedUser = identifyClickedUserFromEditButton(target);
      if (!clickedUser) return;
      setTimeout(() => {
        setUserSaveButtonLabels();
        loadManagedAboutForUser(clickedUser.id).catch((e) => console.warn("load edited user's About You failed", e));
      }, 0);
    }, true);
  }

  window.wyrmgptUserProfiles = {
    fetchUserAboutYou,
    saveUserAboutYou,
    loadManageUserAbout: loadManagedAboutForUser,
    clearManagedAboutFields,
  };

  installProfileUiHooks();
})();
