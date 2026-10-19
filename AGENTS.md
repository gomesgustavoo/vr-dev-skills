# AGENTS.md

Guidance for coding agents (Codex, Claude Code, Copilot, Cursor, Gemini CLI, ...) working in this
repository or using its skills.

## What this repo is

Four [Agent Skills](https://agentskills.io) for Meta Quest development, each a folder under
`skills/` with a `SKILL.md` (front matter `name` + `description`, then the instructions),
`scripts/`, `references/` and `assets/`:

| skill | use it for |
|---|---|
| `skills/unity-quest-sim-loop` | test and debug a Unity Quest app in the Meta XR Simulator through the XR Operator and the app's own tools; JSON scenario suites; headless gates |
| `skills/horizon-os-mcp` | Meta's Horizon OS MCP: docs and API lookups, device control, Perfetto traces |
| `skills/quest-build-deploy` | headless builds behind gates, adb sideload, crash check, worn-headset readout |
| `skills/blender-cli-vr-assets` | headless Blender stages to Unity: validated, deterministic FBX + baked atlases |

`.claude-plugin/` packages the same folders as a Claude Code plugin; nothing in the skills depends
on it.

## Using the skills from another project

- `npx skills add gomesgustavoo/vr-dev-skills` (any agent), or copy the folders to
  `.agents/skills/` (Codex and most agents) / `.claude/skills/` (Claude Code), or run
  `tools/install.sh --agent <agent>`.
- When a task matches a skill's description, read that `SKILL.md` first and follow it; open the
  `references/` it names only when needed. `<skill>` in the text means that skill's folder.
- Scripts are Python 3.10+ (stdlib) and Windows PowerShell 5.1; run them with paths, not by
  importing them into another interpreter.

## Working on this repo

- Before committing, run `python tools/check_repo.py`: secrets, personal paths and addresses, skill
  front matter, JSON and Python validity. It must print `check_repo: OK`.
- Never add credentials, device serials, internal host names, client project names or personal
  paths. A git-ignored `.private-terms` file lists local terms the check must never find.
- Keep each `SKILL.md` under 500 lines and its description under 1,536 characters; move detail
  into `references/`.
- Write skill text for any agent: refer to "the agent" and to MCP servers by name, not to one
  harness's tool names. Harness specifics belong in examples, clearly labelled.
- Diagrams in `docs/assets/*.svg` are generated: edit `docs/assets/src/*.py` and run
  `python docs/assets/src/make.py` (needs `pip install -r docs/assets/src/requirements.txt`).
  Never hand-edit the SVGs.
- Text files use LF (`.gitattributes`); `tools/install.sh` stays executable.
- Commit messages: imperative subject, a body that says why.
