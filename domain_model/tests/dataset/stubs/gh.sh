#!/bin/sh
# Stands in for `gh` when asked for the logged-in token: prints STUB_TOKEN.
if [ "$1" = "auth" ] && [ "$2" = "token" ]; then echo "${STUB_TOKEN}"; exit 0; fi
exit 64
