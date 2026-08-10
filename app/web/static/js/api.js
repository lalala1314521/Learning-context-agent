const BASE = "/api/v1";

export async function api(path, options = {}) {
  const { method = "GET", body, form } = options;
  const fetchOptions = { method, headers: {} };
  if (form) {
    fetchOptions.body = form;
  } else if (body !== undefined) {
    fetchOptions.headers["Content-Type"] = "application/json";
    fetchOptions.body = JSON.stringify(body);
  }

  const response = await fetch(BASE + path, fetchOptions);
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }

  if (!response.ok || payload.ok === false) {
    const error = new Error(payload.error || payload.detail || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload.data;
}
