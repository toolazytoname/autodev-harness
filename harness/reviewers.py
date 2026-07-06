"""Reviewer pool assembly — maps task kind to reviewer list.

Per MASTER-PLAN §2 and T05 spec.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pydantic
import yaml


class ReviewerSpec(pydantic.BaseModel):
    """A single reviewer with its configuration."""

    model_config = pydantic.ConfigDict(frozen=True)

    name: str
    prompt_path: Optional[Path] = None  # path to agents/reviewers/{name}.md

    def prompt_path_for(self, agents_dir: Path) -> Path:
        """Return the path to this reviewer's markdown prompt."""
        if self.prompt_path is not None:
            return self.prompt_path
        return agents_dir / f"{self.name}.md"


class ReviewerConfig(pydantic.BaseModel):
    """Top-level reviewer configuration."""

    model_config = pydantic.ConfigDict(frozen=True)

    default: list[str]
    reviewers: dict[str, list[str]] = pydantic.Field(default_factory=dict)
    overrides: dict[str, dict[str, list[str]]] = pydantic.Field(default_factory=dict)
    # T13: optional per-platform reviewer additions. The platform
    # dimension is layered ON TOP of the kind's reviewer set — see
    # :meth:`ReviewerAssembly.get_reviewer_names`.
    platform_reviewers: dict[str, list[str]] = pydantic.Field(default_factory=dict)


class ReviewerAssembly:
    """Resolves task kinds to a list of reviewer names."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        agents_dir: Optional[Path] = None,
    ) -> None:
        if config_path is None:
            harness_root = Path(__file__).parent.parent
            config_path = harness_root / "config" / "reviewers.yaml"
        if agents_dir is None:
            harness_root = Path(__file__).parent.parent
            agents_dir = harness_root / "agents" / "reviewers"

        self._config_path = Path(config_path)
        self._agents_dir = Path(agents_dir)
        self._config: ReviewerConfig = self._load_config()

    def _load_config(self) -> ReviewerConfig:
        with self._config_path.open() as fh:
            raw = yaml.safe_load(fh)
        return ReviewerConfig.model_validate(raw)

    def get_reviewer_names(
        self,
        task_kind: str,
        platform: Optional[str] = None,
    ) -> list[str]:
        """Return the ordered list of reviewer names for a task kind.

        If *platform* is given, the platform-specific reviewers are
        appended (de-duplicated, order-preserving).

        Falls back to ``default`` if the kind is not explicitly configured.
        """
        # Copy the list out of the config so platform additions don't
        # mutate the frozen config's reviewer list (a previous version
        # of this function did exactly that and tests caught it).
        reviewers = list(
            self._config.reviewers.get(task_kind, self._config.default)
        )
        # Check for per-kind overrides
        override = self._config.overrides.get(task_kind, {}).get("reviewers")
        if override is not None:
            reviewers = list(override)

        if platform:
            platform_additions = self._config.platform_reviewers.get(platform, [])
            # Order-preserving de-dupe
            seen = set(reviewers)
            for name in platform_additions:
                if name not in seen:
                    reviewers.append(name)
                    seen.add(name)
        return list(reviewers)

    def get_prompt_path(self, reviewer_name: str) -> Path:
        """Return the path to a reviewer's markdown prompt file."""
        return self._agents_dir / f"{reviewer_name}.md"

    def resolve_prompts(self, task_kind: str) -> list[tuple[str, Path]]:
        """Return (name, path) pairs for all reviewers of a task kind.

        Filters to only reviewers whose prompt files actually exist.
        """
        names = self.get_reviewer_names(task_kind)
        resolved = []
        for name in names:
            path = self.get_prompt_path(name)
            if path.exists():
                resolved.append((name, path))
            # Silently skip reviewers without prompt files (allows partial configs)
        return resolved

    @property
    def all_reviewer_names(self) -> set[str]:
        """Return every reviewer name that appears in any configured list."""
        names: set[str] = set()
        for reviewers in self._config.reviewers.values():
            names.update(reviewers)
        names.update(self._config.default)
        return names
