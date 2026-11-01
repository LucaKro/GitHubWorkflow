#!/usr/bin/env bash
# SessionStart hook: writes the notes and this branch's progress into CLAUDE.local.md and
# answers with what was loaded, as JSON whose systemMessage the person is shown. Never
# fails the session: whatever goes wrong is reported in that message.
#
# Runs the package from the interpreter GITHUB_WORKFLOW_PYTHON names, by default the
# githubworkflow-runtime virtual environment, where the package is installed from main
# rather than from a checkout that may be on any branch.
set -uo pipefail

PYTHON="${GITHUB_WORKFLOW_PYTHON:-${HOME}/.virtualenvs/githubworkflow-runtime/bin/python}"

# Answers the hook with one line shown to the person in bold red, when the package cannot
# answer.
report() {
  local text="${1//\\/\\\\}"
  text="${text//\"/\\\"}"
  printf '{"systemMessage": "\\u001b[1;31m%s\\u001b[0m"}\n' "${text}"
}

if [ ! -x "${PYTHON}" ]; then
  report "github-workflow: notes not loaded: no interpreter at ${PYTHON}; set GITHUB_WORKFLOW_PYTHON to one with the package installed"
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
ERRORS="$(mktemp)"
if ! OUTPUT="$("${PYTHON}" -m github_workflow.session_start 2>"${ERRORS}")"; then
  report "github-workflow: notes not loaded: $(tail -n 1 "${ERRORS}")"
  rm -f "${ERRORS}"
  exit 0
fi
rm -f "${ERRORS}"
printf '%s\n' "${OUTPUT}"
