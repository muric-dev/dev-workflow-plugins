#!/usr/bin/env bash
# Installs, checks or removes the did-i-mess-up pre-commit hook in the current git repository.
# Respects core.hooksPath and worktrees, and never deletes a hook it didn't install.
# Any version of did-i-mess-up is recognised by its "# did-i-mess-up:" header line, so an
# update replaces an older copy in place instead of backing it up as someone else's hook.
set -euo pipefail

src="$(cd "$(dirname "$0")/.." && pwd)/assets/pre-commit"
cd "$(git rev-parse --show-toplevel)"
hooks="$(git rev-parse --git-path hooks)"
target="$hooks/pre-commit"
backup="$target.bak"

# True when the file is a did-i-mess-up hook, of any version.
ours() { [ -f "$1" ] && head -n 5 "$1" | grep -q '^# did-i-mess-up:'; }

case "${1:-status}" in
  install)
    mkdir -p "$hooks"
    if [ -f "$target" ] && cmp -s "$src" "$target"; then
      echo "did-i-mess-up: already on duty at $target. Nothing to do, which is the best outcome."
      exit 0
    fi
    if ours "$target"; then
      cp "$src" "$target"
      chmod +x "$target"
      echo "did-i-mess-up: updated at $target. The older version has been retired, quietly."
      exit 0
    fi
    if [ -f "$target" ]; then
      [ -e "$backup" ] && backup="$target.bak.$(date +%Y%m%d%H%M%S)"
      mv "$target" "$backup"
      echo "did-i-mess-up: the previous hook has been relieved of duty, with honours, and kept as $backup"
    fi
    cp "$src" "$target"
    chmod +x "$target"
    echo "did-i-mess-up: installed at $target. From now on, every commit gets asked: did I mess up?"
    ;;
  status)
    if [ ! -f "$target" ]; then
      echo "did-i-mess-up: not installed ($target missing). Your commits are on the honour system."
      exit 1
    elif cmp -s "$src" "$target"; then
      echo "did-i-mess-up: installed and up to date at $target. Standing by to ask the hard question."
    elif ours "$target"; then
      echo "did-i-mess-up: an older did-i-mess-up is on duty at $target. Run install to update it."
      exit 1
    else
      echo "did-i-mess-up: $target is someone else's hook. install replaces it and keeps the original, respectfully, as a backup."
      exit 1
    fi
    ;;
  uninstall)
    if ! ours "$target"; then
      echo "did-i-mess-up: $target isn't a did-i-mess-up hook. I don't remove hooks I didn't install."
      exit 1
    fi
    rm "$target"
    if ours "$backup"; then
      rm "$backup"
      echo "did-i-mess-up: removed, along with a stale copy of itself in $backup. Your commits are on the honour system again."
    elif [ -f "$backup" ]; then
      mv "$backup" "$target"
      echo "did-i-mess-up: removed. The previous hook resumes its post, from $backup"
    else
      echo "did-i-mess-up: removed. Your commits are on the honour system again."
    fi
    ;;
  *)
    echo "usage: install.sh install | status | uninstall" >&2
    exit 2
    ;;
esac
