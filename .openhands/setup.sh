#!/bin/bash
# pawscode setup — runs every time OpenHands begins working with this repo

cd "${OPENHANDS_PROJECT_DIR:-$PWD}"

# Load env vars from .env if present
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Install Python dependencies
if [ -f requirements.txt ]; then
  pip install -q -r requirements.txt
fi
