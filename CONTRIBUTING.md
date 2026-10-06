# Contributing to gamemaster-red

The convention system in one line: **one number, one scope, one grammar** —
issue, branch, PR title, squash commit, and changelog line all carry the same
`type(scope)` and issue number, so anyone (human or agent) can reconstruct the
flow from any single artifact.

Enforcement is the same script in three places: lefthook hooks (local,
hard-block commits), GitHub CI (cannot be bypassed), and this document.

---

## 1. The flow

```
issue #42 ──▶ branch feat/42-log-tail-rotation ──▶ PR #43 (title = commit msg)
    │                                                    │ squash-merge
    └──────────────── Closes #42 ◀── main: feat(adapter-logtail): survive log rotation
                                              │
                              release-please: Release PR ── merge ──▶ tag v0.4.0
                                                                      + CHANGELOG.md
```

1. **Issue first** for anything bigger than a typo. Title grammar:
   `scope: imperative summary` — e.g. `adapter-logtail: tail must survive log
   rotation without replaying backlog`. Label it: one `type/*` + the `area/*`.
2. **Branch from `main`**, named `<type>/<issue-number>-<slug>`:
   `feat/42-log-tail-rotation`. Slug: kebab-case ASCII, ≤ 50 chars, derived
   from the issue title. Bad branch names warn; rename with
   `git branch -m <type>/<issue>-<slug>`.
3. **Commit freely on the branch** — hooks check every message anyway, so
   history stays readable even before the squash.
4. **PR title = the message that lands on main** (squash-merge only). The
   body's `Closes #42` wires the issue; the template's Release impact box
   states the version consequence.
5. **Merge to `main` updates the release-please Release PR.** Merging *that*
   (or merging several at once — it batches) cuts `vX.Y.Z`, writes
   `CHANGELOG.md`, bumps `pyproject.toml`, and publishes (once the publish
   job is real). No release day, no hand-edited changelog.

Long-lived branch names exempt from the grammar: `main`, `release/…`.

**`main` is protected** (GitHub branch protection, admins included): changes
arrive only through a PR whose `check` job is green and whose commits
pass the grammar, merged by **squash only** (merge commits and rebase-merge
are disabled repo-wide). Force-push and deletion are off — history on `main`
is append-only, which is what release-please and the `@0.3` pin channel rely
on. If you're mid-work and `main` moved, `git merge main` into your branch
(`strict` checks require the PR to sit on current `main` anyway).

## 2. Commit grammar

```
type(scope): imperative summary            ≤ 72 chars, lowercase start, no period

Why it was needed, what was traded off. Wrap ~100.

Closes #42
BREAKING CHANGE: config.toml [model].api_key_env renamed to key_env
```

**Types** (left = bump it causes via release-please):

| type | meaning | bump |
|---|---|---|
| `feat` | new user-visible capability | minor |
| `fix` | wrong behavior corrected | patch |
| `perf` | performance | patch |
| `refactor` `docs` `test` `build` `ci` `chore` `revert` | no user-visible change | none |

Breaking change pre-1.0: `type(scope)!: …` + `BREAKING CHANGE:` footer →
**minor bump** (project policy: `0.x` minors are the breaking boundary;
`1.0.0` = envelope frozen + API stable). Mark breaking honestly — the release
notes are where operators learn to read the diff.

**Scopes are a closed vocabulary** (unknown scope = rejected, in `main`):

| scope | covers |
|---|---|
| `service` | core pipeline, sessions, memory, triggers |
| `adapter-logtail` | log tail + RCON adapter (docs/ARCHITECTURE.md §4) |
| `adapter-bridge` | Paper bridge plugin, `plugin-paper/` (§5) |
| `schema` | envelope contract, `schema/` (§3) |
| `tools` | wiki, crafting KB, MCP, tool API |
| `config` | init / setup / doctor / wizard, config writers |
| `docker` | Dockerfile, compose files |
| `deps` | `uv.lock`, `.python-version` |
| `ci` | workflows, hooks, release automation |
| `docs` | README, docs/ARCHITECTURE.md, docs/MVP.md, this file |

Scope may be omitted (`chore: typo in README`); the slash-set may not be
invented. The same strings are the `area/*` issue labels and the changelog
grouping — change the vocabulary only deliberately, in one commit that touches
`CONTRIBUTING.md`, `AGENTS.md`, `.github/labels.yml`, and
`scripts/check_conventions.py` together.

## 3. Versioning

- SemVer, single train for the repo: one tag ⇒ PyPI `X.Y.Z`, ghcr `:X.Y` +
  `:X.Y.Z`, and `gamemaster-red-bridge-X.Y.Z.jar`.
- Pre-1.0: breaking user-facing changes bump the **minor**; `@0.3`-style pins
  (README/§12.3) stay honest because a minor is the only way to get a breaking
  change until 1.0.
- The envelope `v` field is a **separate axis** — wire compatibility is
  negotiated via `hello.capabilities` (docs/ARCHITECTURE.md §8), not git tags.
- Never hand-edit `version` in `pyproject.toml` or `CHANGELOG.md`;
  release-please owns them.

## 4. Setup

```bash
scripts/install-hooks.sh        # lefthook + uv-based commit-msg gate
uv sync                          # dev env
uv run pytest
```

Hooks are bypassable (`--no-verify`); CI is not. A bypass just moves the
failure from your terminal to the PR.

## 5. Tool-specific entry points

Agents: read [`AGENTS.md`](AGENTS.md) — same rules, machine-shaped.
