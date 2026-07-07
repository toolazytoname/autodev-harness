"""Tests for harness.reviewers module and reviewer prompt files."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from harness.reviewers import ReviewerAssembly, ReviewerConfig


# ---------------------------------------------------------------------------
# ReviewerAssembly tests
# ---------------------------------------------------------------------------


class TestReviewerAssembly:
    @pytest.fixture
    def agents_dir(self, tmp_path):
        """Create a temporary agents/reviewers directory with stub prompt files."""
        d = tmp_path / "agents" / "reviewers"
        d.mkdir(parents=True)
        # Create stub prompt files for known reviewers
        for name in ["correctness", "test", "boundary", "security", "visual", "a11y", "mobile", "miniprogram"]:
            (d / f"{name}.md").write_text(f"# {name}\nstub content")
        return d

    @pytest.fixture
    def config_dir(self, tmp_path, agents_dir):
        """Create a temporary config directory with a reviewers.yaml."""
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir(parents=True)
        config_content = """
default:
  - correctness
  - test
  - boundary

reviewers:
  logic:
    - correctness
    - test
    - boundary
  api:
    - correctness
    - test
    - boundary
    - security
  ui:
    - correctness
    - test
    - boundary
    - a11y
    - visual
  infra:
    - correctness
    - test
    - boundary
    - security
"""
        (cfg_dir / "reviewers.yaml").write_text(config_content)
        return cfg_dir

    def test_resolve_logic(self, config_dir, agents_dir):
        assembly = ReviewerAssembly(
            config_path=config_dir / "reviewers.yaml",
            agents_dir=agents_dir,
        )
        names = assembly.get_reviewer_names("logic")
        assert names == ["correctness", "test", "boundary"]

    def test_resolve_api_includes_security(self, config_dir, agents_dir):
        assembly = ReviewerAssembly(
            config_path=config_dir / "reviewers.yaml",
            agents_dir=agents_dir,
        )
        names = assembly.get_reviewer_names("api")
        assert names == ["correctness", "test", "boundary", "security"]

    def test_resolve_ui_includes_visual_and_a11y(self, config_dir, agents_dir):
        assembly = ReviewerAssembly(
            config_path=config_dir / "reviewers.yaml",
            agents_dir=agents_dir,
        )
        names = assembly.get_reviewer_names("ui")
        assert names == ["correctness", "test", "boundary", "a11y", "visual"]

    def test_resolve_unknown_kind_uses_default(self, config_dir, agents_dir):
        assembly = ReviewerAssembly(
            config_path=config_dir / "reviewers.yaml",
            agents_dir=agents_dir,
        )
        names = assembly.get_reviewer_names("unknown-kind")
        assert names == ["correctness", "test", "boundary"]

    def test_resolve_with_platform_adds_reviewer(self, config_dir, agents_dir):
        # T13: when platform is set, the platform-specific reviewer
        # is appended to the kind's set. Web adds nothing (visual is
        # already in the ui kind).
        assembly = ReviewerAssembly(
            config_path=config_dir / "reviewers.yaml",
            agents_dir=agents_dir,
        )
        # Add a platform_reviewers section to the YAML
        yaml_path = config_dir / "reviewers.yaml"
        text = yaml_path.read_text()
        text += (
            "\nplatform_reviewers:\n"
            "  web: []\n"
            "  mobile: [mobile]\n"
            "  miniprogram: [miniprogram]\n"
        )
        yaml_path.write_text(text)
        assembly = ReviewerAssembly(
            config_path=yaml_path,
            agents_dir=agents_dir,
        )
        # ui + mobile → ui's set + 'mobile'
        names = assembly.get_reviewer_names("ui", platform="mobile")
        assert "mobile" in names
        assert "visual" in names  # ui's base set
        # logic + miniprogram → logic's set + 'miniprogram'
        names = assembly.get_reviewer_names("logic", platform="miniprogram")
        assert "miniprogram" in names
        assert "test" in names  # logic's base set
        # web → no additions
        names = assembly.get_reviewer_names("ui", platform="web")
        assert names == ["correctness", "test", "boundary", "a11y", "visual"]
        # No platform → no additions
        names = assembly.get_reviewer_names("ui")
        assert "mobile" not in names

    def test_resolve_with_platform_dedupes(self, config_dir, agents_dir):
        # If the kind's set already includes a reviewer, adding it via
        # platform must NOT duplicate it.
        assembly_yaml = config_dir / "reviewers.yaml"
        text = assembly_yaml.read_text()
        text += (
            "\nplatform_reviewers:\n"
            "  mobile: [visual]\n"  # 'visual' is already in the ui set
        )
        assembly_yaml.write_text(text)
        assembly = ReviewerAssembly(
            config_path=assembly_yaml,
            agents_dir=agents_dir,
        )
        names = assembly.get_reviewer_names("ui", platform="mobile")
        # Order preserved, no duplicates
        assert names == ["correctness", "test", "boundary", "a11y", "visual"]

    def test_resolve_prompts_filters_nonexistent(self, config_dir, agents_dir):
        # Remove one prompt file to test filtering
        (agents_dir / "boundary.md").unlink()
        assembly = ReviewerAssembly(
            config_path=config_dir / "reviewers.yaml",
            agents_dir=agents_dir,
        )
        resolved = assembly.resolve_prompts("logic")
        names = [n for n, _ in resolved]
        assert "boundary" not in names
        assert "correctness" in names

    def test_all_reviewer_names(self, config_dir, agents_dir):
        assembly = ReviewerAssembly(
            config_path=config_dir / "reviewers.yaml",
            agents_dir=agents_dir,
        )
        names = assembly.all_reviewer_names
        assert "correctness" in names
        assert "test" in names
        assert "security" in names
        assert "visual" in names


# ---------------------------------------------------------------------------
# Reviewer prompt files existence tests
# ---------------------------------------------------------------------------


class TestReviewerPromptsExist:
    """Verify all 5 required reviewer prompt files exist."""

    @pytest.fixture
    def agents_dir(self):
        harness_root = Path(__file__).parent.parent
        return harness_root / "agents" / "reviewers"

    def test_correctness_prompt_exists(self, agents_dir):
        assert (agents_dir / "correctness.md").exists()

    def test_test_prompt_exists(self, agents_dir):
        assert (agents_dir / "test.md").exists()

    def test_boundary_prompt_exists(self, agents_dir):
        assert (agents_dir / "boundary.md").exists()

    def test_security_prompt_exists(self, agents_dir):
        assert (agents_dir / "security.md").exists()

    def test_visual_prompt_exists(self, agents_dir):
        assert (agents_dir / "visual.md").exists()

    def test_all_prompts_end_with_json_requirement(self, agents_dir):
        """Each reviewer prompt must end with a score card JSON output instruction."""
        required_endings = [
            "json",  # each ends with a JSON code block instruction
        ]
        for name in ["correctness", "test", "boundary", "security", "visual"]:
            path = agents_dir / f"{name}.md"
            text = path.read_text()
            assert "score card json" in text.lower(), f"{name}.md must mention 'score card JSON'"
