# AutoDevHarness v2

[![tests](https://github.com/toolazytoname/autodev-harness/actions/workflows/tests.yml/badge.svg)](https://github.com/toolazytoname/autodev-harness/actions/workflows/tests.yml)
[![lint](https://github.com/toolazytoname/autodev-harness/actions/workflows/lint.yml/badge.svg)](https://github.com/toolazytoname/autodev-harness/actions/workflows/lint.yml)

AI-driven development harness with **independent quality loops**. The
model is the cheapest component — quality comes from the *structure*
(generate → independent reviewers → gate → commit).

> "Say one sentence, walk away, come back to a high-quality result."
> The human appears at three points: (1) brief, (2) plan/UI
> confirmation, (3) final acceptance. Everything else is the harness.

## What's new in v2

The original `autodev-harness.sh` is now a thin forwarder to a
Python implementation. The orchestrator, the gate, the Linear sync,
the cross-platform tests, the visual reviewer, and the taste-injected
UI design all live in the `harness/` package.

- **Outer pipeline** (`harness/pipeline.py`): research → plan → UI
  design (4 directions) → tasks → develop, with checkpoint resume.
- **Inner quality loop** (`harness/inner_loop.py`): for every task,
  generate in a worktree → N parallel reviewers → gate. Iterate
  until all reviewers pass; escalate if MAX_ITER is hit.
- **Taste injection** (T08): four aesthetic directions (editorial
  minimal / high-end motion / data-dense industrial / premium
  default), each driven by a bundled skill subset. Slop check
  blocks generic gradients, Inter font, etc.
- **Reuse decision table** (T10): researcher's output must include
  a `## 复用决策表` with fork/port/wrap/drop decisions. Pipeline
  refuses to advance without it.
- **Acceptance criteria** (T11): every task lists executable steps;
  the test reviewer converts them into commands.
- **Visual reviewer** (T09): Playwright captures the running app and
  scores it against the UI spec.
- **Linear sync** (T12): tasks become Linear issues; gate pass /
  escalation mirrors back. Falls back to a local in-memory store
  when `LINEAR_API_KEY` is unset.
- **Cross-platform testing** (T13): reviewer selection gains a
  `platform` dimension — `mobile` (Maestro) and `miniprogram`
  (miniprogram-automator) reviewers added on top of the kind's
  default set.

## Quick start

```bash
# Install
git clone <repo>
cd autodev-harness
uv sync  # or: python -m venv .venv && source .venv/bin/activate && pip install -e .

# Configure (optional — defaults work out of the box)
export ANTHROPIC_API_KEY="sk-..."
export LINEAR_API_KEY="lin_api_..."  # optional; falls back to local mode

# Run
python -m harness -- "做一个 TODO web app"
```

The pipeline:
1. Writes `000-brief.md` from your description.
2. Asks the researcher to produce `001-research-report.md` (must
   include a 复用决策表).
3. Asks the planner to produce `002-plan.md`. Pauses for human
   feedback unless `AUTODEV_PLAN_FEEDBACK` is set.
4. Asks the UI designer to produce 4 aesthetic directions, saves
   `006-ui-spec.md` + `preview/versions/*.html`. Pauses for human
   choice.
5. Asks the taskgen to produce `003-task-queue.json` (every task
   has `kind` and `acceptance`).
6. Runs the inner loop on each task: generate → reviewers → gate.

## CLI

```bash
python -m harness [DIR] -- "description"
python -m harness --test       # smoke test mode (TODO app)
python -m harness --iterate    # resume from checkpoint
python -m harness --phase X    # start at a specific phase
python -m harness --continue   # resume from saved state
python -m harness config       # print the current routing table
python -m harness status       # print the current workflow state
```

## Architecture

```
┌─ Outer Pipeline (harness/pipeline.py) ──────────────────────────────┐
│ research → plan ⇄human → ui_design ⇄human → tasks → develop       │
│ (each phase produces a numbered artifact)                          │
└─────────────────────────────────────────────────────────────────────┘
                                │ per task
┌─ Inner Quality Loop (harness/inner_loop.py) ────────────────────────┐
│ spec → Generate(worktree) → N Reviewers in parallel → Gate        │
│ fail → blockers back into generator, iter++                       │
│ hit MAX_ITER → escalate, preserve worktree for arbitration         │
└─────────────────────────────────────────────────────────────────────┘
         │                    │                    │
   ┌──────────┐         ┌──────────┐         ┌──────────┐
   │Router    │         │Adapters  │         │Linear    │
   │(YAML     │         │(claude / │         │Sync      │
   │routing)  │         │opencode/ │         │(MCP+local│
   │          │         │codex)    │         │ fallback)│
   └──────────┘         └──────────┘         └──────────┘
```

## Documentation

- `docs/MASTER-PLAN.md` — the design rationale
- `docs/REVIEW.md` — the v1 review that drove v2
- `docs/TASKS.md` — the task list
- `docs/ADAPTER.md` — adding a new model adapter
- `docs/CROSS-PLATFORM-TESTING.md` — web / mobile / miniprogram
- `docs/COMPETITIVE-ANALYSIS.md` — 竞品对照与差距分析

## Tests

```bash
.venv/bin/python -m pytest tests/         # unit + integration (287 tests)
.venv/bin/python -m pytest -m "not slow"  # skip real-model tests
.venv/bin/python -m pytest --cov=harness  # coverage report
```

Coverage target: ≥ 80%. Current: 83%.

## Routing table

`config/models.yaml` is the single source of truth. Example:

```yaml
tiers:
  architect: { model: claude-fable-5, fallback: claude-opus-4-8 }
  reviewer:  { model: claude-sonnet-5, fallback: claude-haiku-4-5-20251001 }
  worker:    { model: MiniMax-M2.7, base_url: https://api.minimaxi.com/anthropic,
               fallback: claude-haiku-4-5-20251001 }
assignments:
  research: worker
  plan: architect
  ui_design: reviewer
  taskgen: worker
  generate: worker
  review.correctness: reviewer
  review.test: worker
  review.boundary: reviewer
  review.visual: reviewer
  review.a11y: worker
  review.mobile: reviewer
  review.miniprogram: reviewer
  escalation: architect
  final_acceptance: architect
```

`python -m harness config` prints the resolved table.

## Reviewer selection

`config/reviewers.yaml` maps `kind` × `platform` → reviewer list:

```yaml
reviewers:
  ui:     [correctness, test, boundary, a11y, visual]
  api:    [correctness, test, boundary, security]
  logic:  [correctness, test, boundary]
  infra:  [correctness, test, boundary, security]

platform_reviewers:
  web:        []              # visual is already in ui
  mobile:     [mobile]        # Maestro
  miniprogram:[miniprogram]   # automator on macOS
```
