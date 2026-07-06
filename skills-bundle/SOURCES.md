# skills-bundle — Taste bundle for AutoDevHarness v2 UI design

This directory holds a self-contained copy of the skill prompts that the
ui-design agent (and the visual reviewer) inject into the inner loop. It
exists so the harness does not depend on a particular user's
`~/.claude/skills/` install state — anything referenced in
`agents/ui-design.md` is shipped in the repo.

Per MASTER-PLAN §3 P1: every UI task gets the **three-piece baseline**
(fixed injection) plus a **style module** (conditionally loaded per brief).

---

## What is in here

### Three-piece baseline (always injected)

| Install name | Path | Source |
|---|---|---|
| `design-taste-frontend` | `3-piece/design-taste-frontend/SKILL.md` | taste-skill v2 (Leonxlnx) |
| `high-end-visual-design` | `3-piece/high-end-visual-design/SKILL.md` | taste-skill soft-skill (Leonxlnx) |
| `frontend-design` | `3-piece/frontend-design/SKILL.md` | Anthropic official |

These three define the *anti-slop* baseline — typography, layout,
motion, contrast rules that block every "AI-looking template" failure
mode we have observed.

### Style modules (per brief, at most one)

| Install name | Path | Direction |
|---|---|---|
| `minimalist-ui` | `styles/minimalist-ui/SKILL.md` | Editorial / Linear-class product UI |
| `industrial-brutalist-ui` | `styles/industrial-brutalist-ui/SKILL.md` | Swiss-grid / military-terminal / data-heavy |
| `gpt-taste` | `styles/gpt-taste/SKILL.md` | Strong GSAP motion / wide editorial typography |

The four aesthetic directions covered by the harness (see
`agents/ui-design.md`) are:

1. **Editorial minimal** — minimalist-ui skill
2. **High-end motion** — gpt-taste skill
3. **Data-dense industrial** — industrial-brutalist-ui skill
4. **Premium default** — three-piece only (no style module)

The fourth is *deliberate*: it shows what the baseline can do without
any style module — so we can tell the modules are adding signal, not
noise.

---

## Provenance

| File | Upstream | License | First imported |
|---|---|---|---|
| design-taste-frontend/SKILL.md | https://github.com/Leonxlnx/taste-skill — `skills/taste-skill/` (v2) | MIT (Leonxlnx 2026) | 2026-07-06 |
| high-end-visual-design/SKILL.md | https://github.com/Leonxlnx/taste-skill — `skills/soft-skill/` | MIT (Leonxlnx 2026) | 2026-07-06 |
| frontend-design/SKILL.md | Anthropic official (Claude Code marketplace) | See LICENSE.txt | 2026-07-06 |
| minimalist-ui/SKILL.md | https://github.com/Leonxlnx/taste-skill — `skills/minimalist-skill/` | MIT (Leonxlnx 2026) | 2026-07-06 |
| industrial-brutalist-ui/SKILL.md | https://github.com/Leonxlnx/taste-skill — `skills/brutalist-skill/` | MIT (Leonxlnx 2026) | 2026-07-06 |
| gpt-taste/SKILL.md | https://github.com/Leonxlnx/taste-skill — `skills/gpt-tasteskill/` | MIT (Leonxlnx 2026) | 2026-07-06 |

To update a skill in this bundle, re-run the import command documented
in `docs/TASKS.md` T08 step 2 (do **not** edit SKILL.md in place — keep
the upstream provenance intact).

---

## What is *deliberately* not in here

- `image-to-code` — pipeline takes a brief, not a reference image. Different feature.
- `redesign-existing-projects` — applies to projects that already have a UI; TASKS.md T08 is greenfield.
- `stitch-design-taste` — Google Stitch lock-in; we have no Google target.
- `full-output-enforcement` — orthogonal concern; belongs in the generator prompt if at all.
- `imagegen-frontend-web`/`mobile`/`brandkit` — reference-image generation; ui-design writes HTML, not images.
- v1 of `design-taste-frontend` — kept only as `design-taste-frontend-v1` in the parent repo for users who pin there. We take v2.

If a future task needs any of these, add a dedicated sub-task to
`docs/TASKS.md` rather than bloating this bundle — the bundle is meant
to be a fixed reference, not a kitchen sink.
