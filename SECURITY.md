# Security Policy

## Supported Versions

| Branch    | Supported          |
| --------- | ------------------ |
| `main`    | :white_check_mark: |
| `develop` | :white_check_mark: |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security issues.**

Report privately via one of:

- **GitHub private vulnerability report**: [Repository → Security → Advisories → "Report a vulnerability"](https://github.com/toolazytoname/autodev-harness/security/advisories/new)
- **Email**: see the GitHub profile associated with this repository

Include in the report:

1. A clear description of the issue and its impact
2. Steps to reproduce, or a proof-of-concept
3. Affected versions / commits
4. Any known mitigations

We aim to acknowledge new reports within **72 hours** and ship a fix
or a documented mitigation within **30 days** for critical issues.

## Scope

In scope:

- Code execution / RCE in the harness runtime
- Secret leakage (API keys, tokens, credentials) committed to the repo
- Path traversal, injection, or unsafe deserialization in any
  pipeline / reviewer / adapter code
- Supply-chain risks in declared dependencies (`pyproject.toml`,
  `uv.lock`)
- Malicious or unexpected behavior in bundled skill content under
  `skills-bundle/` or `agents/`

Out of scope:

- Issues in third-party LLM providers (Anthropic, Linear, etc.) — please
  report upstream
- Issues that require physical access to a developer's machine

## Coordinated Disclosure

We follow **90-day responsible disclosure** for critical issues. If you
plan to disclose publicly, please give us a chance to fix and release
first.

## Historical Incidents

- 2026-07: 19 malicious GitHub Actions workflows were removed from
  `origin/main` (PRs titled `security: remove malicious workflow ci-XXXXX.yml`).
  Those commits were not present in the local history chain and are
  reflected in commit count only; current `.github/workflows/` is empty.
