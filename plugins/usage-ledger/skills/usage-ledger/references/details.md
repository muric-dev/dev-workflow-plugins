# Details

The plugin's Stop hook saves the ledger after every turn in any project that has `ledger/usage.json`, so no project command is needed, whatever the language or tooling. Use `/usage-ledger:usage-ledger report` to see the board, or `sync` and `phase <feature> <phase>`. The script lives in the plugin cache, whose path changes with each version, so do not call it from project scripts.

## Git

Commit `ledger/usage.json`, `ledger/phases.csv`, `ledger/categories.csv` (once it exists), and `LEDGER.md`.

The ledger changes every turn, so parallel branches conflict on it. Resolve by taking the base branch's `ledger/usage.json` and `LEDGER.md`, then run `sync` on a machine that still has the transcripts. Records from other machines are kept only if they are in the file you took.

## Stop hook warning

After each turn the hook compares `phases.csv` and `categories.csv` with that turn's prompt. A row set after the prompt counts from the next one, so the hook prints a `systemMessage` naming the row, the attribution the prompt kept, and the `--at` to re-run it with. It never blocks and never edits the timelines.

## Machine-local state

`~/.claude/usage-ledger/aliases.json` maps a project to its former paths. It stays out of the repository because it contains absolute paths.

## Record format

Schema 2, one object per question in `questions`:

| Field              | Meaning                                                                                                                                          |
|--------------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| `id`               | `promptId` of the prompt line, or its `uuid` on transcripts without one                                                                          |
| `session`          | Session UUID                                                                                                                                     |
| `asked_at`         | Prompt timestamp                                                                                                                                 |
| `feature`, `phase` | Last `phases.csv` row at or before `asked_at`. Without one, the saved value, else `unassigned`                                                   |
| `kind`             | `work` if the turn called Edit, MultiEdit, Write or NotebookEdit, else `question`. `unknown` on records saved before schema 2                    |
| `category`         | Last `categories.csv` row at or before `asked_at`, unless a phase row came after it or it is `none`. Without a row, the saved value, else `null` |
| `models[]`         | One entry per model and effort, with `calls`, token counts, and `usd`                                                                            |
| `usd`              | Sum of `models[].usd`                                                                                                                            |
| `active_seconds`   | Sum of `turn_duration`, or capped event gaps on older transcripts                                                                                |

Token counts follow Anthropic's meaning: `input_tokens` excludes cache reads and writes, and `thinking_tokens` is a subset of `output_tokens`. Do not add thinking to output.

## How cost is computed

Each call is priced on its own from `assets/prices.json`, after keeping the last line per `message.id`:

- Haiku 5.5 uses its higher tier when the prompt, counting cache reads and writes, passes 100,000 tokens.
- `speed: fast` applies the model's `fast_multiplier`.
- `inference_geo: us` applies 1.1 where the model has that premium.

## Blind spots

- A file changed through Bash (`sed -i`, a heredoc, `git checkout --`) or an MCP tool leaves no Edit in the transcript, so that turn counts as a `question`. Label it with `category` when the split matters.
- Internal WebFetch calls to a small model do not appear in transcripts.
- The WebSearch tool does not show up in `usage.server_tool_use` in the transcript, so searches are neither counted nor priced.
- Advisor calls, if any, are priced at the main model's rate. `usage.iterations` is not broken down.
- Sessions on other machines, in the cloud, or on claude.ai are not on this disk.
- A session interrupted before Stop is saved by the next `sync`.

## Why not an existing tool

| Option                  | Why not                                                                                                                                 |
|-------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| `ccusage`               | Reports by day and project from the same logs, but keeps nothing in the repository, has no feature or phase attribution, and needs Node |
| `/usage`                | Session-scoped, resets on `/clear`                                                                                                      |
| OpenTelemetry export    | Needs a collector and backend                                                                                                           |
| Admin or Analytics APIs | Organization level, not per project                                                                                                     |
