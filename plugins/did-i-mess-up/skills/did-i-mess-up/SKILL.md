---
name: did-i-mess-up
description: Install, check or remove a git pre-commit hook for Flutter/Dart repositories that blocks a commit carrying debug or "testing on purpose" leftovers, unformatted Dart files, analyze errors or failing tests, and then asks Haiku whether you messed something up. Use when the user wants the "did I mess up" commit check in this repository or on another machine, asks to install, update, check or remove the pre-commit hook, or a commit was blocked by it and they want to know why.
argument-hint: "[install | status | uninstall]"
allowed-tools: Bash(bash ${CLAUDE_SKILL_DIR}/scripts/install.sh *)
---

# Did I mess up?

A git `pre-commit` hook that asks, before every commit, the only question that matters: did I mess up?
It is versioned here so the same check runs in every clone and on every machine. It lives in
`.git/hooks`, which git never versions, so each clone installs it once.

Its voice is formal, dry and a little funny ("the analyzer respectfully disagrees with you"), and
every message still says what to run next. Keep that voice in any message you add or change, and
relay the hook's output as it prints it.

Requested action: $ARGUMENTS

Run every action from inside the repository:

```sh
bash ${CLAUDE_SKILL_DIR}/scripts/install.sh <install | status | uninstall>
```

With no action, run `status`.

| Action      | What it does                                                                                                                                                                               |
|-------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `install`   | Copies the hook into the repository's hooks folder (`core.hooksPath` and worktrees included). An older did-i-mess-up is replaced in place; someone else's hook is kept as `pre-commit.bak` |
| `status`    | Says whether this version is installed. Exit 1 when it's missing, an older did-i-mess-up, or someone else's hook                                                                           |
| `uninstall` | Removes any version of did-i-mess-up, and restores `pre-commit.bak` if there is one                                                                                                        |

## What the hook checks, on the staged changes

1. Added lines that look left in on purpose: `final x = null;`, `Image.network('')`, `Uri.parse('')`, `print(`,
   `// TEMP|DEBUG|HACK|FIXME`, `if (true)`, `skip: true`. Blocking.
2. `dart format` on the staged Dart files. Blocking.
3. `flutter analyze` and `flutter test`, through `fvm` when the repo has `.fvmrc`. Blocking.
4. Haiku (`claude -p --model haiku`, no tools) reads the staged diff and answers `VERDICT: OK` or `BLOCK`.
   Blocking only on `BLOCK`. Skipped when the `claude` CLI is missing or it doesn't answer within 120 s.

Bypass: `SKIP_HAIKU=1 git commit` skips only step 4, `git commit --no-verify` skips everything.

## Rules

- Install only when the user asks. If `status` reports a different hook, say so before `install` replaces it.
- Never bypass the hook (`--no-verify`, `SKIP_HAIKU=1`) on your own. When it blocks, show its output and fix
  the cause, or ask the user.
- To change the checks, edit `assets/pre-commit` in the `dev-workflow-plugins` repo, bump `version` in
  `plugin.json`, then `/plugin marketplace update` and `install` again in each repository. Never edit an
  installed copy: the next `install` replaces it.
