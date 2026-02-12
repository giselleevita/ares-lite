import { useEffect, useMemo, useState } from "react";

import { getHealth, getScenarios, type Scenario } from "./lib/api";

type Status = "online" | "degraded";

function App() {
  const [status, setStatus] = useState<Status>("degraded");
  const [serviceName, setServiceName] = useState("ares-lite-backend");
  const [scenarios, setScenarios] = useState<Scenario[]>([]);

  useEffect(() => {
    const load = async () => {
      try {
        const [health, scenarioPayload] = await Promise.all([getHealth(), getScenarios()]);
        setStatus(health.status === "ok" ? "online" : "degraded");
        setServiceName(health.service);
        setScenarios(scenarioPayload.scenarios);
      } catch {
        setStatus("degraded");
      }
    };

    void load();
  }, []);

  const placeholderReadiness = useMemo(
    () => [
      { label: "urban_dusk", score: 82 },
      { label: "forest_occlusion", score: 67 },
      { label: "swarm_stress", score: 61 },
    ],
    [],
  );

  return (
    <div className="min-h-screen bg-tactical-950 text-slate-100">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(45,95,135,0.2),transparent_45%),radial-gradient(circle_at_80%_10%,rgba(216,180,95,0.12),transparent_30%),radial-gradient(circle_at_50%_80%,rgba(190,92,92,0.1),transparent_35%)]" />
      <main className="relative mx-auto max-w-6xl px-6 py-10 md:px-10">
        <header className="mb-8 flex flex-col gap-4 border-b border-tactical-700 pb-6">
          <p className="font-mono text-xs uppercase tracking-[0.24em] text-tactical-300">ARES LITE // COUNTER-UAS RELIABILITY RANGE</p>
          <h1 className="font-tactical text-4xl font-semibold uppercase tracking-wide text-slate-100 md:text-5xl">Operational Readiness Simulator</h1>
          <p className="max-w-2xl text-sm text-slate-300 md:text-base">
            Battlefield-oriented test harness for stress-testing aerial detection reliability under frontline environmental degradation.
          </p>
        </header>

        <section className="grid gap-4 md:grid-cols-3">
          <article className="rounded border border-tactical-700 bg-tactical-900/70 p-4 shadow-glow">
            <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Backend Status</p>
            <p className="mt-3 font-tactical text-2xl uppercase text-slate-100">{status === "online" ? "Online" : "Degraded"}</p>
            <p className="mt-2 text-sm text-slate-300">Service: {serviceName}</p>
          </article>
          <article className="rounded border border-tactical-700 bg-tactical-900/70 p-4 shadow-glow">
            <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Scenarios Loaded</p>
            <p className="mt-3 font-tactical text-2xl text-slate-100">{scenarios.length}</p>
            <p className="mt-2 text-sm text-slate-300">Bundled stress profiles available for run execution.</p>
          </article>
          <article className="rounded border border-tactical-700 bg-tactical-900/70 p-4 shadow-glow">
            <p className="font-mono text-xs uppercase tracking-widest text-tactical-300">Alert Fatigue (Placeholder)</p>
            <p className="mt-3 font-tactical text-2xl text-accent-amber">0.42 / min</p>
            <p className="mt-2 text-sm text-slate-300">Final metric pipeline wired in later phases.</p>
          </article>
        </section>

        <section className="mt-8 rounded border border-tactical-700 bg-tactical-900/60 p-5">
          <h2 className="font-tactical text-xl uppercase tracking-wider text-slate-100">Scenario Readiness Snapshot</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {placeholderReadiness.map((item) => (
              <div key={item.label} className="rounded border border-tactical-700 bg-tactical-800/50 p-4">
                <p className="font-mono text-xs uppercase tracking-widest text-tactical-200">{item.label}</p>
                <p className="mt-2 font-tactical text-3xl text-slate-100">{item.score}</p>
                <p className="text-xs uppercase tracking-wide text-slate-400">Operational Readiness</p>
              </div>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
