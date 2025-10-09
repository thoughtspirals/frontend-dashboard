#!/bin/bash
#
# Stop script for Data-Service Sync
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/dataservice-sync.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "Data-Service Sync is not running (no PID file found)"
    exit 0
fi

PID=$(cat "$PID_FILE")

if ! ps -p "$PID" > /dev/null 2>&1; then
    echo "Data-Service Sync is not running (stale PID file)"
    rm -f "$PID_FILE"
    exit 0
fi

echo "Stopping Data-Service Sync (PID: $PID)..."
kill -TERM "$PID"

# Wait for graceful shutdown
TIMEOUT=10
COUNT=0
while ps -p "$PID" > /dev/null 2>&1 && [ $COUNT -lt $TIMEOUT ]; do
    sleep 1
    COUNT=$((COUNT + 1))
    echo -n "."
done
echo ""

if ps -p "$PID" > /dev/null 2>&1; then
    echo "Process didn't stop gracefully, forcing shutdown..."
    kill -KILL "$PID"
    sleep 1
fi

rm -f "$PID_FILE"
echo "✅ Data-Service Sync stopped"
