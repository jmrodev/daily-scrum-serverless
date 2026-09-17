/**
 * Central Application State
 */
export const state = {
  currentUser: {
    email: null,
    name: null,
    role: null, // "admin" | "member" | null
    title: null,
    is_admin: false,
    token: null,
  },
  currentMainView: "daily", // "daily" | "kanban"
  currentLoadedTasks: [],
  activeProject: "",
  activeWeek: "",
};

export const setCurrentUser = (user) => {
  if (!user) {
    state.currentUser = {
      email: null,
      name: null,
      role: null,
      title: null,
      is_admin: false,
      token: null,
    };
  } else {
    state.currentUser = {
      email: user.email || "",
      name: user.name || user.email?.split("@")[0] || "Usuario",
      role: user.role || (user.is_admin ? "admin" : "member"),
      title: user.title || (user.role === "admin" ? "Admin / Tech Lead" : "Team Member"),
      is_admin: !!(user.is_admin || user.role === "admin"),
      token: user.token || null,
    };
  }
};

export const isAuthenticated = () => {
  return !!(state.currentUser && state.currentUser.email);
};

export const isAdmin = () => {
  return !!(state.currentUser && (state.currentUser.role === "admin" || state.currentUser.is_admin));
};
