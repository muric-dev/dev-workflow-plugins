"""Owns the two attribution timelines: ledger/phases.csv and ledger/categories.csv.

phases.csv says which feature and phase work belongs to. Each row means "from
this timestamp on, work is <feature> <phase>":
    ts,feature,phase
    2026-11-02T10:00:00Z,checkout,plan

categories.csv labels questions inside a phase (review, tooling, ...). Each row
means "from this timestamp on, questions are <category>", until the next
category row or the next phase row, whichever comes first. `none` clears it:
    ts,category
    2026-11-02T10:20:00Z,review

A record takes the last row at or before its asked_at. With no row at all it
keeps its saved attribution, else it stays unassigned (or uncategorized).
"""
from common import CATEGORIES_FILE, PHASES_FILE, UNASSIGNED, parse_ts, write_atomic

HEADER = "ts,feature,phase\n"
CATEGORY_HEADER = "ts,category\n"
NO_CATEGORY = "none"


def ensure_file(root):
    path = root / PHASES_FILE
    if not path.exists():
        write_atomic(path, HEADER)


def append_row(root, file, header, timestamp, values):
    """Raises ValueError on a bad timestamp or a value with a comma."""
    if any("," in value for value in values):
        raise ValueError("values cannot contain commas")
    parse_ts(timestamp)
    path = root / file
    existing = path.read_text(encoding="utf-8") if path.exists() else header
    write_atomic(path, existing + ",".join([timestamp, *values]) + "\n")


def add_phase(root, timestamp, feature, phase):
    append_row(root, PHASES_FILE, HEADER, timestamp, [feature, phase])


def add_category(root, timestamp, category):
    append_row(root, CATEGORIES_FILE, CATEGORY_HEADER, timestamp, [category])


def read_rows(root, file, fields):
    """Rows as (datetime, *values), oldest first.

    Rows with the wrong number of fields are skipped. A bad timestamp raises, so
    a typo stops the sync instead of silently attributing work to the wrong place.
    """
    try:
        text = (root / file).read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines()[1:]:
        values = [value.strip() for value in line.split(",")]
        if len(values) == fields and values[0]:
            rows.append((parse_ts(values[0]), *values[1:]))
    return sorted(rows, key=lambda row: row[0])


def read_phases(root):
    return read_rows(root, PHASES_FILE, 3)


def read_categories(root):
    return read_rows(root, CATEGORIES_FILE, 2)


def attribute(record, phases, prior):
    """(feature, phase) for a record. `prior` is its saved version, or None."""
    asked_at = parse_ts(record["asked_at"])
    active = [row for row in phases if row[0] <= asked_at]
    if active:
        return active[-1][1], active[-1][2]
    if prior:
        return prior["feature"], prior["phase"]
    return UNASSIGNED, UNASSIGNED


def categorize(record, categories, phases, prior):
    """The record's category, or None. A phase row after the category row ends it."""
    asked_at = parse_ts(record["asked_at"])
    active = [row for row in categories if row[0] <= asked_at]
    if not active:
        return (prior or {}).get("category")
    since, category = active[-1]
    if category == NO_CATEGORY or any(since < row[0] <= asked_at for row in phases):
        return None
    return category


def written_after(rows, asked_at):
    """Rows set after `asked_at`: they don't apply to the question asked then."""
    return [row for row in rows if row[0] > parse_ts(asked_at)]
