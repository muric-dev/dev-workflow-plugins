#!/usr/bin/env python3
"""Usage ledger for Claude Code projects. Standard library only, Python 3.9+.

Entry point for every command and for the plugin's Stop hook. Records hold
identifiers and numbers only, never prompt text or file paths.

How data flows on `sync`. sync() below runs these steps, one line each:

    project.py      root, git worktrees, aliases       -> folders that count as the project
    transcripts.py  ~/.claude/projects/**/*.jsonl      -> questions: calls grouped per prompt
    measure.py      question + assets/prices.json      -> record: tokens, USD, active time
    document.py     records + saved usage.json         -> new ledger/usage.json
                    + phases.py (ledger/phases.csv)       (feature and phase per record)
    report.py       usage.json                         -> LEDGER.md, and the console board of `report`

common.py holds what every step shares: file locations, time, atomic writes.

Where to change things:

    Claude Code changed its transcript format    transcripts.py
    New model or new price                       assets/prices.json only
    New pricing rule (tier, multiplier)          measure.call_cost
    New field in a record                        measure.build_record, SCHEMA in document.py,
                                                 references/details.md
    How saved and fresh records merge            document.build_doc
    New table or column in LEDGER.md             report.render
    New view in the console board                report.board
    New command                                  a cmd_* function here, registered in parse_args
"""
import argparse
import json
import os
import sys
from pathlib import Path

import document
import measure
import phases
import project
import report
import transcripts
from common import USAGE_FILE, now_iso, write_atomic

MARKETPLACE = "dev-workflow-plugins"
MARKETPLACE_REPO = "muric-dev/dev-workflow-plugins"
PLUGIN_ID = f"usage-ledger@{MARKETPLACE}"


def sync(root, only_session=None):
    """Import transcripts into the ledger. Returns (usage.json was rewritten, new document)."""
    prices = measure.load_prices()
    questions = transcripts.read_questions(project.project_paths(root), only_session)
    fresh = [measure.build_record(question, prices) for question in questions.values()]
    old_doc = document.read_doc(root)
    doc = document.build_doc(old_doc, fresh, phases.read_phases(root), prices)
    changed = document.save_doc(root, old_doc, doc)
    report.write_report(root, doc)
    for model in measure.unpriced_models(fresh, prices):
        print(f"usage-ledger: no price for {model}; add it to {measure.PRICES_FILE}", file=sys.stderr)
    return changed, doc


# Commands. Each takes the parsed arguments and returns the exit code.


def cmd_sync(args):
    changed, doc = sync(args.root)
    totals = doc["totals"]
    state = "updated" if changed else "already up to date"
    print(f"{USAGE_FILE} {state}: {totals['questions']} questions, {totals['usd']:.2f} USD")
    return 0


def cmd_report(args):
    doc = document.read_doc(args.root)
    if not doc:
        print("No ledger here. Run init first.", file=sys.stderr)
        return 1
    print(report.board(doc))
    return 0


def cmd_phase(args):
    timestamp = args.at or now_iso()
    try:
        phases.add_phase(args.root, timestamp, args.feature, args.phase)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"{args.feature} {args.phase} active from {timestamp}")
    return 0


def cmd_alias(args):
    old_path = args.old_path.rstrip("/")
    project.add_alias(args.root, old_path)
    print(f"{old_path} now counts as this project. Run sync to import it.")
    return 0


def enable_plugin_for_team(path):
    """The plugin ships the Stop hook, so the team only needs the plugin enabled."""
    settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    marketplaces = settings.setdefault("extraKnownMarketplaces", {})
    marketplaces[MARKETPLACE] = {"source": {"source": "github", "repo": MARKETPLACE_REPO}}
    settings.setdefault("enabledPlugins", {})[PLUGIN_ID] = True
    write_atomic(path, json.dumps(settings, indent=2) + "\n")


def cmd_init(args):
    root = args.root
    phases.ensure_file(root)
    if args.shared:
        enable_plugin_for_team(root / ".claude" / "settings.json")
        print(f"{PLUGIN_ID} enabled for the team in .claude/settings.json")
    _, doc = sync(root)
    print(f"Imported {doc['totals']['questions']} questions, {doc['totals']['usd']:.2f} USD")
    return 0


def cmd_hook(_args):
    """Never blocks the agent: exit 2 on Stop would send it back to work."""
    try:
        payload = json.load(sys.stdin)
        root = project.find_root(payload.get("cwd") or Path.cwd())
        if root is not None:
            sync(root, payload.get("session_id"))
    except Exception as error:  # noqa: BLE001 - a broken ledger must not stop the session.
        print(f"usage-ledger: {error}", file=sys.stderr)
    return 0


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Usage ledger for Claude Code projects")
    parser.add_argument("--root", type=lambda value: Path(os.path.realpath(value)), help="project root")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="create the ledger and backfill it")
    init.add_argument("--shared", action="store_true", help="enable the plugin in .claude/settings.json")
    init.set_defaults(run=cmd_init)
    commands.add_parser("sync", help="import every project transcript").set_defaults(run=cmd_sync)
    commands.add_parser("report", help="print the usage board").set_defaults(run=cmd_report)
    commands.add_parser("hook", help="Stop hook entry point").set_defaults(run=cmd_hook)
    phase = commands.add_parser("phase", help="set the active feature and phase")
    phase.add_argument("feature")
    phase.add_argument("phase")
    phase.add_argument("--at", help="ISO timestamp, default now")
    phase.set_defaults(run=cmd_phase)
    alias = commands.add_parser("alias", help="count a former project path as this project")
    alias.add_argument("old_path")
    alias.set_defaults(run=cmd_alias)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.root is None:
        args.root = project.find_root(Path.cwd()) or project.default_root()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
