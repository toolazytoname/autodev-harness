"""HTML slop validator — fail-fast check on generated mockups.

Per TASKS.md T08 step 5: ship a small deterministic validator that
greps the generated HTML for the slop tells the three-piece baseline
calls out. This is the *automatic* half of "human spot-check"; the
visual reviewer (T09) is the *judgment* half.

Design choices:

- Pure stdlib (re + dataclass). No new dep.
- Rules live in a YAML next to the module so users can extend without
  editing Python. If the YAML is missing we fall back to a built-in
  rule set that is the union of what the three SKILL.md files call out.
- The validator returns a list of violations. Each violation has the
  rule id, severity, and the matched line (truncated). The caller
  decides what to do (warn, fail, score-card blocker).
- One file contains the public API
  (``SlopValidator``/``ValidationResult``) plus the CLI entry for
  ad-hoc usage (``python -m harness.slop_check path/to/index.html``).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Optional

import pydantic
import yaml

Severity = Literal["blocker", "warn"]


# ---------------------------------------------------------------------------
# Built-in rule set (used when no YAML is provided)
# ---------------------------------------------------------------------------

BUILTIN_RULES: list[dict] = [
    {
        "id": "font.inter",
        "severity": "blocker",
        "description": "Inter is the canonical AI-default sans. Use one of the baseline pairs.",
        "patterns": [r"family=['\"]?Inter[:,\s]", r"font-inter", r"--font-inter"],
    },
    {
        "id": "font.roboto",
        "severity": "blocker",
        "description": "Roboto looks like every Material app. Use a baseline pair.",
        "patterns": [r"family=['\"]?Roboto"],
    },
    {
        "id": "tailwind.cdn",
        "severity": "blocker",
        "description": "Tailwind CDN is a slop tell — its default theme overrides your typography and color.",
        "patterns": [r"cdn\.tailwindcss\.com"],
    },
    {
        "id": "gradient.purple_pink",
        "severity": "blocker",
        "description": "Purple→pink gradient is the AI-generic-hero cliché.",
        "patterns": [
            r"linear-gradient\([^)]*(?:7c3aed|8b5cf6|a855f7|d946ef|ec4899|f472b6)[^)]*",
            r"bg-gradient-to-[a-z]+\s+from-purple",
        ],
    },
    {
        "id": "shadow.standard_card",
        "severity": "warn",
        "description": "The 0 4px 12px rgba(0,0,0,.08) shadow is the default; use a baseline shadow token.",
        "patterns": [
            r"box-shadow:\s*0\s+4px\s+12px\s+rgba\(0,\s*0,\s*0,\s*0\.0?[58]\)",
        ],
    },
    {
        "id": "copy.modern_clean_professional",
        "severity": "warn",
        "description": "'Modern / clean / professional' filler prose — replace with concrete claims.",
        "patterns": [
            r"\bmodern\b.{0,30}\b(clean|professional|best-in-class)\b",
            r"\bclean\s+(and\s+)?modern\b",
            r"\bbest-in-class\b",
        ],
    },
    {
        "id": "placeholder.lorem",
        "severity": "blocker",
        "description": "Lorem ipsum / placeholder text is a failed call — replace with real copy.",
        "patterns": [
            r"\blorem ipsum\b",
            r"\bcoming soon\b",
            r"\[add description\]",
        ],
    },
    {
        "id": "tailwind.utility_primary_blue_purple",
        "severity": "warn",
        "description": "tailwind class containing indigo/blue/purple — re-check the palette per direction.",
        "patterns": [r"\bbg-(indigo|blue|purple|violet)-[0-9]+\b"],
    },
]


# ---------------------------------------------------------------------------
# Pydantic schema (T26)
# ---------------------------------------------------------------------------


class SlopRule(pydantic.BaseModel):
    """One slop rule.

    T26 — was previously a raw dict with string fields; severity was
    typo-tolerant (any value passed through to a regex that never
    matched), and ``patterns=[]`` produced a useless no-op rule that
    nobody noticed until it landed in CI. Validation now requires
    a known severity and at least one pattern.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    id: str
    severity: Severity
    description: str
    patterns: list[str] = pydantic.Field(min_length=1)


class SlopConfig(pydantic.BaseModel):
    """Top-level slop_rules.yaml schema."""

    model_config = pydantic.ConfigDict(frozen=True)

    rules: list[SlopRule] = pydantic.Field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlopViolation:
    """One rule violation found in one file."""

    rule_id: str
    severity: str  # blocker | warn
    description: str
    line: int
    match: str  # the offending snippet (truncated)


@dataclass(frozen=True)
class ValidationResult:
    """Aggregate result of validating one or more files."""

    target: str
    violations: list[SlopViolation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(v.severity == "blocker" for v in self.violations)

    @property
    def blockers(self) -> list[SlopViolation]:
        return [v for v in self.violations if v.severity == "blocker"]

    @property
    def warnings(self) -> list[SlopViolation]:
        return [v for v in self.violations if v.severity == "warn"]

    def render(self) -> str:
        lines = [f"Slop check on {self.target}"]
        if not self.violations:
            lines.append("  ✅ no violations")
            return "\n".join(lines)
        for v in self.violations:
            tag = "❌ BLOCK" if v.severity == "blocker" else "⚠️  WARN"
            lines.append(f"  {tag}  [{v.rule_id}] line {v.line}: {v.description}")
            lines.append(f"        match: {v.match}")
        lines.append(
            f"  overall: {'PASS' if self.passed else 'FAIL'} "
            f"({len(self.blockers)} blockers, {len(self.warnings)} warnings)"
        )
        return "\n".join(lines)


def load_rules(yaml_path: Optional[Path] = None) -> list[dict]:
    """Load rules from YAML or fall back to the built-in defaults.

    T26 — the YAML is parsed through :class:`SlopConfig` so bad
    severities, empty patterns, or missing required fields surface as a
    ``ValidationError`` at load time instead of as a silently misfiring
    rule at scan time.
    """
    if yaml_path is None or not Path(yaml_path).exists():
        return BUILTIN_RULES
    raw = yaml.safe_load(Path(yaml_path).read_text())
    if not isinstance(raw, dict) or "rules" not in raw:
        raise ValueError(
            f"slop rules YAML must be a mapping with a 'rules' key, got: {raw!r}"
        )
    cfg = SlopConfig.model_validate(raw)
    return [rule.model_dump() for rule in cfg.rules]


class SlopValidator:
    """Cheap, fast regex-based slop detector for HTML / CSS / spec text."""

    def __init__(self, rules: Optional[Iterable[dict]] = None) -> None:
        rules = rules if rules is not None else BUILTIN_RULES
        self._compiled = [
            (
                rule["id"],
                rule["severity"],
                rule["description"],
                [re.compile(p, re.IGNORECASE) for p in rule["patterns"]],
            )
            for rule in rules
        ]

    def validate_file(self, path: Path) -> ValidationResult:
        text = Path(path).read_text(errors="replace")
        violations = self._scan(str(path), text)
        return ValidationResult(target=str(path), violations=violations)

    def validate_text(self, target: str, text: str) -> ValidationResult:
        return ValidationResult(target=target, violations=self._scan(target, text))

    def _scan(self, target: str, text: str) -> list[SlopViolation]:
        out: list[SlopViolation] = []
        for rule_id, severity, description, patterns in self._compiled:
            for pattern in patterns:
                for lineno, line in enumerate(text.splitlines(), start=1):
                    match = pattern.search(line)
                    if not match:
                        continue
                    snippet = match.group(0)
                    if len(snippet) > 120:
                        snippet = snippet[:117] + "…"
                    out.append(
                        SlopViolation(
                            rule_id=rule_id,
                            severity=severity,
                            description=description,
                            line=lineno,
                            match=snippet,
                        )
                    )
        return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m harness.slop_check <file> [<file> ...]", file=sys.stderr)
        return 2
    validator = SlopValidator()
    any_fail = False
    for arg in argv:
        result = validator.validate_file(Path(arg))
        print(result.render())
        if not result.passed:
            any_fail = True
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
