#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(CDPATH= cd -- "$script_dir/.." && pwd)"
if [[ -n "${TRADEPILOT_PYTHON:-}" ]]; then
  python_bin="$TRADEPILOT_PYTHON"
elif [[ -x "$project_root/.venv/bin/python" ]]; then
  python_bin="$project_root/.venv/bin/python"
elif [[ -x /home/wang/python_env/B1_RATE/bin/python ]]; then
  python_bin=/home/wang/python_env/B1_RATE/bin/python
else
  python_bin=python3
fi

cd "$project_root"
exec "$python_bin" -m python.run_backtest "$@"
