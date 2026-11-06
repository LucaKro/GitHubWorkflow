#!/usr/bin/env bash
# Posts each discussion waiting in the posts directory to the repository's Discussions,
# in the order it was queued, and removes it from the notes branch once posted. A post
# naming a category the repository lacks, or one GitHub does not create, is kept, and the
# run fails. Run by the posting
# workflow in a checkout of the notes branch, with gh signed in.
#
# Usage: post-discussions.sh <posts directory> <categories query> <create query>
#   <owner/name> <notes branch>
set -euo pipefail

POSTS="$1"
CATEGORIES_QUERY="$2"
CREATE_QUERY="$3"
REPOSITORY="$4"
NOTES_BRANCH="$5"

shopt -s nullglob
waiting=("${POSTS}"/*.json)
if [ "${#waiting[@]}" -eq 0 ]; then
  exit 0
fi
found="$(gh api graphql -F query=@"${CATEGORIES_QUERY}" -f owner="${REPOSITORY%%/*}" -f name="${REPOSITORY#*/}")"
repository_id="$(jq -r '.data.repository.id' <<<"${found}")"
kept=0
for post in "${waiting[@]}"; do
  category="$(jq -r '.category' "${post}")"
  category_id="$(jq -r --arg name "${category}" '.data.repository.discussionCategories.nodes[] | select(.name == $name) | .id' <<<"${found}")"
  if [ -z "${category_id}" ]; then
    echo "kept ${post}: ${REPOSITORY} has no discussion category named ${category}" >&2
    kept=1
    continue
  fi
  if ! gh api graphql -F query=@"${CREATE_QUERY}" \
    -f repositoryId="${repository_id}" \
    -f categoryId="${category_id}" \
    -f title="$(jq -r '.title' "${post}")" \
    -f body="$(jq -r '.body' "${post}")" \
    --jq '.data.createDiscussion.discussion.url'; then
    echo "kept ${post}: GitHub did not create it" >&2
    kept=1
    continue
  fi
  git rm --quiet "${post}"
done
if ! git diff --cached --quiet; then
  git commit --quiet --message "Remove the discussions posted"
  for attempt in 1 2 3; do
    if git push --quiet origin "HEAD:refs/heads/${NOTES_BRANCH}"; then
      break
    fi
    if [ "${attempt}" -eq 3 ]; then
      exit 1
    fi
    git pull --quiet --rebase origin "${NOTES_BRANCH}"
  done
fi
exit "${kept}"
