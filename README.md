# picoagent-tools

A [picoagent](https://github.com/opscontinuum/picoagent) plugin: a stdlib-only base toolset
(diagrams, search, git introspection, test running, structured data). No third-party
dependencies, no network calls, ever.

## Tools

| Tool | What it does |
|---|---|
| `mermaid_reference` | Minimal, correct template for every common Mermaid diagram type (flowchart, sequence, class, state, ER, journey, gantt, pie, mindmap) - call it before guessing syntax from memory. |
| `mermaid_lint` | Regex-level sanity checks on every ` ```mermaid ` fenced block in a file: known diagram type, balanced brackets/quotes, non-empty body. Not a real parser - catches the mistakes that most often break rendering, nothing more. |
| `grep_search` | Regex search across a directory tree. Skips `.git/` and common heavy dirs; honors a basic subset of a root-level `.gitignore` (no negation, no nested files - stated plainly, not oversold). |
| `git_status` / `git_diff` / `git_log` / `git_pr_summary` | Read-only git introspection - status, diffs, history, and commit-list+diffstat between a branch and HEAD. Never commits, pushes, or touches a remote; supplies raw facts for the model to write commit messages/PR descriptions from, not pre-written prose. |
| `run_tests` | Detects a project's test command from marker files (pytest config, `tests/` dir, `package.json`, `Cargo.toml`, `go.mod`) and runs it, with a parsed pass/fail summary. Accepts an explicit `command` override. |
| `structured_data` | Parses and optionally queries JSON/TOML files (real validation, with the parser's own line/col error on failure). YAML has no stdlib parser, so `.yaml`/`.yml` files are returned as raw text with an explicit "not parsed" note - never silently mis-parsed. |

Also bundles `using-mermaid-tools`, a skill so a model that discovers the plugin knows when to
reach for the diagram tools.

## Use

```bash
picoagent -e path/to/picoagent-tools -p "document the auth flow with a sequence diagram"
```

or add it to `.picoagent/config.toml`:

```toml
[plugins]
enabled = ["git:github.com/opscontinuum/picoagent-tools@main"]
```

## Tests

```bash
python -m unittest discover -s tests -v
```
