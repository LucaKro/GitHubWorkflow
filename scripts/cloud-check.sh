#!/usr/bin/env bash
# Checks that this cloud session runs the workflow, and publishes what it found to the
# github-workflow/probe-results branch for reading elsewhere.
#
# Checks the runtime, that the session loaded the plugin, the guard (denies a commit, lets a
# log through), the session start's answer, and one round through the workflow's
# commands in the checkout it is run in: a branch, a commit, a push, a draft pull
# request, a rewritten description and a cleanup. The draft pull request is left open
# for the person to close; its branch is then ready for deletion.
#
# Usage, inside the checkout of a repository of the owner's, in a session that loaded the
# plugin (its session start sets GITHUB_WORKFLOW_PLUGIN_ROOT):
#   bash "${GITHUB_WORKFLOW_PLUGIN_ROOT}/scripts/cloud-check.sh"
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${GITHUB_WORKFLOW_PYTHON:-${HOME}/.virtualenvs/githubworkflow-runtime/bin/python}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RESULTS="$(mktemp -d)/cloud-check-${STAMP}"
REPORT="${RESULTS}/report.md"
mkdir -p "${RESULTS}"
printf '# Cloud check %s\n\n| check | ok | last line |\n|---|---|---|\n' "${STAMP}" >"${REPORT}"

# Runs a command, recording whether it succeeded and its last line of output.
check() {
  local name="$1"
  shift
  local output status
  output="$("$@" 2>&1)"
  status=$?
  printf '| %s | %s | %s |\n' "${name}" "$([ "${status}" -eq 0 ] && echo yes || echo NO)" \
    "$(printf '%s' "${output}" | tail -n 1 | tr '|\n' '/ ')" >>"${REPORT}"
  printf '%s' "${output}"
  return "${status}"
}

# Feeds the guard one Bash command, as the hook would.
guard() {
  printf '{"tool_name": "Bash", "tool_input": {"command": "%s"}}' "$1" |
    "${ROOT}/hooks/guard.sh"
}

check "runtime runs" "${PYTHON}" -m github_workflow --help >/dev/null
check "plugin loaded by the session" test -n "${GITHUB_WORKFLOW_PLUGIN_ROOT:-}"
check "guard denies a commit" bash -c "$(declare -f guard); ROOT='${ROOT}'; guard 'git commit -m x' | grep -q deny"
check "guard lets a log through" bash -c "$(declare -f guard); ROOT='${ROOT}'; [ -z \"\$(guard 'git log -1')\" ]"
check "session start answers" bash -c "CLAUDE_PROJECT_DIR='${PWD}' '${ROOT}/hooks/session-start.sh' | tee '${RESULTS}/session-start.json' | grep -q systemMessage"

START_BRANCH="$(git branch --show-current)"
BRANCH="cloud-check/${STAMP}"
FILE="cloud-check-${STAMP}.md"
printf 'Written by the cloud check %s; never merged.\n' "${STAMP}" >"${FILE}"
printf 'Opened by the cloud check %s; close it when read.\n' "${STAMP}" >"${RESULTS}/draft.md"
check "branch start" "${PYTHON}" -m github_workflow branch start "${BRANCH}" &&
  check "commit" "${PYTHON}" -m github_workflow commit -m "Cloud check ${STAMP}" "${FILE}" &&
  check "push" "${PYTHON}" -m github_workflow push &&
  DRAFT="$(check "draft" "${PYTHON}" -m github_workflow draft --title "Cloud check ${STAMP} (close me)" --body-file "${RESULTS}/draft.md")" &&
  NUMBER="$(printf '%s' "${DRAFT}" | sed -n 's/.*draft #\([0-9]*\).*/\1/p')" &&
  check "describe" "${PYTHON}" -m github_workflow describe "${NUMBER}" --body-file "${RESULTS}/draft.md"
check "back to ${START_BRANCH}" "${PYTHON}" -m github_workflow branch switch "${START_BRANCH}"
check "cleanup runs" "${PYTHON}" -m github_workflow cleanup
rm -f "${FILE}"

cat "${REPORT}"
"${PYTHON}" -m github_workflow.probe.publish "${RESULTS}"
