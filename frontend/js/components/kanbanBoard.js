/**
 * Kanban Board Component
 * 4-column flow (TODO, DOING, BLOCKED, DONE) with drag-and-drop & Daily bridge.
 */
import { KANBAN_STATUSES } from "../config.js";
import { state, isAdmin } from "../state.js";
import { api } from "../services/api.js";
import { getStatusLabel, getCurrentDayName } from "../services/dateUtils.js";
import { escapeHtml, createModalController } from "../services/domUtils.js";
import { showToast, showPrompt, showConfirm } from "./uiFeedback.js";
import { syncKanbanToDaily } from "./dailyMatrix.js";

let taskModalController = null;
let draggedTaskId = null;

const getNextStatus = (current) => {
  const idx = KANBAN_STATUSES.indexOf(current);
  return idx < KANBAN_STATUSES.length - 1 ? KANBAN_STATUSES[idx + 1] : null;
};

const getPrevStatus = (current) => {
  const idx = KANBAN_STATUSES.indexOf(current);
  return idx > 0 ? KANBAN_STATUSES[idx - 1] : null;
};

export const renderKanban = async () => {
  const project = document.getElementById("boardProject")?.value || state.activeProject;
  if (!project) return;
  const week = document.getElementById("boardWeek")?.value || state.activeWeek || "WEEK 1";

  KANBAN_STATUSES.forEach((st) => {
    const colList = document.getElementById(`col${st}`);
    const countBadge = document.getElementById(`count${st}`);
    if (colList) colList.innerHTML = `<div style="text-align:center; padding:16px; color:var(--text-muted); font-size:12px;">Cargando...</div>`;
    if (countBadge) countBadge.textContent = "0";
  });

  const [tasks, scrums] = await Promise.all([
    api.getTasks(project),
    api.getWeeklyScrums(project, week),
  ]);
  state.currentLoadedTasks = tasks || [];

  const statusMap = { TODO: [], DOING: [], BLOCKED: [], DONE: [] };
  tasks.forEach((t) => {
    const st = statusMap[t.status] ? t.status : "TODO";
    statusMap[st].push(t);
  });

  KANBAN_STATUSES.forEach((st) => {
    const colList = document.getElementById(`col${st}`);
    const countBadge = document.getElementById(`count${st}`);
    const list = statusMap[st];
    if (countBadge) countBadge.textContent = list.length;
    if (!colList) return;

    if (list.length === 0) {
      colList.innerHTML = `<div style="text-align:center; padding:24px 8px; color:var(--text-muted); font-size:11px; border: 1px dashed var(--border); border-radius: 6px;">Sin tareas</div>`;
      return;
    }

    colList.innerHTML = "";
    list.forEach((t) => {
      const card = document.createElement("div");
      card.className = "kanban-card";
      const isSelf = state.currentUser.name && t.assignee && (t.assignee.toLowerCase() === state.currentUser.name.toLowerCase());
      const canManageTask = isAdmin() || isSelf || !t.assignee;
      const prevStatus = getPrevStatus(t.status);
      const nextStatus = getNextStatus(t.status);

      const prioClass = (t.priority || "medium").toLowerCase();
      const prioLabel = t.priority === "HIGH" ? "Alta" : (t.priority === "LOW" ? "Baja" : "Media");

      if (canManageTask) {
        card.draggable = true;
        card.ondragstart = (e) => handleDragStart(e, t.id);
        card.ondragend = handleDragEnd;
      } else {
        card.draggable = false;
        card.classList.add("readonly");
        card.setAttribute("title", `Tarea asignada a ${t.assignee} (Solo lectura)`);
      }

      const isMentionedInDaily = (scrums || []).some((s) => {
        if (!s.answers || !t.assignee) return false;
        if (s.member.toLowerCase() !== t.assignee.toLowerCase()) return false;
        const fullAnswers = s.answers.join(" ").toLowerCase();
        const taskTitle = (t.title || "").toLowerCase().trim();
        return taskTitle.length > 2 && (fullAnswers.includes(taskTitle) || (t.blocker && fullAnswers.includes(t.blocker.toLowerCase())));
      });

      card.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
          <div style="display: flex; align-items: center; gap: 4px; flex-wrap: wrap;">
            <span class="priority-badge ${prioClass}">${prioLabel}</span>
            ${isMentionedInDaily ? '<span class="badge-in-daily" title="Reportada en el Daily Scrum de esta semana">📅 En Daily</span>' : ''}
          </div>
          ${canManageTask ? `<button type="button" class="btn-action btn-edit-task" title="Editar Tarea" style="font-size: 11px;">✏️</button>` : `<span class="badge-readonly" title="Solo editable por ${escapeHtml(t.assignee)}">🔒</span>`}
        </div>
        <div class="kanban-card-title">${escapeHtml(t.title)}</div>
        ${t.status === "BLOCKED" && t.blocker ? `
          <div class="kanban-card-blocker">🚨 ${escapeHtml(t.blocker)}</div>
        ` : ''}
        <div class="kanban-card-footer">
          <span class="kanban-assignee">
            👤 ${escapeHtml(t.assignee || "Sin Asignar")}
            ${isSelf ? '<span class="member-cell-self" style="font-size:8px;">TÚ</span>' : ''}
            ${!t.assignee ? `<button type="button" class="btn-claim-task" title="Asignarme esta tarea para resolverla">🙋‍♂️ Tomar</button>` : ''}
          </span>
          <div class="kanban-nav-btns">
            ${canManageTask ? `
              ${prevStatus ? `<button type="button" class="kanban-nav-btn btn-prev-status" title="Mover a ${getStatusLabel(prevStatus)}">◀</button>` : ''}
              ${nextStatus ? `<button type="button" class="kanban-nav-btn btn-next-status" title="Mover a ${getStatusLabel(nextStatus)}">▶</button>` : ''}
            ` : `<span style="font-size:10px; color:var(--text-muted);" title="Solo editable por ${escapeHtml(t.assignee)}">🔒 Asignada</span>`}
          </div>
        </div>
      `;

      if (canManageTask) {
        card.querySelector(".btn-edit-task")?.addEventListener("click", () => openEditTaskModal(t.id));
        if (prevStatus) {
          card.querySelector(".btn-prev-status")?.addEventListener("click", () => moveTaskStatus(t.id, prevStatus));
        }
        if (nextStatus) {
          card.querySelector(".btn-next-status")?.addEventListener("click", () => moveTaskStatus(t.id, nextStatus));
        }
      }

      if (!t.assignee) {
        card.querySelector(".btn-claim-task")?.addEventListener("click", () => claimTaskAction(t.id));
      }

      colList.appendChild(card);
    });
  });
};

export const handleDragStart = (e, taskId) => {
  if (state.currentLoadedTasks && state.currentLoadedTasks.length) {
    const task = state.currentLoadedTasks.find((t) => t.id === taskId);
    if (task && task.assignee) {
      const isOwner = state.currentUser.name && (task.assignee.toLowerCase() === state.currentUser.name.toLowerCase());
      const canDrag = isAdmin() || isOwner;
      if (!canDrag) {
        e.preventDefault();
        showToast(`Solo podés mover tus propias tareas (${task.assignee})`, "error");
        return;
      }
    }
  }
  draggedTaskId = taskId;
  e.dataTransfer.setData("text/plain", taskId);
  e.target.classList.add("dragging");
};

export const handleDragEnd = (e) => {
  e.target.classList.remove("dragging");
  document.querySelectorAll(".kanban-col").forEach((col) => col.classList.remove("drag-over"));
};

export const handleDragOver = (e) => {
  e.preventDefault();
  const col = e.currentTarget;
  col.classList.add("drag-over");
};

export const handleDragLeave = (e) => {
  const col = e.currentTarget;
  col.classList.remove("drag-over");
};

export const handleDrop = async (e, targetStatus) => {
  e.preventDefault();
  const col = e.currentTarget;
  col.classList.remove("drag-over");
  const taskId = e.dataTransfer.getData("text/plain") || draggedTaskId;
  if (!taskId) return;
  await moveTaskStatus(taskId, targetStatus);
};

export const moveTaskStatus = async (taskId, nextStatus) => {
  const project = document.getElementById("boardProject")?.value || state.activeProject;
  if (!project) return;
  const tasks = await api.getTasks(project);
  const task = tasks.find((t) => t.id === taskId);
  if (!task) return;

  const isSelf = state.currentUser.name && task.assignee && (task.assignee.toLowerCase() === state.currentUser.name.toLowerCase());
  const canManage = isAdmin() || isSelf || !task.assignee;
  if (!canManage) {
    showToast(`Solo podés mover tus propias tareas (Asignada a ${task.assignee})`, "error");
    return;
  }

  if (nextStatus === "BLOCKED" && !task.blocker) {
    const res = await showPrompt({
      title: "🚨 Registrar Bloqueo",
      label: "Motivo o impedimento que traba la tarea:",
      initialValue: "Esperando dependencias",
    });
    if (res === null) return;
    task.blocker = res.value.trim() || "Bloqueo no especificado";
  } else if (nextStatus !== "BLOCKED") {
    task.blocker = "";
  }

  task.status = nextStatus;
  await api.saveTask(task);
  if (task.assignee) {
    await syncKanbanToDaily(project, task.assignee);
  }
  showToast(`Tarea movida a ${getStatusLabel(nextStatus)} y sincronizada con Daily (${getCurrentDayName()}).`);
  await renderKanban();
};

export const claimTaskAction = async (taskId) => {
  const project = document.getElementById("boardProject")?.value || state.activeProject;
  if (!project || !state.currentUser.name) return;
  try {
    const tasks = await api.getTasks(project);
    const task = tasks.find((t) => t.id === taskId);
    if (!task) return;

    task.assignee = state.currentUser.name;
    if (task.status === "TODO") task.status = "DOING";
    await api.saveTask(task);
    await syncKanbanToDaily(project, state.currentUser.name);
    await renderKanban();
    showToast(`¡Tomaste la tarea '${task.title}'! Ahora está asignada a vos y en progreso.`);
  } catch (err) {
    showToast(err.message, "error");
  }
};

export const openNewTaskModal = async () => {
  const project = document.getElementById("boardProject")?.value || state.activeProject;
  if (!project) return;

  document.getElementById("taskModalTitle").textContent = "➕ Nueva Tarea de Kanban";
  document.getElementById("taskId").value = "";
  document.getElementById("taskTitle").value = "";
  document.getElementById("taskStatus").value = "TODO";
  document.getElementById("taskPriority").value = "MEDIUM";
  document.getElementById("taskBlocker").value = "";
  document.getElementById("taskBlockerGroup").style.display = "none";
  document.getElementById("btnDeleteTask").style.display = "none";

  await populateAssigneeSelect(project);

  const assigneeSelect = document.getElementById("taskAssignee");
  if (assigneeSelect && state.currentUser.name) {
    assigneeSelect.value = state.currentUser.name;
  }

  taskModalController.open();
};

export const openEditTaskModal = async (taskId) => {
  const project = document.getElementById("boardProject")?.value || state.activeProject;
  if (!project) return;
  const tasks = await api.getTasks(project);
  const task = tasks.find((t) => t.id === taskId);
  if (!task) return;

  document.getElementById("taskModalTitle").textContent = "✏️ Editar Tarea de Kanban";
  document.getElementById("taskId").value = task.id;
  document.getElementById("taskTitle").value = task.title;
  document.getElementById("taskStatus").value = task.status;
  document.getElementById("taskPriority").value = task.priority || "MEDIUM";
  document.getElementById("taskBlocker").value = task.blocker || "";
  document.getElementById("taskBlockerGroup").style.display = task.status === "BLOCKED" ? "block" : "none";
  document.getElementById("btnDeleteTask").style.display = "inline-flex";

  await populateAssigneeSelect(project, task.assignee);
  taskModalController.open();
};

const populateAssigneeSelect = async (project, selected = "") => {
  const select = document.getElementById("taskAssignee");
  if (!select) return;
  select.innerHTML = '<option value="">(Sin Asignar)</option>';

  const members = await api.getMembers(project);
  members.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m.name;
    opt.textContent = `${m.name} (${m.role || "Developer"})`;
    if (m.name === selected) opt.selected = true;
    select.appendChild(opt);
  });
};

export const initKanbanListeners = () => {
  taskModalController = createModalController("taskModal", "taskModalClose");

  const btnOpenNewTaskModal = document.getElementById("btnOpenNewTaskModal");
  if (btnOpenNewTaskModal) {
    btnOpenNewTaskModal.addEventListener("click", openNewTaskModal);
  }

  const btnCancelTask = document.getElementById("btnCancelTask");
  if (btnCancelTask) {
    btnCancelTask.addEventListener("click", () => taskModalController.close());
  }

  const taskStatusSelect = document.getElementById("taskStatus");
  if (taskStatusSelect) {
    taskStatusSelect.addEventListener("change", (e) => {
      const blockerGroup = document.getElementById("taskBlockerGroup");
      if (blockerGroup) blockerGroup.style.display = e.target.value === "BLOCKED" ? "block" : "none";
    });
  }

  // Setup Column Drag & Drop Listeners
  KANBAN_STATUSES.forEach((st) => {
    const col = document.getElementById(`col${st}`)?.parentElement;
    if (col) {
      col.addEventListener("dragover", handleDragOver);
      col.addEventListener("dragleave", handleDragLeave);
      col.addEventListener("drop", (e) => handleDrop(e, st));
    }
  });

  const btnSaveTask = document.getElementById("btnSaveTask");
  if (btnSaveTask) {
    btnSaveTask.addEventListener("click", async () => {
      const project = document.getElementById("boardProject")?.value || state.activeProject;
      if (!project) return;

      const title = document.getElementById("taskTitle").value.trim();
      if (!title) {
        showToast("El título de la tarea es obligatorio", "error");
        return;
      }

      const id = document.getElementById("taskId").value;
      const status = document.getElementById("taskStatus").value;
      const priority = document.getElementById("taskPriority").value;
      const assignee = document.getElementById("taskAssignee").value;
      const blocker = status === "BLOCKED" ? document.getElementById("taskBlocker").value.trim() : "";

      const task = {
        project,
        title,
        status,
        priority,
        assignee,
        blocker,
      };
      if (id) task.id = id;

      btnSaveTask.disabled = true;
      btnSaveTask.textContent = "Guardando...";

      try {
        await api.saveTask(task);
        if (assignee) {
          await syncKanbanToDaily(project, assignee);
        }
        taskModalController.close();
        await renderKanban();
        showToast(id ? "Tarea actualizada." : "Tarea creada.");
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btnSaveTask.disabled = false;
        btnSaveTask.textContent = "💾 Guardar Tarea";
      }
    });
  }

  const btnDeleteTask = document.getElementById("btnDeleteTask");
  if (btnDeleteTask) {
    btnDeleteTask.addEventListener("click", async () => {
      const project = document.getElementById("boardProject")?.value || state.activeProject;
      const id = document.getElementById("taskId").value;
      if (!project || !id) return;

      const ok = await showConfirm("Eliminar Tarea", "¿Estás seguro de eliminar esta tarea?");
      if (!ok) return;

      try {
        await api.deleteTask(project, id);
        taskModalController.close();
        await renderKanban();
        showToast("Tarea eliminada.");
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  }
};
