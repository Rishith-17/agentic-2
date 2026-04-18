let backendUrl = "http://127.0.0.1:8765";

async function resolveBackendUrl() {
  try {
    if (window.jarvis?.getBackendUrl) {
      const u = await window.jarvis.getBackendUrl();
      if (u) backendUrl = u;
    }
  } catch {
    // keep default
  }
  return backendUrl;
}

async function request(path, options = {}) {
  const base = await resolveBackendUrl();
  const res = await fetch(`${base}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    throw new Error(data?.detail || data?.error || `HTTP ${res.status}`);
  }
  return data;
}

export async function getSystemHealth() {
  return request("/api/system/health");
}

export async function getSystemLogs(lines = 160) {
  return request(`/api/system/logs?lines=${lines}`);
}

export async function getSystemMetrics() {
  return request("/api/system/metrics");
}

export async function getSkills() {
  return request("/api/skills");
}

export async function executeTask(task, sessionId = "dashboard") {
  return request("/api/agent/execute", {
    method: "POST",
    body: JSON.stringify({ task, session_id: sessionId }),
  });
}

export async function executeChat(message, sessionId = "dashboard") {
  return request("/api/chat", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId }),
  });
}

export async function executeSkill(skill, action, parameters = {}) {
  return request("/api/execute", {
    method: "POST",
    body: JSON.stringify({ skill, action, parameters }),
  });
}
