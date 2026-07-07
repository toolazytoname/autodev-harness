# skills-bundle/opendesign — Open Design subset for AutoDevHarness v2

This directory holds a self-contained copy of a small subset of skills from
the [nexu-io/open-design](https://github.com/nexu-io/open-design) monorepo
(700+ skills). The opendesign repo is huge and has heavy overlap with the
three-piece baseline we already ship in `skills-bundle/3-piece/`, so we only
import the skills that fill gaps the baseline cannot cover:

1. **Reference → spec**: turning screenshots/URLs/notes into a grounded
   `DESIGN.md` (and feeding it into ui-design).
2. **Structured brief**: parsing an I-Lang protocol brief instead of free-form
   prose.
3. **Advanced motion & polish**: Emil Kowalski / Impeccable follow-ups for
   cases where the three-piece baseline is not enough.
4. **Marketing creative**: competitor ad teardown + ad-copy iteration, used
   by the researcher phase on landing-page / paid-acquisition projects.

The bundle is read-only provenance: each `SKILL.md` is imported verbatim
from upstream; we do not edit it. To refresh, re-run the import command
documented at the bottom of this file.

---

## Layout

```
skills-bundle/opendesign/
├── LICENSE                          (Apache-2.0, opendesign top-level)
├── SOURCES.md                       (this file)
├── reference-design-contract/       (1)
│   ├── SKILL.md
│   ├── example.html
│   └── references/checklist.md
├── design-brief/                    (2)
│   └── SKILL.md
├── emil-design-eng/                 (3)
│   ├── SKILL.md
│   └── LICENSE                      (MIT, Matt Pocock — sub-upstream)
├── emilkowalski-motion/             (3)
│   └── SKILL.md
├── impeccable-design-polish/        (3)
│   └── SKILL.md
├── competitive-ads-extractor/       (4)
│   └── SKILL.md
└── ad-creative/                     (4)
    └── SKILL.md
```

Categories match the four gaps above; numbers in parentheses are the
category index.

---

## Provenance

| Skill | Path | Upstream (opendesign) | Sub-upstream / original | License | First imported |
|---|---|---|---|---|---|
| reference-design-contract | `reference-design-contract/SKILL.md` | `skills/reference-design-contract/` | nexu-io/open-design | Apache-2.0 | 2026-07-06 |
| design-brief | `design-brief/SKILL.md` | `skills/design-brief/` | nexu-io/open-design (I-Lang protocol) | Apache-2.0 | 2026-07-06 |
| emil-design-eng | `emil-design-eng/SKILL.md` | `skills/emil-design-eng/` | github.com/emilkowalski/skills | MIT (Matt Pocock) — see `LICENSE` | 2026-07-06 |
| emilkowalski-motion | `emilkowalski-motion/SKILL.md` | `skills/emilkowalski-motion/` | emilkowal.ski/skill | Apache-2.0 | 2026-07-06 |
| impeccable-design-polish | `impeccable-design-polish/SKILL.md` | `skills/impeccable-design-polish/` | github.com/pbakaus/impeccable | Apache-2.0 | 2026-07-06 |
| competitive-ads-extractor | `competitive-ads-extractor/SKILL.md` | `skills/competitive-ads-extractor/` | github.com/ComposioHQ/awesome-claude-skills | Apache-2.0 | 2026-07-06 |
| ad-creative | `ad-creative/SKILL.md` | `skills/ad-creative/` | github.com/coreyhaines31/marketingskills | Apache-2.0 | 2026-07-06 |

Top-level `LICENSE` is the Apache-2.0 from nexu-io/open-design. The MIT
LICENSE inside `emil-design-eng/` is the original sub-upstream's license
(Matt Pocock, 2026) and applies to that subdir only.

To re-verify any of the upstream URLs above, see
`docs/TASKS.md` T08b verification checklist.

---

## What is *deliberately* not in here

opendesign has 161 skills; we imported 7. The 154 we skipped fall into
four groups, each with a reason:

1. **Heavy overlap with the three-piece baseline** (e.g. `color-expert`,
   `typography-*`, `brand-extract`, `design-md`, `design-review`,
   `design-consultation`, `canvas-design`, `article-magazine`,
   `data-report`, `d3-visualization`, `deck-*` etc.). ui-design already
   gets the baseline via `agents/ui-design.md`, so re-importing them adds
   prompt bloat without new signal.
2. **Different surface** (e.g. `fal-*`, `ai-music-album`, `remotion`,
   `card-twitter`, `card-xiaohongshu`). These are media/format-specific;
   the harness writes HTML/CSS, not videos or social cards.
3. **Brand-locked** (e.g. `apple-hig`, `brandkit`,
   `brutalist-skill`-upstream). Brand choices live in the brief, not the
   prompt baseline.
4. **Workflow skills** (e.g. `brainstorming`, `agent-browser`,
   `artifacts-builder`, `domain-name-brainstormer`, `export-download-debugging`).
   These belong in `agents/*.md` if at all, not in `skills-bundle/`.

If a future task needs any of these, add a dedicated sub-task to
`docs/TASKS.md` rather than bloating this bundle — the bundle is meant
to be a fixed reference, not a kitchen sink.

---

## Refresh command

```sh
export https_proxy=http://127.0.0.1:7890 \
       http_proxy=http://127.0.0.1:7890 \
       all_proxy=socks5://127.0.0.1:7890

BASE=https://raw.githubusercontent.com/nexu-io/open-design/main
DEST=skills-bundle/opendesign
for s in reference-design-contract design-brief emil-design-eng \
         emilkowalski-motion impeccable-design-polish \
         competitive-ads-extractor ad-creative; do
  curl -fsSL --max-time 30 "$BASE/skills/$s/SKILL.md" -o "$DEST/$s/SKILL.md"
done
# Auxiliary files
curl -fsSL --max-time 30 "$BASE/skills/emil-design-eng/LICENSE" \
  -o "$DEST/emil-design-eng/LICENSE"
curl -fsSL --max-time 30 "$BASE/skills/reference-design-contract/example.html" \
  -o "$DEST/reference-design-contract/example.html"
curl -fsSL --max-time 30 \
  "$BASE/skills/reference-design-contract/references/checklist.md" \
  -o "$DEST/reference-design-contract/references/checklist.md"
```

After running, sanity-check:

```sh
git diff --stat skills-bundle/opendesign
pytest tests/test_opendesign_bundle.py -v
```