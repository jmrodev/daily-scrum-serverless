/**
 * Application Entry Point & Module Coordinator
 * Enforces mandatory authentication gate before initializing boards or data queries.
 */
import { state } from "./state.js";
import { api } from "./services/api.js";
import { initTheme } from "./components/header.js";
import { enforceAuthGate, initAuthGateListeners } from "./components/authGate.js";
import { initWeekSelector, initWeekSelectorListeners } from "./components/weekSelector.js";
import { renderBoard, initDailyMatrixListeners, setDailyMatrixCallbacks } from "./components/dailyMatrix.js";
import { renderKanban, initKanbanListeners } from "./components/kanbanBoard.js";
import { initAdminModalListeners, setAdminModalRefreshCallback, loadManageModal } from "./components/adminModal.js";

export const switchMainView = async (view) => {
  state.currentMainView = view;
  const tabDaily = document.getElementById("tabDailyView");
  const tabKanban = document.getElementById("tabKanbanView");
  const dailyContainer = document.getElementById("dailyViewContainer");
  const kanbanContainer = document.getElementById("kanbanViewContainer");
  const weekGroup = document.getElementById("weekFilterGroup");

  if (view === "daily") {
    tabDaily?.classList.add("active");
    tabKanban?.classList.remove("active");
    if (dailyContainer) dailyContainer.style.display = "block";
    if (kanbanContainer) kanbanContainer.style.display = "none";
    if (weekGroup) weekGroup.style.display = "block";
    await renderBoard();
  } else {
    tabDaily?.classList.remove("active");
    tabKanban?.classList.add("active");
    if (dailyContainer) dailyContainer.style.display = "none";
    if (kanbanContainer) kanbanContainer.style.display = "block";
    if (weekGroup) weekGroup.style.display = "none";
    await renderKanban();
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
  } else {
    await renderKanban();
  }
};

export const refreshCurrentView = async () => {
  if (state.currentMainView === "daily") {
    await renderBoard();
  } else {
    await renderKanban();
  }
};

/**
 * Bootstraps the application once authentication is confirmed.
 */
const startAuthenticatedApp = async () => {
  await initProjectSelectors();
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

  // 5. Board Filter Listeners
  const boardProject = document.getElementById("boardProject");
  if (boardProject) {
    boardProject.addEventListener("change", async () => {
      state.activeProject = boardProject.value;
      await initWeekSelector(boardProject.value);
      await refreshCurrentView();
    });
  }

  const btnRefresh = document.getElementById("btnRefreshBoard");
  if (btnRefresh) {
    btnRefresh.addEventListener("click", refreshCurrentView);
  }

  // 6. ENFORCE MANDATORY AUTH GATE:
  // If not logged in, NO board data is requested. Only the login screen is displayed!
  enforceAuthGate(startAuthenticatedApp);
});
