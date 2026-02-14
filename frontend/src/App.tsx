import { useEffect, useMemo, useState } from "react";

import {
  createRun,
  cancelRun,
  createBenchmark,
  getBenchmarkSuite,
  getHealth,
  getRun,
  getRunBlindspots,
  getRunEngagement,
  getRunMetrics,
  getRunReadiness,
  getRuns,
  getScenarios,
  getStressProfiles,
  compareRuns,
  type Scenario,
  type Blindspot,
  type RunSummary,
  type StressProfile,
  type BenchmarkSuite,
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
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>("");
  const [runCreateError, setRunCreateError] = useState<string | null>(null);
  const [creatingRun, setCreatingRun] = useState(false);

  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedBlindspot, setSelectedBlindspot] = useState<Blindspot | null>(null);

  const [runDetail, setRunDetail] = useState<Record<string, unknown> | null>(null);
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null);
  const [engagement, setEngagement] = useState<Record<string, unknown> | null>(null);
  const [readiness, setReadiness] = useState<Record<string, unknown> | null>(null);
  const [blindspots, setBlindspots] = useState<Blindspot[]>([]);

  const [stressProfiles, setStressProfiles] = useState<StressProfile[]>([]);
  const [benchmarkSuiteId, setBenchmarkSuiteId] = useState<string | null>(null);
  const [benchmarkSuite, setBenchmarkSuite] = useState<BenchmarkSuite | null>(null);
  const [benchmarkScenarioIds, setBenchmarkScenarioIds] = useState<string[]>([]);
  const [benchmarkProfileIds, setBenchmarkProfileIds] = useState<string[]>(["light_noise"]);
  const [benchmarkSeeds, setBenchmarkSeeds] = useState<string>("12345");

  const [compareA, setCompareA] = useState<string>("");
  const [compareB, setCompareB] = useState<string>("");
  const [compareResult, setCompareResult] = useState<Record<string, unknown> | null>(null);

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
        setScenarios(scenarioPayload.scenarios);
        setScenarioCount(scenarioPayload.scenarios.length);
        if (scenarioPayload.scenarios.length > 0) {
          setSelectedScenarioId((current) => current || scenarioPayload.scenarios[0].id);
        }
        setRuns(runPayload.runs);
        if (runPayload.runs.length > 0) {
          setSelectedRunId(runPayload.runs[0].id);
        }

        // Optional: stress profiles (benchmark mode). Failure should not break core flow.
        try {
          const profiles = await getStressProfiles();
          setStressProfiles(profiles.profiles ?? []);
        } catch {
          setStressProfiles([]);
        }

        setBenchmarkScenarioIds((cur) =>
          cur.length ? cur : (scenarioPayload.scenarios ?? []).slice(0, 2).map((s) => s.id),
        );
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

    let alive = true;
    let intervalId: number | null = null;

    const tick = async () => {
      if (!alive) return;
      try {
        const [run, runPayload] = await Promise.all([getRun(selectedRunId), getRuns(50)]);
        if (!alive) return;

        setRuns(runPayload.runs);
        setRunDetail(run as unknown as Record<string, unknown>);

        const status = String((run as unknown as { status?: unknown }).status ?? "");
        if (status === "completed") {
          const [m, e, r, b] = await Promise.all([
            getRunMetrics(selectedRunId),
            getRunEngagement(selectedRunId),
            getRunReadiness(selectedRunId),
            getRunBlindspots(selectedRunId),
          ]);
          if (!alive) return;
          setMetrics(m.metrics);
          setEngagement(e.engagement);
          setReadiness(r.readiness);
          setBlindspots(b.blindspots);
          setSelectedBlindspot((current) => current ?? (b.blindspots[0] ?? null));
          if (intervalId != null) {
            window.clearInterval(intervalId);
            intervalId = null;
          }
        } else if (status === "failed" || status === "cancelled") {
          setMetrics(null);
          setEngagement(null);
          setReadiness(null);
          setBlindspots([]);
          setSelectedBlindspot(null);
          if (intervalId != null) {
            window.clearInterval(intervalId);
            intervalId = null;
          }
        } else {
          setMetrics(null);
          setEngagement(null);
          setReadiness(null);
          setBlindspots([]);
          setSelectedBlindspot(null);
        }
      } catch {
        if (!alive) return;
        setRunDetail(null);
        setMetrics(null);
        setEngagement(null);
        setReadiness(null);
        setBlindspots([]);
        setSelectedBlindspot(null);
      }
    };

    void tick();
    intervalId = window.setInterval(() => void tick(), 2000);

    return () => {
      alive = false;
      if (intervalId != null) {
        window.clearInterval(intervalId);
      }
    };
  }, [selectedRunId]);

  useEffect(() => {
    if (!benchmarkSuiteId) return;
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      try {
        const suite = await getBenchmarkSuite(benchmarkSuiteId);
        if (!alive) return;
        setBenchmarkSuite(suite);
      } catch {
        // ignore
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 1500);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [benchmarkSuiteId]);

  const onCreateRun = async () => {
    if (!selectedScenarioId) return;
    setRunCreateError(null);
    setCreatingRun(true);
    try {
      const result = await createRun(selectedScenarioId);
      setSelectedRunId(result.run_id);
    } catch (err) {
      setRunCreateError(err instanceof Error ? err.message : "Failed to create run");
    } finally {
      setCreatingRun(false);
    }
  };

  const onRunDemo = async () => {
    setRunCreateError(null);
    setCreatingRun(true);
    try {
      const result = await createRun("demo", {
        resize: 320,
        every_n_frames: 1,
        max_frames: 60,
        seed: 12345,
        disable_stress: false,
      });
      setSelectedRunId(result.run_id);
    } catch (err) {
      setRunCreateError(err instanceof Error ? err.message : "Failed to run demo");
    } finally {
      setCreatingRun(false);
    }
  };

  const onCancelRun = async () => {
    if (!selectedRunId) return;
    try {
      await cancelRun(selectedRunId);
    } catch {
      // Ignore; polling will reflect state.
    }
  };

  const onStartBenchmark = async () => {
    setRunCreateError(null);
    setCreatingRun(true);
    try {
      const seeds = benchmarkSeeds
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map((s) => Number(s))
        .filter((n) => Number.isFinite(n) && n >= 0);

      const result = await createBenchmark({
        name: "Benchmark Suite",
        scenario_ids: benchmarkScenarioIds,
        stress_profile_ids: benchmarkProfileIds.length ? benchmarkProfileIds : ["light_noise"],
        seeds: seeds.length ? seeds : [12345],
        include_baselines: true,
        base_options: { resize: 320, every_n_frames: 1, max_frames: 60 },
      });
      setBenchmarkSuiteId(result.suite_id);
      setBenchmarkSuite(result.suite);
    } catch (err) {
      setRunCreateError(err instanceof Error ? err.message : "Failed to start benchmark suite");
    } finally {
      setCreatingRun(false);
    }
  };

  const onCompare = async () => {
    if (!compareA || !compareB) return;
    setRunCreateError(null);
    setCreatingRun(true);
    try {
      const result = await compareRuns(compareA, compareB);
      setCompareResult(result as unknown as Record<string, unknown>);
    } catch (err) {
      setRunCreateError(err instanceof Error ? err.message : "Failed to compare runs");
    } finally {
      setCreatingRun(false);
    }
  };

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

  const readinessBreakdown = (readiness?.readiness_breakdown ?? null) as
    | {
        weighting_mode?: unknown;
        components?: unknown;
        top_positive_contributors?: unknown;
        top_negative_contributors?: unknown;
      }
    | null;

  const breakdownComponents = Array.isArray(readinessBreakdown?.components)
    ? (readinessBreakdown?.components as Array<Record<string, unknown>>)
    : [];
  const topPos = Array.isArray(readinessBreakdown?.top_positive_contributors)
    ? (readinessBreakdown?.top_positive_contributors as Array<Record<string, unknown>>)
    : [];
  const topNeg = Array.isArray(readinessBreakdown?.top_negative_contributors)
    ? (readinessBreakdown?.top_negative_contributors as Array<Record<string, unknown>>)
    : [];

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

          <div className="mt-4 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div className="flex flex-col gap-2 md:flex-row md:items-center">
              <label className="font-mono text-xs uppercase tracking-widest text-tactical-200">Scenario</label>
              <select
                value={selectedScenarioId}
                onChange={(e) => setSelectedScenarioId(e.target.value)}
                className="rounded border border-tactical-700 bg-tactical-900/70 px-3 py-2 text-sm text-slate-100"
              >
                {scenarios.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.id}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void onCreateRun()}
                disabled={creatingRun || !selectedScenarioId}
                className="rounded border border-accent-amber bg-tactical-800/80 px-3 py-2 font-mono text-xs uppercase tracking-widest text-slate-100 disabled:opacity-50"
              >
                {creatingRun ? "Queuing..." : "Start Run"}
              </button>
              <button
                type="button"
                onClick={() => void onRunDemo()}
                disabled={creatingRun}
                className="rounded border border-tactical-500 bg-tactical-800/60 px-3 py-2 font-mono text-xs uppercase tracking-widest text-slate-100 disabled:opacity-50"
              >
                Run Demo
              </button>
            </div>
            {runCreateError && <p className="text-sm text-accent-red">{runCreateError}</p>}
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
                    score {run.readiness_score ?? "n/a"} • {run.stage ?? run.status} {run.progress != null ? `(${run.progress}%)` : ""}
                  </p>
                  {run.message && <p className="mt-1 text-xs text-slate-500">{run.message}</p>}
                </button>
              ))}
            </div>
          </aside>

          <div className="space-y-4">
            <section className="rounded border border-tactical-700 bg-tactical-900/60 p-4">
              <details>
                <summary className="cursor-pointer font-mono text-xs uppercase tracking-[0.2em] text-tactical-200">
                  Benchmark Mode (Batch Runs)
                </summary>
                <p className="mt-2 text-sm text-slate-300">
                  Run a suite: scenarios x stress profiles x seeds, using the existing DB-backed worker queue.
                </p>

                <div className="mt-4 grid gap-4 md:grid-cols-3">
                  <div>
                    <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Scenarios</p>
                    <div className="mt-2 max-h-[180px] space-y-2 overflow-auto pr-1 text-sm">
                      {scenarios.map((s) => {
                        const checked = benchmarkScenarioIds.includes(s.id);
                        return (
                          <label key={s.id} className="flex items-center gap-2">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() =>
                                setBenchmarkScenarioIds((cur) =>
                                  checked ? cur.filter((x) => x !== s.id) : [...cur, s.id],
                                )
                              }
                            />
                            <span>{s.id}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>

                  <div>
                    <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Stress Profiles</p>
                    <div className="mt-2 max-h-[180px] space-y-2 overflow-auto pr-1 text-sm">
                      {stressProfiles
                        .filter((p) => p.id !== "none")
                        .map((p) => {
                          const checked = benchmarkProfileIds.includes(p.id);
                          return (
                            <label key={p.id} className="flex items-center gap-2">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() =>
                                  setBenchmarkProfileIds((cur) =>
                                    checked ? cur.filter((x) => x !== p.id) : [...cur, p.id],
                                  )
                                }
                              />
                              <span>{p.id}</span>
                            </label>
                          );
                        })}
                    </div>
                  </div>

                  <div>
                    <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Seeds</p>
                    <input
                      value={benchmarkSeeds}
                      onChange={(e) => setBenchmarkSeeds(e.target.value)}
                      className="mt-2 w-full rounded border border-tactical-700 bg-tactical-950/40 px-3 py-2 text-sm"
                      placeholder="12345, 1337"
                    />
                    <button
                      type="button"
                      onClick={() => void onStartBenchmark()}
                      disabled={creatingRun}
                      className="mt-3 w-full rounded border border-accent-amber bg-tactical-800/80 px-3 py-2 font-mono text-xs uppercase tracking-widest text-slate-100 disabled:opacity-50"
                    >
                      {creatingRun ? "Queuing..." : "Start Benchmark"}
                    </button>
                  </div>
                </div>

                {benchmarkSuite ? (
                  <div className="mt-4 rounded border border-tactical-700 bg-tactical-950/40 p-3">
                    <p className="text-sm text-slate-200">
                      Suite: <span className="font-mono">{benchmarkSuite.id}</span> • Status:{" "}
                      <span className="text-accent-amber">{benchmarkSuite.status}</span> • Progress:{" "}
                      {benchmarkSuite.progress}%
                    </p>
                    <div className="mt-3 overflow-x-auto">
                      <table className="w-full min-w-[900px] border-collapse text-left text-sm">
                        <thead className="text-xs uppercase tracking-[0.2em] text-tactical-300">
                          <tr>
                            <th className="border-b border-tactical-700 py-2 pr-3">Scenario</th>
                            <th className="border-b border-tactical-700 py-2 pr-3">Seed</th>
                            <th className="border-b border-tactical-700 py-2 pr-3">Profile</th>
                            <th className="border-b border-tactical-700 py-2 pr-3">Role</th>
                            <th className="border-b border-tactical-700 py-2 pr-3">Status</th>
                            <th className="border-b border-tactical-700 py-2 pr-3">Stage</th>
                            <th className="border-b border-tactical-700 py-2">Run</th>
                          </tr>
                        </thead>
                        <tbody className="text-slate-200">
                          {benchmarkSuite.items.map((item) => (
                            <tr key={item.run_id} className="border-b border-tactical-900/60">
                              <td className="py-2 pr-3">{item.scenario_id}</td>
                              <td className="py-2 pr-3">{item.seed ?? "n/a"}</td>
                              <td className="py-2 pr-3">{item.stress_profile_id}</td>
                              <td className="py-2 pr-3">{item.role}</td>
                              <td className="py-2 pr-3">{item.status}</td>
                              <td className="py-2 pr-3">{item.stage}</td>
                              <td className="py-2">
                                <button
                                  type="button"
                                  onClick={() => setSelectedRunId(item.run_id)}
                                  className="rounded border border-tactical-700 bg-tactical-900/60 px-2 py-1 font-mono text-xs"
                                >
                                  {item.run_id}
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : (
                  <p className="mt-4 text-sm text-slate-400">No suite running.</p>
                )}
              </details>
            </section>

            <section className="rounded border border-tactical-700 bg-tactical-900/60 p-4">
              <details>
                <summary className="cursor-pointer font-mono text-xs uppercase tracking-[0.2em] text-tactical-200">
                  Run Comparison
                </summary>
                <p className="mt-2 text-sm text-slate-300">Compare two runs (metrics + readiness deltas).</p>
                <div className="mt-4 grid gap-3 md:grid-cols-3">
                  <input
                    value={compareA}
                    onChange={(e) => setCompareA(e.target.value)}
                    className="rounded border border-tactical-700 bg-tactical-950/40 px-3 py-2 text-sm"
                    placeholder="run_id A"
                  />
                  <input
                    value={compareB}
                    onChange={(e) => setCompareB(e.target.value)}
                    className="rounded border border-tactical-700 bg-tactical-950/40 px-3 py-2 text-sm"
                    placeholder="run_id B"
                  />
                  <button
                    type="button"
                    onClick={() => void onCompare()}
                    disabled={creatingRun}
                    className="rounded border border-accent-amber bg-tactical-800/80 px-3 py-2 font-mono text-xs uppercase tracking-widest text-slate-100 disabled:opacity-50"
                  >
                    Compare
                  </button>
                </div>
                {compareResult ? (
                  <pre className="mt-4 max-h-[420px] overflow-auto rounded border border-tactical-700 bg-black/30 p-3 text-xs text-slate-200">
                    {JSON.stringify(compareResult, null, 2)}
                  </pre>
                ) : (
                  <p className="mt-4 text-sm text-slate-400">No comparison loaded.</p>
                )}
              </details>
            </section>

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

            {readinessBreakdown ? (
              <section className="rounded border border-tactical-700 bg-tactical-900/60 p-4">
                <details>
                  <summary className="cursor-pointer font-mono text-xs uppercase tracking-[0.2em] text-tactical-200">
                    Readiness Breakdown
                  </summary>
                  <p className="mt-2 text-xs text-slate-400">
                    Weighting mode: {String(readinessBreakdown.weighting_mode ?? "n/a")}
                  </p>

                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <div>
                      <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Top Positive</p>
                      {topPos.length > 0 ? (
                        <ul className="mt-2 space-y-1 text-sm text-slate-200">
                          {topPos.map((item, idx) => (
                            <li key={idx}>
                              {String(item.name ?? "n/a")}: {toNumber(item.contribution).toFixed(2)}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-2 text-sm text-slate-400">n/a</p>
                      )}
                    </div>
                    <div>
                      <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Top Negative</p>
                      {topNeg.length > 0 ? (
                        <ul className="mt-2 space-y-1 text-sm text-slate-200">
                          {topNeg.map((item, idx) => (
                            <li key={idx}>
                              {String(item.name ?? "n/a")}: {toNumber(item.contribution).toFixed(2)}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-2 text-sm text-slate-400">n/a</p>
                      )}
                    </div>
                  </div>

                  <div className="mt-4 overflow-x-auto">
                    <table className="w-full min-w-[720px] border-collapse text-left text-sm">
                      <thead className="text-xs uppercase tracking-[0.2em] text-tactical-300">
                        <tr>
                          <th className="border-b border-tactical-700 py-2 pr-3">Component</th>
                          <th className="border-b border-tactical-700 py-2 pr-3">Raw</th>
                          <th className="border-b border-tactical-700 py-2 pr-3">Normalized</th>
                          <th className="border-b border-tactical-700 py-2 pr-3">Weight</th>
                          <th className="border-b border-tactical-700 py-2">Contribution</th>
                        </tr>
                      </thead>
                      <tbody className="text-slate-200">
                        {breakdownComponents.map((c, idx) => (
                          <tr key={idx} className="border-b border-tactical-900/60">
                            <td className="py-2 pr-3">{String(c.name ?? "n/a")}</td>
                            <td className="py-2 pr-3 text-slate-400">{String(c.raw_value ?? "")}</td>
                            <td className="py-2 pr-3">{toNumber(c.normalized_value).toFixed(2)}</td>
                            <td className="py-2 pr-3">{toNumber(c.weight).toFixed(4)}</td>
                            <td className="py-2">{toNumber(c.contribution).toFixed(2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </section>
            ) : null}

            <section className="rounded border border-tactical-700 bg-tactical-900/60 p-4">
              <h2 className="font-tactical text-xl uppercase">Blind Spots</h2>
              <p className="mt-1 text-sm text-slate-300">
                Run: {String(runDetail?.id ?? "n/a")} • Scenario: {String(runDetail?.scenario_id ?? "n/a")} • Status: {String(runDetail?.status ?? "n/a")} • Stage: {String(runDetail?.stage ?? "n/a")} • FNs: {blindspots.length}
              </p>
              {String(runDetail?.status ?? "") === "processing" && (
                <div className="mt-3">
                  <button
                    type="button"
                    onClick={() => void onCancelRun()}
                    className="rounded border border-accent-red bg-tactical-800/80 px-3 py-2 font-mono text-xs uppercase tracking-widest text-slate-100"
                  >
                    Cancel Run
                  </button>
                </div>
              )}

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
