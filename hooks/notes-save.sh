#!/usr/bin/env bash
# Stop and SessionEnd hook: saves the notes in CLAUDE.local.md when they were edited
# since they were loaded or last saved, so the edits outlive a cloud session's container.
#
# Never fails the turn or the session: a save that goes wrong is reported in the
# systemMessage the person is shown, and the edits stay in CLAUDE.local.md for the next
# try. Without a runtime it does nothing; the session start reports that.
set -uo pipefail

source "$(dirname "$0")/runtime.sh"
if [ ! -x "${PYTHON}" ]; then
  exit 0
fi
use_plugin_source
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

ERRORS="$(mktemp)"
trap 'rm -f "${ERRORS}"' EXIT
if ! OUTPUT="$("${PYTHON}" -m github_workflow.notes.unsaved 2>"${ERRORS}")"; then
  say "github-workflow: notes not saved, kept in CLAUDE.local.md: $(tail -n 1 "${ERRORS}")"
  exit 0
fi
printf '%s' "${OUTPUT}"
