/**
 * Application Entry Point & Module Coordinator
 * Enforces mandatory authentication gate before initializing boards or data queries.
 */
import { state, isAdmin } from "./state.js";
import { api } from "./services/api.js";
import { initTheme, updateHeaderUI } from "./components/header.js";
import { showToast } from "./components/uiFeedback.js";
import { enforceAuthGate, initAuthGateListeners } from "./components/authGate.js";
import { initWeekSelector, initWeekSelectorListeners } from "./components/weekSelector.js";
import { renderBoard, initDailyMatrixListeners, setDailyMatrixCallbacks } from "./components/dailyMatrix.js";
import { renderKanban, initKanbanListeners } from "./components/kanbanBoard.js";
import { renderDiagnosticsView } from "./components/diagnosticsView.js";
import { initAdminModalListeners, setAdminModalRefreshCallback, loadManageModal } from "./components/adminModal.js";
import { startSyncService, stopSyncService } from "./services/syncService.js";

export const switchMainView = async (view) => {
  if (view === "diagnostics" && !isAdmin()) {
    showToast("Acceso a PERT/CPM y Diagnóstico exclusivo para administradores.", "error");
    view = "daily";
  }
  state.currentMainView = view;
  const tabDaily = document.getElementById("tabDailyView");
  const tabKanban = document.getElementById("tabKanbanView");
  const tabDiagnostics = document.getElementById("tabDiagnosticsView");
  const dailyContainer = document.getElementById("dailyViewContainer");
  const kanbanContainer = document.getElementById("kanbanViewContainer");
  const diagnosticsContainer = document.getElementById("diagnosticsViewContainer");
  const weekGroup = document.getElementById("weekFilterGroup");

  tabDaily?.classList.toggle("active", view === "daily");
  tabKanban?.classList.toggle("active", view === "kanban");
  tabDiagnostics?.classList.toggle("active", view === "diagnostics");

  if (dailyContainer) dailyContainer.style.display = view === "daily" ? "block" : "none";
  if (kanbanContainer) kanbanContainer.style.display = view === "kanban" ? "block" : "none";
  if (diagnosticsContainer) diagnosticsContainer.style.display = view === "diagnostics" ? "block" : "none";

  if (weekGroup) weekGroup.style.display = view === "kanban" ? "none" : "block";

  if (view === "daily") {
    await renderBoard();
  } else if (view === "kanban") {
    await renderKanban();
  } else if (view === "diagnostics") {
    await renderDiagnosticsView();
  }
};

export const initProjectSelectors = async () => {
  const projects = await api.getProjects();
  const boardSelect = document.getElementById("boardProject");
  if (!boardSelect) return;

  const prev = boardSelect.value;
  boardSelect.innerHTML = "";

  projects.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.name;
    opt.textContent = p.name;
    if (p.name === prev) opt.selected = true;
    boardSelect.appendChild(opt);
  });

  if (!boardSelect.value && projects.length > 0) {
    boardSelect.value = projects[0].name;
  }
  state.activeProject = boardSelect.value;

  if (boardSelect.value) {
    await initWeekSelector(boardSelect.value);
  }

  if (state.currentMainView === "daily") {
    await renderBoard();
  } else if (state.currentMainView === "kanban") {
    await renderKanban();
  } else if (state.currentMainView === "diagnostics") {
    await renderDiagnosticsView();
  }
};

export const refreshCurrentView = async (silent = false) => {
  if (state.currentMainView === "daily") {
    await renderBoard(silent);
  } else if (state.currentMainView === "kanban") {
    await renderKanban(silent);
  } else if (state.currentMainView === "diagnostics") {
    await renderDiagnosticsView(null, null, silent);
  }
};

/**
 * Bootstraps the application once authentication is confirmed.
 */
const startAuthenticatedApp = async () => {
  updateHeaderUI();
  if (!isAdmin() && state.currentMainView === "diagnostics") {
    state.currentMainView = "daily";
  }
  await initProjectSelectors();
  startSyncService(refreshCurrentView);
};

// Global App Initialization
document.addEventListener("DOMContentLoaded", () => {
  // 1. Initialize Theme (runs unauthenticated so dark/light is respected)
  initTheme();

  // 2. Register Cross-Component Callbacks
  setDailyMatrixCallbacks({
    onRenderKanban: renderKanban,
    onReloadAdminModal: loadManageModal,
  });
  setAdminModalRefreshCallback(refreshCurrentView);

  // 3. Attach UI Component Listeners
  initAuthGateListeners();
  initDailyMatrixListeners();
  initKanbanListeners();
  initAdminModalListeners();
  initWeekSelectorListeners(refreshCurrentView);

  // 4. View Switcher Tabs
  document.getElementById("tabDailyView")?.addEventListener("click", () => switchMainView("daily"));
  document.getElementById("tabKanbanView")?.addEventListener("click", () => switchMainView("kanban"));
  document.getElementById("tabDiagnosticsView")?.addEventListener("click", () => switchMainView("diagnostics"));

  // 5. Board Filter Listeners
  const boardProject = document.getElementById("boardProject");
  if (boardProject) {
    boardProject.addEventListener("change", async () => {
      state.activeProject = boardProject.value;
      await initWeekSelector(boardProject.value);
      await refreshCurrentView();
    });
  }

  // 6. ENFORCE MANDATORY AUTH GATE:
  // If not logged in, NO board data is requested. Only the login screen is displayed!
  enforceAuthGate(startAuthenticatedApp);
});
