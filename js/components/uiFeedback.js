/**
 * Non-intrusive UI Feedback (Toast, Confirm, Prompt Modals)
 */
export const showToast = (message, type = "success", action = null) => {
  const container = document.getElementById("toastContainer");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;

  let timeoutMs = 4000;
  if (action && action.label) {
    timeoutMs = 10000;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = action.label;
    btn.style.cssText = "margin-left:10px;font-weight:800;text-decoration:underline;background:none;border:none;color:inherit;cursor:pointer;font-size:12px;";
    btn.addEventListener("click", async () => {
      try {
        await action.onClick();
      } finally {
        toast.remove();
      }
    });
    toast.appendChild(btn);
  }
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    toast.style.transition = "all 0.2s ease";
    setTimeout(() => toast.remove(), 200);
  }, timeoutMs);
};

export const showConfirm = (title, message) => {
  return new Promise((resolve) => {
    const modal = document.getElementById("confirmModal");
    const titleEl = document.getElementById("confirmTitle");
    const msgEl = document.getElementById("confirmMessage");
    const okBtn = document.getElementById("confirmOkBtn");
    const cancelBtn = document.getElementById("confirmCancelBtn");
    const closeBtn = document.getElementById("confirmClose");

    titleEl.textContent = title || "Confirmar Acción";
    msgEl.textContent = message || "¿Estás seguro?";

    const cleanup = () => {
      modal.classList.remove("open");
      okBtn.onclick = null;
      cancelBtn.onclick = null;
      closeBtn.onclick = null;
    };

    okBtn.onclick = () => { cleanup(); resolve(true); };
    cancelBtn.onclick = () => { cleanup(); resolve(false); };
    closeBtn.onclick = () => { cleanup(); resolve(false); };

    modal.classList.add("open");
  });
};

export const showPrompt = ({ title, label, initialValue = "", secondLabel = "", secondInitialValue = "" }) => {
  return new Promise((resolve) => {
    const modal = document.getElementById("promptModal");
    const titleEl = document.getElementById("promptTitle");
    const labelEl = document.getElementById("promptLabel");
    const inputEl = document.getElementById("promptInput");
    const secondGroup = document.getElementById("promptSecondGroup");
    const secondLabelEl = document.getElementById("promptSecondLabel");
    const secondInputEl = document.getElementById("promptSecondInput");
    const okBtn = document.getElementById("promptOkBtn");
    const cancelBtn = document.getElementById("promptCancelBtn");
    const closeBtn = document.getElementById("promptClose");

    titleEl.textContent = title || "Ingresar Dato";
    labelEl.textContent = label || "Valor:";
    inputEl.value = initialValue;

    if (secondLabel) {
      secondGroup.style.display = "block";
      secondLabelEl.textContent = secondLabel;
      secondInputEl.value = secondInitialValue;
    } else {
      secondGroup.style.display = "none";
      secondInputEl.value = "";
    }

    const cleanup = () => {
      modal.classList.remove("open");
      okBtn.onclick = null;
      cancelBtn.onclick = null;
      closeBtn.onclick = null;
    };

    okBtn.onclick = () => {
      const val1 = inputEl.value;
      const val2 = secondInputEl.value;
      cleanup();
      resolve(secondLabel ? { value: val1, secondValue: val2 } : { value: val1 });
    };

    cancelBtn.onclick = () => { cleanup(); resolve(null); };
    closeBtn.onclick = () => { cleanup(); resolve(null); };

    modal.classList.add("open");
    setTimeout(() => inputEl.focus(), 100);
  });
};
