# AutoDevHarness — Environment Variables

T27 — single source of truth for every `AUTODEV_*` environment variable
the harness reads. The runtime source is `harness/env.py::EnvVars`;
this file mirrors it in a format operators can grep / cite in runbooks.

## Per-tier model overrides

Format: `AUTODEV_<KEY>_<TIER>` where `<TIER>` is one of
`ARCHITECT` / `REVIEWER` / `WORKER` (uppercase).

| Variable                       | Purpose                                | Consumed by                 |
|--------------------------------|----------------------------------------|-----------------------------|
| `AUTODEV_MODEL_<TIER>`         | Override the model for a tier          | `router.ModelRouter.resolve` |
| `AUTODEV_API_KEY_<TIER>`       | Override the API key for a tier        | `pipeline`, `generator`, `reviewer_runner` |
| `AUTODEV_BASE_URL_<TIER>`      | Override the API base URL for a tier   | `router.ModelRouter.resolve` |
| `AUTODEV_FALLBACK_<TIER>`      | Override the fallback model for a tier | `router.ModelRouter.resolve` |

Example: `AUTODEV_MODEL_WORKER=claude-haiku-4-5-20251001` makes the
worker tier use Haiku even when `config/models.yaml` points elsewhere.

## Human feedback loops (non-TTY / CI runs)

| Variable                | Phase | Purpose                                       |
|-------------------------|-------|-----------------------------------------------|
| `AUTODEV_PLAN_FEEDBACK` | plan  | Free-form feedback string for the plan phase |
| `AUTODEV_UI_CHOICE`     | ui    | Pick a version (1-4) for the UI phase        |
| `AUTODEV_UI_FEEDBACK`   | ui    | Free-form feedback string for the UI phase   |
| `AUTODEV_UI_DIRECTION`  | ui    | Force the recommended UI direction by slug   |

These are read once (T23) and the value is consumed into the pipeline's
instance state — the env var itself is never mutated, so other
pipelines / tests see a clean environment.

## Visual reviewer

| Variable                 | Purpose                                                    |
|--------------------------|------------------------------------------------------------|
| `AUTODEV_VISUAL_BASE_URL`| Base URL the visual reviewer uses to capture pages        |

Default: `http://127.0.0.1:8765` (constant `DEFAULT_VISUAL_BASE_URL`
in `harness/reviewer_runner.py`).

## Test mode

| Variable            | Purpose                                                       |
|---------------------|---------------------------------------------------------------|
| `AUTODEV_TEST_MODE` | Set to `1` to disable the slow-test skip in CI runs           |

## Removed in T27

- `AUTODEV_USE_LEGACY` — the `AUTODEV_USE_LEGACY=1` switch in
  `autodev-harness.sh` and the underlying `autodev-harness-legacy.sh`
  bash pipeline have been deleted. The Python pipeline is the only
  supported path.
- The legacy `AUTODEV_MODEL` / `AUTODEV_API_KEY` / `AUTODEV_BASE_URL`
  (no `_TIER` suffix) names from the bash pipeline are gone too —
  always set the per-tier override instead.

## Adding a new variable

1. Add the constant to `harness/env.py::EnvVars`.
2. Use `EnvVars.MY_VAR` in the read site; never inline the string.
3. Document it in the table above.
4. Add a unit test that exercises the new attribute (typos should
   surface as `AttributeError`, not silent `None`).