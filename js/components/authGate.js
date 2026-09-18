/**
 * Stepped Auth Gate Controller (email-first, no tabs).
 * Step 1: email -> identify routes to password / register / code.
 * Invite links (?action=activate&email&code) land straight on the code step.
 */
import { AUTH_STORAGE_KEY } from "../config.js";
import { state, setCurrentUser } from "../state.js";
import { api } from "../services/api.js";
import { showToast } from "./uiFeedback.js";
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

const STEPS = ["stepEmail", "stepPassword", "stepRegister", "stepCode"];
const STEP_TITLES = {
  stepEmail: "Matriz Semanal de Equipo • Acceso Obligatorio",
  stepPassword: "Cuenta encontrada — ingresá tu contraseña",
  stepRegister: "Cuenta nueva — completemos tu registro",
  stepCode: "Activá tu cuenta con el código de 6 dígitos",
};

export const showStep = (step) => {
  STEPS.forEach((s) => {
    const el = document.getElementById(s);
    if (el) el.style.display = s === step ? "block" : "none";
  });
  const title = document.getElementById("authStepTitle");
  if (title) title.textContent = STEP_TITLES[step] || STEP_TITLES.stepEmail;
  document.querySelectorAll("#authStepsBar .auth-step-pill").forEach((pill) => {
    const kind = pill.dataset.step;
    pill.classList.remove("active", "done");
    if (step === "stepEmail" && kind === "email") pill.classList.add("active");
    if (step !== "stepEmail" && kind === "verify") pill.classList.add("active");
    if (step !== "stepEmail" && kind === "email") pill.classList.add("done");
  });
};

const setWho = (elId, email, name) => {
  const el = document.getElementById(elId);
  if (el) el.textContent = `👤 ${name ? `${name} — ` : ""}${email}`;
};

const resetFlowToEmail = () => {
  flow.email = "";
  flow.name = "";
  flow.needPasswordOnCode = false;
  flow.lastRegisterCreds = null;
  ["stepPassInput", "stepRegName", "stepRegPassword", "stepCodeInput", "stepCodePassword"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  const box = document.getElementById("loginUnknownBox");
  if (box) box.style.display = "none";
  showStep("stepEmail");
  setTimeout(() => document.getElementById("stepEmailInput")?.focus(), 100);
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
  setCurrentUser(null);
  const authGateEl = document.getElementById("authGate");
  const appShellEl = document.getElementById("appShell");
  if (authGateEl) authGateEl.style.display = "flex";
  if (appShellEl) appShellEl.style.display = "none";
  updateHeaderUI();
  resetFlowToEmail();
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
      resetFlowToEmail();
    }
  }
};

export const initAuthGateListeners = () => {
  // ---- Step 1: email -> identify ----
  const btnEmailContinue = document.getElementById("btnEmailContinue");
  if (btnEmailContinue) {
    btnEmailContinue.addEventListener("click", async () => {
      const email = document.getElementById("stepEmailInput").value.trim().toLowerCase();
      if (!email || !email.includes("@")) {
        showToast("Ingresá un correo válido.", "error");
        return;
      }
      btnEmailContinue.disabled = true;
      btnEmailContinue.textContent = "Verificando...";
      try {
        const res = await api.identify(email);
        flow.email = email;
        flow.name = res.name || "";
        flow.lastRegisterCreds = null;
        if (res.status === "login") {
          setWho("stepPassWho", email, res.name);
          const box = document.getElementById("loginUnknownBox");
          if (box) box.style.display = "none";
          const pass = document.getElementById("stepPassInput");
          if (pass) pass.value = "";
          showStep("stepPassword");
          setTimeout(() => document.getElementById("stepPassInput")?.focus(), 100);
        } else if (res.status === "confirm") {
          goCodeStep({
            email,
            name: res.name,
            needPassword: true,
            hint: "Esa cuenta está pendiente de activación. Ingresá el código que te enviamos.",
          });
        } else {
          setWho("stepRegWho", email, "");
          showStep("stepRegister");
          setTimeout(() => document.getElementById("stepRegName")?.focus(), 100);
        }
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        btnEmailContinue.disabled = false;
        btnEmailContinue.textContent = "Continuar ➔";
      }
    });
  }

  const linkHaveCode = document.getElementById("linkHaveCode");
  if (linkHaveCode) {
    linkHaveCode.addEventListener("click", () => {
      const typed = document.getElementById("stepEmailInput").value.trim().toLowerCase();
      goCodeStep({ email: typed, name: "", needPassword: true });
    });
  }

  // ---- Step 2a: password -> login (smart failures) ----
  const btnLoginSubmit = document.getElementById("btnLoginSubmit");
  if (btnLoginSubmit) {
    btnLoginSubmit.addEventListener("click", async () => {
      const email = flow.email;
      const password = document.getElementById("stepPassInput").value;
      if (!email || !password) {
        showToast("Ingresá tu contraseña.", "error");
        return;
      }
      btnLoginSubmit.disabled = true;
      btnLoginSubmit.textContent = "Ingresando...";
      try {
        const res = await api.login(email, password);
        unlockApp(res);
      } catch (err) {
        const payload = err.payload || {};
        if (payload.requires_activation || payload.requires_confirmation) {
          // Account exists but needs activation: jump to code step, no dead end
          goCodeStep({
            email,
            name: flow.name,
            needPassword: true,
            hint: err.message,
          });
        } else if (err.code === 401 && /no encontrado|not found|incorrecta|inválidas/i.test(err.message)) {
          // Unknown email or wrong password: offer one-click account creation
          const box = document.getElementById("loginUnknownBox");
          if (box) box.style.display = "block";
          showToast("Revisá los datos. Si no tenés cuenta, creala con un clic.", "error");
        } else {
          showToast(err.message, "error");
        }
      } finally {
        btnLoginSubmit.disabled = false;
        btnLoginSubmit.textContent = "Ingresar";
      }
    });
  }

  const btnGoRegister = document.getElementById("btnGoRegister");
  if (btnGoRegister) {
    btnGoRegister.addEventListener("click", () => {
      setWho("stepRegWho", flow.email, "");
      showStep("stepRegister");
      setTimeout(() => document.getElementById("stepRegName")?.focus(), 100);
    });
  }

  // ---- Step 2b: register -> signup -> code step ----
  const btnRegisterSubmit = document.getElementById("btnRegisterSubmit");
  if (btnRegisterSubmit) {
    btnRegisterSubmit.addEventListener("click", async () => {
      const name = document.getElementById("stepRegName").value.trim();
      const password = document.getElementById("stepRegPassword").value;
      const email = flow.email;
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

  // ---- Step 2c: code -> confirm ----
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
          showToast(res.message || "Cuenta activada. Ingresá tu contraseña.");
          setWho("stepPassWho", email, res.user?.name || flow.name);
          const box = document.getElementById("loginUnknownBox");
          if (box) box.style.display = "none";
          showStep("stepPassword");
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
  ["btnBackToEmailPass", "btnBackToEmailReg", "btnBackToEmailCode"].forEach((id) => {
    document.getElementById(id)?.addEventListener("click", resetFlowToEmail);
  });

  // ---- Enter key submits each step ----
  onEnter("stepEmailInput", "btnEmailContinue");
  onEnter("stepPassInput", "btnLoginSubmit");
  onEnter("stepRegPassword", "btnRegisterSubmit");
  onEnter("stepCodeInput", "btnConfirmSubmit");
  onEnter("stepCodePassword", "btnConfirmSubmit");

  // ---- Logout ----
  const btnLogout = document.getElementById("btnLogout");
  if (btnLogout) {
    btnLogout.addEventListener("click", () => {
      stopSyncService();
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
      resetFlowToEmail();
      showToast("Sesión cerrada.");
    });
  }
};
