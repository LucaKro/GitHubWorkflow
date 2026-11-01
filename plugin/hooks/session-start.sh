#!/usr/bin/env bash
# SessionStart hook: writes the notes and this branch's progress into CLAUDE.local.md and
# prints one line saying what was loaded. Never fails the session: whatever goes wrong is
# reported in that one line.
#
# Runs the package from the interpreter GITHUB_WORKFLOW_PYTHON names, by default the
# githubworkflow virtual environment.
set -uo pipefail

PYTHON="${GITHUB_WORKFLOW_PYTHON:-${HOME}/.virtualenvs/githubworkflow/bin/python}"
if [ ! -x "${PYTHON}" ]; then
  echo "github-workflow: notes not loaded: no interpreter at ${PYTHON}; set GITHUB_WORKFLOW_PYTHON to one with the package installed"
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
if ! OUTPUT="$("${PYTHON}" -m github_workflow.session_start 2>&1)"; then
  echo "github-workflow: notes not loaded: $(printf '%s\n' "${OUTPUT}" | tail -n 1)"
  exit 0
fi
echo "${OUTPUT}"
