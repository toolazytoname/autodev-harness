#!/bin/bash
# =============================================================================
# AutoDevHarness — thin entry point, forwards to `python -m harness`.
# Legacy bash implementation preserved as autodev-harness-legacy.sh
# (delete after 30 days per TASKS.md T07; kept since 2026-07-06).
# Set AUTODEV_USE_LEGACY=1 to run the old bash pipeline.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${AUTODEV_USE_LEGACY:-}" == "1" ]]; then
    exec "$SCRIPT_DIR/autodev-harness-legacy.sh" "$@"
fi

if command -v uv >/dev/null 2>&1; then
    exec uv run --project "$SCRIPT_DIR" python -m harness "$@"
fi

exec python3 -m harness "$@"
