export type HealthResponse = {
  status: string;
  service: string;
};

export type Scenario = {
  id: string;
  name: string;
  description: string;
  video_id?: string;
  difficulty?: number;
  default_seed?: number;
  stressors?: string[];
};

export type ScenariosResponse = {
  scenarios: Scenario[];
};

export type RunSummary = {
  id: string;
  scenario_id: string;
  status: string;
  created_at: string;
  detector_backend?: string | null;
  stress_enabled?: boolean | null;
  readiness_score?: number | null;
};

export type RunDetail = {
  id: string;
  scenario_id: string;
  status: string;
  created_at: string;
  config: Record<string, unknown>;
};

export type MetricsResponse = {
  run_id: string;
  metrics: Record<string, unknown>;
};

export type EngagementResponse = {
  run_id: string;
  engagement: Record<string, unknown>;
};

export type ReadinessResponse = {
  run_id: string;
  readiness: Record<string, unknown>;
};

export type Blindspot = {
  frame_idx: number;
  reason_tags: string[];
  frame_url: string;
  overlay_url: string;
};

export type BlindspotsResponse = {
  run_id: string;
  blindspots: Blindspot[];
  count: number;
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>("/health");
}

export function getScenarios(): Promise<ScenariosResponse> {
  return getJson<ScenariosResponse>("/api/scenarios");
}

export function getRuns(limit = 25): Promise<{ runs: RunSummary[] }> {
  return getJson<{ runs: RunSummary[] }>(`/api/runs?limit=${limit}`);
}

export function getRun(runId: string): Promise<RunDetail> {
  return getJson<RunDetail>(`/api/runs/${runId}`);
}

export function getRunMetrics(runId: string): Promise<MetricsResponse> {
  return getJson<MetricsResponse>(`/api/runs/${runId}/metrics`);
}

export function getRunEngagement(runId: string): Promise<EngagementResponse> {
  return getJson<EngagementResponse>(`/api/runs/${runId}/engagement`);
}

export function getRunReadiness(runId: string): Promise<ReadinessResponse> {
  return getJson<ReadinessResponse>(`/api/runs/${runId}/readiness`);
}

export function getRunBlindspots(runId: string): Promise<BlindspotsResponse> {
  return getJson<BlindspotsResponse>(`/api/runs/${runId}/blindspots`);
}

export function withApiBase(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  return `${API_BASE}${path}`;
}
