// Fetch wrappers. All calls go through Vite's /api proxy → localhost:8000.
// See vite.config.ts.

import type {
  AnalyzeResponse,
  HealthResponse,
  OptimizeResponse,
  WorkloadResponse,
} from "./types";

const BASE = "/api";

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`${resp.status} ${resp.statusText}: ${text || "(no body)"}`);
  }
  return resp.json() as Promise<T>;
}

export function analyzeQuery(query: string, signal?: AbortSignal): Promise<AnalyzeResponse> {
  return postJson<AnalyzeResponse>("/analyze", { query }, signal);
}

export function optimizeQuery(query: string, signal?: AbortSignal): Promise<OptimizeResponse> {
  return postJson<OptimizeResponse>("/optimize", { query }, signal);
}

export async function health(): Promise<HealthResponse> {
  const resp = await fetch(`${BASE}/health`);
  return resp.json();
}

export function workload(n = 8, minCalls = 1, signal?: AbortSignal): Promise<WorkloadResponse> {
  return postJson<WorkloadResponse>("/workload", { n, min_calls: minCalls }, signal);
}
