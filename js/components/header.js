/**
 * Header & App Navigation Component
 */
import { THEME_STORAGE_KEY } from "../config.js";
import { state, isAdmin } from "../state.js";

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

export const updateHeaderUI = () => {
  const authUserBadge = document.getElementById("authUserBadge");
  const btnOpenManageModal = document.getElementById("btnOpenManageModal");
  const btnLogout = document.getElementById("btnLogout");

  if (!authUserBadge) return;

  if (state.currentUser && state.currentUser.email) {
    authUserBadge.style.display = "inline-flex";
    const roleLabel = state.currentUser.role === "admin" ? "Admin" : "Dev";
    authUserBadge.textContent = `👤 ${state.currentUser.name} (${roleLabel})`;

    if (btnOpenManageModal) {
      btnOpenManageModal.style.display = isAdmin() ? "inline-flex" : "none";
    }
    if (btnLogout) {
      btnLogout.style.display = "inline-flex";
    }
  } else {
    authUserBadge.style.display = "none";
    if (btnOpenManageModal) btnOpenManageModal.style.display = "none";
    if (btnLogout) btnLogout.style.display = "none";
  }
};
