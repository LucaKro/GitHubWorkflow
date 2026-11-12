#!/usr/bin/env bash
# Sourced by the plugin's hooks and scripts: where the plugin and its runtime are, the
# interpreter they run the package with, and how a hook answers with one line the person
# is shown.
#
# GITHUB_WORKFLOW_PYTHON names an interpreter to run instead of the runtime's, with the
# package already installed; development uses it.

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RUNTIME="${HOME:-}/.virtualenvs/githubworkflow-runtime"
PYTHON="${GITHUB_WORKFLOW_PYTHON:-${RUNTIME}/bin/python}"
# The plugin's source directories, the workflow's and the domain model's, as a path.
PLUGIN_SOURCES="${PLUGIN_ROOT}/src:${PLUGIN_ROOT}/domain_model/src"

# Runs the installer with the system's interpreter on the plugin's own source, giving it
# the arguments given.
install_runtime() {
  python3 -I -c 'import sys; sys.path[:0] = sys.argv.pop(1).split(":"); from github_workflow.install import main; main()' "${PLUGIN_SOURCES}" "$@"
}

# Puts the plugin's own code first on the interpreter's path, so a plugin updated after
# the runtime was installed never runs code older than the hook; the runtime supplies
# the libraries.
use_plugin_source() {
  export PYTHONPATH="${PLUGIN_SOURCES}${PYTHONPATH:+:${PYTHONPATH}}"
}

# Answers the hook with one line shown to the person, bold in the colour the second
# argument names as an ANSI code: red (31) unless given.
say() {
  local text="${1//\\/\\\\}"
  text="${text//\"/\\\"}"
  printf '{"systemMessage": "\\u001b[1;%sm%s\\u001b[0m"}\n' "${2:-31}" "${text}"
}
