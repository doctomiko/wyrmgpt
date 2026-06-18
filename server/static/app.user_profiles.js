// ----------------------------------
// User-scoped About You profile helpers
// ----------------------------------

(function () {
  const $ = (id) => document.getElementById(id);
  let managedAboutUserId = null;
  let managedAboutProfileLoaded = false;
  let managedAboutLoadSeq = 0;
  let managedAvatarObjectUrl = null;
  let userListObserver = null;
  let toastTimer = null;

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
    const identity = activeIdentity();
    return userPool().find((u) => Number(u.id) === Number(identity.user_id));
  }

  function currentEditingUserId() {
    return identityState().editingUserId || managedAboutUserId || null;
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

  function userDisplayName(u) {
    return u?.display_name || u?.slug || u?.handle || (u?.id ? `User ${u.id}` : "New User");
  }

  function userListLabel(u) {
    return `${u.display_name || `User ${u.id}`} · ${u.slug || u.handle || "user"} · ${userScopeLabel(u)}${u.is_enabled === 0 ? " · disabled" : ""}${u.reference_count ? ` · refs=${u.reference_count}` : ""}`;
  }

  function baseLabelText(row) {
    const label = row?.querySelector?.(".identityListLabel");
    if (!label) return "";
    return (label.childNodes[0]?.nodeValue || label.textContent || "").trim();
  }

  function identifyUserFromRow(row) {
    const fromData = Number(row?.dataset?.userId || 0);
    if (fromData) return userPool().find((u) => Number(u.id) === fromData) || null;
    const label = baseLabelText(row);
    const byLabel = usersForCurrentTenant().find((u) => userListLabel(u) === label);
    if (byLabel) return byLabel;
    const items = [...document.querySelectorAll("#identityUserList .identityListItem")];
    const idx = items.indexOf(row);
    const rows = usersForCurrentTenant();
    if (idx >= 0 && idx < rows.length) return rows[idx];
    return null;
  }

  function identifyClickedUserFromEditButton(button) {
    const row = button?.closest?.("#identityUserList .identityListItem");
    return identifyUserFromRow(row);
  }

  function showToast(message, tone = "ok") {
    if (typeof window.wyrmgptIdentityToast === "function") {
      window.wyrmgptIdentityToast(message, tone);
      return;
    }
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
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("visible"), 2600);
  }

  function setUserSaveStatus(message, tone = "ok") {
    const el = $("identityUserStatus");
    if (!el) return;
    el.textContent = message || "";
    el.className = `identityStatus ${tone || "ok"}`;
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
    if (!userId) return { nickname: "", age: "", occupation: "", more_about_you: "", text: "" };
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
    showToast("About You saved.");
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
      discord_user_id: ($("identityUserDiscordId")?.value || "").trim() || ($("identityUserSlug")?.value || "").trim(),
      is_pk_identity: !!$("identityUserPkIdentity")?.checked,
    };
  }

  function hasAnyAboutFields(payload) {
    return !!(payload?.nickname || payload?.age || payload?.occupation || payload?.more_about_you || payload?.discord_user_id || payload?.is_pk_identity);
  }

  function setManagedAboutTitle(user) {
    const title = $("identityAboutTitle");
    if (!title) return;
    title.textContent = `About This User - ${user ? userDisplayName(user) : (($("identityUserName")?.value || "").trim() || "New User")}`;
  }

  function clearManagedAboutFields() {
    managedAboutUserId = null;
    managedAboutProfileLoaded = false;
    managedAboutLoadSeq += 1;
    if ($("identityAboutNickname")) $("identityAboutNickname").value = "";
    if ($("identityAboutAge")) $("identityAboutAge").value = "";
    if ($("identityAboutOccupation")) $("identityAboutOccupation").value = "";
    if ($("identityAboutMore")) $("identityAboutMore").value = "";
    if ($("identityUserDiscordId")) $("identityUserDiscordId").value = "";
    if ($("identityUserPkIdentity")) $("identityUserPkIdentity").checked = false;
    clearManagedAvatarSelection();
    setManagedAvatarPreview(null);
    setManagedAboutTitle(null);
  }

  function clearManagedAvatarSelection() {
    const input = $("identityUserAvatar");
    if (input) input.value = "";
    if (managedAvatarObjectUrl) {
      URL.revokeObjectURL(managedAvatarObjectUrl);
      managedAvatarObjectUrl = null;
    }
  }

  function setManagedAvatarPreview(user) {
    const preview = $("identityUserAvatarPreview");
    const empty = $("identityUserAvatarEmpty");
    if (!preview) return;
    if (managedAvatarObjectUrl) {
      URL.revokeObjectURL(managedAvatarObjectUrl);
      managedAvatarObjectUrl = null;
    }
    const url = user?.avatar_url || "";
    preview.src = url;
    preview.classList.toggle("hidden", !url);
    empty?.classList.toggle("hidden", !!url);
  }

  function previewSelectedAvatar() {
    const input = $("identityUserAvatar");
    const file = input?.files?.[0];
    const preview = $("identityUserAvatarPreview");
    const empty = $("identityUserAvatarEmpty");
    if (!preview || !file) return;
    if (managedAvatarObjectUrl) URL.revokeObjectURL(managedAvatarObjectUrl);
    managedAvatarObjectUrl = URL.createObjectURL(file);
    preview.src = managedAvatarObjectUrl;
    preview.classList.remove("hidden");
    empty?.classList.add("hidden");
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
      <h3 id="identityAboutTitle">About This User - New User</h3>
      <div class="identityAboutGrid">
        <label>
          Nickname
          <input id="identityAboutNickname" placeholder="Nickname" />
        </label>
        <label>
          Approximate Age
          <input id="identityAboutAge" placeholder="Approximate age" />
        </label>
        <label>
          Discord tag or user ID
          <input id="identityUserDiscordId" placeholder="Discord user ID / slug" />
        </label>
        <label class="identityCheckboxRow identityAboutCheckbox">
          <input id="identityUserPkIdentity" type="checkbox" /> Discord profile is a PK identity
        </label>
        <label class="span2">
          Occupation
          <textarea id="identityAboutOccupation" rows="4" placeholder="Occupation"></textarea>
        </label>
        <label class="span2">
          More About This User
          <textarea id="identityAboutMore" rows="8" placeholder="Anything enduring, useful, or identity-shaping about this user."></textarea>
        </label>
        <label class="span2">
          Profile Image
          <input id="identityUserAvatar" type="file" accept="image/jpeg,image/png,image/gif,image/webp,image/*" />
        </label>
        <div class="span2 identityAvatarPreviewRow">
          <img id="identityUserAvatarPreview" class="identityUserAvatarPreview hidden" alt="" />
          <div id="identityUserAvatarEmpty" class="identityUserAvatarEmpty">No profile image</div>
        </div>
        <div class="span2">
          <button id="identitySaveUserBottom">Create User</button>
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
        .identityAboutCheckbox { align-self: end; justify-self: start; display: inline-flex !important; align-items: center; gap: 6px; min-height: 34px; width: auto; }
        .identityAboutGrid .span2 { grid-column: 1 / -1; }
        .identityAboutGrid input, .identityAboutGrid textarea { width: 100%; box-sizing: border-box; }
        .identityAboutGrid .identityAboutCheckbox input { width: auto; }
        .identityAvatarPreviewRow { display: flex; align-items: center; gap: 10px; min-height: 44px; }
        .identityUserAvatarPreview, .identityUserAvatarThumb { width: 36px; height: 36px; border-radius: 50%; object-fit: cover; background: rgba(128,128,128,.18); border: 1px solid rgba(128,128,128,.35); }
        .identityUserAvatarEmpty { font-size: .82rem; opacity: .72; }
        .identityListItem.hasAvatar { grid-template-columns: 36px minmax(0, 1fr) auto; align-items: center; }
        .identityRefDetails { grid-column: 1 / -1; margin-top: 4px; opacity: .82; }
        .identityRefDetails summary { cursor: pointer; }
        .identityRefDetails ul { margin: 4px 0 0 18px; padding: 0; }
        .identityForceDelete { padding: 2px 6px; font-size: .75rem; line-height: 1.4; }
        @media (max-width: 800px) { .identityAboutGrid { grid-template-columns: 1fr; } .identityAboutGrid .span2 { grid-column: auto; } }
      `;
      document.head.appendChild(style);
    }
    $("identitySaveUserBottom")?.addEventListener("click", handleUserSaveClick, true);
    $("identityUserAvatar")?.addEventListener("change", previewSelectedAvatar);
    $("identityUserName")?.addEventListener("input", () => {
      if (!currentEditingUserId()) setManagedAboutTitle(null);
    });
  }

  async function loadManagedAboutForUser(userId) {
    ensureManageUserAboutPanel();
    const actorUserId = activeIdentity().user_id;
    if (!userId) {
      clearManagedAboutFields();
      return;
    }
    const requestSeq = managedAboutLoadSeq + 1;
    managedAboutLoadSeq = requestSeq;
    managedAboutUserId = Number(userId);
    managedAboutProfileLoaded = false;
    const user = userPool().find((u) => Number(u.id) === Number(userId));
    setManagedAboutTitle(user || { id: userId });
    clearManagedAvatarSelection();
    setManagedAvatarPreview(user);
    setUserSaveButtonLabels();
    const data = await fetchUserAboutYou(userId, actorUserId);
    if (requestSeq !== managedAboutLoadSeq || Number(managedAboutUserId) !== Number(userId)) return;
    managedAboutProfileLoaded = !!data.id;
    if ($("identityAboutNickname")) $("identityAboutNickname").value = data.nickname || "";
    if ($("identityAboutAge")) $("identityAboutAge").value = data.age || "";
    if ($("identityAboutOccupation")) $("identityAboutOccupation").value = data.occupation || "";
    if ($("identityAboutMore")) $("identityAboutMore").value = data.more_about_you || "";
    if ($("identityUserDiscordId")) $("identityUserDiscordId").value = data.discord_user_id || user?.discord_user_id || user?.slug || user?.handle || "";
    if ($("identityUserPkIdentity")) $("identityUserPkIdentity").checked = Number(data.is_pk_identity ?? user?.is_pk_identity ?? 0) === 1;
    setManagedAboutTitle(user || { id: userId });
    setUserSaveButtonLabels();
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
      email: ($("identityUserEmail")?.value || "").trim(),
      discord_user_id: ($("identityUserDiscordId")?.value || "").trim() || ($("identityUserSlug")?.value || "").trim(),
      is_pk_identity: !!$("identityUserPkIdentity")?.checked,
      acting_user_id: activeIdentity().user_id,
      is_global: isGlobal,
      is_global_admin: isGlobalAdmin,
      is_tenant_admin: isTenantAdmin,
      tenant_id: isGlobal ? null : Number(scopeValue || activeIdentity().tenant_id || 0) || null,
      role: isGlobalAdmin ? "global_admin" : isTenantAdmin ? "tenant_admin" : "member",
    };
  }

  async function uploadManagedAvatar(userId, actingUserId) {
    const input = $("identityUserAvatar");
    const file = input?.files?.[0];
    if (!userId || !file) return null;
    const form = new FormData();
    form.append("acting_user_id", String(actingUserId || userId));
    form.append("file", file);
    const res = await fetch(`/api/identity/scope/users/${encodeURIComponent(userId)}/avatar`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      let detail = "";
      try {
        const data = await res.json();
        detail = data?.detail || data?.error || "";
      } catch {}
      throw new Error(detail || `Avatar upload failed with HTTP ${res.status}`);
    }
    clearManagedAvatarSelection();
    return await res.json();
  }

  function setUserSaveButtonLabels() {
    const isEdit = !!currentEditingUserId();
    if ($("identitySaveUser")) $("identitySaveUser").textContent = isEdit ? "Update User" : "Create User";
    if ($("identitySaveUserBottom")) $("identitySaveUserBottom").textContent = isEdit ? "Update User" : "Create User";
    $("identityCancelUserEdit")?.classList.toggle("hidden", !isEdit);
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
    setUserSaveStatus(`${editingUserId ? "Updating" : "Creating"} user...`, "warn");
    const url = editingUserId
      ? `/api/identity/scope/users/${encodeURIComponent(editingUserId)}`
      : "/api/identity/scope/users";
    const method = editingUserId ? "PUT" : "POST";
    const savedUser = await fetchJsonDebug(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const savedUserId = savedUser?.id || editingUserId;
    const aboutPayload = readManagedAboutFields();
    if (savedUserId && (hasAnyAboutFields(aboutPayload) || editingUserId || managedAboutProfileLoaded)) {
      await saveUserAboutYou(savedUserId, activeIdentity().user_id, aboutPayload);
    }
    if (savedUserId) {
      await uploadManagedAvatar(savedUserId, activeIdentity().user_id);
    }

    const state = identityState();
    if (savedUserId) {
      state.editingUserId = savedUserId;
      managedAboutUserId = Number(savedUserId);
    }
    if (window.wyrmgptIdentity?.loadIdentity) await window.wyrmgptIdentity.loadIdentity();
    if (savedUserId) await loadManagedAboutForUser(savedUserId);
    setUserSaveButtonLabels();
    setUserSaveStatus(`User ${editingUserId ? "updated" : "created"}: ${savedUser?.display_name || payload.display_name}`, "ok");
    showToast(`User ${editingUserId ? "updated" : "created"}: ${savedUser?.display_name || payload.display_name}`);
    if (typeof window.refreshContext === "function") await window.refreshContext();
  }

  function handleUserSaveClick(event) {
    interceptUserSave(event).catch((e) => {
      setUserSaveStatus(`Failed to save user: ${e?.message || e}`, "error");
      showToast(`Failed to save user: ${e?.message || e}`, "error");
    });
  }

  function effectiveForceAction(ref) {
    if (ref.force_action) return ref.force_action;
    if (ref.table === "tenant_users" && ref.column === "user_id") return "cascade_delete";
    if (ref.table === "user_profiles" && ref.column === "user_id") return "cascade_delete";
    return "assign_global_admin";
  }

  function forceActionLabel(ref) {
    const action = effectiveForceAction(ref);
    if (action === "cascade_delete") return "delete row";
    if (action === "assign_global_admin") return "reassign to @global-admin";
    if (action === "assign_fallback_persona") return "reassign to fallback persona";
    if (action === "clear_tenant_scope") return "clear tenant scope";
    return action || "force-handle";
  }

  function formatRef(ref) {
    return `${ref.table}.${ref.column}: ${ref.count}`;
  }

  async function forceDeleteUser(user) {
    const refs = Number(user.reference_count || 0);
    const details = user.reference_details || [];
    const deleteRefs = details.filter((r) => effectiveForceAction(r) === "cascade_delete");
    const reassignRefs = details.filter((r) => effectiveForceAction(r) !== "cascade_delete");

    const deleteLines = deleteRefs.map((r) => `- ${formatRef(r)}`).join("\n") || "- none";
    const reassignLines = reassignRefs.map((r) => `- ${formatRef(r)} → ${forceActionLabel(r)}`).join("\n") || "- none";

    const ok = confirm(
      `Force delete ${userDisplayName(user)}?\n\n` +
      `This will permanently delete the user record.\n\n` +
      `Cascade-deleted user-owned rows:\n${deleteLines}\n\n` +
      `Reassigned historical/shared references:\n${reassignLines}\n\n` +
      `Total refs: ${refs}\n\nContinue?`
    );
    if (!ok) return;
    await fetchJsonDebug(`/api/identity/scope/users/${encodeURIComponent(user.id)}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ acting_user_id: activeIdentity().user_id, tenant_id: user.tenant_id, force: true }),
    });
    showToast(`Force deleted ${userDisplayName(user)}.`, "warn");
    if (window.wyrmgptIdentity?.loadIdentity) await window.wyrmgptIdentity.loadIdentity();
    if (Number(currentEditingUserId()) === Number(user.id)) clearManagedAboutFields();
    if (typeof window.refreshContext === "function") await window.refreshContext();
  }

  function enhanceUserList() {
    const list = $("identityUserList");
    if (!list) return;
    const caps = identityState().capabilities || {};
    [...list.querySelectorAll(".identityListItem")].forEach((row) => {
      if (row.dataset.profileEnhanced === "1") return;
      const user = identifyUserFromRow(row);
      if (!user) return;
      row.dataset.profileEnhanced = "1";
      row.dataset.userId = String(user.id);
      const label = row.querySelector(".identityListLabel");
      const actions = row.querySelector(".identityListActions");
      if (user.avatar_url && label && !row.querySelector(".identityUserAvatarThumb")) {
        const avatar = document.createElement("img");
        avatar.className = "identityUserAvatarThumb";
        avatar.src = user.avatar_url;
        avatar.alt = "";
        row.classList.add("hasAvatar");
        row.insertBefore(avatar, label);
      }
      if (label && Number(user.reference_count || 0) > 0) {
        const details = document.createElement("details");
        details.className = "identityRefDetails";
        const summary = document.createElement("summary");
        summary.textContent = `refs=${user.reference_count}`;
        details.appendChild(summary);
        const ul = document.createElement("ul");
        (user.reference_details || []).forEach((ref) => {
          const li = document.createElement("li");
          li.textContent = `${formatRef(ref)} — ${forceActionLabel(ref)}`;
          ul.appendChild(li);
        });
        details.appendChild(ul);
        label.appendChild(details);
      }
      if (actions && Number(user.reference_count || 0) > 0 && user.can_force_delete && caps.can_force_delete_identity) {
        const btn = document.createElement("button");
        btn.className = "identityForceDelete danger";
        btn.textContent = "Force Delete";
        btn.addEventListener("click", () => forceDeleteUser(user).catch((e) => alert(`Force delete failed: ${e?.message || e}`)));
        actions.appendChild(btn);
      }
    });
  }

  function installProfileUiHooks() {
    ensureManageUserAboutPanel();
    $("identitySaveUser")?.addEventListener("click", handleUserSaveClick, true);
    $("identitySaveUserBottom")?.addEventListener("click", handleUserSaveClick, true);

    const manageUsers = $("manageUsersTop");
    manageUsers?.addEventListener("click", () => {
      setTimeout(() => {
        setUserSaveButtonLabels();
        enhanceUserList();
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

    document.addEventListener("wyrmgpt:identity-user-edit", (event) => {
      const userId = event?.detail?.userId || event?.detail?.user?.id;
      if (!userId) return;
      setUserSaveButtonLabels();
      loadManagedAboutForUser(userId).catch((e) => {
        console.warn("load edited user's About You failed", e);
        showToast(`Failed to load About This User: ${e?.message || e}`, "error");
      });
    });

    document.addEventListener("wyrmgpt:identity-user-reset", () => {
      clearManagedAboutFields();
      setUserSaveButtonLabels();
    });

    const list = $("identityUserList");
    if (list && !userListObserver) {
      userListObserver = new MutationObserver(() => {
        enhanceUserList();
        setUserSaveButtonLabels();
      });
      userListObserver.observe(list, { childList: true, subtree: true });
    }
    setTimeout(() => {
      enhanceUserList();
      setUserSaveButtonLabels();
    }, 0);
  }

  window.wyrmgptUserProfiles = {
    fetchUserAboutYou,
    saveUserAboutYou,
    loadManageUserAbout: loadManagedAboutForUser,
    clearManagedAboutFields,
    enhanceUserList,
    syncUserSaveButtonLabels: setUserSaveButtonLabels,
  };

  installProfileUiHooks();
})();
