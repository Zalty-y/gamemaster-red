#!/usr/bin/env bash
# One-time hook setup for humans and agents:
#   scripts/install-hooks.sh
# Installs lefthook (if missing) and wires .git/hooks to lefthook.yml.
set -euo pipefail

DEST="${HOME}/.local/bin"

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv not on PATH — install it first:" >&2
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

if ! command -v lefthook >/dev/null 2>&1; then
  echo "lefthook not found — installing to ${DEST}"
  os=$(uname -s); arch=$(uname -m)
  tag=$(curl -fsSL https://api.github.com/repos/evilmartians/lefthook/releases/latest \
        | sed -n 's/.*"tag_name": *"\(v[^"]*\)".*/\1/p')
  ver=${tag#v}
  case "$os/$arch" in
    Linux/x86_64|Linux/amd64)  plat="Linux_x86_64" ;;
    Linux/aarch64|Linux/arm64) plat="Linux_arm64" ;;
    Darwin/arm64)              plat="MacOS_arm64" ;;
    Darwin/x86_64)             plat="MacOS_x86_64" ;;
    *) echo "error: unsupported platform $os/$arch — install lefthook manually" >&2; exit 1 ;;
  esac
  asset="lefthook_${ver}_${plat}.gz"
  url="https://github.com/evilmartians/lefthook/releases/download/${tag}/${asset}"
  mkdir -p "$DEST"
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$url"
  elif command -v wget >/dev/null 2>&1; then wget -qO- "$url"
  else echo "need curl or wget" >&2; exit 1; fi \
    | gunzip > "${DEST}/lefthook"
  chmod +x "${DEST}/lefthook"
  PATH="${DEST}:${PATH}"
  command -v lefthook >/dev/null 2>&1 || {
    echo "error: lefthook installed to ${DEST} but not on PATH — add it" >&2; exit 1; }
fi

cd "$(git rev-parse --show-toplevel)"
lefthook install
echo "hooks installed. Try it: git commit --allow-empty -m 'oops no grammar'"
