<!-- Title MUST match: type(scope): imperative summary   (<= 72 chars)
     The title becomes the squash-commit message on main — CI checks it. -->

Closes #

## What

One paragraph: what changes and why. Link the issue's decision, don't restate the code.

## Verification

How this was actually run and observed (not just "tests pass"):

- [ ] `uv run pytest` green
- [ ] command exercised: `...` → observed: `...`

## Release impact

Pick one (the bot computes the bump from the squash-commit type — this is
what it will actually do):

- [ ] `feat` — minor bump (`0.0.x` → `0.1.0` for the first one)
- [ ] `fix` / `perf` — patch bump
- [ ] `docs` / `refactor` / `revert` — patch bump
- [ ] Breaking user-facing change (pre-1.0) — `!` in title **and**
      `BREAKING CHANGE:` footer in the squash body → minor bump
- [ ] `chore` / `test` / `build` / `ci` alone — no release
