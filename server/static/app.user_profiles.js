// ----------------------------------
// User-scoped About You profile helpers
// ----------------------------------

(function () {
  const $ = (id) => document.getElementById(id);

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

  function usersManageableFromUserModal() {
    const state = identityState();
    const caps = state.capabilities || {};
    if (caps.is_global_admin) return state.allUsers?.length ? state.allUsers : state.users || [];
    return state.users || [];
  }

  function updateAboutYouTitle(user) {
    const section = window.aboutYouSectionEl || document.getElementById("aboutYouNickname")?.closest(".memSection");
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
    const payload = {
      nickname: (window.aboutYouNicknameEl?.value || $("aboutYouNickname")?.value || "").trim(),
      age: (window.aboutYouAgeEl?.value || $("aboutYouAge")?.value || "").trim(),
      occupation: (window.aboutYouOccupationEl?.value || $("aboutYouOccupation")?.value || "").trim(),
      more_about_you: (window.aboutYouMoreEl?.value || $("aboutYouMore")?.value || "").trim(),
    };
    await saveUserAboutYou(ident.user_id, ident.user_id, payload);
    if (typeof window.loadPersonalization === "function") await window.loadPersonalization();
    if (typeof window.refreshContext === "function") await window.refreshContext();
  };

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
      <div class="identityFormStack">
        <select id="identityAboutUserSelect"></select>
        <input id="identityAboutNickname" placeholder="Nickname" />
        <input id="identityAboutAge" placeholder="Approximate age" />
        <textarea id="identityAboutOccupation" rows="2" placeholder="Occupation"></textarea>
        <textarea id="identityAboutMore" rows="5" placeholder="More about this user"></textarea>
        <button id="identityAboutSave">Save About This User</button>
        <div id="identityAboutNote" class="identityScopeNote"></div>
      </div>
    `;
    bodyGrid.appendChild(panel);
    $("identityAboutUserSelect")?.addEventListener("change", () => loadManageUserAbout().catch((e) => alert(`Failed to load About You: ${e?.message || e}`)));
    $("identityAboutSave")?.addEventListener("click", () => saveManageUserAbout().catch((e) => alert(`Failed to save About You: ${e?.message || e}`)));
  }

  function fillManageAboutUserSelect(preferUserId = null) {
    ensureManageUserAboutPanel();
    const select = $("identityAboutUserSelect");
    if (!select) return;
    const prev = preferUserId || select.value || activeIdentity().user_id;
    const users = usersManageableFromUserModal();
    select.innerHTML = "";
    users.forEach((u) => {
      const opt = document.createElement("option");
      opt.value = String(u.id);
      const role = Number(u.is_global_admin || 0) === 1 ? "global admin" : Number(u.is_tenant_admin || 0) === 1 ? "tenant admin" : Number(u.is_global || 0) === 1 ? "global" : u.tenant_name || "tenant user";
      opt.textContent = `${u.display_name || u.slug || `User ${u.id}`} · ${role}`;
      select.appendChild(opt);
    });
    if ([...select.options].some((opt) => opt.value === String(prev))) select.value = String(prev);
  }

  async function loadManageUserAbout(preferUserId = null) {
    fillManageAboutUserSelect(preferUserId);
    const targetUserId = Number($("identityAboutUserSelect")?.value || 0);
    const actorUserId = activeIdentity().user_id;
    if (!targetUserId) return;
    const data = await fetchUserAboutYou(targetUserId, actorUserId);
    if ($("identityAboutNickname")) $("identityAboutNickname").value = data.nickname || "";
    if ($("identityAboutAge")) $("identityAboutAge").value = data.age || "";
    if ($("identityAboutOccupation")) $("identityAboutOccupation").value = data.occupation || "";
    if ($("identityAboutMore")) $("identityAboutMore").value = data.more_about_you || "";
    const user = usersManageableFromUserModal().find((u) => Number(u.id) === Number(targetUserId));
    if ($("identityAboutNote")) $("identityAboutNote").textContent = `Editing About You for ${user?.display_name || targetUserId}.`;
  }

  async function saveManageUserAbout() {
    const targetUserId = Number($("identityAboutUserSelect")?.value || 0);
    const actorUserId = activeIdentity().user_id;
    if (!targetUserId) return;
    await saveUserAboutYou(targetUserId, actorUserId, {
      nickname: ($("identityAboutNickname")?.value || "").trim(),
      age: ($("identityAboutAge")?.value || "").trim(),
      occupation: ($("identityAboutOccupation")?.value || "").trim(),
      more_about_you: ($("identityAboutMore")?.value || "").trim(),
    });
    if (Number(targetUserId) === Number(activeIdentity().user_id) && typeof window.loadPersonalization === "function") {
      await window.loadPersonalization();
    }
    if (typeof window.refreshContext === "function") await window.refreshContext();
  }

  function installProfileUiHooks() {
    ensureManageUserAboutPanel();
    const manageUsers = $("manageUsersTop");
    manageUsers?.addEventListener("click", () => {
      setTimeout(() => loadManageUserAbout().catch((e) => console.warn("load managed About You failed", e)), 0);
    });
    document.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.textContent === "Edit" && target.closest("#identityUserList")) {
        setTimeout(() => {
          const editing = window.wyrmgptIdentity?.state?.editingUserId;
          if (editing) loadManageUserAbout(editing).catch((e) => console.warn("load edited user's About You failed", e));
        }, 0);
      }
    });
  }

  window.wyrmgptUserProfiles = {
    fetchUserAboutYou,
    saveUserAboutYou,
    loadManageUserAbout,
  };

  installProfileUiHooks();
})();
