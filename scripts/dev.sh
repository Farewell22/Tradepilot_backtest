#!/bin/bash
# Start Python scoring (:8081) + Python backtest dashboard (:8082) + Vue (:3000)
set -e

echo "Starting TradePilot dev environment..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

kill_port() {
  local port=$1
  local pids
  pids=$(lsof -ti :"$port" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "[Cleanup] Killing existing process(es) on :$port -> $pids"
    echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
}

kill_port 8081
kill_port 8082
kill_port 3000
sleep 0.5

VENV_PATH="$HOME/python_env/B1_RATE"
if [ ! -f "$VENV_PATH/bin/activate" ]; then
  echo "[ERROR] Python venv not found at $VENV_PATH"
  exit 1
fi

echo "[Python] Starting scoring service on :8081..."
source "$VENV_PATH/bin/activate"
cd "$PROJECT_DIR/python"
nohup uvicorn main:app --host 0.0.0.0 --port 8081 --reload > /tmp/scoring-service.log 2>&1 &
SCORING_PID=$!

echo "[Python] Starting backtest dashboard on :8082..."
cd "$PROJECT_DIR"
nohup uvicorn python.backtest_dashboard.api:app --host 0.0.0.0 --port 8082 --reload > /tmp/backtest-service.log 2>&1 &
BT_PID=$!
deactivate

echo "[Vue] Starting on :3000..."
cd "$PROJECT_DIR/web" && nohup npx vite > /tmp/vue-service.log 2>&1 &
VUE_PID=$!

trap "kill $SCORING_PID $BT_PID $VUE_PID 2>/dev/null" EXIT

echo ""
echo "TradePilot running:"
echo "  Frontend:           http://localhost:3000"
echo "  Scoring service:    http://localhost:8081"
echo "  Backtest dashboard: http://localhost:8082"
echo ""
echo "  Logs:"
echo "    /tmp/scoring-service.log"
echo "    /tmp/backtest-service.log"
echo "    /tmp/vue-service.log"
echo ""
echo "  Press Ctrl+C to stop"
echo ""

wait
