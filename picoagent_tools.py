"""Entry module for the picoagent-tools plugin - aggregates every tool module's register().

Each tool module (mermaid_tools, search_tools, git_tools, test_runner_tools,
structured_data_tools) is independent and owns its own tools/tests; this just wires all of
them into the plugin's single ``plugin.toml`` entry point.
"""
from __future__ import annotations

import git_tools
import mermaid_tools
import search_tools
import structured_data_tools
import test_runner_tools


def register(api):
    mermaid_tools.register(api)
    search_tools.register(api)
    git_tools.register(api)
    test_runner_tools.register(api)
    structured_data_tools.register(api)
