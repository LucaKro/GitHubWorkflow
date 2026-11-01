#!/usr/bin/env bash
# Measures what this session can do on git and GitHub, then commits what it found and
# pushes it, so it can be pulled and read elsewhere: to the checked-out branch, or to a
# branch of its own when that is the default branch.
#
# Installs this package and basstler-domain-model into a fresh environment of its own,
# runs `python -m github_workflow.probe`, and records the install log, the run log, the
# report and the results under probe-results/<UTC stamp>/. The checks create a label, an
# issue, a draft pull request and a few branches on the repository, write two settings
# back unchanged, and run one short Actions workflow that deletes its own branches. The
# issue and the pull request are closed rather than deleted, and a branch a session may
# not delete is named in the report.
#
# Usage: bash scripts/cloud-probe.sh
set -uo pipefail

DOMAIN_MODEL="basstler-domain-model @ git+https://github.com/LucaKro/basstler_domain_model@extract-from-basstler"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RESULTS="${ROOT}/probe-results/${STAMP}"
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
    "${ENVIRONMENT}/bin/python" -m pip install --quiet "${DOMAIN_MODEL}" &&
    "${ENVIRONMENT}/bin/python" -m pip install --quiet --editable "${ROOT}"
} >"${RESULTS}/install.log" 2>&1; then
  "${ENVIRONMENT}/bin/python" -m github_workflow.probe "${RESULTS}" >"${RESULTS}/run.log" 2>&1
  echo "probe finished with status $?"
else
  echo "installing failed; see ${RESULTS}/install.log"
fi

# Results never go to the default branch directly: on it, or on no branch at all, they go
# to a branch of their own.
BRANCH="$(git branch --show-current)"
DEFAULT_BRANCH="$(git ls-remote --symref origin HEAD | sed -n 's|^ref: refs/heads/\(.*\)\tHEAD$|\1|p')"
if [ -z "${BRANCH}" ] || [ "${BRANCH}" = "${DEFAULT_BRANCH}" ]; then
  BRANCH="probe/results-${STAMP}"
  git switch --quiet --create "${BRANCH}"
fi
git add "${RESULTS}"
git commit --quiet --message "Record cloud probe results ${STAMP}" --message "Made with AI assistance"
if git push --quiet origin "HEAD:refs/heads/${BRANCH}"; then
  echo "pushed probe-results/${STAMP} to ${BRANCH}"
else
  echo "pushing failed; the results follow, to paste back by hand:"
  cat "${RESULTS}"/*.md "${RESULTS}"/*.log 2>/dev/null
fi
