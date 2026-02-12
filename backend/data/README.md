# ARES Lite Offline Demo Dataset (Phase 2)

This folder contains deterministic synthetic assets for offline CPU-only demos.

## Clips

- `clips/urban_dusk_demo.mp4`
  - 8s, 854x480, 15 FPS
  - single drone-like target
- `clips/forest_occlusion_demo.mp4`
  - 8s, 854x480, 15 FPS
  - two drone-like targets with occlusion bars
- `clips/clutter_false_positive.mp4`
  - 8s, 854x480, 15 FPS
  - clutter-only scene for false-positive testing

## Ground Truth

JSON format follows:

```json
{
  "0": [{"bbox": [x, y, w, h], "label": "drone"}],
  "1": [...]
}
```

Files:
- `annotations/urban_dusk_demo.json`
- `annotations/forest_occlusion_demo.json`
- `annotations/clutter_false_positive.json`

## Regenerate Assets

From repo root:

```bash
make dataset
```

or

```bash
python3 scripts/generate_synthetic_dataset.py
```
