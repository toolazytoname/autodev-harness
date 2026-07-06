# Cross-Platform Testing (T13 / MASTER-PLAN §3 P5)

The harness supports three target platforms: **web**, **mobile**, and
**miniprogram**. Each platform has a different test stack because
"tested" means different things on each surface.

## TL;DR

| Platform    | Runner               | Where it runs   | Test file location                    |
|-------------|----------------------|-----------------|---------------------------------------|
| web         | Playwright / browser-use | Linux CI ok | `tests/e2e/...` + visual reviewer    |
| mobile      | Maestro              | Mac/Linux + emulator | `tests/maestro/<task-id>.yaml`  |
| miniprogram | miniprogram-automator | macOS / Windows only | `tests/automator/<task-id>.spec.js` |

The `platform` field on a task (in `003-task-queue.json`) tells the
inner loop which cross-platform reviewer to add. The kind (`ui`,
`api`, `logic`, `infra`) still drives the base reviewer set — the
platform is a layer on top.

## Web (default)

- The `ui` kind already includes the `visual` reviewer
  (Playwright screenshot + multimodal score card — see T09).
- For logic / api / infra, no platform reviewer is added.
- Linux CI is the happy path.

## Mobile (Maestro)

- Generator must produce a YAML flow under `tests/maestro/<task-id>.yaml`.
- See [`templates/maestro-flow-template.yaml`](../templates/maestro-flow-template.yaml)
  for the starter template.
- The `mobile` reviewer checks: flow exists, lints clean, all
  acceptance steps are covered, and (when an emulator is up)
  runs `maestro test` end-to-end.

### Local emulator setup

| OS       | Emulator              | Notes |
|----------|-----------------------|-------|
| macOS    | iOS Simulator (Xcode) / Android Studio AVD | `xcrun simctl boot` for iOS; `emulator -avd <name>` for Android |
| Linux    | Android Studio AVD    | iOS is not available on Linux — skip iOS-only flows |
| Windows  | Android Studio AVD    | iOS requires a Mac |

If no emulator is available the reviewer runs `maestro lint` and
notes "runtime check skipped due to no emulator" in `evidence`.
The score is still allowed to be ≥ 0.8 in that case.

## Miniprogram (miniprogram-automator)

- This is the trickiest platform because the official tool
  (`miniprogram-automator`) **only runs on macOS and Windows**
  (it needs the WeChat DevTools IDE).
- Generator must:
  1. Keep all business logic in `miniprogram/utils/` (or `src/`) as
     **pure functions** that don't import `wx.*`.
  2. Keep `miniprogram/pages/*.js` as thin shells.
  3. Produce an automator spec under `tests/automator/<task-id>.spec.js`.
  4. See [`templates/miniprogram-automator-template.js`](../templates/miniprogram-automator-template.js)
     for the starter template.

### macOS setup (the only working path)

```bash
# 1. Install WeChat DevTools
brew install --cask wechatwebdevtools

# 2. Open the IDE, open your miniprogram project, then go to
#    Settings → Security → Service Port → Enable
#    (note the port; default is 9420)

# 3. Install the automator
npm install --save-dev miniprogram-automator

# 4. Run the test
node tests/automator/<task-id>.spec.js
```

### Linux CI strategy (no official tool)

Don't try to Wine the WeChat DevTools — it doesn't work. Two options:

1. **Compile the pages to H5** with the WeChat-provided tool
   (mini-program → web) and run Playwright on the compiled output.
   Useful for layout regression; misses all `wx.*` runtime behaviour.
2. **Pure-function tests only.** Since the generator is constrained
   to put logic in `miniprogram/utils/`, you can import those files
   from a plain Node test (no DevTools needed). The automator
   spec's `describe('pure functions', ...)` block does exactly this.
   Set `MINIPROGRAM_SKIP_RUNTIME=1` to skip the IDE-required parts.

The harness's miniprogram reviewer treats Linux CI with
`MINIPROGRAM_SKIP_RUNTIME=1` as "lint + pure-function coverage" —
the score is still allowed to be ≥ 0.8.

## When a platform value is missing / wrong

- Empty / `null` / unknown → defaults to `web` (no extra reviewer).
- This is the safest fallback: web is the only platform that has
  a CI-equivalent test path on every host.

## Adding a new platform

1. Add the value to `harness.artifacts.Platform` enum.
2. Add the platform-specific reviewers in `config/reviewers.yaml`
   under `platform_reviewers`.
3. Add a reviewer prompt under `agents/reviewers/<name>.md`.
4. Add a starter template under `templates/`.
5. Update this doc.
