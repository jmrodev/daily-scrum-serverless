/**
 * Date & Calendar Utilities
 */
export const getCurrentDayName = () => {
  const dayIndex = new Date().getDay();
  const map = {
    1: "Lunes",
    2: "Martes",
    3: "Miércoles",
    4: "Jueves",
    5: "Viernes",
    6: "Sábado",
    0: "Domingo",
  };
  return map[dayIndex] || "Lunes";
};

export const getCalendarWeekNumber = (d = new Date()) => {
  const target = new Date(d.valueOf());
  const dayNr = (d.getDay() + 6) % 7;
  target.setDate(target.getDate() - dayNr + 3);
  const firstThursday = target.valueOf();
  target.setMonth(0, 1);
  if (target.getDay() !== 4) {
    target.setMonth(0, 1 + ((4 - target.getDay()) + 7) % 7);
  }
  return 1 + Math.ceil((firstThursday - target) / 604800000);
};

export const getStatusLabel = (status) => {
  switch (status) {
    case "TODO": return "Por Hacer";
    case "DOING": return "En Progreso";
    case "BLOCKED": return "Bloqueado";
    case "DONE": return "Completado";
    default: return status;
  }
};
