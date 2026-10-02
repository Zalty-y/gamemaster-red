# Agent operating rules

Canonical rules: [`CONTRIBUTING.md`](CONTRIBUTING.md). This file is the
machine-shaped projection. The validator
(`scripts/check_conventions.py`) is executable truth — when in doubt, run it
against your message *before* committing.

## Vocabulary (exact strings)

```
TYPES  = feat fix perf refactor docs test build ci chore revert
SCOPES = service adapter-logtail adapter-bridge schema tools config docker deps ci docs
```

## Grammar

| artifact | pattern | example |
|---|---|---|
| issue title | `scope: imperative summary` | `adapter-logtail: survive log rotation without replay` |
| branch | `<type>/<issue#>-<kebab-slug≤50>` | `feat/42-survive-log-rotation` |
| commit / PR title | `type(scope): imperative summary` ≤72, lowercase, no period | `fix(adapter-logtail): resume tail after rotation` |
| issue link | commit body or PR body: `Closes #42` | — |
| breaking (pre-1.0) | `!` marker + `BREAKING CHANGE:` footer → minor bump | `feat(config)!: rename api_key_env to key_env` |

Squash-merge means the **PR title is the landed commit message** — CI checks
both, same regex.

## Recipes

```bash
# create the issue (label set exists; see .github/labels.yml)
gh issue create --title "adapter-logtail: survive log rotation without replay" \
  --label "area/adapter-logtail" --label "type/fix" --body-file task.md

# branch from current issue #42
git switch -c fix/42-survive-log-rotation

# validate before committing (exit 0 = safe to commit)
uv run --no-project scripts/check_conventions.py --mode commit \
  "fix(adapter-logtail): resume tail after rotation"

# open the PR whose title will become the commit
gh pr create --title "fix(adapter-logtail): resume tail after rotation" \
  --body "Closes #42 ... verification evidence ..."
```

## Invariants

- Never commit directly on `main` — server-side branch protection rejects
  the push (`enforce_admins`); every change enters via a green-PR squash merge.
- Never `--no-verify` to "fix" a hook error — fix the message; CI enforces
  identically, the bypass only delays the failure.
- Branch name violations **warn** (rename: `git branch -m ...`); commit
  messages **block**.
- Claim an issue before working on it: `gh issue edit <n> --add-label
  "agent:claimed"` so humans and other agents see it's taken.
- One issue → one PR → one squash commit. Split the issue if you need two.
- Version numbers and `CHANGELOG.md` are bot-owned: never edit
  `pyproject.toml` `version` or changelog by hand.

## Release model (what your commit causes)

`feat` → minor · `fix`/`perf` → patch · `!`/`BREAKING CHANGE:` pre-1.0 →
minor (documented in release notes) · everything else → no bump. Merging your
PR to `main` adds it to the open Release PR; whoever merges the Release PR cuts
the tag. Nothing else to do.
