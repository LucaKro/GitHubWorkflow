#!/usr/bin/env bash
# SessionStart hook: installs the runtime from this plugin when the runtime in use was
# built from another (or none), writes the notes and this branch's progress into
# CLAUDE.local.md, and answers with what the session should know, as JSON whose
# systemMessage the person is shown. Never fails the session: whatever goes wrong is
# reported in that message.
#
# GITHUB_WORKFLOW_PYTHON names an interpreter to run instead, with the package already
# installed, and skips the install; development uses it.
set -uo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

# Answers the hook with one line shown to the person in bold red, when the package cannot
# answer.
report() {
  local text="${1//\\/\\\\}"
  text="${text//\"/\\\"}"
  printf '{"systemMessage": "\\u001b[1;31m%s\\u001b[0m"}\n' "${text}"
}

ERRORS="$(mktemp)"
trap 'rm -f "${ERRORS}"' EXIT

if [ -n "${GITHUB_WORKFLOW_PYTHON:-}" ]; then
  PYTHON="${GITHUB_WORKFLOW_PYTHON}"
else
  RUNTIME="${HOME}/.virtualenvs/githubworkflow-runtime"
  if ! GITHUB_WORKFLOW_INSTALLED="$(python3 -I "${PLUGIN_ROOT}/src/github_workflow/install.py" "${PLUGIN_ROOT}" "${RUNTIME}" 2>"${ERRORS}")"; then
    report "github-workflow: notes not loaded: $(tail -n 1 "${ERRORS}")"
    exit 0
  fi
  export GITHUB_WORKFLOW_INSTALLED
  PYTHON="${RUNTIME}/bin/python"
fi
if [ ! -x "${PYTHON}" ]; then
  report "github-workflow: notes not loaded: no interpreter at ${PYTHON}"
  exit 0
fi

# Tells the session's later commands where the plugin is.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  printf 'export GITHUB_WORKFLOW_PLUGIN_ROOT=%q\n' "${PLUGIN_ROOT}" >>"${CLAUDE_ENV_FILE}"
fi

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
if ! OUTPUT="$("${PYTHON}" -m github_workflow.session_start 2>"${ERRORS}")"; then
  report "github-workflow: notes not loaded: $(tail -n 1 "${ERRORS}")"
  exit 0
fi
printf '%s\n' "${OUTPUT}"
