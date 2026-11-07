#!/usr/bin/env bash
# Measures what this session can do on git and GitHub, and publishes what it found to the
# github-workflow/probe-results branch, outside every code branch, so it can be fetched and
# read elsewhere and the branch deleted afterwards. The checked-out branch is never
# committed to.
#
# Installs this package and the domain model it ships into a fresh environment of its own,
# runs `python -m github_workflow.probe`, which publishes the report and the results under
# <UTC stamp>/ on that branch. The checks create a label, an
# issue, a draft pull request and a few branches on the repository, write two settings
# back unchanged, and run one short Actions workflow that deletes its own branches. The
# issue and the pull request are closed rather than deleted, and a branch a session may
# not delete is named in the report.
#
# Usage: bash scripts/cloud-probe.sh
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RESULTS="$(mktemp -d)/${STAMP}"
ENVIRONMENT="$(mktemp -d)/environment"

cd "${ROOT}" || exit 1

# A checkout behind its remote would run an old probe and have its push refused. Bash
# reads this script while running it, so it stops rather than updating itself.
CURRENT="$(git branch --show-current)"
if [ -n "${CURRENT}" ] && git fetch --quiet origin "${CURRENT}" 2>/dev/null &&
  [ "$(git rev-list --count HEAD..FETCH_HEAD)" != "0" ]; then
  echo "${CURRENT} is behind origin/${CURRENT}: run 'git merge --ff-only origin/${CURRENT}', then run this again"
  exit 1
fi

mkdir -p "${RESULTS}"

# The project's own author signs every commit the probe makes, its own probe commits
# included, rather than whatever identity the session's git carries.
mapfile -t AUTHOR < <(python3 -I -c '
import sys, tomllib
author = tomllib.load(open(sys.argv[1], "rb"))["project"]["authors"][0]
print(author["name"]); print(author["email"])' "${ROOT}/pyproject.toml")
export GIT_AUTHOR_NAME="${AUTHOR[0]}" GIT_COMMITTER_NAME="${AUTHOR[0]}"
export GIT_AUTHOR_EMAIL="${AUTHOR[1]}" GIT_COMMITTER_EMAIL="${AUTHOR[1]}"

if {
  python3 -m venv "${ENVIRONMENT}" &&
    "${ENVIRONMENT}/bin/python" -m pip install --quiet --editable "${ROOT}/domain_model" &&
    "${ENVIRONMENT}/bin/python" -m pip install --quiet --editable "${ROOT}"
} >"${RESULTS}/install.log" 2>&1; then
  "${ENVIRONMENT}/bin/python" -m github_workflow.probe "${RESULTS}"
else
  echo "installing failed; the install log follows, to paste back by hand:"
  cat "${RESULTS}/install.log"
fi
