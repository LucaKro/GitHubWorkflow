#!/usr/bin/env bash
# Stands in for a build step that fails and says why on its error output.
echo "progress the step printed"
echo "the reason the step failed" >&2
exit 1
