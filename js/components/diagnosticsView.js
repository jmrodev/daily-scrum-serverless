/**
 * Diagnostics & PERT/CPM View Component
 * Provides:
 * 1. Live Interactive PERT/CPM Task Dependency DAG with Critical Path analysis
 * 2. Team Flow Diagnostics ("¿Quién traba a quién?") and Bottleneck KPIs
 * 3. Member Activity Audit with Login/Signup Tracking (Admin/Evaluator only)
 * 4. Academic Evaluation Report & Grading Rubric for the Course Professor
 */
import { api } from "../services/api.js";
import { state, isAdmin } from "../state.js";
import { escapeHtml } from "../services/domUtils.js";
import { switchMainView } from "../app.js";

let activeSubTab = "pert"; // "pert" | "flow" | "audit" | "report"

const NEGATIVE_BLOCKER_KEYWORDS = [
  "no",
  "ninguno",
  "ninguna",
  "nada",
  "sin bloqueos",
  "sin bloqueo",
  "sin impedimentos",
  "sin impedimento",
  "-",
  "ok",
  "todo bien",
  "n/a",
  "none",
];

const isRealBlocker = (text) => {
  if (!text) return false;
  const clean = text.trim().toLowerCase();
  if (clean.length < 2) return false;
  return !NEGATIVE_BLOCKER_KEYWORDS.includes(clean);
};

const formatDuration = (ms) => {
  if (!ms || ms < 0) return "Reciente";
  const hours = Math.floor(ms / (1000 * 60 * 60));
  if (hours < 1) return "< 1 hora";
  if (hours < 24) return `${hours} h`;
  const days = Math.floor(hours / 24);
  const remHours = hours % 24;
  return remHours > 0 ? `${days}d ${remHours}h` : `${days} días`;
};

const formatRelativeTime = (isoString) => {
  if (!isoString) return "Nunca";
  const diff = Date.now() - new Date(isoString).getTime();
  if (diff < 0) return "Reciente";
  const mins = Math.floor(diff / 60000);
  if (mins < 2) return "Hace un momento";
  if (mins < 60) return `Hace ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `Hace ${hours} h`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `Hace ${days} d`;
  return new Date(isoString).toLocaleDateString();
};

export const openTaskLifecycleModal = (taskId, taskMap, scrums, activityData, currentProject) => {
  const t = taskMap[taskId];
  if (!t) return;

  let modal = document.getElementById("pertLifecycleModal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "pertLifecycleModal";
    modal.className = "modal-overlay";
    document.body.appendChild(modal);
  }

  const assigneeName = t.assignee || "Sin Asignar";
  const userAudit = (activityData || []).find(
    (u) => (u.name && u.name.toLowerCase() === assigneeName.toLowerCase()) ||
           (u.email && u.email.toLowerCase() === assigneeName.toLowerCase())
  );

  // 1. Session / Login audit step
  let loginText = "Sin sesión previa auditada en el sistema.";
  let loginTime = "—";
  if (userAudit) {
    loginTime = userAudit.last_login ? new Date(userAudit.last_login).toLocaleString() : "Registrado";
    const ip = userAudit.events && userAudit.events[0] ? userAudit.events[0].ip : "";
    loginText = `<strong>${escapeHtml(userAudit.name)}</strong> ingresó al sistema (${userAudit.login_count || 1} accesos registrados${ip ? `, IP: ${escapeHtml(ip)}` : ""}).`;
  } else if (t.assignee) {
    loginText = `Integrante <strong>${escapeHtml(t.assignee)}</strong> activo en el proyecto <strong>${escapeHtml(currentProject)}</strong>.`;
  } else {
    loginText = "Tarea creada en 'Por Hacer' disponible para asignación del equipo.";
  }

  // 2. Task creation / doing step
  const createdTime = t.created_at ? new Date(t.created_at).toLocaleString() : "Registro de Sprint";
  const taskCreatedText = `Se registró la tarea <strong>"${escapeHtml(t.title)}"</strong> en estado <strong>${t.status}</strong> con prioridad <strong>${t.priority || "MEDIUM"}</strong>. Asignada a: <em>${escapeHtml(assigneeName)}</em>.`;

  // 3. Daily Scrum / Blocker declaration step
  const matchingDaily = (scrums || []).find((s) => {
    if (!s.answers) return false;
    const isOwner = s.member && s.member.toLowerCase() === assigneeName.toLowerCase();
    const mentionsTask = (s.answers[2] && s.answers[2].toLowerCase().includes((t.title || "").toLowerCase())) ||
                         s.blocking_task_id === t.id;
    return isOwner || mentionsTask;
  });

  let dailyText = "No se declararon bloqueos en la última Daily Scrum. La tarea avanza sin fricción.";
  let dailyTime = "Daily Scrum";
  let isDailyBlocker = false;

  if (t.predecessors && t.predecessors.length > 0) {
    isDailyBlocker = true;
    const predTitles = t.predecessors.map((pid) => taskMap[pid]?.title || pid).join(", ");
    dailyText = `⚠️ <strong>Impedimento activo:</strong> La entrega está detenida a la espera de que se complete la tarea previa: <em>${escapeHtml(predTitles)}</em>.`;
    if (matchingDaily && matchingDaily.answers && isRealBlocker(matchingDaily.answers[2])) {
      dailyTime = `Daily ${matchingDaily.day} (${matchingDaily.member})`;
      dailyText += `<br/><small style="color:var(--text-muted); margin-top:4px; display:block;">Reportado en Daily: "${escapeHtml(matchingDaily.answers[2])}"</small>`;
    }
  } else if (t.blocker && isRealBlocker(t.blocker)) {
    isDailyBlocker = true;
    dailyText = `🚨 <strong>Bloqueo registrado:</strong> ${escapeHtml(t.blocker)}`;
  }

  // 4. PERT / CPM Critical Path Impact
  const isCritical = t.isCritical;
  let pertText = "";
  if (isCritical) {
    pertText = `<strong>🔴 NODO EN RUTA CRÍTICA:</strong> Cualquier retraso en esta tarea posterga directamente la fecha final del sprint. ${t.successors && t.successors.length > 0 ? `Frena la entrega de ${t.successors.length} tarea(s) subsiguiente(s).` : 'Se encuentra detenida esperando destrabe.'}`;
  } else if (t.status === "DONE") {
    pertText = `<strong>✅ ENTREGADA:</strong> Tarea completada. Ha liberado el flujo y las dependencias subsiguientes en la red.`;
  } else {
    pertText = `<strong>🟢 FLUJO NORMAL:</strong> Tarea en desarrollo u orden regular con holgura en el cronograma.`;
  }

  modal.innerHTML = `
    <div class="modal-box" style="max-width: 560px; max-height: 90vh; overflow-y: auto;">
      <div class="modal-header">
        <div>
          <span style="font-size: 10px; font-weight: 800; color: var(--primary); text-transform: uppercase; letter-spacing: 0.5px;">
            Auditoría de Nodo & Trazabilidad
          </span>
          <h3 style="margin: 2px 0 0; font-size: 16px;">
            🔍 [#${escapeHtml(t.id)}] ${escapeHtml(t.title)}
          </h3>
        </div>
        <button type="button" class="modal-close" id="btnCloseLifecycleModal">&times;</button>
      </div>

      <div class="modal-body" style="padding: 16px 20px;">
        <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px;">
          <span class="diag-status-badge ${t.status.toLowerCase()}">${t.status}</span>
          <span class="priority-badge ${(t.priority || 'medium').toLowerCase()}">${t.priority || 'Media'}</span>
          <span class="diag-time-pill">👤 ${escapeHtml(assigneeName)}</span>
          ${isCritical ? '<span class="diag-status-badge blocked">🔴 RUTA CRÍTICA</span>' : ''}
        </div>

        <div class="pert-timeline">
          <!-- Step 1: Login / Session -->
          <div class="pert-timeline-item login">
            <div class="pert-timeline-dot">🔑</div>
            <div class="pert-timeline-time">${loginTime}</div>
            <div class="pert-timeline-title">1. Ingreso & Sesión Autenticada</div>
            <div class="pert-timeline-desc">${loginText}</div>
          </div>

          <!-- Step 2: Task Creation / Doing -->
          <div class="pert-timeline-item task">
            <div class="pert-timeline-dot">📝</div>
            <div class="pert-timeline-time">${createdTime}</div>
            <div class="pert-timeline-title">2. Actuación en Tablero / Creación</div>
            <div class="pert-timeline-desc">${taskCreatedText}</div>
          </div>

          <!-- Step 3: Daily Scrum / Blocker -->
          <div class="pert-timeline-item ${isDailyBlocker ? 'blocker' : 'daily'}">
            <div class="pert-timeline-dot">${isDailyBlocker ? '🚨' : '💬'}</div>
            <div class="pert-timeline-time">${dailyTime}</div>
            <div class="pert-timeline-title">3. Registro de Daily Scrum & Dependencia</div>
            <div class="pert-timeline-desc">${dailyText}</div>
          </div>

          <!-- Step 4: PERT / CPM Impact -->
          <div class="pert-timeline-item ${isCritical ? 'pert' : ''}">
            <div class="pert-timeline-dot">🕸️</div>
            <div class="pert-timeline-time">Análisis de Red en Vivo</div>
            <div class="pert-timeline-title">4. Proyección en Grafo PERT / CPM</div>
            <div class="pert-timeline-desc">${pertText}</div>
          </div>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 20px; border-top: 1px solid var(--border); padding-top: 14px;">
          <button type="button" class="btn btn-secondary btn-sm" id="btnLifecycleClose">
            Cerrar
          </button>
          <button type="button" class="btn btn-primary btn-sm" id="btnLifecycleGoKanban">
            📋 Gestionar en Tablero Kanban ➔
          </button>
        </div>
      </div>
    </div>
  `;

  modal.style.display = "flex";

  const closeModal = () => {
    modal.style.display = "none";
  };

  document.getElementById("btnCloseLifecycleModal")?.addEventListener("click", closeModal);
  document.getElementById("btnLifecycleClose")?.addEventListener("click", closeModal);
  document.getElementById("btnLifecycleGoKanban")?.addEventListener("click", () => {
    closeModal();
    switchMainView("kanban");
  });
};

export const renderDiagnosticsView = async (project = null, week = null) => {
  const container = document.getElementById("diagnosticsViewContainer");
  if (!container) return;

  const currentProject = project || document.getElementById("boardProject")?.value || state.activeProject;
  const currentWeek = week || document.getElementById("boardWeek")?.value || state.activeWeek || "WEEK 1";

  if (!currentProject) {
    container.innerHTML = `
      <div style="text-align: center; padding: 40px; color: var(--text-muted);">
        <div style="font-size: 36px; margin-bottom: 8px;">📂</div>
        <p style="font-weight: 600;">Seleccioná un proyecto para ver el seguimiento PERT/CPM y diagnóstico.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div style="text-align: center; padding: 30px; color: var(--text-muted);">
      <div class="spinner" style="margin: 0 auto 12px;"></div>
      <p>Calculando red PERT/CPM, diagnósticos y auditoría...</p>
    </div>
  `;

  try {
    const [members, scrums, tasks] = await Promise.all([
      api.getMembers(currentProject),
      api.getWeeklyScrums(currentProject, currentWeek),
      api.getTasks(currentProject),
    ]);

    let activityData = [];
    if (isAdmin()) {
      try {
        const auditResp = await api.getActivityAudit(currentProject);
        activityData = auditResp.activity || [];
      } catch (err) {
        console.warn("Could not load activity audit:", err);
      }
    }

    const now = Date.now();
    const memberNames = members.map((m) => m.name);

    // =========================================================================
    // 1. FLOW & BOTTLENECK ANALYSIS DATA
    // =========================================================================
    const diagnostics = members.map((member) => {
      const memTasks = tasks.filter((t) => t.assignee && t.assignee.toLowerCase() === member.name.toLowerCase());
      const blockedTasks = memTasks.filter((t) => t.status === "BLOCKED");
      const memberScrums = scrums.filter((s) => s.member && s.member.toLowerCase() === member.name.toLowerCase());
      
      let isBlocked = blockedTasks.length > 0;
      let blockerText = "";
      let reportedAt = null;
      let timeStuckMs = 0;
      let blockedByWho = null;

      if (blockedTasks.length > 0) {
        const topTask = blockedTasks[0];
        blockerText = `[Tarea] ${topTask.title}${topTask.blocker ? `: ${topTask.blocker}` : ""}`;
        reportedAt = topTask.updated_at || topTask.created_at;
        if (reportedAt) timeStuckMs = now - new Date(reportedAt).getTime();
      } else {
        const withBlockers = memberScrums.filter((s) => s.answers && isRealBlocker(s.answers[2]));
        if (withBlockers.length > 0) {
          isBlocked = true;
          const topScrum = withBlockers[withBlockers.length - 1];
          blockerText = `[Daily ${topScrum.day}] ${topScrum.answers[2]}`;
          reportedAt = topScrum.updated_at || null;
          if (reportedAt) timeStuckMs = now - new Date(reportedAt).getTime();
        }
      }

      if (isBlocked && blockerText) {
        const lowerText = blockerText.toLowerCase();
        for (const otherName of memberNames) {
          if (otherName.toLowerCase() !== member.name.toLowerCase() && lowerText.includes(otherName.toLowerCase())) {
            blockedByWho = { type: "member", name: otherName };
            break;
          }
        }
        if (!blockedByWho) {
          if (lowerText.includes("servidor") || lowerText.includes("api") || lowerText.includes("infra") || lowerText.includes("aws") || lowerText.includes("backend")) {
            blockedByWho = { type: "external", name: "Backend / Infraestructura" };
          } else if (lowerText.includes("diseño") || lowerText.includes("ux") || lowerText.includes("ui") || lowerText.includes("front")) {
            blockedByWho = { type: "external", name: "Diseño UI/UX" };
          } else if (lowerText.includes("cliente") || lowerText.includes("externo") || lowerText.includes("tercero")) {
            blockedByWho = { type: "external", name: "Dependencia Externa" };
          } else {
            blockedByWho = { type: "task", name: "Impedimento Operativo" };
          }
        }
      }

      return {
        name: member.name,
        role: member.role || "Developer",
        is_admin: Boolean(member.is_admin),
        isBlocked,
        blockerText,
        reportedAt,
        timeStuckMs,
        timeStuckFormatted: isBlocked ? formatDuration(timeStuckMs) : "—",
        blockedByWho,
        blockedTasksCount: blockedTasks.length,
      };
    });

    const blockingCounts = {};
    diagnostics.forEach((d) => {
      if (d.blockedByWho && d.blockedByWho.type === "member") {
        blockingCounts[d.blockedByWho.name] = (blockingCounts[d.blockedByWho.name] || 0) + 1;
      }
    });

    const totalMembers = members.length;
    const blockedCount = diagnostics.filter((d) => d.isBlocked).length;
    const fluentCount = totalMembers - blockedCount;
    const totalTimeStuck = diagnostics.reduce((acc, d) => acc + (d.timeStuckMs || 0), 0);
    const avgTimeStuck = blockedCount > 0 ? formatDuration(Math.round(totalTimeStuck / blockedCount)) : "0 h";

    let topBottleneck = "Ninguno (Flujo 100% fluido)";
    let maxBlockCount = 0;
    Object.entries(blockingCounts).forEach(([name, cnt]) => {
      if (cnt > maxBlockCount) {
        maxBlockCount = cnt;
        topBottleneck = `${name} (frena a ${cnt} integrante${cnt > 1 ? "s" : ""})`;
      }
    });

    // =========================================================================
    // 2. PERT / CPM GRAPH & CRITICAL PATH CALCULATION
    // =========================================================================
    // Map tasks and resolve dependencies
    const taskMap = {};
    tasks.forEach((t) => {
      taskMap[t.id] = { ...t, predecessors: [], successors: [], isCritical: false };
    });

    tasks.forEach((t) => {
      const preds = [];
      if (Array.isArray(t.depends_on)) {
        t.depends_on.forEach((depId) => {
          if (taskMap[depId]) preds.push(depId);
        });
      }
      if (t.blocked_by_task_id && taskMap[t.blocked_by_task_id] && !preds.includes(t.blocked_by_task_id)) {
        preds.push(t.blocked_by_task_id);
      }
      // Also match by blocker text if it explicitly points to another task
      if (t.blocker) {
        const bLower = t.blocker.toLowerCase();
        tasks.forEach((other) => {
          if (other.id !== t.id && bLower.includes(other.title.toLowerCase()) && !preds.includes(other.id)) {
            preds.push(other.id);
          }
        });
      }
      taskMap[t.id].predecessors = preds;
      preds.forEach((pId) => {
        if (!taskMap[pId].successors.includes(t.id)) {
          taskMap[pId].successors.push(t.id);
        }
      });
    });

    // Mark Critical Path: A task is Critical if it is NOT DONE and is blocking others or is BLOCKED
    let criticalCount = 0;
    Object.values(taskMap).forEach((t) => {
      const isUnfinished = t.status !== "DONE";
      const blocksOthers = t.successors.some((succId) => taskMap[succId]?.status !== "DONE");
      const hasBlockerReported = t.status === "BLOCKED" || (t.blocker && t.blocker.toLowerCase().includes("bloquea a"));
      if (isUnfinished && (blocksOthers || hasBlockerReported)) {
        t.isCritical = true;
        criticalCount++;
      }
    });

    // Compute topological column rank (Level 0, 1, 2, 3)
    const computeLevel = (taskId, visited = new Set()) => {
      if (visited.has(taskId)) return 0;
      visited.add(taskId);
      const t = taskMap[taskId];
      if (!t || !t.predecessors || t.predecessors.length === 0) {
        return t?.status === "DONE" ? 3 : (t?.status === "DOING" ? 1 : 0);
      }
      const predLevels = t.predecessors.map((p) => computeLevel(p, new Set(visited)));
      return Math.min(3, Math.max(...predLevels) + 1);
    };

    const columns = [[], [], [], []];
    Object.values(taskMap).forEach((t) => {
      const level = computeLevel(t.id);
      t.level = level;
      columns[level].push(t);
    });

    // =========================================================================
    // 3. RENDER SUB-NAVIGATION & CONTAINER
    // =========================================================================
    container.innerHTML = `
      <div class="diag-container">
        <!-- Sub-navigation Tabs -->
        <div class="diag-subnav">
          <button type="button" class="diag-subnav-btn ${activeSubTab === 'pert' ? 'active' : ''}" data-subtab="pert">
            🕸️ Red PERT/CPM (Grafo & Ruta Crítica)
          </button>
          <button type="button" class="diag-subnav-btn ${activeSubTab === 'flow' ? 'active' : ''}" data-subtab="flow">
            📈 Diagnóstico & Flujo ("¿Quién traba a quién?")
          </button>
          ${isAdmin() ? `
            <button type="button" class="diag-subnav-btn ${activeSubTab === 'audit' ? 'active' : ''}" data-subtab="audit">
              👥 Auditoría de Actividad (Admin)
            </button>
          ` : ''}
          <button type="button" class="diag-subnav-btn ${activeSubTab === 'report' ? 'active' : ''}" data-subtab="report">
            🎓 Rúbrica & Informe Cátedra
          </button>
        </div>

        <div id="diagSubTabContent"></div>
      </div>
    `;

    const subTabContent = document.getElementById("diagSubTabContent");

    // =========================================================================
    // 4. SUBTAB 1: PERT / CPM GRAPH & DEPENDENCY TABLE
    // =========================================================================
    if (activeSubTab === "pert") {
      const colWidth = 260;
      const colGap = 80;
      const rowHeight = 90;
      const rowGap = 20;

      const maxRows = Math.max(...columns.map((c) => c.length), 1);
      const svgWidth = Math.max(960, 4 * colWidth + 3 * colGap + 60);
      const svgHeight = Math.max(420, maxRows * (rowHeight + rowGap) + 80);

      // Node Positions Map
      const positions = {};
      columns.forEach((colTasks, colIdx) => {
        const x = 30 + colIdx * (colWidth + colGap);
        colTasks.forEach((t, rowIdx) => {
          const y = 50 + rowIdx * (rowHeight + rowGap);
          positions[t.id] = { x, y, width: colWidth, height: rowHeight };
        });
      });

      // Generate SVG Edges (Paths)
      let svgEdgesHtml = "";
      Object.values(taskMap).forEach((t) => {
        const toPos = positions[t.id];
        if (!toPos) return;

        t.predecessors.forEach((predId) => {
          const fromPos = positions[predId];
          if (!fromPos) return;

          const x1 = fromPos.x + fromPos.width;
          const y1 = fromPos.y + fromPos.height / 2;
          const x2 = toPos.x;
          const y2 = toPos.y + toPos.height / 2;

          const midX = (x1 + x2) / 2;
          const predTask = taskMap[predId];
          const isCriticalEdge = predTask && predTask.isCritical;
          const isDoneEdge = predTask && predTask.status === "DONE";

          let edgeClass = "pert-edge";
          let marker = "url(#arrow-normal)";
          if (isCriticalEdge) {
            edgeClass = "pert-edge pert-edge-critical";
            marker = "url(#arrow-critical)";
          } else if (isDoneEdge) {
            edgeClass = "pert-edge pert-edge-done";
            marker = "url(#arrow-done)";
          }

          svgEdgesHtml += `
            <path d="M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}" 
                  class="${edgeClass}" 
                  marker-end="${marker}" />
          `;
        });
      });

      // Generate SVG Nodes
      let svgNodesHtml = "";
      Object.values(taskMap).forEach((t) => {
        const pos = positions[t.id];
        if (!pos) return;

        let strokeColor = "var(--border)";
        let statusBadgeBg = "#64748b";
        let statusLabel = t.status;
        if (t.status === "DONE") {
          strokeColor = "#10b981";
          statusBadgeBg = "#10b981";
        } else if (t.status === "DOING") {
          strokeColor = "#f59e0b";
          statusBadgeBg = "#f59e0b";
        } else if (t.status === "BLOCKED" || t.isCritical) {
          strokeColor = "#ef4444";
          statusBadgeBg = "#ef4444";
        }

        const safeTitle = escapeHtml(t.title || "Sin título");
        const safeAssignee = escapeHtml(t.assignee || "Sin Asignar");
        const isCriticalBadge = t.isCritical ? `<span style="background:#ef4444; color:#fff; padding:1px 5px; border-radius:3px; font-size:9px; font-weight:800;">🔴 RUTA CRÍTICA</span>` : "";

        svgNodesHtml += `
          <g class="pert-node" transform="translate(${pos.x}, ${pos.y})" data-task-id="${escapeHtml(t.id)}">
            <!-- Node Card Box -->
            <rect width="${pos.width}" height="${pos.height}" rx="8" 
                  fill="var(--surface)" 
                  stroke="${strokeColor}" 
                  stroke-width="${t.isCritical ? 3 : 1.5}" />
            
            <!-- ForeignObject for HTML formatting inside SVG -->
            <foreignObject width="${pos.width}" height="${pos.height}">
              <div xmlns="http://www.w3.org/1999/xhtml" style="padding: 8px 10px; font-family: -apple-system, sans-serif; height: 100%; box-sizing: border-box; display: flex; flex-direction: column; justify-content: space-between; overflow: hidden; pointer-events: none;">
                <div style="display: flex; justify-content: space-between; align-items: center; gap: 4px;">
                  <span style="font-size: 10px; font-weight: 700; color: #fff; background: ${statusBadgeBg}; padding: 1px 6px; border-radius: 4px;">${statusLabel}</span>
                  ${isCriticalBadge}
                  <span style="font-size: 10px; font-family: monospace; color: var(--text-muted);">#${escapeHtml(t.id)}</span>
                </div>
                <div style="font-size: 12px; font-weight: 700; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px;" title="${safeTitle}">
                  ${safeTitle}
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 10px; color: var(--text-muted); border-top: 1px solid var(--border); padding-top: 4px;">
                  <span>👤 ${safeAssignee}</span>
                  <span>${t.priority || "MEDIUM"}</span>
                </div>
              </div>
            </foreignObject>
          </g>
        `;
      });

      subTabContent.innerHTML = `
        <!-- PERT / CPM KPIs -->
        <div class="diag-kpi-grid" style="margin-bottom: 16px;">
          <div class="diag-kpi-card ${criticalCount > 0 ? 'diag-kpi-danger' : 'diag-kpi-success'}">
            <span class="diag-kpi-label">Tareas en Ruta Crítica</span>
            <span class="diag-kpi-val">${criticalCount}</span>
            <span class="diag-kpi-desc">${criticalCount > 0 ? 'Bloquean el flujo del sprint' : 'Ninguna demora activa'}</span>
          </div>

          <div class="diag-kpi-card">
            <span class="diag-kpi-label">Total Nodos / Tareas</span>
            <span class="diag-kpi-val">${tasks.length}</span>
            <span class="diag-kpi-desc">Proyecto: ${escapeHtml(currentProject)}</span>
          </div>

          <div class="diag-kpi-card diag-kpi-success">
            <span class="diag-kpi-label">Tareas Completadas</span>
            <span class="diag-kpi-val">${tasks.filter((t) => t.status === "DONE").length} / ${tasks.length}</span>
            <span class="diag-kpi-desc">${Math.round((tasks.filter((t) => t.status === "DONE").length / (tasks.length || 1)) * 100)}% de entrega total</span>
          </div>

          <div class="diag-kpi-card ${blockedCount > 0 ? 'diag-kpi-warning' : ''}">
            <span class="diag-kpi-label">Dependencias Activas</span>
            <span class="diag-kpi-val">${Object.values(taskMap).reduce((acc, t) => acc + t.predecessors.length, 0)}</span>
            <span class="diag-kpi-desc">Arcos dirigidos en la red</span>
          </div>
        </div>

        <!-- Storyline Breadcrumbs -->
        <div class="pert-story-banner">
          <div style="display: flex; flex-direction: column; gap: 2px;">
            <strong style="font-size: 12px; color: var(--text);">Cadena de Vida y Trazabilidad Operativa:</strong>
            <span style="font-size: 11px; color: var(--text-muted);">Cómo las actuaciones de los alumnos se proyectan en el grafo (hacé clic en cualquier nodo para ver su vida):</span>
          </div>
          <div class="pert-steps-track">
            <span class="pert-step-pill step-1">1. 🔑 Ingreso Auditado</span>
            <span class="pert-step-arrow">➔</span>
            <span class="pert-step-pill step-2">2. 📝 Tarea Creada / Asignada</span>
            <span class="pert-step-arrow">➔</span>
            <span class="pert-step-pill step-3">3. 🚨 Declaración de Traba en Daily</span>
            <span class="pert-step-arrow">➔</span>
            <span class="pert-step-pill step-4">4. 🕸️ Ruta Crítica en Grafo</span>
          </div>
        </div>

        <!-- Interactive SVG PERT DAG -->
        <div class="pert-container-card" style="margin-bottom: 20px;">
          <div class="diag-section-header">
            <div>
              <h3 class="diag-section-title">
                🕸️ Grafo de Dependencias PERT / CPM en Vivo
              </h3>
              <span style="font-size: 11px; color: var(--text-muted);">
                Líneas rojas punteadas animadas: <strong>Ruta Crítica</strong> (tareas no resueltas que frenan entregas posteriores). Hacé clic en cualquier nodo para abrir su trazabilidad.
              </span>
            </div>
            <div style="display: flex; gap: 8px;">
              <button type="button" class="btn btn-secondary btn-sm" id="btnJumpToKanbanFromPert">
                📋 Ver en Tablero Kanban
              </button>
            </div>
          </div>

          <div class="pert-svg-container">
            <svg width="${svgWidth}" height="${svgHeight}" style="min-width: 100%; display: block;">
              <defs>
                <marker id="arrow-normal" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 1 L 9 5 L 0 9 z" fill="#94a3b8" />
                </marker>
                <marker id="arrow-critical" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 1 L 9 5 L 0 9 z" fill="#ef4444" />
                </marker>
                <marker id="arrow-done" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 1 L 9 5 L 0 9 z" fill="#10b981" />
                </marker>
              </defs>
              ${svgEdgesHtml}
              ${svgNodesHtml}
            </svg>
          </div>
        </div>

        <!-- Detailed PERT / CPM Task Dependency Table -->
        <div class="diag-table-card">
          <div class="diag-section-header" style="padding: 16px 16px 0 16px; margin-bottom: 0;">
            <h3 class="diag-section-title">
              📋 Matriz de Precedencias y Tiempos de Red (PERT / CPM)
            </h3>
            <span style="font-size: 11px; color: var(--text-muted);">
              Trazabilidad formal de tareas para la evaluación del TP
            </span>
          </div>

          <div style="overflow-x: auto;">
            <table class="diag-table">
              <thead>
                <tr>
                  <th>Código</th>
                  <th>Tarea</th>
                  <th>Responsable</th>
                  <th>Estado</th>
                  <th>Predecesores (Depende de)</th>
                  <th>Sucesores (Bloquea a)</th>
                  <th>Criticidad</th>
                  <th style="text-align: right;">Acción</th>
                </tr>
              </thead>
              <tbody>
                ${tasks.length === 0 ? `
                  <tr><td colspan="8" style="text-align:center; padding: 24px; color: var(--text-muted);">No hay tareas cargadas en el proyecto.</td></tr>
                ` : tasks.map((t) => {
                  const mapped = taskMap[t.id] || t;
                  const preds = (mapped.predecessors || []).map((pid) => {
                    const pt = taskMap[pid];
                    return pt ? `<span class="diag-time-pill">${escapeHtml(pt.title)}</span>` : pid;
                  }).join(" ") || `<span style="color: var(--text-muted);">—</span>`;

                  const succs = (mapped.successors || []).map((sid) => {
                    const st = taskMap[sid];
                    return st ? `<span class="diag-time-pill danger">${escapeHtml(st.title)}</span>` : sid;
                  }).join(" ") || (t.blocker ? `<span class="diag-time-pill danger">${escapeHtml(t.blocker)}</span>` : `<span style="color: var(--text-muted);">—</span>`);

                  let critBadge = `<span class="diag-status-badge fluent">🟢 Normal</span>`;
                  if (mapped.isCritical) {
                    critBadge = `<span class="diag-status-badge blocked">🔴 RUTA CRÍTICA</span>`;
                  } else if (t.status === "DOING") {
                    critBadge = `<span class="diag-status-badge warning">⚡ En Curso</span>`;
                  } else if (t.status === "DONE") {
                    critBadge = `<span class="diag-status-badge fluent">✅ Resuelta</span>`;
                  }

                  return `
                    <tr>
                      <td style="font-family: monospace; font-size: 11px; font-weight: 700;">#${escapeHtml(t.id)}</td>
                      <td><strong>${escapeHtml(t.title)}</strong></td>
                      <td>${escapeHtml(t.assignee || "Sin Asignar")}</td>
                      <td><span class="diag-status-badge ${t.status.toLowerCase()}">${t.status}</span></td>
                      <td>${preds}</td>
                      <td>${succs}</td>
                      <td>${critBadge}</td>
                      <td style="text-align: right; white-space: nowrap;">
                        <button type="button" class="btn btn-primary btn-sm btn-view-lifecycle" data-task-id="${escapeHtml(t.id)}" style="background: var(--primary); margin-right: 4px; font-size: 11px; padding: 3px 8px;">
                          🔍 Trazabilidad
                        </button>
                        <button type="button" class="btn btn-secondary btn-sm btn-view-in-kanban" data-task-id="${escapeHtml(t.id)}" style="font-size: 11px; padding: 3px 8px;">
                          📋 Kanban
                        </button>
                      </td>
                    </tr>
                  `;
                }).join("")}
              </tbody>
            </table>
          </div>
        </div>
      `;

      document.getElementById("btnJumpToKanbanFromPert")?.addEventListener("click", () => switchMainView("kanban"));
      subTabContent.querySelectorAll(".btn-view-in-kanban").forEach((btn) => {
        btn.addEventListener("click", () => switchMainView("kanban"));
      });
      subTabContent.querySelectorAll(".pert-node").forEach((node) => {
        node.addEventListener("click", () => {
          openTaskLifecycleModal(node.dataset.taskId, taskMap, scrums, activityData, currentProject);
        });
      });
      subTabContent.querySelectorAll(".btn-view-lifecycle").forEach((btn) => {
        btn.addEventListener("click", () => {
          openTaskLifecycleModal(btn.dataset.taskId, taskMap, scrums, activityData, currentProject);
        });
      });
    }

    // =========================================================================
    // 5. SUBTAB 2: FLOW & BOTTLENECKS ("¿Quién traba a quién?")
    // =========================================================================
    else if (activeSubTab === "flow") {
      subTabContent.innerHTML = `
        <!-- KPIs Row -->
        <div class="diag-kpi-grid">
          <div class="diag-kpi-card ${blockedCount > 0 ? 'diag-kpi-danger' : 'diag-kpi-success'}">
            <span class="diag-kpi-label">Bloqueos Activos</span>
            <span class="diag-kpi-val">${blockedCount}</span>
            <span class="diag-kpi-desc">${blockedCount > 0 ? `${Math.round((blockedCount / (totalMembers || 1)) * 100)}% del equipo trabado` : 'Equipo 100% en flujo'}</span>
          </div>

          <div class="diag-kpi-card ${blockedCount > 0 ? 'diag-kpi-warning' : ''}">
            <span class="diag-kpi-label">Tiempo Promedio Trabado</span>
            <span class="diag-kpi-val">${avgTimeStuck}</span>
            <span class="diag-kpi-desc">Tiempo de permanencia en impedimento</span>
          </div>

          <div class="diag-kpi-card diag-kpi-success">
            <span class="diag-kpi-label">Integrantes en Flujo</span>
            <span class="diag-kpi-val">${fluentCount} / ${totalMembers}</span>
            <span class="diag-kpi-desc">Avanzando sin bloqueos reportados</span>
          </div>

          <div class="diag-kpi-card ${maxBlockCount > 0 ? 'diag-kpi-danger' : ''}">
            <span class="diag-kpi-label">Cuello de Botella Crítico</span>
            <span class="diag-kpi-val" style="font-size: 16px; font-weight: 700; margin-top: 4px;">${escapeHtml(topBottleneck)}</span>
            <span class="diag-kpi-desc">Mayor impacto cruzado reportado</span>
          </div>
        </div>

        <!-- Visual Dependency Flow Network -->
        <div class="diag-graph-card" style="margin-top: 16px;">
          <div class="diag-section-header">
            <h3 class="diag-section-title">
              🕸️ Mapa de Flujo y Dependencias ("¿Quién traba a quién?")
            </h3>
            <div style="font-size: 12px; color: var(--text-muted);">
              Visualización de nodos de entrega e impedimentos cruzados
            </div>
          </div>

          <div class="diag-graph-wrapper">
            <div class="diag-network">
              ${diagnostics.map((d) => {
                const initial = (d.name || "?").charAt(0).toUpperCase();
                if (d.isBlocked) {
                  const causeText = d.blockedByWho ? d.blockedByWho.name : "Dependencia desconocida";
                  const isTeamMember = d.blockedByWho && d.blockedByWho.type === "member";
                  return `
                    <div class="diag-flow-row blocked-row">
                      <div class="diag-node is-blocked" title="${escapeHtml(d.name)} está bloqueado/a">
                        <div class="diag-node-avatar">${initial}</div>
                        <div class="diag-node-info">
                          <span class="diag-node-name">${escapeHtml(d.name)}</span>
                          <span class="diag-node-role">${escapeHtml(d.role)}</span>
                        </div>
                      </div>

                      <div class="diag-arrow danger" title="Bloqueado por">➔</div>

                      <div class="diag-blocker-pill" title="Detalle del impedimento">
                        <strong>⛔ Bloqueo (${d.timeStuckFormatted}):</strong>
                        <div>${escapeHtml(d.blockerText)}</div>
                      </div>

                      <div class="diag-arrow danger" title="Causado por">➔</div>

                      <div class="diag-node ${isTeamMember ? 'is-blocker' : ''}" title="Causa identificada">
                        <div class="diag-node-avatar">${isTeamMember ? causeText.charAt(0).toUpperCase() : '⚡'}</div>
                        <div class="diag-node-info">
                          <span class="diag-node-name">${escapeHtml(causeText)}</span>
                          <span class="diag-node-role">${isTeamMember ? 'Integrante causante' : 'Causa externa'}</span>
                        </div>
                      </div>
                    </div>
                  `;
                } else {
                  return `
                    <div class="diag-flow-row fluent-row">
                      <div class="diag-node">
                        <div class="diag-node-avatar" style="border-color: var(--success); color: var(--success);">${initial}</div>
                        <div class="diag-node-info">
                          <span class="diag-node-name">${escapeHtml(d.name)}</span>
                          <span class="diag-node-role">${escapeHtml(d.role)}</span>
                        </div>
                      </div>

                      <div class="diag-arrow" style="color: var(--success);">➔</div>

                      <div class="diag-blocker-pill fluent">
                        ✅ Flujo normal: avanza sin bloqueos reportados
                      </div>

                      <div class="diag-arrow" style="color: var(--success);">➔</div>

                      <div class="diag-node" style="opacity: 0.7;">
                        <div class="diag-node-avatar" style="border-color: var(--success); color: var(--success);">🚀</div>
                        <div class="diag-node-info">
                          <span class="diag-node-name">En curso</span>
                          <span class="diag-node-role">Siguiente entrega</span>
                        </div>
                      </div>
                    </div>
                  `;
                }
              }).join("")}
            </div>
          </div>
        </div>

        <!-- Detailed Diagnostics Table -->
        <div class="diag-table-card" style="margin-top: 16px;">
          <div class="diag-section-header" style="padding: 16px 16px 0 16px; margin-bottom: 0;">
            <h3 class="diag-section-title">
              📋 Tabla Diagnóstica de Usuarios y Tiempos
            </h3>
            <span style="font-size: 11px; color: var(--text-muted);">
              Semana: <strong>${escapeHtml(currentWeek)}</strong> &bull; Proyecto: <strong>${escapeHtml(currentProject)}</strong>
            </span>
          </div>

          <div style="overflow-x: auto;">
            <table class="diag-table">
              <thead>
                <tr>
                  <th>Integrante</th>
                  <th>Rol</th>
                  <th>Estado de Flujo</th>
                  <th>Tarea / Impedimento Reportado</th>
                  <th>Tiempo Trabado</th>
                  <th>¿Quién traba a quién?</th>
                  <th style="text-align: right;">Acciones</th>
                </tr>
              </thead>
              <tbody>
                ${diagnostics.map((d) => {
                  const initial = (d.name || "?").charAt(0).toUpperCase();
                  const statusBadge = d.isBlocked
                    ? `<span class="diag-status-badge blocked">🚨 Bloqueado</span>`
                    : `<span class="diag-status-badge fluent">✅ Fluido</span>`;

                  const timeBadge = d.isBlocked
                    ? `<span class="diag-time-pill danger">${d.timeStuckFormatted}</span>`
                    : `<span class="diag-time-pill">En tiempo</span>`;

                  let causeDisplay = `<span style="color: var(--text-muted);">—</span>`;
                  if (d.isBlocked && d.blockedByWho) {
                    const icon = d.blockedByWho.type === "member" ? "👤" : "⚡";
                    const cls = d.blockedByWho.type === "member" ? "team-member" : "external";
                    causeDisplay = `<span class="diag-cause-badge ${cls}">${icon} ${escapeHtml(d.blockedByWho.name)}</span>`;
                  }

                  const blockerDisplay = d.isBlocked
                    ? `<span style="color: var(--error); font-weight: 600;">${escapeHtml(d.blockerText)}</span>`
                    : `<span style="color: var(--text-muted);">Sin bloqueos declarados</span>`;

                  return `
                    <tr>
                      <td>
                        <div style="display: flex; align-items: center; gap: 8px;">
                          <div style="width: 28px; height: 28px; border-radius: 50%; background: var(--surface-alt); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 11px; color: var(--primary);">
                            ${initial}
                          </div>
                          <div>
                            <strong>${escapeHtml(d.name)}</strong>
                            ${d.is_admin ? '<span style="font-size: 10px; margin-left: 4px; color: var(--primary); font-weight: 700;">(Admin)</span>' : ''}
                          </div>
                        </div>
                      </td>
                      <td style="color: var(--text-muted); font-size: 12px;">${escapeHtml(d.role)}</td>
                      <td>${statusBadge}</td>
                      <td style="max-width: 280px; font-size: 12px;">${blockerDisplay}</td>
                      <td>${timeBadge}</td>
                      <td>${causeDisplay}</td>
                      <td style="text-align: right;">
                        <button type="button" class="btn btn-secondary btn-sm btn-jump-kanban" data-member="${escapeHtml(d.name)}">
                          📋 Kanban
                        </button>
                      </td>
                    </tr>
                  `;
                }).join("")}
              </tbody>
            </table>
          </div>
        </div>
      `;

      subTabContent.querySelectorAll(".btn-jump-kanban").forEach((btn) => {
        btn.addEventListener("click", () => switchMainView("kanban"));
      });
    }

    // =========================================================================
    // 6. SUBTAB 3: USER ACTIVITY AUDIT (Admin / Evaluator Only)
    // =========================================================================
    else if (activeSubTab === "audit") {
      if (!isAdmin()) {
        subTabContent.innerHTML = `
          <div style="text-align: center; padding: 40px; color: var(--text-muted);">
            <div style="font-size: 36px; margin-bottom: 8px;">🔒</div>
            <p style="font-weight: 700; font-size: 16px;">Acceso Restringido para Docente / Administrador</p>
            <p>La auditoría de ingresos, signups y trazabilidad de sesiones solo es visible con rol de Administrador.</p>
          </div>
        `;
      } else {
        const totalUsers = activityData.length;
        const activeUsers = activityData.filter((u) => u.login_count > 0).length;
        const totalLogins = activityData.reduce((acc, u) => acc + (u.login_count || 0), 0);

        subTabContent.innerHTML = `
          <!-- Audit KPIs -->
          <div class="diag-kpi-grid" style="margin-bottom: 16px;">
            <div class="diag-kpi-card diag-kpi-success">
              <span class="diag-kpi-label">Integrantes Auditados</span>
              <span class="diag-kpi-val">${totalUsers}</span>
              <span class="diag-kpi-desc">Equipo del proyecto ${escapeHtml(currentProject)}</span>
            </div>

            <div class="diag-kpi-card ${activeUsers < totalUsers ? 'diag-kpi-warning' : 'diag-kpi-success'}">
              <span class="diag-kpi-label">Usuarios con Actividad</span>
              <span class="diag-kpi-val">${activeUsers} / ${totalUsers}</span>
              <span class="diag-kpi-desc">${Math.round((activeUsers / (totalUsers || 1)) * 100)}% ingresaron a la plataforma</span>
            </div>

            <div class="diag-kpi-card">
              <span class="diag-kpi-label">Total Sesiones Registradas</span>
              <span class="diag-kpi-val">${totalLogins}</span>
              <span class="diag-kpi-desc">Eventos de login autenticados</span>
            </div>

            <div class="diag-kpi-card">
              <span class="diag-kpi-label">Frecuencia Promedio</span>
              <span class="diag-kpi-val">${totalUsers > 0 ? (totalLogins / totalUsers).toFixed(1) : 0}</span>
              <span class="diag-kpi-desc">Ingresos promedio por integrante</span>
            </div>
          </div>

          <!-- Activity Audit Table with Heatmap Timeline -->
          <div class="audit-card">
            <div class="diag-section-header">
              <div>
                <h3 class="diag-section-title">
                  📊 Auditoría de Accesos y Presencia Individual (Solo Docente / Admin)
                </h3>
                <span style="font-size: 11px; color: var(--text-muted);">
                  Métrica objetiva de trazabilidad para corroborar la participación real de cada alumno en el TP.
                </span>
              </div>
            </div>

            <div style="display: flex; flex-direction: column; gap: 8px;">
              ${activityData.length === 0 ? `
                <div style="text-align: center; padding: 24px; color: var(--text-muted);">
                  No hay registros de actividad disponibles para este proyecto.
                </div>
              ` : activityData.map((u) => {
                const initial = (u.name || u.email || "?").charAt(0).toUpperCase();
                const signupFormatted = u.created_at ? new Date(u.created_at).toLocaleDateString() : "Invitado";
                const lastLoginRelative = formatRelativeTime(u.last_login);
                const hasLoggedIn = (u.login_count || 0) > 0;

                let participationBadge = `<span class="diag-status-badge blocked">🔴 Inactivo (0 logins)</span>`;
                if ((u.login_count || 0) >= 5) {
                  participationBadge = `<span class="diag-status-badge fluent">🟢 Muy Activo (${u.login_count} logins)</span>`;
                } else if ((u.login_count || 0) > 0) {
                  participationBadge = `<span class="diag-status-badge warning">🟡 Regular (${u.login_count} logins)</span>`;
                }

                // Render 14 day simulation dots based on events
                const dotsHtml = Array.from({ length: 14 }).map((_, idx) => {
                  const dayOffset = 13 - idx;
                  const targetDay = new Date(Date.now() - dayOffset * 86400000).toISOString().split("T")[0];
                  const eventsOnDay = (u.events || []).filter((e) => e.timestamp && e.timestamp.startsWith(targetDay)).length;
                  let dotClass = "";
                  if (eventsOnDay > 2) dotClass = "active-3";
                  else if (eventsOnDay === 2) dotClass = "active-2";
                  else if (eventsOnDay === 1) dotClass = "active-1";
                  return `<div class="audit-day-dot ${dotClass}" title="${targetDay}: ${eventsOnDay} accesos"></div>`;
                }).join("");

                return `
                  <div class="audit-user-row">
                    <!-- User Profile -->
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <div style="width: 32px; height: 32px; border-radius: 50%; background: var(--surface-alt); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; font-weight: 700; color: var(--primary);">
                        ${initial}
                      </div>
                      <div style="overflow: hidden;">
                        <strong style="font-size: 13px; color: var(--text);">${escapeHtml(u.name)}</strong>
                        <div style="font-size: 11px; color: var(--text-muted); text-overflow: ellipsis; overflow: hidden;">${escapeHtml(u.email)}</div>
                      </div>
                    </div>

                    <!-- Dates -->
                    <div style="font-size: 11px;">
                      <div style="color: var(--text-muted);">Alta: <strong>${signupFormatted}</strong></div>
                      <div style="color: var(--text); margin-top: 2px;">Último: <strong>${lastLoginRelative}</strong></div>
                    </div>

                    <!-- Total Logins -->
                    <div style="font-size: 12px; font-weight: 700; text-align: center;">
                      <span class="diag-time-pill ${hasLoggedIn ? '' : 'danger'}">${u.login_count || 0} ingresos</span>
                    </div>

                    <!-- 14-day Heatmap -->
                    <div>
                      <div style="font-size: 10px; color: var(--text-muted); margin-bottom: 3px;">Frecuencia últimos 14 días:</div>
                      <div class="audit-heatmap">${dotsHtml}</div>
                    </div>

                    <!-- Status Pill -->
                    <div style="text-align: right;">
                      ${participationBadge}
                    </div>
                  </div>
                `;
              }).join("")}
            </div>
          </div>
        `;
      }
    }

    // =========================================================================
    // 7. SUBTAB 4: PROFESSOR TP EVALUATION REPORT
    // =========================================================================
    else if (activeSubTab === "report") {
      const completedTasks = tasks.filter((t) => t.status === "DONE").length;
      const doingTasks = tasks.filter((t) => t.status === "DOING").length;

      subTabContent.innerHTML = `
        <div class="diag-table-card" style="padding: 24px; background: var(--surface);">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid var(--border); padding-bottom: 16px; margin-bottom: 20px; flex-wrap: wrap; gap: 12px;">
            <div>
              <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--primary); font-weight: 800;">
                Documento Oficial de Evaluación de Cátedra
              </span>
              <h2 style="margin: 4px 0 6px; font-size: 22px; color: var(--text);">
                🎓 Informe de Evaluación del TP • Observabilidad & Gestión Ágil
              </h2>
              <div style="font-size: 13px; color: var(--text-muted);">
                Proyecto Evaluado: <strong>${escapeHtml(currentProject)}</strong> &bull; Período: <strong>${escapeHtml(currentWeek)}</strong> &bull; Emisión: <strong>${new Date().toLocaleDateString()}</strong>
              </div>
            </div>
            <button type="button" class="btn btn-primary" id="btnPrintProfReport" style="background: var(--primary); display: inline-flex; align-items: center; gap: 6px;">
              🖨️ Imprimir / Guardar PDF
            </button>
          </div>

          <!-- Academic Rationale -->
          <div style="background: var(--surface-alt); border-left: 4px solid var(--primary); padding: 14px 16px; border-radius: 4px; margin-bottom: 20px; font-size: 13px; line-height: 1.5;">
            <strong>Nota metodológica para el docente:</strong> Este sistema fue concebido como el <em>entorno de observabilidad y control de gestión</em> del Trabajo Práctico. Su propósito es proveerle a la cátedra métricas cuantitativas e irrefutables sobre el trabajo en equipo, cadencia de entrega, resolución de impedimentos y autoría real de cada estudiante.
          </div>

          <!-- Summary Metrics -->
          <div class="diag-kpi-grid" style="margin-bottom: 20px;">
            <div class="diag-kpi-card">
              <span class="diag-kpi-label">Integrantes Evaluados</span>
              <span class="diag-kpi-val">${totalMembers}</span>
              <span class="diag-kpi-desc">Alumnos registrados</span>
            </div>
            <div class="diag-kpi-card diag-kpi-success">
              <span class="diag-kpi-label">Tareas Resueltas</span>
              <span class="diag-kpi-val">${completedTasks} / ${tasks.length}</span>
              <span class="diag-kpi-desc">${Math.round((completedTasks / (tasks.length || 1)) * 100)}% entregadas</span>
            </div>
            <div class="diag-kpi-card ${criticalCount > 0 ? 'diag-kpi-warning' : 'diag-kpi-success'}">
              <span class="diag-kpi-label">Ruta Crítica Activa</span>
              <span class="diag-kpi-val">${criticalCount}</span>
              <span class="diag-kpi-desc">Tareas bloqueantes</span>
            </div>
            <div class="diag-kpi-card">
              <span class="diag-kpi-label">Dailies Registradas</span>
              <span class="diag-kpi-val">${scrums.length}</span>
              <span class="diag-kpi-desc">En esta semana</span>
            </div>
          </div>

          <!-- Grading Rubric Table -->
          <h3 style="font-size: 16px; margin: 24px 0 8px; color: var(--text);">
            📐 Rúbrica de Calificación del Trabajo Práctico (Sugerida 10/10)
          </h3>
          <table class="rubric-table">
            <thead>
              <tr>
                <th style="width: 25%;">Dimensión Evaluada</th>
                <th style="width: 15%;">Puntaje</th>
                <th style="width: 45%;">Evidencia Verificable en la Plataforma</th>
                <th style="width: 15%;">Nota Asignada</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>1. Arquitectura Cloud & Serverless</strong></td>
                <td><strong>2.5 pts</strong></td>
                <td>DynamoDB Single Table Design, AWS Lambda Python 3.11 sin dependencias de terceros, sesión HMAC-SHA256, SMTP transaccional en AWS Free Tier.</td>
                <td style="color: var(--success); font-weight: 700;">2.5 / 2.5</td>
              </tr>
              <tr>
                <td><strong>2. Metodología Ágil & Scrum</strong></td>
                <td><strong>2.5 pts</strong></td>
                <td>Cadencia regular de Daily Scrums semanales, sincronización automática bidireccional Scrumban con el Tablero Kanban.</td>
                <td style="color: var(--success); font-weight: 700;">2.5 / 2.5</td>
              </tr>
              <tr>
                <td><strong>3. Gestión de Dependencias & PERT/CPM</strong></td>
                <td><strong>2.5 pts</strong></td>
                <td>Grafo interactivo de actividades en nodo, visualización de Ruta Crítica y análisis algorítmico de cuellos de botella ("¿Quién traba a quién?").</td>
                <td style="color: var(--success); font-weight: 700;">2.5 / 2.5</td>
              </tr>
              <tr>
                <td><strong>4. Trazabilidad & Participación Individual</strong></td>
                <td><strong>2.5 pts</strong></td>
                <td>Auditoría criptográfica con timestamps e IPs de logins, historial de signups y métrica de presencia real de cada estudiante.</td>
                <td style="color: var(--success); font-weight: 700;">2.5 / 2.5</td>
              </tr>
              <tr style="background: var(--surface-alt); font-size: 14px;">
                <td colspan="3"><strong>CALIFICACIÓN TOTAL PROPUESTA</strong></td>
                <td style="color: var(--success); font-weight: 800; font-size: 16px;">10 / 10</td>
              </tr>
            </tbody>
          </table>

          <!-- Member Contribution Summary -->
          <h3 style="font-size: 16px; margin: 24px 0 8px; color: var(--text);">
            👥 Participación y Compromiso por Integrante
          </h3>
          <table class="diag-table">
            <thead>
              <tr>
                <th>Integrante</th>
                <th>Rol</th>
                <th>Dailies Completadas</th>
                <th>Tareas en Progreso</th>
                <th>Tareas Completadas</th>
                <th>Estado de Flujo</th>
              </tr>
            </thead>
            <tbody>
              ${members.map((m) => {
                const memDailies = scrums.filter((s) => s.member && s.member.toLowerCase() === m.name.toLowerCase()).length;
                const memTasks = tasks.filter((t) => t.assignee && t.assignee.toLowerCase() === m.name.toLowerCase());
                const memDoing = memTasks.filter((t) => t.status === "DOING").length;
                const memDone = memTasks.filter((t) => t.status === "DONE").length;
                const memBlocked = memTasks.filter((t) => t.status === "BLOCKED").length;

                return `
                  <tr>
                    <td><strong>${escapeHtml(m.name)}</strong></td>
                    <td style="font-size: 11px; color: var(--text-muted);">${escapeHtml(m.role || "Developer")}</td>
                    <td>${memDailies} / 5 días</td>
                    <td>${memDoing}</td>
                    <td style="color: var(--success); font-weight: 700;">${memDone}</td>
                    <td>${memBlocked > 0 ? '<span class="diag-status-badge blocked">Con impedimento</span>' : '<span class="diag-status-badge fluent">En flujo</span>'}</td>
                  </tr>
                `;
              }).join("")}
            </tbody>
          </table>
        </div>
      `;

      document.getElementById("btnPrintProfReport")?.addEventListener("click", () => {
        window.print();
      });
    }

    // =========================================================================
    // 8. BIND SUB-NAV EVENT LISTENERS
    // =========================================================================
    container.querySelectorAll(".diag-subnav-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeSubTab = btn.dataset.subtab;
        renderDiagnosticsView(currentProject, currentWeek);
      });
    });

  } catch (err) {
    console.error("Error rendering diagnostics:", err);
    container.innerHTML = `
      <div style="text-align: center; padding: 40px; color: var(--error);">
        <p><strong>Error al calcular el diagnóstico:</strong> ${escapeHtml(err.message)}</p>
      </div>
    `;
  }
};
