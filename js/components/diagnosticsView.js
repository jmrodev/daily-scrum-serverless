import { api } from "../services/api.js";
import { state } from "../state.js";
import { escapeHtml } from "../services/domUtils.js";
import { showToast } from "./uiFeedback.js";
import { switchMainView } from "../app.js";

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

export const renderDiagnosticsView = async (project = null, week = null) => {
  const container = document.getElementById("diagnosticsViewContainer");
  if (!container) return;

  const currentProject = project || document.getElementById("boardProject")?.value || state.currentProject;
  const currentWeek = week || document.getElementById("boardWeek")?.value || state.currentWeek;

  if (!currentProject) {
    container.innerHTML = `
      <div style="text-align: center; padding: 40px; color: var(--text-muted);">
        <div style="font-size: 36px; margin-bottom: 8px;">📂</div>
        <p style="font-weight: 600;">Seleccioná un proyecto para ver el diagnóstico de flujo y bloqueos.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div style="text-align: center; padding: 30px; color: var(--text-muted);">
      <div class="spinner" style="margin: 0 auto 12px;"></div>
      <p>Calculando diagnóstico de flujo y dependencias...</p>
    </div>
  `;

  try {
    const [members, scrums, tasks] = await Promise.all([
      api.getMembers(currentProject),
      api.getWeeklyScrums(currentProject, currentWeek),
      api.getTasks(currentProject),
    ]);

    const now = Date.now();
    const memberNames = members.map((m) => m.name);

    // Analyze each member's blockers and dependencies
    const diagnostics = members.map((member) => {
      const memTasks = tasks.filter((t) => t.assignee === member.name);
      const blockedTasks = memTasks.filter((t) => t.status === "BLOCKED");

      // Daily Scrum blockers for this member
      const memberScrums = scrums.filter((s) => s.member === member.name && isRealBlocker(s.blockers));
      
      let isBlocked = blockedTasks.length > 0 || memberScrums.length > 0;
      let blockerText = "";
      let reportedAt = null;
      let timeStuckMs = 0;
      let blockedByWho = null;

      if (blockedTasks.length > 0) {
        const topTask = blockedTasks[0];
        blockerText = `[Tarea] ${topTask.title}`;
        reportedAt = topTask.updated_at || topTask.created_at;
        if (reportedAt) {
          timeStuckMs = now - new Date(reportedAt).getTime();
        }
      } else if (memberScrums.length > 0) {
        // Pick the most recent daily blocker
        const sortedScrums = [...memberScrums].sort((a, b) => {
          const tA = a.updated_at ? new Date(a.updated_at).getTime() : 0;
          const tB = b.updated_at ? new Date(b.updated_at).getTime() : 0;
          return tB - tA;
        });
        const topScrum = sortedScrums[0];
        blockerText = `[Daily ${topScrum.day}] ${topScrum.blockers}`;
        reportedAt = topScrum.updated_at || null;
        if (reportedAt) {
          timeStuckMs = now - new Date(reportedAt).getTime();
        }
      }

      // Detect who is blocking whom
      if (isBlocked && blockerText) {
        const lowerText = blockerText.toLowerCase();
        for (const otherName of memberNames) {
          if (otherName !== member.name && lowerText.includes(otherName.toLowerCase())) {
            blockedByWho = { type: "member", name: otherName };
            break;
          }
        }
        if (!blockedByWho) {
          if (lowerText.includes("servidor") || lowerText.includes("api") || lowerText.includes("infra") || lowerText.includes("aws")) {
            blockedByWho = { type: "external", name: "Infraestructura / Backend" };
          } else if (lowerText.includes("cliente") || lowerText.includes("diseño") || lowerText.includes("ux")) {
            blockedByWho = { type: "external", name: "Diseño / Cliente" };
          } else if (lowerText.includes("tercero") || lowerText.includes("externo")) {
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

    // Cross-reference: Who is blocking how many people?
    const blockingCounts = {};
    diagnostics.forEach((d) => {
      if (d.blockedByWho && d.blockedByWho.type === "member") {
        blockingCounts[d.blockedByWho.name] = (blockingCounts[d.blockedByWho.name] || 0) + 1;
      }
    });

    // Summary Metrics
    const totalMembers = members.length;
    const blockedCount = diagnostics.filter((d) => d.isBlocked).length;
    const fluentCount = totalMembers - blockedCount;
    const totalTimeStuck = diagnostics.reduce((acc, d) => acc + (d.timeStuckMs || 0), 0);
    const avgTimeStuck = blockedCount > 0 ? formatDuration(Math.round(totalTimeStuck / blockedCount)) : "0 h";

    // Most impactful bottleneck
    let topBottleneck = "Ninguno (Flujo 100% fluido)";
    let maxBlockCount = 0;
    Object.entries(blockingCounts).forEach(([name, cnt]) => {
      if (cnt > maxBlockCount) {
        maxBlockCount = cnt;
        topBottleneck = `${name} (frena a ${cnt} integrante${cnt > 1 ? "s" : ""})`;
      }
    });

    // Render HTML Output
    container.innerHTML = `
      <div class="diag-container">
        <!-- 1. KPIs Row -->
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
            <span class="diag-kpi-desc">Origen con mayor impacto cruzado</span>
          </div>
        </div>

        <!-- 2. Visual Dependency & Flow Network -->
        <div class="diag-graph-card">
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
                      <!-- Node Left: Blocked Member -->
                      <div class="diag-node is-blocked" title="${escapeHtml(d.name)} está bloqueado/a">
                        <div class="diag-node-avatar">${initial}</div>
                        <div class="diag-node-info">
                          <span class="diag-node-name">${escapeHtml(d.name)}</span>
                          <span class="diag-node-role">${escapeHtml(d.role)}</span>
                        </div>
                      </div>

                      <!-- Arrow to Blocker -->
                      <div class="diag-arrow danger" title="Bloqueado por">➔</div>

                      <!-- Middle Node: The Blocker / Task -->
                      <div class="diag-blocker-pill" title="Detalle del impedimento">
                        <strong>⛔ Bloqueo (${d.timeStuckFormatted}):</strong>
                        <div>${escapeHtml(d.blockerText)}</div>
                      </div>

                      <!-- Arrow to Cause -->
                      <div class="diag-arrow danger" title="Causado por">➔</div>

                      <!-- Node Right: The Cause / Responsible -->
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

        <!-- 3. Detailed Diagnostics Table -->
        <div class="diag-table-card">
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
                        <button type="button" class="btn btn-secondary btn-sm btn-jump-kanban" data-member="${escapeHtml(d.name)}" title="Ver tareas de ${escapeHtml(d.name)} en el Kanban">
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
      </div>
    `;

    // Bind Jump to Kanban buttons
    container.querySelectorAll(".btn-jump-kanban").forEach((btn) => {
      btn.addEventListener("click", () => {
        switchMainView("kanban");
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
