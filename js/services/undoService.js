/**
 * Undo / Redo service (in-memory command stack, session scope).
 * Covers destructive ops (delete/create) via the trash API: undo restores,
 * redo re-trashes. Updates are snapshots (before/after) when the caller
 * provides both images.
 */
import { showToast } from "../components/uiFeedback.js";

const MAX_HISTORY = 20;
const undoStack = [];
const redoStack = [];
const listeners = new Set();

export const canUndo = () => undoStack.length > 0;
export const canRedo = () => redoStack.length > 0;

export const subscribeUndoState = (listener) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

const notify = () => {
  const snapshot = { canUndo: canUndo(), canRedo: canRedo() };
  listeners.forEach((fn) => {
    try {
      fn(snapshot);
    } catch {
      // Listener errors must never break undo/redo
    }
  });
};

export const clearHistory = () => {
  undoStack.length = 0;
  redoStack.length = 0;
  notify();
};

const isTypingTarget = () => {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
};

/**
 * @param {{ label: string, undo: () => Promise<void>, redo: () => Promise<void>, toast?: string }} action
 */
export const pushHistory = (action) => {
  undoStack.push(action);
  if (undoStack.length > MAX_HISTORY) undoStack.shift();
  redoStack.length = 0;
  notify();
  if (action.toast !== null) {
    showToast(action.toast || `${action.label}.`, "success", {
      label: "Deshacer",
      onClick: () => undoLast(),
    });
  }
};

export const undoLast = async () => {
  const action = undoStack.pop();
  if (!action) {
    showToast("No hay nada que deshacer.", "error");
    return;
  }
  try {
    await action.undo();
    redoStack.push(action);
    notify();
    showToast(`Deshecho: ${action.label}.`, "success", {
      label: "Rehacer",
      onClick: () => redoLast(),
    });
  } catch (err) {
    showToast(err.message || "No se pudo deshacer.", "error");
  }
};

export const redoLast = async () => {
  const action = redoStack.pop();
  if (!action) {
    showToast("No hay nada que rehacer.", "error");
    return;
  }
  try {
    await action.redo();
    undoStack.push(action);
    notify();
    showToast(`Rehecho: ${action.label}.`);
  } catch (err) {
    showToast(err.message || "No se pudo rehacer.", "error");
  }
};

let shortcutsInit = false;
export const initUndoShortcuts = () => {
  if (shortcutsInit) return;
  shortcutsInit = true;
  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || isTypingTarget()) return;
    const key = e.key.toLowerCase();
    if (key === "z" && !e.shiftKey) {
      e.preventDefault();
      undoLast();
    } else if ((key === "y") || (key === "z" && e.shiftKey)) {
      e.preventDefault();
      redoLast();
    }
  });
};
