import { useEffect, useMemo, useState } from "react";

import {
  createRun,
  cancelRun,
  createBenchmark,
  listBenchmarkBatches,
  getBenchmarkBatch,
  downloadBenchmarkCsv,
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
  type BenchmarkBatch,
  type BenchmarkBatchSummary,
  withApiBase,
} from "./lib/api";

type Status = "online" | "degraded";
type Page = "runs" | "benchmarks" | "compare";

function toNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function App() {
  const [page, setPage] = useState<Page>("runs");
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
  const [runSearch, setRunSearch] = useState<string>("");

  const [runDetail, setRunDetail] = useState<Record<string, unknown> | null>(null);
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null);
  const [engagement, setEngagement] = useState<Record<string, unknown> | null>(null);
  const [readiness, setReadiness] = useState<Record<string, unknown> | null>(null);
  const [blindspots, setBlindspots] = useState<Blindspot[]>([]);

  const [stressProfiles, setStressProfiles] = useState<StressProfile[]>([]);
  const [benchmarkBatches, setBenchmarkBatches] = useState<BenchmarkBatchSummary[]>([]);
  const [benchmarkSuiteId, setBenchmarkSuiteId] = useState<string | null>(null);
  const [benchmarkSuite, setBenchmarkSuite] = useState<BenchmarkBatch | null>(null);
  const [benchmarkScenarioIds, setBenchmarkScenarioIds] = useState<string[]>([]);
  const [benchmarkProfileIds, setBenchmarkProfileIds] = useState<string[]>(["baseline", "fog"]);
  const [benchmarkSeeds, setBenchmarkSeeds] = useState<string>("12345");
  const [benchmarkFilterScenario, setBenchmarkFilterScenario] = useState<string>("all");
  const [benchmarkFilterProfile, setBenchmarkFilterProfile] = useState<string>("all");
  const [benchmarkFilterStatus, setBenchmarkFilterStatus] = useState<string>("all");
  const [benchmarkFilterRole, setBenchmarkFilterRole] = useState<string>("all");
  const [benchmarkFilterSeed, setBenchmarkFilterSeed] = useState<string>("");

  const [compareSelectedIds, setCompareSelectedIds] = useState<string[]>([]);
  const [compareManualId, setCompareManualId] = useState<string>("");
  const [compareResult, setCompareResult] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [health, scenarioPayload, runPayload] = await Promise.all([
          getHealth(),
          getScenarios(),
          getRuns(100),
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
        const [run, runPayload] = await Promise.all([getRun(selectedRunId), getRuns(100)]);
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
    let intervalId: number | null = null;
    const tick = async () => {
      if (!alive) return;
      try {
        const suite = await getBenchmarkBatch(benchmarkSuiteId);
        if (!alive) return;
        setBenchmarkSuite(suite);

        const s = String((suite as any)?.status ?? "");
        if (intervalId != null && (s === "completed" || s === "failed")) {
          window.clearInterval(intervalId);
          intervalId = null;
        }
      } catch {
        // ignore
      }
    };
    void tick();
    intervalId = window.setInterval(() => void tick(), 1500);
    return () => {
      alive = false;
      if (intervalId != null) {
        window.clearInterval(intervalId);
      }
    };
  }, [benchmarkSuiteId]);

  useEffect(() => {
    if (page !== "benchmarks") return;
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      try {
        const payload = await listBenchmarkBatches(50);
        if (!alive) return;
        setBenchmarkBatches(payload.batches ?? []);
      } catch {
        // ignore
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), 2000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [page]);

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
        scenarios: benchmarkScenarioIds,
        stress_profiles: benchmarkProfileIds.length ? benchmarkProfileIds : ["fog"],
        seeds: seeds.length ? seeds : [12345],
        run_options_overrides: { resize: 320, every_n_frames: 1, max_frames: 60 },
      });
      setBenchmarkSuiteId(result.batch_id);
      setBenchmarkSuite(null);
      setPage("benchmarks");
    } catch (err) {
      setRunCreateError(err instanceof Error ? err.message : "Failed to start benchmark suite");
    } finally {
      setCreatingRun(false);
    }
  };

  const onCompare = async () => {
    const manual = compareManualId.trim();
    const ids = Array.from(new Set([...(compareSelectedIds ?? []), ...(manual ? [manual] : [])])).filter(Boolean);
    if (ids.length < 2) return;
    setRunCreateError(null);
    setCreatingRun(true);
    try {
      const result = await compareRuns(ids);
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

  const runsById = useMemo(() => {
    const map: Record<string, RunSummary> = {};
    for (const r of runs) {
      map[r.id] = r;
    }
    return map;
  }, [runs]);

  const filteredRuns = useMemo(() => {
    const q = runSearch.trim().toLowerCase();
    if (!q) return runs;
    return runs.filter((r) => {
      const id = String(r.id ?? "").toLowerCase();
      const scenario = String(r.scenario_id ?? "").toLowerCase();
      const stage = String(r.stage ?? r.status ?? "").toLowerCase();
      const msg = String(r.message ?? "").toLowerCase();
      return id.includes(q) || scenario.includes(q) || stage.includes(q) || msg.includes(q);
    });
  }, [runs, runSearch]);

  const filteredBenchmarkItems = useMemo(() => {
    const suite = benchmarkSuite;
    if (!suite) return [];
    const seedQuery = benchmarkFilterSeed.trim();
    return suite.items.filter((item) => {
      if (benchmarkFilterScenario !== "all" && item.scenario_id !== benchmarkFilterScenario) return false;
      const profileId = String((item as any).stress_profile?.id ?? "");
      if (benchmarkFilterProfile !== "all" && profileId !== benchmarkFilterProfile) return false;
      if (benchmarkFilterStatus !== "all" && item.status !== benchmarkFilterStatus) return false;
      if (benchmarkFilterRole !== "all" && item.role !== benchmarkFilterRole) return false;
      if (seedQuery) {
        const want = Number(seedQuery);
        if (!Number.isFinite(want) || (item.seed ?? null) !== want) return false;
      }
      return true;
    });
  }, [
    benchmarkSuite,
    benchmarkFilterScenario,
    benchmarkFilterProfile,
    benchmarkFilterStatus,
    benchmarkFilterRole,
    benchmarkFilterSeed,
  ]);

  const onDownloadCsv = async () => {
    if (!benchmarkSuiteId) return;
    setRunCreateError(null);
    try {
      const blob = await downloadBenchmarkCsv(benchmarkSuiteId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${benchmarkSuiteId}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setRunCreateError(err instanceof Error ? err.message : "Failed to download CSV");
    }
  };

  const compareBreakdown = useMemo(() => {
    const result = compareResult as any;
    const runsArr = Array.isArray(result?.runs) ? (result.runs as any[]) : [];
    const byId: Record<string, any> = {};
    for (const r of runsArr) {
      const id = String(r?.id ?? "");
      if (!id) continue;
      byId[id] = r;
    }

    const selected = (compareSelectedIds ?? []).filter((id) => !!byId[id]);
    const componentNames = new Set<string>();
    const componentsByRun: Record<string, Record<string, any>> = {};
    const weightingModeByRun: Record<string, string> = {};

    for (const id of selected) {
      const rb = byId[id]?.readiness?.readiness_breakdown ?? null;
      const mode = String(rb?.weighting_mode ?? "n/a");
      weightingModeByRun[id] = mode;

      const comps = Array.isArray(rb?.components) ? (rb.components as any[]) : [];
      const map: Record<string, any> = {};
      for (const c of comps) {
        const name = String(c?.name ?? "");
        if (!name) continue;
        componentNames.add(name);
        map[name] = c;
      }
      componentsByRun[id] = map;
    }

    const names = Array.from(componentNames).sort((a, b) => a.localeCompare(b));
    return { selected, names, componentsByRun, weightingModeByRun };
  }, [compareResult, compareSelectedIds]);

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

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setPage("runs")}
              className={`rounded border px-3 py-2 font-mono text-xs uppercase tracking-widest ${
                page === "runs"
                  ? "border-accent-amber bg-tactical-800/90 text-slate-100"
                  : "border-tactical-700 bg-tactical-800/50 text-tactical-200 hover:border-tactical-500"
              }`}
            >
              Runs
            </button>
            <button
              type="button"
              onClick={() => setPage("benchmarks")}
              className={`rounded border px-3 py-2 font-mono text-xs uppercase tracking-widest ${
                page === "benchmarks"
                  ? "border-accent-amber bg-tactical-800/90 text-slate-100"
                  : "border-tactical-700 bg-tactical-800/50 text-tactical-200 hover:border-tactical-500"
              }`}
            >
              Benchmarks
            </button>
            <button
              type="button"
              onClick={() => setPage("compare")}
              className={`rounded border px-3 py-2 font-mono text-xs uppercase tracking-widest ${
                page === "compare"
                  ? "border-accent-amber bg-tactical-800/90 text-slate-100"
                  : "border-tactical-700 bg-tactical-800/50 text-tactical-200 hover:border-tactical-500"
              }`}
            >
              Compare
            </button>
          </div>

          {page === "runs" ? (
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
          ) : runCreateError ? (
            <p className="mt-3 text-sm text-accent-red">{runCreateError}</p>
          ) : null}
        </header>

        {page === "runs" ? (
          <section className="grid gap-4 lg:grid-cols-[320px_1fr]">
          <aside className="rounded border border-tactical-700 bg-tactical-900/70 p-3">
            <h2 className="font-mono text-xs uppercase tracking-widest text-tactical-200">Run List</h2>
            <input
              value={runSearch}
              onChange={(e) => setRunSearch(e.target.value)}
              className="mt-3 w-full rounded border border-tactical-700 bg-tactical-950/40 px-3 py-2 text-sm"
              placeholder="Search runs (id/scenario/status)..."
            />
            <p className="mt-2 text-xs text-slate-400">Showing {filteredRuns.length} / {runs.length}.</p>
            <div className="mt-3 max-h-[600px] space-y-2 overflow-y-auto pr-1">
              {runs.length === 0 && <p className="text-sm text-slate-400">No runs found. Execute `/api/run` or `make demo`.</p>}
              {filteredRuns.map((run) => (
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
        ) : page === "benchmarks" ? (
          <section className="grid gap-4 lg:grid-cols-[360px_1fr]">
            <aside className="rounded border border-tactical-700 bg-tactical-900/70 p-3">
              <h2 className="font-mono text-xs uppercase tracking-widest text-tactical-200">Batches</h2>
              <p className="mt-2 text-sm text-slate-400">Create and monitor benchmark batches (suite runs).</p>

              <div className="mt-4 space-y-3">
                <div className="rounded border border-tactical-700 bg-tactical-950/40 p-3">
                  <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Create Batch</p>

                  <div className="mt-3 space-y-3">
                    <div>
                      <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Scenarios</p>
                      <div className="mt-2 max-h-[160px] space-y-2 overflow-auto pr-1 text-sm">
                        {scenarios.map((s) => {
                          const checked = benchmarkScenarioIds.includes(s.id);
                          return (
                            <label key={s.id} className="flex items-center gap-2">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() =>
                                  setBenchmarkScenarioIds((cur) => (checked ? cur.filter((x) => x !== s.id) : [...cur, s.id]))
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
                      <div className="mt-2 max-h-[160px] space-y-2 overflow-auto pr-1 text-sm">
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
                                    setBenchmarkProfileIds((cur) => (checked ? cur.filter((x) => x !== p.id) : [...cur, p.id]))
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
                </div>

                <div className="rounded border border-tactical-700 bg-tactical-950/40 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Recent Batches</p>
                    <button
                      type="button"
                      onClick={() =>
                        void (async () => {
                          try {
                            const payload = await listBenchmarkBatches(50);
                            setBenchmarkBatches(payload.batches ?? []);
                          } catch {
                            // ignore
                          }
                        })()
                      }
                      className="rounded border border-tactical-700 bg-tactical-900/60 px-2 py-1 font-mono text-[11px] uppercase tracking-widest text-tactical-200 hover:border-tactical-500"
                    >
                      Refresh
                    </button>
                  </div>

                  <div className="mt-3 max-h-[340px] space-y-2 overflow-y-auto pr-1 text-sm">
                    {benchmarkBatches.length === 0 ? <p className="text-slate-400">No batches yet.</p> : null}
                    {benchmarkBatches.map((b) => {
                      const active = b.id === benchmarkSuiteId;
                      return (
                        <button
                          key={b.id}
                          type="button"
                          onClick={() => {
                            setBenchmarkSuiteId(b.id);
                            setBenchmarkSuite(null);
                          }}
                          className={`w-full rounded border p-2 text-left ${
                            active ? "border-accent-amber bg-tactical-800/90" : "border-tactical-700 bg-tactical-900/60 hover:border-tactical-500"
                          }`}
                        >
                          <p className="font-mono text-xs text-tactical-200">{b.id}</p>
                          <p className="mt-1 text-xs text-slate-400">
                            {b.status} • {new Date(b.created_at).toLocaleString()}
                          </p>
                          {b.message ? <p className="mt-1 text-xs text-slate-500">{b.message}</p> : null}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            </aside>

            <div className="space-y-4">
              {benchmarkSuite ? (
                <section className="rounded border border-tactical-700 bg-tactical-900/60 p-4">
                  <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="text-sm text-slate-200">
                        Batch: <span className="font-mono">{benchmarkSuite.id}</span> • Status:{" "}
                        <span className="text-accent-amber">{benchmarkSuite.status}</span>
                      </p>
                      {benchmarkSuite.message ? <p className="mt-1 text-xs text-slate-400">{String(benchmarkSuite.message ?? "")}</p> : null}
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void onDownloadCsv()}
                        className="rounded border border-tactical-700 bg-tactical-900/60 px-3 py-2 font-mono text-xs uppercase tracking-widest text-tactical-100 hover:border-tactical-500"
                      >
                        Download CSV
                      </button>
                      <button
                        type="button"
                        onClick={() => void setBenchmarkSuiteId(benchmarkSuite.id)}
                        className="rounded border border-tactical-700 bg-tactical-900/60 px-3 py-2 font-mono text-xs uppercase tracking-widest text-tactical-200 hover:border-tactical-500"
                      >
                        Refresh
                      </button>
                    </div>
                  </div>

                  <div className="mt-4 grid gap-3 md:grid-cols-5">
                    <div>
                      <p className="font-mono text-[11px] uppercase tracking-widest text-tactical-300">Scenario</p>
                      <select
                        value={benchmarkFilterScenario}
                        onChange={(e) => setBenchmarkFilterScenario(e.target.value)}
                        className="mt-1 w-full rounded border border-tactical-700 bg-tactical-950/40 px-2 py-2 text-sm"
                      >
                        <option value="all">all</option>
                        {Array.from(new Set(benchmarkSuite.items.map((i) => i.scenario_id))).map((id) => (
                          <option key={id} value={id}>
                            {id}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <p className="font-mono text-[11px] uppercase tracking-widest text-tactical-300">Profile</p>
                      <select
                        value={benchmarkFilterProfile}
                        onChange={(e) => setBenchmarkFilterProfile(e.target.value)}
                        className="mt-1 w-full rounded border border-tactical-700 bg-tactical-950/40 px-2 py-2 text-sm"
                      >
                        <option value="all">all</option>
                        {Array.from(
                          new Set(benchmarkSuite.items.map((i) => String((i as any).stress_profile?.id ?? ""))),
                        )
                          .filter(Boolean)
                          .map((id) => (
                            <option key={id} value={id}>
                              {id}
                            </option>
                          ))}
                      </select>
                    </div>
                    <div>
                      <p className="font-mono text-[11px] uppercase tracking-widest text-tactical-300">Status</p>
                      <select
                        value={benchmarkFilterStatus}
                        onChange={(e) => setBenchmarkFilterStatus(e.target.value)}
                        className="mt-1 w-full rounded border border-tactical-700 bg-tactical-950/40 px-2 py-2 text-sm"
                      >
                        <option value="all">all</option>
                        {Array.from(new Set(benchmarkSuite.items.map((i) => i.status))).map((id) => (
                          <option key={id} value={id}>
                            {id}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <p className="font-mono text-[11px] uppercase tracking-widest text-tactical-300">Role</p>
                      <select
                        value={benchmarkFilterRole}
                        onChange={(e) => setBenchmarkFilterRole(e.target.value)}
                        className="mt-1 w-full rounded border border-tactical-700 bg-tactical-950/40 px-2 py-2 text-sm"
                      >
                        <option value="all">all</option>
                        {Array.from(new Set(benchmarkSuite.items.map((i) => i.role))).map((id) => (
                          <option key={id} value={id}>
                            {id}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <p className="font-mono text-[11px] uppercase tracking-widest text-tactical-300">Seed</p>
                      <input
                        value={benchmarkFilterSeed}
                        onChange={(e) => setBenchmarkFilterSeed(e.target.value)}
                        className="mt-1 w-full rounded border border-tactical-700 bg-tactical-950/40 px-2 py-2 text-sm"
                        placeholder="e.g. 12345"
                      />
                    </div>
                  </div>

                  <p className="mt-3 text-xs text-slate-400">Showing {filteredBenchmarkItems.length} / {benchmarkSuite.items.length} items.</p>

                  <div className="mt-3 overflow-x-auto">
                    <table className="w-full min-w-[980px] border-collapse text-left text-sm">
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
                        {filteredBenchmarkItems.map((item) => {
                          const rid = String(item.run_id ?? "");
                          const stage = rid ? String(runsById[rid]?.stage ?? runsById[rid]?.status ?? "n/a") : "n/a";
                          return (
                            <tr key={String(item.run_id ?? item.id)} className="border-b border-tactical-900/60">
                              <td className="py-2 pr-3">{item.scenario_id}</td>
                              <td className="py-2 pr-3">{item.seed ?? "n/a"}</td>
                              <td className="py-2 pr-3">{String((item as any).stress_profile?.id ?? "n/a")}</td>
                              <td className="py-2 pr-3">{item.role}</td>
                              <td className="py-2 pr-3">{item.status}</td>
                              <td className="py-2 pr-3">{stage}</td>
                              <td className="py-2">
                                {item.run_id ? (
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setSelectedRunId(String(item.run_id));
                                      setPage("runs");
                                    }}
                                    className="rounded border border-tactical-700 bg-tactical-900/60 px-2 py-1 font-mono text-xs"
                                  >
                                    {item.run_id}
                                  </button>
                                ) : (
                                  <span className="text-slate-500">pending</span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  {benchmarkSuite.status === "completed" && benchmarkSuite.summary ? (
                    <div className="mt-4 grid gap-4 md:grid-cols-2">
                      <div className="rounded border border-tactical-700 bg-black/30 p-3">
                        <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Overall</p>
                        <div className="mt-2 text-sm text-slate-200">
                          <p>Mean: {String((benchmarkSuite.summary as any)?.overall?.mean_readiness ?? "n/a")}</p>
                          <p>Median: {String((benchmarkSuite.summary as any)?.overall?.median_readiness ?? "n/a")}</p>
                          <p>Worst: {String((benchmarkSuite.summary as any)?.overall?.worst_readiness ?? "n/a")}</p>
                          <p>Pass (&ge; 75): {String((benchmarkSuite.summary as any)?.overall?.pass_rate_ready ?? "n/a")}</p>
                        </div>
                      </div>
                      <div className="rounded border border-tactical-700 bg-black/30 p-3">
                        <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Top Blindspot Reasons</p>
                        <div className="mt-2 space-y-1 text-sm text-slate-200">
                          {Array.isArray((benchmarkSuite.summary as any)?.top_blindspot_reasons) &&
                          ((benchmarkSuite.summary as any)?.top_blindspot_reasons as any[]).length > 0 ? (
                            ((benchmarkSuite.summary as any)?.top_blindspot_reasons as any[]).slice(0, 6).map((r, idx) => (
                              <p key={idx}>
                                {String(r.reason ?? "n/a")}: {String(r.count ?? "0")}
                              </p>
                            ))
                          ) : (
                            <p className="text-slate-400">n/a</p>
                          )}
                        </div>
                      </div>

                      <div className="rounded border border-tactical-700 bg-black/30 p-3 md:col-span-2">
                        <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">By Stress Profile</p>
                        <div className="mt-3 overflow-x-auto">
                          <table className="w-full min-w-[700px] border-collapse text-left text-sm">
                            <thead className="text-xs uppercase tracking-[0.2em] text-tactical-300">
                              <tr>
                                <th className="border-b border-tactical-700 py-2 pr-3">Profile</th>
                                <th className="border-b border-tactical-700 py-2 pr-3">Count</th>
                                <th className="border-b border-tactical-700 py-2 pr-3">Mean</th>
                                <th className="border-b border-tactical-700 py-2 pr-3">Worst</th>
                                <th className="border-b border-tactical-700 py-2">Chart</th>
                              </tr>
                            </thead>
                            <tbody className="text-slate-200">
                              {Object.entries(((benchmarkSuite.summary as any)?.by_stress_profile ?? {}) as Record<string, any>).map(
                                ([profileId, row]) => {
                                  const m = toNumber(row?.mean, 0);
                                  return (
                                    <tr key={profileId} className="border-b border-tactical-900/60">
                                      <td className="py-2 pr-3">{profileId}</td>
                                      <td className="py-2 pr-3">{String(row?.count ?? "0")}</td>
                                      <td className="py-2 pr-3">{String(row?.mean ?? "n/a")}</td>
                                      <td className="py-2 pr-3">{String(row?.worst ?? "n/a")}</td>
                                      <td className="py-2">
                                        <div className="h-2 w-full rounded bg-tactical-800/60">
                                          <div
                                            className="h-2 rounded bg-accent-amber"
                                            style={{ width: `${Math.max(0, Math.min(100, m))}%` }}
                                          />
                                        </div>
                                      </td>
                                    </tr>
                                  );
                                },
                              )}
                            </tbody>
                          </table>
                        </div>
                      </div>

                      <details className="rounded border border-tactical-700 bg-black/30 p-3 md:col-span-2">
                        <summary className="cursor-pointer font-mono text-xs uppercase tracking-[0.2em] text-tactical-200">
                          Raw Summary JSON
                        </summary>
                        <pre className="mt-3 max-h-[280px] overflow-auto text-xs text-slate-200">
                          {JSON.stringify(benchmarkSuite.summary, null, 2)}
                        </pre>
                      </details>
                    </div>
                  ) : null}
                </section>
              ) : (
                <section className="rounded border border-tactical-700 bg-tactical-900/60 p-4">
                  <p className="text-sm text-slate-300">Select a batch from the left, or create one.</p>
                </section>
              )}
            </div>
          </section>
        ) : (
          <section className="grid gap-4 lg:grid-cols-[360px_1fr]">
            <aside className="rounded border border-tactical-700 bg-tactical-900/70 p-3">
              <h2 className="font-mono text-xs uppercase tracking-widest text-tactical-200">Select Runs</h2>
              <p className="mt-2 text-sm text-slate-400">Choose 2+ completed runs to compare.</p>

              <div className="mt-3 flex items-center gap-2">
                <input
                  value={compareManualId}
                  onChange={(e) => setCompareManualId(e.target.value)}
                  className="w-full rounded border border-tactical-700 bg-tactical-950/40 px-3 py-2 text-sm"
                  placeholder="Add run id (optional)"
                  list="run-ids"
                />
                <button
                  type="button"
                  onClick={() => {
                    const id = compareManualId.trim();
                    if (!id) return;
                    setCompareSelectedIds((cur) => (cur.includes(id) ? cur : [...cur, id]));
                    setCompareManualId("");
                  }}
                  className="rounded border border-tactical-700 bg-tactical-900/60 px-2 py-2 font-mono text-xs uppercase tracking-widest text-tactical-200 hover:border-tactical-500"
                >
                  Add
                </button>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void onCompare()}
                  disabled={creatingRun || compareSelectedIds.length < 2}
                  className="rounded border border-accent-amber bg-tactical-800/80 px-3 py-2 font-mono text-xs uppercase tracking-widest text-slate-100 disabled:opacity-50"
                >
                  {creatingRun ? "Working..." : "Compare Selected"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCompareSelectedIds([]);
                    setCompareResult(null);
                  }}
                  className="rounded border border-tactical-700 bg-tactical-900/60 px-3 py-2 font-mono text-xs uppercase tracking-widest text-tactical-200 hover:border-tactical-500"
                >
                  Clear
                </button>
              </div>

              <p className="mt-3 text-xs text-slate-400">Selected: {compareSelectedIds.length}</p>

              <datalist id="run-ids">
                {runs.map((r) => (
                  <option key={r.id} value={r.id} />
                ))}
              </datalist>

              <div className="mt-3 max-h-[560px] space-y-2 overflow-y-auto pr-1 text-sm">
                {runs.map((r) => {
                  const checked = compareSelectedIds.includes(r.id);
                  return (
                    <label
                      key={r.id}
                      className={`flex cursor-pointer items-start gap-2 rounded border p-2 ${
                        checked ? "border-accent-amber bg-tactical-800/90" : "border-tactical-700 bg-tactical-900/60 hover:border-tactical-500"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() =>
                          setCompareSelectedIds((cur) => (checked ? cur.filter((x) => x !== r.id) : [...cur, r.id]))
                        }
                        className="mt-1"
                      />
                      <div className="min-w-0">
                        <p className="font-mono text-xs text-tactical-200">{r.id}</p>
                        <p className="mt-1 text-xs text-slate-400">
                          {r.scenario_id} • {r.stage ?? r.status} {r.progress != null ? `(${r.progress}%)` : ""} • score{" "}
                          {r.readiness_score ?? "n/a"}
                        </p>
                      </div>
                    </label>
                  );
                })}
              </div>
            </aside>

            <div className="space-y-4">
              <section className="rounded border border-tactical-700 bg-tactical-900/60 p-4">
                <h3 className="font-mono text-xs uppercase tracking-[0.2em] text-tactical-200">Comparison</h3>
                {compareResult ? (
                  <div className="mt-4 space-y-3">
                    <div className="overflow-x-auto rounded border border-tactical-700 bg-black/30 p-3">
                      <table className="w-full min-w-[860px] border-collapse text-left text-sm">
                        <thead className="text-xs uppercase tracking-[0.2em] text-tactical-300">
                          <tr>
                            <th className="border-b border-tactical-700 py-2 pr-3">Field</th>
                            {compareSelectedIds.map((id) => (
                              <th key={id} className="border-b border-tactical-700 py-2 pr-3">
                                {id}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="text-slate-200">
                          {Array.isArray((compareResult as any)?.aligned)
                            ? ((compareResult as any).aligned as any[]).map((row, idx) => (
                                <tr key={idx} className="border-b border-tactical-900/60">
                                  <td className="py-2 pr-3">{String(row.label ?? row.field ?? "n/a")}</td>
                                  {compareSelectedIds.map((id) => (
                                    <td key={id} className="py-2 pr-3">
                                      {String(row.values?.[id] ?? "n/a")}
                                    </td>
                                  ))}
                                </tr>
                              ))
                            : null}
                        </tbody>
                      </table>
                    </div>

                    <section className="rounded border border-tactical-700 bg-black/30 p-3">
                      <h4 className="font-mono text-xs uppercase tracking-[0.2em] text-tactical-200">Readiness Breakdown</h4>
                      <div className="mt-2 grid gap-2 md:grid-cols-2">
                        {compareBreakdown.selected.map((id) => (
                          <div key={id} className="rounded border border-tactical-800 bg-black/20 p-2">
                            <p className="font-mono text-[11px] uppercase tracking-widest text-tactical-300">{id}</p>
                            <p className="mt-1 text-xs text-slate-400">
                              weighting_mode: {String(compareBreakdown.weightingModeByRun[id] ?? "n/a")}
                            </p>
                          </div>
                        ))}
                      </div>

                      <div className="mt-3 overflow-x-auto">
                        <table className="w-full min-w-[900px] border-collapse text-left text-sm">
                          <thead className="text-xs uppercase tracking-[0.2em] text-tactical-300">
                            <tr>
                              <th className="border-b border-tactical-700 py-2 pr-3">Component</th>
                              {compareBreakdown.selected.map((id) => (
                                <th key={id} className="border-b border-tactical-700 py-2 pr-3">
                                  {id}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody className="text-slate-200">
                            {compareBreakdown.names.map((name) => (
                              <tr key={name} className="border-b border-tactical-900/60">
                                <td className="py-2 pr-3">{name}</td>
                                {compareBreakdown.selected.map((id) => {
                                  const c = compareBreakdown.componentsByRun[id]?.[name] ?? null;
                                  const contribution = toNumber(c?.contribution, Number.NaN);
                                  const weight = toNumber(c?.weight, Number.NaN);
                                  const normalized = toNumber(c?.normalized_value, Number.NaN);
                                  const text =
                                    Number.isFinite(contribution) && Number.isFinite(weight) && Number.isFinite(normalized)
                                      ? `${contribution.toFixed(3)} (n=${normalized.toFixed(2)}, w=${weight.toFixed(3)})`
                                      : "n/a";
                                  const cls =
                                    Number.isFinite(contribution) && contribution < 0
                                      ? "text-accent-red"
                                      : Number.isFinite(contribution) && contribution > 0
                                        ? "text-accent-amber"
                                        : "text-slate-400";
                                  return (
                                    <td key={id} className={`py-2 pr-3 ${cls}`}>
                                      {text}
                                    </td>
                                  );
                                })}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </section>

                    <details className="rounded border border-tactical-700 bg-black/30 p-3">
                      <summary className="cursor-pointer font-mono text-xs uppercase tracking-[0.2em] text-tactical-200">
                        Raw Compare JSON
                      </summary>
                      <pre className="mt-3 max-h-[420px] overflow-auto text-xs text-slate-200">
                        {JSON.stringify(compareResult, null, 2)}
                      </pre>
                    </details>
                  </div>
                ) : (
                  <p className="mt-3 text-sm text-slate-400">No comparison loaded.</p>
                )}
              </section>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

export default App;
