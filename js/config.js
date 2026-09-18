/**
 * Application Configuration & Constants
 */
export const DEFAULT_API_URL = "https://2pa3hfii3cirygdrjnyjsit7ve0ybqgy.lambda-url.us-east-1.on.aws/";

export const STORAGE_KEY = "daily_scrum_api_url";
export const AUTH_STORAGE_KEY = "daily_scrum_auth_session";
export const THEME_STORAGE_KEY = "daily_scrum_theme";

export const DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
export const KANBAN_STATUSES = ["TODO", "DOING", "BLOCKED", "DONE"];

export const getCleanUrl = () => {
  const saved = localStorage.getItem(STORAGE_KEY);
  const url = (saved && saved.trim()) ? saved.trim() : DEFAULT_API_URL;
  return url.replace(/\/+$/, "");
};
