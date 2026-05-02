# GitHub Actions Workflows

## Status Badges

Add these badges to your project README:

```markdown
[![CI](https://github.com/USER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/USER/REPO/actions/workflows/ci.yml)
[![AutoDev](https://github.com/USER/REPO/actions/workflows/autodev.yml/badge.svg)](https://github.com/USER/REPO/actions/workflows/autodev.yml)
[![Deploy](https://github.com/USER/REPO/actions/workflows/deploy.yml/badge.svg)](https://github.com/USER/REPO/actions/workflows/deploy.yml)
```

## Workflows

### 1. ci.yml - Quality Gates
- Runs on: Push to main/develop, PR
- Checks: Lint, Type check, Build, Test, E2E

### 2. pr-review.yml - PR Review
- Runs on: PR open/sync
- AI Code Review + Security Scan
- Auto approve if all checks pass

### 3. gan-evaluation.yml - GAN Quality
- Runs on: Manual trigger
- Full GAN loop evaluation
- Auto commit if configured

### 4. autodev.yml - AutoDevHarness CI
- Runs on: Push, Daily, Manual
- Full AutoDevHarness execution
- Generates build report

### 5. deploy.yml - Deploy
- Runs on: Push to main, Manual
- Environment: Preview / Staging / Production
- Requires GAN pass for production

### 6. notifications.yml - Notifications
- Runs on: All workflow completion
- Slack / DingTalk notifications

## Setup Guide

See [ENVIRONMENT_SETUP.md](./ENVIRONMENT_SETUP.md) for detailed setup instructions.
