"""Provider-agnostic JSON envelope parsing for CLI adapters.

T30 — these five helpers were previously private methods on
:class:`harness.adapters.claude.ClaudeAdapter`. They have no
claude-specific knowledge (no rate-limit regexes, no structured-error
key names) so they belong here and can be reused verbatim by the
upcoming ``OpenCodeAdapter`` / ``CodexAdapter``.

The parser contract: ``--output-format json`` style output may be a
top-level object, a one-element array wrapping an object, or a chatty
preamble followed by the JSON. We strip any markdown fences, then walk
the text with ``json.JSONDecoder.raw_decode`` (O(n)) and unwrap the
common one-element array shape. On a hard-error envelope
(``is_error: true``), we raise :class:`InvalidResponseError` so the
caller never silently consumes a failed response as an empty success.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from harness.adapters.base import InvalidResponseError, Usage


__all__ = [
    "parse_json_output",
    "loads_json_envelope",
    "strip_code_fence",
    "extract_json",
    "parse_usage",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_json_output(
    raw_stdout: str,
    duration_ms: int,
) -> tuple[Usage, str]:
    """Parse ``--output-format json`` style output from a CLI adapter.

    The JSON may be wrapped in a markdown code fence. We strip it if
    present. Expected top-level shape:

    - object: ``{"result": "...", "usage": {...}}``
    - array: ``[{"result": "...", "usage": {...}}]`` — some CLI
      builds wrap the envelope in a one-element list. We unwrap the
      first element when this happens.

    Returns ``(Usage, result_text)``.

    Raises
    ------
    InvalidResponseError
        T25 — when the output is not parseable as JSON. The legacy
        implementation silently returned the raw text, which made
        downstream consumers believe the literal stdout was the
        result. We treat ``--output-format json`` as a contract:
        anything else is a broken response.

        T30 — when the JSON parses but ``is_error`` is truthy. A
        hard-error envelope often returns ``exit_code == 0`` (e.g.
        ``invalid_request``, auth failure) so we cannot rely on the
        exit code alone. Surfacing as ``InvalidResponseError``
        (non-retryable per ``NON_RETRYABLE_EXCEPTIONS``) ensures the
        failure propagates instead of being swallowed as "".
    """
    text = raw_stdout.strip()
    fence_stripped = strip_code_fence(text)

    data = loads_json_envelope(fence_stripped)
    if data is None:
        raise InvalidResponseError(
            "JSON envelope returned unparseable output: "
            + repr(text[:200])
        )

    # Unwrap a one-element array envelope.
    if isinstance(data, list):
        if not data:
            raise InvalidResponseError(
                "JSON envelope returned an empty array"
            )
        data = data[0]
        if not isinstance(data, dict):
            raise InvalidResponseError(
                "JSON array envelope did not contain an object: "
                f"{type(data).__name__}"
            )

    # T30 — Bug B: a JSON envelope with ``is_error: true`` is a hard
    # error that often comes back with ``exit_code == 0``. The legacy
    # implementation found none of result/content/text and silently
    # returned "", which made downstream consumers believe the call
    # succeeded with empty output. Surface as InvalidResponseError
    # (non-retryable) so the failure is propagated.
    if isinstance(data, dict) and data.get("is_error"):
        error_text = str(
            data.get("error")
            or data.get("error_type")
            or "unknown error"
        )
        status = data.get("status_code")
        raise InvalidResponseError(
            "is_error envelope"
            + (f" (status_code={status})" if status is not None else "")
            + f": {error_text[:200]}"
        )

    usage = parse_usage(data, duration_ms)

    # Prefer the first explicitly present text field. ``data.get(x)``
    # style fallback would swallow legitimate falsy values (e.g. an
    # empty-string ``result``) via the ``or`` short-circuit — explicit
    # ``in``/``is not None`` guards keep the distinction.
    result_text = ""
    for key in ("result", "content", "text"):
        if key in data and data[key] is not None:
            result_text = str(data[key])
            break

    return usage, result_text


def loads_json_envelope(text: str):
    """Parse ``text`` as a JSON object or array, or return ``None``.

    T25 — replaces an O(n²) progressive-slicing loop with a single
    O(n) ``JSONDecoder.raw_decode`` walk. Also handles top-level
    arrays, which the legacy version silently rejected.
    """
    if not text:
        return None
    decoder = json.JSONDecoder()
    # Find the first JSON value boundary. ``raw_decode`` itself
    # tolerates leading whitespace, but we look for ``{`` or ``[``
    # explicitly so a chatty preamble ("thinking: ... {json}") is
    # handled cleanly without a manual scan.
    for opener in ("{", "["):
        start = text.find(opener)
        if start == -1:
            continue
        try:
            data, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        return data
    return None


_CODE_FENCE_JSON_RE = re.compile(r"^```json\s*\n", flags=re.MULTILINE)
_CODE_FENCE_RE = re.compile(r"^```\s*\n", flags=re.MULTILINE)
_CODE_FENCE_END_RE = re.compile(r"\n```\s*$", flags=re.MULTILINE)


def strip_code_fence(text: str) -> str:
    """Remove triple-backtick markdown fences from JSON output.

    Recognises both ``\\`\\`\\`json\\n…\\n\\`\\`\\```` and the plain
    ``\\`\\`\\`\\n…\\n\\`\\`\\```` shape. Returns the input with
    leading/trailing whitespace stripped.
    """
    text = _CODE_FENCE_JSON_RE.sub("", text)
    text = _CODE_FENCE_RE.sub("", text)
    text = _CODE_FENCE_END_RE.sub("", text)
    return text.strip()


def extract_json(text: str) -> Optional[dict]:
    """Linear-time JSON object/array extractor with dict-only return.

    T25 — was O(n²) via progressive slicing. Delegates to
    :func:`loads_json_envelope` and unwraps a one-element array
    envelope so the legacy ``dict`` return contract is preserved.
    Returns ``None`` when the input is unparseable or the JSON is a
    non-object, non-one-element-array.
    """
    data = loads_json_envelope(text)
    if data is None:
        return None
    if isinstance(data, list):
        if not data:
            return None
        inner = data[0]
        return inner if isinstance(inner, dict) else None
    return data if isinstance(data, dict) else None


def parse_usage(data: dict, duration_ms: int) -> Usage:
    """Extract a :class:`Usage` from a parsed JSON envelope.

    All numeric fields default to ``None`` (not 0) because pydantic
    distinguishes "unknown" from "zero" — different downstream consumers
    care about the difference.
    """
    raw_usage = data.get("usage") or {}
    return Usage(
        input_tokens=raw_usage.get("input_tokens"),
        output_tokens=raw_usage.get("output_tokens"),
        total_tokens=raw_usage.get("total_tokens"),
        duration_ms=duration_ms,
    )