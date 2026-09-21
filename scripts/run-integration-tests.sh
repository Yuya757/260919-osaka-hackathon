#!/usr/bin/env bash
# Run the store contract suite against the Firestore Emulator (§13.3 Integration).
#
# `pytest` on its own skips every Firestore test, because
# FIRESTORE_EMULATOR_HOST is unset. This script supplies the emulator and runs
# the whole suite, so the emulator-backed tests run alongside the unit tests
# rather than in a separate world.
#
# Requires Java (the emulator is a JVM process) and network access on first run,
# when npx downloads firebase-tools.
#
# Usage: ./scripts/run-integration-tests.sh [extra pytest args]
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

# Emulator-only project id. It must not match a real project, so that a
# misconfigured run cannot reach production data.
project="osaka-hackathon-test"
firebase_tools_version="14.16.0"

if ! command -v java >/dev/null 2>&1; then
  echo "java not found. The Firestore Emulator needs a JRE (e.g. apt install default-jre)." >&2
  exit 1
fi

npx --yes "firebase-tools@${firebase_tools_version}" emulators:exec \
  --only firestore \
  --project "$project" \
  "cd services/agent && PYTHONPATH=src AGENT_DEMO_MODE=true pytest -q $*"
