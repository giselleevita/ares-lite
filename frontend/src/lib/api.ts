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
  stage?: string;
  progress?: number;
  message?: string;
  created_at: string;
  updated_at?: string;
  detector_backend?: string | null;
  stress_enabled?: boolean | null;
  readiness_score?: number | null;
};

export type RunDetail = {
  id: string;
  scenario_id: string;
  status: string;
  created_at: string;
  updated_at?: string | null;
  queued_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  stage?: string;
  progress?: number;
  message?: string;
  error_message?: string;
  cancel_requested?: boolean;
  cancelled_at?: string | null;
  config: Record<string, unknown>;
};

export type RunCreateResponse = {
  run_id: string;
  scenario_id: string;
  status: string;
  processed_at: string;
  frames_processed: number;
  detections_written: number;
  detector_backend: string;
  inference_seconds: number;
  fallback_reason?: string | null;
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

export type StressProfile = {
  id: string;
  name: string;
  description?: string;
};

export type StressProfilesResponse = {
  profiles: StressProfile[];
};

export type BenchmarkItem = {
  run_id: string;
  scenario_id: string;
  seed: number | null;
  stress_profile_id: string;
  role: string;
  status: string;
  stage: string;
  progress: number;
  message: string;
  error_message: string;
};

export type BenchmarkSuite = {
  id: string;
  name: string;
  status: string;
  progress: number;
  counts: Record<string, number>;
  created_at: string;
  updated_at: string;
  config: Record<string, unknown>;
  items: BenchmarkItem[];
};

export type CreateBenchmarkRequest = {
  name: string;
  scenario_ids: string[];
  stress_profile_ids: string[];
  seeds: number[];
  include_baselines?: boolean;
  base_options?: Record<string, unknown>;
};

export type CreateBenchmarkResponse = {
  suite_id: string;
  suite: BenchmarkSuite;
};

export type CompareRunsResponse = {
  run_a: { id: string; scenario_id: string; status: string; config: Record<string, unknown> };
  run_b: { id: string; scenario_id: string; status: string; config: Record<string, unknown> };
  metrics: Record<string, { a: unknown; b: unknown; delta: number | null }>;
  readiness: { a: Record<string, unknown>; b: Record<string, unknown>; delta: number | null };
};

const API_BASE = String(import.meta.env.VITE_API_BASE ?? "").trim();

function withBase(path: string): string {
  if (!API_BASE) return path;
  const base = API_BASE.endsWith("/") ? API_BASE.slice(0, -1) : API_BASE;
  const suffix = path.startsWith("/") ? path : `/${path}`;
  return `${base}${suffix}`;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(withBase(path));
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await fetch(withBase(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
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

export function getStressProfiles(): Promise<StressProfilesResponse> {
  return getJson<StressProfilesResponse>("/api/stress-profiles");
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

export function cancelRun(runId: string): Promise<RunDetail> {
  return postJson<RunDetail>(`/api/runs/${runId}/cancel`, {});
}

export function createRun(scenarioId: string, options?: Record<string, unknown>): Promise<RunCreateResponse> {
  return postJson<RunCreateResponse>("/api/run", {
    scenario_id: scenarioId,
    options: {
      resize: 640,
      every_n_frames: 2,
      max_frames: 120,
      ...(options ?? {}),
    },
  });
}

export function createBenchmark(payload: CreateBenchmarkRequest): Promise<CreateBenchmarkResponse> {
  return postJson<CreateBenchmarkResponse>("/api/benchmarks", payload);
}

export function getBenchmarkSuite(suiteId: string): Promise<BenchmarkSuite> {
  return getJson<BenchmarkSuite>(`/api/benchmarks/${suiteId}`);
}

export function compareRuns(runA: string, runB: string): Promise<CompareRunsResponse> {
  const params = new URLSearchParams({ run_a: runA, run_b: runB });
  return getJson<CompareRunsResponse>(`/api/compare/runs?${params.toString()}`);
}

export function withApiBase(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  return withBase(path);
}
