#!/usr/bin/env bash
# Deletes each branch the list names that is still at the commit listed with it, then
# empties the list on the notes branch, so a branch made again under a listed name is
# kept. Never deletes the default branch or the notes branch. Run by the deletion
# workflow in a checkout of the notes branch.
#
# Usage: delete-ready-branches.sh <list file> <default branch> <notes branch>
set -euo pipefail

LIST="$1"
DEFAULT_BRANCH="$2"
NOTES_BRANCH="$3"

if [ ! -s "${LIST}" ]; then
  exit 0
fi
while read -r branch commit; do
  if [ -z "${branch}" ] || [ -z "${commit:-}" ] || [ "${branch}" = "${DEFAULT_BRANCH}" ] || [ "${branch}" = "${NOTES_BRANCH}" ]; then
    continue
  fi
  if git push --quiet --force-with-lease="refs/heads/${branch}:${commit}" origin ":refs/heads/${branch}"; then
    echo "deleted ${branch}"
  else
    echo "kept ${branch}: it is gone or no longer at ${commit}"
  fi
done < "${LIST}"
: > "${LIST}"
git add "${LIST}"
git commit --quiet --message "Empty the list of branches ready for deletion"
git push --quiet origin "HEAD:refs/heads/${NOTES_BRANCH}"
