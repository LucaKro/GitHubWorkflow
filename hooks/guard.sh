#!/usr/bin/env bash
# PreToolUse hook: denies writing to git or GitHub directly, so every write goes through
# the workflow's commands; reading stays allowed. Prints the guard's denial, its request
# that the person confirm a workflow command needing their go-ahead, or nothing to leave
# the call to the usual permissions.
#
# Fails closed: when the guard cannot run or fails, the call is blocked (exit 2) with the
# reason, rather than let through unjudged.
#
# Runs the package from the interpreter GITHUB_WORKFLOW_PYTHON names, by default the
# githubworkflow-runtime virtual environment, which the session start installs from this
# plugin - or this guard, when the session start never ran.
set -uo pipefail

INPUT="$(cat)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

# A plugin synced from the claude.ai account can arrive after the session started, and
# with it this guard before the runtime it runs: install the runtime first then.
if [ -n "${GITHUB_WORKFLOW_PYTHON:-}" ]; then
  PYTHON="${GITHUB_WORKFLOW_PYTHON}"
else
  RUNTIME="${HOME}/.virtualenvs/githubworkflow-runtime"
  PYTHON="${RUNTIME}/bin/python"
  if [ ! -x "${PYTHON}" ] &&
    ! INSTALLED="$(python3 -I "${PLUGIN_ROOT}/src/github_workflow/install.py" "${PLUGIN_ROOT}" "${RUNTIME}" 2>&1)"; then
    echo "github-workflow guard: could not install the runtime, so the call is blocked: $(printf '%s\n' "${INSTALLED}" | tail -n 1)" >&2
    exit 2
  fi
fi
if [ ! -x "${PYTHON}" ]; then
  echo "github-workflow guard: no interpreter at ${PYTHON}; set GITHUB_WORKFLOW_PYTHON to one with the package installed" >&2
  exit 2
fi

if ! OUTPUT="$(printf '%s' "${INPUT}" | "${PYTHON}" -m github_workflow.guard 2>&1)"; then
  echo "github-workflow guard failed, so the call is blocked: $(printf '%s\n' "${OUTPUT}" | tail -n 1)" >&2
  exit 2
fi
printf '%s' "${OUTPUT}"
