# dev-workflow-plugins

Claude Code plugin marketplace with skills, agents and hooks for day-to-day development.

## Plugins

| Plugin                                   | What it does                                                                                                                                                                                                                                 |
|------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`usage-ledger`](plugins/usage-ledger)   | Keeps `ledger/usage.json` and `LEDGER.md` in each project: Claude Code tokens, list-price cost and active time per question, attributed by feature and phase, split into work and questions, with optional categories. Needs `python3` 3.9+. |
| [`did-i-mess-up`](plugins/did-i-mess-up) | Installs a git `pre-commit` hook in Flutter/Dart repos: blocks debug leftovers, unformatted files, analyze or test failures, and asks Haiku whether you messed up. Run `/did-i-mess-up:did-i-mess-up install` once per clone.                |

## Install

For yourself, in Claude Code:

```
/plugin marketplace add muric-dev/dev-workflow-plugins
/plugin install usage-ledger@dev-workflow-plugins
/plugin install did-i-mess-up@dev-workflow-plugins
```

For a whole team, commit this to the project's `.claude/settings.json`. Claude Code offers to install the plugin when someone trusts the folder. `/usage-ledger:usage-ledger init --shared` writes it for you.

```json
{
  "extraKnownMarketplaces": {
    "dev-workflow-plugins": { "source": { "source": "github", "repo": "muric-dev/dev-workflow-plugins" } }
  },
  "enabledPlugins": { "usage-ledger@dev-workflow-plugins": true }
}
```

Then, once per project: `/usage-ledger:usage-ledger init`.

## Update

Bump `version` in the plugin's `.claude-plugin/plugin.json` on every change, then users run `/plugin marketplace update dev-workflow-plugins`.

## Develop

```sh
python3 plugins/usage-ledger/skills/usage-ledger/scripts/test_ledger.py
bash plugins/did-i-mess-up/skills/did-i-mess-up/scripts/install.sh status   # inside a repo
claude plugin validate .
```
