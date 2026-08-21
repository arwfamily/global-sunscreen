#!/usr/bin/env bash
# .github/publish.sh — the ONLY place this repo talks to git.
#
# Every persistence failure this project has had came from a different copy
# of push/rebase logic:
#   - "cannot rebase: You have unstaged changes"  (a collector wrote files
#     after staging)                              -> --autostash
#   - "fatal: no rebase in progress"              (an aborted rebase left
#     state behind)                               -> clear it first
#   - "You are not currently on a branch"         (detached HEAD stranded
#     the run's commits)                          -> push HEAD:<branch>
#   - shallow clone with nothing to rebase onto   -> unshallow up front
# One implementation, so a fix stays fixed.
set -uo pipefail
MSG="${1:?commit message required}"
BRANCH="${GITHUB_REF_NAME:-main}"

if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
  echo "[publish] clearing an interrupted rebase"
  git rebase --abort || git rebase --quit || true
fi

git config user.name  "ingredients-bot"
git config user.email "actions@users.noreply.github.com"
git add -A data/
if ! git diff --cached --quiet; then
  git commit -q -m "$MSG"
  echo "[publish] committed: $MSG"
fi

if [ "$(git rev-parse --is-shallow-repository 2>/dev/null)" = "true" ]; then
  git fetch --unshallow --quiet || true
fi

git fetch --quiet origin "$BRANCH"
AHEAD=$(git rev-list --count "origin/$BRANCH..HEAD")
echo "[publish] commits waiting to push: $AHEAD"
[ "$AHEAD" -eq 0 ] && { echo "[publish] nothing to push"; exit 0; }

for i in 1 2 3 4; do
  if git push --quiet origin "HEAD:$BRANCH"; then
    echo "[publish] pushed $AHEAD commit(s) on attempt $i"; exit 0
  fi
  echo "[publish] push rejected (attempt $i) - replaying onto origin/$BRANCH"
  git fetch --quiet origin "$BRANCH"
  if ! git rebase --autostash --quiet "origin/$BRANCH"; then
    git rebase --abort || true
    echo "::error::rebase onto origin/$BRANCH failed - conflicting history"
    break
  fi
  sleep $((i * 5))
done
echo "::error::could not publish. The commit exists locally at $(git rev-parse --short HEAD); data/ is attached to this run as an artifact."
exit 1
