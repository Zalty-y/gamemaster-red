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

- [ ] User-visible feature (`feat`) — minor bump
- [ ] Fix (`fix`) — patch bump
- [ ] Breaking user-facing change — add `BREAKING CHANGE:` footer to the squash commit body
