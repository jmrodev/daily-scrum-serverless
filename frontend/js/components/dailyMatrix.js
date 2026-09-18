/**
 * Daily Scrum Matrix Component
 * Manages weekly matrix table rendering, cell edits, and Kanban synchronization.
 */
import { DAYS } from "../config.js";
import { state, isAdmin } from "../state.js";
import { api } from "../services/api.js";
import { getCurrentDayName, getStatusLabel } from "../services/dateUtils.js";
import { escapeHtml, createModalController } from "../services/domUtils.js";
import { showToast, showConfirm } from "./uiFeedback.js";

let scrumModalController = null;
let activeScrumContext = null;
let requestKanbanRender = null;
let requestAdminModalReload = null;

export const setDailyMatrixCallbacks = ({ onRenderKanban, onReloadAdminModal }) => {
  requestKanbanRender = onRenderKanban;
  requestAdminModalReload = onReloadAdminModal;
};

export const renderBoard = async () => {
  const project = document.getElementById("boardProject")?.value || state.activeProject;
  const week = document.getElementById("boardWeek")?.value || state.activeWeek;
  const tbody = document.getElementById("scrumTableBody");
  const bannerContainer = document.getElementById("projectSelfAssignContainer");

  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 24px; color:#94a3b8;">Cargando matriz...</td></tr>`;

  if (!project) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 24px; color:#94a3b8;">No hay proyectos disponibles.</td></tr>`;
    return;
  }

  const [allProjects, members, scrums, tasks] = await Promise.all([
    api.getProjects(),
    api.getMembers(project),
    api.getWeeklyScrums(project, week),
    api.getTasks(project),
  ]);

  const currentProjObj = allProjects.find((p) => p.name === project) || {
    name: project,
    allow_self_assignment: false,
  };

  const isMemberOfProject = members.some(
    (m) => state.currentUser.name && m.name.toLowerCase() === state.currentUser.name.toLowerCase()
  );

  // Render Project Self-Assignment Status
  if (bannerContainer) {
    if (isAdmin()) {
      bannerContainer.innerHTML = `
        <button type="button" class="tag-status ${currentProjObj.allow_self_assignment ? 'open' : 'closed'}" id="btnToggleSelfAssign" title="Clic para alternar permiso de autoasignación">
          ${currentProjObj.allow_self_assignment ? '🔓 Abierto (Autoasignable)' : '🔒 Cerrado (Solo Admin)'}
        </button>
      `;
      document.getElementById("btnToggleSelfAssign")?.addEventListener("click", () => toggleProjectSelfAssign(project));
    } else if (state.currentUser.role === "member") {
      if (isMemberOfProject) {
        bannerContainer.innerHTML = `
          <span style="font-size: 12px; color: var(--success); font-weight: 700; display: inline-flex; align-items: center; gap: 4px;">
            ✅ Estás en este equipo
          </span>
          ${currentProjObj.allow_self_assignment ? `
            <button type="button" id="btnLeaveProject" class="btn btn-secondary btn-sm" style="margin-left: 6px; font-size: 11px; padding: 2px 7px;">
              Abandonar
            </button>
          ` : ''}
        `;
        document.getElementById("btnLeaveProject")?.addEventListener("click", () => leaveProjectAction(project));
      } else {
        if (currentProjObj.allow_self_assignment) {
          bannerContainer.innerHTML = `
            <button type="button" id="btnJoinProject" class="btn btn-primary btn-sm" style="background: #16a34a;">
              ➕ Unirme a este Proyecto
            </button>
          `;
          document.getElementById("btnJoinProject")?.addEventListener("click", () => joinProjectAction(project));
        } else {
          bannerContainer.innerHTML = `
            <span style="font-size: 11px; color: var(--text-muted);">
              🔒 Proyecto cerrado por el administrador.
            </span>
          `;
        }
      }
    } else {
      bannerContainer.innerHTML = "";
    }
  }

  // Highlight Current Day Header
  const today = getCurrentDayName();
  DAYS.forEach((d, idx) => {
    const th = document.querySelector(`#scrumTableHeadRow th:nth-child(${idx + 2})`);
    if (th) {
      if (d === today) {
        th.classList.add("current-day");
        if (!th.querySelector(".badge-today")) {
          th.innerHTML = `${d} <span class="badge-today">HOY</span>`;
        }
      } else {
        th.classList.remove("current-day");
        th.textContent = d;
      }
    }
  });

  tbody.innerHTML = "";

  if (members.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 24px; color:#94a3b8;">No hay integrantes asignados a este proyecto.</td></tr>`;
    return;
  }

  const scrumsMap = {};
  scrums.forEach((s) => {
    scrumsMap[`${s.member}#${s.day}`] = s;
  });

  members.forEach((m) => {
    const tr = document.createElement("tr");

    const isSelf = state.currentUser.name && (m.name.toLowerCase() === state.currentUser.name.toLowerCase());
    const canEditThisRow = isAdmin() || isSelf;

    const memberTasks = (tasks || []).filter(
      (t) => t.assignee && t.assignee.toLowerCase() === m.name.toLowerCase()
    );
    const doingCount = memberTasks.filter((t) => t.status === "DOING").length;
    const blockedCount = memberTasks.filter((t) => t.status === "BLOCKED").length;
    const doneCount = memberTasks.filter((t) => t.status === "DONE").length;

    const memberTd = document.createElement("td");
    memberTd.innerHTML = `
      <div class="member-cell-name">
        👤 ${escapeHtml(m.name)}
        ${isSelf ? '<span class="member-cell-self">TÚ</span>' : ''}
      </div>
      <div class="member-cell-role">${escapeHtml(m.role || "Developer")}</div>
      <div class="member-kanban-badges" title="Tareas de ${escapeHtml(m.name)} en el Tablero Kanban">
        ${blockedCount > 0 ? `<span class="badge-kanban-mini blocked" title="${blockedCount} tarea(s) bloqueada(s)">🚨 ${blockedCount}</span>` : ''}
        ${doingCount > 0 ? `<span class="badge-kanban-mini doing" title="${doingCount} tarea(s) en progreso">⚡ ${doingCount}</span>` : ''}
        ${doneCount > 0 ? `<span class="badge-kanban-mini done" title="${doneCount} tarea(s) completada(s)">✅ ${doneCount}</span>` : ''}
        ${blockedCount === 0 && doingCount === 0 && doneCount === 0 ? `<span class="badge-kanban-mini empty" title="Sin tareas activas">0 tareas</span>` : ''}
      </div>
    `;
    tr.appendChild(memberTd);

    DAYS.forEach((day) => {
      const isToday = day === today;
      const dayTd = document.createElement("td");
      if (isToday) dayTd.classList.add("current-day-cell");
      const scrum = scrumsMap[`${m.name}#${day}`];

      if (scrum) {
        const ans = scrum.answers || [];
        const ans1 = escapeHtml(ans[0] || "Sin respuesta");
        const ans2 = escapeHtml(ans[1] || "Sin respuesta");
        const ans3 = escapeHtml(ans[2] || "Ninguno");
        const hasBlocker = ans[2] && ans[2].toLowerCase() !== "ninguno" && ans[2].trim() !== "";

        dayTd.innerHTML = `
          <div class="scrum-entry">
            <div class="scrum-top-bar">
              <div style="display: flex; align-items: center; gap: 4px;">
                ${hasBlocker ? '<span class="tag-blocker">🚨 Bloqueo</span>' : '<span class="tag-clean">✓</span>'}
                ${isToday ? '<span class="tag-synced">⚡ Hoy</span>' : ''}
              </div>
              ${canEditThisRow ? `
                <div class="actions-mini">
                  <button type="button" class="btn-action btn-edit-scrum" title="Editar">✏️</button>
                  <button type="button" class="btn-action danger btn-delete-scrum" title="Eliminar">🗑️</button>
                </div>
              ` : ''}
            </div>
            <div class="scrum-line"><span class="lbl">Hecho:</span> ${ans1}</div>
            <div class="scrum-line"><span class="lbl">Sigue:</span> ${ans2}</div>
            ${hasBlocker ? `<div class="scrum-line is-blocked"><span class="lbl">Bloqueo:</span> ${ans3}</div>` : ""}
          </div>
        `;

        if (canEditThisRow) {
          dayTd.querySelector(".btn-edit-scrum")?.addEventListener("click", () => openScrumModal(project, week, day, m.name, true));
          dayTd.querySelector(".btn-delete-scrum")?.addEventListener("click", () => deleteScrumEntry(project, week, day, m.name));
        }
      } else {
        if (canEditThisRow) {
          dayTd.innerHTML = `
            <button type="button" class="cell-empty-btn">
              <span>+ Cargar</span>
              ${isToday && memberTasks.length > 0 ? `<span style="font-size:9px; color:var(--primary); font-weight:700;">(${memberTasks.length} en Kanban)</span>` : ''}
            </button>
          `;
          dayTd.querySelector(".cell-empty-btn")?.addEventListener("click", () => openScrumModal(project, week, day, m.name, false));
        } else {
          dayTd.innerHTML = `
            <div class="cell-empty-readonly" title="Solo editable por ${escapeHtml(m.name)}">—</div>
          `;
        }
      }
      tr.appendChild(dayTd);
    });

    tbody.appendChild(tr);
  });
};

export const joinProjectAction = async (project) => {
  if (!state.currentUser.name) {
    showToast("Debes iniciar sesión para unirte a un proyecto.", "error");
    return;
  }
  try {
    await api.createMember(project, state.currentUser.name, state.currentUser.title || "Developer", state.currentUser.email);
    await renderBoard();
    showToast(`¡Te uniste al proyecto '${project}'! Ya podés cargar tu Daily.`);
  } catch (err) {
    showToast(err.message, "error");
  }
};

export const leaveProjectAction = async (project) => {
  const ok = await showConfirm("Abandonar Proyecto", `¿Seguro que deseas desvincularte del proyecto '${project}'?`);
  if (!ok) return;
  try {
    await api.deleteMember(project, state.currentUser.name);
    await renderBoard();
    showToast(`Te desvinculaste de '${project}'.`);
  } catch (err) {
    showToast(err.message, "error");
  }
};

export const toggleProjectSelfAssign = async (project) => {
  if (!isAdmin()) return;
  const projects = await api.getProjects();
  const p = projects.find((x) => x.name === project);
  if (!p) return;
  const newVal = !p.allow_self_assignment;
  try {
    await api.updateProject(project, project, newVal);
    if (requestAdminModalReload) await requestAdminModalReload(project);
    await renderBoard();
    showToast(`Proyecto '${project}' configurado como ${newVal ? 'Abierto (Autoasignable)' : 'Cerrado (Solo Admin)'}.`);
  } catch (err) {
    showToast(err.message, "error");
  }
};

export const openScrumModal = async (project, week, day, member, isEdit) => {
  const isSelf = state.currentUser.name && (member.toLowerCase() === state.currentUser.name.toLowerCase());
  if (!isAdmin() && !isSelf) {
    showToast(`Solo podés cargar o editar tu propia Daily Scrum (${state.currentUser.name})`, "error");
    return;
  }

  activeScrumContext = { project, week, day, member, isEdit };
  document.getElementById("modalTitle").textContent = isEdit ? "✏️ Editar Daily Scrum" : "📝 Registrar Daily Scrum";
  document.getElementById("modalMetaTags").innerHTML = `
    <span class="tag">📁 ${escapeHtml(project)}</span>
    <span class="tag">📅 ${escapeHtml(week)}</span>
    <span class="tag">🗓️ ${escapeHtml(day)}</span>
    <span class="tag">👤 ${escapeHtml(member)}</span>
  `;

  const ans1 = document.getElementById("modalAns1");
  const ans2 = document.getElementById("modalAns2");
  const ans3 = document.getElementById("modalAns3");
  const deleteBtn = document.getElementById("btnDeleteScrum");

  let prefilledFromKanban = false;
  let memberTasks = [];
  try {
    const tasks = await api.getTasks(project);
    memberTasks = (tasks || []).filter(
      (t) => t.assignee && t.assignee.toLowerCase() === member.toLowerCase()
    );
  } catch (err) {
    // continue
  }

  if (isEdit) {
    deleteBtn.style.display = "inline-flex";
    const scrums = await api.getWeeklyScrums(project, week);
    const match = scrums.find((s) => s.member === member && s.day === day);
    const answers = match ? match.answers : ["", "", ""];
    ans1.value = answers[0] || "";
    ans2.value = answers[1] || "";
    ans3.value = answers[2] || "";
  } else {
    deleteBtn.style.display = "none";
    const doneTasks = memberTasks.filter((t) => t.status === "DONE").map((t) => t.title);
    const doingTasks = memberTasks.filter((t) => t.status === "DOING").map((t) => t.title);
    const blockedTasks = memberTasks.filter((t) => t.status === "BLOCKED").map((t) => t.blocker ? `[${t.title}] ${t.blocker}` : `[${t.title}] Bloqueada`);

    if (doneTasks.length > 0 || doingTasks.length > 0 || blockedTasks.length > 0) {
      ans1.value = doneTasks.length > 0 ? doneTasks.map((t) => `• ${t}`).join("\n") : "Sin respuesta";
      ans2.value = doingTasks.length > 0 ? doingTasks.map((t) => `• ${t}`).join("\n") : "Sin respuesta";
      ans3.value = blockedTasks.length > 0 ? blockedTasks.map((t) => `• ${t}`).join("\n") : "Ninguno";
      prefilledFromKanban = true;
    } else {
      ans1.value = "";
      ans2.value = "";
      ans3.value = "Ninguno";
    }
  }

  const syncCheckbox = document.getElementById("syncKanbanOnSave");
  if (syncCheckbox) syncCheckbox.checked = true;

  const btnAutofill = document.getElementById("btnAutofillFromKanban");
  if (btnAutofill) {
    btnAutofill.textContent = memberTasks.length > 0
      ? `🔄 Re-sincronizar con mi Kanban (${memberTasks.length})`
      : `🔄 Re-sincronizar con mi Kanban`;
  }

  await refreshModalBlockedTasks(project, member);

  const banner = document.getElementById("scrumAutoSyncBanner");
  if (banner) {
    if (prefilledFromKanban) {
      banner.style.display = "flex";
      banner.innerHTML = `⚡ <strong>Sincronización automática:</strong> Respuestas auto-cargadas desde tus tareas de Kanban.`;
    } else {
      banner.style.display = "none";
    }
  }

  scrumModalController.open();
};

export const refreshModalBlockedTasks = async (project, member) => {
  const container = document.getElementById("modalActiveBlockedTasksList");
  const blockedSelect = document.getElementById("modalBlockedTaskSelect");
  const newBlockedTitleContainer = document.getElementById("modalNewBlockedTaskTitleContainer");
  const newBlockedTitleInput = document.getElementById("modalNewBlockedTaskTitle");

  if (newBlockedTitleContainer) newBlockedTitleContainer.style.display = "none";
  if (newBlockedTitleInput) newBlockedTitleInput.value = "";

  let allProjectTasks = [];
  let memberTasks = [];
  try {
    allProjectTasks = await api.getTasks(project);
    memberTasks = (allProjectTasks || []).filter(
      (t) => t.assignee && t.assignee.toLowerCase() === member.toLowerCase()
    );
  } catch (err) {
    console.warn("Error loading modal blocked list:", err);
  }

  const blockedTasks = memberTasks.filter((t) => t.status === "BLOCKED");
  const waitingOnOtherTasks = (allProjectTasks || []).filter(
    (t) => t.blocker && t.blocker.toLowerCase().includes(`bloquea a ${member.toLowerCase()}`)
  );

  if (container) {
    if (blockedTasks.length === 0 && waitingOnOtherTasks.length === 0) {
      container.innerHTML = `
        <div style="padding: 6px 10px; background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.25); border-radius: 6px; font-size: 11px; color: #10b981; display: flex; align-items: center; gap: 6px; margin-bottom: 8px;">
          <span>✓</span> <span>No tenés tareas bloqueadas ni dependencias pendientes.</span>
        </div>
      `;
    } else {
      let html = `
        <div style="display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px;">
          <div style="font-size: 11px; font-weight: 700; color: #ef4444; text-transform: uppercase; letter-spacing: 0.5px;">
            🚨 Bloqueos Activos (${blockedTasks.length + waitingOnOtherTasks.length}) — No se liberan hasta resolverlos
          </div>
      `;
      blockedTasks.forEach((t) => {
        html += `
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.25); border-radius: 6px; font-size: 12px;">
            <div style="overflow: hidden; text-overflow: ellipsis; padding-right: 8px;">
              <strong>${escapeHtml(t.title)}</strong>
              <div style="font-size: 11px; color: #ef4444; margin-top: 1px;">Impedimento: ${escapeHtml(t.blocker || "Bloqueada")}</div>
            </div>
            <button type="button" class="btn-action btn-destrabar" data-task-id="${escapeHtml(t.id)}" style="background: var(--surface); border: 1px solid var(--border); font-size: 11px; padding: 4px 8px; border-radius: 4px; white-space: nowrap; cursor: pointer; color: #10b981;">
              ✅ Destrabar
            </button>
          </div>
        `;
      });
      waitingOnOtherTasks.forEach((t) => {
        const isDone = t.status === "DONE";
        const statusLabel = getStatusLabel(t.status);
        html += `
          <div style="display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; background: ${isDone ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)'}; border: 1px solid ${isDone ? 'rgba(16, 185, 129, 0.25)' : 'rgba(239, 68, 68, 0.25)'}; border-radius: 6px; font-size: 12px;">
            <div style="overflow: hidden; text-overflow: ellipsis; padding-right: 8px;">
              <strong>${isDone ? '🎉 [Resuelta]' : '⏳ [Esperando tarea]'} ${escapeHtml(t.title)}</strong>
              <div style="font-size: 11px; color: ${isDone ? '#10b981' : '#ef4444'}; margin-top: 1px;">
                ${t.assignee ? `Asignada a ${escapeHtml(t.assignee)} (${statusLabel})` : `Sin asignar en 'Por Hacer' (disponible para el equipo)`}
              </div>
            </div>
            <button type="button" class="btn-action btn-destrabar" data-task-id="${escapeHtml(t.id)}" style="background: var(--surface); border: 1px solid var(--border); font-size: 11px; padding: 4px 8px; border-radius: 4px; white-space: nowrap; cursor: pointer; color: #10b981;">
              ✅ Destrabar
            </button>
          </div>
        `;
      });
      html += `</div>`;
      container.innerHTML = html;

      container.querySelectorAll(".btn-destrabar").forEach((btn) => {
        btn.addEventListener("click", () => resolveTaskBlocker(btn.dataset.taskId));
      });
    }
  }

  if (blockedSelect) {
    blockedSelect.innerHTML = "";
    const defaultOpt = document.createElement("option");
    defaultOpt.value = "";
    defaultOpt.textContent = "🟢 Sin nuevo bloqueo (Avanzando con normalidad)";
    blockedSelect.appendChild(defaultOpt);

    // Group 1: Other project tasks that might be blocking me (in TODO or DOING)
    const otherTasks = (allProjectTasks || []).filter(
      (t) => (!t.assignee || t.assignee.toLowerCase() !== member.toLowerCase()) && (t.status === "TODO" || t.status === "DOING")
    );
    if (otherTasks.length > 0) {
      const groupOther = document.createElement("optgroup");
      groupOther.label = "⏳ Tarea del Proyecto que me traba (en curso o por hacer):";
      otherTasks.forEach((t) => {
        const opt = document.createElement("option");
        opt.value = `BLOCKS_ME#${t.id}`;
        const assigneeLabel = t.assignee ? `[${t.assignee}]` : "[Sin asignar en Por Hacer]";
        const statusIcon = t.status === "DOING" ? "⚡ [DOING]" : "📝 [TODO]";
        opt.textContent = `${statusIcon} ${assigneeLabel} ${t.title}`;
        groupOther.appendChild(opt);
      });
      blockedSelect.appendChild(groupOther);
    }

    // Group 2: My own tasks (if I want to mark my task as BLOCKED)
    const myActiveTasks = memberTasks.filter((t) => t.status === "TODO" || t.status === "DOING");
    if (myActiveTasks.length > 0) {
      const groupMy = document.createElement("optgroup");
      groupMy.label = "🚨 Marcar como bloqueada una de mis tareas:";
      myActiveTasks.forEach((t) => {
        const opt = document.createElement("option");
        opt.value = `MY_TASK#${t.id}`;
        const statusIcon = t.status === "DOING" ? "⚡ [DOING]" : "📝 [TODO]";
        opt.textContent = `${statusIcon} ${t.title}`;
        groupMy.appendChild(opt);
      });
      blockedSelect.appendChild(groupMy);
    }

    // Group 3: Create new blocking task
    const groupNew = document.createElement("optgroup");
    groupNew.label = "➕ Si la tarea requerida no existe todavía:";
    const newOpt = document.createElement("option");
    newOpt.value = "__NEW__";
    newOpt.textContent = "➕ Crear tarea en 'Por Hacer' (para que alguien del equipo la tome y me destrabe)";
    groupNew.appendChild(newOpt);
    blockedSelect.appendChild(groupNew);

    blockedSelect.value = "";
  }
};

export const resolveTaskBlocker = async (taskId) => {
  if (!activeScrumContext) return;
  const { project, member } = activeScrumContext;
  try {
    const tasks = await api.getTasks(project);
    const t = tasks.find((x) => x.id === taskId);
    if (!t) return;

    if (t.assignee && t.assignee.toLowerCase() === member.toLowerCase()) {
      t.status = "DOING";
      t.blocker = "";
    } else if (t.blocker) {
      t.blocker = t.blocker.replace(new RegExp(`Bloquea a ${member}:?.*`, "i"), "").trim();
    }
    await api.saveTask(t);
    showToast(`Bloqueo de '${t.title}' resuelto.`);

    await refreshModalBlockedTasks(project, member);

    const updatedTasks = await api.getTasks(project);
    const remainingBlocked = (updatedTasks || []).filter(
      (x) => (x.assignee && x.assignee.toLowerCase() === member.toLowerCase() && x.status === "BLOCKED") ||
             (x.blocker && x.blocker.toLowerCase().includes(`bloquea a ${member.toLowerCase()}`) && x.status !== "DONE")
    );
    const ans3 = document.getElementById("modalAns3");
    if (ans3) {
      ans3.value = remainingBlocked.length > 0
        ? remainingBlocked.map((x) => x.blocker ? `[${x.title}] ${x.blocker}` : `[${x.title}] Bloqueada`).join("; ")
        : "Ninguno";
    }

    await renderBoard();
    if (requestKanbanRender) await requestKanbanRender();
  } catch (err) {
    showToast(err.message, "error");
  }
};

export const deleteScrumEntry = async (project, week, day, member) => {
  const isSelf = state.currentUser.name && (member.toLowerCase() === state.currentUser.name.toLowerCase());
  if (!isAdmin() && !isSelf) {
    showToast(`Solo podés eliminar tu propia Daily Scrum`, "error");
    return;
  }
  const ok = await showConfirm("Eliminar Daily", `¿Eliminar la Daily de ${member} del ${day}?`);
  if (!ok) return;

  try {
    await api.deleteScrum(project, week, day, member);
    await renderBoard();
    showToast(`Daily eliminada.`);
  } catch (err) {
    showToast(err.message, "error");
  }
};

export const syncDailyToKanban = async (project, member, answers, explicitBlockedTaskId, explicitNewBlockedTitle, explicitBlockerReason) => {
  const doneText = answers[0] || "";
  const doingText = answers[1] || "";
  const blockerText = answers[2] || "";

  const splitItems = (text) => {
    if (!text) return [];
    // If text contains newlines or semicolons, treat them as intentional task delimiters and protect internal commas
    const hasLineBreaksOrSemi = text.includes("\n") || text.includes(";");
    const rawTokens = hasLineBreaksOrSemi
      ? text.split(/[\n;]+/)
      : text.split(",");

    return rawTokens
      .map((s) => s.replace(/^[-*•\d.)\s]+/, "").trim())
      .filter((s) => {
        if (!s || s.length < 2) return false;
        const lower = s.toLowerCase();
        return ![
          "ninguno",
          "ninguna",
          "no",
          "nada",
          "sin respuesta",
          "sin novedades",
          "n/a",
          "none",
          "ok",
        ].includes(lower);
      });
  };

  const doneItems = splitItems(doneText);
  const doingItems = splitItems(doingText);

  const tasks = await api.getTasks(project);
  const memberTasks = (tasks || []).filter(
    (t) => t.assignee && t.assignee.toLowerCase() === member.toLowerCase()
  );

  const findMatchingTask = (title) => {
    const clean = title.trim().toLowerCase();
    // 1. Exact match (case-insensitive)
    const exact = memberTasks.find((t) => (t.title || "").trim().toLowerCase() === clean);
    if (exact) return exact;

    // 2. Strict substring match only if title has substantial length (>= 6 chars)
    if (clean.length >= 6) {
      return memberTasks.find((t) => {
        const tLower = (t.title || "").trim().toLowerCase();
        return tLower.length >= 6 && (tLower.includes(clean) || clean.includes(tLower));
      });
    }
    return null;
  };

  const savePromises = [];

  for (const item of doneItems) {
    const match = findMatchingTask(item);
    if (match) {
      if (match.status !== "DONE") {
        match.status = "DONE";
        match.blocker = "";
        savePromises.push(api.saveTask(match));
      }
    } else {
      savePromises.push(api.saveTask({
        project,
        title: item,
        assignee: member,
        status: "DONE",
        priority: "MEDIUM",
        blocker: "",
      }));
    }
  }

  for (const item of doingItems) {
    const match = findMatchingTask(item);
    if (match) {
      if (match.status !== "DOING" && match.status !== "BLOCKED") {
        match.status = "DOING";
        savePromises.push(api.saveTask(match));
      }
    } else {
      savePromises.push(api.saveTask({
        project,
        title: item,
        assignee: member,
        status: "DOING",
        priority: "HIGH",
        blocker: "",
      }));
    }
  }

  if (explicitBlockedTaskId === "__NEW__" && explicitNewBlockedTitle) {
    const reason = (explicitBlockerReason && explicitBlockerReason.toLowerCase() !== "ninguno")
      ? explicitBlockerReason : "Requiere que alguien tome esta tarea en Kanban";
    const createdTask = await api.saveTask({
      project,
      title: explicitNewBlockedTitle,
      assignee: "",
      status: "TODO",
      priority: "HIGH",
      blocker: `Bloquea a ${member}: ${reason}`,
    });
    const myDoing = memberTasks.find((t) => t.status === "DOING");
    if (myDoing && createdTask && createdTask.id) {
      const deps = myDoing.depends_on || [];
      if (!deps.includes(createdTask.id)) deps.push(createdTask.id);
      myDoing.depends_on = deps;
      myDoing.blocked_by_task_id = createdTask.id;
      myDoing.blocked_by_task_title = createdTask.title;
      savePromises.push(api.saveTask(myDoing));
    }
  } else if (explicitBlockedTaskId && explicitBlockedTaskId.startsWith("BLOCKS_ME#")) {
    const targetId = explicitBlockedTaskId.replace("BLOCKS_ME#", "");
    const blockingTask = (tasks || []).find((t) => t.id === targetId);
    if (blockingTask) {
      const reason = (explicitBlockerReason && explicitBlockerReason.toLowerCase() !== "ninguno")
        ? explicitBlockerReason : "Dependencia requerida";
      blockingTask.blocker = `Bloquea a ${member}: ${reason}`;
      savePromises.push(api.saveTask(blockingTask));

      const myDoing = memberTasks.find((t) => t.status === "DOING");
      if (myDoing) {
        const deps = myDoing.depends_on || [];
        if (!deps.includes(targetId)) deps.push(targetId);
        myDoing.depends_on = deps;
        myDoing.blocked_by_task_id = targetId;
        myDoing.blocked_by_task_title = blockingTask.title;
        savePromises.push(api.saveTask(myDoing));
      }
    }
  } else if (explicitBlockedTaskId && (explicitBlockedTaskId.startsWith("MY_TASK#") || explicitBlockedTaskId !== "")) {
    const targetId = explicitBlockedTaskId.replace("MY_TASK#", "");
    const target = memberTasks.find((t) => t.id === targetId);
    if (target) {
      target.status = "BLOCKED";
      target.blocker = (explicitBlockerReason && explicitBlockerReason.toLowerCase() !== "ninguno")
        ? explicitBlockerReason : "Bloqueada";
      savePromises.push(api.saveTask(target));
    }
  }

  if (savePromises.length > 0) {
    await Promise.all(savePromises);
  }
};

export const syncKanbanToDaily = async (project, member) => {
  if (!project || !member) return;
  const week = document.getElementById("boardWeek")?.value || state.activeWeek || "WEEK 1";
  const today = getCurrentDayName();

  const [tasks, scrums] = await Promise.all([
    api.getTasks(project),
    api.getWeeklyScrums(project, week),
  ]);

  const memberTasks = (tasks || []).filter(
    (t) => t.assignee && t.assignee.toLowerCase() === member.toLowerCase()
  );

  const doneTitles = memberTasks.filter((t) => t.status === "DONE").map((t) => t.title);
  const doingTitles = memberTasks.filter((t) => t.status === "DOING").map((t) => t.title);
  const blockedTitles = memberTasks.filter((t) => t.status === "BLOCKED").map((t) => t.blocker ? `[${t.title}] ${t.blocker}` : `[${t.title}] Bloqueada`);

  const existingScrum = (scrums || []).find(
    (s) => s.member && s.member.toLowerCase() === member.toLowerCase() && s.day === today
  );

  let ans1 = doneTitles.length > 0 ? doneTitles.map((t) => `• ${t}`).join("\n") : "";
  let ans2 = doingTitles.length > 0 ? doingTitles.map((t) => `• ${t}`).join("\n") : "";
  let ans3 = blockedTitles.length > 0 ? blockedTitles.map((t) => `• ${t}`).join("\n") : "Ninguno";

  if (existingScrum && existingScrum.answers) {
    const prev1 = existingScrum.answers[0] || "";
    const prev2 = existingScrum.answers[1] || "";
    if (prev1 && !ans1) ans1 = prev1;
    if (prev2 && !ans2) ans2 = prev2;
  }

  const finalAns1 = ans1 || "Sin respuesta";
  const finalAns2 = ans2 || "Sin respuesta";
  const finalAns3 = ans3 || "Ninguno";

  await api.saveScrum(project, week, today, member, [finalAns1, finalAns2, finalAns3]);
  await renderBoard();
};

export const initDailyMatrixListeners = () => {
  scrumModalController = createModalController("scrumModal", "modalClose");

  const btnCancelScrum = document.getElementById("btnCancelScrum");
  if (btnCancelScrum) {
    btnCancelScrum.addEventListener("click", () => scrumModalController.close());
  }

  const blockedSelect = document.getElementById("modalBlockedTaskSelect");
  if (blockedSelect) {
    blockedSelect.addEventListener("change", async (e) => {
      const val = e.target.value;
      const ans3 = document.getElementById("modalAns3");
      const container = document.getElementById("modalNewBlockedTaskTitleContainer");
      const newTitleInput = document.getElementById("modalNewBlockedTaskTitle");

      if (val === "__NEW__") {
        if (container) container.style.display = "block";
        if (newTitleInput) newTitleInput.focus();
        if (ans3 && ans3.value === "Ninguno") ans3.value = "";
      } else if (val === "") {
        if (container) container.style.display = "none";
        if (newTitleInput) newTitleInput.value = "";
      } else if (val.startsWith("BLOCKS_ME#")) {
        if (container) container.style.display = "none";
        if (newTitleInput) newTitleInput.value = "";
        const targetId = val.replace("BLOCKS_ME#", "");
        if (activeScrumContext) {
          const tasks = await api.getTasks(activeScrumContext.project);
          const t = (tasks || []).find((x) => x.id === targetId);
          if (t && ans3) {
            ans3.value = `Esperando resolución de tarea [${t.title}] (${t.assignee || 'Sin asignar en Por Hacer'})`;
          }
        }
      } else if (val.startsWith("MY_TASK#")) {
        if (container) container.style.display = "none";
        if (newTitleInput) newTitleInput.value = "";
        const targetId = val.replace("MY_TASK#", "");
        if (activeScrumContext) {
          const tasks = await api.getTasks(activeScrumContext.project);
          const t = (tasks || []).find((x) => x.id === targetId);
          if (t && t.blocker && ans3) ans3.value = t.blocker;
          else if (t && ans3) ans3.value = `Bloqueo en mi tarea [${t.title}]`;
        }
      }
    });
  }

  const btnSaveScrum = document.getElementById("btnSaveScrum");
  if (btnSaveScrum) {
    btnSaveScrum.addEventListener("click", async () => {
      if (!activeScrumContext) return;
      const { project, week, day, member } = activeScrumContext;
      const blockedTaskId = document.getElementById("modalBlockedTaskSelect")?.value;
      const newBlockedTitle = document.getElementById("modalNewBlockedTaskTitle")?.value.trim();
      const inputBlockerReason = document.getElementById("modalAns3")?.value.trim();

      if (blockedTaskId === "__NEW__" && !newBlockedTitle) {
        showToast("Ingresá el título de la tarea requerida para 'Por Hacer'", "error");
        return;
      }

      btnSaveScrum.disabled = true;
      btnSaveScrum.textContent = "Guardando...";

      try {
        const tasks = await api.getTasks(project);
        const memberTasks = (tasks || []).filter(
          (t) => t.assignee && t.assignee.toLowerCase() === member.toLowerCase()
        );

        const blockerEntries = [];
        memberTasks.filter((t) => t.status === "BLOCKED").forEach((t) => {
          blockerEntries.push(`[${t.title}] ${t.blocker || "Bloqueada"}`);
        });

        let blockingTaskId = "";
        let blockingTaskTitle = "";

        if (blockedTaskId === "__NEW__" && newBlockedTitle) {
          const reason = (inputBlockerReason && inputBlockerReason.toLowerCase() !== "ninguno") ? inputBlockerReason : "Requiere que alguien tome esta tarea";
          blockerEntries.push(`[Esperando: ${newBlockedTitle}] ${reason}`);
          blockingTaskTitle = newBlockedTitle;
        } else if (blockedTaskId && blockedTaskId.startsWith("BLOCKS_ME#")) {
          const targetId = blockedTaskId.replace("BLOCKS_ME#", "");
          const target = (tasks || []).find((t) => t.id === targetId);
          if (target) {
            const reason = (inputBlockerReason && inputBlockerReason.toLowerCase() !== "ninguno") ? inputBlockerReason : "Dependencia requerida";
            blockerEntries.push(`[Esperando: ${target.title}] ${reason}`);
            blockingTaskId = target.id;
            blockingTaskTitle = target.title;
          }
        } else if (blockedTaskId && (blockedTaskId.startsWith("MY_TASK#") || blockedTaskId !== "")) {
          const targetId = blockedTaskId.replace("MY_TASK#", "");
          const target = memberTasks.find((t) => t.id === targetId);
          if (target && target.status !== "BLOCKED") {
            const reason = (inputBlockerReason && inputBlockerReason.toLowerCase() !== "ninguno") ? inputBlockerReason : "Bloqueada";
            blockerEntries.push(`[${target.title}] ${reason}`);
          }
        }

        if (blockerEntries.length === 0 && inputBlockerReason && inputBlockerReason.toLowerCase() !== "ninguno") {
          blockerEntries.push(inputBlockerReason);
        }

        const finalBlockerAns = blockerEntries.length > 0 ? blockerEntries.join("; ") : "Ninguno";
        const answers = [
          document.getElementById("modalAns1")?.value.trim() || "Sin respuesta",
          document.getElementById("modalAns2")?.value.trim() || "Sin respuesta",
          finalBlockerAns,
        ];
        const shouldSync = document.getElementById("syncKanbanOnSave")?.checked;

        await api.saveScrum(project, week, day, member, answers, blockingTaskId, blockingTaskTitle);
        if (shouldSync) {
          await syncDailyToKanban(project, member, answers, blockedTaskId, newBlockedTitle, inputBlockerReason);
        }
        scrumModalController.close();
        await renderBoard();
        if (requestKanbanRender) await requestKanbanRender();
        showToast(`Daily guardada para ${member} (${day}).`);
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btnSaveScrum.disabled = false;
        btnSaveScrum.textContent = "💾 Guardar";
      }
    });
  }

  const btnDeleteScrum = document.getElementById("btnDeleteScrum");
  if (btnDeleteScrum) {
    btnDeleteScrum.addEventListener("click", async () => {
      if (!activeScrumContext) return;
      const { project, week, day, member } = activeScrumContext;
      const ok = await showConfirm("Eliminar Daily", `¿Eliminar la Daily de ${member} del ${day}?`);
      if (!ok) return;

      try {
        await api.deleteScrum(project, week, day, member);
        scrumModalController.close();
        await renderBoard();
        showToast(`Daily eliminada.`);
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  }
};
