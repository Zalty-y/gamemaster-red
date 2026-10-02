#!/usr/bin/env -S uv run --script --no-project
# /// script
# requires-python = ">=3.12"
# ///
"""gamemaster-red convention validator — the ONE canonical rules file.

Enforced in three places, by this same script:
  - lefthook commit-msg hook   -> hard block      (--msg-file <path> or argv msg)
  - GitHub CI (conventions.yml)-> hard block      (auto-detects GitHub context)
  - lefthook post-checkout     -> soft warning    (--mode branch)

Modes (auto-detected unless --mode given):
  commit    validate a message file / arg
  pr-title  validate GITHUB_EVENT pull_request title (release-please PRs exempt)
  range     validate every non-merge commit GITHUB_SHA..HEAD (push/PR base)
  branch    validate current branch name            (warnings only, exit 0)

Grammar (CONTRIBUTING.md):
  commit/PR/issue title : type(scope): imperative summary   (<= 72 chars)
  branch                : type/<issue-number>-kebab-slug    (slug <= 50 chars)

Exit codes: 0 ok (or branch-mode warnings) · 1 violation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

TYPES = ("feat", "fix", "perf", "refactor", "docs", "test", "build", "ci", "chore", "revert")

SCOPES = (
    "service",
    "adapter-logtail",
    "adapter-bridge",
    "schema",
    "tools",
    "config",
    "docker",
    "deps",
    "ci",
    "docs",
)

TITLE_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-z0-9-]+)\))?(?P<breaking>!)?: "
    r"(?P<subject>.+)$"
)
BRANCH_RE = re.compile(
    r"^(?P<type>[a-z]+)/(?P<issue>\d+)-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)$"
)
ALLOWED_BRANCHES = re.compile(r"^(main|master|release(-v?\d+(\.\d+)*)?)$")

SUMMARY_MAX = 72
SLUG_MAX = 50

# release-please opens these itself; don't hold its PR title to our grammar.
BOT_PR_AUTHORS = ("github-actions[bot]", "release-please[bot]")


def _title_errors(title: str, *, what: str) -> list[str]:
    errors: list[str] = []
    title = title.rstrip()
    if not title or title != title.lstrip():
        return [f"{what}: empty or leading whitespace"]
    m = TITLE_RE.match(title)
    if not m:
        return [
            f'{what}: {title!r} does not match "type(scope): imperative summary"\n'
            f"  types : {' '.join(TYPES)}\n"
            f"  scopes: {' '.join(SCOPES)}\n"
            f"  example: fix(adapter-logtail): survive log rotation without replay"
        ]
    if m["type"] not in TYPES:
        errors.append(f"{what}: unknown type {m['type']!r} (types: {' '.join(TYPES)})")
    if m["scope"] is not None and m["scope"] not in SCOPES:
        errors.append(
            f"{what}: unknown scope {m['scope']!r} (scopes: {' '.join(SCOPES)}; scope may be omitted)"
        )
    if len(title) > SUMMARY_MAX:
        errors.append(f"{what}: {len(title)} chars > {SUMMARY_MAX} limit")
    subject = m["subject"]
    if subject[:1].isupper():
        errors.append(f"{what}: subject must start lowercase (imperative): {subject!r}")
    if subject.endswith("."):
        errors.append(f"{what}: subject must not end with a period")
    return errors


def validate_message(msg: str, *, what: str = "commit") -> list[str]:
    lines = msg.splitlines()
    if not lines or not lines[0].strip():
        return [f"{what}: empty message"]
    title = lines[0]
    # allow `revert: "feat(x): y"` style produced by git revert -n edits
    errors = _title_errors(title, what=what)
    body_lines = lines[1:]
    if body_lines and body_lines[0].strip():
        errors.append(f"{what}: missing blank line after summary")
    for ln in body_lines:
        if ln.rstrip() != ln:
            errors.append(f"{what}: trailing whitespace in body")
            break
    return errors


def validate_branch(branch: str) -> list[str]:
    if ALLOWED_BRANCHES.match(branch):
        return []
    m = BRANCH_RE.match(branch)
    if not m:
        return [
            f'branch: {branch!r} does not match "type/<issue>-kebab-slug" '
            f"(e.g. feat/42-log-tail-rotation)"
        ]
    errors: list[str] = []
    if m["type"] not in TYPES:
        errors.append(f"branch: unknown type prefix {m['type']!r}")
    if len(m["slug"]) > SLUG_MAX:
        errors.append(f"branch: slug {len(m['slug'])} chars > {SLUG_MAX} limit")
    return errors


def _event() -> dict:
    try:
        with open(os.environ.get("GITHUB_EVENT_PATH", ""), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _base_ref() -> str | None:
    """Best-effort comparison base in CI; None if we can't tell."""
    base = os.environ.get("GITHUB_BASE_REF")
    if base:
        return f"origin/{base}"
    before = _event().get("before") or ""
    if re.fullmatch(r"[0-9a-f]{40}", before):
        return before
    return None

def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def current_branch() -> str:
    try:
        return git("branch", "--show-current").strip()
    except subprocess.CalledProcessError:
        return ""



def ci_commits(base: str) -> list[str]:
    log = git("log", "--no-merges", "--format=%H%x00%B%x01", f"{base}..HEAD")
    return [chunk for chunk in log.split("\x01") if chunk.strip()]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=("commit", "pr-title", "range", "branch"))
    ap.add_argument("--msg-file", type=argparse.FileType("r", encoding="utf-8"))
    ap.add_argument("msg", nargs="?", help="commit message (commit mode)")
    ap.add_argument("--strict-branch", action="store_true",
                    help="exit 1 on branch violations instead of warning")
    args = ap.parse_args(argv)

    mode = args.mode
    if mode is None:
        if args.msg_file or args.msg is not None:
            mode = "commit"
        elif os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
            mode = "pr-title"
        elif _base_ref() or os.environ.get("GITHUB_EVENT_NAME") == "push":
            mode = "range"
        else:
            mode = "branch"

    errors: list[str] = []

    if mode == "commit":
        text = args.msg_file.read() if args.msg_file else (args.msg or "")
        errors = validate_message(text)

    elif mode == "pr-title":
        event = _event()
        pr = event.get("pull_request", {})
        author = pr.get("user", {}).get("login", "")
        if author in BOT_PR_AUTHORS:
            print(f"pr-title: {author} PR exempt from title grammar")
            return 0
        if not pr.get("title"):
            print("pr-title: event has no pull_request.title; skipping")
            return 0
        errors = _title_errors(pr["title"], what="PR title")

    elif mode == "range":
        base = _base_ref()
        head = os.environ.get("GITHUB_SHA", "HEAD")
        if base is None:
            # push event whose `before` SHA is unreachable (fresh branch):
            # validate everything the branch adds on top of its fork point
            base = git("rev-parse", f"{head}~1").strip()
        try:
            commits = ci_commits(base)
        except subprocess.CalledProcessError:
            # shallow clone: deepen and materialize remote branches, retry once
            subprocess.run(
                ["git", "fetch", "--no-tags", "--deepen=100", "origin",
                 "+refs/heads/*:refs/remotes/origin/*"],
                check=False,
            )
            commits = ci_commits(base)
        for chunk in commits:
            sha, body = chunk.split("\x00", 1)
            for err in validate_message(body.rstrip("\x00"), what=f"commit {sha[:8]}"):
                errors.append(err)

    elif mode == "branch":
        branch = current_branch()
        if branch:
            errors = validate_branch(branch)

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        if mode == "branch" and not args.strict_branch:
            print(
                "branch: warning only — rename with "
                "`git branch -m <type>/<issue>-<slug>` when convenient",
                file=sys.stderr,
            )
            return 0
        return 1
    print(f"{mode}: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
