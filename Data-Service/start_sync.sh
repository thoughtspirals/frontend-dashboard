#!/bin/bash
#
# Start script for Data-Service Sync
# Syncs polled values from vista-backend to Data-Service via IPC
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$SCRIPT_DIR/venv"
PYTHON="$VENV_PATH/bin/python"
SYNC_RUNNER="$SCRIPT_DIR/sync_runner.py"
PID_FILE="$SCRIPT_DIR/dataservice-sync.pid"
LOG_FILE="$SCRIPT_DIR/logs/dataservice-sync.log"

# Create logs directory if it doesn't exist
mkdir -p "$SCRIPT_DIR/logs"

# Check if virtual environment exists
if [ ! -d "$VENV_PATH" ]; then
    echo "Error: Virtual environment not found at $VENV_PATH"
    echo "Please run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Data-Service sync is already running (PID: $OLD_PID)"
        exit 1
    else
        echo "Removing stale PID file"
        rm -f "$PID_FILE"
    fi
fi

# Start the sync service
echo "Starting Data-Service Sync..."
echo "Log file: $LOG_FILE"

nohup "$PYTHON" "$SYNC_RUNNER" \
    --socket-path /tmp/dataservice.sock \
    --interval 1.0 \
    --stats-interval 300 \
    >> "$LOG_FILE" 2>&1 &

SYNC_PID=$!
echo $SYNC_PID > "$PID_FILE"

# Wait a moment and check if it's still running
sleep 2
if ps -p "$SYNC_PID" > /dev/null 2>&1; then
    echo "✅ Data-Service Sync started successfully (PID: $SYNC_PID)"
    echo "   Monitor logs: tail -f $LOG_FILE"
    echo "   Stop service: ./stop_sync.sh"
else
    echo "❌ Failed to start Data-Service Sync"
    echo "   Check logs: cat $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
