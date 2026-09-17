/**
 * Dynamic Week Selector Component
 * Loads distinct weeks from DynamoDB + current calendar week + manual '➕' button.
 */
import { api } from "../services/api.js";
import { getCalendarWeekNumber } from "../services/dateUtils.js";
import { showToast } from "./uiFeedback.js";
import { state } from "../state.js";

let onWeekChangedCallback = null;

export const initWeekSelector = async (project, targetWeek = null) => {
  const weekSelect = document.getElementById("boardWeek");
  if (!weekSelect) return;

  const prevVal = targetWeek || weekSelect.value;
  const currentCalWeekNum = getCalendarWeekNumber();
  const currentWeekKey = `WEEK ${currentCalWeekNum}`;

  let loadedWeeks = [];
  if (project) {
    try {
      loadedWeeks = await api.getWeeks(project);
    } catch (e) {
      console.error("Error loading weeks for project", e);
    }
  }

  const weekSet = new Set(loadedWeeks);
  weekSet.add(currentWeekKey);
  if (prevVal) weekSet.add(prevVal);

  const sortedWeeks = Array.from(weekSet).sort((a, b) => {
    const numA = parseInt((a.match(/\d+/) || [0])[0], 10);
    const numB = parseInt((b.match(/\d+/) || [0])[0], 10);
    return numA - numB;
  });

  weekSelect.innerHTML = "";
  sortedWeeks.forEach((w) => {
    const opt = document.createElement("option");
    opt.value = w;
    opt.textContent = w.replace(/^WEEK\s*/i, "Semana ");
    weekSelect.appendChild(opt);
  });

  if (prevVal && sortedWeeks.includes(prevVal)) {
    weekSelect.value = prevVal;
  } else if (sortedWeeks.includes(currentWeekKey)) {
    weekSelect.value = currentWeekKey;
  } else if (sortedWeeks.length > 0) {
    weekSelect.value = sortedWeeks[sortedWeeks.length - 1];
  }

  state.activeWeek = weekSelect.value;
};

export const addNewWeek = async () => {
  const weekSelect = document.getElementById("boardWeek");
  if (!weekSelect) return;

  let maxNum = 0;
  Array.from(weekSelect.options).forEach((opt) => {
    const num = parseInt((opt.value.match(/\d+/) || [0])[0], 10);
    if (num > maxNum) maxNum = num;
  });

  const nextNum = maxNum + 1;
  const nextKey = `WEEK ${nextNum}`;
  const opt = document.createElement("option");
  opt.value = nextKey;
  opt.textContent = `Semana ${nextNum}`;
  weekSelect.appendChild(opt);
  weekSelect.value = nextKey;
  state.activeWeek = nextKey;

  showToast(`Semana ${nextNum} agregada.`);
  if (typeof onWeekChangedCallback === "function") {
    await onWeekChangedCallback();
  }
};

export const initWeekSelectorListeners = (onWeekChange) => {
  onWeekChangedCallback = onWeekChange;

  const weekSelect = document.getElementById("boardWeek");
  if (weekSelect) {
    weekSelect.addEventListener("change", async () => {
      state.activeWeek = weekSelect.value;
      if (typeof onWeekChangedCallback === "function") {
        await onWeekChangedCallback();
      }
    });
  }

  const btnAddWeek = document.getElementById("btnAddWeek");
  if (btnAddWeek) {
    btnAddWeek.addEventListener("click", addNewWeek);
  }
};
