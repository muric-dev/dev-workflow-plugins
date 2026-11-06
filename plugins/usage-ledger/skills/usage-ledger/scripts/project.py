"""Step 1. Which folders count as this project.

A project is its root, its git worktrees, and the former paths registered with
`alias`. Transcripts whose cwd is one of these folders, or inside one, are imported.

Owns ~/.claude/usage-ledger/aliases.json: {root: [former paths]}. It stays on
this machine because it holds absolute paths.
"""
import json
import os
import subprocess
from pathlib import Path

from common import USAGE_FILE, config_dir, write_atomic


def aliases_file():
    return config_dir() / "usage-ledger" / "aliases.json"


def read_aliases():
    try:
        return json.loads(aliases_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def add_alias(root, old_path):
    aliases = read_aliases()
    known = aliases.setdefault(str(root), [])
    if old_path not in known:
        known.append(old_path)
    write_atomic(aliases_file(), json.dumps(aliases, indent=2) + "\n")


def run_git(root, *args):
    """Git output, or None when git is missing or the folder is not a repository."""
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def worktrees(root):
    listing = run_git(root, "worktree", "list", "--porcelain") or ""
    return [line[len("worktree "):] for line in listing.splitlines() if line.startswith("worktree ")]


def project_paths(root):
    root = str(root)
    return sorted({root, *worktrees(root), *read_aliases().get(root, [])})


def in_project(cwd, paths):
    return any(cwd == path or cwd.startswith(path + "/") for path in paths)


def find_root(start):
    """Nearest folder at or above `start` that already has a ledger."""
    start = Path(os.path.realpath(start))
    for directory in (start, *start.parents):
        if (directory / USAGE_FILE).is_file():
            return directory
    return None


def default_root():
    """Where `init` creates a ledger: the git top level, else the current folder."""
    top = run_git(Path.cwd(), "rev-parse", "--show-toplevel")
    return Path(os.path.realpath(top.strip() if top else Path.cwd()))
