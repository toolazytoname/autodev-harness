"""RED tests for T19 — score_card docstring correctness.

The docstring of ``harness.score_card`` previously claimed:
    "On validation failure the harness retries the same model (max 2 times),
     then switches to the fallback model for that tier."

T19 fixes the code so the fallback path is actually wired in (instead of
never triggering), and aligns the docstring with the new behaviour so it
does not mis-describe the system.
"""

from __future__ import annotations

import inspect

from harness import score_card


def test_score_card_docstring_does_not_claim_unimplemented_fallback():
    """The module docstring should not promise a "switches to fallback model"
    behaviour unless the implementation actually does so."""
    doc = inspect.getdoc(score_card)
    assert doc is not None, "score_card module must have a docstring"
    lower = doc.lower()
    # Old lie: "switches to the fallback model for that tier"
    assert "switches to the fallback model for that tier" not in lower
    assert "switches to the fallback model" not in lower