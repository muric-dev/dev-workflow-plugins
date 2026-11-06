"""What every step shares: where the ledger's files live, time, and safe writes."""
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Files kept inside the project, relative to its root. Each has one owner module.
USAGE_FILE = Path("ledger/usage.json")  # saved records, written by document.py
PHASES_FILE = Path("ledger/phases.csv")  # feature/phase timeline, owned by phases.py
REPORT_FILE = Path("LEDGER.md")  # human summary, written by report.py

UNASSIGNED = "unassigned"


def config_dir():
    """Claude Code's config folder: transcripts and machine-local state live here."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def write_atomic(path, text):
    """Write through a temp file so a crash never leaves a half-written ledger."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.chmod(temp, 0o644)
    os.replace(temp, path)
