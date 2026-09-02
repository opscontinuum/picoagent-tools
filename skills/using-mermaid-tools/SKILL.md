---
name: using-mermaid-tools
description: How to write Mermaid diagrams in docs using the mermaid_reference and mermaid_lint tools
---
1. Before writing a diagram type you're not certain of, call `mermaid_reference` rather than
   guessing syntax from memory - it returns a minimal, correct template for every common type
   (flowchart, sequence, class, state, ER, journey, gantt, pie, mindmap).
2. Write the diagram as a fenced ` ```mermaid ` code block in the markdown file.
3. After writing (or editing) a file with diagrams in it, call `mermaid_lint` on that file. It
   flags: an unrecognized diagram-type keyword, unbalanced brackets/quotes, and empty blocks.
   It is a regex-level check, not a real parser - it won't catch every mistake, but it catches
   the ones that most often break rendering.
4. If `mermaid_lint` reports a failing block, fix it with `edit` and re-run the lint before
   telling the user the doc is done.
