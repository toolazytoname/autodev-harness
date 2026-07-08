#!/bin/bash
# =============================================================================
# AutoDevHarness — entry point, forwards to `python -m harness`.
# =============================================================================
# This shell script is preserved as a thin compatibility shim because:
#   - CI scripts / docs reference `./autodev-harness.sh`
#   - The legacy bash pipeline (Phase + lib/* + config/providers.sh) was
#     retired in favour of the Python pipeline shipped by T07 (M1) and
#     hardened by T17–T27 (M4/M5).
#
# Any flag previously understood by the legacy bash version
# (--new/--iterate/--test/--provider/--max-iterations/--restart/--llm-url/…)
# is now handled by `python -m harness`. Pass them through unchanged:
#
#   ./autodev-harness.sh --new /path/to/project
#   ./autodev-harness.sh --continue /path/to/project
#   ./autodev-harness.sh --test
#   AUTODEV_MODEL_WORKER=haiku-x ./autodev-harness.sh --iterate /path
#
# For the full env-var contract (AUTODEV_MODEL_<TIER>, AUTODEV_API_KEY_<TIER>,
# AUTODEV_BASE_URL_<TIER>, AUTODEV_FALLBACK_<TIER>, AUTODEV_PLAN_FEEDBACK,
# AUTODEV_UI_*, AUTODEV_VISUAL_BASE_URL, AUTODEV_TEST_MODE) see docs/ENV.md.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Optional one-time heads-up so long-running terminals don't think the
# shell is silently dropping flags it used to handle. Cheap: 1 echo,
# no branch logic, exits 0 even when stdout is not a TTY.
echo "autodev-harness.sh is a thin shim — forwarding to python -m harness" >&2

if command -v uv >/dev/null 2>&1; then
    exec uv run --project "$SCRIPT_DIR" python -m harness "$@"
fi

exec python3 -m harness "$@"