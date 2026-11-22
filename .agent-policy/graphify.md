# Graphify policy (canonical)

All AI agents in this repository share **this file** as the single Graphify
policy. `AGENTS.md` points here; no agent config duplicates these rules.
Security rules in `AGENTS.md` always win over anything below.

## Installed state (verified locally, offline)

| Item            | Value                                                                 |
| --------------- | --------------------------------------------------------------------- |
| Executable      | `C:\Users\Rising\.local\bin\graphify.exe` (shared, outside the repo)  |
| Package version | `0.9.115` (`graphify --version`)                                      |
| Skill copy      | `.opencode/skills/graphify/` — built from `0.9.31` (older, still usable) |
| Map output      | `graphify-out/` — Git-ignored, never committed                        |
| Git             | Initialised (`master`, no remote, **no commits yet**)                 |
| Git hooks       | 4 installed + hand-patched (see below)                                |
| Merge driver    | `merge.graphify` registered in `.git/config` (harmless — graph ignored) |

**Known skew:** the project skill copy (0.9.31) trails the package (0.9.115).
The commands below work fine; the skill only affects agent-facing docs. Do
**not** run `graphify install --platform opencode` to fix it: that installer
also rewrites `AGENTS.md` and adds a `tool.execute.before` plugin, which would
duplicate this policy and bypass the repo's own permission model.

**Auto-refresh side effect (important):** `graphify` silently refreshes skill
copies for detected platforms on invocation, including paths **outside this
repository** (`~/.claude/skills/graphify`, `~/.gemini/config/skills/graphify`).
That breaks the project-boundary rule. Always set `GRAPHIFY_NO_AUTO_REFRESH=1`
when running graphify from this repo:

```powershell
$env:GRAPHIFY_NO_AUTO_REFRESH = "1"
```

## Commands verified against this version

| Need                    | Command                                     |
| ----------------------- | ------------------------------------------- |
| Local code map (no key) | `graphify extract . --code-only --no-cluster` |
| Cluster only (offline)  | `graphify cluster-only . --no-label --no-viz` |
| Ask the map             | `graphify query "<question>"`               |
| Explain one node        | `graphify explain "<node>"`                 |
| Path between two nodes  | `graphify path "A" "B"`                     |
| Impact of a symbol      | `graphify affected "<node>"`                |
| Hubs                    | `graphify god-nodes --top 10`               |
| Refresh after edits     | `graphify update .`                         |
| Hook / integration      | `graphify hook status`, `graphify opencode install` (installers — not run here) |

## Required workflow

1. **Map first.** For questions about architecture, call relationships,
   dependencies, or the impact of a change, query the map before reading files.
2. **Verify.** Confirm every symbol, path, line number and edge the map reports
   against the current source with `grep` / direct inspection.
3. **Fall back honestly.** If `graphify-out/graph.json` is absent, stale, or
   does not cover the content (audits, findings, `README.md`, SQL, configs),
   say so and use ordinary repository-local search. Uncommitted work is not in
   the map.
4. **Right-size.** Skip Graphify for tasks unrelated to code structure. Never
   invent Graphify findings. Before risky edits, review affected nodes and run
   the relevant tests afterwards.

## Output rules

- Keep `graphify-out/`, `graph.json` and rebuild logs repository-local and
  Git-ignored. Never commit generated graph JSON.
- A `merge.graphify` driver is registered in `.git/config` but is unnecessary
  because the graph file is never tracked; it is harmless.
- No Graphify operation may write outside this repository.

## Git hooks (installed and patched)

`graphify hook install` wrote four hooks. All were then hand-patched so nothing
is written outside the repository:

| Hook            | Fires on                         |
| --------------- | -------------------------------- |
| `post-commit`   | every commit                     |
| `post-checkout` | branch switch / checkout         |
| `post-merge`    | merge completes                  |
| `post-rewrite`  | rebase or `git pull --rebase`    |

Patch applied to each (`AGENTS.md` §1 compliance):

```sh
_GRAPHIFY_LOG="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/graphify-out/rebuild.log"
export GRAPHIFY_NO_AUTO_REFRESH=1
```

Rebuilds run detached, re-extract changed code files only (AST, no LLM, no
network) and rewrite `graphify-out/graph.json` + `GRAPH_REPORT.md`.

**Never re-run `graphify hook install`.** It would overwrite the patch, restore
`$HOME/.cache/graphify-rebuild.log`, and `graphify hook status` would stop
warning about drift. `graphify hook status` currently reports all four as
"installed (out of date)" — that drift is the patch itself, not breakage.

**Pre-push gate: not installed.** Nothing blocks a push yet. A real gate must
scan outgoing commits (`git diff --name-only @{u}..HEAD`, not staged files) for
secrets and policy violations. Not written — awaiting approval.

## Awaiting approval (manual, user-run only)

Agents never install or upgrade Graphify. Package is current (`0.9.115`), Git is
initialised and hooks are installed. Outstanding items:

1. **Pre-push secrets/policy gate** — not written; see above.
2. **First commit** — the repo has no commits, so the hooks have never actually
   run. Until a commit exists their runtime behaviour is unverified.
3. **Merge driver** — registered but unused; remove with
   `git config --local --remove-section merge.graphify` if you prefer a clean
   `.git/config`.
