/**
 * Header & App Navigation Component
 */
import { THEME_STORAGE_KEY } from "../config.js";
import { state, isAdmin } from "../state.js";
import { redoLast, subscribeUndoState, undoLast } from "../services/undoService.js";

export const getPreferredTheme = () => {
  const saved = localStorage.getItem(THEME_STORAGE_KEY);
  if (saved) return saved;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
};

export const applyTheme = (theme) => {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(THEME_STORAGE_KEY, theme);

  const themeBtns = document.querySelectorAll(".btn-theme-toggle");
  themeBtns.forEach((btn) => {
    btn.textContent = theme === "dark" ? "☀️ Claro" : "🌙 Oscuro";
  });
};

export const initTheme = () => {
  const initialTheme = getPreferredTheme();
  applyTheme(initialTheme);

  const themeBtns = document.querySelectorAll(".btn-theme-toggle");
  themeBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || "light";
      applyTheme(current === "dark" ? "light" : "dark");
    });
  });
};

export const initUndoButtons = () => {
  const btnUndo = document.getElementById("btnUndo");
  const btnRedo = document.getElementById("btnRedo");
  if (!btnUndo || !btnRedo || btnUndo.dataset.bound) return;
  btnUndo.dataset.bound = "true";

  const paint = ({ canUndo, canRedo }) => {
    btnUndo.disabled = !canUndo;
    btnUndo.style.opacity = canUndo ? "1" : "0.45";
    btnRedo.disabled = !canRedo;
    btnRedo.style.opacity = canRedo ? "1" : "0.45";
  };
  btnUndo.addEventListener("click", () => undoLast());
  btnRedo.addEventListener("click", () => redoLast());
  subscribeUndoState(paint);
  paint({ canUndo: false, canRedo: false });
};

export const updateHeaderUI = () => {
  const authUserBadge = document.getElementById("authUserBadge");
  const btnOpenManageModal = document.getElementById("btnOpenManageModal");
  const btnLogout = document.getElementById("btnLogout");
  const tabDiagnosticsView = document.getElementById("tabDiagnosticsView");
  const btnAddWeek = document.getElementById("btnAddWeek");

  if (!authUserBadge) return;

  if (state.currentUser && state.currentUser.email) {
    authUserBadge.style.display = "inline-flex";
    const roleLabel = state.currentUser.role === "admin" ? "Admin" : "Dev";
    authUserBadge.textContent = `👤 ${state.currentUser.name} (${roleLabel})`;

    const admin = isAdmin();
    if (btnOpenManageModal) {
      btnOpenManageModal.style.display = admin ? "inline-flex" : "none";
    }
    if (tabDiagnosticsView) {
      tabDiagnosticsView.style.display = admin ? "inline-block" : "none";
    }
    if (btnAddWeek) {
      btnAddWeek.style.display = admin ? "inline-block" : "none";
    }
    if (btnLogout) {
      btnLogout.style.display = "inline-flex";
    }
  } else {
    authUserBadge.style.display = "none";
    if (btnOpenManageModal) btnOpenManageModal.style.display = "none";
    if (tabDiagnosticsView) tabDiagnosticsView.style.display = "none";
    if (btnAddWeek) btnAddWeek.style.display = "none";
    if (btnLogout) btnLogout.style.display = "none";
  }
};
