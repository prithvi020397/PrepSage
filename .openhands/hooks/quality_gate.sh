#!/bin/bash
cd "${OPENHANDS_PROJECT_DIR:-$PWD}"

if python3 -m unittest discover -q 2>&1; then
  exit 0
else
  echo '{"decision":"deny","reason":"Tests failed. Fix them before finishing."}'
  exit 2
fi
