#!/usr/bin/env bash
# Copy this repo's skills into a Claude Code skills folder (for use without the plugin).
#
#   ./tools/install.sh                 # -> ~/.claude/skills (every project on this machine)
#   ./tools/install.sh --project DIR   # -> DIR/.claude/skills (commit them with that project)
#   ./tools/install.sh --only unity-quest-sim-loop,horizon-os-mcp
#
# An existing skill folder of the same name is replaced (its old copy is moved to <name>.bak-<time>).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest="${HOME}/.claude/skills"
only=""
while [ $# -gt 0 ]; do
  case "$1" in
    --project) dest="$2/.claude/skills"; shift 2 ;;
    --only) only="$2"; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
mkdir -p "$dest"
stamp="$(date +%Y%m%d-%H%M%S)"
for dir in "$here"/skills/*/; do
  name="$(basename "$dir")"
  if [ -n "$only" ] && [[ ",$only," != *",$name,"* ]]; then continue; fi
  if [ -e "$dest/$name" ]; then mv "$dest/$name" "$dest/$name.bak-$stamp"; fi
  cp -R "$dir" "$dest/$name"
  find "$dest/$name" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
  find "$dest/$name" -path "*/examples/*/out" -type d -prune -exec rm -rf {} + 2>/dev/null || true
  echo "installed $name -> $dest/$name"
done
echo "done. Start a new Claude Code session to load them."
