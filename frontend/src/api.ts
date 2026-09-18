import type { AskResult, GalaxyData, Graph, GraphDetail } from "./types";

const API_ROOT = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    headers: init?.body instanceof URLSearchParams || init?.body instanceof FormData
      ? { ...(init?.headers || {}) }
      : { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `请求失败（${response.status}）`);
  }
  return payload.data as T;
}

export const api = {
  graphs: () => request<Graph[]>("/graphs"),
  graph: (id: string) => request<GraphDetail>(`/graphs/${encodeURIComponent(id)}`),
  galaxy: () => request<GalaxyData>("/galaxy"),
  ask: (question: string, useDatabase = true) =>
    request<AskResult>("/ask", { method: "POST", body: JSON.stringify({ question, use_database: useDatabase }) }),
  askAsync: (question: string, useDatabase = true) =>
    request<{ id: string }>("/ask/async", { method: "POST", body: JSON.stringify({ question, use_database: useDatabase }) }),
  parse: (text: string) => request<{ content: string; preview: Record<string, unknown>; source_name?: string }>("/graphs/parse", {
    method: "POST",
    headers: {},
    body: new URLSearchParams({ text }),
  }),
  parseSource: (source: { file?: File; url?: string; text?: string }) => {
    const form = new FormData();
    if (source.file) form.append("file", source.file);
    if (source.url) form.append("url", source.url);
    if (source.text) form.append("text", source.text);
    return request<{ content: string; preview: Record<string, unknown>; source_name?: string }>("/graphs/parse", {
      method: "POST", headers: {}, body: form,
    });
  },
  generate: (content: string, options: { webSearchEnabled?: boolean; learningGoal?: string; generationDepth?: string } = {}) =>
    request<{ id: string; title?: string; nodes: unknown[] }>("/graphs/generate", {
      method: "POST", body: JSON.stringify({ content, output_format: "both", web_search_enabled: options.webSearchEnabled ?? false, auto_link: true, learning_goal: options.learningGoal || "理解主线", generation_depth: options.generationDepth || "standard" }),
    }),
  generateAsync: (content: string, options: { webSearchEnabled?: boolean; learningGoal?: string; generationDepth?: string } = {}) =>
    request<{ id: string }>("/graphs/generate/async", {
      method: "POST", body: JSON.stringify({ content, output_format: "both", web_search_enabled: options.webSearchEnabled ?? false, auto_link: true, learning_goal: options.learningGoal || "理解主线", generation_depth: options.generationDepth || "standard" }),
    }),
  job: (id: string) => request<{ id: string; status: string; stage?: string; progress?: number; error?: string; trace?: Array<{ text?: string; type?: string }>; result?: { id?: string } }>(`/jobs/${encodeURIComponent(id)}`),
  cancelJob: (id: string) => request<{ id: string; status: string; stage?: string }>(`/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  retryJob: (id: string) => request<{ id: string }>(`/jobs/${encodeURIComponent(id)}/retry`, { method: "POST" }),
  reviewSession: (mode = "feynman") => request<{ id: string; mode: string; items: Array<Record<string, unknown>> }>("/review/session", {
    method: "POST", body: JSON.stringify({ mode, count: 6 }),
  }),
  answerReview: (sessionId: string, response: Record<string, unknown>) => request<{ feedback: string; answer?: unknown; next?: string }>(`/review/session/${sessionId}/answer`, {
    method: "POST", body: JSON.stringify({ response }),
  }),
};
