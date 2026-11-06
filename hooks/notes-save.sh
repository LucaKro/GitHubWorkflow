#!/usr/bin/env bash
# Stop and SessionEnd hook: saves the notes in CLAUDE.local.md when they were edited
# since they were loaded or last saved, so the edits outlive a cloud session's container.
#
# Never fails the turn or the session: a save that goes wrong is reported in the
# systemMessage the person is shown, and the edits stay in CLAUDE.local.md for the next
# try. Without a runtime it does nothing; the session start reports that.
set -uo pipefail

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PYTHON="${GITHUB_WORKFLOW_PYTHON:-${HOME}/.virtualenvs/githubworkflow-runtime/bin/python}"
if [ ! -x "${PYTHON}" ]; then
  exit 0
fi
# The plugin's own code goes first, so a plugin updated after the runtime was installed
# never runs code older than this hook; the runtime supplies the libraries.
export PYTHONPATH="${PLUGIN_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

ERRORS="$(mktemp)"
trap 'rm -f "${ERRORS}"' EXIT
if ! OUTPUT="$("${PYTHON}" -m github_workflow.notes.unsaved 2>"${ERRORS}")"; then
  text="github-workflow: notes not saved, kept in CLAUDE.local.md: $(tail -n 1 "${ERRORS}")"
  text="${text//\\/\\\\}"
  text="${text//\"/\\\"}"
  printf '{"systemMessage": "\\u001b[1;31m%s\\u001b[0m"}\n' "${text}"
  exit 0
fi
printf '%s' "${OUTPUT}"
