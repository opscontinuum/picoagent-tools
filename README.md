# picoagent-tools

A [picoagent](https://github.com/opscontinuum/picoagent) plugin: a stdlib-only base toolset
(diagrams, search, git introspection, test running, structured data). No third-party
dependencies, no network calls, ever.

## Tools

| Tool | What it does |
|---|---|
| `mermaid_reference` | Minimal, correct template for every common Mermaid diagram type (flowchart, sequence, class, state, ER, journey, gantt, pie, mindmap) - call it before guessing syntax from memory. |
| `mermaid_lint` | Checks every ` ```mermaid ` block: known diagram type, balanced brackets/quotes, non-empty body, and grammar collisions that look like ordinary text. With `target`, also checks what a specific renderer supports. Not a real parser - see below. |
| `grep_search` | Regex search across a directory tree. Skips `.git/` and common heavy dirs; honors a basic subset of a root-level `.gitignore` (no negation, no nested files - stated plainly, not oversold). |
| `git_status` / `git_diff` / `git_log` / `git_pr_summary` | Read-only git introspection - status, diffs, history, and commit-list+diffstat between a branch and HEAD. Never commits, pushes, or touches a remote; supplies raw facts for the model to write commit messages/PR descriptions from, not pre-written prose. |
| `run_tests` | Detects a project's test command from marker files (pytest config, `tests/` dir, `package.json`, `Cargo.toml`, `go.mod`) and runs it, with a parsed pass/fail summary. Accepts an explicit `command` override. |
| `structured_data` | Parses and optionally queries JSON/TOML files (real validation, with the parser's own line/col error on failure). YAML has no stdlib parser, so `.yaml`/`.yml` files are returned as raw text with an explicit "not parsed" note - never silently mis-parsed. |

Also bundles `using-mermaid-tools`, a skill so a model that discovers the plugin knows when to
reach for the diagram tools.

## Targeting a renderer

A diagram that parses under the latest Mermaid can still render as nothing where your readers
are. GitLab is the common case: it vendors a specific Mermaid version and **pinned 10.7.0 from
GitLab 16.9 through 18.10**, about eighteen months, so anything added in 10.8.0 or later fails
for a large installed base.

```
mermaid_lint(path="docs/architecture.md", target="gitlab:17.2")
mermaid_lint(path="docs/architecture.md", target="mermaid:10.7.0")
```

With a target, the lint also reports:

* **Diagram types too new** for that renderer - `block-beta` needs 10.8.0, so it fails on
  GitLab 16.9-18.10 while `xychart-beta` (10.6.0) squeaks in.
* **Syntax too new**, such as expanded node shapes (`A@{ shape: ... }`, 11.3.0) or
  bidirectional sequence arrows (`<<->>`, 11.0.0).
* **GitLab's size limits**, for a `gitlab:` target: 2000 characters per diagram *and* as a
  running total per page, 50 diagrams per page, 30 `&` link chainings. Exceeding these is a
  soft failure - GitLab shows a click-to-render warning instead of the diagram. Wiki pages are
  exempt from the character and block caps.

An unrecognised GitLab version is an error, not a guess. Version data and its sources are in
`mermaid_versions.py`.

## What this does not check

It is a regex, not a parser, and the gap is real: validating this project's own diagrams
against actual Mermaid found two that it had passed and that do not parse - a participant
named `Loop` (colliding with `loop ... end`) and a `;` inside sequence message text. Both are
now rules, but the lesson generalises. For anything you are publishing, run the diagrams
through Mermaid itself.

Four things are deliberately **not** checked, because no primary source pins them to a
version: `<br/>` reliability in labels, quoted `subgraph` labels, when `classDef`/`class`
styling arrived, and `stateDiagram` `note` syntax. A guessed version table reports breakage
that isn't real and teaches people to ignore the tool.

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
