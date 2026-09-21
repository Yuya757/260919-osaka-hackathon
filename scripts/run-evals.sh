#!/usr/bin/env bash
# Run the agent evaluation dataset and gate on the §13.2 acceptance criteria.
# Usage: ./scripts/run-evals.sh [--repeats N]
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root/services/agent"

export PYTHONPATH="src"
export AGENT_DEMO_MODE="${AGENT_DEMO_MODE:-true}"

# WSLには `python` が無いことが多い。CIのsetup-pythonは両方用意する。
python_bin="$(command -v python || command -v python3)"

"$python_bin" -m event_agent.evaluation.cli \
  --report "$repo_root/evals/results/latest.json" \
  --fail-under-gates \
  "$@"
