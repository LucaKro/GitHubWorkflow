#!/usr/bin/env bash
# Written by github-workflow's session start, and into every clone its clone command
# makes. Checks a push run from a Claude Code session, however it was started, against
# the workflow's rules: only to the owner's repositories, and never to the default
# branch. A push from anywhere else, where __MARKER_VARIABLE__ is unset, passes
# unchecked.
if [ -z "${__MARKER_VARIABLE__:-}" ]; then
  exit 0
fi
exec "__PYTHON__" -m __MODULE__ "$@"
