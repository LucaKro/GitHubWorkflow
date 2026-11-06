#!/usr/bin/env bash
# SessionStart hook, and UserPromptSubmit hook for a session whose start it missed.
#
# Installs the runtime from this plugin when the runtime in use was built from another
# (or none), writes the notes and this branch's progress into CLAUDE.local.md, and
# answers with what the session should know, as JSON whose systemMessage the person is
# shown. Never fails the session: whatever goes wrong is reported in that message.
#
# Reports once per session: a plugin synced from the claude.ai account can arrive after
# the session started, and a session start that runs too long is cut off, so the first
# prompt reports when the start did not. Run with "UserPromptSubmit" as its argument for
# that, it does nothing once the session was reported.
#
# The session start never installs itself: it starts the install in a process of its own
# and leaves the report to the first prompt, which waits for that install.
#
# GITHUB_WORKFLOW_PYTHON names an interpreter to run instead, with the package already
# installed, and skips the install; development uses it.
set -uo pipefail

EVENT="${1:-SessionStart}"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
SESSION="$(python3 -I -c 'import json, sys; print(json.load(sys.stdin).get("session_id", ""))' 2>/dev/null)"
MARKERS="${TMPDIR:-/tmp}/github-workflow-sessions"
REPORTED="${MARKERS}/${SESSION:-unknown}"

if [ "${EVENT}" != "SessionStart" ] && { [ -z "${SESSION}" ] || [ -e "${REPORTED}" ]; }; then
  exit 0
fi

# A new session forgets the sessions over for a week.
if [ "${EVENT}" = "SessionStart" ] && [ -d "${MARKERS}" ]; then
  find "${MARKERS}" -type f -mtime +7 -delete 2>/dev/null
fi

# Records that the session got its report.
reported() {
  mkdir -p "$(dirname "${REPORTED}")" && touch "${REPORTED}"
}

# Answers the hook with one line shown to the person, bold in the colour the second
# argument names as an ANSI code: red (31) unless given.
say() {
  local text="${1//\\/\\\\}"
  text="${text//\"/\\\"}"
  printf '{"systemMessage": "\\u001b[1;%sm%s\\u001b[0m"}\n' "${2:-31}" "${text}"
}

# Answers the hook with what went wrong, which counts as the session's report.
report() {
  reported
  say "$1"
}

# Tells the session's later commands where the plugin and its data are.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  printf 'export GITHUB_WORKFLOW_PLUGIN_ROOT=%q\n' "${PLUGIN_ROOT}" >>"${CLAUDE_ENV_FILE}"
  if [ -n "${CLAUDE_PLUGIN_DATA:-}" ]; then
    printf 'export GITHUB_WORKFLOW_PLUGIN_DATA=%q\n' "${CLAUDE_PLUGIN_DATA}" >>"${CLAUDE_ENV_FILE}"
  fi
fi

ERRORS="$(mktemp)"
trap 'rm -f "${ERRORS}"' EXIT

if [ -n "${GITHUB_WORKFLOW_PYTHON:-}" ]; then
  PYTHON="${GITHUB_WORKFLOW_PYTHON}"
else
  RUNTIME="${HOME}/.virtualenvs/githubworkflow-runtime"
  INSTALL=(python3 -I "${PLUGIN_ROOT}/src/github_workflow/install.py")
  if [ "${EVENT}" = "SessionStart" ]; then
    INSTALL+=(--background)
  fi
  if ! GITHUB_WORKFLOW_INSTALLED="$("${INSTALL[@]}" "${PLUGIN_ROOT}" "${RUNTIME}" 2>"${ERRORS}")"; then
    report "github-workflow: notes not loaded: $(tail -n 1 "${ERRORS}")"
    exit 0
  fi
  if [ "${EVENT}" = "SessionStart" ] && [ -n "${GITHUB_WORKFLOW_INSTALLED}" ]; then
    say "${GITHUB_WORKFLOW_INSTALLED}; the notes follow with the first prompt" 36
    exit 0
  fi
  export GITHUB_WORKFLOW_INSTALLED
  PYTHON="${RUNTIME}/bin/python"
fi
if [ ! -x "${PYTHON}" ]; then
  report "github-workflow: notes not loaded: no interpreter at ${PYTHON}"
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
if ! OUTPUT="$("${PYTHON}" -m github_workflow.session_start "${EVENT}" 2>"${ERRORS}")"; then
  report "github-workflow: notes not loaded: $(tail -n 1 "${ERRORS}")"
  exit 0
fi
reported
printf '%s\n' "${OUTPUT}"
