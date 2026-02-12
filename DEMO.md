# ARES Lite — 2 Minute Demo Script (Phase 1)

## Objective

Show that ARES Lite already behaves like a deployable reliability product scaffold:
- system boots with one command
- scenarios are loaded through API
- canned readiness output demonstrates stress impact narrative

## Pre-demo Setup

```bash
cd /Users/yusaf/ARES-lite
make setup
```

## Demo Flow (2 minutes)

1. Start stack
```bash
make dev
```
What to say:
- "ARES Lite is an offline CPU-safe reliability simulator for Counter-UAS systems."
- "Backend and frontend are running locally with deterministic behavior."

2. Open UI
- Navigate to `http://127.0.0.1:5173`
- Point at:
  - Operational title
  - Backend status card
  - Scenario count card
  - Readiness snapshot cards

3. Validate backend endpoints quickly (new terminal)
```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/scenarios
```
What to say:
- "Scenarios and health telemetry are exposed via the API surface that later phases consume."

4. Run canned readiness demo (new terminal)
```bash
make demo
```
Expected output:
- `urban_dusk readiness: 82`
- `forest_occlusion readiness: 67`
- `degradation observed under stress: yes`

What to say:
- "Even in Phase 1, the demo mode establishes the final product narrative: stress lowers readiness."

## Backup Mode

If the UI cannot be shown live:
1. Run API checks and `make demo` only.
2. Explain this is scaffold mode and full reliability pipeline is wired in upcoming phases.

## Exit

Stop `make dev` with `Ctrl+C`.
