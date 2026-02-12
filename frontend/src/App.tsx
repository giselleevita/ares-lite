import { useEffect, useMemo, useState } from "react";

import {
  getHealth,
  getRun,
  getRunBlindspots,
  getRunEngagement,
  getRunMetrics,
  getRunReadiness,
  getRuns,
  getScenarios,
  type Blindspot,
  type RunSummary,
  withApiBase,
} from "./lib/api";

type Status = "online" | "degraded";

function toNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function App() {
  const [status, setStatus] = useState<Status>("degraded");
  const [serviceName, setServiceName] = useState("ares-lite-backend");
  const [scenarioCount, setScenarioCount] = useState(0);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedBlindspot, setSelectedBlindspot] = useState<Blindspot | null>(null);

  const [runDetail, setRunDetail] = useState<Record<string, unknown> | null>(null);
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null);
  const [engagement, setEngagement] = useState<Record<string, unknown> | null>(null);
  const [readiness, setReadiness] = useState<Record<string, unknown> | null>(null);
  const [blindspots, setBlindspots] = useState<Blindspot[]>([]);

  useEffect(() => {
    const load = async () => {
      try {
        const [health, scenarioPayload, runPayload] = await Promise.all([
          getHealth(),
          getScenarios(),
          getRuns(50),
        ]);
        setStatus(health.status === "ok" ? "online" : "degraded");
        setServiceName(health.service);
        setScenarioCount(scenarioPayload.scenarios.length);
        setRuns(runPayload.runs);
        if (runPayload.runs.length > 0) {
          setSelectedRunId(runPayload.runs[0].id);
        }
      } catch {
        setStatus("degraded");
      }
    };

    void load();
  }, []);

  useEffect(() => {
    if (!selectedRunId) {
      return;
    }

    const loadDetails = async () => {
      try {
        const [run, m, e, r, b] = await Promise.all([
          getRun(selectedRunId),
          getRunMetrics(selectedRunId),
          getRunEngagement(selectedRunId),
          getRunReadiness(selectedRunId),
          getRunBlindspots(selectedRunId),
        ]);

        setRunDetail(run as unknown as Record<string, unknown>);
        setMetrics(m.metrics);
        setEngagement(e.engagement);
        setReadiness(r.readiness);
        setBlindspots(b.blindspots);
        setSelectedBlindspot(b.blindspots[0] ?? null);
      } catch {
        setRunDetail(null);
        setMetrics(null);
        setEngagement(null);
        setReadiness(null);
        setBlindspots([]);
        setSelectedBlindspot(null);
      }
    };

    void loadDetails();
  }, [selectedRunId]);

  const readinessScore = toNumber(readiness?.readiness_score);
  const recommendation = String(readiness?.recommendation ?? "UNKNOWN");
  const precision = toNumber(metrics?.precision);
  const recall = toNumber(metrics?.recall);
  const delay = metrics?.detection_delay_seconds == null ? "n/a" : toNumber(metrics.detection_delay_seconds).toFixed(2);
  const stability = toNumber(metrics?.track_stability_index);
  const fpRate = toNumber(metrics?.false_positive_rate_per_minute);

  const engagementAttempts = toNumber(engagement?.engagement_attempts);
  const engagementSuccess = toNumber(engagement?.engagement_success_rate);
  const wasteRate = toNumber(engagement?.waste_rate);
  const collateralRisk = toNumber(engagement?.collateral_risk_events);

  const selectedFrameUrl = useMemo(
    () => (selectedBlindspot ? withApiBase(selectedBlindspot.frame_url) : null),
    [selectedBlindspot],
  );
  const selectedOverlayUrl = useMemo(
    () => (selectedBlindspot ? withApiBase(selectedBlindspot.overlay_url) : null),
    [selectedBlindspot],
  );

  return (
    <div className="min-h-screen bg-tactical-950 text-slate-100">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_18%_10%,rgba(60,104,152,0.25),transparent_44%),radial-gradient(circle_at_85%_15%,rgba(216,180,95,0.14),transparent_28%),radial-gradient(circle_at_50%_90%,rgba(162,70,70,0.14),transparent_36%)]" />
      <main className="relative mx-auto max-w-7xl px-4 py-6 md:px-8 md:py-8">
        <header className="mb-6 border-b border-tactical-700 pb-4">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-tactical-300">ARES LITE // OPERATIONAL READINESS CONSOLE</p>
          <h1 className="font-tactical text-3xl font-semibold uppercase md:text-4xl">Blind Spot Explorer</h1>
          <div className="mt-3 grid gap-2 text-sm text-slate-300 md:grid-cols-4">
            <span>Backend: {status === "online" ? "Online" : "Degraded"}</span>
            <span>Service: {serviceName}</span>
            <span>Scenarios: {scenarioCount}</span>
            <span>Runs: {runs.length}</span>
          </div>
        </header>

        <section className="grid gap-4 lg:grid-cols-[320px_1fr]">
          <aside className="rounded border border-tactical-700 bg-tactical-900/70 p-3">
            <h2 className="font-mono text-xs uppercase tracking-widest text-tactical-200">Run List</h2>
            <div className="mt-3 max-h-[640px] space-y-2 overflow-y-auto pr-1">
              {runs.length === 0 && <p className="text-sm text-slate-400">No runs found. Execute `/api/run` or `make demo`.</p>}
              {runs.map((run) => (
                <button
                  key={run.id}
                  type="button"
                  onClick={() => setSelectedRunId(run.id)}
                  className={`w-full rounded border p-3 text-left transition ${
                    run.id === selectedRunId
                      ? "border-accent-amber bg-tactical-800/90"
                      : "border-tactical-700 bg-tactical-800/50 hover:border-tactical-500"
                  }`}
                >
                  <p className="font-mono text-xs text-tactical-200">{run.id}</p>
                  <p className="mt-1 text-sm text-slate-100">{run.scenario_id}</p>
                  <p className="mt-1 text-xs text-slate-400">
                    score {run.readiness_score ?? "n/a"} • {run.status}
                  </p>
                </button>
              ))}
            </div>
          </aside>

          <div className="space-y-4">
            <section className="grid gap-4 md:grid-cols-3">
              <article className="rounded border border-tactical-700 bg-tactical-900/70 p-4 shadow-glow">
                <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Readiness</p>
                <p className="mt-2 font-tactical text-4xl text-slate-100">{readinessScore.toFixed(1)}</p>
                <p className="text-xs uppercase tracking-wider text-accent-amber">{recommendation}</p>
              </article>
              <article className="rounded border border-tactical-700 bg-tactical-900/70 p-4 shadow-glow">
                <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Reliability</p>
                <p className="mt-2 text-sm text-slate-200">Precision: {(precision * 100).toFixed(1)}%</p>
                <p className="text-sm text-slate-200">Recall: {(recall * 100).toFixed(1)}%</p>
                <p className="text-sm text-slate-200">Stability: {(stability * 100).toFixed(1)}%</p>
                <p className="text-sm text-slate-200">Delay: {delay}s</p>
                <p className="text-sm text-slate-200">FP/min: {fpRate.toFixed(2)}</p>
              </article>
              <article className="rounded border border-tactical-700 bg-tactical-900/70 p-4 shadow-glow">
                <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Engagement</p>
                <p className="mt-2 text-sm text-slate-200">Attempts: {engagementAttempts}</p>
                <p className="text-sm text-slate-200">Success: {(engagementSuccess * 100).toFixed(1)}%</p>
                <p className="text-sm text-slate-200">Waste: {(wasteRate * 100).toFixed(1)}%</p>
                <p className="text-sm text-slate-200">Collateral Risk: {collateralRisk.toFixed(2)}</p>
              </article>
            </section>

            <section className="rounded border border-tactical-700 bg-tactical-900/60 p-4">
              <h2 className="font-tactical text-xl uppercase">Blind Spots</h2>
              <p className="mt-1 text-sm text-slate-300">
                Run: {String(runDetail?.id ?? "n/a")} • Scenario: {String(runDetail?.scenario_id ?? "n/a")} • FNs: {blindspots.length}
              </p>

              <div className="mt-4 grid gap-4 xl:grid-cols-[240px_1fr]">
                <div className="max-h-[380px] space-y-2 overflow-y-auto pr-1">
                  {blindspots.length === 0 && <p className="text-sm text-slate-400">No blind spots recorded.</p>}
                  {blindspots.map((spot) => (
                    <button
                      key={spot.frame_idx}
                      type="button"
                      onClick={() => setSelectedBlindspot(spot)}
                      className={`w-full rounded border p-2 text-left text-sm ${
                        selectedBlindspot?.frame_idx === spot.frame_idx
                          ? "border-accent-red bg-tactical-800/85"
                          : "border-tactical-700 bg-tactical-800/45"
                      }`}
                    >
                      <p className="font-mono text-xs text-tactical-200">frame {spot.frame_idx}</p>
                      <p className="text-xs text-slate-300">{spot.reason_tags.join(", ")}</p>
                    </button>
                  ))}
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <div className="rounded border border-tactical-700 bg-black/30 p-2">
                    <p className="mb-2 font-mono text-xs uppercase tracking-wide text-slate-300">Stressed Frame</p>
                    {selectedFrameUrl ? (
                      <img src={selectedFrameUrl} alt="stressed frame" className="h-[300px] w-full rounded object-contain" />
                    ) : (
                      <div className="flex h-[300px] items-center justify-center text-sm text-slate-500">No frame selected</div>
                    )}
                  </div>
                  <div className="rounded border border-tactical-700 bg-black/30 p-2">
                    <p className="mb-2 font-mono text-xs uppercase tracking-wide text-slate-300">Overlay Evidence</p>
                    {selectedOverlayUrl ? (
                      <img src={selectedOverlayUrl} alt="overlay frame" className="h-[300px] w-full rounded object-contain" />
                    ) : (
                      <div className="flex h-[300px] items-center justify-center text-sm text-slate-500">No overlay selected</div>
                    )}
                  </div>
                </div>
              </div>
            </section>
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
