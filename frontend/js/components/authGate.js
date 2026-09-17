/**
 * Mandatory Auth Gate Controller
 * Ensures NO data access or board rendering without authenticated login.
 */
import { AUTH_STORAGE_KEY } from "../config.js";
import { state, setCurrentUser } from "../state.js";
import { api } from "../services/api.js";
import { showToast } from "./uiFeedback.js";
import { updateHeaderUI } from "./header.js";

let onAuthSuccessCallback = null;

export const getStoredAuth = () => {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
};

export const saveStoredAuth = (session) => {
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
};

export const clearStoredAuth = () => {
  localStorage.removeItem(AUTH_STORAGE_KEY);
};

export const switchAuthTab = (tab) => {
  const tabs = ["login", "signup", "confirm"];
  tabs.forEach((t) => {
    const btn = document.getElementById(`authTabBtn${t.charAt(0).toUpperCase() + t.slice(1)}`);
    const form = document.getElementById(`${t}Form`);
    if (btn) btn.classList.toggle("active", t === tab);
    if (form) form.style.display = t === tab ? "block" : "none";
  });
};

export const enforceAuthGate = (onSuccess) => {
  onAuthSuccessCallback = onSuccess;
  const stored = getStoredAuth();

  const authGateEl = document.getElementById("authGate");
  const appShellEl = document.getElementById("appShell");

  if (stored && stored.user) {
    // Authenticated session exists
    setCurrentUser(stored.user);
    if (stored.token) state.currentUser.token = stored.token;

    authGateEl.style.display = "none";
    appShellEl.style.display = "block";
    updateHeaderUI();

    if (typeof onAuthSuccessCallback === "function") {
      onAuthSuccessCallback();
    }
  } else {
    // Unauthenticated: Hard Gate
    setCurrentUser(null);
    authGateEl.style.display = "flex";
    appShellEl.style.display = "none";
    updateHeaderUI();
    // Zero data fetching triggered!
  }
};

export const initAuthGateListeners = () => {
  // Tab Switchers
  const btnTabLogin = document.getElementById("authTabBtnLogin");
  const btnTabSignup = document.getElementById("authTabBtnSignup");
  const btnTabConfirm = document.getElementById("authTabBtnConfirm");

  if (btnTabLogin) btnTabLogin.addEventListener("click", () => switchAuthTab("login"));
  if (btnTabSignup) btnTabSignup.addEventListener("click", () => switchAuthTab("signup"));
  if (btnTabConfirm) btnTabConfirm.addEventListener("click", () => switchAuthTab("confirm"));

  const linkToSignup = document.getElementById("authLinkToSignup");
  if (linkToSignup) linkToSignup.addEventListener("click", () => switchAuthTab("signup"));

  const linkToLogin = document.getElementById("authLinkToLogin");
  if (linkToLogin) linkToLogin.addEventListener("click", () => switchAuthTab("login"));

  const linkToConfirm = document.getElementById("authLinkToConfirm");
  if (linkToConfirm) linkToConfirm.addEventListener("click", () => switchAuthTab("confirm"));

  const linkConfirmBackToLogin = document.getElementById("authLinkConfirmBackToLogin");
  if (linkConfirmBackToLogin) linkConfirmBackToLogin.addEventListener("click", () => switchAuthTab("login"));

  // Login Submit
  const btnSubmitLogin = document.getElementById("btnSubmitLogin");
  if (btnSubmitLogin) {
    btnSubmitLogin.addEventListener("click", async () => {
      const email = document.getElementById("loginEmail").value.trim();
      const password = document.getElementById("loginPassword").value;

      if (!email || !password) {
        showToast("Completá tu correo y contraseña.", "error");
        return;
      }

      btnSubmitLogin.disabled = true;
      btnSubmitLogin.textContent = "Ingresando...";

      try {
        const res = await api.login(email, password);
        saveStoredAuth(res);
        setCurrentUser(res.user);
        if (res.token) state.currentUser.token = res.token;

        showToast(`¡Bienvenido/a, ${state.currentUser.name}!`);

        // Unlock App Shell
        document.getElementById("authGate").style.display = "none";
        document.getElementById("appShell").style.display = "block";
        updateHeaderUI();

        // Trigger authenticated data loading
        if (typeof onAuthSuccessCallback === "function") {
          onAuthSuccessCallback();
        }
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btnSubmitLogin.disabled = false;
        btnSubmitLogin.textContent = "Ingresar";
      }
    });
  }

  // Signup Submit
  const btnSubmitSignup = document.getElementById("btnSubmitSignup");
  if (btnSubmitSignup) {
    btnSubmitSignup.addEventListener("click", async () => {
      const name = document.getElementById("signupName").value.trim();
      const email = document.getElementById("signupEmail").value.trim();
      const password = document.getElementById("signupPassword").value;

      if (!name || !email || !password) {
        showToast("Completá todos los campos.", "error");
        return;
      }
      if (password.length < 8) {
        showToast("La contraseña debe tener al menos 8 caracteres.", "error");
        return;
      }

      btnSubmitSignup.disabled = true;
      btnSubmitSignup.textContent = "Creando cuenta...";

      try {
        const res = await api.signup(email, password, name);
        showToast(res.message || "Cuenta creada. Revisá tu email para el código de activación.");

        // Switch to confirm tab with email pre-filled
        const confirmEmailInput = document.getElementById("confirmEmail");
        if (confirmEmailInput) confirmEmailInput.value = email;
        switchAuthTab("confirm");
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btnSubmitSignup.disabled = false;
        btnSubmitSignup.textContent = "Crear Cuenta";
      }
    });
  }

  // Confirm Submit
  const btnSubmitConfirm = document.getElementById("btnSubmitConfirm");
  if (btnSubmitConfirm) {
    btnSubmitConfirm.addEventListener("click", async () => {
      const email = document.getElementById("confirmEmail").value.trim();
      const code = document.getElementById("confirmCode").value.trim();

      if (!email || !code) {
        showToast("Ingresá el correo y el código de 6 dígitos.", "error");
        return;
      }

      btnSubmitConfirm.disabled = true;
      btnSubmitConfirm.textContent = "Verificando...";

      try {
        const res = await api.confirm(email, code);
        showToast(res.message || "Cuenta verificada con éxito. Ya podés iniciar sesión.");

        // Switch to login tab with email pre-filled
        const loginEmailInput = document.getElementById("loginEmail");
        if (loginEmailInput) loginEmailInput.value = email;
        switchAuthTab("login");
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btnSubmitConfirm.disabled = false;
        btnSubmitConfirm.textContent = "Verificar Cuenta";
      }
    });
  }

  // Logout Handler
  const btnLogout = document.getElementById("btnLogout");
  if (btnLogout) {
    btnLogout.addEventListener("click", () => {
      clearStoredAuth();
      setCurrentUser(null);

      // Lock App Shell
      document.getElementById("appShell").style.display = "none";
      document.getElementById("authGate").style.display = "flex";

      // Clear table and kanban in DOM so nothing is leaked
      const tbody = document.getElementById("scrumTableBody");
      if (tbody) tbody.innerHTML = "";
      ["TODO", "DOING", "BLOCKED", "DONE"].forEach((st) => {
        const col = document.getElementById(`col${st}`);
        if (col) col.innerHTML = "";
      });

      updateHeaderUI();
      switchAuthTab("login");
      showToast("Sesión cerrada.");
    });
  }
};
