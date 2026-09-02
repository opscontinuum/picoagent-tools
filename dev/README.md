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

**2. Point the tests at it:**

```bash
PICOAGENT_MERMAID_PARSER_DIR=~/mermaid-check python -m unittest discover -s tests -v
```

Optionally set `PICOAGENT_MERMAID_PARSER_PATHS` (os.pathsep-separated) to validate other
repositories' markdown instead of this one:

```bash
PICOAGENT_MERMAID_PARSER_DIR=~/mermaid-check \
PICOAGENT_MERMAID_PARSER_PATHS=/path/to/picoagent/docs \
  python -m unittest discover -s tests -v
```

Without step 1, step 2 skips with a message naming the missing package. The check is inert
until a human has installed those packages on purpose.

## What this does and does not guarantee

Being straight about the boundary, since a control that is oversold is worse than none.

The real guarantee is **narrow and structural**: the shipped `mermaid_lint` tool contains no
code that spawns a process. An agent calling it cannot reach Node, whatever the environment
says. Nothing here widens the tool's capabilities.

The environment variable is a **convenience switch, not a security boundary**. An agent with
shell access runs as you and could set that variable, or install packages, exactly as you
could - our own [trust boundaries](https://github.com/opscontinuum/picoagent/blob/main/docs/security/trust-boundaries.md)
say as much. If that matters in your environment, the control is the one you already have:
don't grant shell access, or don't install Node where the agent can reach it. The two-step
setup makes accidental activation essentially impossible; it does not make deliberate
activation impossible.
