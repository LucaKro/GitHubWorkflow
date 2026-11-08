#!/usr/bin/env bash
# PreToolUse hook: denies writing to git or GitHub directly, so every write goes through
# the workflow's commands; reading stays allowed. Prints the guard's denial, its request
# that the person confirm a workflow command needing their go-ahead, or nothing to leave
# the call to the usual permissions.
#
# When the guard cannot run from its runtime - the runtime missing, or the guard
# failing - the guard runs again from the plugin's source on the standard library alone,
# judging the call as usual. When that fails too, the coarse guard stands in: it denies
# every call that could reach git or GitHub and lets every other call run. Only when that
# cannot run either is the call blocked (exit 2) with the reason.
#
# Runs the package from the runtime, which the session start installs from this plugin -
# or this guard, when the session start never ran.
set -uo pipefail

INPUT="$(cat)"
source "$(dirname "$0")/runtime.sh"

# Decides the call with the guard run from the plugin's source by the system's Python on
# the standard library alone, the runtime having failed for the reason given; with the
# coarse guard when that fails too.
from_source() {
  local decided
  if decided="$(printf '%s' "${INPUT}" | python3 -I -S -c 'import sys; sys.path[:0] = sys.argv[1].split(":"); from github_workflow.guard import main; main()' "${PLUGIN_SOURCES}" 2>/dev/null)"; then
    printf '%s' "${decided}"
    exit 0
  fi
  coarse "$1"
}

# Decides the call with the coarse guard, the guard having failed for the reason given.
coarse() {
  local reason="$1" decided errors
  errors="$(mktemp)"
  if ! decided="$(printf '%s' "${INPUT}" | python3 -I -c 'import sys; sys.path[:0] = sys.argv[1].split(":"); from github_workflow.coarse_guard import main; main(sys.argv[2])' "${PLUGIN_SOURCES}" "${reason}" 2>"${errors}")"; then
    echo "github-workflow guard: ${reason}, and the coarse guard failed too, so the call is blocked: $(tail -n 1 "${errors}")" >&2
    rm -f "${errors}"
    exit 2
  fi
  rm -f "${errors}"
  printf '%s' "${decided}"
  exit 0
}

# A plugin synced from the claude.ai account can arrive after the session started, and
# with it this guard before the runtime it runs: install the runtime first then.
if [ -z "${GITHUB_WORKFLOW_PYTHON:-}" ] && [ ! -x "${PYTHON}" ] &&
  ! INSTALLED="$(python3 -I "${INSTALLER}" "${PLUGIN_ROOT}" "${RUNTIME}" 2>&1)"; then
  from_source "could not install the runtime: $(printf '%s\n' "${INSTALLED}" | tail -n 1)"
fi
if [ ! -x "${PYTHON}" ]; then
  from_source "no interpreter at ${PYTHON}; set GITHUB_WORKFLOW_PYTHON to one with the package installed"
fi

use_plugin_source
if ! OUTPUT="$(printf '%s' "${INPUT}" | "${PYTHON}" -m github_workflow.guard 2>&1)"; then
  from_source "the guard failed: $(printf '%s\n' "${OUTPUT}" | tail -n 1)"
fi
printf '%s' "${OUTPUT}"
