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

## Registering a new adapter (T32 contract)

The pipeline dispatches to the right backend per-tier via the central
`ADAPTER_REGISTRY` in `harness/adapters/__init__.py`. The contract for
adding a new adapter:

1. **Implement the class.** Subclass `AdapterBase` in a new module
   under `harness/adapters/`. The class must implement `_execute(...)`
   returning an `AgentResult`. The full interface is described at the
   top of `harness/adapters/base.py`.

2. **Register the name.** Add a key → class entry in
   `ADAPTER_REGISTRY`:
   ```python
   ADAPTER_REGISTRY: dict[str, type[AdapterBase]] = {
       "claude": ClaudeAdapter,
       "your_backend": YourAdapter,
   }
   ```
   Only register a backend that **fully works** — T32's rule is
   "注册过的 adapter 必须能跑". A `NotImplementedError` stub must NOT
   be in the registry; instead, leave it as a non-registered module
   (the opencode/codex stubs are excluded for this reason).

3. **Reference it from YAML.** Set `adapter: your_backend` under the
   tier that should use it in `config/models.yaml`. The default
   (`adapter: claude`) is implied when the field is omitted.

4. **Validate before running.** `python -m harness --validate-config`
   loads the YAML, checks every tier's `adapter` against the registry,
   and exits non-zero with a clear error if anything is off. Run this
   in CI on every PR — it's the cheapest way to catch a typo in the
   adapter name.

5. **Per-tier resolution.** The pipeline looks up the adapter name
   through `pipeline._adapter_resolver(name)`. The default resolver
   reads from `ADAPTER_REGISTRY`; tests can inject a custom resolver
   to swap backends per-test without touching the registry.

6. **Update the spec / tests / docs.** Add the adapter to
   `tests/test_adapters.py`, list the prerequisites in the
   "Platform-specific notes" section above, and confirm the
   `tests/test_t32_adapter_factory.py` registry tests still pass
   (they assert "claude" is registered, but additional keys are
   allowed).
