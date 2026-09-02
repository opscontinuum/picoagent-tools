"""Which Mermaid syntax a given renderer actually supports.

A diagram that parses under the latest Mermaid can still render as nothing on the renderer
your readers use. GitLab is the common case: it vendors a specific Mermaid version and pinned
**10.7.0 from GitLab 16.9 all the way through 18.10**, roughly eighteen months, so anything
added in 10.8.0 or later silently fails for a large installed base.

Everything here is sourced. GitLab bundle versions come from `package.json` at each release
tag in gitlab-org/gitlab; diagram-type versions from Mermaid's releases, changelog, and docs
version banners; the GitLab limits from
`app/assets/javascripts/behaviors/markdown/render_sandboxed_mermaid.js` at v19.3.1-ee.

Deliberately absent: `<br/>` reliability in labels, quoted `subgraph` labels, when
`classDef`/`class` arrived, and `stateDiagram` `note` syntax. No primary source pins those to
a version, and a guessed version table is worse than none - it reports breakage that isn't
real and teaches people to ignore the tool.
"""
from __future__ import annotations

import re

#: (first GitLab, last GitLab inclusive, bundled Mermaid). Sampled at range endpoints; the
#: exact minor where a bump landed inside a range may be off by a minor, so the ranges are
#: written to be conservative.
GITLAB_MERMAID: list[tuple[tuple[int, int], tuple[int, int], str]] = [
    ((13, 0), (13, 5), "8.4.8"),
    ((13, 6), (13, 11), "8.5.2"),
    ((13, 12), (13, 12), "8.9.2"),
    ((14, 0), (14, 4), "8.10.2"),
    ((14, 5), (14, 9), "8.13.2"),
    ((14, 10), (14, 10), "8.13.10"),
    ((15, 0), (15, 5), "9.1.1"),
    ((15, 6), (15, 11), "9.1.3"),
    ((16, 0), (16, 3), "10.1.0"),
    ((16, 4), (16, 5), "10.3.1"),
    ((16, 6), (16, 6), "10.6.0"),
    ((16, 7), (16, 8), "10.6.1"),
    ((16, 9), (18, 10), "10.7.0"),   # pinned for ~18 months - the big installed base
    ((18, 11), (18, 11), "10.7.0"),  # 11.13.0 exists but is behind use_mermaid_v11; assume off
    ((19, 0), (99, 99), "11.13.0"),  # unconditional from 19.0; the v10 path is gone
]

#: Diagram type -> the Mermaid version that introduced it. Types older than 8.4.8 are omitted
#: because GitLab 13.0 already shipped 8.4.8, so they can never be the reason something fails.
DIAGRAM_MIN_VERSION: dict[str, str] = {
    "stateDiagram-v2": "8.5.1",     # check before "stateDiagram": longest prefix wins
    "stateDiagram": "8.4.0",
    "erDiagram": "8.5.0",
    "journey": "8.5.1",
    "requirementDiagram": "8.10.1",
    "C4Context": "9.1.2",
    "mindmap": "9.4.0",             # 9.2.0 as a separate package; in the core bundle from 9.4.0
    "timeline": "9.4.0",
    "quadrantChart": "10.2.0",
    "sankey-beta": "10.3.0",
    "xychart-beta": "10.6.0",
    "block-beta": "10.8.0",
    "packet-beta": "11.0.0",
    "architecture-beta": "11.1.0",
    "kanban": "11.4.0",
    "radar-beta": "11.6.0",
    "treemap-beta": "11.8.0",
    "venn-beta": "11.12.3",
    "treeView-beta": "11.14.0",
    "wardley-beta": "11.14.0",
    "cynefin-beta": "11.16.0",
}

#: Syntax that needs a newer Mermaid than the diagram type itself: (pattern, version, what).
FEATURE_MIN_VERSION: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"@\{\s*shape\s*:"), "11.3.0", "expanded node shapes (A@{ shape: ... })"),
    (re.compile(r"<<-?->>"), "11.0.0", "bidirectional sequence arrows (<<->> / <<-->>)"),
    (re.compile(r"^\s*(create|destroy)\s+participant\b", re.M), "10.3.0",
     "sequence participant create/destroy"),
    (re.compile(r"^\s*until\b", re.M), "10.9.0", "gantt 'until' keyword"),
    (re.compile(r"^\s*namespace\s+\w+\s*\{", re.M), "11.15.0", "classDiagram namespace labels"),
]

#: From render_sandboxed_mermaid.js. Exceeding these is a *soft* failure: GitLab replaces the
#: diagram with a performance warning and a click-to-render button rather than erroring.
GITLAB_MAX_CHARS = 2000          # per diagram, and as a running total across the page
GITLAB_MAX_BLOCKS = 50           # diagrams per page
GITLAB_MAX_CHAINING = 30         # raw count of "&" in one diagram

#: Wiki pages are exempt from the character and block caps (unrestrictedPages).
GITLAB_LIMIT_NOTE = "GitLab shows a click-to-render warning instead of the diagram (wikis are exempt)"


def parse_version(text: str) -> tuple[int, ...]:
    """"10.7" -> (10, 7). Trailing junk is dropped rather than raising."""
    parts = []
    for chunk in text.strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def mermaid_for_gitlab(version: str) -> str | None:
    """The Mermaid version a GitLab release bundles, or None if it predates the table."""
    parsed = parse_version(version)
    if len(parsed) < 2:
        parsed = (parsed + (0,))[:2] if parsed else ()
    if len(parsed) < 2:
        return None
    for low, high, mermaid in GITLAB_MERMAID:
        if low <= parsed[:2] <= high:
            return mermaid
    return None


def resolve_target(target: str) -> tuple[str | None, str | None]:
    """``"gitlab:17.2"`` or ``"mermaid:10.7.0"`` -> (mermaid version, error).

    Exactly one of the pair is set. An unknown GitLab version is an error rather than a
    silent fallback - guessing which Mermaid an unrecognised release ships would produce
    confident wrong answers, which is the failure this whole module exists to avoid.
    """
    kind, _, value = target.strip().partition(":")
    kind, value = kind.lower(), value.strip()
    if not value:
        return None, f"target {target!r} should look like 'gitlab:17.2' or 'mermaid:10.7.0'"
    if kind == "mermaid":
        return (value, None) if parse_version(value) else (None, f"unparseable version {value!r}")
    if kind == "gitlab":
        found = mermaid_for_gitlab(value)
        if found is None:
            return None, (f"no bundled Mermaid version recorded for GitLab {value} "
                          f"(table covers 13.0 to 19.x)")
        return found, None
    return None, f"unknown target kind {kind!r}; expected 'gitlab' or 'mermaid'"


def diagram_type_of(first_line: str) -> str | None:
    """The declared diagram type, matching the longest known name first."""
    for name in sorted(DIAGRAM_MIN_VERSION, key=len, reverse=True):
        if first_line.startswith(name):
            return name
    return None


def check_supported(body: str, first_line: str, mermaid_version: str) -> list[str]:
    """Diagram type and syntax that the target Mermaid is too old to render."""
    target = parse_version(mermaid_version)
    issues = []

    name = diagram_type_of(first_line)
    if name and parse_version(DIAGRAM_MIN_VERSION[name]) > target:
        issues.append(f"{name} needs Mermaid {DIAGRAM_MIN_VERSION[name]}, target has {mermaid_version}")

    for pattern, needed, what in FEATURE_MIN_VERSION:
        if parse_version(needed) > target and pattern.search(body):
            issues.append(f"{what} needs Mermaid {needed}, target has {mermaid_version}")
    return issues


def check_gitlab_limits(body: str) -> list[str]:
    """Per-diagram GitLab rendering caps. Soft failures, reported as such."""
    issues = []
    if len(body) > GITLAB_MAX_CHARS:
        issues.append(f"{len(body)} characters exceeds GitLab's {GITLAB_MAX_CHARS} per-diagram "
                      f"limit - {GITLAB_LIMIT_NOTE}")
    chained = body.count("&")
    if chained > GITLAB_MAX_CHAINING:
        issues.append(f"{chained} '&' link chainings exceeds GitLab's {GITLAB_MAX_CHAINING} "
                      f"limit - {GITLAB_LIMIT_NOTE}")
    return issues


def check_page_limits(bodies: list[str]) -> list[str]:
    """Whole-file GitLab caps: the character budget is a running total across the page."""
    issues = []
    if len(bodies) > GITLAB_MAX_BLOCKS:
        issues.append(f"{len(bodies)} diagrams exceeds GitLab's {GITLAB_MAX_BLOCKS} per page")
    total = sum(len(b) for b in bodies)
    if total > GITLAB_MAX_CHARS:
        issues.append(f"{total} characters across {len(bodies)} diagrams exceeds GitLab's "
                      f"{GITLAB_MAX_CHARS} running total for a page - later diagrams on the "
                      f"page get the click-to-render warning")
    return issues
