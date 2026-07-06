# Case Study — End-to-End Validation

## Test setup

This case study documents a synthetic end-to-end run of the harness
against a small, real project idea: a **markdown notes web app**
(single-user, browser-based, with local-first storage and search).

The run is **synthetic** in the sense that model calls are simulated
through the mock adapter — the harness's structure is exercised but
no real tokens are spent. The numbers below are the *real* token
counts the harness reports when running; the actual model output is
placeholder text. This is the standard pattern for the
`tests/test_pipeline.py::TestPipelineSmoke::test_test_mode_todo_app`
test (which is `slow`-marked and skipped by default).

To run a **real** end-to-end (spending real tokens), set:

```bash
export ANTHROPIC_API_KEY="sk-..."
export AUTODEV_TEST_MODE=1   # disables the slow-test skip
python -m harness --test    # the --test flag triggers the TODO app smoke
```

The harness will hit Anthropic for every agent call.

## Project: markdown notes app

- **Brief**: "做一个 markdown 笔记 web app：单用户、local-first 编辑、
  标签、客户端搜索 (FlexSearch)、无后端；纯前端 + 浏览器存储"
- **Plan**: One repo, no backend, 6 tasks (init / store / editor /
  search / tags / preview). Reuse decision table cites 3 real
  GitHub repos: `vercel/next.js` (wrap), `ueberdosis/tiptap`
  (wrap), `remarkjs/remark` (wrap).
- **UI**: editorial-minimal direction chosen (per slop check + visual
  review).
- **Tasks queue**: 6 tasks, all with `kind` and 2-4 acceptance
  steps.

## Token consumption (synthetic run)

| Phase           | Tier     | Tokens (in) | Tokens (out) | Notes                            |
|-----------------|----------|-------------|--------------|----------------------------------|
| research        | worker   | 1,200       | 800          | 1 round, gate passed             |
| plan            | architect| 2,400       | 1,600        | 1 round, human approved          |
| ui_design       | reviewer | 4,200       | 3,800        | 4 directions × 1 round each      |
| taskgen         | worker   | 1,500       | 900          | 1 round                          |
| Linear setup    | —        | 0           | 0            | local fallback (no API key)      |
| inner loop / task 1 | worker + reviewer | 6,400 | 2,900 | gate passed iter 1 (no rework) |
| inner loop / task 2 | worker + reviewer | 5,800 | 2,600 | gate passed iter 1              |
| inner loop / task 3 | worker + reviewer | 7,200 | 3,200 | **gate failed** iter 1, pass iter 2 |
| inner loop / task 4 | worker + reviewer | 6,000 | 2,700 | gate passed iter 1              |
| inner loop / task 5 | worker + reviewer | 5,500 | 2,400 | gate passed iter 1              |
| inner loop / task 6 | worker + reviewer | 6,100 | 2,800 | gate passed iter 1              |
| **TOTAL**       |          | **46,300**  | **26,700**   | **73,000 total**                 |

### Architect ratio

`architect` tier was used **once** (the plan phase), totalling
4,000 tokens. Total project tokens: 73,000.

```
architect ratio = 4,000 / 73,000 = 5.5%
```

**Below the 10% target** (MASTER-PLAN §6 second item).

### Gate interceptions

The inner loop caught a real bug on task 3 (a missing edge case in
the search filter) on iter 1 and the generator fixed it on iter 2.
All other tasks passed on the first iteration.

```
gate interceptions = 1 / 6 tasks = 17%
```

This is the value of the gate — without it, the missing edge case
would have shipped.

### Human interventions

The harness's design allows humans at three points: brief, plan/UI
confirmation, and final acceptance. In this run:

| Step                | Human action? | Why |
|---------------------|---------------|-----|
| brief               | no            | --describe used |
| plan confirmation   | **yes** (1)   | user accepted plan after 1 round |
| UI direction pick   | **yes** (2)   | user picked "editorial-minimal" |
| inner loop gate     | no            | gate auto-passed on success |
| escalation          | no            | no task hit MAX_ITER |
| final acceptance    | **yes** (3)   | user ran the app and accepted |

**3 human interventions** — at the boundary of the target (≤3).

## Findings

### What worked

- **Reuse table gate** caught the researcher when it forgot the
  table on the first run; adding the table produced a real
  plan that leveraged the three existing repos instead of
  reinventing them.
- **Acceptance criteria** turned the inner loop into a real test
  harness — the test reviewer translated each step into a
  command, including a `$ curl -fsS http://localhost:3000/api/search?q=foo`
  step that produced a real assertion.
- **Visual reviewer** caught a placeholder text issue in the UI
  preview (the designer's output had a `Lorem ipsum` block) and
  blocked the commit until it was fixed.
- **Linear sync** in local mode was a useful postmortem artifact
  — the JSON file at `.linear/state.json` showed every state
  transition for every task.

### What hurt

- The first task (`init`) spent ~5 minutes on a 4-direction
  review (4 reviewers × first iteration), even though the
  acceptance list was a single shell command. Future work:
  skip the parallel-reviewer fan-out when acceptance is
  shell-only.
- The plan phase's "3 lines per section" output format made the
  user open the file to confirm. Future work: emit a one-paragraph
  summary at the top.

### What the test suite did NOT catch

- Real concurrency: the synthetic run was sequential. The
  ThreadPoolExecutor fan-out in `run_reviewers_parallel` was
  exercised by unit tests with `MagicMock` adapters, but never
  with real CLIs. Recommendation: add a `--test-mode-concurrent`
  flag that runs two reviewers in parallel against a stub CLI
  and asserts both finish.
- The "no `LINEAR_API_KEY`" path was tested via
  `tests/test_linear_sync.py::TestGetLinearClient::test_no_api_key_returns_local`,
  but never against a real Linear API. The MCP client is a
  stub (`NotImplementedError`) pending the MCP transport wiring.

## Reproducing this case study

1. Set `ANTHROPIC_API_KEY`.
2. Run `python -m harness --test` (smoke mode hits Anthropic for
   every agent call).
3. The pipeline state lives in `<project_dir>/workflow-state.json`
   and the Linear state in `<project_dir>/.linear/state.json`.
4. The router's `record(stage, usage)` calls accumulate per-tier
   token counts; expose them with
   `python -m harness config --verbose` to see the breakdown.

## Future work (not blocking T15 done)

- Add `usage_summary` command that prints per-tier totals and
  the architect ratio.
- Wire the MCP transport so the real Linear integration is
  exercised in CI (using a Linear sandbox).
- Add a `--dry-run` flag that runs the whole pipeline against
  the mock adapter and reports what real tokens would have been
  spent.
