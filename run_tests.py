"""Temporary test runner that shims the main repo's venv site-packages.

Removed after test verification; only exists because the worktree lacks its own
venv and the sandbox restricts executing the main repo's python binary directly.
"""
import os
import sys
import site

VENV_BASE = r"D:\DEV\ClaudeProjects\VideoSearchDB\backend\venv"

site_packages_candidates = [
    os.path.join(VENV_BASE, "Lib", "site-packages"),
]
for sp in site_packages_candidates:
    if os.path.isdir(sp):
        site.addsitedir(sp)

# Ensure the worktree backend comes first so `app.*` imports resolve here.
worktree_backend = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
sys.path.insert(0, worktree_backend)

os.chdir(worktree_backend)

import pytest  # noqa: E402

raise SystemExit(pytest.main(["tests/", "-v"]))
