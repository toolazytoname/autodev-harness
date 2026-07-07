"""Tests for harness.slop_check.

These verify the regex-based slop detector against known slop tells and
known-clean inputs. The validator is the *automatic* half of T08 step 5
verification; the visual reviewer (T09) is the *judgment* half.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.slop_check import (
    BUILTIN_RULES,
    SlopValidator,
    ValidationResult,
    load_rules,
)


# ---------------------------------------------------------------------------
# Known-clean baseline
# ---------------------------------------------------------------------------

CLEAN_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Editorial minimal — index</title>
<style>
:root {
  --paper: #f4f1ec;
  --ink: #1a1a1a;
  --accent: #b3401a;
  --font-display: "Söhne", "Inter", sans-serif;
  --font-body: "EB Garamond", Georgia, serif;
}
body {
  font-family: var(--font-body);
  color: var(--ink);
  background: var(--paper);
  line-height: 1.6;
}
.card {
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  padding: 24px 32px;
}
</style>
</head>
<body>
<h1>Index — A magazine for slow software</h1>
<p>Eleven articles, no autoplay, no infinite scroll.</p>
</body>
</html>
"""

SLOPPY_HTML = """\
<!DOCTYPE html>
<html>
<head>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet">
<script src="https://cdn.tailwindcss.com"></script>
<style>
body { font-family: 'Inter', sans-serif; }
.hero {
  background: linear-gradient(135deg, #7c3aed, #ec4899);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  padding: 48px;
}
.btn { @apply bg-purple-500 text-blue-600; }
</style>
</head>
<body>
<h1>Modern. Clean. Professional.</h1>
<p>Lorem ipsum dolor sit amet, consectetur adipiscing elit.</p>
<p class="placeholder">[Add description]</p>
<p>Coming soon — premium best-in-class solution.</p>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


class TestDetection:
    def test_clean_html_passes(self):
        v = SlopValidator()
        result = v.validate_text("clean.html", CLEAN_HTML)
        assert result.passed, f"Clean HTML should pass: {result.render()}"

    def test_sloppy_html_fails(self):
        v = SlopValidator()
        result = v.validate_text("sloppy.html", SLOPPY_HTML)
        assert not result.passed
        rule_ids = {violation.rule_id for violation in result.violations}
        # All the tells we put in there should fire:
        assert "font.inter" in rule_ids
        assert "tailwind.cdn" in rule_ids
        assert "gradient.purple_pink" in rule_ids
        assert "shadow.standard_card" in rule_ids
        assert "copy.modern_clean_professional" in rule_ids
        assert "placeholder.lorem" in rule_ids

    def test_severity_segregates_blockers_and_warnings(self):
        v = SlopValidator()
        result = v.validate_text("sloppy.html", SLOPPY_HTML)
        assert any(viol.severity == "blocker" for viol in result.violations)
        # standard-card shadow is severity=warn
        assert any(viol.rule_id == "shadow.standard_card" for viol in result.warnings)


# ---------------------------------------------------------------------------
# Rule loading (YAML extension path)
# ---------------------------------------------------------------------------


class TestRuleLoading:
    def test_default_fallback(self, tmp_path, monkeypatch):
        # Point SlopValidator at a non-existent path → must fall back to built-ins
        v = SlopValidator(rules=load_rules(tmp_path / "nope.yaml"))
        result = v.validate_text("x.html", SLOPPY_HTML)
        assert not result.passed

    def test_yaml_extension(self, tmp_path):
        rules_yaml = tmp_path / "rules.yaml"
        rules_yaml.write_text(
            "rules:\n"
            "  - id: custom.foo\n"
            "    severity: blocker\n"
            "    description: my custom rule\n"
            "    patterns:\n"
            "      - 'flutter'\n"
        )
        # Built-ins disabled by replacing with one rule
        v = SlopValidator(rules=load_rules(rules_yaml))
        result = v.validate_text("x.html", "I like flutter")
        ids = [viol.rule_id for viol in result.violations]
        assert ids == ["custom.foo"]


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestResultShape:
    def test_passed_true_for_clean(self):
        result = ValidationResult(target="x", violations=[])
        assert result.passed
        assert result.blockers == []
        assert result.warnings == []

    def test_blockers_only_when_severity_is_blocker(self):
        from harness.slop_check import SlopViolation

        result = ValidationResult(
            target="x",
            violations=[
                SlopViolation("a", "warn", "d", 1, "m"),
                SlopViolation("b", "blocker", "d", 2, "m"),
            ],
        )
        assert not result.passed
        assert len(result.blockers) == 1
        assert len(result.warnings) == 1

    def test_render_includes_target(self):
        result = ValidationResult(target="preview/foo.html", violations=[])
        assert "preview/foo.html" in result.render()


# ---------------------------------------------------------------------------
# Built-in rules sanity (no silent rule drift)
# ---------------------------------------------------------------------------


class TestBuiltinRulesShape:
    def test_every_rule_has_required_fields(self):
        for rule in BUILTIN_RULES:
            assert {"id", "severity", "description", "patterns"} <= rule.keys()
            assert rule["severity"] in {"blocker", "warn"}
            assert rule["patterns"], rule["id"]
            assert isinstance(rule["id"], str) and rule["id"]


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_argv_returns_zero_on_clean_input(capsys):
    """Direct invocation against a clean in-memory string isn't possible in
    the CLI (it reads files), but we can verify the validator itself end-to-end
    by writing to tmp and invoking main()."""
    import harness.slop_check as mod

    p = Path(mod.__file__).parent / "_test_clean.html"
    p.write_text(CLEAN_HTML)
    try:
        rc = mod.main([str(p)])
    finally:
        p.unlink()
    out = capsys.readouterr().out
    assert "no violations" in out
    assert rc == 0
