/**
 * Admin Management Modal Component
 * Gated to users with role='admin'.
 */
import { STORAGE_KEY, DEFAULT_API_URL, getCleanUrl } from "../config.js";
import { state, isAdmin } from "../state.js";
import { api } from "../services/api.js";
import { escapeHtml, createModalController } from "../services/domUtils.js";
import { showToast, showPrompt, showConfirm } from "./uiFeedback.js";

let adminModalController = null;
let onRequestRefreshBoard = null;

export const setAdminModalRefreshCallback = (cb) => {
  onRequestRefreshBoard = cb;
};

export const loadEmailConfig = async () => {
  try {
    const cfg = await api.getEmailConfig();
    const userEl = document.getElementById("gmailUser");
    const nameEl = document.getElementById("gmailSenderName");
    const passEl = document.getElementById("gmailAppPassword");
    const urlEl = document.getElementById("gmailAppUrl");
    if (userEl && cfg.gmailUser) userEl.value = cfg.gmailUser;
    if (nameEl && cfg.senderName) nameEl.value = cfg.senderName;
    if (urlEl) urlEl.value = cfg.appUrl || window.location.origin + window.location.pathname;
    if (passEl && cfg.hasPassword && !passEl.value) {
      passEl.placeholder = cfg.passwordMasked || "••••••••";
    }
  } catch (e) {
    console.warn("Could not prefetch email config", e);
  }
};

export const switchAdminTab = (tab) => {
  const tabs = ["projects", "members", "email", "endpoint"];
  tabs.forEach((t) => {
    const btn = document.getElementById(`tabBtn${t.charAt(0).toUpperCase() + t.slice(1)}`);
    const content = document.getElementById(`adminTab${t.charAt(0).toUpperCase() + t.slice(1)}`);
    if (btn) btn.classList.toggle("active", t === tab);
    if (content) content.style.display = t === tab ? "block" : "none";
  });

  if (tab === "email") {
    loadEmailConfig();
  }

  if (tab === "endpoint") {
    const input = document.getElementById("adminApiUrlInput");
    if (input) input.value = getCleanUrl();
  }
};

export const loadManageModal = async (selectedProj = null) => {
  const projects = await api.getProjects();
  const projSelect = document.getElementById("manageProjectSelect");
  const projChips = document.getElementById("projectsChipList");

  if (projSelect) projSelect.innerHTML = "";
  if (projChips) projChips.innerHTML = "";

  projects.forEach((p) => {
    if (projSelect) {
      const opt = document.createElement("option");
      opt.value = p.name;
      opt.textContent = `${p.name} ${p.allow_self_assignment ? '🔓' : '🔒'}`;
      projSelect.appendChild(opt);
    }

    if (projChips) {
      const chip = document.createElement("div");
      chip.className = "chip";
      chip.innerHTML = `
        <span>${escapeHtml(p.name)}</span>
        <button type="button" class="btn-toggle-proj-lock" title="${p.allow_self_assignment ? 'Autoasignable (clic para cerrar)' : 'Cerrado (clic para abrir)'}">
          ${p.allow_self_assignment ? '🔓' : '🔒'}
        </button>
        <button type="button" class="btn-edit-proj" title="Editar nombre">✏️</button>
        <button type="button" class="btn-delete-proj" title="Eliminar proyecto">×</button>
      `;

      chip.querySelector(".btn-toggle-proj-lock")?.addEventListener("click", () => toggleProjectLock(p.name, p.allow_self_assignment));
      chip.querySelector(".btn-edit-proj")?.addEventListener("click", () => editProjectName(p.name));
      chip.querySelector(".btn-delete-proj")?.addEventListener("click", () => deleteProjectAction(p.name));

      projChips.appendChild(chip);
    }
  });

  const active = selectedProj || (projects[0] && projects[0].name);
  if (projSelect && active) {
    projSelect.value = active;
  }
  await loadMembersChipList();
};

export const loadMembersChipList = async () => {
  const projSelect = document.getElementById("manageProjectSelect");
  const chipContainer = document.getElementById("membersChipList");
  if (!projSelect || !chipContainer) return;

  const project = projSelect.value;
  chipContainer.innerHTML = `<span style="font-size: 11px; color: var(--text-muted);">Cargando integrantes...</span>`;

  if (!project) {
    chipContainer.innerHTML = `<span style="font-size: 11px; color: var(--text-muted);">Seleccioná un proyecto.</span>`;
    return;
  }

  const members = await api.getMembers(project);
  chipContainer.innerHTML = "";

  if (members.length === 0) {
    chipContainer.innerHTML = `<span style="font-size: 11px; color: var(--text-muted);">Sin integrantes. Agregá uno arriba.</span>`;
    return;
  }

  members.forEach((m) => {
    const chip = document.createElement("div");
    chip.className = "chip";
    const roleBadge = m.is_admin ? '<span style="color: #0284c7; font-weight: 700; margin-left: 4px;">(Admin)</span>' : '';
    const emailInfo = m.email ? `<small style="color: var(--text-muted); font-size: 11px; margin-left: 4px;">&lt;${escapeHtml(m.email)}&gt;</small>` : '';
    chip.innerHTML = `
      <span>👤 <strong>${escapeHtml(m.name)}</strong> (${escapeHtml(m.role || "Dev")})${roleBadge}${emailInfo}</span>
      <button type="button" class="btn-edit-member" title="Editar integrante">✏️</button>
      <button type="button" class="btn-delete-member" title="Eliminar de este proyecto">×</button>
    `;

    chip.querySelector(".btn-edit-member")?.addEventListener("click", () => editMemberAction(project, m.name, m.role, m.email, m.is_admin));
    chip.querySelector(".btn-delete-member")?.addEventListener("click", () => deleteMemberAction(project, m.name));

    chipContainer.appendChild(chip);
  });
};

const toggleProjectLock = async (name, currentVal) => {
  try {
    await api.updateProject(name, name, !currentVal);
    await loadManageModal(name);
    if (onRequestRefreshBoard) await onRequestRefreshBoard();
    showToast(`Proyecto '${name}' ahora está ${!currentVal ? 'Abierto (Autoasignable)' : 'Cerrado (Solo Admin)'}.`);
  } catch (err) {
    showToast(err.message, "error");
  }
};

const editProjectName = async (oldName) => {
  const res = await showPrompt({
    title: "Editar Proyecto",
    label: "Nuevo nombre del proyecto:",
    initialValue: oldName,
  });
  if (!res || !res.value.trim() || res.value.trim() === oldName) return;
  const newName = res.value.trim();

  try {
    await api.updateProject(oldName, newName);
    await loadManageModal(newName);
    if (onRequestRefreshBoard) await onRequestRefreshBoard();
    showToast(`Proyecto renombrado a '${newName}'.`);
  } catch (err) {
    showToast(err.message, "error");
  }
};

const deleteProjectAction = async (name) => {
  const ok = await showConfirm("Eliminar Proyecto", `¿Eliminar '${name}' y todas sus tareas/dailies?`);
  if (!ok) return;
  try {
    await api.deleteProject(name);
    await loadManageModal();
    if (onRequestRefreshBoard) await onRequestRefreshBoard();
    showToast(`Proyecto '${name}' eliminado.`);
  } catch (err) {
    showToast(err.message, "error");
  }
};

const editMemberAction = async (project, oldName, oldRole, oldEmail, oldIsAdmin = false) => {
  const res = await showPrompt({
    title: "Editar Integrante",
    label: "Nombre:",
    initialValue: oldName,
    secondLabel: "Rol en proyecto:",
    secondInitialValue: oldRole || "Developer",
  });
  if (!res || !res.value.trim()) return;

  try {
    await api.updateMember(project, oldName, res.value.trim(), res.secondValue?.trim() || "Developer", oldEmail || "", oldIsAdmin);
    await loadMembersChipList();
    if (onRequestRefreshBoard) await onRequestRefreshBoard();
    showToast("Integrante actualizado.");
  } catch (err) {
    showToast(err.message, "error");
  }
};

const deleteMemberAction = async (project, name) => {
  const ok = await showConfirm(
    "Eliminar Integrante y Cuenta",
    `¿Eliminar a '${name}' y dar de baja definitivamente su cuenta de usuario? Si vuelve a agregarse con el mismo correo, se creará de cero con una nueva invitación.`
  );
  if (!ok) return;
  try {
    await api.deleteMember(project, name);
    await loadMembersChipList();
    if (onRequestRefreshBoard) await onRequestRefreshBoard();
    showToast(`Integrante '${name}' y su cuenta fueron eliminados de cero.`);
  } catch (err) {
    showToast(err.message, "error");
  }
};

export const initAdminModalListeners = () => {
  adminModalController = createModalController("manageModal", "manageModalClose");

  // Open Manage Modal
  const btnOpen = document.getElementById("btnOpenManageModal");
  if (btnOpen) {
    btnOpen.addEventListener("click", () => {
      if (!isAdmin()) {
        showToast("Se requieren privilegios de Administrador.", "error");
        return;
      }
      switchAdminTab("projects");
      adminModalController.open();
      loadManageModal();
    });
  }

  // Manage Modal Tabs
  document.getElementById("tabBtnProjects")?.addEventListener("click", () => switchAdminTab("projects"));
  document.getElementById("tabBtnMembers")?.addEventListener("click", () => switchAdminTab("members"));
  document.getElementById("tabBtnEmail")?.addEventListener("click", () => switchAdminTab("email"));
  document.getElementById("tabBtnEndpoint")?.addEventListener("click", () => switchAdminTab("endpoint"));

  // Add Project
  document.getElementById("btnAddProject")?.addEventListener("click", async () => {
    const input = document.getElementById("newProjectName");
    const name = input?.value.trim();
    const allowSelf = document.getElementById("newProjectAllowSelf")?.checked || false;
    if (!name) return;

    try {
      await api.createProject(name, allowSelf);
      input.value = "";
      document.getElementById("newProjectAllowSelf").checked = false;
      await loadManageModal(name);
      if (onRequestRefreshBoard) await onRequestRefreshBoard();
      showToast(`Proyecto '${name}' creado.`);
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Project Select Change in Members Tab
  document.getElementById("manageProjectSelect")?.addEventListener("change", () => {
    loadMembersChipList();
  });

  // Add Member
  document.getElementById("btnAddMember")?.addEventListener("click", async () => {
    const project = document.getElementById("manageProjectSelect")?.value;
    const nameInput = document.getElementById("newMemberName");
    const roleInput = document.getElementById("newMemberRole");
    const emailInput = document.getElementById("newMemberEmail");
    const systemRoleSelect = document.getElementById("newMemberSystemRole");

    const name = nameInput?.value.trim();
    const role = roleInput?.value.trim() || "Developer";
    const email = emailInput?.value.trim() || "";
    const systemRole = systemRoleSelect?.value || "member";
    const isAdmin = systemRole === "admin";

    if (!project || !name) {
      showToast("Ingresá el nombre del integrante", "error");
      return;
    }
    if (!email) {
      showToast("El correo electrónico es obligatorio para enviar la invitación", "error");
      return;
    }

    try {
      const res = await api.createMember(project, name, role, email, isAdmin);
      nameInput.value = "";
      roleInput.value = "";
      emailInput.value = "";
      await loadMembersChipList();
      if (onRequestRefreshBoard) await onRequestRefreshBoard();

      if (res?.invite_sent) {
        showToast(`Integrante '${name}' agregado. Código de activación enviado a ${email}.`);
      } else if (res?.invite_error) {
        showToast(`Integrante agregado, pero falló el envío de correo (${res.invite_error}).`, "error");
      } else {
        showToast(`Integrante '${name}' agregado exitosamente.`);
      }
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Gmail SMTP Email Config
  const gmailUserInput = document.getElementById("gmailUser");
  const gmailPassInput = document.getElementById("gmailAppPassword");
  const gmailSenderInput = document.getElementById("gmailSenderName");
  const gmailUrlInput = document.getElementById("gmailAppUrl");

  document.getElementById("btnToggleGmailPassword")?.addEventListener("click", () => {
    if (!gmailPassInput) return;
    gmailPassInput.type = gmailPassInput.type === "password" ? "text" : "password";
  });

  document.getElementById("btnSaveEmailConfig")?.addEventListener("click", async () => {
    const gmailUser = gmailUserInput?.value.trim();
    const gmailPassword = gmailPassInput?.value.trim();
    const senderName = gmailSenderInput?.value.trim() || "Daily Scrum";
    const appUrl = (gmailUrlInput?.value.trim()) || (window.location.origin + window.location.pathname);

    if (!gmailUser) {
      showToast("Ingresá tu correo de Gmail", "error");
      return;
    }

    try {
      await api.saveEmailConfig(gmailUser, gmailPassword, senderName, appUrl);
      showToast("Configuración de Gmail SMTP guardada en el backend.");
      await loadEmailConfig();
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  document.getElementById("btnTestEmail")?.addEventListener("click", async () => {
    const defaultEmail = state.currentUser?.email || "";
    const targetEmail = prompt(
      "Ingresá el correo de destino para la prueba de Gmail SMTP:",
      defaultEmail
    );
    if (!targetEmail || !targetEmail.includes("@")) return;

    try {
      showToast("Enviando correo de prueba...");
      const res = await api.testEmail(targetEmail.trim());
      showToast(res.message || "Email de prueba enviado exitosamente.");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  // Endpoint Config
  const adminApiInput = document.getElementById("adminApiUrlInput");
  if (adminApiInput) adminApiInput.value = getCleanUrl();

  document.getElementById("btnSaveApiUrl")?.addEventListener("click", () => {
    const val = (adminApiInput?.value || "").trim();
    if (!val || !val.startsWith("http")) {
      showToast("Ingresá una URL válida que empiece con https://", "error");
      return;
    }
    localStorage.setItem(STORAGE_KEY, val);
    showToast("Endpoint de Lambda actualizado exitosamente.");
    if (onRequestRefreshBoard) onRequestRefreshBoard();
  });

  document.getElementById("btnResetApiUrl")?.addEventListener("click", () => {
    localStorage.setItem(STORAGE_KEY, DEFAULT_API_URL);
    if (adminApiInput) adminApiInput.value = DEFAULT_API_URL;
    showToast("Endpoint restablecido al valor predeterminado de AWS.");
    if (onRequestRefreshBoard) onRequestRefreshBoard();
  });
};
