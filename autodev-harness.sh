#!/bin/bash
# =============================================================================
# AutoDevHarness — entry point, forwards to `python -m harness`.
# =============================================================================
# T27 — the legacy 707-line bash implementation that used to live in
# ``autodev-harness-legacy.sh`` (and the ``AUTODEV_USE_LEGACY=1``
# switch) has been removed; the Python pipeline is the only supported
# path. See docs/ENV.md for the env vars the Python pipeline reads.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if command -v uv >/dev/null 2>&1; then
    exec uv run --project "$SCRIPT_DIR" python -m harness "$@"
fi

exec python3 -m harness "$@"