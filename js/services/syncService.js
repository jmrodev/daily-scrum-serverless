/**
 * Smart Polling & Real-Time Sync Service
 * Maintains live data synchronization across active tabs and devices without WebSockets.
 */
import { state, isAdmin } from "../state.js";
import { isDraggingTask } from "../components/kanbanBoard.js";
import { loadMembersChipList } from "../components/adminModal.js";

const SYNC_INTERVAL_MS = 4500; // 4.5 seconds poll frequency
let syncTimer = null;
let isSyncing = false;
let refreshViewCallback = null;

export const setSyncViewCallback = (cb) => {
  refreshViewCallback = cb;
};

/**
 * Checks if the user is actively interacting with an input, modal, or dragging an item.
 * If true, background sync is skipped to preserve focus, state, and user inputs.
 */
export const isUserInteracting = () => {
  // 1. Skip if document/tab is not visible
  if (document.visibilityState !== "visible") return true;

  // 2. Skip if user is dragging a Kanban task
  if (typeof isDraggingTask === "function" && isDraggingTask()) return true;

  // 3. Skip if an interactive editing modal is open
  const activeModal = document.querySelector(
    "#scrumModal.open, #taskModal.open, #confirmModal.open, #promptModal.open"
  );
  if (activeModal) return true;

  // 4. Skip if the user is typing in any input or textarea
  const activeTag = document.activeElement?.tagName;
  if (activeTag === "INPUT" || activeTag === "TEXTAREA") return true;

  return false;
};

/**
 * Executes a single silent background sync pass.
 */
export const runSilentSync = async () => {
  if (isSyncing) return;
  if (!state.currentUser?.token) return;
  if (!state.activeProject) return;
  if (isUserInteracting()) return;

  isSyncing = true;
  try {
    // 1. Silent refresh of active main view (Daily Matrix, Kanban Board, or Diagnostics)
    if (refreshViewCallback) {
      await refreshViewCallback(true);
    }

    // 2. If Admin Modal is open, silently update the member list if viewing members tab
    const manageModal = document.getElementById("manageModal");
    if (manageModal && manageModal.classList.contains("open") && isAdmin()) {
      const membersTab = document.getElementById("adminTabMembers");
      if (membersTab && membersTab.style.display !== "none") {
        await loadMembersChipList(true);
      }
    }
  } catch (err) {
    console.debug("[SyncService] Background sync warning:", err);
  } finally {
    isSyncing = false;
  }
};

/**
 * Initializes the background synchronization loop and window visibility listeners.
 */
export const startSyncService = (refreshCb) => {
  if (refreshCb) setSyncViewCallback(refreshCb);

  if (syncTimer) {
    clearInterval(syncTimer);
  }

  syncTimer = setInterval(runSilentSync, SYNC_INTERVAL_MS);

  // Instant refresh when user switches back to this tab or window gains focus
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      runSilentSync();
    }
  });

  window.addEventListener("focus", () => {
    runSilentSync();
  });
};

/**
 * Stops the background sync loop (e.g., on logout).
 */
export const stopSyncService = () => {
  if (syncTimer) {
    clearInterval(syncTimer);
    syncTimer = null;
  }
};
