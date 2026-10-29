#!/bin/bash
# macOS launcher (double-click in Finder). Run setup.command once first.
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
  .venv/bin/python run.py "$@" &
  disown
else
  echo "Run setup.command first."
  read -r
fi
