/**
 * DOM Utilities & Modal Helpers
 */
export const escapeHtml = (str) => {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
};

export const createModalController = (modalId, closeBtnId) => {
  const el = document.getElementById(modalId);
  const closeBtn = closeBtnId ? document.getElementById(closeBtnId) : null;

  const controller = {
    el,
    open: () => {
      if (el) el.classList.add("open");
    },
    close: () => {
      if (el) el.classList.remove("open");
    },
  };

  if (closeBtn) {
    closeBtn.addEventListener("click", controller.close);
  }

  if (el) {
    el.addEventListener("click", (e) => {
      if (e.target === el) controller.close();
    });
  }

  return controller;
};
