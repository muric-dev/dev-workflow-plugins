# dev-workflow-plugins

Claude Code plugin marketplace with skills, agents and hooks for day-to-day development.

## Plugins

| Plugin                                 | What it does                                                                                                                                                                        |
|----------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`usage-ledger`](plugins/usage-ledger) | Keeps `ledger/usage.json` and `LEDGER.md` in each project: Claude Code tokens, list-price cost and active time per question, attributed by feature and phase. Needs `python3` 3.9+. |

## Install

For yourself, in Claude Code:

```
/plugin marketplace add muric-dev/dev-workflow-plugins
/plugin install usage-ledger@dev-workflow-plugins
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
claude plugin validate .
```
