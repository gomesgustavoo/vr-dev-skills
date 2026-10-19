#!/usr/bin/env bash
# Copy this repo's skills to where your coding agent looks for them (no Node needed).
# The one-line alternative for any agent is:  npx skills add gomesgustavoo/vr-dev-skills
#
#   ./tools/install.sh                                  # universal (~/.agents/skills) + Claude Code if ~/.claude exists
#   ./tools/install.sh --agent codex                    # one agent
#   ./tools/install.sh --agent codex,claude-code,cursor # several
#   ./tools/install.sh --project ~/src/MyQuestApp       # into that project instead of your home folder
#   ./tools/install.sh --only unity-quest-sim-loop,horizon-os-mcp
#
# Agents (global path / project path):
#   universal       ~/.agents/skills           .agents/skills   (Codex, Cline, Warp, Zed and others)
#   codex           ~/.agents/skills           .agents/skills
#   claude-code     ~/.claude/skills           .claude/skills
#   cursor          ~/.cursor/skills           .agents/skills
#   gemini-cli      ~/.gemini/skills           .agents/skills
#   github-copilot  ~/.copilot/skills          .agents/skills
#   opencode        ~/.config/opencode/skills  .agents/skills
# An existing skill folder of the same name is replaced (the old copy is moved to <name>.bak-<time>).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
agents=""
project=""
only=""
while [ $# -gt 0 ]; do
  case "$1" in
    --agent) agents="$2"; shift 2 ;;
    --project) project="$2"; shift 2 ;;
    --only) only="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$agents" ]; then
  agents="universal"
  [ -d "$HOME/.claude" ] && agents="$agents,claude-code"
fi

dest_for() {   # agent -> skills folder
  local a="$1"
  if [ -n "$project" ]; then
    case "$a" in
      claude-code) echo "$project/.claude/skills" ;;
      universal|codex|cursor|gemini-cli|github-copilot|opencode) echo "$project/.agents/skills" ;;
      *) return 1 ;;
    esac
  else
    case "$a" in
      universal|codex) echo "$HOME/.agents/skills" ;;
      claude-code) echo "$HOME/.claude/skills" ;;
      cursor) echo "$HOME/.cursor/skills" ;;
      gemini-cli) echo "$HOME/.gemini/skills" ;;
      github-copilot) echo "$HOME/.copilot/skills" ;;
      opencode) echo "$HOME/.config/opencode/skills" ;;
      *) return 1 ;;
    esac
  fi
}

stamp="$(date +%Y%m%d-%H%M%S)"
done_dests=" "
IFS=',' read -ra list <<< "$agents"
for agent in "${list[@]}"; do
  dest="$(dest_for "$agent")" || { echo "unknown agent: $agent (see --help)" >&2; exit 2; }
  case "$done_dests" in *" $dest "*) continue ;; esac   # agents that share a folder get one copy
  done_dests="$done_dests$dest "
  mkdir -p "$dest"
  for dir in "$here"/skills/*/; do
    name="$(basename "$dir")"
    if [ -n "$only" ] && [[ ",$only," != *",$name,"* ]]; then continue; fi
    if [ -e "$dest/$name" ]; then mv "$dest/$name" "$dest/$name.bak-$stamp"; fi
    cp -R "$dir" "$dest/$name"
    find "$dest/$name" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
    find "$dest/$name" -path "*/examples/*/out" -type d -prune -exec rm -rf {} + 2>/dev/null || true
  done
  echo "installed -> $dest  ($agent)"
done
echo "done. Start a new agent session to load them."
