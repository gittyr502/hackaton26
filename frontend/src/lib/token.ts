/** The JWT from /api/auth/login. Storage can be blocked (private mode), so every access is guarded. */
const KEY = "auth_token";
let memory: string | null = null;

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(KEY) ?? memory;
  } catch {
    return memory;
  }
}

export function setToken(token: string | null) {
  memory = token;
  try {
    if (token) window.localStorage.setItem(KEY, token);
    else window.localStorage.removeItem(KEY);
  } catch {
    /* storage blocked: the token lives for this tab only */
  }
}

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Session expired or token rejected: forget it and go to the login screen. */
export function handleUnauthorized() {
  setToken(null);
  if (window.location.pathname !== "/login") {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.assign(`/login?next=${next}`);
  }
}
