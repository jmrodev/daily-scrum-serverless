/**
 * Auth Gate Controller: classic login-first card (email + password together),
 * with register and code-activation as secondary paths. No tabs, no identify
 * round-trip: one login attempt routes everywhere (enter / activate / create).
 * Invite links (?action=activate&email&code) land straight on the code step.
 */
import { AUTH_STORAGE_KEY } from "../config.js";
import { state, setCurrentUser } from "../state.js";
import { api } from "../services/api.js";
import { showToast } from "./uiFeedback.js";
import { clearHistory } from "../services/undoService.js";
import { updateHeaderUI } from "./header.js";
import { stopSyncService } from "../services/syncService.js";

let onAuthSuccessCallback = null;

// Flow state (memory only, dies with reload — passwords never persisted)
const flow = {
  email: "",
  name: "",
  needPasswordOnCode: false,
  lastRegisterCreds: null, // { name, password } — enables "resend code" this session
};

export const getStoredAuth = () => {
  try {
    const raw = localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) return null;
    const session = JSON.parse(raw);
    const token = session?.token || session?.idToken || session?.accessToken;
    if (!token) return null;

    // Proactively check JWT expiration client-side to prevent stale 401s
    const parts = token.split(".");
    if (parts.length === 3) {
      try {
        const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
        if (payload.exp && payload.exp < Date.now() / 1000) {
          localStorage.removeItem(AUTH_STORAGE_KEY);
          return null;
        }
      } catch {
        // Continue if payload parse fails
      }
    }
    return session;
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

const STEPS = ["stepLogin", "stepRegister", "stepCode"];
const STEP_TITLES = {
  stepLogin: "Ingresá con tu cuenta de equipo",
  stepRegister: "Creá tu cuenta en un paso",
  stepCode: "Activá tu cuenta con el código de 6 dígitos",
};

export const showStep = (step) => {
  STEPS.forEach((s) => {
    const el = document.getElementById(s);
    if (el) el.style.display = s === step ? "block" : "none";
  });
  const title = document.getElementById("authStepTitle");
  if (title) title.textContent = STEP_TITLES[step] || STEP_TITLES.stepLogin;
};

const setWho = (elId, email, name) => {
  const el = document.getElementById(elId);
  if (el) el.textContent = `👤 ${name ? `${name} — ` : ""}${email}`;
};

const resetFlowToLogin = () => {
  flow.email = "";
  flow.name = "";
  flow.needPasswordOnCode = false;
  flow.lastRegisterCreds = null;
  ["stepLoginPassword", "stepRegName", "stepRegPassword", "stepCodeInput", "stepCodePassword"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  const box = document.getElementById("loginErrorBox");
  if (box) box.style.display = "none";
  showStep("stepLogin");
  setTimeout(() => document.getElementById("stepLoginEmail")?.focus(), 100);
};

const unlockApp = (res, welcomeMsg) => {
  const token = res.token || res.idToken || res.accessToken;
  saveStoredAuth({ ...res, token });
  setCurrentUser({ ...res.user, token });
  showToast(welcomeMsg || `¡Bienvenido/a, ${state.currentUser.name}!`);
  document.getElementById("authGate").style.display = "none";
  document.getElementById("appShell").style.display = "block";
  updateHeaderUI();
  if (typeof onAuthSuccessCallback === "function") {
    onAuthSuccessCallback();
  }
};

export const handleSessionExpired = () => {
  clearStoredAuth();
  clearHistory();
  setCurrentUser(null);
  const authGateEl = document.getElementById("authGate");
  const appShellEl = document.getElementById("appShell");
  if (authGateEl) authGateEl.style.display = "flex";
  if (appShellEl) appShellEl.style.display = "none";
  updateHeaderUI();
  resetFlowToLogin();
  showToast("Sesión expirada o no autorizada. Por favor ingresá nuevamente.", "error");
};

const goCodeStep = ({ email, name, needPassword, hint }) => {
  flow.email = email;
  if (name) flow.name = name;
  flow.needPasswordOnCode = !!needPassword;
  setWho("stepCodeWho", email, name);
  const passWrap = document.getElementById("stepCodePassWrap");
  if (passWrap) passWrap.style.display = needPassword ? "block" : "none";
  const codeInput = document.getElementById("stepCodeInput");
  if (codeInput) codeInput.value = "";
  const passInput = document.getElementById("stepCodePassword");
  if (passInput) passInput.value = "";
  showStep("stepCode");
  if (hint) showToast(hint);
  setTimeout(() => document.getElementById("stepCodeInput")?.focus(), 100);
};

const goRegisterStep = (email) => {
  flow.email = email || flow.email;
  setWho("stepRegWho", flow.email, "");
  showStep("stepRegister");
  setTimeout(() => document.getElementById("stepRegName")?.focus(), 100);
};

const onEnter = (inputId, btnId) => {
  const input = document.getElementById(inputId);
  const btn = document.getElementById(btnId);
  if (input && btn) {
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        btn.click();
      }
    });
  }
};

export const enforceAuthGate = (onSuccess) => {
  onAuthSuccessCallback = onSuccess;

  const urlParams = new URLSearchParams(window.location.search);
  const hash = window.location.hash || "";
  const inviteEmail = urlParams.get("email") || "";
  const inviteCode = urlParams.get("code") || "";
  const isActivationRequested =
    urlParams.get("action") === "activate" ||
    urlParams.get("action") === "confirm" ||
    urlParams.get("tab") === "confirm" ||
    urlParams.get("tab") === "activate" ||
    Boolean(inviteCode) ||
    hash.includes("activate") ||
    hash.includes("confirm");

  const stored = getStoredAuth();

  const authGateEl = document.getElementById("authGate");
  const appShellEl = document.getElementById("appShell");

  const token = stored ? (stored.token || stored.idToken || stored.accessToken) : null;

  if (stored && stored.user && token && !isActivationRequested) {
    // Authenticated session exists and no activation was requested in URL
    setCurrentUser({ ...stored.user, token });

    authGateEl.style.display = "none";
    appShellEl.style.display = "block";
    updateHeaderUI();

    if (typeof onAuthSuccessCallback === "function") {
      onAuthSuccessCallback();
    }
  } else {
    // Unauthenticated or explicit activation request
    clearStoredAuth();
    setCurrentUser(null);
    authGateEl.style.display = "flex";
    appShellEl.style.display = "none";
    updateHeaderUI();

    if (isActivationRequested && inviteEmail) {
      // Invite link: straight to the code step, password required
      if (inviteCode) {
        const codeInput = document.getElementById("stepCodeInput");
        if (codeInput) codeInput.value = inviteCode;
      }
      goCodeStep({
        email: inviteEmail,
        name: "",
        needPassword: true,
        hint: "Completá el código y definí tu contraseña para activar tu cuenta.",
      });
      setTimeout(() => document.getElementById("stepCodePassword")?.focus(), 200);
    } else {
      resetFlowToLogin();
    }
  }
};

export const initAuthGateListeners = () => {
  // ---- Login (main screen): one attempt routes everywhere ----
  const btnLoginSubmit = document.getElementById("btnLoginSubmit");
  if (btnLoginSubmit) {
    btnLoginSubmit.addEventListener("click", async () => {
      const email = document.getElementById("stepLoginEmail").value.trim().toLowerCase();
      const password = document.getElementById("stepLoginPassword").value;
      const box = document.getElementById("loginErrorBox");
      const errText = document.getElementById("loginErrorText");
      const btnGoRegister = document.getElementById("btnGoRegister");
      if (box) box.style.display = "none";
      if (btnGoRegister) btnGoRegister.style.display = "none";

      if (!email || !email.includes("@") || !password) {
        showToast("Ingresá tu correo y contraseña.", "error");
        return;
      }
      btnLoginSubmit.disabled = true;
      btnLoginSubmit.textContent = "Ingresando...";
      try {
        const res = await api.login(email, password);
        flow.email = email;
        unlockApp(res);
      } catch (err) {
        const payload = err.payload || {};
        if (payload.requires_activation || payload.requires_confirmation) {
          // Account exists but needs activation: jump to code step, no dead end
          flow.email = email;
          flow.name = "";
          goCodeStep({
            email,
            name: "",
            needPassword: true,
            hint: err.message,
          });
        } else {
          // Wrong password OR unknown email (backend won't tell which):
          // show the error and offer one-click account creation.
          if (errText) errText.textContent = "Revisá tu correo y contraseña.";
          if (box) box.style.display = "block";
          if (btnGoRegister) {
            btnGoRegister.style.display = "block";
            btnGoRegister.onclick = () => {
              const loginEmail = document.getElementById("stepLoginEmail").value.trim().toLowerCase();
              goRegisterStep(loginEmail);
            };
          }
          showToast(err.message, "error");
        }
      } finally {
        btnLoginSubmit.disabled = false;
        btnLoginSubmit.textContent = "Ingresar";
      }
    });
  }

  const linkGoRegister = document.getElementById("linkGoRegister");
  if (linkGoRegister) {
    linkGoRegister.addEventListener("click", () => {
      const typed = document.getElementById("stepLoginEmail").value.trim().toLowerCase();
      goRegisterStep(typed);
    });
  }

  const linkHaveCode = document.getElementById("linkHaveCode");
  if (linkHaveCode) {
    linkHaveCode.addEventListener("click", () => {
      const typed = document.getElementById("stepLoginEmail").value.trim().toLowerCase();
      goCodeStep({ email: typed, name: "", needPassword: true });
    });
  }

  // ---- Register -> signup -> code step ----
  const btnRegisterSubmit = document.getElementById("btnRegisterSubmit");
  if (btnRegisterSubmit) {
    btnRegisterSubmit.addEventListener("click", async () => {
      const name = document.getElementById("stepRegName").value.trim();
      const password = document.getElementById("stepRegPassword").value;
      const email = flow.email;
      if (!email || !email.includes("@")) {
        showToast("Volvé atrás e ingresá un correo válido.", "error");
        return;
      }
      if (!name || !password) {
        showToast("Completá tu nombre y contraseña.", "error");
        return;
      }
      if (password.length < 8) {
        showToast("La contraseña debe tener al menos 8 caracteres.", "error");
        return;
      }
      btnRegisterSubmit.disabled = true;
      btnRegisterSubmit.textContent = "Creando cuenta...";
      try {
        const res = await api.signup(email, password, name);
        flow.name = name;
        flow.lastRegisterCreds = { name, password };
        showToast(res.message || "Cuenta creada. Revisá tu email.");
        // Password already set at signup: code only
        goCodeStep({ email, name, needPassword: false });
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btnRegisterSubmit.disabled = false;
        btnRegisterSubmit.textContent = "Crear Cuenta";
      }
    });
  }

  // ---- Code -> confirm ----
  const btnConfirmSubmit = document.getElementById("btnConfirmSubmit");
  if (btnConfirmSubmit) {
    btnConfirmSubmit.addEventListener("click", async () => {
      const email = flow.email;
      const code = document.getElementById("stepCodeInput").value.trim();
      const password = document.getElementById("stepCodePassword")?.value || "";
      if (!email || !code) {
        showToast("Ingresá el código de 6 dígitos.", "error");
        return;
      }
      if (flow.needPasswordOnCode && (!password || password.length < 8)) {
        showToast("Definí una contraseña de al menos 8 caracteres.", "error");
        return;
      }
      btnConfirmSubmit.disabled = true;
      btnConfirmSubmit.textContent = "Activando...";
      try {
        const res = await api.confirm(email, code, flow.needPasswordOnCode ? password : "");
        const token = res.token || res.idToken || res.accessToken;
        if (token && res.user) {
          unlockApp(res, `¡Bienvenido/a, ${res.user.name}! Tu cuenta está activada.`);
        } else {
          showToast(res.message || "Cuenta activada. Ingresá con tu contraseña.");
          const loginEmail = document.getElementById("stepLoginEmail");
          if (loginEmail) loginEmail.value = email;
          flow.email = email;
          resetFlowToLogin();
          if (loginEmail) loginEmail.value = email;
        }
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btnConfirmSubmit.disabled = false;
        btnConfirmSubmit.textContent = "Activar y Entrar";
      }
    });
  }

  const btnResendCode = document.getElementById("btnResendCode");
  if (btnResendCode) {
    btnResendCode.addEventListener("click", async () => {
      if (!flow.lastRegisterCreds) {
        showToast("Si no recibiste el código, pedile al admin que te re-invite.", "error");
        return;
      }
      btnResendCode.disabled = true;
      try {
        await api.signup(flow.email, flow.lastRegisterCreds.password, flow.lastRegisterCreds.name);
        showToast("Te enviamos un código nuevo. Revisá tu correo.");
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btnResendCode.disabled = false;
      }
    });
  }

  // ---- Back links ----
  ["btnBackToLoginReg", "btnBackToLoginCode"].forEach((id) => {
    const emailInput = document.getElementById("stepLoginEmail");
    document.getElementById(id)?.addEventListener("click", () => {
      const keep = flow.email;
      resetFlowToLogin();
      if (keep && emailInput) emailInput.value = keep;
    });
  });

  // ---- Enter key submits each step ----
  onEnter("stepLoginEmail", "btnLoginSubmit");
  onEnter("stepLoginPassword", "btnLoginSubmit");
  onEnter("stepRegName", "btnRegisterSubmit");
  onEnter("stepRegPassword", "btnRegisterSubmit");
  onEnter("stepCodeInput", "btnConfirmSubmit");
  onEnter("stepCodePassword", "btnConfirmSubmit");

  // ---- Logout ----
  const btnLogout = document.getElementById("btnLogout");
  if (btnLogout) {
    btnLogout.addEventListener("click", () => {
      stopSyncService();
      clearStoredAuth();
      clearHistory();
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
      resetFlowToLogin();
      showToast("Sesión cerrada.");
    });
  }
};
