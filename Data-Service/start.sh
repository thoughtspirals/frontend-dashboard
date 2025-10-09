#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/venv"
PYTHON_BIN="$VENV_DIR/bin/python3.12"
UVICORN_BIN="$VENV_DIR/bin/uvicorn"

PID_FILE="$ROOT_DIR/dataservice.pid"
SYNC_PID_FILE="$ROOT_DIR/dataservice-sync.pid"
LOG_FILE="$ROOT_DIR/logs/dataservice.log"
SYNC_LOG_FILE="$ROOT_DIR/logs/dataservice-sync.log"

# Create logs directory if it doesn't exist
mkdir -p "$ROOT_DIR/logs"

# Function to forcefully stop DataService AND Sync
force_stop_all() {
    echo "==> Forcefully stopping DataService and Sync services"
    
    # Stop DataService
    if [ -f "$PID_FILE" ]; then
        OLD_PID="$(cat "$PID_FILE" || true)"
        if [ -n "$OLD_PID" ] && ps -p "$OLD_PID" >/dev/null 2>&1; then
            echo "Killing DataService PID $OLD_PID"
            kill -9 "$OLD_PID" >/dev/null 2>&1 || true
        fi
        rm -f "$PID_FILE"
    fi
    
    # Stop Sync service
    if [ -f "$SYNC_PID_FILE" ]; then
        SYNC_PID="$(cat "$SYNC_PID_FILE" || true)"
        if [ -n "$SYNC_PID" ] && ps -p "$SYNC_PID" >/dev/null 2>&1; then
            echo "Killing Sync service PID $SYNC_PID"
            kill -9 "$SYNC_PID" >/dev/null 2>&1 || true
        fi
        rm -f "$SYNC_PID_FILE"
    fi
    
    # Kill all uvicorn processes
    echo "Killing all uvicorn processes..."
    pkill -f "uvicorn.*dataservice" >/dev/null 2>&1 || true
    
    # Kill sync_runner processes
    echo "Killing sync_runner processes..."
    pkill -f "sync_runner" >/dev/null 2>&1 || true
    
    # Kill all python processes running dataservice
    echo "Killing all dataservice python processes..."
    pkill -f "python.*dataservice" >/dev/null 2>&1 || true
    
    # Kill processes using ports 8080, 5020, 4840, 2404
    echo "Killing processes on service ports..."
    for port in 8080 5020 4840 2404; do
        if command -v lsof >/dev/null 2>&1; then
            lsof -ti:$port | xargs -r kill -9 >/dev/null 2>&1 || true
        fi
    done
    
    # Kill any remaining processes with dataservice in the command line
    echo "Killing any remaining dataservice processes..."
    ps aux | grep -i dataservice | grep -v grep | awk '{print $2}' | xargs -r kill -9 >/dev/null 2>&1 || true
    
    echo "==> Force stop complete"
}

# Function to gracefully stop DataService AND Sync
graceful_stop_all() {
    echo "==> Gracefully stopping DataService and Sync services"
    
    # Stop DataService
    if [ -f "$PID_FILE" ]; then
        OLD_PID="$(cat "$PID_FILE" || true)"
        if [ -n "$OLD_PID" ] && ps -p "$OLD_PID" >/dev/null 2>&1; then
            echo "Found running DataService PID $OLD_PID, sending SIGTERM"
            kill "$OLD_PID" >/dev/null 2>&1 || true
            # wait up to 10s
            for i in {1..10}; do
                if ps -p "$OLD_PID" >/dev/null 2>&1; then
                    sleep 1
                else
                    break
                fi
            done
            if ps -p "$OLD_PID" >/dev/null 2>&1; then
                echo "DataService $OLD_PID did not exit, sending SIGKILL"
                kill -9 "$OLD_PID" >/dev/null 2>&1 || true
            fi
        fi
        rm -f "$PID_FILE"
    fi
    
    # Stop Sync service
    if [ -f "$SYNC_PID_FILE" ]; then
        SYNC_PID="$(cat "$SYNC_PID_FILE" || true)"
        if [ -n "$SYNC_PID" ] && ps -p "$SYNC_PID" >/dev/null 2>&1; then
            echo "Found running Sync service PID $SYNC_PID, sending SIGTERM"
            kill "$SYNC_PID" >/dev/null 2>&1 || true
            # wait up to 5s
            for i in {1..5}; do
                if ps -p "$SYNC_PID" >/dev/null 2>&1; then
                    sleep 1
                else
                    break
                fi
            done
            if ps -p "$SYNC_PID" >/dev/null 2>&1; then
                echo "Sync service $SYNC_PID did not exit, sending SIGKILL"
                kill -9 "$SYNC_PID" >/dev/null 2>&1 || true
            fi
        fi
        rm -f "$SYNC_PID_FILE"
    fi
}

# Check for command line arguments
if [ "${1:-}" = "stop" ]; then
    graceful_stop_all
    exit 0
elif [ "${1:-}" = "force-stop" ]; then
    force_stop_all
    exit 0
elif [ "${1:-}" = "restart" ]; then
    echo "==> Restarting DataService and Sync"
    graceful_stop_all
    sleep 2
    # Continue with startup below
elif [ "${1:-}" = "force-restart" ]; then
    echo "==> Force restarting DataService and Sync"
    force_stop_all
    sleep 2
    # Continue with startup below
fi

# Default behavior: start both services
echo "==> Stopping any existing DataService and Sync instances"
graceful_stop_all

echo "==> Preparing virtual environment"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo "==> Installing requirements"
pip install -r "$ROOT_DIR/requirements.txt" >/dev/null

echo "==> Ensuring low-port capability (optional)"
if command -v setcap >/dev/null 2>&1; then
  if [ -x "$PYTHON_BIN" ]; then
    sudo -n setcap 'cap_net_bind_service=+ep' "$PYTHON_BIN" 2>/dev/null || true
  fi
fi

echo "==> Starting DataService (FastAPI/uvicorn)"
cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR/src:${PYTHONPATH:-}"
nohup "$UVICORN_BIN" dataservice.server:app --host 0.0.0.0 --port 8080 > "$LOG_FILE" 2>&1 &
DATASERVICE_PID=$!
echo $DATASERVICE_PID > "$PID_FILE"

echo "==> Waiting for DataService health"
for i in {1..30}; do
  if curl -sf http://127.0.0.1:8080/health >/dev/null; then
    break
  fi
  sleep 1
done

if ! curl -sf http://127.0.0.1:8080/health >/dev/null; then
  echo "DataService failed to report healthy. See $LOG_FILE"
  exit 1
fi

echo "==> DataService is up (PID $DATASERVICE_PID)"

# Start the sync service
echo "==> Starting Data Sync service"
SYNC_RUNNER="$ROOT_DIR/sync_runner.py"

if [ -f "$SYNC_RUNNER" ]; then
    nohup "$PYTHON_BIN" "$SYNC_RUNNER" \
        --socket-path /tmp/dataservice.sock \
        --interval 1.0 \
        --stats-interval 300 \
        >> "$SYNC_LOG_FILE" 2>&1 &
    
    SYNC_PID=$!
    echo $SYNC_PID > "$SYNC_PID_FILE"
    
    # Wait a moment and check if sync is still running
    sleep 2
    if ps -p "$SYNC_PID" >/dev/null 2>&1; then
        echo "==> Data Sync service started successfully (PID: $SYNC_PID)"
    else
        echo "❌ Failed to start Data Sync service"
        echo "   Check logs: cat $SYNC_LOG_FILE"
        # Don't exit, DataService can still work without sync
    fi
else
    echo "⚠️  sync_runner.py not found, skipping sync service"
fi

echo "==> All services started successfully!"
echo "-- Stats:"
curl -s http://127.0.0.1:8080/stats || true
echo
echo "-- Data snapshot (first keys):"
curl -s http://127.0.0.1:8080/data | head -c 500; echo

echo
echo "=== Service Information ==="
echo "DataService PID: $DATASERVICE_PID"
if [ -f "$SYNC_PID_FILE" ]; then
    echo "Sync Service PID: $(cat $SYNC_PID_FILE 2>/dev/null || echo 'N/A')"
fi
echo "DataService Logs: tail -f $LOG_FILE"
echo "Sync Logs: tail -f $SYNC_LOG_FILE"
echo "Stop services: ./start.sh stop"
