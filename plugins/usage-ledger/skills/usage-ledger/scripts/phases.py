"""Owns ledger/phases.csv: the timeline that says which feature and phase work belongs to.

Each row means "from this timestamp on, work is <feature> <phase>":
    ts,feature,phase
    2026-11-02T10:00:00Z,checkout,plan

A record takes the last row at or before its asked_at. With no such row it keeps
its saved attribution, else it stays unassigned.
"""
from common import PHASES_FILE, UNASSIGNED, parse_ts, write_atomic

HEADER = "ts,feature,phase\n"


def ensure_file(root):
    path = root / PHASES_FILE
    if not path.exists():
        write_atomic(path, HEADER)


def add_phase(root, timestamp, feature, phase):
    """Append a row. Raises ValueError on a bad timestamp or a value with a comma."""
    if "," in feature or "," in phase:
        raise ValueError("feature and phase cannot contain commas")
    parse_ts(timestamp)
    path = root / PHASES_FILE
    existing = path.read_text(encoding="utf-8") if path.exists() else HEADER
    write_atomic(path, f"{existing}{timestamp},{feature},{phase}\n")


def read_phases(root):
    """Rows as (datetime, feature, phase), oldest first.

    Rows without three fields are skipped. A bad timestamp raises, so a typo stops
    the sync instead of silently attributing work to the wrong feature.
    """
    try:
        text = (root / PHASES_FILE).read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines()[1:]:
        fields = [field.strip() for field in line.split(",")]
        if len(fields) == 3 and fields[0]:
            rows.append((parse_ts(fields[0]), fields[1], fields[2]))
    return sorted(rows, key=lambda row: row[0])


def attribute(record, phases, prior):
    """(feature, phase) for a record. `prior` is its saved version, or None."""
    asked_at = parse_ts(record["asked_at"])
    active = [row for row in phases if row[0] <= asked_at]
    if active:
        return active[-1][1], active[-1][2]
    if prior:
        return prior["feature"], prior["phase"]
    return UNASSIGNED, UNASSIGNED
