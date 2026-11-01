#!/usr/bin/env bash
# PreToolUse hook: denies writing to git or GitHub directly, so every write goes through
# the workflow's commands; reading stays allowed. Prints the guard's denial, or nothing
# to leave the call to the usual permissions.
#
# Fails closed: when the guard cannot run or fails, the call is blocked (exit 2) with the
# reason, rather than let through unjudged.
#
# Runs the package from the interpreter GITHUB_WORKFLOW_PYTHON names, by default the
# githubworkflow virtual environment.
set -uo pipefail

PYTHON="${GITHUB_WORKFLOW_PYTHON:-${HOME}/.virtualenvs/githubworkflow/bin/python}"
if [ ! -x "${PYTHON}" ]; then
  echo "github-workflow guard: no interpreter at ${PYTHON}; set GITHUB_WORKFLOW_PYTHON to one with the package installed" >&2
  exit 2
fi

if ! OUTPUT="$("${PYTHON}" -m github_workflow.guard 2>&1)"; then
  echo "github-workflow guard failed, so the call is blocked: $(printf '%s\n' "${OUTPUT}" | tail -n 1)" >&2
  exit 2
fi
printf '%s' "${OUTPUT}"
