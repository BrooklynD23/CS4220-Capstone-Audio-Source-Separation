#!/usr/bin/env bash
set -e
exec python3 "$(dirname "$0")/launch.py" "$@"
