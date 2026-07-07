"""Tests for skills-bundle/opendesign/.

Per MASTER-PLAN §3 P1 + TASKS T08b: this bundle ships a self-contained,
attributed subset of skills imported from nexu-io/open-design. The
acceptance criteria from TASKS.md T08b are:

1. skills-bundle/opendesign/ lands ≥ 4 SKILL.md files, each with LICENSE
   + SOURCES.md attribution.
2. agents/ui-design.md adds the opendesign subset to the STYLE MODULE
   candidate list.
3. agents/researcher.md wires competitive-ads-extractor + ad-creative.
4. Full test suite still ≥ 158 passed (currently 287+).

These tests pin the bundle shape so accidental drift fails fast.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE = REPO_ROOT / "skills-bundle" / "opendesign"
UI_DESIGN = REPO_ROOT / "agents" / "ui-design.md"
RESEARCHER = REPO_ROOT / "agents" / "researcher.md"

# The seven target skills imported from opendesign (T08b verification).
EXPECTED_SKILLS = {
    "reference-design-contract",
    "design-brief",
    "emil-design-eng",
    "emilkowalski-motion",
    "impeccable-design-polish",
    "competitive-ads-extractor",
    "ad-creative",
}

# T08b's three "follow-up style modules" wired into ui-design.md §E0.
UI_FOLLOWUP_MODULES = {
    "reference-design-contract": "reference-design-contract/",
    "emilkowalski-motion": "emilkowalski-motion/",
    "impeccable-design-polish": "impeccable-design-polish/",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_frontmatter(path: Path) -> dict[str, str]:
    """Parse a tiny subset of YAML frontmatter (name / description /
    triggers) without dragging in PyYAML. The opendesign SKILL.md files
    use `key: value` and `key: |\n  ...` blocks; we only need the
    flat scalars here.
    """
    text = path.read_text()
    if not text.startswith("---"):
        raise AssertionError(f"{path}: missing frontmatter opening '---'")

    end = text.find("\n---", 3)
    if end == -1:
        raise AssertionError(f"{path}: missing frontmatter closing '---'")

    block = text[3:end].strip()
    out: dict[str, str] = {}
    current_key: str | None = None
    for line in block.splitlines():
        if not line.strip():
            continue
        # New key
        if re.match(r"^[A-Za-z_][A-Za-z0-9_-]*\s*:", line):
            key, _, value = line.partition(":")
            current_key = key.strip()
            value = value.strip()
            if value == "|":
                # Multi-line literal block; we capture the next non-empty line.
                continue
            out[current_key] = value.strip('"').strip("'")
        elif current_key and line.startswith(("  ", "\t")):
            # Continuation of the previous `|` block. We append the first
            # non-empty line as the description preview.
            content = line.strip()
            if current_key not in out and content:
                out[current_key] = content
            elif current_key in out:
                out[current_key] = (out[current_key] + " " + content).strip()
    return out


# ---------------------------------------------------------------------------
# Bundle shape
# ---------------------------------------------------------------------------


class TestBundleShape:
    def test_bundle_directory_exists(self):
        assert BUNDLE.is_dir(), f"missing bundle dir: {BUNDLE}"

    def test_top_level_license_present(self):
        license_path = BUNDLE / "LICENSE"
        assert license_path.is_file(), "top-level LICENSE missing"
        # Apache-2.0 from opendesign — must mention Apache
        head = license_path.read_text()[:200].lower()
        assert "apache" in head

    def test_sources_md_present_and_mentions_every_skill(self):
        sources = BUNDLE / "SOURCES.md"
        assert sources.is_file()
        text = sources.read_text()
        for skill in EXPECTED_SKILLS:
            assert skill in text, f"SOURCES.md does not mention {skill}"

    def test_at_least_four_skill_md_files(self):
        skill_mds = list(BUNDLE.glob("*/SKILL.md"))
        assert len(skill_mds) >= 4, (
            f"T08b requires ≥ 4 SKILL.md, found {len(skill_mds)}"
        )
        names = {p.parent.name for p in skill_mds}
        assert names >= EXPECTED_SKILLS, (
            f"missing skills: {EXPECTED_SKILLS - names}"
        )


# ---------------------------------------------------------------------------
# Per-skill frontmatter sanity
# ---------------------------------------------------------------------------


class TestSkillFrontmatter:
    @pytest.mark.parametrize("skill_name", sorted(EXPECTED_SKILLS))
    def test_skill_md_has_frontmatter(self, skill_name):
        path = BUNDLE / skill_name / "SKILL.md"
        assert path.is_file(), f"missing {skill_name}/SKILL.md"
        fm = _read_frontmatter(path)
        assert "name" in fm, f"{skill_name}: frontmatter missing `name`"
        assert "description" in fm, (
            f"{skill_name}: frontmatter missing `description`"
        )
        assert fm["name"] == skill_name, (
            f"{skill_name}: frontmatter name is {fm.get('name')!r}"
        )

    @pytest.mark.parametrize("skill_name", sorted(EXPECTED_SKILLS))
    def test_skill_md_has_body(self, skill_name):
        path = BUNDLE / skill_name / "SKILL.md"
        text = path.read_text()
        # The frontmatter ends at the second `---`; everything after is body.
        body = text.split("\n---", 2)[-1].strip()
        assert len(body) >= 200, (
            f"{skill_name}: body too short ({len(body)} chars)"
        )


# ---------------------------------------------------------------------------
# Per-skill attribution
# ---------------------------------------------------------------------------


class TestSkillAttribution:
    def test_emil_design_eng_has_sub_upstream_license(self):
        # emil-design-eng imports from emilkowalski/skills under MIT.
        # We carry the MIT LICENSE into the subdir so attribution travels
        # with the file.
        license_path = BUNDLE / "emil-design-eng" / "LICENSE"
        assert license_path.is_file(), (
            "emil-design-eng/LICENSE missing — sub-upstream MIT not preserved"
        )
        head = license_path.read_text()[:200].lower()
        assert "mit license" in head

    def test_reference_design_contract_keeps_example_html(self):
        # The skill's preview is example.html — must travel with the bundle
        # so the pipeline can render the preview locally.
        path = BUNDLE / "reference-design-contract" / "example.html"
        assert path.is_file(), "reference-design-contract/example.html missing"
        assert path.read_text().strip(), "example.html is empty"


# ---------------------------------------------------------------------------
# ui-design.md wiring
# ---------------------------------------------------------------------------


class TestUIDesignWiring:
    def test_ui_design_md_mentions_opendesign(self):
        text = UI_DESIGN.read_text()
        assert "opendesign" in text.lower(), (
            "ui-design.md does not reference opendesign bundle"
        )

    @pytest.mark.parametrize("needle", UI_FOLLOWUP_MODULES.values())
    def test_ui_design_lists_followup_module(self, needle):
        text = UI_DESIGN.read_text()
        assert needle in text, (
            f"ui-design.md does not mention follow-up module path {needle}"
        )

    def test_ui_design_section_e0_present(self):
        text = UI_DESIGN.read_text()
        assert re.search(r"^##\s+E0\.", text, re.MULTILINE), (
            "ui-design.md missing §E0 'Follow-up style modules' section"
        )


# ---------------------------------------------------------------------------
# researcher.md wiring
# ---------------------------------------------------------------------------


class TestResearcherWiring:
    def test_researcher_md_mentions_opendesign(self):
        text = RESEARCHER.read_text()
        assert "opendesign" in text.lower(), (
            "researcher.md does not reference opendesign bundle"
        )

    def test_researcher_md_wires_competitive_ads_extractor(self):
        text = RESEARCHER.read_text()
        assert "competitive-ads-extractor" in text

    def test_researcher_md_wires_ad_creative(self):
        text = RESEARCHER.read_text()
        assert "ad-creative" in text

    def test_researcher_keyword_trigger_table_present(self):
        text = RESEARCHER.read_text()
        # The keyword trigger table introduced by T08b must exist.
        assert "命中词集合" in text or "命中词" in text, (
            "researcher.md missing keyword trigger table for opendesign skills"
        )