export type HealthResponse = {
  status: string;
  service: string;
};

export type Scenario = {
  id: string;
  name: string;
  description: string;
};

export type ScenariosResponse = {
  scenarios: Scenario[];
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
