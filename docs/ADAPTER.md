# Adapter Integration Guide

The harness talks to model CLIs through a thin adapter layer. Each
adapter implements the same minimal surface so the rest of the
codebase can swap providers without changes.

## Interface

All adapters inherit from `harness.adapters.base.AdapterBase` and
implement:

```python
class AdapterBase(ABC):
    @abstractmethod
    def run(
        self,
        prompt: str,
        *,
        model: str,
        cwd: Path,
        timeout: int = 600,
    ) -> AgentResult: ...
```

`AgentResult` carries:

| field        | type    | meaning                                  |
|--------------|---------|------------------------------------------|
| `stdout`     | str     | the model's response text                |
| `stderr`     | str     | CLI's stderr (usually empty)             |
| `exit_code`  | int     | 0 = success                              |
| `usage`      | Usage   | token counts (input/output/total)        |
| `duration_ms`| int     | wall-clock duration                      |

## Implementations

### `ClaudeAdapter` (`harness/adapters/claude.py`)

The default. Wraps `claude -p --model <m> --output-format json` and
parses the JSON response. The `output-format json` mode is required
because it gives us:

- `result` — the model's reply, free of any CLI artifacts
- `usage` — token counts
- `is_error` — distinguishes genuine model output from CLI errors

We also implement:

- **Exponential backoff retry** on 429 / 5xx (up to 3 attempts)
- **Tier fallback** — when retries are exhausted, the adapter asks
  the router for the fallback model and tries once more
- **Timeout** — subprocess timeout in seconds; defaults to 600

### `OpencodeAdapter` (`harness/adapters/opencode.py`)

A stub. Real implementation should:

1. Spawn `opencode run --model <m> < prompt.txt`
2. Capture stdout and parse the JSON the CLI emits (its
   `--output-format json` is similar to claude's)
3. Map token usage from the JSON to `Usage`

The interface contract is identical to `ClaudeAdapter.run` — call
sites don't need to know which one is active.

### `CodexAdapter` (`harness/adapters/codex.py`)

A stub. Real implementation should wrap `codex exec --model <m>
--json < prompt.txt` and parse the response.

## Selecting an adapter

The router (`harness/router.py`) resolves a stage name (e.g.
`"plan"`, `"review.correctness"`) to a `ModelSpec(model=..., tier=...)`
and the pipeline passes the model name to the adapter. The adapter
itself is selected at pipeline construction time:

```python
from harness.adapters.claude import ClaudeAdapter
from harness.pipeline import Pipeline

adapter = ClaudeAdapter()  # the default
pipeline = Pipeline(config, adapter=adapter, ...)
```

To use a different adapter, swap the import — no other changes
required.

## Adding a new adapter

1. Create `harness/adapters/<name>.py` with a class that inherits
   from `AdapterBase`.
2. Implement `run(prompt, *, model, cwd, timeout) -> AgentResult`.
3. Map the CLI's `--output-format json` response to `AgentResult`.
4. Add a `__init__` that takes the CLI path (or auto-detects it)
   and any auth tokens.
5. Add tests under `tests/test_adapters.py` that mock `subprocess`
   and exercise:
   - happy path (exit 0, parsed JSON)
   - retry path (429 → backoff → success)
   - timeout path (subprocess killed after N seconds)
   - fallback path (all retries exhausted → fallback model)
6. Document the new adapter in this file.

## Platform-specific notes

- **macOS**: `claude` is installed via `npm install -g @anthropic-ai/claude-cli` or downloaded from anthropic.com. The harness
  uses PATH resolution.
- **Linux**: same as macOS. Headless servers work — no display
  required.
- **Windows**: works in WSL2. Native Windows is untested.
