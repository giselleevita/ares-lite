# ARES Lite — 2 Minute Demo Script (Certification Kit)

## Goal

In 2 minutes, prove ARES Lite is more than a CV demo: it is an offline, reproducible test range with:
- deterministic runs + benchmarking
- evidence packs with chain-of-custody hashes
- policy-as-code gates (PASS/FAIL)
- delta-first comparisons (baseline vs stress)

## Pre-Demo (30s)

```bash
cd /Users/yusaf/ARES-lite
make doctor
```

If ports are busy, pick alternates:
- Local dev: `ARES_BACKEND_PORT=8001 ARES_FRONTEND_PORT=5174 make demo`
- Docker: `ARES_BACKEND_PORT=8001 ARES_FRONTEND_PORT=5174 make docker-demo`

## Demo Flow (2 minutes)

1) Start the stack (one command)
```bash
make demo
```
Say:
- "Offline, CPU-only, deterministic by seed. No external infra."

2) Open UI
- `http://127.0.0.1:5173`
Say:
- "Single run still works. Benchmarks and compare are additive."

3) Run Demo (deterministic)
- Click `Run Demo` (fixed seed)
Say:
- "Same inputs produce the same outputs. This is critical for audit and regression testing."

4) Show Gate + Evidence Pack
- After completion: note `Gate: PASS/FAIL/UNKNOWN`
- Click `Download Evidence Pack`
Say:
- "This ZIP contains the report + JSONs + overlays and a manifest with SHA256 hashes. That is chain-of-custody."

5) Benchmark Batch (30s)
- Go to `Benchmarks`, create a small batch:
  - profiles: baseline + fog (or low_light)
  - seeds: 12345
- When complete: point at:
  - gate pass-rate
  - worst regressions
  - `Download CSV` and `Download Evidence Pack`
Say:
- "This becomes a release gate. We can run it in CI and fail builds on regressions."

6) Compare (20s)
- Go to `Compare`, select baseline + stressed run(s)
- Point at deltas and `Top Regressions`
Say:
- "Delta-first view shows what regressed under stress and by how much."

## Exit

- Stop `make demo` with `Ctrl+C`.
- Docker: `ARES_BACKEND_PORT=8001 ARES_FRONTEND_PORT=5174 make docker-selftest` for a proof run.
