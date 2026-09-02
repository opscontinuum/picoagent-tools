# Optional: validating diagrams with Mermaid's real parser

**Off by default. Nothing in this directory runs unless you explicitly enable it, and none of
it is reachable from the `mermaid_lint` tool.**

## Why it exists

`mermaid_lint` is a regex, not a parser, and it has been wrong in practice. Validating this
project's own diagrams against real Mermaid found two that the linter had passed and that do
not parse:

* a `sequenceDiagram` participant named `Loop`, colliding with the `loop ... end` block
* a `;` inside sequence message text, which Mermaid treats as a statement separator

Rules were added for both, but the general lesson holds: only the parser knows the grammar. If
you publish diagrams, check them against the real thing at least once.

## Exactly what runs if you enable it

This matters more than the feature, so it is spelled out precisely.

**The script:** [`mermaid_parse_check.mjs`](mermaid_parse_check.mjs), about 70 lines, in this
directory. Read it - it is meant to be auditable in one sitting. It:

1. reads the markdown files you name,
2. extracts every ` ```mermaid ` fenced block with a regular expression,
3. calls `mermaid.parse()` on each,
4. prints a verdict and exits non-zero if any failed.

**The exact command executed** by `tests/test_mermaid_real_parser.py`:

```
node <repo>/dev/mermaid_parse_check.mjs --modules $PICOAGENT_MERMAID_PARSER_DIR <paths>
```

Nothing else is spawned. No shell is involved - the test uses an argument list, not a command
string.

**What it does not do:**

* **Does not install anything.** If `mermaid` or `jsdom` are missing from the directory you
  point it at, it exits with a message. There is no `npm install` anywhere in this repo.
* **Does not touch the network.** It imports two local packages and reads local files.
* **Does not write any file.** It only reads and prints.
* **Does not run during a normal `mermaid_lint` call.** The tool the model invokes has no code
  path that reaches Node. That property is unchanged by this directory existing.

## Enabling it

Two deliberate steps, because either alone should not be enough:

**1. Provision Node packages yourself**, somewhere outside this repo:

```bash
mkdir -p ~/mermaid-check && cd ~/mermaid-check
npm init -y
npm install mermaid jsdom@22        # jsdom 23+ needs Node 20+; 22 works on Node 18
```

**2. Write the opt-in file**, `~/.picoagent/dev-tools.toml`:

```toml
[mermaid_parser]
modules_dir = "~/mermaid-check"
# paths = "/path/to/picoagent/docs"   # optional; defaults to this repo
```

Then run the suite normally:

```bash
python -m unittest discover -s tests -v
```

Without step 1, step 2 skips with a message naming the missing package. Without step 2,
everything skips. The check is inert until a human has done both on purpose.

**Not an environment variable, deliberately.** An env var is no gate at all against the agent:
the shell tool runs commands as the user, and `VAR=x command` sets a variable for the child
whatever the parent environment allows. That was measured against this project's own guarded
shell, not assumed - inline assignment, `export`, and writing files all succeeded.

## What this does and does not guarantee

Being exact, since a control that is oversold is worse than none.

**Structural, and holds absolutely:** the shipped `mermaid_lint` tool contains no code that
spawns a process. No `subprocess`, no shell, no network. An agent calling the tool cannot
reach Node whatever any configuration says. Nothing in this directory widens the tool's
capabilities - it is developer tooling that the tool cannot invoke.

**Enforced against the agent's file tools:** the plugin registers a `tool_call` guard that
refuses any tool call naming `~/.picoagent/dev-tools.toml`, by resolved path, for *every* tool
rather than a known list. `read`, `write`, `edit`, `grep_search`, `structured_data`, and
anything added later are all refused.

**Not enforced against the shell**, and this is the honest limit. A shell command runs as you
and can write any file you can write, so an agent with an unrestricted `shell` tool can create
this file. Measured, not theoretical. The guard closes the easy and accidental routes; it is
not containment.

If your environment needs the hard guarantee, use the levers that actually provide it:

* don't install Node where the agent can reach it - the check exits rather than installing
  anything, so with no packages present it cannot run at all;
* restrict the toolset (`api.set_active_tools([...])` without `shell`, i.e. a read-only or
  plan mode);
* use `permission-gate` to refuse writes to that path.

This mirrors what [the trust boundaries doc](https://github.com/opscontinuum/picoagent/blob/main/docs/security/trust-boundaries.md)
says generally: the boundary around an agent is the tools it is given, not a configuration
file it happens to be asked not to touch.
