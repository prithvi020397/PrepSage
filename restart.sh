#!/usr/bin/env bash
# Kill anything bound to port 5050, then start the app as a single clean process
# (no Flask reloader fork, so pgrep won't multiply). Usage: ./restart.sh
set -u
cd "$(dirname "$0")"

PORT=5050
if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -ti :"$PORT" 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "Killing stale process(es) on port $PORT: $PIDS"
    kill -9 $PIDS 2>/dev/null || true
    sleep 1
  fi
fi

# belt-and-suspenders: also kill any lingering app.py by name
for p in $(pgrep -f "app.py" 2>/dev/null); do
  kill -9 "$p" 2>/dev/null || true
done
sleep 1

export FLASK_DEBUG=0
echo "Starting server on http://127.0.0.1:$PORT ..."
exec python3 -c "from app import app; app.run(host='127.0.0.1', port=$PORT, debug=False, use_reloader=False)"
