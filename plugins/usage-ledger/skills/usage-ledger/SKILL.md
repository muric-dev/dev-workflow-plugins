---
name: usage-ledger
description: Track Claude Code tokens, cost, and active time per question in a versioned project ledger (ledger/usage.json and LEDGER.md), attributed by feature and phase, split into work and questions with optional categories, and show it as a console board overall and per feature. Works in any project, whatever its language. Use when the user wants to set up usage tracking, save or update the ledger, tag work with a feature or phase, categorize questions (review, tooling...), see what a feature, phase, category, or the whole project cost, or preserve usage before transcripts expire.
argument-hint: "[init | sync | report | phase <feature> <phase> | category <name> | alias <old-path>]"
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/ledger.py *)
---

# Usage ledger

Keeps a per-project usage history in the repository, so it survives transcript cleanup (`cleanupPeriodDays`, 30 days by default). It does not depend on the project's language or tooling: it only needs `python3` and reads Claude Code's local transcripts.

Requested action: $ARGUMENTS

Run every action through:

```sh
python3 ${CLAUDE_SKILL_DIR}/scripts/ledger.py <command>
```

| Goal                                   | Command                                                                                       |
|----------------------------------------|-----------------------------------------------------------------------------------------------|
| Start tracking this project            | `init`, or `init --shared` to also enable the plugin for the team in `.claude/settings.json`  |
| Save usage now                         | `sync`                                                                                        |
| See the board, overall and per feature | `report`                                                                                      |
| Attribute work from now on             | `phase <feature> <phase>`, optional `--at <ISO timestamp>`                                    |
| Label questions from now on            | `category <name>` until the next category or phase, `category none` to clear, optional `--at` |
| Project folder moved or was renamed    | `alias <old-path>`, then `sync`                                                               |

With no action, run `sync`, then `report`.

Show the output of `report` to the user exactly as printed, inside a code block, then at most one line of comment. Do not rebuild it as a Markdown table: the bars and columns are aligned for a monospace font.

## After `init`

The plugin's Stop hook keeps the ledger up to date in any project with `ledger/usage.json`, so `init` adds no hook. Tell the user that `ledger/` and `LEDGER.md` are meant to be committed, and with `--shared`, `.claude/settings.json` too, and that `phase <feature> <phase>` is how work gets attributed to a feature.

## Work, questions and categories

Each question gets a `kind` by itself: `work` when its turn called Edit, MultiEdit, Write or NotebookEdit (a subagent's edit counts too), `question` otherwise. Records saved before schema 2 read as `unknown`. A `category` is the user's label, from `ledger/categories.csv`. The board splits every phase by `kind/category`, and the `Kind / category` table adds them up across features, with USD and active time.

A row counts from its timestamp on. One written during a turn applies from the next prompt, and the Stop hook says so with the `--at` that would cover the turn that just ran. Set the phase or category for a prompt before sending it, or pass that `--at`.

## Rules

- The ledger is read through this skill (`report`) and `LEDGER.md`.
- Never edit `ledger/usage.json` by hand. Fix the input (`phases.csv`, `categories.csv`, `alias`) and run `sync`.
- Records hold identifiers and numbers only. Never add prompt text, tool input or file paths to them.
- Call USD "API list-price equivalent", not spend: on a subscription it is not what the user paid.
- If `sync` warns that a model has no price, tell the user to add it to `assets/prices.json` in the `dev-workflow-plugins` repo from the official pricing page, bump `version` in `plugin.json`, and run `/plugin marketplace update` before `sync`. Never edit the installed copy, an update replaces it. Never guess a price.
- `active_seconds` comes from Claude Code's `turn_duration` when present. Older transcripts fall back to event gaps capped at 5 minutes, which also counts idle time.

## More detail

[references/details.md](references/details.md) covers merge conflicts, the record format, how cost is computed, and known blind spots.
