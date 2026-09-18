/**
 * Serverless Backend API Client
 */
import { getCleanUrl, AUTH_STORAGE_KEY } from "../config.js";
import { state, setCurrentUser } from "../state.js";
import { showToast } from "../components/uiFeedback.js";
import { updateHeaderUI } from "../components/header.js";

export const getAuthHeaders = () => {
  const headers = { "Content-Type": "application/json" };
  const token = state.currentUser?.token;
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
};

export const handleUnauthorized = () => {
  localStorage.removeItem(AUTH_STORAGE_KEY);
  setCurrentUser(null);
  const authGateEl = document.getElementById("authGate");
  const appShellEl = document.getElementById("appShell");
  if (authGateEl) authGateEl.style.display = "flex";
  if (appShellEl) appShellEl.style.display = "none";
  updateHeaderUI();
  showToast("Sesión expirada o no autorizada. Por favor ingresá nuevamente.", "error");
};

const authFetch = async (url, options = {}) => {
  const headers = { ...getAuthHeaders(), ...(options.headers || {}) };
  const res = await fetch(url, { ...options, headers });
  if (res.status === 401) {
    handleUnauthorized();
  }
  return res;
};

export const api = {
  // Authentication & Verification
  async login(email, password) {
    const url = getCleanUrl();
    const res = await fetch(`${url}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) {
      const err = new Error(data.error || "Credenciales inválidas");
      err.code = res.status;
      err.payload = data;
      throw err;
    }
    return data;
  },

  async signup(email, password, name) {
    const url = getCleanUrl();
    const res = await fetch(`${url}/auth/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, name }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al registrar cuenta");
    return data;
  },

  async confirm(email, code, password = "") {
    const url = getCleanUrl();
    const payload = { email, code };
    if (password) payload.password = password;
    const res = await fetch(`${url}/auth/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Código de verificación inválido");
    return data;
  },

  async requestOtp(email) {
    const url = getCleanUrl();
    const res = await fetch(`${url}/auth/otp/request`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al solicitar código OTP");
    return data;
  },

  async verifyOtp(email, code) {
    const url = getCleanUrl();
    const res = await fetch(`${url}/auth/otp/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, code }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al verificar código OTP");
    return data;
  },

  // Projects CRUD
  async getProjects() {
    const url = getCleanUrl();
    try {
      const res = await authFetch(`${url}/projects`);
      if (!res.ok) return [];
      const data = await res.json();
      return data.projects || [];
    } catch (err) {
      console.error("Error fetching projects:", err);
      return [];
    }
  },

  async createProject(name, allow_self_assignment = false) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/projects`, {
      method: "POST",
      body: JSON.stringify({ name, allow_self_assignment }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al crear proyecto");
    return data;
  },

  async updateProject(oldName, newName, allow_self_assignment) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/projects/${encodeURIComponent(oldName)}`, {
      method: "PUT",
      body: JSON.stringify({ newName, allow_self_assignment }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al actualizar proyecto");
    return data;
  },

  async deleteProject(name) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/projects/${encodeURIComponent(name)}`, {
      method: "DELETE",
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al eliminar proyecto");
    return data;
  },

  // Members CRUD
  async getMembers(project) {
    const url = getCleanUrl();
    try {
      const res = await authFetch(`${url}/projects/${encodeURIComponent(project)}/members`);
      if (!res.ok) return [];
      const data = await res.json();
      return data.members || [];
    } catch (err) {
      console.error("Error fetching members:", err);
      return [];
    }
  },

  async createMember(project, name, role, email = "", isAdmin = false) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/projects/${encodeURIComponent(project)}/members`, {
      method: "POST",
      body: JSON.stringify({
        name,
        role,
        email,
        is_admin: isAdmin,
        system_role: isAdmin ? "admin" : "member",
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al agregar integrante");
    return data;
  },

  async updateMember(project, oldName, newName, role, email = "", isAdmin = false) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/projects/${encodeURIComponent(project)}/members/${encodeURIComponent(oldName)}`, {
      method: "PUT",
      body: JSON.stringify({
        newName,
        role,
        email,
        is_admin: isAdmin,
        system_role: isAdmin ? "admin" : "member",
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al actualizar integrante");
    return data;
  },

  async deleteMember(project, name) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/projects/${encodeURIComponent(project)}/members/${encodeURIComponent(name)}`, {
      method: "DELETE",
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al eliminar integrante");
    return data;
  },

  async deleteUserAccount(email) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/admin/users/${encodeURIComponent(email)}`, {
      method: "DELETE",
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al eliminar la cuenta de usuario");
    return data;
  },

  // Scrums & Dynamic Weeks
  async getWeeks(project) {
    const url = getCleanUrl();
    try {
      const res = await authFetch(`${url}/scrums?project=${encodeURIComponent(project)}`);
      if (!res.ok) return [];
      const data = await res.json();
      return data.weeks || [];
    } catch (err) {
      console.error("Error fetching weeks:", err);
      return [];
    }
  },

  async getWeeklyScrums(project, week) {
    const url = getCleanUrl();
    try {
      const res = await authFetch(`${url}/scrums?project=${encodeURIComponent(project)}&week=${encodeURIComponent(week)}`);
      if (!res.ok) return [];
      const data = await res.json();
      return data.scrums || [];
    } catch (err) {
      console.error("Error fetching weekly scrums:", err);
      return [];
    }
  },

  async saveScrum(project, week, day, member, answers, blocking_task_id = "", blocking_task_title = "", kanban_refs = null) {
    const url = getCleanUrl();
    const payload = { project, week, day, member, answers, blocking_task_id, blocking_task_title };
    if (kanban_refs != null) payload.kanban_refs = kanban_refs;
    const res = await authFetch(`${url}/scrums`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al guardar Daily Scrum");
    return data;
  },

  async deleteScrum(project, week, day, member) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/scrums`, {
      method: "DELETE",
      body: JSON.stringify({ project, week, day, member }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al eliminar Daily Scrum");
    return data;
  },

  // Tasks & Kanban
  async getTasks(project) {
    const url = getCleanUrl();
    try {
      const res = await authFetch(`${url}/tasks?project=${encodeURIComponent(project)}`);
      if (!res.ok) return [];
      const data = await res.json();
      return data.tasks || [];
    } catch (err) {
      console.error("Error fetching tasks:", err);
      return [];
    }
  },

  async saveTask(task) {
    const url = getCleanUrl();
    const method = task.id ? "PUT" : "POST";
    const res = await authFetch(`${url}/tasks`, {
      method,
      body: JSON.stringify(task),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al guardar tarea");
    return data.task || task;
  },

  async deleteTask(project, taskId) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/tasks?project=${encodeURIComponent(project)}&id=${encodeURIComponent(taskId)}`, {
      method: "DELETE",
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al eliminar tarea");
    return data;
  },

  async restoreTask(project, taskId) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/tasks/restore`, {
      method: "POST",
      body: JSON.stringify({ project, id: taskId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al restaurar tarea");
    return data;
  },

  async restoreScrum(project, week, day, member) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/scrums/restore`, {
      method: "POST",
      body: JSON.stringify({ project, week, day, member }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al restaurar Daily");
    return data;
  },

  // Trash (papelera, admin)
  async getTrash(project) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/admin/trash?project=${encodeURIComponent(project)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al obtener papelera");
    return data.trash || [];
  },

  async restoreTrashItem(project, pk, sk) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/admin/trash/restore`, {
      method: "POST",
      body: JSON.stringify({ project, pk, sk }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al restaurar");
    return data;
  },

  async purgeTrashItem(project, pk, sk) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/admin/trash?project=${encodeURIComponent(project)}&pk=${encodeURIComponent(pk)}&sk=${encodeURIComponent(sk)}`, {
      method: "DELETE",
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al eliminar definitivamente");
    return data;
  },

  // Gmail SMTP Admin Config
  async getEmailConfig() {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/admin/config/email`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al obtener configuración de Email");
    return data;
  },

  async saveEmailConfig(gmailUser, gmailPassword, senderName, appUrl) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/admin/config/email`, {
      method: "POST",
      body: JSON.stringify({ gmailUser, gmailPassword, senderName, appUrl }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al guardar configuración de Email");
    return data;
  },

  async testEmail(toEmail) {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/admin/config/email/test`, {
      method: "POST",
      body: JSON.stringify({ toEmail }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al enviar email de prueba");
    return data;
  },

  // Admin Activity Audit
  async getActivityAudit(project = "") {
    const url = getCleanUrl();
    const query = project ? `?project=${encodeURIComponent(project)}` : "";
    const res = await authFetch(`${url}/admin/audit/activity${query}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al obtener auditoría de actividad");
    return data;
  },

  // Admin Registered Users
  async getAdminUsers() {
    const url = getCleanUrl();
    const res = await authFetch(`${url}/admin/users`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Error al obtener usuarios registrados");
    return data.users || [];
  },
};
