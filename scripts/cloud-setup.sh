#!/usr/bin/env bash
# Sets a Claude Code cloud environment up for the workflow: installs the runtime the hooks
# run (basstler-domain-model from GitHub, this checkout of GitHubWorkflow), and writes the
# plugin's hooks and the workflow's permission into the session's user settings, since a
# cloud session does not load plugins from a marketplace.
#
# Use it as the cloud environment's setup script, with GitHubWorkflow attached to the
# environment:
#   bash "$(find / -maxdepth 5 -type d -name GitHubWorkflow 2>/dev/null | head -n 1)/scripts/cloud-setup.sh"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="${HOME}/.virtualenvs/githubworkflow-runtime"
DOMAIN_MODEL="basstler-domain-model @ git+https://github.com/LucaKro/basstler_domain_model@main"

# The standard library's venv needs ensurepip, which some system Pythons lack; virtualenv
# brings its own pip.
if ! python3 -m venv "${RUNTIME}" >/dev/null 2>&1; then
  rm -rf "${RUNTIME}"
  virtualenv --quiet -p python3 "${RUNTIME}"
fi
"${RUNTIME}/bin/python" -m pip install --quiet "${DOMAIN_MODEL}"
"${RUNTIME}/bin/python" -m pip install --quiet "${ROOT}"
"${RUNTIME}/bin/python" -m github_workflow.cloud_setup "${ROOT}/plugin"
